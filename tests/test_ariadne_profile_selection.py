from urban_design import ariadne_chat
from urban_design.store import ProjectStateStore


def test_configured_ariadne_provider_uses_selected_json_schema_profile(tmp_path, monkeypatch):
    store = ProjectStateStore(tmp_path / "project.sqlite3")
    config = ariadne_chat.load_model_provider_config()
    created = []

    def create_provider(profile, **kwargs):
        created.append((profile.id, profile.supports_json_schema, kwargs))
        return object()

    monkeypatch.setattr(ariadne_chat, "create_profile_provider", create_provider)
    monkeypatch.setattr(ariadne_chat, "ModelProviderRouter", lambda **kwargs: kwargs)

    result = ariadne_chat._configured_ariadne_provider(
        store,
        "project-test",
        selected_profile_id="claude-cli",
    )

    assert created == [("claude-cli", True, {"cli_resolver": ariadne_chat.resolve_cli_executable, "use_ariadne_persona": True})]
    assert result["fallback_order"] == ["claude-cli"]
    assert set(result["providers"]) == {"claude-cli"}
    assert result["weekly_call_limit"] == config.weekly_call_limit
    store.close()


def test_configured_ariadne_api_profile_uses_injected_credential_resolver(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    store = ProjectStateStore(tmp_path / "project.sqlite3")
    created = []
    resolved_services = []

    def create_provider(profile, **kwargs):
        created.append((profile.id, kwargs))
        return object()

    def resolve_credential(service):
        resolved_services.append(service)
        return "fake-test-key"

    monkeypatch.setattr(ariadne_chat, "create_profile_provider", create_provider)
    monkeypatch.setattr(ariadne_chat, "ModelProviderRouter", lambda **kwargs: kwargs)

    result = ariadne_chat._configured_ariadne_provider(
        store,
        "project-test",
        selected_profile_id="openai-gpt-4o",
        credential_resolver=resolve_credential,
    )

    profile = next(item for item in ariadne_chat.load_model_provider_config().profiles if item.id == "openai-gpt-4o")
    assert resolved_services == [profile.keychain_service]
    assert created == [("openai-gpt-4o", {
        "cli_resolver": ariadne_chat.resolve_cli_executable,
        "use_ariadne_persona": True,
        "api_key": "fake-test-key",
    })]
    assert result["fallback_order"] == ["openai-gpt-4o"]
    store.close()


def test_configured_ariadne_api_profile_does_not_resolve_key_without_authorization(tmp_path, monkeypatch):
    monkeypatch.delenv("PROJECT_AI_AUTHORIZED", raising=False)
    store = ProjectStateStore(tmp_path / "project.sqlite3")
    resolved_services = []

    monkeypatch.setattr(ariadne_chat, "create_profile_provider", lambda profile, **kwargs: object())
    monkeypatch.setattr(ariadne_chat, "ModelProviderRouter", lambda **kwargs: kwargs)

    ariadne_chat._configured_ariadne_provider(
        store,
        "project-test",
        selected_profile_id="openai-gpt-4o",
        credential_resolver=lambda service: resolved_services.append(service),
    )

    assert resolved_services == []
    store.close()
