from __future__ import annotations
import hashlib, json, shutil
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'artifacts/milestone2-site-proposal-rotterdam-m4h-v3/run-20260915T120300Z'
V2=ROOT/'artifacts/milestone2-site-proposal-rotterdam-m4h-v2/run-20260915T110000Z'

def payload(): return json.loads((PACKAGE/'site-proposal.json').read_text())

def test_v3_validates_and_preserves_proposed_state():
 from urban_design.site_proposal_rotterdam_v3 import validate_site_proposal_rotterdam_v3
 p=validate_site_proposal_rotterdam_v3(payload(),PACKAGE,v2_dir=V2)
 assert p.id=='site-proposal-rotterdam-m4h-v3'; assert p.status=='PROPOSED'; assert p.human_decision_status=='HUMAN_DECISION_REQUIRED'
 assert p.delft_context['display_option']=='A'; assert p.delft_context['option_b_rejection_reason'].startswith('REJECTED_BY_HUMAN_FEEDBACK')

def test_parent_v2_all_bytes_match_manifest():
 m=json.loads((PACKAGE/'parent-v2-integrity.json').read_text())
 for item in m['files']:
  p=PACKAGE/item['retained_path']; assert p.stat().st_size==item['size_bytes']; assert 'sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']

def test_human_feedback_is_retained_intent_only():
 d=json.loads((PACKAGE/'sources/human-feedback-evidence.json').read_text())
 assert len(d['feedback'])==3
 for x in d['feedback']:
  assert x['classification']==['HUMAN_FEEDBACK','HUMAN_INTENT']; assert x['used_as_measurement'] is False; assert (PACKAGE/x['retained_path']).is_file()

def test_boundary_has_dense_closed_valid_ring_and_edge_evidence():
 from urban_design.geometry import validate_geometry
 p=payload(); validate_geometry(p['geometry'])
 ring=p['geometry']['coordinates'][0]; assert len(ring)>12 and ring[0]==ring[-1]
 ev=json.loads((PACKAGE/'sources/boundary-relationship-evidence-v3.json').read_text())
 assert len(ev['edges'])==len(ring)-1
 assert any(x['claim_status']=='HUMAN_INTENT_ALIGNMENT_REVIEW' for x in ev['edges'])
 assert any(x['claim_status']=='SOURCE_GEOMETRY_SEGMENT' for x in ev['edges'])

def test_display_is_exclusive_and_water_is_dissolved():
 d=json.loads((PACKAGE/'display-data-v3.geojson').read_text()); assert d['classification_priority']==['background/land','water','public/open','context buildings','site buildings','roads/walk paths','rail','labels/markers','boundary']
 layers=[f['properties']['display_layer'] for f in d['features']]; assert all(layer in d['classification_priority'] for layer in layers); assert all(list(f['properties']).count('display_layer')==1 for f in d['features'])
 assert sum(x=='water' for x in layers)==1
 assert all(not f['properties'].get('geometry_clipped') for f in d['features'] if f['properties']['display_layer'] in {'context buildings','site buildings'})

def test_svg_layer_order_and_styling():
 import re
 text=(PACKAGE/'map-preview-v3.svg').read_text()
 required=['layer-background','layer-water','layer-public-space','layer-context-buildings','layer-site-buildings','layer-roads','layer-rail','layer-markers','layer-boundary']
 ids=re.findall(r'<g id="([^"]+)"',text); assert [x for x in ids if x in required]==required
 assert '#f1f4f5' in text and '#d62728' in text and 'stroke-width="1.4"' in text
 assert 'REJECTED_BY_HUMAN_FEEDBACK' in text and 'Cross-boundary buildings' in text

def test_png_is_valid_dimensions_and_nonblank():
 p=PACKAGE/'map-preview-v3.png'; raw=p.read_bytes(); assert raw[:8]==b'\x89PNG\r\n\x1a\n'; assert int.from_bytes(raw[16:20],'big')==1240; assert int.from_bytes(raw[20:24],'big')==850; assert any(b not in (0,255) for b in raw[32:])

def test_state_has_no_approval_or_effective_project_site():
 import sqlite3
 c=sqlite3.connect(PACKAGE/'proposal-state.sqlite3')
 try:
  project=[json.loads(x[0]) for x in c.execute("select payload_json from state_versions where entity_type='Project'")]
  assert any(x.get('id')=='rotterdam-m4h-pilot-project' and x.get('site_id') is None for x in project)
  assert not c.execute("select 1 from ledger_events where lower(action) like '%approve%' or lower(action) like '%accept%' or lower(action) like '%freeze%'").fetchall()
 finally:c.close()

def test_builder_offline_rebuilds_hashes(tmp_path):
 from scripts.create_site_proposal_rotterdam_v3 import build_rotterdam_v3
 out=tmp_path/'rebuild'; rebuilt=build_rotterdam_v3(out,v2_dir=V2,bgt_source=PACKAGE/'sources/raw/pdok-bgt-wegdeel-m4h.json',offline=True)
 assert rebuilt.boundary_sha256==payload()['boundary_sha256']; assert rebuilt.geometry_sha256==payload()['geometry_sha256']; assert hashlib.sha256((out/'map-preview-v3.svg').read_bytes()).hexdigest()==hashlib.sha256((PACKAGE/'map-preview-v3.svg').read_bytes()).hexdigest()
 expected=json.loads((PACKAGE/'sources/human-feedback-evidence.json').read_text())['feedback']
 actual=json.loads((out/'sources/human-feedback-evidence.json').read_text())['feedback']
 assert [(x['original_path'],x['sha256'],x['size_bytes']) for x in actual]==[(x['original_path'],x['sha256'],x['size_bytes']) for x in expected]
 for record in actual:
  retained=out/record['retained_path']
  assert retained.stat().st_size==record['size_bytes']
  assert 'sha256:'+hashlib.sha256(retained.read_bytes()).hexdigest()==record['sha256']
