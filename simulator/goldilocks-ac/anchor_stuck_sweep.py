"""Can the confirmed anchor hold a node on an abandoned branch when fewer than half are online?

Params.confirmed_anchor (outside the spec) makes a node with no live lock start its head walk from
its last confirmed block, and the unlock rule moves that block back like a lock. The unlock rule
moves a block back only when at least half of all n validators vote against it, online or not.
Locks also expire after at most k slots; the anchor does not. So when fewer than n/2 validators are
online, a node whose anchor sits on a branch the others abandoned may never leave it.

Each run: 8 nodes of 8 validators; only the first m nodes are online, the others asleep for the whole
run. From slot START the online nodes are split into [0, a) and [a, m) for D slots, so each side
confirms its own blocks, then the cut heals and the run goes on for AFTER slots. Each setting runs
under the spec and with the change. Per run: whether the online heads agree at the end and since
when, the slot of each online node's confirmed tip at the end, and the confirmed blocks lost.

Run:  python anchor_stuck_sweep.py [--out data/sweeps/anchor_stuck.json] [--seeds 32] [--quick]
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor

NODES, VALIDATORS, START, AFTER = 8, 64, 24, 64


def run(job):
    m, a, D, seed, anchor = job
    from model import BLOCKS, Params, conflicts, prec
    from sim import Rule, Tracker, World

    P = Params(n=VALIDATORS, seed=seed, confirmed_anchor=anchor)
    P.check()
    sm = P.slot_ms
    A, B = frozenset(range(a)), frozenset(range(a, m))
    rules = [Rule(START * sm, (START + D) * sm, A, B, None, None),
             Rule(START * sm, (START + D) * sm, B, A, None, None)] if D else []
    sleep = {i: [(0, 10 ** 9)] for i in range(m, NODES)}
    w = World(P, NODES, rules=rules, sleep=sleep)
    tr = Tracker(w)
    end = START + D + AFTER
    heal = {}

    def observe(s, world):
        tr.observe(s, world)
        tr.states.clear()
        if s == START + D:  # the last confirmed blocks of the online nodes as the cut heals
            heal["conf"] = [n.ac.latest_confirmed for n in world.nodes[:m]]

    for s in range(end + 1):
        w.run_slot(s, observe)
    t = w.t
    online = w.nodes[:m]
    heads = [n.head(t) for n in online]
    final = heads[0]
    lost = {c for n in online for c, first in tr.first_conf[n.id].items() if not prec(c, final)}
    since = tr.agree_since(1, START + D)
    return {"m": m, "a": a, "D": D, "seed": seed, "anchor": anchor,
            "online_validators": sum(len(n.validators) for n in online),
            "conf_conflict_at_heal": any(conflicts(x, y) for x in heal["conf"] for y in heal["conf"]),
            "agree_end": len(set(heads)) == 1,
            "agree_after_heal": None if since is None else since - (START + D),
            "head_end": [BLOCKS[h].slot for h in heads],
            "conf_end": [BLOCKS[n.confirmed(t)].slot for n in online],
            "lost": len(lost)}


def jobs(seeds, quick):
    out = []
    for m in ([3, 4] if quick else [2, 3, 4, 5, 6]):
        for a in range(1, m // 2 + 1):
            for D in ([8] if quick else [2, 4, 8, 16]):
                for seed in range(seeds):
                    for anchor in (False, True):
                        out.append((m, a, D, seed, anchor))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/anchor_stuck.json")
    p.add_argument("--seeds", type=int, default=32)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    js = jobs(args.seeds, args.quick)
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"nodes": NODES, "validators": VALIDATORS, "start": START, "after": AFTER, "rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
