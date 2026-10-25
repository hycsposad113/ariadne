"""J11 DRAFT rehearsal, strictly offline and copy-only."""
import argparse
from pathlib import Path
from urban_design.generation.formal_multimodal import run_copy
p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--diagnosis',type=Path);p.add_argument('--motor-cache',type=Path)
a=p.parse_args();r=run_copy(a.database,a.output,diagnosis_path=a.diagnosis,motor_cache=a.motor_cache)
print(r['status'],r['valid_variant_count'],r['runtime_seconds'])
raise SystemExit(0 if r['status']=='DRAFT' else 2)
