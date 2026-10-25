#!/usr/bin/env python3
"""Create the M2-R02 readable map revision without changing the v2 boundary.

This script consumes only the retained v2 package. It copies v2 into a
byte-checked parent subtree, transforms retained OSM geometry with the pinned
GDAL tool, clips context geometry to a projected-metre viewport, renders a
new SVG and PNG, and appends a proposed v3 package to a copied ledger.
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
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from urban_design.geometry import canonical_geometry_hash
from urban_design.models import Artifact, Site, SiteStatus
from urban_design.site_proposal import SiteProposal, V2SourceRecord, assert_no_effective_site_conflict, canonical_json_bytes, sha256_file
from urban_design.site_proposal_v3 import SiteProposalV3ValidationError, validate_site_proposal_v3, verify_package_integrity
from urban_design.store import ProjectStateStore


# Importing the M2-R01 script is safe: its network work is called only by its
# build_v2() entry point, which this revision never invokes.
from scripts.create_site_proposal_v2 import GDAL_OGR2OGR, _osm_layers, _way_points


PRODUCER = "urban-design-m2-repair-v3/0.1"
V2_DEFAULT = Path("artifacts/milestone2-site-proposal-v2/run-20260915T013000Z")
V3_PROPOSAL_ID = "site-proposal-delft-v3"
V2_PROPOSAL_ID = "site-proposal-delft-v2"
V2_BOUNDARY_HASH = "sha256:671117c91589b20ca28ffb39df1eb1697f12e42e0e7a3a5b969e7f7b5c1dc9c4"
QGIS_PYTHON = "/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3"


class ProposalBuildError(RuntimeError):
    """Raised when a retained-byte map revision cannot be built."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _hash_manifest(package_root: Path, output_path: Path, schema_version: str) -> dict[str, Any]:
    entries = []
    for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
        entries.append({"path": path.relative_to(package_root).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if not entries:
        raise ProposalBuildError("parent package contains no files")
    payload = {"schema_version": schema_version, "package_root": str(package_root), "files": entries}
    _write_json(output_path, payload)
    return payload


def _geojson_features(elements: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Convert retained OSM elements into a transformable GeoJSON collection."""

    features: list[dict[str, Any]] = []
    for element in elements:
        element_type = element.get("type")
        tags = element.get("tags", {}) if isinstance(element.get("tags", {}), Mapping) else {}
        if element_type == "way":
            points = [[float(point["lon"]), float(point["lat"])] for point in element.get("geometry", []) if isinstance(point, Mapping) and "lon" in point and "lat" in point]
            if len(points) < 2:
                continue
            if points[0] == points[-1] and len(points) >= 4:
                geometry = {"type": "Polygon", "coordinates": [points]}
            else:
                geometry = {"type": "LineString", "coordinates": points}
        elif element_type == "node" and "lon" in element and "lat" in element:
            geometry = {"type": "Point", "coordinates": [float(element["lon"]), float(element["lat"])]}
        else:
            continue
        features.append({"type": "Feature", "id": str(element.get("id")), "properties": dict(tags), "geometry": geometry})
    return {"type": "FeatureCollection", "features": features}


def _transform_context(raw_path: Path, output_path: Path, root: Path) -> tuple[str, str]:
    """Transform retained OSM geometry to EPSG:28992 with pinned GDAL."""

    if not Path(GDAL_OGR2OGR).is_file():
        raise ProposalBuildError(f"pinned GDAL transform tool is missing: {GDAL_OGR2OGR}")
    command = [GDAL_OGR2OGR, "-f", "GeoJSON", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:28992", "-nlt", "GEOMETRY", str(output_path), str(raw_path)]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=90)
        version = subprocess.run([GDAL_OGR2OGR, "--version"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProposalBuildError(f"deterministic context transform failed: {exc}") from exc
    return " ".join(command), version or "GDAL version unavailable"


def _coords(geometry: Mapping[str, Any]) -> list[list[tuple[float, float]]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "LineString":
        return [[(float(point[0]), float(point[1])) for point in coordinates]]
    if kind == "Polygon":
        return [[(float(point[0]), float(point[1])) for point in ring] for ring in coordinates]
    if kind == "MultiLineString":
        return [[(float(point[0]), float(point[1])) for point in line] for line in coordinates]
    if kind == "MultiPolygon":
        return [[(float(point[0]), float(point[1])) for point in ring] for polygon in coordinates for ring in polygon]
    return []


def _clip_segment(a: tuple[float, float], b: tuple[float, float], viewport: tuple[float, float, float, float]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    xmin, ymin, xmax, ymax = viewport
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - xmin), (dx, xmax - a[0]), (-dy, a[1] - ymin), (dy, ymax - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        ratio = q / p
        if p < 0:
            if ratio > t1:
                return None
            t0 = max(t0, ratio)
        else:
            if ratio < t0:
                return None
            t1 = min(t1, ratio)
    return ((a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy))


def _clip_polyline(points: Sequence[tuple[float, float]], viewport: tuple[float, float, float, float]) -> list[list[tuple[float, float]]]:
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for first, second in zip(points, points[1:]):
        clipped = _clip_segment(first, second, viewport)
        if clipped is None:
            if current:
                segments.append(current)
                current = []
            continue
        start, end = clipped
        if not current or math.dist(current[-1], start) > 1e-7:
            if current:
                segments.append(current)
            current = [start, end]
        else:
            current.append(end)
    if current:
        segments.append(current)
    return [segment for segment in segments if len(segment) >= 2]


def _clip_polygon(points: Sequence[tuple[float, float]], viewport: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    xmin, ymin, xmax, ymax = viewport
    output = list(points)
    if output and output[0] == output[-1]:
        output = output[:-1]
    for edge, boundary in (("left", xmin), ("right", xmax), ("bottom", ymin), ("top", ymax)):
        if not output:
            return []
        clipped: list[tuple[float, float]] = []
        for current, previous in zip(output, output[-1:] + output[:-1]):
            def inside(point: tuple[float, float]) -> bool:
                return point[0] >= boundary if edge == "left" else point[0] <= boundary if edge == "right" else point[1] >= boundary if edge == "bottom" else point[1] <= boundary
            current_inside, previous_inside = inside(current), inside(previous)
            if current_inside != previous_inside:
                dx, dy = current[0] - previous[0], current[1] - previous[1]
                if edge in {"left", "right"}:
                    x = boundary
                    y = previous[1] + dy * ((boundary - previous[0]) / dx) if abs(dx) > 1e-12 else previous[1]
                else:
                    y = boundary
                    x = previous[0] + dx * ((boundary - previous[1]) / dy) if abs(dy) > 1e-12 else previous[0]
                clipped.append((x, y))
            if current_inside:
                clipped.append(current)
        output = clipped
    return output + ([output[0]] if output and output[0] != output[-1] else [])


def _projector(viewport: tuple[float, float, float, float], frame: tuple[float, float, float, float]):
    xmin, ymin, xmax, ymax = viewport
    left, top, width, height = frame
    scale = min(width / (xmax - xmin), height / (ymax - ymin))
    used_width, used_height = (xmax - xmin) * scale, (ymax - ymin) * scale
    offset_x = left + (width - used_width) / 2.0 - xmin * scale
    offset_y = top + (height - used_height) / 2.0 + ymax * scale
    return lambda point: (offset_x + point[0] * scale, offset_y - point[1] * scale), scale


def _fmt_points(points: Iterable[tuple[float, float]], project) -> str:
    return " ".join(f"{project(point)[0]:.2f},{project(point)[1]:.2f}" for point in points)


def _feature_point(features: Sequence[Mapping[str, Any]], viewport: tuple[float, float, float, float]) -> tuple[float, float] | None:
    for feature in features:
        for ring in _coords(feature.get("geometry", {})):
            for point in ring:
                if viewport[0] <= point[0] <= viewport[2] and viewport[1] <= point[1] <= viewport[3]:
                    return point
    return None


def _map_svg_v3(path: Path, boundary: Mapping[str, Any], projected_context: Mapping[str, Any], source_records: Sequence[V2SourceRecord], proposal_id: str, viewport: tuple[float, float, float, float], margin_m: float) -> dict[str, Any]:
    frame = (44.0, 100.0, 790.0, 590.0)
    viewbox = (0.0, 0.0, 1240.0, 850.0)
    project, scale = _projector(viewport, frame)
    features = [feature for feature in projected_context.get("features", []) if isinstance(feature, Mapping)]
    by_id = {str(feature.get("id")): feature for feature in features}
    groups: dict[str, list[Mapping[str, Any]]] = {"water": [], "public": [], "buildings": [], "roads": [], "rail": []}
    raw_properties = {str(feature.get("id")): feature.get("properties", {}) for feature in features}
    for feature in features:
        props = feature.get("properties", {}) if isinstance(feature.get("properties", {}), Mapping) else {}
        if props.get("waterway") or props.get("natural") == "water" or props.get("landuse") in {"reservoir", "basin"}:
            groups["water"].append(feature)
        if props.get("highway") == "pedestrian" or props.get("leisure") or props.get("landuse") in {"park", "recreation_ground", "grass"}:
            groups["public"].append(feature)
        if props.get("building"):
            groups["buildings"].append(feature)
        if props.get("highway"):
            groups["roads"].append(feature)
        if props.get("railway"):
            groups["rail"].append(feature)

    def paths_for(feature: Mapping[str, Any], style: str) -> str:
        geometry = feature.get("geometry", {})
        kind = geometry.get("type")
        output: list[str] = []
        for ring in _coords(geometry):
            if kind in {"Polygon", "MultiPolygon"}:
                clipped = _clip_polygon(ring, viewport)
                if len(clipped) >= 4:
                    output.append(f'<polygon data-source-id="{html.escape(str(feature.get("id")))}" points="{_fmt_points(clipped, project)}" {style}/>')
            else:
                for segment in _clip_polyline(ring, viewport):
                    output.append(f'<polyline data-source-id="{html.escape(str(feature.get("id")))}" points="{_fmt_points(segment, project)}" {style}/>')
        return "".join(output)

    water = "".join(paths_for(feature, 'fill="none" stroke="#2e8da8" stroke-width="3.6" opacity="0.95"') for feature in groups["water"])
    public = "".join(paths_for(feature, 'fill="none" stroke="#4f8e68" stroke-width="2.6" stroke-dasharray="5 4" opacity="0.9"') for feature in groups["public"])
    buildings = "".join(paths_for(feature, 'fill="#cfc7b7" fill-opacity="0.9" stroke="#8f887d" stroke-width="0.8"') for feature in groups["buildings"])
    roads = "".join(paths_for(feature, 'fill="none" stroke="#a08f7d" stroke-width="1.8" opacity="0.9"') for feature in groups["roads"])
    rail = "".join(paths_for(feature, 'fill="none" stroke="#303943" stroke-width="4.4" stroke-dasharray="10 5"') for feature in groups["rail"])
    boundary_geometry = boundary
    boundary_ring = [(float(point[0]), float(point[1])) for point in boundary_geometry["coordinates"][0]]
    clipped_boundary = _clip_polygon(boundary_ring, viewport)
    if not clipped_boundary:
        raise ProposalBuildError("boundary is outside map viewport")
    boundary_bbox = (min(point[0] for point in clipped_boundary), min(point[1] for point in clipped_boundary), max(point[0] for point in clipped_boundary), max(point[1] for point in clipped_boundary))
    boundary_markup = f'<polygon data-boundary="true" points="{_fmt_points(clipped_boundary, project)}" fill="#006d68" fill-opacity="0.24" stroke="#004f4b" stroke-width="5.2"/>'

    station = by_id.get("3376839743")
    station_point = None
    if station and station.get("geometry", {}).get("type") == "Point":
        coords = station["geometry"]["coordinates"]
        station_point = (float(coords[0]), float(coords[1]))
    marker_markup = ""
    if station_point is not None and viewport[0] <= station_point[0] <= viewport[2] and viewport[1] <= station_point[1] <= viewport[3]:
        sx, sy = project(station_point)
        marker_markup = f'<circle data-source-id="3376839743" cx="{sx:.2f}" cy="{sy:.2f}" r="10" fill="#a43b54" stroke="#ffffff" stroke-width="2.5"/><text x="{sx + 14:.2f}" y="{sy - 12:.2f}" class="map-label">Delft station</text>'
    for feature in features:
        props = feature.get("properties", {}) if isinstance(feature.get("properties", {}), Mapping) else {}
        if props.get("shop") and feature.get("geometry", {}).get("type") == "Point":
            coords = feature["geometry"]["coordinates"]
            point = (float(coords[0]), float(coords[1]))
            if viewport[0] <= point[0] <= viewport[2] and viewport[1] <= point[1] <= viewport[3]:
                sx, sy = project(point)
                marker_markup += f'<circle data-source-id="{html.escape(str(feature.get("id")))}" cx="{sx:.2f}" cy="{sy:.2f}" r="5" fill="#d97941" stroke="#ffffff" stroke-width="1.5"/>'

    labels: list[str] = []
    for way_id, label in (("330692263", "Oude Lijn railway"), ("173906835", "Buitenwatersloot canal"), ("223329783", "Houttuinen")):
        feature = by_id.get(way_id)
        if feature:
            point = _feature_point([feature], viewport)
            if point is not None:
                x, y = project(point)
                labels.append(f'<text x="{min(max(x + 8, frame[0] + 8), frame[0] + frame[2] - 220):.2f}" y="{min(max(y - 8, frame[1] + 18), frame[1] + frame[3] - 10):.2f}" class="map-label">{html.escape(label)}</text>')
    label_markup = "".join(labels)

    source_lines = []
    for record in source_records:
        if record.id in {"source-pdok-delft-municipality", "source-osm-exact-polygon-context"}:
            source_lines.append(f"{record.id}: {record.request_started_at.isoformat() if record.request_started_at else 'UNAVAILABLE'} – {record.request_finished_at.isoformat() if record.request_finished_at else 'UNAVAILABLE'}")
    source_text = " | ".join(source_lines)
    # Projected metre scale: 100 m in the same data transform used by the map.
    scale_bar_px = 100.0 * scale
    if scale_bar_px > 240:
        scale_bar_px = 240.0
    counts = {"roads": len(groups["roads"]), "buildings": len(groups["buildings"]), "rail": len(groups["rail"]), "water": len(groups["water"]), "public": len(groups["public"])}
    content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="850" viewBox="0 0 1240 850">
<style>.map-label{{font-family:sans-serif;font-size:13px;font-weight:700;fill:#16252d;paint-order:stroke;stroke:#fffdf8;stroke-width:4px;stroke-linejoin:round}}.legend-text{{font-family:sans-serif;font-size:13px;fill:#16252d}}.meta{{font-family:sans-serif;font-size:11px;fill:#4d5a63}}.mono{{font-family:monospace;font-size:12px;fill:#16252d}}</style>
<rect id="background" data-layout-bbox="0 0 1240 850" x="0" y="0" width="1240" height="850" fill="#f4f0e7"/>
<text id="title" data-layout-bbox="44 14 1152 34" x="44" y="40" font-family="sans-serif" font-size="25" font-weight="700" fill="#16252d">Delft station rail–canal corridor — MAP REVIEW v3</text>
<text id="subtitle" data-layout-bbox="44 50 1152 22" x="44" y="68" class="meta">{html.escape(proposal_id)} · PROPOSED BOUNDARY · exact boundary bytes preserved from site-proposal-delft-v2</text>
<rect id="map-frame" data-layout-bbox="44 100 790 590" x="44" y="100" width="790" height="590" rx="4" fill="#fbfaf6" stroke="#b6b0a5" stroke-width="1.5"/>
<g id="layer-water" data-map-layer="context" data-layout-bbox="44 100 790 590">{water}</g>
<g id="layer-public-space" data-map-layer="context" data-layout-bbox="44 100 790 590">{public}</g>
<g id="layer-buildings" data-map-layer="context" data-layout-bbox="44 100 790 590">{buildings}</g>
<g id="layer-roads" data-map-layer="context" data-layout-bbox="44 100 790 590">{roads}</g>
<g id="layer-rail" data-map-layer="context" data-layout-bbox="44 100 790 590">{rail}</g>
<g id="layer-boundary" data-map-layer="boundary" data-layout-bbox="44 100 790 590">{boundary_markup}</g>
<g id="layer-markers" data-map-layer="markers" data-layout-bbox="44 100 790 590">{marker_markup}{label_markup}</g>
<g id="north-arrow" data-layout-bbox="62 118 54 84"><line x1="80" y1="184" x2="80" y2="142" stroke="#16252d" stroke-width="3"/><path d="M80 130 l-10 20 h20 z" fill="#16252d"/><text x="65" y="120" class="legend-text" font-weight="700">NORTH</text></g>
<g id="scale-bar" data-layout-bbox="62 650 270 30"><line x1="70" y1="665" x2="{70 + scale_bar_px:.2f}" y2="665" stroke="#16252d" stroke-width="5"/><line x1="70" y1="657" x2="70" y2="673" stroke="#16252d" stroke-width="2"/><line x1="{70 + scale_bar_px:.2f}" y1="657" x2="{70 + scale_bar_px:.2f}" y2="673" stroke="#16252d" stroke-width="2"/><text x="70" y="650" class="legend-text">100 m SCALE (EPSG:28992)</text></g>
<rect id="legend" data-layout-bbox="860 100 330 430" x="860" y="100" width="330" height="430" rx="6" fill="#fffdf8" stroke="#b6b0a5" stroke-width="1.5"/>
<text x="882" y="134" class="legend-text" font-size="18" font-weight="700">LEGEND</text>
<text x="882" y="166" class="legend-text" fill="#004f4b">━━ Proposed boundary</text>
<text x="882" y="194" class="legend-text">━━ Roads / walk paths ({counts['roads']})</text>
<text x="882" y="222" class="legend-text">▰ Buildings ({counts['buildings']})</text>
<text x="882" y="250" class="legend-text">┈ Rail / station ({counts['rail']})</text>
<text x="882" y="278" class="legend-text">━━ Water ({counts['water']})</text>
<text x="882" y="306" class="legend-text">┈ Public spaces ({counts['public']})</text>
<text x="882" y="334" class="legend-text">● Shops</text>
<text x="882" y="374" class="legend-text" font-weight="700">Named context</text>
<text x="882" y="398" class="legend-text">Delft station</text>
<text x="882" y="422" class="legend-text">Oude Lijn railway</text>
<text x="882" y="446" class="legend-text">Buitenwatersloot canal</text>
<text x="882" y="470" class="legend-text">Houttuinen</text>
<text x="882" y="506" class="meta">Context clipped to projected viewport.</text>
<text id="footer-tags" data-layout-bbox="44 706 1152 22" x="44" y="724" class="mono">SHOP TAGS (PROPOSED): supermarket=0 · convenience=0 · grocery=0 · other=2</text>
<text id="footer-source" data-layout-bbox="44 736 1152 36" x="44" y="752" class="meta">SOURCE / TIMESTAMP: {html.escape(source_text)}</text>
<text id="footer-attribution" data-layout-bbox="44 778 1152 38" x="44" y="798" class="meta">CRS: EPSG:28992 metric display · attribution: © OpenStreetMap contributors (ODbL 1.0); PDOK/Kadaster · retained bytes only.</text>
</svg>'''
    path.write_text(content, encoding="utf-8")
    return {"viewbox": list(viewbox), "frame": list(frame), "viewport": list(viewport), "margin_m": margin_m, "scale_px_per_m": scale, "boundary_display_bbox": list(boundary_bbox), "context_geometry_clipped": True, "boundary_above_context": True, "counts": counts}


def _render_png(svg_path: Path, png_path: Path) -> None:
    """Render SVG through the installed Qt SVG engine, without live data."""

    if not Path(QGIS_PYTHON).is_file():
        raise ProposalBuildError(f"pinned Qt renderer is missing: {QGIS_PYTHON}")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        script_path = Path(handle.name)
        handle.write("""from PyQt5.QtWidgets import QApplication\nfrom PyQt5.QtGui import QImage, QPainter\nfrom PyQt5.QtSvg import QSvgRenderer\nimport sys\napp = QApplication(['m2-r02-render'])\nimage = QImage(1240, 850, QImage.Format_ARGB32)\nimage.fill(0xffffffff)\nrenderer = QSvgRenderer(sys.argv[1])\nif not renderer.isValid(): raise SystemExit('invalid SVG')\npainter = QPainter(image)\nrenderer.render(painter)\npainter.end()\nif not image.save(sys.argv[2], 'PNG'): raise SystemExit('PNG save failed')\n""")
    try:
        subprocess.run([QGIS_PYTHON, str(script_path), str(svg_path), str(png_path)], check=True, capture_output=True, text=True, timeout=60, env={**dict(__import__("os").environ), "QT_QPA_PLATFORM": "offscreen"})
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProposalBuildError(f"SVG render failed: {exc}") from exc
    finally:
        script_path.unlink(missing_ok=True)


def _artifact(path: Path, root: Path, artifact_id: str, mime: str, project_id: str, created_at: datetime, parents: list[str]) -> Artifact:
    return Artifact(id=artifact_id, type="proposal-artifact", uri=path.relative_to(root).as_posix(), sha256=sha256_file(path), mime=mime, crs="EPSG:28992" if mime == "application/geo+json" else None, producer=PRODUCER, created_at=created_at, project_id=project_id, size_bytes=path.stat().st_size, parent_artifact_ids=parents)


def build_v3(output_dir: str | Path, *, v2_root: str | Path = V2_DEFAULT, project_id: str = "delft-pilot-project") -> SiteProposal:
    root = Path(output_dir).resolve()
    parent_source = Path(v2_root).resolve()
    if not parent_source.is_dir():
        raise ProposalBuildError(f"v2 package directory is missing: {parent_source}")
    root.mkdir(parents=True, exist_ok=True)
    parent_root = root / "parent-v2"
    if parent_root.exists():
        raise ProposalBuildError(f"refusing to overwrite existing parent package: {parent_root}")
    shutil.copytree(parent_source, parent_root)
    v2_manifest = _hash_manifest(parent_source, root / "v2-integrity.json", "m2-r02-v2-integrity")
    if verify_package_integrity(root / "v2-integrity.json", parent_root)["file_count"] != len(v2_manifest["files"]):
        raise ProposalBuildError("copied v2 package failed integrity check")
    v2_payload = json.loads((parent_root / "site-proposal-v2.json").read_text(encoding="utf-8"))
    if v2_payload.get("boundary_sha256") != V2_BOUNDARY_HASH:
        raise ProposalBuildError("preserved v2 boundary hash differs from required hash")
    v2_boundary_path = parent_root / str(v2_payload["boundary_artifact_path"])
    v2_boundary_bytes = v2_boundary_path.read_bytes()
    boundary_path = root / "boundary-epsg28992-v3.geojson"
    boundary_path.write_bytes(v2_boundary_bytes)
    if sha256_file(boundary_path) != V2_BOUNDARY_HASH:
        raise ProposalBuildError("v3 boundary copy hash differs from v2")
    boundary_geometry = v2_payload["geometry"]
    exact_raw_path = parent_root / "sources" / "raw" / "osm-exact-proposed-polygon-v2.json"
    osm_payload = json.loads(exact_raw_path.read_text(encoding="utf-8"))
    layers = _osm_layers(osm_payload)
    context_wgs84 = root / "_context-wgs84-v3.geojson"
    context_wgs84.write_bytes(canonical_json_bytes(_geojson_features(layers["elements"])))
    context_projected = root / "context-display-epsg28992-v3.geojson"
    transform_command, transform_version = _transform_context(context_wgs84, context_projected, root)
    context_wgs84.unlink(missing_ok=True)
    projected_context = json.loads(context_projected.read_text(encoding="utf-8"))
    boundary_ring = [(float(point[0]), float(point[1])) for point in boundary_geometry["coordinates"][0]]
    bx = [point[0] for point in boundary_ring]
    by = [point[1] for point in boundary_ring]
    margin_m = 120.0
    viewport = (min(bx) - margin_m, min(by) - margin_m, max(bx) + margin_m, max(by) + margin_m)
    source_records_v2 = json.loads((parent_root / "sources" / "source-records-v2.json").read_text(encoding="utf-8"))
    source_records: list[dict[str, Any]] = []
    for record in source_records_v2["records"]:
        copied = dict(record)
        if copied.get("artifact_path"):
            copied["artifact_path"] = "parent-v2/" + str(copied["artifact_path"])
        if isinstance(copied.get("coverage"), Mapping):
            coverage = dict(copied["coverage"])
            if coverage.get("selected_feature_path"):
                coverage["selected_feature_path"] = "parent-v2/" + str(coverage["selected_feature_path"])
            copied["coverage"] = coverage
        source_records.append(copied)
    source_records_path = root / "sources" / "source-records-v3.json"
    _write_json(source_records_path, {"schema_version": "m2-r02-source-records", "records": source_records, "parent_source_records": "parent-v2/sources/source-records-v2.json"})
    source_models = [V2SourceRecord.model_validate(record) for record in source_records]
    map_path = root / "map-preview-v3.svg"
    render_metadata = _map_svg_v3(map_path, boundary_geometry, projected_context, source_models, V3_PROPOSAL_ID, viewport, margin_m)
    png_path = root / "map-preview-v3.png"
    _render_png(map_path, png_path)
    render_record_path = root / "map-render-record-v3.json"
    render_record = {**render_metadata, "schema_version": "m2-r02-map-render", "producer": PRODUCER, "svg_path": map_path.relative_to(root).as_posix(), "svg_sha256": sha256_file(map_path), "svg_size_bytes": map_path.stat().st_size, "png_path": png_path.relative_to(root).as_posix(), "png_sha256": sha256_file(png_path), "png_size_bytes": png_path.stat().st_size, "render_engine": QGIS_PYTHON + " / PyQt5.QtSvg", "render_crs": "EPSG:28992", "transform_command": transform_command, "transform_version": transform_version, "context_source": "parent-v2/sources/raw/osm-exact-proposed-polygon-v2.json", "projected_context_path": context_projected.relative_to(root).as_posix(), "viewport": {"crs": "EPSG:28992", "margin_m": margin_m, "bbox": list(viewport)}}
    _write_json(render_record_path, render_record)
    approval_path = root / "approval-record-v3.md"
    approval_path.write_text(f"""# Human approval record — Delft site proposal v3\n\nDecision status: **HUMAN_DECISION_REQUIRED**\n\nExact proposal: `{V3_PROPOSAL_ID}` version `v3`; supersedes `{V2_PROPOSAL_ID}`. The boundary is byte-for-byte preserved from v2 with SHA-256 `{V2_BOUNDARY_HASH}`. New map: `map-preview-v3.svg`; rendered verification: `map-preview-v3.png`.\n\nThis M2-R02 revision repairs viewport, clipping, layer order, and readability only. It does not change the proposed boundary, selection criteria, source bytes, scale status, taxonomy status, or approval state.\n\n- **APPROVE**: append a human decision naming this exact proposal, boundary hash, actor, timezone-aware timestamp, and reason.\n- **REJECT**: append a human rejection naming this exact proposal, actor, timestamp, and reason; preserve v1, v2, and v3 artifacts.\n\nThe map uses retained OSM bytes transformed to EPSG:28992 and clipped to a 120 m projected context margin. It does not use live tiles. OSM coverage, planning/buildability, accessibility, morphology, and climate limitations remain unchanged from v2.\n\nNo HumanDecision, approval, acceptance, or frozen snapshot was created.\n""", encoding="utf-8")
    v3_context = dict(v2_payload["delft_context"])
    v3_context["municipality_feature_path"] = "parent-v2/" + str(v2_payload["delft_context"]["municipality_feature_path"])
    v3_context.update({"parent_boundary_path": "parent-v2/" + str(v2_payload["boundary_artifact_path"]), "parent_boundary_sha256": V2_BOUNDARY_HASH, "map_svg_sha256": sha256_file(map_path), "map_svg_size_bytes": map_path.stat().st_size, "rendered_png_path": png_path.relative_to(root).as_posix(), "rendered_png_sha256": sha256_file(png_path), "rendered_png_size_bytes": png_path.stat().st_size, "render_record_path": render_record_path.relative_to(root).as_posix(), "context_display_path": context_projected.relative_to(root).as_posix(), "viewport": {"crs": "EPSG:28992", "margin_m": margin_m, "bbox": list(viewport)}})
    proposal = SiteProposal(
        id=V3_PROPOSAL_ID,
        project_id=project_id,
        version="v3",
        boundary_artifact_path=boundary_path.relative_to(root).as_posix(),
        boundary_sha256=sha256_file(boundary_path),
        boundary_size_bytes=boundary_path.stat().st_size,
        boundary_mime="application/geo+json",
        geometry_sha256=v2_payload["geometry_sha256"],
        geometry=boundary_geometry,
        geometry_type=v2_payload["geometry_type"],
        horizontal_crs=v2_payload["horizontal_crs"],
        units=v2_payload["units"],
        vertical_reference_status=v2_payload["vertical_reference_status"],
        transform=v2_payload["transform"],
        producer=PRODUCER,
        created_at=utc_now(),
        selection_method=v2_payload["selection_method"],
        rationale="M2-R02 map-only revision: repair viewport, clipping, layer order, and readability while preserving the exact v2 boundary and evidence.",
        source_refs=[record["id"] for record in source_records],
        parent_refs=[V2_PROPOSAL_ID, "artifact-boundary-delft-v2", "artifact-map-preview-delft-v2", v2_manifest["schema_version"]],
        measurements=v2_payload["measurements"],
        delft_context=v3_context,
        dataset_plan=v2_payload["dataset_plan"],
        limitations=v2_payload["limitations"] + ["M2-R02 changes map presentation only; no new planning or analytical evidence is introduced."],
        approval_record_path=approval_path.relative_to(root).as_posix(),
        supersedes_proposal_id=V2_PROPOSAL_ID,
        selection_criteria_status="PROPOSED_PROJECT_DECISION",
        selection_criteria=v2_payload["selection_criteria"],
        scale_parameters=v2_payload["scale_parameters"],
        taxonomy_status="PROPOSED",
        map_preview_path=map_path.relative_to(root).as_posix(),
        source_records_path=source_records_path.relative_to(root).as_posix(),
    )
    v2_db = parent_root / "proposal-state-v2.sqlite3"
    v3_db = root / "proposal-state-v3.sqlite3"
    shutil.copy2(v2_db, v3_db)
    created_at = proposal.created_at
    with ProjectStateStore(v3_db) as store:
        assert_no_effective_site_conflict(store, project_id)
        base_sequence = max((event.sequence for event in store.events(project_id=project_id)), default=0)
        artifact_specs = [
            (boundary_path, "artifact-boundary-delft-v3", "application/geo+json", ["artifact-boundary-delft-v2"]),
            (context_projected, "artifact-context-display-delft-v3", "application/geo+json", ["artifact-source-osm-exact-polygon-context"]),
            (source_records_path, "artifact-source-records-delft-v3", "application/json", ["artifact-source-records-delft-v2"]),
            (map_path, "artifact-map-preview-delft-v3", "image/svg+xml", ["artifact-map-preview-delft-v2", "artifact-boundary-delft-v3", "artifact-context-display-delft-v3"]),
            (png_path, "artifact-map-render-delft-v3", "image/png", ["artifact-map-preview-delft-v3"]),
            (render_record_path, "artifact-map-render-record-delft-v3", "application/json", ["artifact-map-preview-delft-v3", "artifact-map-render-delft-v3"]),
            (approval_path, "artifact-approval-record-delft-v3", "text/markdown", ["artifact-boundary-delft-v3", "artifact-map-render-record-delft-v3"]),
            (root / "v2-integrity.json", "artifact-v2-integrity-v3", "application/json", ["artifact-boundary-delft-v2"]),
        ]
        for path, artifact_id, mime, parents in artifact_specs:
            store.create_typed(_artifact(path, root, artifact_id, mime, project_id, created_at, parents), actor="m2-r02-executor", action="RecordArtifact", reason="Retain map-repair artifact with hash, size, producer, and parent links.", resulting_refs=[artifact_id])
        site = Site(id="site-delft-v3", project_id=project_id, version="v3", boundary_artifact_id="artifact-boundary-delft-v3", boundary_sha256=proposal.boundary_sha256, crs="EPSG:28992", vertical_reference=proposal.vertical_reference_status, units="m", dataset_snapshot_ids=[], status=SiteStatus.PROPOSED)
        store.create_typed(site, actor="m2-r02-executor", action="ProposeSite", reason="Append v3 map-only revision; status remains PROPOSED pending human decision.", changed_refs=proposal.source_refs, resulting_refs=[site.id, site.boundary_artifact_id, proposal.id], supersedes="site-delft-v2", event_payload={"proposal_id": proposal.id, "proposal_version": proposal.version, "supersedes": V2_PROPOSAL_ID, "boundary_unchanged": True, "human_decision_required": True})
        store.create("SiteProposal", proposal.model_dump(mode="json"), entity_id=proposal.id, project_id=project_id, actor="m2-r02-executor", action="RecordSiteProposal", reason="Append v3 map repair while preserving v2 and v1 evidence.", changed_refs=proposal.source_refs, resulting_refs=[proposal.id, site.id, site.boundary_artifact_id], supersedes=V2_PROPOSAL_ID, event_payload={"proposal_id": proposal.id, "status": proposal.status, "supersedes": V2_PROPOSAL_ID, "boundary_unchanged": True, "human_decision_required": True})
        events = store.events(project_id=project_id)
        v3_event_refs = [event.event_id for event in events if event.sequence > base_sequence and event.target_id in {proposal.id, site.id}]
        store.update(proposal.id, {"ledger_event_refs": v3_event_refs}, expected_revision=1, actor="m2-r02-executor", action="LinkProposalLedgerRefs", reason="Link v3 proposal to append-only map-repair events.", changed_refs=v3_event_refs, resulting_refs=[proposal.id], supersedes=V2_PROPOSAL_ID)
    proposal.ledger_event_refs.extend(v3_event_refs)
    proposal_json_path = root / "site-proposal-v3.json"
    _write_json(proposal_json_path, proposal.model_dump(mode="json"))
    validate_site_proposal_v3(proposal, root, v2_root=parent_source)
    return proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--v2-dir", type=Path, default=V2_DEFAULT)
    parser.add_argument("--project-id", default="delft-pilot-project")
    args = parser.parse_args(argv)
    try:
        proposal = build_v3(args.output_dir, v2_root=args.v2_dir, project_id=args.project_id)
    except (ProposalBuildError, SiteProposalV3ValidationError, ValueError, OSError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"proposal_id": proposal.id, "version": proposal.version, "status": proposal.status, "boundary_sha256": proposal.boundary_sha256}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
