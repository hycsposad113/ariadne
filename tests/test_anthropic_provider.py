from __future__ import annotations

import json
import pytest

from urban_design.model_profiles import ModelProviderProfile
from urban_design.model_provider import AnthropicCriticProvider, CriticRequest


@pytest.fixture(autouse=True)
def _authorize_fake_provider_tests(monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")


def test_anthropic_adapter_uses_native_messages_request_and_local_json_validation():
    captured = {}
    model_checks = []

    def fake_transport(url, headers, body, timeout):
        captured.update({"url": url, "headers": headers, "body": body, "timeout": timeout})
        output = {
            "evidence_refs": [],
            "observations": [],
            "design_hypotheses": ["Test one design hypothesis."],
            "limitations": [],
            "next_questions": [],
        }
        return 200, {
            "id": "msg-fake",
            "model": "claude-sonnet-test-version",
            "content": [{"type": "text", "text": json.dumps(output)}],
            "usage": {"input_tokens": 15, "output_tokens": 10},
        }

    def fake_models(url, headers, timeout):
        model_checks.append((url, headers, timeout))
        return 200, {"data": [{"id": "claude-sonnet-test"}]}

    profile = ModelProviderProfile.model_validate({
        "id": "anthropic-test",
        "adapter": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-test",
        "keychain_service": "urban-design-anthropic-test",
        "supports_json_schema": False,
        "data_egress": "cloud",
        "enabled": True,
    })
    provider = AnthropicCriticProvider(
        profile,
        api_key="fake-anthropic-secret",
        transport=fake_transport,
        model_list_transport=fake_models,
        request_id_factory=lambda: "request-anthropic-1",
    )
    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5", evidence_bundle=[]))

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert model_checks[0][0] == "https://api.anthropic.com/v1/models"
    assert captured["headers"]["x-api-key"] == "fake-anthropic-secret"
    assert captured["headers"]["anthropic-version"]
    assert captured["body"]["model"] == "claude-sonnet-test"
    assert captured["body"]["max_tokens"] == 2048
    assert "JSON" in captured["body"]["system"]
    assert result["provider_status"] == "LIVE_AI: ACTIVE"
    assert result["provider_name"] == "anthropic"
    assert result["provider_model"] == "claude-sonnet-test-version"
    assert "fake-anthropic-secret" not in json.dumps(result)


def test_anthropic_project_gate_stops_before_transport(monkeypatch):
    monkeypatch.delenv("PROJECT_AI_AUTHORIZED", raising=False)
    calls = []
    profile = ModelProviderProfile.model_validate({
        "id": "anthropic-test",
        "adapter": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-test",
        "keychain_service": "urban-design-anthropic-test",
        "supports_json_schema": False,
        "data_egress": "cloud",
        "enabled": True,
    })
    provider = AnthropicCriticProvider(
        profile,
        api_key="fake-key",
        transport=lambda *args: calls.append(args),
        model_list_transport=lambda *args: calls.append(args),
    )

    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_status"] == "LIVE_AI: BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED"
    assert calls == []
