"""Aggregate stability_props results (props_<tag>.json) across a sweep directory.

Usage: python props_summary.py RESULTS_DIR
Groups runs by (split, start, D) and reports, per group, how many seeds show each property
finding, plus the list of G1 fallbacks with their reason and how they related to the other
nodes' stable roots.
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

TAG = re.compile(r"props_split(\d+)_start(\d+)_d(\d+)_seed(\d+)\.json$")


def main(results_dir):
    groups = defaultdict(list)
    g1_rows = []
    for path in sorted(glob.glob(os.path.join(results_dir, "props_*.json"))):
        m = TAG.search(path)
        if not m:
            continue
        split, start, d, seed = map(int, m.groups())
        with open(path) as fh:
            p = json.load(fh)
        groups[(split, start, d)].append((seed, p))
        for g in p["g1_rounds"]:
            others = {c for c, _ in g["others"]}
            for node, v in g["g1_nodes"].items():
                g1_rows.append((split, start, d, seed, g["round"], g["phase"], node, v["chosen"],
                                v["g1_reason"], "same as others" if others == {v["chosen"]} else f"others {sorted(others)}"))

    print("split start  D | runs | P1 conflict | P1 nested | P2 conflict | P2 regress(cut/after) "
          "| P3 fails | P4 rounds after heal | G1 rounds")
    for (split, start, d), runs in sorted(groups.items()):
        p1c = sum(bool(p["p1_conflicting_rounds"]) for _, p in runs)
        p1n = sum(bool(p["p1_nested_rounds"]) for _, p in runs)
        p2c = sum(any(x["kind"] == "conflict" for x in p["p2"]) for _, p in runs)
        reg = Counter(x["phase"] for _, p in runs for x in p["p2"] if x["kind"] == "regression")
        p3 = sum(len(p["p3"]) for _, p in runs)
        p4 = Counter(p["p4_rounds_to_common_stable_root_after_heal"] for _, p in runs)
        g1 = sum(len(p["g1_rounds"]) for _, p in runs)
        print(f"{split:5d} {start:5d} {d:2d} | {len(runs):4d} | {p1c:11d} | {p1n:9d} | {p2c:11d} | "
              f"{reg.get('cut', 0):3d}/{reg.get('after', 0):<3d}               | {p3:8d} | {dict(p4)} | {g1}")

    print("\nG1 fallbacks: split start D seed round phase node chosen_slot reason relation")
    reasons = Counter(r[8] for r in g1_rows)
    relations = Counter(r[9] == "same as others" for r in g1_rows)
    for r in g1_rows:
        print("  ", *r)
    print(f"\nG1 reasons: {dict(reasons)}; same root as the non-G1 nodes: {relations.get(True, 0)}"
          f" / {len(g1_rows)}")
    fails = [(k, seed, v) for k, runs in groups.items() for seed, p in runs for v in p["p3"]]
    if fails:
        print("\nP3 failures (group, seed, detail):")
        for k, seed, v in fails[:40]:
            print("  ", k, seed, v)


if __name__ == "__main__":
    main(sys.argv[1])
