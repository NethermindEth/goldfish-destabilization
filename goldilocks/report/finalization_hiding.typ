#import "style.typ": *
#import "timeline.typ": *
#import "sync_attack_fig.typ": *
#import "fin_hide_fig.typ": *
#set document(title: "Goldilocks: the finalization-hiding attack")
#set page(paper: "a4", margin: (x: 2cm, y: 2cm), numbering: "1")
#set text(size: 10pt, lang: "en")
#set par(justify: true, leading: 0.62em)
#set heading(numbering: "1.1")
#show ref: set text(fill: rgb("#1d5f9e"))
#show heading.where(level: 1): it => { v(0.7em); text(size: 14pt, it); v(0.25em) }
#show heading.where(level: 2): it => { v(0.4em); text(size: 11pt, it); v(0.1em) }
#set table(stroke: 0.4pt + luma(180), inset: 4pt)
#show table: set text(size: 8.6pt)
#show table: set par(justify: false)

#text(size: 17pt, weight: "bold")[Goldilocks: the finalization-hiding attack]
#v(-6pt)
#text(size: 9pt, fill: luma(90))[A confirmed and locked block reverted while the network is synchronous · 3 Nov 2026 · Goldilocks specification (FG-SA, 22 Oct 2026) and its Lean formalization (`fradamt/simplified-dc-lean`) · simulator: `goldilocks/`]

= The previous protocol's available chain <sec-prev>

Decoupled consensus splits Ethereum's consensus into two parts. The *available chain* keeps producing blocks and tells users early which blocks it considers safe; those statements are fast, but they rest on assumptions about the network. The *finality gadget* runs on top of it and makes blocks irreversible, more slowly. This section recaps how the available chain of the previous protocol worked, and includes a refresher on the attack we found on it, the *Synchrony Attack*. @sec-gold describes how Goldilocks works in comparison with the old protocol. @sec-attack explains the new attack we found.

*Slots and blocks.* Time is divided into *slots* of fixed length. In each slot one validator, the *proposer*, creates a *block*. Following parents from a block back to the first block gives its *chain*; the blocks on it are its *ancestors*, and the blocks built on top of it are its *descendants*. A block *extends* another if it is that block or one of its descendants. Two blocks with the same parent are *siblings*. Two blocks *conflict* when neither is an ancestor of the other: they sit on different branches, and at most one of them can end up on the final chain. A block that ends up off the final chain is *orphaned*.

*The network.* The analysis assumes *synchrony*: all nodes share one clock, and there is a known bound Δ such that a message sent at time $t$, or relayed by an honest node at time $t$, reaches every honest node before $t + Delta$. A slot lasts $4Delta$; in the setup we simulate, a slot is 6 s and Δ = 1.5 s. Validators that follow the protocol are *honest*. The others are *faulty*: some may just be slow or offline, some are controlled by an *adversary*, who coordinates them and can choose when each honest node receives each of their messages, within the synchrony bound.

*Votes and the head.* In every slot a *committee* of validators votes. The deployed design samples about 512 committee *seats* per slot (a validator can hold several); the spec, and our simulations, let every validator vote. A *Goldfish vote* is a signed message that names one block: the tip of the chain the voter currently believes is the right one, its *head*. A vote for a block also counts for all of that block's ancestors: we say the vote *supports* them. Only recent votes matter: the votes of slot $s$ are used in slots $s$ and $s + 1$, and older votes are ignored. A validator that signs two different votes in the same slot has *equivocated*. Anyone who sees both votes can prove it, so honest nodes relay the second vote too, as evidence, and the protocol treats such an *equivocator* specially.

*The head walk.* A node picks its head with a fork-choice rule we call the *head walk*: starting from a recent settled block, it keeps stepping to the child supported by a strict majority of the slot's voters, and stops when no child has one. The votes a node uses for this are its *view*.

*Confirmation.* A *confirmation rule* tells users when a block will not be reverted. The protocol's answer, the newest confirmed block on the node's current chain, is the node's *confirmed tip*. Confirmations are meant to be safe whenever the network is synchronous: a confirmed block should never be orphaned.

A slot has four phases, one per Δ. Figure 1 shows them, and when the votes of slot $s$ are used during slot $s + 1$. We write $t_s$ for the start of slot $s$.

#figure(
  timeline(
    bands: (
      (0, 1, c-prop, [proposal travels]),
      (1, 2, c-vote, [honest votes travel]),
      (2, 3, c-late, [late votes · relays]),
      (3, 4, c-merge, [proposer collects]),
    ),
    events: (
      (0, 1, c-prop, [$B_s$ proposed]),
      (1, 2, c-vote, [committee votes \ (head walk)]),
      (2, 1, c-conf, [*snapshot frozen* \ fast confirmation]),
      (3, 2, c-late, [*view freeze*: \ view closes]),
      (4, 1, c-merge, [proposal carries \ slot-$s$ votes]),
      (5, 2, c-vote, [slot-$(s + 1)$ votes: \ head walk on slot-$s$ votes]),
      (6, 1, c-conf, [*delayed confirmation* \ of slot $s$]),
    ),
  ),
  caption: [One slot of the previous spec. The coloured bands are the four phases of slot $s$; the marks in slot $s + 1$ show where the votes of slot $s$ are used. The terms in bold are explained in 1.1–1.4.],
)

== Proposal $[0, Delta]$

At $t_s$ the proposer of slot $s$ runs the head walk on the slot-$(s - 1)$ votes it holds, builds block $B_s$ with the resulting head as parent, and puts those votes into $B_s$: a block carries the votes of the previous slot, in a field of its own (1.4 explains how the proposer collects them, and why). Under synchrony every honest node has $B_s$ before $t_s + Delta$.

An adversarial proposer can instead deliver its block to some nodes before $t_s + Delta$ and to others after it, so that some honest validators vote for its block and the rest for its parent. That is the first step of the Synchrony Attack (1.6).

== Honest votes and the confirmation snapshot $[Delta, 2Delta]$

At $t_s + Delta$ every member of the slot-$s$ committee runs the head walk and votes for its head, normally $B_s$. Nobody has voted for $B_s$ yet, so on votes alone the walk would never reach it; the rule makes one exception, letting the walk step into a block of the current slot without votes. That is how a fresh proposal becomes the head. Honest votes are sent at $t_s + Delta$, so under synchrony all of them reach every honest node before $t_s + 2Delta$.

At $t_s + 2Delta$ each node takes a *confirmation snapshot* of slot $s$: the first vote of each validator received by then. The snapshot fixes two numbers that confirmation will use: the number of *voters* $m_s$, the validators with a vote in the snapshot, and the *support* $c_s (B)$ of each block. Validators already known to have equivocated are left out of both. Under synchrony the snapshot holds every honest vote, and nothing that arrives later changes it.

There are two confirmation rules, both read from the snapshot:
- *Fast confirmation*, right away at $t_s + 2Delta$: $B$ is confirmed if $c_s (B)$ is at least $3\/4$ of the whole committee.
- *Delayed confirmation*, one slot later at $t_(s+1) + 2Delta$: $B$ is confirmed if $c_s(B) > m_s\/2$, a strict majority of the snapshot's voters. It covers the case where many validators are offline and $3\/4$ is out of reach.

== Late votes and the view freeze $[2Delta, 3Delta]$

A vote that arrives after $t_s + 2Delta$ is *late*. Under synchrony an honest vote is never late, so late votes come from faulty validators: slow, offline for a while, or adversarial. The only other votes arriving now are relays of votes that some honest node received just before $2Delta$; those reach the other honest nodes before $3Delta$. Late votes still enter the view, so a node's head can still change during this phase: a node recomputes its head whenever it needs it, with the votes it holds at that moment. This ends at $t_s + 3Delta$, the *view freeze*: each node closes its view of slot $s$, and a slot-$s$ vote that arrives on the network after this moment no longer enters its head walk.

The gap of one Δ between the snapshot ($2Delta$) and the view freeze ($3Delta$) is deliberate. Every vote that some honest node has in its snapshot is relayed to every other honest node before that node closes its view. So the votes behind a confirmation are present in every honest head walk of the next slot. Fast confirmation relies on this property.

== Block building $[3Delta, 4Delta]$

The proposer of slot $s + 1$ is the exception to the view freeze: it keeps collecting slot-$s$ votes until it proposes at $t_(s+1) = t_s + 4Delta$, and puts all of them into its block (1.1). When a voter of slot $s + 1$ receives that block, it adds the votes it carries to its own view. This is the *view merge*. With an honest proposer, the proposer's collection contains every vote that any honest node has in its view, so after the merge every honest voter runs the head walk on the same votes and reaches the new block. An adversarial proposer can leave votes out, so that honest voters walk on different views.

== How the votes are used

The same votes of slot $s$ feed three rules, and the rules count them differently:

#table(columns: (1.1fr, 1.25fr, 1.6fr, 1.35fr),
  table.header([*rule*], [*which slot-$s$ votes*], [*threshold*], [*equivocators*]),
  [head walk (at $t_(s+1)$ and $t_(s+1) + Delta$)], [received before the view freeze ($t_s + 3Delta$), plus those carried by the slot-$(s+1)$ block], [follow a child whose support is a strict majority of all validators in the view; a current-slot block is always allowed], [count *for every block*, and as voters],
  [fast confirmation ($t_s + 2Delta$)], [the snapshot], [support $>= 3\/4$ of the whole committee], [left out of support and voters],
  [delayed confirmation ($t_(s+1) + 2Delta$)], [the same snapshot], [support $> m_s\/2$, a strict majority of the snapshot's voters], [left out of support and voters],
)

The head walk counts an equivocator's vote *for every block*. Otherwise an adversary could show one vote to some nodes and a second, different vote to others, and move a block in or out of the majority at will; crediting the equivocator everywhere removes that lever.

Why $3\/4$ for fast confirmation? The adversary holds less than half of the committee. If at least $3\/4$ of the committee supports $B$ in one honest node's snapshot, those votes reach every honest view before the view freeze, and they keep $B$ an honest majority even if every adversarial supporter later equivocates. Delayed confirmation has no such margin: a bare majority of the *snapshot* is enough. That is where the Synchrony Attack lives.

== The Synchrony Attack

Delayed confirmation and the head walk read *different* sets of votes. Delayed confirmation counts only the snapshot, taken at $2Delta$, both for support and for voters; the head walk counts everything received until the view freeze at $3Delta$. A vote that arrives between the two is invisible to the confirmation but visible to the head walk. An adversary with 25% of the stake uses that gap. It needs to propose one slot, and it never equivocates.

Our setting has 64 validators: nodes 0 and 1 host 16 honest validators each, node 2 hosts 16 more, and the remaining 16 belong to the adversary. Honest messages take 200 ms, and Δ = 1500 ms. Times below are counted from the start of slot $s$; @fig-sync shows them, and the numbers in the steps refer to its markers. Three blocks matter: $B_(s-1)$, the honest head when slot $s$ starts; $B_s$, the adversary's block of slot $s$, built on $B_(s-1)$; and $C_(s+1)$, the honest block of slot $s + 1$.

#figure(
  sync-attack-timeline(),
  caption: [The Synchrony Attack, from the start of slot $s$ (0 ms) to the delayed confirmation in slot $s + 1$ (9000 ms). One lane per party; the dashed lines are the moments of Figure 1.],
) <fig-sync>

+ *Split the honest votes* (markers 1, 2). The adversary proposes $B_s$ and delivers it to nodes 0 and 1 at 1400 ms, just before they vote at 1500 ms, and to node 2 at 1600 ms, just after. Relay from nodes 0 and 1 also reaches node 2 only after its vote. Nodes 0 and 1 vote for $B_s$; node 2 has not seen it and votes for its parent $B_(s-1)$. This is the only moment where honest nodes see different things.
+ *Stay out of the snapshot* (marker 3). The adversary holds back its own 16 votes. At 3000 ms every honest snapshot has 48 voters, 32 of them for $B_s$: $32 > 24$. The snapshot is set to confirm $B_s$ one slot later.
+ *Vote late* (marker 4). At 3200 ms, after the snapshot and before the view freeze, the adversary sends its 16 votes, all for $B_(s-1)$. They reach every honest node by 3400 ms.
+ *$B_s$ loses the majority* (marker 5). At the view freeze, 4500 ms, every honest view has 64 voters and $B_s$ still has 32. Since 32 is not more than half of 64, the head walk no longer steps into $B_s$: it stops at $B_(s-1)$.
+ *$B_s$ is orphaned* (marker 6). At 6000 ms, the start of slot $s + 1$, the honest proposer runs the head walk, which stops at $B_(s-1)$, and builds $C_(s+1)$ on it. At 7500 ms every honest validator votes for $C_(s+1)$. $B_s$ is off the chain that everyone follows.
+ *$B_s$ is confirmed anyway* (marker 7). At 9000 ms, every honest node runs the delayed confirmation of slot $s$. It reads the *slot-$s$ snapshot*, where $B_s$ has 32 of 48 voters, and confirms $B_s$: a block that is already orphaned.

#figure(
  sync-attack-tree(),
  caption: [The resulting blocks. $B_s$ is confirmed by every honest node at $t_(s+1) + 2Delta$, but $C_(s+1)$, built on $B_(s-1)$, is the block that stays.],
)

All honest nodes are fooled in the same way. The flaw is not that nodes disagree with each other: it is that *each node's* confirmation and *its own* head walk count different votes. The previous spec also had a stricter "safe" confirmation, which checked the latest votes of the whole validator set; but each validator casts that whole-set vote only once every 8 slots, so within one slot only an eighth of them had seen $C_(s+1)$, too few to notice.

#pagebreak()
= Goldilocks <sec-gold>

Goldilocks is the available chain of the new specification (AC): *Goldfish with locks*. It keeps Goldfish's slots and votes, and a head walk that works the same way, apart from where it starts (2.5). There is no longer a same-slot fast confirmation: every block is confirmed one slot later, by a single rule (2.1). The word "fast" survives only in the *fast test* for locks (2.2), which has nothing to do with the old $3\/4$ rule. The two main changes are:
- *Confirmation counts voters late.* The support of a block is still taken from early votes, but the number of voters now includes every vote received up to the moment the confirmation is computed. This closes the Synchrony Attack, as we show at the end of this introduction.
- *Locks*, explained in 2.2–2.5. In short, a confirmed block is protected for a few slots: the node keeps building on it even if the votes of one slot are missing or misleading.

*The finality gadget.* Goldilocks runs alongside a finality gadget. Slots are grouped into *rounds* of $R = 8$ slots. Once per round, at $2Delta$ into the round's second slot, each validator sends an *attestation*. It carries two votes: a *target vote* for a recent block derived from the available chain's locks (2.2), and a *finality vote* for the most recently *justified* block. A block becomes justified when two thirds of the validators target it, and *finalized* when two thirds send finality votes for it. Finalized blocks can never be reverted; justified blocks are on the way there. Each node keeps track of its latest finalized block, written $F$, and *accepts only blocks that extend* $F$: a block on another branch is refused, together with everything inside it. The tree a node walks also consists only of blocks extending $F$: when $F$ moves forward, blocks that no longer extend it drop out of it, although votes the node already took from them stay in its count of voters. These rules matter for the attack in Section 3.

#figure(
  timeline(
    rows-below: 2,
    bands: (
      (0, 1, c-prop, [proposal travels]),
      (1, 2, c-vote, [honest votes travel]),
      (2, 3, c-late, [late votes · relays]),
      (3, 4, c-merge, [proposer collects]),
    ),
    events: (
      (0, 1, c-prop, [$B_s$ proposed]),
      (1, 2, c-vote, [vote \ (after unlocking \ against slot $s - 1$)]),
      (2, 1, c-conf, [*support cutoff* \ (+ update of $s - 1$)]),
      (3, 2, c-late, [*view freeze*]),
      (4, 1, c-merge, [proposal carries \ slot-$s$ votes]),
      (5, 3, c-lock, [*unlocking* against \ slot-$s$ votes, \ then slot-$(s + 1)$ vote]),
      (6, 1, c-conf, [*confirmation update* \ of slot $s$: \ confirm + lock]),
    ),
    spans: (
      (1, 2, 1, c-conf, [support]),
      (1, 6, 2, c-lock, [voters: every slot-$s$ vote held at $t_s + 6Delta$]),
    ),
  ),
  caption: [One slot of Goldilocks. The marks at $t_s$, $t_s + Delta$, $t_s + 3Delta$ and $t_(s+1)$ are as in Figure 1; at $t_s + 2Delta$ the snapshot of Figure 1 becomes the *support cutoff* (box below). New: *unlocking* against the slot-$s$ votes at $t_(s+1) + Delta$ (2.3), and the *confirmation update* of slot $s$, which confirms and locks, at $t_(s+1) + 2Delta$ (2.1, 2.2). The same two steps for slot $s - 1$ happen inside slot $s$, at $t_s + Delta$ and $t_s + 2Delta$. The brackets show which votes count as *support* and which as *voters*.],
)

The support of a block is defined as in Goldfish, with one more condition: the vote must be *resolved* in time.

#rule-box("Support of a block")[
For the confirmation of slot $s$, the *support* of a block $B$ is the number of validators whose slot-$s$ vote
+ was *resolved before $t_s + 2Delta$*. A vote is resolved once the node holds both the vote and the block it names; a vote for a block the node has not received yet cannot be counted;
+ comes from a validator that has *not equivocated*: the node holds no second, different slot-$s$ vote from it;
+ names *$B$ or a descendant of $B$*.

The *voters* are all validators with *any* slot-$s$ vote that the node holds when it computes the confirmation, at $t_s + 6Delta$: late votes, votes for unknown blocks and equivocators included.
]

This is how Goldilocks closes the Synchrony Attack. The adversary's late votes for the parent, released between $2Delta$ and $3Delta$, now count as voters in the confirmation as well. With the numbers of 1.6, $B_s$ has 32 votes out of 64 voters, which is not a strict majority, so $B_s$ is never confirmed. Confirmation and head walk count the same voters again, *as long as every honest node holds the same votes*. Section 3 shows how to break that condition.

== When is a block confirmed?

At $t_s + 6Delta$, which is two Δ into slot $s + 1$, each node runs the *confirmation update* of slot $s$ (spec, Figure 8). The update does a walk of its own, similar to the head walk. It starts at the finalized block $F$ and steps to a child only if that child's support is a *strict majority of the voters*:
$ 2 dot "support"(B) > V, quad "where" V "is the number of voters of slot" s "held at" t_s + 6Delta. $
The block where this walk stops is the *confirmed* block $C$, and its whole chain back to $F$ is confirmed with it: support can only grow towards the root, so every block on the way passed the test too. The node stores $C$ as its *record*, the latest confirmed block, unless the node holds a lock on a block that conflicts with $C$; then the result is ignored (*vetoed*). The confirmed tip that users see is the newest block that both the record and the node's current head extend: normally the record itself, but less if the head has moved to another branch.

The rule is *relative* to how many validators voted. With all 64 voting it needs 33 votes; with only 30 voters, 16.

== When is a block locked?

A *lock* is a mark a node puts on a confirmed block, with an expiry time. Right after confirming $C$, the update locks one block of $C$'s chain: the newest one that passes one of two tests.
- *Fast test:* support $>= n\/2$, where $n$ is the size of the *whole committee*, counting members who did not vote. Unlike confirmation, this test is *absolute*.#footnote[The spec line is "`define fast(B) as 2 · confirmation_score(A, Φ, s, B) ≥ |K_s|`", $K_s$ being the committee of slot $s$.]
- *Slow test:* the block was also confirmed by each of the previous $k - 1$ updates, so with this update it has been confirmed $k$ times in a row. $k$ is a parameter; we use $k = 4$. The slow test is for low participation, when support never reaches $n\/2$.

The lock written by the update of slot $s$ expires at $t_(s+k) + 5Delta$, so it lives $k$ slots. Each update writes a new lock with its own expiry, so a node usually holds about $k$ *live* (not yet expired) locks at once, normally on blocks of one chain. Locking a block also locks all of its ancestors.

Fast locks also feed the finality gadget. The target vote that a validator puts in its attestation (introduction of Section 2) is derived from the newest block that passed the fast test in the update of the round's first slot; the spec calls that block `fg_confirmed`. A target must never be reverted later, which is why it is derived from a fast lock. If no block passed the fast test in that update, the validator sends no attestation in that round, and the finality gadget waits for the next one. Since the support of a block includes the votes for its descendants, this happens only when fewer than $n\/2$ validators voted early for the confirmed chain.

With all validators voting, every confirmed block also passes the fast test: more than 32 of 64 means at least 32. The two tests part ways only when fewer than $n$ voters are counted. In particular, a block with *exactly* $n\/2 = 32$ early votes is both confirmed and fast-locked whenever fewer than 64 voters are counted, because 32 is then a strict majority of the voters as well. The fact that equality with $n\/2$ is enough ($>=$ instead of $>$) will be important later in the attack (3.3).

== How is a lock released?

In two ways.
- *Opposition.* At $t_s + 5Delta$, right before it casts its slot-$(s + 1)$ vote, a node checks each of its live locks against the votes of slot $s$. The *opponents* of a locked block are the validators whose resolved slot-$s$ vote names a block that *conflicts* with it, leaving out equivocators. Every vote the node holds counts; there is no early cutoff here. If the locked block has $n\/2$ opponents or more, the lock moves back to the newest ancestor that has fewer than $n\/2$ opponents.
- *Expiry*, after $k$ slots.

Opponents are not simply "everyone who did not support the block". A vote for an ancestor of the locked block does not oppose it, and neither does a missing vote or an equivocation. So a lock survives silence: if nobody votes against the block, the lock stays even with no support at all. And exactly $n\/2$ opponents is enough to move a lock back, even if the other $n\/2$ voted for the block.

== Recap: how votes are used

#table(columns: (1.15fr, 1.5fr, 1.6fr, 1.2fr),
  table.header([*rule*], [*which slot-$s$ votes*], [*threshold*], [*equivocators*]),
  [head walk (vote at $t_(s+1) + Delta$)], [received before the view freeze ($t_s + 3Delta$), plus those carried by slot-$(s + 1)$ blocks], [strict majority of all validators in the view; a current-slot block is always allowed; starts from the newest locked block (2.5)], [count for every block, and as voters],
  [unlocking ($t_s + 5Delta$)], [every resolved vote held], [lock moves back if $n\/2$ or more opponents], [ignored],
  [confirmation ($t_s + 6Delta$)], [support: resolved before $t_s + 2Delta$; voters: every vote held], [$2 dot "support" > "voters"$], [not support, but counted as voters],
  [fast lock], [the same support], [$2 dot "support" >= n$ (whole committee)], [not support],
  [slow lock], [the results of the previous $k - 1$ updates], [confirmed $k$ times in a row], [—],
)

== What does a lock do?

+ *It anchors the head walk.* In Goldilocks the head walk starts at the newest block the node has locked (if it holds no live lock, at a root block given by the finality gadget). A locked node therefore keeps voting on that block's branch, whatever the latest votes say. This is what makes a confirmation stick when the votes of one slot are missing or misleading.
+ *It vetoes conflicting confirmations*, as described in 2.1.
+ *It feeds finality*: targets come from fast locks (2.2).
+ *It protects the confirmed tip.* Plain Goldfish forgets everything after one slot. A lock keeps a confirmed block for $k$ slots, through periods where the network is not synchronous or where many validators are offline, which is why the confirmed tip can be shown to users.

#pagebreak()
= The attack <sec-attack>

== The safety claim

Under adversarial superminority ($< 1\/3$ stake) and through synchrony (or after a GST heal), Goldilocks is meant to guarantee that confirmations are not reverted.#footnote[*Spec* ("Goldilocks" FG-SA specification, 22 Oct 2026, opening section "The name"), of the confirmed tip: "it comes soon, and the locks protect it". *Design slides* (same authors): slide "No conflicting live locks after GST", "At least $n\/2$ of the committee voted for it. They oppose any conflicting lock, which is unlocked, even one from before GST"; slide "Fast locks make FG targets safe", "After GST a fast lock unlocks every conflicting lock, and every honest head keeps it". *Lean formalization* (`fradamt/simplified-dc-lean`): proved as `CleanHistoryClaim` and `CleanSafetyClaim`.] Once an honest node confirms a block $B$, it should not be orphaned unless asynchrony occurs. The design slides make this precise for a confirmed block that is also fast-locked.

*Claim.* Suppose that, under synchrony, an honest node X confirms a block $B$ in its update of slot $s$, at $t_s + 6Delta$, and fast-locks it, that is, $B$ has support $>= n\/2$ (2.2). Then every honest head extends $B$ from then on.

*Their argument.* The support of $B$ consists of validators whose slot-$s$ votes for $B$ (or a descendant) X received before $t_s + 2Delta$; there are at least $n\/2$ of them. Take any other honest node Y. Y casts its slot-$(s + 1)$ vote at $t_s + 5Delta$, and for its head to extend $B$ two things must hold.
+ *Y holds no lock that conflicts with $B$.* Y's head walk starts at its newest locked block (2.5), so a lock that conflicts with $B$ would keep its head off $B$. Under synchrony the supporters of $B$ reach Y by $t_s + 3Delta$, before Y's unlocking at $t_s + 5Delta$. Against a lock that conflicts with $B$ they are at least $n\/2$ opponents, so the lock is released (2.3). This step uses the fast lock.
+ *Y's head walk steps into $B$.* This needs $2 dot "support" > V_Y$, where $V_Y$ is the number of voters in Y's view. X's confirmation gives $2 dot "support" > V_X$. Every vote in Y's view at $t_s + 5Delta$ is relayed to X by $t_s + 6Delta$, so $V_Y <= V_X$. *Why is $V_X$ a superset of Y's view?* Y's view holds two kinds of slot-$s$ votes, and each reaches X in time by its own route:
  - the votes Y received before its view freeze at $t_s + 3Delta$. An honest node relays a vote as soon as it receives it, so Y forwarded them during slot $s$ and X has them by $t_s + 4Delta$;
  - the votes carried by the slot-$(s + 1)$ block, which the proposer collected until $t_s + 4Delta$. Nobody sends them on their own; they travel inside the block. Y holds the block by $t_s + 5Delta$ and relays it, so X receives it by $t_s + 6Delta$ and adds the votes it carries.
  This step uses the confirmation.

Hence every honest slot-$(s + 1)$ vote extends $B$. Only faulty validators can vote against $B$, and they are fewer than $n\/2$, so no honest lock on $B$ is released.

== Spotting the weakness

Step 1 holds by counting alone. Step 2 does not: with exactly $n\/2$ votes, $B$ is a majority for Y only if Y counts fewer than $n$ voters. It rests entirely on $V_Y <= V_X$: *no honest node may count a voter that X never counts*.

How can a vote reach a node? On the network, where honest nodes relay it within Δ, or *inside a block*: a block of slot $s + 1$ carries votes of slot $s$, and voters add them to their view (the view merge of 1.4). Honest nodes relay such a block as it is; nothing in the spec makes them also send the votes inside it as separate messages. So a vote inside a block counts only if the node accepts the block. The spec is explicit (spec §1.6): "the AC does not see a refused block. No handler then runs for an object that it carries". And a node refuses every block that does not extend its finalized block $F$.

#problem[
*What if* the adversary puts votes inside a block that some honest nodes accept and others refuse? Those votes are voters for the first group and *do not exist* for the second.

*When can that happen while the network is synchronous?* In the short window when a *new finalization* has reached some honest nodes and not others. A block on another branch that leaves the chain *below* the newly finalized block is accepted by the nodes that have not yet seen the finalization, and refused by those that have. The adversary can open that window itself: if it proposes the block that carries the round's attestations, which is the one that finalizes, it decides who sees it first.
]

== The finalization-hiding attack (spec, $>= n\/2$)

*The setting.* 64 validators. The adversary controls 21 of them (32.8%, under one third). The 43 honest validators sit on four nodes: node 0 hosts 11, node 1 hosts 11, node 2 hosts 10 and node 3 hosts 11. Nodes 0–2 (32 honest validators) are the group to fool; node 3 is the *holdout*. Honest messages and relays take 200 ms.

*The idea.* The adversary keeps some of its slot-$s$ votes off the network and puts them only inside a block that one honest node accepts and the others refuse (3.2). We call them the *hidden votes*: the accepting node counts them as voters, the others never see them.

*What the adversary needs.* The attacked block $B$ is the adversary's slot-$s$ block. The hidden votes are slot-$s$ votes, so they travel in a slot-$(s + 1)$ block. That block is refused only by nodes that have just learned of a new finalization, so the finalization must also arrive during slot $s + 1$. A finalization comes with the block that carries the round's attestations, the block of the round's third slot (the attestations are sent in the second). So the adversary must propose the second and the third slot of the same round: the second for $B$, the third to decide who sees the finalization first. With 21 of 64 validators this happens with probability $(21\/64)^2 approx 11%$ per round. In our example the adversary proposes slots 33 and 34, the second and third slots of round 4. Before the attack, every node has the block of slot 10 finalized and the block of slot 19 justified.

The adversary proposes all four blocks of the attack: B in its slot 33, and three different blocks, FB, Q and Z, in its slot 34. Proposing several blocks in one slot is a provable offence, but the spec has no rule that makes honest nodes discard a proposer's blocks once it is caught; they accept and relay each of them, and so does our simulator.
- *B*, its slot-33 block, the one that will be confirmed and then orphaned;
- *FB*, the *finalizing block*: a slot-34 child of B that carries round 4's attestations. Their target votes justify a new block (at slot 26) and their finality votes finalize the slot-19 block;
- *Q*, the *hiding block*: a slot-34 block that must be accepted by a node whose finalized block is still slot 10, and refused once slot 19 is finalized. So it must extend slot 10 but not slot 19; the adversary builds it on the slot-17 block, the parent of the slot-19 block. Q carries the 11 held-back slot-33 votes of the adversary, all naming W. A vote for W does not conflict with B, so these votes never oppose B; they arrive too late to count as support for anything; they only raise the count of voters;
- *Z*, the *rival block*: a slot-34 sibling of B.

W, B's parent, is the honest head when the attack starts: the block of slot 32.

#figure(
  fin-hide-tree(),
  caption: [The blocks of the attack. Grey: honest; red: the adversary's. $B$ is the adversary's slot-33 block; FB, $Z$ and $Q$ are three different blocks of its slot 34. $Q$ is dashed: nodes 0–2 refuse it.],
) <fig-finhide>

#table(columns: (auto, 1.1fr, 1.2fr, 1.2fr),
  table.header([*time*], [*adversary*], [*nodes 0–2*], [*node 3*]),
  [$t_(33)+Delta-1$ ms], [B (on W) to nodes 0 and 3, just before their vote], [0 votes B; 1 and 2 vote W (B reaches them by relay, after their vote)], [votes B. B has 22 honest votes],
  [$t_(33)+2Delta-1$ ms], [10 faulty votes for B, to all. The other 11 faulty validators send no vote], [B: 32 early votes; W: 21 (nodes 1 and 2)], [B: 32 early votes; W: 21 (nodes 1 and 2)],
  [$t_(34)+Delta-101$ ms], [FB to nodes 0–2], [slot 19 becomes their finalized block], [—],
  [$t_(34)+Delta-1$ ms], [Q (carrying the 11 held-back slot-33 votes) and Z, to node 3], [—], [accepts Q, since its finalized block is still slot 10, so the 11 votes count],
  [$t_(34)+Delta$ (vote)], [faulty validators vote Z], [vote FB: B has 32 of 53 voters, a majority], [B has 32 of 64 voters, not a majority; the walk stops at W, and node 3 votes *Z*, the current-slot child of W],
  [$t_(34)+Delta+99$ ms], [—], [—], [FB arrives by relay, after its vote],
  [$t_(34)+Delta+199$ ms], [—], [Q arrives by relay: *refused*, it does not extend slot 19], [—],
  [$t_(34)+2Delta$ (update of 33)], [—], [*B confirmed* ($2 dot 32 > 53$) and *fast-locked* ($2 dot 32 >= 64$); B is their confirmed tip], [confirms W],
  [$t_(35)$], [—], [—], [proposes slot 35 on W (B has no majority in its view)],
  [$t_(35)+Delta$ (unlocking)], [—], [Z has 32 votes, $n\/2$ opponents of B: *the locks move back to W*], [—],
  [afterwards], [—], [*B orphaned*: the slot-34 votes are 32 for B's branch and 32 for Z, so no honest walk goes past W, and everyone votes for the slot-35 block], [—],
)

*Why the votes add up.* In slot 33 every honest validator votes (43) and so do 10 faulty ones: every honest node holds 53 votes from the network, 32 of them for B (node 0's 11, node 3's 11 and the 10 faulty). The 11 held-back votes exist only inside Q. Node 3 accepts Q and counts 64 voters: B is not a majority in its head walk. Nodes 0–2 refuse Q and count 53: B is a majority, so it is confirmed, and since $2 dot 32 >= 64$ it passes the fast test and is locked.

*Why these times.* Two conditions fix when FB may reach nodes 0–2:
- *before Q does*, so that they have the new finalized block and refuse Q. Q reaches node 3 at $t_(34) + Delta - 1$ ms and nodes 0–2 by relay 200 ms later, at $Delta + 199$ ms;
- *late enough that its relay reaches node 3 after node 3's vote* at $t_(34) + Delta$. If node 3 had the new finalized block when it votes, Q would no longer be part of its tree, and the view merge would skip Q's votes.

With the relay delay $d$ = 200 ms, FB may reach nodes 0–2 at any time from $t_(34) + Delta - d$ up to just before $t_(34) + Delta - 1 + d$ ms; our adversary uses $Delta - 101$ ms, inside that window. (If FB reaches nodes 0–2 after their own vote, they vote for B instead of FB, which supports B just the same.) The window is about $2d$ wide, so it stays open whatever the honest relay delay is, down to a few milliseconds: we tested 1499 ms (Δ − 1 ms), 200, 50 and 3 ms.

*Why Q can carry slot-33 votes.* A block's slot is not tied to its parent's: Q is a slot-34 block whose parent is the block of slot 17. A slot-34 block carries slot-33 votes, and a vote does not have to name a block on the branch that carries it. The adversary signs these votes, since they belong to its own validators, and puts them only inside Q, never on the network.

#figure(
  table(columns: (auto, 1fr, 1fr, 1fr, 1fr),
    table.header([*node*], [*head*], [*confirmed tip*], [*newest locked block*], [*finalized block*]),
    [0, 1, 2], [FB (slot 34)], [*B* (slot 33)], [*B*, until slot 38], [slot 19],
    [3], [Z (slot 34)], [W (slot 32)], [W], [slot 19],
  ),
  caption: [State of each node at $t_(34) + 3Delta$, from the simulator run above. Nodes 0–2 show B as confirmed and hold a fast lock on it; one slot later both are gone.],
)


*How often it works.* We ran the attack on 120 random proposer schedules of 96 slots each. The adversary attacks at the first round from slot 32 on that gives it the two slots, so each run has eight chances at about 11% each; 74 runs got one. Every one of the 74 attacks succeeded, including those where one of the fooled nodes proposed the next slot:

#table(columns: (2.2fr, 1fr),
  table.header([*setting*], [*attacks that succeed*]),
  [fool node 0 only; honest relay delay 1499, 200, 50 or 3 ms], [74 of 74 each],
  [fool nodes 0–2, relay 200 ms], [74 of 74, all three nodes each time; B shown as confirmed for 4.5 s],
  [8 or 16 honest nodes instead of 4], [74 of 74 each],
)

Without the two slots nothing breaks; neither does anything in 1,300 runs of an adversary that acts at random (votes, blocks and delays chosen at random within the rules).

== How does it change with $> n\/2$?

Suppose the fast test is made strict: $2 dot "support" > n$. Then $2 dot "support" > V_Y$ for *every* honest node Y, whatever votes Y holds, because no node counts more than $n$ voters. A fast-locked block is a strict majority in every honest head walk, and every honest node keeps it. The fast-lock version of the attack fails: *0 of 74*.

The *confirmed tip* is still exposed. Nodes 0–2 still confirm B, because 32 out of 53 voters is a strict majority; they just do not lock it, so their head walk no longer starts at B. Their head then follows the slot-34 votes as they arrive. Node 3's 11 votes for Z are honest and arrive right after $t_(34) + Delta$, as the protocol says; the adversary can only choose when its own 21 votes for Z arrive. Once they do, B's branch and Z have 32 votes each, neither is a majority, and the head of nodes 0–2 falls back to W. From then on their confirmed tip is W. So:
- if the adversary's Z votes arrive before the update at $t_(34) + 2Delta$, the head is already at W when B is confirmed, and B is never shown;
- if they arrive later, B is the confirmed tip until they do, and is orphaned afterwards.

#table(columns: (2.2fr, 0.9fr, 1fr),
  table.header([*with $> n\/2$, 74 schedules with the two slots*], [*B shown, then orphaned*], [*shown as confirmed for*]),
  [adversary's Z votes sent at once], [0], [—],
  [adversary's Z votes just before the slot-34 view freeze ($t_(34) + 3Delta$)], [74], [1.5 s],
  [adversary's Z votes only to the slot-35 proposer, which carries them in its block], [48], [3–4.5 s],
)

The last variant fails in the 26 schedules where the slot-35 proposer is faulty, a case our adversary does not handle. So $> n\/2$ protects fast locks, and with them the finality gadget's targets, but not every confirmation. The threshold is not the root cause.

== The fix

The root cause is that whether a vote counts depends on the *block that carries it*, and whether that block is accepted depends on each node's finalized block. A vote is valid on its own, so it should count wherever it arrives. Two fixes do this, and each is enough on its own:
- *Count the votes of every well-formed block*, even when the block itself is refused because it does not extend the node's finalized block.
- *Re-send the votes carried by every accepted block* as separate messages, so that relay spreads them like any other vote. This is what the Lean formalization assumes (appendix).

Either way the 11 hidden votes reach nodes 0–2 before their update, and $V_Y <= V_X$ holds again. Both fixes stop *every* variant, with either threshold: 0 of 74, and 200 runs of the random adversary stay clean.

A tempting alternative is to apply a new finalization only at a fixed moment of the slot, for instance right after voting. That narrows the window but does not close it: the finalizing block can still reach some nodes just before that moment and others just after, they switch one slot apart, and the same split reappears.

#idea[
*Recommendation for the spec.* State the obligation explicitly: an honest node processes the votes carried by every block it receives, or relays them as separate messages, whether or not the block extends its finalized block. Separately, make the fast test strict ($> n\/2$): it protects the finality gadget's targets by counting alone, without relying on how votes travel.
]

#pagebreak()
#heading(numbering: none)[Summary]

#recap[
- *The setting.* The network is synchronous throughout. There are 64 validators and 21 of them are faulty (32.8%).
- *The attack.* When the adversary proposes the two slots around a round's attestations (about 11% of rounds), it makes up to three of four honest nodes *confirm and fast-lock* a block, which every honest node then orphans.
- *The threshold.* With the spec's fast test ($>= n\/2$) this breaks the claim that every honest head keeps a fast lock. With $> n\/2$ the fast-lock version is gone, but the confirmed tip can still be reverted.
- *The root cause.* The votes carried inside a block count only if the node accepts the block, and honest nodes can disagree on that for a moment around each new finalization.
- *The scope.* The attack works on the spec as written. The Lean proof assumes that honest nodes *re-send the votes carried by every block they accept*, which closes it. The spec never states that obligation (appendix).
]

#heading(numbering: none)[References]
#set text(size: 9pt)
- *Spec:* "Goldilocks" (FG-SA) specification, 22 Oct 2026, PDF linked from the decoupled-consensus hub, `hackmd.io/@benjaminion/decoupled-consensus-links`. Figure 8 holds the confirmation and lock rules; §1.6 the block-acceptance rule.
- *Slides:* "Goldilocks" design deck by the spec's authors, same hub; the safety claim quoted in 3.1 is on the slides "No conflicting live locks after GST" and "Fast locks make FG targets safe".
- *Lean formalization:* `github.com/fradamt/simplified-dc-lean`.
- *Simulator and explorer:* `goldilocks/` (`adversary.py`, `fin_hide_trace.py`, `build_explorer.sh`).
#set text(size: 10pt)

#pagebreak()
#heading(numbering: none)[Appendix: the Lean formalization and the spec disagree on relaying]

The Goldilocks specification comes with a machine-checked proof in the Lean language (`fradamt/simplified-dc-lean`). Among other things it proves that every honest head keeps a confirmation (statements `CleanHistoryClaim` and `CleanSafetyClaim`), which the finalization-hiding attack breaks in the spec. The Lean model refuses blocks and drops the votes they carry exactly like the spec (lemma `admitBlock_refused`: a refused block leaves the node's state unchanged, with "no carried vote"). The proof still goes through because of an assumption about the network.

*The assumption.* A theorem in Lean is proved under *premises*, assumptions it takes as given. Both of its network premises, `PartialSynchronyBy` and `HealthyPrefixDeliveryBy` (file `generic/AvailableChainGeneric/Statements/V2/Duty/DeliveryBy.lean`), contain this clause:

```lean
relay_accepted : ∀ v ∈ rho.honest, ∀ i o t, D.Run.acceptsAt E rho i v o t →
  ∀ w ∈ rho.honest, D.DeliveryDemand E rho v w o t (fun a => a + delayOf o) cut
```

Here `rho` is a run of the protocol, `v` and `w` are honest nodes, `o` is an object (a block, a vote, an attestation) and `t` a time. In words: *whatever an honest node accepts, every other honest node receives within the delay bound of that moment*. An object counts as accepted at the delivery where the node processes it for the first time (`acceptsAt`). And the definition of what a node processes on a delivery (`handlesS`, file `fgsa/AvailableChainFGSARun/Model/Protocol.lean`, lines 345–352) says that when a node accepts a block, it also processes *the votes the block carries*, each as an object of its own. So the votes inside an accepted block must be relayed separately. The authors' design notes say so in prose (`docs/internal/CONTRACT.md`): "Relay starts from honest acceptance; it does not require receiver acceptance."

*Consequence for the attack.* Node 3 accepts Q at $t_(34) + Delta - 1$ ms, so the 11 votes in Q must reach nodes 0–2 before $t_(34) + 2Delta - 1$ ms, which is before their update at $t_(34) + 2Delta$. They count 64 voters, B has 32, and B is not confirmed. Sending Q to node 3 later does not help the adversary: Q's votes matter only if node 3 counts them in its vote at $t_(34) + Delta$, which uses only what node 3 holds before that moment. With Q arriving at $Delta + 1$ ms, node 3 votes on B's branch and B is kept.

#table(columns: (1.6fr, 1.2fr, 1.2fr),
  table.header([*Q reaches node 3 at*], [*relay of whole messages only (spec text)*], [*Lean relay (carried votes re-sent)*]),
  [$t_(34) + Delta - 1$ ms], [74 of 74 attacks succeed], [0],
  [$t_(34) + Delta + 1$ ms], [0], [0],
  [$t_(34) + 2Delta - 1$ ms], [0], [0],
)

*What the spec says.* Spec §1.1 bounds the delivery of "blocks and AC messages". Spec §1.6 refuses blocks and drops the objects they carry. The only mention of relaying is in spec §3.3, about nodes rejoining after downtime: "the other nodes relayed them before the restart". Nothing says that a node must re-send the votes inside a block it accepts. Today's Ethereum clients do not do it either: the votes they find inside blocks (Ethereum's attestations) are not gossiped again on their own.

*Conclusion.* The attack is not a counterexample to the Lean theorems; it breaks one of their premises. It shows a gap between the spec and the assumption its proof rests on. The spec should either state the relay obligation, or count votes independently of whether their block is accepted. Whether real clients will meet the obligation is worth checking, for example in Prysm's `decoupled-consensus` branch.

#v(0.6em)
#text(size: 8.5pt, fill: luma(90))[*Reproduce* (from `goldilocks/`): `python fin_hide_trace.py --seed 13 --relay-ms 200 --group-a 0,1,2` prints the attack step by step (`--group-a` lists the nodes to fool). Add `--fast-strict` for the $> n\/2$ test and `--late-z proposer` for the delayed Z votes, or `--refused-votes` / `--relay-carried` for the two fixes. Batches: `python fuzz_batch.py --seeds 120 --out x.json --strategy fin_hide --group-a 0,1,2 --relay-ms 200`. Explorer: `bash build_explorer.sh`.]
