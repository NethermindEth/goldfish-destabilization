"""Step-by-step trace of the fin_hide attack (adversary.py FinalityHide) for one seed.

Run:  python fin_hide_trace.py [--relay-ms 200] [--fast-strict] [--seed 7]
"""

import argparse
import sys

import adversary
from model import ANC, BLOCKS


def main(argv):
    p = argparse.ArgumentParser(allow_abbrev=False)
    adversary.add_args(p)
    args = p.parse_args(["--strategy", "fin_hide", "--group-a", "0", "--seed", "7"] + argv)
    w, _, res = adversary.run(args)
    a, P = w.adv, w.P
    print(a.notes[0] if a.notes else "no attack in this run")
    if not getattr(a, "Z", None):
        return
    names = {a.B.root: "B", a.W: "W", a.Z.root: "Z"}

    def nm(r):
        return names.get(r, f"#{BLOCKS[r].slot}") if r else "-"

    s0 = a.s0
    for e in w.log_events:
        s = P.slot(e["t"])
        if not s0 <= s <= s0 + 3:
            continue
        off = (e["t"] - P.t(s)) // P.delta
        if e["kind"] == "confirm":
            print(f"  slot {s} +{off}Δ  node {e['node']}: update of slot {e['slot']} -> {nm(e['result'])}, "
                  f"lock {nm(e.get('lock'))} {e.get('how') or ''}")
        elif e["kind"] == "lock_back":
            print(f"  slot {s} +{off}Δ  node {e['node']}: lock {nm(e['block'])} moved back to {nm(e['to'])}")
    for n in w.nodes:
        print(f"  node {n.id}: B on its final chain: {a.B.root in ANC[n.head(w.t)]}")
    print("  orphaned confirmed tips (block slot, last slot shown):", res["orphaned_confirmed"])


if __name__ == "__main__":
    main(sys.argv[1:])
