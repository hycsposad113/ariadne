"""Offline end-to-end fixed-template enforcement, including A2 number-word bypasses."""
import pytest

from test_opportunity_relationships import (
    INPUT, FixtureSuggestionProvider, _suggestion_payload, make_bundle, make_resolver,
)
from urban_design.site_intelligence.opportunities import reference_token, suggest_opportunities


@pytest.mark.parametrize('text', [
    'twenty percent', 'one hundred twenty meters', 'half of the edge',
    'a third of the site', 'two thirds', 'twelve', 'XII', 'Ⅻ', '半數',
    'Forty-two buildings', '¾', '120 m',
])
@pytest.mark.parametrize('route', ['free_hypothesis', 'statement', 'direction', 'verification', 'template_id', 'metric_ref'])
def test_quantity_cannot_enter_final_statement_via_any_template_route(text, route):
    raw = _suggestion_payload([reference_token(INPUT)])
    if route == 'free_hypothesis':
        raw = {'design_hypotheses': [text], 'evidence_refs': [reference_token(INPUT)]}
    elif route == 'statement':
        raw['opportunities'][0]['statement'] = text
    else:
        raw['opportunities'][0]['statement_template'][route] = text
    provider = FixtureSuggestionProvider(raw)
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider, max_repair=0)
    assert result.status == 'INVALID_MODEL_OUTPUT'
    assert result.opportunities == ()
    assert (provider.propose_calls, provider.repair_calls) == (1, 0)


@pytest.mark.parametrize('status', ['LIVE_AI: ACTIVE', 'NON_AI: DETERMINISTIC_TEMPLATE'])
def test_explicit_usable_status_accepts_server_rendered_fixed_template(status):
    raw = _suggestion_payload([reference_token(INPUT)])
    raw['provider_status'] = status
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=FixtureSuggestionProvider(raw), max_repair=0)
    assert result.status == 'AVAILABLE'
    opportunity = result.opportunities[0]
    assert opportunity.statement == ('road_degree_one_vertex_count indicates a unresolved tendency; '
                                      'verify through deterministic analysis.')
    assert opportunity.statement_template.metric_ref == 'road_degree_one_vertex_count'
    assert result.raw_structured_output['opportunities'][0]['statement_template']['template_id'] == 'METRIC_TENDENCY'


@pytest.mark.parametrize('status', ['LIVE_AI: HERMES_TOOLS_ENABLED',
                                  'LIVE_AI: HERMES_TOOLSET_RESPONSE_INVALID', 'LIVE_AI: FUTURE_UNKNOWN'])
def test_valid_template_content_cannot_bypass_unavailable_provider_status(status):
    raw = _suggestion_payload([reference_token(INPUT)])
    raw['provider_status'] = status
    provider = FixtureSuggestionProvider(raw, repaired=raw)
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider)
    assert result.status == 'UNAVAILABLE'
    assert result.opportunities == ()
    assert (provider.propose_calls, provider.repair_calls) == (1, 0)
