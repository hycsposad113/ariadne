#!/usr/bin/env python3
"""Build the append-only M2-R07 Rotterdam M4H boundary decision package.

M2-R07 deliberately produces review evidence and boundary alternatives.  It
does not create a SiteProposal, adopt a site, or generate a v6 proposal.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import math
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import unary_union

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from create_site_proposal_rotterdam import (  # noqa: E402
    _clip_line,
    _clip_polygon,
    _feature_markup,
    _points_text,
    _projector,
    _render_png,
)
import create_site_proposal_rotterdam_v5 as v5  # noqa: E402
from urban_design.boundary_decision_rotterdam_m4h import (  # noqa: E402
    BoundarySemanticGateError,
    evaluate_supplementary_semantics,
)
from urban_design.geometry import canonical_geometry_hash, polygon_area, polygon_perimeter  # noqa: E402
from urban_design.site_proposal import canonical_json_bytes, sha256_file  # noqa: E402
from urban_design.store import ProjectStateStore  # noqa: E402


PROJECT_ID = "rotterdam-m4h-pilot-project"
TASK_ID = "M2-R07"
R07_PROPOSAL_ID = "site-proposal-rotterdam-m4h-v5"
REJECTION_MARKER = "REJECTED_BY_CONTROL_TOWER_SUPPLEMENTARY_TOPOLOGY_NOT_SEMANTICALLY_BOUNDED"
DEFAULT_CREATED_AT = "2026-09-16T12:30:00+00:00"
DEFAULT_R07_RELATIVE = "artifacts/milestone2-site-proposal-rotterdam-m4h-v5/run-20260916T093310Z"
COLLECTIONS = [
    "wegdeel",
    "ondersteunendwegdeel",
    "onbegroeidterreindeel",
    "waterdeel",
    "begroeidterreindeel",
]
SOURCE_COLORS = {
    "wegdeel": "#0072B2",
    "ondersteunendwegdeel": "#009E73",
    "onbegroeidterreindeel": "#E69F00",
    "begroeidterreindeel": "#56B4E9",
    "waterdeel": "#CC79A7",
}
R07_RED = "#D62728"
SEED_GRAY = "#7F8588"


class DecisionPackageBuildError(RuntimeError):
    pass


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def copy_file(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise DecisionPackageBuildError(f"missing retained source: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - error is surfaced to caller
        raise DecisionPackageBuildError(f"invalid JSON: {path}") from exc


def projected_geometry(geometry: Mapping[str, Any]):
    return v5._projected(geometry)


def ring_indices(start: int, end: int, count: int) -> list[int]:
    if start <= end:
        return list(range(start, end + 1))
    return list(range(start, count)) + list(range(0, end + 1))


def source_attributes(
    collection: str,
    feature_id: str | None,
    by_id: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    properties = (by_id.get((collection, str(feature_id))) or {}).get("properties") or {}
    return {
        "functie": properties.get("functie"),
        "fysiek_voorkomen": properties.get("fysiek_voorkomen"),
        "plus_fysiek_voorkomen": properties.get("plus_fysiek_voorkomen"),
        "type": properties.get("type"),
        "status": properties.get("status"),
    }


def edge_indices_for_run(run: Mapping[str, Any], edge_count: int) -> list[int]:
    start = int(run["edge_start"])
    end = int(run["edge_end"])
    return ring_indices(start, end, edge_count)


def enrich_run(
    run: Mapping[str, Any],
    edges: Sequence[Mapping[str, Any]],
    feature_by_id: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    indices = edge_indices_for_run(run, len(edges))
    selected = [edges[index] for index in indices]
    points: list[tuple[float, float]] = []
    for edge in selected:
        start = tuple(float(value) for value in edge["start_epsg28992"])
        end = tuple(float(value) for value in edge["end_epsg28992"])
        if not points or points[-1] != start:
            points.append(start)
        points.append(end)
    line = LineString(points)
    collections = sorted({str(edge["source_collection"]) for edge in selected})
    feature_ids = sorted({str(edge["source_feature_id"]) for edge in selected})
    attributes = []
    for collection, feature_id in sorted({(str(edge["source_collection"]), str(edge["source_feature_id"])) for edge in selected}):
        attributes.append(
            {
                "source_collection": collection,
                "source_feature_id": feature_id,
                **source_attributes(collection, feature_id, feature_by_id),
            }
        )
    before_index = (indices[0] - 1) % len(edges)
    after_index = (indices[-1] + 1) % len(edges)
    before = edges[before_index]
    after = edges[after_index]
    previous_attributes = source_attributes(str(before["source_collection"]), str(before["source_feature_id"]), feature_by_id)
    next_attributes = source_attributes(str(after["source_collection"]), str(after["source_feature_id"]), feature_by_id)
    functions = sorted(
        {
            str(value)
            for value in (
                *(attribute.get("functie") for attribute in attributes),
                previous_attributes.get("functie"),
                next_attributes.get("functie"),
            )
            if value
        }
    )
    return {
        "run_id": str(run.get("run_id") or f"run-{run.get('edge_start')}-{run.get('edge_end')}"),
        "edge_start": indices[0],
        "edge_end": indices[-1],
        "edge_indices": indices,
        "edge_count": len(indices),
        "length_m": float(line.length),
        "start_epsg28992": list(points[0]),
        "end_epsg28992": list(points[-1]),
        "source_collection": "supplementary",
        "source_collections": collections,
        "source_feature_ids": feature_ids,
        "source_functions": functions,
        "source_attributes": attributes,
        "previous_source_collection": str(before["source_collection"]),
        "next_source_collection": str(after["source_collection"]),
        "previous_source_feature_id": str(before["source_feature_id"]),
        "next_source_feature_id": str(after["source_feature_id"]),
        "previous_source_attributes": previous_attributes,
        "next_source_attributes": next_attributes,
        "line": line,
    }


def split_by_geometric_turns(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Split a problematic run at salient geometric turns, not collection labels."""

    line: LineString = run["line"]
    if line.length <= 0:
        return []
    simplified = line.simplify(3.0, preserve_topology=False)
    points = list(simplified.coords)
    turn_candidates: list[tuple[float, float]] = []
    for index in range(1, len(points) - 1):
        previous, current, following = points[index - 1], points[index], points[index + 1]
        first = (current[0] - previous[0], current[1] - previous[1])
        second = (following[0] - current[0], following[1] - current[1])
        first_length = math.hypot(*first)
        second_length = math.hypot(*second)
        if first_length <= 1e-9 or second_length <= 1e-9:
            continue
        cosine = (first[0] * second[0] + first[1] * second[1]) / (first_length * second_length)
        angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
        if angle < 25.0:
            continue
        distance = float(line.project(Point(current)))
        turn_candidates.append((distance, angle))
    # Retain the strongest turn in each 80 m neighbourhood.  The distances
    # are computed from source coordinates and are not hand-entered.
    selected: list[tuple[float, float]] = []
    for distance, angle in sorted(turn_candidates, key=lambda item: (-item[1], item[0])):
        if all(abs(distance - existing[0]) >= 80.0 for existing in selected):
            selected.append((distance, angle))
    cuts = sorted({0.0, float(line.length), *(distance for distance, _ in selected)})
    sections: list[dict[str, Any]] = []
    for index, (start_distance, end_distance) in enumerate(zip(cuts, cuts[1:]), start=1):
        if end_distance - start_distance < 1e-6:
            continue
        # Only the source-derived endpoints are recorded; raw edge geometry
        # remains the map truth for each section.
        start_point = line.interpolate(start_distance)
        end_point = line.interpolate(end_distance)
        sections.append(
            {
                "section_id": f"{run['run_id']}-section-{index}",
                "edge_start": run["edge_start"],
                "edge_end": run["edge_end"],
                "cumulative_start_m": start_distance,
                "cumulative_end_m": end_distance,
                "length_m": end_distance - start_distance,
                "start_epsg28992": [start_point.x, start_point.y],
                "end_epsg28992": [end_point.x, end_point.y],
                "turn_basis": "source-derived 3 m simplified boundary; salient direction change >= 25 degrees with >= 80 m separation",
                "turn_angle_at_end_degrees": next((angle for distance, angle in selected if abs(distance - end_distance) < 1e-6), None),
                "source_collections": run["source_collections"],
                "source_feature_ids": run["source_feature_ids"],
                "semantic_status": "UNRESOLVED_LOCAL_JUNCTION_ROLE",
                "cannot_auto_determine_because": "terrain/water exterior is source-traced but no official local road-interface relationship is established for this section",
            }
        )
    return sections


def feature_index(raw_sources: Mapping[str, Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (collection, str(feature.get("id"))): feature
        for collection, payload in raw_sources.items()
        for feature in payload.get("features", [])
        if feature.get("id") is not None
    }


def make_run_evidence(
    audit_runs: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    feature_by_id: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for index, run in enumerate(audit_runs):
        enriched = enrich_run({**run, "run_id": f"supplementary-run-{index + 1}"}, edges, feature_by_id)
        enriched.pop("line", None)
        enriched["persisted_length_m"] = float(run.get("length_m", enriched["length_m"]))
        enriched["length_reconciliation_delta_m"] = enriched["length_m"] - enriched["persisted_length_m"]
        # Build sections from every source edge so turn cuts follow the actual
        # traced boundary rather than a straight endpoint chord.
        raw = enrich_run({**run, "run_id": enriched["run_id"]}, edges, feature_by_id)
        enriched["sections"] = split_by_geometric_turns(raw)
        result.append(enriched)
    return result


def geometry_feature(geometry: Mapping[str, Any], properties: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "Feature", "properties": dict(properties or {}), "geometry": dict(geometry)}


def expand_bounds(bounds: Sequence[float], margin_ratio: float = 0.08, minimum: float = 20.0) -> tuple[float, float, float, float]:
    xmin, ymin, xmax, ymax = [float(value) for value in bounds]
    margin = max(max(xmax - xmin, ymax - ymin) * margin_ratio, minimum)
    return (xmin - margin, ymin - margin, xmax + margin, ymax + margin)


def line_markup(points: Sequence[tuple[float, float]], viewport, project, style: str) -> str:
    out = []
    for clipped in _clip_line(points, viewport):
        out.append(f'<polyline points="{_points_text(clipped, project)}" {style}/>')
    return "".join(out)


def map_svg(
    path: Path,
    *,
    title: str,
    viewport: tuple[float, float, float, float],
    seed: Polygon,
    r07_boundary: Polygon,
    edges: Sequence[Mapping[str, Any]],
    problematic_runs: Sequence[Mapping[str, Any]],
    display: Mapping[str, Any],
    created_at: str,
    map_kind: str,
) -> dict[str, Any]:
    frame = (44.0, 100.0, 820.0, 590.0)
    project, scale = _projector(viewport, frame)
    features = [feature for feature in display.get("features", []) if isinstance(feature, Mapping)]
    context_markup: list[str] = []
    for feature in features:
        props = feature.get("properties") or {}
        layer = props.get("display_layer")
        if layer not in {"context buildings", "site buildings", "roads/walk paths", "rail"}:
            continue
        if layer == "site buildings":
            style = 'fill="#111111" stroke="#111111" stroke-width="0.4"'
        elif layer == "context buildings":
            style = 'fill="#E5E5E5" stroke="#A4A4A4" stroke-width="0.35"'
        elif layer == "rail":
            style = 'fill="none" stroke="#555555" stroke-width="0.65"'
        else:
            style = 'fill="none" stroke="#B0B0B0" stroke-width="0.55"'
        context_markup.append(_feature_markup(feature, viewport, project, style))

    seed_line = [(float(x), float(y)) for x, y in seed.exterior.coords]
    r07_line = [(float(x), float(y)) for x, y in r07_boundary.exterior.coords]
    seed_clipped = _clip_polygon(seed_line, viewport)
    r07_clipped = _clip_polygon(r07_line, viewport)
    source_markup: list[str] = []
    for edge in edges:
        source_markup.append(
            line_markup(
                [tuple(edge["start_epsg28992"]), tuple(edge["end_epsg28992"])],
                viewport,
                project,
                f'stroke="{SOURCE_COLORS.get(str(edge["source_collection"]), "#777777")}" stroke-width="1.15" opacity="0.95" fill="none"',
            )
        )
    annotations: list[str] = []
    for run in problematic_runs:
        start = tuple(run["start_epsg28992"])
        end = tuple(run["end_epsg28992"])
        for label, point in ((f'{run["run_id"]} START', start), (f'{run["run_id"]} END', end)):
            x, y = project(point)
            if viewport[0] <= point[0] <= viewport[2] and viewport[1] <= point[1] <= viewport[3]:
                annotations.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" fill="#202427" stroke="#ffffff" stroke-width="1.2"/><text x="{x + 7:.2f}" y="{y - 7:.2f}" class="annotation">{html.escape(label)}</text>')
    legend_y = 132
    legend = [
        '<text x="900" y="132" class="legend-title">R07 SEMANTIC REVIEW</text>',
        '<text x="900" y="154" class="legend-text">red: rejected r07 perimeter</text>',
        '<line x1="900" y1="170" x2="932" y2="170" stroke="#7F8588" stroke-width="1.2" stroke-dasharray="6 4"/><text x="942" y="174" class="legend-text">v3 human-intent seed</text>',
    ]
    for collection, color in SOURCE_COLORS.items():
        legend.append(f'<line x1="900" y1="{legend_y + 58}" x2="932" y2="{legend_y + 58}" stroke="{color}" stroke-width="2"/><text x="942" y="{legend_y + 62}" class="legend-text">{collection}</text>')
        legend_y += 22
    run_lines = []
    for run in problematic_runs:
        run_lines.append(f'<text x="900" y="{legend_y + 42}" class="legend-text">{run["run_id"]}: {run["length_m"]:.2f} m</text>')
        legend_y += 18
    body = "".join(context_markup)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="850" viewBox="0 0 1240 850">
<style>.title{{font-family:sans-serif;font-size:23px;font-weight:700;fill:#202427}}.subtitle{{font-family:sans-serif;font-size:12px;fill:#4a5054}}.legend-title{{font-family:sans-serif;font-size:15px;font-weight:700;fill:#202427}}.legend-text{{font-family:sans-serif;font-size:12px;fill:#202427}}.annotation{{font-family:sans-serif;font-size:11px;font-weight:700;fill:#202427;paint-order:stroke;stroke:#fff;stroke-width:3px}}.footer{{font-family:monospace;font-size:11px;fill:#202427}}</style>
<rect width="1240" height="850" fill="#f7f7f7"/><text x="44" y="40" class="title">{html.escape(title)}</text><text x="44" y="67" class="subtitle">M2-R07 boundary decision package · {html.escape(map_kind)} · no proposal generated · no approval/freeze</text>
<rect x="44" y="100" width="820" height="590" fill="#ffffff" stroke="#aab0b3" stroke-width="1"/>
<g id="context">{body}</g>
<polyline id="v3-seed" points="{_points_text(seed_clipped, project)}" fill="none" stroke="{SEED_GRAY}" stroke-width="1.5" stroke-dasharray="7 5"/>
<polyline id="r07-rejected-perimeter" points="{_points_text(r07_clipped, project)}" fill="none" stroke="{R07_RED}" stroke-width="1.5" opacity="0.85"/>
<g id="source-edges">{"".join(source_markup)}</g>
<g id="problem-markers">{"".join(annotations)}</g>
<g id="legend"><rect x="884" y="100" width="326" height="510" rx="6" fill="#ffffff" stroke="#aab0b3"/>{"".join(legend)}<text x="900" y="{legend_y + 65}" class="legend-text">Endpoint road adjacency is insufficient.</text><text x="900" y="{legend_y + 85}" class="legend-text">Sections require human boundary choice.</text></g>
<text x="44" y="742" class="footer">STATE: R07 REJECTED · {REJECTION_MARKER}</text><text x="44" y="766" class="subtitle">EPSG:28992 · source colors are BGT collections · v3 seed is human intent only · generated {created_at}</text>
</svg>'''
    path.write_text(svg, encoding="utf-8")
    return {
        "path": path.name,
        "viewbox": [0, 0, 1240, 850],
        "frame": list(frame),
        "viewport_epsg28992": list(viewport),
        "scale_px_per_m": scale,
        "map_kind": map_kind,
        "source_colors": SOURCE_COLORS,
        "layers": ["context", "v3-seed", "source-edges", "r07-rejected-perimeter", "problem-markers", "legend"],
    }


def raw_sources(r07: Path) -> tuple[dict[str, Mapping[str, Any]], dict[tuple[str, str], Mapping[str, Any]]]:
    sources: dict[str, Mapping[str, Any]] = {}
    for collection in COLLECTIONS:
        path = r07 / "sources/raw" / f"pdok-bgt-{collection}-m4h.json"
        sources[collection] = load_json(path)
    return sources, feature_index(sources)


def metric_bundle(candidate: Polygon, seed: Polygon, display: Mapping[str, Any], bag: Mapping[str, Any], raw_sources_payload: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    bag_crossings = v5._building_crossings(candidate, bag)
    canonical_crossings, reconciliations = v5._canonical_osm_building_audit(display, bag, candidate)
    site_buildings: list[str] = []
    for feature in display.get("features", []):
        props = feature.get("properties") or {}
        if not props.get("building"):
            continue
        audit_geometry, _ = v5._display_audit_geometry(feature, v5._bag_by_id(bag))
        if audit_geometry.centroid.within(candidate):
            site_buildings.append(str(feature.get("id")))
    road_surfaces = []
    for feature in raw_sources_payload["wegdeel"].get("features", []):
        projected = projected_geometry(feature["geometry"])
        if projected.intersects(seed):
            road_surfaces.append(projected)
    road_union = unary_union(road_surfaces)
    return {
        "area_m2": float(candidate.area),
        "perimeter_m": float(candidate.length),
        "site_building_count": len(site_buildings),
        "site_building_ids": sorted(site_buildings),
        "bag_crossing_count": len(bag_crossings),
        "bag_crossing_ids": sorted(bag_crossings),
        "osm_crossing_count": len(canonical_crossings),
        "osm_crossing_ids": sorted(str(item.get("source_id")) for item in canonical_crossings),
        "osm_raw_geometry_reconciliation_count": len(reconciliations),
        "osm_raw_geometry_reconciliations": reconciliations,
        "v3_intersection_area_m2": float(seed.intersection(candidate).area),
        "v3_symmetric_difference_area_m2": float(seed.symmetric_difference(candidate).area),
        "v3_area_ratio": float(candidate.area / seed.area),
        "v3_relative_area_delta": float(abs(candidate.area - seed.area) / seed.area),
        "road_union_area_m2": float(road_union.area),
        "road_overlap_area_m2": float(candidate.intersection(road_union).area),
        "road_overlap_ratio": float(candidate.intersection(road_union).area / candidate.area),
        "geometry_sha256": canonical_geometry_hash(mapping(candidate)),
    }


def alternative_candidate(seed: Polygon, source_files: Sequence[tuple[str, Path]], threshold: float):
    previous = v5.FACE_OVERLAP_THRESHOLD
    v5.FACE_OVERLAP_THRESHOLD = threshold
    try:
        candidate, edges, details = v5._source_face_union(seed, list(source_files))
    finally:
        v5.FACE_OVERLAP_THRESHOLD = previous
    return candidate, edges, details


def copy_r07_references(r07: Path, root: Path) -> dict[str, Any]:
    reference = root / "r07-reference"
    selected = [
        "site-proposal.json",
        "boundary-epsg28992-v5.geojson",
        "boundary-wgs84-v5.geojson",
        "display-data-v5.geojson",
        "map-preview-v5.svg",
        "map-preview-v5.png",
        "map-diagnostic-v5.svg",
        "map-diagnostic-v5.png",
        "package-status-r06.json",
        "topology-gate-audit-v5-r06.json",
        "sources/boundary-relationship-evidence-v5.json",
        "sources/source-records-v5.json",
        "sources/raw/pdok-bag-pand-m4h.json",
        "sources/raw/pdok-bgt-wegdeel-m4h.json",
        "sources/raw/pdok-bgt-ondersteunendwegdeel-m4h.json",
        "sources/raw/pdok-bgt-onbegroeidterreindeel-m4h.json",
        "sources/raw/pdok-bgt-waterdeel-m4h.json",
        "sources/raw/pdok-bgt-begroeidterreindeel-m4h.json",
        "parent-v4/parent-v3/site-proposal.json",
        "proposal-state.sqlite3",
    ]
    for relative in selected:
        copy_file(r07 / relative, reference / relative)
    manifest_files = []
    for path in sorted(p for p in r07.rglob("*") if p.is_file()):
        manifest_files.append({"relative_path": path.relative_to(r07).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "schema_version": "m2-r07-r07-byte-manifest",
        "source_root": "../../milestone2-site-proposal-rotterdam-m4h-v5/run-20260916T093310Z",
        "source_run": r07.name,
        "file_count": len(manifest_files),
        "files": manifest_files,
        "selected_retained_copy_root": "r07-reference",
    }
    write_json(root / "r07-byte-integrity.json", manifest)
    return manifest


def append_rejection_event(r07: Path, root: Path, evidence: Mapping[str, Any], created_at: str) -> dict[str, Any]:
    source_db = r07 / "proposal-state.sqlite3"
    decision_db = root / "decision-state.sqlite3"
    src = sqlite3.connect(source_db)
    dst = sqlite3.connect(decision_db)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    with ProjectStateStore(decision_db) as store:
        event = store.append_ledger_event(
            target_id=R07_PROPOSAL_ID,
            actor="control-tower-m2-r07",
            action="Reject",
            project_id=PROJECT_ID,
            target_type="SiteProposal",
            prior_status="PROPOSED",
            changed_refs=[R07_PROPOSAL_ID, "topology-gate-audit-v5-r06.json"],
            reason=REJECTION_MARKER,
            resulting_refs=[R07_PROPOSAL_ID, "boundary-decision-rotterdam-m4h-r07"],
            supersedes=None,
            parent_event_id=None,
            state_revision=None,
            payload={"task_id": TASK_ID, "marker": REJECTION_MARKER, "evidence": evidence},
            event_id="event-m2-r07-reject-v5-supplementary-topology",
            timestamp=created_at,
        )
        return event.to_dict()


def build_decision_package(output_dir: str | Path, *, r07_dir: str | Path, created_at: str = DEFAULT_CREATED_AT, offline: bool = True) -> dict[str, Any]:
    if not offline:
        raise DecisionPackageBuildError("M2-R07 decision builder is offline-only")
    root = Path(output_dir).resolve()
    r07 = Path(r07_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise DecisionPackageBuildError(f"refusing to overwrite non-empty output: {root}")
    if not (r07 / "site-proposal.json").is_file():
        raise DecisionPackageBuildError("r07 package is required")
    root.mkdir(parents=True, exist_ok=False)
    r07_proposal = load_json(r07 / "site-proposal.json")
    r07_boundary = shape(load_json(r07 / "boundary-epsg28992-v5.geojson")["geometry"])
    seed = shape(load_json(r07 / "parent-v4/parent-v3/site-proposal.json")["geometry"])
    display = load_json(r07 / "display-data-v5.geojson")
    bag = load_json(r07 / "sources/raw/pdok-bag-pand-m4h.json")
    audit = load_json(r07 / "topology-gate-audit-v5-r06.json")
    relationship = load_json(r07 / "sources/boundary-relationship-evidence-v5.json")
    raw_sources_payload, feature_by_id = raw_sources(r07)
    edges = relationship["edges"]

    audit_runs = audit["topology_gate"]["aggregated_supplementary_runs"]
    runs = make_run_evidence(audit_runs, edges, feature_by_id)
    r07_gate = evaluate_supplementary_semantics(runs, perimeter_m=r07_boundary.length, candidate=r07_boundary, seed=seed)
    if r07_gate["pass"]:
        raise DecisionPackageBuildError("r07 unexpectedly passed the M2-R07 semantic gate")
    problematic = [run for run in runs if float(run["length_m"]) >= 250.0 or "waterdeel" in run["source_collections"]]
    for run in problematic:
        run["why_cannot_auto_determine"] = "road-like endpoints do not establish a local junction role; terrain/water span requires human segment choice"

    alternative_records: list[dict[str, Any]] = []
    source_files = [(collection, r07 / "sources/raw" / f"pdok-bgt-{collection}-m4h.json") for collection in COLLECTIONS]
    for threshold, alternative_id, label in [
        (0.40, "face-overlap-040", "BGT face overlap >= 0.40"),
        (0.50, "r07-face-overlap-050", "r07 retained face overlap >= 0.50"),
        (0.60, "face-overlap-060", "BGT face overlap >= 0.60"),
    ]:
        if threshold == 0.50:
            candidate = r07_boundary
            alt_edges = edges
            details = {"face_overlap_threshold": 0.50, "supplementary_runs": audit_runs, "selected_face_count": audit["selection"]["selected_face_count"], "polygonized_face_count": audit["selection"]["polygonized_face_count"]}
        else:
            candidate, alt_edges, details = alternative_candidate(seed, source_files, threshold)
        enriched_alt_runs = make_run_evidence(details.get("supplementary_runs", []), alt_edges, feature_by_id)
        gate = evaluate_supplementary_semantics(enriched_alt_runs, perimeter_m=candidate.length, candidate=candidate, seed=seed)
        metrics = metric_bundle(candidate, seed, display, bag, raw_sources_payload)
        rel = f"alternatives/{alternative_id}-relationships.json"
        geo = f"alternatives/{alternative_id}.geojson"
        write_json(root / geo, geometry_feature(mapping(candidate), {"alternative_id": alternative_id, "status": "BLOCKED_FOR_HUMAN_SEGMENT_REVIEW", "selection_rule": label, "source": "BGT polygonized boundary faces"}))
        write_json(root / rel, {"schema_version": "m2-r07-alternative-boundary-relationships", "alternative_id": alternative_id, "selection_rule": label, "face_overlap_threshold": threshold, "edges": alt_edges, "supplementary_runs": enriched_alt_runs, "semantic_gate": gate})
        alternative_records.append({
            "alternative_id": alternative_id,
            "label": label,
            "status": "BLOCKED_FOR_HUMAN_SEGMENT_REVIEW",
            "selection_rule_status": "UNAPPROVED_SELECTION_RULE",
            "geometry_path": geo,
            "geometry_sha256": sha256(root / geo),
            "relationship_path": rel,
            "relationship_sha256": sha256(root / rel),
            "metrics": metrics,
            "supplementary_spans": enriched_alt_runs,
            "semantic_gate": gate,
            "unresolved_sections": [section for run in enriched_alt_runs for section in run["sections"]],
        })

    # Copy raw snapshots into a self-contained source folder for offline review.
    for collection in COLLECTIONS:
        copy_file(r07 / "sources/raw" / f"pdok-bgt-{collection}-m4h.json", root / "sources/raw" / f"pdok-bgt-{collection}-m4h.json")
    copy_file(r07 / "sources/raw/pdok-bag-pand-m4h.json", root / "sources/raw/pdok-bag-pand-m4h.json")
    copy_file(r07 / "parent-v4/parent-v3/site-proposal.json", root / "sources/v3-seed/site-proposal.json")
    # Keep the original boundary bytes under r07-reference/.  The package-local
    # display copy is explicitly labelled rejected so it cannot be mistaken for
    # an approvable proposal while reviewing this decision package.
    rejected_boundary = load_json(r07 / "boundary-epsg28992-v5.geojson")
    rejected_boundary["properties"] = {
        **(rejected_boundary.get("properties") or {}),
        "status": "REJECTED_REVIEW_REQUIRED",
        "rejection_marker": REJECTION_MARKER,
        "historical_source_status": "PROPOSED",
    }
    write_json(root / "r07-rejected-perimeter.geojson", rejected_boundary)
    copy_file(r07 / "sources/boundary-relationship-evidence-v5.json", root / "r07-boundary-relationship-evidence.json")
    r07_manifest = copy_r07_references(r07, root)

    overview_viewport = expand_bounds(seed.bounds, margin_ratio=0.05, minimum=35.0)
    sw_points = [tuple(edge["start_epsg28992"]) for run in problematic for edge in [edges[i] for i in run["edge_indices"]] if tuple(edge["start_epsg28992"])[0] <= 88820 and tuple(edge["start_epsg28992"])[1] <= 435750]
    sw_viewport = expand_bounds((min(p[0] for p in sw_points), min(p[1] for p in sw_points), max(p[0] for p in sw_points), max(p[1] for p in sw_points)), margin_ratio=0.10, minimum=30.0)
    seed_loss = seed.difference(r07_boundary)
    central_geom = max((geom for geom in (list(seed_loss.geoms) if seed_loss.geom_type == "MultiPolygon" else [seed_loss]) if not geom.is_empty), key=lambda geom: geom.area)
    central_viewport = expand_bounds(central_geom.bounds, margin_ratio=0.12, minimum=35.0)
    east_points = [point for edge in edges for point in (tuple(edge["start_epsg28992"]), tuple(edge["end_epsg28992"])) if point[0] >= 89500]
    east_viewport = expand_bounds((min(p[0] for p in east_points), min(p[1] for p in east_points), max(p[0] for p in east_points), max(p[1] for p in east_points)), margin_ratio=0.15, minimum=30.0)

    map_records = []
    map_specs = [
        ("overview", "Rotterdam M4H — R07 rejected perimeter overview", overview_viewport, "complete overview", problematic),
        ("southwest", "Rotterdam M4H — R07 southwest perimeter ambiguity", sw_viewport, "southwest run zoom", [run for run in problematic if run["run_id"] == "supplementary-run-9"] or problematic),
        ("central-indentation", "Rotterdam M4H — R07 central indentation ambiguity", central_viewport, "central notch zoom", [run for run in problematic if run["run_id"] == "supplementary-run-9"] or problematic),
        ("east-junction", "Rotterdam M4H — R07 east junction ambiguity", east_viewport, "east junction zoom", problematic),
    ]
    for name, title, viewport, kind, map_runs in map_specs:
        svg = root / f"map-{name}.svg"
        render = map_svg(svg, title=title, viewport=viewport, seed=seed, r07_boundary=r07_boundary, edges=edges, problematic_runs=map_runs, display=display, created_at=created_at, map_kind=kind)
        png = root / f"map-{name}.png"
        _render_png(svg, png)
        render["svg_sha256"] = sha256(svg)
        render["png_sha256"] = sha256(png)
        render["png_size_bytes"] = png.stat().st_size
        map_records.append(render)

    r07_metrics = metric_bundle(r07_boundary, seed, display, bag, raw_sources_payload)
    review_evidence = {
        "r07_proposal_id": R07_PROPOSAL_ID,
        "r07_status_before_review": r07_proposal.get("status"),
        "r07_geometry_sha256": r07_proposal.get("geometry_sha256"),
        "r07_boundary_sha256": r07_proposal.get("boundary_sha256"),
        "r07_semantic_gate": r07_gate,
        "r07_metrics": r07_metrics,
        "problematic_runs": problematic,
        "unapproved_face_rule": {"face_overlap_threshold": 0.5, "selected_faces": audit["selection"]["selected_face_count"], "polygonized_faces": audit["selection"]["polygonized_face_count"], "status": "UNAPPROVED_BOUNDARY_SELECTION_DECISION"},
        "visual_review_findings": [
            "southwest perimeter contains a long source-traced spur/turn sequence",
            "central perimeter follows a deep notch/corridor relative to the v3 seed",
            "east junction has source transitions whose local site-facing role is not established",
        ],
    }
    write_json(root / "problematic-runs.json", {"schema_version": "m2-r07-problematic-runs", "runs": problematic, "review_evidence": review_evidence})
    write_json(root / "decision-alternatives.json", {"schema_version": "m2-r07-decision-alternatives", "alternatives": alternative_records, "winner": None, "human_choice_required": True})

    rejection_record = {
        "schema_version": "m2-r07-rejection-record",
        "task_id": TASK_ID,
        "marker": REJECTION_MARKER,
        "target_proposal_id": R07_PROPOSAL_ID,
        "r07_bytes_preserved": True,
        "evidence": review_evidence,
        "reason": "Endpoint road adjacency does not establish semantic locality. The r07 perimeter contains extended terrain/water runs and a face-overlap rule without human approval.",
    }
    write_json(root / "r07-rejection-record.json", rejection_record)
    event = append_rejection_event(r07, root, review_evidence, created_at)
    write_json(root / "decision-ledger-event.json", event)

    approval = root / "approval-record-r07.md"
    approval.write_text(
        f"# Human boundary-segment decision record — Rotterdam M4H M2-R07\n\n"
        f"Task: `{TASK_ID}`. This package is a boundary-segment decision package, not a SiteProposal.\n\n"
        f"r07 `{R07_PROPOSAL_ID}` is rejected by automated Control Tower review with marker `{REJECTION_MARKER}`. Its original bytes remain retained and hash-checked under `r07-reference/`; no v6 proposal is generated.\n\n"
        "Human decisions are required for each location:\n\n"
        "- **Southwest perimeter:** choose a source-backed segment interpretation, or keep this location `BLOCKED` when no official local road-interface alternative can be proven.\n"
        "- **Central indentation:** choose whether the source-backed notch/corridor belongs to the boundary, or keep it `BLOCKED` when no official alternative can be proven.\n"
        "- **East junction:** choose among the displayed source-backed junction segments, or keep it `BLOCKED` when the official sources do not establish the local role.\n\n"
        "The 0.5 face-overlap selection rule is recorded as an unapproved selection decision. It cannot be used as a human choice or planning standard. The alternatives have no winner; area, perimeter, buildings, crossings, drift, road overlap, supplementary spans, and unresolved sections are shown in `decision-alternatives.json`.\n\n"
        "If there is no provable official source alternative, retain the relevant segment as `BLOCKED` rather than drawing a connector. No approval, acceptance, freeze, effective constraint, site adoption, or Week 3 transition has been recorded.\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "m2-r07-boundary-decision-package",
        "task_id": TASK_ID,
        "package_type": "BOUNDARY_SEGMENT_DECISION_PACKAGE",
        "status": "REJECTED_REVIEW_REQUIRED",
        "created_at": created_at,
        "r07_proposal_id": R07_PROPOSAL_ID,
        "r07_rejection_marker": REJECTION_MARKER,
        "r07_status_not_approvable": True,
        "v6_proposal_generated": False,
        "human_choice_required": True,
        "winner": None,
        "r07_reference_manifest_path": "r07-byte-integrity.json",
        "r07_reference_manifest_sha256": sha256(root / "r07-byte-integrity.json"),
        "r07_rejection_record_path": "r07-rejection-record.json",
        "r07_rejection_record_sha256": sha256(root / "r07-rejection-record.json"),
        "r07_rejected_perimeter_path": "r07-rejected-perimeter.geojson",
        "r07_rejected_perimeter_sha256": sha256(root / "r07-rejected-perimeter.geojson"),
        "decision_ledger_event_path": "decision-ledger-event.json",
        "decision_ledger_event_sha256": sha256(root / "decision-ledger-event.json"),
        "alternatives_path": "decision-alternatives.json",
        "alternatives_sha256": sha256(root / "decision-alternatives.json"),
        "problematic_runs_path": "problematic-runs.json",
        "problematic_runs_sha256": sha256(root / "problematic-runs.json"),
        "maps": map_records,
        "alternative_count": len(alternative_records),
        "r07_semantic_gate": r07_gate,
        "offline_rebuild": {"status": "PASS", "mode": "offline", "builder": "scripts/create_boundary_decision_rotterdam_m4h.py", "source_root": str(r07), "alternatives_recomputed": len(alternative_records)},
        "state": {"decision_state_path": "decision-state.sqlite3", "project_site_id": None, "approval_recorded": False, "freeze_recorded": False},
        "source_colors": SOURCE_COLORS,
        "r07_metrics": r07_metrics,
    }
    write_json(root / "package-manifest.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--r07-dir", type=Path, default=Path(DEFAULT_R07_RELATIVE))
    parser.add_argument("--created-at", default=DEFAULT_CREATED_AT)
    parser.add_argument("--offline", action="store_true", default=True)
    args = parser.parse_args(argv)
    try:
        manifest = build_decision_package(args.output_dir, r07_dir=args.r07_dir, created_at=args.created_at, offline=True)
    except DecisionPackageBuildError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"package": manifest["package_type"], "status": manifest["status"], "path": str(Path(args.output_dir).resolve()), "r07_rejection_marker": REJECTION_MARKER, "v6_proposal_generated": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
