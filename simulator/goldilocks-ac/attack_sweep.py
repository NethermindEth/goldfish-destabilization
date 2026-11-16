"""How much asynchrony the available chain absorbs: a sweep of network faults against participation.

Each run has 8 nodes of 8 validators. A share of the nodes sleeps through slots 40–71, so that only
the rest is online when the fault hits at slot 48 (+ an offset of 0–3 Δ into the slot). Faults:

  outage      every message on every link is held for D slots, then released (+ latency)
  votes       only the votes are held for D slots; blocks flow
  blocks      only the blocks are held for D slots; votes flow
  vote_lag    every vote gets `extra` ms on top of its delay for 8 slots (synchrony holds while
              latency + extra <= Δ)

Per run it reports the damage to the available chain:
  lost_pre     confirmed tips first seen before the fault started and later orphaned: what the
               locks are meant to protect
  lost_during  confirmed tips first seen while the fault lasted and later orphaned
  max_reorg    deepest head reorg of any node
  recover      slots from the end of the fault until all nodes agree on the head for good

Run:  python attack_sweep.py [--out data/sweeps/attack.json] [--seeds 3] [--quick]
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor

NODES, VALIDATORS = 8, 64
SLEEP_FROM, SLEEP_TO, START, END = 40, 72, 48, 100


def run(job):
    """One run; imports in the worker, so each process has its own block registry."""
    kind, D, offset, awake, extra, seed = job
    from model import BLOCKS, Params, prec
    from sim import Rule, Tracker, World

    P = Params(n=VALIDATORS, seed=seed)
    sm = P.slot_ms
    a = START * sm + offset * P.delta
    everyone = frozenset(range(NODES))
    if kind == "vote_lag":
        b = a + 8 * sm
        rules = [Rule(a, b, everyone, everyone, frozenset({"vote"}), extra)]
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
        "kind": kind, "D": D, "offset": offset, "awake": awake, "extra": extra, "seed": seed,
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/attack.json")
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    js = jobs(args.seeds, args.quick)
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"nodes": NODES, "validators": VALIDATORS, "sleep": [SLEEP_FROM, SLEEP_TO], "start": START,
                   "end": END, "rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
