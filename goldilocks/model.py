"""Goldilocks: an executable transcription of the FGSA spec (fgsa-spec-22102026.pdf).

The spec is pseudocode over an abstract model: n validators of weight 1, a delivery bound
Δ for blocks and AC messages, Δ_F for attestations, public times at multiples of Δ, and
slot s starting at t_s = 4Δs. This module follows it figure by figure:

  Figure 2  node handlers and duties            -> Node
  Figure 3  FG handlers, finality caches, frame -> FG
  Figure 4  FG validator client                 -> Client
  Figure 5  FG state transition                 -> state_transition and helpers
  Figure 7  Goldilocks interface functions      -> AC
  Figure 8  Goldilocks confirmation and locks   -> AC
  Figure 9  Goldilocks fork choice and vote     -> AC

Comments of the form `# F8.18` point at figure 8, line 18 of the spec.

Times are integers in milliseconds. Blocks are content-addressed and shared between nodes
through the global registry BLOCKS (it holds content only; each node's FG decides which
blocks it has accepted). Chain states are pure in (parent state, block), so they are cached
globally as well.

Not modelled (yet): restarts and sleeping nodes (restart_time stays -inf, every node is
always joined), signatures, slashing evidence, attestation committees (every validator
attests at the action time of every round, as in the abstract model, where K_s = V).
"""

import hashlib
import math
from collections import namedtuple
from dataclasses import dataclass, field, replace

NEG_INF = -math.inf
INF = math.inf
GEN = "G"  # root of B_gen

Att = namedtuple("Att", "v h T tau hf Tf")  # (val_index, h, T, τ, h_f, T_f)
Vote = namedtuple("Vote", "v s H")  # Goldfish vote (val_index, s, B)


@dataclass(frozen=True)
class Params:
    n: int = 64  # validators, weight 1 each
    delta: int = 1500  # Δ in ms; a slot is 4Δ
    delta_f: int = 1500  # Δ_F >= Δ, delivery bound of attestations
    R: int = 8  # slots per round (SLOTS_PER_ROUND)
    k: int = 4  # slow window / lock length in slots
    KW: int = 4  # PENDING_FINALITY_WINDOW
    delta_t: int = 8  # timeout delay in slots (TIMEOUT_DELAY_SLOTS = SLOTS_PER_ROUND)
    seed: int = 0

    @property
    def q(self):
        return math.ceil(2 * self.n / 3)

    @property
    def slot_ms(self):
        return 4 * self.delta

    def t(self, s):  # t_s = 4Δs (also for negative s)
        return 4 * self.delta * s

    def slot(self, t):  # slot(t) = ⌊t/(4Δ)⌋
        return int(t // (4 * self.delta))

    def round(self, s):
        return s // self.R

    def action_time(self, r):  # a_r = T_r + 6Δ, the confirmation update of slot rR
        return self.t(r * self.R) + 6 * self.delta

    def proposer(self, s):
        h = hashlib.sha256(f"proposer-{self.seed}-{s}".encode()).digest()
        return int.from_bytes(h[:8], "big") % self.n

    def check(self):
        need = max(2, math.ceil((6 * self.delta + self.delta_f) / (4 * self.delta)))
        assert self.R >= need, f"Goldilocks requires R >= {need}"
        assert self.k >= 2 and self.KW >= 2 and self.delta_f >= self.delta


# ---------------------------------------------------------------- blocks (section 1.2)


@dataclass(frozen=True)
class Block:
    root: str
    slot: int
    parent: str
    proposer: int
    attestations: tuple = ()
    votes: tuple = ()  # B.votes: slot-(B.slot-1) Goldfish votes
    support_votes: tuple = ()  # entries of B.votes resolved at proposal time


BLOCKS = {GEN: Block(GEN, 0, None, -1)}
DEPTH = {GEN: 0}
ANC = {GEN: frozenset([GEN])}  # ancestor-or-self sets: B ⪯ C  iff  B in ANC[C]


def make_block(slot, parent, proposer, attestations, votes, support_votes):
    digest = hashlib.sha256(repr((parent, slot, proposer, attestations, votes, support_votes)).encode()).hexdigest()
    root = f"{slot:03d}{digest[:5]}"
    if root not in BLOCKS:
        BLOCKS[root] = Block(root, slot, parent, proposer, tuple(attestations), tuple(votes), tuple(support_votes))
        DEPTH[root] = DEPTH[parent] + 1
        ANC[root] = ANC[parent] | {root}
    return BLOCKS[root]


def prec(b, c):
    """b ⪯ c: b = c or b is an ancestor of c."""
    return b in ANC[c]


def compatible(b, c):
    return prec(b, c) or prec(c, b)


def conflicts(b, c):
    return not compatible(b, c)


def deepest(roots):
    """Maximum depth; ties use a fixed root order (smallest root)."""
    return min(roots, key=lambda r: (-DEPTH[r], r))


def common_ancestor(b, c):
    return deepest(ANC[b] & ANC[c])


# ------------------------------------------------------------ chain state (Figure 5)


@dataclass(frozen=True)
class ChainState:
    L: str = GEN
    s: int = 0
    h: int = 1
    Th: str = GEN
    target_participation: frozenset = frozenset()  # Q_target
    progress: frozenset = frozenset()  # Q_prog
    pending_finality: tuple = ()  # ((j, T), ...) increasing j, at most KW
    finality_participation: tuple = ()  # ((j, frozenset), ...) aligned with the keys of pending_finality
    J: str = GEN
    hj: int = 0
    F: str = GEN
    hF: int = 0

    def fin_part(self, j):
        return dict(self.finality_participation).get(j, frozenset())


STATE = {GEN: ChainState()}
INCL = {GEN: frozenset()}  # attestations included on the chain ending at a block


def valid_attestation(sigma, a):  # F5.10
    if (a.h, a.T) == (sigma.h, sigma.Th):
        return True  # names the chain's own entry
    return (a.hf, a.Tf) in sigma.pending_finality and a.hf < a.h < sigma.h


def process_attestation(sigma, a):  # F5.15
    fp = dict(sigma.finality_participation)
    if (a.hf, a.Tf) in sigma.pending_finality:
        fp[a.hf] = fp[a.hf] | {a.v}
    tp, pr = sigma.target_participation, sigma.progress
    if a.h == sigma.h and a.T == sigma.Th:
        pr = pr | {a.v}
        if not a.tau:
            tp = tp | {a.v}
    return replace(sigma, finality_participation=tuple(sorted(fp.items())), target_participation=tp, progress=pr)


def advance_height(sigma):  # F5.36
    return replace(sigma, h=sigma.h + 1, Th=sigma.L, target_participation=frozenset(), progress=frozenset())


def process_height_events(sigma, P):  # F5.24
    pend = list(sigma.pending_finality)
    fp = dict(sigma.finality_participation)
    fin = [(j, T) for (j, T) in pend if len(fp.get(j, ())) >= P.q]
    if fin:
        j, T = max(fin)
        sigma = replace(sigma, F=T, hF=j)
    pend = [(j, T) for (j, T) in pend if j > sigma.hF]
    fp = {j: fp[j] for (j, _) in pend}
    if len(sigma.target_participation) >= P.q:
        pend.append((sigma.h, sigma.Th))
        fp[sigma.h] = frozenset()
        pend = pend[-P.KW:]
        fp = {j: fp[j] for (j, _) in pend}
        sigma = replace(sigma, J=sigma.Th, hj=sigma.h, pending_finality=tuple(pend),
                        finality_participation=tuple(sorted(fp.items())))
        return advance_height(sigma)
    sigma = replace(sigma, pending_finality=tuple(pend), finality_participation=tuple(sorted(fp.items())))
    if len(sigma.progress) >= P.q and sigma.s >= BLOCKS[sigma.Th].slot + P.delta_t:
        return advance_height(sigma)  # timeouts count only after the delay
    return sigma


def state_transition(sigma, B, P):  # F5.1; raises AssertionError on an invalid block
    assert B.proposer == P.proposer(B.slot)
    assert BLOCKS[B.parent].slot < B.slot
    assert all(valid_attestation(sigma, a) for a in B.attestations)
    sigma = replace(sigma, s=B.slot)
    for a in B.attestations:
        sigma = process_attestation(sigma, a)
    sigma = replace(sigma, L=B.root)
    return process_height_events(sigma, P)


def chain_state(B, P):
    """Σ.σ[B]: pure in the block (and so in its parent's state); cached globally."""
    if B.root not in STATE:
        STATE[B.root] = state_transition(STATE[B.parent], B, P)
        INCL[B.root] = INCL[B.parent] | frozenset(B.attestations)
    return STATE[B.root]


# ------------------------------------------------------- finality gadget (Figure 3)


@dataclass
class Frame:  # Φ = (tree, fc_root, viable_heads)
    tree: frozenset
    fc_root: str
    viable_heads: frozenset
    F: str


class FG:
    def __init__(self, P):
        self.P = P
        self.T = {GEN}
        self.F = self.J = GEN
        self.hj, self.hmax = 0, 1
        self.pool, self._pool_set = [], set()
        self._frame = None

    def sigma(self, root):
        return STATE[root]

    def on_block(self, B):  # F3.1; returns whether B is accepted
        if B.root in self.T or B.parent not in self.T or not prec(self.F, B.root):
            return False
        try:
            sigma = chain_state(B, self.P)
        except AssertionError:
            return False
        self.T.add(B.root)
        self._frame = None
        self.update_finality(sigma)
        for a in B.attestations:
            self.on_attestation(a)
        return True

    def on_attestation(self, a):  # F3.10
        if a not in self._pool_set:
            self._pool_set.add(a)
            self.pool.append(a)

    def update_finality(self, sigma):  # F3.16
        self.hmax = max(self.hmax, sigma.h)
        if prec(self.F, sigma.J) and (sigma.hj, sigma.J) > (self.hj, self.J):
            self.J, self.hj = sigma.J, sigma.hj
        if self.F != sigma.F and prec(self.F, sigma.F) and prec(sigma.F, self.J) and self.has_viable_descendant(sigma.F):
            self.F = sigma.F
        self._frame = None

    def contest(self):  # F3.22: the whole tree, never the tree of a voter
        if self.hmax != self.hj + 1:
            return False
        return any(STATE[B].h == self.hmax and prec(self.F, B) and not prec(self.J, B) for B in self.T)

    def head_height_floor(self):  # F3.27
        return self.hmax if self.contest() else self.hmax - 1

    def fc_root(self):  # F3.31
        if self.hmax == self.hj + 1 and not self.contest():
            return self.J
        return self.F

    def is_viable(self, B, floor=None):  # F3.35
        return STATE[B].h >= (self.head_height_floor() if floor is None else floor)

    def has_viable_descendant(self, B):  # F3.37
        floor = self.head_height_floor()
        return any(prec(B, X) and self.is_viable(X, floor) for X in self.T)

    def frame(self):  # F3.39 fg_to_ac
        if self._frame is None:
            tree = frozenset(B for B in self.T if prec(self.F, B))
            root = self.fc_root()
            floor = self.head_height_floor()
            viable = frozenset(B for B in tree if prec(root, B) and self.is_viable(B, floor))
            self._frame = Frame(tree, root, viable, self.F)
        return self._frame

    def proposal_attestations(self, H):  # F3.44
        sigma, incl = STATE[H], INCL[H]
        return [a for a in self.pool if a not in incl and valid_attestation(sigma, a)]

    def attest_inputs(self, fg_confirmed, head):  # F3.12, the part that reads Σ
        c, hd = STATE[fg_confirmed], STATE[head]
        return c.h, c.Th, hd.hj, hd.J, hd.hF


# ------------------------------------------------------- validator client (Figure 4)


class Client:
    """The anti-slashing record Λ of one validator and create_attestation."""

    def __init__(self, v):
        self.v = v
        self.target, self.timeout, self.lock = {}, {}, {}
        self.sent = set()

    def finality_pair(self, hj, J, hF):  # F4.1
        if hj > hF:
            if self.target.get(hj) in (None, J) and not self.timeout.get(hj) and self.lock.get(hj) in (None, J):
                return hj, J
        return None, None

    def height_pair(self, hc, Tc, hf, Tf):  # F4.6
        if hc is None:
            return None, None, None
        lock = self.lock.get(hc)
        if hc == hf:
            lock = Tf
        if self.timeout.get(hc):
            return hc, Tc, True
        if lock is not None:
            return (hc, Tc, False) if lock == Tc else (None, None, None)
        if self.target.get(hc) in (None, Tc):
            return hc, Tc, False
        return hc, Tc, True

    def create_attestation(self, hc, Tc, hj, J, hF):  # F4.19
        hf, Tf = self.finality_pair(hj, J, hF)
        h, T, tau = self.height_pair(hc, Tc, hf, Tf)
        if h is None:
            return None
        if any(b[0] == h and (not tau or b[1] == T) for b in self.sent):
            return None  # a target only as the first vote at h; no entry twice
        if hf is not None and h <= hf:
            hf, Tf = None, None
        a = Att(self.v, h, T, tau, hf, Tf)
        self.record(a)
        return a

    def record(self, a):  # F4.30, the only writer of Λ
        self.sent.add((a.h, a.T, a.tau, a.hf, a.Tf))
        if a.Tf is not None:
            self.lock[a.hf] = a.Tf
        if a.h is not None:
            if not a.tau and a.h not in self.target:
                self.target[a.h] = a.T
            if a.tau:
                self.timeout[a.h] = True


# ------------------------------------------------- available chain: Goldilocks (3)


def equivocators_of(votes):
    seen = {}
    eq = set()
    for x in votes:
        if x.v in seen and seen[x.v] != x:
            eq.add(x.v)
        seen.setdefault(x.v, x)
    return eq


def ghost(anchor, tree, score, eligible):  # F9.5
    children = {}
    for B in tree:
        children.setdefault(BLOCKS[B].parent, []).append(B)
    H = anchor
    while True:
        ch = [B for B in children.get(H, ()) if eligible(B)]
        if not ch:
            return H
        H = min(ch, key=lambda B: (-score(B), B))  # arg max, ties by root order


class AC:
    def __init__(self, P, val_indices, log=None):
        self.P = P
        self.local = val_indices  # validators of this node; K_s = V, so all are on every committee
        self.gf_votes = {}  # s -> [votes] in order of acceptance
        self.vts = {}  # timestamp[vote]
        self.bts = {GEN: NEG_INF}  # timestamp[block]
        self.saved_confirmation = {}
        self.locks = {}  # deadline -> block
        self.fast_confirmed = set()
        self.latest_confirmed = GEN
        self.restart_time = NEG_INF
        self.log = log if log is not None else (lambda *a, **k: None)

    # --- helpers
    def votes(self, s):
        return self.gf_votes.get(s, [])

    def resolution_time(self, phi, vote):  # F8.1
        if vote.H not in phi.tree or BLOCKS[vote.H].slot > vote.s:
            return INF
        return max(self.vts[vote], self.bts[vote.H])

    def live_locks(self, phi, t):
        return [(B, d) for d, B in self.locks.items() if d > t and B in phi.tree]

    def is_locked(self, phi, t, B):
        return any(prec(B, L) for L, _ in self.live_locks(phi, t))

    def vetoed(self, phi, t, C):
        return any(conflicts(C, L) for L, _ in self.live_locks(phi, t))

    # --- Figure 7
    def on_tick(self, phi, t, node):  # F7.1
        P = self.P
        s = P.slot(t)
        for d in [d for d in self.locks if d <= t]:
            self.log("lock_expire", block=self.locks[d], deadline=d)
            del self.locks[d]
        if t == P.t(s) + P.delta:
            if self.restart_time <= P.t(s - 1):
                if s > 0:
                    self.unlock(phi, t, s - 1)
                return self.goldfish_vote(phi, t)
        if t == P.t(s) + 2 * P.delta and s > 0:
            self.update_confirmation(phi, t, s - 1)
        return None

    def on_block(self, t, B):  # F7.14
        self.bts[B.root] = t
        for vote in B.votes:
            self.on_goldfish_vote(t, vote)

    def on_goldfish_vote(self, t, vote):  # F7.18
        s = self.P.slot(t)
        pool = self.gf_votes.setdefault(vote.s, []) if s - 1 <= vote.s <= s else None
        if pool is None or not (0 <= vote.v < self.P.n) or vote in self.vts:
            return
        if len({x for x in pool if x.v == vote.v}) >= 2:
            return
        pool.append(vote)
        self.vts[vote] = t

    def proposal(self, phi, t):  # F7.25, runs at t_s
        s = self.P.slot(t)
        if self.restart_time > self.P.t(s - 1):
            return None
        votes = list(self.votes(s - 1))
        support = [x for x in votes if self.resolution_time(phi, x) < INF]
        H = self.get_head(phi, t, votes, support, s - 1)
        return H, votes, support

    def to_fg(self, phi, t):  # F7.33, runs at a_r after the update of slot rR
        s = self.P.slot(t)
        votes = self.votes(s)
        support = [x for x in votes if self.resolution_time(phi, x) < INF]
        head = self.get_head(phi, t, votes, support, s)
        vt = self.viable_tree(phi, phi.tree)
        fc = [B for B in self.fast_confirmed if B in vt]
        return (deepest(fc) if fc else None), head

    def head(self, phi, t):  # F7.40
        P = self.P
        s = P.slot(t)
        s_star = s if t >= P.t(s) + 2 * P.delta else s - 1
        votes = self.votes(s_star)
        support = [x for x in votes if self.resolution_time(phi, x) < INF]
        return self.get_head(phi, t, votes, support, s_star)

    def confirmed(self, phi, t):  # F7.46, user-facing
        C = self.latest_confirmed if self.latest_confirmed in phi.tree else phi.F
        return common_ancestor(C, self.head(phi, t))

    # --- Figure 8
    def unlock(self, phi, t, s):  # F8.6, at t_s + 5Δ
        votes = self.votes(s)
        eq = equivocators_of(votes)
        heads = [x.H for x in votes if x.v not in eq and self.resolution_time(phi, x) < INF]
        n = self.P.n
        new = {}
        for d, B in self.locks.items():
            if not (d > t and B in phi.tree):
                continue  # only the live locks survive (F8.11)
            chain = sorted((X for X in ANC[B] if X in phi.tree and prec(phi.F, X)), key=lambda X: -DEPTH[X])
            lb = next(X for X in chain if 2 * sum(1 for H in heads if conflicts(H, X)) < n)
            if lb != B:
                self.log("lock_back", block=B, to=lb, deadline=d, slot=s)
            new[d] = lb
        self.locks = new

    def confirmation_score(self, phi, s, B):  # F8.15
        votes = self.votes(s)
        eq = equivocators_of(votes)
        cut = self.P.t(s) + 2 * self.P.delta
        return sum(1 for x in votes if x.v not in eq and self.resolution_time(phi, x) < cut and prec(B, x.H))

    def get_confirmation(self, phi, s):  # F8.19
        votes = self.votes(s)
        voters = len({x.v for x in votes})
        eq = equivocators_of(votes)
        cut = self.P.t(s) + 2 * self.P.delta
        early = [x.H for x in votes if x.v not in eq and self.resolution_time(phi, x) < cut]

        def score(B):
            return sum(1 for H in early if prec(B, H))

        def eligible(B):
            return 2 * score(B) > voters

        H = ghost(phi.F, phi.tree, score, eligible)
        return H if eligible(H) else None

    def update_confirmation(self, phi, t, s):  # F8.25, at t_s + 6Δ
        P = self.P
        self.fast_confirmed = set()
        if self.restart_time > P.t(s):
            self.saved_confirmation[s] = None
            return
        C = self.get_confirmation(phi, s)
        self.saved_confirmation[s] = C
        if C is None or self.vetoed(phi, t, C):
            self.log("confirm", slot=s, result=C, vetoed=C is not None)
            return
        old = self.latest_confirmed
        self.latest_confirmed = self.advance(phi, old, C)
        if old in phi.tree and conflicts(old, C):
            self.log("confirm_switch", slot=s, old=old, new=C)
        path = [B for B in phi.tree if B != GEN and prec(B, C)]

        def fast(B):
            return 2 * self.confirmation_score(phi, s, B) >= P.n

        def slow(B):
            for j in range(s - P.k + 1, s):
                c = self.saved_confirmation.get(j)
                if c is None or c not in phi.tree or not prec(B, c):
                    return False
            return True

        fasts = {B for B in path if fast(B)}
        self.fast_confirmed = fasts
        cands = [B for B in path if B in fasts or slow(B)]
        lb = deepest(cands) if cands else None
        how = None
        if lb is not None:
            d = P.t(s + P.k) + 5 * P.delta
            self.locks[d] = lb
            how = "fast" if lb in fasts else "slow"
        self.log("confirm", slot=s, result=C, vetoed=False, lock=lb, how=how)

    def restart(self, phi, t):  # F7.50: keep the locks and the record, reset the rest
        locks, record = self.locks, self.latest_confirmed
        self.__init__(self.P, self.local, self.log)
        self.locks, self.latest_confirmed = locks, record
        self.restart_time = t
        for B in sorted(phi.tree - {GEN}, key=lambda r: DEPTH[r]):  # parent order
            self.on_block(t, BLOCKS[B])

    @staticmethod
    def advance(phi, old, C):  # F8.41
        if C is None:
            return old
        if old in phi.tree and prec(C, old):
            return old
        return C

    # --- Figure 9
    @staticmethod
    def goldfish_score(votes, support, s, B, eq=None):  # F9.1
        if eq is None:
            eq = equivocators_of(votes)
        sup = {x.v for x in support if x.s == s and x.v not in eq and prec(B, x.H)}
        return len(eq) + len(sup)

    def goldfish_fork_choice(self, phi, t, anchor, tree, votes, support, s):  # F9.20
        eq = equivocators_of(votes)
        voters = len({x.v for x in votes})
        cur = self.P.slot(t)
        sup = [x for x in support if x.s == s and x.v not in eq]

        def score(B):
            return len(eq) + len({x.v for x in sup if prec(B, x.H)})

        def eligible(B):  # F9.12
            if BLOCKS[B].parent not in phi.viable_heads:
                return True
            if BLOCKS[B].slot == cur:
                return True
            return 2 * score(B) > voters

        return ghost(anchor, tree, score, eligible)

    @staticmethod
    def viable_tree(phi, tree):  # F9.24
        heads = [W for W in tree if W in phi.viable_heads]
        return frozenset(B for B in tree if prec(phi.fc_root, B) and any(prec(B, W) for W in heads))

    def get_anchor(self, phi, t):  # F9.26
        vt = self.viable_tree(phi, phi.tree)
        locked = [B for B in vt if self.is_locked(phi, t, B)]
        return deepest(locked) if locked else phi.fc_root

    def get_head_in_tree(self, phi, t, tree, votes, support, s):  # F9.28
        return self.goldfish_fork_choice(phi, t, self.get_anchor(phi, t), tree, votes, support, s)

    def get_head(self, phi, t, votes, support, s):  # F9.31
        return self.get_head_in_tree(phi, t, self.viable_tree(phi, phi.tree), votes, support, s)

    def voter_block_tree(self, phi, s):  # F9.33
        freeze = self.P.t(s - 1) + 3 * self.P.delta
        props = [P_ for P_ in phi.tree if BLOCKS[P_].slot == s]
        return frozenset(B for B in phi.tree if self.bts.get(B, INF) < freeze or any(prec(B, P_) for P_ in props))

    def goldfish_vote(self, phi, t):  # F9.37, runs at t_s + Δ; returns the votes to broadcast
        P = self.P
        s = P.slot(t)
        freeze = P.t(s - 1) + 3 * P.delta
        votes = [x for x in self.votes(s - 1) if self.vts[x] < freeze]
        support = [x for x in votes if self.resolution_time(phi, x) < freeze]
        for B in phi.tree:
            if BLOCKS[B].slot == s:
                blk = BLOCKS[B]
                votes += [x for x in blk.votes if x not in votes]
                support += [x for x in blk.support_votes
                            if x.s == s - 1 and x.H in phi.tree and BLOCKS[x.H].slot <= s - 1 and x not in support]
        tree = self.viable_tree(phi, self.voter_block_tree(phi, s))
        H = self.get_head_in_tree(phi, t, tree, votes, support, s - 1)
        out = [Vote(v, s, H) for v in self.local]
        for x in out:
            self.on_goldfish_vote(t, x)
        return out


# ----------------------------------------------------------------- node (Figure 2)


class Node:
    def __init__(self, nid, P, validators, log=None):
        self.id, self.P = nid, P
        self.validators = list(validators)
        self.log = log if log is not None else (lambda *a, **k: None)
        self.fg = FG(P)
        self.ac = AC(P, self.validators, log=lambda kind, **kw: self.log(kind, node=nid, **kw))
        self.clients = {v: Client(v) for v in self.validators}
        self.orphans = {}  # parent root -> [blocks]: re-delivery of a refused block (1.6)
        self.last_fg_confirmed = None

    def phi(self):
        return self.fg.frame()

    def on_tick(self, t):  # F2.1; returns [(kind, payload)] to broadcast
        P = self.P
        s = P.slot(t)
        out = []
        votes = self.ac.on_tick(self.phi(), t, self)
        if votes:
            out.append(("vote", tuple(votes)))
        if s > 0 and t == P.t(s) and P.proposer(s) in self.clients:
            B = self.propose_block(t)
            if B is not None:
                out.append(("block", B))
        if t == P.action_time(P.round(s)):
            atts = self.attest(t)
            if atts:
                out.append(("att", tuple(atts)))
        return out

    def on_block(self, B, t):  # F2.8
        if B.slot > self.P.slot(t):
            return False
        if B.parent not in self.fg.T and B.root not in self.fg.T:
            self.orphans.setdefault(B.parent, []).append(B)
            return False
        if not self.fg.on_block(B):
            return False
        self.ac.on_block(t, B)
        for child in self.orphans.pop(B.root, []):
            self.on_block(child, t)
        return True

    def restart(self, t):  # section 1.3: keep Λ, Σ and the clock; A <- ac_restart(A, Φ, t)
        self.ac.restart(self.phi(), t)
        self.log("restart")

    def on_vote(self, vote, t):
        self.ac.on_goldfish_vote(t, vote)

    def on_attestation(self, a):
        self.fg.on_attestation(a)

    def propose_block(self, t):  # F2.18
        P = self.P
        s = P.slot(t)
        prop = self.ac.proposal(self.phi(), t)
        if prop is None:
            return None
        H, votes, support = prop
        atts = self.fg.proposal_attestations(H)
        B = make_block(s, H, P.proposer(s), tuple(atts), tuple(votes), tuple(support))
        self.on_block(B, t)
        return B

    def attest(self, t):  # F2.26
        phi = self.phi()
        fgc, head = self.ac.to_fg(phi, t)
        self.last_fg_confirmed = fgc
        self.log("fg_pair", fg_confirmed=fgc, head=head)
        if fgc is not None and not (fgc in self.ac.viable_tree(phi, phi.tree) and prec(fgc, head)):
            self.log("violation", what="requirement 2: fg_confirmed in the viable tree, head extends it")
        if fgc is None:
            return []
        hc, Tc, hj, J, hF = self.fg.attest_inputs(fgc, head)
        out = []
        for v, c in self.clients.items():
            a = c.create_attestation(hc, Tc, hj, J, hF)
            if a is not None:
                out.append(a)
                self.on_attestation(a)
        return out

    # --- outputs
    def head(self, t):
        return self.ac.head(self.phi(), t)

    def confirmed(self, t):
        return self.ac.confirmed(self.phi(), t)
