# Goldilocks, live spec: executable model and partition harness

An executable transcription of the live Goldilocks spec, `ethlabs-org/eth-consensus-lean` at commit
`4a63033e` (10 Nov 2026), `specs/goldilocks/tex/` (`goldilocks-spec.tex`, `shared/composition.tex`,
`shared/fg.tex`). `../goldilocks/` is the same harness on the 22 Oct 2026 text; this folder reuses its
driver and CLI, and replaces the protocol.

**What the live spec changes**, and where it is in `model.py`:

| Change | Where |
|---|---|
| Honest nodes forward every object they accept, also the votes and attestations a block carries | `Node` receipt handlers (`--no-forward` turns it off, not the spec) |
| The FG update runs after every tick (the FG gets a new source every slot), not once per round | `Node.on_tick`, `AC.to_fg` |
| A node votes as soon as it holds a ready proposal, else at t_s+Δ | `AC.try_vote` |
| The vote reads the merged view (pre-freeze votes plus the proposals' payload) and walks the full tree when its voter block tree has no viable block | `AC.merged_vote_view`, `AC.try_vote` |
| Optimistic confirmation: 3/4 of the committee before t_s+2Δ gives a fast lock | `AC.optimistic_confirmation` |
| Locks `(B, j, f, e)` with an expiry; graded fast locks (`fast_expiry`, increment `c`); a lock lives until t_{e+1} | `AC.fast_expiry`, `AC.live_locks` |
| A vetoed update still writes its locks below the vetoing lock; fast and slow locks are separate | `AC.update_confirmation` |
| Unlocking before each vote and proposal, against that action's view | `AC.unlock` |
| FG: K_W = 2, the finality pair from the entry state, and a height whose previous height is justified waits for its predecessor | `Client`, `process_height_events` |

**Run.**

```sh
python partition_run.py --groups 2,2 --start 48 --slots-down 16   # one run, per-slot table
python scenarios.py --out results/first                           # the partition study of ../goldilocks
python timeout_sweep.py                                           # heal-to-finality time against δ_t
```

| File | Contents |
|---|---|
| `model.py` | The protocol, under the spec's figure names |
| `sim.py` | The driver of `../goldilocks/sim.py`; receipt handlers can send (forwarding, early votes) |
| `partition_run.py`, `scenarios.py` | The CLI and the named scenarios of `../goldilocks`, on this model |
| `timeout_sweep.py` | How fast finality returns after a cut, against the FG timeout delay δ_t |
| `data/runs/` | The runs of the partition study |

**Model.** `n = 64` validators of weight 1 on 4 nodes; Δ = Δ_F = 1500 ms (slot 6 s); k = 4, c = 2,
K_W = 2, δ_t = 8 (as in `../goldilocks`, for comparison; the spec asks δ_t ≥ x + c_F + k_F with
c_F = 2 here). Every validator is on every slot committee.

**Simplifications.** As in `../goldilocks`: validators of a node share one AC state; no signatures,
slashing or wire-form checks beyond `ac_valid_payload`; a block with a missing parent waits for it.
The checks that the spec runs after each receipt run once after a batch of votes from one message
(see the docstring of `model.py` for why this changes nothing).

**Not yet here.** The adversary of `../goldilocks/adversary.py` (the finalization-hiding attacks
and their controls) runs on the 22 Oct model only; there, `--relay-carried` is the live spec's
forwarding rule and closes the attacks (explorer tab 17).
