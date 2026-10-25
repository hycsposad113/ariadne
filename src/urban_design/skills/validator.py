"""Deterministic reference, numeric binding and stage completeness checks."""
from __future__ import annotations
import math
import re
import unicodedata
from pydantic import ValidationError
from .contracts import SkillOutput

NUMBER = re.compile(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?')
IDENTIFIER = re.compile(r'\b[A-Z][A-Z0-9_]+(?:-[A-Z0-9_]+)+\b')
EXTERNAL = re.compile(r'https?://\S+|\b10\.\d{4,9}/\S+|\b(?:ISBN|doi)\s*[:：]?\s*\S+', re.I)


def validate(raw: str, *, skill_id: str, cards, library, metrics: dict, tolerance: float = 1e-6):
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('numeric tolerance must be finite and nonnegative')
    try:
        output = SkillOutput.model_validate_json(raw)
    except (ValidationError, ValueError):
        return None, ['INVALID_JSON_OR_SCHEMA']
    errors = []
    supplied = {c.id: c for c in cards}
    refs = set(output.rule_card_ids)
    refs.update(cid for strategy in output.strategies for cid in strategy.rule_card_ids)
    if not refs <= supplied.keys():
        errors.append('CARD_NOT_SUPPLIED')
    if any(not set(strategy.rule_card_ids) <= set(output.rule_card_ids) for strategy in output.strategies):
        errors.append('STRATEGY_CITATION_NOT_DECLARED')
    permitted_library = {s.library_id for cid in refs if cid in supplied for s in supplied[cid].sources}
    if not set(output.library_ids) <= permitted_library:
        errors.append('EXTERNAL_LITERATURE')
    for cid in refs & supplied.keys():
        if supplied[cid].enforcement != 'CANDIDATE_ONLY' and any(
                library[s.library_id].verification.status != 'VERIFIED' for s in supplied[cid].sources):
            errors.append('HARD_CARD_UNVERIFIED_SOURCE')
    if skill_id == 'S3' and len(output.strategies) < 2:
        errors.append('MISSING_STRATEGY_ALTERNATIVES')
    if skill_id == 'S7' and not all((output.strengths_zh, output.weaknesses_zh, output.risks_zh, output.goal_results_zh)):
        errors.append('MISSING_CRITIQUE')
    if skill_id == 'S8' and not all((output.walking_zh.strip(), output.massing_response_zh.strip(), output.uncertainties_zh)):
        errors.append('MISSING_DESIGN_EXPLANATION')
    if len(output.alternatives_zh) < 2:
        errors.append('MISSING_ALTERNATIVES')
    claims = []
    for claim in output.numeric_claims:
        metric = metrics.get(claim.metric_id)
        if (not metric or not isinstance(metric.get('value'), (int, float))
                or isinstance(metric.get('value'), bool) or not math.isfinite(claim.value)
                or not math.isfinite(metric['value']) or claim.unit != metric.get('unit')
                or abs(claim.value - metric['value']) > tolerance):
            errors.append('UNSUPPORTED_NUMBER')
        else:
            claims.append(claim)
    # All prose fields are scanned; ID lists and structured numeric values are separate.
    prose = output.model_dump(exclude={'rule_card_ids', 'library_ids', 'numeric_claims'})
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key != 'rule_card_ids':
                    yield from strings(item)
    for text in strings(prose):
        text = unicodedata.normalize('NFKC', text)
        if EXTERNAL.search(text):
            errors.append('EXTERNAL_LITERATURE')
        for title in re.findall(r'《([^》]+)》', text):
            if title not in {library[lid].title for lid in permitted_library}:
                errors.append('EXTERNAL_LITERATURE')
        if re.search(r'根據.*(?:研究|文獻)|(?:研究|文獻).*(?:指出|顯示|認為)|according to', text, re.I):
            if not any(lid in text for lid in permitted_library):
                errors.append('EXTERNAL_LITERATURE')
        for match in IDENTIFIER.finditer(text):
            ref = match.group()
            if ref not in supplied and ref not in permitted_library and ref not in metrics and ref not in {'DATA-GAP'}:
                errors.append('REFERENCE_NOT_SUPPLIED')
        scrubbed = re.sub(r'\b(?:D1|D2|C1|S[1-8])\b', '', text)
        for ref in sorted(set(supplied) | permitted_library | set(metrics), key=len, reverse=True):
            scrubbed = scrubbed.replace(ref, '')
        for match in NUMBER.finditer(scrubbed):
            value = float(match.group())
            if not any(abs(value - c.value) <= tolerance and c.metric_id in text and c.unit in text for c in claims):
                errors.append('UNSUPPORTED_NUMBER')
        # Chinese written quantitative assertions also need structured metric binding.
        if re.search(r'[零〇一二三四五六七八九十百千萬億兩]+(?:公尺|米|平方米|平方公尺|層|%|％)', scrubbed):
            errors.append('UNSUPPORTED_NUMBER')
    return output, sorted(set(errors))
