"""Offline draft knowledge contracts. Loading never activates design constraints."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

Stage = Literal['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8']
Domain = Literal['space_syntax', 'morphology', 'mobility', 'public_space', 'context_response', 'land_use', 'policy', 'portfolio']
Number = StrictInt | StrictFloat

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)

Strength = Literal['STRONG_EMPIRICAL', 'MIXED', 'THEORETICAL', 'NORMATIVE_PRACTICE', 'ASSUMED']

class Verification(Contract):
    status: Literal['VERIFIED', 'AMBIGUOUS', 'NOT_FOUND']
    api: Literal['OpenAlex', 'Crossref', 'Open Library']
    query: dict[str, str | int | None]
    matched_record_id: str | None
    checked_at_utc: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
    match_notes_zh: str = Field(min_length=1)
    @model_validator(mode='after')
    def verified_identity(self):
        if self.status == 'VERIFIED' and not self.matched_record_id:
            raise ValueError('VERIFIED requires matched record id')
        return self

class Claim(Contract):
    claim_id: str = Field(pattern=r'^[A-Z][A-Z0-9_-]+$')
    claim_zh: str = Field(min_length=1)
    strength: Strength
    scope_zh: str = Field(min_length=1)
    assessment_basis: Literal['ABSTRACT_REVIEW', 'BIBLIOGRAPHIC_SCOPE_ONLY']

class LibraryEntry(Contract):
    id: str = Field(pattern=r'^[A-Z][A-Z0-9_-]+$')
    title: str = Field(min_length=1)
    authors: list[str] = Field(min_length=1)
    year: StrictInt
    venue_or_publisher: str = Field(min_length=1)
    doi: str | None
    isbn: str | None
    openalex_id: str | None
    kind: Literal['ACADEMIC_PAPER', 'ACADEMIC_BOOK', 'POLICY', 'PRACTICE_MANUAL', 'PORTFOLIO']
    tradition: str = Field(min_length=1)
    region: list[str] = Field(min_length=1)
    method: str = Field(min_length=1)
    claims: list[Claim] = Field(min_length=1)
    known_critiques: list[str]
    verification: Verification
    limitations_zh: str = Field(min_length=1)
    critique_relationship_zh: str = Field(min_length=1)
    metadata_licence_zh: str = Field(min_length=1)
    @model_validator(mode='after')
    def identity(self):
        if not any((self.doi, self.isbn, self.openalex_id)):
            raise ValueError('library requires DOI, ISBN or OpenAlex id')
        if len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError('duplicate claim id')
        if len(set(self.authors)) != len(self.authors) or any(not a.strip() for a in self.authors):
            raise ValueError('invalid authors')
        return self

class Source(Contract):
    library_id: str = Field(pattern=r'^[A-Z][A-Z0-9_-]+$')
    claim_id: str = Field(pattern=r'^[A-Z][A-Z0-9_-]+$')
    support_scope_zh: str = Field(min_length=1)

class Parameter(Contract):
    name: str = Field(min_length=1)
    value: Number | StrictStr | None
    range: tuple[Number, Number] | None
    unit: str = Field(min_length=1)
    provenance: Literal['SOURCE', 'ASSUMED_COMMANDER', 'FOUNDER']
    source_ids: list[str]
    authority_ref: str | None = None
    status: Literal['PROPOSED_PENDING_FOUNDER', 'CONTEXT_TO_VERIFY', 'PROJECT_INSTRUCTION']
    rationale_zh: str = Field(min_length=1)
    @model_validator(mode='after')
    def valid_parameter(self):
        if (self.value is None) == (self.range is None):
            raise ValueError('parameter requires exactly one value or range')
        nums = self.range or (() if isinstance(self.value, str) else (self.value,))
        if any(not math.isfinite(n) for n in nums):
            raise ValueError('parameter must be finite')
        if self.range and self.range[0] > self.range[1]:
            raise ValueError('reversed parameter range')
        if self.provenance == 'ASSUMED_COMMANDER' and self.status != 'PROPOSED_PENDING_FOUNDER':
            raise ValueError('ASSUMED parameter must remain proposed')
        if self.provenance == 'SOURCE' and not self.source_ids:
            raise ValueError('SOURCE parameter requires library references')
        if self.provenance == 'FOUNDER' and (not self.authority_ref or self.status != 'PROJECT_INSTRUCTION'):
            raise ValueError('FOUNDER parameter requires explicit authority')
        return self

class Check(Contract):
    method_zh: str = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    output: str = Field(min_length=1)
    implementation_status: Literal['SPECIFICATION_ONLY']

class Response(Contract):
    option: str = Field(min_length=1)
    action_zh: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    tradeoff_zh: str = Field(min_length=1)

class RuleCard(Contract):
    id: str = Field(pattern=r'^[A-Z]{3}-[0-9]{3}$')
    title_zh: str = Field(min_length=1)
    title_en: str = Field(min_length=1)
    domain: Domain
    stages: list[Stage] = Field(min_length=1)
    statement_zh: str = Field(min_length=1)
    rationale_zh: str = Field(min_length=1)
    applies_when: dict[str, list[str]]
    parameters: list[Parameter]
    check: Check | None
    check_unavailable_reason_zh: str | None
    design_responses: list[Response] = Field(min_length=2)
    evidence_level: Literal['ACADEMIC', 'POLICY', 'PORTFOLIO', 'COMMON_SENSE_ASSUMED']
    evidence_strength: Strength
    sources: list[Source] = Field(min_length=1)
    source_count_flag: Literal['MULTI_SOURCE', 'SINGLE_SOURCE']
    enforcement: Literal['CANDIDATE_ONLY', 'PROJECT_GUARDRAIL']
    authority_ref: str | None
    local_context_refs: list[str] = []
    debates_zh: str = Field(min_length=1)
    context_validity_zh: str = Field(min_length=1)
    exceptions_zh: str = Field(min_length=1)
    version: str = Field(pattern=r'^\d+\.\d+\.\d+$')
    @model_validator(mode='after')
    def relationships(self):
        ids = [s.library_id for s in self.sources]
        refs = [(s.library_id, s.claim_id) for s in self.sources]
        if len(refs) != len(set(refs)):
            raise ValueError('duplicate source claim reference')
        if self.source_count_flag == 'SINGLE_SOURCE' and self.enforcement != 'CANDIDATE_ONLY':
            raise ValueError('hard rule requires multi-source support')
        if self.enforcement != 'CANDIDATE_ONLY' and not self.authority_ref:
            raise ValueError('hard rule requires explicit project authority')
        if self.enforcement == 'CANDIDATE_ONLY' and self.authority_ref:
            raise ValueError('candidate cannot assert project authority')
        if self.check is None and not self.check_unavailable_reason_zh:
            raise ValueError('null check requires reason')
        if self.check is not None and self.check_unavailable_reason_zh is not None:
            raise ValueError('available check cannot have unavailable reason')
        for obj in [*self.parameters, *self.design_responses]:
            if not set(obj.source_ids) <= set(ids):
                raise ValueError('unresolved source reference')
        for k, values in self.applies_when.items():
            if not k.strip() or not values or any(not v.strip() for v in values):
                raise ValueError('invalid applicability condition')
        if len(self.stages) != len(set(self.stages)):
            raise ValueError('duplicate stage')
        names = [p.name for p in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError('duplicate parameter name')
        return self

class SkillSpec(Contract):
    stage: Stage
    title_zh: str = Field(min_length=1)
    purpose_zh: str = Field(min_length=1)
    trigger_zh: str = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    card_ids: list[str] = Field(min_length=1)
    steps_zh: list[str] = Field(min_length=1)
    llm_responsibility_zh: str = Field(min_length=1)
    deterministic_responsibility_zh: str = Field(min_length=1)
    output_fields: dict[str, str]
    quality_checks_zh: list[str] = Field(min_length=1)
    failure_zh: str = Field(min_length=1)
    requires_design_rationale: StrictBool
    @model_validator(mode='after')
    def rationale_contract(self):
        if self.stage in ('S6', 'S7', 'S8'):
            if not self.requires_design_rationale or not {'design_intent_zh','rationale_zh','rule_card_ids'} <= self.output_fields.keys():
                raise ValueError('S6-S8 require design intent, rationale and card references')
        return self

class DesignKnowledge:
    """Repository-root based loader; explicit root supported for disposable tests.

    Conditions use AND across keys and OR within requested values. Missing constrained
    keys fail closed; unknown keys raise. No conditions means browse all candidates,
    not assert applicability. A wildcard card accepts any supplied value for its key.
    """
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[3]
        rules = self.root / 'knowledge/design_rules'
        schema = json.loads((rules / 'schema.json').read_text(encoding='utf-8'))
        if schema != RuleCard.model_json_schema():
            raise ValueError('schema.json differs from runtime RuleCard schema')
        library_schema = json.loads((self.root / 'knowledge/library-schema.json').read_text(encoding='utf-8'))
        if library_schema != LibraryEntry.model_json_schema():
            raise ValueError('library-schema.json differs from runtime LibraryEntry schema')
        entries = tuple(LibraryEntry.model_validate_json(p.read_text(encoding='utf-8')) for p in sorted((self.root / 'knowledge/library').glob('*.json')))
        if not entries or len({e.id for e in entries}) != len(entries):
            raise ValueError('empty or duplicate library')
        self.library = {e.id: e for e in entries}
        for e in entries:
            if not set(e.known_critiques) <= self.library.keys() or e.id in e.known_critiques:
                raise ValueError('unresolved or self critique reference')
        self.cards = tuple(RuleCard.model_validate_json(p.read_text(encoding='utf-8')) for p in sorted((rules / 'cards').glob('*.json')))
        if not self.cards:
            raise ValueError('no rule cards')
        ids = [c.id for c in self.cards]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate card id')
        for c in self.cards:
            resolved = []
            for ref in c.sources:
                entry = self.library.get(ref.library_id)
                if entry is None or ref.claim_id not in {claim.claim_id for claim in entry.claims}:
                    raise ValueError(f'{c.id}: unresolved library claim reference')
                resolved.append(entry)
            # Portfolio is local context, never an independent research source.
            eligible = [e for e in resolved if e.kind != 'PORTFOLIO' and e.verification.status == 'VERIFIED']
            independent = any(set(a.casefold() for a in x.authors).isdisjoint(a.casefold() for a in y.authors)
                              for i, x in enumerate(eligible) for y in eligible[i + 1:])
            if c.source_count_flag != ('MULTI_SOURCE' if independent else 'SINGLE_SOURCE'):
                raise ValueError(f'{c.id}: source count flag does not match verified independent authors')
            if c.enforcement != 'CANDIDATE_ONLY':
                if any(e.verification.status != 'VERIFIED' for e in resolved):
                    raise ValueError(f'{c.id}: hard rule requires VERIFIED references')
                if not independent or not any(e.kind in ('ACADEMIC_PAPER', 'ACADEMIC_BOOK') for e in eligible):
                    raise ValueError(f'{c.id}: hard rule requires independent academic support')
            if not set(c.local_context_refs) <= {'PORTFOLIO', 'FOUNDER', 'M4H_PENDING'}:
                raise ValueError('unknown local context reference')
        specs = []
        for p in sorted((self.root / 'knowledge/skills').glob('S[1-8]-*.md')):
            blocks = re.findall(r'```json\s*\n(.*?)\n```', p.read_text(encoding='utf-8'), flags=re.S)
            if len(blocks) != 1:
                raise ValueError(f'{p}: expected one JSON skill contract')
            skill = SkillSpec.model_validate_json(blocks[0])
            if not p.name.startswith(skill.stage + '-'):
                raise ValueError('skill filename/stage mismatch')
            if not set(skill.card_ids) <= set(ids):
                raise ValueError('skill references missing card')
            if len(skill.card_ids) != len(set(skill.card_ids)):
                raise ValueError('duplicate skill card reference')
            by_id = {c.id: c for c in self.cards}
            if any(skill.stage not in by_id[cid].stages for cid in skill.card_ids):
                raise ValueError('skill references card outside its stage')
            for input_ref in skill.inputs:
                if input_ref.startswith('TODO_SOURCE:'):
                    continue
                if not (self.root / input_ref).is_file():
                    raise ValueError(f'skill input missing: {input_ref}')
            specs.append(skill)
        if len(specs) != 8 or {s.stage for s in specs} != {f'S{i}' for i in range(1,9)}:
            raise ValueError('requires exactly eight stages')
        self.skills = tuple(specs)

    def author_statistics(self) -> dict:
        from collections import Counter
        entries = [e for e in self.library.values() if e.verification.status == 'VERIFIED' and e.kind != 'PORTFOLIO']
        catalogue = Counter(a for e in entries for a in set(e.authors))
        usages = [(c.id, ref.library_id) for c in self.cards for ref in c.sources
                  if self.library[ref.library_id].verification.status == 'VERIFIED'
                  and self.library[ref.library_id].kind != 'PORTFOLIO']
        counts = Counter(a for _, lid in usages for a in set(self.library[lid].authors))
        def rank(counts, denominator):
            return [{'author': a, 'count': n, 'share': n / denominator} for a, n in counts.most_common()]
        return {'catalogue_denominator': len(entries), 'catalogue': rank(catalogue, len(entries)),
                'citation_denominator': len(usages), 'citations': rank(counts, len(usages))}

    def cards_for(self, stage: Stage, domain: Domain | None = None, conditions: dict[str, str | list[str]] | None = None) -> tuple[RuleCard, ...]:
        if stage not in {f'S{i}' for i in range(1, 9)}:
            raise ValueError('unknown stage')
        domains = {'space_syntax','morphology','mobility','public_space','context_response','land_use','policy','portfolio'}
        if domain is not None and domain not in domains:
            raise ValueError('unknown domain')
        if conditions is not None:
            known = {k for c in self.cards for k in c.applies_when}
            if not conditions.keys() <= known:
                raise ValueError('unknown condition key')
            if any(not isinstance(v, (str,list)) or not v or (isinstance(v,list) and any(not isinstance(x,str) or not x for x in v)) for v in conditions.values()):
                raise ValueError('condition values must be nonempty strings or string lists')
        def matches(c):
            if conditions is None:
                return True
            for key, allowed in c.applies_when.items():
                if '*' in allowed:
                    continue
                query = conditions.get(key)
                if query is None:
                    return False
                requested = [query] if isinstance(query,str) else query
                if not set(requested) & set(allowed):
                    return False
            return True
        return tuple(c for c in self.cards if stage in c.stages and (domain is None or c.domain == domain) and matches(c))


def load_knowledge(root: Path | str | None = None) -> DesignKnowledge:
    return DesignKnowledge(root)
