from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from urban_design.syntax_context_api import (
    SHIPPED_SYNTAX_CONTEXT_MANIFEST_SHA256,
    create_syntax_context_router,
    load_verified_manifest,
    load_verified_mode,
    sha256_file,
)


PROJECT_ID = "rotterdam-m4h-pilot-project"
BASE_URL = f"/api/v1/projects/{PROJECT_ID}/syntax/context"


def make_fake_run(
    tmp_path: Path,
    *,
    segments: list[dict[str, Any]] | None = None,
    max_context_m: float = 3000.0,
    corrupt_mode: bool = False,
    extra_modes: bool = False,
) -> tuple[Path, str]:
    run_dir = tmp_path / "fake-run"
    run_dir.mkdir(parents=True, exist_ok=True)

    if segments is None:
        segments = [
            {
                "id": "pedestrian:seg-1",
                "coordinates": [[89000.0, 436000.0], [89010.0, 436010.0]],
                "distance_to_site_m": 200.0,
                "inside_site": False,
                "boundary_effect_risk": False,
                "nain": 0.10,
                "nach": 0.20,
            },
            {
                "id": "pedestrian:seg-2",
                "coordinates": [[89010.0, 436010.0], [89020.0, 436020.0]],
                "distance_to_site_m": 400.0,
                "inside_site": False,
                "boundary_effect_risk": False,
                "nain": 0.30,
                "nach": 0.40,
            },
            {
                "id": "pedestrian:seg-3",
                "coordinates": [[89020.0, 436020.0], [89030.0, 436030.0]],
                "distance_to_site_m": 600.0,
                "inside_site": False,
                "boundary_effect_risk": False,
                "nain": 0.50,
                "nach": 0.60,
            },
            {
                "id": "pedestrian:seg-4",
                "coordinates": [[89030.0, 436030.0], [89040.0, 436040.0]],
                "distance_to_site_m": 1200.0,
                "inside_site": False,
                "boundary_effect_risk": True,
                "nain": 0.70,
                "nach": 0.80,
            },
            {
                "id": "pedestrian:seg-5",
                "coordinates": [[89040.0, 436040.0], [89050.0, 436050.0]],
                "distance_to_site_m": 2000.0,
                "inside_site": False,
                "boundary_effect_risk": True,
                "nain": 0.90,
                "nach": 1.00,
            },
        ]

    ped_payload = {
        "schema_version": "syntax-context-v1",
        "evidence_level": "EXPLORATORY",
        "formal_result_eligible": False,
        "engine": "PST 3.3.1",
        "formula_version": "pstalgo-3.3.1-walking-radius-v1",
        "network_mode": "pedestrian",
        "radius_m": 800.0,
        "extract_buffer_m": 1500,
        "max_context_m": max_context_m,
        "reliable_within_m": 700.0,
        "limitations": "Exploratory display only.",
        "legend_breaks": {"nain": [0.1, 0.3, 0.5, 0.7, 0.9, 0.9], "nach": [0.2, 0.4, 0.6, 0.8, 1.0, 1.0]},
        "segment_count": len(segments),
        "attribution": "© OpenStreetMap contributors (ODbL 1.0)",
        "segments": segments,
    }
    ped_file = run_dir / "syntax_context_pedestrian.json"
    ped_bytes = json.dumps(ped_payload).encode("utf-8")
    ped_file.write_bytes(ped_bytes)
    ped_sha = hashlib.sha256(ped_bytes).hexdigest()

    manifest_outputs = {
        "pedestrian": {
            "path": "syntax_context_pedestrian.json",
            "sha256": "0" * 64 if corrupt_mode else ped_sha,
            "segment_count": len(segments),
            "runtime_seconds": 0.1,
        }
    }
    if extra_modes:
        for mode_name, radius_m, reliable_within_m in (
            ("bicycle", 2000.0, 4000.0),
            ("motor_vehicle", 10000.0, 10000.0),
        ):
            payload = dict(ped_payload)
            payload.update(
                {
                    "network_mode": mode_name,
                    "radius_m": radius_m,
                    "reliable_within_m": reliable_within_m,
                    "evidence_level": "EXPLORATORY",
                    "formal_result_eligible": False,
                }
            )
            raw = json.dumps(payload).encode("utf-8")
            (run_dir / f"syntax_context_{mode_name}.json").write_bytes(raw)
            manifest_outputs[mode_name] = {
                "path": f"syntax_context_{mode_name}.json",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "segment_count": len(segments),
                "runtime_seconds": 0.1,
            }

    manifest_payload = {
        "schema_version": "syntax-context-v1",
        "created_at_utc": "2026-10-01T10:00:00Z",
        "max_context_m": max_context_m,
        "outputs": manifest_outputs,
    }
    manifest_file = run_dir / "manifest.json"
    manifest_bytes = json.dumps(manifest_payload, indent=1).encode("utf-8")
    manifest_file.write_bytes(manifest_bytes)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

    return run_dir, manifest_sha


def client_for(root: Path | None = None, manifest_sha256: str | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(create_syntax_context_router(root=root, manifest_sha256=manifest_sha256))
    return TestClient(app)


def test_syntax_context_not_configured_returns_503() -> None:
    client = client_for(None, None)
    resp = client.get(f"{BASE_URL}?mode=pedestrian&distance_m=1000")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "SYNTAX_CONTEXT_NOT_CONFIGURED"


def test_syntax_context_sha_mismatch_rejected(tmp_path: Path) -> None:
    root, _pin = make_fake_run(tmp_path)
    wrong_pin = "f" * 64

    # 1. Loading helper strictly raises ValueError on sha mismatch
    with pytest.raises(ValueError, match="manifest sha256 mismatch"):
        load_verified_manifest(root, wrong_pin)

    # 2. API client returns 503 with hash mismatch detail
    client = client_for(root, wrong_pin)
    resp = client.get(f"{BASE_URL}?mode=pedestrian&distance_m=1000")
    assert resp.status_code == 503
    assert "SYNTAX_CONTEXT_HASH_MISMATCH" in resp.json()["detail"]


def test_syntax_context_mode_unavailable_returns_404(tmp_path: Path) -> None:
    root, pin = make_fake_run(tmp_path)
    client = client_for(root, pin)

    # Mode 'bicycle' is valid schema but not generated in this fake run
    resp = client.get(f"{BASE_URL}?mode=bicycle&distance_m=1000")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "SYNTAX_CONTEXT_MODE_UNAVAILABLE"


def test_syntax_context_invalid_parameters_return_422(tmp_path: Path) -> None:
    root, pin = make_fake_run(tmp_path, max_context_m=3000.0)
    client = client_for(root, pin)

    # Unknown mode string
    resp1 = client.get(f"{BASE_URL}?mode=flying_car&distance_m=1000")
    assert resp1.status_code == 422

    # Negative distance
    resp2 = client.get(f"{BASE_URL}?mode=pedestrian&distance_m=-10")
    assert resp2.status_code == 422

    # Distance exceeding max_context_m
    resp3 = client.get(f"{BASE_URL}?mode=pedestrian&distance_m=3500")
    assert resp3.status_code == 422


def test_syntax_context_10000m_query_is_rejected_by_verified_3000m_manifest_contract(tmp_path: Path) -> None:
    root, pin = make_fake_run(tmp_path, max_context_m=3000.0)
    manifest = load_verified_manifest(root, pin)
    assert manifest["max_context_m"] == 3000.0

    client = client_for(root, pin)
    resp = client.get(f"{BASE_URL}?mode=pedestrian&distance_m=10000")

    assert resp.status_code == 422
    assert resp.json()["detail"] == "distance_m must be between 0 and 3000.0"


def test_syntax_context_distance_filtering_and_break_recalculation(tmp_path: Path) -> None:
    root, pin = make_fake_run(tmp_path)
    client = client_for(root, pin)

    # Query with distance_m = 1000
    # Expected: segments 1, 2, 3 (distances: 200, 400, 600 m <= 1000)
    resp = client.get(f"{BASE_URL}?mode=pedestrian&distance_m=1000")
    assert resp.status_code == 200
    data = resp.json()

    assert data["mode"] == "pedestrian"
    assert data["radius_m"] == 800.0
    assert data["distance_m"] == 1000.0
    assert data["reliable_within_m"] == 700.0
    assert data["evidence_level"] == "EXPLORATORY"
    readiness = data["readiness"]
    assert readiness["status"] == "BLOCKED_BOUNDARY_STABILITY_UNASSESSED"
    assert readiness["formal_result"] is False
    assert readiness["radius_m"] == 800.0
    assert readiness["manifest_sha256"] == pin
    assert readiness["bound_manifest_sha256"] == SHIPPED_SYNTAX_CONTEXT_MANIFEST_SHA256
    assert readiness["bound_manifest_sha256"] == "a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1"
    assert readiness["manifest_binding"] == "UNBOUND_MANIFEST"
    assert pin in readiness["reason"]
    assert "PASS" not in readiness["status"]
    assert data["segment_count"] == 3
    assert len(data["segments"]) == 3
    assert [s["id"] for s in data["segments"]] == ["pedestrian:seg-1", "pedestrian:seg-2", "pedestrian:seg-3"]

    # Breaks recalculated for 3 values [0.1, 0.3, 0.5]
    nain_breaks = data["legend_breaks"]["nain"]
    assert len(nain_breaks) == 6
    assert nain_breaks[0] == 0.1  # min
    assert nain_breaks[-1] == 0.5  # max

    nach_breaks = data["legend_breaks"]["nach"]
    assert len(nach_breaks) == 6
    assert nach_breaks[0] == 0.2  # min
    assert nach_breaks[-1] == 0.6  # max

    # Query with distance_m = 2500 -> all 5 segments
    resp_all = client.get(f"{BASE_URL}?mode=pedestrian&distance_m=2500")
    assert resp_all.status_code == 200
    data_all = resp_all.json()
    assert data_all["segment_count"] == 5
    assert len(data_all["segments"]) == 5
    assert data_all["legend_breaks"]["nain"][0] == 0.1
    assert data_all["legend_breaks"]["nain"][-1] == 0.9


def test_syntax_context_corrupt_mode_file_returns_503(tmp_path: Path) -> None:
    root, pin = make_fake_run(tmp_path, corrupt_mode=True)
    client = client_for(root, pin)

    resp = client.get(f"{BASE_URL}?mode=pedestrian&distance_m=1000")
    assert resp.status_code == 503
    assert "SYNTAX_CONTEXT_CORRUPT" in resp.json()["detail"]


def test_radius_readiness_labels_are_not_formal(tmp_path: Path) -> None:
    root, pin = make_fake_run(tmp_path, extra_modes=True)
    client = client_for(root, pin)
    expected = {
        "pedestrian": ("BLOCKED_BOUNDARY_STABILITY_UNASSESSED", 800.0),
        "bicycle": ("EXPLORATORY", 2000.0),
        "motor_vehicle": ("EXPLORATORY", 10000.0),
    }
    for mode, (status, radius_m) in expected.items():
        resp = client.get(f"{BASE_URL}?mode={mode}&distance_m=1000")
        assert resp.status_code == 200, resp.text
        readiness = resp.json()["readiness"]
        assert readiness["mode"] == mode
        assert readiness["status"] == status
        assert readiness["radius_m"] == radius_m
        assert readiness["formal_result"] is False
        assert readiness["manifest_sha256"] == pin
        assert pin in readiness["reason"]
        assert readiness["status"] not in {"PASS", "FORMAL", "VALIDATED"}


def test_shipped_manifest_readiness_stays_blocked_or_exploratory() -> None:
    real_run = Path.home() / ".local/share/urban-design-data/syntax-context/run-20261001T105231Z"
    if not real_run.is_dir():
        pytest.skip(f"Shipped syntax context run not found: {real_run}")

    pin = sha256_file(real_run / "manifest.json")
    assert pin == "a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1"
    assert pin == SHIPPED_SYNTAX_CONTEXT_MANIFEST_SHA256
    client = client_for(real_run, pin)
    expected = {
        "pedestrian": ("BLOCKED_BOUNDARY_STABILITY_UNASSESSED", 800.0),
        "bicycle": ("EXPLORATORY", 2000.0),
        "motor_vehicle": ("EXPLORATORY", 10000.0),
    }
    for mode, (status, radius_m) in expected.items():
        resp = client.get(f"{BASE_URL}?mode={mode}&distance_m=100")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["radius_m"] == radius_m
        readiness = body["readiness"]
        assert readiness["status"] == status
        assert readiness["formal_result"] is False
        assert readiness["manifest_sha256"] == pin
        assert readiness["manifest_binding"] == "SHIPPED"
        assert pin in readiness["reason"]
        assert "PASS" not in readiness["status"]


def test_real_commander_pedestrian_run() -> None:
    real_run = Path.home() / ".local/share/urban-design-data/syntax-context/run-20261001T105212Z"
    if not real_run.is_dir():
        pytest.skip(f"Real run not found: {real_run}")

    manifest_file = real_run / "manifest.json"
    assert manifest_file.is_file()
    pin = sha256_file(manifest_file)

    client = client_for(real_run, pin)
    resp = client.get(f"{BASE_URL}?mode=pedestrian&distance_m=1000")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "pedestrian"
    assert data["radius_m"] == 800.0
    assert data["reliable_within_m"] == 700.0
    assert data["evidence_level"] == "EXPLORATORY"
    assert data["segment_count"] > 0
    assert all(s["distance_to_site_m"] <= 1000.0 for s in data["segments"])


def test_disabled_capability_is_readable_without_requesting_context():
    app = FastAPI()
    app.include_router(create_syntax_context_router())
    response = TestClient(app).get(BASE_URL + '/capabilities')
    assert response.status_code == 200
    assert response.json()['enabled'] is False
    assert response.json()['status'] == 'NOT_CONFIGURED'
    assert '未啟用' in response.json()['reason_zh']


def test_verified_capability_reports_available_modes(tmp_path):
    root, manifest_hash = make_fake_run(tmp_path)
    app = FastAPI()
    app.include_router(create_syntax_context_router(root, manifest_hash))
    result = TestClient(app).get(BASE_URL + '/capabilities').json()
    assert result['enabled'] is True
    assert result['modes'] == ['pedestrian']
