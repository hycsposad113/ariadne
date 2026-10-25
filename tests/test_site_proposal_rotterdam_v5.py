import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pyproj import Transformer
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v5/run-20260915T150000Z"
R07_PACKAGE = ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v5/run-20260916T093310Z"
V4 = ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v4/run-20260915T125400Z"


def test_official_overlay_fails_closed_when_strict_perimeter_is_not_available():
    from scripts.create_site_proposal_rotterdam_v5 import ProposalBuildError, _selected_union

    seed = shape(json.loads((PACKAGE / "parent-v4/parent-v3/site-proposal.json").read_text())["geometry"])
    collections = [
        ("wegdeel", PACKAGE / "sources/raw/pdok-bgt-wegdeel-m4h.json"),
        ("ondersteunendwegdeel", PACKAGE / "sources/raw/pdok-bgt-ondersteunendwegdeel-m4h.json"),
        ("onbegroeidterreindeel", PACKAGE / "sources/raw/pdok-bgt-onbegroeidterreindeel-m4h.json"),
        ("waterdeel", PACKAGE / "sources/raw/pdok-bgt-waterdeel-m4h.json"),
        ("begroeidterreindeel", PACKAGE / "sources/raw/pdok-bgt-begroeidterreindeel-m4h.json"),
    ]
    with pytest.raises(ProposalBuildError, match="strict-valid closed perimeter"):
        _selected_union(seed, collections)


def test_polygonized_face_candidate_traces_every_exterior_edge_to_bgt(tmp_path):
    from scripts.create_site_proposal_rotterdam_v5 import _source_face_union

    inverse = Transformer.from_crs(28992, 4326, always_xy=True)
    seed = shape({"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]})
    projected = [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)]
    coordinates = [[list(inverse.transform(x, y)) for x, y in projected]]
    source = tmp_path / "faces.json"
    source.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "id": "face", "geometry": {"type": "Polygon", "coordinates": coordinates}, "properties": {}}]}), encoding="utf-8")

    candidate, edges, details = _source_face_union(seed, [("wegdeel", source)])

    assert candidate.geom_type == "Polygon"
    assert candidate.area == pytest.approx(400.0)
    assert len(edges) == 4
    assert {edge["source_collection"] for edge in edges} == {"wegdeel"}
    assert details["face_overlap_threshold"] == 0.5


def test_polygonized_face_candidate_groups_official_junction_supplements_between_roads():
    from scripts.create_site_proposal_rotterdam_v5 import _source_face_union

    seed = shape(json.loads((PACKAGE / "parent-v4/parent-v3/site-proposal.json").read_text())["geometry"])
    collections = [
        ("wegdeel", PACKAGE / "sources/raw/pdok-bgt-wegdeel-m4h.json"),
        ("ondersteunendwegdeel", PACKAGE / "sources/raw/pdok-bgt-ondersteunendwegdeel-m4h.json"),
        ("onbegroeidterreindeel", PACKAGE / "sources/raw/pdok-bgt-onbegroeidterreindeel-m4h.json"),
        ("waterdeel", PACKAGE / "sources/raw/pdok-bgt-waterdeel-m4h.json"),
        ("begroeidterreindeel", PACKAGE / "sources/raw/pdok-bgt-begroeidterreindeel-m4h.json"),
    ]

    _, _, details = _source_face_union(seed, collections)

    assert details["supplementary_runs_bounded"] is True
    assert "possibly spanning multiple official supplementary collections" in details["supplementary_bound_rule"]
    assert details["unbounded_supplement_runs"] == []
    long_run = max(details["supplementary_runs"], key=lambda run: run["length_m"])
    assert long_run["source_collections"] == ["begroeidterreindeel", "onbegroeidterreindeel", "waterdeel"]
    assert long_run["length_m"] == pytest.approx(1316.7623802581)
    assert long_run["previous_source_collection"] in {"wegdeel", "ondersteunendwegdeel"}
    assert long_run["next_source_collection"] in {"wegdeel", "ondersteunendwegdeel"}
    assert long_run["bound_by_road_edges"] is True


def test_official_overlay_does_not_select_the_largest_disconnected_component(tmp_path):
    from scripts.create_site_proposal_rotterdam_v5 import ProposalBuildError, _selected_union

    seed = shape(json.loads((PACKAGE / "parent-v4/parent-v3/site-proposal.json").read_text())["geometry"])
    inverse = Transformer.from_crs(28992, 4326, always_xy=True)

    def square(x, y):
        return [[list(inverse.transform(px, py)) for px, py in [(x, y), (x + 5, y), (x + 5, y + 5), (x, y + 5), (x, y)]]]

    min_x, min_y, max_x, max_y = seed.bounds
    interior = seed.buffer(-10)
    candidates = [
        Point(min_x + 20 + 50 * i, min_y + 20 + 50 * j)
        for i in range(int((max_x - min_x) // 50))
        for j in range(int((max_y - min_y) // 50))
        if interior.contains(Point(min_x + 20 + 50 * i, min_y + 20 + 50 * j))
    ]
    first = candidates[0]
    second = next(point for point in candidates[1:] if point.distance(first) > 20)
    payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "id": "a", "geometry": {"type": "Polygon", "coordinates": square(first.x - 2.5, first.y - 2.5)}, "properties": {}},
            {"type": "Feature", "id": "b", "geometry": {"type": "Polygon", "coordinates": square(second.x - 2.5, second.y - 2.5)}, "properties": {}},
        ],
    }
    source = tmp_path / "disconnected.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProposalBuildError, match="one connected Polygon perimeter"):
        _selected_union(seed, [("wegdeel", source)])


def test_v5_validator_rejects_v4_identity_and_keeps_failure_explicit():
    from urban_design.site_proposal_rotterdam_v5 import (
        RotterdamSiteProposalV5ValidationError,
        validate_site_proposal_rotterdam_v5,
    )

    v4 = json.loads((V4 / "site-proposal.json").read_text())
    with pytest.raises(RotterdamSiteProposalV5ValidationError, match="wrong v5 identity/lineage"):
        validate_site_proposal_rotterdam_v5(v4, PACKAGE)


def test_osm_partial_duplicate_is_reconciled_to_bag_for_crossing_decision():
    from pyproj import Transformer
    from scripts.create_site_proposal_rotterdam_v5 import _canonical_osm_building_audit

    inverse = Transformer.from_crs(28992, 4326, always_xy=True)
    def wgs_ring(points):
        return [[list(inverse.transform(x, y)) for x, y in points]]

    boundary = shape({"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]})
    raw = [[(8, 1), (10.005, 1), (10.005, 3), (8, 3), (8, 1)]]
    bag_ring = wgs_ring([(8, 1), (10, 1), (10, 3), (8, 3), (8, 1)])
    display = {"features": [{"type": "Feature", "id": "osm-1", "geometry": {"type": "Polygon", "coordinates": raw}, "properties": {"building": "yes", "ref:bag": "bag-1"}}]}
    bag = {"features": [{"type": "Feature", "id": "bag-1", "geometry": {"type": "Polygon", "coordinates": bag_ring}, "properties": {"identificatie": "bag-1"}}]}

    crossings, reconciliations = _canonical_osm_building_audit(display, bag, boundary)

    assert crossings == []
    assert len(reconciliations) == 1
    assert reconciliations[0]["decision"] == "CANONICAL_BAG_DUPLICATE_FOR_PHYSICAL_CROSSING"


def test_blocked_record_retains_v4_rejection_marker_and_no_proposal():
    status = json.loads((PACKAGE / "package-status.json").read_text())
    evidence = json.loads((PACKAGE / "blocked-evidence-v5.json").read_text())
    assert status["status"] == "BLOCKED"
    assert status["proposal_written"] is False
    assert evidence["site_proposal_written"] is False
    assert evidence["v4_rejection"]["marker"] == "REJECTED_BY_CONTROL_TOWER_INVALID_SITE_SEMANTICS"
    assert evidence["official_overlay_attempt"]["site_building_centroid_count"] == 11
    assert not (PACKAGE / "site-proposal.json").exists()


def test_semantic_validator_rejects_v4_collapse_zero_buildings_road_dominance_and_drift():
    from urban_design.site_proposal_rotterdam_v5 import (
        RotterdamSiteProposalV5ValidationError,
        _validate_metrics,
    )

    seed = shape(json.loads((PACKAGE / "parent-v4/parent-v3/site-proposal.json").read_text())["geometry"])
    v4 = shape(json.loads((V4 / "boundary-epsg28992-v4.geojson").read_text())["geometry"])

    def metrics(candidate, *, buildings=31, road_ratio=0.1):
        return {
            "intersection_area_m2": seed.intersection(candidate).area,
            "symmetric_difference_area_m2": seed.symmetric_difference(candidate).area,
            "area_ratio_candidate_to_seed": candidate.area / seed.area,
            "relative_area_delta": abs(candidate.area - seed.area) / seed.area,
            "road_surface_overlap_ratio": road_ratio,
            "candidate_building_centroid_count": buildings,
            "seed_building_centroid_count": 31,
        }

    for candidate, kwargs in [
        (v4, {}),
        (seed, {"buildings": 0}),
        (seed, {"road_ratio": 0.8}),
    ]:
        with pytest.raises(RotterdamSiteProposalV5ValidationError):
            _validate_metrics(PACKAGE, {"intent_drift_metrics": metrics(candidate, **kwargs)}, candidate, {})


def test_additional_official_scheiding_layer_does_not_close_source_graph():
    evidence = json.loads((PACKAGE / "blocked-evidence-v5.json").read_text())
    result = evidence["southwest_source_graph"]["scheiding_lijn_result"]
    assert result["feature_count"] == 561
    assert result["all_five_guide_edges_nearest_distance_m"] == 0.0
    assert result["connected_path_found"] is False


def test_v5_cli_uses_the_explicit_road_snapshot(monkeypatch, tmp_path):
    import scripts.create_site_proposal_rotterdam_v5 as builder

    captured = {}

    def fake_build(output_dir, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            id="site-proposal-rotterdam-m4h-v5",
            version="v5",
            status="PROPOSED",
            boundary_sha256="sha256:boundary",
            geometry_sha256="sha256:geometry",
        )

    monkeypatch.setattr(builder, "build_rotterdam_v5", fake_build)
    road = tmp_path / "road.json"
    road.write_text("{}", encoding="utf-8")
    args = [
        "--output-dir", str(tmp_path / "output"),
        "--v4-dir", str(tmp_path / "v4"),
        "--wegdeel-source", str(road),
        "--offline",
    ]
    for collection in ["ondersteunendwegdeel", "onbegroeidterreindeel", "waterdeel", "begroeidterreindeel"]:
        args.extend([f"--{collection}-source", str(tmp_path / f"{collection}.json")])

    assert builder.main(args) == 0
    assert captured["wegdeel_source"] == road


def test_appended_topology_audit_keeps_latest_run_blocked():
    run = ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v5/run-20260915T233000Z"
    status = json.loads((run / "package-status-r03.json").read_text())
    audit = json.loads((run / "topology-gate-audit-v5-r03.json").read_text())
    assert status["status"] == "BLOCKED"
    assert status["blocked_evidence_path"] == "blocked-evidence-v5-r03.json"
    assert audit["supplementary_runs_bounded"] is False
    assert audit["offline_rebuild"]["exit_code"] == 2
    assert not (run / "site-proposal.json").exists()


def test_appended_face_subset_audit_finds_no_complete_topology_passing_alternative():
    run = ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v5/run-20260915T233000Z"
    status = json.loads((run / "package-status-r04.json").read_text())
    audit = json.loads((run / "face-subset-topology-audit-v5-r04.json").read_text())
    search = audit["exact_seed_component_search"]

    assert status["status"] == "BLOCKED"
    assert status["face_subset_complete_candidate_count"] == 29
    assert status["face_subset_topology_pass_candidate_count"] == 0
    assert search["main_component_site_building_centroid_count"] == 29
    assert search["single_polygon_complete_candidate_count"] == 29
    assert search["topology_pass_candidate_count"] == 0
    assert audit["result"]["proposal_promoted"] is False


def test_latest_r07_package_retains_historical_cross_collection_technical_audit():
    run = ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v5/run-20260916T093310Z"
    status = json.loads((run / "package-status-r06.json").read_text())
    audit = json.loads((run / "topology-gate-audit-v5-r06.json").read_text())
    proposal = json.loads((run / "site-proposal.json").read_text())

    assert status["status"] == "PROPOSED"
    assert status["proposal_written"] is True
    assert status["approval_state"] == "HUMAN_DECISION_REQUIRED"
    assert status["project_site_id"] is None
    assert status["supplementary_runs_bounded"] is True
    assert status["unbounded_supplement_run_count"] == 0
    assert audit["topology_gate"]["aggregated_supplementary_run_count"] == 9
    assert audit["topology_gate"]["unbounded_supplementary_runs"] == []
    assert proposal["status"] == "PROPOSED"
    assert proposal["human_decision_status"] == "HUMAN_DECISION_REQUIRED"
    assert proposal["supersedes_proposal_id"] == "site-proposal-rotterdam-m4h-v4"
    assert proposal["delft_context"]["intent_drift_metrics"]["candidate_building_centroid_count"] == 31
    assert proposal["delft_context"]["boundary_options"]["B"]["status"] == "REJECTED_BY_HUMAN_FEEDBACK"
    assert proposal["delft_context"]["v4_rejection_marker"] == "REJECTED_BY_CONTROL_TOWER_INVALID_SITE_SEMANTICS"


def test_semantic_gate_rejects_one_kilometre_arc_even_when_endpoints_are_roads():
    from urban_design.boundary_decision_rotterdam_m4h import evaluate_supplementary_semantics

    arc = {
        "edge_start": 10,
        "edge_end": 109,
        "edge_count": 100,
        "length_m": 1000.0,
        "source_collections": ["onbegroeidterreindeel"],
        "start_epsg28992": [0.0, 0.0],
        "end_epsg28992": [10.0, 0.0],
        "previous_source_collection": "wegdeel",
        "next_source_collection": "wegdeel",
    }
    result = evaluate_supplementary_semantics([arc], perimeter_m=1200.0)
    assert result["pass"] is False
    assert "SUPPLEMENTARY_SPAN_TOO_LONG_FOR_LOCAL_INTERFACE" in {item["code"] for item in result["failures"]}
    assert "SUPPLEMENTARY_DETOUR_OR_SPUR" in {item["code"] for item in result["failures"]}


def test_semantic_gate_is_invariant_to_re_grouping_of_the_same_arc():
    from urban_design.boundary_decision_rotterdam_m4h import evaluate_supplementary_semantics

    base = {
        "source_collections": ["onbegroeidterreindeel"],
        "previous_source_collection": "wegdeel",
        "next_source_collection": "wegdeel",
    }
    grouped = {**base, "edge_start": 1, "edge_end": 100, "edge_count": 100, "length_m": 1000.0}
    split = [
        {**base, "edge_start": i * 25, "edge_end": i * 25 + 24, "edge_count": 25, "length_m": 250.0}
        for i in range(4)
    ]
    grouped_result = evaluate_supplementary_semantics([grouped], perimeter_m=1200.0)
    split_result = evaluate_supplementary_semantics(split, perimeter_m=1200.0)
    assert grouped_result["pass"] is False
    assert split_result["pass"] is False
    assert "TOTAL_SUPPLEMENTARY_SPAN_EXCEEDS_LOCAL_REVIEW_BUDGET" in {item["code"] for item in split_result["failures"]}


def test_latest_r07_package_is_rejected_by_the_new_semantic_gate():
    from urban_design.site_proposal_rotterdam_v5 import (
        RotterdamSiteProposalV5ValidationError,
        validate_site_proposal_rotterdam_v5,
    )

    proposal = json.loads((R07_PACKAGE / "site-proposal.json").read_text())
    with pytest.raises(RotterdamSiteProposalV5ValidationError, match="not semantically bounded"):
        validate_site_proposal_rotterdam_v5(proposal, R07_PACKAGE)
