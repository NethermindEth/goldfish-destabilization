#import "style.typ": *

= 5. Goldfish on the Frame: Votes, Head Walk, Proposal, Vote

This chapter covers the part of the AC that existed already in Goldfish: one-slot votes, a majority-gated walk, and view merge. What is new is that the walk runs on the FG frame and starts at an *anchor* given by the locks. The locks themselves are in Chapter 6.

== 5.1 Goldfish Votes and the Vote Pool

A Goldfish vote is $(v, s, B)$: validator $v$ says that at slot $s$ its head is $B$ #specref[§3.1]. In the FGSA model the slot committee is the whole set, $K_s = V$. Upstream, a committee of 1024 seats is sampled per slot by effective balance. The AC keeps the votes of each slot in a pool $A\."gf_votes"[s]$ #specref[F7.18]:

- a vote is accepted only during its own slot or the next one, so older votes are dropped on arrival (one-slot memory);
- at most *two distinct* votes per validator are kept, which is enough to prove an equivocation. A validator with two distinct votes in a slot is an *equivocator* for that slot;
- a vote whose head is unknown is kept; it is simply not *resolved* yet.

#formula-card[
*Resolution* #specref[F8.1]. A vote with head $H$ is resolved when $H$ is in $Phi\."tree"$ and $H\."slot"$ is at most the vote's slot. Its *resolution time* is the later of the vote's arrival stamp and the block's arrival stamp; an unresolved vote has resolution time $+infinity$. The test reads the current frame at every use: if $F$ moves past the head, the vote stops being resolved.
]

Timestamps are the key to the timing rules. "Counted for confirmation" means resolved *before* $t_s + 2 Delta$, and "in the vote's view" means resolved before the freeze. A vote that arrives late, or whose block arrives late, still sits in the pool but does not count for those purposes.

== 5.2 The Head Walk

#formula-card[
`ghost(anchor, tree, score, eligible)` #specref[F9.5]: start at the anchor; repeatedly move to the eligible child with the highest score (ties by root order); stop when no child is eligible.

*Score of $B$* #specref[F9.1]: the number of equivocators, plus the number of non-equivocating validators whose (resolved) support vote has a head extending $B$. *Equivocators count for every block.*

*Eligible child $B$* #specref[F9.12]: if its parent is not a viable head (the walk has not yet reached the viable heights and must keep going); or if $B$ is a block of the current slot; or if $2 dot "score"(B) > $ the number of validators with a vote.
]

The walk runs in the *full viable tree* and starts at the *anchor*. The anchor is the deepest locked block of the viable tree, or the fork-choice root if no block is locked (§6.5).

The three eligibility clauses each have a job:
- *Not yet viable:* the walk must at least reach the viable heights of the frame, whatever the votes say.
- *Current slot:* a fresh proposal has no votes yet, but it must be able to become the head, or no one could ever vote for it.
- *Strict majority of voters:* once on a viable head, the walk descends only into a child that a majority of the validators who voted in that slot support. Otherwise it stops. This makes a stopped head "safe to build on": no competing child has a majority.

Counting equivocators for every block means an equivocation cannot help one branch against another. It still adds the equivocator to the number of voters, and it adds the same amount to every score.

*Which votes does the head read?* `ac_head` reads the latest slot whose votes are due: slot $s - 1$ before $t_s + 2 Delta$, slot $s$ from then on #specref[F7.40]. After GST, every honest slot-$s$ vote reaches every awake node by $t_s + 2 Delta$, so the head never reads a pool that is still filling.

== 5.3 The Proposal

At $t_s$ the proposer of slot $s$ computes its head with the slot-$(s-1)$ votes and builds on it #specref[F7.25]. Into the block it puts:
- `votes`: every slot-$(s-1)$ vote it holds, in pool order;
- `support_votes`: exactly those of them that are resolved at proposal time.

These lists are the proposer's *view*, published so that the voters of slot $s$ can merge it.

== 5.4 The Vote and Its Freeze: View Merge

#block(breakable: false)[
#problem[
Two honest voters can disagree on the head simply because one received a slot-$(s-1)$ vote, or a block, a few milliseconds before the other. Goldfish confirms only if honest voters line up behind the same block.
]
#idea[
*View merge.* Each voter freezes its own view at the previous slot's freeze time, then adds what the slot-$s$ proposal carries. After GST, an honest proposer at $t_s$ already holds everything any honest voter froze at $t_(s-1) + 3 Delta$, because relaying takes at most $Delta$. So every honest voter ends up with the same merged view, and with it the same head: the honest proposal.
]
]

#formula-card[
*The vote at $t_s + Delta$* #specref[F9.37]. With $"freeze" = t_(s-1) + 3 Delta$:
- *votes:* the slot-$(s-1)$ votes received before the freeze, plus the `votes` of every slot-$s$ proposal in $Phi\."tree"$;
- *support:* those votes resolved before the freeze, plus the `support_votes` of the slot-$s$ proposals whose head is in $Phi\."tree"$ with slot at most $s - 1$;
- *tree:* the *voter block tree*: blocks received before the freeze, plus every ancestor of a slot-$s$ proposal. Then take its viable tree (not the full viable tree cut afterwards, so a late block cannot make an old child enter the walk);
- *head:* the walk from the anchor in that tree. Each local validator sends $(v, s, "head")$.
Just before voting, the node runs *unlocking* against the slot-$(s-1)$ votes (§6.4), so the anchor the vote uses is already adjusted.
]

#example[
Honest steady state, $n = 64$. At $t_s + Delta$ every voter holds the slot-$s$ proposal $P_s$, which is a child of the previous head and is eligible as a current-slot block. All 64 validators vote $P_s$. The votes arrive before $t_s + 2 Delta$, so at $t_s + 6 Delta$ the confirmation update of slot $s$ sees 64 early votes on $P_s$. It confirms $P_s$ and fast-locks it (Chapter 6). In our runs this gives a confirmed tip exactly one slot behind the head, observed at $t_(s+1) + 3 Delta$.
]

#recap[
Votes live for one slot; at most two per validator are kept; a vote counts once its head is known (resolution), and the timing rules compare resolution times with $t_s + 2 Delta$ and the freeze. The head is a majority-gated walk from the anchor in the viable tree, with fresh proposals always eligible and equivocators counted everywhere. The vote merges the proposer's published view with the voter's frozen view, so honest voters agree after GST.
]
