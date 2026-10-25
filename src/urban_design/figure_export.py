"""Deterministic cartographic figure export for Space Syntax and Site Analysis (CP4-7).

Produces high-resolution formal PNG figures without UI chrome/gizmos/selection.
Uses SVG composition with deterministic styling and PyQt5 offscreen rendering.
"""

from __future__ import annotations

import hashlib
import html
import math
from pathlib import Path
import subprocess
import tempfile
import textwrap
from typing import Any, Mapping, Sequence

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

QGIS_PYTHON = "/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3"


def _color_ramp(val: float, min_val: float, max_val: float) -> str:
    """Return hex color from blue (low) -> cyan -> yellow -> orange -> red (high)."""
    if max_val <= min_val or math.isnan(val):
        return "#888888"
    norm = max(0.0, min(1.0, (val - min_val) / (max_val - min_val)))
    # 5-stop ramp
    # 0.0: #2c7bb6 (deep blue)
    # 0.25: #abd9e9 (light blue)
    # 0.5: #ffffbf (pale yellow)
    # 0.75: #fdae61 (orange)
    # 1.0: #d7191c (vibrant red)
    stops = [
        (0.00, (44, 123, 182)),
        (0.25, (171, 217, 233)),
        (0.50, (255, 255, 191)),
        (0.75, (253, 174, 97)),
        (1.00, (215, 25, 28)),
    ]
    for i in range(len(stops) - 1):
        s0, c0 = stops[i]
        s1, c1 = stops[i + 1]
        if s0 <= norm <= s1:
            t = (norm - s0) / (s1 - s0)
            r = int(c0[0] + t * (c1[0] - c0[0]))
            g = int(c0[1] + t * (c1[1] - c0[1]))
            b = int(c0[2] + t * (c1[2] - c0[2]))
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#d7191c"


def _render_svg_to_png(svg_path: Path, png_path: Path, width: int = 1240, height: int = 850) -> None:
    """Render SVG to PNG using QGIS Python / PyQt5 QtSvg offscreen."""
    qgis_py = Path(QGIS_PYTHON)
    if not qgis_py.is_file():
        raise RuntimeError(f"QGIS Python renderer not found at {QGIS_PYTHON}")

    script_content = f"""import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtSvg import QSvgRenderer

app = QApplication(['figure-render'])
image = QImage({int(width)}, {int(height)}, QImage.Format_ARGB32)
image.fill(0xffffffff)
renderer = QSvgRenderer(sys.argv[1])
if not renderer.isValid():
    sys.exit('Invalid SVG')
painter = QPainter(image)
renderer.render(painter)
painter.end()
if not image.save(sys.argv[2], 'PNG'):
    sys.exit('PNG save failed')
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp_script = Path(tmp.name)
        tmp.write(script_content)

    try:
        subprocess.run(
            [str(qgis_py), str(tmp_script), str(svg_path), str(png_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            env={**dict(__import__("os").environ), "QT_QPA_PLATFORM": "offscreen"},
        )
    finally:
        tmp_script.unlink(missing_ok=True)


def render_site_syntax_figure(
    study_area_geom: BaseGeometry,
    study_area_id: str,
    segments_data: Sequence[Mapping[str, Any]],
    metric_name: str,
    output_path: Path,
    title: str = "Rotterdam M4H — Space Syntax Analysis",
    subtitle: str = "Deterministic Segment Angular Model (Turner 2007)",
    revision: str = "rev 1",
    validation_status: str = "BLOCKED_COVERAGE_EVIDENCE_ABSENT",
    source_label: str = "Source identities and hashes are in the companion record",
    width: int = 1240,
    height: int = 850,
) -> dict[str, Any]:
    """Render a formal publication-ready figure of Space Syntax on a Study Area."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path = output_path.with_suffix(".svg")

    # Determine bounding box
    minx, miny, maxx, maxy = study_area_geom.bounds
    for seg in segments_data:
        geom = seg["geometry"]
        s_minx, s_miny, s_maxx, s_maxy = geom.bounds
        minx = min(minx, s_minx)
        miny = min(miny, s_miny)
        maxx = max(maxx, s_maxx)
        maxy = max(maxy, s_maxy)

    margin = 80.0  # meters
    minx -= margin
    miny -= margin
    maxx += margin
    maxy += margin

    geom_width = max(1.0, maxx - minx)
    geom_height = max(1.0, maxy - miny)

    # Drawing area in SVG (leaving margins for header, legend, metadata panel)
    map_x = 40.0
    map_y = 90.0
    map_w = 880.0
    map_h = 670.0

    scale = min(map_w / geom_width, map_h / geom_height)
    x_offset = map_x + (map_w - geom_width * scale) / 2.0
    y_offset = map_y + (map_h - geom_height * scale) / 2.0

    def to_svg(x: float, y: float) -> tuple[float, float]:
        px = x_offset + (x - minx) * scale
        py = y_offset + (maxy - y) * scale  # Invert Y for screen coords
        return px, py

    # Analyze metric values
    vals = [float(s["value"]) for s in segments_data if s.get("value") is not None and not math.isnan(s["value"])]
    min_v = min(vals) if vals else 0.0
    max_v = max(vals) if vals else 1.0

    # Build SVG content
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif;">',
        "  <defs>",
        '    <linearGradient id="ramp" x1="0%" y1="100%" x2="0%" y2="0%">',
        '      <stop offset="0%" stop-color="#2c7bb6"/>',
        '      <stop offset="25%" stop-color="#abd9e9"/>',
        '      <stop offset="50%" stop-color="#ffffbf"/>',
        '      <stop offset="75%" stop-color="#fdae61"/>',
        '      <stop offset="100%" stop-color="#d7191c"/>',
        "    </linearGradient>",
        "  </defs>",
        "  <!-- Header -->",
        f'  <text x="40" y="45" font-size="20" font-weight="700" fill="#0f172a">{html.escape(title)}</text>',
        f'  <text x="40" y="70" font-size="13" font-weight="400" fill="#475569">{html.escape(subtitle)}</text>',
        "  <!-- Map frame -->",
        f'  <rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}" fill="#ffffff" stroke="#cbd5e1" stroke-width="1"/>',
    ]

    # Render Study Area Boundary
    def render_poly(poly: Polygon) -> str:
        pts = [to_svg(x, y) for x, y in poly.exterior.coords]
        pts_str = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        return f'<polygon points="{pts_str}" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="4 2"/>'

    if isinstance(study_area_geom, Polygon):
        lines.append(f"  <!-- Study Area -->\n  {render_poly(study_area_geom)}")
    elif isinstance(study_area_geom, MultiPolygon):
        for p in study_area_geom.geoms:
            lines.append(f"  <!-- Study Area Part -->\n  {render_poly(p)}")

    # Render Segments
    lines.append("  <!-- Segments -->")
    # Sort segments so higher values are drawn on top
    sorted_segs = sorted(
        segments_data,
        key=lambda s: float(s["value"]) if s.get("value") is not None and not math.isnan(s["value"]) else -1.0,
    )
    for seg in sorted_segs:
        val = seg.get("value")
        color = _color_ramp(float(val), min_v, max_v) if val is not None and not math.isnan(val) else "#94a3b8"
        stroke_w = 2.4 if val is not None and not math.isnan(val) else 1.0
        geom = seg["geometry"]
        if isinstance(geom, LineString):
            coords = list(geom.coords)
            pts = [to_svg(x, y) for x, y in coords]
            pts_str = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
            lines.append(f'  <polyline points="{pts_str}" fill="none" stroke="{color}" stroke-width="{stroke_w}" stroke-linecap="round"/>')
        elif isinstance(geom, MultiLineString):
            for part in geom.geoms:
                coords = list(part.coords)
                pts = [to_svg(x, y) for x, y in coords]
                pts_str = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
                lines.append(f'  <polyline points="{pts_str}" fill="none" stroke="{color}" stroke-width="{stroke_w}" stroke-linecap="round"/>')

    # Side Legend and Info Panel
    panel_x = 940
    panel_y = 90
    panel_w = 260
    panel_h = 670

    status_is_validated = validation_status == "VALIDATED_COVERAGE"
    status_fill = "#f0fdf4" if status_is_validated else "#fff7ed"
    status_stroke = "#86efac" if status_is_validated else "#fdba74"
    status_color = "#15803d" if status_is_validated else "#9a3412"
    metric_lines = textwrap.wrap(metric_name, width=32)[:2] or [metric_name]
    study_id_lines = textwrap.wrap(study_area_id, width=31)[:2] or [study_area_id]
    status_lines = textwrap.wrap(validation_status.replace("_", " "), width=27)[:2] or [validation_status]
    if status_is_validated:
        warning_text = "VALIDATED COVERAGE — see linked evidence and scope"
        warning_fill, warning_stroke, warning_color = "#f0fdf4", "#86efac", "#166534"
    elif "COVERAGE" in validation_status:
        warning_text = "EXPLORATORY ONLY — SOURCE COVERAGE INSUFFICIENT — NOT A FORMAL ROTTERDAM RESULT"
        warning_fill, warning_stroke, warning_color = "#fff1f2", "#fb7185", "#9f1239"
    else:
        warning_text = f"EXPLORATORY ONLY — DATA NOT VALIDATED: {validation_status.replace('_', ' ')}"
        warning_fill, warning_stroke, warning_color = "#fff7ed", "#fdba74", "#9a3412"
    lines.extend([
        f'  <rect x="40" y="82" width="1160" height="32" fill="{warning_fill}" stroke="{warning_stroke}" rx="3"/>',
        f'  <text x="54" y="103" font-size="13" font-weight="800" fill="{warning_color}">{html.escape(warning_text)}</text>',
        f'  <!-- Info Panel -->',
        f'  <rect x="{panel_x}" y="{panel_y}" width="{panel_w}" height="{panel_h}" fill="#ffffff" stroke="#cbd5e1" stroke-width="1" rx="4"/>',
        f'  <text x="{panel_x + 16}" y="{panel_y + 30}" font-size="14" font-weight="700" fill="#0f172a">METRIC &amp; SCALE</text>',
        *[
            f'  <text x="{panel_x + 16}" y="{panel_y + 55 + (line_index * 16)}" font-size="11" font-weight="600" fill="#334155">{html.escape(line)}</text>'
            for line_index, line in enumerate(metric_lines)
        ],
        f'  <text x="{panel_x + 16}" y="{panel_y + 92}" font-size="10" fill="#64748b">Normalized segment measure</text>',
        # Legend Ramp
        f'  <text x="{panel_x + 16}" y="{panel_y + 125}" font-size="13" font-weight="700" fill="#0f172a">LEGEND</text>',
        f'  <rect x="{panel_x + 20}" y="{panel_y + 140}" width="24" height="150" fill="url(#ramp)" stroke="#cbd5e1" stroke-width="1"/>',
        f'  <text x="{panel_x + 55}" y="{panel_y + 150}" font-size="11" font-weight="600" fill="#0f172a">{max_v:.3f} (High)</text>',
        f'  <text x="{panel_x + 55}" y="{panel_y + 215}" font-size="11" font-weight="600" fill="#64748b">{(min_v + max_v) / 2:.3f} (Mid)</text>',
        f'  <text x="{panel_x + 55}" y="{panel_y + 288}" font-size="11" font-weight="600" fill="#0f172a">{min_v:.3f} (Low)</text>',
        # Study Area Info
        f'  <text x="{panel_x + 16}" y="{panel_y + 325}" font-size="13" font-weight="700" fill="#0f172a">STUDY AREA</text>',
        *[
            f'  <text x="{panel_x + 16}" y="{panel_y + 345 + (line_index * 15)}" font-size="9.5" fill="#475569"><tspan font-family="monospace">{html.escape(line)}</tspan></text>'
            for line_index, line in enumerate(study_id_lines)
        ],
        f'  <text x="{panel_x + 16}" y="{panel_y + 380}" font-size="10" fill="#475569">Revision: {html.escape(revision)}</text>',
        f'  <text x="{panel_x + 16}" y="{panel_y + 397}" font-size="10" fill="#475569">Segments: {len(segments_data):,}</text>',
        # Status / Validation
        f'  <text x="{panel_x + 16}" y="{panel_y + 430}" font-size="13" font-weight="700" fill="#0f172a">STATUS</text>',
        f'  <rect x="{panel_x + 16}" y="{panel_y + 445}" width="228" height="39" fill="{status_fill}" stroke="{status_stroke}" rx="3"/>',
        *[
            f'  <text x="{panel_x + 24}" y="{panel_y + 462 + (line_index * 14)}" font-size="9.5" font-weight="600" fill="{status_color}">{html.escape(line)}</text>'
            for line_index, line in enumerate(status_lines)
        ],
        # CRS & Attribution
        f'  <text x="{panel_x + 16}" y="{panel_y + 515}" font-size="11" font-weight="600" fill="#64748b">CRS / REFERENCE</text>',
        f'  <text x="{panel_x + 16}" y="{panel_y + 533}" font-size="10" fill="#64748b">EPSG:28992 (Amersfoort / RD New)</text>',
        f'  <text x="{panel_x + 16}" y="{panel_y + 551}" font-size="10" fill="#64748b">Source-linked deterministic output</text>',
        # Footer in Map
        f'  <!-- Footer -->',
        f'  <text x="40" y="785" font-size="10" fill="#64748b">CRS: EPSG:28992 · {html.escape(source_label)} · Producer: urban-design-week4/0.1</text>',
        f'</svg>',
    ])

    svg_content = "\n".join(lines)
    svg_path.write_text(svg_content, encoding="utf-8")

    # Render PNG
    _render_svg_to_png(svg_path, output_path, width=width, height=height)

    # Compute hash
    png_bytes = output_path.read_bytes()
    png_hash = hashlib.sha256(png_bytes).hexdigest()

    return {
        "status": "RENDERED" if status_is_validated else "EXPLORATORY_RENDERED",
        "sha256": f"sha256:{png_hash}",
        "png_path": str(output_path),
        "svg_path": str(svg_path),
        "size_bytes": len(png_bytes),
        "width": width,
        "height": height,
        "metric_name": metric_name,
        "study_area_id": study_area_id,
        "revision": revision,
        "validation_status": validation_status,
        "formal_result_eligible": status_is_validated,
        "exploratory_only": not status_is_validated,
        "warning": warning_text,
    }


def render_week7_figure(**kwargs):
    """Week 7 scenes reuse this module's PNG renderer via week7.figures."""

    from urban_design.week7.figures import render_figure

    return render_figure(**kwargs)


def render_real_week7_figure(**kwargs):
    """Export hash-verified authoritative scene geometry; no fixture fallback."""
    from urban_design.week7.real_figures import render_real_figure
    return render_real_figure(**kwargs)
