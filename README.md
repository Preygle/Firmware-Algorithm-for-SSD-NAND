# RRA-FTL: Reliability-Remaining Adaptive Flash Translation Layer

**Adaptive Firmware Algorithms for SSD / NAND Efficiency & Reliability**

A simulation-based framework for **reducing Write Amplification, balancing wear distribution, and extending NAND endurance** through reliability-aware firmware algorithms.

SanDisk Firmware Hackathon — Track 2: Firmware  
Domain: Firmware / Systems Engineering  
Implementation: Python-Based SSD Simulator

---

# 1. Executive Summary

Modern Solid State Drives rely on **Flash Translation Layer (FTL)** firmware to manage NAND flash memory. Traditional FTL implementations rely on static, greedy garbage collection algorithms that operate reactively and optimize only for immediate space reclamation.

These legacy strategies introduce three critical problems:

- High **Write Amplification Factor (WAF)**
- Severe **wear imbalance across blocks**
- **Premature block failure** due to uneven Program/Erase cycles

To address these limitations, this project introduces **RRA-FTL (Reliability-Remaining Adaptive Flash Translation Layer)** — a compound firmware architecture that shifts SSD management from **usage-based wear estimation** to **remaining-life-based reliability modeling**.

> **Core Thesis**

Legacy FTL optimizes for **how much a block has been used**.

RRA-FTL optimizes for **how much life the block still has remaining.**

This system integrates three novel firmware mechanisms:

| Contribution | Description |
|---|---|
| Weibull Failure Probability Scoring | Uses a physics-based failure probability model instead of erase count |
| Adaptive Erase Duration Control | Dynamically adjusts erase time based on block health |
| GC-Epoch Pareto Adaptive Tuning | Parameter adaptation triggered by Pareto dominance |

These mechanisms work together to produce measurable improvements in:

- Write Amplification
- Wear variance
- SSD lifespan
- Reliability under hotspot workloads

---

# 2. NAND Flash Constraints

NAND flash memory has fundamental physical limitations that require firmware-level management.

## 2.1 Erase-Before-Write Constraint

Unlike magnetic storage, NAND pages cannot be overwritten in place.

Updating data requires:

1. Write new data to a fresh page
2. Mark the old page as invalid
3. Reclaim space later through **Garbage Collection**

---

## 2.2 Block-Level Erasure

NAND memory is organized into:

```text
Block
├ Page
├ Page
├ Page
└ Page
```

Pages are the **write unit**  
Blocks are the **erase unit**

Even if **1 page is invalid**, the entire block must be erased.

---

## 2.3 Limited Program / Erase Endurance

Each block can endure only a limited number of erase cycles.

Typical MLC NAND endurance:

```text
3000 – 10000 P/E cycles
```

Uneven wear leads to:

- localized degradation
- early bad blocks
- reduced SSD lifetime

---

# 3. The Problem With Legacy FTL Firmware

Traditional firmware uses **greedy garbage collection**.

Victim block selection:

```text
Select block with highest number of invalid pages
```

Problems:

| Issue | Cause |
|---|---|
| High WAF | Migrating many valid pages during GC |
| Uneven wear | Hot blocks erased repeatedly |
| Premature failure | Endurance exhausted locally |
| Reduced lifespan | Uneven silicon degradation |

The system lacks **health awareness and adaptive behavior**.

---

# 4. System Architecture

The project implements a **software SSD firmware simulator** with modular components.

```text
Host Workload
↓
FTL Layer
↓
NAND Hardware Simulation
↓
Metrics Engine
↓
Analytics & Reporting
```

---

# 5. Project Structure

| Module | Description |
|---|---|
| nand.py | NAND flash hardware simulation |
| ftl.py | Base Flash Translation Layer |
| baseline_ftl.py | Legacy greedy GC implementation |
| adaptive_ftl.py | Adaptive FTL with multi-objective scoring |
| workload.py | Host I/O workload generator |
| metrics.py | Runtime metric calculations |
| main.py | Simulation controller |
| export_results.py | Report and chart generation |

---

# 6. NAND Hardware Simulation

The NAND simulator models real flash constraints.

### Page States

Each page can be:

| State | Meaning |
|---|---|
| FREE | erased page available for writing |
| VALID | current data |
| INVALID | stale data after overwrite |

---

### Block Model

Blocks contain multiple pages and track:

```python
erase_count
```

This represents **silicon wear level**.

---

### Over-Provisioning

Extra blocks reserved for firmware operations.

Used for:

- GC migration targets
- wear leveling
- avoiding deadlocks

---

# 7. Flash Translation Layer (FTL)

The FTL translates logical addresses to physical NAND pages.

Responsibilities:

- Logical-to-Physical (L2P) mapping
- Garbage collection scheduling
- Wear leveling
- Host I/O translation

---

# 8. Baseline FTL (Legacy Algorithm)

Baseline behavior:

### Static GC Trigger

```python
if free_pages < threshold:
    run_gc()
```

### Greedy Victim Selection

```python
victim = block_with_max_invalid_pages
```

This ignores:

- migration cost
- wear distribution
- block health

---

# 9. Adaptive FTL Algorithm

Adaptive FTL uses **multi-objective scoring**.

Victim block selection:

```text
TotalScore(b) =
α × Efficiency(b)
− γ × MigrationCost(b)
+ β × WearScore(b)
```

Where:

Efficiency:

```text
invalid_pages / pages_per_block
```

Migration Cost:

```text
valid_pages / pages_per_block
```

Wear Score:

```text
1 / (1 + erase_count)
```

The block with **highest score** becomes the GC victim.

---

# 10. RRA-FTL Improvement 1  
# Weibull Failure Probability Model

Traditional wear score:

```text
WearScore = 1 / (1 + erase_count)
```

This poorly reflects real NAND degradation.

Actual failure probability follows a **Weibull distribution**.

### Weibull Failure Model

```text
P_failure(b) =
1 − exp(-(erase_count / PE_endurance)^k)
```

Remaining life score:

```text
Remaining_Budget(b) =
exp(-(erase_count / PE_endurance)^k)
```

Typical parameter:

```text
k = 2
```

### Updated Victim Scoring

```text
TotalScore(b) =
α × Efficiency(b)
− γ × MigrationCost(b)
+ β × RemainingBudget(b)
```

This directly models **remaining silicon life**.

---

# 11. RRA-FTL Improvement 2  
# Adaptive Erase Duration

Existing simulators assume:

```text
erase_time = constant
```

This is unrealistic.

Real NAND erase pulse duration depends on block age.

### Adaptive Erase Model

```text
erase_time(b) =
t_base × (1 + k_age × (erase_count / PE_endurance))
```

Example:

| Erase Count | Erase Time |
|---|---|
| 0–2000 | 1.5 ms |
| 2000–5000 | 2.0 ms |
| 5000–8000 | 2.8 ms |
| 8000–9500 | 3.5 ms |

---

### Erase Error Probability

```text
P_error(b) =
P_base × exp(erase_count / (k_err × PE_endurance))
```

This models increasing failure risk near end-of-life.

---

# 12. RRA-FTL Improvement 3  
# GC-Epoch Pareto Adaptive Tuning

Original design recalibrated parameters every **1000 writes**.

Problems:

- CPU overhead
- oscillating parameters
- unstable behavior

---

## GC Epoch Trigger

Parameters update **after each GC cycle**, not after write count.

```python
if GC_epoch % N == 0:
    recalibrate_parameters()
```

---

## EMA Signal Smoothing

```text
EMA_WAF(t) =
λ × WAF(t)
+ (1 − λ) × EMA_WAF(t−1)
```

Typical λ values:

| λ | Behavior |
|---|---|
| 0.1 | stable |
| 0.3 | moderate |
| 0.5 | fast response |

---

## Pareto Dominance Trigger

Instead of scalar thresholds:

```text
WAF > threshold
```

RRA-FTL uses **Pareto dominance**.

A point is dominated if:

```text
∃ q :
q.WAF ≤ p.WAF
AND
q.WearVariance ≤ p.WearVariance
```

If dominated → system regressed → update parameters.

Otherwise → keep parameters unchanged.

---

# 13. Workload Simulation

Three workloads simulate real SSD usage.

### Sequential Writes

Examples:

- video recording
- OS installation
- database logs

Low fragmentation.

---

### Random Writes

Examples:

- OLTP databases
- virtual machines

High fragmentation.

---

### 80/20 Hotspot Pattern

Zipf-like distribution:

```text
80% writes → 20% addresses
```

This is the **primary stress test for wear leveling**.

---

# 14. Metrics Collected

### Write Amplification Factor

```text
WAF =
PhysicalWrites / HostWrites
```

Ideal value:

```text
1.0
```

---

### Wear Variance

Variance of erase counts across blocks.

Low variance = balanced wear.

---

### Erase Distribution

Histogram showing hot and cold blocks.

---

### Lifespan Projection

Estimated lifetime:

```text
Years =
TBW × 1000 / (GB_day × 365)
```

Derived from simulation WAF and workload.

---

# 15. Expected Improvements

| Metric | Baseline | RRA-FTL Target |
|---|---|---|
| WAF | High | 25–40% lower |
| Wear variance | High | 50–70% lower |
| SSD lifespan | Limited | 30–50% longer |
| Latency | High under hotspot | Reduced tail latency |

---

# 16. Simulation Experiment Setup

Simulation parameters:

- 100,000 host writes
- identical NAND configuration
- identical workloads

Compared systems:

- Baseline FTL
- Adaptive FTL
- RRA-FTL

Outputs include:

- WAF charts
- wear histograms
- lifespan projections

---

# 17. Key Novel Contributions

| Contribution | Status |
|---|---|
| Weibull failure probability in GC scoring | Novel |
| Adaptive erase duration control | First simulator implementation |
| Pareto adaptive parameter tuning | Novel |
| Reliability-remaining wear metric | Novel |

---

# 18. Repository

GitHub:

```text
https://github.com/Preygle/Firmware-Algorithm-for-SSD-NAND
```

---

# 19. License

SanDisk Hackathon Submission — 2025

Research prototype for firmware algorithm experimentation.
