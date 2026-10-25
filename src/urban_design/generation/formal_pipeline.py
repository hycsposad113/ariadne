"""Approved-input G2/dictionary execution; no decisions or fixture input values."""
from itertools import combinations
import hashlib
import json
from types import SimpleNamespace
from shapely.geometry import mapping, shape
from shapely.ops import unary_union, nearest_points
from .block_program import build_block_program, geometry_value
from .massing_adapter import build_massing
from .contracts import (FrozenRef, FixtureDictionaryRecipe, FixtureRetainedBuilding, ValidationReport, ValidationCheck, StageStatus)
from .hashing import semantic_digest
from .skeleton import SkeletonInputs, SkeletonEntry, build_skeleton, _principal_angle
from .strategy_catalog import build_strategy_catalog
from .formal_adapter import retained_gfa_bounds
from urban_design.morphology.streets import derive_land_block_contacts
from urban_design.far import FarSiteContext, resolve_far_denominator

from .road_access import (ROAD_ACCESS_RULE_M, ROAD_ACCESS_PROVENANCE, ROAD_ACCESS_BASIS, road_surface, road_access_metrics, aligned_access_paths, rebuild_access_skeleton, prune_access_lanes)

VERSION = 'formal-dictionary-v6-south-strip-collector'
# Authored candidate recipe settings, not approved constraints or observations.
RECIPES = (
    ('grid-mixed', 'CONNECTED_GRID', 100., .76, 5),
    ('common-mixed', 'CENTRAL_COMMON', 100., .75, 5),
    ('spine-mixed', 'LINEAR_SPINE', 110., .74, 5),
    ('grid-fine', 'CONNECTED_GRID', 80., .78, 5),
    ('common-compact', 'CENTRAL_COMMON', 80., .77, 4),
)


def approved_parameters(inputs):
    def value(name, scope='whole_site'):
        rows = [c for c in inputs.constraint_set.constraints if c.name == name and c.scope == scope]
        if len(rows) != 1:
            raise ValueError('unique approved constraint required: '+name+'/'+scope)
        return float(rows[0].value)
    params = {key: {'value':value(name), 'unit':unit} for key,name,unit in (
        ('far_upper_bound','far_upper_limit','ratio'),('coverage_upper_bound','coverage_upper_limit','ratio'),
        ('height_upper_bound_m','height_upper_limit','m'),('standard_floor_height_m','standard_floor_height','m'),
        ('first_floor_height_m','first_floor_height','m'))}
    params.update(access_lane_width_m=4.5, road_local_width_m=value('road_width','road:residential'),road_collector_width_m=value('road_width','road:primary'))
    # D1 explicitly approved 15m band; 0.25m numerical clearance and 3m
    # retained separation are authored recipe settings, never planning rules.
    params.update(waterfront_band_m={'value':15.,'unit':'m'}, retained_setback_m={'value':3.,'unit':'m'},
                  road_clearance_m=.25, noding_grid_m=1e-6, grid_open_space_diameter_m=24.,central_common_diameter_m=40.,linear_open_space_width_m=18.)
    params['road_access'] = {'rule_m':ROAD_ACCESS_RULE_M,'provenance':ROAD_ACCESS_PROVENANCE,'basis':ROAD_ACCESS_BASIS,
                             'access_lane_width_m':4.5,'added_length_budget_ratio':.25,'selection_policy':'accessible envelopes first; required types before trial preferences; place-serve-replace; prune final unused lanes','spur_max_count':64,'access_halo_m':35.,'intermediate_building_halos_m':[35.,15.,5.],'trial_anchor_policy':'independent candidate-local trial preferences','access_lane_width_provenance':'ASSUMED_COMMANDER'}
    params['south_strip_collector'] = {'provenance':'FOUNDER_DECISION_2026-10-04',
        'families':['CENTRAL_COMMON','LINEAR_SPINE'], 'width_parameter':'road_collector_width_m',
        'derivation':'longest width-clear grid-aligned section in southern half of site; site-relative 4 m sampling; equal lengths prefer southern-half centre; both endpoints attached to original network',
        'retained_setback_m':3, 'waterfront_band_m':15}
    return params


def skeleton_inputs(inputs, context):
    land=inputs.design_area.difference(inputs.water_geometry)
    parts=[land] if land.geom_type=='Polygon' else list(land.geoms)
    # Sub-micrometre-area overlay residues are not routable land blocks.
    # Preserve them in the report and FAR denominator; only the G2 routing
    # domain excludes <1e-6 m2, matching block-program geometry tolerance.
    land=unary_union([p for p in parts if p.area > 1e-6])
    parts=[p for p in parts if p.area > 1e-6]
    contacts=[c for part in parts for c in derive_land_block_contacts(inputs.source_network_roads,land_block=part,design_area=inputs.design_area)]
    refs={r.id:r for r in context.source_refs}
    # Source intersections on a sloping boundary may lie ~1e-11m outside
    # after floating point overlay. Project <=1e-6m to an interior witness;
    # source IDs are unchanged and G2's own boundary tolerance still applies.
    def contact_point(point):
        witness=nearest_points(land.buffer(-1e-7),point)[0]
        if witness.distance(point)>1e-6:
            raise ValueError('contact normalization exceeds 1 micrometre')
        return witness
    entries=tuple(SkeletonEntry(c.contact_id,contact_point(c.point),c.layer,(refs[c.source_artifact_id],refs[c.source_snapshot_id]),c.bridge,c.tunnel) for c in contacts)
    if not entries:
        raise ValueError('BLOCKED: no source-derived external road contacts')
    retained=tuple(g for _,g,_ in inputs.retained_buildings)
    retained_refs=tuple(FrozenRef(id=d.feature_id,sha256=semantic_digest(g),kind='RETAINED_FOOTPRINT') for d,g,_ in inputs.retained_buildings)
    eligible=sorted((e for e in entries if e.level==0 and not e.bridge and not e.tunnel),key=lambda e:e.id)
    if not eligible: raise ValueError('BLOCKED: no at-grade contact')
    waterfront=inputs.water_geometry.buffer(15).intersection(land)
    protected=() if waterfront.is_empty else (waterfront,)
    return SkeletonInputs(site_geometry=land,entry_contacts=entries,water_geometries=(),retained_geometries=retained,collector_exclusion_geometries=protected,
        source_refs=context.source_refs,retained_geometry_refs=retained_refs,spine_entry_id=eligible[0].id,
        spine_target=land.representative_point(),spine_target_ref=FrozenRef(id='recipe-land-interior-target',sha256=semantic_digest(land.representative_point()),kind='RECIPE_GEOMETRY'))


def run_formal_pipeline(context, manifest, inputs):
    from urban_design.generation_context import GenerationContext as FrozenManifest, context_digest
    if context_digest(FrozenManifest.model_validate(context.method_parameters.get('formal_manifest'))) != context_digest(manifest):
        raise ValueError('BLOCKED: supplied manifest differs from frozen typed context')
    bounds=retained_gfa_bounds(manifest)
    if bounds['status']=='UNAVAILABLE':
        return {'status':'BLOCKED','candidates':[],'blockers':['retained GFA unavailable: '+str(bounds['unavailable_buildings'])],'pairwise_differences':[]}
    params=approved_parameters(inputs)
    ctx=context.model_copy(update={'method_parameters':{**context.method_parameters,**params}})
    resolved=skeleton_inputs(inputs,ctx)
    catalog=build_strategy_catalog(SimpleNamespace(intents=()))
    families={s.topology_family:s for s in catalog.strategies}
    angle=round(_principal_angle(resolved.site_geometry)/15)*15
    # Shared 15-degree alignment follows G2 principal site axis.
    candidates=[]
    retained=tuple(FixtureRetainedBuilding(source_ref=r,geometry=geometry_value(g),floor_count=None) for r,g in zip(resolved.retained_geometry_refs,resolved.retained_geometries))
    far_constraint=next(c for c in inputs.constraint_set.constraints if c.name=='far_upper_limit' and c.scope=='whole_site')
    denominator,label=resolve_far_denominator(far_constraint,FarSiteContext(inputs.design_area,inputs.water_geometry))
    retained_union=unary_union(resolved.retained_geometries)
    for id,family,spacing,target_far,floor_count in RECIPES:
        row={'recipe_id':id,'recipe_version':VERSION,'family':family,'seed':ctx.seed,'status':'BLOCKED','failure_reasons':[], 'geometry':None,'context_hash':semantic_digest(ctx),'constraint_set_digest':context.constraint_refs[0].sha256}
        skeleton=blocks=massing=street_blocks=None
        try:
            candidate_context=ctx.model_copy(update={'method_parameters':{**ctx.method_parameters,'grid_spacing_m':spacing,'grid_alignment_deg':angle,'central_common_diameter_m':80. if id=='common-compact' else 40.}})
            strategy=families[family].model_copy(update={'strategy_id':id})
            skeleton=build_skeleton(candidate_context,strategy,resolved).artifact
            base_skeleton=skeleton
            row['south_strip_collector_paths']=[{'geometry':e.geometry.model_dump(mode='json'),
                'width_m':e.width_m,'role':e.id.split(':')[1], 'provenance':'FOUNDER_DECISION_2026-10-04'}
                for e in skeleton.edges if e.id.startswith(('road:south_strip_collector:', 'road:south_strip_connector:'))]
            original_road_length=sum(shape(e.geometry.model_dump()).length for e in skeleton.edges)
            lanes=[]
            # Placement preferences belong only to this candidate's own trials.
            preferred_cells=set()
            blocks=build_block_program(candidate_context,skeleton,geometry_value(resolved.site_geometry),strategy_id=id,ground_use='UNALLOCATED',
                water_geometry=geometry_value(inputs.water_geometry),retained_buildings=retained)
            street_blocks=blocks
            from .formal_placement import place_program
            target_gfa=max(0, min(target_far, params['far_upper_bound']['value'])*denominator-bounds['upper_m2'])
            if target_gfa <= 0:
                row.update(status='FAIL',failure_reasons=['retained GFA upper bound already exceeds candidate FAR budget'])
                raise ValueError(row['failure_reasons'][0])
            def placement(street, rule=ROAD_ACCESS_RULE_M, profile_filter=None):
                packed, recipes, assignments=place_program(street,angle=angle,zones=manifest.zones,recipe_id=id,
                    seed=ctx.seed,target_gfa_m2=target_gfa,floor_count=floor_count,road_edges=skeleton.edges,road_access_rule_m=rule,minimum_types=4,preferred_cells=preferred_cells,profile_filter=profile_filter)
                massing=build_massing(candidate_context,packed,next(iter(recipes.values())),retained,block_recipes=recipes)
                return packed, recipes, assignments, massing
            from .skeleton import _obstacles
            obstacles=unary_union([_obstacles(resolved),inputs.water_geometry.buffer(15),
                                  *(shape(g.geometry.model_dump()) for g in skeleton.primary_open_spaces)])
            for iteration in range(65):
                blocks, recipes, assignments, massing=placement(street_blocks)
                placed_gfa=sum(shape(f.geometry.model_dump()).area for b in massing.buildings for f in b.floors)
                assigned_zones={a['zone_id'] for a in assignments.values()}
                missing_zones={z['zone_id'] for z in manifest.zones}-assigned_zones
                from .formal_placement import TYPES
                missing_types=set(TYPES)-{b.type_id for b in massing.buildings}
                if ((placed_gfa+bounds['upper_m2'])/denominator >= .70 and not missing_zones and not missing_types) or iteration == 64: break
                trial_blocks, _, trial_assignments, trial=placement(street_blocks,float('inf'))
                targets=[shape(b.footprint.model_dump()) for b in trial.buildings
                         if (trial_assignments[b.id.removesuffix('-building')]['zone_id'] in missing_zones if missing_zones
                             else b.type_id in missing_types if missing_types else True)]
                options=aligned_access_paths(targets,skeleton.edges,angle=angle,site=resolved.site_geometry,obstacles=obstacles)
                lookahead=False
                missing_targets=targets
                if not options and missing_zones:
                    # A building-serving intermediate lane may unlock a route
                    # around retained footprints to the still-unserved zone.
                    # Each candidate still ends at an actual trial building.
                    targets=[shape(b.footprint.model_dump()) for b in trial.buildings]
                    options=[path for halo in (35.,15.,5.) for path in aligned_access_paths(
                        targets,skeleton.edges,angle=angle,site=resolved.site_geometry,obstacles=obstacles,halo_m=halo)]
                    lookahead=True
                if not options: break
                current=road_surface(skeleton.edges)
                remote=[p for g in targets for p in (g.geoms if g.geom_type=='MultiPolygon' else (g,)) if p.distance(current)>40]
                # Reward access to real trial footprints per metre, deterministic ties.
                def score(path):
                    surface=current.union(path.buffer(4.5/2))
                    gain=sum(g.area for g in remote if g.distance(surface)<=40)
                    return (-gain/path.length,path.length,path.wkb_hex)
                centreline=unary_union([shape(e.geometry.model_dump()) for e in skeleton.edges])
                used=max(0.,sum(shape(e.geometry.model_dump()).length for e in skeleton.edges)-original_road_length)
                options=[p for p in options if p.difference(current).length>1e-4 and score(p)[0]<0
                         and used+p.difference(centreline).length<=.25*original_road_length+1e-6]
                if lookahead:
                    def future_score(path):
                        edge=SimpleNamespace(geometry=SimpleNamespace(model_dump=lambda: mapping(path)),width_m=4.5)
                        future=sum(bool(aligned_access_paths([g],[*skeleton.edges,edge],angle=angle,
                                   site=resolved.site_geometry,obstacles=obstacles,first_only=True)) for g in missing_targets)
                        return (-future,*score(path))
                    near=sorted(options,key=lambda path:(min(g.distance(path) for g in missing_targets),path.length,path.wkb_hex))[:8]
                    shortest=sorted(options,key=lambda path:(path.length,path.wkb_hex))[:8]
                    options=list({p.wkb_hex:p for p in [*near,*shortest]}.values())
                    options.sort(key=future_score)
                else:
                    options.sort(key=score)
                chosen=None
                for option in options:
                    try:
                        trial_skeleton=rebuild_access_skeleton(candidate_context,strategy,resolved,base_skeleton,[*lanes,option])
                    except ValueError:
                        continue
                    chosen=option; skeleton=trial_skeleton; break
                if chosen is None: break
                lanes.append(chosen)
                served=road_surface(skeleton.edges)
                for b,cell in zip(trial.buildings,trial_blocks.blocks):
                    footprint=shape(b.footprint.model_dump())
                    envelope=shape(cell.geometry.model_dump())
                    if any(part.distance(served)<=40 for part in (footprint.geoms if footprint.geom_type=='MultiPolygon' else (footprint,))) and envelope.intersection(served).area<1e-6:
                        preferred_cells.add(envelope.wkb_hex)
                street_blocks=build_block_program(candidate_context,skeleton,geometry_value(resolved.site_geometry),strategy_id=id,ground_use='UNALLOCATED',
                    water_geometry=geometry_value(inputs.water_geometry),retained_buildings=retained)
            final_footprints=[shape(b.footprint.model_dump()) for b in massing.buildings]
            pruned=prune_access_lanes(base_skeleton.edges,lanes,final_footprints,
                                      validate=lambda kept: rebuild_access_skeleton(candidate_context,strategy,resolved,base_skeleton,kept))
            if len(pruned)!=len(lanes):
                lanes=pruned
                skeleton=rebuild_access_skeleton(candidate_context,strategy,resolved,base_skeleton,lanes)
                street_blocks=build_block_program(candidate_context,skeleton,geometry_value(resolved.site_geometry),strategy_id=id,ground_use='UNALLOCATED',
                    water_geometry=geometry_value(inputs.water_geometry),retained_buildings=retained)
            blocks=blocks.model_copy(update={'parent_skeleton_ref':street_blocks.parent_skeleton_ref,'input_refs':street_blocks.input_refs})
            massing=build_massing(candidate_context,blocks,next(iter(recipes.values())),retained,block_recipes=recipes)
            road_length=sum(shape(e.geometry.model_dump()).length for e in skeleton.edges)
            added_length=max(0.,road_length-original_road_length)
            row['access_lane_paths']=[{'geometry':mapping(path),'width_m':4.5,'length_m':path.length,
                                      'provenance':ROAD_ACCESS_PROVENANCE} for path in lanes]
            buildings=massing.buildings
            footprint=unary_union([shape(b.footprint.model_dump()) for b in buildings])
            roads=unary_union([shape(e.geometry.model_dump()).buffer(e.width_m/2,cap_style=2) for e in skeleton.edges]).intersection(resolved.site_geometry)
            new_gfa=sum(shape(f.geometry.model_dump()).area for b in buildings for f in b.floors)
            far=(new_gfa+bounds['upper_m2'])/denominator
            coverage=footprint.union(retained_union).intersection(resolved.site_geometry).area/denominator
            open_geom=resolved.site_geometry.difference(unary_union([footprint,retained_union,roads]))
            max_height=max(b.height_m for b in buildings)
            access=road_access_metrics([shape(b.footprint.model_dump()) for b in buildings],road_surface(skeleton.edges))
            failures=[]
            access_failure='road access: new building footprint exceeds 40 m from skeleton road surface'
            if access['accessible_count'] != access['total_new_buildings']: failures.append(access_failure)
            if far < .70: failures.append('quality FAR below 0.70')
            if open_geom.area/denominator < .4: failures.append('open space below 40 percent')
            if far>params['far_upper_bound']['value']: failures.append('FAR upper bound exceeded')
            if coverage>params['coverage_upper_bound']['value']: failures.append('coverage upper bound exceeded')
            if max_height>params['height_upper_bound_m']['value']: failures.append('new height upper bound exceeded')
            if footprint.intersection(inputs.water_geometry.buffer(15)).area>1e-6: failures.append('new massing enters waterfront band')
            if footprint.intersection(retained_union).area>1e-6: failures.append('new massing overlaps retained footprint')
            program={}
            zone_program={z['zone_id']:{} for z in manifest.zones}
            zone_totals={z['zone_id']:0. for z in manifest.zones}
            for b in buildings:
                assignment=assignments[b.id.removesuffix('-building')]
                for f in b.floors:
                    area=shape(f.geometry.model_dump()).area
                    program[f.use]=program.get(f.use,0)+area
                    zp=zone_program[assignment['zone_id']]
                    zp[f.use]=zp.get(f.use,0)+area
                    zone_totals[assignment['zone_id']]+=area
            if any(v <= 0 for v in zone_totals.values()): failures.append('zone has no assigned new GFA')
            if len({b.type_id for b in buildings}) < 4: failures.append('fewer than four dictionary types')
            massing=massing.model_copy(update={'validation':ValidationReport(
                geometry_status=StageStatus.PASS,topology_status=StageStatus.PASS,
                constraint_status=StageStatus.FAIL if failures else StageStatus.PASS,
                checks=tuple(ValidationCheck(check_id=name,status=StageStatus.FAIL if reason in failures else StageStatus.PASS,detail=reason) for name,reason in (
                    ('road_access',access_failure),('far_land_upper','FAR upper bound exceeded'),('coverage','coverage upper bound exceeded'),
                    ('new_height','new height upper bound exceeded'),('waterfront','new massing enters waterfront band'),('retained','new massing overlaps retained footprint'))),
                unknowns=(),failures=tuple(failures))})
            row.update(status=('INVALID' if access_failure in failures else 'FAIL') if failures else 'VALID',failure_reasons=failures, metrics=dict(road_access=access,road_length_m=road_length,original_road_length_m=original_road_length,added_spur_length_m=added_length,added_access_path_length_m=sum(p.length for p in lanes),added_length_budget_met=added_length<=.25*original_road_length,far=far,far_denominator=label,far_denominator_m2=denominator,
                new_gfa_m2=new_gfa,total_gfa_upper_m2=new_gfa+bounds['upper_m2'],total_gfa_lower_m2=new_gfa+bounds['lower_m2'],unallocated_share=program.get('UNALLOCATED',0)/new_gfa,dictionary_types=sorted({b.type_id for b in buildings}),retained_gfa_lower_m2=bounds['lower_m2'],retained_gfa_upper_m2=bounds['upper_m2'],coverage=coverage,
                highest_new_height_m=max_height,open_space_ratio=open_geom.area/denominator,open_space_preference_met=open_geom.area/denominator>=.4,program_gfa_m2=program,zone_uses=[dict(zone_id=z['zone_id'],preferred_use=z['target_use'],assigned_new_gfa_m2=zone_totals[z['zone_id']],floor_program_gfa_m2=zone_program[z['zone_id']],allocation_status='ASSUMED_FROM_PORTFOLIO') for z in manifest.zones]),
                recipe={k:v.model_dump(mode='json') for k,v in recipes.items()},building_assignments=assignments,orientation_deg=angle)
        except ValueError as exc:
            row['failure_reasons']=[str(exc)]
            failure_geometry=getattr(exc,'failure_geometry',None)
            row['failure_geometry']=None if failure_geometry is None else mapping(failure_geometry)
        features=[]
        def feature(g,role,**properties):
            return {'type':'Feature','geometry':mapping(g),'properties':{'role':role,**properties}}
        features.append(feature(inputs.design_area,'site_area',
            study_area_id=getattr(inputs,'study_area_id',None),
            study_area_geometry_sha256=getattr(inputs,'study_area_geometry_sha256',None)))
        features.append(feature(inputs.water_geometry,'water'))
        if row.get('failure_geometry') is not None:
            features.append(feature(shape(row['failure_geometry']),'failed_skeleton_geometry'))
        features.extend(feature(g,'retained',building_id=d.feature_id) for d,g,_ in inputs.retained_buildings)
        if skeleton:
            from urban_design.scenario_syntax import assumed_road_properties
            features.extend(feature(shape(e.geometry.model_dump()),'road',width_m=e.width_m,
                **assumed_road_properties(e.id)) for e in skeleton.edges)
            features.extend(feature(shape(s.geometry.model_dump()),'primary_open_space') for s in skeleton.primary_open_spaces)
        if street_blocks: features.extend(feature(shape(b.geometry.model_dump()),'street_block') for b in street_blocks.blocks)
        if blocks: features.extend(feature(shape(b.geometry.model_dump()),'massing_envelope') for b in blocks.blocks)
        if massing: features.extend(feature(shape(b.footprint.model_dump()),'new_building',height_m=b.height_m,use=b.use,floor_count=len(b.floors),type_id=b.type_id) for b in massing.buildings)
        row.update(geometry={'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:28992'}},'features':features},
            stages={name:None if stage is None else stage.model_dump(mode='json') for name,stage in [('skeleton',skeleton),('block_program',blocks),('massing',massing)]})
        row['result_hash_method']='canonical-json-sha256-v1 (exact output coordinates; no topology-changing quantization)'
        row['result_hash']='sha256:'+hashlib.sha256(json.dumps({k:v for k,v in row.items() if k!='stages'},sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        candidates.append(row)
    candidates.sort(key=lambda c:next(i for i,r in enumerate(RECIPES) if r[0]==c['recipe_id']))
    differences=[]
    for a,b in combinations([r for r in candidates if r['status']=='VALID'],2):
        flags={}
        for role in ('road','street_block','primary_open_space','new_building'):
            geoms=[unary_union([shape(f['geometry']).buffer(f['properties']['width_m']/2) if role=='road' else shape(f['geometry']) for f in r['geometry']['features'] if f['properties']['role']==role]) for r in (a,b)]
            flags[role]=geoms[0].symmetric_difference(geoms[1]).area/max(geoms[0].area,geoms[1].area,1e-9)
        # Program difference uses GFA shares, so changing total intensity alone
        # cannot masquerade as a different use allocation.
        pa,pb=a['metrics']['program_gfa_m2'],b['metrics']['program_gfa_m2']
        flags['program']=sum(abs(pa.get(k,0)/sum(pa.values())-pb.get(k,0)/sum(pb.values())) for k in set(pa)|set(pb))/2
        differences.append(dict(a=a['recipe_id'],b=b['recipe_id'],difference_ratios=flags,minimum_ratio=.1,
            substantive=max(flags['road'],flags['street_block'])>=.1 and sum(v>=.1 for v in flags.values())>=2))
    valid=[r for r in candidates if r['status']=='VALID']
    enough=any(len({r['family'] for r in trio})==3 and all(next(d['substantive'] for d in differences if {d['a'],d['b']}=={a['recipe_id'],b['recipe_id']}) for a,b in combinations(trio,2)) for trio in combinations(valid,3))
    enough = enough and all(d['substantive'] for d in differences) and len(set().union(*(set(r['metrics']['dictionary_types']) for r in valid))) >= 4
    # The label sits beside the recipe. It is not a method parameter, so it
    # does not enter skeleton or placement hashes.
    accepted_tradeoff={'label':'ACCEPTED_TRADEOFF_FOUNDER_2026-10-04','fallback_lanes_m':'201-242','road_length_increase':'+64-80%','open_space_change_percentage_points':-6.4,'note':'Founder accepted the south-distributor tradeoff on 2026-10-04. Lane simplification is later work.'}
    return dict(status='READY' if enough else 'INCOMPLETE',candidates=candidates,pairwise_differences=differences,valid_count=len(valid),blockers=[] if enough else ['quality gate: require three topology families, all valid pairs road/block >=0.1 plus two substantive differences, and four dictionary types'],
        authored_recipe_settings={'south_strip_collector':params['south_strip_collector'],'accepted_tradeoff':accepted_tradeoff,'road_access':{**params['road_access'],'method':'maximum of minimum component-footprint distances to centreline buffers including half-width','count_basis':'BuildingMassing records; every detached component must pass'},'envelope_m':[40,56],'cell_spacing_m':[44,60],'profile_adapter':'W5 footprint templates; D2 floor counts authored separately','retained_setback_m':3,'diversity_ratio':.1,'grid_alignment_deg':angle,'contact_interior_witness_m':1e-7,'contact_max_displacement_m':1e-6},
        routing_overlay_residue_m2=inputs.design_area.difference(inputs.water_geometry).area-resolved.site_geometry.area,
        commander_assumptions=[ROAD_ACCESS_BASIS+'; rule_m=40; ASSUMED_COMMANDER','#5 source-demolished GFA zero; footprint reserved','20m applies to new massing and total height of additions; existing observation unchanged'])
