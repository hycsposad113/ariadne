"""Tests for climate extras router endpoints (W8, 2026-10-17)."""

from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore


@pytest.fixture
def test_client(tmp_path: Path) -> tuple[TestClient, Path]:
    store = ProjectStateStore(tmp_path / "test.sqlite3")
    app = create_workspace_app(store=store)
    client = TestClient(app)
    return client, app.state.climate_artifact_root if hasattr(app.state, "climate_artifact_root") else Path(__file__).resolve().parents[1] / "artifacts" / "w8"


def test_list_climate_extras_default_success(test_client: tuple[TestClient, Path]) -> None:
    client, root = test_client
    response = client.get("/api/v1/environment/climate-extras")
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 5

    section_ids = [s["id"] for s in data]
    assert section_ids == ["e1-fabric", "utci", "e3-energy", "e4-thermal-mass", "e5-cfd"]

    for sec in data:
        assert "探索性，非認證" in sec["label_zh"]
        assert "Exploratory, not certification" in sec["label_en"]
        assert sec["status"] == "OK"
        assert sec["missing_files"] == []
        assert "limitations_zh" in sec and len(sec["limitations_zh"]) > 0
        assert "limitations_en" in sec and len(sec["limitations_en"]) > 0
        assert isinstance(sec["source_sha256"], dict)
        assert len(sec["source_sha256"]) > 0

    # E1 specifics
    e1 = data[0]
    assert len(e1["figures"]) == 3
    assert e1["table"] is not None
    assert len(e1["table"]["columns"]) > 0
    assert len(e1["table"]["rows"]) > 0
    selected_e1 = [r for r in e1["table"]["rows"] if r.get("is_selected")]
    assert len(selected_e1) > 0
    assert selected_e1[0]["紋理方案代碼"] == "harbour_grain"

    # UTCI specifics
    utci = data[1]
    assert len(utci["figures"]) == 4
    assert utci["table"] is not None
    assert any(r.get("is_selected") for r in utci["table"]["rows"])

    # E3 specifics
    e3 = data[2]
    assert len(e3["figures"]) == 1
    assert e3["table"] is not None
    assert any(r.get("is_selected") for r in e3["table"]["rows"])

    # E4 specifics
    e4 = data[3]
    assert len(e4["figures"]) == 1
    assert e4["table"] is not None
    assert len(e4["table"]["rows"]) == 3

    # E5 specifics
    e5 = data[4]
    assert len(e5["figures"]) == 6
    assert e5["table"] is not None
    assert len(e5["table"]["rows"]) == 4
    assert "Commander 審查補充" in e5["limitations_zh"]
    assert "Lawson 概估圖不採用" in e5["limitations_zh"]


def test_missing_files_returns_missing_status(tmp_path: Path) -> None:
    empty_root = tmp_path / "empty_artifacts"
    empty_root.mkdir()
    # Create partial directory structure with some missing files
    (empty_root / "e1-fabric").mkdir()

    store = ProjectStateStore(tmp_path / "test_missing.sqlite3")
    app = create_workspace_app(store=store, climate_artifact_root=empty_root)
    client = TestClient(app)

    response = client.get("/api/v1/environment/climate-extras")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 5

    for sec in data:
        assert sec["status"] == "MISSING"
        assert len(sec["missing_files"]) > 0
        assert sec["table"] is None
        assert sec["figures"] == []


def test_get_file_success(test_client: tuple[TestClient, Path]) -> None:
    client, _ = test_client
    resp = client.get("/api/v1/environment/climate-extras/files/e1-fabric/comparison_table.csv")
    assert resp.status_code == 200
    assert "紋理方案代碼" in resp.text
    assert resp.headers["content-type"].startswith("text/csv")

    resp_img = client.get("/api/v1/environment/climate-extras/files/e3e4-final/e3_eui_by_fabric.png")
    assert resp_img.status_code == 200
    assert resp_img.headers["content-type"] == "image/png"


def test_get_file_path_traversal_blocked(test_client: tuple[TestClient, Path]) -> None:
    client, _ = test_client

    # Dot-dot traversal
    resp1 = client.get("/api/v1/environment/climate-extras/files/e1-fabric/../../something.csv")
    assert resp1.status_code == 404

    # Percent-encoded dot-dot traversal
    resp2 = client.get("/api/v1/environment/climate-extras/files/e1-fabric/%2e%2e/e1-fabric/comparison_table.csv")
    assert resp2.status_code == 404

    # Absolute path attempts
    resp3 = client.get("/api/v1/environment/climate-extras/files//etc/passwd")
    assert resp3.status_code == 404


def test_get_file_disallowed_extension(test_client: tuple[TestClient, Path]) -> None:
    client, _ = test_client
    resp = client.get("/api/v1/environment/climate-extras/files/e1-fabric/comparison_table.py")
    assert resp.status_code == 404


def test_get_file_disallowed_directory(test_client: tuple[TestClient, Path]) -> None:
    client, _ = test_client
    resp = client.get("/api/v1/environment/climate-extras/files/demo/something.json")
    assert resp.status_code == 404


def test_get_nonexistent_file(test_client: tuple[TestClient, Path]) -> None:
    client, _ = test_client
    resp = client.get("/api/v1/environment/climate-extras/files/e1-fabric/nonexistent_file.csv")
    assert resp.status_code == 404


def test_english_figure_requires_registered_hash_pair(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    e1_dir, utci_dir = root / "e1-fabric", root / "utci"
    e1_dir.mkdir(parents=True)
    utci_dir.mkdir(parents=True)

    zh_path = "e1-fabric/e1-compare-20261221-冬至-zh.png"
    en_path = "e1-fabric/e1-compare-20261221-winter-solstice-en.png"
    (e1_dir / "comparison_table.csv").write_text("field\n", encoding="utf-8")
    (e1_dir / Path(zh_path).name).write_bytes(b"zh-figure")
    (e1_dir / Path(en_path).name).write_bytes(b"en-figure")
    utci_zh_path = "utci/harbour_grain_utci_1400.png"
    utci_en_path = "utci/harbour_grain_utci_1400-en.png"
    (utci_dir / Path(utci_en_path).name).write_bytes(b"en-utci")
    for filename in (
        "e1-compare-20260321-春分-zh.png",
        "e1-compare-20260621-夏至-zh.png",
    ):
        (e1_dir / filename).write_bytes(b"zh-figure")
    (utci_dir / "utci_stress_hours_comparison.json").write_text('{"fabrics": {}}', encoding="utf-8")
    for fabric in ("harbour_grain", "closed_block_extension", "courtyard_islands", "landscape_figure"):
        (utci_dir / f"{fabric}_utci_1400.png").write_bytes(b"zh-utci")

    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    en_file, zh_file = root / en_path, root / zh_path
    registry = {
        "manifest_version": "1.0.0",
        "language": "en",
        "files": {
            en_path: {
                "zh_counterpart": zh_path,
                "sha256": digest(en_file),
                "zh_sha256": digest(zh_file),
            },
            utci_en_path: {
                "zh_counterpart": utci_zh_path,
                "sha256": digest(root / utci_en_path),
                "zh_sha256": digest(root / utci_zh_path),
            },
        },
    }
    (root / "english-figures-manifest.json").write_text(json.dumps(registry), encoding="utf-8")

    store = ProjectStateStore(tmp_path / "test_english.sqlite3")
    app = create_workspace_app(store=store, climate_artifact_root=root)
    client = TestClient(app)

    listed = client.get("/api/v1/environment/climate-extras")
    assert listed.status_code == 200
    e1 = listed.json()[0]
    winter = e1["figures"][0]
    assert winter["path"] == zh_path
    assert winter["path_en"] == en_path
    assert e1["source_sha256"][en_path] == digest(en_file)
    assert "english-figures-manifest.json" in e1["source_sha256"]
    assert e1["figures"][1]["path_en"] is None
    utci = listed.json()[1]
    assert utci["figures"][0]["path_en"] == utci_en_path
    assert utci["source_sha256"][utci_en_path] == digest(root / utci_en_path)

    served = client.get(f"/api/v1/environment/climate-extras/files/{en_path}")
    assert served.status_code == 200
    assert served.content == b"en-figure"
    served_utci = client.get(f"/api/v1/environment/climate-extras/files/{utci_en_path}")
    assert served_utci.status_code == 200
    assert served_utci.content == b"en-utci"

    zh_file.write_bytes(b"replaced-zh-figure")
    relisted = client.get("/api/v1/environment/climate-extras")
    assert relisted.status_code == 200
    assert relisted.json()[0]["figures"][0]["path_en"] is None
    assert client.get(f"/api/v1/environment/climate-extras/files/{en_path}").status_code == 404
