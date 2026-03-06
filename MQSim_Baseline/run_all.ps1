Write-Host "Running MQSim Simulations..."
.\MQSim.exe -i ssdconfig_original.xml -w workload_seq_original.xml
.\MQSim.exe -i ssdconfig_original.xml -w workload_rand_original.xml
.\MQSim.exe -i ssdconfig_original.xml -w workload_hotspot_original.xml

.\MQSim.exe -i ssdconfig_modern.xml -w workload_seq_modern.xml
.\MQSim.exe -i ssdconfig_modern.xml -w workload_rand_modern.xml
.\MQSim.exe -i ssdconfig_modern.xml -w workload_hotspot_modern.xml
Write-Host "All simulations complete!"
