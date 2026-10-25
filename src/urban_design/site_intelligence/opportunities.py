"""Bounded, evidence-cited opportunity suggestions over typed analysis summaries."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from enum import Enum
from typing import Any, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .contracts import (
    AnalysisStatus,
    CategoryCount,
    DesignIntent,
    FrozenRef,
    Observation,
    Opportunity,
    SuggestedAction,
    SiteAnalysisBundle,
    StatementTemplate,
)
from .relationships import RelationshipResolver, RelationshipValidationError, has_unbound_numeric_text, render_statement, validate_analysis_bundle, validate_opportunity


def reference_token(ref: FrozenRef) -> str:
    """Stable citation token containing the full artifact identity and hash."""
    return f"{ref.id}@{ref.revision}#{ref.sha256}"


class EvidenceRefToken(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    token: str = Field(min_length=1)
    ref: FrozenRef

    @model_validator(mode="after")
    def token_matches_reference(self) -> "EvidenceRefToken":
        if self.token != reference_token(self.ref):
            raise ValueError("evidence token must contain the exact reference id, revision, and hash")
        return self


class SuggestionObservation(BaseModel):
    """Small, typed measurement summary passed to a suggestion provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_key: str = Field(min_length=1)
    status: AnalysisStatus
    value: FiniteFloat | None = None
    category_counts: tuple[CategoryCount, ...] = ()
    unit: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    scope_ref: EvidenceRefToken
    input_refs: tuple[EvidenceRefToken, ...] = ()
    limitation_codes: tuple[str, ...] = ()
    limitation_details: tuple[str, ...] = ()


class SuggestionRequest(BaseModel):
    """Provider boundary: evidence summaries, exact citations, and finite actions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_ref: EvidenceRefToken
    workspace_ref: EvidenceRefToken
    study_area_ref: EvidenceRefToken
    observations: tuple[SuggestionObservation, ...]
    allowed_evidence_refs: tuple[EvidenceRefToken, ...]
    allowed_actions: tuple[SuggestedAction, ...]
    statement_template_schema: dict[str, Any] = Field(default_factory=StatementTemplate.model_json_schema)


class SuggestionStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class OpportunitySuggestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: SuggestionStatus
    analysis_ref: FrozenRef
    opportunities: tuple[Opportunity, ...] = ()
    repair_attempts: int = Field(default=0, ge=0, le=1)
    raw_structured_output: Any | None = None
    rejection_codes: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    manual_entry_available: bool = True


class OpportunityProvider(Protocol):
    available: bool
    is_live: bool

    def propose(self, request: SuggestionRequest) -> Any: ...

    def repair(
        self,
        request: SuggestionRequest,
        invalid_output: Any,
        rejection_codes: tuple[str, ...],
    ) -> Any: ...


_ALLOWED_ACTIONS = tuple(SuggestedAction)
_PRIVATE_FIELDS = {
    "analysis",
    "chainofthought",
    "cot",
    "credential",
    "credentials",
    "reason",
    "privatereasoning",
    "reasoning",
    "reasoningcontent",
    "internalreasoning",
    "think",
    "thoughts",
    "thought",
    "thinking",
    "reflection",
    "deliberation",
    "scratchpad",
    "rationale",
    "private",
    "authorization",
    "apikey",
    "accesskey",
    "accesstoken",
    "bearer",
    "cookie",
    "cookies",
    "jwt",
    "sessionid",
    "token",
    "secret",
    "password",
    "passwd",
    "pwd",
    "privatekey",
    "clientsecret",
    "apitoken",
    "auth",
    "openaikey",
    "reasoningsummary",
    "internalnotes",
    "思考",
}
_NUMERIC_LITERAL = re.compile(r"[0-9０-９零〇一二三四五六七八九十百千万萬]")
_THINK_BLOCK = re.compile(r"<(?:think|thinking|reasoning|scratchpad)\b[^>]*>.*?</(?:think|thinking|reasoning|scratchpad)\s*>", re.IGNORECASE | re.DOTALL)
_UNCLOSED_THINK_BLOCK = re.compile(r"<(?:think|thinking|reasoning|scratchpad)\b[^>]*>.*$", re.IGNORECASE | re.DOTALL)
_THINK_TAG = re.compile(r"</?(?:think|thinking|reasoning|scratchpad)\b[^>]*>", re.IGNORECASE)
_CREDENTIAL_TEXT = re.compile(
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+|(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]+"
    r"|ghp_[A-Za-z0-9]+|AKIA[A-Z0-9]{16}|xoxb-[A-Za-z0-9-]+|AIza[A-Za-z0-9_-]+"
    r"|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|-----BEGIN [A-Z ]+-----(?:.*?-----END [A-Z ]+-----|.*$)"
    r"|Authorization\s*:\s*Basic\s+[A-Za-z0-9+/=]+",
    re.DOTALL,
)
# Only documented suggestion-envelope fields may enter retained audit output.
_RAW_OUTPUT_FIELDS = frozenset({
    "provider_status", "design_hypotheses", "evidence_refs", "next_questions",
    "opportunities", "statement", "suggested_actions", "counterexamples",
    "verification_metric_keys", "uncertainties", "initial", "repaired",
    "repair_exception_type", "statement_template", "template_id", "metric_ref", "direction", "verification",
})
_MAX_SUGGESTIONS = 5
_MAX_NARRATIVE_CHARS = 1000
_MAX_TEXT_ITEMS = 10


def _is_private_output_key(name: str) -> bool:
    normalized = re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", name).casefold())
    return normalized in _PRIVATE_FIELDS


def _sanitize_text_output(value: str) -> str:
    sanitized = _THINK_BLOCK.sub("", value)
    sanitized = _UNCLOSED_THINK_BLOCK.sub("", sanitized)
    sanitized = _THINK_TAG.sub("", sanitized)
    return _CREDENTIAL_TEXT.sub("[FILTERED_CREDENTIAL]", sanitized)


def _validate_generated_text(value: str, field_name: str) -> None:
    if len(value) > _MAX_NARRATIVE_CHARS:
        raise RelationshipValidationError(f"invalid opportunity schema: {field_name} exceeds the text length limit")
    if _THINK_TAG.search(value) or _CREDENTIAL_TEXT.search(value):
        raise RelationshipValidationError(f"invalid opportunity schema: {field_name} contains filtered private or credential text")


def _sanitize_raw(value: Any, *, depth: int = 0) -> Any:
    """Keep structured output for audit while dropping private or secret fields."""
    if depth > 8:
        return "[depth-limited]"
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name not in _RAW_OUTPUT_FIELDS or _is_private_output_key(name):
                continue
            output[name] = _sanitize_raw(item, depth=depth + 1)
        return output
    if isinstance(value, (list, tuple)):
        return [_sanitize_raw(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return _sanitize_text_output(value)[:12000]
    if isinstance(value, float) and not math.isfinite(value):
        return "[non-finite-number]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"[unsupported:{type(value).__name__}]"


def _all_refs(bundle: SiteAnalysisBundle) -> tuple[EvidenceRefToken, ...]:
    refs: dict[FrozenRef, EvidenceRefToken] = {}
    for observation in bundle.observations:
        for ref in (observation.scope_ref, *observation.input_refs):
            refs.setdefault(ref, EvidenceRefToken(token=reference_token(ref), ref=ref))
    return tuple(refs.values())


def build_suggestion_request(bundle: SiteAnalysisBundle) -> SuggestionRequest:
    refs = {item.ref: item for item in _all_refs(bundle)}
    observations = tuple(
        SuggestionObservation(
            metric_key=item.metric_key,
            status=item.status,
            value=item.value,
            category_counts=item.category_counts,
            unit=item.unit,
            method_version=item.method_version,
            scope_ref=refs.setdefault(
                item.scope_ref,
                EvidenceRefToken(token=reference_token(item.scope_ref), ref=item.scope_ref),
            ),
            input_refs=tuple(refs[ref] for ref in item.input_refs),
            limitation_codes=item.limitation_codes,
            limitation_details=item.limitation_details,
        )
        for item in bundle.observations
        if item.status in {"AVAILABLE", "PARTIAL"}
    )
    allowed_refs: dict[FrozenRef, EvidenceRefToken] = {}
    for observation in bundle.observations:
        if observation.status not in {"AVAILABLE", "PARTIAL"}:
            continue
        for ref in observation.input_refs:
            if ref == observation.scope_ref:
                continue
            allowed_refs.setdefault(ref, refs[ref])
    return SuggestionRequest(
        analysis_ref=EvidenceRefToken(token=reference_token(bundle.bundle_ref), ref=bundle.bundle_ref),
        workspace_ref=EvidenceRefToken(token=reference_token(bundle.workspace_ref), ref=bundle.workspace_ref),
        study_area_ref=EvidenceRefToken(token=reference_token(bundle.study_area_ref), ref=bundle.study_area_ref),
        observations=observations,
        allowed_evidence_refs=tuple(allowed_refs.values()),
        allowed_actions=_ALLOWED_ACTIONS,
    )


def designer_authored_intent(
    *,
    intent_id: str,
    text: str,
    scope_ref: FrozenRef,
    kind: str = "PREFERENCE",
    version: int = 1,
) -> DesignIntent:
    """Create a manual draft intent independently of provider availability."""
    return DesignIntent(
        id=intent_id,
        text=text,
        scope_ref=scope_ref,
        kind=kind,
        origin="DESIGNER_AUTHORED",
        version=version,
    )


def _rejection_code(error: Exception) -> str:
    message = str(error).lower()
    if "numeric" in message or "measured number" in message:
        return "MODEL_NUMERIC_CLAIM_REJECTED"
    if "schema" in message or "invalid opportunity" in message:
        return "MODEL_OUTPUT_SCHEMA_INVALID"
    if any(part in message for part in ("reference", "unresolved", "revision", "hash", "evidence")):
        return "MODEL_EVIDENCE_REFERENCE_INVALID"
    if any(part in message for part in ("scope", "unit", "method", "metric", "scenario", "baseline")):
        return "MODEL_CLAIM_RELATIONSHIP_INVALID"
    return "MODEL_OUTPUT_REJECTED_BY_VALIDATOR"


def _parse_ref_token(token: Any, allowed: Mapping[str, FrozenRef]) -> FrozenRef:
    if not isinstance(token, str) or token not in allowed:
        raise RelationshipValidationError("evidence reference is not an exact allowed id/revision/hash token")
    return allowed[token]


def _drafts_from_raw(raw: Any, request: SuggestionRequest) -> list[dict[str, Any]]:
    if not isinstance(raw, Mapping):
        raise RelationshipValidationError("invalid opportunity schema: output must be an object")
    allowed = {item.token: item.ref for item in request.allowed_evidence_refs}
    if "design_hypotheses" in raw:
        raise RelationshipValidationError(
            "invalid opportunity schema: free-text hypotheses require fixed statement_template selections"
        )

    raw_drafts = raw.get("opportunities")
    if not isinstance(raw_drafts, (list, tuple)) or not raw_drafts:
        raise RelationshipValidationError("invalid opportunity schema: opportunities must be non-empty")
    if len(raw_drafts) > _MAX_SUGGESTIONS:
        raise RelationshipValidationError("invalid opportunity schema: at most five opportunities are allowed")
    drafts = []
    allowed_fields = {
        "statement_template",
        "statement",
        "evidence_refs",
        "suggested_actions",
        "counterexamples",
        "verification_metric_keys",
        "uncertainties",
    }
    for item in raw_drafts:
        if not isinstance(item, Mapping) or set(item) - allowed_fields:
            raise RelationshipValidationError("invalid opportunity schema: unsupported fields in draft")
        statement = item.get("statement")
        refs = item.get("evidence_refs")
        actions = item.get("suggested_actions", [SuggestedAction.TEST_HYPOTHESIS.value])
        try:
            template = StatementTemplate.model_validate(item.get("statement_template"))
        except Exception as exc:
            raise RelationshipValidationError("invalid opportunity schema: fixed statement_template is required") from exc
        if statement is not None:
            if not isinstance(statement, str) or not statement.strip():
                raise RelationshipValidationError("invalid opportunity schema: statement must be text")
            _validate_generated_text(statement.strip(), "statement")
        if not isinstance(refs, (list, tuple)) or not refs:
            raise RelationshipValidationError("invalid opportunity schema: evidence_refs are required")
        if not isinstance(actions, (list, tuple)) or not actions:
            raise RelationshipValidationError("invalid opportunity schema: suggested_actions are required")
        parsed_actions = tuple(SuggestedAction(value) for value in actions)
        if not set(parsed_actions).issubset(set(request.allowed_actions)):
            raise RelationshipValidationError("invalid opportunity schema: action is not in the allowlist")
        optional_text_fields: dict[str, tuple[str, ...]] = {}
        for field_name in ("counterexamples", "verification_metric_keys", "uncertainties"):
            value = item.get(field_name, ())
            if not isinstance(value, (list, tuple)) or any(not isinstance(entry, str) for entry in value):
                raise RelationshipValidationError(f"invalid opportunity schema: {field_name} must be a string list")
            if len(value) > _MAX_TEXT_ITEMS:
                raise RelationshipValidationError(f"invalid opportunity schema: {field_name} has too many entries")
            optional_text_fields[field_name] = tuple(value)
        for field_name in ("counterexamples", "uncertainties"):
            for entry in optional_text_fields[field_name]:
                _validate_generated_text(entry.strip(), field_name)
        drafts.append({
            "statement": statement.strip() if statement is not None else None,
            "statement_template": template,
            "evidence_refs": tuple(dict.fromkeys(_parse_ref_token(token, allowed) for token in refs)),
            "suggested_actions": parsed_actions,
            **optional_text_fields,
        })
    return drafts


def _build_opportunities(
    raw: Any,
    request: SuggestionRequest,
    bundle: SiteAnalysisBundle,
    resolver: RelationshipResolver,
    origin: str,
) -> tuple[Opportunity, ...]:
    drafts = _drafts_from_raw(raw, request)
    approved: list[Opportunity] = []
    for index, draft in enumerate(drafts, start=1):
        statement = render_statement(draft["statement_template"], bundle, resolver)
        template_observations = [item for item in bundle.observations
                                 if item.metric_key == draft["statement_template"].metric_ref
                                 and item.status in {"AVAILABLE", "PARTIAL"}
                                 and (set(item.input_refs) - {item.scope_ref}).issubset(set(draft["evidence_refs"]))]
        if not template_observations:
            raise RelationshipValidationError("statement template metric requires its exact observation evidence references")
        if draft["statement"] is not None and draft["statement"] != statement:
            raise RelationshipValidationError("invalid opportunity schema: statement must equal the server-rendered template")
        if has_unbound_numeric_text(" ".join((statement, *draft["counterexamples"], *draft["uncertainties"])), bundle, resolver):
            raise RelationshipValidationError("model cannot author measured numbers; bind a server observation")
        identity = hashlib.sha256(
            f"{reference_token(bundle.bundle_ref)}\0{index}\0{statement}".encode("utf-8")
        ).hexdigest()[:20]
        opportunity = Opportunity(
            id=f"ai-opportunity-{identity}",
            origin=origin,
            statement=statement,
            statement_template=draft["statement_template"],
            kind="CONDITIONAL_HYPOTHESIS",
            evidence_refs=draft["evidence_refs"],
            scope_ref=bundle.study_area_ref,
            suggested_actions=draft["suggested_actions"],
            counterexamples=draft["counterexamples"],
            verification_metric_keys=draft["verification_metric_keys"],
            uncertainties=draft["uncertainties"],
        )
        approved.append(validate_opportunity(opportunity, bundle, resolver))
    return tuple(approved)


def _is_outcome_unknown(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    return raw.get("provider_status") == "LIVE_AI: OUTCOME_UNKNOWN"


def _is_provider_unavailable(raw: Any, *, allow_statusless_test_fake: bool = False) -> bool:
    """Fail closed: production responses must explicitly report a usable status."""
    if not isinstance(raw, Mapping):
        return not allow_statusless_test_fake  # only explicit offline fakes reach schema repair
    if "provider_status" not in raw:
        return not allow_statusless_test_fake
    status = raw["provider_status"]
    return not isinstance(status, str) or status not in {
        "LIVE_AI: ACTIVE", "NON_AI: DETERMINISTIC_TEMPLATE",
    }


def _result(
    status: SuggestionStatus,
    bundle: SiteAnalysisBundle,
    *,
    opportunities: tuple[Opportunity, ...] = (),
    repair_attempts: int = 0,
    raw: Any = None,
    rejection_codes: tuple[str, ...] = (),
    reason_codes: tuple[str, ...] = (),
) -> OpportunitySuggestionResult:
    return OpportunitySuggestionResult(
        status=status,
        analysis_ref=bundle.bundle_ref,
        opportunities=opportunities,
        repair_attempts=repair_attempts,
        raw_structured_output=_sanitize_raw(raw) if raw is not None else None,
        rejection_codes=tuple(dict.fromkeys(rejection_codes)),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        manual_entry_available=True,
    )


def suggest_opportunities(
    bundle: SiteAnalysisBundle,
    resolver: RelationshipResolver,
    *,
    provider: OpportunityProvider | None,
    live_authorized: bool = False,
    budget_authorized: bool = False,
    max_repair: int = 1,
) -> OpportunitySuggestionResult:
    """Request and validate bounded suggestions; no provider is created here."""
    if type(max_repair) is not int or max_repair not in {0, 1}:
        raise ValueError("max_repair is an engineering bound and cannot exceed one")
    try:
        validate_analysis_bundle(bundle, resolver)
    except RelationshipValidationError:
        return _result(SuggestionStatus.UNAVAILABLE, bundle, reason_codes=("ANALYSIS_BUNDLE_INVALID",))
    request = build_suggestion_request(bundle)
    if provider is None or not bool(getattr(provider, "available", True)):
        return _result(SuggestionStatus.UNAVAILABLE, bundle, reason_codes=("SUGGESTION_PROVIDER_UNAVAILABLE",))
    if not request.observations or not request.allowed_evidence_refs:
        return _result(SuggestionStatus.UNAVAILABLE, bundle, reason_codes=("NO_CITABLE_ANALYSIS_EVIDENCE",))
    if getattr(provider, "is_live", None) is not False and not (live_authorized and budget_authorized):
        return _result(SuggestionStatus.UNAVAILABLE, bundle, reason_codes=("LIVE_PROVIDER_AUTHORIZATION_REQUIRED",))

    try:
        raw = provider.propose(request)
    except Exception as exc:
        # Once a provider call may have been dispatched, do not silently retry.
        code = "PROVIDER_OUTCOME_UNKNOWN" if not isinstance(exc, SuggestionNotDispatched) else "PROVIDER_REQUEST_NOT_STARTED"
        state = SuggestionStatus.OUTCOME_UNKNOWN if code == "PROVIDER_OUTCOME_UNKNOWN" else SuggestionStatus.UNAVAILABLE
        return _result(state, bundle, reason_codes=(code, type(exc).__name__))
    if _is_outcome_unknown(raw):
        return _result(SuggestionStatus.OUTCOME_UNKNOWN, bundle, raw=raw, reason_codes=("PROVIDER_OUTCOME_UNKNOWN",))
    # Explicit non-live providers are the only supported statusless test fake route.
    allow_statusless_test_fake = getattr(provider, "is_live", None) is False
    if _is_provider_unavailable(raw, allow_statusless_test_fake=allow_statusless_test_fake):
        return _result(SuggestionStatus.UNAVAILABLE, bundle, raw=raw, reason_codes=("PROVIDER_REPORTED_UNAVAILABLE",))

    reported_origin = getattr(provider, "suggestion_origin", "AI_SUGGESTED")
    origin = (
        reported_origin
        if isinstance(reported_origin, str) and reported_origin in {"AI_SUGGESTED", "RULE_SUGGESTED"}
        else "AI_SUGGESTED"
    )
    try:
        accepted = _build_opportunities(raw, request, bundle, resolver, origin)
        return _result(SuggestionStatus.AVAILABLE, bundle, opportunities=accepted, raw=raw)
    except Exception as first_error:
        rejection_codes = [_rejection_code(first_error)]

    repairer = getattr(provider, "repair", None)
    if max_repair == 0 or not callable(repairer):
        return _result(
            SuggestionStatus.INVALID_MODEL_OUTPUT,
            bundle,
            raw=raw,
            rejection_codes=tuple(rejection_codes),
        )
    try:
        repaired_raw = repairer(request, _sanitize_raw(raw), tuple(rejection_codes))
    except Exception as exc:
        return _result(
            SuggestionStatus.OUTCOME_UNKNOWN,
            bundle,
            repair_attempts=1,
            raw={"initial": raw, "repair_exception_type": type(exc).__name__},
            rejection_codes=tuple(rejection_codes),
            reason_codes=("REPAIR_OUTCOME_UNKNOWN", type(exc).__name__),
        )
    if _is_outcome_unknown(repaired_raw):
        return _result(
            SuggestionStatus.OUTCOME_UNKNOWN,
            bundle,
            repair_attempts=1,
            raw={"initial": raw, "repaired": repaired_raw},
            rejection_codes=tuple(rejection_codes),
            reason_codes=("REPAIR_OUTCOME_UNKNOWN",),
        )
    if _is_provider_unavailable(repaired_raw, allow_statusless_test_fake=allow_statusless_test_fake):
        return _result(
            SuggestionStatus.UNAVAILABLE,
            bundle,
            repair_attempts=1,
            raw={"initial": raw, "repaired": repaired_raw},
            rejection_codes=tuple(rejection_codes),
            reason_codes=("REPAIR_PROVIDER_UNAVAILABLE",),
        )
    try:
        accepted = _build_opportunities(repaired_raw, request, bundle, resolver, origin)
        return _result(
            SuggestionStatus.AVAILABLE,
            bundle,
            opportunities=accepted,
            repair_attempts=1,
            raw={"initial": raw, "repaired": repaired_raw},
            rejection_codes=tuple(rejection_codes),
        )
    except Exception as second_error:
        rejection_codes.append(_rejection_code(second_error))
        return _result(
            SuggestionStatus.INVALID_MODEL_OUTPUT,
            bundle,
            repair_attempts=1,
            raw={"initial": raw, "repaired": repaired_raw},
            rejection_codes=tuple(rejection_codes),
        )


class SuggestionNotDispatched(ConnectionError):
    """Provider transport proves that request bytes were never dispatched."""


class CriticSuggestionAdapter:
    """Narrow adapter over the existing CriticRequest/BaseCriticProvider API."""

    def __init__(self, provider: Any):
        from urban_design.model_provider import DeterministicFixtureProvider

        self._deterministic_fixture = type(provider) is DeterministicFixtureProvider
        self.provider = provider
        self.is_live = bool(getattr(provider, "is_live_available", False))
        status = str(getattr(provider, "status", "")).upper()
        self.available = (
            self._deterministic_fixture
            or (self.is_live and not status.startswith("BLOCKED"))
        )
        self.suggestion_origin = "RULE_SUGGESTED" if self._deterministic_fixture else "AI_SUGGESTED"

    @staticmethod
    def _critic_request(request: SuggestionRequest, repair_codes: tuple[str, ...] = (), *, bound_fixture: bool = False) -> Any:
        from urban_design.model_provider import CriticRequest

        cards: list[dict[str, Any]] = []
        for observation in request.observations:
            for reference in observation.input_refs:
                if reference.ref == observation.scope_ref.ref:
                    continue
                cards.append({
                    "card_id": reference.token,
                    "metric_name": observation.metric_key,
                    "value": observation.value,
                    "unit": observation.unit,
                    "status": observation.status,
                    "method_version": observation.method_version,
                    "scope_ref": observation.scope_ref.token,
                    "input_refs": [item.token for item in observation.input_refs
                                   if item.ref != observation.scope_ref.ref],
                    "limitations": list(observation.limitation_codes),
                    "limitation_details": list(observation.limitation_details),
                })
        if bound_fixture:
            # This known local fixture emits one hypothesis per card. Bound its
            # request, preserving the hard rejection cap for arbitrary providers.
            cards = cards[:_MAX_SUGGESTIONS]
        actions = ", ".join(item.value for item in request.allowed_actions)
        if repair_codes:
            query = (
                "Return corrected structured design hypotheses only. Do not add fields or measurements. "
                f"Validation issue codes: {', '.join(repair_codes)}. Allowed actions: {actions}."
            )
        else:
            query = (
                "Suggest conditional design hypotheses only. Do not state measured values or assert access, "
                f"buildability, traffic, or dead ends. Allowed actions: {actions}."
            )
        query += (
            " Return opportunities with statement_template selections only; no free-text statement. "
            "Each template selects template_id=METRIC_TENDENCY, metric_ref=an exact supplied metric_name, "
            "direction=HIGHER|LOWER|UNRESOLVED, verification=DETERMINISTIC_ANALYSIS|DESIGNER_REVIEW. "
            "Cite exact card IDs in evidence_refs. Template schema: "
            + str(request.statement_template_schema)
        )
        return CriticRequest(
            study_area_id=request.study_area_ref.ref.id,
            workspace_id=request.workspace_ref.ref.id,
            workspace_revision=request.workspace_ref.ref.revision,
            evidence_bundle=cards,
            query=query,
        )

    def _generate(self, request: SuggestionRequest, repair_codes: tuple[str, ...] = ()) -> Any:
        critic_request = self._critic_request(request, repair_codes, bound_fixture=self._deterministic_fixture)
        raw = self.provider.generate_criticism(critic_request)
        if not self._deterministic_fixture:
            return raw
        # Only the exact local fixture gets a deterministic projection. Arbitrary
        # model prose cannot be converted into accepted template selections.
        return {
            "provider_status": raw.get("provider_status"),
            "opportunities": [
                {
                    "statement_template": {
                        "template_id": "METRIC_TENDENCY", "metric_ref": card["metric_name"],
                        "direction": "UNRESOLVED", "verification": "DETERMINISTIC_ANALYSIS",
                    },
                    "evidence_refs": card["input_refs"],
                    "suggested_actions": ["TEST_HYPOTHESIS"],
                }
                for card in critic_request.evidence_bundle
            ],
        }

    def propose(self, request: SuggestionRequest) -> Any:
        return self._generate(request)

    def repair(self, request: SuggestionRequest, invalid_output: Any, rejection_codes: tuple[str, ...]) -> Any:
        # invalid_output is retained by the caller for audit; it is deliberately
        # not echoed into a second provider prompt.
        return self._generate(request, rejection_codes)
