#!/usr/bin/env python3
"""S6 design-intent brief tools. Local, deterministic, and copy-only."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point, Polygon, shape, mapping
from shapely.ops import nearest_points, split as split_geometry
from shapely.ops import unary_union


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
Q5_ROOT = REPO_ROOT.parent
PROJECT_ROOT = Q5_ROOT / "project"
KB_ROOT_DEFAULT = REPO_ROOT  # knowledge/v2 lives in this repo (w6-08-editor worktree retired 10-15)
SCHEMA_RELATIVE = Path("knowledge/v2/skills/massing-design-brief.schema.json")
SKILL_RELATIVE = Path("knowledge/v2/skills/massing-design-brief-zh.md")
FORMAL_DB = PROJECT_ROOT / ".urban_design_runtime/state.sqlite3"
STRATEGIES = ("radial", "axial", "grid", "green_service")
WARN_CODES = frozenset({"WIDE_LAND_UNDERUSED"})
STATION_STEP_M = 25.0
PROMPT_STATION_STEP_M = 50.0
WIDE_LAND_MIN_WIDTH_M = 105.0
WIDE_LAND_PARK_COVERAGE_WARN_RATIO = 0.60
EXTERNAL_HIGH_ROAD_ADJACENCY_M = 30.0
DAKPARK_NAME_DISTANCE_LIMIT_M = 150.0
WATERFRONT_NAME_DISTANCE_LIMIT_M = 40.0
LANDMARK_ENTRY_DISTANCE_LIMIT_M = 80.0
KB_QUERIES = (
    "周邊式街廓 板樓 連棟 類型比較",
    "水岸 帶狀 街區 先例",
    "Spacematrix 密度 FSI GSI",
    "街廓尺寸 棟距 日照",
    "荷蘭 自行車 停車 街道",
)
PORTFOLIO_USE_RANGES = {
    "製造": [30, 40],
    "辦公": [10, 20],
    "住宅": [30, 50],
    "設施": [10, 10],
}


class S6BriefError(RuntimeError):
    pass


def _json_read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S6BriefError(f"無法讀取 JSON {path}: {exc}") from exc


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    # Project operations record time through the system UTC clock command.
    result = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _connect_copy_database(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if resolved == FORMAL_DB.resolve():
        raise S6BriefError("拒絕直接開啟正式資料庫；請先以 SQLite backup API 建立 /private/tmp 副本。")
    try:
        resolved.relative_to(Path("/private/tmp"))
    except ValueError as exc:
        raise S6BriefError("資料庫副本必須位於 /private/tmp。") from exc
    if not resolved.is_file():
        raise S6BriefError(f"資料庫副本不存在：{resolved}")
    uri = f"file:{resolved.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("PRAGMA query_only=ON")
        return conn
    except sqlite3.Error as exc:
        raise S6BriefError(f"唯讀開啟資料庫副本失敗：{exc}") from exc


def _state_payload(conn: sqlite3.Connection, entity_type: str, entity_id: str | None = None) -> dict[str, Any]:
    sql = (
        "SELECT v.payload_json FROM state_heads h "
        "JOIN state_versions v ON v.entity_id=h.entity_id AND v.entity_type=h.entity_type "
        "AND v.revision=h.current_revision WHERE h.entity_type=?"
    )
    params: list[Any] = [entity_type]
    if entity_id is not None:
        sql += " AND h.entity_id=?"
        params.append(entity_id)
    sql += " ORDER BY h.entity_id"
    rows = conn.execute(sql, params).fetchall()
    if entity_id is not None:
        if len(rows) != 1:
            raise S6BriefError(f"資料庫副本中找不到唯一 {entity_type}/{entity_id}。")
        return json.loads(rows[0][0])
    return {str(i): json.loads(row[0]) for i, row in enumerate(rows)}


def _artifact(conn: sqlite3.Connection, artifact_id: str) -> dict[str, Any]:
    return _state_payload(conn, "Artifact", artifact_id)


def _verified_artifact(conn: sqlite3.Connection, artifact_id: str) -> tuple[dict[str, Any], Path]:
    artifact = _artifact(conn, artifact_id)
    path = Path(str(artifact.get("uri", ""))).expanduser()
    if not path.is_file():
        raise S6BriefError(f"來源檔不存在：{artifact_id} -> {path}")
    observed = _sha256(path)
    expected = str(artifact.get("sha256", "")).removeprefix("sha256:")
    if observed != expected:
        raise S6BriefError(f"來源 hash 不符：{artifact_id}；DB={expected}，檔案={observed}")
    if artifact.get("size_bytes") is not None and path.stat().st_size != int(artifact["size_bytes"]):
        raise S6BriefError(f"來源位元組數不符：{artifact_id}")
    return artifact, path


def _source_record(conn: sqlite3.Connection, artifact_id: str) -> dict[str, Any]:
    artifact, path = _verified_artifact(conn, artifact_id)
    rows = conn.execute(
        "SELECT v.payload_json FROM state_heads h JOIN state_versions v "
        "ON v.entity_id=h.entity_id AND v.entity_type=h.entity_type AND v.revision=h.current_revision "
        "WHERE h.entity_type='DatasetSnapshot'"
    ).fetchall()
    snapshots = [json.loads(row[0]) for row in rows]
    linked = [s for s in snapshots if artifact_id in (s.get("normalized_artifact_id"), s.get("raw_artifact_id"))]
    snapshot = sorted(linked, key=lambda s: str(s.get("id")))[0] if linked else {}
    return {
        "artifact_id": artifact_id,
        "path": str(path),
        "sha256": str(artifact.get("sha256", "")),
        "size_bytes": int(artifact["size_bytes"]) if artifact.get("size_bytes") is not None else None,
        "crs": artifact.get("crs"),
        "producer": artifact.get("producer"),
        "dataset_snapshot_id": snapshot.get("id"),
        "source": snapshot.get("source"),
        "query": snapshot.get("query"),
        "version": snapshot.get("version"),
        "retrieved_at": snapshot.get("retrieved_at"),
        "license": snapshot.get("license"),
        "publisher": snapshot.get("publisher"),
    }


def _json_geometry(data: dict[str, Any]) -> Polygon | Any:
    if data.get("type") == "Feature":
        geometry = data.get("geometry")
    elif data.get("type") == "FeatureCollection":
        geometry = unary_union([shape(f["geometry"]) for f in data.get("features", []) if f.get("geometry")])
        return geometry
    elif "geometry" in data:
        geometry = data["geometry"]
    else:
        geometry = data
    if not geometry:
        raise S6BriefError("GeoJSON 沒有 geometry。")
    return shape(geometry)


def _geojson_features(path: Path) -> list[dict[str, Any]]:
    data = _json_read(path)
    if data.get("type") != "FeatureCollection":
        raise S6BriefError(f"不是 GeoJSON FeatureCollection：{path}")
    crs = data.get("crs", {}).get("properties", {}).get("name")
    if crs and crs != "EPSG:28992":
        raise S6BriefError(f"來源 CRS 必須為 EPSG:28992，實際為 {crs}: {path}")
    return [f for f in data.get("features", []) if f.get("geometry")]


def _polygonal(geometry: Any) -> Any:
    if geometry.is_empty:
        return geometry
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    polygons = []
    for child in getattr(geometry, "geoms", []):
        polygons.extend(_polygon_parts(child))
    return unary_union(polygons) if polygons else GeometryCollection()


def _polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon" or hasattr(geometry, "geoms"):
        return [part for child in geometry.geoms for part in _polygon_parts(child)]
    return []


def _line_parts(geometry: Any) -> list[LineString]:
    if geometry.geom_type == "LineString":
        return [geometry] if geometry.length > 0 else []
    if geometry.geom_type == "MultiLineString" or hasattr(geometry, "geoms"):
        return [part for child in geometry.geoms for part in _line_parts(child)]
    return []


def _current_workspace(conn: sqlite3.Connection) -> dict[str, Any]:
    payloads = _state_payload(conn, "WorkspaceRevision")
    if not payloads:
        raise S6BriefError("資料庫副本沒有 WorkspaceRevision。")
    return max(payloads.values(), key=lambda row: int(row.get("revision", 0)))


def _load_bag_features(conn: sqlite3.Connection, workspace: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    dispositions = [
        d for d in workspace.get("feature_dispositions", [])
        if d.get("feature_kind") == "building" and d.get("disposition") == "preserve"
    ]
    artifact_ids = sorted({str(d["source_artifact_id"]) for d in dispositions})
    features_by_id: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact_id in artifact_ids:
        artifact, path = _verified_artifact(conn, artifact_id)
        artifacts[artifact_id] = artifact
        for feature in _geojson_features(path):
            identifier = str(feature.get("properties", {}).get("identificatie", ""))
            if identifier:
                features_by_id[identifier] = feature
    return features_by_id, artifacts


def _geometry_from_feature(feature: dict[str, Any]) -> Any:
    geometry = shape(feature["geometry"])
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    if geometry.is_empty or not geometry.is_valid:
        raise S6BriefError(f"來源圖徵幾何無效：{feature.get('properties', {})}")
    return geometry


def _bag_floor_rows(
    conn: sqlite3.Connection,
    workspace: dict[str, Any],
    site: Any,
    features_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[Any], dict[str, Any]]:
    from urban_design.constraint_sets import constraint_set_payload_digest
    from urban_design.morphology.floor_estimate import estimate_floor_count_from_3dbag
    from urban_design.three_d_bag import load_3dbag_height_table

    height_artifact_id = "artifact-3dbag-height-table-study-area-v5-buffer500m-v2025-09-03"
    height_artifact, height_path = _verified_artifact(conn, height_artifact_id)
    table = load_3dbag_height_table(height_path)
    constraints = _state_payload(conn, "ConstraintSet", "constraint-set-d2-a-20261001")
    decision_id = "decision-976f0a79dd914be7aa52cae1fd7ade27"
    decision = _state_payload(conn, "HumanDecision", decision_id)
    floor_height = float(next(c["value"] for c in constraints["constraints"] if c["name"] == "standard_floor_height"))
    approved_height = (
        decision.get("status") == "approved"
        and decision.get("target_id") == constraints.get("id")
        and decision.get("target_version") == constraints.get("version")
        and decision.get("target_payload_digest") == constraint_set_payload_digest(constraints)
    )
    floor_status = "APPROVED" if approved_height else "FIXTURE_ONLY"
    # The approved 3.5m setting is referenced read-only; if the target lineage
    # does not match, the deterministic estimator will reject this instead of
    # silently substituting a fixture value.
    estimate_height = floor_height if approved_height else 3.0
    disposition_by_id = {
        str(row["source_feature_id"]): row
        for row in workspace.get("feature_dispositions", [])
        if row.get("feature_kind") == "building" and row.get("disposition") == "preserve"
    }
    rows: list[dict[str, Any]] = []
    geometries: list[Any] = []
    for bag_id, disposition in sorted(disposition_by_id.items()):
        feature = features_by_id.get(bag_id)
        if feature is None:
            rows.append({
                "id": f"bag:{bag_id}", "bag_id": bag_id, "status": "UNAVAILABLE",
                "reason": "Preserved BAG footprint is absent from the registered normalized tile.",
                "gfa_lower_m2": None, "gfa_upper_m2": None, "footprint_area_m2": None,
            })
            continue
        geometry = _geometry_from_feature(feature).intersection(site)
        if geometry.is_empty:
            rows.append({
                "id": f"bag:{bag_id}", "bag_id": bag_id, "status": "UNAVAILABLE",
                "reason": "Preserved BAG footprint does not intersect StudyArea v5.",
                "gfa_lower_m2": None, "gfa_upper_m2": None, "footprint_area_m2": 0.0,
            })
            continue
        props = feature.get("properties", {})
        use = str(props.get("gebruiksdoel") or "")
        bag_status = str(props.get("status") or "")
        footprint_area = float(geometry.area)
        record: dict[str, Any] = {
            "id": f"bag:{bag_id}", "bag_id": bag_id, "status": "ESTIMATE",
            "disposition": disposition.get("disposition"), "source_artifact_id": disposition.get("source_artifact_id"),
            "bag_status": bag_status, "bag_use": use, "footprint_area_m2": footprint_area,
        }
        if "gesloopt" in bag_status.casefold():
            # This is the existing J16b project assumption for BAG #5; retain
            # it explicitly and do not treat the footprint as a live building.
            record.update({
                "status": "ASSUMED_COMMANDER", "assumption": "BAG status is Pand gesloopt; existing GFA assumed zero; footprint stays excluded from new massing.",
                "floor_count_lower": 0, "floor_count_upper": 0,
                "gfa_lower_m2": 0.0, "gfa_upper_m2": 0.0,
                "height_above_ground_m": None, "volume_prism_estimate_m3": None,
            })
        else:
            estimate = estimate_floor_count_from_3dbag(
                building_id=f"bag:{bag_id}", bag_id=bag_id, building_use=use,
                height_table=table, floor_height_m=estimate_height,
                floor_height_status=floor_status,
                floor_height_decision_id=decision_id if floor_status == "APPROVED" else None,
            )
            floor = estimate.floor_count
            if isinstance(floor, tuple):
                floor_lower, floor_upper = int(floor[0]), int(floor[1])
            elif isinstance(floor, int):
                floor_lower = floor_upper = floor
            else:
                floor_lower = floor_upper = None
            record.update({
                "status": estimate.status if floor_lower is not None else "UNAVAILABLE",
                "floor_count_lower": floor_lower, "floor_count_upper": floor_upper,
                "floor_height_m": estimate.floor_height_m,
                "floor_height_status": estimate.floor_height_status,
                "floor_height_decision_id": estimate.floor_height_decision_id,
                "roof_p70_height_m": estimate.roof_p70_height_m,
                "ground_height_m": estimate.ground_height_m,
                "height_above_ground_m": (
                    estimate.roof_p70_height_m - estimate.ground_height_m
                    if estimate.roof_p70_height_m is not None and estimate.ground_height_m is not None else None
                ),
                "height_source_artifact_id": height_artifact_id,
                "height_source_sha256": height_artifact.get("sha256"),
                "floor_rule_version": estimate.rule_version,
                "limitations": list(estimate.limitations),
                "gfa_lower_m2": footprint_area * floor_lower if floor_lower is not None else None,
                "gfa_upper_m2": footprint_area * floor_upper if floor_upper is not None else None,
                "volume_prism_estimate_m3": (
                    footprint_area * (estimate.roof_p70_height_m - estimate.ground_height_m)
                    if estimate.roof_p70_height_m is not None and estimate.ground_height_m is not None else None
                ),
            })
        record["geometry"] = mapping(geometry)
        rows.append(record)
        geometries.append(geometry)
    height_source = _source_record(conn, height_artifact_id)
    height_source["vertical_reference"] = table.vertical_reference
    height_source["roof_p70_field"] = table.roof_p70_field
    height_source["ground_height_field"] = table.ground_height_field
    return rows, geometries, height_source


def _retained_roads(conn: sqlite3.Connection, run13: dict[str, Any], osm_path: Path, site: Any) -> tuple[list[dict[str, Any]], list[Any], list[str]]:
    osm_features = _geojson_features(osm_path)
    by_osm_id: dict[str, list[dict[str, Any]]] = {}
    for feature in osm_features:
        props = feature.get("properties", {})
        if props.get("osm_type") == "way" and props.get("osm_id") is not None:
            by_osm_id.setdefault(str(props["osm_id"]), []).append(feature)
    retained_ids = sorted({
        str(row.get("source_id", "")) for row in run13.get("dispositions", [])
        if row.get("disposition") == "retained"
    })
    roads: list[dict[str, Any]] = []
    geometries: list[Any] = []
    missing: list[str] = []
    for source_id in retained_ids:
        match = re.match(r"^way/(\d+)", source_id)
        if not match:
            missing.append(source_id)
            continue
        matches = by_osm_id.get(match.group(1), [])
        if not matches:
            missing.append(source_id)
            continue
        for feature in matches:
            geometry = shape(feature["geometry"])
            if geometry.is_empty:
                continue
            clipped = geometry.intersection(site.buffer(2.0))
            if clipped.is_empty:
                continue
            props = feature.get("properties", {})
            roads.append({
                "id": source_id,
                "name": props.get("tags", {}).get("name"),
                "highway": props.get("tags", {}).get("highway"),
                "geometry": mapping(clipped),
                "source_osm_id": props.get("osm_id"),
            })
            geometries.extend(_line_parts(clipped))
    return roads, geometries, missing


def _entrance_line_links(axis: LineString, entrances: list[dict[str, Any]], roads: list[tuple[str, Any]]) -> dict[str, Any]:
    endpoints = [Point(axis.coords[0]), Point(axis.coords[-1])]
    results = []
    for endpoint_no, endpoint in enumerate(endpoints, start=1):
        ranked_entries = sorted(
            ((endpoint.distance(Point(item["coordinates"])), item) for item in entrances),
            key=lambda pair: (pair[0], str(pair[1].get("id"))),
        )
        ranked_roads = sorted(
            ((endpoint.distance(geometry), road_id) for road_id, geometry in roads),
            key=lambda pair: (pair[0], pair[1]),
        )
        exact: list[dict[str, Any]] = []
        exact.extend({"kind": "入口", "id": item["id"]} for distance, item in ranked_entries if distance <= 0.01)
        exact.extend({"kind": "保留道路", "id": road_id} for distance, road_id in ranked_roads if distance <= 0.01)
        results.append({
            "end": endpoint_no,
            "coordinate_epsg28992": [float(endpoint.x), float(endpoint.y)],
            "exact_connections_within_0_01m": exact,
            "nearest_entrance": (
                {"id": ranked_entries[0][1]["id"], "distance_m": float(ranked_entries[0][0])}
                if ranked_entries else None
            ),
            "nearest_retained_road": (
                {"id": ranked_roads[0][1], "distance_m": float(ranked_roads[0][0])}
                if ranked_roads else None
            ),
        })
    return {"ends": results, "connection_tolerance_m": 0.01, "note_zh": "僅精確量測距離 ≤0.01m 才列為相接；其餘只列最近圖徵及實測距離。"}


def _sample_width_series(sections: list[dict[str, Any]], length_m: float) -> list[dict[str, float]]:
    rows = sorted((r for r in sections if math.isfinite(float(r["station_m"]))), key=lambda r: float(r["station_m"]))
    if not rows:
        return []
    stations = [float(r["station_m"]) for r in rows]
    widths = [float(r["width_m"]) for r in rows]
    targets = [float(v) for v in range(0, int(length_m // 25) * 25 + 1, 25)]
    if not targets or targets[0] != 0.0:
        targets.insert(0, 0.0)
    if abs(targets[-1] - length_m) > 1e-6:
        targets.append(float(length_m))
    result = []
    for target in targets:
        if target <= stations[0]:
            width = widths[0]
        elif target >= stations[-1]:
            width = widths[-1]
        else:
            right = next(i for i, station in enumerate(stations) if station >= target)
            left = right - 1
            span = stations[right] - stations[left]
            weight = (target - stations[left]) / span if span else 0.0
            width = widths[left] * (1 - weight) + widths[right] * weight
        result.append({"station_m": target, "width_m": width})
    return result


def _trapezoid_area(sections: list[dict[str, Any]]) -> float | None:
    rows = sorted(sections, key=lambda r: float(r["station_m"]))
    if len(rows) < 2:
        return None
    return sum(
        (float(b["station_m"]) - float(a["station_m"])) * (float(a["width_m"]) + float(b["width_m"])) / 2
        for a, b in zip(rows, rows[1:])
    )


def _band_geometry(axis: LineString, domain: Any, step_m: float = 25.0) -> Any:
    if axis.is_empty or axis.length < 2:
        return GeometryCollection()
    left_edge: list[tuple[float, float]] = []
    right_edge: list[tuple[float, float]] = []
    stations = [float(v) for v in range(0, int(axis.length // step_m) * int(step_m) + 1, int(step_m))]
    if not stations or stations[0] != 0.0:
        stations.insert(0, 0.0)
    if abs(stations[-1] - axis.length) > 1e-6:
        stations.append(float(axis.length))
    reach = max(200.0, 1.5 * math.hypot(domain.bounds[2] - domain.bounds[0], domain.bounds[3] - domain.bounds[1]) if not domain.is_empty else 200.0)
    for station in stations:
        before = max(0.0, station - 0.5)
        after = min(axis.length, station + 0.5)
        p = axis.interpolate(station)
        a, b = axis.interpolate(before), axis.interpolate(after)
        dx, dy = b.x - a.x, b.y - a.y
        length = math.hypot(dx, dy)
        if length < 1e-8:
            continue
        nx, ny = -dy / length, dx / length
        cross = LineString([(p.x - nx * reach, p.y - ny * reach), (p.x + nx * reach, p.y + ny * reach)])
        cuts = _line_parts(cross.intersection(domain))
        selected = min(cuts, key=lambda line: (line.distance(p), -line.length), default=None)
        if selected is None or selected.distance(p) > 0.05:
            continue
        points = [Point(xy) for xy in selected.coords]
        points.sort(key=lambda q: (q.x - p.x) * nx + (q.y - p.y) * ny)
        lo, hi = points[0], points[-1]
        right_edge.append((float(lo.x), float(lo.y)))
        left_edge.append((float(hi.x), float(hi.y)))
    if len(left_edge) < 2 or len(right_edge) < 2:
        return GeometryCollection()
    try:
        corridor = Polygon(left_edge + list(reversed(right_edge)))
        if not corridor.is_valid:
            corridor = corridor.buffer(0)
        return _polygonal(corridor.intersection(domain))
    except (ValueError, TypeError):
        return GeometryCollection()


def _precedent_library(kb_root: Path) -> list[dict[str, Any]]:
    directory = kb_root / "knowledge/v2/topics/MOR/precedents"
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("*.md"), key=lambda p: p.name.casefold()):
        text = path.read_text(encoding="utf-8")
        first = next((line.strip().lstrip("# ") for line in text.splitlines() if line.strip()), path.stem)
        if "｜" in first:
            local, international = first.split("｜", 1)
            aliases = [local.strip(), international.strip()]
        else:
            aliases = [first.strip()]
        extra = {"阿姆斯特丹舊南區": ["Plan Zuid", "Berlage Plan Zuid", "Oud-Zuid", "Amsterdam-Zuid", "阿姆斯特丹南區計畫"]}
        for key, more in extra.items():
            if any(key in a for a in aliases):
                aliases = aliases + more
        records.append({
            "name": aliases[0], "title": first, "aliases": aliases,
            "path": str(path), "sha256": _sha256(path),
        })
    return records


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    low = int(math.floor(position))
    high = int(math.ceil(position))
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def _syntax_context(mode: str, radius_m: float, run_root: Path, site: Any, entrances: list[dict[str, Any]], osm_name_by_id: dict[str, str]) -> dict[str, Any]:
    path = run_root / f"radial-0-{mode}-syntax.json"
    if not path.is_file():
        return {"status": "UNAVAILABLE", "mode": mode, "radius_m": radius_m, "reason": f"Missing {path.name}"}
    document = _json_read(path)
    if document.get("status") != "COMPUTED" or document.get("mode") != mode or float(document.get("radius_m", -1)) != radius_m:
        return {"status": "UNAVAILABLE", "mode": mode, "radius_m": radius_m, "reason": "run-13 baseline metadata does not match requested mode/radius"}
    before = document.get("before", {})
    metrics = before.get("metrics", {})
    segments = before.get("segments", [])
    values = [float(row["nain"]) for row in segments if isinstance(row.get("nain"), (int, float)) and math.isfinite(float(row["nain"]))]
    threshold = metrics.get("high_threshold_nain")
    if threshold is None:
        threshold = _percentile(values, 60)
    threshold_value = float(threshold) if threshold is not None else None
    entry_sources = {
        str(source_id)
        for entrance in entrances
        for source_ids in entrance.get("source_ids", {}).values()
        for source_id in source_ids
    }
    entrances_by_source: dict[str, list[dict[str, Any]]] = {}
    for entrance in entrances:
        for source_ids in entrance.get("source_ids", {}).values():
            for source_id in source_ids:
                entrances_by_source.setdefault(str(source_id), []).append(entrance)
    boundary = site.boundary
    candidate_rows: list[dict[str, Any]] = []
    boundary_buffer = site.buffer(0.05)
    # The baseline can contain tens of thousands of rows; cheaply cull by bbox
    # before the exact geometry predicate.
    minx, miny, maxx, maxy = boundary_buffer.bounds
    for row in segments:
        value = row.get("nain")
        if threshold_value is None or not isinstance(value, (int, float)) or float(value) < threshold_value:
            continue
        if row.get("inside_site"):
            continue
        coords = row.get("coordinates") or []
        if len(coords) < 2:
            continue
        xs = [float(p[0]) for p in coords]
        ys = [float(p[1]) for p in coords]
        if max(xs) < minx or min(xs) > maxx or max(ys) < miny or min(ys) > maxy:
            continue
        line = LineString(coords)
        if not line.intersects(boundary_buffer):
            continue
        source_line_id = str(row.get("source_line_id", ""))
        source_way = source_line_id.split("::", 1)[0]
        intersection = line.intersection(boundary)
        if intersection.is_empty and source_way not in entry_sources:
            continue
        points: list[list[float]] = []
        if not intersection.is_empty:
            if intersection.geom_type == "Point":
                points = [[float(intersection.x), float(intersection.y)]]
            elif intersection.geom_type == "MultiPoint":
                points = [[float(point.x), float(point.y)] for point in intersection.geoms]
            elif intersection.geom_type in {"LineString", "MultiLineString"}:
                lines = _line_parts(intersection)
                points = [[float(lines[0].interpolate(0.5, normalized=True).x), float(lines[0].interpolate(0.5, normalized=True).y)]] if lines else []
        candidate_rows.append({
            "source_line_id": source_way,
            "segment_id": row.get("id"),
            "nain": float(value),
            "boundary_points_epsg28992": points,
            "entrance_source_match": source_way in entry_sources,
            "entrance_matches": [
                {"id": entrance["id"], "coordinates_epsg28992": entrance["coordinates"], "modes": entrance.get("modes", [])}
                for entrance in entrances_by_source.get(source_way, [])
            ],
            "geometry": mapping(line),
        })
    grouped: dict[str, dict[str, Any]] = {}
    for row in candidate_rows:
        key = str(row["source_line_id"])
        group = grouped.setdefault(key, {
            "source_line_id": key,
            "road_name": osm_name_by_id.get(key),
            "segments": [], "boundary_points_epsg28992": [], "nain_values": [],
            "entrance_source_match": False, "entrance_matches": {},
        })
        group["segments"].append({"id": row["segment_id"], "nain": row["nain"], "geometry": row["geometry"]})
        group["boundary_points_epsg28992"].extend(row["boundary_points_epsg28992"])
        group["nain_values"].append(row["nain"])
        group["entrance_source_match"] = group["entrance_source_match"] or row["entrance_source_match"]
        for entrance in row["entrance_matches"]:
            group["entrance_matches"][entrance["id"]] = entrance
    road_rows = []
    for key in sorted(grouped):
        group = grouped[key]
        unique_points = sorted({(round(p[0], 3), round(p[1], 3)) for p in group.pop("boundary_points_epsg28992")})
        vals = group.pop("nain_values")
        road_rows.append({
            **group,
            "entrance_matches": [group["entrance_matches"][key] for key in sorted(group["entrance_matches"])],
            "connection_basis": "same normalized OSM source way id matched to J9b/run-13 entrance; syntax segment need not intersect boundary geometry" if group["entrance_source_match"] else "exact boundary intersection",
            "boundary_points_epsg28992": [list(p) for p in unique_points],
            "segment_count": len(group["segments"]),
            "nain_min": min(vals), "nain_max": max(vals),
        })
    return {
        "status": "EXPLORATORY",
        "mode": mode,
        "radius_m": radius_m,
        "source_path": str(path),
        "source_sha256": _sha256(path),
        "formula_version": document.get("formula_version"),
        "evidence_level": document.get("evidence_level"),
        "formal_result_eligible": document.get("formal_result_eligible"),
        "baseline_segment_count": len(values),
        "baseline_nain_percentiles": {
            f"p{pct}": _percentile(values, pct) for pct in (25, 40, 50, 60, 75, 80, 90, 95)
        },
        "high_threshold_nain": threshold_value,
        "high_threshold_definition": metrics.get("high_definition", "run-13 baseline high-Nain threshold"),
        "threshold_source": "before.metrics.high_threshold_nain" if metrics.get("high_threshold_nain") is not None else "computed from baseline segment NAIN values",
        "external_high_integration_connections": road_rows,
        "limitations": document.get("limitations", []),
    }


def _constraint_value(constraint_set: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((row for row in constraint_set.get("constraints", []) if row.get("name") == name), None)


def _study_boundary(conn: sqlite3.Connection) -> tuple[dict[str, Any], Path, Any]:
    project = _state_payload(conn, "Project", "rotterdam-m4h-pilot-project")
    study = _state_payload(conn, "StudyArea", str(project["active_study_area_id"]))
    if study.get("status") != "CONFIRMED_FOR_EXPLORATION" or study.get("horizontal_crs") != "EPSG:28992":
        raise S6BriefError("active StudyArea 未確認或 CRS 不是 EPSG:28992。")
    artifact, path = _verified_artifact(conn, str(study["geometry_artifact_id"]))
    if artifact.get("sha256") != study.get("artifact_sha256"):
        raise S6BriefError("StudyArea 的 DB hash 與 Artifact hash 不一致。")
    site = _json_geometry(_json_read(path))
    if not site.is_valid or site.is_empty or site.geom_type not in {"Polygon", "MultiPolygon"}:
        raise S6BriefError("StudyArea 幾何無效或非面。")
    return study, path, site


def _load_facts(database: Path, run_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not run_root.is_dir():
        raise S6BriefError(f"run-13 network root 不存在：{run_root}")
    run_inputs_path = run_root / "inputs.json"
    run13 = _json_read(run_inputs_path)
    conn = _connect_copy_database(database)
    try:
        study, study_path, site = _study_boundary(conn)
        workspace = _current_workspace(conn)
        if workspace.get("status") != "DRAFT":
            raise S6BriefError(f"WorkspaceRevision 不是 DRAFT：{workspace.get('status')}")
        # Read the exact registered sources from this SQLite backup and fail
        # closed on any path/hash mismatch.
        water_id = "artifact-pdok-bgt-waterdeel-p001-normalized-3390e215019805a1"
        osm_id = "artifact-osm-overpass-v5-normalized-3390e215019805a1"
        water_source = _source_record(conn, water_id)
        osm_source = _source_record(conn, osm_id)
        water_features = _geojson_features(Path(water_source["path"]))
        water_polygons = []
        for feature in water_features:
            geom = _polygonal(shape(feature["geometry"]))
            if not geom.is_empty and geom.intersects(site):
                cut = geom.intersection(site)
                if not cut.is_empty:
                    water_polygons.extend(_polygon_parts(cut))
        water = unary_union(water_polygons) if water_polygons else GeometryCollection()
        land = _polygonal(site.difference(water))

        bag_features, bag_artifacts = _load_bag_features(conn, workspace)
        retained_rows, retained_geometries, height_source = _bag_floor_rows(conn, workspace, site, bag_features)
        retained_map: dict[str, Any] = {}
        for row in retained_rows:
            geom_obj = row.get("geometry")
            if geom_obj:
                retained_map[row["id"]] = shape(geom_obj)
        from urban_design.constraint_sets import constraint_set_payload_digest
        from urban_design.generation import block_first, multimodal_network

        network_rules = multimodal_network.NetworkRules()
        _land, buildable, _kept = block_first._buildable(site, water, retained_map, network_rules)
        axes, meta = block_first.strip_axes(buildable, "grid", sample_step_m=10, segment_m=80)
        strip_sections = meta.get("sections", [])
        main_axes: dict[str, list[LineString]] = {}
        for axis in axes:
            if axis.get("role") in {"main", "path", "service"}:
                main_axes.setdefault(str(axis["strip_id"]), []).append(axis["geometry"])

        # Retained city roads are selected by run-13's explicit disposition and
        # matched back to normalized OSM features by the source way ID.
        roads, retained_road_geometries, missing_road_ids = _retained_roads(
            conn, run13, Path(osm_source["path"]), site
        )
        road_name_by_id = {
            str(feature.get("properties", {}).get("osm_id")): str(feature.get("properties", {}).get("tags", {}).get("name", ""))
            for feature in _geojson_features(Path(osm_source["path"]))
            if feature.get("properties", {}).get("osm_id") is not None
        }
        entrances = [
            {"id": row["id"], "coordinates": row["coordinates"], "modes": row.get("modes", []),
             "weight": row.get("weight"), "diagnosis_provenance": row.get("diagnosis_provenance"),
             "source_ids": row.get("source_ids", {})}
            for row in run13.get("entrances", [])
        ]
        retained_road_pairs: list[tuple[str, Any]] = []
        for road in roads:
            road_geom = shape(road["geometry"])
            retained_road_pairs.extend((road["id"], line) for line in _line_parts(road_geom))

        strip_rows = []
        for record in meta.get("strips", []):
            strip_id = str(record["id"])
            sections = [row for row in strip_sections if row.get("strip_id") == strip_id]
            length_m = float(record["length_m"])
            width_series = _sample_width_series(sections, length_m)
            widths = [float(row["width_m"]) for row in sections]
            area = _trapezoid_area(sections)
            geometries = main_axes.get(strip_id, [])
            band_parts = [_band_geometry(line, buildable) for line in geometries]
            band_parts = [geom for geom in band_parts if not geom.is_empty]
            band = _polygonal(unary_union(band_parts)) if band_parts else GeometryCollection()
            axis_union = unary_union(geometries) if geometries else GeometryCollection()
            first_axis = max(geometries, key=lambda geom: geom.length) if geometries else None
            strip_row = {
                "id": strip_id,
                "length_m": length_m,
                "orientation_deg_from_east_ccw": float(record["heading_deg"]),
                "width_sampling_step_m": float(meta.get("sample_step_m", 10)),
                "width_series_every_25m": width_series,
                "width_min_m": min(widths) if widths else None,
                "width_max_m": max(widths) if widths else None,
                "area_m2": area,
                "area_method": "J16b 10m cross-section widths; trapezoidal integration along longitudinal station; sampled estimate.",
                "axes_length_m": float(sum(g.length for g in geometries)),
                "ends": _entrance_line_links(first_axis, entrances, retained_road_pairs) if first_axis else {"ends": [], "status": "UNAVAILABLE"},
                "axis_geometry": mapping(axis_union) if not axis_union.is_empty else None,
                "band_geometry_schematic": mapping(band) if not band.is_empty else None,
            }
            strip_rows.append(strip_row)

        d2 = _state_payload(conn, "ConstraintSet", "constraint-set-d2-a-20261001")
        far = _constraint_value(d2, "far_upper_limit")
        height = _constraint_value(d2, "height_upper_limit")
        first_floor = _constraint_value(d2, "first_floor_height")
        standard_floor = _constraint_value(d2, "standard_floor_height")
        if not all((far, height, first_floor, standard_floor)):
            raise S6BriefError("D2 A 缺少 FAR、高度或層高記錄。")
        decision = _state_payload(conn, "HumanDecision", "decision-976f0a79dd914be7aa52cae1fd7ade27")
        current_set_digest = constraint_set_payload_digest(d2)
        approval_current_revision_matches = (
            decision.get("status") == "approved"
            and decision.get("target_id") == d2.get("id")
            and decision.get("target_version") == d2.get("version")
            and decision.get("target_payload_digest") == current_set_digest
        )
        retained_upper = None if any(r.get("gfa_upper_m2") is None for r in retained_rows) else sum(float(r["gfa_upper_m2"]) for r in retained_rows)
        retained_lower = None if any(r.get("gfa_lower_m2") is None for r in retained_rows) else sum(float(r["gfa_lower_m2"]) for r in retained_rows)
        land_area = float(land.area)
        far_max = float(far["value"])
        new_gfa_budget = max(0.0, far_max * land_area - retained_upper) if retained_upper is not None else None

        workspace_zones = workspace.get("spatial_brief", {}).get("zones", [])
        zones = [{
            "zone_id": row.get("zone_id"), "name": row.get("name"), "status": row.get("status"),
            "area_m2": row.get("area_m2"), "target_use": row.get("target_use"),
            "target_far": row.get("target_far"), "target_coverage_ratio": row.get("target_coverage_ratio"),
            "target_height_m": row.get("target_height_m"), "crs": row.get("crs"),
            "draft_preferences": row.get("draft_preferences", []),
            "geometry": row.get("geometry"),
        } for row in workspace_zones]
        dakpark_path = REPO_ROOT / "data/context/dakpark-osm-epsg28992.geojson"
        dakpark_doc = _json_read(dakpark_path)
        park_feature = next((f for f in dakpark_doc.get("features", []) if f.get("properties", {}).get("name") == "Dakpark"), None)
        if park_feature is None:
            raise S6BriefError("Dakpark OSM GeoJSON 找不到名稱 Dakpark 的圖徵。")
        dakpark_geometry = shape(park_feature["geometry"])
        if not dakpark_geometry.is_valid:
            dakpark_geometry = dakpark_geometry.buffer(0)

        syntax_ped = _syntax_context("pedestrian", 800.0, run_root, site, entrances, {f"way/{k}": v for k, v in road_name_by_id.items()})
        syntax_bike = _syntax_context("bicycle", 2000.0, run_root, site, entrances, {f"way/{k}": v for k, v in road_name_by_id.items()})
        j9b = run13.get("J9b", {})
        precedent_records = _precedent_library(KB_ROOT_DEFAULT)
        bag_source_records = [_source_record(conn, artifact_id) for artifact_id in sorted(bag_artifacts)]
        source_records = [
            _source_record(conn, str(study["geometry_artifact_id"])), water_source, osm_source,
            *bag_source_records, height_source,
        ]
        # Source records are keyed once but preserve all registration metadata.
        sources_by_id = {str(row["artifact_id"]): row for row in source_records}
        facts: dict[str, Any] = {
            "schema_version": "s6-site-facts-v1",
            "generated_at_utc": _utc_now(),
            "evidence_status": "EXPLORATORY_INPUT_PACKAGE",
            "project_id": "rotterdam-m4h-pilot-project",
            "site": {
                "study_area_id": study["id"], "study_area_version": study["version"],
                "status": study["status"], "horizontal_crs": study["horizontal_crs"], "units": study["units"],
                "area_including_water_m2": float(site.area), "land_area_m2": land_area,
                "water_area_intersection_m2": float(water.area),
            },
            "buildable": {
                "logic": "J16b block_first._buildable + strip_axes；扣水域、水岸 15m band、保留建物 3m setback；道路另外疊圖供判讀。",
                "status": "COMPUTED_DRAFT_GEOMETRY",
                "area_m2": float(buildable.area),
                "sample_step_m": int(meta.get("sample_step_m", 10)),
                "strip_segment_m": 80,
                "strips": strip_rows,
                "waterfront_band_m": float(network_rules.waterfront_band_m),
            },
            "waterfront": {
                "source_artifact_id": water_id,
                "water_area_within_site_m2": float(water.area),
                "waterfront_band_width_m": float(network_rules.waterfront_band_m),
                "band_area_m2": float(site.intersection(water.buffer(network_rules.waterfront_band_m)).area - water.area),
                "method": "BGT waterdeel polygons intersecting StudyArea v5, then J16b 15m band buffer; area is geometric overlay.",
            },
            "retained_buildings": retained_rows,
            "retained_city_roads": {
                "run13_disposition": "retained",
                "count_matched_features": len(roads),
                "missing_source_ids": missing_road_ids,
                "features": roads,
                "note_zh": "沿 run-13 dispositions 的 retained way id 回配 normalized OSM；未配到的 source id 明列，不自行補線。",
            },
            "entrances": entrances,
            "external_space_syntax": {
                "pedestrian_800m": syntax_ped,
                "bicycle_2km": syntax_bike,
                "run13_inputs_sha256": _sha256(run_inputs_path),
            },
            "transit": {
                "closest_side": j9b.get("closest_transit_side"),
                "status": j9b.get("status"),
                "created_at": j9b.get("created_at"),
                "source_path": j9b.get("path"),
                "source_sha256": j9b.get("sha256"),
                "entrance_matches": j9b.get("matches", []),
                "limitations": j9b.get("limitations", []),
            },
            "dakpark": {
                "name": "Dakpark", "source_ref": park_feature.get("properties", {}).get("source_ref"),
                "retrieved_utc": park_feature.get("properties", {}).get("retrieved_utc"),
                "elevation_difference_m": park_feature.get("properties", {}).get("elevation_difference_m"),
                "elevation_provenance": park_feature.get("properties", {}).get("elevation_provenance"),
                "elevation_status": "ASSUMED_PORTFOLIO" if park_feature.get("properties", {}).get("elevation_difference_m") is not None else "UNAVAILABLE",
            },
            "zones": {
                "workspace_revision": workspace.get("revision"), "workspace_status": workspace.get("status"),
                "spatial_brief_status": workspace.get("spatial_brief", {}).get("status"),
                "per_zone_use_ratios_exist": any(row.get("target_use") and row.get("target_far") is not None for row in workspace_zones),
                "zone_rows": zones,
                "portfolio_use_ratio_guidance_percent": PORTFOLIO_USE_RANGES,
                "portfolio_guidance_source": "Founder portfolio plan §2.1 (manufacturing 30–40%, office 10–20%, residential 30–50%, facilities 10%); portfolio ranges, not zone allocation or legally adopted zoning.",
                "note_zh": "Workspace zones remain DRAFT_PENDING_HUMAN_DECISION; target FAR, coverage, and height are null, so no per-zone ratio is inferred.",
            },
            "gfa": {
                "denominator": "StudyArea v5 land area after mapped BGT water subtraction",
                "far_min_for_validation": 0.70,
                "far_max": far_max,
                "retained_lower_m2": retained_lower,
                "retained_upper_m2": retained_upper,
                "new_gfa_budget_m2": new_gfa_budget,
                "total_gfa_upper_at_far_max_m2": far_max * land_area,
                "status": "COMPUTED_ESTIMATE" if retained_upper is not None else "UNAVAILABLE_RETAINED_GFA_BOUND",
                "calculation": "new_gfa_budget = max(0, D2-A FAR max × land area − sum(retained upper GFA); null if any retained upper bound is unavailable)",
            },
            "height": {
                "cap_m": float(height["value"]), "first_floor_height_m": float(first_floor["value"]),
                "standard_floor_height_m": float(standard_floor["value"]),
                "constraint_set_id": d2.get("id"), "constraint_set_version": d2.get("version"),
                "constraint_set_status": d2.get("status"), "founder_decision_id": decision.get("id"),
                "founder_decision_status": decision.get("status"),
                "decision_target_version": decision.get("target_version"),
                "decision_payload_digest_matches_current": approval_current_revision_matches,
                "setting_status": "APPROVAL_LINEAGE_MATCHES_CURRENT" if approval_current_revision_matches else "APPROVAL_LINEAGE_CONFLICT",
                "notes_conflict_with_approval": bool(approval_current_revision_matches and any(term in str(d2.get("notes", "")) for term in ("未核准", "未啟用", "待 Founder"))),
                "floor_height_conversion": "first_floor_height + (storeys - 1) × standard_floor_height",
                "note_zh": "數值照 D2-A 記錄；目前 ConstraintSet revision 與 Founder 決定的 target version/digest 若不一致，標為 lineage conflict，不宣稱當前約束已生效。",
            },
            "precedents": precedent_records,
            "limitations": [
                "Space Syntax is exploratory and uses run-13 before-baseline NAIN; it is not observed pedestrian/bicycle flow.",
                "Entrances are J9b local exploratory, inferred and physical gate/opening status is unverified.",
                "D2-A/Workspace settings and zone rows carry their recorded approval and draft status; this package does not adopt a design decision.",
                "Each band area is a trapezoidal estimate from J16b sampled cross-sections; it is not a cadastral area.",
                "Retained-building GFA is an estimate from BAG footprints and 3D BAG roof P70/ground-height records under the referenced floor-height rule.",
            ],
            "sources": list(sources_by_id.values()),
            "geometry": {
                "crs": "EPSG:28992", "site": mapping(site), "water": mapping(water),
                "buildable": mapping(buildable),
                "waterfront_band": mapping(site.intersection(water.buffer(network_rules.waterfront_band_m)).difference(water)),
                "dakpark": mapping(dakpark_geometry),
                "strips": [{"id": row["id"], "geometry": row["band_geometry_schematic"], "axis": row["axis_geometry"]} for row in strip_rows],
                "retained_buildings": [{"id": row["id"], "geometry": row.get("geometry")} for row in retained_rows if row.get("geometry")],
                "retained_roads": [{"id": row["id"], "geometry": row["geometry"]} for row in roads],
                "zones": [{"zone_id": z["zone_id"], "geometry": z.get("geometry")} for z in zones if z.get("geometry")],
                "entrances": [{"id": e["id"], "coordinates": e["coordinates"]} for e in entrances],
                "external_high_roads": {
                    "pedestrian": [segment["geometry"] for road in syntax_ped.get("external_high_integration_connections", []) for segment in road.get("segments", []) if isinstance(segment, dict) and segment.get("geometry")],
                    "bicycle": [segment["geometry"] for road in syntax_bike.get("external_high_integration_connections", []) for segment in road.get("segments", []) if isinstance(segment, dict) and segment.get("geometry")],
                },
            },
        }
        facts["buildable"]["station_spacing_m"] = STATION_STEP_M
        facts["buildable"]["station_adjacency_method_zh"] = (
            "每25m依EPSG:28992帶面和長軸建立橫剖面；入口、Dakpark、水域及保留建物距離從橫剖面中點量測；"
            "水域側別以朝s增加方向的左法線判定；外部高整合道路距離從該站前後各12.5m帶面切片量測。"
        )
        for strip in facts["buildable"]["strips"]:
            strip["stations"] = _build_station_adjacency_rows(strip, facts)
            strip["summary_zh"] = _strip_summary_zh(strip, strip["stations"])
    finally:
        conn.close()
    return facts, {"site": site, "water": water, "land": land, "buildable": buildable,
                   "roads": roads, "entrances": entrances, "dakpark": dakpark_geometry,
                   "retained_buildings": retained_rows, "axes": strip_rows}


def _plot_geometry(
    ax: Any,
    geometry: Any,
    *,
    facecolor: str = "none",
    edgecolor: str = "#333333",
    linewidth: float = 0.8,
    alpha: float = 1.0,
    zorder: int = 1,
    linestyle: str = "solid",
    hatch: str | None = None,
) -> None:
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        x, y = geometry.exterior.xy
        ax.fill(x, y, facecolor=facecolor, edgecolor=edgecolor, linewidth=linewidth, alpha=alpha, zorder=zorder, linestyle=linestyle, hatch=hatch)
        for ring in geometry.interiors:
            hx, hy = ring.xy
            ax.fill(hx, hy, facecolor="#fbfaf6", edgecolor=edgecolor, linewidth=max(0.3, linewidth * 0.6), alpha=1, zorder=zorder + 0.01)
    elif hasattr(geometry, "geoms"):
        for child in geometry.geoms:
            _plot_geometry(ax, child, facecolor=facecolor, edgecolor=edgecolor, linewidth=linewidth, alpha=alpha, zorder=zorder, linestyle=linestyle, hatch=hatch)
    elif geometry.geom_type in {"LineString", "LinearRing"}:
        x, y = geometry.xy
        ax.plot(x, y, color=edgecolor, linewidth=linewidth, alpha=alpha, zorder=zorder, linestyle=linestyle)
    elif geometry.geom_type == "Point":
        ax.scatter([geometry.x], [geometry.y], color=edgecolor, s=12, zorder=zorder)


def _load_render_geometries(facts: dict[str, Any]) -> dict[str, Any]:
    raw = facts.get("geometry", {})
    strip_rows = facts.get("buildable", {}).get("strips", facts.get("strips", []))
    return {
        "site": shape(raw["site"]), "water": shape(raw["water"]),
        "buildable": shape(raw["buildable"]), "waterfront_band": shape(raw["waterfront_band"]),
        "dakpark": shape(raw["dakpark"]),
        "strips": {row["id"]: shape(row["geometry"]) for row in raw.get("strips", []) if row.get("geometry")},
        "axes": {row["id"]: shape(row["axis"]) for row in raw.get("strips", []) if row.get("axis")},
        "strip_lengths": {
            str(row["id"]): float(row["length_m"])
            for row in strip_rows
            if row.get("id") is not None and isinstance(row.get("length_m"), (int, float))
        },
        "retained_buildings": [(row["id"], shape(row["geometry"])) for row in raw.get("retained_buildings", []) if row.get("geometry")],
        "retained_roads": [(row["id"], shape(row["geometry"])) for row in raw.get("retained_roads", []) if row.get("geometry")],
        "zones": [(row["zone_id"], shape(row["geometry"])) for row in raw.get("zones", []) if row.get("geometry")],
        "entrances": raw.get("entrances", []),
        "external_high_roads": raw.get("external_high_roads", {}),
    }


def _figure_font() -> str | None:
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    )
    return next((path for path in candidates if Path(path).is_file()), None)


TYPOLOGY_COLORS = {
    "perimeter": "#d98961", "l_block": "#e7b65a", "slab": "#7c9ea9", "rowhouse": "#9c81a8",
    "point": "#cf7778", "courtyard": "#72a987", "maker_hall": "#808789",
    "retained_reuse": "#6c665b", "park": "#65a87b",
}
TYPOLOGY_LABELS_ZH = {
    "perimeter": "周邊式", "l_block": "L 形", "slab": "板樓", "rowhouse": "連棟",
    "point": "點式", "courtyard": "合院", "maker_hall": "製造廠房",
    "retained_reuse": "保留改造", "park": "公園",
}
STRATEGY_LABELS_ZH = {"radial": "向心", "axial": "軸線", "grid": "網格", "green_service": "綠廊服務"}
ZH_TYPOLOGY_ALIASES = {
    "連棟": "rowhouse", "街屋": "rowhouse", "線性板樓": "slab", "板樓": "slab",
    "淺進深板樓": "slab", "街牆式": "perimeter", "周邊式": "perimeter",
    "合院": "courtyard", "中庭": "courtyard", "點式": "point",
    "maker": "maker_hall", "廠房": "maker_hall", "製造": "maker_hall",
    "保留改造": "retained_reuse", "保留建築": "retained_reuse", "公園": "park",
    "L 形": "l_block", "L形": "l_block", "l 形": "l_block", "綠地": "park", "地景": "park",
}


def _station_length(facts: dict[str, Any], strip_id: str, axis: Any | None = None) -> float | None:
    """Return the brief station domain, falling back to the axis geometry length."""
    length = _load_render_geometries(facts)["strip_lengths"].get(strip_id)
    if isinstance(length, (int, float)) and math.isfinite(float(length)) and float(length) > 0:
        return float(length)
    if axis is not None and not axis.is_empty and float(axis.length) > 0:
        return float(axis.length)
    return None


def _axis_line(axis: Any) -> LineString | None:
    lines = _line_parts(axis) if axis is not None else []
    return max(lines, key=lambda line: line.length, default=None)


def _cross_section_line(axis: LineString, band: Any, station_m: float, station_length_m: float) -> LineString:
    if station_length_m <= 0 or axis.length <= 0:
        raise S6BriefError("帶軸線長度必須大於零。")
    geometric_station = min(axis.length, max(0.0, station_m / station_length_m * axis.length))
    point = axis.interpolate(geometric_station)
    before = axis.interpolate(max(0.0, geometric_station - 0.5))
    after = axis.interpolate(min(axis.length, geometric_station + 0.5))
    dx, dy = after.x - before.x, after.y - before.y
    tangent_length = math.hypot(dx, dy)
    if tangent_length < 1e-8:
        raise S6BriefError(f"無法在帶軸線 s={station_m:.2f}m 建立 10m 橫剖面。")
    nx, ny = -dy / tangent_length, dx / tangent_length
    minx, miny, maxx, maxy = band.bounds
    reach = max(100.0, 2.0 * math.hypot(maxx - minx, maxy - miny))
    return LineString([(point.x - nx * reach, point.y - ny * reach), (point.x + nx * reach, point.y + ny * reach)])


def _slice_strip_cells(
    axis: LineString,
    band: Any,
    start_m: float,
    end_m: float,
    station_length_m: float,
    step_m: float = 10.0,
) -> list[Any]:
    """Build non-overlapping band slices bounded by axis-normal cross-sections."""
    if band is None or band.is_empty:
        return []
    if not all(math.isfinite(float(value)) for value in (start_m, end_m, station_length_m, step_m)):
        raise S6BriefError("帶切片站距必須是有限數值。")
    if start_m < 0 or end_m < start_m or end_m > station_length_m + 1e-6 or step_m <= 0:
        raise S6BriefError(f"帶切片範圍 s={start_m:.2f}–{end_m:.2f}m 不在 0–{station_length_m:.2f}m 內。")
    if end_m - start_m <= 1e-8:
        return []
    cut_stations: set[float] = set()
    if start_m > 1e-8:
        cut_stations.add(float(start_m))
    if end_m < station_length_m - 1e-8:
        cut_stations.add(float(end_m))
    next_cut = (math.floor(start_m / step_m) + 1) * step_m
    while next_cut < end_m - 1e-8:
        cut_stations.add(float(next_cut))
        next_cut += step_m

    pieces = _polygon_parts(_polygonal(band))
    for station in sorted(cut_stations):
        section = _cross_section_line(axis, band, station, station_length_m)
        divided: list[Any] = []
        for piece in pieces:
            try:
                divided.extend(_polygon_parts(split_geometry(piece, section)))
            except ValueError:
                divided.append(piece)
        pieces = divided

    cells: list[Any] = []
    for piece in pieces:
        representative = piece.representative_point()
        station = axis.project(representative) / axis.length * station_length_m
        if start_m - 1e-6 <= station <= end_m + 1e-6:
            cells.append(piece)
    return cells


def _slice_strip_geometry(
    axis: LineString,
    band: Any,
    start_m: float,
    end_m: float,
    station_length_m: float,
    step_m: float = 10.0,
) -> Any:
    cells = _slice_strip_cells(axis, band, start_m, end_m, station_length_m, step_m)
    return unary_union(cells) if cells else GeometryCollection()


def _partition_strip_geometry(axis: LineString, band: Any, station_length_m: float, step_m: float = 10.0) -> list[Any]:
    return _slice_strip_cells(axis, band, 0.0, station_length_m, station_length_m, step_m)


def _width_at_station(width_series: list[dict[str, Any]], station_m: float) -> float | None:
    rows = sorted(
        (
            (float(row["station_m"]), float(row["width_m"]))
            for row in width_series
            if isinstance(row.get("station_m"), (int, float))
            and isinstance(row.get("width_m"), (int, float))
            and math.isfinite(float(row["station_m"]))
            and math.isfinite(float(row["width_m"]))
        ),
        key=lambda pair: pair[0],
    )
    if not rows:
        return None
    if station_m <= rows[0][0]:
        return rows[0][1]
    if station_m >= rows[-1][0]:
        return rows[-1][1]
    for (left_station, left_width), (right_station, right_width) in zip(rows, rows[1:]):
        if left_station <= station_m <= right_station:
            fraction = (station_m - left_station) / (right_station - left_station) if right_station != left_station else 0.0
            return left_width * (1 - fraction) + right_width * fraction
    return None


def _build_station_adjacency_rows(strip_row: dict[str, Any], facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Build measured 25m station facts from the package's EPSG:28992 geometries."""
    site = facts.get("site", {})
    geometry = facts.get("geometry", {})
    if geometry.get("crs") != "EPSG:28992" or site.get("horizontal_crs") != "EPSG:28992" or site.get("units") != "m":
        raise S6BriefError("逐段鄰接量測要求 facts 幾何與基地明確使用 EPSG:28992、單位 m。")

    strip_id = str(strip_row.get("id", ""))
    geometry_row = next((row for row in geometry.get("strips", []) if str(row.get("id")) == strip_id), None)
    if not geometry_row or not geometry_row.get("geometry") or not geometry_row.get("axis"):
        raise S6BriefError(f"逐段鄰接量測缺少 {strip_id} 的帶面或長軸幾何。")
    band = shape(geometry_row["geometry"])
    axis = _axis_line(shape(geometry_row["axis"]))
    length_m = strip_row.get("length_m")
    if axis is None or axis.is_empty or axis.length <= 0 or not isinstance(length_m, (int, float)) or isinstance(length_m, bool) or not math.isfinite(float(length_m)) or float(length_m) <= 0:
        raise S6BriefError(f"逐段鄰接量測缺少有效的 {strip_id} 軸線或帶長。")
    length_m = float(length_m)

    water_data = geometry.get("water")
    water = shape(water_data) if water_data else GeometryCollection()
    if not water.is_valid:
        water = water.buffer(0)
    dakpark_data = geometry.get("dakpark")
    dakpark = shape(dakpark_data) if dakpark_data else GeometryCollection()
    if not dakpark.is_valid:
        dakpark = dakpark.buffer(0)

    entrances = []
    for row in facts.get("entrances", geometry.get("entrances", [])):
        coordinates = row.get("coordinates", row.get("coordinates_epsg28992"))
        if row.get("id") is not None and isinstance(coordinates, list) and len(coordinates) >= 2:
            entrances.append((str(row["id"]), Point(float(coordinates[0]), float(coordinates[1]))))

    retained = []
    for row in geometry.get("retained_buildings", []):
        if row.get("id") is not None and row.get("geometry"):
            geom = shape(row["geometry"])
            if not geom.is_empty:
                retained.append((str(row["id"]), geom))

    high_roads = []
    for syntax_key in ("pedestrian_800m", "bicycle_2km"):
        syntax = facts.get("external_space_syntax", {}).get(syntax_key, {})
        mode = str(syntax.get("mode", syntax_key))
        for connection in syntax.get("external_high_integration_connections", []):
            source_id = str(connection.get("source_line_id", "unknown-road"))
            for index, segment in enumerate(connection.get("segments", [])):
                raw = segment.get("geometry") if isinstance(segment, dict) else None
                if raw:
                    road = shape(raw)
                    if not road.is_empty:
                        segment_id = str(segment.get("id", index))
                        high_roads.append((f"{mode}:{source_id}:{segment_id}", road))
    if not high_roads:
        for mode, records in sorted(geometry.get("external_high_roads", {}).items()):
            for index, raw in enumerate(records if isinstance(records, list) else []):
                if raw:
                    road = shape(raw)
                    if not road.is_empty:
                        high_roads.append((f"{mode}:{index}", road))
    syntax_statuses = [
        facts.get("external_space_syntax", {}).get("pedestrian_800m", {}).get("status"),
        facts.get("external_space_syntax", {}).get("bicycle_2km", {}).get("status"),
    ]
    road_inventory_known = bool(high_roads) or any(status in {"EXPLORATORY", "COMPUTED"} for status in syntax_statuses)

    station_values = sorted({
        round(float(row["station_m"]), 6)
        for row in strip_row.get("width_series_every_25m", [])
        if isinstance(row.get("station_m"), (int, float)) and math.isfinite(float(row["station_m"]))
    })
    station_values = [value for value in station_values if -1e-6 <= value <= length_m + 1e-6]
    if not station_values:
        station_values = [float(value) for value in range(0, int(length_m // STATION_STEP_M) * int(STATION_STEP_M) + 1, int(STATION_STEP_M))]
    if not station_values or abs(station_values[0]) > 1e-6:
        station_values.insert(0, 0.0)
    if abs(station_values[-1] - length_m) > 1e-6:
        station_values.append(length_m)

    result = []
    for station_m in station_values:
        geometry_station_m = station_m
        cross_section = _cross_section_line(axis, band, geometry_station_m, length_m).intersection(band)
        sections = _line_parts(cross_section)
        # A strip axis can start a few centimetres outside the reconstructed band.
        # At an endpoint only, use the nearest interior cross-section and retain
        # the measured station separately from the geometry station used.
        if not sections and station_m <= 1e-6:
            for offset_m in (step / 10 for step in range(1, int(STATION_STEP_M / 2 * 10) + 1)):
                geometry_station_m = min(length_m, station_m + offset_m)
                sections = _line_parts(_cross_section_line(axis, band, geometry_station_m, length_m).intersection(band))
                if sections:
                    break
        elif not sections and abs(station_m - length_m) <= 1e-6:
            for offset_m in (step / 10 for step in range(1, int(STATION_STEP_M / 2 * 10) + 1)):
                geometry_station_m = max(0.0, station_m - offset_m)
                sections = _line_parts(_cross_section_line(axis, band, geometry_station_m, length_m).intersection(band))
                if sections:
                    break
        axis_point = axis.interpolate(min(axis.length, max(0.0, geometry_station_m / length_m * axis.length)))
        section = min(sections, key=lambda line: (line.distance(axis_point), -line.length), default=None)
        if section is None or section.is_empty or section.length <= 0:
            raise S6BriefError(f"{strip_id} s={station_m:g}m 無法從可建帶幾何建立橫剖面中點。")
        midpoint = section.interpolate(0.5, normalized=True)
        width_m = _width_at_station(strip_row.get("width_series_every_25m", []), station_m)
        if width_m is None:
            width_m = float(section.length)

        nearest_entrances = [
            {"id": entry_id, "distance_m": float(midpoint.distance(point))}
            for entry_id, point in sorted(
                entrances,
                key=lambda item: (midpoint.distance(item[1]), item[0]),
            )[:2]
        ]
        dakpark_distance = float(midpoint.distance(dakpark)) if not dakpark.is_empty else None
        water_distance = float(midpoint.distance(water)) if not water.is_empty else None
        water_side = None
        if not water.is_empty:
            tangent_before = axis.interpolate(max(0.0, geometry_station_m / length_m * axis.length - 0.5))
            tangent_after = axis.interpolate(min(axis.length, geometry_station_m / length_m * axis.length + 0.5))
            dx = tangent_after.x - tangent_before.x
            dy = tangent_after.y - tangent_before.y
            tangent_length = math.hypot(dx, dy)
            if tangent_length > 1e-8:
                water_point = nearest_points(midpoint, water.boundary)[1]
                signed_side = (water_point.x - midpoint.x) * (-dy / tangent_length) + (water_point.y - midpoint.y) * (dx / tangent_length)
                water_side = "left" if signed_side > 1e-6 else "right" if signed_side < -1e-6 else "on_axis"

        nearest_building = min(
            ((float(midpoint.distance(building)), building_id) for building_id, building in retained),
            default=(None, None),
        )
        cell_start = max(0.0, station_m - STATION_STEP_M / 2)
        cell_end = min(length_m, station_m + STATION_STEP_M / 2)
        station_cell = _slice_strip_geometry(axis, band, cell_start, cell_end, length_m, step_m=STATION_STEP_M)
        if station_cell.is_empty:
            station_cell = section
        nearest_road = min(
            ((float(station_cell.distance(road)), road_id) for road_id, road in high_roads),
            default=(None, None),
        )
        adjacent = (
            nearest_road[0] <= EXTERNAL_HIGH_ROAD_ADJACENCY_M + 1e-6
            if nearest_road[0] is not None
            else (False if road_inventory_known else None)
        )
        result.append({
            "station_m": float(station_m),
            "cross_section_geometry_station_m": float(geometry_station_m),
            "station_cell_range_m": [float(cell_start), float(cell_end)],
            "width_m": float(width_m),
            "midpoint_epsg28992": [float(midpoint.x), float(midpoint.y)],
            "nearest_entrances": nearest_entrances,
            "dakpark_distance_m": dakpark_distance,
            "water_distance_m": water_distance,
            "water_side_from_axis": water_side,
            "water_side_zh": {"left": "左", "right": "右", "on_axis": "中線"}.get(water_side, "未知"),
            "nearest_retained_building": (
                {"id": nearest_building[1], "distance_m": nearest_building[0]}
                if nearest_building[1] is not None else None
            ),
            "nearest_retained_building_distance_m": nearest_building[0],
            "nearest_external_high_integration_road": (
                {"id": nearest_road[1], "distance_m": nearest_road[0]}
                if nearest_road[1] is not None else None
            ),
            "adjacent_external_high_integration_road": adjacent,
        })
    return result


def _strip_summary_zh(strip_row: dict[str, Any], stations: list[dict[str, Any]]) -> str:
    strip_id = str(strip_row.get("id", "未命名帶"))
    length_m = float(strip_row.get("length_m", 0.0))
    if not stations:
        return f"{strip_id} 的逐段位置資料不可用。"
    first = min(stations, key=lambda row: abs(float(row.get("station_m", 0.0))))
    last = min(stations, key=lambda row: abs(float(row.get("station_m", 0.0)) - length_m))
    dakpark_rows = [row for row in stations if isinstance(row.get("dakpark_distance_m"), (int, float))]
    nearest_dakpark = min(dakpark_rows, key=lambda row: float(row["dakpark_distance_m"]), default=None)
    sides = [row.get("water_side_zh") for row in stations if row.get("water_side_zh") in {"左", "右"}]
    side = max(set(sides), key=lambda value: (sides.count(value), value), default=None)
    side_text = f"水域多在軸線{side}側" if side and sides.count(side) / len(sides) >= 0.6 else "水域側別隨里程變化或未能判定"

    def end_text(label: str, row: dict[str, Any]) -> str:
        entries = row.get("nearest_entrances", [])
        if not entries:
            return f"{label}端最近入口未知"
        nearest = entries[0]
        return f"{label}端近{nearest['id']}（{float(nearest['distance_m']):.1f}m）"

    dakpark_text = (
        f"Dakpark最近於s={float(nearest_dakpark['station_m']):g}m（{float(nearest_dakpark['dakpark_distance_m']):.1f}m）"
        if nearest_dakpark else "Dakpark距離未能量測"
    )
    return (
        f"{strip_id} 長軸里程0–{length_m:g}m；{end_text('s=0', first)}、{end_text('s=L', last)}；"
        f"{dakpark_text}；{side_text}（左／右以朝s增加方向判定）。"
    )


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted((min(float(a), float(b)), max(float(a), float(b))) for a, b in intervals if float(b) - float(a) > 1e-8):
        if merged and start <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _width_intervals_at_least(strip_row: dict[str, Any], threshold_m: float) -> list[tuple[float, float]]:
    samples = sorted(
        (
            (float(row["station_m"]), float(row["width_m"]))
            for row in strip_row.get("width_series_every_25m", [])
            if isinstance(row.get("station_m"), (int, float))
            and isinstance(row.get("width_m"), (int, float))
            and math.isfinite(float(row["station_m"]))
            and math.isfinite(float(row["width_m"]))
        ),
        key=lambda pair: pair[0],
    )
    if len(samples) < 2:
        if float(strip_row.get("width_min_m") or 0.0) >= threshold_m and isinstance(strip_row.get("length_m"), (int, float)):
            return [(0.0, float(strip_row["length_m"]))]
        return []
    intervals: list[tuple[float, float]] = []
    for (left_station, left_width), (right_station, right_width) in zip(samples, samples[1:]):
        if left_width >= threshold_m and right_width >= threshold_m:
            intervals.append((left_station, right_station))
        elif left_width >= threshold_m > right_width:
            crossing = left_station + (threshold_m - left_width) * (right_station - left_station) / (right_width - left_width)
            intervals.append((left_station, crossing))
        elif left_width < threshold_m <= right_width:
            crossing = left_station + (threshold_m - left_width) * (right_station - left_station) / (right_width - left_width)
            intervals.append((crossing, right_station))
    return _merge_intervals(intervals)


def _position_text(strip_id: str | None, segment_m: Any) -> str:
    if not strip_id:
        return "位置未指定"
    if not isinstance(segment_m, list) or len(segment_m) != 2:
        return f"{strip_id}｜位置未指定"
    try:
        start, end = (float(value) for value in segment_m)
    except (TypeError, ValueError):
        return "位置未指定"
    return f"{strip_id}｜s={start:g}–{end:g} m"


def _normalise_typologies(row: dict[str, Any], fallback: list[str] | None = None) -> list[str]:
    direct = row.get("typologies")
    # Commander 2026-10-10: typologies may be Chinese labels (axial r4b); map them via aliases.
    labels = direct if isinstance(direct, list) else row.get("building_types_zh", row.get("building_types", []))
    if not isinstance(labels, list):
        labels = [labels] if labels else []
    mapped: list[str] = []
    for value in labels:
        text = str(value).casefold()
        if str(value) in TYPOLOGY_COLORS:
            if str(value) not in mapped:
                mapped.append(str(value))
            continue
        for alias, kind in ZH_TYPOLOGY_ALIASES.items():
            if alias.casefold() in text and kind not in mapped:
                mapped.append(kind)
    return mapped or list(fallback or [])


def _brief_segment_rows(brief: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for parent in brief.get("strips", []):
        strip_id = str(parent.get("strip_id", ""))
        children = parent.get("segments")
        if isinstance(children, list) and children:
            for index, child in enumerate(children):
                if not isinstance(child, dict):
                    continue
                # Commander 2026-10-10: children may describe types only in typology_mix_zh
                # and floors in floors_range (r5 briefs); read those before inheriting the parent.
                child_view = dict(child)
                if "typologies" not in child_view and "building_types_zh" not in child_view and child_view.get("typology_mix_zh"):
                    child_view["building_types_zh"] = [str(child_view["typology_mix_zh"])]
                child_floors = child.get("floors", child.get("floors_range", parent.get("floors")))
                result.append({
                    **parent,
                    **child,
                    "floors": child_floors,
                    "strip_id": str(child.get("strip_id", strip_id)),
                    "segment_m": child.get("segment_m", parent.get("segment_m")),
                    "typologies": _normalise_typologies(child_view, _normalise_typologies(parent)),
                    "reason_zh": child.get("reason_zh", parent.get("reason_zh", "")),
                    "_segment_index": index,
                    "_is_child": True,
                })
        else:
            result.append({
                **parent,
                "strip_id": strip_id,
                "typologies": _normalise_typologies(parent),
                "_segment_index": 0,
            })
    return result


def _missing_anchor_items(brief: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for strip in brief.get("strips", []):
        segments = strip.get("segments", [])
        if isinstance(segments, list):
            for segment in segments:
                if isinstance(segment, dict) and not isinstance(segment.get("segment_m"), list):
                    strip_id = segment.get("strip_id", strip.get("strip_id", ""))
                    missing.append(f"帶段落「{strip_id}」")
    for park in brief.get("open_spaces", []):
        if not park.get("strip_id") or not isinstance(park.get("segment_m"), list):
            missing.append(f"開放空間「{park.get('name_zh', '未命名')}」")
    height = brief.get("height_strategy", {})
    for landmark in height.get("landmarks", []):
        if not landmark.get("strip_id") or landmark.get("station_m") is None:
            missing.append(f"地標「{landmark.get('location_zh', '未命名')}」")
    for low in height.get("low_zones", []):
        if not low.get("strip_id") or not isinstance(low.get("segment_m"), list):
            missing.append(f"低層區「{low.get('location_zh', '未命名')}」")
    return missing


def _paper_bounds(site: Any) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = site.bounds
    pad = max(maxx - minx, maxy - miny) * 0.08
    return minx - pad, maxx + pad, miny - pad, maxy + pad


def _render_axis_station(axis: LineString, station_m: float, station_length_m: float) -> Point:
    return axis.interpolate(min(axis.length, max(0.0, station_m / station_length_m * axis.length)))


def _draw_site_panel(
    ax: Any,
    facts: dict[str, Any],
    geo: dict[str, Any],
    brief: dict[str, Any],
    font_prop: Any,
    bounds: tuple[float, float, float, float],
    *,
    include_legend: bool = True,
    annotation_scale: float = 1.0,
) -> list[Any]:
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D

    site = geo["site"]
    ax.set_facecolor("#f6f4ef")
    _plot_geometry(ax, site, facecolor="#f1eee5", edgecolor="#23313d", linewidth=1.2, zorder=2)
    _plot_geometry(ax, geo["buildable"], facecolor="#f7f0d8", edgecolor="#dfd4b0", linewidth=0.35, alpha=0.4, zorder=2.1)
    for _zone_id, zone in geo["zones"]:
        _plot_geometry(ax, zone, facecolor="none", edgecolor="#96918a", linewidth=0.4, alpha=0.75, zorder=2.2, linestyle="dashed")
    _plot_geometry(ax, geo["waterfront_band"], facecolor="#c5e5e8", edgecolor="#80bcc7", linewidth=0.35, alpha=0.7, zorder=2.3)
    _plot_geometry(ax, geo["water"], facecolor="#74b6d1", edgecolor="#428ca8", linewidth=0.55, alpha=0.9, zorder=2.5)
    for _building_id, geometry in geo["retained_buildings"]:
        _plot_geometry(ax, geometry, facecolor="#655b59", edgecolor="#3e3735", linewidth=0.45, alpha=0.9, zorder=3)
    for _road_id, geometry in geo["retained_roads"]:
        _plot_geometry(ax, geometry, edgecolor="#474b4f", linewidth=1.1, alpha=0.85, zorder=3.1)

    for strip_id, geometry in geo["strips"].items():
        _plot_geometry(ax, geometry, facecolor="#e7dfd0", edgecolor="#a99a80", linewidth=0.45, alpha=0.74, zorder=4)
    slice_cache: dict[tuple[str, float, float], Any] = {}

    def slice_for(strip_id: str, segment_m: Any) -> Any:
        if strip_id not in geo["strips"]:
            return GeometryCollection()
        if not isinstance(segment_m, list) or len(segment_m) != 2:
            return geo["strips"][strip_id]
        try:
            start, end = (float(value) for value in segment_m)
        except (TypeError, ValueError):
            return GeometryCollection()
        key = (strip_id, start, end)
        if key not in slice_cache:
            axis = _axis_line(geo["axes"].get(strip_id))
            station_length = _station_length(facts, strip_id, axis)
            slice_cache[key] = (
                _slice_strip_geometry(axis, geo["strips"][strip_id], start, end, station_length, 10.0)
                if axis is not None and station_length is not None else GeometryCollection()
            )
        return slice_cache[key]

    segment_rows = _brief_segment_rows(brief)
    displayed_types: set[str] = set()
    for segment in segment_rows:
        strip_id = str(segment.get("strip_id", ""))
        if segment.get("_is_child") and not isinstance(segment.get("segment_m"), list):
            continue
        geometry = slice_for(strip_id, segment.get("segment_m"))
        typologies = [kind for kind in segment.get("typologies", []) if kind in TYPOLOGY_COLORS]
        if geometry.is_empty or not typologies:
            continue
        displayed_types.update(typologies)
        main_type = typologies[0]
        hatch = "///" if len(typologies) > 1 else None
        _plot_geometry(
            ax, geometry, facecolor=TYPOLOGY_COLORS[main_type], edgecolor="#655b45",
            linewidth=0.42, alpha=0.77, zorder=4.2, hatch=hatch,
        )
        center = geometry.representative_point()
        label_parts = [TYPOLOGY_LABELS_ZH[main_type]]
        floors = segment.get("floors")
        if floors is not None:
            if isinstance(floors, list) and len(floors) == 2:
                label_parts.append(f"{floors[0]}–{floors[1]} 層")
            else:
                label_parts.append(f"{floors} 層")
        ax.annotate(
            "｜".join(label_parts), (center.x, center.y), fontsize=5.4 * annotation_scale,
            color="#262421", ha="center", va="center",
            bbox={"boxstyle": "round,pad=0.16", "fc": "#fffdf7", "ec": "none", "alpha": 0.84},
            zorder=8,
        )

    for park in brief.get("open_spaces", []):
        strip_id = str(park.get("strip_id", ""))
        segment_m = park.get("segment_m")
        if not strip_id or not isinstance(segment_m, list):
            continue
        geometry = slice_for(strip_id, segment_m)
        if geometry.is_empty:
            continue
        _plot_geometry(ax, geometry, facecolor="#65ad78", edgecolor="#236b3a", linewidth=0.75, alpha=0.56, zorder=6.3)
        center = geometry.representative_point()
        target = park.get("area_m2_target")
        target_label = f"目標 {float(target):,.0f} m²" if isinstance(target, (int, float)) else "目標面積未提供"
        ax.annotate(
            f"{park.get('name_zh', '開放空間')}｜{target_label}", (center.x, center.y),
            fontsize=5.6 * annotation_scale, color="#164b2a", ha="center", va="center",
            bbox={"boxstyle": "round,pad=0.18", "fc": "#f6fff5", "ec": "#4f9561", "alpha": 0.9},
            zorder=9,
        )

    for low in brief.get("height_strategy", {}).get("low_zones", []):
        strip_id = str(low.get("strip_id", ""))
        segment_m = low.get("segment_m")
        if not strip_id or not isinstance(segment_m, list):
            continue
        geometry = slice_for(strip_id, segment_m)
        if geometry.is_empty:
            continue
        _plot_geometry(ax, geometry, facecolor="#eff7e9", edgecolor="#3d7650", linewidth=0.65, alpha=0.38, zorder=6.6, hatch="///")
        center = geometry.representative_point()
        floors = low.get("floors")
        floor_label = f"{floors[0]}–{floors[1]} 層" if isinstance(floors, list) and len(floors) == 2 else f"{floors} 層"
        ax.annotate(
            f"低層 {floor_label}", (center.x, center.y), fontsize=5.6 * annotation_scale,
            color="#315d43", ha="center", va="center",
            bbox={"boxstyle": "round,pad=0.16", "fc": "#f3fff5", "ec": "#65a87b", "alpha": 0.88}, zorder=10,
        )

    for strip_id, axis_geometry in geo["axes"].items():
        axis = _axis_line(axis_geometry)
        if axis is None:
            continue
        bold = any(str(row.get("strip_id")) == strip_id for row in brief.get("development_streets", []))
        _plot_geometry(ax, axis, edgecolor="#a64836" if bold else "#9a7742", linewidth=2.5 if bold else 0.7, alpha=0.94, zorder=7)

    for road_class in ("pedestrian", "bicycle"):
        color = "#a43055" if road_class == "pedestrian" else "#7c4a8e"
        for raw in geo["external_high_roads"].get(road_class, []):
            _plot_geometry(ax, shape(raw), edgecolor=color, linewidth=1.4, alpha=0.84, zorder=7.2)
    entry_offsets = [(4, 4), (4, -9), (-24, 5), (-24, -9), (6, 12), (-25, 12), (5, -17), (-25, -17)]
    for entrance_index, entrance in enumerate(geo["entrances"]):
        x, y = entrance["coordinates"]
        ax.scatter([x], [y], marker="o", s=22, c="#df5a36", edgecolors="white", linewidths=0.5, zorder=8)
        ax.annotate(str(entrance["id"]), (x, y), xytext=entry_offsets[entrance_index % len(entry_offsets)],
                    textcoords="offset points", fontsize=5.8 * annotation_scale, color="#812d1e", zorder=9)

    _plot_geometry(ax, geo["dakpark"], facecolor="#71ae80", edgecolor="#2b7946", linewidth=0.9, alpha=0.84, zorder=6)
    park_point = geo["dakpark"].representative_point()
    ax.annotate("Dakpark\n高差 10 m*", (park_point.x, park_point.y), fontsize=7.0 * annotation_scale,
                ha="center", va="center", color="#154d2b",
                bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "#71ae80", "alpha": 0.9}, zorder=9.5)

    for landmark in brief.get("height_strategy", {}).get("landmarks", []):
        strip_id = str(landmark.get("strip_id", ""))
        station = landmark.get("station_m")
        axis = _axis_line(geo["axes"].get(strip_id))
        station_length = _station_length(facts, strip_id, axis)
        if axis is None or station_length is None or not isinstance(station, (int, float)):
            continue
        center = _render_axis_station(axis, float(station), station_length)
        ax.scatter([center.x], [center.y], marker="*", s=62, c="#b43b3b", edgecolors="white", linewidths=0.5, zorder=11)
        ax.annotate(
            f"地標 {float(landmark.get('height_m', 0)):.1f} m",
            (center.x, center.y), xytext=(7, 7), textcoords="offset points", fontsize=5.8 * annotation_scale,
            color="#742d2d", bbox={"boxstyle": "round,pad=0.2", "fc": "#fff6ee", "ec": "#c97a57", "alpha": 0.92}, zorder=11,
        )

    minx, maxx, miny, maxy = bounds
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("東距（m；EPSG:28992）", fontproperties=font_prop)
    ax.set_ylabel("北距（m；EPSG:28992）", fontproperties=font_prop)
    strategy = STRATEGY_LABELS_ZH.get(str(brief.get("strategy")), str(brief.get("strategy")))
    ax.set_title(f"S6 設計意圖｜{strategy}策略", fontsize=12 * annotation_scale, fontproperties=font_prop)

    missing = _missing_anchor_items(brief)
    if missing:
        missing_text = "位置未指定：\n" + "\n".join(f"・{item}" for item in missing)
        ax.text(
            0.99, 0.99, missing_text, transform=ax.transAxes, ha="right", va="top",
            fontsize=5.3 * annotation_scale, color="#5b4b38", fontproperties=font_prop,
            bbox={"boxstyle": "round,pad=0.25", "fc": "#fffaf0", "ec": "#c8b99f", "alpha": 0.92},
            zorder=12,
        )
    ax.text(
        0.99, 0.015,
        "段落依基地事實資料站距與帶幾何切片；Dakpark 10 m 高差為作品集假設。",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=5.0 * annotation_scale,
        color="#53504a", fontproperties=font_prop,
    )

    legend_handles = [
        Patch(facecolor="#f7f0d8", edgecolor="#dfd4b0", label="J16b 可建造地"),
        Patch(facecolor="#e7dfd0", edgecolor="#a99a80", label="未指定段"),
        Patch(facecolor="#74b6d1", edgecolor="#428ca8", label="BGT 水域"),
        Patch(facecolor="#c5e5e8", edgecolor="#80bcc7", label="水岸帶 15 m"),
        Patch(facecolor="#71ae80", edgecolor="#2b7946", label="Dakpark（依基地事實資料）"),
        Line2D([0], [0], color="#474b4f", lw=1.4, label="保留城市道路"),
        Line2D([0], [0], color="#a43055", lw=1.4, label="步行高整合外部道路"),
        Line2D([0], [0], color="#7c4a8e", lw=1.4, label="自行車高整合外部道路"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#df5a36", label="入口", markersize=5),
        Line2D([0], [0], color="#a64836", lw=2.5, label="發展街（加粗）"),
        Patch(facecolor="#65ad78", edgecolor="#236b3a", alpha=0.56, label="錨定開放空間切片"),
        Patch(facecolor="#eff7e9", edgecolor="#3d7650", hatch="///", label="錨定低層區"),
        Patch(facecolor="white", edgecolor="#655b45", hatch="///", label="斜線＝同段另有類型（詳中文意圖書）"),
    ]
    for kind in sorted(displayed_types):
        legend_handles.append(Patch(facecolor=TYPOLOGY_COLORS[kind], edgecolor="#655b45", alpha=0.77, label=f"主類型：{TYPOLOGY_LABELS_ZH[kind]}"))
    if include_legend:
        ax.legend(handles=legend_handles, loc="lower left", fontsize=6.2 * annotation_scale, framealpha=0.94, prop=font_prop)
    return legend_handles


def _draw_site_figure(facts: dict[str, Any], destination: Path, brief: dict[str, Any] | None = None) -> None:
    cache_root = Path(os.environ.get("TMPDIR", "/private/tmp")) / "s6-brief-matplotlib"
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_root))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    geo = _load_render_geometries(facts)
    font_path = _figure_font()
    font_prop = font_manager.FontProperties(fname=font_path) if font_path else None
    if font_prop:
        plt.rcParams["font.family"] = font_prop.get_name()
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(11, 10.5))
    view = brief or {"strategy": "site_facts", "strips": [], "open_spaces": [], "height_strategy": {}, "development_streets": []}
    legend_handles = _draw_site_panel(
        ax, facts, geo, view, font_prop, _paper_bounds(geo["site"]), include_legend=False
    )
    if brief is None:
        ax.set_title("S6 基地事實示意圖", fontsize=13, fontproperties=font_prop)
    fig.legend(handles=legend_handles, loc="lower center", ncol=4, fontsize=7, framealpha=0.95, prop=font_prop)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.94, bottom=0.2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def _draw_comparison_figure(facts: dict[str, Any], briefs: list[dict[str, Any]], destination: Path) -> None:
    cache_root = Path(os.environ.get("TMPDIR", "/private/tmp")) / "s6-brief-matplotlib"
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_root))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D

    geo = _load_render_geometries(facts)
    font_path = _figure_font()
    font_prop = font_manager.FontProperties(fname=font_path) if font_path else None
    if font_prop:
        plt.rcParams["font.family"] = font_prop.get_name()
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 2, figsize=(19, 14))
    bounds = _paper_bounds(geo["site"])
    for ax, brief in zip(axes.flat, briefs):
        _draw_site_panel(ax, facts, geo, brief, font_prop, bounds, include_legend=False, annotation_scale=0.78)
    legend_handles = [
        Patch(facecolor="#f7f0d8", edgecolor="#dfd4b0", label="J16b 可建造地"),
        Patch(facecolor="#e7dfd0", edgecolor="#a99a80", label="未指定段"),
        Patch(facecolor="#74b6d1", edgecolor="#428ca8", label="BGT 水域"),
        Patch(facecolor="#c5e5e8", edgecolor="#80bcc7", label="水岸帶 15 m"),
        Patch(facecolor="#71ae80", edgecolor="#2b7946", label="Dakpark（依基地事實資料）"),
        Line2D([0], [0], color="#474b4f", lw=1.4, label="保留城市道路"),
        Line2D([0], [0], color="#a43055", lw=1.4, label="步行高整合外部道路"),
        Line2D([0], [0], color="#7c4a8e", lw=1.4, label="自行車高整合外部道路"),
        Line2D([0], [0], color="#a64836", lw=2.5, label="發展街（加粗）"),
        Patch(facecolor="#65ad78", edgecolor="#236b3a", alpha=0.56, label="錨定開放空間切片"),
        Patch(facecolor="#eff7e9", edgecolor="#3d7650", hatch="///", label="錨定低層區"),
        Patch(facecolor="white", edgecolor="#655b45", hatch="///", label="斜線＝同段另有類型（詳中文意圖書）"),
    ]
    for kind in sorted({kind for brief in briefs for row in _brief_segment_rows(brief) for kind in row.get("typologies", []) if kind in TYPOLOGY_COLORS}):
        legend_handles.append(Patch(facecolor=TYPOLOGY_COLORS[kind], edgecolor="#655b45", label=f"主類型：{TYPOLOGY_LABELS_ZH[kind]}"))
    fig.suptitle("S6 四策略設計意圖並列｜四圖同一比例尺", fontsize=16, fontproperties=font_prop)
    fig.legend(handles=legend_handles, loc="lower center", ncol=5, fontsize=8, framealpha=0.95, prop=font_prop)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.94, bottom=0.1, hspace=0.28, wspace=0.12)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def command_facts(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    facts, _objects = _load_facts(Path(args.database), Path(args.network_root))
    output = Path(args.out)
    _json_write(output / "site-facts.json", facts)
    _draw_site_figure(facts, output / "site-facts-zh.png")
    print(f"已輸出基地事實：{output / 'site-facts.json'}")
    print(f"已輸出繁體中文示意圖：{output / 'site-facts-zh.png'}")
    print(f"土地面積 {facts['site']['land_area_m2']:.1f} m²；可建造地 {facts['buildable']['area_m2']:.1f} m²；帶數 {len(facts['buildable']['strips'])}。")
    print(f"保留建築 GFA upper={facts['gfa']['retained_upper_m2']} m²；新建 GFA budget={facts['gfa']['new_gfa_budget_m2']} m²。")
    return 0


def _format_m(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return "未知"
    return f"{float(value):.1f}"


def _prompt_station_rows(strip_row: dict[str, Any]) -> list[dict[str, Any]]:
    length_m = float(strip_row.get("length_m", 0.0))
    return [
        row for row in strip_row.get("stations", [])
        if isinstance(row.get("station_m"), (int, float))
        and (
            abs(float(row["station_m"]) / PROMPT_STATION_STEP_M - round(float(row["station_m"]) / PROMPT_STATION_STEP_M)) < 1e-6
            or abs(float(row["station_m"]) - length_m) < 1e-6
        )
    ]


def _spatial_locator_summary(facts: dict[str, Any]) -> str:
    strips = facts.get("buildable", {}).get("strips", [])
    station_records = [
        (strip, station)
        for strip in strips
        for station in strip.get("stations", [])
        if isinstance(station, dict)
    ]
    if not station_records:
        return "逐段鄰接站距尚未計算；不可由策略文字推定 Dakpark、入口或最寬帶的位置。"

    lines: list[str] = []
    dakpark_candidates = [
        (float(station["dakpark_distance_m"]), str(strip["id"]), float(station["station_m"]))
        for strip, station in station_records
        if isinstance(station.get("dakpark_distance_m"), (int, float))
    ]
    if dakpark_candidates:
        distance, strip_id, station_m = min(dakpark_candidates)
        lines.append(f"- 最近 Dakpark 的帶段：{strip_id} s={station_m:g}m，橫剖面中點距離 {distance:.1f}m。")
    else:
        lines.append("- 最近 Dakpark 的帶段：距離未能量測。")

    entry1 = next((row for row in facts.get("entrances", []) if str(row.get("id", "")).casefold() == "entry-1"), None)
    if entry1 and isinstance(entry1.get("coordinates"), list) and len(entry1["coordinates"]) >= 2:
        ex, ey = float(entry1["coordinates"][0]), float(entry1["coordinates"][1])
        def distance_to_entry1(pair: tuple[dict[str, Any], dict[str, Any]]) -> tuple[float, str, float]:
            strip, station = pair
            coords = station.get("midpoint_epsg28992", [])
            distance = math.hypot(float(coords[0]) - ex, float(coords[1]) - ey) if len(coords) >= 2 else math.inf
            return distance, str(strip.get("id", "")), float(station.get("station_m", 0.0))

        station_nearest = min(station_records, key=distance_to_entry1)
        station_distance, station_strip_id, station_m = distance_to_entry1(station_nearest)
        endpoints = [
            pair for pair in station_records
            if abs(float(pair[1].get("station_m", -1.0))) < 1e-6
            or abs(float(pair[1].get("station_m", -1.0)) - float(pair[0].get("length_m", 0.0))) < 1e-6
        ]
        if endpoints:
            end_nearest = min(endpoints, key=distance_to_entry1)
            end_distance, end_strip_id, end_station = distance_to_entry1(end_nearest)
            end_label = "s=0端" if abs(end_station) < 1e-6 else "s=L端"
            lines.append(f"- 最靠近 entry-1 的帶端：{end_strip_id} {end_label}，{end_distance:.1f}m；全站最近位置為 {station_strip_id} s={station_m:g}m（{station_distance:.1f}m）。")
        else:
            lines.append(f"- entry-1 最近站點：{station_strip_id} s={station_m:g}m（{station_distance:.1f}m）；帶端資料未知。")
    else:
        lines.append("- entry-1 帶端位置：入口未列於 facts，無法定位。")

    widest = []
    for strip in strips:
        samples = strip.get("width_series_every_25m", [])
        for start, end in _width_intervals_at_least(strip, WIDE_LAND_MIN_WIDTH_M):
            widths = [
                float(row["width_m"]) for row in samples
                if start - 1e-6 <= float(row.get("station_m", -math.inf)) <= end + 1e-6
                and isinstance(row.get("width_m"), (int, float))
            ]
            widest.append((max(widths, default=WIDE_LAND_MIN_WIDTH_M), str(strip["id"]), start, end))
    if widest:
        widest.sort(key=lambda item: (-item[0], item[1], item[2]))
        descriptions = [f"{strip_id} s={start:g}–{end:g}m（峰值約{peak:.1f}m）" for peak, strip_id, start, end in widest]
        lines.append("- 最寬可建段（寬度≥105m；請保留周邊式街廓可建空間）：" + "；".join(descriptions) + "。")
    else:
        lines.append("- 最寬可建段：未量得寬度≥105m的帶段。")
    return "\n".join(lines)


def _facts_summary(facts: dict[str, Any]) -> str:
    site = facts.get("site", {})
    gfa = facts.get("gfa", {})
    height = facts.get("height", {})
    zones = facts.get("zones", {})
    lines = [
        f"- StudyArea：{site.get('study_area_id')}／{site.get('study_area_version')}，狀態 {site.get('status')}，CRS {site.get('horizontal_crs')}。",
        f"- 陸地面積 {site.get('land_area_m2')} m²；水域 {site.get('water_area_intersection_m2')} m²；J16b 可建造地 {facts.get('buildable', {}).get('area_m2')} m²。",
        f"- D2-A 記錄 FAR {gfa.get('far_max')}、最低核對 FAR {gfa.get('far_min_for_validation')}；保留建物 GFA lower/upper {gfa.get('retained_lower_m2')} / {gfa.get('retained_upper_m2')} m²；新建預算 {gfa.get('new_gfa_budget_m2')} m²。",
        f"- 高度 {height.get('cap_m')} m；首層 {height.get('first_floor_height_m')} m；標準層 {height.get('standard_floor_height_m')} m；設定狀態 {height.get('setting_status')}；備註與核准狀態衝突={height.get('notes_conflict_with_approval')}。",
        f"- J9b 大眾運輸最近側：{facts.get('transit', {}).get('closest_side')}（{facts.get('transit', {}).get('status')}）。",
        f"- Dakpark 高差 {facts.get('dakpark', {}).get('elevation_difference_m')} m（{facts.get('dakpark', {}).get('elevation_status')}）。",
        f"- 既有 zones 工作區 rev {zones.get('workspace_revision')}／{zones.get('workspace_status')}；空間簡報 {zones.get('spatial_brief_status')}；各區用途比例存在={zones.get('per_zone_use_ratios_exist')}。",
        f"- 作品集用途比例範圍（百分比，不是各 zone 配額）：{json.dumps(zones.get('portfolio_use_ratio_guidance_percent', {}), ensure_ascii=False)}。",
        "- 可建造帶（面積為 10m 橫剖面積分估算；逐段入口／水域／Dakpark／保留建物距離以 EPSG:28992 幾何量測）：",
    ]
    for row in facts.get("buildable", {}).get("strips", []):
        lines.append(
            f"  - {row['id']}：長 {row['length_m']:.1f}m，方位 {row['orientation_deg_from_east_ccw']:.1f}°，"
            f"寬 {row.get('width_min_m')}–{row.get('width_max_m')}m，面積估算 {row.get('area_m2')}m²。"
        )
        if row.get("summary_zh"):
            lines.append(f"    - {row['summary_zh']}")
        for end in row.get("ends", {}).get("ends", []):
            connected = ", ".join(f"{x['kind']} {x['id']}" for x in end.get("exact_connections_within_0_01m", [])) or "無 0.01m 內精確連接"
            near = end.get("nearest_entrance")
            if near:
                connected += f"；最近入口 {near['id']} {near['distance_m']:.1f}m"
            lines.append(f"    - 端點 {end['end']}：{connected}。")
    lines.extend([
        "",
        "| 帶 | s (m) | 寬 (m) | 橫剖面中點 (E, N; EPSG:28992) | 最近入口前二 (m) | Dakpark (m) | 水域距離／側別 (m) | 最近保留建物 (m) | 外部高整合道路 ≤30m |",
        "| --- | ---: | ---: | --- | --- | ---: | --- | ---: | --- |",
    ])
    table_rows = 0
    for strip in facts.get("buildable", {}).get("strips", []):
        for station in _prompt_station_rows(strip):
            coords = station.get("midpoint_epsg28992", [])
            coordinate_text = f"{float(coords[0]):.1f}, {float(coords[1]):.1f}" if len(coords) >= 2 else "未知"
            entries_text = "、".join(
                f"{row['id']} {_format_m(row.get('distance_m'))}"
                for row in station.get("nearest_entrances", [])
            ) or "未知"
            water_text = f"{_format_m(station.get('water_distance_m'))}／{station.get('water_side_zh', '未知')}"
            road = station.get("nearest_external_high_integration_road") or {}
            adjacent = station.get("adjacent_external_high_integration_road")
            road_text = "未知" if adjacent is None else ("是" if adjacent else "否")
            if road.get("distance_m") is not None:
                road_text += f"（{_format_m(road['distance_m'])}m"
                if road.get("id"):
                    road_text += f"；{road['id']}"
                road_text += "）"
            lines.append(
                f"| {strip['id']} | {float(station['station_m']):g} | {_format_m(station.get('width_m'))} | {coordinate_text} | {entries_text} | "
                f"{_format_m(station.get('dakpark_distance_m'))} | {water_text} | {_format_m(station.get('nearest_retained_building_distance_m'))} | {road_text} |"
            )
            table_rows += 1
    if not table_rows:
        lines.append("| — | — | — | 逐段量測資料未知 | — | — | — | — | — |")
    for mode_key, label in (("pedestrian_800m", "步行800m"), ("bicycle_2km", "自行車2km")):
        syntax = facts.get("external_space_syntax", {}).get(mode_key, {})
        percentile = syntax.get("baseline_nain_percentiles", {}).get("p60")
        lines.append(f"- {label} NAIN：{syntax.get('status')}，run-13 高整合門檻 {syntax.get('high_threshold_nain')}（{syntax.get('high_threshold_definition')}），基準 P60 {percentile}；基地接點道路 {len(syntax.get('external_high_integration_connections', []))} 條。")
        for road in syntax.get("external_high_integration_connections", [])[:12]:
            entry_points = ", ".join(f"{e['id']} {e['coordinates_epsg28992']}" for e in road.get("entrance_matches", []))
            location = f"source way 配對入口 {entry_points}" if entry_points else f"基地邊界交點 {road.get('boundary_points_epsg28992')}"
            lines.append(f"  - {road.get('source_line_id')} {road.get('road_name') or ''} NAIN {road.get('nain_min'):.3f}–{road.get('nain_max'):.3f}；{location}。")
    lines.append("- 保留建築：")
    for row in facts.get("retained_buildings", []):
        lines.append(f"  - {row['id']}：BAG {row.get('bag_status')}，用途 {row.get('bag_use')}，footprint {row.get('footprint_area_m2')}m²，樓層 {row.get('floor_count_lower')}–{row.get('floor_count_upper')}，GFA upper {row.get('gfa_upper_m2')}m²（{row.get('status')}）。")
    lines.append("- 來源限制：" + "；".join(facts.get("limitations", [])))
    return "\n".join(lines)


def _context_pack(kb_root: Path, question: str, max_chars: int) -> str:
    script = kb_root / "scripts/kb_context_pack.py"
    if not script.is_file():
        raise S6BriefError(f"唯讀知識檢索工具不存在：{script}")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(kb_root / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    result = subprocess.run(
        [sys.executable, str(script), question, "--max-chars", str(max_chars)],
        cwd=kb_root, env=env, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise S6BriefError(f"本機 KB 檢索失敗（{question}）：{result.stderr.strip()}")
    return result.stdout.strip()


def _dedupe_paragraphs(packs: Iterable[str]) -> str:
    seen: set[str] = set()
    output = []
    for pack in packs:
        for paragraph in re.split(r"\n\s*\n", pack):
            normalized = "\n".join(line.rstrip() for line in paragraph.strip().splitlines()).strip()
            if not normalized:
                continue
            key = re.sub(r"\s+", " ", normalized).casefold()
            if key in seen:
                continue
            seen.add(key)
            output.append(normalized)
    return "\n\n".join(output)


STRATEGY_NOTES = {
    "radial": "向心策略：以已量測入口、中心節點與高整合道路安排主要發展街；逐帶說明向中心的連接、端點和保留條件。不要把中心或中心位置當成未驗證基地事實。",
    "axial": "軸線策略：選一條可辨識、連續的主軸串接入口、轉乘側和水岸；以次軸完成橫向連結，說明街道界面和中斷處。",
    "grid": "網格策略：以均衡的縱橫步行自行車網連接各帶；保持街廓可穿透，說明既有城市道路和保留建築如何限制網格。",
    "green_service": "綠廊服務策略：將連續開放空間與水岸連接成具名公共骨架，服務街貼近街區而不切碎公園；逐帶說明服務、低層和住宅過渡。",
}


def command_prompt(args: argparse.Namespace) -> int:
    if args.strategy not in STRATEGIES:
        raise S6BriefError(f"未知策略：{args.strategy}")
    kb_root = Path(args.kb).expanduser().resolve()
    skill_path = kb_root / SKILL_RELATIVE
    facts_path = Path(args.facts)
    facts = _json_read(facts_path)
    if not skill_path.is_file():
        raise S6BriefError(f"技能說明不存在：{skill_path}")
    skill_text = skill_path.read_text(encoding="utf-8").strip()
    facts_text = _facts_summary(facts)
    spatial_locator_text = _spatial_locator_summary(facts)
    packs = [_context_pack(kb_root, question, 5000) for question in KB_QUERIES]
    context_text = _dedupe_paragraphs(packs)
    strategy_text = STRATEGY_NOTES[args.strategy]
    header = "# S6 設計意圖書任務\n\n"
    sections = [
        ("空間定位要點", spatial_locator_text),
        ("技能說明全文", skill_text),
        ("基地事實（含每 50m 逐帶鄰接表）", facts_text),
        ("本機形態知識情境包（去重）", context_text),
        ("本次策略", f"策略代碼：{args.strategy}\n{strategy_text}"),
        ("輸出格式", "只輸出一個 JSON 物件，不要 Markdown code fence、前言或結語。JSON 必須符合 massing-design-brief.schema.json。每一個決策的 reason_zh 都要引用基地事實或 KU／先例證據；未知資料要標為未知，禁止補造。名稱含 Dakpark 的公園／綠廊須錨在距 Dakpark 150m 內；名稱含水岸／港岸的空間須臨水40m內；地標若寫入口 id，station_m 到該入口須在80m內。寬度≥105m的帶段屬最適合周邊式街廓的可建地，不得未說明就大面積改成公園。"),
    ]
    prompt = header + "\n\n".join(f"## {title}\n\n{text}" for title, text in sections)
    if len(prompt) > 45_000:
        # Preserve every required section and query; trim retrieved context only
        # at paragraph boundaries, then fail if the required core still exceeds.
        overflow = len(prompt) - 45_000
        if context_text:
            context_text = context_text[:max(0, len(context_text) - overflow - 100)]
            context_text = context_text.rsplit("\n\n", 1)[0] if "\n\n" in context_text else context_text
            sections[2] = (sections[2][0], context_text)
            prompt = header + "\n\n".join(f"## {title}\n\n{text}" for title, text in sections)
    if len(prompt) > 45_000:
        raise S6BriefError(f"提示核心超過 45,000 字元：{len(prompt)}")
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(prompt + "\n", encoding="utf-8")
    print(f"已輸出 {args.strategy} 提示：{output}（{len(prompt)} 字元；上限 45,000）")
    print(f"本機 KB 查詢數：{len(KB_QUERIES)}；四策略指令不呼叫 AI 模型。")
    return 0


def _schema_path() -> Path:
    candidates = [KB_ROOT_DEFAULT / SCHEMA_RELATIVE]
    return next((path for path in candidates if path.is_file()), candidates[0])


def _at_path(data: Any, path: Iterable[Any]) -> Any:
    current = data
    for part in path:
        current = current[part]
    return current


def _schema_with_legacy_anchor_fallback(schema: dict[str, Any]) -> dict[str, Any]:
    """Permit pre-anchor briefs only for anchor presence; validate all supplied anchors below."""
    compatible = copy.deepcopy(schema)
    optional_fields = {
        ("properties", "open_spaces", "items"): {"strip_id", "segment_m"},
        ("properties", "height_strategy", "properties", "landmarks", "items"): {"strip_id", "station_m"},
        ("properties", "height_strategy", "properties", "low_zones", "items"): {"strip_id", "segment_m"},
    }
    for path, optional in optional_fields.items():
        try:
            node = _at_path(compatible, path)
        except (KeyError, TypeError):
            continue
        if isinstance(node.get("required"), list):
            node["required"] = [field for field in node["required"] if field not in optional]
    return compatible


def _fact_strip_length(strip_id: str, strip_by_id: dict[str, dict[str, Any]], facts: dict[str, Any]) -> float | None:
    row = strip_by_id.get(strip_id, {})
    value = row.get("length_m")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0:
        return float(value)
    for geometry_row in facts.get("geometry", {}).get("strips", []):
        if str(geometry_row.get("id")) == strip_id and geometry_row.get("axis"):
            axis = _axis_line(shape(geometry_row["axis"]))
            return float(axis.length) if axis is not None else None
    return None


def _brief_segment_geometry(strip_id: Any, interval: Any, facts: dict[str, Any]) -> Any | None:
    if not isinstance(strip_id, str) or not strip_id or not isinstance(interval, list) or len(interval) != 2:
        return None
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) for value in interval):
        return None
    start_m, end_m = (float(value) for value in interval)
    if start_m < 0 or end_m <= start_m:
        return None
    try:
        geometry_row = next(
            (row for row in facts.get("geometry", {}).get("strips", []) if str(row.get("id")) == strip_id),
            None,
        )
        if not geometry_row or not geometry_row.get("geometry") or not geometry_row.get("axis"):
            return None
        band = shape(geometry_row["geometry"])
        axis = _axis_line(shape(geometry_row["axis"]))
        strip_rows = facts.get("buildable", {}).get("strips", facts.get("strips", []))
        strip_by_id = {str(row.get("id")): row for row in strip_rows if row.get("id") is not None}
        length_m = _fact_strip_length(strip_id, strip_by_id, facts)
        if axis is None or length_m is None or end_m > length_m + 1e-6:
            return None
        result = _slice_strip_geometry(axis, band, start_m, end_m, length_m, step_m=10.0)
        return None if result.is_empty else result
    except (KeyError, TypeError, ValueError, S6BriefError):
        return None


def _park_named_space(row: dict[str, Any]) -> bool:
    text = f"{row.get('name_zh', '')} {row.get('name', '')} {row.get('use_zh', '')}".casefold()
    return any(term in text for term in ("park", "公園", "公园", "綠廊", "绿廊", "綠地", "绿地"))


def _semantic_location_issues(
    brief: dict[str, Any], facts: dict[str, Any], strip_by_id: dict[str, dict[str, Any]]
) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    geometry = facts.get("geometry", {})
    dakpark_data = geometry.get("dakpark")
    water_data = geometry.get("water")
    dakpark = shape(dakpark_data) if dakpark_data else GeometryCollection()
    water = shape(water_data) if water_data else GeometryCollection()
    if not dakpark.is_valid:
        dakpark = dakpark.buffer(0)
    if not water.is_valid:
        water = water.buffer(0)

    for index, row in enumerate(brief.get("open_spaces", [])):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name_zh", row.get("name", "未命名")))
        name_folded = name.casefold()
        # Commander 2026-10-10: the target area must physically fit inside its anchored segment.
        target_area = row.get("area_m2_target")
        segment_shape = _brief_segment_geometry(row.get("strip_id"), row.get("segment_m"), facts)
        if isinstance(target_area, (int, float)) and segment_shape is not None and not segment_shape.is_empty:
            if float(target_area) > float(segment_shape.area) * 1.05:
                issues.append((
                    "OPEN_SPACE_EXCEEDS_SEGMENT",
                    f"open_spaces[{index}]「{name}」目標 {float(target_area):.0f}m² 大於其帶段面積 {float(segment_shape.area):.0f}m²；請延長 segment_m 或縮小面積。",
                ))
        checks = []
        if "dakpark" in name_folded:
            checks.append(("Dakpark", dakpark, DAKPARK_NAME_DISTANCE_LIMIT_M))
        if "水岸" in name or "港岸" in name:
            checks.append(("水域", water, WATERFRONT_NAME_DISTANCE_LIMIT_M))
        if not checks:
            continue
        segment = _brief_segment_geometry(row.get("strip_id"), row.get("segment_m"), facts)
        for place_name, target, limit_m in checks:
            if segment is None or target.is_empty:
                issues.append((
                    "PARK_NAME_LOCATION_MISMATCH",
                    f"open_spaces[{index}]「{name}」缺少可計算的帶段錨點或{place_name}幾何，無法驗證其名稱位置。",
                ))
                continue
            distance_m = float(segment.distance(target))
            if distance_m > limit_m + 1e-6:
                issues.append((
                    "PARK_NAME_LOCATION_MISMATCH",
                    f"open_spaces[{index}]「{name}」段落距{place_name}最近 {distance_m:.1f}m，超過 {limit_m:.0f}m。",
                ))

    entrance_by_id = {
        str(row.get("id", "")).casefold(): row
        for row in facts.get("entrances", geometry.get("entrances", []))
        if row.get("id") is not None
    }
    geometry_strip_by_id = {
        str(row.get("id")): row
        for row in geometry.get("strips", [])
        if row.get("id") is not None
    }
    for index, landmark in enumerate(brief.get("height_strategy", {}).get("landmarks", [])):
        if not isinstance(landmark, dict):
            continue
        location = str(landmark.get("location_zh", ""))
        mentioned_ids = sorted(set(re.findall(r"entry-\d+", location, flags=re.IGNORECASE)), key=str.casefold)
        if not mentioned_ids:
            continue
        strip_id = landmark.get("strip_id")
        station_m = landmark.get("station_m")
        strip_row = strip_by_id.get(str(strip_id)) if strip_id is not None else None
        geometry_row = geometry_strip_by_id.get(str(strip_id)) if strip_id is not None else None
        axis = _axis_line(shape(geometry_row["axis"])) if geometry_row and geometry_row.get("axis") else None
        length_m = _fact_strip_length(str(strip_id), strip_by_id, facts) if strip_row and axis else None
        landmark_point = None
        if (
            axis is not None and length_m is not None
            and isinstance(station_m, (int, float)) and not isinstance(station_m, bool)
            and math.isfinite(float(station_m)) and 0 <= float(station_m) <= length_m + 1e-6
        ):
            landmark_point = _render_axis_station(axis, float(station_m), length_m)
        for entry_id in mentioned_ids:
            entry = entrance_by_id.get(entry_id.casefold())
            coordinates = entry.get("coordinates", entry.get("coordinates_epsg28992")) if entry else None
            if landmark_point is None or not isinstance(coordinates, list) or len(coordinates) < 2:
                issues.append((
                    "LANDMARK_ENTRY_MISMATCH",
                    f"height_strategy.landmarks[{index}] 的位置提到 {entry_id}，但缺少可核對的帶號、有效 station_m 或入口座標。",
                ))
                continue
            distance_m = float(landmark_point.distance(Point(float(coordinates[0]), float(coordinates[1]))))
            if distance_m > LANDMARK_ENTRY_DISTANCE_LIMIT_M + 1e-6:
                issues.append((
                    "LANDMARK_ENTRY_MISMATCH",
                    f"height_strategy.landmarks[{index}] 的 station_m 距 {entry_id} {distance_m:.1f}m，超過 {LANDMARK_ENTRY_DISTANCE_LIMIT_M:.0f}m。",
                ))
    return issues


def _wide_land_park_coverage_issue(
    brief: dict[str, Any], strip_by_id: dict[str, dict[str, Any]]
) -> tuple[str, str] | None:
    wide_by_strip = {
        strip_id: _width_intervals_at_least(row, WIDE_LAND_MIN_WIDTH_M)
        for strip_id, row in strip_by_id.items()
    }
    total_wide_length = sum(end - start for intervals in wide_by_strip.values() for start, end in intervals)
    if total_wide_length <= 1e-8:
        return None

    park_by_strip: dict[str, list[tuple[float, float]]] = {}
    park_segments = [
        row for row in brief.get("open_spaces", [])
        if isinstance(row, dict) and _park_named_space(row)
    ]
    park_segments.extend(
        row for row in _brief_segment_rows(brief)
        if "park" in row.get("typologies", [])
    )
    for row in park_segments:
        strip_id = row.get("strip_id")
        interval = row.get("segment_m")
        if strip_id not in strip_by_id or not isinstance(interval, list) or len(interval) != 2:
            continue
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) for value in interval):
            continue
        start_m, end_m = (float(value) for value in interval)
        length_value = strip_by_id[str(strip_id)].get("length_m")
        length_m = float(length_value) if isinstance(length_value, (int, float)) and not isinstance(length_value, bool) else None
        if end_m <= start_m or start_m < 0:
            continue
        if length_m is not None and end_m > length_m + 1e-6:
            continue
        park_by_strip.setdefault(str(strip_id), []).append((start_m, end_m))

    covered_intervals: list[tuple[str, float, float]] = []
    for strip_id, wide_intervals in wide_by_strip.items():
        parks = _merge_intervals(park_by_strip.get(strip_id, []))
        for wide_start, wide_end in wide_intervals:
            for park_start, park_end in parks:
                start_m, end_m = max(wide_start, park_start), min(wide_end, park_end)
                if end_m - start_m > 1e-8:
                    covered_intervals.append((strip_id, start_m, end_m))
    by_strip_covered: dict[str, list[tuple[float, float]]] = {}
    for strip_id, start_m, end_m in covered_intervals:
        by_strip_covered.setdefault(strip_id, []).append((start_m, end_m))
    covered_length = sum(
        end - start
        for intervals in by_strip_covered.values()
        for start, end in _merge_intervals(intervals)
    )
    ratio = covered_length / total_wide_length
    if ratio <= WIDE_LAND_PARK_COVERAGE_WARN_RATIO + 1e-9:
        return None
    return (
        "WIDE_LAND_UNDERUSED",
        f"寬度≥{WIDE_LAND_MIN_WIDTH_M:.0f}m的可建帶總長 {total_wide_length:.1f}m 中，公園段覆蓋 {covered_length:.1f}m（{ratio:.1%}），高於60%；可能浪費最適合周邊式街廓的土地。",
    )


def _validate_brief(brief: dict[str, Any], facts: dict[str, Any]) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    schema_path = _schema_path()
    if not schema_path.is_file():
        return [("SCHEMA_UNAVAILABLE", f"找不到質量設計意圖書 schema：{schema_path}")]
    schema = _schema_with_legacy_anchor_fallback(_json_read(schema_path))
    for error in Draft202012Validator(schema).iter_errors(brief):
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        issues.append(("BRIEF_SCHEMA_INVALID", f"{path}: {error.message}"))

    strip_rows = facts.get("buildable", {}).get("strips", facts.get("strips", []))
    strip_by_id = {str(row.get("id")): row for row in strip_rows if row.get("id") is not None}
    strip_refs: list[tuple[str, str]] = []
    for i, row in enumerate(brief.get("strips", [])):
        strip_refs.append((f"strips[{i}].strip_id", str(row.get("strip_id", ""))))
        for j, segment in enumerate(row.get("segments", []) if isinstance(row.get("segments"), list) else []):
            if isinstance(segment, dict) and segment.get("strip_id"):
                strip_refs.append((f"strips[{i}].segments[{j}].strip_id", str(segment["strip_id"])))
    for key in ("development_streets", "open_spaces"):
        for i, row in enumerate(brief.get(key, [])):
            if not isinstance(row, dict):
                issues.append(("BRIEF_ROW_NOT_OBJECT", f"{key}[{i}] 必須是物件，收到 {type(row).__name__}。"))
                continue
            if row.get("strip_id"):
                strip_refs.append((f"{key}[{i}].strip_id", str(row["strip_id"])))
    for key in ("landmarks", "low_zones"):
        for i, row in enumerate(brief.get("height_strategy", {}).get(key, [])):
            if isinstance(row, dict) and row.get("strip_id"):
                strip_refs.append((f"height_strategy.{key}[{i}].strip_id", str(row["strip_id"])))
    for i, row in enumerate(brief.get("gfa_allocation", {}).get("by_strip", [])):
        strip_refs.append((f"gfa_allocation.by_strip[{i}].strip_id", str(row.get("strip_id", ""))))
    for field_name, strip_id in strip_refs:
        if strip_id not in strip_by_id:
            issues.append(("STRIP_ID_UNKNOWN", f"{field_name}={strip_id!r} 不存在於基地事實包。"))

    def validate_interval(field_name: str, strip_id_value: Any, interval: Any, *, nested: bool = False) -> None:
        if not isinstance(interval, list) or len(interval) != 2:
            if nested:
                issues.append(("SEGMENT_RANGE_INVALID", f"{field_name} 必須是兩元素的里程陣列。"))
            return  # The schema reports malformed schema-defined intervals.
        if not isinstance(strip_id_value, str) or not strip_id_value:
            issues.append(("SEGMENT_STRIP_REQUIRED", f"{field_name} 有段落里程，必須同時提供 strip_id。"))
            return
        if strip_id_value not in strip_by_id:
            return
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) for value in interval):
            issues.append(("SEGMENT_RANGE_INVALID", f"{field_name} 必須是兩個有限數值。"))
            return
        start, end = (float(value) for value in interval)
        length = _fact_strip_length(strip_id_value, strip_by_id, facts)
        if start < 0 or end < start:
            issues.append(("SEGMENT_RANGE_INVALID", f"{field_name}={start:g}–{end:g}m 必須滿足 0 ≤ 起點 ≤ 終點。"))
        elif length is not None and end > length + 1e-6:
            issues.append(("SEGMENT_OUT_OF_RANGE", f"{field_name} 終點 {end:.2f}m 超出 {strip_id_value} 帶長 {length:.2f}m。"))

    def validate_anchor_pair(field_name: str, row: dict[str, Any], strip_key: str, measure_key: str) -> None:
        has_strip = bool(row.get(strip_key))
        has_measure = row.get(measure_key) is not None
        if has_measure and not has_strip:
            issues.append(("ANCHOR_STRIP_REQUIRED", f"{field_name}.{measure_key} 有里程值，必須同時提供 {strip_key}。"))

    for i, row in enumerate(brief.get("strips", [])):
        strip_id = row.get("strip_id")
        if row.get("segment_m") is not None:
            validate_interval(f"strips[{i}].segment_m", strip_id, row.get("segment_m"))
        nested_segments = row.get("segments", [])
        if "segments" in row and not isinstance(nested_segments, list):
            issues.append(("SEGMENTS_INVALID", f"strips[{i}].segments 必須是陣列。"))
            continue
        for j, segment in enumerate(nested_segments):
            if not isinstance(segment, dict):
                issues.append(("BRIEF_ROW_NOT_OBJECT", f"strips[{i}].segments[{j}] 必須是物件。"))
                continue
            if segment.get("segment_m") is not None:
                validate_interval(
                    f"strips[{i}].segments[{j}].segment_m",
                    segment.get("strip_id", strip_id),
                    segment.get("segment_m"),
                    nested=True,
                )
    for key in ("development_streets", "open_spaces"):
        for i, row in enumerate(brief.get(key, [])):
            if isinstance(row, dict):
                if key == "open_spaces":
                    validate_anchor_pair(f"{key}[{i}]", row, "strip_id", "segment_m")
                if row.get("segment_m") is not None:
                    validate_interval(f"{key}[{i}].segment_m", row.get("strip_id"), row.get("segment_m"))
    for i, row in enumerate(brief.get("height_strategy", {}).get("landmarks", [])):
        if not isinstance(row, dict):
            continue
        validate_anchor_pair(f"height_strategy.landmarks[{i}]", row, "strip_id", "station_m")
        station = row.get("station_m")
        if station is None:
            continue
        strip_id = row.get("strip_id")
        if not isinstance(station, (int, float)) or isinstance(station, bool) or not math.isfinite(float(station)):
            issues.append(("STATION_RANGE_INVALID", f"height_strategy.landmarks[{i}].station_m 必須是有限數值。"))
            continue
        if not isinstance(strip_id, str) or strip_id not in strip_by_id:
            continue
        length = _fact_strip_length(strip_id, strip_by_id, facts)
        if float(station) < 0 or (length is not None and float(station) > length + 1e-6):
            issues.append(("STATION_OUT_OF_RANGE", f"height_strategy.landmarks[{i}].station_m={float(station):.2f}m 超出 {strip_id} 帶長 0–{length if length is not None else '未知'}m。"))
    for i, row in enumerate(brief.get("height_strategy", {}).get("low_zones", [])):
        if isinstance(row, dict):
            validate_anchor_pair(f"height_strategy.low_zones[{i}]", row, "strip_id", "segment_m")
            if row.get("segment_m") is not None:
                validate_interval(
                    f"height_strategy.low_zones[{i}].segment_m", row.get("strip_id"), row.get("segment_m")
                )

    # Commander 2026-10-10: the generator needs a typology for every stretch of every strip.
    # Rows must carry segment_m, and each strip must be ≥85% covered by its rows.
    covered: dict[str, list[tuple[float, float]]] = {}
    for i, row in enumerate(brief.get("strips", [])):
        if not isinstance(row, dict):
            continue
        candidates = [row.get("segment_m")] + [
            child.get("segment_m") for child in (row.get("segments") if isinstance(row.get("segments"), list) else []) if isinstance(child, dict)
        ]
        intervals = [
            (float(seg[0]), float(seg[1])) for seg in candidates
            if isinstance(seg, list) and len(seg) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in seg)
        ]
        if not intervals:
            issues.append(("STRIP_SEGMENT_REQUIRED", f"strips[{i}] 缺少 segment_m（或 segments[].segment_m）；每列必須指定帶段，生成器才能逐段執行。"))
            continue
        covered.setdefault(str(row.get("strip_id")), []).extend(intervals)
    for strip_id_value in strip_by_id:
        length = _fact_strip_length(strip_id_value, strip_by_id, facts)
        if not length:
            continue
        merged, total = sorted(covered.get(strip_id_value, [])), 0.0
        cursor = None
        for start, end in merged:
            if cursor is None or start > cursor:
                total += max(0.0, end - start); cursor = end
            elif end > cursor:
                total += end - cursor; cursor = end
        if total < 0.85 * float(length):
            issues.append(("STRIP_COVERAGE_LOW", f"{strip_id_value} 的 strips 段落只覆蓋 {total:.0f}m／帶長 {float(length):.0f}m（<85%）；請為每段指定類型（公園段可用 park 類型）。"))

    gfa_facts = facts.get("gfa", {})
    budget = gfa_facts.get("new_gfa_budget_m2", facts.get("new_gfa_budget_m2"))
    # Compare the FAR floor against the same retained-upper scenario used to
    # derive the new-GFA budget. The lower estimate remains reported separately.
    retained_reference = gfa_facts.get("retained_upper_m2", gfa_facts.get("retained_lower_m2", 0.0))
    far_min = gfa_facts.get("far_min_for_validation", 0.70)
    land_area = facts.get("site", {}).get("land_area_m2")
    by_strip = brief.get("gfa_allocation", {}).get("by_strip", [])
    declared_total = brief.get("gfa_allocation", {}).get("total_new_gfa_m2")
    if any(not isinstance(row.get("gfa_m2"), (int, float)) or isinstance(row.get("gfa_m2"), bool) for row in by_strip):
        issues.append(("GFA_VALUE_INVALID", "by_strip 每列都必須提供數值 gfa_m2。"))
        summed_gfa = None
    else:
        summed_gfa = sum(float(row["gfa_m2"]) for row in by_strip)
    if isinstance(declared_total, (int, float)) and summed_gfa is not None and abs(float(declared_total) - summed_gfa) > 0.01:
        issues.append(("GFA_DECLARED_TOTAL_MISMATCH", f"逐帶 GFA 合計 {summed_gfa:.2f} m² 與 total_new_gfa_m2 {float(declared_total):.2f} m² 不同。"))
    if budget is None or summed_gfa is None:
        issues.append(("GFA_BUDGET_UNAVAILABLE", "新建 GFA 預算或逐帶合計未知，無法證明不超預算。"))
    elif summed_gfa > float(budget) + 0.01:
        issues.append(("GFA_BUDGET_EXCEEDED", f"新建 GFA {summed_gfa:.2f} m² 超過預算 {float(budget):.2f} m²。"))
    if land_area is None or retained_reference is None or summed_gfa is None:
        issues.append(("FAR_FLOOR_UNVERIFIABLE", "基地面積、保留建築 GFA upper 情境值或新建 GFA 未知，無法驗證總 FAR 下限。"))
    elif summed_gfa + float(retained_reference) + 0.01 < float(far_min) * float(land_area):
        issues.append(("FAR_MINIMUM_NOT_MET", f"新建加保留 GFA upper 情境值={summed_gfa + float(retained_reference):.2f} m²，低於 FAR {float(far_min):.2f} 對應 {float(far_min) * float(land_area):.2f} m²。"))

    height_facts = facts.get("height", {})
    cap = height_facts.get("cap_m", height_facts.get("height_cap_m"))
    first_floor = height_facts.get("first_floor_height_m", height_facts.get("floor_height_m"))
    standard_floor = height_facts.get("standard_floor_height_m", height_facts.get("floor_height_m"))
    if cap is None or first_floor is None or standard_floor is None:
        issues.append(("HEIGHT_RULE_UNAVAILABLE", "高度上限或層高資料缺失，無法換算樓層限制。"))
    else:
        def height_for_floors(storeys: int) -> float:
            return float(first_floor) + max(0, storeys - 1) * float(standard_floor)
        for i, row in enumerate(brief.get("strips", [])):
            floors = row.get("floors")
            if isinstance(floors, list) and len(floors) == 2:
                for storeys in floors:
                    if isinstance(storeys, int) and height_for_floors(storeys) > float(cap) + 1e-6:
                        issues.append(("FLOOR_HEIGHT_CAP_EXCEEDED", f"strips[{i}] {storeys} 層換算 {height_for_floors(storeys):.2f}m，超過 {float(cap):.2f}m。"))
        for i, row in enumerate(brief.get("height_strategy", {}).get("low_zones", [])):
            storeys = row.get("floors")
            if isinstance(storeys, int) and height_for_floors(storeys) > float(cap) + 1e-6:
                issues.append(("FLOOR_HEIGHT_CAP_EXCEEDED", f"height_strategy.low_zones[{i}] {storeys} 層換算 {height_for_floors(storeys):.2f}m，超過 {float(cap):.2f}m。"))
        for i, row in enumerate(brief.get("height_strategy", {}).get("landmarks", [])):
            value = row.get("height_m")
            if isinstance(value, (int, float)) and float(value) > float(cap) + 1e-6:
                issues.append(("LANDMARK_HEIGHT_CAP_EXCEEDED", f"height_strategy.landmarks[{i}] {float(value):.2f}m 超過 {float(cap):.2f}m。"))

    precedent_names = set()
    for precedent in facts.get("precedents", []):
        precedent_names.update(str(value).strip().casefold() for value in precedent.get("aliases", []))
        precedent_names.add(str(precedent.get("name", "")).strip().casefold())
        precedent_names.add(str(precedent.get("title", "")).strip().casefold())
    for i, precedent in enumerate(brief.get("precedents", [])):
        name = str(precedent.get("name", "")).strip().casefold()
        known = {n for n in precedent_names if len(n) >= 3}
        if name not in known and not any(n in name or name in n for n in known):
            issues.append(("PRECEDENT_UNKNOWN", f"precedents[{i}].name={precedent.get('name')!r} 不存在於事實包列出的先例庫。"))

    for i, row in enumerate(brief.get("strips", [])):
        strip = strip_by_id.get(str(row.get("strip_id", "")))
        if strip is None:
            continue
        width = strip.get("width_min_m")
        width_series = strip.get("width_series_every_25m", [])
        segment = row.get("segment_m")
        if width_series and isinstance(segment, list) and len(segment) == 2:
            lo, hi = sorted(float(v) for v in segment)
            inside = [float(s["width_m"]) for s in width_series if lo - 1e-6 <= float(s["station_m"]) <= hi + 1e-6]
            if inside:
                width = min(inside)
        elif width is None and width_series:
            width = min(float(sample["width_m"]) for sample in width_series)
        # Commander 2026-10-10: a segment may touch a narrow end point; block ends are
        # handled by the generator. Fail only when >20% of stations are <60 m or any is <45 m.
        seg_widths = []
        if width_series and isinstance(segment, list) and len(segment) == 2:
            lo, hi = sorted(float(v) for v in segment)
            seg_widths = [float(s["width_m"]) for s in width_series if lo - 1e-6 <= float(s["station_m"]) <= hi + 1e-6]
        elif width_series:
            seg_widths = [float(s["width_m"]) for s in width_series]
        narrow_share = (sum(w < 60 for w in seg_widths) / len(seg_widths)) if seg_widths else (1.0 if width is not None and float(width) < 60 else 0.0)
        too_narrow = (min(seg_widths) < 45) if seg_widths else (width is not None and float(width) < 45)
        if "perimeter" in row.get("typologies", []) and row.get("frontage") == "both_sides" and (narrow_share > 0.2 or too_narrow):
            issues.append(("NARROW_BAND_DOUBLE_PERIMETER", f"strips[{i}] 段內寬度 <60m 的樣點占 {narrow_share:.0%}、最小 {min(seg_widths) if seg_widths else float(width):.2f}m，不得採雙側周邊式（容許：<60m 樣點 ≤20% 且最小 ≥45m）。"))
    issues.extend(_semantic_location_issues(brief, facts, strip_by_id))
    wide_land_warning = _wide_land_park_coverage_issue(brief, strip_by_id)
    if wide_land_warning is not None:
        issues.append(wide_land_warning)
    return issues


def _print_validation_issues(issues: list[tuple[str, str]], prefix: str = "") -> bool:
    has_fail = False
    for code, message in issues:
        severity = "WARN" if code in WARN_CODES else "FAIL"
        has_fail = has_fail or severity == "FAIL"
        lead = f"{prefix}｜" if prefix else ""
        print(f"[{severity}] {lead}{code}｜{message}")
    return has_fail


def command_validate(args: argparse.Namespace) -> int:
    brief = _json_read(Path(args.brief))
    facts = _json_read(Path(args.facts))
    if not isinstance(brief, dict):
        raise S6BriefError("brief 根節點必須是 JSON object。")
    issues = _validate_brief(brief, facts)
    has_fail = _print_validation_issues(issues)
    if has_fail:
        print("S6 設計意圖書檢查：FAIL")
        print(f"檢查項目發現 {sum(code not in WARN_CODES for code, _ in issues)} 項阻擋錯誤、{sum(code in WARN_CODES for code, _ in issues)} 項警告。")
        return 1
    print("S6 設計意圖書檢查：WARN（僅非阻擋警告）" if issues else "S6 設計意圖書檢查：PASS（通過）")
    print("[PASS] JSON Schema、帶 ID、段落／地標站距範圍、GFA 預算、FAR 0.70 下限（保留 GFA upper 情境）、樓層高度上限、先例名稱、窄帶周邊式條件。")
    if issues:
        print(f"檢查項目發現 0 項阻擋錯誤、{len(issues)} 項警告。")
    for item in _missing_anchor_items(brief):
        print(f"[INFO] {item}：位置未指定；未從描述文字推算座標。")
    print("注意：此檢查不核准設計意圖，也不使草稿限制或證據成為正式規劃決定。")
    return 0


def _intent_markdown(brief: dict[str, Any], facts: dict[str, Any]) -> str:
    rows = [
        "# 設計意圖書",
        "",
        f"- 策略：{STRATEGY_LABELS_ZH.get(brief.get('strategy'), brief.get('strategy'))}",
        f"- 基地：{facts.get('site', {}).get('study_area_id')}（{facts.get('site', {}).get('horizontal_crs')}）",
        f"- 證據狀態：{facts.get('evidence_status')}；本文是待設計者審查的意圖，不是已核准的設計提案。",
        "",
        "## 整體構想",
        f"- 決策：{brief.get('concept', {}).get('statement_zh', '')}",
        "- 回應條件：" + "；".join(brief.get("concept", {}).get("responds_to_zh", [])),
        "",
        "## 參照先例",
    ]
    for i, precedent in enumerate(brief.get("precedents", []), start=1):
        rows.extend([f"{i}. **{precedent.get('name')}**：借鏡 {precedent.get('borrow_zh', '')}；不直接套用 {precedent.get('not_applicable_zh', '')}。"])
    rows += ["", "## 發展街道"]
    for row in brief.get("development_streets", []):
        location = _position_text(row.get("strip_id"), row.get("segment_m"))
        rows.append(f"- **{location}**：{row.get('reason_zh', '')}")
    rows += ["", "## 分段量體決策"]
    strip_facts = {str(row.get("id")): row for row in facts.get("buildable", {}).get("strips", [])}
    frontage_labels = {
        "both_sides": "雙側界定", "one_side_street": "單側臨街",
        "one_side_water": "單側臨水", "one_side_park": "單側臨公園", "none": "不設建築界面",
    }
    for row in _brief_segment_rows(brief):
        strip_id = str(row.get("strip_id", ""))
        fact = strip_facts.get(strip_id, {})
        segment_m = row.get("segment_m")
        location = _position_text(strip_id, segment_m) if segment_m is not None else (
            f"{strip_id}｜全帶（未再細分）" if not row.get("_is_child") else "位置未指定"
        )
        typologies = [TYPOLOGY_LABELS_ZH.get(kind, kind) for kind in row.get("typologies", [])]
        floors = row.get("floors")
        floor_text = f"{floors[0]}–{floors[1]} 層" if isinstance(floors, list) and len(floors) == 2 else f"{floors} 層"
        block_length = row.get("block_length_m")
        if block_length is None and isinstance(row.get("block_size_m"), dict):
            block_length = row["block_size_m"].get("along_axis")
        if isinstance(block_length, list) and len(block_length) == 2:
            block_length_text = f"{block_length[0]}–{block_length[1]}"
        else:
            block_length_text = str(block_length) if block_length is not None else "未提供"
        rows.append(
            f"- **{location}**：主類型與其他類型 { '／'.join(typologies) or '未提供' }；"
            f"界面 {frontage_labels.get(row.get('frontage'), '未提供')}；層數 {floor_text}；街廓長度 {block_length_text} m。"
        )
        length = fact.get("length_m")
        width_min, width_max, area = fact.get("width_min_m"), fact.get("width_max_m"), fact.get("area_m2")
        length_text = f"{float(length):.1f}" if isinstance(length, (int, float)) else "未知"
        width_text = f"{float(width_min):.1f}–{float(width_max):.1f}" if isinstance(width_min, (int, float)) and isinstance(width_max, (int, float)) else "未知"
        area_text = f"{float(area):,.1f}" if isinstance(area, (int, float)) else "未知"
        rows.append(f"  - 帶量測：長 {length_text} m，寬 {width_text} m，面積估算 {area_text} m²。")
        rows.append(f"  - 決策理由：{row.get('reason_zh', '')}")
    height = brief.get("height_strategy", {})
    rows += ["", "## 高度與天際線", f"- 整體理由：{height.get('reason_zh', '')}"]
    for landmark in height.get("landmarks", []):
        strip_id, station = landmark.get("strip_id"), landmark.get("station_m")
        location = (
            f"{strip_id}｜s={float(station):g} m"
            if strip_id and isinstance(station, (int, float))
            else f"{strip_id}｜位置未指定" if strip_id else "位置未指定"
        )
        rows.append(f"- 地標（{location}）：高度 {landmark.get('height_m')} m；描述 {landmark.get('location_zh', '')}。理由：{landmark.get('reason_zh', '')}")
    for low in height.get("low_zones", []):
        location = _position_text(low.get("strip_id"), low.get("segment_m"))
        floors = low.get("floors")
        floor_text = f"{floors[0]}–{floors[1]}" if isinstance(floors, list) and len(floors) == 2 else str(floors)
        rows.append(f"- 低層區（{location}）：{floor_text} 層；描述 {low.get('location_zh', '')}。理由：{low.get('reason_zh', '')}")
    rows += ["", "## 開放空間"]
    for park in brief.get("open_spaces", []):
        location = _position_text(park.get("strip_id"), park.get("segment_m"))
        rows.append(f"- **{park.get('name_zh')}（{location}）**：描述 {park.get('location_zh', '')}；目標面積 {park.get('area_m2_target')} m²；用途 {park.get('use_zh')}。理由：{park.get('reason_zh', '')}")
    movement = brief.get("movement", {})
    rows += ["", "## 移動策略"]
    rows.append(f"- 步行與自行車主線：{movement.get('pedestrian_cycle_spine_zh', '')}")
    rows.append(f"- 汽車接入：{movement.get('car_access_zh', '')}")
    rows.append(f"- 服務迴路：{movement.get('service_loop_zh', '')}")
    if movement.get("bike_parking_zh"):
        rows.append(f"- 自行車停車：{movement.get('bike_parking_zh')}")
    allocation = brief.get("gfa_allocation", {})
    rows += ["", "## 容積分配", "| 帶 | 新建 GFA（m²） |", "|---|---:|"]
    for row in allocation.get("by_strip", []):
        rows.append(f"| {row.get('strip_id')} | {row.get('gfa_m2')} |")
    rows.append(f"| **合計** | **{allocation.get('total_new_gfa_m2')}** |")
    rows.append(f"- FAR 核對：{allocation.get('far_check_zh', '')}")
    rows += ["", "## 取捨與風險"]
    rows.extend(f"- {item}" for item in brief.get("tradeoffs", []))
    rows += ["", "## 出處"]
    rows.extend(f"- {source}" for source in brief.get("sources", []))
    rows += [
        "", "## 圖面方法",
        "有錨點的帶段以 facts 帶幾何和軸線切片；每 10 m 設橫剖面，區段邊界依 brief 站距處理。帶長使用 facts 的 length_m；若軸線幾何長度不同，依兩者長度比例映射到完整帶幾何。",
        "段內第一類型填色；同段其他類型以斜線表示。公園和低層區只在帶號與段距完整時著色。缺錨點的項目標示「位置未指定」，不由描述文字推算。",
        "", "## 使用限制",
        "基地事實包中的 NAIN、保留建築樓層與 GFA 均保留其來源和估算狀態；zone 偏好和 Dakpark 高差仍按其原始草稿／作品集假設標示。圖中的開放空間是 brief 錨定帶段的候選切片，目標面積不代表切片的實測面積，也不是已核准邊界。",
        "",
    ]
    return "\n".join(rows)


def command_render(args: argparse.Namespace) -> int:
    brief = _json_read(Path(args.brief))
    facts = _json_read(Path(args.facts))
    if not isinstance(brief, dict):
        raise S6BriefError("brief 根節點必須是 JSON object。")
    issues = _validate_brief(brief, facts)
    if _print_validation_issues(issues):
        raise S6BriefError("brief 未通過 schema／語意檢查；不輸出設計意圖書。")
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    markdown_path = output / "design-intent-zh.md"
    png_path = output / "design-intent-zh.png"
    markdown_path.write_text(_intent_markdown(brief, facts), encoding="utf-8")
    _draw_site_figure(facts, png_path, brief=brief)
    print(f"已輸出中文設計意圖書：{markdown_path}")
    print(f"已輸出策略示意圖：{png_path}")
    for item in _missing_anchor_items(brief):
        print(f"[INFO] {item}：位置未指定；圖面未推算座標。")
    return 0


def command_compare(args: argparse.Namespace) -> int:
    facts = _json_read(Path(args.facts))
    briefs_dir = Path(args.briefs_dir)
    briefs: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        path = briefs_dir / f"{strategy}.json"
        brief = _json_read(path)
        if not isinstance(brief, dict):
            raise S6BriefError(f"brief 根節點必須是 JSON object：{path}")
        if brief.get("strategy") != strategy:
            raise S6BriefError(f"{path} 的 strategy={brief.get('strategy')!r}，預期 {strategy!r}。")
        issues = _validate_brief(brief, facts)
        if _print_validation_issues(issues, path.name):
            raise S6BriefError(f"{path} 未通過 schema／語意檢查；不輸出比較圖。")
        briefs.append(brief)
    destination = Path(args.out)
    _draw_comparison_figure(facts, briefs, destination)
    print(f"已輸出四策略同比例尺比較圖：{destination}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="以確定性來源建立與驗證 S6 設計意圖書資料包。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    facts = subparsers.add_parser("facts", help="由唯讀資料庫副本建立 site-facts JSON 與示意圖")
    facts.add_argument("--database", required=True, help="位於 /private/tmp 的 SQLite backup 副本")
    facts.add_argument("--network-root", required=True, help="J11f run-13 輸出目錄")
    facts.add_argument("--out", required=True, help="輸出目錄")
    facts.set_defaults(func=command_facts)
    prompt = subparsers.add_parser("prompt", help="組裝策略提示與本機形態知識情境包")
    prompt.add_argument("--facts", required=True)
    prompt.add_argument("--strategy", choices=STRATEGIES, required=True)
    prompt.add_argument("--kb", required=True, help="唯讀知識庫根目錄（含 knowledge/v2）")
    prompt.add_argument("--out", required=True)
    prompt.set_defaults(func=command_prompt)
    validate = subparsers.add_parser("validate", help="以既有 schema 與基地事實檢查手寫 JSON")
    validate.add_argument("--brief", required=True)
    validate.add_argument("--facts", required=True)
    validate.set_defaults(func=command_validate)
    render = subparsers.add_parser("render", help="輸出中文設計意圖書 Markdown 與策略示意圖")
    render.add_argument("--brief", required=True)
    render.add_argument("--facts", required=True)
    render.add_argument("--out", required=True)
    render.set_defaults(func=command_render)
    compare = subparsers.add_parser("compare", help="輸出四策略同一比例尺的 2×2 比較圖")
    compare.add_argument("--briefs-dir", required=True)
    compare.add_argument("--facts", required=True)
    compare.add_argument("--out", required=True)
    compare.set_defaults(func=command_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (S6BriefError, sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"S6 INCOMPLETE｜{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
