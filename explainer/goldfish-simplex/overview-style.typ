// Two builds from one source:
//   typst compile main.typ                          -> internal version (with Part V)
//   typst compile --input share=true main.typ out   -> shareable version
#let SHARE = sys.inputs.at("share", default: "false") == "true"

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
#let tag(t) = text(size: 8pt, fill: luma(110))[\[#t\]]
// Mechanism colors, used consistently for Goldfish / TSQ / proposer / finality.
#let c-gold = rgb("#1f7a6d")
#let c-tsq = rgb("#6a3d9a")
#let c-prop = rgb("#c4661f")
#let c-fin = rgb("#1d5f9e")

#let pill(label, color) = box(
  fill: color, inset: (x: 6pt, y: 3pt), radius: 8pt, baseline: 25%,
)[#text(fill: white, size: 8pt, weight: "bold")[#label]]

// Grid cells (not blocks), so every cell in a row shares the row's height.
#let lane-cell(color, body) = grid.cell(
  fill: color.lighten(88%), stroke: 0.6pt + color.lighten(35%), inset: 6pt, align: left,
)[#set text(size: 8.8pt); #set par(justify: false, leading: 0.55em); #body]

#let lane-empty = grid.cell(inset: 6pt, align: center + horizon)[
  #text(fill: luma(185), size: 9pt)[·]
]

#let lane-head(body) = grid.cell(inset: (x: 2pt, bottom: 3pt), align: bottom)[
  #set text(size: 8.5pt, weight: "bold", fill: luma(70)); #set par(justify: false); #body
]

#let lane-label(label, color) = grid.cell(align: horizon + right, inset: (right: 2pt))[
  #pill(label, color)
]

// A row of cards, optionally joined by arrows; never split across pages.
#let card-row(..cards, arrows: false) = {
  let items = cards.pos()
  let cols = if arrows { items.map(_ => 1fr).intersperse(auto) } else { items.map(_ => 1fr) }
  let cells = if arrows {
    items.intersperse(grid.cell(align: center + horizon, inset: 2pt)[
      #text(size: 15pt, fill: luma(130))[→]
    ])
  } else { items }
  block(breakable: false, width: 100%, grid(columns: cols, column-gutter: if arrows { 0pt } else { 8pt }, ..cells))
}

#let rule-box(title, body) = block(
  fill: rgb("#fff8e1"), stroke: 1pt + rgb("#d4a017"), inset: 10pt, radius: 4pt, width: 100%,
)[#text(size: 8.5pt, weight: "bold", fill: rgb("#8a6500"))[#upper(title)] \ #v(-2pt) #body]

#let step-card(time, title, color, body) = grid.cell(
  fill: color.lighten(90%), stroke: 0.8pt + color, inset: 8pt,
)[
  #text(size: 8pt, weight: "bold", fill: color.darken(15%))[#time] \
  #text(weight: "bold", size: 9.5pt)[#title]
  #v(-4pt)
  #set text(size: 8.8pt); #set par(justify: false, leading: 0.55em)
  #body
]

#let diagram(caption, body) = figure(
  block(fill: luma(247), stroke: 0.5pt + luma(200), inset: 8pt, radius: 3pt, width: 100%)[
    #set align(left)
    #show raw: set text(size: 5.9pt)
    #body
  ],
  caption: caption,
  kind: "diagram",
  supplement: [Diagram],
)
