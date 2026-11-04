#!/bin/bash
# The Goldilocks runs in the old protocol's explorer UI (explorer_classic.py). Needs the runs that
# build_explorer.sh writes. Run from goldilocks/:  bash build_classic.sh
#   -> results/explorer/goldilocks-classic.html
set -e
F=results/first
O=results/explorer
python3 explorer_classic.py "$O/goldilocks-classic.html" --meta explorer_meta.json \
  "01 honest=$F/honest.events.json" \
  "02 partition 50-50=$F/p50_s48_d16.events.json" \
  "03 partition 75-25=$F/p75_s48_d16.events.json" \
  "04 partition 52-48=$F/p52_s48_d16.events.json" \
  "05 long cut 50-50=$F/p50_s48_d64.events.json" \
  "06 messy heal=$F/p50_s48_d16_spread.events.json" \
  "07 one-slot glitch at a round start=$F/glitch_s48_d1.events.json" \
  "08 half asleep=$F/sleep50_s48_d16.events.json" \
  "09 adversary: silent=$O/adv_silent.events.json" \
  "10 adversary: equivocation=$O/adv_equiv.events.json" \
  "11 adversary: two-faced across a cut=$O/adv_twoface.events.json"
