"""Disposable Week 7 fixtures; synthetic observations are not engine results."""
from __future__ import annotations

import builtins
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from shapely.geometry import box, mapping
from urban_design.geometry import canonical_geometry_hash
from urban_design.models import Artifact, EvidenceCard, Scenario, StudyArea
from urban_design.store import ProjectStateStore
from urban_design.workspace_contracts import WorkspaceRevision
from urban_design.week7.service import Week7Service, AUTHORITY_DATABASE


@pytest.fixture(autouse=True)
def week7_database_guard_scope(request):
    """Plugin registration is session-wide; automatic protection is Week 7 only."""
    if Path(request.module.__file__).name.startswith("test_week7_"):
        request.getfixturevalue("no_canonical_main_database")


@pytest.fixture
def no_canonical_main_database(monkeypatch):
    """Fail before SQLite or file I/O can read the canonical DB or sidecars."""
    canonical = str(AUTHORITY_DATABASE.resolve())
    def check(value):
        if isinstance(value, (str, bytes, Path)):
            text = value.decode() if isinstance(value, bytes) else str(value)
            path = unquote(urlsplit(text).path) if text.startswith('file:') else text
            resolved = str(Path(path).resolve())
            assert resolved not in {canonical, canonical + '-wal', canonical + '-shm'}, 'canonical main DB access forbidden'
    connect, path_open, builtin_open = sqlite3.connect, Path.open, builtins.open
    def guarded_connect(database, *args, **kwargs):
        check(database)
        return connect(database, *args, **kwargs)
    def guarded_path_open(path, *args, **kwargs):
        check(path)
        return path_open(path, *args, **kwargs)
    def guarded_open(file, *args, **kwargs):
        check(file)
        return builtin_open(file, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', guarded_connect)
    monkeypatch.setattr(Path, 'open', guarded_path_open)
    monkeypatch.setattr(builtins, 'open', guarded_open)
    import io
    monkeypatch.setattr(io, 'open', guarded_open)


def create_injected_authority_refusal_fixture(database: Path) -> Path:
    """Seed a synthetic injected authority fixture strictly for verifying write refusal.

    This fixture is distinct from general disposable workspaces: it models an injected
    authority database whose writes must be refused before any modification, and whose
    bytes/hash must remain unchanged. It contains no valid analysis, tool execution,
    or human approval claims.
    """
    database.parent.mkdir(parents=True, exist_ok=True)
    with ProjectStateStore(database) as store:
        store.create_project(
            {
                'name': 'Synthetic Injected Authority Fixture (Refusal Testing Only)',
                'active_study_area_id': 'authority-refusal-study',
                'provenance': 'INJECTED_AUTHORITY_REFUSAL_FIXTURE_ONLY',
            },
            project_id='rotterdam-m4h-pilot-project',
        )
    return database



def seed_project_database(database: Path) -> Path:
    """Seed typed, unapproved scene records without authority copies or tool runs.

    Comparison observations describe the constructed fixture polygons only.
    They remain UNVERIFIED and carry no runtime/acceptance claim.
    """
    # Legacy fixture consumers use this identifier; all state is synthetic and local.
    project = 'rotterdam-m4h-pilot-project'
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    boundary = box(0, 0, 100, 100)
    with ProjectStateStore(database) as store:
        store.create_project({'name': 'Synthetic W7 portability fixture',
            'active_study_area_id': 'fixture-study', 'provenance': 'FIXTURE_ONLY'}, project_id=project)
        def artifact(entity_id, document):
            path = database.parent / (entity_id + '.json')
            raw = json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            path.write_bytes(raw)
            sha = 'sha256:' + hashlib.sha256(raw).hexdigest()
            store.create_typed(Artifact(id=entity_id, project_id=project, type='scenario-geometry',
                uri=str(path), sha256=sha, mime='application/geo+json', crs='EPSG:28992',
                producer='synthetic-test-fixture-no-engine', created_at=now, size_bytes=len(raw)))
            return sha
        study_sha = artifact('fixture-study-geometry', mapping(boundary))
        store.create_typed(StudyArea(id='fixture-study', project_id=project, version='1',
            geometry_artifact_id='fixture-study-geometry', geometry_sha256=canonical_geometry_hash(mapping(boundary)),
            artifact_sha256=study_sha, horizontal_crs='EPSG:28992', units='m'))
        workspace = WorkspaceRevision(workspace_id='fixture-workspace', project_id=project,
            revision=1, study_area_id='fixture-study')
        # WorkspaceRevision uses workspace_id rather than the domain id interface.
        store.create('WorkspaceRevision', workspace.model_dump(mode='json'),
            entity_id=workspace.workspace_id, project_id=project)
        for index in (1, 2):
            scenario_id = f'fixture-scenario-{index}'
            footprint = box(10 * index, 10, 10 * index + 10, 20)
            doc = {'type': 'FeatureCollection', 'features': [{'type': 'Feature',
                'geometry': mapping(footprint), 'properties': {'role': 'new_building',
                'height_m': 3, 'provenance': 'FIXTURE_ONLY'}}]}
            geometry_id = f'fixture-geometry-{index}'
            sha = artifact(geometry_id, doc)
            coverage = footprint.area / boundary.area
            observations = {'far': (coverage, 'ratio'), 'coverage_ratio': (coverage, 'ratio'),
                'height_m': (3, 'm'), 'road_ratio': (0, 'ratio'), 'open_space_ratio': (1 - coverage, 'ratio')}
            metrics = {key: {'value': value, 'unit': unit, 'method': 'fixture-polygon-observation',
                'validation_status': 'UNVERIFIED', 'provenance': 'FIXTURE_ONLY'}
                for key, (value, unit) in observations.items()}
            store.create_typed(Scenario(id=scenario_id, project_id=project, site_id='fixture-study',
                site_version='1', geometry_artifact_id=geometry_id, geometry_sha256=sha,
                generator='synthetic-test-fixture-no-engine', generator_version='fixture-v1',
                constraint_set_id='fixture-unactivated-constraints', parameters={
                    'provenance': 'FIXTURE_ONLY', 'validation': {'valid': footprint.is_valid},
                    'metrics': metrics, 'comparison_basis': {'denominator_hash': study_sha,
                    'rules_version': 'fixture-polygon-observation-v1'} }))
            store.create_typed(EvidenceCard(id=f'fixture-card-{index}', project_id=project,
                scenario_id=scenario_id, claim={'id': f'fixture-claim-{index}', 'type': 'observation',
                    'statement': 'Synthetic scene fixture only; no engine execution', 'scope': 'fixture-study'},
                source_refs=[geometry_id], metric={'id': 'fixture-geometry', 'name': 'Fixture geometry', 'unit': 'm'},
                method={'id': 'fixture-observation', 'description': 'Inspect synthetic input polygon only'},
                tool='test-fixture', tool_version='1', result={'status': 'observed', 'values': {},
                    'artifact_refs': [geometry_id], 'artifact_hashes': [sha]}, units='m',
                limitations=['FIXTURE_ONLY; no runtime or human approval'],
                confidence={'level': 'unknown', 'basis': 'synthetic input', 'uncertainty': 'not engine evidence',
                    'assessed_by': 'test-harness'}, created_at=now))
    return database


@pytest.fixture()
def week7_db(tmp_path: Path) -> Path:
    return seed_project_database(tmp_path / 'state.sqlite3')


@pytest.fixture()
def service(week7_db: Path):
    opened = Week7Service(week7_db)
    try:
        yield opened
    finally:
        opened.close()


def seed_pair(opened: Week7Service, workspace_id: str = "ws-w7") -> None:
    opened.switch_scheme(
        workspace_id,
        project_id="rotterdam-m4h-pilot-project",
        scenario_id="B1",
        revision="rev-b1",
        results=[{"kind": "gfa_far", "value": 1.1, "unit": "ratio", "provenance": "FIXTURE_ONLY"}],
        cards=[
            {
                "evidence_id": "card-b1-sun",
                "source": "fixture sun B1",
                "formula": "stored",
                "unit": "hour",
                "version": "rev-b1",
                "limits": "FIXTURE_ONLY",
                "period": "2026-06-21",
                "radius_family": "accessibility",
                "radius_m": 800.0,
                "numbers": [1.1],
                "provenance": "FIXTURE_ONLY",
            }
        ],
    )
    opened.switch_scheme(
        workspace_id,
        project_id="rotterdam-m4h-pilot-project",
        scenario_id="B2",
        revision="rev-b2",
        results=[{"kind": "gfa_far", "value": 2.2, "unit": "ratio", "provenance": "FIXTURE_ONLY"}],
        cards=[
            {
                "evidence_id": "card-b2-sun",
                "source": "fixture sun B2",
                "formula": "stored",
                "unit": "hour",
                "version": "rev-b2",
                "limits": "FIXTURE_ONLY",
                "period": "2026-06-21",
                "radius_family": "accessibility",
                "radius_m": 800.0,
                "numbers": [2.2],
                "provenance": "FIXTURE_ONLY",
                "validation_status": "invalid",
            }
        ],
    )
