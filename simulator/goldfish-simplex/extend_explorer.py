"""Add runs (and per-run labels) to an existing explorer page without its source event files.

make_figures.py builds the page from one events JSON per tab. The runs already embedded in a
built page can be re-used as they are: this script reads that page's DATA, optionally attaches
`meta` (header facts, callout boxes, jump buttons) to named runs, adds new runs from events
files, and writes the page again with the current template.

    python extend_explorer.py BASE.html OUT.html [--first NAME]

Meta is defined in META below, keyed by the tab name.
"""

import argparse
import json
import os
import re

import make_figures as mf

HONEST_PILLS = (
    '<span class="side-pill side-a"><b>Honest (75%)</b>: Nodes 0–2 (48/64 stake)</span>'
    '<span class="side-pill side-b"><b>Adversary (25%)</b>: Node 3 (16/64 stake)</span>'
)
SYNC_FACTS = HONEST_PILLS + '<span>all message delays <b>≤ 1400 ms &lt; Δ = 1500 ms</b> · no equivocation</span>'

META = {
    "Synchrony attack (slot 13)": {
        "facts": SYNC_FACTS + "<span>attack slot <b>13</b></span>",
        "callouts": [
            {"color": "held", "title": "① Slot 13 @ 1.4–1.6 s (split delivery)",
             "body": "The adversary proposes B13 and sends it at 0.2 s. Nodes 0–1 receive it at 1.4 s, before the 25% deadline, and vote B13; node 2 receives it at 1.6 s and votes B12."},
            {"color": "b", "title": "② Slot 13 @ 3.0–4.5 s (armed, then outvoted)",
             "body": "At the 50% freeze B13 holds 243/389 seats (62.5%) and is armed for delayed confirmation. The adversary's 123 votes for B12 arrive at 3.4 s, before the 75% view freeze, so B13 falls to 243/512 (47.5%) and is no longer viable."},
            {"color": "heal", "title": "③ Slot 14 @ 0 s (honest proposer orphans B13)",
             "body": "The honest slot-14 proposer's head walk rejects B13 and builds B14 on B12."},
            {"color": "tsq", "title": "④ Slot 14 @ 3.0 s (permanence breaks)",
             "body": "The frozen 50% snapshot of slot 13 confirms B13 (available and safe: only slot 14's cohort, 1/8 of D &lt; 1/3, has voted for B14). Safe confirmation reverts to B14 at slot 15."},
        ],
        "jumps": [["Attack (s13)", 10], ["Orphaning (s14)", 12], ["Reversal (s15)", 13]],
        "zooms": [["s12 (before)", 12], ["s13 (attack)", 13], ["s14 (B13 orphaned)", 14], ["s15 (safe reverts)", 15]],
    },
    "Synchrony attack at round edge (slot 14)": {
        "facts": SYNC_FACTS + "<span>attack slot <b>14</b> (≡ 6 mod 8, seed 0)</span>",
        "callouts": [
            {"color": "held", "title": "① Slot 14 (same strategy, two slots before a round start)",
             "body": "Split delivery and a withheld parent vote as in the slot-13 run. The adversary's B14 is orphaned at slot 15; the honest proposer builds B15 on B13."},
            {"color": "b", "title": "② Slot 15 @ 3.0 s (B14 falsely confirmed)",
             "body": "B14 becomes the live confirmed head although honest nodes' head chain excludes it."},
            {"color": "heal", "title": "③ Slot 16 @ 0 s (round-start proposer drops B15)",
             "body": "<code>get_proposer_head</code> takes the deeper of the TSQ candidate and the live confirmed head (B14); the honest head B15 does not descend from it, so honest node 0 builds B16 on B14 and orphans the honest B15."},
            {"color": "tsq", "title": "④ Finality votes",
             "body": "0 of 199 honest finality attestations name an orphaned block as target or finality target; 5 head fields name B15."},
        ],
        "jumps": [["Attack (s14)", 11], ["Round start (s16)", 13]],
        "zooms": [["s14 (attack)", 14], ["s15 (B14 orphaned)", 15], ["s16 (round start)", 16], ["s17", 17]],
    },
}

SWING = "Repeated swing, adaptive split (seed 0)"
SWING_META = {
    "facts": SYNC_FACTS + "<span>the adversary attacks in <b>every slot it proposes</b> · 96 slots</span>",
    "callouts": [
        {"color": "held", "title": "① 16 attacks, 14 break permanence",
         "body": "Each time node 3 proposes it picks the honest subset that gets the block early and plays the slot-13 strategy. Red-ringed blocks in the tree were safe-confirmed and then orphaned: 14 adversarial blocks plus honest blocks 47 and 71."},
        {"color": "b", "title": "② Round-edge swing (s46 → s48, s70 → s72)",
         "body": "An attack at slot ≡ 6 mod 8 leaves the adversary's block canonical and drops the honest block of slot ≡ 7. At slot 48: head s47, TSQ candidate s42, live confirmed s46; the proposer builds on s46."},
        {"color": "tsq", "title": "③ Finality and stable roots are unchanged",
         "body": "Finalized slot 64 at slot 96, as in the no-attack baseline; finality lag mean 29.7 vs 29.9 slots. All 36 stable roots come from the TSQ lock and none is orphaned. 45 of 382 honest finality attestations name an orphan as head, none as target."},
        {"color": "heal", "title": "④ Chain growth",
         "body": "0.833 canonical blocks per slot (80 of 96): 14 adversarial and 2 honest blocks lost."},
    ],
    "jumps": [["First attacks (s15–18)", 12], ["Round edge s46–48", 44], ["Round edge s70–72", 68]],
    "zooms": [["s15", 15], ["s46", 46], ["s47", 47], ["s48 (round start)", 48], ["s71", 71], ["s72 (round start)", 72]],
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("base")
    p.add_argument("out")
    p.add_argument("--first", help="tab to show first (for screenshots)")
    p.add_argument("--swing-events", required=True)
    args = p.parse_args()

    html = open(args.base, encoding="utf-8").read()
    m = re.search(r"const DATA = (\{.*?\});\n", html, re.S)
    data = json.loads(m.group(1))
    for name, meta in META.items():
        if name in data["runs"]:
            data["runs"][name]["meta"] = meta
    data["runs"][SWING] = mf.compact(args.swing_events, SWING_META)
    if args.first:
        data["runs"] = {args.first: data["runs"][args.first], **{k: v for k, v in data["runs"].items() if k != args.first}}
    out = mf.TEMPLATE.replace("/*DATA*/", "const DATA = " + json.dumps(data, separators=(",", ":")) + ";")
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"wrote {args.out} ({len(out) / 1e6:.2f} MB); tabs: {list(data['runs'])}")


if __name__ == "__main__":
    main()
