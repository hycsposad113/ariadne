from __future__ import annotations

from urban_design.model_provider import CriticRequest, ModelProviderRouter
import pytest


@pytest.fixture(autouse=True)
def _authorize_fake_router_tests(monkeypatch):
    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")


class _StubProvider:
    is_live_available = True

    def __init__(self, profile_id: str, result: dict):
        self.profile_id = profile_id
        self.provider_name = profile_id
        self.status = "LIVE_AI: CONFIGURED_NOT_CALLED"
        self.result = result
        self.calls = 0

    def generate_criticism(self, _request):
        self.calls += 1
        return dict(self.result)


def _result(profile_id: str, status: str, *, http_status: int | None = None):
    return {
        "critic_id": f"critic-{profile_id}",
        "study_area_id": "area-v5",
        "evidence_refs": [],
        "observations": [],
        "design_hypotheses": ["Test one bounded hypothesis."],
        "limitations": [],
        "next_questions": [],
        "provider_profile_id": profile_id,
        "provider_name": profile_id,
        "provider_model": f"{profile_id}-version",
        "provider_status": status,
        "provider_metadata": {"http_status": http_status} if http_status else {},
    }


def _router(primary, fallback, *, claims, finishes, claim=None):
    return ModelProviderRouter(
        providers={"primary": primary, "fallback": fallback},
        fallback_order=["primary", "fallback"],
        claim_request=claim or (lambda *args: claims.append(args) or True),
        finish_request=lambda *args: finishes.append(args) or True,
        request_id_factory=lambda: "router-request-1",
        weekly_call_limit=200,
    )


def test_router_falls_back_only_after_an_explicit_401_or_403_response():
    primary = _StubProvider("primary", _result("primary", "LIVE_AI: REQUEST_REJECTED", http_status=401))
    fallback = _StubProvider("fallback", _result("fallback", "LIVE_AI: ACTIVE"))
    claims, finishes = [], []
    router = _router(primary, fallback, claims=claims, finishes=finishes)

    result = router.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_profile_id"] == "fallback"
    assert [entry[0] for entry in claims] == ["primary", "fallback"]
    assert [entry[0] for entry in finishes] == ["primary", "fallback"]
    assert "observations" not in finishes[-1][2]
    assert primary.calls == fallback.calls == 1


def test_router_never_falls_back_after_outcome_unknown():
    primary = _StubProvider("primary", _result("primary", "LIVE_AI: OUTCOME_UNKNOWN"))
    fallback = _StubProvider("fallback", _result("fallback", "LIVE_AI: ACTIVE"))
    claims, finishes = [], []
    router = _router(primary, fallback, claims=claims, finishes=finishes)

    result = router.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_status"] == "LIVE_AI: OUTCOME_UNKNOWN"
    assert primary.calls == 1
    assert fallback.calls == 0
    assert len(claims) == len(finishes) == 1


def test_router_falls_back_after_a_confirmed_pre_dispatch_connection_failure():
    primary = _StubProvider("primary", _result("primary", "LIVE_AI: CONNECTION_FAILED"))
    primary.result["provider_metadata"] = {"delivery": "not_started"}
    fallback = _StubProvider("fallback", _result("fallback", "LIVE_AI: ACTIVE"))
    claims, finishes = [], []
    router = _router(primary, fallback, claims=claims, finishes=finishes)

    result = router.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_profile_id"] == "fallback"
    assert primary.calls == fallback.calls == 1
    assert len(claims) == len(finishes) == 2


def test_router_fails_closed_without_durable_call_accounting_or_when_budget_is_exhausted():
    primary = _StubProvider("primary", _result("primary", "LIVE_AI: ACTIVE"))
    fallback = _StubProvider("fallback", _result("fallback", "LIVE_AI: ACTIVE"))
    router = ModelProviderRouter(
        providers={"primary": primary, "fallback": fallback},
        fallback_order=["primary", "fallback"],
    )
    blocked = router.generate_criticism(CriticRequest(study_area_id="area-v5"))
    assert blocked["provider_status"] == "LIVE_AI: BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE"
    assert primary.calls == fallback.calls == 0


def test_router_checks_project_authorization_before_budget_or_provider_dispatch(monkeypatch):
    monkeypatch.delenv("PROJECT_AI_AUTHORIZED", raising=False)
    primary = _StubProvider("primary", _result("primary", "LIVE_AI: ACTIVE"))
    fallback = _StubProvider("fallback", _result("fallback", "LIVE_AI: ACTIVE"))
    claims, finishes = [], []
    router = ModelProviderRouter(
        providers={"primary": primary, "fallback": fallback},
        fallback_order=["primary", "fallback"],
        claim_request=lambda *args: claims.append(args) or True,
        finish_request=lambda *args: finishes.append(args) or True,
    )

    result = router.generate_criticism(CriticRequest(study_area_id="area-v5"))

    assert result["provider_status"] == "LIVE_AI: BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED"
    assert primary.calls == fallback.calls == 0
    assert claims == finishes == []

    monkeypatch.setenv("PROJECT_AI_AUTHORIZED", "1")
    exhausted = _router(primary, fallback, claims=[], finishes=[], claim=lambda *_args: False)
    blocked = exhausted.generate_criticism(CriticRequest(study_area_id="area-v5"))
    assert blocked["provider_status"] == "LIVE_AI: BLOCKED_BUDGET"
    assert primary.calls == fallback.calls == 0
