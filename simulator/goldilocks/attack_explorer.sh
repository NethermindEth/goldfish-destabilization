#!/bin/bash
# Event files of the adversary study and one explorer page for them.
# Run from simulator/goldilocks/:  bash attack_explorer.sh   -> results/adversary/attack-explorer.html
set -e
O=results/adversary/explore
mkdir -p "$O"
e() {
  name=$1
  shift
  python3 adversary.py --quiet --slots 64 "$@" --events "$O/$name.events.json" --json "$O/$name.json" > /dev/null
}
e 1_passive --strategy passive --seed 7
e 2_equiv_faithful --strategy equiv --seed 7
e 3_equiv_first_seen --strategy equiv --seed 7 --relay first-seen
e 4_skew_fast_2ms --strategy skew_fast --seed 7 --round-start --group-a 0 --skew 0:2
e 5_skew_fast_2ms_strict --strategy skew_fast --seed 7 --round-start --group-a 0 --skew 0:2 --fast-strict
e 6_skew_freeze_2ms --strategy skew_freeze --seed 7 --round-start --group-a 0 --skew 1:2,2:2,3:2
e 7_spec_drop_early_250ms --strategy passive --seed 7 --skew 1:250,2:250,3:250 --spec-drop-early
e 8_fin_hide_3_nodes --strategy fin_hide --seed 7 --group-a 0,1,2 --relay-ms 200
e 9_fin_hide_3_nodes_strict --strategy fin_hide --seed 7 --group-a 0,1,2 --relay-ms 200 --fast-strict
python3 explorer.py results/adversary/attack-explorer.html --index "$O"
