#!/bin/bash
# FULL-SCALE SIMULATION — Original parameters
# Drive: 8ch x 4chip x 2die x 2plane x 2048 blocks x 256 pages (~67M pages)
# Requests: 1,000,000 per workload | Occupancy: 75%
# WARNING: This will take a long time (potentially 30-60+ min per workload)

echo "=============================================="
echo "  FULL-SCALE BASELINE SIMULATION"
echo "  Drive: 2048 blocks x 256 pages (original)"
echo "  Requests: 1,000,000 per workload"
echo "  Occupancy: 75%"
echo "=============================================="
echo ""

mkdir -p Baseline_Results/fullscale

run_with_progress() {
    local label="$1"
    local cmd="$2"
    local output_file="$3"
    local start
    start=$(date +%s)

    echo "  Starting: $label"
    bash -c "$cmd" > "$output_file" 2>&1 &
    local pid=$!

    while kill -0 "$pid" 2>/dev/null; do
        local now
        now=$(date +%s)
        local elapsed=$(( now - start ))
        local mins=$(( elapsed / 60 ))
        local secs=$(( elapsed % 60 ))
        printf "\r  [%s] Running... elapsed: %02d:%02d  " "$label" "$mins" "$secs"
        sleep 5
    done

    wait "$pid"
    local exit_code=$?
    local elapsed=$(( $(date +%s) - start ))
    local mins=$(( elapsed / 60 ))
    local secs=$(( elapsed % 60 ))

    if [ $exit_code -eq 0 ]; then
        printf "\r  [%s] DONE in %02d:%02d                      \n" "$label" "$mins" "$secs"
    else
        printf "\r  [%s] FAILED after %02d:%02d (exit %d)       \n" "$label" "$mins" "$secs" "$exit_code"
    fi
}

# Run Sequential
run_with_progress "Sequential (1M)" \
    "./MQSim -i ssdconfig_original.xml -w workload_seq_original.xml" \
    "Baseline_Results/fullscale/out_seq.txt"
mv workload_seq_original_scenario_1.xml Baseline_Results/fullscale/data_seq.xml 2>/dev/null

# Run Random
run_with_progress "Random (1M)" \
    "./MQSim -i ssdconfig_original.xml -w workload_rand_original.xml" \
    "Baseline_Results/fullscale/out_rand.txt"
mv workload_rand_original_scenario_1.xml Baseline_Results/fullscale/data_rand.xml 2>/dev/null

# Run Hotspot
run_with_progress "Hotspot 80/20 (1M)" \
    "./MQSim -i ssdconfig_original.xml -w workload_hotspot_original.xml" \
    "Baseline_Results/fullscale/out_hotspot.txt"
mv workload_hotspot_original_scenario_1.xml Baseline_Results/fullscale/data_hotspot.xml 2>/dev/null

echo ""
echo "=============================================="
echo "  SIMULATION COMPLETE"
echo "  Results saved in: Baseline_Results/fullscale/"
echo "=============================================="
echo ""
echo "--- Summary ---"
for f in Baseline_Results/fullscale/out_*.txt; do
    echo ""
    echo ">> $(basename $f)"
    grep -E "requests generated|response time|end-to-end" "$f" 2>/dev/null
done
