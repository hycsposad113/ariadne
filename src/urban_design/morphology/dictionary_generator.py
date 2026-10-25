"""Dictionary-driven, orthogonal morphology generation for the W6 prototype.

The module keeps the older grid/morphology generator untouched. It consumes
frozen project files, treats catalogue scores as editorial ranking hints, and
records every assumed generation parameter with the candidate.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
import hashlib
import heapq
import json
import math
from pathlib import Path
import struct
import zlib
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from urban_design.generation.contracts import (GenerationContext, AreaGeometryValue, SkeletonArtifact, FixtureDictionaryRecipe, FixtureRetainedBuilding, FixturePipelineResult)

from shapely import set_precision
from pyproj import Transformer
from shapely.affinity import rotate
from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, transform as transform_geometry, unary_union

from urban_design.morphology.contracts import SITE_GEOMETRY_TOLERANCE_M, SiteRoadInput
from urban_design.morphology.streets import (
    count_road_components,
    derive_land_block_contacts,
    external_contact_boundary_side,
)
from urban_design.morphology.metrics import FloorPlate, RetainedBuilding, calculate_morphology_metrics
from urban_design.morphology_dictionary import load_dictionary, query_by_atmosphere


CRS = "EPSG:28992"
GENERATOR_VERSION = "dictionary-generator-v4"
ORIENTATION_VERSION = "minimum-rotated-rectangle-long-axis-v1"
CONTACT_RULES_VERSION = "contact-connectivity-v3.1"
ZONE_FUNCTION_RULES_VERSION = "portfolio-zone-name-function-key-v1"
WATERFRONT_BAND_M = 15.0
WATERFRONT_BUILD_BUFFER_M = 15.25
WATER_ROAD_CLEARANCE_M = 0.25
QUAY_WIDTH_M = 6.0
PRESERVED_SETBACK_M = 3.0
# Keep generated geometry slightly beyond the 3 m minimum so polygonal buffer
# approximation and the local/world rotation round trip cannot reduce measured
# clearance below the stated threshold.
PRESERVED_SETBACK_BUILD_BUFFER_M = 3.25
BLOCK_MIN_SIDE_M = 60.0
BLOCK_MAX_SIDE_M = 120.0
LAND_BLOCK_REQUIRED_CONTACTS = 2
ACTIVE_STUDY_AREA_ID = "study-area-rotterdam-m4h-pilot-project-v5"
ACTIVE_STUDY_AREA_GEOMETRY_SHA256 = "sha256:3dedb804fa4f07f4c9570bcc64e68c8d576c03340455ab35fd4963bca52aa4f5"

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_RECIPE_DIR = _ROOT / "config" / "morphology-recipes"
_DEFAULT_STUDY_AREA = _ROOT / "artifacts/week4-execution-r33-20260924T1741z-p4-unlock-focus/topology/study-area.geojson"
_DEFAULT_BASELINE = _ROOT / "artifacts" / "portfolio-baseline"
_DEFAULT_W5_RUN = _ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v5/run-20260916T093310Z"
_DEFAULT_SPATIAL_RUN = _ROOT / (
    "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
)


class DictionaryGenerationError(ValueError):
    """Raised when source geometry or an authored recipe cannot be used safely."""


@dataclass(frozen=True)
class PreservedBuilding:
    building_id: str
    bag_id: str
    geometry: BaseGeometry
    height_m: float | None
    floor_count: int | None
    floor_count_status: str
    confidence: str
    source_design_numbers: tuple[int, ...] = ()


@dataclass(frozen=True)
class ZonePreference:
    zone_id: str
    geometry: BaseGeometry
    name: str
    classification: str = "PREFERENCE"


@dataclass(frozen=True)
class ExternalContact:
    contact_id: str
    point: Point
    source_road_id: str
    boundary_side: str
    highway: str = "unknown"
    priority: str = "minor"
    layer: int = 0
    bridge: bool = False
    tunnel: bool = False
    land_block_id: str = "land-block-001"


@dataclass(frozen=True)
class IntensitySpec:
    code: str
    far_upper_bound: float
    height_upper_bound_m: float
    coverage_upper_bound: float | None
    first_floor_height_m: float
    standard_floor_height_m: float
    far_target: float | None = None


@dataclass(frozen=True)
class GeneratorInputs:
    design_area: BaseGeometry
    water_geometry: BaseGeometry
    preserved_buildings: tuple[PreservedBuilding, ...]
    zones: tuple[ZonePreference, ...]
    open_spaces: BaseGeometry
    external_contacts: tuple[ExternalContact, ...]
    crs: str = CRS
    source_provenance: Mapping[str, Any] = field(default_factory=dict)
    study_area_id: str = ACTIVE_STUDY_AREA_ID
    study_area_geometry_sha256: str = ACTIVE_STUDY_AREA_GEOMETRY_SHA256

    def __post_init__(self) -> None:
        if self.crs != CRS:
            raise DictionaryGenerationError(f"expected projected CRS {CRS}, got {self.crs}")
        if self.design_area.geom_type not in {"Polygon", "MultiPolygon"}:
            raise DictionaryGenerationError("StudyArea must be polygonal")
        if self.design_area.is_empty or not self.design_area.is_valid or self.design_area.area <= 0:
            raise DictionaryGenerationError("StudyArea must be valid, non-empty, and have positive area")
        if self.water_geometry.geom_type not in {"Polygon", "MultiPolygon", "GeometryCollection"}:
            raise DictionaryGenerationError("water geometry must be polygonal")
        for item in self.preserved_buildings:
            if item.geometry.is_empty or not item.geometry.is_valid:
                raise DictionaryGenerationError(f"preserved footprint {item.building_id} is invalid")
            if item.floor_count is not None and item.floor_count < 1:
                raise DictionaryGenerationError(f"preserved floor estimate for {item.building_id} must be positive")


@dataclass(frozen=True)
class OrientationFrame:
    orientation_deg: float
    origin: tuple[float, float]
    minimum_rotated_rectangle_deg: float

    def to_local(self, geometry: BaseGeometry) -> BaseGeometry:
        return rotate(geometry, -self.orientation_deg, origin=self.origin)

    def to_rd(self, geometry: BaseGeometry) -> BaseGeometry:
        return rotate(geometry, self.orientation_deg, origin=self.origin)


@dataclass(frozen=True)
class GeneratedRoad:
    segment_id: str
    geometry: BaseGeometry
    road_class: str
    width_m: float
    source: str


@dataclass(frozen=True)
class GeneratedBuilding:
    building_id: str
    footprint: BaseGeometry
    floor_footprints: tuple[BaseGeometry, ...]
    floor_count: int
    height_m: float
    dictionary_type_id: str
    block_assembly_type_id: str
    dictionary_parameters: Mapping[str, Any]
    selection_reason: Mapping[str, Any]
    block_id: str
    zone_id: str
    use_label: str


@dataclass(frozen=True)
class BlockDesign:
    block_id: str
    geometry: BaseGeometry
    assembly_type_id: str
    selection_reason: Mapping[str, Any]
    zone_id: str


@dataclass(frozen=True)
class ScenarioResult:
    inputs: GeneratorInputs
    intensity: IntensitySpec
    recipe: Mapping[str, Any]
    seed: int
    frame: OrientationFrame
    roads: tuple[GeneratedRoad, ...]
    buildings: tuple[GeneratedBuilding, ...]
    preserved_buildings: tuple[PreservedBuilding, ...]
    blocks: tuple[BlockDesign, ...]
    waterfront_no_build: BaseGeometry
    strategy_open_space: BaseGeometry
    land_area_m2: float
    metrics: Mapping[str, Any]
    validation: Mapping[str, Any]
    metadata: Mapping[str, Any]
    scenario_hash: str

    @property
    def valid(self) -> bool:
        return bool(self.validation.get("valid"))


def _parts(geometry: BaseGeometry, geometry_types: set[str]) -> tuple[BaseGeometry, ...]:
    if geometry.is_empty:
        return ()
    if geometry.geom_type in geometry_types:
        return (geometry,)
    if geometry.geom_type == "GeometryCollection" or geometry.geom_type.startswith("Multi"):
        return tuple(part for child in geometry.geoms for part in _parts(child, geometry_types))
    return ()


def _line_parts(geometry: BaseGeometry) -> tuple[LineString, ...]:
    return tuple(part for part in _parts(geometry, {"LineString"}) if part.length > 1e-7)


def _polygon_parts(geometry: BaseGeometry) -> tuple[Polygon, ...]:
    return tuple(part for part in _parts(geometry, {"Polygon"}) if part.area > 1e-7)


def _polygonal_intersection(geometry: BaseGeometry, mask: BaseGeometry) -> BaseGeometry:
    polygons = _polygon_parts(geometry.intersection(mask))
    return unary_union(polygons) if polygons else GeometryCollection()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DictionaryGenerationError(f"expected a JSON object at {path}")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _geojson_geometry(document: Mapping[str, Any], label: str) -> BaseGeometry:
    kind = document.get("type")
    if kind == "FeatureCollection":
        geometries = [shape(feature["geometry"]) for feature in document.get("features", []) if feature.get("geometry")]
        geometry = unary_union(geometries) if geometries else GeometryCollection()
    elif kind == "Feature":
        geometry = shape(document["geometry"])
    else:
        geometry = shape(document)
    if geometry.is_empty or not geometry.is_valid:
        raise DictionaryGenerationError(f"{label} geometry must be valid and non-empty")
    return geometry


def _json_geometry_features(document: Mapping[str, Any]) -> tuple[tuple[Mapping[str, Any], BaseGeometry], ...]:
    if document.get("type") == "FeatureCollection":
        return tuple((feature.get("properties", {}), shape(feature["geometry"])) for feature in document.get("features", []) if feature.get("geometry"))
    if document.get("type") == "Feature":
        return ((document.get("properties", {}), shape(document["geometry"])),)
    return (({}, shape(document)),)


def _source_record(path: Path, source_id_fragment: str) -> dict[str, Any]:
    candidates = (path.parent / "source-records-v5.json", path.parent.parent / "sources" / "source-records-v5.json")
    for records_path in candidates:
        if not records_path.exists():
            continue
        records = _read_json(records_path).get("records", [])
        for record in records:
            if source_id_fragment in str(record.get("id", "")):
                return dict(record)
    return {}


def _dictionary_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        rel = path.relative_to(directory).as_posix().encode("utf-8")
        digest.update(len(rel).to_bytes(4, "big"))
        digest.update(rel)
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _dictionary_fingerprint(dictionary: Mapping[str, Any]) -> tuple[str, str]:
    directory = dictionary.get("directory")
    if directory is not None and Path(directory).is_dir():
        path = Path(directory).resolve()
        label = path.relative_to(_ROOT).as_posix() if path.is_relative_to(_ROOT) else str(path)
        return _dictionary_hash(path), label
    payload = {key: dictionary[key] for key in ("schema", "atmospheres", "entries") if key in dictionary}
    rendered = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return _sha256_bytes(rendered), "injected-dictionary-mapping"


def _floor_estimate(height_m: float | None) -> tuple[int | None, str]:
    if height_m is None:
        return None, "UNKNOWN"
    if not math.isfinite(height_m) or height_m <= 0:
        return None, "UNKNOWN"
    return max(1, math.floor(height_m / 3.5 + 0.5)), "ESTIMATE_FROM_3DBAG"


def _load_osm_roads(path: Path, artifact_id: str, snapshot_id: str) -> tuple[SiteRoadInput, ...]:
    document = _read_json(path)
    roads: list[SiteRoadInput] = []
    for feature in document.get("features", []):
        geometry_data = feature.get("geometry") or {}
        if geometry_data.get("type") not in {"LineString", "MultiLineString"}:
            continue
        properties = feature.get("properties") or {}
        tags = properties.get("tags") or {}
        highway = tags.get("highway")
        if not isinstance(highway, str) or not highway.strip():
            continue
        road_id = feature.get("id") or properties.get("osm_id")
        if road_id is None:
            raise DictionaryGenerationError("OSM highway line lacks a stable feature id")
        raw_layer = tags.get("layer", "0")
        try:
            layer = int(raw_layer)
        except (TypeError, ValueError) as error:
            raise DictionaryGenerationError(f"OSM road {road_id} has a non-integer layer") from error
        if isinstance(raw_layer, str) and str(layer) != raw_layer.strip():
            raise DictionaryGenerationError(f"OSM road {road_id} has a non-canonical layer tag")
        active = not any(
            str(key).split(":", 1)[0] in {"construction", "proposed", "disused", "abandoned", "razed"}
            and value not in (None, False, 0, "", "no", "false")
            for key, value in tags.items()
        ) and highway not in {"construction", "proposed", "disused", "abandoned", "razed"}
        if not active:
            continue
        flag = lambda key: bool(tags.get(key)) and str(tags.get(key)).casefold() not in {"no", "false", "0"}
        roads.append(SiteRoadInput(
            road_id=str(road_id),
            geometry=shape(geometry_data),
            layer=layer,
            bridge=flag("bridge"),
            tunnel=flag("tunnel"),
            source_artifact_id=artifact_id,
            source_snapshot_id=snapshot_id,
            road_width_scope=None,
            highway=highway,
        ))
    return tuple(roads)


def load_generator_inputs(
    root: str | Path | None = None,
    *,
    study_area_path: str | Path | None = None,
) -> GeneratorInputs:
    """Load only retained local inputs; no network, model, or database calls."""
    project_root = Path(root).resolve() if root is not None else _ROOT
    baseline = project_root / "artifacts" / "portfolio-baseline"
    area_path = Path(study_area_path).resolve() if study_area_path is not None else project_root / _DEFAULT_STUDY_AREA.relative_to(_ROOT)
    if not area_path.exists():
        raise DictionaryGenerationError(f"StudyArea v5 source is missing: {area_path}")
    area_doc = _read_json(area_path)
    area = _geojson_geometry(area_doc, "StudyArea v5")
    props = area_doc.get("properties", {})
    area_id = str(area_doc.get("id") or props.get("study_area_id") or props.get("id") or "")
    if area_id != ACTIVE_STUDY_AREA_ID:
        raise DictionaryGenerationError(f"refusing a non-v5 StudyArea input: {area_id}")
    area_geometry_hash = str(props.get("study_area_geometry_sha256", ""))
    if area_geometry_hash != ACTIVE_STUDY_AREA_GEOMETRY_SHA256:
        raise DictionaryGenerationError("StudyArea v5 geometry hash does not match the active read-only state snapshot")
    if str(props.get("crs", "")) != CRS:
        raise DictionaryGenerationError(f"StudyArea v5 source must be {CRS}")

    w5_run = project_root / _DEFAULT_W5_RUN.relative_to(_ROOT)
    water_path = w5_run / "sources" / "raw" / "pdok-bgt-waterdeel-m4h.json"
    bag_path = w5_run / "sources" / "raw" / "pdok-bag-pand-m4h.json"
    spatial_run = project_root / _DEFAULT_SPATIAL_RUN.relative_to(_ROOT)
    osm_path = spatial_run / "sources" / "normalized" / "osm-overpass-v5-epsg28992.geojson"
    if not all(path.exists() for path in (water_path, bag_path, osm_path)):
        missing = [str(path) for path in (water_path, bag_path, osm_path) if not path.exists()]
        raise DictionaryGenerationError("required retained local source file is missing: " + ", ".join(missing))

    # The PDOK OGC API snapshots identify their request bbox as CRS84; normalize
    # explicitly to the StudyArea's projected horizontal CRS before overlay.
    to_rd = Transformer.from_crs("OGC:CRS84", CRS, always_xy=True)
    water_doc = _read_json(water_path)
    water_features = [
        transform_geometry(to_rd.transform, shape(feature["geometry"]))
        for feature in water_doc.get("features", [])
        if feature.get("geometry")
    ]
    water = unary_union(water_features).intersection(area) if water_features else GeometryCollection()
    water = unary_union(_polygon_parts(water)) if not water.is_empty else water

    bag_doc = _read_json(bag_path)
    bag_by_id = {
        str(feature.get("properties", {}).get("identificatie")): feature
        for feature in bag_doc.get("features", [])
        if feature.get("properties", {}).get("identificatie")
    }
    preserved_doc = _read_json(baseline / "preserved-buildings.json")
    by_bag: dict[str, dict[str, Any]] = {}
    excluded_preserved: list[dict[str, Any]] = []
    for item in preserved_doc.get("buildings", []):
        bag_id = str(item.get("bag_pand_id", ""))
        feature = bag_by_id.get(bag_id)
        if feature is None:
            excluded_preserved.append({"bag_id": bag_id, "reason": "no matching retained BAG footprint"})
            continue
        footprint = transform_geometry(to_rd.transform, shape(feature["geometry"])).intersection(area)
        if footprint.is_empty or footprint.area <= 1e-6:
            excluded_preserved.append({"bag_id": bag_id, "design_number": item.get("design_number"), "reason": "outside StudyArea v5"})
            continue
        record = by_bag.setdefault(bag_id, {"footprint": footprint, "items": []})
        record["items"].append(item)

    preserved: list[PreservedBuilding] = []
    for bag_id, record in sorted(by_bag.items()):
        item = sorted(record["items"], key=lambda value: int(value.get("design_number", 0)))[0]
        height_record = item.get("three_d_bag_height_reference") or {}
        height = height_record.get("height_above_ground_m")
        height_value = None if height is None else float(height)
        floors, status = _floor_estimate(height_value)
        preserved.append(PreservedBuilding(
            building_id=f"preserved-{bag_id}",
            bag_id=bag_id,
            geometry=record["footprint"],
            height_m=height_value,
            floor_count=floors,
            floor_count_status=status,
            confidence=str(item.get("confidence", "UNKNOWN")),
            source_design_numbers=tuple(sorted(int(value.get("design_number", 0)) for value in record["items"])),
        ))

    zone_doc = _read_json(baseline / "zones.geojson")
    open_doc = _read_json(baseline / "open-spaces.geojson")
    zone_crs = str(zone_doc.get("crs", {}).get("properties", {}).get("name", ""))
    open_space_crs = str(open_doc.get("crs", {}).get("properties", {}).get("name", ""))
    if zone_crs != CRS or open_space_crs != CRS:
        raise DictionaryGenerationError(f"zone/open-space CRS must be {CRS}; got {zone_crs!r}/{open_space_crs!r}")
    zones = tuple(
        ZonePreference(
            zone_id=str(props.get("id") or feature.get("id") or f"zone-{index:03d}"),
            geometry=shape(feature["geometry"]).intersection(area),
            name=str(props.get("name", "Unnamed preference zone")),
            classification=str(props.get("classification", "PREFERENCE")),
        )
        for index, feature in enumerate(zone_doc.get("features", []), start=1)
        for props in (feature.get("properties") or {},)
        if feature.get("geometry") and shape(feature["geometry"]).intersection(area).area > 1e-6
    )
    open_parts = [shape(feature["geometry"]).intersection(area) for feature in open_doc.get("features", []) if feature.get("geometry")]
    open_spaces = unary_union([part for part in open_parts if not part.is_empty]) if open_parts else GeometryCollection()

    osm_manifest_path = spatial_run / "source-and-integrity-manifest.json"
    osm_manifest: dict[str, Any] = {}
    if osm_manifest_path.exists():
        osm_manifest = _read_json(osm_manifest_path)
    osm_artifact = next(
        (item for item in osm_manifest.get("normalized_artifacts", []) if item.get("uri", "").endswith("osm-overpass-v5-epsg28992.geojson")),
        {},
    )
    if osm_artifact.get("crs") != CRS:
        raise DictionaryGenerationError(f"normalized OSM roads must be {CRS}, got {osm_artifact.get('crs')!r}")
    osm_snapshot = next(
        (item for item in osm_manifest.get("snapshots", []) if "osm-overpass-v5" in item.get("id", "")),
        {},
    )
    osm_hash = _sha256_file(osm_path)
    if osm_artifact.get("sha256"):
        expected = str(osm_artifact["sha256"]).removeprefix("sha256:")
        if expected != osm_hash:
            raise DictionaryGenerationError("normalized OSM snapshot hash does not match its retained manifest")
    osm_roads = _load_osm_roads(osm_path, str(osm_artifact.get("id", "osm-overpass-v5-normalized")), str(osm_snapshot.get("id", "snapshot-osm-overpass-v5")))
    land = area.difference(water)
    land_parts = sorted(_polygon_parts(land), key=lambda part: (-part.area, tuple(round(v, 6) for v in part.bounds)))
    contacts: list[ExternalContact] = []
    for block_index, land_block in enumerate(land_parts, start=1):
        block_id = f"land-block-{block_index:03d}"
        observed = derive_land_block_contacts(osm_roads, land_block=land_block, design_area=area)
        for contact in observed:
            contacts.append(ExternalContact(
                contact_id=contact.contact_id,
                point=contact.point,
                source_road_id=contact.source_road_id,
                boundary_side=external_contact_boundary_side(contact, design_area=area),
                highway=contact.highway,
                priority=contact.priority,
                layer=contact.layer,
                bridge=contact.bridge,
                tunnel=contact.tunnel,
                land_block_id=block_id,
            ))

    source_records_path = w5_run / "sources" / "source-records-v5.json"
    source_records = _read_json(source_records_path).get("records", []) if source_records_path.exists() else []
    water_record = next((dict(item) for item in source_records if "waterdeel" in item.get("id", "")), {})
    bag_record = next((dict(item) for item in source_records if "bag-pand" in item.get("id", "")), {})
    for record, path in ((water_record, water_path), (bag_record, bag_path)):
        record["observed_file_sha256"] = _sha256_file(path)
        record["observed_file_path"] = path.relative_to(project_root).as_posix()
    osm_record = {
        "id": osm_snapshot.get("id"),
        "source_identity": "Retained normalized OSM Overpass v5 roads",
        "query": osm_snapshot.get("query"),
        "version": osm_snapshot.get("version"),
        "retrieved_at": osm_snapshot.get("retrieved_at"),
        "license": osm_snapshot.get("license"),
        "attribution": osm_snapshot.get("attribution"),
        "limitations": osm_snapshot.get("limitations", []),
        "normalized_artifact_sha256": osm_hash,
        "normalized_artifact_path": osm_path.relative_to(project_root).as_posix(),
        "manifest_sha256": _sha256_file(osm_manifest_path) if osm_manifest_path.exists() else None,
    }
    source_provenance = {
        "study_area": {
            "id": ACTIVE_STUDY_AREA_ID,
            "version": "v5",
            "geometry_sha256": ACTIVE_STUDY_AREA_GEOMETRY_SHA256,
            "horizontal_crs": CRS,
            "units": "m",
            "source_file": area_path.relative_to(project_root).as_posix() if area_path.is_relative_to(project_root) else str(area_path),
            "file_sha256": _sha256_file(area_path),
            "geometry_area_m2": round(float(area.area), 3),
        },
        "water": water_record,
        "preserved_buildings": {
            "source_file": "artifacts/portfolio-baseline/preserved-buildings.json",
            "file_sha256": _sha256_file(baseline / "preserved-buildings.json"),
            "bag_source": bag_record,
            "height_field": "three_d_bag_height_reference.height_above_ground_m",
            "floor_conversion": "round(height_m / 3.5 m), ESTIMATE_FROM_3DBAG",
            "deduplicated_by_bag_id": True,
            "excluded": excluded_preserved,
        },
        "zones": {
            "source_file": "artifacts/portfolio-baseline/zones.geojson",
            "file_sha256": _sha256_file(baseline / "zones.geojson"),
            "classification": "PREFERENCE",
            "crs": str(zone_doc.get("crs", {}).get("properties", {}).get("name", CRS)),
        },
        "open_spaces": {
            "source_file": "artifacts/portfolio-baseline/open-spaces.geojson",
            "file_sha256": _sha256_file(baseline / "open-spaces.geojson"),
            "classification": "PREFERENCE_OPEN_SPACE",
            "crs": str(open_doc.get("crs", {}).get("properties", {}).get("name", CRS)),
        },
        "osm_contacts": osm_record,
        "intensity_A": {"source_file": "artifacts/portfolio-baseline/intensity-A.json", "file_sha256": _sha256_file(baseline / "intensity-A.json")},
        "intensity_B": {"source_file": "artifacts/portfolio-baseline/intensity-B.json", "file_sha256": _sha256_file(baseline / "intensity-B.json")},
        "excluded_preserved_buildings": excluded_preserved,
    }
    return GeneratorInputs(
        design_area=area,
        water_geometry=water,
        preserved_buildings=tuple(preserved),
        zones=zones,
        open_spaces=open_spaces,
        external_contacts=tuple(sorted(contacts, key=lambda item: (item.land_block_id, item.contact_id))),
        source_provenance=source_provenance,
    )


def load_intensities(root: str | Path | None = None) -> dict[str, IntensitySpec]:
    project_root = Path(root).resolve() if root is not None else _ROOT
    result: dict[str, IntensitySpec] = {}
    for code in ("A", "B"):
        document = _read_json(project_root / "artifacts" / "portfolio-baseline" / f"intensity-{code}.json")
        values = document["parameters"]
        upper = float(values["far_upper_bound_land"])
        result[code] = IntensitySpec(
            code=code,
            far_upper_bound=upper,
            height_upper_bound_m=float(values["height_upper_bound_m"]),
            coverage_upper_bound=None if values.get("coverage_upper_bound") is None else float(values["coverage_upper_bound"]),
            first_floor_height_m=float(values["first_floor_height_m"]),
            standard_floor_height_m=float(values["standard_floor_height_m"]),
            far_target=None if values.get("far_target_land") is None else float(values["far_target_land"]),
        )
    return result


def load_recipes(directory: str | Path | None = None) -> dict[str, dict[str, Any]]:
    recipe_root = Path(directory).resolve() if directory is not None else _DEFAULT_RECIPE_DIR
    recipes: dict[str, dict[str, Any]] = {}
    for path in sorted(recipe_root.glob("*.json")):
        recipe = _read_json(path)
        recipe_id = recipe.get("id")
        if not isinstance(recipe_id, str) or not recipe_id.strip():
            raise DictionaryGenerationError(f"recipe {path.name} must include a non-empty id")
        if recipe_id in recipes:
            raise DictionaryGenerationError(f"duplicate recipe id {recipe_id}")
        recipe["recipe_path"] = path.as_posix()
        recipe["recipe_sha256"] = _sha256_file(path)
        recipes[recipe_id] = recipe
    return recipes


def derive_orientation(design_area: BaseGeometry) -> OrientationFrame:
    """Select the longest minimum-rotated-rectangle edge as the local x axis."""
    if design_area.geom_type not in {"Polygon", "MultiPolygon"} or design_area.is_empty or not design_area.is_valid:
        raise DictionaryGenerationError("orientation requires a valid polygonal StudyArea")
    rectangle = design_area.minimum_rotated_rectangle
    if rectangle.geom_type != "Polygon":
        raise DictionaryGenerationError("StudyArea has no non-degenerate minimum rotated rectangle")
    coords = list(rectangle.exterior.coords)[:-1]
    edges = []
    for first, second in zip(coords, coords[1:] + coords[:1]):
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = math.hypot(dx, dy)
        if length > 1e-9:
            edges.append((length, math.degrees(math.atan2(dy, dx)) % 180.0))
    if not edges:
        raise DictionaryGenerationError("cannot derive a major axis from a degenerate StudyArea")
    angle = max(edges, key=lambda item: (item[0], -item[1]))[1]
    min_x, min_y, max_x, max_y = design_area.bounds
    return OrientationFrame(
        orientation_deg=round(angle, 10),
        origin=((min_x + max_x) / 2.0, (min_y + max_y) / 2.0),
        minimum_rotated_rectangle_deg=round(angle, 10),
    )


def _grid_values(low: float, high: float, step: float, inset: float = 0.0) -> list[float]:
    start = low + inset
    stop = high - inset
    if stop <= start:
        return []
    first = start + step / 2.0
    count = max(0, int(math.floor((stop - first) / step)) + 1)
    return [round(first + index * step, 6) for index in range(count)]


def _orthogonal_visibility_path(
    start: Point,
    end: Point,
    domain: BaseGeometry,
    *,
    spacing_m: float,
    obstacle_geometries: Sequence[BaseGeometry],
) -> tuple[Point, ...] | None:
    """Find a deterministic Manhattan path through free land using a visibility grid."""
    epsilon = 1e-6
    allowed = domain.buffer(epsilon)
    if not allowed.covers(start) or not allowed.covers(end):
        return None
    min_x, min_y, max_x, max_y = domain.bounds
    xs = set(_grid_values(min_x, max_x, spacing_m)) | {round(start.x, 6), round(end.x, 6)}
    ys = set(_grid_values(min_y, max_y, spacing_m)) | {round(start.y, 6), round(end.y, 6)}
    xs.update((round(min_x, 6), round(max_x, 6)))
    ys.update((round(min_y, 6), round(max_y, 6)))
    for obstacle in obstacle_geometries:
        if obstacle.is_empty:
            continue
        left, bottom, right, top = obstacle.bounds
        for value in (left - 1.0, left + 1.0, right - 1.0, right + 1.0):
            if min_x - epsilon <= value <= max_x + epsilon:
                xs.add(round(value, 6))
        for value in (bottom - 1.0, bottom + 1.0, top - 1.0, top + 1.0):
            if min_y - epsilon <= value <= max_y + epsilon:
                ys.add(round(value, 6))
    xs, ys = sorted(xs), sorted(ys)
    if len(xs) * len(ys) > 14_000:
        stride = max(1, math.ceil((len(xs) * len(ys) / 14_000) ** 0.5))
        xs = sorted(set(xs[::stride]) | {round(start.x, 6), round(end.x, 6)})
        ys = sorted(set(ys[::stride]) | {round(start.y, 6), round(end.y, 6)})

    points: dict[tuple[int, int], Point] = {}
    rows: dict[int, list[tuple[int, int]]] = {}
    columns: dict[int, list[tuple[int, int]]] = {}
    for yi, y in enumerate(ys):
        for xi, x in enumerate(xs):
            if (x, y) == (round(start.x, 6), round(start.y, 6)):
                point = start
            elif (x, y) == (round(end.x, 6), round(end.y, 6)):
                point = end
            else:
                point = Point(x, y)
            if allowed.covers(point):
                key = (xi, yi)
                points[key] = point
                rows.setdefault(yi, []).append(key)
                columns.setdefault(xi, []).append(key)
    source = (xs.index(round(start.x, 6)), ys.index(round(start.y, 6)))
    target = (xs.index(round(end.x, 6)), ys.index(round(end.y, 6)))
    if source not in points or target not in points:
        return None

    graph: dict[tuple[int, int], list[tuple[tuple[int, int], float]]] = {key: [] for key in points}
    for group, is_row in ((rows, True), (columns, False)):
        for keys in group.values():
            keys.sort(key=(lambda key: key[0]) if is_row else (lambda key: key[1]))
            for first, second in zip(keys, keys[1:]):
                p1, p2 = points[first], points[second]
                line = LineString((p1, p2))
                if not allowed.covers(line):
                    continue
                distance = float(line.length)
                graph[first].append((second, distance))
                graph[second].append((first, distance))

    distances = {source: 0.0}
    previous: dict[tuple[int, int], tuple[int, int]] = {}
    queue: list[tuple[float, tuple[int, int]]] = [(0.0, source)]
    while queue:
        cost, node = heapq.heappop(queue)
        if node == target:
            break
        if cost != distances.get(node):
            continue
        for neighbor, edge_cost in graph.get(node, []):
            new_cost = cost + edge_cost
            if new_cost + 1e-9 < distances.get(neighbor, math.inf):
                distances[neighbor] = new_cost
                previous[neighbor] = node
                heapq.heappush(queue, (new_cost, neighbor))
    if target not in distances:
        return None
    chain = [target]
    while chain[-1] != source:
        chain.append(previous[chain[-1]])
    chain.reverse()
    return tuple(points[key] for key in chain)


def _path_lines(points: Sequence[Point]) -> tuple[LineString, ...]:
    result = []
    for first, second in zip(points, points[1:]):
        if first.distance(second) <= 1e-7:
            continue
        line = LineString((first, second))
        if len(line.coords) != 2:
            raise DictionaryGenerationError("orthogonal path emitted a non-segment line")
        result.append(line)
    return tuple(result)


def _road_widths(recipe: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, str]]:
    values = recipe.get("road_widths_m", {})
    widths = {
        "main": float(values.get("main", 14.0)),
        "secondary": float(values.get("secondary", 10.0)),
        "alley": float(values.get("alley", 6.0)),
        "quay_promenade": QUAY_WIDTH_M,
    }
    if any(not math.isfinite(width) or width <= 0 for width in widths.values()):
        raise DictionaryGenerationError("road widths must be finite positive metres")
    sources = {
        "main": str(values.get("main_source", "ASSUMED_FROM_space.street_canyon")),
        "secondary": str(values.get("secondary_source", "ASSUMED_FROM_space.shared_street")),
        "alley": str(values.get("alley_source", "ASSUMED_FROM_space.shared_street")),
        "quay_promenade": "DESIGNER_DECISION_6M",
    }
    return widths, sources


def _rectilinear_roads(
    inputs: GeneratorInputs,
    recipe: Mapping[str, Any],
    frame: OrientationFrame,
    dictionary: Mapping[str, Any],
) -> tuple[tuple[GeneratedRoad, ...], BaseGeometry, dict[str, Any], BaseGeometry]:
    area = frame.to_local(inputs.design_area)
    water = frame.to_local(inputs.water_geometry)
    preserved = [frame.to_local(item.geometry) for item in inputs.preserved_buildings]
    water_band = area.intersection(water.buffer(WATERFRONT_BAND_M))
    widths, width_sources = _road_widths(recipe)
    max_width = max(widths[name] for name in ("main", "secondary", "alley"))
    preserve_union = unary_union(preserved) if preserved else GeometryCollection()
    # The 15 m waterfront rule prohibits buildings. Roads clear actual water
    # plus half their width, so the shoreline band does not sever the street graph.
    obstacles = [water.buffer(max_width / 2.0 + WATER_ROAD_CLEARANCE_M)]
    if not preserve_union.is_empty:
        obstacles.append(preserve_union.buffer(PRESERVED_SETBACK_M + max_width / 2.0 + 0.25))
    road_domain = area.difference(unary_union(obstacles))
    if not road_domain.is_valid:
        road_domain = road_domain.buffer(0)
    connector_width = widths["alley"]
    connector_obstacles = [water.buffer(connector_width / 2.0 + WATER_ROAD_CLEARANCE_M)]
    if not preserve_union.is_empty:
        connector_obstacles.append(preserve_union.buffer(PRESERVED_SETBACK_M + connector_width / 2.0 + WATER_ROAD_CLEARANCE_M))
    routing_domain = area.difference(unary_union(connector_obstacles))
    if not routing_domain.is_valid:
        routing_domain = routing_domain.buffer(0)
    min_x, min_y, max_x, max_y = area.bounds
    grid = recipe.get("road_grid", {})
    x_step = float(grid.get("cross_street_spacing_m", 100.0))
    y_step = float(grid.get("longitudinal_spacing_m", 80.0))
    inset = float(grid.get("site_edge_inset_m", 26.0))
    x_positions = _grid_values(min_x, max_x, x_step, inset)
    y_positions = _grid_values(min_y, max_y, y_step, inset)
    roads: list[GeneratedRoad] = []
    serial = 0
    for index, y in enumerate(y_positions):
        road_class = "main" if index % 2 == 0 else "secondary"
        source_line = LineString(((min_x - 2.0, y), (max_x + 2.0, y)))
        for part in _line_parts(source_line.intersection(road_domain)):
            serial += 1
            roads.append(GeneratedRoad(f"{recipe['id']}-street-{serial:04d}", part, road_class, widths[road_class], width_sources[road_class]))
    alley_frequency = max(2, int(grid.get("alley_every_nth_cross_street", 3)))
    for index, x in enumerate(x_positions):
        road_class = "alley" if index % alley_frequency == alley_frequency - 1 else "secondary"
        source_line = LineString(((x, min_y - 2.0), (x, max_y + 2.0)))
        for part in _line_parts(source_line.intersection(road_domain)):
            serial += 1
            roads.append(GeneratedRoad(f"{recipe['id']}-street-{serial:04d}", part, road_class, widths[road_class], width_sources[road_class]))

    obstacle_geometries = list(connector_obstacles)
    for land_index, contact in enumerate(inputs.external_contacts):
        local_point = frame.to_local(contact.point)
        block_id = contact.land_block_id or f"land-block-{land_index + 1:03d}"
        if contact.layer != 0 or contact.bridge or contact.tunnel or not road_domain.buffer(1e-5).covers(local_point):
            continue
        network = unary_union([item.geometry for item in roads]) if roads else GeometryCollection()
        if network.is_empty:
            continue
        target = nearest_points(local_point, network)[1]
        path = _orthogonal_visibility_path(
            local_point,
            target,
            routing_domain,
            spacing_m=min(20.0, max(8.0, min(x_step, y_step) / 5.0)),
            obstacle_geometries=obstacle_geometries,
        )
        if not path:
            continue
        for line in _path_lines(path):
            serial += 1
            roads.append(GeneratedRoad(f"{recipe['id']}-contact-{block_id}-{serial:04d}", set_precision(line, grid_size=1e-6), "alley", widths["alley"], width_sources["alley"]))

    roads = [replace(road, geometry=set_precision(road.geometry, grid_size=1e-6)) for road in roads]

    # Join grid pieces around obstacles through L/T routes; every connector is
    # computed against the same free-road domain and can contain only x/y runs.
    unroutable_routes: list[str] = []
    for _ in range(max(32, len(roads) * 2)):
        component_count = count_road_components(tuple(_road_contract(item) for item in roads)) if roads else 0
        if component_count <= 1:
            break
        components = _road_components(roads)
        anchor = max(components, key=lambda group: sum(item.geometry.length for item in group))
        candidates = []
        for group in components:
            if group is anchor:
                continue
            first_network = unary_union([item.geometry for item in group])
            second_network = unary_union([item.geometry for item in anchor])
            p1, p2 = nearest_points(first_network, second_network)
            candidates.append((p1.distance(p2), group, p1, p2))
        if not candidates:
            break
        _distance, group, start, end = min(candidates, key=lambda row: row[0])
        path = _orthogonal_visibility_path(
            start,
            end,
            routing_domain,
            spacing_m=min(15.0, max(8.0, min(x_step, y_step) / 6.0)),
            obstacle_geometries=obstacle_geometries,
        )
        if not path:
            # Do not emit a diagonal placeholder: failed routes are represented
            # as explicit validation failures, while every road remains axial.
            unroutable_routes.append(
                "a disconnected street component had no legal Manhattan path in the free-road domain; "
                f"gap_m={_distance:.3f}; start_local={[round(start.x, 3), round(start.y, 3)]}; "
                f"end_local={[round(end.x, 3), round(end.y, 3)]}"
            )
            break
        for line in _path_lines(path):
            serial += 1
            roads.append(GeneratedRoad(f"{recipe['id']}-detour-{serial:04d}", set_precision(line, grid_size=1e-6), "alley", widths["alley"], width_sources["alley"]))
    road_component_count_after_stitch = count_road_components(tuple(_road_contract(item) for item in roads)) if roads else 0

    # Quay segments are axis-aligned fragments in the land portion of the
    # 3–15 m shore strip. Their road surface is the explicitly allowed 6 m path.
    quay_zone = area.intersection(water.buffer(15.0).difference(water.buffer(3.0)))
    if not preserve_union.is_empty:
        quay_zone = quay_zone.difference(preserve_union.buffer(PRESERVED_SETBACK_M + QUAY_WIDTH_M / 2.0))
    quay_core = quay_zone.buffer(-QUAY_WIDTH_M / 2.0)
    quay_spacing = float(recipe.get("quay_sample_spacing_m", 36.0))
    q_serial = 0
    for y in _grid_values(min_y, max_y, quay_spacing, 3.0):
        line = LineString(((min_x - 2.0, y), (max_x + 2.0, y)))
        for part in _line_parts(line.intersection(quay_core)):
            if part.length < 12.0 or part.buffer(QUAY_WIDTH_M / 2.0).intersection(water).area > 1e-7:
                continue
            q_serial += 1
            roads.append(GeneratedRoad(f"{recipe['id']}-quay-h-{q_serial:03d}", part, "quay_promenade", QUAY_WIDTH_M, width_sources["quay_promenade"]))
    for x in _grid_values(min_x, max_x, quay_spacing, 3.0):
        line = LineString(((x, min_y - 2.0), (x, max_y + 2.0)))
        for part in _line_parts(line.intersection(quay_core)):
            if part.length < 12.0 or part.buffer(QUAY_WIDTH_M / 2.0).intersection(water).area > 1e-7:
                continue
            q_serial += 1
            roads.append(GeneratedRoad(f"{recipe['id']}-quay-v-{q_serial:03d}", part, "quay_promenade", QUAY_WIDTH_M, width_sources["quay_promenade"]))

    x_breaks = sorted({round(min_x, 6), round(max_x, 6), *x_positions})
    y_breaks = sorted({round(min_y, 6), round(max_y, 6), *y_positions})
    regular_surfaces = [item.geometry.buffer(item.width_m / 2.0, cap_style="flat").intersection(area) for item in roads if item.road_class != "quay_promenade"]
    quay_surfaces = [item.geometry.buffer(item.width_m / 2.0, cap_style="flat").intersection(area) for item in roads if item.road_class == "quay_promenade"]
    street_surface = unary_union(regular_surfaces) if regular_surfaces else GeometryCollection()
    quay_surface = unary_union(quay_surfaces) if quay_surfaces else GeometryCollection()
    open_preferences = frame.to_local(inputs.open_spaces).intersection(area)
    park_width = float(recipe.get("green_axis_width_m", 0.0))
    strategy_park = GeometryCollection()
    if park_width > 0:
        y_center = (min_y + max_y) / 2.0 + float(recipe.get("green_axis_offset_m", 0.0))
        park_line = LineString(((min_x - 2.0, y_center), (max_x + 2.0, y_center)))
        strategy_park = park_line.buffer(park_width / 2.0, cap_style="flat").intersection(area).difference(water.buffer(15.25))
        if not preserve_union.is_empty:
            strategy_park = strategy_park.difference(preserve_union.buffer(PRESERVED_SETBACK_BUILD_BUFFER_M))
    # ``open_preferences`` are honored as preferred open space for massing. The
    # roads remain able to cross them, which is recorded in the recipe trade-off.
    buildable = area.difference(unary_union((water.buffer(WATERFRONT_BUILD_BUFFER_M), preserve_union.buffer(PRESERVED_SETBACK_BUILD_BUFFER_M) if not preserve_union.is_empty else GeometryCollection(), street_surface, open_preferences, strategy_park)))
    if not buildable.is_valid:
        buildable = buildable.buffer(0)
    blocks: list[tuple[str, BaseGeometry]] = []
    min_side = float(recipe.get("block_size_target_m", {}).get("minimum", BLOCK_MIN_SIDE_M))
    max_side = float(recipe.get("block_size_target_m", {}).get("maximum", BLOCK_MAX_SIDE_M))
    for xi, (left, right) in enumerate(zip(x_breaks, x_breaks[1:])):
        width = right - left
        for yi, (bottom, top) in enumerate(zip(y_breaks, y_breaks[1:])):
            depth = top - bottom
            if width < min_side or depth < min_side or width > max_side + 1e-6 or depth > max_side + 1e-6:
                continue
            cell = box(left, bottom, right, top).intersection(buildable)
            for part in _polygon_parts(cell):
                if part.area >= 1_800.0:
                    blocks.append((f"block-{xi + 1:02d}-{yi + 1:02d}-{len(blocks) + 1:03d}", part))

    metadata = {
        "road_widths_m": widths,
        "road_width_sources": width_sources,
        "road_domain_area_m2": round(float(road_domain.area), 3),
        "connector_routing_domain_area_m2": round(float(routing_domain.area), 3),
        "street_block_count": len(blocks),
        "street_block_size_target_m": {"minimum": min_side, "maximum": max_side},
        "quay_segment_count": q_serial,
        "contact_connectivity_rules_version": CONTACT_RULES_VERSION,
        "unroutable_routes": unroutable_routes,
        "source_contact_count": len(inputs.external_contacts),
        "roads_before_massing": len(roads),
        "road_component_count_after_stitch": road_component_count_after_stitch,
        "street_surface_area_m2": round(float(street_surface.area), 3),
        "quay_surface_area_m2": round(float(quay_surface.area), 3),
    }
    return tuple(roads), buildable, metadata, strategy_park


def _road_contract(road: GeneratedRoad) -> Any:
    # ``count_road_components`` consumes only a geometry-bearing road shape.
    @dataclass(frozen=True)
    class _Road:
        segment_id: str
        geometry: BaseGeometry
        layer: int = 0
        bridge: bool = False
        tunnel: bool = False
        road_width_scope: str | None = None

    return _Road(road.segment_id, road.geometry)


def _road_components(roads: Sequence[GeneratedRoad]) -> list[list[GeneratedRoad]]:
    groups: list[list[GeneratedRoad]] = []
    remaining = set(range(len(roads)))
    while remaining:
        seed = min(remaining)
        component = {seed}
        stack = [seed]
        remaining.remove(seed)
        while stack:
            current = stack.pop()
            linked = [index for index in sorted(remaining) if roads[current].geometry.distance(roads[index].geometry) <= 1e-6]
            for index in linked:
                remaining.remove(index)
                component.add(index)
                stack.append(index)
        groups.append([roads[index] for index in sorted(component)])
    return groups


def _recipe_type_selection(
    dictionary: Mapping[str, Any],
    recipe: Mapping[str, Any],
    *,
    level: str,
    intensity: IntensitySpec,
    use_seed: str,
) -> tuple[str | None, dict[str, Any]]:
    dimension_targets = recipe.get("atmosphere_targets", {})
    dimension_weights = recipe.get("atmosphere_dimension_weights", {})
    if not dimension_targets:
        raise DictionaryGenerationError(f"recipe {recipe['id']} lacks atmosphere_targets")
    ranked = query_by_atmosphere(dictionary, dimension_targets, levels=[level])
    allowed = recipe.get("block_assembly_types" if level == "block_assembly" else "building_types", [])
    weights = {str(item["id"]): float(item.get("weight", 1.0)) for item in allowed}
    if not weights:
        raise DictionaryGenerationError(f"recipe {recipe['id']} has no {level} type entries")
    candidates = []
    entry_by_id = dictionary["entry_by_id"]
    for result in ranked:
        entry_id = result["entry_id"]
        if entry_id not in weights:
            continue
        entry = entry_by_id[entry_id]
        score_sum, weight_sum = 0.0, 0.0
        for dimension, target in dimension_targets.items():
            weight = float(dimension_weights.get(dimension, 1.0))
            observed = float(entry["atmosphere_scores"][dimension]["value"])
            score_sum += weight * (1.0 - abs(observed - float(target)))
            weight_sum += weight
        atmosphere_fit = score_sum / weight_sum if weight_sum else float(result["fit"])
        params = entry.get("generator_parameters", {}).get("parameters", {})
        compatible, compatibility_note = _density_compatibility(params, intensity)
        if level == "building_plan" and not compatible:
            continue
        # The recipe weight affects selection after dictionary query ranking;
        # it does not convert editorial scores into performance evidence.
        weighted_score = atmosphere_fit * weights[entry_id]
        candidates.append((weighted_score, atmosphere_fit, weights[entry_id], entry_id, compatibility_note))
    if not candidates:
        return None, {
            "status": "NO_DENSITY_COMPATIBLE_DICTIONARY_TYPE",
            "queried_level": level,
            "allowed_type_ids": sorted(weights),
            "height_upper_bound_m": intensity.height_upper_bound_m,
        }
    candidates.sort(key=lambda row: (-row[0], row[3]))
    top = candidates[0]
    # Stable seed-dependent tie rotation among equal weighted fits is bounded to
    # the top score group; recipe weights and density compatibility remain clear.
    top_group = [row for row in candidates if abs(row[0] - top[0]) <= 1e-9]
    selector = int(hashlib.sha256(use_seed.encode("utf-8")).hexdigest()[:8], 16)
    selected = top_group[selector % len(top_group)]
    return selected[3], {
        "status": "SELECTED",
        "queried_level": level,
        "atmosphere_fit_editorial_score": round(selected[1], 4),
        "recipe_type_weight": selected[2],
        "weighted_query_score": round(selected[0], 4),
        "density_compatibility": selected[4],
        "atmosphere_query_targets": dict(dimension_targets),
        "dictionary_entry_sources": [dict(item) for item in entry_by_id[selected[3]].get("sources", [])],
        "dictionary_atmosphere_score_sources": {
            name: list(entry_by_id[selected[3]].get("atmosphere_scores", {}).get(name, {}).get("source_ids", []))
            for name in dimension_targets
        },
        "selection_reason": "最高加權氛圍相近度，且字典參數與本強度高度上限可相容；分數僅作編輯排序。",
        "score_interpretation": "EDITORIAL_ESTIMATE_NOT_PERFORMANCE_EVIDENCE",
    }


def _density_compatibility(parameters: Mapping[str, Any], intensity: IntensitySpec) -> tuple[bool, str]:
    max_levels = _max_floor_count(intensity)
    for field_name in ("floor_count", "tower_floors"):
        value = parameters.get(field_name)
        if isinstance(value, list) and len(value) == 2:
            minimum = int(value[0])
            if field_name == "tower_floors":
                podium = parameters.get("podium_floors", [1, 1])
                minimum += int(podium[0] if isinstance(podium, list) else 0)
            if minimum > max_levels:
                return False, f"字典最低樓層 {minimum} 高於本強度高度可容納的 {max_levels} 層"
    return True, f"本強度最多 {max_levels} 層；選擇參數將落在字典範圍內"


def _max_floor_count(intensity: IntensitySpec) -> int:
    available = intensity.height_upper_bound_m - intensity.first_floor_height_m
    return max(1, 1 + math.floor((available + 1e-9) / intensity.standard_floor_height_m))


def _entry_parameter_range(entry: Mapping[str, Any], name: str) -> tuple[float, float] | None:
    value = entry.get("generator_parameters", {}).get("parameters", {}).get(name)
    if isinstance(value, list) and len(value) == 2 and all(isinstance(item, (int, float)) for item in value):
        return float(value[0]), float(value[1])
    return None


def _parameter_value(entry: Mapping[str, Any], name: str, default: float) -> float:
    bounds = _entry_parameter_range(entry, name)
    return default if bounds is None else min(bounds[1], max(bounds[0], default))


def _contained_template(block: BaseGeometry, geometry: BaseGeometry) -> BaseGeometry:
    clipped = geometry.intersection(block)
    if not clipped.is_valid:
        clipped = clipped.buffer(0)
    polygons = _polygon_parts(clipped)
    return unary_union(polygons) if polygons else GeometryCollection()


def _floor_shapes(
    footprint: BaseGeometry,
    entry: Mapping[str, Any],
    intensity: IntensitySpec,
    *,
    recipe_seed: str,
) -> tuple[tuple[BaseGeometry, ...], float, dict[str, Any]] | None:
    params = entry.get("generator_parameters", {}).get("parameters", {})
    profile = str(params.get("profile_key", ""))
    max_levels = _max_floor_count(intensity)
    requested = max_levels
    if isinstance(params.get("floor_count"), list):
        requested = min(max_levels, int(params["floor_count"][1]))
        if requested < int(params["floor_count"][0]):
            return None
        requested = max(int(params["floor_count"][0]), requested)
    if profile == "industrial_hall":
        clear_height = _parameter_value(entry, "clear_height_m", min(12.0, intensity.height_upper_bound_m))
        if clear_height > intensity.height_upper_bound_m:
            return None
        return (footprint,), clear_height, {"clear_height_m": clear_height, "floor_count": 1}
    if profile == "podium_tower":
        podium = params.get("podium_floors", [2, 8])
        towers = params.get("tower_floors", [8, 38])
        podium_levels = int(podium[0])
        tower_levels = min(int(towers[0]), max_levels - podium_levels)
        if tower_levels < int(towers[0]):
            return None
        total_levels = podium_levels + tower_levels
        min_x, min_y, max_x, max_y = footprint.bounds
        tower_width = min(max_x - min_x - 10.0, max_y - min_y - 10.0, 26.0)
        if tower_width < 15.0:
            return None
        tower = box((min_x + max_x - tower_width) / 2.0, (min_y + max_y - tower_width) / 2.0,
                    (min_x + max_x + tower_width) / 2.0, (min_y + max_y + tower_width) / 2.0)
        levels = [footprint] * podium_levels + [tower] * tower_levels
        height = intensity.first_floor_height_m + (total_levels - 1) * intensity.standard_floor_height_m
        return tuple(levels), height, {
            "tower_count": 1,
            "podium_floors": podium_levels,
            "tower_floors": tower_levels,
            "floor_count": total_levels,
        }
    if profile == "terraced":
        setback = _parameter_value(entry, "setback_per_level_m", 2.0)
        floor_shapes = []
        for index in range(requested):
            floor = footprint.buffer(-setback * index, join_style="mitre") if index else footprint
            if floor.is_empty or floor.area < 25.0:
                break
            floor_shapes.append(floor)
        if not floor_shapes:
            return None
        height = intensity.first_floor_height_m + (len(floor_shapes) - 1) * intensity.standard_floor_height_m
        return tuple(floor_shapes), height, {"floor_count": len(floor_shapes), "setback_per_level_m": setback, "roof_terrace": True}
    return tuple(footprint for _ in range(requested)), intensity.first_floor_height_m + (requested - 1) * intensity.standard_floor_height_m, {"floor_count": requested}


def _template_geometry(
    block: BaseGeometry,
    entry: Mapping[str, Any],
    *,
    seed_text: str,
    recipe: Mapping[str, Any],
) -> tuple[tuple[BaseGeometry, ...], dict[str, Any]]:
    profile = str(entry.get("generator_parameters", {}).get("parameters", {}).get("profile_key", ""))
    min_x, min_y, max_x, max_y = block.bounds
    width, depth = max_x - min_x, max_y - min_y
    margin = float(recipe.get("building_edge_setback_m", 5.0))
    left, bottom, right, top = min_x + margin, min_y + margin, max_x - margin, max_y - margin
    width, depth = right - left, top - bottom
    if width < 20.0 or depth < 20.0:
        return (), {}
    entry_params = entry.get("generator_parameters", {}).get("parameters", {})
    max_width = _entry_parameter_range(entry, "width_m")
    max_depth = _entry_parameter_range(entry, "depth_m")
    if max_width:
        right = min(right, left + max_width[1])
    if max_depth:
        top = min(top, bottom + max_depth[1])
    cx, cy = (left + right) / 2.0, (bottom + top) / 2.0
    width, depth = right - left, top - bottom
    params: dict[str, Any] = {}
    if profile in {"courtyard", "open_block"}:
        min_width = _entry_parameter_range(entry, "width_m")
        min_depth = _entry_parameter_range(entry, "depth_m")
        if min_width and width < min_width[0] or min_depth and depth < min_depth[0]:
            return (), {}
        outer = box(left, bottom, right, top)
        void_range = _entry_parameter_range(entry, "courtyard_void_ratio") or (0.2, 0.58)
        void_ratio = min(void_range[1], max(void_range[0], 0.34))
        inner_w, inner_d = width * math.sqrt(void_ratio), depth * math.sqrt(void_ratio)
        inner = box(cx - inner_w / 2.0, cy - inner_d / 2.0, cx + inner_w / 2.0, cy + inner_d / 2.0)
        ring = outer.difference(inner)
        if profile == "open_block":
            gap_range = _entry_parameter_range(entry, "opening_width_m") or (8.0, 30.0)
            gap = min(gap_range[1], max(gap_range[0], 16.0))
            ring = ring.difference(box(left - 1.0, cy - gap / 2.0, left + max(8.0, (width - inner_w) / 2.0), cy + gap / 2.0))
        params = {"width_m": round(width, 3), "depth_m": round(depth, 3), "courtyard_void_ratio": round(void_ratio, 4)}
        if profile == "open_block":
            params["opening_width_m"] = round(gap, 3)
        return tuple(geometry for geometry in (_contained_template(block, ring),) if not geometry.is_empty), params
    if profile in {"L", "U"}:
        thickness = min(20.0, width * 0.22, depth * 0.22)
        outer = box(left, bottom, right, top)
        if profile == "L":
            shape_geometry = unary_union((box(left, bottom, left + thickness, top), box(left, top - thickness, right, top)))
        else:
            shape_geometry = unary_union((
                box(left, bottom, right, bottom + thickness),
                box(left, bottom, left + thickness, top),
                box(right - thickness, bottom, right, top),
            ))
        opening = float((entry_params.get("opening_width_m") or [10.0, 28.0])[0])
        params = {"width_m": round(width, 3), "depth_m": round(depth, 3), "bar_depth_m": round(thickness, 3)}
        if profile == "U":
            params["opening_width_m"] = min(width - 2 * thickness, opening)
        return tuple(geometry for geometry in (_contained_template(block, shape_geometry),) if not geometry.is_empty), params
    if profile == "comb":
        spine_length = min(width, 105.0)
        spine_depth = min(16.0, depth / 4.0)
        spine = box(cx - spine_length / 2, cy - spine_depth / 2, cx + spine_length / 2, cy + spine_depth / 2)
        wing_count = min(4, max(2, int((entry_params.get("wing_count") or [2, 5])[0])))
        wing_depth = min(24.0, max(10.0, depth / 3.0))
        wings = []
        for index in range(wing_count):
            x = cx - spine_length / 2 + (index + 1) * spine_length / (wing_count + 1)
            wings.append(box(x - 6.0, cy + spine_depth / 2, x + 6.0, cy + spine_depth / 2 + wing_depth))
        comb = unary_union((spine, *wings))
        params = {"spine_length_m": round(spine_length, 3), "wing_depth_m": round(wing_depth, 3), "wing_count": wing_count}
        return tuple(geometry for geometry in (_contained_template(block, comb),) if not geometry.is_empty), params
    if profile == "I":
        slab_width = _parameter_value(entry, "width_m", min(85.0, width - 8.0))
        slab_depth = _parameter_value(entry, "depth_m", min(20.0, depth - 8.0))
        slab_width = min(width - 4.0, slab_width)
        slab_depth = min(depth - 4.0, slab_depth)
        if slab_width < 32.0 or slab_depth < 10.0:
            return (), {}
        slab = box(cx - slab_width / 2, cy - slab_depth / 2, cx + slab_width / 2, cy + slab_depth / 2)
        params = {"width_m": round(slab_width, 3), "depth_m": round(slab_depth, 3)}
        return tuple(geometry for geometry in (_contained_template(block, slab),) if not geometry.is_empty), params
    if profile == "industrial_hall":
        span = min(42.0, max(18.0, width - 8.0))
        hall_depth = min(72.0, max(30.0, depth - 8.0))
        hall = box(cx - span / 2, cy - hall_depth / 2, cx + span / 2, cy + hall_depth / 2)
        params = {"span_m": round(span, 3), "depth_m": round(hall_depth, 3), "grid_spacing_m": 12.0, "clear_height_m": 12.0}
        return tuple(geometry for geometry in (_contained_template(block, hall),) if not geometry.is_empty), params
    if profile in {"point", "point_array"}:
        tower_count = 1 if profile == "point" else 4
        tower_width = min(30.0, max(15.0, min(width, depth) * 0.28))
        offsets = ((0.0, 0.0),) if tower_count == 1 else ((-16.0, -16.0), (16.0, -16.0), (-16.0, 16.0), (16.0, 16.0))
        point_shapes = []
        for dx, dy in offsets:
            point_shape = box(cx + dx - tower_width / 2, cy + dy - tower_width / 2, cx + dx + tower_width / 2, cy + dy + tower_width / 2)
            fitted = _contained_template(block, point_shape)
            if not fitted.is_empty:
                point_shapes.append(fitted)
        if len(point_shapes) != tower_count:
            return (), {}
        params = {"footprint_width_m": round(tower_width, 3), "footprint_depth_m": round(tower_width, 3)} if profile == "point" else {"tower_count": tower_count, "spacing_m": 32.0}
        return tuple(point_shapes), params
    if profile == "podium_tower":
        coverage_range = _entry_parameter_range(entry, "podium_coverage") or (0.42, 0.82)
        target_coverage = min(coverage_range[1], max(coverage_range[0], 0.56))
        target_area = target_coverage * block.area
        base_w = min(width - 8.0, math.sqrt(target_area))
        base_d = min(depth - 8.0, target_area / max(base_w, 1e-9))
        if base_d > depth - 8.0:
            base_d = depth - 8.0
            base_w = target_area / max(base_d, 1e-9)
        if min(base_w, base_d) < 36.0 or max(base_w, base_d) > 120.0:
            return (), {}
        podium = box(cx - base_w / 2, cy - base_d / 2, cx + base_w / 2, cy + base_d / 2)
        fitted = _contained_template(block, podium)
        if fitted.is_empty:
            return (), {}
        coverage = float(fitted.area / max(block.area, 1e-9))
        if not coverage_range[0] - 1e-9 <= coverage <= coverage_range[1] + 1e-9:
            return (), {}
        params = {"podium_coverage": round(coverage, 4), "tower_count": 1, "podium_floors": 2, "tower_floors": 8}
        return (fitted,), params
    if profile == "rowhouse":
        frontage_range = _entry_parameter_range(entry, "frontage_m") or (5.0, 10.0)
        depth_range = _entry_parameter_range(entry, "depth_m") or (10.0, 26.0)
        frontage = min(frontage_range[1], max(frontage_range[0], 8.0))
        house_depth = min(depth_range[1], max(depth_range[0], depth - 8.0))
        gap = 1.0
        count = max(1, int((width + gap) // (frontage + gap)))
        total_width = count * frontage + max(0, count - 1) * gap
        start_x = cx - total_width / 2.0
        front_y = cy - house_depth / 2.0
        houses = []
        for index in range(count):
            house = box(start_x + index * (frontage + gap), front_y,
                        start_x + index * (frontage + gap) + frontage, front_y + house_depth)
            if block.covers(house):
                houses.append(house)
        params = {"frontage_m": round(frontage, 3), "depth_m": round(house_depth, 3), "party_wall_sides": 2}
        return tuple(houses), params
    if profile == "terraced":
        terrace = box(left, bottom, right, top)
        params = {"setback_per_level_m": 2.0}
        return tuple(geometry for geometry in (_contained_template(block, terrace),) if not geometry.is_empty), params
    return (), {}


def _validate_dictionary_parameters(entry: Mapping[str, Any], parameters: Mapping[str, Any]) -> list[str]:
    errors = []
    for name, value in parameters.items():
        bounds = _entry_parameter_range(entry, name)
        if bounds is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not bounds[0] - 1e-9 <= float(value) <= bounds[1] + 1e-9:
            errors.append(f"{entry['id']}.{name}={value!r} is outside dictionary range {bounds}")
    return errors


def _zone_preference_for(geometry: BaseGeometry, zones: Sequence[ZonePreference]) -> ZonePreference | None:
    if not zones:
        return None
    point = geometry.representative_point()
    matching = [zone for zone in zones if zone.geometry.covers(point)]
    if matching:
        return max(matching, key=lambda zone: (zone.geometry.intersection(geometry).area, zone.zone_id))
    zone, area = max(
        ((zone, zone.geometry.intersection(geometry).area) for zone in zones),
        key=lambda item: (item[1], item[0].zone_id),
        default=(None, 0.0),
    )
    return zone if area > 1.0 else None


def _zone_function_key(zone: ZonePreference | None) -> str:
    if zone is None:
        return "mixed_use"
    name = zone.name.casefold()
    if "energy" in name:
        return "energy_hub"
    if "maker" in name or "recycle" in name:
        return "maker_recycle_hub"
    if "art" in name or "recreation" in name:
        return "art_space_recreation"
    if "tidal" in name or "park" in name:
        return "residential_tidal_park"
    if "residential" in name:
        return "residential"
    return "mixed_use"


def _zone_for(geometry: BaseGeometry, zones: Sequence[ZonePreference]) -> str:
    zone = _zone_preference_for(geometry, zones)
    return zone.zone_id if zone else "unclassified"


def _local_contacts(inputs: GeneratorInputs, frame: OrientationFrame) -> tuple[ExternalContact, ...]:
    return tuple(replace(contact, point=frame.to_local(contact.point)) for contact in inputs.external_contacts)


def _candidate_buildings(
    blocks: Sequence[tuple[str, BaseGeometry]],
    inputs: GeneratorInputs,
    recipe: Mapping[str, Any],
    intensity: IntensitySpec,
    dictionary: Mapping[str, Any],
    seed: int,
) -> tuple[tuple[BlockDesign, ...], tuple[GeneratedBuilding, ...], list[str], dict[str, Any]]:
    entry_by_id = dictionary["entry_by_id"]
    local_zones = tuple(ZonePreference(zone.zone_id, zone.geometry, zone.name, zone.classification) for zone in inputs.zones)
    floorplates: list[tuple[BaseGeometry, str, int]] = []
    known_retained_gfa = 0.0
    for retained in inputs.preserved_buildings:
        if retained.floor_count is not None:
            known_retained_gfa += retained.geometry.area * retained.floor_count
    land_area = inputs.design_area.difference(inputs.water_geometry).area
    density_fraction = float(recipe.get("density_target_fraction", 0.86))
    far_target = min(intensity.far_upper_bound, float(intensity.far_target or intensity.far_upper_bound)) * density_fraction
    target_gfa = max(0.0, land_area * far_target - known_retained_gfa)
    new_buildings: list[GeneratedBuilding] = []
    block_designs: list[BlockDesign] = []
    parameter_failures: list[str] = []
    selection_audit: list[dict[str, Any]] = []
    current_gfa = 0.0
    for block_index, (block_id, block_geometry) in enumerate(blocks, start=1):
        zone = _zone_preference_for(block_geometry, local_zones)
        zone_id = zone.zone_id if zone else "unclassified"
        zone_function = _zone_function_key(zone)
        zone_recipe = dict(recipe)
        query_targets = dict(recipe.get("atmosphere_targets", {}))
        query_targets.update(recipe.get("zone_function_atmosphere_targets", {}).get(zone_function, {}))
        zone_recipe["atmosphere_targets"] = query_targets
        block_reason_seed = f"{seed}:{recipe['id']}:{block_id}:assembly"
        assembly_id, assembly_reason = _recipe_type_selection(
            dictionary, zone_recipe, level="block_assembly", intensity=intensity, use_seed=block_reason_seed
        )
        if assembly_id is None:
            parameter_failures.append(f"{block_id} has no block assembly type compatible with the recipe query")
            continue
        assembly_reason["zone_function_key"] = zone_function
        assembly_reason["zone_name"] = zone.name if zone else None
        assembly_reason["zone_function_rules_version"] = ZONE_FUNCTION_RULES_VERSION
        block_designs.append(BlockDesign(block_id, block_geometry, assembly_id, assembly_reason, zone_id))
        building_id = f"{recipe['id']}-{intensity.code}-{block_index:03d}"
        type_id, type_reason = _recipe_type_selection(
            dictionary, zone_recipe, level="building_plan", intensity=intensity, use_seed=f"{seed}:{building_id}:type"
        )
        if type_id is None:
            parameter_failures.append(f"{block_id} has no dictionary building type compatible with the {intensity.code} height limit")
            selection_audit.append({"block_id": block_id, "status": type_reason["status"], "reason": type_reason})
            continue
        type_reason["zone_function_key"] = zone_function
        type_reason["zone_name"] = zone.name if zone else None
        type_reason["zone_function_rules_version"] = ZONE_FUNCTION_RULES_VERSION
        entry = entry_by_id[type_id]
        fitted, shape_parameters = _template_geometry(block_geometry, entry, seed_text=f"{seed}:{building_id}", recipe=recipe)
        if not fitted:
            selection_audit.append({"block_id": block_id, "dictionary_type_id": type_id, "status": "BLOCK_TOO_SMALL_OR_IRREGULAR"})
            continue
        for component_index, footprint in enumerate(fitted, start=1):
            if footprint.is_empty or footprint.area < 150.0:
                continue
            shape_errors = _validate_dictionary_parameters(entry, shape_parameters)
            if shape_errors:
                parameter_failures.extend(shape_errors)
                continue
            floors = _floor_shapes(footprint, entry, intensity, recipe_seed=f"{seed}:{building_id}:{component_index}")
            if floors is None:
                parameter_failures.append(f"{building_id} {type_id} floor parameters do not fit the height limit")
                continue
            floor_shapes, height, level_parameters = floors
            if type_id == "building.industrial_hall":
                level_parameters["clear_height_m"] = min(20.0, intensity.height_upper_bound_m)
                height = float(level_parameters["clear_height_m"])
            final_parameters = dict(shape_parameters)
            final_parameters.update(level_parameters)
            final_parameters.pop("floor_count", None) if "floor_count" not in shape_parameters and type_id not in {"building.terraced", "building.podium_tower", "building.point_array", "building.point_tower", "building.i_slab"} else None
            if type_id in {"building.terraced", "building.podium_tower", "building.point_array", "building.point_tower", "building.i_slab"}:
                param_floor_range = _entry_parameter_range(entry, "floor_count")
                if param_floor_range and not param_floor_range[0] <= len(floor_shapes) <= param_floor_range[1]:
                    parameter_failures.append(f"{building_id} {type_id} floor_count={len(floor_shapes)} is outside dictionary range {param_floor_range}")
                    continue
            expected_remaining = min(target_gfa - current_gfa, intensity.far_upper_bound * land_area - known_retained_gfa - current_gfa)
            if expected_remaining <= 0:
                selection_audit.append({"block_id": block_id, "dictionary_type_id": type_id, "status": "DENSITY_TARGET_REACHED"})
                continue
            current_area_gfa = sum(shape.area for shape in floor_shapes)
            if current_area_gfa > expected_remaining + 1e-6:
                parameter_floor_range = _entry_parameter_range(entry, "floor_count")
                minimum_levels = int(parameter_floor_range[0]) if parameter_floor_range else 1
                if type_id == "building.podium_tower":
                    raw_parameters = entry.get("generator_parameters", {}).get("parameters", {})
                    minimum_levels = int(raw_parameters.get("podium_floors", [2, 8])[0]) + int(raw_parameters.get("tower_floors", [8, 38])[0])
                desired_levels = next((
                    level_count for level_count in range(len(floor_shapes), minimum_levels - 1, -1)
                    if math.fsum(shape.area for shape in floor_shapes[:level_count]) <= expected_remaining + 1e-6
                ), None)
                if desired_levels is None:
                    selection_audit.append({"block_id": block_id, "dictionary_type_id": type_id, "status": "SKIPPED_TO_KEEP_FAR_WITHIN_BOUND"})
                    continue
                floor_shapes = floor_shapes[:desired_levels]
                height = intensity.first_floor_height_m + (len(floor_shapes) - 1) * intensity.standard_floor_height_m
                if parameter_floor_range:
                    final_parameters["floor_count"] = len(floor_shapes)
                current_area_gfa = math.fsum(shape.area for shape in floor_shapes)
            if height > intensity.height_upper_bound_m + 1e-9:
                parameter_failures.append(f"{building_id} {type_id} height {height:.3f} m exceeds {intensity.height_upper_bound_m:.3f} m")
                continue
            building = GeneratedBuilding(
                building_id=f"{building_id}-{component_index:02d}",
                footprint=footprint,
                floor_footprints=tuple(floor_shapes),
                floor_count=len(floor_shapes),
                height_m=float(height),
                dictionary_type_id=type_id,
                block_assembly_type_id=assembly_id,
                dictionary_parameters=final_parameters,
                selection_reason={
                    **type_reason,
                    "block_assembly_type_id": assembly_id,
                    "block_selection_reason": dict(assembly_reason),
                    "zone_id": zone_id,
                    "zone_classification": next((zone.classification for zone in local_zones if zone.zone_id == zone_id), "PREFERENCE"),
                    "density_compatibility": type_reason.get("density_compatibility"),
                    "fitting_rule": "template clipped to orthogonal street block and selected dictionary parameter envelope",
                    "atmosphere_score_status": "EDITORIAL_ESTIMATE_NOT_PERFORMANCE_EVIDENCE",
                },
                block_id=block_id,
                zone_id=zone_id,
                use_label=str(next((zone.name for zone in local_zones if zone.zone_id == zone_id), "mixed-use")),
            )
            if any(building.footprint.intersection(old.geometry).area > 1e-7 for old in inputs.preserved_buildings):
                parameter_failures.append(f"{building.building_id} overlaps a preserved building")
                continue
            new_buildings.append(building)
            current_gfa += current_area_gfa
            selection_audit.append({
                "block_id": block_id,
                "building_id": building.building_id,
                "dictionary_type_id": type_id,
                "block_assembly_type_id": assembly_id,
                "atmosphere_fit_editorial_score": type_reason.get("atmosphere_fit_editorial_score"),
                "density_compatibility": type_reason.get("density_compatibility"),
                "parameters": final_parameters,
                "selection_reason": type_reason.get("selection_reason"),
            })
            if len(fitted) > 1:
                # Point-array placements already emit multiple single-building
                # features; each carries the same valid type id and block lineage.
                continue
            break
        if current_gfa >= target_gfa:
            break
    if not new_buildings:
        parameter_failures.append("no massing footprint fits a recipe block and its dictionary parameter ranges")
    unbuilt_audit = [item for item in selection_audit if not item.get("building_id")]
    return tuple(block_designs), tuple(new_buildings), parameter_failures, {
        "density_target_far_assumed": round(far_target, 6),
        "density_target_fraction_assumed": density_fraction,
        "new_gfa_target_m2": round(target_gfa, 3),
        "generated_new_gfa_m2": round(current_gfa, 3),
        "known_retained_gfa_m2": round(known_retained_gfa, 3),
        "blocks_retained_as_open_space_count": len(unbuilt_audit),
        "blocks_retained_as_open_space_reasons": dict(sorted(Counter(
            str(item.get("status", "NO_FIT_RECORDED")) for item in unbuilt_audit
        ).items())),
        "selection_audit": selection_audit,
    }


def _round_coords(value: Any, precision: int = 3) -> Any:
    if isinstance(value, (tuple, list)):
        return [_round_coords(item, precision) for item in value]
    if isinstance(value, float):
        return round(value, precision)
    return value


def _geometry_payload(geometry: BaseGeometry) -> dict[str, Any]:
    return _round_coords(mapping(geometry), 3)


def _floor_plates(buildings: Sequence[GeneratedBuilding]) -> tuple[FloorPlate, ...]:
    return tuple(
        FloorPlate(
            id=f"{building.building_id}-floor-{level + 1:02d}",
            geometry=geometry,
            level=level,
            building_id=building.building_id,
        )
        for building in buildings
        for level, geometry in enumerate(building.floor_footprints)
    )


def _metrics(
    inputs: GeneratorInputs,
    frame: OrientationFrame,
    roads: Sequence[GeneratedRoad],
    buildings: Sequence[GeneratedBuilding],
    intensity: IntensitySpec,
    recipe: Mapping[str, Any],
    generation_meta: Mapping[str, Any],
) -> dict[str, Any]:
    local_area = frame.to_local(inputs.design_area)
    metric_area = local_area.buffer(-SITE_GEOMETRY_TOLERANCE_M)
    local_water = frame.to_local(inputs.water_geometry)
    local_land = local_area.difference(local_water)
    land_area = float(local_land.area)
    local_buildings = [frame.to_local(item.footprint) for item in buildings]
    local_roads = [frame.to_local(item.geometry).buffer(item.width_m / 2.0, cap_style="flat").intersection(local_area) for item in roads if item.road_class != "quay_promenade"]
    retained_known = [item for item in inputs.preserved_buildings if item.floor_count is not None]
    retained_unknown = [item for item in inputs.preserved_buildings if item.floor_count is None]
    floorplates = [
        replace(plate, geometry=clipped)
        for plate in _floor_plates(buildings)
        for clipped in (_polygonal_intersection(frame.to_local(plate.geometry), metric_area),)
        if not clipped.is_empty
    ]
    for item in retained_known:
        local_geometry = _polygonal_intersection(frame.to_local(item.geometry), metric_area)
        floorplates.extend(FloorPlate(
            id=f"{item.building_id}-floor-{level + 1:02d}",
            geometry=local_geometry,
            level=level,
            building_id=item.building_id,
        ) for level in range(int(item.floor_count or 0)))
    retained_metric_inputs = tuple(
        RetainedBuilding(
            id=item.building_id,
            footprint=_polygonal_intersection(frame.to_local(item.geometry), metric_area),
            floor_count=item.floor_count if item.floor_count is not None else 1,
        )
        for item in inputs.preserved_buildings
    )
    known = calculate_morphology_metrics(
        local_land,
        tuple(floorplates),
        first_floor_height_m=intensity.first_floor_height_m,
        standard_floor_height_m=intensity.standard_floor_height_m,
        far_upper_bound=intensity.far_upper_bound,
    )
    coverage = calculate_morphology_metrics(
        local_land,
        tuple(
            replace(plate, geometry=clipped)
            for plate in _floor_plates(buildings)
            for clipped in (_polygonal_intersection(frame.to_local(plate.geometry), metric_area),)
            if not clipped.is_empty
        ),
        first_floor_height_m=intensity.first_floor_height_m,
        standard_floor_height_m=intensity.standard_floor_height_m,
        retained_buildings=retained_metric_inputs,
        far_upper_bound=intensity.far_upper_bound,
    )
    building_area = unary_union([
        *(_polygonal_intersection(geometry, local_area) for geometry in local_buildings),
        *(_polygonal_intersection(frame.to_local(item.geometry), local_area) for item in inputs.preserved_buildings),
    ]) if local_buildings or inputs.preserved_buildings else GeometryCollection()
    road_area = unary_union(local_roads) if local_roads else GeometryCollection()
    open_area = local_land.difference(building_area.union(road_area))
    new_heights = [float(item.height_m) for item in buildings]
    known_retained_heights = [float(item.height_m) for item in retained_known if item.height_m is not None]
    all_known_heights = [*new_heights, *known_retained_heights]
    type_counts = dict(sorted(Counter(item.dictionary_type_id for item in buildings).items()))
    block_counts = dict(sorted(Counter(item.block_assembly_type_id for item in buildings).items()))
    new_gfa = math.fsum(float(shape.area) for item in buildings for shape in item.floor_footprints)
    known_retained_gfa = math.fsum(item.geometry.area * int(item.floor_count or 0) for item in retained_known)
    known_far = (new_gfa + known_retained_gfa) / land_area if land_area else 0.0
    all_footprints_area = float(building_area.area)
    coverage_ratio = all_footprints_area / land_area if land_area else 0.0
    connected_contacts = int(generation_meta.get("connected_external_contact_count", 0))
    return {
        "scenario_status": "UNAPPROVED_PREVIEW",
        "human_decision_created": False,
        "intensity_code": intensity.code,
        "land_area_m2": round(land_area, 3),
        "water_area_m2": round(float(local_water.intersection(local_area).area), 3),
        "far_land_area": {
            "denominator_label": "legacy/unspecified:land_area",
            "known_value": round(known_far, 6),
            "known_gfa_m2": round(new_gfa + known_retained_gfa, 3),
            "new_gfa_m2": round(new_gfa, 3),
            "known_retained_gfa_m2": round(known_retained_gfa, 3),
            "unknown_retained_building_count": len(retained_unknown),
            "denominator_area_m2": round(land_area, 3),
            "status": "KNOWN_PARTIAL_WITH_UNKNOWN_RETAINED_COUNT" if retained_unknown else "AVAILABLE",
            "upper_bound": float(intensity.far_upper_bound),
            "upper_bound_check": "PASS" if known_far <= intensity.far_upper_bound + 1e-9 else "FAIL",
            "unknown_floor_warning": bool(retained_unknown),
        },
        "coverage_ratio": {
            "value": round(coverage_ratio, 6),
            "footprint_union_area_m2": round(all_footprints_area, 3),
            "denominator_area_m2": round(land_area, 3),
            "upper_bound": intensity.coverage_upper_bound,
            "upper_bound_check": "NOT_SET" if intensity.coverage_upper_bound is None else ("PASS" if coverage_ratio <= intensity.coverage_upper_bound + 1e-9 else "FAIL"),
        },
        "maximum_height_m": {
            "generated_building_m": round(max(new_heights, default=0.0), 3),
            "known_preserved_building_m": round(max(known_retained_heights, default=0.0), 3),
            "known_all_building_m": round(max(all_known_heights, default=0.0), 3),
            "unknown_preserved_building_count": sum(item.height_m is None for item in inputs.preserved_buildings),
            "generated_height_upper_bound_m": float(intensity.height_upper_bound_m),
            "generated_height_upper_bound_check": "PASS" if max(new_heights, default=0.0) <= intensity.height_upper_bound_m + 1e-9 else "FAIL",
        },
        "open_space_ratio": {
            "value": round(float(open_area.area / land_area) if land_area else 0.0, 6),
            "area_m2": round(float(open_area.area), 3),
            "denominator_area_m2": round(land_area, 3),
            "method": "land area minus new and preserved building footprints and non-quay street surfaces; includes undeveloped land and preference parks",
        },
        "external_contacts": {
            "rules_version": CONTACT_RULES_VERSION,
            "observed": int(generation_meta.get("observed_external_contact_count", 0)),
            "available": int(generation_meta.get("available_external_contact_count", 0)),
            "connected": connected_contacts,
            "land_blocks": generation_meta.get("land_block_connectivity", []),
        },
        "road_metrics": {
            "segment_count": len(roads),
            "street_segment_count": sum(item.road_class != "quay_promenade" for item in roads),
            "quay_promenade_segment_count": sum(item.road_class == "quay_promenade" for item in roads),
            "centerline_length_m": round(math.fsum(item.geometry.length for item in roads), 3),
            "street_surface_area_m2": round(float(road_area.area), 3),
        },
        "building_count": len(buildings),
        "preserved_buildings": {
            "count_inside_study_area": len(inputs.preserved_buildings),
            "known_floor_count": sum(item.floor_count is not None for item in inputs.preserved_buildings),
            "unknown_floor_count": len(retained_unknown),
            "floor_estimate_status_counts": dict(sorted(Counter(item.floor_count_status for item in inputs.preserved_buildings).items())),
        },
        "typology_composition": {"building_type_ids": type_counts, "block_assembly_type_ids": block_counts},
        "dictionary_parameter_validation_errors": list(generation_meta.get("dictionary_parameter_errors", [])),
        "density_allocation": dict(generation_meta.get("density_allocation", {})),
        "deterministic_kernel": {
            "name": "urban_design.morphology.metrics.calculate_morphology_metrics",
            "gfa_known_partial_m2": round(float(known.gfa_m2), 3),
            "far_known_partial": round(float(known.far), 6),
            "coverage_kernel_ratio_including_unknown_retained": round(float(coverage.coverage_ratio), 6),
            "provenance": "ASSUMED_PREVIEW; intensity JSON status is assumption-only",
        },
        "unused_validation_inputs": {
            "geometry_kernel_gfa_m2": round(float(known.gfa_m2), 3),
        },
    }


def _validate_scenario(
    inputs: GeneratorInputs,
    frame: OrientationFrame,
    roads: Sequence[GeneratedRoad],
    buildings: Sequence[GeneratedBuilding],
    blocks: Sequence[BlockDesign],
    intensity: IntensitySpec,
    recipe: Mapping[str, Any],
    dictionary: Mapping[str, Any],
    generation_meta: Mapping[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    failures.extend(f"street routing failed: {reason}" for reason in generation_meta.get("unroutable_routes", []))
    area = inputs.design_area
    water = inputs.water_geometry
    waterfront = area.intersection(water.buffer(WATERFRONT_BAND_M))
    preserved_union = unary_union([item.geometry for item in inputs.preserved_buildings]) if inputs.preserved_buildings else GeometryCollection()
    for road in roads:
        local = frame.to_local(road.geometry)
        for a, b in zip(list(local.coords), list(local.coords)[1:]) if local.geom_type == "LineString" else ():
            dx, dy = b[0] - a[0], b[1] - a[1]
            angle = abs(math.degrees(math.atan2(dy, dx))) % 90.0
            deviation = min(angle, 90.0 - angle)
            if deviation > 1.0 + 1e-9:
                failures.append(f"road {road.segment_id} contains a diagonal segment ({deviation:.4f}° from orthogonal frame)")
                break
        if not area.buffer(1e-5).covers(road.geometry):
            failures.append(f"road {road.segment_id} leaves StudyArea")
        road_surface = road.geometry.buffer(road.width_m / 2.0, cap_style="flat").intersection(area)
        if road_surface.intersection(water).area > 1e-7:
            failures.append(f"road surface {road.segment_id} overlaps water")
        if road.road_class == "quay_promenade":
            if road.width_m != QUAY_WIDTH_M:
                failures.append(f"quay promenade {road.segment_id} is not {QUAY_WIDTH_M:g} m wide")
        if not preserved_union.is_empty and road_surface.distance(preserved_union) < PRESERVED_SETBACK_M - 1e-5:
            failures.append(f"street surface {road.segment_id} violates the 3 m preserved-building setback")

    entry_by_id = dictionary["entry_by_id"]
    parameter_errors: list[str] = []
    for building in buildings:
        if building.dictionary_type_id not in entry_by_id or entry_by_id[building.dictionary_type_id]["level"] != "building_plan":
            failures.append(f"{building.building_id} lacks a valid building-plan dictionary type id")
        if not area.buffer(1e-5).covers(building.footprint):
            failures.append(f"{building.building_id} leaves StudyArea")
        if building.footprint.intersection(waterfront).area > 1e-7:
            failures.append(f"{building.building_id} enters the 15 m waterfront no-build band")
        if not preserved_union.is_empty and building.footprint.distance(preserved_union) < PRESERVED_SETBACK_M - 1e-5:
            failures.append(f"{building.building_id} violates the 3 m preserved-building setback")
        if building.height_m > intensity.height_upper_bound_m + 1e-9:
            failures.append(f"{building.building_id} exceeds the new-building height cap")
        entry = entry_by_id.get(building.dictionary_type_id)
        if entry:
            parameter_errors.extend(_validate_dictionary_parameters(entry, building.dictionary_parameters))
        for preserved in inputs.preserved_buildings:
            if building.footprint.intersection(preserved.geometry).area > 1e-7:
                failures.append(f"{building.building_id} covers preserved building {preserved.building_id}")

    for block in blocks:
        if block.assembly_type_id not in entry_by_id or entry_by_id[block.assembly_type_id]["level"] != "block_assembly":
            failures.append(f"{block.block_id} lacks a valid block-assembly dictionary type id")

    land_area = area.difference(water).area
    footprint_union = unary_union([
        *(item.footprint for item in buildings),
        *(item.geometry for item in inputs.preserved_buildings),
    ]) if buildings or inputs.preserved_buildings else GeometryCollection()
    coverage_ratio = float(footprint_union.area / land_area) if land_area else 0.0
    coverage_exceeded = intensity.coverage_upper_bound is not None and coverage_ratio > intensity.coverage_upper_bound + 1e-9
    if coverage_exceeded:
        failures.append(f"building coverage {coverage_ratio:.6f} exceeds intensity upper bound {intensity.coverage_upper_bound:.6f}")

    land_parts = sorted(_polygon_parts(area.difference(water)), key=lambda part: (-part.area, tuple(round(v, 6) for v in part.bounds)))
    connectivity = []
    local_roads = [
        replace(_road_contract(road), geometry=set_precision(frame.to_local(road.geometry), grid_size=1e-6))
        for road in roads if road.road_class != "quay_promenade"
    ]
    road_components = count_road_components(tuple(local_roads)) if local_roads else 0
    if road_components != 1:
        failures.append(f"generated street graph has {road_components} disconnected components")
    observed_count = 0
    available_count = 0
    connected_count = 0
    for index, land_part in enumerate(land_parts, start=1):
        block_id = f"land-block-{index:03d}"
        candidates = [item for item in inputs.external_contacts if item.land_block_id == block_id or len(land_parts) == 1]
        observed_count += len(candidates)
        local_land = frame.to_local(land_part)
        local_water = frame.to_local(water)
        max_road_half = max((road.width_m for road in roads if road.road_class != "quay_promenade"), default=0.0) / 2.0
        no_contact = local_water.buffer(max_road_half + WATER_ROAD_CLEARANCE_M)
        local_preserved = [frame.to_local(item.geometry) for item in inputs.preserved_buildings]
        if local_preserved:
            no_contact = unary_union((no_contact, unary_union(local_preserved).buffer(PRESERVED_SETBACK_M + max_road_half + 0.25)))
        available = [
            contact for contact in candidates
            if contact.layer == 0 and not contact.bridge and not contact.tunnel
            and not no_contact.buffer(1e-6).covers(frame.to_local(contact.point))
            and area.boundary.distance(contact.point) <= 0.5
        ]
        available_count += len(available)
        connected = [
            contact for contact in available
            if any(road.geometry.distance(contact.point) <= 0.5 for road in roads if road.road_class != "quay_promenade")
        ]
        connected_count += len(connected)
        required = min(LAND_BLOCK_REQUIRED_CONTACTS, len(available))
        block_warnings: list[str] = []
        if land_part.area >= 2_000.0 and len(available) < LAND_BLOCK_REQUIRED_CONTACTS:
            failures.append(f"{block_id} has {len(available)} usable observed external contacts; v3.1 task target is at least 2")
        if len(connected) < required:
            failures.append(f"{block_id} connects {len(connected)} of {required} required observed contacts")
        if len(available) < LAND_BLOCK_REQUIRED_CONTACTS:
            block_warnings.append("observed local OSM snapshot has fewer than two usable boundary contacts")
        connectivity.append({
            "land_block_id": block_id,
            "area_m2": round(float(land_part.area), 3),
            "required_external_connection_count": required,
            "observed_external_contact_count": len(candidates),
            "available_external_contact_count": len(available),
            "connected_external_contact_count": len(connected),
            "connected_contact_ids": sorted(contact.contact_id for contact in connected),
            "warnings": block_warnings,
        })

    if not buildings:
        failures.append("no new dictionary massing was generated")
    if parameter_errors:
        failures.extend(parameter_errors)
    far_exceeded = generation_meta.get("density_allocation", {}).get("known_far_after_generation", 0) > intensity.far_upper_bound + 1e-9
    if far_exceeded:
        failures.append("known-part land FAR exceeds intensity upper bound")
    # Unknown floor counts remain a warning and are excluded from the known FAR
    # numerator; they do not cause the candidate itself to fail.
    unknown_count = sum(item.floor_count is None for item in inputs.preserved_buildings)
    if unknown_count:
        warnings.append(f"{unknown_count} unknown retained floor estimate(s); known-part FAR is reported separately")
    if any(item.height_m is None for item in inputs.preserved_buildings):
        warnings.append("maximum known height excludes retained buildings without 3D BAG height")
    if generation_meta.get("dictionary_parameter_errors"):
        failures.extend(str(item) for item in generation_meta["dictionary_parameter_errors"])
    if not failures and not all(len(item["connected_contact_ids"]) >= item["required_external_connection_count"] for item in connectivity):
        failures.append("contact-connectivity-v3.1 is incomplete")
    return {
        "valid": not failures,
        "failure_reasons": list(dict.fromkeys(failures)),
        "warnings": list(dict.fromkeys(warnings)),
        "checks": {
            "orthogonal_roads": "PASS" if not any("diagonal segment" in item for item in failures) else "FAIL",
            "water_and_waterfront_no_build": "PASS" if not any("waterfront no-build" in item for item in failures) else "FAIL",
            "preserved_building_setback": "PASS" if not any("preserved building" in item for item in failures) else "FAIL",
            "dictionary_type_ids": "PASS" if not any("dictionary type id" in item for item in failures) else "FAIL",
            "dictionary_parameter_ranges": "PASS" if not parameter_errors else "FAIL",
            "building_coverage_upper_bound": "FAIL" if coverage_exceeded else "PASS",
            "contact_connectivity": "PASS" if all(len(item["connected_contact_ids"]) >= item["required_external_connection_count"] for item in connectivity) else "FAIL",
            "far_upper_bound_known_part": "FAIL" if far_exceeded else "PASS",
            "height_upper_bound_new_buildings": "PASS" if not any("height cap" in item for item in failures) else "FAIL",
            "road_graph_components": "PASS" if road_components == 1 else "FAIL",
        },
        "road_component_count": road_components,
        "land_block_connectivity": connectivity,
        "dictionary_parameter_errors": parameter_errors,
        "waterfront_band_m": WATERFRONT_BAND_M,
        "preserved_building_setback_m": PRESERVED_SETBACK_M,
        "contact_connectivity_rules_version": CONTACT_RULES_VERSION,
    }


def validate_road_orthogonality(scenario: ScenarioResult, *, tolerance_deg: float = 1.0) -> dict[str, Any]:
    off_axis = []
    max_deviation = 0.0
    for road in scenario.roads:
        local = scenario.frame.to_local(road.geometry)
        for line in _line_parts(local):
            for first, second in zip(line.coords, list(line.coords)[1:]):
                dx, dy = second[0] - first[0], second[1] - first[1]
                if math.hypot(dx, dy) <= 1e-9:
                    continue
                angle = math.degrees(math.atan2(dy, dx)) % 90.0
                deviation = min(angle, 90.0 - angle)
                max_deviation = max(max_deviation, deviation)
                if deviation > tolerance_deg:
                    off_axis.append({"segment_id": road.segment_id, "deviation_deg": round(deviation, 6), "coordinates": [list(first), list(second)]})
    return {
        "valid": not off_axis,
        "tolerance_deg": tolerance_deg,
        "maximum_deviation_deg": round(max_deviation, 8),
        "road_segment_count": len(scenario.roads),
        "off_axis_segments": off_axis,
    }


def _scenario_core_payload(result: ScenarioResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    return {
        "scenario_id": f"{result.intensity.code}-{result.recipe['id']}-seed-{result.seed}",
        "study_area_geometry_sha256": result.inputs.study_area_geometry_sha256,
        "recipe_sha256": result.metadata.get("recipe_sha256"),
        "dictionary_catalogue_sha256": result.metadata.get("dictionary_catalogue", {}).get("sha256"),
        "source_provenance": dict(result.metadata.get("source_provenance", {})),
        "orientation_deg": round(result.frame.orientation_deg, 8),
        "roads": [
            [road.segment_id, road.road_class, round(road.width_m, 3), _geometry_payload(road.geometry)]
            for road in result.roads
        ],
        "buildings": [
            [
                building.building_id,
                building.dictionary_type_id,
                building.block_assembly_type_id,
                building.floor_count,
                round(building.height_m, 3),
                _geometry_payload(building.footprint),
                [_geometry_payload(item) for item in building.floor_footprints],
                dict(building.dictionary_parameters),
            ]
            for building in result.buildings
        ],
        "metrics": dict(result.metrics),
        "validation": dict(result.validation),
    }


def generate_scenario(
    inputs: GeneratorInputs,
    recipe: Mapping[str, Any],
    *,
    intensity: IntensitySpec,
    seed: int = 42,
    dictionary: Mapping[str, Any] | None = None,
) -> ScenarioResult:
    """Generate and validate one unapproved deterministic proposal candidate."""
    catalogue = dictionary or load_dictionary()
    if recipe.get("schema_version") != "morphology-recipe-v1":
        raise DictionaryGenerationError(f"unsupported recipe schema for {recipe.get('id')}")
    dictionary_sha256, dictionary_directory = _dictionary_fingerprint(catalogue)
    frame = derive_orientation(inputs.design_area)
    raw_roads, local_buildable, road_meta, strategy_park = _rectilinear_roads(inputs, recipe, frame, catalogue)
    local_inputs = GeneratorInputs(
        design_area=frame.to_local(inputs.design_area),
        water_geometry=frame.to_local(inputs.water_geometry),
        preserved_buildings=tuple(replace(item, geometry=frame.to_local(item.geometry)) for item in inputs.preserved_buildings),
        zones=tuple(replace(item, geometry=frame.to_local(item.geometry)) for item in inputs.zones),
        open_spaces=frame.to_local(inputs.open_spaces),
        external_contacts=_local_contacts(inputs, frame),
        crs=inputs.crs,
        source_provenance=inputs.source_provenance,
        study_area_id=inputs.study_area_id,
        study_area_geometry_sha256=inputs.study_area_geometry_sha256,
    )
    # Partition the same validated buildable domain used to construct the road
    # skeleton. ``_rectilinear_roads`` works in the local axis frame; keep its
    # geometry local for block reconstruction and transform once on storage.
    local_roads = raw_roads
    local_blocks = []
    excluded_fragments: Counter[str] = Counter()
    excluded_fragment_area_m2: Counter[str] = Counter()
    grid = recipe.get("road_grid", {})
    min_x, min_y, max_x, max_y = local_inputs.design_area.bounds
    x_step = float(grid.get("cross_street_spacing_m", 100.0))
    y_step = float(grid.get("longitudinal_spacing_m", 80.0))
    inset = float(grid.get("site_edge_inset_m", 26.0))
    x_positions = _grid_values(min_x, max_x, x_step, inset)
    y_positions = _grid_values(min_y, max_y, y_step, inset)
    x_breaks = sorted({round(min_x, 6), round(max_x, 6), *x_positions})
    y_breaks = sorted({round(min_y, 6), round(max_y, 6), *y_positions})
    local_preserved_union = unary_union([item.geometry for item in local_inputs.preserved_buildings]) if local_inputs.preserved_buildings else GeometryCollection()
    no_build = local_inputs.water_geometry.buffer(WATERFRONT_BUILD_BUFFER_M)
    available_land = local_buildable
    min_side = float(recipe.get("block_size_target_m", {}).get("minimum", BLOCK_MIN_SIDE_M))
    max_side = float(recipe.get("block_size_target_m", {}).get("maximum", BLOCK_MAX_SIDE_M))
    for xi, (left, right) in enumerate(zip(x_breaks, x_breaks[1:])):
        cell_width = right - left
        for yi, (bottom, top) in enumerate(zip(y_breaks, y_breaks[1:])):
            cell_depth = top - bottom
            if cell_width < min_side or cell_depth < min_side or cell_width > max_side + 1e-6 or cell_depth > max_side + 1e-6:
                continue
            fragment = box(left, bottom, right, top).intersection(available_land)
            for polygon in _polygon_parts(fragment):
                if polygon.area >= 1_800.0:
                    local_blocks.append((f"block-{xi + 1:02d}-{yi + 1:02d}-{len(local_blocks) + 1:03d}", polygon))
                else:
                    excluded_fragments["below_minimum_area"] += 1
                    excluded_fragment_area_m2["below_minimum_area"] += polygon.area
    road_meta = {
        **road_meta,
        "street_block_count": len(local_blocks),
        "small_or_irregular_fragments_retained_as_open_space": {
            "minimum_area_m2": 1800.0,
            "status": "ASSUMED_GENERATOR_FILTER",
            "excluded_fragment_count": int(sum(excluded_fragments.values())),
            "excluded_area_m2": round(float(sum(excluded_fragment_area_m2.values())), 3),
            "reason_counts": dict(sorted(excluded_fragments.items())),
            "reason_area_m2": {key: round(float(value), 3) for key, value in sorted(excluded_fragment_area_m2.items())},
        },
    }
    block_designs, local_buildings, allocation_failures, density_meta = _candidate_buildings(
        local_blocks, local_inputs, recipe, intensity, catalogue, seed
    )
    buildings = tuple(replace(item, footprint=frame.to_rd(item.footprint), floor_footprints=tuple(frame.to_rd(geom) for geom in item.floor_footprints)) for item in local_buildings)
    blocks = tuple(replace(item, geometry=frame.to_rd(item.geometry)) for item in block_designs)
    roads = tuple(sorted(
        (replace(road, geometry=frame.to_rd(road.geometry)) for road in raw_roads),
        key=lambda item: (item.road_class, item.segment_id),
    ))
    local_waterfront = local_inputs.design_area.intersection(local_inputs.water_geometry.buffer(WATERFRONT_BAND_M))
    density_meta["known_far_after_generation"] = (
        density_meta["known_retained_gfa_m2"] + density_meta["generated_new_gfa_m2"]
    ) / max(local_inputs.design_area.difference(local_inputs.water_geometry).area, 1e-9)
    parameter_errors = list(allocation_failures)
    generation_meta = {
        **road_meta,
        "density_allocation": density_meta,
        "dictionary_parameter_errors": [],
        "observed_external_contact_count": len(inputs.external_contacts),
        "available_external_contact_count": 0,
        "connected_external_contact_count": 0,
        "land_block_connectivity": [],
    }
    # Calculate contact status in the world CRS, matching the geometry checked
    # by the v3.1 validator below.
    local_area = local_inputs.design_area
    local_max_half = max((road.width_m for road in local_roads if road.road_class != "quay_promenade"), default=0.0) / 2.0
    no_contact_area = local_inputs.water_geometry.buffer(local_max_half + WATER_ROAD_CLEARANCE_M)
    if not local_preserved_union.is_empty:
        no_contact_area = unary_union((no_contact_area, local_preserved_union.buffer(PRESERVED_SETBACK_M + local_max_half + 0.25)))
    eligible_contacts = [
        contact for contact in local_inputs.external_contacts
        if contact.layer == 0 and not contact.bridge and not contact.tunnel
        and local_area.boundary.distance(contact.point) <= 0.5
        and not no_contact_area.buffer(1e-6).covers(contact.point)
    ]
    connected_contacts = [
        contact for contact in eligible_contacts
        if any(road.geometry.distance(contact.point) <= 0.5 for road in local_roads if road.road_class != "quay_promenade")
    ]
    land_parts = sorted(
        _polygon_parts(local_area.difference(local_inputs.water_geometry)),
        key=lambda part: (-part.area, tuple(round(value, 6) for value in part.bounds)),
    )
    connectivity = []
    for index, land_part in enumerate(land_parts, start=1):
        block_id = f"land-block-{index:03d}"
        observed = [item for item in local_inputs.external_contacts if item.land_block_id == block_id or len(land_parts) == 1]
        available = [item for item in eligible_contacts if item in observed]
        connected = [item for item in connected_contacts if item in available]
        connectivity.append({
            "land_block_id": block_id,
            "area_m2": round(float(land_part.area), 3),
            "observed_external_contact_count": len(observed),
            "available_external_contact_count": len(available),
            "required_external_connection_count": min(LAND_BLOCK_REQUIRED_CONTACTS, len(available)),
            "connected_external_contact_count": len(connected),
            "connected_contact_ids": sorted(item.contact_id for item in connected),
            "warnings": [] if len(available) >= LAND_BLOCK_REQUIRED_CONTACTS else ["fewer than two usable observed external contacts"],
        })
    generation_meta.update({
        "available_external_contact_count": len(eligible_contacts),
        "connected_external_contact_count": len(connected_contacts),
        "land_block_connectivity": connectivity,
    })
    validation = _validate_scenario(inputs, frame, roads, buildings, blocks, intensity, recipe, catalogue, generation_meta)
    validation["generation_warnings"] = [
        "密度分配是可讀配方的 ASSUMED 方案；不是已核准設計。",
        "字典氛圍分數僅供檢索排序，不是模擬或性能證據。",
    ]
    if allocation_failures:
        validation["warnings"].extend(allocation_failures)
    validation["warnings"] = list(dict.fromkeys(validation["warnings"]))
    metrics = _metrics(inputs, frame, roads, buildings, intensity, recipe, generation_meta)
    metrics["far_land_area"]["upper_bound_check"] = "PASS" if metrics["far_land_area"]["known_value"] <= intensity.far_upper_bound + 1e-9 else "FAIL"
    metrics["coverage_ratio"]["upper_bound_check"] = "NOT_SET" if intensity.coverage_upper_bound is None else ("PASS" if metrics["coverage_ratio"]["value"] <= intensity.coverage_upper_bound + 1e-9 else "FAIL")
    metrics["external_contacts"]["land_blocks"] = connectivity
    metadata = {
        "generator_version": GENERATOR_VERSION,
        "orientation": {
            "rules_version": ORIENTATION_VERSION,
            "orientation_deg": round(frame.orientation_deg, 8),
            "origin": [round(frame.origin[0], 3), round(frame.origin[1], 3)],
            "minimum_rotated_rectangle_deg": round(frame.minimum_rotated_rectangle_deg, 8),
            "local_x_axis": "parallel to StudyArea v5 major axis",
        },
        "crs": inputs.crs,
        "seed": seed,
        "recipe_id": recipe["id"],
        "recipe_sha256": recipe.get("recipe_sha256"),
        "dictionary_catalogue": {
            "source_directory": dictionary_directory,
            "sha256": dictionary_sha256,
            "schema_id": catalogue.get("schema", {}).get("$id"),
            "entry_count": len(catalogue.get("entries", [])),
            "source_registry": dict(catalogue.get("atmospheres", {}).get("source_registry", {})),
        },
        "source_provenance": dict(inputs.source_provenance),
        "contact_connectivity_rules_version": CONTACT_RULES_VERSION,
        "design_decision": {
            "study_area_id": inputs.study_area_id,
            "study_area_geometry_sha256": inputs.study_area_geometry_sha256,
            "preserved_buildings_included_low_confidence": True,
            "waterfront_no_build_band_m": WATERFRONT_BAND_M,
            "quay_promenade_width_m": QUAY_WIDTH_M,
            "preserved_building_setback_m": PRESERVED_SETBACK_M,
            "human_decision_created": False,
            "proposal_acceptance_status": "NOT_ACCEPTED",
        },
        "road_generation": generation_meta,
    }
    waterfront_world = frame.to_rd(local_waterfront)
    park_world = frame.to_rd(strategy_park)
    provisional = ScenarioResult(
        inputs=inputs,
        intensity=intensity,
        recipe=dict(recipe),
        seed=seed,
        frame=frame,
        roads=roads,
        buildings=buildings,
        preserved_buildings=inputs.preserved_buildings,
        blocks=blocks,
        waterfront_no_build=waterfront_world,
        strategy_open_space=park_world,
        land_area_m2=float(inputs.design_area.difference(inputs.water_geometry).area),
        metrics=metrics,
        validation=validation,
        metadata=metadata,
        scenario_hash="",
    )
    core = _scenario_core_payload(provisional)
    scenario_hash = _sha256_bytes(json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    return replace(provisional, scenario_hash=scenario_hash)


def _feature(geometry: BaseGeometry, properties: Mapping[str, Any], feature_id: str) -> dict[str, Any]:
    return {"type": "Feature", "id": feature_id, "geometry": _geometry_payload(geometry), "properties": dict(properties)}


def scenario_geojson(result: ScenarioResult) -> dict[str, Any]:
    features = [
        _feature(result.inputs.design_area, {
            "feature_kind": "study_area",
            "study_area_id": result.inputs.study_area_id,
            "geometry_sha256": result.inputs.study_area_geometry_sha256,
            "source_status": "ACTIVE_STUDY_AREA_V5",
        }, "study-area"),
        _feature(result.inputs.water_geometry, {
            "feature_kind": "water", "no_build_distance_m": WATERFRONT_BAND_M,
        }, "water"),
        _feature(result.waterfront_no_build, {
            "feature_kind": "waterfront_building_no_build_band",
            "distance_from_water_m": WATERFRONT_BAND_M,
            "quay_promenade_allowed": True,
        }, "waterfront-no-build-band"),
    ]
    if not result.inputs.open_spaces.is_empty:
        features.append(_feature(result.inputs.open_spaces, {
            "feature_kind": "preference_open_space", "status": "PREFERENCE",
        }, "preference-open-space"))
    if not result.strategy_open_space.is_empty:
        features.append(_feature(result.strategy_open_space, {
            "feature_kind": "strategy_open_space", "status": "ASSUMED_RECIPE",
        }, "strategy-open-space"))
    local_land = result.inputs.design_area.difference(result.inputs.water_geometry)
    building_union = unary_union([
        *(item.footprint for item in result.buildings),
        *(item.geometry for item in result.preserved_buildings),
    ]) if result.buildings or result.preserved_buildings else GeometryCollection()
    street_surface = unary_union([
        road.geometry.buffer(road.width_m / 2.0, cap_style="flat").intersection(result.inputs.design_area)
        for road in result.roads if road.road_class != "quay_promenade"
    ]) if any(road.road_class != "quay_promenade" for road in result.roads) else GeometryCollection()
    residual_open_space = local_land.difference(building_union.union(street_surface))
    if not residual_open_space.is_empty:
        features.append(_feature(residual_open_space, {
            "feature_kind": "residual_open_space",
            "method": "land minus generated and preserved footprints and non-quay street surfaces",
            "includes_unbuilt_small_or_irregular_fragments": True,
        }, "residual-open-space"))
    for index, road in enumerate(result.roads, start=1):
        features.append(_feature(road.geometry, {
            "feature_kind": "road_segment",
            "segment_id": road.segment_id,
            "road_class": road.road_class,
            "width_m": road.width_m,
            "width_source": road.source,
            "alignment_rule": "main_axis_or_perpendicular",
            "orientation_deg": round(result.frame.orientation_deg, 6),
        }, f"road-{index:04d}"))
    for index, preserved in enumerate(result.preserved_buildings, start=1):
        features.append(_feature(preserved.geometry, {
            "feature_kind": "preserved_building",
            "building_id": preserved.building_id,
            "bag_id": preserved.bag_id,
            "source_design_numbers": list(preserved.source_design_numbers),
            "preserved": True,
            "confidence": preserved.confidence,
            "floor_count": preserved.floor_count,
            "floor_estimate_status": preserved.floor_count_status,
            "height_m": preserved.height_m,
            "floor_count_source": "three_d_bag_height_reference.height_above_ground_m / 3.5 m, rounded" if preserved.floor_count is not None else "UNKNOWN",
            "dictionary_type_id": None,
        }, f"preserved-{index:03d}"))
    for index, building in enumerate(result.buildings, start=1):
        features.append(_feature(building.footprint, {
            "feature_kind": "generated_building",
            "building_id": building.building_id,
            "dictionary_type_id": building.dictionary_type_id,
            "block_assembly_type_id": building.block_assembly_type_id,
            "dictionary_parameters": dict(building.dictionary_parameters),
            "selection_reason": dict(building.selection_reason),
            "block_id": building.block_id,
            "zone_id": building.zone_id,
            "preferred_use_label": building.use_label,
            "floor_count": building.floor_count,
            "height_m": round(building.height_m, 3),
            "floor_area_m2": round(math.fsum(item.area for item in building.floor_footprints), 3),
            "seed": result.seed,
            "proposal_status": "UNAPPROVED_PREVIEW",
        }, f"building-{index:03d}"))
    for index, block in enumerate(result.blocks, start=1):
        built = any(item.block_id == block.block_id for item in result.buildings)
        features.append(_feature(block.geometry, {
            "feature_kind": "street_block" if built else "open_space_block",
            "block_id": block.block_id,
            "block_assembly_type_id": block.assembly_type_id,
            "selection_reason": dict(block.selection_reason),
            "zone_id": block.zone_id,
            "massing_status": "BUILT" if built else "RETAINED_AS_OPEN_SPACE",
        }, f"block-{index:03d}"))
    return {
        "type": "FeatureCollection",
        "name": f"{result.intensity.code}-{result.recipe['id']}-seed-{result.seed}",
        "crs": {"type": "name", "properties": {"name": result.inputs.crs}},
        "properties": {
            "generator_version": GENERATOR_VERSION,
            "scenario_hash": result.scenario_hash,
            "orientation_deg": round(result.frame.orientation_deg, 8),
            "study_area_geometry_sha256": result.inputs.study_area_geometry_sha256,
            "recipe_sha256": result.metadata.get("recipe_sha256"),
            "dictionary_catalogue": dict(result.metadata.get("dictionary_catalogue", {})),
            "source_provenance": dict(result.metadata.get("source_provenance", {})),
            "validation_valid": result.valid,
        },
        "features": features,
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class _Raster:
    """Tiny RGB raster surface used to emit deterministic PNGs without packages."""

    def __init__(self, width: int, height: int, color: tuple[int, int, int]) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(color * (width * height))

    def _pixel(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            index = (y * self.width + x) * 3
            self.pixels[index:index + 3] = bytes(color)

    def line(self, first: tuple[int, int], second: tuple[int, int], color: tuple[int, int, int], width: int = 1) -> None:
        x0, y0 = map(int, first)
        x1, y1 = map(int, second)
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx - dy
        radius = max(0, width // 2)
        while True:
            for oy in range(-radius, radius + 1):
                for ox in range(-radius, radius + 1):
                    self._pixel(x0 + ox, y0 + oy, color)
            if x0 == x1 and y0 == y1:
                break
            twice = 2 * err
            if twice > -dy:
                err -= dy
                x0 += sx
            if twice < dx:
                err += dx
                y0 += sy

    def polygon(self, rings: Sequence[Sequence[tuple[int, int]]], color: tuple[int, int, int]) -> None:
        if not rings or len(rings[0]) < 3:
            return
        min_y = max(0, min(point[1] for ring in rings for point in ring))
        max_y = min(self.height - 1, max(point[1] for ring in rings for point in ring))
        for y in range(int(min_y), int(max_y) + 1):
            intersections = []
            for ring in rings:
                for first, second in zip(ring, list(ring)[1:] + [ring[0]]):
                    x1, y1 = first
                    x2, y2 = second
                    if y1 == y2 or y < min(y1, y2) or y >= max(y1, y2):
                        continue
                    intersections.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
            intersections.sort()
            for left, right in zip(intersections[::2], intersections[1::2]):
                for x in range(max(0, math.ceil(left)), min(self.width - 1, math.floor(right)) + 1):
                    self._pixel(x, y, color)

    def circle(self, center: tuple[int, int], radius: int, color: tuple[int, int, int]) -> None:
        cx, cy = center
        for y in range(-radius, radius + 1):
            for x in range(-radius, radius + 1):
                if x * x + y * y <= radius * radius:
                    self._pixel(cx + x, cy + y, color)

    def text(self, x: int, y: int, value: str, color: tuple[int, int, int], scale: int = 1) -> None:
        cursor = x
        for character in value.upper():
            bitmap = _FONT.get(character, _FONT["?"])
            for row, bits in enumerate(bitmap):
                for column, bit in enumerate(bits):
                    if bit == "1":
                        for sy in range(scale):
                            for sx in range(scale):
                                self._pixel(cursor + column * scale + sx, y + row * scale + sy, color)
            cursor += 6 * scale

    def png(self) -> bytes:
        raw = b"".join(b"\x00" + self.pixels[row * self.width * 3:(row + 1) * self.width * 3] for row in range(self.height))
        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


_FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "|": ("00100", "00100", "00100", "00100", "00100", "00100", "00100"),
    "=": ("00000", "11111", "00000", "11111", "00000", "00000", "00000"),
}


def _rgba(color: str) -> tuple[int, int, int]:
    value = color.removeprefix("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _screen_transform(bounds: tuple[float, float, float, float], rect: tuple[int, int, int, int]):
    min_x, min_y, max_x, max_y = bounds
    left, top, right, bottom = rect
    span_x, span_y = max(max_x - min_x, 1e-9), max(max_y - min_y, 1e-9)
    scale = min((right - left) / span_x, (bottom - top) / span_y)
    offset_x = left + ((right - left) - span_x * scale) / 2.0
    offset_y = top + ((bottom - top) - span_y * scale) / 2.0
    def convert(x: float, y: float) -> tuple[int, int]:
        return round(offset_x + (x - min_x) * scale), round(bottom - ((y - min_y) * scale + offset_y - top))
    return convert, scale


def _draw_geom(raster: _Raster, geometry: BaseGeometry, convert, color: tuple[int, int, int], *, outline: tuple[int, int, int] | None = None, hole_color: tuple[int, int, int] | None = None, line_width: int = 1) -> None:
    for polygon in _polygon_parts(geometry):
        rings = [[convert(x, y) for x, y, *_ in polygon.exterior.coords[:-1]]]
        if hole_color is None:
            raster.polygon(rings, color)
            for interior in polygon.interiors:
                hole = [convert(x, y) for x, y, *_ in interior.coords[:-1]]
                raster.polygon((hole,), color)
        else:
            raster.polygon(rings, color)
            for interior in polygon.interiors:
                hole = [convert(x, y) for x, y, *_ in interior.coords[:-1]]
                raster.polygon((hole,), hole_color)
        if outline:
            for ring in (polygon.exterior, *polygon.interiors):
                coords = [convert(x, y) for x, y, *_ in ring.coords]
                for first, second in zip(coords, coords[1:]):
                    raster.line(first, second, outline, line_width)


_TYPE_LABELS = {
    "building.courtyard_closed": "COURT",
    "building.courtyard_open_corner": "OPEN",
    "building.l_block": "L",
    "building.u_block": "U",
    "building.comb": "COMB",
    "building.i_slab": "SLAB",
    "building.point_tower": "TOWER",
    "building.point_array": "POINT",
    "building.podium_tower": "PODIUM",
    "building.industrial_hall": "HALL",
    "building.terraced": "TERRACE",
}


def _draw_plan(raster: _Raster, result: ScenarioResult, rect: tuple[int, int, int, int], *, legend: bool) -> None:
    local_area = result.frame.to_local(result.inputs.design_area)
    bounds = local_area.bounds
    convert, scale = _screen_transform(bounds, rect)
    local_water = result.frame.to_local(result.inputs.water_geometry)
    local_band = local_area.intersection(local_water.buffer(WATERFRONT_BAND_M))
    _draw_geom(raster, local_area, convert, _rgba("#efece4"), outline=_rgba("#243746"), line_width=2)
    _draw_geom(raster, local_band, convert, _rgba("#d7e8e8"), outline=None)
    _draw_geom(raster, local_water, convert, _rgba("#82b4c1"), outline=_rgba("#4d8793"), line_width=1)
    local_open = result.frame.to_local(result.inputs.open_spaces).union(result.frame.to_local(result.strategy_open_space))
    _draw_geom(raster, local_open.intersection(local_area), convert, _rgba("#a9c998"), outline=None)
    road_colors = {
        "main": _rgba("#c45e38"),
        "secondary": _rgba("#d49a45"),
        "alley": _rgba("#89959a"),
        "quay_promenade": _rgba("#32877d"),
    }
    for road in result.roads:
        local = result.frame.to_local(road.geometry)
        pixel_width = max(1, round(road.width_m * scale))
        for line in _line_parts(local):
            coords = [convert(x, y) for x, y, *_ in line.coords]
            for first, second in zip(coords, coords[1:]):
                raster.line(first, second, road_colors[road.road_class], pixel_width)
    generated_palette = ["#c68d5e", "#9a7f61", "#b7a174", "#cfaa77", "#8d9071", "#b97e6c"]
    for index, building in enumerate(result.buildings):
        local = result.frame.to_local(building.footprint)
        color = _rgba(generated_palette[index % len(generated_palette)])
        _draw_geom(raster, local, convert, color, outline=_rgba("#5e5146"), hole_color=_rgba("#a9c998"), line_width=1)
        point = convert(local.representative_point().x, local.representative_point().y)
        label = _TYPE_LABELS.get(building.dictionary_type_id, "TYPE")
        if scale * min(local.bounds[2] - local.bounds[0], local.bounds[3] - local.bounds[1]) >= 16:
            raster.text(point[0] - len(label) * 2, point[1] - 3, label, _rgba("#302b28"), 1)
    for index, building in enumerate(result.preserved_buildings):
        local = result.frame.to_local(building.geometry)
        _draw_geom(raster, local, convert, _rgba("#55423d"), outline=_rgba("#302623"), line_width=2)
        point = convert(local.representative_point().x, local.representative_point().y)
        design_label = "/".join(str(value) for value in building.source_design_numbers) or str(index + 1)
        floor_label = f"{building.floor_count}F" if building.floor_count is not None else "?F"
        raster.text(point[0] - 10, point[1] - 4, f"P{design_label}-{floor_label}", _rgba("#ffffff"), 1)
    # North arrow: north is rotated into the local frame along the inverse axis.
    arrow_origin = (rect[2] - 54, rect[1] + 56)
    angle = math.radians(result.frame.orientation_deg)
    vector = (-math.sin(angle), math.cos(angle))
    tip = (round(arrow_origin[0] + vector[0] * 28), round(arrow_origin[1] - vector[1] * 28))
    raster.line(arrow_origin, tip, _rgba("#243746"), 3)
    raster.line(tip, (tip[0] - 6, tip[1] + 10), _rgba("#243746"), 3)
    raster.line(tip, (tip[0] + 6, tip[1] + 10), _rgba("#243746"), 3)
    raster.text(tip[0] - 3, tip[1] - 18, "N", _rgba("#243746"), 2)
    if legend:
        y = rect[3] + 16
        items = (("MAIN", "#c45e38"), ("SECONDARY", "#d49a45"), ("ALLEY", "#89959a"), ("QUAY 6M", "#32877d"), ("PRESERVED / STOREYS", "#55423d"))
        x = rect[0]
        for label, color in items:
            raster.line((x, y + 4), (x + 18, y + 4), _rgba(color), 4)
            raster.text(x + 24, y, label, _rgba("#334047"), 1)
            x += 27 + 6 * (len(label) + 2)


def render_plan_png(result: ScenarioResult, path: str | Path) -> None:
    raster = _Raster(1400, 900, _rgba("#faf9f6"))
    raster.text(32, 24, f"{result.intensity.code} {result.recipe['id']}  AXIS {result.frame.orientation_deg:.1f}  FAR {result.metrics['far_land_area']['known_value']:.3f}", _rgba("#243746"), 2)
    _draw_plan(raster, result, (70, 90, 1320, 790), legend=True)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raster.png())


def _iso_point(x: float, y: float, z: float, center_x: float, center_y: float, scale: float) -> tuple[float, float]:
    return ((x - y) * 0.72 * scale, (x + y) * 0.36 * scale - z * 2.4 * scale)


def render_axonometric_png(result: ScenarioResult, path: str | Path) -> None:
    raster = _Raster(1400, 900, _rgba("#faf9f6"))
    area = result.frame.to_local(result.inputs.design_area)
    min_x, min_y, max_x, max_y = area.bounds
    scale = min(0.98, 1100.0 / max((max_x - min_x + max_y - min_y) * 0.72, 1.0))
    projected = []
    for x in (min_x, max_x):
        for y in (min_y, max_y):
            projected.append(_iso_point(x, y, 0.0, 0, 0, scale))
    for building in result.buildings:
        local_footprint = result.frame.to_local(building.footprint)
        for polygon in _polygon_parts(local_footprint):
            projected.extend(_iso_point(x, y, building.height_m, 0, 0, scale) for x, y, *_ in polygon.exterior.coords)
    min_sx, max_sx = min(p[0] for p in projected), max(p[0] for p in projected)
    min_sy, max_sy = min(p[1] for p in projected), max(p[1] for p in projected)
    x_offset = (raster.width - (max_sx - min_sx)) / 2.0 - min_sx
    y_offset = 110 - min_sy
    def convert(x: float, y: float, z: float = 0.0) -> tuple[int, int]:
        sx, sy = _iso_point(x, y, z, 0, 0, scale)
        return round(sx + x_offset), round(sy + y_offset)
    raster.text(32, 24, f"AXONOMETRIC  {result.intensity.code} {result.recipe['id']}  VERTICAL SCALE 2.4", _rgba("#243746"), 2)
    local_water = result.frame.to_local(result.inputs.water_geometry)
    _draw_geom(raster, local_water, lambda x, y: convert(x, y), _rgba("#82b4c1"), outline=_rgba("#4d8793"), line_width=1)
    for road in result.roads:
        local = result.frame.to_local(road.geometry)
        color = _rgba("#c45e38" if road.road_class == "main" else "#d49a45" if road.road_class == "secondary" else "#32877d" if road.road_class == "quay_promenade" else "#89959a")
        for line in _line_parts(local):
            coords = [convert(x, y) for x, y, *_ in line.coords]
            for first, second in zip(coords, coords[1:]):
                raster.line(first, second, color, max(1, round(road.width_m * scale * 0.55)))
    buildings_to_draw = []
    for building in result.preserved_buildings:
        local = result.frame.to_local(building.geometry)
        buildings_to_draw.append((local, float(building.height_m or 0.0), "#66534d", building.floor_count))
    for building in result.buildings:
        buildings_to_draw.append((result.frame.to_local(building.footprint), float(building.height_m), "#b58a65", building.floor_count))
    buildings_to_draw.sort(key=lambda item: sum(convert(item[0].centroid.x, item[0].centroid.y, item[1] / 2.0)))
    for footprint, height, color_text, floor_count in buildings_to_draw:
        color = _rgba(color_text)
        top_color = tuple(max(0, min(255, int(component * 1.08))) for component in color)
        polygons = _polygon_parts(footprint)
        for polygon in polygons:
            coords = list(polygon.exterior.coords)[:-1]
            if height > 0:
                for first, second in zip(coords, coords[1:] + coords[:1]):
                    wall = [convert(first[0], first[1]), convert(second[0], second[1]), convert(second[0], second[1], height), convert(first[0], first[1], height)]
                    raster.polygon((wall,), tuple(max(0, int(value * 0.82)) for value in color))
            top_rings = [[convert(x, y, height) for x, y, *_ in polygon.exterior.coords[:-1]]]
            for interior in polygon.interiors:
                top_rings.append([convert(x, y, height) for x, y, *_ in interior.coords[:-1]])
            raster.polygon(top_rings, top_color)
            top_coords = [convert(x, y, height) for x, y, *_ in polygon.exterior.coords]
            for first, second in zip(top_coords, top_coords[1:]):
                raster.line(first, second, _rgba("#594a40"), 1)
        center = convert(footprint.centroid.x, footprint.centroid.y, height)
        raster.text(center[0] - 7, center[1] - 3, f"{floor_count}F" if floor_count is not None else "?F", _rgba("#302b28"), 1)
    raster.text(38, 850, "SCHEMATIC MASSING  |  EXTRUSION USES RECORDED FLOORS AND HEIGHTS", _rgba("#596970"), 1)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raster.png())


def _comparison_png(results: Sequence[ScenarioResult], path: Path) -> None:
    raster = _Raster(1900, 1120, _rgba("#faf9f6"))
    raster.text(32, 24, "DICTIONARY GENERATOR V4  |  A AND B STRATEGY COMPARISON", _rgba("#243746"), 2)
    colors = {"main": _rgba("#c45e38"), "secondary": _rgba("#d49a45"), "alley": _rgba("#89959a"), "quay_promenade": _rgba("#32877d")}
    for index, result in enumerate(results):
        col, row = index % 5, index // 5
        left, top = 20 + col * 376, 72 + row * 514
        right, bottom = left + 350, top + 468
        raster.text(left, top, f"{result.intensity.code} {result.recipe['id']}", _rgba("#243746"), 1)
        raster.text(left, top + 14, f"FAR {result.metrics['far_land_area']['known_value']:.3f}  OPEN {result.metrics['open_space_ratio']['value']:.2f}  {'VALID' if result.valid else 'INVALID'}", _rgba("#485a61"), 1)
        local_area = result.frame.to_local(result.inputs.design_area)
        convert, scale = _screen_transform(local_area.bounds, (left + 8, top + 32, right - 8, bottom - 30))
        _draw_geom(raster, local_area, convert, _rgba("#efece4"), outline=_rgba("#243746"), line_width=1)
        _draw_geom(raster, result.frame.to_local(result.inputs.water_geometry), convert, _rgba("#82b4c1"), outline=None)
        for road in result.roads:
            for line in _line_parts(result.frame.to_local(road.geometry)):
                coords = [convert(x, y) for x, y, *_ in line.coords]
                for first, second in zip(coords, coords[1:]):
                    raster.line(first, second, colors[road.road_class], max(1, round(road.width_m * scale)))
        for building in result.buildings:
            _draw_geom(raster, result.frame.to_local(building.footprint), convert, _rgba("#b58a65"), outline=_rgba("#594a40"), hole_color=_rgba("#a9c998"), line_width=1)
        for retained in result.preserved_buildings:
            _draw_geom(raster, result.frame.to_local(retained.geometry), convert, _rgba("#55423d"), outline=_rgba("#302623"), line_width=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raster.png())


def _scenario_metrics_record(result: ScenarioResult) -> dict[str, Any]:
    return {
        "scenario_id": f"{result.intensity.code}-{result.recipe['id']}-seed-{result.seed}",
        "strategy_id": result.recipe["id"],
        "intensity": result.intensity.code,
        "scenario_hash": result.scenario_hash,
        "valid": result.valid,
        "failure_reasons": list(result.validation["failure_reasons"]),
        "warnings": list(result.validation["warnings"]),
        "land_far": result.metrics["far_land_area"]["known_value"],
        "coverage_ratio": result.metrics["coverage_ratio"]["value"],
        "maximum_height_m": result.metrics["maximum_height_m"]["known_all_building_m"],
        "open_space_ratio": result.metrics["open_space_ratio"]["value"],
        "external_contacts": result.metrics["external_contacts"],
        "type_composition": result.metrics["typology_composition"],
        "building_count": result.metrics["building_count"],
        "strategy_label": result.recipe["label_zh"],
    }


def write_scenario(result: ScenarioResult, output_dir: str | Path) -> dict[str, Any]:
    target = Path(output_dir)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"scenario output directory is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    render_plan_png(result, target / "plan.png")
    render_axonometric_png(result, target / "axonometric.png")
    _write_json(target / "scenario.geojson", scenario_geojson(result))
    metrics = {
        "scenario_id": f"{result.intensity.code}-{result.recipe['id']}-seed-{result.seed}",
        "scenario_hash": result.scenario_hash,
        "scenario_status": "UNAPPROVED_PREVIEW",
        "human_decision_created": False,
        "valid": result.valid,
        "intensity": {
            "code": result.intensity.code,
            "far_upper_bound_land": result.intensity.far_upper_bound,
            "height_upper_bound_new_buildings_m": result.intensity.height_upper_bound_m,
            "coverage_upper_bound": result.intensity.coverage_upper_bound,
        },
        "orientation": result.metadata["orientation"],
        "metrics": dict(result.metrics),
        "validation": dict(result.validation),
        "generation_metadata": dict(result.metadata),
    }
    _write_json(target / "metrics.json", metrics)
    recipe_copy = dict(result.recipe)
    recipe_copy["run"] = {
        "seed": result.seed,
        "intensity": result.intensity.code,
        "scenario_hash": result.scenario_hash,
        "selected_building_type_ids": sorted({item.dictionary_type_id for item in result.buildings}),
        "selected_block_assembly_type_ids": sorted({item.assembly_type_id for item in result.blocks}),
    }
    _write_json(target / "recipe.json", recipe_copy)
    record = _scenario_metrics_record(result)
    record["artifact_hashes"] = {
        name: _sha256_bytes((target / name).read_bytes())
        for name in ("plan.png", "axonometric.png", "scenario.geojson", "metrics.json", "recipe.json")
    }
    return record


def run_dictionary_generator(
    output_dir: str | Path,
    *,
    root: str | Path | None = None,
    study_area_path: str | Path | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Run all five recipes for intensities A and B into an append-only run path."""
    project_root = Path(root).resolve() if root is not None else _ROOT
    inputs = load_generator_inputs(project_root, study_area_path=study_area_path)
    intensities = load_intensities(project_root)
    recipes = load_recipes(project_root / "config" / "morphology-recipes")
    dictionary = load_dictionary(project_root / "config" / "morphology-dictionary")
    if len(recipes) != 5:
        raise DictionaryGenerationError(f"expected exactly five morphology recipes, found {len(recipes)}")
    destination = Path(output_dir).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"run output directory is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    results: list[ScenarioResult] = []
    for code in ("A", "B"):
        for recipe_id, recipe in sorted(recipes.items()):
            results.append(generate_scenario(inputs, recipe, intensity=intensities[code], seed=seed, dictionary=dictionary))
    for result in results:
        records.append(write_scenario(result, destination / result.intensity.code / str(result.recipe["id"])))
    comparison = {
        "schema_version": "dictionary-generator-comparison-v1",
        "generator_version": GENERATOR_VERSION,
        "run_status": "UNAPPROVED_PREVIEW",
        "human_decision_created": False,
        "seed": seed,
        "study_area": inputs.source_provenance.get("study_area", {}),
        "strategy_count": len(records),
        "valid_count_by_intensity": {
            code: sum(row["valid"] for row in records if row["intensity"] == code)
            for code in ("A", "B")
        },
        "strategies": records,
        "overall_winner": None,
        "decision_rule": None,
        "limitations": [
            "Zone/open-space geometries are portfolio transcription preferences, not statutory controls.",
            "Morphology atmosphere scores are editorial retrieval estimates; no comfort, daylight, wind, access, or performance simulation was run.",
            "FAR is land-denominator known-part FAR; retained buildings with unknown floors are disclosed separately.",
            "Generation outputs are unapproved proposals and do not create HumanDecision state.",
        ],
    }
    _write_json(destination / "comparison.json", comparison)
    _comparison_png(results, destination / "comparison.png")
    manifest_files = {}
    for path in sorted(item for item in destination.rglob("*") if item.is_file()):
        relative = path.relative_to(destination).as_posix()
        manifest_files[relative] = {
            "sha256": _sha256_bytes(path.read_bytes()),
            "size_bytes": path.stat().st_size,
        }
    _write_json(destination / "artifact-manifest.json", {
        "schema_version": "dictionary-generator-artifact-manifest-v1",
        "algorithm": "SHA-256",
        "manifest_excludes_self": True,
        "files": manifest_files,
    })
    return comparison


def generate_profile_geometry_v5(
    type_id: str,
    site_geometry: BaseGeometry,
    parameters: Mapping[str, Any],
    *,
    crs: str,
    coordinate_unit: str,
    preserved_obstacles: Sequence[BaseGeometry] = (),
):
    """Versioned adapter entry point for the post-v4 morphology registry.

    Existing ``generate_scenario`` and its v4 replay path remain unchanged.
    """

    from urban_design.generation.type_registry import generate_profile_geometry

    return generate_profile_geometry(
        type_id,
        site_geometry,
        parameters,
        crs=crs,
        coordinate_unit=coordinate_unit,
        preserved_obstacles=tuple(preserved_obstacles),
    )


__all__ = [
    "ACTIVE_STUDY_AREA_GEOMETRY_SHA256",
    "ACTIVE_STUDY_AREA_ID",
    "BLOCK_MAX_SIDE_M",
    "BLOCK_MIN_SIDE_M",
    "CONTACT_RULES_VERSION",
    "CRS",
    "DictionaryGenerationError",
    "ExternalContact",
    "GeneratedBuilding",
    "GeneratedRoad",
    "GeneratorInputs",
    "IntensitySpec",
    "OrientationFrame",
    "PreservedBuilding",
    "ScenarioResult",
    "ZonePreference",
    "derive_orientation",
    "generate_scenario",
    "generate_profile_geometry_v5",
    "load_generator_inputs",
    "load_intensities",
    "load_recipes",
    "render_axonometric_png",
    "render_plan_png",
    "run_dictionary_generator",
    "scenario_geojson",
    "validate_road_orthogonality",
    "write_scenario",
]


def run_fixture_dictionary_pipeline(
    context: "GenerationContext", site_geometry: "AreaGeometryValue",
    skeletons: "tuple[SkeletonArtifact, ...]", recipes: "tuple[FixtureDictionaryRecipe, ...]",
    *, water_geometry: "AreaGeometryValue | None" = None,
    retained_buildings: "tuple[FixtureRetainedBuilding, ...]" = (),
) -> "FixturePipelineResult":
    """W6-06 typed fixture entry; v4 historical previews retain their authority.

    This adapter creates no Scenario or HumanDecision. Approved context remains
    BLOCKED until the W6-3 resolver and Founder kernel/dictionary decisions.
    """
    from urban_design.generation.massing_adapter import run_fixture_dictionary_pipeline as generate_fixture
    return generate_fixture(context, site_geometry, skeletons, recipes,
                            water_geometry=water_geometry, retained_buildings=retained_buildings)


__all__.append("run_fixture_dictionary_pipeline")
