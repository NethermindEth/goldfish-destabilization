"""Spike: partition the network for D slots, then heal (GST), and measure the damage.

Network model: nodes are split into two groups. Every message sent across the cut during
[start, end) is held by the adversary and released at `end` (+ normal latency). Messages
inside a group flow normally. After `end` the network is synchronous again.

Per node, per slot we record:
- head reorgs: the previous head is not an ancestor of the new head. Depth = number of
  blocks on the abandoned branch (old head back to the common ancestor);
- abandoned available confirmations: the node's non-retracting `latest_confirmed_head`
  is no longer an ancestor of its head;
- safe-confirmation reversals: the new safe-confirmed head does not descend from the
  previous one;
- the stable root and whether it came from the TSQ lock or the G1 fallback.

Run: PYTHONPATH=$SPECS $SPECS/.venv/bin/python partition_run.py --split 2 --start 24 --slots-down 16
"""

import argparse
import heapq
import json
import random
import time
from collections import Counter

import honest_run as hr
from honest_run import spec


class PartitionedNetwork(hr.Network):
    """Asynchrony during [start, end), synchrony (GST) from `end` on.

    Default: messages across groups are held until `end` + latency. With `flap_ms`, group
    membership is reshuffled (same group sizes) every `flap_ms` during the window. With
    `messy_ms`, there are no groups: every message gets an extra exponential delay with
    mean `messy_ms`, capped so it still arrives by `end` + latency (the GST bound).
    """

    def __init__(self, latency_ms, jitter_ms, seed, group_of, start_ms, end_ms, flap_ms=0, messy_ms=0):
        super().__init__(latency_ms, jitter_ms, seed)
        self.group_of = group_of
        self.start_ms, self.end_ms = start_ms, end_ms
        self.flap_ms, self.messy_ms = flap_ms, messy_ms
        self.async_rng = random.Random(f"async-{seed}")  # separate from the jitter draws
        self.flap_groups = {}
        self.held = Counter()

    def groups_at(self, now_ms):
        if not self.flap_ms:
            return self.group_of
        epoch = (now_ms - self.start_ms) // self.flap_ms
        if epoch not in self.flap_groups:
            ids = sorted(self.group_of)
            labels = [self.group_of[i] for i in ids]
            self.async_rng.shuffle(labels)
            self.flap_groups[epoch] = dict(zip(ids, labels))
        return self.flap_groups[epoch]

    def broadcast(self, sender, now_ms, kind, msg):
        self.sent[kind] += 1
        in_window = self.start_ms <= now_ms < self.end_ms
        groups = self.groups_at(now_ms) if in_window else self.group_of
        for node in self.nodes:
            at = now_ms + self.delay(sender, node)
            held = False
            if in_window and node is not sender:
                gst_bound = max(at, self.end_ms + self.latency_ms)
                if self.messy_ms:
                    late = min(at + int(self.async_rng.expovariate(1 / self.messy_ms)), gst_bound)
                    held = late > at
                    at = late
                elif groups[node.id] != groups[sender.id]:
                    at, held = gst_bound, True
                if held:
                    self.held[kind] += 1
            self.record(sender, node, now_ms, at, kind, msg, held=held)
            heapq.heappush(self.queue, (at, next(self.seq), node.id, kind, msg))


def is_ancestor_root(store, anc, desc):
    """True iff block `anc` is an ancestor-or-self of block `desc` (beacon roots)."""
    if anc not in store.blocks or desc not in store.blocks:
        return False
    node = spec.ForkChoiceNode(root=desc, payload_status=spec.PAYLOAD_STATUS_PENDING)
    return spec.get_ancestor(store, node, store.blocks[anc].slot).root == anc


def orphaned_blocks(store, old, new):
    """Blocks on the branch from `old` back to its common ancestor with `new`."""
    count, r = 0, old
    while not is_ancestor_root(store, r, new):
        count += 1
        r = store.blocks[r].parent_root
    return count, int(store.blocks[r].slot)


class Tracker:
    def __init__(self, nodes):
        self.prev_head = {n.id: None for n in nodes}
        self.prev_safe = {n.id: None for n in nodes}
        self.reorgs = {n.id: [] for n in nodes}  # (slot, depth_blocks, ancestor_slot)
        self.safe_reversals = {n.id: [] for n in nodes}
        self.abandoned_conf = {n.id: [] for n in nodes}
        self.stable = {}  # (round) -> {node: (stable_slot, src, root)}
        self.ever_safe = {n.id: set() for n in nodes}
        self.ever_avail = {n.id: set() for n in nodes}

    def abandoned(self, node, which):
        """Ever-confirmed blocks that are not on the node's final head chain."""
        s, head = node.store, node.head().root
        roots = self.ever_safe[node.id] if which == "safe" else self.ever_avail[node.id]
        lost = sorted(int(s.blocks[r].slot) for r in roots if not is_ancestor_root(s, r, head))
        return lost

    def observe(self, slot, node):
        s = node.store
        head = node.head().root
        safe = spec.get_safe_confirmed_head(s)
        ph = self.prev_head[node.id]
        if ph is not None and not is_ancestor_root(s, ph, head):
            depth, anc_slot = orphaned_blocks(s, ph, head)
            self.reorgs[node.id].append((slot, depth, anc_slot))
        ps = self.prev_safe[node.id]
        if ps is not None and not is_ancestor_root(s, ps, safe):
            self.safe_reversals[node.id].append((slot, int(s.blocks[ps].slot)))
        conf_root = s.latest_confirmed_head[0]
        self.ever_safe[node.id].add(safe)
        if conf_root in s.blocks:
            self.ever_avail[node.id].add(conf_root)
        if conf_root in s.blocks and not is_ancestor_root(s, conf_root, head):
            self.abandoned_conf[node.id].append((slot, int(s.blocks[conf_root].slot)))
        self.prev_head[node.id], self.prev_safe[node.id] = head, safe
        rnd = int(spec.compute_round_at_slot(spec.Slot(slot)))
        snap = node.snapshot()
        self.stable.setdefault(rnd, {})[node.id] = (snap["stable_slot"], snap["stable_src"], s.stable_root)
        return snap


def main():
    p = argparse.ArgumentParser()
    hr.add_world_args(p)
    p.add_argument("--trace-blocks", action="store_true")
    p.add_argument("--json", help="write a machine-readable summary to this path")
    p.add_argument("--events", help="write every message and per-node per-slot state to this JSON file")
    p.add_argument("--split", type=int, default=2, help="nodes [0, split) vs [split, nodes)")
    p.add_argument("--start", type=int, default=24, help="first partitioned slot")
    p.add_argument("--slots-down", type=int, default=16, help="partition duration D in slots")
    p.add_argument("--after", type=int, default=24, help="slots to run after healing")
    p.add_argument("--props", help="check stable-root properties (stability_props) and write them here")
    p.add_argument("--groups", help="comma-separated group sizes in nodes, e.g. 3,3,2 (overrides --split)")
    p.add_argument("--flap", type=int, default=0, help="reshuffle group membership every K slots of the cut")
    p.add_argument("--messy-ms", type=int, default=0,
                   help="no groups: every message in the window gets an extra Exp(mean) delay, capped at GST")
    args = p.parse_args()
    hr.TRACE_BLOCKS = args.trace_blocks

    slot_ms = hr.SLOT_MS
    start_ms = args.start * slot_ms
    end_ms = (args.start + args.slots_down) * slot_ms
    if args.groups:
        sizes = [int(x) for x in args.groups.split(",")]
        assert sum(sizes) == args.nodes, "group sizes must add up to --nodes"
        labels = [g for g, size in enumerate(sizes) for _ in range(size)]
        group_of = {i: labels[i] for i in range(args.nodes)}
    else:
        group_of = {i: 0 if i < args.split else 1 for i in range(args.nodes)}
    genesis = hr.make_genesis(args.validators, args.seed)
    net = PartitionedNetwork(args.latency_ms, args.jitter_ms, args.seed, group_of, start_ms, end_ms,
                             flap_ms=args.flap * slot_ms, messy_ms=args.messy_ms)
    assignment = hr.assign_validators(args.validators, args.nodes, args.seed)
    net.nodes = [hr.Node(i, genesis, assignment[i]) for i in range(args.nodes)]
    if args.props:
        import stability_props as sp
        sp.install(net.nodes)
    stake = Counter(group_of[n.id] for n in net.nodes for _ in n.validators)
    total = sum(stake.values())
    groups_desc = " | ".join(
        f"{'ABCDEFGH'[g]}={sorted(i for i in group_of if group_of[i] == g)} ({100 * stake[g] // total}% stake)"
        for g in sorted(set(group_of.values()))
    )
    mode = f"messy Exp({args.messy_ms} ms)" if args.messy_ms else (f"flap every {args.flap} slots" if args.flap else "cut")
    print(f"partition: {groups_desc}; slots [{args.start}, {args.start+args.slots_down}) {mode}, "
          f"heal at slot {args.start+args.slots_down}")
    print("slot | per node: head/safe/stable(src)/h  | finalized(n0) | agree")
    tracker = Tracker(net.nodes)
    total_slots = args.start + args.slots_down + args.after
    t0 = time.perf_counter()
    agree_since = None
    finality_timeline = []  # (slot, finalized_slot) whenever node 0's finalized changes
    if args.events:
        net.events = []
    states = []
    for slot in range(1, total_slots + 1):
        base = slot * slot_ms
        for offset, action in ((0, "s"), (hr.ATT_DUE_MS, "a"), (hr.CONF_DUE_MS, "c"), (hr.FREEZE_DUE_MS, "f")):
            now = base + offset
            net.deliver_until(now)
            for node in net.nodes:
                if action == "s":
                    node.slot_start(slot, now, net)
                elif action == "a":
                    node.attestation_deadline(slot, now, net)
                else:
                    node.tick(spec.on_tick_per_high_resolution, spec.uint64(offset))
            net.deliver_until(now)
        snaps = [tracker.observe(slot, n) for n in net.nodes]
        states.append({"slot": slot, "nodes": snaps})
        if args.props:
            sp.observe_slot(slot, net.nodes)
        if not finality_timeline or finality_timeline[-1][1] != snaps[0]["finalized_slot"]:
            finality_timeline.append((slot, snaps[0]["finalized_slot"]))
        heads = {x["head_slot"] for x in snaps}
        agree = len({n.head().root for n in net.nodes}) == 1
        if agree and agree_since is None:
            agree_since = slot
        elif not agree:
            agree_since = None
        mark = "  CUT" if args.start <= slot < args.start + args.slots_down else ""
        cols = " ".join(
            f"{x['head_slot']:>2}/{x['safe_conf_slot']:>2}/{str(x['stable_slot']):>4}({x['stable_src']})/h{x['chain_height']}"
            for x in snaps
        )
        print(f"{slot:4d} | {cols} | {snaps[0]['finalized_slot']:3d} | {agree}{mark}")
    print(f"\nsimulated {total_slots} slots in {time.perf_counter()-t0:.0f}s; held across cut: {dict(net.held)}")
    print(f"rejections per node: {[dict(n.rejected) for n in net.nodes]}")

    heal = args.start + args.slots_down
    print("\n== results ==")
    for n in net.nodes:
        r = tracker.reorgs[n.id]
        print(
            f"node {n.id} (group {'ABCDEFGH'[group_of[n.id]]}): reorgs={len(r)} "
            f"max_depth={max((d for _, d, _ in r), default=0)} blocks {r[:4]}"
            f" | safe-conf reversals={tracker.safe_reversals[n.id][:3]}"
            f" | abandoned available-conf (first)={tracker.abandoned_conf[n.id][:1]}"
        )
        lost_safe, lost_avail = tracker.abandoned(n, "safe"), tracker.abandoned(n, "avail")
        print(
            f"    ever-confirmed blocks now off-chain: safe={len(lost_safe)} {lost_safe} "
            f"| available={len(lost_avail)} {lost_avail}"
        )
    print(f"heads agree continuously since slot {agree_since} (heal at {heal}; "
          f"{(agree_since - heal) if agree_since else 'never'} slots to reconverge)")
    print("stable root per round (node: slot/src):")
    for rnd in sorted(tracker.stable):
        row = tracker.stable[rnd]
        roots = {v[2] for v in row.values()}
        print(f"  round {rnd}: " + ", ".join(f"n{k}:{v[0]}/{v[1]}" for k, v in sorted(row.items()))
              + ("" if len(roots) == 1 else "   <-- DIVERGENT"))
    if args.events:
        with open(args.events, "w") as fh:
            json.dump({"config": vars(args), "slot_ms": hr.SLOT_MS,
                       "deadlines_ms": [hr.ATT_DUE_MS, hr.CONF_DUE_MS, hr.FREEZE_DUE_MS],
                       "slots_per_round": int(spec.get_slots_per_round_at_slot(spec.Slot(0))),
                       "group_of": group_of, "messages": net.events, "states": states, "outcomes": hr.OUTCOMES}, fh)
    if args.props:
        sp.report(net.nodes, args.start, heal, args.props)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(summarize(args, net, tracker, group_of, agree_since, finality_timeline), fh, indent=1)
    print("finality vote kinds per round:")
    for rnd in sorted({r for n in net.nodes for r in n.vote_kinds}):
        merged = Counter()
        for n in net.nodes:
            merged.update(n.vote_kinds[rnd])
        print(f"  round {rnd}: {dict(merged)}")



def stable_root_relations(store, roots):
    """'same', 'nested' (all on one chain) or 'conflicting' for a set of stable roots."""
    roots = [r for r in roots if r in store.blocks]
    if len(set(roots)) <= 1:
        return "same"
    for a in roots:
        for b in roots:
            if not (is_ancestor_root(store, a, b) or is_ancestor_root(store, b, a)):
                return "conflicting"
    return "nested"


def summarize(args, net, tracker, group_of, agree_since, finality_timeline):
    heal = args.start + args.slots_down
    ref = net.nodes[0].store
    per_node = []
    for n in net.nodes:
        reorgs = tracker.reorgs[n.id]
        per_node.append({
            "node": n.id,
            "group": "ABCDEFGH"[group_of[n.id]],
            "reorgs": len(reorgs),
            "max_reorg_depth": max((d for _, d, _ in reorgs), default=0),
            "safe_retractions": len(tracker.safe_reversals[n.id]),
            "orphaned_safe": len(tracker.abandoned(n, "safe")),
            "orphaned_available": len(tracker.abandoned(n, "avail")),
            "rejected": dict(n.rejected),
        })
    rounds = {}
    for rnd, row in sorted(tracker.stable.items()):
        if all(v[0] is None for v in row.values()):
            continue
        rounds[rnd] = {
            "slots": sorted({v[0] for v in row.values() if v[0] is not None}),
            "sources": dict(Counter(v[1] for v in row.values())),
            "relation": stable_root_relations(ref, [v[2] for v in row.values()]),
        }
    return {
        "config": vars(args),
        "heal_slot": heal,
        "reconverge_slots": (agree_since - heal) if agree_since else None,
        "finality_timeline": finality_timeline,
        "per_node": per_node,
        "stable_rounds": rounds,
        "held": dict(net.held),
    }


if __name__ == "__main__":
    main()
