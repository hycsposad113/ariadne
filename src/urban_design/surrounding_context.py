"""Offline OSM context extraction and read-only context delivery for Rotterdam M4H.

Context is a display layer bound to a confirmed StudyArea snapshot. It is not
an analysis result and never writes project state or the Design Ledger.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.metadata
import json
import math
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Mapping, Sequence

import osmium
from pyproj import Transformer
from shapely import from_wkb
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Polygon, mapping, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

from .geometry import canonical_geometry_hash


CONTEXT_SCHEMA_VERSION = "osm-surrounding-context-v1"
PROJECT_ID = "rotterdam-m4h-pilot-project"
CONTEXT_CRS = "EPSG:28992"
CONTEXT_UNITS = "m"
DEFAULT_CONTEXT_DISTANCE_M = 2000.0
THREE_DBAG_PRIORITY_DISTANCE_M = 500.0
LEVEL_DISPLAY_HEIGHT_M = 3.0
LEVEL_DISPLAY_POLICY = "osm-building-levels-display-v1"
OSM_LICENSE = "ODbL 1.0"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"

LAYER_NAMES = ("buildings", "water", "green", "roads")
GREEN_LANDUSE = frozenset({
    "allotments", "forest", "grass", "meadow", "orchard", "recreation_ground",
    "village_green", "vineyard", "wood",
})
GREEN_LEISURE = frozenset({
    "common", "garden", "golf_course", "nature_reserve", "park", "pitch",
    "recreation_ground",
})
WATERWAY_SURFACES = frozenset({"basin", "canal", "dock", "lock", "riverbank"})
_NUMBER_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([a-zA-Z'\"]*)\s*$")
_LINE_TYPES = (LineString, MultiLineString)
_POLYGON_TYPES = (Polygon, MultiPolygon)


class ContextDataError(ValueError):
    """Context artifacts or their provenance failed validation."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def parse_osm_height_m(raw: Any) -> float | None:
    """Parse numeric OSM height tags in metres or explicitly marked feet."""
    if raw is None:
        return None
    match = _NUMBER_RE.match(str(raw))
    if not match:
        return None
    value = _finite_number(match.group(1))
    unit = match.group(2).strip().lower()
    if value is None or value <= 0:
        return None
    if unit in {"", "m", "meter", "meters", "metre", "metres"}:
        return value
    if unit in {"ft", "foot", "feet", "'", "\""}:
        return value * 0.3048
    return None


def parse_building_levels(raw: Any) -> float | None:
    if raw is None:
        return None
    value = _finite_number(str(raw).split(";")[0])
    return value if value is not None and value > 0 else None


def _feature_geometry(feature: Mapping[str, Any]):
    raw = feature.get("geometry")
    try:
        geometry = shape(raw) if isinstance(raw, Mapping) else raw
    except Exception as exc:  # noqa: BLE001 - normalize geometry parser failures.
        raise ContextDataError("context feature geometry is invalid") from exc
    if geometry is None or geometry.is_empty or not geometry.is_valid:
        raise ContextDataError("context feature geometry is empty or invalid")
    return geometry


def _read_polygonal_geojson(path: Path):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        raw_geometry = document.get("geometry", document) if isinstance(document, dict) else None
        geometry = shape(raw_geometry)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContextDataError("StudyArea GeoJSON could not be read") from exc
    if not isinstance(geometry, _POLYGON_TYPES) or geometry.is_empty or not geometry.is_valid:
        raise ContextDataError("StudyArea must be a valid, non-empty Polygon or MultiPolygon")
    return document, raw_geometry, geometry


def _polygon_parts(geometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry] if not geometry.is_empty and geometry.area > 0 else []
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty and part.area > 0]
    if isinstance(geometry, GeometryCollection):
        parts: list[Polygon] = []
        for member in geometry.geoms:
            parts.extend(_polygon_parts(member))
        return parts
    return []


def _line_parts(geometry) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry] if not geometry.is_empty and geometry.length > 0 else []
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if not part.is_empty and part.length > 0]
    if isinstance(geometry, GeometryCollection):
        parts: list[LineString] = []
        for member in geometry.geoms:
            parts.extend(_line_parts(member))
        return parts
    return []


def _polygonal_only(geometry):
    parts = _polygon_parts(geometry)
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _linear_only(geometry):
    parts = _line_parts(geometry)
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else MultiLineString(parts)


def _classify_area(tags: Mapping[str, str]) -> str | None:
    building = tags.get("building")
    if building and building.lower() not in {"no", "false", "0"}:
        return "buildings"
    if tags.get("natural") == "water" or tags.get("waterway") in WATERWAY_SURFACES:
        return "water"
    if tags.get("landuse") in GREEN_LANDUSE or tags.get("leisure") in GREEN_LEISURE:
        return "green"
    return None


def _project_geometry(geometry, transformer: Transformer):
    return transform(transformer.transform, geometry)


def _parse_height_table(path: Path | None, study_geometry_hash: str):
    if path is None:
        return None, {}, None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextDataError("3D BAG height table could not be read") from exc
    if document.get("study_area_geometry_sha256") != study_geometry_hash:
        raise ContextDataError("3D BAG height table StudyArea geometry hash does not match the extraction boundary")
    if float(document.get("buffer_distance_m", -1)) != THREE_DBAG_PRIORITY_DISTANCE_M:
        raise ContextDataError("3D BAG height table is not scoped to the approved 500 m priority buffer")
    height_by_bag: dict[str, dict[str, Any]] = {}
    for record in document.get("records", []):
        if not isinstance(record, dict) or record.get("status") != "AVAILABLE":
            continue
        bag_id = record.get("bag_identificatie")
        height = _finite_number(record.get("height_above_ground_m"))
        if isinstance(bag_id, str) and bag_id and height is not None and height > 0:
            height_by_bag[bag_id] = record
    return document, height_by_bag, sha256_file(path)


def _gpkg_geometry(blob: bytes):
    if len(blob) < 8 or blob[:2] != b"GP":
        raise ContextDataError("3D BAG tile contains a malformed GeoPackage geometry")
    envelope_type = (blob[3] >> 1) & 0x07
    envelope_lengths = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope_type not in envelope_lengths:
        raise ContextDataError("3D BAG GeoPackage geometry has an unsupported envelope")
    offset = 8 + envelope_lengths[envelope_type]
    try:
        geometry = from_wkb(blob[offset:])
    except Exception as exc:  # noqa: BLE001 - normalize GEOS and WKB failures.
        raise ContextDataError("3D BAG GeoPackage geometry could not be parsed") from exc
    if not isinstance(geometry, _POLYGON_TYPES) or geometry.is_empty or not geometry.is_valid:
        raise ContextDataError("3D BAG pand footprint is not a valid polygon")
    return geometry


def _load_3dbag_footprints(
    tile_paths: Sequence[str | Path],
    eligible_bag_ids: set[str],
    priority_buffer,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    footprints: dict[str, list[Any]] = defaultdict(list)
    tile_metadata: list[dict[str, Any]] = []
    for raw_path in tile_paths:
        path = Path(raw_path)
        raw = path.read_bytes()
        try:
            database_bytes = gzip.decompress(raw) if path.suffix == ".gz" else raw
        except OSError as exc:
            raise ContextDataError(f"3D BAG tile {path.name} is not a readable gzip file") from exc
        connection = sqlite3.connect(":memory:")
        try:
            connection.deserialize(database_bytes)
            tile_row = connection.execute(
                "SELECT srs_id FROM gpkg_contents WHERE table_name='pand' AND data_type='features'"
            ).fetchone()
            if tile_row is None or int(tile_row[0]) != 7415:
                raise ContextDataError(f"3D BAG tile {path.name} has an unexpected horizontal/vertical CRS")
            for bag_id, blob in connection.execute("SELECT identificatie, geom FROM pand"):
                if bag_id not in eligible_bag_ids:
                    continue
                geometry = _gpkg_geometry(blob)
                if geometry.intersects(priority_buffer):
                    footprints[str(bag_id)].append(geometry)
        except sqlite3.DatabaseError as exc:
            raise ContextDataError(f"3D BAG tile {path.name} is not a readable GeoPackage") from exc
        finally:
            connection.close()
        tile_metadata.append({
            "file": path.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "crs": "EPSG:7415 (EPSG:28992 horizontal + EPSG:5709 vertical)",
        })
    merged = {bag_id: unary_union(parts) for bag_id, parts in footprints.items()}
    return merged, tile_metadata


def _tag_bag_id(tags: Mapping[str, str]) -> str | None:
    for key in ("ref:bag", "ref:bag:identificatie", "building:ref:bag", "bag"):
        value = tags.get(key)
        if value:
            return value.strip()
    return None


def _bag_id_by_footprint(geometry, footprint_index: STRtree | None, bag_ids: Sequence[str], footprints: Mapping[str, Any]) -> str | None:
    if footprint_index is None:
        return None
    point = geometry.representative_point()
    candidates = footprint_index.query(point)
    candidate_ids = sorted({bag_ids[int(index)] for index in candidates})
    if len(candidate_ids) != 1:
        return None
    bag_id = candidate_ids[0]
    footprint = footprints[bag_id]
    denominator = min(float(geometry.area), float(footprint.area))
    if denominator <= 0:
        return None
    overlap = geometry.intersection(footprint).area / denominator
    return bag_id if overlap >= 0.5 else None


def _make_building_properties(
    tags: Mapping[str, str],
    geometry,
    *,
    priority_buffer,
    bag_heights: Mapping[str, Mapping[str, Any]],
    footprint_index: STRtree | None,
    bag_ids: Sequence[str],
    bag_footprints: Mapping[str, Any],
    osm_data_version: str,
) -> dict[str, Any]:
    raw_height = tags.get("height")
    osm_height = parse_osm_height_m(raw_height)
    raw_levels = tags.get("building:levels")
    levels = parse_building_levels(raw_levels)
    in_priority_area = geometry.intersects(priority_buffer)
    bag_id = _tag_bag_id(tags) if in_priority_area else None
    match_method = "osm_ref:bag"
    if bag_id not in bag_heights and in_priority_area:
        bag_id = _bag_id_by_footprint(geometry, footprint_index, bag_ids, bag_footprints)
        match_method = "3dbag_pand_footprint_representative_point_overlap"
    record = bag_heights.get(bag_id or "") if in_priority_area else None
    bag_height = _finite_number(record.get("height_above_ground_m")) if record else None

    if bag_height is not None and bag_height > 0:
        display_height = bag_height
        height_source = "3DBAG"
    elif osm_height is not None:
        display_height = osm_height
        height_source = "OSM_HEIGHT"
    elif levels is not None:
        display_height = levels * LEVEL_DISPLAY_HEIGHT_M
        height_source = "OSM_BUILDING_LEVELS_DISPLAY_ASSUMPTION"
    else:
        display_height = None
        height_source = "FOOTPRINT_ONLY"

    return {
        "building": tags.get("building"),
        "building:levels": raw_levels,
        "building:levels:parsed": levels,
        "height": raw_height,
        "osm_height_m": osm_height,
        "osm_building_levels": levels,
        "height_m": display_height,
        "height_source": height_source,
        "height_source_version": record.get("source_version") if record else osm_data_version,
        "height_unit": "m" if display_height is not None else None,
        "level_display_policy": LEVEL_DISPLAY_POLICY if height_source == "OSM_BUILDING_LEVELS_DISPLAY_ASSUMPTION" else None,
        "level_display_height_m_per_storey": LEVEL_DISPLAY_HEIGHT_M if levels is not None and record is None and osm_height is None else None,
        "within_3dbag_priority_area": bool(in_priority_area),
        "bag_identificatie": bag_id if record else None,
        "3dbag_match_method": match_method if record else None,
        "3dbag_license": "CC BY 4.0" if record else None,
        "3dbag_attribution": "© 3DBAG by tudelft3d and 3DGI" if record else None,
        "osm_data_version": osm_data_version,
        "osm_tags": dict(tags),
    }


def extract_osm_context(
    *,
    pbf_path: str | Path,
    study_area_path: str | Path,
    output_dir: str | Path,
    height_table_path: str | Path | None = None,
    three_dbag_tile_paths: Sequence[str | Path] = (),
    context_distance_m: float = DEFAULT_CONTEXT_DISTANCE_M,
    study_area_id: str = "study-area-rotterdam-m4h-pilot-project-v5",
    study_area_version: str = "v5",
    extraction_id: str | None = None,
    source_data_version: str = "2026-09-22T20:22:59Z",
    project_id: str = PROJECT_ID,
) -> dict[str, Any]:
    """Extract, project, clip, and hash the four display-only OSM context layers."""
    pbf = Path(pbf_path)
    boundary_path = Path(study_area_path)
    out = Path(output_dir)
    if not pbf.is_file() or not boundary_path.is_file():
        raise ContextDataError("OSM source and StudyArea artifact must already exist on disk")
    distance = _finite_number(context_distance_m)
    if distance is None or distance <= 0:
        raise ContextDataError("context distance must be a positive finite number of metres")
    if out.exists():
        raise ContextDataError(f"refusing to overwrite an existing context run directory: {out}")

    study_document, raw_study_geometry, study_area = _read_polygonal_geojson(boundary_path)
    study_hash = canonical_geometry_hash(raw_study_geometry)
    study_artifact_hash = sha256_file(boundary_path)
    bag_document, bag_heights, bag_table_hash = _parse_height_table(Path(height_table_path) if height_table_path else None, study_hash)
    priority_distance = THREE_DBAG_PRIORITY_DISTANCE_M
    if bag_document and str(bag_document.get("study_area_id")) != study_area_id:
        raise ContextDataError("3D BAG height table is bound to a different StudyArea id")
    if bag_document and str(bag_document.get("study_area_version")) != study_area_version:
        raise ContextDataError("3D BAG height table is bound to a different StudyArea version")
    if bag_document and bag_document.get("study_area_artifact_sha256") not in (None, study_artifact_hash, f"sha256:{study_artifact_hash}"):
        raise ContextDataError("3D BAG height table artifact hash does not match the supplied StudyArea bytes")

    context_buffer = study_area.buffer(float(distance))
    priority_buffer = study_area.buffer(priority_distance)
    if context_buffer.is_empty or not context_buffer.is_valid:
        raise ContextDataError("buffered StudyArea is invalid")
    bag_footprints, bag_tile_metadata = _load_3dbag_footprints(
        three_dbag_tile_paths,
        set(bag_heights),
        priority_buffer,
    )
    bag_ids = sorted(bag_footprints)
    footprint_index = STRtree([bag_footprints[bag_id] for bag_id in bag_ids]) if bag_ids else None

    transformer = Transformer.from_crs("EPSG:4326", CONTEXT_CRS, always_xy=True)
    collected: dict[str, list[dict[str, Any]]] = {name: [] for name in LAYER_NAMES}
    rejected_geometry_count: dict[str, int] = defaultdict(int)
    clipped_geometry_count: dict[str, int] = defaultdict(int)
    height_source_counts: dict[str, int] = defaultdict(int)

    class Extractor(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.factory = osmium.geom.WKBFactory()

        def area(self, area_obj):
            tags = {str(tag.k): str(tag.v) for tag in area_obj.tags}
            layer = _classify_area(tags)
            if layer is None:
                return
            try:
                source_geometry = from_wkb(self.factory.create_multipolygon(area_obj))
                source_geometry = _project_geometry(source_geometry, transformer)
                if not source_geometry.is_valid:
                    rejected_geometry_count[layer] += 1
                    return
                if not source_geometry.intersects(context_buffer):
                    return
                clipped = source_geometry.intersection(context_buffer)
                display_geometry = _polygonal_only(clipped)
            except Exception:  # noqa: BLE001 - invalid OSM geometry is counted and skipped.
                rejected_geometry_count[layer] += 1
                return
            if display_geometry is None or display_geometry.is_empty or not display_geometry.is_valid:
                rejected_geometry_count[layer] += 1
                return
            if not source_geometry.equals(display_geometry):
                clipped_geometry_count[layer] += 1
            from_way = bool(area_obj.from_way())
            osm_type = "way" if from_way else "relation"
            source_id = str(area_obj.orig_id())
            if layer == "buildings":
                properties = _make_building_properties(
                    tags,
                    source_geometry,
                    priority_buffer=priority_buffer,
                    bag_heights=bag_heights,
                    footprint_index=footprint_index,
                    bag_ids=bag_ids,
                    bag_footprints=bag_footprints,
                    osm_data_version=source_data_version,
                )
                height_source_counts[properties["height_source"]] += 1
            else:
                properties = {key: tags[key] for key in ("natural", "waterway", "water", "landuse", "leisure", "name", "surface") if key in tags}
                properties["osm_tags"] = dict(tags)
            properties.update({
                "osm_type": osm_type,
                "osm_id": source_id,
                "source": "OpenStreetMap",
                "license": OSM_LICENSE,
                "bounds_m": [float(value) for value in display_geometry.bounds],
                "inside_study_area": bool(source_geometry.representative_point().within(study_area)),
                "clipped_to_context": not source_geometry.equals(display_geometry),
            })
            collected[layer].append({
                "type": "Feature",
                "id": f"{osm_type}/{source_id}",
                "properties": properties,
                "geometry": mapping(display_geometry),
            })

        def way(self, way_obj):
            tags = {str(tag.k): str(tag.v) for tag in way_obj.tags}
            highway = tags.get("highway")
            if not highway or tags.get("area") == "yes":
                return
            try:
                source_geometry = from_wkb(self.factory.create_linestring(way_obj))
                source_geometry = _project_geometry(source_geometry, transformer)
                if not isinstance(source_geometry, LineString) or source_geometry.is_empty or not source_geometry.is_valid:
                    rejected_geometry_count["roads"] += 1
                    return
                if not source_geometry.intersects(context_buffer):
                    return
                clipped = source_geometry.intersection(context_buffer)
                display_geometry = _linear_only(clipped)
            except Exception:  # noqa: BLE001 - ways with unresolved nodes are counted and skipped.
                rejected_geometry_count["roads"] += 1
                return
            if display_geometry is None or display_geometry.is_empty:
                rejected_geometry_count["roads"] += 1
                return
            source_id = str(way_obj.id)
            collected["roads"].append({
                "type": "Feature",
                "id": f"way/{source_id}",
                "properties": {
                    "osm_type": "way",
                    "osm_id": source_id,
                    "highway": highway,
                    "bridge": tags.get("bridge"),
                    "tunnel": tags.get("tunnel"),
                    "layer": tags.get("layer"),
                    "name": tags.get("name"),
                    "surface": tags.get("surface"),
                    "osm_data_version": source_data_version,
                    "osm_tags": dict(tags),
                    "source": "OpenStreetMap",
                    "license": OSM_LICENSE,
                    "bounds_m": [float(value) for value in display_geometry.bounds],
                    "clipped_to_context": not source_geometry.equals(display_geometry),
                },
                "geometry": mapping(display_geometry),
            })
            if not source_geometry.equals(display_geometry):
                clipped_geometry_count["roads"] += 1

    handler = Extractor()
    try:
        handler.apply_file(str(pbf), locations=True, idx="flex_mem")
    except Exception as exc:  # noqa: BLE001 - turn file/tool errors into a stable extraction failure.
        raise ContextDataError(f"offline OSM extraction failed for {pbf.name}: {type(exc).__name__}") from exc

    out.mkdir(parents=True, exist_ok=False)
    (out / "study-area-v5.geojson").write_bytes(boundary_path.read_bytes())
    layer_files: dict[str, dict[str, Any]] = {}
    for layer in LAYER_NAMES:
        features = sorted(collected[layer], key=lambda item: item["id"])
        artifact = out / f"{layer}.geojson"
        artifact.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        layer_files[layer] = {
            "file": artifact.name,
            "sha256": sha256_file(artifact),
            "size_bytes": artifact.stat().st_size,
            "feature_count": len(features),
        }

    extraction_id = extraction_id or datetime.now(timezone.utc).strftime("context-%Y%m%dT%H%M%SZ")
    manifest: dict[str, Any] = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "extraction_id": extraction_id,
        "run_directory": out.name,
        "project_id": project_id,
        "study_area_id": study_area_id,
        "study_area_version": study_area_version,
        "study_area_geometry_sha256": study_hash,
        "study_area_artifact_sha256": study_artifact_hash,
        "study_area_file": "study-area-v5.geojson",
        "study_area_file_size_bytes": len(boundary_path.read_bytes()),
        "crs": CONTEXT_CRS,
        "units": CONTEXT_UNITS,
        "vertical_reference": "not applicable to 2D OSM context; 3D BAG height_above_ground_m is a vertical difference in metres",
        "context_distance_m": float(distance),
        "selection_query": {
            "polygon_layers": [
                "building=* excluding building=no,false,0",
                "natural=water",
                "waterway in " + ",".join(sorted(WATERWAY_SURFACES)),
                "landuse in " + ",".join(sorted(GREEN_LANDUSE)),
                "leisure in " + ",".join(sorted(GREEN_LEISURE)),
            ],
            "road_lines": "way with highway=* and area!=yes",
            "clip": "intersection with a round 2D buffer of the exact StudyArea geometry in EPSG:28992",
        },
        "context_buffer_area_m2": float(context_buffer.area),
        "context_buffer_bounds_m": [float(value) for value in context_buffer.bounds],
        "context_buffer_geometry_sha256": hashlib.sha256(context_buffer.normalize().wkb).hexdigest(),
        "feature_counts": {layer: len(collected[layer]) for layer in LAYER_NAMES},
        "layer_files": layer_files,
        "rejected_geometry_counts": {layer: int(rejected_geometry_count.get(layer, 0)) for layer in LAYER_NAMES},
        "clipped_geometry_counts": {layer: int(clipped_geometry_count.get(layer, 0)) for layer in LAYER_NAMES},
        "source": "OpenStreetMap",
        "source_file": pbf.name,
        "source_file_size_bytes": pbf.stat().st_size,
        "source_pbf_sha256": sha256_file(pbf),
        "source_data_version": source_data_version,
        "source_format": "OSM PBF" if pbf.suffix == ".pbf" else "OSM XML fixture",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "license": OSM_LICENSE,
        "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "attribution": OSM_ATTRIBUTION,
        "extraction_tool": "pyosmium",
        "extraction_tool_version": importlib.metadata.version("osmium"),
        "projection_tool": "pyproj",
        "projection_tool_version": importlib.metadata.version("pyproj"),
        "clipping_tool": "Shapely",
        "clipping_tool_version": importlib.metadata.version("shapely"),
        "height_policy": {
            "priority_distance_m": priority_distance,
            "3dbag_priority": "3D BAG height_above_ground_m from the height table, joined by ref:bag or a unique pand-footprint representative-point match with at least 0.5 overlap of the smaller footprint",
            "osm_height": "OSM height tag parsed as metres; explicit feet are converted using 0.3048 m/ft",
            "osm_levels": "OSM building:levels is displayed as levels × 3.0 m/storey under the versioned display-only assumption; this is not an analysis measurement",
            "untagged": "footprint only; no height is fabricated",
            "level_display_policy": LEVEL_DISPLAY_POLICY,
            "level_display_height_m_per_storey": LEVEL_DISPLAY_HEIGHT_M,
            "height_source_counts": {source: int(height_source_counts.get(source, 0)) for source in ("3DBAG", "OSM_HEIGHT", "OSM_BUILDING_LEVELS_DISPLAY_ASSUMPTION", "FOOTPRINT_ONLY")},
        },
        "3dbag": {
            "used": bool(bag_document),
            "data_version": bag_document.get("data_version") if bag_document else None,
            "license": bag_document.get("license") if bag_document else None,
            "attribution": bag_document.get("attribution") if bag_document else None,
            "height_table_sha256": bag_table_hash,
            "height_table_record_count": len(bag_document.get("records", [])) if bag_document else 0,
            "tile_files": bag_tile_metadata,
            "matched_building_count": int(height_source_counts.get("3DBAG", 0)),
        },
        "data_gaps": [
            "OSM coverage and tag completeness depend on contributor mapping; omitted features and missing tags remain unknown.",
            "3D BAG heights are shown only where an available height record could be joined within the exact StudyArea 500 m buffer.",
            "building:levels extrusion is a display-only assumption and is not a measured building height.",
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def preview_design_area_intersection(candidate_geometry: Mapping[str, Any], study_area_geometry: Mapping[str, Any]) -> dict[str, Any]:
    """Return an inspectable Polygon intersection without saving any project state."""
    try:
        candidate = shape(candidate_geometry)
        study_area = shape(study_area_geometry)
    except Exception as exc:  # noqa: BLE001 - normalize geometry parser failures.
        raise ContextDataError("candidate or active StudyArea geometry is invalid") from exc
    if not isinstance(candidate, _POLYGON_TYPES) or candidate.is_empty or not candidate.is_valid or candidate.area <= 0:
        raise ContextDataError("candidate design area must be a valid positive-area Polygon or MultiPolygon")
    if not isinstance(study_area, _POLYGON_TYPES) or study_area.is_empty or not study_area.is_valid or study_area.area <= 0:
        raise ContextDataError("active StudyArea must be a valid positive-area Polygon or MultiPolygon")
    if any(not math.isfinite(float(value)) for value in (*candidate.bounds, *study_area.bounds)):
        raise ContextDataError("candidate and StudyArea coordinates must be finite EPSG:28992 metres")

    intersection = candidate.intersection(study_area)
    parts = _polygon_parts(intersection)
    if not parts:
        return {
            "status": "EMPTY",
            "clipped": True,
            "area_m2": 0.0,
            "component_count": 0,
            "geometry": None,
            "horizontal_crs": CONTEXT_CRS,
            "units": CONTEXT_UNITS,
        }
    result_geometry = parts[0] if len(parts) == 1 else MultiPolygon(parts)
    if len(parts) > 1:
        status = "MULTIPLE_COMPONENTS"
    elif candidate.equals(result_geometry):
        status = "UNCHANGED"
    else:
        status = "CLIPPED"
    return {
        "status": status,
        "clipped": not candidate.equals(result_geometry),
        "area_m2": float(result_geometry.area),
        "component_count": len(parts),
        "geometry": mapping(result_geometry),
        "horizontal_crs": CONTEXT_CRS,
        "units": CONTEXT_UNITS,
    }


class ContextRepository:
    """Validate pinned context artifacts and expose simplified read-only layers."""

    def __init__(self, *, data_root: str | Path, manifest_path: str | Path):
        self.data_root = Path(data_root)
        self.manifest_path = Path(manifest_path)
        self._lock = RLock()
        self._loaded_key: tuple[int, int, int, int] | None = None
        self._manifest: dict[str, Any] | None = None
        self._layers: dict[str, dict[str, Any]] | None = None
        self._study_area: dict[str, Any] | None = None

    def _load(self) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
        with self._lock:
            try:
                expected_stat = self.manifest_path.stat()
                data_manifest_path = self.data_root / "manifest.json"
                data_stat = data_manifest_path.stat()
            except OSError as exc:
                raise ContextDataError("pinned or external context manifest is unavailable") from exc
            key = (expected_stat.st_mtime_ns, expected_stat.st_size, data_stat.st_mtime_ns, data_stat.st_size)
            if self._loaded_key == key and self._manifest is not None and self._layers is not None and self._study_area is not None:
                return self._manifest, self._layers, self._study_area
            expected_bytes = self.manifest_path.read_bytes()
            data_bytes = data_manifest_path.read_bytes()
            if hashlib.sha256(expected_bytes).digest() != hashlib.sha256(data_bytes).digest():
                raise ContextDataError("external context manifest differs from the committed provenance manifest")
            try:
                manifest = json.loads(expected_bytes)
            except json.JSONDecodeError as exc:
                raise ContextDataError("context manifest is not valid JSON") from exc
            if manifest.get("schema_version") != CONTEXT_SCHEMA_VERSION:
                raise ContextDataError("unsupported surrounding-context manifest schema")
            run_name = manifest.get("run_directory")
            if not isinstance(run_name, str) or not run_name or Path(run_name).name != run_name:
                raise ContextDataError("context manifest run directory is invalid")
            run_dir = self.data_root / run_name
            layer_files = manifest.get("layer_files")
            if not isinstance(layer_files, dict):
                raise ContextDataError("context manifest has no typed layer inventory")
            layers: dict[str, dict[str, Any]] = {}
            for layer_name in LAYER_NAMES:
                entry = layer_files.get(layer_name)
                if not isinstance(entry, dict):
                    raise ContextDataError(f"context manifest is missing the {layer_name} layer")
                filename = entry.get("file")
                if not isinstance(filename, str) or Path(filename).name != filename:
                    raise ContextDataError(f"context layer path for {layer_name} is invalid")
                layer_path = run_dir / filename
                if sha256_file(layer_path) != entry.get("sha256"):
                    raise ContextDataError(f"context layer hash mismatch: {layer_name}")
                try:
                    collection = json.loads(layer_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ContextDataError(f"context layer {layer_name} could not be read") from exc
                if collection.get("type") != "FeatureCollection" or not isinstance(collection.get("features"), list):
                    raise ContextDataError(f"context layer {layer_name} is not a FeatureCollection")
                if len(collection["features"]) != entry.get("feature_count"):
                    raise ContextDataError(f"context layer feature count mismatch: {layer_name}")
                layers[layer_name] = collection
            study_file = manifest.get("study_area_file", "study-area-v5.geojson")
            if not isinstance(study_file, str) or Path(study_file).name != study_file:
                raise ContextDataError("context manifest StudyArea path is invalid")
            boundary_path = run_dir / study_file
            if sha256_file(boundary_path) != manifest.get("study_area_artifact_sha256"):
                raise ContextDataError("context StudyArea artifact hash mismatch")
            _, raw_geometry, study_area = _read_polygonal_geojson(boundary_path)
            if canonical_geometry_hash(raw_geometry) != manifest.get("study_area_geometry_sha256"):
                raise ContextDataError("context StudyArea geometry hash mismatch")
            if manifest.get("crs") != CONTEXT_CRS or manifest.get("units") != CONTEXT_UNITS:
                raise ContextDataError("context manifest CRS or units are unsupported")
            self._loaded_key = key
            self._manifest = manifest
            self._layers = layers
            self._study_area = mapping(study_area)
            return manifest, layers, self._study_area

    def manifest(self) -> dict[str, Any]:
        manifest, _, _ = self._load()
        return manifest

    def get_context(self, *, tolerance_m: float = 0.0) -> dict[str, Any]:
        tolerance = _finite_number(tolerance_m)
        if tolerance is None or tolerance < 0 or tolerance > 50:
            raise ContextDataError("tolerance_m must be between 0 and 50 metres")
        manifest, source_layers, _ = self._load()
        response_layers: dict[str, dict[str, Any]] = {}
        for layer_name in LAYER_NAMES:
            response_features: list[dict[str, Any]] = []
            for feature in source_layers[layer_name]["features"]:
                geometry = _feature_geometry(feature)
                if tolerance > 0:
                    geometry = geometry.simplify(tolerance, preserve_topology=True)
                    if geometry.is_empty:
                        continue
                response_features.append({
                    "type": "Feature",
                    "id": feature.get("id"),
                    "properties": dict(feature.get("properties") or {}),
                    "geometry": mapping(geometry),
                })
            response_layers[layer_name] = {"type": "FeatureCollection", "features": response_features}
        metadata = {
            "schema_version": manifest["schema_version"],
            "project_id": manifest.get("project_id", PROJECT_ID),
            "study_area_id": manifest["study_area_id"],
            "study_area_version": manifest["study_area_version"],
            "study_area_geometry_sha256": manifest["study_area_geometry_sha256"],
            "crs": manifest["crs"],
            "units": manifest["units"],
            "context_distance_m": manifest["context_distance_m"],
            "source": manifest["source"],
            "source_data_version": manifest["source_data_version"],
            "source_pbf_sha256": manifest["source_pbf_sha256"],
            "license": manifest["license"],
            "attribution": manifest["attribution"],
            "tolerance_m": tolerance,
            "height_policy": manifest.get("height_policy"),
            "3dbag": manifest.get("3dbag"),
        }
        return {"metadata": metadata, "layers": response_layers}

    def preview_design_area(self, candidate_geometry: Mapping[str, Any]) -> dict[str, Any]:
        _, _, study_area = self._load()
        return preview_design_area_intersection(candidate_geometry, study_area)


def _write_data_manifest(data_root: Path, manifest: Mapping[str, Any], reference_path: Path) -> None:
    """Write identical, small manifests beside external artifacts and in Git."""
    encoded = (json.dumps(dict(manifest), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "manifest.json").write_bytes(encoded)
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.write_bytes(encoded)


__all__ = [
    "CONTEXT_CRS",
    "CONTEXT_SCHEMA_VERSION",
    "ContextDataError",
    "ContextRepository",
    "extract_osm_context",
    "parse_building_levels",
    "parse_osm_height_m",
    "preview_design_area_intersection",
]
