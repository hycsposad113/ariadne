from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.model_profiles import load_model_provider_config
from urban_design.model_provider import CriticRequest, ModelProviderRouter, create_profile_provider
from urban_design.site_critic import CriticValidationError, SiteCriticService
from urban_design.store import ProjectStateStore


PROJECT_ID = "m4h-model-run-test"


def _profile(profile_id: str):
    return next(profile for profile in load_model_provider_config().profiles if profile.id == profile_id)


def _response(profile_id: str, *, evidence_ref: str = "card-1") -> dict:
    profile = _profile(profile_id)
    return {
        "critic_id": f"critic-{profile_id}",
        "study_area_id": "study-area-test",
        "evidence_refs": [evidence_ref],
        "observations": [f"The supplied evidence is cited [{evidence_ref}]."],
        "design_hypotheses": ["Test one bounded design hypothesis."],
        "limitations": [],
        "next_questions": [],
        "provider_name": profile.cli_command + "-cli" if profile.cli_command else profile.id,
        "provider_profile_id": profile_id,
        "provider_model": profile.model,
        "provider_status": "LIVE_AI: ACTIVE",
        "provider_metadata": {"response_sha256": "b" * 64, "delivery": "response_received"},
    }


class _RecordingProvider:
    is_live_available = True
    status = "LIVE_AI: CONFIGURED_NOT_CALLED"

    def __init__(self, profile_id: str, store: ProjectStateStore, response: dict | None = None):
        self.profile = _profile(profile_id)
        self.profile_id = profile_id
        self.provider_name = self.profile.cli_command + "-cli" if self.profile.cli_command else profile_id
        self.store = store
        self.response = response or _response(profile_id)
        self.calls = 0
        self.pending_seen_before_dispatch = False

    def generate_criticism(self, _request: CriticRequest) -> dict:
        self.calls += 1
        runs = self.store.list_current("ModelRun", project_id=PROJECT_ID)
        self.pending_seen_before_dispatch = len(runs) == 1 and runs[0].payload.get("status") == "PENDING"
        return dict(self.response)


def _router(store: ProjectStateStore, providers: dict[str, _RecordingProvider] | None = None) -> ModelProviderRouter:
    if providers is None:
        provider = _RecordingProvider("codex-cli", store)
        providers = {provider.profile_id: provider}
    return ModelProviderRouter(
        providers=providers,
        fallback_order=list(providers),
        store=store,
        project_id=PROJECT_ID,
    )


def test_live_dispatch_creates_pending_record_before_dispatch_and_finalizes_after_local_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    store = ProjectStateStore(tmp_path / "model-runs.sqlite3")
    provider = _RecordingProvider("codex-cli", store)
    router = _router(store, {provider.profile_id: provider})

    result = SiteCriticService(provider=router).generate_and_validate(
        "study-area-test",
        [{"card_id": "card-1", "metric_name": "Coverage", "value": 50, "unit": "%"}],
    )

    assert result.provider_status == "LIVE_AI: ACTIVE"
    assert provider.pending_seen_before_dispatch is True
    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["status"] == "SUCCEEDED"
    assert run.payload["profile_id"] == "codex-cli"
    assert run.payload["provider"] == "codex-cli"
    assert run.payload["prompt_template_version"]
    assert re.fullmatch(r"[0-9a-f]{64}", run.payload["prompt_template_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", run.payload["request_sha256"])
    assert run.payload["budget_sequence"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", run.payload["response_hash"])
    assert run.payload["validation_result"] == "PASSED"

    store.close()


def test_evidence_validation_failure_finalizes_the_model_run_as_model_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    store = ProjectStateStore(tmp_path / "invalid-model-run.sqlite3")
    provider = _RecordingProvider("claude-cli", store, _response("claude-cli", evidence_ref="invented-card"))
    router = _router(store, {provider.profile_id: provider})

    with pytest.raises(CriticValidationError, match="fake or unverified evidence ref"):
        SiteCriticService(provider=router).generate_and_validate(
            "study-area-test",
            [{"card_id": "card-1", "metric_name": "Coverage", "value": 50, "unit": "%"}],
        )

    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["status"] == "MODEL_FAILED"
    assert run.payload["response_hash"] == "b" * 64
    assert run.payload["validation_result"] == "FAILED"

    store.close()


def test_post_dispatch_exception_finalizes_the_model_run_as_outcome_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    store = ProjectStateStore(tmp_path / "unknown-model-run.sqlite3")
    provider = _RecordingProvider("codex-cli", store)

    def lose_receipt(_request: CriticRequest) -> dict:
        provider.calls += 1
        runs = store.list_current("ModelRun", project_id=PROJECT_ID)
        provider.pending_seen_before_dispatch = len(runs) == 1 and runs[0].payload.get("status") == "PENDING"
        raise RuntimeError("fake post-dispatch connection loss")

    provider.generate_criticism = lose_receipt
    router = _router(store, {provider.profile_id: provider})

    result = router.generate_criticism(CriticRequest(study_area_id="study-area-test"))

    assert result["provider_status"] == "LIVE_AI: OUTCOME_UNKNOWN"
    assert provider.pending_seen_before_dispatch is True
    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["status"] == "OUTCOME_UNKNOWN"
    assert run.payload["response_hash"] is None
    assert run.payload["validation_result"] == "NOT_RUN"

    store.close()


def test_profile_selection_updates_the_router_used_by_the_critic_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    # The login probe would run the real CLI; this test is about router selection.
    monkeypatch.setattr("urban_design.model_profiles.probe_cli_login", lambda *args, **kwargs: True)
    store = ProjectStateStore(tmp_path / "selected-profile.sqlite3")
    codex = _RecordingProvider("codex-cli", store)
    claude = _RecordingProvider("claude-cli", store)
    router = _router(store, {"codex-cli": codex, "claude-cli": claude})
    client = TestClient(create_workspace_app(store, critic_provider=router, allow_live_critic=False))

    response = client.post("/api/v1/model-profiles/active", json={"profile_id": "claude-cli"})
    assert response.status_code == 200
    assert response.json()["live_dispatch_enabled"] is True
    assert router.active_profile_id == "claude-cli"

    SiteCriticService(provider=router).generate_and_validate(
        "study-area-test",
        [{"card_id": "card-1", "metric_name": "Coverage", "value": 50, "unit": "%"}],
    )

    assert claude.calls == 1
    assert codex.calls == 0
    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["profile_id"] == "claude-cli"

    store.close()


def test_weekly_budget_uses_persisted_model_runs_and_blocks_before_provider_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    store = ProjectStateStore(tmp_path / "budget.sqlite3")
    now = datetime.now(timezone.utc).isoformat()
    for index in range(200):
        run_id = f"seed-run-{index:03d}"
        store.create(
            "ModelRun",
            {
                "id": run_id,
                "provider": "codex-cli",
                "model_id": "gpt-6-luna",
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
    provider = _RecordingProvider("codex-cli", store)
    router = _router(store, {provider.profile_id: provider})

    result = router.generate_criticism(CriticRequest(study_area_id="study-area-test"))

    assert result["provider_status"] == "LIVE_AI: BLOCKED_BUDGET"
    assert provider.calls == 0
    assert len(store.list_current("ModelRun", project_id=PROJECT_ID)) == 200

    store.close()


def test_malformed_cli_response_is_hashed_and_recorded_as_model_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    store = ProjectStateStore(tmp_path / "malformed-cli.sqlite3")
    profile = _profile("codex-cli")
    provider = create_profile_provider(
        profile,
        cli_resolver=lambda _command: "/fake/codex",
        cli_runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="{malformed-json", stderr="private diagnostic"),
    )
    router = _router(store, {profile.id: provider})

    result = router.generate_criticism(CriticRequest(study_area_id="study-area-test"))

    assert result["provider_status"] == "LIVE_AI: MODEL_FAILED"
    [run] = store.list_current("ModelRun", project_id=PROJECT_ID)
    assert run.payload["status"] == "MODEL_FAILED"
    assert re.fullmatch(r"[0-9a-f]{64}", run.payload["response_hash"])
    assert "private diagnostic" not in str(run.payload)

    store.close()


def test_hermes_checks_toolsets_first_and_uses_only_the_profile_server_key(monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    profile = {
        "id": "hermes-urban-critic",
        "adapter": "openai_compatible",
        "base_url": "http://127.0.0.1:8780/v1",
        "model": "hermes-test-model",
        "keychain_service": "urban-design-hermes",
        "supports_json_schema": False,
        "data_egress": "hermes",
        "enabled": True,
    }
    from urban_design.model_profiles import ModelProviderProfile

    profile_model = ModelProviderProfile.model_validate(profile)
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_get(url, headers, _timeout):
        calls.append((url, dict(headers)))
        if url.endswith("/toolsets"):
            return 200, {"tools": [], "version": "hermes-test"}
        return 200, {"data": [{"id": "hermes-test-model"}]}

    def fake_post(url, headers, _body, _timeout):
        calls.append((url, dict(headers)))
        return 200, {
            "model": "hermes-test-model-v1",
            "choices": [{"message": {"content": json.dumps({
                "evidence_refs": [],
                "observations": [],
                "design_hypotheses": [],
                "limitations": [],
                "next_questions": [],
            })}}],
        }

    provider = create_profile_provider(
        profile_model,
        api_key="fake-hermes-server-key",
        get_transport=fake_get,
        model_list_transport=fake_get,
        transport=fake_post,
    )

    result = provider.generate_criticism(CriticRequest(study_area_id="study-area-test"))

    assert result["provider_status"] == "LIVE_AI: ACTIVE"
    assert calls[0][0].endswith("/toolsets")
    assert calls[1][0].endswith("/models")
    assert calls[2][0].endswith("/chat/completions")
    assert all(headers.get("Authorization") == "Bearer fake-hermes-server-key" for _url, headers in calls)
    assert all("X-Hermes-Session-Key" not in headers for _url, headers in calls)


def test_live_dispatch_requires_the_exact_project_authorization_value(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "true")
    store = ProjectStateStore(tmp_path / "authorization.sqlite3")
    provider = _RecordingProvider("codex-cli", store)
    router = _router(store, {provider.profile_id: provider})

    result = router.generate_criticism(CriticRequest(study_area_id="study-area-test"))

    assert result["provider_status"] == "LIVE_AI: BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED"
    assert provider.calls == 0
    assert store.list_current("ModelRun", project_id=PROJECT_ID) == []

    store.close()
