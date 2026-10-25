"""Legacy typed-evidence migration is bounded and all subsequent replays are inert."""
from test_week6_d1_workspace_binding import authority_copy
from urban_design.analysis_persistence import persist_site_analysis_bundle
from urban_design.workspace_sources import WorkspaceSourceCatalog, DEFAULT_SPATIAL_R01_ROOT
from urban_design.models import EvidenceCard


def inventory(store):
    return {r.entity_id: (r.revision, r.payload) for r in store.list_current()}


def test_legacy_normalization_preserves_results_and_stabilizes(authority_copy):
    store = authority_copy
    catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
    execution = next(r for r in store.list_current('ToolExecution') if r.payload.get('tool') == 'site-analysis')
    artifact = store.current(execution.payload['output_artifact_refs'][0])
    before = inventory(store)
    events = store.events()
    bundle = artifact.payload['bundle']
    def replay():
        return persist_site_analysis_bundle(store, catalog, bundle,
            idempotency_key=execution.payload['idempotency_key'])
    current_exec, current_artifact, cards = replay()
    assert current_artifact.payload['bundle'] == bundle
    assert current_artifact.revision == artifact.revision + 1
    assert current_artifact.payload['sha256'] == 'sha256:' + artifact.payload['sha256'].removeprefix('sha256:')
    assert current_exec.revision == execution.revision + 1
    assert current_exec.payload['parameters'] == {
        **execution.payload['parameters'], 'persistence_schema_version': 'typed-evidence-v2'}
    assert current_exec.payload['output_artifact_hashes'] == [current_artifact.payload['sha256']]
    assert len(cards) == len(bundle['cards']) == 7
    for typed, legacy in zip(cards, bundle['cards'], strict=True):
        parsed = EvidenceCard.model_validate(typed.payload)
        assert parsed.result.values[legacy['metric_key']] == legacy['value']
        assert parsed.metric.unit == legacy['unit']
        assert typed.entity_id not in before
        assert store.current(legacy['card_id']).payload == legacy
    added = store.events()[len(events):]
    assert len(added) == 9
    assert {e.action for e in added} == {
        'NormalizeAnalysisArtifactSha256', 'NormalizeAnalysisToolExecutionSchema',
        'CreateTypedSiteAnalysisEvidenceCard'}
    stable_inventory = inventory(store)
    stable_events = store.events()
    for _ in range(5):
        replay()
        assert inventory(store) == stable_inventory
        assert store.events() == stable_events
