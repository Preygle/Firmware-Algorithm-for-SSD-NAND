from nand import NANDFlash
from baseline_ftl import BaselineFTL
from adaptive_ftl import AdaptiveFTL
from workload import WorkloadGenerator
from metrics import Metrics
import sys

def run_simulation(strategy_class, workload, total_blocks, pages_per_block, name):
    nand = NANDFlash(total_blocks, pages_per_block)
    ftl = strategy_class(nand)
    metrics = Metrics(ftl, name)
    
    print(f"Starting simulation for {name} with {len(workload)} writes...")
    
    for i, lba in enumerate(workload):
        try:
            ftl.write(lba)
        except Exception as e:
            print(f"Simulation failed at write {i}: {e}")
            break
            
    metrics.print_summary()
    return metrics.get_summary()

def main():
    # Simulation Parameters
    TOTAL_BLOCKS = 50
    PAGES_PER_BLOCK = 64
    TOTAL_PAGES = TOTAL_BLOCKS * PAGES_PER_BLOCK
    
    # We will simulate writing enough data to force Multiple GCs.
    # We set logical capacity to 90% of physical capacity (10% overprovisioning)
    LOGICAL_CAPACITY = int(TOTAL_PAGES * 0.90)
    NUM_WRITES = 100000 # 100k writes to ensure deep GC wearing

    print("--- SSD Firmware Simulation Configuration ---")
    print(f"Total Blocks: {TOTAL_BLOCKS}")
    print(f"Pages Per Block: {PAGES_PER_BLOCK}")
    print(f"Physical Capacity (Pages): {TOTAL_PAGES}")
    print(f"Logical Capacity (LBAs): {LOGICAL_CAPACITY}")
    print(f"Total Write Commands: {NUM_WRITES}")
    print("-" * 45)

    wg = WorkloadGenerator(LOGICAL_CAPACITY)
    
    # Define Workloads to test
    workloads = {
        "Sequential": wg.generate_sequential(NUM_WRITES),
        "Random": wg.generate_random(NUM_WRITES),
        "Hotspot (80/20)": wg.generate_hotspot(NUM_WRITES, hot_ratio=0.8, hot_data_fraction=0.2)
    }

    for wl_name, wl_data in workloads.items():
        print(f"\n====== Running Workload: {wl_name} ======")
        
        # Run Baseline
        base_res = run_simulation(BaselineFTL, wl_data, TOTAL_BLOCKS, PAGES_PER_BLOCK, "Baseline FTL")
        
        # Run Adaptive
        adapt_res = run_simulation(AdaptiveFTL, wl_data, TOTAL_BLOCKS, PAGES_PER_BLOCK, "Adaptive FTL")
        
        # Comparison
        print("\n--- Comparison ---")
        waf_diff = base_res["Write Amplifi. Factor (WAF)"] - adapt_res["Write Amplifi. Factor (WAF)"]
        variance_diff = base_res["Wear Variance"] - adapt_res["Wear Variance"]
        
        print(f"WAF Improvement: {waf_diff:.3f} " 
              f"({'Adaptive is Better' if waf_diff > 0 else 'Baseline is Better'})")
        print(f"Wear Variance Improvement: {variance_diff:.3f} "
              f"({'Adaptive is Better (more uniform)' if variance_diff > 0 else 'Baseline is Better'})")


if __name__ == "__main__":
    main()
