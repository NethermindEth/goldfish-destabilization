"""How much asynchrony the available chain absorbs: a sweep of network faults against participation.

Each run has 8 nodes of 8 validators. A share of the nodes sleeps through slots 40–71, so that only
the rest is online when the fault hits at slot 48 (+ an offset of 0–3 Δ into the slot). Faults:

  outage      every message on every link is held for D slots, then released (+ latency)
  votes       only the votes are held for D slots; blocks flow
  blocks      only the blocks are held for D slots; votes flow
  vote_lag    every vote gets `extra` ms on top of its delay for 8 slots (synchrony holds while
              latency + extra <= Δ)

and, with --family asym, faults that treat a target group A (the first k online nodes) apart from
the rest, for D slots:

  split       every message between A and the rest is held: a k-against-the-rest partition
  eclipse_in  every message into A is held; A still sends
  votes_in    only the votes into A are held
  votes_late  the votes into A arrive 2.8 s late, after the +3 s cutoff of the confirmation count
  blocks_in   only the blocks into A are held

Per run it reports the damage to the available chain:
  lost_pre     confirmed tips first seen before the fault started and later orphaned: what the
               locks are meant to protect
  lost_during  confirmed tips first seen while the fault lasted and later orphaned
  max_reorg    deepest head reorg of any node
  recover      slots from the end of the fault until all nodes agree on the head for good

and, with --family blocks, blocks_in at 4 to 10 slots for a group of one node, half of the online
nodes, and all online nodes but one.

Run:  python attack_sweep.py [--family sym|asym|blocks] [--out data/sweeps/attack.json] [--seeds 3] [--quick]
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor

NODES, VALIDATORS = 8, 64
SLEEP_FROM, SLEEP_TO, START, END = 40, 72, 48, 100


def run(job):
    """One run; imports in the worker, so each process has its own block registry."""
    kind, D, offset, awake, extra, seed = job[:6]
    k = job[6] if len(job) > 6 else None
    from model import BLOCKS, Params, prec
    from sim import Rule, Tracker, World

    P = Params(n=VALIDATORS, seed=seed)
    sm = P.slot_ms
    a = START * sm + offset * P.delta
    everyone = frozenset(range(NODES))
    A = frozenset(range(k)) if k else frozenset()
    rest = everyone - A
    votes, blocks = frozenset({"vote"}), frozenset({"block"})
    if kind == "vote_lag":
        b = a + 8 * sm
        rules = [Rule(a, b, everyone, everyone, votes, extra)]
    elif kind in ("split", "eclipse_in", "votes_in", "votes_late", "blocks_in"):
        b = a + round(D * sm)
        rules = {"split": [Rule(a, b, A, rest, None, None), Rule(a, b, rest, A, None, None)],
                 "eclipse_in": [Rule(a, b, rest, A, None, None)],
                 "votes_in": [Rule(a, b, rest, A, votes, None)],
                 "votes_late": [Rule(a, b, rest, A, votes, 2800)],
                 "blocks_in": [Rule(a, b, rest, A, blocks, None)]}[kind]
    else:
        b = a + round(D * sm)
        kinds = {"outage": None, "votes": frozenset({"vote"}), "blocks": frozenset({"block"})}[kind]
        rules = [Rule(a, b, everyone, everyone, kinds, None)]
    sleep = {i: [(SLEEP_FROM * sm, SLEEP_TO * sm)] for i in range(awake, NODES)}
    w = World(P, NODES, rules=rules, sleep=sleep)
    tr = Tracker(w)
    for s in range(END + 1):
        w.run_slot(s, tr.observe)
    t = w.t
    final = w.nodes[0].head(t)
    agree_end = len({n.head(t) for n in w.nodes}) == 1
    start_slot, end_slot = a // sm, -(-b // sm)
    lost_pre, lost_during = set(), set()
    for n in w.nodes:
        for c, first in tr.first_conf[n.id].items():
            if prec(c, final):
                continue
            if first < start_slot:
                lost_pre.add(c)
            elif first <= end_slot:
                lost_during.add(c)
    since = tr.agree_since(1, end_slot)
    return {
        "kind": kind, "D": D, "offset": offset, "awake": awake, "extra": extra, "seed": seed, "k": k,
        "lost_pre": len(lost_pre), "lost_pre_slots": sorted(BLOCKS[c].slot for c in lost_pre),
        "lost_during": len(lost_during),
        "max_reorg": max((d for r in tr.reorgs.values() for _, d, _ in r), default=0),
        "recover": None if since is None else since - end_slot,
        "agree_end": agree_end,
    }


def jobs(seeds, quick):
    Ds = [1, 2, 3, 4] if quick else [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6]
    offsets = [0, 2] if quick else [0, 1, 2, 3]
    awakes = [8, 4] if quick else [8, 6, 4, 3]
    extras = [0, 1000, 1300, 1600, 3000] if quick else [0, 600, 1000, 1200, 1300, 1400, 1600, 2000, 3000, 4500, 6000]
    out = []
    for seed in range(seeds):
        for awake in awakes:
            for kind in ("outage", "votes", "blocks"):
                for D in Ds:
                    for off in offsets:
                        out.append((kind, D, off, awake, None, seed))
            for extra in extras:
                out.append(("vote_lag", 8, 0, awake, extra, seed))
    return out


def asym_jobs(seeds, quick):
    Ds = [1, 3] if quick else [1, 2, 3, 4, 6]
    offsets = [0, 2] if quick else [0, 1, 2, 3]
    awakes = [8, 4] if quick else [8, 6, 4]
    out = []
    for seed in range(seeds):
        for awake in awakes:
            for kind in ("split", "eclipse_in", "votes_in", "votes_late", "blocks_in"):
                for k in (1, 2, 3, 4):
                    if k >= awake:
                        continue
                    for D in Ds:
                        for off in offsets:
                            out.append((kind, D, off, awake, None, seed, k))
    return out


def blocks_jobs(seeds, quick):
    """blocks_in at longer durations: the group alone, half and all but one of the online nodes."""
    out = []
    for seed in range(seeds):
        for awake in (8, 6, 4):
            for k in sorted({1, awake // 2, awake - 1}):
                for D in ([5, 8] if quick else [4, 5, 6, 7, 8, 10]):
                    for off in ([0] if quick else [0, 1, 2, 3]):
                        out.append(("blocks_in", D, off, awake, None, seed, k))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--family", choices=["sym", "asym", "blocks"], default="sym")
    p.add_argument("--out", default=None, help="default data/sweeps/attack.json or attack_asym.json")
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    args.out = args.out or {"sym": "data/sweeps/attack.json", "asym": "data/sweeps/attack_asym.json",
                            "blocks": "data/sweeps/attack_blocks.json"}[args.family]
    js = {"sym": jobs, "asym": asym_jobs, "blocks": blocks_jobs}[args.family](args.seeds, args.quick)
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"nodes": NODES, "validators": VALIDATORS, "sleep": [SLEEP_FROM, SLEEP_TO], "start": START,
                   "end": END, "rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
