# MQSim Original Parameters Backup

Backup of all original parameter values before any optimization changes.
Keep this file for reference when you want to restore full-scale simulation settings.

---

## ssdconfig.xml — Original Values

| Parameter | Original Value | Changed To |
|---|---|---|
| `Block_No_Per_Plane` | `2048` | `256` |
| `Page_No_Per_Block` | `256` | `64` |
| `Flash_Channel_Count` | `8` | *(unchanged)* |
| `Chip_No_Per_Channel` | `4` | *(unchanged)* |
| `Die_No_Per_Chip` | `2` | *(unchanged)* |
| `Plane_No_Per_Die` | `2` | *(unchanged)* |
| `Page_Capacity` | `8192` | *(unchanged)* |
| `GC_Exec_Threshold` | `0.05` | *(unchanged)* |
| `Overprovisioning_Ratio` | `0.07` | *(unchanged)* |
| `Flash_Technology` | `MLC` | *(unchanged)* |
| `Block_PE_Cycles_Limit` | `10000` | *(unchanged)* |

### Original Total Drive Size
```
8 channels × 4 chips × 2 dies × 2 planes × 2048 blocks × 256 pages × 8192 B/page
= ~67 million pages = ~512 GB simulated NAND
```

### Current (Reduced) Drive Size
```
8 channels × 4 chips × 2 dies × 2 planes × 256 blocks × 64 pages × 8192 B/page
= ~1 million pages = ~8 GB simulated NAND
```

---

## workload_seq.xml — Original Values

| Parameter | Original Value | Changed To |
|---|---|---|
| `Initial_Occupancy_Percentage` | `75` | *(unchanged — reduce to 10 for faster runs)* |
| `Stop_Time` | `10000000000` | `0` |
| `Total_Requests_To_Generate` | `1000000` | `100000` |
| `Average_Request_Size` | `128` | *(unchanged)* |
| `Address_Distribution` | `STREAMING` | *(unchanged)* |

---

## workload_rand.xml — Original Values

| Parameter | Original Value | Changed To |
|---|---|---|
| `Initial_Occupancy_Percentage` | `75` | *(unchanged — reduce to 10 for faster runs)* |
| `Stop_Time` | `10000000000` | `0` |
| `Total_Requests_To_Generate` | `1000000` | `100000` |
| `Average_Request_Size` | `8` | *(unchanged)* |
| `Address_Distribution` | `UNIFORM_RANDOM` | *(unchanged)* |

---

## workload_hotspot.xml — Original Values

| Parameter | Original Value | Changed To |
|---|---|---|
| `Initial_Occupancy_Percentage` | `75` | *(unchanged — reduce to 10 for faster runs)* |
| `Stop_Time` | `10000000000` | `0` |
| `Total_Requests_To_Generate` | `1000000` | `100000` |
| `Average_Request_Size` | `8` | *(unchanged)* |
| `Address_Distribution` | `HOTCOLD` |  *(unchanged)* |
| `Percentage_of_Hot_Region` | `20` | *(unchanged)* |

---

## To Restore Full-Scale Simulation

Apply these values back to `ssdconfig.xml`:
```xml
<Block_No_Per_Plane>2048</Block_No_Per_Plane>
<Page_No_Per_Block>256</Page_No_Per_Block>
```

And in each workload XML:
```xml
<Stop_Time>10000000000</Stop_Time>
<Total_Requests_To_Generate>1000000</Total_Requests_To_Generate>
```
