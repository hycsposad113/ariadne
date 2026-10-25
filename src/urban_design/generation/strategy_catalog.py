"""Registered G2 road/public-space strategy candidates.

The catalogue interprets only the small, explicit intent-ID vocabulary below.
Free text remains visible to the caller but never silently becomes geometry
instructions.
"""

from __future__ import annotations

from dataclasses import dataclass

from urban_design.generation.contracts import (
    MethodProvenance,
    MethodSourceKind,
    StrategyReason,
    StrategySpec,
)


FAMILY_IDS = ("CONNECTED_GRID", "CENTRAL_COMMON", "LINEAR_SPINE")
_TOPOLOGY_INTENTS = {
    f"topology:{effect}:{family}": (effect, family)
    for effect in ("require", "avoid")
    for family in FAMILY_IDS
}
_WATERFRONT_INTENT = "open-space:prefer-waterfront"
_HIERARCHY = {
    "CONNECTED_GRID": ("DISTRIBUTED_NODES",),
    "CENTRAL_COMMON": ("CENTRAL_COMMON",),
    "LINEAR_SPINE": ("SPINE",),
}


@dataclass(frozen=True)
class StrategyCatalog:
    strategies: tuple[StrategySpec, ...]
    excluded_families: tuple[str, ...] = ()
    unsupported_intent_ids: tuple[str, ...] = ()
    status: str = "READY"
    blocked_reason: str | None = None


def _registered_method(family: str) -> MethodProvenance:
    label = family.replace("_", " ").lower()
    return MethodProvenance(
        method_id=f"g2.skeleton.{family.lower()}",
        version="g2-skeleton-v1",
        description=f"Registered deterministic {label} road and public-space candidate",
        source_kind=MethodSourceKind.REGISTERED_DETERMINISTIC_METHOD,
    )


def build_strategy_catalog(brief) -> StrategyCatalog:
    """Build strategy candidates from an A2 DesignBriefRevision.

    Supported topology directives are deliberately literal:
    ``topology:require:<FAMILY>`` must be a REQUIRED_FEATURE and
    ``topology:avoid:<FAMILY>`` must be an AVOID_FEATURE. The exact
    ``open-space:prefer-waterfront`` PREFERENCE changes only the linear spine
    target policy. Unknown ids are reported and their natural-language text is
    not interpreted.
    """

    intents = tuple(getattr(brief, "intents", ()))
    required: set[str] = set()
    avoided: set[str] = set()
    unsupported: list[str] = []
    invalid_registered_intent = False
    for intent in intents:
        intent_id = intent.id
        directive = _TOPOLOGY_INTENTS.get(intent_id)
        if directive is not None:
            effect, family = directive
            expected_kind = "REQUIRED_FEATURE" if effect == "require" else "AVOID_FEATURE"
            if intent.kind != expected_kind:
                unsupported.append(intent_id)
                invalid_registered_intent = True
                continue
            (required if effect == "require" else avoided).add(family)
            continue
        if intent_id == _WATERFRONT_INTENT and intent.kind == "PREFERENCE":
            continue
        unsupported.append(intent_id)

    if invalid_registered_intent:
        return StrategyCatalog(
            strategies=(),
            unsupported_intent_ids=tuple(sorted(set(unsupported))),
            status="BLOCKED",
            blocked_reason="registered topology intent uses an incompatible A2 intent kind",
        )

    if len(required) > 1:
        return StrategyCatalog(
            strategies=(),
            excluded_families=tuple(family for family in FAMILY_IDS if family not in required),
            unsupported_intent_ids=tuple(sorted(set(unsupported))),
            status="BLOCKED",
            blocked_reason="multiple incompatible required topology families cannot be satisfied together",
        )

    allowed = set(required) if required else set(FAMILY_IDS)
    allowed -= avoided
    if not allowed:
        return StrategyCatalog(
            strategies=(),
            excluded_families=FAMILY_IDS,
            unsupported_intent_ids=tuple(sorted(set(unsupported))),
            status="BLOCKED",
            blocked_reason="brief topology intents exclude every registered family",
        )

    relevant_intents = {
        family: tuple(
            intent.id
            for intent in intents
            if (directive := _TOPOLOGY_INTENTS.get(intent.id)) is not None
            and directive[1] == family
        )
        for family in FAMILY_IDS
    }
    waterfront = any(
        intent.id == _WATERFRONT_INTENT and intent.kind == "PREFERENCE"
        for intent in intents
    )
    strategies: list[StrategySpec] = []
    for family in FAMILY_IDS:
        if family not in allowed:
            continue
        policy = {"spine_target": "EXPLICIT"}
        hierarchy = _HIERARCHY[family]
        intent_ids = relevant_intents[family]
        reasons = [
            StrategyReason(text=f"Candidate topology family: {family}; no ranking is implied.")
        ]
        if family == "LINEAR_SPINE" and waterfront:
            policy = {"spine_target": "WATERFRONT"}
            hierarchy = ("WATERFRONT_SPINE", "SPINE")
            intent_ids = (*intent_ids, _WATERFRONT_INTENT)
            reasons.append(StrategyReason(text="A2 preference selects a source-derived waterfront target."))
        for intent_id in intent_ids:
            reasons.append(StrategyReason(text=f"Responds to registered A2 intent {intent_id}."))
        strategies.append(
            StrategySpec(
                strategy_id=f"g2.{family.lower()}.v1",
                topology_family=family,
                registered_method=_registered_method(family),
                intent_ids=tuple(intent_ids),
                open_space_hierarchy=hierarchy,
                program_policy=policy,
                reasons=tuple(reasons),
            )
        )

    insufficient = len(strategies) < 3
    return StrategyCatalog(
        strategies=tuple(strategies),
        excluded_families=tuple(family for family in FAMILY_IDS if family not in allowed),
        unsupported_intent_ids=tuple(sorted(set(unsupported))),
        status="INSUFFICIENT" if insufficient else "READY",
    )
