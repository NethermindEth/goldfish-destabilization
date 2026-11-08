// Reuse the original overview's helpers without alteration.
#import "overview-style.typ": *

#let chapter-table(columns: (1fr, 2fr), ..cells) = {
  set text(size: 9.5pt)
  set par(justify: false)
  table(columns: columns, stroke: 0.5pt + luma(180), inset: 5pt, ..cells)
}
#let formula-card(body) = rule-box("The rule", body)
#let mechanism-figure(file, caption) = figure(
  block(width: 100%, breakable: false)[
    #image("figures/" + file, width: 100%)
  ],
  caption: caption, kind: "diagram", supplement: [Diagram],
)
