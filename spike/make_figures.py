"""Build an interactive HTML explorer and static SVG/PDF/PNG figures for simulator runs.

Usage:
    python make_figures.py OUT.html NAME=events.json [NAME=events.json ...] [--sweep-dir DIR]
e.g.
    python make_figures.py results/figs/partition-explorer.html \
        "50/50 split=results/figs/split50.json" \
        "75/25 split=results/figs/split75.json" \
        "Honest=results/figs/honest.json"
"""

import glob
import html as html_mod
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict

KINDS = {"block": 0, "att": 1, "avail": 2}
HONEST_FIRST_FINALITY = (16, 40)  # honest schedule: slot 16 finalized at slot 40


def classify_stable_src(slot, stable_slot, raw_src):
    """Distinguish genuine TSQ locks (>0) from the genesis Simplex floor (0) and G1 fallback."""
    if stable_slot is None:
        return "-"
    if raw_src == "G1":
        return "G1"
    if stable_slot == 0:
        return "INIT" if slot < 16 else "FLOOR"
    return "TSQ"


def compact(path):
    with open(path) as fh:
        d = json.load(fh)
    cfg = d["config"]
    votes, msgs, blocks = [], [], {}
    for m in d["messages"]:
        vote = -1
        if m["kind"] == "att":
            if m["vote"] not in votes:
                votes.append(m["vote"])
            vote = votes.index(m["vote"])
        msgs.append([
            m["t"], m["at"], m["src"], m["dst"], KINDS[m["kind"]],
            int(m["held"]), m["slot"], vote
        ])
        if m["kind"] == "block" and m["root"] not in blocks:
            blocks[m["root"]] = [m["slot"], m["parent"], m["src"], m.get("proposer", -1), m.get("n_att", 0)]
    states = []
    for s in d["states"]:
        slot = s["slot"]
        nodes_row = []
        for n in s["nodes"]:
            src_tag = classify_stable_src(slot, n["stable_slot"], n["stable_src"])
            nodes_row.append([
                n["head_slot"], n["head_root"],
                n["safe_conf_slot"], n["safe_root"],
                n["stable_slot"], n["stable_root"],
                n["finalized_slot"], n["justified_slot"],
                n["chain_height"], src_tag, n.get("h_max", n["chain_height"])
            ])
        states.append([slot, nodes_row])
    return {
        "cfg": {
            k: cfg[k]
            for k in ("nodes", "split", "start", "slots_down", "seed", "latency_ms", "jitter_ms", "validators")
        },
        "groupOf": [
            d["group_of"][str(i)] if str(i) in d["group_of"] else d["group_of"][i]
            for i in range(cfg["nodes"])
        ],
        "slotMs": d["slot_ms"],
        "deadlines": d["deadlines_ms"],
        "spr": d["slots_per_round"],
        "votes": votes,
        "msgs": msgs,
        "blocks": blocks,
        "states": states,
        "settlements": settlements_of(d),
    }


def settlements_of(d):
    """Round-boundary height settlements on the majority chain (needs the OUTCOMES trace).

    Each row: [slot, height, target_votes, finality_votes, timeouts, progressed,
    block_at_slot, justified, finalized]; quorum = ceil(2 * validators / 3).
    """
    if not d.get("outcomes"):
        return None
    cfg, R = d["config"], d["slots_per_round"]
    groups = list(d["group_of"].values()) if isinstance(d["group_of"], dict) else d["group_of"]
    major = min(i for i, g in enumerate(groups) if g == 0)
    minority_size = sum(1 for g in groups if g == 1) * cfg["validators"] // cfg["nodes"]
    has_block = {st["slot"]: st["nodes"][major]["head_slot"] == st["slot"] for st in d["states"]}
    rows, seen = [], set()
    for r in d["outcomes"]:
        if r["slot"] % R or max(r["target_votes"], r["timeouts"], r["finality_votes"]) <= minority_size:
            continue
        key = (r["slot"], r["height"], r["justified_slot"], r["finalized_slot"])
        if key in seen:
            continue
        seen.add(key)
        quorum = -(-2 * cfg["validators"] // 3)
        just = r["height_after"] != r["height"] and r["target_votes"] >= quorum
        fin = r["finalized_after"] != r["finalized_slot"]
        rows.append([r["slot"], r["height"], r["target_votes"], r["finality_votes"], r["timeouts"],
                     int(r["height_after"] != r["height"] or fin), int(has_block.get(r["slot"], False)),
                     int(just), int(fin)])
    rows.sort()
    return {"rows": rows, "quorum": -(-2 * cfg["validators"] // 3)}


def load_sweep(sweep_dir):
    """Load 30-run seeded sweep JSONs into structured summary records."""
    dirs = sweep_dir if isinstance(sweep_dir, (list, tuple)) else str(sweep_dir).split(",")
    paths = sorted(p for d_ in dirs for p in glob.glob(os.path.join(d_, "*.json"))
                   if not p.endswith(".events.json"))
    if not paths:
        return None
    runs = []
    for p in paths:
        with open(p) as fh:
            d = json.load(fh)
        c = d["config"]
        nodes = d["per_node"]
        share = round(100 * c["split"] / c["nodes"])
        split_label = f"{share}/{100 - share}"
        finalized_at = next(
            (slot for slot, fin in d["finality_timeline"] if fin >= HONEST_FIRST_FINALITY[0]),
            None,
        )
        fin32_at = next(
            (slot for slot, fin in d["finality_timeline"] if fin >= 32),
            None,
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
        runs.append({
            "file": os.path.basename(p),
            "split": split_label,
            "share": share,
            "D": c["slots_down"],
            "start": c["start"],
            "seed": c["seed"],
            "nodes": c["nodes"],
            "validators": c["validators"],
            "max_reorg": max(n["max_reorg_depth"] for n in nodes),
            "orphaned_safe": max(n["orphaned_safe"] for n in nodes),
            "orphaned_avail": max(n["orphaned_available"] for n in nodes),
            "maj_orphaned_safe": max((n["orphaned_safe"] for n in nodes if n["group"] == "A"), default=0),
            "min_orphaned_safe": max((n["orphaned_safe"] for n in nodes if n["group"] == "B"), default=0),
            "reconverge": d["reconverge_slots"],
            "finality_delay": None if finalized_at is None else finalized_at - HONEST_FIRST_FINALITY[1],
            "fin32_delay": None if fin32_at is None else fin32_at - 56,
            "finality_timeline": d["finality_timeline"],
            "stable_regressions": regressions,
            "rounds_nested": nested,
            "rounds_conflicting": conflicting,
            "rounds_with_g1": g1,
        })
    return runs


# ---------------------------------------------------------------------------
# Static Publication-Ready SVG / PDF / PNG Generators
# ---------------------------------------------------------------------------

SVG_STYLE = """
<style>
  text { font-family: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; fill: #1b2230; }
  .mono { font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace; }
  .title { font-size: 18px; font-weight: 700; fill: #0f172a; }
  .subtitle { font-size: 12.5px; fill: #475569; }
  .panel-title { font-size: 14px; font-weight: 600; fill: #0f172a; }
  .axis-label { font-size: 11.5px; font-weight: 500; fill: #475569; }
  .tick { font-size: 11px; fill: #64748b; }
  .badge { font-size: 10.5px; font-weight: 600; }
  .note { font-size: 11px; fill: #334155; }
  .callout-box { fill: #ffffff; stroke: #cbd5e1; stroke-width: 1; rx: 5; }
  .grid { stroke: #e2e8f0; stroke-width: 1; }
  .grid-strong { stroke: #cbd5e1; stroke-width: 1.2; }
  .cut-tint { fill: #fee2e2; fill-opacity: 0.55; }
  .cut-line { stroke: #dc2626; stroke-width: 1.2; stroke-dasharray: 4,3; }
  .heal-line { stroke: #0d9488; stroke-width: 1.5; stroke-dasharray: 4,3; }
</style>
"""


def esc(s):
    return html_mod.escape(str(s))


def save_svg_and_convert(svg_path, svg_content):
    with open(svg_path, "w", encoding="utf-8") as fh:
        fh.write(svg_content)
    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        base = os.path.splitext(svg_path)[0]
        subprocess.run([rsvg, "-f", "pdf", "-o", base + ".pdf", svg_path], check=False)
        subprocess.run([rsvg, "-f", "png", "-d", "200", "-p", "200", "-w", "2200", "-o", base + ".png", svg_path], check=False)


def build_fig1_sweep_svg(sweep_runs):
    """Figure 1: 30-Run Seeded Sweep Summary (Reorg Depth, Orphaned Safe Blocks, Finality Delay)."""
    W, H = 1120, 470
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" style="background:#ffffff">',
        SVG_STYLE,
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>',
        '<text x="24" y="30" class="title">Partition Resilience Across 30 Seeded Runs (16 Nodes, 64 Validators, Minimal Preset)</text>',
        '<text x="24" y="48" class="subtitle">Cut starts at slot 24 (round 3) for duration D ∈ {8, 16, 32} slots (1, 2, 4 rounds), then heals (GST). 5 seeds per cell (varying RANDAO, placement, and 200+U[0,100] ms latency).</text>',
    ]

    # Legend at top right
    out.append('<g transform="translate(24, 62)">')
    out.append('<line x1="0" y1="6" x2="22" y2="6" stroke="#dc2626" stroke-width="2.5"/><circle cx="11" cy="6" r="4" fill="#dc2626"/>')
    out.append('<text x="28" y="10" class="axis-label" style="fill:#0f172a;font-weight:600">50/50 split (no 2/3 quorum during cut)</text>')
    out.append('<line x1="280" y1="6" x2="302" y2="6" stroke="#2563eb" stroke-width="2.5"/><circle cx="291" cy="6" r="4" fill="#2563eb"/>')
    out.append('<text x="308" y="10" class="axis-label" style="fill:#0f172a;font-weight:600">75/25 split (25% minority loses branch; 75% majority loses 0)</text>')
    out.append('<line x1="700" y1="6" x2="722" y2="6" stroke="#64748b" stroke-width="1.5" stroke-dasharray="4,3"/>')
    out.append('<text x="728" y="10" class="axis-label">Expected losing-branch share (D/2 vs D/4)</text>')
    out.append('</g>')

    by_group = defaultdict(list)
    for r in sweep_runs:
        by_group[(r["split"], r["D"])].append(r)

    Ds = [8, 16, 32]
    panels = [
        ("A. Max Reorg Depth (Blocks)", "max_reorg", 20, "Blocks abandoned on losing side", True),
        ("B. Orphaned Safe-Confirmed Blocks", "orphaned_safe", 20, "G0-clear blocks later orphaned", True),
        ("C. Delay of First Finality (Slots)", "finality_delay", 36, "Delay vs honest slot 40 (slot 16 fin)", False),
    ]

    pw, ph = 320, 260
    top_y = 105
    lefts = [48, 412, 776]

    for idx, (title, key, ymax, ylab, show_theory) in enumerate(panels):
        x0 = lefts[idx]
        y0 = top_y
        out.append(f'<text x="{x0 - 10}" y="{y0 - 12}" class="panel-title">{esc(title)}</text>')
        out.append(f'<rect x="{x0}" y="{y0}" width="{pw}" height="{ph}" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>')

        def X(d):
            return x0 + 30 + (d - 8) / (32 - 8) * (pw - 60)

        def Y(v):
            return y0 + ph - 20 - (v / ymax) * (ph - 40)

        # Y gridlines
        step = 4 if ymax <= 20 else 8
        for v in range(0, ymax + 1, step):
            yy = Y(v)
            out.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0 + pw}" y2="{yy:.1f}" class="grid"/>')
            out.append(f'<text x="{x0 - 6}" y="{yy + 4:.1f}" text-anchor="end" class="tick mono">{v}</text>')

        # X gridlines & labels
        for d in Ds:
            xx = X(d)
            out.append(f'<line x1="{xx:.1f}" y1="{y0}" x2="{xx:.1f}" y2="{y0 + ph}" class="grid"/>')
            out.append(f'<text x="{xx:.1f}" y="{y0 + ph + 18}" text-anchor="middle" class="tick mono">D={d} ({d//8}r)</text>')

        out.append(f'<text x="{x0 + pw / 2:.1f}" y="{y0 + ph + 36}" text-anchor="middle" class="axis-label">Partition duration D (slots / rounds)</text>')

        # Theory lines
        if show_theory:
            # D/2 and D/4
            out.append(f'<line x1="{X(8):.1f}" y1="{Y(4):.1f}" x2="{X(32):.1f}" y2="{Y(16):.1f}" stroke="#dc2626" stroke-opacity="0.4" stroke-width="1.5" stroke-dasharray="4,3"/>')
            out.append(f'<text x="{X(24):.1f}" y="{Y(12) - 6:.1f}" text-anchor="middle" class="tick" style="fill:#b91c1c;font-size:10px;font-weight:600">~D/2</text>')
            out.append(f'<line x1="{X(8):.1f}" y1="{Y(2):.1f}" x2="{X(32):.1f}" y2="{Y(8):.1f}" stroke="#2563eb" stroke-opacity="0.4" stroke-width="1.5" stroke-dasharray="4,3"/>')
            out.append(f'<text x="{X(24):.1f}" y="{Y(6) + 13:.1f}" text-anchor="middle" class="tick" style="fill:#1d4ed8;font-size:10px;font-weight:600">~D/4</text>')
        else:
            # Delay = D line for 50/50
            out.append(f'<line x1="{X(8):.1f}" y1="{Y(8):.1f}" x2="{X(32):.1f}" y2="{Y(32):.1f}" stroke="#dc2626" stroke-opacity="0.4" stroke-width="1.5" stroke-dasharray="4,3"/>')

        # Plot series
        for split, color, offset_x in [("50/50", "#dc2626", -6), ("75/25", "#2563eb", 6)]:
            means = []
            for d in Ds:
                vals = [r[key] for r in by_group[(split, d)] if r[key] is not None]
                if not vals:
                    continue
                lo, hi, mean = min(vals), max(vals), sum(vals) / len(vals)
                xx = X(d) + offset_x
                means.append((xx, Y(mean), mean, lo, hi, d))
                # Whisker bar for min-max
                if lo != hi:
                    out.append(f'<line x1="{xx:.1f}" y1="{Y(lo):.1f}" x2="{xx:.1f}" y2="{Y(hi):.1f}" stroke="{color}" stroke-width="1.8" stroke-opacity="0.55"/>')
                    out.append(f'<line x1="{xx - 4:.1f}" y1="{Y(lo):.1f}" x2="{xx + 4:.1f}" y2="{Y(lo):.1f}" stroke="{color}" stroke-width="1.5" stroke-opacity="0.7"/>')
                    out.append(f'<line x1="{xx - 4:.1f}" y1="{Y(hi):.1f}" x2="{xx + 4:.1f}" y2="{Y(hi):.1f}" stroke="{color}" stroke-width="1.5" stroke-opacity="0.7"/>')
                # Individual seeds (slightly jittered by seed index)
                for s_idx, v in enumerate(vals):
                    jx = xx + (s_idx - 2) * 2.2
                    out.append(f'<circle cx="{jx:.1f}" cy="{Y(v):.1f}" r="3.2" fill="{color}" fill-opacity="0.45" stroke="#ffffff" stroke-width="0.6"/>')

            # Mean line & mean markers
            if len(means) > 1:
                pts = " ".join(f"{mx:.1f},{my:.1f}" for mx, my, _, _, _, _ in means)
                out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.4"/>')
            for mx, my, mean, lo, hi, d in means:
                out.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="4.5" fill="{color}" stroke="#ffffff" stroke-width="1.2"/>')
                lbl = f"{mean:.1f}" if lo != hi else f"{int(mean)}"
                ly = my - 9 if split == "50/50" else my + 15
                if not show_theory and split == "75/25" and d in (16, 32):
                    ly = my - 10
                out.append(f'<text x="{mx:.1f}" y="{ly:.1f}" text-anchor="middle" class="badge mono" style="fill:{color}">{lbl}</text>')

        # Special annotation in Panel C for the 75/25 liveness margin
        if not show_theory:
            out.append(f'<rect x="{x0 + 12}" y="{y0 + 10}" width="198" height="52" class="callout-box"/>')
            out.append(f'<text x="{x0 + 20}" y="{y0 + 25}" class="badge" style="fill:#1e40af">75/25 Liveness Margin (§2.4):</text>')
            out.append(f'<text x="{x0 + 20}" y="{y0 + 39}" class="note" style="font-size:10.5px">Slips 1r (+8–9s) when round-start</text>')
            out.append(f'<text x="{x0 + 20}" y="{y0 + 53}" class="note" style="font-size:10.5px">proposer is cut: 75%×7/8 = 65.6% &lt; 2/3</text>')

    # Bottom takeaway strip
    out.append('<rect x="24" y="412" width="1072" height="46" rx="6" fill="#f1f5f9" stroke="#cbd5e1"/>')
    out.append('<text x="38" y="431" class="note"><tspan font-weight="700" fill="#0f172a">Key Takeaways (30 runs):</tspan>  (1) Zero conflicting stable roots or finalizations across all 30 runs; heads reconverge in ≤ 1 slot after GST.</text>')
    out.append('<text x="38" y="448" class="note">(2) Losing branch orphans safe-confirmed blocks linearly in D (~D/2 for 50/50, ~D/4 for 75/25 minority; 0 for 75% majority) because G0-clear cannot veto an unseen branch.</text>')

    out.append("</svg>")
    return "\n".join(out)


def build_fig2_beliefs_svg(split50, split75):
    """Figure 2: Side-by-side comparison of 50/50 Split vs 75/25 Split node beliefs across slots 1..64."""
    W, H = 1160, 795
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" style="background:#ffffff">',
        SVG_STYLE,
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>',
        '<text x="24" y="28" class="title">What Each Partition Side Believed, Slot by Slot (Cut: Slots 24–39, GST Heal at Slot 40)</text>',
        '<text x="24" y="46" class="subtitle">Comparison of 50/50 Split (left, no 2/3 quorum during cut) vs. 75/25 Split (right, 75% majority keeps advancing TSQ &amp; finality; 25% minority recovers via G1).</text>',
    ]

    # Top Legend
    out.append('<g transform="translate(24, 58)">')
    out.append('<line x1="0" y1="6" x2="22" y2="6" stroke="#2563eb" stroke-width="2.6"/><text x="27" y="10" class="axis-label" style="fill:#1e40af;font-weight:600">Side A (solid blue)</text>')
    out.append('<line x1="152" y1="6" x2="174" y2="6" stroke="#d97706" stroke-width="2.6"/><text x="179" y="10" class="axis-label" style="fill:#b45309;font-weight:600">Side B (solid orange)</text>')
    out.append('<line x1="318" y1="6" x2="340" y2="6" stroke="#0891b2" stroke-width="2" stroke-dasharray="4,3"/><text x="345" y="10" class="axis-label" style="fill:#0e7490;font-weight:600">Justified A / B (dashed)</text>')
    out.append('<circle cx="502" cy="6" r="4.5" fill="none" stroke="#dc2626" stroke-width="2"/><text x="512" y="10" class="axis-label" style="fill:#b91c1c;font-weight:600">Orphaned block</text>')
    out.append('<circle cx="622" cy="6" r="4.5" fill="#16a34a"/><text x="632" y="10" class="axis-label" style="fill:#15803d;font-weight:600">TSQ lock (&gt;0)</text>')
    out.append('<rect x="732" y="1.5" width="9" height="9" fill="#ffffff" stroke="#dc2626" stroke-width="2"/><text x="747" y="10" class="axis-label" style="fill:#b91c1c;font-weight:600">Simplex floor (0)</text>')
    out.append('<polygon points="866,0.5 872,6 866,11.5 860,6" fill="#9333ea"/><text x="877" y="10" class="axis-label" style="fill:#7e22ce;font-weight:600">G1 fallback (get_grade_1_root)</text>')
    out.append('</g>')

    scenarios = [
        ("50/50 Split — Side A: Nodes 0–3 (V0–31) vs. Side B: Nodes 4–7 (V32–63)", split50, 52),
        ("75/25 Split — Side A: Nodes 0–5 (V0–47) vs. Side B: Nodes 6–7 (V48–63)", split75, 616),
    ]

    row_defs = [
        ("1. Head Slot (get_head)", 0, 1, "head"),
        ("2. Safe-Confirmed Slot (get_safe_confirmed_head, G0-clear)", 2, 3, "safe"),
        ("3. Stable Root Slot (freeze_stable_root: TSQ lock vs Simplex floor vs G1)", 4, 5, "stable"),
        ("4. Simplex Finality: Finalized (solid blue/orange) & Justified (dashed cyan/purple) + Height h", 6, None, "fin"),
    ]

    pw, ph = 500, 122
    for col_title, run, x0 in scenarios:
        out.append(f'<text x="{x0}" y="94" class="panel-title" style="font-size:14px">{esc(col_title)}</text>')
        max_slot = len(run["states"])
        cutA, cutB = run["cfg"]["start"], run["cfg"]["start"] + run["cfg"]["slots_down"]

        # Determine final chain roots
        last_root = run["states"][-1][1][0][1]
        final_chain = set()
        r = last_root
        while r and r in run["blocks"]:
            final_chain.add(r)
            r = run["blocks"][r][1]

        def X(s):
            return x0 + (s - 1) / (max_slot - 1) * pw

        for r_idx, (r_label, si, ri, kind) in enumerate(row_defs):
            y0 = 114 + r_idx * (ph + 36)
            out.append(f'<text x="{x0}" y="{y0 - 6}" class="axis-label" style="fill:#0f172a;font-weight:600">{esc(r_label)}</text>')
            out.append(f'<rect x="{x0}" y="{y0}" width="{pw}" height="{ph}" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>')
            # Shaded partition cut window
            out.append(f'<rect x="{X(cutA):.1f}" y="{y0}" width="{X(cutB) - X(cutA):.1f}" height="{ph}" class="cut-tint"/>')
            out.append(f'<line x1="{X(cutA):.1f}" y1="{y0}" x2="{X(cutA):.1f}" y2="{y0 + ph}" class="cut-line"/>')
            out.append(f'<line x1="{X(cutB):.1f}" y1="{y0}" x2="{X(cutB):.1f}" y2="{y0 + ph}" class="heal-line"/>')

            def Y(v):
                return y0 + ph - 10 - (v / max_slot) * (ph - 20)

            # Gridlines
            for v in (0, 16, 32, 48, 64):
                yy = Y(v)
                out.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0 + pw}" y2="{yy:.1f}" class="grid"/>')
                out.append(f'<text x="{x0 - 6}" y="{yy + 4:.1f}" text-anchor="end" class="tick mono">{v}</text>')
            for s in range(8, max_slot + 1, 8):
                xx = X(s)
                out.append(f'<line x1="{xx:.1f}" y1="{y0}" x2="{xx:.1f}" y2="{y0 + ph}" class="grid"/>')
                if r_idx == 3:
                    out.append(f'<text x="{xx:.1f}" y="{y0 + ph + 16}" text-anchor="middle" class="tick mono">s{s} (r{s//8})</text>')

            # Representative node for Side A (node 0) and Side B (last node)
            idxA, idxB = 0, run["cfg"]["nodes"] - 1
            ptsA, ptsB = [], []
            for slot, ns in run["states"]:
                vA, vB = ns[idxA][si], ns[idxB][si]
                if vA is not None:
                    ptsA.append((slot, X(slot), Y(vA), vA, ns[idxA]))
                if vB is not None:
                    ptsB.append((slot, X(slot), Y(vB), vB, ns[idxB]))

            def step_coords(xy_list, dy=0.0):
                """Hold y_{i-1} horizontally from x_{i-1} to x_i, then jump vertically at x_i to y_i."""
                if not xy_list:
                    return []
                res = [(xy_list[0][0], xy_list[0][1] + dy)]
                for i in range(1, len(xy_list)):
                    px, py = xy_list[i][0], xy_list[i][1] + dy
                    prev_y = xy_list[i - 1][1] + dy
                    res.append((px, prev_y))
                    res.append((px, py))
                return res

            stepA_raw = step_coords([(px, py) for _, px, py, _, _ in ptsA], 0.0)
            stepB_raw = step_coords([(px, py) for _, px, py, _, _ in ptsB], 0.0)
            # Slight +/- 1.0px vertical twin-track offset so both solid blue and solid orange show when equal
            stepA = step_coords([(px, py) for _, px, py, _, _ in ptsA], -1.0)
            stepB = step_coords([(px, py) for _, px, py, _, _ in ptsB], +1.0)

            # Shaded divergence polygon between Side A and Side B step functions
            if len(stepA_raw) == len(stepB_raw) and stepA_raw:
                poly = [f"{px:.1f},{py:.1f}" for px, py in stepA_raw] + [
                    f"{px:.1f},{py:.1f}" for px, py in reversed(stepB_raw)
                ]
                out.append(f'<polygon points="{" ".join(poly)}" fill="#f59e0b" fill-opacity="0.16"/>')

            if kind == "fin":
                # Plot Justified slot (index 7) as clearly distinct dashed step lines (cyan for A, purple for B)
                jA = step_coords([(X(s), Y(ns[idxA][7])) for s, ns in run["states"]], -0.8)
                jB = step_coords([(X(s), Y(ns[idxB][7])) for s, ns in run["states"]], +0.8)
                out.append(f'<polyline points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in jB)}" fill="none" stroke="#9333ea" stroke-width="1.8" stroke-dasharray="4,3"/>')
                out.append(f'<polyline points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in jA)}" fill="none" stroke="#0891b2" stroke-width="1.8" stroke-dasharray="5,3"/>')

            # Draw Side B (solid orange) and Side A (solid blue — never dashed!)
            if stepB:
                out.append(f'<polyline points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in stepB)}" fill="none" stroke="#d97706" stroke-width="2.2"/>')
            if stepA:
                out.append(f'<polyline points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in stepA)}" fill="none" stroke="#2563eb" stroke-width="2.2"/>')

            # Orphaned block rings
            if ri is not None:
                for pts, col in ((ptsA, "#2563eb"), (ptsB, "#d97706")):
                    for slot, px, py, val, nstate in pts:
                        root = nstate[ri]
                        if root and root in run["blocks"] and root not in final_chain:
                            out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.0" fill="#ffffff" stroke="#dc2626" stroke-width="1.8"/>')

            # Special markers for Stable root (kind == "stable")
            if kind == "stable":
                for slot in range(8, max_slot + 1, 8):
                    ns = run["states"][slot - 1][1]
                    for side_idx, (n_i, col) in enumerate(((idxA, "#2563eb"), (idxB, "#d97706"))):
                        st_slot = ns[n_i][4]
                        st_src = ns[n_i][9]
                        if st_slot is None:
                            continue
                        px, py = X(slot), Y(st_slot)
                        # If both sides have identical (st_slot, st_src), only draw badge once
                        if side_idx == 1 and st_slot == ns[idxA][4] and st_src == ns[idxA][9]:
                            continue
                        if st_src == "G1":
                            out.append(f'<polygon points="{px:.1f},{py - 6:.1f} {px + 6:.1f},{py:.1f} {px:.1f},{py + 6:.1f} {px - 6:.1f},{py:.1f}" fill="#9333ea" stroke="#ffffff" stroke-width="1"/>')
                            out.append(f'<text x="{px + 6:.1f}" y="{py + 13:.1f}" class="badge mono" style="fill:#7e22ce">{st_slot} (G1)</text>')
                        elif st_src == "FLOOR":
                            out.append(f'<rect x="{px - 4.5:.1f}" y="{py - 4.5:.1f}" width="9" height="9" fill="#ffffff" stroke="#dc2626" stroke-width="2"/>')
                            if slot == 32:
                                out.append(f'<text x="{px + 6:.1f}" y="{py - 6:.1f}" class="badge mono" style="fill:#b91c1c">0 (Floor)</text>')
                        elif st_src == "TSQ":
                            out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="#16a34a" stroke="#ffffff" stroke-width="1"/>')
                            if slot in (16, 24, 32, 40, 48, 56):
                                dy = -7 if side_idx == 0 else 13
                                out.append(f'<text x="{px + 3:.1f}" y="{py + dy:.1f}" class="badge mono" style="fill:#15803d">{st_slot}</text>')

            # Special markers for Finality & Heights (kind == "fin")
            if kind == "fin":
                for slot in (8, 16, 24, 32, 40, 48, 56):
                    ns = run["states"][slot - 1][1]
                    hA, hB = ns[idxA][8], ns[idxB][8]
                    px = X(slot)
                    lbl = f"h{hA}" if hA == hB else f"h{hA}/h{hB}"
                    out.append(f'<text x="{px:.1f}" y="{y0 + 13:.1f}" text-anchor="middle" class="badge mono" style="fill:#334155">{lbl}</text>')
                if "50/50" in col_title:
                    out.append(f'<text x="{X(40) + 4:.1f}" y="{Y(26):.1f}" class="note" style="fill:#b91c1c;font-weight:600">s16 finalized @ s56 (+16s delay)</text>')
                else:
                    out.append(f'<text x="{X(40) + 4:.1f}" y="{Y(16) + 13:.1f}" class="note" style="fill:#15803d;font-weight:600">s16 finalized @ s40 (0 delay)</text>')

            if r_idx == 1:
                # Callout for G0-clear dip at slot 40
                if "50/50" in col_title:
                    out.append(f'<text x="{X(40) + 5:.1f}" y="{Y(23) + 12:.1f}" class="badge" style="fill:#b91c1c">← G0 veto @ GST drops safe to s23</text>')
                else:
                    out.append(f'<text x="{X(40) + 5:.1f}" y="{Y(23) + 12:.1f}" class="badge" style="fill:#b45309">← Side B dips to s23, recovers @ s41</text>')

    # Bottom narrative callout bar
    out.append('<rect x="24" y="736" width="1112" height="46" rx="6" fill="#f1f5f9" stroke="#cbd5e1"/>')
    out.append('<text x="38" y="755" class="note"><tspan font-weight="700" fill="#0f172a">Why 50/50 and 75/25 behave differently:</tspan>  In <tspan font-weight="600">50/50</tspan>, neither side reaches the ⌈2W/3⌉ TSQ quorum at s32 (r4), so stable_root regresses from s18 to the Simplex floor (s0).</text>')
    out.append('<text x="38" y="772" class="note">In <tspan font-weight="600">75/25</tspan>, Side A (75%) locks s24 (TSQ) and justifies s16 at r4, then finalizes s16 on time at s40 (r5). At GST (40.2s), Side B (25%) adopts s16 as its new floor and jumps to s32 via <tspan font-weight="600" fill="#7e22ce">G1 fallback</tspan>.</text>')
    out.append("</svg>")
    return "\n".join(out)


def build_fig3_trees_svg(split50, split75):
    """Figure 3: Stacked Block Trees for 50/50 Split and 75/25 Split showing orphaned safe-confirmed blocks."""
    W, H = 1160, 420
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" style="background:#ffffff">',
        SVG_STYLE,
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>',
        '<text x="24" y="28" class="title">Block Tree &amp; Confirmation Reversals Across the Partition (Slots 0–64)</text>',
        '<text x="24" y="46" class="subtitle">Top row in each panel is the canonical chain all nodes converge on after GST (slot 40); lower row is the branch abandoned at heal. Red rings mark orphaned safe-confirmed blocks.</text>',
        '<g transform="translate(24, 58)">',
        '<circle cx="6" cy="6" r="5.5" fill="#2563eb"/><text x="18" y="10" class="axis-label" style="fill:#0f172a;font-weight:600">Proposed by Side A</text>',
        '<circle cx="156" cy="6" r="5.5" fill="#d97706"/><text x="168" y="10" class="axis-label" style="fill:#0f172a;font-weight:600">Proposed by Side B</text>',
        '<circle cx="310" cy="6" r="7.5" fill="none" stroke="#dc2626" stroke-width="2.2"/><text x="324" y="10" class="axis-label" style="fill:#b91c1c;font-weight:600">Reported as safe-confirmed (G0-clear), later orphaned</text>',
        '<rect x="655" y="0.5" width="11" height="11" fill="none" stroke="#0f172a" stroke-width="2"/><text x="672" y="10" class="axis-label" style="fill:#0f172a;font-weight:600">Finalized checkpoint</text>',
        '</g>',
    ]

    panels = [
        ("A. 50/50 Split (D = 16 slots, cut [24, 40)): Side A's 8-block branch is orphaned at slot 41 (7 blocks were safe-confirmed)", split50, 96),
        ("B. 75/25 Split (D = 16 slots, cut [24, 40)): Side B's (25% minority) 3-block branch is orphaned at slot 40 (all 3 were safe-confirmed)", split75, 256),
    ]

    left_x, right_x = 112, W - 36
    for title, run, y0 in panels:
        out.append(f'<text x="24" y="{y0 - 8}" class="panel-title">{esc(title)}</text>')
        ph = 122
        out.append(f'<rect x="24" y="{y0}" width="{W - 48}" height="{ph}" rx="6" fill="#f8fafc" stroke="#cbd5e1"/>')

        blocks = [
            {"root": root, "slot": b[0], "parent": b[1], "src": b[2]}
            for root, b in run["blocks"].items()
        ]
        blocks.sort(key=lambda x: x["slot"])
        max_slot = max(b["slot"] for b in blocks)
        cutA, cutB = run["cfg"]["start"], run["cfg"]["start"] + run["cfg"]["slots_down"]

        last_root = run["states"][-1][1][0][1]
        final_chain = set()
        r = last_root
        while r and r in run["blocks"]:
            final_chain.add(r)
            r = run["blocks"][r][1]

        ever_safe = set()
        for _, ns in run["states"]:
            for n in ns:
                ever_safe.add(n[3])

        fin_slots = {0, run["states"][-1][1][0][6]}
        if fin_slots == {0, 32}:
            fin_slots.add(16)

        def TX(s):
            return left_x + s / max_slot * (right_x - left_x)

        def TY(row_idx):
            return y0 + 40 if row_idx == 0 else y0 + 88

        # Cut tint
        out.append(f'<rect x="{TX(cutA):.1f}" y="{y0 + 1}" width="{TX(cutB) - TX(cutA):.1f}" height="{ph - 2}" class="cut-tint"/>')
        out.append(f'<line x1="{TX(cutA):.1f}" y1="{y0}" x2="{TX(cutA):.1f}" y2="{y0 + ph}" class="cut-line"/>')
        out.append(f'<line x1="{TX(cutB):.1f}" y1="{y0}" x2="{TX(cutB):.1f}" y2="{y0 + ph}" class="heal-line"/>')

        for s in range(0, max_slot + 1, 8):
            xx = TX(s)
            out.append(f'<line x1="{xx:.1f}" y1="{y0 + 16}" x2="{xx:.1f}" y2="{y0 + ph - 6}" class="grid"/>')
            out.append(f'<text x="{xx:.1f}" y="{y0 + 13}" text-anchor="middle" class="tick mono">s{s}</text>')

        out.append(f'<text x="34" y="{TY(0) + 4}" class="axis-label" style="font-weight:600;fill:#0f172a">Final chain</text>')
        out.append(f'<text x="34" y="{TY(1) + 4}" class="axis-label" style="font-weight:600;fill:#b91c1c">Orphaned</text>')

        by_root = {b["root"]: b for b in blocks}
        row_of = {b["root"]: (0 if b["root"] in final_chain else 1) for b in blocks}

        # Genesis node at slot 0
        out.append(f'<circle cx="{TX(0):.1f}" cy="{TY(0):.1f}" r="4.5" fill="#475569"/>')
        out.append(f'<rect x="{TX(0) - 6.5:.1f}" y="{TY(0) - 6.5:.1f}" width="13" height="13" fill="none" stroke="#0f172a" stroke-width="1.8"/>')

        # Edges
        for b in blocks:
            p = by_root.get(b["parent"])
            px = TX(p["slot"]) if p else TX(0)
            py = TY(row_of[p["root"]]) if p else TY(0)
            bx, by = TX(b["slot"]), TY(row_of[b["root"]])
            col = "#94a3b8" if row_of[b["root"]] == 0 else "#ef4444"
            out.append(f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{bx:.1f}" y2="{by:.1f}" stroke="{col}" stroke-width="1.5"/>')

        # Nodes
        for b in blocks:
            bx, by = TX(b["slot"]), TY(row_of[b["root"]])
            side_col = "#2563eb" if run["groupOf"][b["src"]] == 0 else "#d97706"
            out.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="4.8" fill="{side_col}" stroke="#ffffff" stroke-width="0.8"/>')
            if row_of[b["root"]] == 0 and b["slot"] in fin_slots:
                out.append(f'<rect x="{bx - 6.8:.1f}" y="{by - 6.8:.1f}" width="13.6" height="13.6" fill="none" stroke="#0f172a" stroke-width="2"/>')
            if row_of[b["root"]] == 1:
                if b["root"] in ever_safe:
                    out.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="7.5" fill="none" stroke="#dc2626" stroke-width="2"/>')
                out.append(f'<text x="{bx:.1f}" y="{by + 18:.1f}" text-anchor="middle" class="tick mono" style="fill:#991b1b;font-weight:600;font-size:10px">{b["slot"]}</text>')

    out.append("</svg>")
    return "\n".join(out)


def build_fig4_deadlines_svg(split75):
    """Figure 4: Clean 2-Lane Partition Timeline + Zoomed 2-Slot Deadline Anatomy around GST Heal (slots 39–40)."""
    W, H = 1160, 560
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" style="background:#ffffff">',
        SVG_STYLE,
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>',
        '<text x="24" y="28" class="title">Message Flow &amp; Sub-Slot Deadline Anatomy (75/25 Split, Cut: Slots 24–39, GST Heal at Slot 40)</text>',
        '<text x="24" y="46" class="subtitle">Replacing the 8-node all-to-all spiderweb with: (A) a 2-lane partition overview across slots 16–48, and (B) a zoomed 2-slot view of the 0%/25%/50%/75% deadlines at GST heal (slots 39–40).</text>',
    ]

    # Panel A: 2-Lane Macro Partition Timeline (Slots 16..48)
    x0, y0, pw, ph = 48, 82, 1080, 175
    out.append(f'<text x="24" y="{y0 - 10}" class="panel-title">A. Two-Lane Partition Overview (Slots 16–48): Block Proposals, Cut Barrier, and GST Flush</text>')
    out.append(f'<rect x="{x0}" y="{y0}" width="{pw}" height="{ph}" rx="6" fill="#f8fafc" stroke="#cbd5e1"/>')

    s_min, s_max = 16, 48
    cutA, cutB = 24, 40

    def MX(s):
        return x0 + 90 + (s - s_min) / (s_max - s_min) * (pw - 115)

    yA, yMid, yB = y0 + 46, y0 + 92, y0 + 138

    # Cut shaded region and barrier line
    out.append(f'<rect x="{MX(cutA):.1f}" y="{y0 + 1}" width="{MX(cutB) - MX(cutA):.1f}" height="{ph - 2}" class="cut-tint"/>')
    out.append(f'<line x1="{MX(cutA):.1f}" y1="{y0}" x2="{MX(cutA):.1f}" y2="{y0 + ph}" class="cut-line"/>')
    out.append(f'<line x1="{MX(cutB):.1f}" y1="{y0}" x2="{MX(cutB):.1f}" y2="{y0 + ph}" class="heal-line"/>')

    for s in range(s_min, s_max + 1):
        xx = MX(s)
        is_rb = s % 8 == 0
        cls = "grid-strong" if is_rb else "grid"
        out.append(f'<line x1="{xx:.1f}" y1="{y0 + 18}" x2="{xx:.1f}" y2="{y0 + ph - 8}" class="{cls}"/>')
        if is_rb or s % 2 == 0:
            lbl = f"r{s//8}·s{s}" if is_rb else f"{s}"
            weight = "700" if is_rb else "400"
            col = "#0f172a" if is_rb else "#64748b"
            out.append(f'<text x="{xx:.1f}" y="{y0 + 14}" text-anchor="middle" class="tick mono" style="font-weight:{weight};fill:{col}">{lbl}</text>')

    # Group tracks
    out.append(f'<line x1="{MX(s_min):.1f}" y1="{yA}" x2="{MX(s_max):.1f}" y2="{yA}" stroke="#2563eb" stroke-width="2.5"/>')
    out.append(f'<text x="{x0 + 10}" y="{yA - 6}" class="badge" style="fill:#1e40af">Side A (75%)</text>')
    out.append(f'<text x="{x0 + 10}" y="{yA + 10}" class="tick">nodes 0–5</text>')

    out.append(f'<line x1="{MX(s_min):.1f}" y1="{yB}" x2="{MX(s_max):.1f}" y2="{yB}" stroke="#d97706" stroke-width="2.5"/>')
    out.append(f'<text x="{x0 + 10}" y="{yB - 6}" class="badge" style="fill:#b45309">Side B (25%)</text>')
    out.append(f'<text x="{x0 + 10}" y="{yB + 10}" class="tick">nodes 6–7</text>')

    # Cut barrier line between tracks during [24, 40)
    out.append(f'<line x1="{MX(cutA):.1f}" y1="{yMid}" x2="{MX(cutB):.1f}" y2="{yMid}" stroke="#dc2626" stroke-width="2.2" stroke-dasharray="6,4"/>')

    # Draw block proposals & cross-side deliveries
    blocks_by_slot = {b[0]: (root, b[2]) for root, b in split75["blocks"].items() if s_min <= b[0] <= s_max}
    for s in range(s_min, s_max + 1):
        if s not in blocks_by_slot:
            continue
        _, src = blocks_by_slot[s]
        grp = split75["groupOf"][src]
        xx = MX(s)
        sy = yA if grp == 0 else yB
        dy = yB if grp == 0 else yA
        col = "#2563eb" if grp == 0 else "#d97706"
        in_cut = cutA <= s < cutB
        if not in_cut:
            # Delivered across groups in ~200ms
            out.append(f'<line x1="{xx:.1f}" y1="{sy:.1f}" x2="{xx + 2.5:.1f}" y2="{dy:.1f}" stroke="{col}" stroke-width="1.5" stroke-opacity="0.65"/>')
            out.append(f'<circle cx="{xx + 2.5:.1f}" cy="{dy:.1f}" r="2.5" fill="{col}"/>')
        else:
            # Blocked at cut barrier
            by_stop = yMid - 5 if grp == 0 else yMid + 5
            out.append(f'<line x1="{xx:.1f}" y1="{sy:.1f}" x2="{xx:.1f}" y2="{by_stop:.1f}" stroke="#dc2626" stroke-width="1.3" stroke-dasharray="2,2"/>')
        out.append(f'<circle cx="{xx:.1f}" cy="{sy:.1f}" r="4.8" fill="{col}" stroke="#ffffff" stroke-width="1"/>')

    # Cut barrier summary pill
    mid_cut_x = (MX(cutA) + MX(cutB)) / 2
    out.append(f'<rect x="{mid_cut_x - 165:.1f}" y="{yMid - 12:.1f}" width="330" height="24" rx="12" fill="#fef2f2" stroke="#dc2626" stroke-width="1.2"/>')
    out.append(f'<text x="{mid_cut_x:.1f}" y="{yMid + 4:.1f}" text-anchor="middle" class="badge" style="fill:#991b1b">CUT: 44 blocks, 332 finality &amp; 384 Goldfish votes held</text>')

    # GST Flush bundle at slot 40.033 (40.2s)
    flush_x = MX(40.15)
    out.append(f'<line x1="{flush_x:.1f}" y1="{yA + 6}" x2="{flush_x:.1f}" y2="{yB - 6}" stroke="#0d9488" stroke-width="3.5"/>')
    out.append(f'<polygon points="{flush_x - 5:.1f},{yB - 10} {flush_x + 5:.1f},{yB - 10} {flush_x:.1f},{yB - 3}" fill="#0d9488"/>')
    out.append(f'<polygon points="{flush_x - 5:.1f},{yA + 10} {flush_x + 5:.1f},{yA + 10} {flush_x:.1f},{yA + 3}" fill="#0d9488"/>')
    out.append(f'<rect x="{flush_x + 8:.1f}" y="{yMid - 13:.1f}" width="236" height="26" rx="5" fill="#f0fdfa" stroke="#0d9488" stroke-width="1.2"/>')
    out.append(f'<text x="{flush_x + 15:.1f}" y="{yMid + 4:.1f}" class="badge" style="fill:#0f766e">← GST Flush @ 40.2s (all held msgs land)</text>')

    # Panel B: Zoomed 2-Slot Deadline Anatomy (Slots 39 and 40: 234.0s to 246.0s)
    zy0, zph = 296, 238
    out.append(f'<text x="24" y="{zy0 - 10}" class="panel-title">B. Zoomed 2-Slot Sub-Slot Deadline Anatomy Around GST Heal: Slot 39 (Last Slot of Round 4) → Slot 40 (Start of Round 5)</text>')
    out.append(f'<rect x="{x0}" y="{zy0}" width="{pw}" height="{zph}" rx="6" fill="#f8fafc" stroke="#cbd5e1"/>')

    t_start, t_end = 39 * 6000, 41 * 6000  # ms

    def ZX(t_ms):
        return x0 + 90 + (t_ms - t_start) / (t_end - t_start) * (pw - 115)

    zyA, zyMid, zyB = zy0 + 74, zy0 + 134, zy0 + 194

    # Shaded cut in slot 39 (234s..240s)
    out.append(f'<rect x="{ZX(39 * 6000):.1f}" y="{zy0 + 1}" width="{ZX(40 * 6000) - ZX(39 * 6000):.1f}" height="{zph - 2}" class="cut-tint"/>')

    # Draw deadline verticals for slot 39 and slot 40 (concise sub-labels so 115px columns never overlap)
    deadlines_spec = [
        (39 * 6000 + 0, "s39 · 0% (0.0s)", "on_tick + propose", "#475569", True),
        (39 * 6000 + 1500, "25% (1.5s)", "avail + fin votes", "#64748b", False),
        (39 * 6000 + 3000, "50% (3.0s)", "avail_votes freeze", "#64748b", False),
        (39 * 6000 + 4500, "75% (4.5s)", "freeze_tsq_view (F)", "#b45309", False),
        (40 * 6000 + 0, "r5·s40 · 0% (0s)", "tsq_selection + block", "#0f172a", True),
        (40 * 6000 + 200, "+0.2s (GST)", "held msgs arrive", "#0d9488", False),
        (40 * 6000 + 1500, "25% (1.5s)", "stable_root + votes", "#7e22ce", False),
        (40 * 6000 + 3000, "50% (3.0s)", "G0 confirm check", "#dc2626", False),
        (40 * 6000 + 4500, "75% (4.5s)", "view freeze", "#64748b", False),
    ]

    for t_ms, top_lbl, sub_lbl, col, is_slot in deadlines_spec:
        xx = ZX(t_ms)
        dash = "" if is_slot else 'stroke-dasharray="3,3"'
        sw = "1.8" if is_slot or t_ms in (39 * 6000 + 4500, 40 * 6000 + 200, 40 * 6000 + 1500) else "1"
        out.append(f'<line x1="{xx:.1f}" y1="{zy0 + 34}" x2="{xx:.1f}" y2="{zy0 + zph - 12}" stroke="{col}" stroke-width="{sw}" {dash}/>')
        if t_ms == 40 * 6000 + 200:
            # Place GST label in the middle band
            out.append(f'<rect x="{xx + 5:.1f}" y="{zyMid - 11:.1f}" width="185" height="22" rx="4" fill="#f0fdfa" stroke="#0d9488"/>')
            out.append(f'<text x="{xx + 11:.1f}" y="{zyMid + 4:.1f}" class="badge mono" style="fill:{col}">← +0.2s GST: held msgs land</text>')
        else:
            out.append(f'<text x="{xx:.1f}" y="{zy0 + 16}" text-anchor="middle" class="badge mono" style="fill:{col}">{esc(top_lbl)}</text>')
            out.append(f'<text x="{xx:.1f}" y="{zy0 + 29}" text-anchor="middle" class="tick" style="fill:{col};font-size:10px">{esc(sub_lbl)}</text>')

    # Group tracks in Panel B
    out.append(f'<line x1="{ZX(t_start):.1f}" y1="{zyA}" x2="{ZX(t_end):.1f}" y2="{zyA}" stroke="#2563eb" stroke-width="2.5"/>')
    out.append(f'<text x="{x0 + 10}" y="{zyA - 6}" class="badge" style="fill:#1e40af">Side A (75%)</text>')
    out.append(f'<text x="{x0 + 10}" y="{zyA + 10}" class="tick">majority</text>')

    out.append(f'<line x1="{ZX(t_start):.1f}" y1="{zyB}" x2="{ZX(t_end):.1f}" y2="{zyB}" stroke="#d97706" stroke-width="2.5"/>')
    out.append(f'<text x="{x0 + 10}" y="{zyB - 6}" class="badge" style="fill:#b45309">Side B (25%)</text>')
    out.append(f'<text x="{x0 + 10}" y="{zyB + 10}" class="tick">minority</text>')

    # Cut barrier in slot 39
    out.append(f'<line x1="{ZX(39 * 6000):.1f}" y1="{zyMid}" x2="{ZX(40 * 6000):.1f}" y2="{zyMid}" stroke="#dc2626" stroke-width="2" stroke-dasharray="5,4"/>')

    # Events in Slot 39
    # Block 39 proposed by Side A at 0.0s, held from Side B until 40.2s
    out.append(f'<circle cx="{ZX(39 * 6000):.1f}" cy="{zyA}" r="5.5" fill="#2563eb" stroke="#ffffff" stroke-width="1.2"/>')
    out.append(f'<text x="{ZX(39 * 6000) + 8:.1f}" y="{zyA - 8}" class="badge" style="fill:#1e40af">Block s39 proposed</text>')
    out.append(f'<line x1="{ZX(39 * 6000):.1f}" y1="{zyA}" x2="{ZX(40 * 6000 + 200):.1f}" y2="{zyB}" stroke="#dc2626" stroke-width="1.8" stroke-dasharray="5,3"/>')

    # Attestations at s39 + 1.5s
    out.append(f'<circle cx="{ZX(39 * 6000 + 1500):.1f}" cy="{zyA}" r="4" fill="#2563eb"/>')
    out.append(f'<circle cx="{ZX(39 * 6000 + 1500):.1f}" cy="{zyB}" r="4" fill="#d97706"/>')
    out.append(f'<line x1="{ZX(39 * 6000 + 1500):.1f}" y1="{zyA}" x2="{ZX(40 * 6000 + 200):.1f}" y2="{zyB}" stroke="#dc2626" stroke-width="1.4" stroke-dasharray="4,3"/>')
    out.append(f'<line x1="{ZX(39 * 6000 + 1500):.1f}" y1="{zyB}" x2="{ZX(40 * 6000 + 200):.1f}" y2="{zyA}" stroke="#dc2626" stroke-width="1.4" stroke-dasharray="4,3"/>')

    # freeze_tsq_view at s39 + 4.5s (BEFORE heal!)
    fx39 = ZX(39 * 6000 + 4500)
    out.append(f'<rect x="{fx39 - 78:.1f}" y="{zyA - 28}" width="156" height="19" rx="4" fill="#eff6ff" stroke="#2563eb"/>')
    out.append(f'<text x="{fx39:.1f}" y="{zyA - 15}" text-anchor="middle" class="badge" style="fill:#1e40af">A freezes F (75% weight ≥ 2/3)</text>')
    out.append(f'<rect x="{fx39 - 82:.1f}" y="{zyB + 10}" width="164" height="19" rx="4" fill="#fffbeb" stroke="#d97706"/>')
    out.append(f'<text x="{fx39:.1f}" y="{zyB + 23}" text-anchor="middle" class="badge" style="fill:#b45309">B freezes F (only 25% &lt; 2/3!)</text>')

    # Slot 40 @ 0.0s: freeze_tsq_selection + Block 40 proposed by Side A (delivers at 40.2s)
    out.append(f'<circle cx="{ZX(40 * 6000):.1f}" cy="{zyA}" r="5.5" fill="#2563eb" stroke="#ffffff" stroke-width="1.2"/>')
    out.append(f'<line x1="{ZX(40 * 6000):.1f}" y1="{zyA}" x2="{ZX(40 * 6000 + 220):.1f}" y2="{zyB}" stroke="#2563eb" stroke-width="2"/>')

    # GST Flush at 40.2s
    gx = ZX(40 * 6000 + 200)
    out.append(f'<circle cx="{gx:.1f}" cy="{zyB}" r="6" fill="#0d9488" stroke="#ffffff" stroke-width="1.5"/>')
    out.append(f'<rect x="{gx - 70:.1f}" y="{zyB - 32}" width="195" height="20" rx="4" fill="#f0fdfa" stroke="#0d9488"/>')
    out.append(f'<text x="{gx + 27:.1f}" y="{zyB - 18}" text-anchor="middle" class="badge" style="fill:#0f766e">B receives A\'s chain → fin=16!</text>')

    # Slot 40 @ 1.5s: freeze_stable_root
    sx40 = ZX(40 * 6000 + 1500)
    out.append(f'<rect x="{sx40 - 65:.1f}" y="{zyA - 28}" width="140" height="19" rx="4" fill="#f0fdf4" stroke="#16a34a"/>')
    out.append(f'<text x="{sx40 + 5:.1f}" y="{zyA - 15}" text-anchor="middle" class="badge" style="fill:#15803d">A locks s32 via TSQ</text>')
    out.append(f'<rect x="{sx40 - 65:.1f}" y="{zyB + 10}" width="185" height="19" rx="4" fill="#faf5ff" stroke="#9333ea"/>')
    out.append(f'<text x="{sx40 + 27:.1f}" y="{zyB + 23}" text-anchor="middle" class="badge" style="fill:#7e22ce">B: TSQ stale (0&lt;16) → s32 via G1!</text>')

    # Attestations at s40 + 1.5s (synchronous again)
    out.append(f'<line x1="{sx40:.1f}" y1="{zyA}" x2="{ZX(40 * 6000 + 1750):.1f}" y2="{zyB}" stroke="#2563eb" stroke-width="1.5"/>')
    out.append(f'<line x1="{sx40:.1f}" y1="{zyB}" x2="{ZX(40 * 6000 + 1750):.1f}" y2="{zyA}" stroke="#d97706" stroke-width="1.5"/>')

    out.append("</svg>")
    return "\n".join(out)


def main(out_html, specs, sweep_dir=None):
    data = {}
    for spec in specs:
        name, path = spec.split("=", 1)
        data[name] = compact(path)

    if sweep_dir is None:
        candidate = os.path.join(os.path.dirname(os.path.abspath(out_html)), "..", "seeded")
        if os.path.isdir(candidate):
            sweep_dir = candidate
    sweep_runs = load_sweep(sweep_dir) if sweep_dir else None

    payload = {
        "runs": data,
        "sweep": sweep_runs or [],
    }
    html = TEMPLATE.replace("/*DATA*/", "const DATA = " + json.dumps(payload, separators=(",", ":")) + ";")
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {out_html} ({len(html) / 1e6:.2f} MB)")

    # Also write static SVG / PDF / PNG figures into the same directory as out_html
    out_dir = os.path.dirname(os.path.abspath(out_html))
    base_runs = [r for r in (sweep_runs or []) if r.get("start", 24) == 24]
    if base_runs:
        p1 = os.path.join(out_dir, "fig1_sweep_summary.svg")
        save_svg_and_convert(p1, build_fig1_sweep_svg(base_runs))
        print(f"wrote static figure {p1} (+ .pdf, .png)")

    split50 = next((v for k, v in data.items() if "50" in k), None)
    split75 = next((v for k, v in data.items() if "75" in k), None)
    if split50 and split75:
        p2 = os.path.join(out_dir, "fig2_beliefs_comparison.svg")
        save_svg_and_convert(p2, build_fig2_beliefs_svg(split50, split75))
        print(f"wrote static figure {p2} (+ .pdf, .png)")

        p3 = os.path.join(out_dir, "fig3_block_trees.svg")
        save_svg_and_convert(p3, build_fig3_trees_svg(split50, split75))
        print(f"wrote static figure {p3} (+ .pdf, .png)")

    if split75:
        p4 = os.path.join(out_dir, "fig4_network_and_deadlines.svg")
        save_svg_and_convert(p4, build_fig4_deadlines_svg(split75))
        print(f"wrote static figure {p4} (+ .pdf, .png)")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Decoupled Consensus — Partition &amp; Healing Explorer</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root {
  --bg: #f4f6f9; --panel: #ffffff; --fg: #0f172a; --muted: #475569; --subtle: #64748b;
  --grid: #e2e8f0; --gridStrong: #cbd5e1;
  --a: #2563eb; --aSoft: rgba(37,99,235,0.12);
  --b: #d97706; --bSoft: rgba(217,119,6,0.14);
  --held: #dc2626; --tint: rgba(220,38,38,0.08);
  --heal: #0d9488; --tsq: #16a34a; --g1: #9333ea;
  --sans: "IBM Plex Sans", system-ui, -apple-system, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0b0f17; --panel: #131b26; --fg: #e2e8f0; --muted: #94a3b8; --subtle: #64748b;
  --grid: #1e293b; --gridStrong: #334155;
  --a: #60a5fa; --aSoft: rgba(96,165,250,0.15);
  --b: #fbbf24; --bSoft: rgba(251,191,36,0.15);
  --held: #f87171; --tint: rgba(248,113,113,0.10);
  --heal: #2dd4bf; --tsq: #4ade80; --g1: #c084fc;
  color-scheme: dark;
}}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font-family: var(--sans); font-size: 14.5px; line-height: 1.5; }
.wrap { max-width: 1200px; margin: 0 auto; padding: 24px 20px 64px; display: grid; gap: 20px; }
header { display: grid; gap: 6px; }
h1 { font-size: 24px; font-weight: 700; margin: 0; letter-spacing: -0.015em; }
h2 { font-size: 16.5px; font-weight: 600; margin: 0; }
p { margin: 0; }
.lead { color: var(--muted); max-width: 88ch; font-size: 14px; }
.topbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; }
.tabs { display: flex; flex-wrap: wrap; gap: 8px; }
.tabs button, .subtabs button {
  font: 600 13.5px var(--sans); padding: 7px 14px; border-radius: 6px;
  border: 1px solid var(--gridStrong); background: var(--panel); color: var(--fg); cursor: pointer;
}
.subtabs button { font-weight: 500; font-size: 12.5px; padding: 4px 10px; }
.tabs button[aria-pressed="true"], .subtabs button[aria-pressed="true"] {
  border-color: var(--a); background: var(--aSoft); color: var(--a); box-shadow: inset 0 0 0 1px var(--a);
}
.facts {
  display: flex; flex-wrap: wrap; gap: 8px 22px; font-family: var(--mono); font-size: 12.5px;
  color: var(--muted); background: var(--panel); border: 1px solid var(--grid); border-radius: 8px; padding: 10px 14px;
}
.facts b { color: var(--fg); font-weight: 600; }
.panel {
  background: var(--panel); border: 1px solid var(--grid); border-radius: 8px;
  padding: 18px; display: grid; gap: 12px; min-width: 0;
}
.panel-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 10px; }
.controls { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; font-size: 12.5px; color: var(--muted); }
.legend { display: flex; flex-wrap: wrap; gap: 8px 18px; font-size: 12.5px; color: var(--muted); align-items: center; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { display: inline-block; width: 18px; height: 3px; border-radius: 2px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }
.sq { display: inline-block; width: 9px; height: 9px; border: 2px solid var(--held); }
.dia { display: inline-block; width: 9px; height: 9px; background: var(--g1); transform: rotate(45deg); }
.note { font-size: 13px; color: var(--muted); max-width: 95ch; }
.callouts {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px;
  padding-top: 4px;
}
.callout {
  background: var(--bg); border-left: 3px solid var(--a); border-radius: 4px;
  padding: 8px 10px; font-size: 12.5px; color: var(--muted); line-height: 1.45;
}
.callout b { color: var(--fg); }
.callout > b:first-child { display: block; margin-bottom: 4px; font-size: 12.5px; }
canvas { display: block; width: 100%; height: auto; }
.side-pill {
  display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px;
  border-radius: 5px; font-weight: 500;
}
.side-a { background: var(--aSoft); color: var(--a); border: 1px solid var(--a); }
.side-b { background: var(--bSoft); color: var(--b); border: 1px solid var(--b); }
.winbar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px;
  background: var(--bg); border: 1px solid var(--grid); border-radius: 6px; padding: 7px 12px;
  font-size: 12.5px; color: var(--muted);
}
.winbar input[type="range"] { flex: 1; min-width: 160px; accent-color: var(--a); cursor: pointer; }
.winbar .win-readout { font-family: var(--mono); font-weight: 600; color: var(--fg); min-width: 185px; }
.step-btn {
  font: 600 12px var(--sans); padding: 4px 10px; border-radius: 5px;
  border: 1px solid var(--gridStrong); background: var(--panel); color: var(--fg); cursor: pointer;
}
.step-btn:hover { border-color: var(--a); color: var(--a); }
table.summary { width: 100%; border-collapse: collapse; font-size: 13px; font-family: var(--mono); }
table.summary th, table.summary td { padding: 7px 10px; border-bottom: 1px solid var(--grid); text-align: left; }
table.summary th { font-family: var(--sans); font-weight: 600; color: var(--muted); background: var(--bg); }
.tip {
  position: fixed; pointer-events: none; background: var(--panel); border: 1px solid var(--gridStrong);
  border-radius: 6px; padding: 7px 10px; font: 12px/1.45 var(--mono); color: var(--fg);
  box-shadow: 0 6px 18px rgba(0,0,0,.16); max-width: 340px; z-index: 50;
}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Decoupled Consensus — Partition &amp; Healing Explorer</h1>
    <p class="lead">Multi-node discrete-event runs of the official executable spec (<code>fradamt/consensus-specs@simplex-healing</code>, commit <code>5750e57</code>): Goldfish available chain + TSQ/G1 stabilization gadget + Simplex finality. Minimal preset: 6 s slots, 8-slot rounds, 64 equal-stake validators.</p>
  </header>

  <div class="topbar">
    <div class="tabs" id="tabs" role="group" aria-label="Scenario"></div>
  </div>

  <div id="singleView" style="display:grid;gap:20px">
    <div class="facts" id="facts"></div>

    <section class="panel">
      <div class="panel-head">
        <h2>1. What each partition side believed, slot by slot</h2>
        <div class="controls">
          <span>Window size:</span>
          <div class="subtabs" id="winSizeTabs">
            <button type="button" data-wsize="64" aria-pressed="true">All 64 slots</button>
            <button type="button" data-wsize="16">16 slots (2r)</button>
            <button type="button" data-wsize="8">8 slots (1r)</button>
            <button type="button" data-wsize="4">4 slots</button>
            <button type="button" data-wsize="1">1 slot</button>
          </div>
          <div class="subtabs" id="progMode">
            <button type="button" data-mode="slot" aria-pressed="true">Block slot</button>
            <button type="button" data-mode="lag">Lag (slot − pointer)</button>
          </div>
        </div>
      </div>

      <div class="winbar" id="winBar">
        <button type="button" class="step-btn" id="winPrevBtn">◀ Prev</button>
        <input type="range" id="winSlider" min="1" max="64" value="24" aria-label="Scroll slot window">
        <button type="button" class="step-btn" id="winNextBtn">Next ▶</button>
        <span class="win-readout" id="winReadout">Showing slots 1–64</span>
        <div class="subtabs" id="winJumpTabs">
          <button type="button" data-jump="22">Cut start (s24)</button>
          <button type="button" data-jump="30">Round 4 Floor/TSQ (s32)</button>
          <button type="button" data-jump="38">GST Heal &amp; G1 (s40)</button>
          <button type="button" data-jump="52">Finality (s56)</button>
        </div>
      </div>

      <p class="note">Step-function trajectory (vertical jumps at slot <i>x</i>) for <b>Side A</b> (solid blue) vs. <b>Side B</b> (solid orange) across all four protocol layers. Choose a smaller <b>Window size</b> (e.g. <b>16 / 8 / 4 / 1 slot</b>) and drag the slider (or scroll on the plot): <b>each subplot's Y-axis automatically scales to only the values inside the current slot window</b> so you can read individual block indices clearly.</p>
      <div class="legend">
        <span><i class="sw" style="background:var(--a);height:3.5px"></i>Side A (solid blue)</span>
        <span><i class="sw" style="background:var(--b);height:3.5px"></i>Side B (solid orange)</span>
        <span><i class="sw" style="background:#0891b2;border-top:2px dashed #0891b2;height:0"></i>Justified Side A (dashed cyan)</span>
        <span><i class="sw" style="background:#9333ea;border-top:2px dashed #9333ea;height:0"></i>Justified Side B (dashed purple)</span>
        <span><i class="dot" style="border:2px solid var(--held)"></i>Points at block later orphaned</span>
        <span><i class="dot" style="background:var(--tsq)"></i>TSQ lock (&gt;0)</span>
        <span><i class="sq"></i>Simplex floor (slot 0, no 2/3 quorum)</span>
        <span><i class="dia"></i>G1 fallback (get_grade_1_root)</span>
      </div>
      <canvas id="prog" style="cursor:grab"></canvas>
      <div class="callouts" id="callouts"></div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>2. Block tree &amp; confirmation reversals</h2>
      </div>
      <p class="note">Every block proposed across slots 1–64. The top row is the canonical chain all nodes converge on after GST; the lower row is the branch orphaned at heal. Red rings mark blocks that the losing side reported as <b>safe-confirmed (<code>get_safe_confirmed_head</code>, G0-clear)</b> before they were abandoned.</p>
      <div class="legend">
        <span><i class="dot" style="background:var(--a)"></i>Proposed by Side A</span>
        <span><i class="dot" style="background:var(--b)"></i>Proposed by Side B</span>
        <span><i class="dot" style="border:2px solid var(--held)"></i>Safe-confirmed (G0-clear), later orphaned</span>
        <span><i class="sq" style="border-color:var(--fg)"></i>Finalized checkpoint</span>
      </div>
      <canvas id="tree"></canvas>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>3. Single-slot sub-slot deadline &amp; message anatomy (1 slot at a time across all 8 nodes)</h2>
        <div class="controls">
          <span>Message display:</span>
          <div class="subtabs" id="msgModeTabs">
            <button type="button" data-msgmode="waves" aria-pressed="true">Clean Broadcast Waves (recommended)</button>
            <button type="button" data-msgmode="rays">All 56 Peer-to-Peer Rays</button>
          </div>
        </div>
      </div>

      <div class="winbar" id="slotBar">
        <button type="button" class="step-btn" id="sPrevBtn">◀ −1 Slot</button>
        <input type="range" id="sSlider" min="1" max="64" value="40" aria-label="Select single slot">
        <button type="button" class="step-btn" id="sNextBtn">+1 Slot ▶</button>
        <span class="win-readout" id="sReadout">Slot 40 / 64</span>
        <div class="subtabs" id="zoomTabs">
          <button type="button" data-slot="23">s23 (Pre-cut · End r2)</button>
          <button type="button" data-slot="24">s24 (Cut starts · r3)</button>
          <button type="button" data-slot="31">s31 (End r3)</button>
          <button type="button" data-slot="32">s32 (r4 · Floor vs TSQ)</button>
          <button type="button" data-slot="39">s39 (End r4 · Freeze votes)</button>
          <button type="button" data-slot="40" aria-pressed="true">s40 (GST Heal &amp; G1)</button>
          <button type="button" data-slot="41">s41 (Reorg)</button>
          <button type="button" data-slot="56">s56 (Finality)</button>
        </div>
      </div>

      <p class="note">Inspects a <b>single 6.0-second slot</b> across all 8 validator nodes (<code>Node 0</code> … <code>Node 7</code>) and its four internal protocol deadlines: <b>0% (+0.0s)</b> Block Proposal, <b>25% (+1.5s)</b> Attestation Deadline (every node broadcasts <b>both</b> its Goldfish availability vote and its Simplex finality vote; on round-start slots it first locks its <b>Stable Root</b>), <b>50% (+3.0s)</b> Confirmation Cutoff (<code>freeze_available_votes</code>: nodes freeze availability votes received by +3.0s and update <b>Safe-Confirmed</b> &amp; <b>Head</b>), and <b>75% (+4.5s)</b> View Freeze Cutoff (<code>accept_tsq_packets</code> / <code>freeze_tsq_view</code>). <i>Tip: click any slot on Plot 1 or Plot 2 above, or use the slider / Left &amp; Right arrow keys.</i></p>

      <div class="legend" style="background:var(--bg);padding:8px 12px;border-radius:6px;border:1px solid var(--grid)">
        <span><i class="dot" style="background:var(--a)"></i><b>0% (+0.0s) Blue/Orange dot &amp; rays:</b> Slot leader proposes block &amp; broadcasts to peers</span>
        <span><i class="dot" style="background:var(--tsq)"></i><i class="dot" style="background:var(--g1);margin-left:-3px"></i><b>25% (+1.5s) Green + Purple dots &amp; waves:</b> Every node broadcasts <b>Simplex finality vote</b> (green) + <b>Goldfish availability vote</b> (purple) (+ locks <b>Stable Root</b> on round start)</span>
        <span><i class="dot" style="border:2px solid var(--g1);background:var(--panel)"></i><b>50% (+3.0s) Purple ring:</b> Confirmation cutoff (<code>freeze_available_votes</code>) — nodes freeze availability votes received by +3.0s &amp; update <b>Safe-Confirmed / Head</b></span>
        <span><i class="sq" style="background:var(--fg);border-color:var(--fg)"></i><b>75% (+4.5s) Black square:</b> View freeze cutoff (on the 8th slot of a round, freezes the <b>Round Vote Snapshot</b> for the next round's TSQ)</span>
        <span><i class="sw" style="background:var(--held);border-top:2px dashed var(--held);height:0"></i><b>Red dashed:</b> Blocked by partition cut (held until s40)</span>
        <span><i class="sw" style="background:var(--heal);height:3.5px"></i><b>Teal (+0.2s on s40):</b> GST Heal Flush (held messages from s24–s39 arrive)</span>
      </div>

      <canvas id="net"></canvas>
      <div class="callouts" id="slotStepCards"></div>
      <div id="slotStateTable"></div>
    </section>
    <section class="panel" id="settlePanel" hidden>
      <h2>Height settlements at each round boundary (majority chain)</h2>
      <p class="note">Every round boundary settles one height outcome from the votes <b>already on chain</b>. Bars: target (justify) votes and finality-piggyback votes counted by the spec state at that moment; dashed line: the 2/3 quorum. A red marker under the axis means the round's first slot had no block on the majority chain, so the last slot's votes could not be included before the settlement. Finality piggybacks accumulate across rounds (extended window); target votes do not.</p>
      <div class="legend">
        <span><i class="sw" style="background:var(--a)"></i>target votes on chain</span>
        <span><i class="sw" style="background:var(--tsq)"></i>finality votes on chain</span>
        <span><i class="sw" style="background:var(--held)"></i>round-start block missing</span>
        <span>J = height justified · F = checkpoint finalized · – = no progress</span>
      </div>
      <canvas id="settleCanvas"></canvas>
    </section>
  </div>

  <div id="sweepView" style="display:none;gap:20px">
    <section class="panel">
      <h2>30-Run Seeded Partition Sweep (16 Nodes, 64 Validators, 5 Seeds × 6 Settings)</h2>
      <p class="note">Partition starts at slot 24 (round 3) for duration <b>D ∈ {8, 16, 32} slots</b> (1, 2, 4 rounds), then heals (GST). Each seed varies genesis RANDAO (committees &amp; proposers), validator-to-node assignment, and per-message latency (200 ms + U[0, 100] ms). Dots show individual seeds; vertical bars show [min–max]; lines connect seed means.</p>
      <div class="legend">
        <span><i class="sw" style="background:var(--held)"></i><b>50/50 split</b> (8 vs 8 nodes — no 2/3 quorum during cut)</span>
        <span><i class="sw" style="background:var(--a)"></i><b>75/25 split</b> (12 vs 4 nodes — 25% minority loses branch; 75% majority loses 0)</span>
        <span><i class="sw" style="background:var(--subtle)"></i>Dashed: expected losing proposer share (~D/2 vs ~D/4)</span>
      </div>
      <canvas id="sweepCanvas"></canvas>
      <div class="callouts">
        <div class="callout" style="border-left-color:var(--held)">
          <b>1. Safe confirmation is not safe across a partition</b>
          Losing side orphans ~D/2 blocks (50/50) or ~D/4 blocks (75/25 minority), including blocks reported as safe-confirmed (<code>G0-clear</code>), because <code>is_g0_clear</code> only vetoes conflicting branches visible in the node's local Store.
        </div>
        <div class="callout" style="border-left-color:var(--tsq)">
          <b>2. Zero conflicting stable roots or finalizations</b>
          Across all 30 runs, stable roots are never conflicting (always identical or nested on one chain). After GST, heads reconverge within ≤ 1 slot in every single run.
        </div>
        <div class="callout" style="border-left-color:var(--a)">
          <b>3. Missing round-start blocks cost justification votes</b>
          A boundary settlement counts only votes some block carried before it. When the round's first slot has no block, the last slot's voters drop out; with 75% online that often leaves &lt; 2/3 target votes (checked against on-chain counts in 148/149 settlements). Finality piggybacks accumulate across rounds, so finalization is hit less often.
        </div>
      </div>
    </section>
    <section class="panel">
      <h2>Aggregated Metrics Table (Mean [Min–Max] over 5 Seeds per Row)</h2>
      <div id="sweepTableWrap"></div>
    </section>
    <section class="panel" id="timingPanel" hidden>
      <h2>Does it matter when in the round the partition starts? (D = 16)</h2>
      <p class="note">Same metrics, with the cut starting 0, 2, 4 or 7 slots into round 3 (slots 24, 26, 28, 31). Dots are seeds, bars [min–max], lines connect means.</p>
      <canvas id="timingCanvas"></canvas>
      <div id="timingTableWrap"></div>
    </section>
  </div>
</div>
<div class="tip" id="tip" hidden></div>

<script>
/*DATA*/
const RUNS = DATA.runs;
const SWEEP = DATA.sweep || [];
const runNames = Object.keys(RUNS);
const SWEEP_TAB = "30-Run Sweep (16 nodes)";
const allTabs = SWEEP.length ? [...runNames, SWEEP_TAB] : runNames;
let cur = runNames[0];
let progMode = "slot";
let winSize = 64;
let winStart = 1;
let zoomSlot = 40;
let msgMode = "waves";
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function setup(cv, w, h) {
  const r = window.devicePixelRatio || 1;
  cv.width = w * r; cv.height = h * r;
  cv.style.width = "100%"; cv.style.maxWidth = w + "px";
  const c = cv.getContext("2d");
  c.setTransform(r, 0, 0, r, 0, 0);
  c.font = "12px " + css("--sans");
  return c;
}

function finalChain(run) {
  const last = run.states[run.states.length - 1][1][0][1];
  const on = new Set(); let r = last;
  while (r && run.blocks[r]) { on.add(r); r = run.blocks[r][1]; }
  return on;
}

function renderCallouts(run, shareA) {
  const cfg = run.cfg, cut = cfg.slots_down > 0;
  const box = $("callouts");
  if (!cut) {
    box.innerHTML = `
      <div class="callout" style="border-left-color:var(--tsq)"><b>Synchronous baseline</b>All 8 nodes agree on head every slot (0 reorgs, 0 rejected messages). Safe confirmation trails head by 1 slot.</div>
      <div class="callout" style="border-left-color:var(--a)"><b>TSQ lock advances every round</b>Stable root locks via TSQ at each round boundary (s10 → s18 → s26 → s34 → s42). G1 fallback is never needed.</div>
      <div class="callout" style="border-left-color:var(--b)"><b>Two rounds per height (§1)</b>Round-start target is 1 slot ahead of safe-confirmed head, so <code>freeze_round_vote</code> alternates <code>justify@h</code> and <code>empty+fin@h</code> (s16 finalized at s40).</div>
    `;
    return;
  }
  if (shareA === 50) {
    box.innerHTML = `
      <div class="callout" style="border-left-color:var(--held)"><b>① Slot 24 (Cut starts, 50/50)</b>Cross-cut traffic is held. Both Side A and Side B continue proposing and safe-confirming blocks on their own isolated branch.</div>
      <div class="callout" style="border-left-color:var(--held)"><b>② Slot 32 (Round 4: TSQ drops to Floor 0)</b>Neither 50% side has ≥ ⌈2W/3⌉ support in round 3. <code>get_deepest_tsq_root</code> returns the pinned Simplex root (slot 0), so <code>stable_root</code> regresses from s18 to s0.</div>
      <div class="callout" style="border-left-color:var(--heal)"><b>③ Slot 40 (GST Heal &amp; G0 Veto)</b>Held votes arrive at 40.2s. Both branches now carry ≥ 1/3 weight in D, so <code>is_g0_clear</code> vetoes post-cut blocks (safe drops to s23). Side A reorgs at s41 (orphaning 7 safe blocks).</div>
      <div class="callout" style="border-left-color:var(--b)"><b>④ Slot 56 (Finality delayed by D = 16)</b>Height progress resumes at s48 (r6, TSQ locks s42, justifies s16) and finalizes s16 at s56 (+16 slots behind honest s40).</div>
    `;
  } else {
    box.innerHTML = `
      <div class="callout" style="border-left-color:var(--a)"><b>① Slot 24–39 (75% Majority vs 25% Minority)</b>Side A (75%) has ≥ 2/3 stake: at s32 (r4) it locks s24 via TSQ, justifies s16, and advances to h3. Side B (25%) drops to Floor (s0) yet still safe-confirms 3 minority blocks (26, 31, 38).</div>
      <div class="callout" style="border-left-color:var(--heal)"><b>② Slot 40 @ 0.2s (GST Heal &amp; On-Time Finality)</b>Side A finalizes s16 on schedule at s40 (0 delay). At 40.2s, Side B receives Side A's chain and updates its Simplex root to s16 before the 25% deadline (41.5s).</div>
      <div class="callout" style="border-left-color:var(--g1)"><b>③ Slot 40 @ 1.5s (Side B triggers G1 Fallback)</b>Side B's frozen Round 4 vote snapshot (from s39 @ 4.5s) only had 25% votes, so its TSQ lock (s0) is stale behind the new Simplex root (s16). <code>freeze_stable_root</code> falls back to <code>G1</code>, jumping to s32!</div>
      <div class="callout" style="border-left-color:var(--tsq)"><b>④ Slot 41–56 (1-Slot Reconvergence)</b>Side B reorgs onto Side A at s40–41 (orphaning its 3 safe-confirmed blocks). By s48 (r6), all nodes lock s42 via TSQ and finalize s32 at s56.</div>
    `;
  }
}

function clampWindow(maxSlot) {
  if (winSize >= maxSlot) {
    winStart = 1;
  } else {
    winStart = Math.max(1, Math.min(maxSlot - winSize + 1, Math.round(winStart)));
  }
  const slider = $("winSlider");
  slider.min = 1;
  slider.max = Math.max(1, maxSlot - winSize + 1);
  slider.value = winStart;
  slider.disabled = winSize >= maxSlot;
  $("winPrevBtn").disabled = winSize >= maxSlot || winStart <= 1;
  $("winNextBtn").disabled = winSize >= maxSlot || winStart >= maxSlot - winSize + 1;
  const sEnd = Math.min(maxSlot, winStart + winSize - 1);
  $("winReadout").textContent = winSize === 1
    ? `Slot ${winStart} of ${maxSlot} (r${Math.floor(winStart / 8)})`
    : `Slots ${winStart}–${sEnd} of ${maxSlot}`;
}

function clampZoomSlot(maxSlot, spr, slotMs) {
  zoomSlot = Math.max(1, Math.min(maxSlot, Math.round(zoomSlot)));
  const sSlider = $("sSlider");
  sSlider.min = 1;
  sSlider.max = maxSlot;
  sSlider.value = zoomSlot;
  $("sPrevBtn").disabled = zoomSlot <= 1;
  $("sNextBtn").disabled = zoomSlot >= maxSlot;
  const rIdx = Math.floor(zoomSlot / spr);
  const posInRound = (zoomSlot % spr) + 1;
  const t0s = (zoomSlot * slotMs / 1000).toFixed(1);
  const t1s = ((zoomSlot + 1) * slotMs / 1000).toFixed(1);
  $("sReadout").textContent = `Slot ${zoomSlot} / ${maxSlot} · Round ${rIdx} (slot ${posInRound} of ${spr}) · t = ${t0s}s–${t1s}s`;
  [...$("zoomTabs").querySelectorAll("button")].forEach(b => {
    b.setAttribute("aria-pressed", +b.dataset.slot === zoomSlot);
  });
}

function renderSlotDetails(run, s, T, shareA, final) {
  const cfg = run.cfg, cut = cfg.slots_down > 0;
  const cutA = cfg.start, cutB = cfg.start + cfg.slots_down;
  const inCut = cut && s >= cutA && s < cutB;
  const isHealSlot = cut && s === cutB;
  const isRb = s % run.spr === 0;
  const isLastInRound = (s + 1) % run.spr === 0;
  const rIdx = Math.floor(s / run.spr);
  const curRow = run.states[s - 1][1];
  const prevRow = s > 1 ? run.states[s - 2][1] : null;
  const idxA = 0, idxB = cfg.nodes - 1;
  const nA = curRow[idxA], nB = curRow[idxB];

  // Find block proposed in slot s
  let propNode = null, propParentSlot = 0, propOrphaned = false;
  Object.entries(run.blocks).forEach(([root, [bslot, parent, src]]) => {
    if (bslot === s) {
      propNode = src;
      propParentSlot = run.blocks[parent] ? run.blocks[parent][0] : 0;
      propOrphaned = !final.has(root);
    }
  });
  const propSide = propNode === null ? "None" : (!cut ? `Node ${propNode}` : (run.groupOf[propNode] === 0 ? `Node ${propNode} (Side A)` : `Node ${propNode} (Side B)`));

  // Collect Simplex finality votes cast at 25% in slot s
  const votesBySide = { A: new Set(), B: new Set() };
  run.msgs.forEach(([t, at, src, dst, k, held, mslot, voteIdx]) => {
    if (mslot === s && k === 1 && voteIdx >= 0 && run.votes[voteIdx]) {
      const key = run.groupOf[src] === 0 ? "A" : "B";
      votesBySide[key].add(run.votes[voteIdx]);
    }
  });
  const vStrA = [...votesBySide.A].join(", ") || "—";
  const vStrB = [...votesBySide.B].join(", ") || "—";

  // 4-step walkthrough cards explaining the 4 columns of the 1-slot plot
  const step1Body = (propNode !== null
    ? `<b>${propSide}</b> proposes <b>Block #${s}</b> extending parent <b>Block #${propParentSlot}</b>${propOrphaned ? ' <span class="delta-down">(later orphaned)</span>' : ''}. ` +
      (inCut ? `Delivered in +0.2s to same-side peers; <b>blocked across the partition cut</b> (held until slot ${cutB}).` : `Delivered to all 8 nodes within +0.2s.`)
    : `No block proposed in slot ${s}.`) +
    (isRb ? `<br><b>Round ${rIdx} start:</b> Each node also selects its TSQ candidate from the frozen Round ${rIdx - 1} vote snapshot.` : "") +
    (isHealSlot ? `<br><span style="color:var(--heal);font-weight:700">+0.2s GST Heal Flush:</span> All held blocks &amp; votes from slots ${cutA}–${cutB - 1} arrive across the cut before the 25% deadline!` : "");

  let step2Body = `Every node broadcasts <b>both</b> its <b>Goldfish availability vote</b> (purple) for its current head and its <b>Simplex finality vote</b> (green) at +1.5s (arriving at peers by ~+1.7s):<br>` +
    (cut ? `• <b>Side A Simplex vote:</b> <code>${vStrA}</code><br>• <b>Side B Simplex vote:</b> <code>${vStrB}</code>` : `• <b>Simplex vote cast:</b> <code>${vStrA}</code>`);
  if (isRb) {
    const explainSrc = (stSlot, src) => src === "G1"
      ? `<b>#${stSlot} via G1 Fallback</b> (stale TSQ view fell behind new Simplex root #${nB[6]})`
      : (src === "FLOOR" ? `<b>#0 (Simplex Floor)</b> — no ≥2/3 supermajority in Round ${rIdx - 1}` : `<b>#${stSlot} via TSQ</b> (≥2/3 supermajority lock)`);
    step2Body = `<b>Round ${rIdx} Stable Root Lock</b> (<code>freeze_stable_root</code>), then all nodes broadcast their <b>Goldfish availability vote</b> (purple) + <b>Simplex finality vote</b> (green):<br>` +
      (cut
        ? `• <b>Side A locks:</b> ${explainSrc(nA[4], nA[9])}<br>• <b>Side B locks:</b> ${explainSrc(nB[4], nB[9])}<br>• <b>Simplex votes:</b> A=<code>${vStrA}</code>, B=<code>${vStrB}</code>`
        : `• <b>All nodes lock:</b> ${explainSrc(nA[4], nA[9])} · Vote: <code>${vStrA}</code>`);
  }

  const step3Body = `<b>No new votes are sent at 50%.</b> Instead, each node runs <code>freeze_available_votes</code> to freeze the Goldfish availability votes received before +3.0s into <code>store.D</code>, then recomputes <b>Head</b> and <b>Safe-Confirmed (G0-clear)</b>:<br>` +
    (cut
      ? `• <b>Side A:</b> Head = <b>#${nA[0]}</b>, Safe-Confirmed = <b>#${nA[2]}</b><br>• <b>Side B:</b> Head = <b>#${nB[0]}</b>, Safe-Confirmed = <b>#${nB[2]}</b>`
      : `• <b>All nodes:</b> Head = <b>#${nA[0]}</b>, Safe-Confirmed = <b>#${nA[2]}</b>`);

  const step4Body = isLastInRound
    ? `<b>End of Round ${rIdx} Snapshot!</b> Every node freezes the votes it has received by +4.5s as its <b>Round ${rIdx} Vote Snapshot</b> (black squares). In 1.5s (at slot ${s + 1} @ 0% &amp; 25%), this snapshot is used to compute Round ${rIdx + 1}'s <b>Stable Root</b>.` +
      (inCut ? ` Because the partition is active, Side A's snapshot only contains ${shareA}% stake and Side B's only contains ${100 - shareA}% stake.` : "")
    : `Each node merges votes received before the +4.5s cutoff into its local vote buffer (black squares) for the next slot proposer to build on.`;

  $("slotStepCards").innerHTML = `
    <div class="callout" style="border-left-color:var(--a)"><b>① 0% (+0.0s) · Block Proposal${isRb ? " &amp; Round Start" : ""}</b>${step1Body}</div>
    <div class="callout" style="border-left-color:var(--tsq)"><b>② 25% (+1.5s) · ${isRb ? "Stable Root + " : ""}Broadcast Both Votes</b>${step2Body}</div>
    <div class="callout" style="border-left-color:var(--g1)"><b>③ 50% (+3.0s) · Freeze Avail Votes &amp; Update Safe/Head</b>${step3Body}</div>
    <div class="callout" style="border-left-color:var(--fg)"><b>④ 75% (+4.5s) · ${isLastInRound ? "Freeze Round Vote Snapshot" : "Incoming Vote Cutoff"}</b>${step4Body}</div>
  `;

  // Per-side state comparison table
  const fmtDelta = (now, prev, isRootOrphan) => {
    if (prev === null || prev === undefined || now === prev) {
      return `<b>#${now}</b>${isRootOrphan ? ' <span class="delta-down">(orphaned branch)</span>' : ''}`;
    }
    const diff = now - prev;
    const cls = diff < 0 ? "delta-down" : "delta-up";
    const sign = diff > 0 ? `+${diff}` : `${diff}`;
    return `<b>#${now}</b> <span class="${cls}">(was #${prev}, ${sign})</span>${isRootOrphan ? ' <span class="delta-down">[orphaned]</span>' : ''}`;
  };

  const vPerNode = Math.round(cfg.validators / cfg.nodes);
  const vSplit = cfg.split * vPerNode;
  const rows = [
    [cut ? `Side A (${shareA}% · Nodes 0–${cfg.split - 1} · Val 0–${vSplit - 1})` : "Nodes 0–3", idxA, vStrA],
    [cut ? `Side B (${100 - shareA}% · Nodes ${cfg.split}–${cfg.nodes - 1} · Val ${vSplit}–${cfg.validators - 1})` : "Nodes 4–7", idxB, vStrB],
  ].map(([name, i, vStr]) => {
    const n = curRow[i], p = prevRow ? prevRow[i] : null;
    const headOrph = n[1] && run.blocks[n[1]] && !final.has(n[1]);
    const safeOrph = n[3] && run.blocks[n[3]] && !final.has(n[3]);
    const srcLabel = n[9] === "G1"
      ? `<span class="delta-g1">G1 Fallback</span>`
      : (n[9] === "FLOOR" ? `<span class="delta-down">Simplex Floor (no 2/3 quorum)</span>` : `<span class="delta-up">${n[9]}</span>`);
    return `<tr>
      <td><b>${name}</b></td>
      <td>${fmtDelta(n[0], p ? p[0] : null, headOrph)}</td>
      <td>${fmtDelta(n[2], p ? p[2] : null, safeOrph)}</td>
      <td>${fmtDelta(n[4], p ? p[4] : null, false)} · ${srcLabel}</td>
      <td>Justified <b>#${n[7]}</b> / Finalized <b>#${n[6]}</b> (height h=${n[8]})</td>
      <td><code>${vStr}</code></td>
    </tr>`;
  }).join("");

  $("slotStateTable").innerHTML = `
    <table class="summary">
      <thead><tr>
        <th>Partition Side (Nodes &amp; Validators)</th>
        <th>Head Block (50%)</th>
        <th>Safe-Confirmed Block (50%)</th>
        <th>Locked Stable Root (25%)</th>
        <th>Simplex Checkpoints (Height)</th>
        <th>Simplex Vote Cast (25%)</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderSingle() {
  const run = RUNS[cur];
  const T = {
    a: css("--a"), b: css("--b"), aSoft: css("--aSoft"), bSoft: css("--bSoft"),
    held: css("--held"), heal: css("--heal"), tsq: css("--tsq"), g1: css("--g1"),
    fg: css("--fg"), muted: css("--muted"), subtle: css("--subtle"),
    grid: css("--grid"), gs: css("--gridStrong"), tint: css("--tint"), panel: css("--panel"), bg: css("--bg")
  };
  const cfg = run.cfg, cut = cfg.slots_down > 0;
  const cutA = cfg.start, cutB = cfg.start + cfg.slots_down;
  const shareA = Math.round(100 * cfg.split / cfg.nodes);
  const vPerNode = Math.round(cfg.validators / cfg.nodes);
  const vSplit = cfg.split * vPerNode;
  const final = finalChain(run);
  const maxSlot = run.states.length;

  clampWindow(maxSlot);
  clampZoomSlot(maxSlot, run.spr, run.slotMs);
  const sFrom = winStart;
  const sTo = Math.min(maxSlot, winStart + winSize - 1);
  // For 1-slot view in Plot 1, span [sFrom - 0.85, sFrom + 0.65] on X so the incoming level at s-1 and vertical jump at s are centered!
  const xMinSlot = winSize === 1 ? Math.max(1, sFrom - 0.85) : sFrom;
  const xMaxSlot = winSize === 1 ? Math.min(maxSlot + 0.5, sFrom + 0.65) : (sTo + (winSize < maxSlot ? 0.35 : 0));

  // Top facts bar with explicit Side A / Side B node & validator membership
  const sideBadges = cut
    ? `<span class="side-pill side-a"><b>Side A (${shareA}%)</b>: Nodes 0–${cfg.split - 1} (Validators 0–${vSplit - 1}, ${vSplit}/${cfg.validators} stake)</span>` +
      `<span class="side-pill side-b"><b>Side B (${100 - shareA}%)</b>: Nodes ${cfg.split}–${cfg.nodes - 1} (Validators ${vSplit}–${cfg.validators - 1}, ${cfg.validators - vSplit}/${cfg.validators} stake)</span>`
    : `<span class="side-pill side-a"><b>All Honest (100%)</b>: Nodes 0–${cfg.nodes - 1} (Validators 0–${cfg.validators - 1})</span>`;

  $("facts").innerHTML =
    sideBadges +
    (cut ? `<span>partition <b>slots ${cutA}–${cutB - 1} (D=${cfg.slots_down})</b> · GST heal at <b>slot ${cutB}</b></span>` : "") +
    `<span>latency <b>${cfg.latency_ms}+U[0,${cfg.jitter_ms}] ms</b></span>` +
    `<span>seed <b>${cfg.seed}</b></span>`;

  renderCallouts(run, shareA);

  // ---------- 1. Node Beliefs (Windowed X-axis + Auto-Scaling Y-axis) ----------
  const W = 1120;
  const panels = [
    ["1. Head slot (get_head)", 0, 1, "head"],
    ["2. Safe-confirmed slot (get_safe_confirmed_head, G0-clear)", 2, 3, "safe"],
    ["3. Stable root slot (freeze_stable_root: TSQ vs Floor vs G1)", 4, 5, "stable"],
    ["4. Simplex Finality: Finalized (solid blue/orange) & Justified (dashed cyan/purple) + Height h", 6, null, "fin"],
  ];
  const ph = 138, gap = 36, PH = panels.length * (ph + gap) + 20;
  const pc = setup($("prog"), W, PH);
  const L = 58, R = 48;
  const PX = s => L + ((s - xMinSlot) / Math.max(0.5, xMaxSlot - xMinSlot)) * (W - L - R);
  const idxA = 0, idxB = cfg.nodes - 1;

  panels.forEach(([label, si, ri, kind], k) => {
    const y0 = 18 + k * (ph + gap);
    const isLag = progMode === "lag";
    const valOf = (s, nstate, idx) => {
      const raw = nstate[idx];
      if (raw === null || raw === undefined) return null;
      return isLag ? (s - raw) : raw;
    };

    // Compute Y range [yMin, yMax] strictly from values visible in [Math.max(1, sFrom - 1), sTo]!
    let yMin = 0, yMax = maxSlot;
    if (winSize < maxSlot || isLag) {
      let lo = Infinity, hi = -Infinity;
      const scanStart = Math.max(1, sFrom - 1);
      for (let s = scanStart; s <= sTo; s++) {
        const ns = run.states[s - 1][1];
        [idxA, idxB].forEach(i => {
          const v = valOf(s, ns[i], si);
          if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
          if (kind === "fin") {
            const jv = valOf(s, ns[i], 7);
            if (jv !== null) { lo = Math.min(lo, jv); hi = Math.max(hi, jv); }
          }
        });
      }
      if (!isFinite(lo)) { lo = 0; hi = maxSlot; }
      if (winSize >= maxSlot && isLag) {
        yMin = 0;
        yMax = Math.max(8, Math.ceil(hi / 4) * 4);
      } else {
        const pad = Math.max(1, Math.ceil((hi - lo) * 0.12));
        yMin = Math.max(0, Math.floor(lo - pad));
        yMax = Math.ceil(hi + pad);
        if (yMax - yMin < 2) yMax = yMin + 2;
      }
    }

    const PY = v => y0 + 22 + (1 - (v - yMin) / Math.max(1, yMax - yMin)) * (ph - 30);

    pc.fillStyle = T.fg; pc.font = "600 13px " + css("--sans"); pc.textAlign = "left";
    pc.fillText(
      label + (isLag ? " — lag (slots behind current)" : "") + (winSize < maxSlot ? `  [Y-axis: ${yMin}..${yMax}]` : ""),
      L, y0 + 10
    );
    pc.font = "11px " + css("--mono");

    // Determine clean integer tick step for [yMin, yMax]
    const ySpan = yMax - yMin;
    const yStep = ySpan <= 8 ? 1 : (ySpan <= 18 ? 2 : (ySpan <= 36 ? 4 : (ySpan <= 48 ? 8 : 16)));
    const firstTick = Math.ceil(yMin / yStep) * yStep;
    for (let v = firstTick; v <= yMax; v += yStep) {
      const yy = PY(v);
      pc.strokeStyle = T.grid; pc.lineWidth = 1;
      pc.beginPath(); pc.moveTo(L, yy); pc.lineTo(W - R, yy); pc.stroke();
      pc.fillStyle = T.muted; pc.textAlign = "right";
      pc.fillText(v, L - 8, yy + 4);
    }

    // Clip drawing inside subplot box with small horizontal margin for endpoint markers
    pc.save();
    pc.beginPath();
    pc.rect(L - 6, y0 + 14, W - L - R + 12, ph - 14);
    pc.clip();

    if (cut) {
      pc.fillStyle = T.tint;
      pc.fillRect(PX(cutA), y0 + 18, PX(cutB) - PX(cutA), ph - 22);
      pc.strokeStyle = T.held; pc.lineWidth = 1.2; pc.setLineDash([4, 3]);
      pc.beginPath(); pc.moveTo(PX(cutA), y0 + 18); pc.lineTo(PX(cutA), y0 + ph - 4); pc.stroke();
      pc.strokeStyle = T.heal;
      pc.beginPath(); pc.moveTo(PX(cutB), y0 + 18); pc.lineTo(PX(cutB), y0 + ph - 4); pc.stroke();
      pc.setLineDash([]);
    }

    // Highlight active Section 3 zoomSlot column lightly
    const zsX = PX(zoomSlot);
    const slotW = (W - L - R) / Math.max(1, xMaxSlot - xMinSlot);
    pc.fillStyle = T.aSoft;
    pc.fillRect(zsX - Math.max(3, slotW * 0.15), y0 + 18, Math.max(6, slotW), ph - 22);

    const xStep = winSize <= 16 ? 1 : 8;
    for (let s = 1; s <= maxSlot; s++) {
      if (s % xStep !== 0 && s % 8 !== 0) continue;
      const isRb = s % 8 === 0;
      pc.strokeStyle = isRb ? T.gs : T.grid;
      pc.lineWidth = isRb ? 1.2 : 0.8;
      pc.beginPath(); pc.moveTo(PX(s), y0 + 18); pc.lineTo(PX(s), y0 + ph - 4); pc.stroke();
    }

    const ptsA = [], ptsB = [];
    run.states.forEach(([s, ns]) => {
      const vA = valOf(s, ns[idxA], si), vB = valOf(s, ns[idxB], si);
      if (vA !== null) ptsA.push([s, PX(s), PY(vA), ns[idxA], vA]);
      if (vB !== null) ptsB.push([s, PX(s), PY(vB), ns[idxB], vB]);
    });

    const stepCoords = (pts, dy = 0) => {
      if (!pts.length) return [];
      const res = [[pts[0][1], pts[0][2] + dy]];
      for (let i = 1; i < pts.length; i++) {
        res.push([pts[i][1], pts[i - 1][2] + dy]);
        res.push([pts[i][1], pts[i][2] + dy]);
      }
      res.push([PX(maxSlot + 1), pts[pts.length - 1][2] + dy]);
      return res;
    };
    const stepA_raw = stepCoords(ptsA, 0), stepB_raw = stepCoords(ptsB, 0);
    // Use +/- 1.1px vertical twin-track offset so both solid blue and solid orange are visible without dashing!
    const stepA = stepCoords(ptsA, cut ? -1.1 : 0), stepB = stepCoords(ptsB, cut ? +1.1 : 0);

    // Divergence shading between Side A and Side B step functions
    if (cut && stepA_raw.length === stepB_raw.length && stepA_raw.length > 0) {
      pc.fillStyle = T.bSoft;
      pc.beginPath();
      stepA_raw.forEach((p, i) => i ? pc.lineTo(p[0], p[1]) : pc.moveTo(p[0], p[1]));
      for (let i = stepB_raw.length - 1; i >= 0; i--) pc.lineTo(stepB_raw[i][0], stepB_raw[i][1]);
      pc.closePath(); pc.fill();
    }

    // Justified dashed step curve on Finality panel (distinct colors: cyan for A, purple for B)
    if (kind === "fin") {
      const jList = cut
        ? [[idxB, "#9333ea", [4, 3], +0.8], [idxA, "#0891b2", [6, 3], -0.8]]
        : [[idxA, "#0891b2", [5, 3], 0]];
      jList.forEach(([idx, col, dash, dy]) => {
        const jPts = stepCoords(run.states.map(([s, ns]) => [s, PX(s), PY(valOf(s, ns[idx], 7))]), dy);
        pc.strokeStyle = col; pc.lineWidth = 1.9; pc.setLineDash(dash);
        pc.beginPath();
        jPts.forEach((p, i) => i ? pc.lineTo(p[0], p[1]) : pc.moveTo(p[0], p[1]));
        pc.stroke(); pc.setLineDash([]);
      });
    }

    // Draw Side B (solid orange) and Side A (solid blue — never dashed!)
    if (stepB.length && cut) {
      pc.strokeStyle = T.b; pc.lineWidth = 2.3;
      pc.beginPath(); stepB.forEach((p, i) => i ? pc.lineTo(p[0], p[1]) : pc.moveTo(p[0], p[1])); pc.stroke();
    }
    if (stepA.length) {
      pc.strokeStyle = T.a; pc.lineWidth = 2.3;
      pc.beginPath(); stepA.forEach((p, i) => i ? pc.lineTo(p[0], p[1]) : pc.moveTo(p[0], p[1])); pc.stroke();
    }

    // When zoomed in (winSize <= 16), print exact integer values on step plateaus
    if (winSize <= 16) {
      pc.font = "600 10.5px " + css("--mono");
      ptsA.forEach(([s, x, y, nstate, vA], idx) => {
        if (s < sFrom - 1 || s > sTo) return;
        const prevVA = idx > 0 ? ptsA[idx - 1][4] : null;
        if (winSize <= 8 || vA !== prevVA) {
          pc.fillStyle = T.a; pc.textAlign = "left";
          pc.fillText(vA, x + 4, y - 6);
        }
      });
      if (cut) {
        ptsB.forEach(([s, x, y, nstate, vB], idx) => {
          if (s < sFrom - 1 || s > sTo) return;
          const vA = ptsA[idx] ? ptsA[idx][4] : null;
          if (vB === vA && winSize > 4) return;
          const prevVB = idx > 0 ? ptsB[idx - 1][4] : null;
          if (winSize <= 8 || vB !== prevVB) {
            pc.fillStyle = T.b; pc.textAlign = "left";
            pc.fillText(vB, x + 4, y + 13);
          }
        });
      }
    }

    // Orphaned rings
    if (ri !== null) {
      [ptsA, ptsB].forEach(pts => {
        pts.forEach(([s, x, y, nstate]) => {
          if (s < sFrom - 1 || s > sTo + 1) return;
          const r = nstate[ri];
          if (r && run.blocks[r] && !final.has(r)) {
            pc.fillStyle = T.panel; pc.strokeStyle = T.held; pc.lineWidth = 1.8;
            pc.beginPath(); pc.arc(x, y, 4.0, 0, 7); pc.fill(); pc.stroke();
          }
        });
      });
    }

    // Badges on Stable root
    if (kind === "stable") {
      for (let s = 8; s <= maxSlot; s += 8) {
        const ns = run.states[s - 1][1];
        [[idxA, 0], [idxB, 1]].forEach(([ni, sideIdx]) => {
          const stSlot = ns[ni][4], stSrc = ns[ni][9];
          if (stSlot === null) return;
          if (sideIdx === 1 && stSlot === ns[idxA][4] && stSrc === ns[idxA][9]) return;
          const x = PX(s), y = PY(isLag ? (s - stSlot) : stSlot);
          if (stSrc === "G1") {
            pc.fillStyle = T.g1;
            pc.beginPath(); pc.moveTo(x, y - 6); pc.lineTo(x + 6, y); pc.lineTo(x, y + 6); pc.lineTo(x - 6, y); pc.closePath(); pc.fill();
            pc.fillStyle = T.g1; pc.textAlign = "left"; pc.fillText(`${stSlot} (G1)`, x + 8, y + 12);
          } else if (stSrc === "FLOOR") {
            pc.fillStyle = T.panel; pc.strokeStyle = T.held; pc.lineWidth = 2;
            pc.fillRect(x - 4.5, y - 4.5, 9, 9); pc.strokeRect(x - 4.5, y - 4.5, 9, 9);
            if (s === 32) { pc.fillStyle = T.held; pc.textAlign = "left"; pc.fillText("0 (Floor)", x + 7, y - 5); }
          } else if (stSrc === "TSQ") {
            pc.fillStyle = T.tsq;
            pc.beginPath(); pc.arc(x, y, 4, 0, 7); pc.fill();
            pc.textAlign = "left"; pc.fillText(`${stSlot}`, x + 5, y - 6);
          }
        });
      }
    }

    // Height badges on Finality
    if (kind === "fin") {
      for (let s = 8; s <= maxSlot; s += 8) {
        const ns = run.states[s - 1][1];
        const hA = ns[idxA][8], hB = ns[idxB][8];
        pc.fillStyle = T.muted; pc.textAlign = "center";
        pc.fillText(hA === hB ? `h${hA}` : `h${hA}/h${hB}`, PX(s), y0 + 30);
      }
    }

    pc.restore();
  });

  // Bottom X-axis labels for current window
  pc.textAlign = "center";
  const lblStep = winSize <= 16 ? 1 : 8;
  for (let s = Math.max(1, Math.floor(xMinSlot)); s <= Math.min(maxSlot, Math.ceil(xMaxSlot)); s++) {
    if (winSize > 16 && s % lblStep !== 0) continue;
    const isRb = s % run.spr === 0;
    pc.fillStyle = isRb ? T.fg : T.muted;
    pc.font = (isRb ? "600 " : "400 ") + "11px " + css("--mono");
    pc.fillText(isRb ? `slot ${s} (r${s / run.spr})` : `s${s}`, PX(s), PH - 4);
  }

  // ---------- 2. Block Tree ----------
  const blocks = Object.entries(run.blocks).map(([root, [slot, parent, src]]) => ({ root, slot, parent, src })).sort((x, y) => x.slot - y.slot);
  const everSafe = new Set(); run.states.forEach(s => s[1].forEach(n => everSafe.add(n[3])));
  const rowOf = {};
  blocks.forEach(b => { rowOf[b.root] = final.has(b.root) ? 0 : 1; });
  const hasOrphan = blocks.some(b => rowOf[b.root] === 1);
  const TH = hasOrphan ? 132 : 84;
  const tc = setup($("tree"), W, TH);
  const TL = 96, TR = 28;
  const TX = s => TL + (s / maxSlot) * (W - TL - TR);
  const TY = r => r === 0 ? 38 : 92;

  if (cut) {
    tc.fillStyle = T.tint; tc.fillRect(TX(cutA), 16, TX(cutB) - TX(cutA), TH - 22);
    tc.strokeStyle = T.held; tc.setLineDash([4, 3]);
    tc.beginPath(); tc.moveTo(TX(cutA), 16); tc.lineTo(TX(cutA), TH - 6); tc.stroke();
    tc.strokeStyle = T.heal;
    tc.beginPath(); tc.moveTo(TX(cutB), 16); tc.lineTo(TX(cutB), TH - 6); tc.stroke();
    tc.setLineDash([]);
  }
  // Highlight Section 3 active slot on the block tree
  const treeStepW = (W - TL - TR) / maxSlot;
  tc.fillStyle = T.aSoft;
  tc.fillRect(TX(zoomSlot) - treeStepW * 0.4, 16, Math.max(8, treeStepW * 0.8), TH - 22);

  for (let s = 0; s <= maxSlot; s += run.spr) {
    tc.strokeStyle = T.grid; tc.beginPath(); tc.moveTo(TX(s), 16); tc.lineTo(TX(s), TH - 6); tc.stroke();
    tc.fillStyle = T.muted; tc.textAlign = "center"; tc.font = "11px " + css("--mono");
    tc.fillText(`s${s}`, TX(s), 12);
  }
  tc.textAlign = "left"; tc.font = "600 12px " + css("--sans");
  tc.fillStyle = T.fg; tc.fillText("Final chain", 6, TY(0) + 4);
  if (hasOrphan) { tc.fillStyle = T.held; tc.fillText("Orphaned", 6, TY(1) + 4); }

  const byRoot = {}; blocks.forEach(b => byRoot[b.root] = b);
  blocks.forEach(b => {
    const p = byRoot[b.parent];
    const px = p ? TX(p.slot) : TX(0), py = p ? TY(rowOf[p.root]) : TY(0);
    tc.strokeStyle = rowOf[b.root] === 0 ? T.gs : T.held; tc.lineWidth = 1.5;
    tc.beginPath(); tc.moveTo(px, py); tc.lineTo(TX(b.slot), TY(rowOf[b.root])); tc.stroke();
  });
  tc.fillStyle = T.muted; tc.beginPath(); tc.arc(TX(0), TY(0), 4.5, 0, 7); tc.fill();
  tc.strokeStyle = T.fg; tc.lineWidth = 1.8; tc.strokeRect(TX(0) - 6.5, TY(0) - 6.5, 13, 13);

  const finSlots = new Set([0, run.states[run.states.length - 1][1][0][6]]);
  if (finSlots.has(32)) finSlots.add(16);

  blocks.forEach(b => {
    const x = TX(b.slot), y = TY(rowOf[b.root]);
    tc.fillStyle = !cut ? T.a : (run.groupOf[b.src] === 0 ? T.a : T.b);
    tc.beginPath(); tc.arc(x, y, 4.8, 0, 7); tc.fill();
    if (rowOf[b.root] === 0 && finSlots.has(b.slot)) {
      tc.strokeStyle = T.fg; tc.lineWidth = 1.8; tc.strokeRect(x - 6.8, y - 6.8, 13.6, 13.6);
    }
    if (rowOf[b.root] === 1) {
      if (everSafe.has(b.root)) {
        tc.strokeStyle = T.held; tc.lineWidth = 2;
        tc.beginPath(); tc.arc(x, y, 7.6, 0, 7); tc.stroke();
      }
      tc.fillStyle = T.held; tc.font = "600 10px " + css("--mono"); tc.textAlign = "center";
      tc.fillText(b.slot, x, y + 18);
    }
  });

  $("tree").onclick = e => {
    const rect = $("tree").getBoundingClientRect();
    const clickX = (e.clientX - rect.left) * (W / rect.width);
    const clickedSlot = Math.round(((clickX - TL) / (W - TL - TR)) * maxSlot);
    if (clickedSlot >= 1 && clickedSlot <= maxSlot) {
      zoomSlot = clickedSlot;
      renderSingle();
    }
  };

  // ---------- 3. Single-Slot 8-Node Sub-Slot Deadline & Message Inspector ----------
  renderSlotDetails(run, zoomSlot, T, shareA, final);

  const NW = 1120, NH = 416;
  const nc = setup($("net"), NW, NH);
  const NL = 178, NR = 42;
  const s = zoomSlot;
  const t0 = s * run.slotMs, t1 = (s + 1) * run.slotMs;
  const ZX = t => NL + ((t - t0) / (t1 - t0)) * (NW - NL - NR);
  const ny0 = 58, nph = 312;
  const NY = n => ny0 + 22 + (n + (n >= cfg.split && cut ? 0.7 : 0)) / (cfg.nodes - 1 + (cut ? 0.7 : 0)) * (nph - 44);
  const yMidCut = cut ? (NY(cfg.split - 1) + NY(cfg.split)) / 2 : (ny0 + nph / 2);

  const isRb = s % run.spr === 0;
  const isLastInRound = (s + 1) % run.spr === 0;
  const rIdx = Math.floor(s / run.spr);
  const inCut = cut && s >= cutA && s < cutB;
  const isHealSlot = cut && s === cutB;

  // Title banner
  nc.fillStyle = T.fg; nc.font = "600 13.5px " + css("--sans"); nc.textAlign = "left";
  const statusStr = inCut
    ? `PARTITION ACTIVE (cross-side messages blocked & held until slot ${cutB})`
    : (isHealSlot ? `GST HEAL SLOT (all held messages from slots ${cutA}–${cutB - 1} arrive @ +0.2s)` : `Synchronous delivery (~0.2s latency)`);
  nc.fillText(
    `Slot ${s} Timeline (Round ${rIdx}, t = ${(t0 / 1000).toFixed(1)}s … ${(t1 / 1000).toFixed(1)}s) — ${statusStr}`,
    6, 16
  );

  // Shaded background & partition barrier line if in cut
  if (inCut) {
    nc.fillStyle = T.tint;
    nc.fillRect(NL, ny0, NW - NL - NR, nph);
    nc.strokeStyle = T.held; nc.setLineDash([6, 4]); nc.lineWidth = 1.8;
    nc.beginPath(); nc.moveTo(NL, yMidCut); nc.lineTo(NW - NR, yMidCut); nc.stroke();
    nc.setLineDash([]);
  }

  // Sub-slot deadlines: 0%, 25%, 50%, 75%, 100% with plain-English headers
  const dSpecs = [
    [0, `0% (+0.0s)`, isRb ? "① Propose Block + Pick TSQ" : "① Propose Block", T.a, true],
    [run.deadlines[0], `25% (+1.5s)`, isRb ? "② Stable Root + Broadcast Votes" : "② Broadcast Simplex & Avail Votes", T.tsq, false],
    [run.deadlines[1], `50% (+3.0s)`, "③ Freeze Avail Votes + Safe/Head", T.g1, false],
    [run.deadlines[2], `75% (+4.5s)`, isLastInRound ? `④ Freeze Round r${rIdx} Vote Snapshot` : "④ Freeze Incoming Votes", T.fg, false],
    [run.slotMs, `100% (+6.0s)`, `Slot ${s + 1} starts`, T.muted, true],
  ];
  dSpecs.forEach(([off, lbl1, lbl2, col, strong]) => {
    const x = ZX(t0 + off);
    nc.strokeStyle = strong ? T.gs : T.grid; nc.lineWidth = strong ? 1.6 : 1.1;
    nc.setLineDash(strong ? [] : [4, 3]);
    nc.beginPath(); nc.moveTo(x, ny0); nc.lineTo(x, ny0 + nph); nc.stroke();
    nc.setLineDash([]);
    nc.fillStyle = strong ? T.fg : col; nc.font = "600 11px " + css("--mono"); nc.textAlign = "center";
    nc.fillText(lbl1, x, ny0 - 20);
    nc.font = "600 10.5px " + css("--sans"); nc.fillStyle = col;
    nc.fillText(lbl2, x, ny0 - 6);
  });

  // Draw 8 horizontal node swimlanes with explicit Side and Validator IDs
  for (let n = 0; n < cfg.nodes; n++) {
    const y = NY(n), grp = run.groupOf[n];
    const col = !cut ? T.a : (grp === 0 ? T.a : T.b);
    const v0 = n * vPerNode, v1 = (n + 1) * vPerNode - 1;
    nc.strokeStyle = T.grid; nc.lineWidth = 1;
    nc.beginPath(); nc.moveTo(NL, y); nc.lineTo(NW - NR, y); nc.stroke();
    nc.fillStyle = col; nc.font = "600 11px " + css("--mono"); nc.textAlign = "left";
    const sideStr = !cut ? "Honest" : (grp === 0 ? "Side A" : "Side B");
    nc.fillText(`Node ${n} · ${sideStr} (Val ${v0}–${v1})`, 6, y + 4);
  }

  // Helper to draw a pill label with background so text never clashes with lines
  const drawPill = (x, y, text, fgCol, borderCol, align = "left") => {
    nc.font = "600 10px " + css("--mono");
    const tw = nc.measureText(text).width;
    const px = align === "center" ? x - tw / 2 - 5 : (align === "right" ? x - tw - 10 : x);
    nc.fillStyle = T.panel; nc.globalAlpha = 0.94;
    nc.fillRect(px, y - 10, tw + 10, 15);
    nc.globalAlpha = 1;
    if (borderCol) {
      nc.strokeStyle = borderCol; nc.lineWidth = 1;
      nc.strokeRect(px, y - 10, tw + 10, 15);
    }
    nc.fillStyle = fgCol; nc.textAlign = "left";
    nc.fillText(text, px + 5, y + 1);
  };

  // Draw GST Heal Flush wave at +0.2s on slot 40
  if (isHealSlot) {
    const xFlushStart = ZX(t0), xFlushEnd = ZX(t0 + 250);
    nc.fillStyle = T.heal; nc.globalAlpha = 0.14;
    nc.fillRect(xFlushStart, NY(0) - 8, xFlushEnd - xFlushStart, NY(cfg.nodes - 1) - NY(0) + 16);
    nc.globalAlpha = 1;
    nc.strokeStyle = T.heal; nc.lineWidth = 2.6;
    nc.beginPath(); nc.moveTo(xFlushEnd, NY(0) - 4); nc.lineTo(xFlushEnd, NY(cfg.nodes - 1) + 4); nc.stroke();
    drawPill(xFlushEnd + 5, yMidCut, `← +0.2s GST Flush: held s${cutA}–s${cutB - 1} msgs arrive`, T.heal, T.heal, "left");
  }

  // Draw Block Proposal rays at 0% (+0.0s -> +0.2s)
  Object.entries(run.blocks).forEach(([root, [bslot, parent, src]]) => {
    if (bslot !== s) return;
    const pSlot = run.blocks[parent] ? run.blocks[parent][0] : 0;
    const gSrc = run.groupOf[src];
    const propCol = !cut ? T.a : (gSrc === 0 ? T.a : T.b);
    const xProp = ZX(t0), yProp = NY(src);

    // Draw rays from proposer node to every other node
    for (let dst = 0; dst < cfg.nodes; dst++) {
      if (dst === src) continue;
      const gDst = run.groupOf[dst];
      const blocked = inCut && gSrc !== gDst;
      const xArr = ZX(t0 + (blocked ? 380 : 220));
      const yArr = blocked ? yMidCut : NY(dst);
      nc.strokeStyle = blocked ? T.held : propCol;
      nc.globalAlpha = blocked ? 0.75 : 0.55;
      nc.lineWidth = 1.7;
      nc.setLineDash(blocked ? [4, 3] : []);
      nc.beginPath(); nc.moveTo(xProp, yProp); nc.lineTo(xArr, yArr); nc.stroke();
      nc.setLineDash([]); nc.globalAlpha = 1;
    }

    // Proposer dot and clear plain-English badge (fits cleanly inside [0%, 25%] column!)
    nc.fillStyle = propCol;
    nc.beginPath(); nc.arc(xProp, yProp, 6, 0, 7); nc.fill();
    const orphTag = !final.has(root) ? " · orphaned" : "";
    drawPill(xProp + 8, yProp - 9, `Proposes #${s} (parent #${pSlot}${orphTag})`, propCol, propCol, "left");
  });

  // At 25% (+1.5s), BOTH Simplex Finality Votes (green, k=1) AND Goldfish Availability Votes (purple, k=2) are broadcast!
  // They arrive at peers around +1.7s..+1.8s (well before the 50% confirmation cutoff at +3.0s).
  const x25Start = ZX(t0 + run.deadlines[0]);
  const x25Mid = ZX(t0 + run.deadlines[0] + 135);
  const x25End = ZX(t0 + run.deadlines[0] + 270);
  if (msgMode === "rays") {
    [1, 2].forEach(kKind => {
      const col = kKind === 1 ? T.tsq : T.g1;
      run.msgs.forEach(([t, at, src, dst, k, held]) => {
        if (k !== kKind) return;
        const sentHere = t >= t0 && t < t1;
        if (!sentHere) return;
        const x1 = ZX(t);
        const x2 = ZX(Math.min(t1, held && inCut ? t + 420 : at));
        const y1 = NY(src);
        const y2 = held && inCut ? yMidCut : NY(dst);
        nc.strokeStyle = held && inCut ? T.held : col;
        nc.globalAlpha = 0.28;
        nc.lineWidth = 1.1;
        nc.setLineDash(held && inCut ? [3, 3] : []);
        nc.beginPath(); nc.moveTo(x1, y1); nc.lineTo(x2, y2); nc.stroke();
        nc.setLineDash([]); nc.globalAlpha = 1;
      });
    });
  } else {
    // Draw twin side-by-side broadcast wave bands at 25% (+1.5s..+1.77s): Green (Simplex finality) + Purple (Goldfish availability)
    const drawBand = (xa, xb, col) => {
      if (inCut) {
        const yA0 = NY(0) - 6, yA1 = NY(cfg.split - 1) + 6;
        const yB0 = NY(cfg.split) - 6, yB1 = NY(cfg.nodes - 1) + 6;
        nc.fillStyle = col; nc.globalAlpha = 0.14;
        nc.fillRect(xa, yA0, xb - xa, yA1 - yA0);
        nc.fillRect(xa, yB0, xb - xa, yB1 - yB0);
        nc.globalAlpha = 1;
      } else {
        const y0Band = NY(0) - 6, y1Band = NY(cfg.nodes - 1) + 6;
        nc.fillStyle = col; nc.globalAlpha = 0.14;
        nc.fillRect(xa, y0Band, xb - xa, y1Band - y0Band);
        nc.globalAlpha = 1;
      }
    };
    drawBand(x25Start, x25Mid, T.tsq);
    drawBand(x25Mid, x25End, T.g1);
    if (inCut) {
      const yA1 = NY(cfg.split - 1) + 2, yB0 = NY(cfg.split) - 2;
      nc.strokeStyle = T.held; nc.lineWidth = 1.4; nc.setLineDash([3, 3]);
      nc.beginPath();
      nc.moveTo(x25Start, yA1); nc.lineTo(x25End, yMidCut - 2);
      nc.moveTo(x25Start, yB0); nc.lineTo(x25End, yMidCut + 2);
      nc.stroke(); nc.setLineDash([]);
    }
  }
  // Label the two 25% broadcast waves and the 50% confirmation check in the dedicated footer strip below Node 7
  drawPill(x25Start - 6, ny0 + nph + 22, "▲ @25%: Simplex + Avail votes sent", T.tsq, T.tsq, "left");
  drawPill(ZX(t0 + run.deadlines[1]) - 6, ny0 + nph + 22, "▲ @50%: Freeze avail votes (D)", T.g1, T.g1, "left");

  // Draw per-node markers & plain-English state badges at 25%, 50%, 75%
  // Each column is 225px wide, so every pill is kept <= 205px wide to stay strictly inside its own column!
  const ns = run.states[s - 1][1];
  const prevNs = s > 1 ? run.states[s - 2][1] : null;
  const x25 = ZX(t0 + run.deadlines[0]);
  const x50 = ZX(t0 + run.deadlines[1]);
  const x75 = ZX(t0 + run.deadlines[2]);

  for (let n = 0; n < cfg.nodes; n++) {
    const y = NY(n), nst = ns[n], pnst = prevNs ? prevNs[n] : null;
    const isRepNode = (n === 0) || (cut && n === cfg.split);

    // 25% (+1.5s): Green + Purple twin dots = Broadcasts Simplex finality vote (green) + Goldfish availability vote (purple)
    nc.fillStyle = T.tsq;
    nc.beginPath(); nc.arc(x25 - 2.5, y, 3.8, 0, 7); nc.fill();
    nc.fillStyle = T.g1;
    nc.beginPath(); nc.arc(x25 + 2.5, y, 3.8, 0, 7); nc.fill();
    if (isRb) {
      const stSlot = nst[4], stSrc = nst[9];
      const bCol = stSrc === "G1" ? T.g1 : (stSrc === "FLOOR" ? T.held : T.tsq);
      const srcWord = stSrc === "G1" ? "G1 Fallback!" : (stSrc === "FLOOR" ? "Floor: <2/3 stake" : "TSQ ≥2/3 lock");
      if (isRepNode) {
        drawPill(x25 + 8, y - 6, `Stable=#${stSlot} (${srcWord})`, bCol, bCol, "left");
      }
    } else if (isRepNode) {
      let nodeVote = "";
      run.msgs.forEach(([t, at, src, dst, k, held, mslot, voteIdx]) => {
        if (mslot === s && src === n && k === 1 && voteIdx >= 0 && !nodeVote) {
          nodeVote = run.votes[voteIdx];
        }
      });
      if (nodeVote) {
        drawPill(x25 + 8, y - 6, `Simplex: ${nodeVote} + Avail`, T.tsq, null, "left");
      }
    }

    // 50% (+3.0s): Open purple ring = Confirmation cutoff (freeze_available_votes -> updates Safe & Head)
    nc.fillStyle = T.panel; nc.strokeStyle = T.g1; nc.lineWidth = 2;
    nc.beginPath(); nc.arc(x50, y, 4.0, 0, 7); nc.fill(); nc.stroke();
    const headChanged = pnst && nst[0] < pnst[0];
    const safeDrop = pnst && nst[2] < pnst[2];
    if (isRepNode && (headChanged || safeDrop)) {
      const reorgTxt = headChanged
        ? `REORG: Head #${pnst[0]}→#${nst[0]} · Safe=#${nst[2]}`
        : `G0 Veto: Safe #${pnst[2]}→#${nst[2]} · Head=#${nst[0]}`;
      drawPill(x50 + 6, y - 6, reorgTxt, T.held, T.held, "left");
    } else {
      nc.fillStyle = T.fg; nc.font = "10px " + css("--mono"); nc.textAlign = "left";
      nc.fillText(`Head=#${nst[0]} · Safe=#${nst[2]}`, x50 + 6, y + 3);
    }

    // 75% (+4.5s): Black square = Incoming vote cutoff (and on round end: Freeze Round Vote Snapshot inside [75%, 100%] column!)
    nc.fillStyle = T.fg;
    const sqSize = isLastInRound ? 8 : 5.5;
    nc.fillRect(x75 - sqSize / 2, y - sqSize / 2, sqSize, sqSize);
    if (isLastInRound && isRepNode) {
      drawPill(x75 + 7, y - 6, `Freezes Round r${rIdx} Votes`, T.fg, T.gs, "left");
    } else if (!isLastInRound && isRepNode) {
      nc.fillStyle = T.muted; nc.font = "9.5px " + css("--mono"); nc.textAlign = "left";
      nc.fillText("Buffers votes (+4.5s)", x75 + 7, y + 3);
    }
  }
}

function renderSweep() {
  if (!SWEEP.length) return;
  renderTiming();
  const SWEEP_ALL = SWEEP;
  const SWEEP_BASE = SWEEP_ALL.filter(r => (r.start ?? 24) === 24);
  const W = 1120, H = 340;
  const c = setup($("sweepCanvas"), W, H);
  const T = {
    a: css("--a"), held: css("--held"), fg: css("--fg"), muted: css("--muted"),
    subtle: css("--subtle"), grid: css("--grid"), gs: css("--gridStrong"), bg: css("--bg"), panel: css("--panel")
  };
  const Ds = [8, 16, 32];
  const panels = [
    ["A. Max Reorg Depth (Blocks)", "max_reorg", 20, true],
    ["B. Orphaned Safe-Confirmed Blocks", "orphaned_safe", 20, true],
    ["C. Delay of First Finality (Slots)", "finality_delay", 36, false],
  ];
  const pw = 310, ph = 230, y0 = 42, lefts = [48, 418, 788];

  panels.forEach(([title, key, ymax, showTheory], idx) => {
    const x0 = lefts[idx];
    const X = d => x0 + 28 + ((d - 8) / (32 - 8)) * (pw - 56);
    const Y = v => y0 + ph - 18 - (v / ymax) * (ph - 36);

    c.fillStyle = T.fg; c.font = "600 13.5px " + css("--sans"); c.textAlign = "left";
    c.fillText(title, x0 - 6, y0 - 12);
    c.fillStyle = T.bg; c.strokeStyle = T.gs; c.lineWidth = 1;
    c.fillRect(x0, y0, pw, ph); c.strokeRect(x0, y0, pw, ph);

    const step = ymax <= 20 ? 4 : 8;
    c.font = "11px " + css("--mono");
    for (let v = 0; v <= ymax; v += step) {
      c.strokeStyle = T.grid; c.beginPath(); c.moveTo(x0, Y(v)); c.lineTo(x0 + pw, Y(v)); c.stroke();
      c.fillStyle = T.muted; c.textAlign = "right"; c.fillText(v, x0 - 6, Y(v) + 4);
    }
    Ds.forEach(d => {
      c.strokeStyle = T.grid; c.beginPath(); c.moveTo(X(d), y0); c.lineTo(X(d), y0 + ph); c.stroke();
      c.fillStyle = T.muted; c.textAlign = "center"; c.fillText(`D=${d} (${d / 8}r)`, X(d), y0 + ph + 18);
    });

    if (showTheory) {
      c.strokeStyle = T.subtle; c.setLineDash([4, 3]); c.lineWidth = 1.2;
      c.beginPath(); c.moveTo(X(8), Y(4)); c.lineTo(X(32), Y(16)); c.stroke();
      c.beginPath(); c.moveTo(X(8), Y(2)); c.lineTo(X(32), Y(8)); c.stroke();
      c.setLineDash([]);
    }

    [["50/50", T.held, -6], ["75/25", T.a, 6]].forEach(([split, col, ox]) => {
      const means = [];
      Ds.forEach(d => {
        const vals = SWEEP_BASE.filter(r => r.split === split && r.D === d).map(r => r[key]).filter(v => v !== null);
        if (!vals.length) return;
        const lo = Math.min(...vals), hi = Math.max(...vals), mean = vals.reduce((a, b) => a + b, 0) / vals.length;
        const xx = X(d) + ox;
        means.push([xx, Y(mean), mean, lo, hi]);
        if (lo !== hi) {
          c.strokeStyle = col; c.globalAlpha = 0.55; c.lineWidth = 1.8;
          c.beginPath(); c.moveTo(xx, Y(lo)); c.lineTo(xx, Y(hi)); c.stroke();
          c.globalAlpha = 1;
        }
        vals.forEach((v, si) => {
          c.fillStyle = col; c.globalAlpha = 0.45;
          c.beginPath(); c.arc(xx + (si - 2) * 2.2, Y(v), 3, 0, 7); c.fill();
          c.globalAlpha = 1;
        });
      });
      c.strokeStyle = col; c.lineWidth = 2.2;
      c.beginPath(); means.forEach(([mx, my], i) => i ? c.lineTo(mx, my) : c.moveTo(mx, my)); c.stroke();
      means.forEach(([mx, my, mean, lo, hi]) => {
        c.fillStyle = col; c.beginPath(); c.arc(mx, my, 4.2, 0, 7); c.fill();
        c.font = "600 11px " + css("--mono"); c.textAlign = "center";
        c.fillText(lo === hi ? `${mean}` : mean.toFixed(1), mx, my - 8);
      });
    });
  });

  // Build HTML summary table
  const fmt = vals => {
    const lo = Math.min(...vals), hi = Math.max(...vals), m = vals.reduce((a, b) => a + b, 0) / vals.length;
    return lo === hi ? `${m.toFixed(1)}` : `${m.toFixed(1)} [${lo}–${hi}]`;
  };
  let rowsHtml = "";
  [["50/50", 8], ["50/50", 16], ["50/50", 32], ["75/25", 8], ["75/25", 16], ["75/25", 32]].forEach(([sp, d]) => {
    const rs = SWEEP_BASE.filter(r => r.split === sp && r.D === d);
    if (!rs.length) return;
    rowsHtml += `<tr>
      <td><b>${sp}</b></td><td>${d} (${d / 8}r)</td><td>${rs.length}</td>
      <td>${fmt(rs.map(r => r.max_reorg))}</td>
      <td>${fmt(rs.map(r => r.orphaned_safe))}</td>
      <td>${fmt(rs.map(r => r.maj_orphaned_safe))}</td>
      <td>${fmt(rs.map(r => r.reconverge))} slot</td>
      <td>${fmt(rs.map(r => r.finality_delay))}</td>
      <td>${fmt(rs.map(r => r.rounds_with_g1))}</td>
      <td>${fmt(rs.map(r => r.rounds_conflicting))}</td>
    </tr>`;
  });
  $("sweepTableWrap").innerHTML = `<table class="summary">
    <thead><tr>
      <th>Split</th><th>Cut D</th><th>Seeds</th><th>Max reorg (blocks)</th>
      <th>Orphaned safe (losing side)</th><th>Orphaned safe (majority)</th>
      <th>Reconverge</th><th>Finality delay (s16)</th><th>Rounds using G1</th><th>Conflicting stable roots</th>
    </tr></thead>
    <tbody>${rowsHtml}</tbody>
  </table>`;
}

function drawSeedPanels(c, rows, xKeys, xLabel, groupKey, panels, T, opts) {
  const pw = 310, ph = 230, y0 = 42, lefts = [48, 418, 788];
  panels.forEach(([title, key, ymax], idx) => {
    const x0 = lefts[idx], n = xKeys.length;
    const X = i => x0 + 34 + (n === 1 ? (pw - 68) / 2 : i * (pw - 68) / (n - 1));
    const Y = v => y0 + ph - 18 - (Math.min(v, ymax) / ymax) * (ph - 36);
    c.fillStyle = T.fg; c.font = "600 13.5px " + css("--sans"); c.textAlign = "left"; c.fillText(title, x0 - 6, y0 - 12);
    c.fillStyle = T.bg; c.strokeStyle = T.gs; c.lineWidth = 1; c.fillRect(x0, y0, pw, ph); c.strokeRect(x0, y0, pw, ph);
    c.font = "11px " + css("--mono");
    const step = ymax <= 20 ? 4 : 8;
    for (let v = 0; v <= ymax; v += step) { c.strokeStyle = T.grid; c.beginPath(); c.moveTo(x0, Y(v)); c.lineTo(x0 + pw, Y(v)); c.stroke(); c.fillStyle = T.muted; c.textAlign = "right"; c.fillText(v, x0 - 6, Y(v) + 4); }
    xKeys.forEach((k, i) => { c.strokeStyle = T.grid; c.beginPath(); c.moveTo(X(i), y0); c.lineTo(X(i), y0 + ph); c.stroke(); c.fillStyle = T.muted; c.textAlign = "center"; c.fillText(xLabel(k), X(i), y0 + ph + 18); });
    opts.series.forEach(([g, col, ox]) => {
      const means = [];
      xKeys.forEach((k, i) => {
        const vals = rows.filter(r => r[groupKey] === g && opts.match(r, k)).map(r => r[key]).filter(v => v !== null && v !== undefined);
        if (!vals.length) return;
        const lo = Math.min(...vals), hi = Math.max(...vals), mean = vals.reduce((a, b) => a + b, 0) / vals.length, xx = X(i) + ox;
        means.push([xx, Y(mean), mean, lo, hi]);
        if (lo !== hi) { c.strokeStyle = col; c.globalAlpha = 0.55; c.lineWidth = 1.8; c.beginPath(); c.moveTo(xx, Y(lo)); c.lineTo(xx, Y(hi)); c.stroke(); c.globalAlpha = 1; }
        vals.forEach((v, si) => { c.fillStyle = col; c.globalAlpha = 0.45; c.beginPath(); c.arc(xx + (si - (vals.length - 1) / 2) * 2.2, Y(v), 3, 0, 7); c.fill(); c.globalAlpha = 1; });
      });
      c.strokeStyle = col; c.lineWidth = 2.2; c.beginPath(); means.forEach(([mx, my], i) => i ? c.lineTo(mx, my) : c.moveTo(mx, my)); c.stroke();
      means.forEach(([mx, my, mean, lo, hi]) => { c.fillStyle = col; c.beginPath(); c.arc(mx, my, 4.2, 0, 7); c.fill(); c.font = "600 11px " + css("--mono"); c.textAlign = "center"; c.fillText(lo === hi ? `${mean}` : mean.toFixed(1), mx, my - 8); });
    });
  });
}

function renderTiming() {
  const rows = SWEEP.filter(r => r.D === 16);
  const starts = [...new Set(rows.map(r => r.start ?? 24))].sort((a, b) => a - b);
  if (starts.length < 2) { $("timingPanel").hidden = true; return; }
  $("timingPanel").hidden = false;
  const T = { held: css("--held"), a: css("--a"), fg: css("--fg"), muted: css("--muted"), grid: css("--grid"), gs: css("--gridStrong"), bg: css("--bg") };
  const c = setup($("timingCanvas"), 1120, 330);
  drawSeedPanels(c, rows, starts, s => `slot ${s} (+${s % 8})`, "split", [
    ["A. Max Reorg Depth (Blocks)", "max_reorg", 16],
    ["B. Orphaned Safe-Confirmed Blocks", "orphaned_safe", 16],
    ["C. Delay of First Finality (Slots)", "finality_delay", 32],
  ], T, { series: [["50/50", T.held, -6], ["75/25", T.a, 6]], match: (r, k) => (r.start ?? 24) === k });
  const fmt = vals => { vals = vals.filter(v => v !== null); if (!vals.length) return "–"; const lo = Math.min(...vals), hi = Math.max(...vals), m = vals.reduce((a, b) => a + b, 0) / vals.length; return lo === hi ? m.toFixed(1) : `${m.toFixed(1)} [${lo}–${hi}]`; };
  let body = "";
  ["50/50", "75/25"].forEach(sp => starts.forEach(st => {
    const rs = rows.filter(r => r.split === sp && (r.start ?? 24) === st);
    if (!rs.length) return;
    body += `<tr><td><b>${sp}</b></td><td>${st} (+${st % 8})</td><td>${rs.length}</td><td>${fmt(rs.map(r => r.max_reorg))}</td><td>${fmt(rs.map(r => r.orphaned_safe))}</td><td>${fmt(rs.map(r => r.reconverge))} slot</td><td>${fmt(rs.map(r => r.finality_delay))}</td><td>${fmt(rs.map(r => r.rounds_nested))}</td><td>${fmt(rs.map(r => r.rounds_conflicting))}</td></tr>`;
  }));
  $("timingTableWrap").innerHTML = `<table class="summary"><thead><tr><th>Split</th><th>Cut starts at</th><th>Seeds</th><th>Max reorg (blocks)</th><th>Orphaned safe</th><th>Reconverge</th><th>Finality delay (s16)</th><th>Rounds nested roots</th><th>Conflicting stable roots</th></tr></thead><tbody>${body}</tbody></table>`;
}

function renderSettlements(run) {
  const st = run.settlements;
  if (!st || !st.rows.length) { $("settlePanel").hidden = true; return; }
  $("settlePanel").hidden = false;
  const T = { a: css("--a"), tsq: css("--tsq"), held: css("--held"), fg: css("--fg"), muted: css("--muted"), grid: css("--grid"), gs: css("--gridStrong") };
  const rows = st.rows, q = st.quorum, maxV = run.cfg.validators;
  const W = Math.max(900, rows.length * 46 + 120), H = 300, L = 56, R = 20, top = 20, bot = 230;
  const c = setup($("settleCanvas"), W, H);
  const X = i => L + (i + 0.5) * (W - L - R) / rows.length, Y = v => bot - (v / maxV) * (bot - top), bw = Math.min(14, (W - L - R) / rows.length / 3);
  c.font = "11px " + css("--mono");
  for (let v = 0; v <= maxV; v += 16) { c.strokeStyle = T.grid; c.lineWidth = 1; c.beginPath(); c.moveTo(L, Y(v)); c.lineTo(W - R, Y(v)); c.stroke(); c.fillStyle = T.muted; c.textAlign = "right"; c.fillText(v, L - 6, Y(v) + 4); }
  c.strokeStyle = T.fg; c.setLineDash([5, 4]); c.lineWidth = 1.2; c.beginPath(); c.moveTo(L, Y(q)); c.lineTo(W - R, Y(q)); c.stroke(); c.setLineDash([]);
  c.fillStyle = T.fg; c.textAlign = "left"; c.fillText(`quorum ${q}`, W - R - 70, Y(q) - 5);
  rows.forEach(([slot, h, tv, fv, to, prog, block, just, fin], i) => {
    const x = X(i);
    c.fillStyle = T.a; c.fillRect(x - bw - 1, Y(tv), bw, bot - Y(tv));
    c.fillStyle = T.tsq; c.fillRect(x + 1, Y(fv), bw, bot - Y(fv));
    c.fillStyle = T.muted; c.textAlign = "center"; c.fillText(slot, x, bot + 16);
    c.fillStyle = prog ? T.fg : T.held; c.font = "600 11px " + css("--mono");
    c.fillText(just ? (fin ? "J+F" : "J") : (fin ? "F" : "–"), x, bot + 32); c.font = "11px " + css("--mono");
    if (!block) { c.fillStyle = T.held; c.beginPath(); c.moveTo(x, bot + 40); c.lineTo(x - 6, bot + 51); c.lineTo(x + 6, bot + 51); c.closePath(); c.fill(); }
  });
  c.fillStyle = T.muted; c.textAlign = "left"; c.fillText("round boundary slot →", L, H - 6);
}

function render() {
  if (cur === SWEEP_TAB) {
    $("singleView").style.display = "none";
    $("sweepView").style.display = "grid";
    renderSweep();
  } else {
    $("singleView").style.display = "grid";
    $("sweepView").style.display = "none";
    renderSingle();
    renderSettlements(RUNS[cur]);
  }
}

function pick(name) {
  cur = name;
  [...$("tabs").children].forEach(b => b.setAttribute("aria-pressed", b.textContent === name));
  render();
}

allTabs.forEach(n => {
  const b = document.createElement("button");
  b.textContent = n; b.type = "button"; b.onclick = () => pick(n);
  $("tabs").appendChild(b);
});

[...$("winSizeTabs").querySelectorAll("button")].forEach(b => {
  b.onclick = () => {
    const newSize = +b.dataset.wsize;
    // Keep window centered around current midpoint (or slot 24 if coming from 64)
    if (winSize === 64 && newSize < 64) {
      winStart = Math.max(1, 24 - Math.floor(newSize / 4));
    }
    winSize = newSize;
    [...$("winSizeTabs").querySelectorAll("button")].forEach(x => x.setAttribute("aria-pressed", x === b));
    renderSingle();
  };
});

$("winPrevBtn").onclick = () => { winStart -= Math.max(1, Math.floor(winSize / 2)); renderSingle(); };
$("winNextBtn").onclick = () => { winStart += Math.max(1, Math.floor(winSize / 2)); renderSingle(); };
$("winSlider").oninput = e => { winStart = +e.target.value; renderSingle(); };

[...$("winJumpTabs").querySelectorAll("button")].forEach(b => {
  b.onclick = () => {
    const target = +b.dataset.jump;
    if (winSize === 64) {
      winSize = 8;
      [...$("winSizeTabs").querySelectorAll("button")].forEach(x => x.setAttribute("aria-pressed", +x.dataset.wsize === 8));
    }
    winStart = target;
    renderSingle();
  };
});

// Allow scrolling/dragging directly on Panel 1 canvas to pan the slot window, or click to select slot in Section 3
let dragStartX = null, dragStartSlot = null, dragMoved = false;
$("prog").addEventListener("mousedown", e => {
  dragStartX = e.clientX;
  dragStartSlot = winStart;
  dragMoved = false;
  if (winSize < 64) $("prog").style.cursor = "grabbing";
});
window.addEventListener("mousemove", e => {
  if (dragStartX === null) return;
  if (Math.abs(e.clientX - dragStartX) > 4) dragMoved = true;
  if (winSize >= 64) return;
  const rect = $("prog").getBoundingClientRect();
  const dx = e.clientX - dragStartX;
  const slotsPerPx = winSize / Math.max(200, rect.width - 94);
  winStart = dragStartSlot - Math.round(dx * slotsPerPx);
  renderSingle();
});
window.addEventListener("mouseup", e => {
  if (dragStartX !== null && !dragMoved) {
    const run = RUNS[cur];
    if (run) {
      const maxSlot = run.states.length;
      const rect = $("prog").getBoundingClientRect();
      const clickX = (e.clientX - rect.left) * (1120 / rect.width);
      const sFrom = winStart, sTo = Math.min(maxSlot, winStart + winSize - 1);
      const xMinSlot = winSize === 1 ? Math.max(1, sFrom - 0.85) : sFrom;
      const xMaxSlot = winSize === 1 ? Math.min(maxSlot + 0.5, sFrom + 0.65) : (sTo + (winSize < maxSlot ? 0.35 : 0));
      const clickedSlot = Math.round(xMinSlot + ((clickX - 58) / (1120 - 58 - 48)) * (xMaxSlot - xMinSlot));
      if (clickedSlot >= 1 && clickedSlot <= maxSlot) {
        zoomSlot = clickedSlot;
        renderSingle();
      }
    }
  }
  dragStartX = null;
  $("prog").style.cursor = "grab";
});
$("prog").addEventListener("wheel", e => {
  if (winSize >= 64) return;
  if (Math.abs(e.deltaX) > Math.abs(e.deltaY) || e.shiftKey) {
    e.preventDefault();
    const delta = Math.sign(e.deltaX || e.deltaY);
    winStart += delta;
    renderSingle();
  }
}, { passive: false });

[...$("progMode").querySelectorAll("button")].forEach(b => {
  b.onclick = () => {
    progMode = b.dataset.mode;
    [...$("progMode").querySelectorAll("button")].forEach(x => x.setAttribute("aria-pressed", x === b));
    renderSingle();
  };
});

[...$("msgModeTabs").querySelectorAll("button")].forEach(b => {
  b.onclick = () => {
    msgMode = b.dataset.msgmode;
    [...$("msgModeTabs").querySelectorAll("button")].forEach(x => x.setAttribute("aria-pressed", x === b));
    renderSingle();
  };
});

[...$("zoomTabs").querySelectorAll("button")].forEach(b => {
  b.onclick = () => {
    zoomSlot = +b.dataset.slot;
    renderSingle();
  };
});
$("sPrevBtn").onclick = () => { zoomSlot = Math.max(1, zoomSlot - 1); renderSingle(); };
$("sNextBtn").onclick = () => { zoomSlot = zoomSlot + 1; renderSingle(); };
$("sSlider").oninput = e => { zoomSlot = +e.target.value; renderSingle(); };

window.addEventListener("keydown", e => {
  if (cur === SWEEP_TAB) return;
  if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
  if (e.key === "ArrowLeft") { e.preventDefault(); zoomSlot = Math.max(1, zoomSlot - 1); renderSingle(); }
  if (e.key === "ArrowRight") { e.preventDefault(); zoomSlot = zoomSlot + 1; renderSingle(); }
});

window.addEventListener("resize", render);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
pick(allTabs[0]);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        args, sweep = sys.argv[2:], None
        if "--sweep-dir" in args:
            i = args.index("--sweep-dir")
            sweep = args[i + 1]
            args = args[:i] + args[i + 2:]
        main(sys.argv[1], args, sweep)
    else:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "figs")
        main(
            os.path.join(base, "partition-explorer.html"),
            [
                f"50/50 split={os.path.join(base, 'split50.json')}",
                f"75/25 split={os.path.join(base, 'split75.json')}",
                f"Honest={os.path.join(base, 'honest.json')}",
            ],
        )
