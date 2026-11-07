# Goldfish + stabilization gadget: multi-node harness around the simplex pyspec

The simulator of the first protocol we studied (Goldfish with the stabilization gadget,
`fradamt/consensus-specs@simplex-healing`). It drives the executable spec itself. It started as a
feasibility prototype (7–8 Oct 2026) that answered one question: can the executable spec
(`fradamt/consensus-specs@simplex-healing`, commit `5750e57`) be driven as N nodes over a
simulated network fast enough to run experiments? **Yes.**

## Setup

```bash
git clone -b simplex-healing https://github.com/fradamt/consensus-specs ~/Projects/consensus-specs
cd ~/Projects/consensus-specs && make test fork=simplex   # builds pyspec + .venv; 1219 passed (~14 min)
export SPECS=~/Projects/consensus-specs
cd simulator/goldfish-simplex
PYTHONPATH=$SPECS $SPECS/.venv/bin/python honest_run.py --rounds 8
PYTHONPATH=$SPECS $SPECS/.venv/bin/python partition_run.py --split 2 --start 24 --slots-down 16
```

`PYTHONPATH` must contain the consensus-specs root because some test helpers import
`tests.infra`. The minimal preset is used: 8-slot epochs, 8-slot rounds, **6 s slots**.
In-slot deadlines therefore fall at 1.5 s, 3 s and 4.5 s.

## Files

| File | Contents |
|---|---|
| `honest_run.py` | `Node` (spec `Store` + validator duties + attestation pool), `Network` (priority queue by delivery time), honest synchronous run |
| `partition_run.py` | `PartitionedNetwork` (cross-cut messages held until heal), reorg / confirmation-reversal / stable-root tracking |
| `perf.py` | Semantics-preserving caches (see below) |
| `probe.py` | First import/timing probe |
| `results/` | Logs of the runs quoted below (not committed: 500 MB; rerun the commands to regenerate) |

## How a slot is driven

The order is the one prescribed by `on_tick_per_high_resolution`: deliver every message
due at or before t, then tick.

| Time in slot | Harness action |
|---|---|
| 0 | `on_tick` (slot boundary: `freeze_tsq_selection`, committee caching); proposer builds on `get_proposer_head`, aggregates pooled finality attestations (≤ 8, simulated with `process_attestation`) and broadcasts |
| 25% | `on_tick_per_high_resolution` (round start: `freeze_stable_root`). At round start: `RoundSelectionEvent` + `freeze_round_vote` for every local validator. Then available attestations (`get_available_attestation_data`) and finality attestations for this slot's committee (`get_attestation_data` + signing-boundary checks from validator.md) |
| 50% | `on_tick_per_high_resolution` (available-vote freeze, confirmations) |
| 75% | `on_tick_per_high_resolution` (view freeze; last slot of a round: `freeze_tsq_view`) |

All protocol decisions are made by spec functions. The harness only schedules them and
moves messages.

**Simplifications:**
- BLS off, stub signatures.
- No execution payloads are revealed (every block is EMPTY in Gloas terms).
- Finality duties run at the 25% deadline, not on early block receipt.
- No randomness yet: runs are deterministic.

## Performance shims (`perf.py`)

Each one returns exactly what the spec function returns. The harness checks this:
- `--check-every k` compares the Goldfish scores against the original spec functions on
  live state;
- `get_ancestor` is spot-checked against the original at the end of every run.

| Shim | Why exact | Effect |
|---|---|---|
| memoized `get_ancestor` | reads only `store.blocks`, which is append-only and immutable per block | removes repeated SSZ walks |
| Goldfish seat scores and majority thresholds grouped by member/vote | per-seat contribution depends only on the member and its vote content | 512 seat checks → about 1–3 |
| G1 `get_attestation_score` grouped by distinct latest message | apart from equivocation, every condition depends only on (slot, root) | O(validators) ancestor checks → O(distinct messages) |
| cached available-attestation positions/indices | pure in (aggregation bits, committee) | N² ingress decoding: 45 ms → < 1 ms |
| memoized `compute_balance_weighted_selection`, `get_total_balance` | read only the registry | epoch processing |
| `process_slots` / `state_transition` shared across nodes | pure in (pre-state, block); remerkleable trees are persistent, so post-states are adopted with `set_backing` | every node's identical transitions computed once (~95% hit rate) |
| harness `get_head` memo | invalidated on every message and tick | ~6 calls/node/slot → 1–2 |

**Scaling** (64 validators, honest run, average over 24 slots):

| Nodes | Raw spec | With shims |
|---|---|---|
| 4 | 10–25 s/slot | 0.8 s/slot |
| 16 | ~19 s/slot (by slot 11) | 2.2 s/slot |
| 64 | — | 7.1 s/slot |

At 64 nodes, round-boundary slots cost 14–17 s. With the shims, cost grows roughly
linearly in the node count; what remains is the N² message ingress and per-node fork
choice. For sweeps, run independent scenarios in parallel processes (one per core).

## What is validated

Honest synchronous run, 8 rounds (`results/honest_8rounds.log`):
- every node has the same head in every slot;
- no rejected messages;
- the stable root comes from the TSQ lock in every round and advances by one round each
  round;
- safe confirmation trails the head by one slot;
- heights 1 → 5; slot 16 justified at 32 and finalized at 40; slot 32 justified at 48 and
  finalized at 56.

**Steady state of the executable schedule is two rounds per height.** Finality votes
alternate `justify@h` and `empty + fin@h`:
- At the round-start selection the new height's target is that round's own proposal.
- The safe-confirmed head is still one slot behind it, so the uniform gate yields an
  *empty* vote.
- The target is justified in the following round, and finalized by piggyback in the round
  after that.
- validator.md states this ("the target is considered in the next round").
- With mainnet's placeholder `SLOTS_PER_ROUND = 32`, that is 64 slots per height. Worth
  asking fradamt.

## Partition results (16 nodes, 5 seeds per row; preliminary)

```bash
PYTHONPATH=$SPECS $SPECS/.venv/bin/python partition_run.py --nodes 16 --split 8 \
    --slots-down 16 --seed 1 --jitter-ms 100 --json out.json
python aggregate.py results/seeded/*.json
```

**Setup:**
- Nodes are split into two groups at slot 24.
- Every cross-cut message is held until heal (GST) at slot 24 + D.
- 64 validators.
- Seeds vary the genesis RANDAO, validator placement and latency (200 ms + U[0, 100] ms).

| Split | D | Max reorg (blocks) | Orphaned safe-confirmed blocks | Finality delay (slot 16) |
|---|---|---|---|---|
| 50/50 | 8 / 16 / 32 | 4.8 / 7.6 / 16.4 | 3.8 / 6.8 / 15.2 | 8 / 16 / 32 |
| 75/25 | 8 / 16 / 32 | 2.2 / 3.8 / 8.4 | 1.8 / 3.4 / 8.0 | 0 / 1.6 / 1.8 |

- The losing side's blocks, including safe-confirmed ones, are orphaned roughly linearly
  in D.
- **50/50**: no block reaches the TSQ quorum, so the stable root falls back to the Simplex
  root for the cut plus one round.
- **75/25**: the majority keeps TSQ locks.
- No run produced conflicting stable roots or conflicting finalization. Heads re-converge
  one slot after GST.
- In 75/25 runs, finality slips one round exactly when the majority chain misses a
  round-start proposal right after a majority-only round (6/6 cases). That is consistent
  with the previous round's last-slot votes needing the next block for inclusion, which
  needs ≥ 2/3 · R/(R−1) responsive stake (R = slots per round).
