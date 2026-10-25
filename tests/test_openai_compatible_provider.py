from __future__ import annotations

import json
import pytest

from urban_design.model_profiles import ModelProviderProfile
from urban_design.model_provider import CriticRequest, NoRequestDispatched, OpenAICompatibleCriticProvider


@pytest.fixture(autouse=True)
def _authorize_fake_provider_tests(monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")


def _profile(*, supports_json_schema: bool = True) -> ModelProviderProfile:
    return ModelProviderProfile.model_validate({
        "id": "openai-test",
        "adapter": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-test",
        "keychain_service": "urban-design-test",
        "supports_json_schema": supports_json_schema,
        "data_egress": "cloud",
        "enabled": True,
    })


def test_openai_compatible_adapter_sends_bounded_json_schema_request_and_hides_key():
    captured = {}
    model_checks = []

    def fake_models(url, headers, timeout):
        model_checks.append((url, headers, timeout))
        return 200, {"data": [{"id": "gpt-4o-test"}]}

    def fake_transport(url, headers, body, timeout):
        captured.update({"url": url, "headers": headers, "body": body, "timeout": timeout})
        output = {
            "evidence_refs": ["card-area"],
            "observations": ["Observed metric."],
            "design_hypotheses": ["Test a design option."],
            "limitations": [],
            "next_questions": [],
        }
        return 200, {
            "id": "chatcmpl-fake",
            "model": "gpt-4o-2026-test",
            "choices": [{"message": {"content": json.dumps(output)}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 9},
        }

    provider = OpenAICompatibleCriticProvider(
        _profile(),
        api_key="fake-secret-never-returned",
        transport=fake_transport,
        model_list_transport=fake_models,
        request_id_factory=lambda: "request-test-1",
    )
    result = provider.generate_criticism(CriticRequest(
        study_area_id="area-v5",
        query="Describe this card.",
        evidence_bundle=[{"card_id": "card-area", "value": 12, "unit": "m²"}],
    ))

    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert model_checks[0][0] == "https://api.openai.com/v1/models"
    assert len(model_checks) == 1
    assert captured["headers"]["Authorization"] == "Bearer fake-secret-never-returned"
    assert captured["body"]["max_tokens"] == 2048
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert captured["timeout"] == 30
    assert result["provider_status"] == "LIVE_AI: ACTIVE"
    assert result["provider_profile_id"] == "openai-test"
    assert result["provider_model"] == "gpt-4o-2026-test"
    assert result["provider_request_id"] == "request-test-1"
    assert "fake-secret-never-returned" not in json.dumps(result)
    assert len(result["provider_metadata"]["request_sha256"]) == 64
    assert len(result["provider_metadata"]["response_sha256"]) == 64


def test_openai_compatible_transport_loss_is_outcome_unknown_without_retry():
    calls = []

    def lost_transport(*_args):
        calls.append("sent")
        raise TimeoutError("connection lost after dispatch")

    provider = OpenAICompatibleCriticProvider(
        _profile(),
        api_key="fake-key",
        transport=lost_transport,
        model_list_transport=lambda *_args: (200, {"data": [{"id": "gpt-4o-test"}]}),
        request_id_factory=lambda: "request-timeout-1",
    )
    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert calls == ["sent"]
    assert result["provider_status"] == "LIVE_AI: OUTCOME_UNKNOWN"
    assert result["provider_request_id"] == "request-timeout-1"
    assert result["observations"] == []


def test_explicit_pre_dispatch_connection_failure_is_distinguishable_from_unknown():
    provider = OpenAICompatibleCriticProvider(
        _profile(),
        api_key="fake-key",
        transport=lambda *_args: (_ for _ in ()).throw(NoRequestDispatched("refused before send")),
        model_list_transport=lambda *_args: (200, {"data": [{"id": "gpt-4o-test"}]}),
    )

    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_status"] == "LIVE_AI: CONNECTION_FAILED"
    assert result["provider_metadata"]["delivery"] == "not_started"


def test_project_authorization_gate_prevents_any_provider_request(monkeypatch):
    monkeypatch.delenv("PROJECT_AI_AUTHORIZED", raising=False)
    calls = []
    provider = OpenAICompatibleCriticProvider(
        _profile(),
        api_key="fake-key",
        transport=lambda *args: calls.append(args),
    )

    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_status"] == "LIVE_AI: BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED"
    assert calls == []


def test_live_provider_is_blocked_by_default_without_project_authorization(monkeypatch):
    monkeypatch.delenv("PROJECT_AI_AUTHORIZED", raising=False)
    calls = []
    provider = OpenAICompatibleCriticProvider(
        _profile(),
        api_key="fake-key",
        model_list_transport=lambda *args: calls.append(("GET", args)),
        transport=lambda *args: calls.append(("POST", args)),
    )

    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_status"] == "LIVE_AI: BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED"
    assert provider.is_live_available is False
    assert calls == []


def test_profile_model_list_is_checked_once_per_provider_instance():
    model_checks = []
    chat_calls = []
    provider = OpenAICompatibleCriticProvider(
        _profile(),
        api_key="fake-key",
        model_list_transport=lambda *args: model_checks.append(args) or (200, {"data": [{"id": "gpt-4o-test"}]}),
        transport=lambda *args: chat_calls.append(args) or (200, {
            "model": "gpt-4o-version",
            "choices": [{"message": {"content": json.dumps({
                "evidence_refs": [],
                "observations": [],
                "design_hypotheses": ["A bounded hypothesis."],
                "limitations": [],
                "next_questions": [],
            })}}],
        }),
    )

    first = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))
    second = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert first["provider_status"] == second["provider_status"] == "LIVE_AI: ACTIVE"
    assert len(model_checks) == 1
    assert len(chat_calls) == 2


def test_configured_model_missing_from_profile_list_blocks_without_chat_request():
    chat_calls = []
    provider = OpenAICompatibleCriticProvider(
        _profile(),
        api_key="fake-key",
        model_list_transport=lambda *_args: (200, {"data": [{"id": "different-model"}]}),
        transport=lambda *args: chat_calls.append(args),
    )

    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_status"] == "LIVE_AI: BLOCKED_CONFIGURED_MODEL_NOT_FOUND"
    assert result["provider_metadata"]["configured_model"] == "gpt-4o-test"
    assert provider.is_live_available is False
    assert provider.status == "BLOCKED_CONFIGURED_MODEL_NOT_FOUND"
    assert chat_calls == []


def test_live_response_without_actual_model_version_is_not_reported_active():
    response = {
        "choices": [{"message": {"content": json.dumps({
            "evidence_refs": [],
            "observations": [],
            "design_hypotheses": ["A bounded hypothesis."],
            "limitations": [],
            "next_questions": [],
        })}}],
    }
    provider = OpenAICompatibleCriticProvider(
        _profile(),
        api_key="fake-key",
        model_list_transport=lambda *_args: (200, {"data": [{"id": "gpt-4o-test"}]}),
        transport=lambda *_args: (200, response),
    )

    result = provider.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_status"] == "LIVE_AI: MODEL_FAILED"
    assert result["provider_model"] == "gpt-4o-test"
