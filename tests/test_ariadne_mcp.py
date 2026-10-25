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


def test_tool_get_site_analysis(test_app_and_client) -> None:
    toolset = test_app_and_client["toolset"]
    res = toolset.get_site_analysis(project_id="rotterdam-m4h")

    assert res["project_id"] == "rotterdam-m4h"
    assert res["study_area_area_m2"] == 226064.33
    assert res["crs"] == "EPSG:28992"
    assert "report_summary" in res
    assert res["claims_count"] >= 20
    assert len(res["claims"]) == res["claims_count"]
    # Check claim format
    first_claim = res["claims"][0]
    assert "id" in first_claim
    assert "章節" in first_claim
    assert "敘述" in first_claim
    assert "數值" in first_claim
    assert "來源檔案或證據 ID" in first_claim
    assert len(res["limitations"]) > 0


def test_tool_get_syntax_layers_includes_mandatory_warning(test_app_and_client) -> None:
    toolset = test_app_and_client["toolset"]
    res = toolset.get_syntax_layers(project_id="rotterdam-m4h")

    assert res["warning"] == SYNTAX_WARNING
    assert "不等於實際人流或交通量" in res["warning"]
    assert "Does NOT equal footfall or vehicular traffic volume" in res["warning"]
    assert "quantiles_definition" in res
    assert "q1_very_low" in res["quantiles_definition"]
    assert "q5_very_high" in res["quantiles_definition"]
    assert len(res["limitations"]) > 0


def test_tool_get_surrounding_context_summary(test_app_and_client) -> None:
    toolset = test_app_and_client["toolset"]
    res = toolset.get_surrounding_context_summary(project_id="rotterdam-m4h")

    assert res["project_id"] == "rotterdam-m4h"
    assert res["crs"] == "EPSG:28992"
    assert res["context_distance_m"] == 2000.0
    assert res["source"] == "OpenStreetMap"
    assert "summary_zh" in res


def test_tool_list_and_compare_scenarios_includes_portfolio_baseline(test_app_and_client) -> None:
    toolset = test_app_and_client["toolset"]

    # 1. list_scenarios
    listed = toolset.list_scenarios(include_assumed=True, include_portfolio_baseline=True)
    assert "assumed_previews" in listed
    assert len(listed["assumed_previews"]) >= 3
    assert all(p["provenance"] == "ASSUMED" for p in listed["assumed_previews"])
    assert all(p["status"] == "UNAPPROVED_PREVIEW" for p in listed["assumed_previews"])
    assert listed["portfolio_original_baseline"] == PORTFOLIO_ORIGINAL_BASELINE
    assert PORTFOLIO_ORIGINAL_BASELINE["designer"] == "Jack Hsieh"
    assert PORTFOLIO_ORIGINAL_BASELINE["baseline_metrics"]["far"]["value"] == 2.85

    # 2. compare_scenarios
    compared = toolset.compare_scenarios(
        scenario_ids=["preview-site-grid-assumed", "preview-site-linear-green-axis-assumed"],
        include_portfolio_baseline=True,
    )
    assert "scenario_comparison" in compared
    assert "portfolio_baseline" in compared
    assert "designer_differences_analysis" in compared
    assert "the designer 原設計基準" in compared["designer_differences_analysis"]


def test_tool_draft_constraints_produces_draft_without_activating(test_app_and_client) -> None:
    toolset = test_app_and_client["toolset"]
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


def test_tool_run_preview_generation_marks_unapproved_preview(test_app_and_client) -> None:
    toolset = test_app_and_client["toolset"]
    res = toolset.run_preview_generation(seed=42)

    assert res["status"] == "UNAPPROVED_PREVIEW"
    assert res["provenance"] == "ASSUMED"
    assert res["authority_db_written"] is False
    assert res["human_decision_created"] is False
    assert len(res["generated_candidates"]) >= 3
    assert "UNAPPROVED_PREVIEW" in res["note_zh"]


def test_tool_critique_scenario_validates_citations_and_provenance(test_app_and_client) -> None:
    toolset = test_app_and_client["toolset"]
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


def test_tool_explain_decision_needed(test_app_and_client) -> None:
    toolset = test_app_and_client["toolset"]
    res = toolset.explain_decision_needed(project_id="rotterdam-m4h")

    assert res["project_id"] == "rotterdam-m4h"
    assert res["constitutional_core_law"] == "LLMs reason. Deterministic tools calculate. Validators verify. Humans decide."
    assert "PD-14" in res["pd14_protection_rule"]
    assert "HumanDecision" in res["pd14_protection_rule"]
    assert res["pending_decisions_count"] == 4


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
    assert data["designer"] == "Jack Hsieh"
    assert data["provenance"] == "PORTFOLIO_ORIGINAL_BASELINE"
    assert data["baseline_metrics"]["far"]["value"] == 2.85
    assert len(data["spatial_principles"]) >= 4
