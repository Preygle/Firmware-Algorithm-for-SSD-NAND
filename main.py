"""
main.py  —  SSD Firmware Simulation Runner (Updated)
=====================================================
Runs Baseline FTL and Adaptive FTL through all 3 workloads.
Uses MetricsEngine to collect live data during simulation.
Uses Visualizer to generate all 4 charts from that live data.

Charts are generated fresh every run — nothing is pre-loaded.
"""

from nand         import NANDFlash
from baseline_ftl import BaselineFTL
from adaptive_ftl import AdaptiveFTL
from workload     import WorkloadGenerator
from metrics_engine  import MetricsEngine, CHECKPOINT_EVERY
from visualization   import Visualizer

# ── Simulation configuration ─────────────────────────────────────────────────
TOTAL_BLOCKS     = 50
PAGES_PER_BLOCK  = 64
OP_RATIO         = 0.10          # 10% over-provisioning
NUM_WRITES       = 100_000
TOTAL_PAGES      = TOTAL_BLOCKS * PAGES_PER_BLOCK
LOGICAL_CAPACITY = int(TOTAL_PAGES * (1 - OP_RATIO))


def run_simulation(strategy_class, workload: list,
                   strategy_name: str) -> MetricsEngine:
    """
    Runs one full simulation and returns a populated MetricsEngine.
    MetricsEngine holds both time-series data and the final summary.
    """
    nand    = NANDFlash(TOTAL_BLOCKS, PAGES_PER_BLOCK, op_ratio=OP_RATIO)
    ftl     = strategy_class(nand)
    engine  = MetricsEngine(ftl, strategy_name)

    print(f"    {strategy_name:<22} running ...", end=" ", flush=True)

    for i, lba in enumerate(workload):
        try:
            ftl.write(lba)
        except Exception as e:
            print(f"\n    [stopped at write {i}]: {e}")
            break

        # Record a snapshot every CHECKPOINT_EVERY host writes
        if (i + 1) % CHECKPOINT_EVERY == 0:
            engine.record_checkpoint()

    summary = engine.get_final_summary()
    print(f"WAF={summary['waf']:.3f}  "
          f"Var={summary['wear_variance']:.2f}  "
          f"Life={summary['lifetime_estimate']:,}")

    return engine


def main():
    print("=" * 60)
    print("  SSD Firmware Simulation")
    print(f"  Blocks: {TOTAL_BLOCKS}  |  Pages/Block: {PAGES_PER_BLOCK}  "
          f"|  Writes: {NUM_WRITES:,}")
    print("=" * 60)

    # ── Generate workloads ────────────────────────────────────────────────────
    wg = WorkloadGenerator(LOGICAL_CAPACITY)
    workloads = {
        "Sequential":       wg.generate_sequential(NUM_WRITES),
        "Random":           wg.generate_random(NUM_WRITES),
        "Hotspot (80/20)":  wg.generate_hotspot(NUM_WRITES,
                                                  hot_ratio=0.8,
                                                  hot_data_fraction=0.2),
    }

    viz = Visualizer(output_dir="charts")

    # ── Run each workload ─────────────────────────────────────────────────────
    for wl_name, wl_data in workloads.items():
        print(f"\n── Workload: {wl_name} ──────────────────────────")

        base_engine = run_simulation(BaselineFTL, wl_data, "Baseline FTL")
        adpt_engine = run_simulation(AdaptiveFTL, wl_data, "Adaptive FTL")

        # Print metric summaries to console
        base_engine.print_summary()
        adpt_engine.print_summary()

        # Generate all 4 charts live from this run's data
        viz.plot_all(base_engine, adpt_engine, workload_name=wl_name)

    print(f"\n{'='*60}")
    print(f"  All charts saved to:  charts/")
    print(f"  Each run regenerates charts from fresh simulation data.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
