#!/usr/bin/env python3
"""Combine E3/E4 outputs and render E3/E4 figures in Chinese and English."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_w8_figures import get_font_path
from e3_fabric_energy import render_e4_harbour_mass_vs_light_figure

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "artifacts/w8/e3e4-final"
DEFAULT_CSV = DEFAULT_OUT_DIR / "e3e4_results_zh.csv"

SCHEME_MAP_EN = {
    "港埠線性紋理": "Harbour grain",
    "圍合街廓延伸": "Closed block extension",
    "大型院落島": "Courtyard islands",
    "院落島嶼": "Courtyard islands",
    "地景為圖": "Landscape figure",
    "地景圖形": "Landscape figure",
}


def get_font(size: int, language: str = "zh") -> ImageFont.FreeTypeFont:
    if language == "en":
        for p in (
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ):
            if Path(p).is_file():
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
    cjk = get_font_path()
    if cjk and Path(cjk).is_file():
        try:
            return ImageFont.truetype(cjk, size)
        except Exception:
            pass
    return ImageFont.load_default()


def load_e3e4_csv(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def render_e3_eui_chart(csv_path: Path, output_png: Path, language: str = "zh") -> Path:
    rows = load_e3e4_csv(csv_path)
    e3 = [r for r in rows if r.get("構造") == "CZ5_Mass" and r.get("冷氣") == "開"]
    e3.sort(key=lambda r: float(r["EUI_kWh_m2年"]))

    W, H = 1800, 1100
    im = Image.new("RGB", (W, H), (250, 250, 248))
    dr = ImageDraw.Draw(im)

    font_func = lambda s: get_font(s, language=language)

    if language == "en":
        title = "E3 Building energy use intensity (four schemes, full models; exploratory, not an energy certificate)"
        subtitle = "Unit: kWh/(m²·year); ideal loads, ASHRAE 2019 CZ5 heavy mass, WWR 40%; fan power not included"
        footnote = "Red = selected scheme (Harbour grain). Full 253-building model (supersedes prior 108.6 sampled extrapolation)."
        title_font_size = 40
        subtitle_font_size = 24
        label_font_size = 26
    else:
        title = "E3 建築耗能 EUI（四案全量模型；探索性，非能源認證）"
        subtitle = "單位 kWh/(平方公尺·年)；理想負荷、ASHRAE 2019 CZ5 重質構造、WWR 40%；風機電力未含"
        footnote = "紅色＝Founder 選定方案（港埠線性紋理）。港埠以完整 253 棟模型計算（先前抽樣外推 108.6 已取代）。"
        title_font_size = 44
        subtitle_font_size = 26
        label_font_size = 30

    dr.text((70, 50), title, fill=(20, 30, 45), font=font_func(title_font_size))
    dr.text((70, 115), subtitle, fill=(90, 100, 115), font=font_func(subtitle_font_size))

    mx = max(float(r["EUI_kWh_m2年"]) for r in e3) * 1.15
    x0, y0, bw = 160, 950, 300

    for i, r in enumerate(e3):
        v = float(r["EUI_kWh_m2年"])
        hgt = int(v / mx * 700)
        x = x0 + i * 400
        is_harbour = (r["方案"] == "港埠線性紋理")
        col = (192, 57, 43) if is_harbour else (127, 140, 141)
        dr.rectangle([x, y0 - hgt, x + bw, y0], fill=col)

        val_str = f"{v:.1f}"
        bb_v = dr.textbbox((0, 0), val_str, font=font_func(36))
        val_w = bb_v[2] - bb_v[0]
        dr.text((x + (bw - val_w) // 2, y0 - hgt - 50), val_str, fill=(20, 30, 45), font=font_func(36))

        if language == "en":
            name = SCHEME_MAP_EN.get(r["方案"], r["方案"])
        else:
            name = r["方案"]

        bb_n = dr.textbbox((0, 0), name, font=font_func(label_font_size))
        name_w = bb_n[2] - bb_n[0]
        dr.text((x + (bw - name_w) // 2, y0 + 20), name, fill=(40, 45, 55), font=font_func(label_font_size))

    dr.line([(x0 - 20, y0), (x0 + 4 * 400, y0)], fill=(60, 60, 60), width=3)
    dr.text((70, H - 50), footnote, fill=(140, 140, 140), font=font_func(22))

    output_png.parent.mkdir(parents=True, exist_ok=True)
    im.save(output_png)
    return output_png


def render_e4_chart(csv_path: Path, output_png: Path, language: str = "zh") -> Path:
    rows = load_e3e4_csv(csv_path)
    harbour = [r for r in rows if r.get("方案") == "港埠線性紋理"]
    h = {(r["構造"], r["冷氣"]): r for r in harbour}

    mass_on = h.get(("CZ5_Mass", "開"))
    light_on = h.get(("CZ5_Light_U_Matched", "開")) or h.get(("CZ5_Light", "開"))
    mass_off = h.get(("CZ5_Mass", "關（只開暖氣）")) or h.get(("CZ5_Mass", "關"))
    light_off = h.get(("CZ5_Light_U_Matched", "關（只開暖氣）")) or h.get(("CZ5_Light", "關"))
    if not (mass_on and light_on and mass_off and light_off):
        raise KeyError("Missing required Harbour grain simulation cases in CSV.")

    e4_data = {
        "summer_overheating_mass": float(mass_off["夏季過熱時數_樓地板加權"]),
        "summer_overheating_light": float(light_off["夏季過熱時數_樓地板加權"]),
        "winter_heating_mass": float(mass_on["冬季暖氣需求_kWh_熱"]),
        "winter_heating_light": float(light_on["冬季暖氣需求_kWh_熱"]),
        "peak_cooling_mass": float(mass_on["尖峰冷氣_kW_熱"]),
        "peak_cooling_light": float(light_on["尖峰冷氣_kW_熱"]),
    }

    return render_e4_harbour_mass_vs_light_figure(
        e4_data=e4_data,
        output_png=output_png,
        language=language,
        output_svg=output_png.with_suffix(".svg"),
    )


def write_e3e4_markdown(csv_path: Path, output_md: Path, language: str = "zh") -> Path:
    rows = load_e3e4_csv(csv_path)
    e3 = [r for r in rows if r.get("構造") == "CZ5_Mass" and r.get("冷氣") == "開"]
    e3.sort(key=lambda r: float(r["EUI_kWh_m2年"]))

    harbour = [r for r in rows if r.get("方案") == "港埠線性紋理"]
    h = {(r["構造"], r["冷氣"]): r for r in harbour}
    mass_on = h.get(("CZ5_Mass", "開"))
    light_on = h.get(("CZ5_Light_U_Matched", "開")) or h.get(("CZ5_Light", "開"))
    mass_off = h.get(("CZ5_Mass", "關（只開暖氣）")) or h.get(("CZ5_Mass", "關"))
    light_off = h.get(("CZ5_Light_U_Matched", "關（只開暖氣）")) or h.get(("CZ5_Light", "關"))
    if not (mass_on and light_on and mass_off and light_off):
        raise KeyError("Missing required Harbour grain simulation cases in CSV.")

    fmt = lambda x: f"{float(x):,.1f}"
    diff = lambda a, b: float(b) - float(a)

    if language == "en":
        scope_map = {
            "全量（168 棟）": "Full model (168 buildings)",
            "全量（83 棟）": "Full model (83 buildings)",
            "全量（51 棟）": "Full model (51 buildings)",
            "全量（253 棟）": "Full model (253 buildings)",
        }
        md = [
            "# E3 Building Energy Use + E4 Thermal Mass (Four Fabrics Full Models, Final)",
            "",
            "**Exploratory; not an energy certification.** All four schemes use full building models "
            "(Harbour grain's 253 buildings calculated in full, superseding prior 3/253 sampled extrapolation of 108.6). "
            "Ideal loads, ASHRAE 2019 CZ5, WWR 40%; fan power not reported by EnergyPlus (set to 0).",
            "",
            "## E3 Annual Comparison (Heavy Mass Construction, Cooling & Heating On)",
            "",
            "| Scheme | Scope | New GFA (m²) | Heating Demand (kWh-th/y) | Cooling Demand (kWh-th/y) | EUI (kWh/m²·y) | Peak Heating (kW) | Peak Cooling (kW) |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for r in e3:
            s_en = SCHEME_MAP_EN.get(r["方案"], r["方案"])
            scope_en = scope_map.get(r["建模範圍"], r["建模範圍"])
            md.append(
                f"| {s_en} | {scope_en} | {fmt(r['新建GFA分母_m2'])} | {fmt(r['暖氣需求_kWh_熱'])} | "
                f"{fmt(r['冷氣需求_kWh_熱'])} | **{float(r['EUI_kWh_m2年']):.1f}** | "
                f"{fmt(r['尖峰暖氣_kW_熱'])} | {fmt(r['尖峰冷氣_kW_熱'])} |"
            )

        md += [
            "",
            "## E4 Harbour Thermal Mass Sensitivity (Full 253 Buildings)",
            "",
            "| Metric | Heavy Mass | Light Construction | Difference (Light - Heavy) |",
            "|---|---:|---:|---:|",
            f"| Summer overheating hours (Jun–Aug >26°C, heating only, floor-weighted hours) | {fmt(mass_off['夏季過熱時數_樓地板加權'])} | {fmt(light_off['夏季過熱時數_樓地板加權'])} | {diff(mass_off['夏季過熱時數_樓地板加權'], light_off['夏季過熱時數_樓地板加權']):+,.1f} |",
            f"| Winter heating demand (Dec–Feb, kWh-th) | {fmt(mass_on['冬季暖氣需求_kWh_熱'])} | {fmt(light_on['冬季暖氣需求_kWh_熱'])} | {diff(mass_on['冬季暖氣需求_kWh_熱'], light_on['冬季暖氣需求_kWh_熱']):+,.1f} |",
            f"| Peak cooling load (cooling on, kW-th) | {fmt(mass_on['尖峰冷氣_kW_熱'])} | {fmt(light_on['尖峰冷氣_kW_熱'])} | {diff(mass_on['尖峰冷氣_kW_熱'], light_on['尖峰冷氣_kW_熱']):+,.1f} |",
            "",
            "Sources: `artifacts/w8/e3e4/` (closed, courtyard, landscape full models) and `artifacts/w8/e3e4-harbour-full/` (harbour full model); previous sampled results retained for audit.",
        ]
    else:
        md = [
            "# E3 建築耗能＋E4 蓄熱（四案全量模型，最終版）",
            "",
            "**探索性；非能源認證。** 四案皆為全量模型（港埠 253 棟由專用完整重算取得，取代先前 3/253 抽樣外推 108.6）。理想負荷、ASHRAE 2019 CZ5、WWR 40%；風機電力 EnergyPlus 未輸出，以 0 計。",
            "",
            "## E3 年度比較（重質構造、冷暖氣皆開）",
            "",
            "| 方案 | 建模範圍 | 新建 GFA (m²) | 暖氣需求 (kWh-熱/年) | 冷氣需求 (kWh-熱/年) | EUI (kWh/m²·年) | 尖峰暖氣 (kW) | 尖峰冷氣 (kW) |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for r in e3:
            md.append(
                f"| {r['方案']} | {r['建模範圍']} | {fmt(r['新建GFA分母_m2'])} | {fmt(r['暖氣需求_kWh_熱'])} | "
                f"{fmt(r['冷氣需求_kWh_熱'])} | **{float(r['EUI_kWh_m2年']):.1f}** | "
                f"{fmt(r['尖峰暖氣_kW_熱'])} | {fmt(r['尖峰冷氣_kW_熱'])} |"
            )

        md += [
            "",
            "## E4 港埠重質／輕質構造比較（全量 253 棟）",
            "",
            "| 指標 | 重質 | 輕質 | 輕質減重質 |",
            "|---|---:|---:|---:|",
            f"| 夏季過熱時數（6–8 月 >26 °C，只開暖氣，樓地板加權小時） | {fmt(mass_off['夏季過熱時數_樓地板加權'])} | {fmt(light_off['夏季過熱時數_樓地板加權'])} | {diff(mass_off['夏季過熱時數_樓地板加權'], light_off['夏季過熱時數_樓地板加權']):,.1f} |",
            f"| 冬季暖氣需求（12–2 月，kWh-熱） | {fmt(mass_on['冬季暖氣需求_kWh_熱'])} | {fmt(light_on['冬季暖氣需求_kWh_熱'])} | {diff(mass_on['冬季暖氣需求_kWh_熱'], light_on['冬季暖氣需求_kWh_熱']):,.1f} |",
            f"| 尖峰冷負荷（冷氣開啟，kW-熱） | {fmt(mass_on['尖峰冷氣_kW_熱'])} | {fmt(light_on['尖峰冷氣_kW_熱'])} | {diff(mass_on['尖峰冷氣_kW_熱'], light_on['尖峰冷氣_kW_熱']):,.1f} |",
            "",
            "來源：`artifacts/w8/e3e4/`（圍合、院落、地景全量）與 `artifacts/w8/e3e4-harbour-full/`（港埠全量）；先前抽樣結果保留供查核。",
        ]

    output_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    return output_md


def main() -> None:
    parser = argparse.ArgumentParser(description="Render E3/E4 figures and tables.")
    parser.add_argument("--language", choices=["zh", "en", "both"], default="en", help="Language to render (default: en)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory")
    parser.add_argument("--results-csv", type=Path, default=DEFAULT_CSV, help="Source CSV results path")
    args = parser.parse_args()

    out_dir = args.output_dir
    csv_path = args.results_csv
    if not csv_path.is_file():
        raise FileNotFoundError(f"Source results CSV not found: {csv_path}")

    languages = ["en"] if args.language == "en" else (["zh"] if args.language == "zh" else ["zh", "en"])

    for lang in languages:
        suffix = "-en" if lang == "en" else ""
        e3_png = out_dir / f"e3_eui_by_fabric{suffix}.png"
        e4_png = out_dir / f"e4_harbour_mass_vs_light{suffix}.png"
        md_file = out_dir / f"e3e4_results_{lang}.md"

        print(f"Rendering E3 ({lang}) -> {e3_png}")
        render_e3_eui_chart(csv_path, e3_png, language=lang)

        print(f"Rendering E4 ({lang}) -> {e4_png}")
        render_e4_chart(csv_path, e4_png, language=lang)

        print(f"Writing table ({lang}) -> {md_file}")
        write_e3e4_markdown(csv_path, md_file, language=lang)


if __name__ == "__main__":
    main()
