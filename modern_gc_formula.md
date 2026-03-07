# Modern Baseline: Lifespan-Aware Garbage Collection

The modern baseline implemented in `MQSim_Baseline` is based on the **Lifespan-Aware Garbage Collection** approach, inspired by modern flash management techniques from circa 2022 (e.g., Lee et al.). This algorithm specifically aims to minimize Write Amplification Factor (WAF) and reduce the migration of "cold" (long-lived) data during garbage collection. 

To implement this without completely rewriting the simulator's core structures, the unused `FIFO` policy enum in `GC_and_WL_Unit_Page_Level.cpp` was hijacked and replaced with the following scoring logic.

## The Formula

When the SSD runs out of free space and must select a victim block to erase, the Lifespan-Aware GC scores every active block in the block pool. The block with the **highest score** is selected for eviction.

### Core Equation:
```cpp
Score = (α * Invalid_Ratio) - (β * Migration_Cost)
```

Where:
*   **`Invalid_Ratio`**: The proportion of pages in the block that are already invalid (garbage). Erasing blocks with more garbage is highly efficient since fewer pages need to be copied out.
    *   `Invalid_Ratio = Invalid_Page_Count / Total_Pages_Per_Block`
*   **`Migration_Cost`**: A penalty applied based on how many valid pages must be preserved (copied to a new block) before the erase can happen.
    *   `Migration_Cost = Valid_Page_Count / Total_Pages_Per_Block`
*   **`Valid_Page_Count`**: Calculated dynamically in MQSim as `(Current_page_write_index - Invalid_page_count)`.
*   **`α` (Alpha)**: Weight given to block efficiency (default = `1.2`).
*   **`β` (Beta)**: Penalty weight given to the cost of migrating data (default = `1.0`).

### Why this beats GREEDY algorithm

The **GREEDY** algorithm (the legacy baseline) simply selects the block with the highest `Invalid_Page_Count`. It does not explicitly penalize the cost of migrating the remaining valid pages, often leading to "cold" data being unnecessarily moved around the drive over and over again, which wastes P/E cycles and increases Write Amplification.

The **Lifespan-Aware** algorithm explicitly penalizes `Migration_Cost`. By subtracting `β * Migration_Cost`, the firmware inherently favors blocks that not only have high invalid data but also have a low amount of valid data left to migrate. This implicitly separates short-lived (hot) data—which invalidates quickly—from long-lived (cold) data, lowering the overall WAF compared to GREEDY.
