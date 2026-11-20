"""The timed blocks-only fault of ../goldilocks-ac/timed_sweep.py, with the finality gadget running.

On the available chain alone, withholding blocks from exactly half of the online validators during
k consecutive slots in which the other half proposes loses every block confirmed since the last
finalized one, which there is genesis. Here the FG runs. With 2/3 or more of the validators online
it keeps finalizing, so the fork-choice root, where the cut-off half falls back to, is a few slots
behind the head; with fewer it stalls at the last block finalized before participation dropped.

The first `awake` of 8 nodes are online; the others sleep from slot 40 to the end. A is the first
awake/2 nodes, B the rest of the online ones. The fault withholds blocks, and only blocks, sent from
B to A during the first run of exactly r slots in [SCAN) whose proposer is in B. Votes and FG
attestations flow. Per run: lost_pre, the confirmed tips first seen before the fault and later
orphaned; the finalized slot of node 0 at the fault and at the end; fin_conflict, any two nodes
finalizing conflicting blocks.

Run:  python timed_sweep.py [--out data/sweeps/timed.json] [--seeds 32] [--quick]
"""

import argparse
import heapq
import json
import os
from concurrent.futures import ProcessPoolExecutor

NODES, VALIDATORS, AFTER, SLEEP_FROM = 8, 64, 30, 40
SCAN = (56, 160)


def find_run(P, owner, B, r):
    """First slot of a run of exactly r slots proposed in B, in SCAN; None if absent."""
    inB = lambda s: owner[P.proposer(s)] in B
    s = SCAN[0]
    while s < SCAN[1]:
        if not inB(s):
            s += 1
            continue
        e = s
        while inB(e):
            e += 1
        if e - s == r:
            return s
        s = e
    return None


def run(job):
    awake, kw, r, seed = job
    from model import BLOCKS, Params, prec
    from sim import Tracker, World

    P = Params(n=VALIDATORS, seed=seed, k=kw)
    sm = P.slot_ms
    A = frozenset(range(awake // 2))
    B = frozenset(range(awake // 2, awake))
    sleep = {i: [(SLEEP_FROM * sm, 10 ** 9)] for i in range(awake, NODES)}
    w = World(P, NODES, sleep=sleep)
    s0 = find_run(P, w.node_of, B, r)
    row = {"awake": awake, "k": kw, "r": r, "seed": seed, "run_start": s0}
    if s0 is None:
        return row
    start, stop = s0 * sm, (s0 + r) * sm
    net, plain = w.net, w.net.broadcast

    def broadcast(src, now, kind, payload, nodes):
        if kind != "block" or src not in B or not (start <= now < stop):
            return plain(src, now, kind, payload, nodes)
        plain(src, now, kind, payload, [n for n in nodes if n.id not in A])
        for dst in A:  # held until the end of the fault, then sent with the usual latency
            heapq.heappush(net.queue, (max(now, stop) + net.latency_ms, next(net.seq), dst, kind, payload))

    net.broadcast = broadcast
    tr = Tracker(w)
    first = {n.id: {} for n in w.nodes}
    fin_at_fault = None

    def observe(s, world):
        nonlocal fin_at_fault
        tr.observe(s, world)
        tr.states.clear()  # keep memory flat
        for n in world.nodes[:awake]:
            first[n.id].setdefault(n.confirmed(world.t), s)
        if s == s0 - 1:
            fin_at_fault = BLOCKS[world.nodes[0].fg.F].slot

    for s in range(s0 + r + AFTER + 1):
        w.run_slot(s, observe)
    final = w.nodes[0].head(w.t)
    lost_pre = {c for i in first for c, f in first[i].items() if f < s0 and not prec(c, final)}
    row.update({"lost_pre": len(lost_pre), "lost_pre_first": min((BLOCKS[c].slot for c in lost_pre), default=None),
                "fin_at_fault": fin_at_fault, "fin_end": BLOCKS[w.nodes[0].fg.F].slot,
                "fin_conflict": tr.fin_conflict, "agree_end": len({n.head(w.t) for n in w.nodes[:awake]}) == 1})
    return row


def jobs(seeds, quick):
    return [(awake, kw, r, seed)
            for seed in range(seeds)
            for awake in ([8, 4] if quick else [8, 6, 4])
            for kw in ([4] if quick else [2, 4, 6])
            for r in ([4] if quick else range(1, 9))]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/timed.json")
    p.add_argument("--seeds", type=int, default=32)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    js = jobs(args.seeds, args.quick)
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"nodes": NODES, "validators": VALIDATORS, "scan": SCAN, "after": AFTER, "sleep_from": SLEEP_FROM,
                   "rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
