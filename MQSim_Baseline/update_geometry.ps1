
$configs = @("ssdconfig_original.xml", "ssdconfig_modern.xml")
foreach ($c in $configs) {
    (Get-Content $c) -replace "<Flash_Channel_Count>.*</Flash_Channel_Count>", "<Flash_Channel_Count>1</Flash_Channel_Count>" `
                     -replace "<Chip_No_Per_Channel>.*</Chip_No_Per_Channel>", "<Chip_No_Per_Channel>1</Chip_No_Per_Channel>" `
                     -replace "<Die_No_Per_Chip>.*</Die_No_Per_Chip>", "<Die_No_Per_Chip>1</Die_No_Per_Chip>" `
                     -replace "<Plane_No_Per_Die>.*</Plane_No_Per_Die>", "<Plane_No_Per_Die>1</Plane_No_Per_Die>" `
                     -replace "<Block_No_Per_Plane>.*</Block_No_Per_Plane>", "<Block_No_Per_Plane>256</Block_No_Per_Plane>" | Set-Content $c
}

$workloads = @("workload_seq_original.xml", "workload_rand_original.xml", "workload_hotspot_original.xml", "workload_seq_modern.xml", "workload_rand_modern.xml", "workload_hotspot_modern.xml")
foreach ($w in $workloads) {
    (Get-Content $w) -replace "<Channel_IDs>.*</Channel_IDs>", "<Channel_IDs>0</Channel_IDs>" `
                     -replace "<Chip_IDs>.*</Chip_IDs>", "<Chip_IDs>0</Chip_IDs>" `
                     -replace "<Die_IDs>.*</Die_IDs>", "<Die_IDs>0</Die_IDs>" `
                     -replace "<Plane_IDs>.*</Plane_IDs>", "<Plane_IDs>0</Plane_IDs>" | Set-Content $w
}

