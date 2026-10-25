"""Validation helpers for the repaired M2 Delft proposal (v2).

The v2 layer is deliberately additive. It reuses the deterministic geometry
kernel and state store, but requires an independent municipal context source,
per-request provenance, exact-polygon OSM coverage, and a contextual static map.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .geometry import GeometryValidationError, canonical_geometry_hash, validate_geometry
from .site_proposal import (
    SiteProposal,
    SiteProposalValidationError,
    V2SourceRecord,
    canonical_json_bytes,
    sha256_file,
    validate_site_proposal,
)


class SiteProposalV2ValidationError(SiteProposalValidationError):
    """Raised when a repaired v2 approval package is incomplete or tampered."""


def _raw_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _geometry_from_geojson(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("type") in {"Polygon", "MultiPolygon"}:
        return {"type": payload["type"], "coordinates": payload.get("coordinates")}
    if payload.get("type") == "Feature":
        geometry = payload.get("geometry")
        if isinstance(geometry, Mapping):
            return {"type": geometry.get("type"), "coordinates": geometry.get("coordinates")}
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features")
        if isinstance(features, list) and len(features) == 1 and isinstance(features[0], Mapping):
            geometry = features[0].get("geometry")
            if isinstance(geometry, Mapping):
                return {"type": geometry.get("type"), "coordinates": geometry.get("coordinates")}
    raise SiteProposalV2ValidationError("context artifact must contain one Polygon or MultiPolygon")


def _point_on_segment(point: tuple[float, float], a: Sequence[float], b: Sequence[float]) -> bool:
    cross = (float(b[0]) - float(a[0])) * (point[1] - float(a[1])) - (float(b[1]) - float(a[1])) * (point[0] - float(a[0]))
    if abs(cross) > 1e-10:
        return False
    return min(float(a[0]), float(b[0])) - 1e-10 <= point[0] <= max(float(a[0]), float(b[0])) + 1e-10 and min(float(a[1]), float(b[1])) - 1e-10 <= point[1] <= max(float(a[1]), float(b[1])) + 1e-10


def _inside_ring(point: tuple[float, float], ring: Sequence[Sequence[float]]) -> bool:
    inside = False
    for first, second in zip(ring, ring[1:]):
        if _point_on_segment(point, first, second):
            return True
        x1, y1 = float(first[0]), float(first[1])
        x2, y2 = float(second[0]), float(second[1])
        if (y1 > point[1]) != (y2 > point[1]):
            cross_x = (x2 - x1) * (point[1] - y1) / (y2 - y1) + x1
            if point[0] < cross_x:
                inside = not inside
    return inside


def point_in_polygon(point: tuple[float, float], geometry: Mapping[str, Any]) -> bool:
    """Return whether a WGS84 point is inside a validated Polygon/MultiPolygon."""

    summary = validate_geometry(geometry)
    if summary["type"] == "Polygon":
        rings = summary["coordinates"]
        return _inside_ring(point, rings[0]) and not any(_inside_ring(point, ring) for ring in rings[1:])
    for polygon in summary["coordinates"]:
        if _inside_ring(point, polygon[0]) and not any(_inside_ring(point, ring) for ring in polygon[1:]):
            return True
    return False


def verify_v1_integrity(manifest_path: str | Path, v1_root: str | Path) -> dict[str, Any]:
    """Re-hash every retained v1 file listed by the v2 integrity manifest."""

    manifest_file = Path(manifest_path)
    root = Path(v1_root)
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    entries = payload.get("files") if isinstance(payload, Mapping) else None
    if not isinstance(entries, list) or not entries:
        raise SiteProposalV2ValidationError("v1 integrity manifest is empty")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise SiteProposalV2ValidationError("v1 integrity manifest entry is malformed")
        path = root / str(entry.get("path", ""))
        if not path.is_file() or path.stat().st_size != entry.get("size_bytes") or _raw_sha256(path) != entry.get("sha256"):
            raise SiteProposalV2ValidationError(f"v1 artifact integrity mismatch: {entry.get('path')}")
    return {"file_count": len(entries), "manifest_sha256": _raw_sha256(manifest_file)}


def validate_context_map(path: str | Path, *, expected_sha256: str | None = None, expected_size_bytes: int | None = None) -> None:
    """Check that the static SVG exposes every approval-critical map element."""

    map_path = Path(path)
    if not map_path.is_file() or map_path.stat().st_size == 0:
        raise SiteProposalV2ValidationError("context map artifact is missing or empty")
    if expected_sha256 is not None and _raw_sha256(map_path) != expected_sha256:
        raise SiteProposalV2ValidationError("context map artifact hash mismatch")
    if expected_size_bytes is not None and map_path.stat().st_size != expected_size_bytes:
        raise SiteProposalV2ValidationError("context map artifact size mismatch")
    content = map_path.read_text(encoding="utf-8").casefold()
    required = (
        "proposed boundary",
        "roads",
        "buildings",
        "rail",
        "water",
        "public space",
        "shops",
        "north",
        "scale",
        "legend",
        "epsg:28992",
        "source",
        "timestamp",
        "attribution",
    )
    missing = [token for token in required if token not in content]
    if missing:
        raise SiteProposalV2ValidationError("context map is incomplete: missing " + ", ".join(missing))


def _verify_municipal_context(proposal: SiteProposal, root: Path) -> None:
    context = proposal.delft_context
    context_path_value = context.get("municipality_feature_path")
    context_hash = context.get("municipality_feature_sha256")
    if not isinstance(context_path_value, str) or not isinstance(context_hash, str):
        raise SiteProposalV2ValidationError("independent municipality context artifact and hash are required")
    context_path = root / context_path_value
    if not context_path.is_file() or _raw_sha256(context_path) != context_hash:
        raise SiteProposalV2ValidationError("independent municipality context artifact hash mismatch")
    payload = json.loads(context_path.read_text(encoding="utf-8"))
    geometry = _geometry_from_geojson(payload)
    try:
        validate_geometry(geometry)
    except (GeometryValidationError, TypeError, KeyError) as exc:
        raise SiteProposalV2ValidationError(str(exc)) from exc
    properties = payload.get("properties", {}) if isinstance(payload, Mapping) else {}
    if properties.get("naam") != "Delft" or properties.get("code") != "0503":
        raise SiteProposalV2ValidationError("context feature is not the independent PDOK Delft municipality")
    expected_geometry_hash = context.get("municipality_geometry_sha256")
    if expected_geometry_hash and canonical_geometry_hash(geometry) != expected_geometry_hash:
        raise SiteProposalV2ValidationError("municipality geometry hash mismatch")
    ring = context.get("candidate_boundary_wgs84")
    if not isinstance(ring, list) or len(ring) < 4:
        raise SiteProposalV2ValidationError("candidate WGS84 ring is required for containment validation")
    try:
        candidate_points = [(float(point[0]), float(point[1])) for point in ring[:-1]]
        candidate_geometry = {"type": "Polygon", "coordinates": [ring]}
        candidate_geometry_hash = canonical_geometry_hash(candidate_geometry)
        contained = all(point_in_polygon(point, geometry) for point in candidate_points)
    except (GeometryValidationError, TypeError, ValueError, IndexError, KeyError) as exc:
        raise SiteProposalV2ValidationError("candidate WGS84 boundary geometry is invalid") from exc
    if not contained:
        raise SiteProposalV2ValidationError("candidate boundary is not inside the independent Delft municipality")
    candidate_hash = context.get("candidate_boundary_wgs84_sha256")
    if candidate_hash != candidate_geometry_hash:
        raise SiteProposalV2ValidationError("candidate WGS84 boundary hash mismatch")


def validate_site_proposal_v2(
    proposal: SiteProposal | Mapping[str, Any],
    package_root: str | Path,
    *,
    v1_root: str | Path | None = None,
) -> SiteProposal:
    """Validate the complete v2 proposal, sources, map, and v1 lineage."""

    root = Path(package_root)
    candidate = proposal if isinstance(proposal, SiteProposal) else SiteProposal.model_validate(proposal)
    if candidate.version.casefold() != "v2":
        raise SiteProposalV2ValidationError("v2 validator requires version v2")
    validate_site_proposal(candidate, root)
    if candidate.source_records_path is None or candidate.map_preview_path is None:
        raise SiteProposalV2ValidationError("v2 source-record and map paths are required")
    source_path = root / candidate.source_records_path
    if not source_path.is_file():
        raise SiteProposalV2ValidationError("v2 source-record artifact is missing")
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    raw_records = source_payload.get("records") if isinstance(source_payload, Mapping) else None
    if not isinstance(raw_records, list) or not raw_records:
        raise SiteProposalV2ValidationError("v2 source-record artifact contains no records")
    records = [V2SourceRecord.model_validate(item) for item in raw_records]
    for record in records:
        if record.availability == "OBSERVED":
            artifact = root / str(record.artifact_path)
            if not artifact.is_file() or artifact.stat().st_size != record.artifact_size_bytes or _raw_sha256(artifact) != record.artifact_sha256:
                raise SiteProposalV2ValidationError(f"source artifact mismatch: {record.id}")
    _verify_municipal_context(candidate, root)
    validate_context_map(root / candidate.map_preview_path)
    exact_hash = candidate.delft_context.get("candidate_boundary_wgs84_sha256")
    exact_records = [record for record in records if record.id == "source-osm-exact-polygon-context"]
    if not exact_records or exact_records[0].parameters.get("query_boundary_sha256") != exact_hash:
        raise SiteProposalV2ValidationError("OSM coverage query is not linked to the exact proposed polygon")
    exact_artifact = root / str(exact_records[0].artifact_path)
    try:
        exact_payload = json.loads(exact_artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SiteProposalV2ValidationError("OSM exact-polygon artifact cannot be read") from exc
    elements = exact_payload.get("elements", []) if isinstance(exact_payload, Mapping) else []
    retained_way_ids = {str(item.get("id")) for item in elements if isinstance(item, Mapping) and item.get("type") == "way"}
    edges = candidate.selection_criteria.get("edges", [])
    if not isinstance(edges, list) or not edges:
        raise SiteProposalV2ValidationError("proposed boundary must name retained OSM edge evidence")
    edge_ids = {str(edge.get("osm_way_id")) for edge in edges if isinstance(edge, Mapping) and edge.get("osm_way_id") is not None}
    if not edge_ids or not edge_ids.issubset(retained_way_ids):
        raise SiteProposalV2ValidationError("selection criteria reference OSM ways absent from retained exact-polygon bytes")
    exact_coverage = exact_records[0].coverage
    if exact_coverage.get("exact_polygon_query") is not True or "poly:" not in exact_records[0].query:
        raise SiteProposalV2ValidationError("OSM source must retain an exact polygon query")
    count_keys = ("roads", "pedestrian_ways", "buildings", "railways", "waterways", "public_space", "shops", "stations")
    if any(not isinstance(exact_coverage.get(key), int) or exact_coverage[key] < 0 for key in count_keys):
        raise SiteProposalV2ValidationError("OSM source must retain non-negative raw layer counts")
    if not exact_records[0].limitations or not any("missing" in limitation.casefold() for limitation in exact_records[0].limitations):
        raise SiteProposalV2ValidationError("OSM source must state missing-feature limitations")
    counts = exact_coverage.get("shop_tag_counts", {})
    if not isinstance(counts, Mapping) or any(key not in counts for key in ("supermarket", "convenience", "grocery")):
        raise SiteProposalV2ValidationError("raw grocery shop tag categories must remain separate")
    if candidate.taxonomy_status != "PROPOSED":
        raise SiteProposalV2ValidationError("destination taxonomy cannot be effective in v2")
    if candidate.scale_parameters.get("status") not in {None, "PROPOSED_PROJECT_DECISION"}:
        raise SiteProposalV2ValidationError("scale parameters must remain proposed")
    if v1_root is not None:
        manifest_path = root / "v1-integrity.json"
        verify_v1_integrity(manifest_path, v1_root)
    return candidate


__all__ = [
    "SiteProposalV2ValidationError",
    "point_in_polygon",
    "validate_context_map",
    "validate_site_proposal_v2",
    "verify_v1_integrity",
]
