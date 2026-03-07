# Feature Implementation Prompt for Agentic AI
## Project: Adaptive SSD Firmware Simulator

You are tasked with implementing a new module in an existing SSD firmware simulator written in Python.

The simulator already contains the following modules:

- nand.py → NAND flash hardware simulation
- ftl.py → base Flash Translation Layer
- baseline_ftl.py → greedy garbage collection algorithm
- adaptive_ftl.py → adaptive heuristic garbage collection
- workload.py → workload generation (sequential/random/hotspot)
- metrics.py → runtime metrics (WAF, wear variance, etc.)
- main.py → simulation runner
- export_results.py → results and charts

Your job is to implement a **new endurance modeling subsystem** inspired by real SSD endurance calculators.

The system must support the following features.

---

# 1. Endurance Parameter Conversion

Implement functions that convert between the following SSD endurance metrics:

DWPD — Drive Writes Per Day  
TBW — Total Bytes Written (in TB)  
GB/day — Host write workload

Use these formulas:

DWPD = GB_per_day / SSD_capacity

DWPD = (TBW * 1000) / (capacity * warranty_years * 365)

TBW = (DWPD * capacity * warranty_years * 365) / 1000

GB/day = DWPD * capacity

Create functions:

convert_tbw_to_dwpd()
convert_dwpd_to_tbw()
convert_gb_day_to_dwpd()
convert_dwpd_to_gb_day()

---

# 2. IOPS Workload Conversion

Implement conversion between IOPS workload and GB/day.

Inputs:

IOPS
block size (KB)

Formulas:

MB/s = (IOPS * block_size_kb) / 1024

GB/day = MB/s * 86.4

Create function:

iops_to_gb_day(iops, block_size_kb)

---

# 3. SSD Lifetime Estimation

Estimate the lifetime of the SSD based on workload and TBW.

Formula:

Lifetime_years = TBW / (GB_per_day * 365 / 1000)

Create function:

estimate_lifetime_years(tbw_tb, gb_per_day)

---

# 4. Integration with Firmware Simulation

Modify the metrics system to incorporate endurance modeling.

The simulator already tracks:

host_writes
physical_writes
WAF
erase_counts

Compute:

effective_GB_per_day = host_GB_per_day * WAF

Use this to estimate SSD lifetime.

Add metrics:

- projected_lifetime_years
- effective_write_rate
- endurance_consumption_rate

---

# 5. Firmware Comparison Feature

The simulator should compare endurance impact between firmware algorithms:

Baseline FTL
Adaptive FTL

Compute:

Baseline lifetime
Adaptive lifetime
Lifetime improvement %

Example output:

Baseline Firmware:
WAF = 2.9
Projected lifetime = 10.2 years

Adaptive Firmware:
WAF = 1.7
Projected lifetime = 17.8 years

Lifetime improvement = 74%

---

# 6. Command Line Interface

Add CLI support.

Example usage:

python main.py \
--capacity 480 \
--tbw 945 \
--iops 15000 \
--block 64 \
--warranty 5

Outputs:

SSD endurance parameters
workload write rate
projected lifetime for each firmware

---

# 7. Visualization

Add charts:

1. WAF vs writes
2. Wear distribution across blocks
3. Lifetime comparison
4. Erase count histogram

Use matplotlib.

---

# 8. Code Structure

Create new module:

endurance_model.py

Structure:

class EnduranceModel
class WorkloadConverter
class LifetimeEstimator

Ensure modular design so endurance modeling can run independently from the simulator.

---

# 9. Future Extensibility

Design the module to allow:

- real SSD model profiles
- failure probability modeling
- workload detection
- NAND degradation modeling

---

# Deliverable

A fully integrated endurance modeling subsystem that allows the simulator to estimate real-world SSD lifetime impact of different firmware algorithms.