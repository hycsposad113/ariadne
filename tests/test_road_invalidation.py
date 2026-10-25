from urban_design.editing.road_dependencies import stale_road_dependencies, require_current_road_job
import pytest


def test_transitive_stale_preserves_history_and_unrelated():
    params = {'syntax_result_ids': ['syntax'], 'accessibility_result_ids': ['access'],
              'road_dependency_refs': {'comparison': ['access'], 'report': ['comparison'], 'height': ['massing']},
              'result_statuses': {'height': 'CURRENT', 'report': 'CURRENT'}}
    result = stale_road_dependencies(params, 'old', 'new')
    assert result['stale_result_ids'] == ['access', 'comparison', 'report', 'syntax']
    assert result['result_statuses']['height'] == 'CURRENT'
    assert params['result_statuses']['report'] == 'CURRENT'
    assert stale_road_dependencies(params, 'old', 'old')['stale_result_ids'] == []


def test_delayed_job_cannot_publish_to_new_graph_or_revision():
    require_current_road_job('hash', 2, 'hash', 2)
    with pytest.raises(ValueError, match='STALE'):
        require_current_road_job('old', 1, 'new', 2)
    with pytest.raises(ValueError, match='STALE'):
        require_current_road_job('hash', 1, 'hash', 2)
