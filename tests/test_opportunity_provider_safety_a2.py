"""A2 provider fail-closed and retained-output counterexamples (offline only)."""
import ast
import json
from pathlib import Path

import pytest

from test_opportunity_relationships import make_bundle, make_resolver
from urban_design.site_intelligence.opportunities import (
    _sanitize_raw, _validate_generated_text, suggest_opportunities,
)
from urban_design.site_intelligence.relationships import RelationshipValidationError


def provider_status_literals():
    tree = ast.parse(Path('src/urban_design/model_provider.py').read_text())
    return sorted({node.value for node in ast.walk(tree)
                   if isinstance(node, ast.Constant) and isinstance(node.value, str)
                   and node.value.startswith(('LIVE_AI: ', 'NON_AI: '))})


@pytest.mark.parametrize('status', provider_status_literals() + ['LIVE_AI: FUTURE_UNKNOWN'])
def test_every_provider_status_is_fail_closed_before_repair(status):
    class Provider:
        available = True
        is_live = False
        proposes = repairs = 0

        def propose(self, request):
            self.proposes += 1
            return {'provider_status': status, 'opportunities': []}

        def repair(self, *args):
            self.repairs += 1
            return {}

    provider = Provider()
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider, max_repair=0 if status in {
        "LIVE_AI: ACTIVE", "NON_AI: DETERMINISTIC_TEMPLATE"} else 1)
    assert provider.proposes == 1
    assert provider.repairs == 0
    if status in {'LIVE_AI: ACTIVE', 'NON_AI: DETERMINISTIC_TEMPLATE'}:
        assert result.status == 'INVALID_MODEL_OUTPUT'  # allowed into content validation
    elif status == 'LIVE_AI: OUTCOME_UNKNOWN':
        assert result.status == 'OUTCOME_UNKNOWN'
    else:
        assert result.status == 'UNAVAILABLE'
    assert not result.opportunities


@pytest.mark.parametrize('status', ['LIVE_AI: HERMES_TOOLS_ENABLED',
                                  'LIVE_AI: HERMES_TOOLSET_RESPONSE_INVALID',
                                  'LIVE_AI: FUTURE_UNKNOWN'])
def test_unavailable_status_never_repairs_even_with_repair_budget(status):
    class Provider:
        available = True
        is_live = False
        proposes = repairs = 0
        def propose(self, request):
            self.proposes += 1
            return {'provider_status': status, 'design_hypotheses': ['Test connectivity.'],
                    'evidence_refs': [item.token for item in request.allowed_evidence_refs]}
        def repair(self, *args):
            self.repairs += 1
            raise AssertionError('must not dispatch repair')
    provider = Provider()
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider)
    assert (provider.proposes, provider.repairs) == (1, 0)
    assert result.status == 'UNAVAILABLE'
    assert not result.opportunities


@pytest.mark.parametrize('tag', ['think', 'thinking', 'reasoning', 'scratchpad'])
def test_private_tags_are_filtered_and_rejected(tag):
    payload = f'<{tag}>synthetic-private</{tag}>Public text.'
    assert _sanitize_raw({'statement': payload}) == {'statement': 'Public text.'}
    assert _sanitize_raw({'statement': f'<{tag}>synthetic-private'}) == {'statement': ''}
    with pytest.raises(RelationshipValidationError):
        _validate_generated_text(payload, 'statement')


@pytest.mark.parametrize('token', [
    'ghp_SyntheticFakeOnly', 'AKIAABCDEFGHIJKLMNOP', 'xoxb-synthetic-fake',
    'eyJsynthetic.payload.signature', 'AIzaSyntheticFakeOnly',
    '-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----',
    'Authorization: Basic c3ludGhldGlj',
])
def test_common_synthetic_credential_patterns_never_retained(token):
    result = _sanitize_raw({'statement': token, 'unknown_field': token,
                            'refresh_token': token, 'x-api-key': token})
    assert token not in json.dumps(result)
    assert set(result) == {'statement'}
    with pytest.raises(RelationshipValidationError):
        _validate_generated_text(token, 'statement')


def test_raw_field_allowlist_drops_arbitrary_nested_fields():
    assert _sanitize_raw({'opportunities': [{'statement': 'Public',
                                            'harmless_looking': 'synthetic-private'}],
                          'notes': 'synthetic-private'}) == {
        'opportunities': [{'statement': 'Public'}]}


@pytest.mark.parametrize('status', [None, [], {}, 7, 'LIVE_AI: FUTURE_OUTCOME_UNKNOWN'])
def test_malformed_or_unknown_status_is_unavailable_without_repair(status):
    from test_opportunity_relationships import FixtureSuggestionProvider, _suggestion_payload, INPUT
    from urban_design.site_intelligence.opportunities import reference_token
    raw = _suggestion_payload([reference_token(INPUT)])
    raw['provider_status'] = status
    provider = FixtureSuggestionProvider(raw, repaired=raw)
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider)
    assert result.status == 'UNAVAILABLE'
    assert (provider.propose_calls, provider.repair_calls) == (1, 0)


def test_unclosed_pem_header_never_retained():
    assert 'synthetic-private' not in str(_sanitize_raw({'statement': '-----BEGIN PRIVATE KEY-----synthetic-private'}))
