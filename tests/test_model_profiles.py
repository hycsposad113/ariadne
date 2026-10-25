from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from urban_design.model_profiles import ModelProviderConfig, load_model_provider_config
from urban_design.model_provider import create_profile_provider


def test_default_model_profiles_keep_only_approved_fallback_order_and_no_secret_fields():
    config = load_model_provider_config()
    profiles = {profile.id: profile for profile in config.profiles}

    assert config.weekly_call_limit == 200
    assert config.max_output_tokens == 2048
    assert config.timeout_seconds == 30
    assert config.fallback_order == [
        "openai-gpt-4o",
        "hermes-urban-critic",
        "codex-cli",
        "claude-cli",
    ]
    assert profiles["openai-gpt-4o"].adapter == "openai_compatible"
    assert profiles["openai-gpt-4o"].model == "gpt-4o"
    assert profiles["hermes-urban-critic"].enabled is False
    assert profiles["hermes-urban-critic"].base_url == ""
    assert profiles["codex-cli"].adapter == "cli_subprocess"
    assert profiles["codex-cli"].cli_command == "codex"
    assert profiles["codex-cli"].model == "gpt-6-luna"
    assert profiles["claude-cli"].adapter == "cli_subprocess"
    assert profiles["claude-cli"].cli_command == "claude"
    assert "api_key" not in json.dumps(config.model_dump()).lower()
    assert "secret" not in json.dumps(config.model_dump()).lower()


def test_profile_refuses_reserved_runtime_ports():
    with pytest.raises(ValidationError, match="reserved"):
        ModelProviderConfig.model_validate({
            "weekly_call_limit": 200,
            "max_output_tokens": 2048,
            "timeout_seconds": 30,
            "fallback_order": ["hermes"],
            "profiles": [{
                "id": "hermes",
                "adapter": "openai_compatible",
                "base_url": "http://127.0.0.1:8787/v1",
                "model": "local-model",
                "keychain_service": None,
                "supports_json_schema": False,
                "data_egress": "hermes",
                "enabled": True,
                "fallback_priority": 1,
            }],
        })


def test_provider_factory_routes_enabled_profiles_without_reading_credentials(monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    config = load_model_provider_config()
    profile = next(item for item in config.profiles if item.id == "openai-gpt-4o")
    captured = []
    provider = create_profile_provider(
        profile,
        api_key="fake-test-key",
        transport=lambda *args: captured.append(args),
    )

    assert provider.provider_name == "openai"
    assert provider.is_live_available is True
    assert captured == []


def test_provider_factory_rejects_disabled_profiles():
    config = load_model_provider_config()
    profile = next(item for item in config.profiles if item.id == "hermes-urban-critic")

    with pytest.raises(ValueError, match="disabled"):
        create_profile_provider(profile)


def test_cli_login_probe_claude_and_codex(monkeypatch):
    from types import SimpleNamespace
    from urban_design import model_profiles

    model_profiles.clear_cli_login_cache()
    monkeypatch.setattr(model_profiles, "resolve_cli_executable", lambda cmd: f"/fake/{cmd}")
    monkeypatch.setenv("USER", "test-user")
    monkeypatch.setenv("HOME", "/fake/home")

    calls = []

    def fake_runner(args, **kwargs):
        calls.append((args, kwargs))
        if args[:3] == ["/fake/claude", "auth", "status"]:
            return SimpleNamespace(returncode=0, stdout='{"loggedIn": true}', stderr="")
        if args[:3] == ["/fake/codex", "login", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    # Claude logged in
    assert model_profiles.probe_cli_login("claude", runner=fake_runner, force_refresh=True) is True
    assert calls[0][0] == ["/fake/claude", "auth", "status"]
    assert calls[0][1]["timeout"] == 10
    assert calls[0][1]["env"]["USER"] == "test-user"
    assert calls[0][1]["env"]["HOME"] == "/fake/home"

    # Codex logged in
    assert model_profiles.probe_cli_login("codex", runner=fake_runner, force_refresh=True) is True
    assert calls[1][0] == ["/fake/codex", "login", "status"]
    assert calls[1][1]["timeout"] == 10

    # Claude not logged in
    def fake_runner_logged_out(args, **kwargs):
        if args[:3] == ["/fake/claude", "auth", "status"]:
            return SimpleNamespace(returncode=0, stdout='{"loggedIn": false}', stderr="")
        return SimpleNamespace(returncode=1, stdout="not logged in", stderr="")

    assert model_profiles.probe_cli_login("claude", runner=fake_runner_logged_out, force_refresh=True) is False
    assert model_profiles.probe_cli_login("codex", runner=fake_runner_logged_out, force_refresh=True) is False
    model_profiles.clear_cli_login_cache()


def test_cli_login_probe_caching(monkeypatch):
    from types import SimpleNamespace
    from urban_design import model_profiles

    model_profiles.clear_cli_login_cache()
    monkeypatch.setattr(model_profiles, "resolve_cli_executable", lambda cmd: f"/fake/{cmd}")

    call_count = 0

    def counting_runner(args, **kwargs):
        nonlocal call_count
        call_count += 1
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    model_profiles.set_cli_login_runner(counting_runner)
    try:
        assert model_profiles.probe_cli_login("codex") is True
        assert model_profiles.probe_cli_login("codex") is True
        assert call_count == 1  # Cached!
    finally:
        model_profiles.set_cli_login_runner(None)
        model_profiles.clear_cli_login_cache()


def test_describe_model_profiles_reports_not_logged_in(monkeypatch):
    from urban_design import model_profiles

    config = model_profiles.load_model_provider_config()
    states = model_profiles.describe_model_profiles(
        config,
        active_profile_id=None,
        weekly_calls_used=0,
        project_ai_authorized=True,
        model_run_accounting_available=True,
        cli_available=lambda cmd: True,
        cli_logged_in=lambda cmd: False,
    )
    codex = next(s for s in states if s.id == "codex-cli")
    assert codex.status == "NOT_LOGGED_IN"
    assert codex.status_detail == "CLI 尚未登入；請在終端機執行 claude 並使用 /login（或 codex login）後重新整理。"
    claude = next(s for s in states if s.id == "claude-cli")
    assert claude.status == "NOT_LOGGED_IN"
