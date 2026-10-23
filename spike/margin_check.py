"""Check the liveness-margin mechanism against on-chain counts recorded at each height settlement.

Model: a majority vote cast in slot X of round r counts at the settlement at boundary s
iff the majority chain has a block in slots X+1..s (so some block can include it before
the outcome is settled). Predicted on-chain count = majority votes passing that test,
for the vote property the settlement uses (target votes for a justify round, finality
piggybacks otherwise). Compared with what the spec state actually held (OUTCOMES hook).

Usage: python margin_check.py results/margin2/seed*.events.json
"""
import json, math, sys
from collections import Counter

rows, tally = [], Counter()
for p in sys.argv[1:]:
    d = json.load(open(p))
    R, cfg = d["slots_per_round"], d["config"]
    q = math.ceil(2 * cfg["validators"] / 3)
    groups = list(d["group_of"].values())
    major = {i for i, g in enumerate(groups) if g == 0}
    node = min(major)
    has_block = {s["slot"]: s["nodes"][node]["head_slot"] == s["slot"] for s in d["states"]}
    votes = {}  # slot -> list of (label, n)
    for m in d["messages"]:
        if m["kind"] == "att" and m["src"] == m["dst"] and m["src"] in major:
            votes.setdefault(m["slot"], []).append((m["vote"], m["n"]))
    seen = set()
    for r in d["outcomes"]:
        s = r["slot"]
        if s % R or s < 24 or max(r["target_votes"], r["timeouts"], r["finality_votes"]) <= 16:
            continue  # boundary settlements on the majority chain only
        key = (s, r["height"], r["justified_slot"])
        if key in seen: continue
        seen.add(key)
        pred_t = pred_f = 0
        for X in range(s - R, s):
            carried = any(has_block.get(y, False) for y in range(X + 1, s + 1))
            for label, n in votes.get(X, []):
                if not carried: continue
                if label.startswith("justify") and f"@h{r['height']}" in label.split("+")[0]: pred_t += n
                if f"+fin@h" in label: pred_f += n
        actual_t, actual_f = r["target_votes"], r["finality_votes"]
        progressed = r["height_after"] != r["height"] or r["finalized_after"] != r["finalized_slot"]
        ok_t, ok_f = pred_t == actual_t, pred_f == actual_f or actual_f == 0
        tally[(ok_t, ok_f)] += 1
        rows.append((p.split("/")[-1], s, has_block.get(s), pred_t, actual_t, pred_f, actual_f, progressed))
print("settlements where predicted == on-chain (target, finality):", dict(tally))
bad = [r for r in rows if r[3] != r[4] or (r[5] != r[6] and r[6] != 0)]
print(f"mismatches: {len(bad)}/{len(rows)}")
print("file, slot, block@s, pred_target, chain_target, pred_fin, chain_fin, progressed")
for r in bad[:20]: print("  ", r)
fails = [r for r in rows if not r[7]]
print(f"\nfailed settlements: {len(fails)}; with block at s missing: {sum(1 for r in fails if not r[2])}")
