#!/bin/bash

echo "Starting Baseline SSD Simulation..."
mkdir -p Baseline_Results

# Progress timer — shows elapsed time every 2 seconds while MQSim runs
run_with_progress() {
    local label="$1"
    local cmd="$2"
    local output_file="$3"
    local start
    start=$(date +%s)

    echo "  Starting: $label"

    # Run MQSim in background, capture output to file
    bash -c "$cmd" > "$output_file" 2>&1 &
    local pid=$!

    # Show elapsed time while MQSim is running
    while kill -0 "$pid" 2>/dev/null; do
        local now
        now=$(date +%s)
        local elapsed=$(( now - start ))
        local mins=$(( elapsed / 60 ))
        local secs=$(( elapsed % 60 ))
        printf "\r  [%s] Running... elapsed: %02d:%02d  " "$label" "$mins" "$secs"
        sleep 2
    done

    wait "$pid"
    local exit_code=$?
    local now
    now=$(date +%s)
    local elapsed=$(( now - start ))
    local mins=$(( elapsed / 60 ))
    local secs=$(( elapsed % 60 ))

    if [ $exit_code -eq 0 ]; then
        printf "\r  [%s] Done in %02d:%02d                    \n" "$label" "$mins" "$secs"
    else
        printf "\r  [%s] FAILED after %02d:%02d (exit %d)     \n" "$label" "$mins" "$secs" "$exit_code"
    fi
}

# Run Sequential Workload
run_with_progress "Sequential" \
    "./MQSim -i ssdconfig.xml -w workload_seq.xml" \
    "Baseline_Results/terminal_seq.txt"
mv workload_seq_scenario_1.xml Baseline_Results/data_seq.xml 2>/dev/null

# Run Random Workload
run_with_progress "Random" \
    "./MQSim -i ssdconfig.xml -w workload_rand.xml" \
    "Baseline_Results/terminal_rand.txt"
mv workload_rand_scenario_1.xml Baseline_Results/data_rand.xml 2>/dev/null

# Run Hotspot Workload
run_with_progress "Hotspot (80/20)" \
    "./MQSim -i ssdconfig.xml -w workload_hotspot.xml" \
    "Baseline_Results/terminal_hotspot.txt"
mv workload_hotspot_scenario_1.xml Baseline_Results/data_hotspot.xml 2>/dev/null

echo ""
echo "Simulation Complete! Results saved in Baseline_Results/"
echo ""
echo "--- Quick Results Summary ---"
for f in Baseline_Results/terminal_*.txt; do
    echo ""
    echo ">> $f"
    grep -E "Throughput|Latency|GC|WAF|Request" "$f" 2>/dev/null | head -20 || cat "$f"
done
