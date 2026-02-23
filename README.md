# Adaptive Firmware Algorithms for SSD/NAND Efficiency & Reliability

![Project Overview](Picture%201.png)

This project models the internal firmware of a Solid State Drive (SSD), specifically simulating the Flash Translation Layer (FTL). It compares a traditional **Baseline FTL** algorithm against a deeply optimized **Adaptive FTL**, demonstrating how multi-objective heuristic mathematics can dynamically increase the lifespan of NAND flash memory.

## How NAND and SSDs are Simulated in Python

![Simulation Methodology](Picture%202.png)

This project builds a fully functional software replica of an SSD's internal hardware and firmware interactions using object-oriented Python.

### The Physical Hardware (`nand.py`)
To mimic real silicon architecture, we created classes for `Page` and `Block`:
- **Pages**: The fundamental unit of data storage (e.g., 4KB of data). In Python, a `Page` object tracks its target `logical_address` (the file's ID from the OS) and its physical `state` (`FREE`, `VALID`, or `INVALID`).
- **Blocks**: An array of `Page` objects. The `Block` class enforces the physical constraints of NAND flash:
   - *Erase-Before-Write*: The `write_page()` function refuses to overwrite data. It only targets `FREE` pages.
   - *Block-Level Erasure*: The `erase()` function resets every `Page` in the array simultaneously back to `FREE`, while critically incrementing the block's `erase_count` (simulating silicon degradation).
- **Over-Provisioning (OP)**: The `NANDFlash` class instantiates the array of `Block`s. It actively reserves a strict percentage (e.g., 10%) of blocks purely for background operations. These OP blocks ensure the drive always has breathing room to migrate valid pages during Garbage Collection.

### The Firmware "Brain" (`ftl.py` & Subclasses)
The Flash Translation Layer (FTL) acts as the bridge between the operating system and the physical NAND simulation.
- **Logical-to-Physical (L2P) Mapping**: The base `FTL` class maintains a massive Python dictionary (`self.l2p_map`) that translates the OS's simple logical requests (e.g., "Save to LBA 5") into literal physical coordinates (e.g., "Block 42, Page Index 12").
- **Handling Writes**: When you overwrite a file, the `write()` function finds the *old* physical coordinate in the dictionary, reaches into `nand.py` to flag that specific `Page` as `INVALID`, and then writes the new data to a fresh `FREE` page, updating the dictionary map.

When the SSD inevitably runs low on completely `FREE` pages, the FTL triggers its Garbage Collection algorithm to recover the scattered `INVALID` pages, and this is where the algorithmic battle between the Baseline and Adaptive strategies takes place.

---

## Core SSD Constraints Managing the Algorithms

Modern SSDs rely on NAND flash memory cells, which suffer from three major physical constraints that firmware must manage:
1. **Erase-Before-Write**: A page of memory must be blank (`FREE`) before new data can be written to it. It cannot be overwritten in place.
2. **Block-Level Erasure**: While data is written at the precise `Page` level, it can only be erased at the massive `Block` level (which contains dozens of pages).
3. **Limited Endurance**: Every time a block is erased, the silicon degrades. After thousands of erases, the block permanently dies.

Because of these rules, when an operating system deletes or modifies a file, the SSD firmware must mark the old data as `INVALID` and write the new data elsewhere. Exploring how to optimally reclaim those `INVALID` blocks of space—a process called **Garbage Collection (GC)**—is the core objective of this project.

---

## 1. Parameters & System Metrics
During execution, the simulator actively tracks specific mathematical parameters to gauge the health and efficiency of the simulated SSD.

### Write Amplification Factor (WAF)
* **Formula**: `WAF = Total Physical NAND Writes / Total Host Writes`
* **What it Does**: Measures the hidden cost of Garbage Collection. If an OS sends 100 pages to save to disk, but the SSD has to shuffle around 300 pages internally just to make room, the WAF is `3.0`.
* **The Goal**: Keep WAF as close to `1.0` as possible. High WAF wastes SSD performance and lifespan. 

### Wear Variance
* **Formula**: `Wear_Variance = Σ (Block_Erase_Count - Mean_Erase_Count)^2 / Total_Blocks`
* **What it Does**: A statistical variance matrix calculating how evenly the damage (erase counts) is spread across all physical silicon blocks.
* **The Goal**: Keep Wear Variance as low as possible (`~0.0`). High variance means a few specific blocks are being destroyed rapidly while others are untouched, which will cause premature drive failure.

### Estimated Lifetime Projection
* **Formula**: `Lifetime_Host_Writes = (Global_Max_Erase_Limit / Current_Max_Block_Erase_Count) * Total_Host_Writes_So_Far`
* **What it Does**: Calculates how many Host Writes the drive can ultimately endure before the most heavily-abused block hits the theoretical silicon failure limit (e.g., 10,000 erases).
* **The Goal**: Maximize this number.

---

## 2. The Baseline Strategy
The Baseline represents older, traditional, static FTL algorithms.

**Garbage Collection Trigger:**
* **Trigger**: Static. GC triggers blindly when the SSD has no free space remaining.

**Victim Block Selection:**
* **Logic**: *Greedy Selection*. The algorithm scans all blocks and picks the one simply containing the highest number of `INVALID` pages. It rescues the remaining valid pages, erases the block, and reclaims space efficiently.
* **The Flaw**: It is completely oblivious to block health. It will mercilessly erase the exact same blocks over and over if they happen to accumulate invalid pages, skyrocketing the Wear Variance and guaranteeing premature hardware failure. 

---

## 3. The Adaptive "Elite" Strategy

![Adaptive FTL Strategy](Picture%203.png)

The Adaptive FTL is a research-grade algorithm leveraging multi-objective mathematical heuristics to dynamically adapt to the stress profile of the active workload.

### 3.1. Dynamic Garbage Collection Threshold
Instead of waiting until the drive is 100% full, the Adaptive FTL calculates a shifting global threshold to trigger GC proactively based on system health.
* **Formula**: `Dynamic_Threshold = base_threshold + (k1 * current_waf) - (k2 * wear_variance)`
* **Why**: If the current system WAF is high, the SSD raises the threshold (delaying GC to wait for more pages to become naturally invalidated). If Wear Variance is getting dangerously bad, it lowers the threshold (triggering GC faster to allow the block selection algorithm to step in and spread the wear).

### 3.2. Multi-Objective Block Selection Heuristic
When GC triggers, the Adaptive FTL calculates a specialized `Total_Score` for every single physical block on the drive. The block with the highest score is erased.
* **Formula**: `Total_Score = (Alpha * Efficiency_Score) - (Gamma * Migration_Cost) + (Beta * Wear_Score)`

Below is the breakdown of how the FTL calculates each internal variable:

#### A. Efficiency Score
* **Formula**: `Invalid_Pages / Total_Pages_In_Block`
* **What it is**: Represents the raw percentage of space that can be reclaimed from the block. A block that is 90% full of garbage data will score `0.9`. Higher is better.

#### B. Migration Cost
* **Formula**: `Valid_Pages / Total_Pages_In_Block`
* **What it is**: The brutal penalty calculation. Every valid page surviving in a block *must* be physically copied to a new location before the block can be erased. This copy operation directly spikes Write Amplification. A block that has many active files will possess a high `Migration_Cost` and be mathematically penalized via the Gamma parameter.

#### C. Wear Score
* **Formula**: `1.0 - (Block_Erase_Count / Current_Max_Erase_Count_In_SSD)`
* **What it is**: Rather than normalizing to a theoretical limit (like 10,000 erases), it is normalized against the currently most heavily damaged block on the drive. If a block has only been erased 10 times, but the worst block on the drive has been erased 100 times, this healthy block gets a high Wear Score (`0.90`) making it very attractive to select.

### 3.3. Dynamic Runtime Parameter Tuning
The greatest strength of the Adaptive FTL is that `Alpha`, `Beta`, and `Gamma` are not static numbers. They are dynamically tuned variables that clamp between `[0.1, 2.0]`. 

Every 1,000 host writes, the Adaptive FTL evaluates exponential moving averages of the system WAF and Wear Variance:
* **If WAF > Target Limit**: The algorithm is struggling to reclaim space cleanly. It dynamically increases `Alpha` and `Gamma`. This shifts the focus of the SSD to strictly maximizing space recovery and absolutely punishing data migrations, ignoring wear leveling.
* **If Wear_Variance > Target Limit**: The algorithm is destroying specific blocks too quickly. It dynamically increases `Beta`. This shifts the SSD's focus to aggressively punishing tired blocks, forcing the Garbage Collector to select healthy blocks instead, spreading the damage across the drive. 
* **Failsafe Protocol**: If Write Amplification spikes wildly out of control (WAF > 6.0), the system kicks in an emergency lock. It forces `Alpha = 1.5`, `Gamma = 1.5`, and `Beta = 0.5`. This instantly overrides wear-leveling concerns to save the drive's IO throughput.

---

## 4. The Workload Generator (`workload.py`)
To test the FTL algorithms, the simulator does not use random noise. It uses a bespoke `WorkloadGenerator` to replicate realistic operating system behaviors:

* **Sequential Workload**: Replicates saving massive continuous files (like installing a massive 50GB video game or downloading a 4K movie). It writes logically ordered LBAs (`1, 2, 3...`) which are extremely easy for an SSD to process with `1.0` WAF.
* **Random Workload**: Replicates a heavily fragmented OS or a database server writing tiny, completely randomized scattered chunks. This causes immense fragmentation and heavily stresses the Garbage Collection system since valid pages are scattered everywhere.
* **Hotspot Workload (80/20 Rule)**: The most realistic simulation of a human user. 80% of all disk writes are forced into just 20% of the drive's logical space. This replicates how users constantly overwrite their `AppletData`, Temp folders, and page files, while completely ignoring the remaining 80% of the drive (like cold storage photos). This creates immediate hardware wear imbalances that the Adaptive FTL must solve.

---

## 5. System Execution (`main.py` & `export_results.py`)

![System Execution](Picture%204.png)

The simulation is orchestrated by a central runner script.

1. **Configuration Setup**: The script defines the exact physical parameters of the simulated drive (e.g., 50 Blocks, 64 Pages, 10% Over-Provisioning).
2. **Workload Generation**: It generates arrays containing 100,000 specific LBA write instructions for all three workload types.
3. **Dual Simulation**: It feeds the exact same 100,000 LBA instructions first into the `BaselineFTL` simulation, and then a fresh replica into the `AdaptiveFTL` simulation.
4. **Metric Exporting**: It parses the WAF, Wear Variance, and Lifetime outputs of both runs and generates a comparative `.txt` file proving exactly how many millions of extra Host Writes the Adaptive algorithm physically saved the drive.
