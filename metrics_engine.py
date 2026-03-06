"""
metrics_engine.py  —  RRA-FTL Enhanced Metrics Engine
======================================================
New metrics added over original:
  1. erase_time_ms      — total adaptive erase latency (novel: varies by block age)
  2. erase_error_rate   — fleet-wide simulated erase failure rate
  3. remaining_budget   — mean Weibull remaining budget across all blocks
  4. lifespan_years()   — firmware-native lifespan projection (no external tools)
                          using the full endurance conversion chain:
                          IOPS -> MB/s -> GB/day -> TBW -> Years
  5. Pareto window data — exposes current alpha/beta/gamma for each checkpoint
"""

import math

MAX_ERASE_LIMIT   = 10_000
CHECKPOINT_EVERY  = 1_000

# Workload assumption for lifespan projection (configurable)
PAGE_SIZE_KB      = 4        # 4 KB pages (typical NVMe)
IOPS_ASSUMED      = 15       # assumed sustained IOPS for projection
BLOCK_SIZE_KIB    = 64       # I/O block size used in throughput formula
WARRANTY_YEARS    = 5        # warranty period for TBW calculation


class MetricsEngine:
    def __init__(self, ftl_instance, strategy_name: str,
                 max_erase_limit: int = MAX_ERASE_LIMIT,
                 checkpoint_every: int = CHECKPOINT_EVERY):

        self.ftl             = ftl_instance
        self.strategy_name   = strategy_name
        self.max_erase_limit = max_erase_limit
        self.checkpoint_every = checkpoint_every

        # Time-series
        self.ts_host_writes     = []
        self.ts_physical_writes = []
        self.ts_waf             = []
        self.ts_wear_variance   = []
        self.ts_lifetime        = []
        self.ts_erase_time_ms   = []   # NEW: adaptive erase latency trend
        self.ts_erase_err_rate  = []   # NEW: erase error rate trend
        self.ts_rem_budget_mean = []   # NEW: mean Weibull remaining budget

    # ── Core metrics ──────────────────────────────────────────────────────────

    def logical_writes(self):
        return self.ftl.host_writes

    def physical_writes(self):
        return self.ftl.total_writes

    def waf(self):
        if self.ftl.host_writes == 0:
            return 1.0
        return self.ftl.total_writes / self.ftl.host_writes

    def wear_variance(self):
        counts = self.ftl.nand.get_erase_counts()
        if not counts:
            return 0.0
        mean = sum(counts) / len(counts)
        return sum((c - mean) ** 2 for c in counts) / len(counts)

    def lifetime_estimate(self):
        counts    = self.ftl.nand.get_erase_counts()
        max_erase = max(counts) if counts else 0
        if max_erase == 0:
            return float('inf')
        return (self.max_erase_limit / max_erase) * self.ftl.host_writes

    # ── NEW: Adaptive erase metrics ───────────────────────────────────────────

    def total_erase_time_ms(self):
        """Total adaptive erase latency accumulated across all blocks (ms)."""
        return self.ftl.nand.get_total_erase_time_ms()

    def erase_error_rate(self):
        """Simulated erase failure rate (errors per erase operation)."""
        return self.ftl.nand.get_erase_error_rate()

    def mean_remaining_budget(self):
        """Mean Weibull remaining_budget across all blocks (1.0=new, 0=dead)."""
        budgets = self.ftl.nand.get_remaining_budgets()
        if not budgets:
            return 1.0
        return sum(budgets) / len(budgets)

    # ── NEW: Firmware-native lifespan projection ──────────────────────────────

    def lifespan_projection(self,
                             capacity_gb=None,
                             iops=IOPS_ASSUMED,
                             block_size_kib=BLOCK_SIZE_KIB,
                             warranty_years=WARRANTY_YEARS):
        """
        Full endurance conversion chain — firmware-native (no external tools).

          Step 1: IOPS -> MB/s
                  mb_per_sec = iops * block_size_kib / 1024

          Step 2: MB/s -> GB/day
                  gb_per_day = mb_per_sec * 86400 / 1000

          Step 3: DWPD  (Drive Writes Per Day)
                  dwpd = gb_per_day / capacity_gb

          Step 4: TBW   (Total Bytes Written, TB)
                  tbw = gb_per_day * 365 * warranty_years / 1000

          Step 5: PBW   (Petabytes Written)
                  pbw = tbw / 1000

          Step 6: Lifetime adjusted for actual WAF vs ideal
                  effective_tbw = tbw / waf           (WAF degrades TBW)
                  lifetime_years = effective_tbw * 1000 / (gb_per_day * 365)

        Returns a dict of all intermediate values plus final lifetime.
        """
        nand     = self.ftl.nand
        cap_gb   = capacity_gb or (
            nand.logical_blocks_count * nand.pages_per_block * PAGE_SIZE_KB / (1024 * 1024)
        )

        mb_per_sec      = iops * block_size_kib / 1024.0
        gb_per_day      = mb_per_sec * 86_400 / 1_000.0
        dwpd            = gb_per_day / cap_gb if cap_gb > 0 else 0
        tbw_rated       = gb_per_day * 365 * warranty_years / 1_000.0
        pbw             = tbw_rated / 1_000.0
        current_waf     = self.waf()
        effective_tbw   = tbw_rated / current_waf if current_waf > 0 else tbw_rated
        lifetime_years  = (effective_tbw * 1_000.0) / (gb_per_day * 365.0) if gb_per_day > 0 else 0

        return {
            "capacity_gb":     round(cap_gb, 2),
            "iops":            iops,
            "block_size_kib":  block_size_kib,
            "mb_per_sec":      round(mb_per_sec, 4),
            "gb_per_day":      round(gb_per_day, 2),
            "dwpd":            round(dwpd, 4),
            "tbw_rated_tb":    round(tbw_rated, 3),
            "pbw":             round(pbw, 6),
            "waf":             round(current_waf, 4),
            "effective_tbw_tb": round(effective_tbw, 3),
            "lifetime_years":  round(lifetime_years, 3),
        }

    # ── Checkpoint recorder ───────────────────────────────────────────────────

    def record_checkpoint(self):
        self.ts_host_writes.append(self.logical_writes())
        self.ts_physical_writes.append(self.physical_writes())
        self.ts_waf.append(self.waf())
        self.ts_wear_variance.append(self.wear_variance())
        lt = self.lifetime_estimate()
        self.ts_lifetime.append(lt if lt != float('inf') else 0)
        self.ts_erase_time_ms.append(self.total_erase_time_ms())
        self.ts_erase_err_rate.append(self.erase_error_rate())
        self.ts_rem_budget_mean.append(self.mean_remaining_budget())

    # ── Summary ───────────────────────────────────────────────────────────────

    def get_final_summary(self):
        counts    = self.ftl.nand.get_erase_counts()
        max_erase = max(counts) if counts else 1
        min_erase = min(counts) if counts else 0
        lt        = self.lifetime_estimate()
        proj      = self.lifespan_projection()

        return {
            "strategy":           self.strategy_name,
            "logical_writes":     self.logical_writes(),
            "physical_writes":    self.physical_writes(),
            "waf":                round(self.waf(), 4),
            "wear_variance":      round(self.wear_variance(), 4),
            "lifetime_estimate":  int(lt) if lt != float('inf') else 999_999_999,
            "gc_count":           self.ftl.gc_count,
            "max_erase_count":    max_erase,
            "min_erase_count":    min_erase,
            "erase_counts":       counts,
            # RRA-FTL novel metrics
            "total_erase_ms":     round(self.total_erase_time_ms(), 2),
            "erase_error_rate":   round(self.erase_error_rate(), 8),
            "mean_rem_budget":    round(self.mean_remaining_budget(), 4),
            "lifespan_years":     proj["lifetime_years"],
            "effective_tbw_tb":   proj["effective_tbw_tb"],
            "gb_per_day":         proj["gb_per_day"],
            "dwpd":               proj["dwpd"],
        }

    def print_summary(self):
        s    = self.get_final_summary()
        proj = self.lifespan_projection()
        print(f"\n{'='*56}")
        print(f"  Metrics — {s['strategy']}")
        print(f"{'='*56}")
        print(f"  Logical Writes  (Host)       : {s['logical_writes']:>14,}")
        print(f"  Physical Writes (NAND)       : {s['physical_writes']:>14,}")
        print(f"  Write Amplification (WAF)    : {s['waf']:>14.4f}")
        print(f"  Wear Variance                : {s['wear_variance']:>14.4f}")
        print(f"  Estimated Lifetime (writes)  : {s['lifetime_estimate']:>14,}")
        print(f"  GC Triggered                 : {s['gc_count']:>14,}")
        print(f"  Max Block Erase Count        : {s['max_erase_count']:>14,}")
        print(f"  Min Block Erase Count        : {s['min_erase_count']:>14,}")
        print(f"  --- RRA-FTL Novel Metrics ---")
        print(f"  Total Erase Time (ms)        : {s['total_erase_ms']:>14,.2f}")
        print(f"  Erase Error Rate             : {s['erase_error_rate']:>14.2e}")
        print(f"  Mean Remaining Budget        : {s['mean_rem_budget']:>14.4f}")
        print(f"  --- Lifespan Projection ---")
        print(f"  Throughput (MB/s)            : {proj['mb_per_sec']:>14.4f}")
        print(f"  Daily Write Load (GB/day)    : {proj['gb_per_day']:>14.2f}")
        print(f"  DWPD                         : {proj['dwpd']:>14.4f}")
        print(f"  Rated TBW (TB)               : {proj['tbw_rated_tb']:>14.3f}")
        print(f"  WAF-Adjusted TBW (TB)        : {proj['effective_tbw_tb']:>14.3f}")
        print(f"  Projected Lifetime (years)   : {proj['lifetime_years']:>14.3f}")
        print(f"{'='*56}")
