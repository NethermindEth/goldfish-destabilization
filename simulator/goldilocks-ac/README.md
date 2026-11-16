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

**Faults on a group** (`attack_sweep.py --family asym`, 3300 runs: a target group of 1 to 4 of the
online nodes, 1 to 6 slots, 8, 6 or 4 of 8 nodes online). Partitions of the group, holding every
message into it, or holding or delaying only the votes into it never cost a block confirmed before
the fault; only what the cut-off side confirmed during it is lost. Votes that reach the group after
the +3 s cutoff change nothing at all.

**Blocks withheld from half of the online validators** (`--family blocks`, 1296 runs, and explorer
tab 12). Holding only the blocks into a group, while its votes still flow, is harmless for a group
of one node or of all online nodes but one. For a group of exactly half of the online validators,
2 of the 6 proposer schedules with all 8 nodes online (faults of 7 slots or more) and 1 of 6 with 6
online (5 slots or more) lose every block confirmed since the last finalized block: 46–47 slots in
the sweep. With 4 online it never happened. The spec allows it: the votes for blocks a node
does not have count as voters but support no block, not even the last common ancestor, so no block
of the cut-off half holds a strict majority and it stops confirming. When its last lock expires, its
head walk starts from the fork-choice root, which is the last finalized block, and its proposer
builds there. With the online stake split exactly in half, no block of the old chain regains a
majority, and every node follows the new chain. With the finality gadget running, the root is a
few slots behind the head; with fewer than 2/3 online it is the last block finalized before
participation dropped.

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
| `attack_sweep.py` | Network faults against participation, what is lost before and during each fault: on every link (`data/sweeps/attack.json`), on a group (`attack_asym.json`), blocks withheld from a group (`attack_blocks.json`) |
| `build_explorer.sh`, `explorer_meta.json` | The explorer page, with an About card per tab |
| `data/runs/` | The runs of the explorer tabs |
| `data/sweeps/` | The sweeps |

**Model.** `n = 64` validators of weight 1 on 4 nodes; Δ = 1500 ms (slot 6 s); k = 4, c = 2. Every
validator is on every slot committee. The simplifications are those of `../goldilocks-live`.
