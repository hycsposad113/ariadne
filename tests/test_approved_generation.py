from __future__ import annotations
from urban_design.geometry import canonical_geometry_hash

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from shapely.geometry import shape

from urban_design import decision_key
from urban_design.approved_generation import (
    ApprovedGenerationBlocked,
    run_approved_generation,
)
from urban_design.constraint_sets import constraint_set_payload_digest
from urban_design.models import (
    ActorKind,
    Artifact,
    Constraint,
    ConstraintSet,
    ConstraintStatus,
    DatasetSnapshot,
    DecisionAction,
    HumanDecision,
    HumanStatus,
)
from urban_design.store import ProjectStateStore
from urban_design.workspace_contracts import (
    ExplorationDesignArea,
    FeatureDisposition,
    SpatialZone,
    SyncRequest,
    WorkspaceSpatialBrief,
)
from urban_design.workspace_service import WorkspaceService


PROJECT_ID = "project-generation-fixture"
AREA = {
    "type": "Polygon",
    "coordinates": [[[90000.0, 436000.0], [90100.0, 436000.0], [90100.0, 436080.0], [90000.0, 436080.0], [90000.0, 436000.0]]],
}
RETAINED_FOOTPRINT = {
    "type": "Polygon",
    "coordinates": [[[90004.0, 436004.0], [90010.0, 436004.0], [90010.0, 436010.0], [90004.0, 436010.0], [90004.0, 436004.0]]],
}


def _artifact(store: ProjectStateStore, root: Path, artifact_id: str, document: dict) -> Artifact:
    path = root / f"{artifact_id}.geojson"
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    record = Artifact(
        id=artifact_id,
        type="source-geojson",
        uri=str(path),
        sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        mime="application/geo+json",
        crs="EPSG:28992",
        producer="test-fixture",
        created_at=datetime.now(timezone.utc),
        project_id=PROJECT_ID,
        size_bytes=len(raw),
    )
    store.create_typed(record, actor="test-fixture", actor_kind=ActorKind.TEST_HARNESS)
    return record


def _create_decision(
    store: ProjectStateStore,
    *,
    secret: str,
    key_path: Path,
    target_id: str,
    target_type: str,
    target_version: str,
    target_payload_digest: str,
) -> None:
    geometry_binding = {}
    if target_type == "WorkspaceRevision":
        from urban_design.geometry import canonical_geometry_hash
        target = store.current(target_id)
        eda = (target.payload.get("spatial_brief") or {}).get("exploration_design_area")
        if eda:
            geometry_binding['target_geometry_sha256'] = canonical_geometry_hash(eda['geometry'])
    decision = HumanDecision(
        **geometry_binding,
        id=f"decision-{uuid.uuid4().hex}",
        project_id=PROJECT_ID,
        target_id=target_id,
        target_type=target_type,
        target_version=target_version,
        target_payload_digest=target_payload_digest,
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
        actor="designer-fixture",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id=f"session-{uuid.uuid4().hex}",
        reason="Test fixture only.",
        timestamp=datetime.now(timezone.utc),
    )
    store.record_human_decision(decision, decision_key=secret, decision_key_path=key_path)


def _constraints() -> list[Constraint]:
    return [
        Constraint(id="c-far", name="far_upper_limit", value=2.4, unit="ratio", scope="whole_site", enforcement="HARD"),
        Constraint(id="c-coverage", name="coverage_upper_limit", value=0.5, unit="ratio", scope="whole_site", enforcement="HARD"),
        Constraint(id="c-height", name="height_upper_limit", value=18.0, unit="m", scope="whole_site", enforcement="HARD"),
        Constraint(id="c-first-floor", name="first_floor_height", value=4.0, unit="m", scope="whole_site", enforcement="HARD"),
        Constraint(id="c-standard-floor", name="standard_floor_height", value=3.0, unit="m", scope="whole_site", enforcement="HARD"),
        Constraint(id="c-road", name="road_width", value=6.0, unit="m", scope="road:hierarchy-a", enforcement="HARD"),
        Constraint(id="c-rotation", name="rotation_step", value=15.0, unit="degree", scope="whole_site", enforcement="PREFERENCE"),
    ]


def _workspace_fixture(
    root: Path,
    *,
    omit: str | None = None,
    stale_workspace_decision: bool = False,
    known_retained_floors: bool = False,
) -> tuple[ProjectStateStore, Path]:
    database = root / "fixture.sqlite3"
    store = ProjectStateStore(database)
    store.create_project({"id": PROJECT_ID, "name": "fixture"}, project_id=PROJECT_ID)

    area_record = store.create(
        "StudyArea",
        {"id": "study-area-fixture", "project_id": PROJECT_ID, "version": "v1", "status": "CONFIRMED_FOR_EXPLORATION", "geometry_sha256": canonical_geometry_hash(AREA)},
        entity_id="study-area-fixture",
        project_id=PROJECT_ID,
        actor="test-fixture",
        actor_kind=ActorKind.TEST_HARNESS,
    )
    building_artifact = _artifact(
        store,
        root,
        "artifact-buildings",
        {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "building-1", "geometry": RETAINED_FOOTPRINT, "properties": {"bag_id": "bag-fixture-1"}}]},
    )
    road_artifact = _artifact(
        store,
        root,
        "artifact-roads",
        {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "road-1", "geometry": {"type": "LineString", "coordinates": [[90000.0, 436020.0], [90100.0, 436020.0]]}, "properties": {"layer": 0, "highway": "residential"}}]},
    )
    source_records = [("snapshot-buildings", building_artifact), ("snapshot-roads", road_artifact)]
    if known_retained_floors:
        bag_artifact = _artifact(
            store,
            root,
            "artifact-3dbag",
            {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "id": "bag-fixture-1",
                    "geometry": RETAINED_FOOTPRINT,
                    "properties": {
                        "bag_id": "bag-fixture-1",
                        "roof_p70_height_m": 10.0,
                        "ground_height_m": 0.0,
                        "gebruiksdoel": "woonfunctie",
                    },
                }],
            },
        )
        source_records.append(("snapshot-3dbag", bag_artifact))
    for snapshot_id, artifact in source_records:
        store.create_typed(
            DatasetSnapshot(
                id=snapshot_id,
                project_id=PROJECT_ID,
                source="3D BAG fixture" if snapshot_id == "snapshot-3dbag" else "fixture-source",
                query=f"snapshot={snapshot_id}",
                retrieved_at=datetime.now(timezone.utc),
                publisher="Fixture publisher",
                license="Fixture-only",
                version="fixture-v1",
                sha256=artifact.sha256,
                raw_artifact_id=artifact.id,
                normalized_artifact_id=artifact.id,
            ),
            actor="test-fixture",
            actor_kind=ActorKind.TEST_HARNESS,
        )
        store.update(
            snapshot_id,
            {"status": "CONFIRMED"},
            expected_revision=1,
            actor="test-fixture",
            actor_kind=ActorKind.TEST_HARNESS,
            action="ConfirmFixtureSnapshot",
            reason="Mark the test-only source snapshot as confirmed.",
        )

    dispositions = [] if omit == "dispositions" else [
        FeatureDisposition(
            feature_id="building-1",
            feature_kind="building",
            disposition="preserve",
            source_artifact_id=building_artifact.id,
            source_snapshot_id="snapshot-buildings",
            source_feature_id="building-1",
        ),
        FeatureDisposition(
            feature_id="road-1",
            feature_kind="road",
            disposition="editable",
            source_artifact_id=road_artifact.id,
            source_snapshot_id="snapshot-roads",
            source_feature_id="road-1",
        ),
    ]
    brief = WorkspaceSpatialBrief(
        exploration_design_area=None if omit == "design_area" else ExplorationDesignArea(geometry=AREA),
        zones=[] if omit == "zones" else [
            SpatialZone(
                zone_id="zone-whole-site",
                name="Whole site",
                target_use="mixed-use",
                geometry=AREA,
                original_text="Fixture zone covering the test area.",
            )
        ],
    )
    workspace = WorkspaceService(store).sync(
        SyncRequest(
            project_id=PROJECT_ID,
            study_area_id=area_record.entity_id,
            expected_workspace_revision=0,
            source_snapshot_ids=[item[0] for item in source_records],
            idempotency_key=f"sync-{uuid.uuid4().hex}",
            actor_kind=ActorKind.HUMAN_UI,
            actor_session_id=f"workspace-{uuid.uuid4().hex}",
            feature_dispositions=dispositions,
            spatial_brief=brief,
        )
    )

    key_path = root / "config" / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    if omit != "workspace_decision":
        _create_decision(
            store,
            secret=secret,
            key_path=key_path,
            target_id=workspace.workspace_id,
            target_type="WorkspaceRevision",
            target_version=str(workspace.revision),
            target_payload_digest="sha256:" + (workspace.payload_digest or ""),
        )
    if stale_workspace_decision:
        store.update(
            workspace.workspace_id,
            {"revision": workspace.revision + 1, "status": "DRAFT"},
            expected_revision=1,
            actor="test-fixture",
            actor_kind=ActorKind.TEST_HARNESS,
            action="FixtureWorkspaceRevision",
            reason="Create a newer fixture workspace revision after its approval.",
        )

    if omit != "constraint_set":
        constraint_set = ConstraintSet(
            id="constraint-set-fixture",
            project_id=PROJECT_ID,
            version="v1",
            constraints=_constraints(),
        )
        if omit == "constraint_decision":
            constraint_set = constraint_set.model_copy(update={
                "status": ConstraintStatus.EFFECTIVE,
                "constraints": [item.model_copy(update={"status": ConstraintStatus.EFFECTIVE}) for item in constraint_set.constraints],
            })
        store.create_typed(constraint_set, actor="test-fixture", actor_kind=ActorKind.TEST_HARNESS)
        if omit != "constraint_decision":
            _create_decision(
                store,
                secret=secret,
                key_path=key_path,
                target_id=constraint_set.id,
                target_type="ConstraintSet",
                target_version=constraint_set.version,
                target_payload_digest=constraint_set_payload_digest(constraint_set),
            )
    return store, key_path


def test_approved_generation_writes_three_proposals_comparison_and_unavailable_retained_gfa(tmp_path: Path) -> None:
    store, _key_path = _workspace_fixture(tmp_path)
    source_database = tmp_path / "fixture.sqlite3"
    output_database = tmp_path / "generated-copy.sqlite3"
    result = run_approved_generation(
        source_database=source_database,
        output_database=output_database,
        artifact_root=tmp_path / "generated-artifacts",
        project_id=PROJECT_ID,
        fixture_only=True,
    )

    assert result.status == "GENERATED_FIXTURE_ONLY"
    assert len(result.scenario_ids) == 3
    assert result.comparison["ranking"] is None
    assert result.comparison["overall_score"] is None
    assert source_database != output_database
    assert len(store.list_current("Scenario", project_id=PROJECT_ID)) == 0
    store.close()

    with ProjectStateStore(output_database, read_only=True) as generated:
        scenarios = generated.list_current("Scenario", project_id=PROJECT_ID)
        assert len(scenarios) == 3
        assert len(generated.list_current("ToolExecution", project_id=PROJECT_ID)) == 4
        assert len(generated.list_current("Artifact", project_id=PROJECT_ID)) == 6
        assert all(record.payload["status"] == "proposed" for record in scenarios)
        assert all(record.payload["parameters"]["provenance"] == "FIXTURE_ONLY" for record in scenarios)
        executions = generated.list_current("ToolExecution", project_id=PROJECT_ID)
        strategy_executions = [item for item in executions if item.payload.get("scenario_id")]
        assert len(strategy_executions) == 3
        assert all({"snapshot-buildings", "snapshot-roads"}.issubset(item.payload["input_refs"]) for item in strategy_executions)
        assert all(
            item.payload["input_snapshot_hashes"][snapshot_id].startswith("sha256:")
            for item in strategy_executions
            for snapshot_id in ("snapshot-buildings", "snapshot-roads")
        )
        for record in scenarios:
            metrics = record.payload["parameters"]["metrics"]
            assert metrics["gfa_m2"]["status"] == "UNAVAILABLE"
            assert metrics["far"]["status"] == "PARTIALLY_UNKNOWN"
            assert metrics["far"]["known_lower_bound"] > 0
            assert "value" not in metrics["far"]
            artifact = generated.current(record.payload["geometry_artifact_id"])
            geojson = json.loads(Path(artifact.payload["uri"]).read_text(encoding="utf-8"))
            retained = [feature for feature in geojson["features"] if feature["properties"].get("source_feature_id") == "building-1"]
            assert len(retained) == 1
            assert shape(retained[0]["geometry"]).equals(shape(RETAINED_FOOTPRINT))
        comparison_artifacts = [item for item in generated.list_current("Artifact", project_id=PROJECT_ID) if item.payload.get("type") == "scenario-comparison"]
        assert len(comparison_artifacts) == 1


@pytest.mark.parametrize(
    ("omit", "expected_missing"),
    [
        ("design_area", "approved ExplorationDesignArea"),
        ("dispositions", "feature dispositions"),
        ("zones", "approved spatial zones"),
        ("constraint_set", "effective ConstraintSet"),
        ("constraint_decision", "effective ConstraintSet: no current approved HumanDecision"),
        ("workspace_decision", "no current approved HumanDecision"),
    ],
)
def test_missing_approved_prerequisite_stops_and_lists_missing_item(
    tmp_path: Path, omit: str, expected_missing: str
) -> None:
    store, _key_path = _workspace_fixture(tmp_path, omit=omit)
    output_database = tmp_path / "must-not-be-created.sqlite3"

    with pytest.raises(ApprovedGenerationBlocked) as blocked:
        run_approved_generation(
            source_database=tmp_path / "fixture.sqlite3",
            output_database=output_database,
            artifact_root=tmp_path / "artifacts",
            project_id=PROJECT_ID,
            fixture_only=True,
        )

    assert expected_missing in "\n".join(blocked.value.missing)
    assert not output_database.exists()
    store.close()


def test_new_draft_preserves_last_accepted_workspace(tmp_path: Path) -> None:
    store, _key_path = _workspace_fixture(tmp_path, stale_workspace_decision=True)
    from urban_design.approved_generation import _load_approved_inputs
    inputs = _load_approved_inputs(store, PROJECT_ID, site_generation=False)
    assert store.current(inputs.workspace_record.entity_id).revision == 2
    assert inputs.workspace_record.revision == 1
    assert inputs.workspace_decision.target_version == "1"
    store.close()


def test_source_artifact_must_match_its_workspace_dataset_snapshot(tmp_path: Path) -> None:
    store, _key_path = _workspace_fixture(tmp_path)
    store.update(
        "snapshot-buildings",
        {"normalized_artifact_id": "artifact-roads"},
        expected_revision=2,
        actor="test-fixture",
        actor_kind=ActorKind.TEST_HARNESS,
        action="CorruptFixtureLineage",
        reason="Exercise fail-closed source lineage validation.",
    )

    with pytest.raises(ApprovedGenerationBlocked) as blocked:
        run_approved_generation(
            source_database=tmp_path / "fixture.sqlite3",
            output_database=tmp_path / "out.sqlite3",
            artifact_root=tmp_path / "artifacts",
            project_id=PROJECT_ID,
            fixture_only=True,
        )

    assert any("not the normalized Artifact" in item for item in blocked.value.missing)
    assert not (tmp_path / "out.sqlite3").exists()
    store.close()


def test_formal_mode_uses_site_generator_without_promoting_fixture_sources(tmp_path: Path) -> None:
    store, _key_path = _workspace_fixture(tmp_path, known_retained_floors=True)
    output_database = tmp_path / "formal-output.sqlite3"

    result = run_approved_generation(
        source_database=tmp_path / "fixture.sqlite3",
        output_database=output_database,
        artifact_root=tmp_path / "formal-artifacts",
        project_id=PROJECT_ID,
    )

    assert result.status == "GENERATED_FIXTURE_ONLY"
    assert len(result.scenario_ids) == 3
    assert result.valid_candidate_count == 3
    assert result.failed_candidate_count == 0
    assert output_database.is_file()
    with ProjectStateStore(output_database, read_only=True) as generated:
        scenarios = generated.list_current("Scenario", project_id=PROJECT_ID)
        assert len(scenarios) == 3
        assert all(item.payload["status"] == "proposed" for item in scenarios)
        assert all(item.payload["generator"] == "urban_design.morphology.strategies.generate_site_strategies" for item in scenarios)
        assert all(item.payload["parameters"]["provenance"] == "FIXTURE_ONLY" for item in scenarios)
        assert all(item.payload["parameters"]["validation"]["valid"] for item in scenarios)
    store.close()


def test_formal_mode_persists_invalid_site_candidates_and_reasons(tmp_path: Path) -> None:
    store, _key_path = _workspace_fixture(tmp_path)
    output_database = tmp_path / "blocked-candidates.sqlite3"

    result = run_approved_generation(
        source_database=tmp_path / "fixture.sqlite3",
        output_database=output_database,
        artifact_root=tmp_path / "blocked-candidate-artifacts",
        project_id=PROJECT_ID,
    )

    assert result.valid_candidate_count == 0
    assert result.failed_candidate_count == 3
    with ProjectStateStore(output_database, read_only=True) as generated:
        scenarios = generated.list_current("Scenario", project_id=PROJECT_ID)
        assert len(scenarios) == 3
        assert all(item.payload["status"] == "blocked" for item in scenarios)
        assert all(item.payload["parameters"]["validation"]["failure_reasons"] for item in scenarios)
        assert len(generated.list_current("HumanDecision", project_id=PROJECT_ID)) == 2
    store.close()


def test_authority_write_requires_expected_sha256_before_opening_database(tmp_path: Path) -> None:
    from scripts.run_approved_generation import main

    database = tmp_path / "authority.sqlite3"
    database.write_bytes(b"must not be opened")
    with pytest.raises(SystemExit) as stopped:
        main(["--database", str(database), "--project-id", PROJECT_ID, "--write-authority"])
    assert stopped.value.code == 2
    assert database.read_bytes() == b"must not be opened"
