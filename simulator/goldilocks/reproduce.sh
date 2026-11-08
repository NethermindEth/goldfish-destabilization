#!/bin/bash
# Every number of the finalization-hiding report (reports/goldilocks-finalization-hiding/) and of
# the follow-ups (fin_hide_df, outage), regenerated into data/batches/. Each batch is one
# fuzz_batch.py file (every run keeps its argv); the drivers that only print write a .txt.
# Run from simulator/goldilocks/:  bash reproduce.sh   (about 20 minutes on 12 cores)
#   -> data/batches/*.json, *.txt and data/batches/summary.txt
set -e
O=data/batches
P=${PROCS:-12}
mkdir -p "$O"
b() {
  name=$1
  seeds=$2
  shift 2
  python3 fuzz_batch.py --seeds "$seeds" --procs "$P" --out "$O/$name.json" "$@" > /dev/null
}
FH="--f 21 --strategy fin_hide --group-a 0,1,2 --relay-ms 200"
SEQ="--f 21 --strategy fin_hide_seq --group-a 0,1,2 --relay-ms 200 --slots 160"
DF="--f 21 --strategy fin_hide_df --group-a 0,1,2 --relay-ms 200 --slots 160"

# Section 3.3: fin_hide, with proposer equivocation (120 schedules of 96 slots).
b fin_hide 120 $FH
for r in 1499 200 50 3; do
  b "fin_hide_node0_relay_$r" 120 --f 21 --strategy fin_hide --group-a 0 --relay-ms "$r"
done
b fin_hide_8_nodes 120 --f 21 --strategy fin_hide --nodes 8 --group-a 0 --relay-ms 200
b fin_hide_16_nodes 120 --f 21 --strategy fin_hide --nodes 16 --group-a 0 --relay-ms 200
# Section 3.4: > n/2, the adversary's Z votes at once, just before the view freeze, or only to the
# next proposer.
b fin_hide_strict 120 $FH --fast-strict
b fin_hide_strict_latez_freeze 120 $FH --fast-strict --late-z freeze
b fin_hide_strict_latez 120 $FH --fast-strict --late-z proposer
# Section 3.7 and appendix: the two fixes, when Q reaches node 3 (t_(s+1) + Δ ± 1 ms, 2Δ - 1 ms),
# and Ethereum's first-seen gossip.
b fin_hide_refused_votes 120 $FH --refused-votes
b fin_hide_relay_carried 120 $FH --relay-carried
for q in 1501 2999; do
  b "fin_hide_q_$q" 120 $FH --q-offset "$q"
  b "fin_hide_q_${q}_relay_carried" 120 $FH --q-offset "$q" --relay-carried
done
b fin_hide_first_seen 120 $FH --relay first-seen

# Section 3.5: fin_hide_seq, no equivocation.
b seq 300 $SEQ
b seq_first_seen 300 $SEQ --relay first-seen
b seq_relay_3ms 300 ${SEQ/--relay-ms 200/--relay-ms 3}
b seq_relay_1499ms 300 ${SEQ/--relay-ms 200/--relay-ms 1499}
b seq_8_nodes 300 ${SEQ/--group-a 0,1,2/--nodes 8 --group-a 0,1,2,3,4,5}
b seq_f8 2000 ${SEQ/--f 21 --strategy fin_hide_seq --group-a 0,1,2/--f 8 --strategy fin_hide_seq --group-a 0,1}
b seq_strict 300 $SEQ --fast-strict
b seq_strict_late_w 150 $SEQ --fast-strict --late-z
b seq_refused_votes 300 $SEQ --refused-votes
b seq_relay_carried 300 $SEQ --relay-carried

# Section 3.6: honest proposals orphaned.
python3 honest_orphans.py --seeds 150 --procs "$P" $SEQ > "$O/honest_orphans_seq.txt"
python3 honest_orphans.py --seeds 150 --procs "$P" ${SEQ/fin_hide_seq/passive} > "$O/honest_orphans_passive.txt"
python3 honest_orphans.py --seeds 150 --procs "$P" $SEQ --fast-strict --late-z > "$O/honest_orphans_strict_late_w.txt"
python3 honest_orphans.py --seeds 150 --procs "$P" $SEQ --refused-votes > "$O/honest_orphans_refused_votes.txt"

# fin_hide_df: attestations slower than blocks (PR #13), Δ_F = 1, 2, 4, 8, 16 Δ.
for df in 1500 3000 6000 12000 24000; do
  b "df_$df" 200 $DF --delta-f-ms "$df"
done

# The random adversary stays clean.
b fuzz 200 --f 21 --strategy fuzz

# Asynchrony resilience of a fast confirmation: the outage frontier, k = 4 and k = 6.
python3 outage_sweep.py --seeds 10 --procs "$P" --taus 3,4,5,6,8 --lengths 3,3.5,4,4.5,5 > "$O/outage_k4.txt"
python3 outage_sweep.py --k 6 --seeds 8 --procs "$P" --taus 4,6,7,8 --lengths 4.75,5,5.5,5.75,6 > "$O/outage_k6.txt"

python3 summarize.py "$O"/*.json > "$O/summary.txt"
cat "$O/summary.txt"
