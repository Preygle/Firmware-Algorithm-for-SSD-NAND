"""
workload_generator.py
=====================
Workload Generation Module for SSD/NAND Firmware Simulation
------------------------------------------------------------
Generates logical write request sequences (LBA streams) that mimic
real-world application behavior. These are fed into the FTL layer
to stress-test Baseline vs Adaptive firmware algorithms.

Workload Types:
    1. Sequential  – video recording, backups, file downloads
    2. Random      – databases, OS file system operations
    3. Hotspot     – logs, cache, metadata (80/20 hot/cold split) ★ KEY
    4. Mixed       – realistic blend of all three

Usage:
    from workload_generator import WorkloadGenerator

    wg = WorkloadGenerator(max_lba=1000)
    workload = wg.sequential_workload(num_requests=10_000)

    for lba in workload:
        ftl.write(lba)
"""

import random
import statistics
from collections import Counter
from typing import List, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Default Configuration
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MAX_LBA        = 1000   # Total logical address space
DEFAULT_NUM_REQUESTS   = 10_000 # Write operations per test run
DEFAULT_HOTSPOT_RATIO  = 0.80   # 80% of writes go to hot region
DEFAULT_HOT_RANGE      = (0, 100)   # Hot region: small, frequently hit
DEFAULT_COLD_RANGE     = (101, 999) # Cold region: large, rarely hit


# ─────────────────────────────────────────────────────────────────────────────
# WorkloadGenerator Class
# ─────────────────────────────────────────────────────────────────────────────

class WorkloadGenerator:
    """
    Generates configurable LBA write sequences for SSD firmware simulation.

    Parameters
    ----------
    max_lba : int
        Maximum logical block address. Defines the total address space.
    hotspot_ratio : float
        Fraction of writes directed to the hot region (default: 0.80).
    hot_range : tuple
        (min_lba, max_lba) for the hot region.
    cold_range : tuple
        (min_lba, max_lba) for the cold region.
    seed : int or None
        Random seed for reproducibility. None = non-deterministic.
    """

    def __init__(
        self,
        max_lba: int = DEFAULT_MAX_LBA,
        hotspot_ratio: float = DEFAULT_HOTSPOT_RATIO,
        hot_range: Tuple[int, int] = DEFAULT_HOT_RANGE,
        cold_range: Tuple[int, int] = DEFAULT_COLD_RANGE,
        seed: int = None,
    ):
        self.max_lba       = max_lba
        self.hotspot_ratio = hotspot_ratio
        self.hot_range     = hot_range
        self.cold_range    = cold_range

        if seed is not None:
            random.seed(seed)

        # Validate ranges
        assert 0 <= hotspot_ratio <= 1, "hotspot_ratio must be between 0 and 1"
        assert hot_range[0] <= hot_range[1], "Invalid hot_range"
        assert cold_range[0] <= cold_range[1], "Invalid cold_range"
        assert hot_range[1] < max_lba, "hot_range exceeds max_lba"
        assert cold_range[1] < max_lba, "cold_range exceeds max_lba"


    # ─── 1. Sequential Workload ───────────────────────────────────────────────

    def sequential_workload(
        self,
        num_requests: int = DEFAULT_NUM_REQUESTS,
        max_lba: int = None,
        start: int = None,
    ) -> List[int]:
        """
        Generate sequential LBA writes — mimics video recording, backups,
        and large file downloads.

        Pattern: start → start+1 → start+2 → ... (wraps around if needed)

        Parameters
        ----------
        num_requests : int
            Number of write operations.
        max_lba : int, optional
            Override the instance max_lba for this call.
        start : int, optional
            Starting LBA. Random if not specified.

        Returns
        -------
        List[int]
            Ordered list of LBAs to write.
        """
        max_lba = max_lba or self.max_lba

        if start is None:
            # Pick a random start so we don't always begin at 0
            start = random.randint(0, max_lba - 1)

        lbas = [(start + i) % max_lba for i in range(num_requests)]
        return lbas


    # ─── 2. Random Workload ───────────────────────────────────────────────────

    def random_workload(
        self,
        num_requests: int = DEFAULT_NUM_REQUESTS,
        max_lba: int = None,
    ) -> List[int]:
        """
        Generate uniformly random LBA writes — mimics databases and
        OS file system operations.

        Pattern: completely unpredictable spread across full LBA space.

        Parameters
        ----------
        num_requests : int
            Number of write operations.
        max_lba : int, optional
            Override the instance max_lba for this call.

        Returns
        -------
        List[int]
            Random list of LBAs.
        """
        max_lba = max_lba or self.max_lba
        return [random.randint(0, max_lba - 1) for _ in range(num_requests)]


    # ─── 3. Hotspot Workload (★ Most Important) ───────────────────────────────

    def hotspot_workload(
        self,
        num_requests: int = DEFAULT_NUM_REQUESTS,
        hotspot_ratio: float = None,
        hot_range: Tuple[int, int] = None,
        cold_range: Tuple[int, int] = None,
    ) -> List[int]:
        """
        Generate a hot/cold skewed workload — mimics frequently updated logs,
        application caches, and metadata regions.

        ★ This is your most powerful stress test for the adaptive firmware.

        Pattern:
            ~80% of writes → hot_range  (small LBA region, few addresses)
            ~20% of writes → cold_range (large LBA region, many addresses)

        Effect on Baseline FTL:
            - Same physical blocks erased repeatedly
            - Severe wear imbalance → high wear variance
            - High Write Amplification Factor (WAF)

        Effect on Adaptive FTL:
            - Hot/cold page separation reduces unnecessary movement
            - Wear leveling migrates cold data to balance erase counts
            - WAF and variance significantly lower

        Parameters
        ----------
        num_requests : int
            Number of write operations.
        hotspot_ratio : float, optional
            Override instance hotspot_ratio for this call.
        hot_range : tuple, optional
            Override instance hot_range (min_lba, max_lba).
        cold_range : tuple, optional
            Override instance cold_range (min_lba, max_lba).

        Returns
        -------
        List[int]
            LBA list with skewed hot/cold distribution.
        """
        ratio      = hotspot_ratio if hotspot_ratio is not None else self.hotspot_ratio
        hot_range  = hot_range  or self.hot_range
        cold_range = cold_range or self.cold_range

        lbas = []
        for _ in range(num_requests):
            if random.random() < ratio:
                lbas.append(random.randint(*hot_range))   # hot write
            else:
                lbas.append(random.randint(*cold_range))  # cold write
        return lbas


    # ─── 4. Mixed Workload ────────────────────────────────────────────────────

    def mixed_workload(
        self,
        num_requests: int = DEFAULT_NUM_REQUESTS,
        max_lba: int = None,
        random_ratio: float = 0.40,
        sequential_ratio: float = 0.30,
        # hotspot fills the remaining fraction (1 - random - sequential)
    ) -> List[int]:
        """
        Generate a realistic mixed workload — no real-world SSD sees clean
        single-pattern traffic. Combines random, sequential, and hotspot writes.

        Default split:
            40% random      (database-style)
            30% sequential  (streaming-style)
            30% hotspot     (log/cache-style)

        Parameters
        ----------
        num_requests : int
            Number of write operations.
        max_lba : int, optional
            Override the instance max_lba.
        random_ratio : float
            Fraction of writes that are random (default: 0.40).
        sequential_ratio : float
            Fraction of writes that are sequential (default: 0.30).

        Returns
        -------
        List[int]
            Mixed LBA list.
        """
        max_lba = max_lba or self.max_lba
        hotspot_ratio_in_mix = 1.0 - random_ratio - sequential_ratio

        assert hotspot_ratio_in_mix >= 0, \
            "random_ratio + sequential_ratio must not exceed 1.0"

        seq_cursor = random.randint(0, max_lba - 1)  # rolling sequential pointer
        lbas = []

        for _ in range(num_requests):
            r = random.random()

            if r < random_ratio:
                # Random write
                lbas.append(random.randint(0, max_lba - 1))

            elif r < random_ratio + sequential_ratio:
                # Sequential write — advances the cursor
                lbas.append(seq_cursor % max_lba)
                seq_cursor += 1

            else:
                # Hotspot write — uses instance hot/cold ranges
                if random.random() < self.hotspot_ratio:
                    lbas.append(random.randint(*self.hot_range))
                else:
                    lbas.append(random.randint(*self.cold_range))

        return lbas


    # ─── Utility: Workload Statistics ─────────────────────────────────────────

    def analyze_workload(self, lbas: List[int], label: str = "Workload") -> dict:
        """
        Print and return statistics about a generated workload.

        Shows:
        - Total writes
        - Unique LBAs touched (overwrite rate)
        - Top 10 hottest LBAs
        - Distribution between hot and cold regions

        Parameters
        ----------
        lbas : List[int]
            The workload to analyze.
        label : str
            Label for display purposes.

        Returns
        -------
        dict
            Summary statistics.
        """
        total        = len(lbas)
        unique_lbas  = len(set(lbas))
        overwrite_pct = (1 - unique_lbas / total) * 100 if total > 0 else 0
        freq          = Counter(lbas)
        top10         = freq.most_common(10)

        hot_writes  = sum(1 for lba in lbas if self.hot_range[0] <= lba <= self.hot_range[1])
        cold_writes = sum(1 for lba in lbas if self.cold_range[0] <= lba <= self.cold_range[1])
        hot_pct     = (hot_writes / total * 100) if total > 0 else 0
        cold_pct    = (cold_writes / total * 100) if total > 0 else 0

        counts = list(freq.values())
        avg_writes_per_lba = statistics.mean(counts) if counts else 0
        max_writes         = max(counts) if counts else 0

        stats = {
            "label":               label,
            "total_writes":        total,
            "unique_lbas":         unique_lbas,
            "overwrite_pct":       round(overwrite_pct, 2),
            "hot_write_pct":       round(hot_pct, 2),
            "cold_write_pct":      round(cold_pct, 2),
            "avg_writes_per_lba":  round(avg_writes_per_lba, 2),
            "max_writes_single_lba": max_writes,
            "top10_hot_lbas":      top10,
        }

        # ── Print summary ──
        print(f"\n{'─'*55}")
        print(f"  📊 Workload Analysis: {label}")
        print(f"{'─'*55}")
        print(f"  Total writes       : {total:,}")
        print(f"  Unique LBAs        : {unique_lbas:,}  ({100-overwrite_pct:.1f}% new, {overwrite_pct:.1f}% overwrites)")
        print(f"  Hot region writes  : {hot_writes:,}  ({hot_pct:.1f}%)  [{self.hot_range[0]}–{self.hot_range[1]}]")
        print(f"  Cold region writes : {cold_writes:,}  ({cold_pct:.1f}%)  [{self.cold_range[0]}–{self.cold_range[1]}]")
        print(f"  Avg writes/LBA     : {avg_writes_per_lba:.2f}")
        print(f"  Max writes (1 LBA) : {max_writes}")
        print(f"  Top 5 hottest LBAs : {top10[:5]}")
        print(f"{'─'*55}")

        return stats


# ─────────────────────────────────────────────────────────────────────────────
# Standalone Test Cases
# ─────────────────────────────────────────────────────────────────────────────

def run_test_cases():
    """
    Generates the standard 10K test workloads and analyzes each one.
    These are intended to be fed into Baseline FTL and Adaptive FTL
    for metric comparison.

    Integration with main.py:
        from workload_generator import WorkloadGenerator
        wg = WorkloadGenerator(max_lba=1000, seed=42)
        workloads = {
            "Sequential":   wg.sequential_workload(10_000),
            "Random":       wg.random_workload(10_000),
            "Hotspot":      wg.hotspot_workload(10_000),
            "Mixed":        wg.mixed_workload(10_000),
        }
        for lba in workloads["Hotspot"]:
            ftl.write(lba)
    """
    print("=" * 55)
    print("  SSD Workload Generator — Test Suite")
    print("  Each workload: 10,000 writes | LBA space: 0–999")
    print("=" * 55)

    wg = WorkloadGenerator(
        max_lba       = 1000,
        hotspot_ratio = 0.80,
        hot_range     = (0, 99),
        cold_range    = (100, 999),
        seed          = 42          # reproducible results
    )

    # ── Generate all 4 workloads ──
    seq  = wg.sequential_workload(num_requests=10_000)
    rnd  = wg.random_workload(num_requests=10_000)
    hot  = wg.hotspot_workload(num_requests=10_000)
    mix  = wg.mixed_workload(num_requests=10_000)

    # ── Analyze each ──
    wg.analyze_workload(seq,  label="Sequential  (video/backup)")
    wg.analyze_workload(rnd,  label="Random      (database/OS)")
    wg.analyze_workload(hot,  label="Hotspot 80/20 ★ (logs/cache)")
    wg.analyze_workload(mix,  label="Mixed       (realistic blend)")

    print("\n✅ All workloads generated successfully.")
    print("   ➡  Feed these into Baseline FTL and Adaptive FTL")
    print("   ➡  Metrics Engineer: compare WAF, wear variance, lifetime")
    print("   ➡  Hotspot workload is the key stress test — watch WAF gap!\n")

    return {
        "sequential": seq,
        "random":     rnd,
        "hotspot":    hot,
        "mixed":      mix,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    workloads = run_test_cases()
