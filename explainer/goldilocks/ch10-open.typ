#import "style.typ": *

= 10. Open Questions and Next Experiments

== 10.1 Questions About the Design

+ *Exact halves.* The fast test is $>= n\/2$, and a lock survives only with $< n\/2$ opponents. Two disjoint halves therefore fast-lock conflicting blocks before GST, and both lose everything at the heal (§9.3). Is "$>=$" intended, so that an even split resolves to neither side? With committee sampling (1024 seats), exact halves are rare but not impossible.
+ *One slot decides a round.* `fg_confirmed` comes only from the update of slot $r R$ (§6.6). Why not the deepest live fast lock in the viable tree, or the latest update that produced a result? With the current rule, one bad slot at each round start can stall finality indefinitely. A timeout does not help, because a validator without `fg_confirmed` does not attest at all.
+ *The value of $k$.* The upstream presets fix no lock length. A small $k$ gives faster slow locks and faster draining (healing in $2L$). A large $k$ gives longer protection under low participation. Which $k$ is intended, and does it relate to $R$?
+ *Late votes count against.* Confirmation counts every vote as a participant but only early votes as support. A burst of late votes (or late blocks, which delay resolution) can turn a slot's confirmation into $bot$. Is this the intended trade-off against counting stale support?
+ *Slow locks under a partition.* A minority slow-locks its branch after $k$ confirmations (§9.3). This is harmless after GST, but a user of the minority sees "confirmed and locked" on blocks that the majority will reorg. Should the user-facing confirmation distinguish fast from slow?
+ *Healing proof.* The argument of Chapter 8 is not written down beyond the slides. In particular: the overlap of slow-lock windows across GST, and why an unfollowed lock cannot be renewed.

== 10.2 What the Simulator Does Not Yet Do

- *Byzantine validators.* No equivocating Goldfish votes, no withheld or equivocating proposals, no adversarial attestations. Equivocators count for every block in the head walk but are excluded from confirmation support and from opponents. That asymmetry is the first thing to probe.
- *Committee sampling.* $K_s = V$ here; upstream samples 1024 seats per slot by effective balance.
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
