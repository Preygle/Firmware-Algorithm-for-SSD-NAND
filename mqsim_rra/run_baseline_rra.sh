#!/bin/bash
# run_baseline_rra.sh
# =====================
# Runs BASELINE simulation using the proven MQSim_Baseline configs.
# Results saved to mqsim_rra/results/baseline/
#
# NOTE: ssdconfig_baseline.xml from mqsim_rra uses a different XML schema
# than the MQSim_Baseline binary. This script uses the working
# ssdconfig_original.xml + workload_*_original.xml instead.
#
# Usage:
#   sed -i 's/\r//' run_baseline_rra.sh && bash run_baseline_rra.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MQSIM="$REPO_ROOT/MQSim_Baseline/MQSim"
CONFIGS="$REPO_ROOT/MQSim_Baseline"
RESULTS="$SCRIPT_DIR/results/baseline"

echo "============================================================"
echo "  BASELINE FTL SIMULATION  (GREEDY GC — No Wear Leveling)"
echo "  MQSim  : $MQSIM"
echo "  Config : ssdconfig_original.xml (2048 blk x 256 pg)"
echo "  Requests: 1,000,000 per workload | Occupancy: 25%"
echo "============================================================"
echo ""

if [ ! -f "$MQSIM" ]; then
    echo "ERROR: MQSim binary not found at: $MQSIM"
    exit 1
fi

mkdir -p "$RESULTS"
cd "$CONFIGS" || exit 1

# ── Progress timer ─────────────────────────────────────────────────────────
run_with_progress() {
    local label="$1"
    local workload="$2"
    local out_txt="$3"
    local data_dest="$4"
    local start
    start=$(date +%s)

    echo "  Starting: $label"
    "$MQSIM" -i "ssdconfig_original.xml" -w "$workload" > "$out_txt" 2>&1 &
    local pid=$!

    while kill -0 "$pid" 2>/dev/null; do
        local elapsed=$(( $(date +%s) - start ))
        printf "\r  [%s] Running... %02d:%02d  " "$label" $(( elapsed/60 )) $(( elapsed%60 ))
        sleep 3
    done

    wait "$pid"; local ec=$?
    local elapsed=$(( $(date +%s) - start ))
    if [ $ec -eq 0 ]; then
        printf "\r  [%s] DONE in %02d:%02d                     \n" "$label" $(( elapsed/60 )) $(( elapsed%60 ))
    else
        printf "\r  [%s] FAILED (exit %d)\n" "$label" "$ec"
    fi

    # MQSim drops the scenario XML in the CWD (MQSim_Baseline/)
    local base
    base=$(basename "$workload" .xml)
    if [ -f "${base}_scenario_1.xml" ]; then
        mv "${base}_scenario_1.xml" "$data_dest"
    fi
}

# ── Run all 3 workloads ───────────────────────────────────────────────────
run_with_progress \
    "Sequential  (25% pre-fill)" \
    "workload_seq_original.xml" \
    "$RESULTS/out_seq.txt" \
    "$RESULTS/data_seq_baseline.xml"

run_with_progress \
    "Random      (25% pre-fill)" \
    "workload_rand_original.xml" \
    "$RESULTS/out_rand.txt" \
    "$RESULTS/data_rand_baseline.xml"

run_with_progress \
    "Hotspot 80/20 (25% pre-fill)" \
    "workload_hotspot_original.xml" \
    "$RESULTS/out_hotspot.txt" \
    "$RESULTS/data_hotspot_baseline.xml"

echo ""
echo "============================================================"
echo "  BASELINE COMPLETE — Results saved to: $RESULTS"
echo "============================================================"
echo ""

for f in "$RESULTS"/out_*.txt; do
    echo ">> $(basename "$f")"
    grep -E "requests generated|response time|ERROR" "$f" 2>/dev/null
    echo ""
done

echo "Next:"
echo "  Run RRA-FTL build, then: python plot_comparison.py"
