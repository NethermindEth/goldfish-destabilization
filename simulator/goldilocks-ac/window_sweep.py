"""Does the lock window set how long the blocks-only fault must last?

The fault of attack_sweep.py --family blocks, into exactly half of the online nodes, with no
adversary, for D = 1 to --dmax slots from slot 48, under each lock window k (every lock has
j+2 <= e <= j+k) and fast increment c. If the locks are what holds the cut-off half to its chain,
the shortest fault that loses pre-fault confirmations should grow with k.

Run:  python window_sweep.py [--out data/sweeps/window.json] [--seeds 8] [--dmax 14] [--c 2,4] [--quick]
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor

from adv_sweep import END, NODES, START, VALIDATORS, run


def jobs(seeds, quick, dmax, cs):
    out = []
    for seed in range(seeds):
        for kw in ([2, 4] if quick else [2, 3, 4, 6, 8]):
            for c in ([2] if quick else cs):
                for awake in ([8] if quick else [8, 6]):
                    for D in ([3, 6] if quick else range(1, dmax + 1)):
                        out.append((0, awake, awake // 2, D, seed, {"k": kw, "c": c}))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/window.json")
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--dmax", type=int, default=14, help="longest fault, in slots")
    p.add_argument("--c", default="2,4", help="fast increments to sweep")
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    js = jobs(args.seeds, args.quick, args.dmax, [int(x) for x in args.c.split(",")])
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"nodes": NODES, "validators": VALIDATORS, "start": START, "end": END, "rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
