"""Asynchrony resilience of a confirmation: when can an outage plus a one-third adversary revert it?

Grid: outage start τ relative to the confirmation of an honest block B, outage length d (slots),
node grouping during the outage. For each cell: runs where the adversary got its slot, and runs
where some node showed B as confirmed and B ended off the final chain, with the adversary
voting C (attack) and with the adversary silent (control).

Run:  python outage_sweep.py [--seeds 12] [--procs 6]
"""

import argparse
import itertools
from collections import defaultdict
from multiprocessing import Pool

import adversary
from model import prec

DELTA = 1500
TAUS = [-2 * DELTA, -DELTA, 0, DELTA, 2 * DELTA, 4 * DELTA]
LENGTHS = [1, 2, 4, 6, 8]
GROUPS = ["0/1/2/3", "0,1/2,3", "0,1,2/3"]


def one(job):
    groups, d, tau, seed, passive = job
    argv = ["--f", "21", "--strategy", "outage", "--seed", str(seed), "--slots", "72", "--outage-tau", str(tau),
            "--outage-slots", str(d), "--outage-groups", groups] + (["--outage-passive"] if passive else [])
    p = argparse.ArgumentParser(allow_abbrev=False)
    adversary.add_args(p)
    world, _, res = adversary.run(p.parse_args(argv))
    adv = world.adv
    attacked = getattr(adv, "C", None) is not None
    broke = False
    if attacked:
        final = world.nodes[0].head(world.t)
        shown = any(prec(adv.B, c) for tl in world.conf_tl.values() for _, c in tl)
        broke = shown and not prec(adv.B, final)
    return (groups, d, tau, passive), attacked, broke


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=12)
    p.add_argument("--procs", type=int, default=6)
    p.add_argument("--taus", default=None, help="comma-separated, in Δ")
    p.add_argument("--lengths", default=None, help="comma-separated, in slots")
    p.add_argument("--groups", default=None, help="semicolon-separated groupings")
    args = p.parse_args()
    global TAUS, LENGTHS, GROUPS
    if args.taus:
        TAUS = [round(float(x) * DELTA) for x in args.taus.split(",")]
    if args.lengths:
        LENGTHS = [float(x) for x in args.lengths.split(",")]
    if args.groups:
        GROUPS = args.groups.split(";")
    jobs = list(itertools.product(GROUPS, LENGTHS, TAUS, range(args.seeds), (False, True)))
    with Pool(args.procs) as pool:
        out = pool.map(one, jobs, chunksize=4)
    cell = defaultdict(lambda: [0, 0])
    for key, attacked, broke in out:
        if attacked:
            cell[key][0] += 1
            cell[key][1] += broke
    for groups in GROUPS:
        print(f"\ngroups {groups}: B reverted, attack (control), out of attacked runs")
        print("d \\ τ   " + "".join(f"{t / DELTA:+5.0f}Δ      " for t in TAUS))
        for d in LENGTHS:
            row = []
            for tau in TAUS:
                a, b = cell[(groups, d, tau, False)], cell[(groups, d, tau, True)]
                row.append(f"{a[1]:>2}/{a[0]:<2} ({b[1]:>2})  ")
            print(f"{d:>4} slots " + "".join(row))


if __name__ == "__main__":
    main()
