"""Week 7 figure scenes. Rendering uses the existing figure exporter's PNG path."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from urban_design.figure_export import _color_ramp, _render_svg_to_png

CANVAS_WIDTH = 1240
CANVAS_HEIGHT = 850
RAMP_ID = "week7-blue-red-v1"

FIGURE_KINDS = (
    "comparison",
    "plan",
    "perspective",
    "axonometric",
    "site",
    "syntax",
    "massing",
    "e1",
    "e2",
)

FIGURE_PRESETS: dict[str, dict[str, Any]] = {
    kind: {
        "kind": kind,
        "width": CANVAS_WIDTH,
        "height": CANVAS_HEIGHT,
        "ramp_id": RAMP_ID,
        "legend": {"x": 40, "y": 700, "width": 520, "height": 120, "label": "LEGEND"},
        "camera": {
            "id": "week7-consistent-v1",
            "projection": {
                "comparison": "orthographic-compare",
                "plan": "plan",
                "perspective": "perspective",
                "axonometric": "axonometric",
                "site": "plan",
                "syntax": "plan",
                "massing": "axonometric",
                "e1": "plan",
                "e2": "plan",
            }[kind],
            "azimuth_deg": 315 if kind in {"perspective", "axonometric", "massing"} else 0,
            "elevation_deg": 35 if kind in {"perspective", "axonometric", "massing"} else 90,
        },
        "manipulators": "hidden",
    }
    for kind in FIGURE_KINDS
}


def _text(x: int, y: int, size: int, weight: int, color: str, content: str) -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}">'
        f"{html.escape(content)}</text>"
    )


def render_figure(
    *,
    kind: str,
    output_path: Path,
    revision: str,
    unit: str,
    period: str,
    schemes: Sequence[Mapping[str, Any]],
    extent_id: str = "shared-public-open-space",
) -> dict[str, Any]:
    """Draw one preset view. Values are printed as given; nothing is rescaled to imply improvement."""

    if kind not in FIGURE_PRESETS:
        raise ValueError(f"unknown figure kind: {kind}")
    if not schemes:
        raise ValueError("at least one scheme is required")
    preset = FIGURE_PRESETS[kind]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    extents = {str(item.get("extent_id") or extent_id) for item in schemes}
    extent_differs = len(extents) > 1
    values = [float(item["value"]) for item in schemes]
    low = min(values)
    high = max(values)
    width = CANVAS_WIDTH
    height = CANVAS_HEIGHT
    legend = preset["legend"]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f8fafc"/>',
        _text(40, 36, 20, 700, "#0f172a", f"{kind}  revision {revision}"),
        _text(40, 62, 14, 400, "#334155", f"unit {unit}  period {period}"),
        _text(
            40,
            88,
            14,
            700,
            "#9a3412" if extent_differs else "#166534",
            "EXTENT_DIFFERS" if extent_differs else f"extent {extent_id}",
        ),
    ]
    lines.append(_text(40, 112, 13, 700, "#7c2d12", "FIXTURE_ONLY schematic — values are printed, not rescaled"))
    for index, item in enumerate(schemes):
        color = _color_ramp(float(item["value"]), low, high if high > low else low + 1.0)
        x = 80 + index * 220
        y = 520
        if kind == "comparison":
            bar_h = 40 + int(180 * (float(item["value"]) - low) / ((high - low) or 1.0))
            lines.append(f'<rect x="{x}" y="{y - bar_h}" width="120" height="{bar_h}" fill="{color}"/>')
        elif kind == "plan":
            lines.append(f'<rect x="{x}" y="{y - 90}" width="140" height="90" fill="none" stroke="{color}" stroke-width="4"/>')
        elif kind == "perspective":
            lines.append(
                f'<polygon points="{x}, {y} {x + 150}, {y} {x + 120}, {y - 110} {x + 30}, {y - 110}" fill="{color}" fill-opacity="0.85"/>'
            )
        elif kind in {"axonometric", "massing"}:
            lines.append(f'<polygon points="{x + 20}, {y} {x + 120}, {y - 28} {x + 120}, {y - 108} {x + 20}, {y - 80}" fill="{color}"/>')
            lines.append(f'<polygon points="{x + 120}, {y - 28} {x + 170}, {y - 52} {x + 170}, {y - 132} {x + 120}, {y - 108}" fill="{color}" fill-opacity="0.75"/>')
        else:
            lines.append(f'<rect x="{x}" y="{y - 70}" width="150" height="70" fill="{color}"/>')
            lines.append(_text(x + 8, y - 40, 13, 600, "#0f172a", kind))
        lines.append(_text(x, y + 28, 14, 600, "#0f172a", str(item["scenario_id"])))
        lines.append(_text(x, y + 48, 14, 400, "#0f172a", f"{item['value']} {unit}"))
    lines.extend(
        [
            f'<rect x="{legend["x"]}" y="{legend["y"]}" width="{legend["width"]}" height="{legend["height"]}" fill="#ffffff" stroke="#334155"/>',
            _text(legend["x"] + 16, legend["y"] + 28, 16, 700, "#0f172a", "LEGEND"),
            _text(legend["x"] + 16, legend["y"] + 56, 13, 400, "#0f172a", f"low {low:g} {unit}"),
            _text(legend["x"] + 16, legend["y"] + 78, 13, 400, "#0f172a", f"high {high:g} {unit}"),
            _text(legend["x"] + 16, legend["y"] + 104, 13, 400, "#0f172a", f"camera {preset['camera']['id']}"),
            "</svg>",
        ]
    )
    svg_path = output_path.with_suffix(".svg")
    svg_path.write_text("\n".join(lines), encoding="utf-8")
    _render_svg_to_png(svg_path, output_path, width=width, height=height)
    png_bytes = output_path.read_bytes()
    digest = hashlib.sha256(png_bytes).hexdigest()
    text_boxes = [
        {"text": f"revision {revision}", "x": 40, "y": 36},
        {"text": f"unit {unit}", "x": 40, "y": 62},
        {"text": period, "x": 40, "y": 62},
        {"text": "LEGEND", "x": legend["x"] + 16, "y": legend["y"] + 28},
    ]
    metadata = {
        "kind": kind,
        "revision": revision,
        "unit": unit,
        "period": period,
        "width": width,
        "height": height,
        "sha256": digest,
        "png_path": str(output_path),
        "svg_path": str(svg_path),
        "camera": preset["camera"],
        "ramp_id": RAMP_ID,
        "legend": legend,
        "legend_inside_canvas": True,
        "manipulators_hidden": True,
        "extent_differs": extent_differs,
        "extent_ids": sorted(extents),
        "values": [{"scenario_id": item["scenario_id"], "value": item["value"]} for item in schemes],
        "text_boxes": text_boxes,
        "improvement_implied_by_image_edit": False,
    }
    output_path.with_suffix(".json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return metadata


def export_figure_set(
    destination: Path,
    *,
    revision: str,
    unit: str,
    period: str,
    schemes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Write one PNG per preset and a manifest of the bytes that were written."""

    destination.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for kind in FIGURE_KINDS:
        metadata = render_figure(
            kind=kind,
            output_path=destination / f"{kind}.png",
            revision=revision,
            unit=unit,
            period=period,
            schemes=schemes,
        )
        png_path = destination / f"{kind}.png"
        digest = hashlib.sha256(png_path.read_bytes()).hexdigest()
        if digest != metadata["sha256"]:
            raise RuntimeError(f"figure digest mismatch for {kind}")
        rows.append(
            {
                "kind": kind,
                "sha256": digest,
                "width": metadata["width"],
                "height": metadata["height"],
                "revision": metadata["revision"],
                "unit": metadata["unit"],
                "period": metadata["period"],
                "camera": metadata["camera"]["id"],
                "extent_differs": metadata["extent_differs"],
                "manipulators_hidden": metadata["manipulators_hidden"],
            }
        )
    (destination / "manifest.json").write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    return rows


def legend_inside_canvas(metadata: Mapping[str, Any]) -> bool:
    legend = metadata["legend"]
    width = int(metadata["width"])
    height = int(metadata["height"])
    box_ok = (
        legend["x"] >= 0
        and legend["y"] >= 0
        and legend["x"] + legend["width"] <= width
        and legend["y"] + legend["height"] <= height
    )
    text_ok = all(0 <= box["x"] < width and 0 < box["y"] < height for box in metadata["text_boxes"])
    return bool(box_ok and text_ok and metadata["manipulators_hidden"] is True)


def png_dimensions(path: Path) -> tuple[int, int]:
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"not a PNG: {path}")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height
