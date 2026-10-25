#import "style.typ": *

= 2. System Model and Architecture

== 2.1 Validators, Quorums and Delivery

The spec fixes a set $V$ of $n$ validators, each of weight 1 #specref[§1.1]. The quorum threshold is $q = ceil(2n\/3)$. Two parameters bound delivery:

- $Delta$ bounds the delivery of blocks and AC messages (Goldfish votes);
- $Delta_F >= Delta$ bounds the delivery of attestations.

The bounds hold after the *global stabilization time* (GST), and only for nodes that are awake and honest. Before GST, messages can be delayed arbitrarily, which is how a partition is modelled.

#example[
Our experiments use $n = 64$, so $q = 43$ and "half of the committee" is $n\/2 = 32$. With $Delta = 1.5$ s a slot lasts 6 s, which matches the minimal preset of the earlier experiments: the old in-slot deadlines at 1.5 s, 3 s and 4.5 s are exactly $Delta$, $2 Delta$ and $3 Delta$.
]

== 2.2 Time: Public Times, Slots and Rounds

Time is continuous. The *public times* are the multiples of $Delta$, and a node runs one *tick* at each of them. A tick starts from the state as it was before its public time, and an object received exactly at a public time counts as received *after* that tick #specref[§1.6].

- Slot $s$ starts at $t_s = 4 Delta s$, so a slot spans four public times. Slot $s$ has one assigned proposer.
- Round $r$ contains the slots $r R, dots, r R + R - 1$. Its *action time* is $a_r = t_(r R) + 6 Delta$, the moment at which validators attest.
- Goldilocks requires $R >= max{2, ceil((6 Delta + Delta_F) \/ (4 Delta))}$, so an attestation sent at $a_r$ arrives before the next action time. The upstream preset uses $R = 8$.

#fig("slot-timeline.svg")[The public actions of slot $s$ #specref[§3.1]. The unlocking against slot-$s$ votes ($t_s + 5 Delta$) and the confirmation update of slot $s$ ($t_s + 6 Delta$) happen during slot $s + 1$, at its vote time and at its support cutoff. The action time $a_r$ of round $r$ is the confirmation update of slot $r R$.]

The table below collects the six public actions of slot $s$. We will meet each of them in Chapters 5 and 6.

#chapter-table(columns: (0.7fr, 2.3fr),
  [$t_s$], [*proposal*: the proposer builds on its head and includes all slot-$(s-1)$ votes it holds],
  [$t_s + Delta$], [*Goldfish vote* of slot $s$ (just before it: unlocking against slot-$(s-1)$ votes)],
  [$t_s + 2 Delta$], [*support cutoff*: only slot-$s$ votes resolved before this time count for confirmation],
  [$t_s + 3 Delta$], [*view freeze*: slot-$s$ votes received before this time feed the vote of slot $s+1$],
  [$t_s + 5 Delta$], [*unlocking* against slot-$s$ votes],
  [$t_s + 6 Delta$], [*confirmation update* of slot $s$: may advance the confirmed record and write one lock],
)

== 2.3 Awake, Asleep, Restart

A node is *awake* or *asleep* #specref[§1.1]. An asleep node receives nothing, runs no tick and has no duty. A message sent to it while it sleeps is delivered after it wakes, and the delivery bound counts from the later of the send time and the wake. A crash is a sleep. A node that wakes *restarts* before it does anything else, and it takes no vote-reading action until it is *joined* again (Chapter 7). This is the dynamic-availability model: the protocol must keep going with whatever fraction of validators is awake.

== 2.4 Blocks

A block $B$ has a slot, a parent, a proposer, a list of attestations (the FG payload) and an AC payload #specref[§1.2]. Its root is the digest of `(parent root, slot, attestations, AC payload)`. Ties between blocks ("deepest", "arg max") are broken by a fixed root order. Since the root is a digest, this order is effectively pseudo-random.

For Goldilocks the AC payload is `(votes, support_votes)` #specref[§3.1]. `votes` lists slot-$(s-1)$ Goldfish votes. `support_votes` is the subset of them that the proposer counted, meaning those whose head it already held at proposal time. The support list records the proposer's view; it is not a second set of votes.

== 2.5 The Three Parts of a Node

#fig("architecture.svg")[A node, its finality gadget and its available chain #specref[Figure 1]. The FG gives the AC the *FG frame* $Phi$. Once per round, the AC gives the FG a pair $("fg_confirmed", "head")$. The three tips lie on one chain.]

- The *finality gadget* owns the block tree $Sigma\.T$, the immutable chain state $sigma[B]$ of every accepted block, the finality caches $F, J, h_j, h_max$ and the attestation pool. It decides which blocks are accepted. A block enters the tree only if it extends $F$, and nothing ever removes it.
- The *available chain* owns its own state $A$: Goldfish votes, timestamps, saved confirmations, locks and the confirmed record. It has *no block store*. It sees blocks only through the frame $Phi$, which the FG derives from its state when asked:
  $ Phi = "fg_to_ac"(Sigma) = ("tree", "fc_root", "viable_heads"). $
- The *node* keeps the clock and both states and calls the parts. In each tick it runs the AC schedule first, then the proposal at $t_s$, then the FG action at $a_r$.

#formula-card[
The AC must satisfy four requirements #specref[§1.5]:
+ every head of a duty (proposal parent, vote head, the head given to the FG) extends $Phi\."fc_root"$; a head whose walk starts in the viable tree is a viable head;
+ $"fg_confirmed"$, if not $bot$, is in the viable tree, and the returned head extends it;
+ the head extends $Phi\."fc_root"$; the confirmed tip extends $Phi\.F$ and is an ancestor of the head;
+ the parent of a proposal is a head of the AC at that time.
So $F$ #sym.prec.eq confirmed tip #sym.prec.eq head at all times.
]

Our simulator checks requirement 3 for every node at every slot, and requirement 2 at every action time (Chapter 9). No run violated them.

#recap[
Time is ticks at multiples of $Delta$; a slot is $4 Delta$ long and its actions spill into the next slot; a round of $R$ slots has one attestation time $a_r$. A node is an FG (owns blocks and finality) plus an AC (owns votes and locks). They talk through the frame $Phi$ (FG #sym.arrow AC) and the pair $("fg_confirmed", "head")$ (AC #sym.arrow FG).
]
