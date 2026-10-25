"""Retained delivery regression: fresh PST lineage and selected plan identity."""
import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design import scenario_syntax
from urban_design.fabric_syntax_segments import load_verified, verify
from urban_design.fabric_plans_api import FABRICS, create_fabric_plans_router, verify_selected_plan_receipt

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / 'artifacts/net2/round-7'



def _repo_relative(path) -> str:
    # Receipts keep the producing checkout's absolute path; compare the repository-relative part.
    parts = Path(path).parts
    return '/'.join(parts[parts.index('artifacts'):])

def receipts(value):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            yield value
        for nested in value.values():
            yield from receipts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from receipts(nested)


@pytest.mark.parametrize('fabric', FABRICS)
@pytest.mark.parametrize('mode', ('pedestrian', 'bicycle', 'motor_vehicle'))
def test_round7_durable_lineage_and_selected_plan(fabric, mode):
    document = load_verified(ROUND / 'syntax/segments' / f'{fabric}-{mode}.geojson')
    refs = document['metadata']['source_receipts']
    verify_selected_plan_receipt(ROOT / 'artifacts/fab1/run-8', fabric, refs['plan'])
    assert _repo_relative(refs['compact']['path']) == _repo_relative(ROUND / 'syntax' / f'{fabric}-{mode}.json')
    compact = json.loads(verify(refs['compact']).read_text())
    canonical = json.loads((ROUND / 'syntax' / f'{fabric}-{mode}.json').read_text())
    assert canonical == compact
    summary = json.loads((ROUND / 'syntax/syntax-summary.json').read_text())
    assert summary['computed_count'] == 12 and len(summary['results']) == 12
    assert next(r for r in summary['results'] if r['fabric_id'] == fabric and r['mode'] == mode) == compact
    assert compact['source_receipts']['extract'] == scenario_syntax.verified_extract(mode)[1]
    full = json.loads(verify(refs['full']).read_text())
    assert full['pst_checkpoint_receipts']
    checkpoints = [json.loads(verify(ref).read_text()) for ref in full['pst_checkpoint_receipts']]
    for value in (document, compact, full, checkpoints):
        for ref in receipts(value):
            path = Path(ref['path'])
            # Verify the complete compute/export receipt chain. Historical
            # acquisition provenance is covered by verified_extract separately.
            if value is full or value is checkpoints:
                verify(ref)
            assert not any(path == base or base in path.parents for base in (Path('/tmp'), Path('/private/tmp'))), ref
    for ref in full['pst_checkpoint_receipts']:
        checkpoint = json.loads(verify(ref).read_text())
        verify(checkpoint['raw_result'])
        assert _repo_relative(checkpoint['raw_result']['path']).startswith('artifacts/net2/round-7/receipts/')
    app = FastAPI()
    app.include_router(create_fabric_plans_router())
    response = TestClient(app).get(f'/api/v1/fabric-plans/{fabric}/syntax/{mode}')
    assert response.status_code == 200, response.text
