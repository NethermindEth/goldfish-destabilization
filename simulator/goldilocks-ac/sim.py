"""Multi-node driver for the Goldilocks available chain alone: network, partitions, sleep, metrics.

The driver of ../goldilocks-live/sim.py without the finality gadget: blocks and votes are the only
messages, and the metrics are those of the available chain (head reorgs, confirmed-tip regressions,
orphaned confirmed blocks, conflicting locks, agreement).

Schedule (section 1.6): at each public time τ (a multiple of Δ) every node first receives every
message that arrived strictly before τ, in arrival order, stamped with its arrival time; then it
runs its tick. A message that arrives exactly at τ is processed after that tick. A node processes
its own block and votes at once (stamp τ).

Network: every message from a node to another one has delay `latency_ms` plus a uniform jitter in
[0, jitter_ms]. Synchrony in the sense of the spec needs that delay to stay below Δ. On top of that,
delay rules act on single links and message kinds: a rule matches a message sent during
[start, end) from a node in `src` to a node in `dst`, of a kind in `kinds` (None: any), and either
holds it until end + latency (+ a uniform spread) or adds `extra_ms` to its delay. A partition
window (start, end, groups) is a hold rule on every link across its cut; a full outage holds every
link; a votes-only outage holds the votes alone; an eclipse holds the links of a few nodes.
"""

import heapq
import itertools
import random
from collections import Counter, namedtuple

from model import BLOCKS, DEPTH, Node, common_ancestor, conflicts, prec

# extra_ms None: hold until end (+ latency + spread); a number: that much on top of the delay
Rule = namedtuple("Rule", "start end src dst kinds extra_ms")


def partition_rules(windows, nodes):
    """A partition window (start, end, {node: group}) as hold rules, one per pair of groups."""
    out = []
    for start, end, group_of in windows:
        groups = sorted(set(group_of.values()))
        for a in groups:
            for b in groups:
                if a != b:
                    out.append(Rule(start, end, frozenset(i for i in range(nodes) if group_of[i] == a),
                                    frozenset(i for i in range(nodes) if group_of[i] == b), None, None))
    return out


class Network:
    def __init__(self, latency_ms=200, jitter_ms=0, seed=0, rules=(), release_spread_ms=0):
        self.latency_ms, self.jitter_ms = latency_ms, jitter_ms
        self.release_spread_ms = release_spread_ms  # held messages leave at end + latency + U(0, spread)
        self.rng = random.Random(f"net-{seed}")
        self.rules = list(rules)
        self.queue, self.seq = [], itertools.count()
        self.held = Counter()  # messages held or delayed by a rule, per kind
        self.sent = Counter()
        self.events = None  # list when recording

    def arrival(self, src, dst, now, kind):
        """The arrival time of a message, and whether a rule held or delayed it."""
        at = now + self.latency_ms + (self.rng.uniform(0, self.jitter_ms) if self.jitter_ms else 0)
        hit = False
        for r in self.rules:
            if not (r.start <= now < r.end and src in r.src and dst in r.dst
                    and (r.kinds is None or kind in r.kinds)):
                continue
            hit = True
            if r.extra_ms is None:
                spread = self.rng.uniform(0, self.release_spread_ms) if self.release_spread_ms else 0
                at = max(at, r.end + self.latency_ms + spread)
            else:
                at += r.extra_ms
        return at, hit

    def broadcast(self, src, now, kind, payload, nodes):
        self.sent[kind] += 1
        for dst in nodes:
            if dst.id == src:
                continue
            at, held = self.arrival(src, dst.id, now, kind)
            if held:
                self.held[kind] += 1
            heapq.heappush(self.queue, (at, next(self.seq), dst.id, kind, payload))
            if self.events is not None:
                self.events.append(message_event(now, at, src, dst.id, kind, payload, held))

    def pop_before(self, t):
        while self.queue and self.queue[0][0] < t:
            yield heapq.heappop(self.queue)


def message_event(now, at, src, dst, kind, payload, held):
    e = {"t": now, "at": at, "src": src, "dst": dst, "kind": kind, "held": held}
    if kind == "block":
        e.update(root=payload.root, slot=payload.slot, parent=payload.parent, proposer=payload.proposer,
                 n_att=0, n_votes=len(payload.votes))
    else:
        e.update(slot=payload[0].s, heads=sorted(Counter(x.H for x in payload).items()))
    return e


def assign(n, nodes, shares=None):
    """Validators to nodes: contiguous ranges, equal unless `shares` (weights per node)."""
    shares = shares or [1] * nodes
    tot = sum(shares)
    cuts = [round(n * sum(shares[: i + 1]) / tot) for i in range(nodes)]
    out, lo = [], 0
    for hi in cuts:
        out.append(range(lo, hi))
        lo = hi
    return out


class World:
    """Nodes + network. `sleep` maps a node to [(start_ms, end_ms)] windows in which it is asleep
    (section 1.1): it receives nothing and runs no tick; an object that would reach it then is
    delivered after the wake (+ latency); at the first tick after a window it restarts (section
    1.3) and joins one or two slots later."""

    def __init__(self, P, nodes=4, latency_ms=200, jitter_ms=0, windows=(), shares=None, record=False,
                 sleep=None, release_spread_ms=0, forward=True, rules=(), honest=None):
        self.P = P
        self.log_events = []
        self.t = 0
        self.net = Network(latency_ms, jitter_ms, P.seed, partition_rules(windows, nodes) + list(rules),
                           release_spread_ms)
        if record:
            self.net.events = []
        # validators [0, honest) are on the nodes; [honest, n) belong to an adversary, if any
        self.nodes = [Node(i, P, vals, log=self._log, forward=forward)
                      for i, vals in enumerate(assign(P.n if honest is None else honest, nodes, shares))]
        self.node_of = {v: n.id for n in self.nodes for v in n.validators}
        self.sleep = sleep or {}
        self.woken = set()

    def _log(self, kind, **kw):
        kw["t"], kw["kind"] = self.t, kind
        self.log_events.append(kw)

    def wake_time(self, nid, t):
        """End of the sleep window containing t, or None when the node is awake at t."""
        for a, b in self.sleep.get(nid, ()):
            if a <= t < b:
                return b
        return None

    def wake_due(self, now):
        """Restart every node whose sleep window ended at or before `now`, at its wake time."""
        for nid, ws in self.sleep.items():
            for a, b in ws:
                if b <= now and (nid, b) not in self.woken:
                    self.woken.add((nid, b))
                    self.t = b
                    self.nodes[nid].restart(b)

    def step(self, t):
        """Deliver every message that arrived before t, then run the tick at t."""
        for at, _, dst, kind, payload in self.net.pop_before(t):
            self.wake_due(at)
            wake = self.wake_time(dst, at)
            if wake is not None:  # delivered after the next wake
                heapq.heappush(self.net.queue, (wake + self.net.latency_ms, next(self.net.seq), dst, kind, payload))
                continue
            node = self.nodes[dst]
            self.t = at
            out = node.on_block(payload, at) if kind == "block" else node.on_votes(payload, at)
            for k, p in out:
                self.net.broadcast(node.id, at, k, p, self.nodes)
        self.wake_due(t)
        self.t = t
        for node in self.nodes:
            if self.wake_time(node.id, t) is not None:
                continue
            for kind, payload in node.on_tick(t):
                self.net.broadcast(node.id, t, kind, payload, self.nodes)

    def run_slot(self, s, observe=None):
        P = self.P
        for i in range(4):
            self.step(P.t(s) + i * P.delta)
            if i == 3 and observe:
                observe(s, self)


# ----------------------------------------------------------------------- metrics


def snapshot(node, t):
    ac = node.ac
    phi = node.phi()
    head = ac.head(phi, t)
    conf = ac.confirmed(phi, t)
    s = node.P.slot(t)
    live = sorted(ac.live_locks(phi, t), key=lambda L: (L.e, L.j, L.B, L.f))
    anchor = ac.get_anchor(phi, t)
    return {
        "head": head, "head_slot": BLOCKS[head].slot,
        "conf": conf, "conf_slot": BLOCKS[conf].slot,
        "record": ac.latest_confirmed, "record_slot": BLOCKS[ac.latest_confirmed].slot,
        "anchor": anchor, "anchor_slot": BLOCKS[anchor].slot,
        "locks": [[L.B, BLOCKS[L.B].slot, L.e + 1] for L in live],  # [block, its slot, the slot it is gone]
        "lock_detail": [[L.B, L.j, L.f, L.e] for L in live],
        "saved_conf": ac.saved_confirmation.get(s - 1),
        "tree": len(phi.tree),
    }


class Tracker:
    """Per-slot observations: reorgs, confirmed-tip regressions, lock conflicts, agreement."""

    def __init__(self, world):
        self.w = world
        ids = [n.id for n in world.nodes]
        self.prev = {i: None for i in ids}
        self.reorgs = {i: [] for i in ids}  # head switched to a conflicting block: (slot, depth, ancestor_slot)
        self.head_stepbacks = {i: [] for i in ids}  # head moved back to a strict ancestor
        self.agree = []  # (slot, heads agree, confirmed tips agree) over awake nodes
        self.conf_reversals = {i: [] for i in ids}  # confirmed tip replaced by a conflicting one
        self.conf_stepbacks = {i: [] for i in ids}  # confirmed tip moved to a strict ancestor
        self.ever_conf = {i: {} for i in ids}  # confirmed tip -> last slot it was the tip
        self.first_conf = {i: {} for i in ids}  # confirmed tip -> first slot it was the tip
        self.lock_conflicts = []  # slots with conflicting live locks across honest nodes
        self.states = []
        self.invariant_violations = []

    def observe(self, s, world):
        t = world.t
        snaps = [snapshot(n, t) for n in world.nodes]
        for n, x in zip(world.nodes, snaps):
            x["asleep"] = world.wake_time(n.id, t) is not None
            if x["asleep"]:
                self.prev[n.id] = None  # an asleep node has no outputs; restart the comparison on wake
                continue
            p = self.prev[n.id]
            if p is not None:
                if conflicts(p["head"], x["head"]):
                    anc = common_ancestor(p["head"], x["head"])
                    self.reorgs[n.id].append((s, DEPTH[p["head"]] - DEPTH[anc], BLOCKS[anc].slot))
                elif p["head"] != x["head"] and prec(x["head"], p["head"]):
                    self.head_stepbacks[n.id].append((s, BLOCKS[p["head"]].slot, x["head_slot"]))
                if conflicts(p["conf"], x["conf"]):
                    self.conf_reversals[n.id].append((s, BLOCKS[p["conf"]].slot, x["conf_slot"]))
                elif p["conf"] != x["conf"] and prec(x["conf"], p["conf"]):
                    self.conf_stepbacks[n.id].append((s, BLOCKS[p["conf"]].slot, x["conf_slot"]))
            self.ever_conf[n.id][x["conf"]] = s
            self.first_conf[n.id].setdefault(x["conf"], s)
            self.prev[n.id] = x
            if not prec(x["conf"], x["head"]):
                self.invariant_violations.append((s, n.id))
        locks = {(B, n.id) for n, x in zip(world.nodes, snaps) for B, _, _ in x["locks"]}
        bad = [(a, b) for (a, i) in locks for (b, j) in locks if i < j and conflicts(a, b)]
        if bad:
            self.lock_conflicts.append((s, len(bad)))
        awake = [x for x in snaps if not x["asleep"]]
        self.agree.append((s, len({x["head"] for x in awake}) == 1, len({x["conf"] for x in awake}) == 1))
        self.states.append({"slot": s, "nodes": snaps})
        return snaps

    def agree_since(self, which, from_slot=0):
        """First slot >= from_slot from which `which` (1 heads, 2 confirmed) agree to the end."""
        since = None
        for row in self.agree:
            if row[0] < from_slot:
                continue
            since = (row[0] if since is None else since) if row[which] else None
        return since

    def orphaned_confirmed(self, node, t, with_seen=False):
        """Blocks that were this node's confirmed tip at some slot and are off its final chain
        (with the last slot at which each was the confirmed tip, if with_seen)."""
        head = node.head(t)
        out = sorted((BLOCKS[c].slot, seen) for c, seen in self.ever_conf[node.id].items() if not prec(c, head))
        return out if with_seen else [b for b, _ in out]
