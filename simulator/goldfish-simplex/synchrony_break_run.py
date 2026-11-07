"""Reproduce available- and safe-confirmation permanence failure under strict synchrony.

Scenario (see ../../reports/goldfish-simplex-synchrony-confirmation-failure.md):
- N = 64 equal-stake validators across 4 nodes (16 validators = 25% stake per node):
  - Nodes 0, 1: "Early Honest" (50% of total stake = 32 validators)
  - Node 2:     "Late Honest"  (25% of total stake = 16 validators)
  - Node 3:     "Adversary"    (25% of total stake = 16 validators)
- Network is strictly synchronous: slot = 6000 ms, Delta = 1500 ms (25%).
  Every message is delivered within <= 1400 ms < Delta:
  - Normal honest-to-honest latency = 200 ms.
- In a target mid-round slot `s_attack` where Node 3 is the scheduled proposer:
  1. Node 3 proposes a single valid block B_s (zero equivocation), sending it so that:
     - Nodes 0 and 1 receive B_s at t = 1400 ms (before the 1500 ms attestation deadline)
       and vote for B_s at 1500 ms.
     - Node 2 receives B_s at t = 1600 ms (just after the 1500 ms attestation deadline,
       still <= Delta = 1500 ms if sent at t = 200 ms) and therefore votes for the parent
       block B_{s-1} at 1500 ms.
  2. At t = 3000 ms (50% confirmation freeze of slot s_attack):
     - All honest nodes freeze `frozen_available_votes[s_attack]`, containing the votes of
       Nodes 0, 1 (for B_s, ~2/3 of honest seats) and Node 2 (for B_{s-1}, ~1/3 of honest seats).
     - Because ~2/3 > 1/2 (and < 3/4 of 512), B_s is armed for delayed confirmation in slot s+1.
  3. At t = 3200 ms (between 50% and 75% of slot s_attack):
     - Node 3 broadcasts its single valid available vote for B_{s-1}, arriving at all honest
       nodes at t = 3400 ms (< 4500 ms view-freeze deadline).
     - Together with Node 2's votes for B_{s-1}, the non-supporting votes now make up >= 50%
       of `available_votes[s_attack]`, so B_s's score in `get_head` drops to <= 50%!
  4. In slot s_attack + 1:
     - At t = 0 ms, the honest proposer of slot s_attack + 1 calls `get_head`, sees B_s fail
       the > 50% Goldfish threshold, and builds B_{s+1} on top of B_{s-1} (orphaning B_s).
     - At t = 1500 ms (25%), all honest nodes vote for B_{s+1}.
     - At t = 3000 ms (50%), `update_confirmation_heads` evaluates `frozen_available_votes[s_attack]`
       and CONFIRMS the already-orphaned block B_s in `live_confirmed_head`,
       `latest_confirmed_head` (available confirmation), AND `get_safe_confirmed_head` (safe
       confirmation, because 1 slot's finality cohort on B_{s+1} is 1/8 = 12.5% < 1/3 of D)!
  5. In slot s_attack + 2:
     - At t = 3000 ms (50%), `live_confirmed_head` and `get_safe_confirmed_head` switch to
       B_{s+1} (a safe-confirmation reversal!), while `latest_confirmed_head` remains stuck on
       the orphaned block B_s!

Run (from simulator/goldfish-simplex/):
    PYTHONPATH=$SPECS $SPECS/.venv/bin/python synchrony_break_run.py
"""

import argparse
import heapq
import json

import honest_run as hr
from honest_run import spec
from partition_run import Tracker, is_ancestor_root


class SynchronousAdversaryNetwork(hr.Network):
    """Synchronous network (all delays <= 1400 ms < Delta = 1500 ms) with an adversarial node."""

    def __init__(self, latency_ms, seed, adv_node_id, attack_slot, early_honest_ids, late_honest_ids):
        super().__init__(latency_ms, jitter_ms=0, seed=seed)
        self.adv_node_id = adv_node_id
        self.attack_slot = attack_slot
        self.early_honest_ids = set(early_honest_ids)
        self.late_honest_ids = set(late_honest_ids)
        self.max_delay_observed_ms = 0

    def broadcast_custom(self, sender, send_ms, deliver_map, kind, msg):
        """Send `msg` at `send_ms` with explicit per-recipient delivery times `deliver_map[dst_id]`."""
        self.sent[kind] += 1
        for node in self.nodes:
            at = deliver_map.get(node.id, send_ms + self.delay(sender, node))
            if node is not sender:
                self.max_delay_observed_ms = max(self.max_delay_observed_ms, at - send_ms)
            self.record(sender, node, send_ms, at, kind, msg)
            heapq.heappush(self.queue, (at, next(self.seq), node.id, kind, msg))

    def broadcast(self, sender, now_ms, kind, msg):
        for node in self.nodes:
            if node is not sender:
                self.max_delay_observed_ms = max(self.max_delay_observed_ms, self.delay(sender, node))
        super().broadcast(sender, now_ms, kind, msg)


class AdversarialProposerNode(hr.Node):
    """Node that follows the protocol honestly except in `attack_slot` (and optionally `attack_slot + 1`)."""

    def __init__(self, node_id, genesis_state, validators, attack_slot):
        super().__init__(node_id, genesis_state, validators)
        self.attack_slot = attack_slot
        self.parent_of_attack_block = None
        self.attack_block_root = None

    def slot_start(self, slot, now_ms, net):
        if slot != self.attack_slot:
            return super().slot_start(slot, now_ms, net)

        # In attack_slot, build the valid block B_s at t = 0, but send it at t = 200 ms so that:
        # - Early honest nodes receive it at t = 1400 ms (delay = 1200 ms < Delta = 1500 ms)
        # - Late honest nodes receive it at t = 1600 ms (delay = 1400 ms < Delta = 1500 ms)
        self.tick(spec.on_tick, self.store.genesis_time + now_ms // 1000)
        head_root = self.head().root
        parent_root = spec.get_proposer_head(self.store, head_root, spec.Slot(slot))
        state = spec.get_current_slot_state(self.store, parent_root)
        proposer = spec.get_beacon_proposer_index(state)
        if proposer not in self.validators:
            return
        self.parent_of_attack_block = parent_root
        state = self.store.block_states[parent_root].copy()
        block = hr.build_empty_block(spec, state, slot=spec.Slot(slot), proposer_index=proposer)
        block.parent_root = parent_root
        pre = state.copy()
        spec.process_slots(pre, spec.Slot(slot))
        block.body.attestations = self.select_attestations(pre, parent_root)
        signed = hr.state_transition_and_sign_block(spec, state, block)
        self.attack_block_root = signed.message.hash_tree_root()

        send_ms = now_ms + 200  # emitted at 200 ms into slot s
        deliver_map = {self.id: now_ms}
        for nid in net.early_honest_ids:
            deliver_map[nid] = now_ms + 1400  # arrives at 1400 ms (100 ms before 25% deadline)
        for nid in net.late_honest_ids:
            deliver_map[nid] = now_ms + 1600  # arrives at 1600 ms (100 ms after 25% deadline)
        net.broadcast_custom(self, send_ms, deliver_map, "block", signed)

    def available_duty(self, slot, now_ms, net):
        if slot != self.attack_slot:
            return super().available_duty(slot, now_ms, net)

        # In attack_slot, withhold our available vote for the parent block B_{s-1} until t = 3200 ms
        # (after the 3000 ms confirmation freeze, before the 4500 ms view freeze).
        store = self.store
        committee = store.available_committees.get(spec.Slot(slot))
        if committee is None:
            return
        positions = [i for i, v in enumerate(committee) if v in self.validators]
        if not positions:
            return
        parent_node = spec.ForkChoiceNode(
            root=self.parent_of_attack_block, payload_status=spec.PAYLOAD_STATUS_EMPTY
        )
        data = spec.get_available_attestation_data(store, parent_node)
        bits = spec.Bitvector[spec.AVAILABLE_COMMITTEE_SIZE]()
        for i in positions:
            bits[i] = True
        att = spec.AvailableAttestation(aggregation_bits=bits, data=data, signature=hr.STUB_SIG)

        slot_base_ms = slot * hr.SLOT_MS
        send_ms = slot_base_ms + 3200  # emitted at 3200 ms (53.3% of slot)
        deliver_map = {
            nid: (send_ms if nid == self.id else send_ms + net.latency_ms)
            for nid in range(len(net.nodes))
        }
        net.broadcast_custom(self, send_ms, deliver_map, "avail", att)


def find_candidate_slot(genesis, assignment, adv_node_id, min_slot=9, max_slot=23):
    """Find a mid-round slot where `adv_node_id` is proposer and Early Honest has 50%..74% of honest seats."""
    adv_vals = set(assignment[adv_node_id])
    early_vals = set(assignment[0]) | set(assignment[1])
    late_vals = set(assignment[2])
    slots_per_round = int(spec.get_slots_per_round_at_slot(spec.Slot(0)))
    for s in range(min_slot, max_slot + 1):
        if s % slots_per_round == 0:
            continue  # skip round-start slots
        st = genesis.copy()
        spec.process_slots(st, spec.Slot(s))
        proposer = int(spec.get_beacon_proposer_index(st))
        if proposer not in adv_vals:
            continue
        comm = [int(v) for v in spec.get_available_committee(st, spec.Slot(s))]
        n_early = sum(1 for v in comm if v in early_vals)
        n_late = sum(1 for v in comm if v in late_vals)
        n_adv = sum(1 for v in comm if v in adv_vals)
        n_honest = n_early + n_late
        # Need:
        # 1) At 50% freeze (only honest seats present): n_early > n_honest // 2 (so B_s is confirmed in s+1)
        # 2) Not fast-confirmed in slot s: n_early < 384
        # 3) At 75% freeze (honest + adv seats present): n_early <= 512 // 2 = 256 (so B_s fails head walk in s+1)
        # 4) Next slot proposer is honest
        st_next = genesis.copy()
        spec.process_slots(st_next, spec.Slot(s + 1))
        next_proposer = int(spec.get_beacon_proposer_index(st_next))
        if (
            n_early > n_honest // 2
            and n_early < 384
            and n_early <= (n_honest + n_adv) // 2
            and next_proposer not in adv_vals
        ):
            return s, proposer, next_proposer, (n_early, n_late, n_adv)
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--validators", type=int, default=64)
    p.add_argument("--nodes", type=int, default=4)
    p.add_argument("--latency-ms", type=int, default=200)
    p.add_argument("--slots", type=int, default=32)
    p.add_argument("--json", help="optional path to write detailed JSON trace")
    p.add_argument("--events", help="write message/state event log for make_figures.py HTML plotter")
    args = p.parse_args()

    # Search seeds for one that naturally gives a mid-round slot with the required committee seat split
    chosen = None
    for seed in range(0, 200):
        genesis = hr.make_genesis(args.validators, seed)
        assignment = hr.assign_validators(args.validators, args.nodes, seed)
        for adv_node_id in range(args.nodes):
            other = [i for i in range(args.nodes) if i != adv_node_id]
            # Map early=[other[0], other[1]], late=[other[2]], adv=adv_node_id
            reordered = [assignment[other[0]], assignment[other[1]], assignment[other[2]], assignment[adv_node_id]]
            res = find_candidate_slot(genesis, reordered, 3)
            if res is not None:
                chosen = (seed, genesis, reordered, res)
                break
        if chosen is not None:
            break

    assert chosen is not None, "No suitable (seed, slot) found in range"
    seed, genesis, assignment, (attack_slot, proposer, next_proposer, (n_early, n_late, n_adv)) = chosen

    print("=== SYNCHRONOUS CONFIRMATION-PERMANENCE BREAK EXPERIMENT ===")
    print(f"Seed: {seed} | Total validators: {args.validators} across {args.nodes} nodes (16 vals = 25% stake each)")
    print(f"Slot duration: {hr.SLOT_MS} ms | Synchronous bound Delta = {hr.ATT_DUE_MS} ms (25%) | Base latency = {args.latency_ms} ms")
    print(f"Roles:")
    print(f"  - Nodes 0, 1 (Early Honest, 50% stake): receive B_{attack_slot} at 1400 ms (< 1500 ms) -> vote B_{attack_slot}")
    print(f"  - Node 2     (Late Honest,  25% stake): receives B_{attack_slot} at 1600 ms (> 1500 ms) -> votes B_{attack_slot - 1}")
    print(f"  - Node 3     (Adversary,    25% stake): proposer in slot {attack_slot} (val {proposer}); releases vote for B_{attack_slot - 1} at 3200 ms")
    print(f"Slot {attack_slot} 512-seat committee split:")
    print(f"  - Early Honest (Nodes 0,1): {n_early} seats (votes for B_{attack_slot})")
    print(f"  - Late Honest  (Node 2):    {n_late} seats (votes for B_{attack_slot - 1})")
    print(f"  - Adversary    (Node 3):    {n_adv} seats (votes for B_{attack_slot - 1} released at 3200 ms)")
    print(f"  => At 50% freeze (3000 ms): B_{attack_slot} has {n_early} / {n_early + n_late} seats "
          f"(threshold {(n_early + n_late)//2}) -> PASSES (> 50%)!")
    print(f"  => At 75% freeze (4500 ms): B_{attack_slot} has {n_early} / 512 seats "
          f"(threshold 256) -> FAILS (<= 50%)!")
    print()

    net = SynchronousAdversaryNetwork(
        latency_ms=args.latency_ms,
        seed=seed,
        adv_node_id=3,
        attack_slot=attack_slot,
        early_honest_ids=[0, 1],
        late_honest_ids=[2],
    )
    if args.events:
        net.events = []
    net.nodes = [
        hr.Node(0, genesis, assignment[0]),
        hr.Node(1, genesis, assignment[1]),
        hr.Node(2, genesis, assignment[2]),
        AdversarialProposerNode(3, genesis, assignment[3], attack_slot=attack_slot),
    ]

    tracker = Tracker(net.nodes)
    trace_rows = []
    states = []

    print("slot | phase   | n0: head / live_conf / avail_conf / safe_conf (G0-clear?) | all honest heads")
    print("-" * 98)

    for slot in range(1, args.slots + 1):
        base = slot * hr.SLOT_MS
        for offset, action in (
            (0, "0% start"),
            (hr.ATT_DUE_MS, "25% att "),
            (hr.CONF_DUE_MS, "50% conf"),
            (hr.FREEZE_DUE_MS, "75% frz "),
        ):
            now = base + offset
            net.deliver_until(now)
            for node in net.nodes:
                if action == "0% start":
                    node.slot_start(slot, now, net)
                elif action == "25% att ":
                    node.attestation_deadline(slot, now, net)
                else:
                    node.tick(spec.on_tick_per_high_resolution, spec.uint64(offset))
            net.deliver_until(now)

            if attack_slot - 1 <= slot <= attack_slot + 3:
                s0 = net.nodes[0].store
                h0 = net.nodes[0].head().root
                live_c = s0.live_confirmed_head[0]
                avail_c = s0.latest_confirmed_head[0]
                safe_c = spec.get_safe_confirmed_head(s0)
                g0_live = spec.is_g0_clear(s0, live_c) if live_c in s0.blocks else True

                def fmt_b(r):
                    if r not in s0.blocks:
                        return "gen"
                    b = s0.blocks[r]
                    return f"s{int(b.slot)}({hr.short(r)[:4]})"

                honest_heads = [fmt_b(net.nodes[i].head().root) for i in (0, 1, 2)]
                row = {
                    "slot": slot,
                    "phase": action.strip(),
                    "head": fmt_b(h0),
                    "live_conf": fmt_b(live_c),
                    "avail_conf": fmt_b(avail_c),
                    "safe_conf": fmt_b(safe_c),
                    "live_conf_g0_clear": bool(g0_live),
                    "honest_heads": honest_heads,
                }
                trace_rows.append(row)
                print(
                    f"{slot:4d} | {action} | "
                    f"{fmt_b(h0):>10} / {fmt_b(live_c):>10} / {fmt_b(avail_c):>10} / {fmt_b(safe_c):>10} "
                    f"(G0={str(g0_live):<5}) | {honest_heads}"
                )

        snaps = [tracker.observe(slot, n) for n in net.nodes]
        states.append({"slot": slot, "nodes": snaps})

    print("-" * 98)
    print(f"Max message delay observed across entire run: {net.max_delay_observed_ms} ms (synchronous bound Delta = {hr.ATT_DUE_MS} ms)")
    assert net.max_delay_observed_ms <= hr.ATT_DUE_MS, "Synchrony bound violated!"

    print("\n=== SUMMARY FOR HONEST NODES (0, 1, 2) ===")
    for nid in (0, 1, 2):
        n = net.nodes[nid]
        lost_avail = tracker.abandoned(n, "avail")
        lost_safe = tracker.abandoned(n, "safe")
        print(
            f"Honest Node {nid}: "
            f"orphaned available-confirmed blocks = {lost_avail} | "
            f"orphaned safe-confirmed blocks = {lost_safe} | "
            f"safe-confirmation reversals = {tracker.safe_reversals[nid]} | "
            f"reorgs = {tracker.reorgs[nid]}"
        )
        assert attack_slot in lost_avail, f"Expected slot {attack_slot} to be orphaned after available confirmation!"
        assert attack_slot in lost_safe, f"Expected slot {attack_slot} to be orphaned after safe confirmation!"

    if args.events:
        group_of = {0: 0, 1: 0, 2: 0, 3: 1}
        cfg = {
            "nodes": args.nodes,
            "split": 3,
            "start": attack_slot,
            "slots_down": 1,
            "seed": seed,
            "latency_ms": args.latency_ms,
            "jitter_ms": 0,
            "validators": args.validators,
        }
        with open(args.events, "w") as fh:
            json.dump(
                {
                    "config": cfg,
                    "slot_ms": hr.SLOT_MS,
                    "deadlines_ms": [hr.ATT_DUE_MS, hr.CONF_DUE_MS, hr.FREEZE_DUE_MS],
                    "slots_per_round": int(spec.get_slots_per_round_at_slot(spec.Slot(0))),
                    "group_of": group_of,
                    "messages": net.events,
                    "states": states,
                    "outcomes": getattr(hr, "OUTCOMES", []),
                },
                fh,
            )

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(
                {
                    "seed": seed,
                    "attack_slot": attack_slot,
                    "proposer": proposer,
                    "next_proposer": next_proposer,
                    "committee_seats": {"early_honest": n_early, "late_honest": n_late, "adversary": n_adv},
                    "max_delay_ms": net.max_delay_observed_ms,
                    "delta_ms": hr.ATT_DUE_MS,
                    "trace": trace_rows,
                },
                fh,
                indent=2,
            )


if __name__ == "__main__":
    main()
