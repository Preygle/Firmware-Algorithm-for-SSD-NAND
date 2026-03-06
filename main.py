"""
main.py  —  RRA-FTL Simulation Runner
======================================
Runs Baseline FTL and RRA-FTL (Adaptive) through all 3 workloads.
Prints full metric summaries including the novel RRA-FTL metrics:
  - Adaptive erase time (ms)
  - Erase error rate
  - Mean Weibull remaining budget
  - Firmware-native lifespan projection (GB/day, DWPD, TBW, lifetime years)
"""

from nand          import NANDFlash
from baseline_ftl  import BaselineFTL
from adaptive_ftl  import AdaptiveFTL
from workload      import WorkloadGenerator
from metrics_engine import MetricsEngine, CHECKPOINT_EVERY
from visualization  import Visualizer

TOTAL_BLOCKS    = 50
PAGES_PER_BLOCK = 64
OP_RATIO        = 0.10
NUM_WRITES      = 100_000
TOTAL_PAGES     = TOTAL_BLOCKS * PAGES_PER_BLOCK
LOGICAL_CAPACITY = int(TOTAL_PAGES * (1 - OP_RATIO))


def run_simulation(strategy_class, workload, strategy_name):
    nand   = NANDFlash(TOTAL_BLOCKS, PAGES_PER_BLOCK, op_ratio=OP_RATIO)
    ftl    = strategy_class(nand)
    engine = MetricsEngine(ftl, strategy_name)

    print(f"    {strategy_name:<26} running ...", end=" ", flush=True)

    for i, lba in enumerate(workload):
        try:
            ftl.write(lba)
        except Exception as e:
            print(f"\n    [stopped at write {i}]: {e}")
            break
        if (i + 1) % CHECKPOINT_EVERY == 0:
            engine.record_checkpoint()

    s = engine.get_final_summary()
    print(f"WAF={s['waf']:.3f}  Var={s['wear_variance']:.2f}  "
          f"Life={s['lifetime_estimate']:,}  "
          f"LT(yr)={s['lifespan_years']:.2f}")
    return engine


def print_comparison(base_s, adpt_s):
    waf_imp   = base_s['waf']        - adpt_s['waf']
    var_imp   = base_s['wear_variance'] - adpt_s['wear_variance']
    life_imp  = adpt_s['lifetime_estimate'] - base_s['lifetime_estimate']
    lt_imp    = adpt_s['lifespan_years']    - base_s['lifespan_years']
    err_imp   = base_s['erase_error_rate']  - adpt_s['erase_error_rate']
    bgt_imp   = adpt_s['mean_rem_budget']   - base_s['mean_rem_budget']

    print(f"\n  {'Metric':<32} {'Baseline':>12} {'RRA-FTL':>12} {'Delta':>12}")
    print(f"  {'-'*68}")
    def row(label, bv, av, delta, fmt=".3f", higher_better=False):
        sign = "▲" if (delta > 0) == higher_better else "▼"
        if abs(delta) < 1e-9: sign = "="
        print(f"  {label:<32} {bv:>12{fmt}} {av:>12{fmt}} {sign} {abs(delta):>10{fmt}}")

    row("WAF",                      base_s['waf'],              adpt_s['waf'],             waf_imp,  ".4f", False)
    row("Wear Variance",            base_s['wear_variance'],    adpt_s['wear_variance'],   var_imp,  ".2f", False)
    row("Mean Remaining Budget",    base_s['mean_rem_budget'],  adpt_s['mean_rem_budget'], bgt_imp,  ".4f", True)
    row("Erase Error Rate",         base_s['erase_error_rate'], adpt_s['erase_error_rate'],err_imp, ".2e", False)
    row("Lifespan (years)",         base_s['lifespan_years'],   adpt_s['lifespan_years'],  lt_imp,  ".3f", True)
    row("Effective TBW (TB)",       base_s['effective_tbw_tb'], adpt_s['effective_tbw_tb'],
        adpt_s['effective_tbw_tb'] - base_s['effective_tbw_tb'], ".3f", True)
    print()


def main():
    print("=" * 62)
    print("  RRA-FTL: Reliability-Remaining Adaptive FTL Simulation")
    print(f"  Blocks: {TOTAL_BLOCKS}  |  Pages/Block: {PAGES_PER_BLOCK}"
          f"  |  Writes: {NUM_WRITES:,}")
    print("=" * 62)

    wg = WorkloadGenerator(LOGICAL_CAPACITY)
    workloads = {
        "Sequential":      wg.generate_sequential(NUM_WRITES),
        "Random":          wg.generate_random(NUM_WRITES),
        "Hotspot (80/20)": wg.generate_hotspot(NUM_WRITES,
                                                hot_ratio=0.8,
                                                hot_data_fraction=0.2),
    }

    viz = Visualizer(output_dir="charts")

    for wl_name, wl_data in workloads.items():
        print(f"\n── Workload: {wl_name} {'─'*(46-len(wl_name))}")
        base_engine = run_simulation(BaselineFTL, wl_data, "Baseline FTL")
        adpt_engine = run_simulation(AdaptiveFTL, wl_data, "RRA-FTL (Adaptive)")

        base_engine.print_summary()
        adpt_engine.print_summary()

        print(f"\n  ── Comparison: {wl_name} ──")
        print_comparison(base_engine.get_final_summary(),
                         adpt_engine.get_final_summary())

        viz.plot_all(base_engine, adpt_engine, workload_name=wl_name)

    print(f"\n{'='*62}")
    print(f"  Charts saved to: charts/")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
