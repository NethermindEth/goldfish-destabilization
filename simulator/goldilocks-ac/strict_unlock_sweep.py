"""The timed blocks-only fault with a lock that moves back only against a strict majority.

lock_check.py shows that the last step of the timed fault is the unlock rule: a lock moves back to an
ancestor unless fewer than half of the validators vote against it, so A's half of the votes, on a
branch from the fork-choice root, is enough to move B's locks back. This sweep changes that one test,
outside the spec, so that a lock moves back only when more than half of the validators vote against
it (Params.strict_unlock), and reruns the two timed sweeps:

- honest: timed_sweep.py, k = 2, 4, 6, runs of r = 1 to 9 slots, no lead or tail;
- adversary: timed_adv_sweep.py --propose, f = 0 to 16, every split of the 8 online honest nodes,
  k = 4, r = 3 to 6.

Both record, besides the lost blocks, the slot of every node's confirmed tip at the end, to see
whether the chain keeps confirming after the fault.

Run:  python strict_unlock_sweep.py [--out data/sweeps/strict_unlock.json] [--seeds 64] [--quick]
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor

import timed_adv_sweep
import timed_sweep

OVER = {"strict_unlock": True}


def run(job):
    kind, j = job
    row = (timed_sweep.run if kind == "honest" else timed_adv_sweep.run)(j)
    row["kind"] = kind
    return row


def jobs(seeds, quick):
    honest = [("honest", (kw, seed, r, 0, 0, OVER))
              for seed in range(seeds)
              for kw in ([4] if quick else [2, 4, 6])
              for r in ([3, 4, 5] if quick else range(1, 10))]
    adv = [("adversary", (f, a, 4, r, seed, True, OVER))
           for seed in range(seeds)
           for f in ([0, 8] if quick else [0, 4, 8, 12, 16])
           for a in ([3, 4] if quick else range(1, timed_adv_sweep.NODES))
           for r in ([4] if quick else [3, 4, 5, 6])]
    return honest + adv


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/strict_unlock.json")
    p.add_argument("--seeds", type=int, default=64)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    js = jobs(args.seeds, args.quick)
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"params": OVER, "after": timed_sweep.AFTER, "rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
