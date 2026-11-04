#!/bin/bash
# The adversary study in one go: every targeted attack, its controls, and the threshold comparison.
# Run from goldilocks/:  bash attack_suite.sh
r() {
  name=$1
  shift
  printf '%-34s ' "$name"
  python3 adversary.py --quiet "$@" 2>&1 | grep -E "n_orphaned_any_tick|n_tsq|n_dropped|lock_conflict_slots|final_F|^VIOL|^ok" | tr -s ' \n' ' '
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
# The in-model result: synchrony, perfect clocks, everything relayed, 200 ms honest relay.
r "fin_hide, node 0 fooled" --strategy fin_hide --seed 7 --group-a 0 --relay-ms 200
r "fin_hide, nodes 0-2 fooled" --strategy fin_hide --seed 7 --group-a 0,1,2 --relay-ms 200
r "fin_hide, nodes 0-2, > n/2" --strategy fin_hide --seed 7 --group-a 0,1,2 --relay-ms 200 --fast-strict
r "fin_hide, > n/2, late Z votes" --strategy fin_hide --seed 7 --group-a 0,1,2 --relay-ms 200 --fast-strict --late-z freeze
r "fin_hide + refused-votes fix" --strategy fin_hide --seed 7 --group-a 0,1,2 --relay-ms 200 --refused-votes
r "fin_hide, > n/2, late Z + fix" --strategy fin_hide --seed 7 --group-a 0,1,2 --relay-ms 200 --fast-strict --late-z freeze --refused-votes
