"""One outage run: when does each node stop showing B as confirmed, relative to the outage?

Run:  python outage_trace.py --f 21 --strategy outage --seed 0 --outage-tau 10500 --outage-slots 3.75
"""

import argparse

import adversary
from model import BLOCKS, prec


def main():
    p = argparse.ArgumentParser(allow_abbrev=False)
    adversary.add_args(p)
    args = p.parse_args()
    world, _, _ = adversary.run(args)
    adv, P = world.adv, world.P
    if getattr(adv, "C", None) is None:
        print("no attack in this run")
        return
    b0, b1 = adv.window
    fmt = lambda t: f"t{P.slot(t)}+{(t - P.t(P.slot(t))) / P.delta:.2f}Δ"
    print("notes:", adv.notes)
    print(f"B = slot {BLOCKS[adv.B].slot}; outage [{fmt(b0)}, {fmt(b1)}); B on node 0's final chain: "
          f"{prec(adv.B, world.nodes[0].head(world.t))}")
    for n in world.nodes:
        tl = world.conf_tl[n.id]
        ext = [(t, prec(adv.B, c)) for t, c in tl]
        first = next((t for t, e in ext if e), None)
        lost = next((t for t, e in ext if first is not None and t > first and not e), None)
        print(f"node {n.id}: shows B from {fmt(first) if first else None}; stops at {fmt(lost) if lost else 'never'}"
              f"{'' if lost is None else (' (during the outage)' if lost < b1 else ' (after the heal)')}")


if __name__ == "__main__":
    main()
