#import "style.typ": *

= 3. The Finality Gadget: Heights, Targets, Timeouts

The FG of Goldilocks is close to the Simplex-style finality of the previous book, minus the stabilization fields. It works in *heights*. A height is entered by one block, its *target*. The chain leaves the height when a quorum justifies the target, or, after a delay, when a quorum of target votes and timeouts lets it move on without justification.

== 3.1 Attestations Are Pure Finality Votes

An attestation is #specref[§2.1]
$ a = (v, h, T, tau, h_f, T_f). $

- The *height pair* $(h, T, tau)$ is a vote at height $h >= 1$ for the block $T$ that brought the chain of `fg_confirmed` into height $h$. With $tau = "false"$ it is a *target vote*; with $tau = "true"$ it is a *timeout*.
- The *finality pair* $(h_f, T_f)$ is either empty or names a justification $T_f$ at a height $h_f < h$. It is a vote to finalize that justification.

The height pair is read from the chain state of `fg_confirmed` (a block the AC fast-locked), and the finality pair from the chain state of the head. There is no head vote and no round number in an attestation.

== 3.2 The Chain State of a Block

Every accepted block $B$ has an immutable chain state $sigma[B] = "state_transition"(sigma[B\."parent"], B)$ #specref[F5]:

#chapter-table(columns: (0.9fr, 2.4fr),
  [$L$, $s$], [the latest block and its slot],
  [$h$, $T_h$], [the current height and the block that brought the chain into it (the target)],
  [`target_participation`, `progress`], [one bit per validator: who sent a target vote for $(h, T_h)$; who sent a target vote *or a timeout* for it],
  [`pending_finality`], [at most $K_W$ pairs $(j, T)$: justifications on this chain that are not yet finalized (upstream $K_W = 4$)],
  [`finality_participation[j]`], [one bit per validator: whose finality pair names $(j, T)$ on this chain],
  [$J, h_j$ / $F, h_F$], [the latest justification and the latest finalization on this chain],
)

An attestation can be included in a block only if it is *valid against the parent's state*. Either it names the chain's own entry $(h, T_h)$, or it is a vote at a height below $h$ whose finality pair is one of the pending pairs. So an old vote can still be included for the sake of its finality pair.

== 3.3 Height Events

After processing the attestations of $B$, the state transition checks three events, in this order #specref[F5.24]:

#formula-card[
+ *Finalize.* If some pending $(j, T)$ has finality participation $>= q$, set $(F, h_F) <- (T, j)$ for the greatest such $j$, and drop the pending pairs with $j <= h_F$.
+ *Justify and advance.* If the target participation for $(h, T_h)$ is $>= q$: set $(J, h_j) <- (T_h, h)$, append $(h, T_h)$ to the pending list (keeping the newest $K_W$), and *advance*: $h <- h + 1$, $T_h <- B$, participation reset.
+ *Advance without justification.* Otherwise, if the progress participation (targets plus timeouts) is $>= q$ *and* $sigma\.s >= T_h\."slot" + delta_t$, advance the height without justifying. Upstream, $delta_t = R$ slots.
]

The block that carries the justifying attestations becomes the target of the next height. Rounds play no part in the state transition, which reads only heights.

#fig("heights.svg")[The honest steady state with $R = 8$, as reproduced by our simulator. Attestations are cast at $a_r$, in slot $r R + 1$, and included in the block of slot $r R + 2$. That block justifies the current target and becomes the next target. A target is finalized two rounds after it is proposed.]

#example[
$n = 64$, all honest, $R = 8$. In round 0 nothing is fast-locked yet, so no one attests. At $a_1$, `fg_confirmed` is block 8, whose state is at height 1 with target genesis, so all 64 validators attest $(1, "gen")$. Block 10 includes them: 64 $>= 43$ justifies genesis at height 1, and block 10 becomes the target of height 2. At $a_2$ everyone attests $(2, \#10)$ with finality pair $(1, "gen")$. Block 18 finalizes genesis, justifies \#10 and becomes target of height 3. At $a_3$ everyone attests $(3, \#18)$ with finality pair $(2, \#10)$, so block 26 finalizes \#10. The finalized tip trails the head by two rounds and a little: 16 slots for the target, 16 to 24 slots for the head. This is the sawtooth of the green line in the honest-run plot of Chapter 9.
]

== 3.4 The FG State of a Node

Besides the per-block chain states, the node keeps four caches #specref[§2.2, F3]:

- $Sigma\.F$: the accepted finalization. It moves to $sigma\.F$ of a new block only if that block extends the current $F$, is an ancestor of $Sigma\.J$, and *has a viable descendant* (Chapter 4);
- $(Sigma\.J, Sigma\.h_j)$: the lex-greatest $(h_j, "root")$ justification among accepted states that extend $Sigma\.F$;
- $Sigma\.h_max$: the greatest height of any accepted state;
- the attestation pool: every processed attestation, kept forever, one copy each. It serves *inclusion only*: a proposer includes every pooled attestation that is valid against its parent's state and not already on the parent's chain. No rule reads arrival times of attestations.

== 3.5 The Validator Client: Vote Once per Height per Chain

The anti-slashing record of a validator is $Lambda = ("target"[dot], "timeout"[dot], "lock"[dot], "sent")$ #specref[F4]: the first target sent at each height, whether a timeout was sent there, the target of the first finality pair at each height, and the contents already sent. This *finality lock* $Lambda\."lock"[h]$ is unrelated to the AC locks of Chapter 6.

#formula-card[
*Finality pair.* Attach $(h_j, J)$ from the head's state if $h_j > h_F$ and the record allows it: no different target at $h_j$, no timeout at $h_j$, no finality vote for a different block at $h_j$.

*Height pair* for the entry $(h_c, T_c)$ of `fg_confirmed`:
- already timed out at $h_c$ → timeout $(h_c, T_c, "true")$;
- finality-locked at $h_c$ (now or by this attestation): target if the lock is $T_c$, otherwise *no attestation*: wait out the height;
- no target yet at $h_c$, or the same one → target vote $(h_c, T_c, "false")$;
- a different target already sent at $h_c$ → timeout $(h_c, T_c, "true")$.

A target is only ever the first vote at a height, no entry is named twice, and a finality pair is attached only below the height pair.
]

So a validator votes once per height per chain. It votes again only if it moves to a chain with a different entry at that height, and then it sends a timeout for that entry. Timeouts let validators who voted for different targets at the same height (for example on two sides of a partition) still give a progress quorum to one chain, which advances the height after $delta_t$ slots without justifying anything.

#caveat[
Two features of the upstream EIP are not in the abstract FGSA model and not in our simulator. First, attestation committees: upstream, each validator attests in one committee slot per round; in the model, everyone attests at $a_r$. Second, inactivity: upstream, inactivity reduces a validator's *weight* in FG quorums (quadratically in its inactivity score) instead of its balance, which is how a quorum is regained after a long stall.
]

#recap[
Heights, not epochs. A block that sees $q$ target votes for the current target justifies it and becomes the next target; $q$ finality pairs finalize a pending justification; $q$ targets-plus-timeouts move on without justifying after $delta_t$. Honest steady state: one height per round, finality two rounds behind. The client signs at most one target per height and times out when it switches chains.
]
