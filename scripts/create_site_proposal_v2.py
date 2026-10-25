#!/usr/bin/env python3
"""Build the repaired, approval-ready Delft site proposal (M2-R01).

The v2 builder is additive: it copies the closed v1 state database, records
v1 hashes, and appends a new proposed site and proposal.  It never adopts a
site, creates a HumanDecision, or freezes a dataset.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

from urban_design.geometry import canonical_geometry_hash, polygon_area, polygon_perimeter
from urban_design.models import Artifact, Site, SiteStatus
from urban_design.site_proposal import (
    Measurement,
    SiteProposal,
    TransformRecord,
    V2SourceRecord,
    assert_no_effective_site_conflict,
    canonical_json_bytes,
    sha256_file,
)
from urban_design.site_proposal_v2 import (
    SiteProposalV2ValidationError,
    point_in_polygon,
    validate_site_proposal_v2,
)
from urban_design.store import ProjectStateStore


PRODUCER = "urban-design-m2-repair-v2/0.1"
GDAL_OGR2OGR = "/Applications/QGIS-LTR.app/Contents/MacOS/bin/ogr2ogr"
V1_PROPOSAL_ID = "site-proposal-delft-v1"
V2_PROPOSAL_ID = "site-proposal-delft-v2"
V1_DEFAULT = Path("artifacts/milestone2-site-proposal/run-20260915T000500Z")
OSM_OVERPASS = "https://overpass.kumi.systems/api/interpreter"
OSM_ANCHOR = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=Delft%20railway%20station%2C%20Netherlands"
PDOK_BOUNDARY_BASE = "https://api.pdok.nl/kadaster/brk-bestuurlijke-gebieden/ogc/v1"
PDOK_MUNICIPALITY_COLLECTION = PDOK_BOUNDARY_BASE + "/collections/gemeentegebied?f=json"
PDOK_MUNICIPALITY_ITEMS = PDOK_BOUNDARY_BASE + "/collections/gemeentegebied/items?bbox=4.34,51.98,4.38,52.03&limit=10&f=json"
PDOK_BAG_LANDING = "https://api.pdok.nl/kadaster/bag/ogc/v2?f=json"
PDOK_BAG_COLLECTIONS = "https://api.pdok.nl/kadaster/bag/ogc/v2/collections?f=json"


class ProposalBuildError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Capture:
    source_id: str
    url: str
    query: str
    started_at: datetime
    finished_at: datetime
    path: Path

    def manifest(self, root: Path) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "request_url": self.url,
            "query": self.query,
            "request_started_at": self.started_at.isoformat(),
            "request_finished_at": self.finished_at.isoformat(),
            "artifact_path": self.path.relative_to(root).as_posix(),
            "artifact_sha256": sha256_file(self.path),
            "artifact_size_bytes": self.path.stat().st_size,
        }


def _fetch_json(url: str, path: Path, *, source_id: str, query: str, root: Path, timeout: int = 90) -> Capture:
    started = utc_now()
    request = urllib.request.Request(url, headers={"User-Agent": "DelftPilotEvidence/0.2 (urban-design prototype)", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except Exception as exc:  # pragma: no cover - external service dependent
        raise ProposalBuildError(f"{source_id} source retrieval failed: {exc}") from exc
    finished = utc_now()
    if not body:
        raise ProposalBuildError(f"{source_id} source retrieval returned empty bytes")
    try:
        json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProposalBuildError(f"{source_id} response is not JSON") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return Capture(source_id, url, query, started, finished, path)


def _raw_hash(path: Path) -> str:
    return sha256_file(path)


def _write_json(path: Path, payload: object) -> None:
    if not isinstance(payload, dict):
        raise ProposalBuildError("JSON artifact payload must be an object")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _extract_geometry(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("type") in {"Polygon", "MultiPolygon"}:
        return {"type": payload["type"], "coordinates": payload.get("coordinates")}
    if payload.get("type") == "Feature":
        geometry = payload.get("geometry")
        if isinstance(geometry, dict):
            return {"type": geometry.get("type"), "coordinates": geometry.get("coordinates")}
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features")
        if isinstance(features, list) and len(features) == 1 and isinstance(features[0], dict):
            geometry = features[0].get("geometry")
            if isinstance(geometry, dict):
                return {"type": geometry.get("type"), "coordinates": geometry.get("coordinates")}
    raise ProposalBuildError("GeoJSON payload does not contain a single Polygon/MultiPolygon")


def _run_transform(input_path: Path, transformed_path: Path) -> tuple[str, str]:
    if not Path(GDAL_OGR2OGR).exists():
        raise ProposalBuildError(f"pinned GDAL transform tool is missing: {GDAL_OGR2OGR}")
    command = [GDAL_OGR2OGR, "-f", "GeoJSON", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:28992", str(transformed_path), str(input_path)]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        version = subprocess.run([GDAL_OGR2OGR, "--version"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProposalBuildError(f"deterministic CRS transform failed: {exc}") from exc
    return " ".join(command), version or "GDAL version unavailable"


def _municipality_feature(items_path: Path) -> dict[str, object]:
    payload = json.loads(items_path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    if not isinstance(features, list):
        raise ProposalBuildError("PDOK municipality response has no features list")
    matches = [feature for feature in features if isinstance(feature, dict) and feature.get("properties", {}).get("naam") == "Delft" and feature.get("properties", {}).get("code") == "0503"]
    if len(matches) != 1:
        raise ProposalBuildError(f"PDOK municipality response returned {len(matches)} Delft/0503 features")
    feature = matches[0]
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise ProposalBuildError("PDOK Delft municipality feature has no geometry")
    return {"type": "Feature", "id": feature.get("id"), "properties": feature.get("properties", {}), "geometry": geometry}


def _v1_manifest(v1_root: Path, output_path: Path) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for path in sorted(p for p in v1_root.rglob("*") if p.is_file()):
        entries.append({"path": path.relative_to(v1_root).as_posix(), "size_bytes": path.stat().st_size, "sha256": _raw_hash(path)})
    if not entries:
        raise ProposalBuildError("v1 package contains no files")
    payload = {"schema_version": "m2-r01-v1-integrity", "v1_root": str(v1_root), "files": entries}
    _write_json(output_path, payload)
    return payload


def _way_points(element: dict[str, object]) -> list[tuple[float, float]]:
    geometry = element.get("geometry", [])
    return [(float(point["lon"]), float(point["lat"])) for point in geometry if isinstance(point, dict) and "lat" in point and "lon" in point]


def _osm_layers(payload: dict[str, object]) -> dict[str, object]:
    elements = payload.get("elements", [])
    if not isinstance(elements, list):
        raise ProposalBuildError("OSM exact-polygon response has no elements list")
    roads: list[dict[str, object]] = []
    buildings: list[dict[str, object]] = []
    rails: list[dict[str, object]] = []
    waters: list[dict[str, object]] = []
    public_spaces: list[dict[str, object]] = []
    shops: list[dict[str, object]] = []
    stations: list[dict[str, object]] = []
    shop_counts = {"supermarket": 0, "convenience": 0, "grocery": 0, "other": 0}
    for item in elements:
        if not isinstance(item, dict):
            continue
        tags = item.get("tags", {})
        if not isinstance(tags, dict):
            tags = {}
        if item.get("type") == "node":
            if "shop" in tags:
                shops.append(item)
                category = str(tags.get("shop"))
                shop_counts[category if category in {"supermarket", "convenience", "grocery"} else "other"] += 1
            if tags.get("railway") == "station":
                stations.append(item)
            continue
        if item.get("type") != "way" or not _way_points(item):
            continue
        if "highway" in tags:
            roads.append(item)
        if "building" in tags:
            buildings.append(item)
        if "railway" in tags or str(tags.get("railway", "")).startswith("rail"):
            rails.append(item)
        if tags.get("waterway") or tags.get("natural") == "water" or tags.get("landuse") in {"reservoir", "basin"}:
            waters.append(item)
        if tags.get("highway") == "pedestrian" or tags.get("leisure") or tags.get("landuse") in {"park", "recreation_ground", "grass"}:
            public_spaces.append(item)
    return {
        "elements": elements,
        "roads": roads,
        "buildings": buildings,
        "rails": rails,
        "waters": waters,
        "public_spaces": public_spaces,
        "shops": shops,
        "stations": stations,
        "shop_counts": shop_counts,
    }


def _map_svg(path: Path, ring: list[list[float]], layers: dict[str, object], source_records: list[V2SourceRecord], proposal_id: str) -> None:
    all_points: list[tuple[float, float]] = [(float(point[0]), float(point[1])) for point in ring]
    for key in ("roads", "buildings", "rails", "waters", "public_spaces"):
        for item in layers[key]:
            all_points.extend(_way_points(item))
    for item in layers["shops"] + layers["stations"]:
        if isinstance(item, dict) and "lon" in item and "lat" in item:
            all_points.append((float(item["lon"]), float(item["lat"])))
    min_x, max_x = min(point[0] for point in all_points), max(point[0] for point in all_points)
    min_y, max_y = min(point[1] for point in all_points), max(point[1] for point in all_points)
    span_x, span_y = max_x - min_x, max_y - min_y
    pad_x, pad_y = max(span_x * 0.14, 0.00015), max(span_y * 0.14, 0.00015)
    min_x, max_x, min_y, max_y = min_x - pad_x, max_x + pad_x, min_y - pad_y, max_y + pad_y
    width, height = 1120, 760
    plot_left, plot_top, plot_width, plot_height = 70, 105, 980, 535
    scale_x, scale_y = plot_width / (max_x - min_x), plot_height / (max_y - min_y)

    def project(point: tuple[float, float]) -> tuple[float, float]:
        return (plot_left + (point[0] - min_x) * scale_x, plot_top + plot_height - (point[1] - min_y) * scale_y)

    def line(points: list[tuple[float, float]], style: str) -> str:
        if len(points) < 2:
            return ""
        return f'<polyline points="{" ".join(f"{project(p)[0]:.2f},{project(p)[1]:.2f}" for p in points)}" {style}/>'

    def polygon(points: list[tuple[float, float]], style: str) -> str:
        if len(points) < 3:
            return ""
        return f'<polygon points="{" ".join(f"{project(p)[0]:.2f},{project(p)[1]:.2f}" for p in points)}" {style}/>'

    buildings = "".join(polygon(_way_points(item), 'fill="#d8d5cd" stroke="#aaa59b" stroke-width="0.65"') for item in layers["buildings"])
    waters = "".join(line(_way_points(item), 'fill="none" stroke="#5fa9c6" stroke-width="3" opacity="0.9"') for item in layers["waters"])
    roads = "".join(line(_way_points(item), f'fill="none" stroke="{("#9b9286" if item.get("tags", {}).get("highway") in {"primary", "secondary", "tertiary"} else "#b9b1a4")}" stroke-width="{("2.8" if item.get("tags", {}).get("highway") in {"primary", "secondary", "tertiary"} else "1.25")}"') for item in layers["roads"])
    rails = "".join(line(_way_points(item), 'fill="none" stroke="#363c44" stroke-width="4" stroke-dasharray="8 4"') for item in layers["rails"])
    public = "".join(line(_way_points(item), 'fill="none" stroke="#6b9e72" stroke-width="2.2" stroke-dasharray="3 3"') for item in layers["public_spaces"])
    boundary_points = [(float(point[0]), float(point[1])) for point in ring]
    boundary = polygon(boundary_points, 'fill="#0b6e69" fill-opacity="0.13" stroke="#0b6e69" stroke-width="4"')
    shops = "".join(f'<circle cx="{project((float(item["lon"]), float(item["lat"])))[0]:.2f}" cy="{project((float(item["lon"]), float(item["lat"])))[1]:.2f}" r="4" fill="#d97941" stroke="#fff" stroke-width="1"/>' for item in layers["shops"] if "lon" in item and "lat" in item)
    stations = "".join(f'<circle cx="{project((float(item["lon"]), float(item["lat"])))[0]:.2f}" cy="{project((float(item["lon"]), float(item["lat"])))[1]:.2f}" r="8" fill="#a33d4e" stroke="#fff" stroke-width="2"/>' for item in layers["stations"] if "lon" in item and "lat" in item)
    # At the proposal scale, 100 m is rendered with a deterministic local
    # longitude conversion for display only; metric facts remain EPSG:28992.
    lat_mid = sum(point[1] for point in boundary_points) / len(boundary_points)
    degrees_for_100m = 100.0 / (111_320.0 * max(math.cos(math.radians(lat_mid)), 0.1))
    bar_px = degrees_for_100m * scale_x
    source_lines = []
    for record in source_records:
        if record.id in {"source-osm-exact-polygon-context", "source-pdok-delft-municipality"}:
            source_lines.append(f'{html.escape(record.id)} {html.escape(record.request_started_at.isoformat() if record.request_started_at else "UNAVAILABLE")} – {html.escape(record.request_finished_at.isoformat() if record.request_finished_at else "UNAVAILABLE")}')
    source_text = " · ".join(source_lines)
    counts = {"roads": len(layers["roads"]), "buildings": len(layers["buildings"]), "rails": len(layers["rails"]), "water": len(layers["waters"]), "public": len(layers["public_spaces"]), "shops": len(layers["shops"])}
    shop_counts = layers["shop_counts"]
    content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#f5f1e9"/>
<text x="42" y="38" font-family="sans-serif" font-size="25" font-weight="700" fill="#17212b">Delft centrum rail–canal corridor — PROPOSED BOUNDARY</text>
<text x="42" y="66" font-family="sans-serif" font-size="14" fill="#58636d">{html.escape(proposal_id)} · display geometry from retained OSM exact-polygon bytes · metrics EPSG:28992</text>
<rect x="{plot_left}" y="{plot_top}" width="{plot_width}" height="{plot_height}" fill="#fbfaf6" stroke="#c6c0b5"/>
{waters}{public}{buildings}{roads}{rails}{boundary}{shops}{stations}
<line x1="{plot_left + 18}" y1="{plot_top + 42}" x2="{plot_left + 18}" y2="{plot_top - 8}" stroke="#17212b" stroke-width="3"/><path d="M{plot_left + 18} {plot_top - 17} l-9 18 h18 z" fill="#17212b"/><text x="{plot_left + 9}" y="{plot_top - 27}" font-family="sans-serif" font-size="14" fill="#17212b">NORTH</text>
<line x1="{plot_left + 25}" y1="{plot_top + plot_height - 24}" x2="{plot_left + 25 + bar_px:.2f}" y2="{plot_top + plot_height - 24}" stroke="#17212b" stroke-width="4"/><line x1="{plot_left + 25}" y1="{plot_top + plot_height - 30}" x2="{plot_left + 25}" y2="{plot_top + plot_height - 18}" stroke="#17212b" stroke-width="2"/><line x1="{plot_left + 25 + bar_px:.2f}" y1="{plot_top + plot_height - 30}" x2="{plot_left + 25 + bar_px:.2f}" y2="{plot_top + plot_height - 18}" stroke="#17212b" stroke-width="2"/><text x="{plot_left + 25}" y="{plot_top + plot_height - 38}" font-family="sans-serif" font-size="12" fill="#17212b">100 m SCALE</text>
<rect x="{plot_left + plot_width + 22}" y="{plot_top + 10}" width="250" height="230" rx="5" fill="#fffdf8" stroke="#c6c0b5"/>
<text x="{plot_left + plot_width + 38}" y="{plot_top + 38}" font-family="sans-serif" font-size="16" font-weight="700" fill="#17212b">LEGEND</text>
<text x="{plot_left + plot_width + 38}" y="{plot_top + 66}" font-family="sans-serif" font-size="13" fill="#0b6e69">━━ Proposed boundary</text>
<text x="{plot_left + plot_width + 38}" y="{plot_top + 88}" font-family="sans-serif" font-size="13" fill="#9b9286">━━ Roads / walk paths ({counts['roads']})</text>
<text x="{plot_left + plot_width + 38}" y="{plot_top + 110}" font-family="sans-serif" font-size="13" fill="#8c877f">▰ Buildings ({counts['buildings']})</text>
<text x="{plot_left + plot_width + 38}" y="{plot_top + 132}" font-family="sans-serif" font-size="13" fill="#363c44">┈ Rail ({counts['rails']}) · ● Station</text>
<text x="{plot_left + plot_width + 38}" y="{plot_top + 154}" font-family="sans-serif" font-size="13" fill="#5fa9c6">━━ Water ({counts['water']})</text>
<text x="{plot_left + plot_width + 38}" y="{plot_top + 176}" font-family="sans-serif" font-size="13" fill="#6b9e72">┈ Public space ({counts['public']})</text>
<text x="{plot_left + plot_width + 38}" y="{plot_top + 198}" font-family="sans-serif" font-size="13" fill="#d97941">● Shops ({counts['shops']})</text>
<text x="{plot_left + plot_width + 38}" y="{plot_top + 226}" font-family="sans-serif" font-size="11" fill="#58636d">Buildings unavailable if count is zero.</text>
<text x="42" y="690" font-family="monospace" font-size="12" fill="#17212b">SHOP TAGS (PROPOSED TAXONOMY): supermarket={shop_counts['supermarket']} · convenience={shop_counts['convenience']} · grocery={shop_counts['grocery']} · other={shop_counts['other']}</text>
<text x="42" y="713" font-family="sans-serif" font-size="11" fill="#58636d">CRS: EPSG:28992 for measurements; display coordinates WGS84. SOURCE / TIMESTAMP: {html.escape(source_text)}</text>
<text x="42" y="734" font-family="sans-serif" font-size="11" fill="#58636d">Attribution: © OpenStreetMap contributors (ODbL 1.0); PDOK/Kadaster Bestuurlijke Gebieden. Retained bytes only; no live tiles.</text>
</svg>'''
    path.write_text(content, encoding="utf-8")


def _artifact(path: Path, root: Path, artifact_id: str, mime: str, project_id: str, created_at: datetime, *, crs: str | None = None, parents: list[str] | None = None) -> Artifact:
    return Artifact(id=artifact_id, type="proposal-artifact", uri=path.relative_to(root).as_posix(), sha256=sha256_file(path), mime=mime, crs=crs, producer=PRODUCER, created_at=created_at, project_id=project_id, size_bytes=path.stat().st_size, parent_artifact_ids=parents or [])


def build_v2(output_dir: str | Path, *, v1_root: str | Path = V1_DEFAULT, project_id: str = "delft-pilot-project") -> SiteProposal:
    root = Path(output_dir).resolve()
    v1 = Path(v1_root).resolve()
    if not v1.is_dir():
        raise ProposalBuildError(f"v1 package directory is missing: {v1}")
    root.mkdir(parents=True, exist_ok=True)
    raw_dir = root / "sources" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    created_at = utc_now()
    v1_manifest_payload = _v1_manifest(v1, root / "v1-integrity.json")

    anchor_path = raw_dir / "nominatim-delft-railway-station-v2.json"
    municipality_collection_path = raw_dir / "pdok-gemeentegebied-collection-v2.json"
    municipality_items_path = raw_dir / "pdok-gemeentegebied-items-v2.json"
    bag_landing_path = raw_dir / "pdok-bag-landing-v2.json"
    bag_collections_path = raw_dir / "pdok-bag-collections-v2.json"
    anchor_capture = _fetch_json(OSM_ANCHOR, anchor_path, source_id="source-nominatim-delft-anchor-v2", query="Delft railway station, Netherlands; limit=1", root=root)
    municipal_collection_capture = _fetch_json(PDOK_MUNICIPALITY_COLLECTION, municipality_collection_path, source_id="source-pdok-delft-municipality-collection", query="PDOK Bestuurlijke Gebieden gemeentegebied collection metadata", root=root)
    municipal_items_capture = _fetch_json(PDOK_MUNICIPALITY_ITEMS, municipality_items_path, source_id="source-pdok-delft-municipality", query="PDOK gemeentegebied items bbox=4.34,51.98,4.38,52.03; limit=10", root=root)
    bag_landing_capture = _fetch_json(PDOK_BAG_LANDING, bag_landing_path, source_id="source-pdok-bag-landing-v2", query="PDOK BAG OGC API landing metadata", root=root)
    bag_collections_capture = _fetch_json(PDOK_BAG_COLLECTIONS, bag_collections_path, source_id="source-pdok-bag-collections-v2", query="PDOK BAG OGC API collections metadata", root=root)

    anchor_payload = json.loads(anchor_path.read_text(encoding="utf-8"))
    if not isinstance(anchor_payload, list) or not anchor_payload:
        raise ProposalBuildError("Nominatim returned no station anchor")
    anchor = anchor_payload[0]
    lat, lon = float(anchor["lat"]), float(anchor["lon"])
    # Vertices are snapped to retained OSM vertices on Oude Lijn railway,
    # Buitenwatersloot canal, and Houttuinen cycleway. This is a proposed
    # rail-to-canal corridor decision, not a dimension threshold.
    ring = [[4.3557695, 52.0091312], [4.3558385, 52.0090792], [4.3588278, 52.00555], [4.358829, 52.0053301], [4.3574818, 52.0054477], [4.3557695, 52.0091312]]
    candidate_geometry = {"type": "Polygon", "coordinates": [ring]}
    candidate_hash = canonical_geometry_hash(candidate_geometry)
    selection_path = root / "boundary-wgs84-selection-v2.geojson"
    _write_json(selection_path, {"type": "Feature", "properties": {"selection_status": "PROPOSED_PROJECT_DECISION", "selection_criteria": "rail–canal corridor around Delft station and historic centre", "vertex_refs": {"north_west": "OSM Oude Lijn way 330692263", "north_east": "OSM Buitenwatersloot way 173906835", "south_east": "OSM Buitenwatersloot way 173906835 and Houttuinen way 223329783", "south_west": "OSM Oude Lijn way 330692263"}}, "geometry": candidate_geometry})

    municipality_feature = _municipality_feature(municipality_items_path)
    municipality_geometry = _extract_geometry(municipality_feature)
    if not all(point_in_polygon((point[0], point[1]), municipality_geometry) for point in ring[:-1]):
        raise ProposalBuildError("candidate ring is not contained by PDOK Delft municipality geometry")
    municipality_feature_path = root / "context-delft-municipality.geojson"
    _write_json(municipality_feature_path, municipality_feature)
    municipality_geometry_hash = canonical_geometry_hash(municipality_geometry)

    poly_query_coords = " ".join(f"{point[1]} {point[0]}" for point in ring[:-1])
    osm_query = f'[out:json][timeout:60];(way["highway"](poly:"{poly_query_coords}");way["building"](poly:"{poly_query_coords}");way["railway"](poly:"{poly_query_coords}");way["waterway"](poly:"{poly_query_coords}");way["natural"="water"](poly:"{poly_query_coords}");way["leisure"](poly:"{poly_query_coords}");way["landuse"~"park|recreation_ground|grass"](poly:"{poly_query_coords}");node["railway"="station"](poly:"{poly_query_coords}");node["shop"](poly:"{poly_query_coords}"););out tags geom;'
    osm_url = OSM_OVERPASS + "?data=" + urllib.parse.quote(osm_query, safe="")
    osm_path = raw_dir / "osm-exact-proposed-polygon-v2.json"
    osm_capture = _fetch_json(osm_url, osm_path, source_id="source-osm-exact-polygon-context", query=osm_query, root=root, timeout=120)
    osm_payload = json.loads(osm_path.read_text(encoding="utf-8"))
    layers = _osm_layers(osm_payload)

    transformed = root / "_boundary-rd-transformed.geojson"
    command, tool_version = _run_transform(selection_path, transformed)
    transformed_payload = json.loads(transformed.read_text(encoding="utf-8"))
    boundary_geometry = _extract_geometry(transformed_payload)
    transformed.unlink(missing_ok=True)
    area = polygon_area(boundary_geometry)
    perimeter = polygon_perimeter(boundary_geometry)
    boundary_path = root / "boundary-epsg28992-v2.geojson"
    _write_json(boundary_path, {"type": boundary_geometry["type"], "coordinates": boundary_geometry["coordinates"], "crs": {"type": "name", "properties": {"name": "EPSG:28992"}}})
    map_path = root / "map-preview-v2.svg"

    # Request timestamps are preserved per HTTP source; no generation time is
    # substituted for a request interval.
    captures = [anchor_capture, municipal_collection_capture, municipal_items_capture, bag_landing_capture, bag_collections_capture, osm_capture]
    request_manifest_path = root / "sources" / "request-manifest.json"
    _write_json(request_manifest_path, {"schema_version": "m2-r01-request-manifest", "captures": [capture.manifest(root) for capture in captures]})

    def source_from_capture(capture: Capture, *, publisher: str, source_identity: str, license_text: str, attribution: str, version: str, limitations: list[str], coverage: dict[str, object], parameters: dict[str, object]) -> V2SourceRecord:
        return V2SourceRecord(id=capture.source_id, source_class="DATASET_OBSERVATION", availability="OBSERVED", publisher=publisher, source_identity=source_identity, query=capture.query, retrieved_at=capture.finished_at, request_started_at=capture.started_at, request_finished_at=capture.finished_at, request_url=capture.url, version=version, license=license_text, attribution=attribution, parameters=parameters, artifact_path=capture.path.relative_to(root).as_posix(), artifact_sha256=sha256_file(capture.path), artifact_size_bytes=capture.path.stat().st_size, coverage=coverage, limitations=limitations)

    shop_counts = layers["shop_counts"]
    osm_version = str(osm_payload.get("generator", "Overpass API unspecified")) + "; osm_base=" + str(osm_payload.get("osm3s", {}).get("timestamp_osm_base", "unspecified"))
    counts = {"elements": len(layers["elements"]), "roads": len(layers["roads"]), "pedestrian_ways": sum(1 for item in layers["roads"] if item.get("tags", {}).get("highway") in {"footway", "path", "pedestrian", "cycleway", "steps"}), "buildings": len(layers["buildings"]), "railways": len(layers["rails"]), "waterways": len(layers["waters"]), "public_space": len(layers["public_spaces"]), "shops": len(layers["shops"]), "stations": len(layers["stations"]), "shop_tag_counts": shop_counts, "exact_polygon_query": True, "query_boundary_sha256": candidate_hash, "missing_or_unavailable": []}
    records = [
        source_from_capture(anchor_capture, publisher="OpenStreetMap Nominatim", source_identity=OSM_ANCHOR, license_text="ODbL 1.0; attribution required", attribution="© OpenStreetMap contributors", version="Nominatim jsonv2; endpoint version unspecified", limitations=["Station geocoder result is an anchor and regional label only; it is not municipal containment evidence."], coverage={"anchor_lat": lat, "anchor_lon": lon, "display_name": anchor.get("display_name")}, parameters={"format": "jsonv2", "limit": 1}),
        source_from_capture(municipal_collection_capture, publisher="PDOK / Kadaster", source_identity=PDOK_MUNICIPALITY_COLLECTION, license_text="Public Domain Mark 1.0 indicated by PDOK service metadata", attribution="PDOK / Kadaster", version="collection metadata updated=" + str(json.loads(municipality_collection_path.read_text(encoding="utf-8")).get("links", [{}])[0].get("updated", "unspecified")), limitations=["Collection metadata identifies the official municipality-boundary service; the Delft feature geometry is retained separately."], coverage={"collection": "gemeentegebied", "independent_context": True}, parameters={"collection_id": "gemeentegebied"}),
        source_from_capture(municipal_items_capture, publisher="PDOK / Kadaster", source_identity=PDOK_MUNICIPALITY_ITEMS, license_text="Public Domain Mark 1.0 indicated by PDOK service metadata", attribution="PDOK / Kadaster", version="PDOK response timestamp=" + str(json.loads(municipality_items_path.read_text(encoding="utf-8")).get("timeStamp", "unspecified")), limitations=["Five municipality features were returned for the bbox; only the Delft/0503 feature is used for containment. This is administrative context, not planning/buildability evidence."], coverage={"municipality_name": "Delft", "municipality_code": "0503", "selected_feature_path": municipality_feature_path.relative_to(root).as_posix(), "selected_feature_sha256": sha256_file(municipality_feature_path), "selected_geometry_sha256": municipality_geometry_hash, "candidate_vertices_inside": True}, parameters={"bbox": "4.34,51.98,4.38,52.03", "limit": 10, "candidate_boundary_sha256": candidate_hash}),
        source_from_capture(osm_capture, publisher="OpenStreetMap via Overpass", source_identity=OSM_OVERPASS, license_text="ODbL 1.0; attribution required", attribution="© OpenStreetMap contributors", version=osm_version, limitations=["Exact polygon query is a coverage observation, not a complete network, building, public-space, destination, or accessibility dataset.", "Missing features remain possible; no live tiles are used."], coverage={**counts, "selection_edge_way_ids": ["330692263", "173906835", "223329783"]}, parameters={"query_boundary_sha256": candidate_hash, "polygon_vertex_count": len(ring) - 1, "query_crs": "EPSG:4326 display geometry"}),
        source_from_capture(bag_landing_capture, publisher="PDOK / Kadaster", source_identity=PDOK_BAG_LANDING, license_text="Public Domain Mark 1.0 indicated by PDOK service metadata", attribution="PDOK / Kadaster", version="OGC API landing metadata; dataset version not supplied", limitations=["Service metadata only; no BAG features are frozen or used for metrics."], coverage={"building_data_indicated": True}, parameters={"format": "json"}),
        source_from_capture(bag_collections_capture, publisher="PDOK / Kadaster", source_identity=PDOK_BAG_COLLECTIONS, license_text="Public Domain Mark 1.0 indicated by PDOK service metadata", attribution="PDOK / Kadaster", version="OGC API collections metadata; dataset version not supplied", limitations=["Collection discovery only; later morphology retrieval requires its own query, snapshot, and validation."], coverage={"collection_count": len(json.loads(bag_collections_path.read_text(encoding="utf-8")).get("collections", [])), "building_data_indicated": True}, parameters={"format": "json"}),
        V2SourceRecord(id="source-climate-future-check-v2", source_class="UNAVAILABLE", availability="UNAVAILABLE", publisher="KNMI / Dutch climate data providers", source_identity="https://data.knmi.nl/", query="No climate layer retrieved during M2-R01", retrieved_at=created_at, version="not retrieved", license="To be verified for selected climate product", attribution="KNMI attribution to be confirmed", validation_status="UNAVAILABLE", limitations=["Climate evidence remains unavailable and cannot support an experiment until a later approved dataset plan."]),
        V2SourceRecord(id="source-project-selection-criteria-v2", source_class="PROJECT_DECISION", availability="OBSERVED", publisher="Delft pilot project", source_identity="local:boundary-wgs84-selection-v2.geojson", query="Candidate ring snapped to retained OSM rail, canal, and cycleway vertices; criteria remain proposed", retrieved_at=created_at, request_started_at=created_at, request_finished_at=created_at, request_url="local://boundary-wgs84-selection-v2.geojson", version="v2", license="Project decision record", attribution="Project decision; human approval required", parameters={"candidate_boundary_sha256": candidate_hash}, artifact_path=selection_path.relative_to(root).as_posix(), artifact_sha256=sha256_file(selection_path), artifact_size_bytes=selection_path.stat().st_size, coverage={"boundary_edges": ["Oude Lijn railway", "Buitenwatersloot canal", "Houttuinen cycleway"]}, limitations=["Selection criteria, corridor purpose, and scale are proposed project decisions; no scale threshold is effective."]),
    ]
    source_records_path = root / "sources" / "source-records-v2.json"
    _write_json(source_records_path, {"schema_version": "m2-r01-source-records", "records": [record.model_dump(mode="json") for record in records]})

    _map_svg(map_path, ring, layers, records, V2_PROPOSAL_ID)
    approval_path = root / "approval-record-v2.md"
    boundary_hash = sha256_file(boundary_path)
    approval_path.write_text(f"""# Human approval record — Delft site proposal v2

Decision status: **HUMAN_DECISION_REQUIRED**

Exact proposal: `{V2_PROPOSAL_ID}` version `v2`; supersedes `{V1_PROPOSAL_ID}`. Boundary artifact `{boundary_path.relative_to(root).as_posix()}` has SHA-256 `{boundary_hash}`. Map: `map-preview-v2.svg`.

The v2 boundary is a proposed rail–canal corridor around Delft station and the historic centre. Its criteria and scale are project decisions awaiting review; no dimension threshold is executable or effective.

- **APPROVE**: append a human decision naming this exact proposal, boundary hash, actor, timezone-aware timestamp, and reason; only then may a later transition make the Site effective and set `Project.site_id`.
- **REJECT**: append a human rejection naming this exact proposal, actor, timestamp, and reason; preserve v1 and v2 artifacts and append any replacement as a new proposal/version.

Limitations requiring review: OSM exact-polygon coverage is indicative; grocery tags remain separate and taxonomy is proposed; PDOK municipal containment does not establish buildability, planning permission, ownership, or legal access; climate evidence is unavailable.

No HumanDecision, approval, acceptance, or frozen snapshot was created.
""", encoding="utf-8")

    proposal = SiteProposal(
        id=V2_PROPOSAL_ID,
        project_id=project_id,
        version="v2",
        boundary_artifact_path=boundary_path.relative_to(root).as_posix(),
        boundary_sha256=boundary_hash,
        boundary_size_bytes=boundary_path.stat().st_size,
        boundary_mime="application/geo+json",
        geometry_sha256=canonical_geometry_hash(boundary_geometry),
        geometry=boundary_geometry,
        geometry_type=str(boundary_geometry["type"]),
        horizontal_crs="EPSG:28992",
        units="m",
        vertical_reference_status="NOT_APPLICABLE_2D_BOUNDARY; no vertical reference supplied",
        transform=TransformRecord(input_crs="EPSG:4326", output_crs="EPSG:28992", method="GDAL/OGR deterministic reprojection", tool=GDAL_OGR2OGR, tool_version=tool_version, command=command, axis_order="traditional GIS axis order: longitude, latitude input", vertical_reference_status="NOT_APPLICABLE_2D_BOUNDARY"),
        producer=PRODUCER,
        created_at=created_at,
        selection_method="Proposed rail–canal corridor: vertices are retained OSM vertices on Oude Lijn railway, Buitenwatersloot canal, and Houttuinen cycleway; station anchor is contextual only.",
        rationale="The corridor keeps the railway and canal as legible edges while enclosing a contiguous station-to-centre urban fabric with mapped roads, pedestrian paths, public space, buildings, and shops for later evidence work.",
        source_refs=[record.id for record in records],
        parent_refs=[V1_PROPOSAL_ID, "artifact-boundary-delft-v1", "artifact-map-preview-delft-v1", v1_manifest_payload["schema_version"]],
        measurements=[Measurement(name="area", value=area, unit="m2", method="shoelace area on projected 2D exterior ring", crs="EPSG:28992"), Measurement(name="perimeter", value=perimeter, unit="m", method="Euclidean exterior-ring perimeter on projected 2D coordinates", crs="EPSG:28992")],
        delft_context={"containment_status": "WITHIN_INDEPENDENT_MUNICIPAL_BOUNDARY", "evidence_ref": "source-pdok-delft-municipality", "context_type": "PDOK Bestuurlijke Gebieden gemeentegebied", "municipality_feature_path": municipality_feature_path.relative_to(root).as_posix(), "municipality_feature_sha256": sha256_file(municipality_feature_path), "municipality_geometry_sha256": municipality_geometry_hash, "candidate_boundary_wgs84": ring, "candidate_boundary_wgs84_sha256": candidate_hash, "candidate_vertices_inside": True, "nominatim_bbox_is_not_containment_evidence": True},
        dataset_plan={"pedestrian_network": "exact-polygon OSM coverage observed; retrieve, validate, and snapshot network after approval", "grocery_destinations": "retain supermarket, convenience, grocery, and other tags separately; taxonomy remains proposed until human decision", "morphology": "PDOK BAG service/collections feasible; retrieve building footprints and address evidence after approval", "public_space": "OSM pedestrian/leisure/water observations present; validate completeness and municipal sources later", "climate": "UNAVAILABLE in v2; select KNMI product and scenario after approval", "planning_and_buildability": "UNAVAILABLE; municipal containment does not establish zoning, ownership, permission, or constructability", "freeze_gate": "no final benchmark snapshot frozen"},
        limitations=["PDOK municipality geometry verifies Delft administrative containment but not planning or buildability conditions.", "OSM exact-polygon features are provisional coverage observations and may omit mapped or unmapped features.", "Grocery taxonomy is proposed; raw shop tags remain separate and do not establish destination suitability.", "Scale and corridor criteria are proposed project decisions, not effective thresholds.", "Climate evidence is unavailable; accessibility and morphology results are not calculated."],
        approval_record_path=approval_path.relative_to(root).as_posix(),
        supersedes_proposal_id=V1_PROPOSAL_ID,
        selection_criteria_status="PROPOSED_PROJECT_DECISION",
        selection_criteria={"purpose": "station-to-historic-centre rail–canal corridor", "status": "PROPOSED_PROJECT_DECISION", "edges": [{"name": "Oude Lijn", "osm_way_id": "330692263", "role": "western railway edge"}, {"name": "Buitenwatersloot", "osm_way_id": "173906835", "role": "northern canal edge"}, {"name": "Houttuinen", "osm_way_id": "223329783", "role": "southern cycleway/public-realm edge"}], "anchor": {"source_ref": "source-nominatim-delft-anchor-v2", "role": "contextual station anchor only"}},
        scale_parameters={"status": "PROPOSED_PROJECT_DECISION", "area_m2": area, "perimeter_m": perimeter, "purpose": "descriptive facts for review; no pass/fail threshold", "thresholds": None},
        taxonomy_status="PROPOSED",
        map_preview_path=map_path.relative_to(root).as_posix(),
        source_records_path=source_records_path.relative_to(root).as_posix(),
    )

    # Copy the closed v1 state into a new database before appending v2. The
    # original v1 SQLite file is never opened for writes or overwritten.
    v1_db = v1 / "proposal-state.sqlite3"
    if not v1_db.is_file():
        raise ProposalBuildError("v1 proposal-state.sqlite3 is missing")
    v2_db = root / "proposal-state-v2.sqlite3"
    shutil.copy2(v1_db, v2_db)
    with ProjectStateStore(v2_db) as store:
        assert_no_effective_site_conflict(store, project_id)
        artifact_specs = [
            (boundary_path, "artifact-boundary-delft-v2", "application/geo+json", "EPSG:28992", ["artifact-boundary-delft-v1", "artifact-selection-method-delft-v2", "artifact-context-delft-municipality-v2"]),
            (map_path, "artifact-map-preview-delft-v2", "image/svg+xml", None, ["artifact-boundary-delft-v2", "artifact-source-osm-exact-polygon-context"]),
            (approval_path, "artifact-approval-record-delft-v2", "text/markdown", None, ["artifact-boundary-delft-v2"]),
            (selection_path, "artifact-selection-method-delft-v2", "application/geo+json", "EPSG:4326", ["artifact-source-osm-exact-polygon-context"]),
            (municipality_feature_path, "artifact-context-delft-municipality-v2", "application/geo+json", "CRS84", ["artifact-source-pdok-delft-municipality"]),
            (source_records_path, "artifact-source-records-delft-v2", "application/json", None, []),
            (request_manifest_path, "artifact-request-manifest-delft-v2", "application/json", None, []),
            (root / "v1-integrity.json", "artifact-v1-integrity-v2", "application/json", None, ["artifact-boundary-delft-v1"]),
        ]
        raw_ids = {capture.source_id: f"artifact-{capture.source_id}" for capture in captures}
        for capture in captures:
            artifact_specs.append((capture.path, raw_ids[capture.source_id], "application/json", None, []))
        for path, artifact_id, mime, crs, parents in artifact_specs:
            store.create_typed(_artifact(path, root, artifact_id, mime, project_id, created_at, crs=crs, parents=parents), actor="m2-repair-executor", action="RecordArtifact", reason="Retain immutable v2 proposal artifact with provenance and parent links.", resulting_refs=[artifact_id])
        site = Site(id="site-delft-v2", project_id=project_id, version="v2", boundary_artifact_id="artifact-boundary-delft-v2", boundary_sha256=proposal.boundary_sha256, crs="EPSG:28992", vertical_reference=proposal.vertical_reference_status, units="m", dataset_snapshot_ids=[], status=SiteStatus.PROPOSED)
        store.create_typed(site, actor="m2-repair-executor", action="ProposeSite", reason="Append v2 Delft corridor proposal; status remains PROPOSED pending human decision.", changed_refs=proposal.source_refs, resulting_refs=[site.id, site.boundary_artifact_id, proposal.id], supersedes="site-delft-v1", event_payload={"proposal_id": proposal.id, "proposal_version": proposal.version, "supersedes": V1_PROPOSAL_ID, "human_decision_required": True})
        store.create("SiteProposal", proposal.model_dump(mode="json"), entity_id=proposal.id, project_id=project_id, actor="m2-repair-executor", action="RecordSiteProposal", reason="Append v2 approval package while preserving v1 proposal and state.", changed_refs=proposal.source_refs, resulting_refs=[proposal.id, site.id, site.boundary_artifact_id], supersedes=V1_PROPOSAL_ID, event_payload={"proposal_id": proposal.id, "status": proposal.status, "supersedes": V1_PROPOSAL_ID, "human_decision_required": True})
        events = store.events(project_id=project_id)
        v2_event_refs = [event.event_id for event in events if event.target_id in {proposal.id, site.id} and event.sequence > 13]
        store.update(proposal.id, {"ledger_event_refs": v2_event_refs}, expected_revision=1, actor="m2-repair-executor", action="LinkProposalLedgerRefs", reason="Link v2 proposal to append-only supersedes and record events.", changed_refs=v2_event_refs, resulting_refs=[proposal.id], supersedes=V1_PROPOSAL_ID)
    proposal.ledger_event_refs.extend(v2_event_refs)
    proposal_json_path = root / "site-proposal-v2.json"
    _write_json(proposal_json_path, proposal.model_dump(mode="json"))
    # Validate after state/artifact creation, including independent municipal
    # containment, exact query linkage, map completeness, and v1 hashes.
    validate_site_proposal_v2(proposal, root, v1_root=v1)
    return proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--v1-dir", type=Path, default=V1_DEFAULT)
    parser.add_argument("--project-id", default="delft-pilot-project")
    args = parser.parse_args(argv)
    try:
        proposal = build_v2(args.output_dir, v1_root=args.v1_dir, project_id=args.project_id)
    except (ProposalBuildError, SiteProposalV2ValidationError, ValueError, OSError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"proposal_id": proposal.id, "version": proposal.version, "status": proposal.status, "boundary_sha256": proposal.boundary_sha256, "area_m2": next(item.value for item in proposal.measurements if item.name == "area"), "perimeter_m": next(item.value for item in proposal.measurements if item.name == "perimeter")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
