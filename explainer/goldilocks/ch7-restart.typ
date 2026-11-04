#import "style.typ": *

= 7. Sleep, Restart and Joining

#block(breakable: false)[
#problem[
A node that slept, or crashed, has lost the votes it received before it went down. The network does not deliver them again, because the other nodes relayed them already. If such a node voted or confirmed right after waking, it would read a different vote set than the other honest nodes and could break the agreement arguments of Chapters 5 and 6.
]
#idea[
On wake, *restart*: keep what must persist (the FG state, the anti-slashing record, the locks, the confirmed record) and reset the rest of the AC state. Then take no action that reads votes until enough time has passed that every vote such an action would read arrived after the restart: the node must be *joined*.
]
]

#formula-card[
*Restart at time $t$* #specref[§1.3, §3.2, F7.50]: keep $Sigma$, $Lambda$, the clock, $A\."locks"$ and $A\."latest_confirmed"$. Reset every other part of $A$ to its initial value, and set $A\."restart_time" <- t$. Then call `ac_on_block` at time $t$ for every block of $Phi\."tree"$ except genesis, in parent order. The blocks get stamp $t$, and the votes they carry enter the pools with stamp $t$. A lock written before the restart keeps its deadline, so sleeping does not extend it.

*Joined* at time $t$: $A\."restart_time" <= t_("slot"(t) - 1)$, meaning awake with no restart since the start of the previous slot. Only a joined node unlocks, votes, proposes, runs the confirmation update or gives a block to the FG. An update while not joined saves $bot$ for its slot and writes nothing else.
]

A node does not accept a slot-$j$ vote before $t_j$, and a block carries slot-$j$ votes only from slot $j + 1$. So a node joined at $t$ has erased no vote of slot $"slot"(t) - 1$ or later, and every action of the tick reads only such votes. After GST, a joined node also holds every honest slot-$(s - 1)$ vote, and every block sent while it slept, by $t_(s-1) + 2 Delta$, before the freeze. A node that wakes at $t_j$ is joined from $t_(j+1)$. A node that wakes strictly inside $(t_j, t_(j+1))$ is joined from $t_(j+2)$.

#observed[
*Waking at a round boundary costs a round of attestations.* In our 25%-awake run, the sleepers woke at $t_(64)$, the first slot of round 8. They are joined from $t_(65)$, so they did not vote in slot 64, and slot 64 had only the 16 votes of the node that stayed awake. The update of slot 64 confirmed (16 is a majority of the 16 participants) but could not fast-lock ($2 dot 16 < 64$). The action time $a_8$ reads exactly that update, so `fg_confirmed` was $bot$ on every node and *nobody* attested in round 8. Finality resumed one round later than the wake. The root cause is general: the attestations of a whole round depend on the fast test of a single slot, $r R$ (§6.6 and Chapter 9).
]

#recap[
Restart keeps the FG state, the record, the locks and the confirmed record, and clears votes and timestamps. A restarted node acts again only from the second slot boundary after waking (the first, if it woke exactly at one), so it never reads a vote set that the other honest nodes do not share.
]
