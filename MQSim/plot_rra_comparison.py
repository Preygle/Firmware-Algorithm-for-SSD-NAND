"""
plot_rra_comparison.py — Generates comparison bar charts from 3 MQSim XML outputs
"""
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import os

FILES  = ["/tmp/sim_baseline.xml", "/tmp/sim_modern.xml", "/tmp/sim_rra.xml"]
LABELS = ["Baseline\n(GREEDY)", "Modern\n(Lifespan-FIFO)", "RRA-FTL v2\n(Composite+Hot)"]
COLORS = ["#4C9BE8", "#F4A261", "#2EC4B6"]
OUT    = "/tmp/rra_comparison.png"

def parse(path):
    tree = ET.parse(path)
    root = tree.getroot()
    r = {}
    def grab(el):
        for child in el:
            try:
                r[child.tag] = float(child.text)
            except (TypeError, ValueError):
                pass
            grab(child)
    grab(root)
    return r

data = [parse(f) for f in FILES]

# ── Metrics to plot ──────────────────────────────────────────────────────────
metrics = {
    "IOPS (write)":            [d.get("IOPS_Write",               d.get("IOPS", 0))        for d in data],
    "Avg Latency (µs)":        [d.get("Device_Response_Time",     0)                        for d in data],
    "Max Latency (µs)":        [d.get("Max_Device_Response_Time", 0)                        for d in data],
    "Bandwidth (B/s)":         [d.get("Bandwidth_Write",          d.get("Bandwidth", 0))   for d in data],
    "Avg Write Txn Time (ns)": [d.get("Average_Write_Transaction_Execution_Time", 0)        for d in data],
}

n_metrics = len(metrics)
fig, axes = plt.subplots(1, n_metrics, figsize=(18, 6))
fig.patch.set_facecolor("#0F172A")

for ax, (title, values) in zip(axes, metrics.items()):
    x = np.arange(len(LABELS))
    bars = ax.bar(x, values, color=COLORS, width=0.55, edgecolor='white', linewidth=0.5)

    # Mark best value
    if "Latency" in title or "Time" in title:
        best_i = np.argmin(values)
        arrow = "↓ best"
    else:
        best_i = np.argmax(values)
        arrow = "↑ best"

    for i, (bar, val) in enumerate(zip(bars, values)):
        label = f"{val:,.0f}"
        if i == best_i:
            label += f"\n★"
            bar.set_edgecolor("#FFD700")
            bar.set_linewidth(2.5)
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(values)*0.02,
                label, ha='center', va='bottom', color='white', fontsize=8.5, fontweight='bold')

    ax.set_title(title, color='white', fontsize=11, fontweight='bold', pad=10)
    ax.set_xticks(x)
    ax.set_xticklabels(LABELS, color='white', fontsize=8)
    ax.set_facecolor("#1E293B")
    ax.tick_params(colors='white')
    ax.spines[:].set_color('#334155')
    ax.yaxis.set_tick_params(labelcolor='white', labelsize=8)
    ax.set_ylim(0, max(values) * 1.25 if max(values) > 0 else 1)

# Legend patches
patches = [mpatches.Patch(color=c, label=l.replace('\n', ' ')) for c, l in zip(COLORS, LABELS)]
fig.legend(handles=patches, loc='lower center', ncol=3,
           facecolor='#1E293B', labelcolor='white', fontsize=10,
           framealpha=0.8, bbox_to_anchor=(0.5, -0.08))

fig.suptitle("RRA-FTL v2 vs Baseline vs Modern — MQSim Comparison",
             color='white', fontsize=15, fontweight='bold', y=1.02)

plt.tight_layout()
plt.savefig(OUT, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
print(f"Graph saved to: {OUT}")
print("\nRaw values:")
for title, values in metrics.items():
    print(f"  {title}:")
    for l, v in zip(LABELS, values):
        print(f"    {l.replace(chr(10),' '):30s}: {v:,.2f}")
