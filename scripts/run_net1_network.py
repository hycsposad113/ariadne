"""Append-only NET1 round generation from retained run-5; no database writes."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from urban_design import scenario_syntax as ss
from urban_design.generation.fabric_network_finish import finish_network
from urban_design.generation.fabric_plan import validate_plan


def write(path, value):
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(payload.encode()) >= 5_000_000:
        raise ValueError('NET1 artifact exceeds 5 MB')
    path.write_text(payload)


def run(number, output):
    if output.exists():
        raise ValueError('Use a fresh NET1 round output')
    output.mkdir(parents=True)
    parent = Path('artifacts/fab1/run-5')
    context = json.loads(Path('artifacts/ctx1-context-morphology/context-facts.json').read_text())
    external = {mode: ss.verified_extract(mode)[0]['network']['features'] for mode in ss.MODES}
    rows = []
    for source in sorted(parent.glob('*-plan.json')):
        original = json.loads(source.read_text()); plan = finish_network(original, external, context, number)
        validation = validate_plan(plan)
        plan['validation'] = validation; plan['metrics'] = validation['metrics']
        plan['net1']['parent_receipt'] = {'path': str(source.resolve()), 'sha256': 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest()}
        fabric = source.stem.removesuffix('-plan')
        write(output / source.name, plan)
        checks = {'schema_version': 'fab1-plan-checks-v1', 'fabric_id': fabric,
                  'core_validator': validation, 'failure_ids': validation['failure_ids'],
                  'net1_round': number, 'render_status': 'NOT_REGENERATED'}
        write(output / f'{fabric}-checks.json', checks)
        # Land allocation and buildings remain exact run-5 geometries.
        csv = parent / f'{fabric}-landuse.csv'
        (output / csv.name).write_bytes(csv.read_bytes())
        rows.append({'fabric_id': fabric, 'status': validation['status'],
                     'failure_ids': validation['failure_ids'], 'added_roads': len(plan['net1']['added_roads']),
                     'new_gfa_percent': validation['metrics']['new_gfa_m2'] / 146873 * 100})
        print(f'{fabric} {validation["status"]} {validation["failure_ids"]}', flush=True)
    comparison = json.loads((parent / 'comparison.json').read_text())
    comparison['net1_round'] = number
    comparison['net1_validation'] = rows
    comparison['status'] = 'PASS' if all(r['status'] == 'PASS' for r in rows) else 'FAIL'
    write(output / 'comparison.json', comparison)
    write(output / 'generation-summary.json', rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--round', type=int, required=True, choices=(1, 2, 3))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.round, args.output)
