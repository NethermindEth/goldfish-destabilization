#!/bin/bash
# The explorer page of the live spec: the partition study on this model, one tab each, with an
# About card. It uses the explorer of ../goldilocks (explorer_classic.py --spec live) and writes the
# page next to the 22 Oct page, so that the two link to each other:
#   ../goldilocks/explorer/goldilocks-live-explorer.html
# Run from simulator/goldilocks-live/:  bash build_explorer.sh
# Every run is seeded, so a rebuild gives the same page.
set -e
R=data/runs
mkdir -p "$R"

python3 scenarios.py --out "$R" \
  --only honest,p50_s48_d16,p75_s48_d16,p52_s48_d16,p50_s48_d64,p50_s48_d16_spread,p211_s48_d16,glitch_s48_d1,sleep50_s48_d16 > /dev/null
rm -f "$R"/*.log

TABS=(
  "01 Honest Run=$R/honest.events.json"
  "02 Partition 50/50=$R/p50_s48_d16.events.json"
  "03 Partition 75/25=$R/p75_s48_d16.events.json"
  "04 Partition 52/48=$R/p52_s48_d16.events.json"
  "05 Long Partition 50/50=$R/p50_s48_d64.events.json"
  "06 Messy Heal=$R/p50_s48_d16_spread.events.json"
  "07 Three-Way Cut=$R/p211_s48_d16.events.json"
  "08 One-Slot Glitch at Slot 48=$R/glitch_s48_d1.events.json"
  "09 Half the Network Asleep=$R/sleep50_s48_d16.events.json"
)
python3 ../goldilocks/explorer_classic.py ../goldilocks/explorer/goldilocks-live-explorer.html \
  --spec live --meta explorer_meta.json "${TABS[@]}"
