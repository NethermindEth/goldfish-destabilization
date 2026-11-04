// Goldilocks textbook. Build: python3 generate_figures.py && typst compile main.typ goldilocks-textbook.pdf
#import "style.typ": *
#set document(title: "Goldilocks — Goldfish with Locks, Composed with a Finality Gadget", author: "Alessandro Bombarda")
#set page(paper: "a4", margin: (x: 2.3cm, y: 2.4cm), numbering: "1")
#set text(size: 10.5pt, lang: "en")
#set par(justify: true, leading: 0.68em)
#set heading(numbering: none)
#show heading.where(level: 1): it => { pagebreak(weak: true); v(0.4em); it; v(0.4em) }
#show heading.where(level: 2): it => { v(0.45em); it; v(0.25em) }
#set table(stroke: 0.5pt + luma(180), inset: 5pt)
#show table: set text(size: 9.5pt)
#show table: set par(justify: false)
#show figure.caption: set text(size: 9pt)

#align(center)[
  #v(2.6cm)
  #text(size: 24pt, weight: "bold")[Goldilocks]
  #v(0.35em)
  #text(size: 14pt)[Goldfish with Locks, Composed with a Finality Gadget]
  #v(1.1em)
  #text(size: 11pt)[A Progressive Course, with First Experiments]
  #v(0.25em)
  #text(size: 10pt, fill: luma(90))[Textbook Edition · October 2026 · companion to the Decoupled Consensus textbook]
  #v(0.4em)
  #text(size: 10pt, fill: luma(90))[Alessandro Bombarda · Nethermind Research Internship]
  #v(1.4cm)
  #block(width: 86%)[
    #set align(left)
    #set text(size: 10pt)
    *Sources.* The protocol is the one of the FGSA specification "Goldilocks" (PDF dated 22 October 2026) and of the design slides "Goldilocks: Goldfish with locks, composed with a finality gadget" (21 October 2026), both linked from the EIP-8453 hub. The upstream executable specification (`ethereum/consensus-specs`, branch `decoupled-consensus`, `specs/_features/eip8453`) covers the beacon-chain side of the finality gadget only; the available chain is not yet executable there. References of the form _(spec F8.18)_ point at figure 8, line 18 of the FGSA pseudocode.

    *How this book relates to the previous one.* The Decoupled Consensus textbook explained Goldfish with a stabilization gadget (G0, G1, TSQ) and Simplex finality. Goldilocks keeps the decoupled structure but removes the stabilization gadget: locks move asynchrony resilience from the round layer into the committee layer, and attestations become pure finality votes. Chapter 1 lists exactly what changed. The chapters then follow the order of the old book: model, finality, fork choice, confirmation, healing.

    *Rules versus claims versus measurements.* We separate what a node computes (the rules, fully specified), what the design claims across nodes (from the slides, not yet proved in a paper), and what our executable model measured (Chapter 9). Open points are collected in Chapter 10.
  ]
]
#pagebreak()
#outline(indent: auto, depth: 2)

#include "ch1-why.typ"
#include "ch2-model.typ"
#include "ch3-fg.typ"
#include "ch4-frame.typ"
#include "ch5-goldfish.typ"
#include "ch6-locks.typ"
#include "ch7-restart.typ"
#include "ch8-healing.typ"
#include "ch9-experiments.typ"
#include "ch10-open.typ"
