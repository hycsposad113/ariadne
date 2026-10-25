#!/usr/bin/env python3
"""Build spatial problem definition artifacts and map figures for Rotterdam M4H.

Reproducibility (macOS, from repository root):
  MPLCONFIGDIR=/private/tmp/w6-problem-definition-mplconfig \
  PROJ_LIB=/Applications/QGIS-LTR.app/Contents/Resources/proj \
  PYTHONPATH=src:scripts PYTHONDONTWRITEBYTECODE=1 \
  /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 \
  scripts/build_problem_definition.py

If matplotlib is unavailable in the active interpreter, figures are skipped while
all JSON and GeoJSON outputs are deterministically generated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
from pathlib import Path
from typing import Any, Sequence

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union
import shapely

from urban_design.problem_definition import (
    ProblemDefinitionBundle,
    export_problem_definition_artifacts,
    run_problem_definition_analysis,
)

ROOT = Path(__file__).resolve().parents[1]
MAIN_PROJECT_ROOT = Path("/Users/jackhsieh/Downloads/TUD/Q5/project")
URBAN_DATA_ROOT = Path(os.path.expanduser("~/.local/share/urban-design-data"))
CONTEXT_ROOT = URBAN_DATA_ROOT / "context"
SYNTAX_RUN_ROOT = URBAN_DATA_ROOT / "week5-syntax-modes/syntax/run-week5-modes-01"


def find_path(paths: Sequence[Path]) -> Path:
    for p in paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"None found: {paths}")


def load_study_area() -> tuple[Polygon | MultiPolygon, str]:
    candidates = [
        ROOT / "artifacts/week4-repair-r02/syntax/study-area.geojson",
        MAIN_PROJECT_ROOT / "artifacts/week4-repair-r02/syntax/study-area.geojson",
        CONTEXT_ROOT / "context-20260927T153054Z/study-area-v5.geojson",
    ]
    path = find_path(candidates)
    doc = json.loads(path.read_text(encoding="utf-8"))
    geom_raw = doc.get("geometry") if "geometry" in doc else doc["features"][0]["geometry"]
    geom = shape(geom_raw)
    sa_id = doc.get("id", "study-area-rotterdam-m4h-pilot-project-v5")
    return geom, sa_id


def load_normalized_inputs() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    roots = [
        ROOT / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized",
        MAIN_PROJECT_ROOT / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized",
    ]
    norm_dir = find_path(roots)

    # BAG pands
    bag_features: list[dict[str, Any]] = []
    for p in sorted(norm_dir.glob("pdok-bag-pand-*.geojson")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        bag_features.extend(doc.get("features", []))

    # BGT water
    water_doc = json.loads((norm_dir / "pdok-bgt-waterdeel-p001-epsg28992.geojson").read_text(encoding="utf-8"))
    water_features = water_doc.get("features", [])

    # OSM
    osm_doc = json.loads((norm_dir / "osm-overpass-v5-epsg28992.geojson").read_text(encoding="utf-8"))
    osm_features = osm_doc.get("features", [])

    return bag_features, water_features, osm_features


def load_context_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = json.loads((CONTEXT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    run_dir = CONTEXT_ROOT / manifest["run_directory"]

    green_doc = json.loads((run_dir / "green.geojson").read_text(encoding="utf-8"))
    green_features = green_doc.get("features", [])

    bag_ctx: list[dict[str, Any]] = []
    return green_features, bag_ctx


def load_syntax_layer0() -> dict[str, Any] | None:
    path = SYNTAX_RUN_ROOT / "syntax_six_layer_candidate.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    layers = doc.get("layers", [])
    return layers[0] if layers else None


def _display_input_path(path: Path) -> str:
    """Return a portable, credential-free input path for artifact provenance."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        try:
            return "~/.local/share/urban-design-data/" + resolved.relative_to(URBAN_DATA_ROOT.resolve()).as_posix()
        except ValueError:
            return f"external-input/{path.name}"


def build_source_inventory() -> dict[str, Any]:
    """Hash the exact local inputs consumed by the analysis without copying source requests."""
    study_area_path = find_path([
        ROOT / "artifacts/week4-repair-r02/syntax/study-area.geojson",
        MAIN_PROJECT_ROOT / "artifacts/week4-repair-r02/syntax/study-area.geojson",
        CONTEXT_ROOT / "context-20260927T153054Z/study-area-v5.geojson",
    ])
    norm_dir = find_path([
        ROOT / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized",
        MAIN_PROJECT_ROOT / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized",
    ])
    context_manifest_path = CONTEXT_ROOT / "manifest.json"
    context_manifest = json.loads(context_manifest_path.read_text(encoding="utf-8"))
    context_run_dir = CONTEXT_ROOT / context_manifest["run_directory"]
    green_path = context_run_dir / "green.geojson"
    syntax_path = SYNTAX_RUN_ROOT / "syntax_six_layer_candidate.json"
    syntax_doc = json.loads(syntax_path.read_text(encoding="utf-8")) if syntax_path.exists() else {}
    syntax_layers = syntax_doc.get("layers", [])
    syntax_layer0 = syntax_layers[0] if syntax_layers else {}
    integrity_manifest_path = norm_dir.parents[1] / "source-and-integrity-manifest.json"

    selected_paths = [study_area_path]
    selected_paths.extend(sorted(norm_dir.glob("pdok-bag-pand-*.geojson")))
    selected_paths.extend([
        norm_dir / "pdok-bgt-waterdeel-p001-epsg28992.geojson",
        norm_dir / "osm-overpass-v5-epsg28992.geojson",
        integrity_manifest_path,
        context_manifest_path,
        green_path,
        syntax_path,
    ])
    roles: dict[Path, str] = {study_area_path: "study_area"}
    roles.update({path: "pdok_bag_buildings" for path in sorted(norm_dir.glob("pdok-bag-pand-*.geojson"))})
    roles.update({
        norm_dir / "pdok-bgt-waterdeel-p001-epsg28992.geojson": "pdok_bgt_water",
        norm_dir / "osm-overpass-v5-epsg28992.geojson": "osm_roads",
        integrity_manifest_path: "normalized_source_integrity_manifest",
        context_manifest_path: "osm_context_manifest",
        green_path: "osm_green_polygons",
        syntax_path: "pst_candidate_layer_source",
    })

    input_records = []
    for path in selected_paths:
        data = path.read_bytes()
        input_records.append({
            "role": roles[path],
            "path": _display_input_path(path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })

    integrity_manifest = json.loads(integrity_manifest_path.read_text(encoding="utf-8"))
    snapshots = integrity_manifest.get("snapshots", [])
    snapshot_versions = sorted({str(row["version"]) for row in snapshots if row.get("version")})
    snapshot_times = sorted({str(row["retrieved_at"]) for row in snapshots if row.get("retrieved_at")})
    snapshot_licenses = sorted({str(row["license"]) for row in snapshots if row.get("license")})
    snapshot_publishers = sorted({str(row["publisher"]) for row in snapshots if row.get("publisher")})
    return {
        "crs": "EPSG:28992",
        "methodology": "deterministic_spatial_indicators_s2_review_v2",
        "tool_versions": {
            "python": platform.python_version(),
            "shapely": shapely.__version__,
        },
        "inputs": input_records,
        "source_metadata": {
            "pdok_bag_bgt_osm_integrity_manifest": {
                "status": integrity_manifest.get("status"),
                "schema_version": integrity_manifest.get("schema_version"),
                "snapshot_count": len(snapshots),
                "normalized_artifact_count": len(integrity_manifest.get("normalized_artifacts", [])),
                "publishers": snapshot_publishers,
                "licenses": snapshot_licenses,
                "source_version_range_utc": [snapshot_versions[0], snapshot_versions[-1]] if snapshot_versions else None,
                "retrieval_time_range_utc": [snapshot_times[0], snapshot_times[-1]] if snapshot_times else None,
                "query_scopes": [
                    "Normalized PDOK/Kadaster BAG building features in the StudyArea and 0-800m exterior comparison ring",
                    "Normalized PDOK/Kadaster BGT waterdeel geometries intersecting the StudyArea",
                    "Normalized OSM road ways clipped to the StudyArea land geometry by the deterministic analysis",
                ],
            },
            "osm_green": {
                "source": context_manifest.get("source"),
                "source_data_version": context_manifest.get("source_data_version"),
                "retrieved_at": context_manifest.get("retrieved_at"),
                "license": context_manifest.get("license"),
                "attribution": context_manifest.get("attribution"),
                "crs": context_manifest.get("crs"),
            },
            "pst_candidate": {
                "source": "local syntax_six_layer_candidate.json; StudyArea segments only",
                "path": _display_input_path(syntax_path),
                "query_scope": "Use source layer 0 segment_values; no surrounding comparator values are present",
                "data_readiness": syntax_layer0.get("data_readiness"),
            },
        },
    }


# ---------------------------------------------------------------------------
# Cartographic Rendering (Matplotlib)
# ---------------------------------------------------------------------------

def add_cartographic_elements(
    ax: Any,
    xlim: tuple[float, float],
    ylim: tuple[float, float],
    scale_len_m: float = 200.0,
    source_text: str = "CRS: EPSG:28992 | Sources: PDOK BAG/BGT, OSM, PST 3.3.1 | Platform: Rotterdam M4H",
) -> None:
    minx, maxx = xlim
    miny, maxy = ylim

    ax.grid(True, linestyle=":", alpha=0.4, color="#94a3b8")
    ax.set_xlabel("RD Easting (m) [EPSG:28992]", fontsize=8, color="#334155")
    ax.set_ylabel("RD Northing (m) [EPSG:28992]", fontsize=8, color="#334155")
    ax.tick_params(axis="both", labelsize=7.5, colors="#475569")

    # North arrow in top-right
    na_x = maxx - (maxx - minx) * 0.05
    na_y = maxy - (maxy - miny) * 0.05
    arr_len = (maxy - miny) * 0.06
    ax.annotate(
        "N",
        xy=(na_x, na_y),
        xytext=(na_x, na_y - arr_len),
        arrowprops=dict(facecolor="#0f172a", edgecolor="#0f172a", width=1.5, headwidth=6, headlength=7),
        ha="center",
        va="bottom",
        fontsize=9,
        fontweight="bold",
        color="#0f172a",
        zorder=100,
    )

    # Scale bar in bottom-left
    sb_x = minx + (maxx - minx) * 0.05
    sb_y = miny + (maxy - miny) * 0.05
    tick_h = (maxy - miny) * 0.012

    ax.plot([sb_x, sb_x + scale_len_m], [sb_y, sb_y], color="#0f172a", linewidth=2.5, zorder=100)
    ax.plot([sb_x, sb_x], [sb_y - tick_h, sb_y + tick_h], color="#0f172a", linewidth=1.5, zorder=100)
    ax.plot([sb_x + scale_len_m, sb_x + scale_len_m], [sb_y - tick_h, sb_y + tick_h], color="#0f172a", linewidth=1.5, zorder=100)
    ax.plot([sb_x + scale_len_m / 2, sb_x + scale_len_m / 2], [sb_y - tick_h * 0.6, sb_y + tick_h * 0.6], color="#0f172a", linewidth=1.0, zorder=100)

    label_text = f"{int(scale_len_m)} m" if scale_len_m < 1000 else f"{scale_len_m / 1000:.1f} km"
    ax.text(sb_x + scale_len_m / 2, sb_y + tick_h * 1.5, label_text, ha="center", va="bottom", fontsize=8, fontweight="bold", color="#0f172a", zorder=100)

    # Source text
    ax.text(0.01, -0.07, source_text, transform=ax.transAxes, fontsize=7.5, color="#64748b", ha="left", va="top")


def plot_polygon_mpl(geom: Polygon | MultiPolygon, facecolor: str, edgecolor: str, linewidth: float = 1.0, alpha: float = 1.0) -> list[Any]:
    from matplotlib.path import Path as MplPath
    from matplotlib.patches import PathPatch

    def ring_parts(ring: Any) -> tuple[list[tuple[float, float]], list[int]]:
        coords = list(ring.coords)
        codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(coords) - 2) + [MplPath.CLOSEPOLY]
        return coords, codes

    patches = []
    polys = [geom] if isinstance(geom, Polygon) else (list(geom.geoms) if isinstance(geom, MultiPolygon) else [])
    for p in polys:
        vertices, codes = ring_parts(p.exterior)
        for interior in p.interiors:
            inner_vertices, inner_codes = ring_parts(interior)
            vertices.extend(inner_vertices)
            codes.extend(inner_codes)
        patch = PathPatch(
            MplPath(vertices, codes), facecolor=facecolor, edgecolor=edgecolor,
            linewidth=linewidth, alpha=alpha, zorder=10,
        )
        patches.append(patch)
    return patches


def metric_text(problem: Any, key: str, digits: int = 2) -> str:
    value = problem.metrics.get(key)
    if value is None:
        return "未提供"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def metric_comparison_text(problem: Any, key: str, digits: int = 2) -> str:
    item = next((m for m in problem.statement.metrics if m.key == key), None)
    value = item.comparison_value if item else None
    if value is None:
        return "無可比值"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def render_all_problem_figures(bundle: ProblemDefinitionBundle, figures_dir: Path) -> list[Path]:
    """Render 6 cartographic figures for the defined spatial problems."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
    except ImportError:
        print("[WARN] matplotlib is not installed in the active environment. Skipping map rendering.", file=sys.stderr)
        return []

    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang TC", "Heiti TC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    figures_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []

    sa_geom, _ = load_study_area()
    minx, miny, maxx, maxy = sa_geom.bounds
    pad_x = (maxx - minx) * 0.08
    pad_y = (maxy - miny) * 0.08
    xlim = (minx - pad_x, maxx + pad_x)
    ylim = (miny - pad_y, maxy + pad_y)

    _, water_features, _ = load_normalized_inputs()
    water_union = unary_union([shape(f["geometry"]) for f in water_features if shape(f["geometry"]).intersects(sa_geom)])

    # -----------------------------------------------------------------------
    # Fig 01: Functional Monoculture
    # -----------------------------------------------------------------------
    p1 = bundle.problems[0]
    fig = plt.figure(figsize=(11, 8.5), dpi=150)
    ax = fig.add_axes([0.08, 0.12, 0.65, 0.78])
    lax = fig.add_axes([0.75, 0.15, 0.22, 0.72])
    lax.axis("off")

    # Base study area & water
    for p in plot_polygon_mpl(sa_geom, facecolor="#f8fafc", edgecolor="#475569", linewidth=1.5, alpha=0.9):
        ax.add_patch(p)
    if not water_union.is_empty:
        for p in plot_polygon_mpl(water_union, facecolor="#bae6fd", edgecolor="#0284c7", linewidth=1.0, alpha=0.8):
            ax.add_patch(p)

    color_map = {
        "industrial": "#dc2626",
        "office": "#2563eb",
        "amenity": "#16a34a",
        "retail": "#d97706",
        "demolished": "#94a3b8",
        "UNKNOWN": "#cbd5e1",
    }
    for feat in p1.geojson_layer["features"]:
        cat = feat["properties"]["functional_category"]
        c = color_map.get(cat, "#94a3b8")
        g = shape(feat["geometry"])
        for p in plot_polygon_mpl(g, facecolor=c, edgecolor="#1e293b", linewidth=0.8, alpha=0.88):
            ax.add_patch(p)

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_title("Rotterdam M4H: Problem 1 - BAG Use Labels & Status\n(問題一：BAG 建築用途標籤與登記狀態)", fontsize=11, fontweight="bold", pad=12)
    add_cartographic_elements(ax, xlim, ylim, scale_len_m=200.0)

    # Legend & text
    patches = [
        Patch(facecolor="#dc2626", edgecolor="#1e293b", label="Industrial function label"),
        Patch(facecolor="#2563eb", edgecolor="#1e293b", label="Office function label"),
        Patch(facecolor="#16a34a", edgecolor="#1e293b", label="Amenity function label"),
        Patch(facecolor="#d97706", edgecolor="#1e293b", label="Retail function label"),
        Patch(facecolor="#94a3b8", edgecolor="#1e293b", label="BAG status: Pand gesloopt"),
        Patch(facecolor="#cbd5e1", edgecolor="#1e293b", label="Usage label missing"),
        Patch(facecolor="#bae6fd", edgecolor="#0284c7", label="Water Basin (港池水體)"),
    ]
    lax.legend(handles=patches, loc="upper left", title="Functional Categories\n(BAG 登記用途分類)", fontsize=8, title_fontsize=8.5)
    lax.text(
        0.02, 0.40,
        f"【BAG 登記指標】\n"
        f"• 住宅用途標籤：{metric_text(p1, 'residential_share_site')}% (外環：{metric_comparison_text(p1, 'residential_share_site')}%)\n"
        f"• 工業用途標籤：{metric_text(p1, 'industrial_share_site')}% (外環：{metric_comparison_text(p1, 'industrial_share_site')}%)\n"
        f"• 用途缺漏：{metric_text(p1, 'unknown_usage_building_count', 0)} 個；Pand gesloopt：{metric_text(p1, 'demolished_building_count', 0)} 個\n"
        f"• 上述條件聯集：{metric_text(p1, 'unknown_or_demolished_building_count', 0)} 個；Shannon：{metric_text(p1, 'shannon_entropy_site', 4)}\n"
        f"• S2 審查級別：{p1.statement.severity_code}\n\n"
        "【對應形態字典建議】\n"
        "• block_hybrid (混合街廓)\n"
        "• building_courtyard_open_corner\n"
        "• building_podium_tower\n"
        "• space_plaza",
        transform=lax.transAxes,
        fontsize=7.8,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#f1f5f9", edgecolor="#cbd5e1"),
    )
    f1_path = figures_dir / "fig01_problem_functional_monoculture.png"
    fig.savefig(f1_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    rendered.append(f1_path)

    # -----------------------------------------------------------------------
    # Fig 02: Spatial Fragmentation & Low Permeability
    # -----------------------------------------------------------------------
    p2 = bundle.problems[1]
    fig = plt.figure(figsize=(11, 8.5), dpi=150)
    ax = fig.add_axes([0.08, 0.12, 0.65, 0.78])
    lax = fig.add_axes([0.75, 0.15, 0.22, 0.72])
    lax.axis("off")

    for p in plot_polygon_mpl(sa_geom, facecolor="#f8fafc", edgecolor="#475569", linewidth=1.5, alpha=0.9):
        ax.add_patch(p)
    if not water_union.is_empty:
        for p in plot_polygon_mpl(water_union, facecolor="#bae6fd", edgecolor="#0284c7", linewidth=1.0, alpha=0.8):
            ax.add_patch(p)

    # OSM vertex-degree proxy points, long BAG footprints, and polygonized road blocks.
    for feat in p2.geojson_layer["features"]:
        ft = feat["properties"].get("feature_type")
        g = shape(feat["geometry"])
        if ft == "polygonized_road_area_over_1ha":
            for p in plot_polygon_mpl(g, facecolor="#fee2e2", edgecolor="#ef4444", linewidth=1.2, alpha=0.45):
                ax.add_patch(p)
        elif ft == "long_building_footprint_axis":
            for p in plot_polygon_mpl(g, facecolor="#b45309", edgecolor="#78350f", linewidth=1.4, alpha=0.65):
                ax.add_patch(p)
        elif ft == "osm_line_degree_one_vertex":
            ax.scatter([g.x], [g.y], color="#dc2626", s=18, marker="x", zorder=30)

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_title("Rotterdam M4H: Problem 2 - OSM Vertex Proxies & Polygonized Blocks\n(問題二：OSM 座標頂點代理值與道路線多邊形化街廓)", fontsize=11, fontweight="bold", pad=12)
    add_cartographic_elements(ax, xlim, ylim, scale_len_m=200.0)

    patches = [
        Patch(facecolor="#b45309", edgecolor="#78350f", label="BAG footprints with long axis ≥80m"),
        Patch(facecolor="#fee2e2", edgecolor="#ef4444", label="Polygonized road block >1ha"),
        Line2D([0], [0], marker="x", color="#dc2626", label=f"Degree-one OSM vertices ({metric_text(p2, 'road_degree_one_vertex_count', 0)})", markersize=7, linestyle="None"),
        Patch(facecolor="#bae6fd", edgecolor="#0284c7", label="Water Basin (港池水體)"),
    ]
    lax.legend(handles=patches, loc="upper left", title="Mapped OSM / BAG Geometry", fontsize=8, title_fontsize=8.5)
    lax.text(
        0.02, 0.40,
        f"【幾何代理指標】\n"
        f"• 度數≥3 的 OSM 頂點密度：{metric_text(p2, 'road_degree_ge3_vertex_density')} nodes/ha；頂點數 {metric_text(p2, 'road_degree_ge3_node_count', 0)}\n"
        f"• 度數=1 的 OSM 頂點：{metric_text(p2, 'road_degree_one_vertex_count', 0)} (不等同死巷)\n"
        f"• 路徑繞行比均值／最大值（n={metric_text(p2, 'walking_detour_sample_pair_count', 0)}）：{metric_text(p2, 'walking_detour_ratio')} / {metric_text(p2, 'max_walking_detour_ratio')}\n"
        f"• 最大 BAG footprint 長軸：{metric_text(p2, 'max_building_footprint_long_axis_m')} m (不代表阻隔)\n"
        f"• highway=service：{metric_text(p2, 'highway_service_line_length_m')} / {metric_text(p2, 'total_osm_road_line_length_m')} m ({metric_text(p2, 'service_road_ratio')}%)\n"
        f"• 所選步行／騎行標籤線長佔比：{metric_text(p2, 'selected_path_network_line_length_m')} m ({metric_comparison_text(p2, 'service_road_ratio')}%)\n"
        f"• S2 審查級別：{p2.statement.severity_code}\n\n"
        "【對應形態字典建議】\n"
        "• block_open (開放街廓)\n"
        "• space_covered_public_passage\n"
        "• space_shared_street\n"
        "• block_rowhouse_strip",
        transform=lax.transAxes,
        fontsize=7.8,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#f1f5f9", edgecolor="#cbd5e1"),
    )
    f2_path = figures_dir / "fig02_problem_spatial_fragmentation.png"
    fig.savefig(f2_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    rendered.append(f2_path)

    # -----------------------------------------------------------------------
    # Fig 03: Socio-Spatial Isolation
    # -----------------------------------------------------------------------
    p3 = bundle.problems[2]
    fig = plt.figure(figsize=(11, 8.5), dpi=150)
    ax = fig.add_axes([0.08, 0.12, 0.65, 0.78])
    lax = fig.add_axes([0.75, 0.15, 0.22, 0.72])
    lax.axis("off")

    for p in plot_polygon_mpl(sa_geom, facecolor="#f8fafc", edgecolor="#475569", linewidth=1.5, alpha=0.9):
        ax.add_patch(p)
    if not water_union.is_empty:
        for p in plot_polygon_mpl(water_union, facecolor="#bae6fd", edgecolor="#0284c7", linewidth=1.0, alpha=0.8):
            ax.add_patch(p)

    for feat in p3.geojson_layer["features"]:
        g = shape(feat["geometry"])
        props = feat["properties"]
        is_north = props.get("boundary_intersection_type") == "north_y_threshold_intersection"
        ax.scatter(
            [g.x], [g.y], color="#16a34a" if is_north else "#3b82f6",
            edgecolor="#0f172a", s=45 if is_north else 28,
            marker="o" if is_north else "s", zorder=30,
        )

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_title("Rotterdam M4H: Problem 3 - Boundary Intersections & Topology\n(問題三：邊界幾何交點與路網拓撲指標)", fontsize=11, fontweight="bold", pad=12)
    add_cartographic_elements(ax, xlim, ylim, scale_len_m=200.0)

    patches = [
        Line2D([0], [0], marker="o", color="#16a34a", markeredgecolor="#0f172a", label="North selector: y > 436000m"),
        Line2D([0], [0], marker="s", color="#3b82f6", markeredgecolor="#0f172a", label="Other boundary intersections"),
        Patch(facecolor="#bae6fd", edgecolor="#0284c7", label="Water Basin (港池水體)"),
    ]
    lax.legend(handles=patches, loc="upper left", title="OSM Line / StudyArea Intersections", fontsize=8, title_fontsize=8.5)
    lax.text(
        0.02, 0.40,
        f"【幾何與拓撲量測】\n"
        f"• y>436000m 選取區交點：{metric_text(p3, 'north_boundary_osm_intersections_count', 0)}；全邊界：{metric_text(p3, 'all_boundary_osm_intersections_count', 0)} (5m 聚類)\n"
        f"• PST 行人 800m NAIN 候選層均值：{metric_text(p3, 'syntax_pedestrian_800m_nain_mean', 4)}\n"
        f"• NAIN=0 的路段：{metric_text(p3, 'syntax_zero_nain_segment_count', 0)} / {metric_comparison_text(p3, 'syntax_zero_nain_segment_count', 0)}\n"
        "• 缺周邊 NAIN 比較值；不推論人流\n"
        f"• S2 審查級別：{p3.statement.severity_code}\n\n"
        "【對應形態字典建議】\n"
        "• space_linear_park (立體生態天橋)\n"
        "• building_terraced (消解堤防高差)\n"
        "• space_shared_street (門戶共享路網)",
        transform=lax.transAxes,
        fontsize=7.8,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#f1f5f9", edgecolor="#cbd5e1"),
    )
    f3_path = figures_dir / "fig03_problem_sociospatial_isolation.png"
    fig.savefig(f3_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    rendered.append(f3_path)

    # -----------------------------------------------------------------------
    # Fig 04: Ecological Disconnection
    # -----------------------------------------------------------------------
    p4 = bundle.problems[3]
    fig = plt.figure(figsize=(11, 8.5), dpi=150)
    ax = fig.add_axes([0.08, 0.12, 0.65, 0.78])
    lax = fig.add_axes([0.75, 0.15, 0.22, 0.72])
    lax.axis("off")

    for p in plot_polygon_mpl(sa_geom, facecolor="#f8fafc", edgecolor="#475569", linewidth=1.5, alpha=0.9):
        ax.add_patch(p)
    if not water_union.is_empty:
        for p in plot_polygon_mpl(water_union, facecolor="#bae6fd", edgecolor="#0284c7", linewidth=1.0, alpha=0.8):
            ax.add_patch(p)

    for feat in p4.geojson_layer["features"]:
        ft = feat["properties"].get("feature_type")
        g = shape(feat["geometry"])
        if ft == "osm_green_tag_polygon_piece":
            for p in plot_polygon_mpl(g, facecolor="#22c55e", edgecolor="#15803d", linewidth=1.0, alpha=0.8):
                ax.add_patch(p)

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_title("Rotterdam M4H: Problem 4 - OSM Green-Tagged Polygon Geometry\n(問題四：OSM 綠地標籤多邊形幾何)", fontsize=11, fontweight="bold", pad=12)
    add_cartographic_elements(ax, xlim, ylim, scale_len_m=200.0)

    patches = [
        Patch(facecolor="#22c55e", edgecolor="#15803d", label="OSM green-tag polygons (area >5m²)"),
        Patch(facecolor="#bae6fd", edgecolor="#0284c7", label="Water Basin (港池水體)"),
    ]
    lax.legend(handles=patches, loc="upper left", title="Mapped Green Geometry", fontsize=8, title_fontsize=8.5)
    lax.text(
        0.02, 0.40,
        f"【OSM 幾何量測】\n"
        f"• 綠地標籤多邊形聯集：{metric_text(p4, 'site_green_area_m2')} m² ({metric_text(p4, 'green_coverage_percentage')}%)\n"
        f"• 面積篩選後片段數：{metric_text(p4, 'site_green_polygon_count', 0)}；最近片段距離>40m：{metric_text(p4, 'green_polygon_nearest_gap_over_40m_count', 0)}\n"
        "• 不代表樹冠、地表材質、可進入性或生態連通\n"
        f"• S2 審查級別：{p4.statement.severity_code}\n\n"
        "【對應形態字典建議】\n"
        "• space_linear_park (貫穿性生態綠軸)\n"
        "• space_pocket_park (微型生物跳島)\n"
        "• block_towers_park (釋放地面層綠化)",
        transform=lax.transAxes,
        fontsize=7.8,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#f1f5f9", edgecolor="#cbd5e1"),
    )
    f4_path = figures_dir / "fig04_problem_ecological_disconnection.png"
    fig.savefig(f4_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    rendered.append(f4_path)

    # -----------------------------------------------------------------------
    # Fig 05: Waterfront Inaccessibility
    # -----------------------------------------------------------------------
    p5 = bundle.problems[4]
    fig = plt.figure(figsize=(11, 8.5), dpi=150)
    ax = fig.add_axes([0.08, 0.12, 0.65, 0.78])
    lax = fig.add_axes([0.75, 0.15, 0.22, 0.72])
    lax.axis("off")

    for p in plot_polygon_mpl(sa_geom, facecolor="#f8fafc", edgecolor="#475569", linewidth=1.5, alpha=0.9):
        ax.add_patch(p)
    if not water_union.is_empty:
        for p in plot_polygon_mpl(water_union, facecolor="#bae6fd", edgecolor="#0284c7", linewidth=1.0, alpha=0.8):
            ax.add_patch(p)

    for feat in p5.geojson_layer["features"]:
        qs = feat["properties"].get("quay_status")
        g = shape(feat["geometry"])
        lines = [g] if isinstance(g, LineString) else (list(g.geoms) if isinstance(g, MultiLineString) else [])
        for l in lines:
            if qs == "NEAR_SELECTED_OSM_WAY":
                ax.plot(*l.xy, color="#10b981", linewidth=4.5, solid_capstyle="round", zorder=30)
            else:
                ax.plot(*l.xy, color="#64748b", linewidth=3.5, solid_capstyle="round", zorder=25)

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_title("Rotterdam M4H: Problem 5 - Water-Land Interface & OSM-Way Proximity\n(問題五：水陸幾何界面與 OSM 路線鄰近度)", fontsize=11, fontweight="bold", pad=12)
    add_cartographic_elements(ax, xlim, ylim, scale_len_m=200.0)

    patches = [
        Line2D([0], [0], color="#10b981", linewidth=3.5, label="Within 22m of selected OSM way"),
        Line2D([0], [0], color="#64748b", linewidth=3.5, label="No selected OSM way within 22m"),
        Patch(facecolor="#bae6fd", edgecolor="#0284c7", label=f"BGT water ({bundle.water_area_m2:,.0f} m²)"),
    ]
    lax.legend(handles=patches, loc="upper left", title="OSM Way Proximity Proxy", fontsize=8, title_fontsize=8.5)
    lax.text(
        0.02, 0.40,
        f"【幾何鄰近量測】\n"
        f"• 水陸界面：{metric_text(p5, 'water_land_interface_length_m')} m\n"
        f"• 距篩選 OSM way ≤22m：{metric_text(p5, 'quay_near_osm_pedestrian_way_m')} m ({metric_text(p5, 'osmped_way_quay_proximity_pct')}%)\n"
        f"• 未落入該鄰近範圍：{metric_text(p5, 'quay_without_nearby_osm_pedestrian_way_m')} m\n"
        "• 不代表公眾可達／封閉狀態\n"
        f"• S2 審查級別：{p5.statement.severity_code}\n\n"
        "【對應形態字典建議】\n"
        "• space_waterfront_promenade\n"
        "• space_plaza (碼頭端景廣場)\n"
        "• block_open (通透視廊引水入城)",
        transform=lax.transAxes,
        fontsize=7.8,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#f1f5f9", edgecolor="#cbd5e1"),
    )
    f5_path = figures_dir / "fig05_problem_waterfront_inaccessibility.png"
    fig.savefig(f5_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    rendered.append(f5_path)

    # -----------------------------------------------------------------------
    # Fig 06: Massive Unclassified Ground Residual (AI-Discovered)
    # -----------------------------------------------------------------------
    p6 = bundle.problems[5]
    fig = plt.figure(figsize=(11, 8.5), dpi=150)
    ax = fig.add_axes([0.08, 0.12, 0.65, 0.78])
    lax = fig.add_axes([0.75, 0.15, 0.22, 0.72])
    lax.axis("off")

    for p in plot_polygon_mpl(sa_geom, facecolor="#f8fafc", edgecolor="#475569", linewidth=1.5, alpha=0.9):
        ax.add_patch(p)
    if not water_union.is_empty:
        for p in plot_polygon_mpl(water_union, facecolor="#bae6fd", edgecolor="#0284c7", linewidth=1.0, alpha=0.8):
            ax.add_patch(p)

    for feat in p6.geojson_layer["features"]:
        g = shape(feat["geometry"])
        for p in plot_polygon_mpl(g, facecolor="#f59e0b", edgecolor="#b45309", linewidth=1.0, alpha=0.65):
            ax.add_patch(p)

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_title("Rotterdam M4H: Problem 6 - Nonbuilding / Nonwater Geometry Remainder\n(問題六：非建築／非水體幾何差額；候選待確認)", fontsize=11, fontweight="bold", pad=12)
    add_cartographic_elements(ax, xlim, ylim, scale_len_m=200.0)

    patches = [
        Patch(facecolor="#f59e0b", edgecolor="#b45309", label="Exported remainder polygon area >5,000m²"),
        Patch(facecolor="#bae6fd", edgecolor="#0284c7", label=f"BGT water ({bundle.water_area_m2:,.0f} m²)"),
    ]
    lax.legend(handles=patches, loc="upper left", title="Geometry Only", fontsize=8, title_fontsize=8.5)
    lax.text(
        0.02, 0.40,
        f"【幾何差額量測】\n"
        f"• 面積：{metric_text(p6, 'nonbuilding_nonwater_residual_area_m2')} m² ({metric_text(p6, 'nonbuilding_nonwater_residual_ratio_pct')}% StudyArea)\n"
        f"• BAG footprint 聯集：{metric_text(p6, 'building_footprint_union_area_m2')} m²\n"
        f"• 幾何 Polygon 片段：{metric_text(p6, 'residual_polygon_count', 0)}；>5,000m²：{metric_text(p6, 'residual_polygons_over_5000m2_count', 0)}\n"
        "• 不代表地表材質、空置或土地用途\n\n"
        "【狀態】\n"
        f"• {p6.statement.status}\n"
        f"• S2 審查級別：{p6.statement.severity_code}\n\n"
        "【對應形態字典建議】\n"
        "• block_industrial_campus\n"
        "• space_plaza (定錨公共核心)\n"
        "• space_shared_street (細化街網)",
        transform=lax.transAxes,
        fontsize=7.8,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#f1f5f9", edgecolor="#cbd5e1"),
    )
    f6_path = figures_dir / "fig06_problem_unclassified_residual_ground.png"
    fig.savefig(f6_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    rendered.append(f6_path)

    return rendered


# ---------------------------------------------------------------------------
# Main Routine
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build spatial problem definition artifacts for Rotterdam M4H.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/w6-problem-definition", help="Output directory")
    parser.add_argument("--skip-figures", action="store_true", help="Skip rendering PNG figures")
    args = parser.parse_args()

    print(f"[1/4] Loading authoritative spatial inputs for StudyArea v5...")
    sa_geom, sa_id = load_study_area()
    bag_features, water_features, osm_features = load_normalized_inputs()
    green_features, _ = load_context_data()
    syntax_layer0 = load_syntax_layer0()

    print(f"[2/4] Running deterministic spatial problem analysis...")
    bundle = run_problem_definition_analysis(
        study_area_geom=sa_geom,
        bag_features=bag_features,
        water_features=water_features,
        road_features=osm_features,
        context_green_features=green_features,
        context_bag_features=bag_features,
        syntax_candidate_layer0=syntax_layer0,
        study_area_id=sa_id,
    )
    bundle.metadata["source_inventory"] = build_source_inventory()

    print(f"[3/4] Exporting GeoJSON layers and JSON statements to {args.output_dir}...")
    exported = export_problem_definition_artifacts(bundle, args.output_dir)
    for k, v in exported.items():
        print(f"  -> {k}: {v}")

    if not args.skip_figures:
        fig_dir = args.output_dir / "figures"
        print(f"[4/4] Rendering 6 cartographic problem map figures to {fig_dir}...")
        try:
            import matplotlib
            figures = render_all_problem_figures(bundle, fig_dir)
            for f in figures:
                print(f"  -> Figure rendered: {f}")
        except ImportError:
            qgis_py = Path("/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3")
            if qgis_py.exists():
                print(f"  -> Invoking QGIS Python for map rendering...")
                import subprocess
                env = os.environ.copy()
                env["MPLCONFIGDIR"] = "/private/tmp/w6-problem-definition-mplconfig"
                env["PROJ_LIB"] = "/Applications/QGIS-LTR.app/Contents/Resources/proj"
                env["PYTHONPATH"] = "src:scripts"
                subprocess.run([
                    str(qgis_py),
                    "scripts/render_problem_definition_maps.py",
                    "--artifacts-dir", str(args.output_dir),
                    "--output-dir", str(fig_dir),
                ], check=True, env=env)
            else:
                print("  -> matplotlib not found and QGIS python not present; skipping figure generation.")
    else:
        print("[4/4] Skipping map rendering (--skip-figures).")

    print("[DONE] Spatial problem definition build completed successfully.")


if __name__ == "__main__":
    main()
