"""Aggregate the asynchrony sweep (props_<scenario>_seed<k>.json) into one table.

Usage: python async_summary.py RESULTS_DIR
Per scenario (seeds pooled): finality safety violations (P5), post-GST finality latency
(P6), user-facing confirmations off the canonical chain after GST and how long (P7), rounds
with only empty finality votes after GST (P8), "unreachable" confirmation resets (P9), and
the stable-root checks (P1-P4) from the earlier sweep.
"""
import ast
import glob
import json
import os
import re
import sys
from collections import defaultdict

TAG = re.compile(r"props_(.+)_seed(\d+)\.json$")
SPR = 8


def bare_empty_rounds(log_path, heal):
    """Rounds after GST whose finality votes carry no target, timeout or finality vote."""
    if not os.path.exists(log_path):
        return None
    rounds, inside = [], False
    with open(log_path) as fh:
        for line in fh:
            if line.startswith("finality vote kinds per round"):
                inside = True
                continue
            m = re.match(r"\s+round (\d+): (\{.*\})", line) if inside else None
            if m:
                rnd, kinds = int(m.group(1)), ast.literal_eval(m.group(2))
                if rnd >= heal // SPR and set(kinds) <= {"empty", "skipped", "refused"}:
                    rounds.append(rnd)
    return rounds


def main(results_dir):
    rows = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(results_dir, "props_*.json"))):
        m = TAG.search(path)
        if not m:
            continue
        with open(path) as fh:
            p = json.load(fh)
        log = os.path.join(results_dir, f"run_{m.group(1)}_seed{m.group(2)}.log")
        p["bare_empty_rounds"] = bare_empty_rounds(log, p["p6_heal_slot"])
        rows[m.group(1)].append((int(m.group(2)), p))

    print("scenario            | P5 | fin(cut-block) after GST | fin(post-GST block) | P7 nodes off / max slots off"
          " / stuck at end | P8 bare-empty rounds | P9 resets | P1c P2c P3 | G1 rounds")
    for scen, runs in sorted(rows.items()):
        p5 = sum(len(p["p5_finality_safety_violations"]) for _, p in runs)
        lat_cut, lat_gst, offs, maxoff, stuck, empty_rounds, resets, g1 = [], [], 0, 0, 0, 0, 0, 0
        p1c = p2c = p3 = 0
        for _, p in runs:
            heal = p["p6_heal_slot"]
            fc, fg = p["p6_first_slot_all_finalized_block_from_cut_or_later"], p["p6_first_slot_all_finalized_post_gst_block"]
            lat_cut.append(fc - heal if fc is not None else None)
            lat_gst.append(fg - heal if fg is not None else None)
            p7 = p["p7_user_confirmation_off_canonical_after_gst"]
            offs += len(p7)
            maxoff = max([maxoff] + [v["slots_off_after_gst"] for v in p7.values()])
            stuck += sum(v["still_off_at_end"] for v in p7.values())
            empty_rounds += len(p["bare_empty_rounds"] or [])
            resets += len(p["p9_unreachable_confirmation_resets"])
            p1c += bool(p["p1_conflicting_rounds"])
            p2c += any(x["kind"] == "conflict" for x in p["p2"])
            p3 += len(p["p3"])
            g1 += len(p["g1_rounds"])
        n_nodes = 8 * len(runs)
        print(f"{scen:19s} | {p5:2d} | {str(lat_cut):24s} | {str(lat_gst):19s} | "
              f"{offs:2d}/{n_nodes} / {maxoff:3d} / {stuck:2d}            | {empty_rounds:19d} | {resets:9d} | "
              f"{p1c:3d} {p2c:3d} {p3:2d} | {g1}")


if __name__ == "__main__":
    main(sys.argv[1])
