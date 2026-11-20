"""The timed blocks-only fault of timed_sweep.py with a minority voting for blocks it never releases.

timed_sweep.py loses the unfinalized chain when blocks are withheld from exactly half of the online
nodes during k consecutive slots without a proposer of that half. adv_sweep.py showed that f
validators voting, every slot, for blocks they never release let an untimed fault work on uneven
splits. This sweep asks whether the same holds for the timed fault: f adversary validators (on no
node; their proposer slots stay empty) vote for withheld blocks from slot 48 on, delivered to every
honest node 0.5 s into the slot; the 64 - f honest validators sit on 8 online nodes; A is the first
a of them. The fault covers the first run of exactly r slots in [48, 160) without a proposer in A.

With --propose the adversary also fills its own proposer slots: at the start of the slot it builds
the block an honest node of the other side B would build, from a copy of that node's state, and
sends it to the nodes of B only while the fault lasts, to every node otherwise. Without it, its
slots stay empty, and an empty slot inside the run lets B vote for the last block A has, which
renews A's locks.

Run:  python timed_adv_sweep.py [--out data/sweeps/timed_adv.json] [--seeds 64] [--propose] [--quick]
"""

import argparse
import copy
import heapq
import json
import os
from concurrent.futures import ProcessPoolExecutor

NODES, VALIDATORS, AFTER, START = 8, 64, 30, 48
SCAN = (48, 160)
VOTE_AT_MS = 500


def find_run(P, owner, A, r):
    """First slot of a run of exactly r slots without an A proposer, in SCAN; None if absent."""
    inA = lambda s: owner.get(P.proposer(s)) in A
    s = SCAN[0]
    while s < SCAN[1]:
        if inA(s):
            s += 1
            continue
        e = s
        while e < SCAN[1] + 20 and not inA(e):
            e += 1
        if e - s == r:
            return s
        s = e
    return None


def run(job):
    f, a, kw, r, seed = job[:5]
    propose = job[5] if len(job) > 5 else False
    from model import BLOCKS, Params, Vote, make_block, prec
    from sim import Rule, Tracker, World

    P = Params(n=VALIDATORS, seed=seed, k=kw)
    P.check()
    sm = P.slot_ms
    A = frozenset(range(a))
    probe = World(P, NODES, honest=VALIDATORS - f)
    owner = {v: n.id for n in probe.nodes for v in n.validators}
    side_a = sum(len(n.validators) for n in probe.nodes[:a])
    s0 = find_run(P, owner, A, r)
    row = {"f": f, "a": a, "side_a": side_a, "side_b": VALIDATORS - f - side_a, "k": kw, "r": r, "seed": seed,
           "run_start": s0, "propose": propose}
    if s0 is None:
        return row
    del probe
    start, stop = s0, s0 + r
    rules = [Rule(start * sm, stop * sm, frozenset(range(NODES)) - A, A, frozenset({"block"}), None)]
    w = World(P, NODES, rules=rules, honest=VALIDATORS - f)
    tr = Tracker(w)
    adv = range(VALIDATORS - f, VALIDATORS)
    lat = w.net.latency_ms
    for s in range(stop + AFTER + 1):
        if propose and f and s >= START and P.proposer(s) >= VALIDATORS - f:
            ref = w.nodes[a]  # an honest node of B; a copy, so that its state is left alone
            prop = copy.deepcopy(ref.ac).proposal(ref.phi(), P.t(s))
            if prop is not None:
                H, votes, support = prop
                B = make_block(s, H, P.proposer(s), (), tuple(votes), tuple(support))
                targets = range(a, NODES) if start <= s < stop else range(NODES)
                for dst in targets:
                    heapq.heappush(w.net.queue, (P.t(s) + lat, next(w.net.seq), dst, "block", B))
        if f and s >= START:
            votes = tuple(Vote(v, s, f"withheld-{s}") for v in adv)
            for n in w.nodes:
                heapq.heappush(w.net.queue, (P.t(s) + VOTE_AT_MS, next(w.net.seq), n.id, "vote", votes))
        w.run_slot(s, tr.observe)
    final = w.nodes[0].head(w.t)
    lost_pre, lost_during = set(), set()
    for n in w.nodes:
        for c, first in tr.first_conf[n.id].items():
            if not prec(c, final):
                (lost_pre if first < start else lost_during).add(c)
    row.update({"lost_pre": len(lost_pre), "lost_pre_first": min((BLOCKS[c].slot for c in lost_pre), default=None),
                "lost_during": len(lost_during), "agree_end": len({n.head(w.t) for n in w.nodes}) == 1})
    return row


def jobs(seeds, quick, propose):
    return [(f, a, 4, r, seed, propose)
            for seed in range(seeds)
            for f in ([0, 8] if quick else [0, 4, 8, 12, 16])
            for a in ([2, 4] if quick else range(1, NODES))
            for r in ([4] if quick else [3, 4, 5, 6])]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/timed_adv.json")
    p.add_argument("--seeds", type=int, default=64)
    p.add_argument("--propose", action="store_true", help="the adversary fills its proposer slots for B")
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    js = jobs(args.seeds, args.quick, args.propose)
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"nodes": NODES, "validators": VALIDATORS, "scan": SCAN, "after": AFTER, "start": START,
                   "vote_at_ms": VOTE_AT_MS, "rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
