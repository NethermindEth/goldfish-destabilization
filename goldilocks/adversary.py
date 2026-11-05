"""A Byzantine adversary for the Goldilocks model, under synchrony.

f of the n validators are faulty, and one adversary runs them. It is rushing: it sees every
honest message the moment it is sent. It can sign any number of Goldfish votes, propose any
blocks at its own proposer slots, and send any attestations, and it chooses when each honest
node receives each of its objects.

Synchrony (section 1.1) binds it in two ways, and the driver enforces both:
  - every honest message reaches every honest node within the bound (Δ for blocks and votes,
    Δ_F for attestations); the adversary may pick each delay in [1, bound - 1] ms;
  - relay: when an honest node receives an adversary object at τ, every other honest node has
    it by τ + relay_ms (relay_ms = bound - 1 by default, the latest the bound allows). Two
    distinct votes of one validator are two objects, so an equivocating vote is relayed like
    any other ("faithful", the spec's model: "the other nodes relayed them", section 3.3).

Options that leave the spec's model, for the assumption study only:
  --relay first-seen   today's gossip rule (phase0 p2p-interface: IGNORE a second attestation
                       of a validator; IGNORE a block that is not the first of its proposer
                       for its slot): a node drops, and does not forward, a second vote of v
                       for slot s or a second block of proposer p for slot s;
  --skew i:ms,...      clock offsets: node i runs its tick at local public time τ, which is real
                       time τ - ms. Delays are real; stamps are local.

The honest nodes are World nodes (model.py, unchanged): validators [0, n - f) are spread over
them, and [n - f, n) are the adversary's.

Run:  python adversary.py --f 21 --strategy fuzz --seed 3
"""

import argparse
import heapq
import json
import random
import time
from collections import defaultdict

from model import BLOCKS, DEPTH, GEN, INF, STATE, Att, Node, Params, Vote, chain_state, conflicts, make_block, \
    prec, valid_attestation
from sim import Network, Tracker, World, assign, message_event


def okey(kind, obj):
    return obj.root if kind == "block" else obj


class AdvNetwork(Network):
    def __init__(self, P, latency_ms, seed, relay="faithful", relay_ms=None, skew=None):
        super().__init__(latency_ms, 0, seed)
        self.P = P
        self.relay = relay
        self.relay_ms = relay_ms  # None: bound - 1 per kind
        self.skew = skew or {}
        self.honest_delay = None  # fn(src, dst, kind, payload, now) -> ms, set by the adversary
        self.sent_log = []  # every honest send: (local time, src, kind, payload)
        self.got = {}  # (kind, key, dst) -> earliest local arrival already scheduled (adversary objects)
        self.dropped = 0  # first-seen mode: equivocating votes ignored by a node
        self.windows = []  # [(start_ms, end_ms, {node: group})]: honest traffic across the cut waits for the heal

    def held_until(self, src, dst, real_now):
        """End of the cut that separates src and dst at real time real_now, or None."""
        for a, b, g in self.windows:
            if a <= real_now < b and g[src] != g[dst]:
                return b
        return None

    def bound(self, kind):
        return self.P.delta_f if kind == "att" else self.P.delta

    def local(self, real, dst):
        return real + self.skew.get(dst, 0)

    def real(self, local, node):
        return local - self.skew.get(node, 0)

    def broadcast(self, src, now, kind, payload, nodes):
        self.sent[kind] += 1
        self.sent_log.append((now, src, kind, payload))
        t0 = self.real(now, src)
        for dst in nodes:
            if dst.id == src:
                continue
            d = self.latency_ms if self.honest_delay is None else self.honest_delay(src, dst.id, kind, payload, now)
            d = min(max(1, d), self.bound(kind) - 1)
            end = self.held_until(src, dst.id, t0)
            at = self.local(max(t0, end) + d if end is not None else t0 + d, dst.id)
            heapq.heappush(self.queue, (at, next(self.seq), dst.id, kind, payload, "honest"))
            if self.events is not None:
                self.events.append(message_event(now, at, src, dst.id, kind, payload, end is not None))

    def adv_send(self, kind, obj, arrivals):
        """Deliver one adversary object: arrivals maps node -> real arrival time (ms)."""
        self.sent["adv_" + kind] += 1
        for dst, real in arrivals.items():
            self._schedule(kind, obj, dst, self.local(real, dst), "adv")

    def _schedule(self, kind, obj, dst, at, origin, sent=None, held=False):
        k = (kind, okey(kind, obj), dst)
        if self.got.get(k, INF) <= at:
            return
        self.got[k] = at
        payload = obj if kind == "block" else (obj,)
        heapq.heappush(self.queue, (at, next(self.seq), dst, kind, payload, origin))
        if self.events is not None:  # the adversary is drawn as node -1; a relay starts at its relaying node
            src = -1 if origin == "adv" else origin
            self.events.append(message_event(at if sent is None else sent, at, src, dst, kind, payload, held))

    def relay_from(self, src, at, kind, obj, nodes):
        """src received an adversary object at local time `at`: every other node has it by then
        + relay_ms (real)."""
        d = self.bound(kind) - 1 if self.relay_ms is None else min(self.relay_ms, self.bound(kind) - 1)
        r0 = self.real(at, src)
        for n in nodes:
            if n.id != src:
                end = self.held_until(src, n.id, r0)
                self._schedule(kind, obj, n.id, self.local((r0 if end is None else end) + d, n.id), src, sent=at,
                               held=end is not None)


class AdvWorld(World):
    def __init__(self, P, f, nodes=4, shares=None, latency_ms=200, relay="faithful", relay_ms=None, skew=None):
        P.check()
        self.P = P
        self.log_events = []
        self.t = 0
        self.net = AdvNetwork(P, latency_ms, P.seed, relay, relay_ms, skew)
        self.nodes = [Node(i, P, vals, log=self._log) for i, vals in enumerate(assign(P.n - f, nodes, shares))]
        self.node_of = {v: n.id for n in self.nodes for v in n.validators}
        self.adv_vals = list(range(P.n - f, P.n))
        self.sleep, self.woken = {}, set()
        self.adv = None
        self.hold_early = bool(skew)
        self.relay_carried = False  # --relay-carried: Lean `relay_accepted` + `handlesS`
        self.seen_blocks = {n.id: {} for n in self.nodes}  # first-seen: (proposer, slot) -> first root
        self.conf_seen = {n.id: {} for n in self.nodes}
        self.conf_tl = {n.id: [] for n in self.nodes}  # (public time, confirmed tip) at every change  # node -> {block: first public time it was the confirmed tip}

    def _dup_vote(self, node, x):
        return any(y.v == x.v and y != x for y in node.ac.gf_votes.get(x.s, ()))

    def step(self, t):
        for at, _, dst, kind, payload, origin in self.net.pop_before(t):
            node = self.nodes[dst]
            self.wake_due(at)
            wake = self.wake_time(dst, at)
            if wake is not None:  # asleep: delivered after the next wake (section 1.1)
                heapq.heappush(self.net.queue, (wake + self.net.latency_ms, next(self.net.seq), dst, kind, payload, origin))
                continue
            self.t = at
            if self.hold_early:
                # Clients accept gossip up to MAXIMUM_GOSSIP_CLOCK_DISPARITY early and hold it to its
                # slot (phase0 p2p-interface); the spec would drop it (perfect clocks never send one)
                slot = payload.slot if kind == "block" else (payload[0].s if kind == "vote" else None)
                if slot is not None and slot > self.P.slot(at):
                    heapq.heappush(self.net.queue, (self.P.t(slot), next(self.net.seq), dst, kind, payload, origin))
                    continue
            if kind == "block":
                key = (payload.proposer, payload.slot)
                if origin != "honest" and self.net.relay == "first-seen" and self.seen_blocks[dst].get(key, payload.root) != payload.root:
                    self.net.dropped += 1  # IGNORE: not the first block of this proposer for this slot
                    continue
                self.seen_blocks[dst].setdefault(key, payload.root)
                accepted = node.on_block(payload, at)
                obj = payload
                if accepted and self.relay_carried:  # the Lean's reading: relay what you accepted, also
                    for x in payload.votes:           # the votes a block carries, as standalone votes
                        self.net.relay_from(dst, at, "vote", x, self.nodes)
            elif kind == "vote":
                obj = payload[0]
                for x in payload:
                    if origin != "honest" and self.net.relay == "first-seen" and self._dup_vote(node, x):
                        self.net.dropped += 1
                        obj = None  # ignored: not processed, not forwarded
                        continue
                    node.on_vote(x, at)
            else:
                obj = payload[0]
                for a in payload:
                    node.on_attestation(a)
            if origin != "honest" and obj is not None:
                self.net.relay_from(dst, at, kind, obj, self.nodes)
        self.wake_due(t)
        self.t = t
        for node in self.nodes:
            if self.wake_time(node.id, t) is not None:
                continue
            for kind, payload in node.on_tick(t):
                self.net.broadcast(node.id, t, kind, payload, self.nodes)
        if self.adv is not None:
            self.adv.act(t)
        for node in self.nodes:  # the user-facing confirmed tip at every public time
            if self.wake_time(node.id, t) is None:
                c = node.confirmed(t)
                if c != self.conf_seen[node.id].get("last"):
                    self.conf_seen[node.id]["last"] = c
                    self.conf_seen[node.id].setdefault(c, t)
                    self.conf_tl[node.id].append((t, c))


# ------------------------------------------------------------------------ adversaries


class Adversary:
    """Base: abstains. Helpers to sign and deliver objects."""

    name = "passive"

    def __init__(self, world, rng, groups):
        self.w, self.P, self.rng = world, world.P, rng
        self.vals = world.adv_vals
        self.valset = set(self.vals)
        self.groups = groups  # [[node ids of group A], [group B]]
        self.cast = []  # (slot, validator, head) of every vote signed
        self.proposed = []  # (slot, root)
        self.notes = []

    # --- schedule
    def act(self, t):
        P = self.P
        s = P.slot(t)
        off = t - P.t(s)
        if off == 0 and s > 0:
            self.at_slot_start(s, t)
        if off == P.delta:
            self.at_vote(s, t)
        if off == 2 * P.delta:
            self.at_cutoff(s, t)
        if off == 3 * P.delta:
            self.at_freeze(s, t)
        if t == P.action_time(P.round(s)):
            self.at_action(P.round(s), t)

    def at_slot_start(self, s, t):
        pass

    def at_vote(self, s, t):
        pass

    def at_cutoff(self, s, t):
        pass

    def at_freeze(self, s, t):
        pass

    def at_action(self, r, t):
        pass

    # --- helpers
    def mine(self, s):
        return self.P.proposer(s) in self.valset

    def all_nodes(self):
        return [n.id for n in self.w.nodes]

    def at(self, nodes, local):
        """Arrivals at node-local time `local` on each node's own clock (real = local - skew)."""
        return {i: local - self.w.net.skew.get(i, 0) for i in nodes}

    def vote(self, v, s, H, arrivals):
        x = Vote(v, s, H)
        self.cast.append((s, v, H))
        self.w.net.adv_send("vote", x, arrivals)
        return x

    def block(self, s, parent, votes=(), support=(), atts=None):
        """A block of the adversary's slot s, or None when the state transition refuses it."""
        if atts is None:
            atts = self.valid_atts(parent)
        try:
            B = make_block(s, parent, self.P.proposer(s), tuple(atts), tuple(votes), tuple(support))
            chain_state(B, self.P)
        except AssertionError:
            return None
        self.proposed.append((s, B.root))
        return B

    def send_block(self, B, arrivals):
        self.w.net.adv_send("block", B, arrivals)

    def pool(self):
        seen, out = set(), []
        for n in self.w.nodes:
            for a in n.fg.pool:
                if a not in seen:
                    seen.add(a)
                    out.append(a)
        return out

    def valid_atts(self, parent, extra=()):
        from model import INCL
        sigma, incl = STATE[parent], INCL[parent]
        return [a for a in list(extra) + self.pool() if a not in incl and valid_attestation(sigma, a)]

    def honest_votes(self, s):
        out = []
        for _, _, kind, payload in self.w.net.sent_log:
            if kind == "vote":
                out += [x for x in payload if x.s == s]
        return out

    def head(self, i=0, t=None):
        return self.w.nodes[i].head(self.w.t if t is None else t)

    def tree(self):
        return set().union(*(n.fg.T for n in self.w.nodes))


class Equivocate(Adversary):
    """Every slot, every faulty validator votes two conflicting heads, one to each group,
    early; at its own slots it proposes two blocks, one to each group, just before the vote."""

    name = "equiv"
    pair = None

    def at_slot_start(self, s, t):
        P = self.P
        A, B = self.groups
        if self.mine(s):
            H = self.head(A[0], t)
            par = BLOCKS[H].parent if H != GEN else GEN
            b1 = self.block(s, H)
            b2 = self.block(s, par if par is not None else H, atts=[])
            if b1 and b2 and b1.root != b2.root:
                self.send_block(b1, self.at(A, t + P.delta - 1))
                self.send_block(b2, self.at(B, t + P.delta - 1))
                self.pair = (b1.root, b2.root)
                return
        self.pair = None

    def at_vote(self, s, t):
        A, B = self.groups
        if self.pair:
            h1, h2 = self.pair
        else:
            h1 = self.head(A[0], t)
            par = BLOCKS[h1].parent
            h2 = par if par is not None else h1
        for v in self.vals:
            self.vote(v, s, h1, self.at(A, t + 1))
            if h2 != h1:
                self.vote(v, s, h2, self.at(B, t + 1))


class Split(Adversary):
    """The PR4 timing attack moved to Goldilocks. At its own slot s the adversary proposes P and
    shows it to group A just before the vote and to group B only through relay, so A votes P and
    B votes P's parent. Its own votes for P reach A just before the support cutoff and B only
    through relay, after it. A then counts |A| + f early votes for P, B only |A|."""

    name = "split"

    def at_slot_start(self, s, t):
        self.P_ = None
        if not self.mine(s):
            return
        A, _ = self.groups
        H = self.head(A[0], t)
        B_ = self.block(s, H)
        if B_ is None:
            return
        self.P_ = B_.root
        self.send_block(B_, self.at(A, t + self.P.delta - 1))

    def at_vote(self, s, t):
        if not getattr(self, "P_", None):
            return
        A, _ = self.groups
        for v in self.vals:
            self.vote(v, s, self.P_, self.at(A, t + self.P.delta - 1))  # just before t_s + 2Δ


class _TwoSlots(Adversary):
    """Base of the clock-skew attacks: they need the proposer slots s and s + 1 (the first such
    pair from --attack-from on, at a round start when --round-start). Group A = [X], the node
    that locks; group B = the others."""

    round_start = False
    attack_from = 16

    def target(self, s):
        P = self.P
        ok = s >= self.attack_from and self.mine(s) and self.mine(s + 1) and (not self.round_start or s % P.R == 0)
        if ok and not hasattr(self, "s0"):
            self.s0 = s
        return getattr(self, "s0", None)


class SkewFast(_TwoSlots):
    """Clock skew, X ahead of the others by ε. Exactly n/2 early support for the adversary's
    block B at slot s, from honest and faulty votes, while w faulty validators keep their slot-s
    votes back. At s + 1 the adversary proposes Q, a sibling of B that carries those w votes,
    and shows it to the others just before their vote: for them B has n/2 of n voters and is not
    eligible, so they vote Q. X gets Q by relay Δ later in real time, which on its clock is after
    its update at t_s + 6Δ: X counts n - w voters, confirms B and fast-locks it (≥ n/2). The next
    unlocking moves X's lock back, and every honest head leaves B."""

    name = "skew_fast"

    def at_slot_start(self, s, t):
        P = self.P
        X, others = self.groups
        s0 = self.target(s)
        if s == s0:
            self.W = self.head(others[0], t)
            self.B = self.block(s, self.W)
            # honest supporters of B: the nodes that see B before the vote
            self.voters_B = [i for i in self.all_nodes() if i in X or i == others[0]]
            a = sum(len(self.w.nodes[i].validators) for i in self.voters_B)
            self.f1 = max(0, P.n // 2 - a)  # faulty early votes for B, to reach exactly n/2
            assert self.f1 < len(self.vals), "not enough faulty validators for an exact half"
            self.send_block(self.B, self.at(self.voters_B, t + P.delta - 1))
            self.notes.append(f"slot {s}: B={self.B.root[:6]} on W={self.W[:6]}; honest for B={a}, faulty f1={self.f1}, "
                              f"withheld w={len(self.vals) - self.f1}")
        elif s0 is not None and s == s0 + 1:
            withheld = [Vote(v, s0, self.W) for v in self.vals[self.f1:]]
            prev = self.honest_votes(s0) + [Vote(v, s0, self.B.root) for v in self.vals[:self.f1]] + withheld
            support = [x for x in prev if x.H in self.w.nodes[others[0]].fg.T]
            Q = self.block(s, self.W, prev, support)
            self.Q = Q
            self.send_block(Q, self.at(others, t + P.delta - 1))  # just before the others' vote

    def at_vote(self, s, t):
        P = self.P
        s0 = getattr(self, "s0", None)
        if s == s0:
            for v in self.vals[:self.f1]:
                self.vote(v, s, self.B.root, self.at(self.all_nodes(), t + P.delta - 1))  # early everywhere
        elif s0 is not None and s == s0 + 1:
            for v in self.vals:
                self.vote(v, s, self.Q.root, self.at(self.all_nodes(), t + 1))


class SkewFreeze(_TwoSlots):
    """Clock skew, the others ahead of X by ε. The adversary's block B at slot s gets a honest
    votes and f1 faulty votes, sent to X just before its support cutoff; relay brings them to
    the others Δ later in real time, which on their clocks is after their freeze t_s + 3Δ. The
    other faulty validators vote B's parent W, early everywhere. X sees a + f1 > n/2 support of
    n voters: it confirms B and fast-locks it, also with the strict test. The others' frozen view
    lacks the f1 votes, so B is not eligible for them, and they vote the adversary's slot-(s + 1)
    proposal Q, a child of W whose vote list leaves out the f1 votes."""

    name = "skew_freeze"

    def at_slot_start(self, s, t):
        P = self.P
        X, others = self.groups
        s0 = self.target(s)
        if s == s0:
            self.W = self.head(others[0], t)
            self.B = self.block(s, self.W)
            self.voters_B = [i for i in self.all_nodes() if i in X or i == others[0]]
            a = sum(len(self.w.nodes[i].validators) for i in self.voters_B)
            self.f1 = max(0, P.n // 2 + 1 - a)  # strict: a + f1 > n/2
            self.send_block(self.B, self.at(self.voters_B, t + P.delta - 1))
            self.notes.append(f"slot {s}: B={self.B.root[:6]} on W={self.W[:6]}; honest for B={a}, faulty f1={self.f1}")
        elif s0 is not None and s == s0 + 1:
            hidden = {Vote(v, s0, self.B.root) for v in self.vals[:self.f1]}
            prev = [x for x in self.honest_votes(s0) + [Vote(v, s0, self.W) for v in self.vals[self.f1:]]
                    if x not in hidden]
            support = [x for x in prev if x.H in self.w.nodes[others[0]].fg.T]
            self.Q = self.block(s, self.W, prev, support)
            self.send_block(self.Q, self.at(self.all_nodes(), t + 1))

    def at_vote(self, s, t):
        P = self.P
        X, others = self.groups
        s0 = getattr(self, "s0", None)
        if s == s0:
            for v in self.vals[:self.f1]:
                self.vote(v, s, self.B.root, self.at(X, t + P.delta - 1))  # X only, just before its cutoff
            for v in self.vals[self.f1:]:
                self.vote(v, s, self.W, self.at(self.all_nodes(), t + 1))
        elif s0 is not None and s == s0 + 1:
            for v in self.vals:
                self.vote(v, s, self.Q.root, self.at(self.all_nodes(), t + 1))


class FinalityHide(Adversary):
    """Under synchrony, no clock skew. It needs the adversary's proposer slots s = rR + 1 and
    s + 1 = rR + 2, the first slot after the action time a_r, whose block finalizes the latest
    justification once it carries the round's finality pairs.

    Slot s: the adversary's block B on the head W reaches nodes 0 and 1 just before their vote.
    f1 faulty votes for B reach everyone early, so B has exactly n/2 early votes; w faulty
    validators keep their slot-s votes back.
    Slot s + 1: three blocks of the adversary.
      FB  extends B and carries the finality pairs: it finalizes J. Only X = node 0 gets it,
          at t_(s+1) + 2 ms; the others get it by relay, Δ later, after their vote.
      Q   a fork from J's parent that carries the w held-back votes. The others get it at
          t_(s+1) + 1 ms and accept it, because their finalized block is still older. X gets it
          by relay after FB, and refuses it: it does not extend X's finalized block. Its votes
          never reach X.
      Z   a sibling of B. The others get it with Q.
    For the others B has n/2 of n voters, is not eligible, and they vote Z. X counts n - w
    voters, confirms B (fast lock with ≥ n/2), and keeps it on its chain, until Z's voters
    unlock it. Every delay is inside Δ; the only lever is the acceptance test Σ.F ⪯ B."""

    name = "fin_hide"
    late_z = False
    q_offset = None  # ms after t_(s+1) at which Q reaches the holdout nodes (default Δ - 1)

    def target(self, s):
        P = self.P
        if not hasattr(self, "s0") and s >= 32 and s % P.R == 1 and self.mine(s) and self.mine(s + 1):
            self.s0 = s
        return getattr(self, "s0", None)

    def at_slot_start(self, s, t):
        P = self.P
        X, others = self.groups
        s0 = self.target(s)
        if s == s0:
            self.W = self.head(others[0], t)
            self.B = self.block(s, self.W, atts=[])
            # honest supporters: X, then other nodes, until n/2 - a faulty votes leave at least one held back
            self.voters_B, a = [X[0]], len(self.w.nodes[X[0]].validators)
            for i in others:
                if P.n // 2 - a <= len(self.vals) - 1:
                    break
                self.voters_B.append(i)
                a += len(self.w.nodes[i].validators)
            self.f1 = max(0, P.n // 2 - a)
            self.send_block(self.B, self.at(self.voters_B, t + P.delta - 1))
        elif s0 is not None and s == s0 + 1:
            F_old = self.w.nodes[others[0]].fg.F
            FB = self.block(s, self.B.root)
            F_new = STATE[FB.root].F
            withheld = [Vote(v, s0, self.W) for v in self.vals[self.f1:]]
            prev = self.honest_votes(s0) + [Vote(v, s0, self.B.root) for v in self.vals[:self.f1]] + withheld
            support = [x for x in prev if x.H in self.w.nodes[others[0]].fg.T]
            Q = self.block(s, BLOCKS[F_new].parent, prev, support, atts=[])
            Z = self.block(s, self.W, atts=[])
            ok = F_new != F_old and prec(F_old, BLOCKS[F_new].parent) and Q is not None and Z is not None
            self.notes.append(f"slot {s0}: B={self.B.root[:6]} (faulty early f1={self.f1}, held back "
                              f"w={len(self.vals) - self.f1}); slot {s}: FB finalizes slot {BLOCKS[F_new].slot} "
                              f"(was {BLOCKS[F_old].slot}); Q on slot {BLOCKS[BLOCKS[F_new].parent].slot}; "
                              f"setup {'ok' if ok else 'FAILED'}")
            if not ok:
                return
            self.Z = Z
            # Q and Z reach the others just before their vote; relay brings Q to X d later. FB reaches
            # X d/2 before that, and its relay reaches the others d/2 after their vote: any honest
            # relay delay d >= 3 ms works (d = the relay bound used by the driver)
            net = self.w.net
            d = P.delta - 1 if net.relay_ms is None else min(net.relay_ms, P.delta - 1)
            q_at = t + (P.delta - 1 if self.q_offset is None else self.q_offset)
            self.send_block(Q, self.at(others, q_at))
            self.send_block(Z, self.at(others, t + P.delta - 1))
            self.send_block(FB, self.at(X, t + P.delta - 1 - d // 2))

    def at_vote(self, s, t):
        P = self.P
        s0 = getattr(self, "s0", None)
        if s == s0:
            for v in self.vals[:self.f1]:
                self.vote(v, s, self.B.root, self.at(self.all_nodes(), t + P.delta - 1))
        elif s0 is not None and s == s0 + 1 and getattr(self, "Z", None):
            # late_z: the faulty Z votes land just before the freeze, after the fooled nodes' update
            # (t + Δ): they still enter every frozen view, so the next slot's votes go to Z
            if self.late_z == "proposer":
                return  # sent at the freeze, to the next proposer only (at_freeze)
            at = t + 2 * P.delta - 1 if self.late_z else t + 1
            for v in self.vals:
                self.vote(v, s, self.Z.root, self.at(self.all_nodes(), at))

    def at_freeze(self, s, t):
        """late_z = proposer: the faulty slot-(s0+1) votes for Z reach only the slot-(s0+2) proposer,
        just before its proposal; its block carries them to everyone (relay brings them too)."""
        P = self.P
        s0 = getattr(self, "s0", None)
        if self.late_z != "proposer" or s0 is None or s != s0 + 1 or not getattr(self, "Z", None):
            return
        prop = P.proposer(s + 1)
        if prop in self.valset:
            self.notes.append("slot-(s0+2) proposer is faulty: not handled")
            return
        dst = self.w.node_of[prop]
        for v in self.vals:
            self.vote(v, s, self.Z.root, self.at([dst], P.t(s + 1) - 1))


class FinalityHideSeq(Adversary):
    """fin_hide without proposer equivocation: one block per adversary slot. It needs the
    adversary's slots rR + 2, rR + 3 and rR + 4 of one round.

    Slot rR + 2: FB, the first block after the round's attestations, carries them; the adversary
      withholds it, so no honest node finalizes J yet (the next honest proposer would include
      the attestations, so every slot up to the hiding block must be the adversary's).
    Slot s = rR + 3: B on the head W reaches group X just before its vote; f1 faulty early votes
      bring B to exactly n/2 early votes; the other w faulty validators keep their slot-s votes
      back (they name W, so they never oppose B).
    Slot s + 1: Q, a fork from J's parent carrying the w held-back votes, reaches the holdout just
      before its vote; FB reaches X just before Q's relay does. X finalizes J and refuses Q, counts
      n - w voters, confirms B and fast-locks it (≥ n/2). The holdout counts n voters, B is no
      majority, and it votes W. The faulty validators vote W from then on.
    Nothing opposes B, so X's lock holds until it expires, k slots later; B never regains a
    majority (X's honest votes only), and every honest head then leaves it."""

    name = "fin_hide_seq"

    def target(self, s):
        P = self.P
        if not hasattr(self, "s0") and s >= 32 and s % P.R == 2 and all(self.mine(s + i) for i in range(3)):
            self.s0 = s + 1
        return getattr(self, "s0", None)

    def at_slot_start(self, s, t):
        P = self.P
        X, others = self.groups
        s0 = self.target(s)
        if s0 is None:
            return
        if s == s0 - 1:
            self.F_old = self.w.nodes[others[0]].fg.F
            self.FB = self.block(s, self.head(others[0], t))  # carries the round's attestations; withheld
        elif s == s0:
            self.W = self.head(others[0], t)
            self.B = self.block(s, self.W, atts=[])
            a = sum(len(self.w.nodes[i].validators) for i in X)
            self.f1 = max(0, P.n // 2 - a)
            assert self.f1 < len(self.vals), "not enough faulty validators for an exact half"
            self.send_block(self.B, self.at(X, t + P.delta - 1))
        elif s == s0 + 1:
            FB = self.FB
            F_new = STATE[FB.root].F if FB is not None else self.F_old
            withheld = [Vote(v, s0, self.W) for v in self.vals[self.f1:]]
            prev = self.honest_votes(s0) + [Vote(v, s0, self.B.root) for v in self.vals[:self.f1]] + withheld
            support = [x for x in prev if x.H in self.w.nodes[others[0]].fg.T]
            Q = self.block(s, BLOCKS[F_new].parent, prev, support, atts=[]) if F_new != self.F_old else None
            ok = FB is not None and Q is not None and prec(self.F_old, BLOCKS[F_new].parent)
            self.notes.append(f"slot {s0 - 1}: FB withheld, finalizes slot {BLOCKS[F_new].slot} (was {BLOCKS[self.F_old].slot}); "
                              f"slot {s0}: B (f1={self.f1}, held back w={len(self.vals) - self.f1}); slot {s}: Q; "
                              f"setup {'ok' if ok else 'FAILED'}")
            if not ok:
                return
            net = self.w.net
            d = P.delta - 1 if net.relay_ms is None else min(net.relay_ms, P.delta - 1)
            self.send_block(Q, self.at(others, t + P.delta - 1))
            self.send_block(FB, self.at(X, t + P.delta - 1 - d // 2))

    def at_vote(self, s, t):
        P = self.P
        s0 = getattr(self, "s0", None)
        if s0 is None:
            return
        if s == s0:
            for v in self.vals[:self.f1]:
                self.vote(v, s, self.B.root, self.at(self.all_nodes(), t + P.delta - 1))
        elif s > s0:  # from then on, vote W (never an opponent of B), early, to everyone
            # late_z: at s0 + 1, just before the freeze instead, after the fooled nodes' update (> n/2)
            at = t + 2 * P.delta - 1 if self.late_z and s == s0 + 1 else t + 1
            for v in self.vals:
                self.vote(v, s, self.W, self.at(self.all_nodes(), at))


class FinalityHideDF(FinalityHideSeq):
    """fin_hide_seq when attestations travel slower than blocks (Δ_F > Δ). Every honest attestation
    of round r reaches every node only at a_r + Δ_F - 1 (within its bound), and the adversary
    keeps its own: with 43 honest validators and q = 43, no honest proposer can include a
    finality quorum before then. So the finalizing block FB need not be in the slot right after
    the attestations: it is the adversary's block of ANY earlier slot j of the round
    (rR + 2 <= j < s), built only when it is sent, on the newest block older than j, with all the
    honest attestations. The attack needs adversary slots j, s, s + 1 with s, s + 1 consecutive,
    and every honest proposal in [rR + 2, s) before the attestations arrive."""

    name = "fin_hide_df"

    def __init__(self, world, rng, groups):
        super().__init__(world, rng, groups)
        P = self.P
        net = world.net

        def delay(src, dst, kind, payload, now):  # honest attestations as late as the bound allows
            return P.delta_f - 1 if kind == "att" else net.latency_ms
        net.honest_delay = delay

    def target(self, s):
        P = self.P
        if hasattr(self, "s0") or s < 32 or s % P.R != 2:
            return getattr(self, "s0", None)
        r = P.round(s)
        arrive = P.action_time(r) + P.delta_f - 1
        for b in range(s + 1, r * P.R + P.R - 1):  # B in slot b, Q in slot b + 1, both in the round
            if not (self.mine(b) and self.mine(b + 1)):
                continue
            js = [j for j in range(s, b) if self.mine(j)]
            honest = [h for h in range(s, b) if not self.mine(h)]
            if js and all(P.t(h) < arrive for h in honest) and (not honest or P.t(max(honest)) < arrive):
                self.s0, self.j = b, js[-1]
                break
        return getattr(self, "s0", None)

    def at_slot_start(self, s, t):
        P = self.P
        X, others = self.groups
        s0 = self.target(s)
        if s0 is None:
            return
        if s == s0:
            self.F_old = self.w.nodes[others[0]].fg.F
            self.W = self.head(others[0], t)
            self.B = self.block(s, self.W, atts=[])
            a = sum(len(self.w.nodes[i].validators) for i in X)
            self.f1 = max(0, P.n // 2 - a)
            self.send_block(self.B, self.at(X, t + P.delta - 1))
        elif s == s0 + 1:
            # FB: slot j, on the newest block older than j, with every honest attestation
            older = [r for r in self.tree() if BLOCKS[r].slot < self.j and prec(r, self.W)]
            parent = max(older, key=lambda r: (DEPTH[r], r))
            atts = [a for _, _, kind, payload in self.w.net.sent_log if kind == "att" for a in payload]
            self.FB = self.block(self.j, parent, atts=self.valid_atts(parent, atts))
            super().at_slot_start(s, t)
            self.notes[-1] = self.notes[-1].replace(f"slot {s0 - 1}: FB withheld", f"slot {self.j}: FB built late")


class LateJustification(Adversary):
    """A justification revealed late, to open a frontier contest. Needs a cut (--cut a:d) that
    starts after round r - 1's attestations spread and before a block includes them, and that
    contains round r's action time. No equivocation: the adversary never signs two conflicting
    objects.

    During the cut each side includes round r - 1's attestations in its own block, so the
    chains enter height h at different blocks, A1 (side A = group A) and B1. Faulty validators
    are split, not doubled: f_A vote side A's head to side A, the others side B's to side B, so
    each side reaches n/2 early votes and fast-locks (it can attest). At a_r side A targets
    (h, A1) and side B (h, B1); the faulty validators also target (h, A1), but only inside X_A,
    a block on A's chain that the adversary keeps: X_A justifies A1 and nobody knows.
    After the heal the faulty validators vote B's head: side A's locks move back and everyone
    follows B. At a_(r+1) side A, having targeted A1 at h, times out at (h, B1); so do the
    faulty validators. B reaches the progress quorum and, after δt, height h + 1 without a
    justification. Then the adversary reveals X_A: J = A1 at h, h_max = h + 1, and B's blocks
    at h + 1 do not extend A1, a contest at every node."""

    name = "late_j"

    def __init__(self, world, rng, groups):
        super().__init__(world, rng, groups)
        self.XA = None
        self.revealed = False
        self.no_reveal = False  # --no-reveal: keep X_A for good (control: the split alone)

    def cut(self):
        return self.w.net.windows[0] if self.w.net.windows else None

    def in_cut(self, t):
        c = self.cut()
        return c is not None and c[0] <= t < c[1]

    def after_cut(self, t):
        c = self.cut()
        return c is not None and t >= c[1]

    def split(self):
        A, B = self.groups
        hA = sum(len(self.w.nodes[i].validators) for i in A)
        fA = max(0, self.P.n // 2 - hA)
        return self.vals[:fA], self.vals[fA:]

    def at_vote(self, s, t):
        A, B = self.groups
        if self.in_cut(t):
            for side, vals in zip((A, B), self.split()):
                H = self.head(side[0], t)
                for v in vals:
                    self.vote(v, s, H, self.at(side, t + 1))
        elif self.after_cut(t):
            H = self.head(B[0], t)
            for v in self.vals:
                self.vote(v, s, H, self.at(self.all_nodes(), t + 1))

    def at_action(self, r, t):
        A, B = self.groups
        if self.in_cut(t) and self.XA is None and not hasattr(self, "hA"):
            a = self.w.nodes[A[0]]
            fgc = a.last_fg_confirmed
            if fgc is None:
                self.notes.append(f"round {r}: side A has no fg_confirmed, setup FAILED")
                return
            self.hA, self.A1 = STATE[fgc].h, STATE[fgc].Th
            self.hidden = [Att(v, self.hA, self.A1, False, None, None) for v in self.vals]
            self.r0 = r
            b = self.w.nodes[B[0]]
            self.B1 = STATE[b.last_fg_confirmed].Th if b.last_fg_confirmed else None
            self.notes.append(f"round {r}: side A targets (h={self.hA}, A1 slot {BLOCKS[self.A1].slot}); side B entry "
                              f"{BLOCKS[self.B1].slot if self.B1 else None}")
        elif self.after_cut(t) and hasattr(self, "hA") and not getattr(self, "timed_out", False):
            node = self.w.nodes[B[0]]
            fgc = node.last_fg_confirmed or node.head(t)
            st = STATE[fgc]
            if st.h == self.hA and st.Th != self.A1:
                for v in self.vals:
                    self.w.net.adv_send("att", Att(v, st.h, st.Th, True, None, None), self.at(self.all_nodes(), t + 1))
                self.timed_out = True
                self.notes.append(f"round {r}: faulty timeouts at (h={st.h}, B entry slot {BLOCKS[st.Th].slot})")

    def at_slot_start(self, s, t):
        from model import INCL
        A, B = self.groups
        if hasattr(self, "hA") and self.XA is None and self.mine(s):
            # X_A on A's chain: side A's targets not yet included plus the hidden faulty targets
            tips = [r for r in self.tree() if STATE[r].h == self.hA and STATE[r].Th == self.A1]
            if tips:
                parent = max(tips, key=lambda r: (DEPTH[r], r))
                if BLOCKS[parent].slot < s:
                    extra = [a for a in self.pool() if (a.h, a.T) == (self.hA, self.A1) and a not in INCL[parent]]
                    XA = self.block(s, parent, atts=self.valid_atts(parent, self.hidden + extra))
                    if XA is not None and STATE[XA.root].hj == self.hA:
                        self.XA = XA
                        self.notes.append(f"slot {s}: X_A on slot {BLOCKS[parent].slot} justifies A1 at h={self.hA} (kept)")
        if self.after_cut(t) and self.XA is not None and not self.revealed and not self.no_reveal:
            heads = [STATE[self.head(i, t)].h for i in self.all_nodes()]
            if min(heads) > self.hA:
                self.send_block(self.XA, self.at(self.all_nodes(), t + 1))
                self.revealed = True
                self.notes.append(f"slot {s}: B's chain at h={min(heads)} everywhere; X_A revealed")
        if self.after_cut(t) and self.mine(s) and (self.XA is None or self.revealed or s != getattr(self.XA, "slot", -1)):
            H = self.head(B[0], t)
            Bk = self.block(s, H)
            if Bk is not None:
                self.send_block(Bk, self.at(self.all_nodes(), t + 1))


class Outage(Adversary):
    """Asynchrony resilience of a confirmation. Under synchrony an honest block B of slot s is
    confirmed at T = t_(s+1) + 2Δ (the update of slot s). An outage starts at T + τ
    (--outage-tau, ms, ≥ -2Δ) and lasts d slots (--outage-slots); during it honest traffic
    between different groups (--outage-groups, e.g. 0/1/2/3 or 0,1,2/3) waits for the heal, while
    the adversary reaches every node. The adversary proposes C, a sibling of B, in slot s + 1 (it
    needs that slot) and from then on its validators vote C, early, to every node. A break is a
    node that showed B as confirmed and ends with B orphaned."""

    name = "outage"
    tau = 0
    slots = 2
    groups_spec = None
    passive_votes = False  # --outage-passive: same outage, the adversary does not vote (control)

    def at_slot_start(self, s, t):
        P = self.P
        if hasattr(self, "B") or s < 33 or not self.mine(s):
            return
        B = self.head(0, t)
        if BLOCKS[B].slot != s - 1 or BLOCKS[B].proposer in self.valset:
            return
        self.B, self.s0 = B, s - 1
        self.C = self.block(s, BLOCKS[B].parent, atts=[])
        if self.C is None:
            return
        self.send_block(self.C, self.at(self.all_nodes(), t + 1))
        T = P.t(s) + 2 * P.delta
        start = T + self.tau
        end = start + self.slots * P.slot_ms
        spec = self.groups_spec or "/".join(str(i) for i in self.all_nodes())
        g = {int(i): k for k, part in enumerate(spec.split("/")) for i in part.split(",")}
        self.w.net.windows.append((start, end, g))
        self.window = (start, end)
        self.notes.append(f"B = slot {s - 1} (honest), C = slot {s} on its parent; confirmation at T = t_{s}+2Δ; "
                          f"outage [{(start - P.t(s)) / P.delta:+.2f}Δ, +{self.slots} slots) groups {spec}")

    def at_vote(self, s, t):
        if hasattr(self, "C") and self.C is not None and s >= self.s0 + 1 and not self.passive_votes:
            for v in self.vals:
                self.vote(v, s, self.C.root, self.at(self.all_nodes(), t + 1))


class TwoFace(Adversary):
    """Partial synchrony. During the cut the adversary is honest-looking on both sides at once:
    it votes each side's head to that side, proposes one block per side at its slots, and
    attests each side's own entry with that side's finality pair (it ignores its anti-slashing
    record: equivocating attestations are slashable, not prevented). With a 22/21 honest split
    each side sees 43 or 42 participants, so the side that reaches q justifies and may finalize
    on its own. After the heal (GST) it follows `post`:
      passive  abstain;
      balance  every slot, vote the weaker of the two heaviest conflicting branches, early, to
               keep honest votes split;
      fuzz     random behaviour as Fuzz;
      reveal   it also kept back its side-B blocks during the cut and releases them one by one
               after the heal, at random times, to reopen contests and frame changes."""

    name = "twoface"
    post = "passive"

    def __init__(self, world, rng, groups):
        super().__init__(world, rng, groups)
        self.kept = []  # blocks withheld during the cut (reveal mode)
        self.fuzz = None

    def in_cut(self, t):
        return any(a <= t < b for a, b, _ in self.w.net.windows)

    def after_cut(self, t):
        return self.w.net.windows and t >= max(b for _, b, _ in self.w.net.windows)

    def sides(self):
        return [g for g in self.groups if g]

    def act(self, t):
        if self.after_cut(t) and self.post == "fuzz":
            if self.fuzz is None:
                self.fuzz = Fuzz(self.w, self.rng, self.groups)
                self.fuzz.cast, self.fuzz.proposed = self.cast, self.proposed
            return self.fuzz.act(t)
        return super().act(t)

    def at_slot_start(self, s, t):
        P = self.P
        if self.in_cut(t):
            if not self.mine(s):
                return
            for k, g in enumerate(self.sides()):
                H = self.head(g[0], t)
                prev = [x for x in self.honest_votes(s - 1) if True] + [Vote(v, s - 1, h) for (ss, v, h) in self.cast
                                                                        if ss == s - 1 and h in self.w.nodes[g[0]].fg.T]
                support = [x for x in prev if x.H in self.w.nodes[g[0]].fg.T and BLOCKS[x.H].slot <= s - 1]
                atts = [a for a in self.w.nodes[g[0]].fg.pool]
                B = self.block(s, H, prev, support, [a for a in self.valid_atts(H, atts)])
                if B is None:
                    continue
                if self.post == "reveal" and k == 1 and self.rng.random() < 0.5:
                    self.kept.append(B)
                else:
                    self.send_block(B, self.at(g, t + 1))
            return
        if self.after_cut(t):
            if self.post == "reveal" and self.kept and self.rng.random() < 0.5:
                B = self.kept.pop(0)
                self.send_block(B, self.at([self.rng.choice(self.all_nodes())], t + self.rng.choice((1, P.delta - 1, 2 * P.delta))))
            if self.post in ("balance",) and self.mine(s):
                H = self.head(0, t)
                B = self.block(s, H)
                if B is not None:
                    self.send_block(B, self.at(self.all_nodes(), t + 1))

    def at_vote(self, s, t):
        P = self.P
        if self.in_cut(t):
            for g in self.sides():
                H = self.head(g[0], t)
                for v in self.vals:
                    self.vote(v, s, H, self.at(g, t + 1))
            return
        if self.after_cut(t) and self.post == "balance":
            heads = [self.head(i, t) for i in self.all_nodes()]
            # the two heaviest conflicting candidates among the honest heads and their parents
            cand = sorted(set(heads) | {BLOCKS[h].parent for h in heads if BLOCKS[h].parent})
            pairs = [(a, b) for a in cand for b in cand if a < b and conflicts(a, b)]
            if not pairs:
                return
            cnt = {c: sum(1 for x in self.honest_votes(s) if prec(c, x.H)) for c in cand}
            a, b = max(pairs, key=lambda p_: min(cnt[p_[0]], cnt[p_[1]]))
            weak = a if cnt[a] <= cnt[b] else b
            for v in self.vals:
                self.vote(v, s, weak, self.at(self.all_nodes(), t + 1))

    def at_action(self, r, t):
        if not self.in_cut(t):
            return
        for g in self.sides():
            node = self.w.nodes[g[0]]
            fgc = node.last_fg_confirmed
            if fgc is None:
                continue
            head = node.head(t)
            hc, Tc, hj, J, hF = node.fg.attest_inputs(fgc, head)
            hf, Tf = (hj, J) if hj > hF else (None, None)
            if hf is not None and hf >= hc:
                hf, Tf = None, None
            for v in self.vals:
                self.w.net.adv_send("att", Att(v, hc, Tc, False, hf, Tf), self.at(g, t + 1))


INTERESTING = (1, -1)  # offsets around each boundary


class Fuzz(Adversary):
    """Random behaviour inside the synchrony bounds: votes (abstain, one, or two conflicting
    heads per cohort), blocks (none, one, two, on random recent parents, with random vote and
    support lists and attestation subsets), attestations (random entries, timeouts, finality
    pairs) and honest delays, each delivered per node at times near the boundaries
    Δ, 2Δ, 3Δ, 5Δ, 6Δ of the slot."""

    name = "fuzz"

    def __init__(self, world, rng, groups, cohorts=3):
        super().__init__(world, rng, groups)
        k = max(1, cohorts)
        self.cohorts = [self.vals[i::k] for i in range(k)]
        P = self.P
        r = self.rng
        bound = {"block": P.delta, "vote": P.delta, "att": P.delta_f}

        def delay(src, dst, kind, payload, now):
            return r.choice((1, world.net.latency_ms, bound[kind] - 1))

        world.net.honest_delay = delay

    def rtime(self, s):
        P = self.P
        b = self.rng.choice((0, 1, 2, 3, 5, 6, 7))
        return P.t(s) + b * P.delta + self.rng.choice(INTERESTING) if b else P.t(s) + 1

    def candidates(self, s, depth=4):
        tr = self.tree() | {r for _, r in self.proposed}
        cand = [B for B in tr if BLOCKS[B].slot >= s - depth and BLOCKS[B].slot <= s]
        heads = [self.head(i) for i in range(len(self.w.nodes))]
        return sorted(set(cand + heads) or {GEN})

    def deliver(self, kind, obj, s):
        if self.rng.random() < 0.1:
            return  # withheld for good
        arr = {}
        for i in self.all_nodes():
            if self.rng.random() < 0.7:
                arr[i] = self.rtime(s)
        if not arr:
            arr[self.rng.choice(self.all_nodes())] = self.rtime(s)
        if kind == "block":
            self.w.net.adv_send(kind, obj, arr)
        elif kind == "vote":
            self.w.net.adv_send(kind, obj, arr)
        else:
            self.w.net.adv_send(kind, obj, arr)

    def at_slot_start(self, s, t):
        r = self.rng
        cand = self.candidates(s)
        if self.mine(s):
            prev = self.honest_votes(s - 1) + [Vote(v, s - 1, h) for (ss, v, h) in self.cast if ss == s - 1]
            for _ in range(r.choice((0, 1, 1, 2))):
                parent = r.choice([c for c in cand if BLOCKS[c].slot < s] or [GEN])
                votes = [x for x in prev if r.random() < 0.8]
                if r.random() < 0.3:  # fresh, never-sent votes of the previous slot
                    votes += [Vote(v, s - 1, r.choice(cand)) for v in r.sample(self.vals, r.randint(1, len(self.vals)))]
                support = [x for x in votes if r.random() < 0.8 and BLOCKS.get(x.H) and BLOCKS[x.H].slot <= s - 1]
                atts = [a for a in self.valid_atts(parent) if r.random() < 0.8]
                B = self.block(s, parent, votes, support, atts)
                if B is not None:
                    self.deliver("block", B, s)
            cand = self.candidates(s)
        for coh in self.cohorts:
            mode = r.choice(("abstain", "one", "one", "two"))
            if mode == "abstain":
                continue
            heads = r.sample(cand, min(len(cand), 1 if mode == "one" else 2))
            for v in coh:
                for H in heads:
                    x = Vote(v, s, H)
                    self.cast.append((s, v, H))
                    self.deliver("vote", x, s)

    def at_action(self, rr, t):
        r = self.rng
        P = self.P
        tr = sorted(self.tree())
        entries = sorted({(STATE[B].h, STATE[B].Th) for B in tr})
        pend = sorted({pf for B in tr for pf in STATE[B].pending_finality})
        for coh in self.cohorts:
            if r.random() < 0.3:
                continue
            h, T = r.choice(entries)
            tau = r.random() < 0.3
            hf, Tf = r.choice(pend) if pend and r.random() < 0.6 else (None, None)
            if hf is not None and hf >= h:
                hf, Tf = None, None
            for v in coh:
                a = Att(v, h, T, tau, hf, Tf)
                arr = {i: t + r.choice((1, P.delta_f - 1, 2 * P.delta, 4 * P.delta)) for i in self.all_nodes()
                       if r.random() < 0.8}
                if arr:
                    self.w.net.adv_send("att", a, arr)


STRATEGIES = {c.name: c for c in (Adversary, Equivocate, Split, Fuzz, SkewFast, SkewFreeze, TwoFace, FinalityHide, FinalityHideSeq, FinalityHideDF, LateJustification, Outage)}


# ------------------------------------------------------------------------ checks


def check(world, tracker, t_end, warmup=0):
    """The synchrony claims of the spec and the slides, from the honest nodes' logs."""
    P = world.P
    nodes = world.nodes
    heads = {n.id: n.head(t_end) for n in nodes}
    confirm = [e for e in world.log_events if e["kind"] == "confirm"]
    by_slot = defaultdict(list)
    for e in confirm:
        if e["result"] is not None:
            by_slot[e["slot"]].append((e["node"], e["result"]))
    tsq = []  # two honest nodes confirm conflicting blocks in one slot
    for s, rows in sorted(by_slot.items()):
        if s < warmup:
            continue
        for i, (a, x) in enumerate(rows):
            for b, y in rows[i + 1:]:
                if conflicts(x, y):
                    tsq.append((s, a, BLOCKS[x].slot, b, BLOCKS[y].slot))
    dropped = []  # a fast-confirmed block (fast lock or fg_confirmed) that some final head does not extend
    seen = set()
    for e in confirm:
        for B in (e.get("fast"),):
            if B and e["slot"] >= warmup and B not in seen:
                seen.add(B)
                miss = [i for i, h in heads.items() if not prec(B, h)]
                if miss:
                    dropped.append(("fast", e["slot"], e["node"], BLOCKS[B].slot, miss))
    fgc = [e for e in world.log_events if e["kind"] == "fg_pair" and e["fg_confirmed"]]
    for e in fgc:
        B = e["fg_confirmed"]
        if P.slot(e["t"]) >= warmup and ("fg", B) not in seen:
            seen.add(("fg", B))
            miss = [i for i, h in heads.items() if not prec(B, h)]
            if miss:
                dropped.append(("fg_confirmed", P.slot(e["t"]), e["node"], BLOCKS[B].slot, miss))
    # a block that was some honest node's confirmed tip (user-facing) and is off the final chain:
    # the PR4 property ("the confirmed head never reorgs under synchrony")
    orphaned = {n.id: [(b, seen) for b, seen in tracker.orphaned_confirmed(n, t_end, True) if b >= warmup]
                for n in nodes}
    fine = {}
    for n in nodes:
        seen = getattr(world, "conf_seen", {}).get(n.id, {})
        fine[n.id] = sorted((BLOCKS[b].slot, round(t0 / P.slot_ms, 2)) for b, t0 in seen.items()
                            if b != "last" and BLOCKS[b].slot >= warmup and not prec(b, heads[n.id]))
    lock_conf = [s for s, _ in tracker.lock_conflicts if s >= warmup]
    reversals = {n.id: [r for r in tracker.conf_reversals[n.id] if r[0] >= warmup] for n in nodes}
    fin = tracker.finality
    fslots = [n.fg.F for n in nodes]
    return {
        "tsq_violations": tsq[:20], "n_tsq": len(tsq),
        "dropped_fast": dropped[:20], "n_dropped": len(dropped),
        "lock_conflict_slots": lock_conf, "conf_reversals": reversals,
        "orphaned_confirmed": orphaned, "n_orphaned": sum(len(v) for v in orphaned.values()),
        "orphaned_confirmed_any_tick": fine, "n_orphaned_any_tick": sum(len(v) for v in fine.values()),
        "orphaned_shown_ms": {n.id: [b - a for (a, c), (b, _) in zip(world.conf_tl[n.id], world.conf_tl[n.id][1:])
                                     if BLOCKS[c].slot >= warmup and not prec(c, heads[n.id])]
                              for n in nodes} if hasattr(world, "conf_tl") else {},
        "finality_timeline": fin, "final_F_slots": [BLOCKS[F].slot for F in fslots],
        "finalized_conflict": tracker.fin_conflict,
        "heads_agree_end": len(set(heads.values())) == 1,
        "invariant_violations": tracker.invariant_violations[:10]
        + [(e["t"], e["node"], e["what"]) for e in world.log_events if e["kind"] == "violation"][:10],
    }


def bad(res):
    return bool(res["n_tsq"] or res["n_dropped"] or res["lock_conflict_slots"] or res["finalized_conflict"]
                or res.get("n_orphaned") or res.get("n_orphaned_any_tick")
                or any(res["conf_reversals"].values()) or res["invariant_violations"])


def dump(path, args, world, tracker):
    from partition_run import dump_events
    A = set(world.adv.groups[0])
    group_of = {n.id: 0 if n.id in A else 1 for n in world.nodes}
    dump_events(path, args, world, tracker, group_of, [])


def run(args, quiet=True):
    assert 3 * args.f <= args.validators, f"the adversary holds at most n/3 (f={args.f}, n={args.validators})"
    P = Params(n=args.validators, delta=args.delta_ms, delta_f=args.delta_f_ms or args.delta_ms, R=args.R, k=args.k,
               delta_t=args.delta_t or args.R, seed=args.seed, fast_strict=args.fast_strict,
               refused_votes=args.refused_votes, lean_finality=args.lean_finality)
    skew = {}
    for item in filter(None, (args.skew or "").split(",")):
        i, ms = item.split(":")
        skew[int(i)] = int(ms)
    shares = [int(x) for x in args.shares.split(",")] if args.shares else None
    world = AdvWorld(P, args.f, args.nodes, shares, args.latency_ms, args.relay, args.relay_ms, skew)
    if getattr(args, "events", None):
        world.net.events = []
    world.relay_carried = args.relay_carried
    if args.spec_drop_early:
        world.hold_early = False  # the spec's rule: drop a block (and a vote) of a future slot
    half = args.nodes // 2
    groups = [list(range(half)), list(range(half, args.nodes))] if not args.group_a else \
        [[int(x) for x in args.group_a.split(",")],
         [i for i in range(args.nodes) if str(i) not in args.group_a.split(",")]]
    world.adv = STRATEGIES[args.strategy](world, random.Random(f"adv-{args.seed}"), groups)
    world.adv.round_start = args.round_start
    world.adv.no_reveal = args.no_reveal
    world.adv.tau, world.adv.slots, world.adv.groups_spec = args.outage_tau, args.outage_slots, args.outage_groups
    world.adv.passive_votes = args.outage_passive
    for item in filter(None, args.sleep.split(",")):
        nid, a, b = item.split(":")
        world.sleep.setdefault(int(nid), []).append((round(float(a) * P.slot_ms), round(float(b) * P.slot_ms)))
    world.adv.post = args.post
    world.adv.late_z = args.late_z
    world.adv.q_offset = args.q_offset
    if args.cut:
        a, d = (int(x) for x in args.cut.split(":"))
        A = set(groups[0])
        world.net.windows.append((P.t(a), P.t(a + d), {n.id: 0 if n.id in A else 1 for n in world.nodes}))
    tracker = Tracker(world)
    for s in range(args.slots + 1):
        world.run_slot(s, tracker.observe)
        if not quiet:
            snaps = tracker.states[-1]["nodes"]
            cols = "  ".join(f"{x['head_slot']:>3}/{x['conf_slot']:>3}/{x['F_slot']:>3} h{x['head_h']}"
                             f" L[{','.join(str(b) for _, b, _ in x['locks'])}]" for x in snaps)
            mine = "P" if world.adv.mine(s) else " "
            print(f"{s:4d} {mine} | {cols} | {'=' if len({x['head'] for x in snaps}) == 1 else 'x'}")
    heal = 0
    if args.cut:
        a, d = (int(x) for x in args.cut.split(":"))
        heal = a + d
    # claims after GST: conflicting locks gone by GST + L, heads healed by GST + 2L + G (slides 8-9);
    # L is k slots of lock lifetime, G the wait for an honest proposer. Checked from GST + 2k + 4.
    res = check(world, tracker, world.t, max(args.warmup, heal + 2 * P.k + 4 if heal else 0))
    res["heal"] = heal
    fin = tracker.finality
    if heal:
        f_heal = max([f for s_, f in fin if s_ <= heal] or [0])
        later = [(s_, f) for s_, f in fin if s_ > heal and f > f_heal]
        res["finality_resumes_slot"] = later[0][0] if later else None
        res["finality_resume_delay"] = (later[0][0] - heal) if later else None
    changes = [s_ for s_, _ in fin if s_ > (heal or 40)]
    gaps = [b - a for a, b in zip([heal or 40] + changes, changes + [args.slots])]
    res["max_finality_gap"] = max(gaps) if gaps else None
    res["notes"] = list(world.adv.notes)
    res["adv_votes"] = len(world.adv.cast)
    res["adv_blocks"] = len(world.adv.proposed)
    res["dropped_first_seen"] = world.net.dropped
    return world, tracker, res


def add_args(p):
    p.add_argument("--validators", type=int, default=64)
    p.add_argument("--f", type=int, default=21, help="faulty validators (at most n/3)")
    p.add_argument("--nodes", type=int, default=4)
    p.add_argument("--shares", default=None)
    p.add_argument("--group-a", default=None, help="honest nodes of group A, e.g. 0,1 (default first half)")
    p.add_argument("--latency-ms", type=int, default=200)
    p.add_argument("--delta-ms", type=int, default=1500)
    p.add_argument("--k", type=int, default=4)
    p.add_argument("--R", type=int, default=8)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--slots", type=int, default=96)
    p.add_argument("--warmup", type=int, default=0)
    p.add_argument("--strategy", choices=sorted(STRATEGIES), default="fuzz")
    p.add_argument("--relay", choices=("faithful", "first-seen"), default="faithful")
    p.add_argument("--relay-ms", type=int, default=None)
    p.add_argument("--delta-f-ms", type=int, default=None, help="Δ_F, delivery bound of attestations (default Δ)")
    p.add_argument("--skew", default="", help="clock offsets node:ms,... (leaves the spec's model)")
    p.add_argument("--fast-strict", action="store_true", help="fast test > n/2 (NOT the spec), to compare")
    p.add_argument("--lean-finality", action="store_true", help="NOT the spec: F advances ignoring a contest (Lean model)")
    p.add_argument("--q-offset", type=int, default=None, help="fin_hide: when Q reaches the holdout (ms after t_(s+1))")
    p.add_argument("--relay-carried", action="store_true",
                   help="honest nodes relay the carried votes of every block they accept (the Lean's relay premise)")
    p.add_argument("--refused-votes", action="store_true",
                   help="NOT the spec (proposed fix): take the votes of a block the FG refuses")
    p.add_argument("--round-start", action="store_true", help="skew attacks: only at a round start (FG source)")
    p.add_argument("--no-reveal", action="store_true", help="late_j: never reveal X_A (control)")
    p.add_argument("--outage-tau", type=int, default=0, help="outage: start, ms after the confirmation (>= -2Δ)")
    p.add_argument("--outage-slots", type=float, default=2, help="outage: length in slots")
    p.add_argument("--outage-groups", default=None, help="outage: groups, e.g. 0/1/2/3 or 0,1,2/3")
    p.add_argument("--outage-passive", action="store_true", help="outage: the adversary does not vote (control)")
    p.add_argument("--late-z", nargs="?", const="freeze", default=None, choices=("freeze", "proposer"),
                   help="fin_hide: faulty slot-(s+1) votes just before the freeze, or only to the next proposer")
    p.add_argument("--sleep", default="", help="asleep windows node:start:end (slots), comma-separated")
    p.add_argument("--cut", default="", help="partition start:slots between group A and the rest (GST at the end)")
    p.add_argument("--post", default="passive", choices=("passive", "balance", "fuzz", "reveal"),
                   help="twoface: behaviour after the heal")
    p.add_argument("--delta-t", type=int, default=None, help="timeout delay in slots (default R; the proofs use 2R)")
    p.add_argument("--spec-drop-early", action="store_true",
                   help="with --skew: drop early objects as the spec says, instead of holding them like clients")


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False)
    add_args(p)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--json")
    p.add_argument("--events", help="write messages + per-slot states for explorer.py")
    args = p.parse_args(argv)
    assert 3 * args.f <= args.validators, "the adversary holds at most n/3"
    t0 = time.perf_counter()
    world, tracker, res = run(args, quiet=args.quiet)
    print(f"\n{args.strategy}: n={args.validators} f={args.f} relay={args.relay} skew={args.skew or 0} "
          f"fast_strict={args.fast_strict} in {time.perf_counter() - t0:.1f}s; adversary votes {res['adv_votes']}, "
          f"blocks {res['adv_blocks']}")
    for k in ("n_orphaned", "orphaned_confirmed", "n_orphaned_any_tick", "orphaned_confirmed_any_tick", "orphaned_shown_ms", "n_tsq", "tsq_violations", "n_dropped", "dropped_fast", "lock_conflict_slots", "conf_reversals",
              "finalized_conflict", "heads_agree_end", "final_F_slots", "finality_timeline", "invariant_violations",
              "dropped_first_seen", "finality_resume_delay", "max_finality_gap"):
        print(f"  {k}: {res.get(k)}")
    for line in world.adv.notes:
        print("  adversary:", line)
    print("VIOLATION" if bad(res) else "ok")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(res, fh, indent=1, default=str)
    if args.events:
        dump(args.events, args, world, tracker)
    return res


if __name__ == "__main__":
    main()
