"""G10 live-AI cases through the shipped provider, with a fake transport only."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from urban_design.model_profiles import load_model_provider_config
from urban_design.model_provider import (
    CriticRequest,
    ModelProviderRouter,
    ProjectStateModelRunAccounting,
    create_profile_provider,
)
from urban_design.site_critic import CriticValidationError, SiteCriticService
from urban_design.store import ProjectStateStore


PROJECT_ID = "g10-live-ai"
FIXTURE_KEY = "fixture-key-not-live"
CARD_ID = "card-open-space"
CURRENT_HASH = "ab" * 32
STALE_HASH = "cd" * 32
CARD = {
    "card_id": CARD_ID,
    "metric_name": "Public open space",
    "value": 42.5,
    "unit": "%",
    "scenario_id": "scenario-grid",
    "source_package_revision": "r03",
    "study_area_revision": 8,
    "input_sha256": CURRENT_HASH,
    "radius_m": 800,
}


@pytest.fixture(autouse=True)
def _forbid_live_calls(monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    monkeypatch.delenv("PROJECT_OPENAI_AUTHORIZED", raising=False)

    def blocked_urlopen(*_args, **_kwargs):
        raise AssertionError("G10 tests must not open a live HTTP socket")

    def blocked_run(command, *_args, **_kwargs):
        text = " ".join(command) if isinstance(command, (list, tuple)) else str(command)
        if "find-generic-password" in text or "security" in text.split():
            raise AssertionError("G10 tests must not read Keychain")
        raise AssertionError(f"unexpected subprocess in a fake-transport test: {text}")

    monkeypatch.setattr("urban_design.model_provider.urlopen", blocked_urlopen)
    monkeypatch.setattr("urban_design.model_provider.subprocess.run", blocked_run)


def _profile():
    profile = next(item for item in load_model_provider_config().profiles if item.id == "openai-gpt-4o")
    assert profile.model == "gpt-4o"
    return profile


def _observation() -> str:
    return f"Public open space is 42.5 % [{CARD_ID}]."


def _content(**extra) -> dict:
    payload = {
        "evidence_refs": [CARD_ID],
        "observations": [_observation()],
        "design_hypotheses": ["A designer could test a more open edge."],
        "limitations": [],
        "next_questions": [],
        "scenario_id": "scenario-grid",
        "source_package_revision": "r03",
        "study_area_revision": 8,
        "input_sha256": CURRENT_HASH,
        "radius_m": 800,
        "unit": "%",
    }
    payload.update(extra)
    return payload


def _chat_response(content: dict) -> tuple[int, dict]:
    return 200, {
        "id": "chatcmpl-fake",
        "model": "gpt-4o-2024-08-06",
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 12},
    }


class _OtherProfile:
    """A second configured profile that must not run unless the router explicitly falls through."""

    is_live_available = True
    status = "LIVE_AI: CONFIGURED_NOT_CALLED"
    provider_name = "not-gpt-4o"

    def __init__(self):
        self.calls = 0
        self.profile = _profile()

    def generate_criticism(self, _request):
        self.calls += 1
        raise AssertionError("fake transport must not switch models or profiles")


def _provider(calls: list[str], *, models=None, chat=None):
    def model_list(_url, headers, _timeout):
        calls.append("models")
        assert headers["Authorization"] == f"Bearer {FIXTURE_KEY}"
        if models is not None:
            return models
        return 200, {"data": [{"id": "gpt-4o"}]}

    def transport(url, headers, body, _timeout):
        calls.append("chat")
        assert url == "https://api.openai.com/v1/chat/completions"
        assert headers["Authorization"] == f"Bearer {FIXTURE_KEY}"
        assert body["model"] == "gpt-4o"
        encoded = json.dumps(body)
        assert FIXTURE_KEY not in encoded
        assert "/Users/" not in encoded
        assert "state.sqlite3" not in encoded
        if chat is not None:
            return chat
        return _chat_response(_content())

    return create_profile_provider(
        _profile(),
        api_key=FIXTURE_KEY,
        transport=transport,
        model_list_transport=model_list,
        request_id_factory=lambda: "request-g10-fixed",
    )


def _router(tmp_path, provider, *extra, name="runs.sqlite3"):
    store = ProjectStateStore(tmp_path / name)
    providers = {"openai-gpt-4o": provider}
    order = ["openai-gpt-4o"]
    for item in extra:
        providers[item.provider_name] = item
        order.append(item.provider_name)
    router = ModelProviderRouter(
        providers=providers,
        fallback_order=order,
        store=store,
        project_id=PROJECT_ID,
        weekly_call_limit=200,
    )
    return store, router


def _request() -> CriticRequest:
    return CriticRequest(
        study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
        evidence_bundle=[dict(CARD)],
        query="Explain this scheme using only the evidence bundle.",
    )


def test_fake_transport_success_persists_model_run_and_survives_reopen(tmp_path):
    calls: list[str] = []
    provider = _provider(calls)
    store, router = _router(tmp_path, provider)
    response = SiteCriticService(provider=router).generate_and_validate(
        "study-area-rotterdam-m4h-pilot-project-v5",
        [dict(CARD)],
        query="Explain this scheme using only the evidence bundle.",
    )

    assert calls == ["models", "chat"]
    assert response.provider_status == "LIVE_AI: ACTIVE"
    assert response.provider_model == "gpt-4o-2024-08-06"
    assert response.provider_profile_id == "openai-gpt-4o"
    assert FIXTURE_KEY not in json.dumps(response.model_dump(mode="json"))
    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["status"] == "SUCCEEDED"
    assert run.payload["validation_result"] == "PASSED"
    assert run.payload["model_id"] == "gpt-4o"
    assert run.payload["configured_model_id"] == "gpt-4o"
    assert run.payload["profile_id"] == "openai-gpt-4o"
    assert run.payload["actual_model"] == "gpt-4o-2024-08-06"
    assert run.payload["budget_sequence"] == 1
    path = store.database
    store.close()

    reopened = ProjectStateStore(path)
    assert ProjectStateModelRunAccounting(reopened, PROJECT_ID).weekly_calls_used() == 1
    [again] = reopened.list_current("ModelRun", project_id=PROJECT_ID)
    assert again.payload["status"] == "SUCCEEDED"
    reopened.close()


def test_fake_transport_401_stops_without_retry_and_withholds_body(tmp_path):
    secret_body = {"error": "do-not-keep-this-body", "token": FIXTURE_KEY}
    list_calls: list[str] = []
    list_provider = _provider(list_calls, models=(401, secret_body))
    store, router = _router(tmp_path, list_provider, name="auth-list.sqlite3")
    listed = router.generate_criticism(_request())
    assert list_calls == ["models"]
    assert listed["provider_status"] == "LIVE_AI: REQUEST_REJECTED"
    assert "withheld" in listed["limitations"][0]
    assert "do-not-keep-this-body" not in json.dumps(listed)
    assert FIXTURE_KEY not in json.dumps(listed)
    store.close()

    chat_calls: list[str] = []
    chat_provider = _provider(chat_calls, chat=(401, secret_body))
    store, router = _router(tmp_path, chat_provider, name="auth-chat.sqlite3")
    rejected = router.generate_criticism(_request())
    assert chat_calls == ["models", "chat"]
    assert rejected["provider_status"] == "LIVE_AI: REQUEST_REJECTED"
    assert rejected["provider_metadata"]["http_status"] == 401
    assert "withheld" in rejected["limitations"][0]
    assert "do-not-keep-this-body" not in json.dumps(rejected)
    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["status"] == "MODEL_FAILED"
    assert run.payload["model_id"] == "gpt-4o"
    store.close()


def test_fake_transport_429_does_not_retry_or_switch_model(tmp_path):
    other = _OtherProfile()
    list_calls: list[str] = []
    listed = _provider(list_calls, models=(429, {"error": "slow-down"}))
    store, router = _router(tmp_path, listed, other, name="quota-http.sqlite3")
    result = router.generate_criticism(_request())
    assert list_calls == ["models"]
    assert other.calls == 0
    assert result["provider_status"] == "LIVE_AI: MODEL_LIST_FAILED"
    assert result["provider_metadata"]["http_status"] == 429
    assert result["provider_model"] == "gpt-4o"
    store.close()

    other = _OtherProfile()
    chat_calls: list[str] = []
    chatting = _provider(chat_calls, chat=(429, {"error": "slow-down"}))
    store, router = _router(tmp_path, chatting, other, name="quota-chat.sqlite3")
    result = router.generate_criticism(_request())
    assert chat_calls == ["models", "chat"]
    assert other.calls == 0
    assert result["provider_status"] == "LIVE_AI: REQUEST_REJECTED"
    assert result["provider_metadata"]["http_status"] == 429
    assert result["provider_model"] == "gpt-4o"
    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["status"] == "MODEL_FAILED"
    assert run.payload["configured_model_id"] == "gpt-4o"
    store.close()


def test_fake_transport_timeout_is_outcome_unknown_without_resend(tmp_path):
    calls: list[str] = []

    def explode(*_args):
        calls.append("chat")
        raise TimeoutError("timed out after connect")

    other = _OtherProfile()
    provider = _provider(calls, chat=None)
    provider.transport = explode
    store, router = _router(tmp_path, provider, other)
    result = router.generate_criticism(_request())

    assert calls == ["models", "chat"]
    assert other.calls == 0
    assert result["provider_status"] == "LIVE_AI: OUTCOME_UNKNOWN"
    assert "reconcile" in result["limitations"][0].lower()
    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["status"] == "OUTCOME_UNKNOWN"
    assert run.payload["validation_result"] == "NOT_RUN"
    store.close()


def test_fake_transport_outcome_unknown_is_not_resent(tmp_path):
    calls: list[str] = []

    def explode(*_args):
        calls.append("chat")
        raise RuntimeError("connection reset after dispatch")

    other = _OtherProfile()
    provider = _provider(calls)
    provider.transport = explode
    store, router = _router(tmp_path, provider, other, name="unknown.sqlite3")
    result = router.generate_criticism(_request())

    assert calls == ["models", "chat"]
    assert other.calls == 0
    assert result["provider_status"] == "LIVE_AI: OUTCOME_UNKNOWN"
    assert result["provider_metadata"]["error_class"] == "RuntimeError"
    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["status"] == "OUTCOME_UNKNOWN"
    store.close()


def _critic_payload(**extra) -> dict:
    payload = {
        "critic_id": "critic-g10",
        "study_area_id": "study-area-rotterdam-m4h-pilot-project-v5",
        "evidence_refs": [CARD_ID],
        "observations": [_observation()],
        "design_hypotheses": ["A designer could test a more open edge."],
        "limitations": [],
        "next_questions": [],
        "provider_status": "LIVE_AI: ACTIVE",
        "provider_name": "openai",
        "provider_profile_id": "openai-gpt-4o",
        "provider_model": "gpt-4o-2024-08-06",
    }
    payload.update(extra)
    return payload


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"scenario_id": "scenario-other"}, "scheme that is not in the current evidence bundle"),
        (
            {"observations": [f"scheme-other is not this scheme [{CARD_ID}]."]},
            "scheme that is not in the current evidence bundle",
        ),
        (
            {"observations": [f"Public open space is 42.5 m [{CARD_ID}]."]},
            "unsupported numeric claim",
        ),
        ({"unit": "m"}, "unit that does not match"),
        (
            {"observations": [f"Public open space is 1500 m [{CARD_ID}]."]},
            "unsupported numeric claim",
        ),
        ({"radius_m": 1500}, "radius that does not match"),
        ({"study_area_revision": 7}, "stale revision or source hash"),
        ({"input_sha256": STALE_HASH}, "stale revision or source hash"),
        (
            {"observations": [f"Public open space is 42.5 % [{CARD_ID}]. Hash {STALE_HASH} is old."]},
            "stale revision or source hash",
        ),
    ],
)
def test_fake_citation_rejects_wrong_scheme_unit_radius_and_stale_binding(extra, message):
    with pytest.raises(CriticValidationError, match=message):
        SiteCriticService().validate_critic_response(_critic_payload(**extra), [dict(CARD)])


def test_bad_scheme_citation_is_recorded_model_failed_not_succeeded(tmp_path):
    calls: list[str] = []
    provider = _provider(calls, chat=_chat_response(_content(scenario_id="scenario-other")))
    store, router = _router(tmp_path, provider, name="bad-citation.sqlite3")
    with pytest.raises(CriticValidationError, match="scheme that is not in the current evidence bundle"):
        SiteCriticService(provider=router).generate_and_validate(
            "study-area-rotterdam-m4h-pilot-project-v5",
            [dict(CARD)],
        )

    assert calls == ["models", "chat"]
    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["status"] == "MODEL_FAILED"
    assert run.payload["validation_result"] == "FAILED"
    assert run.payload["status"] != "SUCCEEDED"
    store.close()


def test_offline_template_is_not_a_live_pass():
    response = SiteCriticService().validate_critic_response(
        _critic_payload(provider_status="NON_AI: DETERMINISTIC_TEMPLATE"),
        [dict(CARD)],
    )
    assert response.provider_status == "NON_AI: DETERMINISTIC_TEMPLATE"
    assert response.provider_status != "LIVE_AI: ACTIVE"


def test_weekly_quota_blocks_before_transport_and_survives_reopen(tmp_path):
    path = tmp_path / "quota.sqlite3"
    store = ProjectStateStore(path)
    now = datetime.now(timezone.utc).isoformat()
    for index in range(200):
        run_id = f"seed-run-{index:03d}"
        store.create(
            "ModelRun",
            {
                "id": run_id,
                "provider": "openai",
                "model_id": "gpt-4o",
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
    store.close()

    calls: list[str] = []
    reopened = ProjectStateStore(path)
    provider = _provider(calls)
    router = ModelProviderRouter(
        providers={"openai-gpt-4o": provider},
        fallback_order=["openai-gpt-4o"],
        store=reopened,
        project_id=PROJECT_ID,
        weekly_call_limit=200,
    )
    result = router.generate_criticism(_request())

    assert calls == []
    assert result["provider_status"] == "LIVE_AI: BLOCKED_BUDGET"
    assert ProjectStateModelRunAccounting(reopened, PROJECT_ID).weekly_calls_used() == 200
    assert len(reopened.list_current("ModelRun", project_id=PROJECT_ID)) == 200
    reopened.close()
