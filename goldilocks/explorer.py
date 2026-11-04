"""Interactive explorer for Goldilocks runs (partition_run.py --events).

    python explorer.py out.html name=results/first/p50_s48_d16.events.json [name=path ...]
    python explorer.py out.html --index results/first      # every *.events.json in a folder

One self-contained HTML page. Per run it shows:
  * tips over time, one panel per node: head, confirmed tip, finalized tip (y = slot of
    the block), live locks as markers; blocks that end up off the final chain are hollow;
    cut and sleep windows shaded;
  * the block tree: x = slot, one lane per branch, proposer group, finalized and
    orphaned blocks; the selected slot's heads, confirmed tips and locks per node;
  * FG heights per node (h_max, h_j) and contests;
  * the selected slot: per-node state table, AC events (locks written / moved back /
    expired, confirmations, vetoes, restarts), and a message timeline across the slot's
    public times (proposal, vote, support cutoff, freeze) with held messages dashed.
"""

import glob
import json
import os
import sys

KINDS = {"block": 0, "vote": 1, "att": 2}


def compact(path, name):
    with open(path) as fh:
        d = json.load(fh)
    P = d["params"]
    slot_ms = P["slot_ms"]
    blocks = d["blocks"]
    roots = ["G"] + sorted(blocks, key=lambda r: (blocks[r][0], r))
    idx = {r: i for i, r in enumerate(roots)}
    parent = [-1] + [idx[blocks[r][1]] for r in roots[1:]]
    bslot = [0] + [blocks[r][0] for r in roots[1:]]
    pnode = [-1] + [blocks[r][3] for r in roots[1:]]
    natt = [0] + [blocks[r][4] for r in roots[1:]]
    nvotes = [0] + [blocks[r][5] for r in roots[1:]]

    def I(r):
        return idx.get(r, -1) if r is not None else -1

    states = []
    for row in d["states"]:
        nodes = []
        for x in row["nodes"]:
            nodes.append([I(x["head"]), I(x["conf"]), I(x["F"]), I(x["J"]), x["hj"], x["hmax"], int(x["contest"]),
                          I(x["fc_root"]), I(x["anchor"]), [[I(b), dl] for b, _, dl in x["locks"]],
                          I(x["saved_conf"]), I(x["fg_confirmed"]), x["head_h"], I(x["record"]), int(x["asleep"])])
        states.append([row["slot"], nodes])
    log = []
    for e in d["log"]:
        k = e["kind"]
        s = int(e["t"] // slot_ms)
        if k == "confirm":
            log.append([s, e["node"], "confirm", I(e.get("result")), int(bool(e.get("vetoed"))), I(e.get("lock")),
                        e.get("how") or "", e.get("slot")])
        elif k == "lock_back":
            log.append([s, e["node"], "lock_back", I(e["block"]), I(e["to"]), int(e["deadline"] // slot_ms)])
        elif k == "lock_expire":
            log.append([s, e["node"], "lock_expire", I(e["block"]), int(e["deadline"] // slot_ms)])
        elif k == "confirm_switch":
            log.append([s, e["node"], "confirm_switch", I(e["old"]), I(e["new"]), e["slot"]])
        elif k in ("restart", "violation"):
            log.append([s, e["node"], k, e.get("what", "")])
        elif k == "fg_pair":
            log.append([s, e["node"], "fg_pair", I(e["fg_confirmed"]), I(e["head"])])
    msgs, vidx = [], {}
    for m in d["messages"]:
        extra = ""
        if m["kind"] == "block":
            extra = I(m["root"])
        elif m["kind"] == "vote":
            extra = [[I(h), c] for h, c in m["heads"]]
            k = (m["t"], round(m["at"]), m["src"], m["dst"], int(m["held"]))
            if k in vidx:  # one line per sender, receiver and timing (the adversary sends votes one by one)
                agg = dict(map(tuple, msgs[vidx[k]][6]))
                for h, c in extra:
                    agg[h] = agg.get(h, 0) + c
                msgs[vidx[k]][6] = [[h, c] for h, c in agg.items()]
                continue
            vidx[k] = len(msgs)
        else:
            extra = [m["h"], I(m["T"]), int(bool(m["tau"])), m["hf"], I(m["Tf"]), m["n"]]
        msgs.append([m["t"], round(m["at"]), m["src"], m["dst"], KINDS[m["kind"]], int(m["held"]), extra])
    cfg = d["config"]
    sleep = []
    for item in filter(None, (cfg.get("sleep") or "").split(",")):
        nid, a, b = item.split(":")
        sleep.append([int(nid), float(a), float(b)])
    summary = None
    jpath = path.replace(".events.json", ".json")
    if os.path.exists(jpath):
        with open(jpath) as fh:
            summary = json.load(fh)
        summary.pop("config", None)
    return {
        "name": name, "params": P, "cfg": {k: cfg.get(k) for k in ("groups", "shares", "start", "slots_down", "start2",
                                                                    "slots_down2", "groups2", "sleep", "latency_ms",
                                                                    "jitter_ms", "release_spread_ms", "seed")},
        "groupOf": [d["group_of"][str(i)] if str(i) in d["group_of"] else d["group_of"][i]
                    for i in range(len(d["validators"]))],
        "validators": d["validators"],
        "windows": [[a // slot_ms, b // slot_ms, [g[str(i)] if str(i) in g else g[i] for i in range(len(d["validators"]))]]
                    for a, b, g in d["windows"]],
        "sleep": sleep,
        "blocks": {"slot": bslot, "parent": parent, "pnode": pnode, "natt": natt, "nvotes": nvotes},
        "states": states, "log": log, "msgs": msgs, "summary": summary,
    }


def main(argv):
    meta = {}
    if "--meta" in argv:  # {run name: {"about": html, "slot": focus slot}}
        i = argv.index("--meta")
        with open(argv[i + 1]) as fh:
            meta = json.load(fh)
        argv = argv[:i] + argv[i + 2:]
    out, specs = argv[0], argv[1:]
    runs = []
    if specs and specs[0] == "--index":
        for p in sorted(glob.glob(os.path.join(specs[1], "*.events.json"))):
            runs.append(compact(p, os.path.basename(p).replace(".events.json", "")))
    else:
        for s in specs:
            name, path = s.split("=", 1)
            runs.append(compact(path, name))
    for r in runs:
        r["meta"] = meta.get(r["name"], {})
    html = PAGE.replace("/*DATA*/null", json.dumps(runs, separators=(",", ":")))
    with open(out, "w") as fh:
        fh.write(html)
    print(f"wrote {out} ({os.path.getsize(out)/1e6:.2f} MB, {len(runs)} runs)")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Goldilocks Explorer</title>
<style>
:root{color-scheme:light;--bg:#f6f6f4;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;--grid:#e4e3df;
--line:#cfcec9;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s7:#6250d6;--shade:rgba(120,118,110,.13);
--sleep:rgba(98,80,214,.10);--sel:rgba(42,120,214,.12);--bad:#e34948}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#111110;--surface:#1a1a19;--ink:#f0efec;
--ink2:#c3c2b7;--muted:#8d8c85;--grid:#2c2c2a;--line:#3a3a37;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
--s7:#9085e9;--shade:rgba(200,198,190,.10);--sleep:rgba(144,133,233,.14);--sel:rgba(57,135,229,.18);--bad:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111110;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#8d8c85;--grid:#2c2c2a;
--line:#3a3a37;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s7:#9085e9;--shade:rgba(200,198,190,.10);
--sleep:rgba(144,133,233,.14);--sel:rgba(57,135,229,.18);--bad:#e66767}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:14px 16px 6px}h1{font-size:18px;margin:0 0 2px}h2{font-size:14px;margin:0 0 6px}.sub{color:var(--ink2)}
main{padding:0 16px 40px;display:grid;gap:12px}.card{background:var(--surface);border:1px solid var(--grid);border-radius:10px;padding:12px;min-width:0}
.runs{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.runs button{font:inherit;border:1px solid var(--line);background:var(--surface);color:var(--ink);
border-radius:999px;padding:3px 10px;cursor:pointer}.runs button.on{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{border:1px solid var(--grid);border-radius:8px;padding:4px 8px}.chip b{font-variant-numeric:tabular-nums}
.legend{display:flex;flex-wrap:wrap;gap:12px;color:var(--ink2);margin-bottom:6px}.sw{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;vertical-align:middle;margin-right:5px}
svg{display:block;width:100%;height:auto;overflow:visible}svg text{fill:var(--ink2);font-size:10px}
.scroll{overflow-x:auto}table{border-collapse:collapse;font-variant-numeric:tabular-nums;width:100%}th,td{padding:3px 8px;border-bottom:1px solid var(--grid);text-align:left;white-space:nowrap}
th{color:var(--ink2);font-weight:600}.tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:6px 8px;
box-shadow:0 4px 14px rgba(0,0,0,.15);font-size:12px;display:none;z-index:9;max-width:340px}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.row2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}@media(max-width:900px){.row2{grid-template-columns:1fr}}
.nav{display:flex;gap:6px;align-items:center}.nav button{font:inherit;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:6px;padding:1px 8px;cursor:pointer}
.about{display:none;margin-top:10px;background:var(--surface);border:1px solid var(--grid);border-left:3px solid var(--s1);border-radius:8px;padding:10px 12px;line-height:1.55;max-width:1100px}
.about b{color:var(--ink)}.about p{margin:4px 0}
.ev{margin:0;padding-left:16px}.ev li{margin:2px 0}.warn{color:var(--bad);font-weight:600}
</style></head><body>
<header><h1>Goldilocks explorer</h1><div class="sub">Executable model of the FGSA spec (22 Oct 2026): partitions, sleep, healing and a one-third adversary. Click any chart to select a slot; ← → step.</div>
<div class="runs" id="runs"></div><div class="chips" id="chips"></div><div class="about" id="about"></div></header>
<main>
<section class="card"><h2>Tips over time, per node</h2>
<div class="legend"><span><span class="sw" style="background:var(--s1)"></span>head</span><span><span class="sw" style="background:var(--s2)"></span>confirmed tip</span>
<span><span class="sw" style="background:var(--s3)"></span>finalized tip (FG)</span><span><span class="dot" style="background:var(--s4)"></span>live lock (block slot)</span>
<span><span class="dot" style="border:2px solid var(--ink2)"></span>hollow = block not on the final chain</span><span><span class="sw" style="background:var(--shade);height:10px"></span>cut</span><span><span class="sw" style="background:var(--sleep);height:10px"></span>asleep</span></div>
<div id="tips"></div></section>
<section class="card"><h2>Block tree <span class="sub" id="treesub"></span></h2>
<div class="legend"><span>digit = proposer's node, X = adversary</span><span><span class="dot" style="background:var(--s3)"></span>finalized (final view, node 0)</span><span><span class="dot" style="border:2px solid var(--muted)"></span>orphaned</span>
<span>selected slot: <b style="color:var(--s1)">H</b> head, <b style="color:var(--s2)">C</b> confirmed, <b style="color:var(--s4)">L</b> lock — subscript = node</span></div>
<div class="scroll" id="tree"></div></section>
<div class="row2">
<section class="card"><h2>FG heights per node</h2><div class="legend" id="hlegend"></div><div id="heights"></div></section>
<section class="card"><h2>Messages held across the cut, per slot</h2><div class="legend"><span><span class="sw" style="background:var(--s1)"></span>blocks</span><span><span class="sw" style="background:var(--s2)"></span>vote bundles</span><span><span class="sw" style="background:var(--s3)"></span>attestation bundles</span></div><div id="held"></div></section>
</div>
<section class="card"><div class="nav"><h2 style="margin:0">Slot <span id="slotno"></span></h2><button id="prev">←</button><button id="next">→</button><span class="sub" id="slotsub"></span></div>
<div class="scroll" style="margin-top:8px"><table id="tbl"></table></div>
<div class="row2" style="margin-top:10px"><div><h2>AC / FG events this slot</h2><ul class="ev mono" id="events"></ul></div>
<div><h2>Messages in flight around this slot</h2><div class="legend"><span><span class="sw" style="background:var(--s1)"></span>block</span><span><span class="sw" style="background:var(--s2)"></span>votes</span><span><span class="sw" style="background:var(--s3)"></span>attestations</span><span>dashed = held by the cut</span><span>top row: adversary</span></div><div id="msgs"></div></div></div>
</section>
</main><div class="tip" id="tip"></div>
<script>
const RUNS=/*DATA*/null;
let R=null, SEL=0, FINAL=null;
const $=id=>document.getElementById(id);
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const NS="http://www.w3.org/2000/svg";
function el(tag,attrs,parent){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e}
function txt(parent,x,y,s,attrs={}){const t=el("text",Object.assign({x,y},attrs),parent);t.textContent=s;return t}
const tip=$("tip");
function showTip(ev,html){tip.innerHTML=html;tip.style.display="block";const w=tip.offsetWidth;let x=ev.clientX+14;if(x+w>innerWidth-8)x=ev.clientX-w-14;tip.style.left=x+"px";tip.style.top=(ev.clientY+12)+"px"}
function hideTip(){tip.style.display="none"}
const G=r=>String.fromCharCode(65+r);
function bslot(i){return i<0?"—":R.blocks.slot[i]}
function bname(i){if(i<0)return "⊥";return i===0?"gen":"#"+R.blocks.slot[i]+(FINAL.canon[i]?"":"′")}
function anc(a,b){ // a ⪯ b
  if(a<0||b<0)return false;const P=R.blocks.parent,S=R.blocks.slot;while(b>=0&&S[b]>=S[a]){if(b===a)return true;b=P[b]}return false}
function prepare(run){
  R=run;const n=R.blocks.slot.length,last=R.states[R.states.length-1][1][0];
  const canon=new Array(n).fill(false),fin=new Array(n).fill(false);
  let b=last[0];while(b>=0){canon[b]=true;b=R.blocks.parent[b]}
  b=last[2];while(b>=0){fin[b]=true;b=R.blocks.parent[b]}
  // lanes: canonical chain on lane 0, other branches greedily below
  const kids=Array.from({length:n},()=>[]);for(let i=1;i<n;i++)kids[R.blocks.parent[i]].push(i);
  const lane=new Array(n).fill(0),laneEnd=[];
  function depthFirst(i,l){lane[i]=l;laneEnd[l]=Math.max(laneEnd[l]??-1,R.blocks.slot[i]);
    const ks=kids[i].slice().sort((a,b)=>(canon[b]-canon[a])||(R.blocks.slot[a]-R.blocks.slot[b]));
    ks.forEach((k,j)=>{if(j===0&&(canon[k]||!canon[i]||kids[i].every(x=>!canon[x])))depthFirst(k,l);else{let m=1;while(laneEnd[m]!==undefined&&laneEnd[m]>=R.blocks.slot[i])m++;laneEnd[m]=R.blocks.slot[i];depthFirst(k,m)}})}
  depthFirst(0,0);
  FINAL={canon,fin,lane,lanes:Math.max(...lane)+1};
  const nslots=R.states.length;SEL=Math.min(SEL,nslots-1);
  if(!SEL&&R.meta&&R.meta.slot!=null)SEL=Math.min(R.meta.slot,nslots-1);
  if(!SEL){const s=R.summary;SEL=(s&&s.heal_slot)?Math.min(s.heal_slot,nslots-1):Math.min(24,nslots-1)}
}
function cutAt(s){return R.windows.some(w=>s>=w[0]&&s<w[1])}
function chips(){
  const S=R.summary||{},p=R.params,c=R.cfg,box=$("chips");box.innerHTML="";
  const add=(k,v,cls="")=>{const d=document.createElement("div");d.className="chip";d.innerHTML=`${k} <b class="${cls}">${v}</b>`;box.appendChild(d)};
  add("validators",`${p.n} (q=${p.q})`);add("nodes",R.validators.map((v,i)=>`${i}:${G(R.groupOf[i])}${v}`).join(" "));
  add("Δ",`${p.delta} ms · slot ${p.slot_ms} ms · R=${p.R} · k=${p.k}`);
  R.windows.forEach(w=>add("cut",`[${w[0]}, ${w[1]}) groups ${w[2].map(G).join("")}`));
  R.sleep.forEach(z=>add("asleep",`node ${z[0]} [${z[1]}, ${z[2]})`));
  if(c.release_spread_ms)add("release spread",c.release_spread_ms+" ms");if(c.jitter_ms)add("jitter",c.jitter_ms+" ms");
  if(S.per_node){const reorg=Math.max(...S.per_node.map(x=>x.max_reorg_depth)),orph=Math.max(...S.per_node.map(x=>x.orphaned_confirmed.length));
    if(S.heal_slot)add("heal / GST","slot "+S.heal_slot);
    if(S.heal_slot)add("heads agree",S.agree_head_since==null?"never":`+${S.reconverge_head_slots}`);
    if(S.heal_slot)add("confirmed agree",S.agree_conf_since==null?"never":`+${S.reconverge_conf_slots}`);
    add("max reorg depth",reorg);add("orphaned confirmed blocks",orph,orph?"warn":"");
    add("conflicting live locks",`${S.lock_conflict_slots.length} slots`+(S.last_lock_conflict_after_heal!=null?`, last ${S.last_lock_conflict_after_heal}`:""),S.last_lock_conflict_after_heal!=null?"warn":"");
    add("finalized conflict",S.finalized_conflict?"YES":"no",S.finalized_conflict?"warn":"");
    add("invariants",S.invariant_violations&&S.invariant_violations.length?"VIOLATED":"ok",S.invariant_violations&&S.invariant_violations.length?"warn":"");}
}
const W=1100;
function xScale(n,l,r){return s=>l+(r-l)*s/Math.max(1,n-1)}
function shadeWindows(svg,x,top,h,node){
  R.windows.forEach(w=>el("rect",{x:x(w[0]-.5),y:top,width:x(w[1]-.5)-x(w[0]-.5),height:h,fill:"var(--shade)"},svg));
  R.sleep.filter(z=>node==null||z[0]===node).forEach(z=>el("rect",{x:x(z[1]-.5),y:top,width:x(z[2]-.5)-x(z[1]-.5),height:h,fill:"var(--sleep)"},svg));
}
function clickLayer(svg,x,top,h,n,onHover){
  const r=el("rect",{x:x(-.5),y:top,width:x(n-.5)-x(-.5),height:h,fill:"transparent",style:"cursor:crosshair"},svg);
  const inv=ev=>{const pt=svg.createSVGPoint();pt.x=ev.clientX;pt.y=ev.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());
    return Math.max(0,Math.min(n-1,Math.round((p.x-x(0))/(x(1)-x(0)))))};
  r.addEventListener("click",ev=>{SEL=inv(ev);renderSel()});
  r.addEventListener("mousemove",ev=>onHover(ev,inv(ev)));r.addEventListener("mouseleave",hideTip);
}
function selLine(svg,x,top,h){el("rect",{class:"selbar",x:x(SEL-.5),y:top,width:x(1)-x(0),height:h,fill:"var(--sel)"},svg)}
function renderTips(){
  const box=$("tips");box.innerHTML="";const N=R.validators.length,n=R.states.length,ph=118,gap=26,L=44,Rr=W-10;
  const H=N*(ph+gap);const svg=el("svg",{viewBox:`0 0 ${W} ${H}`},box);const x=xScale(n,L,Rr);
  const maxSlot=n-1;
  // y = how many slots the tip is behind the current slot (0 at the top)
  let maxLag=8;R.states.forEach(([s,nodes])=>nodes.forEach(st=>{if(!st[14])maxLag=Math.max(maxLag,s-bslot(st[2]),s-bslot(st[1]))}));
  maxLag=Math.ceil(maxLag/8)*8;
  for(let k=0;k<N;k++){
    const top=k*(ph+gap)+16,y=lag=>top+ph*lag/maxLag;
    txt(svg,0,top-4,`node ${k} · group ${G(R.groupOf[k])} · ${R.validators[k]} validators — slots behind the current slot`,{style:"font-weight:600;fill:var(--ink)"});
    shadeWindows(svg,x,top,ph,k);
    for(let t=0;t<=maxSlot;t+=8){el("line",{x1:x(t),x2:x(t),y1:top,y2:top+ph,stroke:"var(--grid)"},svg);if(k===N-1)txt(svg,x(t),top+ph+12,t,{"text-anchor":"middle"})}
    for(let v=0;v<=maxLag;v+=maxLag/4){el("line",{x1:x(0),x2:x(maxSlot),y1:y(v),y2:y(v),stroke:"var(--grid)"},svg);txt(svg,L-6,y(v)+3,v,{"text-anchor":"end"})}
    selLine(svg,x,top,ph);
    R.states.forEach(([s,nodes])=>{if(nodes[k][14])return;nodes[k][9].forEach(([b])=>{if(b>=0)el("circle",{cx:x(s),cy:y(s-bslot(b)),r:2.6,fill:"var(--s4)",opacity:.85},svg)})});
    const series=[[2,"--s3"],[1,"--s2"],[0,"--s1"]];
    series.forEach(([f,c])=>{let d="";R.states.forEach(([s,nodes],i)=>{const st=nodes[k];if(st[14]){return}const v=s-bslot(st[f]);d+=(d&&!R.states[i-1][1][k][14]?"L":"M")+x(s)+","+y(v)});
      el("path",{d,fill:"none",stroke:`var(${c})`,"stroke-width":2,"stroke-linejoin":"round"},svg);
      R.states.forEach(([s,nodes])=>{const b=nodes[k][f];if(b>=0&&!FINAL.canon[b]&&!nodes[k][14])el("circle",{cx:x(s),cy:y(s-bslot(b)),r:3,fill:"var(--surface)",stroke:`var(${c})`,"stroke-width":1.5},svg)})});
    clickLayer(svg,x,top,ph,n,(ev,s)=>{const st=R.states[s][1][k];showTip(ev,`<b>slot ${s} · node ${k}</b>${st[14]?" (asleep)":""}<br>head ${bname(st[0])} · confirmed ${bname(st[1])} · finalized ${bname(st[2])}<br>locks: ${st[9].map(([b,d])=>bname(b)+"→"+d).join(", ")||"none"}<br>h_max ${st[5]} · h_j ${st[4]}${st[6]?" · contest":""}`)});
  }
}
function renderTree(){
  const box=$("tree");box.innerHTML="";const n=R.states.length,lanes=FINAL.lanes,lh=34,top=10,L=44;
  const Wt=Math.max(W,n*16+L+20),H=top+lanes*lh+40;const svg=el("svg",{viewBox:`0 0 ${Wt} ${H}`,style:`min-width:${Wt}px`},box);
  const x=xScale(n,L,Wt-14),y=l=>top+l*lh+14;
  shadeWindows(svg,x,top,lanes*lh,null);
  for(let t=0;t<n;t+=8){el("line",{x1:x(t),x2:x(t),y1:top,y2:top+lanes*lh,stroke:"var(--grid)"},svg);txt(svg,x(t),top+lanes*lh+12,t,{"text-anchor":"middle"})}
  selLine(svg,x,top,lanes*lh);
  const B=R.blocks;
  for(let i=1;i<B.slot.length;i++){const p=B.parent[i];el("path",{d:`M${x(B.slot[p])},${y(FINAL.lane[p])} C${x(B.slot[p])+8},${y(FINAL.lane[p])} ${x(B.slot[i])-8},${y(FINAL.lane[i])} ${x(B.slot[i])},${y(FINAL.lane[i])}`,fill:"none",stroke:"var(--line)","stroke-width":1.5},svg)}
  for(let i=0;i<B.slot.length;i++){
    const cx=x(B.slot[i]),cy=y(FINAL.lane[i]),canon=FINAL.canon[i],fin=FINAL.fin[i];
    const g=el("g",{},svg);
    el("rect",{x:cx-6,y:cy-6,width:12,height:12,rx:3,fill:fin?"var(--s3)":canon?"var(--surface)":"var(--bg)",stroke:canon?"var(--ink2)":"var(--muted)","stroke-dasharray":canon?"":"2 2","stroke-width":1.5},g);
    if(i>0)txt(g,cx,cy+3.5,B.pnode[i]<0?"X":String(B.pnode[i]),{"text-anchor":"middle",style:`font-size:8px;font-weight:700;fill:${fin?"#fff":"var(--ink)"}`});
    g.addEventListener("mousemove",ev=>showTip(ev,`<b>${bname(i)}</b> slot ${B.slot[i]}${i?(B.pnode[i]<0?" · proposed by the adversary":` · proposer node ${B.pnode[i]} (group ${G(R.groupOf[B.pnode[i]])})`):""}<br>parent ${bname(B.parent[i])} · ${B.natt[i]} attestations · ${B.nvotes[i]} votes<br>${fin?"finalized":canon?"on the final chain":"orphaned"}`));
    g.addEventListener("mouseleave",hideTip);g.addEventListener("click",()=>{SEL=Math.min(n-1,B.slot[i]);renderSel()});
  }
  // markers for the selected slot
  const st=R.states[SEL][1],marks={};
  const push=(b,kind,k)=>{if(b<0)return;const m=(marks[b]=marks[b]||{H:new Set(),C:new Set(),L:new Set()});m[kind].add(k)};
  st.forEach((s,k)=>{if(s[14])return;push(s[0],"H",k);push(s[1],"C",k);s[9].forEach(([b])=>push(b,"L",k))});
  // one label row per kind, stacked above the block: H0123 / C01 / L23
  Object.entries(marks).forEach(([b,m])=>{b=+b;const cx=x(B.slot[b]),cy=y(FINAL.lane[b]);let row=0;
    [["L","--s4"],["C","--s2"],["H","--s1"]].forEach(([kind,c])=>{if(!m[kind].size)return;
      txt(svg,cx+7,cy-7-row*9,kind+[...m[kind]].sort().join(""),{style:`font-size:8.5px;font-weight:700;fill:var(${c})`});row++})});
  $("treesub").textContent=`— ${B.slot.length} blocks, ${FINAL.canon.filter(Boolean).length} on the final chain`;
}
function renderHeights(){
  const box=$("heights");box.innerHTML="";const N=R.validators.length,n=R.states.length,h=170,L=30,Wh=540;
  const svg=el("svg",{viewBox:`0 0 ${Wh} ${h+24}`},box);const x=xScale(n,L,Wh-8);
  const maxH=Math.max(...R.states.map(r=>Math.max(...r[1].map(s=>s[5]))));const y=v=>8+h-(h*v/Math.max(1,maxH));
  shadeWindows(svg,x,8,h,null);selLine(svg,x,8,h);
  for(let v=0;v<=maxH;v+=Math.max(1,Math.ceil(maxH/6))){el("line",{x1:x(0),x2:x(n-1),y1:y(v),y2:y(v),stroke:"var(--grid)"},svg);txt(svg,L-4,y(v)+3,v,{"text-anchor":"end"})}
  for(let t=0;t<n;t+=16)txt(svg,x(t),h+22,t,{"text-anchor":"middle"});
  const cols=["--s1","--s2","--s3","--s4","--s5","--s7"];$("hlegend").innerHTML=Array.from({length:N},(_,k)=>`<span><span class="sw" style="background:var(${cols[k%6]})"></span>node ${k}</span>`).join("")+`<span>solid h_max · dashed h_j · ◆ contest</span>`;
  for(let k=0;k<N;k++){[[5,""],[4,"4 3"]].forEach(([f,da])=>{let d="";R.states.forEach(([s,nd])=>{d+=(d?"L":"M")+x(s)+","+(y(nd[k][f])+k*1.2)});el("path",{d,fill:"none",stroke:`var(${cols[k%6]})`,"stroke-width":1.6,"stroke-dasharray":da},svg)});
    R.states.forEach(([s,nd])=>{if(nd[k][6])el("path",{d:`M${x(s)},${y(nd[k][5])-4}l3,3l-3,3l-3,-3z`,fill:`var(${cols[k%6]})`},svg)})}
  clickLayer(svg,x,8,h,n,(ev,s)=>showTip(ev,`<b>slot ${s}</b><br>`+R.states[s][1].map((st,k)=>`node ${k}: h_max ${st[5]} · h_j ${st[4]} · head height ${st[12]}${st[6]?" · contest":""}`).join("<br>")));
}
function renderHeld(){
  const box=$("held");box.innerHTML="";const n=R.states.length,h=170,L=30,Wh=540,ms=R.params.slot_ms;
  const cnt=Array.from({length:n},()=>[0,0,0]);R.msgs.forEach(m=>{if(m[5]){const s=Math.floor(m[0]/ms);if(s<n)cnt[s][m[4]]++}});
  const mx=Math.max(1,...cnt.map(c=>c[0]+c[1]+c[2]));const svg=el("svg",{viewBox:`0 0 ${Wh} ${h+24}`},box);const x=xScale(n,L,Wh-8),y=v=>8+h-h*v/mx;
  shadeWindows(svg,x,8,h,null);selLine(svg,x,8,h);
  [0,mx].forEach(v=>txt(svg,L-4,y(v)+3,v,{"text-anchor":"end"}));for(let t=0;t<n;t+=16)txt(svg,x(t),h+22,t,{"text-anchor":"middle"});
  const bw=Math.max(1,(x(1)-x(0))-1);
  cnt.forEach((c,s)=>{let base=0;[0,1,2].forEach(k=>{if(!c[k])return;el("rect",{x:x(s)-bw/2,y:y(base+c[k]),width:bw,height:y(base)-y(base+c[k]),fill:`var(--s${k+1})`},svg);base+=c[k]})});
  clickLayer(svg,x,8,h,n,(ev,s)=>showTip(ev,`<b>slot ${s}</b> held: ${cnt[s][0]} blocks · ${cnt[s][1]} vote bundles · ${cnt[s][2]} attestation bundles`));
}
function renderSel(){
  const n=R.states.length;$("slotno").textContent=SEL;
  const p=R.params,d=p.delta;$("slotsub").textContent=`round ${Math.floor(SEL/p.R)}${SEL%p.R===0?" (round start)":""}${cutAt(SEL)?" · CUT":""} · t_s = ${SEL*p.slot_ms} ms`;
  renderTips();renderTree();renderHeights();renderHeld();
  const st=R.states[SEL][1];
  const head=`<tr><th>node</th><th>head</th><th>h(head)</th><th>confirmed</th><th>record</th><th>finalized F</th><th>J</th><th>h_j / h_max</th><th>fc root</th><th>anchor</th><th>live locks (block→deadline slot)</th><th>saved conf (s−1)</th><th>last fg_confirmed</th></tr>`;
  $("tbl").innerHTML=head+st.map((s,k)=>`<tr><td>${k} (${G(R.groupOf[k])})${s[14]?" z":""}</td><td>${bname(s[0])}</td><td>${s[12]}</td><td>${bname(s[1])}</td><td>${bname(s[13])}</td><td>${bname(s[2])}</td><td>${bname(s[3])}</td><td>${s[4]} / ${s[5]}${s[6]?" contest":""}</td><td>${bname(s[7])}</td><td>${bname(s[8])}</td><td>${s[9].map(([b,dl])=>bname(b)+"→"+dl).join(", ")||"—"}</td><td>${bname(s[10])}</td><td>${bname(s[11])}</td></tr>`).join("");
  const evs=R.log.filter(e=>e[0]===SEL).map(e=>{const [s,node,k]=e;
    if(k==="confirm")return `n${node} confirm(slot ${e[7]}) → ${bname(e[3])}${e[4]?' <span class="warn">vetoed by a live lock</span>':""}${e[5]>=0?` · lock ${bname(e[5])} (${e[6]}) until slot ${e[7]+R.params.k}+5Δ`:""}`;
    if(k==="lock_back")return `n${node} <b>unlock</b>: lock ${bname(e[3])} moved back to ${bname(e[4])} (deadline slot ${e[5]})`;
    if(k==="lock_expire")return `n${node} lock ${bname(e[3])} expired`;
    if(k==="confirm_switch")return `<span class="warn">n${node} confirmed record switched ${bname(e[3])} → ${bname(e[4])} (conflicting)</span>`;
    if(k==="restart")return `n${node} <b>restart</b> (wakes; joins later)`;
    if(k==="violation")return `<span class="warn">n${node} violation: ${e[3]}</span>`;
    if(k==="fg_pair")return `n${node} FG action: fg_confirmed ${bname(e[3])}, head ${bname(e[4])}${e[3]<0?" — no attestation":""}`;
    return JSON.stringify(e)});
  $("events").innerHTML=evs.length?evs.map(e=>`<li>${e}</li>`).join(""):"<li>none</li>";
  renderMsgs();
}
function renderMsgs(){
  const box=$("msgs");box.innerHTML="";const p=R.params,d=p.delta,N=R.validators.length;
  const adv=R.msgs.some(m=>m[2]<0),off=adv?1:0;
  const t0=SEL*p.slot_ms-d,t1=(SEL+1)*p.slot_ms+2*d,Wm=540,L=58,lh=30,H=(N+off)*lh+34;
  const svg=el("svg",{viewBox:`0 0 ${Wm} ${H}`},box);const x=t=>L+(Wm-L-8)*(t-t0)/(t1-t0),y=k=>14+(k+off)*lh+lh/2;
  if(adv){txt(svg,L-6,y(-1)+3,"adversary",{"text-anchor":"end",style:"fill:var(--bad);font-weight:600"});el("line",{x1:L,x2:Wm-8,y1:y(-1),y2:y(-1),stroke:"var(--grid)","stroke-dasharray":"2 3"},svg)}
  const names=["prop","vote","cutoff","freeze"];
  for(let s=SEL;s<=SEL+1;s++)for(let i=0;i<4;i++){const t=s*p.slot_ms+i*d;if(t<t0||t>t1)continue;el("line",{x1:x(t),x2:x(t),y1:10,y2:H-18,stroke:i?"var(--grid)":"var(--line)"},svg);txt(svg,x(t),H-6,(s===SEL?"":"+1 ")+names[i],{"text-anchor":"middle"})}
  for(let k=0;k<N;k++){txt(svg,L-6,y(k)+3,"node "+k,{"text-anchor":"end"});el("line",{x1:L,x2:Wm-8,y1:y(k),y2:y(k),stroke:"var(--grid)"},svg)}
  const shown=R.msgs.filter(m=>(m[0]>=t0&&m[0]<=t1)||(m[1]>=t0&&m[1]<=t1&&m[0]<t0));
  shown.sort((a,b)=>(a[4]!==1)-(b[4]!==1)||(a[2]<0)-(b[2]<0));  // votes first, so blocks and the adversary draw on top
  shown.slice(-600).forEach(m=>{const xa=Math.max(L,x(m[0])),xb=Math.min(Wm-8,x(m[1]));
    const ln=el("line",{x1:xa,y1:y(m[2]),x2:xb,y2:y(m[3]),stroke:`var(--s${m[4]+1})`,"stroke-width":1.6,"stroke-dasharray":m[5]?"3 3":"",opacity:.85},svg);
    el("circle",{cx:xb,cy:y(m[3]),r:2.4,fill:`var(--s${m[4]+1})`},svg);
    const hit=el("line",{x1:xa,y1:y(m[2]),x2:xb,y2:y(m[3]),stroke:"transparent","stroke-width":8},svg);
    hit.addEventListener("mousemove",ev=>{let w=["block "+bname(m[6]),"votes: "+(m[6]||[]).map(([h,c])=>c+"×"+bname(h)).join(", "),`attestations ×${m[6][5]}: (h ${m[6][0]}, ${bname(m[6][1])}${m[6][2]?", timeout":""})${m[6][3]!=null?` fin (${m[6][3]}, ${bname(m[6][4])})`:""}`][m[4]];
      showTip(ev,`<b>${w}</b><br>${m[2]<0?"adversary":"node "+m[2]} → node ${m[3]}<br>sent ${m[0]} ms · arrives ${m[1]} ms${m[5]?" · <b>held by the cut</b>":""}`)});hit.addEventListener("mouseleave",hideTip)});
}
function about(){const a=$("about"),m=(R.meta||{}).about;a.innerHTML=m?"<b>About this experiment</b>"+m:"";a.style.display=m?"block":"none"}
function pick(i){prepare(RUNS[i]);about();document.querySelectorAll(".runs button").forEach((b,j)=>b.classList.toggle("on",i===j));chips();renderSel();try{localStorage.setItem("gl-run",i)}catch(e){}}
const _renderSel=renderSel;renderSel=function(){_renderSel();try{history.replaceState(null,"",`#run=${R.name}&slot=${SEL}`)}catch(e){}};
RUNS.forEach((r,i)=>{const b=document.createElement("button");b.textContent=r.name;b.onclick=()=>{SEL=0;pick(i)};$("runs").appendChild(b)});
$("prev").onclick=()=>{SEL=Math.max(0,SEL-1);renderSel()};$("next").onclick=()=>{SEL=Math.min(R.states.length-1,SEL+1);renderSel()};
addEventListener("keydown",e=>{if(e.key==="ArrowLeft")$("prev").click();if(e.key==="ArrowRight")$("next").click()});
let start=0;try{start=+(localStorage.getItem("gl-run")||0);if(!(start<RUNS.length))start=0}catch(e){}
const hp=new URLSearchParams(location.hash.slice(1));
if(hp.get("run")){const j=RUNS.findIndex(r=>r.name===hp.get("run"));if(j>=0)start=j}
if(hp.get("slot"))SEL=+hp.get("slot");
pick(start);
</script></body></html>"""

if __name__ == "__main__":
    main(sys.argv[1:])
