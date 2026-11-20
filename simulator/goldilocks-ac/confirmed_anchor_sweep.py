"""The timed blocks-only fault when the head walk falls back to the last confirmed block.

strict_unlock_sweep.py showed that the timed fault loses the chain because every lock of a node can
expire without a new confirmation, and its head walk then starts from the fork-choice root, the last
finalized block. This sweep tries a change outside the spec (Params.confirmed_anchor): a node with
no live lock starts its head walk from its last confirmed block instead. That block moves back under
the unlock rule like a lock, so that the node is not stuck on it forever. It reruns:

- honest: timed_sweep.py, k = 2, 4, 6, runs of 1 to 9 slots, with the change alone and together
  with Params.strict_unlock;
- adversary: timed_adv_sweep.py --propose, f = 0 to 16, every split of the 8 online honest nodes,
  k = 4, runs of 3 to 6 slots, with the change alone;
- partitions: attack_sweep.py --family asym, kinds split and blocks_in, with the change alone, to
  see whether a node held on its own confirmed block delays recovery after a fault. These rows
  compare with data/sweeps/attack_asym.json, the same runs under the spec.

Run:  python confirmed_anchor_sweep.py [--out data/sweeps/confirmed_anchor.json] [--seeds 64] [--quick]
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor

import attack_sweep
import timed_adv_sweep
import timed_sweep

ANCHOR = {"confirmed_anchor": True}
BOTH = {"confirmed_anchor": True, "strict_unlock": True}


def run(job):
    kind, j = job
    fn = {"honest": timed_sweep.run, "adversary": timed_adv_sweep.run, "partition": attack_sweep.run}[kind]
    row = fn(j)
    row["family"] = kind
    return row


def jobs(seeds, quick):
    honest = [("honest", (kw, seed, r, 0, 0, over))
              for over in (ANCHOR, BOTH)
              for seed in range(seeds)
              for kw in ([4] if quick else [2, 4, 6])
              for r in ([3, 4, 5] if quick else range(1, 10))]
    adv = [("adversary", (f, a, 4, r, seed, True, ANCHOR))
           for seed in range(seeds)
           for f in ([0, 8] if quick else [0, 4, 8, 12, 16])
           for a in ([3, 4] if quick else range(1, timed_adv_sweep.NODES))
           for r in ([4] if quick else [3, 4, 5, 6])]
    part = [("partition", j + (ANCHOR,))
            for j in attack_sweep.asym_jobs(1 if quick else 3, quick) if j[0] in ("split", "blocks_in")]
    return honest + adv + part


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/confirmed_anchor.json")
    p.add_argument("--seeds", type=int, default=64)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    js = jobs(args.seeds, args.quick)
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"after": timed_sweep.AFTER, "rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
