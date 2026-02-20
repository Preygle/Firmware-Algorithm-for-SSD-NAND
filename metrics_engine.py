"""
metrics_engine.py  —  Engineer 3: Live Metrics Calculator
==========================================================
Wraps any FTL instance and records metrics at every checkpoint interval.

Calculates:
  1. Logical Writes      — host write commands issued
  2. Physical Writes     — actual NAND page writes (includes GC migrations)
  3. Write Amplification Factor (WAF) = Physical / Logical
  4. Wear Variance       — statistical variance of per-block erase counts
  5. Lifetime Estimation — projected host writes before most-worn block dies
"""

import math


MAX_ERASE_LIMIT  = 10_000   # NAND P/E cycle limit per block
CHECKPOINT_EVERY = 1_000    # record a snapshot every N host writes


class MetricsEngine:
    """
    Attach to any FTL instance before the simulation loop.
    Call  .record_checkpoint()  inside the loop to collect time-series data.
    Call  .get_final_summary()  after the loop for the complete picture.
    """

    def __init__(self, ftl_instance, strategy_name: str,
                 max_erase_limit: int = MAX_ERASE_LIMIT,
                 checkpoint_every: int = CHECKPOINT_EVERY):

        self.ftl              = ftl_instance
        self.strategy_name    = strategy_name
        self.max_erase_limit  = max_erase_limit
        self.checkpoint_every = checkpoint_every

        # ── Time-series snapshots (one entry per checkpoint) ─────────────────
        self.ts_host_writes    = []   # logical writes at each checkpoint
        self.ts_physical_writes= []   # physical NAND writes at each checkpoint
        self.ts_waf            = []   # WAF at each checkpoint
        self.ts_wear_variance  = []   # wear variance at each checkpoint
        self.ts_lifetime       = []   # estimated lifetime (host writes) at each checkpoint

    # ── Core metric calculations ─────────────────────────────────────────────

    def logical_writes(self) -> int:
        """Total host write commands issued so far."""
        return self.ftl.host_writes

    def physical_writes(self) -> int:
        """Total NAND page writes so far (host writes + GC migrations)."""
        return self.ftl.total_writes

    def waf(self) -> float:
        """
        Write Amplification Factor.
        WAF = Physical NAND Writes / Logical Host Writes
        Ideal = 1.0  (every host write costs exactly one NAND write)
        """
        if self.ftl.host_writes == 0:
            return 1.0
        return self.ftl.total_writes / self.ftl.host_writes

    def wear_variance(self) -> float:
        """
        Wear Variance = Σ(erase_count_i - mean)² / N
        Measures how evenly erase cycles are distributed across all blocks.
        Lower is better — 0.0 means perfectly uniform wear.
        """
        counts = self.ftl.nand.get_erase_counts()
        if not counts:
            return 0.0
        mean = sum(counts) / len(counts)
        return sum((c - mean) ** 2 for c in counts) / len(counts)

    def lifetime_estimate(self) -> float:
        """
        Estimated Lifetime (Host Writes).
        = (MAX_ERASE_LIMIT / max_block_erase_count) * host_writes_so_far

        Logic: if the worst block has been erased X times after Y host writes,
        it will reach the failure limit after MAX_ERASE_LIMIT/X * Y host writes.
        """
        counts    = self.ftl.nand.get_erase_counts()
        max_erase = max(counts) if counts else 0
        if max_erase == 0:
            return float('inf')
        return (self.max_erase_limit / max_erase) * self.ftl.host_writes

    # ── Snapshot recorder ────────────────────────────────────────────────────

    def record_checkpoint(self):
        """Call this every CHECKPOINT_EVERY writes to build time-series data."""
        self.ts_host_writes.append(self.logical_writes())
        self.ts_physical_writes.append(self.physical_writes())
        self.ts_waf.append(self.waf())
        self.ts_wear_variance.append(self.wear_variance())
        lt = self.lifetime_estimate()
        self.ts_lifetime.append(lt if lt != float('inf') else 0)

    # ── Final summary ─────────────────────────────────────────────────────────

    def get_final_summary(self) -> dict:
        """Returns a complete dict of all final metrics after simulation ends."""
        counts    = self.ftl.nand.get_erase_counts()
        max_erase = max(counts) if counts else 1
        min_erase = min(counts) if counts else 0
        lt        = self.lifetime_estimate()

        return {
            "strategy":          self.strategy_name,
            "logical_writes":    self.logical_writes(),
            "physical_writes":   self.physical_writes(),
            "waf":               round(self.waf(), 4),
            "wear_variance":     round(self.wear_variance(), 4),
            "lifetime_estimate": int(lt) if lt != float('inf') else 999_999_999,
            "gc_count":          self.ftl.gc_count,
            "max_erase_count":   max_erase,
            "min_erase_count":   min_erase,
            "erase_counts":      counts,          # full per-block list for heatmap
        }

    def print_summary(self):
        s = self.get_final_summary()
        print(f"\n{'='*50}")
        print(f"  Metrics — {s['strategy']}")
        print(f"{'='*50}")
        print(f"  Logical Writes  (Host)     : {s['logical_writes']:>12,}")
        print(f"  Physical Writes (NAND)     : {s['physical_writes']:>12,}")
        print(f"  Write Amplification (WAF)  : {s['waf']:>12.4f}")
        print(f"  Wear Variance              : {s['wear_variance']:>12.4f}")
        print(f"  Estimated Lifetime (writes): {s['lifetime_estimate']:>12,}")
        print(f"  GC Triggered               : {s['gc_count']:>12,}")
        print(f"  Max Block Erase Count      : {s['max_erase_count']:>12,}")
        print(f"  Min Block Erase Count      : {s['min_erase_count']:>12,}")
        print(f"{'='*50}")
