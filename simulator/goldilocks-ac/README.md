# Goldilocks available chain alone: the live spec with nothing finalized

The available chain (AC) of the live Goldilocks spec, `ethlabs-org/eth-consensus-lean` at commit
`4a63033e` (10 Nov 2026), run on its own. It answers how the available chain behaves when the
finality gadget (FG) cannot help: while fewer than 2/3 of the validators are online, or for any
stretch of the chain that is not finalized yet.

**How.** The AC reads the FG only through the frame Φ = (tree, fc_root, allowed). An FG that never
processes an attestation stays at height 1 with nothing justified, so its frame is constant:
fc_root = F = genesis, and every accepted block is allowed. `model.py` imports the AC of
`../goldilocks-live/model.py` unchanged and runs it against that frame. Genesis plays the finalized
checkpoint, so a run describes any unfinalized stretch of the chain. There are no FG attestations,
no validator client, no heights or timeouts, and blocks carry only Goldfish votes and support votes.

**Check.** On honest, 50/50, 75/25 and sleep runs, every node's head, confirmed tip and live locks
are identical, slot by slot, to those of the live model with its attestations switched off.

**Run.**

```sh
python partition_run.py --groups 2,2 --start 48 --slots-down 16   # one run, per-slot table
python scenarios.py --out results/first                           # the partition and sleep study
python partition_run.py --nodes 8 --groups 8 --slots-down 0 --rule 48:51:*:*:vote:hold   # a votes-only outage
python attack_sweep.py                                            # faults against participation (~12 min, 24 cores)
bash build_explorer.sh                                            # data/runs/ and the explorer page
```

**Explorer.** `../goldilocks/explorer/goldilocks-ac-explorer.html` (online:
https://nethermindeth.github.io/goldfish-destabilization/goldilocks-ac-explorer.html) has the runs of
`build_explorer.sh`, one tab each. It is the live spec's page without any finality: no finality
row, no FG attestations, no finality column.

**Network faults.** `sim.py` takes delay rules on single links and message kinds: a rule holds the
messages sent in a time window from some nodes to others, or adds a fixed delay. Partitions are
hold rules across their cut; `--rule` adds outages of every link or of one message kind, eclipses
and extra delays.

**Symmetric faults** (`attack_sweep.py`, 1572 runs: 8 nodes, 3 proposer seeds, 0–3 Δ into the slot,
8, 6, 4 or 3 of 8 nodes online). A fault that hits every link alike never costs a block confirmed
before it, up to 6 slots and at every participation level. A full outage of 2 slots or more loses
only blocks that a node confirmed alone during it, at most D − 1 of them; votes-only and
blocks-only outages lose nothing. Extra vote delay changes nothing as long as the votes, sent about
0.2 s into the slot, still arrive before the +3 s cutoff of the confirmation count: up to 2.3 s on
top of the 0.2 s latency, beyond Δ. From 2.6 s on, no block is confirmed while it lasts, the heads
keep growing, and confirmation resumes when it ends. Damage to earlier confirmations needs asymmetric delivery: some nodes must
see what others do not.

**First results.** In every partition and sleep scenario the available chain does exactly what it
does in the live model with the FG running: the same reorgs, the same orphaned confirmed blocks,
the same time to agree after the heal. Finality never changed the outcome of a partition. A 50/50
cut of two slots already costs side A a confirmed and fast-locked block, because each side holds
exactly n/2 votes. A longer even cut discards every block confirmed during it on both sides. With
3/4 of the validators asleep, the awake quarter keeps confirming its own blocks and nothing is
orphaned at the wake.

| File | Contents |
|---|---|
| `model.py` | The frozen frame and the node without the FG; the AC is imported from `../goldilocks-live/model.py` |
| `sim.py` | The driver of `../goldilocks-live/sim.py` with blocks and votes only, and the AC's metrics |
| `partition_run.py`, `scenarios.py` | One run and the named partition and sleep scenarios |
| `attack_sweep.py` | Network faults against participation: full outage, votes-only and blocks-only outages, vote lag; what is lost before and during the fault -> `data/sweeps/attack.json` |
| `build_explorer.sh`, `explorer_meta.json` | The explorer page, with an About card per tab |
| `data/runs/` | The runs of the explorer tabs |
| `data/sweeps/` | The sweeps |

**Model.** `n = 64` validators of weight 1 on 4 nodes; Δ = 1500 ms (slot 6 s); k = 4, c = 2. Every
validator is on every slot committee. The simplifications are those of `../goldilocks-live`.
