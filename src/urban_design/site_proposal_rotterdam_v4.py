"""Fail-closed validation for the append-only M2-R05 Rotterdam v4 package."""
from __future__ import annotations

import json, math, re, struct
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from pyproj import Transformer
from shapely.geometry import LineString, shape
from shapely.ops import transform as shp_transform

from .geometry import canonical_geometry_hash, validate_geometry, GeometryValidationError
from .site_proposal import SiteProposal, sha256_file


class RotterdamSiteProposalV4ValidationError(ValueError):
    pass


def _safe(root: Path, value: str) -> Path:
    p = (root / PurePosixPath(value.replace("\\", "/"))).resolve()
    if root.resolve() not in p.parents and p != root.resolve():
        raise RotterdamSiteProposalV4ValidationError("path escapes package")
    return p


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RotterdamSiteProposalV4ValidationError(f"invalid JSON: {path}") from exc


def _geom(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if payload.get("type") == "Feature":
        return payload.get("geometry") or {}
    return payload


def _require_hash(root: Path, rel: str, expected: str | None = None) -> Path:
    p = _safe(root, rel)
    if not p.is_file():
        raise RotterdamSiteProposalV4ValidationError(f"missing artifact: {rel}")
    if expected and sha256_file(p) != expected:
        raise RotterdamSiteProposalV4ValidationError(f"hash mismatch: {rel}")
    return p


def _validate_parent(root: Path, context: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = _load(_require_hash(root, context.get("parent_integrity_path", "parent-v3-integrity.json")))
    if manifest.get("parent_id") != "site-proposal-rotterdam-m4h-v3":
        raise RotterdamSiteProposalV4ValidationError("v3 parent manifest id missing")
    for item in manifest.get("files", []):
        p = _safe(root, item["retained_path"])
        if not p.is_file() or p.stat().st_size != item["size_bytes"] or sha256_file(p) != item["sha256"]:
            raise RotterdamSiteProposalV4ValidationError(f"parent byte integrity failed: {item.get('relative_path')}")
    return manifest


def _validate_feedback(root: Path, context: Mapping[str, Any]) -> None:
    payload = _load(_require_hash(root, context["human_feedback_evidence_path"]))
    entries = payload.get("feedback", [])
    if len(entries) != 3:
        raise RotterdamSiteProposalV4ValidationError("exactly three retained feedback images required")
    for item in entries:
        if item.get("classification") != ["HUMAN_FEEDBACK", "HUMAN_INTENT"] or item.get("used_as_measurement") is not False:
            raise RotterdamSiteProposalV4ValidationError("human feedback classification/measurement contract failed")
        p = _require_hash(root, item["retained_path"], item.get("sha256"))
        if p.stat().st_size != item.get("size_bytes"):
            raise RotterdamSiteProposalV4ValidationError("feedback size mismatch")


def _rings(geometry: Mapping[str, Any]) -> list[list[tuple[float, float]]]:
    if geometry.get("type") != "Polygon" or len(geometry.get("coordinates", [])) != 1:
        raise RotterdamSiteProposalV4ValidationError("v4 boundary must be one Polygon exterior ring")
    rings = [[(float(x), float(y)) for x, y in ring] for ring in geometry["coordinates"]]
    if len(rings[0]) < 4 or rings[0][0] != rings[0][-1]:
        raise RotterdamSiteProposalV4ValidationError("boundary ring must be closed")
    try:
        validate_geometry(geometry)
    except GeometryValidationError as exc:
        raise RotterdamSiteProposalV4ValidationError(str(exc)) from exc
    return rings


def _validate_boundary_evidence(root: Path, context: Mapping[str, Any], ring: list[tuple[float, float]]) -> None:
    evidence = _load(_require_hash(root, context["boundary_relationship_evidence_path"]))
    if evidence.get("schema_version") != "m2-r05-boundary-relationship-evidence":
        raise RotterdamSiteProposalV4ValidationError("v4 boundary evidence schema invalid")
    if evidence.get("coordinate_crs") != "EPSG:28992" or evidence.get("source_dataset") != "BGT":
        raise RotterdamSiteProposalV4ValidationError("BGT projected boundary evidence is required")
    raw_path = _require_hash(root, context["bgt_source_path"], context.get("bgt_source_sha256"))
    raw = _load(raw_path)
    tx = Transformer.from_crs(4326, 28992, always_xy=True)
    bag_path = _require_hash(root, context["bag_source_path"], context.get("bag_source_sha256"))
    bag = _load(bag_path)
    if evidence.get("bag_building_snapshot_path") != context.get("bag_source_path") or evidence.get("bag_building_snapshot_sha256") != context.get("bag_source_sha256"):
        raise RotterdamSiteProposalV4ValidationError("BAG building snapshot provenance mismatch")
    boundary = shape({"type": "Polygon", "coordinates": [[list(point) for point in ring]]})
    bag_crossings = []
    for feature in bag.get("features", []):
        geometry = feature.get("geometry") or {}
        try:
            footprint = shp_transform(tx.transform, shape(geometry))
        except Exception as exc:
            raise RotterdamSiteProposalV4ValidationError("BAG pand contains an unreadable building geometry") from exc
        if not footprint.is_valid or footprint.is_empty:
            raise RotterdamSiteProposalV4ValidationError("BAG pand contains an invalid or empty building geometry")
        if not footprint.within(boundary) and footprint.intersection(boundary).area > 1e-7:
            properties = feature.get("properties") or {}
            bag_crossings.append(str(properties.get("identificatie") or feature.get("id") or "unknown"))
    bag_crossings = sorted(set(bag_crossings))
    if evidence.get("bag_building_crossing_count") != len(bag_crossings) or evidence.get("bag_cross_boundary_buildings") != bag_crossings or context.get("bag_building_crossing_count") != len(bag_crossings) or context.get("bag_cross_boundary_buildings") != bag_crossings:
        raise RotterdamSiteProposalV4ValidationError("BAG building-interior crossing result mismatch")
    if bag_crossings:
        raise RotterdamSiteProposalV4ValidationError("BAG building footprint interior crosses v4 boundary")
    source = {str(f.get("id")): f for f in raw.get("features", []) if f.get("id") is not None}
    edges = evidence.get("edges", [])
    if len(edges) != len(ring) - 1:
        raise RotterdamSiteProposalV4ValidationError("one BGT evidence record required for every boundary segment")
    for i, item in enumerate(edges):
        if item.get("edge_index") != i or item.get("claim_status") != "SOURCE_GEOMETRY_SEGMENT" or item.get("physical_edge_claim") is not True:
            raise RotterdamSiteProposalV4ValidationError("unsupported boundary edge claim")
        if item.get("source_dataset") != "BGT" or item.get("source_collection") != "wegdeel":
            raise RotterdamSiteProposalV4ValidationError("every boundary segment must cite BGT wegdeel")
        if any(token in json.dumps(item, sort_keys=True).upper() for token in ("OSM", "HUMAN_INTENT", "CENTERLINE")):
            raise RotterdamSiteProposalV4ValidationError("forbidden centerline/human connector claim")
        feature = source.get(str(item.get("source_feature_id")))
        seg = item.get("source_segment")
        if feature is None or not isinstance(seg, list) or len(seg) != 2 or any(type(v) is not int or v < 0 for v in seg):
            raise RotterdamSiteProposalV4ValidationError("BGT source feature/segment missing")
        source_geom = feature.get("geometry") or {}
        coords = source_geom.get("coordinates", [])
        if source_geom.get("type") != "Polygon" or len(coords) != 1 or seg[1] != seg[0] + 1 or seg[1] >= len(coords[0]):
            raise RotterdamSiteProposalV4ValidationError("BGT source ring/segment index is outside retained polygon")
        projected = shp_transform(tx.transform, shape({"type": "LineString", "coordinates": [coords[0][seg[0]], coords[0][seg[1]]]}))
        a = tuple(float(v) for v in item["start_epsg28992"]); b = tuple(float(v) for v in item["end_epsg28992"])
        boundary_segment = LineString([a, b])
        if projected.distance(boundary_segment) > 1e-4 or float(item.get("measured_distance_m", 1.0)) > 1e-4:
            raise RotterdamSiteProposalV4ValidationError("boundary segment is not the cited BGT polygon segment")


def _validate_display(root: Path, context: Mapping[str, Any]) -> None:
    display = _load(_require_hash(root, context["display_data_path"]))
    expected = ["background/land", "water", "public/open", "context buildings", "site buildings", "roads/walk paths", "rail", "labels/markers", "boundary"]
    if display.get("classification_priority") != expected:
        raise RotterdamSiteProposalV4ValidationError("display priority mismatch")
    features = display.get("features", [])
    layers = [(f.get("properties") or {}).get("display_layer") for f in features]
    if len(layers) != len(features) or any(layer not in expected for layer in layers):
        raise RotterdamSiteProposalV4ValidationError("exclusive display classification failed")
    if sum(layer == "water" for layer in layers) > 1:
        raise RotterdamSiteProposalV4ValidationError("water polygons were not dissolved")
    if any((f.get("properties") or {}).get("geometry_clipped") for f in features if (f.get("properties") or {}).get("building")):
        raise RotterdamSiteProposalV4ValidationError("building geometry was clipped")


def _validate_svg(root: Path, context: Mapping[str, Any]) -> None:
    text = _safe(root, context["map_svg_path"]).read_text(encoding="utf-8")
    required = ["layer-background", "layer-water", "layer-public-space", "layer-context-buildings", "layer-site-buildings", "layer-roads", "layer-rail", "layer-markers", "layer-boundary"]
    ids = re.findall(r'<g id="([^"]+)"', text)
    if [value for value in ids if value in required] != required:
        raise RotterdamSiteProposalV4ValidationError("SVG layer order mismatch")
    for token in ('#f1f4f5', '#d62728', 'stroke-width="1.4"', 'fill="none"', 'site-proposal-rotterdam-m4h-v4', 'REJECTED_BY_HUMAN_FEEDBACK'):
        if token not in text:
            raise RotterdamSiteProposalV4ValidationError(f"required SVG token missing: {token}")
    if 'HUMAN_INTENT_ALIGNMENT_REVIEW' in text or 'OSM road geometry' in text or 'human connector' in text.lower():
        raise RotterdamSiteProposalV4ValidationError("SVG retains a human/OSM connector claim")


def _validate_png(root: Path, context: Mapping[str, Any]) -> None:
    path = _safe(root, context["rendered_png_path"]); raw = path.read_bytes()
    if sha256_file(path) != context.get("rendered_png_sha256") or raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 24:
        raise RotterdamSiteProposalV4ValidationError("PNG hash/signature invalid")
    if struct.unpack(">II", raw[16:24]) != (1240, 850) or b"IDAT" not in raw:
        raise RotterdamSiteProposalV4ValidationError("PNG must be a non-empty 1240x850 render")


def _validate_state(root: Path, proposal: SiteProposal) -> None:
    import sqlite3
    con = sqlite3.connect(_safe(root, proposal.delft_context["state_path"]))
    try:
        rows = con.execute("select entity_type, payload_json from state_versions where entity_type in ('Project','Site','SiteModel','SiteProposal')").fetchall()
        if not rows:
            raise RotterdamSiteProposalV4ValidationError("state has no records")
        for typ, payload in rows:
            data = json.loads(payload)
            if typ == "Project" and data.get("id") == proposal.project_id and data.get("site_id") is not None:
                raise RotterdamSiteProposalV4ValidationError("Project.site_id must remain null")
            if typ in {"Site", "SiteModel"} and data.get("version") == "v4" and str(data.get("status", "")).upper() != "PROPOSED":
                raise RotterdamSiteProposalV4ValidationError("v4 site is not proposed")
        bad = con.execute("select action from ledger_events where lower(action) like '%approve%' or lower(action) like '%accept%' or lower(action) like '%freeze%'").fetchall()
        if bad:
            raise RotterdamSiteProposalV4ValidationError("approval/accept/freeze event present")
    finally:
        con.close()


def validate_site_proposal_rotterdam_v4(proposal: SiteProposal | Mapping[str, Any], package_root: str | Path, *, v3_dir: str | Path | None = None) -> SiteProposal:
    candidate = proposal if isinstance(proposal, SiteProposal) else SiteProposal.model_validate(proposal)
    if candidate.id != "site-proposal-rotterdam-m4h-v4" or candidate.version != "v4" or candidate.supersedes_proposal_id != "site-proposal-rotterdam-m4h-v3":
        raise RotterdamSiteProposalV4ValidationError("wrong v4 identity/lineage")
    root = Path(package_root).resolve(); context = candidate.delft_context
    _validate_parent(root, context); _validate_feedback(root, context)
    boundary_path = _require_hash(root, candidate.boundary_artifact_path, candidate.boundary_sha256)
    if boundary_path.stat().st_size != candidate.boundary_size_bytes:
        raise RotterdamSiteProposalV4ValidationError("boundary size mismatch")
    geometry = _geom(_load(boundary_path)); ring = _rings(geometry)[0]
    if geometry != candidate.geometry or canonical_geometry_hash(geometry) != candidate.geometry_sha256:
        raise RotterdamSiteProposalV4ValidationError("boundary geometry/hash mismatch")
    _validate_boundary_evidence(root, context, ring); _validate_display(root, context); _validate_svg(root, context); _validate_png(root, context)
    if context.get("cross_boundary_buildings") != [] or context.get("building_crossing_count") != 0:
        raise RotterdamSiteProposalV4ValidationError("v4 building crossing result is not zero")
    _validate_state(root, candidate)
    return candidate


__all__ = ["RotterdamSiteProposalV4ValidationError", "validate_site_proposal_rotterdam_v4"]
