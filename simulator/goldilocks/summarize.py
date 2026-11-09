"""Summarize fuzz_batch.py outputs of the finalization-hiding attacks: how many schedules gave the
adversary its slots, how many attacks fooled a node, and for how long the orphaned block was shown.

Run:  python summarize.py data/batches/*.json
"""

import json
import sys


def main():
    for path in sys.argv[1:]:
        rows = json.load(open(path))
        if not isinstance(rows, list) or not rows or "notes" not in rows[0]:
            continue
        setup = [r for r in rows if any("setup ok" in n for n in r["notes"])]
        hit = [r for r in setup if any(v for v in r["orphaned_shown_ms"].values())]
        shown = sorted(max(max(v) for v in r["orphaned_shown_ms"].values() if v) for r in hit)
        nodes = sorted(sum(1 for v in r["orphaned_shown_ms"].values() if v) for r in hit)
        other = [r for r in rows if r.get("bad") and r not in hit]
        line = f"{path.split('/')[-1]:28s} schedules {len(rows):5d}  attacked {len(setup):4d}  succeeded {len(hit):4d}"
        if hit:
            line += f"  shown {shown[0] / 1000:g}-{shown[-1] / 1000:g} s  nodes fooled {nodes[0]}-{nodes[-1]}"
        if other:
            line += f"  other violations {len(other)}"
        errors = sum(1 for r in rows if "error" in r)
        if errors:
            line += f"  crashed {errors}"
        print(line)


if __name__ == "__main__":
    main()
