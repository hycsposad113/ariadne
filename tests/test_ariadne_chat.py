from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.model_provider import CriticRequest, ModelProviderRouter, ProjectStateModelRunAccounting
from urban_design.site_critic import SiteCriticService
from urban_design.store import ProjectStateStore


PROJECT_ID = "project-ariadne-test"
CARD_ID = "card-verified-site-metric"


def _context() -> dict:
    return {
        "project_id": PROJECT_ID,
        "study_area_id": "study-area-test-v1",
        "evidence_cards_status": "VERIFIED_SOURCE_RESULT_ALIGNMENT",
        "evidence_cards": [
            {
                "card_id": CARD_ID,
                "metric_name": "Verified building features",
                "value": 12,
                "unit": "features",
                "status": "SOURCE_ALIGNED_COVERAGE_LIMITED",
                "limitations": ["Mapped coverage may be incomplete."],
            }
        ],
        "problems": [
            {"problem_id": "prob-test-access", "title": "Access needs review", "status": "DRAFT"}
        ],
        "syntax_layers": [
            {"layer_id": "syntax-test-local", "title": "Local Syntax", "calculation_status": "NOT_COMPUTED"}
        ],
        "workspace": {
            "workspace_id": "workspace-project-ariadne-test",
            "revision": 1,
            "status": "DRAFT",
            "spatial_brief": {"status": "DRAFT_PENDING_HUMAN_DECISION"},
        },
    }


class _RecordingProvider:
    provider_name = "fixture-provider"
    status = "LIVE_AI: CONFIGURED_NOT_CALLED"
    is_live_available = True
    profile = SimpleNamespace(model="fixture-model", adapter="fixture")

    def __init__(self, response: dict):
        self.response = response
        self.calls = 0

    def generate_criticism(self, _request):
        self.calls += 1
        return dict(self.response)


def _response(*, status: str = "LIVE_AI: ACTIVE", refs: list[str] | None = None, metadata: dict | None = None) -> dict:
    return {
        "critic_id": "critic-ariadne-test",
        "study_area_id": "study-area-test-v1",
        "evidence_refs": refs if refs is not None else [CARD_ID],
        "observations": ["The saved site evidence is linked [card-verified-site-metric]."] if status == "LIVE_AI: ACTIVE" else [],
        "design_hypotheses": [],
        "limitations": [],
        "next_questions": [],
        "provider_status": status,
        "provider_name": "fixture-provider",
        "provider_profile_id": "ariadne-fixture",
        "provider_model": "fixture-model",
        "provider_metadata": metadata or {},
    }


def _client(
    tmp_path: Path,
    *,
    live_enabled: bool = False,
    provider_factory=None,
    context: dict | None = None,
    authority: ProjectStateStore | None = None,
) -> tuple[TestClient, ProjectStateStore, Path]:
    authority_path = tmp_path / "authority.sqlite3"
    authority = authority or ProjectStateStore(authority_path)
    chat_path = tmp_path / "ariadne-chat.sqlite3"

    from urban_design.ariadne_chat import create_ariadne_chat_router

    app = FastAPI()
    app.include_router(
        create_ariadne_chat_router(
            project_store=authority,
            source_catalog=None,
            chat_database=chat_path,
            context_loader=lambda _project_id: context or _context(),
            provider_factory=provider_factory,
            live_enabled=live_enabled,
        )
    )
    return TestClient(app), authority, chat_path


def test_unapproved_mode_uses_offline_evidence_and_never_calls_provider(tmp_path):
    calls = []
    client, _authority, _chat_path = _client(
        tmp_path,
        provider_factory=lambda *_args: calls.append("provider-created"),
    )

    status = client.get(f"/api/v1/projects/{PROJECT_ID}/ariadne/status")
    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Summarize the verified site evidence."},
    )

    assert status.status_code == 200
    assert status.json()["mode"] == "OFFLINE"
    assert status.json()["block_reason_code"] == "BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED"
    assert result.status_code == 200
    assistant = result.json()["assistant_message"]
    assert assistant["provider_status"] == "NON_AI: DETERMINISTIC_TEMPLATE"
    assert CARD_ID in assistant["evidence_refs"]
    assert f"[{CARD_ID}]" in assistant["content"]
    assert "12 features" in assistant["content"]
    assert "prob-test-access" in assistant["evidence_refs"]
    assert "syntax-test-local" in assistant["evidence_refs"]
    assert calls == []


def test_live_flag_still_requires_project_authorization(tmp_path, monkeypatch):
    monkeypatch.delenv("PROJECT_AI_AUTHORIZED", raising=False)
    calls = []
    client, _authority, _chat_path = _client(
        tmp_path,
        live_enabled=True,
        provider_factory=lambda *_args: calls.append("provider-created"),
    )

    status = client.get(f"/api/v1/projects/{PROJECT_ID}/ariadne/status")
    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Summarize the verified site evidence."},
    )

    assert status.json()["block_reason_code"] == "BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED"
    assert result.status_code == 200
    assert result.json()["assistant_message"]["provider_status"] == "NON_AI: DETERMINISTIC_TEMPLATE"
    assert calls == []


def test_offline_syntax_mean_is_rendered_from_its_cited_layer(tmp_path):
    context = _context()
    context["syntax_status"] = "VERIFIED"
    context["syntax_layers"] = [
        {
            "layer_id": "syntax-test-local",
            "title": "Local Integration",
            "calculation_status": "COMPUTED",
            "unit": "index",
            "statistics": {"mean": 0.47},
        }
    ]
    client, _authority, _chat_path = _client(tmp_path, context=context)

    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Summarize the Syntax result."},
    )

    assistant = result.json()["assistant_message"]
    assert assistant["provider_status"] == "NON_AI: DETERMINISTIC_TEMPLATE"
    assert "Local Integration mean: 0.47 index [syntax-test-local]." in assistant["content"]
    assert "syntax-test-local" in assistant["evidence_refs"]


def test_offline_answer_uses_english_and_selects_the_footprint_evidence(tmp_path):
    context = _context()
    context["evidence_cards"] = [
        {"card_id": "card-footprint", "metric_name": "Building footprint area", "value": 1234.5, "unit": "m2", "status": "VERIFIED_OBSERVATION", "limitations": []},
        {"card_id": "card-water", "metric_name": "Mapped water features", "value": 800, "unit": "features", "status": "VERIFIED_OBSERVATION", "limitations": []},
        {"card_id": "card-road", "metric_name": "Road length", "value": 420, "unit": "m", "status": "VERIFIED_OBSERVATION", "limitations": []},
    ]
    client, _authority, _chat_path = _client(tmp_path, context=context)

    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "What is the building footprint area?", "language": "en"},
    )

    assistant = result.json()["assistant_message"]
    assert "Relevant current evidence:" in assistant["content"]
    assert "Building footprint area: 1,235 m² [card-footprint]." in assistant["content"]
    assert assistant["evidence_refs"] == ["card-footprint"]
    assert "card-water" not in assistant["evidence_refs"]
    assert "即時 AI" not in assistant["content"]


def test_offline_answer_uses_traditional_chinese_template_and_water_keywords(tmp_path):
    context = _context()
    context["evidence_cards"] = [
        {"card_id": "card-water", "metric_name": "Water area", "value": 1234.5, "unit": "m²", "status": "VERIFIED_OBSERVATION", "limitations": []},
        {"card_id": "card-road", "metric_name": "Road length", "value": 420, "unit": "m", "status": "VERIFIED_OBSERVATION", "limitations": []},
    ]
    client, _authority, _chat_path = _client(tmp_path, context=context)

    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "水域面積是多少？", "language": "zh-TW"},
    )

    assistant = result.json()["assistant_message"]
    assert "以下是與問題相關的目前證據：" in assistant["content"]
    assert "Water area：1,235 m² [card-water]。" in assistant["content"]
    assert assistant["evidence_refs"] == ["card-water"]
    assert "card-road" not in assistant["evidence_refs"]
    assert "即時 AI 尚未啟用" in assistant["content"]
    assert "Live AI is not enabled" not in assistant["content"]


def test_offline_chinese_feature_counts_use_the_localized_counter(tmp_path):
    context = _context()
    context["evidence_cards"] = [
        {
            "card_id": "card-building-count",
            "metric_name": "BAG building footprint features",
            "value": 51,
            "unit": "features",
            "status": "VERIFIED_OBSERVATION",
            "limitations": [],
        }
    ]
    client, _authority, _chat_path = _client(tmp_path, context=context)

    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "建築基底有幾筆？", "language": "zh-TW"},
    )

    assistant = result.json()["assistant_message"]
    assert "51 筆 [card-building-count]" in assistant["content"]
    assert "51 features" not in assistant["content"]
    assert assistant["evidence_refs"] == ["card-building-count"]


def test_offline_chinese_road_question_matches_bilingual_problem_titles(tmp_path):
    context = _context()
    context["evidence_cards"] = []
    context["problems"] = [
        {"problem_id": "prob-street", "title": "街道通行問題", "title_zh": "街道通行問題", "title_en": "Street access issue", "status": "NEEDS_REVIEW"},
        {"problem_id": "prob-water", "title": "水域使用問題", "title_zh": "水域使用問題", "title_en": "Water use issue", "status": "NEEDS_REVIEW"},
    ]
    client, _authority, _chat_path = _client(tmp_path, context=context)

    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "街道問題要檢視什麼？", "language": "zh-TW"},
    )

    assistant = result.json()["assistant_message"]
    assert assistant["evidence_refs"] == ["prob-street"]
    assert "已定義問題：街道通行問題" in assistant["content"]
    assert "prob-water" not in assistant["evidence_refs"]


def test_offline_answer_selects_relevant_problems_and_at_most_three_sources(tmp_path):
    context = _context()
    context["evidence_cards"] = [
        {"card_id": f"card-road-{index}", "metric_name": f"Road network section {index}", "value": index, "unit": "features", "status": "VERIFIED_OBSERVATION", "limitations": []}
        for index in range(1, 5)
    ] + [
        {"card_id": "card-water", "metric_name": "Water area", "value": 17, "unit": "m2", "status": "VERIFIED_OBSERVATION", "limitations": []}
    ]
    context["problems"] = [
        {"problem_id": "prob-road", "title": "Road crossings need review", "title_en": "Road crossings need review", "status": "DRAFT"},
        {"problem_id": "prob-water", "title": "Water access needs review", "title_en": "Water access needs review", "status": "DRAFT"},
    ]
    client, _authority, _chat_path = _client(tmp_path, context=context)

    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "What road problems need review?", "language": "en"},
    )

    assistant = result.json()["assistant_message"]
    assert len(assistant["evidence_refs"]) == 3
    assert "prob-road" in assistant["evidence_refs"]
    assert "prob-water" not in assistant["evidence_refs"]
    assert "card-water" not in assistant["evidence_refs"]
    assert all(f"[{reference}]" in assistant["content"] for reference in assistant["evidence_refs"])


def test_offline_answer_rounds_area_and_ratio_units_and_keeps_citations(tmp_path):
    context = _context()
    context["evidence_cards"] = [
        {"card_id": "card-area", "metric_name": "Footprint area", "value": 1234.5, "unit": "m2", "status": "VERIFIED_OBSERVATION", "limitations": []},
        {"card_id": "card-ratio", "metric_name": "Coverage ratio", "value": 0.456, "unit": "ratio", "status": "VERIFIED_OBSERVATION", "limitations": []},
        {"card_id": "card-percent", "metric_name": "Area share", "value": 12.34, "unit": "%", "status": "VERIFIED_OBSERVATION", "limitations": []},
    ]
    client, _authority, _chat_path = _client(tmp_path, context=context)

    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Give me the footprint area figures."},
    )

    assistant = result.json()["assistant_message"]
    assert "1,235 m² [card-area]" in assistant["content"]
    assert "0.5 ratio [card-ratio]" in assistant["content"]
    assert "12.3% [card-percent]" in assistant["content"]
    assert assistant["evidence_refs"] == ["card-area", "card-ratio", "card-percent"]


def test_live_send_records_model_run_in_shared_project_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    recording = _RecordingProvider(_response())
    routers = []

    def provider_factory(store, project_id):
        router = ModelProviderRouter(
            providers={"ariadne-fixture": recording},
            fallback_order=["ariadne-fixture"],
            store=store,
            project_id=project_id,
            weekly_call_limit=200,
        )
        routers.append(router)
        return router

    client, authority, chat_path = _client(tmp_path, live_enabled=True, provider_factory=provider_factory)
    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Explain the verified evidence."},
    )

    chat_store = ProjectStateStore(chat_path)
    runs = authority.list_current("ModelRun", project_id=PROJECT_ID)
    assert result.status_code == 200
    assert result.json()["assistant_message"]["provider_status"] == "LIVE_AI: ACTIVE"
    assert recording.calls == 1
    assert len(runs) == 1
    assert runs[0].payload["status"] == "SUCCEEDED"
    assert chat_store.list_current("ModelRun", project_id=PROJECT_ID) == []
    assert routers[0].weekly_call_limit == 200
    chat_store.close()


def test_site_critic_and_ariadne_share_the_same_weekly_model_run_count(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    authority = ProjectStateStore(tmp_path / "authority.sqlite3")
    site_provider = _RecordingProvider(_response())
    site_router = ModelProviderRouter(
        providers={"site-fixture": site_provider},
        fallback_order=["site-fixture"],
        store=authority,
        project_id=PROJECT_ID,
        weekly_call_limit=200,
    )
    site_result = SiteCriticService(provider=site_router).generate_and_validate(
        "study-area-test-v1",
        [{"card_id": CARD_ID, "metric_name": "Verified buildings", "value": 12, "unit": "features"}],
        query="Summarize the verified evidence.",
    )
    ariadne_provider = _RecordingProvider(_response())

    def ariadne_provider_factory(store, project_id):
        return ModelProviderRouter(
            providers={"ariadne-fixture": ariadne_provider},
            fallback_order=["ariadne-fixture"],
            store=store,
            project_id=project_id,
            weekly_call_limit=200,
        )

    client, _authority, chat_path = _client(
        tmp_path,
        live_enabled=True,
        provider_factory=ariadne_provider_factory,
        authority=authority,
    )
    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Explain the verified evidence."},
    )

    assert site_result.provider_status == "LIVE_AI: ACTIVE"
    assert result.status_code == 200
    assert result.json()["assistant_message"]["provider_status"] == "LIVE_AI: ACTIVE"
    assert site_provider.calls == 1
    assert ariadne_provider.calls == 1
    assert ProjectStateModelRunAccounting(authority, PROJECT_ID).weekly_calls_used() == 2
    chat_store = ProjectStateStore(chat_path)
    assert chat_store.list_current("ModelRun", project_id=PROJECT_ID) == []
    chat_store.close()


def test_weekly_budget_blocks_site_critic_and_ariadne_from_shared_project_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    authority = ProjectStateStore(tmp_path / "authority.sqlite3")
    now = datetime.now(timezone.utc).isoformat()
    for index in range(200):
        run_id = f"seed-run-{index:03d}"
        authority.create(
            "ModelRun",
            {
                "id": run_id,
                "provider": "fixture-provider",
                "model_id": "fixture-model",
                "prompt_hash": "a" * 64,
                "schema_version": "site-critic-response-v1",
                "status": "SUCCEEDED",
                "response_hash": "b" * 64,
                "created_at": now,
                "project_id": PROJECT_ID,
            },
            entity_id=run_id,
            project_id=PROJECT_ID,
            actor="TEST_HARNESS",
        )

    site_provider = _RecordingProvider(_response())
    site_router = ModelProviderRouter(
        providers={"site-fixture": site_provider},
        fallback_order=["site-fixture"],
        store=authority,
        project_id=PROJECT_ID,
        weekly_call_limit=200,
    )
    site_result = site_router.generate_criticism(CriticRequest(study_area_id="study-area-test-v1"))
    ariadne_provider = _RecordingProvider(_response())

    def ariadne_provider_factory(store, project_id):
        return ModelProviderRouter(
            providers={"ariadne-fixture": ariadne_provider},
            fallback_order=["ariadne-fixture"],
            store=store,
            project_id=project_id,
            weekly_call_limit=200,
        )

    client, _authority, _chat_path = _client(
        tmp_path,
        live_enabled=True,
        provider_factory=ariadne_provider_factory,
        authority=authority,
    )
    status = client.get(f"/api/v1/projects/{PROJECT_ID}/ariadne/status")
    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Explain the verified evidence."},
    )

    assert site_result["provider_status"] == "LIVE_AI: BLOCKED_BUDGET"
    assert site_provider.calls == 0
    assert status.json()["block_reason_code"] == "BLOCKED_BUDGET"
    assert status.json()["weekly_calls_used"] == 200
    assert result.json()["status"]["block_reason_code"] == "BLOCKED_BUDGET"
    assert ariadne_provider.calls == 0
    assert ProjectStateModelRunAccounting(authority, PROJECT_ID).weekly_calls_used() == 200


def test_live_response_with_unknown_evidence_reference_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    recording = _RecordingProvider(_response(refs=["card-not-in-current-evidence"]))

    def provider_factory(store, project_id):
        return ModelProviderRouter(
            providers={"ariadne-fixture": recording},
            fallback_order=["ariadne-fixture"],
            store=store,
            project_id=project_id,
            weekly_call_limit=200,
        )

    client, _authority, _chat_path = _client(tmp_path, live_enabled=True, provider_factory=provider_factory)

    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Explain this evidence."},
    )

    assert result.status_code == 502
    assert "unverified evidence" in result.json()["detail"].lower()
    assert recording.calls == 1


def test_http_401_stops_after_one_profile_attempt(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    recording = _RecordingProvider(
        _response(status="LIVE_AI: REQUEST_REJECTED", refs=[], metadata={"http_status": 401})
    )

    def provider_factory(store, project_id):
        return ModelProviderRouter(
            providers={"ariadne-fixture": recording},
            fallback_order=["ariadne-fixture"],
            store=store,
            project_id=project_id,
            weekly_call_limit=200,
        )

    client, _authority, _chat_path = _client(tmp_path, live_enabled=True, provider_factory=provider_factory)
    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Ask one question."},
    )

    assert result.status_code == 200
    assert result.json()["assistant_message"]["provider_status"] == "LIVE_AI: REQUEST_REJECTED"
    assert recording.calls == 1


def test_outcome_unknown_is_not_resent(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    recording = _RecordingProvider(
        _response(status="LIVE_AI: OUTCOME_UNKNOWN", refs=[], metadata={"delivery": "unknown"})
    )

    def provider_factory(store, project_id):
        return ModelProviderRouter(
            providers={"ariadne-fixture": recording},
            fallback_order=["ariadne-fixture"],
            store=store,
            project_id=project_id,
            weekly_call_limit=200,
        )

    client, _authority, _chat_path = _client(tmp_path, live_enabled=True, provider_factory=provider_factory)
    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Ask one question."},
    )

    assert result.status_code == 200
    assert result.json()["assistant_message"]["provider_status"] == "LIVE_AI: OUTCOME_UNKNOWN"
    assert "reconcile" in result.json()["assistant_message"]["content"].lower()
    assert recording.calls == 1


def test_chat_messages_never_write_to_authority_database(tmp_path):
    client, authority, _chat_path = _client(tmp_path)
    authority_path = tmp_path / "authority.sqlite3"
    before = hashlib.sha256(authority_path.read_bytes()).hexdigest()

    result = client.post(
        f"/api/v1/projects/{PROJECT_ID}/ariadne/messages",
        json={"content": "Show the source status."},
    )
    messages = client.get(f"/api/v1/projects/{PROJECT_ID}/ariadne/messages")

    after = hashlib.sha256(authority_path.read_bytes()).hexdigest()
    assert result.status_code == 200
    assert messages.status_code == 200
    assert len(messages.json()["messages"]) == 2
    assert before == after
    assert authority.list_current("HumanDecision", project_id=PROJECT_ID) == []
    assert authority.list_current("ModelRun", project_id=PROJECT_ID) == []


def test_decisions_needed_include_workspace_and_brief_sources(tmp_path):
    context = _context()
    context["evidence_cards"] = [
        {
            "card_id": "card-legacy-status",
            "metric_name": "Legacy observation",
            "value": 1,
            "unit": "features",
            "status": "VERIFIED_OBSERVATION",
            "limitations": [],
        }
    ]
    client, _authority, _chat_path = _client(tmp_path, context=context)

    result = client.get(f"/api/v1/projects/{PROJECT_ID}/ariadne/decisions-needed")

    assert result.status_code == 200
    items = result.json()["items"]
    assert {"card-legacy-status", "workspace-project-ariadne-test"}.issubset(
        {item["source_id"] for item in items}
    )
    assert any(item["id"].startswith("d1-") for item in items)
    assert any(item["id"].startswith("d3-") for item in items)


def test_decisions_needed_groups_legacy_cards_and_localizes_titles_and_reasons(tmp_path):
    context = _context()
    context["evidence_cards"] = [
        {
            "card_id": f"card-legacy-{index}",
            "metric_name": "Legacy observation",
            "value": index,
            "unit": "features",
            "status": "VERIFIED_OBSERVATION",
            "limitations": [],
        }
        for index in range(1, 8)
    ]
    context["problems"] = [
        {"problem_id": "prob-access", "title": "通行問題", "title_zh": "通行問題", "title_en": "Access issue", "status": "DRAFT"}
    ]
    client, _authority, _chat_path = _client(tmp_path, context=context)
    endpoint = f"/api/v1/projects/{PROJECT_ID}/ariadne/decisions-needed"

    zh_result = client.get(endpoint, headers={"Accept-Language": "zh-TW"})
    en_result = client.get(endpoint, headers={"Accept-Language": "en"})

    zh_items = zh_result.json()["items"]
    en_items = en_result.json()["items"]
    zh_legacy = next(item for item in zh_items if item["id"] == "legacy-status-verified_observation")
    en_legacy = next(item for item in en_items if item["id"] == "legacy-status-verified_observation")
    assert len(zh_items) == len(en_items)
    assert len(zh_legacy["source_ids"]) == 7
    assert zh_legacy["title"] == "確認 7 張證據卡的舊版狀態標籤"
    assert "請逐張確認" in zh_legacy["reason"]
    assert en_legacy["title"] == "Confirm legacy status labels for 7 evidence cards"
    assert "review each label" in en_legacy["reason"]
    assert any(item["title"] == "檢視問題定義：通行問題" for item in zh_items)
    assert any(item["title"] == "Review problem definition: Access issue" for item in en_items)


def test_workspace_api_registers_ariadne_status_and_decisions_routes(tmp_path):
    store = ProjectStateStore(tmp_path / "workspace-authority.sqlite3")
    client = TestClient(create_workspace_app(store))

    status = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/ariadne/status")
    decisions = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/ariadne/decisions-needed")

    assert status.status_code == 200
    assert status.json()["mode"] == "OFFLINE"
    assert status.json()["block_reason_code"] == "BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED"
    assert decisions.status_code == 200
    assert decisions.json()["project_id"] == "rotterdam-m4h-pilot-project"
    assert store.list_current("HumanDecision", project_id="rotterdam-m4h-pilot-project") == []


def test_decisions_needed_omits_workspace_and_brief_when_decision_approved(tmp_path):
    context = _context()
    context["human_decisions"] = [
        {
            "target_id": "workspace-project-ariadne-test",
            "target_type": "WorkspaceRevision",
            "target_version": "1",
            "status": "approved",
        }
    ]
    client, _authority, _chat_path = _client(tmp_path, context=context)

    result = client.get(f"/api/v1/projects/{PROJECT_ID}/ariadne/decisions-needed")

    assert result.status_code == 200
    items = result.json()["items"]
    assert not any(item["id"].startswith("d1-") for item in items)
    assert not any(item["id"].startswith("d3-") for item in items)


def test_decisions_needed_explains_older_accepted_workspace_revision(tmp_path):
    context = _context()
    context["workspace_decision"] = {"status": "APPROVED", "accepted_workspace_revision": 8}
    client, _authority, _chat_path = _client(tmp_path, context=context)

    result = client.get(f"/api/v1/projects/{PROJECT_ID}/ariadne/decisions-needed", headers={"Accept-Language": "zh-TW"})

    assert result.status_code == 200
    items = result.json()["items"]
    d1 = [item for item in items if item["id"].startswith("d1-")]
    assert len(d1) == 1 and "r8" in d1[0]["reason"]
    assert not any(item["id"].startswith("d3-") for item in items)


def test_decisions_needed_omits_workspace_items_when_current_revision_is_accepted(tmp_path):
    context = _context()
    current = str(context["workspace"]["revision"])
    context["workspace_decision"] = {"status": "APPROVED", "accepted_workspace_revision": int(current)}
    client, _authority, _chat_path = _client(tmp_path, context=context)

    items = client.get(f"/api/v1/projects/{PROJECT_ID}/ariadne/decisions-needed").json()["items"]

    assert not any(item["id"].startswith(("d1-", "d3-")) for item in items)
