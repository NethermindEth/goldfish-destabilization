"""Adversary gadget: Byzantine validators that equivocate across a partition.

The honest machinery lives in honest_run.py. Here we add:

- SplitNetwork: a PartitionedNetwork whose adversary can deliver a *different*
  message to each partition group in the same slot (``send_split``). The
  adversary straddles the cut -- its messages are never held -- modelling an
  attacker that controls delivery and shows each honest side only one version of
  an equivocated vote. While both versions never meet in one honest store, the
  spec's equivocation detector (fork-choice ``update_latest_messages``) never
  fires, so the adversary's whole stake counts toward *both* branches' SG grades.

- Adversary: holds a Byzantine validator set (kept out of the honest nodes) and,
  at each attestation deadline, casts equivocating *finality head votes* -- the
  messages that feed ``get_attestation_score`` (G1 numerator) and
  ``get_total_active_voting_weight`` (the relative denominator D). For each
  honest group it points its validators' latest head vote at that group's own
  branch tip, reinforcing the local G1 descent on both sides at once.

This targets the one grade whose threshold is relative (2/3 of live weight D)
rather than absolute (TSQ's 2W/3): quorum intersection does not bound it, so a
sub-1/3 adversary may be able to split or strand the stable chain.

Run: PYTHONPATH=$SPECS $SPECS/.venv/bin/python adversary.py --groups 2,2 \
        --adv-validators 16 --start 16 --slots-down 16 --after 40
"""

import argparse
import heapq
import json
import time
from collections import Counter, defaultdict

import honest_run as hr
import partition_run as pr
from honest_run import spec
from eth_consensus_specs.test.helpers.block import build_empty_block
from eth_consensus_specs.test.helpers.state import state_transition_and_sign_block

FAR_FUTURE_HEIGHT = spec.Height(2**64 - 1)
STUB_SIG = hr.STUB_SIG


class SplitNetwork(hr.Network):
    """Multi-window partition network + adversary per-group directed delivery.

    ``windows`` is a list of (start_ms, end_ms, group_map); honest cross-group
    messages inside a window are held until that window's end (+latency). Between
    windows the network is synchronous (a real heal). The adversary straddles all
    windows and delivers per-group via ``send_split`` (never held)."""

    def __init__(self, latency_ms, jitter_ms, seed, windows, regossip=False):
        super().__init__(latency_ms, jitter_ms, seed)
        self.windows = windows  # [(start_ms, end_ms, {node_id: group})]
        self.start_ms = windows[0][0] if windows else 0
        self.end_ms = windows[-1][1] if windows else 0
        self.held = Counter()
        self.regossip = regossip
        self.gossiped = defaultdict(set)  # node_id -> {msg keys it has already forwarded}

    @staticmethod
    def _key(kind, msg):
        if kind == "block":
            return ("block", bytes(spec.hash_tree_root(msg.message)))
        return (kind, bytes(spec.hash_tree_root(msg)))

    def deliver_until(self, t_ms):
        while self.queue and self.queue[0][0] <= t_ms:
            at, _, dst, kind, msg = heapq.heappop(self.queue)
            node = self.nodes[dst]
            node.receive(kind, msg)
            if not self.regossip:
                continue
            key = self._key(kind, msg)
            if key in self.gossiped[dst]:
                continue
            self.gossiped[dst].add(key)
            # Flood to peers (gossipsub): cross-partition copies are held to the
            # window's GST bound, intra-partition copies ride normal latency.
            w = self.active_window(at)
            for other in self.nodes:
                if other.id == dst:
                    continue
                arr = at + self.latency_ms
                if w is not None and w[2][other.id] != w[2][dst]:
                    arr = max(arr, w[1] + self.latency_ms)
                heapq.heappush(self.queue, (arr, next(self.seq), other.id, kind, msg))

    def active_window(self, now_ms):
        for w in self.windows:
            if w[0] <= now_ms < w[1]:
                return w
        return None

    def groups_at(self, now_ms):
        w = self.active_window(now_ms)
        return w[2] if w else None

    straggle_ms = 0
    straggle_set = ()  # node ids that receive straggler (late) available votes

    def broadcast(self, sender, now_ms, kind, msg):
        self.sent[kind] += 1
        w = self.active_window(now_ms)
        for node in self.nodes:
            at = now_ms + self.delay(sender, node)
            held = False
            if w is not None and node is not sender and w[2][node.id] != w[2][sender.id]:
                at, held = max(at, w[1] + self.latency_ms), True
                self.held[kind] += 1
            # Straggler delivery (within the GST delay budget): honest available
            # votes reach the straggler set only AFTER their 50% confirmation
            # freeze, so those nodes freeze a different available-confirmation
            # snapshot -- the spec's admitted-unproven cross-node agreement.
            if (self.straggle_ms and kind == "avail" and node is not sender
                    and node.id in self.straggle_set):
                at += self.straggle_ms
            self.record(sender, node, now_ms, at, kind, msg, held=held)
            heapq.heappush(self.queue, (at, next(self.seq), node.id, kind, msg))

    def send_halves_timed(self, at_ms, kind, msg_a, msg_b, halves):
        """Deliver msg_a to halves[0], msg_b to halves[1], arriving at absolute
        time at_ms (used to land votes just before honest nodes' view-freeze)."""
        for node in self.nodes:
            msg = msg_a if node.id in halves[0] else msg_b
            self.sent[kind] += 1
            heapq.heappush(self.queue, (at_ms, next(self.seq), node.id, kind, msg))

    def send_halves(self, now_ms, kind, msg_a, msg_b, halves):
        """Deliver msg_a to honest nodes in halves[0], msg_b to halves[1] (adversary
        controls per-recipient delivery; no partition, no holds)."""
        pick = {nid: (msg_a if nid in halves[0] else msg_b) for nid in range(len(self.nodes))}
        for node in self.nodes:
            msg = pick[node.id]
            self.sent[kind] += 1
            at = now_ms + self.latency_ms
            heapq.heappush(self.queue, (at, next(self.seq), node.id, kind, msg))

    def send_split(self, now_ms, kind, msg_by_group, leak=True):
        """Deliver msg_by_group[g] to group g immediately. The OTHER groups'
        versions also reach g, but only at the GST bound (window end + latency) --
        modelling that the equivocation evidence is gossiped and eventually
        crosses the heal, where the spec's detector can see both versions. With
        leak=False the cross-group copies are suppressed (evidence never meets)."""
        w = self.active_window(now_ms)
        groups = w[2] if w else {n.id: 0 for n in self.nodes}
        gst_bound = (w[1] + self.latency_ms) if w else (now_ms + self.latency_ms)
        for node in self.nodes:
            g = groups[node.id]
            own = msg_by_group.get(g)
            if own is not None:
                self.sent[kind] += 1
                at = now_ms + self.latency_ms
                self.record(self.nodes[node.id], node, now_ms, at, kind, own, held=False)
                heapq.heappush(self.queue, (at, next(self.seq), node.id, kind, own))
            if leak:
                for og, msg in msg_by_group.items():
                    if og == g or msg is None:
                        continue
                    at = max(now_ms + self.latency_ms, gst_bound)
                    self.record(self.nodes[node.id], node, now_ms, at, kind, msg, held=True)
                    heapq.heappush(self.queue, (at, next(self.seq), node.id, kind, msg))


class Adversary:
    """Byzantine controller. Omniscient (reads honest heads directly), equivocates
    finality head votes per partition group, and can equivocate proposals."""

    def __init__(self, validators, nodes, group_of, net, equiv_proposer=False, strategy="tip",
                 equiv_target=False, leak=True):
        self.validators = set(validators)
        self.nodes = nodes
        self.group_of = group_of
        self.net = net
        self.equiv_proposer = equiv_proposer
        self.equiv_target = equiv_target
        self.leak = leak
        self.strategy = strategy
        self.groups = sorted(set(group_of.values()))
        # One honest reference node per group, to read that group's branch tip/state.
        self.ref = {}
        for g in self.groups:
            self.ref[g] = next(n for n in nodes if group_of[n.id] == g)
        self.cast = []  # (slot, group, head_root) equivocated head votes actually sent
        self.proposed = []  # (slot, [roots]) adversary proposals

    def build_block(self, slot, parent_root, proposer, ref_store):
        """A valid (empty-body) signed block for an adversary proposer on parent_root."""
        state = ref_store.block_states[parent_root].copy()
        block = build_empty_block(spec, state, slot=spec.Slot(slot), proposer_index=proposer)
        block.parent_root = parent_root
        return state_transition_and_sign_block(spec, state, block)

    def propose(self, slot, now_ms):
        """Propose for any adversary proposer this slot. During the window with
        --equiv-proposer, deliver a DISTINCT block to each group (forces a split
        even where honest views would merge); otherwise one block per local view."""
        in_window = self.net.active_window(now_ms) is not None
        built = {}
        for g in self.groups:
            ref = self.ref[g]
            store = ref.store
            head_root = ref.head().root
            parent_root = spec.get_proposer_head(store, head_root, spec.Slot(slot))
            state = spec.get_current_slot_state(store, parent_root)
            proposer = spec.get_beacon_proposer_index(state)
            if proposer not in self.validators:
                continue
            built[g] = self.build_block(slot, parent_root, proposer, store)
        if not built:
            return
        roots = {g: spec.hash_tree_root(b.message) for g, b in built.items()}
        if in_window:
            # Each side gets its own local-head block (naturally separated), or a
            # deliberately distinct block per group under --equiv-proposer.
            self.net.send_split(now_ms, "block", dict(built), leak=self.leak)
            self.proposed.append((slot, [hr.short(r) for r in roots.values()]))
        else:
            # Single network view: one block to everyone.
            b = next(iter(built.values()))
            for node in self.nodes:
                at = now_ms + self.net.latency_ms
                self.net.sent["block"] += 1
                # record it for the explorer too: otherwise the final-chain walk stops at the first
                # adversary block and every older block is drawn as orphaned
                self.net.record(node, node, now_ms, at, "block", b, held=False)
                heapq.heappush(self.net.queue, (at, next(self.net.seq), node.id, "block", b))
            self.proposed.append((slot, [hr.short(spec.hash_tree_root(b.message))]))

    def group_target(self, g, slot):
        """The head root this group's votes should point at, per strategy."""
        ref = self.ref[g]
        if self.strategy == "tip":
            return ref.head().root
        if self.strategy == "freeze":  # point at the group's safe-confirmed head
            return spec.get_safe_confirmed_head(ref.store)
        return ref.head().root

    def equivocate_finality(self, slot, now_ms):
        """Per committee, build the adversary validators' head vote pointing at
        each group's own branch, and send both versions in one call so each group
        gets its version now and (unless --no-leak) the conflicting version at the
        GST bound, where the spec's equivocation detector can see both."""
        by_committee = defaultdict(dict)  # cidx -> {group: att}
        for g in self.groups:
            head = self.group_target(g, slot)
            ref = self.ref[g]
            store = ref.store
            if head not in store.blocks:
                continue
            state = spec.get_current_slot_state(store, head)
            n_committees = spec.get_committee_count_per_slot(
                state, spec.compute_epoch_at_slot(slot)
            )
            target, height = spec.Checkpoint(), spec.Height(0)
            if self.equiv_target:
                cand = state.current_height_target
                if (cand.root in store.blocks
                        and store.blocks[cand.root].slot == cand.slot
                        and cand.slot <= slot):
                    target, height = cand, spec.Height(state.current_height)
            data = spec.AttestationData(
                slot=spec.Slot(slot), beacon_block_root=head, target=target,
                height=height, finality_target=spec.Checkpoint(),
                finality_height=FAR_FUTURE_HEIGHT,
            )
            cast_any = False
            for cidx in range(n_committees):
                committee = spec.get_beacon_committee(state, spec.Slot(slot), spec.CommitteeIndex(cidx))
                members = {v for v in committee if v in self.validators}
                if not members:
                    continue
                att = hr.Node.build_attestation(state, data, {cidx: (data, members)})
                if att is not None:
                    by_committee[cidx][g] = att
                    cast_any = True
            if cast_any:
                self.cast.append((slot, g, hr.short(head)))
        for cidx, msg_by_group in by_committee.items():
            self.net.send_split(now_ms, "att", msg_by_group, leak=self.leak)

    def balance_available(self, slot, now_ms, halves):
        """Classic balancing attack on the Goldfish available layer, NO partition:
        split the adversary's current-slot available-committee seats to vote the
        two heaviest competing children, delivering branch A's vote to one honest
        half and branch B's to the other, to keep the two halves on different
        Goldfish heads. Non-equivocating (each seat votes once) => detection-immune."""
        ref = self.nodes[0]
        store = ref.store
        committee = store.available_committees.get(spec.Slot(slot))
        if committee is None:
            return
        seats = [i for i, v in enumerate(committee) if v in self.validators]
        if not seats:
            return
        # Two competing branches: the two heaviest children of the confirmed head.
        base = spec.get_available_confirmation_head(store)
        blocks = spec.get_filtered_block_tree(store)
        kids = [c for c in spec.get_node_children(store, blocks, base)
                if spec.is_in_filtered_block_tree(store, blocks, c)]
        if len(kids) < 2:
            return  # no live fork to balance this slot
        kids = sorted(kids, key=lambda c: c.root)[:2]
        msgs = {}
        for b_idx, child in enumerate(kids):
            data = spec.get_available_attestation_data(store, child)
            bits = spec.Bitvector[spec.AVAILABLE_COMMITTEE_SIZE]()
            for s in seats:
                bits[s] = True
            msgs[b_idx] = spec.AvailableAttestation(aggregation_bits=bits, data=data, signature=STUB_SIG)
        # half 0 gets branch 0's vote, half 1 gets branch 1's vote
        self.net.send_halves(now_ms, "avail", msgs[0], msgs[1], halves)
        self.cast.append((slot, -1, "balance"))

    def timing_bounce(self, slot, base_ms, halves):
        """Sub-slot timing / bouncing attack: at slot start, pre-schedule split
        available-vote boosts to land at each honest half JUST BEFORE its view
        freeze (so the two halves freeze on different Goldfish heads). Uses each
        half's own reference node to pick the branch to reinforce there, trying to
        keep two branches alive indefinitely."""
        import honest_run as _hr
        att_due = _hr.ATT_DUE_MS
        msgs = {}
        for hi, half in enumerate(halves):
            ref = self.nodes[half[0]] if half else self.nodes[0]
            store = ref.store
            committee = store.available_committees.get(spec.Slot(slot))
            if committee is None:
                return
            seats = [i for i, v in enumerate(committee) if v in self.validators]
            if not seats:
                return
            # reinforce THIS half's current head (keep it where it is -> sustain split)
            head = ref.head().root
            try:
                data = spec.get_available_attestation_data(store, ref.head())
            except Exception:
                return
            bits = spec.Bitvector[spec.AVAILABLE_COMMITTEE_SIZE]()
            for s in seats:
                bits[s] = True
            msgs[hi] = spec.AvailableAttestation(aggregation_bits=bits, data=data, signature=STUB_SIG)
        if 0 in msgs and 1 in msgs:
            # land at the available-vote deadline, before the 75% view freeze
            self.net.send_halves_timed(base_ms + att_due, "avail", msgs[0], msgs[1], halves)
            self.cast.append((slot, -2, "bounce"))

    def act(self, slot, now_ms, halves=None):
        if halves is not None:
            self.balance_available(slot, now_ms, halves)
        else:
            self.equivocate_finality(slot, now_ms)


def assign_with_adversary(n_validators, n_honest_nodes, adv_count, seed):
    """Validator indices: last ``adv_count`` go to the adversary, the rest are
    round-robin across the honest nodes (seeded shuffle preserved)."""
    indices = list(range(n_validators))
    if seed:
        import random
        random.Random(f"assign-{seed}").shuffle(indices)
    adv = indices[n_validators - adv_count:]
    honest = indices[: n_validators - adv_count]
    per_node = [honest[i::n_honest_nodes] for i in range(n_honest_nodes)]
    return per_node, adv


def canonical_chain(nodes):
    """Union block table and the deepest finalized-consistent head across nodes,
    used to decide which blocks are orphaned at the end."""
    blocks = {}
    for n in nodes:
        blocks.update(n.store.blocks)
    # Reference head: the node whose head has the highest slot (deepest canonical).
    ref = max(nodes, key=lambda n: n.store.blocks[n.head().root].slot)
    return blocks, ref.head().root, ref.store


def is_ancestor_in(blocks, anc, desc):
    if anc not in blocks or desc not in blocks:
        return False
    r = desc
    anc_slot = blocks[anc].slot
    while r in blocks and blocks[r].slot > anc_slot:
        r = blocks[r].parent_root
    return r == anc


def main():
    p = argparse.ArgumentParser()
    hr.add_world_args(p)
    p.add_argument("--adv-validators", type=int, default=16, help="Byzantine stake (validators)")
    p.add_argument("--honest-nodes", type=int, default=4, help="number of honest nodes")
    p.add_argument("--groups", help="comma group sizes over honest nodes, e.g. 2,2")
    p.add_argument("--split", type=int, default=2)
    p.add_argument("--start", type=int, default=16)
    p.add_argument("--slots-down", type=int, default=16)
    p.add_argument("--start2", type=int, default=0, help="second partition window start (0=none)")
    p.add_argument("--slots-down2", type=int, default=0)
    p.add_argument("--after", type=int, default=40)
    p.add_argument("--strategy", default="tip", choices=["tip", "freeze"])
    p.add_argument("--equiv-proposer", action="store_true")
    p.add_argument("--equiv-target", action="store_true", help="adversary equivocates justification targets too")
    p.add_argument("--passive", action="store_true", help="adversary holds validators but casts nothing (control)")
    p.add_argument("--adv-stop", type=int, default=0, help="adversary goes fully silent after this slot (0=never)")
    p.add_argument("--no-leak", action="store_true", help="suppress cross-group leakage of equivocation evidence")
    p.add_argument("--regossip", action="store_true", help="honest nodes re-flood every first-seen message (gossipsub)")
    p.add_argument("--balance", action="store_true", help="Goldfish balancing attack (no partition; split available votes across honest halves)")
    p.add_argument("--timing", action="store_true", help="sub-slot bouncing: pre-schedule split available boosts to land before each half's view freeze")
    p.add_argument("--straggle-ms", type=int, default=0, help="delay honest available votes to half the nodes by this much (straggler snapshot attack)")
    p.add_argument("--sync", action="store_true")
    p.add_argument("--json", help="write a machine-readable summary here")
    p.add_argument("--events", help="write per-message + per-slot state JSON for the explorer (make_figures.py)")
    p.add_argument("--trace-blocks", action="store_true")
    args = p.parse_args()
    hr.TRACE_BLOCKS = args.trace_blocks
    hr.SYNC_MISSING = args.sync

    slot_ms = hr.SLOT_MS
    start_ms, end_ms = args.start * slot_ms, (args.start + args.slots_down) * slot_ms
    nh = args.honest_nodes
    if args.groups:
        sizes = [int(x) for x in args.groups.split(",")]
        assert sum(sizes) == nh, "group sizes must add up to --honest-nodes"
        labels = [g for g, size in enumerate(sizes) for _ in range(size)]
        group_of = {i: labels[i] for i in range(nh)}
    else:
        group_of = {i: (0 if i < args.split else 1) for i in range(nh)}

    windows = [] if args.balance else [(start_ms, end_ms, group_of)]
    if args.start2 and not args.balance:
        windows.append((args.start2 * slot_ms, (args.start2 + args.slots_down2) * slot_ms, group_of))
    halves = (([n for n in range(nh) if n % 2 == 0], [n for n in range(nh) if n % 2 == 1])
              if (args.balance or args.timing) else None)
    genesis = hr.make_genesis(args.validators, args.seed)
    net = SplitNetwork(args.latency_ms, args.jitter_ms, args.seed, windows, regossip=args.regossip)
    if args.straggle_ms:
        net.straggle_ms = args.straggle_ms
        net.straggle_set = tuple(n for n in range(nh) if n % 2 == 1)
    honest_assign, adv_validators = assign_with_adversary(args.validators, nh, args.adv_validators, args.seed)
    net.nodes = [hr.Node(i, genesis, honest_assign[i]) for i in range(nh)]
    adversary = Adversary(adv_validators, net.nodes, group_of, net,
                          equiv_proposer=args.equiv_proposer, strategy=args.strategy,
                          equiv_target=args.equiv_target, leak=not args.no_leak)

    W = args.validators
    f = args.adv_validators
    stake = Counter(group_of[n.id] for n in net.nodes for _ in n.validators)
    total_honest = sum(stake.values())
    desc = " | ".join(
        f"{'ABCDEFGH'[g]}={sorted(i for i in group_of if group_of[i]==g)} "
        f"({100*stake[g]//W}% of W)" for g in sorted(set(group_of.values()))
    )
    print(f"validators W={W}, adversary f={f} ({100*f//W}% of W, honest {total_honest} = {100*total_honest//W}%)")
    print(f"honest groups: {desc}; partition [{args.start},{args.start+args.slots_down}), strategy={args.strategy}")
    print("slot | per honest node: head/safe/stable(src)/h | fin(n0) | agree  | adv-equiv")

    tracker = pr.Tracker(net.nodes)
    total_slots = args.start + args.slots_down + args.after
    t0 = time.perf_counter()
    agree_since = None
    fin_timeline = []
    states = []  # per-slot per-node snapshots for the explorer
    if args.events:
        net.events = []
    # orphan-vote log: honest validator cast a target/finality vote; recorded with the root.
    target_votes = []  # (slot, round, node, height, target_root)
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
            silent = args.passive or (args.adv_stop and slot > args.adv_stop)
            if action == "s" and not silent:
                adversary.propose(slot, now)  # adversary proposers build (maybe equivocating) blocks
                if args.timing:
                    adversary.timing_bounce(slot, base, halves)  # pre-schedule pre-freeze boosts
            if action == "a" and not silent and not args.timing:
                adversary.act(slot, now, halves=halves)  # adversary votes right after honest finality duty
            net.deliver_until(now)
        # record honest target/finality votes cast this slot (from duty histories)
        rnd = int(spec.compute_round_at_slot(spec.Slot(slot)))
        for node in net.nodes:
            for v, d in node.duties.items():
                data = d.signed_attestation_at_round.get(rnd)
                if data is not None and data.target != spec.Checkpoint():
                    target_votes.append((slot, rnd, node.id, int(data.height), data.target.root))
        snaps = [tracker.observe(slot, n) for n in net.nodes]
        if args.events:
            states.append({"slot": slot, "nodes": snaps})
        if not fin_timeline or fin_timeline[-1][1] != snaps[0]["finalized_slot"]:
            fin_timeline.append((slot, snaps[0]["finalized_slot"]))
        agree = len({n.head().root for n in net.nodes}) == 1
        if agree and agree_since is None:
            agree_since = slot
        elif not agree:
            agree_since = None
        mark = "  CUT" if net.active_window(base) is not None else ""
        cols = " ".join(
            f"{x['head_slot']:>2}/{x['safe_conf_slot']:>2}/{str(x['stable_slot']):>4}({x['stable_src']})/h{x['chain_height']}"
            for x in snaps
        )
        nequiv = sum(1 for c in adversary.cast if c[0] == slot)
        print(f"{slot:4d} | {cols} | {snaps[0]['finalized_slot']:3d} | {str(agree):5s}{mark} | eq={nequiv}")

    heal = args.start + args.slots_down
    blocks, canon_head, canon_store = canonical_chain(net.nodes)

    # Orphaned honest target votes: a target checkpoint not on the canonical chain.
    orphan_votes = [
        tv for tv in target_votes
        if tv[4] in blocks and not is_ancestor_in(blocks, tv[4], canon_head)
    ]
    # Distinct conflicting committed stable roots across honest nodes, per round
    # (using the union block table so cross-partition roots are comparable).
    conflicting_rounds = []
    for rnd, row in sorted(tracker.stable.items()):
        roots = [v[2] for v in row.values() if v[0] is not None and v[2] in blocks]
        rel = _relation(blocks, roots)
        if rel == "conflicting":
            conflicting_rounds.append((rnd, rel, {k: (v[0], v[1]) for k, v in row.items()}))

    print("\n== results ==")
    print(f"heads agree continuously since slot {agree_since} (heal at {heal}; "
          f"{(agree_since-heal) if agree_since else 'never'} slots to reconverge)")
    print(f"final finalized slot (node0): {net.nodes[0].store.finalized_checkpoint.slot}; "
          f"timeline {fin_timeline}")
    fin_after_heal = [s for s, fs in fin_timeline if s > heal and fs > 0]
    print(f"first finalization change after heal: {fin_after_heal[0] if fin_after_heal else 'NONE (liveness stalled)'}")
    print(f"adversary equivocated head votes: {len(adversary.cast)} "
          f"(e.g. {adversary.cast[:4]})")
    print(f"honest target votes cast: {len(target_votes)}; "
          f"ORPHANED honest target votes: {len(orphan_votes)}")
    for tv in orphan_votes[:8]:
        print(f"    slot {tv[0]} r{tv[1]} node{tv[2]} h{tv[3]} target={hr.short(tv[4])} (orphaned)")
    print(f"rounds with CONFLICTING committed stable roots across honest nodes: "
          f"{[c[0] for c in conflicting_rounds]}")
    for rnd, rel, row in conflicting_rounds[:6]:
        print(f"    round {rnd}: {row}")
    # finality safety: do any two honest nodes have conflicting finalized checkpoints?
    fins = {n.id: n.store.finalized_checkpoint.root for n in net.nodes}
    safety = _relation(blocks, list(fins.values()))
    print(f"finalized checkpoints across honest nodes: relation={safety} "
          f"({ {k: hr.short(v) for k, v in fins.items()} })")
    # Equivocation DETECTION: are the adversary's validators ever caught (added to
    # store.equivocating_indices)? If never, the attack evades slashing-style exclusion.
    adv_set = adversary.validators
    detect = {}
    for n in net.nodes:
        eq = set(n.store.equivocating_indices)
        detect[n.id] = len(eq & adv_set)
    print(f"adversary validators ({len(adv_set)}) detected as equivocators per honest node: {detect}")
    # G0/grade denominator D and safe-conf per node at the end (is the veto still live?)
    end = {n.id: (int(spec.get_total_active_voting_weight(n.store)),
                  int(n.store.blocks[spec.get_safe_confirmed_head(n.store)].slot)) for n in net.nodes}
    print(f"end-of-run (D, safe_conf_slot) per node: {end}")

    if args.json:
        out = {
            "config": vars(args),
            "heal_slot": heal,
            "reconverge_slots": (agree_since - heal) if agree_since else None,
            "finality_timeline": fin_timeline,
            "final_finalized_slot": int(net.nodes[0].store.finalized_checkpoint.slot),
            "first_fin_change_after_heal": fin_after_heal[0] if fin_after_heal else None,
            "n_adv_equivocations": len(adversary.cast),
            "n_honest_target_votes": len(target_votes),
            "n_orphaned_target_votes": len(orphan_votes),
            "orphaned_target_votes": [[tv[0], tv[1], tv[2], tv[3], hr.short(tv[4])] for tv in orphan_votes],
            "conflicting_stable_root_rounds": [c[0] for c in conflicting_rounds],
            "finalized_relation": safety,
        }
        with open(args.json, "w") as fh:
            json.dump(out, fh, indent=1)
    if args.events:
        # Config shaped for make_figures.compact(): it reads nodes/split/start/
        # slots_down/seed/latency_ms/jitter_ms/validators. Map honest_nodes->nodes.
        cfg = dict(vars(args))
        cfg["nodes"] = nh
        cfg.setdefault("split", args.split)
        with open(args.events, "w") as fh:
            json.dump({
                "config": cfg, "slot_ms": slot_ms,
                "deadlines_ms": [hr.ATT_DUE_MS, hr.CONF_DUE_MS, hr.FREEZE_DUE_MS],
                "slots_per_round": int(spec.get_slots_per_round_at_slot(spec.Slot(0))),
                "group_of": {str(k): v for k, v in group_of.items()},
                "messages": net.events or [], "states": states, "outcomes": hr.OUTCOMES,
            }, fh)
        print(f"wrote explorer events -> {args.events} ({len(net.events or [])} msgs, {len(states)} slots)")
    print("finality vote kinds per round:")
    for rnd in sorted({r for n in net.nodes for r in n.vote_kinds}):
        merged = Counter()
        for n in net.nodes:
            merged.update(n.vote_kinds[rnd])
        print(f"  round {rnd}: {dict(merged)}")


def _relation(blocks, roots):
    roots = [r for r in roots if r in blocks]
    if len(set(roots)) <= 1:
        return "same"
    for a in roots:
        for b in roots:
            if not (is_ancestor_in(blocks, a, b) or is_ancestor_in(blocks, b, a)):
                return "conflicting"
    return "nested"


if __name__ == "__main__":
    main()
