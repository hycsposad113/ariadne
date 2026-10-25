#!/usr/bin/env python3
"""Render the E1 four-fabric comparison sheets from saved sunlight maps and results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_w8_figures import get_font_path
from e1_fabric_sunlight import FABRIC_NAMES_EN, SPACE_CATEGORY_LABELS_EN, get_sunlight_color


DEFAULT_DIR = Path(__file__).resolve().parents[1] / "artifacts/w8/e1-fabric"
ORDER = ["harbour_grain", "closed_block_extension", "courtyard_islands", "landscape_figure"]
DATES = [
    ("20261221", "winter", "Winter solstice 2026-12-21", "Winter Solstice", "冬至", "冬至 (12/21)"),
    ("20260321", "spring", "Spring equinox 2026-03-21", "Spring Equinox", "春分", "春分 (3/21)"),
    ("20260621", "summer", "Summer solstice 2026-06-21", "Summer Solstice", "夏至", "夏至 (6/21)"),
]
FABRIC_NAMES_ZH = {
    "harbour_grain": "港埠線性紋理",
    "closed_block_extension": "圍合街廓延伸",
    "courtyard_islands": "大型院落島",
    "landscape_figure": "地景為圖",
}
MAP = (100, 340, 2420, 2000)
PX_PER_M = 399 / 200.0
SCALE = 0.5


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = get_font_path()
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_rows(source_dir: Path, language: str) -> list[dict[str, str]]:
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("output_artifacts", {})
    expected = entries.get("comparison_table.csv", {}).get("sha256")
    csv_path = source_dir / "comparison_table.csv"
    if not expected or not csv_path.is_file() or _sha256(csv_path) != expected:
        raise ValueError("comparison_table.csv is missing or does not match the E1 manifest")
    if language == "en":
        for fabric in ORDER:
            for date_code, *_ in DATES:
                filename = f"{fabric}-{date_code}-sunlight-zh.png"
                expected_hash = entries.get(filename, {}).get("sha256")
                image_path = source_dir / filename
                if not expected_hash or not image_path.is_file() or _sha256(image_path) != expected_hash:
                    raise ValueError(f"E1 map is missing or does not match the source manifest: {filename}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def render_sheets(source_dir: Path, output_dir: Path, language: str = "zh") -> list[Path]:
    rows = _read_rows(source_dir, language)
    stat = {(row["紋理方案代碼"], row["開放空間類別"]): row for row in rows}
    map_w, map_h = int((MAP[2] - MAP[0]) * SCALE), int((MAP[3] - MAP[1]) * SCALE)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    for date_code, metric, date_en, season_en, season_zh, label_zh in DATES:
        width, height = 60 + 2 * map_w + 40 + 60, 230 + 2 * (map_h + 110) + 170
        sheet = Image.new("RGB", (width, height), (252, 251, 249))
        draw = ImageDraw.Draw(sheet)
        if language == "en":
            draw.text((60, 40), f"E1 Four-Fabric Direct Sunlight Comparison | {season_en} (2026-{date_code[4:6]}-{date_code[6:]})", fill=(25, 30, 40), font=_font(42))
            draw.text(
                (60, 105),
                "Shared map extent and colour scale (0–10 h); 08:00–18:00; 5 m grid; 0.5 m above ground; 300 m context obstruction; all unbuilt site land, including courtyards; exploratory analysis.",
                fill=(95, 100, 110),
                font=_font(21),
            )
            date_column = f"{season_zh}平均日照_小時"
            percent_column = f"{season_zh}日照大於等於2小時比例_百分比"
            detail_offset, map_offset = 42, 82
        else:
            draw.text((60, 40), f"E1 四案開放空間直射日照對照｜{label_zh}", fill=(25, 30, 40), font=_font(48))
            draw.text((60, 110), "四案同一視圖範圍、同一色階（0–10 小時）；08:00–18:00、網格 5 m、地面 +0.5 m、含周邊 300 m 脈絡遮擋；範圍＝基地全部未建土地（含中庭）；探索性", fill=(95, 100, 110), font=_font(26))
            date_column = f"{season_zh}平均日照_小時"
            percent_column = f"{season_zh}日照大於等於2小時比例_百分比"
            detail_offset, map_offset = 48, 95

        ranking = sorted(ORDER, key=lambda fabric: -float(stat[(fabric, "全體開放空間")][date_column]))
        for index, fabric in enumerate(ORDER):
            source = Image.open(source_dir / f"{fabric}-{date_code}-sunlight-zh.png").convert("RGB")
            tile = source.crop(MAP).resize((map_w, map_h), Image.Resampling.LANCZOS)
            x = 60 + (index % 2) * (map_w + 40)
            y = 230 + (index // 2) * (map_h + 110)
            all_space = stat[(fabric, "全體開放空間")]
            street = stat[(fabric, "街道路權")]
            if language == "en":
                name = FABRIC_NAMES_EN[fabric] + (" (Selected)" if fabric == "harbour_grain" else "")
                mean_text = (
                    f"Overall mean {float(all_space[date_column]):.2f} h (rank {ranking.index(fabric) + 1}) | "
                    f"≥2 h: {float(all_space[percent_column]):.1f}% | Streets {float(street[date_column]):.2f} h"
                )
                courtyard = stat.get((fabric, "街廓中庭"))
                mean_text += f" | Courtyards {float(courtyard[date_column]):.2f} h" if courtyard else " | No courtyards"
                heading_font, detail_font = _font(30), _font(21)
            else:
                name = all_space["紋理方案名稱"] + ("（選定）" if fabric == "harbour_grain" else "")
                mean_text = (
                    f"全體平均 {float(all_space[date_column]):.2f} 小時（第 {ranking.index(fabric) + 1} 名）｜"
                    f"≥2 小時 {float(all_space[percent_column]):.1f}%｜街道 {float(street[date_column]):.2f}｜"
                )
                courtyard = stat.get((fabric, "街廓中庭"))
                mean_text += f"中庭 {float(courtyard[date_column]):.2f} 小時" if courtyard else "無中庭"
                heading_font, detail_font = _font(36), _font(26)
            draw.text((x, y), name, fill=(192, 57, 43) if fabric == "harbour_grain" else (25, 30, 40), font=heading_font)
            draw.text((x, y + detail_offset), mean_text, fill=(70, 75, 85), font=detail_font)
            sheet.paste(tile, (x, y + map_offset))
            draw.rectangle([x, y + map_offset, x + map_w, y + map_offset + map_h], outline=(210, 212, 214), width=2)

        source = Image.open(source_dir / f"harbour_grain-{date_code}-sunlight-zh.png").convert("RGB")
        baseline_y = height - 140
        if language == "en":
            draw.text((60, baseline_y), "Direct sunlight duration (hours)", fill=(40, 45, 55), font=_font(22))
            draw.text((760, baseline_y), "Scale (shared across all maps)", fill=(40, 45, 55), font=_font(22))
            draw.text((1100, baseline_y + 8), "North is up. Dark blocks are scheme buildings; light grey shows surrounding buildings.", fill=(95, 100, 110), font=_font(19))
            draw.text((1100, baseline_y + 44), "Source: existing E1 Ladybug direct-sun results.", fill=(95, 100, 110), font=_font(19))
        else:
            draw.text((60, baseline_y), "日照時數（小時）", fill=(40, 45, 55), font=_font(26))
            draw.text((760, baseline_y), "比例尺（四圖相同）", fill=(40, 45, 55), font=_font(26))
            draw.text((1100, baseline_y + 10), "北向朝上。深色方塊＝方案建築；淺灰＝周邊既有建築。", fill=(95, 100, 110), font=_font(24))
            draw.text((1100, baseline_y + 50), "資料：artifacts/w8/e1-fabric/（Ladybug 直射追蹤）。", fill=(95, 100, 110), font=_font(24))

        legend_x, legend_y, legend_w, legend_h = 70, baseline_y + 44, 560, 26
        for pixel_x in range(legend_w):
            draw.line([(legend_x + pixel_x, legend_y), (legend_x + pixel_x, legend_y + legend_h)], fill=get_sunlight_color(pixel_x / legend_w * 10.0, max_hours=10.0))
        draw.rectangle([legend_x, legend_y, legend_x + legend_w, legend_y + legend_h], outline=(47, 53, 66), width=1)
        for tick in range(0, 11, 2):
            draw.text((legend_x + tick / 10 * legend_w - 12, legend_y + legend_h + 6), f"{tick}h", fill=(47, 53, 66), font=_font(18 if language == "en" else 20))

        bar_x, bar_y, bar_length = 760, baseline_y + 60, PX_PER_M * SCALE * 200
        draw.rectangle([bar_x, bar_y, bar_x + bar_length / 2, bar_y + 10], fill=(40, 45, 55))
        draw.rectangle([bar_x + bar_length / 2, bar_y, bar_x + bar_length, bar_y + 10], outline=(40, 45, 55), width=2)
        for value, x in [("0", bar_x), ("100", bar_x + bar_length / 2 - 16), ("200 m", bar_x + bar_length - 16)]:
            draw.text((x, bar_y + 18), value, fill=(40, 45, 55), font=_font(22 if language == "zh" else 20))

        if language == "en":
            season_slug = season_en.lower().replace(" ", "-")
            output_name = f"e1-compare-{date_code}-{season_slug}-en.png"
        else:
            output_name = f"e1-compare-{date_code}-{season_zh}-zh.png"
        output = output_dir / output_name
        sheet.save(output)
        generated.append(output)
    return generated


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render saved E1 four-scheme sunlight comparison sheets")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_DIR, help="Existing E1 result directory")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIR, help="Figure output directory")
    parser.add_argument("--language", choices=("zh", "en"), default="zh", help="Figure language")
    args = parser.parse_args(argv)
    for output in render_sheets(args.source_dir, args.output_dir, args.language):
        print(output)


if __name__ == "__main__":
    main()
