#!/usr/bin/env python3
"""Build the proposed-only M2-T02 Rotterdam M4H alternative package.

The builder consumes retained source bytes.  Network retrieval is intentionally
outside this script: an online source cache is assembled by the executor, and
``--offline --source-dir`` rebuilds the package from those bytes without a
network call.  The output is immutable by convention: an existing output
directory is never overwritten.
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

from urban_design.geometry import canonical_geometry_hash, polygon_area, polygon_perimeter
from urban_design.models import Artifact, Project, Site, SiteStatus
from urban_design.site_proposal import SiteProposal, V2SourceRecord, canonical_json_bytes, sha256_file
from urban_design.site_proposal_rotterdam import validate_site_proposal_rotterdam
from urban_design.store import ProjectStateStore


PRODUCER = "urban-design-m2-t02-rotterdam-m4h/0.1"
PROJECT_ID = "rotterdam-m4h-pilot-project"
PROPOSAL_ID = "site-proposal-rotterdam-m4h-v1"
GDAL_OGR2OGR = "/Applications/QGIS-LTR.app/Contents/MacOS/bin/ogr2ogr"
QGIS_PYTHON = "/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3"
RUN_CREATED_AT = "2026-09-15T09:55:00+00:00"


class ProposalBuildError(RuntimeError):
    """Raised when retained evidence cannot produce a reviewable package."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _copy(source: Path, target: Path) -> None:
    if not source.is_file():
        raise ProposalBuildError(f"retained source is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _feature_geometry(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("type") in {"Polygon", "MultiPolygon"}:
        return {"type": payload["type"], "coordinates": payload.get("coordinates")}
    if payload.get("type") == "Feature":
        geometry = payload.get("geometry")
        if isinstance(geometry, Mapping):
            return {"type": geometry.get("type"), "coordinates": geometry.get("coordinates")}
    raise ProposalBuildError("retained GeoJSON has no Polygon/MultiPolygon geometry")


def _geojson_feature(geometry: Mapping[str, Any], properties: Mapping[str, Any], *, crs: str) -> dict[str, Any]:
    return {"type": "Feature", "properties": dict(properties), "geometry": dict(geometry), "crs": {"type": "name", "properties": {"name": crs}}}


def _transform(input_path: Path, output_path: Path) -> tuple[str, str]:
    if not Path(GDAL_OGR2OGR).is_file():
        raise ProposalBuildError(f"pinned GDAL transform tool is missing: {GDAL_OGR2OGR}")
    command = [GDAL_OGR2OGR, "-f", "GeoJSON", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:28992", "-nlt", "GEOMETRY", "-lco", "RFC7946=NO", str(output_path), str(input_path)]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
        version = subprocess.run([GDAL_OGR2OGR, "--version"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProposalBuildError(f"deterministic GDAL transform failed: {exc}") from exc
    return " ".join(command), version or "GDAL version unavailable"


def _geometry_from_transformed(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") if isinstance(payload, Mapping) else None
    if not isinstance(features, list) or len(features) != 1:
        raise ProposalBuildError("transformed boundary must contain exactly one feature")
    geometry = features[0].get("geometry") if isinstance(features[0], Mapping) else None
    if not isinstance(geometry, Mapping):
        raise ProposalBuildError("transformed boundary geometry is missing")
    return {"type": geometry["type"], "coordinates": geometry["coordinates"]}


def _elements_to_features(elements: Sequence[Mapping[str, Any]], bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    xmin, ymin, xmax, ymax = bbox
    features: list[dict[str, Any]] = []
    for element in elements:
        kind = element.get("type")
        points: list[list[float]] = []
        if kind == "way":
            points = [[float(point["lon"]), float(point["lat"])] for point in element.get("geometry", []) if isinstance(point, Mapping) and "lon" in point and "lat" in point]
        elif kind == "node" and "lon" in element and "lat" in element:
            points = [[float(element["lon"]), float(element["lat"])]]
        if not points or not any(xmin <= point[0] <= xmax and ymin <= point[1] <= ymax for point in points):
            continue
        tags = element.get("tags", {}) if isinstance(element.get("tags", {}), Mapping) else {}
        if kind == "node":
            geometry: dict[str, Any] = {"type": "Point", "coordinates": points[0]}
        elif points[0] == points[-1] and len(points) >= 4:
            geometry = {"type": "Polygon", "coordinates": [points]}
        else:
            geometry = {"type": "LineString", "coordinates": points}
        features.append({"type": "Feature", "id": str(element.get("id")), "properties": dict(tags), "geometry": geometry})
    return {"type": "FeatureCollection", "features": features, "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}}


def _coords(geometry: Mapping[str, Any]) -> list[list[tuple[float, float]]]:
    kind = geometry.get("type")
    value = geometry.get("coordinates")
    if kind == "LineString":
        return [[(float(point[0]), float(point[1])) for point in value]]
    if kind == "Polygon":
        return [[(float(point[0]), float(point[1])) for point in ring] for ring in value]
    if kind == "MultiLineString":
        return [[(float(point[0]), float(point[1])) for point in line] for line in value]
    if kind == "MultiPolygon":
        return [[(float(point[0]), float(point[1])) for point in ring] for polygon in value for ring in polygon]
    if kind == "Point":
        return [[(float(value[0]), float(value[1]))]]
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


def _clip_line(points: Sequence[tuple[float, float]], viewport: tuple[float, float, float, float]) -> list[list[tuple[float, float]]]:
    result: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for a, b in zip(points, points[1:]):
        clipped = _clip_segment(a, b, viewport)
        if clipped is None:
            if current:
                result.append(current)
                current = []
            continue
        start, end = clipped
        if not current or math.dist(current[-1], start) > 1e-7:
            if current:
                result.append(current)
            current = [start, end]
        else:
            current.append(end)
    if current:
        result.append(current)
    return [line for line in result if len(line) >= 2]


def _clip_polygon(points: Sequence[tuple[float, float]], viewport: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    xmin, ymin, xmax, ymax = viewport
    output = list(points[:-1] if points and points[0] == points[-1] else points)
    for edge, boundary in (("left", xmin), ("right", xmax), ("bottom", ymin), ("top", ymax)):
        if not output:
            return []
        clipped: list[tuple[float, float]] = []
        for current, previous in zip(output, output[-1:] + output[:-1]):
            inside = (current[0] >= boundary if edge == "left" else current[0] <= boundary if edge == "right" else current[1] >= boundary if edge == "bottom" else current[1] <= boundary)
            previous_inside = (previous[0] >= boundary if edge == "left" else previous[0] <= boundary if edge == "right" else previous[1] >= boundary if edge == "bottom" else previous[1] <= boundary)
            if inside != previous_inside:
                dx, dy = current[0] - previous[0], current[1] - previous[1]
                if edge in {"left", "right"}:
                    x = boundary
                    y = previous[1] + dy * ((boundary - previous[0]) / dx) if abs(dx) > 1e-12 else previous[1]
                else:
                    y = boundary
                    x = previous[0] + dx * ((boundary - previous[1]) / dy) if abs(dy) > 1e-12 else previous[0]
                clipped.append((x, y))
            if inside:
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


def _points_text(points: Iterable[tuple[float, float]], project) -> str:
    return " ".join(f"{project(point)[0]:.2f},{project(point)[1]:.2f}" for point in points)


def _feature_markup(feature: Mapping[str, Any], viewport, project, style: str) -> str:
    geometry = feature.get("geometry", {})
    kind = geometry.get("type")
    source_id = html.escape(str(feature.get("id", "")))
    out: list[str] = []
    if kind in {"Polygon", "MultiPolygon"}:
        for ring in _coords(geometry):
            clipped = _clip_polygon(ring, viewport)
            if len(clipped) >= 4:
                out.append(f'<polygon data-source-id="{source_id}" points="{_points_text(clipped, project)}" {style}/>')
    elif kind == "Point":
        point = _coords(geometry)[0][0]
        if viewport[0] <= point[0] <= viewport[2] and viewport[1] <= point[1] <= viewport[3]:
            x, y = project(point)
            out.append(f'<circle data-source-id="{source_id}" cx="{x:.2f}" cy="{y:.2f}" r="3.2" {style}/>')
    else:
        for line in _coords(geometry):
            for clipped in _clip_line(line, viewport):
                out.append(f'<polyline data-source-id="{source_id}" points="{_points_text(clipped, project)}" {style}/>')
    return "".join(out)


def _label_markup(features: Sequence[Mapping[str, Any]], viewport, project, frame) -> str:
    names = {"Keilehaven", "Keileweg", "Keilestraat", "Vierhavensstraat", "Dakpark", "Getijdenpark Keilehaven", "Marconistraat"}
    out: list[str] = []
    seen: set[str] = set()
    for feature in features:
        props = feature.get("properties", {}) if isinstance(feature.get("properties", {}), Mapping) else {}
        name = props.get("name")
        if name not in names or name in seen:
            continue
        points = [point for line in _coords(feature.get("geometry", {})) for point in line if viewport[0] <= point[0] <= viewport[2] and viewport[1] <= point[1] <= viewport[3]]
        if not points:
            continue
        point = points[len(points) // 2]
        x, y = project(point)
        if name == "Getijdenpark Keilehaven":
            y += 18
        elif name == "Keilehaven":
            y -= 14
        x = min(max(x + 6, frame[0] + 6), frame[0] + frame[2] - 180)
        y = min(max(y - 5, frame[1] + 16), frame[1] + frame[3] - 8)
        out.append(f'<text x="{x:.2f}" y="{y:.2f}" class="map-label">{html.escape(str(name))}</text>')
        seen.add(str(name))
    return "".join(out)


def _render_svg(path: Path, boundary_a: Mapping[str, Any], boundary_b: Mapping[str, Any], context: Mapping[str, Any], source_records: Sequence[V2SourceRecord], viewport: tuple[float, float, float, float], *, generated_at: str) -> dict[str, Any]:
    frame = (44.0, 100.0, 790.0, 590.0)
    viewbox = (0.0, 0.0, 1240.0, 850.0)
    project, scale = _projector(viewport, frame)
    features = [feature for feature in context.get("features", []) if isinstance(feature, Mapping)]
    groups: dict[str, list[Mapping[str, Any]]] = {"water": [], "public": [], "buildings": [], "roads": [], "rail": []}
    for feature in features:
        props = feature.get("properties", {}) if isinstance(feature.get("properties", {}), Mapping) else {}
        if props.get("waterway") or props.get("natural") == "water" or props.get("landuse") in {"reservoir", "basin"}:
            groups["water"].append(feature)
        if props.get("leisure") or props.get("landuse") in {"park", "recreation_ground", "grass", "forest", "allotments"} or props.get("natural") in {"sand", "scrub", "wood"}:
            groups["public"].append(feature)
        if props.get("building"):
            groups["buildings"].append(feature)
        if props.get("highway"):
            groups["roads"].append(feature)
        if props.get("railway"):
            groups["rail"].append(feature)
    water = "".join(_feature_markup(feature, viewport, project, 'fill="#d9dde0" fill-opacity="0.85" stroke="#68747c" stroke-width="1.1"') for feature in groups["water"])
    public = "".join(_feature_markup(feature, viewport, project, 'fill="url(#public-hatch)" fill-opacity="0.7" stroke="#7d858a" stroke-width="0.55"') for feature in groups["public"])
    buildings = "".join(_feature_markup(feature, viewport, project, 'fill="#e3e3e3" stroke="#8c8c8c" stroke-width="0.45"') for feature in groups["buildings"])
    roads = "".join(_feature_markup(feature, viewport, project, 'fill="none" stroke="#50565a" stroke-width="0.85"') for feature in groups["roads"])
    rail_base = "".join(_feature_markup(feature, viewport, project, 'fill="none" stroke="#292d30" stroke-width="1.2" data-style="rail-paired-sleeper"') for feature in groups["rail"])
    rail_sleepers = "".join(_feature_markup(feature, viewport, project, 'fill="none" stroke="#292d30" stroke-width="0.55" stroke-dasharray="1 5" data-style="rail-paired-sleeper"') for feature in groups["rail"])
    def boundary_markup(geometry: Mapping[str, Any], style: str) -> str:
        ring = [(float(point[0]), float(point[1])) for point in geometry["coordinates"][0]]
        clipped = _clip_polygon(ring, viewport)
        return f'<polygon points="{_points_text(clipped, project)}" {style}/>' if clipped else ""
    primary = boundary_markup(boundary_a, 'fill="#d62728" fill-opacity="0.06" stroke="#d62728" stroke-width="1.8" data-boundary-option="A"')
    alternate = boundary_markup(boundary_b, 'fill="none" stroke="#9c3d3d" stroke-width="1.15" opacity="0.9" data-boundary-option="B"')
    station_markup = ""
    station_names = {"Marconiplein", "Marconiplein metrostation"}
    for feature in features:
        props = feature.get("properties", {}) if isinstance(feature.get("properties", {}), Mapping) else {}
        if props.get("railway") == "station" or props.get("name") in station_names:
            points = _coords(feature.get("geometry", {}))
            if points and points[0]:
                point = points[0][0]
                if viewport[0] <= point[0] <= viewport[2] and viewport[1] <= point[1] <= viewport[3]:
                    x, y = project(point)
                    station_markup += f'<circle data-source-id="{html.escape(str(feature.get("id", "")))}" cx="{x:.2f}" cy="{y:.2f}" r="7" fill="#222" stroke="#fff" stroke-width="1.5"/><text x="{x + 10:.2f}" y="{y - 9:.2f}" class="map-label">Marconiplein station</text>'
                    break
    labels = _label_markup(features, viewport, project, frame)
    scale_bar_px = min(220.0, 100.0 * scale)
    source_lines = " | ".join(f"{record.id}: {record.retrieved_at.isoformat()}" for record in source_records if record.id in {"source-osm-m4h-context", "source-pdok-rotterdam-municipality"})
    counts = {key: len(value) for key, value in groups.items()}
    content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="850" viewBox="0 0 1240 850">
<defs><pattern id="public-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><line x1="0" y1="0" x2="0" y2="8" stroke="#9ca1a3" stroke-width="1"/></pattern></defs>
<style>.map-label{{font-family:sans-serif;font-size:12px;font-weight:700;fill:#202427;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}}.legend-text{{font-family:sans-serif;font-size:12px;fill:#202427}}.meta{{font-family:sans-serif;font-size:11px;fill:#4a5054}}.mono{{font-family:monospace;font-size:11px;fill:#202427}}</style>
<rect id="background" x="0" y="0" width="1240" height="850" fill="#f7f7f7"/>
<text id="title" data-layout-bbox="44 14 1152 34" x="44" y="40" font-family="sans-serif" font-size="25" font-weight="700" fill="#202427">Rotterdam M4H Vierhavenblok — MAP REVIEW v1</text>
<text id="subtitle" data-layout-bbox="44 50 1152 34" x="44" y="68" class="meta">{PROPOSAL_ID} · PROPOSED · AMBIGUOUS BOUNDARY — HUMAN SELECTION REQUIRED · display option A only</text>
<rect id="map-frame" data-layout-bbox="44 100 790 590" x="44" y="100" width="790" height="590" rx="4" fill="#fff" stroke="#aab0b3" stroke-width="1"/>
<g id="layer-water" data-map-layer="context">{water}</g>
<g id="layer-public-space" data-map-layer="context">{public}</g>
<g id="layer-buildings" data-map-layer="context">{buildings}</g>
<g id="layer-roads" data-map-layer="context">{roads}</g>
<g id="layer-rail" data-map-layer="context">{rail_base}{rail_sleepers}</g>
<g id="layer-boundary" data-map-layer="boundary">{primary}</g>
<g id="layer-boundary-option-b" data-map-layer="boundary-alternative">{alternate}</g>
<g id="layer-markers" data-map-layer="markers">{station_markup}{labels}</g>
<g id="north-arrow"><line x1="80" y1="184" x2="80" y2="142" stroke="#202427" stroke-width="1.5"/><path d="M80 130 l-9 18 h18 z" fill="#202427"/><text x="65" y="120" class="legend-text" font-weight="700">NORTH</text></g>
<g id="scale-bar"><line x1="70" y1="665" x2="{70 + scale_bar_px:.2f}" y2="665" stroke="#202427" stroke-width="1.5"/><line x1="70" y1="658" x2="70" y2="672" stroke="#202427" stroke-width="1.2"/><line x1="{70 + scale_bar_px:.2f}" y1="658" x2="{70 + scale_bar_px:.2f}" y2="672" stroke="#202427" stroke-width="1.2"/><text x="70" y="650" class="legend-text">100 m SCALE · EPSG:28992</text></g>
<g id="legend" data-layout-bbox="860 100 330 492"><rect x="860" y="100" width="330" height="492" rx="6" fill="#fff" stroke="#aab0b3" stroke-width="1"/>
<text x="882" y="132" class="legend-text" font-size="18" font-weight="700">LEGEND</text>
<line data-legend-swatch="boundary-a" x1="882" y1="158" x2="914" y2="158" stroke="#d62728" stroke-width="1.8"/><text x="924" y="162" class="legend-text">Proposed boundary — Option A</text>
<line data-legend-swatch="boundary-b" x1="882" y1="184" x2="914" y2="184" stroke="#9c3d3d" stroke-width="1.15"/><text x="924" y="188" class="legend-text">Alternative boundary — Option B</text>
<line data-legend-swatch="roads" x1="882" y1="210" x2="914" y2="210" stroke="#50565a" stroke-width="0.85"/><text x="924" y="214" class="legend-text">Roads / walk paths ({counts['roads']})</text>
<rect data-legend-swatch="buildings" x="882" y="226" width="32" height="13" fill="#e3e3e3" stroke="#8c8c8c" stroke-width="0.45"/><text x="924" y="238" class="legend-text">Buildings ({counts['buildings']})</text>
<line data-legend-swatch="rail" x1="882" y1="264" x2="914" y2="264" stroke="#292d30" stroke-width="1.2"/><line x1="882" y1="264" x2="914" y2="264" stroke="#292d30" stroke-width="0.55" stroke-dasharray="1 5"/><text x="924" y="268" class="legend-text">Rail / station ({counts['rail']})</text>
<line data-legend-swatch="water" x1="882" y1="290" x2="914" y2="290" stroke="#68747c" stroke-width="1.1"/><text x="924" y="294" class="legend-text">Water / harbour ({counts['water']})</text>
<rect data-legend-swatch="public" x="882" y="306" width="32" height="13" fill="url(#public-hatch)" stroke="#7d858a" stroke-width="0.55"/><text x="924" y="318" class="legend-text">Public / open space ({counts['public']})</text>
<circle data-legend-swatch="station" cx="898" cy="344" r="6" fill="#222" stroke="#fff" stroke-width="1.5"/><text x="924" y="348" class="legend-text">Station / verified landmark</text>
<text x="882" y="386" class="legend-text" font-weight="700">Named context</text>
<text x="882" y="410" class="legend-text">Keilehaven · Keileweg · Keilestraat</text>
<text x="882" y="432" class="legend-text">Vierhavensstraat · Dakpark</text>
<text x="882" y="454" class="legend-text">Getijdenpark Keilehaven</text>
<text x="882" y="486" class="meta">Grayscale vector context; no Google tiles.</text>
<text x="882" y="504" class="meta">Boundary options measured separately.</text></g>
<text id="footer-tags" data-layout-bbox="44 706 1152 22" x="44" y="724" class="mono">STATE: PROPOSED · HUMAN_DECISION_REQUIRED · Project.site_id = null · no approval/freeze</text>
<text id="footer-source" data-layout-bbox="44 736 1152 36" x="44" y="752" class="meta">SOURCE / TIMESTAMP: {html.escape(source_lines)} · generated {generated_at}</text>
<text id="footer-attribution" data-layout-bbox="44 778 1152 38" x="44" y="798" class="meta">CRS: EPSG:28992 metric display · attribution: © OpenStreetMap contributors (ODbL 1.0); PDOK/Kadaster; Rotterdam sources.</text>
</svg>'''
    path.write_text(content, encoding="utf-8")
    return {"viewbox": list(viewbox), "frame": list(frame), "scale_px_per_m": scale, "counts": counts, "context_geometry_clipped": True, "boundary_above_context": True, "crs": "EPSG:28992"}


def _render_png(svg_path: Path, png_path: Path, *, width: int = 1240, height: int = 850) -> None:
    if not Path(QGIS_PYTHON).is_file():
        raise ProposalBuildError(f"pinned Qt renderer is missing: {QGIS_PYTHON}")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        helper = Path(handle.name)
        handle.write(f"""from PyQt5.QtWidgets import QApplication\nfrom PyQt5.QtGui import QImage, QPainter\nfrom PyQt5.QtSvg import QSvgRenderer\nimport sys\napp = QApplication(['m2-t02-render'])\nimage = QImage({int(width)}, {int(height)}, QImage.Format_ARGB32)\nimage.fill(0xffffffff)\nrenderer = QSvgRenderer(sys.argv[1])\nif not renderer.isValid(): raise SystemExit('invalid SVG')\npainter = QPainter(image)\nrenderer.render(painter)\npainter.end()\nif not image.save(sys.argv[2], 'PNG'): raise SystemExit('PNG save failed')\n""")
    try:
        subprocess.run([QGIS_PYTHON, str(helper), str(svg_path), str(png_path)], check=True, capture_output=True, text=True, timeout=90, env={**dict(__import__("os").environ), "QT_QPA_PLATFORM": "offscreen"})
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProposalBuildError(f"SVG render failed: {exc}") from exc
    finally:
        helper.unlink(missing_ok=True)


def _artifact(path: Path, root: Path, artifact_id: str, mime: str, created_at: datetime, parents: list[str]) -> Artifact:
    return Artifact(id=artifact_id, type="proposal-artifact", uri=path.relative_to(root).as_posix(), sha256=sha256_file(path), mime=mime, crs="EPSG:28992" if mime == "application/geo+json" else None, producer=PRODUCER, created_at=created_at, project_id=PROJECT_ID, size_bytes=path.stat().st_size, parent_artifact_ids=parents)


def _integrity_manifest(root: Path, output: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    parents = {
        "delft-v1": Path("artifacts/milestone2-site-proposal/run-20260915T000500Z"),
        "delft-v2": Path("artifacts/milestone2-site-proposal-v2/run-20260915T013000Z"),
        "delft-v3": Path("artifacts/milestone2-site-proposal-v3/run-20260915T020700Z"),
    }
    selected = {
        "delft-v1": ["site-proposal.json", "boundary-epsg28992.geojson", "sources/source-records.json"],
        "delft-v2": ["site-proposal-v2.json", "boundary-epsg28992-v2.geojson", "boundary-wgs84-selection-v2.geojson", "sources/source-records-v2.json", "v1-integrity.json"],
        "delft-v3": ["site-proposal-v3.json", "boundary-epsg28992-v3.geojson", "map-preview-v3.svg", "map-preview-v3.png", "sources/source-records-v3.json", "v2-integrity.json"],
    }
    for label, source_root in parents.items():
        retained_root = root / "parents" / label
        if retained_root.exists():
            raise ProposalBuildError(f"refusing to overwrite retained parent: {retained_root}")
        for relative in selected[label]:
            source = source_root / relative
            if not source.is_file():
                raise ProposalBuildError(f"required Delft parent is missing: {source}")
            target = retained_root / relative
            _copy(source, target)
            entries.append({"parent": label, "external_path": str(source.resolve()), "retained_path": target.relative_to(root).as_posix(), "size_bytes": target.stat().st_size, "sha256": sha256_file(target)})
    payload = {"schema_version": "m2-t02-delft-parent-integrity", "files": entries}
    _write_json(output, payload)
    return payload


def _source_record(record_id: str, source_class: str, availability: str, publisher: str, identity: str, query: str, retrieved: str, started: str | None, finished: str | None, url: str | None, license_text: str, attribution: str, artifact: Path | None, root: Path, *, version: str, limitations: list[str], coverage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"id": record_id, "source_class": source_class, "availability": availability, "publisher": publisher, "source_identity": identity, "query": query, "retrieved_at": retrieved, "request_started_at": started, "request_finished_at": finished, "request_url": url, "version": version, "license": license_text, "attribution": attribution, "parameters": {}, "validation_status": "VALIDATED" if availability == "OBSERVED" else "UNAVAILABLE", "artifact_path": artifact.relative_to(root).as_posix() if artifact else None, "artifact_sha256": sha256_file(artifact) if artifact else None, "artifact_size_bytes": artifact.stat().st_size if artifact else None, "coverage": dict(coverage or {}), "limitations": limitations}
    return data


def build_rotterdam(output_dir: str | Path, *, source_dir: str | Path | None = None, offline: bool = False) -> SiteProposal:
    root = Path(output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise ProposalBuildError(f"refusing to overwrite non-empty output directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    source_base = Path(source_dir).resolve() if source_dir else Path("/tmp")
    if offline:
        # A package can serve as its own source cache for reproducible rebuilds.
        source_base = source_base / "sources" / "raw" if (source_base / "sources" / "raw").is_dir() else source_base
    raw_dir = root / "sources" / "raw"
    source_map = {
        "pdok_collection": ("m4h-collection.raw", "pdok-gemeentegebied-collection.json"),
        "pdok_items": ("m4h-items.raw", "pdok-gemeentegebied-items.json"),
        "osm": ("m4h-overpass.json", "osm-overpass-m4h-context.json"),
        "rotterdam": ("m4h-rotterdam.raw", "rotterdam-merwehaven.html"),
        "projects": ("m4h-budget.raw", "rotterdam-projects.html"),
    }
    for key, (cache_name, package_name) in source_map.items():
        candidate = source_base / cache_name
        if not candidate.is_file() and source_dir:
            candidate = source_base / package_name
        _copy(candidate, raw_dir / package_name)
    screenshot_source = Path("/var/folders/_t/cqm4x_v56g327tfhswnzhzwr0000gn/T/codex-clipboard-38a0b77c-5841-473a-b6bf-bcf88079f6fa.png")
    portfolio_source = Path("/Users/jackhsieh/Downloads/TUD/portfolio/Urbanism Q2 Portfolio.pdf")
    if offline and source_dir:
        screenshot_source = Path(source_dir) / "sources" / "human" / "google-anchor-screenshot.png"
        portfolio_source = Path(source_dir) / "sources" / "human" / "urbanism-q2-portfolio.pdf"
    elif source_dir and not screenshot_source.is_file():
        screenshot_source = Path(source_dir) / "sources" / "human" / "google-anchor-screenshot.png"
    elif source_dir and not portfolio_source.is_file():
        portfolio_source = Path(source_dir) / "sources" / "human" / "urbanism-q2-portfolio.pdf"
    human_dir = root / "sources" / "human"
    _copy(screenshot_source, human_dir / "google-anchor-screenshot.png")
    _copy(portfolio_source, human_dir / "urbanism-q2-portfolio.pdf")
    request_manifest = root / "sources" / "request-manifest.json"
    _write_json(request_manifest, {"schema_version": "m2-t02-request-manifest", "offline_rebuild_supported": True, "requests": [{"id": "pdok-gemeentegebied-collection", "method": "GET", "url": "https://api.pdok.nl/kadaster/brk-bestuurlijke-gebieden/ogc/v1/collections/gemeentegebied?f=json", "retrieved_at": "2026-09-15T09:47:23+00:00", "raw_artifact": "sources/raw/pdok-gemeentegebied-collection.json"}, {"id": "pdok-gemeentegebied-items", "method": "GET", "url": "https://api.pdok.nl/kadaster/brk-bestuurlijke-gebieden/ogc/v1/collections/gemeentegebied/items?bbox=4.35,51.85,4.55,52.0&limit=100&f=json", "retrieved_at": "2026-09-15T09:47:23+00:00", "raw_artifact": "sources/raw/pdok-gemeentegebied-items.json"}, {"id": "osm-overpass-m4h-context", "method": "GET", "url": "https://overpass-api.de/api/interpreter", "retrieved_at": "2026-09-15T09:39:01+00:00", "query": "[out:json][timeout:90];(way[highway](51.900,4.415,51.920,4.450);way[waterway](51.900,4.415,51.920,4.450);way[railway](51.900,4.415,51.920,4.450);way[building](51.900,4.415,51.920,4.450);way[leisure](51.900,4.415,51.920,4.450);way[landuse](51.900,4.415,51.920,4.450);way[natural](51.900,4.415,51.920,4.450);node[place](51.900,4.415,51.920,4.450);node[amenity](51.900,4.415,51.920,4.450);node[shop](51.900,4.415,51.920,4.450);node[railway](51.900,4.415,51.920,4.450););out body geom;", "raw_artifact": "sources/raw/osm-overpass-m4h-context.json"}, {"id": "rotterdam-merwehaven", "method": "GET", "url": "https://www.rotterdam.nl/merwehaven", "retrieved_at": "2026-09-15T09:48:00+00:00", "raw_artifact": "sources/raw/rotterdam-merwehaven.html"}, {"id": "rotterdam-projects", "method": "GET", "url": "https://www.watdoetdegemeente.rotterdam.nl/begroting-2026/programmas/stedelijke-ontwikkeling/projecten/", "retrieved_at": "2026-09-15T09:48:00+00:00", "raw_artifact": "sources/raw/rotterdam-projects.html"}], "raw_artifacts": [{"path": (raw_dir / package_name).relative_to(root).as_posix(), "sha256": sha256_file(raw_dir / package_name), "size_bytes": (raw_dir / package_name).stat().st_size} for _, package_name in source_map.values()]})
    pdok_items = json.loads((raw_dir / "pdok-gemeentegebied-items.json").read_text(encoding="utf-8"))
    matches = [feature for feature in pdok_items.get("features", []) if isinstance(feature, Mapping) and feature.get("properties", {}).get("naam") == "Rotterdam" and feature.get("properties", {}).get("code") == "0599"]
    if len(matches) != 1:
        raise ProposalBuildError(f"PDOK did not return exactly one Rotterdam feature (count={len(matches)})")
    municipality = matches[0]
    municipality_path = raw_dir / "pdok-rotterdam-municipality.geojson"
    _write_json(municipality_path, municipality)
    osm_payload = json.loads((raw_dir / "osm-overpass-m4h-context.json").read_text(encoding="utf-8"))
    osm_elements = osm_payload.get("elements") if isinstance(osm_payload, Mapping) else None
    if not isinstance(osm_elements, list) or not osm_elements:
        raise ProposalBuildError("retained OSM response has no elements")
    option_a = [(4.4339426, 51.9105673), (4.4356244, 51.9087779), (4.4257062, 51.9049757), (4.4240413, 51.9066715), (4.4339426, 51.9105673)]
    option_b = [(4.4339426, 51.9105673), (4.4360738, 51.9091456), (4.4252388, 51.9044433), (4.4246096, 51.9055522), (4.4339426, 51.9105673)]
    wgs84_a = {"type": "Polygon", "coordinates": [[list(point) for point in option_a]]}
    wgs84_b = {"type": "Polygon", "coordinates": [[list(point) for point in option_b]]}
    wgs84_a_path = root / "boundary-wgs84-option-a.geojson"
    wgs84_b_path = root / "boundary-wgs84-option-b.geojson"
    _write_json(wgs84_a_path, _geojson_feature(wgs84_a, {"option": "A", "status": "PROPOSED_DISPLAY_ONLY"}, crs="EPSG:4326"))
    _write_json(wgs84_b_path, _geojson_feature(wgs84_b, {"option": "B", "status": "PROPOSED_ALTERNATIVE"}, crs="EPSG:4326"))
    with tempfile.TemporaryDirectory(prefix="m4h-transform-") as temp:
        temp_path = Path(temp)
        transformed_a = temp_path / "a.geojson"
        transformed_b = temp_path / "b.geojson"
        transform_command, transform_version = _transform(wgs84_a_path, transformed_a)
        _transform(wgs84_b_path, transformed_b)
        geometry_a = _geometry_from_transformed(transformed_a)
        geometry_b = _geometry_from_transformed(transformed_b)
    boundary_a_path = root / "boundary-epsg28992-option-a.geojson"
    boundary_b_path = root / "boundary-epsg28992-option-b.geojson"
    _write_json(boundary_a_path, _geojson_feature(geometry_a, {"option": "A", "status": "PROPOSED_DISPLAY_ONLY"}, crs="EPSG:28992"))
    _write_json(boundary_b_path, _geojson_feature(geometry_b, {"option": "B", "status": "PROPOSED_ALTERNATIVE"}, crs="EPSG:28992"))
    primary_boundary_path = root / "boundary-epsg28992.geojson"
    primary_boundary_path.write_bytes(boundary_a_path.read_bytes())
    context_bbox = (4.4215, 51.9032, 4.4390, 51.9145)
    context_wgs84 = root / "_context-wgs84.geojson"
    _write_json(context_wgs84, _elements_to_features(osm_elements, context_bbox))
    context_projected = root / "context-display-epsg28992.geojson"
    _transform(context_wgs84, context_projected)
    context_wgs84.unlink(missing_ok=True)
    projected_context = json.loads(context_projected.read_text(encoding="utf-8"))
    projected_features = projected_context.get("features", [])
    boundary_points = [(float(point[0]), float(point[1])) for point in geometry_a["coordinates"][0]]
    margin_m = 320.0
    viewport = (min(point[0] for point in boundary_points) - margin_m, min(point[1] for point in boundary_points) - margin_m, max(point[0] for point in boundary_points) + margin_m, max(point[1] for point in boundary_points) + margin_m)
    created_at = datetime.fromisoformat(RUN_CREATED_AT)
    claims_path = root / "sources" / "human-context-claims.json"
    _write_json(claims_path, {"schema_version": "m2-t02-human-context", "claims": [{"id": "claim-portfolio-m4h-aim", "classification": "HUMAN_PROVIDED_DESIGN_CONTEXT", "source_ref": "source-human-portfolio", "statement": "The supplied portfolio frames M4H as a productive, mixed urban transformation context."}, {"id": "claim-portfolio-keilehaven", "classification": "HUMAN_PROVIDED_DESIGN_CONTEXT", "source_ref": "source-human-portfolio", "statement": "The supplied portfolio shows Keilehaven, Dakpark, and cross-dike access as design context."}, {"id": "claim-boundary-edge-interpretation", "classification": "INTERPRETATION", "source_ref": "source-human-google-anchor", "statement": "The screenshot red outline is interpreted against retained mapped road and harbour edges as two candidates."}]})
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    source_records: list[dict[str, Any]] = [
        _source_record("source-human-google-anchor", "PROJECT_DECISION", "OBSERVED", "User-provided screenshot", "Google Maps link and screenshot supplied in execution packet", "Human anchor near 51.909035, 4.433758; screenshot red quadrilateral", "2026-09-15T09:20:00+00:00", "2026-09-15T09:20:00+00:00", "2026-09-15T09:20:01+00:00", "https://www.google.com/maps", "User-provided; Google imagery is not retained as basemap", "User-provided screenshot", human_dir / "google-anchor-screenshot.png", root, version="USER_PROVIDED", limitations=["Human intent only; screenshot is not authoritative geometry and Google tiles are not reused."], coverage={"anchor_wgs84": [51.909035, 4.433758]}),
        _source_record("source-human-portfolio", "PROJECT_DECISION", "OBSERVED", "User-provided portfolio", "Urbanism Q2 Portfolio.pdf", "Portfolio pages describing M4H, Keilehaven, Dakpark, adaptive reuse, and social/ecological aims", "2026-09-15T09:20:00+00:00", "2026-09-15T09:20:00+00:00", "2026-09-15T09:20:01+00:00", "file:///Users/jackhsieh/Downloads/TUD/portfolio/Urbanism%20Q2%20Portfolio.pdf", "User-provided design context; claims are not dataset observations", "User-provided portfolio", human_dir / "urbanism-q2-portfolio.pdf", root, version="USER_PROVIDED", limitations=["Portfolio text and diagrams are human design context and interpretation; they are not site measurements or planning constraints."], coverage={"pages_inspected": [4, 5, 9, 10, 17, 18, 19, 21, 22, 27]}),
        _source_record("source-pdok-gemeentegebied-collection", "DATASET_OBSERVATION", "OBSERVED", "PDOK/Kadaster", "BRK Bestuurlijke Gebieden gemeentegebied collection", "GET collection metadata f=json", "2026-09-15T09:47:23+00:00", "2026-09-15T09:47:22+00:00", "2026-09-15T09:47:23+00:00", "https://api.pdok.nl/kadaster/brk-bestuurlijke-gebieden/ogc/v1/collections/gemeentegebied?f=json", "PDOK terms; verify current terms before publication", "PDOK/Kadaster", raw_dir / "pdok-gemeentegebied-collection.json", root, version="response metadata", limitations=["Collection metadata establishes source identity and CRS availability, not zoning or constructability."], coverage={"crs": ["CRS84", "EPSG:28992", "EPSG:3857", "EPSG:4258"]}),
        _source_record("source-pdok-rotterdam-municipality", "DATASET_OBSERVATION", "OBSERVED", "PDOK/Kadaster", "BRK gemeentegebied feature Rotterdam code 0599", "GET items bbox=4.35,51.85,4.55,52.0 limit=100 f=json; select naam=Rotterdam code=0599", "2026-09-15T09:47:23+00:00", "2026-09-15T09:47:22+00:00", "2026-09-15T09:47:23+00:00", "https://api.pdok.nl/kadaster/brk-bestuurlijke-gebieden/ogc/v1/collections/gemeentegebied/items?bbox=4.35,51.85,4.55,52.0&limit=100&f=json", "PDOK terms; verify current terms before publication", "PDOK/Kadaster", municipality_path, root, version="2026-09-15 response", limitations=["Independent municipal containment only; does not establish zoning, ownership, permission, or buildability."], coverage={"feature_code": "0599", "feature_name": "Rotterdam"}),
        _source_record("source-osm-m4h-context", "DATASET_OBSERVATION", "OBSERVED", "OpenStreetMap contributors", "Overpass M4H context response", "[out:json][timeout:90];(way[highway](51.900,4.415,51.920,4.450);way[waterway](51.900,4.415,51.920,4.450);way[railway](51.900,4.415,51.920,4.450);way[building](51.900,4.415,51.920,4.450);way[leisure](51.900,4.415,51.920,4.450);way[landuse](51.900,4.415,51.920,4.450);way[natural](51.900,4.415,51.920,4.450);node[place](51.900,4.415,51.920,4.450);node[amenity](51.900,4.415,51.920,4.450);node[shop](51.900,4.415,51.920,4.450);node[railway](51.900,4.415,51.920,4.450););out body geom;", "2026-09-15T09:39:01+00:00", "2026-09-15T09:38:58+00:00", "2026-09-15T09:39:01+00:00", "https://overpass-api.de/api/interpreter", "ODbL 1.0", "© OpenStreetMap contributors", raw_dir / "osm-overpass-m4h-context.json", root, version="Overpass 0.7.62.11; OSM base 2026-09-15T09:39:01Z", limitations=["OSM coverage is provisional and may omit mapped or unmapped features; tags do not prove ownership, access, safety, or suitability."], coverage={"bbox_wgs84": list(context_bbox), "retained_elements": len(osm_elements), "edge_way_ids": ["82806419", "7517828", "259184950", "7518596", "134702130"]}),
        _source_record("source-rotterdam-merwehaven", "DATASET_OBSERVATION", "OBSERVED", "Municipality of Rotterdam", "Merwehaven official page", "GET official project page", "2026-09-15T09:48:00+00:00", "2026-09-15T09:48:00+00:00", "2026-09-15T09:48:01+00:00", "https://www.rotterdam.nl/merwehaven", "Municipality website terms", "Municipality of Rotterdam", raw_dir / "rotterdam-merwehaven.html", root, version="2026-09-15 retrieval", limitations=["Official context source is not a boundary or permit decision."], coverage={"topic": "M4H Merwehaven development context"}),
        _source_record("source-rotterdam-projects", "DATASET_OBSERVATION", "OBSERVED", "Municipality of Rotterdam", "Stedelijke ontwikkeling projects page", "GET official projects page", "2026-09-15T09:48:00+00:00", "2026-09-15T09:48:00+00:00", "2026-09-15T09:48:01+00:00", "https://www.watdoetdegemeente.rotterdam.nl/begroting-2026/programmas/stedelijke-ontwikkeling/projecten/", "Municipality website terms", "Municipality of Rotterdam", raw_dir / "rotterdam-projects.html", root, version="2026-09-15 retrieval", limitations=["Official context source is not a boundary or permit decision."], coverage={"topic": "M4H and Keilekwartier projects"}),
        _source_record("source-project-boundary-options", "PROJECT_DECISION", "OBSERVED", "M2-T02 executor", "Physical-edge interpretation of supplied red outline", "Snap the supplied quadrilateral to retained OSM road/harbour vertices; preserve both alternatives", RUN_CREATED_AT, RUN_CREATED_AT, "2026-09-15T09:55:01+00:00", "file:///m2-t02/boundary-options", "Project evidence; no external licence asserted", "Derived from retained source records and user-provided intent", wgs84_a_path, root, version="M2-T02 proposed", limitations=["Option A is displayed provisionally; Option B remains a live alternative pending human selection."], coverage={"option_a_artifact": wgs84_a_path.relative_to(root).as_posix(), "option_b_artifact": wgs84_b_path.relative_to(root).as_posix()}),
        _source_record("source-climate-out-of-scope", "UNAVAILABLE", "UNAVAILABLE", "M2-T02 scope gate", "Climate evidence", "No climate experiment requested in M2-T02", RUN_CREATED_AT, None, None, None, "Not applicable", "No source retained", None, root, version="OUT_OF_SCOPE", limitations=["Climate evidence is intentionally unavailable in this milestone."]),
    ]
    source_records_path = root / "sources" / "source-records.json"
    _write_json(source_records_path, {"schema_version": "m2-t02-source-records", "records": source_records})
    source_models = [V2SourceRecord.model_validate(item) for item in source_records]
    svg_path = root / "map-preview.svg"
    render_meta = _render_svg(svg_path, geometry_a, geometry_b, projected_context, source_models, viewport, generated_at=RUN_CREATED_AT)
    png_path = root / "map-preview.png"
    _render_png(svg_path, png_path)
    render_record_path = root / "map-render-record.json"
    render_record = {"schema_version": "m2-t02-map-render", "producer": PRODUCER, "svg_path": svg_path.relative_to(root).as_posix(), "svg_sha256": sha256_file(svg_path), "svg_size_bytes": svg_path.stat().st_size, "png_path": png_path.relative_to(root).as_posix(), "png_sha256": sha256_file(png_path), "png_size_bytes": png_path.stat().st_size, "render_engine": QGIS_PYTHON + " / PyQt5.QtSvg", "transform_command": transform_command, "transform_version": transform_version, "crs": "EPSG:28992", "viewport": {"bbox": list(viewport), "crs": "EPSG:28992", "margin_m": margin_m}, "context_geometry_clipped": True, "boundary_above_context": True, "projected_context_path": context_projected.relative_to(root).as_posix()}
    _write_json(render_record_path, render_record)
    parent_manifest = _integrity_manifest(root, root / "delft-parent-integrity.json")
    context = {"containment_status": "WITHIN_INDEPENDENT_MUNICIPAL_BOUNDARY", "evidence_ref": "source-pdok-rotterdam-municipality", "municipality_feature_path": municipality_path.relative_to(root).as_posix(), "municipality_feature_sha256": sha256_file(municipality_path), "municipality_geometry_sha256": canonical_geometry_hash(_feature_geometry(municipality)), "candidate_boundary_wgs84_sha256": canonical_geometry_hash(wgs84_a), "candidate_boundary_wgs84": option_a, "boundary_selection_status": "AMBIGUOUS_HUMAN_SELECTION_REQUIRED", "human_choice_required": True, "display_option": "A", "display_only": True, "boundary_options": {"A": {"label": "Road-edge interpretation", "wgs84_geometry": wgs84_a, "wgs84_geometry_sha256": canonical_geometry_hash(wgs84_a), "projected_geometry": geometry_a, "projected_geometry_sha256": canonical_geometry_hash(geometry_a), "measurements": {"area_m2": polygon_area(geometry_a), "perimeter_m": polygon_perimeter(geometry_a)}, "artifact_path": wgs84_a_path.relative_to(root).as_posix(), "projected_artifact_path": boundary_a_path.relative_to(root).as_posix(), "edge_refs": [{"osm_way_id": "82806419", "name": "Vierhavensstraat"}, {"osm_way_id": "7517828", "name": "Keilestraat"}, {"osm_way_id": "7518596", "name": "Keileweg"}]}, "B": {"label": "Harbour/water-edge interpretation", "wgs84_geometry": wgs84_b, "wgs84_geometry_sha256": canonical_geometry_hash(wgs84_b), "projected_geometry": geometry_b, "projected_geometry_sha256": canonical_geometry_hash(geometry_b), "measurements": {"area_m2": polygon_area(geometry_b), "perimeter_m": polygon_perimeter(geometry_b)}, "artifact_path": wgs84_b_path.relative_to(root).as_posix(), "projected_artifact_path": boundary_b_path.relative_to(root).as_posix(), "edge_refs": [{"osm_way_id": "82806419", "name": "Vierhavensstraat"}, {"osm_way_id": "134702130", "name": "Keilehaven"}, {"osm_way_id": "782762035", "name": "Keilehaven canal"}]}}, "map_svg_path": svg_path.relative_to(root).as_posix(), "map_svg_sha256": sha256_file(svg_path), "map_svg_size_bytes": svg_path.stat().st_size, "rendered_png_path": png_path.relative_to(root).as_posix(), "rendered_png_sha256": sha256_file(png_path), "rendered_png_size_bytes": png_path.stat().st_size, "render_record_path": render_record_path.relative_to(root).as_posix(), "context_display_path": context_projected.relative_to(root).as_posix(), "viewport": {"bbox": list(viewport), "crs": "EPSG:28992", "margin_m": margin_m}, "human_context_claims_path": claims_path.relative_to(root).as_posix(), "delft_parent_integrity_path": "delft-parent-integrity.json", "state_path": "proposal-state.sqlite3", "portfolio_claims": claims["claims"], "limitations": ["Human screenshot and portfolio express intent/design context; neither is authoritative geometry.", "A/B edge reconstruction remains ambiguous and requires explicit human selection.", "PDOK municipality containment does not establish zoning, ownership, permission, or constructability.", "OSM context is provisional; accessibility, morphology, climate, Site Intelligence, and Space Syntax are out of scope."]}
    approval_path = root / "approval-record.md"
    approval_path.write_text(f"""# Human approval record — Rotterdam M4H Vierhavenblok\n\nProposal: `{PROPOSAL_ID}` (`v1`)\n\nDecision status: **HUMAN_DECISION_REQUIRED**\n\nThe supplied screenshot and portfolio are retained as human intent/design context. The red outline was reconstructed against retained mapped physical edges as two measured candidates:\n\n- **Option A — road-edge interpretation:** area {polygon_area(geometry_a):.3f} m²; perimeter {polygon_perimeter(geometry_a):.3f} m.\n- **Option B — harbour/water-edge interpretation:** area {polygon_area(geometry_b):.3f} m²; perimeter {polygon_perimeter(geometry_b):.3f} m.\n\nOption A is shown in the static map only as a provisional display. It is not a human selection. No option is approved, adopted, frozen, or effective. A human must explicitly select or reject an option by naming its exact WGS84 and EPSG:28992 hashes, actor, timezone-aware timestamp, and reason.\n\n**APPROVE:** append an explicit human decision naming the chosen option and hashes.\n\n**REJECT:** append an explicit human rejection naming the option, actor, timestamp, and reason.\n\nThe project state keeps `Project.site_id = null`, contains no human decision event, and contains no Approve or Accept ledger event. Existing Delft v1–v3 bytes are retained and integrity-checked as sibling history.\n""", encoding="utf-8")
    proposal = SiteProposal(id=PROPOSAL_ID, project_id=PROJECT_ID, version="v1", boundary_artifact_path=primary_boundary_path.relative_to(root).as_posix(), boundary_sha256=sha256_file(primary_boundary_path), boundary_size_bytes=primary_boundary_path.stat().st_size, boundary_mime="application/geo+json", geometry_sha256=canonical_geometry_hash(geometry_a), geometry=geometry_a, geometry_type="Polygon", horizontal_crs="EPSG:28992", units="m", vertical_reference_status="NOT_APPLICABLE_2D_BOUNDARY; no vertical reference supplied", transform={"input_crs": "EPSG:4326", "output_crs": "EPSG:28992", "method": "GDAL/OGR deterministic reprojection", "tool": GDAL_OGR2OGR, "tool_version": transform_version, "command": transform_command, "axis_order": "traditional GIS axis order: longitude, latitude input", "vertical_reference_status": "NOT_APPLICABLE_2D_BOUNDARY"}, producer=PRODUCER, created_at=created_at, selection_method="Physical-edge reconstruction from supplied intent: Option A follows retained Keileweg, Vierhavensstraat, and Keilestraat vertices; Option B follows retained harbour/water edges.", rationale="Alternative M4H Vierhavenblok proposal for review. Option A is displayed provisionally while A/B boundary ambiguity remains explicit and human selection is required.", source_refs=[item["id"] for item in source_records], parent_refs=["site-proposal-delft-v1", "site-proposal-delft-v2", "site-proposal-delft-v3", "delft-parent-integrity"], measurements=[{"name": "area", "value": polygon_area(geometry_a), "unit": "m2", "method": "shoelace area on EPSG:28992 projected exterior ring", "crs": "EPSG:28992"}, {"name": "perimeter", "value": polygon_perimeter(geometry_a), "unit": "m", "method": "Euclidean exterior-ring perimeter on EPSG:28992 projected coordinates", "crs": "EPSG:28992"}], delft_context=context, dataset_plan={"municipality": "PDOK BRK gemeentegebied Rotterdam containment only", "context": "retained OSM/Overpass context transformed to EPSG:28992", "planning_and_buildability": "UNAVAILABLE; outside M2-T02 scope", "accessibility": "OUT_OF_SCOPE", "morphology": "OUT_OF_SCOPE", "space_syntax": "OUT_OF_SCOPE", "climate": "UNAVAILABLE; no experiment plan approved", "design_generation": "OUT_OF_SCOPE"}, limitations=context["limitations"], approval_record_path=approval_path.relative_to(root).as_posix(), selection_criteria_status="PROPOSED_PROJECT_DECISION", selection_criteria={"status": "PROPOSED_PROJECT_DECISION", "human_selection_required": True, "options": ["A", "B"], "edge_evidence": context["boundary_options"]["A"]["edge_refs"] + context["boundary_options"]["B"]["edge_refs"]}, scale_parameters={"status": "PROPOSED_PROJECT_DECISION", "purpose": "descriptive measurements for human comparison", "thresholds": None}, taxonomy_status="PROPOSED", map_preview_path=svg_path.relative_to(root).as_posix(), source_records_path=source_records_path.relative_to(root).as_posix())
    db_path = root / "proposal-state.sqlite3"
    with ProjectStateStore(db_path) as store:
        project = Project(id=PROJECT_ID, name="Rotterdam M4H Vierhavenblok alternative", current_revision=0, site_id=None, settings={"milestone": "M2-T02", "site_id": None, "status": "PROPOSED", "human_decision_required": True})
        store.create_typed(project, actor="m2-t02-executor", action="CreateProject", reason="Create isolated proposed-only Rotterdam alternative project.")
        artifact_specs = [(request_manifest, "artifact-request-manifest-rotterdam-m4h", "application/json", []), (primary_boundary_path, "artifact-boundary-rotterdam-m4h-v1", "application/geo+json", []), (wgs84_a_path, "artifact-boundary-wgs84-option-a", "application/geo+json", ["artifact-boundary-rotterdam-m4h-v1"]), (wgs84_b_path, "artifact-boundary-wgs84-option-b", "application/geo+json", ["artifact-boundary-rotterdam-m4h-v1"]), (boundary_b_path, "artifact-boundary-epsg28992-option-b", "application/geo+json", ["artifact-boundary-wgs84-option-b"]), (municipality_path, "artifact-pdok-rotterdam-municipality", "application/geo+json", []), (context_projected, "artifact-context-display-rotterdam-m4h", "application/geo+json", ["artifact-pdok-rotterdam-municipality"]), (source_records_path, "artifact-source-records-rotterdam-m4h", "application/json", []), (claims_path, "artifact-human-context-claims", "application/json", ["artifact-source-records-rotterdam-m4h"]), (svg_path, "artifact-map-preview-rotterdam-m4h", "image/svg+xml", ["artifact-context-display-rotterdam-m4h", "artifact-boundary-rotterdam-m4h-v1"]), (png_path, "artifact-map-render-rotterdam-m4h", "image/png", ["artifact-map-preview-rotterdam-m4h"]), (render_record_path, "artifact-map-render-record-rotterdam-m4h", "application/json", ["artifact-map-preview-rotterdam-m4h", "artifact-map-render-rotterdam-m4h"]), (approval_path, "artifact-approval-record-rotterdam-m4h", "text/markdown", ["artifact-boundary-rotterdam-m4h-v1", "artifact-map-render-record-rotterdam-m4h"]), (root / "delft-parent-integrity.json", "artifact-delft-parent-integrity", "application/json", [])]
        for path, artifact_id, mime, parents in artifact_specs:
            store.create_typed(_artifact(path, root, artifact_id, mime, created_at, parents), actor="m2-t02-executor", action="RecordArtifact", reason="Retain M2-T02 source, boundary, map, and approval-gate artifact with hash and parent links.")
        site = Site(id="site-rotterdam-m4h-v1", project_id=PROJECT_ID, version="v1", boundary_artifact_id="artifact-boundary-rotterdam-m4h-v1", boundary_sha256=proposal.boundary_sha256, crs="EPSG:28992", vertical_reference=proposal.vertical_reference_status, units="m", dataset_snapshot_ids=[], status=SiteStatus.PROPOSED)
        store.create_typed(site, actor="m2-t02-executor", action="ProposeSite", reason="Append proposed sibling alternative; explicit human boundary selection remains required.", changed_refs=proposal.source_refs, resulting_refs=[site.id, site.boundary_artifact_id, proposal.id], event_payload={"proposal_id": proposal.id, "status": proposal.status, "boundary_selection_status": "AMBIGUOUS_HUMAN_SELECTION_REQUIRED", "human_decision_required": True})
        store.create("SiteProposal", proposal.model_dump(mode="json"), entity_id=proposal.id, project_id=PROJECT_ID, actor="m2-t02-executor", action="RecordSiteProposal", reason="Record Rotterdam M4H alternative without adoption or approval.", changed_refs=proposal.source_refs, resulting_refs=[proposal.id, site.id, site.boundary_artifact_id], event_payload={"proposal_id": proposal.id, "status": proposal.status, "human_decision_required": True})
        events = store.events(project_id=PROJECT_ID)
        refs = [event.event_id for event in events if event.target_id in {proposal.id, site.id}]
        store.update(proposal.id, {"ledger_event_refs": refs}, expected_revision=1, actor="m2-t02-executor", action="LinkProposalLedgerRefs", reason="Link proposal to append-only proposed-state events.", changed_refs=refs, resulting_refs=[proposal.id])
    proposal.ledger_event_refs = refs
    _write_json(root / "site-proposal.json", proposal.model_dump(mode="json"))
    validate_site_proposal_rotterdam(proposal, root)
    return proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, default=None, help="retained source cache or prior package root")
    parser.add_argument("--offline", action="store_true", help="forbid network and read only retained source bytes")
    args = parser.parse_args(argv)
    try:
        proposal = build_rotterdam(args.output_dir, source_dir=args.source_dir, offline=args.offline)
    except (ProposalBuildError, ValueError, OSError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"proposal_id": proposal.id, "version": proposal.version, "status": proposal.status, "boundary_sha256": proposal.boundary_sha256, "geometry_sha256": proposal.geometry_sha256}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
