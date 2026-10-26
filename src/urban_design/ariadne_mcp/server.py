"""Ariadne MCP Server implementation using Python MCP SDK."""

from __future__ import annotations

import sys
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from .client import AriadneApiClient
from .tools import AriadneToolSet, with_requested_language


def create_ariadne_mcp_server(
    client: AriadneApiClient | None = None,
    toolset: AriadneToolSet | None = None,
) -> MCPServer:
    """Create and configure the Ariadne MCP Server instance with all tools."""
    tools = toolset or AriadneToolSet(client=client)
    server = MCPServer(
        name="ariadne",
        instructions=(
            "You are Ariadne, the Rotterdam M4H urban-design partner. Use each tool's language "
            "parameter (zh-TW or en) for generated judgement and proposal content. Preserve source "
            "records in their original language. Never approve a proposal, create a HumanDecision, "
            "or request a decision passphrase; the designer decides in the platform. Do not invent "
            "data, and do not describe Space Syntax as measured footfall or traffic. "
            "你是 Rotterdam M4H 都市設計平台的 AI 夥伴；遵循證據先於建議、不可偽造數據，且不可代行設計者決策。"
        ),
    )

    @server.tool()
    def get_site_analysis(project_id: str = "rotterdam-m4h", language: Literal["zh-TW", "en"] = "zh-TW") -> dict[str, Any]:
        """取得平台目前已驗證的基地分析記錄與證據卡。"""
        return with_requested_language(tools.get_site_analysis(project_id=project_id, language=language), language)

    @server.tool()
    def get_syntax_layers(project_id: str = "rotterdam-m4h", language: Literal["zh-TW", "en"] = "zh-TW") -> dict[str, Any]:
        """取得平台目前的空間語法結果、五級分位與限制說明（附不等於人流／交通量警語）。"""
        return with_requested_language(tools.get_syntax_layers(project_id=project_id, language=language), language)

    @server.tool()
    def get_surrounding_context_summary(project_id: str = "rotterdam-m4h", language: Literal["zh-TW", "en"] = "zh-TW") -> dict[str, Any]:
        """取得基地周邊 2 km 空間環境摘要（包含 OSM 建築、水體、綠地、道路總覽）。"""
        return with_requested_language(tools.get_surrounding_context_summary(project_id=project_id, language=language), language)

    @server.tool()
    def list_scenarios(
        include_assumed: bool = True,
        include_portfolio_baseline: bool = True,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """列出已持久化方案、平台探索方案與 the designer 原設計基準。"""
        return with_requested_language(
            tools.list_scenarios(
                include_assumed=include_assumed,
                include_portfolio_baseline=include_portfolio_baseline,
                language=language,
            ),
            language,
        )

    @server.tool()
    def compare_scenarios(
        scenario_ids: list[str],
        include_portfolio_baseline: bool = True,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """對比多個方案之指標，並與 the designer 的 Q2 Portfolio 原設計基準進行差異對照。"""
        return with_requested_language(
            tools.compare_scenarios(
                scenario_ids=scenario_ids,
                include_portfolio_baseline=include_portfolio_baseline,
                language=language,
            ),
            language,
        )

    @server.tool()
    def draft_constraints(
        prompt: str,
        far_upper_bound: float | None = None,
        max_height_m: float | None = None,
        min_open_space_ratio: float | None = None,
        waterfront_setback_m: float | None = None,
        project_id: str = "rotterdam-m4h",
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """將自然語言設計意圖轉化為草稿 ConstraintSet 預覽（不生效，需設計者核准）。"""
        return with_requested_language(
            tools.draft_constraints(
                prompt=prompt,
                far_upper_bound=far_upper_bound,
                max_height_m=max_height_m,
                min_open_space_ratio=min_open_space_ratio,
                waterfront_setback_m=waterfront_setback_m,
                project_id=project_id,
                language=language,
            ),
            language,
        )

    @server.tool()
    def run_preview_generation(
        seed: int = 42,
        strategy_floor_count: int = 4,
        road_width_m: float = 6.0,
        project_id: str = "rotterdam-m4h",
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """呼叫假設輸入生成程序，產出探索型態預覽（只產生未核准預覽，不寫入權威資料庫）。"""
        return with_requested_language(
            tools.run_preview_generation(
                seed=seed,
                strategy_floor_count=strategy_floor_count,
                road_width_m=road_width_m,
                project_id=project_id,
                language=language,
            ),
            language,
        )

    @server.tool()
    def critique_scenario(
        scenario_id: str,
        prompt: str = "請依據已驗證證據卡，評論此方案的形態、容積與空間潛力與限制。",
        project_id: str = "rotterdam-m4h",
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """針對指定方案調用證據邊界 AI 批評服務，驗證主張並記錄 ModelRun 來源。"""
        return with_requested_language(
            tools.critique_scenario(
                scenario_id=scenario_id,
                prompt=prompt,
                project_id=project_id,
                language=language,
            ),
            language,
        )

    @server.tool()
    def explain_decision_needed(project_id: str = "rotterdam-m4h", language: Literal["zh-TW", "en"] = "zh-TW") -> dict[str, Any]:
        """列出當前工作區中等待 the designer 決策的事項，重申 AI 不得代行決策之規範。"""
        return with_requested_language(tools.explain_decision_needed(project_id=project_id, language=language), language)

    @server.tool()
    def run_judgement(
        skill_id: str,
        subject_ids: list[str],
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        """Run an evidence-bounded judgement in zh-TW or English; 回傳符合驗證規則的判讀卡。"""
        return tools.run_judgement(skill_id, subject_ids, language=language, project_id=project_id)

    @server.tool()
    def list_judgements(
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        """List stored judgements in the requested language; 只列出原語言相符的判讀卡。"""
        return tools.list_judgements(language=language, project_id=project_id)

    @server.tool()
    def respond_to_judgement(
        judgement_id: str,
        kind: Literal["agree", "contest", "supplement"],
        text: str,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        """Append an agent response, not a human decision; 新增 AI 回應而非人類決策。"""
        return tools.respond_to_judgement(
            judgement_id,
            kind,
            text,
            language=language,
            project_id=project_id,
        )

    @server.tool()
    def request_revision_proposal(
        card_id: str,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        """Request a validated revision proposal in zh-TW or English; 不會核准或套用提案。"""
        return tools.request_revision_proposal(card_id, language=language, project_id=project_id)

    @server.tool()
    def get_proposal(
        proposal_id: str,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        """Retrieve a stored proposal and mark the requested language; 方案正文保留原始語言。"""
        return tools.get_proposal(proposal_id, language=language, project_id=project_id)

    @server.tool()
    def get_design_dialogue(
        subject: str = "harbour_grain",
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        """Retrieve judgement, response and proposal history; 歷史內容保留各自原始語言。"""
        return tools.get_design_dialogue(subject, language=language, project_id=project_id)

    return server


def run_server() -> None:
    """Entrypoint for running the MCP server over stdio."""
    server = create_ariadne_mcp_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    run_server()
