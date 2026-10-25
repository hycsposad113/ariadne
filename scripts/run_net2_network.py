"""NET2 append-only deterministic replanning, authoritative shared validation."""
import argparse
import csv
import hashlib
import json
import sys
import shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from urban_design import scenario_syntax as ss
from urban_design.generation.fabric_net2 import generate_net2_plan, retain_and_connect_network, enforce_five_storeys_and_fill, fill_round6_points, direct_round6_links, repair_round7_links
from urban_design.generation.fabric_network_finish import finish_network
from urban_design.generation.fabric_plan import validate_plan, compare_plans


def write(path, value):
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(payload.encode()) >= 5_000_000:
        raise ValueError('NET2 file exceeds 5 MB')
    path.write_text(payload)


def run(number, output):
    if output.exists() and any(output.iterdir()):
        raise ValueError('NET2 needs fresh append-only output')
    output.mkdir(parents=True, exist_ok=True)
    frozen = Path('artifacts/fab1/run-5/inputs')
    facts = json.loads((frozen / 'site-facts.json').read_text())
    context = json.loads((frozen / 'context-facts.json').read_text())
    network_context = json.loads(Path('artifacts/ctx1-context-morphology/context-facts.json').read_text())
    external = {m: ss.verified_extract(m)[0]['network']['features'] for m in ss.MODES}
    plans = []; summary = []
    for source in sorted(Path('artifacts/fab1/run-6').glob('*-plan.json')):
        parent = json.loads(source.read_text())
        if 4<=number<=5 and parent['fabric_id'] not in ('fabric.courtyard_islands','fabric.landscape_figure'):
            original=Path('artifacts/net2/round-3/plans')/source.name
            shutil.copyfile(original,output/source.name)
            plan=json.loads(original.read_text());plans.append(plan)
            summary.append({'fabric_id':plan['fabric_id'],'status':plan['validation']['status'],'failure_ids':plan['validation']['failure_ids'],'new_gfa_m2':plan['metrics']['new_gfa_m2'],'copied_verbatim_from':str(original)})
            continue
        if number==7 and parent['fabric_id']=='fabric.courtyard_islands':
            original=Path('artifacts/net2/round-5/plans')/source.name
            shutil.copyfile(original,output/source.name)
            plan=json.loads(original.read_text());validation=validate_plan(plan)
            write(output/'courtyard_islands-checks.json',{'core_validator':validation,'failure_ids':validation['failure_ids'], 'copied_verbatim_from':str(original),'reason':'r6 four-island reconstruction regresses whole useful courtyard width to 57m >45m; stop and preserve r5; original r5 three-island failure is not accepted'})
            summary.append({'fabric_id':plan['fabric_id'],'status':validation['status'],'failure_ids':validation['failure_ids'],'new_gfa_m2':validation['metrics']['new_gfa_m2'],'copied_verbatim_from':str(original)})
            comparison_plan=json.loads(original.read_text());comparison_plan['validation']=validation;comparison_plan['metrics']=validation['metrics']
            plans.append(comparison_plan);print(json.dumps(summary[-1]),flush=True);continue
        if number>=6:
            previous=number-1 if number==7 else (5 if parent['fabric_id'] in ('fabric.courtyard_islands','fabric.landscape_figure') else 3)
            start=Path(f'artifacts/net2/round-{previous}/plans')/source.name
            parent=json.loads(start.read_text())
            if number==6 and parent['fabric_id']=='fabric.courtyard_islands':
                plan=generate_net2_plan(facts,context,parent['fabric_dictionary'],external,number)
                plan=retain_and_connect_network(plan,parent)
                plan=enforce_five_storeys_and_fill(plan)
            else:
                plan=json.loads(start.read_text())
                plan['net2']['round']=number
            plan['net2']['starting_plan']={'path':str(start),'sha256':hashlib.sha256(start.read_bytes()).hexdigest()}
            if number==7:
                original=Path(parent['net2']['starting_plan']['path'])
                plan['net2']['round6_candidate']={'path':str(start),'sha256':hashlib.sha256(start.read_bytes()).hexdigest()}
                plan['net2']['starting_plan']={'path':str(original),'sha256':hashlib.sha256(original.read_bytes()).hexdigest()}
                plan=repair_round7_links(plan,json.loads(original.read_text()))
            else:
                plan=fill_round6_points(plan)
                plan=direct_round6_links(plan,external['motor_vehicle'])
        else:
            plan = generate_net2_plan(facts, context, parent['fabric_dictionary'], external, number)
            plan = retain_and_connect_network(plan, parent) if number >= 2 else finish_network(plan, external, network_context, 3)
            if number >= 3:
                plan = enforce_five_storeys_and_fill(plan)
        validation = validate_plan(plan)
        plan['validation'] = validation; plan['metrics'] = validation['metrics']
        plan['net2']['parent_receipt'] = plan['net2'].get('starting_plan', {'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
        stem = source.stem.removesuffix('-plan')
        write(output / source.name, plan)
        write(output / f'{stem}-checks.json', {'schema_version':'fab1-plan-checks-v1','fabric_id':plan['fabric_id'],'core_validator':validation,'failure_ids':validation['failure_ids'],'net2_round':number,'render_status':'NOT_REGENERATED'})
        row = {'fabric_id': plan['fabric_id'], 'status': validation['status'], 'failure_ids': validation['failure_ids'], 'new_gfa_m2': validation['metrics']['new_gfa_m2']}
        summary.append(row); plans.append(plan)
        print(json.dumps(row), flush=True)
    write(output / 'comparison.json', compare_plans(plans))
    write(output / 'generation-summary.json', summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--round', type=int, required=True, choices=(1, 2, 3, 4, 5, 6, 7))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); run(args.round, args.output)
