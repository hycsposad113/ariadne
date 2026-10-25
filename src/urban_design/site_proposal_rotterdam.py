"""Fail-closed validation for the M2-T02 Rotterdam M4H alternative.

The Rotterdam package is a sibling alternative to the Delft proposals.  It
does not change the shared ``SiteProposal`` contract or make a site effective.
The module adds the checks that are specific to the M4H source package:
independent Rotterdam containment, explicit A/B boundary ambiguity, retained
source bytes, readable static cartography, and proposed-only ledger state.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path, PurePosixPath
import struct
import xml.etree.ElementTree as ET
import zlib
from typing import Any, Mapping, Sequence

from .geometry import GeometryValidationError, canonical_geometry_hash, polygon_area, polygon_perimeter, validate_geometry
from .site_proposal import SiteProposal, SiteProposalValidationError, V2SourceRecord, validate_site_proposal


class RotterdamSiteProposalValidationError(SiteProposalValidationError):
    """Raised when the M4H alternative cannot be defended or replayed."""


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _safe(root: Path, relative: str) -> Path:
    path = PurePosixPath(str(relative).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise RotterdamSiteProposalValidationError(f"unsafe package path: {relative}")
    return root / path


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
            return _geometry_from_geojson(features[0])
    raise RotterdamSiteProposalValidationError("GeoJSON artifact must contain one Polygon or MultiPolygon")


def _point_on_segment(point: tuple[float, float], a: Sequence[float], b: Sequence[float]) -> bool:
    cross = (float(b[0]) - float(a[0])) * (point[1] - float(a[1])) - (float(b[1]) - float(a[1])) * (point[0] - float(a[0]))
    return abs(cross) <= 1e-10 and min(float(a[0]), float(b[0])) - 1e-10 <= point[0] <= max(float(a[0]), float(b[0])) + 1e-10 and min(float(a[1]), float(b[1])) - 1e-10 <= point[1] <= max(float(a[1]), float(b[1])) + 1e-10


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


def _inside_summary(point: tuple[float, float], summary: Mapping[str, Any]) -> bool:
    polygons = [summary["coordinates"]] if summary["type"] == "Polygon" else summary["coordinates"]
    return any(_inside_ring(point, polygon[0]) and not any(_inside_ring(point, hole) for hole in polygon[1:]) for polygon in polygons)


def _inside(point: tuple[float, float], geometry: Mapping[str, Any]) -> bool:
    return _inside_summary(point, validate_geometry(geometry))


def _ring_points(geometry: Mapping[str, Any]) -> list[tuple[float, float]]:
    summary = validate_geometry(geometry)
    if summary["type"] != "Polygon" or len(summary["coordinates"]) != 1:
        raise RotterdamSiteProposalValidationError("M4H boundary options must be single-ring Polygons")
    return [(float(x), float(y)) for x, y in summary["coordinates"][0][:-1]]


def _validate_png(path: Path, *, expected_hash: str | None = None, expected_size: int | None = None) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise RotterdamSiteProposalValidationError("rendered PNG is missing or empty")
    if expected_hash and _sha256(path) != expected_hash:
        raise RotterdamSiteProposalValidationError("rendered PNG hash mismatch")
    if expected_size is not None and path.stat().st_size != expected_size:
        raise RotterdamSiteProposalValidationError("rendered PNG size mismatch")
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise RotterdamSiteProposalValidationError("rendered artifact is not a PNG")
    width, height = struct.unpack(">II", raw[16:24])
    if width <= 0 or height <= 0:
        raise RotterdamSiteProposalValidationError("rendered PNG dimensions are invalid")
    chunks: list[bytes] = []
    offset = 8
    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        data = raw[offset + 8 : offset + 8 + length]
        offset += length + 12
        if kind == b"IDAT":
            chunks.append(data)
        if kind == b"IEND":
            break
    if not chunks:
        raise RotterdamSiteProposalValidationError("rendered PNG has no IDAT data")
    try:
        decoded = zlib.decompress(b"".join(chunks))
    except zlib.error as exc:
        raise RotterdamSiteProposalValidationError("rendered PNG pixels cannot be decoded") from exc
    if len(set(decoded)) <= 4:
        raise RotterdamSiteProposalValidationError("rendered PNG appears uniform")
    return {"dimensions": (width, height), "decoded_bytes": len(decoded)}


def _validate_svg(path: Path, *, expected_hash: str | None = None, expected_size: int | None = None) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise RotterdamSiteProposalValidationError("M4H SVG is missing or empty")
    if expected_hash and _sha256(path) != expected_hash:
        raise RotterdamSiteProposalValidationError("M4H SVG hash mismatch")
    if expected_size is not None and path.stat().st_size != expected_size:
        raise RotterdamSiteProposalValidationError("M4H SVG size mismatch")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise RotterdamSiteProposalValidationError("M4H SVG is not well-formed XML") from exc
    viewbox = tuple(float(item) for item in (root.attrib.get("viewBox", "").replace(",", " ").split()))
    if len(viewbox) != 4 or viewbox[2] <= 0 or viewbox[3] <= 0:
        raise RotterdamSiteProposalValidationError("M4H SVG viewBox is invalid")
    text = "".join(root.itertext()).casefold()
    required = ("proposed boundary", "option a", "option b", "keilehaven", "keileweg", "keilestraat", "vierhavensstraat", "dakpark", "getijdenpark keilehaven", "roads / walk paths", "buildings", "rail / station", "water", "public / open space", "north", "100 m", "legend", "epsg:28992", "source / timestamp", "attribution", "ambiguous")
    missing = [token for token in required if token not in text]
    if missing:
        raise RotterdamSiteProposalValidationError("M4H SVG labels missing: " + ", ".join(missing))
    layer_ids = [element.attrib.get("id") for element in root if element.attrib.get("data-map-layer")]
    expected_layers = ["layer-water", "layer-public-space", "layer-buildings", "layer-roads", "layer-rail", "layer-boundary", "layer-boundary-option-b", "layer-markers"]
    if any(layer not in layer_ids for layer in expected_layers):
        raise RotterdamSiteProposalValidationError("M4H SVG map layers are incomplete")
    if layer_ids.index("layer-boundary") <= layer_ids.index("layer-rail"):
        raise RotterdamSiteProposalValidationError("proposed boundary must be above context layers")
    boundary = next(element for element in root if element.attrib.get("id") == "layer-boundary")
    paths = [element for element in boundary.iter() if element.tag.rsplit("}", 1)[-1] in {"polygon", "polyline", "path"}]
    if not paths or not any(float(item.attrib.get("stroke-width", "0")) <= 2.0 and float(item.attrib.get("fill-opacity", "0")) <= 0.08 and float(item.attrib.get("stroke-width", "0")) > 0 for item in paths):
        raise RotterdamSiteProposalValidationError("primary boundary must be a visible thin red outline with low-opacity fill")
    public = next(element for element in root if element.attrib.get("id") == "layer-public-space")
    rail = next(element for element in root if element.attrib.get("id") == "layer-rail")
    if any("stroke-dasharray" in element.attrib for element in public.iter()):
        raise RotterdamSiteProposalValidationError("public/open space must not use dashed strokes")
    if not any(element.attrib.get("data-style") == "rail-paired-sleeper" for element in rail.iter()):
        raise RotterdamSiteProposalValidationError("rail layer must use the distinct paired/sleeper style")
    legend = next((element for element in root if element.attrib.get("id") == "legend"), None)
    if legend is None:
        raise RotterdamSiteProposalValidationError("SVG legend is missing")
    swatches = [element.attrib.get("data-legend-swatch") for element in legend.iter() if element.attrib.get("data-legend-swatch")]
    if len(swatches) < 7 or len(set(swatches)) != len(swatches):
        raise RotterdamSiteProposalValidationError("legend swatches must be actual and unique")
    return {"viewbox": viewbox, "layer_order": layer_ids, "legend_swatches": swatches}


def _validate_sources(candidate: SiteProposal, root: Path) -> list[V2SourceRecord]:
    if not candidate.source_records_path:
        raise RotterdamSiteProposalValidationError("source-record path is required")
    source_path = _safe(root, candidate.source_records_path)
    if not source_path.is_file():
        raise RotterdamSiteProposalValidationError("source-record artifact is missing")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    raw_records = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(raw_records, list) or not raw_records:
        raise RotterdamSiteProposalValidationError("source-record artifact contains no records")
    records = [V2SourceRecord.model_validate(item) for item in raw_records]
    for record in records:
        if record.availability != "OBSERVED":
            continue
        artifact = _safe(root, str(record.artifact_path))
        if not artifact.is_file() or artifact.stat().st_size != record.artifact_size_bytes or _sha256(artifact) != record.artifact_sha256:
            raise RotterdamSiteProposalValidationError(f"source artifact mismatch: {record.id}")
    return records


@lru_cache(maxsize=8)
def _cached_municipality(path_string: str, expected_hash: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    path = Path(path_string)
    payload = json.loads(path.read_text(encoding="utf-8"))
    geometry = _geometry_from_geojson(payload)
    # The PDOK Rotterdam feature is a large official MultiPolygon.  Its
    # validator needs finite, closed rings and a stable hash; a full pairwise
    # self-intersection scan would make every replay unnecessarily quadratic.
    # The retained bytes are immutable and option containment is checked below
    # with sampled boundary vertices, so validate the structural contract in
    # linear time here.
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type not in {"Polygon", "MultiPolygon"} or not isinstance(coordinates, list) or not coordinates:
        raise RotterdamSiteProposalValidationError("Rotterdam municipality geometry is malformed")
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise RotterdamSiteProposalValidationError("Rotterdam municipality geometry has no exterior ring")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1] or len({tuple(point) for point in ring[:-1]}) < 3:
                raise RotterdamSiteProposalValidationError("Rotterdam municipality ring is not closed and non-degenerate")
            for point in ring:
                if not isinstance(point, list) or len(point) != 2 or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in point):
                    raise RotterdamSiteProposalValidationError("Rotterdam municipality coordinate is not finite 2D")
    canonical = json.dumps({"type": geometry_type, "coordinates": coordinates}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    summary = {"type": geometry_type, "coordinates": coordinates}
    return payload, summary, "sha256:" + hashlib.sha256(canonical).hexdigest()


def _validate_municipality(candidate: SiteProposal, root: Path) -> None:
    context = candidate.delft_context
    path_value = context.get("municipality_feature_path")
    expected_hash = context.get("municipality_feature_sha256")
    if not isinstance(path_value, str) or not isinstance(expected_hash, str):
        raise RotterdamSiteProposalValidationError("independent Rotterdam municipality artifact and hash are required")
    path = _safe(root, path_value)
    if not path.is_file() or _sha256(path) != expected_hash:
        raise RotterdamSiteProposalValidationError("Rotterdam municipality artifact hash mismatch")
    payload, municipality_summary, municipality_hash = _cached_municipality(path.as_posix(), expected_hash)
    if payload.get("properties", {}).get("naam") != "Rotterdam" or payload.get("properties", {}).get("code") != "0599":
        raise RotterdamSiteProposalValidationError("municipality artifact is not Rotterdam code 0599")
    if context.get("municipality_geometry_sha256") != municipality_hash:
        raise RotterdamSiteProposalValidationError("Rotterdam municipality geometry hash mismatch")
    options = context.get("boundary_options")
    if not isinstance(options, Mapping) or set(options) != {"A", "B"}:
        raise RotterdamSiteProposalValidationError("both A and B boundary options are required")
    for key in ("A", "B"):
        option = options[key]
        if not isinstance(option, Mapping):
            raise RotterdamSiteProposalValidationError(f"boundary option {key} is malformed")
        ring = option.get("wgs84_geometry")
        if not isinstance(ring, Mapping):
            raise RotterdamSiteProposalValidationError(f"boundary option {key} WGS84 geometry is missing")
        validate_geometry(ring)
        points = _ring_points(ring)
        if not all(_inside_summary(point, municipality_summary) for point in points):
            raise RotterdamSiteProposalValidationError(f"boundary option {key} is outside Rotterdam municipality")
        if option.get("wgs84_geometry_sha256") != canonical_geometry_hash(ring):
            raise RotterdamSiteProposalValidationError(f"boundary option {key} WGS84 hash mismatch")
        projected = option.get("projected_geometry")
        if not isinstance(projected, Mapping):
            raise RotterdamSiteProposalValidationError(f"boundary option {key} projected geometry is missing")
        validate_geometry(projected)
        if option.get("projected_geometry_sha256") != canonical_geometry_hash(projected):
            raise RotterdamSiteProposalValidationError(f"boundary option {key} projected geometry hash mismatch")
        measured = option.get("measurements")
        if not isinstance(measured, Mapping) or not math.isclose(float(measured.get("area_m2", 0)), polygon_area(projected), abs_tol=1e-7) or not math.isclose(float(measured.get("perimeter_m", 0)), polygon_perimeter(projected), abs_tol=1e-7):
            raise RotterdamSiteProposalValidationError(f"boundary option {key} measurements do not match geometry")


def _validate_parent_integrity(candidate: SiteProposal, root: Path) -> None:
    manifest_value = candidate.delft_context.get("delft_parent_integrity_path")
    if not isinstance(manifest_value, str):
        raise RotterdamSiteProposalValidationError("Delft parent integrity manifest is required")
    manifest_path = _safe(root, manifest_value)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("files") if isinstance(payload, Mapping) else None
    if not isinstance(entries, list) or not entries:
        raise RotterdamSiteProposalValidationError("Delft parent integrity manifest is empty")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise RotterdamSiteProposalValidationError("Delft parent integrity entry is malformed")
        retained = _safe(root, str(entry.get("retained_path", "")))
        if not retained.is_file() or retained.stat().st_size != entry.get("size_bytes") or _sha256(retained) != entry.get("sha256"):
            raise RotterdamSiteProposalValidationError(f"retained Delft parent bytes changed: {entry.get('retained_path')}")
        external = Path(str(entry.get("external_path", "")))
        if external.is_file() and (external.stat().st_size != entry.get("size_bytes") or _sha256(external) != entry.get("sha256")):
            raise RotterdamSiteProposalValidationError(f"external Delft parent bytes changed: {entry.get('external_path')}")


def validate_site_proposal_rotterdam(proposal: SiteProposal | Mapping[str, Any], package_root: str | Path) -> SiteProposal:
    """Validate a complete proposed-only M4H package."""

    root = Path(package_root)
    candidate = proposal if isinstance(proposal, SiteProposal) else SiteProposal.model_validate(proposal)
    if candidate.id != "site-proposal-rotterdam-m4h-v1" or candidate.version.casefold() != "v1":
        raise RotterdamSiteProposalValidationError("M4H validator requires site-proposal-rotterdam-m4h-v1 version v1")
    if candidate.status != "PROPOSED" or candidate.human_decision_status != "HUMAN_DECISION_REQUIRED":
        raise RotterdamSiteProposalValidationError("M4H proposal must remain proposed and awaiting human decision")
    try:
        validate_site_proposal(candidate, root)
    except SiteProposalValidationError as exc:
        raise RotterdamSiteProposalValidationError(str(exc)) from exc
    context = candidate.delft_context
    if context.get("containment_status") != "WITHIN_INDEPENDENT_MUNICIPAL_BOUNDARY":
        raise RotterdamSiteProposalValidationError("independent Rotterdam containment status is required")
    if context.get("evidence_ref") != "source-pdok-rotterdam-municipality":
        raise RotterdamSiteProposalValidationError("Rotterdam municipality must be the containment evidence")
    if context.get("boundary_selection_status") != "AMBIGUOUS_HUMAN_SELECTION_REQUIRED" or context.get("human_choice_required") is not True:
        raise RotterdamSiteProposalValidationError("ambiguous boundary must remain explicitly human-selectable")
    if context.get("display_option") != "A" or context.get("display_only") is not True:
        raise RotterdamSiteProposalValidationError("display option A must be labelled provisional-only")
    _validate_municipality(candidate, root)
    options = context["boundary_options"]
    if canonical_geometry_hash(candidate.geometry) != options["A"].get("projected_geometry_sha256"):
        raise RotterdamSiteProposalValidationError("proposal geometry is not the displayed Option A geometry")
    if options["A"].get("projected_geometry_sha256") == options["B"].get("projected_geometry_sha256"):
        raise RotterdamSiteProposalValidationError("A and B boundary options must remain distinct")
    records = _validate_sources(candidate, root)
    if not {record.id for record in records}.issuperset(candidate.source_refs):
        raise RotterdamSiteProposalValidationError("proposal source_refs are not all retained")
    claims_value = context.get("human_context_claims_path")
    if not isinstance(claims_value, str):
        raise RotterdamSiteProposalValidationError("human-context claims path is required")
    claims_path = _safe(root, claims_value)
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    raw_claims = claims.get("claims") if isinstance(claims, Mapping) else None
    if not isinstance(raw_claims, list) or not raw_claims:
        raise RotterdamSiteProposalValidationError("human-context claims are missing")
    allowed_claims = {"HUMAN_PROVIDED_DESIGN_CONTEXT", "INTERPRETATION"}
    if any(item.get("classification") not in allowed_claims for item in raw_claims if isinstance(item, Mapping)):
        raise RotterdamSiteProposalValidationError("human context claims must be explicitly classified")
    svg_path = _safe(root, str(context.get("map_svg_path", candidate.map_preview_path or "")))
    _validate_svg(svg_path, expected_hash=context.get("map_svg_sha256"), expected_size=context.get("map_svg_size_bytes"))
    png_path = _safe(root, str(context.get("rendered_png_path", "")))
    _validate_png(png_path, expected_hash=context.get("rendered_png_sha256"), expected_size=context.get("rendered_png_size_bytes"))
    render_path = _safe(root, str(context.get("render_record_path", "")))
    render = json.loads(render_path.read_text(encoding="utf-8"))
    if render.get("svg_sha256") != context.get("map_svg_sha256") or render.get("png_sha256") != context.get("rendered_png_sha256"):
        raise RotterdamSiteProposalValidationError("render record hashes do not match map outputs")
    if render.get("crs") != "EPSG:28992" or render.get("context_geometry_clipped") is not True or render.get("boundary_above_context") is not True:
        raise RotterdamSiteProposalValidationError("render record lacks projected clipping/layer-order evidence")
    approval_path = _safe(root, candidate.approval_record_path)
    approval = approval_path.read_text(encoding="utf-8").casefold()
    if "human_decision_required" not in approval or "no human decision" not in approval or "approve" not in approval or "reject" not in approval:
        raise RotterdamSiteProposalValidationError("approval record must describe the human gate")
    _validate_parent_integrity(candidate, root)
    state_path = _safe(root, str(context.get("state_path", "proposal-state-rotterdam.sqlite3")))
    if state_path.is_file():
        from .store import ProjectStateStore
        with ProjectStateStore(state_path, read_only=True) as store:
            project = store.current(candidate.project_id)
            if project.get("site_id") is not None:
                raise RotterdamSiteProposalValidationError("Rotterdam project must not have an effective site")
            events = store.events(project_id=candidate.project_id)
            if any(event.target_type == "HumanDecision" or event.action in {"Approve", "Accept"} for event in events):
                raise RotterdamSiteProposalValidationError("proposal state contains an approval or HumanDecision")
            if store.current(candidate.id).get("status") != "PROPOSED":
                raise RotterdamSiteProposalValidationError("stored proposal is not PROPOSED")
    return candidate


__all__ = ["RotterdamSiteProposalValidationError", "validate_site_proposal_rotterdam"]
