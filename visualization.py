"""
visualization.py  —  Engineer 3: Chart Generator
=================================================
Takes live data collected by MetricsEngine and produces 4 charts:

  1. Wear Heatmap              — per-block erase counts (Baseline vs Adaptive)
  2. WAF Graph                 — WAF over time for both strategies
  3. Lifetime Improvement Graph— lifetime projection over time
  4. Baseline vs Adaptive      — final comparison bar chart (all metrics)

Run independently after simulation:
    from visualization import Visualizer
    viz = Visualizer(output_dir="charts")
    viz.plot_all(baseline_engine, adaptive_engine, workload_name="Random")
"""

import os
import math
import matplotlib
matplotlib.use('Agg')          # works without a display (Windows/Linux/Mac)
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np


# ── Colour theme ─────────────────────────────────────────────────────────────
BG       = "#0F1117"
PANEL    = "#1A1D2E"
GRID_C   = "#2A2D3E"
TEXT_C   = "#E8E8F0"
ACCENT   = "#F5A623"
BASE_COL = "#E05C5C"    # red  — Baseline
ADPT_COL = "#4A90D9"    # blue — Adaptive


class Visualizer:

    def __init__(self, output_dir: str = "charts"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _new_fig(self, w, h):
        fig = plt.figure(figsize=(w, h), facecolor=BG)
        return fig

    def _style(self, ax, title="", xlabel="", ylabel=""):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=TEXT_C, labelsize=8)
        for sp in ax.spines.values():
            sp.set_edgecolor(GRID_C)
        ax.grid(True, color=GRID_C, linewidth=0.5, alpha=0.6)
        if title:
            ax.set_title(title, color=TEXT_C, fontsize=11,
                         fontweight='bold', pad=10)
        if xlabel:
            ax.set_xlabel(xlabel, color=TEXT_C, fontsize=9)
        if ylabel:
            ax.set_ylabel(ylabel, color=TEXT_C, fontsize=9)

    def _save(self, fig, filename):
        path = os.path.join(self.output_dir, filename)
        fig.savefig(path, dpi=150, bbox_inches='tight', facecolor=BG)
        plt.close(fig)
        print(f"  [chart saved] {path}")
        return path

    # ─────────────────────────────────────────────────────────────────────────
    # 1. WEAR HEATMAP
    # ─────────────────────────────────────────────────────────────────────────

    def plot_wear_heatmap(self, base_engine, adpt_engine,
                          workload_name: str = "") -> str:
        """
        Visualises the final per-block erase count as a 2-D colour grid.
        Uniform colour = healthy wear leveling.
        Hotspots = premature block death.
        """
        base_counts = base_engine.get_final_summary()["erase_counts"]
        adpt_counts = adpt_engine.get_final_summary()["erase_counts"]

        n = len(base_counts)
        cols = max(1, math.ceil(math.sqrt(n)))
        rows = max(1, math.ceil(n / cols))

        def _grid(counts):
            padded = list(counts) + [0] * (rows * cols - len(counts))
            return np.array(padded, dtype=float).reshape(rows, cols)

        bg = _grid(base_counts)
        ag = _grid(adpt_counts)
        vmax = max(bg.max(), ag.max(), 1)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5), facecolor=BG)
        title = f"Block Erase Count Heatmap — {workload_name}" if workload_name \
                else "Block Erase Count Heatmap"
        fig.suptitle(title + "\n(uniform colour = healthy wear leveling)",
                     color=TEXT_C, fontsize=13, fontweight='bold')

        im1 = ax1.imshow(bg, vmin=0, vmax=vmax, cmap='YlOrRd', aspect='auto')
        ax1.set_title("Baseline FTL  —  Wear Hotspots",
                      color=BASE_COL, fontsize=11, fontweight='bold')

        im2 = ax2.imshow(ag, vmin=0, vmax=vmax, cmap='YlGnBu', aspect='auto')
        ax2.set_title("Adaptive FTL  —  Distributed Wear",
                      color=ADPT_COL, fontsize=11, fontweight='bold')

        for ax, im in [(ax1, im1), (ax2, im2)]:
            ax.set_facecolor(PANEL)
            ax.tick_params(colors=TEXT_C, labelsize=7)
            ax.set_xlabel("Block Column", color=TEXT_C, fontsize=8)
            ax.set_ylabel("Block Row",    color=TEXT_C, fontsize=8)
            cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            cb.set_label("Erase Count", color=TEXT_C, fontsize=8)
            cb.ax.yaxis.set_tick_params(color=TEXT_C)
            plt.setp(cb.ax.yaxis.get_ticklabels(), color=TEXT_C)

        # Variance delta annotation
        bv = float(np.var(base_counts))
        av = float(np.var(adpt_counts))
        pct = (bv - av) / bv * 100 if bv > 0 else 0
        fig.text(0.5, 0.01,
                 f"Wear Variance:  Baseline = {bv:.1f}   →   "
                 f"Adaptive = {av:.1f}   ({pct:.1f}% reduction)",
                 ha='center', color=ACCENT, fontsize=9, fontweight='bold')

        plt.tight_layout(rect=[0, 0.05, 1, 1])
        safe = workload_name.replace(" ", "_").replace("/", "-") \
                            .replace("(", "").replace(")", "")
        return self._save(fig, f"1_wear_heatmap_{safe}.png")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. WAF GRAPH
    # ─────────────────────────────────────────────────────────────────────────

    def plot_waf_graph(self, base_engine, adpt_engine,
                       workload_name: str = "") -> str:
        """
        WAF over simulation time (host writes) for both strategies.
        Shows how write amplification evolves as the drive fills and GC runs.
        """
        fig, ax = self._new_fig(10, 5), None
        ax = fig.add_subplot(111)

        ax.plot(base_engine.ts_host_writes, base_engine.ts_waf,
                color=BASE_COL, linewidth=2, label="Baseline FTL", alpha=0.9)
        ax.plot(adpt_engine.ts_host_writes, adpt_engine.ts_waf,
                color=ADPT_COL, linewidth=2, label="Adaptive FTL",
                alpha=0.9, linestyle='--')
        ax.axhline(y=1.0, color=ACCENT, linewidth=1, linestyle=':',
                   alpha=0.7, label="Ideal WAF = 1.0")

        title = f"Write Amplification Factor (WAF) Over Time"
        if workload_name:
            title += f" — {workload_name}"
        self._style(ax, title=title,
                    xlabel="Host Writes (Logical)",
                    ylabel="WAF  (lower = better)")

        # Shade the gap between curves
        x  = base_engine.ts_host_writes
        b  = base_engine.ts_waf
        a  = adpt_engine.ts_waf
        mn = min(len(x), len(b), len(a))
        ax.fill_between(x[:mn], b[:mn], a[:mn],
                        where=[bi > ai for bi, ai in zip(b[:mn], a[:mn])],
                        alpha=0.15, color=BASE_COL,
                        label="Baseline worse region")
        ax.fill_between(x[:mn], b[:mn], a[:mn],
                        where=[ai > bi for bi, ai in zip(b[:mn], a[:mn])],
                        alpha=0.15, color=ADPT_COL,
                        label="Adaptive worse region")

        ax.legend(fontsize=8, facecolor=PANEL, labelcolor=TEXT_C,
                  edgecolor=GRID_C)

        # Annotate final values
        if base_engine.ts_waf:
            ax.annotate(f"  {base_engine.ts_waf[-1]:.2f}",
                        xy=(base_engine.ts_host_writes[-1], base_engine.ts_waf[-1]),
                        color=BASE_COL, fontsize=8, fontweight='bold')
        if adpt_engine.ts_waf:
            ax.annotate(f"  {adpt_engine.ts_waf[-1]:.2f}",
                        xy=(adpt_engine.ts_host_writes[-1], adpt_engine.ts_waf[-1]),
                        color=ADPT_COL, fontsize=8, fontweight='bold')

        plt.tight_layout()
        safe = workload_name.replace(" ", "_").replace("/", "-") \
                            .replace("(", "").replace(")", "")
        return self._save(fig, f"2_waf_graph_{safe}.png")

    # ─────────────────────────────────────────────────────────────────────────
    # 3. LIFETIME IMPROVEMENT GRAPH
    # ─────────────────────────────────────────────────────────────────────────

    def plot_lifetime_graph(self, base_engine, adpt_engine,
                            workload_name: str = "") -> str:
        """
        Projected SSD lifetime over simulation time.
        Shows how the Adaptive algorithm extends drive longevity vs Baseline.
        """
        fig = self._new_fig(10, 5)
        ax  = fig.add_subplot(111)

        # Convert to millions for readability
        base_lt = [v / 1e6 for v in base_engine.ts_lifetime]
        adpt_lt = [v / 1e6 for v in adpt_engine.ts_lifetime]

        ax.plot(base_engine.ts_host_writes, base_lt,
                color=BASE_COL, linewidth=2, label="Baseline FTL", alpha=0.9)
        ax.plot(adpt_engine.ts_host_writes, adpt_lt,
                color=ADPT_COL, linewidth=2, label="Adaptive FTL",
                alpha=0.9, linestyle='--')

        # Shade the improvement area
        x   = base_engine.ts_host_writes
        mn  = min(len(x), len(base_lt), len(adpt_lt))
        ax.fill_between(x[:mn], base_lt[:mn], adpt_lt[:mn],
                        where=[a > b for b, a in zip(base_lt[:mn], adpt_lt[:mn])],
                        alpha=0.2, color=ADPT_COL, label="Lifetime gain")

        title = "Estimated SSD Lifetime Projection Over Time"
        if workload_name:
            title += f" — {workload_name}"
        self._style(ax, title=title,
                    xlabel="Host Writes So Far",
                    ylabel="Projected Lifetime (Million Writes)")

        ax.legend(fontsize=8, facecolor=PANEL, labelcolor=TEXT_C,
                  edgecolor=GRID_C)

        # Final value annotations
        if base_lt:
            ax.annotate(f"  {base_lt[-1]:.2f}M",
                        xy=(base_engine.ts_host_writes[-1], base_lt[-1]),
                        color=BASE_COL, fontsize=8, fontweight='bold')
        if adpt_lt:
            ax.annotate(f"  {adpt_lt[-1]:.2f}M",
                        xy=(adpt_engine.ts_host_writes[-1], adpt_lt[-1]),
                        color=ADPT_COL, fontsize=8, fontweight='bold')

        plt.tight_layout()
        safe = workload_name.replace(" ", "_").replace("/", "-") \
                            .replace("(", "").replace(")", "")
        return self._save(fig, f"3_lifetime_graph_{safe}.png")

    # ─────────────────────────────────────────────────────────────────────────
    # 4. BASELINE vs ADAPTIVE COMPARISON CHART
    # ─────────────────────────────────────────────────────────────────────────

    def plot_comparison_chart(self, base_engine, adpt_engine,
                              workload_name: str = "") -> str:
        """
        Side-by-side bar chart comparing all key final metrics:
          - Logical Writes
          - Physical Writes
          - WAF
          - Wear Variance
          - Estimated Lifetime
        """
        bs = base_engine.get_final_summary()
        ad = adpt_engine.get_final_summary()

        # Define what to show and how to scale each metric
        metrics_config = [
            ("Logical\nWrites",   bs["logical_writes"]  / 1e3,  ad["logical_writes"]  / 1e3,  "K writes"),
            ("Physical\nWrites",  bs["physical_writes"] / 1e3,  ad["physical_writes"] / 1e3,  "K writes"),
            ("WAF",               bs["waf"],                     ad["waf"],                    "(×)"),
            ("Wear\nVariance",    bs["wear_variance"],            ad["wear_variance"],           "(σ²)"),
            ("Lifetime\nEst.",    bs["lifetime_estimate"] / 1e6, ad["lifetime_estimate"] / 1e6, "M writes"),
        ]

        labels  = [m[0] for m in metrics_config]
        b_vals  = [m[1] for m in metrics_config]
        a_vals  = [m[2] for m in metrics_config]
        units   = [m[3] for m in metrics_config]

        x     = np.arange(len(labels))
        width = 0.35

        fig, ax = self._new_fig(12, 6), None
        ax = fig.add_subplot(111)

        bars1 = ax.bar(x - width / 2, b_vals, width,
                       label="Baseline FTL", color=BASE_COL,
                       alpha=0.85, edgecolor=BG, linewidth=0.8)
        bars2 = ax.bar(x + width / 2, a_vals, width,
                       label="Adaptive FTL", color=ADPT_COL,
                       alpha=0.85, edgecolor=BG, linewidth=0.8)

        # Value labels on top of bars
        for bar, unit in zip(bars1, units):
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h * 1.01,
                    f"{h:.2f}", ha='center', va='bottom',
                    color=BASE_COL, fontsize=7.5, fontweight='bold')
        for bar, unit in zip(bars2, units):
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h * 1.01,
                    f"{h:.2f}", ha='center', va='bottom',
                    color=ADPT_COL, fontsize=7.5, fontweight='bold')

        # Unit labels below x-axis ticks
        ax.set_xticks(x)
        ax.set_xticklabels(
            [f"{l}\n{u}" for l, u in zip(labels, units)],
            color=TEXT_C, fontsize=8.5
        )

        title = "Baseline vs Adaptive — Final Metrics Comparison"
        if workload_name:
            title += f"\n{workload_name}"
        self._style(ax, title=title, ylabel="Value (scaled by unit shown)")

        ax.legend(fontsize=9, facecolor=PANEL, labelcolor=TEXT_C,
                  edgecolor=GRID_C)

        # Delta annotations (improvement %)
        improvements = {
            "WAF":      (bs["waf"]            - ad["waf"])            / bs["waf"]            * 100 if bs["waf"]            > 0 else 0,
            "Variance": (bs["wear_variance"]  - ad["wear_variance"])  / bs["wear_variance"]  * 100 if bs["wear_variance"]  > 0 else 0,
            "Lifetime": (ad["lifetime_estimate"] - bs["lifetime_estimate"]) / bs["lifetime_estimate"] * 100 if bs["lifetime_estimate"] > 0 else 0,
        }
        summary_line = (
            f"WAF {improvements['WAF']:+.1f}%  |  "
            f"Wear Variance {improvements['Variance']:+.1f}%  |  "
            f"Lifetime {improvements['Lifetime']:+.1f}%   "
            f"(positive = Adaptive is better)"
        )
        fig.text(0.5, 0.01, summary_line,
                 ha='center', color=ACCENT, fontsize=9, fontweight='bold')

        plt.tight_layout(rect=[0, 0.04, 1, 1])
        safe = workload_name.replace(" ", "_").replace("/", "-") \
                            .replace("(", "").replace(")", "")
        return self._save(fig, f"4_comparison_{safe}.png")

    # ─────────────────────────────────────────────────────────────────────────
    # Convenience: generate all 4 charts at once
    # ─────────────────────────────────────────────────────────────────────────

    def plot_all(self, base_engine, adpt_engine,
                 workload_name: str = "") -> list:
        """Generate all 4 charts and return their file paths."""
        print(f"\n  Generating charts for: {workload_name or 'simulation'}")
        paths = [
            self.plot_wear_heatmap    (base_engine, adpt_engine, workload_name),
            self.plot_waf_graph       (base_engine, adpt_engine, workload_name),
            self.plot_lifetime_graph  (base_engine, adpt_engine, workload_name),
            self.plot_comparison_chart(base_engine, adpt_engine, workload_name),
        ]
        return paths
