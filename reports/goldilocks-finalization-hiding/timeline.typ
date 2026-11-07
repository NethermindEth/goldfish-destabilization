// Slot timelines drawn with cetz: two slots of 4Δ, phase bands for slot s, and labelled events.
#import "@preview/cetz:0.3.4"

#let c-prop = rgb("#c4661f")
#let c-vote = rgb("#1f7a6d")
#let c-late = rgb("#9a6b00")
#let c-merge = rgb("#5b4b8a")
#let c-lock = rgb("#b03a2e")
#let c-conf = rgb("#1d5f9e")

// bands: ((from, to, colour, label), ...) in units of Δ
// events: ((x, row, colour, body), ...); row > 0 above the axis, row < 0 below
// spans: ((from, to, row, colour, label), ...) brackets below the axis, row 1, 2, ...
#let timeline(bands: (), events: (), spans: (), unit: 2.05, slots: 2, rows-above: 3, rows-below: 0) = cetz.canvas(length: unit * 1cm, {
  import cetz.draw: *
  let W = 4 * slots
  let rh = 0.62
  for (a, b, col, lab) in bands {
    rect((a, -0.2), (b, 0.2), fill: col.lighten(80%), stroke: none)
    content(((a + b) / 2, 0), text(size: 5.9pt, fill: col.darken(30%), weight: "bold", lab))
  }
  line((0, -0.2), (W, -0.2), stroke: 0.6pt + luma(120))
  line((0, 0.2), (W, 0.2), stroke: 0.6pt + luma(120))
  for i in range(W + 1) {
    let major = calc.rem(i, 4) == 0
    line((i, -0.2), (i, 0.2), stroke: (if major { 1.3pt } else { 0.5pt }) + luma(90))
  }
  let lab-y = -0.2 - rows-below * rh - 0.28
  for s in range(slots) {
    let x0 = 4 * s
    let name = if s == 0 { $s$ } else { $s + #s$ }
    content((x0 + 2, 0.2 + rows-above * rh + 0.3), text(size: 8pt, weight: "bold")[slot #name])
    for i in range(4) {
      let lab = if i == 0 { $t_#name$ } else if i == 1 { $t_#name + Delta$ } else { $t_#name + #i Delta$ }
      content((x0 + i, lab-y), text(size: 6.6pt, fill: luma(60), lab))
    }
  }
  content((W, lab-y), text(size: 6.6pt, fill: luma(60), $t_(s + #slots)$))
  for (a, b, row, col, lab) in spans {
    let y = -0.2 - row * rh + 0.12
    line((a, y), (b, y), stroke: 1.1pt + col, mark: (start: "|", end: "|"))
    content((a + 0.05, y - 0.04), text(size: 6.2pt, fill: col.darken(20%), lab), anchor: "north-west")
  }
  for (x, row, col, body) in events {
    let y = 0.2 + (row - 0.3) * rh
    line((x, 0.2), (x, y), stroke: 0.6pt + col)
    circle((x, 0.2), radius: 0.05, fill: col, stroke: none)
    content((x, y), box(fill: white, inset: 1.5pt, align(center, text(size: 6.2pt, fill: col.darken(20%), body))),
      anchor: "south")
  }
})
