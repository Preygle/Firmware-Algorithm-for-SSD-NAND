"""
parse_mqsim_output.py
======================
Parses MQSim XML output files and prints/compares metrics for
Baseline, Modern, and RRA-FTL simulations.

Usage (2-way):
  python3 parse_mqsim_output.py <baseline.xml> <rra.xml>

Usage (3-way):
  python3 parse_mqsim_output.py <baseline.xml> <modern.xml> <rra.xml>
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

    # Per-flow statistics
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

    # Device-level statistics
    device = root.find("Device_Level_Statistics")
    if device is not None:
        for child in device:
            try:
                results[child.tag] = float(child.text) if child.text else 0.0
            except (ValueError, TypeError):
                results[child.tag] = child.text

    # Also scrape attributes on FTL element (some MQSim versions store stats as XML attributes)
    for ftl in root.iter():
        if "FTL" in ftl.tag or "Flash" in ftl.tag:
            for attr, val in ftl.attrib.items():
                try:
                    results[attr] = float(val)
                except (ValueError, TypeError):
                    pass

    # Erase count per block (for wear variance)
    erase_counts = []
    for blk in root.iter("Block"):
        ec = blk.find("Erase_Count")
        if ec is not None and ec.text:
            try:
                erase_counts.append(int(ec.text))
            except ValueError:
                pass
    results["erase_counts"] = erase_counts

    if erase_counts:
        mean = sum(erase_counts) / len(erase_counts)
        results["wear_variance"]   = sum((x - mean) ** 2 for x in erase_counts) / len(erase_counts)
        results["max_erase_count"] = max(erase_counts)
        results["min_erase_count"] = min(erase_counts)
    else:
        results["wear_variance"]   = 0.0
        results["max_erase_count"] = 0
        results["min_erase_count"] = 0

    return results


def lifespan_projection(results: dict,
                        iops: float = 15.0,
                        block_size_kib: float = 64.0,
                        warranty_years: int = 5,
                        capacity_gb: float = 480.0) -> dict:
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
    print(f"\n{'='*62}")
    print(f"  {label}")
    print(f"{'='*62}")

    for i, flow in enumerate(r.get("flows", [])):
        print(f"  Flow {i}: Avg Latency = {flow.get('Average_Response_Time_NS', 'N/A'):>14} ns"
              f"  |  Requests = {int(flow.get('Total_Handled_Requests_Count', 0)):,}")

    for key in ["WAF", "Write_Amplification_Factor", "Total_GC_Executions",
                "Issued_Flash_Erase_CMD", "Total_Flash_Reads_For_GC", "Total_Flash_Writes_For_GC"]:
        if key in r and r[key] != 0:
            print(f"  {key:<42}: {r[key]:>12.4f}")

    print(f"  {'Wear Variance (computed)':<42}: {r['wear_variance']:>12.4f}")
    print(f"  {'Max Block Erase Count':<42}: {r['max_erase_count']:>12}")
    print(f"  {'Min Block Erase Count':<42}: {r['min_erase_count']:>12}")

    proj = lifespan_projection(r)
    print(f"\n  --- Lifespan Projection ---")
    print(f"  {'WAF used':<42}: {proj['waf_used']:>12.4f}")
    print(f"  {'Effective TBW (TB)':<42}: {proj['effective_tbw']:>12.3f}")
    print(f"  {'Lifetime (years)':<42}: {proj['lifetime_years']:>12.3f}")


def compare_all(labels: list, results: list):
    """Print a combined N-way side-by-side comparison table."""
    n = len(results)
    projs = [lifespan_projection(r) for r in results]
    wafs  = [r.get("WAF", r.get("Write_Amplification_Factor", 1.0)) or 1.0 for r in results]

    col_w = 13
    sep = "=" * (40 + n * (col_w + 2))
    print(f"\n{sep}")
    print(f"  FULL {n}-WAY COMPARISON")
    print(sep)

    hdr = f"  {'Metric':<38}" + "".join(f"{l:>{col_w}}" for l in labels)
    print(hdr)
    print(f"  {'-'*(36 + n*(col_w+2))}")

    def best_idx(values, lower_better):
        valid = [(i, v) for i, v in enumerate(values) if v is not None and v != 0]
        if not valid:
            return -1
        return (min if lower_better else max)(valid, key=lambda x: x[1])[0]

    def row(metric, values, fmt, lower_better=True):
        best = best_idx(values, lower_better)
        cols = ""
        for i, v in enumerate(values):
            if isinstance(v, float):
                cell = f"{v:>{col_w}{fmt}}"
            else:
                cell = f"{str(v):>{col_w}}"
            if i == best and best != -1:
                cell = cell.rstrip() + "★"
            cols += cell
        print(f"  {metric:<38}{cols}")

    row("WAF (lower=better)",        wafs,                                              ".4f", lower_better=True)
    row("Wear Variance (lower=best)",[r["wear_variance"]    for r in results],          ".2f", lower_better=True)
    row("Max Erase Count (lower=best)",[r["max_erase_count"] for r in results],         ".0f", lower_better=True)
    row("Lifetime yrs (higher=best)", [p["lifetime_years"]  for p in projs],            ".3f", lower_better=False)
    row("Effective TBW TB (higher=best)",[p["effective_tbw"] for p in projs],           ".3f", lower_better=False)

    avg_lats = []
    for r in results:
        flows = r.get("flows", [])
        avg_lats.append(flows[0].get("Average_Response_Time_NS", 0.0) if flows else 0.0)
    row("Avg Latency ns (lower=best)", avg_lats,                                        ".0f", lower_better=True)

    gc_counts = [r.get("Total_GC_Executions", r.get("Issued_Flash_Erase_CMD", 0.0)) for r in results]
    row("GC Executions (higher=best)", gc_counts,                                        ".0f", lower_better=False)

    print(f"\n  ★ = best in category")
    print(sep)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("\nUsage: python3 parse_mqsim_output.py <baseline.xml> <modern.xml> [<rra.xml>]")
        sys.exit(1)

    if len(sys.argv) == 3:
        files  = [sys.argv[1], sys.argv[2]]
        labels = ["Baseline", "RRA-FTL"]
        p_labels = ["BASELINE FTL (GREEDY)", "RRA-FTL (Weibull + Pareto)"]
    else:
        files  = [sys.argv[1], sys.argv[2], sys.argv[3]]
        labels = ["Baseline", "Modern", "RRA-FTL"]
        p_labels = ["BASELINE FTL (GREEDY)", "MODERN FTL (Lifespan-Aware)", "RRA-FTL (Weibull+Pareto)"]

    results = [parse_output(f) for f in files]

    for label, r in zip(p_labels, results):
        print_results(label, r)

    compare_all(labels, results)


if __name__ == "__main__":
    main()
