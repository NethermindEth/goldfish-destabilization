"""Refined liveness-margin test: count the majority's actual votes per round from the event log.

For round r (slots s0..s0+R-1), with boundary s = s0+R on majority node 0's chain:
  votes[kind] = majority validators whose round-r vote has that property (each node's own
                copy of its aggregates, src == dst, so every vote is counted once)
  lost        = majority validators voting in the round's last slot, if the block at s is missing
Predicted progress iff  max(justify, justify+timeout, finalize) - lost >= ceil(2N/3).
"""
import json, math, sys
from collections import Counter

tab, bad = Counter(), []
for p in sys.argv[1:]:
    d = json.load(open(p))
    R, cfg = d["slots_per_round"], d["config"]
    N = cfg["validators"]; q = math.ceil(2 * N / 3)
    groups = list(d["group_of"].values()) if isinstance(d["group_of"], dict) else d["group_of"]
    major = {i for i, g in enumerate(groups) if g == 0}
    node = min(major)
    st = {s["slot"]: s["nodes"][node] for s in d["states"]}
    key = lambda n: (n["chain_height"], n["justified_slot"], n["finalized_slot"])
    per = {}  # slot -> list of (vote label, n)
    for m in d["messages"]:
        t, at, src, dst, kind, held, slot, vote = m["t"], m["at"], m["src"], m["dst"], m["kind"], m["held"], m["slot"], m.get("vote")
        if kind == "att" and src == dst and src in major:
            per.setdefault(slot, []).append((vote, m["n"]))
    end = cfg["start"] + cfg["slots_down"]
    first = (cfg["start"] // R + 1) * R
    for s0 in range(first, end - R, R):
        s = s0 + R
        if s + 1 not in st: continue
        c = Counter(); last = 0
        for slot in range(s0, s):
            for vote, n in per.get(slot, []):
                if vote.startswith("justify"): c["justify"] += n
                if vote.startswith(("justify", "timeout")): c["tq"] += n
                if "+fin@" in vote: c["fin"] += n
                if slot == s - 1: last += n
        missed = st[s]["head_slot"] != s
        support = max(c["justify"], c["tq"], c["fin"]) - (last if missed else 0)
        pred = support >= q
        got = key(st[s + 1]) != key(st[s - 1])
        tab[(pred, got)] += 1
        if pred != got: bad.append((p.split("/")[-1], s, missed, dict(c), last, got))
print("(predicted progress, observed progress):", dict(tab))
print(f"agreement {tab[(True,True)] + tab[(False,False)]}/{sum(tab.values())}")
for b in bad[:15]: print("  mismatch", b)
