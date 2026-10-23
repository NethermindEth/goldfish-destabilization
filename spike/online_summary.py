"""Summarize the online-share sweep: justification outcome at each round boundary, split by
whether the round's first block was present on the online chain, per number of online nodes.

Usage: python online_summary.py results/online/*.events.json results/margin2/*.events.json
"""
import json, math, sys
from collections import defaultdict

rows = defaultdict(lambda: {"present": [0, 0], "missing": [0, 0], "match": [0, 0]})
for p in sys.argv[1:]:
    d = json.load(open(p))
    R, cfg = d["slots_per_round"], d["config"]
    q = math.ceil(2 * cfg["validators"] / 3)
    groups = list(d["group_of"].values())
    online = {i for i, g in enumerate(groups) if g == 0}
    node = min(online)
    share = len(online) / len(groups)
    has_block = {st["slot"]: st["nodes"][node]["head_slot"] == st["slot"] for st in d["states"]}
    votes = defaultdict(list)
    for m in d["messages"]:
        if m["kind"] == "att" and m["src"] == m["dst"] and m["src"] in online:
            votes[m["slot"]].append((m["vote"], m["n"]))
    minority = (len(groups) - len(online)) * cfg["validators"] // cfg["nodes"]
    seen = set()
    for r in d["outcomes"]:
        s = r["slot"]
        if s % R or s < 24 or max(r["target_votes"], r["timeouts"], r["finality_votes"]) <= minority:
            continue
        key = (s, r["height"], r["justified_slot"])
        if key in seen: continue
        seen.add(key)
        # only rounds whose votes were justify votes for this height: did justification happen?
        justify_votes = sum(n for X in range(s - R, s) for v, n in votes[X] if v.startswith("justify") and f"@h{r['height']}" in v.split("+")[0])
        if justify_votes < q: continue  # not a justify round (empty round), or too few voters to begin with
        ok = r["height_after"] != r["height"]
        b = "present" if has_block.get(s) else "missing"
        rows[share][b][0] += ok; rows[share][b][1] += 1
        pred = sum(n for X in range(s - R, s) if any(has_block.get(y) for y in range(X + 1, s + 1))
                   for v, n in votes[X] if v.startswith("justify") and f"@h{r['height']}" in v.split("+")[0])
        rows[share]["match"][0] += pred == r["target_votes"]; rows[share]["match"][1] += 1
thr = 2 / 3 * 8 / 7
print(f"threshold for a missing round-start block (R=8): {thr:.3f}")
print("| online | justify rounds, block present: justified | block missing: justified | predicted == on-chain |")
print("|---|---|---|---|")
for sh in sorted(rows, reverse=True):
    r = rows[sh]
    f = lambda a: f"{a[0]}/{a[1]}" if a[1] else "–"
    print(f"| {sh:.1%} | {f(r['present'])} | {f(r['missing'])} | {f(r['match'])} |")
