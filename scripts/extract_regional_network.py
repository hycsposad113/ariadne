#!/usr/bin/env python3
"""ETL script to extract regional road networks and grade separation unlinks from OSM PBF.

Follows syntax-network-policy-v1 (ODbL 1.0, (C) OpenStreetMap contributors):
- Extracts highway classes per policy: primary, secondary, tertiary, residential, living_street,
  pedestrian, footway, cycleway, path, steps, service, motorway, trunk.
- Excludes: construction, proposed, abandoned, disused, raceway, corridor, platform, elevator.
- Filters access: excludes private/no unless foot or bicycle permissive/yes.
- Reprojects from EPSG:4326 (WGS84) to EPSG:28992 (RD New metres).
- Detects grade-separated crossings (different layer/bridge/tunnel or unshared OSM nodes)
  and outputs them as unlinks XY pairs for PST.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import osmium
import pyproj
from pyproj.exceptions import ProjError
from shapely.errors import GEOSException
from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon, shape
from shapely.strtree import STRtree

# Project paths
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from urban_design.regional_network import evaluate_way_for_mode

_PRIMARY_STUDY_AREA = (
    ROOT
    / ".urban_design_runtime/artifacts/study-area-bridge/study-areas/4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson"
)
_FALLBACK_STUDY_AREA_PROJECT = (
    Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/artifacts/study-area-bridge/study-areas/4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson")
)
_FALLBACK_STUDY_AREA_REPO = ROOT / "artifacts/week4-repair-r02/syntax/study-area.geojson"

DEFAULT_STUDY_AREA = (
    _PRIMARY_STUDY_AREA
    if _PRIMARY_STUDY_AREA.exists()
    else (_FALLBACK_STUDY_AREA_PROJECT if _FALLBACK_STUDY_AREA_PROJECT.exists() else _FALLBACK_STUDY_AREA_REPO)
)
DEFAULT_PBF = Path.home() / ".local/share/urban-design-data/osm/zuid-holland-260922.osm.pbf"
FALLBACK_PBF = ROOT / "artifacts/week4-regional-osm/raw/zuid-holland-260922.osm.pbf"
DEFAULT_POLY = ROOT / "artifacts/week4-regional-osm/raw/zuid-holland.poly"
DEFAULT_DOWNLOAD_RECORD = ROOT / "artifacts/week4-regional-osm/download-record.json"
LOCAL_OUTPUT_ROOT = Path.home() / ".local/share/urban-design-data/week5-syntax-modes/extracted"

INCLUDED_HIGHWAYS = {
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "pedestrian",
    "footway",
    "cycleway",
    "path",
    "steps",
    "service",
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
}

EXCLUDED_HIGHWAYS = {
    "construction",
    "proposed",
    "abandoned",
    "disused",
    "raceway",
    "corridor",
    "platform",
    "elevator",
}


from urban_design.network_unlinks import (  # noqa: E402
    _normalized_vertical_tag, _vertical_signature, _vertical_signature_is_usable,
    _point_intersections, detect_grade_separated_unlinks,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_recorded_file(path: Path, record: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    if record.get("status_code") != 200 or record.get("success") is not True:
        raise ValueError(f"{label} retained download record is not a successful HTTP 200 response")
    expected_size = record.get("size_bytes")
    expected_hash = record.get("sha256")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int):
        raise ValueError(f"{label} retained download record has no valid byte count")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError(f"{label} retained download record has no SHA-256")
    actual_size = path.stat().st_size
    actual_hash = sha256_file(path)
    if actual_size != expected_size or actual_hash != expected_hash:
        raise ValueError(f"{label} does not match the retained download record")
    return {"size_bytes": actual_size, "sha256": actual_hash}


def load_geofabrik_poly(path: Path, transformer: pyproj.Transformer) -> MultiPolygon:
    """Read a Geofabrik .poly boundary and project it without geometric repair."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("Geofabrik .poly file is empty")
    outer_rings: list[list[tuple[float, float]]] = []
    holes_by_outer: dict[int, list[list[tuple[float, float]]]] = {}
    current: list[tuple[float, float]] = []
    is_hole = False
    last_outer_index: int | None = None

    def commit_ring() -> None:
        nonlocal current, is_hole, last_outer_index
        if not current:
            return
        projected = [transformer.transform(lon, lat) for lon, lat in current]
        if len(projected) < 4 or projected[0] != projected[-1]:
            raise ValueError("Geofabrik .poly contains an open or underspecified ring")
        if is_hole:
            if last_outer_index is None:
                raise ValueError("Geofabrik .poly hole appears before an outer ring")
            holes_by_outer[last_outer_index].append(projected)
        else:
            outer_rings.append(projected)
            last_outer_index = len(outer_rings) - 1
            holes_by_outer[last_outer_index] = []
        current = []
        is_hole = False

    for line in lines[1:]:
        value = line.strip()
        if value == "END":
            if current:
                commit_ring()
            else:
                break
            continue
        parts = value.split()
        if len(parts) == 2:
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except ValueError:
                is_hole = value.startswith("!")
                continue
            if not math.isfinite(lon) or not math.isfinite(lat):
                raise ValueError("Geofabrik .poly contains a non-finite coordinate")
            current.append((lon, lat))
        elif value.startswith("!"):
            is_hole = True

    commit_ring()
    polygons = [
        Polygon(outer_rings[index], holes_by_outer[index])
        for index in range(len(outer_rings))
    ]
    if not polygons or any(poly.is_empty or not poly.is_valid for poly in polygons):
        raise ValueError("Geofabrik .poly boundary is empty or invalid")
    result = MultiPolygon(polygons)
    if result.is_empty or not result.is_valid:
        raise ValueError("Geofabrik .poly boundary is empty or invalid")
    return result


class RegionalOsmHandler(osmium.SimpleHandler):
    def __init__(
        self,
        buffer_polygon: Any,
        transformer: pyproj.Transformer,
        *,
        include_regional_highways: bool = False,
        network_mode: str | None = None,
    ) -> None:
        super().__init__()
        self.buffer_polygon = buffer_polygon
        self.bounds = buffer_polygon.bounds
        self.transformer = transformer
        self.include_regional_highways = include_regional_highways
        self.network_mode = network_mode
        self.ways: list[dict[str, Any]] = []
        self.missing_location_way_count = 0
        self.invalid_geometry_way_count = 0
        self.imputed_access_way_count = 0
        self.explicit_access_way_count = 0
        self.highway_breakdown: dict[str, int] = {}

    def way(self, w: osmium.osm.Way) -> None:
        if "highway" not in w.tags:
            return

        if self.network_mode:
            tag_dict = {tag.k: tag.v for tag in w.tags}
            included, is_imputed, reason = evaluate_way_for_mode(tag_dict, self.network_mode)
            if not included:
                return
            highway = tag_dict.get("highway", "unknown")
        else:
            highway = w.tags.get("highway")
            if not highway or highway in EXCLUDED_HIGHWAYS or highway not in INCLUDED_HIGHWAYS:
                return
            if highway in {"motorway", "motorway_link", "trunk", "trunk_link"} and not self.include_regional_highways:
                return

            access = w.tags.get("access")
            if access in {"private", "no"}:
                foot = w.tags.get("foot")
                bicycle = w.tags.get("bicycle")
                permitted_override = (
                    foot in {"yes", "designated", "permissive"}
                    or bicycle in {"yes", "designated", "permissive"}
                )
                if not permitted_override:
                    return
            is_imputed = False
            reason = "legacy_v1_inclusion"

        coordinates: list[tuple[float, float]] = []
        node_coordinates: dict[int, tuple[float, float]] = {}
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        try:
            for node in w.nodes:
                lon, lat = node.lon, node.lat
                x, y = self.transformer.transform(lon, lat)
                if not math.isfinite(x) or not math.isfinite(y):
                    raise ProjError("OSM way transformed to a non-finite coordinate")
                if x < min_x: min_x = x
                if x > max_x: max_x = x
                if y < min_y: min_y = y
                if y > max_y: max_y = y
                coordinate = (round(x, 3), round(y, 3))
                coordinates.append(coordinate)
                node_coordinates[int(node.ref)] = coordinate
        except (osmium.InvalidLocationError, ProjError, ValueError, TypeError):
            self.missing_location_way_count += 1
            return

        if len(coordinates) < 2:
            return

        b_minx, b_miny, b_maxx, b_maxy = self.bounds
        if max_x < b_minx or min_x > b_maxx or max_y < b_miny or min_y > b_maxy:
            return

        try:
            complete_way = LineString(coordinates)
        except GEOSException:
            self.invalid_geometry_way_count += 1
            return
        if complete_way.is_empty or not complete_way.is_valid:
            self.invalid_geometry_way_count += 1
            return
        if not complete_way.intersects(self.buffer_polygon):
            return

        if self.network_mode:
            if is_imputed:
                self.imputed_access_way_count += 1
            else:
                self.explicit_access_way_count += 1
            self.highway_breakdown[highway] = self.highway_breakdown.get(highway, 0) + 1

        signature = _vertical_signature(w.tags)
        self.ways.append(
            {
                "osm_id": int(w.id),
                "highway": highway,
                "name": w.tags.get("name", ""),
                "vertical_signature": signature,
                "node_coordinates": node_coordinates,
                "coords": coordinates,
                "network_mode": self.network_mode,
                "is_imputed": is_imputed,
                "inclusion_reason": reason,
            }
        )


def extract_network_and_unlinks(
    pbf_path: Path,
    study_area_geojson_path: Path,
    buffer_radius_m: float,
    output_dir: Path,
    *,
    source_coverage_geometry: Any | None = None,
    pbf_identity: Mapping[str, Any] | None = None,
    poly_identity: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    include_regional_highways: bool = False,
    network_mode: str | None = None,
) -> dict[str, Any]:
    """Extract ways intersecting the exact EPSG:28992 buffer and preserve topology evidence."""
    started = time.perf_counter()
    started_at_utc = datetime.now(timezone.utc).isoformat()
    if not math.isfinite(buffer_radius_m) or buffer_radius_m <= 0:
        raise ValueError("buffer_radius_m must be a positive finite number")
    sa_data = json.loads(study_area_geojson_path.read_text(encoding="utf-8"))
    sa_geom = shape(sa_data["geometry"])
    if sa_geom.is_empty or not sa_geom.is_valid:
        raise ValueError("StudyArea geometry must be non-empty and valid")
    buffer_poly = sa_geom.buffer(buffer_radius_m)
    if buffer_poly.is_empty or not buffer_poly.is_valid:
        raise ValueError("derived acquisition envelope must be non-empty and valid")

    tf_to_rd = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
    print(f"Reading OSM PBF for the exact {buffer_radius_m:g}m StudyArea envelope (mode={network_mode or 'legacy_all'})...")
    read_started = time.perf_counter()
    handler = RegionalOsmHandler(
        buffer_polygon=buffer_poly,
        transformer=tf_to_rd,
        include_regional_highways=include_regional_highways,
        network_mode=network_mode,
    )
    handler.apply_file(str(pbf_path), locations=True)
    t_read = time.perf_counter() - read_started
    print(
        f"PBF read completed in {t_read:.2f}s. Intersecting ways: {len(handler.ways)}; "
        f"imputed ways: {handler.imputed_access_way_count}; explicit ways: {handler.explicit_access_way_count}; "
        f"ways skipped for missing locations: {handler.missing_location_way_count}; "
        f"invalid geometries: {handler.invalid_geometry_way_count}."
    )

    features: list[dict[str, Any]] = []
    line_geoms: list[LineString] = []
    line_metadata: list[dict[str, Any]] = []

    for way in handler.ways:
        line = LineString(way["coords"])
        clipped = line.intersection(buffer_poly)
        if clipped.is_empty:
            continue
        geometries = (
            [clipped]
            if isinstance(clipped, LineString)
            else (list(clipped.geoms) if isinstance(clipped, MultiLineString) else [])
        )
        for index, sub_geometry in enumerate(geometries):
            if sub_geometry.is_empty or len(sub_geometry.coords) < 2 or sub_geometry.length < 1.0:
                continue
            feature_id = (
                f"way/{way['osm_id']}_{index}"
                if len(geometries) > 1
                else f"way/{way['osm_id']}"
            )
            signature = way["vertical_signature"]
            feature = {
                "type": "Feature",
                "id": feature_id,
                "geometry": {
                    "type": "LineString",
                    "coordinates": list(sub_geometry.coords),
                },
                "properties": {
                    "osm_id": way["osm_id"],
                    "highway": way["highway"],
                    "name": way["name"],
                    "layer": signature[0],
                    "bridge": signature[1],
                    "tunnel": signature[2],
                    "level": signature[3],
                    "length_m": round(float(sub_geometry.length), 2),
                    "network_mode": way.get("network_mode"),
                    "is_imputed": way.get("is_imputed", False),
                    "inclusion_reason": way.get("inclusion_reason", ""),
                },
            }
            features.append(feature)
            line_geoms.append(sub_geometry)
            line_metadata.append(
                {
                    "feature_id": feature_id,
                    "osm_id": way["osm_id"],
                    "vertical_signature": signature,
                    "source_node_coordinates": way["node_coordinates"],
                }
            )

    # Deduplicate only wholly coincident redundant ways; partially overlapping ways remain visible.
    seen_segments: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    deduped_features: list[dict[str, Any]] = []
    deduped_line_geometries: list[LineString] = []
    deduped_line_metadata: list[dict[str, Any]] = []
    for feature, line_geometry, metadata in zip(features, line_geoms, line_metadata):
        coordinates = feature["geometry"]["coordinates"]
        feature_segments = [
            tuple(sorted((tuple(first), tuple(second))))
            for first, second in zip(coordinates, coordinates[1:])
        ]
        if all(segment in seen_segments for segment in feature_segments):
            continue
        seen_segments.update(feature_segments)
        deduped_features.append(feature)
        deduped_line_geometries.append(line_geometry)
        deduped_line_metadata.append(metadata)

    features = deduped_features
    line_geoms = deduped_line_geometries
    line_metadata = deduped_line_metadata
    unlinks_list = detect_grade_separated_unlinks(line_geoms, line_metadata)
    print(f"Clipped network contains {len(features)} lines; detected {len(unlinks_list)} unlink points.")

    extract_covers_envelope = bool(
        source_coverage_geometry is not None
        and not source_coverage_geometry.is_empty
        and source_coverage_geometry.is_valid
        and source_coverage_geometry.covers(buffer_poly)
    )
    if output_dir.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("derived GeoJSON must be written outside the Git worktree")
    output_dir.mkdir(parents=True, exist_ok=True)

    mode_prefix = f"{network_mode}_" if network_mode else ""
    suffix = f"{mode_prefix}{int(buffer_radius_m)}m"
    geojson_out = output_dir / f"network_{suffix}.geojson"
    unlinks_out = output_dir / f"unlinks_{suffix}.json"
    manifest_out = output_dir / f"extraction-manifest_{suffix}.json"
    if geojson_out.exists() or unlinks_out.exists() or manifest_out.exists():
        raise FileExistsError(f"refusing to overwrite existing extraction outputs for {suffix}")
    feature_collection = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": features,
    }
    with geojson_out.open("x", encoding="utf-8") as stream:
        json.dump(feature_collection, stream, ensure_ascii=False, indent=2)
    with unlinks_out.open("x", encoding="utf-8") as stream:
        json.dump(unlinks_list, stream, ensure_ascii=False, indent=2)

    total_time = time.perf_counter() - started
    total_evaluated = handler.imputed_access_way_count + handler.explicit_access_way_count
    imputed_ratio = round(handler.imputed_access_way_count / total_evaluated, 4) if total_evaluated > 0 else 0.0

    summary = {
        "schema_version": "regional-osm-extract-v2",
        "policy_version": "syntax-network-policy-v2" if network_mode else "syntax-network-policy-v1",
        "network_mode": network_mode,
        "started_at_utc": started_at_utc,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "buffer_radius_m": buffer_radius_m,
        "line_count": len(features),
        "unlink_count": len(unlinks_list),
        "imputed_access_way_count": handler.imputed_access_way_count,
        "explicit_access_way_count": handler.explicit_access_way_count,
        "imputed_ratio": imputed_ratio,
        "highway_breakdown": handler.highway_breakdown,
        "missing_location_way_count": handler.missing_location_way_count,
        "invalid_geometry_way_count": handler.invalid_geometry_way_count,
        "geojson_file": str(geojson_out),
        "unlinks_file": str(unlinks_out),
        "pbf_identity": dict(pbf_identity or {}),
        "poly_identity": dict(poly_identity or {}),
        "extract_covers_envelope": extract_covers_envelope,
        "coverage_basis": (
            "The retained Geofabrik .poly contains the derived geographic envelope; "
            "this does not establish OSM feature completeness or semantics."
            if extract_covers_envelope
            else "The retained Geofabrik .poly does not verify containment of the derived envelope."
        ),
        "include_regional_highways": include_regional_highways,
        "extraction_seconds": round(total_time, 3),
        "pbf_read_seconds": round(t_read, 3),
        "limitations": [
            "Geographic extract-envelope containment does not establish OSM feature completeness or semantic completeness.",
            "Network policy remains EXPLORATORY_PENDING_DESIGNER_APPROVAL.",
            "Ways with missing node locations or invalid geometry are counted and excluded.",
            "Directionality is not modeled by undirected PST angular segment analysis.",
        ],
    }
    manifest = {
        "schema_version": "regional-osm-extraction-manifest-v1",
        "created_at_utc": summary["completed_at_utc"],
        "inputs": {
            "study_area": {
                "path": str(study_area_geojson_path.resolve()),
                "size_bytes": study_area_geojson_path.stat().st_size,
                "sha256": sha256_file(study_area_geojson_path),
                "crs": "EPSG:28992",
            },
            "pbf": {"path": str(pbf_path.resolve()), **dict(pbf_identity or {})},
            "poly": dict(poly_identity or {}),
            "source": dict(source_metadata or {}),
        },
        "extraction": {
            "buffer_radius_m": buffer_radius_m,
            "network_mode": network_mode,
            "line_count": len(features),
            "unlink_count": len(unlinks_list),
            "imputed_access_way_count": handler.imputed_access_way_count,
            "explicit_access_way_count": handler.explicit_access_way_count,
            "imputed_ratio": imputed_ratio,
            "highway_breakdown": handler.highway_breakdown,
            "missing_location_way_count": handler.missing_location_way_count,
            "invalid_geometry_way_count": handler.invalid_geometry_way_count,
            "include_regional_highways": include_regional_highways,
            "extract_covers_envelope": extract_covers_envelope,
            "coverage_basis": summary["coverage_basis"],
            "extraction_seconds": summary["extraction_seconds"],
            "pbf_read_seconds": summary["pbf_read_seconds"],
            "limitations": summary["limitations"],
        },
        "outputs": {
            "network": {
                "path": str(geojson_out.resolve()),
                "size_bytes": geojson_out.stat().st_size,
                "sha256": sha256_file(geojson_out),
            },
            "unlinks": {
                "path": str(unlinks_out.resolve()),
                "size_bytes": unlinks_out.stat().st_size,
                "sha256": sha256_file(unlinks_out),
            },
        },
    }
    with manifest_out.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    summary["manifest_file"] = str(manifest_out)
    return summary


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return LOCAL_OUTPUT_ROOT / f"run-{stamp}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract regional OSM network and unlinks")
    parser.add_argument(
        "--pbf",
        type=Path,
        default=DEFAULT_PBF if DEFAULT_PBF.exists() else FALLBACK_PBF,
        help="Path to the retained OSM PBF bytes",
    )
    parser.add_argument("--poly", type=Path, default=DEFAULT_POLY, help="Retained Geofabrik .poly boundary")
    parser.add_argument("--download-record", type=Path, default=DEFAULT_DOWNLOAD_RECORD)
    parser.add_argument("--study-area", type=Path, default=DEFAULT_STUDY_AREA)
    parser.add_argument("--buffer-m", type=float, default=1500.0)
    parser.add_argument(
        "--regional-scale",
        action="store_true",
        help="Include the policy's conditional motorway/trunk categories for the 10km scale only",
    )
    parser.add_argument(
        "--network-mode",
        choices=["pedestrian", "bicycle", "motor_vehicle"],
        default=None,
        help="Mode-specific network filtering per PD-20: pedestrian (800m), bicycle (2km), motor_vehicle (10km)",
    )
    parser.add_argument("--output-dir", type=Path, default=_default_output_dir())
    args = parser.parse_args(argv)

    try:
        for required in (args.pbf, args.poly, args.download_record, args.study_area):
            if not required.is_file():
                raise FileNotFoundError(f"required retained input is missing: {required}")
        if args.output_dir.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("derived GeoJSON output must be outside the Git worktree")

        download_record = json.loads(args.download_record.read_text(encoding="utf-8"))
        pbf_record = download_record["files"]["pbf"]
        poly_record = download_record["files"]["poly"]
        pbf_identity = verify_recorded_file(args.pbf, pbf_record, label="PBF")
        poly_identity = verify_recorded_file(args.poly, poly_record, label=".poly")
        transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
        source_coverage = load_geofabrik_poly(args.poly, transformer)

        summary = extract_network_and_unlinks(
            pbf_path=args.pbf,
            study_area_geojson_path=args.study_area,
            buffer_radius_m=args.buffer_m,
            output_dir=args.output_dir,
            source_coverage_geometry=source_coverage,
            pbf_identity=pbf_identity,
            poly_identity={"path": str(args.poly.resolve()), **poly_identity},
            source_metadata={
                "provider": download_record.get("provider"),
                "license": download_record.get("license"),
                "attribution": download_record.get("attribution"),
                "retrieval_record_path": str(args.download_record.resolve()),
                "retrieval_record_size_bytes": args.download_record.stat().st_size,
                "retrieval_record_sha256": sha256_file(args.download_record),
                "pbf_url": pbf_record.get("url"),
                "poly_url": poly_record.get("url"),
                "pbf_last_modified": pbf_record.get("headers", {}).get("last-modified"),
            },
            include_regional_highways=args.regional_scale,
            network_mode=args.network_mode,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
