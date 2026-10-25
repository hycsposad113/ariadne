"""Read-only analysis lineage; visibility and freshness never confer authority."""
from __future__ import annotations
from typing import Literal
from types import SimpleNamespace
from pydantic import BaseModel, ConfigDict
from urban_design.store import EntityNotFoundError


class AnalysisProjection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    execution_id: str
    artifact_ids: list[str]
    stage: str
    source_scenario_id: str
    source_revision: int | None
    geometry_sha256: str | None
    freshness: Literal['current','stale','unknown']
    validation_status: str = 'unverified'


def scenario_lineage(store, scenario):
    """Follow declared parent refs for display only, never acceptance inheritance."""
    rows = {scenario.entity_id: scenario}
    row = scenario
    while row.payload.get('parent_scenario_id'):
        parent_id = row.payload['parent_scenario_id']
        if parent_id in rows:
            break
        try:
            parent = store.current(parent_id)
        except EntityNotFoundError:
            break
        if parent.entity_type != 'DesignScenario' or parent.project_id != scenario.project_id:
            break
        rows[parent_id] = parent
        row = parent
    return rows


def analysis_results(store, scenario):
    lineage = scenario_lineage(store, scenario)
    projections = []
    for run in store.list_current('ToolExecution', project_id=scenario.project_id):
        p = run.payload
        parameters = p.get('parameters') or {}
        pins = parameters.get('scenario_pins', [])
        source_id = p.get('scenario_id')
        if source_id not in lineage:
            source_id = next((v.get('scenario_id') for v in pins if v.get('scenario_id') in lineage), None)
        if source_id not in lineage:
            continue
        artifacts = []
        kinds = []
        for identifier in p.get('output_artifact_refs', []):
            try:
                artifact = store.current(identifier)
            except EntityNotFoundError:
                continue
            if artifact.entity_type != 'Artifact' or artifact.project_id != scenario.project_id:
                continue
            kind = str(artifact.payload.get('type','')).lower().replace('_','-')
            if any(term in kind for term in ('result','analysis','syntax')):
                artifacts.append(identifier); kinds.append(kind)
        if not artifacts:
            continue
        stage = ('E1' if any('sunlight' in k for k in kinds) else
                 'E2' if p.get('tool') in {'ladybug_radiance','honeybee_radiance'} or any('radiation' in k for k in kinds) else
                 'Syntax' if any('syntax' in k for k in kinds) else 'Analysis')
        pin = next((v for v in pins if v.get('scenario_id') == source_id), {})
        source_revision = pin.get('scenario_revision',parameters.get('scenario_revision'))
        # Legacy E2 embeds the full approved immutable plan.
        for name in ('baseline','modified'):
            old_pin = (parameters.get('plan') or {}).get(name, {})
            if old_pin.get('scenario_id') == source_id:
                pin = old_pin; source_revision = old_pin.get('revision')
        source = lineage[source_id]
        hashes = p.get('input_artifact_hashes_by_id') or p.get('input_hashes') or {}
        geometry_hash = pin.get('geometry_sha256') or hashes.get(source.payload.get('geometry_artifact_id'))
        if geometry_hash is None:
            for identifier, expected in hashes.items():
                try:
                    artifact = store.current(identifier)
                except EntityNotFoundError:
                    continue
                if 'scenario' in str(artifact.payload.get('type','')).lower() and 'geometry' in str(artifact.payload.get('type','')).lower():
                    # Older artifacts can be found through immutable scenario history.
                    if any(r.payload.get('geometry_artifact_id') == identifier for r in store.history(source_id)):
                        geometry_hash = expected
                        break
        freshness = 'unknown'
        if geometry_hash:
            freshness = ('current' if source_revision is not None else 'unknown') if geometry_hash == scenario.payload.get('geometry_sha256') else 'stale'
        if source_revision is not None:
            expected_revision = scenario.revision if source_id == scenario.entity_id else (scenario.payload.get('parameters') or {}).get('parent_revision')
            if source_revision != expected_revision:
                freshness = 'stale'
        input_hashes_valid = True
        for identifier, expected in hashes.items():
            try:
                actual = store.current(identifier).payload.get('sha256')
            except EntityNotFoundError:
                freshness = 'stale'; input_hashes_valid = False; break
            if actual and actual != expected:
                freshness = 'stale'; input_hashes_valid = False; break
        if p.get('tool') == 'scenario-space-syntax' and input_hashes_valid:
            # S5 depends on roads and analysis boundary, not building floorplates.
            # Resolve the prospective payload as well as persisted records so road
            # edits are marked STALE before the new scenario revision is committed.
            try:
                from .scenario_syntax_api import scenario_document
                from .scenario_syntax import digest, roads_from_geojson
                document = scenario_document(store, scenario.entity_id, scenario_override=scenario)[2]
                roads, site = roads_from_geojson(document)
                freshness = 'current' if (parameters.get('road_input_sha256') == digest([r.model_dump() for r in roads])
                    and parameters.get('site_sha256') == digest(site.__geo_interface__)) else 'stale'
            except (ValueError, KeyError, OSError):
                freshness = 'stale'
        projections.append(AnalysisProjection(execution_id=run.entity_id,artifact_ids=artifacts,stage=stage,
            source_scenario_id=source_id,source_revision=source_revision,geometry_sha256=geometry_hash,
            freshness=freshness).model_dump())
    return projections


def with_analysis_statuses(store, scenario, payload, revision):
    """Append status projections to the new scenario payload; old runs are untouched."""
    result = dict(payload)
    result['parameters'] = dict(payload.get('parameters') or {})
    target = SimpleNamespace(entity_id=scenario.entity_id,project_id=scenario.project_id,payload=result,revision=revision)
    for item in analysis_results(store, target):
        prefix = {'E1':'e1','E2':'e2','Syntax':'syntax','Analysis':'analysis'}[item['stage']]
        ids = list(result['parameters'].get(prefix+'_result_ids') or [])
        statuses = dict(result['parameters'].get(prefix+'_statuses') or {})
        for identifier in item['artifact_ids']:
            if identifier not in ids: ids.append(identifier)
            statuses[identifier] = item['freshness'].upper()
        result['parameters'][prefix+'_result_ids'] = ids
        result['parameters'][prefix+'_statuses'] = statuses
    return result
