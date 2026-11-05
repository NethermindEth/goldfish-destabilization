"""Partition the network for D slots, then heal (GST), and measure the damage.

The Goldilocks counterpart of spike/partition_run.py. Nodes are split into groups; every
message sent across the cut during [start, start + D) slots is held and released at the
heal (+ latency). After the heal the network is synchronous again. A second window
(--start2/--slots-down2, optional --groups2) gives the repeated-partition shape.

Per node and slot it records head reorgs, confirmed-tip regressions (step back to an
ancestor, or a switch to a conflicting block), live locks and whether honest nodes hold
conflicting live locks, the FG caches (F, J, h_j, h_max, contest), and agreement.

Run:  python partition_run.py --groups 2,2 --start 24 --slots-down 16
"""

import argparse
import json
import time

from model import BLOCKS, GEN, Params
from sim import Tracker, World


def parse_groups(spec, nodes):
    sizes = [int(x) for x in spec.split(",")]
    assert sum(sizes) == nodes, f"--groups {spec} must sum to --nodes {nodes}"
    group_of, i = {}, 0
    for g, size in enumerate(sizes):
        for _ in range(size):
            group_of[i] = g
            i += 1
    return group_of


def add_world_args(p):
    p.add_argument("--validators", type=int, default=64)
    p.add_argument("--nodes", type=int, default=4)
    p.add_argument("--shares", default=None, help="validator weights per node, e.g. 3,1 (default equal)")
    p.add_argument("--latency-ms", type=int, default=200)
    p.add_argument("--jitter-ms", type=int, default=0)
    p.add_argument("--delta-ms", type=int, default=1500, help="Δ; a slot is 4Δ")
    p.add_argument("--k", type=int, default=4, help="slow window / lock length in slots")
    p.add_argument("--R", type=int, default=8, help="slots per round")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--lean-finality", action="store_true",
                   help="NOT the spec: F advances ignoring a contest, as in the Lean model")


def make_params(args):
    return Params(n=args.validators, delta=args.delta_ms, delta_f=args.delta_ms, R=args.R, k=args.k,
                  delta_t=args.R, seed=args.seed, lean_finality=args.lean_finality)


def short(root):
    return "gen" if root == GEN else f"{BLOCKS[root].slot}"


def main(argv=None):
    p = argparse.ArgumentParser()
    add_world_args(p)
    p.add_argument("--groups", default="2,2", help="node group sizes for the cut, e.g. 2,2 or 3,1 or 2,1,1")
    p.add_argument("--start", type=int, default=24, help="first partitioned slot")
    p.add_argument("--slots-down", type=int, default=16, help="partition duration D in slots (0: no cut)")
    p.add_argument("--start2", type=int, default=None, help="first slot of a second cut")
    p.add_argument("--slots-down2", type=int, default=0)
    p.add_argument("--groups2", default=None, help="group sizes of the second cut (default: --groups)")
    p.add_argument("--sleep", default="", help="asleep windows node:start:end (slots), comma-separated, e.g. 3:24:40")
    p.add_argument("--release-spread-ms", type=int, default=0,
                   help="held messages are released at heal + latency + U(0, spread)")
    p.add_argument("--after", type=int, default=32, help="slots to run after the last heal")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--json", help="write a machine-readable summary")
    p.add_argument("--events", help="write messages + per-slot states for the explorer")
    args = p.parse_args(argv)

    P = make_params(args)
    slot_ms = P.slot_ms
    windows = []
    group_of = parse_groups(args.groups, args.nodes)
    if args.slots_down:
        windows.append((args.start * slot_ms, (args.start + args.slots_down) * slot_ms, group_of))
    if args.start2 is not None and args.slots_down2:
        g2 = parse_groups(args.groups2 or args.groups, args.nodes)
        windows.append((args.start2 * slot_ms, (args.start2 + args.slots_down2) * slot_ms, g2))
    sleep = {}
    for item in filter(None, args.sleep.split(",")):
        nid, a, b = item.split(":")  # slots; fractions allowed (a wake between public times)
        sleep.setdefault(int(nid), []).append((round(float(a) * slot_ms), round(float(b) * slot_ms)))
    heal = max([w[1] // slot_ms for w in windows] + [-(-b // slot_ms) for ws in sleep.values() for _, b in ws],
               default=0)
    shares = [int(x) for x in args.shares.split(",")] if args.shares else None
    world = World(P, args.nodes, args.latency_ms, args.jitter_ms, windows, shares, record=bool(args.events),
                  sleep=sleep, release_spread_ms=args.release_spread_ms)
    stake = {}
    for n in world.nodes:
        stake[group_of[n.id]] = stake.get(group_of[n.id], 0) + len(n.validators)
    print(f"Goldilocks: n={P.n} q={P.q} Δ={P.delta}ms slot={slot_ms}ms R={P.R} k={P.k} KW={P.KW} δt={P.delta_t}")
    if windows:
        print("cut groups: " + " | ".join(
            f"{chr(65+g)}={[i for i in group_of if group_of[i]==g]} ({100*stake[g]//P.n}%)" for g in sorted(stake)))
        for a, b, _ in windows:
            print(f"  cut slots [{a//slot_ms}, {b//slot_ms}), heal (GST) at slot {b//slot_ms}")
    total = max(heal, args.start) + args.after
    tracker = Tracker(world)
    if not args.quiet:
        print("slot | per node: head/conf/F  h:hmax/hj  locks | agree")
    t0 = time.perf_counter()
    for s in range(0, total + 1):
        world.run_slot(s, tracker.observe)
        if args.quiet:
            continue
        snaps = tracker.states[-1]["nodes"]
        cut = any(a <= P.t(s) < b for a, b, _ in windows)
        cols = "  ".join(
            f"{'z' if x['asleep'] else ' '}{x['head_slot']:>3}/{x['conf_slot']:>3}/{x['F_slot']:>3} h{x['head_h']}:{x['hmax']}/{x['hj']}"
            f"{'C' if x['contest'] else ' '} L[{','.join(str(b) for _, b, _ in x['locks'])}]"
            for x in snaps)
        agree = len({x["head"] for x in snaps}) == 1
        print(f"{s:4d} | {cols} | {'=' if agree else 'x'}{'  CUT' if cut else ''}")
    t_end = world.t
    print(f"\nsimulated {total+1} slots in {time.perf_counter()-t0:.1f}s; messages held across the cut: {dict(world.net.held)}")
    summary = summarize(args, world, tracker, heal, group_of, t_end)
    print_summary(summary)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(summary, fh, indent=1)
    if args.events:
        dump_events(args.events, args, world, tracker, group_of, windows)
    return summary


def summarize(args, world, tracker, heal, group_of, t_end):
    P = world.P
    per_node = []
    for n in world.nodes:
        r = tracker.reorgs[n.id]
        per_node.append({
            "node": n.id, "group": chr(65 + group_of[n.id]), "validators": len(n.validators),
            "reorgs": len(r), "max_reorg_depth": max((d for _, d, _ in r), default=0), "reorg_list": r[:6],
            "head_stepbacks": len(tracker.head_stepbacks[n.id]),
            "conf_reversals": tracker.conf_reversals[n.id], "conf_stepbacks": len(tracker.conf_stepbacks[n.id]),
            "orphaned_confirmed": tracker.orphaned_confirmed(n, t_end),
            "last_slot_with_orphaned_conf": max((seen for _, seen in tracker.orphaned_confirmed(n, t_end, True)),
                                                default=None),
            "final_F_slot": BLOCKS[n.fg.F].slot, "final_hj": n.fg.hj, "final_hmax": n.fg.hmax,
        })
    lc_after = [s for s, _ in tracker.lock_conflicts if s >= heal] if heal else []
    hs, cs = tracker.agree_since(1, heal), tracker.agree_since(2, heal)
    return {
        "config": vars(args), "heal_slot": heal,
        "reconverge_head_slots": (hs - heal) if hs is not None and heal else None,
        "reconverge_conf_slots": (cs - heal) if cs is not None and heal else None,
        "agree_head_since": hs, "agree_conf_since": cs,
        "lock_conflict_slots": [s for s, _ in tracker.lock_conflicts],
        "last_lock_conflict_after_heal": max(lc_after) if lc_after else None,
        "finalized_conflict": tracker.fin_conflict,
        "invariant_violations": tracker.invariant_violations[:10]
        + [(e["t"], e["node"], e["what"]) for e in world.log_events if e["kind"] == "violation"][:10],
        "finality_timeline": tracker.finality,
        "contest_slots": [st["slot"] for st in tracker.states if any(x["contest"] for x in st["nodes"])],
        "per_node": per_node,
        "held": dict(world.net.held),
    }


def print_summary(S):
    print("\n== results ==")
    for x in S["per_node"]:
        print(f"node {x['node']} ({x['group']}, {x['validators']} val): reorgs={x['reorgs']} max_depth={x['max_reorg_depth']} "
              f"{x['reorg_list'][:3]} | conf reversals={x['conf_reversals'][:3]} stepbacks={x['conf_stepbacks']} "
              f"| orphaned confirmed={x['orphaned_confirmed']} | F={x['final_F_slot']} hj={x['final_hj']} hmax={x['final_hmax']}")
    heal = S["heal_slot"]
    if heal:
        print(f"heal at slot {heal}: heads agree from slot {S['agree_head_since']} (+{S['reconverge_head_slots']}), "
              f"confirmed tips agree from slot {S['agree_conf_since']} (+{S['reconverge_conf_slots']})")
        cs = S["lock_conflict_slots"]
        print(f"conflicting live locks across honest nodes: {len(cs)} slots"
              + (f" [{cs[0]}..{cs[-1]}], last after heal: {S['last_lock_conflict_after_heal']}" if cs else ""))
    print(f"finalized blocks conflict across nodes: {S['finalized_conflict']}; "
          f"interface-invariant violations: {S['invariant_violations'] or 'none'}")
    print(f"finality timeline (slot -> F slot, node 0): {S['finality_timeline']}")


def dump_events(path, args, world, tracker, group_of, windows):
    P = world.P
    blocks = {r: [b.slot, b.parent, b.proposer, world.node_of.get(b.proposer, -1), len(b.attestations), len(b.votes)]
              for r, b in BLOCKS.items() if r != GEN}
    with open(path, "w") as fh:
        json.dump({
            "protocol": "goldilocks",
            "config": vars(args),
            "params": {"n": P.n, "q": P.q, "delta": P.delta, "slot_ms": P.slot_ms, "R": P.R, "k": P.k,
                       "KW": P.KW, "delta_t": P.delta_t},
            "group_of": group_of,
            "windows": [[a, b, g] for a, b, g in windows],
            "validators": [len(n.validators) for n in world.nodes],
            "blocks": blocks,
            "messages": world.net.events or [],
            "states": tracker.states,
            "log": world.log_events,
        }, fh, default=lambda o: None if o is None else str(o))


if __name__ == "__main__":
    main()
