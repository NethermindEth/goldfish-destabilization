# Goldilocks: executable model and partition harness

An executable transcription of the FGSA Goldilocks spec of 22 Oct 2026 (`fgsa-spec-22102026.pdf`): the node,
the finality gadget, the validator client, the state transition and the Goldilocks available
chain (Goldfish votes, unlocking, confirmation update, fast/slow locks, anchor, restart).
Standard-library Python, no pyspec needed. The upstream executable spec
(`ethereum/consensus-specs@decoupled-consensus`, `specs/_features/eip8453`) has the beacon-chain
FG only, with no Goldilocks fork choice yet.

**Spec version.** The model follows the 22 Oct 2026 text. The live spec
(`ethlabs-org/eth-consensus-lean`, `specs/goldilocks/tex/`) has since changed the protocol: honest
nodes forward the votes carried by every block they accept, nodes vote as soon as they hold a
ready proposal, blocks declare their support votes, there is an optimistic confirmation at 3/4
of the committee, fast locks are graded and every lock expires at a slot start. Only the first
of these is in the model, as `adversary.py --relay-carried`; it closes the finalization-hiding
attacks (explorer tab 17).

**Explorer.** Open `explorer/goldilocks-explorer.html` in a browser: every experiment below, one
tab each, with an About card that says what to look at. `#run=<tab>&slot=<s>&mode=lag&win=16&from=<s>`
in the URL opens a tab at a slot. `bash build_explorer.sh` rebuilds it from the seeded runs into
`data/runs/`; `--new` also builds the newer UI (`explorer/goldilocks-explorer-new.html`), which shows
one run's per-slot state, events and messages.

**Data.** `data/runs/` holds the runs of the explorer tabs (`*.events.json`, and the summary of each
run in `*.json`).

```sh
python partition_run.py --groups 2,2 --start 48 --slots-down 16      # one run, per-slot table
python partition_run.py --groups 3,1 --start 48 --slots-down 16 --events out.events.json --json out.json
python scenarios.py                       # the first partition study -> results/first/
python sweep.py --seeds 10                # shapes x release spread x seeds vs the 2L healing claim
python adversary.py --strategy fin_hide_seq --seed 115 --group-a 0,1,2 --relay-ms 200 --slots 64   # one attack
python fin_hide_trace.py --seed 13 --relay-ms 200 --group-a 0,1,2   # the attack with equivocation, step by step
bash build_explorer.sh                    # data/runs/ and explorer/goldilocks-explorer.html
bash attack_suite.sh                      # the targeted attacks of the adversary study and their controls
```

| File | Contents |
|---|---|
| `model.py` | The protocol, figure by figure (`# F8.18` = spec figure 8, line 18) |
| `sim.py` | Driver: Δ ticks, network with partition windows and release spread, sleep/restart, metrics (`Tracker`) |
| `partition_run.py` | CLI: one scenario, per-slot table, summary, `--events` for the explorer |
| `scenarios.py` | Named scenarios of the first study (50/50, 75/25, 50/25/25, 52/48, short/long/repeated cuts, sleep, one-slot glitches, spread heals) |
| `sweep.py` | Seeded sweep, measured against effective GST |
| `adversary.py` | A one-third Byzantine adversary under synchrony: per-node delivery inside Δ, relay of every object (also a second vote), equivocation, timing attacks, random fuzzing; checks the synchrony claims. `--relay first-seen` and `--skew` leave the spec's model on purpose |
| `fuzz_batch.py` | Many seeded adversary runs in parallel; lists every run that breaks a claim |
| `honest_orphans.py` | Many seeded adversary runs; counts the honest proposals orphaned under synchrony |
| `contest_compare.py`, `contest_adv.py`, `contest_detail.py` | Frontier contests: the spec's finality rule against the Lean model's (`--lean-finality`), on partitions and adversary runs |
| `height_events.py` | Which heights on the final chain were justified and which were skipped by timeouts |
| `outage_sweep.py`, `outage_trace.py` | Asynchrony resilience of a fast confirmation against an adversary that controls an outage |
| `attack_suite.sh`, `attack_explorer.sh` | The adversary study in one go, and its explorer page |
| `explorer_classic.py` | The explorer (the UI of the earlier protocol's explorer): per-node head, confirmed tip, every live lock and the anchor, FG heights, block tree, per-slot zoom |
| `explorer.py` | The newer explorer UI, opt-in (`build_explorer.sh --new`): per-slot state, events and messages of one run |
| `build_explorer.sh`, `explorer_meta.json` | Every experiment on one explorer page, one tab each, with an About card |
| `explorer/` | The built explorer page |
| `data/` | The runs of the explorer tabs (`data/README.md`) |
| `fin_hide_trace.py` | Step-by-step trace of the finalization-hiding attack (`adversary.py --strategy fin_hide`) |

**Model.** `n` validators of weight 1 on `N` nodes; Δ = Δ_F = 1500 ms (slot 6 s); R = 8,
δ_t = 8, K_W = 4, k = 4 (lock length; not fixed upstream). Every validator is on every slot
committee (K_s = V) and attests at every round's action time, as in the abstract spec.

**Simplifications.** Validators of a node share one AC state. There are no signatures,
slashing or payload form checks; Byzantine behaviour lives in `adversary.py`. A block with a missing parent
waits for it (re-delivery).

**Checks.** At every slot the tracker checks F ⪯ confirmed ⪯ head and fc_root ⪯ head
(§1.5 requirement 3) for every node, and at every action time that `fg_confirmed` is in the
viable tree under the head (requirement 2). An independent line-by-line audit against the spec
found no deviation in the protocol logic. The driver issues it found are fixed.

The textbook, with the first experiments, is `../../explainer/goldilocks/goldilocks-textbook.pdf`
(chapter 9). The attack report is `../../reports/goldilocks-finalization-hiding/finalization_hiding.pdf`.
