#!/bin/bash
# The Goldilocks explorer: every experiment on this protocol, one tab each, with an About card.
# Run from goldilocks/:  bash build_explorer.sh   -> results/explorer/goldilocks-explorer.html
set -e
F=results/first
O=results/explorer
mkdir -p "$O"
python3 scenarios.py > /dev/null  # the partition study -> results/first/
a() {
  name=$1
  shift
  python3 adversary.py --quiet "$@" --events "$O/$name.events.json" --json "$O/$name.json" > /dev/null
}
a adv_silent --strategy passive --seed 7 --slots 64
a adv_equiv --strategy equiv --seed 7 --slots 64
a adv_twoface --strategy twoface --seed 7 --cut 48:16 --group-a 0,1 --post reveal --slots 80
python3 explorer.py "$O/goldilocks-explorer.html" --meta explorer_meta.json \
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
