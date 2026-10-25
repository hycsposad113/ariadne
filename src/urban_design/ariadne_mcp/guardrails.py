"""Guardrails and safety boundaries for Ariadne MCP Server.

Constitutional Law:
- LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.
- PD-14: HumanDecision requires the designer's explicit secret passphrase and cannot be created by AI.
- AI agents cannot make or override consequential design decisions.
- AI agent acts strictly under ActorKind.AGENT_AUTOMATION.
- Space syntax values do not equal footfall or traffic volumes.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

SYNTAX_WARNING = (
    "【重要警語】空間語法（Space Syntax）之整合度（Integration）與穿行度（Choice）"
    "計算為空間拓撲結構測度，不等於實際人流或交通量（Does NOT equal footfall or vehicular traffic volume）。"
    "未經驗證之人流推論屬無效主張。"
)

SENSITIVE_KEY_PATTERNS = [
    re.compile(r"decision[-_]?key", re.IGNORECASE),
    re.compile(r"passphrase", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret[-_]?key", re.IGNORECASE),
]


class GuardrailViolationError(ValueError):
    """Raised when an operation violates agent boundaries or constitutional rules."""


def assert_no_human_decision_attempt(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
    """Ensure that the caller is not attempting to create a HumanDecision or pass a decision passphrase."""
    combined: dict[str, Any] = {}
    if payload:
        combined.update(payload)
    combined.update(kwargs)

    for key, value in combined.items():
        for pattern in SENSITIVE_KEY_PATTERNS:
            if pattern.search(key):
                raise GuardrailViolationError(
                    f"Disallowed attempt to handle decision passphrase or key: {key!r}. "
                    "Ariadne is an AI agent and is prohibited by PD-14 from requesting, reading, "
                    "or storing designer decision passphrases."
                )
            if isinstance(value, str) and pattern.search(value):
                raise GuardrailViolationError(
                    "Disallowed reference to decision passphrase in payload. "
                    "AI agents must not handle decision authentication."
                )

    target_type = combined.get("target_type")
    action = combined.get("action")
    if target_type == "HumanDecision" or action in {"APPROVE", "REJECT", "OVERRIDE"}:
        actor_kind = combined.get("actor_kind")
        if actor_kind in {"HUMAN_UI", "HUMAN"}:
            raise GuardrailViolationError(
                "Ariadne cannot create or forge HumanDecision records with human actor kinds. "
                "Only the designer via platform UI can create HumanDecision."
            )
        raise GuardrailViolationError(
            "AI agents cannot create HumanDecision records. Decisions must be made by human designer."
        )


def enforce_agent_actor_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Force actor metadata to reflect agent automation."""
    data["actor"] = "agent-ariadne"
    data["actor_kind"] = "AGENT_AUTOMATION"
    if not data.get("actor_session_id"):
        data["actor_session_id"] = "ariadne-mcp-session"
    return data


def verify_evidence_card_ids(evidence_refs: list[str], allowed_card_ids: set[str]) -> list[str]:
    """Verify that cited evidence card IDs exist in the allowed set."""
    for ref in evidence_refs:
        if ref not in allowed_card_ids:
            raise GuardrailViolationError(
                f"Invalid evidence citation: {ref!r} does not exist in verified evidence cards."
            )
    return evidence_refs
