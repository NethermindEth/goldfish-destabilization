"""A Byzantine minority that votes for blocks it never releases, with and without a blocks-only fault.

The f validators [n - f, n) belong to the adversary and sit on no node. From slot 48 on, in every
slot s, each of them votes for a block of slot s that it never releases: every honest node gets the
votes 0.5 s into the slot, as it gets honest votes, so synchrony holds for them. An honest node
counts such a vote as a voter, and the vote supports no block, because its block never resolves.

Alone this cannot hurt an honest block that every honest vote supports: it keeps a strict majority
of the voters while the online honest stake exceeds f. With the fault of attack_sweep.py --family
blocks (no block reaches a group A of the first k online nodes for D slots, from slot 48, while the
votes flow) the votes for missing blocks add up: A's chain lacks a majority when |A| < |B| + f, and
the other side's new blocks when |B| <= |A| + f, so the split need not be even. D = 0 runs the
adversary alone, under synchrony.

8 nodes share the n - f honest validators; the last nodes sleep through slots 40–71.
Per run: lost_pre, lost_during, max_reorg, recover as in attack_sweep.py.

Run:  python adv_sweep.py [--out data/sweeps/adv_withheld.json] [--seeds 4] [--quick]
"""

import argparse
import heapq
import json
import os
from concurrent.futures import ProcessPoolExecutor

NODES, VALIDATORS = 8, 64
SLEEP_FROM, SLEEP_TO, START, END = 40, 72, 48, 100
VOTE_AT_MS = 500  # into the slot, when every honest node gets the adversary's votes


def run(job):
    """One run; imports in the worker, so each process has its own block registry."""
    f, awake, k, D, seed = job[:5]
    over = job[5] if len(job) > 5 else {}
    from model import BLOCKS, Params, Vote, prec
    from sim import Rule, Tracker, World

    P = Params(n=VALIDATORS, seed=seed, **over)
    P.check()
    sm = P.slot_ms
    everyone = frozenset(range(NODES))
    A = frozenset(range(k))
    a, b = START * sm, START * sm + round(D * sm)
    rules = [Rule(a, b, everyone - A, A, frozenset({"block"}), None)] if D else []
    sleep = {i: [(SLEEP_FROM * sm, SLEEP_TO * sm)] for i in range(awake, NODES)}
    w = World(P, NODES, rules=rules, sleep=sleep, honest=VALIDATORS - f)
    tr = Tracker(w)
    adv = range(VALIDATORS - f, VALIDATORS)
    for s in range(END + 1):
        if f and s >= START:
            votes = tuple(Vote(v, s, f"withheld-{s}") for v in adv)
            for n in w.nodes:
                heapq.heappush(w.net.queue, (P.t(s) + VOTE_AT_MS, next(w.net.seq), n.id, "vote", votes))
        w.run_slot(s, tr.observe)
    t = w.t
    final = w.nodes[0].head(t)
    lost_pre, lost_during = set(), set()
    end_slot = -(-b // sm)
    for n in w.nodes:
        for c, first in tr.first_conf[n.id].items():
            if prec(c, final):
                continue
            (lost_pre if first < START else lost_during).add(c)
    since = tr.agree_since(1, max(end_slot, START))
    online = sum(len(n.validators) for n in w.nodes[:awake])
    side_a = sum(len(n.validators) for n in w.nodes[:k])
    return {
        "f": f, "awake": awake, "k": k, "D": D, "seed": seed, "params": over, "online_honest": online, "side_a": side_a,
        "lost_pre": len(lost_pre), "lost_pre_first": min((BLOCKS[c].slot for c in lost_pre), default=None),
        "lost_during": len(lost_during),
        "max_reorg": max((d for r in tr.reorgs.values() for _, d, _ in r), default=0),
        "recover": None if since is None else since - max(end_slot, START),
        "agree_end": len({n.head(t) for n in w.nodes}) == 1,
    }


def jobs(seeds, quick):
    out = []
    for seed in range(seeds):
        for f in ([0, 8] if quick else [0, 4, 8, 12, 16]):
            for awake in ([8] if quick else [8, 6]):
                for k in range(1, awake):
                    for D in ([0, 5] if quick else [0, 2, 3, 4, 5, 6, 8]):
                        out.append((f, awake, k, D, seed))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/adv_withheld.json")
    p.add_argument("--seeds", type=int, default=4)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    js = jobs(args.seeds, args.quick)
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"nodes": NODES, "validators": VALIDATORS, "sleep": [SLEEP_FROM, SLEEP_TO], "start": START,
                   "end": END, "vote_at_ms": VOTE_AT_MS, "rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
