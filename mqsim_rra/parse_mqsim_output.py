"""
parse_mqsim_output.py
======================
Parses MQSim's XML output file and prints the metrics that matter for
the RRA-FTL hackathon evaluation.

MQSim writes one output XML per workload scenario.  Typical filename:
  workload_scenario_1.xml  (or whatever the workload XML was named)

Usage:
  python3 parse_mqsim_output.py <baseline_output.xml> <rra_output.xml>

Example:
  python3 parse_mqsim_output.py \\
      workloads/workload_sequential_scenario_1.xml \\
      workloads/workload_sequential_rra_scenario_1.xml

What this reads from MQSim's output XML:
  - Average_Response_Time_NS     → P50 latency
  - Max_Response_Time_NS         → P99.9 latency proxy
  - Total_Handled_Requests_Count → throughput
  - WAF                          → Write Amplification Factor
  - Erase counts per block       → wear variance (computed here)
  - Total_GC_Executions          → GC count

The RRA-FTL novel metrics (adaptive erase time, Weibull remaining budget)
are printed by MQSim via the stdout reporter added in the RRA GC unit.
Check the terminal output during simulation for lines starting with
  [RRA-FTL]
"""

import sys
import xml.etree.ElementTree as ET
import math


def parse_output(xml_path: str) -> dict:
    """Parse one MQSim output XML file into a flat dict of key metrics."""
    try:
        tree = ET.parse(xml_path)
    except FileNotFoundError:
        print(f"ERROR: file not found: {xml_path}")
        sys.exit(1)

    root = tree.getroot()
    results = {"file": xml_path}

    # ── Per-flow statistics ───────────────────────────────────────────────────
    flow_stats = []
    for flow in root.iter("IO_Flow_Statistics"):
        fs = {}
        for child in flow:
            try:
                fs[child.tag] = float(child.text) if child.text else 0.0
            except (ValueError, TypeError):
                fs[child.tag] = child.text
        flow_stats.append(fs)
    results["flows"] = flow_stats

    # ── Device-level statistics ───────────────────────────────────────────────
    device = root.find("Device_Level_Statistics")
    if device is not None:
        for child in device:
            try:
                results[child.tag] = float(child.text) if child.text else 0.0
            except (ValueError, TypeError):
                results[child.tag] = child.text

    # ── Erase count per block (for wear variance) ─────────────────────────────
    erase_counts = []
    for blk in root.iter("Block"):
        ec = blk.find("Erase_Count")
        if ec is not None and ec.text:
            try:
                erase_counts.append(int(ec.text))
            except ValueError:
                pass
    results["erase_counts"] = erase_counts

    # Compute wear variance from erase counts
    if erase_counts:
        mean = sum(erase_counts) / len(erase_counts)
        results["wear_variance"] = sum((x - mean) ** 2 for x in erase_counts) / len(erase_counts)
        results["max_erase_count"] = max(erase_counts)
        results["min_erase_count"] = min(erase_counts)
    else:
        results["wear_variance"]    = 0.0
        results["max_erase_count"]  = 0
        results["min_erase_count"]  = 0

    return results


def lifespan_projection(results: dict,
                        iops: float = 15.0,
                        block_size_kib: float = 64.0,
                        warranty_years: int = 5,
                        capacity_gb: float = 480.0) -> dict:
    """
    Firmware-native lifespan projection — same formula as metrics_engine.py.
    Converts IOPS → MB/s → GB/day → TBW → Effective TBW → Lifetime (years).
    """
    waf = results.get("WAF", results.get("Write_Amplification_Factor", 1.0))
    if not waf or waf <= 0:
        waf = 1.0

    mb_per_sec     = iops * block_size_kib / 1024.0
    gb_per_day     = mb_per_sec * 86_400 / 1_000.0
    dwpd           = gb_per_day / capacity_gb
    tbw_rated      = gb_per_day * 365 * warranty_years / 1_000.0
    effective_tbw  = tbw_rated / waf
    lifetime_years = (effective_tbw * 1_000.0) / (gb_per_day * 365.0)

    return {
        "mb_per_sec":     round(mb_per_sec, 4),
        "gb_per_day":     round(gb_per_day, 2),
        "dwpd":           round(dwpd, 4),
        "tbw_rated_tb":   round(tbw_rated, 3),
        "effective_tbw":  round(effective_tbw, 3),
        "lifetime_years": round(lifetime_years, 3),
        "waf_used":       round(waf, 4),
    }


def print_results(label: str, r: dict):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    # Flow-level latency stats
    for i, flow in enumerate(r.get("flows", [])):
        print(f"  Flow {i}: Avg Latency = {flow.get('Average_Response_Time_NS', 'N/A'):>14} ns"
              f"  |  Max = {flow.get('Max_Response_Time_NS', 'N/A'):>14} ns"
              f"  |  Requests = {flow.get('Total_Handled_Requests_Count', 'N/A')}")

    # Device-level
    for key in ["WAF", "Write_Amplification_Factor", "Total_GC_Executions",
                "Total_Flash_Reads_For_GC", "Total_Flash_Writes_For_GC"]:
        if key in r:
            print(f"  {key:<42}: {r[key]:>12.4f}")

    # Wear metrics (computed from erase count dump)
    print(f"  {'Wear Variance (computed)':<42}: {r['wear_variance']:>12.4f}")
    print(f"  {'Max Block Erase Count':<42}: {r['max_erase_count']:>12}")
    print(f"  {'Min Block Erase Count':<42}: {r['min_erase_count']:>12}")

    # Lifespan projection
    proj = lifespan_projection(r)
    print(f"\n  --- Lifespan Projection ---")
    print(f"  {'WAF used':<42}: {proj['waf_used']:>12.4f}")
    print(f"  {'Effective TBW (TB)':<42}: {proj['effective_tbw']:>12.3f}")
    print(f"  {'Lifetime (years)':<42}: {proj['lifetime_years']:>12.3f}")


def compare(label_a: str, r_a: dict, label_b: str, r_b: dict):
    print(f"\n{'='*60}")
    print(f"  COMPARISON: {label_a}  vs  {label_b}")
    print(f"{'='*60}")

    proj_a = lifespan_projection(r_a)
    proj_b = lifespan_projection(r_b)

    waf_a = r_a.get("WAF", r_a.get("Write_Amplification_Factor", 1.0))
    waf_b = r_b.get("WAF", r_b.get("Write_Amplification_Factor", 1.0))

    def row(metric, va, vb, fmt=".4f", lower_better=True):
        if va and vb and va != 0:
            delta = vb - va
            if lower_better:
                arrow = "▲ BETTER" if delta < 0 else ("▼ WORSE" if delta > 0 else "=")
            else:
                arrow = "▲ BETTER" if delta > 0 else ("▼ WORSE" if delta < 0 else "=")
            print(f"  {metric:<36} {va:>10{fmt}}  {vb:>10{fmt}}  {arrow}")
        else:
            print(f"  {metric:<36} {str(va):>10}  {str(vb):>10}")

    print(f"  {'Metric':<36} {label_a:>10}  {label_b:>10}  {'Result'}")
    print(f"  {'-'*60}")
    row("WAF",                    waf_a,                  waf_b,                  ".4f", lower_better=True)
    row("Wear Variance",          r_a["wear_variance"],   r_b["wear_variance"],   ".2f", lower_better=True)
    row("Lifetime (years)",       proj_a["lifetime_years"],proj_b["lifetime_years"],".3f", lower_better=False)
    row("Effective TBW (TB)",     proj_a["effective_tbw"],proj_b["effective_tbw"],".3f", lower_better=False)
    row("Max Erase Count",        r_a["max_erase_count"], r_b["max_erase_count"], ".0f", lower_better=True)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("\nUsage: python3 parse_mqsim_output.py <baseline.xml> <rra_output.xml>")
        sys.exit(1)

    baseline_xml = sys.argv[1]
    rra_xml      = sys.argv[2]

    r_base = parse_output(baseline_xml)
    r_rra  = parse_output(rra_xml)

    print_results("BASELINE FTL (GREEDY)",  r_base)
    print_results("RRA-FTL (Weibull + Pareto)", r_rra)
    compare("Baseline", r_base, "RRA-FTL", r_rra)


if __name__ == "__main__":
    main()
