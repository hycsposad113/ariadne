"""Typed skill output: proposals and commentary never make human decisions."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr


NonBlank = Annotated[StrictStr, Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)


class NumericClaim(Contract):
    metric_id: StrictStr = Field(min_length=1)
    value: StrictFloat | StrictInt
    unit: StrictStr = Field(min_length=1)


class Strategy(Contract):
    strategy_zh: StrictStr = Field(min_length=1)
    targets_zh: list[NonBlank] = Field(min_length=1)
    rationale_zh: StrictStr = Field(min_length=1)
    rule_card_ids: list[NonBlank] = Field(min_length=1)


class SkillOutput(Contract):
    # This is interpretation status, not a DesignScenario state transition.
    status: Literal['DRAFT', 'INCOMPLETE', 'INVALID']
    design_intent_zh: StrictStr = Field(min_length=1)
    rationale_zh: StrictStr = Field(min_length=1)
    rule_card_ids: list[NonBlank] = Field(min_length=1)
    library_ids: list[NonBlank]
    numeric_claims: list[NumericClaim]
    uncertainties_zh: list[NonBlank]
    strategies: list[Strategy]
    strengths_zh: list[NonBlank]
    weaknesses_zh: list[NonBlank]
    risks_zh: list[NonBlank]
    goal_results_zh: list[NonBlank]
    walking_zh: StrictStr
    massing_response_zh: StrictStr
    alternatives_zh: list[NonBlank]


class RunRequest(Contract):
    idempotency_key: StrictStr = Field(min_length=1, max_length=128)
    conditions: dict[StrictStr, StrictStr | list[NonBlank]] | None = None
    knowledge_query_zh: StrictStr | None = Field(default=None, min_length=1, max_length=2000)
