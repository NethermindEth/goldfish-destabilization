#!/bin/bash
# The adversary study in one go: every targeted attack, its controls, and the threshold comparison.
# Run from goldilocks/:  bash attack_suite.sh
r() {
  name=$1
  shift
  printf '%-34s ' "$name"
  python3 adversary.py --quiet "$@" 2>&1 | grep -E "n_tsq|n_dropped|lock_conflict_slots|final_F|^VIOL|^ok" | tr -s ' \n' ' '
  echo
}
r "passive" --strategy passive --seed 7
r "split (PR4 timing)" --strategy split --seed 7
r "equiv" --strategy equiv --seed 7
r "equiv, first-seen gossip" --strategy equiv --seed 7 --relay first-seen
r "equiv, first-seen gossip, > n/2" --strategy equiv --seed 7 --relay first-seen --fast-strict
r "skew_fast, no skew" --strategy skew_fast --seed 7 --round-start --group-a 0
r "skew_fast, skew 2 ms" --strategy skew_fast --seed 7 --round-start --group-a 0 --skew 0:2
r "skew_fast, skew 2 ms, > n/2" --strategy skew_fast --seed 7 --round-start --group-a 0 --skew 0:2 --fast-strict
r "skew_freeze, no skew" --strategy skew_freeze --seed 7 --round-start --group-a 0
r "skew_freeze, skew 2 ms" --strategy skew_freeze --seed 7 --round-start --group-a 0 --skew 1:2,2:2,3:2
r "skew_freeze, skew 2 ms, > n/2" --strategy skew_freeze --seed 7 --round-start --group-a 0 --skew 1:2,2:2,3:2 --fast-strict
r "skew_fast, 500 ms, relay 1000" --strategy skew_fast --seed 7 --round-start --group-a 0 --skew 0:500 --relay-ms 1000
r "skew_fast, 500 ms, relay 1100" --strategy skew_fast --seed 7 --round-start --group-a 0 --skew 0:500 --relay-ms 1100
r "skew_freeze, 500 ms, relay 1000" --strategy skew_freeze --seed 7 --round-start --group-a 0 --skew 1:500,2:500,3:500 --relay-ms 1000
r "skew_freeze, 500 ms, relay 1100" --strategy skew_freeze --seed 7 --round-start --group-a 0 --skew 1:500,2:500,3:500 --relay-ms 1100
