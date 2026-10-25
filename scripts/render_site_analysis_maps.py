#!/usr/bin/env python3
"""Render site-analysis map figures for Rotterdam M4H.

Reproducibility (macOS, from the repository root; no package installation):
  MPLCONFIGDIR=/private/tmp/w5-site-analysis-mplconfig \
  PROJ_LIB=/Applications/QGIS-LTR.app/Contents/Resources/proj \
  PYTHONPATH=src:scripts PYTHONDONTWRITEBYTECODE=1 \
  /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 \
  scripts/render_site_analysis_maps.py --output-dir artifacts/w5-site-analysis/figures

Required interpreter: QGIS LTR Python. The project .venv does not provide
matplotlib. No downloads or package installation are performed.

Produces 12 cartographic maps in EPSG:28992:
- Fig 01: Scope & Context Overview (StudyArea v5 + 2 km surroundings)
- Fig 02: Existing Buildings & 3D BAG Height Distribution
- Fig 03: Transportation & Road Network Hierarchy
- Fig 04: Land Use & Functions
- Fig 05: Open Space, Water Bodies & Quay Interface
- Fig 06: Space Syntax - Local (800m) Pedestrian Integration (NAIN)
- Fig 07: Space Syntax - Local (800m) Pedestrian Choice (NACH)
- Fig 08: Space Syntax - Mid (2km) Bicycle Integration (NAIN)
- Fig 09: Space Syntax - Mid (2km) Bicycle Choice (NACH)
- Fig 10: Space Syntax - Regional (10km) Motor Vehicle Integration (NAIN)
- Fig 11: Space Syntax - Regional (10km) Motor Vehicle Choice (NACH)
- Fig 12: Surrounding Regional Relationships (Maas, Delfshaven, Schiedam)
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon as MplPolygon, Rectangle
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union

from build_site_analysis_report import linear_quintile_breaks, quintile_counts

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang TC", "Heiti TC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
MAIN_PROJECT_ROOT = Path("/Users/jackhsieh/Downloads/TUD/Q5/project")

STUDY_AREA_PATHS = [
    ROOT / "artifacts/week4-repair-r02/syntax/study-area.geojson",
    MAIN_PROJECT_ROOT / "artifacts/week4-repair-r02/syntax/study-area.geojson",
]

SPATIAL_R01_ROOTS = [
    ROOT / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01",
    MAIN_PROJECT_ROOT / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01",
]

URBAN_DATA_ROOT = Path(os.path.expanduser("~/.local/share/urban-design-data"))
CONTEXT_ROOT = URBAN_DATA_ROOT / "context"
THREE_DBAG_ROOT = URBAN_DATA_ROOT / "3dbag"
SYNTAX_RUN_ROOT = URBAN_DATA_ROOT / "week5-syntax-modes/syntax/run-week5-modes-01"
SYNTAX_EXTRACTED_ROOT = URBAN_DATA_ROOT / "week5-syntax-modes/extracted"


def find_path(paths: Sequence[Path]) -> Path:
    for p in paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"None found: {paths}")


def add_cartographic_elements(
    ax: plt.Axes,
    xlim: tuple[float, float],
    ylim: tuple[float, float],
    scale_len_m: float = 200.0,
    source_text: str = "CRS: EPSG:28992 | Source: PDOK / Kadaster / OSM | Producer: AGY (Gemini 3.8 Flash)",
) -> None:
    """Add standard North Arrow, Scale Bar, Grid, and Source Attribution."""
    minx, maxx = xlim
    miny, maxy = ylim

    # Grid
    ax.grid(True, linestyle=":", alpha=0.4, color="#94a3b8")
    ax.set_xlabel("RD Easting (m) [EPSG:28992]", fontsize=8, color="#334155")
    ax.set_ylabel("RD Northing (m) [EPSG:28992]", fontsize=8, color="#334155")
    ax.tick_params(axis="both", labelsize=7.5, colors="#475569")

    # North arrow in top-right
    na_x = maxx - (maxx - minx) * 0.05
    na_y = maxy - (maxy - miny) * 0.05
    arrow_len = (maxy - miny) * 0.04
    ax.annotate(
        "N",
        xy=(na_x, na_y),
        xytext=(na_x, na_y - arrow_len),
        arrowprops=dict(facecolor="#0f172a", edgecolor="#0f172a", width=2.0, headwidth=6.0, headlength=8.0),
        ha="center",
        va="bottom",
        fontsize=10,
        fontweight="bold",
        color="#0f172a",
        zorder=100,
    )

    # Scale bar in bottom-left
    sb_x = minx + (maxx - minx) * 0.05
    sb_y = miny + (maxy - miny) * 0.04
    tick_h = (maxy - miny) * 0.008
    ax.plot([sb_x, sb_x + scale_len_m], [sb_y, sb_y], color="#0f172a", linewidth=2.5, zorder=100)
    ax.plot([sb_x, sb_x], [sb_y - tick_h, sb_y + tick_h], color="#0f172a", linewidth=1.5, zorder=100)
    ax.plot([sb_x + scale_len_m, sb_x + scale_len_m], [sb_y - tick_h, sb_y + tick_h], color="#0f172a", linewidth=1.5, zorder=100)
    ax.plot([sb_x + scale_len_m / 2, sb_x + scale_len_m / 2], [sb_y - tick_h * 0.6, sb_y + tick_h * 0.6], color="#0f172a", linewidth=1.0, zorder=100)

    label_text = f"{int(scale_len_m)} m" if scale_len_m < 1000 else f"{scale_len_m / 1000:.1f} km"
    ax.text(sb_x + scale_len_m / 2, sb_y + tick_h * 1.5, label_text, ha="center", va="bottom", fontsize=8, fontweight="bold", color="#0f172a", zorder=100)

    # Source attribution text
    ax.text(0.01, -0.07, source_text, transform=ax.transAxes, fontsize=7.5, color="#64748b", ha="left", va="top")


def plot_polygon(geom: Polygon | MultiPolygon, facecolor: str, edgecolor: str, linewidth: float = 1.0, linestyle: str = "-", alpha: float = 1.0, label: str | None = None) -> list[MplPolygon]:
    patches = []
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    else:
        return []

    for i, p in enumerate(polys):
        coords = list(p.exterior.coords)
        lbl = label if (i == 0 and label) else None
        patch = MplPolygon(coords, closed=True, facecolor=facecolor, edgecolor=edgecolor, linewidth=linewidth, linestyle=linestyle, alpha=alpha, label=lbl, zorder=10)
        patches.append(patch)
    return patches


def extract_standalone_pst_segments(features: Sequence[dict[str, Any]]) -> dict[str, LineString]:
    """Extract clean PST segments with loop splitting (standalone implementation)."""
    candidate_lines = []
    for feat in features:
        geom_raw = feat.get("geometry")
        if not geom_raw:
            continue
        g = shape(geom_raw)
        lines = [g] if isinstance(g, LineString) else list(g.geoms) if isinstance(g, MultiLineString) else []
        feat_id = feat.get("id") or f"way/{feat.get('properties', {}).get('osm_id')}"
        
        for part_idx, line in enumerate(lines):
            sub_id = feat_id if len(lines) == 1 else f"{feat_id}#{part_idx+1}"
            raw_coords = list(line.coords)
            if len(raw_coords) < 2:
                continue
            clean = [raw_coords[0]]
            for pt in raw_coords[1:]:
                if (round(pt[0], 3), round(pt[1], 3)) != (round(clean[-1][0], 3), round(clean[-1][1], 3)):
                    clean.append(pt)
            if len(clean) < 2:
                continue
            if (round(clean[0][0], 3), round(clean[0][1], 3)) == (round(clean[-1][0], 3), round(clean[-1][1], 3)):
                mid = len(clean) // 2
                candidate_lines.append((f"{sub_id}_a", clean[: mid + 1]))
                candidate_lines.append((f"{sub_id}_b", clean[mid:]))
            else:
                candidate_lines.append((sub_id, clean))

    seg_geoms = {}
    for lid, coords in candidate_lines:
        for s_idx in range(len(coords) - 1):
            sid = f"{lid}::pst-segment-{s_idx+1:04d}"
            seg_geoms[sid] = LineString([coords[s_idx], coords[s_idx + 1]])
    return seg_geoms


@lru_cache(maxsize=1)
def load_context_documents() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load the retained 2 km OSM buildings, water, and road snapshots once."""
    manifest = json.loads((CONTEXT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    run_dir = CONTEXT_ROOT / manifest["run_directory"]
    buildings = json.loads((run_dir / "buildings.geojson").read_text(encoding="utf-8"))
    water = json.loads((run_dir / "water.geojson").read_text(encoding="utf-8"))
    roads = json.loads((run_dir / "roads.geojson").read_text(encoding="utf-8"))
    return buildings, water, roads


def add_syntax_context_layers(ax: plt.Axes, study_area_geom: Polygon | MultiPolygon) -> Polygon:
    """Draw faded 2 km context layers below the emphasized site network."""
    context_buffer = study_area_geom.buffer(2000.0)
    minx, miny, maxx, maxy = context_buffer.bounds
    buildings_doc, water_doc, roads_doc = load_context_documents()

    building_patches = []
    for feature in buildings_doc.get("features", []):
        geom = shape(feature["geometry"])
        bx0, by0, bx1, by1 = geom.bounds
        if bx1 < minx or bx0 > maxx or by1 < miny or by0 > maxy:
            continue
        building_patches.extend(plot_polygon(geom, facecolor="#e5e7eb", edgecolor="#cbd5e1", linewidth=0.25, alpha=0.62))
    if building_patches:
        ax.add_collection(PatchCollection(building_patches, match_original=True, zorder=1))

    water_patches = []
    for feature in water_doc.get("features", []):
        geom = shape(feature["geometry"])
        wx0, wy0, wx1, wy1 = geom.bounds
        if wx1 < minx or wx0 > maxx or wy1 < miny or wy0 > maxy:
            continue
        water_patches.extend(plot_polygon(geom, facecolor="#dbeafe", edgecolor="#bfdbfe", linewidth=0.35, alpha=0.72))
    if water_patches:
        ax.add_collection(PatchCollection(water_patches, match_original=True, zorder=2))

    road_lines = []
    for feature in roads_doc.get("features", []):
        geom = shape(feature["geometry"])
        gx0, gy0, gx1, gy1 = geom.bounds
        if gx1 < minx or gx0 > maxx or gy1 < miny or gy0 > maxy:
            continue
        lines = [geom] if isinstance(geom, LineString) else list(geom.geoms) if isinstance(geom, MultiLineString) else []
        road_lines.extend(list(line.coords) for line in lines)
    if road_lines:
        ax.add_collection(LineCollection(road_lines, colors="#94a3b8", linewidths=0.45, alpha=0.5, zorder=3))

    for patch in plot_polygon(context_buffer, facecolor="none", edgecolor="#64748b", linewidth=0.9, linestyle=":"):
        patch.set_zorder(4)
        ax.add_patch(patch)
    return context_buffer


def render_fig01_scope_and_context(study_area_geom: Polygon, out_dir: Path) -> Path:
    """Figure 1: Scope & Context (StudyArea v5 + 2km Context)."""
    fig, ax = plt.subplots(figsize=(10, 8), dpi=150)
    
    ctx_manifest = json.loads((CONTEXT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    run_dir = CONTEXT_ROOT / ctx_manifest["run_directory"]

    # Water
    water_doc = json.loads((run_dir / "water.geojson").read_text(encoding="utf-8"))
    water_patches = []
    for f in water_doc.get("features", []):
        g = shape(f["geometry"])
        water_patches.extend(plot_polygon(g, facecolor="#bae6fd", edgecolor="#7dd3fc", linewidth=0.5, alpha=0.8))
    if water_patches:
        ax.add_collection(PatchCollection(water_patches, match_original=True, zorder=2))

    # Green
    green_doc = json.loads((run_dir / "green.geojson").read_text(encoding="utf-8"))
    green_patches = []
    for f in green_doc.get("features", []):
        g = shape(f["geometry"])
        green_patches.extend(plot_polygon(g, facecolor="#bbf7d0", edgecolor="#86efac", linewidth=0.5, alpha=0.8))
    if green_patches:
        ax.add_collection(PatchCollection(green_patches, match_original=True, zorder=3))

    # Context Buildings
    bld_doc = json.loads((run_dir / "buildings.geojson").read_text(encoding="utf-8"))
    bld_patches = []
    for f in bld_doc.get("features", [])[::2]:
        g = shape(f["geometry"])
        bld_patches.extend(plot_polygon(g, facecolor="#e2e8f0", edgecolor="#cbd5e1", linewidth=0.3, alpha=0.7))
    if bld_patches:
        ax.add_collection(PatchCollection(bld_patches, match_original=True, zorder=4))

    # Context Roads
    roads_doc = json.loads((run_dir / "roads.geojson").read_text(encoding="utf-8"))
    road_lines = []
    for f in roads_doc.get("features", []):
        g = shape(f["geometry"])
        if isinstance(g, LineString):
            road_lines.append(list(g.coords))
        elif isinstance(g, MultiLineString):
            for part in g.geoms:
                road_lines.append(list(part.coords))
    if road_lines:
        lc = LineCollection(road_lines, colors="#94a3b8", linewidths=0.6, alpha=0.6, zorder=5)
        ax.add_collection(lc)

    # 2km Buffer Boundary
    buffer_2km = study_area_geom.buffer(2000.0)
    for p in plot_polygon(buffer_2km, facecolor="none", edgecolor="#6366f1", linewidth=1.5, linestyle=":", label="2 km 周邊緩衝區界線 (Context Buffer)"):
        ax.add_patch(p)

    # StudyArea v5
    for p in plot_polygon(study_area_geom, facecolor="#fee2e2", edgecolor="#dc2626", linewidth=2.5, linestyle="-", alpha=0.4, label="StudyArea v5 基地範圍 (22.61 ha)"):
        p.set_zorder(20)
        ax.add_patch(p)

    minx, miny, maxx, maxy = buffer_2km.bounds
    margin = 150
    ax.set_xlim(minx - margin, maxx + margin)
    ax.set_ylim(miny - margin, maxy + margin)
    ax.set_aspect("equal")

    add_cartographic_elements(
        ax,
        (minx - margin, maxx + margin),
        (miny - margin, maxy + margin),
        scale_len_m=1000.0,
        source_text="CRS: EPSG:28992 | Sources: PDOK StudyArea v5, OSM Zuid-Holland (2026-09-22) | Producer: AGY",
    )

    ax.set_title(
        "圖 1：Rotterdam M4H 基地範圍與 2 km 周邊環境概覽\nStudyArea v5 Boundary & 2 km Surrounding Context (EPSG:28992)",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )
    ax.legend(loc="upper left", framealpha=0.92, fontsize=8)

    plt.tight_layout()
    out_path = out_dir / "fig01_scope_and_context.png"
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def render_fig02_buildings_height(study_area_geom: Polygon, out_dir: Path) -> Path:
    """Figure 2: Existing Buildings & 3D BAG Height Distribution."""
    fig, ax = plt.subplots(figsize=(10, 8), dpi=150)

    for p in plot_polygon(study_area_geom, facecolor="#f8fafc", edgecolor="#475569", linewidth=1.8, linestyle="--", label="StudyArea v5"):
        ax.add_patch(p)

    spatial_root = find_path(SPATIAL_R01_ROOTS)
    bag_files = sorted((spatial_root / "sources/normalized").glob("pdok-bag-pand-*.geojson"))
    
    ht_path = THREE_DBAG_ROOT / "height-table-v2025.09.03-study-area-v5-buffer500m.json"
    ht_doc = json.loads(ht_path.read_text(encoding="utf-8"))
    ht_by_ident = {}
    for r in ht_doc.get("records", []):
        ht_by_ident[r["bag_identificatie"]] = r
        ht_by_ident[r["bag_identificatie"].replace("NL.IMBAG.Pand.", "")] = r

    height_colors = {
        "low": "#fed7aa",
        "mid": "#f97316",
        "high": "#ea580c",
        "tower": "#9a3412",
        "demolished": "#94a3b8",
        "unmatched": "#cbd5e1",
    }

    legend_handles = [
        Patch(facecolor="#fed7aa", edgecolor="#c2410c", label="低層 (高度 < 6 m / 約 1-2F)"),
        Patch(facecolor="#f97316", edgecolor="#9a3412", label="中層 (高度 6–12 m / 約 2-4F)"),
        Patch(facecolor="#ea580c", edgecolor="#7c2d12", label="高層 (高度 12–18 m / 約 4-6F)"),
        Patch(facecolor="#9a3412", edgecolor="#431407", label="超高 (高度 > 18 m / 最高 27.4 m)"),
        Patch(facecolor="#94a3b8", edgecolor="#64748b", linestyle=":", label="BAG 歷史已拆除 (Pand gesloopt, 無高度)"),
    ]

    for bf in bag_files:
        data = json.loads(bf.read_text(encoding="utf-8"))
        for f in data.get("features", []):
            g = shape(f["geometry"])
            if g.intersects(study_area_geom):
                clipped = g.intersection(study_area_geom)
                if clipped.is_empty:
                    continue
                ident = str(f.get("properties", {}).get("identificatie") or "")
                hr = ht_by_ident.get(ident)
                status_text = str(f.get("properties", {}).get("status") or "")

                if hr and hr.get("status") == "AVAILABLE" and hr.get("height_above_ground_m") is not None:
                    h = float(hr["height_above_ground_m"])
                    if h < 6.0:
                        fc = height_colors["low"]
                    elif h < 12.0:
                        fc = height_colors["mid"]
                    elif h < 18.0:
                        fc = height_colors["high"]
                    else:
                        fc = height_colors["tower"]
                    ec = "#431407"
                    ls = "-"
                elif "gesloopt" in status_text.lower():
                    fc = height_colors["demolished"]
                    ec = "#64748b"
                    ls = ":"
                else:
                    fc = height_colors["unmatched"]
                    ec = "#64748b"
                    ls = "--"

                for p in plot_polygon(clipped, facecolor=fc, edgecolor=ec, linewidth=1.2, linestyle=ls, alpha=0.9):
                    p.set_zorder(15)
                    ax.add_patch(p)

    minx, miny, maxx, maxy = study_area_geom.bounds
    margin = 80
    ax.set_xlim(minx - margin, maxx + margin)
    ax.set_ylim(miny - margin, maxy + margin)
    ax.set_aspect("equal")

    add_cartographic_elements(
        ax,
        (minx - margin, maxx + margin),
        (miny - margin, maxy + margin),
        scale_len_m=200.0,
        source_text="CRS: EPSG:28992 | Sources: PDOK BAG pand, 3D BAG v2025.09.03 (TU Delft) | Producer: AGY",
    )

    ax.set_title(
        "圖 2：既有建築高度分布與保存狀況圖 (51 棟 BAG 特徵)\nExisting Buildings & 3D BAG Heights (Median: 9.85 m, Max: 27.41 m)",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )
    ax.legend(handles=legend_handles, loc="upper right", framealpha=0.92, fontsize=8)

    plt.tight_layout()
    out_path = out_dir / "fig02_existing_buildings_height.png"
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def render_fig03_transport(study_area_geom: Polygon, out_dir: Path) -> Path:
    """Figure 3: Transportation & Road Network Hierarchy & Gateway Points."""
    fig, ax = plt.subplots(figsize=(10, 8), dpi=150)

    for p in plot_polygon(study_area_geom, facecolor="#f8fafc", edgecolor="#475569", linewidth=1.5, linestyle="--"):
        ax.add_patch(p)

    spatial_root = find_path(SPATIAL_R01_ROOTS)
    water_files = sorted((spatial_root / "sources/normalized").glob("pdok-bgt-waterdeel-*.geojson"))
    for wf in water_files:
        data = json.loads(wf.read_text(encoding="utf-8"))
        for f in data.get("features", []):
            g = shape(f["geometry"])
            if g.intersects(study_area_geom):
                clipped = g.intersection(study_area_geom)
                for p in plot_polygon(clipped, facecolor="#e0f2fe", edgecolor="#0284c7", linewidth=1.2, alpha=0.7):
                    p.set_zorder(5)
                    ax.add_patch(p)

    hwy_styles = {
        "service": ("#475569", 1.8, "-", "服務與作業通道 (Service, 3,425 m)"),
        "footway": ("#059669", 1.5, "--", "步行專用步道 (Footway, 1,898 m)"),
        "unclassified": ("#0284c7", 2.2, "-", "次要聯絡道路 (Unclassified, 1,293 m)"),
        "cycleway": ("#d97706", 1.8, "-.", "專用自行車道 (Cycleway, 956 m)"),
        "pedestrian": ("#10b981", 2.0, "-", "徒步廣場與街道 (Pedestrian, 696 m)"),
        "proposed": ("#94a3b8", 1.2, ":", "規劃路線 (Proposed, 221 m)"),
    }

    osm_path = spatial_root / "sources/normalized/osm-overpass-v5-epsg28992.geojson"
    osm_doc = json.loads(osm_path.read_text(encoding="utf-8"))

    boundary = study_area_geom.boundary
    gateways = []

    lines_by_style = {}
    for f in osm_doc.get("features", []):
        tags = f.get("properties", {}).get("tags", {})
        hwy = tags.get("highway", "other")
        g = shape(f["geometry"])
        if g.intersects(study_area_geom):
            clipped = g.intersection(study_area_geom)
            if not clipped.is_empty and clipped.length > 1e-3:
                style_key = hwy if hwy in hwy_styles else "service"
                if style_key not in lines_by_style:
                    lines_by_style[style_key] = []
                if isinstance(clipped, LineString):
                    lines_by_style[style_key].append(list(clipped.coords))
                elif isinstance(clipped, MultiLineString):
                    for part in clipped.geoms:
                        lines_by_style[style_key].append(list(part.coords))
            
            inter = g.intersection(boundary)
            if not inter.is_empty:
                if inter.geom_type == "Point":
                    gateways.append((inter.x, inter.y))
                elif inter.geom_type == "MultiPoint":
                    for pt in inter.geoms:
                        gateways.append((pt.x, pt.y))

    for style_key, coords_list in lines_by_style.items():
        col, lw, ls, _ = hwy_styles.get(style_key, ("#475569", 1.0, "-", "Other"))
        lc = LineCollection(coords_list, colors=col, linewidths=lw, linestyles=ls, zorder=20)
        ax.add_collection(lc)

    gateway_coords = sorted({(round(x, 3), round(y, 3)) for x, y in gateways})
    if gateway_coords:
        gx, gy = zip(*gateway_coords)
        ax.scatter(gx, gy, color="#dc2626", s=45, edgecolors="#ffffff", linewidths=1.2, zorder=30, label="StudyArea 邊界幾何交點")

    legend_handles = [
        Line2D([0], [0], color=col, lw=lw, ls=ls, label=lbl)
        for col, lw, ls, lbl in hwy_styles.values()
    ]
    legend_handles.append(Line2D([0], [0], marker="o", color="w", markerfacecolor="#dc2626", markersize=8, label=f"邊界幾何交點 ({len(gateway_coords)} 個；非通行出入口證據)"))
    legend_handles.append(Patch(facecolor="#e0f2fe", edgecolor="#0284c7", label="BGT 水體圖徵"))

    minx, miny, maxx, maxy = study_area_geom.bounds
    margin = 80
    ax.set_xlim(minx - margin, maxx + margin)
    ax.set_ylim(miny - margin, maxy + margin)
    ax.set_aspect("equal")

    add_cartographic_elements(
        ax,
        (minx - margin, maxx + margin),
        (miny - margin, maxy + margin),
        scale_len_m=200.0,
        source_text="CRS: EPSG:28992 | Sources: OSM Overpass v5, PDOK BGT | Producer: AGY",
    )

    ax.set_title(
        f"圖 3：OSM 道路標籤與 StudyArea 邊界幾何交點 ({len(gateway_coords)} 個)\nOSM Highway Tags and StudyArea Boundary Intersections",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )
    ax.legend(handles=legend_handles, loc="upper right", framealpha=0.92, fontsize=8)

    plt.tight_layout()
    out_path = out_dir / "fig03_transport_road_network.png"
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def render_fig04_land_use(study_area_geom: Polygon, out_dir: Path) -> Path:
    """Figure 4: Land Use & Registered Building Usages."""
    fig, ax = plt.subplots(figsize=(10, 8), dpi=150)

    for p in plot_polygon(study_area_geom, facecolor="#f8fafc", edgecolor="#475569", linewidth=1.5, linestyle="--"):
        ax.add_patch(p)

    spatial_root = find_path(SPATIAL_R01_ROOTS)
    bag_files = sorted((spatial_root / "sources/normalized").glob("pdok-bag-pand-*.geojson"))

    usage_colors = {
        "industrie": ("#f59e0b", "工業與生產功能 (Industriefunctie, 19棟)"),
        "kantoor": ("#3b82f6", "辦公功能 (Kantoorfunctie, 9棟)"),
        "bijeenkomst": ("#a855f7", "文化與集會功能 (Bijeenkomstfunctie, 5棟)"),
        "winkel": ("#ec4899", "零售商業功能 (Winkelfunctie, 3棟)"),
        "overige": ("#64748b", "其他附屬功能 (Overige gebruiksfunctie, 5棟)"),
        "unknown": ("#cbd5e1", "用途未登記/空白 (UNKNOWN, 20棟)"),
    }

    for bf in bag_files:
        data = json.loads(bf.read_text(encoding="utf-8"))
        for f in data.get("features", []):
            g = shape(f["geometry"])
            if g.intersects(study_area_geom):
                clipped = g.intersection(study_area_geom)
                if clipped.is_empty:
                    continue
                usage = str(f.get("properties", {}).get("gebruiksdoel") or "").lower()
                if "industrie" in usage:
                    fc = usage_colors["industrie"][0]
                elif "kantoor" in usage:
                    fc = usage_colors["kantoor"][0]
                elif "bijeenkomst" in usage:
                    fc = usage_colors["bijeenkomst"][0]
                elif "winkel" in usage:
                    fc = usage_colors["winkel"][0]
                elif "overige" in usage:
                    fc = usage_colors["overige"][0]
                else:
                    fc = usage_colors["unknown"][0]

                for p in plot_polygon(clipped, facecolor=fc, edgecolor="#1e293b", linewidth=1.0, alpha=0.9):
                    p.set_zorder(15)
                    ax.add_patch(p)

    # Green features inside site
    ctx_manifest = json.loads((CONTEXT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    green_doc = json.loads((CONTEXT_ROOT / ctx_manifest["run_directory"] / "green.geojson").read_text(encoding="utf-8"))
    for f in green_doc.get("features", []):
        g = shape(f["geometry"])
        if g.intersects(study_area_geom):
            clipped = g.intersection(study_area_geom)
            for p in plot_polygon(clipped, facecolor="#86efac", edgecolor="#16a34a", linewidth=1.0, alpha=0.7):
                p.set_zorder(8)
                ax.add_patch(p)

    legend_handles = [
        Patch(facecolor=col, edgecolor="#1e293b", label=lbl)
        for col, lbl in usage_colors.values()
    ]
    legend_handles.append(Patch(facecolor="#86efac", edgecolor="#16a34a", label="都市綠地與市民農園 (OSM Green, 2.19 ha)"))

    minx, miny, maxx, maxy = study_area_geom.bounds
    margin = 80
    ax.set_xlim(minx - margin, maxx + margin)
    ax.set_ylim(miny - margin, maxy + margin)
    ax.set_aspect("equal")

    add_cartographic_elements(
        ax,
        (minx - margin, maxx + margin),
        (miny - margin, maxy + margin),
        scale_len_m=200.0,
        source_text="CRS: EPSG:28992 | Sources: PDOK BAG pand, OSM Green | Producer: AGY",
    )

    ax.set_title(
        "圖 4：基地登記使用機能與綠地分布圖 (31 棟具登記用途)\nRegistered BAG Building Usages & Green Surfaces",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )
    ax.legend(handles=legend_handles, loc="upper right", framealpha=0.92, fontsize=8)

    plt.tight_layout()
    out_path = out_dir / "fig04_land_use_and_functions.png"
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def render_fig05_open_space_and_water(study_area_geom: Polygon, out_dir: Path) -> Path:
    """Figure 5: Open Space, Water Bodies & Quay Interface."""
    fig, ax = plt.subplots(figsize=(10, 8), dpi=150)

    # Base StudyArea
    for p in plot_polygon(study_area_geom, facecolor="#f1f5f9", edgecolor="#64748b", linewidth=1.5, linestyle="--", label="StudyArea; residual geometry not classified"):
        p.set_zorder(1)
        ax.add_patch(p)

    spatial_root = find_path(SPATIAL_R01_ROOTS)
    
    # Water
    water_files = sorted((spatial_root / "sources/normalized").glob("pdok-bgt-waterdeel-*.geojson"))
    water_clipped = []
    for wf in water_files:
        data = json.loads(wf.read_text(encoding="utf-8"))
        for f in data.get("features", []):
            g = shape(f["geometry"])
            if g.intersects(study_area_geom):
                c = g.intersection(study_area_geom)
                if not c.is_empty:
                    water_clipped.append(c)

    water_union = unary_union(water_clipped)
    for p in plot_polygon(water_union, facecolor="#38bdf8", edgecolor="#0284c7", linewidth=1.5, alpha=0.85, label="BGT registered water (4.25 ha)"):
        p.set_zorder(10)
        ax.add_patch(p)

    # Buildings Footprint
    bag_files = sorted((spatial_root / "sources/normalized").glob("pdok-bag-pand-*.geojson"))
    bld_clipped = []
    for bf in bag_files:
        data = json.loads(bf.read_text(encoding="utf-8"))
        for f in data.get("features", []):
            g = shape(f["geometry"])
            if g.intersects(study_area_geom):
                c = g.intersection(study_area_geom)
                if not c.is_empty:
                    bld_clipped.append(c)
    bld_union = unary_union(bld_clipped)
    for p in plot_polygon(bld_union, facecolor="#94a3b8", edgecolor="#334155", linewidth=1.0, alpha=0.8, label="既有建築佔地 (4.47 ha, 19.77%)"):
        p.set_zorder(15)
        ax.add_patch(p)

    # Green Spaces
    ctx_manifest = json.loads((CONTEXT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    green_doc = json.loads((CONTEXT_ROOT / ctx_manifest["run_directory"] / "green.geojson").read_text(encoding="utf-8"))
    green_clipped = []
    for f in green_doc.get("features", []):
        g = shape(f["geometry"])
        if g.intersects(study_area_geom):
            c = g.intersection(study_area_geom)
            if not c.is_empty:
                green_clipped.append(c)
    if green_clipped:
        green_union = unary_union(green_clipped)
        for p in plot_polygon(green_union, facecolor="#4ade80", edgecolor="#15803d", linewidth=1.2, alpha=0.9, label="都市綠地/市民農園 (2.19 ha, 9.68%)"):
            p.set_zorder(18)
            ax.add_patch(p)

    # Quay wall line
    water_boundary = water_union.boundary
    quay_interface = water_boundary.difference(study_area_geom.boundary.buffer(0.01))
    if isinstance(quay_interface, LineString):
        q_lines = [list(quay_interface.coords)]
    elif isinstance(quay_interface, MultiLineString):
        q_lines = [list(part.coords) for part in quay_interface.geoms]
    else:
        q_lines = []

    if q_lines:
        qlc = LineCollection(q_lines, colors="#dc2626", linewidths=3.0, zorder=25, label="Geometric water boundary interface (1,332 m)")
        ax.add_collection(qlc)

    minx, miny, maxx, maxy = study_area_geom.bounds
    margin = 80
    ax.set_xlim(minx - margin, maxx + margin)
    ax.set_ylim(miny - margin, maxy + margin)
    ax.set_aspect("equal")

    add_cartographic_elements(
        ax,
        (minx - margin, maxx + margin),
        (miny - margin, maxy + margin),
        scale_len_m=200.0,
        source_text="CRS: EPSG:28992 | Sources: PDOK BGT, BAG, OSM | Producer: AGY",
    )

    ax.set_title(
        "圖 5：水體、水陸介面、綠地與未分類地面殘差分布圖\nWater, Quay Interface (1,332 m), Green Spaces, and Residual Surface (13.89 ha)",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )
    ax.legend(loc="upper right", framealpha=0.92, fontsize=8)

    plt.tight_layout()
    out_path = out_dir / "fig05_open_space_and_water.png"
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def render_syntax_layer(
    layer_idx: int,
    layer_info: dict[str, Any],
    study_area_geom: Polygon,
    out_dir: Path,
) -> Path:
    """Render a single Space Syntax Heatmap with 5 quintile breaks (Blue -> Red)."""
    fig = plt.figure(figsize=(10, 8), dpi=150)
    ax = fig.add_axes([0.09, 0.16, 0.62, 0.70])
    legend_ax = fig.add_axes([0.75, 0.20, 0.23, 0.62])
    context_buffer = add_syntax_context_layers(ax, study_area_geom)
    for p in plot_polygon(study_area_geom, facecolor="#ffffff", edgecolor="#334155", linewidth=1.4, alpha=0.76):
        p.set_zorder(8)
        ax.add_patch(p)

    mode = layer_info["network_mode"]
    net_file_map = {
        "pedestrian": SYNTAX_EXTRACTED_ROOT / "network_pedestrian_1500m.geojson",
        "bicycle": SYNTAX_EXTRACTED_ROOT / "network_bicycle_6000m.geojson",
        "motor_vehicle": SYNTAX_EXTRACTED_ROOT / "network_motor_vehicle_20000m.geojson",
    }
    net_path = net_file_map[mode]
    net_doc = json.loads(net_path.read_text(encoding="utf-8"))

    # Standalone segment extraction
    seg_geoms = extract_standalone_pst_segments(net_doc["features"])

    seg_values = layer_info["segment_values"]

    site_value_items = {
        sid: float(seg_values[sid])
        for sid, geom in seg_geoms.items()
        if sid in seg_values and geom.intersects(study_area_geom)
    }
    breaks = linear_quintile_breaks(list(site_value_items.values()))
    class_counts = quintile_counts(list(site_value_items.values()), breaks)

    # Quintile color ramp
    colors = ["#1d4ed8", "#06b6d4", "#10b981", "#f59e0b", "#dc2626"]
    widths = [1.8, 2.2, 2.6, 3.0, 3.5]
    
    lines_by_q = {i: [] for i in range(5)}
    uncalculated_lines = []
    uncalculated_segment_count = 0

    for sid, geom in seg_geoms.items():
        if not geom.intersects(study_area_geom):
            continue
        clipped = geom.intersection(study_area_geom)
        if clipped.is_empty:
            continue
        c_lines = [list(clipped.coords)] if isinstance(clipped, LineString) else [list(part.coords) for part in clipped.geoms]

        if sid in site_value_items:
            val = site_value_items[sid]
            if val <= breaks[1]:
                q = 0
            elif val <= breaks[2]:
                q = 1
            elif val <= breaks[3]:
                q = 2
            elif val <= breaks[4]:
                q = 3
            else:
                q = 4
            lines_by_q[q].extend(c_lines)
        else:
            uncalculated_lines.extend(c_lines)
            uncalculated_segment_count += 1

    if uncalculated_lines:
        ulc = LineCollection(uncalculated_lines, colors="#94a3b8", linewidths=1.0, linestyles="--", zorder=8)
        ax.add_collection(ulc)

    for q in range(5):
        if lines_by_q[q]:
            lc = LineCollection(lines_by_q[q], colors=colors[q], linewidths=widths[q], zorder=10 + q)
            ax.add_collection(lc)

    legend_handles = [
        Line2D([0], [0], color=colors[0], lw=widths[0], label=f"Very Low · n={class_counts[0]}\n[{breaks[0]:.3f}, {breaks[1]:.3f}]"),
        Line2D([0], [0], color=colors[1], lw=widths[1], label=f"Low · n={class_counts[1]}\n({breaks[1]:.3f}, {breaks[2]:.3f}]"),
        Line2D([0], [0], color=colors[2], lw=widths[2], label=f"Medium · n={class_counts[2]}\n({breaks[2]:.3f}, {breaks[3]:.3f}]"),
        Line2D([0], [0], color=colors[3], lw=widths[3], label=f"High · n={class_counts[3]}\n({breaks[3]:.3f}, {breaks[4]:.3f}]"),
        Line2D([0], [0], color=colors[4], lw=widths[4], label=f"Very High · n={class_counts[4]}\n({breaks[4]:.3f}, {breaks[5]:.3f}]"),
    ]
    if uncalculated_lines:
        legend_handles.append(Line2D([0], [0], color="#94a3b8", lw=1.0, ls="--", label=f"未計算基地路段 · n={uncalculated_segment_count}"))

    minx, miny, maxx, maxy = context_buffer.bounds
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal")

    metric_name = layer_info["title"]
    layer_id = layer_info["layer_id"]
    fig_num = 6 + layer_idx
    filename = f"fig{fig_num:02d}_{layer_id}.png"

    add_cartographic_elements(
        ax,
        (minx, maxx),
        (miny, maxy),
        scale_len_m=200.0,
        source_text="",
    )

    fig.text(
        0.09,
        0.075,
        f"CRS: EPSG:28992 | Engine: PST 3.3.1 (PD-15) | Status: {layer_info['data_readiness']} | EXPLORATORY ONLY",
        fontsize=7.5,
        color="#64748b",
        ha="left",
    )

    ax.set_title(f"圖 {fig_num}：{metric_name}\n基地內路段著色；淡色底圖為 2 km OSM 周邊", fontsize=11, fontweight="bold", pad=10)
    legend_ax.axis("off")
    legend_ax.set_title(f"基地內五分位\n有值路段 n={len(site_value_items)}", fontsize=10, fontweight="bold", loc="left")
    legend_ax.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(0.0, 0.95), framealpha=0.96, fontsize=8, handlelength=2.5, labelspacing=1.1)

    # Watermark / Notice
    legend_ax.text(
        0.0, 0.02,
        "注意：探索性幾何指標，\n不等於實際人流或交通量。",
        fontsize=8,
        fontweight="bold",
        color="#b91c1c",
        ha="left",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#fef2f2", edgecolor="#f87171", alpha=0.9),
        zorder=50,
    )

    out_path = out_dir / filename
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def render_fig12_regional_relationships(study_area_geom: Polygon, out_dir: Path) -> Path:
    """Figure 12: retained OSM 2 km context water, green, and road layers."""
    fig, ax = plt.subplots(figsize=(10, 8), dpi=150)

    buffer_2km = study_area_geom.buffer(2000.0)
    for p in plot_polygon(buffer_2km, facecolor="#f8fafc", edgecolor="#cbd5e1", linewidth=1.0, linestyle=":"):
        ax.add_patch(p)

    ctx_manifest = json.loads((CONTEXT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    run_dir = CONTEXT_ROOT / ctx_manifest["run_directory"]

    # Water
    water_doc = json.loads((run_dir / "water.geojson").read_text(encoding="utf-8"))
    water_patches = []
    for f in water_doc.get("features", []):
        g = shape(f["geometry"])
        water_patches.extend(plot_polygon(g, facecolor="#bae6fd", edgecolor="#0284c7", linewidth=0.8, alpha=0.85))
    if water_patches:
        ax.add_collection(PatchCollection(water_patches, match_original=True, zorder=5))

    # Green
    green_doc = json.loads((run_dir / "green.geojson").read_text(encoding="utf-8"))
    green_patches = []
    for f in green_doc.get("features", []):
        g = shape(f["geometry"])
        green_patches.extend(plot_polygon(g, facecolor="#bbf7d0", edgecolor="#16a34a", linewidth=0.6, alpha=0.75))
    if green_patches:
        ax.add_collection(PatchCollection(green_patches, match_original=True, zorder=6))

    # Roads
    roads_doc = json.loads((run_dir / "roads.geojson").read_text(encoding="utf-8"))
    major_roads = []
    local_roads = []
    for f in roads_doc.get("features", []):
        g = shape(f["geometry"])
        hwy = f.get("properties", {}).get("highway", "")
        lines = [list(g.coords)] if isinstance(g, LineString) else [list(part.coords) for part in g.geoms]
        if hwy in ("primary", "secondary", "trunk", "motorway"):
            major_roads.extend(lines)
        else:
            local_roads.extend(lines)

    if local_roads:
        ax.add_collection(LineCollection(local_roads, colors="#cbd5e1", linewidths=0.6, alpha=0.5, zorder=8))
    if major_roads:
        ax.add_collection(LineCollection(major_roads, colors="#f97316", linewidths=2.0, alpha=0.9, zorder=12, label="Higher-class OSM highway tags"))

    # StudyArea
    for p in plot_polygon(study_area_geom, facecolor="#ef4444", edgecolor="#991b1b", linewidth=2.5, alpha=0.45, label="M4H StudyArea v5 (22.61 ha)"):
        p.set_zorder(20)
        ax.add_patch(p)

    minx, miny, maxx, maxy = buffer_2km.bounds
    margin = 100
    ax.set_xlim(minx - margin, maxx + margin)
    ax.set_ylim(miny - margin, maxy + margin)
    ax.set_aspect("equal")

    add_cartographic_elements(
        ax,
        (minx - margin, maxx + margin),
        (miny - margin, maxy + margin),
        scale_len_m=1000.0,
        source_text="CRS: EPSG:28992 | Sources: OSM Context, PDOK StudyArea v5 | Producer: AGY",
    )

    ax.set_title(
        "圖 12：StudyArea v5 與 2 km OSM 水體、綠地及道路圖層\nRetained OSM Context Features (EPSG:28992)",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )
    ax.legend(loc="upper left", framealpha=0.92, fontsize=8)

    plt.tight_layout()
    out_path = out_dir / "fig12_regional_urban_relationships.png"
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render M4H map figures")
    parser.add_argument("--output-dir", required=True, help="Output directory for PNG figures")
    parser.add_argument("--syntax-only", action="store_true", help="Render only the six syntax maps")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    study_path = find_path(STUDY_AREA_PATHS)
    study_doc = json.loads(study_path.read_text(encoding="utf-8"))
    study_geom = shape(study_doc["geometry"] if "geometry" in study_doc else study_doc["features"][0]["geometry"])

    if not args.syntax_only:
        print("Rendering Fig 01: Scope & Context Overview...")
        render_fig01_scope_and_context(study_geom, out_dir)

        print("Rendering Fig 02: Existing Buildings & 3D BAG Heights...")
        render_fig02_buildings_height(study_geom, out_dir)

        print("Rendering Fig 03: Transportation & Road Network...")
        render_fig03_transport(study_geom, out_dir)

        print("Rendering Fig 04: Land Use & Registered Usages...")
        render_fig04_land_use(study_geom, out_dir)

        print("Rendering Fig 05: Open Space, Water Bodies & Quay Interface...")
        render_fig05_open_space_and_water(study_geom, out_dir)

    cand_path = SYNTAX_RUN_ROOT / "syntax_six_layer_candidate.json"
    cand_doc = json.loads(cand_path.read_text(encoding="utf-8"))
    for idx, layer_info in enumerate(cand_doc.get("layers", [])):
        print(f"Rendering Space Syntax Layer {idx}: {layer_info['layer_id']}...")
        render_syntax_layer(idx, layer_info, study_geom, out_dir)

    if not args.syntax_only:
        print("Rendering Fig 12: Surrounding Regional Relationships...")
        render_fig12_regional_relationships(study_geom, out_dir)

    rendered = 6 if args.syntax_only else 12
    print(f"Rendered {rendered} figure(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
