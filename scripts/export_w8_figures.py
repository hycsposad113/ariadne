#!/usr/bin/env python3
"""Export formal W8-B figure set and manifest for the four fabric schemes.

Figures produced per fabric:
1. Massing Plan (量體平面圖): Land use patches, building massing by height, road hierarchy, water, site boundary, north arrow, scale bar, legend.
2. Axonometric View (等角圖): Buildings extruded by height with consistent angle, scale, and directional shading.
3. Perspective View (透視示意圖): Eye-level perspective from the west end of the primary street looking east, explicitly marked as schematic.
4. Syntax Plan (After & Delta) (語法圖): Pedestrian NAIN 800m after, and delta (after - before), with unified quantiles across all 4 schemes.
5. 4-Scheme Comparative Overview Board (四案並排比較版面): 2x2 board comparing all four schemes with identical extent, scale, and styling.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box, shape

METHOD_VERSION = "w8b-export-v2"
OUTPUT_DPI = 301
MAP_EXTENT_BUFFER_M = 120.0
AXONOMETRIC_VIEW_MARGIN_M = 20.0

CONTEXT_DATASET_DIR = Path(
    "/Users/jackhsieh/.local/share/urban-design-data/context/context-20260927T153054Z"
)
CONTEXT_LAYER_FILES = {
    "buildings": "buildings.geojson",
    "roads": "roads.geojson",
    "water": "water.geojson",
}
CONTEXT_STYLES = {
    "buildings": {"fill": "#e5e6e4", "outline": "#d0d3d2", "width": 1},
    "roads": {"fill": None, "outline": "#b9c0c2", "width": 2},
    "water": {"fill": "#e6ecee", "outline": "#cbd5d8", "width": 1},
}

FABRICS = [
    "harbour_grain",
    "closed_block_extension",
    "courtyard_islands",
    "landscape_figure",
]

FABRIC_NAMES_ZH = {
    "harbour_grain": "港埠線性紋理",
    "closed_block_extension": "圍合街廓延伸",
    "courtyard_islands": "大型院落島",
    "landscape_figure": "地景為圖",
}

FONT_PATHS = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]


def get_font_path() -> Optional[str]:
    for p in FONT_PATHS:
        if os.path.exists(p):
            return p
    return None


ACTIVE_FONT_PATH = get_font_path()


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if ACTIVE_FONT_PATH:
        try:
            return ImageFont.truetype(ACTIVE_FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_union_buffered_bounds(plans: Dict[str, Dict[str, Any]], buffer_m: float = 120.0) -> Tuple[float, float, float, float]:
    site_geoms = []
    for plan in plans.values():
        if "site" in plan:
            site_geoms.append(shape(plan["site"]))
    if not site_geoms:
        raise ValueError("No site geometry found in plans")
    union_site = site_geoms[0]
    for g in site_geoms[1:]:
        union_site = union_site.union(g)
    buffered = union_site.buffer(buffer_m)
    return buffered.bounds


def load_context_layers(
    bounds: Tuple[float, float, float, float],
    dataset_dir: Optional[Path] = None,
) -> Tuple[Dict[str, List[Any]], Dict[str, Any], List[Path]]:
    """Load and clip the dated EPSG:28992 context files to the shared extent."""
    root = dataset_dir or CONTEXT_DATASET_DIR
    extent = box(*bounds)
    layers: Dict[str, List[Any]] = {name: [] for name in CONTEXT_LAYER_FILES}
    manifest_layers: Dict[str, Any] = {}
    source_paths: List[Path] = []

    for layer_name, filename in CONTEXT_LAYER_FILES.items():
        path = root / filename
        if not path.is_file():
            manifest_layers[layer_name] = {"status": "MISSING", "path": str(path)}
            continue
        source_paths.append(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        visible_count = 0
        for feature in payload.get("features", []):
            geometry_doc = feature.get("geometry")
            if not geometry_doc:
                continue
            props = feature.get("properties", {})
            bbox = props.get("bounds_m")
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                if bbox[2] < bounds[0] or bbox[0] > bounds[2] or bbox[3] < bounds[1] or bbox[1] > bounds[3]:
                    continue
            geom = shape(geometry_doc)
            if geom.is_empty or not geom.intersects(extent):
                continue
            clipped = geom.intersection(extent)
            if not clipped.is_empty:
                layers[layer_name].append(clipped)
                visible_count += 1
        manifest_layers[layer_name] = {
            "status": "AVAILABLE",
            "path": str(path),
            "sha256": sha256_file(path),
            "feature_count": len(payload.get("features", [])),
            "visible_feature_count": visible_count,
        }

    status = "AVAILABLE" if all(v.get("status") == "AVAILABLE" for v in manifest_layers.values()) else "PARTIAL"
    return layers, {
        "status": status,
        "directory": str(root),
        "crs": "EPSG:28992",
        "layers": manifest_layers,
    }, source_paths


def draw_context_layers(draw: ImageDraw.ImageDraw, layers: Dict[str, List[Any]], to_scr: Any, faint_roads: bool = False) -> None:
    """Draw surrounding context beneath scenario geometry in a restrained gray palette."""
    for layer_name in ("water", "buildings", "roads"):
        style = dict(CONTEXT_STYLES[layer_name])
        if layer_name == "roads" and faint_roads:
            style["outline"] = "#ebeeed"
            style["width"] = 1
        for geom in layers.get(layer_name, []):
            draw_shapely_geom(
                draw,
                geom,
                to_scr,
                fill=style["fill"],
                outline=style["outline"],
                width=style["width"],
            )


def is_retained_building(feature: Dict[str, Any]) -> bool:
    return feature.get("properties", {}).get("retained") is True


def finite_number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _same_line_coordinates(a: Any, b: Any, tolerance: float = 1e-6) -> bool:
    if not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple)) or len(a) != len(b):
        return False
    forward = all(
        len(pa) >= 2 and len(pb) >= 2 and abs(float(pa[0]) - float(pb[0])) <= tolerance and abs(float(pa[1]) - float(pb[1])) <= tolerance
        for pa, pb in zip(a, b)
    )
    if forward:
        return True
    return all(
        len(pa) >= 2 and len(pb) >= 2 and abs(float(pa[0]) - float(pb[0])) <= tolerance and abs(float(pa[1]) - float(pb[1])) <= tolerance
        for pa, pb in zip(a, reversed(b))
    )


def features_from_syntax_result(result: Dict[str, Any], new_street_ids: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """Normalize a full scenario-syntax result into segment features without inventing null deltas."""
    before_segments = result.get("before", {}).get("segments", [])
    after_segments = result.get("after", {}).get("segments", [])
    before_by_id = {str(segment.get("id")): segment for segment in before_segments if segment.get("id") is not None}
    after_ids = {str(segment.get("id")) for segment in after_segments if segment.get("id") is not None}
    features: List[Dict[str, Any]] = []
    matched_before_ids = set()

    for segment in after_segments:
        coordinates = segment.get("coordinates")
        if not coordinates:
            continue
        segment_id = str(segment.get("id", ""))
        old = before_by_id.get(segment_id)
        same_geometry = bool(old) and _same_line_coordinates(coordinates, old.get("coordinates"))
        if same_geometry:
            matched_before_ids.add(segment_id)
            status = "MATCHED_GEOMETRY"
            before_value = finite_number(old.get("nain"))
            after_value = finite_number(segment.get("nain"))
            delta_value = after_value - before_value if before_value is not None and after_value is not None else None
        else:
            status = "NEW_OR_CHANGED_GEOMETRY"
            before_value = None
            after_value = finite_number(segment.get("nain"))
            delta_value = None
        source_line_id = str(segment.get("source_line_id") or "")
        source_base_id = source_line_id.removeprefix("proposal:").split(":part:", 1)[0]
        is_new_street = source_base_id in (new_street_ids or set())
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coordinates},
            "properties": {
                "segment_id": segment_id,
                "source_line_id": segment.get("source_line_id"),
                "render_phase": "after",
                "comparison_status": status,
                "is_new_street": is_new_street,
                "before_nain": before_value,
                "after_nain": after_value,
                "delta_nain": delta_value,
                "inside_site": segment.get("inside_site"),
            },
        })

    for segment in before_segments:
        segment_id = str(segment.get("id", ""))
        if segment_id in matched_before_ids or segment_id in after_ids or not segment.get("coordinates"):
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": segment["coordinates"]},
            "properties": {
                "segment_id": segment_id,
                "source_line_id": segment.get("source_line_id"),
                "render_phase": "before",
                "comparison_status": "REMOVED",
                "is_new_street": False,
                "before_nain": finite_number(segment.get("nain")),
                "after_nain": None,
                "delta_nain": None,
                "inside_site": segment.get("inside_site"),
            },
        })
    return features


# Colors & Styles
LANDUSE_COLORS = {
    "waterfront": ("#cbe3db", "#99c4b7"),
    "parks": ("#d2e5ca", "#a3c896"),
    "blocks": ("#eee9e0", "#d6cfc2"),
    "service": ("#ebe0d2", "#cbbca9"),
    "retained_buildings": ("#ded9d0", "#b9b2a7"),
    "roads": ("#f4f1eb", "#e2ded6"),
}

HEIGHT_TIERS = [
    (0.0, 7.0, "#c6bea9", "#8b826b", "低層（1–2層，<= 7m）"),
    (7.0001, 12.0, "#aa9b85", "#70614c", "中低層（3–4層，7–12m）"),
    (12.0001, 18.0, "#8e7862", "#584733", "中高層（5層，12–18m）"),
    (18.0001, 999.0, "#5b6b72", "#354247", "高層／特殊保留設施（> 18m）"),
]

ROAD_STYLES = {
    "primary_street": ("#c0392b", 9, "主要街道（18 m）"),
    "city_connector": ("#d35400", 6, "城市聯絡道（14–16m）"),
    "canal_bridge": ("#e67e22", 6, "運河橋梁"),
    "cross_street": ("#5c6b73", 4, "橫向街道（12–14m）"),
    "block_edge_street": ("#7f8c8d", 4, "街廓邊界街（10–12m）"),
    "waterfront_path": ("#16a085", 4, "水岸步道／親水動線"),
    "waterfront_detour": ("#1abc9c", 4, "水岸繞行徑"),
    "other": ("#bdc3c7", 2, "服務／院落內部通道"),
}


def get_building_height(b: Dict[str, Any]) -> float:
    props = b.get("properties", {})
    h = props.get("height_m")
    if h is not None:
        try:
            return float(h)
        except (ValueError, TypeError):
            pass
    src = props.get("source_record", {})
    h = src.get("height_above_ground_m")
    if h is not None:
        try:
            return float(h)
        except (ValueError, TypeError):
            pass
    fl = props.get("floors")
    if fl is not None:
        try:
            return float(fl) * 3.5
        except (ValueError, TypeError):
            pass
    return 0.0


def get_building_tier(height: float) -> Tuple[str, str, str]:
    if height <= 0.05:
        return "#dedcd8", "#b5b1a8", "已拆除／基底足跡"
    for low, high, fill, stroke, label in HEIGHT_TIERS:
        if low <= height <= high:
            return fill, stroke, label
    return HEIGHT_TIERS[-1][2], HEIGHT_TIERS[-1][3], HEIGHT_TIERS[-1][4]


def draw_polygon_coords(draw: ImageDraw.ImageDraw, coords: Sequence[Tuple[float, float]], fill: Optional[str] = None, outline: Optional[str] = None, width: int = 1) -> None:
    if len(coords) < 3:
        return
    if fill:
        draw.polygon(coords, fill=fill)
    if outline and width > 0:
        if width == 1:
            draw.polygon(coords, outline=outline)
        else:
            draw.line(list(coords) + [coords[0]], fill=outline, width=width)


def draw_shapely_geom(draw: ImageDraw.ImageDraw, geom: Any, to_scr: Any, fill: Optional[str] = None, outline: Optional[str] = None, width: int = 1) -> None:
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, MultiPolygon):
        for poly in geom.geoms:
            draw_shapely_geom(draw, poly, to_scr, fill=fill, outline=outline, width=width)
    elif isinstance(geom, Polygon):
        ext_coords = [to_scr(x, y) for x, y in geom.exterior.coords]
        draw_polygon_coords(draw, ext_coords, fill=fill, outline=outline, width=width)
        if fill:
            for interior in geom.interiors:
                hole_coords = [to_scr(x, y) for x, y in interior.coords]
                draw_polygon_coords(draw, hole_coords, fill="#f8f7f4", outline=outline, width=width)
    elif isinstance(geom, MultiLineString):
        for line in geom.geoms:
            draw_shapely_geom(draw, line, to_scr, outline=outline, width=width)
    elif isinstance(geom, LineString):
        pts = [to_scr(x, y) for x, y in geom.coords]
        if len(pts) >= 2:
            draw.line(pts, fill=outline or "#000000", width=width)


def draw_north_arrow(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 60) -> None:
    top = (cx, cy - size)
    bottom = (cx, cy + size // 2)
    left = (cx - size // 3, cy + size // 3)
    right = (cx + size // 3, cy + size // 3)
    center = (cx, cy)
    # Left half dark
    draw.polygon([top, left, center], fill="#2c3e50")
    # Right half light
    draw.polygon([top, right, center], fill="#bdc3c7")
    draw.polygon([top, left, bottom, right], outline="#1a252f", width=2)
    font = get_font(22)
    bbox = draw.textbbox((0, 0), "北", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - size - th - 8), "北", font=font, fill="#1a252f")


def draw_scale_bar(draw: ImageDraw.ImageDraw, x: int, y: int, scale_px_per_m: float, bar_meters: int = 200) -> None:
    font = get_font(20)
    bar_px = int(bar_meters * scale_px_per_m)
    h = 10
    half_px = bar_px // 2
    # Two segment alternating black & white
    draw.rectangle([x, y, x + half_px, y + h], fill="#2c3e50", outline="#1a252f", width=1)
    draw.rectangle([x + half_px, y, x + bar_px, y + h], fill="#ffffff", outline="#1a252f", width=1)
    draw.line([(x, y - 5), (x, y + h + 5)], fill="#1a252f", width=2)
    draw.line([(x + half_px, y - 5), (x + half_px, y + h + 5)], fill="#1a252f", width=2)
    draw.line([(x + bar_px, y - 5), (x + bar_px, y + h + 5)], fill="#1a252f", width=2)

    draw.text((x - 8, y + h + 8), "0", font=font, fill="#1a252f")
    draw.text((x + half_px - 14, y + h + 8), f"{bar_meters // 2}", font=font, fill="#1a252f")
    draw.text((x + bar_px - 20, y + h + 8), f"{bar_meters} m", font=font, fill="#1a252f")


def create_base_canvas(
    width: int = 3600,
    height: int = 2700,
    title: str = "",
    subtitle: str = "",
    fabric_key: str = "",
    plan_hash: str = "",
    notice_line: Optional[str] = None,
) -> Tuple[Image.Image, ImageDraw.ImageDraw, Tuple[int, int, int, int]]:
    img = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(img)

    # Frame border
    draw.rectangle([40, 40, width - 40, height - 40], outline="#d0cec7", width=2)

    # Header section
    font_main = get_font(44)
    font_sub = get_font(28)
    font_badge = get_font(26)
    font_meta = get_font(22)

    fabric_zh = FABRIC_NAMES_ZH.get(fabric_key, fabric_key)
    draw.text((70, 65), f"Rotterdam M4H 港區活化 ｜ {title}", font=font_main, fill="#1e272e")
    draw.text((70, 125), f"方案名稱：{fabric_zh} ｜ {subtitle}", font=font_sub, fill="#485460")

    # Exploratory draft stamp
    stamp_text = "【 探索性草案 · 供方案比對用 】"
    s_bbox = draw.textbbox((0, 0), stamp_text, font=font_badge)
    s_w = s_bbox[2] - s_bbox[0]
    stamp_x = width - 70 - s_w - 20
    draw.rounded_rectangle([stamp_x, 60, width - 70, 110], radius=6, fill="#fdf0ed", outline="#d63031", width=2)
    draw.text((stamp_x + 10, 68), stamp_text, font=font_badge, fill="#d63031")

    # Metadata top right
    ver_text = f"資料版本：sha256:{plan_hash[:8]} ｜ 單位：公尺 (m) ｜ 坐標：EPSG:28992"
    draw.text((width - 70 - draw.textbbox((0, 0), ver_text, font=font_meta)[2], 125), ver_text, font=font_meta, fill="#7f8c8d")

    if notice_line:
        font_notice = get_font(22)
        draw.text((70, 162), f"說明：{notice_line}", font=font_notice, fill="#2c3e50")
        draw.line([(70, 196), (width - 70, 196)], fill="#e0ded8", width=2)
        vp = (70, 210, 2800, 2370)
    else:
        # Separator
        draw.line([(70, 175), (width - 70, 175)], fill="#e0ded8", width=2)
        # Map viewport: Left side (70 to 2850), Y (200 to 2580)
        vp = (70, 200, 2800, 2380)
    return img, draw, vp


# ==============================================================================
# Figure 1: Massing Plan
# ==============================================================================
def render_massing_plan(
    plan: Dict[str, Any],
    bounds: Tuple[float, float, float, float],
    fabric_key: str,
    plan_hash: str,
    context_layers: Dict[str, List[Any]],
) -> Image.Image:
    img, draw, vp = create_base_canvas(
        width=3600,
        height=2700,
        title="量體平面圖",
        subtitle="土地使用色塊、建築高度分級與道路層級系統",
        fabric_key=fabric_key,
        plan_hash=plan_hash,
    )
    vx, vy, vw, vh = vp
    minx, miny, maxx, maxy = bounds
    scale = min((vw - 40) / (maxx - minx), (vh - 40) / (maxy - miny))
    dx = 20 + (vw - 40 - (maxx - minx) * scale) / 2
    dy = 20 + (vh - 40 - (maxy - miny) * scale) / 2

    def to_vp(x: float, y: float) -> Tuple[float, float]:
        return (dx + (x - minx) * scale, dy + (maxy - y) * scale)

    # Separate viewport image for clean pixel clipping
    vp_img = Image.new("RGBA", (vw, vh), "#fbfaf7")
    vp_draw = ImageDraw.Draw(vp_img)

    # Surrounding context is intentionally subdued and sits beneath the proposal.
    draw_context_layers(vp_draw, context_layers, to_vp)

    # 1. Base site boundary
    if "site" in plan:
        site_geom = shape(plan["site"])
        draw_shapely_geom(vp_draw, site_geom, to_vp, fill="#f5f3ee", outline="#95a5a6", width=2)

    # 2. Water
    if "water" in plan:
        water_geom = shape(plan["water"])
        draw_shapely_geom(vp_draw, water_geom, to_vp, fill="#d4e8f1", outline="#8fb8cf", width=2)

    # 3. Land use patches
    for lu in plan.get("land_use", []):
        cat = lu.get("properties", {}).get("category")
        if cat in LANDUSE_COLORS:
            fill_c, stroke_c = LANDUSE_COLORS[cat]
            draw_shapely_geom(vp_draw, shape(lu["geometry"]), to_vp, fill=fill_c, outline=stroke_c, width=1)

    # 4. Blocks
    for blk in plan.get("blocks", []):
        draw_shapely_geom(vp_draw, shape(blk["geometry"]), to_vp, fill=None, outline="#b2bec3", width=1)

    # 5. Roads (lower hierarchy first, primary street last)
    roads = plan.get("roads", [])
    primary_roads = []
    for r in roads:
        role = r.get("properties", {}).get("role", "other")
        if role == "primary_street":
            primary_roads.append(r)
            continue
        style = ROAD_STYLES.get(role, ROAD_STYLES["other"])
        draw_shapely_geom(vp_draw, shape(r["geometry"]), to_vp, outline=style[0], width=max(1, int(style[1] * scale * 0.4)))

    for r in primary_roads:
        style = ROAD_STYLES["primary_street"]
        draw_shapely_geom(vp_draw, shape(r["geometry"]), to_vp, outline=style[0], width=max(4, int(style[1] * scale * 0.45)))

    # 6. Buildings by height tier
    buildings = plan.get("buildings", [])
    for b in buildings:
        h = get_building_height(b)
        fill_c, stroke_c, _ = get_building_tier(h)
        draw_shapely_geom(vp_draw, shape(b["geometry"]), to_vp, fill=fill_c, outline=stroke_c, width=1)

    # Paste viewport onto master canvas
    img.paste(vp_img, (vx, vy))
    draw.rectangle([vx, vy, vx + vw, vy + vh], outline="#e2dfd8", width=1)

    # 7. Sidebar (Legend & Info)
    sb_x = vx + vw + 40
    sb_y = vy + 20
    f_sec = get_font(26)
    f_lbl = get_font(21)
    f_sub = get_font(18)

    draw.text((sb_x, sb_y), "【 圖例 】", font=f_sec, fill="#1e272e")
    curr_y = sb_y + 45

    # Land use legend
    draw.text((sb_x, curr_y), "土地使用分區", font=f_sub, fill="#7f8c8d")
    curr_y += 30
    lu_names = [
        ("waterfront", "水岸親水廊道"),
        ("parks", "公園綠地／開放空間"),
        ("blocks", "標準建築街廓"),
        ("service", "公共／服務設施"),
        ("retained_buildings", "歷史建物保留用地"),
    ]
    for cat, name in lu_names:
        fill_c, stroke_c = LANDUSE_COLORS[cat]
        draw.rectangle([sb_x, curr_y, sb_x + 36, curr_y + 22], fill=fill_c, outline=stroke_c, width=1)
        draw.text((sb_x + 48, curr_y), name, font=f_lbl, fill="#2c3e50")
        curr_y += 34

    curr_y += 15
    # Building height tiers
    draw.text((sb_x, curr_y), "建築量體高度分級", font=f_sub, fill="#7f8c8d")
    curr_y += 30
    for _, _, fill_c, stroke_c, label in HEIGHT_TIERS:
        draw.rectangle([sb_x, curr_y, sb_x + 36, curr_y + 22], fill=fill_c, outline=stroke_c, width=1)
        draw.text((sb_x + 48, curr_y), label, font=f_lbl, fill="#2c3e50")
        curr_y += 34

    curr_y += 15
    # Road hierarchy
    draw.text((sb_x, curr_y), "道路路網階層", font=f_sub, fill="#7f8c8d")
    curr_y += 30
    road_items = [
        ("primary_street", "主要街道（18 m）"),
        ("city_connector", "城市聯絡道（14–16m）"),
        ("canal_bridge", "跨運河橋梁"),
        ("cross_street", "橫向街道（12–14m）"),
        ("block_edge_street", "街廓邊界街（10–12m）"),
        ("waterfront_path", "水岸步道／自行車徑"),
        ("other", "街區內部服務巷道"),
    ]
    for role, label in road_items:
        color, _, _ = ROAD_STYLES[role]
        draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill=color, width=4)
        draw.text((sb_x + 48, curr_y), label, font=f_lbl, fill="#2c3e50")
        curr_y += 34

    # North arrow and scale bar
    draw_north_arrow(draw, vx + vw - 100, vy + 120, size=55)
    draw_scale_bar(draw, vx + 60, vy + vh - 60, scale_px_per_m=scale, bar_meters=200)

    # Metrics summary in sidebar bottom
    curr_y = vy + vh - 220
    draw.text((sb_x, curr_y), "【 方案指標摘要 】", font=f_sec, fill="#1e272e")
    curr_y += 40
    metrics = plan.get("metrics", {})
    gfa = metrics.get("new_gfa_m2")
    gfa_str = f"{gfa:,.0f} 平方公尺" if gfa is not None else "未提供"
    b_count = len(buildings)
    draw.text((sb_x, curr_y), f"• 新建總樓地板面積：{gfa_str}", font=f_lbl, fill="#34495e")
    curr_y += 30
    draw.text((sb_x, curr_y), f"• 建築量體棟數：{b_count} 棟", font=f_lbl, fill="#34495e")
    curr_y += 30
    draw.text((sb_x, curr_y), f"• 街廓單元數：{len(plan.get('blocks', []))} 個", font=f_lbl, fill="#34495e")

    return img


def render_existing_site(
    plan: Dict[str, Any],
    context_layers: Dict[str, List[Any]],
    bounds: Tuple[float, float, float, float],
    fabric_key: str,
    plan_hash: str,
) -> Image.Image:
    """Render the shared-range existing-site context and explicitly retained buildings."""
    img, draw, vp = create_base_canvas(
        title="基地現況圖",
        subtitle="脈絡建築、道路、水體、基地邊界與保留建物",
        fabric_key=fabric_key,
        plan_hash=plan_hash,
    )
    vx, vy, vw, vh = vp
    minx, miny, maxx, maxy = bounds
    scale = min((vw - 40) / (maxx - minx), (vh - 40) / (maxy - miny))
    dx = 20 + (vw - 40 - (maxx - minx) * scale) / 2
    dy = 20 + (vh - 40 - (maxy - miny) * scale) / 2

    def to_vp(x: float, y: float) -> Tuple[float, float]:
        return (dx + (x - minx) * scale, dy + (maxy - y) * scale)

    vp_img = Image.new("RGBA", (vw, vh), "#fbfaf7")
    vp_draw = ImageDraw.Draw(vp_img)
    draw_context_layers(vp_draw, context_layers, to_vp)

    if "site" in plan:
        draw_shapely_geom(vp_draw, shape(plan["site"]), to_vp, outline="#9b2c2c", width=5)
    retained = [b for b in plan.get("buildings", []) if is_retained_building(b)]
    for building in retained:
        draw_shapely_geom(
            vp_draw,
            shape(building["geometry"]),
            to_vp,
            fill="#8f6b57",
            outline="#543b2f",
            width=2,
        )

    img.paste(vp_img, (vx, vy))
    draw.rectangle([vx, vy, vx + vw, vy + vh], outline="#e2dfd8", width=1)

    sb_x = vx + vw + 40
    curr_y = vy + 20
    draw.text((sb_x, curr_y), "【 圖例 】", font=get_font(26), fill="#1e272e")
    curr_y += 48
    for color, label in [
        ("#e5e6e4", "脈絡建築（高度未編碼）"),
        ("#b9c0c2", "脈絡道路"),
        ("#e6ecee", "脈絡水體"),
        ("#9b2c2c", "基地邊界"),
        ("#8f6b57", f"保留建物（{len(retained)} 棟）"),
    ]:
        if color in ("#b9c0c2", "#9b2c2c"):
            draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill=color, width=5)
        else:
            draw.rectangle([sb_x, curr_y, sb_x + 36, curr_y + 22], fill=color, outline="#9b9b97", width=1)
        draw.text((sb_x + 48, curr_y), label, font=get_font(21), fill="#2c3e50")
        curr_y += 38

    draw.text((sb_x, curr_y + 24), "資料範圍：四案基地聯集外擴 120 m", font=get_font(20), fill="#34495e")
    draw.text((sb_x, curr_y + 60), "脈絡底圖：OSM 建物足跡與道路、水體", font=get_font(18), fill="#7f8c8d")
    draw_north_arrow(draw, vx + vw - 100, vy + 120, size=55)
    draw_scale_bar(draw, vx + 60, vy + vh - 60, scale_px_per_m=scale, bar_meters=200)
    return img


# ==============================================================================
# Figure 2: Axonometric View
# ==============================================================================
def render_axonometric(plan: Dict[str, Any], bounds: Tuple[float, float, float, float], fabric_key: str, plan_hash: str) -> Image.Image:
    img, draw, vp = create_base_canvas(
        width=3600,
        height=2700,
        title="等角鳥瞰圖",
        subtitle="建築量體依資料高度擠出 ｜ 四案共用視框與比例",
        fabric_key=fabric_key,
        plan_hash=plan_hash,
    )
    vx, vy, vw, vh = vp
    minx, miny, maxx, maxy = bounds
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0

    # Axonometric projection angles
    # A fixed south-facing 10 degree azimuth keeps the long harbor frontage
    # legible in the isometric projection while preserving the shared scale.
    theta = math.radians(10)
    phi = math.radians(30)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    cos_p, sin_p = math.cos(phi), math.sin(phi)

    # View vector (from camera looking at origin)
    Vx = -sin_t * cos_p
    Vy = -cos_t * cos_p
    Vz = -sin_p

    # Sun vector for architectural shading (from SW, elevation ~45)
    sun = np.array([-0.5, -0.6, 0.7])
    sun = sun / np.linalg.norm(sun)

    def project_3d(x: float, y: float, z: float) -> Tuple[float, float, float]:
        xr = x - cx
        yr = y - cy
        u = xr * cos_t - yr * sin_t
        v = (xr * sin_t + yr * cos_t) * sin_p + z * cos_p
        depth = (xr * sin_t + yr * cos_t) * cos_p - z * sin_p
        return u, v, depth

    # Use one four-site union frame with a small, consistent margin. Plan views
    # retain their wider 120 m context extent; this view omits that extra
    # whitespace so the volumes remain legible.
    site_geom = shape(plan["site"]) if "site" in plan else Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)])
    frame_inset = MAP_EXTENT_BUFFER_M - AXONOMETRIC_VIEW_MARGIN_M
    s_minx, s_miny, s_maxx, s_maxy = (
        minx + frame_inset,
        miny + frame_inset,
        maxx - frame_inset,
        maxy - frame_inset,
    )
    max_height = max((get_building_height(b) for b in plan.get("buildings", [])), default=0.0)
    test_pts = [
        project_3d(s_minx, s_miny, 0), project_3d(s_maxx, s_miny, 0),
        project_3d(s_minx, s_maxy, 0), project_3d(s_maxx, s_maxy, 0),
        project_3d(s_minx, s_miny, max_height), project_3d(s_maxx, s_miny, max_height),
        project_3d(s_minx, s_maxy, max_height), project_3d(s_maxx, s_maxy, max_height),
    ]
    us = [c[0] for c in test_pts]
    vs = [c[1] for c in test_pts]
    span_u = max(us) - min(us)
    span_v = max(vs) - min(vs)
    scale = min((vw - 80) / span_u, (vh - 80) / span_v)

    vp_cx = vw / 2.0
    vp_cy = vh / 2.0 + 30

    def to_vp_3d(x: float, y: float, z: float) -> Tuple[float, float]:
        u, v, _ = project_3d(x, y, z)
        return (vp_cx + u * scale, vp_cy - v * scale)

    # Separate viewport image for clean clipping
    vp_img = Image.new("RGBA", (vw, vh), "#fbfaf7")
    vp_draw = ImageDraw.Draw(vp_img)

    # 1. Ground plane: water & site
    if "site" in plan:
        draw_shapely_geom(vp_draw, site_geom, lambda x, y: to_vp_3d(x, y, 0), fill="#f5f3ee", outline="#bdc3c7", width=2)
    if "water" in plan:
        water_geom = shape(plan["water"])
        draw_shapely_geom(vp_draw, water_geom, lambda x, y: to_vp_3d(x, y, 0), fill="#d4e8f1", outline="#8fb8cf", width=2)

    # Ground land use
    for lu in plan.get("land_use", []):
        cat = lu.get("properties", {}).get("category")
        if cat in ("parks", "waterfront"):
            fill_c, stroke_c = LANDUSE_COLORS[cat]
            draw_shapely_geom(vp_draw, shape(lu["geometry"]), lambda x, y: to_vp_3d(x, y, 0), fill=fill_c, outline=stroke_c, width=1)

    # Ground roads
    for r in plan.get("roads", []):
        role = r.get("properties", {}).get("role", "other")
        color, w, _ = ROAD_STYLES.get(role, ROAD_STYLES["other"])
        draw_shapely_geom(vp_draw, shape(r["geometry"]), lambda x, y: to_vp_3d(x, y, 0), outline=color, width=max(1, int(w * scale * 0.25)))

    # 2. Extrude buildings
    buildings = plan.get("buildings", [])
    building_records = []
    for b in buildings:
        geom = shape(b["geometry"])
        if geom.is_empty:
            continue
        h = get_building_height(b)
        c = geom.centroid
        _, _, depth = project_3d(c.x, c.y, h / 2.0)
        building_records.append((depth, geom, h, b))

    # Sort furthest to nearest
    building_records.sort(key=lambda x: x[0], reverse=True)

    def shade_color(hex_color: str, factor: float) -> str:
        hex_color = hex_color.lstrip("#")
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        r = max(0, min(255, int(r * factor)))
        g = max(0, min(255, int(g * factor)))
        b = max(0, min(255, int(b * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"

    # Painter's algorithm per face (not per building): consistent CCW orientation, outer and
    # courtyard walls, then roofs, all sorted far -> near by their own projected depth.
    from shapely.geometry.polygon import orient as _orient
    faces = []  # (depth, order, points, fill, outline)
    for _, geom, h, b_dict in building_records:
        fill_base, stroke_base, _ = get_building_tier(h)
        polys = [geom] if isinstance(geom, Polygon) else (geom.geoms if isinstance(geom, MultiPolygon) else [])
        for poly in polys:
            poly = _orient(poly, sign=1.0)
            if h <= 0.05:
                pts = [to_vp_3d(x, y, 0) for x, y in poly.exterior.coords]
                c = poly.centroid
                faces.append((project_3d(c.x, c.y, 0)[2], 0, pts, "#dedcd8", "#b5b1a8"))
                continue
            rings = [list(poly.exterior.coords)] + [list(r.coords) for r in poly.interiors]
            for coords in rings:
                for i in range(len(coords) - 1):
                    p0, p1 = coords[i], coords[i + 1]
                    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                    seg_len = math.hypot(dx, dy)
                    if seg_len < 1e-5:
                        continue
                    nx, ny = dy / seg_len, -dx / seg_len  # outward for CCW shell, into courtyard for CW holes
                    # (Vx, Vy) points toward the camera: draw only walls whose normal faces it.
                    if nx * Vx + ny * Vy <= 0:
                        continue
                    k = 0.45 + 0.55 * max(0.0, nx * sun[0] + ny * sun[1])
                    quad = [to_vp_3d(p0[0], p0[1], 0), to_vp_3d(p1[0], p1[1], 0),
                            to_vp_3d(p1[0], p1[1], h), to_vp_3d(p0[0], p0[1], h)]
                    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
                    faces.append((project_3d(mx, my, h / 2.0)[2], 1, quad, shade_color(fill_base, k), shade_color(stroke_base, k)))
            c = poly.representative_point()
            roof = [to_vp_3d(x, y, h) for x, y in poly.exterior.coords]
            holes = [[to_vp_3d(x, y, h) for x, y in r.coords] for r in poly.interiors]
            faces.append((project_3d(c.x, c.y, h)[2], 2, (roof, holes), shade_color(fill_base, 0.90), stroke_base))
    faces.sort(key=lambda f: (f[0], -f[1]), reverse=True)
    for _, kind, pts, fill, outline in faces:
        if kind == 2:
            roof, holes = pts
            draw_polygon_coords(vp_draw, roof, fill=fill, outline=outline, width=1)
            for hole in holes:  # open courtyard: show ground through the roof opening
                draw_polygon_coords(vp_draw, hole, fill="#eae5dc", outline=outline, width=1)
        else:
            draw_polygon_coords(vp_draw, pts, fill=fill, outline=outline, width=1)

    # Paste viewport onto master image
    img.paste(vp_img, (vx, vy))
    draw.rectangle([vx, vy, vx + vw, vy + vh], outline="#e2dfd8", width=1)

    # Sidebar
    sb_x = vx + vw + 40
    sb_y = vy + 20
    draw.text((sb_x, sb_y), "【 圖例 】", font=get_font(26), fill="#1e272e")
    curr_y = sb_y + 45
    draw.text((sb_x, curr_y), "建築量體高度分級", font=get_font(18), fill="#7f8c8d")
    curr_y += 30
    for _, _, fill_c, stroke_c, label in HEIGHT_TIERS:
        draw.rectangle([sb_x, curr_y, sb_x + 36, curr_y + 22], fill=fill_c, outline=stroke_c, width=1)
        draw.text((sb_x + 48, curr_y), label, font=get_font(21), fill="#2c3e50")
        curr_y += 34

    curr_y += 30
    draw.text((sb_x, curr_y), "【 投影參數 】", font=get_font(26), fill="#1e272e")
    curr_y += 45
    draw.text((sb_x, curr_y), "• 視角方位角：10 度（南向斜視）", font=get_font(20), fill="#34495e")
    curr_y += 30
    draw.text((sb_x, curr_y), "• 俯仰角：30 度（等角擠出）", font=get_font(20), fill="#34495e")
    curr_y += 30
    draw.text((sb_x, curr_y), "• 示意光源：西南上方（定向著色）", font=get_font(20), fill="#34495e")
    curr_y += 30
    draw.text((sb_x, curr_y), "• 視框：基地聯集外擴 20 m（四案共用）", font=get_font(20), fill="#34495e")

    draw_north_arrow(draw, vx + vw - 100, vy + 120, size=55)
    return img


# ==============================================================================
# Figure 3: Perspective View
# ==============================================================================
def render_perspective(plan: Dict[str, Any], fabric_key: str, plan_hash: str) -> Image.Image:
    img, draw, vp = create_base_canvas(
        width=3600,
        height=2700,
        title="透視示意圖",
        subtitle="人眼視角：從主要街道西端朝東觀看",
        fabric_key=fabric_key,
        plan_hash=plan_hash,
    )
    vx, vy, vw, vh = vp

    # Derive the camera from this plan's primary street so the same human-scale
    # viewpoint follows the actual geometry rather than a stale hard-coded site.
    primary_roads = [r for r in plan.get("roads", []) if r.get("properties", {}).get("role") == "primary_street"]
    primary_coords = primary_roads[0].get("geometry", {}).get("coordinates", []) if primary_roads else []
    if len(primary_coords) >= 2:
        primary_line = LineString(primary_coords)
        eye_xy = primary_coords[0]
        target_xy = primary_line.interpolate(min(350.0, primary_line.length)).coords[0]
    else:
        site_geom = shape(plan["site"]) if "site" in plan else Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        minx, miny, maxx, maxy = site_geom.bounds
        eye_xy = (minx, (miny + maxy) / 2.0)
        target_xy = (minx + min(350.0, maxx - minx), (miny + maxy) / 2.0)
    eye = np.array([eye_xy[0], eye_xy[1], 1.7])
    target = np.array([target_xy[0], target_xy[1], 1.7])
    D = (target - eye) / np.linalg.norm(target - eye)
    R = np.array([D[1], -D[0], 0.0])
    U = np.array([0.0, 0.0, 1.0])

    # Perspective camera
    fov_deg = 58.0
    fov_rad = math.radians(fov_deg)
    f = (vw / 2.0) / math.tan(fov_rad / 2.0)
    vp_cx = vw / 2.0
    vp_cy = vh / 2.0

    def project_persp(pt_3d: np.ndarray) -> Optional[Tuple[float, float, float]]:
        vec = pt_3d - eye
        zc = float(np.dot(vec, D))
        if zc <= 0.8:
            return None
        xc = float(np.dot(vec, R))
        yc = float(np.dot(vec, U))
        sx = vp_cx + f * (xc / zc)
        sy = vp_cy - f * (yc / zc)
        return sx, sy, zc

    # Separate viewport image for clean pixel clipping
    vp_img = Image.new("RGBA", (vw, vh), "#eef2f5")
    vp_draw = ImageDraw.Draw(vp_img)

    # Ground plane below horizon
    vp_draw.rectangle([0, int(vp_cy), vw, vh], fill="#f2efe9")

    # Perspective street corridor: draw primary road surface
    for r in primary_roads:
        coords = r.get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            road_w = 18.0
            pts_left = []
            pts_right = []
            for c in coords:
                pt = np.array([c[0], c[1], 0.0])
                pl = pt + R * (road_w / 2.0)
                pr = pt - R * (road_w / 2.0)
                spl = project_persp(pl)
                spr = project_persp(pr)
                if spl and spr:
                    pts_left.append((spl[0], spl[1]))
                    pts_right.append((spr[0], spr[1]))
            if len(pts_left) >= 2 and len(pts_right) >= 2:
                poly_scr = pts_left + pts_right[::-1]
                draw_polygon_coords(vp_draw, poly_scr, fill="#e0dbd3", outline="#c5beb4", width=1)

    # Buildings sorted by distance from camera
    buildings = plan.get("buildings", [])
    b_records = []
    for b in buildings:
        geom = shape(b["geometry"])
        if geom.is_empty:
            continue
        c = geom.centroid
        pos = np.array([c.x, c.y, 0.0])
        dist = float(np.dot(pos - eye, D))
        if dist > 2.0:
            h = get_building_height(b)
            b_records.append((dist, geom, h))

    b_records.sort(key=lambda x: x[0], reverse=True)

    sun = np.array([-0.5, -0.6, 0.7])
    sun = sun / np.linalg.norm(sun)

    for dist, geom, h in b_records:
        fill_base, stroke_base, _ = get_building_tier(h)
        polys = [geom] if isinstance(geom, Polygon) else (geom.geoms if isinstance(geom, MultiPolygon) else [])

        for poly in polys:
            from shapely.geometry.polygon import orient as _orient
            poly = _orient(poly, sign=1.0)  # CCW shell so (dy, -dx) is the outward normal
            coords = list(poly.exterior.coords)
            # Walls
            for i in range(len(coords) - 1):
                p0 = np.array([coords[i][0], coords[i][1], 0.0])
                p1 = np.array([coords[i + 1][0], coords[i + 1][1], 0.0])
                p1_top = np.array([coords[i + 1][0], coords[i + 1][1], h])
                p0_top = np.array([coords[i][0], coords[i][1], h])

                dx = p1[0] - p0[0]
                dy = p1[1] - p0[1]
                seg_l = math.hypot(dx, dy)
                if seg_l < 1e-4:
                    continue
                nx, ny = dy / seg_l, -dx / seg_l
                # Visibility from camera:
                vec_to_cam = eye - p0
                dot_vis = nx * vec_to_cam[0] + ny * vec_to_cam[1]
                if dot_vis > 0:
                    s0 = project_persp(p0)
                    s1 = project_persp(p1)
                    s1_t = project_persp(p1_top)
                    s0_t = project_persp(p0_top)
                    if s0 and s1 and s1_t and s0_t:
                        dot_sun = max(0.0, nx * sun[0] + ny * sun[1])
                        k = 0.5 + 0.5 * dot_sun
                        # Shade color
                        hex_c = fill_base.lstrip("#")
                        r = max(0, min(255, int(int(hex_c[0:2], 16) * k)))
                        g = max(0, min(255, int(int(hex_c[2:4], 16) * k)))
                        b = max(0, min(255, int(int(hex_c[4:6], 16) * k)))
                        wall_col = f"#{r:02x}{g:02x}{b:02x}"
                        draw_polygon_coords(vp_draw, [(s0[0], s0[1]), (s1[0], s1[1]), (s1_t[0], s1_t[1]), (s0_t[0], s0_t[1])], fill=wall_col, outline=stroke_base, width=1)

            # Roof
            roof_proj = []
            for c in coords:
                p_top = np.array([c[0], c[1], h])
                sp = project_persp(p_top)
                if sp:
                    roof_proj.append((sp[0], sp[1]))
            if len(roof_proj) >= 3:
                draw_polygon_coords(vp_draw, roof_proj, fill=fill_base, outline=stroke_base, width=1)

    # Restriction and schematic watermark on perspective viewport
    notice_text = "※ 透視示意圖（限制說明：簡化人眼量體透視，未包含細部立面開窗與景觀材質）"
    f_not = get_font(24)
    bbox = vp_draw.textbbox((0, 0), notice_text, font=f_not)
    nw = bbox[2] - bbox[0]
    vp_draw.rounded_rectangle([20, vh - 60, 40 + nw, vh - 15], radius=6, fill="#ffffff", outline="#e67e22", width=2)
    vp_draw.text((30, vh - 52), notice_text, font=f_not, fill="#d35400")

    # Paste viewport onto master image
    img.paste(vp_img, (vx, vy))
    draw.rectangle([vx, vy, vx + vw, vy + vh], outline="#e2dfd8", width=1)

    # Sidebar info
    sb_x = vx + vw + 40
    sb_y = vy + 20
    draw.text((sb_x, sb_y), "【 視點說明 】", font=get_font(26), fill="#1e272e")
    curr_y = sb_y + 45
    draw.text((sb_x, curr_y), "• 站立位置：主要街道西側端點", font=get_font(20), fill="#34495e")
    curr_y += 30
    draw.text((sb_x, curr_y), "• 人眼高度：地面上方 1.7 公尺", font=get_font(20), fill="#34495e")
    curr_y += 30
    draw.text((sb_x, curr_y), "• 凝視方向：朝東南東主街端景", font=get_font(20), fill="#34495e")
    curr_y += 30
    draw.text((sb_x, curr_y), "• 視場角：水平 58 度", font=get_font(20), fill="#34495e")

    curr_y += 50
    draw.text((sb_x, curr_y), "【 量體高度圖例 】", font=get_font(26), fill="#1e272e")
    curr_y += 40
    for _, _, fill_c, stroke_c, label in HEIGHT_TIERS:
        draw.rectangle([sb_x, curr_y, sb_x + 36, curr_y + 22], fill=fill_c, outline=stroke_c, width=1)
        draw.text((sb_x + 48, curr_y), label, font=get_font(21), fill="#2c3e50")
        curr_y += 34

    return img


# ==============================================================================
# Figure 4: Syntax Plans (After & Delta)
# ==============================================================================
SYNTAX_AFTER_COLORS = [
    ("#313695", 2),
    ("#74add1", 3),
    ("#fee090", 4),
    ("#f46d43", 5),
    ("#a50026", 6),
]

SYNTAX_DELTA_COLORS = [
    ("#2b83ba", 5),
    ("#74add1", 3),
    ("#dcdcdc", 2),
    ("#fdae61", 3),
    ("#d7191c", 5),
]


def _format_signed(value: float, digits: int = 3) -> str:
    return f"{value:+.{digits}f}".replace("-", "－")


def render_syntax_figure(
    plan: Dict[str, Any],
    syntax_features: List[Dict[str, Any]],
    bounds: Tuple[float, float, float, float],
    metric_type: str,  # 'after' or 'delta'
    quantiles: List[float],
    fabric_key: str,
    plan_hash: str,
    context_layers: Dict[str, List[Any]],
    available_fabrics: Sequence[str],
) -> Image.Image:
    subtitle = "方案後步行 NAIN（800 m）" if metric_type == "after" else "方案後減方案前 NAIN 差值（800 m）"
    img, draw, vp = create_base_canvas(
        title=f"空間語法分析圖｜{subtitle}",
        subtitle=f"本次可用 {len(available_fabrics)} 案共用色階；四案共用視框",
        fabric_key=fabric_key,
        plan_hash=plan_hash,
    )
    vx, vy, vw, vh = vp
    minx, miny, maxx, maxy = bounds
    scale = min((vw - 40) / (maxx - minx), (vh - 40) / (maxy - miny))
    dx = 20 + (vw - 40 - (maxx - minx) * scale) / 2
    dy = 20 + (vh - 40 - (maxy - miny) * scale) / 2

    def to_vp(x: float, y: float) -> Tuple[float, float]:
        return (dx + (x - minx) * scale, dy + (maxy - y) * scale)

    # Separate viewport image for clean pixel clipping
    vp_img = Image.new("RGBA", (vw, vh), "#fbfaf7")
    vp_draw = ImageDraw.Draw(vp_img)

    # Surrounding buildings, roads and water sit beneath the project data.
    draw_context_layers(vp_draw, context_layers, to_vp)
    if "site" in plan:
        draw_shapely_geom(vp_draw, shape(plan["site"]), to_vp, fill="#f7f5ef", outline="#8c9899", width=2)
    if "water" in plan:
        draw_shapely_geom(vp_draw, shape(plan["water"]), to_vp, fill="#d4e8f1", outline="#8fb8cf", width=2)

    # Subtle building footprints as background reference
    for b in plan.get("buildings", []):
        draw_shapely_geom(vp_draw, shape(b["geometry"]), to_vp, fill="#e8e5dc", outline="#d1cdc2", width=1)

    feature_geometries = [(feature, shape(feature["geometry"])) for feature in syntax_features if feature.get("geometry")]
    prop_key = "after_nain" if metric_type == "after" else "delta_nain"
    feature_geometries.sort(
        key=lambda item: abs(finite_number(item[0].get("properties", {}).get(prop_key)) or 0.0)
    )

    def after_color(value: float) -> Tuple[str, int]:
        for index in range(5):
            if value <= quantiles[index + 1] or index == 4:
                return SYNTAX_AFTER_COLORS[index]
        return SYNTAX_AFTER_COLORS[2]

    def delta_color(value: float) -> Tuple[str, int]:
        if value < quantiles[1]:
            return SYNTAX_DELTA_COLORS[0]
        if value < quantiles[2]:
            return SYNTAX_DELTA_COLORS[1]
        if value <= quantiles[3]:
            return SYNTAX_DELTA_COLORS[2]
        if value <= quantiles[4]:
            return SYNTAX_DELTA_COLORS[3]
        return SYNTAX_DELTA_COLORS[4]

    for feature, geom in feature_geometries:
        props = feature.get("properties", {})
        status = props.get("comparison_status")
        if metric_type == "after":
            value = finite_number(props.get("after_nain"))
            if value is None:
                continue
            color, width = after_color(value)
            if status == "NEW_OR_CHANGED_GEOMETRY":
                width += 4
            draw_shapely_geom(vp_draw, geom, to_vp, outline=color, width=width)
            continue

        value = finite_number(props.get("delta_nain"))
        if status == "NEW_OR_CHANGED_GEOMETRY" and value is None:
            color = "#8e44ad" if props.get("is_new_street") is True else "#9a6b3f"
            draw_shapely_geom(vp_draw, geom, to_vp, outline=color, width=8)
        elif status == "REMOVED" and value is None:
            draw_shapely_geom(vp_draw, geom, to_vp, outline="#5d6668", width=4)
        elif value is not None:
            color, width = delta_color(value)
            draw_shapely_geom(vp_draw, geom, to_vp, outline=color, width=width)

    # Paste viewport onto master image
    img.paste(vp_img, (vx, vy))
    draw.rectangle([vx, vy, vx + vw, vy + vh], outline="#e2dfd8", width=1)

    # Sidebar legend with human-readable numeric boundaries.
    sb_x = vx + vw + 40
    sb_y = vy + 20
    draw.text((sb_x, sb_y), "【 語法圖例 】", font=get_font(26), fill="#1e272e")
    curr_y = sb_y + 48

    if metric_type == "after":
        for i, (color, width) in enumerate(SYNTAX_AFTER_COLORS):
            draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill=color, width=max(3, width))
            low = quantiles[i]
            high = quantiles[i + 1]
            draw.text((sb_x + 48, curr_y), f"{low:.3f} 至 {high:.3f}", font=get_font(19), fill="#2c3e50")
            curr_y += 34
        draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill="#46545a", width=8)
        draw.text((sb_x + 48, curr_y), "加粗：新增／變更路段（含方案後值）", font=get_font(18), fill="#2c3e50")
        curr_y += 42
        draw.text((sb_x, curr_y), "顏色代表步行 NAIN 數值分位區間", font=get_font(18), fill="#7f8c8d")
    else:
        negative_cut = quantiles[1]
        positive_cut = quantiles[4]
        labels = [
            f"{_format_signed(negative_cut)} 以下",
            f"{_format_signed(negative_cut)} 至 －0.001",
            "－0.001 至 +0.001",
            f"+0.001 至 {_format_signed(positive_cut)}",
            f"{_format_signed(positive_cut)} 以上",
        ]
        for (color, width), label in zip(SYNTAX_DELTA_COLORS, labels):
            draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill=color, width=max(3, width))
            draw.text((sb_x + 48, curr_y), label, font=get_font(19), fill="#2c3e50")
            curr_y += 34
        draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill="#8e44ad", width=8)
        draw.text((sb_x + 48, curr_y), "新增路段（無方案前值）", font=get_font(19), fill="#2c3e50")
        curr_y += 34
        draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill="#9a6b3f", width=8)
        draw.text((sb_x + 48, curr_y), "變更路段（無可比方案前值）", font=get_font(18), fill="#2c3e50")
        curr_y += 34
        draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill="#5d6668", width=4)
        draw.text((sb_x + 48, curr_y), "移除路段（無方案後值）", font=get_font(19), fill="#2c3e50")

    curr_y += 45
    draw.text((sb_x, curr_y), "【 分級依據 】", font=get_font(24), fill="#1e272e")
    curr_y += 40
    draw.text((sb_x, curr_y), f"• 可用資料：{len(available_fabrics)} 案", font=get_font(20), fill="#34495e")
    curr_y += 32
    draw.text((sb_x, curr_y), "• 差值只比較相同幾何路段", font=get_font(20), fill="#34495e")
    curr_y += 32
    draw.text((sb_x, curr_y), "• 範圍：四案基地聯集外擴 120 m", font=get_font(20), fill="#34495e")

    draw_north_arrow(draw, vx + vw - 100, vy + 120, size=55)
    draw_scale_bar(draw, vx + 60, vy + vh - 60, scale_px_per_m=scale, bar_meters=200)

    return img


# ==============================================================================
# Figure 4b: Site-Only Syntax Plans (NAIN & NACH for Pedestrian & Bicycle)
# ==============================================================================
SITE_SYNTAX_COLORS = [
    ("#2b83ba", 4),  # Level 1: Cool blue
    ("#74add1", 6),  # Level 2: Light blue
    ("#fee08b", 8),  # Level 3: Warm yellow
    ("#f46d43", 11),  # Level 4: Vivid orange
    ("#a50026", 14),  # Level 5: Crimson red
]


def get_site_segments(
    features: List[Dict[str, Any]],
    site_geom: Any,
    buffer_m: float = 10.0,
) -> List[Tuple[Dict[str, Any], Any]]:
    """Clip post-intervention routes inside site (including entrance connectors crossing boundary, buffered +10 m)."""
    site_buff = site_geom.buffer(buffer_m)
    site_segments: List[Tuple[Dict[str, Any], Any]] = []
    for f in features:
        props = f.get("properties", {})
        if props.get("render_phase") == "before":
            continue
        geom_doc = f.get("geometry")
        if not geom_doc:
            continue
        geom = shape(geom_doc)
        if geom.is_empty:
            continue
        is_candidate = (
            (props.get("inside_site") is True)
            or geom.intersects(site_geom)
            or (props.get("road_role") == "entrance_connector")
        )
        if is_candidate and geom.intersects(site_buff):
            clipped = geom.intersection(site_buff)
            if not clipped.is_empty:
                site_segments.append((f, clipped))
    return site_segments


def compute_site_quantiles(
    site_values: Sequence[float],
    all_values: Sequence[float],
) -> Tuple[List[float], List[float]]:
    """Compute 5-quantile breaks for site segments and their equivalent percentiles in the full network."""
    if not site_values:
        return [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
    arr_site = np.asarray(site_values, dtype=float)
    breaks = [float(x) for x in np.quantile(arr_site, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])]
    for i in range(1, len(breaks)):
        if breaks[i] < breaks[i - 1]:
            breaks[i] = breaks[i - 1]

    if all_values:
        arr_all = np.asarray(all_values, dtype=float)
        p_equiv = [float(np.mean(arr_all <= val) * 100.0) for val in breaks]
    else:
        p_equiv = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
    return [round(b, 4) for b in breaks], [round(p, 1) for p in p_equiv]


def find_top_segments(
    site_segments: List[Tuple[Dict[str, Any], Any]],
    metric_key: str,
    limit: int = 5,
    min_dist_m: float = 40.0,
) -> List[Tuple[int, Dict[str, Any], Any, float]]:
    """Find top N segments by metric value, enforcing minimum distance between centroids to avoid badge crowding."""
    valid_items = []
    for f, g in site_segments:
        p = f.get("properties", {})
        val = finite_number(p.get(f"after_{metric_key}")) if p.get(f"after_{metric_key}") is not None else finite_number(p.get(metric_key))
        if val is not None:
            valid_items.append((val, f, g))
    valid_items.sort(key=lambda item: item[0], reverse=True)

    chosen = []
    for val, f, g in valid_items:
        c = g.centroid
        if any(c.distance(cf[2].centroid) < min_dist_m for cf in chosen):
            continue
        chosen.append((len(chosen) + 1, f, g, val))
        if len(chosen) >= limit:
            break
    return chosen


def render_site_syntax_figure(
    plan: Dict[str, Any],
    site_segments: List[Tuple[Dict[str, Any], Any]],
    all_features: List[Dict[str, Any]],
    bounds: Tuple[float, float, float, float],
    metric_key: str,  # "nain" or "nach"
    mode: str,        # "pedestrian" or "bicycle"
    quantiles: List[float],
    network_percentiles: List[float],
    fabric_key: str,
    plan_hash: str,
    context_layers: Dict[str, List[Any]],
) -> Image.Image:
    mode_zh = "步行（800 m）" if mode == "pedestrian" else "自行車（2 km）"
    metric_zh = "NAIN 整合度" if metric_key == "nain" else "NACH 選擇度"
    meaning_zh = "到達便利性" if metric_key == "nain" else "穿越潛力"
    notice_text = "NAIN＝整合度（到達便利性）；NACH＝選擇度（穿越潛力）；色階以基地內路段分級"

    title = f"基地內空間語法分析圖｜{mode_zh} {metric_zh}"
    subtitle = f"{meaning_zh} ｜ 僅著色基地內路段（裁切至基地＋10 m）；五級色階以基地內路段分位數分級"

    img, draw, vp = create_base_canvas(
        title=title,
        subtitle=subtitle,
        fabric_key=fabric_key,
        plan_hash=plan_hash,
        notice_line=notice_text,
    )
    vx, vy, vw, vh = vp
    minx, miny, maxx, maxy = bounds
    scale = min((vw - 40) / (maxx - minx), (vh - 40) / (maxy - miny))
    dx = 20 + (vw - 40 - (maxx - minx) * scale) / 2
    dy = 20 + (vh - 40 - (maxy - miny) * scale) / 2

    def to_vp(x: float, y: float) -> Tuple[float, float]:
        return (dx + (x - minx) * scale, dy + (maxy - y) * scale)

    vp_img = Image.new("RGBA", (vw, vh), "#fcfbf8")
    vp_draw = ImageDraw.Draw(vp_img)

    # 1. Base map: faint context layers
    draw_context_layers(vp_draw, context_layers, to_vp, faint_roads=True)
    site_geom = shape(plan["site"]) if "site" in plan else None
    if site_geom:
        draw_shapely_geom(vp_draw, site_geom, to_vp, fill="#fcfbf8", outline="#7f8c8d", width=2)
    if "water" in plan:
        draw_shapely_geom(vp_draw, shape(plan["water"]), to_vp, fill="#d4e8f1", outline="#8fb8cf", width=2)

    # Subtle plan buildings
    for b in plan.get("buildings", []):
        draw_shapely_geom(vp_draw, shape(b["geometry"]), to_vp, fill="#e8e5dc", outline="#d1cdc2", width=1)

    # 2. Draw site segments sorted by value ascending (so highest values are drawn on top)
    def get_val(f_dict: Dict[str, Any]) -> Optional[float]:
        p = f_dict.get("properties", {})
        return finite_number(p.get(f"after_{metric_key}")) if p.get(f"after_{metric_key}") is not None else finite_number(p.get(metric_key))

    def get_level(v: float) -> int:
        for idx in range(5):
            if v <= quantiles[idx + 1] or idx == 4:
                return idx
        return 0

    sorted_segments = []
    for f, g in site_segments:
        val = get_val(f)
        if val is not None:
            sorted_segments.append((val, f, g))
    sorted_segments.sort(key=lambda x: x[0])

    for val, f, g in sorted_segments:
        lvl = get_level(val)
        color, width = SITE_SYNTAX_COLORS[lvl]
        draw_shapely_geom(vp_draw, g, to_vp, outline=color, width=width)

    # 3. Highlight annotations: Primary street and Waterfront path
    primary_segs = [g for f, g in site_segments if f.get("properties", {}).get("road_role") == "primary_street"]
    if primary_segs:
        best_prim = max(primary_segs, key=lambda g: g.length)
        c = best_prim.centroid
        px, py = to_vp(c.x, c.y)
        font_badge = get_font(20)
        p_txt = "★ 主要街道（18 m）"
        bb = vp_draw.textbbox((0, 0), p_txt, font=font_badge)
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        bx1, by1 = px - bw // 2 - 8, py - 36 - bh // 2 - 4
        bx2, by2 = px + bw // 2 + 8, py - 36 + bh // 2 + 4
        vp_draw.rounded_rectangle([bx1, by1, bx2, by2], radius=5, fill="#fdf0ed", outline="#c0392b", width=2)
        vp_draw.text((bx1 + 8, by1 + 4), p_txt, font=font_badge, fill="#c0392b")

    wf_segs = [g for f, g in site_segments if "waterfront" in str(f.get("properties", {}).get("road_role")) and g.length > 20.0]
    if wf_segs:
        best_wf = max(wf_segs, key=lambda g: g.length)
        c = best_wf.centroid
        wx, wy = to_vp(c.x, c.y)
        font_badge = get_font(20)
        w_txt = "★ 水岸步道"
        bb = vp_draw.textbbox((0, 0), w_txt, font=font_badge)
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        bx1, by1 = wx - bw // 2 - 8, wy - 32 - bh // 2 - 4
        bx2, by2 = wx + bw // 2 + 8, wy - 32 + bh // 2 + 4
        vp_draw.rounded_rectangle([bx1, by1, bx2, by2], radius=5, fill="#e8f8f5", outline="#16a085", width=2)
        vp_draw.text((bx1 + 8, by1 + 4), w_txt, font=font_badge, fill="#16a085")

    # 4. Top 5 Segments numbered 1-5
    top_5 = find_top_segments(site_segments, metric_key, limit=5, min_dist_m=50.0)
    for rank, f, g, val in top_5:
        c = g.centroid
        sx, sy = to_vp(c.x, c.y)
        r = 20
        vp_draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill="#1e272e", outline="#ffffff", width=2)
        f_num = get_font(22)
        n_txt = str(rank)
        nb = vp_draw.textbbox((0, 0), n_txt, font=f_num)
        nw, nh = nb[2] - nb[0], nb[3] - nb[1]
        vp_draw.text((sx - nw // 2, sy - nh // 2 - 2), n_txt, font=f_num, fill="#ffffff")

    # Paste viewport onto master canvas
    img.paste(vp_img, (vx, vy))
    draw.rectangle([vx, vy, vx + vw, vy + vh], outline="#e2dfd8", width=1)

    # 5. Sidebar Legend (X: vx + vw + 40 to width - 70)
    sb_x = vx + vw + 40
    sb_y = vy + 20
    draw.text((sb_x, sb_y), "【 基地內語法圖例 】", font=get_font(26), fill="#1e272e")
    curr_y = sb_y + 44
    draw.text((sb_x, curr_y), "基地內 5 級分位數色階（低冷高暖）", font=get_font(18), fill="#7f8c8d")
    curr_y += 32

    for i in range(5):
        color, width = SITE_SYNTAX_COLORS[i]
        draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill=color, width=width)
        low = quantiles[i]
        high = quantiles[i + 1]
        p_low = round(network_percentiles[i])
        p_high = round(network_percentiles[i + 1])
        pct_label = f"全網 P{p_low}–P{p_high}" if p_low != p_high else f"全網 P{p_low}"
        range_str = f"{low:.3f} 至 {high:.3f}（{pct_label}）"
        draw.text((sb_x + 48, curr_y), range_str, font=get_font(18), fill="#2c3e50")
        curr_y += 34

    curr_y += 20
    draw.text((sb_x, curr_y), "【 重要標記 】", font=get_font(24), fill="#1e272e")
    curr_y += 36

    draw.rounded_rectangle([sb_x, curr_y, sb_x + 28, curr_y + 20], radius=4, fill="#fdf0ed", outline="#c0392b", width=1)
    draw.text((sb_x + 38, curr_y - 2), "主要街道（primary_street，18 m）", font=get_font(18), fill="#2c3e50")
    curr_y += 30

    draw.rounded_rectangle([sb_x, curr_y, sb_x + 28, curr_y + 20], radius=4, fill="#e8f8f5", outline="#16a085", width=1)
    draw.text((sb_x + 38, curr_y - 2), "水岸步道／親水動線（waterfront）", font=get_font(18), fill="#2c3e50")
    curr_y += 30

    draw.ellipse([sb_x + 4, curr_y, sb_x + 24, curr_y + 20], fill="#1e272e", outline="#ffffff", width=1)
    draw.text((sb_x + 10, curr_y - 1), "★", font=get_font(16), fill="#ffffff")
    draw.text((sb_x + 38, curr_y - 2), "①–⑤ 基地內前 5 名高權重路段", font=get_font(18), fill="#2c3e50")
    curr_y += 40

    draw.text((sb_x, curr_y), f"【 前 5 名路段清單（{metric_zh}）】", font=get_font(22), fill="#1e272e")
    curr_y += 32
    if top_5:
        circ_nums = ["①", "②", "③", "④", "⑤"]
        for rank, f, g, val in top_5:
            p = f.get("properties", {})
            r_name = p.get("name") or p.get("road_role") or p.get("road_id") or p.get("source_line_id") or "新設路段"
            r_label = ROAD_STYLES.get(r_name, (None, 0, r_name))[2] if r_name in ROAD_STYLES else r_name
            draw.text((sb_x, curr_y), f"{circ_nums[rank - 1]} {r_label}：{val:.3f}", font=get_font(18), fill="#2c3e50")
            curr_y += 28
    else:
        draw.text((sb_x, curr_y), "無可用路段數值", font=get_font(18), fill="#7f8c8d")
        curr_y += 28

    curr_y += 25
    draw.text((sb_x, curr_y), "【 指標說明 】", font=get_font(22), fill="#1e272e")
    curr_y += 30
    draw.text((sb_x, curr_y), "• NAIN＝整合度（到達便利性）", font=get_font(18), fill="#34495e")
    curr_y += 26
    draw.text((sb_x, curr_y), "• NACH＝選擇度（穿越潛力）", font=get_font(18), fill="#34495e")
    curr_y += 26
    draw.text((sb_x, curr_y), "• 色階以基地內路段分位數分級", font=get_font(18), fill="#34495e")
    curr_y += 26
    draw.text((sb_x, curr_y), "• 括號標註為該級距對照全網百分位", font=get_font(18), fill="#34495e")
    curr_y += 26
    draw.text((sb_x, curr_y), "• 範圍：基地幾何外擴 10 m 裁切", font=get_font(18), fill="#34495e")

    draw_north_arrow(draw, vx + vw - 100, vy + 120, size=55)
    draw_scale_bar(draw, vx + 60, vy + vh - 60, scale_px_per_m=scale, bar_meters=200)

    draw.text(
        (70, img.height - 50),
        "說明：NAIN＝整合度（到達便利性）；NACH＝選擇度（穿越潛力）；色階以基地內路段分級。四案共用同視框與比例尺。",
        font=get_font(19),
        fill="#7f8c8d",
    )
    return img


def render_site_syntax_comparison_board(
    plans: Dict[str, Dict[str, Any]],
    syntax_features_map: Dict[str, List[Dict[str, Any]]],
    bounds: Tuple[float, float, float, float],
    plan_hashes: Dict[str, str],
    context_layers: Dict[str, List[Any]],
) -> Tuple[Image.Image, List[float], List[float]]:
    width = 4800
    height = 3600
    img = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(img)

    draw.rectangle([40, 40, width - 40, height - 40], outline="#d0cec7", width=2)

    font_main = get_font(52)
    font_sub = get_font(28)
    font_notice = get_font(24)
    font_badge = get_font(28)
    font_meta = get_font(24)

    draw.text((70, 65), "Rotterdam M4H 港區活化草案 ｜ 四案基地內步行空間語法（NAIN）並排比較", font=font_main, fill="#1e272e")
    draw.text((70, 130), "同範圍（四案基地聯集外擴 120 m）、同比例尺、四案共用同一色階（四案基地內路段合併分位數）", font=font_sub, fill="#485460")
    draw.text((70, 168), "說明：NAIN＝整合度（到達便利性）；NACH＝選擇度（穿越潛力）；色階以基地內路段分級", font=font_notice, fill="#2c3e50")

    stamp_text = "【 探索性草案 · 正式比對版面 】"
    s_bbox = draw.textbbox((0, 0), stamp_text, font=font_badge)
    s_w = s_bbox[2] - s_bbox[0]
    stamp_x = width - 70 - s_w - 20
    draw.rounded_rectangle([stamp_x, 65, width - 70, 120], radius=6, fill="#fdf0ed", outline="#d63031", width=2)
    draw.text((stamp_x + 10, 75), stamp_text, font=font_badge, fill="#d63031")

    meta_str = "坐標系統：EPSG:28992 ｜ 單位：公尺 (m) ｜ 解析度：300 DPI"
    draw.text((width - 70 - draw.textbbox((0, 0), meta_str, font=font_meta)[2], 135), meta_str, font=font_meta, fill="#7f8c8d")

    draw.line([(70, 205), (width - 70, 205)], fill="#e0ded8", width=2)

    all_site_nain_vals: List[float] = []
    all_net_nain_vals: List[float] = []
    site_segments_by_fab: Dict[str, List[Tuple[Dict[str, Any], Any]]] = {}

    for fab in FABRICS:
        plan = plans.get(fab)
        feats = syntax_features_map.get(fab, [])
        for f in feats:
            p = f.get("properties", {})
            val = finite_number(p.get("after_nain")) if p.get("after_nain") is not None else finite_number(p.get("nain"))
            if val is not None:
                all_net_nain_vals.append(val)
        if plan and feats:
            site_geom = shape(plan["site"])
            segs = get_site_segments(feats, site_geom)
            site_segments_by_fab[fab] = segs
            for f, g in segs:
                p = f.get("properties", {})
                val = finite_number(p.get("after_nain")) if p.get("after_nain") is not None else finite_number(p.get("nain"))
                if val is not None:
                    all_site_nain_vals.append(val)
        else:
            site_segments_by_fab[fab] = []

    combined_breaks, combined_pcts = compute_site_quantiles(all_site_nain_vals, all_net_nain_vals)

    gw = 3880
    gh = 3120
    panel_w = (gw - 40) // 2
    panel_h = (gh - 40) // 2

    grid_slots = [
        ("harbour_grain", 70, 225),
        ("closed_block_extension", 70 + panel_w + 40, 225),
        ("courtyard_islands", 70, 225 + panel_h + 40),
        ("landscape_figure", 70 + panel_w + 40, 225 + panel_h + 40),
    ]

    minx, miny, maxx, maxy = bounds
    scale = min((panel_w - 30) / (maxx - minx), (panel_h - 75) / (maxy - miny))

    def get_level(v: float) -> int:
        for idx in range(5):
            if v <= combined_breaks[idx + 1] or idx == 4:
                return idx
        return 0

    for fab_key, px, py in grid_slots:
        plan = plans.get(fab_key)
        if not plan:
            continue
        fab_zh = FABRIC_NAMES_ZH.get(fab_key, fab_key)
        segs = site_segments_by_fab.get(fab_key, [])

        panel_img = Image.new("RGBA", (panel_w, panel_h), "#fcfbf8")
        p_draw = ImageDraw.Draw(panel_img)

        p_draw.rectangle([0, 0, panel_w, 55], fill="#f0ece4")
        p_draw.text((20, 12), f"{fab_zh} ｜ 基地內步行 NAIN", font=get_font(24), fill="#2c3e50")

        nain_vals = [
            finite_number(f.get("properties", {}).get("after_nain"))
            for f, _ in segs
            if finite_number(f.get("properties", {}).get("after_nain")) is not None
        ]
        mean_str = f"平均: {np.mean(nain_vals):.3f}" if nain_vals else "無數值"
        max_str = f"最高: {np.max(nain_vals):.3f}" if nain_vals else ""
        p_draw.text((panel_w - 420, 14), f"路段: {len(segs)} ｜ {mean_str} ｜ {max_str}", font=get_font(19), fill="#576574")

        dx = 15 + (panel_w - 30 - (maxx - minx) * scale) / 2
        dy = 65 + (panel_h - 75 - (maxy - miny) * scale) / 2

        def to_panel(x: float, y: float) -> Tuple[float, float]:
            return (dx + (x - minx) * scale, dy + (maxy - y) * scale)

        draw_context_layers(p_draw, context_layers, to_panel, faint_roads=True)

        if "site" in plan:
            draw_shapely_geom(p_draw, shape(plan["site"]), to_panel, fill="#fcfbf8", outline="#95a5a6", width=1)
        if "water" in plan:
            draw_shapely_geom(p_draw, shape(plan["water"]), to_panel, fill="#d4e8f1", outline="#8fb8cf", width=1)

        for b in plan.get("buildings", []):
            draw_shapely_geom(p_draw, shape(b["geometry"]), to_panel, fill="#e8e5dc", outline="#d1cdc2", width=1)

        sorted_segs = []
        for f, g in segs:
            p = f.get("properties", {})
            v = finite_number(p.get("after_nain")) if p.get("after_nain") is not None else finite_number(p.get("nain"))
            if v is not None:
                sorted_segs.append((v, f, g))
        sorted_segs.sort(key=lambda x: x[0])

        for val, f, g in sorted_segs:
            lvl = get_level(val)
            color, width_line = SITE_SYNTAX_COLORS[lvl]
            draw_shapely_geom(p_draw, g, to_panel, outline=color, width=max(2, width_line - 1))

        top_5 = find_top_segments(segs, "nain", limit=5, min_dist_m=50.0)
        for rank, f, g, val in top_5:
            c = g.centroid
            sx, sy = to_panel(c.x, c.y)
            r = 16
            p_draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill="#1e272e", outline="#ffffff", width=2)
            f_num = get_font(18)
            n_txt = str(rank)
            nb = p_draw.textbbox((0, 0), n_txt, font=f_num)
            nw, nh = nb[2] - nb[0], nb[3] - nb[1]
            p_draw.text((sx - nw // 2, sy - nh // 2 - 2), n_txt, font=f_num, fill="#ffffff")

        prim_segs = [g for f, g in segs if f.get("properties", {}).get("road_role") == "primary_street"]
        if prim_segs:
            best_prim = max(prim_segs, key=lambda g: g.length)
            px_c, py_c = to_panel(best_prim.centroid.x, best_prim.centroid.y)
            f_bd = get_font(16)
            p_txt = "主街 (18m)"
            bb = p_draw.textbbox((0, 0), p_txt, font=f_bd)
            bw, bh = bb[2] - bb[0], bb[3] - bb[1]
            p_draw.rounded_rectangle([px_c - bw // 2 - 5, py_c - 25 - bh // 2 - 2, px_c + bw // 2 + 5, py_c - 25 + bh // 2 + 2], radius=4, fill="#fdf0ed", outline="#c0392b", width=1)
            p_draw.text((px_c - bw // 2, py_c - 25 - bh // 2 - 1), p_txt, font=f_bd, fill="#c0392b")

        img.paste(panel_img, (px, py))
        draw.rectangle([px, py, px + panel_w, py + panel_h], outline="#dcd8cf", width=2)

    sb_x = 4010
    sb_y = 230
    draw.text((sb_x, sb_y), "【 綜合圖例 】", font=get_font(28), fill="#1e272e")
    curr_y = sb_y + 45
    draw.text((sb_x, curr_y), "四案共用 5 級分位數色階（低冷高暖）", font=get_font(18), fill="#7f8c8d")
    curr_y += 32

    for i in range(5):
        color, width_line = SITE_SYNTAX_COLORS[i]
        draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill=color, width=width_line)
        low = combined_breaks[i]
        high = combined_breaks[i + 1]
        p_low = round(combined_pcts[i])
        p_high = round(combined_pcts[i + 1])
        pct_label = f"全網 P{p_low}–P{p_high}" if p_low != p_high else f"全網 P{p_low}"
        range_str = f"{low:.3f} 至 {high:.3f}（{pct_label}）"
        draw.text((sb_x + 48, curr_y), range_str, font=get_font(19), fill="#2c3e50")
        curr_y += 34

    curr_y += 30
    draw.text((sb_x, curr_y), "【 標註說明 】", font=get_font(24), fill="#1e272e")
    curr_y += 36
    draw.rounded_rectangle([sb_x, curr_y, sb_x + 28, curr_y + 20], radius=4, fill="#fdf0ed", outline="#c0392b", width=1)
    draw.text((sb_x + 38, curr_y - 2), "主要街道（primary_street，18 m）", font=get_font(18), fill="#2c3e50")
    curr_y += 30
    draw.rounded_rectangle([sb_x, curr_y, sb_x + 28, curr_y + 20], radius=4, fill="#e8f8f5", outline="#16a085", width=1)
    draw.text((sb_x + 38, curr_y - 2), "水岸步道／親水動線（waterfront）", font=get_font(18), fill="#2c3e50")
    curr_y += 30
    draw.ellipse([sb_x + 4, curr_y, sb_x + 24, curr_y + 20], fill="#1e272e", outline="#ffffff", width=1)
    draw.text((sb_x + 10, curr_y - 1), "★", font=get_font(16), fill="#ffffff")
    draw.text((sb_x + 38, curr_y - 2), "①–⑤ 各案前 5 名高權重路段", font=get_font(18), fill="#2c3e50")
    curr_y += 40

    draw.text((sb_x, curr_y), "【 指標說明 】", font=get_font(24), fill="#1e272e")
    curr_y += 32
    draw.text((sb_x, curr_y), "• NAIN＝整合度（到達便利性）", font=get_font(18), fill="#34495e")
    curr_y += 28
    draw.text((sb_x, curr_y), "• NACH＝選擇度（穿越潛力）", font=get_font(18), fill="#34495e")
    curr_y += 28
    draw.text((sb_x, curr_y), "• 色階以四案基地內路段合併分位數分級", font=get_font(18), fill="#34495e")
    curr_y += 28
    draw.text((sb_x, curr_y), "• 括號標註為該級距對照全網百分位", font=get_font(18), fill="#34495e")
    curr_y += 28
    draw.text((sb_x, curr_y), "• 範圍：基地幾何外擴 10 m 裁切", font=get_font(18), fill="#34495e")

    curr_y += 40
    draw_north_arrow(draw, sb_x + 120, curr_y + 60, size=55)
    draw_scale_bar(draw, sb_x, curr_y + 170, scale_px_per_m=scale, bar_meters=200)

    draw.text(
        (70, height - 70),
        "說明：四案均使用 EPSG:28992 同一空間範圍與比例尺；色階採用四案基地內步行路段合併五分位數。",
        font=get_font(20),
        fill="#7f8c8d",
    )
    return img, combined_breaks, combined_pcts


# ==============================================================================
# Figure 5: 4-Scheme Comparison Overview Board
# ==============================================================================
def render_comparison_board(
    plans: Dict[str, Dict[str, Any]],
    bounds: Tuple[float, float, float, float],
    plan_hashes: Dict[str, str],
    context_layers: Dict[str, List[Any]],
) -> Image.Image:
    width = 4800
    height = 3600
    img = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(img)

    # Frame
    draw.rectangle([40, 40, width - 40, height - 40], outline="#d0cec7", width=2)

    # Master Header
    font_main = get_font(52)
    font_sub = get_font(30)
    font_badge = get_font(28)
    font_meta = get_font(24)

    draw.text((70, 70), "Rotterdam M4H 港區活化草案｜四案量體平面並排比較", font=font_main, fill="#1e272e")
    draw.text((70, 140), "同範圍（四案基地聯集外擴 120 m）、同比例尺、同高度分級色階", font=font_sub, fill="#485460")

    # Exploratory draft stamp
    stamp_text = "【 探索性草案 · 正式比對版面 】"
    s_bbox = draw.textbbox((0, 0), stamp_text, font=font_badge)
    s_w = s_bbox[2] - s_bbox[0]
    stamp_x = width - 70 - s_w - 20
    draw.rounded_rectangle([stamp_x, 65, width - 70, 120], radius=6, fill="#fdf0ed", outline="#d63031", width=2)
    draw.text((stamp_x + 10, 75), stamp_text, font=font_badge, fill="#d63031")

    meta_str = "坐標系統：EPSG:28992 ｜ 單位：公尺 (m) ｜ 解析度：300 DPI"
    draw.text((width - 70 - draw.textbbox((0, 0), meta_str, font=font_meta)[2], 140), meta_str, font=font_meta, fill="#7f8c8d")

    draw.line([(70, 195), (width - 70, 195)], fill="#e0ded8", width=2)

    # 2x2 Grid Layout
    gw = 3880
    gh = 3130
    panel_w = (gw - 40) // 2
    panel_h = (gh - 40) // 2

    grid_slots = [
        ("harbour_grain", 70, 220),
        ("closed_block_extension", 70 + panel_w + 40, 220),
        ("courtyard_islands", 70, 220 + panel_h + 40),
        ("landscape_figure", 70 + panel_w + 40, 220 + panel_h + 40),
    ]

    minx, miny, maxx, maxy = bounds
    scale = min((panel_w - 30) / (maxx - minx), (panel_h - 70) / (maxy - miny))

    for fab_key, px, py in grid_slots:
        plan = plans.get(fab_key)
        if not plan:
            continue
        p_hash = plan_hashes.get(fab_key, "unknown")
        fab_zh = FABRIC_NAMES_ZH.get(fab_key, fab_key)

        # Panel canvas
        panel_img = Image.new("RGBA", (panel_w, panel_h), "#fbfaf7")
        p_draw = ImageDraw.Draw(panel_img)

        # Panel title bar
        p_draw.rectangle([0, 0, panel_w, 55], fill="#f0ece4")
        p_draw.text((20, 12), fab_zh, font=get_font(26), fill="#2c3e50")
        p_draw.text((panel_w - 240, 16), f"資料版本：{p_hash[:8]}", font=get_font(20), fill="#7f8c8d")

        dx = 15 + (panel_w - 30 - (maxx - minx) * scale) / 2
        dy = 65 + (panel_h - 75 - (maxy - miny) * scale) / 2

        def to_panel(x: float, y: float) -> Tuple[float, float]:
            return (dx + (x - minx) * scale, dy + (maxy - y) * scale)

        draw_context_layers(p_draw, context_layers, to_panel)

        # Base site
        if "site" in plan:
            draw_shapely_geom(p_draw, shape(plan["site"]), to_panel, fill="#f5f3ee", outline="#95a5a6", width=1)
        if "water" in plan:
            draw_shapely_geom(p_draw, shape(plan["water"]), to_panel, fill="#d4e8f1", outline="#8fb8cf", width=1)

        # Land use
        for lu in plan.get("land_use", []):
            cat = lu.get("properties", {}).get("category")
            if cat in LANDUSE_COLORS:
                fill_c, stroke_c = LANDUSE_COLORS[cat]
                draw_shapely_geom(p_draw, shape(lu["geometry"]), to_panel, fill=fill_c, outline=stroke_c, width=1)

        # Roads
        roads = plan.get("roads", [])
        for r in roads:
            role = r.get("properties", {}).get("role", "other")
            if role == "primary_street":
                continue
            color, _, _ = ROAD_STYLES.get(role, ROAD_STYLES["other"])
            draw_shapely_geom(p_draw, shape(r["geometry"]), to_panel, outline=color, width=1)
        for r in roads:
            if r.get("properties", {}).get("role") == "primary_street":
                draw_shapely_geom(p_draw, shape(r["geometry"]), to_panel, outline="#c0392b", width=3)

        # Buildings
        buildings = plan.get("buildings", [])
        for b in buildings:
            h = get_building_height(b)
            fill_c, stroke_c, _ = get_building_tier(h)
            draw_shapely_geom(p_draw, shape(b["geometry"]), to_panel, fill=fill_c, outline=stroke_c, width=1)

        # Panel metric badge
        metrics = plan.get("metrics", {})
        gfa = metrics.get("new_gfa_m2")
        gfa_str = f"新建樓地板面積：{gfa:,.0f} 平方公尺" if gfa else "新建樓地板面積：未提供"
        p_draw.text((20, panel_h - 35), f"{gfa_str} ｜ 量體數: {len(buildings)} 棟", font=get_font(20), fill="#34495e")

        # Paste panel
        img.paste(panel_img, (px, py))
        draw.rectangle([px, py, px + panel_w, py + panel_h], outline="#dcd8cf", width=2)

    # Master Sidebar (X: 4000 to 4730)
    sb_x = 4010
    sb_y = 230
    draw.text((sb_x, sb_y), "【 綜合圖例 】", font=get_font(28), fill="#1e272e")
    curr_y = sb_y + 50

    draw.text((sb_x, curr_y), "土地使用分區", font=get_font(20), fill="#7f8c8d")
    curr_y += 32
    for cat, name in [
        ("waterfront", "水岸親水廊道"),
        ("parks", "公園綠地／開放空間"),
        ("blocks", "標準建築街廓"),
        ("service", "公共／服務設施"),
        ("retained_buildings", "歷史建物保留用地"),
    ]:
        fill_c, stroke_c = LANDUSE_COLORS[cat]
        draw.rectangle([sb_x, curr_y, sb_x + 36, curr_y + 22], fill=fill_c, outline=stroke_c, width=1)
        draw.text((sb_x + 48, curr_y), name, font=get_font(21), fill="#2c3e50")
        curr_y += 34

    curr_y += 20
    draw.text((sb_x, curr_y), "建築高度分級", font=get_font(20), fill="#7f8c8d")
    curr_y += 32
    for _, _, fill_c, stroke_c, label in HEIGHT_TIERS:
        draw.rectangle([sb_x, curr_y, sb_x + 36, curr_y + 22], fill=fill_c, outline=stroke_c, width=1)
        draw.text((sb_x + 48, curr_y), label, font=get_font(21), fill="#2c3e50")
        curr_y += 34

    curr_y += 20
    draw.text((sb_x, curr_y), "道路路網階層", font=get_font(20), fill="#7f8c8d")
    curr_y += 32
    for role, label in [
        ("primary_street", "主要街道（18m）"),
        ("city_connector", "城市聯絡道（14–16m）"),
        ("cross_street", "次要橫向街（12–14m）"),
        ("waterfront_path", "水岸步道動線"),
    ]:
        color, _, _ = ROAD_STYLES[role]
        draw.line([(sb_x, curr_y + 11), (sb_x + 36, curr_y + 11)], fill=color, width=4)
        draw.text((sb_x + 48, curr_y), label, font=get_font(21), fill="#2c3e50")
        curr_y += 34

    # Scale and North Arrow
    curr_y += 50
    draw_north_arrow(draw, sb_x + 120, curr_y + 60, size=55)
    draw_scale_bar(draw, sb_x, curr_y + 170, scale_px_per_m=scale, bar_meters=200)

    # Footer note
    draw.text(
        (70, height - 70),
        "說明：四案均使用 EPSG:28992 同一空間範圍與比例尺，供設計比對。",
        font=get_font(20),
        fill="#7f8c8d",
    )

    return img


# ==============================================================================
# Main Runner & Manifest Builder
# ==============================================================================
def load_syntax_source(syntax_dir: Path, fabric: str, mode: str = "pedestrian") -> Tuple[Optional[List[Dict[str, Any]]], List[Path], Dict[str, Any]]:
    """Read a pedestrian or bicycle GeoJSON or a summary that pins its complete result JSON."""
    geojson_candidates = [
        syntax_dir / "segments" / f"{fabric}-{mode}.geojson",
        syntax_dir / f"{fabric}-{mode}.geojson",
    ]
    for path in geojson_candidates:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        crs_name = payload.get("crs", {}).get("properties", {}).get("name")
        if crs_name and crs_name.upper() != "EPSG:28992":
            return None, [path], {"status": "MISSING", "reason": f"輸入 CRS 不符：{crs_name}", "candidate": str(path)}
        features = payload.get("features", [])
        if features:
            return features, [path], {"status": "AVAILABLE", "resolution": "GeoJSON", "path": str(path), "feature_count": len(features), "crs": crs_name or "EPSG:28992"}

    summary_path = syntax_dir / f"{fabric}-{mode}.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        reference = summary.get("complete_intermediate") or {}
        intermediate_value = reference.get("path")
        intermediate_path = Path(intermediate_value) if intermediate_value else None
        if not intermediate_path or not intermediate_path.is_file():
            return None, [summary_path], {"status": "MISSING", "reason": "完整中間結果不存在", "summary": str(summary_path), "intermediate": intermediate_value}
        actual_hash = sha256_file(intermediate_path)
        expected_hash = str(reference.get("sha256", "")).removeprefix("sha256:")
        if expected_hash and actual_hash != expected_hash:
            return None, [summary_path, intermediate_path], {"status": "MISSING", "reason": "完整中間結果 SHA-256 不符", "summary": str(summary_path), "intermediate": str(intermediate_path), "expected_sha256": expected_hash, "actual_sha256": actual_hash}
        result = json.loads(intermediate_path.read_text(encoding="utf-8"))
        crs = result.get("parameters", {}).get("crs")
        if crs and str(crs).upper() != "EPSG:28992":
            return None, [summary_path, intermediate_path], {"status": "MISSING", "reason": f"中間結果 CRS 不符：{crs}", "summary": str(summary_path), "intermediate": str(intermediate_path)}
        ranking_ids = {
            str(item.get("road_id"))
            for item in summary.get("new_street_ranking", [])
            if item.get("road_id") is not None
        }
        features = features_from_syntax_result(result, ranking_ids)
        if features:
            return features, [summary_path, intermediate_path], {
                "status": "AVAILABLE",
                "resolution": "完整中間結果 JSON",
                "summary_path": str(summary_path),
                "intermediate_path": str(intermediate_path),
                "intermediate_sha256": actual_hash,
                "feature_count": len(features),
                "crs": crs or "EPSG:28992",
                "feature_normalization": "同 ID 且幾何容差 1e-6 m 才計算方案前後差值；新增或變更幾何的差值保留為空值。",
            }

    mode_zh = "步行" if mode == "pedestrian" else "自行車"
    expected = [str(path) for path in geojson_candidates] + [str(summary_path)]
    return None, [], {"status": "MISSING", "reason": f"指定輸入目錄無可用{mode_zh}路段資料", "searched_candidates": expected}


def _syntax_quantiles(features_by_fabric: Dict[str, List[Dict[str, Any]]]) -> Tuple[Dict[str, List[float]], List[str]]:
    after_values: List[float] = []
    delta_values: List[float] = []
    available_fabrics: List[str] = []
    for fabric, features in features_by_fabric.items():
        fabric_after = [finite_number(f.get("properties", {}).get("after_nain")) for f in features]
        valid_after = [value for value in fabric_after if value is not None]
        if valid_after:
            available_fabrics.append(fabric)
            after_values.extend(valid_after)
        delta_values.extend(
            value for value in (finite_number(f.get("properties", {}).get("delta_nain")) for f in features) if value is not None
        )

    after_breaks = [float(x) for x in np.quantile(after_values, [0.0, .2, .4, .6, .8, 1.0])] if after_values else [0, .55, .7, .82, .95, 3.2]
    if delta_values:
        arr = np.asarray(delta_values, dtype=float)
        negatives = arr[arr < -0.001]
        positives = arr[arr > 0.001]
        neg_cut = float(np.percentile(negatives, 25)) if len(negatives) else -0.02
        pos_cut = float(np.percentile(positives, 75)) if len(positives) else 0.02
        delta_breaks = [
            min(float(arr.min()), neg_cut, -0.001),
            min(neg_cut, -0.001),
            -0.001,
            0.001,
            max(pos_cut, 0.001),
            max(float(arr.max()), pos_cut, 0.001),
        ]
    else:
        delta_breaks = [-0.05, -0.02, -0.001, 0.001, 0.02, 0.05]
    return {
        "after_nain": [round(x, 4) for x in after_breaks],
        "delta_nain": [round(x, 4) for x in delta_breaks],
    }, available_fabrics


def run_export(
    plans_dir: Path,
    syntax_dir: Path,
    output_dir: Path,
    run_label: str,
    overwrite: bool = True,
) -> Dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 1. Load plans
    plans: Dict[str, Dict[str, Any]] = {}
    plan_paths: Dict[str, Path] = {}
    plan_hashes: Dict[str, str] = {}

    for fab in FABRICS:
        p = plans_dir / f"{fab}-plan.json"
        if p.is_file():
            plan = json.loads(p.read_text(encoding="utf-8"))
            if str(plan.get("crs", "")).upper() != "EPSG:28992":
                raise ValueError(f"Unsupported or missing plan CRS in {p}: {plan.get('crs')!r}")
            plans[fab] = plan
            plan_paths[fab] = p
            plan_hashes[fab] = sha256_file(p)
        else:
            print(f"[WARN] Plan file not found: {p}", file=sys.stderr)

    if not plans:
        raise FileNotFoundError(f"No plan JSON files found in {plans_dir}")

    # 2. The same union of the four planned sites, buffered by 120 m, is used
    # for every spatial figure.
    bounds = compute_union_buffered_bounds(plans, buffer_m=MAP_EXTENT_BUFFER_M)
    context_layers, context_manifest, context_source_paths = load_context_layers(bounds)

    # 3. Resolve syntax inputs pinned by the requested input directory for pedestrian and bicycle.
    pedestrian_features_map: Dict[str, List[Dict[str, Any]]] = {}
    pedestrian_source_paths: Dict[str, List[Path]] = {}
    pedestrian_resolution: Dict[str, Dict[str, Any]] = {}

    bicycle_features_map: Dict[str, List[Dict[str, Any]]] = {}
    bicycle_source_paths: Dict[str, List[Path]] = {}
    bicycle_resolution: Dict[str, Dict[str, Any]] = {}

    for fab in FABRICS:
        p_feats, p_srcs, p_det = load_syntax_source(syntax_dir, fab, mode="pedestrian")
        pedestrian_resolution[fab] = p_det
        if p_feats:
            pedestrian_features_map[fab] = p_feats
            pedestrian_source_paths[fab] = p_srcs

        b_feats, b_srcs, b_det = load_syntax_source(syntax_dir, fab, mode="bicycle")
        bicycle_resolution[fab] = b_det
        if b_feats:
            bicycle_features_map[fab] = b_feats
            bicycle_source_paths[fab] = b_srcs

    syntax_features_map = pedestrian_features_map
    syntax_source_paths = pedestrian_source_paths
    syntax_resolution = pedestrian_resolution
    syntax_quantiles, syntax_scale_fabrics = _syntax_quantiles(syntax_features_map)
    manifest_figures: List[Dict[str, Any]] = []
    site_syntax_scales: Dict[str, Any] = {}

    def register_figure(
        filename: str,
        img: Image.Image,
        fig_type: str,
        fabric: str,
        sources: List[Path],
        class_breaks: Optional[List[float]] = None,
        network_percentiles: Optional[List[float]] = None,
    ) -> None:
        out_p = output_dir / filename
        img.save(out_p, dpi=(OUTPUT_DPI, OUTPUT_DPI))
        f_hash = sha256_file(out_p)
        existing_sources = [source for source in sources if source.is_file()]
        fig_doc: Dict[str, Any] = {
            "filename": filename,
            "type": fig_type,
            "fabric": fabric,
            "fabric_zh": FABRIC_NAMES_ZH.get(fabric, fabric),
            "pixel_dimensions": [img.width, img.height],
            "dpi": OUTPUT_DPI,
            "sha256": f_hash,
            "source_files": [
                {"path": str(s), "sha256": sha256_file(s)} for s in existing_sources
            ],
            "method_version": METHOD_VERSION,
            "generated_at": generated_at,
            "status": "GENERATED",
        }
        if class_breaks is not None:
            fig_doc["class_breaks"] = class_breaks
        if network_percentiles is not None:
            fig_doc["network_percentiles"] = network_percentiles
        manifest_figures.append(fig_doc)
        print(f"[OK] Generated {filename} ({img.width}x{img.height}, sha256: {f_hash[:8]})")

    def register_missing(filename: str, fig_type: str, fabric: str, details: Dict[str, Any], sources: List[Path]) -> None:
        existing_sources = [source for source in sources if source.is_file()]
        manifest_figures.append({
            "filename": filename,
            "type": fig_type,
            "fabric": fabric,
            "fabric_zh": FABRIC_NAMES_ZH.get(fabric, fabric),
            "status": "MISSING",
            "reason": details.get("reason", "沒有可用的對應來源資料"),
            "source_files": [
                {"path": str(source), "sha256": sha256_file(source)} for source in existing_sources
            ],
            "search_details": details,
            "generated_at": generated_at,
            "method_version": METHOD_VERSION,
        })
        print(f"[INFO] {filename}: MISSING — {details.get('reason', '沒有可用資料')}")

    # Render per fabric
    for fab in FABRICS:
        if fab not in plans:
            continue
        plan = plans[fab]
        p_path = plan_paths[fab]
        p_hash = plan_hashes[fab]

        context_figure_sources = [p_path, *context_source_paths]

        # 1. Massing plan with pale context beneath the proposal.
        img_massing = render_massing_plan(plan, bounds, fab, p_hash, context_layers)
        register_figure(f"{fab}-massing.png", img_massing, "massing_plan", fab, context_figure_sources)

        # 2. Existing site and preserved buildings.
        img_existing = render_existing_site(plan, context_layers, bounds, fab, p_hash)
        register_figure(f"{fab}-existing-site.png", img_existing, "existing_site", fab, context_figure_sources)

        # 3. Axonometric
        img_axon = render_axonometric(plan, bounds, fab, p_hash)
        register_figure(f"{fab}-axonometric.png", img_axon, "axonometric_view", fab, [p_path])

        # 4. Perspective
        img_persp = render_perspective(plan, fab, p_hash)
        register_figure(f"{fab}-perspective.png", img_persp, "perspective_schematic", fab, [p_path])

        # 5. Syntax figures (full network After & Delta)
        if fab in syntax_features_map:
            s_sources = syntax_source_paths[fab]
            s_feats = syntax_features_map[fab]
            all_syntax_sources = [p_path, *s_sources, *context_source_paths]

            img_after = render_syntax_figure(
                plan, s_feats, bounds, "after", syntax_quantiles["after_nain"], fab, p_hash,
                context_layers, syntax_scale_fabrics,
            )
            register_figure(f"{fab}-syntax-after.png", img_after, "syntax_after_nain", fab, all_syntax_sources)

            img_delta = render_syntax_figure(
                plan, s_feats, bounds, "delta", syntax_quantiles["delta_nain"], fab, p_hash,
                context_layers, syntax_scale_fabrics,
            )
            register_figure(f"{fab}-syntax-delta.png", img_delta, "syntax_delta_nain", fab, all_syntax_sources)
        else:
            details = syntax_resolution.get(fab, {"reason": "指定輸入目錄無可用步行路段資料"})
            missing_sources = [Path(p) for p in details.get("searched_candidates", []) if Path(p).is_file()]
            for s_type, s_name in [("syntax_after_nain", f"{fab}-syntax-after.png"), ("syntax_delta_nain", f"{fab}-syntax-delta.png")]:
                register_missing(s_name, s_type, fab, details, missing_sources)

        # 6. Site-only Syntax Figures (NAIN & NACH for Pedestrian & Bicycle)
        site_geom = shape(plan["site"]) if "site" in plan else None
        for mode in ("pedestrian", "bicycle"):
            f_map = pedestrian_features_map if mode == "pedestrian" else bicycle_features_map
            s_map = pedestrian_source_paths if mode == "pedestrian" else bicycle_source_paths
            r_map = pedestrian_resolution if mode == "pedestrian" else bicycle_resolution

            if fab in f_map and site_geom:
                all_mode_feats = f_map[fab]
                s_sources = s_map[fab]
                site_segs = get_site_segments(all_mode_feats, site_geom)
                all_site_sources = [p_path, *s_sources, *context_source_paths]

                for metric_key in ("nain", "nach"):
                    site_vals = []
                    for f, _ in site_segs:
                        v = finite_number(f.get("properties", {}).get(f"after_{metric_key}")) if f.get("properties", {}).get(f"after_{metric_key}") is not None else finite_number(f.get("properties", {}).get(metric_key))
                        if v is not None:
                            site_vals.append(v)

                    net_vals = []
                    for f in all_mode_feats:
                        v = finite_number(f.get("properties", {}).get(f"after_{metric_key}")) if f.get("properties", {}).get(f"after_{metric_key}") is not None else finite_number(f.get("properties", {}).get(metric_key))
                        if v is not None:
                            net_vals.append(v)

                    breaks, pcts = compute_site_quantiles(site_vals, net_vals)
                    site_syntax_scales.setdefault(fab, {}).setdefault(mode, {})[metric_key] = {
                        "breaks": breaks,
                        "network_percentiles": pcts,
                        "site_segment_count": len(site_segs),
                        "valid_value_count": len(site_vals),
                    }

                    img_site = render_site_syntax_figure(
                        plan=plan,
                        site_segments=site_segs,
                        all_features=all_mode_feats,
                        bounds=bounds,
                        metric_key=metric_key,
                        mode=mode,
                        quantiles=breaks,
                        network_percentiles=pcts,
                        fabric_key=fab,
                        plan_hash=p_hash,
                        context_layers=context_layers,
                    )
                    out_filename = f"{fab}-site-{metric_key}-{mode}.png"
                    fig_type = f"site_{metric_key}_{mode}"
                    register_figure(out_filename, img_site, fig_type, fab, all_site_sources, class_breaks=breaks, network_percentiles=pcts)
            else:
                details = r_map.get(fab, {"reason": f"指定輸入目錄無可用{mode}路段資料"})
                missing_sources = [Path(p) for p in details.get("searched_candidates", []) if Path(p).is_file()]
                for metric_key in ("nain", "nach"):
                    out_filename = f"{fab}-site-{metric_key}-{mode}.png"
                    fig_type = f"site_{metric_key}_{mode}"
                    register_missing(out_filename, fig_type, fab, details, missing_sources)

        # 7. E1 sunlight (MISSING)
        e1_details = {
            "reason": "找到的 E1 草案屬於 grid-mixed 與 common-mixed，未提供這四案逐案可用的日照柵格或數值；不以其他方案代替。",
            "searched_locations": [
                "docs/w6/e1-sunlight-*",
                "artifacts/ 下檔名或內容含 E1、sunlight、shadow、radiation、irradiance 的結果",
                "artifacts/ 下含四案名稱且與 E1／日照／陰影／輻射相關的檔案",
            ],
            "related_result": "docs/w6/e1-sunlight-20261004T2253Z/README.md",
            "related_result_status": "DRAFT_UNAPPROVED",
            "related_schemes": ["formal-dict-3da03eb0172d-grid-mixed-f764c233baa3", "formal-dict-3da03eb0172d-common-mixed-98854aff5f7b"],
        }
        register_missing(f"{fab}-e1-sunlight.png", "e1_sunlight", fab, e1_details, [])

    # 8. Comparative overview boards with the same 120 m shared extent.
    all_plan_paths = list(plan_paths.values())
    img_comp = render_comparison_board(plans, bounds, plan_hashes, context_layers)
    register_figure("comparison-massing.png", img_comp, "comparison_board", "all", [*all_plan_paths, *context_source_paths])

    # NEW: comparison-site-nain-pedestrian.png
    if any(fab in pedestrian_features_map for fab in plans):
        all_ped_sources = []
        for srcs in pedestrian_source_paths.values():
            all_ped_sources.extend(srcs)
        comp_site_img, comp_breaks, comp_pcts = render_site_syntax_comparison_board(
            plans=plans,
            syntax_features_map=pedestrian_features_map,
            bounds=bounds,
            plan_hashes=plan_hashes,
            context_layers=context_layers,
        )
        site_syntax_scales["comparison_site_nain_pedestrian"] = {
            "breaks": comp_breaks,
            "network_percentiles": comp_pcts,
        }
        register_figure(
            "comparison-site-nain-pedestrian.png",
            comp_site_img,
            "comparison_site_nain_pedestrian",
            "all",
            [*all_plan_paths, *all_ped_sources, *context_source_paths],
            class_breaks=comp_breaks,
            network_percentiles=comp_pcts,
        )
    else:
        register_missing("comparison-site-nain-pedestrian.png", "comparison_site_nain_pedestrian", "all", {"reason": "無可用步行路段資料"}, [])

    syntax_feature_summary = {}
    for fab, features in syntax_features_map.items():
        props = [feature.get("properties", {}) for feature in features]
        syntax_feature_summary[fab] = {
            "feature_count": len(features),
            "after_nain_count": sum(finite_number(p.get("after_nain")) is not None for p in props),
            "delta_nain_count": sum(finite_number(p.get("delta_nain")) is not None for p in props),
            "new_geometry_count": sum(p.get("comparison_status") == "NEW_OR_CHANGED_GEOMETRY" for p in props),
            "new_street_count": sum(p.get("is_new_street") is True for p in props),
            "removed_geometry_count": sum(p.get("comparison_status") == "REMOVED" for p in props),
        }

    # 9. Save Manifest.
    manifest_doc = {
        "run_label": run_label,
        "generated_at": generated_at,
        "method_version": METHOD_VERSION,
        "plans_directory": str(plans_dir),
        "syntax_directory": str(syntax_dir),
        "output_directory": str(output_dir),
        "crs": "EPSG:28992",
        "extent_buffer_m": 120.0,
        "extent_bounds_union": [round(b, 4) for b in bounds],
        "axonometric_view_margin_m": AXONOMETRIC_VIEW_MARGIN_M,
        "context_data": context_manifest,
        "syntax_resolution": syntax_resolution,
        "syntax_feature_summary": syntax_feature_summary,
        "syntax_scale_fabrics": syntax_scale_fabrics,
        "syntax_scale_quantiles": syntax_quantiles,
        "syntax_delta_method": "同幾何路段方案後 NAIN 減方案前 NAIN；新增或變更幾何保留 null，不視為零差值。",
        "site_syntax_scales": site_syntax_scales,
        "e1_sunlight": {
            "status": "MISSING",
            "searched_locations": [
                "docs/w6/e1-sunlight-*",
                "artifacts/ 下檔名或內容含 E1、sunlight、shadow、radiation、irradiance 的結果",
                "artifacts/ 下含四案名稱且與 E1／日照／陰影／輻射相關的檔案",
            ],
            "related_result": "docs/w6/e1-sunlight-20261004T2253Z/README.md",
            "related_result_status": "DRAFT_UNAPPROVED",
            "related_schemes": ["formal-dict-3da03eb0172d-grid-mixed-f764c233baa3", "formal-dict-3da03eb0172d-common-mixed-98854aff5f7b"],
            "reason": "找到的 E1 草案屬於 grid-mixed 與 common-mixed，未提供這四案逐案可用的日照柵格或數值；不以其他方案代替。",
        },
        "figures": manifest_figures,
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote manifest to {manifest_path}")

    return manifest_doc


def main() -> None:
    parser = argparse.ArgumentParser(description="Export W8-B official urban design figure set.")
    parser.add_argument("--plans", type=Path, default=Path("artifacts/net2/round-3/plans"), help="Directory containing <fabric>-plan.json files")
    parser.add_argument("--syntax", type=Path, default=Path("artifacts/net2/round-3-weld/syntax"), help="Directory containing syntax segment GeoJSONs")
    parser.add_argument("--label", type=str, default="round-3", help="Run label for output subdirectory")
    parser.add_argument("--output-dir", type=Path, default=None, help="Explicit output directory override")
    parser.add_argument("--overwrite", action="store_true", default=True, help="Allow overwriting non-empty output directory")
    parser.add_argument("--no-overwrite", dest="overwrite", action="store_false", help="Refuse overwriting non-empty output directory")
    args = parser.parse_args()

    out_dir = args.output_dir or (Path("artifacts/w8/figures") / args.label)
    run_export(args.plans, args.syntax, out_dir, args.label, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
