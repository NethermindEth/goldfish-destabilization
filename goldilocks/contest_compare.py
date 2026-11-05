"""The spec's finality rule against the Lean model's, on partition runs.

The spec (F3.20, F3.37) lets F advance only to a block with a viable descendant, and in a
frontier contest the head height floor is h_max. The Lean model's acceptViable uses h_max - 1
always, so F can advance during a contest. This runs every partition shape of sweep.py with
both rules and reports how often a contest happens and whether the two rules then differ in
finality, healing or safety.

Run:  python contest_compare.py [--seeds 5]
"""

import argparse
import contextlib
import io
import itertools
from concurrent.futures import ProcessPoolExecutor

from sweep import DURATIONS, SHAPES, SPREADS


def run_one(job):
    shape, spread, dur, seed, lean = job
    import partition_run
    argv = SHAPES[shape] + ["--start", "48", "--slots-down", str(dur), "--release-spread-ms", str(spread),
                            "--jitter-ms", "1000", "--seed", str(seed), "--after", "40", "--quiet"]
    if lean:
        argv.append("--lean-finality")
    with contextlib.redirect_stdout(io.StringIO()):
        S = partition_run.main(argv)
    return {
        "key": (shape, spread, dur, seed), "lean": lean,
        "contest_slots": S["contest_slots"],
        "final_F": min(x["final_F_slot"] for x in S["per_node"]),
        "finality": S["finality_timeline"],
        "heads_agree": S["agree_head_since"], "conf_agree": S["agree_conf_since"],
        "fin_conflict": S["finalized_conflict"], "violations": len(S["invariant_violations"]),
        "orphaned_conf": sum(len(x["orphaned_confirmed"]) for x in S["per_node"]),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--procs", type=int, default=6)
    args = p.parse_args()
    jobs = [(*c, lean) for c in itertools.product(SHAPES, SPREADS, DURATIONS, range(args.seeds)) for lean in (False, True)]
    with ProcessPoolExecutor(args.procs) as ex:
        rows = list(ex.map(run_one, jobs, chunksize=2))
    spec = {r["key"]: r for r in rows if not r["lean"]}
    lean = {r["key"]: r for r in rows if r["lean"]}
    contested = [k for k in spec if spec[k]["contest_slots"] or lean[k]["contest_slots"]]
    differ = [k for k in spec if (spec[k]["finality"], spec[k]["heads_agree"], spec[k]["conf_agree"])
              != (lean[k]["finality"], lean[k]["heads_agree"], lean[k]["conf_agree"])]
    print(f"{len(spec)} configurations; with a contest at some node: {len(contested)}; "
          f"outcomes differ between the rules: {len(differ)}")
    for side, d in (("spec", spec), ("lean", lean)):
        print(f"  {side}: finalized conflicts {sum(r['fin_conflict'] for r in d.values())}, "
              f"invariant violations {sum(r['violations'] for r in d.values())}, "
              f"orphaned confirmations {sum(r['orphaned_conf'] for r in d.values())}, "
              f"min final F slot {min(r['final_F'] for r in d.values())}")
    for k in differ[:8]:
        a, b = spec[k], lean[k]
        print(f"  {k}: contest slots spec {a['contest_slots'][:6]} lean {b['contest_slots'][:6]}; "
              f"final F {a['final_F']} vs {b['final_F']}; heads agree {a['heads_agree']} vs {b['heads_agree']}")


if __name__ == "__main__":
    main()
