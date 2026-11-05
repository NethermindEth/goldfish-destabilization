"""How each height ended on the final chain: justified, or skipped by timeouts (progress quorum).

Walks the final chain of node 0 and reports every height change: a justification (h_j moves
to the old height) or a timeout advance (the height moves, h_j does not).

Run:  python height_events.py partition --groups 2,2 --start 48 --slots-down 16 --after 40
      python height_events.py adversary --f 21 --strategy late_j --group-a 0,1 --cut 50:8 --slots 112
"""

import argparse
import contextlib
import io
import sys

from model import ANC, BLOCKS, DEPTH, STATE


def events(head):
    chain = sorted(ANC[head], key=lambda r: DEPTH[r])
    out = []
    for prev, cur in zip(chain, chain[1:]):
        a, b = STATE[prev], STATE[cur]
        if b.h != a.h:
            kind = "justified" if b.hj == a.h else "timeout"
            out.append((BLOCKS[cur].slot, a.h, kind))
    return out


def main():
    mode, rest = sys.argv[1], sys.argv[2:]
    if mode == "partition":
        import partition_run
        captured = {}
        orig = partition_run.Tracker if hasattr(partition_run, "Tracker") else None
        with contextlib.redirect_stdout(io.StringIO()):
            partition_run.main(rest + ["--quiet"])
        from model import BLOCKS as B_
        # the deepest block of the run: every node agrees at the end in these runs
        head = max(B_, key=lambda r: (DEPTH.get(r, 0), r))
    else:
        import adversary
        p = argparse.ArgumentParser(allow_abbrev=False)
        adversary.add_args(p)
        args = p.parse_args(rest)
        world, _, _ = adversary.run(args)
        head = world.nodes[0].head(world.t)
    ev = events(head)
    to = [e for e in ev if e[2] == "timeout"]
    print(f"heights ended: {len(ev)}; by timeout: {len(to)} -> {to}")


if __name__ == "__main__":
    main()
