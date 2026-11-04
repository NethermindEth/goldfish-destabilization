// Figure for the finalization-hiding attack (section 3.3): the block tree around slots 33 and 34.
#import "@preview/cetz:0.3.4"
#import "timeline.typ": c-prop, c-vote, c-late, c-merge, c-lock, c-conf

#let fin-hide-tree() = cetz.canvas(length: 1cm, {
  import cetz.draw: *
  let blk(p, name, body, col, dashed: false, fill: none) = {
    rect((p.at(0) - 0.55, p.at(1) - 0.3), (p.at(0) + 0.55, p.at(1) + 0.3), radius: 0.08,
      stroke: (paint: col, thickness: 1pt, dash: if dashed { "dashed" } else { none }),
      fill: if fill == none { col.lighten(88%) } else { fill }, name: name)
    content(p, text(size: 7.5pt, body))
  }
  let edge(a, b) = line(a, b, stroke: 0.8pt + luma(120))
  let note(p, body, col) = content(p, text(size: 6.8pt, fill: col.darken(20%), body), anchor: "west")
  let honest = luma(80)
  let adv = c-lock
  // x positions: slots 10, 17, 19, gap, 32, 33, 34
  let x10 = 0
  let x17 = 1.5
  let x19 = 3.0
  let x32 = 5.0
  let x33 = 6.5
  let x34 = 8.0
  let ys = (fb: 1.1, z: 0, q: -1.3)
  // honest chain
  blk((x10, 0), "f", [slot 10], honest, fill: luma(215))
  blk((x17, 0), "p17", [slot 17], honest)
  blk((x19, 0), "j", [slot 19], honest)
  blk((x32, 0), "w", $W$, honest)
  line("f.east", "p17.west", stroke: (paint: luma(120), thickness: 0.8pt, dash: "dotted"))
  edge("p17.east", "j.west")
  line("j.east", (x32 - 0.55, 0), stroke: (paint: luma(120), thickness: 0.8pt, dash: "dotted"))
  content((x10, 0.5), text(size: 6.5pt, fill: luma(70))[finalized], anchor: "south")
  content((x19, 0.5), text(size: 6.5pt, fill: luma(70))[justified], anchor: "south")
  content((x32, -0.45), text(size: 6.5pt, fill: luma(70), align(center)[slot 32, \ honest head]), anchor: "north")
  // adversary blocks
  blk((x33, ys.fb), "b", $B$, adv)
  blk((x34, ys.fb), "fb", [FB], adv)
  blk((x34, ys.z), "z", $Z$, adv)
  blk((x34, ys.q), "q", $Q$, adv, dashed: true)
  line("w.east", "b.west", stroke: 0.8pt + luma(120))
  edge("b.east", "fb.west")
  line("w.east", "z.west", stroke: 0.8pt + luma(120))
  line("p17.south", (x17, ys.q), "q.west", stroke: 0.8pt + luma(120))
  content((x33, ys.fb + 0.45), text(size: 6.5pt, fill: adv.darken(20%))[slot 33, to nodes 0 and 3], anchor: "south")
  // notes
  let nx = x34 + 0.75
  note((nx, ys.fb), [*FB* (slot 34): carries the round's attestations, which finalize slot 19. \ Sent to nodes 0–2.], adv)
  note((nx, ys.z), [*Z* (slot 34): a sibling of $B$. Sent to node 3, which votes for it.], adv)
  note((nx, ys.q), [*Q* (slot 34): carries the 11 hidden slot-33 votes. Sent to node 3. \ Accepted by node 3 (finalized: slot 10); refused by \ nodes 0–2 (finalized: slot 19), as it does not extend slot 19.], adv)
})
