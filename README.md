# Team Readme: SSD Firmware & FTL Simulation

Hey team! I put together a Python simulator for our SSD firmware project. The main goal here was to model how a Flash Translation Layer (FTL) handles Garbage Collection (GC) and see if we could build a dynamic algorithm that balances reclaiming space vs. wearing out the drive. 

Here’s a quick walkthrough of what I built, how it works under the hood, and the tradeoffs I made.

---

## What I Built: The Core Architecture

I broke the problem down into a few main pieces: the physical NAND flash, the logical FTL brain, and the workloads we use to test them.

### 1. The Physical NAND (`nand.py`)
This is the mock hardware. I created `Page` and `Block` objects to enforce absolute physical rules:
- **Erase-Before-Write**: A page must be empty (`FREE`) to write to it.
- **Block Erasure**: We can write to individual pages, but we can only erase entire blocks at once.
- **Endurance**: I track `erase_count` on every block so we can measure how fast we are destroying the drive.

I also added **Over-Provisioning (OP)** at this layer. The `NANDFlash` setup reserves about 10% of the blocks. The FTL is never allowed to map normal user data to these blocks; they exist solely to give us breathing room to migrate data during Garbage Collection.

### 2. The FTL Brain (`ftl.py` & Subclasses)
The FTL intercepts the host’s read/write commands. It maintains the L2P (Logical-to-Physical) dictionary mapping. When an old file gets updated, the FTL marks the old physical page as `INVALID` and writes the new data to a fresh `FREE` page.

I built two versions of the FTL so we could compare them:
1. **The Baseline FTL**: A dumb, greedy algorithm. When it runs out of space, it just triggers GC and picks the block with the most `INVALID` pages to erase. It’s efficient for reclaiming space but terrible for the drive's lifespan because it doesn't care if it's erasing the same hot blocks over and over.
2. **The Adaptive FTL**: This is the core of my work. It’s a multi-objective heuristic that looks at WAF and Wear Variance and tunes itself on the fly. 

---

## How the Adaptive GC Works (The Math & Tradeoffs)

The primary goal of the Adaptive FTL is to stop the drive from dying prematurely, without completely tanking performance. 

Instead of just grabbing the block with the most garbage data, it calculates a score for every block. The highest score gets erased. 

`Score = (Alpha * Efficiency) - (Gamma * Migration) + (Beta * Wear)`

Here’s why I chose these three parameters:

### The Tradeoff: Efficiency vs. Migration Cost
* **Efficiency (Alpha)**: This is `Invalid_Pages / Total_Pages`. It tells us how much free space we get back. 
* **Migration (Gamma)**: This is `Valid_Pages / Total_Pages`. This is the heavy penalty. For every valid page left in the block, we have to physically copy it somewhere else before we can erase the block. This causes **Write Amplification (WAF)**. The higher the WAF, the slower the drive feels to the user.

*Tradeoff Context*: If we only care about `Alpha`, we get the Baseline FTL. It keeps WAF low, but Wear Variance explodes. So, we subtract `Gamma` to actively punish the algorithm for choosing blocks that require lots of slow data migration.

### Wear Leveling (Beta)
* **Wear Score (Beta)**: This is `1.0 - (Block_Erase_Count / SSD_Max_Erase_Count)`. 
* *Tradeoff Context*: I normalized this against the *currently* most damaged block on the drive, not a theoretical 10k limit. This means if a block is relatively healthy compared to its neighbors, it gets a massive score boost. The algorithm will happily accept a slightly higher WAF penalty just to force selection of a "fresh" block, keeping the wear spread evenly across the chassis.

### Dynamic Tuning (The Adaptive Part)
Rather than hardcoding `Alpha`, `Beta`, and `Gamma`, the algorithm actively monitors the SSD's health using exponential moving averages and adjusts them every 1k writes.

- If the system **Write Amplification** spikes above our target (meaning we are shuffling too much data), the algorithm panics and increases `Alpha` and `Gamma`. It temporarily stops caring about wear-leveling just to rescue IO speeds.
- If the system **Wear Variance** gets too high (meaning specific blocks are taking too much damage), it increases `Beta` to force wear-leveling.
- I clamped all weights between `[0.1, 2.0]` to prevent crazy feedback loops, and added a failsafe: if WAF > 6.0, we lock down and force efficiency rules.

---

## Repository File Breakdown

To help you navigate the codebase, here is exactly what every single file in the project directory does:

### Core Simulator Components
*   `nand.py`: The physical hardware simulator. Defines `Page` and `Block` classes, enforces Erase-Before-Write rules, and handles Over-Provisioning capacity.
*   `ftl.py`: The abstract base class for the firmware brain. Handles the logical-to-physical (L2P) mapping dictionary and proactive Garbage Collection triggers.
*   `baseline_ftl.py`: The traditional SSD algorithm that blindly selects the block with the most invalid pages during Garbage Collection.
*   `adaptive_ftl.py`: The "Elite" algorithm that calculates multi-objective heuristcs (`Alpha/Beta/Gamma`) to balance efficiency against wear-leveling dynamically.

### Orchestration & Utilities
*   `workload.py`: The traffic generator. Simulates the OS feeding Sequential, Random, and Hotspot arrays of Logical Block Addresses (LBAs) into the SSD.
*   `metrics.py`: The math engine. Calculates Write Amplification Factor (WAF), extracts Wear Variance, and formulates the active Estimated Lifetime Projections.
*   `main.py`: The standard execution script. Chains the workloads and the FTLs together and prints performance comparisons to the console.
*   `export_results.py`: The refined execution script. Runs the 100,000 host-write simulation and neatly writes formatted mathematical comparisons directly into `.txt` logs.

### Documentation Files
*   `README.md`: The file you are reading right now! A conversational explanation of the project's logic and architecture for team review.
*   `technical.md`: A highly formal, rigidly structured documentation file containing the exact mathematical formulas, system goals, and raw component explanations (ideal for whitepapers or strict documentation needs).

### Output Logs & Result Files
*   `simulation_results.txt`: The definitive output log cleanly generated by `export_results.py`. Contains sample inputs and the final comparative WAF/Variance metrics for all three workloads.
*   `result.txt`, `result2.txt`, `output.txt`, `output_utf8.txt`: Earlier iteration console dumps generated during the active development and debugging phases to track the evolution of the Garbage Collection algorithms.

---

## How It Fits Together (Testing and Results)

To prove this actually works, I built `workload.py` to generate realistic OS traffic:
- **Sequential**: Huge file copies. Easy for the FTL.
- **Random**: Database thrashing. Heavy fragmentation.
- **Hotspot (80/20)**: Simulating a real user where 80% of writes hit the same 20% of the active OS logical addresses.

The runner script (`main.py` & `export_results.py`) pushes 100,000 writes through both the Baseline and Adaptive FTLs. 

**The Output:**
Because the Adaptive FTL actively forces healthier blocks to be erased, the WAF takes a very minor, expected hit (e.g., jumping from `4.9` to `5.0`). However, the **Wear Variance** plummets from `~41.0` down to `~6.5`. 

Because the silicon wear is distributed so evenly, the estimated lifespan of the SSD extended by over 100,000 Host Writes in the simulation. 

Let me know if you want to dive into any of the specific Python classes!
