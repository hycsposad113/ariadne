"""R03 checks for same-revision, source-aligned observational Evidence Cards."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from urban_design.store import ProjectStateStore
from urban_design.workspace_sources import WorkspaceSourceCatalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPATIAL_R01_ROOT = PROJECT_ROOT / (
    "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
)
LIVE_DATABASE = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")


def _read_only_copy(tmp_path: Path) -> ProjectStateStore:
    target = tmp_path / "state.sqlite3"
    with sqlite3.connect(f"file:{LIVE_DATABASE}?mode=ro", uri=True) as source:
        source.execute("PRAGMA query_only=ON")
        with sqlite3.connect(target) as destination:
            source.backup(destination)
    return ProjectStateStore(target)


def _bundle(tmp_path: Path):
    from urban_design.r03_evidence import build_observational_evidence_bundle

    store = _read_only_copy(tmp_path)
    catalog = WorkspaceSourceCatalog.load(store, SPATIAL_R01_ROOT)
    bundle = build_observational_evidence_bundle(catalog, store)
    return store, catalog, bundle


def test_r03_bundle_contains_source_aligned_observations_and_explicit_gaps(tmp_path):
    from urban_design.r03_evidence import validate_observational_evidence_bundle

    store, catalog, bundle = _bundle(tmp_path)
    try:
        cards = validate_observational_evidence_bundle(bundle, catalog, store)
        assert len(cards) >= 4
        assert {card["status"] for card in cards} == {"SOURCE_ALIGNED_COVERAGE_LIMITED"}
        assert {card["crs"] for card in cards} == {"EPSG:28992"}
        assert all(card["source_artifact_ids"] and card["dataset_snapshot_ids"] for card in cards)
        assert all(card["query_bounds"] and card["algorithm_version"] for card in cards)
        assert all(card["input_sha256"].startswith("sha256:") for card in cards)
        assert all(card["output_sha256"].startswith("sha256:") for card in cards)
        assert {gap["status"] for gap in bundle["evidence_gaps"]} == {"UNKNOWN", "BLOCKED"}
        assert any("ownership" in gap["topic"].lower() for gap in bundle["evidence_gaps"])
        assert bundle["scope"]["study_area_revision"] == 1
        assert bundle["scope"]["source_package_revision"] == "spatial-r01"
    finally:
        store.close()


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda b: b["scope"].__setitem__("source_package_id", "week4-baseline"), "source package"),
        (lambda b: b["scope"].__setitem__("study_area_revision", 2), "revision"),
        (lambda b: b["cards"][0]["source_artifact_ids"].pop(), "parent"),
        (lambda b: b["cards"][0].__setitem__("unit", "invented-unit"), "unit"),
    ],
)
def test_r03_card_bundle_fails_closed_on_misalignment(tmp_path, mutate, match):
    from urban_design.r03_evidence import EvidenceAlignmentError, validate_observational_evidence_bundle

    store, catalog, bundle = _bundle(tmp_path)
    try:
        damaged = json.loads(json.dumps(bundle))
        mutate(damaged)
        with pytest.raises(EvidenceAlignmentError, match=match):
            validate_observational_evidence_bundle(damaged, catalog, store)
    finally:
        store.close()


def test_frozen_r03_bundle_validates_without_relabeling_legacy_cards(tmp_path):
    from urban_design.r03_evidence import select_verified_cards, validate_observational_evidence_bundle

    store = _read_only_copy(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, SPATIAL_R01_ROOT)
        frozen_path = PROJECT_ROOT / "artifacts/week4-repair-r03/evidence-bundle.json"
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))

        cards = validate_observational_evidence_bundle(frozen, catalog, store)

        assert cards == frozen["cards"]
        assert {card["status"] for card in cards} == {"VERIFIED_OBSERVATION"}
        assert select_verified_cards(cards, [cards[0]["card_id"]]) == [cards[0]]
    finally:
        store.close()


def test_r03_card_selector_rejects_unknown_and_duplicate_ids(tmp_path):
    from urban_design.r03_evidence import EvidenceAlignmentError, select_verified_cards

    store, catalog, bundle = _bundle(tmp_path)
    try:
        cards = bundle["cards"]
        with pytest.raises(EvidenceAlignmentError, match="unverified"):
            select_verified_cards(cards, ["fabricated-card-id"])
        with pytest.raises(EvidenceAlignmentError, match="duplicate"):
            select_verified_cards(cards, [cards[0]["card_id"], cards[0]["card_id"]])
    finally:
        store.close()


def test_api_serves_only_validated_cards_and_does_not_dispatch_live_ai(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import urban_design.api as api

    store = _read_only_copy(tmp_path)
    app = api.create_workspace_app(store, source_package_root=SPATIAL_R01_ROOT)
    client = TestClient(app)
    context = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/site-context")
    assert context.status_code == 200, context.text
    data = context.json()
    assert data["evidence_cards_status"] == "VERIFIED_SOURCE_RESULT_ALIGNMENT"
    cards = data["evidence_cards"]
    assert len(cards) >= 4
    assert all(card["status"] == "VERIFIED_OBSERVATION" for card in cards)

    class FakeProvider:
        provider_name = "r03-fake-transport"
        status = "FAKE_TRANSPORT_TEST"
        is_live_available = False

        def generate_criticism(self, request):
            return {
                "critic_id": "critic-r03-test",
                "study_area_id": request.study_area_id,
                "evidence_refs": [cards[0]["card_id"]],
                "observations": ["The selected card reports a source-backed observation."],
                "design_hypotheses": ["A designer may test a related spatial hypothesis."],
                "limitations": ["This fake response is not a live model result."],
                "next_questions": [],
                "provider_status": "FAKE_TRANSPORT_TEST",
                "provider_name": self.provider_name,
            }

    monkeypatch.setattr(api, "get_configured_provider", lambda: FakeProvider())
    req = {
        "prompt": "Describe the observed footprint coverage.",
        "evidence_card_ids": [cards[0]["card_id"]],
        "expected_study_area_id": data["study_area"]["id"],
        "expected_study_area_revision": data["study_area"]["revision"],
        "expected_source_package_revision": data["source_package_revision"],
        "expected_evidence_bundle_sha256": data["evidence_bundle_sha256"],
        "expected_workspace_id": data["current_workspace"]["workspace_id"],
        "expected_workspace_revision": data["current_workspace"]["revision"],
    }
    workspace_revision_before = store.current("workspace-rotterdam-m4h-pilot-project").revision
    response = client.post("/api/v1/critic/evaluate", json=req)
    assert response.status_code == 200, response.text
    assert response.json()["evidence_refs"] == [cards[0]["card_id"]]
    bad = {**req, "evidence_card_ids": ["fabricated-card-id"]}
    assert client.post("/api/v1/critic/evaluate", json=bad).status_code == 422
    stale = {**req, "expected_study_area_revision": 2}
    assert client.post("/api/v1/critic/evaluate", json=stale).status_code == 422
    assert store.current("workspace-rotterdam-m4h-pilot-project").revision == workspace_revision_before
    store.close()
