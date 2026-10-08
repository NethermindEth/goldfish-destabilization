"""Semantics-preserving performance shims for the simplex pyspec.

Every patch here must return exactly what the original spec function returns.
Patches that change protocol behaviour (ablations) do NOT belong in this module.

- get_ancestor: memoized. Justification: it reads only store.blocks, which is
  append-only, and each BeaconBlock is immutable once stored. get_parent_payload_status
  compares two blocks' bids, so it is also a pure function of store.blocks.
  The cache is keyed per store, and per-block (slot, parent_root, parent_status) are
  decoded once into Python values instead of walking SSZ views on every step.
"""

_original_get_ancestor = None


def install(spec):
    global _original_get_ancestor
    if _original_get_ancestor is not None:
        return
    _original_get_ancestor = spec.get_ancestor

    block_info = {}  # (id(store.blocks), root) -> (slot, parent_root, parent_status)
    ancestor_cache = {}  # (id(store.blocks), root, payload_status, slot) -> ForkChoiceNode

    def info(store, root):
        key = (id(store.blocks), root)
        cached = block_info.get(key)
        if cached is None:
            block = store.blocks[root]
            slot = int(block.slot)
            if block.parent_root in store.blocks:
                parent_status = int(spec.get_parent_payload_status(store, block))
            else:
                parent_status = None  # anchor block: never walked past
            cached = (slot, block.parent_root, parent_status)
            block_info[key] = cached
        return cached

    def get_ancestor(store, node, slot):
        slot = int(slot)
        key = (id(store.blocks), node.root, int(node.payload_status), slot)
        hit = ancestor_cache.get(key)
        if hit is not None:
            return hit
        root, status = node.root, node.payload_status
        block_slot, parent_root, parent_status = info(store, root)
        while block_slot > slot:
            root, status = parent_root, parent_status
            block_slot, parent_root, parent_status = info(store, root)
        result = spec.ForkChoiceNode(root=root, payload_status=status)
        ancestor_cache[key] = result
        return result

    spec.get_ancestor = get_ancestor
    _install_grouped_scores(spec)
    _install_selection_cache(spec)


# ---- balance-weighted committee selection -------------------------------------
#
# compute_balance_weighted_selection (available committee, PTC) reads only
# state.validators[i].effective_balance for the given indices, plus its explicit
# arguments. Keyed on hash_tree_root(state.validators) (cached by remerkleable), the
# candidate indices, seed, size and shuffle flag, memoization is exact. Without it,
# every state copy crossing an epoch boundary recomputes 8 available committees at
# ~0.25 s each (process_available_committee_window).

_selection_cache = {}


def _install_selection_cache(spec):
    original = spec.compute_balance_weighted_selection
    _originals["selection"] = original

    def compute_balance_weighted_selection(state, indices, seed, size, shuffle_indices):
        key = (
            bytes(spec.hash_tree_root(state.validators)),
            tuple(int(i) for i in indices),
            bytes(seed),
            int(size),
            bool(shuffle_indices),
        )
        hit = _selection_cache.get(key)
        if hit is None:
            hit = list(original(state, indices, seed, size, shuffle_indices))
            _selection_cache[key] = hit
        return list(hit)

    spec.compute_balance_weighted_selection = compute_balance_weighted_selection
    _install_transition_cache(spec)

    # get_total_balance(state, indices) = max(EFFECTIVE_BALANCE_INCREMENT, sum of
    # state.validators[i].effective_balance): a pure function of the registry and indices.
    original_total = spec.get_total_balance
    total_cache = {}

    def get_total_balance(state, indices):
        key = (bytes(spec.hash_tree_root(state.validators)), tuple(sorted(int(i) for i in indices)))
        hit = total_cache.get(key)
        if hit is None:
            hit = original_total(state, indices)
            total_cache[key] = hit
        return hit

    spec.get_total_balance = get_total_balance


# ---- Goldfish seat scores ---------------------------------------------------
#
# get_available_attestation_score, get_available_confirmation_score and
# get_fast_confirmation_score each loop over the 512 committee seats and test every
# seat's vote with is_supporting_vote. The per-seat result depends only on the seat's
# member (equivocation / vote presence) and on that member's vote content
# (slot, beacon_block_root, payload status). So the sum equals
#   sum over distinct members m of  multiplicity(m) * contribution(m),
# and contribution(m) only needs evaluating once per distinct vote content.
# Exact, not approximate. Originals kept for check_score_equivalence.

_originals = {}
CHECK = False  # when True, every positions-cache miss is verified against the spec


def _install_grouped_scores(spec):
    _originals["available"] = spec.get_available_attestation_score
    _originals["confirmation"] = spec.get_available_confirmation_score
    _originals["fast"] = spec.get_fast_confirmation_score

    multiplicity_cache = {}  # id(committee) -> (committee ref, {member: seats})

    def multiplicities(committee):
        entry = multiplicity_cache.get(id(committee))
        if entry is None or entry[0] is not committee:
            counts = {}
            for member in committee:
                counts[member] = counts.get(member, 0) + 1
            entry = (committee, counts)  # holding the ref prevents id reuse
            multiplicity_cache[id(committee)] = entry
        return entry[1]

    vote_key_cache = {}  # (id(store.blocks), id(vote)) -> (vote ref, key)

    def vote_key(store, vote):
        # AvailableAttestationData stored in the Store is never mutated, and its payload
        # status depends only on store.blocks (append-only). Holding the ref prevents
        # id() reuse.
        ck = (id(store.blocks), id(vote))
        entry = vote_key_cache.get(ck)
        if entry is None or entry[0] is not vote:
            status = spec.get_available_vote_payload_status(store, vote)
            entry = (vote, (int(vote.slot), vote.beacon_block_root, int(status)))
            vote_key_cache[ck] = entry
        return entry[1]

    def grouped_support(store, node, counts, votes, equivocations=None):
        score = 0
        groups = {}  # (slot, root, payload_status) -> seats
        for member, seats in counts.items():
            if equivocations is not None and member in equivocations:
                score += seats
                continue
            if member not in votes:
                continue
            key = vote_key(store, votes[member])
            groups[key] = groups.get(key, 0) + seats
        for (slot, root, status), seats in groups.items():
            message = spec.LatestMessage(slot=spec.Slot(slot), root=root)
            if spec.is_supporting_vote(store, node, message, spec.PayloadStatus(status)):
                score += seats
        return spec.uint64(score)

    def get_available_attestation_score(store, child):
        current_slot = spec.get_current_slot(store)
        if current_slot == spec.GENESIS_SLOT or spec.is_ptc_decision_node(store, child):
            return spec.uint64(0)
        previous_slot = spec.Slot(current_slot - 1)
        if previous_slot not in store.available_votes:
            return spec.uint64(0)
        committee = store.available_committees.get(previous_slot, [])
        return grouped_support(
            store,
            child,
            multiplicities(committee),
            store.available_votes[previous_slot],
            store.available_vote_equivocations[previous_slot],
        )

    def frozen_score(store, node, slot):
        if slot not in store.frozen_available_votes:
            return spec.uint64(0)
        freeze = store.frozen_available_votes[slot]
        return grouped_support(store, node, multiplicities(freeze.committee), freeze.votes)

    def get_available_confirmation_score(store, node):
        current_slot = spec.get_current_slot(store)
        if current_slot == spec.GENESIS_SLOT or spec.is_ptc_decision_node(store, node):
            return spec.uint64(0)
        return frozen_score(store, node, spec.Slot(current_slot - 1))

    def get_fast_confirmation_score(store, node):
        current_slot = spec.get_current_slot(store)
        if current_slot == spec.GENESIS_SLOT or spec.is_ptc_decision_node(store, node):
            return spec.uint64(0)
        return frozen_score(store, node, current_slot)

    spec.get_available_attestation_score = get_available_attestation_score
    spec.get_available_confirmation_score = get_available_confirmation_score
    spec.get_fast_confirmation_score = get_fast_confirmation_score

    # Majority thresholds: same seat loop, counting seats whose member voted.
    _originals["available_threshold"] = spec.get_available_majority_threshold
    _originals["confirmation_threshold"] = spec.get_available_confirmation_majority_threshold

    def seats_voted(counts, votes):
        return sum(seats for member, seats in counts.items() if member in votes)

    def get_available_majority_threshold(store):
        current_slot = spec.get_current_slot(store)
        if current_slot == spec.GENESIS_SLOT:
            return spec.uint64(0)
        previous_slot = spec.Slot(current_slot - 1)
        if previous_slot not in store.available_votes:
            return spec.uint64(0)
        committee = store.available_committees.get(previous_slot, [])
        participants = seats_voted(multiplicities(committee), store.available_votes[previous_slot])
        return spec.uint64(participants) // 2

    def get_available_confirmation_majority_threshold(store):
        current_slot = spec.get_current_slot(store)
        if current_slot == spec.GENESIS_SLOT:
            return spec.uint64(0)
        previous_slot = spec.Slot(current_slot - 1)
        if previous_slot not in store.frozen_available_votes:
            return spec.uint64(0)
        freeze = store.frozen_available_votes[previous_slot]
        return spec.uint64(seats_voted(multiplicities(freeze.committee), freeze.votes)) // 2

    spec.get_available_majority_threshold = get_available_majority_threshold
    spec.get_available_confirmation_majority_threshold = get_available_confirmation_majority_threshold

    # Attesting positions/indices of an AvailableAttestation: a pure function of its
    # aggregation bits and the slot's available committee. Cached on (bits bytes,
    # committee root); the decode itself is redone in plain Python on a miss.
    _originals["positions"] = spec.get_available_attesting_positions
    _originals["indices"] = spec.get_available_attesting_indices
    positions_cache = {}

    def committee_key(committee):
        if hasattr(committee, "hash_tree_root"):
            return bytes(committee.hash_tree_root())
        return tuple(int(i) for i in committee)

    def decoded(state, attestation):
        committee = spec.get_available_committee(state, attestation.data.slot)
        assert len(attestation.aggregation_bits) == spec.AVAILABLE_COMMITTEE_SIZE
        assert len(attestation.aggregation_bits) == len(committee)
        key = (bytes(attestation.aggregation_bits.encode_bytes()), committee_key(committee))
        hit = positions_cache.get(key)
        if hit is None:
            members = [int(i) for i in committee]
            bits = [bool(b) for b in attestation.aggregation_bits]
            attesting = {m for m, b in zip(members, bits) if b}
            positions = frozenset(i for i, m in enumerate(members) if m in attesting)
            hit = (positions, frozenset(attesting))
            if CHECK:
                # (the original indices function calls the patched positions global,
                # so derive its result from the original positions instead)
                expected = {int(p) for p in _originals["positions"](state, attestation)}
                assert expected == set(positions)
                assert {members[p] for p in expected} == set(attesting)
            positions_cache[key] = hit
        return hit

    def get_available_attesting_positions(state, attestation):
        return {spec.uint64(i) for i in decoded(state, attestation)[0]}

    def get_available_attesting_indices(state, attestation):
        return {spec.ValidatorIndex(i) for i in decoded(state, attestation)[1]}

    _install_grouped_attestation_score(spec)

    spec.get_available_attesting_positions = get_available_attesting_positions
    spec.get_available_attesting_indices = get_available_attesting_indices


# ---- finality-vote (G1 / LMD) attestation score -------------------------------------
#
# get_attestation_score sums effective balances of active unslashed validators whose
# latest message passes has_unexpired_latest_message, is inside the window and supports
# the node. Apart from "not equivocating" (per validator), every condition depends only
# on the message content (slot, root). So: sum balances per distinct (slot, root), then
# evaluate the content conditions once per group. The (active, unslashed, balance) list
# is a function of the registry and epoch, cached on (validators root, epoch).

def _install_grouped_attestation_score(spec):
    _originals["attestation_score"] = spec.get_attestation_score
    weights_cache = {}

    def active_weights(state):
        epoch = spec.get_current_epoch(state)
        key = (bytes(spec.hash_tree_root(state.validators)), int(epoch))
        hit = weights_cache.get(key)
        if hit is None:
            hit = [
                (i, int(state.validators[i].effective_balance))
                for i in spec.get_active_validator_indices(state, epoch)
                if not state.validators[i].slashed
            ]
            weights_cache[key] = hit
        return hit

    def get_attestation_score(store, node, state, window_slots=spec.LATEST_MESSAGE_EXPIRY_SLOTS):
        current_slot = int(spec.get_current_slot(store))
        latest, equivocating = store.latest_messages, store.equivocating_indices
        groups = {}
        for i, balance in active_weights(state):
            if i not in latest or i in equivocating:
                continue
            message = latest[i]
            key = (int(message.slot), message.root)
            groups[key] = groups.get(key, 0) + balance
        total = 0
        for (slot, root), weight in groups.items():
            if not spec.is_finalized_compatible(store, root):
                continue
            if not slot + int(spec.LATEST_MESSAGE_EXPIRY_SLOTS) > current_slot:
                continue
            if not slot + int(window_slots) >= current_slot:
                continue
            message = spec.LatestMessage(slot=spec.Slot(slot), root=root)
            if spec.is_supporting_vote(store, node, message, spec.PAYLOAD_STATUS_PENDING):
                total += weight
        return spec.Gwei(total)

    spec.get_attestation_score = get_attestation_score


# ---- state transitions shared across nodes ------------------------------------
#
# process_slots(state, slot) and state_transition(state, signed_block, v) are pure
# functions of their inputs (BLS is off). Every honest node runs the same transitions on
# the same blocks, including epoch processing at round boundaries. remerkleable states
# are persistent trees, so a post-state computed once can be adopted by any other node
# via set_backing without copying or aliasing hazards. Failed transitions raise and are
# not cached, so they fail identically each time.

_transition_stats = {"slots_hit": 0, "slots_miss": 0, "block_hit": 0, "block_miss": 0}


def _install_transition_cache(spec):
    orig_slots = spec.process_slots
    orig_transition = spec.state_transition
    slots_cache, block_cache = {}, {}

    def process_slots(state, slot):
        assert state.slot < slot
        key = (bytes(spec.hash_tree_root(state)), int(slot))
        hit = slots_cache.get(key)
        if hit is not None:
            _transition_stats["slots_hit"] += 1
            if CHECK:
                ref = state.copy()
                orig_slots(ref, slot)
                assert ref.get_backing().merkle_root() == hit.merkle_root()
            state.set_backing(hit)
            return
        _transition_stats["slots_miss"] += 1
        orig_slots(state, slot)
        slots_cache[key] = state.get_backing()

    def state_transition(state, signed_block, validate_result=True):
        key = (
            bytes(spec.hash_tree_root(state)),
            bytes(spec.hash_tree_root(signed_block)),
            bool(validate_result),
        )
        hit = block_cache.get(key)
        if hit is not None:
            _transition_stats["block_hit"] += 1
            if CHECK:
                ref = state.copy()
                orig_transition(ref, signed_block, validate_result)
                assert ref.get_backing().merkle_root() == hit.merkle_root()
            state.set_backing(hit)
            return
        _transition_stats["block_miss"] += 1
        orig_transition(state, signed_block, validate_result)
        block_cache[key] = state.get_backing()

    spec.process_slots = process_slots
    spec.state_transition = state_transition


def check_score_equivalence(spec, store):
    """Compare grouped scores against the spec originals for every node in the store."""
    for root in list(store.blocks.keys()):
        for status in (spec.PAYLOAD_STATUS_PENDING, spec.PAYLOAD_STATUS_EMPTY):
            node = spec.ForkChoiceNode(root=root, payload_status=status)
            assert spec.get_available_attestation_score(store, node) == _originals["available"](store, node)
            assert spec.get_available_confirmation_score(store, node) == _originals["confirmation"](store, node)
            assert spec.get_fast_confirmation_score(store, node) == _originals["fast"](store, node)
    head_state = store.block_states[spec.get_head(store).root]
    for root in list(store.blocks.keys()):
        node = spec.ForkChoiceNode(root=root, payload_status=spec.PAYLOAD_STATUS_PENDING)
        for window in (spec.LATEST_MESSAGE_EXPIRY_SLOTS, spec.uint64(8)):
            assert spec.get_attestation_score(store, node, head_state, window) == _originals[
                "attestation_score"
            ](store, node, head_state, window)
    assert spec.get_available_majority_threshold(store) == _originals["available_threshold"](store)
    assert spec.get_available_confirmation_majority_threshold(store) == _originals[
        "confirmation_threshold"
    ](store)


def check_equivalence(spec, store, samples=200):
    """Compare the patched get_ancestor against the original on random block pairs."""
    import random

    roots = list(store.blocks.keys())
    rng = random.Random(0)
    for _ in range(samples):
        root = rng.choice(roots)
        slot = rng.randint(0, int(store.blocks[root].slot))
        for status in (spec.PAYLOAD_STATUS_PENDING, spec.PAYLOAD_STATUS_EMPTY):
            node = spec.ForkChoiceNode(root=root, payload_status=status)
            assert spec.get_ancestor(store, node, slot) == _original_get_ancestor(store, node, slot)
