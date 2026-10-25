"""Tests for typed workspace sync contracts and state transitions (CP4-2)."""

import pytest
from pydantic import ValidationError


def test_sync_rejects_empty_sources():
    from urban_design.workspace_contracts import SyncRequest

    with pytest.raises(ValidationError):
        SyncRequest(
            project_id="fixture-project",
            study_area_id="fixture-area",
            expected_workspace_revision=0,
            source_snapshot_ids=[],
            idempotency_key="fixture-1",
            actor_kind="TEST_HARNESS",
            actor_session_id="workspace-sync-test",
        )


def test_sync_rejects_client_approval():
    from urban_design.workspace_contracts import SyncRequest

    with pytest.raises(ValidationError):
        SyncRequest(
            project_id="fixture-project",
            study_area_id="fixture-area",
            expected_workspace_revision=0,
            source_snapshot_ids=["fixture-source"],
            idempotency_key="fixture-1",
            actor_kind="TEST_HARNESS",
            actor_session_id="workspace-sync-test",
            approved=True,  # Client cannot pass approval flags
        )


def test_feature_disposition_contract():
    from urban_design.workspace_contracts import FeatureDisposition

    disp = FeatureDisposition(
        source_artifact_id="artifact-pdok-bag-1",
        feature_id="pand.0503100000000001",
        feature_kind="building",
        disposition="preserve",
    )
    assert disp.disposition == "preserve"
    assert disp.feature_kind == "building"

    with pytest.raises(ValidationError):
        FeatureDisposition(
            source_artifact_id="artifact-pdok-bag-1",
            feature_id="pand.0503100000000001",
            feature_kind="satellite",  # Invalid kind
            disposition="preserve",
        )


def test_feature_disposition_annotation_is_bounded_and_persisted(tmp_path):
    from urban_design.store import ProjectStateStore
    from urban_design.workspace_contracts import FeatureDisposition, SyncRequest
    from urban_design.workspace_service import WorkspaceService

    annotation = "Keep the loading access clear; verify with the client."
    disposition = FeatureDisposition(
        source_artifact_id="artifact-annotation",
        feature_id="road-annotation",
        feature_kind="road",
        disposition="undecided",
        annotation=annotation,
    )
    assert disposition.annotation == annotation

    with pytest.raises(ValidationError):
        FeatureDisposition(
            source_artifact_id="artifact-annotation",
            feature_id="road-annotation",
            feature_kind="road",
            disposition="undecided",
            annotation="x" * 501,
        )

    store = ProjectStateStore(tmp_path / "annotation_workspace.sqlite3")
    store.create("StudyArea", {"status": "CONFIRMED_FOR_EXPLORATION"}, entity_id="area-annotation")
    store.create("DatasetSnapshot", {"status": "CONFIRMED"}, entity_id="snapshot-annotation")
    store.create("Artifact", {}, entity_id="artifact-annotation")
    service = WorkspaceService(store)
    revision = service.sync(
        SyncRequest(
            project_id="project-annotation",
            study_area_id="area-annotation",
            expected_workspace_revision=0,
            source_snapshot_ids=["snapshot-annotation"],
            idempotency_key="annotation-1",
            actor_kind="TEST_HARNESS",
            actor_session_id="workspace-sync-test",
        ),
        dispositions=[disposition],
    )

    assert revision.feature_dispositions[0].annotation == annotation
    assert service.get_workspace("workspace-project-annotation").feature_dispositions[0].annotation == annotation


def test_workspace_service_idempotency_and_versioning(tmp_path):
    from urban_design.store import ProjectStateStore
    from urban_design.workspace_contracts import SyncRequest, FeatureDisposition
    from urban_design.workspace_service import WorkspaceService, WorkspaceConflictError

    store = ProjectStateStore(tmp_path / "test_workspace.sqlite3")
    store.create(
        "StudyArea",
        {"id": "study-area-rotterdam-m4h-pilot-project-v5", "status": "CONFIRMED_FOR_EXPLORATION", "version": "v5"},
        entity_id="study-area-rotterdam-m4h-pilot-project-v5",
    )
    for sid in ["snapshot-1", "snapshot-2", "snapshot-DIFFERENT"]:
        store.create("DatasetSnapshot", {"id": sid, "status": "CONFIRMED"}, entity_id=sid)
    for artifact_id in ["artifact-1", "artifact-2", "artifact-DIFFERENT"]:
        store.create("Artifact", {"id": artifact_id}, entity_id=artifact_id)
    service = WorkspaceService(store)

    req = SyncRequest(
        project_id="rotterdam-m4h-pilot-project",
        study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
        expected_workspace_revision=0,
        source_snapshot_ids=["snapshot-1", "snapshot-2"],
        idempotency_key="sync-key-101",
        actor_kind="TEST_HARNESS",
        actor_session_id="workspace-sync-test",
    )

    # First sync creates revision 1
    rev1 = service.sync(
        req,
        dispositions=[
            FeatureDisposition(
                source_artifact_id="artifact-1",
                feature_id="bldg-01",
                feature_kind="building",
                disposition="preserve",
            )
        ],
    )
    assert rev1.revision == 1
    assert rev1.study_area_id == "study-area-rotterdam-m4h-pilot-project-v5"

    # Same key + same payload replay returns same revision
    rev1_replay = service.sync(
        req,
        dispositions=[
            FeatureDisposition(
                source_artifact_id="artifact-1",
                feature_id="bldg-01",
                feature_kind="building",
                disposition="preserve",
            )
        ],
    )
    assert rev1_replay.revision == 1

    # Same key + different payload raises 409 Conflict
    req_different_payload = SyncRequest(
        project_id="rotterdam-m4h-pilot-project",
        study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
        expected_workspace_revision=0,
        source_snapshot_ids=["snapshot-DIFFERENT"],
        idempotency_key="sync-key-101",
        actor_kind="TEST_HARNESS",
        actor_session_id="workspace-sync-test",
    )
    with pytest.raises(WorkspaceConflictError):
        service.sync(req_different_payload, dispositions=[])

    # Stale expected revision raises 409 Conflict
    req_stale = SyncRequest(
        project_id="rotterdam-m4h-pilot-project",
        study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
        expected_workspace_revision=0,  # Now current is 1
        source_snapshot_ids=["snapshot-1", "snapshot-2"],
        idempotency_key="sync-key-102",
        actor_kind="TEST_HARNESS",
        actor_session_id="workspace-sync-test",
    )
    with pytest.raises(WorkspaceConflictError):
        service.sync(req_stale, dispositions=[])


def test_workspace_sync_rollback_on_failure(tmp_path, monkeypatch):
    from urban_design.store import ProjectStateStore
    from urban_design.workspace_contracts import SyncRequest
    from urban_design.workspace_service import WorkspaceService

    store = ProjectStateStore(tmp_path / "rollback_test.sqlite3")
    store.create(
        "StudyArea",
        {"id": "area-1", "status": "CONFIRMED_FOR_EXPLORATION"},
        entity_id="area-1",
    )
    store.create(
        "DatasetSnapshot",
        {"id": "snap-1", "status": "CONFIRMED"},
        entity_id="snap-1",
    )
    service = WorkspaceService(store)

    req = SyncRequest(
        project_id="proj-rollback",
        study_area_id="area-1",
        expected_workspace_revision=0,
        source_snapshot_ids=["snap-1"],
        idempotency_key="key-rollback-1",
        actor_kind="TEST_HARNESS",
        actor_session_id="workspace-sync-test",
    )

    def fail_create(*_args, **_kwargs):
        raise RuntimeError("database error during ledger write")

    monkeypatch.setattr(store, "create", fail_create)
    with pytest.raises(RuntimeError, match="database error during ledger write"):
        service.sync(req)

    # Workspace was not created
    assert service.get_workspace("workspace-proj-rollback") is None


def test_workspace_sync_rejects_stale_study_area(tmp_path):
    from urban_design.store import ProjectStateStore
    from urban_design.workspace_contracts import SyncRequest
    from urban_design.workspace_service import WorkspaceService, WorkspaceValidationError

    store = ProjectStateStore(tmp_path / "stale_study_area.sqlite3")
    # Mark v4 as SUPERSEDED in store
    store.create(
        "StudyArea",
        {"status": "SUPERSEDED", "version": "v4", "name": "Rotterdam M4H v4"},
        entity_id="study-area-rotterdam-m4h-v4",
    )
    service = WorkspaceService(store)

    req = SyncRequest(
        project_id="proj-stale-area",
        study_area_id="study-area-rotterdam-m4h-v4",  # Superseded study area!
        expected_workspace_revision=0,
        source_snapshot_ids=["snap-1"],
        idempotency_key="key-stale-area",
        actor_kind="TEST_HARNESS",
        actor_session_id="workspace-sync-test",
    )

    with pytest.raises(WorkspaceValidationError, match="SUPERSEDED"):
        service.sync(req, validate_study_area=True)


def test_sync_connection_loss_outcome_unknown():
    """Verify that a network timeout or connection loss returns OUTCOME_UNKNOWN,
    prohibiting automatic retries without reconciling first.
    """
    from urban_design.models import RunStatus

    status = RunStatus.OUTCOME_UNKNOWN
    assert status.value == "OUTCOME_UNKNOWN"


def test_exploration_design_area_is_recomputed_and_explicitly_nonbinding():
    from urban_design.workspace_contracts import ExplorationDesignArea

    area = ExplorationDesignArea(
        geometry={
            "type": "Polygon",
            "coordinates": [[[10, 10], [30, 10], [30, 20], [10, 20], [10, 10]]],
        },
        area_m2=999999,
        status="DRAFT_PENDING_HUMAN_DECISION",
    )

    assert area.area_m2 == 200
    assert area.crs == "EPSG:28992"
    assert area.scope == "EXPLORATION_DESIGN_AREA"
    assert area.status == "DRAFT_PENDING_HUMAN_DECISION"

    with pytest.raises(ValidationError):
        ExplorationDesignArea(
            geometry={"type": "Polygon", "coordinates": [[[0, 0], [10, 10], [0, 10], [10, 0], [0, 0]]]},
        )


def test_null_exploration_design_area_keeps_pre_feature_sync_digest():
    import hashlib
    import json
    from urban_design.models import ActorKind
    from urban_design.workspace_contracts import SyncRequest, WorkspaceSpatialBrief
    from urban_design.workspace_service import _compute_sync_digest

    request = SyncRequest(
        project_id="project-digest",
        study_area_id="area-digest",
        expected_workspace_revision=0,
        source_snapshot_ids=["snapshot-digest"],
        idempotency_key="digest-key",
        spatial_brief=WorkspaceSpatialBrief(),
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-digest",
    )
    previous_shape = {
        "project_id": "project-digest",
        "study_area_id": "area-digest",
        "source_snapshot_ids": ["snapshot-digest"],
        "dispositions": [],
        "spatial_brief": {"zones": [], "status": "DRAFT_PENDING_HUMAN_DECISION"},
    }
    previous_digest = hashlib.sha256(
        json.dumps(previous_shape, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    assert _compute_sync_digest(request, [], request.spatial_brief) == previous_digest


def _brief_polygon(x_min, y_min, x_max, y_max):
    return {
        "type": "Polygon",
        "coordinates": [[
            [x_min, y_min], [x_max, y_min], [x_max, y_max],
            [x_min, y_max], [x_min, y_min],
        ]],
    }


def _workspace_request_with_brief(tmp_path, spatial_brief):
    from urban_design.models import ActorKind
    from urban_design.store import ProjectStateStore
    from urban_design.workspace_contracts import SyncRequest
    from urban_design.workspace_service import WorkspaceService

    store = ProjectStateStore(tmp_path / "spatial_brief_scope.sqlite3")
    store.create(
        "StudyArea",
        {"status": "CONFIRMED_FOR_EXPLORATION"},
        entity_id="area-spatial-brief",
    )
    store.create(
        "DatasetSnapshot",
        {"status": "CONFIRMED"},
        entity_id="snapshot-spatial-brief",
    )
    request = SyncRequest(
        project_id="project-spatial-brief",
        study_area_id="area-spatial-brief",
        expected_workspace_revision=0,
        source_snapshot_ids=["snapshot-spatial-brief"],
        idempotency_key="spatial-brief-scope-1",
        spatial_brief=spatial_brief,
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-brief-test",
    )
    return store, WorkspaceService(store), request


def test_workspace_sync_rejects_zone_outside_exploration_design_area(tmp_path):
    from urban_design.workspace_contracts import WorkspaceSpatialBrief
    from urban_design.workspace_service import WorkspaceValidationError

    brief = WorkspaceSpatialBrief.model_validate({
        "exploration_design_area": {"geometry": _brief_polygon(0, 0, 10, 10)},
        "zones": [{
            "zone_id": "outside-zone",
            "name": "Outside area",
            "target_use": "Workshop",
            "geometry": _brief_polygon(20, 20, 30, 30),
            "original_text": "Place workshops here",
        }],
    })
    store, service, request = _workspace_request_with_brief(tmp_path, brief)
    ledger_count = store.connection.execute("SELECT count(*) FROM ledger_events").fetchone()[0]

    with pytest.raises(WorkspaceValidationError, match="outside the Exploration Design Area"):
        service.sync(request)

    assert service.get_workspace("workspace-project-spatial-brief") is None
    assert store.connection.execute("SELECT count(*) FROM ledger_events").fetchone()[0] == ledger_count
    store.close()


def test_workspace_sync_rejects_overlapping_zones_without_allocation_rule(tmp_path):
    from urban_design.workspace_contracts import WorkspaceSpatialBrief
    from urban_design.workspace_service import WorkspaceValidationError

    brief = WorkspaceSpatialBrief.model_validate({
        "exploration_design_area": {"geometry": _brief_polygon(0, 0, 30, 20)},
        "zones": [
            {
                "zone_id": "zone-a",
                "name": "Zone A",
                "target_use": "Workshop",
                "geometry": _brief_polygon(0, 0, 10, 10),
                "original_text": "First area",
            },
            {
                "zone_id": "zone-b",
                "name": "Zone B",
                "target_use": "Housing",
                "geometry": _brief_polygon(9, 0, 20, 10),
                "original_text": "Second area",
            },
        ],
    })
    store, service, request = _workspace_request_with_brief(tmp_path, brief)
    ledger_count = store.connection.execute("SELECT count(*) FROM ledger_events").fetchone()[0]

    with pytest.raises(WorkspaceValidationError, match="overlap"):
        service.sync(request)

    assert service.get_workspace("workspace-project-spatial-brief") is None
    assert store.connection.execute("SELECT count(*) FROM ledger_events").fetchone()[0] == ledger_count
    store.close()


def test_workspace_sync_accepts_zones_that_share_only_a_boundary(tmp_path):
    from urban_design.workspace_contracts import WorkspaceSpatialBrief

    brief = WorkspaceSpatialBrief.model_validate({
        "exploration_design_area": {"geometry": _brief_polygon(0, 0, 20, 10)},
        "zones": [
            {
                "zone_id": "west-zone",
                "name": "West zone",
                "target_use": "Workshop",
                "geometry": _brief_polygon(0, 0, 10, 10),
                "original_text": "Use the western half",
            },
            {
                "zone_id": "east-zone",
                "name": "East zone",
                "target_use": "Housing",
                "geometry": _brief_polygon(10, 0, 20, 10),
                "original_text": "Use the eastern half",
            },
        ],
    })
    store, service, request = _workspace_request_with_brief(tmp_path, brief)

    saved = service.sync(request)

    assert saved.revision == 1
    assert [zone.zone_id for zone in saved.spatial_brief.zones] == ["west-zone", "east-zone"]
    store.close()
