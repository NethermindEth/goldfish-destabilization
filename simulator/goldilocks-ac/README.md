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

**A minority that votes for blocks it never releases** (`adv_sweep.py`, 1680 runs: f = 0 to 16 of
64 validators, 8 or 6 of 8 honest nodes online, every split of the online nodes, faults of 0 to 8
slots, 4 proposer schedules). Under synchrony alone (no fault) it costs nothing: an honest block
supported by every honest vote keeps a strict majority while the online honest stake exceeds f.
With the blocks-only fault the split no longer has to be even: the whole unfinalized chain is lost
for splits with |A| < |B| + f and |B| <= |A| + f, for example 20 against 32 online honest validators
with f = 12, or 18 against 30 with f = 16. The fault still has to last 5 slots or more, long enough
for the locks of the cut-off side to expire, and a run loses the chain in at most 2 of the 4
proposer schedules.

**The lock window sets how long the fault must last** (`window_sweep.py`, on Jed: the blocks-only
fault into exactly half of the online nodes, no adversary, lock windows k = 2, 3, 4, 6 and 8, faults
of 1 to 30 slots, 32 proposer schedules; `data/sweeps/window_long.json`). The shortest fault that
loses the unfinalized chain is 2, 3, 5, 7 and 17 slots for k = 2, 3, 4, 6 and 8 with all 8 nodes
online, and 2, 3, 5, 6 and 20 slots with 6 online: about k + 1 up to k = 6, since the cut-off half
keeps its head only while one of its locks lives. Past that point each extra slot gives the
proposer schedule another chance to hand the cut-off half a proposal on the old root. At k = 4 and
30 slots, 29 of 32 schedules lose the chain with 8 nodes online and 11 of 32 with 6 online; at
k = 8, 8 and 1 of 32. The fast increment c changes nothing (c = 2 and 4 in
`data/sweeps/window.json`, 8 schedules, faults up to 14 slots). The reorg depth these sweeps report
misses this loss: the cut-off half steps back to the root rather than switching to a conflicting
head, and a node asleep through the fault is not compared across its wake. The count of lost
confirmed blocks is the measure to read.

**A fault timed on the proposer schedule** (`timed_sweep.py`, on Jed: 17280 runs; all 8 nodes
online; A is half of them; `data/sweeps/timed.json`). Withholding blocks from A does not freeze A:
A's own proposals still reach the other half, so both sides confirm them and A renews its locks.
A falls only when the other half proposes in k consecutive slots, because A's last lock then
expires and its head walk starts from the last finalized block. Since the proposer schedule is
known in advance, the sweep takes, for each of 64 schedules, the first run of exactly r slots in
[48, 160) without a proposer in A, and withholds blocks from A during that run only (or from one
slot before it, to two slots after it). With r >= k every such run loses the whole unfinalized
chain in every schedule: 55 of 55 at k = 4 and r = 4, 21 of 21 at k = 6 and r = 6, 4 of 4 at
k = 8 and r = 8. With r < k no run loses it, except 9 of the 190 runs at r = k - 1 with k <= 4 whose fault starts one
slot early. At the
default k = 4 the attack is a 4-slot (24 s) cut of the blocks into half of the online stake, needs
no Byzantine validator, and 55 of 64 schedules offer a run of exactly 4 slots within 112 slots.
The fault lengths of `window_sweep.py` reflect how long a fault that starts at a fixed slot waits
for such a run, and runs of 8 slots are rare: 4 of 64 schedules have one, which is why k = 8 looked
like a jump.

**The timed fault with a Byzantine minority** (`timed_adv_sweep.py`, on Jed: f = 0 to 16 of 64
validators, every split of the 8 online honest nodes, runs of r = 3 to 6 slots without a proposer
in A, k = 4, 64 schedules; 8960 runs per variant). The f validators vote in every slot for a block
they never release, as in `adv_sweep.py`. If their own proposer slots stay empty
(`data/sweeps/timed_adv.json`) the attack gets weaker, not stronger: an even split of 28 against 28
with f = 8 loses the chain in 20 of 57 schedules instead of 55 of 55 with f = 0. An empty slot
inside the run gives B no new block, so B votes again for the last block A has, and A confirms it
and renews its locks. If the adversary instead fills its slots with the block an honest node of B
would build, sent to B only while the fault lasts (`--propose`, `data/sweeps/timed_adv_propose.json`),
the rule is exact: the whole unfinalized chain is lost if and only if r >= k and the two honest
sides differ by at most f validators. That holds in 1257 of 1257 runs, and none of the other 4207
runs loses a confirmed block. At f = 16, splits from 18 against 30 to 30 against 18 all fall to a
4-slot fault.

**Why the run must last k slots** (`lock_check.py`, on Jed: k = 2, 4, 6, runs of k - 1, k and
k + 1 slots, 64 schedules, 368 runs with a run found; `data/sweeps/lock_check.json`). Each step of
the argument is checked in every run. In the slot before the run every node confirms the same
block, and with steady confirmations the graded expiry of its fast locks has reached the cap j + k,
so every lock of A is gone after slot s0 - 1 + k. During the run no node confirms a new block,
because each block of B sits on the last common block with half of the votes, not a strict
majority. The first block A proposes after the expiry has no lock to follow and is built on the
fork-choice root, genesis here. A's half of the votes then conflict with B's locks, and a lock
moves back to an ancestor unless fewer than half of the validators vote against it, so B's locks
fall back to the root, or are gone already when k = 2 and the run lasts k + 1 slots. Every node
follows the new branch. With a run of k - 1 slots the slot after the run is A's, its proposer still
holds the lock and extends the old chain, every node confirms it, and nothing is lost. All 368 runs
follow these steps, and lose the chain exactly when r >= k.

**A lock that moves back only against a strict majority** (`strict_unlock_sweep.py`, on Jed: the
honest timed fault at k = 2, 4, 6 with runs of 1 to 9 slots, and the timed fault with a minority
that proposes for B, f = 0 to 16, every split, k = 4, runs of 3 to 6 slots, 64 schedules; 6466 runs
with a run found; `data/sweeps/strict_unlock.json`). The model's `Params.strict_unlock`, outside the
spec, moves a lock back only when more than half of the validators vote against it. Every run loses
exactly the blocks it loses under the spec's rule, in all 6466 runs, and every node agrees and
confirms again by the end. A trace of one run shows why. B's locks no longer move back when A
proposes on the root, but B confirms nothing during the fault either, so its locks expire a few
slots later, its head walk also starts from the fork-choice root, and every node confirms A's
branch. The unlock rule only decides when B gives up the old chain, not whether it does. What
loses the chain is that every lock expires without a confirmation, and the head walk then starts
from the last finalized block.

**Falling back to the last confirmed block** (`confirmed_anchor_sweep.py`, on Jed: the honest timed
fault at k = 2, 4, 6 with runs of 1 to 9 slots, with the change alone and with the strict unlock too;
the timed fault with a minority that proposes for B, f = 0 to 16, every split, k = 4, runs of 3 to 6
slots; 64 schedules; and the partition and blocks-only faults on a group of `attack_sweep.py --family
asym`, 3 schedules; `data/sweeps/confirmed_anchor.json`). The model's `Params.confirmed_anchor`,
outside the spec, makes a node with no live lock start its head walk from its last confirmed block
instead of the fork-choice root. The unlock rule moves that block back like a lock, so a node is not
held on it forever. No timed run loses a confirmed block: 0 of the 458 honest runs and 0 of the 1257
minority runs that lose the whole chain under the spec, with the spec's unlock rule or the strict
one. A's proposer now builds on A's last confirmed block, which B's chain extends, so nobody votes
against it. Every run ends with all nodes on one head and confirming. The 1320 partition and
blocks-only runs on a group recover exactly as they do under the spec, slot for slot, except 4 runs
with 6 nodes online and blocks withheld from 3 of them: under the spec those lose the unfinalized
chain, and with the change they lose nothing. These runs check the available chain alone, not the
spec's proofs, the sleep scenarios, or the model with the finality gadget.

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
| `adv_sweep.py` | A minority voting for blocks it never releases, alone and with the blocks-only fault -> `data/sweeps/adv_withheld.json` |
| `window_sweep.py` | The blocks-only fault into half of the online nodes under lock windows k = 2 to 8 -> `data/sweeps/window.json`, `window_long.json` |
| `timed_sweep.py` | The blocks-only fault timed on a run of r slots without a proposer of the cut-off half -> `data/sweeps/timed.json` |
| `timed_adv_sweep.py` | The timed fault with a minority voting for withheld blocks, with its proposer slots empty or filled for B -> `data/sweeps/timed_adv.json`, `timed_adv_propose.json` |
| `lock_check.py` | Checks each step of why the timed fault needs k slots: lock expiry, no confirmation, the proposal on the root, B's locks moving back -> `data/sweeps/lock_check.json` |
| `strict_unlock_sweep.py` | The timed fault, honest and with a minority, with a lock that moves back only against a strict majority -> `data/sweeps/strict_unlock.json` |
| `confirmed_anchor_sweep.py` | The timed fault and the faults on a group when a node with no live lock falls back to its last confirmed block -> `data/sweeps/confirmed_anchor.json` |
| `jed.sbatch` | Runs one sweep on a node of the Jed cluster: `sbatch jed.sbatch adv_sweep.py --seeds 4` |
| `build_explorer.sh`, `explorer_meta.json` | The explorer page, with an About card per tab |
| `data/runs/` | The runs of the explorer tabs |
| `data/sweeps/` | The sweeps |

**Model.** `n = 64` validators of weight 1 on 4 nodes; Δ = 1500 ms (slot 6 s); k = 4, c = 2. Every
validator is on every slot committee. The simplifications are those of `../goldilocks-live`.
