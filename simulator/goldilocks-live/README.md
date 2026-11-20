# Goldilocks, live spec: executable model and partition harness

An executable transcription of the live Goldilocks spec, `ethlabs-org/eth-consensus-lean` at commit
`4a63033e` (10 Nov 2026), `specs/goldilocks/tex/` (`goldilocks-spec.tex`, `shared/composition.tex`,
`shared/fg.tex`). `../goldilocks/` is the same harness on the 22 Oct 2026 text; this folder reuses its
driver, CLI and explorer, and replaces the protocol.

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

**Explorer.** `../goldilocks/explorer/goldilocks-live-explorer.html` (online:
https://nethermindeth.github.io/goldfish-destabilization/goldilocks-live-explorer.html) has these runs,
one tab each. It is the explorer of `../goldilocks` with the live spec's timeline: votes at their real
time, optimistic confirmations, an FG attestation after any tick, no rounds, every lock with its expiry,
and how long each node's newest fast lock lives (the graded fast locks). `bash build_explorer.sh` rebuilds the runs into `data/runs/` and the page.

**The timed blocks-only fault with the FG running** (`timed_sweep.py`, on Jed: 2244 runs; 8, 6 or 4
of 8 nodes online, the others asleep from slot 40; A is half of the online nodes; k = 2, 4, 6; runs
of 1 to 8 slots proposed by B; 64 schedules; `data/sweeps/timed.json`). On the available chain alone
this fault loses every block confirmed since genesis (`../goldilocks-ac`). Here, with 8 or 6 nodes
online (2/3 of the stake or more), no run loses a confirmed block, at any k and run length. The
fork-choice root is the latest justified block, one slot or so behind the confirmed tip, and FG
attestations still flow during a blocks-only fault: they justify the last block A confirmed before
the run, so when A's locks expire, it falls back to that block and loses only its own unconfirmed
proposal. With 4 of 8 online the FG stalls at slot 38 and the rule of the available chain returns
exactly: a run of r >= k slots loses every block confirmed after slot 38 (up to 53), a shorter one
loses nothing. No two nodes ever finalize conflicting blocks.

| File | Contents |
|---|---|
| `model.py` | The protocol, under the spec's figure names |
| `sim.py` | The driver of `../goldilocks/sim.py`; receipt handlers can send (forwarding, early votes) |
| `partition_run.py`, `scenarios.py` | The CLI and the named scenarios of `../goldilocks`, on this model |
| `timed_sweep.py` | The blocks-only fault timed on k slots proposed by one half, with the FG running -> `data/sweeps/timed.json` |
| `timeout_sweep.py` | How fast finality returns after a cut, against the FG timeout delay δ_t |
| `build_explorer.sh`, `explorer_meta.json` | The explorer page of the live spec, with an About card per tab |
| `data/runs/` | The runs of the explorer tabs |

**Model.** `n = 64` validators of weight 1 on 4 nodes; Δ = Δ_F = 1500 ms (slot 6 s); k = 4, c = 2,
K_W = 2, δ_t = 8 (as in `../goldilocks`, for comparison; the spec asks δ_t ≥ x + c_F + k_F with
c_F = 2 here). Every validator is on every slot committee.

**Simplifications.** As in `../goldilocks`: validators of a node share one AC state; no signatures,
slashing or wire-form checks beyond `ac_valid_payload`; a block with a missing parent waits for it.
The checks that the spec runs after each receipt run once after a batch of votes from one message
(see the docstring of `model.py` for why this changes nothing).

**Not yet here.** The adversary of `../goldilocks/adversary.py` (the finalization-hiding attacks
and their controls) runs on the 22 Oct model only; there, `--relay-carried` is the live spec's
forwarding rule and closes the attacks (explorer tab 13).
