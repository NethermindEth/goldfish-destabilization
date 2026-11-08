// Textbook edition: progressive, self-contained course on Decoupled Consensus without implementation jargon.
#import "helpers.typ": *
#import "overview-style.typ": *

= 1. The Availability–Finality Dilemma and Protocol Architecture

In proof-of-stake blockchain design, a consensus protocol must serve two competing goals. First, it should produce blocks at short, regular intervals and remain *dynamically available*—continuing to extend the chain even if a large fraction of validators temporarily goes offline, provided the online validators can communicate quickly. Second, it should provide *accountable finality*—irrevocably committing a growing prefix of the chain through a supermajority of all staked validators, so that no two honest nodes ever finalize conflicting histories even if the network partitions for an arbitrarily long period.

This monograph develops *Decoupled Consensus* from first principles. Rather than presenting rules in isolation, we construct the protocol layer by layer: each section states a concrete distributed-systems problem, introduces the design idea that resolves it, defines the exact rule used by a node, and traces its behavior on numerical examples and failure scenarios.

Where the protocol rules define what a single node computes locally, but a formal multi-node safety or liveness proof for that rule is still an open research problem, we state explicitly that *the multi-node argument is not yet established*. To keep the core tree-voting mechanics clear, all main-text examples operate on trees of consensus blocks and assume validators have equal stake weights unless noted otherwise.

== 1.1 Why Coupling Head Selection and Finality Creates a Bottleneck

#block(breakable: false)[
#problem[
In a proof-of-stake network with hundreds of thousands of validators, we want new blocks to be proposed and voted on every few seconds. However, collecting, broadcasting, and aggregating cryptographic signatures from the entire validator set takes considerably longer than a single block interval. If every block requires a full-validator-set vote on its critical path, block times must be slow; conversely, if a single vote message must simultaneously steer fast block production and lock in slow full-set finality, neither mechanism can be tuned or analyzed independently.
]

#idea[
Decouple the single voting stream into two separate voting streams operating on different clocks and electorates. Every *slot* (a single block-production interval), a small, randomly sampled *committee* of 512 seats casts fast votes to steer and confirm the *available chain*. Over a longer *round* spanning multiple slots, every active validator in the *full validator set* casts exactly one finality attestation to drive *stabilization* and *finality*.
]
]

In classical epoch-coupled protocols such as Ethereum's Gasper, both responsibilities are bundled into a single attestation cast once per 32-slot epoch: each attestation contains a latest-message head vote (consumed by LMD-GHOST to pick the tip of the chain) and a source-to-target checkpoint link (consumed by Casper FFG to justify and finalize epoch boundary blocks). Because the same message carries both signals on a shared epoch schedule, anomalies in checkpoint justification directly perturb head selection, and fast slot-level confirmations must be inferred from an accumulating pool of epoch votes.

As motivated in Francesco D'Amato's #link("https://ethresear.ch/t/unblocking-faster-finality-with-decoupled-consensus/24527")[design post], decoupling assigns fast chain growth and full-set finality to distinct sub-protocols:
- *Goldfish* (Chapters 3–4) governs the fast available chain using the 512-seat slot committees.
- *The Stabilization Gadget* (Chapters 5–6) bridges the two validator populations so that full-set head votes anchor the available chain and veto contested branches.
- *Simplex Finality* (Chapters 7–8) advances justified and finalized checkpoints using full-set quorum certificates organized by logical finality *heights* rather than wall-clock epochs.

== 1.2 Head Selection, Available Confirmation, and Finality

Separating the voting streams does not eliminate the fundamental theorem of consensus under network partitions (the availability–finality dilemma). Suppose a network splits into two isolated halves, Side A and Side B, with no messages crossing between them. A node on Side A cannot distinguish whether the validators on Side B have crashed or are actively extending a competing branch on the other side of a partition. Any chain-progression rule that continues to advance on Side A during this split will also continue to advance on Side B, producing two incompatible branches.

To handle both normal synchronous operation and asynchronous partitions, every node maintains three distinct outputs along its block tree, ordered from the most speculative tip to the most conservative prefix:

#enum(
  [*The Head: Where should a node build or vote right now?*
  At every slot, a block proposer needs a single parent block to extend, and committee voters need a single tip to endorse. A head-selection rule must therefore always return a leaf block—even if network participation has dropped to a handful of votes, or if a newly proposed block in the current slot has received zero votes so far. Because the head must respond immediately to the latest proposal, it is *not* guaranteed to be permanent; a late block or a split committee can cause the head to reorganize from one slot to the next.],

  [*The Available-Confirmed Prefix: Which prefix has strong committee support under synchrony?*
  External users and downstream protocol layers cannot rely on an unconfirmed head that might reorganize in the next slot, nor do they always want to wait several rounds for full-validator-set finality. A *confirmation rule* identifies the deepest ancestor of the available chain that has been positively endorsed by a quorum of timely committee votes. Unlike the head, the confirmed prefix refuses to advance into a new block until enough committee votes have arrived on time. Under synchronous network delivery and honest committee majorities, a confirmed block will not be overturned; during a 50/50 network partition, however, isolated halves may confirm conflicting available prefixes.],

  [*The Finalized Prefix: Which prefix is irrevocably committed by the full validator set?*
  A block is *finalized* only when a supermajority of at least two thirds of all active validator stake has completed a two-stage cryptographic commitment to it. Because two quorums of size at least $2\/3$ of the total stake must overlap in at least $1\/3$ of the stake, two conflicting branches can never both be finalized unless at least $1\/3$ of all validator stake violates the protocol's slashing rules. During a 50/50 partition, finality safely halts rather than picking a side.]
)

== 1.3 Connecting the Layers: Stabilization and Safe Confirmation

If the 512-seat slot committees and the full validator set operated in complete isolation, two coordination failures could occur:
1. *Downward drift:* A transient network glitch or an unlucky committee sample in a single slot could cause the available chain's head to jump onto a minority fork, pulling subsequent proposals away from the branch favoured by the full validator set.
2. *Upward premature locking:* A small committee on one side of a brief network split might confirm a block $C$ while a large fraction of the full validator set is voting for a conflicting branch $X$. If validators immediately locked their full-set finality votes onto $C$, they could get stuck on incompatible finality targets.

The protocol therefore places a *stabilization layer* (Chapters 5–6) between Goldfish and Simplex finality, as illustrated in Diagram 1:
- *Downward anchoring (the stable root):* The head votes carried inside full-set finality attestations are used to compute an anchor block called the *stable root*. The Goldfish head walk is required to start from this stable root rather than from the older finalized root, keeping slot-by-slot block production aligned with the full validator set's direction.
- *Upward filtering (the safe-confirmed head):* Before a validator casts a finality vote for an available-confirmed block, it filters the confirmed chain against full-set opposition. Walking backward from the available-confirmed tip until no conflicting branch holds at least $1\/3$ of the active full-set head weight yields the *safe-confirmed head*, which serves as the input gate for Simplex finality voting.

#mechanism-figure("architecture.svg")[Two voting streams and three consensus layers. Each slot, a 512-seat committee drives Goldfish head selection and available confirmation (green). Each round, the full validator set emits attestations carrying both a live head for stabilization (purple) and frozen finality commitments (blue). Stabilization anchors the Goldfish walk from below and filters available confirmations into the safe-confirmed prefix consumed by finality voting.]

== 1.4 Network Timing Models: Synchrony and Partial Synchrony

Because the protocol combines an available chain with a BFT finality gadget, its guarantees are analyzed under two standard distributed-systems timing models:

- *Synchrony:* Every message broadcast by an honest validator arrives at all other honest validators within a known maximum network delay tailored to each sub-slot deadline. The safety and liveness of Goldfish available confirmations—as well as the round-boundary head-alignment guarantees of the stabilization layer—rely on synchronous message delivery within specific sub-slot windows.
- *Partial synchrony:* For an arbitrarily long initial period (before an unknown *Global Stabilization Time*, or GST), the network may drop, reorder, or arbitrarily delay messages, partitioning honest nodes into disjoint views. After GST, message delivery returns to within the synchronous delay bounds. Under partial synchrony, Simplex finality guarantees *safety at all times* (even before GST, provided fewer than $1\/3$ of stake is Byzantine) and aims to recover *liveness after GST*.

#block(breakable: false)[
#caveat[
*Post-GST recovery is a state-reconciliation problem, not a magic reset.* Saying "the network has healed at GST" only means that newly sent messages now arrive on time. Honest nodes may emerge from the pre-GST partition holding incompatible confirmed chains, different finality heights, and restrictive signing histories. A complete liveness proof under partial synchrony must show how the protocol's rules guide nodes out of those diverged local states back to a single finalizing chain.
]

#recap[
Decoupled consensus separates fast block production from full-set finality by running two voting streams on different schedules: a 512-seat committee every slot (Goldfish) and the full validator set once per round (Stabilization + Simplex). Every node tracks a live *head* (for building/voting now), an *available-confirmed prefix* (backed by timely committee majorities under synchrony), a *safe-confirmed prefix* (filtered against full-set opposition), and a *finalized prefix* (backed by $>= 2\/3$ of total validator stake).
]
]

#v(1.2em)
= 2. System Model: Blocks, Time Units, and Attestations

Before examining how a node selects a head or confirms a block, we define the data structures stored by each validator node, the three units of time in the protocol, and the contents of the two attestation messages.

== 2.1 The Block Tree and Subtree Vote Support

Each validator maintains a local tree of validated blocks rooted at genesis. Given two blocks $A$ and $B$ in this tree:
- Block $A$ is an *ancestor* of $B$ (and $B$ is a *descendant* of $A$) if $A$ lies on the unique path of parent links from $B$ back to genesis. Every block is trivially an ancestor and a descendant of itself; we say *strict ancestor* or *strict descendant* when $A != B$.
- The *subtree* of a block $B$ consists of $B$ itself together with all descendants of $B$ (all blocks reachable by following parent-to-child links forward from $B$).
- Two blocks are *compatible* if one is an ancestor of the other (so they lie on the same linear chain). They *conflict* if neither is an ancestor of the other (meaning they lie on diverging branches of a fork).

Whenever any layer of the protocol scores a candidate block $B$ using a set of head votes, it applies the principle of *subtree support*: a vote that names block $C$ on the chain $F -> A -> B -> C$ endorses the entire history leading up to $C$. Therefore, a vote for $C$ counts toward the subtree support of $C$, of $B$, of $A$, and of $F$. While the tree walk proceeds *forward* from parent to child, vote weight propagates *backward* from descendants to ancestors.

== 2.2 Three Distinct Units of Time: Slots, Rounds, and Heights

A recurring source of confusion in consensus protocols is the conflation of wall-clock time with finality progress. Decoupled consensus strictly separates three counters:

#enum(
  [*Slot ($s$):* The basic wall-clock interval of block production (for example, $L = 6$ or $12$ seconds). Each slot has one designated block proposer and one randomly sampled 512-seat available committee. Within a slot, local actions occur at four fixed fractional deadlines:
  - $0%$ of slot $s$: slot start and block proposal broadcast;
  - $25%$ of slot $s$: validator attestation deadline;
  - $50%$ of slot $s$: available-confirmation snapshot cutoff;
  - $75%$ of slot $s$: wire-vote intake cutoff.],

  [*Round ($r$):* A fixed, contiguous sequence of $R$ wall-clock slots (for example, $R = 8$ slots per round). Each active validator in the full validator set is assigned to broadcast its finality attestation during one slot of round $r$. Like slots, rounds advance purely by the wall clock whether or not any blocks are proposed or finalized.],

  [*Height ($h$):* A logical finality-attempt counter stored *inside the state of a chain branch*. A height is neither a slot number, nor a round number, nor the number of blocks from genesis. Instead, height $h$ represents the $h$-th sequential attempt by the chain to justify a checkpoint. If the network partitions and no quorum of finality votes is included on-chain, slots and rounds keep incrementing while the chain's height $h$ remains unchanged for as many rounds as it takes to collect a quorum. Conversely, two diverging branches of the block tree can be at different heights at the exact same wall-clock slot.]
)

== 2.3 Two Signed Attestation Families and Their Weight Units

Every vote in the protocol belongs to one of two signed message families, summarized in the table below:

#chapter-table(columns: (0.85fr, 1.45fr, 1.4fr),
  table.header([*Message family*], [*Electorate and schedule*], [*Information supplied*]),
  [Available attestation], [512-seat sampled committee, cast every slot at $25%$], [A head vote for Goldfish head selection and available confirmation],
  [Finality attestation], [Every active validator in the full set, cast once per round at $25%$ of the validator's assigned slot], [A live head vote for stabilization, plus frozen finality fields (target/timeout vote at height $h$ and a finality commitment)]
)

*Seats versus stake weight ($W$).* Because the two message families draw from different electorates, they use different units of weight:
- *Committee seats (out of 512):* For each slot, a committee of 512 seats is sampled with replacement in proportion to validators' active stake. A large validator selected for three seats in slot $s$ broadcasts a single signed available attestation, and that message carries a weight of 3 seats in Goldfish.
- *Stake weight ($W$):* Full-set stabilization and Simplex finality operate directly over the active validator set without committee sampling. Each validator's vote is weighted by its stake, and full-set quorums are measured against the total active stake $W$ (for example, $q = ceil(2 W \/ 3)$). When our worked examples say "43 out of 64 validators," we are considering 64 validators of equal stake ($W = 64$, so $ceil(2 times 64 \/ 3) = 43$).

*Why a finality attestation selects its fields at two different times.* Look closely at the second row of the table above: a single finality attestation carries both a *live head* (for stabilization) and *frozen finality fields* (for Simplex). If all validators broadcast their finality attestations at $25%$ of the first slot of a round, the network would suffer a massive once-per-round traffic spike. To smooth bandwidth across the $R$ slots of a round while still ensuring that all validators evaluate the same finality decision, the protocol splits decision time from broadcast time:
1. At $25%$ of the *first slot* of round $r$, *every* validator inspects its local state and freezes its finality fields for round $r$.
2. Later, at $25%$ of the specific slot $s in r$ when validator $v$ is scheduled to broadcast, $v$ queries its current head to fill in the attestation's live head field, attaches the finality fields it froze at the start of the round, signs the combined message, and broadcasts it.

== 2.4 Pedagogical Scaffolding: Starting from a Fixed Finalized Root $F$

To build the protocol without circular dependencies, Chapters 3 and 4 isolate the available chain by making two temporary simplifying assumptions:
1. We assume all nodes already agree on a fixed, trusted *finalized root* $F$, and start every tree walk at $F$.
2. We assume every accepted block descending from $F$ is eligible to be visited by the tree walk.

Once Goldfish head selection (Chapter 3) and available confirmation (Chapter 4) are completely clear under this fixed root $F$, Chapters 5 and 6 will replace the starting root of the head walk with the stabilization layer's *stable root*, and Chapters 7 and 8 will show how Simplex finality advances $F$ and prunes stale branches by height.

#v(1.2em)
= 3. The Available Chain: Goldfish Head Selection

We now construct the first layer of the protocol: how a node uses the 512-seat slot committees' available attestations to choose its current chain tip (the *head*), and how honest voters stay aligned from one slot to the next.

== 3.1 Why One-Slot Vote Expiration Replaces LMD-GHOST

#block(breakable: false)[
#problem[
In a Latest-Message-Driven GHOST (LMD-GHOST) fork choice, each validator's most recent head vote remains active in the block tree indefinitely until that specific validator casts a newer vote. When small committees rotate every slot, a validator who votes in slot $s - 10$ may not be sampled again for many slots, so its old vote continues to weigh on the tree alongside fresh votes. An adversary who controls committee members across several past slots can withhold their votes and release them all at once during a later slot with low honest participation, overpowering the current committee's honest majority with stale weight.
]

#idea[
Replace persistent latest-message weight with *one-slot vote expiration*. When a node runs head selection during slot $s$, it scores candidate blocks using *only* the available attestations cast in the immediately preceding slot $s - 1$. Votes from slot $s - 2$ and earlier expire completely as head-selection weight upon entering slot $s$.
]
]

Expiring old votes after a single slot means that an adversary cannot stockpile committee weight across multiple slots: any vote cast in slot $s - 2$ or earlier has zero weight when choosing a head in slot $s$. Note that expiring a vote's scoring weight does *not* delete older blocks from the block tree—blocks remain stored permanently, and fresh votes cast in slot $s - 1$ for a leaf block near the tip automatically credit subtree support to all of its older ancestors back to $F$.

== 3.2 The Majority-Gated Subtree Walk and the Current-Slot Exception

How does a node use the available attestations from slot $s - 1$ to walk down the block tree from $F$ during slot $s$? Let us first define the electorate and scoring rule assuming no validator equivocated in slot $s - 1$ (equivocations are added in Section 3.4).

*The slot-$(s-1)$ electorate ($m$) and subtree score.* Suppose the current wall-clock slot is $s$. A node gathers all valid available attestations it has accepted that were *cast for slot $s - 1$*, weighted by the number of seats each signer holds in the slot-$(s-1)$ committee. Let $m$ denote the total number of committee seats represented by these accepted slot-$(s-1)$ votes. For any block $B$ in the tree, its *available score* in slot $s$, denoted $"score"_(s-1)(B)$, is the number of seats among those $m$ votes that name $B$ or any descendant of $B$.

*The majority-gated tree walk.* Starting at root $F$, the node steps down the tree from parent to child. At the current block $A$, it examines $A$'s direct children. For any child $B$ that was proposed in a *prior* slot (slot $s - 1$ or earlier), the walk may step from $A$ into $B$ if and only if $B$'s subtree support is a *strict majority* of the entire slot-$(s-1)$ participating electorate $m$:

#formula-card[$ "score"_(s-1)(B) > m / 2 $]

If a child $B$ satisfies this strict majority gate, the walk moves to $B$ and repeats the test among $B$'s children. Because two sibling children have disjoint subtrees, at most one prior-slot child can have strictly more than $m\/2$ seats. When no child of the current block passes the gate, the walk stops and returns the current block as the selected head.

#rule-box("Crucial invariant: One vote slot, one fixed denominator m across all depths")[
  During a single evaluation of the head walk in slot $s$, *every* prior-slot block $B$—regardless of which historical slot $B$ was originally proposed in, and regardless of how deep the walk has descended into the tree—is tested against the *exact same electorate* of slot-$(s-1)$ votes and the *exact same denominator $m$*. Moving from parent $A$ to child $B$ does *not* shrink the denominator $m$ to $A$'s support.
]

#example[
  *Walking the tree in slot 12 using slot-11 votes.* Suppose the current slot is $s = 12$. A node has accepted available attestations from slot 11 representing $m = 100$ of the 512 seats in the slot-11 committee. (Thus, to pass the majority gate, any prior-slot child must have a subtree score strictly greater than $100\/2 = 50$.)

  Suppose the accepted block tree above $F$ (proposed in slot 6) contains block $A$ (proposed in slot 7), which branches into child $B$ (slot 8, with child $C$ from slot 10) and sibling child $D$ (slot 9). No block was proposed in slot 11, so the slot-11 voters attested to existing blocks:
  - 40 seats cast slot-11 votes naming $C$;
  - 25 seats cast slot-11 votes naming $B$;
  - 35 seats cast slot-11 votes naming $D$.

  Notice that the blocks were proposed in slots 6, 7, 8, 9, and 10, but *all 100 counted votes were cast in slot 11*.
]

#mechanism-figure("goldfish-slot-walk.svg")[An ordinary Goldfish majority walk in slot 12. Tree edges point forward from parent to child, while slot-11 vote support propagates backward from named blocks to their ancestors. Blue labels show when each block was proposed; green labels show each block's subtree support out of the $m = 100$ participating slot-11 seats.]

The table below traces the node's step-by-step decisions at each vertex of Diagram 2:

#chapter-table(columns: (0.8fr, 1.35fr, 1.15fr, 1.4fr),
  table.header([*Current block*], [*Child $B$ being tested*], [*Subtree support $"score"_(11)(B)$*], [*Majority gate ($> 50$ of $m = 100$)*]),
  [At $F$], [$A$ (subtree $\{A, B, C, D\}$)], [$40 + 25 + 35 = 100$], [$100 > 50$: step into $A$],
  [At $A$], [$B$ (subtree $\{B, C\}$)], [$40 + 25 = 65$], [$65 > 50$: step into $B$],
  [At $A$], [$D$ (subtree $\{D\}$)], [$35$], [$35 <= 50$: reject $D$],
  [At $B$], [$C$ (subtree $\{C\}$)], [$40$], [$40 <= 50$: stop at $B$]
)

Two lessons from this example are fundamental:
1. *Why the walk stops at $B$ instead of continuing to $C$:* The 25 votes that named $B$ directly helped the walk step from $A$ into $B$ (giving $B$'s subtree $40 + 25 = 65 > 50$). Once the walk is standing at $B$, however, a vote naming $B$ itself does not express a preference for any child of $B$. Moreover, the threshold required to enter $C$ remains half of *all participating slot-11 seats* ($m\/2 = 50$), not half of $B$'s 65 seats. Because $C$ has only $40 <= 50$, the walk stops at $B$.
2. *Why slot-10 votes for $C$ do not rescue $C$ in slot 12:* Even if $C$ had received 400 committee votes back in slot 10 when it was first proposed, those slot-10 votes expired upon entering slot 12. In slot 12, $C$'s score is 40, not 440. Conversely, block $A$ (from slot 7) needed no voter to name $A$ directly in slot 11: the 100 slot-11 votes naming $A$'s descendants ($B$, $C$, and $D$) automatically gave $A$ a subtree score of 100.

*The current-slot proposal exception.* What happens when the designated proposer for slot $s = 12$ broadcasts a brand-new block $P$ at $0%$ of slot 12 extending parent $B$, and the slot-12 committee members run head selection at $25%$ of slot 12 to decide what to vote for? Because $P$ was just proposed in slot 12, no voter in slot 11 could possibly have voted for $P$, so $"score"_(11)(P) = 0$. If the walk applied the strict majority gate $"score"_(11)(P) > m\/2$ to $P$, no newly proposed block could ever be selected as the head!

Therefore, at an ordinary (non-round-start) slot $s$, the protocol grants a *current-slot proposal exception*: once the majority-gated walk using slot-$(s-1)$ votes reaches $P$'s parent $B$, a child $P$ proposed in the *current* slot $s$ automatically passes the gate without requiring prior-slot votes. In Diagram 2, if a slot-12 block $P$ extends $B$, the walk reaches $B$ via the slot-11 scores ($100 > 50$ at $A$, $65 > 50$ at $B$) and then steps into $P$, allowing the slot-12 committee to vote for $P$. (Note that if $P$ had instead been built on $C$ or $D$, the walk would never reach $P$'s parent in the first place, so $P$ would not be reached.)

== 3.3 View Merge: Aligning Honest Voters Across Slots

#block(breakable: false)[
#problem[
Expiring old votes after one slot stops historical weight from accumulating, but it does not guarantee that two honest nodes see the *same* set of slot-$(s-1)$ votes. Suppose 100 seats vote in slot $s - 1$, and an adversary or network delay causes Alice to receive 60 votes for $A$ and 40 for $B$ before her voting deadline, while Bob receives 40 for $A$ and 60 for $B$. Both count only fresh slot-$(s-1)$ votes, yet they select different heads.
]

#idea[
Combine one-slot vote expiration with *proposer view merge*. Honest receivers stop admitting ordinary gossip votes into their live scoring view after a wire-intake cutoff at $75%$ of slot $s - 1$, while the next slot's proposer continues collecting votes until $0%$ of slot $s$ and bundles them into its block proposal. When receivers process the slot-$s$ proposal before voting at $25%$, they merge (take the union of) the proposer's carried votes with their own $75%$ frozen view.
]
]

To understand how the sub-slot deadlines work together, let $Delta = 25%$ of a slot denote the maximum network propagation delay under synchrony. A slot of duration $4 Delta$ is divided into four quarter-slot phases ($0%, 25%, 50%, 75%$), as shown in Diagram 3:
1. *At $25%$ ($1 Delta$) of slot $s - 1$ (the voting deadline):* Honest members of the slot-$(s-1)$ committee have received the slot-$(s-1)$ block proposal (broadcast at $0%$) and broadcast their available attestations.
2. *By $50%$ ($2 Delta$) of slot $s - 1$:* Because every honest voter broadcast at $25%$ and synchronous delay is at most $Delta = 25%$, *every honest vote has arrived at every honest node by $50%$*. (We will use this $50%$ mark in Chapter 4 as the confirmation snapshot deadline.)
3. *At $75%$ ($3 Delta$) of slot $s - 1$ (the wire-intake cutoff):* Receivers freeze their ordinary wire-vote intake for head selection. Under synchronous delivery ($Delta = 25%$), any vote—even from a late adversarial sender—that entered *any* honest receiver's view before the $75%$ cutoff is guaranteed to reach the slot-$s$ proposer before $0%$ ($4 Delta$) of slot $s$.
4. *At $0%$ ($4 Delta$) of slot $s$ (the proposal deadline):* An *honest* proposer for slot $s$ has collected a superset of every honest receiver's $75%$ view. It runs the head walk on this combined view, builds block $P$ extending the selected head, and bundles all supporting slot-$(s-1)$ available attestations into $P$.
5. *Between $0%$ and $25%$ of slot $s$:* When honest receivers receive block $P$ before their $25%$ voting deadline, they merge (take the set union of) the slot-$(s-1)$ votes carried inside $P$ with their own $75%$ view. Consequently, when the slot-$s$ proposer is honest, every honest validator evaluates the head walk at $25%$ of slot $s$ on the exact same merged view and votes for $P$.

#mechanism-figure("expiry-merge.svg")[Vote expiration and proposer view merge solve complementary problems: expiration discards votes from slot $s - 2$ and earlier, while the $75% -> 0% -> 25%$ view-merge pipeline ensures that an honest slot-$s$ proposer relays all timely slot-$(s-1)$ votes to receivers before the next committee votes at $25%$.]

*What if the slot-$s$ proposer is adversarial and omits votes from its block?*
Suppose the proposer for slot $s$ is Byzantine and either fails to propose a block, equivocates, or deliberately omits some slot-$(s-1)$ votes from its block. Two distinct cases arise:
- *An adversarial proposer cannot erase votes that already reached honest receivers by $75%$:* Because each honest receiver *merges* the block's votes with its own local $75%$ view, omitting a vote from the block does not delete it from any receiver that already heard it over gossip before $75%$. In particular, if the *previous* slot $s - 1$ had an honest proposer, all honest slot-$(s-1)$ voters already broadcast their votes for $B_(s-1)$ at $25%$ of slot $s - 1$, and all those votes reached every honest node by $50%$ (well before $75%$). Thus, even if the slot-$s$ proposer is adversarial, every honest receiver in slot $s$ already holds a strict majority for $B_(s-1)$ in its own $75%$ view and will continue to select $B_(s-1)$ (or a descendant of it)!
- *An adversarial proposer CAN desynchronize nodes on unconfirmed tips:* If the slot-$(s-1)$ committee was split—or if an adversary broadcast straggler votes right around the $75%$ cutoff of slot $s - 1$ so that Alice received them at $74%$ and Bob received them at $76%$—then an honest slot-$s$ proposer would have relayed those stragglers to Bob at $0%$, synchronizing Alice and Bob. An *adversarial* slot-$s$ proposer, however, can refuse to relay them, leaving Alice and Bob with *different* views at $25%$ of slot $s$. Synchronizing honest nodes again will then wait for the next slot that has an honest proposer.

== 3.4 Handling Equivocations in the Head Walk

What if a Byzantine validator on the slot-$(s-1)$ committee *equivocates*—signing and broadcasting two different available attestations in the same slot (for instance, one voting for branch $A$ and another voting for branch $B$)?

If a node simply deleted an equivocator's seats from both the numerator and denominator as soon as it heard the second message, an adversary who revealed an equivocation to half the network before the deadline and to the other half after the deadline could manipulate the relative threshold $m\/2$. In the ordinary Goldfish head walk, the protocol instead gives a known equivocator's seats *generic viability credit*: once a validator is known to have equivocated in slot $s - 1$, its seats in $m$ are added to the score of *every* candidate child being tested in the head walk.

#example[
  *Generic equivocation credit in the head walk.* Suppose $m = 100$ seats from slot $s - 1$ have voted: 45 honest seats support child $A$, 45 honest seats support sibling child $B$, and 10 seats belong to a known equivocator who signed votes for both $A$ and $B$.
  
  The strict majority threshold is $m\/2 = 50$. Because the head walk grants the 10 equivocating seats as generic credit to each candidate, both $A$ and $B$ receive a head-walk score of $45 + 10 = 55 > 50$. Both pass the majority gate, and the head walk uses a deterministic tie-breaker (such as block hash ordering) to pick one leaf tip.
]

#block(breakable: false)[
#caveat[
*Open theoretical rationale.* While the protocol rules add known equivocators' seats to every candidate's score during the head walk, *the formal proof explaining why generic viability credit is preferable to exclusion in head selection is not yet established* (and as we will see in Section 4.2, traditional Goldfish confirmation proofs assume equivocators are excluded rather than credited).
]

#recap[
In slot $s$, the Goldfish head walk scores blocks using only available attestations cast in slot $s - 1$. Starting from the root, it steps into a prior-slot child $B$ only when $B$'s subtree support strictly exceeds half of all participating slot-$(s-1)$ seats ($"score"_(s-1)(B) > m\/2$), and may then step into a current-slot proposal $P$. View merge ($75%$ receiver cutoff + $0%$ proposer relay) aligns honest views whenever the proposer is honest.
]
]

#v(1.2em)
= 4. Confirming Prefixes on the Available Chain

In Chapter 3, we saw how the Goldfish head walk selects a single leaf tip of the block tree in every slot so proposers know where to build and committee members know where to vote. In this chapter, we introduce *confirmation*—explaining first what a confirmation rule is, what goal it serves in Goldfish and in the broader decoupled protocol, why its vote snapshot is frozen at $50%$ rather than $75%$, and how its fast ($3\/4$) and delayed ($> 1\/2$) rules work.

== 4.1 What Confirmation Is, Its Goal in Goldfish, and Why Votes Are Frozen at $50%$

*What is "confirmation" in an available-chain protocol?*
In any available-chain consensus protocol (such as longest-chain, LMD-GHOST, or Goldfish), the *head* is the very tip of the canonical chain at a given moment. Because the head must always extend to a leaf block—even stepping into a brand-new current-slot proposal that has received zero votes so far (Section 3.2), or breaking ties when an adversarial proposer desynchronizes views (Section 3.3)—the tip of the chain is inherently speculative. A block that is the head in slot $s$ can be orphaned in slot $s + 1$ if its proposer was late or equivocated.

A *confirmation rule* is a separate algorithm run by a node on its local view that outputs a conservative prefix of the block tree—called the *confirmed prefix* (with tip the *confirmed head*)—whose formal goal under synchronous message delivery and an honest committee majority ($< 1\/2$ adversarial seats) is *permanence (no reorgs)*:
- *Permanence goal:* Once a block $B$ enters an honest node's confirmed prefix at time $t$, block $B$ should remain an ancestor of the canonical head (and of every honest node's confirmed prefix) at all future times $t' >= t$, even if future proposers are adversarial!

In Decoupled Consensus, this confirmed prefix serves two essential purposes:
1. *Fast synchronous settlement for external users:* Full-validator-set finality (Chapters 7–8) requires collecting votes from at least $2\/3$ of all staked validators across multiple multi-slot rounds. Confirmation gives users a fast guarantee (within the same slot or the next slot) that a block is permanently part of the available chain as long as the network remains synchronous.
2. *Protecting the Stabilization and Finality layers from tip reorgs:* In a decoupled ("ebb-and-flow") architecture, the slow full-validator-set finality gadget must *only* lock finality votes onto blocks that have *already been confirmed* by Goldfish. If validators locked finality votes onto the unconfirmed raw head, a routine 1-slot head reorg at the tip of Goldfish could cause honest validators to commit to an orphaned fork.

*Why freeze the confirmation snapshot at $50%$ ($2 Delta$) instead of $75%$ ($3 Delta$)?*
Recall the four-phase slot timeline ($Delta = 25%$ maximum network delay) from Section 3.3:
- At $0%$ ($0 Delta$), the slot-$s$ block is proposed.
- At $25%$ ($1 Delta$), honest slot-$s$ committee members broadcast their available votes.
- By $50%$ ($2 Delta$), because maximum network delay is $Delta = 25%$, *every vote cast by an honest committee member at $25%$ has arrived at every honest node*.
- At $75%$ ($3 Delta$), honest nodes close their wire-vote intake for head selection.

Why does a node take its confirmation snapshot at *$50%$ ($2 Delta$)* rather than waiting until the *$75%$ ($3 Delta$)* head-selection freeze? Because of the *one-$Delta$ propagation buffer between $50%$ and $75%$*!
- Any vote that an honest node observes at $50%$ ($2 Delta$)—and therefore relies upon to confirm a block $B$—is guaranteed under synchrony (delay $<= 25%$) to finish propagating across the network and reach *every other honest validator* before they freeze their head-selection views at $75%$ ($3 Delta$).
- Consequently, every vote counted toward confirming $B$ at $50%$ is guaranteed to be present in *every* honest validator's $75%$ head-selection view for slot $s + 1$, *even if the slot-$(s+1)$ proposer is adversarial and refuses to relay votes!*
- If confirmation were instead evaluated at $75%$ ($3 Delta$), an adversary could deliver a vote to Alice at $74%$ (causing Alice to confirm $B$ at $75%$) while Bob only receives that vote at $98%$ (after Bob's $75%$ head-selection freeze has closed). If the next slot's proposer were also adversarial and omitted that vote, Bob would never include it in his slot-$(s+1)$ head walk!

*Why both numerator and denominator must be frozen together at $50%$.*
Even within a single node's local view, the $50%$ confirmation test must be protected against late-arriving votes:

#block(breakable: false)[
#problem[
Suppose a node tested whether block $B$ had majority support by counting timely votes for $B$ (arriving by $50%$) in the numerator, but dividing by a *live* denominator of all slot-$s$ votes received by the node so far. At $50%$ of slot $s$, the node might have received 100 timely votes, with 61 supporting $B$ ($61\/100 > 50%$, so $B$ passes). At $60%$ of slot $s$, 40 late adversarial votes for a competing branch arrive. If those late votes were added to the live denominator, the ratio would drop to $61\/140 < 50%$, un-confirming $B$ locally even though not a single supporting voter withdrew their vote.
]

#idea[
Prevent late-arriving votes from mutating the denominator by *freezing both the numerator and the denominator together* in an immutable local confirmation snapshot at $50%$ of slot $s$. Only the first valid wire vote received from each validator on or before $50%$ of slot $s$ enters the snapshot, and any validator known to have equivocated by that $50%$ cutoff is excluded from both the numerator and the denominator.
]
]

Formally, at $50%$ of slot $s$, each node records an immutable confirmation snapshot for slot $s$:
- Let $m_s$ denote the total number of committee seats represented by valid, non-equivocating slot-$s$ votes received on the wire at or before $50%$ of slot $s$.
- For any block $B$, let $c_s(B)$ denote the *frozen subtree support* of $B$ within that snapshot: the number of seats among those $m_s$ frozen votes that name $B$ or a descendant of $B$.

Notice that known equivocators at $50%$ are *excluded* from both $m_s$ and $c_s(B)$: if 45 timely seats support $A$, 45 support $B$, and 10 equivocate before $50%$, the confirmation snapshot has $m_s = 90$, $c_s(A) = 45$, and $c_s(B) = 45$, so neither branch achieves a strict majority ($> 45$).

== 4.2 Fast Confirmation in Slot $s$: Why the Threshold Is $3\/4$ of the Committee

Suppose we want to confirm a block $B$ *immediately at $50%$ ($2 Delta$) of slot $s$*—in the very same slot it is voted on, before the $75%$ view-merge freeze and before the slot-$(s+1)$ proposer even acts. How many supporting seats $c_s(B)$ out of the full 512-seat committee must a node observe at $50%$ of slot $s$ to be certain that *every* honest validator will still see a strict majority for $B$ at $75%$ ($3 Delta$), even if up to half of the committee is adversarial and double-votes?

The answer is *three quarters ($3\/4$) of the full 512-seat committee*:

#formula-card[$ c_s(B) >= (3 times 512) / 4 = 384 quad "seats" $]

*Mathematical derivation of the $3\/4$ fast-confirmation threshold.*
Let us normalize the total committee size to $1$ ($512$ seats), and assume Goldfish's security premise: *strictly less than $1\/2$ of the committee is adversarial* (at most $255$ of $512$ seats), so more than $1\/2$ is honest.

Suppose at $50%$ ($2 Delta$) of slot $s$, an honest node observes non-equivocating votes for block $B$ from a fraction of at least $3\/4$ of the entire committee ($c_s(B) >= 384$ seats):
1. *Propagation to all honest nodes by $75%$ ($3 Delta$):* Because these $3\/4$ votes were already received by an honest node at $50%$ ($2 Delta$), synchronous delivery ($Delta = 25%$) guarantees that all $3\/4$ of these votes arrive at *every* honest validator before the $75%$ ($3 Delta$) wire-intake freeze.
2. *Bounding the opposition ($<= 1\/4$):* At most the remaining $1 - 3\/4 = 1\/4$ of the committee ($128$ seats) did not vote for $B$ before $50%$. In the worst case, all $1\/4$ of those seats vote for a conflicting block $B'$ before $75%$.
3. *Worst-case adversarial double-voting (equivocation $e < 1\/2$):* Suppose a fraction $e$ of the committee who were part of the $3\/4$ supporting $B$ at $50%$ are actually adversarial and *equivocate*—broadcasting a second vote for $B'$ so that honest nodes detect their equivocation by $75%$ and exclude them from fork-choice support.
4. *Counting the remaining non-equivocating votes at $75%$:* Excluding the $e$ equivocators reduces $B$'s non-equivocating support from $3\/4$ down to at least:
   $ "Support"(B) >= 3\/4 - e $
   out of a total non-equivocating electorate of at most $1 - e$ (while any conflicting branch $B'$ has at most $1\/4$ non-equivocating support).
5. *When does $B$ retain a strict majority of all non-equivocating votes?* We require $B$'s remaining support $3\/4 - e$ to strictly exceed half of the remaining non-equivocating electorate $(1 - e)\/2$ (and strictly exceed $B'$'s $1\/4$):
   $ 3\/4 - e > (1 - e) / 2 quad <==> quad 3\/4 - 1\/2 > e - e\/2 quad <==> quad e\/2 < 1\/4 quad <==> quad e < 1\/2. $
6. Because the adversarial fraction of the committee is strictly less than half ($e < 1\/2$), the inequality $3\/4 - e > (1 - e)\/2$ *always holds*! Even if every single adversarial seat on the committee voted for $B$ before $50%$ and then double-voted for $B'$ before $75%$, the honest votes inside the $3\/4$ quorum ($> 3\/4 - 1\/2 = 1\/4$) still outnumber the remaining $1\/4$ of the committee!

Therefore, under the assumption that equivocators are excluded, seeing $>= 3\/4$ ($384\/512$) seats for $B$ at $50%$ ($2 Delta$) guarantees that $B$ holds a strict majority in *every* honest validator's $75%$ ($3 Delta$) frozen view—so every honest validator in slot $s + 1$ will walk through $B$ *even if the slot-$(s+1)$ proposer is adversarial!*

#example[
  *Numerical check of the $3\/4$ resilience to double-voting.* Out of $512$ committee seats, suppose the maximum possible number of seats—$255$ seats ($e = 255\/512 < 1\/2$)—are adversarial, and $257$ seats are honest.
  
  Suppose $B$ achieves fast confirmation at $50%$ with $c_s(B) = 384$ seats, consisting of $129$ honest seats plus all $255$ adversarial seats, while the other $128$ honest seats vote for conflicting branch $B'$. Between $50%$ and $75%$, all $255$ adversarial seats double-vote for $B'$ and are excluded as equivocators:
  - Remaining non-equivocating electorate at $75%$: $512 - 255 = 257$ honest seats.
  - Remaining support for $B$: $384 - 255 = 129$ seats.
  - Support for $B'$: $128$ seats.
  Because $129 > 257\/2 = 128.5$, block $B$ *still* retains a strict majority among the honest voters!
]

#caveat[
*Interaction with Section 3.4's head-walk equivocation rule.* Notice that Step 4 of the $3\/4$ proof above (from the Goldfish design post) relies on *excluding* detected equivocators from the slot-$(s+1)$ head walk so that $3\/4 - e > (1 - e)\/2$ holds for all $e < 1\/2$. As we saw in Section 3.4, however, the current head-walk rule grants known equivocators *generic viability credit* ($+e$ to both $B$ and $B'$) rather than excluding them. Under generic credit, $B'$'s score becomes $1\/4 + e$ out of $1$, which exceeds the majority gate $1\/2$ whenever $e > 1\/4$! This mismatch between the fast-confirmation threshold proof (which assumes equivocator exclusion) and the head walk (which uses generic credit) is an important theoretical point to keep in mind.
]

== 4.3 Delayed Available Confirmation in Slot $s + 1$, and Why Confirmation Views Can Diverge

Fast confirmation ($>= 384$ of $512$ seats) is immediate, but it requires at least $75%$ of the entire committee to be online and voting for the same branch. If half the validators are asleep (say, only $200$ of $512$ seats participate in slot $s$), no block can reach $384$ seats, so fast confirmation cannot advance.

To confirm blocks under *dynamic participation* (when many validators are offline), the protocol defines *delayed available confirmation*. Evaluated during slot $s + 1$ (starting at $50%$ of slot $s + 1$), it reads the frozen snapshot $(m_s, c_s(dot))$ captured at $50%$ of the *previous* slot $s$. Starting at the finalized root $F$, it walks down the unfiltered accepted block tree through children $B$ that satisfy a *strict relative majority* of the frozen participating seats $m_s$:

#formula-card[$ c_s(B) > m_s / 2 $]

#example[
  *Confirming a prefix via subtree support ($m_s = 100$).* Suppose at $50%$ of slot $s$, a node freezes $m_s = 100$ timely, non-equivocating seats distributed across the tree $F -> A -> B -> C$ and a sibling branch $A -> D$ (Diagram 4):
  - 60 seats name $C$;
  - 15 seats name $B$;
  - 25 seats name $D$.

  In slot $s + 1$, the delayed confirmation walk starts at $F$ with strict majority threshold $m_s\/2 = 50$:
  1. Child $A$ has subtree support $c_s(A) = 60 + 15 + 25 = 100 > 50$, so the walk enters $A$.
  2. At $A$, child $B$ has $c_s(B) = 60 + 15 = 75 > 50$ while $D$ has $c_s(D) = 25 <= 50$, so the walk enters $B$.
  3. At $B$, child $C$ has $c_s(C) = 60 > 50$, so the walk enters $C$ and stops. The delayed-confirmed head is $C$.
]

#mechanism-figure("confirmation-tree.svg")[Delayed available confirmation in slot $s + 1$ using the $m_s = 100$ seats frozen at $50%$ of slot $s$. Because votes for $C$ also credit ancestors $B$ and $A$, all three blocks along $F -> A -> B -> C$ exceed the strict majority threshold of 50 seats.]

#example[
  *Comparing delayed vs. fast confirmation on the same snapshot.* Suppose at $50%$ of slot $s$, a node freezes $m_s = 400$ timely seats, of which $c_s(B) = 380$ support block $B$ (Diagram 5):
  - *Fast confirmation (at $50%$ of slot $s$):* Fails, because $380 < 384$ (even though $380\/400 = 95%$ of participating voters supported $B$, the absolute threshold requires $75%$ of all 512 seats).
  - *Delayed available confirmation (in slot $s + 1$):* Passes easily, because $380 > m_s\/2 = 200$.
]

#mechanism-figure("confirmation-thresholds.svg")[Fast confirmation versus delayed available confirmation when $m_s = 400$ timely seats are frozen and $c_s(B) = 380$ support block $B$. The 380 seats easily clear the relative majority ($> 200$ of $400$) for delayed confirmation in slot $s + 1$, but fall short of the absolute $384$-of-$512$ threshold required for immediate fast confirmation in slot $s$.]

*Wait—why is the confirmation snapshot NOT view-merged in slot $s + 1$? And why wait until slot $s + 1$ if the snapshot is already frozen at $50%$ of slot $s$?*

If you examine the timing of delayed available confirmation closely, two natural questions arise:
1. *Why not view-merge the confirmation snapshot with the slot-$(s+1)$ proposer's block?*
   Ask whose votes arrive *after* $50%$ ($2 Delta$) of slot $s$ under synchrony ($Delta = 25%$):
   - Every *honest* member of the slot-$s$ committee broadcast its vote at $25%$ ($1 Delta$). Because maximum network delay is $Delta = 25%$, *100% of honest votes have already arrived at every honest node by $50%$ ($2 Delta$)*—honest votes do not need the slot-$(s+1)$ proposer to relay them!
   - Under synchrony, the *only* votes that arrive after $50%$ (between $50%$ and $75%$, or between $75%$ and $0%$ inside the next proposer's block) are *late votes withheld by adversarial validators*!
   - If the confirmation rule in slot $s + 1$ merged the slot-$(s+1)$ proposer's carried votes into slot $s$'s confirmation snapshot, an *adversarial* slot-$(s+1)$ proposer could stuff withheld adversarial slot-$s$ votes into its block at $0%$ of slot $s + 1$, mutating the confirmation denominator $m_s$ (or confirming an adversarial branch that had zero timely votes at $50%$)! Even worse, if the slot-$(s+1)$ proposer were offline or equivocated, a view-merged confirmation rule would stall or split.
   - Therefore, *view merge is strictly a head-selection mechanism* (helping an *honest* proposer in slot $s + 1$ align voters for the next vote); confirmation must instead restrict its electorate to votes that were actually *timely* at $50%$ ($2 Delta$).

2. *Then why does delayed confirmation wait until slot $s + 1$ to evaluate a snapshot that was already frozen at $50%$ of slot $s$?*
   - In the broader blockchain pipeline, a slot separates *consensus block headers* from *execution transaction payloads* (often called proposer-builder separation): at $0%$ of slot $s$, the proposer publishes the lightweight consensus block header committing to the parent block and a cryptographic hash of the transaction bundle, so the committee at $25%$ can immediately vote on the consensus chain's fork choice without waiting to download and execute megabytes of transactions. The actual transaction payload is revealed in the second half of slot $s$ and verified across the slot boundary, which is why general confirmation is scheduled in slot $s + 1$.
   - On the pure consensus block tree studied in this book, however, because the vote snapshot $(m_s, c_s)$ is already immutably frozen at $50%$ of slot $s$ and is never modified afterward, *waiting until $50%$ of slot $s + 1$ adds no new votes to $(m_s, c_s)$*.

3. *Wait—if an adversary releases late votes between $50%$ and $75%$, can delayed confirmation break permanence?*
   The answer depends critically on whether the slot-$s$ proposer was *honest* or *adversarial*:
   - *Case A — Honest slot-$s$ proposer under synchrony (permanence holds):* If the slot-$s$ proposer is honest, View Merge guarantees that *100% of active honest seats* vote for block $A$ at $25%$, and *zero* honest seats vote for any rival $B$. Because honest seats form a strict majority of the active electorate, even if the adversary withholds all of its ($< 1\/2$) votes and releases them for $B$ between $50%$ and $75%$, $A$ still holds a strict majority over $B$ at $75%$. Thus an honest proposer's block is never overturned.
   - *Case B — Adversarial slot-$s$ proposer (bare relative majority CAN be overturned!):* Suppose the slot-$s$ proposer is adversarial and equivocates (or releases its block right on the $25%$ deadline) so that *honest* voters split at $25%$: say 60 honest seats vote for $A$ and 40 honest seats vote for $B$. Unlike fast confirmation—whose $3\/4$ threshold builds in a $1\/4$ safety margin specifically to absorb adversarial votes—delayed confirmation uses a bare relative majority ($c_s(A) > m_s\/2$) with *zero* margin for withheld adversarial votes:
     - *Withholding between $50%$ and $75%$:* At $50%$, every honest node freezes $m_s = 100$ and $c_s(A) = 60 > 50$. Between $50%$ and $75%$, the adversary releases 30 withheld votes for $B$. Those 30 late votes miss the $50%$ confirmation snapshot $(m_s, c_s)$ *but* enter the $75%$ head-selection view (giving $B$ $40 + 30 = 70 > 60$ in the slot-$(s+1)$ head walk). At $50%$ of slot $s + 1$, delayed confirmation (reading the frozen $50%$ snapshot from slot $s$) confirms $A$ even though the live chain in slot $s + 1$ has already switched to $B$!
     - *Splitting stragglers across $50%$:* Similarly, if 80 honest seats split 40 for $A$ and 40 for $B$, and the adversary delivers 20 votes for $A$ to Alice at $49%$ and 20 votes for $B$ to Bob at $49%$ (with cross-copies arriving at $51%$), Alice confirms $A$ ($60\/100$) while Bob confirms $B$ ($60\/100$).

#caveat[
*Yes—bare-majority delayed confirmation at $50%$ is NOT reorg-proof when the proposer splits the honest committee!* Unlike $3\/4$ fast confirmation (which is provably permanent under synchrony against any $< 1\/2$ adversary), a bare relative majority ($> m_s\/2$) frozen at $50%$ has no buffer against adversarial votes arriving between $50%$ and $75%$ or stragglers split across $50%$. This is an explicit open problem in the current design (Question 2 in Chapter 10), and it is the exact reason why Section 4.4 must introduce a replaceable *live confirmed candidate* (so a node that confirmed an orphaned branch can recover in the next slot) and why Chapter 5 filters confirmation through the full-set $G_0$ conflict veto before any finality vote is cast.
]

== 4.4 Monotonicity versus Recovery: Historical Records and the Live Candidate

#block(breakable: false)[
#problem[
Because network partitions—or adversarial stragglers across the $50%$ cutoff (Section 4.3)—can cause Alice to confirm branch $A$ in slot $s$ while the available chain subsequently converges on conflicting branch $B$, a node faces two contradictory requirements:
1. A user-facing confirmation log should be *monotonic* (non-retracting) along compatible chains and should not silently erase the fact that $A$ was previously confirmed.
2. The node's internal consensus machinery (which feeds finality voting) *must* be able to abandon the orphaned branch $A$ and switch to the live branch $B$; if internal confirmation refused to move off $A$ forever, the node could never participate in finalizing $B$.
]

#idea[
Maintain two separate confirmation pointers in local state:
1. A *historical confirmation record* that only advances forward to descendants of its previous value, ignoring conflicting branches.
2. A *live available-confirmed candidate* that is unconditionally replaced at every evaluation by the current result of the delayed-confirmation walk, allowing it to retreat or switch branches when the next slot's snapshot favours a different branch.
]
]

The table below summarizes the four confirmation-related pointers maintained by a node and how they are consumed:

#chapter-table(columns: (0.95fr, 1.5fr, 1.25fr),
  table.header([*Confirmation pointer*], [*Update rule*], [*Role in the protocol*]),
  [*Live available-confirmed head*], [Set directly to the output of the delayed-confirmation walk; can retreat to an ancestor or switch to a conflicting branch], [Internal input to safe confirmation (Chapter 5) and round-start proposal guards (Chapter 6)],
  [*Historical available-confirmed head*], [Advances to the new delayed-confirmation result *only* if it extends the existing historical head (with a reset only if the old root conflicts with finality)], [External user-facing record of available-chain confirmation under synchrony],
  [*Historical fast-confirmed head*], [Advances to the new fast-confirmation result *only* if it extends the existing fast-confirmed head], [External user-facing record of immediate same-slot confirmation],
  [*Safe-confirmed head*], [Computed dynamically by walking back from the live available-confirmed head until no conflicting branch holds $>= 1\/3$ of full-set head weight (Section 5.4)], [Gates which target or timeout vote a validator may sign in Simplex finality (Chapter 7)]
)

#mechanism-figure("live-history.svg")[Separating the non-retracting historical confirmation record from the recoverable live confirmation candidate. If a partition or boundary split causes a node to confirm $A$ before converging on branch $B$, the live candidate switches to $B$ so the node can help finalize $B$, while the historical record remains at $A$ (until $B$ is finalized).]

#block(breakable: false)[
#caveat[
*Keeping a historical pointer at $A$ does not make $A$ safe.* Diagram 6 is an internal recovery mechanism, not a retroactive safety guarantee: if a user accepted a transaction in $A$ because $A$ was available-confirmed during a partition, and the network subsequently finalizes conflicting branch $B$, the finality check will eventually overwrite the historical record once $B$'s finality makes $A$ invalid. Available confirmation is safe *only* when the synchronous delivery and honest-committee assumptions hold.
]

#recap[
Confirmation identifies the prefix of the available chain that should not reorganize under synchrony, serving both external users and the internal finality gate. At $50%$ ($2 Delta$) of slot $s$—chosen so confirmed votes still have $1 Delta$ ($50% -> 75%$) to reach all honest nodes' $75%$ head-selection freeze—each node freezes an immutable snapshot ($m_s$ seats, $c_s(B)$ support). *Fast confirmation* at $50%$ of slot $s$ requires $c_s(B) >= 384$ ($3\/4$ of $512$), ensuring $3\/4 - e > (1 - e)\/2$ even if $e < 1\/2$ of the committee double-votes. *Delayed confirmation* in slot $s + 1$ requires $c_s(B) > m_s\/2$ of that local snapshot; because snapshots are not view-merged, nodes can diverge and rely on the *live confirmed candidate* to recover.
]
]

#v(1.2em)
= 5. Full-Set Stabilization: The Live Rules $G_1$ and $G_0$

In Chapters 3 and 4, we built an available chain driven entirely by 512-seat slot committees with one-slot vote memory. That design is fast and lightweight, but it has an obvious vulnerability: because slot-$(s-1)$ votes expire completely in slot $s + 1$, a single slot of poor network connectivity or an unlucky committee sample can wipe out the evidence holding the head on the canonical branch. Conversely, a single rogue committee sample might confirm a short branch that the broader validator set disagrees with.

To stabilize the available chain without requiring all validators to vote in every slot, the protocol introduces the *stabilization layer*, which draws on the second voting stream defined in Chapter 2: the live head vote carried inside full-validator-set finality attestations.

== 5.1 The Full-Set Head Vote Stream and Its 128-Slot Window

#block(breakable: false)[
#problem[
One-slot committee votes expire every slot, leaving the available chain vulnerable whenever a single slot's messages are delayed or lost. Yet we cannot ask the entire validator set to sign and broadcast votes in every slot. How can the protocol maintain a long-lived, full-validator-set view of the chain's head while keeping full-set voting at once per round?
]

#idea[
Every validator already broadcasts one finality attestation per round, and fills in that attestation's live head field at the moment of broadcast (Section 2.3). By storing each validator's most recent finality-attestation head vote in a sliding window of *128 slots*, every node maintains a continuously refreshed, long-lived head view across the full validator set.
]
]

Let us specify exactly which full-set head votes count in this sliding window:
- *Immediate wire updates:* Whenever a node receives a valid finality attestation over gossip (or inside a block), it immediately updates that validator's latest head entry in its stabilization table; it does not wait for the attestation to be included on-chain.
- *128-slot expiration:* A validator's latest head vote remains active for 128 slots from the slot in which it was cast. Once its age reaches 128 slots, it expires. If the validator casts a newer finality attestation before then, the new head vote overwrites the old one.
- *Equivocation exclusion:* Any validator known to have equivocated in its finality attestations is excluded.

*The usable live stake denominator ($D$) and subtree weight ($S(B)$).* At any moment, a node's *usable live population* consists of all active, unslashed validators whose latest finality-attestation head vote is unexpired (age $< 128$ slots), non-equivocating, and compatible with the node's current finalized root $F$.
- Let $D$ denote the sum of stake weights of all validators in this usable live population.
- For any candidate block $B$, let $S(B)$ denote the sum of stake weights of validators in this same usable population whose latest head vote names $B$ or a descendant of $B$.

Notice that $D$ is the *observed usable stake* in the node's 128-slot window, not necessarily the total active stake $W$ of the entire blockchain (if some validators have been offline for more than 128 slots, $D < W$). Furthermore, a validator whose latest head vote names an ancestor $A$ contributes its stake to $D$, and to $S(A)$, but contributes zero to $S(B)$ for any strict child $B$ of $A$.

From this single population $(D, S(dot))$, the stabilization layer defines two complementary rules: a positive selection rule ($G_1$, Section 5.2) and a conflict-veto predicate ($G_0$, Section 5.3).

== 5.2 Positive Selection ($G_1$): Finding a Two-Thirds Live Direction

The *grade-1 root* (or *$G_1$ root*) finds the deepest block supported by at least two thirds of the node's usable live full-set head weight $D$. Starting at the finality floor (currently our finalized root $F$), the node walks down the tree, stepping into a child $B$ whenever:

#formula-card[$ 3 S(B) >= 2 D $]

The walk continues until no child of the current block satisfies $3 S(B) >= 2 D$, and returns the last reached block as the $G_1$ root. (If $D = 0$, the walk immediately returns the starting floor $F$.) Because two sibling branches have disjoint subtrees and cannot both hold at least $2\/3$ of $D$, the $G_1$ walk is guaranteed to follow a unique path within any single node's view.

#example[
  *Computing the $G_1$ root.* Suppose a node's 128-slot window contains usable latest head votes from validators with total stake $D = 60$. Starting from $F$, two conflicting branches $A$ and $B$ exist:
  - $S(A) = 40$ (40 units of stake vote for $A$ or descendants of $A$);
  - $S(B) = 20$ (20 units of stake vote for $B$).

  Because $3 S(A) = 120 >= 2 D = 120$ (i.e., $40\/60 = 2\/3$), the $G_1$ walk steps into $A$. Now suppose $A$ has two children $A_1$ and $A_2$ with $S(A_1) = 25$ and $S(A_2) = 15$. Just like the Goldfish walk in Chapter 3, the denominator $D = 60$ remains fixed throughout the descent—it does not shrink to $40$. Since $3 times 25 = 75 < 2 times 60 = 120$, neither $A_1$ nor $A_2$ reaches two thirds of $D$, so the $G_1$ root stops at $A$.
]

#caveat[
*Uniqueness within one node's view does not imply agreement across partitioned nodes.* Because $D$ is a *relative* denominator (counting only the usable votes a node has received in the last 128 slots), suppose the network partitions so that Alice sees all 60 validators ($S(A) = 40, S(B) = 20, D = 60$), while an isolated node Bob has only received the 20 votes for $B$ ($S(B) = 20, D = 20$). Alice computes $G_1 = A$ ($40\/60 >= 2\/3$), whereas Bob computes $G_1 = B$ ($20\/20 >= 2\/3$). For this reason, $G_1$ is used only as a live fallback when the fixed-quorum stabilization mechanism (TSQ, Chapter 6) is unavailable.
]

== 5.3 Conflict Veto ($G_0$): Detecting One-Third Opposition

Whereas $G_1$ asks *"Does a branch have at least $2\/3$ positive support?"*, the *grade-0 predicate* (*$G_0$-clearance*) asks the opposite question: *"Does any conflicting branch have at least $1\/3$ opposing support?"*

Specifically, a candidate block $B$ is *$G_0$-clear* if and only if every accepted block $X$ that conflicts with $B$ (and is compatible with finality) has *strictly less* than one third of the usable live full-set head weight $D$:

#formula-card[Block $B$ is $G_0$-clear $<==>$ for every block $X$ conflicting with $B$, $quad 3 S(X) < D$.]

Notice the boundary condition: if a conflicting branch $X$ has *exactly* one third of $D$ ($3 S(X) = D$), the strict inequality $3 S(X) < D$ fails, so $X$ vetoes $B$. Conversely, if $D = 0$ (no usable votes), every block is vacuously $G_0$-clear because no opposition is observed—which is why $G_0$-clearance is never used by itself to confirm a block, but only to *veto* blocks that have already been confirmed by Goldfish.

#example[
  *Why $G_1$ can select $A$ while $G_0$ simultaneously vetoes $A$.* Return to our split of $D = 60$ with $S(A) = 40$ and $S(B) = 20$ on conflicting branches (Diagram 7):
  - *$G_1$ test on $A$:* $3 S(A) = 120 >= 2 D = 120$ ($40\/60 >= 2\/3$). Thus $G_1$ selects $A$.
  - *$G_0$ test on $A$:* Block $B$ conflicts with $A$ and has $3 S(B) = 3 times 20 = 60$, which violates $3 S(B) < 60$ ($20\/60 = 1\/3$ opposition). Thus $A$ is *not* $G_0$-clear!

  This asymmetry at the exact $2\/3$ and $1\/3$ boundaries is deliberate: when $2\/3$ of the observed validator set favours $A$ and $1\/3$ favours $B$, $A$ is the best candidate to keep building on ($G_1$), but there is still too much live opposition on $B$ to treat $A$ as conflict-free for finality voting ($G_0$).
]

#mechanism-figure("grades.svg")[Comparing the positive selection rule $G_1$ ($3 S(A) >= 2 D$) and the conflict-veto predicate $G_0$ ($3 S(X) < D$ for all conflicting $X$) when $D = 60$, $S(A) = 40$, and $S(B) = 20$. At the boundary, $40\/60$ suffices for $G_1$ to select $A$, while $20\/60$ suffices for $B$ to veto $A$'s $G_0$-clearance.]

== 5.4 Safe Confirmation: Filtering Available Confirmation with $G_0$

#block(breakable: false)[
#problem[
During a brief network disturbance or an unlucky committee sample, a 512-seat Goldfish committee can confirm a new prefix $F -> A -> B -> C$ even while a substantial fraction ($>= 1\/3$) of the full validator set is still voting for a competing branch $X$ that forked off at $A$. If validators immediately cast finality votes for $C$ based solely on the committee's available confirmation, they would ignore the full validator set's active disagreement.
]

#idea[
Define the *safe-confirmed head* by taking the live available-confirmed head $C$ (from Section 4.4) and walking backward along its ancestor chain until reaching the deepest ancestor that is *$G_0$-clear* (stopping no lower than the finality floor $F$).
]
]

Let us trace how safe confirmation combines Chapters 4 and 5 in a single concrete example.

#example[
  *Walking back from the available-confirmed tip until $G_0$ clears.* Suppose the node's live available-confirmed chain (confirmed by the 512-seat Goldfish committees) is $F -> A -> B -> C$ (Diagram 8). Meanwhile, in the 128-slot full-set head table, the total usable weight is $D = 90$:
  - $S(C) = 60$ (supporting $C$, and therefore also crediting ancestors $B$, $A$, and $F$);
  - $S(X) = 30$ on a branch $X$ that forks off from $A$ and conflicts with $B$ and $C$.

  To compute the safe-confirmed head, the node starts at the live available-confirmed tip $C$ and tests $G_0$-clearance (requiring $3 S(Y) < 90$, i.e., $S(Y) < 30$, for every conflicting block $Y$):
  1. *Test $C$:* Branch $X$ conflicts with $C$ and has $S(X) = 30$ ($3 times 30 = 90 lt.not 90$). Thus $C$ fails $G_0$. Step back to parent $B$.
  2. *Test $B$:* Branch $X$ also conflicts with $B$ and has $S(X) = 30$. Thus $B$ also fails $G_0$. Step back to parent $A$.
  3. *Test $A$:* Does $X$ conflict with $A$? *No!* Branch $X$ is a child of $A$, so $A$ is an ancestor of $X$ (they are compatible). Assuming no other branch conflicts with $A$, $A$ has zero conflicting weight ($0 < 30$), so $A$ is $G_0$-clear.

  The walk stops at $A$ and returns $"safe" = A$.
]

#mechanism-figure("safe-confirmation.svg")[Computing the safe-confirmed head. Even though Goldfish committees have confirmed up to $C$, the conflicting branch $X$ holds $30\/90 = 1\/3$ of the live full-set head weight $D$, vetoing both $C$ and $B$ under $G_0$. Walking backward along $C -> B -> A$ stops at $A$, which is an ancestor of $X$ and therefore $G_0$-clear.]

Notice how cleanly this mechanism decouples block production from finality voting:
- Goldfish can keep proposing blocks on $C$ and even advancing the committee-level available confirmation.
- At the same time, $G_0$ detects that $1\/3$ of the full validator set still supports branch $X$ above $A$, holding the *safe-confirmed head* back at $A$ so that Simplex finality voters only endorse the uncontested prefix $F -> A$.
- Once the validators on $X$ switch their finality-attestation head votes to $C$ (or their old votes on $X$ expire after 128 slots), $S(X)$ drops below $D\/3$, the $G_0$ veto clears, and the safe-confirmed head immediately advances to $C$.

#caveat[
*Why use $G_0$ instead of $G_1$ for safe confirmation—and why $G_0$ is only a partial mitigation.* At first glance, $G_1$ ($>= 2\/3$ of $D$ supporting $B$) and $G_0$-clear ($< 1\/3$ of $D$ on any branch conflicting with $B$) look like exact complements (differing only at the exact $2\/3$ boundary). Why, then, does safe confirmation use $G_0$-clear rather than $G_1$?
- *Why $G_1$ cannot confirm recent blocks:* Because only $1\/R$ of the full validator set casts a finality attestation in each slot (e.g., $1\/8 = 12.5%$ per slot when $R = 8$), a newly confirmed block $B$ from slot $s - 1$ has at most $1\/R$ of $D$ pointing into its subtree; the remaining $(R - 1)\/R$ of validators still have their latest messages pointing at *ancestors* of $B$. Thus no block younger than $ceil(2 R \/ 3)$ slots could ever pass $G_1$! Because votes on ancestors of $B$ do *not* conflict with $B$, however, a young uncontested block trivially has $0 < D\/3$ conflicting weight and passes $G_0$-clear immediately.
- *Why $G_0$-clear does not fully solve confirmation splits (two blind spots to test):*
  1. *Young-fork blindness ($1\/R < 1\/3$):* For the exact same reason, if an adversarial proposer or straggler attack in slot $s$ causes a Goldfish confirmation split between branches $A$ and $B$ (Section 4.3), at most $1\/R$ of the full validator set votes on the rival branch per slot. For the first $ceil(R\/3) - 1$ slots after the split (the first 2 slots when $R = 8$, or 10 slots when $R = 32$), the rival branch has $< D\/3$ weight, so *$G_0$-clear is completely blind to a fresh Goldfish split*!
  2. *Partition blindness (unseen rival votes):* During a network partition, nodes on side $A$ never receive the post-split votes cast on side $B$; side $B$'s pre-partition votes sit on a *common ancestor* (counting in $D$ without conflicting with $A$), so the losing partition continues to pass $G_0$-clear (as we verify empirically in Section 9.2).
]

#recap[
The stabilization layer tracks each validator's latest finality-attestation head vote over a 128-slot window (total usable stake $D$, subtree weight $S(B)$). *$G_1$* walks down children with $3 S(B) >= 2 D$; *$G_0$* checks that every conflicting branch $X$ satisfies $3 S(X) < D$. *Safe confirmation* walks back from the live available-confirmed head until it reaches a $G_0$-clear ancestor.
]

#v(1.2em)
= 6. Time-Shifted Quorum (TSQ): Round-Boundary Stabilization

In Chapter 5, we introduced $G_1$ ($3 S(B) >= 2 D$), which identifies a branch supported by two thirds of a node's live 128-slot head view. Why don't nodes simply use $G_1$ at the start of every round as the anchor root for their Goldfish head walks?

== 6.1 Why Live Relative Thresholds ($G_1$) Are Not Enough

#block(breakable: false)[
#problem[
Using the live $G_1$ rule directly as the primary round-boundary anchor has two vulnerabilities:
1. *Relative denominator divergence:* Because $G_1$ divides by the *observed* usable stake $D$ rather than the total active validator stake $W$, a node that has heard from only 20 of 64 validators can compute a $2\/3$ majority from just 14 validators, potentially locking onto a minority branch during a network split.
2. *Simultaneous support and equivocation races at the boundary:* If an adversary reveals new votes or equivocations right as a round starts, one honest validator might count a voter's positive support while another excludes that voter for equivocation, causing them to anchor their head walks on incompatible branches just as they choose their finality targets.
]

#idea[
Introduce *Time-Shifted Quorum (TSQ)* across the round boundary. Instead of reading a single live view, TSQ uses the finality attestations cast during round $r - 1$ (the *support round*) and separates positive support from equivocation detection across three distinct sub-slot moments:
1. *At $75%$ of the last slot of round $r - 1$:* Receivers *freeze* the set of messages eligible to contribute positive support ($F$).
2. *At $0%$ of the first slot of round $r$:* After a quarter-slot dissemination window, the round-$r$ proposer *pins* the candidate tree and total stake $W$, proposes a block, and relays any missing round-$(r-1)$ messages and equivocation evidence.
3. *At $25%$ of the first slot of round $r$:* After a second quarter-slot relay window, receivers compute their *TSQ lock* against a fixed quorum $q = ceil(2 W \/ 3)$ by intersecting their frozen positive set $F$ with their current equivocation-filtered view $U$.
]
]

Crucially, TSQ does *not* introduce a third signed message family: it operates entirely on the head votes carried inside the finality attestations cast during the preceding round $r - 1$.

== 6.2 The Three Data Structures: Live View $U$, Frozen View $F$, and Pinned Selection

To understand how TSQ separates positive support from equivocation removal, let us trace the three local records a node maintains as round $r - 1$ ends and round $r$ begins:

#enum(
  [*The Live Support-Round View ($U$):*
  Throughout round $r - 1$, whenever a node receives a valid finality attestation for round $r - 1$, it records the *first* complete attestation data received from each validator in a live table $U$. If the node later receives a *second, different* valid finality attestation signed by the same validator for round $r - 1$—even if it names the same head but differs in its finality fields—the node marks that validator as *equivocating* in $U$ (without overwriting the first recorded message).],

  [*The Frozen Receiver View ($F$, captured at $75%$ of round $r - 1$'s last slot):*
  At $75%$ of the final slot of round $r - 1$, the node saves an immutable snapshot $F$ by copying the current contents of $U$ together with its current equivocation marks. Once $75%$ passes, $F$ is never modified again; meanwhile, $U$ continues to accept late-arriving round-$(r-1)$ messages and equivocation evidence.],

  [*The Pinned Round Selection (captured at $0%$ of round $r$'s first slot):*
  At the exact boundary $0%$ starting round $r$, *before* processing any block proposed for round $r$'s first slot, each node pins the following parameters for round $r$:
  - the current starting finality floor (our finalized root $F$, generalized to the Simplex root in Chapter 8);
  - the set of currently viable candidate blocks above that floor;
  - each active, unslashed validator's stake weight;
  - the *total active stake $W$* across the entire validator set (including active slashed stake in the denominator); and
  - a *proposer candidate*, defined as the deepest block in the pinned candidate tree whose subtree support in the node's $0%$ view $U$ is at least the fixed two-thirds quorum of total active stake:]
)

#formula-card[$ q = ceil((2 W) / 3) $]

Notice the crucial difference between this threshold $q = ceil(2 W \/ 3)$ and $G_1$'s threshold ($2 D \/ 3$) from Chapter 5: $q$ is an *absolute threshold of total active stake $W$*. With 64 equal-balance validators ($W = 64$), the required quorum is $q = 43$ validators, even if a partitioned node has only heard from 20 validators! If no strict descendant of the pinned floor reaches $q = 43$, the proposer candidate defaults to the pinned floor itself.

Why pin these parameters at $0%$ *before* admitting the new round-start block proposal? Because processing a block can update chain state (such as validator balances, slashings, or finalized checkpoints); pinning before block processing ensures that the round-start block cannot circularly alter the electorate or candidate tree used to evaluate its own round's TSQ lock.

== 6.3 Computing the Receiver's TSQ Lock and Stable Root at $25%$

We now arrive at $25%$ of the first slot of round $r$, when every validator must choose its *stable root* (the anchor from which its Goldfish head walks will start during round $r$). How does a receiver combine its frozen view $F$ (from $75%$), its pinned selection (from $0%$), and its latest live view $U$ (at $25%$)?

*Step 1: Intersect $F$ and $U$.* A validator $v$'s round-$(r-1)$ head vote is counted at $25%$ if and only if $v$ appears with the *exact same complete attestation data* in both the frozen view $F$ and the current view $U$, and *neither* $F$ nor $U$ marks $v$ as equivocating. Because $U$ never overwrites the first valid message from $v$, this intersection rule has a clean, asymmetric effect:
- *No new positive support after $75%$:* If a validator's message arrived after the $75%$ freeze, it is absent from $F$, so it is excluded from $F inter U$. Late messages can *never* increase a branch's support in the receiver's TSQ lock.
- *Late equivocations subtract support until $25%$:* If validator $v$ was in $F$ at $75%$, but between $75%$ and $25%$ the receiver learns of a conflicting round-$(r-1)$ message from $v$ (for example, relayed by the round-$r$ proposer), $U$ marks $v$ as equivocating, removing $v$'s support from $F inter U$!

*Step 2: Project surviving heads into the pinned candidate tree.* For each validator $v$ surviving in $F inter U$, the node walks up the ancestors of $v$'s voted head until it hits the first block that belongs to the $0%$ pinned candidate tree. That ancestor receives $v$'s stake weight. (This ensures that if $v$ voted for a brand-new block that was not yet in the receiver's pinned tree at $0%$, $v$'s vote still credits its known ancestors in the pinned tree without allowing an unpinned block to become the lock.)

*Step 3: Walk down for the TSQ lock.* Starting at the pinned floor, the node descends through children in the pinned candidate tree whose projected subtree support is at least $q = ceil(2 W \/ 3)$. The deepest qualifying block is the node's *TSQ lock*. If no child of the pinned floor reaches $q$, the TSQ lock is simply the pinned floor itself.

*Step 4: Recheck against live state to set the Stable Root.* Finally, the node checks that its TSQ lock is still valid in its live $25%$ state (meaning the lock still extends the current finality floor and remains in the eligible tree). If so, the TSQ lock becomes the round's *stable root*. Only if the TSQ freeze or pinned selection data is missing, or if a state change between $0%$ and $25%$ invalidated the TSQ lock, does the node fall back to using its live *$G_1$ root* (Section 5.2) as the stable root.

#rule-box("Common pitfall: Failing to reach a 2W/3 quorum on a child does NOT trigger the G1 fallback")[
  Suppose no child above the pinned floor $F$ reaches $q = ceil(2 W \/ 3)$ support in $F inter U$. Then the TSQ walk returns the pinned floor $F$ itself as a *valid* TSQ lock. As long as $F$ passes the live-state check at $25%$, the round's stable root is $F$—the node does *not* switch to $G_1$ merely because no child had a $2 W \/ 3$ supermajority! The $G_1$ fallback is used only when TSQ inputs are missing (e.g., after a node restart) or when the TSQ lock fails the live viability/floor check.
]

== 6.4 Summary of the Five Stabilization Roots

Because stabilization involves five closely related block pointers, the table below provides a single reference contrasting their definitions and roles:

#chapter-table(columns: (0.95fr, 2.05fr),
  table.header([*Root pointer*], [*Definition and role*]),
  [*Finality / Simplex floor*], [The starting root from which all stabilization walks begin (the finalized checkpoint $F$, or the conditional justified/finalized Simplex root defined in Chapter 8)],
  [*Proposer candidate*], [The deepest block in the $0%$ pinned tree with $>= q = ceil(2 W \/ 3)$ support in the proposer's $0%$ view $U$; guides where the round-start proposer builds],
  [*TSQ lock*], [The deepest block in the $0%$ pinned tree with $>= q = ceil(2 W \/ 3)$ support in the receiver's intersected view $F inter U$ at $25%$ (or the pinned floor if no child reaches $q$)],
  [*$G_1$ root*], [The deepest block with $>= 2 D \/ 3$ relative support in the live 128-slot full-set head window (Section 5.2); serves as the fallback when TSQ is unavailable or invalidated],
  [*Stable root*], [The final anchor chosen at $25%$ of the round's first slot (the TSQ lock if valid, else the $G_1$ root); serves as the starting root for Goldfish head walks during the round]
)

== 6.5 The Quarter-Slot Relay Timeline and Proposer Duties

Diagram 9 places the three TSQ moments ($75% -> 0% -> 25%$) on a single timeline across the boundary between round $r - 1$ and round $r$:

#mechanism-figure("tsq-timeline.svg")[The Time-Shifted Quorum (TSQ) schedule across the boundary between the last slot of round $r - 1$ and the first slot of round $r$. Receivers freeze admissible positive support $F$ at $75%$; the round-$r$ proposer pins the selection and broadcasts its proposal plus relayed round-$(r-1)$ evidence at $0%$; receivers evaluate $F inter U$ at $25%$ so newly relayed equivocations remove support while late positive votes cannot add support.]

Notice that the two communication windows—from the receiver freeze $F$ ($75%$) to the proposer pin $P$ ($0%$), and from the proposer broadcast $P$ ($0%$) to the receiver action $A$ ($25%$)—each have duration $L\/4$ (one quarter of a slot: $1.5$ seconds for a 6-second slot, or $3$ seconds for a 12-second slot):
1. *During $75% -> 0%$ ($F -> P$):* Any round-$(r-1)$ finality attestation that entered an honest receiver's frozen view $F$ by $75%$ (along with any missing ancestor blocks needed to validate it) must finish propagating to the round-$r$ proposer before $0%$.
2. *At $0%$ ($P$) and during $0% -> 25%$ ($P -> A$):* The round-$r$ proposer broadcasts its new block proposal *and* re-gossips over the peer-to-peer network all retained round-$(r-1)$ signed finality attestations—including conflicting equivocating copies—together with any missing blocks in their ancestry.

Note that the proposed block itself does *not* contain a special "TSQ bundle" field; the proposer relays the round-$(r-1)$ messages and missing ancestry over gossip so receivers can validate them and update $U$ before $25%$. Compare this with Goldfish view merge (Section 3.3): in Goldfish, relayed available votes *add* positive support to the receiver's view; in TSQ, relayed round-$(r-1)$ finality messages cannot add positive support absent from $F$, but *can* expose equivocations in $U$ and subtract their support from $F inter U$.

#caveat[
*Open networking question:* While a well-synchronized receiver already knows almost all ancestor blocks, a lagging receiver may need several missing blocks plus signed attestations validated within $L\/4$. *A worst-case bandwidth and validation budget for this quarter-slot relay phase is not yet established.*
]

== 6.6 Quorum Intersection and the Time-Shift Safety Argument

Why did we go to the trouble of constructing $F$, $U$, and the two $L\/4$ relay windows? Because they allow us to prove three progressively stronger compatibility properties about the TSQ locks computed by honest nodes:

#enum(
  [*Property 1 (Single-node uniqueness, unconditionally):*
  Within any single node's pinned candidate tree, each validator in $F inter U$ contributes its stake once, and $2 q = 2 ceil(2 W \/ 3) > W$. Therefore, two conflicting child branches at the same node can never both reach $q$.],

  [*Property 2 (Cross-node lock compatibility under $< W\/3$ Byzantine stake, without relay timing):*
  Suppose all honest nodes share a common pinned candidate tree and active stake $W$, and total Byzantine stake is strictly less than $W\/3$. If honest node $X$ sees $>= q$ support for branch $A$ and honest node $Y$ sees $>= q$ support for a conflicting branch $B$, the two supporting sets of weight $>= 2 W\/3$ must overlap in at least $2 q - W >= W\/3$ stake. Because Byzantine stake is $< W\/3$, at least one honest validator would have had to sign two conflicting round-$(r-1)$ finality attestations, which honest validators never do. Thus $X$'s lock and $Y$'s lock must lie on the same chain (one is an ancestor of the other), even if messages arrive late!],

  [*Property 3 (Nested proposer-receiver locks under $< W\/2$ Byzantine stake, via the time shift):*
  What if Byzantine stake exceeds $W\/3$ (say, $40$ of $100$ validators are Byzantine, while $30$ honest validators vote for $A$ and $30$ honest validators vote for conflicting $B$)? Without the time shift, an adversary could send 40 votes for $A$ to $X$ ($30 + 40 = 70 >= 67$) and 40 equivocating votes for $B$ to $Y$ ($30 + 40 = 70 >= 67$), causing $X$ and $Y$ to lock onto conflicting branches $A$ and $B$.
  
  Here the $75% -> 0% -> 25%$ time shift does its work. Assume synchronous delivery within each $L\/4$ window and an honest round-$r$ proposer:
  - Every message that receiver $X$ eventually counts in $F_X inter U_X$ at $25%$ was already present in $F_X$ at $75%$, so it reaches the honest proposer's view $U_"prop"$ by $0%$.
  - Conversely, if any validator $v in F_X$ sent a conflicting message to another node before $0%$, the honest proposer sees both copies in $U_"prop"$ at $0%$ and relays the equivocation back to $X$ before $25%$, removing $v$ from $F_X inter U_X$.
  - Therefore, *every validator still counted by any honest receiver in $F_X inter U_X$ at $25%$ was also counted as a non-equivocating supporter in the honest proposer's view $U_"prop"$ at $0%$!*
  
  Because the proposer's counted support for any block is a superset of every honest receiver's counted support at $25%$, every honest receiver's TSQ lock at $25%$ is an *ancestor* of (or equal to) the honest proposer's $0%$ candidate! In our $40$-Byzantine split above, the honest proposer at $0%$ discovers all 40 equivocators and relays both copies; by $25%$, every honest receiver excludes all 40 equivocators, leaving $30 < 67$ on both $A$ and $B$, so all honest receivers safely lock onto the common floor $F$.]
)

== 6.7 Worked Example: Aligning Heads Across Nested Receiver Locks

Even when all validators are honest, network delays near the $75%$ cutoff can cause two honest receivers $X$ and $Y$ to freeze different subsets of votes in $F_X$ and $F_Y$, producing TSQ locks at *different depths along the same chain*. Let us trace how the round-start proposer aligns their heads anyway.

#example[
  *Ten honest validators ($W = 10$, quorum $q = ceil(20\/3) = 7$) on chain $F -> A -> B$.* Suppose validators 1–8 vote for $B$ (which also credits ancestor $A$) and validators 9–10 vote for $A$. At the $75%$ freeze of round $r - 1$:
  - Receiver $X$ has received votes 1–7 (giving $A$: 7 and $B$: 7, both $>= 7$).
  - Receiver $Y$ has received votes 1–6 and 9 (giving $A$: 7, which is $>= 7$, but $B$: 6, which is $< 7$).
  - By $0%$ of round $r$, all 10 votes reach the honest proposer (giving $A$: 10 and $B$: 8, so the proposer selects candidate $B$ and proposes block $P$ extending $B$, while relaying votes 1–10 to all nodes).

  The table below shows what each node computes from $75%$ through the $25%$ action:
]

#chapter-table(columns: (1.1fr, 1.5fr, 0.85fr, 1.2fr),
  table.header([*Node and deadline*], [*Messages in view*], [*Support $A$ / $B$*], [*Result ($q = 7$)*]),
  [Receiver $X$ at $75%$ freeze], [$F_X = \{1..7\}$], [$7$ / $7$], [Frozen view reaches $B$],
  [Receiver $Y$ at $75%$ freeze], [$F_Y = \{1..6, 9\}$], [$7$ / $6$], [Frozen view reaches $A$ only],
  [Proposer at $0%$ pin], [$U_"prop" = \{1..10\}$], [$10$ / $8$], [Candidate $B$; proposes $P$ on $B$],
  [Receiver $X$ at $25%$ action], [$F_X inter U_X = \{1..7\}$], [$7$ / $7$], [*TSQ lock = $B$*],
  [Receiver $Y$ at $25%$ action], [$F_Y inter U_Y = \{1..6, 9\}$], [$7$ / $6$], [*TSQ lock = $A$*]
)

Notice that at $25%$, Receiver $Y$'s live view $U_Y$ now contains all 10 votes (thanks to the proposer's relay), *yet $Y$'s TSQ lock remains at $A$, not $B$*, because votes 7 and 8 were not in $F_Y$ at $75%$! How, then, do $X$ (locked at $B$) and $Y$ (locked at $A$) select the *same* head $P$ at $25%$?

Through the *round-start proposal rule*: at the first slot of round $r$, if a single timely round-start proposal $P$ has arrived by $25%$, extends the receiver's stable root, and is compatible with the receiver's live available-confirmed prefix, the head walk starts directly from $P$! Because $P$ extends $B$, and $B$ extends $A$, $P$ is a descendant of *both* $X$'s stable root ($B$) and $Y$'s stable root ($A$). Thus both $X$ and $Y$ jump to $P$ as their shared head at $25%$ (Diagram 10).

#mechanism-figure("nested-locks.svg")[Aligning heads across nested TSQ locks ($W = 10, q = 7$). At $25%$, receiver $X$ locks onto $B$ ($7\/7$) while receiver $Y$ locks onto ancestor $A$ ($7\/6$, since relayed votes 7–8 were absent from $F_Y$). Because the proposer's timely block $P$ (built on $B$) extends both $A$ and $B$, the round-start proposal rule aligns both receivers' heads at $P$.]

*Exact execution order at the round boundary ($75% -> 0% -> 25%$).* Because a round boundary also triggers on-chain finality height evaluation (which we will study in Chapter 7), a node executes six steps in strict order across the boundary:
1. *At $75%$ of round $r - 1$'s last slot:* Freeze $F$.
2. *At $0%$ of round $r$'s first slot (before block processing):* Pin the round-$r$ TSQ parameters and proposer candidate.
3. *Upon receiving the round-$r$ first-slot block $P$:* Validate $P$ and execute its on-chain operations (including any finality attestations carried inside $P$).
4. *Immediately after the first-slot block (or empty slot):* Settle the pending finality height outcome for the completed round, potentially advancing the justified/finalized checkpoints.
5. *At $25%$ of round $r$'s first slot:* Compute the TSQ lock from $F inter U$ and the pinned inputs, verify that it remains valid above the current finality floor, and record the round's *stable root*.
6. *Also at $25%$ of round $r$'s first slot:* Select the head (starting from the stable root or distinguished proposal $P$) and freeze the validator's finality vote for round $r$.

#recap[
TSQ anchors each round using round-$(r-1)$ finality-attestation heads against an absolute quorum $q = ceil(2 W \/ 3)$. Freezing $F$ at $75%$, pinning the candidate tree and proposer candidate at $0%$, and intersecting $F inter U$ at $25%$ ensures that under synchronous relay, every honest receiver's TSQ lock is an ancestor of the honest proposer's candidate, allowing the round-start proposal $P$ to align their heads.
]

#v(1.2em)
= 7. Simplex Finality: Height-Based Justification and Finalization

Having established how Goldfish builds and confirms the available chain (Chapters 3–4) and how the stabilization layer anchors the head walk and filters confirmations into the safe-confirmed head (Chapters 5–6), we are ready to construct the third layer of the protocol: *how the full validator set justifies and finalizes checkpoints*.

== 7.1 From Wall-Clock Epochs to State-Driven Finality Heights

#block(breakable: false)[
#problem[
In epoch-coupled finality gadgets such as Gasper, every wall-clock epoch (every 32 slots) automatically introduces a new checkpoint target at the epoch boundary block, whether or not the previous epoch's checkpoint collected enough votes to be justified. During a network partition or period of low participation, wall-clock epochs keep ticking, creating a ladder of unjustified checkpoints at different epoch numbers across competing forks and complicating post-partition recovery.
]

#idea[
Replace wall-clock finality epochs with a state-driven *finality height* counter $h$ stored inside the chain state. Each height $h$ represents a single consensus attempt to either *justify* the first block of that height's interval or *time out* height $h$ and move on. Wall-clock rounds keep advancing every $R$ slots, but a chain's state remains at height $h$ for as many rounds as it takes until at least $2 W \/ 3$ of active validator stake is recorded on-chain to settle height $h$.
]
]

What block serves as the *target* of finality attempt $h$? Whenever a chain advances its state from height $h - 1$ to height $h$, the very first block of that new height interval on that branch becomes the branch's *interval target* $T$ for height $h$. As additional blocks are built on that branch while height $h$ remains open, the target $T$ for height $h$ does *not* change—every validator voting to justify height $h$ on that branch votes for that same interval-first block $T$. (On a conflicting branch that also reached numeric height $h$, the first block of height $h$ may be a different block $T'$.)

== 7.2 The Uniform Voting Gate: Target ($R_1$), Timeout ($R_2$), and Empty Votes

#block(breakable: false)[
#problem[
At $25%$ of the first slot of round $r$, every validator must freeze the finality fields of its round-$r$ attestation. Suppose a validator's head chain is currently at height $h$ with interval target $T$, but due to network delays or conflicting votes ($G_0$), its *safe-confirmed head* $C$ (from Section 5.4) has not yet reached $T$. What finality vote should the validator sign?
]

#idea[
Gate every finality decision by the *safe-confirmed head* $C$ (the *uniform voting gate*). Depending on how far $C$ has progressed along the selected head chain at height $h$, the validator chooses one of three vote kinds: a *Target vote ($R_1$)*, a *Timeout vote ($R_2$)*, or an *Empty vote*.
]
]

Let us state the exact decision rule executed by a validator at $25%$ of the first slot of round $r$ (assuming for a moment that the validator has no prior signing restrictions at height $h$; we add signing history in Sections 7.4 and 7.5). Let the validator's selected head chain be at state height $h$ with interval target $T$, and let $C$ be its current safe-confirmed head:

#enum(
  [*Target vote ($R_1$, voting to justify $T$ at height $h$):*
  If the safe-confirmed head $C$ contains the interval target $T$ (meaning $T$ is $C$ or an ancestor of $C$ on the head chain) *and* height $h$ permits fresh target votes, the validator freezes a *Target vote ($R_1$)* endorsing target $T$ at height $h$.],

  [*Timeout vote ($R_2$, voting to skip justification at height $h$ and advance to $h + 1$):*
  If the target condition above fails (for instance, because $T$ is on a conflicting branch or $T$ is not yet safe-confirmed), *but* the stored chain state of the safe-confirmed block $C$ itself has already reached height $h$, the validator freezes a *Timeout vote ($R_2$)* for height $h$ (carrying height $h$ with no target block).],

  [*Empty vote (making no claim at height $h$):*
  Otherwise—when even the safe-confirmed block $C$'s stored state is still at an older height $< h$—the validator freezes an *Empty vote* (encoded with height $0$).]
)

Notice what an Empty vote is—and what a Timeout vote is:
- An *Empty vote* ($h = 0$) does *not* mean the validator stays silent! The validator still broadcasts its finality attestation at its assigned slot in round $r$, because that attestation still carries a live head vote (needed by Chapters 5–6 for stabilization) and can still carry a finality commitment to an older justified checkpoint (Section 7.4). Setting height $0$ simply says: *"My safe-confirmed view has not yet reached height $h$, so I make neither a target claim nor a timeout claim for height $h$."*

#caveat[
*A Timeout vote ($R_2$) is a confirmation-gated quorum vote, not a local wall-clock alarm.* In traditional BFT protocols like Tendermint, a node sends a timeout message when its local wall-clock timer expires. Here, a validator only signs a Timeout vote ($R_2$) at height $h$ when its *safe-confirmed head $C$* has reached state height $h$ without confirming the head chain's target $T$ (or when bridging from a conflicting target during recovery, Section 7.5). Moreover, height $h$ only times out when at least $2 W \/ 3$ of stake is included on-chain!
]

== 7.3 Evaluating Height Outcomes: Target Support ($T_h$) vs. Advance Markers ($M_h$)

How does the blockchain's state transition process finality attestations once they are included inside blocks?

While a chain branch remains at height $h$, its state maintains two participation sets across the active, unslashed validator set:
1. *Exact-target support ($T_h$):* The total active stake of distinct unslashed validators whose included finality attestations at height $h$ cast a valid *Target vote ($R_1$)* for this branch's exact interval target $T$.
2. *Height-progress / advance markers ($M_h$):* The total active stake of distinct unslashed validators whose included finality attestations at height $h$ cast *either* a valid Target vote ($R_1$) for $T$ *or* a valid Timeout vote ($R_2$) at height $h$.

Because every valid Target vote ($R_1$) for $T$ sets *both* the target marker and the progress marker in chain state, while a Timeout vote ($R_2$) sets *only* the progress marker, the exact-target voters are always a subset of the progress-marker voters ($T_h <= M_h$). Each validator's identity is counted at most once in $T_h$ and at most once in $M_h$, even if that validator's attestations are included across multiple rounds while height $h$ remains open.

At each round boundary (after processing the operations of the round-start block, as we saw in Section 6.7), the chain state evaluates the *due height outcome* against the two-thirds quorum of total active stake $q = ceil(2 W \/ 3)$:
1. *Justify and advance:* Checked first! If height $h$ is justifiable and $T_h >= 2 W \/ 3$, the chain state marks target $T$ as *justified* at height $h$, resets the participation markers, and advances the branch's state height to $h + 1$.
2. *Advance without justification (Timeout quorum):* Otherwise, if $M_h >= 2 W \/ 3$, the chain state leaves its justified checkpoint unchanged, resets the participation markers, and advances the branch's state height to $h + 1$.
3. *Remain at height $h$:* Otherwise (when $M_h < 2 W \/ 3$), neither threshold is met; the branch's state height remains at $h$, and the existing participation markers in $T_h$ and $M_h$ are preserved so that attestations included in subsequent rounds can accumulate until $T_h$ or $M_h$ reaches $2 W \/ 3$.

#mechanism-figure("height-outcomes.svg")[Evaluating a due height outcome at height $h$ ($W = 64$ equal-balance validators, quorum $q = 43$). Because every exact-target voter ($T_h$) also sets a height-progress marker ($M_h$), $M_h$ measures the union of target voters and timeout voters. Justification ($T_h >= 43$) is checked before timeout advancement ($M_h >= 43$); if $M_h < 43$, height $h$ remains open across future rounds.]

The table below illustrates all three outcomes for $W = 64$ equal-balance validators ($q = 43$):

#chapter-table(columns: (1.25fr, 0.9fr, 1.0fr, 1.35fr),
  table.header([*Included height-$h$ votes*], [*Target weight $T_h$*], [*Progress weight $M_h$*], [*State transition outcome at round boundary*]),
  [43 Target ($R_1$) voters], [$43 >= 43$], [$43 >= 43$], [*Justify $T$* at height $h$ and advance to $h + 1$],
  [30 Target ($R_1$) voters + \ 15 distinct Timeout ($R_2$) voters], [$30 < 43$], [$30 + 15 = 45 >= 43$], [*Advance to $h + 1$* without justifying $T$],
  [25 Target ($R_1$) voters + \ 15 distinct Timeout ($R_2$) voters \ (24 Empty or not yet included)], [$25 < 43$], [$25 + 15 = 40 < 43$], [*Stay at height $h$*; keep all 40 markers accumulated for the next round]
)

== 7.4 Two-Stage Commitment: Justification vs. Finalization Piggybacks

#block(breakable: false)[
#problem[
Suppose a branch collects $T_h >= 2 W \/ 3$ target votes, justifying target $T$ at height $h$ and advancing to height $h + 1$. Why is $T$ only *justified* rather than immediately *finalized*? Because under asynchronous message delivery, some honest validators who voted for $T$ at height $h$ might not yet know that $T$ reached a $2 W \/ 3$ quorum; if a partition occurs right then, those validators might later switch to a timeout vote at height $h$ on a competing branch (Section 7.5), allowing a conflicting branch to advance past height $h$ without containing $T$.
]

#idea[
Require a second round of $>= 2 W \/ 3$ commitments to finalize a justified checkpoint. Once a validator sees that its chain has *justified* $(T, h)$, it attaches a *finality commitment* (called a *finality piggyback*) to its next finality attestation—provided the validator previously cast an $R_1$ target vote for $(T, h)$ and has never cast a timeout vote at height $h$. When included finality commitments for $(T, h)$ reach $2 W \/ 3$, $(T, h)$ becomes *finalized*.
]
]

Why is this second commitment called a *piggyback*? Because it rides inside the same finality attestation that casts the validator's vote for the *newer* height $h + 1$! For example, once height $h$ justifies $T$ and the chain enters height $h + 1$, a validator's round-$r$ attestation can simultaneously carry:
- a current-height vote ($R_1$, $R_2$, or Empty) for height $h + 1$, *and*
- a finality piggyback committing to finalize the justified checkpoint $(T, h)$.

Even if the new height $h + 1$ is not yet safe-confirmed (so the validator casts an Empty or Timeout vote for height $h + 1$), it can *still* attach its finality piggyback to finish finalizing $(T, h)$!

*The slashing/signing discipline and the $2 W \/ 3$ safety proof.* To make finalization irrevocable under $< W\/3$ Byzantine stake, every honest validator enforces two strict signing rules stored in durable local state across restarts:
1. *No double target at the same height:* A validator must never sign two different non-empty targets $T != T'$ at the same numeric height $h$.
2. *Finality lock at height $h$:* Once a validator signs a finality piggyback committing to $(T, h)$, it is *permanently locked* on $T$ at height $h$: it must never sign a Timeout vote ($R_2$) at height $h$ (nor could it have signed a finality piggyback if it had already signed a Timeout vote at height $h$).

With these two signing rules in place, the core quorum-intersection safety calculation is immediate:
- Suppose 100 equal-balance validators ($W = 100$, fewer than $33$ Byzantine) are active, and $67$ validators have signed finality commitments to $(T, h)$.
- For any conflicting branch (which does not contain $T$) to advance past height $h$, it must assemble a height-$h$ progress quorum $M_h >= 67$ composed of height-$h$ Target votes for some $T' != T$ and/or height-$h$ Timeout votes ($R_2$).
- By quorum intersection, any set of $67$ validators overlaps the $67$ finality committers for $(T, h)$ in at least $67 + 67 - 100 = 34$ validators.
- Since fewer than $33$ validators are Byzantine, at least one *honest* validator lies in the intersection. That honest validator already signed a finality commitment to $(T, h)$—which meant it previously voted for $T$ at height $h$ (forbidding it from voting for $T' != T$) and is finality-locked (forbidding it from signing a Timeout $R_2$ at height $h$).
- Therefore, *no conflicting branch can ever advance past height $h$ once $(T, h)$ has collected $>= 2 W \/ 3$ finality commitments!*

== 7.5 Post-Partition Recovery: The One-Way Target-to-Timeout Bridge

What happens when the network splits *before* $(T, h)$ is finalized, so that some honest validators sign a Target vote ($R_1$) for $T_A$ on branch $A$ at height $h$, while other honest validators sign a Target vote ($R_1$) for $T_B$ on conflicting branch $B$ at the same height $h$?

#block(breakable: false)[
#problem[
Suppose 40 honest validators voted for target $T_A$ at height $h$ and 60 honest validators voted for conflicting target $T_B$ at height $h$ (out of $W = 100$, quorum $q = 67$). Neither branch reached 67 target votes, so neither is justified. After the partition heals, all 100 validators converge on branch $B$. However, the 40 former $T_A$ voters are forbidden by the no-double-target rule from signing $T_B$ at height $h$, and the 60 $T_B$ voters alone are fewer than 67. How can branch $B$ ever advance past height $h$?
]

#idea[
Provide a *one-way target-to-timeout bridge* for unlocked validators. If a validator previously signed target $T_A$ at height $h$, has *not* signed a finality commitment to $(T_A, h)$, and now sees a safe-confirmed head $C$ on a conflicting branch $B$ that has reached height $h$, the validator is permitted to switch *once* from its saved target $T_A$ to a *Timeout vote ($R_2$)* at height $h$. That timeout is durably recorded, permanently closing the validator's ability to vote for or finalize $T_A$ at height $h$.
]
]

#example[
  *Escaping a split height via the one-way bridge ($W = 100, q = 67$).* In our 40/60 split above, once branch $B$ is safe-confirmed at height $h$:
  - The 60 validators who originally voted for $T_B$ continue to supply 60 exact-target votes ($R_1$) for $T_B$ on branch $B$.
  - The 40 unlocked validators who originally voted for $T_A$ take the one-way bridge and sign Timeout votes ($R_2$) at height $h$.
  - When both sets of votes are included on branch $B$, $B$'s exact-target weight is $T_h = 60 < 67$ (so $T_B$ is not justified), *but* $B$'s height-progress marker weight is $M_h = 60 + 40 = 100 >= 67$!
  - By Outcome 2 of Section 7.3, branch $B$ advances from height $h$ to height $h + 1$ via a timeout quorum. At the fresh height $h + 1$, no validator has a conflicting prior target, so all 100 honest validators can vote together to justify and finalize height $h + 1$!
]

What if the 40 validators on branch $A$ *had* already signed finality commitments to $(T_A, h)$ (which could happen if $T_A$ was justified at height $h$ with help from Byzantine validators before the chain reorganized to $B$)? Then those 40 locked validators are *forbidden* from taking the timeout bridge at height $h$; they must cast Empty votes whenever their selected chain conflicts with $T_A$. (We will see in Section 8.4 how the protocol uses *nonjustifiable heights* to prevent an adversary from trapping honest nodes in repeated unfinalizable justifications.)

== 7.6 Steady-State Latency: Why Each Height Takes Two Rounds

Under synchronous, fault-free operation, a striking rhythm appears: *advancing by one finality height in steady state takes two rounds (16 slots), not one round (8 slots).* Why?

Trace what happens at the boundary starting round $r$, when a newly included block $P$ settles height $h - 1$ and opens a brand-new height $h$:
1. *At $0%$ of round $r$'s first slot:* Block $P$ is proposed and processed. Its post-state advances to height $h$, making $P$ the interval target $T$ for height $h$.
2. *At $25%$ of round $r$'s first slot:* Validators must freeze their finality votes for round $r$. At this moment ($25%$ of slot 0 of round $r$), $P$ is the current-slot head, *but $P$ has not yet been available-confirmed!* Recall from Chapter 4 that $P$'s available attestations are only being broadcast right now at $25%$, frozen at $50%$, and delayed-confirmed in the *next* slot. Because the safe-confirmed head cannot yet include $P$, the uniform voting gate (Section 7.2) sees that the new target $P$ is not yet safe-confirmed, and therefore freezes Empty (or older-state) finality fields for round $r$!
3. *Later in round $r$:* Even though Goldfish confirms $P$'s chain by slot 1 of round $r$, validators assigned to slots $1..7$ of round $r$ must emit the finality fields they already froze at $25%$ of slot 0 (Section 2.3).
4. *At $25%$ of round $r + 1$'s first slot:* Now $P$ is well inside the safe-confirmed prefix! Every honest validator freezes a Target vote ($R_1$) for $(P, h)$ at the start of round $r + 1$, broadcasts it across round $r + 1$, and sees height $h$ justified (and advanced to $h + 1$) at the start of round $r + 2$.

#recap[
Simplex organizes finality by chain-state *heights* $h$. At $25%$ of a round's first slot, each validator gates its frozen vote by its safe-confirmed head $C$: Target ($R_1$), Timeout ($R_2$), or Empty ($h = 0$). On-chain inclusion tracks exact-target stake $T_h$ and progress-marker stake $M_h$ ($T_h <= M_h$), advancing height $h$ when either reaches $2 W \/ 3$. Finalization requires a second $>= 2 W \/ 3$ quorum of *finality piggyback* commitments, while the *one-way target-to-timeout bridge* lets unlocked validators recover from pre-finality splits.
]

#v(1.2em)
= 8. Constraining the Block Tree by Height

In Chapters 3–7, we saw how votes along a chain cause its state height $h$ to advance and its checkpoints to become justified and finalized. Now we close the loop: *how do the state heights and justified/finalized checkpoints stored across the block tree feed back to constrain head selection and stabilization?*

== 8.1 Height Viability: Pruning Stale Branches with $h_max - 1$

#block(breakable: false)[
#problem[
Suppose the main chain $A$ has accumulated several rounds of finality quorums and reached state height $12$, while an abandoned side branch $B$ (which forked off just above the finalized root $F$) is still sitting at state height $9$. Because Goldfish committee votes expire after a single slot (Chapter 3), if a brief network hiccup in slot $s$ causes the 512-seat committee votes on branch $A$ to be delayed, nothing in Goldfish alone would stop an adversary or a tiny subset of votes from pulling head selection all the way back onto the stale height-9 branch $B$.
]

#idea[
Filter the eligible block tree by state height. Each node computes its *frontier height* $h_max$—the maximum state height among all accepted blocks in its current finalized subtree. A leaf block is *height-viable* if and only if its state height is at least $h_max - 1$, and an internal block remains viable if and only if it is an ancestor of at least one viable leaf.
]
]

Diagram 12 illustrates the height viability filter when the highest state height in the finalized subtree is $h_max = 12$:
- The viable-leaf threshold is $h_max - 1 = 11$.
- Branch $A -> A_1$ ends at leaf $A_1$ with state height $12 >= 11$, so $A_1$ and its ancestor $A$ are *viable* (any leaf at height $11$ would also be viable).
- Branch $B -> B_1$ ends at leaf $B_1$ with state height $9 < 11$, so the entire branch $B -> B_1$ is *excluded* from the height-viable tree used by head selection, $G_1$, and TSQ!

#mechanism-figure("viability.svg")[The height viability filter when the frontier height in the finalized subtree is $h_max = 12$. Only paths leading to a leaf of state height at least $h_max - 1 = 11$ remain eligible for head selection and stabilization. A stale branch $B -> B_1$ whose best leaf is at height $9$ is pruned from the head walk, though $G_0$ and available confirmation still inspect the unfiltered tree.]

Two interactions with the rest of the protocol are essential:
1. *The final viability descent in head selection:* What if the ordinary Goldfish majority walk (Section 3.2) stops at an internal ancestor $A$ whose own state height is below $h_max - 1$ (because the slot-$(s-1)$ committee votes split among $A$'s children so no child got $> m\/2$)? Because $A$ is in the viable tree, $A$ must lead to at least one viable leaf of height $>= h_max - 1$. In that case, the head walk continues descending from $A$ through viable children *without* the $> m\/2$ gate (picking the viable child with the highest available score and tie-breaker) until it reaches a block of height at least $h_max - 1$.
2. *What is NOT filtered by height viability:* Recall from Chapters 4 and 5 that both *available confirmation* and the *$G_0$ conflict veto* operate on the *unfiltered* accepted block tree above $F$. Even if branch $B$ is excluded from head selection by height viability, live full-set head votes on $B$ can still trigger a $G_0$ veto until they expire or move.

== 8.2 The Simplex Floor: Switching Between the Justified and Finalized Checkpoints

Up to this point, we have referred to the starting floor of stabilization ($G_1$, $G_0$, safe confirmation, and TSQ) simply as the finalized root $F$. In the full protocol, that starting floor is called the *Simplex root*, and it dynamically switches between the node's highest *justified* checkpoint $J$ and its *finalized* checkpoint $F$:

#formula-card[
  Let $J$ be the node's stored justified checkpoint (justified at height $j$), $F$ its finalized checkpoint, and $h_max$ the frontier height in $F$'s subtree. Then:
  $ "SimplexRoot" = cases(
    J & "if " h_max = j + 1,
    F & "otherwise (when " h_max != j + 1 ")."
  ) $
]

Why does the Simplex root start at the justified checkpoint $J$ when $h_max = j + 1$, but drop back to the finalized checkpoint $F$ if $h_max$ advances to $j + 2$ or higher without a newer justification?

#example[
  *Why the Simplex floor releases $J$ when height advances past $j + 1$.* Suppose a branch justifies checkpoint $J$ at height $j = 10$. As soon as $J$ is justified in chain state, that branch advances to height $11$, so $h_max = 11 = j + 1$. While $h_max = 11$, the Simplex root is $J$, forcing all stabilization walks and head selection to build strictly on descendants of $J$ so validators can finish finalizing $J$.

  Suppose, however, that a pre-stabilization split (like the one in Section 7.5) left too many validators locked or split on another branch, so $J$ fails to finalize at height $11$, and instead a competing branch advances via timeout quorums ($M_h >= 2 W \/ 3$) to height $12$. Once $h_max = 12 > j + 1$, the Simplex root drops back from $J$ to the finalized checkpoint $F$, releasing the fork choice from $J$ so the whole validator set can converge on the higher-height branch!
]

== 8.3 Preventing Justification Bouncing

In epoch-based protocols like Gasper, a well-known vulnerability is *justification bouncing*: suppose branch $A$ has a justified checkpoint at epoch $e$, while on conflicting branch $B$, honest validators cast 60 votes for a checkpoint at epoch $e + 1$ and an adversary withholds 7 Byzantine votes. After honest validators move back to $A$, the adversary releases the 7 withheld votes to complete a 67-vote justification certificate on $B$ at epoch $e + 1$, yanking the highest-justified-checkpoint floor from $A$ to $B$ (and potentially repeating the alternation across later epochs).

How does Simplex constrain this interaction between late justification certificates and fork-choice movement? Through three combined mechanisms:
1. *Strict monotonic ordering of accepted justifications:* A node only updates its stored justified checkpoint $J$ when a newly observed justified checkpoint descends from current finality $F$ and strictly exceeds the currently stored $(j, "hash")$ pair in lexicographical order. Replaying an older or lower-height certificate can never move $J$ backward.
2. *The $h_max = j + 1$ equality condition on the Simplex floor:* A late justification at height $j$ only constrains the Simplex floor if $j$ sits right at the current frontier ($h_max = j + 1$). If the active chain has already progressed to height $h_max >= j + 2$, a delayed justification at height $j$ cannot hijack the Simplex floor.
3. *Height viability ($h_max - 1$):* Even if $J$ drops back to $F$, branches whose best leaf has fallen more than one height behind $h_max$ remain excluded by the height viability filter.

== 8.4 Nonjustifiable Heights and Inactivity Leaks Under Prolonged Stalls

What if an adversary during an asynchronous period repeatedly helps justify checkpoints at consecutive heights $j, j + 1, j + 2, dots$ without ever allowing any of them to collect the second round of finality piggybacks needed for finalization?

To ensure that the chain periodically gets a clean, timeout-only height where no validator can acquire a new target lock, the protocol introduces *nonjustifiable heights*:
- Define a branch's *finality debt* when entering height $h$ as $h - h_"fin"$, where $h_"fin"$ is the height of its last finalized checkpoint.
- Whenever the finality debt is strictly greater than $2$ ($h - h_"fin" > 2$) *and* the newly entered height $h$ is divisible by $8$ ($h mod 8 = 0$), height $h$ is permanently marked as *nonjustifiable* on that branch (for instance, entering height $16$ when the last finalized height is $12$).
- At a nonjustifiable height, validators never freeze fresh Target votes ($R_1$), and the state transition skips Outcome 1 (justification) at round boundaries: the *only* way to advance from $h$ to $h + 1$ is via an advance-marker / timeout quorum ($M_h >= 2 W \/ 3$).

Finally, if a catastrophic partition permanently disconnects more than $1\/3$ of validator stake so that neither $T_h$ nor $M_h$ can reach $2 W \/ 3$, the chain state activates an *inactivity leak*: height/leak evaluations back off from once per round to once per epoch, gradually draining the stake weights of offline validators until the online validators represent $>= 2 W \/ 3$ of the remaining active stake.

#block(breakable: false)[
#caveat[
*Open theoretical questions in Chapter 8.* While the protocol rules fix the exact constants—a slack of $1$ height in $h_max - 1$, the exact equality $h_max = j + 1$ for the Simplex floor, and the period of $8$ for nonjustifiable heights—*the formal liveness theorems proving that these exact constants suffice for post-GST healing across all pre-stabilization histories are still open research questions* (collected in Chapter 10).
]

#recap[
Heights and checkpoints constrain the fork choice from below: the height viability filter prunes any branch whose best leaf has state height $< h_max - 1$, the Simplex floor anchors stabilization at the justified checkpoint $J$ when $h_max = j + 1$ (and falls back to $F$ otherwise), and nonjustifiable heights force every 8th height under finality debt $> 2$ to advance purely by timeout quorum.
]
]

#v(1.2em)
= 9. Protocol Behavior Under Faults, Partitions, and Healing

A consensus student truly understands a multi-layer protocol when they can predict how every state variable behaves when network assumptions break. In this chapter, we trace five local quantities—the *head*, *live available confirmation*, *safe confirmation*, the *stable root*, and the *finalized checkpoint* ($F$)—across network partitions, deadline boundary races, node restarts, and post-GST healing.

== 9.1 Symmetric Partition: A 50/50 Split (32 vs. 32 Validators)

Suppose $W = 64$ equal-balance validators (full-set quorum $q = ceil(2 times 64\/3) = 43$) start from a common finalized block $F$ and split cleanly into two isolated halves of 32 validators each (Side A and Side B), with zero cross-partition message delivery (Diagram 13, left):

- *Simplex finality and heights (Halt safely):* Neither Side A (max weight 32) nor Side B (max weight 32) can assemble $q = 43$ validators. Therefore, neither side can justify a new target ($T_h < 43$), finalize a checkpoint, or advance its state height via a timeout quorum ($M_h < 43$). Slots and rounds keep incrementing on the wall clock, while both sides remain stuck at their pre-partition height $h$ and finalized root $F$.
- *Goldfish head and delayed confirmation (Continue independently on each side):* On Side A, approximately half of each slot's 512 committee seats belong to Side A's 32 validators. Because Goldfish head selection ($> m\/2$) and delayed available confirmation ($c_s(B) > m_s\/2$) use *relative* denominators counting only the seats that voted on that side, Side A's chain keeps producing blocks and advancing its live available-confirmed head along branch $A$, while Side B independently produces blocks and advances its live available-confirmed head along conflicting branch $B$! (Fast confirmation, by contrast, requires $384\/512$ absolute seats, which a 32-validator half almost never holds.)
- *Stabilization ($G_1$, $G_0$, and TSQ):* In TSQ, neither side can reach the fixed quorum $q = 43$ for any strict descendant of the Simplex floor, so every valid TSQ evaluation on both sides returns the pre-partition Simplex floor $F$ as its TSQ lock and stable root. What about $G_0$ and safe confirmation? For the first 128 slots of the partition, if Side A still holds unexpired pre-partition head votes from Side B's validators, those votes do not conflict with new blocks built above their common ancestor; once 128 slots pass, Side B's validators expire from Side A's live denominator $D$, so Side A sees $D = 32$ with zero opposition on $B$, and the safe-confirmed head advances on each side!
  - *Why doesn't advancing the safe-confirmed head on both sides break finality safety?* Because even though validators on Side A cast Target votes ($R_1$) for branch $A$'s height-$h$ target and validators on Side B cast Target votes ($R_1$) for branch $B$'s height-$h$ target, neither side has $43$ validators to reach a justification or finality quorum!

== 9.2 Asymmetric Partition: A 75/25 Split (48 vs. 16 Validators)

Now split the 64 validators into a majority partition of 48 validators (Side A) and a minority partition of 16 validators (Side B), as shown on the right of Diagram 13:

- *On the 16-validator minority side (Side B):* Just as in the 50/50 split, the 16 validators can continue proposing blocks and even delayed-confirming a minority available chain among their ~128 committee seats per slot, while their full-set TSQ locks and finality heights remain completely frozen ($16 < 43$).
- *On the 48-validator majority side (Side A):* Because $48 >= q = 43$, Side A has enough active stake to form full-set TSQ locks, justify targets ($T_h >= 43$), advance heights, and finalize new checkpoints ($F -> F' -> F''$)!
- *What happens when the partition heals?* Once messages resume between Side A and Side B, Side B receives blocks carrying Side A's newer finalized checkpoint $F''$. Because $F''$ conflicts with Side B's minority branch, finality updates immediately move Side B's finalized root to $F''$, pruning Side B's entire unfinalized (and locally available-confirmed!) branch from the tree and resetting Side B's historical confirmation record.

#mechanism-figure("partition-healing.svg")[Comparing a symmetric 32/32 partition and an asymmetric 48/16 partition ($W = 64$, full-set quorum $q = 43$), followed by the four-stage recovery pipeline when communication resumes after GST.]

== 9.3 Boundary Stragglers: Votes Arriving Just After a Deadline

Because each slot contains multiple sub-slot cutoffs ($25%$, $50%$, and $75%$), a single late message is not simply "accepted" or "dropped"—its effect depends on *which cutoff it missed*:

#chapter-table(columns: (0.9fr, 1.35fr, 1.45fr),
  table.header([*Message & arrival time*], [*What it CANNOT affect*], [*What it CAN still affect*]),
  [Available vote arriving at $60%$ of slot $s$ (between $50%$ and $75%$)], [Missed the $50%$ confirmation snapshot, so it cannot contribute to fast confirmation in slot $s$ or delayed confirmation in slot $s + 1$], [Arrived before the $75%$ wire cutoff, so it *does* enter the node's live Goldfish view and helps steer head selection in slot $s + 1$],
  [Round-$(r-1)$ finality vote arriving at $85%$ of the last slot (between $75%$ and $25%$)], [Missed the $75%$ TSQ freeze, so it is absent from $F$ and can never add positive support to the receiver's TSQ lock], [Enters the live view $U$ (and the 128-slot $G_1$ / $G_0$ table); if it reveals an equivocation before $25%$, it *removes* that signer from $F inter U$],
  [Round-$(r-1)$ finality vote arriving after $25%$ of round $r$'s first slot], [Missed the $25%$ action, so it cannot alter round $r$'s recorded stable root or frozen finality vote], [Still updates the 128-slot live head table ($G_1$ / $G_0$) and can still be included on-chain inside a block to count toward $T_h$ and $M_h$]
)

== 9.4 Missing or Equivocating Round-Start Proposers

What happens at the start of round $r$ if the designated proposer for the first slot is offline (or broadcasts two conflicting round-start proposals $P$ and $P'$)?
- *If the round-start proposer is silent:* At $25%$, every honest receiver still computes its TSQ lock from $F inter U$ and sets its stable root normally. However, without a round-start block $P$, two things are lost: (1) if honest receivers froze nested locks at different depths (like $X$ at $B$ and $Y$ at $A$ in Section 6.7), there is no distinguished proposal $P$ to pull $Y$'s starting root up to $B$ at slot 0; and (2) any last-slot finality votes from round $r - 1$ that were waiting for block inclusion in slot 0 are not included before the round-$r$ height outcome is evaluated.
- *If the round-start proposer equivocates ($P$ vs. $P'$):* If a receiver observes two distinct proposals for the round-start slot at or before $25%$, the round-start proposal rule refuses to grant special status to *either* proposal; the node simply starts its Goldfish walk from its own stable root. (If the adversary splits delivery so Alice sees only $P$ and Bob sees only $P'$ before $25%$, Alice and Bob may follow $P$ and $P'$ in slot 0, and must rely on subsequent Goldfish slots to reconverge.)

== 9.5 Node Restarts and Missing Local Snapshots (Fail-Closed Rules)

Because TSQ freezes, confirmation snapshots, and finality signing histories are local deadline-driven states rather than on-chain objects, what must a validator node do if it crashes and restarts mid-round without those persisted records?

The protocol enforces a strict *no-hindsight, fail-closed principle*: a restarting node must *never* reconstruct a past deadline's frozen snapshot from whatever messages it happens to hold later. Specifically:
- If the frozen TSQ view ($F$) or pinned round selection is missing at $25%$, the stable-root calculation falls back to the live $G_1$ root.
- If a validator's frozen finality decision (from $25%$ of slot 0) is missing when its assigned duty slot arrives later in the round, the validator *skips casting a finality attestation for that round* rather than recomputing a fresh target mid-round.
- If a validator loses its durable signing-history record (which tracks every target, timeout, and finality piggyback it has ever signed), it must *halt signing completely* (fail closed), because guessing its history from the current chain state could cause it to sign a slashable double vote after a reorganization.

== 9.6 How the Protocol Heals After a Partition (The Seven-Step Sequence)

Suppose a prolonged 50/50 partition (Section 9.1) caused Side A and Side B to build incompatible available chains $A$ and $B$ and cast conflicting height-$h$ target votes $T_A$ and $T_B$. When the network heals at GST (synchronous delivery resumes), how do the three layers work together to restore finality progress?

#enum(
  [*Mutual block and vote dissemination:* Gossip and proposer relay exchange the missing blocks, available votes, and finality attestations between Side A and Side B.],
  [*Goldfish head convergence (1–2 slots):* Because old available votes expire after 1 slot, view merge (Section 3.3) quickly aligns honest committee voters onto a single winning tip (say, on branch $B$).],
  [*Live available-confirmation convergence:* Within the next two slots, the live available-confirmed head on all honest nodes switches to branch $B$ (Section 4.4), even on nodes whose historical confirmation record still remembers $A$.],
  [*Full-set head replacement and $G_0$ clearance (across rounds):* As validators cast their once-per-round finality attestations naming the new head on branch $B$, their latest head entries in the 128-slot stabilization table move from $A$ to $B$. Once opposing stake on $A$ drops below $D\/3$, the $G_0$ veto clears on branch $B$, and the safe-confirmed head advances into branch $B$'s height-$h$ interval.],
  [*TSQ round-start lock alignment:* At the next round boundary with an honest proposer, TSQ locks and the round-start proposal anchor all honest nodes' Goldfish walks on branch $B$.],
  [*Bridging split height $h$ via timeouts ($R_2$):* At $25%$ of the first slot of the next round, validators who previously voted for $T_B$ freeze Target votes ($R_1$) for $T_B$, while unlocked validators who previously voted for $T_A$ see that branch $B$ is now safe-confirmed at height $h$ and take the *one-way target-to-timeout bridge* (Section 7.5) to freeze Timeout votes ($R_2$). When included on-chain, the combined progress markers reach $M_h >= 2 W \/ 3$, advancing branch $B$ to fresh height $h + 1$.],
  [*Clean justification and finalization at height $h + 1$:* At height $h + 1$, no honest validator has a conflicting prior target vote. All honest validators vote for branch $B$'s height-$(h+1)$ target ($R_1$), justifying it at the next round boundary and finalizing it via finality piggybacks in the round after that.]
)

#block(breakable: false)[
#recap[
During a 50/50 partition, Simplex finality safely halts while Goldfish committees can confirm diverging available branches on each half; during a 75/25 partition, the majority side continues finalizing and overwrites the minority branch upon healing. After GST, recovery proceeds from bottom to top: Goldfish head alignment $->$ live available confirmation $->$ $G_0$ clearance and safe confirmation $->$ TSQ lock alignment $->$ one-way timeout bridging ($M_h >= 2 W \/ 3$) $->$ clean justification and finalization at $h + 1$.
]
]

#v(1.2em)
= 10. Synthesis and Open Theoretical Questions

By building Decoupled Consensus from the problems up, we can see how each mechanism fits into a single coherent architecture:
- *Goldfish* (Chapters 3–4) provides slot-by-slot head selection via one-slot vote expiration and proposer view merge, plus immutable $50%$-cutoff snapshots for delayed ($> m_s\/2$) and fast ($>= 384\/512$) available confirmations.
- *The Stabilization Layer* (Chapters 5–6) uses the 128-slot full-set head window to veto contested confirmations ($G_0: 3 S(X) < D$), provide a live fallback direction ($G_1: 3 S(B) >= 2 D$), and align round-start anchors against an absolute quorum ($q = ceil(2 W \/ 3)$) via the $75% -> 0% -> 25%$ Time-Shifted Quorum (TSQ) pipeline.
- *Simplex Finality* (Chapters 7–8) replaces wall-clock epochs with state-driven heights $h$, gating Target ($R_1$) and Timeout ($R_2$) votes by the safe-confirmed head, finalizing justified checkpoints via piggybacked commitments, and constraining the block tree via the $h_max - 1$ viability filter and conditional Simplex floor.

== 10.1 Nine Open Research Questions

Throughout this book, we have distinguished between rules that define what a single node computes locally and multi-node safety or liveness properties whose formal proofs remain open research problems. The nine questions below collect these open problems for theoretical discussion:

#enum(
  [*Formal TSQ theorem and fault threshold ($< W\/3$ vs. $< W\/2$):*
  What exact common-electorate, pinned-tree compatibility, and $L\/4$ relay assumptions are required in the formal proof of cross-node TSQ lock compatibility above $W\/3$ Byzantine stake, and how does the protocol guarantee that honest nodes re-establish a common pinned candidate tree and floor after an arbitrary pre-GST partition?],

  [*Adversarial splitting of the $50%$ confirmation cutoff:*
  Because the confirmation snapshot at $50%$ of slot $s$ is frozen locally without a subsequent view-merge step for that snapshot, what formal assumption or reconciliation mechanism prevents an adversary from delivering straggler votes across the $50%$ cutoff to make two honest nodes compute incompatible delayed confirmations in slot $s + 1$?],

  [*Branch-relative committee convergence after a deep fork:*
  If two sides of a long partition diverge far enough that their on-chain randomness assigns different 512-seat committees to the same wall-clock slot $s$, how does Goldfish re-establish a common committee interpretation upon healing before finality overrides one branch?],

  [*The post-GST healing bound and the $h + 2$ safe-confirmation landmark:*
  Which exact lemma connects the live available-confirmed head, $G_0$-clearance, the $h_max - 1$ viability filter, and the once-per-round finality attestation schedule to prove that all honest validators reach compatible safe confirmations within a bounded number of heights (such as two heights) after GST?],

  [*Exactness of the $h_max - 1$ slack and the $h_max = j + 1$ Simplex-floor test:*
  Why does the height viability filter retain a slack of *exactly one* height ($h_max - 1$), and why does the Simplex floor use the justified checkpoint $J$ *only* when $h_max = j + 1$ (dropping back to $F$ at $h_max = j + 2$)? Are there multi-fork recovery scenarios where a 1-height slack is either too tight or too loose?],

  [*The constant $8$ in nonjustifiable heights under finality debt:*
  Under finality debt $h - h_"fin" > 2$, every 8th height ($h mod 8 = 0$) is marked as nonjustifiable. What adversary strategy or recovery bound determines the period $8$ (and the debt threshold $2$), especially when an adversary holds finality commitments from an earlier height?],

  [*Quarter-slot ($L\/4$) relay bandwidth and validation budget:*
  In TSQ, the proposer must learn receivers' $75%$ frozen views by $0%$, and receivers must download and validate the proposer's relayed round-$(r-1)$ signed attestations plus any missing ancestor blocks by $25%$. What upper bounds on missing ancestry depth and signature verification load make these two $L\/4$ windows realistic in practice?],

  [*External semantics when historical and live confirmations diverge:*
  When a partition heals onto a conflicting branch so that the internal live available-confirmed candidate switches branches while the external historical confirmation record remains on the orphaned branch (until finality triggers a reset), how should a client expose that divergence to external users?],

  [*Two-round-per-height steady-state cadence:*
  As traced in Section 7.6, because a round-start block $P$ opening height $h$ at $0%$ is not yet delayed-confirmed at the $25%$ finality-freezing deadline of that same slot, steady-state justification takes two rounds per height. Is this two-round cadence the intended schedule, or is a fast-confirmation / shifted-gate optimization envisioned to achieve one-round-per-height justification?]
)
