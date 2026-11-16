#!/bin/bash
# The explorer page of the available chain alone: the partition and sleep study on this model, one
# tab each, with an About card. It uses the explorer of ../goldilocks (explorer_classic.py --spec ac)
# and writes the page next to the other two:
#   ../goldilocks/explorer/goldilocks-ac-explorer.html
# Run from simulator/goldilocks-ac/:  bash build_explorer.sh
# Every run is seeded, so a rebuild gives the same page.
set -e
R=data/runs
mkdir -p "$R"

python3 scenarios.py --out "$R" \
  --only honest,p50_s48_d2,p50_s48_d16,p75_s48_d16,p52_s48_d16,p50_s48_d64,p50_s48_d16_spread,p211_s48_d16,p50_twice,sleep50_s48_d16,sleep75_s48_d16 > /dev/null
rm -f "$R"/*.log

TABS=(
  "01 Honest Run=$R/honest.events.json"
  "02 Two-Slot Cut 50/50=$R/p50_s48_d2.events.json"
  "03 Partition 50/50=$R/p50_s48_d16.events.json"
  "04 Partition 75/25=$R/p75_s48_d16.events.json"
  "05 Partition 52/48=$R/p52_s48_d16.events.json"
  "06 Long Partition 50/50=$R/p50_s48_d64.events.json"
  "07 Messy Heal=$R/p50_s48_d16_spread.events.json"
  "08 Three-Way Cut=$R/p211_s48_d16.events.json"
  "09 Two Cuts in a Row=$R/p50_twice.events.json"
  "10 Half the Network Asleep=$R/sleep50_s48_d16.events.json"
  "11 Three Quarters Asleep=$R/sleep75_s48_d16.events.json"
)
python3 ../goldilocks/explorer_classic.py ../goldilocks/explorer/goldilocks-ac-explorer.html \
  --spec ac --meta explorer_meta.json "${TABS[@]}"
