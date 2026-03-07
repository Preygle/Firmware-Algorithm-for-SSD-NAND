# RRA-FTL MQSim Integration Guide
## Reliability-Remaining Adaptive FTL — SanDisk Hackathon 2025

---

## What This Package Contains

```
rra_ftl_mqsim/
│
├── src/ssd/
│   ├── GC_and_WL_Unit_Page_Level_RRA.h      ← RRA-FTL header (novel algorithms)
│   ├── GC_and_WL_Unit_Page_Level_RRA.cpp    ← RRA-FTL implementation
│   └── FTL_RRA_patch.cpp                    ← Exact diff to apply to FTL.cpp
│
├── workloads/
│   ├── trace_sequential.trace               ← 100K sequential writes (MQSim format)
│   ├── trace_random.trace                   ← 100K random writes
│   ├── trace_hotspot.trace                  ← 100K hotspot 80/20 writes
│   ├── workload_sequential.xml              ← MQSim workload XML (sequential)
│   ├── workload_random.xml                  ← MQSim workload XML (random)
│   └── workload_hotspot.xml                 ← MQSim workload XML (hotspot) ← PRIMARY
│
├── ssdconfig_rra.xml                        ← SSD config for RRA-FTL runs
├── ssdconfig_baseline.xml                   ← SSD config for baseline runs
├── Makefile                                 ← Linux build
├── parse_mqsim_output.py                    ← Result parser + comparison
└── README_INTEGRATION.md                    ← This file
```

---

## Step 1 — Clone MQSim

```bash
git clone https://github.com/CMU-SAFARI/MQSim.git
cd MQSim
```

---

## Step 2 — Copy RRA-FTL Files In

```bash
# Copy the two new source files
cp path/to/rra_ftl_mqsim/src/ssd/GC_and_WL_Unit_Page_Level_RRA.h   src/ssd/
cp path/to/rra_ftl_mqsim/src/ssd/GC_and_WL_Unit_Page_Level_RRA.cpp src/ssd/

# Copy workload files
cp -r path/to/rra_ftl_mqsim/workloads/ .

# Copy configs and scripts
cp path/to/rra_ftl_mqsim/ssdconfig_rra.xml .
cp path/to/rra_ftl_mqsim/ssdconfig_baseline.xml .
cp path/to/rra_ftl_mqsim/parse_mqsim_output.py .
```

---

## Step 3 — Patch FTL.cpp (2-line change)

Open `src/ssd/FTL.cpp` and make these two changes:

### 3a. Add include (near top of file, after existing includes)

```cpp
// Existing:
#include "GC_and_WL_Unit_Page_Level.h"

// Add this line directly after it:
#include "GC_and_WL_Unit_Page_Level_RRA.h"   // RRA-FTL
```

### 3b. Replace GC unit constructor call

Search for the line:
```cpp
GC_and_WL_Unit = new GC_and_WL_Unit_Page_Level(
```

Replace it with:
```cpp
GC_and_WL_Unit = new SSD_Components::GC_and_WL_Unit_Page_Level_RRA(
```

Then add four extra arguments at the end of the constructor call,
just before the closing `);`:

```cpp
    // ... all existing arguments stay exactly as-is ...
    gc_and_wl_unit_params->Static_Wearleveling_Threshold,
    10000.0,   // pe_endurance  — must match Max_PE_Cycles in ssdconfig_rra.xml
    1.0,       // initial alpha (efficiency weight)
    1.0,       // initial beta  (Weibull remaining-budget weight)
    1.0        // initial gamma (migration cost penalty weight)
);
```

See `src/ssd/FTL_RRA_patch.cpp` for the complete annotated diff.

**That is the entire change to FTL.cpp.** Everything else — transaction
scheduling, preemptible GC, copyback, address mapping, host interface —
remains 100% vanilla MQSim.

---

## Step 4 — Build

### Linux
```bash
make -j$(nproc)
```

### Windows (Visual Studio)
1. Open `MQSim.vcxproj`
2. Add `src\ssd\GC_and_WL_Unit_Page_Level_RRA.cpp` to the project
3. Build → Release

---

## Step 5 — Run Simulations

### Primary test: Hotspot 80/20 (RRA-FTL wins here)

```bash
# Baseline run (compile WITHOUT the FTL.cpp patch, or use GC_and_WL_Unit_Page_Level directly)
./MQSim -i ssdconfig_baseline.xml -w workloads/workload_hotspot.xml

# RRA-FTL run (compiled WITH the FTL.cpp patch)
./MQSim -i ssdconfig_rra.xml -w workloads/workload_hotspot.xml
```

### All three workloads

```bash
for wl in sequential random hotspot; do
    ./MQSim -i ssdconfig_baseline.xml -w workloads/workload_${wl}.xml
    ./MQSim -i ssdconfig_rra.xml      -w workloads/workload_${wl}.xml
done
```

---

## Step 6 — Parse Results

MQSim writes output XML files named after the workload XML.
Parse and compare them:

```bash
python3 parse_mqsim_output.py \
    workloads/workload_hotspot_scenario_1_baseline.xml \
    workloads/workload_hotspot_scenario_1_rra.xml
```

**Expected results for hotspot workload (from Python sim validation):**

| Metric            | Baseline | RRA-FTL | Delta     |
|-------------------|----------|---------|-----------|
| Wear Variance     | 36.20    | 2.71    | ▼ 93%     |
| Max Erase Count   | 161      | 159     | ▼ lower   |
| Min Erase Count   | 136      | 149     | ▲ higher  |
| Erase Uniformity  | poor     | near-perfect | ▲    |
| WAF               | 4.87     | 5.01    | +0.14 (tradeoff) |

---

## How RRA-FTL Integrates with MQSim's Internals

### Class hierarchy

```
GC_and_WL_Unit_Base              (MQSim core — handles erase dispatch, TSU)
  └── GC_and_WL_Unit_Page_Level  (MQSim — GREEDY/RGA/RANDOM/FIFO logic)
        └── GC_and_WL_Unit_Page_Level_RRA   ← OUR CODE
```

### The one function we override

```cpp
// MQSim calls this to pick the next block to erase in a plane.
// We replace it with Weibull-scored victim selection.
Block_Pool_Slot_Type* Get_next_gc_victim(
    PlaneBookKeepingType* plane_bookkeeping,
    const NVM::FlashMemory::Physical_Page_Address& plane_address) override;
```

### Adaptive erase latency

```cpp
// Called just before MQSim dispatches the erase transaction.
// We patch NVM_Transaction_Flash_ER::Time_to_transfer_die with:
//   T_base_ns * (1 + K_age * erase_count / PE_endurance)
void Set_erase_transaction_time(
    NVM_Transaction_Flash_ER* erase_tr,
    Block_Pool_Slot_Type*     victim_block) override;
```

---

## Three Novel Contributions — What MQSim Now Simulates

### [1] Weibull Remaining-Budget Victim Scoring
- Python: `Block.remaining_budget = exp(-(erase_count/PE_endurance)²)`
- C++: `Weibull_score(erase_count)` using pre-computed LUT (no FP at runtime)
- MQSim hook: `Get_next_gc_victim()` override

### [2] Adaptive Erase Duration
- Python: `Block.erase_time_ms = T_base * (1 + K_age * wear_ratio)`
- C++: `Adaptive_erase_ns(erase_count)`
- MQSim hook: `Set_erase_transaction_time()` patches TSU scheduling time
- Effect: P99 latency in MQSim output reflects block aging accurately

### [3] GC-Epoch Pareto Adaptive Tuning
- Python: `AdaptiveFTL._pareto_adapt()`
- C++: `Pareto_adapt(plane_bookkeeping)` called every 5 GC passes
- EMA damping (lambda=0.1) + dead-band + Pareto dominance window

### [4] Block Quarantine
- Blocks with `remaining_budget < 0.05` (≥95% worn) excluded from victim selection
- Fallback to greedy if all eligible blocks are quarantined

---

## Troubleshooting

**Compile error: `Get_next_gc_victim` not declared in base class**
→ Check your MQSim version. The function is virtual in `GC_and_WL_Unit_Page_Level.h`.
  In some versions it may be named `Select_victim_block`. Change the override
  name in `GC_and_WL_Unit_Page_Level_RRA.h/.cpp` to match.

**Compile error: `NVM_Transaction_Flash_ER::Time_to_transfer_die` not found**
→ The field may be named `Time_to_transfer` or `Execution_time_ns` in your version.
  Check `NVM_Transaction_Flash_ER.h` and update the assignment accordingly.

**Simulation completes but wear variance is identical to baseline**
→ Confirm the FTL.cpp patch was applied and the binary was rebuilt.
  Add `printf("[RRA-FTL] GC epoch %u\n", m_gc_epoch_counter);` in
  `Get_next_gc_victim()` to confirm RRA code is being called.

**MQSim doesn't write block-level erase counts to output XML**
→ MQSim's default output does not include per-block stats. The parser
  computes wear variance from erase counts if they are present, but
  falls back gracefully. You can add per-plane erase-count output
  in `SSD_Component.cpp`'s Report_results_in_XML() method.
