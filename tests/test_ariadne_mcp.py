"""Tests for Ariadne MCP Server tools, guardrails, and platform integration."""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore
from urban_design.ariadne_mcp import create_ariadne_mcp_server
from urban_design.ariadne_mcp.client import AriadneApiClient
from urban_design.ariadne_mcp.guardrails import (
    GuardrailViolationError,
    SYNTAX_WARNING,
    assert_no_human_decision_attempt,
    enforce_agent_actor_metadata,
)
from urban_design.ariadne_mcp.tools import AriadneToolSet, PORTFOLIO_ORIGINAL_BASELINE


@pytest.fixture
def test_app_and_client(tmp_path: Path):
    store = ProjectStateStore(tmp_path / "test-ariadne.sqlite3")
    artifact_root = tmp_path / "scenario-artifacts"
    app = create_workspace_app(store=store, scenario_artifact_root=artifact_root)
    http_client = TestClient(app)
    api_client = AriadneApiClient(base_url="http://testserver", http_client=http_client)
    toolset = AriadneToolSet(client=api_client)
    server = create_ariadne_mcp_server(client=api_client, toolset=toolset)
    return {
        "app": app,
        "http_client": http_client,
        "api_client": api_client,
        "toolset": toolset,
        "server": server,
        "store": store,
    }


def test_mcp_server_registers_all_required_tools(test_app_and_client) -> None:
    server = test_app_and_client["server"]
    tools = asyncio.run(server.list_tools())
    tool_names = {t.name for t in tools}

    expected_tools = {
        "get_site_analysis",
        "get_syntax_layers",
        "get_surrounding_context_summary",
        "list_scenarios",
        "compare_scenarios",
        "draft_constraints",
        "run_preview_generation",
        "critique_scenario",
        "explain_decision_needed",
        "run_judgement",
        "list_judgements",
        "respond_to_judgement",
        "request_revision_proposal",
        "get_proposal",
        "get_design_dialogue",
    }
    assert expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}"
    assert not any("approve" in name or "human_decision" in name for name in tool_names)
    for tool in tools:
        language_schema = tool.input_schema["properties"]["language"]
        assert set(language_schema["enum"]) == {"zh-TW", "en"}


def test_tool_get_site_analysis_uses_fake_platform_record() -> None:
    class FakeClient:
        def get_site_analysis(self, project_id):
            return {
                "project_id": project_id,
                "study_area_id": "study-area-test-v1",
                "study_area_area_m2": 123.5,
                "crs": "EPSG:28992",
                "study_area_revision": 2,
                "source_package_revision": "spatial-test-v1",
                "evidence_cards_status": "VERIFIED_SOURCE_RESULT_ALIGNMENT",
                "evidence_bundle_sha256": "sha256:test-bundle",
                "evidence_cards": [{
                    "card_id": "card-test-1",
                    "metric_name": "test observation",
                    "value": 7,
                    "unit": "features",
                    "validation_status": "VALIDATED",
                    "limitations": [],
                }],
                "claims": [{"id": "claim-test-1", "statement": "Fixture claim."}],
                "report_summary": "Fixture report summary.",
                "limitations": ["Fixture-only test data."],
                "status": "VERIFIED",
            }

    toolset = AriadneToolSet(client=FakeClient())
    res = toolset.get_site_analysis(project_id="rotterdam-m4h")

    assert res["project_id"] == "rotterdam-m4h"
    assert res["study_area_area_m2"] == 123.5
    assert res["crs"] == "EPSG:28992"
    assert res["report_summary"] == "Fixture report summary."
    assert res["claims_count"] == 1
    assert len(res["claims"]) == res["claims_count"]
    assert res["evidence_cards"][0]["card_id"] == "card-test-1"
    assert res["evidence_cards"][0]["validation_status"] == "VALIDATED"
    assert res["study_area_revision"] == 2


def test_tool_get_site_analysis_reports_unavailable_without_fallback_data() -> None:
    class MissingClient:
        def get_site_analysis(self, **_kwargs):
            return {
                "status": "UNAVAILABLE",
                "error_class": "MissingRecordError",
                "reason": "No verified record.",
            }

    result = AriadneToolSet(client=MissingClient()).get_site_analysis()
    assert result["status"] == "UNAVAILABLE"
    assert result["error_class"] == "MissingRecordError"
    assert result["reason"] == "No verified record."
    assert "study_area_area_m2" not in result
    assert "evidence_cards" not in result


def test_tool_get_syntax_layers_includes_mandatory_warning() -> None:
    class FakeClient:
        def get_site_context(self, project_id):
            return {
                "project_id": project_id,
                "syntax_layers_status": "COMPUTED",
                "syntax_layers": [{"layer_id": "syntax-fixture", "calculation_status": "COMPUTED"}],
                "syntax_layer_plan": [{"radius_m": 800.0, "network_mode": "pedestrian"}],
                "syntax_limitations": ["Fixture-only test record."],
            }

    toolset = AriadneToolSet(client=FakeClient())
    res = toolset.get_syntax_layers(project_id="rotterdam-m4h")

    assert res["warning"] == SYNTAX_WARNING
    assert "不等於實際人流或交通量" in res["warning"]
    assert "Does NOT equal footfall or vehicular traffic volume" in res["warning"]
    assert "quantiles_definition" in res
    assert "q1_very_low" in res["quantiles_definition"]
    assert "q5_very_high" in res["quantiles_definition"]
    assert len(res["limitations"]) > 0
    assert res["layers"] == [{"layer_id": "syntax-fixture", "calculation_status": "COMPUTED"}]
    assert res["analysis_radii_m"]["pedestrian"] == 800.0


def test_tool_get_syntax_layers_reports_unavailable_without_fabricated_layers() -> None:
    class FailingClient:
        def get_site_context(self, **_kwargs):
            raise TimeoutError("private transport detail")

    result = AriadneToolSet(client=FailingClient()).get_syntax_layers(language="en")
    assert result["status"] == "UNAVAILABLE"
    assert result["error_class"] == "TimeoutError"
    assert result["reason"] == "The platform API request timed out."
    assert "layers" not in result
    assert result["analysis_radii_m"]["bicycle"] == 2000.0


def test_tool_get_surrounding_context_summary_uses_fake_platform_records() -> None:
    class FakeClient:
        def get_surrounding_context(self, project_id):
            return {
                "metadata": {
                    "project_id": project_id,
                    "crs": "EPSG:28992",
                    "context_distance_m": 2000.0,
                    "source": "OpenStreetMap",
                },
                "layers": {
                    "buildings": {"features": [{"id": "b-1"}]},
                    "water": {"features": []},
                    "green": {"features": [{"id": "g-1"}]},
                    "roads": {"features": [{"id": "r-1"}, {"id": "r-2"}]},
                },
            }

    toolset = AriadneToolSet(client=FakeClient())
    res = toolset.get_surrounding_context_summary(project_id="rotterdam-m4h")

    assert res["project_id"] == "rotterdam-m4h"
    assert res["crs"] == "EPSG:28992"
    assert res["context_distance_m"] == 2000.0
    assert res["source"] == "OpenStreetMap"
    assert "summary_zh" in res
    assert res["total_context_features"] == 4
    assert res["feature_breakdown"] == {"buildings": 1, "water": 0, "green": 1, "roads": 2}


def test_tool_get_surrounding_context_reports_unavailable_without_fallback() -> None:
    class MissingClient:
        def get_surrounding_context(self, **_kwargs):
            return {"status": "UNAVAILABLE", "error_class": "HTTPStatusError", "reason": "HTTP 404"}

    result = AriadneToolSet(client=MissingClient()).get_surrounding_context_summary()
    assert result["status"] == "UNAVAILABLE"
    assert result["error_class"] == "HTTPStatusError"
    assert "total_context_features" not in result


def test_tool_list_and_compare_scenarios_uses_fake_platform_records() -> None:
    class FakeClient:
        def list_scenarios(self):
            return [{"scenario_id": "persisted-1"}]

        def list_fabric_plans(self):
            return {
                "status": "EXPLORATORY_DRAFT",
                "plans": [
                    {"fabric_id": "harbour_grain", "label_zh": "港埠線性紋理", "metrics": {"far": 0.91}},
                    {"fabric_id": "closed_block_extension", "label_zh": "圍合街廓延伸", "metrics": {"far": 0.82}},
                    {"fabric_id": "courtyard_islands", "label_zh": "大型院落島", "metrics": {"far": 0.76}},
                    {"fabric_id": "landscape_figure", "label_zh": "地景為圖", "metrics": {"far": 0.68}},
                ],
            }

        def compare_scenarios(self, ids):
            return {
                "scenario_ids": ids,
                "status": "COMPARABLE",
                "metrics": [
                    {
                        "metric_id": "far",
                        "status": "COMPARABLE",
                        "unit": "ratio",
                        "values": {"scenario-a": 0.96, "scenario-b": 0.72},
                        "validation_status": {"scenario-a": "VALIDATED", "scenario-b": "VALIDATED"},
                        "denominators": {
                            "scenario-a": {"label": "land_area", "area_m2": 1000.0},
                            "scenario-b": {"label": "land_area", "area_m2": 1000.0},
                        },
                    }
                ],
            }

    toolset = AriadneToolSet(client=FakeClient())
    listed = toolset.list_scenarios(include_assumed=True, include_portfolio_baseline=True)

    previews = listed["assumed_previews"]
    assert [p["fabric_id"] for p in previews] == [
        "harbour_grain", "closed_block_extension", "courtyard_islands", "landscape_figure"
    ]
    assert all(p["status"] == "EXPLORATORY_DRAFT" for p in previews)
    assert previews[0]["metrics"] == {"far": 0.91}
    assert listed["status"] == "AVAILABLE"
    assert listed["portfolio_original_baseline"] == PORTFOLIO_ORIGINAL_BASELINE
    assert PORTFOLIO_ORIGINAL_BASELINE["designer"] == "the author (Q2 studio design)"
    assert PORTFOLIO_ORIGINAL_BASELINE["status"] == "PORTFOLIO_BASELINE_APPROX"
    baseline_metrics = PORTFOLIO_ORIGINAL_BASELINE["baseline_metrics"]
    assert baseline_metrics["far"]["value"] == 0.8
    assert baseline_metrics["far"]["denominator"] == "land_area"
    assert baseline_metrics["max_height_m"]["value"] == 20.0
    assert baseline_metrics["open_space_ratio"]["value"] == 0.4
    assert baseline_metrics["open_space_ratio"]["role"] == "preference"
    assert "coverage_ratio" not in baseline_metrics

    compared = toolset.compare_scenarios(["scenario-a", "scenario-b"], include_portfolio_baseline=True)
    assert compared["scenario_comparison"]["status"] == "COMPARABLE"
    assert compared["portfolio_baseline"] == PORTFOLIO_ORIGINAL_BASELINE
    analysis = compared["designer_differences_analysis"]
    assert "scenario-a" in analysis and "+0.160" in analysis
    assert "scenario-b" in analysis and "-0.080" in analysis
    assert "15m" in analysis
    assert "Gusto" in analysis and "Keilepand" in analysis


def test_tool_list_scenarios_reports_fabric_api_failure_without_previews() -> None:
    class FailingClient:
        def list_scenarios(self):
            return []

        def list_fabric_plans(self):
            raise TimeoutError("platform unavailable")

    listed = AriadneToolSet(client=FailingClient()).list_scenarios()
    assert listed["assumed_previews"] == []
    assert listed["status"] == "UNAVAILABLE"
    assert listed["error_class"] == "TimeoutError"
    assert listed["reason"] == "The platform API request timed out."


def test_tool_compare_scenarios_reports_client_failure_without_mock_metrics() -> None:
    class FailingClient:
        def compare_scenarios(self, _ids):
            raise OSError("platform unavailable")

    compared = AriadneToolSet(client=FailingClient()).compare_scenarios(["scenario-a", "scenario-b"])
    assert compared["status"] == "UNAVAILABLE"
    assert compared["scenario_comparison"]["status"] == "UNAVAILABLE"
    assert compared["scenario_comparison"]["error_class"] == "OSError"
    assert compared["scenario_comparison"]["reason"] == "The platform API request failed."
    assert "metrics_matrix" not in compared["scenario_comparison"]
    assert "2.85" not in compared["designer_differences_analysis"]


def test_tool_draft_constraints_produces_draft_without_activating() -> None:
    class FakeClient:
        def create_constraint_set_draft(self, project_id, constraints, **_kwargs):
            return {
                "constraint_set": {
                    "id": "constraint-set-test",
                    "project_id": project_id,
                    "constraints": constraints,
                    "status": "DRAFT_PENDING_HUMAN_DECISION",
                }
            }

    toolset = AriadneToolSet(client=FakeClient())
    res = toolset.draft_constraints(
        prompt="容積率上限 3.2，建築高度上限 35m，保留 20% 開放空間",
        far_upper_bound=3.2,
        max_height_m=35.0,
        min_open_space_ratio=0.20,
    )

    assert res["status"] == "DRAFT_PENDING_HUMAN_DECISION"
    assert res["legal_binding"] is False
    assert res["actor"] == "agent-ariadne"
    assert res["actor_kind"] == "AGENT_AUTOMATION"
    assert "DRAFT_PENDING_HUMAN_DECISION" in res["designer_guidance"]
    assert "HumanDecision" in res["designer_guidance"]

    # Verify drafted constraints content
    draft = res["draft_constraint_set"]
    constraints = draft.get("constraints", [])
    metrics = {c["metric"]: c["target_value"] for c in constraints}
    assert metrics.get("far") == 3.2
    assert metrics.get("max_height_m") == 35.0
    assert metrics.get("open_space_ratio") == 0.20
    assert res["parameters"]["waterfront_setback_m"] == {"value": None, "status": "NOT_SPECIFIED"}
    assert res["draft_constraint_set"]["parameters"]["waterfront_setback_m"]["status"] == "NOT_SPECIFIED"


def test_tool_draft_constraints_leaves_unspecified_values_empty() -> None:
    class MustNotCallClient:
        def create_constraint_set_draft(self, **_kwargs):
            raise AssertionError("An empty constraint set must not be submitted")

    result = AriadneToolSet(client=MustNotCallClient()).draft_constraints(
        prompt="Use a sensible FAR and height."
    )
    assert result["status"] == "NOT_SPECIFIED"
    assert result["draft_constraint_set"]["constraints"] == []
    for parameter in result["draft_constraint_set"]["parameters"].values():
        assert parameter == {"value": None, "status": "NOT_SPECIFIED"}


def test_tool_draft_constraints_reports_api_failure_without_fake_draft() -> None:
    class FailingClient:
        def create_constraint_set_draft(self, **_kwargs):
            raise ConnectionError("transport detail")

    result = AriadneToolSet(client=FailingClient()).draft_constraints("FAR 2.5", far_upper_bound=2.5)
    assert result["status"] == "UNAVAILABLE"
    assert result["error_class"] == "ConnectionError"
    assert result["reason"] == "The platform API connection failed."
    assert "draft_constraint_set" not in result


def test_tool_run_preview_generation_marks_synthetic_inputs_and_unapproved_preview() -> None:
    class FakeClient:
        def create_fixture_scenarios(self, payload):
            return {"scenarios": [{"scenario_id": "fixture-preview-1", "status": "UNAPPROVED_PREVIEW"}]}

    toolset = AriadneToolSet(client=FakeClient())
    res = toolset.run_preview_generation(seed=42)

    assert res["status"] == "UNAPPROVED_PREVIEW"
    assert res["provenance"] == "SYNTHETIC_TEST_INPUT"
    assert res["preview_inputs"]["status"] == "SYNTHETIC_TEST_INPUT"
    assert res["preview_inputs"]["width_m"] == 100.0
    assert res["preview_inputs"]["height_m"] == 80.0
    assert res["authority_db_written"] is False
    assert res["human_decision_created"] is False
    assert res["generated_candidates"] == [{"scenario_id": "fixture-preview-1", "status": "UNAPPROVED_PREVIEW"}]
    assert "UNAPPROVED_PREVIEW" in res["note_zh"]


def test_tool_run_preview_generation_reports_unavailable_without_fake_candidates() -> None:
    class FailingClient:
        def create_fixture_scenarios(self, _payload):
            raise OSError("transport detail")

    result = AriadneToolSet(client=FailingClient()).run_preview_generation()
    assert result["status"] == "UNAVAILABLE"
    assert result["error_class"] == "OSError"
    assert result["preview_inputs"]["status"] == "SYNTHETIC_TEST_INPUT"
    assert "generated_candidates" not in result


def test_tool_critique_scenario_validates_citations_and_provenance_with_fake_client() -> None:
    class FakeClient:
        def get_site_analysis(self, **_kwargs):
            return {
                "study_area_id": "study-area-test-v1",
                "study_area_area_m2": 250.0,
                "crs": "EPSG:28992",
                "study_area_revision": 3,
                "source_package_revision": "spatial-test-v1",
                "evidence_cards_status": "VERIFIED_SOURCE_RESULT_ALIGNMENT",
                "evidence_bundle_sha256": "sha256:test-bundle",
                "claims": [{"id": "claim-test-1"}],
                "report_summary": "Fixture report summary.",
                "status": "VERIFIED",
                "evidence_cards": [{
                    "card_id": "card-verified-test",
                    "metric_name": "Verified test observation",
                    "value": 5,
                    "unit": "features",
                    "validation_status": "VALIDATED",
                }],
            }

        def get_workspace_decision_summary(self, _workspace_id):
            return {"workspace_id": "workspace-test", "revision": 4}

        def evaluate_critic(self, request):
            assert request["evidence_card_ids"] == ["card-verified-test"]
            assert request["expected_study_area_revision"] == 3
            assert request["expected_workspace_revision"] == 4
            return {
                "critic_id": "critic-ariadne-test",
                "study_area_id": "study-area-test-v1",
                "evidence_refs": ["card-verified-test"],
                "observations": ["The saved evidence is linked [card-verified-test]."],
                "design_hypotheses": ["Review the cited observation with the designer."],
                "limitations": ["This fake response tests citation plumbing only."],
                "next_questions": [],
                "provider_name": "fake-provider",
                "provider_profile_id": "fixture",
                "provider_model": "fixture-model",
                "provider_status": "FIXTURE_ONLY",
            }

    toolset = AriadneToolSet(client=FakeClient())
    res = toolset.critique_scenario(
        scenario_id="preview-site-grid-assumed",
        prompt="請依據證據卡分析此方案的容積分布與水岸可及性",
    )

    assert res["scenario_id"] == "preview-site-grid-assumed"
    assert res["guardrail_status"] == "PASSED_EVIDENCE_GATE"
    assert "model_run_provenance" in res
    assert res["model_run_provenance"]["provider_name"] is not None

    critic = res["critic_evaluation"]
    assert "observations" in critic
    assert "design_hypotheses" in critic
    # Check that observations contain evidence card citation
    for obs in critic["observations"]:
        assert "[" in obs and "]" in obs


def test_tool_critique_scenario_reports_unavailable_without_fabricated_critique() -> None:
    class MissingClient:
        def get_site_analysis(self, **_kwargs):
            return {"status": "UNAVAILABLE", "error_class": "MissingRecordError", "reason": "No evidence."}

        def evaluate_critic(self, _request):
            raise AssertionError("Critic API must not be called without evidence")

    result = AriadneToolSet(client=MissingClient()).critique_scenario("scenario-test")
    assert result["status"] == "UNAVAILABLE"
    assert result["error_class"] == "MissingRecordError"
    assert "critic_evaluation" not in result


def test_tool_explain_decision_needed_uses_api_counts() -> None:
    class FakeClient:
        def get_workspace_decision_summary(self, workspace_id):
            return {
                "workspace_id": workspace_id,
                "revision": 2,
                "dispositions": {
                    "buildings": {"counts": {"total": 51, "undecided": 9}},
                    "roads": {"counts": {"total": 12, "undecided": 3}},
                },
            }

    toolset = AriadneToolSet(client=FakeClient())
    res = toolset.explain_decision_needed(project_id="rotterdam-m4h")

    assert res["project_id"] == "rotterdam-m4h"
    assert res["constitutional_core_law"] == "LLMs reason. Deterministic tools calculate. Validators verify. Humans decide."
    assert "PD-14" in res["pd14_protection_rule"]
    assert "HumanDecision" in res["pd14_protection_rule"]
    assert res["pending_decisions_count"] == 1
    description = res["pending_decisions"][0]["description"]
    assert "51 個 BAG 建築圖徵" in description
    assert "12 個道路段" in description
    assert "9 個建築與 3 個道路段仍為 UNDECIDED" in description


def test_tool_explain_decision_needed_omits_counts_when_api_has_none() -> None:
    class FakeClient:
        def get_workspace_decision_summary(self, workspace_id):
            return {"workspace_id": workspace_id, "revision": 2}

    result = AriadneToolSet(client=FakeClient()).explain_decision_needed(language="en")
    assert result["pending_decisions"] == []
    assert "51" not in str(result)


def test_tool_explain_decision_needed_reports_missing_summary() -> None:
    class MissingClient:
        def get_workspace_decision_summary(self, _workspace_id):
            raise LookupError("workspace missing")

    result = AriadneToolSet(client=MissingClient()).explain_decision_needed()
    assert result["status"] == "UNAVAILABLE"
    assert result["error_class"] == "LookupError"
    assert "pending_decisions" not in result


# --- Guardrail Tests ---

def test_guardrail_rejects_decision_key_and_passphrases() -> None:
    with pytest.raises(GuardrailViolationError, match="decision passphrase or key"):
        assert_no_human_decision_attempt(decision_key="my-secret-key")

    with pytest.raises(GuardrailViolationError, match="decision passphrase or key"):
        assert_no_human_decision_attempt(passphrase="super-secret")

    with pytest.raises(GuardrailViolationError, match="decision passphrase or key"):
        assert_no_human_decision_attempt(password="123456")


def test_guardrail_rejects_human_decision_attempts() -> None:
    with pytest.raises(GuardrailViolationError, match="cannot create HumanDecision"):
        assert_no_human_decision_attempt(target_type="HumanDecision", action="APPROVE")

    with pytest.raises(GuardrailViolationError, match="cannot create or forge HumanDecision"):
        assert_no_human_decision_attempt(action="APPROVE", actor_kind="HUMAN_UI")


def test_guardrail_blocks_sensitive_calls_in_tools(test_app_and_client) -> None:
    toolset = test_app_and_client["toolset"]

    with pytest.raises(GuardrailViolationError):
        toolset.draft_constraints(
            prompt="Make a decision",
            decision_key="designer-passphrase-attempt",
        )

    with pytest.raises(GuardrailViolationError):
        toolset.run_preview_generation(passphrase="attempt-auth")


def test_enforce_agent_actor_metadata() -> None:
    meta = enforce_agent_actor_metadata({})
    assert meta["actor"] == "agent-ariadne"
    assert meta["actor_kind"] == "AGENT_AUTOMATION"
    assert meta["actor_session_id"] == "ariadne-mcp-session"


# --- FastAPI Read-only Endpoints Integration Test ---

def test_api_read_only_site_analysis_and_portfolio_baseline(test_app_and_client) -> None:
    client: TestClient = test_app_and_client["http_client"]

    # 1. Test /api/v1/portfolio/baseline
    resp = client.get("/api/v1/portfolio/baseline")
    assert resp.status_code == 200
    data = resp.json()
    assert data == PORTFOLIO_ORIGINAL_BASELINE
