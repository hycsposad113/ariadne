"""Evidence-bound Ariadne conversation API with a separate transcript store."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from fastapi import APIRouter, Header, HTTPException, Path as FPath, Query
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from .analysis_persistence import get_persisted_site_analysis, get_persisted_syntax_bundle
from .model_profiles import (
    ModelProfileSelectionStore,
    default_ariadne_profile_id,
    load_model_provider_config,
    resolve_cli_executable,
)
from .model_provider import (
    CriticRequest,
    ModelProviderRouter,
    ProjectStateModelRunAccounting,
    create_profile_provider,
    _read_keychain_secret,
)
from .r03_syntax import load_verified_exploratory_syntax
from .site_critic import CriticValidationError, SiteCriticService
from .store import ProjectStateStore
from .workspace_service import WorkspaceService


_LEGACY_CARD_STATUSES = {"VERIFIED_OBSERVATION"}
_USABLE_CARD_STATUSES = {"SOURCE_ALIGNED_COVERAGE_LIMITED", "VERIFIED_OBSERVATION"}
_SAFE_REF_PREFIX = "card-ariadne-ref-"


class AriadneMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: StrictStr = Field(..., min_length=1, max_length=4000)
    language: Literal["en", "zh-TW"] = "en"

    @field_validator("content")
    @classmethod
    def nonempty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message content must not be blank")
        return value.strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AriadneChatRepository:
    """Stores only user/assistant conversation messages in its own SQLite file."""

    def __init__(self, database: str | Path):
        self.database = Path(database).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database, timeout=5) as connection:
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ariadne_chat_messages (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL UNIQUE,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ariadne_chat_project_sequence "
                "ON ariadne_chat_messages(project_id, sequence)"
            )

    def append(self, project_id: str, role: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        message = dict(payload)
        message.setdefault("id", f"ariadne-message-{uuid.uuid4().hex}")
        message.setdefault("created_at", _utc_now())
        raw = json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with sqlite3.connect(self.database, timeout=5) as connection:
            connection.execute("PRAGMA busy_timeout = 5000")
            with connection:
                connection.execute(
                    "INSERT INTO ariadne_chat_messages(message_id, project_id, role, payload_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (message["id"], project_id, role, raw, message["created_at"]),
                )
        return message

    def list_messages(self, project_id: str, limit: int) -> list[dict[str, Any]]:
        with sqlite3.connect(self.database, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT payload_json FROM ariadne_chat_messages WHERE project_id = ? "
                "ORDER BY sequence DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in reversed(rows)]


def _default_chat_database(project_store: ProjectStateStore) -> Path:
    configured = os.environ.get("ARIADNE_CHAT_DATABASE", "").strip()
    if configured:
        return Path(configured).expanduser()
    authority_database = str(project_store.database)
    if authority_database != ":memory:":
        return Path(authority_database).expanduser().resolve().parent / "ariadne-chat.sqlite3"
    return Path.cwd() / ".urban_design_runtime" / "ariadne-chat.sqlite3"


def _project_ai_authorized() -> bool:
    return os.environ.get("PROJECT_AI_AUTHORIZED", "").strip() == "1"


def _ariadne_live_flag() -> bool:
    return os.environ.get("ARIADNE_LIVE", "").strip() == "1"


def _configured_ariadne_provider(
    store: ProjectStateStore,
    project_id: str,
    *,
    selected_profile_id: str | None = None,
    credential_resolver: Callable[[str], str | None] | None = None,
) -> Any:
    """Build the selected Ariadne profile, falling back to the configured default."""
    config = load_model_provider_config()
    if selected_profile_id is None:
        selected_profile_id = ModelProfileSelectionStore().load()
    selected_profile_id = selected_profile_id or default_ariadne_profile_id(config)
    profile = next((item for item in config.profiles if item.id == selected_profile_id), None)
    if profile is None:
        raise RuntimeError("selected Ariadne model profile is not configured")
    if not profile.enabled:
        raise RuntimeError(f"selected Ariadne model profile {profile.id!r} is disabled")
    if not profile.supports_json_schema:
        raise RuntimeError(f"selected Ariadne model profile {profile.id!r} does not support JSON Schema output")
    provider_kwargs: dict[str, Any] = {
        "cli_resolver": resolve_cli_executable,
        "use_ariadne_persona": True,
    }
    if profile.keychain_service and os.environ.get("PROJECT_AI_AUTHORIZED", "").strip() == "1":
        resolve_credential = credential_resolver or _read_keychain_secret
        provider_kwargs["api_key"] = resolve_credential(profile.keychain_service)
    provider = create_profile_provider(profile, **provider_kwargs)
    return ModelProviderRouter(
        providers={profile.id: provider},
        fallback_order=[profile.id],
        store=store,
        project_id=project_id,
        weekly_call_limit=config.weekly_call_limit,
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_problem_definitions(project_root: Path, study_area_id: str | None) -> list[dict[str, Any]]:
    candidates = [
        project_root / "artifacts" / "w6-problem-definition",
        Path(__file__).resolve().parents[2] / "artifacts/w6-problem-definition",
    ]
    directory = next((item for item in candidates if item.is_dir()), None)
    if directory is None:
        return []
    try:
        definitions = json.loads((directory / "problem-statements.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(definitions, Mapping) or definitions.get("study_area_id") != study_area_id:
        return []
    statements = definitions.get("statements")
    if not isinstance(statements, list):
        return []
    problems: list[dict[str, Any]] = []
    for statement in statements:
        if not isinstance(statement, Mapping):
            continue
        problem_id = statement.get("problem_id")
        title = statement.get("title_zh") or statement.get("title")
        if isinstance(problem_id, str) and problem_id.strip() and isinstance(title, str) and title.strip():
            title_en = statement.get("title_en") or statement.get("title")
            problems.append(
                {
                    "problem_id": problem_id.strip(),
                    "title": title.strip(),
                    "title_en": title_en.strip() if isinstance(title_en, str) and title_en.strip() else title.strip(),
                    "title_zh": title.strip(),
                    "status": str(statement.get("status") or "UNKNOWN"),
                    "limitations": [
                        str(item) for item in statement.get("uncertainties_zh", [])
                        if isinstance(item, str) and item.strip()
                    ],
                }
            )
    return problems


def _load_project_context(
    project_store: ProjectStateStore,
    source_catalog: Any | None,
    project_id: str,
) -> dict[str, Any]:
    if source_catalog is None:
        return {"project_id": project_id, "source_status": "BLOCKED_SOURCE_CATALOG_UNAVAILABLE"}
    if source_catalog.project_id != project_id:
        raise HTTPException(status_code=404, detail="project is not present in the verified source package")

    catalog = source_catalog
    try:
        from .workspace_sources import WorkspaceSourceCatalog

        catalog = WorkspaceSourceCatalog.load(project_store, source_catalog.package_root)
    except (OSError, ValueError, RuntimeError):
        return {"project_id": project_id, "source_status": "BLOCKED_SOURCE_CATALOG_UNAVAILABLE"}

    bundle, cards, evidence_status, _bundle_sha, evidence_gaps = get_persisted_site_analysis(
        project_store, project_id, catalog
    )
    if evidence_status != "VERIFIED_SOURCE_RESULT_ALIGNMENT":
        cards = []

    syntax = get_persisted_syntax_bundle(project_store, project_id, catalog, _project_root())
    if syntax.get("status") == "NOT_COMPUTED":
        try:
            syntax = load_verified_exploratory_syntax(_project_root(), catalog)
        except (OSError, ValueError, RuntimeError):
            pass
    syntax_layers = [
        dict(item)
        for item in [*syntax.get("layers", []), *syntax.get("layer_plan", [])]
        if isinstance(item, Mapping) and isinstance(item.get("layer_id"), str)
    ]

    workspace: dict[str, Any] | None = None
    try:
        service = WorkspaceService(project_store, source_catalog=catalog)
        record = service.get_workspace(service._workspace_id(project_id))
        if record is not None:
            workspace = record.model_dump(mode="json")
    except (ValueError, RuntimeError):
        workspace = None

    human_decisions = []
    try:
        human_decisions = [
            {
                "target_id": str(record.payload.get("target_id") or ""),
                "target_type": str(record.payload.get("target_type") or ""),
                "target_version": str(record.payload.get("target_version") or ""),
                "status": str(record.payload.get("status") or ""),
            }
            for record in project_store.list_current("HumanDecision", project_id=project_id)
        ]
    except (ValueError, RuntimeError):
        human_decisions = []

    workspace_decision = None
    try:
        from .decision_resolution import latest_accepted_workspace
        ws_rec, dec_rec = latest_accepted_workspace(project_store, project_id)
        workspace_decision = {**dict(dec_rec.payload), "accepted_workspace_revision": ws_rec.revision}
    except Exception:
        workspace_decision = None

    return {
        "project_id": project_id,
        "study_area_id": catalog.study_area_id,
        "source_status": "VERIFIED",
        "evidence_cards": cards,
        "evidence_cards_status": evidence_status,
        "evidence_gaps": evidence_gaps,
        "problems": _load_problem_definitions(_project_root(), catalog.study_area_id),
        "syntax_layers": syntax_layers,
        "syntax_status": syntax.get("status", "UNKNOWN"),
        "workspace": workspace,
        "human_decisions": human_decisions,
        "workspace_decision": workspace_decision,
    }


def _external_sources(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if context.get("evidence_cards_status") == "VERIFIED_SOURCE_RESULT_ALIGNMENT":
        for card in context.get("evidence_cards", []):
            if not isinstance(card, Mapping):
                continue
            card_id = card.get("card_id")
            metric_name = card.get("metric_name")
            if not isinstance(card_id, str) or not card_id.strip() or not isinstance(metric_name, str):
                continue
            sources.append({**dict(card), "evidence_id": card_id, "source_type": "evidence_card"})

    for problem in context.get("problems", []):
        if not isinstance(problem, Mapping):
            continue
        problem_id = problem.get("problem_id")
        title = problem.get("title")
        if isinstance(problem_id, str) and problem_id.strip() and isinstance(title, str) and title.strip():
            sources.append(
                {
                    "evidence_id": problem_id.strip(),
                    "source_type": "problem",
                    "metric_name": title.strip(),
                    "title_en": str(problem.get("title_en") or title).strip(),
                    "title_zh": str(problem.get("title_zh") or title).strip(),
                    "unit": "",
                    "limitations": list(problem.get("limitations", [])),
                    "status": str(problem.get("status") or "UNKNOWN"),
                }
            )

    for layer in context.get("syntax_layers", []):
        if not isinstance(layer, Mapping):
            continue
        layer_id = layer.get("layer_id")
        title = layer.get("title") or layer.get("metric_key")
        if isinstance(layer_id, str) and layer_id.strip() and isinstance(title, str) and title.strip():
            source = {
                    "evidence_id": layer_id.strip(),
                    "source_type": "syntax_layer",
                    "metric_name": title.strip(),
                    "unit": "",
                    "limitations": [str(layer.get("limitations") or layer.get("reason") or "")],
                    "status": str(layer.get("calculation_status") or "UNKNOWN"),
                }
            statistics = layer.get("statistics")
            mean = statistics.get("mean") if isinstance(statistics, Mapping) else None
            syntax_status = str(layer.get("calculation_status") or "UNKNOWN").upper()
            bundle_status = str(context.get("syntax_status") or "UNKNOWN").upper()
            if (
                syntax_status == "COMPUTED"
                and bundle_status not in {"STALE", "BLOCKED", "BLOCKED_HASH_MISMATCH"}
                and isinstance(mean, (int, float))
                and not isinstance(mean, bool)
                and isinstance(layer.get("unit"), str)
                and layer.get("unit")
            ):
                source["metric_name"] = f"{title.strip()} mean"
                source["value"] = mean
                source["unit"] = layer["unit"]
            sources.append(source)

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for source in sources:
        evidence_id = str(source["evidence_id"])
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        unique.append(source)
    return unique


def _aliases(sources: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
    safe_sources: list[dict[str, Any]] = []
    external_to_safe: dict[str, str] = {}
    safe_to_external: dict[str, str] = {}
    for index, source in enumerate(sources):
        alias = f"{_SAFE_REF_PREFIX}{index_to_letters(index)}"
        external_id = str(source["evidence_id"])
        external_to_safe[external_id] = alias
        safe_to_external[alias] = external_id
        normalized = dict(source)
        normalized["card_id"] = alias
        normalized["evidence_id"] = external_id
        safe_sources.append(normalized)
    return safe_sources, external_to_safe, safe_to_external


def index_to_letters(index: int) -> str:
    """Return a lowercase alphabetic token that adds no numeric claims to citations."""
    number = index
    result = ""
    while True:
        result = chr(ord("a") + number % 26) + result
        number = number // 26 - 1
        if number < 0:
            return result


def _replace_reference_aliases(text: str, replacements: Mapping[str, str]) -> str:
    result = text
    for old, new in replacements.items():
        result = result.replace(f"[{old}]", f"[{new}]")
    return result


class _AriadneCitationAdapter:
    """Translate public references to numeric-safe validator aliases for one call."""

    def __init__(self, provider: Any, external_to_safe: Mapping[str, str]):
        self.provider = provider
        self.external_to_safe = dict(external_to_safe)
        self.safe_to_external = {safe: external for external, safe in external_to_safe.items()}

    def generate_criticism(self, request: CriticRequest) -> dict[str, Any]:
        result = dict(self.provider.generate_criticism(request))
        if result.get("provider_status") != "LIVE_AI: ACTIVE":
            return result
        refs = result.get("evidence_refs")
        if isinstance(refs, list):
            result["evidence_refs"] = [self.external_to_safe.get(str(ref), str(ref)) for ref in refs]
        for field in ("observations", "design_hypotheses", "limitations", "next_questions"):
            values = result.get(field)
            if isinstance(values, list):
                result[field] = [
                    _replace_reference_aliases(str(value), self.external_to_safe)
                    for value in values
                ]
        return result

    def record_validation_result(self, payload: Mapping[str, Any], *, passed: bool) -> bool:
        record = getattr(self.provider, "record_validation_result", None)
        return bool(record(payload, passed=passed)) if callable(record) else True


class _AriadneCriticService(SiteCriticService):
    def validate_critic_response(self, payload, allowed_evidence_cards, expected_study_area_id=None):
        response = super().validate_critic_response(
            payload,
            allowed_evidence_cards=allowed_evidence_cards,
            expected_study_area_id=expected_study_area_id,
        )
        if response.provider_status == "LIVE_AI: ACTIVE" and not response.evidence_refs:
            raise CriticValidationError("Ariadne response must cite at least one current evidence ID")
        return response


def _public_response(response: Any, safe_to_external: Mapping[str, str]) -> dict[str, Any]:
    payload = response.model_dump(mode="json")
    payload["evidence_refs"] = [safe_to_external.get(ref, ref) for ref in payload.get("evidence_refs", [])]
    for field in ("observations", "design_hypotheses", "limitations", "next_questions"):
        payload[field] = [
            _replace_reference_aliases(value, safe_to_external)
            for value in payload.get(field, [])
        ]
    return payload


_OFFLINE_TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    "footprint": ("footprint", "footprints", "building area", "site area", "coverage", "area", "sqm", "m2", "m²", "m^2", "基底", "基地面積", "面積", "建蔽率", "建築面積"),
    "water": ("water", "waterbody", "water body", "waterway", "水域", "水體", "水面", "河道", "水"),
    "road": ("road", "roads", "street", "streets", "road network", "道路", "街道", "路網"),
    "use": ("land use", "land-use", "use", "uses", "program", "function", "用途", "使用", "機能"),
    "problem": ("problem", "problems", "issue", "issues", "challenge", "defined problem", "問題", "議題"),
    "syntax": ("syntax", "句法", "整合度", "選擇度"),
}
_OFFLINE_TOPIC_LABELS = {
    "en": ("footprints/area", "water", "roads/streets", "land use", "defined problems", "Syntax"),
    "zh-TW": ("建築基底／面積", "水域", "道路／街道", "用途", "已定義問題", "Syntax"),
}


def _language(value: str | None) -> Literal["en", "zh-TW"]:
    return "zh-TW" if isinstance(value, str) and value.casefold() == "zh-tw" else "en"


def _contains_topic_term(text: str, term: str) -> bool:
    if any("\u3400" <= character <= "\u9fff" for character in term):
        return term in text
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text, flags=re.IGNORECASE) is not None


def _source_text(source: Mapping[str, Any]) -> str:
    parts = [source.get(key) for key in ("metric_name", "title", "title_en", "title_zh", "metric_key", "unit", "source")]
    limitations = source.get("limitations")
    if isinstance(limitations, Sequence) and not isinstance(limitations, (str, bytes)):
        parts.extend(limitations)
    return " ".join(str(part) for part in parts if isinstance(part, (str, int, float))).casefold()


def _source_matches_topic(source: Mapping[str, Any], topic: str) -> bool:
    if topic == "problem" and source.get("source_type") == "problem":
        return True
    if topic == "syntax" and source.get("source_type") == "syntax_layer":
        return True
    text = _source_text(source)
    return any(_contains_topic_term(text, term) for term in _OFFLINE_TOPIC_TERMS[topic])


def _numeric_format(value: int | float, unit: str, language: Literal["en", "zh-TW"] = "en") -> tuple[str, str]:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value), unit
    if not number.is_finite():
        return str(value), unit

    normalized_unit = unit.strip().casefold().replace(" ", "")
    if normalized_unit in {"m2", "m²", "m^2", "sqm", "squaremeter", "squaremeters", "squaremetre", "squaremetres"}:
        return f"{number.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,.0f}", "m²"
    if normalized_unit in {"%", "percent", "percentage"}:
        return f"{number.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):,.1f}", "%"
    if normalized_unit in {"ratio", "proportion"}:
        return f"{number.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):,.1f}", unit
    if normalized_unit in {"feature", "features", "building", "buildings", "count", "counts"}:
        localized_unit = "筆" if language == "zh-TW" else unit
        return f"{number.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,.0f}", localized_unit
    return str(value), unit


def _render_offline_source(source: Mapping[str, Any], language: Literal["en", "zh-TW"]) -> tuple[str, str]:
    evidence_id = str(source["evidence_id"])
    source_type = source.get("source_type")
    status = str(source.get("status") or "UNKNOWN")
    metric_name = str(source.get("metric_name") or "Evidence Card")
    has_value = isinstance(source.get("value"), (int, float)) and not isinstance(source.get("value"), bool)
    value_is_usable = status in _USABLE_CARD_STATUSES or source_type == "syntax_layer" and status == "COMPUTED"
    if has_value and value_is_usable:
        value, unit = _numeric_format(source["value"], str(source.get("unit") or ""), language)
        measured_value = f"{value}{unit}" if unit == "%" else f"{value} {unit}".strip()
        if language == "zh-TW":
            return f"{metric_name}：{measured_value} [{evidence_id}]。", evidence_id
        return f"{metric_name}: {measured_value} [{evidence_id}].", evidence_id

    if source_type == "problem":
        localized_name = str(source.get("title_zh" if language == "zh-TW" else "title_en") or metric_name)
        if language == "zh-TW":
            return f"已定義問題：{localized_name}（狀態：{status}）[{evidence_id}]。", evidence_id
        return f"Defined problem: {localized_name} (status: {status}) [{evidence_id}].", evidence_id
    if source_type == "syntax_layer":
        if language == "zh-TW":
            return f"Syntax 圖層：{metric_name}（狀態：{status}）[{evidence_id}]。", evidence_id
        return f"Syntax layer: {metric_name} (status: {status}) [{evidence_id}].", evidence_id
    if language == "zh-TW":
        return f"{metric_name} 保留為狀態 {status}；請先確認其解讀 [{evidence_id}]。", evidence_id
    return f"{metric_name} is retained with status {status}; confirm its interpretation [{evidence_id}].", evidence_id


def _offline_content(
    sources: Sequence[Mapping[str, Any]],
    query: str,
    language: str = "en",
    note: str | None = None,
) -> tuple[str, list[str]]:
    locale = _language(language)
    query_topics = [topic for topic, terms in _OFFLINE_TOPIC_TERMS.items() if any(_contains_topic_term(query.casefold(), term) for term in terms)]
    specific_topics = [topic for topic in query_topics if topic != "problem"]
    matches: list[tuple[int, Mapping[str, Any]]] = []
    for source in sources:
        if (
            source.get("source_type") == "problem"
            and "problem" in query_topics
            and specific_topics
            and not any(_source_matches_topic(source, topic) for topic in specific_topics)
        ):
            continue
        matched_topics = sum(_source_matches_topic(source, topic) for topic in query_topics)
        if matched_topics:
            matches.append((matched_topics, source))
    matches.sort(key=lambda item: -item[0])
    selected = [source for _score, source in matches[:3]]

    if selected:
        lines = ["以下是與問題相關的目前證據：" if locale == "zh-TW" else "Relevant current evidence:"]
    else:
        selected = list(sources[:3])
        if locale == "zh-TW":
            lines = ["目前的證據卡或已定義問題中沒有找到明確相符項目。可查閱的記錄摘要："]
        else:
            lines = ["No clear match was found in the current Evidence Cards or defined problems. Available record summary:"]

    if note:
        lines.append(note)
    refs: list[str] = []
    for source in selected:
        line, evidence_id = _render_offline_source(source, locale)
        lines.append(line)
        refs.append(evidence_id)

    if not matches:
        if not selected:
            lines.append("目前沒有可引用的證據卡、問題定義或 Syntax 圖層。" if locale == "zh-TW" else "No current Evidence Card, problem definition, or Syntax layer is available.")
        topics = "、".join(_OFFLINE_TOPIC_LABELS[locale]) if locale == "zh-TW" else ", ".join(_OFFLINE_TOPIC_LABELS[locale])
        lines.append(
            f"你可以改問：{topics}。" if locale == "zh-TW"
            else f"You could ask about: {topics}."
        )
    lines.append("此離線摘要不會接受設計提案或作成設計決策。" if locale == "zh-TW" else "This offline summary does not accept a design proposal or make a design decision.")
    return "\n".join(lines), refs


def _offline_status_note(state: Mapping[str, Any], language: str) -> str | None:
    locale = _language(language)
    code = str(state.get("block_reason_code") or state.get("provider_status") or "")
    known = {
        "BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED": ("即時 AI 尚未啟用；此回答使用確定性的離線範本。", "Live AI is not enabled; this answer uses the deterministic offline template."),
        "BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED": ("此專案尚未授權即時 AI；未傳送供應商請求。", "Live AI is not authorized for this project; no provider request was sent."),
        "BLOCKED_BUDGET": ("共用每週 ModelRun 額度已用盡；未傳送供應商請求。", "The shared weekly ModelRun budget is exhausted; no provider request was sent."),
        "BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE": ("共用每週 ModelRun 計數無法使用；未傳送供應商請求。", "Shared weekly ModelRun accounting is unavailable; no provider request was sent."),
        "BLOCKED_ARIADNE_PROFILE_UNAVAILABLE": ("Ariadne persona 設定檔無法使用；未傳送供應商請求。", "The Ariadne persona profile is unavailable; no provider request was sent."),
    }
    if code in known:
        return known[code][0 if locale == "zh-TW" else 1]
    if code:
        return f"即時 AI 狀態為 {code}；此回答使用離線範本。" if locale == "zh-TW" else f"Live AI status is {code}; this answer uses the offline template."
    return None


def _offline_outcome_note(provider_status: str, language: str) -> str:
    locale = _language(language)
    if provider_status == "LIVE_AI: OUTCOME_UNKNOWN":
        return "即時請求結果未知，請先核對狀態；Ariadne 未重送請求。" if locale == "zh-TW" else "The live request outcome is unknown; reconcile status first. Ariadne did not resend it."
    if provider_status == "LIVE_AI: REQUEST_REJECTED":
        return "供應商拒絕此請求；Ariadne 未改用其他設定檔重試。" if locale == "zh-TW" else "The provider rejected the request; Ariadne did not retry with another profile."
    return f"即時回覆無法使用（{provider_status}）；未重送請求。" if locale == "zh-TW" else f"The live response is unavailable ({provider_status}); no retry was sent."


def _evidence_source_labels(sources: Sequence[Mapping[str, Any]], refs: Sequence[str]) -> list[dict[str, str]]:
    source_types = {str(item["evidence_id"]): str(item.get("source_type") or "evidence_card") for item in sources}
    return [
        {"evidence_id": evidence_id, "source_type": source_types.get(evidence_id, "evidence_card")}
        for evidence_id in refs
    ]


def _decisions_needed(context: Mapping[str, Any], language: str = "en") -> list[dict[str, Any]]:
    locale = _language(language)
    items: list[dict[str, Any]] = []
    legacy_statuses: dict[str, list[str]] = {}
    for card in context.get("evidence_cards", []):
        if isinstance(card, Mapping) and card.get("status") in _LEGACY_CARD_STATUSES:
            card_id = str(card.get("card_id") or "")
            if card_id:
                card_ids = legacy_statuses.setdefault(str(card.get("status")), [])
                if card_id not in card_ids:
                    card_ids.append(card_id)
    for status, card_ids in legacy_statuses.items():
        count = len(card_ids)
        title = (
            f"確認 {count} 張證據卡的舊版狀態標籤" if locale == "zh-TW"
            else f"Confirm legacy status labels for {count} evidence card{'s' if count != 1 else ''}"
        )
        reason = (
            f"這些證據卡保留舊版狀態標籤 {status}；請逐張確認標籤與來源後再使用。" if locale == "zh-TW"
            else f"These Evidence Cards retain the legacy status label {status}; review each label and source before relying on them."
        )
        items.append(
            {
                "id": f"legacy-status-{status.lower()}",
                "title": title,
                "source_id": card_ids[0],
                "source_ids": card_ids,
                "source_type": "evidence_card",
                "reason": reason,
            }
        )

    workspace = context.get("workspace")
    if isinstance(workspace, Mapping):
        workspace_id = str(workspace.get("workspace_id") or "")
        revision = str(workspace.get("revision") or "")
        decisions = context.get("human_decisions", [])
        workspace_decision = context.get("workspace_decision")
        accepted_revision = ""
        if isinstance(workspace_decision, Mapping) and str(workspace_decision.get("status") or "").upper() in {"CONFIRMED", "APPROVED", "ACCEPTED"}:
            accepted_revision = str(workspace_decision.get("accepted_workspace_revision") or "")
        # D1 is settled only when the *current* revision is the accepted one.
        d1_confirmed = (accepted_revision != "" and accepted_revision == revision) or any(
            isinstance(item, Mapping)
            and item.get("target_id") == workspace_id
            and item.get("target_version") == revision
            and str(item.get("status", "")).upper() in {"CONFIRMED", "APPROVED", "ACCEPTED"}
            for item in decisions
        )
        if workspace_id and not d1_confirmed and str(workspace.get("status", "")).upper() in {"DRAFT", "DRAFT_PENDING_HUMAN_DECISION"}:
            if accepted_revision:
                reason = (f"目前工作區版本 r{revision} 是草稿；平台依據已核准的 r{accepted_revision}。若 r{revision} 的修改要生效，需要重新確認。"
                          if locale == "zh-TW" else
                          f"Workspace revision r{revision} is a draft; the platform uses the accepted r{accepted_revision}. Re-confirm if r{revision}'s changes should take effect.")
            else:
                reason = "目前工作區版本仍是草稿。" if locale == "zh-TW" else "The current workspace revision is still a draft."
            items.append(
                {
                    "id": f"d1-{workspace_id}-{revision}",
                    "title": "D1：確認目前工作區版本" if locale == "zh-TW" else "D1: Confirm the current workspace revision",
                    "source_id": workspace_id,
                    "source_ids": [workspace_id],
                    "source_type": "workspace",
                    "reason": reason,
                }
            )

        brief = workspace.get("spatial_brief")
        if not d1_confirmed and not accepted_revision and isinstance(brief, Mapping) and str(brief.get("status", "")).upper() in {"DRAFT", "DRAFT_PENDING_HUMAN_DECISION"}:
            items.append(
                {
                    "id": f"d3-{workspace_id}-{revision}",
                    "title": "D3：確認設計需求" if locale == "zh-TW" else "D3: Confirm the design brief",
                    "source_id": workspace_id,
                    "source_ids": [workspace_id],
                    "source_type": "workspace",
                    "reason": "空間需求仍是草稿，等待設計者檢視。" if locale == "zh-TW" else "The spatial brief remains a draft pending designer review.",
                }
            )

    for problem in context.get("problems", []):
        if isinstance(problem, Mapping) and str(problem.get("status", "")).upper() in {"DRAFT", "NEEDS_REVIEW", "UNCONFIRMED"}:
            problem_id = str(problem.get("problem_id") or "")
            if problem_id:
                items.append(
                    {
                        "id": f"problem-review-{problem_id}",
                        "title": f"檢視問題定義：{problem.get('title_zh', problem.get('title', problem_id))}" if locale == "zh-TW" else f"Review problem definition: {problem.get('title_en', problem.get('title', problem_id))}",
                        "source_id": problem_id,
                        "source_ids": [problem_id],
                        "source_type": "problem",
                        "reason": f"問題定義的狀態為 {problem.get('status')}。" if locale == "zh-TW" else f"Problem definition status is {problem.get('status')}.",
                    }
                )
    return items


def create_ariadne_chat_router(
    project_store: ProjectStateStore,
    source_catalog: Any | None,
    *,
    chat_database: str | Path | None = None,
    context_loader: Callable[[str], Mapping[str, Any]] | None = None,
    provider_factory: Callable[[ProjectStateStore, str], Any] | None = None,
    live_enabled: bool | None = None,
) -> APIRouter:
    """Create the Ariadne API router with transcripts separate from project ModelRuns."""
    database = Path(chat_database).expanduser() if chat_database is not None else _default_chat_database(project_store)
    database = database.resolve()
    authority_database = Path(project_store.database).expanduser().resolve()
    if database == authority_database:
        raise ValueError("Ariadne chat database must be separate from the authoritative project database")
    repository = AriadneChatRepository(database)
    load_context = context_loader or (lambda project_id: _load_project_context(project_store, source_catalog, project_id))
    build_provider = provider_factory or _configured_ariadne_provider
    requested_live = _ariadne_live_flag() if live_enabled is None else bool(live_enabled)

    router = APIRouter(prefix="/api/v1/projects/{project_id}/ariadne", tags=["ariadne-chat"])

    def context_for(project_id: str) -> dict[str, Any]:
        raw = load_context(project_id)
        if not isinstance(raw, Mapping):
            return {"project_id": project_id, "source_status": "BLOCKED_CONTEXT_UNAVAILABLE"}
        if raw.get("project_id") not in (None, project_id):
            raise HTTPException(status_code=404, detail="project context does not match the requested project")
        return dict(raw)

    def provider_state(project_id: str, *, create_provider: bool) -> tuple[dict[str, Any], Any | None]:
        config = load_model_provider_config()
        used = 0
        try:
            used = ProjectStateModelRunAccounting(project_store, project_id).weekly_calls_used()
        except Exception:
            reason = "BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE"
            return {
                "mode": "OFFLINE",
                "provider_status": reason,
                "block_reason": "Live AI is blocked because shared weekly ModelRun accounting is unavailable.",
                "block_reason_code": reason,
                "live_available": False,
                "weekly_calls_used": None,
                "weekly_call_limit": config.weekly_call_limit,
                "request_dispatched": False,
            }, None

        try:
            if not requested_live:
                reason = "BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED"
                return {
                    "mode": "OFFLINE",
                    "provider_status": "BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED",
                    "block_reason": "Live AI is disabled. Restart the server with --ariadne-live to enable Ariadne.",
                    "block_reason_code": reason,
                    "live_available": False,
                    "weekly_calls_used": used,
                    "weekly_call_limit": config.weekly_call_limit,
                    "request_dispatched": False,
                }, None
            if used >= config.weekly_call_limit:
                reason = "BLOCKED_BUDGET"
                return {
                    "mode": "OFFLINE",
                    "provider_status": reason,
                    "block_reason": "The shared weekly ModelRun budget is exhausted; no provider request was sent.",
                    "block_reason_code": reason,
                    "live_available": False,
                    "weekly_calls_used": used,
                    "weekly_call_limit": config.weekly_call_limit,
                    "request_dispatched": False,
                }, None
            if not _project_ai_authorized():
                reason = "BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED"
                return {
                    "mode": "OFFLINE",
                    "provider_status": reason,
                    "block_reason": "Live AI also requires PROJECT_AI_AUTHORIZED=1; no provider request was sent.",
                    "block_reason_code": reason,
                    "live_available": False,
                    "weekly_calls_used": used,
                    "weekly_call_limit": config.weekly_call_limit,
                    "request_dispatched": False,
                }, None
            provider = build_provider(project_store, project_id) if create_provider else None
            if provider is None:
                return {
                    "mode": "LIVE",
                    "provider_status": "LIVE_AI: ARIADNE_LIVE_ENABLED",
                    "block_reason": None,
                    "block_reason_code": None,
                    "live_available": True,
                    "weekly_calls_used": used,
                    "weekly_call_limit": config.weekly_call_limit,
                    "request_dispatched": False,
                }, None
            live_available = bool(getattr(provider, "is_live_available", False))
            status = str(getattr(provider, "status", "LIVE_AI: PROFILE_STATUS_UNKNOWN"))
            return {
                "mode": "LIVE" if live_available else "OFFLINE",
                "provider_status": status,
                "block_reason": None if live_available else f"The Ariadne persona profile is unavailable ({status}).",
                "block_reason_code": None if live_available else status,
                "live_available": live_available,
                "weekly_calls_used": used,
                "weekly_call_limit": config.weekly_call_limit,
                "request_dispatched": False,
            }, provider
        except Exception:
            reason = "BLOCKED_ARIADNE_PROFILE_UNAVAILABLE"
            return {
                "mode": "OFFLINE",
                "provider_status": reason,
                "block_reason": "The Ariadne persona profile could not be initialized; no provider request was sent.",
                "block_reason_code": reason,
                "live_available": False,
                "weekly_calls_used": used,
                "weekly_call_limit": config.weekly_call_limit,
                "request_dispatched": False,
            }, None

    @router.get("/status")
    def get_status(project_id: str = FPath(..., min_length=1, max_length=128)) -> dict[str, Any]:
        state, _provider = provider_state(project_id, create_provider=True)
        return {"project_id": project_id, **state}

    @router.get("/decisions-needed")
    def get_decisions_needed(
        project_id: str = FPath(..., min_length=1, max_length=128),
        accept_language: str = Header(default="en", alias="Accept-Language"),
    ) -> dict[str, Any]:
        context = context_for(project_id)
        return {"project_id": project_id, "items": _decisions_needed(context, accept_language)}

    @router.get("/messages")
    def get_messages(
        project_id: str = FPath(..., min_length=1, max_length=128),
        limit: int = Query(100, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"project_id": project_id, "messages": repository.list_messages(project_id, limit)}

    @router.post("/messages")
    def post_message(
        request: AriadneMessageRequest,
        project_id: str = FPath(..., min_length=1, max_length=128),
    ) -> dict[str, Any]:
        context = context_for(project_id)
        sources = _external_sources(context)
        user_message = repository.append(
            project_id,
            "user",
            {
                "role": "user",
                "content": request.content,
                "evidence_refs": [],
                "provider_status": None,
            },
        )

        state, _ = provider_state(project_id, create_provider=False)
        live_gate_open = requested_live and _project_ai_authorized()
        live_provider: Any | None = None
        if live_gate_open and not sources:
            state.update(
                {
                    "mode": "OFFLINE",
                    "provider_status": "LIVE_AI: BLOCKED_EVIDENCE_UNAVAILABLE",
                    "block_reason": "Live AI was not dispatched because no current evidence source is available.",
                    "block_reason_code": "BLOCKED_EVIDENCE_UNAVAILABLE",
                    "live_available": False,
                }
            )
        if live_gate_open and sources and state.get("live_available"):
            try:
                live_provider = build_provider(project_store, project_id)
                if not bool(getattr(live_provider, "is_live_available", False)):
                    provider_status = str(getattr(live_provider, "status", "BLOCKED_ARIADNE_PROFILE_UNAVAILABLE"))
                    state.update(
                        {
                            "mode": "OFFLINE",
                            "provider_status": provider_status,
                            "block_reason": f"The Ariadne persona profile is unavailable ({provider_status}).",
                            "block_reason_code": provider_status,
                            "live_available": False,
                        }
                    )
                    live_provider = None
            except Exception:
                state.update(
                    {
                        "mode": "OFFLINE",
                        "provider_status": "BLOCKED_ARIADNE_PROFILE_UNAVAILABLE",
                        "block_reason": "The Ariadne persona profile could not be initialized; no provider request was sent.",
                        "block_reason_code": "BLOCKED_ARIADNE_PROFILE_UNAVAILABLE",
                        "live_available": False,
                    }
                )
                live_provider = None

        assistant_payload: dict[str, Any]
        if live_provider is None:
            note = _offline_status_note(state, request.language)
            content, refs = _offline_content(sources, request.content, request.language, note)
            assistant_payload = {
                "role": "assistant",
                "content": content,
                "evidence_refs": refs,
                "evidence_sources": _evidence_source_labels(sources, refs),
                "provider_status": "NON_AI: DETERMINISTIC_TEMPLATE",
                "provider_name": "deterministic-evidence-template",
            }
        else:
            safe_sources, external_to_safe, safe_to_external = _aliases(sources)
            citation_adapter = _AriadneCitationAdapter(live_provider, external_to_safe)
            service = _AriadneCriticService(provider=citation_adapter, use_ariadne_persona=True)
            workspace = context.get("workspace")
            workspace_id = workspace.get("workspace_id") if isinstance(workspace, Mapping) else None
            workspace_revision = workspace.get("revision") if isinstance(workspace, Mapping) else None
            study_area_id = str(context.get("study_area_id") or "study-area-unavailable")
            try:
                validated = service.generate_and_validate(
                    study_area_id=study_area_id,
                    evidence_bundle=safe_sources,
                    query=request.content,
                    workspace_id=workspace_id if isinstance(workspace_id, str) else None,
                    workspace_revision=workspace_revision if isinstance(workspace_revision, int) else None,
                )
                if validated.provider_status == "LIVE_AI: ACTIVE":
                    public = _public_response(validated, safe_to_external)
                    content_parts = [*public["observations"], *public["design_hypotheses"], *public["limitations"], *public["next_questions"]]
                    assistant_payload = {
                        "role": "assistant",
                        "content": "\n".join(content_parts),
                        "evidence_refs": public["evidence_refs"],
                        "evidence_sources": _evidence_source_labels(sources, public["evidence_refs"]),
                        "provider_status": public["provider_status"],
                        "provider_name": public.get("provider_name"),
                        "provider_model": public.get("provider_model"),
                        "provider_profile_id": public.get("provider_profile_id"),
                        "provider_request_id": public.get("provider_request_id"),
                    }
                else:
                    provider_status = validated.provider_status or "LIVE_AI: MODEL_FAILED"
                    note = _offline_outcome_note(provider_status, request.language)
                    content, refs = _offline_content(sources, request.content, request.language, note)
                    assistant_payload = {
                        "role": "assistant",
                        "content": content,
                        "evidence_refs": refs,
                        "evidence_sources": _evidence_source_labels(sources, refs),
                        "provider_status": provider_status,
                        "provider_name": validated.provider_name,
                        "provider_model": validated.provider_model,
                        "provider_profile_id": validated.provider_profile_id,
                        "provider_request_id": validated.provider_request_id,
                    }
            except CriticValidationError as exc:
                raise HTTPException(status_code=502, detail=f"Ariadne rejected an unsupported response: {exc}") from exc

        assistant_message = repository.append(project_id, "assistant", assistant_payload)
        return {
            "project_id": project_id,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "status": state,
        }

    return router
