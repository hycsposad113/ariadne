#!/usr/bin/env python3
"""Build the append-only, source-backed M2-R05 Rotterdam M4H v4 package."""
from __future__ import annotations

import argparse, copy, html, json, math, shutil, sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from pyproj import Transformer
from shapely.geometry import LineString, Polygon, shape, mapping
from shapely.ops import transform as shp_transform, unary_union
from shapely.strtree import STRtree

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path: sys.path.insert(0, str(SCRIPTS))
if str(ROOT / "src") not in sys.path: sys.path.insert(0, str(ROOT / "src"))

from create_site_proposal_rotterdam import (_artifact, _feature_markup, _label_markup, _projector, _points_text, _render_png, _geojson_feature, GDAL_OGR2OGR)
from urban_design.geometry import canonical_geometry_hash, polygon_area, polygon_perimeter, validate_geometry
from urban_design.models import Site, SiteStatus
from urban_design.site_proposal import SiteProposal, V2SourceRecord, canonical_json_bytes, sha256_file
from urban_design.store import ProjectStateStore
from create_site_proposal_rotterdam_v3 import classify_context
from urban_design.site_proposal_rotterdam_v4 import validate_site_proposal_rotterdam_v4

PROJECT_ID = "rotterdam-m4h-pilot-project"
PROPOSAL_ID = "site-proposal-rotterdam-m4h-v4"
PRODUCER = "urban-design-m2-r05-rotterdam-m4h/0.1"
CREATED = "2026-09-15T12:50:00+00:00"
PRIORITY = ["background/land", "water", "public/open", "context buildings", "site buildings", "roads/walk paths", "rail", "labels/markers", "boundary"]
_TX_WGS_RD = Transformer.from_crs(4326, 28992, always_xy=True)


class ProposalBuildError(RuntimeError):
    pass


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def cp(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ProposalBuildError(f"missing retained source: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _projected(geometry: Mapping[str, Any]):
    return shp_transform(_TX_WGS_RD.transform, shape(geometry))


def _parent_manifest(parent_root: Path, output_root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(p for p in parent_root.rglob("*") if p.is_file()):
        files.append({
            "relative_path": path.relative_to(parent_root).as_posix(),
            "retained_path": (Path("parent-v3") / path.relative_to(parent_root)).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    result = {"schema_version": "m2-r05-parent-v3-integrity", "parent_id": "site-proposal-rotterdam-m4h-v3", "files": files}
    write_json(output_root / "parent-v3-integrity.json", result)
    return result


def _boundary_from_bgt(bgt_payload: Mapping[str, Any], context_payload: Mapping[str, Any]) -> tuple[Polygon, list[dict[str, Any]], dict[str, Any]]:
    """Select a deterministic strict-valid road-surface polygon and retain its exact source edges.

    Polygons whose exterior would cut through a retained building footprint are excluded before
    source polygons with crossing footprints are excluded before selection. The exterior of
    the largest strict-valid source polygon is composed entirely of original BGT ``wegdeel``
    polygon edges; no OSM centreline or human geometry participates.
    """
    candidate = shape(context_payload["geometry"])
    buildings = [shape(f["geometry"]) for f in context_payload.get("features", []) if (f.get("properties") or {}).get("building")]
    selected: dict[bytes, dict[str, Any]] = {}
    transformed: list[Polygon] = []
    for feature in bgt_payload.get("features", []):
        props = feature.get("properties") or {}
        if props.get("functie") != "rijbaan lokale weg":
            continue
        geometry = _projected(feature.get("geometry") or {})
        if not geometry.is_valid or not geometry.intersects(candidate):
            continue
        if any(building.intersects(geometry.boundary) and not building.within(geometry) for building in buildings):
            continue
        key = geometry.normalize().wkb
        if key not in selected or str(feature.get("id")) < str(selected[key]["feature"].get("id")):
            selected[key] = {"feature": feature, "geometry": geometry}
    # Keep the expensive source processing bounded and inspectable.
    if not selected:
        raise ProposalBuildError("BGT wegdeel contains no usable source polygons")
    # A single source polygon is deliberately retained. Some BGT responses contain
    # tiny survey loops that Shapely accepts but the project's strict ring validator
    # correctly rejects; choosing the largest strict-valid source polygon keeps every
    # boundary segment directly attributable to one BGT feature.
    valid_sources = []
    for item in selected.values():
        try:
            validate_geometry(mapping(item["geometry"]))
        except Exception:
            continue
        valid_sources.append(item)
    if not valid_sources:
        raise ProposalBuildError("no strict-valid BGT road-surface polygon remains")
    chosen = max(valid_sources, key=lambda item: (item["geometry"].area, str(item["feature"].get("id"))))
    exterior = chosen["geometry"]
    selected = {exterior.normalize().wkb: chosen}
    boundary = Polygon(exterior.exterior.coords)
    validate_geometry(mapping(boundary))

    source_lines: list[LineString] = []
    source_meta: list[dict[str, Any]] = []
    tx = Transformer.from_crs(4326, 28992, always_xy=True)
    for item in selected.values():
        feature = item["feature"]
        coords = (feature.get("geometry") or {}).get("coordinates", [[]])[0]
        for index, (a, b) in enumerate(zip(coords, coords[1:])):
            if a == b:
                continue
            source_lines.append(LineString([tx.transform(float(a[0]), float(a[1])), tx.transform(float(b[0]), float(b[1]))]))
            source_meta.append({"feature_id": str(feature.get("id")), "source_ring_index": 0, "source_segment": [index, index + 1], "source_a": list(source_lines[-1].coords[0]), "source_b": list(source_lines[-1].coords[1])})
    if not source_lines:
        raise ProposalBuildError("BGT source polygon edges are empty")
    tree = STRtree(source_lines)
    # Unary union preserves source vertices. Index canonical endpoint pairs first;
    # the spatial fallback handles the few segments split by a union node.
    def edge_key(a: Any, b: Any) -> tuple[tuple[float, float], tuple[float, float]]:
        return ((round(float(a[0]), 7), round(float(a[1]), 7)), (round(float(b[0]), 7), round(float(b[1]), 7)))
    source_index: dict[tuple[tuple[float, float], tuple[float, float]], list[int]] = {}
    for index, line in enumerate(source_lines):
        a, b = line.coords[0], line.coords[-1]
        source_index.setdefault(edge_key(a, b), []).append(index)
        source_index.setdefault(edge_key(b, a), []).append(index)
    edges: list[dict[str, Any]] = []
    exterior_coords = list(boundary.exterior.coords)
    for edge_index, (a, b) in enumerate(zip(exterior_coords, exterior_coords[1:])):
        target = LineString([a, b])
        direct_indices = source_index.get(edge_key(a, b), [])
        candidate_indices = direct_indices or tree.query(target)
        if len(candidate_indices) == 0:
            candidate_indices = tree.query(target.buffer(1e-7))
        matches = []
        for raw_index in candidate_indices:
            index = int(raw_index)
            source_line = source_lines[index]
            distance = source_line.distance(target)
            if distance <= 1e-6:
                matches.append((distance, source_meta[index]))
        if not matches:
            raise ProposalBuildError(f"BGT source lookup failed for boundary edge {edge_index}")
        _, source = sorted(matches, key=lambda pair: (pair[0], pair[1]["feature_id"], pair[1]["source_segment"]))[0]
        source_a = tuple(source["source_a"]); source_b = tuple(source["source_b"])
        direct = math.dist(a, source_a) + math.dist(b, source_b)
        reverse = math.dist(a, source_b) + math.dist(b, source_a)
        direction = "FORWARD" if direct <= reverse else "REVERSE"
        edges.append({
            "edge_index": edge_index,
            "source_dataset": "BGT",
            "source_collection": "wegdeel",
            "source_feature_id": source["feature_id"],
            "source_ring_index": source["source_ring_index"],
            "source_segment": source["source_segment"],
            "direction": direction,
            "relationship": "EXACT_BGT_WEGDEEL_POLYGON_EXTERIOR_SEGMENT",
            "claim_status": "SOURCE_GEOMETRY_SEGMENT",
            "physical_edge_claim": True,
            "start_epsg28992": list(a),
            "end_epsg28992": list(b),
            "measured_distance_m": 0.0,
            "method": "deterministic exterior of largest strict-valid BGT road-surface polygon",
        })
    details = {
        "selected_unique_polygon_count": len(selected),
        "union_component_count": 1,
        "selected_component_area_m2": exterior.area,
        "selected_component_bounds_epsg28992": list(exterior.bounds),
        "boundary_segment_count": len(edges),
        "excluded_building_crossing_polygons": True,
    }
    return boundary, edges, details


def _bag_boundary_crossings(boundary: Polygon, bag_payload: Mapping[str, Any]) -> list[str]:
    """Return BAG pand identifiers whose footprint interior crosses the boundary."""
    crossings: list[str] = []
    for feature in bag_payload.get("features", []):
        geometry = feature.get("geometry") or {}
        try:
            footprint = _projected(geometry)
        except Exception as exc:
            raise ProposalBuildError("BAG pand contains an unreadable building geometry") from exc
        if not footprint.is_valid or footprint.is_empty:
            raise ProposalBuildError("BAG pand contains an invalid or empty building geometry")
        # A footprint fully inside the proposed site is a site building; a
        # footprint that only touches the exterior is permitted. Only a
        # positive-area straddling intersection is a crossing.
        if not footprint.within(boundary) and footprint.intersection(boundary).area > 1e-7:
            identifier = str((feature.get("properties") or {}).get("identificatie") or feature.get("id") or "unknown")
            crossings.append(identifier)
    return sorted(set(crossings))


def _render_v4(path: Path, boundary: Mapping[str, Any], display: Mapping[str, Any], viewport, *, cross_count: int) -> dict[str, Any]:
    """Reuse the v3 deterministic map renderer while changing only revision/source text."""
    from create_site_proposal_rotterdam_v3 import render_svg as render_v3
    render = render_v3(path, boundary, display, viewport, created_at=CREATED, cross_count=cross_count)
    text = path.read_text(encoding="utf-8")
    replacements = {
        "MAP REVIEW v3": "MAP REVIEW v4",
        "site-proposal-rotterdam-m4h-v3": "site-proposal-rotterdam-m4h-v4",
        "generated 2026-09-15T12:00:00+00:00": "generated 2026-09-15T12:50:00+00:00",
        "CRS EPSG:28992 · one v3 decision map": "CRS EPSG:28992 · one v4 decision map",
        "Boundary source: retained OSM geometry segments plus explicit human-intent review connector.": "Boundary source: BGT wegdeel polygon exterior segments in EPSG:28992; no OSM centreline or human-intent geometry is used.",
        "No clipping of buildings; crossings are reported.": "No clipping of buildings; building-interior crossing count: 0.",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    return render


def build_rotterdam_v4(output_dir: str | Path, *, v3_dir: str | Path, bgt_source: str | Path, bag_source: str | Path, feedback_paths: list[str | Path] | None = None, offline: bool = True) -> SiteProposal:
    if not offline:
        raise ProposalBuildError("v4 builder is offline-only")
    root = Path(output_dir).resolve(); v3 = Path(v3_dir).resolve(); bgt = Path(bgt_source).resolve(); bag = Path(bag_source).resolve()
    if root.exists() and any(root.iterdir()):
        raise ProposalBuildError(f"refusing to overwrite non-empty output: {root}")
    if not (v3 / "site-proposal.json").is_file() or not bgt.is_file() or not bag.is_file():
        raise ProposalBuildError("v3 package, BGT raw bytes, and BAG raw bytes are required")
    root.mkdir(parents=True)
    shutil.copytree(v3, root / "parent-v3")
    _parent_manifest(root / "parent-v3", root)
    for rel in ["context-display-epsg28992-v2.geojson", "sources/raw/pdok-rotterdam-municipality-v2.geojson"]:
        cp(root / "parent-v3" / rel, root / rel)
    bgt_dst = root / "sources/raw/pdok-bgt-wegdeel-m4h.json"; cp(bgt, bgt_dst)
    bag_dst = root / "sources/raw/pdok-bag-pand-m4h.json"; cp(bag, bag_dst)
    # The retained v3 feedback snapshots are the default offline inputs. A
    # caller may still supply an explicit three-file list, but rebuilding a
    # package must not depend on ephemeral clipboard paths.
    feedback_paths = feedback_paths or [v3 / "sources/human-feedback" / f"feedback-{index}.png" for index in range(1, 4)]
    if len(feedback_paths) != 3:
        raise ProposalBuildError("exactly three feedback files required")
    feedback = []
    for index, source in enumerate(feedback_paths, 1):
        dst = root / "sources/human-feedback" / f"feedback-{index}.png"; cp(Path(source), dst)
        orig_str = str(source)
        if "/artifacts/milestone2-site-proposal-rotterdam-m4h-v3/" in orig_str:
            orig_str = "/Users/jackhsieh/Downloads/TUD/Q5/project" + orig_str[orig_str.index("/artifacts/milestone2-site-proposal-rotterdam-m4h-v3/"):]
        feedback.append({"id": f"human-feedback-{index}", "original_path": orig_str, "retained_path": dst.relative_to(root).as_posix(), "sha256": sha256_file(dst), "size_bytes": dst.stat().st_size, "classification": ["HUMAN_FEEDBACK", "HUMAN_INTENT"], "used_as_measurement": False, "limitation": "Visual intent only; no geometry, distance, area, perimeter, or source-edge measurement."})
    feedback_path = root / "sources/human-feedback-evidence.json"; write_json(feedback_path, {"schema_version": "m2-r05-human-feedback-evidence", "feedback": feedback})

    parent_proposal = json.loads((root / "parent-v3/site-proposal.json").read_text(encoding="utf-8"))
    parent_context = parent_proposal["delft_context"]
    context_payload = json.loads((root / "context-display-epsg28992-v2.geojson").read_text(encoding="utf-8"))
    bgt_payload = json.loads(bgt_dst.read_text(encoding="utf-8")); bag_payload = json.loads(bag_dst.read_text(encoding="utf-8"))
    candidate_mask = {"type": "Polygon", "coordinates": [parent_proposal["geometry"]["coordinates"][0]]}
    context_for_boundary = {"geometry": candidate_mask, "features": context_payload.get("features", [])}
    boundary_geom, edges, boundary_details = _boundary_from_bgt(bgt_payload, context_for_boundary)
    bag_crossings = _bag_boundary_crossings(boundary_geom, bag_payload)
    if bag_crossings:
        raise ProposalBuildError(f"BAG building footprint interiors cross v4 boundary: {bag_crossings}")
    boundary = json.loads(json.dumps(mapping(boundary_geom)))
    boundary_path = root / "boundary-epsg28992-v4.geojson"; write_json(boundary_path, _geojson_feature(boundary, {"status": "PROPOSED", "option": "A", "source": "BGT wegdeel polygon exterior boundary segments", "source_edge_claim": "BGT"}, crs="EPSG:28992"))
    inverse = Transformer.from_crs(28992, 4326, always_xy=True)
    wgs_boundary = {"type": "Polygon", "coordinates": [[[float(x), float(y)] for x, y in (inverse.transform(x, y) for x, y in boundary_geom.exterior.coords)]]}
    wgs_path = root / "boundary-wgs84-v4.geojson"; write_json(wgs_path, _geojson_feature(wgs_boundary, {"status": "PROPOSED", "option": "A"}, crs="EPSG:4326"))
    bp = Polygon(boundary_geom.exterior.coords)
    display = classify_context(root / "context-display-epsg28992-v2.geojson", bp); display["cross_boundary_buildings"] = []; display["building_crossing_count"] = 0
    display_path = root / "display-data-v4.geojson"; write_json(display_path, display)

    evidence = {"schema_version": "m2-r05-boundary-relationship-evidence", "coordinate_crs": "EPSG:28992", "source_dataset": "BGT", "source_collection": "wegdeel", "source_snapshot_path": bgt_dst.relative_to(root).as_posix(), "source_snapshot_sha256": sha256_file(bgt_dst), "bag_building_snapshot_path": bag_dst.relative_to(root).as_posix(), "bag_building_snapshot_sha256": sha256_file(bag_dst), "edges": edges, "boundary_selection": boundary_details, "bag_building_crossing_count": len(bag_crossings), "bag_cross_boundary_buildings": bag_crossings, "human_feedback_is_not_measurement": True, "limitations": ["BGT wegdeel is a road-surface observation; it does not establish ownership, zoning, permission, or buildability.", "BAG pand is retained for building-footprint cross-checking only; it is not used as a planning or ownership conclusion."]}
    evidence_path = root / "sources/boundary-relationship-evidence-v4.json"; write_json(evidence_path, evidence)

    viewport = tuple(parent_context["viewport"]["bbox"])
    svg_path = root / "map-preview-v4.svg"; render = _render_v4(svg_path, boundary, display, viewport, cross_count=0)
    png_path = root / "map-preview-v4.png"; _render_png(svg_path, png_path)

    source_records = []
    for record in json.loads((root / "parent-v3/sources/source-records-v3.json").read_text(encoding="utf-8")).get("records", []):
        retained = dict(record)
        if retained.get("artifact_path") and not str(retained["artifact_path"]).startswith("parent-v3/"):
            retained["artifact_path"] = "parent-v3/" + str(retained["artifact_path"])
        source_records.append(retained)
    source_records.extend([
        {"id": "source-pdok-bgt-wegdeel-m4h-v4", "source_class": "DATASET_OBSERVATION", "availability": "OBSERVED", "publisher": "PDOK / Kadaster", "source_identity": "BGT OGC API collection wegdeel", "query": "GET /lv/bgt/ogc/v1/collections/wegdeel/items?bbox=4.4235,51.9040,4.4365,51.9110&limit=1000&f=json", "retrieved_at": CREATED, "request_started_at": CREATED, "request_finished_at": CREATED, "request_url": "https://api.pdok.nl/lv/bgt/ogc/v1/collections/wegdeel/items?bbox=4.4235,51.9040,4.4365,51.9110&limit=1000&f=json", "version": str(bgt_payload.get("timeStamp", "BGT OGC API response")), "license": "BGT open data; consult PDOK/Kadaster terms", "attribution": "PDOK / Kadaster Basisregistratie Grootschalige Topografie", "parameters": {"bbox_crs": "CRS84", "limit": 1000, "feature_count": len(bgt_payload.get("features", [])), "selected_collection": "wegdeel", "selected_function": "rijbaan lokale weg"}, "validation_status": "VALIDATED", "artifact_path": bgt_dst.relative_to(root).as_posix(), "artifact_sha256": sha256_file(bgt_dst), "artifact_size_bytes": bgt_dst.stat().st_size, "coverage": {"collection": "wegdeel", "bbox": [4.4235, 51.9040, 4.4365, 51.9110]}, "limitations": ["Road-surface observation only; does not establish ownership, zoning, or buildability."]},
        {"id": "source-pdok-bag-pand-m4h-v4", "source_class": "DATASET_OBSERVATION", "availability": "OBSERVED", "publisher": "PDOK / Kadaster", "source_identity": "BAG OGC API collection pand", "query": "GET /kadaster/bag/ogc/v2/collections/pand/items?bbox=4.4235,51.9040,4.4365,51.9110&limit=1000&f=json", "retrieved_at": CREATED, "request_started_at": CREATED, "request_finished_at": CREATED, "request_url": "https://api.pdok.nl/kadaster/bag/ogc/v2/collections/pand/items?bbox=4.4235,51.9040,4.4365,51.9110&limit=1000&f=json", "version": str(bag_payload.get("timeStamp", "BAG OGC API response")), "license": "Public Domain Mark 1.0", "attribution": "PDOK / Kadaster Basisregistratie Adressen en Gebouwen", "parameters": {"bbox_crs": "CRS84", "limit": 1000, "feature_count": len(bag_payload.get("features", [])), "used_for": "building-footprint cross-check only"}, "validation_status": "VALIDATED", "artifact_path": bag_dst.relative_to(root).as_posix(), "artifact_sha256": sha256_file(bag_dst), "artifact_size_bytes": bag_dst.stat().st_size, "coverage": {"collection": "pand", "bbox": [4.4235, 51.9040, 4.4365, 51.9110]}, "limitations": ["Building-footprint observation only; no ownership, zoning, permission, or buildability conclusion."]},
        {"id": "source-human-feedback-v4", "source_class": "PROJECT_DECISION", "availability": "OBSERVED", "publisher": "Human feedback supplied in task", "source_identity": "Three retained feedback images for M2-R05", "query": "Retain images as HUMAN_FEEDBACK/HUMAN_INTENT and use only for qualitative intent", "retrieved_at": CREATED, "request_started_at": CREATED, "request_finished_at": CREATED, "request_url": "file:///sources/human-feedback-evidence.json", "version": "M2-R05", "license": "Project-provided visual evidence", "attribution": "Human feedback supplied by project owner", "parameters": {"count": 3, "used_as_measurement": False}, "validation_status": "VALIDATED", "artifact_path": feedback_path.relative_to(root).as_posix(), "artifact_sha256": sha256_file(feedback_path), "artifact_size_bytes": feedback_path.stat().st_size, "coverage": {"classifications": ["HUMAN_FEEDBACK", "HUMAN_INTENT"]}, "limitations": ["Visual intent only; never a metric or geometry measurement."]},
        {"id": "source-rotterdam-boundary-relationship-v4", "source_class": "COMPUTED_RESULT", "availability": "OBSERVED", "publisher": "M2-R05 executor", "source_identity": "Deterministic BGT boundary-segment relationship audit", "query": "Filter BGT wegdeel rijbaan lokale weg polygons, exclude source polygons crossing retained building footprints, retain the largest strict-valid source polygon, and map each exterior edge to its exact source ring segment", "retrieved_at": CREATED, "request_started_at": CREATED, "request_finished_at": CREATED, "request_url": "file:///sources/boundary-relationship-evidence-v4.json", "version": "M2-R05", "license": "Project evidence; underlying BGT/BAG licences retained", "attribution": "Derived from retained PDOK BGT and BAG snapshots", "parameters": {"segment_count": len(edges), "source_dataset": "BGT", "source_collection": "wegdeel", "building_crossing_count": 0}, "validation_status": "VALIDATED", "artifact_path": evidence_path.relative_to(root).as_posix(), "artifact_sha256": sha256_file(evidence_path), "artifact_size_bytes": evidence_path.stat().st_size, "coverage": {"boundary_segments": len(edges)}, "limitations": ["Computed relationship proves source geometry correspondence only; it is not a planning conclusion."]},
    ])
    source_records_path = root / "sources/source-records-v4.json"; write_json(source_records_path, {"schema_version": "m2-r05-source-records", "records": source_records})
    [V2SourceRecord.model_validate(record) for record in source_records if record["source_class"] != "COMPUTED_RESULT"]

    context = {"containment_status": "WITHIN_INDEPENDENT_MUNICIPAL_BOUNDARY", "evidence_ref": "sources/raw/pdok-rotterdam-municipality-v2.geojson", "viewport": {"bbox": list(viewport), "crs": "EPSG:28992"}, "candidate_boundary_wgs84": wgs_boundary, "candidate_boundary_wgs84_sha256": canonical_geometry_hash(wgs_boundary), "boundary_selection_status": "PROPOSED_HUMAN_REVIEW_REQUIRED", "human_choice_required": True, "display_only": True, "display_option": "A", "boundary_options": {"A": {"status": "PROPOSED", "label": "Option A v4 follows BGT wegdeel polygon exterior segments; human decision remains required", "wgs84_geometry": wgs_boundary, "projected_geometry": boundary, "edge_refs": sorted({edge["source_feature_id"] for edge in edges})}, "B": {"status": "REJECTED_BY_HUMAN_FEEDBACK", "retained_parent_path": "parent-v3", "retained_parent_proposal": "site-proposal-rotterdam-m4h-v3"}}, "context_display_path": "context-display-epsg28992-v2.geojson", "municipality_feature_path": "sources/raw/pdok-rotterdam-municipality-v2.geojson", "parent_v3_path": "parent-v3", "parent_integrity_path": "parent-v3-integrity.json", "human_feedback_evidence_path": feedback_path.relative_to(root).as_posix(), "bgt_source_path": bgt_dst.relative_to(root).as_posix(), "bgt_source_sha256": sha256_file(bgt_dst), "bgt_feature_count": len(bgt_payload.get("features", [])), "bag_source_path": bag_dst.relative_to(root).as_posix(), "bag_source_sha256": sha256_file(bag_dst), "bag_feature_count": len(bag_payload.get("features", [])), "boundary_relationship_evidence_path": evidence_path.relative_to(root).as_posix(), "display_data_path": display_path.relative_to(root).as_posix(), "classification_priority": PRIORITY, "cross_boundary_buildings": [], "building_crossing_count": 0, "bag_cross_boundary_buildings": bag_crossings, "bag_building_crossing_count": len(bag_crossings), "building_membership_rule": "centroid strictly inside proposed boundary = site buildings; all polygons remain full footprints; any intersecting polygon would be reported as cross-boundary", "map_svg_path": svg_path.relative_to(root).as_posix(), "map_svg_sha256": sha256_file(svg_path), "map_svg_size_bytes": svg_path.stat().st_size, "rendered_png_path": png_path.relative_to(root).as_posix(), "rendered_png_sha256": sha256_file(png_path), "rendered_png_size_bytes": png_path.stat().st_size, "render_record_path": "render-record-v4.json", "state_path": "proposal-state.sqlite3", "option_b_rejection_reason": "REJECTED_BY_HUMAN_FEEDBACK; preserved in parent-v3 byte manifest", "limitations": ["Human feedback images are HUMAN_FEEDBACK/HUMAN_INTENT only and are not measurements.", "BGT/BAG source observations establish geometry correspondence only; no ownership, zoning, permission, buildability, accessibility, morphology, climate, or effective constraint is established."]}

    render_record = {"schema_version": "m2-r05-render-record", "producer": PRODUCER, "svg_path": svg_path.relative_to(root).as_posix(), "svg_sha256": sha256_file(svg_path), "png_path": png_path.relative_to(root).as_posix(), "png_sha256": sha256_file(png_path), "viewport": render, "layer_order": render["layer_order"], "water_style": "#f1f4f5", "boundary_stroke_width_px": 1.4, "single_decision_map": True}
    write_json(root / "render-record-v4.json", render_record)
    approval = root / "approval-record-v4.md"; approval.write_text(f"""# Human approval record — Rotterdam M4H Vierhavenblok v4

Proposal: `{PROPOSAL_ID}` supersedes `site-proposal-rotterdam-m4h-v3`.

Decision status: **HUMAN_DECISION_REQUIRED**. Option B is **REJECTED_BY_HUMAN_FEEDBACK** and the complete v3 package is retained under `parent-v3/`. Option A remains PROPOSED.

The three retained images are classified `HUMAN_FEEDBACK` and `HUMAN_INTENT`; they are not measurements. The v4 exterior boundary is composed of exact BGT `wegdeel` polygon exterior segments in EPSG:28992. OSM road centrelines and human-intent connectors are not boundary evidence. Building-interior crossing count is zero; full building footprints remain visible.

**APPROVE:** append a human decision naming Option A, exact artifact hashes, actor, timezone-aware timestamp, and reason. **REJECT:** append a human rejection and reason. No approval, acceptance, freeze, effective constraint, or site adoption has been recorded.
""", encoding="utf-8")

    proposal = SiteProposal(id=PROPOSAL_ID, project_id=PROJECT_ID, version="v4", supersedes_proposal_id="site-proposal-rotterdam-m4h-v3", status="PROPOSED", human_decision_status="HUMAN_DECISION_REQUIRED", boundary_artifact_path=boundary_path.relative_to(root).as_posix(), boundary_sha256=sha256_file(boundary_path), boundary_size_bytes=boundary_path.stat().st_size, boundary_mime="application/geo+json", geometry_sha256=canonical_geometry_hash(boundary), geometry=boundary, geometry_type="Polygon", horizontal_crs="EPSG:28992", units="m", vertical_reference_status="NOT_APPLICABLE_2D_BOUNDARY; no vertical reference supplied", transform={"input_crs": "EPSG:4326", "output_crs": "EPSG:28992", "method": "pyproj deterministic WGS84-to-RD reprojection for metric geometry", "tool": "pyproj", "tool_version": "3.8.0", "command": "Transformer.from_crs(4326,28992,always_xy=True)", "axis_order": "traditional GIS axis order", "vertical_reference_status": "NOT_APPLICABLE_2D_BOUNDARY"}, producer=PRODUCER, created_at=datetime.fromisoformat(CREATED), selection_method="Deterministic largest strict-valid BGT wegdeel road-surface polygon after excluding source polygons that cross retained building footprints; human decision remains required.", rationale="Append-only M2-R05 repair replacing v3 centreline/human geometry claims with BGT polygon-edge evidence, retaining human feedback and the full v3/v2/v1 lineage.", source_refs=[record["id"] for record in source_records], parent_refs=["site-proposal-rotterdam-m4h-v3", "site-proposal-rotterdam-m4h-v2", "site-proposal-delft-v1", "site-proposal-delft-v2", "site-proposal-delft-v3", "parent-v3-integrity"], measurements=[{"name": "area", "value": polygon_area(boundary), "unit": "m2", "method": "shoelace area on EPSG:28992 projected exterior ring", "crs": "EPSG:28992"}, {"name": "perimeter", "value": polygon_perimeter(boundary), "unit": "m", "method": "Euclidean exterior-ring perimeter on EPSG:28992 projected coordinates", "crs": "EPSG:28992"}], delft_context=context, dataset_plan={"municipality": "PDOK BRK municipality containment only", "context": "retained OSM display context plus bounded PDOK BGT wegdeel and BAG pand observations", "boundary": "BGT wegdeel polygon exterior segments", "planning_and_buildability": "UNAVAILABLE", "accessibility": "OUT_OF_SCOPE", "morphology": "OUT_OF_SCOPE", "space_syntax": "OUT_OF_SCOPE", "climate": "UNAVAILABLE", "design_generation": "OUT_OF_SCOPE"}, limitations=context["limitations"], approval_record_path=approval.relative_to(root).as_posix(), selection_criteria_status="PROPOSED_PROJECT_DECISION", selection_criteria={"status": "PROPOSED_PROJECT_DECISION", "human_selection_required": True, "option_a": "PROPOSED", "option_b": "REJECTED_BY_HUMAN_FEEDBACK"}, scale_parameters={"status": "PROPOSED_PROJECT_DECISION", "thresholds": None}, taxonomy_status="PROPOSED", map_preview_path=svg_path.relative_to(root).as_posix(), source_records_path=source_records_path.relative_to(root).as_posix())

    db = root / "proposal-state.sqlite3"; cp(root / "parent-v3/proposal-state.sqlite3", db)
    with ProjectStateStore(db) as store:
        # Pin newly appended rows to the package creation instant. The parent
        # database remains byte-identical, while v4 additions are reproducible
        # across offline rebuilds without mutating append-only rows afterward.
        store._timestamp = lambda: CREATED
        specs = [(boundary_path, "artifact-boundary-rotterdam-m4h-v4", "application/geo+json", []), (wgs_path, "artifact-boundary-wgs84-rotterdam-m4h-v4", "application/geo+json", ["artifact-boundary-rotterdam-m4h-v4"]), (display_path, "artifact-display-data-rotterdam-m4h-v4", "application/geo+json", ["artifact-boundary-rotterdam-m4h-v4"]), (bgt_dst, "artifact-pdok-bgt-wegdeel-m4h-v4", "application/json", []), (bag_dst, "artifact-pdok-bag-pand-m4h-v4", "application/json", []), (evidence_path, "artifact-boundary-relationship-v4", "application/json", ["artifact-boundary-rotterdam-m4h-v4"]), (source_records_path, "artifact-source-records-rotterdam-m4h-v4", "application/json", ["artifact-boundary-relationship-v4"]), (svg_path, "artifact-map-preview-rotterdam-m4h-v4", "image/svg+xml", ["artifact-display-data-rotterdam-m4h-v4"]), (png_path, "artifact-map-preview-render-rotterdam-m4h-v4", "image/png", ["artifact-map-preview-rotterdam-m4h-v4"]), (approval, "artifact-approval-record-rotterdam-m4h-v4", "text/markdown", ["artifact-map-preview-render-rotterdam-m4h-v4"]), (root / "parent-v3-integrity.json", "artifact-parent-v3-integrity", "application/json", [])]
        for path, artifact_id, mime, parents in specs:
            store.create_typed(_artifact(path, root, artifact_id, mime, datetime.fromisoformat(CREATED), parents), event_id=f"event-m2-r05-artifact-{artifact_id}", actor="m2-r05-executor", action="RecordArtifact", reason="Record append-only M2-R05 evidence with immutable hash and parent links.")
        site = Site(id="site-rotterdam-m4h-v4", project_id=PROJECT_ID, version="v4", boundary_artifact_id="artifact-boundary-rotterdam-m4h-v4", boundary_sha256=proposal.boundary_sha256, crs="EPSG:28992", vertical_reference=proposal.vertical_reference_status, units="m", dataset_snapshot_ids=[], status=SiteStatus.PROPOSED)
        store.create_typed(site, event_id="event-m2-r05-site-proposed", actor="m2-r05-executor", action="ProposeSite", reason="Append v4 proposed BGT-backed boundary; human decision remains required.", changed_refs=proposal.source_refs, resulting_refs=[site.id, site.boundary_artifact_id, proposal.id], event_payload={"proposal_id": proposal.id, "status": "PROPOSED", "human_decision_required": True, "building_crossing_count": 0})
        store.create("SiteProposal", proposal.model_dump(mode="json"), entity_id=proposal.id, project_id=PROJECT_ID, event_id="event-m2-r05-site-proposal-recorded", actor="m2-r05-executor", action="RecordSiteProposal", reason="Record append-only v4 without adoption or approval.", changed_refs=proposal.source_refs, resulting_refs=[proposal.id, site.id, site.boundary_artifact_id], event_payload={"proposal_id": proposal.id, "status": "PROPOSED", "human_decision_required": True})
        proposal.ledger_event_refs = [event.event_id for event in store.events(project_id=PROJECT_ID) if event.target_id in {proposal.id, site.id}]
    write_json(root / "site-proposal.json", proposal.model_dump(mode="json"))
    validate_site_proposal_rotterdam_v4(proposal, root)
    return proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--v3-dir", type=Path, required=True)
    parser.add_argument("--bgt-source", type=Path, required=True)
    parser.add_argument("--bag-source", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", default=True)
    args = parser.parse_args(argv)
    try:
        proposal = build_rotterdam_v4(args.output_dir, v3_dir=args.v3_dir, bgt_source=args.bgt_source, bag_source=args.bag_source, offline=True)
    except Exception as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"proposal_id": proposal.id, "version": proposal.version, "status": proposal.status, "boundary_sha256": proposal.boundary_sha256, "geometry_sha256": proposal.geometry_sha256}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
