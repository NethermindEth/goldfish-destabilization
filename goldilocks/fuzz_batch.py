"""Many seeded runs of an adversary strategy; report every run that breaks a synchrony claim.

Run:  python fuzz_batch.py --seeds 200 --out results/adversary/fuzz_faithful.json [adversary.py options]
"""

import argparse
import json
import time
from multiprocessing import Pool

import adversary


def one(argv):
    p = argparse.ArgumentParser()
    adversary.add_args(p)
    args = p.parse_args(argv)
    try:
        _, _, res = adversary.run(args)
    except Exception as e:  # a crash is a finding about the model or the driver, keep it
        return {"argv": argv, "error": repr(e)}
    res["argv"] = argv
    res["bad"] = adversary.bad(res)
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=100)
    p.add_argument("--first-seed", type=int, default=0)
    p.add_argument("--procs", type=int, default=8)
    p.add_argument("--out", required=True)
    args, rest = p.parse_known_args()
    jobs = [rest + ["--seed", str(s)] for s in range(args.first_seed, args.first_seed + args.seeds)]
    t0 = time.perf_counter()
    with Pool(args.procs) as pool:
        out = pool.map(one, jobs)
    errs = [r for r in out if "error" in r]
    bad = [r for r in out if r.get("bad")]
    print(f"{len(out)} runs in {time.perf_counter() - t0:.0f}s: {len(bad)} with a violation, {len(errs)} crashed")
    for r in bad[:10]:
        print(" ", r["argv"][-1], "tsq", r["n_tsq"], "dropped", r["n_dropped"], "lockconf", r["lock_conflict_slots"][:5],
              "rev", {k: v[:2] for k, v in r["conf_reversals"].items() if v}, "inv", r["invariant_violations"][:2])
    for r in errs[:5]:
        print("  crash", r["argv"][-1], r["error"])
    fin = sorted(min(r["final_F_slots"]) for r in out if "final_F_slots" in r)
    if fin:
        print(f"  final finalized slot (min over nodes): min {fin[0]}, median {fin[len(fin) // 2]}, max {fin[-1]}")
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, default=str)


if __name__ == "__main__":
    main()
