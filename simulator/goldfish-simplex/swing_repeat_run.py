"""Repeat the PR #4 synchrony attack every time the adversary is the proposer.

PR #4 (synchrony_break_run.py) breaks confirmation permanence once: the adversary proposes
B_s, splits the honest nodes around the 25% deadline, and withholds its own vote for the
parent until after the 50% confirmation freeze. B_s is then confirmed (available and safe)
in slot s+1 although the honest proposer of slot s+1 has already orphaned it.

Here the adversary (node 3, 25% of the stake) plays that strategy in EVERY slot it proposes,
for the whole run, and we measure what the repeated swing does to the final chain:
orphaned blocks, chain growth, finality lag, stable roots, finality votes naming orphans.
All delays stay <= 1400 ms < Delta = 1500 ms; no equivocation by anyone.

Modes for who gets the block early (< 25% deadline) and who gets it late (> 25% deadline):
  fixed     nodes 0,1 early, node 2 late (the PR #4 split), attack in every proposer slot
  adaptive  the adversary picks, from the slot's committee, the honest subset that makes
            the break work (early share > 50% of the 50%-frozen votes but <= 50% of all
            seats once its own votes land); it plays honestly in slots with no such subset

Run (from simulator/goldfish-simplex/):
    PYTHONPATH=$SPECS:$SPECS/tests/core/pyspec $SPECS/.venv/bin/python swing_repeat_run.py \
        --mode adaptive --slots 96 --json out.json
"""

import argparse
import itertools
import json
import sys
from collections import Counter

import honest_run as hr
from honest_run import spec
from partition_run import Tracker, is_ancestor_root, orphaned_blocks
from synchrony_break_run import SynchronousAdversaryNetwork

ADV = 3
HONEST = (0, 1, 2)

# Observation-only: log every round-start get_proposer_head call (which anchors it saw and
# what it returned). The wrapper returns the original value unchanged.
PROPOSER_HEAD_LOG = []
_NODE_OF_STORE = {}
_orig_get_proposer_head = spec.get_proposer_head


def _observed_get_proposer_head(store, head_root, slot):
    out = _orig_get_proposer_head(store, head_root, slot)
    rnd = spec.compute_round_at_slot(slot)
    if slot == spec.compute_start_slot_at_round(rnd):
        sel = store.tsq_selections.get(rnd)
        sl = lambda r: int(store.blocks[r].slot) if r in store.blocks else None
        PROPOSER_HEAD_LOG.append({
            "slot": int(slot), "node": _NODE_OF_STORE.get(id(store)),
            "head": sl(head_root),
            "tsq_candidate": sl(sel.candidate_root) if sel is not None else None,
            "live_confirmed": sl(store.live_confirmed_head[0]),
            "returned": sl(out), "kept_head": out == head_root,
            "head_on_final_chain": None,
        })
    return out


spec.get_proposer_head = _observed_get_proposer_head


class RecordingNetwork(SynchronousAdversaryNetwork):
    """Also keeps every finality attestation an honest node signed, for the orphan probe."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.signed = []  # (slot, node_id, AttestationData)

    def broadcast(self, sender, now_ms, kind, msg):
        if kind == "att" and sender.id != ADV:
            self.signed.append((now_ms // hr.SLOT_MS, sender.id, msg.data))
        super().broadcast(sender, now_ms, kind, msg)


class RepeatingAdversary(hr.Node):
    """Honest except that it runs the PR #4 strategy in every slot where it is the proposer."""

    def __init__(self, node_id, genesis, validators, mode, enabled, min_slot, skip_round_start):
        super().__init__(node_id, genesis, validators)
        self.mode = mode
        self.enabled = enabled
        self.min_slot = min_slot
        self.skip_round_start = skip_round_start
        self.attacks = {}  # slot -> info dict
        self.skipped = []  # (slot, reason) proposer slots where it played honestly

    def committee_seats(self, state, slot, net):
        committee = self.store.available_committees.get(spec.Slot(slot))
        if committee is None:
            committee = spec.get_available_committee(state, spec.Slot(slot))
        committee = [int(v) for v in committee]
        seats = {n.id: sum(1 for v in committee if v in n.validators) for n in net.nodes}
        return seats

    @staticmethod
    def break_works(n_early, n_late, n_adv):
        """The two seat conditions of PR #4 (plus: not fast-confirmed in slot s)."""
        total = n_early + n_late + n_adv
        return n_early > (n_early + n_late) // 2 and n_early < 384 and n_early <= total // 2

    def plan_split(self, seats):
        """Return (early_ids, late_ids, works) for this slot's committee."""
        n_adv = seats[ADV]
        if self.mode == "fixed":
            early, late = (0, 1), (2,)
            w = self.break_works(sum(seats[i] for i in early), sum(seats[i] for i in late), n_adv)
            return early, late, w
        best = None
        for k in range(1, len(HONEST)):
            for early in itertools.combinations(HONEST, k):
                late = tuple(i for i in HONEST if i not in early)
                ne, nl = sum(seats[i] for i in early), sum(seats[i] for i in late)
                if not self.break_works(ne, nl, n_adv):
                    continue
                total = ne + nl + n_adv
                slack = min(total // 2 - ne, ne - (ne + nl) // 2 - 1)
                if best is None or slack > best[0]:
                    best = (slack, early, late)
        if best is None:
            return None, None, False
        return best[1], best[2], True

    def slot_start(self, slot, now_ms, net):
        self.tick(spec.on_tick, self.store.genesis_time + now_ms // 1000)
        head_root = self.head().root
        parent_root = spec.get_proposer_head(self.store, head_root, spec.Slot(slot))
        state = spec.get_current_slot_state(self.store, parent_root)
        proposer = spec.get_beacon_proposer_index(state)
        if proposer not in self.validators:
            return
        spr = int(spec.get_slots_per_round_at_slot(spec.Slot(slot)))
        if not self.enabled or slot < self.min_slot:
            return super().slot_start(slot, now_ms, net)
        if self.skip_round_start and slot % spr == 0:
            self.skipped.append((slot, "round-start"))
            return super().slot_start(slot, now_ms, net)
        seats = self.committee_seats(state, slot, net)
        early, late, works = self.plan_split(seats)
        if early is None:
            self.skipped.append((slot, "no-feasible-split"))
            return super().slot_start(slot, now_ms, net)

        st = self.store.block_states[parent_root].copy()
        block = hr.build_empty_block(spec, st, slot=spec.Slot(slot), proposer_index=proposer)
        block.parent_root = parent_root
        pre = st.copy()
        spec.process_slots(pre, spec.Slot(slot))
        block.body.attestations = self.select_attestations(pre, parent_root)
        signed = hr.state_transition_and_sign_block(spec, st, block)
        root = signed.message.hash_tree_root()
        self.attacks[slot] = {
            "slot": slot,
            "parent": parent_root,
            "root": root,
            "early": list(early),
            "late": list(late),
            "seats": dict(seats),
            "break_conditions_hold": bool(works),
            "round_start": slot % spr == 0,
        }
        deliver = {self.id: now_ms}
        for nid in early:
            deliver[nid] = now_ms + 1400
        for nid in late:
            deliver[nid] = now_ms + 1600
        net.broadcast_custom(self, now_ms + 200, deliver, "block", signed)

    def available_duty(self, slot, now_ms, net):
        if slot not in self.attacks:
            return super().available_duty(slot, now_ms, net)
        store = self.store
        committee = store.available_committees.get(spec.Slot(slot))
        if committee is None:
            return
        positions = [i for i, v in enumerate(committee) if v in self.validators]
        if not positions:
            return
        parent_node = spec.ForkChoiceNode(
            root=self.attacks[slot]["parent"], payload_status=spec.PAYLOAD_STATUS_EMPTY
        )
        data = spec.get_available_attestation_data(store, parent_node)
        bits = spec.Bitvector[spec.AVAILABLE_COMMITTEE_SIZE]()
        for i in positions:
            bits[i] = True
        att = spec.AvailableAttestation(aggregation_bits=bits, data=data, signature=hr.STUB_SIG)
        send_ms = slot * hr.SLOT_MS + 3200
        deliver = {
            nid: (send_ms if nid == self.id else send_ms + net.latency_ms)
            for nid in range(len(net.nodes))
        }
        net.broadcast_custom(self, send_ms, deliver, "avail", att)


def chain_of(store, head):
    out, r = [], head
    while r in store.blocks:
        out.append(r)
        if int(store.blocks[r].slot) == 0:
            break
        r = store.blocks[r].parent_root
    return out[::-1]


def run(args):
    genesis = hr.make_genesis(args.validators, args.seed)
    assignment = hr.assign_validators(args.validators, args.nodes, args.seed)
    net = RecordingNetwork(args.latency_ms, args.seed, ADV, -1, (0, 1), (2,))
    if args.events:
        net.events = []
    adv = RepeatingAdversary(
        ADV, genesis, assignment[ADV], args.mode, not args.no_attack, args.min_slot, args.skip_round_start
    )
    net.nodes = [hr.Node(i, genesis, assignment[i]) for i in HONEST] + [adv]
    for n in net.nodes:
        _NODE_OF_STORE[id(n.store)] = n.id
    tracker = Tracker(net.nodes)
    states, finalized_by_slot, justified_by_slot = [], {}, {}
    # latest_confirmed_head is a monotone log that stays stuck on an orphaned block, so the
    # replaceable live_confirmed_head is what shows each new confirmation.
    ever_live = {n.id: set() for n in net.nodes}
    for slot in range(1, args.slots + 1):
        base = slot * hr.SLOT_MS
        for offset, action in (
            (0, "start"), (hr.ATT_DUE_MS, "att"), (hr.CONF_DUE_MS, "conf"), (hr.FREEZE_DUE_MS, "frz")
        ):
            now = base + offset
            net.deliver_until(now)
            for node in net.nodes:
                if action == "start":
                    node.slot_start(slot, now, net)
                elif action == "att":
                    node.attestation_deadline(slot, now, net)
                else:
                    node.tick(spec.on_tick_per_high_resolution, spec.uint64(offset))
            net.deliver_until(now)
        snaps = [tracker.observe(slot, n) for n in net.nodes]
        for n in net.nodes:
            ever_live[n.id].add(n.store.live_confirmed_head[0])
        states.append({"slot": slot, "nodes": snaps})
        finalized_by_slot[slot] = snaps[0]["finalized_slot"]
        justified_by_slot[slot] = snaps[0]["justified_slot"]
        if args.progress and slot % 8 == 0:
            print(f"  slot {slot}: n_attacks={len(adv.attacks)}", file=sys.stderr, flush=True)
    assert net.max_delay_observed_ms <= hr.ATT_DUE_MS, "synchrony bound violated"
    net.ever_live = ever_live
    return net, adv, tracker, states, finalized_by_slot, justified_by_slot


def analyse(args, net, adv, tracker, finalized_by_slot, justified_by_slot):
    n0 = net.nodes[0]
    s0 = n0.store
    heads = [n.head().root for n in net.nodes[:3]]
    final_chain = chain_of(s0, heads[0])
    canon = set(final_chain)
    adv_vals = adv.validators

    blocks = [(r, b) for r, b in s0.blocks.items() if int(b.slot) > 0]
    orphans = [(r, b) for r, b in blocks if r not in canon]
    orphan_roots = {r for r, _ in orphans}
    orph_by_adv = sum(1 for _, b in orphans if int(b.proposer_index) in adv_vals)
    orph_by_honest = len(orphans) - orph_by_adv
    prop_adv = sum(1 for _, b in blocks if int(b.proposer_index) in adv_vals)

    canon_slots = [int(s0.blocks[r].slot) for r in final_chain if int(s0.blocks[r].slot) > 0]
    canon_adv = sum(1 for r in final_chain if int(s0.blocks[r].slot) > 0 and int(s0.blocks[r].proposer_index) in adv_vals)

    attacks = []
    for slot, a in sorted(adv.attacks.items()):
        root = a["root"]
        conf = [nid for nid in HONEST if root in net.ever_live[nid]]
        log_conf = [nid for nid in HONEST if root in tracker.ever_avail[nid]]
        safe = [nid for nid in HONEST if root in tracker.ever_safe[nid]]
        attacks.append({
            "slot": slot,
            "round_start": a["round_start"],
            "early": a["early"], "late": a["late"],
            "seats": a["seats"],
            "break_conditions_hold": a["break_conditions_hold"],
            "orphaned": root not in canon,
            "live_confirmed_by": conf,
            "latest_confirmed_log_by": log_conf,
            "safe_confirmed_by": safe,
            "success": root not in canon and bool(conf),
        })

    orphan_detail = sorted(
        (int(b.slot), "adv" if int(b.proposer_index) in adv_vals else "honest",
         int(s0.blocks[b.parent_root].slot) if b.parent_root in s0.blocks else None)
        for r, b in orphans
    )
    # Honest blocks that got orphaned: say why (parent / the attack that preceded them).
    honest_orphans = sorted(
        (int(b.slot), int(b.parent_root in canon)) for r, b in orphans if int(b.proposer_index) not in adv_vals
    )

    naming = Counter()
    naming_ex = []
    total_att = 0
    for slot, nid, d in net.signed:
        total_att += 1
        for field, root in (
            ("head", d.beacon_block_root), ("target", d.target.root), ("finality_target", d.finality_target.root)
        ):
            if root in orphan_roots:
                naming[field] += 1
                if len(naming_ex) < 8:
                    naming_ex.append((slot, nid, field, int(s0.blocks[root].slot)))

    stable_bad = []
    stable_src = Counter()
    for rnd, per_node in sorted(tracker.stable.items()):
        for nid, (sslot, src, root) in per_node.items():
            if nid == ADV or sslot is None:
                continue
            stable_src[src] += 1
            if root in s0.blocks and root not in canon:
                stable_bad.append((rnd, nid, sslot))

    lags = [slot - finalized_by_slot[slot] for slot in finalized_by_slot if slot >= 16]
    fin_events = sum(1 for a, b in zip(list(finalized_by_slot.values())[:-1], list(finalized_by_slot.values())[1:]) if b != a)
    hs = s0.block_states[heads[0]]
    res = {
        "config": {
            "mode": args.mode, "no_attack": args.no_attack, "seed": args.seed, "slots": args.slots,
            "validators": args.validators, "skip_round_start": args.skip_round_start,
        },
        "heads_agree": len(set(heads)) == 1,
        "attacks": attacks,
        "attacks_total": len(attacks),
        "attacks_succeeded": sum(1 for a in attacks if a["success"]),
        "adv_proposer_slots_played_honestly": adv.skipped,
        "blocks_total": len(blocks),
        "blocks_orphaned": len(orphans),
        "orphaned_adv": orph_by_adv,
        "orphaned_honest": orph_by_honest,
        "orphaned_honest_slots": honest_orphans,
        "orphan_detail": orphan_detail,  # (slot, proposer type, parent slot)
        "canonical_slots": canon_slots,
        "round_start_proposer_heads": PROPOSER_HEAD_LOG,
        "adv_blocks_proposed": prop_adv,
        "canonical_blocks": len(canon_slots),
        "canonical_adv_blocks": canon_adv,
        "canonical_per_slot": round(len(canon_slots) / args.slots, 3),
        "finalized_slot": int(s0.blocks[s0.finalized_checkpoint.root].slot),
        "justified_slot": int(s0.blocks[s0.justified_checkpoint.root].slot),
        "chain_height": int(hs.current_height),
        "justified_height": int(hs.justified_height),
        "finality_lag_mean": round(sum(lags) / len(lags), 2) if lags else None,
        "finality_lag_max": max(lags) if lags else None,
        "finality_updates": fin_events,
        "honest_reorgs": {nid: tracker.reorgs[nid] for nid in HONEST},
        "safe_reversals": {nid: tracker.safe_reversals[nid] for nid in HONEST},
        "abandoned_avail": {nid: tracker.abandoned(net.nodes[nid], "avail") for nid in HONEST},
        "abandoned_safe": {nid: tracker.abandoned(net.nodes[nid], "safe") for nid in HONEST},
        "honest_finality_attestations": total_att,
        "att_fields_naming_orphan": dict(naming),
        "att_naming_examples": naming_ex,
        "stable_roots_off_canonical": stable_bad,
        "stable_sources": dict(stable_src),
        "finalized_slot_by_slot": finalized_by_slot,
        "max_delay_ms": net.max_delay_observed_ms,
    }
    return res


def report(res):
    c = res["config"]
    print(f"=== repeated attack: mode={c['mode']} no_attack={c['no_attack']} seed={c['seed']} slots={c['slots']} ===")
    print(f"adversary proposer slots: attacked={res['attacks_total']} "
          f"honest-fallback={len(res['adv_proposer_slots_played_honestly'])} {res['adv_proposer_slots_played_honestly']}")
    for a in res["attacks"]:
        print(f"  slot {a['slot']:3d}{' (round start)' if a['round_start'] else '              '} "
              f"early={a['early']} late={a['late']} seats={ {k: v for k, v in a['seats'].items()} } "
              f"conds={'Y' if a['break_conditions_hold'] else 'n'} orphaned={'Y' if a['orphaned'] else 'n'} "
              f"live-conf@{a['live_confirmed_by']} safe-conf@{a['safe_confirmed_by']} "
              f"=> {'BREAK' if a['success'] else 'no break'}")
    print(f"attacks that broke confirmation permanence: {res['attacks_succeeded']}/{res['attacks_total']}")
    print(f"blocks: {res['blocks_total']} proposed, {res['blocks_orphaned']} orphaned "
          f"(adversary {res['orphaned_adv']}, honest {res['orphaned_honest']} at slots "
          f"{[s for s, _ in res['orphaned_honest_slots']]}); canonical {res['canonical_blocks']} "
          f"= {res['canonical_per_slot']}/slot, of which adversary {res['canonical_adv_blocks']}")
    print(f"finality: finalized slot {res['finalized_slot']}, justified slot {res['justified_slot']}, "
          f"height {res['chain_height']} (justified {res['justified_height']}); lag from slot 16: "
          f"mean {res['finality_lag_mean']} max {res['finality_lag_max']}; updates {res['finality_updates']}")
    print(f"honest nodes agree on final head: {res['heads_agree']}")
    for nid in HONEST:
        print(f"  node {nid}: reorgs={len(res['honest_reorgs'][nid])} "
              f"safe-reversals={len(res['safe_reversals'][nid])} "
              f"abandoned avail={res['abandoned_avail'][nid]} safe={res['abandoned_safe'][nid]}")
    print(f"finality attestations by honest nodes: {res['honest_finality_attestations']}; "
          f"fields naming an orphaned block: {res['att_fields_naming_orphan']}")
    print(f"stable roots: sources {res['stable_sources']}; off the final chain: {res['stable_roots_off_canonical']}")
    print(f"max message delay {res['max_delay_ms']} ms (Delta {hr.ATT_DUE_MS} ms)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--validators", type=int, default=64)
    p.add_argument("--nodes", type=int, default=4)
    p.add_argument("--latency-ms", type=int, default=200)
    p.add_argument("--slots", type=int, default=96)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--mode", choices=("fixed", "adaptive"), default="adaptive")
    p.add_argument("--no-attack", action="store_true", help="baseline: the adversary proposes honestly")
    p.add_argument("--min-slot", type=int, default=9)
    p.add_argument("--skip-round-start", action="store_true", help="never attack at a round's first slot")
    p.add_argument("--json")
    p.add_argument("--events")
    p.add_argument("--progress", action="store_true")
    args = p.parse_args()
    assert args.nodes == 4, "roles are fixed: nodes 0,1,2 honest, node 3 adversary"

    net, adv, tracker, states, fin, jus = run(args)
    res = analyse(args, net, adv, tracker, fin, jus)
    report(res)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(res, fh, indent=1, default=str)
    if args.events:
        first = min(adv.attacks) if adv.attacks else 0
        cfg = {"nodes": 4, "split": 3, "start": first, "slots_down": 1, "seed": args.seed,
               "latency_ms": args.latency_ms, "jitter_ms": 0, "validators": args.validators}
        with open(args.events, "w") as fh:
            json.dump({
                "config": cfg, "slot_ms": hr.SLOT_MS,
                "deadlines_ms": [hr.ATT_DUE_MS, hr.CONF_DUE_MS, hr.FREEZE_DUE_MS],
                "slots_per_round": int(spec.get_slots_per_round_at_slot(spec.Slot(0))),
                "group_of": {0: 0, 1: 0, 2: 0, 3: 1},
                "messages": net.events, "states": states, "outcomes": getattr(hr, "OUTCOMES", []),
            }, fh)


if __name__ == "__main__":
    main()
