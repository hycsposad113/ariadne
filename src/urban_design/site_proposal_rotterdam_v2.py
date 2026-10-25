"""M2-R03 validation for the append-only Rotterdam M4H v2 repair.

The v2 contract makes the source-to-boundary relationship measurable.  A
control point may be called source-derived only when its projected distance to
the retained source way is within the registered tolerance.  Ring connectors
that do not follow one mapped segment are labelled as human-sketch connectors
and carry no physical-edge claim.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct
import xml.etree.ElementTree as ET
import zlib
from typing import Any, Iterable, Mapping, Sequence

from .geometry import canonical_geometry_hash, polygon_area, polygon_perimeter, validate_geometry
from .site_proposal import SiteProposal, SiteProposalValidationError, V2SourceRecord, validate_site_proposal
from .site_proposal_rotterdam import (
    RotterdamSiteProposalValidationError,
    _validate_municipality,
    _validate_sources,
)


class RotterdamSiteProposalV2ValidationError(RotterdamSiteProposalValidationError):
    """Raised when the M2-R03 append-only repair is incomplete or unsupported."""


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _safe(root: Path, value: str) -> Path:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise RotterdamSiteProposalV2ValidationError(f"unsafe package path: {value}")
    return root / path


def _geometry_from_geojson(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("type") in {"Polygon", "MultiPolygon"}:
        return {"type": payload["type"], "coordinates": payload.get("coordinates")}
    if payload.get("type") == "Feature":
        geometry = payload.get("geometry")
        if isinstance(geometry, Mapping):
            return {"type": geometry.get("type"), "coordinates": geometry.get("coordinates")}
    if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list) and len(payload["features"]) == 1:
        return _geometry_from_geojson(payload["features"][0])
    raise RotterdamSiteProposalV2ValidationError("boundary artifact does not contain one geometry")


def _coords(geometry: Mapping[str, Any]) -> list[list[tuple[float, float]]]:
    kind = geometry.get("type")
    value = geometry.get("coordinates")
    if kind == "LineString":
        return [[(float(point[0]), float(point[1])) for point in value]]
    if kind == "Polygon":
        return [[(float(point[0]), float(point[1])) for point in ring] for ring in value]
    if kind == "MultiLineString":
        return [[(float(point[0]), float(point[1])) for point in line] for line in value]
    if kind == "MultiPolygon":
        return [[(float(point[0]), float(point[1])) for point in ring] for polygon in value for ring in polygon]
    return []


def point_segment_distance(point: Sequence[float], first: Sequence[float], second: Sequence[float]) -> tuple[float, float, tuple[float, float]]:
    """Return projected-metre distance, segment fraction, and nearest point."""

    px, py = float(point[0]), float(point[1])
    ax, ay = float(first[0]), float(first[1])
    bx, by = float(second[0]), float(second[1])
    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy
    fraction = 0.0 if denominator == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denominator))
    nearest = (ax + fraction * dx, ay + fraction * dy)
    return math.dist((px, py), nearest), fraction, nearest


def _nearest_way(point: Sequence[float], way_features: Mapping[str, Mapping[str, Any]], way_id: str) -> dict[str, Any]:
    feature = way_features.get(str(way_id))
    if feature is None:
        raise RotterdamSiteProposalV2ValidationError(f"OSM edge_ref way is absent from retained projected context: {way_id}")
    nearest: tuple[float, int, float, tuple[float, float]] | None = None
    segment_index = 0
    for line in _coords(feature.get("geometry", {})):
        for index, (first, second) in enumerate(zip(line, line[1:])):
            distance, fraction, projected = point_segment_distance(point, first, second)
            candidate = (distance, segment_index + index, fraction, projected)
            if nearest is None or candidate[0] < nearest[0]:
                nearest = candidate
        segment_index += max(0, len(line) - 1)
    if nearest is None:
        raise RotterdamSiteProposalV2ValidationError(f"retained OSM way has no usable segments: {way_id}")
    return {"distance_m": nearest[0], "segment_index": nearest[1], "segment_fraction": nearest[2], "nearest_point_epsg28992": list(nearest[3])}


def _projected_features(root: Path, context_path: str) -> dict[str, Mapping[str, Any]]:
    path = _safe(root, context_path)
    if not path.is_file():
        raise RotterdamSiteProposalV2ValidationError(f"projected OSM context is missing: {context_path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") if isinstance(payload, Mapping) else None
    if not isinstance(features, list):
        raise RotterdamSiteProposalV2ValidationError("projected OSM context has no features")
    return {str(feature.get("id")): feature for feature in features if isinstance(feature, Mapping) and feature.get("id") is not None}


def _raw_way_vertices(root: Path, snapshot_path: str) -> dict[str, list[list[float]]]:
    payload = json.loads(_safe(root, snapshot_path).read_text(encoding="utf-8"))
    elements = payload.get("elements") if isinstance(payload, Mapping) else None
    if not isinstance(elements, list):
        raise RotterdamSiteProposalV2ValidationError("retained source snapshot has no OSM elements")
    result: dict[str, list[list[float]]] = {}
    for element in elements:
        if not isinstance(element, Mapping) or element.get("type") != "way" or element.get("id") is None:
            continue
        geometry = element.get("geometry")
        if isinstance(geometry, list):
            vertices = [[float(point["lon"]), float(point["lat"])] for point in geometry if isinstance(point, Mapping) and "lon" in point and "lat" in point]
            if vertices:
                result[str(element["id"])] = vertices
    return result


def _option_ring(option: Mapping[str, Any]) -> list[list[float]]:
    geometry = option.get("projected_geometry")
    if not isinstance(geometry, Mapping) or geometry.get("type") != "Polygon":
        raise RotterdamSiteProposalV2ValidationError("option projected geometry must be a Polygon")
    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or len(coords) != 1:
        raise RotterdamSiteProposalV2ValidationError("option projected geometry must have one exterior ring")
    return [[float(point[0]), float(point[1])] for point in coords[0]]


def validate_source_edge_relationships(proposal: SiteProposal | Mapping[str, Any], package_root: str | Path, *, require_evidence: bool = True) -> dict[str, Any]:
    """Validate every declared source-derived control point against retained geometry."""

    root = Path(package_root)
    candidate = proposal if isinstance(proposal, SiteProposal) else SiteProposal.model_validate(proposal)
    context = candidate.delft_context
    options = context.get("boundary_options")
    context_path = context.get("context_display_path")
    if not isinstance(options, Mapping) or not isinstance(context_path, str):
        raise RotterdamSiteProposalV2ValidationError("boundary options and projected OSM context are required")
    features = _projected_features(root, context_path)
    evidence_path_value = context.get("source_distance_evidence_path")
    if require_evidence and not isinstance(evidence_path_value, str):
        raise RotterdamSiteProposalV2ValidationError("source-distance evidence is required")
    evidence_payload: Mapping[str, Any] = {}
    raw_vertices: dict[str, list[list[float]]] = {}
    if isinstance(evidence_path_value, str):
        evidence_path = _safe(root, evidence_path_value)
        if not evidence_path.is_file():
            raise RotterdamSiteProposalV2ValidationError("source-distance evidence artifact is missing")
        evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not isinstance(evidence_payload, Mapping) or evidence_payload.get("schema_version") != "m2-r03-source-distance-evidence":
            raise RotterdamSiteProposalV2ValidationError("source-distance evidence schema is invalid")
        source_snapshot_path = evidence_payload.get("source_snapshot_path")
        source_snapshot_sha256 = evidence_payload.get("source_snapshot_sha256")
        if not isinstance(source_snapshot_path, str) or not isinstance(source_snapshot_sha256, str):
            raise RotterdamSiteProposalV2ValidationError("source snapshot path and hash are required")
        snapshot = _safe(root, source_snapshot_path)
        if not snapshot.is_file() or _sha256(snapshot) != source_snapshot_sha256:
            raise RotterdamSiteProposalV2ValidationError("retained source snapshot hash mismatch")
        raw_vertices = _raw_way_vertices(root, source_snapshot_path)
        projected_hash = evidence_payload.get("projected_context_sha256")
        if projected_hash is not None and _sha256(_safe(root, context_path)) != projected_hash:
            raise RotterdamSiteProposalV2ValidationError("projected source context hash mismatch")
    tolerance = evidence_payload.get("tolerance_m", context.get("source_distance_tolerance_m", 1.0))
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or not math.isfinite(float(tolerance)) or float(tolerance) <= 0:
        raise RotterdamSiteProposalV2ValidationError("source-distance tolerance must be a positive metric value")
    evidence_options = evidence_payload.get("options", {}) if isinstance(evidence_payload, Mapping) else {}
    results: dict[str, Any] = {"tolerance_m": float(tolerance), "options": {}}
    for option_key in ("A", "B"):
        option = options.get(option_key)
        if not isinstance(option, Mapping):
            raise RotterdamSiteProposalV2ValidationError(f"boundary option {option_key} is missing")
        edge_refs = option.get("edge_refs")
        if not isinstance(edge_refs, list) or not edge_refs:
            raise RotterdamSiteProposalV2ValidationError(f"boundary option {option_key} has no edge_refs")
        ring = _option_ring(option)
        points = ring[:-1]
        declared_way_ids = {str(ref.get("osm_way_id")) for ref in edge_refs if isinstance(ref, Mapping) and ref.get("osm_way_id") is not None}
        wgs84_geometry = option.get("wgs84_geometry")
        wgs84_points = []
        if isinstance(wgs84_geometry, Mapping) and isinstance(wgs84_geometry.get("coordinates"), list) and wgs84_geometry["coordinates"]:
            wgs84_points = wgs84_geometry["coordinates"][0][:-1]
        declared = evidence_options.get(option_key, {}) if isinstance(evidence_options, Mapping) else {}
        control_evidence = declared.get("control_points", []) if isinstance(declared, Mapping) else []
        by_point = {str(item.get("control_point")): item for item in control_evidence if isinstance(item, Mapping)}
        option_result: list[dict[str, Any]] = []
        for index, point in enumerate(points):
            point_label = chr(ord("A") + index)
            item = by_point.get(point_label)
            if require_evidence and item is None:
                raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} lacks source-distance evidence")
            if item is None:
                item = {"control_point": point_label, "source_way_ids": [str(ref.get("osm_way_id")) for ref in edge_refs if isinstance(ref, Mapping)]}
            source_way_ids = item.get("source_way_ids")
            if not isinstance(source_way_ids, list) or not source_way_ids:
                raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} has no source way")
            if not set(str(value) for value in source_way_ids).issubset(declared_way_ids):
                raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} cites a way absent from edge_refs")
            distances = []
            for way_id in source_way_ids:
                nearest = _nearest_way(point, features, str(way_id))
                distances.append({"way_id": str(way_id), **nearest})
            best = min(distances, key=lambda value: float(value["distance_m"]))
            if float(best["distance_m"]) > float(tolerance) + 1e-7:
                raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} exceeds source tolerance: {best['distance_m']:.3f} m > {float(tolerance):.3f} m")
            if require_evidence:
                if item.get("relationship_status") != "SOURCE_VERTEX_OR_SEGMENT_WITHIN_TOLERANCE":
                    raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} has no passing relationship status")
                if item.get("measured_distance_m") is None or not math.isclose(float(item["measured_distance_m"]), float(best["distance_m"]), abs_tol=1e-7):
                    raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} measured distance is inconsistent")
                if item.get("source_way_id") != best["way_id"]:
                    raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} source way is inconsistent")
                source_vertex = item.get("source_vertex_index")
                if not isinstance(source_vertex, int) or isinstance(source_vertex, bool) or source_vertex < 0:
                    raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} source vertex index is invalid")
                coordinate = item.get("source_coordinate_wgs84")
                if not isinstance(coordinate, list) or len(coordinate) != 2 or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in coordinate):
                    raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} source coordinate is invalid")
                vertices = raw_vertices.get(str(best["way_id"]), [])
                if source_vertex >= len(vertices) or any(not math.isclose(float(coordinate[i]), vertices[source_vertex][i], abs_tol=1e-8) for i in (0, 1)):
                    raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} source vertex does not match snapshot")
                source_segment = item.get("source_segment")
                if not isinstance(source_segment, list) or len(source_segment) != 2 or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in source_segment):
                    raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} source segment is invalid")
                if source_segment[0] >= len(vertices) - 1 or source_segment[1] != source_segment[0] + 1:
                    raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} source segment is outside snapshot")
                if wgs84_points and (index >= len(wgs84_points) or any(not math.isclose(float(coordinate[i]), float(wgs84_points[index][i]), abs_tol=1e-8) for i in (0, 1))):
                    raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} control point {point_label} WGS84 coordinate is inconsistent")
            option_result.append({"control_point": point_label, "coordinate_epsg28992": point, "nearest": best, "source_way_ids": [str(value) for value in source_way_ids], "status": "PASS"})
        edge_evidence = declared.get("boundary_edges", []) if isinstance(declared, Mapping) else []
        if require_evidence:
            for edge in edge_evidence:
                if not isinstance(edge, Mapping) or edge.get("claim_status") not in {"NOT_CLAIMED_HUMAN_SKETCH_CONNECTOR", "SOURCE_SEGMENT_WITHIN_TOLERANCE"}:
                    raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} contains an unsupported boundary edge claim")
                if edge.get("claim_status") == "SOURCE_SEGMENT_WITHIN_TOLERANCE":
                    distance = edge.get("measured_distance_m")
                    if not isinstance(distance, (int, float)) or float(distance) > float(tolerance) + 1e-7:
                        raise RotterdamSiteProposalV2ValidationError(f"Option {option_key} asserted edge exceeds source tolerance")
        results["options"][option_key] = {"control_points": option_result, "boundary_edges": edge_evidence}
    return results


def _validate_png(path: Path, expected_hash: str, expected_size: int, dimensions: tuple[int, int]) -> None:
    if not path.is_file() or _sha256(path) != expected_hash or path.stat().st_size != expected_size:
        raise RotterdamSiteProposalV2ValidationError(f"PNG artifact mismatch: {path.name}")
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", raw[16:24]) != dimensions:
        raise RotterdamSiteProposalV2ValidationError(f"PNG artifact is not {dimensions[0]}x{dimensions[1]}")
    chunks: list[bytes] = []
    offset = 8
    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        if kind == b"IDAT":
            chunks.append(raw[offset + 8 : offset + 8 + length])
        offset += length + 12
        if kind == b"IEND":
            break
    try:
        decoded = zlib.decompress(b"".join(chunks))
    except zlib.error as exc:
        raise RotterdamSiteProposalV2ValidationError("PNG pixel data is not decodable") from exc
    if len(set(decoded)) <= 4:
        raise RotterdamSiteProposalV2ValidationError("PNG appears blank")


def _svg_metadata(path: Path, expected_hash: str, expected_size: int, option: str) -> dict[str, Any]:
    if not path.is_file() or _sha256(path) != expected_hash or path.stat().st_size != expected_size:
        raise RotterdamSiteProposalV2ValidationError(f"{option} SVG artifact mismatch")
    root = ET.parse(path).getroot()
    if root.attrib.get("viewBox") != "0 0 1240 850" or root.attrib.get("width") != "1240" or root.attrib.get("height") != "850":
        raise RotterdamSiteProposalV2ValidationError(f"{option} SVG viewport is not the shared 1240x850 view")
    text = "".join(root.itertext()).casefold()
    required = (f"boundary option {option.casefold()}", "proposed", "human selection required", "rail", "station", "epsg:28992", "source / timestamp", "attribution")
    missing = [item for item in required if item not in text]
    if missing:
        raise RotterdamSiteProposalV2ValidationError(f"{option} SVG metadata mismatch: {', '.join(missing)}")
    layers = [element.attrib.get("id") for element in root if element.attrib.get("data-map-layer")]
    if layers.count("layer-boundary") != 1 or "layer-boundary-option-b" in layers:
        raise RotterdamSiteProposalV2ValidationError(f"{option} SVG renders more than its declared boundary")
    boundaries = [element for element in root.iter() if element.attrib.get("data-boundary-option")]
    if len(boundaries) != 1 or boundaries[0].attrib.get("data-boundary-option") != option:
        raise RotterdamSiteProposalV2ValidationError(f"{option} SVG boundary declaration is inconsistent")
    if "rail / station" in text:
        raise RotterdamSiteProposalV2ValidationError(f"{option} legend still conflates rail and station")
    public = next((element for element in root if element.attrib.get("id") == "layer-public-space"), None)
    rail = next((element for element in root if element.attrib.get("id") == "layer-rail"), None)
    if public is None or rail is None or any("stroke-dasharray" in element.attrib for element in public.iter()):
        raise RotterdamSiteProposalV2ValidationError(f"{option} public/open style is invalid")
    if not any(element.attrib.get("data-style") == "rail-paired-sleeper" for element in rail.iter()):
        raise RotterdamSiteProposalV2ValidationError(f"{option} rail style is not distinct")
    boundary_elements = set(boundaries[0].iter())
    for element in root.iter():
        value = element.attrib.get("stroke-width")
        if value is None:
            continue
        try:
            width = float(value)
        except ValueError as exc:
            raise RotterdamSiteProposalV2ValidationError(f"{option} SVG stroke width is invalid") from exc
        is_boundary = element in boundary_elements or str(element.attrib.get("data-legend-swatch", "")).startswith("boundary")
        if width <= 0 or width > (2.0 if is_boundary else 1.5):
            raise RotterdamSiteProposalV2ValidationError(f"{option} SVG stroke width exceeds declared limit")
    return {"layers": layers, "boundary_count": len(boundaries)}


def _comparison_metadata(path: Path, expected_hash: str, expected_size: int) -> dict[str, Any]:
    if not path.is_file() or _sha256(path) != expected_hash or path.stat().st_size != expected_size:
        raise RotterdamSiteProposalV2ValidationError("comparison SVG artifact mismatch")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise RotterdamSiteProposalV2ValidationError("comparison SVG is not well-formed XML") from exc
    if root.attrib.get("viewBox") != "0 0 2480 900" or root.attrib.get("width") != "2480" or root.attrib.get("height") != "900":
        raise RotterdamSiteProposalV2ValidationError("comparison SVG must use the declared side-by-side viewport")
    text = "".join(root.itertext()).casefold()
    required = ("side-by-side comparison", "option a", "option b", "area delta", "perimeter delta", "neither preferred", "epsg:28992")
    missing = [item for item in required if item not in text]
    if missing:
        raise RotterdamSiteProposalV2ValidationError("comparison SVG metadata missing: " + ", ".join(missing))
    panels = [element for element in root if element.tag.rsplit("}", 1)[-1] == "g" and element.attrib.get("data-comparison-panel")]
    if len(panels) != 2 or {panel.attrib.get("data-comparison-panel") for panel in panels} != {"A", "B"}:
        raise RotterdamSiteProposalV2ValidationError("comparison SVG must contain exactly two named panels")
    boundaries = [element for element in root.iter() if element.attrib.get("data-boundary-option")]
    if len(boundaries) != 2 or {element.attrib.get("data-boundary-option") for element in boundaries} != {"A", "B"}:
        raise RotterdamSiteProposalV2ValidationError("comparison SVG must contain one boundary per panel")
    for option in ("A", "B"):
        panel = next(panel for panel in panels if panel.attrib.get("data-comparison-panel") == option)
        panel_boundaries = [element for element in panel.iter() if element.attrib.get("data-boundary-option")]
        if len(panel_boundaries) != 1 or panel_boundaries[0].attrib.get("data-boundary-option") != option:
            raise RotterdamSiteProposalV2ValidationError("comparison SVG panel boundary does not match its option")
    return {"panel_count": len(panels), "boundary_count": len(boundaries)}


def validate_site_proposal_rotterdam_v2(proposal: SiteProposal | Mapping[str, Any], package_root: str | Path, *, v1_root: str | Path | None = None) -> SiteProposal:
    """Validate the complete append-only M2-R03 Rotterdam v2 package."""

    root = Path(package_root)
    candidate = proposal if isinstance(proposal, SiteProposal) else SiteProposal.model_validate(proposal)
    if candidate.id != "site-proposal-rotterdam-m4h-v2" or candidate.version.casefold() != "v2":
        raise RotterdamSiteProposalV2ValidationError("M2-R03 validator requires site-proposal-rotterdam-m4h-v2 version v2")
    if candidate.supersedes_proposal_id != "site-proposal-rotterdam-m4h-v1":
        raise RotterdamSiteProposalV2ValidationError("v2 must supersede the Rotterdam v1 proposal")
    try:
        validate_site_proposal(candidate, root)
    except SiteProposalValidationError as exc:
        raise RotterdamSiteProposalV2ValidationError(str(exc)) from exc
    context = candidate.delft_context
    if candidate.status != "PROPOSED" or candidate.human_decision_status != "HUMAN_DECISION_REQUIRED":
        raise RotterdamSiteProposalV2ValidationError("v2 proposal must remain proposed and awaiting human decision")
    if context.get("boundary_selection_status") != "AMBIGUOUS_HUMAN_SELECTION_REQUIRED" or context.get("human_choice_required") is not True:
        raise RotterdamSiteProposalV2ValidationError("both options must remain unselected")
    if context.get("display_only") is not True:
        raise RotterdamSiteProposalV2ValidationError("v2 display status must remain provisional")
    validate_source_edge_relationships(candidate, root, require_evidence=True)
    if context.get("containment_status") != "WITHIN_INDEPENDENT_MUNICIPAL_BOUNDARY" or context.get("evidence_ref") != "source-pdok-rotterdam-municipality":
        raise RotterdamSiteProposalV2ValidationError("independent Rotterdam containment evidence is required")
    _validate_municipality(candidate, root)
    records = _validate_sources(candidate, root)
    if not {record.id for record in records}.issuperset(candidate.source_refs):
        raise RotterdamSiteProposalV2ValidationError("proposal source_refs are not all retained")
    claims_path_value = context.get("human_context_claims_path")
    if not isinstance(claims_path_value, str) or not _safe(root, claims_path_value).is_file():
        raise RotterdamSiteProposalV2ValidationError("human-context claims artifact is required")
    options = context.get("boundary_options")
    if not isinstance(options, Mapping):
        raise RotterdamSiteProposalV2ValidationError("v2 boundary options are missing")
    if set(options) != {"A", "B"}:
        raise RotterdamSiteProposalV2ValidationError("both v2 boundary options are required")
    if canonical_geometry_hash(candidate.geometry) != options["A"].get("projected_geometry_sha256"):
        raise RotterdamSiteProposalV2ValidationError("proposal geometry is not corrected Option A")
    if options["A"].get("projected_geometry_sha256") == options["B"].get("projected_geometry_sha256"):
        raise RotterdamSiteProposalV2ValidationError("Option A and B geometries must remain distinct")
    for key in ("A", "B"):
        option = options[key]
        for artifact_field, hash_field in (("artifact_path", "wgs84_geometry_sha256"), ("projected_artifact_path", "projected_geometry_sha256")):
            artifact_path_value = option.get(artifact_field)
            if not isinstance(artifact_path_value, str):
                raise RotterdamSiteProposalV2ValidationError(f"Option {key} is missing {artifact_field}")
            artifact_path = _safe(root, artifact_path_value)
            if not artifact_path.is_file():
                raise RotterdamSiteProposalV2ValidationError(f"Option {key} artifact is missing")
            artifact_geometry = _geometry_from_geojson(json.loads(artifact_path.read_text(encoding="utf-8")))
            if canonical_geometry_hash(artifact_geometry) != option.get(hash_field):
                raise RotterdamSiteProposalV2ValidationError(f"Option {key} {artifact_field} geometry hash mismatch")
    maps = context.get("option_maps")
    if not isinstance(maps, Mapping) or set(maps) != {"A", "B"}:
        raise RotterdamSiteProposalV2ValidationError("separate A and B map metadata is required")
    viewport = context.get("viewport")
    if not isinstance(viewport, Mapping) or viewport.get("crs") != "EPSG:28992" or not isinstance(viewport.get("bbox"), list):
        raise RotterdamSiteProposalV2ValidationError("shared projected viewport is required")
    for key in ("A", "B"):
        item = maps[key]
        for field in ("svg_path", "svg_sha256", "svg_size_bytes", "png_path", "png_sha256", "png_size_bytes"):
            if field not in item:
                raise RotterdamSiteProposalV2ValidationError(f"Option {key} map metadata missing {field}")
        _svg_metadata(_safe(root, item["svg_path"]), item["svg_sha256"], item["svg_size_bytes"], key)
        _validate_png(_safe(root, item["png_path"]), item["png_sha256"], item["png_size_bytes"], (1240, 850))
    comparison = context.get("comparison_map")
    if not isinstance(comparison, Mapping):
        raise RotterdamSiteProposalV2ValidationError("side-by-side comparison metadata is required")
    _comparison_metadata(_safe(root, comparison["svg_path"]), comparison["svg_sha256"], comparison["svg_size_bytes"])
    comparison_svg = _safe(root, comparison["svg_path"]).read_text(encoding="utf-8").casefold()
    if "side-by-side comparison" not in comparison_svg or "area delta" not in comparison_svg or "perimeter delta" not in comparison_svg or "neither preferred" not in comparison_svg:
        raise RotterdamSiteProposalV2ValidationError("comparison SVG lacks explicit neutral numeric comparison")
    _validate_png(_safe(root, comparison["png_path"]), comparison["png_sha256"], comparison["png_size_bytes"], (2480, 900))
    deltas = context.get("comparison_deltas")
    if not isinstance(deltas, Mapping) or deltas.get("preference") != "NONE" or float(deltas.get("area_delta_m2", 0)) == 0 or float(deltas.get("perimeter_delta_m", 0)) == 0:
        raise RotterdamSiteProposalV2ValidationError("comparison deltas must be non-zero and neutral")
    render_path = _safe(root, str(context.get("comparison_render_record_path", "")))
    if not render_path.is_file():
        raise RotterdamSiteProposalV2ValidationError("comparison render record is missing")
    render = json.loads(render_path.read_text(encoding="utf-8"))
    if render.get("viewport") != viewport or render.get("same_scale") is not True or render.get("panel_count") != 2:
        raise RotterdamSiteProposalV2ValidationError("comparison render record does not prove shared scale and two panels")
    approval = _safe(root, candidate.approval_record_path).read_text(encoding="utf-8").casefold()
    for required in ("option a", "option b", "neither preferred", "no human decision", "approve", "reject"):
        if required not in approval:
            raise RotterdamSiteProposalV2ValidationError(f"approval record omits {required}")
    if "option a only" in approval or "option a only" in comparison_svg:
        raise RotterdamSiteProposalV2ValidationError("v2 approval or comparison text contradicts both-option review")
    parent_root_value = context.get("parent_v1_path")
    if not isinstance(parent_root_value, str):
        raise RotterdamSiteProposalV2ValidationError("v1 parent package path is required")
    parent_root = _safe(root, parent_root_value)
    if not parent_root.is_dir():
        raise RotterdamSiteProposalV2ValidationError("retained v1 parent directory is missing")
    parent_payload = json.loads((parent_root / "site-proposal.json").read_text(encoding="utf-8"))
    if parent_payload.get("id") != "site-proposal-rotterdam-m4h-v1" or parent_payload.get("status") != "PROPOSED":
        raise RotterdamSiteProposalV2ValidationError("retained v1 parent is not the Rotterdam proposed package")
    parent_manifest_path = _safe(root, str(context.get("parent_integrity_path", "")))
    if not parent_manifest_path.is_file():
        raise RotterdamSiteProposalV2ValidationError("v1 integrity manifest is missing")
    manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping) or manifest.get("parent_id") != "site-proposal-rotterdam-m4h-v1" or not isinstance(manifest.get("files"), list) or not manifest["files"]:
        raise RotterdamSiteProposalV2ValidationError("v1 integrity manifest is empty or malformed")
    for entry in manifest["files"]:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("retained_path"), str) or not isinstance(entry.get("relative_path"), str):
            raise RotterdamSiteProposalV2ValidationError("v1 integrity entry is malformed")
        retained = _safe(root, entry["retained_path"])
        if not retained.is_file() or retained.stat().st_size != entry.get("size_bytes") or _sha256(retained) != entry.get("sha256"):
            raise RotterdamSiteProposalV2ValidationError("retained v1 bytes failed integrity")
    if v1_root is not None:
        external = Path(v1_root)
        for entry in manifest["files"]:
            path = external / entry["relative_path"]
            if not path.is_file() or path.stat().st_size != entry.get("size_bytes") or _sha256(path) != entry.get("sha256"):
                raise RotterdamSiteProposalV2ValidationError("external v1 bytes failed integrity")
    state_path = _safe(root, str(context.get("state_path", "proposal-state.sqlite3")))
    from .store import ProjectStateStore
    with ProjectStateStore(state_path, read_only=True) as store:
        if store.current(candidate.project_id).get("site_id") is not None:
            raise RotterdamSiteProposalV2ValidationError("Project.site_id must remain null")
        if any(event.target_type == "HumanDecision" or event.action in {"Approve", "Accept"} for event in store.events(project_id=candidate.project_id)):
            raise RotterdamSiteProposalV2ValidationError("v2 state contains an approval or HumanDecision")
        if store.current(candidate.id).get("status") != "PROPOSED":
            raise RotterdamSiteProposalV2ValidationError("stored v2 proposal is not PROPOSED")
    return candidate


__all__ = ["RotterdamSiteProposalV2ValidationError", "point_segment_distance", "validate_source_edge_relationships", "validate_site_proposal_rotterdam_v2"]
