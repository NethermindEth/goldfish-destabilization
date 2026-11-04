// Shared look of the Goldilocks textbook; same boxes as explainer/textbook/overview-style.typ.
#let box-colored(title, color, body) = block(
  fill: color.lighten(88%),
  stroke: (left: 3pt + color),
  inset: (x: 10pt, y: 8pt),
  radius: (right: 3pt),
  width: 100%,
  breakable: false,
)[#text(weight: "bold", fill: color.darken(20%))[#title] \ #body]
#let problem(body) = box-colored("The problem", rgb("#b03a2e"), body)
#let idea(body) = box-colored("The idea", rgb("#1f7a4d"), body)
#let example(body) = box-colored("Worked example", rgb("#1d5f9e"), body)
#let caveat(body) = box-colored("Caveat", rgb("#9a6b00"), body)
#let recap(body) = box-colored("Recap", rgb("#5b4b8a"), body)
#let observed(body) = box-colored("Observed in the simulator", rgb("#c4661f"), body)

// Mechanism colours (also used by generate_figures.py): Goldfish, lock, FG, proposer.
#let c-gold = rgb("#1f7a6d")
#let c-lock = rgb("#b07d00")
#let c-fin = rgb("#1d5f9e")
#let c-prop = rgb("#c4661f")

#let rule-box(title, body) = block(
  fill: rgb("#fff8e1"), stroke: 1pt + rgb("#d4a017"), inset: 10pt, radius: 4pt, width: 100%, breakable: false,
)[#text(size: 8.5pt, weight: "bold", fill: rgb("#8a6500"))[#upper(title)] \ #v(-2pt) #body]
#let formula-card(body) = rule-box("The rule", body)

#let chapter-table(columns: (1fr, 2fr), ..cells) = {
  set text(size: 9.5pt)
  set par(justify: false)
  table(columns: columns, stroke: 0.5pt + luma(180), inset: 5pt, ..cells)
}
#let fig(file, caption, width: 100%) = figure(
  block(width: 100%, breakable: false)[#image("figures/" + file, width: width)],
  caption: caption, kind: "diagram", supplement: [Diagram],
)
#let specref(s) = text(size: 8.5pt, fill: luma(110))[(spec #s)]
