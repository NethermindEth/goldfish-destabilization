#import "style.typ": *

= 6. Confirmation and Locks

== 6.1 The Confirmation Update

#block(breakable: false)[
#problem[
Goldfish confirms a block when a majority of a slot's voters were on it in time. The next slot it has forgotten that. If votes then go missing, the head can be pulled away from a block that users were told is confirmed.
]
#idea[
Each confirmation also writes a *lock* that holds the confirmed block for $k$ slots. While the lock lives, conflicting confirmations are vetoed and the head walk starts no higher than the locked block. The lock dies when it expires, or when half of a committee votes against it.
]
]

#formula-card[
*Confirmation update of slot $s$, at $t_s + 6 Delta$* #specref[F8.19–40]:
+ *Walk.* Starting at $Phi\.F$, descend in $Phi\."tree"$ into children held by a *strict majority of the participants* of slot $s$. Support counts only *non-equivocating* votes *resolved before $t_s + 2 Delta$*. Participants are all validators with a slot-$s$ vote. The result $C$ is the end of the walk if it holds that majority (also when it is $Phi\.F$), else $bot$.
+ *Save.* $A\."saved_confirmation"[s] <- C$, even if a lock vetoes it.
+ *Veto.* If $C = bot$, or $C$ conflicts with the block of a live lock, stop.
+ *Advance the record.* An ancestor of the current record leaves it unchanged; an extension or a *conflicting* block replaces it.
+ *Lock.* On the chain of $C$, take the deepest non-genesis block $B$ that passes one of two tests:
  - *fast:* at least half of the whole committee supports $B$: $2 dot "score"(B) >= n$;
  - *slow:* the saved confirmations of the previous $k - 1$ slots are all in the tree and all extend $B$.
  Write the lock $(B, t_(s+k) + 5 Delta)$. Remember the fast-passing blocks of the chain in $A\."fast_confirmed"$.
]

The two thresholds measure different things. The confirmation walk is *relative*: a strict majority of whoever voted in the slot. It keeps working when most validators sleep, which is dynamic availability. The fast test is *absolute*: half of the whole committee. The slow test replaces the fast one when participation is low: $k$ consecutive slots confirmed a chain through $B$ (slide 7).

#fig("locks.svg")[Fast and slow locking, after slide 7.]

== 6.2 Live Locks, Locked Blocks, Expiry

A lock $(B, d)$ is *live* when $d > t$ and $B in Phi\."tree"$ #specref[§3.2]. Every ancestor of a live lock's block is *locked*. A live lock *vetoes* a block that conflicts with its block. Each update writes at most one lock, each with its own deadline. A lock expires at the first tick at or after its deadline. The lock written at $t_s + 6 Delta = t_(s+1) + 2 Delta$ has deadline $t_(s+k) + 5 Delta = t_(s+k+1) + Delta$. Expiry runs first in that tick, so the vote of slot $s + k + 1$ no longer sees the lock. A lock therefore lives for $k$ slots.

When $Phi\.F$ advances, no rule acts on the locks: a lock whose block left the tree is simply not live, and it never becomes live again.

#observed[
In the honest steady state with $k = 4$, every node holds exactly four live locks, on the blocks of slots $s - 4, dots, s - 1$, each written one slot after the previous one. All are fast locks, because all 64 validators vote for each block in time.
]

== 6.3 The Confirmed Tip

The confirmed tip shown to users is the deepest common ancestor of the record (or $Phi\.F$ if the record left the tree) and the current head #specref[F7.46]. It is never ahead of the head. It can *step back* while the head is behind the record or on another branch, and it moves forward again once the head does. No voting rule reads it.

== 6.4 Unlocking: Half of a Committee Against

#formula-card[
*Unlocking against slot-$s$ votes, at $t_s + 5 Delta$* #specref[F8.6]. Each live lock $(B, d)$ moves back to the deepest $B'$ with $Phi\.F prec.eq B' prec.eq B$ that has fewer than half of the committee as *opponents*: $2 |"opp"(B')| < n$. Opponents are non-equivocating validators with a resolved slot-$s$ vote whose head conflicts with $B'$. The deadline is kept.
]

Opponents of an ancestor are a subset of the opponents of a descendant, so the blocks that survive form a prefix of $B$'s chain. $Phi\.F$ never has opponents, so the move is always defined. A lock on $Phi\.F$ has no effect.

#fig("unlock.svg")[The two ways a lock ends: moved back by a half-committee majority voting elsewhere, or expiry (slide 8).]

#caveat[
Look at the two thresholds together. A block is fast-locked with *at least* $n\/2$ support, and a lock survives only with *strictly fewer* than $n\/2$ opponents. In an exact half/half split, both halves fast-lock their own branch: $2 dot 32 >= 64$. At the heal, both locks have exactly $n\/2$ opponents and both step back. Chapter 9 shows this in the 50/50 partition: every block built during the cut is discarded on both sides. The design accepts conflicting locks *before* GST (slide 10). The point is that they cannot survive after it.
]

== 6.5 The Anchor: Where the Walk Starts

#formula-card[
*Anchor* #specref[F9.26]: the deepest locked block of the full viable tree, or $Phi\."fc_root"$ if no block of the viable tree is locked. Every Goldfish walk of a duty (proposal, vote, head for the FG) starts there.
]

Locks give the anchor, and votes give the walk from it (slide 18). Because the anchor is a *locked* block, the head extends every live lock that lies in the viable tree on the anchor's chain. A confirmed and locked block therefore stays under the head for the lock's lifetime, even if the next few slots have no votes.

== 6.6 The Block for the FG

At the action time $a_r$, the AC gives the FG the pair $("fg_confirmed", "head")$ #specref[F7.33]:
- `fg_confirmed` is the deepest block that the confirmation update *of slot $r R$*, run in the same tick, locked by the *fast* test, and that is in the full viable tree. Half of the committee or more voted for it. If there is none (for example, the update had no result, was vetoed, or only slow-locked), it is $bot$ and the validator does not attest this round;
- `head` is the head of the full viable tree with the current slot's votes.

The FG reads the height pair from $sigma["fg_confirmed"]$ (the target of the height the chain is in) and the finality pair from $sigma["head"]$ (the latest justification on the head's chain). Targets therefore come only from fast locks, which Chapter 8 uses for healing.

#caveat[
*One slot decides a round.* `fg_confirmed` comes from the update of slot $r R$ only, not from the deepest live fast lock. If that one slot fails the fast test, for any reason, no one attests in round $r$ and the FG loses a whole round. A partition of one slot is enough, and so is a block late enough that half the votes resolve after $t_(r R) + 2 Delta$. Participants count every vote that arrived, but support counts only early votes, so late votes act like votes against. In our simulator, a one-slot 50/50 cut at slot 48 (a round start) delayed finality by 8 slots. The same cut at slot 49 delayed it by 1 slot (Chapter 9).
]

#observed[
With 75% of validators asleep (Chapter 9), the awake 25% keep confirming and slow-lock every $k$ slots, but they never fast-lock, because $2 dot 16 < 64$. So `fg_confirmed` is $bot$ and *no one attests* while participation is that low. Finality stalls by design and resumes once half of the validators are back. This is the "guarantees from committees only" row of the table in Chapter 1.
]

#recap[
Each slot's confirmation update (at $t_s + 6 Delta$) walks from $F$ with early, non-equivocating votes. A non-vetoed result advances the confirmed record and writes one lock on the deepest block that passes the fast test ($>= n\/2$ of the committee) or the slow test ($k$ consecutive confirmations). Locks expire after $k$ slots and are moved back when $>= n\/2$ vote against them. The walk starts at the deepest locked block. The FG attests only to fast-locked blocks.
]
