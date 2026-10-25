"""Durable local S5 jobs and immutable scenario comparison artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator
from shapely.geometry import shape

from .scenario_syntax import (EXTRACTION_ROOT, MergeParameters, Mode, assumed_road_properties,
                              compare_syntax, digest, roads_from_geojson, verified_extract)
from .store import EntityNotFoundError, ProjectStateStore
from .syntax_engines.pst_adapter import PSTExecutionError


class SyntaxJobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Mode = 'pedestrian'
    parameters: MergeParameters = MergeParameters()



class SyntaxSegmentResponse(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str
    coordinates: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=2)
    nain: FiniteFloat
    nach: FiniteFloat
    inside_site: bool
    entrance: bool
    distance_to_site_m: FiniteFloat
    boundary_effect_risk: bool


class SyntaxMetricsResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    inside_segment_count: int = Field(ge=0)
    mean_integration_nain: FiniteFloat | None
    high_segment_ratio: FiniteFloat | None = Field(ge=0, le=1)
    entrance_integration_nain: FiniteFloat | None
    through_site_choice_nach: FiniteFloat | None
    through_site_choice_method: str
    weighting: str
    high_threshold_nain: FiniteFloat
    high_definition: str


class SyntaxSideResponse(BaseModel):
    segments: list[SyntaxSegmentResponse]
    metrics: SyntaxMetricsResponse


class SyntaxValueResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nain: FiniteFloat
    nach: FiniteFloat


class SyntaxDiffResponse(SyntaxSegmentResponse):
    before: SyntaxValueResponse | None
    after: SyntaxValueResponse | None
    delta: SyntaxValueResponse | None
    comparison_status: str

    @model_validator(mode='after')
    def no_missing_as_zero(self):
        if (self.before is None or self.after is None) and self.delta is not None:
            raise ValueError('unmatched geometry must not have a numeric delta')
        return self


class ScenarioSyntaxResponse(BaseModel):
    # Provenance and merge diagnostics remain available, while measurement fields
    # are finite and typed at the API/persistence boundary.
    model_config = ConfigDict(extra='allow')
    status: str
    mode: Mode | None = None
    before: SyntaxSideResponse | None = None
    after: SyntaxSideResponse | None = None
    diff: list[SyntaxDiffResponse] = Field(default_factory=list)

    @model_validator(mode='after')
    def computed_requires_sides(self):
        if self.status == 'COMPUTED' and (self.before is None or self.after is None):
            raise ValueError('COMPUTED requires comparable before and after results')
        return self


class SyntaxJobAck(BaseModel):
    job_id: str
    status: str
    mode: Mode

def utc_now():
    return subprocess.check_output(['date', '-u', '+%Y-%m-%dT%H:%M:%SZ'], text=True).strip()


def scenario_document(store, scenario_id, *, scenario_override=None):
    scenario = scenario_override if scenario_override is not None else store.current(scenario_id)
    if getattr(scenario, 'entity_type', 'DesignScenario') != 'DesignScenario':
        raise ValueError('not a DesignScenario')
    artifact = store.current(scenario.payload['geometry_artifact_id'])
    if artifact.entity_type != 'Artifact' or artifact.project_id != scenario.project_id:
        raise ValueError('scenario artifact identity mismatch')
    raw = Path(artifact.payload['uri']).read_bytes()
    actual = 'sha256:' + hashlib.sha256(raw).hexdigest()
    if actual.removeprefix('sha256:') != artifact.payload['sha256'].removeprefix('sha256:') or actual.removeprefix('sha256:') != scenario.payload['geometry_sha256'].removeprefix('sha256:'):
        raise ValueError('scenario geometry hash mismatch')
    document = json.loads(raw)
    # Older immutable candidates omit site_area: resolve their declared StudyArea,
    # hash-check its artifact and attach only an in-memory analysis boundary.
    if not any(f.get('properties', {}).get('role') == 'site_area' for f in document['features']):
        study = store.current(scenario.payload['site_id'])
        if study.entity_type != 'StudyArea' or study.project_id != scenario.project_id or study.payload.get('horizontal_crs') != 'EPSG:28992':
            raise ValueError('legacy scenario StudyArea binding is invalid')
        area_artifact = store.current(study.payload['geometry_artifact_id'])
        area_raw = Path(area_artifact.payload['uri']).read_bytes()
        area_hash = 'sha256:' + hashlib.sha256(area_raw).hexdigest()
        if area_hash != area_artifact.payload['sha256'] or area_hash != study.payload['artifact_sha256']:
            raise ValueError('legacy StudyArea artifact hash mismatch')
        area_doc = json.loads(area_raw)
        document['features'].append({'type':'Feature', 'geometry':area_doc.get('geometry',area_doc),
            'properties':{'role':'site_area', 'boundary_source':'DECLARED_STUDY_AREA', 'artifact_sha256':area_hash}})
    # Legacy role-only geometry is not mutated on disk. Semantic fallback stays labelled.
    return scenario, artifact, document


def persist_comparison(store, scenario, artifact, bundle, job_id, output_root):
    bundle = ScenarioSyntaxResponse.model_validate(bundle).model_dump(exclude_unset=True)
    raw = json.dumps(bundle, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    root = Path(output_root); root.mkdir(parents=True, exist_ok=True)
    path = root / (job_id + '.json')
    with path.open('xb') as target:
        target.write(raw)
    artifact_id = 'artifact-' + job_id
    record = store.create(entity_type='Artifact', entity_id=artifact_id, project_id=scenario.project_id,
        payload={'id': artifact_id, 'type': 'scenario-syntax-result', 'uri': str(path.resolve()),
                 'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw), 'mime': 'application/json',
                 'producer': 'PST 3.3.1', 'created_at': utc_now(), 'project_id': scenario.project_id,
                 'parent_artifact_ids': [artifact.entity_id], 'bundle': bundle},
        actor='j10-syntax', action='CreateScenarioSyntaxArtifact')
    return record


def create_scenario_syntax_router(store: ProjectStateStore, output_root, *, extraction_root=EXTRACTION_ROOT, adapter_factory=None):
    router = APIRouter(tags=['scenario-syntax'])
    active_jobs: set[str] = set()

    def current_inputs(scenario_id):
        try:
            scenario, artifact, document = scenario_document(store, scenario_id)
            roads, site = roads_from_geojson(document)
            return scenario, artifact, roads, site
        except EntityNotFoundError as exc:
            raise HTTPException(404, 'scenario or geometry artifact not found') from exc
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(409, 'BLOCKED: '+str(exc)) from exc

    def run(job_id, scenario_id, request, frozen_hash, frozen_site_hash):
        job = store.current(job_id)
        store.update(job_id, {**job.payload, 'status': 'running'}, expected_revision=job.revision,
                     actor='j10-syntax', action='StartScenarioSyntaxJob')
        phase = 'inputs'
        try:
            scenario, artifact, roads, site = current_inputs(scenario_id)
            if digest([r.model_dump() for r in roads]) != frozen_hash or digest(site.__geo_interface__) != frozen_site_hash:
                raise ValueError('STALE: scenario changed before dispatch')
            docs, source = verified_extract(request.mode, extraction_root)
            study_raw = docs['study_area']
            study = shape(study_raw.get('geometry', study_raw))
            # A new site requires its own approved extraction, not this case's context.
            if not study.buffer(1e-6).covers(site):
                raise ValueError('BLOCKED: scenario site lies outside extraction StudyArea')
            phase = 'compute'
            bundle = compare_syntax(docs['network']['features'], roads, site, request.mode,
                adapter=adapter_factory() if adapter_factory else None, parameters=request.parameters,
                unlinks=tuple(tuple(p) for p in docs['unlinks']))
            bundle.update(scenario_id=scenario_id, scenario_revision=scenario.revision, sources=source,
                          created_at_utc=utc_now(), scenario_geometry_sha256=artifact.payload['sha256'])
            phase = 'persist'
            result = persist_comparison(store, scenario, artifact, bundle, job_id, output_root)
            job = store.current(job_id)
            store.update(job_id, {**job.payload, 'status': 'succeeded' if bundle['status']=='COMPUTED' else 'failed',
                'result_status': bundle['status'], 'output_artifact_refs': [result.entity_id],
                'output_artifact_hashes': [result.payload['sha256']]}, expected_revision=job.revision,
                actor='j10-syntax', action='FinishScenarioSyntaxJob')
        except Exception as exc:
            job = store.current(job_id)
            store.update(job_id, {**job.payload, 'status': 'OUTCOME_UNKNOWN' if isinstance(exc, PSTExecutionError) or phase == 'persist' else 'failed', 'error': str(exc)}, expected_revision=job.revision,
                         actor='j10-syntax', action='FailScenarioSyntaxJob')
        finally:
            active_jobs.discard(job_id)

    @router.post('/api/v1/scenarios/{scenario_id}/syntax', status_code=202, response_model=SyntaxJobAck)
    def submit(scenario_id: str, request: SyntaxJobRequest, background: BackgroundTasks):
        scenario, artifact, roads, site = current_inputs(scenario_id)
        job_id = 'syntax-job-' + str(uuid.uuid4())
        road_hash = digest([r.model_dump() for r in roads]); site_hash = digest(site.__geo_interface__)
        store.create(entity_type='ToolExecution', entity_id=job_id, project_id=scenario.project_id,
            payload={'id': job_id, 'project_id': scenario.project_id, 'scenario_id': scenario_id, 'tool': 'scenario-space-syntax', 'tool_version': '3.3.1',
                     'status': 'pending', 'created_at': utc_now(), 'input_refs': [scenario_id],
                     'input_artifact_hashes_by_id': {artifact.entity_id: artifact.payload['sha256']},
                     'parameters': {'scenario_id': scenario_id, 'scenario_revision': scenario.revision,
                         'mode': request.mode, 'engine': 'PST 3.3.1', 'road_input_sha256': road_hash, 'site_sha256': site_hash,
                         'merge': request.parameters.model_dump()}, 'output_artifact_refs': []},
            actor='j10-syntax', action='CreateScenarioSyntaxJob')
        active_jobs.add(job_id)
        background.add_task(run, job_id, scenario_id, request, road_hash, site_hash)
        return {'job_id': job_id, 'status': 'pending', 'mode': request.mode}

    @router.get('/api/v1/scenarios/{scenario_id}/syntax', response_model=ScenarioSyntaxResponse, response_model_exclude_unset=True)
    def get_result(scenario_id: str, mode: Mode = 'pedestrian', job_id: str | None = None):
        scenario, _, roads, site = current_inputs(scenario_id)
        jobs = [r for r in store.list_current('ToolExecution', project_id=scenario.project_id)
                if r.payload.get('parameters', {}).get('scenario_id') == scenario_id
                and r.payload.get('parameters', {}).get('mode') == mode
                and (job_id is None or r.entity_id == job_id)]
        if not jobs:
            return {'status': 'NOT_COMPUTED', 'mode': mode, 'before': None, 'after': None, 'diff': []}
        sequences = {event.target_id: event.sequence for event in store.events(scenario.project_id) if event.action == 'CreateScenarioSyntaxJob'}
        job = max(jobs, key=lambda r: sequences.get(r.entity_id, 0))
        if job.payload['status'] in ('pending','running') and job.entity_id not in active_jobs:
            return {'job_id': job.entity_id, 'status':'OUTCOME_UNKNOWN', 'error':'Worker ownership lost; reconcile immutable artifacts before another dispatch.'}
        if not job.payload.get('output_artifact_refs'):
            return {'job_id': job.entity_id, 'status': job.payload['status'], 'error': job.payload.get('error')}
        for identifier, expected in job.payload.get('input_artifact_hashes_by_id', {}).items():
            source_artifact = store.current(identifier)
            source_raw = Path(source_artifact.payload['uri']).read_bytes()
            if source_artifact.payload.get('sha256') != expected or 'sha256:'+hashlib.sha256(source_raw).hexdigest() != expected:
                raise HTTPException(409, 'BLOCKED: immutable scenario input artifact changed')
        artifact = store.current(job.payload['output_artifact_refs'][0])
        raw = Path(artifact.payload['uri']).read_bytes()
        if 'sha256:' + hashlib.sha256(raw).hexdigest() != artifact.payload['sha256']:
            raise HTTPException(409, 'BLOCKED: syntax result artifact hash mismatch')
        bundle = json.loads(raw)
        try:
            _, current_source = verified_extract(mode, extraction_root)
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(409, 'BLOCKED: input provenance no longer verifies: '+str(exc)) from exc
        if current_source['manifest_sha256'] != bundle['sources']['manifest_sha256'] or current_source['pst_runtime_manifest_sha256'] != bundle['sources']['pst_runtime_manifest_sha256']:
            return {**bundle, 'job_id':job.entity_id, 'status':'STALE', 'before':None, 'after':None, 'diff':[], 'stale_reason':'Extraction or engine manifest changed'}
        if bundle['road_input_sha256'] != digest([r.model_dump() for r in roads]) or bundle['site_sha256'] != digest(site.__geo_interface__):
            return {**bundle, 'job_id': job.entity_id, 'status': 'STALE', 'before': None, 'after': None, 'diff': [],
                    'stale_reason': 'scenario road modes, geometry, origins, or boundary changed'}
        return {**bundle, 'job_id': job.entity_id}

    return router
