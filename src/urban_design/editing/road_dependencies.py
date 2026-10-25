"""Pure road dependency invalidation and delayed-job publication precondition.

No result bytes/history are rewritten; callers persist a new scenario revision.
The publication guard must run inside the publisher's compare-and-swap transaction.
"""
from typing import Any


def _refs(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError('invalid persisted road dependency references')
    return sorted(set(value))


def stale_road_dependencies(parameters: dict[str, Any], before_hash: str, after_hash: str) -> dict[str, Any]:
    roots = set(_refs(parameters.get('syntax_result_ids', []))) | set(_refs(parameters.get('accessibility_result_ids', []))) | set(_refs(parameters.get('e1_result_ids', [])))
    published = parameters.get('road_job_result_refs', {})
    if not isinstance(published, dict):
        raise ValueError('invalid persisted road job references')
    roots |= set(published)
    dependencies = parameters.get('road_dependency_refs', {})
    if not isinstance(dependencies, dict) or any(not isinstance(k, str) or not k for k in dependencies):
        raise ValueError('invalid persisted road dependency map')
    dependencies = {key: _refs(refs) for key, refs in dependencies.items()}
    stale = roots if before_hash != after_hash else set()
    changed = True
    while changed:
        added = {key for key, refs in dependencies.items() if set(refs) & stale} - stale
        changed = bool(added)
        stale |= added
    statuses = dict(parameters.get('result_statuses', {}))
    statuses.update({key: 'STALE' for key in stale})
    return {'stale_result_ids': sorted(stale), 'result_statuses': statuses}


def require_current_road_job(job_graph_hash: str, job_revision: int, graph_hash: str, revision: int) -> None:
    if not job_graph_hash or job_graph_hash != graph_hash or job_revision != revision:
        raise ValueError('STALE: delayed road job does not match current graph/revision')


def publish_road_job_reference(store: Any, scenario_id: str, *, job_graph_hash: str,
                               job_revision: int, result_id: str, artifact_ref: str) -> Any:
    """Attach an already persisted result reference with scenario CAS.

    This does not compute, validate or approve a result. Publishers must validate
    their artifact first. A concurrent edit makes store.update fail; never retry.
    """
    from .roads import RoadEdge, RoadGraph, RoadNode
    record = store.current(scenario_id)
    if record.entity_type != 'DesignScenario':
        raise ValueError('NOT_READY: scenario is unavailable')
    parameters = dict(record.payload.get('parameters', {}))
    value = parameters['road_graph']
    graph = RoadGraph(tuple(RoadNode(**{**n, 'lineage_ids': tuple(n.get('lineage_ids', []))}) for n in value['nodes']),
                      tuple(RoadEdge(**{**e, 'lineage_ids': tuple(e.get('lineage_ids', [])), 'access_refs': tuple(e.get('access_refs', []))}) for e in value['edges']))
    require_current_road_job(job_graph_hash, job_revision, graph.graph_hash, parameters.get('road_edit_revision_id', 0))
    artifact = store.current(artifact_ref)
    if artifact.entity_type != 'Artifact' or artifact.payload.get('project_id') != record.payload.get('project_id'):
        raise ValueError('NOT_READY: result artifact project differs')
    references = dict(parameters.get('road_job_result_refs', {}))
    if result_id in references:
        raise ValueError('result reference already exists; preserve prior publication')
    references[result_id] = {'artifact_ref': artifact_ref, 'graph_hash': graph.graph_hash, 'road_revision': job_revision,
                             'validation_status': 'UNVERIFIED'}
    parameters['road_job_result_refs'] = references
    payload = {**record.payload, 'parameters': parameters}
    return store.update(scenario_id, payload, expected_revision=record.revision, replace=True,
                        actor='road-job-publisher', actor_kind='AGENT_AUTOMATION', action='AttachRoadJobReference',
                        reason='Attach unverified reference for matching road graph; no approval')
