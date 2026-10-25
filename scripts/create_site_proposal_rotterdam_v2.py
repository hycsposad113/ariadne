#!/usr/bin/env python3
"""Build the append-only M2-R03 Rotterdam M4H boundary-repair package.

The builder is deliberately offline.  It copies the complete v1 package,
recomputes the corrected Option A projection with the pinned GDAL executable,
records source vertex/segment distances, and emits separate option maps plus a
neutral side-by-side comparison.  An existing output directory is never
overwritten.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Mapping

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from create_site_proposal_rotterdam import (  # noqa: E402
    GDAL_OGR2OGR,
    PRODUCER as V1_PRODUCER,
    QGIS_PYTHON,
    _artifact,
    _geometry_from_transformed,
    _geojson_feature,
    _render_png,
    _render_svg,
    _transform,
)
from urban_design.geometry import canonical_geometry_hash, polygon_area, polygon_perimeter  # noqa: E402
from urban_design.site_proposal import SiteProposal, V2SourceRecord, canonical_json_bytes, sha256_file  # noqa: E402
from urban_design.site_proposal_rotterdam_v2 import _nearest_way, validate_site_proposal_rotterdam_v2  # noqa: E402
from urban_design.models import Site, SiteStatus  # noqa: E402
from urban_design.store import ProjectStateStore  # noqa: E402


PRODUCER = "urban-design-m2-r03-rotterdam-m4h/0.1"
PROJECT_ID = "rotterdam-m4h-pilot-project"
PROPOSAL_ID = "site-proposal-rotterdam-m4h-v2"
RUN_CREATED_AT = "2026-09-15T11:00:00+00:00"


class ProposalBuildError(RuntimeError):
    """Raised when retained v1 evidence cannot produce a reviewable v2 package."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _copy(source: Path, target: Path) -> None:
    if not source.is_file():
        raise ProposalBuildError(f"retained source is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _geometry(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("type") == "Feature":
        geometry = payload.get("geometry")
        if isinstance(geometry, Mapping):
            return {"type": geometry.get("type"), "coordinates": geometry.get("coordinates")}
    if payload.get("type") in {"Polygon", "MultiPolygon"}:
        return {"type": payload.get("type"), "coordinates": payload.get("coordinates")}
    raise ProposalBuildError("GeoJSON does not contain one Polygon/MultiPolygon geometry")


def _integrity_manifest(v1_root: Path, parent_root: Path, output: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for source in sorted((path for path in parent_root.rglob("*") if path.is_file()), key=lambda path: path.relative_to(parent_root).as_posix()):
        relative = source.relative_to(parent_root).as_posix()
        external = v1_root / relative
        entries.append({"relative_path": relative, "retained_path": (Path("parent-v1") / relative).as_posix(), "external_path": str(external.resolve()), "size_bytes": source.stat().st_size, "sha256": sha256_file(source)})
    payload = {"schema_version": "m2-r03-parent-v1-integrity", "parent_id": "site-proposal-rotterdam-m4h-v1", "files": entries}
    _write_json(output, payload)
    return payload


def _option_svg(source_svg: Path, output: Path, option: str) -> None:
    text = source_svg.read_text(encoding="utf-8")
    text = re.sub(r'<g id="layer-boundary-option-b"[^>]*>.*?</g>', "", text, flags=re.DOTALL)
    text = re.sub(r'<line data-legend-swatch="boundary-b".*?</text>\n', "", text, flags=re.DOTALL)
    text = text.replace('site-proposal-rotterdam-m4h-v1', PROPOSAL_ID)
    text = text.replace('data-boundary-option="A"', f'data-boundary-option="{option}"')
    text = text.replace('data-boundary-option="B"', f'data-boundary-option="{option}"')
    text = text.replace("Proposed boundary — Option A", f"Proposed boundary — Option {option}")
    text = text.replace("Rail / station", "Rail")
    title = f"Rotterdam M4H Vierhavenblok — MAP REVIEW v2 — OPTION {option}"
    subtitle = f"{PROPOSAL_ID} · PROPOSED · BOUNDARY OPTION {option} · HUMAN SELECTION REQUIRED · source-anchored control points; human-sketch connectors"
    text = re.sub(r'<text id="title"[^>]*>.*?</text>', f'<text id="title" data-layout-bbox="44 14 1152 34" x="44" y="40" font-family="sans-serif" font-size="25" font-weight="700" fill="#202427">{title}</text>', text, flags=re.DOTALL)
    text = re.sub(r'<text id="subtitle"[^>]*>.*?</text>', f'<text id="subtitle" data-layout-bbox="44 50 1152 34" x="44" y="68" class="meta">{subtitle}</text>', text, flags=re.DOTALL)
    output.write_text(text, encoding="utf-8")


def _comparison_svg(option_a_svg: Path, option_b_svg: Path, output: Path, deltas: Mapping[str, Any]) -> None:
    def body(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        body_text = text.split(">", 1)[1].rsplit("</svg>", 1)[0]
        # The outer comparison owns the canvas background so its metadata
        # remains visible above the two translated panels.
        return re.sub(r'<rect id="background"[^>]*/>', "", body_text)

    description = "Source-anchored control points; straight connectors are NOT_CLAIMED_HUMAN_SKETCH_CONNECTOR."
    content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="2480" height="900" viewBox="0 0 2480 900">
<rect x="0" y="0" width="2480" height="900" fill="#f7f7f7"/>
<text x="28" y="24" font-family="sans-serif" font-size="18" font-weight="700" fill="#202427">Side-by-side comparison — Option A and Option B — NEITHER PREFERRED</text>
<text x="28" y="43" font-family="sans-serif" font-size="11" fill="#4a5054">Area delta: {float(deltas['area_delta_m2']):.3f} m² ({float(deltas['area_delta_pct_of_a']):.3f}%). Perimeter delta: {float(deltas['perimeter_delta_m']):.3f} m ({float(deltas['perimeter_delta_pct_of_a']):.3f}%). EPSG:28992.</text>
<text x="28" y="58" font-family="sans-serif" font-size="10" fill="#4a5054">{description} A vs B edge interpretation: road control points versus harbour control points. Human selection required.</text>
<g data-comparison-panel="A" transform="translate(0,50)">{body(option_a_svg)}</g>
<g data-comparison-panel="B" transform="translate(1240,50)">{body(option_b_svg)}</g>
</svg>'''
    output.write_text(content, encoding="utf-8")


def _source_evidence(root: Path, context_path: Path, raw_path: Path, options: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    payload = json.loads(context_path.read_text(encoding="utf-8"))
    features = {str(feature.get("id")): feature for feature in payload.get("features", []) if isinstance(feature, Mapping) and feature.get("id") is not None}
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    ways = {str(item.get("id")): item for item in raw.get("elements", []) if isinstance(item, Mapping) and item.get("type") == "way"}
    point_specs = {
        "A": (("82806419", 0), ("7517828", 3), ("259184950", 8), ("7518596", 0)),
        "B": (("82806419", 0), ("82806419", 5), ("134702130", 41), ("134702130", 42)),
    }
    evidence_options: dict[str, Any] = {}
    for option_key in ("A", "B"):
        option = options[option_key]
        ring = option["projected_geometry"]["coordinates"][0][:-1]
        wgs84 = option["wgs84_geometry"]["coordinates"][0][:-1]
        controls: list[dict[str, Any]] = []
        for index, (way_id, vertex_index) in enumerate(point_specs[option_key]):
            if way_id not in ways:
                raise ProposalBuildError(f"required source way {way_id} is absent")
            vertices = ways[way_id].get("geometry", [])
            if vertex_index >= len(vertices):
                raise ProposalBuildError(f"source vertex {way_id}:{vertex_index} is absent")
            segment = [vertex_index, vertex_index + 1] if vertex_index < len(vertices) - 1 else [vertex_index - 1, vertex_index]
            nearest = _nearest_way(ring[index], features, way_id)
            controls.append({
                "control_point": chr(ord("A") + index),
                "coordinate_wgs84": list(wgs84[index]),
                "coordinate_epsg28992": list(ring[index]),
                "source_way_id": way_id,
                "source_way_ids": [way_id],
                "source_vertex_index": vertex_index,
                "source_segment": segment,
                "source_coordinate_wgs84": [float(vertices[vertex_index]["lon"]), float(vertices[vertex_index]["lat"])],
                "relationship_status": "SOURCE_VERTEX_OR_SEGMENT_WITHIN_TOLERANCE",
                "measured_distance_m": float(nearest["distance_m"]),
                "measured_segment_index": nearest["segment_index"],
                "measured_segment_fraction": nearest["segment_fraction"],
                "nearest_point_epsg28992": nearest["nearest_point_epsg28992"],
            })
        edges = []
        for first, second in zip("ABCD", "BCDA"):
            edges.append({"edge": f"{first}-{second}", "claim_status": "NOT_CLAIMED_HUMAN_SKETCH_CONNECTOR", "description": "Straight connector between source-derived control points; no mapped OSM edge claimed."})
        evidence_options[option_key] = {"control_points": controls, "boundary_edges": edges}
    return {"schema_version": "m2-r03-source-distance-evidence", "source_snapshot_path": str(raw_path.relative_to(root)).replace("\\", "/"), "source_snapshot_sha256": sha256_file(raw_path), "projected_context_path": str(context_path.relative_to(root)).replace("\\", "/"), "projected_context_sha256": sha256_file(context_path), "tolerance_m": 1.0, "options": evidence_options}


def _v2_source_records(parent_root: Path, root: Path, evidence_path: Path) -> list[dict[str, Any]]:
    original = json.loads((parent_root / "sources" / "source-records.json").read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for raw in original.get("records", []):
        record = dict(raw)
        if record.get("artifact_path"):
            record["artifact_path"] = (Path("parent-v1") / str(record["artifact_path"])).as_posix()
        coverage = record.get("coverage")
        if isinstance(coverage, dict):
            record["coverage"] = dict(coverage)
            for key, value in list(record["coverage"].items()):
                if isinstance(value, str) and key.endswith("_artifact") and not value.startswith("parent-v1/"):
                    record["coverage"][key] = (Path("parent-v1") / value).as_posix()
        if record.get("id") == "source-project-boundary-options":
            record["source_identity"] = "Retained v1 project-decision record (superseded relationship claim)"
            record["query"] = "Legacy v1 edge interpretation retained for lineage; superseded by M2-R03 measured source control-point evidence"
            record["limitations"] = ["Legacy v1 relationship is retained only as append-only history; M2-R03 rejects its unsupported Option A control point."]
        records.append(record)
    records.append({"id": "source-rotterdam-boundary-relationship-v2", "source_class": "PROJECT_DECISION", "availability": "OBSERVED", "publisher": "M2-R03 executor", "source_identity": "Measured relationship against retained OSM snapshot", "query": "Compute projected point-to-segment distance for each declared source control point; record source way, vertex, segment, tolerance, and connector claim status", "retrieved_at": RUN_CREATED_AT, "request_started_at": RUN_CREATED_AT, "request_finished_at": RUN_CREATED_AT, "request_url": "file:///m2-r03/source-distance-evidence.json", "version": "M2-R03", "license": "Project evidence; source licence remains in source-osm-m4h-context", "attribution": "Derived from retained OpenStreetMap context and deterministic local distance calculation", "parameters": {"tolerance_m": 1.0, "tool": "urban_design.site_proposal_rotterdam_v2.point_segment_distance"}, "validation_status": "VALIDATED", "artifact_path": evidence_path.relative_to(root).as_posix(), "artifact_sha256": sha256_file(evidence_path), "artifact_size_bytes": evidence_path.stat().st_size, "coverage": {"options": ["A", "B"], "control_points_per_option": 4}, "limitations": ["Only control-point relationships are claimed; ring connectors are explicitly human-sketch connectors without physical-edge claims."]})
    return records


def build_rotterdam_v2(output_dir: str | Path, *, v1_dir: str | Path, offline: bool = True) -> SiteProposal:
    if not offline:
        raise ProposalBuildError("M2-R03 builder is offline-only and requires retained v1 bytes")
    root = Path(output_dir).resolve()
    v1_root = Path(v1_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise ProposalBuildError(f"refusing to overwrite non-empty output directory: {root}")
    if not (v1_root / "site-proposal.json").is_file():
        raise ProposalBuildError(f"retained v1 package is missing: {v1_root / 'site-proposal.json'}")
    root.mkdir(parents=True, exist_ok=True)
    parent_root = root / "parent-v1"
    shutil.copytree(v1_root, parent_root)
    parent_payload = json.loads((parent_root / "site-proposal.json").read_text(encoding="utf-8"))
    if parent_payload.get("id") != "site-proposal-rotterdam-m4h-v1":
        raise ProposalBuildError("input package is not Rotterdam M4H v1")
    _integrity_manifest(v1_root, parent_root, root / "parent-v1-integrity.json")

    for relative in ("context-display-epsg28992.geojson", "sources/raw/pdok-rotterdam-municipality.geojson", "sources/human-context-claims.json"):
        _copy(parent_root / relative, root / relative)
    # Keep the v2 context and municipality artifacts independently addressable.
    context_path = root / "context-display-epsg28992-v2.geojson"
    municipality_path = root / "sources/raw/pdok-rotterdam-municipality-v2.geojson"
    _copy(parent_root / "context-display-epsg28992.geojson", context_path)
    _copy(parent_root / "sources/raw/pdok-rotterdam-municipality.geojson", municipality_path)
    raw_path = parent_root / "sources/raw/osm-overpass-m4h-context.json"

    option_a_wgs84 = {"type": "Polygon", "coordinates": [[[4.4339426, 51.9105673], [4.4356244, 51.9087779], [4.4257076, 51.9049757], [4.4240413, 51.9066715], [4.4339426, 51.9105673]]]}
    option_b_wgs84 = parent_payload["delft_context"]["boundary_options"]["B"]["wgs84_geometry"]
    wgs_a_path = root / "boundary-wgs84-option-a-v2.geojson"
    wgs_b_path = root / "boundary-wgs84-option-b-v2.geojson"
    _write_json(wgs_a_path, _geojson_feature(option_a_wgs84, {"option": "A", "status": "PROPOSED_SOURCE_ANCHORED"}, crs="EPSG:4326"))
    _copy(parent_root / "boundary-wgs84-option-b.geojson", wgs_b_path)
    with tempfile.TemporaryDirectory(prefix="m2-r03-transform-") as temporary:
        transformed_a = Path(temporary) / "a.geojson"
        transformed_b = Path(temporary) / "b.geojson"
        _transform(wgs_a_path, transformed_a)
        _transform(wgs_b_path, transformed_b)
        geometry_a = _geometry_from_transformed(transformed_a)
        geometry_b = _geometry_from_transformed(transformed_b)
    projected_a_path = root / "boundary-epsg28992-option-a-v2.geojson"
    projected_b_path = root / "boundary-epsg28992-option-b-v2.geojson"
    primary_path = root / "boundary-epsg28992-v2.geojson"
    _write_json(projected_a_path, _geojson_feature(geometry_a, {"option": "A", "status": "PROPOSED_SOURCE_ANCHORED"}, crs="EPSG:28992"))
    _write_json(projected_b_path, _geojson_feature(geometry_b, {"option": "B", "status": "PROPOSED_SOURCE_ANCHORED"}, crs="EPSG:28992"))
    _copy(projected_a_path, primary_path)

    option_values: dict[str, dict[str, Any]] = {
        "A": {"label": "Road control-point interpretation; human-sketch connectors", "wgs84_geometry": option_a_wgs84, "projected_geometry": geometry_a, "artifact_path": wgs_a_path.relative_to(root).as_posix(), "projected_artifact_path": projected_a_path.relative_to(root).as_posix(), "edge_refs": [{"osm_way_id": "82806419", "name": "Vierhavensstraat"}, {"osm_way_id": "7517828", "name": "Keilestraat"}, {"osm_way_id": "259184950", "name": "Keilestraat service"}, {"osm_way_id": "7518596", "name": "Keileweg"}]},
        "B": {"label": "Harbour control-point interpretation; human-sketch connectors", "wgs84_geometry": option_b_wgs84, "projected_geometry": geometry_b, "artifact_path": wgs_b_path.relative_to(root).as_posix(), "projected_artifact_path": projected_b_path.relative_to(root).as_posix(), "edge_refs": [{"osm_way_id": "82806419", "name": "Vierhavensstraat"}, {"osm_way_id": "134702130", "name": "Keilehaven"}]},
    }
    for key, option in option_values.items():
        option.update({"wgs84_geometry_sha256": canonical_geometry_hash(option["wgs84_geometry"]), "projected_geometry_sha256": canonical_geometry_hash(option["projected_geometry"]), "measurements": {"area_m2": polygon_area(option["projected_geometry"]), "perimeter_m": polygon_perimeter(option["projected_geometry"] )}})

    evidence_path = root / "sources/source-distance-evidence.json"
    evidence = _source_evidence(root, context_path, raw_path, option_values)
    _write_json(evidence_path, evidence)
    records = _v2_source_records(parent_root, root, evidence_path)
    source_records_path = root / "sources/source-records-v2.json"
    _write_json(source_records_path, {"schema_version": "m2-r03-source-records", "records": records})
    source_models = [V2SourceRecord.model_validate(record) for record in records]

    viewport = tuple(float(value) for value in parent_payload["delft_context"]["viewport"]["bbox"])
    viewport_meta = dict(parent_payload["delft_context"]["viewport"])
    viewport_meta["bbox"] = list(viewport)
    scratch_a = root / "_option-a-source.svg"
    scratch_b = root / "_option-b-source.svg"
    _render_svg(scratch_a, geometry_a, geometry_a, json.loads(context_path.read_text(encoding="utf-8")), source_models, viewport, generated_at=RUN_CREATED_AT)
    _render_svg(scratch_b, geometry_b, geometry_b, json.loads(context_path.read_text(encoding="utf-8")), source_models, viewport, generated_at=RUN_CREATED_AT)
    option_a_svg = root / "map-option-a-v2.svg"
    option_b_svg = root / "map-option-b-v2.svg"
    _option_svg(scratch_a, option_a_svg, "A")
    _option_svg(scratch_b, option_b_svg, "B")
    scratch_a.unlink(missing_ok=True)
    scratch_b.unlink(missing_ok=True)
    option_a_png = root / "map-option-a-v2.png"
    option_b_png = root / "map-option-b-v2.png"
    _render_png(option_a_svg, option_a_png)
    _render_png(option_b_svg, option_b_png)
    area_delta = option_values["B"]["measurements"]["area_m2"] - option_values["A"]["measurements"]["area_m2"]
    perimeter_delta = option_values["B"]["measurements"]["perimeter_m"] - option_values["A"]["measurements"]["perimeter_m"]
    deltas = {"area_delta_m2": area_delta, "area_delta_pct_of_a": area_delta / option_values["A"]["measurements"]["area_m2"] * 100.0, "perimeter_delta_m": perimeter_delta, "perimeter_delta_pct_of_a": perimeter_delta / option_values["A"]["measurements"]["perimeter_m"] * 100.0, "preference": "NONE", "different_edge_interpretation": "A uses road control points; B uses harbour control points; both use human-sketch connectors.", "included_region_description": "A includes the corrected Keileweg-side control point; B shifts the south edge to Keilehaven control points.", "excluded_region_description": "Neither option establishes ownership, zoning, permission, buildability, or a preferred site boundary."}
    comparison_svg = root / "map-preview-comparison-v2.svg"
    comparison_png = root / "map-preview-comparison-v2.png"
    _comparison_svg(option_a_svg, option_b_svg, comparison_svg, deltas)
    _render_png(comparison_svg, comparison_png, width=2480, height=900)

    option_maps = {}
    for key, svg, png in (("A", option_a_svg, option_a_png), ("B", option_b_svg, option_b_png)):
        option_maps[key] = {"svg_path": svg.relative_to(root).as_posix(), "svg_sha256": sha256_file(svg), "svg_size_bytes": svg.stat().st_size, "png_path": png.relative_to(root).as_posix(), "png_sha256": sha256_file(png), "png_size_bytes": png.stat().st_size, "viewport": viewport_meta, "same_scale": True}
    comparison_metadata = {"svg_path": comparison_svg.relative_to(root).as_posix(), "svg_sha256": sha256_file(comparison_svg), "svg_size_bytes": comparison_svg.stat().st_size, "png_path": comparison_png.relative_to(root).as_posix(), "png_sha256": sha256_file(comparison_png), "png_size_bytes": comparison_png.stat().st_size, "viewport": viewport_meta, "panel_count": 2, "same_scale": True}
    comparison_render_path = root / "comparison-render-record-v2.json"
    _write_json(comparison_render_path, {"schema_version": "m2-r03-comparison-render", "producer": PRODUCER, "svg_path": comparison_metadata["svg_path"], "svg_sha256": comparison_metadata["svg_sha256"], "png_path": comparison_metadata["png_path"], "png_sha256": comparison_metadata["png_sha256"], "viewport": comparison_metadata["viewport"], "same_scale": True, "panel_count": 2, "option_maps": {key: {"svg_sha256": value["svg_sha256"], "png_sha256": value["png_sha256"]} for key, value in option_maps.items()}, "render_engine": QGIS_PYTHON + " / PyQt5.QtSvg"})

    context = dict(parent_payload["delft_context"])
    context.update({"candidate_boundary_wgs84": option_a_wgs84, "candidate_boundary_wgs84_sha256": canonical_geometry_hash(option_a_wgs84), "boundary_selection_status": "AMBIGUOUS_HUMAN_SELECTION_REQUIRED", "human_choice_required": True, "display_only": True, "display_option": "A_AND_B_COMPARISON", "boundary_options": option_values, "context_display_path": context_path.relative_to(root).as_posix(), "municipality_feature_path": municipality_path.relative_to(root).as_posix(), "municipality_feature_sha256": sha256_file(municipality_path), "source_distance_evidence_path": evidence_path.relative_to(root).as_posix(), "source_distance_tolerance_m": 1.0, "parent_v1_path": "parent-v1", "parent_integrity_path": "parent-v1-integrity.json", "human_context_claims_path": "sources/human-context-claims.json", "option_maps": option_maps, "comparison_map": comparison_metadata, "comparison_render_record_path": comparison_render_path.relative_to(root).as_posix(), "comparison_deltas": deltas, "map_svg_path": comparison_svg.relative_to(root).as_posix(), "map_svg_sha256": sha256_file(comparison_svg), "map_svg_size_bytes": comparison_svg.stat().st_size, "rendered_png_path": comparison_png.relative_to(root).as_posix(), "rendered_png_sha256": sha256_file(comparison_png), "rendered_png_size_bytes": comparison_png.stat().st_size, "render_record_path": comparison_render_path.relative_to(root).as_posix(), "state_path": "proposal-state.sqlite3", "delft_parent_integrity_path": "parent-v1/delft-parent-integrity.json"})
    context["limitations"] = list(dict.fromkeys(list(context.get("limitations", [])) + ["M2-R03 source evidence claims control-point relationships only; straight ring connectors are NOT_CLAIMED_HUMAN_SKETCH_CONNECTOR.", "Both options remain PROPOSED and require explicit human selection; no preference is recorded."]))
    approval_path = root / "approval-record-v2.md"
    approval_path.write_text(f'''# Human approval record — Rotterdam M4H Vierhavenblok v2

Proposal: `{PROPOSAL_ID}` (`v2`), superseding `site-proposal-rotterdam-m4h-v1`.

Decision status: **HUMAN_DECISION_REQUIRED**. No human decision has been recorded. Both maps are same-scale, separate decision views; the comparison records **neither preferred**.

Option A uses retained OSM source control points on ways 82806419, 7517828, 259184950, and 7518596. Option B uses retained OSM source control points on ways 82806419 and 134702130. Every control point records its source way, snapshot hash, source vertex and segment, tolerance (1.000 m), and measured point-to-segment distance. Straight ring connectors are explicitly `NOT_CLAIMED_HUMAN_SKETCH_CONNECTOR`; no physical mapped edge or snapping claim is made for them.

Option A: area {option_values['A']['measurements']['area_m2']:.3f} m²; perimeter {option_values['A']['measurements']['perimeter_m']:.3f} m. Option B: area {option_values['B']['measurements']['area_m2']:.3f} m²; perimeter {option_values['B']['measurements']['perimeter_m']:.3f} m. Area delta (B−A): {area_delta:.3f} m²; perimeter delta (B−A): {perimeter_delta:.3f} m. A includes the corrected Keileweg-side control point; B shifts the south edge to Keilehaven control points. Neither establishes zoning, ownership, permission, buildability, or a preferred boundary.

**APPROVE:** append an explicit human decision naming Option A or Option B, its exact WGS84 and EPSG:28992 hashes, actor, timezone-aware timestamp, and reason.

**REJECT:** append an explicit human rejection naming the option or both options, actor, timezone-aware timestamp, and reason.

The project state keeps `Project.site_id = null`, contains no `HumanDecision`, `Approve`, or `Accept` event, and remains `PROPOSED`.
''', encoding="utf-8")

    created_at = datetime.fromisoformat(RUN_CREATED_AT)
    transform_command = f"{GDAL_OGR2OGR} -f GeoJSON -s_srs EPSG:4326 -t_srs EPSG:28992 -nlt GEOMETRY -lco RFC7946=NO <boundary-wgs84-option-*.geojson>"
    proposal = SiteProposal(id=PROPOSAL_ID, project_id=PROJECT_ID, version="v2", supersedes_proposal_id="site-proposal-rotterdam-m4h-v1", boundary_artifact_path=primary_path.relative_to(root).as_posix(), boundary_sha256=sha256_file(primary_path), boundary_size_bytes=primary_path.stat().st_size, boundary_mime="application/geo+json", geometry_sha256=canonical_geometry_hash(geometry_a), geometry=geometry_a, geometry_type="Polygon", horizontal_crs="EPSG:28992", units="m", vertical_reference_status="NOT_APPLICABLE_2D_BOUNDARY; no vertical reference supplied", transform={"input_crs": "EPSG:4326", "output_crs": "EPSG:28992", "method": "GDAL/OGR deterministic reprojection", "tool": GDAL_OGR2OGR, "tool_version": "GDAL 3.3.2, released 2021/09/01", "command": transform_command, "axis_order": "traditional GIS axis order: longitude, latitude input", "vertical_reference_status": "NOT_APPLICABLE_2D_BOUNDARY"}, producer=PRODUCER, created_at=created_at, selection_method="Source-anchored control points from retained OSM snapshot; straight ring connectors are explicitly human-sketch connectors and carry no mapped-edge claim.", rationale="Append-only M2-R03 repair of Rotterdam M4H v1. Corrected Option A source relationship, separate same-scale A/B decision maps, and neutral numeric comparison remain provisional pending human selection.", source_refs=[record["id"] for record in records], parent_refs=["site-proposal-rotterdam-m4h-v1", "site-proposal-delft-v1", "site-proposal-delft-v2", "site-proposal-delft-v3", "parent-v1-integrity"], measurements=[{"name": "area", "value": polygon_area(geometry_a), "unit": "m2", "method": "shoelace area on EPSG:28992 projected exterior ring", "crs": "EPSG:28992"}, {"name": "perimeter", "value": polygon_perimeter(geometry_a), "unit": "m", "method": "Euclidean exterior-ring perimeter on EPSG:28992 projected coordinates", "crs": "EPSG:28992"}], delft_context=context, dataset_plan={"municipality": "PDOK BRK gemeentegebied Rotterdam containment only", "context": "retained OSM/Overpass context transformed to EPSG:28992", "planning_and_buildability": "UNAVAILABLE; outside M2-R03 scope", "accessibility": "OUT_OF_SCOPE", "morphology": "OUT_OF_SCOPE", "space_syntax": "OUT_OF_SCOPE", "climate": "UNAVAILABLE; no experiment plan approved", "design_generation": "OUT_OF_SCOPE"}, limitations=context["limitations"], approval_record_path=approval_path.relative_to(root).as_posix(), selection_criteria_status="PROPOSED_PROJECT_DECISION", selection_criteria={"status": "PROPOSED_PROJECT_DECISION", "human_selection_required": True, "options": ["A", "B"], "edge_evidence": {"source_distance_evidence": evidence_path.relative_to(root).as_posix(), "connector_claim": "NOT_CLAIMED_HUMAN_SKETCH_CONNECTOR"}}, scale_parameters={"status": "PROPOSED_PROJECT_DECISION", "purpose": "descriptive same-scale comparison", "thresholds": None}, taxonomy_status="PROPOSED", map_preview_path=comparison_svg.relative_to(root).as_posix(), source_records_path=source_records_path.relative_to(root).as_posix())

    db_path = root / "proposal-state.sqlite3"
    _copy(parent_root / "proposal-state.sqlite3", db_path)
    for suffix in ("-wal", "-shm"):
        sidecar = parent_root / f"proposal-state.sqlite3{suffix}"
        if sidecar.is_file():
            _copy(sidecar, root / sidecar.name)
    with ProjectStateStore(db_path) as store:
        artifact_specs = [(primary_path, "artifact-boundary-rotterdam-m4h-v2", "application/geo+json", []), (wgs_a_path, "artifact-boundary-wgs84-option-a-v2", "application/geo+json", ["artifact-boundary-rotterdam-m4h-v2"]), (wgs_b_path, "artifact-boundary-wgs84-option-b-v2", "application/geo+json", ["artifact-boundary-rotterdam-m4h-v1"]), (projected_b_path, "artifact-boundary-epsg28992-option-b-v2", "application/geo+json", ["artifact-boundary-wgs84-option-b-v2"]), (evidence_path, "artifact-source-distance-evidence-v2", "application/json", []), (source_records_path, "artifact-source-records-rotterdam-m4h-v2", "application/json", ["artifact-source-distance-evidence-v2"]), (option_a_svg, "artifact-map-option-a-v2", "image/svg+xml", ["artifact-boundary-rotterdam-m4h-v2"]), (option_b_svg, "artifact-map-option-b-v2", "image/svg+xml", ["artifact-boundary-epsg28992-option-b-v2"]), (comparison_svg, "artifact-map-preview-comparison-v2", "image/svg+xml", ["artifact-map-option-a-v2", "artifact-map-option-b-v2"]), (option_a_png, "artifact-map-option-a-render-v2", "image/png", ["artifact-map-option-a-v2"]), (option_b_png, "artifact-map-option-b-render-v2", "image/png", ["artifact-map-option-b-v2"]), (comparison_png, "artifact-map-comparison-render-v2", "image/png", ["artifact-map-preview-comparison-v2"]), (comparison_render_path, "artifact-comparison-render-record-v2", "application/json", ["artifact-map-preview-comparison-v2", "artifact-map-comparison-render-v2"]), (approval_path, "artifact-approval-record-rotterdam-m4h-v2", "text/markdown", ["artifact-map-comparison-render-v2"]), (root / "parent-v1-integrity.json", "artifact-parent-v1-integrity", "application/json", [])]
        for path, artifact_id, mime, parents in artifact_specs:
            store.create_typed(_artifact(path, root, artifact_id, mime, created_at, parents), actor="m2-r03-executor", action="RecordArtifact", reason="Record append-only M2-R03 repair evidence with immutable hash and parent links.")
        site = Site(id="site-rotterdam-m4h-v2", project_id=PROJECT_ID, version="v2", boundary_artifact_id="artifact-boundary-rotterdam-m4h-v2", boundary_sha256=proposal.boundary_sha256, crs="EPSG:28992", vertical_reference=proposal.vertical_reference_status, units="m", dataset_snapshot_ids=[], status=SiteStatus.PROPOSED)
        store.create_typed(site, actor="m2-r03-executor", action="ProposeSite", reason="Append corrected proposed alternative; explicit human selection remains required.", changed_refs=proposal.source_refs, resulting_refs=[site.id, site.boundary_artifact_id, proposal.id], event_payload={"proposal_id": proposal.id, "status": proposal.status, "human_decision_required": True})
        store.create("SiteProposal", proposal.model_dump(mode="json"), entity_id=proposal.id, project_id=PROJECT_ID, actor="m2-r03-executor", action="RecordSiteProposal", reason="Record M2-R03 repair without adoption or approval.", changed_refs=proposal.source_refs, resulting_refs=[proposal.id, site.id, site.boundary_artifact_id], event_payload={"proposal_id": proposal.id, "status": proposal.status, "human_decision_required": True})
        refs = [event.event_id for event in store.events(project_id=PROJECT_ID) if event.target_id in {proposal.id, site.id}]
        store.update(proposal.id, {"ledger_event_refs": refs}, expected_revision=1, actor="m2-r03-executor", action="LinkProposalLedgerRefs", reason="Link v2 repair proposal to append-only proposed-state events.", changed_refs=refs, resulting_refs=[proposal.id])
    proposal.ledger_event_refs = refs
    _write_json(root / "site-proposal.json", proposal.model_dump(mode="json"))
    validate_site_proposal_rotterdam_v2(proposal, root, v1_root=v1_root)
    return proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--v1-dir", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", default=True)
    args = parser.parse_args(argv)
    try:
        proposal = build_rotterdam_v2(args.output_dir, v1_dir=args.v1_dir, offline=True)
    except (ProposalBuildError, ValueError, OSError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"proposal_id": proposal.id, "version": proposal.version, "status": proposal.status, "boundary_sha256": proposal.boundary_sha256, "geometry_sha256": proposal.geometry_sha256}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
