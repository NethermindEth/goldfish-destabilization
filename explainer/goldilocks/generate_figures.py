#!/usr/bin/env python3
"""Figures for the Goldilocks textbook: concept diagrams + plots from the simulator.

Standard library only. The data figures re-run the scenarios they show through
simulator/goldilocks/partition_run.py (each takes well under a second), so the book rebuilds from
committed code alone:  python3 generate_figures.py && typst compile main.typ
"""
import contextlib
import io
import json
import sys
import tempfile
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "figures"
SIM = ROOT.parent.parent / "simulator" / "goldilocks"
OUT.mkdir(exist_ok=True)

# Mechanism colours, shared with the text (style.typ): Goldfish, lock, FG, proposer, danger
G, L, F, P, R, K, GR = "#1f7a6d", "#b07d00", "#1d5f9e", "#c4661f", "#b03a2e", "#333333", "#777777"
BG = {G: "#e9f3f0", L: "#fbf3df", F: "#eaf1f8", P: "#fbefe6", R: "#faeeeb", GR: "#f3f3f3", K: "#eeeeee"}


class Fig:
    def __init__(self, name, title, h=330, w=760):
        self.name, self.title, self.h, self.w = name, title, h, w
        self.s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
                  f'aria-label="{escape(title)}">', f"<title>{escape(title)}</title>",
                  f'<rect width="{w}" height="{h}" fill="white"/>', "<defs>"]
        for c in [G, L, F, P, R, K, GR]:
            self.s.append(f'<marker id="a{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
                          f'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{c}"/></marker>')
        self.s.append('</defs><g font-family="DejaVu Sans, sans-serif" fill="#333333" font-size="15">')

    def text(self, x, y, s, color=K, size=15, bold=False, anchor="start"):
        for i, line in enumerate(str(s).split("\n")):
            self.s.append(f'<text x="{x}" y="{y + i * (size + 5)}" text-anchor="{anchor}" font-size="{size}" fill="{color}"'
                          + (' font-weight="bold"' if bold else "") + f">{escape(line)}</text>")

    def rect(self, x, y, w, h, c=G, fill=None, dash=False, rx=3, sw=1.5):
        self.s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill or BG.get(c, "white")}" '
                      f'stroke="{c}" stroke-width="{sw}"' + (' stroke-dasharray="6 4"' if dash else "") + "/>")

    def line(self, x, y, x2, y2, c=GR, arrow=True, dash=False, sw=2):
        self.s.append(f'<path d="M{x} {y} L{x2} {y2}" fill="none" stroke="{c}" stroke-width="{sw}"'
                      + (f' marker-end="url(#a{c[1:]})"' if arrow else "") + (' stroke-dasharray="6 4"' if dash else "") + "/>")

    def path(self, d, c=GR, arrow=False, dash=False, sw=2, fill="none", opacity=1):
        self.s.append(f'<path d="{d}" fill="{fill}" stroke="{c}" stroke-width="{sw}" opacity="{opacity}"'
                      + (f' marker-end="url(#a{c[1:]})"' if arrow else "") + (' stroke-dasharray="6 4"' if dash else "") + "/>")

    def block(self, x, y, label, c=K, dash=False, fill="white", w=40, h=30):
        self.rect(x - w / 2, y - h / 2, w, h, c, fill=fill, dash=dash)
        self.text(x, y + 5, label, c, 13, True, "middle")

    def dot(self, x, y, c=G, r=5, fill=None):
        self.s.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill or c}" stroke="{c}" stroke-width="1.5"/>')

    def save(self):
        (OUT / (self.name + ".svg")).write_text("\n".join(self.s + ["</g></svg>"]))


def edge(f, x1, y1, x2, y2, c=GR):
    """Child-to-parent arrow (points at the parent, as in the slides)."""
    f.line(x2 - 20, y2, x1 + 20, y1, c) if y1 == y2 else f.path(f"M{x2-20} {y2} C{x2-40} {y2} {x1+40} {y1} {x1+20} {y1}", c, arrow=True)


# ------------------------------------------------------------------ concept figures

def fig_architecture():
    f = Fig("architecture", "The three parts of a Goldilocks node", 400)
    f.rect(20, 20, 720, 70, GR)
    f.text(40, 48, "Node", K, 16, True)
    f.text(40, 72, "keeps the clock and both states; runs on_tick, on_block, on_ac_message, on_attestation; duties", GR, 13)
    f.rect(20, 130, 300, 150, F)
    f.text(36, 156, "Finality gadget (FG)", F, 16, True)
    f.text(36, 182, "state Σ: block tree T, chain states σ[B],", K, 13)
    f.text(36, 200, "F, J, h_j, h_max, attestation pool", K, 13)
    f.text(36, 226, "accepts blocks, justifies and finalizes,", K, 13)
    f.text(36, 244, "owns the validator client (record Λ)", K, 13)
    f.rect(440, 130, 300, 150, G)
    f.text(456, 156, "Available chain (AC): Goldilocks", G, 16, True)
    f.text(456, 182, "state A: Goldfish votes, timestamps,", K, 13)
    f.text(456, 200, "saved confirmations, locks, record", K, 13)
    f.text(456, 226, "head, confirmation, locks; no block store:", K, 13)
    f.text(456, 244, "sees blocks only through the frame Φ", K, 13)
    f.line(320, 175, 440, 175, F)
    f.text(380, 166, "Φ = (tree, fc_root, viable_heads)", F, 12, False, "middle")
    f.line(440, 235, 320, 235, G)
    f.text(380, 255, "(fg_confirmed, head)", G, 12, False, "middle")
    f.line(170, 90, 170, 130, GR)
    f.line(590, 90, 590, 130, GR)
    # three tips
    y = 340
    xs = [60, 140, 220, 300, 380, 460, 540, 620, 700]
    for i, x in enumerate(xs):
        c = F if i <= 2 else (L if i <= 6 else G)
        f.block(x, y, "", c, fill=BG[c], w=34, h=26)
        if i:
            f.line(x - 17, y, xs[i - 1] + 17, y, GR)
    f.text(140, y + 38, "finalized tip Σ.F (FG)", F, 13, True, "middle")
    f.text(540, y + 38, "confirmed tip, locked (AC)", L, 13, True, "middle")
    f.text(700, y + 38, "head (AC)", G, 13, True, "middle")
    f.save()


def fig_slot_timeline():
    f = Fig("slot-timeline", "The public actions of slot s and how they overlap slot s+1", 300)
    x0, u = 40, 85  # u = pixels per Δ
    for s in range(2):
        f.rect(x0 + 4 * u * s, 30, 4 * u, 34, GR, fill="#f6f6f6")
        f.text(x0 + 4 * u * s + 2 * u, 53, ["slot s", "slot s+1"][s], K, 14, True, "middle")
    for i in range(9):
        x = x0 + i * u
        f.line(x, 64, x, 260, "#cccccc", arrow=False, sw=1)
        f.text(x, 280, ["t(s)", "+Δ", "+2Δ", "+3Δ", "t(s+1)", "+5Δ", "+6Δ", "+7Δ", "t(s+2)"][i], GR, 12, False, "middle")
    rows = [
        (0, "proposal of slot s (parent = head; carries slot s−1 votes)", P),
        (1, "Goldfish vote of slot s (after unlocking vs slot s−1 votes)", G),
        (2, "support cutoff: slot-s votes resolved before it count", G),
        (3, "view freeze: slot-s votes received before it feed the vote of s+1", G),
        (5, "unlocking against slot-s votes (= vote time of s+1)", L),
        (6, "confirmation update of slot s: result, fast/slow lock (= cutoff of s+1)", L),
    ]
    for j, (d, label, c) in enumerate(rows):
        y = 88 + j * 28
        x = x0 + d * u
        f.dot(x, y, c, 6)
        if d >= 4:  # late actions: label to the left so it stays inside the figure
            f.rect(x - 12 - 6.6 * len(label), y - 11, 6.6 * len(label) + 4, 21, GR, fill="white", sw=0)
            f.text(x - 12, y + 5, label, c, 12.5, False, "end")
        else:
            f.rect(x + 8, y - 11, 6.6 * len(label) + 4, 21, GR, fill="white", sw=0)
            f.text(x + 12, y + 5, label, c, 12.5)
    f.save()


def fig_locks():
    f = Fig("locks", "Two ways to lock", 300)
    f.text(20, 26, "Fast: half of one committee", L, 15, True)
    f.block(70, 150, "A", K)
    f.block(190, 150, "B", L, fill=BG[L])
    f.line(170, 150, 90, 150)
    for i in range(8):
        f.dot(240 + (i % 4) * 22, 110 + (i // 4) * 22, G if i < 5 else GR, 7, fill=BG[G] if i < 5 else "white")
    f.text(240, 175, "≥ n/2 of the committee", G, 12)
    f.text(240, 192, "voted for B (resolved early)", G, 12)
    f.text(20, 240, "The confirmation update of slot s sees at", K, 12)
    f.text(20, 258, "least n/2 of the whole committee on B: lock B.", K, 12)
    f.text(410, 26, "Slow: k confirmations in a row", L, 15, True)
    for i in range(4):
        x = 440 + i * 80
        f.text(x + 20, 60, f"slot s−{3-i}" if i < 3 else "slot s", GR, 12, False, "middle")
        f.block(x + 20, 150, "", G if i else L, fill=BG[L] if i == 0 else "white", w=32, h=24)
        if i:
            f.line(x + 4, 150, x - 44, 150)
        f.dot(x + 20, 100, G, 5)
        f.path(f"M{x+20} 105 L{x+20} 136", G, arrow=False, dash=True, sw=1.5)
    f.text(460, 186, "B", L, 13, True, "middle")
    f.text(410, 222, "Few voters are awake: no slot has n/2 on B,", K, 12)
    f.text(410, 240, "but each of the last k confirmation updates", K, 12)
    f.text(410, 258, "saved a result extending B. Lock B (k = 4).", K, 12)
    f.save()


def fig_unlock():
    f = Fig("unlock", "Two ways to unlock", 300)
    f.text(20, 26, "Fast: half of one committee against", L, 15, True)
    f.block(60, 150, "A", K)
    f.block(170, 110, "B'", K)
    f.block(270, 110, "B", L, fill=BG[L])
    f.block(170, 200, "C", G)
    f.path("M150 110 C120 110 100 150 80 150", GR, arrow=True)
    f.line(250, 110, 190, 110)
    f.path("M150 200 C120 200 100 150 80 150", GR, arrow=True)
    f.path("M262 92 C230 60 120 60 70 132", L, arrow=True, dash=True)
    f.text(165, 58, "lock steps back to A", L, 12, False, "middle")
    for i in range(5):
        f.dot(215 + i * 18, 232, G, 6, fill=BG[G])
    f.text(215, 262, "≥ n/2 vote for heads conflicting with B, B'", G, 12)
    f.text(20, 290, "At t_s+5Δ every live lock moves back to the deepest ancestor with < n/2 opponents.", K, 12)
    f.text(420, 26, "Slow: expiry after k slots", L, 15, True)
    for i in range(6):
        x = 440 + i * 50
        f.line(x, 150, x, 175, "#cccccc", arrow=False, sw=1)
        f.text(x, 195, ["s", "s+1", "s+2", "s+3", "s+4", "s+5"][i], GR, 12, False, "middle")
    f.rect(465, 120, 200, 22, L)
    f.text(565, 136, "lock on B", L, 12, True, "middle")
    f.line(690, 100, 690, 175, R, arrow=False, dash=True)
    f.text(690, 92, "expires", R, 12, True, "middle")
    f.text(420, 232, "Written by the update of slot s at t_s+6Δ,", K, 12)
    f.text(420, 250, "deadline t_{s+k}+5Δ: gone at the vote of s+k+1", K, 12)
    f.text(420, 268, "unless a later update writes a new lock (here k = 4).", K, 12)
    f.save()


def fig_frame():
    f = Fig("frame", "Fork-choice root and head height floor: the three cases", 270, 780)
    titles = ["1 · no J at h_max−1 yet", "2 · J revealed", "3 · contest"]
    notes = [["root F; floor h_max−1;", "blocks at h_max−1 and h_max viable"],
             ["root J; branches not through J", "drop out of the viable tree"],
             ["a block at h_max not on J:", "root F, floor h_max"]]
    for k in range(3):
        ox = 10 + k * 260
        f.rect(ox, 10, 250, 250, GR, fill="#fbfbfb")
        f.text(ox + 12, 34, titles[k], K, 14, True)
        f.text(ox + 12, 60, "h_max−1", GR, 11)
        f.text(ox + 170, 60, "h_max", GR, 11)
        f.line(ox + 150, 66, ox + 150, 200, "#dddddd", arrow=False, sw=1)
        f.block(ox + 34, 140, "F", F, fill=BG[F], w=34, h=26)
        up = ox + 110, 105
        dn = ox + 110, 175
        f.block(*up, "J" if k else "·", F if k else K, fill=BG[F] if k else "white", w=34, h=26)
        f.block(*dn, "·", K, w=34, h=26)
        f.path(f"M{up[0]-17} {up[1]} C{up[0]-40} {up[1]} {ox+70} 140 {ox+51} 140", GR, arrow=True)
        f.path(f"M{dn[0]-17} {dn[1]} C{dn[0]-40} {dn[1]} {ox+70} 140 {ox+51} 140", GR, arrow=True)
        f.block(ox + 200, 105, "✓", G, w=34, h=26)
        f.line(ox + 183, 105, ox + 127, 105, GR)
        if k == 2:
            f.block(ox + 200, 175, "✓", G, w=34, h=26)
            f.line(ox + 183, 175, ox + 127, 175, GR)
        root = (ox + 34, 140) if k != 1 else up
        f.rect(root[0] - 21, root[1] - 17, 42, 34, R, fill="none", dash=True)
        f.text(ox + 12, 226, notes[k][0], K, 11.5)
        f.text(ox + 12, 243, notes[k][1], K, 11.5)
    f.save()


def fig_heights():
    f = Fig("heights", "Honest steady state of the FG: one height per round", 285, 780)
    x0, u = 40, 26
    for s in range(0, 28):
        x = x0 + s * u
        if s % 8 == 0:
            f.rect(x - u / 2, 30, 8 * u, 24, GR, fill="#f4f4f4")
            f.text(x + 4 * u - u / 2, 47, f"round {s//8}", GR, 12, False, "middle")
        f.line(x, 60, x, 66, "#bbbbbb", arrow=False, sw=1)
        if s % 2 == 0:
            f.text(x, 80, s, GR, 10, False, "middle")
    events = [
        (9.33, 100, F, "a_1: attest (h=1, T=gen)"),
        (10, 125, F, "block 10 includes them: justify gen @1; block 10 = target of h=2"),
        (17.33, 150, F, "a_2: attest (h=2, T=#10) + finality pair (1, gen)"),
        (18, 175, F, "block 18: justify #10 @2 (target of h=3 = #18); finalize gen"),
        (25.33, 200, F, "a_3: attest (3, #18) + finality pair (2, #10)"),
        (26, 225, F, "block 26: justify #18 @3, finalize #10  → F lags the head by ~2 rounds"),
    ]
    for s, y, c, label in events:
        x = x0 + s * u
        f.dot(x, y, c, 5)
        f.line(x, 66, x, y - 6, "#d5dfea", arrow=False, sw=1)
        anchor = "end" if s > 20 else "start"
        f.text(x + (-10 if anchor == "end" else 10), y + 4, label, c, 12, False, anchor)
    f.text(40, 268, "Attestations are cast at the action time a_r = t_{rR}+6Δ (slot rR+1, +2Δ) and included two slots into the round.", GR, 11.5)
    f.save()


def fig_healing():
    f = Fig("healing", "Bad locks drain within 2L after GST", 250, 780)
    xs = {"GST": 120, "GST+L": 360, "GST+2L": 600}
    for k, x in xs.items():
        f.line(x, 40, x, 200, "#bbbbbb", arrow=False, dash=True, sw=1.2)
        f.text(x, 225, k, K, 13, True, "middle")
    f.rect(30, 60, 250, 18, R)
    f.text(36, 74, "B · fast (pre-GST)", R, 11.5, True)
    f.rect(60, 90, 220, 18, R)
    f.text(66, 104, "B′ · fast, conflicts with B", R, 11.5, True)
    f.rect(200, 120, 290, 18, L)
    f.text(206, 134, "C · slow, formed across GST", L, 11.5, True)
    f.rect(380, 150, 260, 18, G)
    f.text(386, 164, "formed fully after GST: followed", G, 11.5, True)
    f.text(130, 32, "1 · no new conflicting locks", K, 12, False, "start")
    f.text(370, 32, "2 · post-GST locks followed", K, 12, False, "start")
    f.text(610, 32, "3 · healed", K, 12, False, "start")
    f.text(30, 245, "L = lock lifetime (k slots). Then the next honest proposal is confirmed by all: AC heals by GST + 2L + G.", GR, 11.5)
    f.save()


# ------------------------------------------------------------------ data figures

def run_scenario(argv):
    sys.path.insert(0, str(SIM))
    import partition_run  # noqa: E402
    import model  # noqa: E402
    # fresh registry per scenario
    model.BLOCKS.clear(); model.DEPTH.clear(); model.ANC.clear(); model.STATE.clear(); model.INCL.clear()
    model.BLOCKS[model.GEN] = model.Block(model.GEN, 0, None, -1)
    model.DEPTH[model.GEN] = 0
    model.ANC[model.GEN] = frozenset([model.GEN])
    model.STATE[model.GEN] = model.ChainState()
    model.INCL[model.GEN] = frozenset()
    with tempfile.TemporaryDirectory() as d:
        ev = Path(d) / "ev.json"
        with contextlib.redirect_stdout(io.StringIO()):
            summary = partition_run.main(argv + ["--quiet", "--events", str(ev)])
        data = json.loads(ev.read_text())
    return data, summary


def lag_plot(name, title, argv, nodes, slots=None, h_panel=120):
    d, S = run_scenario(argv)
    blocks = d["blocks"]
    slot_of = lambda r: 0 if r in (None, "G") else blocks[r][0]
    states = d["states"] if slots is None else [x for x in d["states"] if slots[0] <= x["slot"] <= slots[1]]
    last = d["states"][-1]["nodes"][0]["head"]
    canon = set()
    r = last
    while r not in (None, "G"):
        canon.add(r)
        r = blocks[r][1]
    canon.add("G")
    lo, hi = states[0]["slot"], states[-1]["slot"]
    maxlag = 8
    for x in states:
        for i in nodes:
            st = x["nodes"][i]
            if not st["asleep"]:
                maxlag = max(maxlag, x["slot"] - slot_of(st["F"]), x["slot"] - slot_of(st["conf"]))
    maxlag = -(-maxlag // 8) * 8
    W, L0, R0 = 760, 46, 740
    H = 30 + len(nodes) * (h_panel + 36) + 26
    f = Fig(name, title, H, W)
    X = lambda s: L0 + (R0 - L0) * (s - lo) / max(1, hi - lo)
    slot_ms = d["params"]["slot_ms"]
    # legend
    lx = 46
    for lab, c in [("head", "#2a78d6"), ("confirmed tip", "#eb6834"), ("finalized tip", "#1baf7a")]:
        f.line(lx, 16, lx + 18, 16, c, arrow=False, sw=2.5)
        f.text(lx + 24, 20, lab, K, 12)
        lx += 24 + len(lab) * 7 + 22
    f.dot(lx + 4, 16, "#eda100", 3.5)
    f.text(lx + 12, 20, "live lock", K, 12)
    lx += 90
    f.dot(lx + 4, 16, "#555555", 3.5, fill="white")
    f.text(lx + 12, 20, "hollow: block off the final chain", K, 12)
    for pi, i in enumerate(nodes):
        top = 40 + pi * (h_panel + 36)
        Y = lambda lag: top + h_panel * lag / maxlag
        grp = d["group_of"][str(i)] if str(i) in d["group_of"] else d["group_of"][i]
        f.text(L0, top - 6, f"node {i} · group {chr(65+grp)} · {d['validators'][i]} validators — slots behind the current slot", K, 12, True)
        for a, b, _ in d["windows"]:
            a, b = a // slot_ms, b // slot_ms
            f.rect(X(max(lo, a) - .5), top, X(min(hi, b) - .5) - X(max(lo, a) - .5), h_panel, GR, fill="#ececec", sw=0, rx=0)
        for item in filter(None, (d["config"].get("sleep") or "").split(",")):
            nid, a, b = item.split(":")
            if int(nid) == i:
                a, b = float(a), float(b)
                f.rect(X(max(lo, a) - .5), top, X(min(hi, b) - .5) - X(max(lo, a) - .5), h_panel, "#6250d6", fill="#efedfb", sw=0, rx=0)
        for v in range(0, maxlag + 1, max(1, maxlag // 4)):
            f.line(L0, Y(v), R0, Y(v), "#e6e6e6", arrow=False, sw=1)
            f.text(L0 - 6, Y(v) + 4, v, GR, 10, False, "end")
        if pi == len(nodes) - 1:
            for s in range(lo - lo % 8, hi + 1, 8):
                if s >= lo:
                    f.text(X(s), top + h_panel + 16, s, GR, 10, False, "middle")
        for x in states:
            st = x["nodes"][i]
            if st["asleep"]:
                continue
            for b, _, _ in st["locks"]:
                f.dot(X(x["slot"]), Y(x["slot"] - slot_of(b)), "#eda100", 2.4)
        for key, c in [("F", "#1baf7a"), ("conf", "#eb6834"), ("head", "#2a78d6")]:
            dpath, pen = "", False
            for x in states:
                st = x["nodes"][i]
                if st["asleep"]:
                    pen = False
                    continue
                dpath += ("L" if pen else "M") + f"{X(x['slot']):.1f},{Y(x['slot'] - slot_of(st[key])):.1f}"
                pen = True
            f.path(dpath, c, sw=2)
            for x in states:
                st = x["nodes"][i]
                if not st["asleep"] and st[key] not in canon:
                    f.dot(X(x["slot"]), Y(x["slot"] - slot_of(st[key])), c, 2.8, fill="white")
    f.text(L0, H - 6, "slot", GR, 11)
    f.save()
    return S


def sweep_table():
    """Re-run a reduced sweep (3 seeds) and write a Typst table include."""
    sys.path.insert(0, str(SIM))
    import sweep  # noqa: E402
    rows = []
    for job in [(sh, sp, du, sd) for sh in sweep.SHAPES for du in sweep.DURATIONS for sp in (0, 12000) for sd in range(3)]:
        rows.append(sweep.run_one(job))
    groups = {}
    for r in rows:
        groups.setdefault((r["shape"], r["dur"], r["spread"]), []).append(r)

    def worst(rs, k):
        vals = [r[k] for r in rs]
        if k.endswith("agree") and any(v is None for v in vals):
            return "never"
        vals = [v for v in vals if v is not None]
        return f"{max(vals):+d}" if vals else "—"

    cells = []
    for (shape, dur, spread), rs in groups.items():
        cells += [shape, str(dur), f"{spread // 1000} s", worst(rs, "lock_conflict_after"), worst(rs, "heads_agree"),
                  worst(rs, "conf_agree"), worst(rs, "last_orphaned_conf"), str(max(r["max_reorg"] for r in rs)),
                  "yes" if any(r["fin_conflict"] for r in rs) else "no"]
    body = ", ".join(f"[{c}]" for c in cells)
    (OUT / "sweep-table.typ").write_text(
        "#table(columns: 9, align: (left, right, right, right, right, right, right, right, left),\n"
        "  table.header([shape], [D], [spread], [conflicting\\ locks], [heads\\ agree], [confirmed\\ agree],"
        " [last orphaned\\ confirmation], [max\\ reorg], [finality\\ conflict]),\n  " + body + ")\n")


def main():
    fig_architecture()
    fig_slot_timeline()
    fig_locks()
    fig_unlock()
    fig_frame()
    fig_heights()
    fig_healing()
    base = ["--start", "48", "--slots-down", "16"]
    lag_plot("run-honest", "Honest run", ["--slots-down", "0", "--after", "40"], [0], slots=(0, 40))
    lag_plot("run-p75", "75/25 partition", ["--groups", "3,1"] + base, [0, 3], slots=(36, 88))
    lag_plot("run-p50", "50/50 partition", ["--groups", "2,2"] + base, [0, 2], slots=(36, 88))
    lag_plot("run-p52", "52/48 partition", ["--groups", "2,2", "--shares", "17,16,16,15"] + base, [0, 2], slots=(36, 88))
    lag_plot("run-sleep75", "75% asleep", ["--slots-down", "0", "--sleep", "1:48:64,2:48:64,3:48:64", "--after", "32"],
             [0, 1], slots=(36, 88))
    sweep_table()
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
