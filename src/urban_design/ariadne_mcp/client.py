"""HTTP client for communicating with the urban design platform FastAPI server."""

from __future__ import annotations

import os
from typing import Any, Literal, Mapping

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8795"


class AriadneApiClient:
    """Client for Ariadne MCP to call platform FastAPI endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("ARIADNE_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def get_site_context(self, project_id: str = "rotterdam-m4h") -> dict[str, Any]:
        """Fetch site context including StudyArea, buildings, road segments, syntax layers, and cards."""
        resp = self._client.get(f"/api/v1/projects/{project_id}/site-context")
        resp.raise_for_status()
        return resp.json()

    def get_site_analysis(self, project_id: str = "rotterdam-m4h") -> dict[str, Any]:
        """Fetch the platform's current site analysis record without local fallbacks."""
        resp = self._client.get(f"/api/v1/projects/{project_id}/site-analysis")
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, Mapping):
            raise ValueError("Platform site-analysis response is not an object")
        return dict(payload)

    def get_surrounding_context(self, project_id: str = "rotterdam-m4h", tolerance_m: float = 0.0) -> dict[str, Any]:
        """Fetch hash-verified surrounding context layers (2 km buffer)."""
        resp = self._client.get(
            f"/api/v1/projects/{project_id}/surrounding-context",
            params={"tolerance_m": tolerance_m},
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, Mapping):
            raise ValueError("Platform surrounding-context response is not an object")
        return dict(payload)

    def list_scenarios(self) -> list[dict[str, Any]]:
        """List current persisted scenarios from the platform."""
        resp = self._client.get("/api/v1/scenarios")
        resp.raise_for_status()
        return resp.json().get("scenarios", [])

    def list_fabric_plans(self) -> dict[str, Any]:
        """List verified exploratory fabric plans and generator-computed metrics."""
        resp = self._client.get("/api/v1/fabric-plans")
        resp.raise_for_status()
        return resp.json()

    def compare_scenarios(self, scenario_ids: list[str]) -> dict[str, Any]:
        """Compare two or more persisted scenarios."""
        resp = self._client.post(
            "/api/v1/scenarios/comparison",
            json={"scenario_ids": scenario_ids},
        )
        resp.raise_for_status()
        return resp.json()

    def create_constraint_set_draft(
        self,
        project_id: str,
        constraints: list[dict[str, Any]],
        allocation_policy: str | None = None,
        actor_session_id: str = "ariadne-agent-session",
    ) -> dict[str, Any]:
        """Submit a draft ConstraintSet preview to the platform (does NOT activate)."""
        payload: dict[str, Any] = {
            "constraints": constraints,
            "actor_session_id": actor_session_id,
        }
        if allocation_policy:
            payload["allocation_policy"] = allocation_policy
        resp = self._client.post(
            f"/api/v1/projects/{project_id}/constraint-sets",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def create_fixture_scenarios(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Generate fixture-only scenario previews."""
        resp = self._client.post("/api/v1/scenarios/fixtures", json=request_data)
        resp.raise_for_status()
        return resp.json()

    def evaluate_critic(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Invoke evidence-bound critic inquiry endpoint."""
        resp = self._client.post("/api/v1/critic/evaluate", json=request_data)
        resp.raise_for_status()
        return resp.json()

    def get_workspace_decision_summary(self, workspace_id: str) -> dict[str, Any]:
        """Fetch workspace decision summary (pending dispositions, exploration area)."""
        resp = self._client.get(f"/api/v1/workspaces/{workspace_id}/decision-summary")
        resp.raise_for_status()
        return resp.json()

    def list_project_decisions(self, project_id: str) -> list[dict[str, Any]]:
        """List human decisions recorded for a project."""
        resp = self._client.get(f"/api/v1/projects/{project_id}/decisions")
        resp.raise_for_status()
        return resp.json()

    def run_judgement(
        self,
        skill_id: str,
        subject_ids: list[str],
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        resp = self._client.post(
            f"/api/v1/projects/{project_id}/ariadne/judgements",
            json={"skill_id": skill_id, "subject_ids": subject_ids, "language": language},
        )
        resp.raise_for_status()
        return resp.json()

    def list_judgements(
        self,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        resp = self._client.get(
            f"/api/v1/projects/{project_id}/ariadne/judgements",
            params={"language": language},
        )
        resp.raise_for_status()
        return resp.json()

    def respond_to_judgement(
        self,
        judgement_id: str,
        kind: Literal["agree", "contest", "supplement"],
        text: str,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        resp = self._client.post(
            f"/api/v1/projects/{project_id}/ariadne/judgements/{judgement_id}/responses",
            json={
                "kind": kind,
                "text": text,
                "language": language,
                "actor_kind": "AGENT",
                "actor_id": "agent-ariadne",
            },
        )
        resp.raise_for_status()
        return resp.json()

    def request_revision_proposal(
        self,
        card_id: str,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        resp = self._client.post(
            f"/api/v1/projects/{project_id}/ariadne/proposals",
            json={"card_id": card_id, "language": language},
        )
        resp.raise_for_status()
        return resp.json()

    def get_proposal(
        self,
        proposal_id: str,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        resp = self._client.get(
            f"/api/v1/projects/{project_id}/ariadne/proposals/{proposal_id}",
            params={"language": language},
        )
        resp.raise_for_status()
        return resp.json()

    def get_design_dialogue(
        self,
        subject: str = "harbour_grain",
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        resp = self._client.get(
            f"/api/v1/projects/{project_id}/ariadne/dialogue",
            params={"subject": subject, "language": language},
        )
        resp.raise_for_status()
        return resp.json()
