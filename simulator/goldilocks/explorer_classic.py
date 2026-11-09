"""The Goldilocks explorer in the old protocol's explorer UI (../goldfish-simplex/make_figures.py).

Same layout, controls and plots as the PR #5 explorer: (1) what each side believed, slot by
slot, (2) the block tree with confirmation reversals, (3) the single-slot deadline and message
anatomy. The data comes from Goldilocks runs (partition_run.py / adversary.py --events) and the
text describes Goldilocks: head, confirmed tip, anchor (deepest lock, fast or slow), FG
justified / finalized; deadlines vote (Δ), support cutoff + confirmation update (2Δ), view
freeze (3Δ). The adversary, when there is one, gets its own row in panel 3.

Usage:
    python explorer_classic.py OUT.html [--meta explorer_meta.json] NAME=run.events.json ...
"""

import json
import sys

KINDS = {"block": 0, "att": 1, "vote": 2}
GEN = "G"


def compact(path, meta=None):
    with open(path) as fh:
        d = json.load(fh)
    P = d["params"]
    slot_ms, delta = P["slot_ms"], P["delta"]
    vals = d["validators"]
    nodes = len(vals)
    group_of = [d["group_of"][str(i)] if str(i) in d["group_of"] else d["group_of"][i] for i in range(nodes)]
    windows = d["windows"]
    start, down = (windows[0][0] // slot_ms, (windows[0][1] - windows[0][0]) // slot_ms) if windows else (0, 0)
    cfg = d["config"]

    blocks = {r: [b[0], b[1] if b[1] != GEN else GEN, b[3], b[2], b[4]] for r, b in d["blocks"].items()}
    bslot = {r: b[0] for r, b in d["blocks"].items()}
    bslot[GEN] = 0

    def sl(r):
        return bslot.get(r, 0) if r else None

    # final chain of node 0 (for "later orphaned" in the event text)
    last = d["states"][-1]["nodes"][0]["head"]
    final, r = set(), last
    while r in blocks:
        final.add(r)
        r = blocks[r][1]

    def name(r):
        if r is None:
            return "⊥"
        return f"#{sl(r)}" + ("" if r == GEN or r in final else "′")

    # lock kinds per node, from the confirmation updates (a lock moved back keeps its kind)
    how = [dict() for _ in range(nodes)]
    events = {}
    for e in d["log"]:
        k, n = e["kind"], e.get("node")
        s = int(e["t"] // slot_ms)
        if k == "confirm":
            if e.get("lock"):
                how[n][e["lock"]] = e.get("how")
            res = e.get("result")
            txt = (f"n{n}: update of slot {e['slot']} → confirmed <b>{name(res)}</b>"
                   + (" <span class='delta-down'>vetoed by a live lock</span>" if e.get("vetoed") else "")
                   + (f" · {e.get('how')} lock on {name(e['lock'])}" if e.get("lock") else "")
                   if res else f"n{n}: update of slot {e['slot']} → no result")
            events.setdefault(s, []).append([s, "confirm", txt])
        elif k == "lock_back":
            how[n][e["to"]] = how[n].get(e["block"])
            events.setdefault(s, []).append([s, "unlock", f"n{n}: lock {name(e['block'])} moved back to {name(e['to'])}"])
        elif k == "fg_pair":
            events.setdefault(s, []).append(
                [s, "fg", f"n{n}: FG source {name(e['fg_confirmed'])}" + ("" if e["fg_confirmed"] else " — no attestation")])

    states, locks = [], {}
    for row in d["states"]:
        s = row["slot"]
        if s == 0:
            continue
        nrow = []
        for i, x in enumerate(row["nodes"]):
            lk = [b for b, _, _ in x["locks"]]
            a = x["anchor"]
            tag = "FLOOR" if (a == x["fc_root"] and a not in lk) else ("G1" if how[i].get(a) == "slow" else "TSQ")
            nrow.append([x["head_slot"], x["head"], x["conf_slot"], x["conf"], x["anchor_slot"], a,
                         x["F_slot"], x["J_slot"], x["head_h"], tag, x["hmax"],
                         [ls for _, ls, _ in x["locks"]], [b for b, _, _ in x["locks"]]])  # 11, 12: every live lock
            locks.setdefault(s, {})[i] = ", ".join(f"{name(b)}→{dl}" for b, _, dl in x["locks"]) or "none"
        states.append([s, nrow])

    votes, msgs, vote_head, adv_groups = [], [], {}, {}
    for m in d["messages"]:
        k = KINDS[m["kind"]]
        s = m.get("slot")
        if s is None:
            s = int(m["t"] // slot_ms)
        vi = -1
        if k == 1:
            desc = f"(h{m['h']}, {name(m['T'])}{', timeout' if m['tau'] else ''})" + \
                   (f" fin (h{m['hf']}, {name(m['Tf'])})" if m.get("hf") is not None else "")
            if desc not in votes:
                votes.append(desc)
            vi = votes.index(desc)
        if k == 2 and m["src"] >= 0 and m["heads"]:
            vote_head.setdefault(s, {})[m["src"]] = sl(m["heads"][0][0])
        msgs.append([m["t"], m["at"], m["src"], m["dst"], k, int(m["held"]), s, vi])
        if m["src"] < 0:  # adversary deliveries, grouped for the labels of panel 3
            ts = int(m["at"] // slot_ms)
            what = (f"block {name(m['root'])} on {name(blocks.get(m['root'], [0, GEN])[1])}" if k == 0 else
                    f"votes for {', '.join(name(h) for h, _ in m['heads'])}" if k == 2 else "attestations")
            g = adv_groups.setdefault((ts, round(m["at"]), what), [0, set()])
            g[0] += 1 if k != 2 else sum(c for _, c in m["heads"])
            g[1].add(m["dst"])
    adv_notes = {}
    for (ts, at, what), (cnt, dsts) in sorted(adv_groups.items()):
        lab = f"{what}{f' ×{cnt // len(dsts)}' if 'votes' in what else ''} → n{','.join(map(str, sorted(dsts)))} @+{(at - ts * slot_ms) / 1000:.3f}s"
        adv_notes.setdefault(ts, []).append([at, lab])
    for ts in adv_notes:  # keep the list readable: blocks first, at most eight
        adv_notes[ts] = sorted(adv_notes[ts], key=lambda x: ("block" not in x[1], x[0]))[:8]
        adv_notes[ts].sort()

    n_all = P["n"]
    return {
        "cfg": {"nodes": nodes, "split": sum(1 for g in group_of if g == 0), "start": start, "slots_down": down,
                "seed": cfg.get("seed"), "latency_ms": cfg.get("latency_ms", 200), "jitter_ms": cfg.get("jitter_ms", 0),
                "validators": n_all, "sides": any(g != 0 for g in group_of)},
        "groupOf": group_of,
        "slotMs": slot_ms,
        "deadlines": [delta, 2 * delta, 3 * delta],
        "spr": P["R"],
        "votes": votes,
        "msgs": msgs,
        "blocks": blocks,
        "states": states,
        "settlements": None,
        "meta": meta,
        "vals": vals,
        "adv": n_all - sum(vals),
        "advNotes": adv_notes,
        "voteHead": vote_head,
        "locks": locks,
        "events": events,
    }


def main(argv):
    meta = {}
    if "--meta" in argv:
        i = argv.index("--meta")
        with open(argv[i + 1]) as fh:
            meta = json.load(fh)
        argv = argv[:i] + argv[i + 2:]
    out, specs = argv[0], argv[1:]
    runs = {}
    for spec in specs:
        name, path = spec.split("=", 1)
        runs[name] = compact(path, meta.get(name))
    payload = {"runs": runs, "sweep": []}
    html = TEMPLATE.replace("/*DATA*/", "const DATA = " + json.dumps(payload, separators=(",", ":")) + ";")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {out} ({len(html) / 1e6:.2f} MB, {len(runs)} runs)")

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Goldilocks — Partition, Healing &amp; Attack Explorer</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<style>
:root {
  --bg: #f4f6f9; --panel: #ffffff; --fg: #0f172a; --muted: #475569; --subtle: #64748b;
  --grid: #e2e8f0; --gridStrong: #cbd5e1;
  --a: #2563eb; --aSoft: rgba(37,99,235,0.12);
  --b: #d97706; --bSoft: rgba(217,119,6,0.14);
  --held: #dc2626; --tint: rgba(220,38,38,0.08);
  --heal: #0d9488; --tsq: #16a34a; --g1: #9333ea;
  --sans: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: var(--sans);
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
body { margin: 0; background: var(--bg); color: var(--fg); font-family: var(--sans); font-size: 14.5px; line-height: 1.5; font-variant-numeric: tabular-nums; }
code { font-family: inherit; }
.wrap { max-width: 1200px; margin: 0 auto; padding: 24px 20px 64px; display: grid; gap: 20px; }
header { display: grid; gap: 6px; }
h1 { font-size: 24px; font-weight: 700; margin: 0; letter-spacing: -0.015em; }
h2 { font-size: 16.5px; font-weight: 600; margin: 0; }
p { margin: 0; }
.lead { color: var(--muted); max-width: 88ch; font-size: 14px; }
.topbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; }
.tabs { display: flex; flex-wrap: wrap; gap: 8px; }
.subtabs { display: inline-flex; flex-wrap: wrap; gap: 4px; }
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
  display: inline-flex; align-items: center; gap: 0; padding: 3px 9px;
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
#settlePanel[hidden] { display: none; }
.about { background: var(--panel); border: 1px solid var(--grid); border-left: 3px solid var(--a); border-radius: 8px;
  padding: 14px 18px; display: grid; gap: 8px; font-size: 14px; line-height: 1.55; }
.about h2 { margin-bottom: 4px; }
.about[hidden] { display: none; }
.about .sec { display: grid; grid-template-columns: 70px 1fr; gap: 12px; }
.about .lab { font-size: 11.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--subtle); padding-top: 2px; }
.about p, .about ul { margin: 0; } .about ul { padding-left: 18px; } .about b { color: var(--fg); }
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
    <h1>Goldilocks — Partition, Healing &amp; Attack Explorer</h1>
    <p class="lead">Seeded runs of our executable model of the Goldilocks spec (FGSA, 22 Oct 2026). Slots of 6 s (&Delta; = 1.5 s), rounds of 8 slots, locks of k = 4 slots, 64 validators of equal stake.</p>
  </header>

  <div class="topbar">
    <div class="tabs" id="tabs" role="group" aria-label="Scenario"></div>
  </div>

  <div id="singleView" style="display:grid;gap:20px">
    <div class="facts" id="facts"></div>
    <div class="about" id="about" hidden></div>

    <section class="panel">
      <div class="panel-head">
        <h2>1. Each node's view, slot by slot</h2>
        <div class="controls">
          <span>Window:</span>
          <div class="subtabs" id="winSizeTabs">
            <button type="button" data-wsize="999" aria-pressed="true">All</button>
            <button type="button" data-wsize="16">16 slots</button>
            <button type="button" data-wsize="8">8 slots</button>
            <button type="button" data-wsize="4">4 slots</button>
            <button type="button" data-wsize="1">1 slot</button>
          </div>
          <span>Y axis:</span>
          <div class="subtabs" id="progMode">
            <button type="button" data-mode="slot" aria-pressed="true">Block (by slot)</button>
            <button type="button" data-mode="lag">Lag (slots behind)</button>
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

      <div class="legend">
        <span><i class="sw" style="background:var(--a);height:3.5px"></i>Side A</span>
        <span><i class="sw" style="background:var(--b);height:3.5px"></i>Side B</span>
        <span><i class="sw" style="border-top:2px dashed #0891b2;height:0"></i><i class="sw" style="border-top:2px dashed #9333ea;height:0"></i>Justified (A, B)</span>
        <span><i class="dot" style="border:2px solid var(--held)"></i>Block later orphaned</span>
        <span><i class="dot" style="width:7px;height:7px;background:var(--a);opacity:0.65"></i><i class="dot" style="width:7px;height:7px;background:var(--b);opacity:0.65"></i>Live locks held in slot (hollow: orphaned)</span>
        <span>Anchor: <i class="dot" style="background:var(--tsq)"></i>fast lock <i class="dia"></i>slow lock <i class="sq"></i>none</span>
      </div>
      <canvas id="prog" style="cursor:grab"></canvas>
      <div class="callouts" id="callouts"></div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>2. Node chains in progress</h2>
        <div class="controls">
          <span>View:</span>
          <div class="subtabs" id="treeViewTabs"></div>
          <span style="margin-left:6px">Phase:</span>
          <div class="subtabs" id="treePhaseTabs">
            <button type="button" data-tphase="end" aria-pressed="true">Slot end</button>
            <button type="button" data-tphase="25">@25% Vote</button>
          </div>
        </div>
      </div>
      <p class="note" id="treeNote">Each node has its own horizontal chain row at the selected slot. Scroll left to right to inspect blocks.</p>
      <div class="legend" id="treeLegend">
        <span><i class="dot" style="background:var(--a)"></i>Side A block</span>
        <span><i class="dot" style="background:var(--b)"></i>Side B block</span>
        <span><i class="dot" style="background:var(--held)"></i>Adversary block</span>
        <span><i class="dot" style="border:2px solid var(--held);background:var(--panel)"></i>Later orphaned</span>
        <span><i class="dot" style="border:2px solid var(--g1)"></i>🔒 Live lock</span>
        <span><i class="dot" style="border:2px solid var(--heal)"></i>Confirmed tip</span>
      </div>
      <div style="display:flex; border:1px solid var(--grid); border-radius:8px; overflow:hidden; background:var(--panel);">
        <canvas id="treeLeft" style="flex-shrink:0; border-right:1px solid var(--grid);"></canvas>
        <div id="treeScroll" style="overflow-x:auto; overflow-y:hidden; flex-grow:1; min-width:0; cursor:grab;">
          <canvas id="tree"></canvas>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>3. One slot in detail</h2>
        <div class="controls">
          <span>Messages:</span>
          <div class="subtabs" id="msgModeTabs">
            <button type="button" data-msgmode="waves" aria-pressed="true">Broadcasts</button>
            <button type="button" data-msgmode="rays">Every message</button>
          </div>
        </div>
      </div>

      <div class="winbar" id="slotBar">
        <button type="button" class="step-btn" id="sPrevBtn">◀ Prev</button>
        <input type="range" id="sSlider" min="1" max="64" value="40" aria-label="Select single slot">
        <button type="button" class="step-btn" id="sNextBtn">Next ▶</button>
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


      <div class="legend">
        <span><i class="dot" style="background:var(--a)"></i>Proposal (+0 s)</span>
        <span><i class="dot" style="background:var(--g1)"></i>Unlock and vote (+1.5 s)</span>
        <span><i class="dot" style="border:2px solid var(--g1);background:var(--panel)"></i>Confirmation update (+3 s)</span>
        <span><i class="dot" style="background:var(--tsq)"></i>FG attestations</span>
        <span><i class="sq" style="background:var(--fg);border-color:var(--fg)"></i>View freeze (+4.5 s)</span>
        <span><i class="sw" style="border-top:2px dashed var(--held);height:0"></i>Held by the cut</span>
        <span><i class="sw" style="background:var(--held);height:3.5px"></i>Top row: adversary</span>
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
const GEN = "G";
let cur = runNames[0];
let progMode = "slot";
let winSize = 999;
let winStart = 1;
let zoomSlot = 40;
let msgMode = "waves";
let treeView = "final";
let treePhase = "end";
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function setup(cv, w, h, mode = "full") {
  const r = window.devicePixelRatio || 1;
  cv.width = w * r; cv.height = h * r;
  cv.style.height = h + "px";
  if (mode === "scroll" || mode === true) {
    cv.style.width = w + "px";
    cv.style.maxWidth = "none";
  } else if (mode === "fixed") {
    cv.style.width = w + "px";
    cv.style.maxWidth = w + "px";
  } else {
    cv.style.width = "100%";
    cv.style.maxWidth = w + "px";
  }
  const c = cv.getContext("2d");
  c.setTransform(r, 0, 0, r, 0, 0);
  c.font = "12px " + css("--sans");
  return c;
}

function drawTreeBadge(ctx, x, y, text, strokeCol, bgCol) {
  ctx.save();
  ctx.font = "700 9px " + css("--mono");
  const w = ctx.measureText(text).width + 6;
  const h = 12;
  const bx = x - w / 2, by = y - h + 3;
  ctx.fillStyle = bgCol || "#131b26";
  ctx.strokeStyle = strokeCol;
  ctx.lineWidth = 1;
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(bx, by, w, h, 3);
  else ctx.rect(bx, by, w, h);
  ctx.fill(); ctx.stroke();
  ctx.fillStyle = strokeCol;
  ctx.textAlign = "center";
  ctx.fillText(text, x, y + 1);
  ctx.restore();
}

function fmtNodeList(arr, total) {
  if (total && arr.length === total) return "all";
  if (arr.length > 2 && arr.every((v, i) => i === 0 || v === arr[i - 1] + 1)) {
    return `${arr[0]}–${arr[arr.length - 1]}`;
  }
  return arr.join(",");
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
  if (run.meta && run.meta.callouts) {
    box.innerHTML = run.meta.callouts.map(c =>
      `<div class="callout" style="border-left-color:var(--${c.color || "held"})"><b>${c.title}</b>${c.body}</div>`).join("");
    return;
  }
  box.innerHTML = "";
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
  $("sReadout").textContent = `Slot ${zoomSlot} of ${maxSlot} · round ${rIdx}, slot ${posInRound} of ${spr}`;
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
  const isAct = s % run.spr === 1;
  const rIdx = Math.floor(s / run.spr);
  const curRow = run.states[s - 1][1];
  const prevRow = s > 1 ? run.states[s - 2][1] : null;
  const idxA = 0, idxB = cfg.nodes - 1;
  const nA = curRow[idxA], nB = curRow[idxB];

  // Find block proposed in slot s
  let propNode = null, propParentSlot = 0, propOrphaned = false;
  Object.entries(run.blocks).forEach(([root, [bslot, parent, src]]) => {
    if (bslot === s && (propNode === null || src >= 0)) {
      propNode = src;
      propParentSlot = run.blocks[parent] ? run.blocks[parent][0] : 0;
      propOrphaned = !final.has(root);
    }
  });
  const sides = cut || !!cfg.sides;
  const propSide = propNode === null ? "None" : (propNode < 0 ? "The adversary" : (!sides ? `Node ${propNode}` : (run.groupOf[propNode] === 0 ? `Node ${propNode} (Side A)` : `Node ${propNode} (Side B)`)));

  const ev = (run.events[s] || []);
  const evFor = (kinds) => ev.filter(e => kinds.includes(e[1]));
  const fmtEv = es => es.length ? es.map(e => e[2]).join("<br>") : "—";
  const step1Body = (propNode !== null && propNode >= 0
    ? `<b>${propSide}</b> proposes <b>Block #${s}</b> on <b>#${propParentSlot}</b>${propOrphaned ? ' <span class="delta-down">(later orphaned)</span>' : ''}. ` +
      (inCut ? `Delivered to its own side; <b>held across the cut</b> until slot ${cutB}.` : ``)
    : (Object.values(run.blocks).some(b => b[0] === s && b[2] < 0) ? `<b>The adversary</b> proposes in slot ${s}.` : `No block proposed in slot ${s}.`)) +
    (isHealSlot ? `<br><span style="color:var(--heal);font-weight:700">GST heal:</span> held blocks and votes of slots ${cutA}–${cutB - 1} arrive.` : "") +
    ((run.advNotes[s] || []).length ? `<br><b style="color:var(--held)">Adversary deliveries:</b><br>` + run.advNotes[s].map(([at, l]) => `• ${l}`).join("<br>") : "");
  const step2Body = `Locks with n/2 or more opponents among the slot-${s - 1} votes move back; then each node votes.<br>` + fmtEv(evFor(["unlock"]));
  const step3Body = `Update of slot ${s - 1}: the deepest block with a strict majority of the voters is confirmed, and fast-locked with n/2 support or more.<br>` + fmtEv(evFor(["confirm"])) +
    (isAct ? `<br><b>FG action (round ${rIdx}):</b> each node attests to its deepest recent fast-locked block.<br>` + fmtEv(evFor(["fg"])) : "");
  const step4Body = `The slot-${s + 1} vote reads only the slot-${s} votes received before this point, plus those in the slot-${s + 1} proposal.`;
  $("slotStepCards").innerHTML = `
    <div class="callout" style="border-left-color:var(--a)"><b>Proposal · +0 s${isRb ? " · round start" : ""}</b>${step1Body}</div>
    <div class="callout" style="border-left-color:var(--g1)"><b>Unlock and vote · +1.5 s</b>${step2Body}</div>
    <div class="callout" style="border-left-color:var(--tsq)"><b>Confirmation update · +3 s${isAct ? " · FG action" : ""}</b>${step3Body}</div>
    <div class="callout" style="border-left-color:var(--fg)"><b>View freeze · +4.5 s</b>${step4Body}</div>
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

  const rows = (sides ? [
    [`Side A (Nodes 0–${cfg.split - 1} · ${sideVals(run, 0)} val.)`, idxA],
    [`Side B (Nodes ${cfg.split}–${cfg.nodes - 1} · ${sideVals(run, 1)} val.)`, idxB],
  ] : [[`Node 0`, idxA], [`Node ${cfg.nodes - 1}`, idxB]]).map(([name, i]) => {
    const n = curRow[i], p = prevRow ? prevRow[i] : null;
    const headOrph = n[1] && run.blocks[n[1]] && !final.has(n[1]);
    const safeOrph = n[3] && run.blocks[n[3]] && !final.has(n[3]);
    const srcLabel = n[9] === "G1"
      ? `<span class="delta-g1">slow lock</span>`
      : (n[9] === "FLOOR" ? `<span class="delta-down">no live lock</span>` : `<span class="delta-up">fast lock</span>`);
    return `<tr>
      <td><b>${name}</b></td>
      <td>${fmtDelta(n[0], p ? p[0] : null, headOrph)}</td>
      <td>${fmtDelta(n[2], p ? p[2] : null, safeOrph)}</td>
      <td>${fmtDelta(n[4], p ? p[4] : null, false)} · ${srcLabel}</td>
      <td>Justified <b>#${n[7]}</b> / Finalized <b>#${n[6]}</b> (height h=${n[8]})</td>
      <td>${(run.locks[s] && run.locks[s][i]) || "none"}</td>
    </tr>`;
  }).join("");

  $("slotStateTable").innerHTML = `
    <table class="summary">
      <thead><tr>
        <th>Node</th>
        <th>Head</th>
        <th>Confirmed tip</th>
        <th>Anchor</th>
        <th>Finality</th>
        <th>Live locks (block → expiry)</th>
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
  const cfg = run.cfg, cut = cfg.slots_down > 0, sides = cut || !!cfg.sides;
  const cutA = cfg.start, cutB = cfg.start + cfg.slots_down;
  const shareA = Math.round(100 * sideVals(run, 0) / cfg.validators);
  const vPerNode = Math.round(cfg.validators / cfg.nodes);
  const vSplit = cfg.split * vPerNode;
  const final = finalChain(run);
  const maxSlot = run.states.length;

  if (treeView !== "dag" && treeView !== "all" && (typeof treeView !== "number" || treeView >= cfg.nodes)) {
    treeView = "all";
  }

  // Populate Section 2 treeViewTabs & treePhaseTabs
  const tvContainer = $("treeViewTabs");
  let tvHtml = `<button type="button" data-tview="all"${treeView === "all" ? ' aria-pressed="true"' : ""}>All nodes</button>`;
  for (let i = 0; i < cfg.nodes; i++) {
    const grp = sides ? (i < cfg.split ? " (A)" : " (B)") : "";
    tvHtml += `<button type="button" data-tview="${i}"${treeView === i ? ' aria-pressed="true"' : ""}>Node ${i}${grp}</button>`;
  }
  tvHtml += `<button type="button" data-tview="dag"${treeView === "dag" ? ' aria-pressed="true"' : ""}>Final chain</button>`;
  tvContainer.innerHTML = tvHtml;
  [...tvContainer.querySelectorAll("button")].forEach(b => {
    b.onclick = () => {
      const v = b.dataset.tview;
      treeView = (v === "dag" || v === "all") ? v : +v;
      renderSingle();
    };
  });
  [...$("treePhaseTabs").querySelectorAll("button")].forEach(b => {
    b.setAttribute("aria-pressed", b.dataset.tphase === treePhase);
    b.onclick = () => {
      treePhase = b.dataset.tphase;
      [...$("treePhaseTabs").querySelectorAll("button")].forEach(x => x.setAttribute("aria-pressed", x === b));
      renderSingle();
    };
  });

  clampWindow(maxSlot);
  clampZoomSlot(maxSlot, run.spr, run.slotMs);
  const sFrom = winStart;
  const sTo = Math.min(maxSlot, winStart + winSize - 1);
  // For 1-slot view in Plot 1, span [sFrom - 0.85, sFrom + 0.65] on X so the incoming level at s-1 and vertical jump at s are centered!
  const xMinSlot = winSize === 1 ? Math.max(1, sFrom - 0.85) : sFrom;
  const xMaxSlot = winSize === 1 ? Math.min(maxSlot + 0.5, sFrom + 0.65) : (sTo + (winSize < maxSlot ? 0.35 : 0));

  // Top facts bar with explicit Side A / Side B node & validator membership
  const sideBadges = sides
    ? `<span class="side-pill side-a"><b>Side A</b>: ${nodeRange(0, cfg.split - 1)} (${sideVals(run, 0)} honest validators)</span>` +
      `<span class="side-pill side-b"><b>Side B</b>: ${nodeRange(cfg.split, cfg.nodes - 1)} (${sideVals(run, 1)} honest validators)</span>`
    : `<span class="side-pill side-a"><b>All nodes</b>: ${nodeRange(0, cfg.nodes - 1)} (${sideVals(run, 0)} honest validators)</span>`;
  const advBadge = run.adv ? `<span class="side-pill" style="border-color:var(--held);color:var(--held)"><b>Adversary</b>: ${run.adv} faulty validators (${Math.round(100 * run.adv / cfg.validators)}%)</span>` : "";

  const meta = run.meta || null;
  $("facts").innerHTML =
    (meta && meta.facts ? meta.facts : sideBadges + advBadge) +
    (meta && meta.facts ? "" : "") +
    (cut && !(meta && meta.facts) ? `<span>partition <b>slots ${cutA}–${cutB - 1} (D=${cfg.slots_down})</b> · GST heal at <b>slot ${cutB}</b></span>` : "") +
    `<span>latency <b>${cfg.latency_ms}${cfg.jitter_ms ? `–${cfg.latency_ms + cfg.jitter_ms}` : ""} ms</b></span>` +
    `<span>seed <b>${cfg.seed}</b></span>`;

  renderCallouts(run, shareA);

  // ---------- 1. Node Beliefs (Windowed X-axis + Auto-Scaling Y-axis) ----------
  const W = 1120;
  const panels = [
    ["Head", "head block", 0, 1, "head"],
    ["Confirmed tip", "confirmed block", 2, 3, "safe"],
    ["Locks", "each locked block (dots) and anchor (deepest lock, line)", 4, 5, "stable"],
    ["Finality", "finalized (solid) and justified (dashed) block; h = FG height", 6, null, "fin"],
  ];
  const ph = 138, gap = 36, PH = panels.length * (ph + gap) + 20;
  const pc = setup($("prog"), W, PH);
  const L = 66, R = 48;
  const PX = s => L + ((s - xMinSlot) / Math.max(0.5, xMaxSlot - xMinSlot)) * (W - L - R);
  const idxA = 0, idxB = cfg.nodes - 1;

  panels.forEach(([label, what, si, ri, kind], k) => {
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
          if (kind === "stable") (ns[i][11] || []).forEach(ls => {
            const lv = isLag ? s - ls : ls;
            lo = Math.min(lo, lv); hi = Math.max(hi, lv);
          });
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
    pc.fillText(label, L, y0 + 10);
    const lw = pc.measureText(label).width;
    pc.fillStyle = T.muted; pc.font = "12px " + css("--sans");
    pc.fillText((isLag ? "  ·  slots behind the current slot: " : "  ·  ") + what, L + lw, y0 + 10);
    pc.save(); pc.translate(16, y0 + 22 + (ph - 30) / 2); pc.rotate(-Math.PI / 2);
    pc.textAlign = "center"; pc.fillStyle = T.subtle; pc.font = "11px " + css("--sans");
    pc.fillText(isLag ? "slots behind" : "block (by slot)", 0, 0); pc.restore();
    pc.font = "11px " + css("--mono");

    // Determine clean integer tick step for [yMin, yMax]
    const ySpan = yMax - yMin;
    const yStep = [1, 2, 4, 5, 8, 10, 16, 20, 32, 50].find(st => ySpan / st <= 5) || 64;
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
    const stepA = stepCoords(ptsA, sides ? -1.1 : 0), stepB = stepCoords(ptsB, sides ? +1.1 : 0);

    // Divergence shading between Side A and Side B step functions
    if (sides && stepA_raw.length === stepB_raw.length && stepA_raw.length > 0) {
      pc.fillStyle = T.bSoft;
      pc.beginPath();
      stepA_raw.forEach((p, i) => i ? pc.lineTo(p[0], p[1]) : pc.moveTo(p[0], p[1]));
      for (let i = stepB_raw.length - 1; i >= 0; i--) pc.lineTo(stepB_raw[i][0], stepB_raw[i][1]);
      pc.closePath(); pc.fill();
    }

    // Justified dashed step curve on Finality panel (distinct colors: cyan for A, purple for B)
    if (kind === "fin") {
      const jList = sides
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

    // Every live lock of each side's node, one small dot per lock per slot (as in the newer explorer);
    // hollow when the locked block ends up off the final chain
    if (kind === "stable") {
      [[idxB, T.b, +2.2], [idxA, T.a, -2.2]].forEach(([ni, col, dx]) => {
        if (ni === idxB && !sides) return;
        run.states.forEach(([s, ns]) => {
          if (s < sFrom - 1 || s > sTo + 1) return;
          const st = ns[ni], slots = st[11] || [], roots = st[12] || [];
          slots.forEach((ls, j) => {
            const x = PX(s) + (sides ? dx : 0), y = PY(isLag ? s - ls : ls), orph = roots[j] && !final.has(roots[j]);
            pc.globalAlpha = 0.55;
            pc.beginPath(); pc.arc(x, y, 2.2, 0, 7);
            if (orph) { pc.fillStyle = T.panel; pc.fill(); pc.strokeStyle = col; pc.lineWidth = 1.3; pc.stroke(); }
            else { pc.fillStyle = col; pc.fill(); }
            pc.globalAlpha = 1;
          });
        });
      });
    }

    // Draw Side B (solid orange) and Side A (solid blue — never dashed!)
    if (stepB.length && sides) {
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
      if (sides) {
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
      for (let s = (winSize <= 16 ? 1 : 8); s <= maxSlot; s += (winSize <= 16 ? 1 : 8)) {
        const ns = run.states[s - 1][1];
        [[idxA, 0], [idxB, 1]].forEach(([ni, sideIdx]) => {
          const stSlot = ns[ni][4], stSrc = ns[ni][9];
          if (stSlot === null) return;
          if (sideIdx === 1 && stSlot === ns[idxA][4] && stSrc === ns[idxA][9]) return;
          const x = PX(s), y = PY(isLag ? (s - stSlot) : stSlot);
          if (stSrc === "G1") {
            pc.fillStyle = T.g1;
            pc.beginPath(); pc.moveTo(x, y - 6); pc.lineTo(x + 6, y); pc.lineTo(x, y + 6); pc.lineTo(x - 6, y); pc.closePath(); pc.fill();
          } else if (stSrc === "FLOOR") {
            pc.fillStyle = T.panel; pc.strokeStyle = T.held; pc.lineWidth = 2;
            pc.fillRect(x - 4.5, y - 4.5, 9, 9); pc.strokeRect(x - 4.5, y - 4.5, 9, 9);
            
          } else if (stSrc === "TSQ") {
            pc.fillStyle = T.tsq;
            pc.beginPath(); pc.arc(x, y, 4, 0, 7); pc.fill();
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
  // Row 0 = final chain; each orphaned branch gets its own row. A block continues its
  // parent's row when the parent is that row's current tip, otherwise it opens a new row.
  const rowOf = {}, rowTip = {};
  let nRows = 1;
  blocks.forEach(b => {
    if (final.has(b.root)) { rowOf[b.root] = 0; return; }
    const pr = rowOf[b.parent];
    if (pr !== undefined && pr > 0 && rowTip[pr] === b.parent) rowOf[b.root] = pr;
    else rowOf[b.root] = nRows++;
    rowTip[rowOf[b.root]] = b.root;
  });
  // ---------- 2. Node Chains in Progress (Horizontally Scrollable) ----------
  const curSlot = Math.min(run.states.length, Math.max(1, zoomSlot));
  const curState = run.states[curSlot - 1][1];
  const byRoot = {}; blocks.forEach(b => byRoot[b.root] = b);

  const LW = 155;
  const stepW = 46;
  const TL = 28, TR = 40;
  const TX = s => TL + s * stepW;
  const TW = TL + maxSlot * stepW + TR;
  const topH = 34;

  // Update note text
  const noteEl = $("treeNote");
  if (treeView === "dag") {
    noteEl.innerHTML = `Final chain: top row is the final chain; lower rows are orphaned branches. Blue stripe highlights slot <b>${curSlot}</b>. Scroll left to right to inspect blocks.`;
  } else if (treeView === "all") {
    noteEl.innerHTML = `All nodes at slot <b>${curSlot}</b> (${treePhase === "25" ? "@25% vote" : "slot end"}): each row shows that node's active canonical chain. Rings mark live locks and confirmed tips. Scroll left to right.`;
  } else {
    const singleNst0 = curState[treeView];
    const hSlot0 = singleNst0 ? singleNst0[0] : "?";
    noteEl.innerHTML = `Node <b>${treeView}</b> at slot <b>${curSlot}</b> (${treePhase === "25" ? "@25% vote" : "slot end"}): active canonical chain leading to <b>Head #${hSlot0}</b>. Scroll left to right.`;
  }

  let TH = 100, TY = null, nodesToDraw = [];
  const rowH = 52, laneH = 82;

  if (treeView === "dag") {
    TH = topH + nRows * rowH + 16;
    TY = r => topH + 26 + r * rowH;
  } else {
    nodesToDraw = typeof treeView === "number" ? [treeView] : Array.from({ length: cfg.nodes }, (_, i) => i);
    TH = topH + nodesToDraw.length * laneH;
  }

  const lc = setup($("treeLeft"), LW, TH, "fixed");
  const tc = setup($("tree"), TW, TH, "scroll");

  // --- Draw treeLeft (pinned left column) ---
  lc.fillStyle = T.panel;
  lc.fillRect(0, 0, LW, TH);
  lc.strokeStyle = T.grid;
  lc.lineWidth = 1;
  lc.beginPath(); lc.moveTo(0, topH); lc.lineTo(LW, topH); lc.stroke();

  lc.fillStyle = T.muted;
  lc.font = "600 11px " + css("--sans");
  lc.textAlign = "left";
  lc.fillText(treeView === "dag" ? "BRANCH" : "NODE / SIDE", 12, 21);

  if (treeView === "dag") {
    for (let r = 0; r < nRows; r++) {
      lc.fillStyle = r === 0 ? T.fg : T.held;
      lc.font = "600 12px " + css("--sans");
      lc.fillText(r === 0 ? "Final chain" : (nRows > 2 ? `Orphaned ${r}` : "Orphaned"), 12, TY(r) + 4);
      if (r > 0) {
        lc.strokeStyle = T.grid; lc.lineWidth = 0.6;
        lc.beginPath(); lc.moveTo(0, TY(r) - rowH / 2); lc.lineTo(LW, TY(r) - rowH / 2); lc.stroke();
      }
    }
  } else {
    nodesToDraw.forEach((nodeIdx, laneIdx) => {
      const y = topH + laneIdx * laneH + laneH / 2;
      const grp = sides ? (nodeIdx < cfg.split ? "Side A" : "Side B") : "Honest";
      const nodeCol = !sides ? T.a : (run.groupOf[nodeIdx] === 0 ? T.a : T.b);

      lc.fillStyle = nodeCol;
      lc.font = "600 12.5px " + css("--sans");
      lc.fillText(`Node ${nodeIdx}`, 12, y - 8);
      lc.fillStyle = nodeCol;
      lc.font = "500 11px " + css("--sans");
      const nameW = lc.measureText(`Node ${nodeIdx}`).width;
      lc.fillText(`· ${grp}`, 12 + nameW + 4, y - 8);

      lc.fillStyle = T.muted;
      lc.font = "10.5px " + css("--sans");
      lc.fillText(`${run.vals[nodeIdx]} validators`, 12, y + 10);

      // Lane separator
      lc.strokeStyle = T.grid; lc.lineWidth = 1;
      lc.beginPath(); lc.moveTo(0, topH + (laneIdx + 1) * laneH); lc.lineTo(LW, topH + (laneIdx + 1) * laneH); lc.stroke();
    });
  }

  // --- Draw tree (timeline header & active stripe) ---
  tc.strokeStyle = T.grid;
  tc.lineWidth = 1;
  tc.beginPath(); tc.moveTo(0, topH); tc.lineTo(TW, topH); tc.stroke();

  if (cut) {
    tc.fillStyle = T.tint;
    tc.fillRect(TX(cutA), topH, TX(cutB) - TX(cutA), TH - topH);
    tc.strokeStyle = T.held; tc.lineWidth = 1.2; tc.setLineDash([4, 3]);
    tc.beginPath(); tc.moveTo(TX(cutA), topH); tc.lineTo(TX(cutA), TH); tc.stroke();
    tc.strokeStyle = T.heal;
    tc.beginPath(); tc.moveTo(TX(cutB), topH); tc.lineTo(TX(cutB), TH); tc.stroke();
    tc.setLineDash([]);
  }

  // Active slot vertical highlight
  tc.fillStyle = T.aSoft;
  tc.fillRect(TX(curSlot) - stepW * 0.5, 0, stepW, TH);
  tc.strokeStyle = T.a; tc.lineWidth = 1.4;
  tc.strokeRect(TX(curSlot) - stepW * 0.5, 0, stepW, TH);
  drawTreeBadge(tc, TX(curSlot), 11, `SLOT ${curSlot}`, T.a, T.panel);

  for (let s = 0; s <= maxSlot; s++) {
    const isRb = s % run.spr === 0;
    const isStep4 = s % 4 === 0;
    if (isRb) {
      tc.strokeStyle = T.gs; tc.lineWidth = 1.2;
      tc.beginPath(); tc.moveTo(TX(s), 4); tc.lineTo(TX(s), TH); tc.stroke();
      if (s !== curSlot) {
        tc.fillStyle = T.fg; tc.font = "600 11px " + css("--mono"); tc.textAlign = "center";
        tc.fillText(`slot ${s} (r${s / run.spr})`, TX(s), 21);
      }
    } else if (isStep4) {
      tc.strokeStyle = T.grid; tc.lineWidth = 0.8;
      tc.beginPath(); tc.moveTo(TX(s), topH); tc.lineTo(TX(s), TH); tc.stroke();
      if (s !== curSlot) {
        tc.fillStyle = T.muted; tc.font = "400 11px " + css("--mono"); tc.textAlign = "center";
        tc.fillText(`s${s}`, TX(s), 21);
      }
    } else {
      tc.strokeStyle = T.grid; tc.lineWidth = 0.5;
      tc.beginPath(); tc.moveTo(TX(s), topH - 5); tc.lineTo(TX(s), topH); tc.stroke();
    }
  }

  if (treeView === "dag") {
    // Edges
    blocks.forEach(b => {
      const p = byRoot[b.parent];
      const px = p ? TX(p.slot) : TX(0), py = p ? TY(rowOf[p.root]) : TY(0);
      const x = TX(b.slot), y = TY(rowOf[b.root]);
      tc.strokeStyle = rowOf[b.root] === 0 ? T.gs : T.held;
      tc.lineWidth = 1.6;
      tc.beginPath(); tc.moveTo(px, py); tc.lineTo(x, y); tc.stroke();
    });

    // Genesis
    tc.fillStyle = T.muted; tc.beginPath(); tc.arc(TX(0), TY(0), 4.5, 0, 7); tc.fill();
    tc.strokeStyle = T.fg; tc.lineWidth = 1.8; tc.strokeRect(TX(0) - 6.5, TY(0) - 6.5, 13, 13);

    const finSlots = new Set([0]); run.states.forEach(r => finSlots.add(r[1][0][6]));

    blocks.forEach(b => {
      const x = TX(b.slot), y = TY(rowOf[b.root]);
      const isAdversary = b.src < 0;
      const baseCol = isAdversary ? T.held : (!sides ? T.a : (run.groupOf[b.src] === 0 ? T.a : T.b));
      tc.fillStyle = baseCol;
      tc.beginPath(); tc.arc(x, y, 4.8, 0, 7); tc.fill();

      if (rowOf[b.root] === 0 && finSlots.has(b.slot)) {
        tc.strokeStyle = T.fg; tc.lineWidth = 1.8; tc.strokeRect(x - 6.8, y - 6.8, 13.6, 13.6);
      }
      if (rowOf[b.root] > 0) {
        if (everSafe.has(b.root)) {
          tc.strokeStyle = T.held; tc.lineWidth = 2;
          tc.beginPath(); tc.arc(x, y, 7.6, 0, 7); tc.stroke();
        }
        tc.fillStyle = T.held; tc.font = "600 10px " + css("--mono"); tc.textAlign = "center";
        tc.fillText(b.slot, x, y + 18);
      }
    });

  } else {
    // Swimlanes
    nodesToDraw.forEach((nodeIdx, laneIdx) => {
      const y = topH + laneIdx * laneH + laneH / 2;
      const nst = curState[nodeIdx];
      if (!nst) return;

      const nodeCol = !sides ? T.a : (run.groupOf[nodeIdx] === 0 ? T.a : T.b);

      // Lane horizontal divider line
      tc.strokeStyle = T.grid; tc.lineWidth = 1;
      tc.beginPath(); tc.moveTo(0, topH + (laneIdx + 1) * laneH); tc.lineTo(TW, topH + (laneIdx + 1) * laneH); tc.stroke();

      // Baseline across lane
      tc.strokeStyle = T.grid; tc.lineWidth = 0.8; tc.setLineDash([2, 4]);
      tc.beginPath(); tc.moveTo(TL, y); tc.lineTo(TW - TR, y); tc.stroke();
      tc.setLineDash([]);

      // Head root
      let hRoot = nst[1];
      if (treePhase === "25" && run.voteHead && run.voteHead[curSlot] && run.voteHead[curSlot][nodeIdx] !== undefined) {
        const vSlot = run.voteHead[curSlot][nodeIdx];
        const match = blocks.find(b => b.slot === vSlot);
        if (match) hRoot = match.root;
      }
      // the snapshot is taken at +4.5 s; at the vote, confirmation and locks are still those of the previous slot
      const before = treePhase === "25" ? (curSlot > 1 ? run.states[curSlot - 2][1][nodeIdx] : []) : nst;
      const confRoot = before[3];
      const anchorRoot = before[5];
      const lockRoots = new Set(before[12] || []);

      // Trace canonical chain
      const chain = [];
      let curR = hRoot;
      while (curR && curR !== GEN && byRoot[curR]) {
        chain.push(byRoot[curR]);
        curR = byRoot[curR].parent;
      }
      chain.push({ root: GEN, slot: 0, parent: null, src: -1 });
      chain.reverse();

      // Draw chain line connecting consecutive blocks
      tc.strokeStyle = nodeCol;
      tc.lineWidth = 2.8;
      tc.beginPath();
      chain.forEach((b, idx) => {
        const bx = TX(b.slot);
        if (idx === 0) tc.moveTo(bx, y);
        else tc.lineTo(bx, y);
      });
      tc.stroke();

      // Draw blocks
      chain.forEach(b => {
        const bx = TX(b.slot);
        const isGenesis = b.root === GEN;
        const isHead = b.root === hRoot;
        const isConf = b.root === confRoot;
        const isLock = lockRoots.has(b.root);
        const isAnchor = b.root === anchorRoot;
        const isAdversary = b.src < 0;
        const isCanon = isGenesis || final.has(b.root);

        const baseCol = isGenesis ? T.muted : (isAdversary ? T.held : (!sides ? T.a : (run.groupOf[b.src] === 0 ? T.a : T.b)));

        // Badges & rings
        if (isHead && isConf) {
          tc.strokeStyle = nodeCol; tc.lineWidth = 2.2;
          tc.beginPath(); tc.arc(bx, y, 13, 0, 7); tc.stroke();
          tc.strokeStyle = T.heal; tc.lineWidth = 2.0;
          tc.beginPath(); tc.arc(bx, y, 9.5, 0, 7); tc.stroke();
          drawTreeBadge(tc, bx, y - 22, "Head & Conf", nodeCol, T.panel);
        } else if (isHead) {
          tc.strokeStyle = nodeCol; tc.lineWidth = 2.4;
          tc.beginPath(); tc.arc(bx, y, 12, 0, 7); tc.stroke();
          drawTreeBadge(tc, bx, y - 20, "Head", nodeCol, T.panel);
        } else if (isConf) {
          tc.strokeStyle = T.heal; tc.lineWidth = 2.2;
          tc.beginPath(); tc.arc(bx, y, 10.5, 0, 7); tc.stroke();
          drawTreeBadge(tc, bx, y - 19, "Conf", T.heal, T.panel);
        } else if (isLock) {
          tc.strokeStyle = T.g1; tc.lineWidth = 1.8;
          tc.beginPath(); tc.arc(bx, y, 8.5, 0, 7); tc.stroke();
        }

        // Circle
        if (isGenesis) {
          tc.fillStyle = T.muted;
          tc.fillRect(bx - 5.5, y - 5.5, 11, 11);
          tc.strokeStyle = T.fg; tc.lineWidth = 1.5;
          tc.strokeRect(bx - 5.5, y - 5.5, 11, 11);
        } else if (!isCanon) {
          // Orphaned in final outcome
          tc.fillStyle = T.panel;
          tc.beginPath(); tc.arc(bx, y, 5, 0, 7); tc.fill();
          tc.strokeStyle = T.held; tc.lineWidth = 2.2; tc.stroke();
          tc.fillStyle = baseCol;
          tc.beginPath(); tc.arc(bx, y, 2.5, 0, 7); tc.fill();
        } else {
          tc.fillStyle = baseCol;
          tc.beginPath(); tc.arc(bx, y, 5, 0, 7); tc.fill();
        }

        // Anchor
        if (isAnchor && !isGenesis) {
          tc.fillStyle = T.tsq;
          tc.beginPath(); tc.arc(bx, y, 2.5, 0, 7); tc.fill();
        }

        // Slot number / lock tag below block
        tc.fillStyle = isLock ? T.g1 : (isCanon ? T.muted : T.held);
        tc.font = (isLock ? "600 " : "400 ") + "9.5px " + css("--mono");
        tc.textAlign = "center";
        tc.fillText(isLock ? `🔒#${b.slot}` : `#${b.slot}`, bx, y + 20);
      });
    });
  }

  // Center tree scroll on curSlot
  const treeWrap = $("treeScroll");
  if (treeWrap && !window._treeScrollUserInteracted) {
    const targetX = TX(curSlot) - treeWrap.clientWidth / 2;
    treeWrap.scrollLeft = Math.max(0, targetX);
  }

  let treeDragging = false, treeStartX = 0, treeStartScroll = 0, treeDidDrag = false;
  if (treeWrap && !treeWrap._dragInit) {
    treeWrap._dragInit = true;
    treeWrap.addEventListener("mousedown", e => {
      if (e.button !== 0) return;
      treeDragging = true;
      treeDidDrag = false;
      window._treeScrollUserInteracted = true;
      treeStartX = e.clientX;
      treeStartScroll = treeWrap.scrollLeft;
      treeWrap.style.cursor = "grabbing";
    });
    window.addEventListener("mousemove", e => {
      if (!treeDragging) return;
      const dx = e.clientX - treeStartX;
      if (Math.abs(dx) > 4) treeDidDrag = true;
      treeWrap.scrollLeft = treeStartScroll - dx;
    });
    window.addEventListener("mouseup", () => {
      if (treeDragging) {
        treeDragging = false;
        treeWrap.style.cursor = "grab";
      }
    });
  }

  // Click on tree canvas to select slot
  $("tree").onclick = e => {
    if (treeDidDrag) return;
    const rect = $("tree").getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickedSlot = Math.round((clickX - TL) / stepW);
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
  const advOff = run.adv ? 1 : 0;
  const NY = n => ny0 + 22 + (n + advOff + (n >= cfg.split && sides ? 0.7 : 0)) / (cfg.nodes - 1 + advOff + (sides ? 0.7 : 0)) * (nph - 44);
  const yMidCut = sides ? (NY(cfg.split - 1) + NY(cfg.split)) / 2 : (ny0 + nph / 2);

  const isRb = s % run.spr === 0;
  const isLastInRound = (s + 1) % run.spr === 0;
  const isAct = s % run.spr === 1;
  const rIdx = Math.floor(s / run.spr);
  const inCut = cut && s >= cutA && s < cutB;
  const isHealSlot = cut && s === cutB;

  // Title banner
  nc.fillStyle = T.fg; nc.font = "600 13.5px " + css("--sans"); nc.textAlign = "left";
  const statusStr = inCut
    ? `partition: messages across the cut held until slot ${cutB}`
    : (isHealSlot ? `heal: the messages held since slot ${cutA} arrive` : "");
  nc.fillText(`Slot ${s} (round ${rIdx})` + (statusStr ? ` · ${statusStr}` : ""), 6, 16);

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
    [0, "+0 s", isRb ? "Proposal (round start)" : "Proposal", T.a, true],
    [run.deadlines[0], "+1.5 s", "Unlock and vote", T.g1, false],
    [run.deadlines[1], "+3 s", isAct ? "Update and FG attestations" : "Confirmation update", T.g1, false],
    [run.deadlines[2], "+4.5 s", "View freeze", T.fg, false],
    [run.slotMs, "+6 s", `Slot ${s + 1}`, T.muted, true],
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
    const col = !sides ? T.a : (grp === 0 ? T.a : T.b);
    const v0 = run.vals.slice(0, n).reduce((a, b) => a + b, 0), v1 = v0 + run.vals[n] - 1;
    nc.strokeStyle = T.grid; nc.lineWidth = 1;
    nc.beginPath(); nc.moveTo(NL, y); nc.lineTo(NW - NR, y); nc.stroke();
    nc.fillStyle = col; nc.font = "600 11px " + css("--mono"); nc.textAlign = "left";
    const sideStr = !sides ? "Honest" : (grp === 0 ? "Side A" : "Side B");
    nc.fillText(sides ? `Node ${n} · ${sideStr}` : `Node ${n}`, 6, y + 4);
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
  if (run.adv) {
    const y = NY(-1);
    nc.strokeStyle = T.held; nc.lineWidth = 1; nc.setLineDash([3, 3]);
    nc.beginPath(); nc.moveTo(NL, y); nc.lineTo(NW - NR, y); nc.stroke(); nc.setLineDash([]);
    nc.fillStyle = T.held; nc.font = "600 11px " + css("--mono"); nc.textAlign = "left";
    nc.fillText(`Adversary (${run.adv} validators)`, 6, y + 4);
    // every adversary delivery in this slot: a line from its row to the receiving node at the arrival time
    const kcol = [T.a, T.tsq, T.g1];
    run.msgs.forEach(([t, at, src, dst, k]) => {
      if (src >= 0 || at < t0 || at >= t1) return;
      const x = ZX(at);
      nc.strokeStyle = kcol[k]; nc.globalAlpha = 0.7; nc.lineWidth = k === 0 ? 2.2 : 1.2;
      // the line breaks at the rows it passes, so it does not read as a delivery to them
      nc.beginPath(); nc.moveTo(x, y);
      for (let r = 0; r < dst; r++) { nc.lineTo(x, NY(r) - 6); nc.moveTo(x, NY(r) + 6); }
      nc.lineTo(x, NY(dst)); nc.stroke(); nc.globalAlpha = 1;
      nc.fillStyle = kcol[k]; nc.beginPath(); nc.arc(x, NY(dst), k === 0 ? 4 : 2.5, 0, 7); nc.fill();
    });
  }

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
    if (bslot !== s || src < 0) return;
    const pSlot = run.blocks[parent] ? run.blocks[parent][0] : 0;
    const gSrc = run.groupOf[src];
    const propCol = !sides ? T.a : (gSrc === 0 ? T.a : T.b);
    const xProp = ZX(t0), yProp = NY(src);

    // Broadcasts: a schematic fan from the proposer to every other node (every message draws the real sends below)
    for (let dst = 0; dst < cfg.nodes && msgMode !== "rays"; dst++) {
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

  // At 25% (+1.5s) the Goldfish votes (purple, k=2) go out; FG attestations (green, k=1) at 50% of the action slot.
  // They arrive at peers around +1.7s..+1.8s (well before the 50% confirmation cutoff at +3.0s).
  const x25Start = ZX(t0 + run.deadlines[0]);
  const x25Mid = ZX(t0 + run.deadlines[0] + 135);
  const x25End = ZX(t0 + run.deadlines[0] + 270);
  if (msgMode === "rays") {
    [1, 2, 0].forEach(kKind => {
      run.msgs.forEach(([t, at, src, dst, k, held]) => {
        if (k !== kKind || src < 0) return;
        const sentHere = t >= t0 && t < t1;
        if (!sentHere) return;
        // blocks, proposals and relays alike, in the sender's side colour
        const col = kKind === 1 ? T.tsq : kKind === 2 ? T.g1 : (!sides || run.groupOf[src] === 0 ? T.a : T.b);
        const x1 = ZX(t);
        const x2 = ZX(Math.min(t1, held && inCut ? t + 420 : at));
        const y1 = NY(src);
        const y2 = held && inCut ? yMidCut : NY(dst);
        nc.strokeStyle = held && inCut ? T.held : col;
        nc.globalAlpha = kKind === 0 ? 0.6 : 0.28;
        nc.lineWidth = kKind === 0 ? 1.7 : 1.1;
        nc.setLineDash(held && inCut ? [3, 3] : []);
        nc.beginPath(); nc.moveTo(x1, y1); nc.lineTo(x2, y2); nc.stroke();
        nc.setLineDash([]); nc.globalAlpha = 1;
      });
    });
  } else {
    // Broadcast wave bands: purple at 25% (Goldfish votes), green at 50% on the action slot (FG attestations)
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
    drawBand(x25Start, x25End, T.g1);
    if (isAct) drawBand(ZX(t0 + run.deadlines[1]), ZX(t0 + run.deadlines[1] + 270), T.tsq);
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

  // Draw per-node markers & plain-English state badges at 25%, 50%, 75%
  // Each column is 225px wide, so every pill is kept <= 205px wide to stay strictly inside its own column!
  const ns = run.states[s - 1][1];
  const prevNs = s > 1 ? run.states[s - 2][1] : null;
  const x25 = ZX(t0 + run.deadlines[0]);
  const x50 = ZX(t0 + run.deadlines[1]);
  const x75 = ZX(t0 + run.deadlines[2]);

  for (let n = 0; n < cfg.nodes; n++) {
    const y = NY(n), nst = ns[n], pnst = prevNs ? prevNs[n] : null;
    const isRepNode = (n === 0) || (sides && n === cfg.split);

    // 25% (+1.5s): purple dot = Goldfish vote (after unlocking); the pill names the vote's head
    nc.fillStyle = T.g1;
    nc.beginPath(); nc.arc(x25, y, 3.8, 0, 7); nc.fill();
    if (isRepNode) {
      const vh = run.voteHead[s] && run.voteHead[s][n];
      if (vh !== undefined && vh !== null) drawPill(x25 + 8, y - 6, `votes #${vh}` + (nst[4] !== null ? ` · anchor #${nst[4]}` : ""), T.g1, null, "left");
    }
    if (isAct) { nc.fillStyle = T.tsq; nc.beginPath(); nc.arc(x50 + 9, y, 3.6, 0, 7); nc.fill(); }

    // 50% (+3.0s): Open purple ring = Confirmation cutoff (freeze_available_votes -> updates Safe & Head)
    nc.fillStyle = T.panel; nc.strokeStyle = T.g1; nc.lineWidth = 2;
    nc.beginPath(); nc.arc(x50, y, 4.0, 0, 7); nc.fill(); nc.stroke();
    const headChanged = pnst && nst[0] < pnst[0];
    const safeDrop = pnst && nst[2] < pnst[2];
    const confOrph = nst[3] && run.blocks[nst[3]] && !final.has(nst[3]);
    if (headChanged || safeDrop) {
      const reorgTxt = headChanged
        ? `reorg: head ${pnst[0]} → ${nst[0]} · confirmed ${nst[2]}`
        : `confirmed steps back ${pnst[2]} → ${nst[2]}`;
      drawPill(x50 + 16, y - 6, reorgTxt, T.held, T.held, "left");
    } else {
      nc.fillStyle = confOrph ? T.held : T.fg; nc.font = (confOrph ? "600 " : "") + "10px " + css("--mono"); nc.textAlign = "left";
      nc.fillText(`head ${nst[0]} · confirmed ${nst[2]}${confOrph ? " (later orphaned)" : ""}`, x50 + 16, y + 3);
    }

    // 75% (+4.5s): Black square = Incoming vote cutoff (and on round end: Freeze Round Vote Snapshot inside [75%, 100%] column!)
    nc.fillStyle = T.fg;
    const sqSize = isLastInRound ? 8 : 5.5;
    nc.fillRect(x75 - sqSize / 2, y - sqSize / 2, sqSize, sqSize);
    if (isRepNode) {
      nc.fillStyle = T.muted; nc.font = "9.5px " + css("--mono"); nc.textAlign = "left";
      nc.fillText(`locks ${(run.locks[s] && run.locks[s][n]) || "none"}`, x75 + 7, y + 3);
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

const DEF_JUMP = $("winJumpTabs").innerHTML, DEF_ZOOM = $("zoomTabs").innerHTML;
function applyMeta(run) {
  const m = run.meta, btn = (a, v, l) => `<button type="button" data-${a}="${v}">${l}</button>`;
  $("winJumpTabs").innerHTML = m && m.jumps ? m.jumps.map(([l, v]) => btn("jump", v, l)).join("") : DEF_JUMP;
  $("zoomTabs").innerHTML = m && m.zooms ? m.zooms.map(([l, v]) => btn("slot", v, l)).join("") : DEF_ZOOM;
}

function nodeRange(a, b) { return a === b ? `node ${a}` : `nodes ${a}–${b}`; }
function sideVals(run, g) {
  return run.vals.reduce((a, v, i) => a + (run.groupOf[i] === g ? v : 0), 0);
}
function renderAbout(run) {
  const a = $("about"), m = run.meta || {};
  const secs = [["Goal", m.goal], ["Setup", m.setup], ["How", m.how], ["Result", m.result]].filter(x => x[1]);
  a.innerHTML = "<h2>About this experiment</h2>" +
    secs.map(([l, t]) => `<div class="sec"><span class="lab">${l}</span><div>${t}</div></div>`).join("");
  a.hidden = !secs.length;
}
function render() {
  if (cur === SWEEP_TAB) {
    $("singleView").style.display = "none";
    $("sweepView").style.display = "grid";
    renderSweep();
  } else {
    $("singleView").style.display = "grid";
    $("sweepView").style.display = "none";
    applyMeta(RUNS[cur]);
    renderAbout(RUNS[cur]);
    renderSingle();
    renderSettlements(RUNS[cur]);
  }
}

function pick(name) {
  cur = name;
  const m = (RUNS[name] || {}).meta || {};
  if (m.slot) { zoomSlot = m.slot; }
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
    if (winSize >= 999 && newSize < 999) {
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

$("winJumpTabs").onclick = e => {
  const b = e.target.closest("button");
  if (!b) return;
  const target = +b.dataset.jump;
  if (winSize >= 999) {
    winSize = 8;
    [...$("winSizeTabs").querySelectorAll("button")].forEach(x => x.setAttribute("aria-pressed", +x.dataset.wsize === 8));
  }
  winStart = target;
  renderSingle();
};

// Allow scrolling/dragging directly on Panel 1 canvas to pan the slot window, or click to select slot in Section 3
let dragStartX = null, dragStartSlot = null, dragMoved = false;
$("prog").addEventListener("mousedown", e => {
  dragStartX = e.clientX;
  dragStartSlot = winStart;
  dragMoved = false;
  if (winSize < 999) $("prog").style.cursor = "grabbing";
});
window.addEventListener("mousemove", e => {
  if (dragStartX === null) return;
  if (Math.abs(e.clientX - dragStartX) > 4) dragMoved = true;
  if (winSize >= 999) return;
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
  if (winSize >= 999) return;
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

$("zoomTabs").onclick = e => {
  const b = e.target.closest("button");
  if (!b) return;
  zoomSlot = +b.dataset.slot;
  renderSingle();
};
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
// #run=<tab name>&slot=<slot>&mode=lag&win=16&from=<slot> opens that tab at that slot, plot 1 in
// lag mode, a 16-slot window starting at <from>
const HP = new URLSearchParams(location.hash.slice(1));
const startTab = allTabs.includes(HP.get("run")) ? HP.get("run") : allTabs[0];
pick(startTab);
if (HP.get("mode")) {
  progMode = HP.get("mode");
  document.querySelectorAll("[data-mode]").forEach(x => x.setAttribute("aria-pressed", x.dataset.mode === progMode));
}
if (HP.get("win")) {
  winSize = +HP.get("win");
  $("winSizeTabs").querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", +x.dataset.wsize === winSize));
}
if (HP.get("from")) winStart = +HP.get("from");
if (HP.get("slot")) zoomSlot = +HP.get("slot");
if (HP.get("node")) {
  const nv = HP.get("node");
  treeView = (nv === "dag" || nv === "all") ? nv : +nv;
}
if (HP.get("phase")) treePhase = HP.get("phase");
if (HP.get("mode") || HP.get("win") || HP.get("from") || HP.get("slot") || HP.get("node") || HP.get("phase")) renderSingle();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main(sys.argv[1:])
