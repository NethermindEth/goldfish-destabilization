"""Spike: N honest nodes driving the simplex pyspec through a simulated network.

Question this answers: can we run the executable spec end to end (blocks, available
attestations, finality attestations, ticks at the in-slot deadlines) across several
nodes and rounds, and does an honest synchronous run advance heights and finalize?

Run (from this directory):
    PYTHONPATH=$SPECS $SPECS/.venv/bin/python honest_run.py
with SPECS=~/Projects/consensus-specs (branch simplex-healing).

Simplifications (spike only):
- BLS verification off; signatures are stubs.
- No execution payloads are ever revealed, so every block is EMPTY in the Gloas sense.
- Fixed per-message latency; every node receives every message.
- Duties run at the attestation deadline, not on early block receipt.
"""

import argparse
import hashlib
import heapq
import itertools
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field

from eth_consensus_specs.utils import bls

bls.bls_active = False

from eth_consensus_specs.simplex import minimal as spec  # noqa: E402

import perf  # noqa: E402

perf.install(spec)
from eth_consensus_specs.test.helpers.block import build_empty_block  # noqa: E402
from eth_consensus_specs.test.helpers.fork_choice import (  # noqa: E402
    get_genesis_forkchoice_store,
)
from eth_consensus_specs.test.helpers.fulu.state import initialize_proposer_lookahead  # noqa: E402
from eth_consensus_specs.test.helpers.genesis import create_genesis_state  # noqa: E402
from eth_consensus_specs.test.helpers.gloas.state import initialize_ptc_window  # noqa: E402
from eth_consensus_specs.test.helpers.state import (  # noqa: E402
    state_transition_and_sign_block,
)

# Observation-only instrumentation: record the TSQ lock each store computes, so we can
# tell whether the frozen stable root came from the TSQ lock or from the G1 fallback.
# The wrapper returns the original value unchanged.
TSQ_LOCKS = {}  # (id(store), round) -> lock root
_orig_deepest_tsq_root = spec.get_deepest_tsq_root


def _observed_deepest_tsq_root(store, selection, heads):
    root = _orig_deepest_tsq_root(store, selection, heads)
    TSQ_LOCKS[(id(store), int(spec.compute_round_at_slot(spec.get_current_slot(store))))] = root
    return root


spec.get_deepest_tsq_root = _observed_deepest_tsq_root

SLOT_MS = int(spec.config.SLOT_DURATION_MS)
ATT_DUE_MS = int(spec.get_slot_component_duration_ms(spec.AVAILABLE_ATTESTATION_DUE_BPS))
CONF_DUE_MS = int(spec.get_available_confirmation_due_ms())
FREEZE_DUE_MS = int(spec.get_view_freeze_due_ms())
STUB_SIG = spec.BLSSignature(b"\x00" * 96)
TRACE_BLOCKS = False


@dataclass
class ValidatorDuty:
    """Per-validator durable signing state (validator.md "Local state")."""

    voted_target_at: dict = field(default_factory=dict)
    voted_timeout_at: set = field(default_factory=set)
    voted_finality_at: dict = field(default_factory=dict)
    frozen_round_vote_at: dict = field(default_factory=dict)
    skipped_attestation_at_round: set = field(default_factory=set)
    signed_attestation_at_round: dict = field(default_factory=dict)


def vote_kind(data):
    if data.target != spec.Checkpoint():
        kind = f"justify@h{int(data.height)}"
    elif data.height != spec.Height(0):
        kind = f"timeout@h{int(data.height)}"
    else:
        kind = "empty"
    if data.finality_target != spec.Checkpoint():
        kind += f"+fin@h{int(data.finality_height)}"
    return kind


class Node:
    def __init__(self, node_id, genesis_state, validators):
        self.id = node_id
        self.store = get_genesis_forkchoice_store(spec, genesis_state.copy())
        self.validators = set(validators)
        self.duties = {v: ValidatorDuty() for v in validators}
        # hash_tree_root(attestation) -> Attestation; pruned to the inclusion window
        self.att_pool = {}
        self.rejected = defaultdict(int)
        self.vote_kinds = defaultdict(lambda: defaultdict(int))  # round -> kind -> count
        self._head = None  # memoized get_head; invalidated whenever the store may change

    def head(self):
        if self._head is None:
            self._head = spec.get_head(self.store)
        return self._head

    def tick(self, fn, *args):
        self._head = None
        fn(self.store, *args)

    # ---- message ingress -------------------------------------------------
    def receive(self, kind, msg):
        self._head = None
        try:
            if kind == "block":
                spec.on_block(self.store, msg)
                self.store_block_attestations(msg)
            elif kind == "att":
                spec.on_attestation(self.store, msg)
                self.pool_attestation(msg)
            elif kind == "avail":
                spec.on_available_attestation(self.store, msg)
        except AssertionError:
            self.rejected[kind] += 1

    def store_block_attestations(self, signed_block):
        # Keep block-carried finality votes poolable so later proposers can aggregate them.
        for att in signed_block.message.body.attestations:
            self.pool_attestation(att)

    def pool_attestation(self, att):
        # Cheap ingress: no state work here; splitting into committees happens once per
        # proposal, against the proposal's own state.
        self.att_pool.setdefault(spec.hash_tree_root(att), att)

    # ---- duties ----------------------------------------------------------
    def slot_start(self, slot, now_ms, net):
        self.tick(spec.on_tick, self.store.genesis_time + now_ms // 1000)
        head_root = self.head().root
        parent_root = spec.get_proposer_head(self.store, head_root, spec.Slot(slot))
        state = spec.get_current_slot_state(self.store, parent_root)
        proposer = spec.get_beacon_proposer_index(state)
        if proposer not in self.validators:
            return
        state = self.store.block_states[parent_root].copy()
        block = build_empty_block(spec, state, slot=spec.Slot(slot), proposer_index=proposer)
        block.parent_root = parent_root
        pre = state.copy()
        spec.process_slots(pre, spec.Slot(slot))
        block.body.attestations = self.select_attestations(pre, parent_root)
        if TRACE_BLOCKS:
            parts = [
                f"s{int(a.data.slot)}:{vote_kind(a.data)}x{sum(1 for b in a.aggregation_bits if b)}"
                for a in block.body.attestations
            ]
            print(f"    [block {slot} by node {self.id}] pool={len(self.att_pool)} incl={parts}")
        signed = state_transition_and_sign_block(spec, state, block)
        net.broadcast(self, now_ms, "block", signed)

    def included_on_chain(self, slot_state, parent_root, oldest_round):
        """(data_root, validator) pairs already included by blocks on the parent chain."""
        seen = set()
        root = parent_root
        while root in self.store.blocks:
            block = self.store.blocks[root]
            if spec.compute_round_at_slot(block.slot) < oldest_round or block.slot == 0:
                break
            for att in block.body.attestations:
                if spec.compute_round_at_slot(att.data.slot) < oldest_round:
                    continue
                try:
                    indices = spec.get_attesting_indices(slot_state, att)
                except (AssertionError, IndexError, KeyError):
                    continue
                data_root = spec.hash_tree_root(att.data)
                seen.update((data_root, int(v)) for v in indices)
            root = block.parent_root
        return seen

    def select_attestations(self, slot_state, parent_root):
        """Aggregate pooled votes per AttestationData; include those adding new votes.

        Participants already included on the parent chain for the same data are dropped,
        and aggregates are ranked by the number of new votes they add.
        """
        current_round = spec.compute_round_at_slot(slot_state.slot)
        oldest_round = current_round - 1 if current_round > 0 else 0
        self.att_pool = {
            k: a
            for k, a in self.att_pool.items()
            if spec.compute_round_at_slot(a.data.slot) >= oldest_round
        }
        already = self.included_on_chain(slot_state, parent_root, oldest_round)
        by_data = defaultdict(lambda: defaultdict(set))  # data_root -> cidx -> new members
        data_of = {}
        for att in self.att_pool.values():
            try:
                indices = set(spec.get_attesting_indices(slot_state, att))
            except (AssertionError, IndexError, KeyError):
                continue
            data_root = spec.hash_tree_root(att.data)
            fresh = {v for v in indices if (data_root, int(v)) not in already}
            if not fresh:
                continue
            data_of[data_root] = att.data
            for cidx in spec.get_committee_indices(att.committee_bits):
                committee = set(spec.get_beacon_committee(slot_state, att.data.slot, cidx))
                by_data[data_root][int(cidx)] |= fresh & committee
        candidates = []
        for data_root, per_committee in by_data.items():
            data = data_of[data_root]
            att = self.build_attestation(
                slot_state, data, {c: (data, m) for c, m in per_committee.items() if m}
            )
            if att is not None:
                candidates.append((sum(len(m) for m in per_committee.values()), att))
        candidates.sort(key=lambda x: (-x[0], -int(x[1].data.slot)))
        chosen = []
        sim = slot_state.copy()
        for _, att in candidates:
            if len(chosen) == spec.MAX_ATTESTATIONS_ELECTRA:
                break
            trial = sim.copy()
            try:
                spec.process_attestation(trial, att)
            except (AssertionError, IndexError, KeyError):
                continue
            sim = trial
            chosen.append(att)
        return chosen

    @staticmethod
    def build_attestation(state, data, per_committee):
        try:
            committee_bits = spec.Bitvector[spec.MAX_COMMITTEES_PER_SLOT]()
            bits = []
            for cidx in sorted(per_committee):
                committee = spec.get_beacon_committee(state, data.slot, spec.CommitteeIndex(cidx))
                committee_bits[cidx] = True
                members = per_committee[cidx][1]
                bits.extend(v in members for v in committee)
            agg = spec.Bitlist[
                spec.MAX_VALIDATORS_PER_COMMITTEE * spec.MAX_COMMITTEES_PER_SLOT
            ](*bits)
            return spec.Attestation(
                aggregation_bits=agg, data=data, committee_bits=committee_bits, signature=STUB_SIG
            )
        except (AssertionError, IndexError, KeyError):
            return None

    def attestation_deadline(self, slot, now_ms, net):
        store = self.store
        self.tick(spec.on_tick_per_high_resolution, spec.uint64(ATT_DUE_MS))
        round_ = spec.compute_round_at_slot(spec.Slot(slot))
        if slot == spec.compute_start_slot_at_round(round_):
            event = spec.RoundSelectionEvent(
                slot=spec.Slot(slot),
                head_root=self.head().root,
                safe_confirmed_root=spec.get_safe_confirmed_head(store),
                finalized_root=store.finalized_checkpoint.root,
            )
            for d in self.duties.values():
                spec.freeze_round_vote(
                    store,
                    event,
                    d.voted_target_at,
                    d.voted_timeout_at,
                    d.voted_finality_at,
                    d.frozen_round_vote_at,
                )
        self.available_duty(slot, now_ms, net)
        self.finality_duty(slot, now_ms, net)

    def available_duty(self, slot, now_ms, net):
        store = self.store
        committee = store.available_committees.get(spec.Slot(slot))
        if committee is None:
            return
        positions = [i for i, v in enumerate(committee) if v in self.validators]
        if not positions:
            return
        head = self.head()
        data = spec.get_available_attestation_data(store, head)
        bits = spec.Bitvector[spec.AVAILABLE_COMMITTEE_SIZE]()
        for i in positions:
            bits[i] = True
        att = spec.AvailableAttestation(aggregation_bits=bits, data=data, signature=STUB_SIG)
        net.broadcast(self, now_ms, "avail", att)

    def finality_duty(self, slot, now_ms, net):
        store = self.store
        state = spec.get_current_slot_state(store, self.head().root)
        round_ = spec.compute_round_at_slot(spec.Slot(slot))
        n_committees = spec.get_committee_count_per_slot(state, spec.compute_epoch_at_slot(slot))
        for cidx in range(n_committees):
            committee = spec.get_beacon_committee(state, spec.Slot(slot), spec.CommitteeIndex(cidx))
            by_data = {}
            for v in committee:
                if v not in self.validators:
                    continue
                d = self.duties[v]
                if round_ not in d.frozen_round_vote_at:
                    continue
                data = spec.get_attestation_data(
                    store, d.frozen_round_vote_at, d.skipped_attestation_at_round
                )
                if data is None:
                    self.vote_kinds[int(round_)]["skipped"] += 1
                    continue
                if not self.record_signing(d, round_, data):
                    self.vote_kinds[int(round_)]["refused"] += 1
                    continue
                self.vote_kinds[int(round_)][vote_kind(data)] += 1
                by_data.setdefault(spec.hash_tree_root(data), (data, set()))[1].add(v)
            for data, members in by_data.values():
                att = self.build_attestation(state, data, {cidx: (data, members)})
                if att is not None:
                    net.broadcast(self, now_ms, "att", att)

    @staticmethod
    def record_signing(d, round_, data):
        """Signing-boundary checks and history updates (validator.md "Signing")."""
        prior = d.signed_attestation_at_round.get(round_)
        if prior is not None and prior != data:
            return False
        if data.target != spec.Checkpoint():
            if d.voted_target_at.get(data.height) not in (None, data.target):
                return False
            d.voted_target_at.setdefault(data.height, data.target)
        elif data.height != spec.Height(0):
            d.voted_timeout_at.add(data.height)
        if data.finality_target != spec.Checkpoint():
            d.voted_finality_at[data.finality_height] = data.finality_target
        d.signed_attestation_at_round[round_] = data
        return True

    # ---- observation -----------------------------------------------------
    def snapshot(self):
        s = self.store
        head = self.head().root
        hs = s.block_states[head]
        rnd = int(spec.compute_round_at_slot(spec.get_current_slot(s)))
        stable_slot, stable_src = None, "-"
        if rnd in s.stable_root_decisions and int(s.stable_root_round) == rnd:
            stable_slot = int(s.blocks[s.stable_root].slot)
            lock = TSQ_LOCKS.get((id(s), rnd))
            stable_src = "TSQ" if lock is not None and lock == s.stable_root else "G1"
        return {
            "head_slot": int(s.blocks[head].slot),
            "chain_height": int(hs.current_height),
            "h_max": int(s.h_max),
            "justified_slot": int(s.justified_checkpoint.slot),
            "finalized_slot": int(s.finalized_checkpoint.slot),
            "stable_slot": stable_slot,
            "stable_src": stable_src,
            "justified_height": int(s.justified_height) if hasattr(s, "justified_height") else -1,
            "safe_conf_slot": int(s.blocks[spec.get_safe_confirmed_head(s)].slot),
        }


class Network:
    def __init__(self, latency_ms, jitter_ms=0, seed=0):
        self.latency_ms = latency_ms
        self.jitter_ms = jitter_ms
        self.rng = random.Random(f"net-{seed}")  # draws happen in deterministic send order
        self.queue = []
        self.seq = itertools.count()
        self.nodes = []
        self.sent = defaultdict(int)

    def delay(self, sender, node):
        if node is sender:
            return 0
        jitter = self.rng.randint(0, self.jitter_ms) if self.jitter_ms else 0
        return self.latency_ms + jitter

    def broadcast(self, sender, now_ms, kind, msg):
        self.sent[kind] += 1
        for node in self.nodes:
            at = now_ms + self.delay(sender, node)
            heapq.heappush(self.queue, (at, next(self.seq), node.id, kind, msg))

    def deliver_until(self, t_ms):
        while self.queue and self.queue[0][0] <= t_ms:
            _, _, dst, kind, msg = heapq.heappop(self.queue)
            self.nodes[dst].receive(kind, msg)


def make_genesis(n_validators, seed):
    """Genesis state; seed != 0 replaces the RANDAO mixes (committees, proposers, roots).

    Any genesis RANDAO is valid input to the spec. The caches genesis derives from the
    mixes are recomputed exactly as create_genesis_state does.
    """
    state = create_genesis_state(
        spec, [spec.MAX_EFFECTIVE_BALANCE] * n_validators, spec.MIN_ACTIVATION_BALANCE
    )
    if seed:
        mix = spec.Bytes32(hashlib.sha256(f"genesis-randao-{seed}".encode()).digest())
        state.randao_mixes = [mix] * spec.EPOCHS_PER_HISTORICAL_VECTOR
        state.ptc_window = initialize_ptc_window(spec, state)
        state.available_committee_window = spec.initialize_available_committee_window(state)
        state.proposer_lookahead = initialize_proposer_lookahead(spec, state)
    return state


def assign_validators(n_validators, n_nodes, seed):
    """Validator indices per node: round-robin, after a seeded shuffle when seed != 0."""
    indices = list(range(n_validators))
    if seed:
        random.Random(f"assign-{seed}").shuffle(indices)
    return [indices[i::n_nodes] for i in range(n_nodes)]


def add_world_args(p):
    p.add_argument("--validators", type=int, default=64)
    p.add_argument("--nodes", type=int, default=4)
    p.add_argument("--latency-ms", type=int, default=200)
    p.add_argument("--jitter-ms", type=int, default=0, help="uniform extra delay per message")
    p.add_argument("--seed", type=int, default=0, help="0 = the original deterministic world")


def main():
    p = argparse.ArgumentParser()
    add_world_args(p)
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--slots", type=int, default=0)
    p.add_argument("--trace-blocks", action="store_true", help="print attestations included per block")
    p.add_argument("--profile-from", type=int, default=0, help="cProfile slots >= this one")
    p.add_argument("--check-every", type=int, default=0, help="verify perf shims every k slots")
    args = p.parse_args()
    perf.CHECK = bool(args.check_every)
    global TRACE_BLOCKS
    TRACE_BLOCKS = args.trace_blocks

    t0 = time.perf_counter()
    genesis = make_genesis(args.validators, args.seed)
    net = Network(args.latency_ms, args.jitter_ms, args.seed)
    assignment = assign_validators(args.validators, args.nodes, args.seed)
    net.nodes = [Node(i, genesis, assignment[i]) for i in range(args.nodes)]
    slots_per_round = int(spec.get_slots_per_round_at_slot(spec.Slot(0)))
    total_slots = args.slots or args.rounds * slots_per_round
    print(
        f"N={args.validators} validators, {args.nodes} nodes, {slots_per_round} slots/round, "
        f"slot={SLOT_MS}ms, deadlines att={ATT_DUE_MS} conf={CONF_DUE_MS} freeze={FREEZE_DUE_MS}, "
        f"latency={args.latency_ms}+U[0,{args.jitter_ms}]ms seed={args.seed}  (setup {time.perf_counter()-t0:.1f}s)"
    )
    print("slot | node0: head chainH h_max jslot fslot stable safe | heads agree?")

    t_run = time.perf_counter()
    profiler = None
    for slot in range(1, total_slots + 1):
        if args.profile_from and slot == args.profile_from:
            import cProfile

            profiler = cProfile.Profile()
            profiler.enable()
        t_slot = time.perf_counter()
        base = slot * SLOT_MS
        for offset, action in (
            (0, "slot_start"),
            (ATT_DUE_MS, "att_due"),
            (CONF_DUE_MS, "conf_due"),
            (FREEZE_DUE_MS, "freeze_due"),
        ):
            now = base + offset
            net.deliver_until(now)  # spec: process messages due at t before the tick
            for node in net.nodes:
                if action == "slot_start":
                    node.slot_start(slot, now, net)
                elif action == "att_due":
                    node.attestation_deadline(slot, now, net)
                else:
                    node.tick(spec.on_tick_per_high_resolution, spec.uint64(offset))
            net.deliver_until(now)  # zero-latency self-deliveries
        if args.check_every and slot % args.check_every == 0:
            perf.check_score_equivalence(spec, net.nodes[0].store)
        snaps = [n.snapshot() for n in net.nodes]
        s = snaps[0]
        agree = len({x["head_slot"] for x in snaps}) == 1
        print(
            f"{slot:4d} | {s['head_slot']:4d} {s['chain_height']:6d} {s['h_max']:5d} "
            f"{s['justified_slot']:4d} {s['finalized_slot']:3d} {str(s['stable_slot']):>4}/{s['stable_src']:<3} "
            f"{s['safe_conf_slot']:4d} | {agree}  ({time.perf_counter()-t_slot:.1f}s)"
        )
    elapsed = time.perf_counter() - t_run
    if profiler is not None:
        import pstats

        profiler.disable()
        pstats.Stats(profiler).sort_stats("cumtime").print_stats("minimal.py|honest_run|perf", 25)
    perf.check_equivalence(spec, net.nodes[0].store)
    print(f"\nsimulated {total_slots} slots in {elapsed:.1f}s ({elapsed/total_slots:.2f}s/slot)")
    print("messages sent:", dict(net.sent), "| transition cache:", perf._transition_stats)
    print("rejections per node:", [dict(n.rejected) for n in net.nodes])
    print("finality vote kinds per round (all nodes):")
    rounds = sorted({r for n in net.nodes for r in n.vote_kinds})
    for r in rounds:
        merged = defaultdict(int)
        for n in net.nodes:
            for k, c in n.vote_kinds[r].items():
                merged[k] += c
        print(f"  round {r}: {dict(merged)}")


if __name__ == "__main__":
    main()
