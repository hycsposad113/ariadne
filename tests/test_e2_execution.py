"""E2 authority and deterministic comparison regressions; no fixture PASS mocks."""
from datetime import datetime, timezone
from pathlib import Path
import secrets

from fastapi.testclient import TestClient
import pytest

from urban_design.api import create_workspace_app
from urban_design.decision_key import initialize_decision_key
from urban_design.store import ProjectStateStore
from urban_design.environment.e2_service import direction_summary, compare_distributions, readiness
from urban_design.environment.weather_snapshot import E2Blocked, bound_approval, persist_bytes, checked_artifact


def approval(client, record, key, *, action="Approve", status="approved"):
    body = dict(target_id=record.entity_id, target_type=record.entity_type,
                target_version=str(record.payload.get("version",record.revision)), action=action, status=status,
                reason="Disposable test-only approval", decision_key=key, actor_session_id="e2-test-session")
    body["target_artifact_sha256" if record.entity_type == "Artifact" else "target_payload_digest"] = record.payload.get("sha256") if record.entity_type == "Artifact" else record.payload["payload_digest"]
    return client.post(f"/api/v1/projects/{record.project_id}/decisions", json=body)


@pytest.fixture
def authority(tmp_path):
    store = ProjectStateStore(tmp_path / "copy.sqlite3")
    store.create_project({"id":"p", "name":"E2 test project"}, project_id="p")
    key = secrets.token_urlsafe(24)
    key_path = initialize_decision_key(path=tmp_path / "test-key", password_prompt=lambda _: key)
    app = create_workspace_app(store=store, decision_key_path=key_path)
    with TestClient(app) as client:
        yield store, client, key, tmp_path
    store.close()


def test_approval_hash_and_latest_rejection(authority):
    store, client, key, root = authority
    record = persist_bytes(store, "p", root / "artifacts", "experiment-plan", b'{"test":1}')
    with pytest.raises(E2Blocked, match="NOT_APPROVED"):
        bound_approval(store, record, record.payload["sha256"])
    response = approval(client, record, key)
    assert response.status_code == 201, response.text
    assert bound_approval(store, record, record.payload["sha256"])
    response = approval(client, record, key, action="Reject", status="rejected")
    assert response.status_code == 201, response.text
    with pytest.raises(E2Blocked, match="APPROVAL_BINDING_INVALID"):
        bound_approval(store, record, record.payload["sha256"])


def test_artifact_bytes_drift_denied(authority):
    store, _, _, root = authority
    record = persist_bytes(store, "p", root / "artifacts", "experiment-plan", b'{"test":1}')
    Path(record.payload["uri"]).write_bytes(b'{"test":2}')
    with pytest.raises(E2Blocked, match="ARTIFACT_HASH_MISMATCH"):
        checked_artifact(store, record.entity_id, "p")


def test_missing_plan_and_cross_method_absolute_denied(authority):
    store, client, _, _ = authority
    assert readiness(store, "missing", "p")["dispatch_allowed"] is False
    response = client.post("/api/v1/environment/e2/compare", json={"project_id":"p", "job_id":"missing", "comparison":"absolute"})
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "CROSS_METHOD_ABSOLUTE_COMPARISON_FORBIDDEN"


def test_sensitivity_reversal_and_disagreement():
    comparisons = {m: {str(s): {"direction": "DECREASED"} for s in (-1,0,1)} for m in ("ladybug_radiance","honeybee_radiance")}
    comparisons["ladybug_radiance"]["1"]["direction"] = "INCREASED"
    result = direction_summary(comparisons)
    assert result["sensitivity_reversed"] is True
    assert result["direction_agreement_by_offset"]["1"] is False
    assert result["methods"]["honeybee_radiance"]["sensitivity_reversed"] is False


def test_common_overlap_weight_and_occupancy():
    sensors = [{"point_id":"a", "cell_area_m2":1}, {"point_id":"b", "cell_area_m2":3}]
    baseline = {"sensors": sensors, "values":{"a":10,"b":100}, "valid_area_m2":4}
    modified = {"sensors": sensors, "values":{"a":9}, "valid_area_m2":1}
    result = compare_distributions(baseline, modified)
    assert result["direction"] == "DECREASED"
    assert result["baseline_kwh_m2"] == 10
    assert result["common_area_m2"] == 1
    assert result["occupancy_ratio"] == .5
    assert result["area_occupancy_ratio"] == .75
