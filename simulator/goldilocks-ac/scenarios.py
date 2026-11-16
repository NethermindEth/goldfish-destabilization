"""Named scenarios on the available chain alone: the partition and sleep study of ../goldilocks-live.

Writes <out>/<name>.{log,json,events.json} and <out>/index.json.

Run:  python scenarios.py [--out results/first] [--only name1,name2]
"""

import argparse
import contextlib
import io
import json
import os
from concurrent.futures import ProcessPoolExecutor

SCENARIOS = {
    "honest": ["--slots-down", "0", "--after", "72"],
    "p50_s48_d2": ["--groups", "2,2", "--start", "48", "--slots-down", "2"],
    "p50_s48_d16": ["--groups", "2,2", "--start", "48", "--slots-down", "16"],
    "p75_s48_d16": ["--groups", "3,1", "--start", "48", "--slots-down", "16"],
    "p52_s48_d16": ["--groups", "2,2", "--shares", "17,16,16,15", "--start", "48", "--slots-down", "16"],
    "p50_s48_d64": ["--groups", "2,2", "--start", "48", "--slots-down", "64"],
    "p211_s48_d16": ["--groups", "2,1,1", "--start", "48", "--slots-down", "16"],
    "p50_twice": ["--groups", "2,2", "--start", "48", "--slots-down", "8", "--start2", "60", "--slots-down2", "8",
                  "--groups2", "3,1"],
    "p50_s48_d16_spread": ["--groups", "2,2", "--start", "48", "--slots-down", "16", "--release-spread-ms", "12000"],
    "jitter1200": ["--slots-down", "0", "--after", "72", "--jitter-ms", "1200"],
    # dynamic availability: nodes asleep, then restart and rejoin
    "sleep25_s48_d16": ["--slots-down", "0", "--sleep", "3:48:64"],
    "sleep50_s48_d16": ["--slots-down", "0", "--sleep", "2:48:64,3:48:64"],
    "sleep75_s48_d16": ["--slots-down", "0", "--sleep", "1:48:64,2:48:64,3:48:64"],
    # blocks, and only blocks, withheld from half of the online validators while nothing is finalized
    "blocks_half_d8": ["--nodes", "8", "--groups", "3,5", "--slots-down", "0", "--sleep", "3:40:72,4:40:72",
                       "--rule", "48:56:3+4+5+6+7:0+1+2:block:hold", "--start", "44", "--after", "28"],
}


def run_one(job):
    name, argv, out = job
    import partition_run  # imported in the worker: each process has its own block registry
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        S = partition_run.main(argv + ["--quiet", "--json", f"{out}/{name}.json", "--events", f"{out}/{name}.events.json"])
    with open(f"{out}/{name}.log", "w") as fh:
        fh.write(buf.getvalue())
    return name, S


def headline(name, S):
    nodes = S["per_node"]
    reorg = max(x["max_reorg_depth"] for x in nodes)
    orph = max(len(x["orphaned_confirmed"]) for x in nodes)
    rev = sum(len(x["conf_reversals"]) for x in nodes)
    lc = S["lock_conflict_slots"]
    return (f"{name:20s} heal={S['heal_slot']:>3} head+{S['reconverge_head_slots']} conf+{S['reconverge_conf_slots']} "
            f"maxreorg={reorg:>2} orphanedConf={orph:>2} confSwitch={rev} lockConflict={len(lc):>2}"
            f"{'' if not lc else f' [{lc[0]}..{lc[-1]}]'} lastAfterHeal={S['last_lock_conflict_after_heal']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="results/first")
    p.add_argument("--only", default=None)
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)
    names = args.only.split(",") if args.only else list(SCENARIOS)
    jobs = [(n, SCENARIOS[n], args.out) for n in names]
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        results = dict(ex.map(run_one, jobs))
    with open(f"{args.out}/index.json", "w") as fh:
        json.dump({n: {"args": SCENARIOS[n], "summary": results[n]} for n in names}, fh, indent=1)
    for n in names:
        print(headline(n, results[n]))


if __name__ == "__main__":
    main()
