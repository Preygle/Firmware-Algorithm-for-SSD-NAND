"""
plot_comparison.py
===================
Generates 5 publication-ready comparison charts from MQSim baseline
and RRA-FTL output XML files.

Usage:
    python3 plot_comparison.py

Expects result XMLs at:
    results/baseline/data_seq_baseline.xml
    results/baseline/data_rand_baseline.xml
    results/baseline/data_hotspot_baseline.xml
    results/rra/data_seq_rra.xml
    results/rra/data_rand_rra.xml
    results/rra/data_hotspot_rra.xml

If RRA XMLs are not available yet, the script generates placeholder
charts with estimated RRA numbers from the paper (for presentation preview).

Output:
    results/graphs/01_waf.png
    results/graphs/02_wear_variance.png
    results/graphs/03_erase_spread.png
    results/graphs/04_latency.png
    results/graphs/05_lifetime.png
    results/graphs/00_summary_table.png
"""

import os
import sys
import xml.etree.ElementTree as ET
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR   = os.path.join(SCRIPT_DIR, "results", "baseline")
RRA_DIR    = os.path.join(SCRIPT_DIR, "results", "rra")
GRAPH_DIR  = os.path.join(SCRIPT_DIR, "results", "graphs")
os.makedirs(GRAPH_DIR, exist_ok=True)

WORKLOADS   = ["Sequential", "Random", "Hotspot (80/20)"]
BASE_FILES  = ["data_seq_baseline.xml",  "data_rand_baseline.xml",  "data_hotspot_baseline.xml"]
RRA_FILES   = ["data_seq_rra.xml",       "data_rand_rra.xml",       "data_hotspot_rra.xml"]

# ── Colours ──────────────────────────────────────────────────────────────────
C_BASE = "#E05C5C"   # red — baseline (legacy)
C_RRA  = "#4C9BE8"   # blue — RRA-FTL (improved)
plt.rcParams.update({
    "font.family":  "DejaVu Sans",
    "font.size":    11,
    "axes.grid":    True,
    "grid.alpha":   0.35,
    "figure.dpi":   150,
})


# ── XML Parser ───────────────────────────────────────────────────────────────
def parse_xml(path: str) -> dict:
    """Parse MQSim output XML.  Returns {} if file missing (uses estimates)."""
    if not os.path.exists(path):
        return {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return {}

    r = {}
    # Flow latency
    for flow in root.iter("IO_Flow_Statistics"):
        for ch in flow:
            try:    r[ch.tag] = float(ch.text)
            except: r[ch.tag] = ch.text
        break   # first flow only

    # Device stats
    dev = root.find("Device_Level_Statistics")
    if dev is not None:
        for ch in dev:
            try:    r[ch.tag] = float(ch.text)
            except: r[ch.tag] = ch.text

    # Erase counts → wear metrics
    ec = [int(b.find("Erase_Count").text)
          for b in root.iter("Block")
          if b.find("Erase_Count") is not None and b.find("Erase_Count").text]
    if ec:
        mean = sum(ec) / len(ec)
        r["wear_variance"]    = sum((x - mean)**2 for x in ec) / len(ec)
        r["max_erase_count"]  = max(ec)
        r["min_erase_count"]  = min(ec)
    else:
        r["wear_variance"]   = 0.0
        r["max_erase_count"] = 0
        r["min_erase_count"] = 0
    return r


def get_waf(r: dict) -> float:
    return r.get("WAF", r.get("Write_Amplification_Factor", 0.0)) or 0.0

def get_latency_us(r: dict) -> float:
    ns = r.get("Average_Response_Time_NS", 0.0)
    return (ns or 0.0) / 1000.0

def lifetime_years(r: dict, max_pe=10000) -> float:
    waf = get_waf(r)
    mx  = r.get("max_erase_count", 0)
    if waf <= 0 or mx <= 0:
        return 0.0
    return (max_pe / mx) / waf * 5.0   # normalised to 5-year baseline

# ── Fallback estimates (if RRA XMLs not yet generated) ───────────────────────
# Source: workload_hotspot.xml comment and RRA-FTL paper projections.
ESTIMATES = {
    "baseline": {
        "waf":           [1.05, 2.80, 3.60],
        "wear_variance": [0.20, 8.50, 36.0],
        "max_erase":     [120,  340,  620 ],
        "min_erase":     [112,  80,   18  ],
        "latency_us":    [310,  520,  640 ],
        "lifetime_yr":   [9.5,  4.2,  2.1 ],
    },
    "rra": {
        "waf":           [1.02, 2.10, 2.65],
        "wear_variance": [0.12, 1.80, 2.70],
        "max_erase":     [116,  220,  310 ],
        "min_erase":     [114,  195,  280 ],
        "latency_us":    [295,  390,  430 ],
        "lifetime_yr":   [9.9,  5.6,  3.8 ],
    },
}


def collect_metrics():
    """Parse real XMLs if available, otherwise fall back to estimates."""
    base_m = {"waf": [], "wear_variance": [], "max_erase": [],
              "min_erase": [], "latency_us": [], "lifetime_yr": []}
    rra_m  = {k: [] for k in base_m}
    use_estimates = False

    for bf, rf in zip(BASE_FILES, RRA_FILES):
        rb = parse_xml(os.path.join(BASE_DIR, bf))
        rr = parse_xml(os.path.join(RRA_DIR,  rf))
        if not rb or not rr:
            use_estimates = True
            break
        base_m["waf"].append(get_waf(rb))
        base_m["wear_variance"].append(rb.get("wear_variance", 0))
        base_m["max_erase"].append(rb.get("max_erase_count", 0))
        base_m["min_erase"].append(rb.get("min_erase_count", 0))
        base_m["latency_us"].append(get_latency_us(rb))
        base_m["lifetime_yr"].append(lifetime_years(rb))

        rra_m["waf"].append(get_waf(rr))
        rra_m["wear_variance"].append(rr.get("wear_variance", 0))
        rra_m["max_erase"].append(rr.get("max_erase_count", 0))
        rra_m["min_erase"].append(rr.get("min_erase_count", 0))
        rra_m["latency_us"].append(get_latency_us(rr))
        rra_m["lifetime_yr"].append(lifetime_years(rr))

    if use_estimates:
        print("[plot_comparison] INFO: RRA output XMLs not found — using paper estimates.")
        print("                        Re-run after RRA-FTL simulation to get real numbers.")
        base_m = ESTIMATES["baseline"]
        rra_m  = ESTIMATES["rra"]

    return base_m, rra_m, use_estimates


# ── Chart helpers ─────────────────────────────────────────────────────────────
def grouped_bar(ax, values_a, values_b, title, ylabel, higher_better=False):
    x     = np.arange(len(WORKLOADS))
    width = 0.35
    bars_a = ax.bar(x - width/2, values_a, width, label="Baseline (GREEDY)", color=C_BASE, edgecolor="white", linewidth=0.5)
    bars_b = ax.bar(x + width/2, values_b, width, label="RRA-FTL",           color=C_RRA,  edgecolor="white", linewidth=0.5)

    # Annotate improvement %
    for xa, va, vb in zip(x, values_a, values_b):
        if va > 0:
            pct = (vb - va) / va * 100
            sign = "+" if pct > 0 else ""
            col  = C_RRA if (pct > 0) == higher_better else C_BASE
            ax.text(xa, max(va, vb) * 1.04, f"{sign}{pct:.1f}%", ha="center", fontsize=8.5, color=col, fontweight="bold")

    ax.set_title(title, fontweight="bold", pad=10)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(WORKLOADS)
    ax.legend(framealpha=0.85)
    ax.set_ylim(0, max(max(values_a), max(values_b)) * 1.20)


def save(fig, name):
    path = os.path.join(GRAPH_DIR, name)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=== Generating Comparison Charts ===\n")
    base_m, rra_m, estimated = collect_metrics()
    suffix = " (Estimated)" if estimated else ""

    # 1. WAF
    fig, ax = plt.subplots(figsize=(8, 5))
    grouped_bar(ax, base_m["waf"], rra_m["waf"],
                f"Write Amplification Factor (WAF){suffix}",
                "WAF  (lower = better)", higher_better=False)
    ax.axhline(1.0, color="green", linestyle="--", linewidth=1, alpha=0.6, label="Ideal WAF = 1.0")
    ax.legend()
    save(fig, "01_waf.png")

    # 2. Wear Variance
    fig, ax = plt.subplots(figsize=(8, 5))
    grouped_bar(ax, base_m["wear_variance"], rra_m["wear_variance"],
                f"Wear Variance (Erase Count Spread){suffix}",
                "Variance  (lower = better)", higher_better=False)
    save(fig, "02_wear_variance.png")

    # 3. Max vs Min Erase Count
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    grouped_bar(axes[0], base_m["max_erase"], rra_m["max_erase"],
                f"Max Block Erase Count{suffix}", "Erase Count  (lower = better)", higher_better=False)
    grouped_bar(axes[1], base_m["min_erase"], rra_m["min_erase"],
                f"Min Block Erase Count{suffix}", "Erase Count  (higher = better)", higher_better=True)
    fig.suptitle("Wear Spread: Max vs Min Block Erase Counts", fontweight="bold", fontsize=13)
    save(fig, "03_erase_spread.png")

    # 4. Avg Latency
    fig, ax = plt.subplots(figsize=(8, 5))
    grouped_bar(ax, base_m["latency_us"], rra_m["latency_us"],
                f"Average I/O Latency{suffix}", "Latency (µs)  (lower = better)", higher_better=False)
    save(fig, "04_latency.png")

    # 5. Lifetime
    fig, ax = plt.subplots(figsize=(8, 5))
    grouped_bar(ax, base_m["lifetime_yr"], rra_m["lifetime_yr"],
                f"Estimated SSD Lifetime{suffix}", "Estimated Lifetime (years)  (higher = better)",
                higher_better=True)
    save(fig, "05_lifetime.png")

    # 6. Summary table image
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.axis("off")
    col_labels = ["Metric", "Seq Base", "Seq RRA", "Rand Base", "Rand RRA", "Hot Base", "Hot RRA"]
    rows = [
        ["WAF"]           + [f"{v:.2f}" for pair in zip(base_m["waf"],          rra_m["waf"])          for v in pair],
        ["Wear Variance"] + [f"{v:.1f}" for pair in zip(base_m["wear_variance"], rra_m["wear_variance"]) for v in pair],
        ["Max Erase"]     + [f"{v:.0f}" for pair in zip(base_m["max_erase"],     rra_m["max_erase"])     for v in pair],
        ["Latency (µs)"]  + [f"{v:.0f}" for pair in zip(base_m["latency_us"],   rra_m["latency_us"])    for v in pair],
        ["Lifetime (yr)"] + [f"{v:.1f}" for pair in zip(base_m["lifetime_yr"],  rra_m["lifetime_yr"])   for v in pair],
    ]
    tbl = ax.table(cellText=rows, colLabels=col_labels, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.scale(1.2, 2.0)
    # Colour header
    for j in range(len(col_labels)):
        tbl[0, j].set_facecolor("#2C3E50")
        tbl[0, j].set_text_props(color="white", fontweight="bold")
    # Colour RRA cols green-ish
    for i in range(1, len(rows)+1):
        for j in [2, 4, 6]:  # RRA columns
            tbl[i, j].set_facecolor("#DFF0D8")

    title = "Baseline vs RRA-FTL — Summary" + (" (Estimated)" if estimated else "")
    ax.set_title(title, fontweight="bold", fontsize=13, pad=20)
    save(fig, "00_summary_table.png")

    print(f"\n  All charts saved to: {GRAPH_DIR}")
    print(f"  {'NOTE: Using paper estimates — re-run after RRA simulation for real data.' if estimated else 'Using REAL simulation data.'}")


if __name__ == "__main__":
    main()
