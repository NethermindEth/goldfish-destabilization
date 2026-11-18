"""A blocks-only fault timed on the proposer schedule.

window_sweep.py suggests that the cut-off half loses the chain when, during the fault, no proposer of
its own comes for long enough: its own proposals still reach the other half and renew its locks.
The proposer schedule is known in advance, so an attacker can time the fault. For each schedule and
lock window k, this sweep finds the first run of exactly r consecutive slots in [48, 160) whose
proposer is not in A (the first half of the 8 nodes, all online), and withholds the blocks from A
from `lead` slots before the run to `tail` slots after it. The fault then lasts lead + r + tail
slots. Per run: lost_pre counts the confirmed tips first seen before the fault and later orphaned.

Run:  python timed_sweep.py [--out data/sweeps/timed.json] [--seeds 64] [--quick]
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor

NODES, VALIDATORS, AFTER = 8, 64, 30
SCAN = (48, 160)


def node_of():
    from model import Params
    from sim import World
    w = World(Params(n=VALIDATORS, seed=0), NODES)
    return {v: n.id for n in w.nodes for v in n.validators}


def find_run(P, owner, A, r):
    """First slot of a run of exactly r slots without an A proposer, in SCAN; None if absent."""
    s = SCAN[0]
    while s < SCAN[1]:
        if owner[P.proposer(s)] in A:
            s += 1
            continue
        e = s
        while e < SCAN[1] + 20 and owner[P.proposer(e)] not in A:
            e += 1
        if e - s == r:
            return s
        s = e
    return None


def run(job):
    kw, seed, r, lead, tail = job
    from model import BLOCKS, Params, prec
    from sim import Rule, Tracker, World

    P = Params(n=VALIDATORS, seed=seed, k=kw)
    P.check()
    owner = node_of()
    A = frozenset(range(NODES // 2))
    s0 = find_run(P, owner, A, r)
    row = {"k": kw, "seed": seed, "r": r, "lead": lead, "tail": tail, "run_start": s0}
    if s0 is None:
        return row
    sm = P.slot_ms
    start, stop = s0 - lead, s0 + r + tail
    rules = [Rule(start * sm, stop * sm, frozenset(range(NODES)) - A, A, frozenset({"block"}), None)]
    w = World(P, NODES, rules=rules)
    tr = Tracker(w)
    for s in range(stop + AFTER + 1):
        w.run_slot(s, tr.observe)
    final = w.nodes[0].head(w.t)
    lost_pre, lost_during = set(), set()
    for n in w.nodes:
        for c, first in tr.first_conf[n.id].items():
            if not prec(c, final):
                (lost_pre if first < start else lost_during).add(c)
    row.update({"start": start, "D": stop - start, "lost_pre": len(lost_pre),
                "lost_pre_first": min((BLOCKS[c].slot for c in lost_pre), default=None),
                "lost_during": len(lost_during),
                "agree_end": len({n.head(w.t) for n in w.nodes}) == 1})
    return row


def jobs(seeds, quick):
    return [(kw, seed, r, lead, tail)
            for seed in range(seeds)
            for kw in ([4] if quick else [2, 3, 4, 6, 8])
            for r in ([3, 5] if quick else range(1, 10))
            for lead in ([0] if quick else [0, 1])
            for tail in ([0] if quick else [0, 1, 2])]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/timed.json")
    p.add_argument("--seeds", type=int, default=64)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    js = jobs(args.seeds, args.quick)
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"nodes": NODES, "validators": VALIDATORS, "scan": SCAN, "after": AFTER, "rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
