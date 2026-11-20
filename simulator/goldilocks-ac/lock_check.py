"""Why the timed fault needs k slots: a check of each step, in the runs of timed_sweep.py.

The argument, for a run of r slots [s0, s0 + r) without a proposer in A and blocks withheld from A
during it, with no adversary and the online stake split in half:
  1. In slot s0 - 1 every online node confirms the same block, and with steady confirmations the
     expiry of a new fast lock has reached its cap j + k (fast_expiry: min(s + k, max(s + 2, E + c))).
  2. During the run no node confirms a new block: each side's new block holds half of the votes,
     not a strict majority. So no node gains a lock, and every lock is gone after slot s0 - 1 + k.
  3. B, which has every block, keeps its own locks longer, but each of its blocks in the run sits
     on the last common block with half of the votes, so B never builds a chain of its own. The
     first proposal of A after slot s0 - 1 + k has no lock to follow and is built on the
     fork-choice root, here genesis.
  4. A then votes for the new branch. Its half of the votes conflict with B's locks, and a lock
     moves back to an ancestor unless fewer than half of the validators vote against it
     (unlock: 2 |opponents| < n). So B's locks fall back to the root, and every node follows the
     new branch.
For each schedule and r = k - 1, k, k + 1 this records: the latest lock expiry of every online node
at the end of slot s0 - 1, whether any node confirmed a block of slot s0 or later before slot
s0 + k, the first block of an A proposer at slot s0 + k or later and its parent, the first slot in
which a lock of B moved back to the root, and the loss.

Run:  python lock_check.py [--out data/sweeps/lock_check.json] [--seeds 64] [--k 2,4,6]
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor

from timed_sweep import NODES, VALIDATORS, find_run, node_of

AFTER = 20


def run(job):
    kw, seed, r = job
    from model import BLOCKS, GEN, Params, prec
    from sim import Rule, Tracker, World, snapshot

    P = Params(n=VALIDATORS, seed=seed, k=kw)
    owner = node_of()
    A = frozenset(range(NODES // 2))
    s0 = find_run(P, owner, A, r)
    row = {"k": kw, "seed": seed, "r": r, "run_start": s0}
    if s0 is None:
        return row
    sm = P.slot_ms
    w = World(P, NODES, rules=[Rule(s0 * sm, (s0 + r) * sm, frozenset(range(NODES)) - A, A,
                                    frozenset({"block"}), None)])
    tr = Tracker(w)
    seen = {}

    def obs(s, world):
        tr.observe(s, world)
        snaps = [snapshot(n, world.t) for n in world.nodes]
        if s == s0 - 1:
            seen["conf_before"] = sorted({x["conf_slot"] for x in snaps})
            seen["expiry_before"] = sorted({max(e for _, _, e in x["locks"]) - 1 for x in snaps})
        if s0 <= s < s0 + kw:
            if any(x["conf_slot"] >= s0 for x in snaps):
                seen.setdefault("new_conf_in_run", s)

    for s in range(s0 + r + AFTER + 1):
        w.run_slot(s, obs)
    tree = w.nodes[0].phi().tree
    nxt = min((BLOCKS[b] for b in tree if BLOCKS[b].slot >= s0 + kw and owner[BLOCKS[b].proposer] in A),
              key=lambda b: b.slot, default=None)
    back = [e["slot"] for e in w.log_events if e["kind"] == "lock_back" and e.get("node") not in A
            and e["to"] == GEN and e["slot"] >= s0]
    final = w.nodes[0].head(w.t)
    lost = {c for i in tr.first_conf for c, f in tr.first_conf[i].items() if f < s0 and not prec(c, final)}
    row.update({"conf_before": seen.get("conf_before"), "expiry_before": seen.get("expiry_before"),
                "new_conf_in_run": seen.get("new_conf_in_run"),
                "a_block_after": nxt.slot if nxt else None,
                "a_block_after_parent": BLOCKS[nxt.parent].slot if nxt else None,
                "b_lock_back_to_root": min(back, default=None),
                "lost_pre": len(lost)})
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/sweeps/lock_check.json")
    p.add_argument("--seeds", type=int, default=64)
    p.add_argument("--k", default="2,4,6", help="lock windows")
    args = p.parse_args()
    js = [(kw, seed, r) for kw in map(int, args.k.split(",")) for seed in range(args.seeds)
          for r in (kw - 1, kw, kw + 1)]
    with ProcessPoolExecutor(max_tasks_per_child=1) as ex:
        rows = list(ex.map(run, js, chunksize=1))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"rows": rows}, fh, indent=0)
    print(f"{len(rows)} runs -> {args.out}")


if __name__ == "__main__":
    main()
