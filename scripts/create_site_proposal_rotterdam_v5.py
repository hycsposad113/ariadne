#!/usr/bin/env python3
"""Build the append-only, source-backed M2-R06 Rotterdam M4H v5 package."""
from __future__ import annotations
import argparse, copy, hashlib, html, json, math, shutil, sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, shape, mapping
from shapely.ops import transform as shp_transform, unary_union, polygonize
from shapely.strtree import STRtree

SCRIPTS=Path(__file__).resolve().parent; ROOT=SCRIPTS.parent
if str(SCRIPTS) not in sys.path: sys.path.insert(0,str(SCRIPTS))
if str(ROOT/'src') not in sys.path: sys.path.insert(0,str(ROOT/'src'))
from create_site_proposal_rotterdam import _artifact, _points_text, _projector, _render_png, _geojson_feature
from create_site_proposal_rotterdam_v3 import classify_context
from urban_design.geometry import canonical_geometry_hash, polygon_area, polygon_perimeter, validate_geometry
from urban_design.models import Site, SiteStatus
from urban_design.site_proposal import SiteProposal, V2SourceRecord, canonical_json_bytes, sha256_file
from urban_design.store import ProjectStateStore

PROJECT_ID='rotterdam-m4h-pilot-project'; PROPOSAL_ID='site-proposal-rotterdam-m4h-v5'; CREATED='2026-09-15T15:00:00+00:00'; PRODUCER='urban-design-m2-r06-rotterdam-m4h/0.1'
PRIORITY=['background/land','water','public/open','context buildings','site buildings','roads/walk paths','rail','labels/markers','boundary']
TX=Transformer.from_crs(4326,28992,always_xy=True); INV=Transformer.from_crs(28992,4326,always_xy=True)
class ProposalBuildError(RuntimeError): pass

def write_json(path:Path,value:Mapping[str,Any])->None:
 path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(canonical_json_bytes(value))
def cp(src:Path,dst:Path)->None:
 if not src.is_file(): raise ProposalBuildError(f'missing retained source: {src}')
 dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
def _projected(g:Mapping[str,Any]): return shp_transform(TX.transform,shape(g))
def _source_timestamp(payload:Mapping[str,Any])->str:
 raw=str(payload.get('timeStamp') or CREATED)
 if raw.endswith('Z'): return raw[:-1]+'+00:00'
 return raw

def _parent_manifest(parent:Path,root:Path)->dict[str,Any]:
 files=[]
 for p in sorted(x for x in parent.rglob('*') if x.is_file()):
  files.append({'relative_path':p.relative_to(parent).as_posix(),'retained_path':(Path('parent-v4')/p.relative_to(parent)).as_posix(),'size_bytes':p.stat().st_size,'sha256':sha256_file(p)})
 result={'schema_version':'m2-r06-parent-v4-integrity','parent_id':'site-proposal-rotterdam-m4h-v4','files':files}; write_json(root/'parent-v4-integrity.json',result); return result

def _selected_union(v3_seed:Polygon, files:list[tuple[str,Path]]) -> tuple[Polygon,list[dict[str,Any]],dict[str,Any]]:
 """Select source surfaces by centroid in the retained v3 seed and union them.

 The union boundary is composed only of exact BGT polygon edges (possibly split by
 deterministic overlay noding). No seed coordinate is inserted into the result.
 """
 surfaces=[]; source_lines=[]; metadata=[]; selected_counts={}
 for collection,path in files:
  payload=json.loads(path.read_text(encoding='utf-8')); count=0
  source_hash=sha256_file(path)
  for feature in payload.get('features',[]):
   geom=feature.get('geometry') or {}
   try: projected=_projected(geom)
   except Exception: continue
   if projected.is_empty or not projected.is_valid or not projected.centroid.within(v3_seed): continue
   surfaces.append(projected); count+=1
   coords=(geom.get('coordinates') or [[]])[0]
   for seg_index,(a,b) in enumerate(zip(coords,coords[1:])):
    if a==b: continue
    source_lines.append(LineString([TX.transform(float(a[0]),float(a[1])),TX.transform(float(b[0]),float(b[1]))]))
    metadata.append({'source_dataset':'BGT','source_collection':collection,'source_feature_id':str(feature.get('id')),'source_ring_index':0,'source_segment':[seg_index,seg_index+1],'source_a':list(source_lines[-1].coords[0]),'source_b':list(source_lines[-1].coords[-1]),'function':(feature.get('properties') or {}).get('functie'),'source_sha256':source_hash})
  selected_counts[collection]=count
 if not surfaces: raise ProposalBuildError('no official BGT source surfaces have centroids inside the v3 seed')
 union=unary_union(surfaces)
 if union.geom_type!='Polygon':
  raise ProposalBuildError(f'official BGT surfaces did not form one connected Polygon perimeter ({union.geom_type})')
 if not union.is_valid: raise ProposalBuildError('BGT surface union is invalid')
 try:
  validate_geometry(mapping(union))
 except Exception as exc:
  raise ProposalBuildError('official BGT surfaces do not form a strict-valid closed perimeter; M2-R06 is BLOCKED') from exc
 # Map every derived exterior segment back to one original source segment.
 # Deduplicate coincident segments before indexing. BGT returns multiple
 # function observations for the same physical edge; retaining the
 # lexicographically first provenance record makes lookup deterministic and
 # keeps the offline rebuild bounded.
 unique: dict[tuple[tuple[float, float], tuple[float, float]], tuple[LineString, dict[str, Any]]] = {}
 for line, meta in zip(source_lines, metadata):
  key = tuple(sorted(((round(float(line.coords[0][0]), 7), round(float(line.coords[0][1]), 7)),
                      (round(float(line.coords[-1][0]), 7), round(float(line.coords[-1][1]), 7)))))
  if key not in unique or (meta['source_collection'], meta['source_feature_id'], meta['source_segment']) < (unique[key][1]['source_collection'], unique[key][1]['source_feature_id'], unique[key][1]['source_segment']):
   unique[key] = (line, meta)
 source_lines = [item[0] for item in unique.values()]
 metadata = [item[1] for item in unique.values()]
 tree=STRtree(source_lines); edges=[]; misses=[]
 for edge_index,(a,b) in enumerate(zip(union.exterior.coords,union.exterior.coords[1:])):
  target=LineString([a,b]); candidates=[]
  for raw_idx in tree.query(target):
   idx=int(raw_idx); line=source_lines[idx]
   if line.distance(target)<=1e-6 and line.buffer(1e-7).covers(target):
    candidates.append((metadata[idx]['source_collection'],metadata[idx]['source_feature_id'],metadata[idx]['source_segment'],idx,line))
  if not candidates:
   for raw_idx in tree.query(target.buffer(1e-7)):
    idx=int(raw_idx); line=source_lines[idx]
    if line.distance(target)<=1e-6 and line.buffer(1e-7).covers(target):
     candidates.append((metadata[idx]['source_collection'],metadata[idx]['source_feature_id'],metadata[idx]['source_segment'],idx,line))
  if not candidates:
   misses.append(edge_index); continue
  _,_,_,idx,line=sorted(candidates,key=lambda x:(x[0],x[1],x[2]))[0]; meta=metadata[idx]
  sa,sb=tuple(meta['source_a']),tuple(meta['source_b']); direct=math.dist(a,sa)+math.dist(b,sb); reverse=math.dist(a,sb)+math.dist(b,sa)
  # project points directly through nearest endpoint distance along source segment
  def along(point): return line.project(shape({'type':'Point','coordinates':list(point)}))
  ia,ib=along(a),along(b); direction='FORWARD' if ia<=ib else 'REVERSE'
  edges.append({'edge_index':edge_index,'source_dataset':meta['source_dataset'],'source_collection':meta['source_collection'],'source_feature_id':meta['source_feature_id'],'source_ring_index':meta['source_ring_index'],'source_segment':meta['source_segment'],'direction':direction,'relationship':'SITE-FACING_ROAD_EDGE' if meta['source_collection']=='wegdeel' else 'SITE-FACING_SUPPLEMENTARY_EDGE','claim_status':'SOURCE_GEOMETRY_SEGMENT','physical_edge_claim':True,'derived_from_union':True,'derived_subsegment':bool(target.length < line.length-1e-6),'source_interval_m':[round(float(ia),9),round(float(ib),9)],'start_epsg28992':list(a),'end_epsg28992':list(b),'measured_distance_m':float(line.distance(target)),'method':'deterministic unary union of official BGT polygon surfaces selected by centroid inside retained v3 seed; exterior subsegments traced to retained source ring segment'})
 if misses: raise ProposalBuildError(f'BGT source lookup failed for derived boundary edges: {misses[:5]}')
 details={'selection_rule':'BGT polygon centroid strictly inside retained v3 seed; all official supplementary collections are bounded by the same seed bbox','selected_feature_counts':selected_counts,'selected_surface_count':len(surfaces),'union_component_count':1,'selected_component_area_m2':union.area,'selected_component_bounds_epsg28992':list(union.bounds),'boundary_segment_count':len(edges),'boundary_source_collections':sorted(selected_counts),'source_coordinate_policy':'all output boundary vertices are generated from deterministic BGT polygon overlay and traced to a retained source ring segment; no hand coordinates, OSM centerlines, or human connectors'}
 return union,edges,details


FACE_OVERLAP_THRESHOLD = 0.5
MAX_SOURCE_HOLE_FILL_AREA_M2 = 10.0
# OSM building ways and BAG footprints are independently surveyed.  A matched
# ref:bag pair is reconciled only when the discrepancy is within a documented
# source-registration tolerance; otherwise the raw OSM geometry remains a hard
# crossing failure.
MAX_OSM_BAG_DISCREPANCY_AREA_M2 = 1.0
MAX_OSM_BAG_HAUSDORFF_M = 0.01
ROAD_LIKE_COLLECTIONS = frozenset({'wegdeel', 'ondersteunendwegdeel'})


def _source_face_union(v3_seed: Polygon, files: list[tuple[str, Path]]) -> tuple[Polygon, list[dict[str, Any]], dict[str, Any]]:
 """Build a land-face candidate from noded official BGT boundaries.

 The retained BGT responses contain historical observations that overlap one
 another.  Unioning those surfaces directly can produce a self-intersecting
 strip.  This construction instead nodes every boundary from a source feature
 intersecting the v3 seed, polygonizes the resulting linework, and selects
 faces by one documented overlap rule.  It never inserts a seed coordinate or
 chooses a largest component; a disconnected result fails closed.
 """
 source_lines: list[LineString] = []
 metadata: list[dict[str, Any]] = []
 selected_counts: dict[str, int] = {}
 for collection, path in files:
  payload = json.loads(path.read_text(encoding="utf-8"))
  source_hash = sha256_file(path)
  count = 0
  for feature in payload.get("features", []):
   geometry = feature.get("geometry") or {}
   try:
    projected = _projected(geometry)
   except Exception:
    continue
   if projected.is_empty or not projected.intersects(v3_seed):
    continue
   count += 1
   coordinates = geometry.get("coordinates") or []
   if geometry.get("type") == "Polygon":
    rings = [coordinates[0]] if coordinates and coordinates[0] else []
   elif geometry.get("type") == "MultiPolygon":
    rings = [polygon[0] for polygon in coordinates if polygon and polygon[0]]
   else:
    rings = []
   for ring_index, ring in enumerate(rings):
    for segment_index, (a, b) in enumerate(zip(ring, ring[1:])):
     if a == b:
      continue
     source_lines.append(LineString([
      TX.transform(float(a[0]), float(a[1])),
      TX.transform(float(b[0]), float(b[1])),
     ]))
     metadata.append({
      "source_dataset": "BGT",
      "source_collection": collection,
      "source_feature_id": str(feature.get("id")),
      "source_ring_index": ring_index,
      "source_segment": [segment_index, segment_index + 1],
      "source_a": list(source_lines[-1].coords[0]),
      "source_b": list(source_lines[-1].coords[-1]),
      "function": (feature.get("properties") or {}).get("functie"),
      "source_sha256": source_hash,
     })
  selected_counts[collection] = count
  # Source feature counts are retained in ``selected_counts``.
 if not source_lines:
  raise ProposalBuildError("no official BGT polygon boundaries intersect the retained v3 seed")
 noded = unary_union(source_lines)
 faces = [face for face in polygonize(noded) if face.area > 1e-9]
 # Polygonization result is recorded in ``details`` below.
 selected = [
  face for face in faces
  if face.intersection(v3_seed).area / face.area >= FACE_OVERLAP_THRESHOLD
 ]
 if not selected:
  raise ProposalBuildError("official BGT boundaries produced no seed-overlapping land faces")
 candidate = unary_union(selected).buffer(0)
 if candidate.geom_type != "Polygon":
  raise ProposalBuildError(
   f"official BGT face selection did not form one connected Polygon perimeter ({candidate.geom_type})"
  )
 holes_filled: list[dict[str, Any]] = []
 for interior in list(candidate.interiors):
  hole = Polygon(interior)
  if hole.area > MAX_SOURCE_HOLE_FILL_AREA_M2:
   raise ProposalBuildError(
    f"official BGT face candidate contains an unbounded {hole.area:.6f} m2 interior hole"
   )
  point = hole.representative_point()
  # Polygonizer can leave a representative point exactly on a noded vertex;
  # ``covers`` plus a tiny deterministic distance check handles that boundary
  # case without introducing a non-source coordinate.
  source_face = next((face for face in faces if face.covers(point) or face.distance(point) <= 1e-6), None)
  if source_face is None:
   raise ProposalBuildError("official BGT face candidate hole has no source-defined closing face")
  candidate = unary_union([candidate, source_face]).buffer(0)
  holes_filled.append({"area_m2": hole.area, "centroid_epsg28992": [hole.centroid.x, hole.centroid.y]})
 candidate = candidate.buffer(0)
 if candidate.geom_type == "Polygon" and candidate.interiors:
  remaining = [Polygon(interior).area for interior in candidate.interiors]
  if any(area > 1e-6 for area in remaining):
   raise ProposalBuildError("official BGT face candidate remained non-simple after source-defined hole closure")
  # Degenerate zero-area rings can survive GEOS noding.  Dropping only those
  # rings keeps the source-derived exterior unchanged and deterministic.
  candidate = Polygon(candidate.exterior)
 if candidate.geom_type != "Polygon" or candidate.interiors:
  raise ProposalBuildError("official BGT face candidate remained non-simple after source-defined hole closure")
 try:
  validate_geometry(mapping(candidate))
 except Exception as exc:
  raise ProposalBuildError("official BGT face candidate is not strict-valid") from exc

 raw_source_boundary_segment_count = len(source_lines)
 # Deduplicate coincident source segments while retaining deterministic
 # provenance.  Historical BGT observations often describe the same edge.
 unique: dict[tuple[tuple[float, float], tuple[float, float]], tuple[LineString, dict[str, Any]]] = {}
 for line, item in zip(source_lines, metadata):
  key = tuple(sorted((
   (round(float(line.coords[0][0]), 7), round(float(line.coords[0][1]), 7)),
   (round(float(line.coords[-1][0]), 7), round(float(line.coords[-1][1]), 7)),
  )))
  previous = unique.get(key)
  if previous is None or (
   item["source_collection"], item["source_feature_id"], item["source_ring_index"], item["source_segment"]
  ) < (
   previous[1]["source_collection"], previous[1]["source_feature_id"], previous[1]["source_ring_index"], previous[1]["source_segment"]
  ):
   unique[key] = (line, item)
 source_lines = [entry[0] for entry in unique.values()]
 metadata = [entry[1] for entry in unique.values()]
 tree = STRtree(source_lines)
 edges: list[dict[str, Any]] = []
 misses: list[int] = []
 for edge_index, (a, b) in enumerate(zip(candidate.exterior.coords, candidate.exterior.coords[1:])):
  target = LineString([a, b])
  candidates: list[int] = []
  for raw_index in tree.query(target.buffer(1e-7)):
   index = int(raw_index)
   line = source_lines[index]
   if line.distance(target) <= 1e-6 and line.buffer(1e-7).covers(target):
    candidates.append(index)
  if not candidates:
   misses.append(edge_index)
   continue
  index = sorted(
   candidates,
   key=lambda item: (
    metadata[item]["source_collection"],
    metadata[item]["source_feature_id"],
    metadata[item]["source_ring_index"],
    metadata[item]["source_segment"],
   ),
  )[0]
  item = metadata[index]
  line = source_lines[index]
  start = tuple(item["source_a"])
  end = tuple(item["source_b"])
  ia = line.project(Point(a))
  ib = line.project(Point(b))
  edges.append({
   "edge_index": edge_index,
   "source_dataset": item["source_dataset"],
   "source_collection": item["source_collection"],
   "source_feature_id": item["source_feature_id"],
   "source_ring_index": item["source_ring_index"],
   "source_segment": item["source_segment"],
   "direction": "FORWARD" if ia <= ib else "REVERSE",
   "relationship": "SITE-FACING_ROAD_EDGE" if item["source_collection"] == "wegdeel" else "SITE-FACING_SUPPLEMENTARY_EDGE",
   "claim_status": "SOURCE_GEOMETRY_SEGMENT",
   "physical_edge_claim": True,
   "derived_from_union": True,
   "derived_subsegment": bool(target.length < line.length - 1e-6),
   "source_interval_m": [round(float(ia), 9), round(float(ib), 9)],
   "start_epsg28992": list(a),
   "end_epsg28992": list(b),
   "measured_distance_m": float(line.distance(target)),
   "method": "deterministic polygonized BGT boundary faces selected by seed overlap; exterior subsegments traced to retained source ring segment",
  })
 if misses:
  raise ProposalBuildError(f"BGT source lookup failed for derived face boundary edges: {misses[:5]}")
 # A supplementary collection may close a local junction, but it cannot
 # silently substitute for a named road around an extended perimeter.  A
 # bounded run is therefore a contiguous supplementary run bracketed on both
 # ends by road-like BGT collections.  Walk the ring from a label transition
 # so a run crossing the closing vertex is represented once, without inventing
 # a geometric length threshold.
 runs: list[dict[str, Any]] = []
 labels = [edge["source_collection"] for edge in edges]
 lengths = [math.dist(edge["start_epsg28992"], edge["end_epsg28992"]) for edge in edges]
 if labels:
  start = next((index for index, label in enumerate(labels) if label != labels[index - 1]), 0)
  ordered = [(start + offset) % len(labels) for offset in range(len(labels))]
  run_indices = [ordered[0]]
  for edge_index in ordered[1:]:
   if labels[edge_index] != labels[run_indices[0]]:
    following = labels[edge_index]
    run_start = run_indices[0]
    run_end = run_indices[-1]
    runs.append({
     "source_collection": labels[run_start],
     "edge_start": run_start,
     "edge_end": run_end,
     "edge_count": len(run_indices),
     "length_m": sum(lengths[item] for item in run_indices),
     "previous_source_collection": labels[(run_start - 1) % len(labels)],
     "next_source_collection": following,
     "bound_by_road_edges": labels[(run_start - 1) % len(labels)] in ROAD_LIKE_COLLECTIONS and following in ROAD_LIKE_COLLECTIONS,
    })
    run_indices = [edge_index]
   else:
    run_indices.append(edge_index)
  if run_indices:
   run_start = run_indices[0]
   runs.append({
    "source_collection": labels[run_start],
    "edge_start": run_start,
    "edge_end": run_indices[-1],
    "edge_count": len(run_indices),
    "length_m": sum(lengths[item] for item in run_indices),
    "previous_source_collection": labels[(run_start - 1) % len(labels)],
    "next_source_collection": labels[(run_indices[-1] + 1) % len(labels)],
    "bound_by_road_edges": labels[(run_start - 1) % len(labels)] in ROAD_LIKE_COLLECTIONS and labels[(run_indices[-1] + 1) % len(labels)] in ROAD_LIKE_COLLECTIONS,
   })
 # The source collection can change inside one official junction (for example
 # begroeidterreindeel -> onbegroeidterreindeel -> waterdeel).  Treat that
 # whole contiguous non-road span as one supplementary run; otherwise a
 # collection transition would be mistaken for an unbounded perimeter.  Start
 # at a road-like edge so a supplementary run crossing the closing vertex is
 # represented once and supporting-road edges are classified as roads.
 supplementary_runs: list[dict[str, Any]] = []
 if labels:
  road_start = next((index for index, label in enumerate(labels) if label in ROAD_LIKE_COLLECTIONS), 0)
  road_ordered = [(road_start + offset) % len(labels) for offset in range(len(labels))]
  current = [road_ordered[0]]
  current_is_road = labels[current[0]] in ROAD_LIKE_COLLECTIONS
  grouped: list[tuple[bool, list[int]]] = []
  for edge_index in road_ordered[1:]:
   edge_is_road = labels[edge_index] in ROAD_LIKE_COLLECTIONS
   if edge_is_road != current_is_road:
    grouped.append((current_is_road, current))
    current = [edge_index]
    current_is_road = edge_is_road
   else:
    current.append(edge_index)
  grouped.append((current_is_road, current))
  for is_road_like, run_indices in grouped:
   if is_road_like:
    continue
   run_start = run_indices[0]
   run_end = run_indices[-1]
   previous = labels[(run_start - 1) % len(labels)]
   following = labels[(run_end + 1) % len(labels)]
   source_collections = []
   for edge_index in run_indices:
    if labels[edge_index] not in source_collections:
     source_collections.append(labels[edge_index])
   supplementary_runs.append({
    "source_collection": source_collections[0] if len(source_collections) == 1 else "supplementary",
    "source_collections": source_collections,
    "edge_start": run_start,
    "edge_end": run_end,
    "edge_count": len(run_indices),
    "length_m": sum(lengths[item] for item in run_indices),
    "previous_source_collection": previous,
    "next_source_collection": following,
    "bound_by_road_edges": previous in ROAD_LIKE_COLLECTIONS and following in ROAD_LIKE_COLLECTIONS,
   })
 unbounded_supplement_runs = [run for run in supplementary_runs if not run["bound_by_road_edges"]]
 details = {
  "selection_rule": "polygonize all retained official BGT polygon boundaries intersecting the retained v3 seed; select faces with seed-overlap ratio >= 0.5",
  "face_overlap_threshold": FACE_OVERLAP_THRESHOLD,
  "selected_feature_counts": selected_counts,
  "selected_source_polygon_count": sum(selected_counts.values()),
  "source_boundary_segment_count": raw_source_boundary_segment_count,
  "deduplicated_source_boundary_segment_count": len(source_lines),
  "polygonized_face_count": len(faces),
  "selected_face_count": len(selected),
  "source_defined_holes_filled": holes_filled,
  "selected_component_area_m2": candidate.area,
  "selected_component_bounds_epsg28992": list(candidate.bounds),
  "union_component_count": 1,
  "boundary_segment_count": len(edges),
  "contiguous_source_runs": runs,
  "supplementary_bound_rule": "every contiguous supplementary exterior run (possibly spanning multiple official supplementary collections) must be bracketed on both ends by road-like BGT edges (wegdeel or ondersteunendwegdeel); no numerical length threshold is used",
  "supplementary_runs": supplementary_runs,
  "max_supplementary_run_length_m": max((run["length_m"] for run in supplementary_runs), default=0.0),
  "supplementary_runs_bounded": not unbounded_supplement_runs,
  "unbounded_supplement_runs": unbounded_supplement_runs,
  "boundary_source_collections": sorted(selected_counts),
  "source_coordinate_policy": "all output boundary vertices are generated from deterministic BGT polygon overlay and traced to a retained source ring segment; no hand coordinates, OSM centerlines, or human connectors",
 }
 return candidate, edges, details


def _canonical_osm_building_audit(
 display: Mapping[str, Any], bag: Mapping[str, Any], boundary: Polygon
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
 """Audit context building crossings with deterministic BAG duplicate matching.

 OSM context ways carrying ``ref:bag`` are reconciled to the retained BAG
 footprint for the physical crossing decision.  The raw OSM residual is
 retained in the returned audit record, and a discrepancy outside the source
 registration tolerance fails closed.
 """
 bag_by_id = _bag_by_id(bag)
 crossings: list[dict[str, Any]] = []
 reconciliations: list[dict[str, Any]] = []
 for feature in display.get("features", []):
  properties = feature.get("properties") or {}
  if not properties.get("building"):
   continue
  raw_geometry = shape(feature.get("geometry") or {})
  bag_id = str(properties.get("ref:bag") or "")
  bag_feature = bag_by_id.get(bag_id)
  if bag_feature is not None:
   bag_geometry = _projected(bag_feature.get("geometry") or {})
   discrepancy_area = raw_geometry.symmetric_difference(bag_geometry).area
   discrepancy_distance = raw_geometry.hausdorff_distance(bag_geometry)
   raw_area = raw_geometry.intersection(boundary).area
   canonical_area = bag_geometry.intersection(boundary).area
   raw_partial = raw_area > 1e-7 and raw_area < raw_geometry.area - 1e-5
   canonical_partial = canonical_area > 1e-7 and canonical_area < bag_geometry.area - 1e-5
   exceeds_tolerance = discrepancy_area > MAX_OSM_BAG_DISCREPANCY_AREA_M2 or discrepancy_distance > MAX_OSM_BAG_HAUSDORFF_M
   if exceeds_tolerance and (raw_partial or canonical_partial):
    crossings.append({
     "source_id": str(feature.get("id")),
     "reason": "OSM/BAG duplicate geometry discrepancy exceeds reconciliation tolerance",
     "ref_bag": bag_id,
     "discrepancy_area_m2": discrepancy_area,
     "hausdorff_distance_m": discrepancy_distance,
    })
    continue
   # Reconcile the physical crossing against BAG only within the explicit
   # registration tolerance.  A larger discrepancy is retained as an audit
   # fact, but when both footprints are wholly inside/outside it cannot alter
   # the crossing result and therefore does not block the proposal.
   audit_geometry = bag_geometry if not exceeds_tolerance else raw_geometry
   if raw_partial and not canonical_partial and not exceeds_tolerance:
    reconciliations.append({
     "source_id": str(feature.get("id")),
     "ref_bag": bag_id,
     "raw_osm_intersection_area_m2": raw_area,
     "raw_osm_footprint_area_m2": raw_geometry.area,
     "canonical_bag_intersection_area_m2": canonical_area,
     "canonical_bag_footprint_area_m2": bag_geometry.area,
     "discrepancy_area_m2": discrepancy_area,
     "hausdorff_distance_m": discrepancy_distance,
     "decision": "CANONICAL_BAG_DUPLICATE_FOR_PHYSICAL_CROSSING",
    })
  else:
   audit_geometry = raw_geometry
  area = audit_geometry.intersection(boundary).area
  if area > 1e-7 and area < audit_geometry.area - 1e-5:
   crossings.append({
    "source_id": str(feature.get("id")),
    "reason": "building interior crosses proposed boundary",
    "ref_bag": bag_id or None,
   })
 return crossings, reconciliations


def _bag_by_id(bag: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
 """Index retained BAG footprints by their canonical identifier."""
 out: dict[str, Mapping[str, Any]] = {}
 for feature in bag.get("features", []):
  identifier = str((feature.get("properties") or {}).get("identificatie") or "")
  if identifier:
   out[identifier] = feature
 return out


def _display_audit_geometry(feature: Mapping[str, Any], bag_by_id: Mapping[str, Mapping[str, Any]]) -> tuple[Any, dict[str, Any] | None]:
 """Return classification geometry plus deterministic OSM/BAG audit facts."""
 raw_geometry = shape(feature.get("geometry") or {})
 properties = feature.get("properties") or {}
 bag_id = str(properties.get("ref:bag") or "")
 bag_feature = bag_by_id.get(bag_id)
 if bag_feature is None:
  return raw_geometry, None
 bag_geometry = _projected(bag_feature.get("geometry") or {})
 discrepancy_area = raw_geometry.symmetric_difference(bag_geometry).area
 discrepancy_distance = raw_geometry.hausdorff_distance(bag_geometry)
 exceeds_tolerance = discrepancy_area > MAX_OSM_BAG_DISCREPANCY_AREA_M2 or discrepancy_distance > MAX_OSM_BAG_HAUSDORFF_M
 # Keep the raw OSM feature for display when the duplicate is too different
 # to reconcile; the crossing audit fails if either footprint is partial.
 geometry = raw_geometry if exceeds_tolerance else bag_geometry
 return geometry, {
  "canonical_bag_id": bag_id,
  "canonical_geometry_source": "BAG" if not exceeds_tolerance else "OSM_CONTEXT_TOLERANCE_EXCEEDED",
  "osm_geometry_sha256": canonical_geometry_hash(mapping(raw_geometry)),
  "bag_geometry_sha256": canonical_geometry_hash(mapping(bag_geometry)),
  "osm_bag_discrepancy_area_m2": discrepancy_area,
  "osm_bag_hausdorff_distance_m": discrepancy_distance,
  "osm_bag_reconciliation_status": "WITHIN_TOLERANCE" if not exceeds_tolerance else "TOLERANCE_EXCEEDED_NO_CROSSING_CHANGE",
 }

def _building_crossings(boundary:Polygon,bag:Mapping[str,Any])->list[str]:
 out=[]
 for f in bag.get('features',[]):
  try:g=_projected(f.get('geometry') or {})
  except Exception as exc: raise ProposalBuildError('BAG pand contains unreadable geometry') from exc
  if not g.is_valid or g.is_empty: raise ProposalBuildError('BAG pand contains invalid/empty geometry')
  area=g.intersection(boundary).area
  # A footprint fully covered by the boundary may touch its edge; only a
  # positive-area partial intersection is a building-interior crossing.
  if area>1e-7 and area < g.area-1e-5:
   out.append(str((f.get('properties') or {}).get('identificatie') or f.get('id') or 'unknown'))
 return sorted(set(out))

def _intent_metrics(seed:Polygon,candidate:Polygon,display:Mapping[str,Any])->dict[str,Any]:
 return {'seed_area_m2':seed.area,'candidate_area_m2':candidate.area,'intersection_area_m2':seed.intersection(candidate).area,'symmetric_difference_area_m2':seed.symmetric_difference(candidate).area,'area_ratio_candidate_to_seed':candidate.area/seed.area,'relative_area_delta':abs(candidate.area-seed.area)/seed.area,'seed_building_centroid_count':sum((f.get('properties') or {}).get('display_layer')=='site buildings' for f in display.get('features',[])),'candidate_building_centroid_count':sum((f.get('properties') or {}).get('display_layer')=='site buildings' for f in display.get('features',[]))}

def _render_v5(path:Path,boundary:Mapping[str,Any],display:Mapping[str,Any],viewport,*,cross_count:int):
 from create_site_proposal_rotterdam_v3 import render_svg
 render_svg(path,boundary,display,viewport,created_at=CREATED,cross_count=cross_count)
 text=path.read_text(encoding='utf-8')
 for old,new in {'MAP REVIEW v3':'MAP REVIEW v5','site-proposal-rotterdam-m4h-v3':'site-proposal-rotterdam-m4h-v5','generated 2026-09-15T12:00:00+00:00':f'generated {CREATED}','CRS EPSG:28992 · one v3 decision map':'CRS EPSG:28992 · one v5 decision map','Boundary source: retained OSM geometry segments plus explicit human-intent review connector.':'Boundary source: BGT site-facing polygon edges; supplementary BGT surfaces are retained and traced; no OSM centreline or human connector is used.','No clipping of buildings; crossings are reported.':'No clipping of buildings; building-interior crossing count: 0.'}.items(): text=text.replace(old,new)
 path.write_text(text,encoding='utf-8')
 return {'viewbox':[0,0,1240,850],'frame':[44.0,100.0,790.0,590.0],'layer_order':['layer-background','layer-water','layer-public-space','layer-context-buildings','layer-site-buildings','layer-roads','layer-rail','layer-markers','layer-boundary']}

def _diagnostic_svg(path:Path,seed:Polygon,candidate:Polygon,edges:list[dict[str,Any]],display:Mapping[str,Any],viewport):
 frame=(44.0,100.0,790.0,590.0); project,_=_projector(tuple(viewport),frame)
 def pts(g): return _points_text([(float(x),float(y)) for x,y in g.exterior.coords],project)
 blue=''.join(f'<line x1="{project(tuple(e["start_epsg28992"]))[0]:.3f}" y1="{project(tuple(e["start_epsg28992"]))[1]:.3f}" x2="{project(tuple(e["end_epsg28992"]))[0]:.3f}" y2="{project(tuple(e["end_epsg28992"]))[1]:.3f}" />' for e in edges)
 svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="850" viewBox="0 0 1240 850"><rect width="1240" height="850" fill="#f7f7f7"/><text x="44" y="42" font-family="sans-serif" font-size="23" font-weight="700">Rotterdam M4H — M2-R06 boundary diagnostic</text><text x="44" y="67" font-family="sans-serif" font-size="12" fill="#4a5054">Diagnostic only · v3 seed dashed gray · v5 proposed red · official BGT perimeter edges fine blue · PROPOSED</text><rect x="44" y="100" width="790" height="590" fill="#fff" stroke="#aab0b3"/><polyline points="{pts(seed)}" fill="none" stroke="#9aa3a8" stroke-width="1.2" stroke-dasharray="6 4"/><polyline points="{pts(candidate)}" fill="none" stroke="#d62728" stroke-width="1.4"/>
<g fill="none" stroke="#1976d2" stroke-width="0.35" opacity="0.9">{blue}</g><g font-family="sans-serif" font-size="12" fill="#202427"><text x="860" y="145">v3 seed — light gray dashed</text><text x="860" y="175">v5 proposal — red solid</text><text x="860" y="205">BGT source edges — fine blue</text><text x="44" y="745">Every blue segment is traced to a retained BGT polygon ring/segment; this overlay is not an approval map.</text><text x="44" y="770">CRS EPSG:28992 · generated {CREATED} · no OSM centreline or human connector</text></g></svg>'''
 path.write_text(svg,encoding='utf-8')

def build_rotterdam_v5(output_dir:str|Path,*,v4_dir:str|Path,wegdeel_source:str|Path|None=None,supplementary_sources:Mapping[str,str|Path],offline:bool=True)->SiteProposal:
 if not offline: raise ProposalBuildError('v5 builder is offline-only')
 root=Path(output_dir).resolve(); v4=Path(v4_dir).resolve()
 if root.exists() and any(root.iterdir()): raise ProposalBuildError(f'refusing to overwrite non-empty output: {root}')
 if not (v4/'site-proposal.json').is_file(): raise ProposalBuildError('retained v4 package is required')
 required=['ondersteunendwegdeel','onbegroeidterreindeel','waterdeel','begroeidterreindeel']
 if set(supplementary_sources)!=set(required): raise ProposalBuildError(f'exactly supplementary collections required: {required}')
 root.mkdir(parents=True); shutil.copytree(v4,root/'parent-v4'); _parent_manifest(root/'parent-v4',root)
 for rel in ['context-display-epsg28992-v2.geojson','sources/raw/pdok-rotterdam-municipality-v2.geojson']:
  cp(root/'parent-v4'/rel,root/rel)
 bgt_src=Path(wegdeel_source).resolve() if wegdeel_source is not None else v4/'sources/raw/pdok-bgt-wegdeel-m4h.json'; bag_src=v4/'sources/raw/pdok-bag-pand-m4h.json'; bgt_dst=root/'sources/raw/pdok-bgt-wegdeel-m4h.json'; bag_dst=root/'sources/raw/pdok-bag-pand-m4h.json'; cp(bgt_src,bgt_dst); cp(bag_src,bag_dst)
 supplementary=[]
 for collection in required:
  dst=root/f'sources/raw/pdok-bgt-{collection}-m4h.json'; cp(Path(supplementary_sources[collection]),dst); supplementary.append((collection,dst))
 parent=json.loads((root/'parent-v4/site-proposal.json').read_text()); seed=shape(json.loads((root/'parent-v4/parent-v3/site-proposal.json').read_text())['geometry']); bag=json.loads(bag_dst.read_text()); bgt=json.loads(bgt_dst.read_text())
 source_files=[('wegdeel',bgt_dst),*supplementary]; candidate_geom,edges,selection=_source_face_union(seed,source_files)
 if not selection['supplementary_runs_bounded']:
  raise ProposalBuildError(f"supplementary BGT boundary run is not bracketed by road-like BGT edges: {selection['unbounded_supplement_runs']}")
 boundary=json.loads(json.dumps(mapping(candidate_geom))); validate_geometry(boundary)
 # Reclassify v3 context with full-coverage tolerance and reconcile OSM
 # building ways carrying ref:bag against retained BAG footprints.  The raw
 # OSM geometry remains the displayed feature; BAG is used only for the
 # deterministic physical crossing and centroid decision when the duplicate
 # is within the explicit registration tolerance.
 display=classify_context(root/'context-display-epsg28992-v2.geojson',candidate_geom)
 bag_by_id=_bag_by_id(bag)
 true_cross,reconciliations=_canonical_osm_building_audit(display,bag,candidate_geom)
 for f in display['features']:
  props=f.get('properties') or {}
  if not props.get('building'): continue
  audit_geometry,audit=_display_audit_geometry(f,bag_by_id)
  if audit:
   props.update(audit)
  inter=audit_geometry.intersection(candidate_geom).area
  full=inter >= audit_geometry.area-1e-5
  if full and audit_geometry.centroid.within(candidate_geom):
   props['display_layer']='site buildings'; props.pop('cross_boundary',None)
  elif full:
   props['display_layer']='context buildings'; props.pop('cross_boundary',None)
  elif inter>1e-7:
   props['cross_boundary']=True
 display['cross_boundary_buildings']=true_cross
 display['building_crossing_count']=len(true_cross)
 display['osm_building_crossing_count']=len(true_cross)
 display['osm_raw_geometry_reconciliation_count']=len(reconciliations)
 display['osm_raw_geometry_reconciliations']=reconciliations
 display['building_crossing_method']='BAG canonical duplicate reconciliation with raw OSM residual retained; unmatched OSM building footprints are hard failures'
 display['site_building_count']=sum((f.get('properties') or {}).get('display_layer')=='site buildings' for f in display['features'])
 if true_cross: raise ProposalBuildError(f'context building crossings: {true_cross}')
 display_path=root/'display-data-v5.geojson'; write_json(display_path,display)
 bag_cross=_building_crossings(candidate_geom,bag)
 if bag_cross: raise ProposalBuildError(f'BAG building interior crossings: {bag_cross}')
 road_union=unary_union([_projected(f['geometry']) for f in bgt.get('features',[]) if _projected(f['geometry']).intersects(seed)])
 metrics=_intent_metrics(seed,candidate_geom,display); metrics['road_surface_union_area_m2']=road_union.area; metrics['road_surface_overlap_area_m2']=candidate_geom.intersection(road_union).area; metrics['road_surface_overlap_ratio']=metrics['road_surface_overlap_area_m2']/candidate_geom.area
 if metrics['road_surface_overlap_ratio']>=0.75: raise ProposalBuildError('candidate interior is road-surface dominant')
 boundary_path=root/'boundary-epsg28992-v5.geojson'; write_json(boundary_path,_geojson_feature(boundary,{'status':'PROPOSED','option':'A','source':'BGT site-facing road and bounded supplementary polygon edges','source_edge_claim':'BGT'},crs='EPSG:28992'))
 wgs={'type':'Polygon','coordinates':[[list(INV.transform(x,y)) for x,y in candidate_geom.exterior.coords]]}; wgs_path=root/'boundary-wgs84-v5.geojson'; write_json(wgs_path,_geojson_feature(wgs,{'status':'PROPOSED','option':'A'},crs='EPSG:4326'))
 evidence={'schema_version':'m2-r06-boundary-relationship-evidence','coordinate_crs':'EPSG:28992','source_dataset':'BGT','source_collections':sorted(selection['boundary_source_collections']),'source_snapshots':{('wegdeel'): {'path':bgt_dst.relative_to(root).as_posix(),'sha256':sha256_file(bgt_dst)},**{c:{'path':p.relative_to(root).as_posix(),'sha256':sha256_file(p)} for c,p in supplementary}},'edges':edges,'boundary_selection':selection,'bag_building_snapshot_path':bag_dst.relative_to(root).as_posix(),'bag_building_snapshot_sha256':sha256_file(bag_dst),'bag_building_crossing_count':len(bag_cross),'bag_cross_boundary_buildings':bag_cross,'osm_building_crossing_count':len(true_cross),'osm_raw_geometry_reconciliation_count':len(reconciliations),'osm_raw_geometry_reconciliations':reconciliations,'building_crossing_method':'BAG canonical duplicate reconciliation with raw OSM residual retained; unmatched OSM building footprints are hard failures','osm_bag_reconciliation_tolerance':{'symmetric_difference_area_m2_max':MAX_OSM_BAG_DISCREPANCY_AREA_M2,'hausdorff_distance_m_max':MAX_OSM_BAG_HAUSDORFF_M},'intent_drift_metrics':metrics,'human_feedback_is_not_measurement':True,'limitations':['BGT observations establish geometry correspondence only; they do not establish ownership, zoning, permission, or buildability.','Centroid selection and intent-drift values are deterministic QA diagnostics, not planning rules.','OSM/BAG duplicate reconciliation is a source-registration QA rule only; it does not establish building legality or planning status.']}
 ev_path=root/'sources/boundary-relationship-evidence-v5.json'; write_json(ev_path,evidence)
 viewport=tuple(parent['delft_context']['viewport']['bbox']); svg_path=root/'map-preview-v5.svg'; render=_render_v5(svg_path,boundary,display,viewport,cross_count=0); png_path=root/'map-preview-v5.png'; _render_png(svg_path,png_path)
 diag_svg=root/'map-diagnostic-v5.svg'; _diagnostic_svg(diag_svg,seed,candidate_geom,edges,display,viewport); diag_png=root/'map-diagnostic-v5.png'; _render_png(diag_svg,diag_png)
 # Retain all v4 source-record claims under parent-v4 and append v5 observations.
 source_records=[]; parent_records=json.loads((root/'parent-v4/sources/source-records-v4.json').read_text()).get('records',[])
 for rec in parent_records:
  rr=dict(rec); ap=rr.get('artifact_path'); rr['artifact_path']=('parent-v4/'+str(ap)) if ap and not str(ap).startswith('parent-v4/') else ap; source_records.append(rr)
 def src_record(collection,path,payload):
  ts=_source_timestamp(payload); return {'id':f'source-pdok-bgt-{collection}-m4h-v5','source_class':'DATASET_OBSERVATION','availability':'OBSERVED','publisher':'PDOK / Kadaster','source_identity':f'BGT OGC API collection {collection}','query':f'GET /lv/bgt/ogc/v1/collections/{collection}/items?bbox=4.4235,51.9040,4.4365,51.9110&limit=1000&f=json','retrieved_at':ts,'request_started_at':ts,'request_finished_at':ts,'request_url':f'https://api.pdok.nl/lv/bgt/ogc/v1/collections/{collection}/items?bbox=4.4235,51.9040,4.4365,51.9110&limit=1000&f=json','version':str(payload.get('timeStamp','BGT OGC API response')),'license':'BGT open data; consult PDOK/Kadaster terms','attribution':'PDOK / Kadaster Basisregistratie Grootschalige Topografie','parameters':{'bbox_crs':'CRS84','limit':1000,'feature_count':len(payload.get('features',[])),'selected_by':'intersects retained v3 seed; polygonized face seed-overlap ratio >= 0.5'},'validation_status':'VALIDATED','artifact_path':path.relative_to(root).as_posix(),'artifact_sha256':sha256_file(path),'artifact_size_bytes':path.stat().st_size,'coverage':{'collection':collection,'bbox':[4.4235,51.9040,4.4365,51.9110]},'limitations':['Official geometry observation only; no ownership, zoning, permission, or buildability conclusion.']}
 source_records += [src_record('wegdeel',bgt_dst,bgt),*[src_record(c,p,json.loads(p.read_text())) for c,p in supplementary]]
 source_records.append({'id':'source-pdok-bag-pand-m4h-v5','source_class':'DATASET_OBSERVATION','availability':'OBSERVED','publisher':'PDOK / Kadaster','source_identity':'BAG OGC API collection pand','query':'GET /kadaster/bag/ogc/v2/collections/pand/items?bbox=4.4235,51.9040,4.4365,51.9110&limit=1000&f=json','retrieved_at':_source_timestamp(bag),'request_started_at':_source_timestamp(bag),'request_finished_at':_source_timestamp(bag),'request_url':'https://api.pdok.nl/kadaster/bag/ogc/v2/collections/pand/items?bbox=4.4235,51.9040,4.4365,51.9110&limit=1000&f=json','version':str(bag.get('timeStamp','BAG OGC API response')),'license':'Public Domain Mark 1.0','attribution':'PDOK / Kadaster Basisregistratie Adressen en Gebouwen','parameters':{'bbox_crs':'CRS84','limit':1000,'feature_count':len(bag.get('features',[])),'used_for':'building-footprint cross-check only'},'validation_status':'VALIDATED','artifact_path':bag_dst.relative_to(root).as_posix(),'artifact_sha256':sha256_file(bag_dst),'artifact_size_bytes':bag_dst.stat().st_size,'coverage':{'collection':'pand','bbox':[4.4235,51.9040,4.4365,51.9110]},'limitations':['Building-footprint observation only; no planning or ownership conclusion.']})
 source_records.append({'id':'source-rotterdam-boundary-relationship-v5','source_class':'COMPUTED_RESULT','availability':'OBSERVED','publisher':'M2-R06 executor','source_identity':'Deterministic polygonized BGT boundary-face relationship audit','query':'Polygonize official BGT polygon boundaries intersecting the retained v3 seed, select faces with seed-overlap ratio >= 0.5, and map each derived exterior subsegment to its retained source ring segment','retrieved_at':CREATED,'request_started_at':CREATED,'request_finished_at':CREATED,'request_url':'file:///sources/boundary-relationship-evidence-v5.json','version':'M2-R06','license':'Project evidence; underlying BGT/BAG licences retained','attribution':'Derived from retained PDOK snapshots','parameters':{'segment_count':len(edges),'boundary_source_collections':selection['boundary_source_collections'],'bag_building_crossing_count':len(bag_cross),'osm_building_crossing_count':len(true_cross),'osm_raw_geometry_reconciliation_count':len(reconciliations),'intent_drift_metrics':metrics},'validation_status':'VALIDATED','artifact_path':ev_path.relative_to(root).as_posix(),'artifact_sha256':sha256_file(ev_path),'artifact_size_bytes':ev_path.stat().st_size,'coverage':{'boundary_segments':len(edges)},'limitations':['Computed correspondence and QA metrics are not planning conclusions.']})
 sr_path=root/'sources/source-records-v5.json'; write_json(sr_path,{'schema_version':'m2-r06-source-records','records':source_records})
 [V2SourceRecord.model_validate(r) for r in source_records if r['source_class']!='COMPUTED_RESULT']
 context={'containment_status':'WITHIN_INDEPENDENT_MUNICIPAL_BOUNDARY','evidence_ref':'sources/raw/pdok-rotterdam-municipality-v2.geojson','viewport':{'bbox':list(viewport),'crs':'EPSG:28992'},'candidate_boundary_wgs84':wgs,'candidate_boundary_wgs84_sha256':'sha256:'+hashlib.sha256(canonical_json_bytes(wgs)).hexdigest(),'boundary_selection_status':'PROPOSED_HUMAN_REVIEW_REQUIRED','human_choice_required':True,'display_only':True,'display_option':'A','boundary_options':{'A':{'status':'PROPOSED','label':'Option A v5 follows official BGT site-facing road/supplementary edges; human decision remains required','wgs84_geometry':wgs,'projected_geometry':boundary,'edge_refs':sorted({e['source_feature_id'] for e in edges})},'B':{'status':'REJECTED_BY_HUMAN_FEEDBACK','retained_parent_path':'parent-v4','retained_parent_proposal':'site-proposal-rotterdam-m4h-v4','automated_review_marker':'REJECTED_BY_CONTROL_TOWER_INVALID_SITE_SEMANTICS'}},'context_display_path':'context-display-epsg28992-v2.geojson','municipality_feature_path':'sources/raw/pdok-rotterdam-municipality-v2.geojson','parent_v4_path':'parent-v4','parent_integrity_path':'parent-v4-integrity.json','bgt_source_path':bgt_dst.relative_to(root).as_posix(),'bgt_source_sha256':sha256_file(bgt_dst),'bag_source_path':bag_dst.relative_to(root).as_posix(),'bag_source_sha256':sha256_file(bag_dst),'bgt_feature_count':len(bgt.get('features',[])),'supplementary_source_paths':{c:p.relative_to(root).as_posix() for c,p in supplementary},'boundary_relationship_evidence_path':ev_path.relative_to(root).as_posix(),'display_data_path':display_path.relative_to(root).as_posix(),'classification_priority':PRIORITY,'cross_boundary_buildings':true_cross,'building_crossing_count':len(true_cross),'osm_building_crossing_count':len(true_cross),'osm_raw_geometry_reconciliation_count':len(reconciliations),'osm_raw_geometry_reconciliations':reconciliations,'building_crossing_method':'BAG canonical duplicate reconciliation with raw OSM residual retained; unmatched OSM building footprints are hard failures','osm_bag_reconciliation_tolerance':{'symmetric_difference_area_m2_max':MAX_OSM_BAG_DISCREPANCY_AREA_M2,'hausdorff_distance_m_max':MAX_OSM_BAG_HAUSDORFF_M},'bag_cross_boundary_buildings':bag_cross,'bag_building_crossing_count':len(bag_cross),'intent_drift_metrics':metrics,'road_surface_overlap_ratio':metrics['road_surface_overlap_ratio'],'building_membership_rule':'centroid strictly inside v5 boundary = site buildings; full footprints remain un-clipped; only positive-area partial intersections are crossings','map_svg_path':svg_path.relative_to(root).as_posix(),'map_svg_sha256':sha256_file(svg_path),'map_svg_size_bytes':svg_path.stat().st_size,'rendered_png_path':png_path.relative_to(root).as_posix(),'rendered_png_sha256':sha256_file(png_path),'rendered_png_size_bytes':png_path.stat().st_size,'diagnostic_svg_path':diag_svg.relative_to(root).as_posix(),'diagnostic_svg_sha256':sha256_file(diag_svg),'diagnostic_png_path':diag_png.relative_to(root).as_posix(),'diagnostic_png_sha256':sha256_file(diag_png),'render_record_path':'render-record-v5.json','state_path':'proposal-state.sqlite3','v4_rejection_marker':'REJECTED_BY_CONTROL_TOWER_INVALID_SITE_SEMANTICS','option_b_rejection_reason':'REJECTED_BY_HUMAN_FEEDBACK; preserved from the retained parent option record','limitations':['Human feedback remains qualitative intent only and is not used as a measurement.','BGT/BAG observations establish geometry correspondence and QA only; planning, ownership, zoning, buildability, accessibility, morphology, space syntax, climate, and effective constraints remain unavailable.']}
 write_json(root/'render-record-v5.json',{'schema_version':'m2-r06-render-record','producer':PRODUCER,'svg_path':svg_path.relative_to(root).as_posix(),'svg_sha256':sha256_file(svg_path),'png_path':png_path.relative_to(root).as_posix(),'png_sha256':sha256_file(png_path),'diagnostic_svg_path':diag_svg.relative_to(root).as_posix(),'diagnostic_svg_sha256':sha256_file(diag_svg),'diagnostic_png_path':diag_png.relative_to(root).as_posix(),'diagnostic_png_sha256':sha256_file(diag_png),'viewport':render,'layer_order':render['layer_order'],'water_style':'#f1f4f5','boundary_stroke_width_px':1.4,'single_decision_map':True,'diagnostic_only':True})
 approval=root/'approval-record-v5.md'; approval.write_text(f'''# Human approval record — Rotterdam M4H Vierhavenblok v5\n\nProposal: `{PROPOSAL_ID}` supersedes `site-proposal-rotterdam-m4h-v4`.\n\nDecision status: **HUMAN_DECISION_REQUIRED**. v4 is retained under `parent-v4/` and rejected by automated review with marker `REJECTED_BY_CONTROL_TOWER_INVALID_SITE_SEMANTICS`. Option A v5 remains **PROPOSED**.\n\nThe v5 perimeter is generated by polygonizing official BGT boundaries intersecting the retained v3 seed and selecting faces with seed-overlap ratio >= 0.5. Every exterior segment is traced to a retained BGT ring segment. The v3 seed is used only for deterministic face selection and intent-drift QA; no seed coordinate is inserted into v5. BAG is canonical for matched OSM duplicate crossing checks within the documented registration tolerance, with the raw OSM geometry retained.\n\n**APPROVE:** append a human decision naming Option A, exact artifact hashes, actor, timezone-aware timestamp, and reason. **REJECT:** append a human rejection and reason. No approval, acceptance, freeze, effective constraint, or site adoption has been recorded.\n''',encoding='utf-8')
 proposal=SiteProposal(id=PROPOSAL_ID,project_id=PROJECT_ID,version='v5',supersedes_proposal_id='site-proposal-rotterdam-m4h-v4',status='PROPOSED',human_decision_status='HUMAN_DECISION_REQUIRED',boundary_artifact_path=boundary_path.relative_to(root).as_posix(),boundary_sha256=sha256_file(boundary_path),boundary_size_bytes=boundary_path.stat().st_size,boundary_mime='application/geo+json',geometry_sha256=canonical_geometry_hash(boundary),geometry=boundary,geometry_type='Polygon',horizontal_crs='EPSG:28992',units='m',vertical_reference_status='NOT_APPLICABLE_2D_BOUNDARY; no vertical reference supplied',transform={'input_crs':'EPSG:4326','output_crs':'EPSG:28992','method':'pyproj deterministic WGS84-to-RD reprojection for metric geometry','tool':'pyproj','tool_version':'3.8.0','command':'Transformer.from_crs(4326,28992,always_xy=True)','axis_order':'traditional GIS axis order','vertical_reference_status':'NOT_APPLICABLE_2D_BOUNDARY'},producer=PRODUCER,created_at=datetime.fromisoformat(CREATED),selection_method='Deterministic polygonization of official BGT boundaries intersecting the retained v3 seed; selected faces have seed-overlap ratio >= 0.5; every exterior subsegment is traced to source geometry; human decision remains required.',rationale='Append-only M2-R06 repair superseding the invalid single-road-strip v4 candidate, retaining v4 byte lineage, and producing a complete source-backed perimeter with explicit intent-drift and crossing QA.',source_refs=[r['id'] for r in source_records],parent_refs=['site-proposal-rotterdam-m4h-v4','site-proposal-rotterdam-m4h-v3','site-proposal-rotterdam-m4h-v2','site-proposal-delft-v1','site-proposal-delft-v2','site-proposal-delft-v3','parent-v4-integrity'],measurements=[{'name':'area','value':polygon_area(boundary),'unit':'m2','method':'shoelace area on EPSG:28992 projected exterior ring','crs':'EPSG:28992'},{'name':'perimeter','value':polygon_perimeter(boundary),'unit':'m','method':'Euclidean exterior-ring perimeter on EPSG:28992 projected coordinates','crs':'EPSG:28992'}],delft_context=context,dataset_plan={'municipality':'PDOK BRK municipality containment only','context':'retained OSM display context plus bounded official BGT and BAG observations','boundary':'BGT site-facing road and supplementary polygon edges','planning_and_buildability':'UNAVAILABLE','accessibility':'OUT_OF_SCOPE','morphology':'OUT_OF_SCOPE','space_syntax':'OUT_OF_SCOPE','climate':'UNAVAILABLE','design_generation':'OUT_OF_SCOPE'},limitations=context['limitations'],approval_record_path=approval.relative_to(root).as_posix(),selection_criteria_status='PROPOSED_PROJECT_DECISION',selection_criteria={'status':'PROPOSED_PROJECT_DECISION','human_selection_required':True,'option_a':'PROPOSED','option_b':'REJECTED_BY_HUMAN_FEEDBACK'},scale_parameters={'status':'PROPOSED_PROJECT_DECISION','thresholds':None},taxonomy_status='PROPOSED',map_preview_path=svg_path.relative_to(root).as_posix(),source_records_path=sr_path.relative_to(root).as_posix())
 # Copy v4 state and append immutable rejection + v5 records with fixed timestamps.
 db=root/'proposal-state.sqlite3'; cp(root/'parent-v4/proposal-state.sqlite3',db)
 with ProjectStateStore(db) as store:
  store._timestamp=lambda: CREATED
  # v4 rejection is an automated review event only; it does not rewrite v4.
  store.create('ContestEvent',{'id':'contest-v4-invalid-site-semantics','project_id':PROJECT_ID,'target_proposal_id':'site-proposal-rotterdam-m4h-v4','marker':'REJECTED_BY_CONTROL_TOWER_INVALID_SITE_SEMANTICS','status':'REJECTED','reason':'v4 was a single 2,023 m2 BGT road-surface strip with zero site buildings and invalid site semantics.'},entity_id='contest-v4-invalid-site-semantics',project_id=PROJECT_ID,event_id='event-m2-r06-reject-v4-invalid-site-semantics',actor='control-tower-automated-review',action='Reject',reason='REJECTED_BY_CONTROL_TOWER_INVALID_SITE_SEMANTICS',changed_refs=['site-proposal-rotterdam-m4h-v4'],resulting_refs=['site-proposal-rotterdam-m4h-v4','contest-v4-invalid-site-semantics'],event_payload={'marker':'REJECTED_BY_CONTROL_TOWER_INVALID_SITE_SEMANTICS','area_m2':2023.398979,'site_building_count':0})
  specs=[(boundary_path,'artifact-boundary-rotterdam-m4h-v5','application/geo+json',[]),(wgs_path,'artifact-boundary-wgs84-rotterdam-m4h-v5','application/geo+json',['artifact-boundary-rotterdam-m4h-v5']),(display_path,'artifact-display-data-rotterdam-m4h-v5','application/geo+json',['artifact-boundary-rotterdam-m4h-v5']),(bgt_dst,'artifact-pdok-bgt-wegdeel-m4h-v5','application/json',[]),*[(p,f'artifact-pdok-bgt-{c}-m4h-v5','application/json',[]) for c,p in supplementary],(bag_dst,'artifact-pdok-bag-pand-m4h-v5','application/json',[]),(ev_path,'artifact-boundary-relationship-v5','application/json',['artifact-boundary-rotterdam-m4h-v5']),(sr_path,'artifact-source-records-rotterdam-m4h-v5','application/json',['artifact-boundary-relationship-v5']),(svg_path,'artifact-map-preview-rotterdam-m4h-v5','image/svg+xml',['artifact-display-data-rotterdam-m4h-v5']),(png_path,'artifact-map-preview-render-rotterdam-m4h-v5','image/png',['artifact-map-preview-rotterdam-m4h-v5']),(diag_svg,'artifact-map-diagnostic-rotterdam-m4h-v5','image/svg+xml',['artifact-boundary-relationship-v5']),(diag_png,'artifact-map-diagnostic-render-rotterdam-m4h-v5','image/png',['artifact-map-diagnostic-rotterdam-m4h-v5']),(approval,'artifact-approval-record-rotterdam-m4h-v5','text/markdown',['artifact-map-preview-render-rotterdam-m4h-v5']),(root/'parent-v4-integrity.json','artifact-parent-v4-integrity','application/json',[])]
  for p,aid,mime,parents in specs: store.create_typed(_artifact(p,root,aid,mime,datetime.fromisoformat(CREATED),parents),event_id=f'event-m2-r06-artifact-{aid}',actor='m2-r06-executor',action='RecordArtifact',reason='Record append-only M2-R06 evidence with immutable hash and parent links.')
  site=Site(id='site-rotterdam-m4h-v5',project_id=PROJECT_ID,version='v5',boundary_artifact_id='artifact-boundary-rotterdam-m4h-v5',boundary_sha256=proposal.boundary_sha256,crs='EPSG:28992',vertical_reference=proposal.vertical_reference_status,units='m',dataset_snapshot_ids=[],status=SiteStatus.PROPOSED)
  store.create_typed(site,event_id='event-m2-r06-site-proposed',actor='m2-r06-executor',action='ProposeSite',reason='Append v5 proposed source-backed perimeter; human decision remains required.',changed_refs=proposal.source_refs,resulting_refs=[site.id,site.boundary_artifact_id,proposal.id],event_payload={'proposal_id':proposal.id,'status':'PROPOSED','human_decision_required':True,'building_crossing_count':0})
  store.create('SiteProposal',proposal.model_dump(mode='json'),entity_id=proposal.id,project_id=PROJECT_ID,event_id='event-m2-r06-site-proposal-recorded',actor='m2-r06-executor',action='RecordSiteProposal',reason='Record append-only v5 without adoption or approval.',changed_refs=proposal.source_refs,resulting_refs=[proposal.id,site.id,site.boundary_artifact_id],event_payload={'proposal_id':proposal.id,'status':'PROPOSED','human_decision_required':True})
  proposal.ledger_event_refs=[e.event_id for e in store.events(project_id=PROJECT_ID) if e.target_id in {proposal.id,site.id}]
 write_json(root/'site-proposal.json',proposal.model_dump(mode='json'))
 from urban_design.site_proposal_rotterdam_v5 import validate_site_proposal_rotterdam_v5
 validate_site_proposal_rotterdam_v5(proposal,root)
 return proposal

def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('--output-dir',type=Path,required=True); p.add_argument('--v4-dir',type=Path,required=True); p.add_argument('--wegdeel-source',type=Path,required=True)
 p.add_argument('--offline',action='store_true',default=True)
 for c in ['ondersteunendwegdeel','onbegroeidterreindeel','waterdeel','begroeidterreindeel']: p.add_argument(f'--{c}-source',type=Path,required=True)
 a=p.parse_args(argv)
 try:r=build_rotterdam_v5(a.output_dir,v4_dir=a.v4_dir,wegdeel_source=a.wegdeel_source,supplementary_sources={c:getattr(a,f'{c}_source') for c in ['ondersteunendwegdeel','onbegroeidterreindeel','waterdeel','begroeidterreindeel']},offline=True)
 except Exception as exc: print(f'BLOCKED: {exc}',file=sys.stderr); return 2
 print(json.dumps({'proposal_id':r.id,'version':r.version,'status':r.status,'boundary_sha256':r.boundary_sha256,'geometry_sha256':r.geometry_sha256},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
