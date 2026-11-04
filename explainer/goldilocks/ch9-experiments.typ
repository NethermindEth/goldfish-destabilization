#import "style.typ": *

= 9. First Experiments

== 9.1 An Executable Model of the Spec

No executable Goldilocks fork choice exists upstream yet, so we wrote one. `goldilocks/model.py` transcribes the FGSA pseudocode figure by figure: the node (F2), the FG (F3), the validator client (F4), the state transition (F5) and the Goldilocks AC (F7–F9). Each function carries a comment pointing at its figure and line. `goldilocks/sim.py` drives $N$ nodes on the $Delta$ ticks of §2.2. It processes objects that arrive strictly before a public time before that tick, and objects that arrive exactly at it after the tick. The driver adds partition windows, sleep/restart and metrics.

#chapter-table(columns: (1fr, 2.2fr),
  [*Setting*], [*Value*],
  [validators / nodes], [$n = 64$ on 4 nodes (16 each, unless shares are given); $q = 43$, $n\/2 = 32$],
  [time], [$Delta = Delta_F = 1.5$ s, slot $= 6$ s, $R = 8$, $delta_t = 8$ slots, $K_W = 4$, $k = 4$],
  [network], [latency 200 ms (+ optional uniform jitter, kept below $Delta$ after GST)],
  [partition], [messages crossing the cut during $[s_0, s_0 + D)$ are held and released at the heal (+ latency, + optional spread). The heal is GST],
  [sleep], [a node receives nothing and does not tick; messages wait for its wake; it restarts at the wake time (§7)],
)

*Simplifications.* Validators of one node share one AC state, so they see each other's votes at once and vote alike (as in the old harness). Every validator attests at every action time ($K_s = V$, no attestation committees). There are no signatures, no slashing and no payload form checks; all nodes are honest. A block whose parent is missing waits until the parent arrives, which models re-delivery.

*Checks.* An independent review compared the code with the spec line by line. It found no deviation in the protocol logic. It found two restart-timing issues in the driver and a slot-biased tie order, all fixed before the runs reported here. At every slot the tracker checks $F prec.eq "confirmed" prec.eq "head"$ and $"fc_root" prec.eq "head"$ (requirement 3 of §2.5) for every node. At every action time it checks that `fg_confirmed` is in the viable tree under the head (requirement 2). No run violated either. A run of 100 slots takes under a second.

*Metrics.* Per node and slot: *reorgs* (the head switches to a conflicting block); *step-backs* (the head moves to an ancestor); *orphaned confirmations* (blocks that were a node's confirmed tip and are off its final chain); *conflicting live locks* across honest nodes; agreement of heads and of confirmed tips; and the FG caches.

== 9.2 The Partition Study

Same shapes as the first study on the SG protocol: 50/50 and 75/25 cuts, three-way, near-tie, short and long, single and repeated. Cuts start at slot 48, after finality is running, as agreed at the 19 October meeting. Reproduce with `python scenarios.py`; explore with `explorer.html`.

#figure(
  chapter-table(columns: (1.25fr, 0.5fr, 0.62fr, 0.62fr, 0.62fr, 0.9fr, 1.6fr),
    [*scenario*], [*heal*], [*heads agree*], [*max reorg*], [*orph. conf.*], [*lock conflicts (slots)*], [*finality (slot → F)*],
    [honest], [—], [—], [0], [0], [0], [every 8 slots, lag 16–24],
    [50/50, D = 16], [64], [+0], [0 (8 step-backs)], [8], [52–63], [stalls in cut; 65→34, 82→65],
    [75/25, D = 16], [64], [+0], [3 (minority)], [3], [56–63], [on schedule throughout (majority)],
    [50/50, D = 2], [50], [+2], [1], [1], [0], [on time; target shifts: 66→52],
    [75/25, D = 2], [50], [+0], [0], [0], [0], [unaffected],
    [50/50, D = 64], [112], [+0], [0 (35 step-backs)], [35], [52–111], [stalls 8 rounds; 130→113],
    [75/25, D = 64], [112], [+0], [13 (minority)], [13], [56–111], [majority unaffected],
    [50/25/25, D = 16], [64], [+0], [5], [5], [55–63], [stalls in cut],
    [52/48, D = 16], [64], [+0], [7 (48% side)], [7], [55–63], [stalls in cut],
    [50/50 then 75/25], [68], [+0], [1], [5], [52–67], [stalls in first cut; on time after],
    [25% asleep], [64], [+0], [0], [0], [0], [unaffected],
    [50% asleep], [64], [+0], [0], [0], [0], [stalls (32 < 43); resumes at 66],
    [75% asleep], [64], [+0], [0], [0], [0], [stalls; resumes a round after wake],
    [1-slot cut at 48 ($= r R$)], [49], [+0], [0], [0], [0], [*one round lost*: 58→34],
    [1-slot cut at 49], [50], [+0], [0], [0], [0], [one slot late: 51→34],
  ),
  caption: [The first partition study (64 validators, 4 nodes). "heads agree" is in slots after the heal. No run had conflicting live locks after GST, conflicting finalized blocks, or an invariant violation.],
)

== 9.3 Reading the Runs

#fig("run-honest.svg")[Honest run, node 0. The y axis is how many slots each tip is behind the current slot, so a flat line at 0 is a head that keeps up. The confirmed tip is one slot behind. The four yellow dots per slot are the live locks on the last four blocks. The finalized tip draws a sawtooth between 16 and 24 slots behind: one height per round, finalized two rounds after its target.]

#observed[
*75/25.* The majority side (48 validators, $> q$) does not notice the cut: it keeps confirming, fast-locking and finalizing. The minority (16 validators) confirms its own blocks, because 16 of its 16 participants is a strict majority. It never fast-locks, since $2 dot 16 < 64$, but after $k = 4$ consecutive confirmations it *slow-locks* its branch. These are the "conflicting live locks" of the table. At the heal, the 48 majority votes oppose the minority's locks, which move back at the next unlocking. The minority reorgs onto the majority chain (depth 3 for a 16-slot cut, 13 for a 64-slot cut). Its confirmations during the cut are orphaned. That is allowed before GST, and it is exactly why the protocol does not finalize on committee votes.
]

#fig("run-p75.svg")[75/25 cut over slots 48–63 (grey). Top: a majority node. Bottom: the minority node, whose head and confirmed tip lag while it builds a branch with few proposers. Its locks (yellow) sit on that branch, and its blocks are hollow because they end up off the final chain. At the heal it jumps to the majority chain within one slot.]

#observed[
*50/50: both sides fast-lock, and both lose everything.* Each side has exactly $n\/2 = 32$ validators, so it confirms its own branch *and passes the fast test* ($2 dot 32 >= 64$). Conflicting *fast* locks form on the two sides from about four slots into the cut. Neither side reaches $q = 43$, so finality stalls. At the heal, each lock has exactly 32 opponents. That is not fewer than half, so both locks move back to the last common block (#47 here). With 32 supporters out of 64 voters, neither branch is a strict majority of the voters, so the head walk stops at that common block. *Every block built during the cut is discarded, on both sides*: 8 confirmed blocks per node in a 16-slot cut, 35 in a 64-slot cut. The heads agree at once (+0 slots), and the protocol is live again with the next proposal. This is a clean outcome for safety, but the user-facing "confirmed and locked" label meant little during the cut.
]

#fig("run-p50.svg")[50/50 cut over slots 48–63. On both sides the head and the confirmed tip keep up during the cut, with locks on their own branch. All of it is hollow (orphaned). At the heal both step back to the pre-cut block, about 16 slots behind, and recover in one slot. Finality stalls during the cut and resumes within two rounds.]

#fig("run-p52.svg")[52/48 cut (33 vs 31 validators). Only the 33-side passes the fast test ($66 >= 64$). The 31-side only slow-locks. At the heal the 33-side's locks have 31 opponents ($62 < 64$) and survive, while the 31-side's locks have 33 and move back. The 33-side's branch wins and the 31-side reorgs (depth 7). Compare with 50/50, where two more validators on one side would have saved that side's whole branch.]

#observed[
*Low participation.* With 75% asleep, the awake node confirms every slot that has a proposer on its side. It slow-locks every $k$ slots and never fast-locks, so nobody attests and the FG stalls (Chapter 6). On waking, the sleepers restart. They keep their locks, which have expired by then, and they rejoin within a slot. No awake node reorged, and every confirmation stayed on the final chain: the slow locks did their job. Finality resumed one round after the wake, because the first slot of the round had too few votes (§7).
]

#fig("run-sleep75.svg")[75% asleep over slots 48–63 (purple: node 1 asleep). Node 0, alone, keeps a head and a confirmed tip that lag only when its own validators do not propose. It keeps slow locks (sparse yellow). The finalized tip falls behind linearly until a round after the others wake.]

== 9.4 A Single Slot Can Cost a Round of Finality

#observed[
A one-slot 50/50 cut at slot 48, the first slot of round 6, makes the confirmation update of slot 48 return $bot$ on *every* node. All 64 validators count as participants, but only 32 votes per node arrived before the support cutoff. Since `fg_confirmed` reads only the update of slot $r R$, nobody attests in round 6, and finality is delayed by a full round (the step expected at slot 50 comes at 58). The same cut one slot later (slot 49) delays finality by one slot. The protocol stays safe and the AC is unaffected. This is a liveness sensitivity of the FG interface, and an adversary that can delay one slot per round could exploit it (Chapter 10).
]

== 9.5 Messier Heals: The Seeded Sweep

The table below is a reduced version of `goldilocks/sweep.py`: 4 cut shapes × 2 durations × 2 release spreads × 3 seeds, with post-GST jitter up to 1 s. A *spread* means that held messages are released at random times up to 12 s (2 slots) after the heal. *Effective GST* is the moment every held message has been delivered. All columns are in slots relative to effective GST and show the worst case over seeds. "—" means the event never happened after GST. A negative value means it was already settled before effective GST.

#figure(
  include "figures/sweep-table.typ",
  caption: [Healing against effective GST. The full sweep (`sweep.py`, 10 seeds, 4 spreads, 320 runs) gives the same picture: no conflicting live lock after effective GST, heads and confirmed tips agreeing by GST + 3 at worst, no finality conflict.],
)

The slides bound healing by GST $+ 2L + G$, which here is at least 8 slots plus the wait for an honest proposer. Every honest-only run healed far inside that bound, within about three slots. The only events after effective GST are confirmed tips that a node showed one or two slots after GST and then abandoned. They come from short (2-slot) cuts, in the window before the first post-GST lock. This is consistent with the claim, which promises nothing before the drain. *Honest partitions do not reach the worst case of the bound.* The bad case of slide 11 needs pre-GST locks that are *not* opposed by $n\/2$ votes after GST, together with Goldfish votes that split. That requires adversarial votes or adversarial timing, and it is the next experiment (Chapter 10).

== 9.6 Compared With the SG Protocol

#chapter-table(columns: (1fr, 1.6fr, 1.6fr),
  [], [*DC with SG (first study)*], [*Goldilocks (this study)*],
  [50/50, 16 slots], [heads reconverge +1; one side's branch kept], [heads agree +0; *both* branches discarded],
  [75/25], [majority finalizes; minority reorgs], [same; the minority's slow locks are undone by the majority's votes],
  [what the fork choice reads], [blocks, committee votes, full-set head votes (grades, TSQ)], [blocks and current committee votes only],
  [post-heal liveness depends on], [re-gossip of equivocated attestations (our adversary study)], [nothing from attestations; Goldfish vote equivocations are counted for every block],
)

#recap[
The executable model reproduces the honest behaviour that the spec describes: confirmed tip one slot behind, $k$ live locks, finality two rounds behind. In every honest partition, conflicting locks formed before GST and none survived it. Every run healed within about three slots, far inside $2L + G$, and safety always held. Two findings deserve attention. In an exact 50/50 cut both sides fast-lock and both branches are discarded. A single bad slot at a round start costs that round's attestations.
]
