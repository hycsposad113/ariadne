"""Validation helpers for the M2-R02 map/layout revision (v3).

The v3 proposal is a presentation revision only. It carries a byte-preserved
v2 parent package, keeps the exact v2 boundary, and verifies that the new SVG
and rendered PNG are complete, bounded, and derived from retained evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from pathlib import PurePosixPath
import struct
from typing import Any, Mapping
import xml.etree.ElementTree as ET
import zlib

from .site_proposal import SiteProposal, SiteProposalValidationError, V2SourceRecord, validate_site_proposal
from .site_proposal_v2 import _verify_municipal_context


class SiteProposalV3ValidationError(SiteProposalValidationError):
    """Raised when the M2-R02 map revision is incomplete or tampered."""


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def verify_package_integrity(manifest_path: str | Path, package_root: str | Path) -> dict[str, Any]:
    """Re-hash every file listed by a package integrity manifest."""

    manifest = Path(manifest_path)
    root = Path(package_root)
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SiteProposalV3ValidationError("package integrity manifest cannot be read") from exc
    entries = payload.get("files") if isinstance(payload, Mapping) else None
    if not isinstance(entries, list) or not entries:
        raise SiteProposalV3ValidationError("package integrity manifest is empty")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise SiteProposalV3ValidationError("package integrity entry is malformed")
        relative = entry.get("path")
        relative_text = str(relative)
        relative_path = PurePosixPath(relative_text)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise SiteProposalV3ValidationError(f"package integrity path escapes package root: {relative_text}")
        path = root / relative_path
        if (
            not path.is_file()
            or path.stat().st_size != entry.get("size_bytes")
            or _sha256(path) != entry.get("sha256")
        ):
            raise SiteProposalV3ValidationError(f"package artifact integrity mismatch: {relative}")
    return {"file_count": len(entries), "manifest_sha256": _sha256(manifest)}


def _viewbox(root: ET.Element) -> tuple[float, float, float, float]:
    raw = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if not raw:
        raise SiteProposalV3ValidationError("SVG viewBox is required")
    try:
        values = tuple(float(part) for part in raw.replace(",", " ").split())
    except ValueError as exc:
        raise SiteProposalV3ValidationError("SVG viewBox is not numeric") from exc
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise SiteProposalV3ValidationError("SVG viewBox must contain a positive rectangle")
    return values  # type: ignore[return-value]


def _bbox(raw: str, *, label: str) -> tuple[float, float, float, float]:
    try:
        values = tuple(float(part) for part in raw.replace(",", " ").split())
    except ValueError as exc:
        raise SiteProposalV3ValidationError(f"{label} layout bounds are not numeric") from exc
    if len(values) != 4 or values[2] < 0 or values[3] < 0:
        raise SiteProposalV3ValidationError(f"{label} layout bounds are invalid")
    return values  # type: ignore[return-value]


def _inside(outer: tuple[float, float, float, float], inner: tuple[float, float, float, float]) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ox <= ix and oy <= iy and ix + iw <= ox + ow and iy + ih <= oy + oh


def validate_layout_svg(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_size_bytes: int | None = None,
) -> dict[str, Any]:
    """Validate SVG viewport, declared layout boxes, labels, and layer order."""

    svg = Path(path)
    if not svg.is_file() or svg.stat().st_size == 0:
        raise SiteProposalV3ValidationError("v3 SVG artifact is missing or empty")
    if expected_sha256 is not None and _sha256(svg) != expected_sha256:
        raise SiteProposalV3ValidationError("v3 SVG artifact hash mismatch")
    if expected_size_bytes is not None and svg.stat().st_size != expected_size_bytes:
        raise SiteProposalV3ValidationError("v3 SVG artifact size mismatch")
    try:
        root = ET.parse(svg).getroot()
    except (OSError, ET.ParseError) as exc:
        raise SiteProposalV3ValidationError("v3 SVG is not well-formed XML") from exc
    viewbox = _viewbox(root)
    declared: dict[str, tuple[float, float, float, float]] = {}
    for element in root.iter():
        raw = element.attrib.get("data-layout-bbox")
        if raw:
            element_id = element.attrib.get("id", element.tag)
            declared[element_id] = _bbox(raw, label=element_id)
            if not _inside(viewbox, declared[element_id]):
                raise SiteProposalV3ValidationError(f"{element_id} layout bounds exceed SVG viewBox")
    required_boxes = {"title", "subtitle", "map-frame", "legend", "footer-tags", "footer-source", "footer-attribution"}
    missing_boxes = sorted(required_boxes - declared.keys())
    if missing_boxes:
        raise SiteProposalV3ValidationError("SVG layout boxes missing: " + ", ".join(missing_boxes))
    text = "".join(root.itertext()).casefold()
    required_labels = (
        "proposed boundary",
        "delft station",
        "oude lijn railway",
        "buitenwatersloot canal",
        "houttuinen",
        "roads / walk paths",
        "buildings",
        "public spaces",
        "shops",
        "north",
        "scale",
        "legend",
        "epsg:28992",
        "source / timestamp",
        "attribution",
    )
    missing_labels = [label for label in required_labels if label not in text]
    if missing_labels:
        raise SiteProposalV3ValidationError("SVG labels missing: " + ", ".join(missing_labels))
    layer_ids = [element.attrib.get("id") for element in root if element.attrib.get("data-map-layer")]
    required_layers = ["layer-water", "layer-public-space", "layer-buildings", "layer-roads", "layer-rail", "layer-boundary", "layer-markers"]
    if any(layer not in layer_ids for layer in required_layers):
        raise SiteProposalV3ValidationError("SVG map layers are incomplete")
    if layer_ids.index("layer-boundary") <= max(layer_ids.index(layer) for layer in required_layers[:5]):
        raise SiteProposalV3ValidationError("proposed boundary must be above context layers")
    boundary_group = next(element for element in root if element.attrib.get("id") == "layer-boundary")
    boundary_paths = [element for element in boundary_group.iter() if element.tag.rsplit("}", 1)[-1] in {"path", "polygon", "polyline"}]
    if not boundary_paths:
        raise SiteProposalV3ValidationError("proposed boundary geometry is missing")
    if not any(float(element.attrib.get("stroke-width", "0")) > 0 and float(element.attrib.get("fill-opacity", "0")) > 0 for element in boundary_paths):
        raise SiteProposalV3ValidationError("proposed boundary must have visible stroke and fill")
    return {"viewbox": viewbox, "layout_boxes": declared, "layer_order": layer_ids}


def validate_rendered_png(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_size_bytes: int | None = None,
    expected_dimensions: tuple[int, int] = (1240, 850),
) -> dict[str, Any]:
    """Validate PNG signature, dimensions, and non-uniform rendered pixels."""

    png = Path(path)
    if not png.is_file() or png.stat().st_size == 0:
        raise SiteProposalV3ValidationError("rendered PNG artifact is missing or empty")
    if expected_sha256 is not None and _sha256(png) != expected_sha256:
        raise SiteProposalV3ValidationError("rendered PNG artifact hash mismatch")
    if expected_size_bytes is not None and png.stat().st_size != expected_size_bytes:
        raise SiteProposalV3ValidationError("rendered PNG artifact size mismatch")
    raw = png.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise SiteProposalV3ValidationError("rendered artifact is not a PNG")
    offset = 8
    dimensions: tuple[int, int] | None = None
    compressed = bytearray()
    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        body = raw[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR" and len(body) >= 13:
            dimensions = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            break
    if dimensions != expected_dimensions:
        raise SiteProposalV3ValidationError(f"rendered PNG dimensions are {dimensions}, expected {expected_dimensions}")
    try:
        decoded = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise SiteProposalV3ValidationError("rendered PNG pixel stream cannot be decoded") from exc
    if len(set(decoded)) <= 4 or not any(decoded):
        raise SiteProposalV3ValidationError("rendered PNG appears blank or uniform")
    return {"dimensions": dimensions, "decoded_bytes": len(decoded)}


def _validate_source_records(proposal: SiteProposal, root: Path) -> list[V2SourceRecord]:
    if proposal.source_records_path is None:
        raise SiteProposalV3ValidationError("v3 source-record path is required")
    source_path = root / proposal.source_records_path
    if not source_path.is_file():
        raise SiteProposalV3ValidationError("v3 source-record artifact is missing")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    raw_records = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(raw_records, list) or not raw_records:
        raise SiteProposalV3ValidationError("v3 source-record artifact contains no records")
    records = [V2SourceRecord.model_validate(item) for item in raw_records]
    for record in records:
        if record.availability != "OBSERVED":
            continue
        artifact = root / str(record.artifact_path)
        if not artifact.is_file() or artifact.stat().st_size != record.artifact_size_bytes or _sha256(artifact) != record.artifact_sha256:
            raise SiteProposalV3ValidationError(f"v3 source artifact mismatch: {record.id}")
    return records


def validate_site_proposal_v3(
    proposal: SiteProposal | Mapping[str, Any],
    package_root: str | Path,
    *,
    v2_root: str | Path | None = None,
) -> SiteProposal:
    """Validate v3 lineage, exact boundary preservation, layout, and render."""

    root = Path(package_root)
    candidate = proposal if isinstance(proposal, SiteProposal) else SiteProposal.model_validate(proposal)
    if candidate.id != "site-proposal-delft-v3" or candidate.version.casefold() != "v3":
        raise SiteProposalV3ValidationError("v3 validator requires site-proposal-delft-v3 version v3")
    if candidate.supersedes_proposal_id != "site-proposal-delft-v2":
        raise SiteProposalV3ValidationError("v3 proposal must supersede site-proposal-delft-v2")
    try:
        validate_site_proposal(candidate, root)
    except SiteProposalValidationError as exc:
        # Keep the v3 public validator's error type stable even when the
        # shared boundary loader rejects a changed byte or CRS declaration.
        raise SiteProposalV3ValidationError(str(exc)) from exc
    context = candidate.delft_context
    parent_boundary_value = context.get("parent_boundary_path")
    if not isinstance(parent_boundary_value, str):
        raise SiteProposalV3ValidationError("v2 parent boundary path is required")
    boundary_path = root / candidate.boundary_artifact_path
    parent_boundary_path = root / parent_boundary_value
    if not parent_boundary_path.is_file() or parent_boundary_path.read_bytes() != boundary_path.read_bytes():
        raise SiteProposalV3ValidationError("v3 boundary bytes differ from v2 boundary bytes")
    if context.get("parent_boundary_sha256") != _sha256(parent_boundary_path) or candidate.boundary_sha256 != context.get("parent_boundary_sha256"):
        raise SiteProposalV3ValidationError("v3 boundary hash does not match preserved v2 boundary")
    parent_root = root / "parent-v2"
    integrity_result = verify_package_integrity(root / "v2-integrity.json", parent_root)
    if v2_root is not None:
        verify_package_integrity(root / "v2-integrity.json", v2_root)
    records = _validate_source_records(candidate, root)
    _verify_municipal_context(candidate, root)
    exact = next((record for record in records if record.id == "source-osm-exact-polygon-context"), None)
    if exact is None or exact.parameters.get("query_boundary_sha256") != context.get("candidate_boundary_wgs84_sha256"):
        raise SiteProposalV3ValidationError("v3 exact OSM query is not linked to the preserved boundary")
    exact_payload = json.loads((root / str(exact.artifact_path)).read_text(encoding="utf-8"))
    retained_ids = {str(item.get("id")) for item in exact_payload.get("elements", []) if isinstance(item, Mapping) and item.get("type") == "way"}
    edge_ids = {str(edge.get("osm_way_id")) for edge in candidate.selection_criteria.get("edges", []) if isinstance(edge, Mapping)}
    if not edge_ids or not edge_ids.issubset(retained_ids):
        raise SiteProposalV3ValidationError("v3 selection edges are absent from preserved OSM bytes")
    render_record_value = context.get("render_record_path")
    png_value = context.get("rendered_png_path")
    if not isinstance(render_record_value, str) or not isinstance(png_value, str):
        raise SiteProposalV3ValidationError("v3 render record and PNG paths are required")
    render_record_path = root / render_record_value
    try:
        render_record = json.loads(render_record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SiteProposalV3ValidationError("v3 render record cannot be read") from exc
    svg_hash = context.get("map_svg_sha256")
    png_hash = context.get("rendered_png_sha256")
    layout = validate_layout_svg(root / candidate.map_preview_path, expected_sha256=svg_hash, expected_size_bytes=context.get("map_svg_size_bytes"))
    render = validate_rendered_png(root / png_value, expected_sha256=png_hash, expected_size_bytes=context.get("rendered_png_size_bytes"))
    if render_record.get("svg_sha256") != svg_hash or render_record.get("png_sha256") != png_hash:
        raise SiteProposalV3ValidationError("v3 render record hashes do not match outputs")
    viewport = render_record.get("viewport")
    margin_m = viewport.get("margin_m") if isinstance(viewport, Mapping) else None
    if (
        not isinstance(viewport, Mapping)
        or viewport.get("crs") != "EPSG:28992"
        or not isinstance(margin_m, (int, float))
        or isinstance(margin_m, bool)
        or not math.isfinite(float(margin_m))
        or margin_m <= 0
    ):
        raise SiteProposalV3ValidationError("v3 viewport must declare a positive projected-metre margin")
    if render_record.get("context_geometry_clipped") is not True or render_record.get("boundary_above_context") is not True:
        raise SiteProposalV3ValidationError("v3 render record does not prove clipping and layer order")
    return candidate


__all__ = [
    "SiteProposalV3ValidationError",
    "validate_layout_svg",
    "validate_rendered_png",
    "validate_site_proposal_v3",
    "verify_package_integrity",
]
