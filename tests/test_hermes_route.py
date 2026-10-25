from __future__ import annotations

import json
import pytest

from urban_design.model_profiles import ModelProviderProfile
from urban_design.model_provider import CriticRequest, HermesCriticProvider


@pytest.fixture(autouse=True)
def _authorize_fake_provider_tests(monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")


def _profile() -> ModelProviderProfile:
    return ModelProviderProfile.model_validate({
        "id": "hermes-urban-critic",
        "adapter": "openai_compatible",
        "base_url": "http://127.0.0.1:8790/v1",
        "model": "hermes-test-model",
        "keychain_service": "urban-design-hermes",
        "supports_json_schema": False,
        "data_egress": "hermes",
        "enabled": True,
    })


def test_hermes_checks_toolsets_first_and_sends_no_session_key():
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(("GET", url, dict(headers), timeout))
        if url.endswith("/toolsets"):
            return 200, {"version": "hermes-test", "toolsets": []}
        return 200, {"data": [{"id": "hermes-test-model"}]}

    def fake_post(url, headers, body, timeout):
        calls.append(("POST", url, dict(headers), timeout))
        result = {
            "evidence_refs": [],
            "observations": [],
            "design_hypotheses": ["Test one bounded hypothesis."],
            "limitations": [],
            "next_questions": [],
        }
        return 200, {
            "model": "hermes-returned-model",
            "choices": [{"message": {"content": json.dumps(result)}}],
        }

    provider = HermesCriticProvider(
        _profile(),
        api_key="fake-hermes-server-key",
        get_transport=fake_get,
        transport=fake_post,
        request_id_factory=lambda: "request-hermes-1",
    )
    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert calls[0][0:2] == ("GET", "http://127.0.0.1:8790/v1/toolsets")
    assert calls[0][2]["Authorization"] == "Bearer fake-hermes-server-key"
    assert calls[1][0:2] == ("GET", "http://127.0.0.1:8790/v1/models")
    assert calls[2][0:2] == ("POST", "http://127.0.0.1:8790/v1/chat/completions")
    assert all(call[2]["Authorization"] == "Bearer fake-hermes-server-key" for call in calls)
    assert "X-Hermes-Session-Key" not in calls[2][2]
    assert result["provider_status"] == "LIVE_AI: ACTIVE"
    assert result["provider_metadata"]["hermes_version"] == "hermes-test"


def test_hermes_refuses_any_enabled_toolset_before_chat_request():
    post_calls = []

    def fake_get(_url, _headers, _timeout):
        return 200, {"toolsets": [{"name": "filesystem", "enabled": True, "tools": [{"name": "read"}]}]}

    def fake_post(*_args):
        post_calls.append("POST")
        return 200, {}

    provider = HermesCriticProvider(
        _profile(),
        api_key="fake-hermes-server-key",
        get_transport=fake_get,
        transport=fake_post,
    )
    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_status"] == "LIVE_AI: HERMES_TOOLS_ENABLED"
    assert post_calls == []


def test_hermes_project_gate_stops_before_toolset_request(monkeypatch):
    monkeypatch.delenv("PROJECT_AI_AUTHORIZED", raising=False)
    calls = []
    provider = HermesCriticProvider(
        _profile(),
        api_key="fake-hermes-server-key",
        get_transport=lambda *args: calls.append(("GET", args)),
        transport=lambda *args: calls.append(("POST", args)),
    )

    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_status"] == "LIVE_AI: BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED"
    assert calls == []
