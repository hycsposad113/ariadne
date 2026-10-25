"""Bounded offline interpretation output; private reasoning is not accepted."""
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictFloat, StrictStr

class Citation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    evidence_id: StrictStr
    revision: StrictInt | None = None
    unit: StrictStr | None = None
    method_id: StrictStr | None = None

class OfflineInterpretation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    statement: StrictStr = Field(default='',max_length=4000)
    citations: list[Citation] = Field(default_factory=list)
    stated_numbers: list[StrictInt | StrictFloat] = Field(default_factory=list)
