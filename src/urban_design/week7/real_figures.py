"""Deterministic projection of hash-verified scene geometry and result sensors.

SVG is a real vector artifact. PNG rendering is optional and uses the existing
QGIS renderer. Missing geometry/results never produce a schematic substitute.
"""
from __future__ import annotations
import hashlib
import html
import json
import math
from pathlib import Path
from typing import Literal
from shapely.geometry import shape, mapping
from urban_design.figure_export import _color_ramp, _render_svg_to_png
from .real_service import EntityRef, RealWeek7Service, ref
from .service import Week7Refusal

KINDS = ('plan', 'perspective', 'axonometric', 'massing', 'site', 'syntax', 'e1', 'e2', 'comparison')


def render_real_figure(*, service: RealWeek7Service, workspace_id: str, targets: list[EntityRef], kind: str,
                       output_path: Path, result_artifact_ids: list[str] | None = None, syntax_layer_id: str | None = None, png: bool = True):
    if png and Path(output_path).suffix.lower() != '.png':
        raise Week7Refusal('png_output_extension_required', {})
    if kind not in KINDS or not targets:
        raise Week7Refusal('figure_request_invalid', {})
    if kind == 'comparison' and len(targets) < 2:
        raise Week7Refusal('comparison_requires_two_scenarios', {})
    ws = service.workspace(workspace_id)
    scenes, missing, sources = [], [], []
    for target in targets:
        _, scenario = service.target(workspace_id, target, {'DesignScenario'})
        artifact, doc = service.artifact(scenario.payload['geometry_artifact_id'], ws.project_id)
        if artifact.payload['sha256'] != scenario.payload.get('geometry_sha256') or artifact.payload.get('crs') != 'EPSG:28992':
            raise Week7Refusal('scene_geometry_binding_invalid', {})
        features = doc.get('features', [])
        if not features:
            raise Week7Refusal('scene_geometry_missing', {})
        sources.append({'ref': ref(artifact), 'sha256': artifact.payload['sha256']})
        scenes.append({'scenario': scenario, 'features': features, 'sensors': [], 'method': '', 'period': '', 'unit': 'm'})
    # Workspace StudyArea and frozen normalized observations provide the site
    # layer. Geometry is clipped deterministically, never sketched from metrics.
    study = service.record(ws.payload.get('study_area_id'), 'StudyArea')
    study_artifact, study_doc = service.artifact(study.payload['geometry_artifact_id'], ws.project_id)
    if study_doc.get('type') == 'FeatureCollection':
        study_geom = shape(study_doc['features'][0]['geometry'])
    elif study_doc.get('type') == 'Feature':
        study_geom = shape(study_doc['geometry'])
    else:
        study_geom = shape(study_doc)
    boundary = {'type':'Feature','geometry':mapping(study_geom),'properties':{'role':'study_area'}}
    sources.append({'ref':ref(study_artifact),'sha256':study_artifact.payload['sha256']})
    site_features = [boundary]
    if kind == 'site':
        for snapshot_id in ws.payload.get('source_snapshot_ids', []):
            snapshot = service.record(snapshot_id, 'DatasetSnapshot')
            artifact_id = snapshot.payload.get('normalized_artifact_id')
            role = 'existing_building' if 'bag-pand' in snapshot_id else 'road' if 'wegdeel' in snapshot_id else 'water' if 'waterdeel' in snapshot_id else None
            if not artifact_id or not role:
                continue
            artifact, source_doc = service.artifact(artifact_id, ws.project_id)
            if artifact.payload.get('crs') != 'EPSG:28992':
                raise Week7Refusal('SITE_SOURCE_CRS_MISMATCH', {})
            sources.append({'ref':ref(artifact),'sha256':artifact.payload['sha256']})
            for feature in source_doc.get('features', []):
                clipped = shape(feature['geometry']).intersection(study_geom)
                if not clipped.is_empty:
                    site_features.append({'type':'Feature','geometry':mapping(clipped),'properties':{'role':role,'source_feature_id':feature.get('id')}})
        if len(site_features) == 1:
            raise Week7Refusal('MISSING_SITE_OBSERVATIONS', {})
    for scene in scenes:
        scene['features'] = site_features if kind == 'site' else [boundary, *scene['features']]
    results = []
    for artifact_id in result_artifact_ids or []:
        artifact = service.record(artifact_id, 'Artifact')
        if artifact.project_id != ws.project_id:
            raise Week7Refusal('result_out_of_scope', {})
        if artifact.payload.get('bundle') is not None:
            doc = artifact.payload['bundle']
            raw = json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=artifact.payload.get('type') == 'sunlight_simulation_result', allow_nan=False).encode()
            if 'sha256:' + hashlib.sha256(raw).hexdigest() != artifact.payload['sha256']:
                raise Week7Refusal('embedded_bundle_hash_mismatch', {})
        else:
            artifact, doc = service.artifact(artifact_id, ws.project_id)
        sources.append({'ref': ref(artifact), 'sha256': artifact.payload['sha256']})
        results.append((artifact, doc))
    if kind == 'syntax':
        if len(results) != 1 or not syntax_layer_id:
            raise Week7Refusal('SYNTAX_LAYER_AND_SINGLE_SOURCE_REQUIRED', {})
        artifact, data = results[0]
        if study.entity_id not in artifact.payload.get('parent_artifact_ids', []) or (data.get('source_provenance') or {}).get('study_area_geometry_sha256') != study.payload.get('geometry_sha256'):
            raise Week7Refusal('SYNTAX_STUDY_AREA_BINDING_INVALID', {})
        layer = next((r for r in data.get('layers', []) if r.get('layer_id') == syntax_layer_id), None)
        if not layer or layer.get('calculation_status') != 'COMPUTED' or not layer.get('segment_values'):
            raise Week7Refusal('MISSING_SYNTAX_VALUES', {})
        if len(scenes) != 1:
            raise Week7Refusal('SITE_SYNTAX_REQUIRES_SINGLE_SCENE', {})
        scene = scenes[0]
        scene.update(method=layer.get('formula_version'), unit=layer.get('unit'), period='frozen source observations (see hashes)',
                     lines=[(s['geometry'], layer['segment_values'][s['id']]) for s in data.get('segments', []) if s['id'] in layer['segment_values']])
        if not scene['lines']:
            raise Week7Refusal('MISSING_SYNTAX_GEOMETRY', {})
        missing.append('EXPLORATORY: ' + str(layer.get('data_readiness')))
        scene['syntax_layer_id']=syntax_layer_id
        scene['radius_m']=layer.get('radius_m')
        scene['features'] = [boundary]
    if kind in {'e1', 'e2'} or (kind == 'comparison' and results):
        if not results:
            raise Week7Refusal('MISSING_ANALYSIS_DATA', {'kind': kind})
        for scene in scenes:
            scenario = scene['scenario']
            matching = [(a, d) for a, d in results if d.get('scenario_id') == scenario.entity_id or scenario.entity_id in d.get('scenario_ids', [])]
            if not matching:
                raise Week7Refusal('MISSING_SCENARIO_ANALYSIS_DATA', {'scenario_id': scenario.entity_id})
            if len(matching) != 1:
                raise Week7Refusal('ONE_METHOD_PERIOD_PER_SCENE_REQUIRED', {})
            artifact, data = matching[0]
            if artifact.payload.get('type') == 'sunlight_simulation_result':
                ids=data.get('scenario_ids', [])
                if len(ids)!=2 or scenario.entity_id not in ids:
                    raise Week7Refusal('E1_SCENARIO_BINDING_INVALID', {})
                hashes=dict(zip(data.get('input_artifact_ids', []),data.get('input_artifact_hashes', [])))
                if hashes.get(scenario.payload['geometry_artifact_id']) != scenario.payload.get('geometry_sha256'):
                    raise Week7Refusal('STALE_ANALYSIS_DATA', {})
                points=data.get('baseline_results' if ids[0]==scenario.entity_id else 'modified_results', [])
                if not points or not data.get('period'):
                    raise Week7Refusal('MISSING_SENSOR_VALUES', {})
                scene.update(method=data.get('method'),period=json.dumps(data['period'],sort_keys=True),unit='hours',
                    validation_status='UNVERIFIED' if data.get('plan_status')=='DRAFT_UNAPPROVED' else 'SOURCE_CARD_REQUIRED',
                    domain_signature=json.dumps(data.get('comparison_domain'),sort_keys=True),
                    sensors=[(p['coordinates'],p['sunlight_hours']) for p in points if p.get('status')=='VALID'])
                missing.append('E1 plan status: '+str(data.get('plan_status')))
                continue
            meta = data.get('metadata') or {}
            if meta.get('geometry_sha256') != scenario.payload.get('geometry_sha256') or meta.get('scenario_revision') != scenario.revision:
                raise Week7Refusal('STALE_ANALYSIS_DATA', {})
            distribution = data.get('distribution') or {}
            values = distribution.get('values') or {}
            sensors = distribution.get('sensors') or []
            if not sensors or not values or data.get('status') != 'SUCCEEDED':
                raise Week7Refusal('MISSING_SENSOR_VALUES', {})
            # Recover period from its immutable experiment plan, not UI text.
            _, plan = service.artifact(data.get('plan_id'), ws.project_id)
            period = plan.get('period') or plan.get('analysis_period') or {key:plan[key] for key in ('start_month','start_day','start_hour','end_month','end_day','end_hour','time_basis') if key in plan}
            if not period:
                raise Week7Refusal('MISSING_ANALYSIS_PERIOD', {})
            scene.update(method=data.get('method'), period=json.dumps(period, sort_keys=True),
                         unit=distribution.get('unit'), offset_hours=data.get('offset_hours'),
                         domain_signature=json.dumps({key:plan.get(key) for key in ('grid','comparison_domain','weather_bundle_sha256')},sort_keys=True),
                         sensors=[(s['coordinates'], values[s['point_id']]) for s in sensors
                                  if s.get('status') == 'VALID' and s['point_id'] in values])
            if not scene['unit'] or not scene['method']:
                raise Week7Refusal('MISSING_METHOD_OR_UNIT', {})
        bases = {(s['method'], s['unit'], s['period'], s.get('offset_hours'), s.get('domain_signature')) for s in scenes}
        if len(bases) > 1:
            raise Week7Refusal('NOT_COMPARABLE_METHOD_UNIT_PERIOD', {})
    bounds = [shape(f['geometry']).bounds for s in scenes for f in s['features'] if f.get('geometry')]
    minx, miny = min(b[0] for b in bounds), min(b[1] for b in bounds)
    maxx, maxy = max(b[2] for b in bounds), max(b[3] for b in bounds)
    extent = [minx, miny, maxx, maxy]
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    radius = max(maxx - minx, maxy - miny, 1)
    count = len(scenes)
    width, height, pane_width = 1240, 850, 1160 / count
    angle, elevation = math.radians(315), math.radians(35)
    projected = kind in {'perspective', 'axonometric', 'massing'}
    scale = min((pane_width - 30) / (radius * 1.6), 530 / (radius * 1.6)) if projected else min((pane_width - 30) / max(maxx-minx,1), 530 / max(maxy-miny,1))
    projected_center = [0.0, 0.0]
    if projected:
        frame=[]
        for scene in scenes:
            heights={f['building_id']:f.get('height_above_ground_m') for f in (scene['scenario'].payload.get('parameters') or {}).get('floor_estimates', [])}
            for feature in scene['features']:
                geom=shape(feature['geometry']);props=feature.get('properties') or {}
                h=props.get('height_m',0) if props.get('role') == 'new_building' else heights.get(props.get('building_id'),0) if props.get('role') == 'retained' else 0
                parts=[geom] if geom.geom_type == 'Polygon' else list(geom.geoms) if geom.geom_type=='MultiPolygon' else []
                for poly in parts:
                    for x,y,*_ in poly.exterior.coords:
                        x,y=x-cx,y-cy
                        u=math.cos(angle)*x-math.sin(angle)*y
                        depth=math.sin(angle)*x+math.cos(angle)*y
                        for z in (0,float(h or 0)):
                            v=depth*math.sin(elevation)-z*math.cos(elevation)
                            factor=radius*4/(radius*4+depth*math.cos(elevation)+z*math.sin(elevation)) if kind=='perspective' else 1
                            frame.append((u*factor,v*factor))
        umin,umax=min(p[0] for p in frame),max(p[0] for p in frame)
        vmin,vmax=min(p[1] for p in frame),max(p[1] for p in frame)
        scale=min((pane_width-30)/max(umax-umin,1),530/max(vmax-vmin,1))
        projected_center=[(umin+umax)/2,(vmin+vmax)/2]
    all_values = [float(v) for s in scenes for _, v in [*s['sensors'], *s.get('lines', [])] if math.isfinite(float(v))]
    ramp = [min(all_values), max(all_values)] if all_values else None
    camera = {'projection': kind if projected else 'plan', 'azimuth_deg': 315 if projected else 0,
              'elevation_deg': 35 if projected else 90, 'extent': extent, 'center': [cx, cy], 'scale': scale,
              'perspective_distance_m': radius * 4 if kind == 'perspective' else None, 'manipulators': 'hidden'}
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="850" viewBox="0 0 1240 850">',
             '<rect width="1240" height="850" fill="white"/>']
    def text(x,y,value,size=12):
        lines.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="#172554">{html.escape(str(value))}</text>')
    text(40,30,f'{kind} · EPSG:28992 · workspace {ws.entity_id}@{ws.revision}',16)
    for index, scene in enumerate(scenes):
        scenario = scene['scenario']
        xcenter = 40 + pane_width * (index + .5)
        def project(x,y,z=0):
            x,y = x-cx,y-cy
            if projected:
                u = math.cos(angle)*x-math.sin(angle)*y
                depth = math.sin(angle)*x+math.cos(angle)*y
                v = depth*math.sin(elevation) - z*math.cos(elevation)
                if kind == 'perspective':
                    factor = radius*4 / (radius*4 + depth*math.cos(elevation) + z*math.sin(elevation))
                    u,v = u*factor,v*factor
                return xcenter+(u-projected_center[0])*scale,365+(v-projected_center[1])*scale
            return xcenter+x*scale,365-y*scale
        text(40+index*pane_width,55,f'{scenario.entity_id}@{scenario.revision}',9)
        polygons = []
        heights = {f['building_id']: f.get('height_above_ground_m') for f in (scenario.payload.get('parameters') or {}).get('floor_estimates', [])}
        for feature in scene['features']:
            geom = shape(feature['geometry']); props = feature.get('properties') or {}
            role = props.get('role', 'unknown')
            if geom.geom_type not in {'Polygon', 'MultiPolygon'}:
                continue
            height_m = props.get('height_m')
            if role == 'retained':
                height_m = heights.get(props.get('building_id'))
            if role in {'retained', 'new_building'} and projected and height_m is None:
                missing.append(f'height unavailable: {props.get("building_id", role)}; footprint only')
            z = float(height_m or 0) if projected and role in {'retained', 'new_building'} else 0
            fill = {'retained':'#64748b', 'new_building':'#60a5fa','road':'#cbd5e1','primary_open_space':'#bbf7d0','existing_building':'#64748b','water':'#bae6fd'}.get(role,'none')
            for poly in ([geom] if geom.geom_type == 'Polygon' else geom.geoms):
                if z > 0:
                    coords = list(poly.exterior.coords)
                    for a,b in zip(coords, coords[1:]):
                        points = [project(*a[:2],0),project(*b[:2],0),project(*b[:2],z),project(*a[:2],z)]
                        polygons.append((sum(p[1] for p in points)/len(points), f'<polygon points="{" ".join(f"{x:.2f},{y:.2f}" for x,y in points)}" fill="{fill}" stroke="#334155" stroke-width="0.4"/>'))
                paths=[]
                for ring in [poly.exterior, *poly.interiors]:
                    pts=[project(x,y,z) for x,y,*_ in ring.coords]
                    paths.append('M'+' L'.join(f'{x:.2f},{y:.2f}' for x,y in pts)+' Z')
                polygons.append((project(poly.centroid.x,poly.centroid.y,z)[1],f'<path d="{" ".join(paths)}" fill="{fill}" fill-rule="evenodd" stroke="#334155" stroke-width="0.4"/>'))
        for _, element in sorted(polygons, key=lambda p:p[0]):
            lines.append(element)
        for geometry,value in scene.get('lines', []):
            geom = shape(geometry).intersection(study_geom)
            if geom.is_empty: continue
            parts = [geom] if geom.geom_type == 'LineString' else [p for p in getattr(geom,'geoms',[]) if p.geom_type=='LineString']
            for part in parts:
                points = [project(x,y) for x,y,*_ in part.coords]
                lines.append(f'<polyline points="{" ".join(f"{x:.2f},{y:.2f}" for x,y in points)}" fill="none" stroke="{_color_ramp(float(value),*ramp)}" stroke-width="1.5"/>')
        for coords,value in scene['sensors']:
            if not math.isfinite(float(value)):
                continue
            x,y = project(*coords[:2])
            color = _color_ramp(float(value),*ramp)
            lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{max(.7,2.5*scale):.2f}" fill="{color}"/>')
        text(40+index*pane_width,680,f'method: {scene["method"] or "scene geometry"}; unit: {scene["unit"]}',11)
        text(40+index*pane_width,700,f'period: {scene["period"] or "not applicable (geometry)"}',8)
        if scene.get('lines'):
            text(40+index*pane_width,720,f'layer: {scene["syntax_layer_id"]}; radius: {scene["radius_m"]} m',10)
        if scene['sensors']:
            text(40+index*pane_width,720,f'offset hours: {scene.get("offset_hours")}; valid plotted sensors: {len(scene["sensors"])}',10)
    text(40,755,f'shared extent: {extent}; common camera; manipulator hidden',10)
    text(40,775,f'LEGEND: {ramp} {scenes[0]["unit"]}' if ramp else 'LEGEND: blue=new; grey=retained; green=open space; height gaps shown as footprints',10)
    text(40,795,'; '.join(sorted(set(missing)))[:210] or 'No schematic geometry substituted',9)
    text(40,820,'Computed evidence does not establish human acceptance, legal access or thermal comfort.',10)
    lines.append('</svg>')
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    svg = output_path.with_suffix('.svg')
    raw = '\n'.join(lines).encode()
    with svg.open('xb') as out:
        out.write(raw)
    result = {'status':'SVG_RENDERED','kind':kind,'workspace_ref':ref(ws),'scenarios':[ref(s['scenario']) for s in scenes],
              'camera':camera,'color_range':ramp,'sources':sources,'missing':sorted(set(missing)),
              'svg_path':str(svg),'svg_sha256':hashlib.sha256(raw).hexdigest(),'units':scenes[0]['unit'],
              'period':scenes[0]['period'] or 'not applicable (geometry)','schematic':False}
    if png:
        _render_svg_to_png(svg,output_path)
        result.update(status='PNG_RENDERED',png_path=str(output_path),png_sha256=hashlib.sha256(output_path.read_bytes()).hexdigest())
    with output_path.with_suffix('.manifest.json').open('x') as out:
        json.dump(result,out,indent=2)
    return result
