"""Release-blocking tests for the M2-A02 QGIS StudyArea bridge."""

from __future__ import annotations

from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from urban_design.bridge import (
    QGIS_MCP_VERSION,
    QgisMCPPreDispatchError,
    QgisMCPPostDispatchError,
    create_app,
)
from urban_design.models import ActorKind, Project
from urban_design.store import ProjectStateStore


PROJECT_ID = "project-a"
INSTANCE = "qgis-instance-a"
TOKEN = "session-token-a"


def _geometry(width: float = 20) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[0, 0], [width, 0], [width, 10], [0, 10], [0, 0]]],
    }


class FakeQgis:
    def __init__(self, *, geometry=None, layer_id="draft-layer", layer_name="Study Area Draft"):
        self.geometry = geometry or _geometry()
        self.layer_id = layer_id
        self.layer_name = layer_name
        self.active = True
        self.selection = [7]
        self.layer_type = "vector"
        self.geometry_type = 2
        self.crs = "EPSG:28992"
        self.units = "m"
        self.calls: list[tuple[str, dict]] = []
        self.server_version = QGIS_MCP_VERSION
        self.plugin_version = QGIS_MCP_VERSION
        self.fail_command: str | None = None
        self.fail_exception: Exception | None = None

    def send_command(self, command: str, params: dict | None = None):
        params = dict(params or {})
        self.calls.append((command, params))
        if command == self.fail_command:
            raise self.fail_exception or RuntimeError("fake QGIS failure")
        if command == "ping":
            return {"status": "success", "result": {"pong": True}}
        if command == "get_plugin_info":
            return {
                "status": "success",
                "result": {"name": "qgis_mcp_plugin", "version": self.plugin_version, "enabled": True},
            }
        if command == "get_active_layer":
            return {
                "status": "success",
                "result": {
                    "active": self.active,
                    "layer_id": self.layer_id if self.active else None,
                    "name": self.layer_name if self.active else None,
                    "type": self.layer_type if self.active else None,
                },
            }
        if command == "get_layer_info":
            return {
                "status": "success",
                "result": {
                    "id": self.layer_id,
                    "name": self.layer_name,
                    "type": self.layer_type,
                    "geometry_type": self.geometry_type,
                    "crs": self.crs,
                    "units": self.units,
                    "is_valid": True,
                },
            }
        if command == "get_selection":
            return {"status": "success", "result": {"fids": list(self.selection), "count": len(self.selection)}}
        if command == "export_layer":
            output_path = Path(params["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [{"type": "Feature", "properties": {}, "geometry": self.geometry}],
                        "crs": {"type": "name", "properties": {"name": self.crs}},
                    }
                ),
                encoding="utf-8",
            )
            return {"status": "success", "result": {"ok": True, "output": str(output_path)}}
        raise AssertionError(f"unexpected command {command}")

    def probe(self):
        return {
            "server_version": self.server_version,
            "plugin_version": self.plugin_version,
            "reachable": True,
        }


def _store(tmp_path):
    store = ProjectStateStore(tmp_path / "state.sqlite3")
    store.create_typed(
        Project(id=PROJECT_ID, name="Bridge fixture"),
        actor="test",
        actor_kind=ActorKind.TEST_HARNESS,
        actor_session_id="qgis-bridge-test",
        reason="fixture",
    )
    return store


def _client(tmp_path, fake=None, **kwargs):
    fake = fake or FakeQgis()
    app = create_app(
        store=_store(tmp_path),
        qgis_transport=fake,
        artifact_root=tmp_path / "artifacts",
        instance_id=INSTANCE,
        session_token=TOKEN,
        qgis_server_version=QGIS_MCP_VERSION,
        **kwargs,
    )
    return TestClient(app), fake, app


def _capture(client, request_id="request-1", **overrides):
    body = {
        "instance": INSTANCE,
        "layer_id": "draft-layer",
        "fid": 7,
        "actor": "designer",
        "actor_kind": "QGIS_PLUGIN",
        "actor_session_id": INSTANCE,
        "request_id": request_id,
    }
    body.update(overrides)
    return client.post(
        f"/api/v1/projects/{PROJECT_ID}/study-area/capture",
        json=body,
        headers={"X-Urban-Design-Session-Token": TOKEN},
    )


def test_valid_capture_uses_backend_generated_filter_and_confirms_v1(tmp_path):
    client, fake, app = _client(tmp_path)
    response = _capture(client)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["version"] == "v1"
    assert payload["status"] == "CONFIRMED_FOR_EXPLORATION"
    assert payload["horizontal_crs"] == "EPSG:28992"
    assert payload["units"] == "m"
    assert payload["area_m2"] == pytest.approx(200)
    assert payload["artifact_sha256"].startswith("sha256:")
    assert payload["geometry_sha256"].startswith("sha256:")
    export_calls = [params for command, params in fake.calls if command == "export_layer"]
    assert len(export_calls) == 1
    assert export_calls[0]["filter_expression"] == "$id = 7"
    assert export_calls[0]["target_crs"] is None
    assert "geometry" not in export_calls[0]
    assert "path" not in export_calls[0]
    area = app.state.bridge.store.current(payload["study_area_id"])
    confirmation = next(
        event for event in app.state.bridge.store.events(project_id=PROJECT_ID)
        if event.action == "ConfirmStudyArea"
    )
    assert confirmation.actor_kind is ActorKind.QGIS_PLUGIN
    assert confirmation.actor_session_id == INSTANCE
    artifact = app.state.bridge.store.current(area.get("geometry_artifact_id"))
    assert artifact.entity_type == "Artifact"
    assert artifact.get("sha256") == payload["artifact_sha256"]


def test_duplicate_request_id_returns_original_without_second_qgis_dispatch(tmp_path):
    client, fake, _ = _client(tmp_path)
    first = _capture(client, request_id="duplicate")
    second = _capture(client, request_id="duplicate")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert [command for command, _ in fake.calls].count("export_layer") == 1


def test_reused_request_id_with_different_fingerprint_is_rejected(tmp_path):
    client, fake, _ = _client(tmp_path)
    first = _capture(client, request_id="conflict")
    assert first.status_code == 200
    second = _capture(client, request_id="conflict", fid=8)
    assert second.status_code == 409
    assert second.json()["code"] == "REQUEST_ID_CONFLICT"
    assert second.json()["retry_allowed"] is False
    assert [command for command, _ in fake.calls].count("export_layer") == 1


def test_changed_selection_creates_v2_and_marks_declared_dependant_stale(tmp_path):
    client, fake, app = _client(tmp_path)
    first = _capture(client, request_id="version-1")
    assert first.status_code == 200
    first_payload = first.json()
    app.state.bridge.store.create(
        "ToolExecution",
        {
            "id": "dependent-run",
            "project_id": PROJECT_ID,
            "study_area_id": first_payload["study_area_id"],
            "study_area_geometry_sha256": first_payload["geometry_sha256"],
            "status": "SUCCEEDED",
        },
        entity_id="dependent-run",
        project_id=PROJECT_ID,
    )
    fake.geometry = _geometry(30)
    second = _capture(client, request_id="version-2")
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["version"] == "v2"
    assert second_payload["study_area_id"] != first_payload["study_area_id"]
    assert app.state.bridge.store.current(first_payload["study_area_id"]).get("status") == "SUPERSEDED"
    assert app.state.bridge.store.current("dependent-run").get("status") == "STALE"
    assert len(app.state.bridge.store.history(first_payload["study_area_id"])) == 2


def test_request_schema_rejects_geometry_expression_and_path_injection(tmp_path):
    client, fake, _ = _client(tmp_path)
    for injected in (
        {"geometry": _geometry()},
        {"expression": "$id = 7"},
        {"output_path": str(tmp_path / "unsafe.geojson")},
        {"target_crs": "EPSG:4326"},
    ):
        response = _capture(client, request_id="inject-" + next(iter(injected)), **injected)
        assert response.status_code == 422, response.text
    assert fake.calls == []


def test_capture_schema_rejects_coercible_non_integer_fid(tmp_path):
    client, fake, _ = _client(tmp_path)
    response = _capture(client, request_id="strict-fid", fid=7.0)
    assert response.status_code == 422
    assert fake.calls == []


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda f: setattr(f, "selection", []), "exactly one"),
        (lambda f: setattr(f, "selection", [7, 8]), "exactly one"),
        (lambda f: setattr(f, "active", False), "active"),
        (lambda f: setattr(f, "layer_name", "Other layer"), "Study Area Draft"),
        (lambda f: setattr(f, "geometry_type", 1), "polygon"),
        (lambda f: setattr(f, "crs", "EPSG:4326"), "28992"),
        (lambda f: setattr(f, "units", "ft"), "units"),
    ],
)
def test_capture_rejects_independent_qgis_preconditions(tmp_path, mutator, message):
    fake = FakeQgis()
    mutator(fake)
    client, _, _ = _client(tmp_path, fake)
    response = _capture(client, request_id="precondition")
    assert response.status_code in {400, 409, 422}
    assert message.casefold() in response.text.casefold()


def test_capture_accepts_qgis_mcp_vector_geometry_type_label(tmp_path):
    fake = FakeQgis()
    fake.layer_type = "vector_2"
    client, _, _ = _client(tmp_path, fake)
    response = _capture(client, request_id="vector-type-label")
    assert response.status_code == 200, response.text


def test_mismatched_fid_is_rejected_before_export(tmp_path):
    client, fake, _ = _client(tmp_path)
    response = _capture(client, fid=8)
    assert response.status_code in {400, 409, 422}
    assert "fid" in response.text.casefold()
    assert not any(command == "export_layer" for command, _ in fake.calls)


def test_unknown_project_is_a_typed_domain_error_before_qgis_dispatch(tmp_path):
    client, fake, _ = _client(tmp_path)
    response = client.post(
        "/api/v1/projects/missing-project/study-area/capture",
        json={
            "instance": INSTANCE,
            "layer_id": "draft-layer",
            "fid": 7,
            "actor": "designer",
            "actor_kind": "QGIS_PLUGIN",
            "actor_session_id": INSTANCE,
            "request_id": "missing-project",
        },
        headers={"X-Urban-Design-Session-Token": TOKEN},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"
    assert response.json()["request_id"] == "missing-project"
    assert fake.calls == []


def test_post_dispatch_connection_loss_is_outcome_unknown_and_not_retried(tmp_path):
    fake = FakeQgis()
    fake.fail_command = "export_layer"
    fake.fail_exception = QgisMCPPostDispatchError("socket closed after dispatch")
    client, fake, _ = _client(tmp_path, fake)
    response = _capture(client, request_id="unknown")
    assert response.status_code == 503
    assert response.json()["status"] == "OUTCOME_UNKNOWN"
    assert response.json()["retry_allowed"] is False
    again = _capture(client, request_id="unknown")
    assert again.json() == response.json()
    assert [command for command, _ in fake.calls].count("export_layer") == 1


def test_pre_dispatch_failure_is_failed_and_can_be_reconciled_without_state(tmp_path):
    fake = FakeQgis()
    fake.fail_command = "get_active_layer"
    fake.fail_exception = QgisMCPPreDispatchError("QGIS is offline")
    client, fake, app = _client(tmp_path, fake)
    response = _capture(client, request_id="offline")
    assert response.status_code == 503
    assert response.json()["status"] == "FAILED"
    assert response.json()["dispatched"] is False
    assert app.state.bridge.store.events(PROJECT_ID)[-1].action == "Create"


def test_status_reports_separate_qgis_and_ladybug_readiness(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.get(
        "/api/v1/integrations/status",
        headers={"X-Urban-Design-Session-Token": TOKEN},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["backend"]["status"] == "READY"
    assert payload["qgis_mcp"]["status"] == "READY"
    assert payload["qgis_mcp"]["server_version"] == QGIS_MCP_VERSION
    assert "ladybug_core" in payload["ladybug"]
    assert payload["ladybug"]["ladybug_core"]["status"] in {"READY", "DEGRADED", "UNAVAILABLE"}
    assert payload["ladybug"]["radiance_executables"]["status"] in {"READY", "DEGRADED", "UNAVAILABLE"}


def test_status_reports_qgis_version_mismatch_as_degraded(tmp_path):
    fake = FakeQgis()
    fake.plugin_version = "0.13.0"
    client, _, _ = _client(tmp_path, fake)
    payload = client.get(
        "/api/v1/integrations/status",
        headers={"X-Urban-Design-Session-Token": TOKEN},
    ).json()
    assert payload["qgis_mcp"]["status"] == "DEGRADED"


def test_status_requires_session_token_when_configured(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.get("/api/v1/integrations/status")
    assert response.status_code == 401
