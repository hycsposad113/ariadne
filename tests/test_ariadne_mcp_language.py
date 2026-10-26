from __future__ import annotations

import json

import httpx

from urban_design.ariadne_mcp.client import AriadneApiClient
from urban_design.ariadne_mcp.tools import AriadneToolSet


def test_judgement_and_proposal_client_calls_use_fake_transport_and_language():
    requests = []

    def fake_transport(request: httpx.Request) -> httpx.Response:
        requests.append({
            "method": request.method,
            "path": request.url.path,
            "query": dict(request.url.params),
            "body": json.loads(request.content) if request.content else None,
        })
        return httpx.Response(200, json={"ok": True})

    http_client = httpx.Client(
        base_url="http://ariadne.test",
        transport=httpx.MockTransport(fake_transport),
    )
    client = AriadneApiClient(base_url="http://ariadne.test", http_client=http_client)

    client.run_judgement("J-CLIMATE", ["harbour_grain"], language="en")
    client.list_judgements(language="en")
    client.respond_to_judgement("judgement-1", "contest", "Please reconsider the evidence.", language="en")
    client.request_revision_proposal("card-1", language="en")
    client.get_proposal("proposal-1", language="en")
    client.get_design_dialogue("harbour_grain", language="en")

    base = "/api/v1/projects/rotterdam-m4h/ariadne"
    assert requests == [
        {
            "method": "POST",
            "path": f"{base}/judgements",
            "query": {},
            "body": {"skill_id": "J-CLIMATE", "subject_ids": ["harbour_grain"], "language": "en"},
        },
        {"method": "GET", "path": f"{base}/judgements", "query": {"language": "en"}, "body": None},
        {
            "method": "POST",
            "path": f"{base}/judgements/judgement-1/responses",
            "query": {},
            "body": {
                "kind": "contest",
                "text": "Please reconsider the evidence.",
                "language": "en",
                "actor_kind": "AGENT",
                "actor_id": "agent-ariadne",
            },
        },
        {
            "method": "POST",
            "path": f"{base}/proposals",
            "query": {},
            "body": {"card_id": "card-1", "language": "en"},
        },
        {"method": "GET", "path": f"{base}/proposals/proposal-1", "query": {"language": "en"}, "body": None},
        {
            "method": "GET",
            "path": f"{base}/dialogue",
            "query": {"subject": "harbour_grain", "language": "en"},
            "body": None,
        },
    ]
    http_client.close()


def test_client_lists_fabric_plans_through_mock_transport():
    requests = []
    catalog = {
        "status": "EXPLORATORY_DRAFT",
        "plans": [{"fabric_id": "harbour_grain", "label_zh": "港埠線性紋理", "metrics": {"far": 0.91}}],
        "source_package": {"artifact_root": "fixture", "syntax_root": "fixture"},
    }

    def fake_transport(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json=catalog)

    http_client = httpx.Client(
        base_url="http://ariadne.test",
        transport=httpx.MockTransport(fake_transport),
    )
    client = AriadneApiClient(base_url="http://ariadne.test", http_client=http_client)

    assert client.list_fabric_plans() == catalog
    assert requests == [("GET", "/api/v1/fabric-plans")]
    http_client.close()


def test_missing_platform_record_is_unavailable_without_local_fallback():
    def missing_record(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/projects/rotterdam-m4h/site-analysis"
        return httpx.Response(404, json={"detail": "record missing"})

    http_client = httpx.Client(
        base_url="http://ariadne.test",
        transport=httpx.MockTransport(missing_record),
    )
    client = AriadneApiClient(base_url="http://ariadne.test", http_client=http_client)
    result = AriadneToolSet(client=client).get_site_analysis()
    assert result["status"] == "UNAVAILABLE"
    assert result["error_class"] == "HTTPStatusError"
    assert "HTTP 404" in result["reason"]
    assert "evidence_cards" not in result
    assert "study_area_area_m2" not in result
    http_client.close()


def test_toolset_forwards_language_for_agent_workflow_operations():
    class RecordingClient:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def call(*args, **kwargs):
                self.calls.append((name, args, kwargs))
                return {"ok": True}
            return call

    client = RecordingClient()
    toolset = AriadneToolSet(client=client)

    assert toolset.run_judgement("J-CLIMATE", ["harbour_grain"], language="en")["requested_language"] == "en"
    assert toolset.list_judgements(language="en")["requested_language"] == "en"
    assert toolset.respond_to_judgement("judgement-1", "contest", "Please reconsider.", language="en")["requested_language"] == "en"
    assert toolset.request_revision_proposal("card-1", language="en")["requested_language"] == "en"
    assert toolset.get_proposal("proposal-1", language="en")["requested_language"] == "en"
    assert toolset.get_design_dialogue("harbour_grain", language="en")["requested_language"] == "en"
    assert [name for name, _args, _kwargs in client.calls] == [
        "run_judgement",
        "list_judgements",
        "respond_to_judgement",
        "request_revision_proposal",
        "get_proposal",
        "get_design_dialogue",
    ]
    assert all(kwargs["language"] == "en" for _name, _args, kwargs in client.calls)


def test_toolset_fixed_text_and_source_language_annotation():
    class StubClient:
        def get_site_analysis(self, **kwargs):
            return {
                "project_id": kwargs["project_id"],
                "study_area_id": "study-area-fixture-v1",
                "study_area_area_m2": 500.0,
                "crs": "EPSG:28992",
                "study_area_revision": 1,
                "source_package_revision": "spatial-fixture-v1",
                "evidence_cards_status": "VERIFIED_SOURCE_RESULT_ALIGNMENT",
                "evidence_bundle_sha256": "sha256:fixture",
                "report_summary": "這是中文基地摘要",
                "evidence_cards": [{
                    "card_id": "card-fixture-1",
                    "metric_name": "fixture metric",
                    "value": 1,
                    "unit": "features",
                    "validation_status": "VALIDATED",
                }],
                "claims": [{"id": "claim-fixture-1"}],
                "limitations": ["fixture"],
                "status": "VERIFIED",
            }

        def get_site_context(self, **kwargs):
            return {
                "syntax_limitations": ["自訂空間語法限制"],
                "syntax_layers_status": "COMPUTED",
                "syntax_layers": [{"layer_id": "syntax-fixture", "calculation_status": "COMPUTED"}],
                "syntax_layer_plan": [{"radius_m": 800.0}],
            }

        def get_surrounding_context(self, **kwargs):
            return {
                "metadata": {"crs": "EPSG:28992", "context_distance_m": 2000.0, "source": "fixture"},
                "layers": {
                    "buildings": {"features": []},
                    "water": {"features": []},
                    "green": {"features": []},
                    "roads": {"features": []},
                },
            }

        def list_scenarios(self, **kwargs):
            return []

        def list_fabric_plans(self):
            return {
                "status": "EXPLORATORY_DRAFT",
                "plans": [{"fabric_id": "harbour_grain", "label_zh": "港埠線性紋理", "metrics": {"far": 0.91}}],
            }

        def compare_scenarios(self, ids, **kwargs):
            return {
                "scenario_ids": ids,
                "status": "COMPARABLE",
                "metrics": [{
                    "metric_id": "far",
                    "status": "COMPARABLE",
                    "unit": "ratio",
                    "values": {"s1": 1.1, "s2": 0.5},
                    "validation_status": {"s1": "VALIDATED", "s2": "VALIDATED"},
                    "denominators": {
                        "s1": {"label": "land_area"},
                        "s2": {"label": "land_area"},
                    },
                }],
            }

        def create_constraint_set_draft(self, **kwargs):
            return {"constraint_set": {
                "id": "constraint-fixture-1",
                "status": "DRAFT_PENDING_HUMAN_DECISION",
                "constraints": kwargs["constraints"],
            }}

        def create_fixture_scenarios(self, payload):
            return {"scenarios": [{"scenario_id": payload["fixture_id"]}]}

        def get_workspace_decision_summary(self, ws_id):
            return {
                "workspace_id": ws_id,
                "revision": 1,
                "dispositions": {
                    "buildings": {"counts": {"total": 51, "undecided": 10}},
                    "roads": {"counts": {"total": 7, "undecided": 2}},
                },
            }

    toolset = AriadneToolSet(client=StubClient())

    listed_en = toolset.list_scenarios(language="en")
    assert listed_en["assumed_previews"][0]["status"] == "EXPLORATORY_DRAFT"
    assert listed_en["assumed_previews"][0]["source_language"] == "zh-TW"

    # 1. explain_decision_needed in English
    en_decisions = toolset.explain_decision_needed(language="en")
    assert en_decisions["source_language"] == "zh-TW"
    assert "Under PD-14" in en_decisions["pd14_protection_rule"]
    assert en_decisions["pending_decisions"][0]["decision_area"] == "Existing Feature Dispositions"
    assert "51 BAG building features and 7 road segments" in en_decisions["pending_decisions"][0]["description"]
    assert "Jack" not in str(en_decisions)

    # 1b. explain_decision_needed in Chinese
    zh_decisions = toolset.explain_decision_needed(language="zh-TW")
    assert "既有特徵處分" in zh_decisions["pending_decisions"][0]["decision_area"]
    assert "Jack" not in str(zh_decisions)

    # 2. get_site_analysis preserves report_summary and adds source_language: zh-TW
    site = toolset.get_site_analysis(language="en")
    assert site["report_summary"] == "這是中文基地摘要"
    assert site["source_language"] == "zh-TW"

    # 3. get_syntax_layers in English
    syntax = toolset.get_syntax_layers(language="en")
    assert "IMPORTANT NOTICE: Space Syntax Integration and Choice" in syntax["warning"]
    assert syntax["quantiles_definition"]["q1_very_low"].startswith("Lowest 20%")
    assert syntax["metrics"][0].startswith("Integration (to-movement")
    assert syntax["source_language"] == "zh-TW"

    # 4. compare_scenarios in English vs Chinese
    cmp_en = toolset.compare_scenarios(["s1", "s2"], language="en")
    assert "[Key Comparisons with the designer's Original Baseline]:" in cmp_en["designer_differences_analysis"]
    assert "the designer" in cmp_en["designer_differences_analysis"]
    assert "+0.300" in cmp_en["designer_differences_analysis"]
    assert "-0.300" in cmp_en["designer_differences_analysis"]
    assert "Jack" not in cmp_en["designer_differences_analysis"]

    cmp_zh = toolset.compare_scenarios(["s1", "s2"], language="zh-TW")
    assert "【與 the designer 原設計基準對照重點】" in cmp_zh["designer_differences_analysis"]
    assert "+0.300" in cmp_zh["designer_differences_analysis"]
    assert "-0.300" in cmp_zh["designer_differences_analysis"]
    assert "Jack" not in cmp_zh["designer_differences_analysis"]

    # 5. draft_constraints in English vs Chinese
    draft_en = toolset.draft_constraints("test prompt", far_upper_bound=2.5, language="en")
    assert "[Draft Preview Completed]:" in draft_en["designer_guidance"]
    assert "Jack" not in str(draft_en)

    draft_zh = toolset.draft_constraints("test prompt", far_upper_bound=2.5, language="zh-TW")
    assert "【草稿預覽完成】" in draft_zh["designer_guidance"]
    assert "the designer" in draft_zh["designer_guidance"]
    assert "Jack" not in str(draft_zh)

    # 6. run_preview_generation in English
    gen_en = toolset.run_preview_generation(language="en")
    assert "[Unapproved Preview]:" in gen_en["note"]


def test_toolset_docstrings_remove_personal_name_jack():
    from urban_design.ariadne_mcp import server, tools

    # Toolset method docstrings
    for method_name in ["list_scenarios", "compare_scenarios", "explain_decision_needed"]:
        doc = getattr(tools.AriadneToolSet, method_name).__doc__ or ""
        assert "Jack" not in doc, f"Jack found in tools.AriadneToolSet.{method_name} docstring: {doc}"
        assert "the designer" in doc, f"Expected 'the designer' in tools.AriadneToolSet.{method_name} docstring: {doc}"
