#!/usr/bin/env python3
"""Create an inspectable, non-effective Delft pilot-site proposal.

The command captures small, bounded public-source checks, transforms a fixed
selection envelope to RD New (EPSG:28992), computes planar measurements, and
records only PROPOSED state. It never writes Project.site_id or a HumanDecision.
"""

from __future__ import annotations

import argparse
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
import uuid

from urban_design.geometry import canonical_geometry_hash, polygon_area, polygon_perimeter
from urban_design.models import Artifact, Project, Site, SiteStatus
from urban_design.site_proposal import (
    Measurement,
    SiteProposal,
    SourceRecord,
    TransformRecord,
    assert_no_effective_site_conflict,
    canonical_json_bytes,
    sha256_file,
    validate_site_proposal,
)
from urban_design.store import ProjectStateStore


ANCHOR_URL = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=Delft%20railway%20station%2C%20Netherlands"
PDOK_URL = "https://api.pdok.nl/kadaster/bag/ogc/v2?f=json"
OVERPASS_ENDPOINT = "https://overpass.kumi.systems/api/interpreter"
GDAL_OGR2OGR = "/Applications/QGIS-LTR.app/Contents/MacOS/bin/ogr2ogr"
PRODUCER = "urban-design-m2-site-proposal/0.1"


class ProposalBuildError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload if isinstance(payload, dict) else {"value": payload}))


def _fetch_json(url: str, *, data: bytes | None = None, timeout: int = 45) -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "DelftPilotEvidence/0.1 (urban-design prototype)", "Accept": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except Exception as exc:  # pragma: no cover - depends on external service
        raise ProposalBuildError(f"source retrieval failed for {url}: {exc}") from exc
    if not body:
        raise ProposalBuildError(f"source retrieval returned empty body for {url}")
    try:
        json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProposalBuildError(f"source retrieval was not JSON for {url}") from exc
    return body


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _artifact(path: Path, root: Path, *, artifact_id: str, mime: str, crs: str | None, project_id: str, created_at: datetime, parent_artifact_ids: list[str] | None = None) -> Artifact:
    return Artifact(
        id=artifact_id,
        type="source-response" if mime == "application/json" else "boundary-preview",
        uri=_relative(path, root),
        sha256=sha256_file(path),
        mime=mime,
        crs=crs,
        producer=PRODUCER,
        created_at=created_at,
        project_id=project_id,
        size_bytes=path.stat().st_size,
        parent_artifact_ids=parent_artifact_ids or [],
    )


def _geometry_from_ogr(transformed: Path) -> dict[str, object]:
    payload = json.loads(transformed.read_text(encoding="utf-8"))
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features")
        if not isinstance(features, list) or len(features) != 1:
            raise ProposalBuildError("GDAL output must contain one boundary feature")
        geometry = features[0].get("geometry") if isinstance(features[0], dict) else None
    elif payload.get("type") == "Feature":
        geometry = payload.get("geometry")
    else:
        geometry = payload
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ProposalBuildError("GDAL output did not contain Polygon/MultiPolygon geometry")
    return {"type": geometry["type"], "coordinates": geometry["coordinates"]}


def _run_transform(input_path: Path, transformed_path: Path) -> tuple[str, str]:
    if not Path(GDAL_OGR2OGR).exists():
        raise ProposalBuildError(f"pinned GDAL transform tool is missing: {GDAL_OGR2OGR}")
    command = [GDAL_OGR2OGR, "-f", "GeoJSON", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:28992", str(transformed_path), str(input_path)]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProposalBuildError(f"deterministic CRS transform failed: {exc}") from exc
    version = subprocess.run([GDAL_OGR2OGR, "--version"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    return " ".join(command), version or "GDAL version unavailable"


def _svg_preview(geometry: dict[str, object], path: Path, *, area: float, perimeter: float, proposal_id: str) -> None:
    coords = geometry["coordinates"][0] if geometry["type"] == "Polygon" else geometry["coordinates"][0][0]
    points = [(float(point[0]), float(point[1])) for point in coords]
    min_x, max_x = min(point[0] for point in points), max(point[0] for point in points)
    min_y, max_y = min(point[1] for point in points), max(point[1] for point in points)
    pad = max(max_x - min_x, max_y - min_y) * 0.16
    width, height = 920, 640
    scale = min((width - 120) / (max_x - min_x + 2 * pad), (height - 150) / (max_y - min_y + 2 * pad))

    def project(point: tuple[float, float]) -> tuple[float, float]:
        return (60 + (point[0] - min_x + pad) * scale, height - 85 - (point[1] - min_y + pad) * scale)

    polygon = " ".join(f"{x:.2f},{y:.2f}" for x, y in (project(point) for point in points))
    label = html.escape(proposal_id)
    content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#f6f3ed"/>
<text x="42" y="42" font-family="sans-serif" font-size="24" font-weight="700" fill="#17212b">Delft pilot site — PROPOSED</text>
<text x="42" y="70" font-family="sans-serif" font-size="15" fill="#58636d">Human decision required · EPSG:28992 · metres</text>
<polygon points="{polygon}" fill="#d6e8e2" stroke="#0b6e69" stroke-width="4"/>
<line x1="820" y1="160" x2="820" y2="92" stroke="#17212b" stroke-width="3"/><path d="M820 82 l-9 18 h18 z" fill="#17212b"/><text x="808" y="73" font-family="sans-serif" font-size="14" fill="#17212b">N</text>
<text x="42" y="{height - 58}" font-family="monospace" font-size="13" fill="#17212b">Area (computed): {area:.2f} m²   Perimeter (computed): {perimeter:.2f} m</text>
<text x="42" y="{height - 32}" font-family="sans-serif" font-size="12" fill="#58636d">Boundary bytes and provenance are retained beside this preview. Display only; metrics use projected coordinates.</text>
</svg>'''
    path.write_text(content, encoding="utf-8")


def _counts(overpass_payload: dict[str, object]) -> dict[str, int]:
    elements = overpass_payload.get("elements", [])
    if not isinstance(elements, list):
        return {"elements": 0, "highway_ways": 0, "pedestrian_ways": 0, "shop_nodes": 0, "grocery_nodes": 0, "public_space_ways": 0}
    highway = pedestrian = shops = groceries = public_space = 0
    for item in elements:
        if not isinstance(item, dict):
            continue
        tags = item.get("tags", {})
        if not isinstance(tags, dict):
            continue
        if item.get("type") == "way" and "highway" in tags:
            highway += 1
            if tags.get("highway") == "pedestrian":
                pedestrian += 1
        if item.get("type") == "node" and "shop" in tags:
            shops += 1
            if tags.get("shop") in {"supermarket", "convenience", "grocery"}:
                groceries += 1
        if item.get("type") == "way" and (tags.get("highway") == "pedestrian" or tags.get("leisure") in {"park", "square", "garden"}):
            public_space += 1
    return {"elements": len(elements), "highway_ways": highway, "pedestrian_ways": pedestrian, "shop_nodes": shops, "grocery_nodes": groceries, "public_space_ways": public_space}


def build_proposal(output_dir: str | Path, *, project_id: str = "delft-pilot-project", fetch_live: bool = True) -> SiteProposal:
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "sources" / "raw").mkdir(parents=True, exist_ok=True)
    created_at = utc_now()
    proposal_id = "site-proposal-delft-v1"
    raw_dir = root / "sources" / "raw"

    anchor_path = raw_dir / "nominatim-delft-railway-station.json"
    pdok_path = raw_dir / "pdok-bag-landing.json"
    pdok_collections_path = raw_dir / "pdok-bag-collections.json"
    overpass_path = raw_dir / "osm-overpass-coverage.json"
    if fetch_live:
        anchor_path.write_bytes(_fetch_json(ANCHOR_URL))
        pdok_path.write_bytes(_fetch_json(PDOK_URL))
        pdok_collections_path.write_bytes(_fetch_json("https://api.pdok.nl/kadaster/bag/ogc/v2/collections?f=json"))
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))[0]
        lat, lon = float(anchor["lat"]), float(anchor["lon"])
        query = '[out:json][timeout:15];(way["highway"](around:250,%s,%s);node["shop"](around:250,%s,%s);way["leisure"](around:250,%s,%s););out tags center;' % ((lat, lon) * 3)
        overpass_url = OVERPASS_ENDPOINT + "?data=" + urllib.parse.quote(query, safe="")
        overpass_path.write_bytes(_fetch_json(overpass_url, timeout=60))
    for path in (anchor_path, pdok_path, overpass_path):
        if not path.exists() or path.stat().st_size == 0:
            raise ProposalBuildError(f"required source artifact missing: {path}")

    anchor_payload = json.loads(anchor_path.read_text(encoding="utf-8"))
    if not isinstance(anchor_payload, list) or not anchor_payload:
        raise ProposalBuildError("Nominatim returned no Delft railway station anchor")
    anchor = anchor_payload[0]
    lat, lon = float(anchor["lat"]), float(anchor["lon"])
    bbox = [float(value) for value in anchor.get("boundingbox", [])]
    if len(bbox) != 4:
        raise ProposalBuildError("Nominatim anchor did not contain a four-value bounding box")

    # A fixed 0.003° x 0.0036° envelope around the sourced station anchor is
    # the explicit project-selection method. The envelope is not a municipal
    # boundary and is retained as a decision input for human review.
    half_lat, half_lon = 0.0015, 0.0018
    ring_wgs84 = [[lon - half_lon, lat - half_lat], [lon + half_lon, lat - half_lat], [lon + half_lon, lat + half_lat], [lon - half_lon, lat + half_lat], [lon - half_lon, lat - half_lat]]
    if not all(bbox[0] <= point[1] <= bbox[1] and bbox[2] <= point[0] <= bbox[3] for point in ring_wgs84):
        raise ProposalBuildError("selection envelope is not contained by the sourced Delft context bbox")
    selection_path = root / "selection-method-wgs84.geojson"
    selection_payload = {"type": "Feature", "properties": {"selection": "fixed envelope around sourced Delft railway station anchor", "anchor_source": _relative(anchor_path, root), "half_width_degrees": half_lon, "half_height_degrees": half_lat}, "geometry": {"type": "Polygon", "coordinates": [ring_wgs84]}}
    _write_json(selection_path, selection_payload)
    transformed = root / "_transformed-rd.geojson"
    command, tool_version = _run_transform(selection_path, transformed)
    geometry = _geometry_from_ogr(transformed)
    transformed.unlink(missing_ok=True)
    geometry_hash = canonical_geometry_hash(geometry)
    area = polygon_area(geometry)
    perimeter = polygon_perimeter(geometry)
    # Scale is intentionally an inspectable observation only. No area or
    # perimeter threshold is an effective project parameter before approval.

    boundary_path = root / "boundary-epsg28992.geojson"
    boundary_payload = {"type": geometry["type"], "coordinates": geometry["coordinates"], "crs": {"type": "name", "properties": {"name": "EPSG:28992"}}}
    boundary_path.write_bytes(canonical_json_bytes(boundary_payload))
    preview_path = root / "map-preview.svg"
    _svg_preview(geometry, preview_path, area=area, perimeter=perimeter, proposal_id=proposal_id)

    overpass_payload = json.loads(overpass_path.read_text(encoding="utf-8"))
    coverage_counts = _counts(overpass_payload)
    osm3s = overpass_payload.get("osm3s", {}) if isinstance(overpass_payload, dict) else {}
    overpass_version = f"{overpass_payload.get('generator', 'Overpass API unspecified')}; osm_base={osm3s.get('timestamp_osm_base', 'unspecified')}"
    pdok_payload = json.loads(pdok_path.read_text(encoding="utf-8"))
    pdok_collections_url = next((link.get("href") for link in pdok_payload.get("links", []) if isinstance(link, dict) and link.get("rel") == "data"), None)
    pdok_collections_payload = json.loads(pdok_collections_path.read_text(encoding="utf-8")) if pdok_collections_path.exists() and pdok_collections_path.stat().st_size else {}
    collections = pdok_collections_payload.get("collections", []) if isinstance(pdok_collections_payload, dict) else []
    collection_ids = [item.get("id") for item in collections if isinstance(item, dict) and isinstance(item.get("id"), str)]
    sources = [
        SourceRecord(id="source-nominatim-delft-anchor", source_class="DATASET_OBSERVATION", availability="OBSERVED", publisher="OpenStreetMap Nominatim", source_identity=ANCHOR_URL, query="Delft railway station, Netherlands; limit=1", retrieved_at=created_at, version="Nominatim jsonv2 response; endpoint version unspecified", license="ODbL 1.0; attribution required", attribution="© OpenStreetMap contributors", parameters={"format": "jsonv2", "limit": 1}, artifact_path=_relative(anchor_path, root), artifact_sha256=sha256_file(anchor_path), artifact_size_bytes=anchor_path.stat().st_size, coverage={"anchor_lat": lat, "anchor_lon": lon, "geocoder_bbox_wgs84": bbox}, limitations=["Geocoder result is an anchor, not an authoritative municipal boundary."]),
        SourceRecord(id="source-osm-overpass-coverage", source_class="DATASET_OBSERVATION", availability="OBSERVED", publisher="OpenStreetMap via Overpass", source_identity=OVERPASS_ENDPOINT, query="Bounded 250 m radius around sourced Delft railway station; highways, shops, leisure", retrieved_at=created_at, version=overpass_version, license="ODbL 1.0; attribution required", attribution="© OpenStreetMap contributors", parameters={"radius_m": 250, "anchor_lat": lat, "anchor_lon": lon}, artifact_path=_relative(overpass_path, root), artifact_sha256=sha256_file(overpass_path), artifact_size_bytes=overpass_path.stat().st_size, coverage=coverage_counts, limitations=["Sampled OSM features are indicative coverage checks and are not complete network, destination, morphology, or public-space datasets."]),
        SourceRecord(id="source-pdok-bag-feasibility", source_class="DATASET_OBSERVATION", availability="OBSERVED", publisher="PDOK / Kadaster", source_identity=PDOK_URL, query="OGC API landing and collection metadata; collection discovery retained for later building/address retrieval", retrieved_at=created_at, version="OGC API landing metadata; dataset version not supplied", license="Public Domain Mark 1.0 (dataset link); verify current terms before freezing", attribution="PDOK / Kadaster", parameters={"landing": PDOK_URL, "collections": pdok_collections_url}, artifact_path=_relative(pdok_path, root), artifact_sha256=sha256_file(pdok_path), artifact_size_bytes=pdok_path.stat().st_size, coverage={"landing_title": pdok_payload.get("title"), "collections_url": pdok_collections_url, "collections_artifact_path": _relative(pdok_collections_path, root) if pdok_collections_path.exists() else None, "collections_artifact_sha256": sha256_file(pdok_collections_path) if pdok_collections_path.exists() else None, "collection_count": len(collection_ids), "collection_ids": collection_ids[:20], "building_data_indicated": True}, limitations=["Only service metadata was checked in M2; no BAG features are frozen or used for measurements."]),
        SourceRecord(id="source-climate-future-check", source_class="UNAVAILABLE", availability="UNAVAILABLE", publisher="KNMI / Dutch climate data providers", source_identity="https://data.knmi.nl/", query="No climate layer retrieved during M2 site proposal", retrieved_at=created_at, version="not retrieved", license="To be verified for the selected climate product", attribution="KNMI attribution to be confirmed", validation_status="UNAVAILABLE", limitations=["Climate exposure and future weather evidence remains unavailable until a later approved dataset plan."]),
    ]
    selection_source = SourceRecord(id="source-project-selection-method", source_class="PROJECT_DECISION", availability="OBSERVED", publisher="Delft pilot project", source_identity="local:selection-method-wgs84.geojson", query="Fixed envelope around the Nominatim Delft railway station anchor; half-size 0.0015° latitude x 0.0018° longitude", retrieved_at=created_at, version="v1", license="Project decision record", attribution="Project decision; human approval still required", parameters={"half_width_degrees": half_lon, "half_height_degrees": half_lat, "anchor_source_ref": "source-nominatim-delft-anchor"}, artifact_path=_relative(selection_path, root), artifact_sha256=sha256_file(selection_path), artifact_size_bytes=selection_path.stat().st_size, coverage={"anchor_source_ref": "source-nominatim-delft-anchor", "input_crs": "EPSG:4326", "output_crs": "EPSG:28992"}, limitations=["This is a proposal selection rule, not a municipal boundary or planning designation."])
    sources.append(selection_source)
    source_json_path = root / "sources" / "source-records.json"
    source_json_path.write_bytes(canonical_json_bytes({"records": [record.model_dump(mode="json") for record in sources]}))

    approval_path = root / "approval-record.md"
    approval_path.write_text(f"""# Human approval record — Delft site proposal

Decision status: **HUMAN_DECISION_REQUIRED**

Exact proposal: `{proposal_id}` version `v1`; boundary artifact `{_relative(boundary_path, root)}`. The boundary hash is `{sha256_file(boundary_path)}` and must match the retained bytes.

The reviewer must inspect the boundary bytes, projected CRS, computed measurements, source records, map preview, and limitations before deciding.

- **APPROVE**: append a human decision with actor, timestamp, reason, and this exact proposal reference. A later state transition may then make a Site effective and set `Project.site_id`; dataset snapshots still require their own provenance and freeze checks.
- **REJECT**: append a human rejection with actor, timestamp, reason, and this exact proposal reference. The proposal and all artifacts remain inspectable; `Project.site_id` stays unset. A replacement must append a new proposal/version.

No human decision event is created by this package.
""", encoding="utf-8")

    measurements = [
        Measurement(name="area", value=area, unit="m2", method="shoelace area on projected 2D exterior ring", crs="EPSG:28992"),
        Measurement(name="perimeter", value=perimeter, unit="m", method="Euclidean exterior-ring perimeter on projected 2D coordinates", crs="EPSG:28992"),
    ]
    proposal = SiteProposal(
        id=proposal_id,
        project_id=project_id,
        version="v1",
        boundary_artifact_path=_relative(boundary_path, root),
        boundary_sha256=sha256_file(boundary_path),
        boundary_size_bytes=boundary_path.stat().st_size,
        boundary_mime="application/geo+json",
        geometry_sha256=geometry_hash,
        geometry=geometry,
        geometry_type=str(geometry["type"]),
        horizontal_crs="EPSG:28992",
        units="m",
        vertical_reference_status="NOT_APPLICABLE_2D_BOUNDARY; no vertical reference supplied",
        transform=TransformRecord(input_crs="EPSG:4326", output_crs="EPSG:28992", method="GDAL/OGR deterministic reprojection", tool=GDAL_OGR2OGR, tool_version=tool_version, command=command, axis_order="traditional GIS axis order: longitude, latitude input", vertical_reference_status="NOT_APPLICABLE_2D_BOUNDARY"),
        producer=PRODUCER,
        created_at=created_at,
        selection_method="Fixed WGS84 envelope around the Nominatim Delft railway station anchor, then deterministic EPSG:4326→EPSG:28992 transform; see source-project-selection-method.",
        rationale="Compact central Delft study area selected around a sourced railway-station anchor to support a later pedestrian-network and destination feasibility study while keeping the boundary inspectable and human-contestable.",
        source_refs=[record.id for record in sources],
        parent_refs=[_relative(selection_path, root), _relative(anchor_path, root)],
        measurements=measurements,
        delft_context={"containment_status": "WITHIN_CONTEXT_BBOX", "evidence_ref": "source-nominatim-delft-anchor", "context_type": "geocoder_anchor_bbox", "bbox_wgs84": bbox, "method": "all envelope vertices fall inside the sourced anchor bounding box"},
        dataset_plan={"pedestrian_network": "retrieve and validate OSM/PDOK network after site approval; preserve query, date, licence, and snapshot hash", "grocery_destinations": "retrieve OSM shop features and an authoritative address/building cross-check after approval", "morphology": "retrieve PDOK BAG building footprints and relevant land-use layers after approval", "public_space": "retrieve OSM/municipal public-space layers and validate coverage after approval", "climate": "select a KNMI climate product with version and scenario metadata after approval", "freeze_gate": "no benchmark snapshot is frozen by this proposal"},
        limitations=["Geocoder bbox is contextual evidence, not a legal municipality boundary.", "OSM and PDOK checks are provisional service/coverage observations; missing features remain possible.", "No accessibility, morphology, climate, or design constraints are activated in M2.", "Metrics are deterministic planar calculations in EPSG:28992 and do not imply planning thresholds."],
        approval_record_path=_relative(approval_path, root),
    )
    validate_site_proposal(proposal, root)

    proposal_json_path = root / "site-proposal.json"
    proposal_json_path.write_bytes(canonical_json_bytes(proposal.model_dump(mode="json")))
    package_path = root / "site-proposal.md"
    package_path.write_text(f"""# Delft pilot-site proposal `{proposal.id}`

Status: **PROPOSED** · version `{proposal.version}` · human decision: **HUMAN_DECISION_REQUIRED**

This package proposes a compact central Delft study area around the sourced Delft railway-station anchor. It is an approval package, not an effective site or frozen dataset.

## Boundary and deterministic facts

- Boundary: `{proposal.boundary_artifact_path}`
- MIME: `{proposal.boundary_mime}`
- SHA-256: `{proposal.boundary_sha256}`
- Size: `{proposal.boundary_size_bytes}` bytes
- Geometry hash: `{proposal.geometry_sha256}`
- Horizontal CRS: `{proposal.horizontal_crs}`; units: `{proposal.units}`
- Area: `{area:.6f} m²` (`COMPUTED_RESULT`)
- Perimeter: `{perimeter:.6f} m` (`COMPUTED_RESULT`)
- Preview: `map-preview.svg`

## Selection and evidence

Selection method: {proposal.selection_method}

The retained source records in `sources/source-records.json` separate project decisions, dataset observations, computed results, and unavailable climate evidence. OSM/Overpass coverage counts are indicative only (`{json.dumps(coverage_counts, sort_keys=True)}`). PDOK BAG metadata confirms a service/collection discovery path, but no building features are frozen.

## What the later data plan can support

The anchor and bounded OSM check provide a traceable feasibility starting point for pedestrian-network and grocery-destination retrieval. PDOK BAG metadata provides a path for later morphology/building evidence. Public-space observations are provisional OSM tags. Climate evidence is explicitly unavailable in this package and must be selected and versioned later.

## Human decision

See `{proposal.approval_record_path}` for the exact APPROVE/REJECT consequences. This package creates no HumanDecision and does not set `Project.site_id`.
""", encoding="utf-8")

    # Persist immutable artifacts and proposed state. The project is created
    # without a site_id; the proposal is therefore inspectable but ineffective.
    with ProjectStateStore(root / "proposal-state.sqlite3") as store:
        assert_no_effective_site_conflict(store, project_id)
        project = Project(id=project_id, name="Delft pilot project", schema_version="m2", site_id=None)
        store.create_typed(project, actor="m2-executor", action="CreateProject", reason="Create project container for a proposed Delft site; no site is effective.")
        artifact_paths = [
            (boundary_path, "artifact-boundary-delft-v1", "application/geo+json", "EPSG:28992"),
            (preview_path, "artifact-map-preview-delft-v1", "image/svg+xml", None),
            (approval_path, "artifact-approval-record-delft-v1", "text/markdown", None),
            (selection_path, "artifact-selection-method-delft-v1", "application/geo+json", "EPSG:4326"),
            (source_json_path, "artifact-source-records-delft-v1", "application/json", None),
        ] + [(path, f"artifact-source-{path.stem}", "application/json", None) for path in (anchor_path, overpass_path, pdok_path) if path.exists()]
        if pdok_collections_path.exists():
            artifact_paths.append((pdok_collections_path, "artifact-source-pdok-bag-collections", "application/json", None))
        artifact_records = []
        for path, artifact_id, mime, crs in artifact_paths:
            parents = ["artifact-selection-method-delft-v1", "artifact-source-nominatim-delft-railway-station"] if artifact_id == "artifact-boundary-delft-v1" else []
            record = _artifact(path, root, artifact_id=artifact_id, mime=mime, crs=crs, project_id=project_id, created_at=created_at, parent_artifact_ids=parents)
            store.create_typed(record, actor="m2-executor", action="RecordArtifact", reason="Retain immutable proposal input/output artifact with hash and provenance.", resulting_refs=[record.id])
            artifact_records.append(record)
        site = Site(id="site-delft-v1", project_id=project_id, version="v1", boundary_artifact_id="artifact-boundary-delft-v1", boundary_sha256=proposal.boundary_sha256, crs="EPSG:28992", vertical_reference=proposal.vertical_reference_status, units="m", dataset_snapshot_ids=[], status=SiteStatus.PROPOSED)
        store.create_typed(site, actor="m2-executor", action="ProposeSite", reason="Record approval-ready Delft boundary; status remains PROPOSED pending explicit human decision.", changed_refs=proposal.source_refs, resulting_refs=[site.id, site.boundary_artifact_id, proposal.id], event_payload={"proposal_id": proposal.id, "proposal_version": proposal.version, "human_decision_required": True})
        store.create("SiteProposal", proposal.model_dump(mode="json"), entity_id=proposal.id, project_id=project_id, actor="m2-executor", action="RecordSiteProposal", reason="Persist the complete Delft approval package without adopting the site.", changed_refs=proposal.source_refs, resulting_refs=[proposal.id, site.id, site.boundary_artifact_id], event_payload={"proposal_id": proposal.id, "status": proposal.status, "human_decision_required": True})
        # Link the immutable event identifiers through a new proposal revision;
        # this remains append-only and does not change its PROPOSED status.
        events = store.events(project_id=project_id)
        proposal_event_refs = [event.event_id for event in events if event.target_id in {proposal.id, site.id}]
        store.update(proposal.id, {"ledger_event_refs": proposal_event_refs}, expected_revision=1, actor="m2-executor", action="LinkProposalLedgerRefs", reason="Link proposal to its append-only ledger events for audit replay.", changed_refs=proposal_event_refs, resulting_refs=[proposal.id])
    proposal.ledger_event_refs.extend(proposal_event_refs)
    proposal_json_path.write_bytes(canonical_json_bytes(proposal.model_dump(mode="json")))
    return proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--project-id", default="delft-pilot-project")
    parser.add_argument("--offline", action="store_true", help="use already retained source files in output-dir/sources/raw")
    args = parser.parse_args(argv)
    try:
        proposal = build_proposal(args.output_dir, project_id=args.project_id, fetch_live=not args.offline)
    except (ProposalBuildError, ValueError, OSError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"proposal_id": proposal.id, "version": proposal.version, "status": proposal.status, "boundary_sha256": proposal.boundary_sha256, "area_m2": next(item.value for item in proposal.measurements if item.name == "area"), "perimeter_m": next(item.value for item in proposal.measurements if item.name == "perimeter")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
