"""How fast finality comes back after a partition heals, against the FG timeout delay δ_t.

After an even cut every validator has already sent its target at the stuck height for its own
side's entry, so on the chain that wins the client can only time out there, and timeouts count
only δ_t slots after the entry. So the heal-to-finality time of a 50/50 cut tracks δ_t; with a
majority side it does not. The spec leaves δ_t >= x + c_F + k_F open (c_F = 2 at Δ_F = Δ).

Run:  python timeout_sweep.py [--delta-t 2,3,4,5,8] [--shapes 2,2:3,1]
"""

import argparse
import contextlib
import io
from concurrent.futures import ProcessPoolExecutor


def run_one(job):
    groups, shares, dt = job
    import partition_run  # one job per worker (max_tasks_per_child=1): the chain-state cache is keyed by
    # block root only, and the root does not include δ_t
    argv = ["--groups", groups, "--start", "48", "--slots-down", "16", "--quiet", "--delta-t", str(dt)]
    if shares:
        argv += ["--shares", shares]
    with contextlib.redirect_stdout(io.StringIO()):
        S = partition_run.main(argv)
    h = S["heal_slot"]
    back = next((s for s, f in S["finality_timeline"] if f >= h and s >= h), None)
    return groups, shares, dt, back - h if back is not None else None, S["finalized_conflict"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--delta-t", default="2,3,4,5,8")
    p.add_argument("--shapes", default="2,2:;3,1:;2,2:17,16,16,15", help="groups:shares, ;-separated")
    args = p.parse_args()
    shapes = [tuple(x.split(":")) for x in args.shapes.split(";")]
    jobs = [(g, sh, int(dt)) for g, sh in shapes for dt in args.delta_t.split(",")]
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        for g, sh, dt, back, fc in ex.map(run_one, jobs):
            print(f"cut {g}{' shares ' + sh if sh else ''}  δt={dt}: finalized past the heal after +{back} slots"
                  f"{'  FINALITY CONFLICT' if fc else ''}")


if __name__ == "__main__":
    main()
