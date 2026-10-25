#import "style.typ": *

= 10. Open Questions and Next Experiments

== 10.1 Questions About the Design

+ *Exact halves.* The fast test is $>= n\/2$, and a lock survives only with $< n\/2$ opponents. Two disjoint halves therefore fast-lock conflicting blocks before GST, and both lose everything at the heal (§9.3). The non-strict threshold is in every artefact: the draft EIP ("at least half of the full committee"), Prysm (`2*score >= committeeSize`) and the Lean model (`releaseThreshold = (n+1)/2`). Mikhail's post-Cambridge notes plan to take the next FG target from `fg_confirmed` because a fast lock "implies support from a majority of the Goldfish committee". The 50/50 run is a counterexample to that premise. His proposed 60% threshold for VRF-sampled committees of target size 512 would remove the tie.
+ *One slot decides a round.* `fg_confirmed` comes only from the update of slot $r R$ (§6.6). The draft EIP makes this normative: "When no qualifying source exists, a validator MUST NOT produce a finality attestation". Prysm captures the source once per round. Why not the deepest live fast lock in the viable tree, or the latest update that produced a result? With the current rule, one bad slot at each round start can stall finality indefinitely. The consensus-specs branch staggers attestation committees over the slots of a round. If each committee read its own slot's update, a bad slot would cost only about $1\/R$ of the round. That source rule is still a TODO there.
+ *The value of $k$.* No upstream document fixes the lock length. Mikhail lists "Locking period, Threshold" as open, the EIP leaves "timing and lock parameters" TBD, and the Lean model requires only $k >= 2$. The Prysm devnet uses $k = 2$ with $R = 4$. Both findings above also hold at $k = 2, R = 4$ in our simulator. The Lean healing bounds are $2L + G + 8 Delta$ and, when $k <= 2R + 1$, a one-lock bound $L + Gamma + 10 Delta$, with $L = (4k - 1) Delta$. Their proofs assume $delta_t = 2R$, while Prysm and consensus-specs use $delta_t = R$.
+ *Late votes count against.* Confirmation counts every vote as a participant but only early votes as support. A burst of late votes (or late blocks, which delay resolution) can turn a slot's confirmation into $bot$. Is this the intended trade-off against counting stale support?
+ *Slow locks under a partition.* A minority slow-locks its branch after $k$ confirmations (§9.3). This is harmless after GST, but a user of the minority sees "confirmed and locked" on blocks that the majority will reorg. Should the user-facing confirmation distinguish fast from slow?
+ *Healing proof.* The argument of Chapter 8 is not written down beyond the slides. In particular: the overlap of slow-lock windows across GST, and why an unfollowed lock cannot be renewed.

== 10.2 What the Simulator Does Not Yet Do

- *Byzantine validators.* No equivocating Goldfish votes, no withheld or equivocating proposals, no adversarial attestations. Equivocators count for every block in the head walk but are excluded from confirmation support and from opponents. That asymmetry is the first thing to probe.
- *Committee sampling.* $K_s = V$ here. The EIP says about 512 seats per slot, consensus-specs 1024, sampled by effective balance; Prysm, like us, uses the whole set. "Sampling also sets the committee size used for locking thresholds" (Anders' incentives sketch).
- *Realistic delays.* We use a fixed 200 ms latency. The dc-networking measurements show AC-vote p99 of about 0.5–1 s in healthy runs, but 4.5 s when an FG round bursts at once, and 15% of AC votes later than 3 s on a Prysm-on-Shadow run. Gossipsub queues per peer without priorities, so AC delivery is coupled to FG and payload load.
- *Attestation committees and the inactivity weight* of the upstream FG.
- *One validator per node.* Today a node's validators share one view.

== 10.3 Next Experiments

#chapter-table(columns: (1.1fr, 2.4fr),
  [*Experiment*], [*What it tests*],
  [Slide-11 scenario], [Build the worst case of the $2L$ bound on purpose: a lock formed across GST that the post-GST Goldfish votes do not follow (votes split 5/3). Measure the actual healing time against GST $+ 2L + G$.],
  [Round-start attacks], [An adversary that delays or splits slot $r R$ in every round: does finality stall for as long as it keeps doing so? (§9.4)],
  [Equivocating committee members], [$f < n\/3$ equivocating Goldfish voters across a partition. They count for every block in the walk; can they keep two honest groups locked apart after GST, or block the fast test?],
  [Late $J$ revelation], [Withhold a justifying block and release it at the worst moment; check that each height changes frame at most twice (§4.2).],
  [Proposer equivocation at a round start], [Two proposals in slot $r R$ to two halves: interaction with `fg_confirmed` and view merge.],
  [Parameter sweeps], [$k in {2, 4, 8}$; $Delta_F > Delta$; jitter close to $Delta$; committee sampling.],
)

#recap[
The protocol is simpler than the SG design, and so far it behaves as specified. The experiments raise two concrete design questions: exact-half fast locks, and the round's dependence on slot $r R$. They also point to where the next experiments should go: adversarial votes and adversarial timing aimed at the $2L$ bound and at the FG interface.
]
