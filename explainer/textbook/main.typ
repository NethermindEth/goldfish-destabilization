// Textbook edition of Decoupled Consensus (leaves explainer/illustrated untouched).
// Build: typst compile main.typ decoupled-consensus-textbook.pdf
#import "overview-style.typ": *
#set document(title: "Decoupled Consensus — A Progressive Course on Goldfish, Stabilization, and Simplex Finality", author: "Alessandro Bombarda")
#set page(paper: "a4", margin: (x: 2.3cm, y: 2.4cm), numbering: "1")
#set text(size: 10.5pt, lang: "en")
#set par(justify: true, leading: 0.68em)
#set heading(numbering: none)
#show heading.where(level: 1): it => {
  v(0.65em)
  it
  v(0.4em)
}
#show heading.where(level: 2): it => {
  v(0.45em)
  it
  v(0.25em)
}
#set table(stroke: 0.5pt + luma(180), inset: 5pt)
#show table: set text(size: 9.5pt)
#show table: set par(justify: false)
#show figure.caption: set text(size: 9pt)

#align(center)[
  #v(2.8cm)
  #text(size: 22pt, weight: "bold")[Decoupled Consensus]
  #v(0.35em)
  #text(size: 14pt)[Goldfish, the Stabilization Gadget, and Simplex Finality]
  #v(1.1em)
  #text(size: 11pt)[A Progressive Course from First Principles]
  #v(0.25em)
  #text(size: 10pt, fill: luma(90))[Textbook Edition · October 2026]
  #v(0.4em)
  #text(size: 10pt, fill: luma(90))[Alessandro Bombarda · Nethermind Research Internship]
  #v(1.6cm)
  #block(width: 86%)[
    #set align(left)
    #set text(size: 10pt)
    *Pedagogical structure.* This monograph is organized like a university course in distributed consensus. Every protocol layer is introduced only after the concrete fault or liveness problem that motivates it has been stated. Definitions, voting rules, and state transitions are developed progressively through self-contained numerical examples and diagrams, without implementation jargon or forward references to undefined concepts.

    *Rules versus proofs.* Throughout the text, we distinguish between *what a single node computes locally* (which is completely defined by the protocol rules) and *what is proved across nodes under network faults* (where open theoretical questions are explicitly noted and collected in Chapter 10).
  ]
]
#pagebreak()
#outline(indent: auto, depth: 2)
#pagebreak()
#include "chapter.typ"
