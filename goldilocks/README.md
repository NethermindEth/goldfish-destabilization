# Goldilocks: executable model and partition harness

An executable transcription of the FGSA Goldilocks spec (`fgsa-spec-22102026.pdf`): the node,
the finality gadget, the validator client, the state transition and the Goldilocks available
chain (Goldfish votes, unlocking, confirmation update, fast/slow locks, anchor, restart).
Standard-library Python, no pyspec needed. The upstream executable spec
(`ethereum/consensus-specs@decoupled-consensus`, `specs/_features/eip8453`) has the beacon-chain
FG only, with no Goldilocks fork choice yet.

```sh
python partition_run.py --groups 2,2 --start 48 --slots-down 16      # one run, per-slot table
python partition_run.py --groups 3,1 --start 48 --slots-down 16 --events out.events.json --json out.json
python scenarios.py                       # the first partition study -> results/first/
python sweep.py --seeds 10                # shapes x release spread x seeds vs the 2L healing claim
python explorer.py results/first/explorer.html --index results/first     # interactive HTML
python adversary.py --strategy skew_fast --seed 7 --round-start --group-a 0 --skew 0:2   # one attack
bash attack_suite.sh                      # every attack and its control
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
| `attack_suite.sh`, `attack_explorer.sh` | The adversary study in one go, and its explorer page |
| `explorer.py` | Interactive explorer: per-node tips (lag), locks, block tree, FG heights, held messages, per-slot state/events/messages |

**Model.** `n` validators of weight 1 on `N` nodes; Δ = Δ_F = 1500 ms (slot 6 s); R = 8,
δ_t = 8, K_W = 4, k = 4 (lock length; not fixed upstream). Every validator is on every slot
committee (K_s = V) and attests at every round's action time, as in the abstract spec.

**Simplifications.** Validators of a node share one AC state. There are no signatures,
slashing or payload form checks, and no Byzantine behaviour yet. A block with a missing parent
waits for it (re-delivery).

**Checks.** At every slot the tracker checks F ⪯ confirmed ⪯ head and fc_root ⪯ head
(§1.5 requirement 3) for every node, and at every action time that `fg_confirmed` is in the
viable tree under the head (requirement 2). An independent line-by-line audit against the spec
found no deviation in the protocol logic. The driver issues it found are fixed.

The write-up, with all results, is `explainer/goldilocks/goldilocks-textbook.pdf`, chapter 9.
