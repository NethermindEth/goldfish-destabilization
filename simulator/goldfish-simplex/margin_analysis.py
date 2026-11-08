"""Test the liveness-margin prediction on never-healing 75/25 runs (partition_run.py --events).

Prediction (inference from the spec's one-slot inclusion window for last-slot votes):
with only the 75% majority voting, a round's height outcome (justify, or finalize by
piggyback) succeeds iff the next round's first slot has a block on the majority chain.

For every round boundary s after the first majority-only round, on majority node 0:
  missed   = node 0's head at the end of slot s is older than s (no block at s)
  progress = (height, justified slot, finalized slot) at the end of slot s+1 differs from
             the end of slot s-1
and the 2x2 table of (missed, progress) is printed. The prediction says all rounds fall on
the diagonal: (missed, no progress) or (not missed, progress).

Usage: python margin_analysis.py results/margin/seed*.events.json
"""

import json
import sys
from collections import Counter


def rounds(path):
    with open(path) as fh:
        d = json.load(fh)
    spr, start, end = d["slots_per_round"], d["config"]["start"], d["config"]["start"] + d["config"]["slots_down"]
    node = next(i for i, g in enumerate(d["group_of"].values() if isinstance(d["group_of"], dict) else d["group_of"]) if g == 0)
    by_slot = {s["slot"]: s["nodes"][node] for s in d["states"]}
    key = lambda n: (n["chain_height"], n["justified_slot"], n["finalized_slot"])
    out = []
    first = (start // spr + 1) * spr + spr  # boundary after the first full majority-only round
    for s in range(first, min(end, max(by_slot)), spr):
        if s - 1 not in by_slot or s + 1 not in by_slot:
            continue
        missed = by_slot[s]["head_slot"] != s
        progress = key(by_slot[s + 1]) != key(by_slot[s - 1])
        out.append((s, missed, progress))
    return out


def main(paths):
    table, per_run = Counter(), []
    for p in paths:
        r = rounds(p)
        table.update((m, g) for _, m, g in r)
        off = [s for s, m, g in r if m == g]  # off-diagonal: missed and progressed, or neither
        per_run.append((p.split("/")[-1], len(r), sum(m for _, m, _ in r), off))
    print("rounds by (round-start block missed?, outcome progressed?):")
    for m in (False, True):
        print(f"  missed={m!s:5}  progress: {table[(m, True)]:3d}   no progress: {table[(m, False)]:3d}")
    n = sum(table.values())
    agree = table[(False, True)] + table[(True, False)]
    print(f"prediction holds in {agree}/{n} rounds")
    print(f"round-start miss rate: {sum(table[(True, g)] for g in (True, False)) / max(n, 1):.2f} (expected ~0.25)")
    for name, k, misses, off in per_run:
        print(f"  {name}: {k} rounds, {misses} missed starts" + (f", COUNTEREXAMPLES at slots {off}" if off else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
