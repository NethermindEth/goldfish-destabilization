#!/bin/bash
# The Goldilocks explorer: every experiment on this protocol, one tab each, with an About card.
# Run from simulator/goldilocks/:
#   bash build_explorer.sh         -> data/runs/ (the runs) and explorer/goldilocks-explorer.html
#   bash build_explorer.sh --new   -> also explorer/goldilocks-explorer-new.html (the newer UI: per-slot
#                                     state, events and messages of one run at a time)
# Every run is seeded, so a rebuild gives the same pages.
set -e
R=data/runs
mkdir -p "$R" explorer

# The partition study (scenarios.py), only the runs that have a tab.
python3 scenarios.py --out "$R" \
  --only honest,p50_s48_d16,p75_s48_d16,p52_s48_d16,p50_s48_d64,p50_s48_d16_spread,glitch_s48_d1,sleep50_s48_d16 > /dev/null
rm -f "$R"/*.log

a() {
  name=$1
  shift
  python3 adversary.py --quiet "$@" --events "$R/$name.events.json" --json "$R/$name.json" > /dev/null
}
SEQ="--strategy fin_hide_seq --seed 7 --group-a 0,1,2 --relay-ms 200 --slots 64"
a adv_silent --strategy passive --seed 7 --slots 64
a adv_equiv --strategy equiv --seed 7 --slots 64
a adv_twoface --strategy twoface --seed 7 --cut 48:16 --group-a 0,1 --post reveal --slots 80
a fin_hide --strategy fin_hide --seed 13 --group-a 0,1,2 --relay-ms 200 --slots 48
a fin_hide_strict --strategy fin_hide --seed 13 --group-a 0,1,2 --relay-ms 200 --slots 48 --fast-strict --late-z proposer
a fin_hide_fix --strategy fin_hide --seed 13 --group-a 0,1,2 --relay-ms 200 --slots 48 --refused-votes
a fin_hide_seq $SEQ
a fin_hide_seq_first_seen $SEQ --relay first-seen
a fin_hide_seq_forwarding $SEQ --relay-carried
a fin_hide_df --strategy fin_hide_df --seed 17 --group-a 0,1,2 --relay-ms 200 --slots 64 --delta-f-ms 12000
a late_j --strategy late_j --seed 0 --group-a 0,1 --cut 50:8 --slots 112
a outage_3 --strategy outage --seed 0 --outage-tau 10500 --outage-slots 3 --slots 64
a outage_3_75 --strategy outage --seed 0 --outage-tau 10500 --outage-slots 3.75 --slots 64

TABS=(
  "01 Honest Run=$R/honest.events.json"
  "02 Partition 50/50=$R/p50_s48_d16.events.json"
  "03 Partition 75/25=$R/p75_s48_d16.events.json"
  "04 Partition 52/48=$R/p52_s48_d16.events.json"
  "05 Long Partition 50/50=$R/p50_s48_d64.events.json"
  "06 Messy Heal=$R/p50_s48_d16_spread.events.json"
  "07 One-Slot Glitch at a Round Start=$R/glitch_s48_d1.events.json"
  "08 Half the Network Asleep=$R/sleep50_s48_d16.events.json"
  "09 Silent Adversary=$R/adv_silent.events.json"
  "10 Equivocating Adversary=$R/adv_equiv.events.json"
  "11 Two-Faced Adversary Across a Cut=$R/adv_twoface.events.json"
  "12 Finalization Hiding=$R/fin_hide.events.json"
  "13 Finalization Hiding, Strict Fast Test=$R/fin_hide_strict.events.json"
  "14 Finalization Hiding, Refused-Votes Fix=$R/fin_hide_fix.events.json"
  "15 Finalization Hiding Without Equivocation=$R/fin_hide_seq.events.json"
  "16 Without Equivocation, First-Seen Gossip=$R/fin_hide_seq_first_seen.events.json"
  "17 Without Equivocation, Vote Forwarding=$R/fin_hide_seq_forwarding.events.json"
  "18 Finalization Hiding, Slow Attestations=$R/fin_hide_df.events.json"
  "19 Late Justification Contest=$R/late_j.events.json"
  "20 Outage of 3 Slots=$R/outage_3.events.json"
  "21 Outage of 3.75 Slots=$R/outage_3_75.events.json"
)
python3 explorer_classic.py explorer/goldilocks-explorer.html --meta explorer_meta.json "${TABS[@]}"
if [ "$1" = "--new" ]; then
  python3 explorer.py explorer/goldilocks-explorer-new.html --meta explorer_meta.json "${TABS[@]}"
fi
