"""Honest blocks orphaned under synchrony, over many seeded adversary runs.

The slides claim that once every live lock was formed after GST, "the next honest proposal gets
every honest vote". This counts, per run, the honest proposals that end up off the final chain
(the last 8 slots are left out: their fate is not settled yet).

Run:  python honest_orphans.py --seeds 150 --procs 6 --f 21 --strategy fin_hide_seq --group-a 0,1,2 --relay-ms 200 --slots 160
"""

import argparse
from multiprocessing import Pool

import adversary
from model import ANC, BLOCKS, GEN


def one(argv):
    p = argparse.ArgumentParser(allow_abbrev=False)
    adversary.add_args(p)
    args = p.parse_args(argv)
    world, _, _ = adversary.run(args)
    heads = {n.id: n.head(world.t) for n in world.nodes}
    chain = ANC[heads[0]]
    adv = set(world.adv_vals)
    last = args.slots - 8
    honest = sorted(BLOCKS[r].slot for r in set().union(*(n.fg.T for n in world.nodes))
                    if r != GEN and r not in chain and BLOCKS[r].proposer not in adv and BLOCKS[r].slot <= last)
    return {"seed": args.seed, "s0": getattr(world.adv, "s0", None), "honest_orphans": honest,
            "agree": len(set(heads.values())) == 1}


def main():
    p = argparse.ArgumentParser(allow_abbrev=False)
    p.add_argument("--seeds", type=int, default=100)
    p.add_argument("--procs", type=int, default=6)
    args, rest = p.parse_known_args()
    with Pool(args.procs) as pool:
        out = pool.map(one, [rest + ["--seed", str(s)] for s in range(args.seeds)], chunksize=4)
    attacked = [r for r in out if r["s0"] is not None]
    hit = [r for r in attacked if r["honest_orphans"]]
    other = [r for r in out if r["s0"] is None and r["honest_orphans"]]
    counts = sorted(len(r["honest_orphans"]) for r in hit)
    print(f"runs {len(out)}; attacked {len(attacked)}; attacked with honest blocks orphaned {len(hit)}; "
          f"honest orphans per attack min/median/max {counts and (counts[0], counts[len(counts) // 2], counts[-1])}; "
          f"runs without an attack but with honest orphans {len(other)}; heads disagree at end {sum(not r['agree'] for r in out)}")


if __name__ == "__main__":
    main()
