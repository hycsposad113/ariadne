"""Shared Step A proposal publication; never creates human decisions."""
from pathlib import Path
from datetime import datetime, timezone
import json
from urban_design.store import ProjectStateStore
from urban_design.generation_context import resolve_readiness
from .formal_pipeline import VERSION

def persist_results(report, database, output, *, dry_run, store=None):
    import hashlib
    from urban_design.models import Artifact, Scenario
    from urban_design.store import ActorKind
    from urban_design.generation_context import context_digest
    for row in report['candidates']:
        for suffix, document in [('geojson', row['geometry']), ('stages.json', row['stages'])]:
            path=output/(row['recipe_id']+'.'+suffix)
            data = json.dumps(document,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False)+'\n'
            if path.exists():
                if suffix == 'geojson' and path.read_text() != data:
                    raise ValueError('OUTCOME_UNKNOWN: immutable geometry path has different bytes')
            else:
                with path.open('x') as target:
                    target.write(data)
        row['geometry_path']=str((output/(row['recipe_id']+'.geojson')).resolve())
    if dry_run or not report['candidates']:
        return
    from contextlib import nullcontext
    with (nullcontext(store) if store is not None else ProjectStateStore(database)) as store:
        current=resolve_readiness(store,report['project_id'])
        if current.context_hash != report['frozen_context']['context_hash'] or current.status != 'READY':
            raise ValueError('BLOCKED: authority drift before persistence')
        for row in report['candidates']:
            path=Path(row['geometry_path']); raw=path.read_bytes()
            digest='sha256:'+hashlib.sha256(raw).hexdigest()
            id='formal-dict-'+report['typed_context_hash'].removeprefix('sha256:')[:12]+'-'+row['recipe_id']+'-'+row['result_hash'].removeprefix('sha256:')[:12]
            artifact=Artifact(id='artifact-'+id,type='scenario-geometry',uri=str(path),sha256=digest,mime='application/geo+json',crs='EPSG:28992',
                producer=VERSION,created_at=datetime.now(timezone.utc),project_id=report['project_id'],size_bytes=len(raw),
                parent_artifact_ids=[r['id'] for r in current.context.refs if r.get('entity_type')=='Artifact'])
            existing_artifacts=[r for r in store.list_current('Artifact',project_id=report['project_id']) if r.entity_id==artifact.id]
            if existing_artifacts and existing_artifacts[0].payload['sha256'] != digest:
                raise ValueError('OUTCOME_UNKNOWN: existing generated artifact identity has different bytes')
            if not existing_artifacts:
                store.create_typed(artifact,actor='AGENT_AUTOMATION',actor_kind=ActorKind.AGENT_AUTOMATION,reason='Preserve formal dictionary candidate geometry including failures')
            # Failures retain Artifact/report, never masquerade as valid PROPOSED.
            if row['status'] != 'VALID' or report['status'] != 'READY': continue
            scenario=Scenario(id=id,project_id=report['project_id'],site_id=next(r['id'] for r in current.context.refs if r.get('entity_type')=='StudyArea'),
                site_version='v5',morphology_family=row['family'],geometry_artifact_id=artifact.id,geometry_sha256=digest,generator=VERSION,generator_version=VERSION,
                seed=report['seed'],constraint_set_id=next(r['id'] for r in current.context.refs if r.get('entity_type')=='ConstraintSet'),
                parameters=dict(context_hash=current.context_hash,typed_context_hash=report['typed_context_hash'],constraint_set_digest=next(r['payload_hash'] for r in current.context.refs if r.get('entity_type')=='ConstraintSet'),
                    recipe_id=row['recipe_id'],recipe_version=VERSION,result_hash=row['result_hash'],recipe=row.get('recipe'),metrics=row['metrics'],floor_estimates=list(current.context.floor_estimates),
                    commander_assumptions=report['commander_assumptions'],validation={'valid':True,'failure_reasons':[]},provenance='APPROVED_INPUTS'))
            if not any(r.entity_id==id for r in store.list_current('Scenario',project_id=report['project_id'])):
                store.create_typed(scenario,actor='AGENT_AUTOMATION',actor_kind=ActorKind.AGENT_AUTOMATION,reason='PD-04 deterministic generator output; proposal only')
            row['scenario_id']=id
            report['scenario_ids'].append(id)
    report['database_access']='APPEND_ONLY_PROPOSED_AND_ARTIFACT'

