# Decoupled Consensus — Textbook Edition

This directory (`explainer/textbook/`) is a standalone, progressive textbook edition of the illustrated protocol explanation. The original `explainer/illustrated/` directory is left completely untouched.

- `decoupled-consensus-textbook.pdf` (and `decoupled-consensus-illustrated.pdf`): compiled 41-page textbook edition.
- `main.typ`: document entry point, preface, and outline.
- `chapter.typ`: full progressive course with strict dependency order, clean `The problem` / `The idea` separation, worked examples, and recaps.
- `generate_figures.py` & `figures/`: SVG diagrams with forward-jargon removed from early chapters.

## Building

```sh
python3 generate_figures.py
typst compile main.typ decoupled-consensus-textbook.pdf
cp decoupled-consensus-textbook.pdf decoupled-consensus-illustrated.pdf
```
