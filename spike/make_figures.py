"""Build an interactive HTML page of simulator runs from partition_run.py --events files.

Usage:
    python make_figures.py OUT.html NAME=events.json [NAME=events.json ...]
e.g. python make_figures.py results/figs/figures.html \
        "Honest=results/figs/honest.json" "50/50 split=results/figs/split50.json"
"""

import json
import sys

KINDS = {"block": 0, "att": 1, "avail": 2}


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
        msgs.append([m["t"], m["at"], m["src"], m["dst"], KINDS[m["kind"]], int(m["held"]), m["slot"], vote])
        if m["kind"] == "block" and m["root"] not in blocks:
            blocks[m["root"]] = [m["slot"], m["parent"], m["src"]]
    states = [
        [s["slot"], [[n["head_slot"], n["head_root"], n["safe_conf_slot"], n["safe_root"],
                      n["stable_slot"], n["stable_root"], n["finalized_slot"], n["justified_slot"],
                      n["chain_height"], n["stable_src"]] for n in s["nodes"]]]
        for s in d["states"]
    ]
    return {
        "cfg": {k: cfg[k] for k in ("nodes", "split", "start", "slots_down", "seed", "latency_ms", "jitter_ms", "validators")},
        "groupOf": [d["group_of"][str(i)] if str(i) in d["group_of"] else d["group_of"][i] for i in range(cfg["nodes"])],
        "slotMs": d["slot_ms"], "deadlines": d["deadlines_ms"], "spr": d["slots_per_round"],
        "votes": votes, "msgs": msgs, "blocks": blocks, "states": states,
    }


def main(out, specs):
    data = {}
    for spec in specs:
        name, path = spec.split("=", 1)
        data[name] = compact(path)
    html = TEMPLATE.replace("/*DATA*/", "const RUNS = " + json.dumps(data, separators=(",", ":")) + ";")
    with open(out, "w") as fh:
        fh.write(html)
    print(f"wrote {out} ({len(html) / 1e6:.1f} MB)")


TEMPLATE = r"""<meta charset="utf-8">
<title>Partition Run Explorer</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column; each figure is a full-width panel with its own legend and controls, scenario tabs on top. */
:root {
  --bg: #f6f7f9; --panel: #ffffff; --fg: #1b2230; --muted: #5c6678; --grid: #e2e6ec; --gridStrong: #c3cad6;
  --a: #2f6fd6; --b: #c98316; --held: #d2413a; --final: #1b2230; --tint: rgba(210,65,58,0.07); --accent: #2f6fd6;
  --sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #11151c; --panel: #171c25; --fg: #e4e8ef; --muted: #98a2b4; --grid: #262d39; --gridStrong: #3a4352;
  --a: #6ea2ff; --b: #f0aa45; --held: #ff6b62; --final: #e4e8ef; --tint: rgba(255,107,98,0.09); --accent: #6ea2ff; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #11151c; --panel: #171c25; --fg: #e4e8ef; --muted: #98a2b4; --grid: #262d39; --gridStrong: #3a4352;
  --a: #6ea2ff; --b: #f0aa45; --held: #ff6b62; --final: #e4e8ef; --tint: rgba(255,107,98,0.09); --accent: #6ea2ff; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font-family: var(--sans); font-size: 15px; line-height: 1.5; }
.wrap { max-width: 1180px; margin: 0 auto; padding-block: 28px 64px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); display: grid; gap: 24px; }
h1 { font-size: 26px; font-weight: 600; margin: 0; text-wrap: balance; letter-spacing: -0.01em; }
h2 { font-size: 18px; font-weight: 600; margin: 0; text-wrap: balance; }
p { margin: 0; max-width: 72ch; }
.lead { color: var(--muted); }
.tabs { display: flex; flex-wrap: wrap; gap: 8px; }
.tabs button { font: 500 14px var(--sans); padding: 7px 14px; border-radius: 6px; border: 1px solid var(--gridStrong); background: var(--panel); color: var(--fg); cursor: pointer; }
.tabs button[aria-pressed="true"] { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
button:focus-visible, input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.facts { display: flex; flex-wrap: wrap; gap: 8px 20px; font-family: var(--mono); font-size: 13px; color: var(--muted); }
.facts b { color: var(--fg); font-weight: 500; }
.panel { background: var(--panel); border: 1px solid var(--grid); border-radius: 8px; padding: 18px; display: grid; gap: 12px; min-width: 0; }
.controls { display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; font-size: 13px; color: var(--muted); }
.controls label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.controls input[type=number] { width: 4.5em; font: 13px var(--mono); padding: 3px 6px; border: 1px solid var(--gridStrong); border-radius: 4px; background: var(--bg); color: var(--fg); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--muted); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { display: inline-block; width: 18px; height: 3px; border-radius: 2px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }
.scroll { overflow-x: auto; }
canvas { display: block; }
.note { font-size: 13px; color: var(--muted); }
.tip { position: fixed; pointer-events: none; background: var(--panel); border: 1px solid var(--gridStrong); border-radius: 6px; padding: 6px 9px; font: 12px var(--mono); color: var(--fg); box-shadow: 0 4px 14px rgba(0,0,0,.12); max-width: 300px; }
</style>
<div class="wrap">
  <header style="display:grid;gap:8px">
    <h1>Partition Run Explorer</h1>
    <p class="lead">Simulated runs of the decoupled-consensus executable spec (fradamt/consensus-specs, simplex-healing). Each node holds its own spec Store; messages travel through a simulated network that a partition can cut. Minimal preset: 6 s slots, 8-slot rounds.</p>
  </header>
  <div class="tabs" id="tabs" role="group" aria-label="Scenario"></div>
  <div class="facts" id="facts"></div>

  <section class="panel">
    <h2>Who sent what, and when it arrived</h2>
    <p class="note">One lane per node, grouped by partition side. Each line runs from a message's send time on the sender's lane to its delivery on the receiver's lane. Thin vertical lines mark the 25/50/75% deadlines, thicker ones slots, the thickest ones rounds. Messages the partition held back are dashed red and land together when the network heals.</p>
    <div class="controls">
      <label><input type="checkbox" id="k0" checked> blocks</label>
      <label><input type="checkbox" id="k1" checked> finality votes</label>
      <label><input type="checkbox" id="k2"> Goldfish votes</label>
      <label>slots <input type="number" id="from" min="1"> to <input type="number" id="to" min="1"></label>
    </div>
    <div class="legend"><span><i class="sw" style="background:var(--a)"></i>sent by side A</span><span><i class="sw" style="background:var(--b)"></i>sent by side B</span><span><i class="sw" style="background:var(--held)"></i>held by partition</span></div>
    <div class="scroll"><canvas id="st" aria-label="Message space-time diagram"></canvas></div>
  </section>

  <section class="panel">
    <h2>Block tree</h2>
    <p class="note">Every block that was proposed, by slot. The top row is the chain all nodes end on; lower rows are branches that were later abandoned. Fill shows which side proposed the block; a ring marks a block some node reported as safe-confirmed.</p>
    <div class="legend"><span><i class="dot" style="background:var(--a)"></i>proposed by side A</span><span><i class="dot" style="background:var(--b)"></i>proposed by side B</span><span><i class="dot" style="border:2px solid var(--held)"></i>was safe-confirmed somewhere, later orphaned</span></div>
    <div class="scroll"><canvas id="tree" aria-label="Block tree"></canvas></div>
  </section>

  <section class="panel">
    <h2>What each node believed, slot by slot</h2>
    <p class="note">One line per node (colour = partition side). Y is the slot of the block each node points to. A hollow red point means the node pointed at a block that was later orphaned.</p>
    <div class="legend"><span><i class="sw" style="background:var(--a)"></i>side A nodes</span><span><i class="sw" style="background:var(--b)"></i>side B nodes</span><span><i class="dot" style="border:2px solid var(--held)"></i>points at an orphaned block</span></div>
    <div class="scroll"><canvas id="prog" aria-label="Per-node head, safe, stable and finalized"></canvas></div>
  </section>
</div>
<div class="tip" id="tip" hidden></div>
<script>
/*DATA*/
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const names = Object.keys(RUNS);
let cur = names[0];
const $ = id => document.getElementById(id);

function setup(cv, w, h) {
  const r = window.devicePixelRatio || 1;
  cv.width = w * r; cv.height = h * r; cv.style.width = w + 'px'; cv.style.height = h + 'px';
  const c = cv.getContext('2d'); c.setTransform(r, 0, 0, r, 0, 0); c.font = '12px ' + css('--sans'); return c;
}

function finalChain(run) {
  const last = run.states[run.states.length - 1][1][0][1];
  const on = new Set(); let r = last;
  while (r && run.blocks[r]) { on.add(r); r = run.blocks[r][1]; }
  return on;
}

function render() {
  const run = RUNS[cur];
  const T = { a: css('--a'), b: css('--b'), held: css('--held'), fg: css('--fg'), muted: css('--muted'), grid: css('--grid'), gs: css('--gridStrong'), tint: css('--tint'), panel: css('--panel') };
  const side = n => run.groupOf[n] === 0 ? T.a : T.b;
  const final = finalChain(run);
  const cfg = run.cfg, cut = cfg.slots_down > 0;
  const cutA = cfg.start, cutB = cfg.start + cfg.slots_down;
  $('facts').innerHTML = `<span>nodes <b>${cfg.nodes}</b></span><span>validators <b>${cfg.validators}</b></span><span>split <b>${cut ? Math.round(100 * cfg.split / cfg.nodes) + '/' + (100 - Math.round(100 * cfg.split / cfg.nodes)) : 'none'}</b></span>` + (cut ? `<span>cut <b>slots ${cutA}–${cutB - 1}</b>, heal at <b>${cutB}</b></span>` : '') + `<span>latency <b>${cfg.latency_ms}+U[0,${cfg.jitter_ms}] ms</b></span><span>seed <b>${cfg.seed}</b></span>`;

  // ---------- space-time ----------
  const from = Math.max(1, +$('from').value || 1), to = Math.max(from + 1, +$('to').value || from + 1);
  const lanes = [...Array(cfg.nodes).keys()].sort((x, y) => run.groupOf[x] - run.groupOf[y] || x - y);
  const laneOf = {}; lanes.forEach((n, i) => laneOf[n] = i);
  const L = 70, R = 16, top = 34, laneH = 30;
  const W = Math.max(720, Math.min(2400, (to - from) * 70)), H = top + laneH * cfg.nodes + 30;
  const c = setup($('st'), W, H);
  const t0 = from * run.slotMs, t1 = to * run.slotMs, X = t => L + (t - t0) / (t1 - t0) * (W - L - R), Y = n => top + laneOf[n] * laneH + laneH / 2;
  if (cut) { c.fillStyle = T.tint; c.fillRect(X(Math.max(t0, cutA * run.slotMs)), top - 6, Math.max(0, X(Math.min(t1, cutB * run.slotMs)) - X(Math.max(t0, cutA * run.slotMs))), laneH * cfg.nodes + 12); }
  for (let s = from; s <= to; s++) {
    const x = X(s * run.slotMs), rb = s % run.spr === 0;
    c.strokeStyle = rb ? T.gs : T.grid; c.lineWidth = rb ? 2 : 1; c.beginPath(); c.moveTo(x, top - 6); c.lineTo(x, H - 26); c.stroke();
    if (s < to) { for (const d of run.deadlines) { const xd = X(s * run.slotMs + d); c.strokeStyle = T.grid; c.lineWidth = 0.5; c.setLineDash([2, 3]); c.beginPath(); c.moveTo(xd, top); c.lineTo(xd, H - 30); c.stroke(); c.setLineDash([]); } }
    c.fillStyle = rb ? T.fg : T.muted; c.textAlign = 'center'; c.fillText((rb ? 'r' + s / run.spr + ' · ' : '') + s, x, 20);
  }
  c.textAlign = 'left';
  lanes.forEach(n => { c.fillStyle = side(n); c.fillText('node ' + n + ' ' + (run.groupOf[n] ? 'B' : 'A'), 8, Y(n) + 4); c.strokeStyle = T.grid; c.lineWidth = 1; c.beginPath(); c.moveTo(L, Y(n)); c.lineTo(W - R, Y(n)); c.stroke(); });
  const show = [$('k0').checked, $('k1').checked, $('k2').checked];
  const drawn = [];
  for (const pass of [0, 1]) for (const m of run.msgs) {
    const [t, at, src, dst, k, held] = m;
    if (src === dst || !show[k] || held !== pass) continue;
    if (at < t0 || t > t1) continue;
    c.strokeStyle = held ? T.held : side(src); c.globalAlpha = k === 0 ? 0.95 : held ? 0.55 : 0.35; c.lineWidth = k === 0 ? 1.8 : 0.8;
    c.setLineDash(held ? [4, 3] : []);
    c.beginPath(); c.moveTo(X(t), Y(src)); c.lineTo(X(Math.min(at, t1)), Y(dst)); c.stroke();
    if (k === 0) drawn.push(m);
  }
  c.globalAlpha = 1; c.setLineDash([]);
  for (const m of drawn) { c.fillStyle = side(m[2]); c.beginPath(); c.arc(X(m[0]), Y(m[2]), 3.5, 0, 7); c.fill(); }
  c.fillStyle = T.muted; c.fillText('time → (slot numbers on top; r = round start)', L, H - 8);
  $('st')._hit = { X, Y, run, t0, t1 };

  // ---------- block tree ----------
  const blocks = Object.entries(run.blocks).map(([root, [slot, parent, src]]) => ({ root, slot, parent, src }));
  const everSafe = new Set(); run.states.forEach(s => s[1].forEach(n => everSafe.add(n[3])));
  const row = {}; let nextRow = 1; const sorted = blocks.slice().sort((x, y) => x.slot - y.slot);
  for (const b of sorted) {
    if (final.has(b.root)) row[b.root] = 0;
    else { const pr = row[b.parent]; row[b.root] = pr && pr > 0 ? pr : nextRow++; }
  }
  const maxSlot = Math.max(...blocks.map(b => b.slot)), TW = Math.max(720, maxSlot * 18 + 100), rows = Math.max(1, nextRow), TH = 50 + rows * 44;
  const tc = setup($('tree'), TW, TH), TX = s => 60 + s * ((TW - 80) / maxSlot), TY = r => 34 + r * 44;
  if (cut) { tc.fillStyle = T.tint; tc.fillRect(TX(cutA) - 6, 14, TX(cutB) - TX(cutA), TH - 20); }
  for (let s = 0; s <= maxSlot; s += run.spr) { tc.strokeStyle = T.grid; tc.beginPath(); tc.moveTo(TX(s), 14); tc.lineTo(TX(s), TH - 6); tc.stroke(); tc.fillStyle = T.muted; tc.textAlign = 'center'; tc.fillText(s, TX(s), 12); }
  tc.textAlign = 'left'; tc.fillStyle = T.muted; tc.fillText('final chain', 4, TY(0) + 4); if (rows > 1) tc.fillText('orphaned', 4, TY(1) + 4);
  const byRoot = {}; blocks.forEach(b => byRoot[b.root] = b);
  for (const b of blocks) { const p = byRoot[b.parent]; const px = p ? TX(p.slot) : TX(0), py = p ? TY(row[p.root]) : TY(0); tc.strokeStyle = T.gs; tc.lineWidth = 1.2; tc.beginPath(); tc.moveTo(px, py); tc.lineTo(TX(b.slot), TY(row[b.root])); tc.stroke(); }
  for (const b of blocks) {
    const x = TX(b.slot), y = TY(row[b.root]);
    tc.fillStyle = side(b.src); tc.beginPath(); tc.arc(x, y, 5.5, 0, 7); tc.fill();
    if (!final.has(b.root) && everSafe.has(b.root)) { tc.strokeStyle = T.held; tc.lineWidth = 2; tc.beginPath(); tc.arc(x, y, 8.5, 0, 7); tc.stroke(); }
  }

  // ---------- progress small multiples ----------
  const panels = [['Head', 0, 1], ['Safe-confirmed', 2, 3], ['Stable root', 4, 5], ['Finalized', 6, null]];
  const PW = Math.max(720, maxSlot * 14 + 100), ph = 150, PH = panels.length * (ph + 30) + 10;
  const pc = setup($('prog'), PW, PH), PX = s => 60 + (s - 1) * ((PW - 80) / (run.states.length - 1));
  panels.forEach(([label, si, ri], k) => {
    const y0 = 10 + k * (ph + 30), PY = v => y0 + 20 + (1 - v / maxSlot) * (ph - 24);
    pc.fillStyle = T.fg; pc.font = '600 13px ' + css('--sans'); pc.textAlign = 'left'; pc.fillText(label, 0, y0 + 10); pc.font = '12px ' + css('--sans');
    if (cut) { pc.fillStyle = T.tint; pc.fillRect(PX(cutA), y0 + 16, PX(cutB) - PX(cutA), ph - 16); }
    for (let v = 0; v <= maxSlot; v += 16) { pc.strokeStyle = T.grid; pc.beginPath(); pc.moveTo(60, PY(v)); pc.lineTo(PW - 20, PY(v)); pc.stroke(); pc.fillStyle = T.muted; pc.textAlign = 'right'; pc.fillText(v, 52, PY(v) + 4); }
    for (let n = 0; n < cfg.nodes; n++) {
      pc.strokeStyle = side(n); pc.globalAlpha = 0.75; pc.lineWidth = 1.4; pc.beginPath(); let started = false;
      run.states.forEach(([slot, ns]) => { const v = ns[n][si]; if (v === null) { started = false; return; } const x = PX(slot), y = PY(v); started ? pc.lineTo(x, y) : pc.moveTo(x, y); started = true; });
      pc.stroke(); pc.globalAlpha = 1;
      if (ri !== null) run.states.forEach(([slot, ns]) => { const r = ns[n][ri]; if (r && run.blocks[r] && !final.has(r)) { pc.strokeStyle = T.held; pc.lineWidth = 1.5; pc.beginPath(); pc.arc(PX(slot), PY(ns[n][si]), 3.5, 0, 7); pc.stroke(); } });
    }
  });
  pc.textAlign = 'center'; pc.fillStyle = T.muted;
  for (let s = 8; s <= run.states.length; s += 8) pc.fillText('slot ' + s, PX(s), PH - 2);
}

// tooltip on space-time: nearest block message
$('st').addEventListener('mousemove', e => {
  const h = $('st')._hit; if (!h) return; const rect = e.target.getBoundingClientRect(), mx = e.clientX - rect.left, my = e.clientY - rect.top;
  let best = null, bd = 64;
  for (const m of h.run.msgs) { if (m[2] === m[3]) continue; const k = m[4]; if (!$('k' + k).checked) continue; if (m[1] < h.t0 || m[0] > h.t1) continue;
    const ax = h.X(m[0]), ay = h.Y(m[2]), bx = h.X(Math.min(m[1], h.t1)), by = h.Y(m[3]); const vx = bx - ax, vy = by - ay, l2 = vx * vx + vy * vy || 1; let u = ((mx - ax) * vx + (my - ay) * vy) / l2; u = Math.max(0, Math.min(1, u)); const dx = ax + u * vx - mx, dy = ay + u * vy - my, d = dx * dx + dy * dy; if (d < bd) { bd = d; best = m; } }
  const tip = $('tip'); if (!best) { tip.hidden = true; return; }
  const kind = ['block', 'finality vote', 'Goldfish vote'][best[4]], sm = h.run.slotMs;
  tip.innerHTML = `${kind} for slot ${best[6]}${best[7] >= 0 ? ' · ' + h.run.votes[best[7]] : ''}<br>node ${best[2]} → node ${best[3]}<br>sent ${(best[0] / 1000).toFixed(2)} s (slot ${Math.floor(best[0] / sm)} +${best[0] % sm} ms)<br>arrived ${(best[1] / 1000).toFixed(2)} s (slot ${Math.floor(best[1] / sm)} +${best[1] % sm} ms)${best[5] ? '<br><b>held by partition</b>' : ''}`;
  tip.hidden = false; tip.style.left = Math.min(e.clientX + 14, innerWidth - 310) + 'px'; tip.style.top = (e.clientY + 14) + 'px';
});
$('st').addEventListener('mouseleave', () => $('tip').hidden = true);

function pick(name) {
  cur = name;
  const run = RUNS[name];
  $('from').value = Math.max(1, run.cfg.start - 2); $('to').value = run.cfg.start + Math.max(run.cfg.slots_down, 8) + 3;
  [...$('tabs').children].forEach(b => b.setAttribute('aria-pressed', b.textContent === name));
  render();
}
names.forEach(n => { const b = document.createElement('button'); b.textContent = n; b.type = 'button'; b.onclick = () => pick(n); $('tabs').appendChild(b); });
['k0', 'k1', 'k2', 'from', 'to'].forEach(id => $(id).addEventListener('change', render));
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);
new MutationObserver(render).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
pick(names[0]);
</script>
"""

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
