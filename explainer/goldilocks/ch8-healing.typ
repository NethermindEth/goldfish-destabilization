#import "style.typ": *

= 8. Healing After GST

This chapter restates the healing argument of the design slides (slides 9–13 and 22–28). It is a design argument, not yet a written proof. Chapter 9 says how much of it our experiments exercised. Throughout, $L$ is the lock lifetime ($k$ slots) and $G$ is the time until the next honest proposal.

== 8.1 Before GST, Conflicting Locks Can Form

Before GST, honest nodes see different votes. Group 1 can lock $B$ while group 2 locks a conflicting $B'$, and each group walks from its own lock. Nothing prevents this, and Chapter 9 shows it happening in every partition we ran. The claim is only about what happens after GST.

== 8.2 Step 1: No New Conflicting Locks After GST

#formula-card[
Consider two conflicting locks, at least one of them formed after GST.
- *The newer lock is slow.* Its formation window ($k$ consecutive confirmations) overlaps the formation of the other lock. After GST, honest validators cannot confirm two conflicting blocks in the same slot: a confirmation needs a strict majority of the slot's voters, and every honest node sees the same votes. So the two windows cannot both complete.
- *The newer lock is fast.* At least $n\/2$ of the committee voted for it. They are opponents of every conflicting lock, so at the next unlocking every conflicting lock moves back, even one formed before GST.
]

#fig("healing.svg")[Bad locks drain within $2L$ (slide 13). Conflicting pre-GST locks expire by GST + $L$; locks formed across GST, which may not be followed by votes, expire by GST + $2L$; locks formed fully after GST are followed by every honest head.]

== 8.3 Step 2: Old Locks Drain, New Locks Are Followed

After GST, new locks never stay in conflict. Old locks can still be alive, though, and a lock formed partly from pre-GST confirmations (slide 11's "$C$, old window") may not be followed by the votes. In the slide's example, group 1 stays on $C$, held by its lock, while the Goldfish votes (5 against 3) take group 2 past $D$. Group 1 is free only when $C$ expires.

- Conflicting locks from before GST expire by GST + $L$.
- Locks formed across GST, which may not be followed, expire by GST + $2L$.
- A lock formed fully after GST is followed by everyone: every honest head extends it.

== 8.4 Step 3: The Next Honest Proposal Heals the AC

Once only post-GST locks remain, they are compatible and followed by everyone. View merge (§5.4) makes every honest voter vote for the next honest proposal $P$. That proposal is confirmed by all, and every available chain ends at it. Why wait for the old locks to drain, rather than heal right after GST? Slide 28 answers: an available chain never moves back to an ancestor of its tip, and an old lock on $D$ holds $x$'s head on $D$. A fresh proposal that no old tip extends is what reunites $x$ and $y$.

#formula-card[
*AC healing bound (slides 13, 27):* the AC is healed by GST $+ 2L + G$.
]

== 8.5 The FG Falls in Line

The FG needs its own argument, because old evidence from before GST (justifications, finality votes, records) can keep appearing after GST.

- *Fast locks make FG targets safe* (slide 22). The height pair of an attestation comes from `fg_confirmed`, a fast-locked block. After GST, a fast lock unlocks every conflicting lock and every honest head keeps it. So a target read from its state is never dropped later and cannot set up an FG reorg.
- *Heights rise in at most three attempts* (slide 25, our §4.2): one $J$ per height, and contests never go away.
- *From height $H + 1$ on, the FG follows the AC* (slide 26). Let $H$ be the highest height honest nodes reach shortly after GST, so pre-GST evidence stays at $H$ or below. Let $C^*$ be `fg_confirmed` of the first honest attestation at $H + 1$, a fast lock. If $h_max = H + 1$, an old $J$ is either below $C^*$ or contested by it. If $h_max >= H + 2$, an old $J$ is too low to be the root. New justifications name one entry per height, on $C^*$'s chain.

#formula-card[
*Full healing (slide 27):* call *reset* the first honest attestation at $H + 1$. From the reset on, the FG follows the AC; locks formed after the reset are followed by everyone; older locks expire by reset $+ 2L$; the next honest proposal heals. Healed by reset $+ 2L + G$.
]

#caveat[
These are claims of the design slides. The spec states the rules but does not prove them. In particular, step 1's "cannot confirm two conflicting blocks in the same slot after GST" relies on all honest nodes having the same *early* votes, which after GST holds by the $Delta$ bound. Step 2's drain needs the lock lifetime $L$ to be finite and fixed (no renewal of an unfollowed lock), which holds because only a confirmation update writes a lock, and a vetoed or conflicting update writes none.
]

#recap[
Conflicting locks may form before GST. After GST no new conflicting lock forms (slow: overlapping windows; fast: its $n\/2$ supporters unlock the rest). Old locks drain within $2L$, and the next honest proposal reunites every available chain: GST $+ 2L + G$. The FG follows because its targets come from fast locks and each height changes frame at most twice; full healing by reset $+ 2L + G$.
]
