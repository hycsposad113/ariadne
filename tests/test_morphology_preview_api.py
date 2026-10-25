from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from urban_design.morphology.preview_api import create_preview_router
from scripts.preview_catalog_demo import create_demo_app
from test_preview_catalog import make_bundle, reseal


BASE = "/api/v1/morphology/previews"


def client_for(root: Path | None = None, manifest_sha256: str | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(create_preview_router(root=root, manifest_sha256=manifest_sha256))
    return TestClient(app)


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_disabled_catalog_is_explicit_and_routes_are_get_only() -> None:
    client = client_for()

    response = client.get(BASE)

    assert response.status_code == 200
    assert response.json()["status"] == "DISABLED"
    assert response.json()["verified_at_utc"] is None
    assert response.json()["source_reverified"] is False
    assert response.json()["previews"] == []
    app_routes = create_preview_router().routes
    assert app_routes
    assert all(route.methods == {"GET"} for route in app_routes)
    assert client.post(BASE).status_code == 405


def test_catalog_detail_and_assets_are_read_only_and_do_not_expose_host_paths(tmp_path: Path) -> None:
    root, pin = make_bundle(tmp_path / "bundle")
    before = tree_hashes(root)
    client = client_for(root, pin)

    response = client.get(BASE)
    assert response.status_code == 200
    listing = response.json()
    assert listing["status"] == "AVAILABLE"
    assert listing["source_reverified"] is False
    assert listing["verified_at_utc"].endswith("Z")
    assert listing["count"] == 2
    assert [item["identity"]["intensity"] for item in listing["previews"]].count("A") == 1
    assert [item["identity"]["intensity"] for item in listing["previews"]].count("B") == 1

    detail = client.get(f"{BASE}/A/perimeter_block_city")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["source_reverified"] is False
    assert payload["verified_at_utc"] == listing["verified_at_utc"]
    assert payload["identity"]["status"] == "UNAPPROVED_PREVIEW"
    assert payload["identity"]["human_decision_created"] is False
    assert payload["identity"]["run_created_at"] is None
    assert payload["identity"]["generator_commit"] is None
    assert payload["retained_buildings"][0]["floor_estimate_status"] == "UNKNOWN"
    assert payload["metrics"]["known_part_land_far"] == 1.25
    assert "/private/host" not in response.text + detail.text
    assert "recipe_path" not in payload

    image = client.get(f"{BASE}/A/perimeter_block_city/assets/plan")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content == (root / "A/perimeter_block_city/plan.png").read_bytes()
    assert image.headers["etag"].strip('"') == hashlib.sha256(image.content).hexdigest()
    assert client.get(f"{BASE}/A/not_a_strategy").status_code == 404
    assert client.get(f"{BASE}/A/perimeter_block_city/assets/filename").status_code == 404
    assert client.post(f"{BASE}/A/perimeter_block_city").status_code == 405
    assert tree_hashes(root) == before


def test_configured_missing_or_corrupt_bundle_is_not_an_empty_catalog(tmp_path: Path, caplog) -> None:
    missing_root = tmp_path / "missing"
    response = client_for(missing_root, "a" * 64).get(BASE)
    assert response.status_code == 503
    assert "missing_file" in response.json()["detail"]
    assert "category=missing_file" in caplog.text
    assert str(tmp_path) not in caplog.text

    root, pin = make_bundle(tmp_path / "corrupt")
    (root / "comparison.json").unlink()
    response = client_for(root, pin).get(BASE)
    assert response.status_code == 503
    assert "missing_file" in response.json()["detail"]


def test_invalid_bundle_503_detail_reports_a_safe_error_category(tmp_path: Path, caplog) -> None:
    root, pin = make_bundle(tmp_path / "wrong-pin")

    response = client_for(root, "0" * 64).get(BASE)

    assert response.status_code == 503
    assert "hash_mismatch" in response.json()["detail"]
    assert "category=hash_mismatch" in caplog.text
    assert str(root) not in caplog.text


def test_invalid_schema_503_detail_reports_schema_error(tmp_path: Path) -> None:
    root, _ = make_bundle(tmp_path / "bad-schema")
    comparison_path = root / "comparison.json"
    comparison = json.loads(comparison_path.read_text())
    comparison["schema_version"] = "unsupported-v9"
    comparison_path.write_text(json.dumps(comparison))

    response = client_for(root, reseal(root)).get(BASE)

    assert response.status_code == 503
    assert "schema_error" in response.json()["detail"]


def test_demo_allows_only_loopback_origins_for_the_browser_fixture() -> None:
    client = TestClient(create_demo_app(None, None))

    local = client.get(BASE, headers={"Origin": "http://127.0.0.1:62585"})
    remote = client.get(BASE, headers={"Origin": "https://example.invalid"})

    assert local.status_code == 200
    assert local.headers["access-control-allow-origin"] == "http://127.0.0.1:62585"
    assert "access-control-allow-origin" not in remote.headers
