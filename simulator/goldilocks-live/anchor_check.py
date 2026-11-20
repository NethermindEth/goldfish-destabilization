"""The confirmed anchor (Params.confirmed_anchor, outside the spec) with the finality gadget and in sleep.

../goldilocks-ac/confirmed_anchor_sweep.py showed that, on the available chain alone, starting the
head walk of a node with no live lock from its last confirmed block closes the timed fault, and that
partitions on a group recover as before. This sweep checks the two settings it left out:

- timed: timed_sweep.py of this folder, the timed fault with the FG running, 8, 6 or 4 of 8 nodes
  online, k = 2, 4, 6, runs of 1 to 8 slots, with the change; compare with data/sweeps/timed.json;
- scenarios: every named scenario of scenarios.py, in this folder (with the FG) and in
  ../goldilocks-ac (without it): partitions, sleep and rejoin, jitter. Each runs on 8 proposer
  schedules, under the spec and with the change, so that the two are compared run by run.

Run:  python anchor_check.py [--out data/sweeps/anchor_check.json] [--seeds 32] [--scenario-seeds 8] [--quick]
"""

import argparse
import contextlib
import io
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.join(HERE, "..", "goldilocks-ac")
FLAG = "--confirmed-anchor"


def enter(d):  # a worker of one model folder: its model, sim and partition_run come first
    os.chdir(d)
    sys.path.insert(0, d)


def summary(S):
    nodes = S["per_node"]
    out = {"heal": S["heal_slot"], "head_back": S["reconverge_head_slots"], "conf_back": S["reconverge_conf_slots"],
           "orphaned_conf": max(len(x["orphaned_confirmed"]) for x in nodes),
           "conf_switch": sum(len(x["conf_reversals"]) for x in nodes),
           "max_reorg": max(x["max_reorg_depth"] for x in nodes),
           "lock_conflicts": len(S["lock_conflict_slots"]),
           "invariant_violations": len(S["invariant_violations"])}
    if "finalized_conflict" in S:
        out.update({"fin_conflict": S["finalized_conflict"], "F_end": nodes[0]["final_F_slot"]})
    return out


def scenario(job):
    model, name, argv, seed, anchor = job
    import partition_run
    with contextlib.redirect_stdout(io.StringIO()):
        S = partition_run.main(argv + ["--quiet", "--seed", str(seed)] + ([FLAG] if anchor else []))
    return {"family": "scenario", "model": model, "name": name, "seed": seed, "anchor": anchor, **summary(S)}


def timed(job):
    import timed_sweep
    row = timed_sweep.run(job)
    row["family"] = "timed"
    return row


def pool(d, fn, jobs):
    with ProcessPoolExecutor(max_tasks_per_child=1, initializer=enter, initargs=(d,)) as ex:
        return list(ex.map(fn, jobs, chunksize=1))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/anchor_check.json")
    p.add_argument("--seeds", type=int, default=32)
    p.add_argument("--scenario-seeds", type=int, default=8)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    rows = []
    for model, d in (("live", HERE), ("ac", AC)):
        sys.path.insert(0, d)
        import scenarios
        sc = dict(scenarios.SCENARIOS)
        del sys.modules["scenarios"]
        sys.path.remove(d)
        names = list(sc)[:3] if args.quick else list(sc)
        js = [(model, n, sc[n], seed, anchor) for n in names
              for seed in range(1 if args.quick else args.scenario_seeds) for anchor in (False, True)]
        rows += pool(d, scenario, js)
    tj = [(awake, kw, r, seed, {"confirmed_anchor": True})
          for seed in range(2 if args.quick else args.seeds)
          for awake in ([4] if args.quick else [8, 6, 4])
          for kw in ([4] if args.quick else [2, 4, 6])
          for r in ([4] if args.quick else range(1, 9))]
    rows += pool(HERE, timed, tj)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
