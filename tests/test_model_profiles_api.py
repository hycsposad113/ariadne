from __future__ import annotations

from fastapi.testclient import TestClient

from urban_design import model_profiles
from urban_design.api import create_workspace_app
from urban_design.model_provider import DeterministicFixtureProvider
from urban_design.store import ProjectStateStore


def test_profile_settings_endpoint_lists_secret_free_status_and_runtime_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(model_profiles, "keychain_service_exists", lambda _service: False)
    monkeypatch.setattr(model_profiles, "cli_command_available", lambda _command: True)
    store = ProjectStateStore(tmp_path / "profiles.sqlite3")
    app = create_workspace_app(store, critic_provider=DeterministicFixtureProvider())
    client = TestClient(app)

    initial = client.get("/api/v1/model-profiles/status")
    assert initial.status_code == 200
    payload = initial.json()
    assert payload["active_profile_id"] == "codex-cli"
    assert payload["live_dispatch_enabled"] is False
    assert payload["weekly_calls_used"] is None
    assert payload["dispatch_block_reason"] == "BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED"
    profiles = {item["id"]: item for item in payload["profiles"]}
    assert profiles["openai-gpt-4o"]["status"] == "MISSING_KEY"
    assert profiles["hermes-urban-critic"]["status"] == "DISABLED"
    assert "api_key" not in str(payload).lower()
    assert "keychain_service" not in str(payload).lower()

    selected = client.post(
        "/api/v1/model-profiles/active",
        json={"profile_id": "openai-gpt-4o"},
    )
    assert selected.status_code == 200
    assert selected.json()["active_profile_id"] == "openai-gpt-4o"
    assert client.get("/api/v1/model-profiles/status").json()["active_profile_id"] == "openai-gpt-4o"
    assert store.list_current("ModelRun") == []
    assert store.list_current("HumanDecision") == []

    store.close()


def test_profile_selection_refuses_unknown_or_disabled_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(model_profiles, "keychain_service_exists", lambda _service: False)
    store = ProjectStateStore(tmp_path / "profiles.sqlite3")
    client = TestClient(create_workspace_app(store, critic_provider=DeterministicFixtureProvider()))

    assert client.post("/api/v1/model-profiles/active", json={"profile_id": "missing"}).status_code == 404
    assert client.post(
        "/api/v1/model-profiles/active",
        json={"profile_id": "hermes-urban-critic"},
    ).status_code == 409

    store.close()


def test_profile_selection_persists_across_api_restarts_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(model_profiles, "keychain_service_exists", lambda _service: False)
    monkeypatch.setattr(model_profiles, "cli_command_available", lambda _command: True)
    monkeypatch.setattr(model_profiles, "probe_cli_login", lambda _command: True)
    settings_path = tmp_path / "runtime" / "ariadne-profile-selection.json"

    first_store = ProjectStateStore(tmp_path / "first.sqlite3")
    first_app = create_workspace_app(
        first_store,
        critic_provider=DeterministicFixtureProvider(),
        model_profile_selection_path=settings_path,
    )
    with TestClient(first_app) as first_client:
        selected = first_client.post(
            "/api/v1/model-profiles/active",
            json={"profile_id": "claude-cli"},
        )
        assert selected.status_code == 200
        assert selected.json()["active_profile_id"] == "claude-cli"
    first_store.close()

    assert settings_path.read_text(encoding="utf-8") == '{"profile_id":"claude-cli","schema_version":1}'

    second_store = ProjectStateStore(tmp_path / "second.sqlite3")
    second_app = create_workspace_app(
        second_store,
        critic_provider=DeterministicFixtureProvider(),
        model_profile_selection_path=settings_path,
    )
    with TestClient(second_app) as second_client:
        status = second_client.get("/api/v1/model-profiles/status")
        assert status.json()["active_profile_id"] == "claude-cli"
        assert "key" not in settings_path.read_text(encoding="utf-8").lower()
    second_store.close()


def test_profile_state_reports_budget_exhaustion_before_credential_state(monkeypatch):
    monkeypatch.setattr(model_profiles, "keychain_service_exists", lambda _service: False)
    config = model_profiles.load_model_provider_config()

    states = model_profiles.describe_model_profiles(
        config,
        active_profile_id=None,
        weekly_calls_used=config.weekly_call_limit,
        project_ai_authorized=True,
        model_run_accounting_available=True,
    )

    openai = next(state for state in states if state.id == "openai-gpt-4o")
    assert openai.status == "OVER_BUDGET"


def test_active_profile_selection_rejects_not_logged_in_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(model_profiles, "keychain_service_exists", lambda _service: False)
    monkeypatch.setattr(model_profiles, "cli_command_available", lambda _command: True)
    monkeypatch.setattr(model_profiles, "probe_cli_login", lambda _command: False)

    store = ProjectStateStore(tmp_path / "profiles.sqlite3")
    client = TestClient(create_workspace_app(store, critic_provider=DeterministicFixtureProvider()))

    resp = client.post("/api/v1/model-profiles/active", json={"profile_id": "claude-cli"})
    assert resp.status_code == 409
    assert "not logged in" in resp.json()["detail"].lower()

    store.close()
