"""M2-A02-R02 georeference, locality, and project-context regressions."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from urban_design.bridge import QGIS_MCP_VERSION, create_app
from urban_design.project_anchor import ProjectAnchorError, load_project_anchor
from urban_design.store import ProjectStateStore
from urban_design.study_area_workflow import StudyAreaValidationError, validate_study_area_geometry


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "rotterdam-m4h-pilot-project"
INSTANCE = "qgis-instance-r02"
TOKEN = "r02-test-token"


def _polygon(x: float, y: float, width: float = 20.0) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[x, y], [x + width, y], [x + width, y + 20], [x, y + 20], [x, y]]],
    }


class FakeQgis:
    server_version = QGIS_MCP_VERSION
    plugin_version = QGIS_MCP_VERSION

    def __init__(self, geometry: dict):
        self.geometry = geometry
        self.calls: list[tuple[str, dict]] = []

    def send_command(self, command: str, params: dict | None = None):
        params = dict(params or {})
        self.calls.append((command, params))
        if command == "ping":
            return {"status": "success", "result": {"pong": True}}
        if command == "get_plugin_info":
            return {"status": "success", "result": {"version": QGIS_MCP_VERSION}}
        if command == "get_active_layer":
            return {"status": "success", "result": {"active": True, "layer_id": "draft", "name": "Study Area Draft"}}
        if command == "get_layer_info":
            return {"status": "success", "result": {"id": "draft", "name": "Study Area Draft", "type": "vector", "geometry_type": 2, "crs": "EPSG:28992", "units": "m"}}
        if command == "get_selection":
            return {"status": "success", "result": {"fids": [7], "count": 1}}
        if command == "export_layer":
            Path(params["output_path"]).write_text(json.dumps({
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {}, "geometry": self.geometry}],
                "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
            }), encoding="utf-8")
            return {"status": "success", "result": {"ok": True}}
        raise AssertionError(command)

    def probe(self):
        return {"server_version": QGIS_MCP_VERSION, "plugin_version": QGIS_MCP_VERSION, "reachable": True}


def _store(tmp_path: Path) -> ProjectStateStore:
    store = ProjectStateStore(tmp_path / "state.sqlite3")
    store.create_project(PROJECT_ID, {"id": PROJECT_ID, "name": PROJECT_ID, "site_id": None}, actor="test", reason="fixture")
    return store


def _client(tmp_path: Path, geometry: dict, **kwargs):
    app = create_app(
        store=_store(tmp_path),
        qgis_transport=FakeQgis(geometry),
        artifact_root=tmp_path / "artifacts",
        instance_id=INSTANCE,
        session_token=TOKEN,
        qgis_server_version=QGIS_MCP_VERSION,
        **kwargs,
    )
    return TestClient(app), app


def _capture(client: TestClient, request_id: str = "r02-1"):
    return client.post(
        f"/api/v1/projects/{PROJECT_ID}/study-area/capture",
        json={
            "instance": INSTANCE,
            "layer_id": "draft",
            "fid": 7,
            "actor": "designer",
            "actor_kind": "QGIS_PLUGIN",
            "actor_session_id": INSTANCE,
            "request_id": request_id,
        },
        headers={"X-Urban-Design-Session-Token": TOKEN},
    )


def test_retained_anchor_is_typed_source_backed_and_context_is_not_analysis_eligible():
    anchor = load_project_anchor(ROOT / "config/rotterdam-m4h-anchor.json", root=ROOT)
    assert anchor.project_id == PROJECT_ID
    assert anchor.horizontal_crs == "EPSG:28992"
    assert anchor.status == "DRAWING_LOCATION_GUARD_ONLY"
    assert anchor.context_display_only is True
    assert anchor.analysis_eligible is False
    assert anchor.anchor_extent[0] < anchor.anchor_extent[2]


@pytest.mark.parametrize(
    "geometry, message",
    [(_polygon(419, -213), "CRS area of use"), (_polygon(100000, 400000), "configured project geographic anchor")],
)
def test_shared_study_area_validation_rejects_crs_or_project_locality(geometry, message):
    anchor = load_project_anchor(ROOT / "config/rotterdam-m4h-anchor.json", root=ROOT)
    with pytest.raises(StudyAreaValidationError, match=message):
        validate_study_area_geometry(geometry, horizontal_crs="EPSG:28992", units="m", project_anchor=anchor)


def test_valid_m4h_fixture_passes_shared_validation():
    anchor = load_project_anchor(ROOT / "config/rotterdam-m4h-anchor.json", root=ROOT)
    result = validate_study_area_geometry(_polygon(89100, 435700), horizontal_crs="EPSG:28992", units="m", project_anchor=anchor)
    assert result["horizontal_crs"] == "EPSG:28992"


def test_backend_rechecks_locality_after_qgis_export_and_plugin_bypass_cannot_confirm(tmp_path: Path):
    anchor = load_project_anchor(ROOT / "config/rotterdam-m4h-anchor.json", root=ROOT)
    client, app = _client(tmp_path, _polygon(100000, 400000), project_anchor=anchor, anchor_root=ROOT)
    response = _capture(client)
    assert response.status_code == 422
    assert response.json()["code"] == "CAPTURE_REJECTED"
    project = app.state.bridge.store.current(PROJECT_ID)
    assert project.get("active_study_area_id") is None


def test_missing_anchor_fails_closed_before_capture_and_reports_separate_readiness(tmp_path: Path):
    client, app = _client(tmp_path, _polygon(89100, 435700), anchor_config_path=tmp_path / "missing.json", anchor_root=ROOT)
    response = _capture(client)
    assert response.status_code == 422
    assert response.json()["code"] == "PROJECT_ANCHOR_UNRESOLVED"
    status = client.get("/api/v1/integrations/status", headers={"X-Urban-Design-Session-Token": TOKEN})
    assert status.status_code == 200
    assert status.json()["anchor"]["status"] == "UNAVAILABLE"
    assert status.json()["context"]["status"] == "UNAVAILABLE"
    assert app.state.bridge.store.current(PROJECT_ID).get("active_study_area_id") is None


def test_project_xml_has_finite_anchor_extent_context_and_correct_new_draft_path():
    project = ROOT / ".urban_design_runtime/rotterdam-m4h-pilot-project.qgs"
    if not project.is_file():
        pytest.skip(
            "missing untracked runtime file .urban_design_runtime/rotterdam-m4h-pilot-project.qgs; "
            "this worktree does not carry the local QGIS project, so the anchor extent cannot be checked"
        )
    root = ET.parse(project).getroot()
    extent = root.find("mapcanvas/extent")
    values = [float(extent.findtext(name)) for name in ("xmin", "ymin", "xmax", "ymax")]
    assert all(value == value and abs(value) < 1e9 for value in values)
    assert root.find("projectCrs/spatialrefsys/authid").text == "EPSG:28992"
    layers = root.find("projectlayers").findall("maplayer")
    context = next(layer for layer in layers if layer.findtext("layername") == "NON_AUTHORITATIVE_DRAWING_CONTEXT")
    assert context.get("readOnly") == "1"
    assert "context-display-epsg28992-v2.geojson" in context.findtext("datasource")
    draft = next(layer for layer in layers if layer.findtext("layername") == "Study Area Draft")
    assert draft.findtext("datasource").startswith("./study-area-draft.gpkg")
    assert ".urban_design_runtime/.urban_design_runtime" not in draft.findtext("datasource")
