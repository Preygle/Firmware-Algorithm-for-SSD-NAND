#!/bin/bash

echo "Starting Baseline SSD Simulation..."

# Create a folder to store the results cleanly
mkdir -p Baseline_Results

# Run Sequential Workload
echo "Running Sequential Workload..."
./MQSim -i ssdconfig.xml -w workload_seq.xml > Baseline_Results/terminal_seq.txt
mv workload_seq_scenario_1.xml Baseline_Results/data_seq.xml

# Run Random Workload
echo "Running Random Workload..."
./MQSim -i ssdconfig.xml -w workload_rand.xml > Baseline_Results/terminal_rand.txt
mv workload_rand_scenario_1.xml Baseline_Results/data_rand.xml

# Run Hotspot Workload
echo "Running 80/20 Hotspot Workload..."
./MQSim -i ssdconfig.xml -w workload_hotspot.xml > Baseline_Results/terminal_hotspot.txt
mv workload_hotspot_scenario_1.xml Baseline_Results/data_hotspot.xml

echo "Simulation Complete! All results saved in the 'Baseline_Results' folder."
