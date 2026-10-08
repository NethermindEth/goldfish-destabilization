"""Probe: can we drive the simplex pyspec outside pytest, and how fast is it?"""
import time

t0 = time.perf_counter()
from eth_consensus_specs.utils import bls
bls.bls_active = False  # skip signature verification
from eth_consensus_specs.simplex import minimal as spec
from eth_consensus_specs.test.helpers.genesis import create_genesis_state
from eth_consensus_specs.test.helpers.fork_choice import get_genesis_forkchoice_store
from eth_consensus_specs.test.helpers.block import build_empty_block_for_next_slot
from eth_consensus_specs.test.helpers.state import state_transition_and_sign_block
print(f"imports: {time.perf_counter()-t0:.2f}s")

N = 64
t0 = time.perf_counter()
state = create_genesis_state(spec, [spec.MAX_EFFECTIVE_BALANCE] * N, spec.MIN_ACTIVATION_BALANCE)
store = get_genesis_forkchoice_store(spec, state)
print(f"genesis+store (N={N}): {time.perf_counter()-t0:.2f}s")
print("SLOTS_PER_EPOCH", spec.SLOTS_PER_EPOCH, "slots/round",
      spec.get_slots_per_round_at_slot(spec.Slot(0)), "SLOT_DURATION_MS", spec.config.SLOT_DURATION_MS)

t0 = time.perf_counter()
block = build_empty_block_for_next_slot(spec, state)
signed = state_transition_and_sign_block(spec, state, block)
t1 = time.perf_counter()
spec.on_tick(store, store.genesis_time + block.slot * spec.config.SLOT_DURATION_MS // 1000)
spec.on_block(store, signed)
t2 = time.perf_counter()
print(f"build block: {t1-t0:.3f}s  on_block: {t2-t1:.3f}s")
t0 = time.perf_counter()
head = spec.get_head(store)
print(f"get_head: {time.perf_counter()-t0:.3f}s -> {head}")
print("current_height", state.current_height, "h_max", store.h_max)
