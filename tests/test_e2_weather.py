from pathlib import Path

import pytest
from test_e2_execution import authority, approval
from urban_design.environment.weather_snapshot import publish_candidate01, load_weather, E2Blocked, CANDIDATE_HASHES
from urban_design.store import ProjectStateStore

# Frozen repository fixtures only; never current project authority.
PROJECT = Path(__file__).resolve().parents[1]
PROPOSAL = PROJECT / 'artifacts/w5-weather-derived-method-proposal-20260926T115309Z'


def test_immutable_fixture_lineage():
    import hashlib
    import json
    analysis_bytes = (PROPOSAL / 'candidate-01/analysis.json').read_bytes()
    assert hashlib.sha256(analysis_bytes).hexdigest() == '6abd39570fe5043a94170eac1a2cf1e683f38fd271d8b32b559758db3971adb0'
    analysis = json.loads(analysis_bytes)
    assert analysis['classification'] == 'PROPOSAL_ONLY'
    assert analysis['candidate_id'] == 'candidate-01'
    paths = {'source': PROJECT / analysis['source']['source_r08_relative_path'],
             'derived': PROPOSAL / 'candidate-01/derived-minute60.epw',
             'mapping': PROPOSAL / 'candidate-01/minute-row-mapping.csv'}
    assert {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()} == CANDIDATE_HASHES
    assert analysis['source']['sha256'] == analysis['derivation']['input_sha256'] == CANDIDATE_HASHES['source']
    assert analysis['derivation']['output_sha256'] == CANDIDATE_HASHES['derived']
    assert analysis['derivation']['mapping_sha256'] == CANDIDATE_HASHES['mapping']



def test_snapshot_approval_drift_and_restart(authority):
    store, client, key, root = authority
    snapshot = publish_candidate01(store, 'p', PROPOSAL, PROJECT, root / 'artifacts')
    assert snapshot.payload['status'] == 'PROPOSED'
    # PD-08-C01 permits proposal records, never implicit source approval.
    assert store.list_current('HumanDecision', project_id='p') == []
    _, proposal_bundle, _, proposal_decision = load_weather(
        store, snapshot.entity_id, 'p', require_approval=False)
    assert proposal_decision is None
    assert proposal_bundle['supplier_timing_semantics_proven'] is False
    with pytest.raises(E2Blocked, match='NOT_APPROVED'):
        load_weather(store, snapshot.entity_id, 'p')
    response = approval(client, snapshot, key)
    assert response.status_code == 201, response.text
    record, bundle, epw, decision = load_weather(store, snapshot.entity_id, 'p')
    assert epw.suffix == '.epw'
    reopened = ProjectStateStore(root / 'copy.sqlite3')
    try:
        assert load_weather(reopened, snapshot.entity_id, 'p')[3] == decision
    finally:
        reopened.close()
    store.update(snapshot.entity_id, {'sha256':'sha256:'+'0'*64})
    with pytest.raises(E2Blocked, match='WEATHER_SNAPSHOT_BINDING_MISMATCH'):
        load_weather(store, snapshot.entity_id, 'p')


def test_weather_source_bytes_unchanged(authority):
    store, _, _, root = authority
    files = list((PROPOSAL / 'candidate-01').iterdir())
    before = {str(p):p.read_bytes() for p in files if p.is_file()}
    publish_candidate01(store, 'p', PROPOSAL, PROJECT, root / 'artifacts')
    assert all(Path(p).read_bytes() == data for p,data in before.items())


def test_hour_end_sensitivity_keeps_weather_values(authority):
    from types import SimpleNamespace
    from urban_design.environment.e2_service import weather_for_period
    store, _, _, root = authority
    snapshot = publish_candidate01(store, 'p', PROPOSAL, PROJECT, root / 'artifacts')
    _, _, epw, _ = load_weather(store, snapshot.entity_id, 'p', require_approval=False)
    period = SimpleNamespace(start_month=6,start_day=21,end_month=6,end_day=21,start_hour=9,end_hour=15)
    weas = [weather_for_period(epw,period,shift) for shift in (-1,0,1)]
    assert [wea.datetimes[0].hour for wea in weas] == [8,9,10]
    assert all(wea.datetimes[0].minute == 0 for wea in weas)
    assert all(len(wea.hoys) == 7 for wea in weas)
    assert weas[0].direct_normal_irradiance.values == weas[1].direct_normal_irradiance.values == weas[2].direct_normal_irradiance.values
    assert weas[0].diffuse_horizontal_irradiance.values == weas[1].diffuse_horizontal_irradiance.values == weas[2].diffuse_horizontal_irradiance.values


@pytest.mark.parametrize("field,value", [
    ("snapshot_id", "wrong-snapshot"),
    ("snapshot_version", "unapproved-invented-version"),
    ("bundle_sha256", "sha256:" + "0" * 64),
    ("source_sha256", "sha256:" + "0" * 64),
    ("derived_sha256", "sha256:" + "0" * 64),
    ("mapping_sha256", "sha256:" + "0" * 64),
])
def test_exact_weather_qualification_lineage_denied(authority, field, value):
    from urban_design.environment.e2_service import weather_lineage, check_qualification_lineage
    store, _, _, root = authority
    snapshot = publish_candidate01(store, 'p', PROPOSAL, PROJECT, root / 'FIXTURE_ONLY')
    record, bundle, _, _ = load_weather(store, snapshot.entity_id, 'p', require_approval=False)
    lineage = weather_lineage(record, bundle)
    receipt = {"qualification_scope": "EXACT_WEATHER_FIXTURE_ONLY", "weather_lineage": lineage}
    check_qualification_lineage(receipt, record, bundle)
    receipt["weather_lineage"] = {**lineage, field: value}
    with pytest.raises(E2Blocked, match="METHOD_QUALIFICATION_WEATHER_LINEAGE_INVALID"):
        check_qualification_lineage(receipt, record, bundle)


@pytest.mark.parametrize("receipt", [{}, {"qualification_scope": "RUNTIME_GENERAL", "weather_lineage": {}}])
def test_legacy_or_runtime_general_receipt_not_exact_weather_proof(authority, receipt):
    from urban_design.environment.e2_service import check_qualification_lineage
    store, _, _, root = authority
    snapshot = publish_candidate01(store, 'p', PROPOSAL, PROJECT, root / 'FIXTURE_ONLY')
    record, bundle, _, _ = load_weather(store, snapshot.entity_id, 'p', require_approval=False)
    with pytest.raises(E2Blocked, match="METHOD_QUALIFICATION_WEATHER_LINEAGE_INVALID"):
        check_qualification_lineage(receipt, record, bundle)


def test_pd08_content_version_is_preserved_assumption_not_approval():
    import hashlib
    from urban_design.environment.e2_service import PD08_ASSUMPTION_REF
    raw = (PROJECT / 'docs/decisions/2026-09-25-plan-decisions-zh.md').read_bytes()
    section = raw[raw.index('## PD-08 '.encode()):raw.index('## PD-09 '.encode())]
    assert PD08_ASSUMPTION_REF == 'PD-08@sha256:' + hashlib.sha256(section).hexdigest()
    assert '批准前不得發布 DatasetSnapshot'.encode() in section


def test_runtime_general_scope_denied_with_valid_current_weather_lineage(authority):
    from urban_design.environment.e2_service import (
        WeatherLineage, weather_lineage, check_qualification_lineage,
    )
    store, _, _, root = authority
    snapshot = publish_candidate01(store, 'p', PROPOSAL, PROJECT, root / 'FIXTURE_ONLY')
    record, bundle, _, _ = load_weather(store, snapshot.entity_id, 'p', require_approval=False)
    lineage = weather_lineage(record, bundle)
    # All six current fields pass schema validation and the exact-scope control.
    assert WeatherLineage.model_validate(lineage).model_dump(mode='json') == lineage
    receipt = {'qualification_scope': 'EXACT_WEATHER_FIXTURE_ONLY', 'weather_lineage': lineage}
    check_qualification_lineage(receipt, record, bundle)
    # Scope is the only difference; missing/incorrect lineage cannot mask it.
    receipt['qualification_scope'] = 'RUNTIME_GENERAL'
    with pytest.raises(E2Blocked, match='METHOD_QUALIFICATION_WEATHER_LINEAGE_INVALID'):
        check_qualification_lineage(receipt, record, bundle)
