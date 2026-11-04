// Figures for the Synchrony Attack (section 1.6): a timeline with one lane per party, and the block tree.
#import "@preview/cetz:0.3.4"
#import "timeline.typ": c-prop, c-vote, c-late, c-merge, c-lock, c-conf

#let sync-attack-timeline() = cetz.canvas(length: 1cm, {
  import cetz.draw: *
  let X(ms) = ms * 1.58 / 1000  // cm per ms
  let top = 3.4
  let mid = 1.7
  let bot = 0
  let lanes = ((top, [nodes 0–1 \ (32 honest)]), (mid, [node 2 \ (16 honest)]), (bot, [adversary \ (16)]))
  let marks = ((0, $t_s$), (1500, [vote]), (3000, [snapshot]), (4500, [view freeze]), (6000, $t_(s+1)$), (7500, [vote]), (9000, [delayed \ confirmation]))
  for (ms, lab) in marks {
    line((X(ms), -0.6), (X(ms), top + 1.5), stroke: (paint: luma(175), dash: if ms == 6000 { none } else { "dashed" }, thickness: if ms == 6000 { 1pt } else { 0.5pt }))
    content((X(ms), -0.7), text(size: 6.5pt, fill: luma(70), align(center)[#lab \ #(ms) ms]), anchor: "north")
  }
  for (y, lab) in lanes {
    line((X(0), y), (X(9300), y), stroke: 0.6pt + luma(150))
    content((-0.15, y), text(size: 7pt, align(right, lab)), anchor: "east")
  }
  let dot(p, n, col) = {
    circle(p, radius: 0.13, fill: col, stroke: none)
    content(p, text(size: 5.8pt, fill: white, weight: "bold", str(n)))
  }
  let note(p, body, col, anchor: "south") = content(p, box(fill: white, inset: 1pt, text(size: 6.2pt, fill: col.darken(20%), body)), anchor: anchor)
  // 1, 2: B_s delivered on either side of the vote
  // B_s: sent at 1200 ms, arrives at nodes 0-1 at 1400 ms (before the vote) and at node 2 at 1600 ms (after)
  let arrow(a, b) = line(a, b, stroke: 1pt + c-prop, mark: (end: ">", fill: c-prop, scale: 0.7))
  arrow((X(1200), bot + 0.05), (X(1400), top - 0.2))
  arrow((X(1200), bot + 0.05), (X(1600) + 0.03, mid))
  note((X(1200), bot - 0.1), [sends $B_s$ (1200 ms)], c-prop, anchor: "north")
  dot((X(1400), top), 1, c-prop)
  note((X(1400) - 0.12, top + 0.2), [$B_s$ arrives at 1400 ms, \ before the vote: vote for $B_s$], c-prop, anchor: "south-east")
  dot((X(1500), mid), 2, c-vote)
  note((X(1600) + 0.15, mid + 0.2), [vote for $B_(s-1)$ at 1500 ms; \ $B_s$ arrives at 1600 ms, too late], c-vote, anchor: "south-west")
  // 3: snapshot
  dot((X(3000), top), 3, c-conf)
  dot((X(3000), mid), 3, c-conf)
  note((X(3000) - 0.12, top + 0.2), [snapshot: 48 voters, \ 32 for $B_s$], c-conf, anchor: "south-east")
  // 4: adversary's late votes
  dot((X(3200), bot), 4, c-late)
  line((X(3200), bot + 0.2), (X(3400), mid - 0.2), stroke: 0.9pt + c-late, mark: (end: ">", fill: c-late, scale: 0.6))
  line((X(3200), bot + 0.2), (X(3400), top - 0.2), stroke: 0.9pt + c-late, mark: (end: ">", fill: c-late, scale: 0.6))
  note((X(3200) + 0.25, bot - 0.08), [16 votes for $B_(s-1)$ (3200 ms)], c-late, anchor: "north-west")
  // 5: view freeze
  dot((X(4500), top), 5, c-late)
  dot((X(4500), mid), 5, c-late)
  note((X(4500) - 0.12, top + 0.2), [view: 64 voters, \ 32 for $B_s$: \ not a majority], c-late, anchor: "south-east")
  // 6: next slot
  dot((X(6000), top), 6, c-merge)
  dot((X(6000), mid), 6, c-merge)
  note((X(6000) - 0.12, top + 0.2), [$C_(s+1)$ built \ on $B_(s-1)$], c-merge, anchor: "south-east")
  note((X(7500) - 0.05, mid - 0.12), [all vote $C_(s+1)$], c-vote, anchor: "north-east")
  // 7: delayed confirmation
  dot((X(9000), top), 7, c-lock)
  dot((X(9000), mid), 7, c-lock)
  note((X(9000) - 0.12, top + 0.2), [*confirm $B_s$*, \ from the snapshot], c-lock, anchor: "south-east")
})

#let sync-attack-tree() = cetz.canvas(length: 1cm, {
  import cetz.draw: *
  let blk(p, name, body, col, dashed: false) = {
    rect((p.at(0) - 0.75, p.at(1) - 0.32), (p.at(0) + 0.75, p.at(1) + 0.32), radius: 0.08,
      stroke: (paint: col, thickness: 1pt, dash: if dashed { "dashed" } else { none }), fill: col.lighten(85%), name: name)
    content(p, text(size: 8pt, body))
  }
  blk((0, 0), "p", $B_(s-1)$, luma(80))
  blk((3, 0.6), "b", $B_s$, c-lock, dashed: true)
  blk((3, -0.6), "c", $C_(s+1)$, c-vote)
  line("p.east", "b.west", stroke: 0.8pt + luma(120))
  line("p.east", "c.west", stroke: 0.8pt + luma(120))
  content((3.9, 0.6), text(size: 6.8pt, fill: c-lock.darken(15%))[slot $s$, adversary's block: \ *confirmed* at $t_(s+1) + 2Delta$, but *orphaned*], anchor: "west")
  content((3.9, -0.6), text(size: 6.8pt, fill: c-vote.darken(20%))[slot $s + 1$, honest block: \ on the final chain], anchor: "west")
})
