"""Served-store integration of approved dictionary jobs and read-only proposals."""
import hashlib
import json
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Literal
from urban_design.approved_generation import _load_approved_inputs, ApprovedGenerationBlocked
from urban_design.generation_context import resolve_readiness, freeze_context, FreezeRequest
from .formal_adapter import adapt_frozen_context, retained_gfa_bounds
from .formal_pipeline import run_formal_pipeline, skeleton_inputs, VERSION
from .formal_persistence import persist_results
from .hashing import generation_context_digest
from .job_store import GenerationJobStore
from .job_runner import GenerationJobRunner, PreparedOutput, write_prepared_manifest
from .workflow import GenerationWorkflow, ResolvedGeneration, PublicationReceipt

class FormalMetrics(BaseModel):
    model_config = ConfigDict(extra="allow")
    far: float
    far_denominator: str
    far_denominator_m2: float
    coverage: float
    highest_new_height_m: float
    open_space_ratio: float
    zone_uses: list[dict]


class FormalProposal(BaseModel):
    generator_version: str
    revision: int = 1
    id: str
    strategy: str
    status: Literal["PROPOSED", "ACCEPTED", "REJECTED"]
    metrics: FormalMetrics
    geometry_artifact_id: str
    geometry_path: str
    geometry: dict
    rejection_reason: str | None = None
    baseline_reason: str | None = None
    geometry_sha256: str | None = None


def install_formal_service(app, store, root):
    root = Path(root) / 'generation'
    jobs = GenerationJobStore(root / 'jobs.sqlite3')
    runner = GenerationJobRunner(jobs, staging_root=root/'staging', output_root=root/'jobs')

    def frozen(project_id):
        ready = resolve_readiness(store, project_id)
        if ready.status != 'READY':
            return ready
        return freeze_context(store, project_id, FreezeRequest(expected_workspace_revision=ready.context.workspace_revision, expected_context_hash=ready.context_hash))

    resolved_cache: dict[tuple[str, int, str], ResolvedGeneration] = {}

    def resolve(project_id, *, use_cache: bool = True):
        try:
            if not use_cache:
                ready = frozen(project_id)
            else:
                try:
                    ready = resolve_readiness(store, project_id, use_cache=True)
                except TypeError:
                    ready = resolve_readiness(store, project_id)
            if ready.status != 'READY' or retained_gfa_bounds(ready.context)['status'] == 'UNAVAILABLE':
                return None
            cache_key = (project_id, ready.context.workspace_revision, ready.context_hash)
            if use_cache:
                cached = resolved_cache.get(cache_key)
                if cached is not None:
                    return cached
            context = adapt_frozen_context(ready, seed=42)
            inputs = _load_approved_inputs(store, project_id, site_generation=True)
            res = ResolvedGeneration(context, skeleton_inputs(inputs, context), (), str(ready.context.workspace_revision), 'APPROVED')
            if use_cache:
                resolved_cache[cache_key] = res
            return res
        except (ApprovedGenerationBlocked, ValueError):
            return None

    def run(job, staging, token):
        ready = frozen(job.project_id)
        context = adapt_frozen_context(ready, seed=42)
        if generation_context_digest(context) != job.request['context_hash']:
            raise ValueError('BLOCKED: frozen context changed')
        inputs = _load_approved_inputs(store, job.project_id, site_generation=True)
        result = run_formal_pipeline(context, ready.context, inputs)
        report = dict(result, project_id=job.project_id, seed=context.seed,
                      frozen_context=ready.model_dump(mode='json'), typed_context_hash=generation_context_digest(context),
                      scenario_ids=[], database_access='READ_ONLY')
        if token.cancelled:
            raise ValueError('cancelled before publication')
        # Stable authority artifact location is separate from renamed job staging.
        directory = root / 'formal' / generation_context_digest(context).removeprefix('sha256:')
        directory.mkdir(parents=True, exist_ok=True)
        with store.locked_connection():
            persist_results(report, store.database, directory, dry_run=False, store=store)
        data = json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        (staging/'formal-results.json').write_bytes(data)
        if not report['scenario_ids']:
            raise ValueError('BLOCKED: formal quality gate failed')
        # Manifest paths must be unique; one report carries all Scenario identities.
        outputs = [PreparedOutput('formal-results-'+job.job_id, 'formal-results.json', 'sha256:'+hashlib.sha256(data).hexdigest(), len(data))]
        return write_prepared_manifest(staging, handler_version=VERSION, input_refs=job.input_refs, output_refs=outputs)

    runner.register_handler('MASSING', VERSION, run)
    def publication(job_id):
        job = jobs.get(job_id)
        path = root/'jobs'/job_id/'formal-results.json'
        if not path.is_file() or not runner.verify_published(job_id):
            return None
        report = json.loads(path.read_bytes())
        records = []
        for scenario_id in report['scenario_ids']:
            record = store.get_record(scenario_id)
            artifact = store.get_record(record.payload['geometry_artifact_id'])
            raw = Path(artifact.payload['uri']).read_bytes()
            if 'sha256:'+hashlib.sha256(raw).hexdigest() != artifact.payload['sha256']:
                return None
            records.append(dict(id=record.entity_id, revision=record.revision, payload=record.payload))
        if not records:
            return None
        digest = hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',', ':')).encode()).hexdigest()
        return PublicationReceipt(job_id=job_id, manifest_sha256=job.output_manifest_sha256,
            authority_revision=str(report['frozen_context']['context']['workspace_revision']),
            authority_record_sha256='sha256:'+digest)

    workflow = GenerationWorkflow(jobs, runner, resolve, publication_lookup=publication, full_scheme_only=True)
    from .router import create_generation_workflow_router
    app.include_router(create_generation_workflow_router(workflow))
    app.state.generation_workflow = workflow
    from urban_design.route_aliases import with_legacy_prefix

    router = APIRouter(tags=['formal-proposals'])

    @router.get('', response_model=list[FormalProposal])
    def proposals(project_id: str):
        rows = []
        for record in store.list_current('Scenario', project_id=project_id):
            p = record.payload
            status_raw = str(p.get('status', 'proposed')).upper()
            if status_raw not in ('PROPOSED', 'ACCEPTED', 'REJECTED') or p.get('generator') != VERSION:
                continue
            artifact = store.get_record(p['geometry_artifact_id']).payload
            path = Path(artifact['uri'])
            try:
                raw = path.read_bytes()
            except OSError as error:
                raise HTTPException(409, 'FORMAL_GEOMETRY_UNAVAILABLE') from error
            if artifact['project_id'] != project_id or artifact['sha256'] != p['geometry_sha256'] or 'sha256:'+hashlib.sha256(raw).hexdigest() != artifact['sha256']:
                raise HTTPException(409, 'FORMAL_GEOMETRY_INTEGRITY_FAILED')
            geometry = json.loads(raw)
            if not any(f.get('properties', {}).get('role') == 'site_area' for f in geometry['features']):
                from urban_design.scenario_syntax_api import scenario_document
                geometry = scenario_document(store, record.entity_id)[2]
            estimates = {r['building_id']:r for r in p['parameters'].get('floor_estimates', [])}
            for feature in geometry['features']:
                properties = feature['properties']
                estimate = estimates.get(properties.get('building_id'))
                if properties.get('role') == 'retained' and estimate:
                    properties['height_estimate'] = estimate
                    if estimate.get('height_above_ground_m') is not None:
                        properties['height_m'] = estimate['height_above_ground_m']
            identity = re.fullmatch(r'formal-dict-[0-9a-f]{12}-(.+)-[0-9a-f]{12}', record.entity_id)
            strategy = p['parameters'].get('recipe_id') or (identity.group(1) if identity else p['morphology_family'])
            rows.append(FormalProposal(generator_version=p['generator'], revision=record.revision, id=record.entity_id, strategy=strategy, status=status_raw,
                metrics=p['parameters']['metrics'], geometry_artifact_id=artifact['id'], geometry_path=str(path), geometry=geometry,
                rejection_reason=p.get('rejection_reason'), baseline_reason=p.get('baseline_reason'),
                geometry_sha256=p.get('geometry_sha256')))
        return rows
    app.include_router(with_legacy_prefix(
        router,
        canonical='/api/v1/projects/{project_id}/formal-proposals',
        legacy='/api/projects/{project_id}/formal-proposals',
    ))
    from urban_design.scenario_comparison_router import create_scenario_comparison_router
    key_path = getattr(getattr(app, "state", None), "decision_key_path", None)
    limiter = getattr(getattr(app, "state", None), "decision_attempt_limiter", None)
    if not any(getattr(r, "path", None) == "/api/v1/scenarios/comparison" for r in getattr(app, "routes", [])):
        app.include_router(create_scenario_comparison_router(store, decision_key_path=key_path, decision_attempt_limiter=limiter))

