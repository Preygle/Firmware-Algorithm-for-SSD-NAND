#!/bin/bash
# MINIMAL TEST RUN — tiny drive + 1000 requests
# Expected completion: ~10-30 seconds total

echo "=== MINIMAL TEST SIMULATION ==="
echo "Drive: 4ch x 2chip x 1die x 1plane x 32blocks x 32pages"
echo "Requests: 1,000 per workload | Occupancy: 10%"
echo ""

mkdir -p Baseline_Results/minimal

# Progress timer
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
        printf "\r  [%s] Running... elapsed: %02d:%02d  " "$label" $(( elapsed / 60 )) $(( elapsed % 60 ))
        sleep 1
    done

    wait "$pid"
    local exit_code=$?
    local elapsed=$(( $(date +%s) - start ))
    if [ $exit_code -eq 0 ]; then
        printf "\r  [%s] Done in %02d:%02d                    \n" "$label" $(( elapsed / 60 )) $(( elapsed % 60 ))
    else
        printf "\r  [%s] FAILED (exit %d)                   \n" "$label" "$exit_code"
    fi
}

run_with_progress "Sequential (minimal)" \
    "./MQSim -i ssdconfig_minimal.xml -w workload_minimal_seq.xml" \
    "Baseline_Results/minimal/out_seq.txt"
mv workload_minimal_seq_scenario_1.xml Baseline_Results/minimal/data_seq.xml 2>/dev/null

run_with_progress "Random (minimal)" \
    "./MQSim -i ssdconfig_minimal.xml -w workload_minimal_rand.xml" \
    "Baseline_Results/minimal/out_rand.txt"
mv workload_minimal_rand_scenario_1.xml Baseline_Results/minimal/data_rand.xml 2>/dev/null

echo ""
echo "=== TEST COMPLETE — Full Output ==="
echo ""
echo "--- Sequential ---"
cat Baseline_Results/minimal/out_seq.txt
echo ""
echo "--- Random ---"
cat Baseline_Results/minimal/out_rand.txt
