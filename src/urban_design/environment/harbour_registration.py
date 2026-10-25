"""Pinned NET2 harbour fabric -> existing formal geometry contract, registered as a proposal awaiting the human decision (same status generators use).

This adapter validates environmental geometry, not planning compliance. The
formal-dictionary prefix identifies the existing geometry wire format required
by E2; it does not claim a new dictionary generation or constraint PASS.
No key access and no HumanDecision creation occur here.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import math
from pathlib import Path
import json

from shapely.geometry import shape, Polygon, MultiPolygon

from urban_design.models import ActorKind, Artifact, Scenario, ScenarioStatus
from urban_design.store import EntityNotFoundError
from .e2_service import ScenarioPin, scenario_geometry
from .geometry_adapter import formal_scenario_geojson_to_environment
from .weather_snapshot import E2Blocked, canonical_bytes, checked_artifact, sha256

VERSION = 'formal-dictionary-fabric-geometry-adapter-v1'
HARBOUR_PLAN = Path(__file__).resolve().parents[3] / 'artifacts/fab1/run-8/harbour_grain-plan.json'
HARBOUR_SHA256 = 'sha256:88445febe1b657019b9e52d024de978bd628672e244423d1b07480ebfede06dd'
PROJECT = 'rotterdam-m4h-pilot-project'


def fabric_plan_geometry(plan: dict) -> dict:
    """Preserve supplied footprint/height bytes semantically; never estimate height."""
    if (not isinstance(plan, dict) or plan.get('schema_version') != 'fab1-plan-v1'
            or plan.get('crs') != 'EPSG:28992' or plan.get('fabric_id') != 'fabric.harbour_grain'):
        raise E2Blocked('FABRIC_SCHEMA_OR_CRS_INVALID')
    if not isinstance(plan.get('buildings'), list) or not plan['buildings']:
        raise E2Blocked('FABRIC_BUILDINGS_REQUIRED')
    features = []
    for key, role in [('site', 'site_area'), ('water', 'water')]:
        document = plan.get(key)
        if not isinstance(document, dict):
            raise E2Blocked('FABRIC_DOMAIN_REQUIRED:' + key)
        domain = shape(document)
        if domain.is_empty or not domain.is_valid or not isinstance(domain, (Polygon, MultiPolygon)) or domain.has_z:
            raise E2Blocked('FABRIC_DOMAIN_INVALID:' + key)
        features.append(dict(type='Feature', id=key, geometry=copy.deepcopy(document), properties={'role':role}))
    site = shape(plan['site'])
    identifiers = set()
    for row in plan['buildings']:
        if not isinstance(row, dict) or row.get('type') != 'Feature':
            raise E2Blocked('FABRIC_BUILDING_FEATURE_INVALID')
        identifier, properties = row.get('id'), row.get('properties')
        if not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers or not isinstance(properties, dict):
            raise E2Blocked('FABRIC_BUILDING_ID_OR_PROPERTIES_INVALID')
        identifiers.add(identifier)
        height = properties.get('height_m')
        source = properties.get('source_record') or {}
        excluded_retained = properties.get('retained') is True and (
            str(source.get('bag_status', '')).casefold() in {'pand gesloopt', 'gesloopt', 'demolished'}
            or (source.get('floor_count_lower') == 0 and source.get('floor_count_upper') == 0))
        if not excluded_retained and (isinstance(height, bool) or not isinstance(height, (float, int)) or not math.isfinite(height) or height <= 0):
            raise E2Blocked('FABRIC_EXPLICIT_POSITIVE_HEIGHT_REQUIRED:' + identifier)
        if type(properties.get('retained')) is not bool or not isinstance(row.get('geometry'), dict):
            raise E2Blocked('FABRIC_BUILDING_ROLE_OR_GEOMETRY_INVALID:' + identifier)
        footprint = shape(row['geometry'])
        if (not isinstance(footprint, (Polygon, MultiPolygon)) or not footprint.is_valid
                or footprint.is_empty or footprint.has_z or footprint.difference(site).area > 1e-6):
            raise E2Blocked('FABRIC_BUILDING_FOOTPRINT_INVALID:' + identifier)
        feature = copy.deepcopy(row)
        feature['properties']['role'] = 'retained' if properties['retained'] else 'new_building'
        source = properties.get('source_record') or {}
        if properties['retained']:
            # Preserve demolition/zero-floor evidence for the existing adapter.
            feature['properties']['height_estimate'] = {
                'bag_observed_status': source.get('bag_status'),
                'floor_count': {'lower':source.get('floor_count_lower'), 'upper':source.get('floor_count_upper')}}
        features.append(feature)
    result = dict(type='FeatureCollection', crs={'type':'name','properties':{'name':'EPSG:28992'}}, features=features)
    formal_scenario_geojson_to_environment(result)
    return result


def scenario_pin(store, scenario_id: str, project_id: str) -> ScenarioPin:
    record = store.current(scenario_id)
    p = record.payload
    if record.entity_type != 'DesignScenario' or record.project_id != project_id:
        raise E2Blocked('SCENARIO_PROJECT_OR_TYPE_INVALID')
    pin = ScenarioPin(scenario_id=record.entity_id, revision=record.revision,
                      geometry_artifact_id=p['geometry_artifact_id'], geometry_sha256=p['geometry_sha256'],
                      environment_sha256='sha256:'+'0'*64)
    _, metadata = scenario_geometry(store, pin, project_id)
    return pin.model_copy(update={'environment_sha256':metadata['environment_sha256']})


def register_harbour(store, project_id: str, root: Path) -> dict:
    if project_id != PROJECT:
        raise E2Blocked('HARBOUR_PROJECT_INVALID')
    raw = HARBOUR_PLAN.read_bytes()
    if sha256(raw) != HARBOUR_SHA256:
        raise E2Blocked('HARBOUR_SOURCE_HASH_MISMATCH')
    plan = json.loads(raw)
    geometry = fabric_plan_geometry(plan)
    # A pinned import cannot activate a new boundary, water source, or constraints.
    from urban_design.approved_generation import _load_approved_inputs, ApprovedGenerationBlocked
    try:
        inputs = _load_approved_inputs(store, project_id, site_generation=True)
    except ApprovedGenerationBlocked as exc:
        raise E2Blocked('HARBOUR_APPROVED_INPUTS_UNAVAILABLE') from exc
    if (shape(plan['site']).symmetric_difference(inputs.design_area).area > 1e-6
            or inputs.water_geometry is None
            or shape(plan['water']).symmetric_difference(inputs.water_geometry).area > 1e-6):
        raise E2Blocked('HARBOUR_APPROVED_DOMAIN_MISMATCH')
    geometry_raw = canonical_bytes(geometry)
    digest = sha256(geometry_raw)
    source_id = 'artifact-e2-harbour-source-' + HARBOUR_SHA256[7:31]
    artifact_id = 'artifact-e2-harbour-geometry-' + digest[7:31]
    identifier = 'formal-fabric-harbour-grain-' + HARBOUR_SHA256[7:19]
    scenario = Scenario(id=identifier, project_id=project_id, site_id=inputs.study_area.entity_id,
        site_version=str(inputs.study_area.payload.get('version', inputs.study_area.revision)),
        geometry_artifact_id=artifact_id, geometry_sha256=digest,
        generator=VERSION, generator_version=VERSION, constraint_set_id=inputs.constraint_set.id,
        morphology_family='harbour_grain', status=ScenarioStatus.PROPOSED,
        parameters={'source_artifact_id':source_id, 'source_sha256':HARBOUR_SHA256,
            'source_path':'artifacts/fab1/run-8/harbour_grain-plan.json', 'net2_round':plan['net2']['round'],
            'provenance':'FABRIC_PLAN_E2_ONLY', 'approved_input_hash':inputs.input_hash,
            'source_validation':plan['validation'], 'source_limitations':plan.get('limitations', []),
            'validation':{'valid':True, 'scope':'ENVIRONMENT_GEOMETRY_ONLY', 'failure_reasons':[],
                          'planning_compliance_passed':False},
            'vertical_reference':'LOCAL_GROUND_Z0_RELATIVE_HEIGHT_M; not NAP elevation',
            'public_space_definition':'site minus water and all building footprints; not verified legal public access'})
    try:
        existing = store.current(identifier)
    except EntityNotFoundError:
        existing = None
    if existing is not None:
        # Acceptance changes status/revision; registration must never reset it.
        immutable = scenario.model_dump(mode='json')
        for key, value in immutable.items():
            if key not in {'status', 'rejection_reason'} and existing.payload.get(key) != value:
                raise E2Blocked('HARBOUR_SCENARIO_COLLISION')
        if existing.entity_type != 'DesignScenario' or existing.project_id != project_id:
            raise E2Blocked('HARBOUR_SCENARIO_COLLISION')
        checked_artifact(store, source_id, project_id)
        checked_artifact(store, artifact_id, project_id)
    else:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        entities = []
        for aid, data, kind, mime, crs, parents in [
            (source_id, raw, 'fabric-plan-source', 'application/json', 'EPSG:28992',
             [r.entity_id for r in inputs.source_artifacts]),
            (artifact_id, geometry_raw, 'scenario-geometry', 'application/geo+json', 'EPSG:28992', [source_id])]:
            path = root / (aid+'.json')
            if path.exists():
                if path.read_bytes() != data:
                    raise E2Blocked('HARBOUR_IMMUTABLE_BYTES_COLLISION')
            else:
                with path.open('xb') as target: target.write(data)
            artifact = Artifact(id=aid, project_id=project_id, type=kind, uri=str(path.resolve()),
                sha256=sha256(data), mime=mime, crs=crs, producer=VERSION,
                created_at=datetime.now(timezone.utc), size_bytes=len(data), parent_artifact_ids=parents)
            entities.append({'entity_id':aid, 'entity_type':'Artifact', 'payload':artifact.model_dump(mode='json'),
                             'project_id':project_id, 'actor':VERSION, 'actor_kind':ActorKind.AGENT_AUTOMATION,
                             'event_id':'event-'+aid})
        entities.append({'entity_id':identifier, 'entity_type':'DesignScenario', 'payload':scenario.model_dump(mode='json'),
                         'project_id':project_id, 'actor':VERSION, 'actor_kind':ActorKind.AGENT_AUTOMATION,
                         'event_id':'event-'+identifier})
        store.commit_batch(entities=entities, events=[])
    pin = scenario_pin(store, identifier, project_id)
    return {**pin.model_dump(mode='json'), 'status':store.current(identifier).payload['status'], 'source_sha256':HARBOUR_SHA256,
            'source_validation':plan['validation']}
