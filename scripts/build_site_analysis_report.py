#!/usr/bin/env python3
"""Build the Rotterdam M4H site-analysis report and claim register.

Reproducibility (macOS, from the repository root; no package installation):
  MPLCONFIGDIR=/private/tmp/w5-site-analysis-mplconfig \
  PROJ_LIB=/Applications/QGIS-LTR.app/Contents/Resources/proj \
  PYTHONPATH=src:scripts PYTHONDONTWRITEBYTECODE=1 \
  /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 \
  scripts/build_site_analysis_report.py --skip-figures

Required interpreter: QGIS LTR Python at QGIS_PYTHON below. The project
.venv does not provide matplotlib; report calculation can use --skip-figures.
Map rendering is documented in render_site_analysis_maps.py. No downloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union

QGIS_PYTHON = "/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3"
PROJ_LIB_DIR = "/Applications/QGIS-LTR.app/Contents/Resources/proj"

ROOT = Path(__file__).resolve().parents[1]
MAIN_PROJECT_ROOT = Path("/Users/jackhsieh/Downloads/TUD/Q5/project")

# Source paths with fallback to main repo
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

OUTPUT_DOC_PATH = ROOT / "docs/w5/site-analysis-report-zh.md"
OUTPUT_CLAIMS_PATH = ROOT / "artifacts/w5-site-analysis/claims.json"
OUTPUT_FIGURES_DIR = ROOT / "artifacts/w5-site-analysis/figures"


def find_existing_path(paths: Sequence[Path]) -> Path:
    for p in paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"None of the candidate paths exist: {paths}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_study_area() -> tuple[Polygon | MultiPolygon, dict[str, Any], Path]:
    path = find_existing_path(STUDY_AREA_PATHS)
    doc = json.loads(path.read_text(encoding="utf-8"))
    geom_raw = doc["geometry"] if "geometry" in doc else doc["features"][0]["geometry"]
    geom = shape(geom_raw)
    if not isinstance(geom, (Polygon, MultiPolygon)):
        raise ValueError(f"StudyArea geometry must be Polygon or MultiPolygon, got {geom.geom_type}")
    return geom, doc, path


def extract_study_area_syntax_segments(
    segment_values: Mapping[str, Any],
    network_features: Sequence[Mapping[str, Any]],
    study_area_geom: Polygon | MultiPolygon,
) -> dict[str, LineString]:
    """Return candidate PST segment geometries intersecting the site.

    Candidate IDs identify a way and a deterministic segment index. Filter by
    those way IDs before constructing segments so regional networks stay cheap
    to inspect. This mirrors the renderer's standalone segment-ID convention.
    """
    way_ids = set()
    for sid in segment_values:
        way_id = sid.split("::pst-segment-", 1)[0]
        if way_id.endswith(("_a", "_b")):
            way_id = way_id[:-2]
        if "#" in way_id:
            way_id = way_id.split("#", 1)[0]
        way_ids.add(way_id)
    site_segments: dict[str, LineString] = {}

    for feature in network_features:
        feature_id = feature.get("id") or f"way/{feature.get('properties', {}).get('osm_id')}"
        if feature_id not in way_ids:
            continue
        raw_geom = feature.get("geometry")
        if not raw_geom:
            continue
        geom = shape(raw_geom)
        if not geom.intersects(study_area_geom):
            continue
        lines = [geom] if isinstance(geom, LineString) else list(geom.geoms) if isinstance(geom, MultiLineString) else []

        for part_idx, line in enumerate(lines):
            base_id = feature_id if len(lines) == 1 else f"{feature_id}#{part_idx + 1}"
            clean: list[tuple[float, float]] = []
            for point in line.coords:
                if not clean or (round(point[0], 3), round(point[1], 3)) != (round(clean[-1][0], 3), round(clean[-1][1], 3)):
                    clean.append((point[0], point[1]))
            if len(clean) < 2:
                continue
            if (round(clean[0][0], 3), round(clean[0][1], 3)) == (round(clean[-1][0], 3), round(clean[-1][1], 3)):
                mid = len(clean) // 2
                candidate_parts = [(f"{base_id}_a", clean[: mid + 1]), (f"{base_id}_b", clean[mid:])]
            else:
                candidate_parts = [(base_id, clean)]

            for part_id, coords in candidate_parts:
                for segment_index in range(len(coords) - 1):
                    sid = f"{part_id}::pst-segment-{segment_index + 1:04d}"
                    if sid not in segment_values:
                        continue
                    segment = LineString([coords[segment_index], coords[segment_index + 1]])
                    if segment.intersects(study_area_geom):
                        site_segments[sid] = segment

    return site_segments


def extract_study_area_syntax_values(
    segment_values: Mapping[str, Any],
    network_features: Sequence[Mapping[str, Any]],
    study_area_geom: Polygon | MultiPolygon,
) -> dict[str, float]:
    segments = extract_study_area_syntax_segments(segment_values, network_features, study_area_geom)
    return {sid: float(segment_values[sid]) for sid in segments}


def linear_quintile_breaks(values: Sequence[float]) -> list[float]:
    """Return min, interpolated Q20..Q80, and max for a finite value sample."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return []

    def quantile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * weight

    return [ordered[0], *(quantile(q / 5) for q in range(1, 5)), ordered[-1]]


def quintile_counts(values: Sequence[float], breaks: Sequence[float]) -> list[int]:
    """Classify each value into tie-preserving intervals bounded by Q20..Q80."""
    counts = [0, 0, 0, 0, 0]
    for value in values:
        bucket = sum(float(value) > float(cut) for cut in breaks[1:5])
        counts[bucket] += 1
    return counts


def compute_site_metrics() -> dict[str, Any]:
    study_area_geom, study_doc, study_path = load_study_area()
    spatial_root = find_existing_path(SPATIAL_R01_ROOTS)
    norm_dir = spatial_root / "sources/normalized"

    # 1. Site area
    site_area_m2 = round(float(study_area_geom.area), 6)

    # 2. Buildings (BAG pand)
    bag_files = sorted(norm_dir.glob("pdok-bag-pand-*.geojson"))
    site_buildings = []
    clipped_building_geoms = []
    raw_usages: list[str | None] = []
    building_props_by_ident: dict[str, dict[str, Any]] = {}

    for bf in bag_files:
        data = json.loads(bf.read_text(encoding="utf-8"))
        for f in data.get("features", []):
            geom = shape(f["geometry"])
            if geom.intersects(study_area_geom):
                clipped = geom.intersection(study_area_geom)
                if not clipped.is_empty and clipped.area > 1e-3:
                    ident = str(f.get("properties", {}).get("identificatie") or "")
                    site_buildings.append(f)
                    clipped_building_geoms.append(clipped)
                    usage = f.get("properties", {}).get("gebruiksdoel")
                    raw_usages.append(usage)
                    building_props_by_ident[ident] = f.get("properties", {})

    building_union = unary_union(clipped_building_geoms)
    building_footprint_m2 = round(float(building_union.area), 6)
    building_footprint_share_pct = round((building_footprint_m2 / site_area_m2) * 100.0, 6)
    building_count = len(site_buildings)

    # Usage distribution
    usage_counts: dict[str, int] = {}
    null_usage_count = 0
    for u in raw_usages:
        if u is None or not str(u).strip():
            null_usage_count += 1
        else:
            ustr = str(u).strip()
            usage_counts[ustr] = usage_counts.get(ustr, 0) + 1

    registered_usage_count = sum(usage_counts.values())

    # 3. 3D BAG heights & floor estimation (PD-11)
    ht_path = THREE_DBAG_ROOT / "height-table-v2025.09.03-study-area-v5-buffer500m.json"
    ht_doc = json.loads(ht_path.read_text(encoding="utf-8"))
    ht_records = ht_doc.get("records", [])
    ht_by_ident: dict[str, dict[str, Any]] = {}
    for r in ht_records:
        ident_clean = r["bag_identificatie"].replace("NL.IMBAG.Pand.", "")
        ht_by_ident[ident_clean] = r
        ht_by_ident[r["bag_identificatie"]] = r

    matched_heights: list[float] = []
    unmatched_idents: list[str] = []
    demolished_in_bag_count = 0
    year_2025_new_count = 0

    point_estimate_gfa = 0.0
    min_range_gfa = 0.0
    max_range_gfa = 0.0

    for f in site_buildings:
        ident = str(f.get("properties", {}).get("identificatie") or "")
        geom = shape(f["geometry"])
        clipped = geom.intersection(study_area_geom)
        fp_area = clipped.area
        hr = ht_by_ident.get(ident)
        usage = str(f.get("properties", {}).get("gebruiksdoel") or "")

        if hr and hr.get("status") == "AVAILABLE" and hr.get("height_above_ground_m") is not None:
            h = float(hr["height_above_ground_m"])
            matched_heights.append(h)
            est_floors = max(1, round(h / 3.0))
            if "industrie" in usage.lower():
                min_f, max_f = 1, est_floors
            else:
                min_f, max_f = est_floors, est_floors
            point_estimate_gfa += est_floors * fp_area
            min_range_gfa += min_f * fp_area
            max_range_gfa += max_f * fp_area
        else:
            unmatched_idents.append(ident)
            status_text = str(f.get("properties", {}).get("status") or "")
            bouwjaar = f.get("properties", {}).get("bouwjaar")
            if "gesloopt" in status_text.lower():
                demolished_in_bag_count += 1
            elif bouwjaar == 2025:
                year_2025_new_count += 1

    matched_heights.sort()
    n_h = len(matched_heights)
    height_median = matched_heights[n_h // 2] if n_h > 0 else 0.0
    height_min = matched_heights[0] if n_h > 0 else 0.0
    height_max = matched_heights[-1] if n_h > 0 else 0.0
    height_mean = sum(matched_heights) / n_h if n_h > 0 else 0.0
    height_p25 = matched_heights[int(n_h * 0.25)] if n_h > 0 else 0.0
    height_p75 = matched_heights[int(n_h * 0.75)] if n_h > 0 else 0.0

    # 4. Roads (OSM)
    osm_path = norm_dir / "osm-overpass-v5-epsg28992.geojson"
    osm_doc = json.loads(osm_path.read_text(encoding="utf-8"))
    road_lengths_by_type_raw: dict[str, float] = {}
    clipped_road_lines: list[LineString | MultiLineString] = []
    gateway_points: list[Point] = []
    study_area_boundary = study_area_geom.boundary

    for f in osm_doc.get("features", []):
        tags = f.get("properties", {}).get("tags", {})
        hwy = tags.get("highway")
        if not hwy:
            continue
        geom = shape(f["geometry"])
        if geom.intersects(study_area_geom):
            clipped = geom.intersection(study_area_geom)
            if not clipped.is_empty and clipped.length > 1e-3:
                clipped_road_lines.append(clipped)
                road_lengths_by_type_raw[hwy] = road_lengths_by_type_raw.get(hwy, 0.0) + clipped.length
            inter = geom.intersection(study_area_boundary)
            if not inter.is_empty:
                if inter.geom_type == "Point":
                    gateway_points.append(inter)
                elif inter.geom_type == "MultiPoint":
                    gateway_points.extend(list(inter.geoms))

    road_union = unary_union(clipped_road_lines) if clipped_road_lines else LineString()
    dedup_road_length_m = round(float(road_union.length), 6)
    road_lengths_by_type = {key: round(value, 6) for key, value in road_lengths_by_type_raw.items()}
    sum_clipped_road_length_m = round(sum(road_lengths_by_type_raw.values()), 6)

    # 5. Water (BGT waterdeel)
    water_files = sorted(norm_dir.glob("pdok-bgt-waterdeel-*.geojson"))
    clipped_water_geoms = []
    for wf in water_files:
        data = json.loads(wf.read_text(encoding="utf-8"))
        for f in data.get("features", []):
            geom = shape(f["geometry"])
            if geom.intersects(study_area_geom):
                clipped = geom.intersection(study_area_geom)
                if not clipped.is_empty and clipped.area > 1e-3:
                    clipped_water_geoms.append(clipped)

    water_union = unary_union(clipped_water_geoms)
    water_area_m2 = round(float(water_union.area), 6)
    water_share_pct = round((water_area_m2 / site_area_m2) * 100.0, 6)

    # Water-land quay interface
    water_boundary = water_union.boundary
    quay_interface = water_boundary.difference(study_area_boundary.buffer(0.01))
    quay_length_m = round(float(quay_interface.length), 2)
    total_water_boundary_m = round(float(water_boundary.length), 2)

    # 6. Unclassified surface residual area
    occupied_parts = [building_union, water_union]
    occupied_union = unary_union(occupied_parts)
    unclassified_surface_m2 = round(max(0.0, site_area_m2 - float(occupied_union.area)), 6)
    unclassified_share_pct = round((unclassified_surface_m2 / site_area_m2) * 100.0, 6)

    # 7. Green spaces from OSM context
    context_manifest_path = CONTEXT_ROOT / "manifest.json"
    context_manifest = json.loads(context_manifest_path.read_text(encoding="utf-8"))
    green_path = CONTEXT_ROOT / context_manifest["run_directory"] / "green.geojson"
    green_doc = json.loads(green_path.read_text(encoding="utf-8"))
    site_green_area_m2 = 0.0
    green_by_type_raw: dict[str, float] = {}
    site_green_feature_count = 0

    for f in green_doc.get("features", []):
        geom = shape(f["geometry"])
        if geom.intersects(study_area_geom):
            clipped = geom.intersection(study_area_geom)
            if not clipped.is_empty:
                area = float(clipped.area)
                site_green_area_m2 += area
                site_green_feature_count += 1
                lu = f.get("properties", {}).get("landuse") or f.get("properties", {}).get("leisure") or "other"
                green_by_type_raw[lu] = green_by_type_raw.get(lu, 0.0) + area

    site_green_area_m2 = round(site_green_area_m2, 2)
    green_by_type = {key: round(value, 2) for key, value in green_by_type_raw.items()}

    # 8. Space Syntax six layers
    syntax_candidate_path = SYNTAX_RUN_ROOT / "syntax_six_layer_candidate.json"
    syntax_candidate = json.loads(syntax_candidate_path.read_text(encoding="utf-8"))
    syntax_manifest_path = SYNTAX_RUN_ROOT / "run-manifest.json"
    syntax_manifest = json.loads(syntax_manifest_path.read_text(encoding="utf-8"))

    syntax_layers_summary = []
    network_file_map = {
        "pedestrian": SYNTAX_EXTRACTED_ROOT / "network_pedestrian_1500m.geojson",
        "bicycle": SYNTAX_EXTRACTED_ROOT / "network_bicycle_6000m.geojson",
        "motor_vehicle": SYNTAX_EXTRACTED_ROOT / "network_motor_vehicle_20000m.geojson",
    }
    for l in syntax_candidate.get("layers", []):
        network_doc = json.loads(network_file_map[l["network_mode"]].read_text(encoding="utf-8"))
        site_segment_values = extract_study_area_syntax_values(
            l["segment_values"], network_doc.get("features", []), study_area_geom
        )
        site_breaks = linear_quintile_breaks(list(site_segment_values.values()))
        syntax_layers_summary.append({
            "layer_id": l["layer_id"],
            "title": l.get("title"),
            "scale": l.get("scale"),
            "radius_m": l.get("radius_m"),
            "network_mode": l.get("network_mode"),
            "metric_key": l.get("metric_key"),
            "unit": l.get("unit"),
            "data_readiness": l.get("data_readiness"),
            "statistics": l.get("statistics"),
            "legend_breaks": l.get("legend_breaks"),
            "segment_count": len(l.get("segment_values", {})),
            "site_map": {
                "segment_count": len(site_segment_values),
                "quintile_breaks": site_breaks,
                "quintile_counts": quintile_counts(list(site_segment_values.values()), site_breaks),
            },
        })

    return {
        "study_area": {
            "id": "study-area-rotterdam-m4h-pilot-project-v5",
            "version": "v5",
            "crs": "EPSG:28992",
            "bounds": [round(c, 2) for c in study_area_geom.bounds],
            "area_m2": site_area_m2,
            "path": str(study_path),
            "sha256": sha256_file(study_path),
        },
        "buildings": {
            "count": building_count,
            "footprint_area_m2": building_footprint_m2,
            "footprint_share_pct": building_footprint_share_pct,
            "registered_gebruiksdoel_count": registered_usage_count,
            "null_gebruiksdoel_count": null_usage_count,
            "usage_counts": usage_counts,
            "3dbag": {
                "matched_count": len(matched_heights),
                "unmatched_count": len(unmatched_idents),
                "demolished_in_bag_count": demolished_in_bag_count,
                "year_2025_new_count": year_2025_new_count,
                "min_m": round(height_min, 2),
                "max_m": round(height_max, 2),
                "median_m": round(height_median, 2),
                "mean_m": round(height_mean, 2),
                "p25_m": round(height_p25, 2),
                "p75_m": round(height_p75, 2),
                "height_table_sha256": ht_doc.get("schema_version"),
            },
            "gfa_estimate": {
                "rule": "floor-estimate-v1 (PD-11, 3.0m storey FIXTURE_ONLY)",
                "standard_point_gfa_m2": round(point_estimate_gfa, 2),
                "industrie_adjusted_range_gfa_m2": [round(min_range_gfa, 2), round(max_range_gfa, 2)],
                "unknown_count": len(unmatched_idents),
            },
        },
        "roads": {
            "deduplicated_centerline_length_m": dedup_road_length_m,
            "summed_clipped_length_m": sum_clipped_road_length_m,
            "lengths_by_type": road_lengths_by_type,
            "gateway_points_count": len({tuple(round(c, 3) for c in point.coords[0]) for point in gateway_points if not point.is_empty}),
        },
        "water_and_open_space": {
            "bgt_water_area_m2": water_area_m2,
            "bgt_water_share_pct": water_share_pct,
            "total_water_boundary_m": total_water_boundary_m,
            "quay_interface_length_m": quay_length_m,
            "unclassified_surface_residual_m2": unclassified_surface_m2,
            "unclassified_surface_share_pct": unclassified_share_pct,
            "osm_green_area_m2": site_green_area_m2,
            "osm_green_feature_count": site_green_feature_count,
            "green_by_type": green_by_type,
        },
        "syntax": {
            "engine": "PST 3.3.1 (PD-15)",
            "method_manifest_sha256": syntax_manifest.get("method_manifest_sha256"),
            "candidate_sha256": sha256_file(syntax_candidate_path),
            "layers": syntax_layers_summary,
        },
        "context_2km": {
            "extraction_id": context_manifest.get("extraction_id"),
            "feature_counts": context_manifest.get("feature_counts"),
            "source_pbf_sha256": context_manifest.get("source_pbf_sha256"),
            "source_data_version": context_manifest.get("source_data_version"),
        },
    }


def generate_claims_json(metrics: dict[str, Any], output_path: Path) -> list[dict[str, Any]]:
    claims = [
        {
            "id": "claim-w5-site-001",
            "章節": "範圍與資料來源",
            "敘述": "Rotterdam M4H StudyArea v5 是供探索使用、經人工確認的研究範圍，不是正式 Site 或 DesignBoundary；其 EPSG:28992 幾何面積為 226,064.33 m²（22.61 公頃），邊界為 [88610.65, 435507.08, 89558.21, 436221.65]。",
            "數值": metrics["study_area"]["area_m2"],
            "單位": "m²",
            "來源檔案或證據 ID": "artifacts/week4-repair-r02/syntax/study-area.geojson; matching context snapshot: ~/.local/share/urban-design-data/context/context-20260927T153054Z/study-area-v5.geojson",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "僅適用於 v5 確定之研究範圍邊界，不代表未來都市更新法定分區界線",
                "投影計算以 EPSG:28992 為唯一基準",
            ],
        },
        {
            "id": "claim-w5-site-002",
            "章節": "既有建築",
            "敘述": "StudyArea v5 範圍內共有 51 個 BAG 建築面圖徵；圖徵數不等於現地建築棟數。",
            "數值": metrics["buildings"]["count"],
            "單位": "features",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson; artifacts/week4-repair-r03/evidence-bundle.json#card-r03-bag_building_footprint_count-9cedebac22a23cae",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "依據 PDOK BAG 2024 抽取之多邊形計數，包含部分歷史登記但已拆除之特徵",
                "不等於現況實際存在且使用中之實體建物棟數",
            ],
        },
        {
            "id": "claim-w5-site-003",
            "章節": "既有建築",
            "敘述": "51 個 BAG 建築面圖徵裁切至 StudyArea 後的幾何聯集面積為 44,699.56 m²。",
            "數值": metrics["buildings"]["footprint_area_m2"],
            "單位": "m²",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson; artifacts/week4-repair-r03/evidence-bundle.json#card-r03-bag_building_footprint_area-71df3071d6ce665e",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "多邊形重疊部分以聯集消除，不重複計算基底面積",
                "包含裁剪至邊界內部之部分建築投影",
            ],
        },
        {
            "id": "claim-w5-site-004",
            "章節": "既有建築",
            "敘述": "BAG 建築面聯集佔 StudyArea 面積 19.77%；這是幾何比率，不是法規建蔽率。",
            "數值": metrics["buildings"]["footprint_share_pct"],
            "單位": "%",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson + StudyArea; computed as footprint union / StudyArea area",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "基於 44,699.56 m² / 226,064.33 m² 之比率計算",
                "未考慮基地內不可建之水體水面扣除比率",
            ],
        },
        {
            "id": "claim-w5-site-005",
            "章節": "既有建築",
            "敘述": "3D BAG v2025.09.03 高度表可與基地內 51 個 BAG 特徵配對出 31 筆 AVAILABLE 高度；配對高度中位數為 9.85 m，最高 27.41 m、最低 2.68 m、平均 10.44 m。其餘 20 筆沒有可用配對高度；BAG 屬性中 19 筆標為 Pand gesloopt、1 筆 bouwjaar 為 2025，這不單獨證明現地建物狀態。",
            "數值": metrics["buildings"]["3dbag"]["median_m"],
            "單位": "m",
            "來源檔案或證據 ID": "~/.local/share/urban-design-data/3dbag/height-table-v2025.09.03-study-area-v5-buffer500m.json + artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "高度取自 3D BAG b3_h_70p 減去 maaiveld 地面高",
                "20 個未配對圖徵中 BAG 欄位記錄 19 筆 Pand gesloopt 與 1 筆 bouwjaar 2025；登記資料不單獨證明無配對原因或現地狀態",
            ],
        },
        {
            "id": "claim-w5-site-006",
            "章節": "既有建築",
            "敘述": "依 PD-11 floor-estimate-v1 與 3.0 m FIXTURE_ONLY 層高假設，31 個高度已配對 BAG 圖徵的標準點 GFA 估算為 175,984.03 m²，工業用途區間為 [55,425.20 m², 175,984.03 m²]；其餘 20 個高度未知。",
            "數值": metrics["buildings"]["gfa_estimate"]["standard_point_gfa_m2"],
            "單位": "m²",
            "來源檔案或證據 ID": "~/.local/share/urban-design-data/3dbag/height-table-v2025.09.03-study-area-v5-buffer500m.json + artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson; docs/decisions/2026-09-25-plan-decisions-zh.md (PD-11)",
            "證據層級": "COMPUTED_RESULT",
            "假設": ["PD-11 floor-estimate-v1 uses a 3.0 m storey-height FIXTURE_ONLY assumption; 20 unmatched heights remain unknown."],
            "限制": [
                "屬於估算值非觀測值，不宣稱實際樓地板面積",
                "缺高度者維持 UnavailableValue，不補 0，不虛構整體 FAR",
            ],
        },
        {
            "id": "claim-w5-site-007",
            "章節": "既有建築",
            "敘述": "51 個 BAG 建築面圖徵中，31 個有登記用途欄位、20 個為空白；19 個特徵的用途標籤含 industriefunctie，其中 13 個為單一標籤、6 個為複合標籤。",
            "數值": metrics["buildings"]["registered_gebruiksdoel_count"],
            "單位": "features",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson; artifacts/week4-execution-r25-20260924T113401Z/browser-run/report.json#card-r04-bag_registered_gebruiksdoel_features-f518e91a8d407773",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "依據 BAG pand 屬性登記，不代表實際現況承租或合法使用許可",
                "空白欄位保持 UNKNOWN，不推估",
            ],
        },
        {
            "id": "claim-w5-site-008",
            "章節": "道路與交通",
            "敘述": "基地內去重複之 OSM 道路中心線聯集總長度為 8,496.54 m。",
            "數值": metrics["roads"]["deduplicated_centerline_length_m"],
            "單位": "m",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/osm-overpass-v5-epsg28992.geojson; artifacts/week4-execution-r25-20260924T113401Z/browser-run/report.json#card-r04-osm_highway_unique_centerline_length-7532d933e2f11866",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "去重複中心線長度，重疊段僅計一次",
                "不包含人行動線連通性、通行權或通達性政策",
            ],
        },
        {
            "id": "claim-w5-site-009",
            "章節": "道路與交通",
            "敘述": "依 OSM highway 標籤裁切後各類中心線長度合計 8,501.23 m（含重疊線段）；service 為最大類別 3,424.99 m（40.3%），footway 1,897.64 m（22.3%）、unclassified 1,293.09 m（15.2%）、cycleway 955.98 m（11.2%）。類別占比以各標籤長度總和 8,501.23 m 為分母。",
            "數值": metrics["roads"]["lengths_by_type"]["service"],
            "單位": "m",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/osm-overpass-v5-epsg28992.geojson",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "基於 OSM 標籤分類，不代表法定路權分類或設計車速",
            ],
        },
        {
            "id": "claim-w5-site-010",
            "章節": "道路與交通",
            "敘述": "OSM highway 線幾何與 StudyArea 邊界產生 22 個互異交點；交點僅為幾何結果，不證明道路出入口、通行權或可通行性。",
            "數值": metrics["roads"]["gateway_points_count"],
            "單位": "distinct_boundary_intersections",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/osm-overpass-v5-epsg28992.geojson + artifacts/week4-repair-r02/syntax/study-area.geojson",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "僅反映幾何邊界交點，未審查各交點之轉向限制與出入管制",
            ],
        },
        {
            "id": "claim-w5-site-012",
            "章節": "機能與土地使用",
            "敘述": "2 km OSM context snapshot 含 21,045 個建築面、1,135 個綠地面、103 個水體面及 4,862 條道路線要素；這些是圖徵數，不是住宅戶數、人口、交通量或完整土地使用統計。",
            "數值": metrics["context_2km"]["feature_counts"]["buildings"],
            "單位": "buildings",
            "來源檔案或證據 ID": "~/.local/share/urban-design-data/context/manifest.json + ~/.local/share/urban-design-data/context/context-20260927T153054Z/{buildings,green,water,roads}.geojson",
            "證據層級": "DATASET_OBSERVATION",
            "限制": [
                "OSM 資料版本為 2026-09-22T20:22:59Z；本機 context 抽取於 2026-09-27，範圍為 StudyArea 外擴 2 km、EPSG:28992；用途與人流不可由圖徵數推得",
            ],
        },
        {
            "id": "claim-w5-site-013",
            "章節": "機能與土地使用",
            "敘述": "本次 OSM 路網抽取沒有獨立 amenity 或 landuse 多邊形；點狀標籤與 BAG 登記用途不足以形成完整現況機能／土地使用清冊，細部功能仍為 UNKNOWN。",
            "數值": "UNKNOWN",
            "單位": "status",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/osm-overpass-v5-epsg28992.geojson",
            "證據層級": "DATA_GAP",
            "限制": [
                "缺乏細部設施屬性，不得以臆測替代缺漏資料",
            ],
        },
        {
            "id": "claim-w5-site-014",
            "章節": "開放空間與水體",
            "敘述": "基地內 BGT 登記水體面積為 42,472.998 m²，佔基地總面積 18.79%。",
            "數值": metrics["water_and_open_space"]["bgt_water_area_m2"],
            "單位": "m²",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bgt-waterdeel-p001-epsg28992.geojson; artifacts/week4-repair-r03/evidence-bundle.json#card-r03-bgt_waterdeel_area-67f47470e954c0bb",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "以 BGT 水體面特徵裁剪計算，不包含漲退潮潮位變化",
            ],
        },
        {
            "id": "claim-w5-site-015",
            "章節": "開放空間與水體",
            "敘述": "基地內 BGT 水體聯集邊界中，扣除貼近 StudyArea 邊界的裁切線後，幾何水陸介面長度為 1,332.04 m；資料未描述岸線是否垂直、硬化或防汛。",
            "數值": metrics["water_and_open_space"]["quay_interface_length_m"],
            "單位": "m",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bgt-waterdeel-p001-epsg28992.geojson + StudyArea geometry",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "此為 BGT 水體邊界的幾何長度，不是已確認的垂直駁岸長度；無現場護岸結構或高程資料",
            ],
        },
        {
            "id": "claim-w5-site-016",
            "章節": "開放空間與水體",
            "敘述": "基地面積扣除 BAG 建築基底與 BGT 水體聯集後的未分類幾何殘差為 138,891.77 m²（佔 61.44%）；此差額未分類，不能推定為硬鋪面、空置地、可開發地或公共開放空間。",
            "數值": metrics["water_and_open_space"]["unclassified_surface_residual_m2"],
            "單位": "m²",
            "來源檔案或證據 ID": "artifacts/week4-repair-r02/syntax/study-area.geojson + artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson + artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bgt-waterdeel-*.geojson; artifacts/week4-execution-r25-20260924T113401Z/browser-run/report.json#card-r04-unclassified_surface_residual_area-e0f816172e96540c",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "殘差只表示輸入圖層未覆蓋之面積；OSM 綠地可落在此幾何內，地表材質、用途、開放性與可建性均未驗證",
            ],
        },
        {
            "id": "claim-w5-site-017",
            "章節": "開放空間與水體",
            "敘述": "StudyArea 內與 OSM 綠地相交的 21 個圖徵總裁切面積為 21,886.06 m²；按 landuse 分類為 grass 11,454.32 m²、forest 1,526.74 m²、allotments 8,905.00 m²。",
            "數值": metrics["water_and_open_space"]["osm_green_area_m2"],
            "單位": "m²",
            "來源檔案或證據 ID": "~/.local/share/urban-design-data/context/context-20260927T153054Z/green.geojson",
            "證據層級": "COMPUTED_RESULT",
            "限制": [
                "逐圖徵裁切面積加總；取自 OSM 綠地圖層，不保證開放公眾進入或可確認管理者",
            ],
        },
        {
            "id": "claim-w5-site-018",
            "章節": "Space Syntax",
            "敘述": "PST 3.3.1 行人 800 m NAIN 候選值的中間五分位（Q40–Q60）為 [0.7219, 0.8098]，最大值 1.2729；最大值對應的路段在輸入網路中標為 imputed 且沒有道路名稱，不能據此稱為 Marconistraat 出入口。",
            "數值": metrics["syntax"]["layers"][0]["statistics"]["max"],
            "單位": "NAIN (normalized)",
            "來源檔案或證據 ID": "~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 0) + ~/.local/share/urban-design-data/week5-syntax-modes/extracted/network_pedestrian_1500m.geojson",
            "證據層級": "COMPUTED_RESULT",
            "結果狀態": "BLOCKED_BOUNDARY_STABILITY_UNASSESSED",
            "限制": [
                "不得將 integration 說成人流（pedestrian flow）",
                "800m 緩衝區邊界穩定性尚未進行擴展半徑之交叉檢驗",
            ],
        },
        {
            "id": "claim-w5-site-019",
            "章節": "Space Syntax",
            "敘述": "PST 3.3.1 行人 800 m 角穿行度（NACH）最高值 1.4713，平均值 0.8542，五分位間距為 [0.0, 0.6782, 0.8168, 0.9433, 1.1187, 1.4713]。",
            "數值": metrics["syntax"]["layers"][1]["statistics"]["max"],
            "單位": "NACH (normalized)",
            "來源檔案或證據 ID": "~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 1)",
            "證據層級": "COMPUTED_RESULT",
            "結果狀態": "BLOCKED_BOUNDARY_STABILITY_UNASSESSED",
            "限制": [
                "不得將 choice 說成交通量（traffic volume）",
                "800m 緩衝區邊界穩定性尚未評估",
            ],
        },
        {
            "id": "claim-w5-site-020",
            "章節": "Space Syntax",
            "敘述": "自行車 2,000 m（RVV 法規路網）角整合度 NAIN 最高 0.8807，平均 0.6738，經 4 km vs 6 km 檢驗 Spearman 相關係數 1.0，0 段邊界敏感。",
            "數值": metrics["syntax"]["layers"][2]["statistics"]["max"],
            "單位": "NAIN (normalized)",
            "來源檔案或證據 ID": "~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 2) + ~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/stability_2000m_4000m_vs_6000m.json",
            "證據層級": "COMPUTED_RESULT",
            "結果狀態": "EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY",
            "限制": [
                "依荷蘭交通規則推定部分路段，不可作為人流預測",
            ],
        },
        {
            "id": "claim-w5-site-021",
            "章節": "Space Syntax",
            "敘述": "自行車 2,000 m（RVV 法規路網）角穿行度 NACH 最高 1.2715，平均 0.7650，Spearman 相關係數 1.0。",
            "數值": metrics["syntax"]["layers"][3]["statistics"]["max"],
            "單位": "NACH (normalized)",
            "來源檔案或證據 ID": "~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 3) + ~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/stability_2000m_4000m_vs_6000m.json",
            "證據層級": "COMPUTED_RESULT",
            "結果狀態": "EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY",
            "限制": [
                "禁止等同於自行車流量",
            ],
        },
        {
            "id": "claim-w5-site-022",
            "章節": "Space Syntax",
            "敘述": "汽車 10,000 m 角整合度 NAIN 最高 0.7406，平均 0.6446，經 15 km vs 20 km 檢驗 Spearman 相關係數 1.0。",
            "數值": metrics["syntax"]["layers"][4]["statistics"]["max"],
            "單位": "NAIN (normalized)",
            "來源檔案或證據 ID": "~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 4) + ~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/stability_10000m_15000m_vs_20000m.json",
            "證據層級": "COMPUTED_RESULT",
            "結果狀態": "EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY",
            "限制": [
                "禁止等同於機動車車流量；結果為探索性幾何度量",
            ],
        },
        {
            "id": "claim-w5-site-023",
            "章節": "Space Syntax",
            "敘述": "汽車 10,000 m 角穿行度 NACH 最高 1.1620，平均 0.7572，Spearman 相關係數 1.0。",
            "數值": metrics["syntax"]["layers"][5]["statistics"]["max"],
            "單位": "NACH (normalized)",
            "來源檔案或證據 ID": "~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 5) + ~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/stability_10000m_15000m_vs_20000m.json",
            "證據層級": "COMPUTED_RESULT",
            "結果狀態": "EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY",
            "限制": [
                "禁止等同於機動車車流量",
            ],
        },
        {
            "id": "claim-w5-site-024",
            "章節": "Space Syntax",
            "敘述": "空間語法自製引擎比對 method-comparison-v1 判定為 FAIL（95 百分位 choice 相對誤差 42.1%），依 PD-15 正式採用 PST 3.3.1，所有語法圖層均標記為 EXPLORATORY。",
            "數值": "FAIL",
            "單位": "status",
            "來源檔案或證據 ID": "docs/decisions/2026-09-25-plan-decisions-zh.md (PD-15)",
            "證據層級": "PROJECT_DECISION",
            "限制": [
                "舊自製引擎退為歷史參考，新結果不得宣稱為驗證通過之行為預測",
            ],
        },
        {
            "id": "claim-w5-site-025",
            "章節": "資料缺口與建議補充",
            "敘述": "本次保留的資料與程式未驗證正式地籍／產權、公共通行權、無障礙環境、實際租戶使用及微氣候風環境；這些項目維持未評估／未知。程式明列 StudyArea 不構成地籍結論、風環境為 UNVERIFIED_E5，零售可達性則因必要空間政策未批准而 BLOCKED。",
            "數值": "UNKNOWN_BLOCKED",
            "單位": "status",
            "來源檔案或證據 ID": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/data-gap-register.json; src/urban_design/site_analysis.py",
            "證據層級": "DATA_GAP",
            "限制": [
                "設計方案不得在無地籍或無通行權核准下私自處分地塊",
                "風舒適度必須基於 CFD 實質模擬而非僅風玫瑰圖",
            ],
        },
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(claims, ensure_ascii=False, indent=2) + "\n"
    output_path.write_text(raw, encoding="utf-8")
    return claims


def render_all_figures(output_dir: Path) -> list[Path]:
    """Execute figure rendering script using QGIS Python matplotlib."""
    output_dir.mkdir(parents=True, exist_ok=True)
    renderer_script = ROOT / "scripts/render_site_analysis_maps.py"
    
    cmd = [
        str(Path(QGIS_PYTHON)),
        str(renderer_script),
        "--output-dir",
        str(output_dir),
    ]
    env = {
        **dict(os.environ),
        "PROJ_LIB": PROJ_LIB_DIR,
        "PYTHONPATH": f"{ROOT}/src:{os.environ.get('PYTHONPATH', '')}",
        "MPLBACKEND": "Agg",
    }
    
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Map rendering failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    
    generated = sorted(output_dir.glob("*.png"))
    for fig_path in generated:
        size = fig_path.stat().st_size
        if size >= 1_500_000:
            raise ValueError(f"Figure {fig_path.name} exceeds 1.5 MB limit: {size} bytes")
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description="Build M4H Site Analysis Report")
    parser.add_argument("--skip-figures", action="store_true", help="Skip re-rendering figures")
    args = parser.parse_args()

    print("Step 1: Computing site metrics...")
    metrics = compute_site_metrics()

    print("Step 2: Writing claims.json...")
    claims = generate_claims_json(metrics, OUTPUT_CLAIMS_PATH)
    print(f"  Wrote {len(claims)} claims to {OUTPUT_CLAIMS_PATH}")

    if not args.skip_figures:
        print("Step 3: Rendering 12 formal figures...")
        figs = render_all_figures(OUTPUT_FIGURES_DIR)
        print(f"  Rendered {len(figs)} figures to {OUTPUT_FIGURES_DIR}")
    else:
        print("Step 3: Skipping figure rendering (--skip-figures)")

    print("Step 4: Writing site analysis report in Traditional Chinese...")
    # Report generation call or inline
    from build_site_analysis_markdown import write_report_markdown
    write_report_markdown(metrics, claims, OUTPUT_DOC_PATH)
    print(f"  Report written to {OUTPUT_DOC_PATH}")

    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
