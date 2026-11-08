"""Observation-only checks of the stable-root properties, with G1 made visible.

Wraps `freeze_tsq_selection` (round start, 0%) and `freeze_stable_root` (round start, 25%)
to record, per node and round: live G1 before the freeze, the pinned and action-time Simplex
roots, the TSQ lock, G1 at the action, and the chosen stable root with its source. After
each slot (75% snapshot) it checks every node's stable root against every node's view:
G0 clearance and conflicts with the safe-confirmed head. Wrapped functions return the
original values unchanged.

Properties reported (see OPEN_QUESTIONS.md):
  P1 cross-node: conflicting stable roots in the same round
  P2 per-node: stable root of round r+1 conflicts with (or regresses below) round r's
  P3 a node's stable root conflicts with another node's safe-confirmed head, or is not
     G0-clear in another node's view
  P4 rounds after the heal until all nodes use the same stable root
"""
import json
from collections import Counter

import honest_run as hr

spec = hr.spec

RECORDS = {}  # (node_id, round) -> dict
VIOLATIONS = []  # dicts from observe_slot
_NODE_OF = {}  # id(store) -> node id
_orig_select = spec.freeze_tsq_selection
_orig_freeze = spec.freeze_stable_root


def _round(store):
    return int(spec.compute_round_at_slot(spec.get_current_slot(store)))


def _slot(store, root):
    return int(store.blocks[root].slot) if root in store.blocks else None


def _short(root):
    return bytes(root).hex()[:8]


def is_ancestor_root(store, anc, root):
    """`anc` is `root` or one of its ancestors (by parent pointers)."""
    if anc not in store.blocks or root not in store.blocks:
        return False
    anc_slot = store.blocks[anc].slot
    while root in store.blocks and store.blocks[root].slot > anc_slot:
        root = store.blocks[root].parent_root
    return root == anc


def relation(store, a, b):
    if a == b:
        return "same"
    if a not in store.blocks or b not in store.blocks:
        return "unknown"
    if is_ancestor_root(store, a, b):
        return "below"  # a is a strict ancestor of b
    if is_ancestor_root(store, b, a):
        return "above"
    return "conflict"


def _live_g1(store):
    return spec.get_grade_1_root(store, spec.get_filtered_block_tree(store)).root


def _wrapped_select(store):
    rnd = _round(store)
    at_start = spec.get_current_slot(store) == spec.compute_start_slot_at_round(rnd)
    if at_start and rnd not in store.tsq_selections and id(store) in _NODE_OF:
        key = (_NODE_OF[id(store)], rnd)
        RECORDS.setdefault(key, {"node": key[0], "round": rnd})["g1_before_freeze"] = _live_g1(store)
    return _orig_select(store)


def _wrapped_freeze(store):
    rnd = _round(store)
    if rnd in store.stable_root_decisions or id(store) not in _NODE_OF:
        return _orig_freeze(store)
    g1 = _live_g1(store)
    selection = store.tsq_selections.get(rnd)
    view = store.frozen_tsq_views.get(rnd)
    action_simplex = spec.get_simplex_root(store)
    _orig_freeze(store)
    lock = hr.TSQ_LOCKS.get((id(store), rnd))
    chosen = store.stable_root
    if lock is not None and chosen == lock:
        src = "TSQ-floor" if selection is not None and lock == selection.simplex_root else "TSQ"
        why = None
    else:
        src = "G1"
        if selection is None:
            why = "no selection"
        elif view is None or selection.support_round != view.support_round:
            why = "no frozen view"
        elif lock is not None and not is_ancestor_root(store, action_simplex, lock):
            why = "lock not above Simplex root"
        else:
            why = "lock not viable"
    key = (_NODE_OF[id(store)], rnd)
    rec = RECORDS.setdefault(key, {"node": key[0], "round": rnd})
    rec.update({
        "pinned_simplex": selection.simplex_root if selection is not None else None,
        "action_simplex": action_simplex,
        "lock": lock,
        "g1": g1,
        "chosen": chosen,
        "src": src,
        "g1_reason": why,
        "safe": spec.get_safe_confirmed_head(store),
        "live_confirmed": store.live_confirmed_head[0],
    })


CONF_RESETS = []  # update_confirmed_head took the "should be unreachable" finalized-conflict branch
_orig_update_confirmed = spec.update_confirmed_head


def _wrapped_update_confirmed(store, previous, candidate):
    result = _orig_update_confirmed(store, previous, candidate)
    prev_root = previous[0]
    if prev_root in store.blocks and id(store) in _NODE_OF and prev_root != candidate:
        fin = store.finalized_checkpoint.root
        if not is_ancestor_root(store, fin, prev_root) and result[0] == candidate:
            CONF_RESETS.append({
                "node": _NODE_OF[id(store)], "slot": int(spec.get_current_slot(store)),
                "previous_slot": _slot(store, prev_root), "candidate_slot": _slot(store, candidate),
                "finalized_slot": _slot(store, fin),
                "record": "fast" if previous is store.fast_confirmed_head else "available",
            })
    return result


def install(nodes):
    for n in nodes:
        _NODE_OF[id(n.store)] = n.id
    spec.freeze_tsq_selection = _wrapped_select
    spec.freeze_stable_root = _wrapped_freeze
    spec.update_confirmed_head = _wrapped_update_confirmed


TRACE = []  # per slot: {node: (finalized_root, justified_root, justified_height, latest_conf_root)}


def observe_slot(slot, nodes):
    """Per-slot trace for P5-P7, and P3 in the first two slots of each round."""
    TRACE.append((slot, {
        n.id: (n.store.finalized_checkpoint.root, n.store.justified_checkpoint.root,
               int(getattr(n.store, "justified_height", -1)), n.store.latest_confirmed_head[0])
        for n in nodes
    }))
    spr = int(spec.get_slots_per_round_at_slot(spec.Slot(0)))
    if slot % spr > 1:
        return
    rnd = int(spec.compute_round_at_slot(spec.Slot(slot)))
    roots = {}
    for n in nodes:
        rec = RECORDS.get((n.id, rnd))
        if rec and "chosen" in rec:
            roots.setdefault(rec["chosen"], []).append(n.id)
    for root, owners in roots.items():
        for n in nodes:
            s = n.store
            if root not in s.blocks:
                continue
            safe = spec.get_safe_confirmed_head(s)
            rel = relation(s, root, safe)
            g0 = spec.is_g0_clear(s, root)
            if rel == "conflict" or not g0:
                VIOLATIONS.append({
                    "slot": slot, "round": rnd, "viewer": n.id, "owners": owners,
                    "owner_src": sorted({RECORDS[(o, rnd)]["src"] for o in owners}),
                    "root_slot": _slot(s, root), "viewer_safe_slot": _slot(s, safe),
                    "conflicts_viewer_safe": rel == "conflict", "g0_clear_at_viewer": g0,
                })


def report(nodes, cut_start, heal, path=None):
    ref = nodes[0].store
    ids = [n.id for n in nodes]
    rounds = sorted({r for (_, r) in RECORDS})
    spr = int(spec.get_slots_per_round_at_slot(spec.Slot(0)))
    heal_round = heal // spr

    def phase(rnd):
        start = rnd * spr
        if start < cut_start:
            return "before"
        return "cut" if start < heal else "after"

    per_round = []
    for rnd in rounds:
        recs = [RECORDS[(i, rnd)] for i in ids if (i, rnd) in RECORDS and "chosen" in RECORDS[(i, rnd)]]
        if not recs:
            continue
        chosen = [r["chosen"] for r in recs]
        rels = {relation(ref, a, b) for a in chosen for b in chosen}
        p1 = "conflict" if "conflict" in rels else ("nested" if rels - {"same"} else "same")
        per_round.append({
            "round": rnd, "phase": phase(rnd), "p1_cross_node": p1,
            "nodes": {r["node"]: {
                "chosen": _slot(ref, r["chosen"]), "src": r["src"], "g1_reason": r["g1_reason"],
                "lock": _slot(ref, r["lock"]) if r["lock"] is not None else None,
                "g1": _slot(ref, r["g1"]), "g1_before_freeze": _slot(ref, r.get("g1_before_freeze", r["g1"])),
                "pinned_simplex": _slot(ref, r["pinned_simplex"]) if r["pinned_simplex"] is not None else None,
                "action_simplex": _slot(ref, r["action_simplex"]), "safe": _slot(ref, r["safe"]),
            } for r in recs},
        })

    p2 = []
    for i in ids:
        prev = None
        for rnd in rounds:
            rec = RECORDS.get((i, rnd))
            if not rec or "chosen" not in rec:
                continue
            if prev is not None:
                rel = relation(ref, rec["chosen"], prev["chosen"])
                if rel in ("below", "conflict"):
                    p2.append({"node": i, "round": rnd, "phase": phase(rnd),
                               "kind": "regression" if rel == "below" else "conflict",
                               "from_slot": _slot(ref, prev["chosen"]), "to_slot": _slot(ref, rec["chosen"]),
                               "src": rec["src"]})
            prev = rec

    p4 = None
    for row in per_round:
        if row["round"] < heal_round:
            continue
        if row["p1_cross_node"] == "same" and p4 is None:
            p4 = row["round"] - heal_round
        elif row["p1_cross_node"] != "same":
            p4 = None

    g1_rounds = [{"round": row["round"], "phase": row["phase"],
                  "g1_nodes": {k: v for k, v in row["nodes"].items() if v["src"] == "G1"},
                  "others": sorted({(v["chosen"], v["src"]) for v in row["nodes"].values() if v["src"] != "G1"})}
                 for row in per_round if any(v["src"] == "G1" for v in row["nodes"].values())]
    pre_freeze_diff = sorted({(row["round"], k) for row in per_round for k, v in row["nodes"].items()
                              if v["g1_before_freeze"] != v["chosen"]})

    # P5 finality safety: finalized checkpoints pairwise on one chain; no two justified
    # checkpoints at the same height on conflicting branches.
    p5 = []
    for slot, row in TRACE:
        fins = {v[0] for v in row.values()}
        if any(relation(ref, a, b) == "conflict" for a in fins for b in fins):
            p5.append({"slot": slot, "kind": "finalized conflict"})
        by_height = {}
        for v in row.values():
            by_height.setdefault(v[2], set()).add(v[1])
        for h, roots in by_height.items():
            if any(relation(ref, a, b) == "conflict" for a in roots for b in roots):
                p5.append({"slot": slot, "kind": f"justified conflict at height {h}"})

    # P6 post-GST finality: first slot at which every node has finalized a block proposed at
    # or after the cut start (resp. at or after GST).
    def first_all(pred):
        for slot, row in TRACE:
            if slot >= heal and all(pred(_slot(ref, v[0])) for v in row.values()):
                return slot
        return None

    fin_cut = first_all(lambda s: s is not None and s >= cut_start)
    fin_gst = first_all(lambda s: s is not None and s >= heal)
    last_slot = TRACE[-1][0] if TRACE else None
    final_fin = sorted({_slot(ref, v[0]) for v in TRACE[-1][1].values()}) if TRACE else []

    # P7 user-facing (non-retracting) confirmation off the final canonical chain after GST.
    canon = nodes[0].head().root
    p7 = {}
    for n in nodes:
        off = [slot for slot, row in TRACE if slot >= heal and not is_ancestor_root(ref, row[n.id][3], canon)]
        if off:
            p7[n.id] = {"slots_off_after_gst": len(off), "last_off_slot": off[-1],
                        "still_off_at_end": off[-1] == last_slot}

    # P8 rounds after GST where validators cast no height-progress marker (empty vote) or no vote.
    p8 = {}
    for rnd in range(heal_round, (last_slot or 0) // spr + 1):
        kinds = Counter()
        for n in nodes:
            kinds.update(n.vote_kinds.get(rnd, {}))
        no_marker = sum(c for k, c in kinds.items() if k.startswith("empty"))
        no_vote = kinds.get("skipped", 0) + kinds.get("refused", 0)
        if no_marker or no_vote:
            p8[rnd] = {"empty": no_marker, "no_vote": no_vote, "total": sum(kinds.values())}

    out = {
        "p5_finality_safety_violations": p5,
        "p6_first_slot_all_finalized_block_from_cut_or_later": fin_cut,
        "p6_first_slot_all_finalized_post_gst_block": fin_gst,
        "p6_heal_slot": heal, "p6_last_slot": last_slot, "p6_final_finalized_slots": final_fin,
        "p7_user_confirmation_off_canonical_after_gst": p7,
        "p8_rounds_with_empty_or_missing_votes_after_gst": p8,
        "p9_unreachable_confirmation_resets": CONF_RESETS,
        "p1_conflicting_rounds": [r["round"] for r in per_round if r["p1_cross_node"] == "conflict"],
        "p1_nested_rounds": [r["round"] for r in per_round if r["p1_cross_node"] == "nested"],
        "p2": p2,
        "p3": VIOLATIONS,
        "p4_rounds_to_common_stable_root_after_heal": p4,
        "g1_rounds": g1_rounds,
        "pre_freeze_g1_differs_from_frozen_root": pre_freeze_diff,
        "per_round": per_round,
    }
    print("\n== stable-root properties ==")
    print(f"P1 conflicting rounds: {out['p1_conflicting_rounds']} | nested rounds: {out['p1_nested_rounds']}")
    print(f"P2 per-node regressions/conflicts: {Counter((x['kind'], x['phase']) for x in p2)}")
    for x in p2:
        print(f"    node {x['node']} round {x['round']} ({x['phase']}): {x['kind']} {x['from_slot']} -> {x['to_slot']} [{x['src']}]")
    p3_summary = Counter((v["round"], v["owner_src"][0], v["conflicts_viewer_safe"], v["g0_clear_at_viewer"])
                         for v in VIOLATIONS)
    print(f"P3 checks failed (round, owner src, conflicts viewer safe, G0-clear at viewer): {dict(p3_summary)}")
    print(f"P4 rounds after heal until a common stable root: {p4}")
    for g in g1_rounds:
        print(f"G1 used: round {g['round']} ({g['phase']}): {g['g1_nodes']} | others {g['others']}")
    print(f"live G1 before freeze != frozen root (round, node): {len(pre_freeze_diff)} cases")
    print(f"P5 finality safety violations: {len(p5)} {p5[:3]}")
    print(f"P6 heal {heal}: all nodes finalized a block from the cut or later at slot {fin_cut}, "
          f"a post-GST block at slot {fin_gst} (run ends {last_slot}, finalized {final_fin})")
    print(f"P7 user-facing confirmation off the canonical chain after GST: {p7}")
    print(f"P8 empty/missing finality votes per round after GST: {p8}")
    print(f"P9 'unreachable' finalized-conflict reset of a confirmation record: {len(CONF_RESETS)} "
          f"{CONF_RESETS[:4]}")
    if path:
        with open(path, "w") as fh:
            json.dump(out, fh, indent=1)
    return out
