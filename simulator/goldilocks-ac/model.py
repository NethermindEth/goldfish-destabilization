"""Goldilocks available chain on its own: the live spec with the finality gadget frozen at genesis.

The available chain (AC) of ../goldilocks-live/model.py reads the finality gadget only through the
frame Φ = (tree, fc_root, allowed). When no attestation is ever processed, the live FG keeps h = 1,
h_max = 1 and h_j = 0, sees no contest, and so returns a constant frame: fc_root = genesis, every
accepted block allowed, F = genesis. This module runs the AC of the live model, unchanged, against
that frame. Genesis plays the finalized checkpoint, so the runs describe any stretch of the chain
that the FG has not finalized, for example while participation is below 2/3.

What is gone: FG attestations, the validator client, heights and timeouts, the FG source
(ac_to_fg). Blocks carry Goldfish votes and support votes only. What stays: everything of the
Goldilocks AC (votes and views, early votes, the merged view, locks with graded expiries,
unlocking, the head walk, optimistic, fast and slow confirmation, restart), imported from the
live model so that the two cannot drift apart.
"""

import importlib.util
import pathlib

_LIVE = pathlib.Path(__file__).resolve().parent.parent / "goldilocks-live" / "model.py"
_spec = importlib.util.spec_from_file_location("goldilocks_live_model", _LIVE)
live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live)

AC, BLOCKS, DEPTH, ANC, GEN, Frame, Params, Vote, Lock = (
    live.AC, live.BLOCKS, live.DEPTH, live.ANC, live.GEN, live.Frame, live.Params, live.Vote, live.Lock)
prec, conflicts, compatible, common_ancestor, deepest, make_block, ac_valid_payload = (
    live.prec, live.conflicts, live.compatible, live.common_ancestor, live.deepest, live.make_block,
    live.ac_valid_payload)

SPEC = "ethlabs-org/eth-consensus-lean@4a63033e, available chain only (FG frozen at genesis)"


def frozen_frame(tree):
    """fg_to_ac of a gadget that never processes an attestation: fc_root = F = genesis and every
    block of the tree is allowed, so the viable tree is the whole tree."""
    tree = frozenset(tree)
    return Frame(tree, GEN, tree, GEN, _full=tree)


def valid_block(B, P):
    """The checks of the FG state transition that remain without attestations."""
    return B.proposer == P.proposer(B.slot) and BLOCKS[B.parent].slot < B.slot and not B.attestations


class Node:
    """The node of ../goldilocks-live/model.py without the FG: receipt handlers and the tick return
    [(kind, payload)], what the node sends. An honest node forwards every block and vote that it
    accepts, also the votes a block carries; `forward=False` turns that off, for comparison only."""

    def __init__(self, nid, P, validators, log=None, forward=True):
        self.id, self.P = nid, P
        self.validators = list(validators)
        self.forward = forward
        sink = log if log is not None else (lambda *a, **k: None)
        self.log = lambda kind, **kw: sink(kind, node=nid, **kw)
        self.T = {GEN}  # the accepted blocks
        self.ac = AC(P, self.validators, log=self.log)
        self.orphans = {}  # parent root -> [blocks]: re-delivery of a block whose parent is missing
        self._frame = None

    def phi(self):
        if self._frame is None:
            self._frame = frozen_frame(self.T)
        return self._frame

    def on_tick(self, t):
        P = self.P
        s = P.slot(t)
        out = []
        votes = self.ac.on_tick(self.phi(), t)
        if votes:
            out.append(("vote", tuple(votes)))
        if s > 0 and t == P.t(s) and P.proposer(s) in self.validators:
            prop = self.ac.proposal(self.phi(), t)  # None: the AC makes no proposal
            if prop is not None:
                out += self.propose_block(t, prop)
        return out

    def on_block(self, B, t, sent=None):
        """Returns what the node sends; `sent` set to the own block when the node proposed it."""
        if B.slot > self.P.slot(t) or B.root in self.T:
            return []
        if B.parent not in self.T:
            self.orphans.setdefault(B.parent, []).append(B)
            return []
        if not ac_valid_payload(B, self.P) or not valid_block(B, self.P):
            return []
        self.T.add(B.root)
        self._frame = None
        admitted, own = self.ac.on_block(self.phi(), t, B)
        out = []
        if self.forward or sent is B:
            out.append(("block", B))
        if self.forward and admitted:
            out.append(("vote", tuple(admitted)))
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

    def restart(self, t):  # keep the clock; A <- ac_restart(A, Φ, t)
        self.ac.restart(self.phi(), t)
        self.log("restart")

    def propose_block(self, t, prop):  # at t_s
        P = self.P
        s = P.slot(t)
        H, votes, support = prop
        B = make_block(s, H, P.proposer(s), (), tuple(votes), tuple(support))
        return self.on_block(B, t, sent=B)  # broadcast B; on_block(B)

    # --- outputs
    def head(self, t):
        return self.ac.head(self.phi(), t)

    def confirmed(self, t):
        return self.ac.confirmed(self.phi(), t)
