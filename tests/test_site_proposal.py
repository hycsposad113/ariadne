from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from urban_design.geometry import canonical_geometry_hash, polygon_area, polygon_perimeter
from urban_design.models import Project, Site, SiteStatus
from urban_design.site_proposal import (
    Measurement,
    SiteProposal,
    SiteProposalValidationError,
    SourceRecord,
    TransformRecord,
    assert_no_effective_site_conflict,
    assert_site_approval_authorized,
    canonical_json_bytes,
    validate_site_proposal,
)
from urban_design.store import ProjectStateStore


NOW = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)


def _geometry() -> dict[str, object]:
    return {"type": "Polygon", "coordinates": [[[100_000.0, 450_000.0], [100_200.0, 450_000.0], [100_200.0, 450_150.0], [100_000.0, 450_150.0], [100_000.0, 450_000.0]]]}


def _proposal(tmp_path: Path) -> SiteProposal:
    geometry = _geometry()
    boundary = {**geometry, "crs": {"type": "name", "properties": {"name": "EPSG:28992"}}}
    boundary_path = tmp_path / "boundary.geojson"
    boundary_path.write_bytes(canonical_json_bytes(boundary))
    import hashlib

    boundary_hash = "sha256:" + hashlib.sha256(boundary_path.read_bytes()).hexdigest()
    area = polygon_area(geometry)
    perimeter = polygon_perimeter(geometry)
    return SiteProposal(
        id="site-proposal-delft-test-v1",
        project_id="project-test",
        version="v1",
        boundary_artifact_path="boundary.geojson",
        boundary_sha256=boundary_hash,
        boundary_size_bytes=boundary_path.stat().st_size,
        boundary_mime="application/geo+json",
        geometry_sha256=canonical_geometry_hash(geometry),
        geometry=geometry,
        geometry_type="Polygon",
        horizontal_crs="EPSG:28992",
        units="m",
        vertical_reference_status="NOT_APPLICABLE_2D_BOUNDARY",
        transform=TransformRecord(input_crs="EPSG:4326", output_crs="EPSG:28992", method="test transform", tool="test", tool_version="1", command="test", axis_order="lon,lat", vertical_reference_status="not applicable"),
        producer="test",
        created_at=NOW,
        selection_method="fixed test envelope around a retained anchor",
        rationale="test proposal",
        source_refs=["source-anchor"],
        parent_refs=["selection.geojson"],
        measurements=[Measurement(name="area", value=area, unit="m2", method="shoelace", crs="EPSG:28992"), Measurement(name="perimeter", value=perimeter, unit="m", method="euclidean", crs="EPSG:28992")],
        delft_context={"containment_status": "WITHIN_CONTEXT_BBOX", "evidence_ref": "source-anchor"},
        dataset_plan={"climate": "later"},
        limitations=["test data are not a municipal boundary"],
        approval_record_path="approval.md",
    )


def test_valid_roundtrip_hash_and_projected_measurements(tmp_path: Path) -> None:
    proposal = _proposal(tmp_path)
    assert proposal.status == "PROPOSED"
    assert proposal.measurements[0].value == 30_000.0
    assert proposal.measurements[1].value == 700.0
    assert validate_site_proposal(proposal, tmp_path).boundary_sha256 == proposal.boundary_sha256


@pytest.mark.parametrize("crs", ["EPSG:4326", "CRS84", "WGS84"])
def test_metric_epsg4326_is_rejected(crs: str, tmp_path: Path) -> None:
    payload = _proposal(tmp_path).model_dump()
    payload["horizontal_crs"] = crs
    with pytest.raises(ValueError, match="projected CRS"):
        SiteProposal.model_validate(payload)


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Polygon", "coordinates": []},
        {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
        {"type": "Polygon", "coordinates": [[[0, 0, 3], [1, 0, 3], [1, 1, 3], [0, 1, 3], [0, 0, 3]]]},
        {"type": "Point", "coordinates": [0, 0]},
    ],
)
def test_empty_self_intersecting_unclosed_nonfinite_or_mixed_geometry_rejected(geometry: dict[str, object], tmp_path: Path) -> None:
    payload = _proposal(tmp_path).model_dump()
    payload["geometry"] = geometry
    payload["geometry_type"] = geometry["type"]
    payload["geometry_sha256"] = canonical_geometry_hash({"type": "Polygon", "coordinates": _geometry()["coordinates"]})
    with pytest.raises(ValueError):
        SiteProposal.model_validate(payload)


def test_nonfinite_geometry_rejected(tmp_path: Path) -> None:
    payload = _proposal(tmp_path).model_dump()
    payload["geometry"] = {"type": "Polygon", "coordinates": [[[0, 0], [float("nan"), 0], [1, 1], [0, 0]]]}
    with pytest.raises(ValueError):
        SiteProposal.model_validate(payload)


def test_boundary_hash_tamper_is_detected(tmp_path: Path) -> None:
    proposal = _proposal(tmp_path)
    (tmp_path / "boundary.geojson").write_bytes((tmp_path / "boundary.geojson").read_bytes() + b" ")
    with pytest.raises(SiteProposalValidationError, match="hash or size"):
        validate_site_proposal(proposal, tmp_path)


def test_boundary_crs_metadata_is_required(tmp_path: Path) -> None:
    proposal = _proposal(tmp_path)
    geometry = _geometry()
    (tmp_path / "boundary.geojson").write_bytes(canonical_json_bytes(geometry))
    with pytest.raises(SiteProposalValidationError, match="projected CRS"):
        validate_site_proposal(proposal, tmp_path)


def test_source_metadata_and_license_are_required() -> None:
    with pytest.raises(ValueError, match="license"):
        SourceRecord(id="x", source_class="DATASET_OBSERVATION", availability="OBSERVED", publisher="p", source_identity="u", query="q", retrieved_at=NOW, license="", attribution="a", artifact_path="x.json", artifact_sha256="sha256:" + "a" * 64, artifact_size_bytes=1)
    with pytest.raises(ValueError, match="artifact path"):
        SourceRecord(id="x", source_class="DATASET_OBSERVATION", availability="OBSERVED", publisher="p", source_identity="u", query="q", retrieved_at=NOW, license="ODbL", attribution="a")


def test_proposal_does_not_set_project_site_and_replays_as_proposed(tmp_path: Path) -> None:
    proposal = _proposal(tmp_path)
    db = tmp_path / "state.sqlite3"
    with ProjectStateStore(db) as store:
        store.create_typed(Project(id="project-test", name="test"), actor="test", action="CreateProject", reason="test")
        store.create_typed(Site(id="site-test", project_id="project-test", version="v1", boundary_artifact_id="boundary", boundary_sha256=proposal.boundary_sha256, crs="EPSG:28992", units="m", status=SiteStatus.PROPOSED), actor="test", action="ProposeSite", reason="test")
        store.create("SiteProposal", proposal.model_dump(mode="json"), entity_id=proposal.id, project_id="project-test", actor="test", action="RecordSiteProposal", reason="test")
        assert store.current("project-test").get("site_id") is None
        assert store.replay(proposal.id).get("status") == "PROPOSED"
        assert all(event.target_type != "HumanDecision" for event in store.events(project_id="project-test"))


def test_boundary_artifact_preserves_parent_refs_in_state(tmp_path: Path) -> None:
    proposal = _proposal(tmp_path)
    db = tmp_path / "state.sqlite3"
    with ProjectStateStore(db) as store:
        store.create_typed(Project(id="project-test", name="test"), actor="test", action="CreateProject", reason="test")
        from urban_design.models import Artifact

        artifact = Artifact(id="boundary", type="boundary", uri="boundary.geojson", sha256=proposal.boundary_sha256, mime="application/geo+json", crs="EPSG:28992", producer="test", created_at=NOW, project_id="project-test", size_bytes=1, parent_artifact_ids=["selection", "anchor"])
        store.create_typed(artifact, actor="test", action="RecordArtifact", reason="test")
        assert store.current("boundary").get("parent_artifact_ids") == ["selection", "anchor"]


def test_effective_site_conflict_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite3"
    with ProjectStateStore(db) as store:
        store.create_typed(Project(id="project-test", name="test", site_id="site-effective"), actor="test", action="CreateProject", reason="test")
        with pytest.raises(SiteProposalValidationError, match="effective site"):
            assert_no_effective_site_conflict(store, "project-test")


def test_approved_site_requires_human_approval_fields() -> None:
    with pytest.raises(ValueError, match="explicit approval event"):
        Site(id="site-approved", project_id="project-test", version="v1", boundary_artifact_id="boundary", boundary_sha256="sha256:" + "a" * 64, crs="EPSG:28992", units="m", status=SiteStatus.APPROVED)


def test_approved_site_requires_matching_approval_ledger_event(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite3"
    with ProjectStateStore(db) as store:
        store.create_typed(Project(id="project-test", name="test"), actor="test", action="CreateProject", reason="test")
        site = Site(id="site-approved", project_id="project-test", version="v1", boundary_artifact_id="boundary", boundary_sha256="sha256:" + "a" * 64, crs="EPSG:28992", units="m", status=SiteStatus.APPROVED, approval_actor="human", approval_timestamp=NOW, approval_reason="accept exact proposal", approval_event_id="approval-event-1")
        store.create_typed(site, actor="system", action="AdoptSite", reason="transition under human approval", event_id="adoption-event-1")
        with pytest.raises(SiteProposalValidationError, match="matching explicit"):
            assert_site_approval_authorized(store, site.id)
        store.append_ledger_event(target_id=site.id, project_id="project-test", actor="human", action="Approve", reason="accept exact proposal", event_id="approval-event-1")
        assert_site_approval_authorized(store, site.id) is None
