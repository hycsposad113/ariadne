#!/usr/bin/env python3
"""E5 Render from Grids.

Reads a directory containing dumped CFD ratio grids (*.npz), buildings.geojson,
and site.geojson, and renders both Traditional Chinese and English figures:
- cfd_<wind>_wind_ratio.png and cfd_<wind>_wind_ratio-en.png
- cfd_4winds_summary.png and cfd_4winds_summary-en.png
- cfd_wind_risk_zones.png and cfd_wind_risk_zones-en.png
- cfd_lawson_comfort.png and cfd_lawson_comfort-en.png

Also compares computed summary numbers (max/mean ratio, high-wind and stagnant areas
per wind) against baseline results_table.json and flags any difference > 1% or > 0.01 ratio.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from shapely.geometry import shape, Polygon

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.e5_openfoam_harbour import (
    render_wind_field_map,
    render_4winds_summary_panel,
    render_risk_zones_map,
    render_lawson_comfort_map,
    get_site_outdoor_mask,
)


def load_grids_directory(
    grids_dir: Path,
) -> Tuple[
    Dict[str, np.ndarray],
    Dict[str, Dict[str, Any]],
    Tuple[float, float, float, float],
    List[Dict[str, Any]],
    Polygon,
]:
    """Load NPZ grids, buildings, and site geometry from grids_dir."""
    if not grids_dir.is_dir():
        raise FileNotFoundError(f"Grids directory not found: {grids_dir}")

    bldgs_path = grids_dir / "buildings.geojson"
    if not bldgs_path.is_file():
        raise FileNotFoundError(f"Buildings geojson not found: {bldgs_path}")

    site_path = grids_dir / "site.geojson"
    if not site_path.is_file():
        raise FileNotFoundError(f"Site geojson not found: {site_path}")

    with bldgs_path.open("r", encoding="utf-8") as f:
        bldgs_data = json.load(f)

    buildings: List[Dict[str, Any]] = []
    for feat in bldgs_data.get("features", []):
        buildings.append({
            "geometry": shape(feat["geometry"]),
            "height_m": feat.get("properties", {}).get("height_m"),
            "is_harbour": feat.get("properties", {}).get("is_harbour", False),
            "id": feat.get("properties", {}).get("id"),
        })

    with site_path.open("r", encoding="utf-8") as f:
        site_data = json.load(f)
    if site_data.get("type") == "Feature":
        site_geom = shape(site_data["geometry"])
    else:
        site_geom = shape(site_data)

    ratio_grids: Dict[str, np.ndarray] = {}
    wind_stats: Dict[str, Dict[str, Any]] = {}
    master_bounds: Optional[Tuple[float, float, float, float]] = None

    # Preferred order if present
    npz_files = sorted(grids_dir.glob("*.npz"))
    if not npz_files:
        raise FileNotFoundError(f"No .npz grid files found in {grids_dir}")

    for npz_path in npz_files:
        wname = npz_path.stem.upper()
        data = np.load(npz_path)
        r_grid = data["ratio_grid"]
        bounds_arr = data["bounds"]
        bounds = (float(bounds_arr[0]), float(bounds_arr[1]), float(bounds_arr[2]), float(bounds_arr[3]))
        if master_bounds is None:
            master_bounds = bounds

        ratio_grids[wname] = r_grid
        wind_stats[wname] = {
            "wind_direction_deg": float(data.get("wind_deg", 0.0)),
            "center_deg": float(data.get("wind_deg", 0.0)),
            "uref_10m": float(data.get("uref", 0.0)),
            "mean_speed_10m": float(data.get("uref", 0.0)),
            "frequency_pct": float(data.get("frequency_pct", 0.0)),
        }

    assert master_bounds is not None
    return ratio_grids, wind_stats, master_bounds, buildings, site_geom


def compute_wind_metrics(
    ratio_grid: np.ndarray,
    bounds: Tuple[float, float, float, float],
    buildings: Sequence[Dict[str, Any]],
    site_geom: Polygon,
    cell_area: float = 9.0,
) -> Dict[str, float]:
    """Compute pedestrian wind summary metrics for outdoor pedestrian space."""
    outdoor_mask = get_site_outdoor_mask(site_geom, buildings, bounds, ratio_grid.shape, buffer_dist=100.0)
    r_outdoor = ratio_grid[outdoor_mask]

    site_only_mask = get_site_outdoor_mask(site_geom, buildings, bounds, ratio_grid.shape, buffer_dist=0.0)
    r_site_only = ratio_grid[site_only_mask]

    if len(r_outdoor) > 0:
        max_ratio = float(np.max(r_outdoor))
        mean_ratio = float(np.mean(r_outdoor))
        median_ratio = float(np.median(r_outdoor))
        high_area = float(np.sum(r_outdoor > 1.2) * cell_area)
        stagnant_area = float(np.sum(r_outdoor < 0.3) * cell_area)
        comfortable_area = float(np.sum((r_outdoor >= 0.3) & (r_outdoor <= 1.2)) * cell_area)
        tot_outdoor_area = float(len(r_outdoor) * cell_area)
        high_pct = high_area / tot_outdoor_area * 100.0
        stagnant_pct = stagnant_area / tot_outdoor_area * 100.0
        comfortable_pct = comfortable_area / tot_outdoor_area * 100.0
    else:
        max_ratio = 0.0
        mean_ratio = 0.0
        median_ratio = 0.0
        high_area = 0.0
        stagnant_area = 0.0
        comfortable_area = 0.0
        tot_outdoor_area = 0.0
        high_pct = 0.0
        stagnant_pct = 0.0
        comfortable_pct = 0.0

    site_mean = float(np.mean(r_site_only)) if len(r_site_only) > 0 else mean_ratio
    site_median = float(np.median(r_site_only)) if len(r_site_only) > 0 else median_ratio

    return {
        "max_wind_ratio": round(max_ratio, 2),
        "mean_wind_ratio": round(mean_ratio, 2),
        "median_wind_ratio": round(median_ratio, 2),
        "site_only_mean_wind_ratio": round(site_mean, 2),
        "site_only_median_wind_ratio": round(site_median, 2),
        "high_wind_ratio_area_m2": round(high_area, 1),
        "high_wind_ratio_pct": round(high_pct, 1),
        "stagnant_wind_area_m2": round(stagnant_area, 1),
        "stagnant_wind_pct": round(stagnant_pct, 1),
        "comfortable_wind_area_m2": round(comfortable_area, 1),
        "comfortable_wind_pct": round(comfortable_pct, 1),
        "total_outdoor_pedestrian_area_m2": round(tot_outdoor_area, 1),
        "site_only_outdoor_area_m2": round(float(len(r_site_only) * cell_area), 1),
    }


def compare_summary_numbers(
    computed_cases: Dict[str, Dict[str, float]],
    baseline_table: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare computed summary numbers against baseline table.

    Flags any difference > 1% (relative) or > 0.01 for ratio metrics.
    """
    comparison: Dict[str, Any] = {
        "has_flags": False,
        "winds": {},
    }

    tracked_metrics = [
        ("max_wind_ratio", "ratio", 0.01),
        ("mean_wind_ratio", "ratio", 0.01),
        ("high_wind_ratio_area_m2", "area", 1.0),
        ("stagnant_wind_area_m2", "area", 1.0),
    ]

    for wname, computed in computed_cases.items():
        base = baseline_table.get(wname)
        wind_report: Dict[str, Any] = {
            "has_baseline": base is not None,
            "wind_has_flags": False,
            "metrics": {},
        }

        if base is None:
            comparison["winds"][wname] = wind_report
            continue

        for metric_name, mtype, ratio_tol in tracked_metrics:
            c_val = computed.get(metric_name, 0.0)
            b_val = float(base.get(metric_name, 0.0))
            diff_abs = abs(c_val - b_val)
            diff_pct = (diff_abs / b_val * 100.0) if b_val != 0.0 else (0.0 if diff_abs == 0.0 else 100.0)

            flagged = False
            if mtype == "ratio":
                if diff_abs > ratio_tol or (b_val != 0.0 and diff_pct > 1.0):
                    flagged = True
            elif mtype == "area":
                if (b_val != 0.0 and diff_pct > 1.0) or (b_val == 0.0 and diff_abs > 1.0):
                    flagged = True

            if flagged:
                wind_report["wind_has_flags"] = True
                comparison["has_flags"] = True

            wind_report["metrics"][metric_name] = {
                "computed": c_val,
                "baseline": b_val,
                "diff_abs": round(diff_abs, 4),
                "diff_pct": round(diff_pct, 2),
                "flagged": flagged,
            }

        comparison["winds"][wname] = wind_report

    return comparison


def format_comparison_markdown(
    comparison: Dict[str, Any],
    baseline_path: Path,
) -> str:
    """Format comparison result as a readable Markdown table."""
    lines: List[str] = [
        "# E5 Grid Rerun vs Baseline Comparison Report\n",
        f"- **Baseline File**: `{baseline_path}`",
        f"- **Status**: {'⚠️ Discrepancies Flagged (>1% or >0.01 ratio)' if comparison.get('has_flags') else '✅ All metrics match within tolerance (<= 1% and <= 0.01 ratio)'}\n",
        "| Wind | Metric | Computed | Baseline | Diff (Abs) | Diff (%) | Flagged |",
        "|:---:|:---|:---:|:---:|:---:|:---:|:---:|",
    ]

    for wname, wdata in comparison.get("winds", {}).items():
        if not wdata.get("has_baseline"):
            lines.append(f"| {wname} | (No baseline found) | - | - | - | - | ⚠️ Missing |")
            continue
        for mname, mdata in wdata.get("metrics", {}).items():
            flag_str = "⚠️ YES" if mdata["flagged"] else "OK"
            lines.append(
                f"| {wname} | `{mname}` | {mdata['computed']} | {mdata['baseline']} | "
                f"{mdata['diff_abs']} | {mdata['diff_pct']}% | {flag_str} |"
            )

    return "\n".join(lines) + "\n"


def render_all_figures(
    ratio_grids: Dict[str, np.ndarray],
    wind_stats: Dict[str, Dict[str, Any]],
    master_bounds: Tuple[float, float, float, float],
    buildings: Sequence[Dict[str, Any]],
    site_geom: Polygon,
    output_dir: Path,
) -> List[str]:
    """Render all Chinese and English figure files into output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: List[str] = []

    # 1. Individual wind field maps
    for wname, r_grid in ratio_grids.items():
        wstat = wind_stats[wname]
        wdeg = float(wstat.get("wind_direction_deg", 0.0))
        uref = float(wstat.get("uref_10m", 0.0))
        freq = float(wstat.get("frequency_pct", 0.0))

        # Chinese
        zh_path = output_dir / f"cfd_{wname.lower()}_wind_ratio.png"
        render_wind_field_map(
            ratio_grid=r_grid,
            bounds=master_bounds,
            buildings=buildings,
            site_geom=site_geom,
            wind_name=wname,
            wind_deg=wdeg,
            uref=uref,
            freq_pct=freq,
            output_png=str(zh_path),
            language="zh-TW",
        )
        generated.append(str(zh_path))

        # English
        en_path = output_dir / f"cfd_{wname.lower()}_wind_ratio-en.png"
        render_wind_field_map(
            ratio_grid=r_grid,
            bounds=master_bounds,
            buildings=buildings,
            site_geom=site_geom,
            wind_name=wname,
            wind_deg=wdeg,
            uref=uref,
            freq_pct=freq,
            output_png=str(en_path),
            language="en",
        )
        generated.append(str(en_path))

    # 2. Composite maps if > 1 wind
    if len(ratio_grids) > 1:
        # 4-winds summary panel
        zh_4w = output_dir / "cfd_4winds_summary.png"
        render_4winds_summary_panel(
            ratio_grids=ratio_grids,
            wind_stats=wind_stats,
            bounds=master_bounds,
            buildings=buildings,
            site_geom=site_geom,
            output_png=str(zh_4w),
            language="zh-TW",
        )
        generated.append(str(zh_4w))

        en_4w = output_dir / "cfd_4winds_summary-en.png"
        render_4winds_summary_panel(
            ratio_grids=ratio_grids,
            wind_stats=wind_stats,
            bounds=master_bounds,
            buildings=buildings,
            site_geom=site_geom,
            output_png=str(en_4w),
            language="en",
        )
        generated.append(str(en_4w))

        # Wind risk zones
        zh_risk = output_dir / "cfd_wind_risk_zones.png"
        render_risk_zones_map(
            ratio_grids=ratio_grids,
            bounds=master_bounds,
            buildings=buildings,
            site_geom=site_geom,
            output_png=str(zh_risk),
            language="zh-TW",
        )
        generated.append(str(zh_risk))

        en_risk = output_dir / "cfd_wind_risk_zones-en.png"
        render_risk_zones_map(
            ratio_grids=ratio_grids,
            bounds=master_bounds,
            buildings=buildings,
            site_geom=site_geom,
            output_png=str(en_risk),
            language="en",
        )
        generated.append(str(en_risk))

        # Lawson comfort map
        zh_lawson = output_dir / "cfd_lawson_comfort.png"
        render_lawson_comfort_map(
            ratio_grids=ratio_grids,
            wind_stats=wind_stats,
            bounds=master_bounds,
            buildings=buildings,
            site_geom=site_geom,
            output_png=str(zh_lawson),
            language="zh-TW",
        )
        generated.append(str(zh_lawson))

        en_lawson = output_dir / "cfd_lawson_comfort-en.png"
        render_lawson_comfort_map(
            ratio_grids=ratio_grids,
            wind_stats=wind_stats,
            bounds=master_bounds,
            buildings=buildings,
            site_geom=site_geom,
            output_png=str(en_lawson),
            language="en",
        )
        generated.append(str(en_lawson))

    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description="Render E5 figures from CFD ratio grids and compare with baseline.")
    parser.add_argument(
        "--grids-dir",
        type=Path,
        default=REPO_ROOT / "artifacts" / "w8" / "e5-cfd" / "grids",
        help="Directory containing dumped .npz grids and GeoJSON geometry.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save rendered figures. Default is parent of grids-dir.",
    )
    parser.add_argument(
        "--baseline-results",
        type=Path,
        default=REPO_ROOT / "artifacts" / "w8" / "e5-cfd" / "results_table.json",
        help="Path to baseline results_table.json to compare against.",
    )
    parser.add_argument(
        "--comparison-output",
        type=Path,
        default=None,
        help="Path to write JSON comparison. Default is <output-dir>/results_comparison.json.",
    )

    args = parser.parse_args()
    grids_dir = args.grids_dir.resolve()
    output_dir = args.output_dir.resolve() if args.output_dir else grids_dir.parent
    baseline_path = args.baseline_results.resolve()

    print(f"Loading grids from: {grids_dir}")
    print(f"Output directory:  {output_dir}")
    print(f"Baseline results:  {baseline_path}")

    ratio_grids, wind_stats, master_bounds, buildings, site_geom = load_grids_directory(grids_dir)
    print(f"Loaded {len(ratio_grids)} wind grids: {list(ratio_grids.keys())}")
    print(f"Loaded {len(buildings)} buildings. Master bounds: {master_bounds}")

    # 1. Compute summary numbers for each wind
    computed_cases: Dict[str, Dict[str, float]] = {}
    for wname, r_grid in ratio_grids.items():
        metrics = compute_wind_metrics(r_grid, master_bounds, buildings, site_geom)
        computed_cases[wname] = metrics

    # 2. Compare against baseline if available
    comparison: Optional[Dict[str, Any]] = None
    if baseline_path.is_file():
        with baseline_path.open("r", encoding="utf-8") as f:
            baseline_table = json.load(f)
        comparison = compare_summary_numbers(computed_cases, baseline_table)

        comp_json_path = args.comparison_output or (output_dir / "results_comparison.json")
        comp_md_path = comp_json_path.with_suffix(".md")

        with comp_json_path.open("w", encoding="utf-8") as f:
            json.dump(comparison, f, indent=2)

        md_content = format_comparison_markdown(comparison, baseline_path)
        with comp_md_path.open("w", encoding="utf-8") as f:
            f.write(md_content)

        print("\n" + md_content)
        if comparison.get("has_flags"):
            print("⚠️ [WARNING] Some metrics differ from baseline by > 1% or > 0.01 ratio.")
        else:
            print("✅ All summary numbers match baseline within 1% / 0.01 ratio.")
    else:
        print(f"Baseline results not found at {baseline_path}; skipping comparison.")

    # 3. Render all figures (Chinese and English)
    print(f"\nRendering figures into: {output_dir}")
    generated = render_all_figures(
        ratio_grids=ratio_grids,
        wind_stats=wind_stats,
        master_bounds=master_bounds,
        buildings=buildings,
        site_geom=site_geom,
        output_dir=output_dir,
    )
    for g in generated:
        print(f"  - Rendered: {Path(g).name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
