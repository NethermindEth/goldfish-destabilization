#import "style.typ": *

= 4. The FG Frame: Constraining the Fork Choice by Height

#block(breakable: false)[
#problem[
The AC chooses heads by counting Goldfish votes, and Goldfish votes know nothing about finality. Left alone, the AC could keep a head on a branch that the FG has already left behind (two heights stale), or flip between branches in a way that undoes the FG's progress. We need the FG to constrain where heads may be, and the constraint must not itself cause reorgs whenever new FG evidence appears.
]

#idea[
The FG gives the AC a *frame*: the tree of blocks that extend $F$, a *fork-choice root* that every head must extend, and the set of *viable heads* where a head walk may stop. The root and the viable heights follow from the caches $F$, $J$, $h_j$, $h_max$. A *contest* rule makes sure that a late-revealed justification changes the frame at most once more per height.
]
]

== 4.1 The Frame

#formula-card[
Let $Sigma\.h_max$ be the greatest accepted state height and $(Sigma\.J, Sigma\.h_j)$ the latest justification #specref[§2.2, F3.22–43].
- *Contest:* $h_max = h_j + 1$ and some accepted block extending $F$ with state height $h_max$ does *not* extend $J$. The test reads the node's whole tree, never a voter's tree.
- *Fork-choice root:* $J$ if $h_max = h_j + 1$ and there is no contest; otherwise $F$.
- *Head height floor:* $h_max$ in a contest; otherwise $h_max - 1$.
- *Viable heads:* blocks at or above the root whose state height is at least the floor.
- *Viable tree* of a set of blocks: the blocks of the set that extend the root and have a descendant in the set that is a viable head.
- $F$ may advance only to a block that has a viable descendant.
]

Heights at or below $h_max - 2$ are pruned: no head may stop there. A branch that is two heights behind the frontier is no longer a candidate.

#fig("frame.svg")[The three cases of the frame for one height, after the slides 24–25. The dashed red box marks the fork-choice root, ✓ marks the viable heads. (1) No justification at $h_max - 1$ yet: the root is $F$ and both branches are viable. (2) $J$ is revealed at $h_max - 1$: it becomes the root, and branches that do not go through $J$ drop out. (3) A block at $h_max$ that does not extend $J$ contests it: the root falls back to $F$, but the floor rises to $h_max$, so only branches already at $h_max$ are viable.]

== 4.2 Why a Late Justification Cannot Keep Pulling the Head

When a justification $J$ at $h_max - 1$ appears late, it becomes the root and pulls every head through it. That is a single change, because after it is revealed that $J$ is *spent*. If the node's own branch is already at $h_max$ without $J$, the branch contests $J$: the root returns to $F$, and the higher floor keeps the node's branch viable. Revealing $J$ then causes no reorg.

#formula-card[
*Two frame changes per height at most.* Each height has at most one justification $J$, and a contest never goes away, because accepted blocks are never removed. The frame of a height therefore moves through at most three states (before $J$ → $J$ revealed → contest), and in each of them, if nothing else changes, the height rises. Every height rises within three attempts (slide 25).
]

== 4.3 Why a Contest Raises the Floor

#example[
Take $n = 9$, so $q = 6$. Four validators made a finality vote for $J$ at height $h_max - 1$. Their records now hold a finality lock at $h_max - 1$ on $J$, so by the client rule of §3.5 they sign nothing else at that height. If, in a contest, the floor stayed at $h_max - 1$, the head could sit on a block $Z$ at $h_max - 1$ that still needs a quorum *at* $h_max - 1$. Only the other 5 validators can vote for $Z$ there, and $5 < 6$: stuck. With the floor at $h_max$, a branch is viable only once it is already at $h_max$, so it needs no more votes at $h_max - 1$, and the finality votes for $J$ block nothing (slide 29).
]

== 4.4 What the Frame Gives the FG

The frame also explains the AC #sym.arrow FG direction (Chapter 6): `fg_confirmed` must be in the viable tree, and the head must extend it. The height pair of an attestation is read from the state of `fg_confirmed`, which is a *fast-locked* block. That gives the healing property of Chapter 8: after GST, a fast lock unlocks every conflicting lock and every honest head keeps it, so a target read from its state is never dropped later and cannot set up an FG reorg.

#recap[
The frame is $Phi = ("tree", "fc_root", "viable_heads")$. The root is $J$ when the frontier is one height above the latest justification and nobody contests it; otherwise it is $F$. The floor is $h_max - 1$, or $h_max$ in a contest. Heads must extend the root and stop at heights above the floor. A height changes frame at most twice, so it rises within three attempts.
]
