"""Deterministic, same-version observational cards for Week 4 R03.

The cards describe geometry present in verified spatial-r01 inputs. They do not
establish land use, ownership, legal access, pedestrian passability, or policy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import shape
from shapely.ops import unary_union

from .store import EntityNotFoundError, ProjectStateStore
from .workspace_sources import WorkspaceSourceCatalog, WorkspaceSourceError


class EvidenceAlignmentError(ValueError):
    """The card bundle does not match current, verified source/result parents."""


SOURCE_ALIGNED_COVERAGE_LIMITED = "SOURCE_ALIGNED_COVERAGE_LIMITED"
LEGACY_VERIFIED_OBSERVATION = "VERIFIED_OBSERVATION"


class EvidenceCardRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    card_id: str = Field(min_length=1)
    metric_key: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    value: float | int
    unit: str = Field(min_length=1)
    status: str
    confidence: str
    source: str
    timestamp: str
    crs: str
    query_bounds: list[dict[str, Any]]
    algorithm_version: str
    input_sha256: str
    output_sha256: str
    source_package_id: str
    source_package_revision: str
    study_area_id: str
    study_area_revision: int
    study_area_geometry_sha256: str
    source_feature_ids: list[str]
    source_artifact_ids: list[str]
    dataset_snapshot_ids: list[str]
    parents: list[dict[str, Any]]
    limitations: list[str]
    method_definition: str | None = None
    method_diagnostics: dict[str, float] | None = None


class EvidenceBundleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str
    status: str
    scope: dict[str, Any]
    cards: list[EvidenceCardRecord]
    evidence_gaps: list[dict[str, str]]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _bundle_with_legacy_status_normalized(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize only the retired card label when comparing retained bundles."""
    normalized = dict(bundle)
    cards = normalized.get("cards")
    if isinstance(cards, list):
        normalized["cards"] = [
            {
                **dict(card),
                "status": SOURCE_ALIGNED_COVERAGE_LIMITED,
            } if isinstance(card, Mapping) and card.get("status") == LEGACY_VERIFIED_OBSERVATION else card
            for card in cards
        ]
    return normalized


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _recorded_hash(value: Any) -> str:
    return str(value or "").removeprefix("sha256:")


def _artifact_record(catalog: WorkspaceSourceCatalog, artifact_id: str) -> dict[str, Any]:
    record = catalog.normalized_artifacts.get(artifact_id) or catalog.raw_artifacts.get(artifact_id)
    if not isinstance(record, Mapping):
        raise EvidenceAlignmentError(f"parent Artifact {artifact_id!r} is missing from the verified source package")
    uri = str(record.get("uri") or "")
    if not uri:
        raise EvidenceAlignmentError(f"parent Artifact {artifact_id!r} has no source path")
    path = (catalog.package_root / uri).resolve()
    if catalog.package_root.resolve() not in path.parents:
        raise EvidenceAlignmentError(f"parent Artifact {artifact_id!r} escapes the source package")
    if not path.is_file():
        raise EvidenceAlignmentError(f"parent Artifact file is missing: {uri}")
    actual_sha = _sha256_file(path)
    actual_size = path.stat().st_size
    if _recorded_hash(record.get("sha256")) != actual_sha.removeprefix("sha256:"):
        raise EvidenceAlignmentError(f"parent Artifact {artifact_id!r} hash differs from spatial-r01")
    if record.get("size_bytes") != actual_size:
        raise EvidenceAlignmentError(f"parent Artifact {artifact_id!r} size differs from spatial-r01")
    return {
        "entity_type": "Artifact",
        "id": artifact_id,
        "path": f"spatial-r01/{uri}",
        "sha256": actual_sha,
        "size_bytes": actual_size,
        "crs": record.get("crs"),
        "parent_artifact_ids": sorted(str(item) for item in record.get("parent_artifact_ids", [])),
    }


def _snapshot_record(catalog: WorkspaceSourceCatalog, snapshot_id: str) -> dict[str, Any]:
    record = catalog.snapshots.get(snapshot_id)
    if not isinstance(record, Mapping):
        raise EvidenceAlignmentError(f"parent DatasetSnapshot {snapshot_id!r} is missing from spatial-r01")
    return {
        "entity_type": "DatasetSnapshot",
        "id": snapshot_id,
        "sha256": record.get("sha256"),
        "source_url": record.get("source_url"),
        "publisher": record.get("publisher"),
        "license": record.get("license"),
        "retrieved_at": record.get("retrieved_at"),
        "version": record.get("version"),
        "raw_artifact_id": record.get("raw_artifact_id"),
        "normalized_artifact_id": record.get("normalized_artifact_id"),
        "query": record.get("query"),
        "parameters": record.get("parameters"),
    }


def _parents_for_normalized_artifacts(
    catalog: WorkspaceSourceCatalog,
    artifact_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_ids = sorted(set(artifact_ids))
    raw_ids: set[str] = set()
    snapshots: list[dict[str, Any]] = []
    artifact_records: list[dict[str, Any]] = []
    snapshot_by_normalized = {
        str(item.get("normalized_artifact_id")): str(item.get("id"))
        for item in catalog.snapshots.values()
    }
    for artifact_id in normalized_ids:
        artifact = catalog.normalized_artifacts.get(artifact_id)
        if artifact is None:
            raise EvidenceAlignmentError(f"parent normalized Artifact {artifact_id!r} is missing")
        artifact_records.append(_artifact_record(catalog, artifact_id))
        raw_ids.update(str(value) for value in artifact.get("parent_artifact_ids", []))
        snapshot_id = snapshot_by_normalized.get(artifact_id)
        if not snapshot_id:
            raise EvidenceAlignmentError(f"normalized Artifact {artifact_id!r} has no DatasetSnapshot parent")
        snapshots.append(_snapshot_record(catalog, snapshot_id))
    for artifact_id in sorted(raw_ids):
        artifact_records.append(_artifact_record(catalog, artifact_id))
    artifact_records.sort(key=lambda item: item["id"])
    snapshots.sort(key=lambda item: item["id"])
    bounds = {
        _canonical_bytes(item.get("parameters", {}).get("query_bounds")): item.get("parameters", {}).get("query_bounds")
        for item in snapshots
        if isinstance(item.get("parameters"), Mapping)
        and item.get("parameters", {}).get("query_bounds") is not None
    }
    return artifact_records, snapshots, [bounds[key] for key in sorted(bounds)]


def _make_card(
    *,
    metric_key: str,
    metric_name: str,
    value: float | int,
    unit: str,
    source: str,
    feature_ids: Sequence[str],
    artifacts: Sequence[dict[str, Any]],
    snapshots: Sequence[dict[str, Any]],
    query_bounds: Sequence[dict[str, Any]],
    scope: Mapping[str, Any],
    input_material: Mapping[str, Any],
    limitations: Sequence[str],
) -> dict[str, Any]:
    algorithm_version = "r03-observed-geometry-v1"
    input_sha = _sha256_bytes(_canonical_bytes(input_material))
    output_sha = _sha256_bytes(_canonical_bytes({
        "metric_key": metric_key,
        "value": value,
        "unit": unit,
        "algorithm_version": algorithm_version,
        "input_sha256": input_sha,
    }))
    card_id = f"card-r03-{metric_key}-{hashlib.sha256((input_sha + output_sha).encode()).hexdigest()[:16]}"
    feature_ids = sorted(set(str(item) for item in feature_ids))
    snapshot_ids = sorted(str(item["id"]) for item in snapshots)
    retrieved = [str(item.get("retrieved_at")) for item in snapshots if item.get("retrieved_at")]
    card = {
        "card_id": card_id,
        "metric_key": metric_key,
        "metric_name": metric_name,
        "value": value,
        "unit": unit,
        "status": SOURCE_ALIGNED_COVERAGE_LIMITED,
        "confidence": "OBSERVATIONAL_ONLY",
        "source": source,
        "timestamp": max(retrieved) if retrieved else "UNKNOWN_SOURCE_TIME",
        "crs": "EPSG:28992",
        "query_bounds": list(query_bounds),
        "algorithm_version": algorithm_version,
        "input_sha256": input_sha,
        "output_sha256": output_sha,
        "source_package_id": scope["source_package_id"],
        "source_package_revision": scope["source_package_revision"],
        "study_area_id": scope["study_area_id"],
        "study_area_revision": scope["study_area_revision"],
        "study_area_geometry_sha256": scope["study_area_geometry_sha256"],
        "source_feature_ids": feature_ids,
        "source_artifact_ids": sorted({
            str(parent["id"]) for parent in artifacts
            if parent.get("entity_type") == "Artifact"
            and str(parent["id"]).endswith("-normalized-3390e215019805a1")
        }),
        "dataset_snapshot_ids": snapshot_ids,
        "parents": [*artifacts, *snapshots],
        "limitations": list(limitations),
    }
    # Include all relevant source Artifacts, including raw parents, in the source list.
    card["source_artifact_ids"] = sorted({str(parent["id"]) for parent in artifacts if parent.get("entity_type") == "Artifact"})
    return EvidenceCardRecord.model_validate(card).model_dump(mode="json", exclude_none=True)


def _water_features(catalog: WorkspaceSourceCatalog) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    records = [
        (artifact_id, record)
        for artifact_id, record in catalog.normalized_artifacts.items()
        if "/pdok-bgt-waterdeel-" in str(record.get("uri", ""))
    ]
    if not records:
        raise EvidenceAlignmentError("verified spatial-r01 has no BGT waterdeel source Artifact")
    selected_geometries = []
    selected_ids: list[str] = []
    artifact_ids: list[str] = []
    for artifact_id, record in sorted(records):
        artifact_ids.append(artifact_id)
        parent = _artifact_record(catalog, artifact_id)
        if parent.get("crs") != "EPSG:28992":
            raise EvidenceAlignmentError("BGT water source CRS is not EPSG:28992")
        path = catalog.package_root / str(record["uri"])
        document = json.loads(path.read_text(encoding="utf-8"))
        crs = (document.get("crs") or {}).get("properties", {}).get("name")
        if crs not in ("EPSG:28992", "urn:ogc:def:crs:EPSG::28992"):
            raise EvidenceAlignmentError("BGT water GeoJSON declares an unexpected CRS")
        for feature in document.get("features", []):
            raw_geometry = feature.get("geometry")
            if not isinstance(raw_geometry, Mapping):
                raise EvidenceAlignmentError("BGT water feature has no geometry")
            try:
                geometry = shape(raw_geometry)
            except Exception as exc:
                raise EvidenceAlignmentError("BGT water feature geometry cannot be decoded") from exc
            if geometry.is_empty or not geometry.is_valid:
                raise EvidenceAlignmentError("BGT water feature geometry is empty or invalid")
            if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                continue
            if geometry.intersects(catalog.study_area_shape):
                feature_id = str(feature.get("id") or (feature.get("properties") or {}).get("lokaal_id") or "")
                if not feature_id:
                    raise EvidenceAlignmentError("intersecting BGT water feature has no stable source identifier")
                clipped = geometry.intersection(catalog.study_area_shape)
                if not clipped.is_empty:
                    selected_geometries.append(clipped)
                    selected_ids.append(feature_id)
    if len(selected_ids) != len(set(selected_ids)):
        raise EvidenceAlignmentError("duplicate BGT water feature IDs prevent a deterministic observation")
    return selected_geometries, selected_ids, artifact_ids


def build_observational_evidence_bundle(
    catalog: WorkspaceSourceCatalog,
    store: ProjectStateStore,
) -> dict[str, Any]:
    """Build deterministic cards from verified current source geometries only."""
    try:
        project_record = store.current(catalog.project_id)
        area_record = store.current(catalog.study_area_id)
    except EntityNotFoundError as exc:
        raise EvidenceAlignmentError("active project or StudyArea record is missing") from exc
    if project_record.payload.get("active_study_area_id") != catalog.study_area_id:
        raise EvidenceAlignmentError("source package does not match the current active StudyArea")
    if area_record.payload.get("status") != "CONFIRMED_FOR_EXPLORATION":
        raise EvidenceAlignmentError("active StudyArea is not confirmed for exploration")
    if area_record.payload.get("geometry_sha256") != catalog.study_area_geometry_sha256:
        raise EvidenceAlignmentError("active StudyArea geometry hash differs from source package")

    scope = {
        "project_id": catalog.project_id,
        "project_revision": project_record.revision,
        "study_area_id": catalog.study_area_id,
        "study_area_revision": area_record.revision,
        "study_area_geometry_sha256": catalog.study_area_geometry_sha256,
        "source_package_id": catalog.package_id,
        "source_package_revision": catalog.package_revision,
        "crs": "EPSG:28992",
        "units": "metres",
    }
    cards: list[dict[str, Any]] = []

    # BAG polygon features are clipped to the confirmed StudyArea before area
    # aggregation; unary_union prevents overlapping footprints being double-counted.
    building_geometries = [
        shape(item.geometry).intersection(catalog.study_area_shape)
        for item in catalog.buildings
    ]
    building_union = unary_union([item for item in building_geometries if not item.is_empty])
    building_area = round(float(building_union.area), 6)
    site_area = float(catalog.study_area_shape.area)
    if site_area <= 0:
        raise EvidenceAlignmentError("active StudyArea has no positive area")
    building_pct = round((building_area / site_area) * 100.0, 6)
    bag_artifact_ids = sorted({
        artifact_id for artifact_id, record in catalog.normalized_artifacts.items()
        if "/pdok-bag-pand-" in str(record.get("uri", ""))
    })
    bag_artifacts, bag_snapshots, bag_bounds = _parents_for_normalized_artifacts(catalog, bag_artifact_ids)
    building_ids = [item.feature_id for item in catalog.buildings]
    building_inputs = {
        "scope": scope,
        "features": [
            {"id": item.feature_id, "artifact_id": item.source_artifact_id, "geometry": item.geometry}
            for item in catalog.buildings
        ],
        "parents": bag_artifacts,
        "study_area_geometry": catalog.study_area_geometry,
    }
    bag_limitations = [
        "BAG pand footprints are observed geometry, not occupied floor area, building use, condition, ownership, or buildability.",
        "The source queries use a bounded 1200 m envelope; this card does not establish completeness outside the retained acquisition scope.",
        "Area is the union of valid footprint intersections with the confirmed StudyArea; it is not a regulatory coverage ratio.",
    ]
    for metric_key, metric_name, value, unit in (
        ("bag_building_footprint_count", "BAG building footprint features", len(building_ids), "features"),
        ("bag_building_footprint_area", "BAG footprint area inside StudyArea", building_area, "m²"),
        ("bag_building_footprint_share", "BAG footprint share of StudyArea", building_pct, "%"),
    ):
        cards.append(_make_card(
            metric_key=metric_key,
            metric_name=metric_name,
            value=value,
            unit=unit,
            source="PDOK / Kadaster BAG pand normalized geometry in spatial-r01",
            feature_ids=building_ids,
            artifacts=bag_artifacts,
            snapshots=bag_snapshots,
            query_bounds=bag_bounds,
            scope=scope,
            input_material=building_inputs,
            limitations=bag_limitations,
        ))

    road_artifact_ids = sorted({item.source_artifact_id for item in catalog.roads})
    road_artifacts, road_snapshots, road_bounds = _parents_for_normalized_artifacts(catalog, road_artifact_ids)
    clipped_road_lengths = [
        shape(item.geometry).intersection(catalog.study_area_shape).length
        for item in catalog.roads
    ]
    road_length = round(float(sum(clipped_road_lengths)), 6)
    road_inputs = {
        "scope": scope,
        "features": [
            {"id": item.feature_id, "artifact_id": item.source_artifact_id, "geometry": item.geometry}
            for item in catalog.roads
        ],
        "parents": road_artifacts,
        "study_area_geometry": catalog.study_area_geometry,
    }
    cards.append(_make_card(
        metric_key="osm_highway_centerline_length",
        metric_name="OSM highway centerline length inside StudyArea",
        value=road_length,
        unit="m",
        source="OpenStreetMap contributors via retained Overpass spatial-r01 snapshot",
        feature_ids=[item.source_feature_id for item in catalog.roads],
        artifacts=road_artifacts,
        snapshots=road_snapshots,
        query_bounds=road_bounds,
        scope=scope,
        input_material=road_inputs,
        limitations=[
            "This is clipped centerline geometry length, not a connected pedestrian graph, public right of way, access permission, passability, safety, or travel time.",
            "The retained OSM acquisition is bounded; no regional completeness or radius-stability claim is made.",
            "Road classification is the retained OSM highway tagging and does not establish a transport-mode policy.",
        ],
    ))

    water_geometries, water_ids, water_artifact_ids = _water_features(catalog)
    water_artifacts, water_snapshots, water_bounds = _parents_for_normalized_artifacts(catalog, water_artifact_ids)
    water_union = unary_union(water_geometries) if water_geometries else None
    water_area = round(float(water_union.area), 6) if water_union is not None else 0.0
    water_inputs = {
        "scope": scope,
        "features": sorted(water_ids),
        "parents": water_artifacts,
        "study_area_geometry": catalog.study_area_geometry,
    }
    cards.append(_make_card(
        metric_key="bgt_waterdeel_area",
        metric_name="BGT waterdeel polygon area inside StudyArea",
        value=water_area,
        unit="m²",
        source="PDOK / Kadaster BGT waterdeel normalized geometry in spatial-r01",
        feature_ids=water_ids,
        artifacts=water_artifacts,
        snapshots=water_snapshots,
        query_bounds=water_bounds,
        scope=scope,
        input_material=water_inputs,
        limitations=[
            "This is observed waterdeel polygon overlap, not a hydrological, flood, ownership, access, or legal-water-boundary conclusion.",
            "The retained input is a single bounded BGT query and does not establish completeness beyond its recorded acquisition envelope.",
        ],
    ))

    cards.sort(key=lambda item: item["metric_key"])
    return EvidenceBundleRecord.model_validate({
        "schema_version": "week4-r03-evidence-bundle-v1",
        "status": "VERIFIED_SOURCE_RESULT_ALIGNMENT",
        "scope": scope,
        "cards": cards,
        "evidence_gaps": [
            {"topic": "land use and occupancy", "status": "UNKNOWN", "reason": "No verified same-version land-use or occupancy source is part of spatial-r01."},
            {"topic": "ownership and property rights", "status": "UNKNOWN", "reason": "Building and water geometry does not establish ownership or property rights."},
            {"topic": "public access and pedestrian passability", "status": "UNKNOWN", "reason": "OSM highway centerlines do not establish public rights, barriers, crossings, or passability."},
            {"topic": "accessibility policy", "status": "BLOCKED", "reason": "Origin denominator, destination taxonomy, and pedestrian-network policy remain unapproved."},
            {"topic": "Space Syntax coverage", "status": "BLOCKED", "reason": "The retained 800 m calculations lack a verified acquisition envelope and radius-stability evidence."},
        ],
    }).model_dump(mode="json", exclude_none=True)


def validate_observational_evidence_bundle(
    candidate: Mapping[str, Any],
    catalog: WorkspaceSourceCatalog,
    store: ProjectStateStore,
) -> list[dict[str, Any]]:
    """Recompute all card inputs and reject stale, missing, or fabricated parents."""
    expected = build_observational_evidence_bundle(catalog, store)
    scope = candidate.get("scope") if isinstance(candidate, Mapping) else None
    if not isinstance(scope, Mapping) or scope.get("source_package_id") != expected["scope"]["source_package_id"]:
        raise EvidenceAlignmentError("source package identity does not match the current verified source package")
    if scope.get("source_package_revision") != expected["scope"]["source_package_revision"]:
        raise EvidenceAlignmentError("source package revision does not match the current verified source package")
    if scope.get("study_area_id") != expected["scope"]["study_area_id"] or scope.get("study_area_revision") != expected["scope"]["study_area_revision"]:
        raise EvidenceAlignmentError("StudyArea revision does not match current project state")
    candidate_cards = candidate.get("cards")
    expected_cards = {item["card_id"]: item for item in expected["cards"]}
    if not isinstance(candidate_cards, list):
        raise EvidenceAlignmentError("Evidence Card list is missing")
    for card in candidate_cards:
        if not isinstance(card, Mapping):
            raise EvidenceAlignmentError("Evidence Card record is invalid")
        expected_card = expected_cards.get(str(card.get("card_id", "")))
        if expected_card is None:
            raise EvidenceAlignmentError("Evidence Card ID is unverified for the current source package")
        if card.get("unit") != expected_card["unit"]:
            raise EvidenceAlignmentError(f"Evidence Card {card.get('card_id')} unit does not match its method")
        for field in ("source_artifact_ids", "dataset_snapshot_ids", "parents"):
            if card.get(field) != expected_card[field]:
                raise EvidenceAlignmentError(f"Evidence Card {card.get('card_id')} parent lineage is missing or mismatched")
    if _bundle_with_legacy_status_normalized(candidate).get("cards") != expected["cards"]:
        raise EvidenceAlignmentError("Evidence Card result, revision, method, or parent hash differs from deterministic recomputation")
    if candidate.get("scope") != expected["scope"]:
        raise EvidenceAlignmentError("Evidence bundle scope differs from current project state")
    if candidate.get("evidence_gaps") != expected["evidence_gaps"]:
        raise EvidenceAlignmentError("Evidence bundle unknown and blocked gates differ from the current contract")
    if candidate.get("schema_version") != expected["schema_version"] or candidate.get("status") != expected["status"]:
        raise EvidenceAlignmentError("Evidence bundle schema or alignment status is invalid")
    try:
        EvidenceBundleRecord.model_validate(candidate)
    except Exception as exc:
        raise EvidenceAlignmentError("Evidence bundle typed contract validation failed") from exc
    return [dict(item) for item in candidate_cards]


def select_verified_cards(cards: Sequence[Mapping[str, Any]], card_ids: Sequence[str]) -> list[dict[str, Any]]:
    if len(card_ids) != len(set(card_ids)):
        raise EvidenceAlignmentError("duplicate Evidence Card IDs are not allowed")
    accepted_statuses = {LEGACY_VERIFIED_OBSERVATION, SOURCE_ALIGNED_COVERAGE_LIMITED}
    index = {str(card.get("card_id")): card for card in cards if card.get("status") in accepted_statuses}
    if any(card_id not in index for card_id in card_ids):
        raise EvidenceAlignmentError("requested Evidence Card ID is unverified or stale")
    return [dict(index[card_id]) for card_id in card_ids]
