"""Tests for DesignBrief, SpatialZone, and constraint boundaries (CP4-4)."""

import pytest
from pydantic import ValidationError
from shapely.geometry import Polygon


def test_spatial_zone_rejects_self_intersecting_polygon():
    from urban_design.design_brief import SpatialZone, BriefValidationError

    # Bowtie polygon (self-intersecting)
    bowtie_coords = [(0, 0), (10, 10), (10, 0), (0, 10)]
    with pytest.raises(BriefValidationError, match="self-intersecting|invalid"):
        SpatialZone.from_coordinates(
            zone_id="zone-1",
            coordinates=bowtie_coords,
            program_demands=["commercial"],
            raw_notes="Commercial zone",
            author="designer",
        )


def test_spatial_zone_rejects_empty_or_zero_area_polygon():
    from urban_design.design_brief import SpatialZone, BriefValidationError

    collinear_coords = [(0, 0), (10, 0), (20, 0)]
    with pytest.raises(BriefValidationError, match="zero area|degenerate"):
        SpatialZone.from_coordinates(
            zone_id="zone-2",
            coordinates=collinear_coords,
            program_demands=["residential"],
            raw_notes="Zero area line",
            author="designer",
        )


def test_design_brief_requires_explicit_far_and_defaults_to_none():
    from urban_design.design_brief import SpatialBrief

    brief = SpatialBrief(
        brief_id="brief-001",
        project_id="rotterdam-m4h-pilot-project",
        study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
    )
    # Cannot have unapproved default numbers like 3.5 or 2.0!
    assert brief.whole_site_far_limit is None
    assert brief.status == "DRAFT"


def test_design_brief_cannot_be_marked_confirmed_without_human_decision(tmp_path):
    from urban_design.design_brief import BriefValidationError, BriefService, SpatialBrief
    from urban_design.store import ProjectStateStore

    with pytest.raises(ValidationError):
        SpatialBrief(
            brief_id="brief-unapproved-confirmation",
            project_id="rotterdam-m4h-pilot-project",
            study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
            whole_site_far_limit=1.5,
            status="CONFIRMED",
        )

    brief = SpatialBrief(
        brief_id="brief-unvalidated-confirmation",
        project_id="rotterdam-m4h-pilot-project",
        study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
    ).model_copy(update={"status": "CONFIRMED"})
    service = BriefService(ProjectStateStore(tmp_path / "brief.sqlite3"))
    from urban_design.models import ActorKind
    with pytest.raises(BriefValidationError, match="HumanDecision"):
        service.save_brief(
            brief,
            actor="brief-test",
            actor_kind=ActorKind.TEST_HARNESS,
            actor_session_id="brief-test-session",
        )
    assert service.get_brief(brief.brief_id) is None


def test_design_brief_detects_overlapping_zones():
    from urban_design.design_brief import SpatialBrief, SpatialZone, BriefValidationError

    # Two overlapping 100x100 squares
    zone_a = SpatialZone.from_coordinates(
        zone_id="zone-a",
        coordinates=[(0, 0), (100, 0), (100, 100), (0, 100)],
        program_demands=["commercial"],
        raw_notes="Zone A",
        author="designer",
    )
    zone_b = SpatialZone.from_coordinates(
        zone_id="zone-b",
        coordinates=[(50, 0), (150, 0), (150, 100), (50, 100)],  # overlaps by 50m
        program_demands=["residential"],
        raw_notes="Zone B",
        author="designer",
    )

    brief = SpatialBrief(
        brief_id="brief-002",
        project_id="rotterdam-m4h-pilot-project",
        study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
        zones=[zone_a, zone_b],
    )

    overlaps = brief.detect_zone_overlaps()
    assert len(overlaps) == 1
    assert ("zone-a", "zone-b") in overlaps or ("zone-b", "zone-a") in overlaps


def test_overlapping_zone_far_limits_need_an_explicit_allocation_rule():
    from urban_design.constraint_sets import validate_zone_allocation
    from urban_design.workspace_contracts import SpatialZone, WorkspaceSpatialBrief

    zone_a = SpatialZone(
        zone_id="zone-a",
        name="A",
        target_use="mixed",
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        original_text="fixture zone A",
    )
    zone_b = SpatialZone(
        zone_id="zone-b",
        name="B",
        target_use="mixed",
        geometry={"type": "Polygon", "coordinates": [[[5, 0], [15, 0], [15, 10], [5, 10], [5, 0]]]},
        original_text="fixture zone B",
    )
    brief = WorkspaceSpatialBrief(zones=[zone_a, zone_b])

    with pytest.raises(ValueError, match="allocation"):
        validate_zone_allocation(brief, allocation_policy=None)
    validate_zone_allocation(brief, allocation_policy="priority")


def test_design_brief_persistence_and_replay(tmp_path):
    from urban_design.store import ProjectStateStore
    from urban_design.design_brief import SpatialBrief, SpatialZone, BriefService
    from urban_design.models import ActorKind

    store = ProjectStateStore(tmp_path / "brief_test.sqlite3")
    service = BriefService(store)

    zone = SpatialZone.from_coordinates(
        zone_id="zone-north",
        coordinates=[(0, 0), (200, 0), (200, 100), (0, 100)],
        program_demands=["mixed_use", "open_space"],
        raw_notes="North waterfront area",
        author="designer",
    )

    brief = SpatialBrief(
        brief_id="brief-rotterdam-1",
        project_id="rotterdam-m4h-pilot-project",
        study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
        zones=[zone],
        status="DRAFT",
    )

    saved = service.save_brief(
        brief,
        actor="brief-test",
        actor_kind=ActorKind.TEST_HARNESS,
        actor_session_id="brief-test-session",
    )
    assert saved.revision == 1
    event = store.events()[-1]
    assert event.actor_kind is ActorKind.TEST_HARNESS
    assert event.actor_session_id == "brief-test-session"

    loaded = service.get_brief("brief-rotterdam-1")
    assert loaded is not None
    assert loaded.brief_id == "brief-rotterdam-1"
    assert len(loaded.zones) == 1
    assert loaded.zones[0].zone_id == "zone-north"
    assert loaded.status == "DRAFT"


def _a3_hash(payload):
    import hashlib
    import json

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _a3_store(tmp_path, *, workspace_revision=1, include_zone=False, include_analysis=True):
    from urban_design.site_intelligence.contracts import FrozenRef, Observation, SiteAnalysisBundle
    from urban_design.store import ProjectStateStore

    project_id = "a3-disposable-project"
    workspace_id = f"workspace-{project_id}"
    study_area_id = "a3-study-area"
    store = ProjectStateStore(tmp_path / "a3-disposable.sqlite3")
    store.create_project({"id": project_id, "project_id": project_id}, project_id=project_id)
    study_area_payload = {
        "id": study_area_id,
        "project_id": project_id,
        "status": "CONFIRMED_FOR_EXPLORATION",
        "geometry_artifact_id": "a3-study-area-geometry",
    }
    store.create("StudyArea", study_area_payload, entity_id=study_area_id, project_id=project_id)
    scope_geometry = {
        "type": "Polygon",
        "coordinates": [[[88000, 435000], [88100, 435000], [88100, 435100], [88000, 435100], [88000, 435000]]],
    }
    scope_payload = {
        "id": "a3-study-area-geometry",
        "type": "study_area_geometry",
        "uri": "fixture://a3-study-area-geometry.geojson",
        "sha256": _a3_hash(scope_geometry),
        "mime": "application/geo+json",
        "crs": "EPSG:28992",
        "producer": "synthetic-test-fixture",
        "created_at": "2026-09-30T10:00:00+00:00",
        "project_id": project_id,
        "size_bytes": 1,
        "parent_artifact_ids": [],
        "geometry": scope_geometry,
    }
    store.create("Artifact", scope_payload, entity_id=scope_payload["id"], project_id=project_id)
    spatial_brief = {
        "zones": [],
        "exploration_design_area": None,
        "status": "DRAFT_PENDING_HUMAN_DECISION",
    }
    zone_geometry = {
        "type": "Polygon",
        "coordinates": [[[88020, 435020], [88060, 435020], [88060, 435060], [88020, 435060], [88020, 435020]]],
    }
    if include_zone:
        spatial_brief["zones"].append({
            "zone_id": "zone-north",
            "name": "North local zone",
            "target_use": "mixed",
            "geometry": zone_geometry,
            "crs": "EPSG:28992",
            "area_m2": 1600,
            "author": "designer",
            "revision": 3,
            "original_text": "Synthetic saved local-zone fixture.",
            "notes": "Synthetic saved local-zone fixture.",
            "status": "DRAFT_PENDING_HUMAN_DECISION",
        })
    workspace_payload = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "revision": workspace_revision,
        "study_area_id": study_area_id,
        "source_snapshot_ids": [],
        "feature_dispositions": [],
        "spatial_brief": spatial_brief,
        "status": "DRAFT",
        "idempotency_key": f"workspace-seed-{workspace_revision}",
        "payload_digest": _a3_hash({"workspace_revision": workspace_revision}),
    }
    first_workspace_payload = {**workspace_payload, "revision": 1}
    store.create("WorkspaceRevision", first_workspace_payload, entity_id=workspace_id, project_id=project_id)
    for revision in range(2, workspace_revision + 1):
        workspace_payload["revision"] = revision
        store.update(
            workspace_id,
            workspace_payload,
            expected_revision=revision - 1,
            replace=True,
            reason=f"Synthetic workspace revision {revision}",
        )

    workspace_ref = FrozenRef(id=workspace_id, revision=workspace_revision, sha256=_a3_hash(workspace_payload))
    study_area_ref = FrozenRef(id=study_area_id, revision=1, sha256=_a3_hash(study_area_payload))
    provisional = SiteAnalysisBundle(
        bundle_ref=FrozenRef(id="provisional", revision=1, sha256="sha256:" + "0" * 64),
        study_area_ref=study_area_ref,
        workspace_ref=workspace_ref,
        observations=(
            Observation(
                metric_key="fixture.synthetic_count",
                status="AVAILABLE",
                value=0.0,
                unit="count",
                method_version="fixture-v1",
                scope_ref=study_area_ref,
                input_refs=(FrozenRef(id=scope_payload["id"], revision=1, sha256=scope_payload["sha256"]),),
            ),
        ),
        created_at="2026-09-30T10:00:00+00:00",
        tool_versions={"fixture": "a3-v1"},
    )
    from urban_design.site_intelligence.contracts import Opportunity, compute_site_analysis_bundle_ref

    bundle = provisional.model_copy(update={"bundle_ref": compute_site_analysis_bundle_ref(provisional)})
    bundle_payload = {
        "id": bundle.bundle_ref.id,
        "type": "site-analysis-bundle",
        "uri": f"fixture://{bundle.bundle_ref.id}.json",
        "sha256": bundle.bundle_ref.sha256,
        "mime": "application/json",
        "producer": "synthetic-test-fixture",
        "created_at": "2026-09-30T10:00:00+00:00",
        "project_id": project_id,
        "size_bytes": 1,
        "parent_artifact_ids": [scope_payload["id"]],
        "bundle": bundle.model_dump(mode="json"),
    }
    if include_analysis:
        store.create("Artifact", bundle_payload, entity_id=bundle_payload["id"], project_id=project_id)
    opportunity_ref = FrozenRef(
        id=scope_payload["id"],
        revision=1,
        sha256=scope_payload["sha256"],
    )
    opportunities = [
        Opportunity(
            id="opp-selected",
            origin="AI_SUGGESTED",
            statement="Explore a more connected local route.",
            kind="CONDITIONAL_HYPOTHESIS",
            evidence_refs=(),
            scope_ref=opportunity_ref,
            uncertainties=("Route continuity needs review.",),
        ),
        Opportunity(
            id="opp-rejected",
            origin="RULE_SUGGESTED",
            statement="Consider adding a small plaza.",
            kind="DESIGN_PREFERENCE",
            scope_ref=opportunity_ref,
        ),
    ]
    opportunity_content = {
        "analysis_ref": bundle.bundle_ref.model_dump(mode="json"),
        "opportunities": [item.model_dump(mode="json") for item in opportunities],
    }
    opportunity_payload = {
        "id": "a3-opportunity-set",
        "type": "site-opportunity-set",
        "uri": "fixture://a3-opportunities.json",
        "sha256": _a3_hash(opportunity_content),
        "mime": "application/json",
        "producer": "synthetic-test-fixture",
        "created_at": "2026-09-30T10:00:00+00:00",
        "project_id": project_id,
        "size_bytes": 1,
        "parent_artifact_ids": [bundle.bundle_ref.id],
        "analysis_ref": bundle.bundle_ref.model_dump(mode="json"),
        "opportunities": opportunity_content["opportunities"],
    }
    if include_analysis:
        store.create("Artifact", opportunity_payload, entity_id=opportunity_payload["id"], project_id=project_id)
    return (
        store,
        project_id,
        workspace_payload,
        workspace_ref,
        scope_payload,
        bundle,
        bundle_payload,
        opportunity_payload,
        opportunities,
    )


def _a3_brief_request(*, project_id, workspace_ref, scope_payload, bundle, opportunity_payload):
    from urban_design.site_intelligence.contracts import DesignIntent, FrozenRef

    scope_ref = FrozenRef(
        id=scope_payload["id"],
        revision=1,
        sha256=scope_payload["sha256"],
    )
    return {
        "brief_id": "brief-a3-disposable",
        "expected_workspace_revision": workspace_ref.revision,
        "input_hashes": {
            workspace_ref.id: workspace_ref.sha256,
            bundle.bundle_ref.id: bundle.bundle_ref.sha256,
            scope_ref.id: scope_ref.sha256,
            opportunity_payload["id"]: opportunity_payload["sha256"],
        },
        "idempotency_key": "brief-a3-create-001",
        "actor_session_id": "a3-panel-session",
        "change_reason": "Create a designer-owned draft for review.",
        "intents": [
            DesignIntent(
                id="intent-designer-authored",
                text="Keep a clear walking route through this local area.",
                scope_ref=scope_ref,
                kind="PREFERENCE",
                origin="DESIGNER_AUTHORED",
                version=1,
            ).model_dump(mode="json"),
            DesignIntent(
                id="intent-ai-edited",
                text="Explore another local connection, then check continuity.",
                scope_ref=scope_ref,
                kind="PREFERENCE",
                source_opportunity_ids=("opp-selected",),
                origin="AI_SUGGESTED",
                version=2,
            ).model_dump(mode="json"),
        ],
        "selected_opportunity_ids": ["opp-selected"],
        "rejected_opportunities": [
            {"opportunity_id": "opp-rejected", "reason": "Keep the existing quay edge unobstructed."}
        ],
    }


def test_site_intelligence_reads_persisted_bundle_without_mutating_store(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app

    store, project_id, _, _, _, bundle, *_ = _a3_store(tmp_path)
    event_count = len(store.events(project_id=project_id))
    client = TestClient(create_workspace_app(store=store))

    response = client.get(f"/api/v1/projects/{project_id}/site-intelligence")

    assert response.status_code == 200, response.text
    assert response.json()["analysis_status"] == "AVAILABLE"
    assert response.json()["latest_bundle_ref"] == bundle.bundle_ref.model_dump(mode="json")
    assert response.json()["bundle_persisted"] is True
    assert len(store.events(project_id=project_id)) == event_count


def test_not_run_snapshot_allows_self_authored_draft_without_fabricating_analysis(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app

    from_store = _a3_store(tmp_path, include_analysis=False)
    store, project_id, _, workspace_ref, _, _, _, _, _ = from_store
    client = TestClient(create_workspace_app(store=store))
    before_artifacts = len(store.list_current("Artifact", project_id=project_id))
    before_events = len(store.events(project_id=project_id))

    snapshot = client.get(f"/api/v1/projects/{project_id}/site-intelligence")

    assert snapshot.status_code == 200, snapshot.text
    projection = snapshot.json()
    assert projection["analysis_status"] == "NOT_RUN"
    assert projection["bundle_persisted"] is False
    assert projection["latest_bundle_ref"] is not None
    assert len(store.list_current("Artifact", project_id=project_id)) == before_artifacts
    assert len(store.events(project_id=project_id)) == before_events
    scope_ref = projection["default_scope_ref"]
    body = {
        "brief_id": "brief-authored-when-analysis-not-run",
        "expected_workspace_revision": workspace_ref.revision,
        "input_hashes": {
            **projection["input_hashes"],
            scope_ref["id"]: scope_ref["sha256"],
        },
        "idempotency_key": "brief-authored-no-run-001",
        "actor_session_id": "a3-panel-session",
        "intents": [
            {
                "id": "intent-authored-without-analysis",
                "text": "Keep a safe walking route through this area.",
                "scope_ref": scope_ref,
                "kind": "PREFERENCE",
                "origin": "DESIGNER_AUTHORED",
                "version": 1,
            }
        ],
    }

    saved = client.post(f"/api/v1/projects/{project_id}/design-briefs", json=body)

    assert saved.status_code == 201, saved.text
    assert saved.json()["status"] == "DRAFT"
    assert len(store.list_current("Artifact", project_id=project_id)) == before_artifacts + 2
    assert len(store.events(project_id=project_id)) == before_events + 2
    bundle_record = store.current(projection["latest_bundle_ref"]["id"])
    assert bundle_record.payload["type"] == "site-analysis-bundle"
    assert bundle_record.payload["status"] == "NOT_RUN"
    assert bundle_record.payload["bundle"]["observations"] == []
    assert len(store.list_current("HumanDecision", project_id=project_id)) == 0


def test_reusing_saved_workspace_zone_does_not_duplicate_materialized_scope(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app
    from urban_design.site_intelligence.contracts import FrozenRef

    store, project_id, _, workspace_ref, _, bundle, _, opportunity_set, _ = _a3_store(
        tmp_path, include_zone=True
    )
    client = TestClient(create_workspace_app(store=store))
    snapshot = client.get(f"/api/v1/projects/{project_id}/site-intelligence").json()
    zone_ref = FrozenRef.model_validate(
        next(item["ref"] for item in snapshot["scope_refs"] if item["scope_id"] == "zone:zone-north:r3")
    )
    body = _a3_brief_request(
        project_id=project_id,
        workspace_ref=workspace_ref,
        scope_payload={"id": zone_ref.id, "sha256": zone_ref.sha256},
        bundle=bundle,
        opportunity_payload=opportunity_set,
    )
    body["intents"] = [{**body["intents"][0], "scope_ref": zone_ref.model_dump(mode="json")}]
    body["selected_opportunity_ids"] = []
    body["rejected_opportunities"] = []
    body["input_hashes"] = {
        workspace_ref.id: workspace_ref.sha256,
        bundle.bundle_ref.id: bundle.bundle_ref.sha256,
        opportunity_set["id"]: opportunity_set["sha256"],
        zone_ref.id: zone_ref.sha256,
    }

    first = client.post(f"/api/v1/projects/{project_id}/design-briefs", json=body)
    assert first.status_code == 201, first.text
    before_artifacts = len(store.list_current("Artifact", project_id=project_id))
    before_events = len(store.events(project_id=project_id))
    second_body = {
        **body,
        "brief_id": "brief-a3-other-draft",
        "idempotency_key": "brief-a3-zone-reuse-002",
    }

    second = client.post(f"/api/v1/projects/{project_id}/design-briefs", json=second_body)

    assert second.status_code == 201, second.text
    assert len(store.list_current("Artifact", project_id=project_id)) == before_artifacts + 1
    assert len(store.events(project_id=project_id)) == before_events + 1


def test_analysis_jobs_is_explicitly_deferred_to_u1_contract(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app

    store, project_id, *_ = _a3_store(tmp_path)
    response = TestClient(create_workspace_app(store=store)).post(
        f"/api/v1/projects/{project_id}/analysis-jobs",
        json={"expected_workspace_revision": 1},
    )

    assert response.status_code == 501
    assert "U1" in response.json()["detail"]


def test_stale_brief_submission_has_no_artifact_or_ledger_write(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app

    store, project_id, _, workspace_ref, scope_payload, bundle, *_ = _a3_store(tmp_path, workspace_revision=2)
    before_artifacts = len(store.list_current("Artifact", project_id=project_id))
    before_events = len(store.events(project_id=project_id))
    body = {
        "brief_id": "brief-stale-a3",
        "expected_workspace_revision": 1,
        "input_hashes": {
            workspace_ref.id: workspace_ref.sha256,
            bundle.bundle_ref.id: bundle.bundle_ref.sha256,
            scope_payload["id"]: scope_payload["sha256"],
        },
        "idempotency_key": "brief-stale-key",
        "actor_session_id": "a3-panel-session",
        "intents": [],
    }

    response = TestClient(create_workspace_app(store=store)).post(
        f"/api/v1/projects/{project_id}/design-briefs", json=body
    )

    assert response.status_code == 409, response.text
    assert len(store.list_current("Artifact", project_id=project_id)) == before_artifacts
    assert len(store.events(project_id=project_id)) == before_events


def test_brief_save_is_an_immutable_draft_artifact_and_idempotent(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app

    store, project_id, _, workspace_ref, scope, bundle, _, opportunity_set, _ = _a3_store(tmp_path)
    client = TestClient(create_workspace_app(store=store))
    body = _a3_brief_request(
        project_id=project_id,
        workspace_ref=workspace_ref,
        scope_payload=scope,
        bundle=bundle,
        opportunity_payload=opportunity_set,
    )
    before_decisions = len(store.list_current("HumanDecision", project_id=project_id))

    response = client.post(f"/api/v1/projects/{project_id}/design-briefs", json=body)

    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["status"] == "DRAFT"
    assert saved["brief"]["revision"] == 1
    assert saved["brief"]["selected_opportunity_ids"] == ["opp-selected"]
    assert saved["rejected_opportunities"] == body["rejected_opportunities"]
    assert len(store.list_current("HumanDecision", project_id=project_id)) == before_decisions
    events = store.events(project_id=project_id, target_id=saved["artifact_ref"]["id"])
    assert len(events) == 1
    assert events[0].action == "CreateDesignBriefDraft"

    replay = client.post(f"/api/v1/projects/{project_id}/design-briefs", json=body)
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["artifact_ref"] == saved["artifact_ref"]
    assert len(store.events(project_id=project_id, target_id=saved["artifact_ref"]["id"])) == 1

    loaded = client.get(
        f"/api/v1/projects/{project_id}/design-briefs/{saved['brief']['id']}/revisions/1"
    )
    assert loaded.status_code == 200
    assert loaded.json()["brief"] == saved["brief"]


def test_brief_rejects_client_approval_and_unverified_input_hashes(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app

    store, project_id, _, workspace_ref, scope, bundle, _, opportunity_set, _ = _a3_store(tmp_path)
    client = TestClient(create_workspace_app(store=store))
    body = _a3_brief_request(
        project_id=project_id,
        workspace_ref=workspace_ref,
        scope_payload=scope,
        bundle=bundle,
        opportunity_payload=opportunity_set,
    )
    before_events = len(store.events(project_id=project_id))

    approved = client.post(
        f"/api/v1/projects/{project_id}/design-briefs", json={**body, "approved": True}
    )
    assert approved.status_code == 422

    wrong_hashes = dict(body["input_hashes"])
    wrong_hashes[bundle.bundle_ref.id] = "sha256:" + "f" * 64
    invalid = client.post(
        f"/api/v1/projects/{project_id}/design-briefs",
        json={**body, "idempotency_key": "brief-a3-create-002", "input_hashes": wrong_hashes},
    )
    assert invalid.status_code == 422
    assert len(store.events(project_id=project_id)) == before_events


def test_brief_revision_preserves_parent_and_reloadable_previous_version(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app

    store, project_id, _, workspace_ref, scope, bundle, _, opportunity_set, _ = _a3_store(tmp_path)
    client = TestClient(create_workspace_app(store=store))
    body = _a3_brief_request(
        project_id=project_id,
        workspace_ref=workspace_ref,
        scope_payload=scope,
        bundle=bundle,
        opportunity_payload=opportunity_set,
    )
    first = client.post(f"/api/v1/projects/{project_id}/design-briefs", json=body)
    assert first.status_code == 201, first.text
    first_payload = first.json()

    revised_body = {
        **body,
        "idempotency_key": "brief-a3-revision-002",
        "parent_ref": first_payload["artifact_ref"],
        "change_reason": "The designer narrowed the route preference.",
        "intents": [
            {
                **body["intents"][0],
                "text": "Keep a clear walking route through the northern part of this area.",
                "version": 2,
            }
        ],
        "selected_opportunity_ids": [],
        "rejected_opportunities": [],
    }
    second = client.post(f"/api/v1/projects/{project_id}/design-briefs", json=revised_body)
    assert second.status_code == 201, second.text
    assert second.json()["brief"]["revision"] == 2
    assert second.json()["brief"]["parent_ref"] == first_payload["artifact_ref"]

    original = client.get(
        f"/api/v1/projects/{project_id}/design-briefs/{first_payload['brief']['id']}/revisions/1"
    )
    assert original.status_code == 200
    assert original.json()["brief"] == first_payload["brief"]


def test_saved_workspace_zone_becomes_a_hash_bound_scope_artifact_atomically(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app
    from urban_design.site_intelligence.contracts import FrozenRef

    store, project_id, _, workspace_ref, _, bundle, _, opportunity_set, _ = _a3_store(
        tmp_path, include_zone=True
    )
    client = TestClient(create_workspace_app(store=store))
    site_intelligence = client.get(f"/api/v1/projects/{project_id}/site-intelligence")
    assert site_intelligence.status_code == 200, site_intelligence.text
    zone_option = next(
        item for item in site_intelligence.json()["scope_refs"] if item["scope_id"] == "zone:zone-north:r3"
    )
    zone_ref = FrozenRef.model_validate(zone_option["ref"])
    body = _a3_brief_request(
        project_id=project_id,
        workspace_ref=workspace_ref,
        scope_payload={"id": zone_ref.id, "sha256": zone_ref.sha256},
        bundle=bundle,
        opportunity_payload=opportunity_set,
    )
    body["intents"] = [
        {
            **body["intents"][0],
            "scope_ref": zone_ref.model_dump(mode="json"),
        }
    ]
    body["selected_opportunity_ids"] = []
    body["rejected_opportunities"] = []
    body["input_hashes"] = {
        workspace_ref.id: workspace_ref.sha256,
        bundle.bundle_ref.id: bundle.bundle_ref.sha256,
        opportunity_set["id"]: opportunity_set["sha256"],
        zone_ref.id: zone_ref.sha256,
    }
    before_events = len(store.events(project_id=project_id))

    saved = client.post(f"/api/v1/projects/{project_id}/design-briefs", json=body)

    assert saved.status_code == 201, saved.text
    scope_artifact = store.current(zone_ref.id)
    assert scope_artifact.entity_type == "Artifact"
    assert scope_artifact.payload["geometry"] == _a3_store_zone_geometry()
    assert scope_artifact.payload["sha256"] == zone_ref.sha256
    new_events = store.events(project_id=project_id)[before_events:]
    assert [event.action for event in new_events] == [
        "MaterializeWorkspaceScopeArtifact",
        "CreateDesignBriefDraft",
    ]
    assert len(store.list_current("HumanDecision", project_id=project_id)) == 0


def _a3_store_zone_geometry():
    return {
        "type": "Polygon",
        "coordinates": [[[88020, 435020], [88060, 435020], [88060, 435060], [88020, 435060], [88020, 435020]]],
    }


def test_brief_rejects_a_scope_artifact_outside_saved_study_area_without_writes(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app

    store, project_id, _, workspace_ref, scope, bundle, _, opportunity_set, _ = _a3_store(tmp_path)
    outside_geometry = {
        "type": "Polygon",
        "coordinates": [[[90000, 440000], [90010, 440000], [90010, 440010], [90000, 440010], [90000, 440000]]],
    }
    outside_payload = {
        "id": "scope-outside-study-area",
        "type": "local_scope",
        "uri": "fixture://outside.geojson",
        "sha256": _a3_hash(outside_geometry),
        "mime": "application/geo+json",
        "crs": "EPSG:28992",
        "producer": "synthetic-test-fixture",
        "created_at": "2026-09-30T10:00:00+00:00",
        "project_id": project_id,
        "size_bytes": 1,
        "parent_artifact_ids": [],
        "geometry": outside_geometry,
    }
    store.create("Artifact", outside_payload, entity_id=outside_payload["id"], project_id=project_id)
    body = _a3_brief_request(
        project_id=project_id,
        workspace_ref=workspace_ref,
        scope_payload=scope,
        bundle=bundle,
        opportunity_payload=opportunity_set,
    )
    body["intents"] = [
        {
            **body["intents"][0],
            "scope_ref": {
                "id": outside_payload["id"],
                "revision": 1,
                "sha256": outside_payload["sha256"],
            },
        }
    ]
    body["selected_opportunity_ids"] = []
    body["rejected_opportunities"] = []
    body["input_hashes"] = {
        workspace_ref.id: workspace_ref.sha256,
        bundle.bundle_ref.id: bundle.bundle_ref.sha256,
        opportunity_set["id"]: opportunity_set["sha256"],
        outside_payload["id"]: outside_payload["sha256"],
    }
    before_artifacts = len(store.list_current("Artifact", project_id=project_id))
    before_events = len(store.events(project_id=project_id))

    response = TestClient(create_workspace_app(store=store)).post(
        f"/api/v1/projects/{project_id}/design-briefs", json=body
    )

    assert response.status_code == 422
    assert "outside" in response.json()["detail"]
    assert len(store.list_current("Artifact", project_id=project_id)) == before_artifacts
    assert len(store.events(project_id=project_id)) == before_events


def test_latest_design_brief_endpoint_and_site_intelligence_projection(tmp_path):
    from fastapi.testclient import TestClient
    from urban_design.api import create_workspace_app

    store, project_id, _, workspace_ref, scope, bundle, _, opportunity_set, _ = _a3_store(tmp_path)
    client = TestClient(create_workspace_app(store=store))

    # Before saving any brief, latest endpoint returns 404 and site-intelligence has latest_brief=None
    not_found = client.get(f"/api/v1/projects/{project_id}/design-briefs/latest")
    assert not_found.status_code == 404
    intel_before = client.get(f"/api/v1/projects/{project_id}/site-intelligence").json()
    assert intel_before["latest_brief"] is None

    body = _a3_brief_request(
        project_id=project_id,
        workspace_ref=workspace_ref,
        scope_payload=scope,
        bundle=bundle,
        opportunity_payload=opportunity_set,
    )
    saved = client.post(f"/api/v1/projects/{project_id}/design-briefs", json=body)
    assert saved.status_code == 201
    saved_payload = saved.json()

    revised_body = {
        **body,
        "idempotency_key": "brief-latest-revision-002",
        "parent_ref": saved_payload["artifact_ref"],
        "change_reason": "The designer refined the draft intent.",
    }
    revised = client.post(f"/api/v1/projects/{project_id}/design-briefs", json=revised_body)
    assert revised.status_code == 201, revised.text
    assert revised.json()["brief"]["revision"] == 2

    before_get_artifacts = len(store.list_current("Artifact", project_id=project_id))
    before_get_events = len(store.events(project_id=project_id))

    latest = client.get(f"/api/v1/projects/{project_id}/design-briefs/latest")
    assert latest.status_code == 200
    assert latest.json()["brief"]["id"] == revised_body["brief_id"]
    assert latest.json()["brief"]["revision"] == 2

    intel_after = client.get(f"/api/v1/projects/{project_id}/site-intelligence").json()
    assert intel_after["latest_brief"] is not None
    assert intel_after["latest_brief"]["brief"]["id"] == revised_body["brief_id"]
    assert intel_after["latest_brief"]["brief"]["revision"] == 2
    assert len(store.list_current("Artifact", project_id=project_id)) == before_get_artifacts
    assert len(store.events(project_id=project_id)) == before_get_events
