"""Evidence-bound AI criticism and safety validation service (CP4-7).

Enforces:
- Model output cannot reference unverified or fake evidence card IDs.
- Observations must cite valid Evidence Cards.
- Design hypotheses are explicitly labelled as hypotheses, not planning facts.
- Rejection of prompt injections, unauthorized approvals, and overall ranking claims.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .model_provider import CriticRequest, get_configured_provider


class CriticValidationError(Exception):
    """Raised when model response violates evidence or safety boundaries."""


INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous\s+)?instructions", re.IGNORECASE),
    re.compile(r"system\s+override", re.IGNORECASE),
    re.compile(r"elevate\s+privilege", re.IGNORECASE),
    re.compile(r"approved\s*=\s*true", re.IGNORECASE),
    re.compile(r"status\s*=\s*[\"']?approved[\"']?", re.IGNORECASE),
    re.compile(r"drop\s+table", re.IGNORECASE),
]


class SiteCriticResponse(BaseModel):
    """Structured, evidence-grounded AI critic evaluation."""

    model_config = ConfigDict(extra="ignore")

    critic_id: str = Field(..., min_length=1)
    study_area_id: str = Field(..., min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    design_hypotheses: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_questions: list[str] = Field(default_factory=list)
    provider_status: str | None = None
    provider_name: str | None = None
    provider_profile_id: str | None = None
    provider_request_id: str | None = None
    provider_model: str | None = None
    provider_metadata: dict[str, Any] | None = None


_NUMBER_WITH_UNIT = re.compile(
    r"(?<![A-Za-z0-9_])(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<unit>m²|m2|meters?|metres?|features?|%|percent|km)?",
    re.IGNORECASE,
)
_CARD_ID_PATTERN = re.compile(r"\bcard-[A-Za-z0-9_-]+\b")
_UNVERIFIED_CONCEPTS = [
    re.compile(r"\b(?:pedestrian|vehicle|vehicular|traffic|walking)\s+(?:flow|volume|demand|count|accessibility|movement|time)\b", re.IGNORECASE),
    re.compile(r"\b(?:pedestrian|vehicle|vehicular)\s+traffic\b", re.IGNORECASE),
    re.compile(r"\b(?:traffic|pedestrian)\s+prediction\b", re.IGNORECASE),
    re.compile(r"\bwalkability\b", re.IGNORECASE),
    re.compile(r"\b(?:zoning|land[- ]use|planning)\s+(?:compliance|compliant|approval|approved)\b", re.IGNORECASE),
    re.compile(r"\b(?:legally\s+)?buildab(?:le|ility)\b", re.IGNORECASE),
    re.compile(r"\b(?:ownership|owned\s+by|public\s+right[- ]of[- ]way)\b", re.IGNORECASE),
]
_NEGATED_LIMITATION = re.compile(
    r"\b(?:not|no|unknown|unavailable|unverified|without|cannot|does\s+not|doesn't|not\s+established|not\s+proven)\b",
    re.IGNORECASE,
)


def _normalized_number(raw: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation as exc:
        raise CriticValidationError("critic returned an invalid numeric claim") from exc


def _normalized_unit(raw: str | None) -> str | None:
    if raw is None:
        return None
    token = re.sub(r"\s+", "", raw).lower()
    if token in {"%", "percent"}:
        return "%"
    if token in {"m²", "m2"}:
        return "m²"
    if token in {"m", "meter", "meters", "metre", "metres"}:
        return "m"
    if token == "km":
        return "km"
    if token in {"feature", "features"}:
        return "features"
    return token


def _text_number_claims(text: str) -> set[tuple[Decimal, str | None]]:
    return {
        (_normalized_number(match.group("number")), _normalized_unit(match.group("unit")))
        for match in _NUMBER_WITH_UNIT.finditer(text)
    }


def _response_number_claims(text: str) -> list[tuple[Decimal, str | None]]:
    return [
        (_normalized_number(match.group("number")), _normalized_unit(match.group("unit")))
        for match in _NUMBER_WITH_UNIT.finditer(_CARD_ID_PATTERN.sub(" ", text))
    ]


def _check_unverified_conclusions(texts: Sequence[str]) -> None:
    for text in texts:
        for sentence in re.split(r"(?<=[.!?;])\s+", text):
            for pattern in _UNVERIFIED_CONCEPTS:
                match = pattern.search(sentence)
                if not match:
                    continue
                prefix = sentence[max(0, match.start() - 70):match.start()]
                if _NEGATED_LIMITATION.search(prefix):
                    continue
                raise CriticValidationError(
                    "critic returned an unsupported transport or planning conclusion"
                )


def _validate_numeric_claims(
    response: SiteCriticResponse,
    cards_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    narrative = [
        *response.observations,
        *response.design_hypotheses,
        *response.limitations,
        *response.next_questions,
    ]
    _check_unverified_conclusions(narrative)

    for field_name, statements in (
        ("observations", response.observations),
        ("limitations", response.limitations),
    ):
        for statement in statements:
            claims = _response_number_claims(statement)
            if not claims:
                continue
            inline_refs = _CARD_ID_PATTERN.findall(statement)
            if len(set(inline_refs)) != 1 or inline_refs[0] not in response.evidence_refs:
                raise CriticValidationError(
                    "numeric evidence statements must cite one selected Evidence Card inline"
                )
            card = cards_by_id[inline_refs[0]]
            if field_name == "observations":
                metric_name = str(card.get("metric_name") or "").strip()
                if not metric_name or metric_name.casefold() not in statement.casefold():
                    raise CriticValidationError(
                        "numeric observation metric name does not match its cited Evidence Card"
                    )
                value = card.get("value")
                unit = _normalized_unit(str(card.get("unit") or ""))
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not unit:
                    raise CriticValidationError(
                        "numeric observation has no matching deterministic Evidence Card value and unit"
                    )
                supported = {(_normalized_number(str(value)), unit)}
            else:
                supported = set()
                limitations = card.get("limitations")
                if isinstance(limitations, list):
                    for item in limitations:
                        if isinstance(item, str):
                            supported.update(_text_number_claims(item))

            for number, unit in claims:
                if (field_name == "observations" and unit is None) or (number, unit) not in supported:
                    raise CriticValidationError(
                        "critic returned an unsupported numeric claim for the cited Evidence Card"
                    )

    for statement in (*response.design_hypotheses, *response.next_questions):
        if _response_number_claims(statement):
            raise CriticValidationError(
                "critic returned an unsupported numeric claim outside an Evidence Card observation"
            )


_SCHEME_TOKEN = re.compile(r"\b(?:scenario|scheme)-[A-Za-z0-9][A-Za-z0-9_-]*\b")
_SHA256_TOKEN = re.compile(r"\b[0-9a-fA-F]{64}\b")
_BINDING_KEYS = (
    "scenario_id",
    "scheme_id",
    "source_package_revision",
    "study_area_revision",
    "input_sha256",
    "output_sha256",
    "study_area_geometry_sha256",
    "source_hash",
    "radius_m",
    "unit",
)
_HASH_CARD_KEYS = (
    "input_sha256",
    "output_sha256",
    "study_area_geometry_sha256",
    "source_hash",
)


def _binding_text(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer() and abs(value) >= 1:
            return format(value, "f").rstrip("0").rstrip(".")
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()
    return None


def _card_hash_tokens(card: Mapping[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for key in _HASH_CARD_KEYS:
        text = _binding_text(card.get(key))
        if text and _SHA256_TOKEN.fullmatch(text):
            tokens.add(text.lower())
    return tokens


def _card_radii(card: Mapping[str, Any]) -> set[Decimal]:
    radii: set[Decimal] = set()
    for key in ("radius_m", "radius"):
        raw = card.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            continue
        try:
            radii.add(Decimal(str(raw).strip()))
        except InvalidOperation:
            continue
    bounds = card.get("query_bounds")
    if isinstance(bounds, list):
        for item in bounds:
            if not isinstance(item, Mapping):
                continue
            raw = item.get("radius_m")
            if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
                continue
            try:
                radii.add(Decimal(str(raw).strip()))
            except InvalidOperation:
                continue
    return radii


def _validate_citation_binding(
    payload: Mapping[str, Any],
    response: SiteCriticResponse,
    cards_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    """Reject a scheme, unit, radius, revision, or source hash the current cards do not carry.

    SiteCriticResponse ignores unknown keys, so these fields are read from the raw payload.
    """
    cited = [cards_by_id[ref] for ref in response.evidence_refs if ref in cards_by_id]
    scheme_ids = {
        text
        for card in cited
        if (text := _binding_text(card.get("scenario_id")))
    }
    hash_tokens: set[str] = set()
    radii: set[Decimal] = set()
    units: set[str] = set()
    revisions: dict[str, set[str]] = {
        "source_package_revision": set(),
        "study_area_revision": set(),
    }
    for card in cited:
        hash_tokens.update(_card_hash_tokens(card))
        radii.update(_card_radii(card))
        unit = _normalized_unit(_binding_text(card.get("unit")))
        if unit:
            units.add(unit)
        for key in revisions:
            text = _binding_text(card.get(key))
            if text:
                revisions[key].add(text)

    named_scheme = _binding_text(payload.get("scenario_id")) or _binding_text(payload.get("scheme_id"))
    if named_scheme is not None and named_scheme not in scheme_ids:
        raise CriticValidationError(
            "critic cited a scheme that is not in the current evidence bundle"
        )

    narrative = [
        *response.observations,
        *response.design_hypotheses,
        *response.limitations,
        *response.next_questions,
    ]
    for statement in narrative:
        for token in _SCHEME_TOKEN.findall(statement):
            if token not in scheme_ids:
                raise CriticValidationError(
                    "critic cited a scheme that is not in the current evidence bundle"
                )
        for token in _SHA256_TOKEN.findall(statement):
            if token.lower() not in hash_tokens:
                raise CriticValidationError(
                    "critic cited a stale revision or source hash"
                )

    claimed_unit = _normalized_unit(_binding_text(payload.get("unit")))
    if claimed_unit is not None and claimed_unit not in units:
        raise CriticValidationError(
            "critic cited a unit that does not match the current evidence bundle"
        )

    claimed_radius = _binding_text(payload.get("radius_m"))
    if claimed_radius is not None:
        try:
            radius_value = Decimal(claimed_radius)
        except InvalidOperation as exc:
            raise CriticValidationError(
                "critic cited a radius that does not match the current evidence bundle"
            ) from exc
        if radius_value not in radii:
            raise CriticValidationError(
                "critic cited a radius that does not match the current evidence bundle"
            )

    for key, allowed in revisions.items():
        claimed = _binding_text(payload.get(key))
        if claimed is not None and claimed not in allowed:
            raise CriticValidationError("critic cited a stale revision or source hash")

    for key in _HASH_CARD_KEYS:
        claimed = _binding_text(payload.get(key))
        if claimed is not None and claimed.lower() not in hash_tokens:
            raise CriticValidationError("critic cited a stale revision or source hash")


class SiteCriticService:
    """Service to coordinate model critic generation and fail-closed safety checks."""

    def __init__(self, provider=None, *, use_ariadne_persona: bool = False):
        self.provider = provider or get_configured_provider()
        self.use_ariadne_persona = use_ariadne_persona
        if use_ariadne_persona and hasattr(self.provider, "use_ariadne_persona"):
            self.provider.use_ariadne_persona = True

    def validate_critic_response(
        self,
        payload: Mapping[str, Any],
        allowed_evidence_cards: Sequence[Mapping[str, Any]],
        expected_study_area_id: str | None = None,
    ) -> SiteCriticResponse:
        # 1. Check prompt injection in any string value
        for key, val in payload.items():
            text_to_check = []
            if isinstance(val, str):
                text_to_check.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        text_to_check.append(item)

            for text in text_to_check:
                for pat in INJECTION_PATTERNS:
                    if pat.search(text):
                        raise CriticValidationError(
                            f"Model response contained disallowed injection or unauthorized command: {pat.pattern}"
                        )

        # 2. Validate schema and keep provider schema failures inside the critic boundary.
        try:
            resp = SiteCriticResponse.model_validate(payload)
        except ValidationError as exc:
            raise CriticValidationError(
                "Model response did not match the required schema"
            ) from exc

        if resp.provider_status == "LIVE_AI: ACTIVE" and not (
            resp.provider_name and resp.provider_profile_id and resp.provider_model
        ):
            raise CriticValidationError(
                "live AI response must identify its provider profile and actual model"
            )

        if expected_study_area_id is not None and resp.study_area_id != expected_study_area_id:
            raise CriticValidationError(
                "Model response StudyArea does not match the current request"
            )

        # 3. Verify evidence references
        valid_card_ids = {
            c.get("card_id") or c.get("id")
            for c in allowed_evidence_cards
            if (c.get("card_id") or c.get("id"))
        }
        for ref in resp.evidence_refs:
            if ref not in valid_card_ids:
                raise CriticValidationError(
                    f"Model cited fake or unverified evidence ref {ref!r}; not in current evidence bundle"
                )

        cards_by_id = {
            str(c.get("card_id") or c.get("id")): c
            for c in allowed_evidence_cards
            if c.get("card_id") or c.get("id")
        }
        _validate_numeric_claims(resp, cards_by_id)
        _validate_citation_binding(payload, resp, cards_by_id)

        return resp

    def generate_and_validate(
        self,
        study_area_id: str,
        evidence_bundle: Sequence[Mapping[str, Any]],
        query: str = "Explain site conditions, potential, and design hypotheses based strictly on evidence.",
        workspace_id: str | None = None,
        workspace_revision: int | None = None,
    ) -> SiteCriticResponse:
        for pat in INJECTION_PATTERNS:
            if pat.search(query):
                raise CriticValidationError(
                    f"User prompt contained disallowed injection or unauthorized command: {pat.pattern}"
                )

        req = CriticRequest(
            study_area_id=study_area_id,
            workspace_id=workspace_id,
            workspace_revision=workspace_revision,
            evidence_bundle=list(evidence_bundle),
            query=query,
        )
        raw_output = self.provider.generate_criticism(req)
        try:
            validated = self.validate_critic_response(
                raw_output,
                allowed_evidence_cards=evidence_bundle,
                expected_study_area_id=study_area_id,
            )
        except CriticValidationError as exc:
            if raw_output.get("provider_status") == "LIVE_AI: ACTIVE":
                self._record_live_validation(raw_output, passed=False, cause=exc)
            raise
        if raw_output.get("provider_status") == "LIVE_AI: ACTIVE":
            self._record_live_validation(raw_output, passed=True)
        return validated

    def _record_live_validation(
        self,
        payload: Mapping[str, Any],
        *,
        passed: bool,
        cause: Exception | None = None,
    ) -> None:
        record_validation = getattr(self.provider, "record_validation_result", None)
        if not callable(record_validation):
            return
        try:
            persisted = record_validation(payload, passed=passed)
        except Exception as exc:
            raise CriticValidationError(
                "Live critic ModelRun validation outcome could not be persisted; reconcile before retrying."
            ) from exc
        if not persisted:
            raise CriticValidationError(
                "Live critic ModelRun is no longer pending; reconcile before retrying."
            ) from cause
