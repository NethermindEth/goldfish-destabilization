"""Per seed: when a contest holds, how long, and the finality timeline, for one adversary setting.

Run:  python contest_detail.py --seeds 10 --f 21 --strategy late_j --group-a 0,1 --cut 50:8 --slots 112
"""

import argparse
from multiprocessing import Pool

import adversary


def one(argv):
    p = argparse.ArgumentParser(allow_abbrev=False)
    adversary.add_args(p)
    args = p.parse_args(argv)
    world, tracker, res = adversary.run(args)
    contest = [st["slot"] for st in tracker.states if any(x["contest"] for x in st["nodes"])]
    all_nodes = [st["slot"] for st in tracker.states if all(x["contest"] for x in st["nodes"])]
    return args.seed, contest, all_nodes, res["finality_timeline"], res["max_finality_gap"], res["finality_resume_delay"], world.adv.notes


def main():
    p = argparse.ArgumentParser(allow_abbrev=False)
    p.add_argument("--seeds", type=int, default=10)
    p.add_argument("--procs", type=int, default=6)
    args, rest = p.parse_known_args()
    with Pool(args.procs) as pool:
        out = pool.map(one, [rest + ["--seed", str(s)] for s in range(args.seeds)])
    lens = []
    for seed, contest, alln, fin, gap, resume, notes in out:
        span = (contest[0], contest[-1]) if contest else None
        lens.append(len(contest))
        print(f"seed {seed}: contest slots {span} ({len(contest)} slots, all nodes {len(alln)}); max finality gap {gap}; "
              f"resume delay {resume}; finality {fin[-6:]}")
    print("contest length (slots) per seed:", sorted(lens))


if __name__ == "__main__":
    main()
