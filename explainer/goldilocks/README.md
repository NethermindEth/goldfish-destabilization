# Goldilocks — Textbook Edition

A progressive course on Goldilocks (Goldfish with locks, composed with a finality gadget),
in the style of `explainer/goldfish-simplex/`, plus the first experiments with our executable
model (`simulator/goldilocks/`).

- `goldilocks-textbook.pdf`: compiled book (31 pages).
- `main.typ`: title page, sources, outline; includes one file per chapter:
  `ch1-why` (what changed from DC with SG), `ch2-model`, `ch3-fg` (heights, attestations,
  client), `ch4-frame` (fork-choice root, viable heads, contest), `ch5-goldfish` (votes,
  head walk, view merge), `ch6-locks` (confirmation, fast/slow locks, unlocking, anchor,
  `fg_confirmed`), `ch7-restart`, `ch8-healing` (the slides' argument), `ch9-experiments`,
  `ch10-open`.
- `style.typ`: boxes (problem / idea / worked example / caveat / recap / observed) and colours.
- `generate_figures.py`: concept diagrams and the data figures. The data figures re-run their
  scenarios through `simulator/goldilocks/partition_run.py`, so the book rebuilds from committed code.

## Sources

- FGSA spec "Goldilocks", `fgsa-spec-22102026.pdf` (pseudocode, Figures 1–9).
- Slides "Goldilocks: Goldfish with locks, composed with a finality gadget" (21 Oct 2026).
- Both linked from https://hackmd.io/@benjaminion/decoupled-consensus-links.

## Building

```sh
python3 generate_figures.py
typst compile main.typ goldilocks-textbook.pdf
```
