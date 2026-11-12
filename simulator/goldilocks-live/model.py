"""Goldilocks, live spec: an executable transcription of ethlabs-org/eth-consensus-lean at 4a63033e
(10 Nov 2026), specs/goldilocks/tex/{goldilocks-spec.tex, shared/composition.tex, shared/fg.tex}.

The model of ../goldilocks/model.py follows the 22 Oct 2026 text. This one follows the live text,
figure by figure, under the spec's figure names:

  Node: handlers and duties               (composition.tex, alg:node)      -> Node
  FG: handlers, finality caches, frame    (fg.tex, alg:fg-store)           -> FG
  FG: validator client                    (fg.tex, alg:attn-full)          -> Client
  FG: state transition                    (fg.tex, alg:chain-full)         -> state_transition
  Goldilocks: initial state and joined    (alg:sa-initial)                 -> AC.__init__, AC.joined
  Goldilocks: votes and views             (alg:sa-views)                   -> AC
  Goldilocks: locks and unlocking         (alg:sa-locks)                   -> AC
  Goldilocks: fork choice                 (alg:sa-fc)                      -> AC
  Goldilocks: confirmation                (alg:sa-gate)                    -> AC
  Goldilocks: the vote and the receipt    (alg:sa-vote)                    -> AC
  Goldilocks: block, tick, proposal, FG   (alg:sa-events)                  -> AC
  Goldilocks: restart                     (alg:sa-restart)                 -> AC.restart

What changed against the 22 Oct text, and where it is here:
  - honest nodes forward every object they accept, also the votes and attestations a block
    carries (composition.tex, Model)                                -> Node receipt handlers
  - the FG update runs after every tick, not once per round        -> Node.on_tick, AC.to_fg
  - a node votes as soon as it holds a ready proposal, else at t_s+Δ -> AC.try_vote
  - the vote reads a merged view: pre-freeze votes plus the payload of the slot's proposals,
    and walks the full tree when its voter block tree has no viable block -> AC.try_vote
  - optimistic confirmation at 3/4 of the committee before t_s+2Δ  -> AC.optimistic_confirmation
  - locks (B, j, f, e) with an expiry e; fast locks graded by fast_expiry; a lock lives
    until t_{e+1}                                                    -> AC.fast_expiry, live_locks
  - a vetoed update still writes its locks below the vetoing lock; fast and slow locks are
    written separately                                               -> AC.update_confirmation
  - unlocking runs before each vote and proposal, against the vote's own view -> AC.unlock
  - the FG source is the deepest live fast lock of slot slot(t)-2 or later -> AC.to_fg
  - FG: K_W = 2, the finality pair read from the entry state, and a height whose previous
    height is justified waits for its predecessor                    -> Client, process_height_events

Times are integers in milliseconds. Blocks are content-addressed and shared between nodes
through the global registry BLOCKS; chain states are pure in (parent state, block), so they are
cached globally as well.

Simplifications, as in ../goldilocks/model.py: a node hosts several validators and keeps one AC
state for all of them; no signatures or slashing evidence; every validator is on every committee
(K_s = V). A batch of votes from one message is admitted vote by vote, and the checks that the
spec runs after each receipt (the optimistic check, then the vote check) run once after the
batch: the optimistic lock on the deepest passing block covers the locks of the earlier votes,
and the vote check cannot fire on a vote receipt (readiness reads only blocks).
"""

import hashlib
import math
from collections import namedtuple
from dataclasses import dataclass, field, replace

NEG_INF = -math.inf
INF = math.inf
GEN = "G"  # root of genesis

Att = namedtuple("Att", "v h T tau hf Tf")  # (val_index, h, T, τ, h_f, T_f)
Vote = namedtuple("Vote", "v s H")  # Goldfish vote (val_index, s, B)
Lock = namedtuple("Lock", "B j f e")  # block, slot of its confirmation, fast bit, expiry


@dataclass(frozen=True)
class Params:
    n: int = 64  # validators, weight 1 each
    delta: int = 1500  # Δ in ms; a slot is 4Δ
    delta_f: int = 1500  # Δ_F > 0, delivery bound of attestation rows
    R: int = 8  # slots per round: the network's aggregation heartbeat; no rule reads it
    k: int = 4  # slow window: every lock has j+2 <= e <= j+k
    c: int = 2  # fast increment of fast_expiry
    KW: int = 2  # pending-finality window K_W
    delta_t: int = 8  # timeout delay in slots, >= x + c_F + k_F
    seed: int = 0
    lean_finality: bool = False  # accepted for the shared CLI; the live model has no such switch

    @property
    def q(self):
        return math.ceil(2 * self.n / 3)

    @property
    def slot_ms(self):
        return 4 * self.delta

    @property
    def c_F(self):
        return math.ceil((6 * self.delta + self.delta_f) / (4 * self.delta))

    def t(self, s):  # t_s = 4Δs (also for negative s)
        return 4 * self.delta * s

    def slot(self, t):  # slot(t) = ⌊t/(4Δ)⌋
        return int(t // (4 * self.delta))

    def round(self, s):
        return s // self.R

    def proposer(self, s):
        h = hashlib.sha256(f"proposer-{self.seed}-{s}".encode()).digest()
        return int.from_bytes(h[:8], "big") % self.n

    def check(self):
        assert not self.lean_finality, "the live model has no --lean-finality"
        assert self.R >= self.c_F, f"Goldilocks requires R >= {self.c_F}"
        assert self.k >= 2 and self.c >= 2 and self.KW >= 1 and self.delta_f > 0
        assert self.delta_t >= self.c_F, f"delta_t >= x + c_F + k_F >= {self.c_F}"


# ---------------------------------------------------------------- blocks (composition.tex)


@dataclass(frozen=True)
class Block:
    root: str
    slot: int
    parent: str
    proposer: int
    attestations: tuple = ()
    votes: tuple = ()  # B.votes: slot-(B.slot-1) Goldfish votes
    support_votes: tuple = ()  # the entries of B.votes resolved at proposal time


BLOCKS = {GEN: Block(GEN, 0, None, -1)}
DEPTH = {GEN: 0}
ANC = {GEN: frozenset([GEN])}  # ancestor-or-self sets: B ⪯ C  iff  B in ANC[C]


def make_block(slot, parent, proposer, attestations, votes, support_votes):
    # the digest of (parent root, slot, attestations, votes, support_votes)
    root = hashlib.sha256(repr((parent, slot, attestations, votes, support_votes)).encode()).hexdigest()[:16]
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


# ------------------------------------------------------- FG: state transition (fg.tex)


@dataclass(frozen=True)
class ChainState:
    L: str = GEN
    s: int = 0
    h: int = 1
    Th: str = GEN
    target_participation: frozenset = frozenset()  # Q_target
    progress: frozenset = frozenset()  # Q_prog
    pending_finality: tuple = ()  # ((j, T), ...) increasing j, at most K_W
    finality_participation: tuple = ()  # ((j, frozenset), ...) aligned with pending_finality
    J: str = GEN
    hj: int = 0
    F: str = GEN
    hF: int = 0

    def fin_part(self, j):
        return dict(self.finality_participation).get(j, frozenset())


STATE = {GEN: ChainState()}
INCL = {GEN: frozenset()}  # attestations included on the chain ending at a block


def previous_height_justified(sigma):  # the chain entered σ.h by justifying σ.h - 1
    return sigma.hj > 0 and sigma.hj == sigma.h - 1


def valid_attestation(sigma, a):
    if (a.h, a.T) == (sigma.h, sigma.Th):
        return True  # names the chain's own entry
    return (a.hf, a.Tf) in sigma.pending_finality and a.hf < a.h < sigma.h  # an older vote, useful pair


def process_attestation(sigma, a):
    fp = dict(sigma.finality_participation)
    if (a.hf, a.Tf) in sigma.pending_finality:
        fp[a.hf] = fp[a.hf] | {a.v}
    tp, pr = sigma.target_participation, sigma.progress
    if a.h == sigma.h and a.T == sigma.Th:
        pr = pr | {a.v}
        if not a.tau:
            tp = tp | {a.v}
    return replace(sigma, finality_participation=tuple(sorted(fp.items())), target_participation=tp, progress=pr)


def advance_height(sigma):
    return replace(sigma, h=sigma.h + 1, Th=sigma.L, target_participation=frozenset(), progress=frozenset())


def process_height_events(sigma, P):
    pend = list(sigma.pending_finality)
    fp = dict(sigma.finality_participation)
    fin = [(j, T) for (j, T) in pend if len(fp.get(j, ())) >= P.q]
    if fin:
        j, T = max(fin)
        sigma = replace(sigma, F=T, hF=j)
    pend = [(j, T) for (j, T) in pend if j > sigma.hF]
    fp = {j: fp[j] for (j, _) in pend}
    sigma = replace(sigma, pending_finality=tuple(pend), finality_participation=tuple(sorted(fp.items())))
    if len(sigma.target_participation) >= P.q and (not previous_height_justified(sigma) or sigma.hF == sigma.hj):
        pend.append((sigma.h, sigma.Th))  # such a height waits for its predecessor
        fp[sigma.h] = frozenset()
        pend = pend[-P.KW:]
        fp = {j: fp[j] for (j, _) in pend}
        sigma = replace(sigma, J=sigma.Th, hj=sigma.h, pending_finality=tuple(pend),
                        finality_participation=tuple(sorted(fp.items())))
        return advance_height(sigma)
    if len(sigma.progress) >= P.q and sigma.s >= BLOCKS[sigma.Th].slot + P.delta_t:
        return advance_height(sigma)  # timeouts count only after the delay
    return sigma


def state_transition(sigma, B, P):  # raises AssertionError on an invalid block
    assert B.proposer == P.proposer(B.slot)
    assert BLOCKS[B.parent].slot < B.slot
    assert all(valid_attestation(sigma, a) for a in B.attestations)  # against the parent's state
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


# ------------------------------------------- FG: handlers, finality caches, frame (fg.tex)


@dataclass
class Frame:  # Φ = (tree, fc_root, allowed)
    tree: frozenset
    fc_root: str
    viable_heads: frozenset  # Φ.allowed: the blocks on which a head walk may stop
    F: str
    _full: frozenset = field(default=None, repr=False)

    @property
    def allowed(self):
        return self.viable_heads

    def full_viable(self):  # filtered(Φ, Φ.tree), cached with the frame
        if self._full is None:
            self._full = viable_tree(self, self.tree)
        return self._full


def viable_tree(phi, tree):
    """filtered(Φ, tree): the blocks of tree that extend Φ.fc_root and have a descendant in
    tree ∩ Φ.allowed."""
    under = set()
    for W in tree:
        if W in phi.viable_heads:
            under |= ANC[W]
    return frozenset(B for B in under if B in tree and prec(phi.fc_root, B))


class FG:
    def __init__(self, P):
        self.P = P
        self.T = {GEN}
        self.F = self.J = GEN
        self.hj, self.hmax = 0, 1
        self.pool, self._pool_set = [], set()
        self._frame = None

    def on_block(self, B):  # fg_on_block; returns (accepted, the attestations new to the pool)
        if B.root in self.T or B.parent not in self.T or not prec(self.F, B.root):
            return False, []
        try:
            sigma = chain_state(B, self.P)
        except AssertionError:
            return False, []  # a failed assertion: no write
        self.T.add(B.root)
        self._frame = None
        self.update_finality(sigma)
        return True, [a for a in B.attestations if self.on_attestation(a)]

    def on_attestation(self, a):  # fg_on_attestation: one copy of each; returns whether it is new
        if a in self._pool_set:
            return False
        self._pool_set.add(a)
        self.pool.append(a)
        return True

    def attest_inputs(self, fg_confirmed):  # fg_attest, the part that reads Σ
        c = STATE[fg_confirmed]
        return c.h, c.Th, STATE[c.Th]  # (h_c, T_c, σ_e): the entry state has σ_e.h = h_c

    def update_finality(self, sigma):
        self.hmax = max(self.hmax, sigma.h)
        if prec(self.F, sigma.J) and (sigma.hj, sigma.J) > (self.hj, self.J):  # lex order
            self.J, self.hj = sigma.J, sigma.hj
        if self.F != sigma.F and prec(self.F, sigma.F) and prec(sigma.F, self.J) and self.has_viable_descendant(sigma.F):
            self.F = sigma.F
        self._frame = None

    def contest(self):  # fg_contest: the whole tree, never the tree of a voter
        if self.hmax != self.hj + 1:
            return False
        return any(STATE[B].h == self.hmax and prec(self.F, B) and not prec(self.J, B) for B in self.T)

    def head_height_floor(self):
        return self.hmax if self.contest() else self.hmax - 1

    def fc_root(self):  # get_fc_root
        if self.hmax == self.hj + 1 and not self.contest():
            return self.J
        return self.F

    def has_viable_descendant(self, B):
        floor = self.head_height_floor()
        return any(prec(B, X) and STATE[X].h >= floor for X in self.T)

    def frame(self):  # fg_to_ac
        if self._frame is None:
            tree = frozenset(B for B in self.T if prec(self.F, B))
            root = self.fc_root()
            floor = self.head_height_floor()
            heads = frozenset(B for B in tree if prec(root, B) and STATE[B].h >= floor)
            self._frame = Frame(tree, root, heads, self.F)
        return self._frame

    def proposal_attestations(self, H):
        sigma, incl = STATE[H], INCL[H]
        return [a for a in self.pool if a not in incl and valid_attestation(sigma, a)]


# ------------------------------------------------------- FG: validator client (fg.tex)


class Client:
    """The anti-slashing record Λ of one validator and create_attestation."""

    def __init__(self, v):
        self.v = v
        self.target, self.timeout, self.lock = {}, {}, {}  # h -> T, h -> {T}, h -> T
        self.sent = set()

    def permits(self, j, T):  # the record allows the finality pair (j, T)
        return (self.target.get(j) in (None, T) and self.timeout.get(j, set()) <= {T}
                and self.lock.get(j) in (None, T))

    def finality_pair(self, sigma_e):  # σ_e: the entry state of the source
        if previous_height_justified(sigma_e):  # the predecessor, even if a later state finalized it
            if self.permits(sigma_e.hj, sigma_e.J):
                return sigma_e.hj, sigma_e.J
            return None, None
        ok = [(j, T) for (j, T) in sigma_e.pending_finality if self.permits(j, T)]
        return max(ok) if ok else (None, None)  # the newest permitted pair

    def height_pair(self, hc, Tc):
        if hc is None:
            return None, None, None
        if self.lock.get(hc) not in (None, Tc):
            return None, None, None  # locked elsewhere: wait out the height
        if self.timeout.get(hc):
            return hc, Tc, True  # select a timeout for the current entry
        if self.target.get(hc) in (None, Tc):
            return hc, Tc, False  # vote for the target of that chain
        return hc, Tc, True  # otherwise time out at h_c

    def create_attestation(self, hc, Tc, sigma_e):
        hf, Tf = self.finality_pair(sigma_e)  # below σ_e.h = h_c
        h, T, tau = self.height_pair(hc, Tc)
        if h is None:
            return None  # no attestation without a height pair
        if any(b[0] == h and (not tau or b[1] == T) for b in self.sent):
            return None  # a target only as the first vote at h; no entry twice
        a = Att(self.v, h, T, tau, hf, Tf)
        self.record(a)
        return a

    def record(self, a):  # record_attestation, the only writer of Λ
        self.sent.add((a.h, a.T, a.tau, a.hf, a.Tf))
        if a.Tf is not None:
            self.lock[a.hf] = a.Tf
        if a.h is not None:
            if not a.tau and a.h not in self.target:
                self.target[a.h] = a.T
            if a.tau:
                self.timeout.setdefault(a.h, set()).add(a.T)


# ------------------------------------------------------------- available chain: Goldilocks


def equivocators(votes):
    seen, eq = {}, set()
    for x in votes:
        if x.v in seen and seen[x.v] != x:
            eq.add(x.v)
        seen.setdefault(x.v, x)
    return eq


def supporters(votes, support, s, B, eq=None):
    eq = equivocators(votes) if eq is None else eq
    return {x.v for x in support if x.s == s and x.v not in eq and prec(B, x.H)}


def ghost(anchor, tree, score, eligible):
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
    def __init__(self, P, val_indices, log=None):  # initial_ac
        self.P = P
        self.local = val_indices  # validators of this node; K_s = V, so all are on every committee
        self.gf_pool = {}  # s -> [votes] in the order of acceptance
        self.ts = {GEN: NEG_INF}  # timestamp[x] of a vote or a block
        self.saved_confirmation = {}  # s -> block or None (⊥ when absent)
        self.locks = frozenset()  # {Lock(B, j, f, e)}
        self.latest_confirmed = GEN
        self.fg_reported = GEN
        self.voted_slot = -1
        self.restart_time = NEG_INF
        self.log = log if log is not None else (lambda *a, **k: None)

    def joined(self, t):  # awake since the start of the previous slot
        return self.restart_time <= self.P.t(self.P.slot(t) - 1)

    # --- votes and views
    def pool(self, s):
        return self.gf_pool.get(s, [])

    def on_goldfish_vote(self, t, vote):  # admission; returns whether the vote was accepted
        s = self.P.slot(t)
        if vote.s < s - 1 or vote.s > s or not (0 <= vote.v < self.P.n) or vote in self.ts:
            return False
        pool = self.gf_pool.setdefault(vote.s, [])
        if len({x for x in pool if x.v == vote.v}) >= 2:
            return False
        pool.append(vote)
        self.ts[vote] = t
        return True

    @staticmethod
    def resolved(phi, vote):
        return vote.H in phi.tree and BLOCKS[vote.H].slot <= vote.s

    def resolution_time(self, phi, vote):
        if not self.resolved(phi, vote):
            return INF
        return max(self.ts[vote], self.ts[vote.H])

    def vote_view(self, phi, s, cutoff):
        votes = [x for x in self.pool(s) if self.ts[x] < cutoff]
        support = [x for x in votes if self.resolution_time(phi, x) < cutoff]
        return votes, support

    def latest_view(self, phi, t):
        P = self.P
        s = P.slot(t)
        s_star = s if t >= P.t(s) + 2 * P.delta else s - 1  # the latest slot whose votes are due
        votes, support = self.vote_view(phi, s_star, INF)
        return votes, support, s_star

    def merged_vote_view(self, phi, s):  # the slot-(s-1) view of a slot-s voter
        freeze = self.P.t(s - 1) + 3 * self.P.delta
        votes, support = self.vote_view(phi, s - 1, freeze)
        vs, ss = set(votes), set(support)
        for B in sorted(phi.tree, key=lambda r: (DEPTH[r], r)):
            blk = BLOCKS[B]
            if blk.slot != s:
                continue  # the slot-s proposals: their lists pass the vote freeze
            for x in blk.votes:
                if x not in vs:
                    vs.add(x)
                    votes.append(x)
            for x in blk.support_votes:
                if x.s == s - 1 and x.H in phi.tree and BLOCKS[x.H].slot <= s - 1 and x not in ss:
                    ss.add(x)
                    support.append(x)
        return votes, support

    def voter_block_tree(self, phi, s):
        freeze = self.P.t(s - 1) + 3 * self.P.delta
        props = [B for B in phi.tree if BLOCKS[B].slot == s]
        under = set()
        for Pr in props:
            under |= ANC[Pr]
        return frozenset(B for B in phi.tree if self.ts.get(B, INF) < freeze or B in under)

    # --- locks and unlocking
    @staticmethod
    def viable_ancestor(phi, B):  # B itself when B is viable or at or below Φ.fc_root
        full = phi.full_viable()
        return deepest([X for X in ANC[B] if prec(X, phi.fc_root) or X in full])

    def live_locks(self, phi, t, locks=None):
        locks = self.locks if locks is None else locks
        sl = self.P.slot(t)
        return frozenset(Lock(self.viable_ancestor(phi, L.B), L.j, L.f, L.e)
                         for L in locks if sl <= L.e and L.B in phi.tree)

    def conflicts_with_lock(self, phi, t, C, live=None):
        live = self.live_locks(phi, t) if live is None else live
        return any(conflicts(C, L.B) for L in live)

    def get_anchor(self, phi, t):  # the deepest viable lock block, or Φ.fc_root
        return deepest([L.B for L in self.live_locks(phi, t)] + [phi.fc_root])

    def fast_expiry(self, phi, t, s):  # the expiry of a new fast lock of slot s
        E = [L.e for L in self.live_locks(phi, t) if L.f and L.j < s]  # the live fast locks of earlier slots
        if not E:
            return s + 2
        return min(s + self.P.k, max(s + 2, max(E) + self.P.c))

    def add_locks(self, phi, t, s, N):  # N: (B, f, e), new locks of slot s; the caller writes them
        return self.live_locks(phi, t, self.locks | {Lock(B, s, f, e) for B, f, e in N})

    def unlock(self, phi, t, s, votes, support):  # against the slot-s votes of a view, in slot s+1
        eq = equivocators(votes)
        sup_v = [(x.v, x.H) for x in support if x.s == s]

        def opponents(B):
            return eq | {v for v, H in sup_v if conflicts(H, B)}

        new = set()
        for L in sorted(self.live_locks(phi, t)):  # sorted: the log order does not depend on hashing
            B = L.B
            if L.j < s:  # a lock of slot s or later keeps its place against these votes
                chain = sorted((X for X in ANC[B] if X in phi.tree), key=lambda X: -DEPTH[X])
                B = next((X for X in chain if 2 * len(opponents(X)) < self.P.n), phi.F)
                if B != L.B:
                    self.log("lock_back", block=L.B, to=B, deadline=L.e, slot=s)
            new.add(Lock(B, L.j, L.f, L.e))  # keep the slot, the bit and the expiry
        self.locks = frozenset(new)

    # --- fork choice
    def get_head(self, phi, t, tree, votes, support, s):
        anchor = self.get_anchor(phi, t)  # of the full viable tree, also when tree is smaller
        eq = equivocators(votes)
        voters = len({x.v for x in votes})
        cur = self.P.slot(t)
        sup = [(x.v, x.H) for x in support if x.s == s and x.v not in eq]

        def score(B):  # goldfish_score: equivocators count for every block
            return len(eq) + len({v for v, H in sup if prec(B, H)})

        def eligible(B):  # goldfish_eligible
            if BLOCKS[B].parent not in phi.viable_heads:
                return True  # the walk is not yet on a viable head
            if BLOCKS[B].slot == cur:
                return True  # a block of the current slot
            return 2 * score(B) > voters  # a strict majority of the voters

        return ghost(anchor, tree, score, eligible)

    def head(self, phi, t):  # ac_head
        votes, support, s_star = self.latest_view(phi, t)
        return self.get_head(phi, t, phi.full_viable(), votes, support, s_star)

    # --- confirmation
    def update_latest_confirmed(self, phi, C):
        E = self.latest_confirmed
        if E not in phi.tree or not prec(C, E):
            if E in phi.tree and conflicts(E, C):
                self.log("confirm_switch", old=E, new=C)
            self.latest_confirmed = C  # never back to an ancestor

    def _early_support(self, phi, s):
        votes = self.pool(s)  # the whole pool: it decides who equivocates
        eq = equivocators(votes)
        cut = self.P.t(s) + 2 * self.P.delta
        return {x.v: x.H for x in votes if x.v not in eq and self.resolution_time(phi, x) < cut}

    @staticmethod
    def _counts(phi, heads_by_v, floor):
        """For each block B of Φ.tree at or above `floor`: the validators with a head extending B."""
        cnt = {}
        for v, H in heads_by_v:
            for B in ANC[H]:
                if B in phi.tree and prec(floor, B):
                    cnt.setdefault(B, set()).add(v)
        return cnt

    def confirmation_score(self, phi, s, B):
        return sum(1 for H in self._early_support(phi, s).values() if prec(B, H))

    def get_confirmation(self, phi, s):  # at t_s + 6Δ
        voters = len({x.v for x in self.pool(s)})
        cnt = self._counts(phi, self._early_support(phi, s).items(), phi.F)
        ok = [B for B, vs in cnt.items() if 2 * len(vs) > voters]  # these blocks lie on one chain
        return deepest(ok) if ok else None

    def update_confirmation(self, phi, t, s):  # at t_s + 6Δ
        P = self.P
        C = self.get_confirmation(phi, s)
        self.saved_confirmation[s] = C
        if C is None:
            self.log("confirm", slot=s, result=None, vetoed=False)
            return
        live = self.live_locks(phi, t)
        vetoed = self.conflicts_with_lock(phi, t, C, live)
        path = [B for B in ANC[C] if B != GEN and B in phi.tree and not self.conflicts_with_lock(phi, t, B, live)]
        early = self._early_support(phi, s)

        def fast(B):
            return 2 * sum(1 for H in early.values() if prec(B, H)) >= P.n

        def slow(B):
            for j in range(s - P.k + 1, s):
                c = self.saved_confirmation.get(j)
                if c is None or c not in phi.tree or not prec(B, c):
                    return False
            return True

        fasts = [B for B in path if fast(B)]
        slows = [B for B in path if slow(B)]
        D = deepest(fasts) if fasts else None
        X = deepest(slows) if slows else None
        N = set()
        fast_e = self.fast_expiry(phi, t, s) if D is not None else None
        if D is not None:
            N.add((D, True, fast_e))
        if X is not None:
            N.add((X, False, s + P.k))
        if not vetoed:
            self.update_latest_confirmed(phi, C)  # the veto stops only the confirmation
        self.locks = self.add_locks(phi, t, s, N)
        lb = deepest([B for B, _, _ in N]) if N else None
        self.log("confirm", slot=s, result=C, vetoed=vetoed, lock=lb,
                 how=None if lb is None else ("fast" if lb == D else "slow"), fast=D, slow=X,
                 fast_e=fast_e, slow_e=None if X is None else s + P.k)

    def optimistic_confirmation(self, phi, t):  # after each receipt
        P = self.P
        s = P.slot(t)
        if not self.joined(t) or s == 0 or t >= P.t(s) + 2 * P.delta:
            return
        heads = [(x.v, x.H) for x in self.pool(s) if x.H in phi.tree]  # equivocators included
        cnt = self._counts(phi, heads, GEN)
        live = self.live_locks(phi, t)
        ok = [B for B, vs in cnt.items() if 4 * len(vs) >= 3 * P.n and not self.conflicts_with_lock(phi, t, B, live)]
        if not ok:
            return
        B = deepest(ok)  # if e < n/2, they lie on one chain
        e = self.fast_expiry(phi, t, s)
        before = self.locks
        self.locks = self.add_locks(phi, t, s, {(B, True, e)})
        if self.locks != before:
            self.log("opt_confirm", slot=s, block=B, expiry=e)
        self.update_latest_confirmed(phi, B)

    def confirmed(self, phi, t):  # ac_confirmed, user-facing
        C = self.latest_confirmed if self.latest_confirmed in phi.tree else phi.F
        return common_ancestor(C, self.head(phi, t))

    # --- the vote and the vote receipt
    @staticmethod
    def vote_ready(phi, s):  # a ready proposal of slot s: its support references resolve
        return any(BLOCKS[Pr].slot == s and all(x.H in phi.tree and BLOCKS[x.H].slot <= s - 1
                                                for x in BLOCKS[Pr].support_votes)
                   for Pr in phi.tree)

    def try_vote(self, phi, t):  # after each receipt, and in the tick at t_s + Δ; returns the votes to send
        P = self.P
        s = P.slot(t)
        if not self.joined(t) or self.voted_slot == s or t > P.t(s) + P.delta:
            return []  # one vote per slot
        if t < P.t(s) + P.delta and (s == 0 or not self.vote_ready(phi, s)):
            return []  # wait for a ready proposal or for t_s + Δ
        votes, support = self.merged_vote_view(phi, s)  # empty in slot 0
        if s > 0:
            self.unlock(phi, t, s - 1, votes, support)
        T = self.voter_block_tree(phi, s)
        tree = viable_tree(phi, T)
        if not tree:
            tree = phi.full_viable()  # the vote domain: the full-tree fallback
        H = self.get_head(phi, t, tree, votes, support, s - 1)
        self.voted_slot = s  # before the own vote, which re-enters this check
        eq = equivocators(votes)  # the view behind the vote, for the explorer
        tally = {}
        for x in support:
            if x.s == s - 1 and x.v not in eq:
                tally.setdefault(x.H, set()).add(x.v)
        self.log("vote", slot=s, head=H, voters=len({x.v for x in votes}), equivocators=len(eq),
                 early=t < P.t(s) + P.delta,
                 tally=sorted(((B, len(vs)) for B, vs in tally.items()), key=lambda p: -p[1]))
        out = [Vote(v, s, H) for v in self.local]
        for x in out:  # the own vote is a receipt
            self.on_goldfish_vote(t, x)
        self.optimistic_confirmation(phi, t)
        return out

    def on_votes(self, phi, t, votes):  # ac_on_message for a batch; returns (admitted, own votes)
        admitted = [x for x in votes if self.on_goldfish_vote(t, x)]
        self.optimistic_confirmation(phi, t)
        return admitted, self.try_vote(phi, t)

    # --- block, tick, proposal and FG update
    def on_block(self, phi, t, B):  # ac_on_block; returns (admitted carried votes, own votes)
        self.ts[B.root] = t
        admitted = [x for x in B.votes if self.on_goldfish_vote(t, x)]
        self.optimistic_confirmation(phi, t)
        return admitted, self.try_vote(phi, t)

    def on_tick(self, phi, t):  # ac_on_tick; returns the votes to send
        P = self.P
        s = P.slot(t)
        if not self.joined(t):
            return []  # not joined: no duty and no write
        out = []
        if t == P.t(s) + P.delta:
            out = self.try_vote(phi, t)  # the latest vote time: no readiness test
        if t == P.t(s) + 2 * P.delta and s > 0:
            self.update_confirmation(phi, t, s - 1)
        return out

    def proposal(self, phi, t):  # ac_proposal, at t_s: the view is of slot s-1
        if not self.joined(t):
            return None  # not joined: the node makes no proposal
        s = self.P.slot(t)
        votes, support = self.vote_view(phi, s - 1, INF)  # every previous-slot vote held; the resolved ones
        self.unlock(phi, t, s - 1, votes, support)
        H = self.get_head(phi, t, phi.full_viable(), votes, support, s - 1)
        return H, votes, support

    def to_fg(self, phi, t):  # ac_to_fg, after each tick
        if not self.joined(t):
            return None
        sl = self.P.slot(t)
        full = phi.full_viable()
        cands = [L.B for L in self.live_locks(phi, t) if L.f and sl <= L.j + 2 and L.B in full]
        if not cands:
            return None
        C = deepest(cands)  # the candidates lie on one chain
        if self.fg_reported in phi.tree and prec(C, self.fg_reported):
            return None  # nothing new
        self.fg_reported = C
        return C

    def restart(self, phi, t):  # ac_restart: keep the locks and the record, reset the rest
        locks, record = self.locks, self.latest_confirmed
        self.__init__(self.P, self.local, self.log)
        self.locks, self.latest_confirmed = locks, record
        self.restart_time = t
        for B in sorted(phi.tree - {GEN}, key=lambda r: (DEPTH[r], r)):  # parent order, siblings by root
            self.on_block(phi, t, BLOCKS[B])  # not joined: the two checks do nothing


def ac_valid_payload(B, P):  # stateless: reads neither the clock nor the pool
    vs = set(B.votes)
    return (all(x.s == B.slot - 1 >= 0 and 0 <= x.v < P.n for x in B.votes)
            and all(x in vs for x in B.support_votes))


# ------------------------------------------------------- node (composition.tex, alg:node)


class Node:
    """Receipt handlers and the tick return [(kind, payload)]: what the node sends. An honest node
    forwards every object that it accepts, also the votes and attestations that a block carries
    (composition.tex, Model); `forward=False` turns the forwarding off, for comparison only."""

    def __init__(self, nid, P, validators, log=None, forward=True):
        self.id, self.P = nid, P
        self.validators = list(validators)
        self.forward = forward
        sink = log if log is not None else (lambda *a, **k: None)
        self.log = lambda kind, **kw: sink(kind, node=nid, **kw)
        self.fg = FG(P)
        self.ac = AC(P, self.validators, log=self.log)
        self.clients = {v: Client(v) for v in self.validators}
        self.orphans = {}  # parent root -> [blocks]: re-delivery of a block whose parent is missing
        self.last_fg_confirmed = None

    def phi(self):
        return self.fg.frame()

    def on_tick(self, t):
        P = self.P
        s = P.slot(t)
        out = []
        votes = self.ac.on_tick(self.phi(), t)
        if votes:
            out.append(("vote", tuple(votes)))
        if s > 0 and t == P.t(s) and P.proposer(s) in self.clients:
            prop = self.ac.proposal(self.phi(), t)  # None: the AC makes no proposal
            if prop is not None:
                out += self.propose_block(t, prop)
        fgc = self.ac.to_fg(self.phi(), t)  # None: no new block for the FG
        if fgc is not None:
            out += self.attest(t, fgc)
        return out

    def on_block(self, B, t, sent=None):
        """Returns what the node sends; `sent` set to the own block when the node proposed it."""
        if B.slot > self.P.slot(t):
            return []
        if B.parent not in self.fg.T and B.root not in self.fg.T:
            self.orphans.setdefault(B.parent, []).append(B)
            return []
        if not ac_valid_payload(B, self.P):
            return []
        ok, new_atts = self.fg.on_block(B)
        if not ok:
            return []  # the AC does not see a refused block
        admitted, own = self.ac.on_block(self.phi(), t, B)
        out = []
        if self.forward or sent is B:
            out.append(("block", B))
        if self.forward:
            if admitted:
                out.append(("vote", tuple(admitted)))
            if new_atts:
                out.append(("att", tuple(new_atts)))
        if own:
            out.append(("vote", tuple(own)))
        for child in self.orphans.pop(B.root, []):
            out += self.on_block(child, t)
        return out

    def on_votes(self, votes, t):
        admitted, own = self.ac.on_votes(self.phi(), t, votes)
        out = []
        if self.forward and admitted:
            out.append(("vote", tuple(admitted)))
        if own:
            out.append(("vote", tuple(own)))
        return out

    def on_vote(self, vote, t):
        return self.on_votes([vote], t)

    def on_attestations(self, atts, t=None):
        new = [a for a in atts if self.fg.on_attestation(a)]
        return [("att", tuple(new))] if self.forward and new else []

    def on_attestation(self, a, t=None):
        return self.on_attestations([a], t)

    def restart(self, t):  # keep Λ, Σ and the clock; A <- ac_restart(A, Φ, t)
        self.ac.restart(self.phi(), t)
        self.log("restart")

    def propose_block(self, t, prop):  # at t_s
        P = self.P
        s = P.slot(t)
        H, votes, support = prop
        atts = self.fg.proposal_attestations(H)
        B = make_block(s, H, P.proposer(s), tuple(atts), tuple(votes), tuple(support))
        return self.on_block(B, t, sent=B)  # broadcast B; on_block(B)

    def attest(self, t, fgc):
        phi = self.phi()
        self.last_fg_confirmed = fgc
        self.log("fg_pair", fg_confirmed=fgc, head=None)
        if fgc not in phi.full_viable():
            self.log("violation", what="requirement 2: fg_confirmed in the viable tree")
        hc, Tc, sigma_e = self.fg.attest_inputs(fgc)
        out = []
        for v, c in self.clients.items():
            a = c.create_attestation(hc, Tc, sigma_e)
            if a is not None:
                out.append(a)
                self.fg.on_attestation(a)
        return [("att", tuple(out))] if out else []

    # --- outputs
    def head(self, t):
        return self.ac.head(self.phi(), t)

    def confirmed(self, t):
        return self.ac.confirmed(self.phi(), t)
