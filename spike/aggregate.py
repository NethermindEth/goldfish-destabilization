"""Aggregate partition_run.py JSON summaries into a per-setting table (over seeds).

Usage: python aggregate.py results/seeded/*.json
"""

import json
import sys
from collections import defaultdict

HONEST_FIRST_FINALITY = (16, 40)  # honest schedule: slot 16 finalized at slot 40


def run_metrics(d):
    nodes = d["per_node"]
    finalized_at = next(
        (slot for slot, fin in d["finality_timeline"] if fin >= HONEST_FIRST_FINALITY[0]), None
    )
    regressions, conflicting, nested, g1 = 0, 0, 0, 0
    prev_max = None
    for _, r in sorted(d["stable_rounds"].items(), key=lambda kv: int(kv[0])):
        if prev_max is not None and min(r["slots"]) < prev_max:
            regressions += 1
        prev_max = max(r["slots"])
        conflicting += r["relation"] == "conflicting"
        nested += r["relation"] == "nested"
        g1 += r["sources"].get("G1", 0) > 0
    return {
        "max_reorg": max(n["max_reorg_depth"] for n in nodes),
        "orphaned_safe": max(n["orphaned_safe"] for n in nodes),
        "orphaned_avail": max(n["orphaned_available"] for n in nodes),
        "losing_nodes": sum(1 for n in nodes if n["reorgs"]),
        "reconverge": d["reconverge_slots"],
        "finality_delay": None if finalized_at is None else finalized_at - HONEST_FIRST_FINALITY[1],
        "stable_regressions": regressions,
        "rounds_nested": nested,
        "rounds_conflicting": conflicting,
        "rounds_with_g1": g1,
    }


def fmt(values):
    values = [v for v in values if v is not None]
    if not values:
        return "–"
    lo, hi, mean = min(values), max(values), sum(values) / len(values)
    return f"{mean:.1f}" if lo == hi else f"{mean:.1f} [{lo}–{hi}]"


def main(paths):
    groups = defaultdict(list)
    for path in paths:
        with open(path) as fh:
            d = json.load(fh)
        c = d["config"]
        share = round(100 * c["split"] / c["nodes"])
        groups[(share, c["slots_down"], c["start"])].append(run_metrics(d))
    cols = [
        ("max_reorg", "max reorg (blocks)"),
        ("orphaned_safe", "orphaned safe-conf"),
        ("orphaned_avail", "orphaned avail-conf"),
        ("reconverge", "reconverge (slots)"),
        ("finality_delay", "finality delay (slots)"),
        ("stable_regressions", "stable-root regressions"),
        ("rounds_with_g1", "rounds using G1"),
        ("rounds_nested", "rounds nested roots"),
        ("rounds_conflicting", "rounds conflicting roots"),
    ]
    print("| split A/B | D | cut starts at slot | runs | " + " | ".join(h for _, h in cols) + " |")
    print("|---" * (len(cols) + 4) + "|")
    for (share, D, start), runs in sorted(groups.items()):
        cells = [fmt([r[k] for r in runs]) for k, _ in cols]
        print(f"| {share}/{100 - share} | {D} | {start} | {len(runs)} | " + " | ".join(cells) + " |")
    print("\nCells: mean [min–max] over seeds. Orphaned counts are the worst node in the run.")


if __name__ == "__main__":
    main(sys.argv[1:])
