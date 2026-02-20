from nand import NANDFlash
from baseline_ftl import BaselineFTL
from adaptive_ftl import AdaptiveFTL
from workload import WorkloadGenerator
from metrics import Metrics

def run_simulation(strategy_class, workload, total_blocks, pages_per_block, name):
    nand = NANDFlash(total_blocks, pages_per_block)
    ftl = strategy_class(nand)
    metrics = Metrics(ftl, name)
    
    for i, lba in enumerate(workload):
        try:
            ftl.write(lba)
        except Exception as e:
            pass
            
    return metrics.get_summary()

def main():
    TOTAL_BLOCKS = 50
    PAGES_PER_BLOCK = 64
    TOTAL_PAGES = TOTAL_BLOCKS * PAGES_PER_BLOCK
    LOGICAL_CAPACITY = int(TOTAL_PAGES * 0.90) # 10% overprovisioning
    NUM_WRITES = 100000 # Increased workload

    wg = WorkloadGenerator(LOGICAL_CAPACITY)
    
    workloads = {
        "Sequential Workload": wg.generate_sequential(NUM_WRITES),
        "Random Workload": wg.generate_random(NUM_WRITES),
        "Hotspot Workload (80/20)": wg.generate_hotspot(NUM_WRITES, hot_ratio=0.8, hot_data_fraction=0.2)
    }

    with open("simulation_results.txt", "w", encoding="utf-8") as f:
        f.write("=========================================================\n")
        f.write("      SSD FIRMWARE ALGORITHMS: FULL SIMULATION DATA      \n")
        f.write("=========================================================\n\n")
        f.write(f"Configuration:\n")
        f.write(f"- Total Blocks: {TOTAL_BLOCKS}\n")
        f.write(f"- Pages Per Block: {PAGES_PER_BLOCK}\n")
        f.write(f"- Physical Capacity (Pages): {TOTAL_PAGES}\n")
        f.write(f"- Logical Capacity (LBAs): {LOGICAL_CAPACITY}\n")
        f.write(f"- Total Write Operations Simulated per Case: {NUM_WRITES:,}\n\n")
        f.write("=========================================================\n\n")

        for wl_name, wl_data in workloads.items():
            f.write(f"#########################################################\n")
            f.write(f"   CASE: {wl_name.upper()}\n")
            f.write(f"#########################################################\n\n")
            
            # Show input
            f.write("--- INPUT (THE WORKLOAD) ---\n")
            f.write("Description: A massive array of Logical Block Addresses (LBAs) sent by the OS to the SSD.\n")
            f.write(f"Total Inputs: {len(wl_data):,} writes.\n")
            f.write(f"Sample First 50 Writes: {wl_data[:50]}\n")
            f.write(f"...\n\n")
            
            # Run
            f.write("--- PROCESSING ---\n")
            f.write("Running inputs through Baseline FTL Algorithm...\n")
            base_res = run_simulation(BaselineFTL, wl_data, TOTAL_BLOCKS, PAGES_PER_BLOCK, "Baseline FTL")
            
            f.write("Running inputs through Adaptive (Elite) FTL Algorithm...\n\n")
            adapt_res = run_simulation(AdaptiveFTL, wl_data, TOTAL_BLOCKS, PAGES_PER_BLOCK, "Adaptive FTL")
            
            # Show Output
            f.write("--- OUTPUT (METRICS) ---\n")
            
            f.write("\n1. BASELINE FTL RESULTS:\n")
            for k, v in base_res.items():
                if isinstance(v, float):
                    f.write(f"  - {k}: {v:.3f}\n")
                elif type(v) == int and v > 1000:
                    f.write(f"  - {k}: {v:,}\n")
                else:
                    f.write(f"  - {k}: {v}\n")
                    
            f.write("\n2. ADAPTIVE FTL RESULTS:\n")
            for k, v in adapt_res.items():
                if isinstance(v, float):
                    f.write(f"  - {k}: {v:.3f}\n")
                elif type(v) == int and v > 1000:
                    f.write(f"  - {k}: {v:,}\n")
                else:
                    f.write(f"  - {k}: {v}\n")
                    
            f.write("\n3. COMPARISON (ADAPTIVE VS BASELINE):\n")
            waf_diff = base_res["Write Amplifi. Factor (WAF)"] - adapt_res["Write Amplifi. Factor (WAF)"]
            variance_diff = base_res["Wear Variance"] - adapt_res["Wear Variance"]
            
            if base_res["Proj. Lifetime (Host Writes)"] != "Unlimited" and adapt_res["Proj. Lifetime (Host Writes)"] != "Unlimited":
                life_diff = adapt_res["Proj. Lifetime (Host Writes)"] - base_res["Proj. Lifetime (Host Writes)"]
                life_str = f"+{life_diff:,} Host Writes"
            else:
                life_str = "N/A"
            
            f.write(f"  - WAF Improvement: {waf_diff:.3f} ")
            if waf_diff > 0: f.write("(Adaptive is Better)\n")
            elif waf_diff < 0: f.write("(Baseline is Better)\n")
            else: f.write("(Tie)\n")
            
            f.write(f"  - Wear Variance Improvement: {variance_diff:.3f} ")
            if variance_diff > 0: f.write("(Adaptive is Better - Erase cycles are spread far more evenly)\n")
            elif variance_diff < 0: f.write("(Baseline is Better)\n")
            else: f.write("(Tie)\n")
            
            f.write(f"  - Estimated Lifetime Extension: {life_str}\n\n")
            f.write("=========================================================\n\n")

if __name__ == "__main__":
    main()
