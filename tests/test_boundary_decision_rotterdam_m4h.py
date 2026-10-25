import hashlib
import json
import sqlite3
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts/milestone2-boundary-decision-rotterdam-m4h/run-20260916T123000Z"
R07 = ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v5/run-20260916T093310Z"
MARKER = "REJECTED_BY_CONTROL_TOWER_SUPPLEMENTARY_TOPOLOGY_NOT_SEMANTICALLY_BOUNDED"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_decision_package_is_review_only_and_has_no_winner_or_v6():
    manifest = read_json(PACKAGE / "package-manifest.json")
    assert manifest["package_type"] == "BOUNDARY_SEGMENT_DECISION_PACKAGE"
    assert manifest["status"] == "REJECTED_REVIEW_REQUIRED"
    assert manifest["r07_rejection_marker"] == MARKER
    assert manifest["human_choice_required"] is True
    assert manifest["winner"] is None
    assert manifest["v6_proposal_generated"] is False
    assert manifest["alternative_count"] == 3
    assert not (PACKAGE / "site-proposal.json").exists()
    assert not list(PACKAGE.glob("*v6*"))
    rejected_perimeter = read_json(PACKAGE / manifest["r07_rejected_perimeter_path"])
    assert rejected_perimeter["properties"]["status"] == "REJECTED_REVIEW_REQUIRED"
    assert rejected_perimeter["properties"]["rejection_marker"] == MARKER
    assert "sha256:" + hashlib.sha256((PACKAGE / manifest["r07_rejected_perimeter_path"]).read_bytes()).hexdigest() == manifest["r07_rejected_perimeter_sha256"]


def test_decision_package_contains_all_maps_with_rendered_dimensions_and_source_layers():
    manifest = read_json(PACKAGE / "package-manifest.json")
    assert {item["map_kind"] for item in manifest["maps"]} == {
        "complete overview",
        "southwest run zoom",
        "central notch zoom",
        "east junction zoom",
    }
    for item in manifest["maps"]:
        svg = PACKAGE / item["path"]
        png = PACKAGE / item["path"].replace(".svg", ".png")
        assert svg.is_file() and png.is_file()
        text = svg.read_text(encoding="utf-8")
        assert 'id="source-edges"' in text
        assert MARKER in text
        raw = png.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", raw[16:24]) == (1240, 850)
        assert any(byte not in (0, 255) for byte in raw[32:])


def test_problematic_runs_retain_source_features_functions_adjacent_roads_and_turn_sections():
    evidence = read_json(PACKAGE / "problematic-runs.json")
    by_length = sorted(evidence["runs"], key=lambda run: run["length_m"], reverse=True)
    assert [round(run["length_m"], 6) for run in by_length] == [1316.762380, 305.786639]
    assert any("waterdeel" in run["source_collections"] for run in by_length)
    for run in by_length:
        assert run["source_feature_ids"]
        assert run["source_functions"]
        assert run["previous_source_collection"] in {"wegdeel", "ondersteunendwegdeel"}
        assert run["next_source_collection"] in {"wegdeel", "ondersteunendwegdeel"}
        assert run["previous_source_attributes"]["functie"]
        assert run["next_source_attributes"]["functie"]
        assert run["sections"]
        assert all(section["semantic_status"] == "UNRESOLVED_LOCAL_JUNCTION_ROLE" for section in run["sections"])
        assert all("direction change" in section["turn_basis"] and "25 degrees" in section["turn_basis"] for section in run["sections"])


def test_alternatives_have_recomputable_metric_bundle_and_no_selection_winner():
    data = read_json(PACKAGE / "decision-alternatives.json")
    assert data["winner"] is None
    assert data["human_choice_required"] is True
    assert len(data["alternatives"]) == 3
    required = {
        "area_m2",
        "perimeter_m",
        "site_building_count",
        "bag_crossing_count",
        "osm_crossing_count",
        "v3_intersection_area_m2",
        "v3_symmetric_difference_area_m2",
        "v3_area_ratio",
        "v3_relative_area_delta",
        "road_overlap_ratio",
    }
    for alternative in data["alternatives"]:
        assert alternative["status"] == "BLOCKED_FOR_HUMAN_SEGMENT_REVIEW"
        assert alternative["selection_rule_status"] == "UNAPPROVED_SELECTION_RULE"
        assert required <= alternative["metrics"].keys()
        assert alternative["metrics"]["site_building_count"] == 31
        assert alternative["metrics"]["bag_crossing_count"] == 0
        assert alternative["metrics"]["osm_crossing_count"] == 0
        assert alternative["semantic_gate"]["status"] == "REJECTED"
        assert alternative["unresolved_sections"]
        assert (PACKAGE / alternative["geometry_path"]).is_file()
        assert (PACKAGE / alternative["relationship_path"]).is_file()


def test_rejection_event_is_appended_without_approval_or_new_siteproposal():
    record = read_json(PACKAGE / "r07-rejection-record.json")
    event_record = read_json(PACKAGE / "decision-ledger-event.json")
    assert record["marker"] == MARKER
    assert record["r07_bytes_preserved"] is True
    assert event_record["event_id"] == "event-m2-r07-reject-v5-supplementary-topology"
    assert event_record["action"] == "Reject"
    assert event_record["reason"] == MARKER
    assert event_record["target_type"] == "SiteProposal"

    with sqlite3.connect(PACKAGE / "decision-state.sqlite3") as con:
        latest = con.execute(
            "select event_id, action, reason, sequence from ledger_events order by sequence desc limit 1"
        ).fetchone()
        assert latest == (event_record["event_id"], "Reject", MARKER, event_record["sequence"])
        assert not con.execute(
            "select 1 from ledger_events where lower(action) like '%approve%' or lower(action) like '%accept%' or lower(action) like '%freeze%'"
        ).fetchone()
        project_payloads = [
            json.loads(row[0])
            for row in con.execute("select payload_json from state_versions where entity_type='Project'")
        ]
        assert any(item.get("id") == "rotterdam-m4h-pilot-project" and item.get("site_id") is None for item in project_payloads)
        assert not con.execute(
            "select 1 from ledger_events where sequence > ?", (event_record["sequence"],)
        ).fetchone()


def test_r07_all_bytes_match_manifest_and_original_package_remains_unchanged():
    manifest = read_json(PACKAGE / "r07-byte-integrity.json")
    assert manifest["source_run"] == R07.name
    source_root = (PACKAGE / manifest["source_root"]).resolve()
    assert source_root == R07.resolve()
    assert manifest["file_count"] == len(manifest["files"])
    for item in manifest["files"]:
        source = source_root / item["relative_path"]
        assert source.is_file()
        assert source.stat().st_size == item["size_bytes"]
        assert "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"]

    for relative in [
        "site-proposal.json",
        "boundary-epsg28992-v5.geojson",
        "topology-gate-audit-v5-r06.json",
        "proposal-state.sqlite3",
    ]:
        assert (PACKAGE / "r07-reference" / relative).read_bytes() == (R07 / relative).read_bytes()
