from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from urban_design.site_proposal import SiteProposal, SiteProposalValidationError, V2SourceRecord
from urban_design.site_proposal_v2 import (
    SiteProposalV2ValidationError,
    validate_context_map,
    validate_site_proposal_v2,
    verify_v1_integrity,
)
from urban_design.store import ProjectStateStore


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT / "artifacts" / "milestone2-site-proposal" / "run-20260915T000500Z"
V2_ROOT = ROOT / "artifacts" / "milestone2-site-proposal-v2" / "run-20260915T013000Z"


@pytest.fixture(scope="module")
def v2_payload() -> dict[str, object]:
    return json.loads((V2_ROOT / "site-proposal-v2.json").read_text(encoding="utf-8"))


def test_v1_integrity_manifest_rehashes_every_retained_file() -> None:
    manifest = V2_ROOT / "v1-integrity.json"
    result = verify_v1_integrity(manifest, V1_ROOT)
    entries = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    assert result["file_count"] == len(entries)
    assert result["file_count"] >= 10
    assert {entry["path"] for entry in entries} >= {
        "boundary-epsg28992.geojson",
        "map-preview.svg",
        "site-proposal.json",
        "proposal-state.sqlite3",
    }


def test_v2_package_validates_against_retained_bytes(v2_payload: dict[str, object]) -> None:
    proposal = validate_site_proposal_v2(v2_payload, V2_ROOT, v1_root=V1_ROOT)
    assert proposal.id == "site-proposal-delft-v2"
    assert proposal.version == "v2"
    assert proposal.status == "PROPOSED"


def test_context_missing_or_hash_tamper_fails(v2_payload: dict[str, object], tmp_path: Path) -> None:
    package = tmp_path / "package"
    shutil.copytree(V2_ROOT, package)
    context = package / "context-delft-municipality.geojson"
    context.unlink()
    with pytest.raises(SiteProposalV2ValidationError, match="municipality context artifact"):
        validate_site_proposal_v2(v2_payload, package)

    shutil.copy2(V2_ROOT / "context-delft-municipality.geojson", context)
    context.write_bytes(context.read_bytes() + b" ")
    with pytest.raises(SiteProposalV2ValidationError, match="municipality context artifact hash"):
        validate_site_proposal_v2(v2_payload, package)


def test_nominatim_bbox_alone_cannot_satisfy_v2_containment(v2_payload: dict[str, object]) -> None:
    payload = json.loads(json.dumps(v2_payload))
    context = payload["delft_context"]
    assert isinstance(context, dict)
    context["containment_status"] = "WITHIN_CONTEXT_BBOX"
    context["evidence_ref"] = "source-nominatim-delft-anchor-v2"
    with pytest.raises(ValueError, match="independent municipal boundary|Nominatim bbox"):
        SiteProposal.model_validate(payload)


def test_context_map_required_tokens_and_hash_are_enforced(tmp_path: Path) -> None:
    source_map = V2_ROOT / "map-preview-v2.svg"
    validate_context_map(source_map)
    broken = tmp_path / "broken.svg"
    broken.write_text(source_map.read_text(encoding="utf-8").replace("Buildings", "Structures"), encoding="utf-8")
    with pytest.raises(SiteProposalV2ValidationError, match="missing buildings"):
        validate_context_map(broken)
    with pytest.raises(SiteProposalV2ValidationError, match="hash mismatch"):
        validate_context_map(source_map, expected_sha256="sha256:" + "0" * 64)


def test_every_observed_source_has_independent_timing_retained_bytes_and_license() -> None:
    payload = json.loads((V2_ROOT / "sources" / "source-records-v2.json").read_text(encoding="utf-8"))
    records = [V2SourceRecord.model_validate(item) for item in payload["records"]]
    assert records
    for record in records:
        assert record.license.strip()
        assert record.attribution.strip()
        if record.availability != "OBSERVED":
            continue
        assert record.request_url
        assert record.request_started_at is not None
        assert record.request_finished_at is not None
        assert record.request_finished_at >= record.request_started_at
        artifact = V2_ROOT / str(record.artifact_path)
        assert artifact.is_file()
        assert artifact.stat().st_size == record.artifact_size_bytes
        from urban_design.site_proposal import sha256_file

        assert sha256_file(artifact) == record.artifact_sha256


def test_exact_polygon_link_separate_taxonomy_and_no_scale_gate(v2_payload: dict[str, object]) -> None:
    context = v2_payload["delft_context"]
    assert isinstance(context, dict)
    records_payload = json.loads((V2_ROOT / "sources" / "source-records-v2.json").read_text(encoding="utf-8"))
    exact = next(item for item in records_payload["records"] if item["id"] == "source-osm-exact-polygon-context")
    assert exact["parameters"]["query_boundary_sha256"] == context["candidate_boundary_wgs84_sha256"]
    assert exact["coverage"]["exact_polygon_query"] is True
    edge_ids = {str(edge["osm_way_id"]) for edge in v2_payload["selection_criteria"]["edges"]}
    retained_ids = {
        str(item["id"])
        for item in json.loads((V2_ROOT / str(exact["artifact_path"])).read_text(encoding="utf-8")).get("elements", [])
        if item.get("type") == "way"
    }
    assert edge_ids <= retained_ids
    assert set((exact["coverage"]["shop_tag_counts"]).keys()) >= {"supermarket", "convenience", "grocery", "other"}
    assert v2_payload["taxonomy_status"] == "PROPOSED"
    assert v2_payload["selection_criteria_status"] == "PROPOSED_PROJECT_DECISION"
    assert v2_payload["scale_parameters"]["status"] == "PROPOSED_PROJECT_DECISION"
    assert v2_payload["scale_parameters"]["thresholds"] is None
    assert "50_000 <=" not in (ROOT / "scripts" / "create_site_proposal.py").read_text(encoding="utf-8")


def test_v2_lineage_replay_stays_proposed_without_human_decision(v2_payload: dict[str, object]) -> None:
    assert v2_payload["supersedes_proposal_id"] == "site-proposal-delft-v1"
    assert set(v2_payload["parent_refs"]) >= {"site-proposal-delft-v1", "m2-r01-v1-integrity"}
    with ProjectStateStore(V2_ROOT / "proposal-state-v2.sqlite3", read_only=True) as store:
        project = store.current("delft-pilot-project")
        assert project.get("site_id") is None
        proposal = store.replay("site-proposal-delft-v2")
        assert proposal.get("status") == "PROPOSED"
        site = store.replay("site-delft-v2")
        assert site.get("status") == "proposed"
        events = store.events(project_id="delft-pilot-project")
        assert any(event.target_id == "site-proposal-delft-v2" and event.supersedes == "site-proposal-delft-v1" for event in events)
        assert any(event.target_id == "site-delft-v2" and event.supersedes == "site-delft-v1" for event in events)
        assert all(event.target_type != "HumanDecision" for event in events)


def test_v2_candidate_geometry_and_crs_tamper_are_rejected(v2_payload: dict[str, object], tmp_path: Path) -> None:
    bad_crs = json.loads(json.dumps(v2_payload))
    bad_crs["horizontal_crs"] = "EPSG:4326"
    with pytest.raises(ValueError, match="projected CRS"):
        SiteProposal.model_validate(bad_crs)

    bad_geometry = json.loads(json.dumps(v2_payload))
    geometry = bad_geometry["geometry"]
    assert isinstance(geometry, dict)
    geometry["coordinates"][0][1][0] += 1.0
    with pytest.raises(ValueError, match="geometry_sha256"):
        SiteProposal.model_validate(bad_geometry)

    package = tmp_path / "m2-r01-crs-tamper"
    shutil.copytree(V2_ROOT, package)
    boundary_path = package / str(v2_payload["boundary_artifact_path"])
    boundary = json.loads(boundary_path.read_text(encoding="utf-8"))
    boundary["crs"]["properties"]["name"] = "EPSG:4326"
    boundary_path.write_text(json.dumps(boundary), encoding="utf-8")
    with pytest.raises(SiteProposalValidationError, match="projected CRS"):
        validate_site_proposal_v2(v2_payload, package)


def test_v1_artifacts_are_not_rewritten_by_v2_package(v2_payload: dict[str, object]) -> None:
    # The v2 manifest is a complete byte-level record of the closed v1 package.
    # Re-running this check is the release-blocking preservation assertion.
    result = verify_v1_integrity(V2_ROOT / "v1-integrity.json", V1_ROOT)
    assert result["file_count"] == len(json.loads((V2_ROOT / "v1-integrity.json").read_text(encoding="utf-8"))["files"])
