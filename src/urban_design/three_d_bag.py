"""Offline 3D BAG tile extraction and DatasetSnapshot registration support.

The extractor reads the immutable official tile responses only. It never makes
network requests or accesses project state. Roof P70 values are stored per roof
part by 3D BAG, so this module selects the maximum roof-part P70 for each BAG
building and records that derivation explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import struct
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse
import zlib

from shapely import from_wkb, normalize as normalize_geometry, to_wkb
from shapely.geometry import shape

from urban_design.models import Artifact, DatasetSnapshot


THREE_DBAG_LICENSE = "CC BY 4.0"
THREE_DBAG_ATTRIBUTION = "© 3DBAG by tudelft3d and 3DGI"
THREE_DBAG_LICENSE_URL = "https://docs.3dbag.nl/en/copyright/"
THREE_DBAG_PUBLISHER = "3D geoinformation research group, TU Delft and 3DGI"
THREE_DBAG_SCHEMA_VERSION = "3dbag-height-table-v1"
THREE_DBAG_MANIFEST_VERSION = "3dbag-height-source-manifest-v1"
THREE_DBAG_EXTRACTOR_VERSION = "3dbag-height-extractor-v1"
THREE_DBAG_ROOF_P70_FIELD = "b3_h_70p"
THREE_DBAG_GROUND_FIELD = "b3_h_maaiveld"
THREE_DBAG_BAG_ID_FIELD = "identificatie"
THREE_DBAG_ROOF_P70_AGGREGATION = "maximum-roofpart-b3_h_70p"
THREE_DBAG_AGGREGATION_VERSION = "3dbag-roof-p70-aggregation-v1"
THREE_DBAG_VERTICAL_REFERENCE = "NAP height (EPSG:5709); compound tile CRS EPSG:7415"
THREE_DBAG_GPKG_SRS_ID = 7415
THREE_DBAG_MAX_UNCOMPRESSED_TILE_BYTES = 200_000_000
_BAG_PREFIX = "NL.IMBAG.Pand."
_BAG_ID_RE = re.compile(r"^\d{16}$")
_BAG_IDENTIFICATIE_RE = re.compile(r"^NL\.IMBAG\.Pand\.\d{16}$")
_SHA256_RE = re.compile(r"^sha256:([0-9a-f]{64})$")


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _validated_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must use sha256:<64 lowercase hexadecimal characters>")
    return value


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_bag_identificatie(value: str) -> str:
    """Return the official BAG identifier from either its full form or 16 digits.

    No partial, fuzzy, numeric, or truncated identifiers are accepted.
    """

    text = _required_text(value, "bag_identificatie")
    if _BAG_ID_RE.fullmatch(text):
        return _BAG_PREFIX + text
    if _BAG_IDENTIFICATIE_RE.fullmatch(text):
        return text
    raise ValueError("bag_identificatie must be 16 digits or NL.IMBAG.Pand.<16 digits>")


@dataclass(frozen=True)
class TileSource:
    tile_id: str
    path: Path
    sha256: str
    url: str

    def __post_init__(self) -> None:
        _required_text(self.tile_id, "tile_id")
        object.__setattr__(self, "path", Path(self.path))
        _validated_sha256(self.sha256, "tile sha256")
        parsed = urlparse(_required_text(self.url, "tile url"))
        if parsed.scheme != "https" or parsed.hostname != "data.3dbag.nl":
            raise ValueError("tile URL must use the official https://data.3dbag.nl service")


@dataclass(frozen=True)
class BuildingHeightRecord:
    bag_identificatie: str
    roof_p70_height_m: float | None
    ground_height_m: float | None
    source_version: str
    roof_part_count: int
    source_tile_ids: tuple[str, ...]
    roof_p70_aggregation: str
    status: str
    unavailable_reason: str | None

    def __post_init__(self) -> None:
        canonical = normalize_bag_identificatie(self.bag_identificatie)
        object.__setattr__(self, "bag_identificatie", canonical)
        _required_text(self.source_version, "source_version")
        if isinstance(self.roof_part_count, bool) or self.roof_part_count < 0:
            raise ValueError("roof_part_count must be a non-negative integer")
        if not isinstance(self.roof_part_count, int):
            raise ValueError("roof_part_count must be a non-negative integer")
        for field_name in ("roof_p70_height_m", "ground_height_m"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{field_name} must be a finite height in metres or null")
            object.__setattr__(self, field_name, float(value))
        object.__setattr__(self, "source_tile_ids", tuple(sorted(set(self.source_tile_ids))))
        _required_text(self.roof_p70_aggregation, "roof_p70_aggregation")
        if self.status not in {"AVAILABLE", "UNAVAILABLE"}:
            raise ValueError("height record status must be AVAILABLE or UNAVAILABLE")
        usable = (
            self.roof_p70_height_m is not None
            and self.ground_height_m is not None
            and self.roof_p70_height_m >= self.ground_height_m
        )
        if self.status == "AVAILABLE" and not usable:
            raise ValueError("AVAILABLE height record requires a valid roof-ground pair")
        if self.status == "UNAVAILABLE" and not self.unavailable_reason:
            raise ValueError("UNAVAILABLE height record requires an explicit reason")
        if self.status == "AVAILABLE" and self.unavailable_reason is not None:
            raise ValueError("AVAILABLE height record cannot have an unavailable reason")

    @property
    def height_above_ground_m(self) -> float | None:
        if (
            self.roof_p70_height_m is None
            or self.ground_height_m is None
            or self.roof_p70_height_m < self.ground_height_m
        ):
            return None
        return self.roof_p70_height_m - self.ground_height_m


@dataclass(frozen=True)
class BuildingHeightTable:
    data_version: str
    license: str
    attribution: str
    study_area_id: str
    study_area_version: str
    study_area_geometry_sha256: str
    study_area_artifact_sha256: str
    study_area_horizontal_crs: str
    vertical_reference: str
    buffer_distance_m: float
    buffer_geometry_sha256: str
    buffer_bbox_m: tuple[float, float, float, float]
    buffered_area_m2: float
    records: Mapping[str, BuildingHeightRecord]
    source_tiles: tuple[Mapping[str, Any], ...] = ()
    schema_version: str = THREE_DBAG_SCHEMA_VERSION
    bag_identificatie_field: str = THREE_DBAG_BAG_ID_FIELD
    roof_p70_field: str = THREE_DBAG_ROOF_P70_FIELD
    ground_height_field: str = THREE_DBAG_GROUND_FIELD
    roof_p70_aggregation: str = THREE_DBAG_ROOF_P70_AGGREGATION
    aggregation_method_version: str = THREE_DBAG_AGGREGATION_VERSION
    height_unit: str = "m"
    selection_predicate: str = (
        "3D BAG pand footprint intersects the exact StudyArea polygon buffered by buffer_distance_m"
    )

    def __post_init__(self) -> None:
        for field_name in (
            "data_version",
            "license",
            "attribution",
            "study_area_id",
            "study_area_version",
            "vertical_reference",
        ):
            _required_text(getattr(self, field_name), field_name)
        _validated_sha256(self.study_area_geometry_sha256, "study_area_geometry_sha256")
        _validated_sha256(self.study_area_artifact_sha256, "study_area_artifact_sha256")
        _validated_sha256(self.buffer_geometry_sha256, "buffer_geometry_sha256")
        if self.study_area_horizontal_crs != "EPSG:28992":
            raise ValueError("study_area_horizontal_crs must be EPSG:28992")
        if self.vertical_reference != THREE_DBAG_VERTICAL_REFERENCE:
            raise ValueError(f"vertical_reference must be {THREE_DBAG_VERTICAL_REFERENCE}")
        if not math.isfinite(self.buffer_distance_m) or self.buffer_distance_m <= 0:
            raise ValueError("buffer_distance_m must be a positive finite distance in metres")
        if len(self.buffer_bbox_m) != 4 or not all(math.isfinite(float(v)) for v in self.buffer_bbox_m):
            raise ValueError("buffer_bbox_m must contain four finite projected coordinates")
        if not math.isfinite(self.buffered_area_m2) or self.buffered_area_m2 <= 0:
            raise ValueError("buffered_area_m2 must be a positive finite area in square metres")
        if self.schema_version != THREE_DBAG_SCHEMA_VERSION:
            raise ValueError(f"unsupported height-table schema {self.schema_version!r}")
        normalized: dict[str, BuildingHeightRecord] = {}
        for key, record in self.records.items():
            canonical = normalize_bag_identificatie(key)
            if canonical != record.bag_identificatie:
                raise ValueError("height-table key does not match record BAG identificatie")
            if canonical in normalized:
                raise ValueError(f"duplicate BAG identificatie in height table: {canonical}")
            if record.source_version != self.data_version:
                raise ValueError("height record source_version does not match table data_version")
            normalized[canonical] = record
        object.__setattr__(self, "records", normalized)
        object.__setattr__(self, "buffer_bbox_m", tuple(float(v) for v in self.buffer_bbox_m))
        object.__setattr__(self, "source_tiles", tuple(dict(item) for item in self.source_tiles))

    def lookup(self, bag_id: str | None) -> BuildingHeightRecord | None:
        if bag_id is None:
            return None
        try:
            canonical = normalize_bag_identificatie(bag_id)
        except ValueError:
            return None
        return self.records.get(canonical)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "data_version": self.data_version,
            "license": self.license,
            "license_url": THREE_DBAG_LICENSE_URL,
            "publisher": THREE_DBAG_PUBLISHER,
            "attribution": self.attribution,
            "study_area_id": self.study_area_id,
            "study_area_version": self.study_area_version,
            "study_area_geometry_sha256": self.study_area_geometry_sha256,
            "study_area_artifact_sha256": self.study_area_artifact_sha256,
            "study_area_horizontal_crs": self.study_area_horizontal_crs,
            "vertical_reference": self.vertical_reference,
            "buffer_distance_m": self.buffer_distance_m,
            "buffer_geometry_sha256": self.buffer_geometry_sha256,
            "buffer_bbox_m": list(self.buffer_bbox_m),
            "buffered_area_m2": self.buffered_area_m2,
            "bag_identificatie_field": self.bag_identificatie_field,
            "roof_p70_field": self.roof_p70_field,
            "ground_height_field": self.ground_height_field,
            "height_unit": self.height_unit,
            "roof_p70_aggregation": self.roof_p70_aggregation,
            "aggregation_method_version": self.aggregation_method_version,
            "selection_predicate": self.selection_predicate,
            "source_tiles": [dict(item) for item in self.source_tiles],
            "records": [
                {
                    "bag_identificatie": record.bag_identificatie,
                    "roof_p70_height_m": record.roof_p70_height_m,
                    "ground_height_m": record.ground_height_m,
                    "height_above_ground_m": record.height_above_ground_m,
                    "source_version": record.source_version,
                    "roof_part_count": record.roof_part_count,
                    "source_tile_ids": list(record.source_tile_ids),
                    "roof_p70_aggregation": record.roof_p70_aggregation,
                    "status": record.status,
                    "unavailable_reason": record.unavailable_reason,
                }
                for _, record in sorted(self.records.items())
            ],
        }


def _height_table_from_dict(data: Mapping[str, Any]) -> BuildingHeightTable:
    if data.get("schema_version") != THREE_DBAG_SCHEMA_VERSION:
        raise ValueError("unsupported 3D BAG height-table schema_version")
    records: dict[str, BuildingHeightRecord] = {}
    raw_records = data.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("height-table records must be a list")
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            raise ValueError("height-table record must be an object")
        bag_id = normalize_bag_identificatie(raw.get("bag_identificatie"))
        if bag_id in records:
            raise ValueError(f"duplicate BAG identificatie in height table: {bag_id}")
        record = BuildingHeightRecord(
            bag_identificatie=bag_id,
            roof_p70_height_m=raw.get("roof_p70_height_m"),
            ground_height_m=raw.get("ground_height_m"),
            source_version=raw.get("source_version") or data.get("data_version"),
            roof_part_count=raw.get("roof_part_count", 0),
            source_tile_ids=tuple(raw.get("source_tile_ids") or ()),
            roof_p70_aggregation=raw.get("roof_p70_aggregation") or data.get("roof_p70_aggregation"),
            status=raw.get("status"),
            unavailable_reason=raw.get("unavailable_reason"),
        )
        declared_height = raw.get("height_above_ground_m")
        if declared_height != record.height_above_ground_m:
            raise ValueError(f"height-above-ground value does not reconcile for {bag_id}")
        records[bag_id] = record
    return BuildingHeightTable(
        data_version=data.get("data_version"),
        license=data.get("license"),
        attribution=data.get("attribution"),
        study_area_id=data.get("study_area_id"),
        study_area_version=data.get("study_area_version"),
        study_area_geometry_sha256=data.get("study_area_geometry_sha256"),
        study_area_artifact_sha256=data.get("study_area_artifact_sha256"),
        study_area_horizontal_crs=data.get("study_area_horizontal_crs"),
        vertical_reference=data.get("vertical_reference"),
        buffer_distance_m=data.get("buffer_distance_m"),
        buffer_geometry_sha256=data.get("buffer_geometry_sha256"),
        buffer_bbox_m=tuple(data.get("buffer_bbox_m") or ()),
        buffered_area_m2=data.get("buffered_area_m2"),
        records=records,
        source_tiles=tuple(data.get("source_tiles") or ()),
        schema_version=data.get("schema_version"),
        bag_identificatie_field=data.get("bag_identificatie_field", THREE_DBAG_BAG_ID_FIELD),
        roof_p70_field=data.get("roof_p70_field", THREE_DBAG_ROOF_P70_FIELD),
        ground_height_field=data.get("ground_height_field", THREE_DBAG_GROUND_FIELD),
        roof_p70_aggregation=data.get("roof_p70_aggregation", THREE_DBAG_ROOF_P70_AGGREGATION),
        aggregation_method_version=data.get(
            "aggregation_method_version", THREE_DBAG_AGGREGATION_VERSION
        ),
        height_unit=data.get("height_unit", "m"),
        selection_predicate=data.get("selection_predicate") or "",
    )


def load_3dbag_height_table(path: str | Path) -> BuildingHeightTable:
    """Load and validate a frozen 3D BAG height table."""

    source_path = Path(path)
    try:
        data = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read 3D BAG height table: {source_path}") from exc
    if not isinstance(data, Mapping):
        raise ValueError("3D BAG height table must be a JSON object")
    return _height_table_from_dict(data)


def _decode_gpkg_geometry(blob: bytes) -> tuple[int, Any]:
    if not isinstance(blob, (bytes, bytearray, memoryview)) or len(blob) < 8 or blob[:2] != b"GP":
        raise ValueError("GeoPackage geometry has an invalid binary header")
    data = bytes(blob)
    if data[2] != 0:
        raise ValueError(f"unsupported GeoPackage geometry header version: {data[2]}")
    flags = data[3]
    byte_order = "<" if flags & 1 else ">"
    srs_id = struct.unpack(f"{byte_order}i", data[4:8])[0]
    envelope_indicator = (flags >> 1) & 0b111
    envelope_bytes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope_indicator)
    if envelope_bytes is None:
        raise ValueError("GeoPackage geometry has an invalid envelope indicator")
    if flags & 0x10:
        raise ValueError("empty GeoPackage geometries cannot select a building footprint")
    offset = 8 + envelope_bytes
    if offset >= len(data):
        raise ValueError("GeoPackage geometry is truncated")
    try:
        geometry = from_wkb(data[offset:])
    except Exception as exc:
        raise ValueError("GeoPackage geometry WKB could not be decoded") from exc
    return srs_id, geometry


def _finite_optional_height(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite metre height or null")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite metre height or null")
    return number


def _open_tile_database(source: TileSource) -> sqlite3.Connection:
    if not source.path.is_file():
        raise FileNotFoundError(source.path)
    actual_hash = _file_sha256(source.path)
    if actual_hash != source.sha256:
        raise ValueError(f"tile SHA-256 mismatch for tile {source.tile_id}")
    try:
        raw = gzip.decompress(source.path.read_bytes())
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError(f"tile gzip response is invalid for tile {source.tile_id}") from exc
    if len(raw) > THREE_DBAG_MAX_UNCOMPRESSED_TILE_BYTES:
        raise ValueError(f"uncompressed tile exceeds 200 MB for tile {source.tile_id}")
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(raw)
        connection.execute("PRAGMA query_only=ON")
        contents = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT table_name, data_type, srs_id FROM gpkg_contents"
            )
        }
        for layer in ("pand", "lod22_2d"):
            if contents.get(layer) != ("features", THREE_DBAG_GPKG_SRS_ID):
                raise ValueError(
                    f"tile {source.tile_id} layer {layer} must be features in EPSG:7415"
                )
        pand_columns = {row[1] for row in connection.execute('PRAGMA table_info("pand")')}
        roof_columns = {row[1] for row in connection.execute('PRAGMA table_info("lod22_2d")')}
        if not {"fid", "geom", THREE_DBAG_BAG_ID_FIELD, THREE_DBAG_GROUND_FIELD}.issubset(pand_columns):
            raise ValueError(f"tile {source.tile_id} pand layer is missing required fields")
        if not {
            "fid",
            THREE_DBAG_BAG_ID_FIELD,
            THREE_DBAG_ROOF_P70_FIELD,
            "b3_dd_id",
            "b3_pand_deel_id",
        }.issubset(roof_columns):
            raise ValueError(f"tile {source.tile_id} lod22_2d layer is missing required fields")
    except Exception:
        connection.close()
        raise
    return connection


def _geometry_intersects_buffer(geometry: Any, buffer_geometry: Any, bbox: tuple[float, ...]) -> bool:
    if geometry.is_empty:
        return False
    min_x, min_y, max_x, max_y = geometry.bounds
    buffer_min_x, buffer_min_y, buffer_max_x, buffer_max_y = bbox
    if max_x < buffer_min_x or min_x > buffer_max_x or max_y < buffer_min_y or min_y > buffer_max_y:
        return False
    if not geometry.is_valid:
        raise ValueError("candidate 3D BAG pand footprint has invalid geometry")
    return bool(geometry.intersects(buffer_geometry))


def _canonical_geometry_hash(geometry: Any) -> bytes:
    return to_wkb(normalize_geometry(geometry), byte_order=1, output_dimension=2)


def extract_3dbag_height_table(
    *,
    study_area_geojson_path: str | Path,
    study_area_artifact_sha256: str,
    study_area_geometry_sha256: str,
    study_area_id: str,
    study_area_version: str,
    study_area_crs: str,
    tile_sources: Sequence[TileSource],
    data_version: str,
    buffer_distance_m: float,
    output_path: str | Path,
) -> BuildingHeightTable:
    """Build a BAG-keyed height table from frozen, locally stored tile responses.

    Tile packages are verified by exact response-byte SHA-256 before they are
    parsed. Footprints are selected by exact intersection with the buffered
    StudyArea polygon; the tile query BBOX is only a download-size preflight.
    """

    if study_area_crs != "EPSG:28992":
        raise ValueError("StudyArea must be explicitly supplied in EPSG:28992")
    _validated_sha256(study_area_artifact_sha256, "study_area_artifact_sha256")
    _validated_sha256(study_area_geometry_sha256, "study_area_geometry_sha256")
    study_area_id = _required_text(study_area_id, "study_area_id")
    study_area_version = _required_text(study_area_version, "study_area_version")
    data_version = _required_text(data_version, "data_version")
    if isinstance(buffer_distance_m, bool) or not isinstance(buffer_distance_m, (int, float)):
        raise ValueError("buffer_distance_m must be a positive distance in metres")
    buffer_distance_m = float(buffer_distance_m)
    if not math.isfinite(buffer_distance_m) or buffer_distance_m <= 0:
        raise ValueError("buffer_distance_m must be a positive distance in metres")
    if not tile_sources:
        raise ValueError("at least one verified 3D BAG tile source is required")

    study_area_path = Path(study_area_geojson_path)
    if not study_area_path.is_file():
        raise FileNotFoundError(study_area_path)
    if _file_sha256(study_area_path) != study_area_artifact_sha256:
        raise ValueError("StudyArea artifact SHA-256 does not match its registered bytes")
    try:
        study_area_document = json.loads(study_area_path.read_text(encoding="utf-8"))
        geometry_document = (
            study_area_document.get("geometry")
            if study_area_document.get("type") == "Feature"
            else study_area_document
        )
        study_area_geometry = shape(geometry_document)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("StudyArea GeoJSON could not be parsed") from exc
    if study_area_geometry.is_empty or study_area_geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("StudyArea must be a non-empty Polygon or MultiPolygon")
    if not study_area_geometry.is_valid:
        raise ValueError("StudyArea polygon geometry is invalid")
    if not all(math.isfinite(float(value)) for value in study_area_geometry.bounds):
        raise ValueError("StudyArea polygon bounds contain non-finite coordinates")
    buffered_geometry = study_area_geometry.buffer(buffer_distance_m, quad_segs=16)
    if buffered_geometry.is_empty or not buffered_geometry.is_valid:
        raise ValueError("buffered StudyArea geometry is empty or invalid")
    buffer_bbox = tuple(float(value) for value in buffered_geometry.bounds)
    buffer_geometry_sha256 = "sha256:" + hashlib.sha256(
        _canonical_geometry_hash(buffered_geometry)
    ).hexdigest()

    selected: dict[str, dict[str, Any]] = {}
    for source in tile_sources:
        connection = _open_tile_database(source)
        try:
            rows = connection.execute(
                "SELECT fid, identificatie, b3_h_maaiveld, geom FROM pand ORDER BY fid"
            )
            for fid, raw_bag_id, raw_ground_height, raw_geometry in rows:
                bag_id = normalize_bag_identificatie(raw_bag_id)
                srs_id, footprint = _decode_gpkg_geometry(raw_geometry)
                if srs_id != THREE_DBAG_GPKG_SRS_ID:
                    raise ValueError(f"tile {source.tile_id} pand geometry is not EPSG:7415")
                if not _geometry_intersects_buffer(footprint, buffered_geometry, buffer_bbox):
                    continue
                ground_height = _finite_optional_height(raw_ground_height, THREE_DBAG_GROUND_FIELD)
                geometry_hash = _canonical_geometry_hash(footprint)
                current = selected.get(bag_id)
                if current is None:
                    selected[bag_id] = {
                        "ground_height_m": ground_height,
                        "geometry_hash": geometry_hash,
                        "geometry": footprint,
                        "tile_ids": {source.tile_id},
                    }
                else:
                    if (
                        current["ground_height_m"] != ground_height
                        or current["geometry_hash"] != geometry_hash
                    ):
                        raise ValueError(f"conflicting duplicate pand rows for {bag_id}")
                    current["tile_ids"].add(source.tile_id)
        finally:
            connection.close()

    roof_parts: dict[str, dict[tuple[Any, ...], tuple[float, str]]] = {
        bag_id: {} for bag_id in selected
    }
    roof_tile_ids: dict[str, set[str]] = {bag_id: set() for bag_id in selected}
    selected_ids = sorted(selected)
    for source in tile_sources:
        if not selected_ids:
            break
        connection = _open_tile_database(source)
        try:
            for start in range(0, len(selected_ids), 500):
                chunk = selected_ids[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""SELECT fid, identificatie, b3_h_70p, b3_dd_id, b3_pand_deel_id
                        FROM lod22_2d WHERE identificatie IN ({placeholders}) ORDER BY fid""",
                    chunk,
                )
                for fid, raw_bag_id, raw_height, dd_id, part_id in rows:
                    bag_id = normalize_bag_identificatie(raw_bag_id)
                    roof_height = _finite_optional_height(raw_height, THREE_DBAG_ROOF_P70_FIELD)
                    if roof_height is None:
                        continue
                    part_key = (
                        (part_id, dd_id)
                        if dd_id is not None
                        else ("fid", fid, roof_height)
                    )
                    existing = roof_parts[bag_id].get(part_key)
                    if existing is not None and existing[0] != roof_height:
                        raise ValueError(
                            f"conflicting roof P70 values for {bag_id} part {part_key!r}"
                        )
                    roof_parts[bag_id][part_key] = (roof_height, source.tile_id)
                    roof_tile_ids[bag_id].add(source.tile_id)
        finally:
            connection.close()

    records: dict[str, BuildingHeightRecord] = {}
    for bag_id in sorted(selected):
        selected_building = selected[bag_id]
        parts = roof_parts[bag_id]
        roof_height = max((value[0] for value in parts.values()), default=None)
        ground_height = selected_building["ground_height_m"]
        if roof_height is None:
            reason = "No matching finite b3_h_70p value in the 3D BAG lod22_2d layer."
        elif ground_height is None:
            reason = "No finite b3_h_maaiveld value in the 3D BAG pand layer."
        elif roof_height < ground_height:
            reason = "Selected roof P70 is below b3_h_maaiveld; height is invalid for extrusion or floors."
        else:
            reason = None
        status = "AVAILABLE" if reason is None else "UNAVAILABLE"
        tile_ids = selected_building["tile_ids"] | roof_tile_ids[bag_id]
        records[bag_id] = BuildingHeightRecord(
            bag_identificatie=bag_id,
            roof_p70_height_m=roof_height,
            ground_height_m=ground_height,
            source_version=data_version,
            roof_part_count=len(parts),
            source_tile_ids=tuple(tile_ids),
            roof_p70_aggregation=THREE_DBAG_ROOF_P70_AGGREGATION,
            status=status,
            unavailable_reason=reason,
        )

    source_tile_manifest = tuple(
        {
            "tile_id": source.tile_id,
            "url": source.url,
            "path": str(source.path.resolve()),
            "sha256": source.sha256,
            "size_bytes": source.path.stat().st_size,
        }
        for source in tile_sources
    )
    table = BuildingHeightTable(
        data_version=data_version,
        license=THREE_DBAG_LICENSE,
        attribution=THREE_DBAG_ATTRIBUTION,
        study_area_id=study_area_id,
        study_area_version=study_area_version,
        study_area_geometry_sha256=study_area_geometry_sha256,
        study_area_artifact_sha256=study_area_artifact_sha256,
        study_area_horizontal_crs=study_area_crs,
        vertical_reference=THREE_DBAG_VERTICAL_REFERENCE,
        buffer_distance_m=buffer_distance_m,
        buffer_geometry_sha256=buffer_geometry_sha256,
        buffer_bbox_m=buffer_bbox,
        buffered_area_m2=float(buffered_geometry.area),
        records=records,
        source_tiles=source_tile_manifest,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8") as stream:
            json.dump(table.to_dict(), stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite existing height table: {output}") from None
    return table


@dataclass(frozen=True)
class SnapshotRegistrationBundle:
    project_id: str
    manifest_sha256: str
    artifacts: tuple[Artifact, ...]
    dataset_snapshots: tuple[DatasetSnapshot, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "manifest_sha256": self.manifest_sha256,
            "artifacts": [item.model_dump(mode="json") for item in self.artifacts],
            "dataset_snapshots": [item.model_dump(mode="json") for item in self.dataset_snapshots],
        }


def build_snapshot_registration_bundle(manifest_path: str | Path) -> SnapshotRegistrationBundle:
    """Verify local hashes and build typed records; this function never writes a DB."""

    path = Path(manifest_path)
    manifest_bytes = path.read_bytes()
    manifest_sha256 = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != THREE_DBAG_MANIFEST_VERSION:
        raise ValueError("unsupported 3D BAG source manifest")
    project_id = _required_text(manifest.get("project_id"), "project_id")
    dataset = manifest.get("dataset")
    study_area = manifest.get("study_area")
    scope = manifest.get("scope")
    height_data = manifest.get("height_table")
    tile_data = manifest.get("tiles")
    if not all(isinstance(value, Mapping) for value in (dataset, study_area, scope, height_data)):
        raise ValueError("manifest dataset, study_area, scope, and height_table sections are required")
    if not isinstance(tile_data, list) or not tile_data:
        raise ValueError("manifest must contain one or more downloaded tiles")
    version = _required_text(dataset.get("version"), "dataset.version")
    license_name = _required_text(dataset.get("license"), "dataset.license")
    publisher = _required_text(dataset.get("publisher"), "dataset.publisher")
    attribution = _required_text(dataset.get("attribution"), "dataset.attribution")
    if license_name != THREE_DBAG_LICENSE or attribution != THREE_DBAG_ATTRIBUTION:
        raise ValueError("manifest license or attribution does not match the official 3D BAG terms")
    if dataset.get("license_url") != THREE_DBAG_LICENSE_URL:
        raise ValueError("manifest license_url does not match the official 3D BAG copyright page")

    height_path = Path(_required_text(height_data.get("path"), "height_table.path"))
    height_hash = _validated_sha256(height_data.get("sha256"), "height_table.sha256")
    if not height_path.is_file() or _file_sha256(height_path) != height_hash:
        raise ValueError("derived height-table SHA-256 does not match its local bytes")
    if height_path.stat().st_size != height_data.get("size_bytes"):
        raise ValueError("derived height-table size does not match the manifest")
    height_table = load_3dbag_height_table(height_path)
    if (
        height_table.data_version != version
        or height_table.license != license_name
        or height_table.attribution != attribution
        or height_table.study_area_id != study_area.get("id")
        or height_table.study_area_version != study_area.get("version")
        or height_table.study_area_geometry_sha256 != study_area.get("geometry_sha256")
        or height_table.study_area_artifact_sha256 != study_area.get("artifact_sha256")
        or height_table.study_area_horizontal_crs != study_area.get("horizontal_crs")
        or height_table.buffer_distance_m != scope.get("buffer_distance_m")
        or height_table.buffer_geometry_sha256 != height_data.get("buffer_geometry_sha256")
        or len(height_table.records) != height_data.get("record_count")
        or sum(record.status == "AVAILABLE" for record in height_table.records.values())
        != height_data.get("available_count")
        or sum(record.status == "UNAVAILABLE" for record in height_table.records.values())
        != height_data.get("unavailable_count")
    ):
        raise ValueError("derived height table provenance does not reconcile with the manifest")

    artifacts: list[Artifact] = []
    snapshots: list[DatasetSnapshot] = []
    tile_artifact_ids: list[str] = []
    used_record_ids: set[str] = set()
    validated_tile_data: list[Mapping[str, Any]] = []
    for item in tile_data:
        if not isinstance(item, Mapping):
            raise ValueError("tile manifest entry must be an object")
        tile_id = _required_text(item.get("tile_id"), "tile_id")
        tile_path = Path(_required_text(item.get("path"), "tile.path"))
        tile_url = _required_text(item.get("url"), "tile.url")
        parsed = urlparse(tile_url)
        if parsed.scheme != "https" or parsed.hostname != "data.3dbag.nl":
            raise ValueError("tile manifest URL must use the official 3D BAG data service")
        tile_hash = _validated_sha256(item.get("sha256"), f"tile {tile_id} sha256")
        if not tile_path.is_file() or _file_sha256(tile_path) != tile_hash:
            raise ValueError(f"tile SHA-256 does not reconcile for {tile_id}")
        if tile_path.stat().st_size != item.get("size_bytes"):
            raise ValueError(f"tile size does not reconcile for {tile_id}")
        validated_tile_data.append(item)
        artifact_id = _required_text(item.get("artifact_id"), "tile.artifact_id")
        snapshot_id = _required_text(item.get("snapshot_id"), "tile.snapshot_id")
        if artifact_id in used_record_ids or snapshot_id in used_record_ids or artifact_id == snapshot_id:
            raise ValueError(f"duplicate registration record ID for tile {tile_id}")
        used_record_ids.update((artifact_id, snapshot_id))
        tile_artifact_ids.append(artifact_id)
        query = _required_text(item.get("query"), "tile.query")
        retrieved_at = _required_text(item.get("retrieved_at"), "tile.retrieved_at")
        artifacts.append(
            Artifact(
                id=artifact_id,
                type="dataset-source",
                uri=str(tile_path.resolve()),
                sha256=tile_hash,
                mime="application/gzip",
                crs="EPSG:7415",
                producer="3dbag-official-tile-download",
                created_at=retrieved_at,
                project_id=project_id,
                size_bytes=tile_path.stat().st_size,
            )
        )
        snapshots.append(
            DatasetSnapshot(
                id=snapshot_id,
                project_id=project_id,
                source=tile_url,
                query=query,
                retrieved_at=retrieved_at,
                publisher=publisher,
                license=license_name,
                version=version,
                sha256=tile_hash,
                raw_artifact_id=artifact_id,
                normalized_artifact_id=height_data.get("artifact_id"),
            )
        )

    table_sources = {
        _required_text(source.get("tile_id"), "height_table.source_tiles.tile_id"): source
        for source in height_table.source_tiles
        if isinstance(source, Mapping)
    }
    if len(table_sources) != len(height_table.source_tiles):
        raise ValueError("height-table source tile metadata is malformed or duplicated")
    if set(table_sources) != {str(item.get("tile_id")) for item in validated_tile_data}:
        raise ValueError("height-table source tile IDs do not match the manifest tile set")
    for item in validated_tile_data:
        tile_id = str(item["tile_id"])
        source = table_sources[tile_id]
        if (
            source.get("url") != item.get("url")
            or Path(str(source.get("path"))).resolve() != Path(str(item.get("path"))).resolve()
            or source.get("sha256") != item.get("sha256")
            or source.get("size_bytes") != item.get("size_bytes")
        ):
            raise ValueError(f"height-table source tile provenance does not reconcile for {tile_id}")

    study_area_artifact_id = _required_text(study_area.get("artifact_id"), "study_area.artifact_id")
    derived_artifact_id = _required_text(height_data.get("artifact_id"), "height_table.artifact_id")
    if study_area_artifact_id in used_record_ids or derived_artifact_id in used_record_ids:
        raise ValueError("StudyArea or derived artifact ID collides with a tile registration record")
    if study_area_artifact_id == derived_artifact_id:
        raise ValueError("StudyArea and derived height-table artifact IDs must be different")
    used_record_ids.add(derived_artifact_id)
    created_at = _required_text(height_data.get("created_at"), "height_table.created_at")
    artifacts.append(
        Artifact(
            id=derived_artifact_id,
            type="derived-dataset",
            uri=str(height_path.resolve()),
            sha256=height_hash,
            mime="application/json",
            producer="urban_design.three_d_bag.extract_3dbag_height_table",
            created_at=created_at,
            project_id=project_id,
            size_bytes=height_path.stat().st_size,
            parent_artifact_ids=[*tile_artifact_ids, study_area_artifact_id],
        )
    )
    return SnapshotRegistrationBundle(
        project_id=project_id,
        manifest_sha256=manifest_sha256,
        artifacts=tuple(artifacts),
        dataset_snapshots=tuple(snapshots),
    )


def append_snapshot_registration_to_store(
    store: Any,
    bundle: SnapshotRegistrationBundle,
    *,
    backup_path: str | Path,
    expected_backup_sha256: str,
) -> tuple[list[Any], list[Any]]:
    """Append a reviewed registration bundle atomically when explicitly invoked.

    The CLI requires an explicit database path, ``--write`` and a verified
    pre-write database backup. This helper is not called by the extractor or
    the default registration-bundle command.
    """

    backup = Path(backup_path)
    expected_hash = _validated_sha256(expected_backup_sha256, "expected_backup_sha256")
    if not backup.is_file() or _file_sha256(backup) != expected_hash:
        raise ValueError("pre-write database backup SHA-256 does not match")
    project_record = store.get(bundle.project_id)
    if project_record.entity_type != "Project":
        raise ValueError("registration project_id does not resolve to a Project record")

    entities: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    records: list[Artifact | DatasetSnapshot] = [*bundle.artifacts, *bundle.dataset_snapshots]
    timestamp_by_id: dict[str, str] = {}
    for record in records:
        if isinstance(record, Artifact):
            timestamp = record.created_at.isoformat()
        else:
            timestamp = record.retrieved_at.isoformat()
        event_id = "event-3dbag-" + hashlib.sha256(
            f"{type(record).__name__}:{record.id}".encode("utf-8")
        ).hexdigest()[:32]
        timestamp_by_id[record.id] = timestamp
        event_payload = {
            "registration_manifest_sha256": bundle.manifest_sha256,
            "pre_write_backup_sha256": expected_hash,
            "pre_write_backup_path": str(backup.resolve()),
        }
        entities.append(
            {
                "entity_id": record.id,
                "entity_type": type(record).__name__,
                "payload": record.model_dump(mode="json"),
                "project_id": bundle.project_id,
                "event_id": event_id,
                "actor": "AGENT_AUTOMATION",
                "actor_kind": "AGENT_AUTOMATION",
                "action": "Create",
                "timestamp": timestamp,
                "reason": "Register reviewed official 3D BAG source tiles and derived height table.",
                "event_payload": event_payload,
            }
        )
        events.append(
            {
                "event_id": event_id,
                "timestamp": timestamp,
                "actor": "AGENT_AUTOMATION",
                "actor_kind": "AGENT_AUTOMATION",
                "action": "Create",
                "target_id": record.id,
                "target_type": type(record).__name__,
                "project_id": bundle.project_id,
                "reason": "Register reviewed official 3D BAG source tiles and derived height table.",
                "changed_refs": [record.id],
                "resulting_refs": [record.id],
                "payload": event_payload,
            }
        )
    if len(timestamp_by_id) != len(records):
        raise ValueError("duplicate registration record IDs would make a batch ambiguous")
    return store.commit_batch(entities=entities, events=events)


__all__ = [
    "BuildingHeightRecord",
    "BuildingHeightTable",
    "SnapshotRegistrationBundle",
    "THREE_DBAG_AGGREGATION_VERSION",
    "THREE_DBAG_ATTRIBUTION",
    "THREE_DBAG_BAG_ID_FIELD",
    "THREE_DBAG_GROUND_FIELD",
    "THREE_DBAG_EXTRACTOR_VERSION",
    "THREE_DBAG_LICENSE",
    "THREE_DBAG_LICENSE_URL",
    "THREE_DBAG_MANIFEST_VERSION",
    "THREE_DBAG_ROOF_P70_AGGREGATION",
    "THREE_DBAG_ROOF_P70_FIELD",
    "THREE_DBAG_SCHEMA_VERSION",
    "THREE_DBAG_VERTICAL_REFERENCE",
    "TileSource",
    "append_snapshot_registration_to_store",
    "build_snapshot_registration_bundle",
    "extract_3dbag_height_table",
    "load_3dbag_height_table",
    "normalize_bag_identificatie",
]
