"""Seeded sweep of partition shapes x heal messiness, measured against the healing claim.

The slides claim: after GST, conflicting locks are gone by GST + L, unfollowed locks by
GST + 2L, and the next honest proposal heals the AC (GST + 2L + G), with L = k slots.
Here "effective GST" is the slot by which every held message has been delivered: the heal
plus the release spread. Post-GST delays are latency + U(0, jitter) < Δ.

Per run it records, relative to effective GST (in slots): the last slot with conflicting
live locks across honest nodes, when heads and confirmed tips agree for good, and the last
slot at which some node's confirmed tip was a block that ended up off its final chain.

Run:  python sweep.py [--seeds 10] [--out results/sweep]
"""

import argparse
import contextlib
import io
import itertools
import json
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

SHAPES = {
    "50/50": ["--groups", "2,2"],
    "75/25": ["--groups", "3,1"],
    "50/25/25": ["--groups", "2,1,1"],
    "52/48": ["--groups", "2,2", "--shares", "17,16,16,15"],
}
SPREADS = [0, 3000, 6000, 12000]
DURATIONS = [2, 16]


def run_one(job):
    shape, spread, dur, seed = job
    import partition_run
    argv = SHAPES[shape] + ["--start", "48", "--slots-down", str(dur), "--release-spread-ms", str(spread),
                            "--jitter-ms", "1000", "--seed", str(seed), "--after", "40", "--quiet"]
    with contextlib.redirect_stdout(io.StringIO()):
        S = partition_run.main(argv)
    slot_ms = 6000
    heal = S["heal_slot"]
    gst = -(-(heal * slot_ms + 200 + spread) // slot_ms)  # every held message delivered
    rel = lambda v: None if v is None else v - gst
    bad_conf = [x["last_slot_with_orphaned_conf"] for x in S["per_node"] if x["last_slot_with_orphaned_conf"] is not None]
    return {
        "shape": shape, "spread": spread, "dur": dur, "seed": seed, "heal": heal, "gst": gst,
        "lock_conflict_after": rel(max([s for s in S["lock_conflict_slots"] if s >= gst], default=None)),
        "heads_agree": rel(S["agree_head_since"]), "conf_agree": rel(S["agree_conf_since"]),
        "last_orphaned_conf": rel(max(bad_conf, default=None)),
        "max_reorg": max(x["max_reorg_depth"] for x in S["per_node"]),
        "fin_conflict": S["finalized_conflict"], "violations": len(S["invariant_violations"]),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=10)
    p.add_argument("--out", default="results/sweep")
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)
    jobs = list(itertools.product(SHAPES, SPREADS, DURATIONS, range(args.seeds)))
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(run_one, jobs, chunksize=4))
    with open(f"{args.out}/sweep.json", "w") as fh:
        json.dump(rows, fh, indent=1)
    groups = defaultdict(list)
    for r in rows:
        groups[(r["shape"], r["dur"], r["spread"])].append(r)

    def mx(rs, k):
        vals = [r[k] for r in rs if r[k] is not None]
        return "never" if any(r[k] is None for r in rs) and k.endswith("agree") else (max(vals) if vals else "-")

    print(f"{len(rows)} runs; slots relative to effective GST (k = L = 4, so 2L = 8)")
    print(f"{'shape':9s} {'D':>3s} {'spread':>6s} | {'lockConfl':>9s} {'heads':>5s} {'conf':>5s} {'lastOrphConf':>12s} "
          f"{'maxReorg':>8s} finConfl viol")
    for (shape, dur, spread), rs in sorted(groups.items(), key=lambda kv: (list(SHAPES).index(kv[0][0]), kv[0][1], kv[0][2])):
        print(f"{shape:9s} {dur:3d} {spread:6d} | {str(mx(rs, 'lock_conflict_after')):>9s} {str(mx(rs, 'heads_agree')):>5s} "
              f"{str(mx(rs, 'conf_agree')):>5s} {str(mx(rs, 'last_orphaned_conf')):>12s} {max(r['max_reorg'] for r in rs):8d} "
              f"{sum(r['fin_conflict'] for r in rs):8d} {sum(r['violations'] for r in rs):4d}")


if __name__ == "__main__":
    main()
