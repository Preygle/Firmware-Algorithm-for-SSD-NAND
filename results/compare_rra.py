#!/usr/bin/env python3
"""
compare_rra.py — RRA-FTL v2 Comparison Tool
=============================================
Parses MQSim output XMLs for Baseline, Modern, and RRA-FTL v2,
prints a side-by-side comparison table, and saves a bar chart.

Usage:
    python3 compare_rra.py <baseline.xml> <modern.xml> <rra_v2.xml>

Output:
    - Printed comparison table in terminal
    - results/rra_comparison.png  (bar chart)

Example:
    python3 compare_rra.py /tmp/sim_baseline.xml /tmp/sim_modern.xml /tmp/sim_rra_v2.xml
"""

import sys
import os
import xml.etree.ElementTree as ET

# ── Try importing matplotlib (optional — text table always works) ─────────────
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("[WARN] matplotlib not installed — graph will be skipped.")
    print("       Install with: sudo apt-get install python3-matplotlib python3-numpy\n")

# ── Output directory (same folder as this script) ────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHART_OUT  = os.path.join(SCRIPT_DIR, "rra_comparison.png")


def parse(path):
    """Parse one MQSim XML result file into a flat metrics dict."""
    try:
        tree = ET.parse(path)
    except FileNotFoundError:
        print(f"ERROR: File not found: {path}")
        sys.exit(1)

    root  = tree.getroot()
    data  = {}

    def walk(el):
        for child in el:
            try:
                val = float(child.text) if child.text and child.text.strip() else None
                if val is not None:
                    data[child.tag] = val
            except (ValueError, TypeError):
                pass
            walk(child)
    walk(root)

    # Per-block erase counts (wear variance)
    erases = []
    for blk in root.iter("Block"):
        ec = blk.find("Erase_Count")
        if ec is not None and ec.text:
            try:
                erases.append(int(ec.text))
            except ValueError:
                pass
    if erases:
        mean = sum(erases) / len(erases)
        data["wear_variance"] = sum((x - mean) ** 2 for x in erases) / len(erases)
        data["max_erase"]     = max(erases)
        data["min_erase"]     = min(erases)
    else:
        data["wear_variance"] = 0.0
        data["max_erase"]     = 0
        data["min_erase"]     = 0

    return data


def lifespan(data, iops=None, block_kib=64, warranty=5, cap_gb=480):
    """Simple lifespan projection from WAF."""
    waf = data.get("WAF", data.get("Write_Amplification_Factor", 1.0)) or 1.0
    if iops is None:
        iops = data.get("IOPS_Write", data.get("IOPS", 7432))
    mb_s      = iops * block_kib / 1024.0
    gb_day    = mb_s * 86400 / 1000.0
    tbw       = gb_day * 365 * warranty / 1000.0
    eff_tbw   = tbw / waf
    life_yr   = (eff_tbw * 1000.0) / (gb_day * 365.0) if gb_day > 0 else 0
    return {"waf": round(waf, 4), "tbw_tb": round(eff_tbw, 3), "life_yr": round(life_yr, 3)}


def print_table(labels, datasets):
    """Print a formatted side-by-side comparison table."""
    col = 16
    sep = "=" * (36 + len(labels) * (col + 1))

    metrics = [
        ("IOPS Write",            [d.get("IOPS_Write",         d.get("IOPS", 0))   for d in datasets], False, ".0f"),
        ("Avg Latency (µs)",      [d.get("Device_Response_Time", 0)                 for d in datasets], True,  ".0f"),
        ("Max Latency (µs)",      [d.get("Max_Device_Response_Time", 0)             for d in datasets], True,  ".0f"),
        ("Bandwidth MB/s",        [d.get("Bandwidth_Write", d.get("Bandwidth",0))/1e6 for d in datasets], False, ".2f"),
        ("WAF",                   [d.get("WAF", 1.0)                                for d in datasets], True,  ".4f"),
        ("Wear Variance",         [d.get("wear_variance", 0.0)                      for d in datasets], True,  ".2f"),
        ("Max Erase Count",       [d.get("max_erase", 0)                            for d in datasets], True,  ".0f"),
        ("Effective TBW (TB)",    [lifespan(d)["tbw_tb"]                            for d in datasets], False, ".3f"),
        ("Lifetime (yrs)",        [lifespan(d)["life_yr"]                           for d in datasets], False, ".3f"),
        ("GC Executions",         [d.get("Total_GC_Executions",
                                   d.get("Issued_Flash_Erase_CMD", 0))              for d in datasets], False, ".0f"),
    ]

    print(f"\n{sep}")
    print(f"  {'METRIC':<34}" + "".join(f"{l:>{col}}" for l in labels))
    print(f"  {'-'*(32 + len(labels)*(col+1))}")

    for name, values, lower_better, fmt in metrics:
        valid = [(i, v) for i, v in enumerate(values) if v != 0]
        if valid:
            best_i = (min if lower_better else max)(valid, key=lambda x: x[1])[0]
        else:
            best_i = -1

        row = f"  {name:<34}"
        for i, v in enumerate(values):
            cell = f"{v:{fmt}}"
            star = "★" if i == best_i else " "
            row += f"{(cell + star):>{col}}"
        print(row)

    print(f"\n  ★ = best in category")
    print(sep + "\n")


def make_chart(labels, datasets, out_path):
    """Generate and save a comparison bar chart."""
    if not HAS_MPL:
        return

    COLORS = ["#4C9BE8", "#F4A261", "#2EC4B6"]
    metrics_plot = {
        "IOPS Write":       [d.get("IOPS_Write", d.get("IOPS", 0))         for d in datasets],
        "Avg Latency (µs)": [d.get("Device_Response_Time", 0)               for d in datasets],
        "Max Latency (µs)": [d.get("Max_Device_Response_Time", 0)           for d in datasets],
        "GC Executions":    [d.get("Total_GC_Executions",
                              d.get("Issued_Flash_Erase_CMD", 0))           for d in datasets],
        "Lifetime (yrs)":   [lifespan(d)["life_yr"]                         for d in datasets],
    }
    lower_better = {"Avg Latency (µs)": True, "Max Latency (µs)": True}

    n = len(metrics_plot)
    fig, axes = plt.subplots(1, n, figsize=(20, 6))
    fig.patch.set_facecolor("#0F172A")

    for ax, (title, values) in zip(axes, metrics_plot.items()):
        x    = np.arange(len(labels))
        bars = ax.bar(x, values, color=COLORS, width=0.5, edgecolor='white', linewidth=0.5)

        lb   = lower_better.get(title, False)
        best = (min if lb else max)(range(len(values)), key=lambda i: values[i]) \
               if any(v > 0 for v in values) else -1

        for i, (bar, val) in enumerate(zip(bars, values)):
            lbl = f"{val:,.0f}" if val > 100 else f"{val:.2f}"
            if i == best:
                lbl += "\n★"
                bar.set_edgecolor("#FFD700")
                bar.set_linewidth(2.5)
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_height() + max(values) * 0.02,
                    lbl, ha='center', va='bottom',
                    color='white', fontsize=8, fontweight='bold')

        ax.set_title(title, color='white', fontsize=11, fontweight='bold', pad=8)
        ax.set_xticks(x)
        ax.set_xticklabels([l.replace(" ", "\n") for l in labels], color='white', fontsize=8)
        ax.set_facecolor("#1E293B")
        ax.tick_params(colors='white')
        ax.spines[:].set_color('#334155')
        ax.yaxis.set_tick_params(labelcolor='white', labelsize=7)
        ax.set_ylim(0, max(values) * 1.28 if max(values) > 0 else 1)

    import matplotlib.patches as mpatches
    patches = [mpatches.Patch(color=c, label=l) for c, l in zip(COLORS, labels)]
    fig.legend(handles=patches, loc='lower center', ncol=3,
               facecolor='#1E293B', labelcolor='white', fontsize=10,
               framealpha=0.9, bbox_to_anchor=(0.5, -0.06))

    fig.suptitle("RRA-FTL v2 vs Baseline vs Modern — MQSim Results",
                 color='white', fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"Chart saved → {out_path}")


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    files  = sys.argv[1:4]
    labels = ["Baseline\n(GREEDY)", "Modern\n(Lifespan-FIFO)", "RRA-FTL v2\n(Adaptive)"]

    print("Parsing simulation results...")
    datasets = [parse(f) for f in files]

    print_table(labels, datasets)
    make_chart(labels, datasets, CHART_OUT)


if __name__ == "__main__":
    main()
