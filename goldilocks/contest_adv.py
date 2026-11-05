"""Contests from a two-faced adversary across a cut: the spec's finality rule against the Lean model's.

Run:  python contest_adv.py --seeds 40 [adversary.py options, default: twoface across a 16-slot cut]
"""

import argparse
from multiprocessing import Pool

import adversary
from model import BLOCKS


def one(argv):
    p = argparse.ArgumentParser(allow_abbrev=False)
    adversary.add_args(p)
    args = p.parse_args(argv)
    world, tracker, res = adversary.run(args)
    contest = [st["slot"] for st in tracker.states if any(x["contest"] for x in st["nodes"])]
    return {"seed": args.seed, "lean": args.lean_finality, "contest": contest,
            "final_F": min(BLOCKS[n.fg.F].slot for n in world.nodes), "finality": res.get("finality_timeline"),
            "bad": adversary.bad(res), "fin_conflict": res.get("finalized_conflict"),
            "max_gap": res.get("max_finality_gap"), "heads_agree": res.get("heads_agree_end"),
            "orph": res.get("n_orphaned_any_tick")}


def main():
    p = argparse.ArgumentParser(allow_abbrev=False)
    p.add_argument("--seeds", type=int, default=40)
    p.add_argument("--procs", type=int, default=6)
    args, rest = p.parse_known_args()
    if not rest:
        rest = ["--f", "21", "--strategy", "twoface", "--cut", "48:16", "--group-a", "0,1", "--post", "reveal", "--slots", "112"]
    jobs = [rest + ["--seed", str(s)] + (["--lean-finality"] if lean else []) for s in range(args.seeds) for lean in (False, True)]
    with Pool(args.procs) as pool:
        out = pool.map(one, jobs, chunksize=2)
    spec = {r["seed"]: r for r in out if not r["lean"]}
    lean = {r["seed"]: r for r in out if r["lean"]}
    contested = [s for s in spec if spec[s]["contest"] or lean[s]["contest"]]
    differ = [s for s in spec if (spec[s]["finality"], spec[s]["heads_agree"]) != (lean[s]["finality"], lean[s]["heads_agree"])]
    print(f"{len(spec)} seeds; contest at some node: spec {sum(bool(r['contest']) for r in spec.values())}, "
          f"lean {sum(bool(r['contest']) for r in lean.values())}; outcomes differ: {len(differ)}")
    for side, d in (("spec", spec), ("lean", lean)):
        print(f"  {side}: runs flagged bad {sum(bool(r['bad']) for r in d.values())}, finalized conflicts "
              f"{sum(bool(r['fin_conflict']) for r in d.values())}, max finality gap "
              f"{max((r['max_gap'] or 0) for r in d.values())}, min final F {min(r['final_F'] for r in d.values())}")
    for s in differ[:8]:
        a, b = spec[s], lean[s]
        print(f"  seed {s}: contest spec {a['contest'][:5]}.. ({len(a['contest'])}) lean {b['contest'][:5]}.. ({len(b['contest'])}); "
              f"final F {a['final_F']} vs {b['final_F']}; max gap {a['max_gap']} vs {b['max_gap']}")


if __name__ == "__main__":
    main()
