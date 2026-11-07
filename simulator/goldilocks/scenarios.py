"""The first partition study on Goldilocks: named scenarios, one process each.

Mirrors the shapes run on the SG protocol (../goldfish-simplex/partition_run.py): 50/50 and 75/25 cuts,
before and after finality starts, short (< k) and long (> R) cuts, a three-way cut, a
repeated cut, and a 52/48 near-tie. Writes <out>/<name>.{log,json,events.json}.

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
    "p50_s24_d16": ["--groups", "2,2", "--start", "24", "--slots-down", "16"],
    "p75_s24_d16": ["--groups", "3,1", "--start", "24", "--slots-down", "16"],
    "p50_s48_d16": ["--groups", "2,2", "--start", "48", "--slots-down", "16"],
    "p75_s48_d16": ["--groups", "3,1", "--start", "48", "--slots-down", "16"],
    "p50_s48_d2": ["--groups", "2,2", "--start", "48", "--slots-down", "2"],
    "p75_s48_d2": ["--groups", "3,1", "--start", "48", "--slots-down", "2"],
    "p50_s48_d64": ["--groups", "2,2", "--start", "48", "--slots-down", "64"],
    "p75_s48_d64": ["--groups", "3,1", "--start", "48", "--slots-down", "64"],
    "p211_s48_d16": ["--groups", "2,1,1", "--start", "48", "--slots-down", "16"],
    "p52_s48_d16": ["--groups", "2,2", "--shares", "17,16,16,15", "--start", "48", "--slots-down", "16"],
    "p50_twice": ["--groups", "2,2", "--start", "48", "--slots-down", "8", "--start2", "60", "--slots-down2", "8",
                  "--groups2", "3,1"],
    "jitter1200": ["--slots-down", "0", "--after", "72", "--jitter-ms", "1200"],
    # dynamic availability: nodes asleep, then restart and rejoin
    "sleep25_s48_d16": ["--slots-down", "0", "--sleep", "3:48:64"],
    "sleep75_s48_d16": ["--slots-down", "0", "--sleep", "1:48:64,2:48:64,3:48:64"],
    "sleep50_s48_d16": ["--slots-down", "0", "--sleep", "2:48:64,3:48:64"],
    # one-slot glitch at a round start (slot 48 = rR) vs mid-round: fg_confirmed reads only slot rR
    "glitch_s48_d1": ["--groups", "2,2", "--start", "48", "--slots-down", "1", "--after", "40"],
    "glitch_s49_d1": ["--groups", "2,2", "--start", "49", "--slots-down", "1", "--after", "40"],
    # messier heal: held messages trickle out over two slots after GST
    "p50_s48_d16_spread": ["--groups", "2,2", "--start", "48", "--slots-down", "16", "--release-spread-ms", "12000"],
    "p75_s48_d16_spread": ["--groups", "3,1", "--start", "48", "--slots-down", "16", "--release-spread-ms", "12000"],
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
    fin = S["finality_timeline"]
    return (f"{name:14s} heal={S['heal_slot']:>3} head+{S['reconverge_head_slots']} conf+{S['reconverge_conf_slots']} "
            f"maxreorg={reorg:>2} orphanedConf={orph:>2} confSwitch={rev} lockConflict={len(lc):>2}"
            f"{'' if not lc else f' [{lc[0]}..{lc[-1]}]'} lastAfterHeal={S['last_lock_conflict_after_heal']} "
            f"finConflict={S['finalized_conflict']} F_end={nodes[0]['final_F_slot']} fin={fin[-4:]}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="results/first")
    p.add_argument("--only", default=None)
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)
    names = args.only.split(",") if args.only else list(SCENARIOS)
    jobs = [(n, SCENARIOS[n], args.out) for n in names]
    with ProcessPoolExecutor() as ex:
        results = dict(ex.map(run_one, jobs))
    with open(f"{args.out}/index.json", "w") as fh:
        json.dump({n: {"args": SCENARIOS[n], "summary": results[n]} for n in names}, fh, indent=1)
    for n in names:
        print(headline(n, results[n]))


if __name__ == "__main__":
    main()
