"""Export actual NET2 allocation geometry with the existing FAB CSV writer."""
import argparse
import json
from pathlib import Path
from run_fabric_plan import _landuse_csv_rows, write_landuse_csv


def run(root):
    facts=json.loads(Path('artifacts/fab1/run-5/inputs/site-facts.json').read_text())
    for path in sorted(root.glob('*-plan.json')):
        plan=json.loads(path.read_text());destination=path.with_name(path.name.removesuffix('-plan.json')+'-landuse.csv')
        if destination.exists():raise ValueError('Preserve prior CSV: '+str(destination))
        # Use the delivered projected land denominator, avoiding stale estimates.
        export_facts={**facts,'site':{**facts['site'],'land_area_m2':plan['metrics']['land_area_m2']}}
        rows=_landuse_csv_rows(plan,export_facts)
        write_landuse_csv(destination,rows)
        if destination.stat().st_size>=5_000_000:raise ValueError('CSV exceeds size cap')
        print(destination,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);run(p.parse_args().root)
