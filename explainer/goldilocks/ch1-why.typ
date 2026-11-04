#import "style.typ": *

= 1. Why Goldilocks: Moving Stabilization Into the Committee Layer

== 1.1 What Is Kept From Decoupled Consensus

Goldilocks keeps the basic split of decoupled consensus. Two voting processes run on two clocks:

- In every *slot*, a committee casts *Goldfish votes* on the head of the chain. These votes drive the *available chain* (AC): which block to build on, which block to vote for, which prefix to call confirmed.
- In every *round* of $R$ slots, every validator casts one *attestation*. Attestations drive the *finality gadget* (FG): justification and finalization, organized by *heights* rather than epochs.

A node exposes three tips that lie on one chain: the *finalized tip* (from the FG), the *confirmed tip* (from the AC), and the *head* (from the AC). Everything that a user or a later layer reads is one of these three blocks.

== 1.2 What the Stabilization Gadget Did, and Why It Is Gone

#block(breakable: false)[
#problem[
Pure Goldfish counts only the votes of the latest slot. It confirms fast, but it has no memory: if votes go missing for a few slots (a short asynchrony, or most validators asleep), a confirmed block is no longer protected, and the head can be pulled onto another branch. In the previous design, that resilience came from the *stabilization gadget* (SG): attestations carried a head vote of the whole validator set, and a round-level mechanism (the grades $G_0$/$G_1$ and the time-shifted quorum) produced a *stable root* from which the Goldfish walk had to start.
]

#idea[
Give the committee layer a short memory of its own. When the AC confirms a block it also *locks* it for $k$ slots. While the lock lives, the head walk starts at or below the locked block and no conflicting confirmation is accepted. A lock is renewed by later confirmations, moved back when at least half of a committee votes against it, and otherwise expires. Asynchrony resilience therefore costs one slot (with full participation) instead of one round, and the round layer keeps one job only: finality.
]
]

The name says what the locks are for. Goldfish counts only the votes of one slot and remembers too little. LMD-GHOST counts the latest vote of every validator with no age limit and remembers too much. A lock holds a confirmed block for $k$ slots and then expires, which is neither too short nor too long.

#figure(
  chapter-table(columns: (1.15fr, 1.6fr, 1.6fr),
    [], [*DC with the stabilization gadget*], [*Goldilocks*],
    [Latency to asynchrony resilience], [1 round], [1 slot (full participation), $k$ slots (low participation)],
    [Attestations], [FG + SG fields, one per round], [FG only, one per height: no progress means no new attestations],
    [Fork-choice inputs], [blocks, committee votes and attestations; old attestations must be processed], [blocks and the current committee votes only; network attestations are safe to drop],
    [Healing], [grades mechanism; extra latency in each round], [two unlocking triggers: expiry, or a majority against the lock],
    [Post-quantum available chain], [needs PQ attestations from the whole set], [needs PQ committee signatures only],
    [Low participation], [guarantees from the whole validator set], [guarantees from committees only],
  ),
  caption: [The comparison of the design slides (slide 6), unchanged.],
)

== 1.3 Two Consequences for the Network

#block(breakable: false)[
#idea[
*Attestations no longer influence the fork choice.* The FG turns blocks (and the attestations they carry) into the finality caches $F$, $J$, $h_max$ and a constrained block tree. The AC runs its fork choice on that tree with blocks and current Goldfish votes only. A node that keeps up with blocks and Goldfish votes never falls behind, even if it drops attestations from the network.
]
]

*When finality stalls, attestation traffic dies down by itself.* A validator attests to the *current height*. If the height does not advance there is no new target, so a validator whose vote already landed has nothing new to send. Bandwidth then goes to propagating and aggregating the existing votes. In the old design, a new full-set head vote was due every round regardless.

This second point also removes the issue we hit in the adversary study of the SG design. There, liveness after a partition depended on honest nodes re-gossiping equivocated full-set head votes, because those votes fed the fork choice through the grades. In Goldilocks the fork choice reads no attestations at all. Equivocation still matters for Goldfish votes, which Chapter 5 treats.

== 1.4 A Map of the Book

#chapter-table(columns: (0.45fr, 2fr),
  [Ch. 2], [Model: validators, time ($Delta$, slots of $4 Delta$, rounds), sleeping nodes, the three parts of a node and their interface.],
  [Ch. 3], [Finality gadget: attestations, the chain state, heights, justification, timeouts, finalization, the validator client.],
  [Ch. 4], [The FG frame: the finality caches, the fork-choice root, viable heads, the frontier contest.],
  [Ch. 5], [Goldfish on the frame: votes, resolution, the head walk, the proposal, the vote and its freeze.],
  [Ch. 6], [Confirmation and locks: the confirmation update, fast and slow locks, unlocking, expiry, the anchor, the block for the FG.],
  [Ch. 7], [Sleep, restart and joining.],
  [Ch. 8], [Healing after GST: the argument of the slides.],
  [Ch. 9], [Experiments with our executable model: partitions and sleep, what we measured.],
  [Ch. 10], [Open questions and next experiments.],
)

#recap[
Goldilocks = Goldfish + locks (the available chain) composed with a height-based finality gadget. Locks replace the stabilization gadget, so the committee layer protects its own confirmations for $k$ slots, attestations become pure finality votes, and the fork choice reads blocks and current committee votes only.
]
