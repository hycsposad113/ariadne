"""Release-blocking M2-A01 Study Area workflow contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from pydantic import ValidationError

from urban_design.models import (
    ActorKind,
    Artifact,
    DecisionAction,
    DesignBoundary,
    DesignBoundaryStatus,
    ExplorationStage,
    FormalClaimType,
    HumanDecision,
    HumanStatus,
    Project,
    StudyArea,
    StudyAreaStatus,
)
from urban_design.store import ProjectStateStore
from urban_design.study_area_workflow import (
    authorize_exploration_scope,
    FormalClaimGuardError,
    StudyAreaConfirmationError,
    StudyAreaConfirmationService as _StudyAreaConfirmationService,
    StudyAreaValidationError,
    evidence_semantic_contract,
    is_stale_dependency,
    validate_exploration_scope,
    validate_formal_claim,
    validate_study_area_artifact,
)


class StudyAreaConfirmationService(_StudyAreaConfirmationService):
    """Give test-created confirmations an explicit non-human test provenance."""

    def confirm(
        self,
        project_id,
        *,
        actor,
        actor_kind=ActorKind.TEST_HARNESS,
        actor_session_id="study-area-test-session",
        **kwargs,
    ):
        return super().confirm(
            project_id,
            actor=actor,
            actor_kind=actor_kind,
            actor_session_id=actor_session_id,
            **kwargs,
        )


NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
HASH_A = "sha256:" + "a" * 64


def _geojson(path, *, geometry=None, crs="EPSG:28992", units="m"):
    if geometry is None:
        geometry = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [20, 0], [20, 10], [0, 10], [0, 0]]],
        }
    payload = {"type": "Feature", "geometry": geometry}
    if crs is not None:
        payload["crs"] = {"type": "name", "properties": {"name": crs}}
    if units is not None:
        payload["units"] = units
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _store(tmp_path):
    store = ProjectStateStore(tmp_path / "state.sqlite3")
    store.create_typed(Project(id="project-a", name="Study Area fixture"), actor="test", reason="fixture")
    return store


def test_study_area_model_requires_projected_crs_and_confirmation_fields():
    with pytest.raises(ValidationError, match="projected"):
        StudyArea(
            id="area-v1",
            project_id="project-a",
            version="v1",
            geometry_artifact_id="artifact-a",
            geometry_sha256=HASH_A,
            horizontal_crs="EPSG:4326",
            units="m",
        )

    with pytest.raises(ValidationError, match="confirmation event"):
        StudyArea(
            id="area-v1",
            project_id="project-a",
            version="v1",
            geometry_artifact_id="artifact-a",
            geometry_sha256=HASH_A,
            horizontal_crs="EPSG:28992",
            units="m",
            status=StudyAreaStatus.CONFIRMED_FOR_EXPLORATION,
        )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"crs": None}, "horizontal CRS"),
        ({"units": None}, "units"),
        ({"crs": "EPSG:4326"}, "projected"),
        (
            {
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[0, 0], [10, 0]],
                }
            },
            "Polygon",
        ),
        (
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [],
                }
            },
            "empty",
        ),
        (
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [20, 0], [0, 0]]],
                }
            },
            "non-empty and valid",
        ),
        (
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 10], [0, 10], [10, 0], [0, 0]]],
                }
            },
            "self-intersecting",
        ),
    ],
)
def test_study_area_artifact_validation_fails_closed(tmp_path, kwargs, message):
    path = _geojson(tmp_path / "area.geojson", **kwargs)
    with pytest.raises(StudyAreaValidationError, match=message):
        validate_study_area_artifact(path)


def test_study_area_artifact_hash_mismatch_fails_closed(tmp_path):
    path = _geojson(tmp_path / "area.geojson")
    with pytest.raises(StudyAreaValidationError, match="does not match"):
        validate_study_area_artifact(path, expected_sha256="sha256:" + "b" * 64)


def test_confirmed_study_area_activates_all_four_stages_without_site_approval(tmp_path):
    store = _store(tmp_path)
    area = StudyAreaConfirmationService(store).confirm(
        "project-a",
        actor="designer",
        artifact_path=_geojson(tmp_path / "area.geojson"),
        confirmed_at=NOW,
    )

    assert area.status is StudyAreaStatus.CONFIRMED_FOR_EXPLORATION
    assert store.current("project-a").get("active_study_area_id") == area.id
    replayed = store.replay_project("project-a")
    assert replayed["project-a"].get("active_study_area_id") == area.id
    assert replayed[area.id].get("status") == "CONFIRMED_FOR_EXPLORATION"
    assert [event.action for event in store.events("project-a")] == [
        "Create",
        "Create",
        "ConfirmStudyArea",
        "ActivateStudyArea",
    ]
    assert not any(event.action in {"ApproveSite", "ApproveDesignBoundary", "AdoptSite"} for event in store.events("project-a"))

    for stage in ExplorationStage:
        validate_exploration_scope(area, stage)


def test_confirmed_study_area_does_not_require_bgt_or_road_alignment(tmp_path):
    # The arbitrary projected polygon is intentionally unrelated to any road
    # or cadastral fixture; exploration validation has no topology gate.
    path = _geojson(tmp_path / "arbitrary.geojson", geometry={
        "type": "Polygon",
        "coordinates": [[[12345, 67890], [12367, 67890], [12367, 67911], [12345, 67911], [12345, 67890]]],
    })
    store = _store(tmp_path)
    area = StudyAreaConfirmationService(store).confirm("project-a", actor="designer", artifact_path=path)
    assert area.status is StudyAreaStatus.CONFIRMED_FOR_EXPLORATION


def test_second_confirmation_versions_area_preserves_history_and_marks_declared_results_stale(tmp_path):
    store = _store(tmp_path)
    first = StudyAreaConfirmationService(store).confirm(
        "project-a", actor="designer", artifact_path=_geojson(tmp_path / "area-v1.geojson"), confirmed_at=NOW
    )
    store.create(
        "ToolExecution",
        {
            "id": "run-a",
            "project_id": "project-a",
            "study_area_id": first.id,
            "study_area_geometry_sha256": first.geometry_sha256,
            "status": "SUCCEEDED",
        },
        entity_id="run-a",
        project_id="project-a",
    )
    second = StudyAreaConfirmationService(store).confirm(
        "project-a", actor="designer", artifact_path=_geojson(tmp_path / "area-v2.geojson", geometry={
            "type": "Polygon",
            "coordinates": [[[0, 0], [30, 0], [30, 10], [0, 10], [0, 0]]],
        }), confirmed_at=NOW
    )

    assert second.version == "v2"
    assert store.current("project-a").get("active_study_area_id") == second.id
    assert store.current(first.id).get("status") == "SUPERSEDED"
    assert len(store.history(first.id)) == 2
    assert store.current("run-a").get("status") == "STALE"
    assert is_stale_dependency(
        store.current("run-a"),
        previous_study_area_id=first.id,
        previous_geometry_sha256=first.geometry_sha256,
    )
    stale_event = next(event for event in store.events("project-a") if event.action == "MarkStale")
    assert stale_event.actor_kind is ActorKind.AGENT_AUTOMATION
    assert stale_event.actor_session_id == "study-area-test-session"
    assert not any(event.action == "Rerun" for event in store.events("project-a"))


@pytest.mark.parametrize("claim_type", list(FormalClaimType))
def test_formal_claims_fail_closed_until_human_decision_approved_boundary(claim_type):
    with pytest.raises(FormalClaimGuardError, match="approved DesignBoundary"):
        validate_formal_claim(claim_type)

    proposed = {
        "id": "boundary-v1",
        "project_id": "project-a",
        "study_area_id": "area-v1",
        "version": "v1",
        "geometry_artifact_id": "artifact-a",
        "geometry_sha256": HASH_A,
        "horizontal_crs": "EPSG:28992",
        "units": "m",
    }
    with pytest.raises(FormalClaimGuardError, match="APPROVED"):
        validate_formal_claim(FormalClaimType.OWNERSHIP, design_boundary=proposed)

    with pytest.raises(FormalClaimGuardError, match="HumanDecision-backed"):
        validate_formal_claim(
            FormalClaimType.CADASTRAL,
            design_boundary={**proposed, "status": "APPROVED"},
        )

    with pytest.raises(ValidationError, match="HumanDecision"):
        DesignBoundary(**proposed, status=DesignBoundaryStatus.APPROVED)

    approved = DesignBoundary(
        **proposed,
        status=DesignBoundaryStatus.APPROVED,
        human_decision_id="decision-1",
        human_decision=HumanDecision(
            id="decision-1",
            project_id="project-a",
            target_id="boundary-v1",
            target_type="DesignBoundary",
            target_version="v1",
            target_geometry_sha256=HASH_A,
                action=DecisionAction.APPROVE,
                status=HumanStatus.APPROVED,
                actor="designer",
                actor_kind=ActorKind.HUMAN_UI,
                actor_session_id="decision-test-session",
                reason="approved for formal review",
            timestamp=NOW,
            decision_event_id="decision-event-1",
        ),
    )
    validate_formal_claim(FormalClaimType.LEGAL_BUILDABILITY, design_boundary=approved)


def test_evidence_semantics_keep_ai_and_gap_outputs_from_authoring_numbers_or_formal_claims():
    evidence_semantic_contract("DATASET_OBSERVATION", numeric_values={"area": 10})
    evidence_semantic_contract("COMPUTED_RESULT", numeric_values={"area": 10})
    with pytest.raises(StudyAreaValidationError, match="cannot author numerical"):
        evidence_semantic_contract("AI_INTERPRETATION", numeric_values={"area": 10})
    with pytest.raises(StudyAreaValidationError, match="formal claim"):
        evidence_semantic_contract("HYPOTHESIS", formal_claim_type="OWNERSHIP")
    with pytest.raises(StudyAreaValidationError, match="DATA_GAP"):
        evidence_semantic_contract("DATA_GAP", numeric_values={"area": 10})


def test_confirmation_is_atomic_when_activation_fails(tmp_path, monkeypatch):
    store = _store(tmp_path)

    def fail(*_args, **_kwargs):
        raise RuntimeError("activation unavailable")

    monkeypatch.setattr(store, "_append_ledger_event", fail)
    with pytest.raises(RuntimeError, match="activation unavailable"):
        StudyAreaConfirmationService(store).confirm(
            "project-a", actor="designer", artifact_path=_geojson(tmp_path / "area.geojson")
        )
    assert store.current("project-a").get("active_study_area_id") is None
    assert len(store.events("project-a")) == 1
    assert not any(record.entity_type == "Artifact" for record in store.replay_project("project-a").values())


def test_confirmation_rolls_back_artifact_and_study_area_when_activation_event_fails(tmp_path, monkeypatch):
    store = _store(tmp_path)
    original_append = store._append_ledger_event

    def fail_activation(**kwargs):
        if kwargs.get("action") == "ActivateStudyArea":
            raise RuntimeError("activation unavailable")
        return original_append(**kwargs)

    monkeypatch.setattr(store, "_append_ledger_event", fail_activation)
    with pytest.raises(RuntimeError, match="activation unavailable"):
        StudyAreaConfirmationService(store).confirm(
            "project-a", actor="designer", artifact_path=_geojson(tmp_path / "late-failure.geojson")
        )
    assert store.current("project-a").get("active_study_area_id") is None
    assert len(store.events("project-a")) == 1
    assert not any(record.entity_type in {"Artifact", "StudyArea"} for record in store.replay_project("project-a").values())


@pytest.mark.parametrize("declared", ["m", "meter", "meters", "metre", "metres"])
def test_epsg_28992_metre_aliases_are_canonicalized(tmp_path, declared):
    result = validate_study_area_artifact(_geojson(tmp_path / f"{declared}.geojson", units=declared))
    assert result.horizontal_crs == "EPSG:28992"
    assert result.units == "m"


@pytest.mark.parametrize("declared", ["feet", "ft", "degrees", "banana"])
def test_epsg_28992_rejects_non_metre_units(tmp_path, declared):
    with pytest.raises(StudyAreaValidationError, match="units|linear unit"):
        validate_study_area_artifact(_geojson(tmp_path / f"{declared}.geojson", units=declared))


def test_projected_foot_crs_normalizes_foot_aliases(tmp_path):
    path = _geojson(tmp_path / "foot.geojson", crs="EPSG:2277", units="US survey feet")
    result = validate_study_area_artifact(path)
    assert result.horizontal_crs == "EPSG:2277"
    assert result.units == "ft"


def test_confirmation_registers_resolvable_typed_artifact_with_matching_fields(tmp_path):
    store = _store(tmp_path)
    path = _geojson(tmp_path / "area.geojson")
    area = StudyAreaConfirmationService(store).confirm("project-a", actor="designer", artifact_path=path)
    artifact = store.current(area.geometry_artifact_id)
    assert artifact.entity_type == "Artifact"
    assert artifact.project_id == "project-a"
    assert artifact.get("uri") == str(path.resolve())
    assert artifact.get("sha256") == area.artifact_sha256
    assert artifact.get("size_bytes") == path.stat().st_size
    assert artifact.get("mime") == "application/geo+json"
    assert artifact.get("crs") == "EPSG:28992"
    assert artifact.get("producer") == "QGIS"


def test_nonexistent_caller_artifact_id_fails_before_mutation(tmp_path):
    store = _store(tmp_path)
    path = _geojson(tmp_path / "area.geojson")
    before = len(store.events("project-a"))
    with pytest.raises(StudyAreaConfirmationError, match="does not exist"):
        StudyAreaConfirmationService(store).confirm(
            "project-a", actor="designer", artifact_id="missing-artifact", artifact_path=path
        )
    assert len(store.events("project-a")) == before
    assert store.current("project-a").get("active_study_area_id") is None


@pytest.mark.parametrize("field", ["uri", "sha256", "size_bytes", "mime", "crs", "producer", "project_id"])
def test_existing_artifact_metadata_mismatch_fails_atomically(tmp_path, field):
    store = _store(tmp_path)
    path = _geojson(tmp_path / "area.geojson")
    raw = path.read_bytes()
    from hashlib import sha256

    values = {
        "id": "artifact-existing",
        "type": "study_area_geometry",
        "uri": str(path.resolve()),
        "sha256": "sha256:" + sha256(raw).hexdigest(),
        "mime": "application/geo+json",
        "crs": "EPSG:28992",
        "producer": "QGIS",
        "created_at": NOW,
        "project_id": "project-a",
        "size_bytes": len(raw),
    }
    if field == "uri":
        values[field] = str((tmp_path / "other.geojson").resolve())
    elif field == "sha256":
        values[field] = "sha256:" + "b" * 64
    elif field == "size_bytes":
        values[field] = values[field] + 1
    elif field == "mime":
        values[field] = "text/plain"
    elif field == "crs":
        values[field] = "EPSG:2277"
    elif field == "producer":
        values[field] = "unknown"
    elif field == "project_id":
        values[field] = "other-project"
    store.create_typed(Artifact(**values), actor="fixture", reason="mismatch fixture")
    before = len(store.events("project-a"))
    with pytest.raises(StudyAreaConfirmationError):
        StudyAreaConfirmationService(store).confirm(
            "project-a", actor="designer", artifact_id="artifact-existing", artifact_path=path
        )
    assert len(store.events("project-a")) == before
    assert store.current("project-a").get("active_study_area_id") is None
    assert not any(record.entity_type == "StudyArea" for record in store.replay_project("project-a").values())


def test_four_confirmations_use_project_scoped_monotonic_lineage(tmp_path):
    store = _store(tmp_path)
    service = StudyAreaConfirmationService(store)
    areas = []
    for index in range(4):
        areas.append(
            service.confirm(
                "project-a",
                actor="designer",
                artifact_path=_geojson(
                    tmp_path / f"area-{index}.geojson",
                    geometry={
                        "type": "Polygon",
                        "coordinates":[[
                            [0, 0], [20 + index, 0], [20 + index, 10], [0, 10], [0, 0]
                        ]],
                    },
                ),
            )
        )
    assert [area.version for area in areas] == ["v1", "v2", "v3", "v4"]
    assert [area.supersedes_id for area in areas] == [None, areas[0].id, areas[1].id, areas[2].id]
    replayed = store.replay_project("project-a")
    assert [replayed[area.id].get("version") for area in areas] == ["v1", "v2", "v3", "v4"]
    assert replayed["project-a"].get("active_study_area_id") == areas[-1].id


def test_duplicate_explicit_version_or_id_fails_without_mutation(tmp_path):
    store = _store(tmp_path)
    service = StudyAreaConfirmationService(store)
    first = service.confirm("project-a", actor="designer", artifact_path=_geojson(tmp_path / "one.geojson"))
    before_events = len(store.events("project-a"))
    with pytest.raises(StudyAreaConfirmationError, match="version"):
        service.confirm(
            "project-a", actor="designer", artifact_path=_geojson(tmp_path / "two.geojson"), version="V1"
        )
    assert len(store.events("project-a")) == before_events
    with pytest.raises(StudyAreaConfirmationError, match="already exists"):
        service.confirm(
            "project-a",
            actor="designer",
            artifact_path=_geojson(tmp_path / "three.geojson"),
            version="v2",
            study_area_id=first.id,
        )
    assert len(store.events("project-a")) == before_events


def _boundary_and_decision(*, decision_id="decision-1", project_id="project-a", target_id="boundary-v1", action="Approve", status="approved"):
    decision = HumanDecision(
        id=decision_id,
        project_id=project_id,
        target_id=target_id,
        target_type="DesignBoundary",
        target_version="v1",
        target_geometry_sha256=HASH_A,
        action=action,
        status=status,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="decision-test-session",
        reason="formal boundary approved",
        timestamp=NOW,
        decision_event_id="decision-event-1",
    )
    boundary = DesignBoundary(
        id=target_id,
        project_id=project_id,
        study_area_id="area-v1",
        version="v1",
        geometry_artifact_id="artifact-a",
        geometry_sha256=HASH_A,
        horizontal_crs="EPSG:28992",
        units="m",
        status=DesignBoundaryStatus.APPROVED,
        human_decision_id=decision_id,
        human_decision=decision,
    )
    return boundary, decision


def test_bare_human_decision_id_never_authorizes_formal_claim():
    boundary, _decision = _boundary_and_decision()
    bare = boundary.model_copy(update={"human_decision": None})
    with pytest.raises(FormalClaimGuardError, match="complete typed HumanDecision"):
        validate_formal_claim(FormalClaimType.OWNERSHIP, design_boundary=bare)


def test_persisted_matching_human_decision_and_event_authorize_formal_claim(tmp_path):
    store = _store(tmp_path)
    boundary, decision = _boundary_and_decision()
    store.create(
        "DesignBoundary",
        {
            "id": boundary.id,
            "project_id": boundary.project_id,
            "version": boundary.version,
            "geometry_sha256": boundary.geometry_sha256,
            "status": "APPROVED",
        },
        entity_id=boundary.id,
        project_id=boundary.project_id,
    )
    from urban_design.decision_key import initialize_decision_key

    key_path = tmp_path / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    store.record_human_decision(decision, decision_key=secret, decision_key_path=key_path)
    validate_formal_claim(FormalClaimType.CADASTRAL, design_boundary=boundary, store=store)


def test_formal_claim_rejects_decision_event_with_wrong_target_type(tmp_path):
    store = _store(tmp_path)
    boundary, decision = _boundary_and_decision()
    store.create(
        "DesignBoundary",
        {
            "id": boundary.id,
            "project_id": boundary.project_id,
            "version": boundary.version,
            "geometry_sha256": boundary.geometry_sha256,
            "status": "APPROVED",
        },
        entity_id=boundary.id,
        project_id=boundary.project_id,
    )
    from urban_design.decision_key import initialize_decision_key

    key_path = tmp_path / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    store.record_human_decision(decision, decision_key=secret, decision_key_path=key_path)
    for (trigger_name,) in store.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger'"
    ).fetchall():
        escaped_name = trigger_name.replace('"', '""')
        store.connection.execute(f'DROP TRIGGER "{escaped_name}"')
    store.connection.execute(
        "UPDATE ledger_events SET target_type = 'Artifact' WHERE event_id = ?",
        (decision.decision_event_id,),
    )
    store.connection.commit()
    with pytest.raises(FormalClaimGuardError, match="ledger event"):
        validate_formal_claim(FormalClaimType.CADASTRAL, design_boundary=boundary, store=store)


@pytest.mark.parametrize(
    ("column", "value"),
    [("actor_kind", None), ("actor_session_id", "")],
)
def test_formal_claim_replay_rejects_missing_event_actor_provenance(tmp_path, column, value):
    store = _store(tmp_path)
    boundary, decision = _boundary_and_decision()
    store.create(
        "DesignBoundary",
        {
            "id": boundary.id,
            "project_id": boundary.project_id,
            "version": boundary.version,
            "geometry_sha256": boundary.geometry_sha256,
            "status": "APPROVED",
        },
        entity_id=boundary.id,
        project_id=boundary.project_id,
    )
    from urban_design.decision_key import initialize_decision_key

    key_path = tmp_path / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    store.record_human_decision(decision, decision_key=secret, decision_key_path=key_path)
    for (trigger_name,) in store.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger'"
    ).fetchall():
        escaped_name = trigger_name.replace('"', '""')
        store.connection.execute(f'DROP TRIGGER "{escaped_name}"')
    store.connection.execute(f"UPDATE ledger_events SET {column} = ? WHERE event_id = ?", (value, decision.decision_event_id))
    store.connection.commit()
    with pytest.raises(FormalClaimGuardError, match="ledger event"):
        validate_formal_claim(FormalClaimType.CADASTRAL, design_boundary=boundary, store=store)


@pytest.mark.parametrize("mutator", [
    lambda d: d.model_copy(update={"project_id": "other-project"}),
    lambda d: d.model_copy(update={"target_id": "other-boundary"}),
    lambda d: d.model_copy(update={"target_geometry_sha256": "sha256:" + "b" * 64}),
    lambda d: d.model_copy(update={"action": DecisionAction.REJECT}),
    lambda d: d.model_copy(update={"status": HumanStatus.REJECTED}),
])
def test_wrong_or_rejected_human_decision_fails_closed(mutator):
    boundary, decision = _boundary_and_decision()
    invalid = mutator(decision)
    invalid_boundary = boundary.model_copy(update={"human_decision": invalid})
    with pytest.raises(FormalClaimGuardError):
        validate_formal_claim(FormalClaimType.OWNERSHIP, design_boundary=invalid_boundary)


def test_runtime_exploration_requires_persisted_matching_events(tmp_path):
    store = _store(tmp_path)
    path = _geojson(tmp_path / "area.geojson")
    area = StudyAreaConfirmationService(store).confirm("project-a", actor="designer", artifact_path=path)
    for stage in ExplorationStage:
        authorize_exploration_scope(store, area, stage)
        validate_exploration_scope(area, stage, store=store)
    fake = area.model_copy(update={"id": "fabricated-area"})
    with pytest.raises(StudyAreaConfirmationError, match="not persisted"):
        authorize_exploration_scope(store, fake, ExplorationStage.UNDERSTAND)


def test_cli_returns_nonzero_without_partial_state_on_invalid_units(tmp_path):
    store = _store(tmp_path)
    database = tmp_path / "state.sqlite3"
    # Reopen through the CLI against the same database after closing the fixture.
    store.close()
    path = _geojson(tmp_path / "area.geojson", units="feet")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "scripts" / "confirm_study_area.py"),
            "--database", str(database),
            "--project-id", "project-a",
            "--artifact-path", str(path),
            "--actor", "designer",
            "--actor-kind", "TEST_HARNESS",
            "--actor-session-id", "test-cli-session",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    with ProjectStateStore(database) as reopened:
        assert reopened.current("project-a").get("active_study_area_id") is None
        assert not any(record.entity_type == "Artifact" for record in reopened.replay_project("project-a").values())
