"""Climate extras read-only exploratory viewer router (W8, 2026-10-17)."""

from __future__ import annotations

import csv
import hashlib
import json
import urllib.parse
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/environment/climate-extras", tags=["environment-climate-extras"])

ALLOWED_SUBDIRS = {"e1-fabric", "utci", "e3e4-final", "e5-cfd"}
ALLOWED_EXTENSIONS = {".png", ".svg", ".csv", ".json", ".md"}
ENGLISH_FIGURE_MANIFEST = "english-figures-manifest.json"

DEFAULT_CLIMATE_ARTIFACT_ROOT = (Path(__file__).resolve().parents[3] / "artifacts" / "w8").resolve()

EXPLORATORY_LABEL_ZH = "探索性，非認證"
EXPLORATORY_LABEL_EN = "Exploratory, not certification"

FABRIC_SCHEMES = {
    "harbour_grain": {
        "code": "harbour_grain",
        "name_zh": "港埠線性紋理",
        "name_en": "Harbour grain",
        "is_selected": True,
        "selected_label_zh": "選定",
        "selected_label_en": "Selected",
    },
    "closed_block_extension": {
        "code": "closed_block_extension",
        "name_zh": "圍合街廓延伸",
        "name_en": "Closed-block extension",
        "is_selected": False,
        "selected_label_zh": None,
        "selected_label_en": None,
    },
    "courtyard_islands": {
        "code": "courtyard_islands",
        "name_zh": "大型院落島",
        "name_en": "Courtyard islands",
        "is_selected": False,
        "selected_label_zh": None,
        "selected_label_en": None,
    },
    "landscape_figure": {
        "code": "landscape_figure",
        "name_zh": "地景為圖",
        "name_en": "Landscape as figure",
        "is_selected": False,
        "selected_label_zh": None,
        "selected_label_en": None,
    },
}

SPACE_CATEGORY_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "全體開放空間": {"zh": "全體開放空間", "en": "Total Open Space"},
    "街坊公園/綠軸": {"zh": "街坊公園/綠軸", "en": "Neighborhood Park / Green Axis"},
    "水岸公共帶": {"zh": "水岸公共帶", "en": "Waterfront Public Realm"},
    "街道路權": {"zh": "街道路權", "en": "Street Right-of-Way"},
    "街廓中庭": {"zh": "街廓中庭", "en": "Block Courtyard"},
    "街廓內其他空地": {"zh": "街廓內其他空地", "en": "Other Open Space in Block"},
    "設備院與其他空地": {"zh": "設備院與其他空地", "en": "Utility Courtyard & Other Open Space"},
    "公園與廣場": {"zh": "公園與廣場", "en": "Parks & Plazas"},
}

E1_HEADER_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "紋理方案代碼": {"zh": "方案代碼", "en": "Scheme Code"},
    "紋理方案名稱": {"zh": "方案名稱", "en": "Scheme Name"},
    "開放空間類別": {"zh": "開放空間類別", "en": "Space Category"},
    "有效網格點數": {"zh": "有效網格點數", "en": "Sensor Points"},
    "代表面積_m2": {"zh": "代表面積 (m²)", "en": "Area (m²)"},
    "春分平均日照_小時": {"zh": "春分平均日照 (h)", "en": "Spring Mean Sun (h)"},
    "春分日照大於等於2小時比例_百分比": {"zh": "春分日照≥2h (%)", "en": "Spring ≥2h (%)"},
    "夏至平均日照_小時": {"zh": "夏至平均日照 (h)", "en": "Summer Mean Sun (h)"},
    "夏至日照大於等於2小時比例_百分比": {"zh": "夏至日照≥2h (%)", "en": "Summer ≥2h (%)"},
    "冬至平均日照_小時": {"zh": "冬至平均日照 (h)", "en": "Winter Mean Sun (h)"},
    "冬至日照大於等於2小時比例_百分比": {"zh": "冬至日照≥2h (%)", "en": "Winter ≥2h (%)"},
}


class TableColumn(BaseModel):
    key: str
    title_zh: str
    title_en: str


class TableData(BaseModel):
    columns: List[TableColumn]
    rows: List[Dict[str, Any]]


class FigureItem(BaseModel):
    path: str
    path_en: Optional[str] = None
    title_zh: str
    title_en: str
    caption_zh: Optional[str] = None
    caption_en: Optional[str] = None
    tag: Optional[str] = None
    fabric: Optional[str] = None
    season: Optional[str] = None


class ClimateSection(BaseModel):
    id: str
    title_zh: str
    title_en: str
    label_zh: str = Field(default=EXPLORATORY_LABEL_ZH)
    label_en: str = Field(default=EXPLORATORY_LABEL_EN)
    status: str
    missing_files: List[str] = Field(default_factory=list)
    figures: List[FigureItem] = Field(default_factory=list)
    table: Optional[TableData] = None
    limitations_zh: str
    limitations_en: str
    source_sha256: Dict[str, str] = Field(default_factory=dict)


def get_climate_artifact_root(request: Request) -> Path:
    configured = getattr(request.app.state, "climate_artifact_root", None)
    if configured is not None:
        return Path(configured).resolve()
    return DEFAULT_CLIMATE_ARTIFACT_ROOT


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _safe_artifact_file(root: Path, relative_path: str) -> Optional[Path]:
    if not isinstance(relative_path, str) or "\\" in relative_path:
        return None
    posix_path = PurePosixPath(relative_path)
    if posix_path.is_absolute() or ".." in posix_path.parts or not posix_path.parts:
        return None
    if posix_path.parts[0] not in ALLOWED_SUBDIRS or Path(posix_path.name).suffix.lower() not in ALLOWED_EXTENSIONS:
        return None
    try:
        root_resolved = root.resolve()
        subroot = (root_resolved / posix_path.parts[0]).resolve()
        target = (root_resolved / Path(*posix_path.parts)).resolve()
        target.relative_to(subroot)
    except (OSError, ValueError):
        return None
    return target if target.is_file() else None


def _validated_english_figure(root: Path, path_en: str, expected_zh: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Return the registered pair only when both files still match the deployment manifest."""
    manifest_path = root / ENGLISH_FIGURE_MANIFEST
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("manifest_version") != "1.0.0" or manifest.get("language") != "en":
            return None
        entry = manifest.get("files", {}).get(path_en)
        if not isinstance(entry, dict):
            return None
        path_zh = entry.get("zh_counterpart")
        expected_en_hash = entry.get("sha256")
        expected_zh_hash = entry.get("zh_sha256")
        if expected_zh is not None and path_zh != expected_zh:
            return None
        if not isinstance(expected_en_hash, str) or not isinstance(expected_zh_hash, str):
            return None
        en_file = _safe_artifact_file(root, path_en)
        zh_file = _safe_artifact_file(root, path_zh)
        if en_file is None or zh_file is None:
            return None
        if not PurePosixPath(path_en).stem.endswith("-en"):
            return None
        if PurePosixPath(path_en).parts[0] != PurePosixPath(path_zh).parts[0]:
            return None
        if en_file.suffix.lower() != zh_file.suffix.lower():
            return None
        actual_en_hash = file_sha256(en_file)
        actual_zh_hash = file_sha256(zh_file)
        if actual_en_hash != expected_en_hash or actual_zh_hash != expected_zh_hash:
            return None
        return {"path_en": path_en, "sha256": actual_en_hash, "manifest_sha256": file_sha256(manifest_path)}
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return None


def _attach_english_figure_paths(root: Path, figures: List[FigureItem], source_sha256: Dict[str, str]) -> None:
    for figure in figures:
        if not figure.path_en:
            continue
        registration = _validated_english_figure(root, figure.path_en, expected_zh=figure.path)
        if registration is None:
            figure.path_en = None
            continue
        source_sha256[figure.path_en] = registration["sha256"]
        source_sha256[ENGLISH_FIGURE_MANIFEST] = registration["manifest_sha256"]


def _build_e1_section(root: Path) -> ClimateSection:
    sec_id = "e1-fabric"
    title_zh = "E1 四案日照對照"
    title_en = "E1 Four-Fabric Sunlight Comparison"
    limitations_zh = (
        "探索性分析，非日照權或法規認證。以 Ladybug／Radiance 直射日照追蹤（5 m 網格、地面 +0.5 m、"
        "08:00–18:00、15 分鐘取樣、含周邊 300 m 脈絡建築遮擋）；範圍為基地內全部未建土地（含街廓中庭與街廓內空地），"
        "未計植栽遮蔭。數值僅供四案相對比較。"
    )
    limitations_en = (
        "Exploratory analysis, not statutory sunlight certification. Ladybug/Radiance direct-sun tracing "
        "(5 m grid, 0.5 m above ground, 08:00-18:00, 15-minute steps, 300 m context buildings as obstructions); "
        "domain is all unbuilt land on site including block courtyards and block-internal open land; "
        "tree shading not modelled. For relative comparison of the four fabrics only."
    )

    required_files = [
        "e1-fabric/comparison_table.csv",
        "e1-fabric/e1-compare-20261221-冬至-zh.png",
        "e1-fabric/e1-compare-20260321-春分-zh.png",
        "e1-fabric/e1-compare-20260621-夏至-zh.png",
    ]

    source_sha256: Dict[str, str] = {}
    missing_files: List[str] = []
    for rel_path in required_files:
        p = root / rel_path
        if p.is_file():
            source_sha256[rel_path] = file_sha256(p)
        else:
            missing_files.append(rel_path)

    if missing_files:
        return ClimateSection(
            id=sec_id,
            title_zh=title_zh,
            title_en=title_en,
            status="MISSING",
            missing_files=missing_files,
            figures=[],
            table=None,
            limitations_zh=limitations_zh,
            limitations_en=limitations_en,
            source_sha256=source_sha256,
        )

    figures = [
        FigureItem(
            path="e1-fabric/e1-compare-20261221-冬至-zh.png",
            path_en="e1-fabric/e1-compare-20261221-winter-solstice-en.png",
            title_zh="冬至日照對照圖（2026-12-21）",
            title_en="Winter Solstice Sunlight Comparison (2026-12-21)",
            caption_zh="四案冬至全日照時數與 ≥2h 比例對比",
            caption_en="Comparison of full-day sunlight hours and ≥2h compliance across four fabrics on Winter Solstice",
            season="winter_solstice",
            tag="2026-12-21",
        ),
        FigureItem(
            path="e1-fabric/e1-compare-20260321-春分-zh.png",
            path_en="e1-fabric/e1-compare-20260321-spring-equinox-en.png",
            title_zh="春分日照對照圖（2026-03-21）",
            title_en="Spring Equinox Sunlight Comparison (2026-03-21)",
            caption_zh="四案春分全日照時數與 ≥2h 比例對比",
            caption_en="Comparison of full-day sunlight hours and ≥2h compliance across four fabrics on Spring Equinox",
            season="spring_equinox",
            tag="2026-03-21",
        ),
        FigureItem(
            path="e1-fabric/e1-compare-20260621-夏至-zh.png",
            path_en="e1-fabric/e1-compare-20260621-summer-solstice-en.png",
            title_zh="夏至日照對照圖（2026-06-21）",
            title_en="Summer Solstice Sunlight Comparison (2026-06-21)",
            caption_zh="四案夏至全日照時數與 ≥2h 比例對比",
            caption_en="Comparison of full-day sunlight hours and ≥2h compliance across four fabrics on Summer Solstice",
            season="summer_solstice",
            tag="2026-06-21",
        ),
    ]

    csv_path = root / "e1-fabric/comparison_table.csv"
    columns: List[TableColumn] = []
    rows: List[Dict[str, Any]] = []

    with csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            for field in reader.fieldnames:
                tr = E1_HEADER_TRANSLATIONS.get(field, {"zh": field, "en": field})
                columns.append(TableColumn(key=field, title_zh=tr["zh"], title_en=tr["en"]))

        for r in reader:
            row_dict: Dict[str, Any] = dict(r)
            fabric_code = r.get("紋理方案代碼", "")
            scheme_meta = FABRIC_SCHEMES.get(fabric_code)
            if scheme_meta:
                row_dict["is_selected"] = scheme_meta["is_selected"]
                row_dict["fabric_name_en"] = scheme_meta["name_en"]
            else:
                row_dict["is_selected"] = False
                row_dict["fabric_name_en"] = fabric_code

            cat = r.get("開放空間類別", "")
            cat_tr = SPACE_CATEGORY_TRANSLATIONS.get(cat)
            if cat_tr:
                row_dict["space_category_en"] = cat_tr["en"]
            else:
                row_dict["space_category_en"] = cat

            rows.append(row_dict)

    _attach_english_figure_paths(root, figures, source_sha256)
    return ClimateSection(
        id=sec_id,
        title_zh=title_zh,
        title_en=title_en,
        status="OK",
        missing_files=[],
        figures=figures,
        table=TableData(columns=columns, rows=rows),
        limitations_zh=limitations_zh,
        limitations_en=limitations_en,
        source_sha256=source_sha256,
    )


def _build_utci_section(root: Path) -> ClimateSection:
    sec_id = "utci"
    title_zh = "UTCI 夏季熱舒適"
    title_en = "UTCI Summer Thermal Comfort"
    limitations_zh = (
        "探索性分析；風速採都市粗糙度對數律換算，未考慮建物風場遮蔽（留待 E5 CFD）；"
        "地面反射率 0.25，人體參數為站姿。非微氣候環境認證。"
    )
    limitations_en = (
        "Exploratory UTCI analysis; wind speed derived from roughness logarithmic profile without "
        "building aerodynamic shielding (addressed in E5 CFD); ground albedo 0.25, standing posture. "
        "Not an environmental comfort certification."
    )

    required_files = [
        "utci/utci_stress_hours_comparison.json",
        "utci/harbour_grain_utci_1400.png",
        "utci/closed_block_extension_utci_1400.png",
        "utci/courtyard_islands_utci_1400.png",
        "utci/landscape_figure_utci_1400.png",
    ]

    source_sha256: Dict[str, str] = {}
    missing_files: List[str] = []
    for rel_path in required_files:
        p = root / rel_path
        if p.is_file():
            source_sha256[rel_path] = file_sha256(p)
        else:
            missing_files.append(rel_path)

    if missing_files:
        return ClimateSection(
            id=sec_id,
            title_zh=title_zh,
            title_en=title_en,
            status="MISSING",
            missing_files=missing_files,
            figures=[],
            table=None,
            limitations_zh=limitations_zh,
            limitations_en=limitations_en,
            source_sha256=source_sha256,
        )

    figures = [
        FigureItem(
            path="utci/harbour_grain_utci_1400.png",
            path_en="utci/harbour_grain_utci_1400-en.png",
            title_zh="港埠線性紋理 14:00 UTCI 分布圖（選定）",
            title_en="Harbour grain 14:00 UTCI (Selected)",
            caption_zh="最熱夏日（2017-08-19 14:00）開放空間 UTCI 等級分布圖（港埠選定案）",
            caption_en="Open-space UTCI stress-level distribution at 14:00 on the hottest summer day (Harbour grain, selected)",
            fabric="harbour_grain",
            tag="harbour_grain",
        ),
        FigureItem(
            path="utci/closed_block_extension_utci_1400.png",
            path_en="utci/closed_block_extension_utci_1400-en.png",
            title_zh="圍合街廓延伸 14:00 UTCI 分布圖",
            title_en="Closed-block extension 14:00 UTCI",
            caption_zh="最熱夏日（2017-08-19 14:00）開放空間 UTCI 等級分布圖",
            caption_en="Open space UTCI stress level distribution at 14:00 on the hottest summer day",
            fabric="closed_block_extension",
            tag="closed_block_extension",
        ),
        FigureItem(
            path="utci/courtyard_islands_utci_1400.png",
            path_en="utci/courtyard_islands_utci_1400-en.png",
            title_zh="大型院落島 14:00 UTCI 分布圖",
            title_en="Courtyard islands 14:00 UTCI",
            caption_zh="最熱夏日（2017-08-19 14:00）開放空間 UTCI 等級分布圖",
            caption_en="Open space UTCI stress level distribution at 14:00 on the hottest summer day",
            fabric="courtyard_islands",
            tag="courtyard_islands",
        ),
        FigureItem(
            path="utci/landscape_figure_utci_1400.png",
            path_en="utci/landscape_figure_utci_1400-en.png",
            title_zh="地景為圖 14:00 UTCI 分布圖",
            title_en="Landscape as figure 14:00 UTCI",
            caption_zh="最熱夏日（2017-08-19 14:00）開放空間 UTCI 等級分布圖",
            caption_en="Open space UTCI stress level distribution at 14:00 on the hottest summer day",
            fabric="landscape_figure",
            tag="landscape_figure",
        ),
    ]

    json_path = root / "utci/utci_stress_hours_comparison.json"
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    columns = [
        TableColumn(key="scheme_name", title_zh="方案名稱", title_en="Scheme"),
        TableColumn(key="category_name", title_zh="空間類別", title_en="Space Category"),
        TableColumn(key="area_m2", title_zh="開放空間面積 (m²)", title_en="Area (m²)"),
        TableColumn(key="sensor_count", title_zh="感測點數", title_en="Sensor Points"),
        TableColumn(key="mean_utci_c", title_zh="平均 UTCI (°C)", title_en="Mean UTCI (°C)"),
        TableColumn(key="max_utci_c", title_zh="最高 UTCI (°C)", title_en="Max UTCI (°C)"),
        TableColumn(key="mean_mrt_c", title_zh="平均 MRT (°C)", title_en="Mean MRT (°C)"),
        TableColumn(key="mean_svf", title_zh="平均 SVF", title_en="Mean SVF"),
        TableColumn(key="heat_stress_pct", title_zh="熱壓力時數比 (>26°C)", title_en="Heat Stress (>26°C)"),
        TableColumn(key="strong_plus_pct", title_zh="強烈以上時數比 (>32°C)", title_en="Strong+ (>32°C)"),
        TableColumn(key="very_strong_pct", title_zh="非常強烈時數比 (>38°C)", title_en="Very Strong (>38°C)"),
    ]

    rows: List[Dict[str, Any]] = []
    fabrics_dict = data.get("fabrics", {})

    order = ["harbour_grain", "closed_block_extension", "courtyard_islands", "landscape_figure"]
    for code in order:
        f_data = fabrics_dict.get(code)
        if not f_data:
            continue
        meta = FABRIC_SCHEMES.get(code, {"name_zh": code, "name_en": code, "is_selected": False})
        stress_table = f_data.get("stress_table", {})

        # "total" first, then every category the run produced (courtyards, block land, ...).
        cat_order = ["total"] + [k for k in stress_table if k != "total"]
        for cat_key in cat_order:
            cat_data = stress_table.get(cat_key)
            if not cat_data or not cat_data.get("sensor_count"):
                continue
            cat_zh = cat_data.get("category_zh", cat_key)
            cat_tr = SPACE_CATEGORY_TRANSLATIONS.get(cat_zh, {"zh": cat_zh, "en": cat_zh})

            rows.append({
                "fabric_id": code,
                "scheme_name": meta["name_zh"],
                "scheme_name_en": meta["name_en"],
                "is_selected": meta["is_selected"],
                "category_key": cat_key,
                "category_name": cat_zh,
                "category_name_en": cat_tr["en"],
                "area_m2": f"{cat_data.get('area_m2', 0):,.0f}",
                "sensor_count": cat_data.get("sensor_count", 0),
                "mean_utci_c": f"{cat_data.get('mean_utci_c', 0):.1f}",
                "max_utci_c": f"{cat_data.get('max_utci_c', 0):.1f}",
                "mean_mrt_c": f"{cat_data.get('mean_mrt_c', 0):.1f}",
                "mean_svf": f"{cat_data.get('mean_svf', 0):.3f}",
                "heat_stress_pct": f"{cat_data.get('heat_stress_pct', 0):.1f}%",
                "strong_plus_pct": f"{cat_data.get('strong_plus_pct', 0):.1f}%",
                "very_strong_pct": f"{cat_data.get('very_strong_pct', 0):.1f}%",
            })

    _attach_english_figure_paths(root, figures, source_sha256)
    return ClimateSection(
        id=sec_id,
        title_zh=title_zh,
        title_en=title_en,
        status="OK",
        missing_files=[],
        figures=figures,
        table=TableData(columns=columns, rows=rows),
        limitations_zh=limitations_zh,
        limitations_en=limitations_en,
        source_sha256=source_sha256,
    )


def _build_e3_section(root: Path) -> ClimateSection:
    sec_id = "e3-energy"
    title_zh = "E3 建築耗能"
    title_en = "E3 Building Energy Use"
    limitations_zh = (
        "探索性分析，非能源認證。四案皆為全量 EnergyPlus 模型（港埠 253 棟完整計算）。"
        "設定為理想負荷、ASHRAE 2019 CZ5、WWR 40%；風機電力 EnergyPlus 未輸出以 0 計。"
        "僅用於四案形態相對耗能對比。"
    )
    limitations_en = (
        "Exploratory analysis, not energy certification. Full EnergyPlus building models across all four fabrics "
        "(Harbour 253 buildings calculated). Ideal loads, ASHRAE 2019 CZ5, WWR 40%; fan power not reported (set to 0). "
        "For relative morphological energy comparison only."
    )

    required_files = [
        "e3e4-final/e3e4_results_zh.csv",
        "e3e4-final/e3_eui_by_fabric.png",
    ]

    source_sha256: Dict[str, str] = {}
    missing_files: List[str] = []
    for rel_path in required_files:
        p = root / rel_path
        if p.is_file():
            source_sha256[rel_path] = file_sha256(p)
        else:
            missing_files.append(rel_path)

    if missing_files:
        return ClimateSection(
            id=sec_id,
            title_zh=title_zh,
            title_en=title_en,
            status="MISSING",
            missing_files=missing_files,
            figures=[],
            table=None,
            limitations_zh=limitations_zh,
            limitations_en=limitations_en,
            source_sha256=source_sha256,
        )

    figures = [
        FigureItem(
            path="e3e4-final/e3_eui_by_fabric.png",
            path_en="e3e4-final/e3_eui_by_fabric-en.png",
            title_zh="四案形態 EUI 比較圖（重質構造）",
            title_en="EUI Comparison by Fabric (Heavy Mass)",
            caption_zh="四案全量模型重質構造（CZ5_Mass）年度 EUI、暖氣與冷氣用電對比",
            caption_en="Annual EUI, heating, and cooling demand across full-model fabrics under heavy mass construction (CZ5_Mass)",
        )
    ]

    csv_path = root / "e3e4-final/e3e4_results_zh.csv"
    columns = [
        TableColumn(key="scheme_name", title_zh="方案", title_en="Scheme"),
        TableColumn(key="scope", title_zh="建模範圍", title_en="Scope"),
        TableColumn(key="gfa_m2", title_zh="新建 GFA (m²)", title_en="New GFA (m²)"),
        TableColumn(key="heating_demand", title_zh="暖氣需求 (kWh-熱/年)", title_en="Heating Demand (kWh-th/y)"),
        TableColumn(key="cooling_demand", title_zh="冷氣需求 (kWh-熱/年)", title_en="Cooling Demand (kWh-th/y)"),
        TableColumn(key="eui", title_zh="EUI (kWh/m²·年)", title_en="EUI (kWh/m²·y)"),
        TableColumn(key="peak_heat", title_zh="尖峰暖氣 (kW)", title_en="Peak Heating (kW)"),
        TableColumn(key="peak_cool", title_zh="尖峰冷氣 (kW)", title_en="Peak Cooling (kW)"),
    ]

    rows: List[Dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("構造") == "CZ5_Mass" and r.get("冷氣") == "開":
                scheme_zh = r.get("方案", "")
                fabric_code = ""
                scheme_en = scheme_zh
                is_selected = False
                for code, meta in FABRIC_SCHEMES.items():
                    if meta["name_zh"] == scheme_zh:
                        fabric_code = code
                        scheme_en = meta["name_en"]
                        is_selected = meta["is_selected"]
                        break

                try:
                    gfa = float(r.get("新建GFA分母_m2", 0))
                    heat = float(r.get("暖氣需求_kWh_熱", 0))
                    cool = float(r.get("冷氣需求_kWh_熱", 0))
                    eui = float(r.get("EUI_kWh_m2年", 0))
                    pk_heat = float(r.get("尖峰暖氣_kW_熱", 0))
                    pk_cool = float(r.get("尖峰冷氣_kW_熱", 0))
                except (ValueError, TypeError):
                    continue

                rows.append({
                    "fabric_id": fabric_code,
                    "scheme_name": scheme_zh,
                    "scheme_name_en": scheme_en,
                    "is_selected": is_selected,
                    "scope": r.get("建模範圍", ""),
                    "scope_en": r.get("建模範圍", "").replace("全量（", "Full (").replace("棟）", " bldgs)"),
                    "gfa_m2": f"{gfa:,.1f}",
                    "heating_demand": f"{heat:,.1f}",
                    "cooling_demand": f"{cool:,.1f}",
                    "eui": f"{eui:.1f}",
                    "peak_heat": f"{pk_heat:,.1f}",
                    "peak_cool": f"{pk_cool:,.1f}",
                })

    _attach_english_figure_paths(root, figures, source_sha256)
    return ClimateSection(
        id=sec_id,
        title_zh=title_zh,
        title_en=title_en,
        status="OK",
        missing_files=[],
        figures=figures,
        table=TableData(columns=columns, rows=rows),
        limitations_zh=limitations_zh,
        limitations_en=limitations_en,
        source_sha256=source_sha256,
    )


def _build_e4_section(root: Path) -> ClimateSection:
    sec_id = "e4-thermal-mass"
    title_zh = "E4 蓄熱"
    title_en = "E4 Thermal Mass Performance"
    limitations_zh = (
        "探索性分析，非材料熱性能認證。僅針對港埠方案全量 253 棟進行重質（CZ5_Mass）"
        "與外牆等效 U 值輕質（CZ5_Light_U_Matched）對比，評估夜間蓄熱延遲與尖峰負荷削減效果。"
    )
    limitations_en = (
        "Exploratory analysis, not material thermal certification. Compares heavy mass (CZ5_Mass) with "
        "U-value-matched light construction (CZ5_Light_U_Matched) across Harbour grain's 253 buildings to "
        "evaluate thermal lag and peak load shaving."
    )

    required_files = [
        "e3e4-final/e3e4_results_zh.csv",
        "e3e4-final/e4_harbour_mass_vs_light.png",
    ]

    source_sha256: Dict[str, str] = {}
    missing_files: List[str] = []
    for rel_path in required_files:
        p = root / rel_path
        if p.is_file():
            source_sha256[rel_path] = file_sha256(p)
        else:
            missing_files.append(rel_path)

    if missing_files:
        return ClimateSection(
            id=sec_id,
            title_zh=title_zh,
            title_en=title_en,
            status="MISSING",
            missing_files=missing_files,
            figures=[],
            table=None,
            limitations_zh=limitations_zh,
            limitations_en=limitations_en,
            source_sha256=source_sha256,
        )

    figures = [
        FigureItem(
            path="e3e4-final/e4_harbour_mass_vs_light.png",
            path_en="e3e4-final/e4_harbour_mass_vs_light-en.png",
            title_zh="港埠方案重質 vs 輕質構造蓄熱表現",
            title_en="Harbour Grain Heavy Mass vs Light Construction",
            caption_zh="港埠 253 棟重質與等效輕質構造在過熱時數、暖氣需求與冷負荷之對比（選定方案）",
            caption_en="Thermal mass comparison of overheating hours, heating demand, and peak cooling load for Harbour grain (253 buildings, Selected)",
            fabric="harbour_grain",
        )
    ]

    csv_path = root / "e3e4-final/e3e4_results_zh.csv"
    columns = [
        TableColumn(key="metric_zh", title_zh="指標", title_en="Metric"),
        TableColumn(key="mass_val", title_zh="重質 (CZ5_Mass)", title_en="Heavy Mass"),
        TableColumn(key="light_val", title_zh="輕質 (CZ5_Light)", title_en="Light Construction"),
        TableColumn(key="diff_val", title_zh="輕質減重質", title_en="Difference (Light - Heavy)"),
    ]

    rows = [
        {
            "metric_zh": "夏季過熱時數（6–8 月 >26 °C，只開暖氣，樓地板加權小時）",
            "metric_en": "Summer Overheating Hours (Jun–Aug >26°C, heating only, floor-weighted hours)",
            "mass_val": "840.4",
            "light_val": "883.9",
            "diff_val": "+43.5",
        },
        {
            "metric_zh": "冬季暖氣需求（12–2 月，kWh-熱）",
            "metric_en": "Winter Heating Demand (Dec–Feb, kWh-th)",
            "mass_val": "5,456,772.7",
            "light_val": "5,466,727.2",
            "diff_val": "+9,954.4",
        },
        {
            "metric_zh": "尖峰冷負荷（冷氣開啟，kW-熱）",
            "metric_en": "Peak Cooling Load (AC on, kW-th)",
            "mass_val": "4,402.8",
            "light_val": "4,662.7",
            "diff_val": "+259.9",
        },
    ]

    _attach_english_figure_paths(root, figures, source_sha256)
    return ClimateSection(
        id=sec_id,
        title_zh=title_zh,
        title_en=title_en,
        status="OK",
        missing_files=[],
        figures=figures,
        table=TableData(columns=columns, rows=rows),
        limitations_zh=limitations_zh,
        limitations_en=limitations_en,
        source_sha256=source_sha256,
    )


def _build_e5_section(root: Path) -> ClimateSection:
    sec_id = "e5-cfd"
    title_zh = "E5 行人風場"
    title_en = "E5 Pedestrian Wind Comfort"

    readme_path = root / "e5-cfd/README_zh.md"
    commander_limitations_zh = ""
    if readme_path.is_file():
        try:
            content = readme_path.read_text(encoding="utf-8")
            marker = "## Commander 審查補充（2026-10-17）：行人高度換算的限制"
            if marker in content:
                commander_limitations_zh = content[content.index(marker):].strip()
        except Exception:
            pass

    if not commander_limitations_zh:
        commander_limitations_zh = (
            "## Commander 審查補充（2026-10-17）：行人高度換算的限制\n"
            "- 行人層風速不是直接在 1.5 m 取樣，而是取每個垂直柱「離地最近一層流體網格中心」（高度 zP，粗網格下約 1–15 m）"
            "的 CFD 風速，再用對數律（z0＝0.5 m）換算到 1.5 m。\n"
            "- 對數律只適用於地表附近、流場接近平衡的開闊區；在建築背風區、轉角加速區與迴流區，實際剖面不符合對數律，"
            "換算值可能高估或低估。zP 越高，換算誤差越大。\n"
            "- 因此本結果只能用來比較「哪裡相對有風、哪裡相對靜風」的空間趨勢，不能當作行人風舒適度的定量判定；"
            "Lawson 分級亦僅為粗略概估。研究等級需加密地表附近網格（第一層 ≤ 0.5 m）並直接在 1.5 m 取樣。\n"
            "- **Lawson 概估圖不採用**：本次以 4 風向頻率加權的「平均」風速分級，Lawson 準則應以超越機率"
            "（例如 5% 時間被超越的風速）判定；用平均值必然全區落在「戶外長坐」，圖面無資訊量且會高估舒適度，"
            "因此報告與 demo 不使用 `cfd_lawson_comfort.png`（檔案保留供查核）。"
        )

    limitations_en = (
        "## Commander Review Note (2026-10-17): Pedestrian Level Conversion Limitations\n"
        "- Pedestrian wind speed is not sampled directly at 1.5 m, but taken from the cell center of the first "
        "fluid layer above ground (height zP ~1–15 m) and converted to 1.5 m using logarithmic law (z0 = 0.5 m).\n"
        "- The log law applies only to open terrain near equilibrium; in building wakes, corner acceleration, "
        "and recirculation zones, the profile deviates, causing over- or under-estimation. Higher zP increases error.\n"
        "- Results indicate relative spatial trends ('where is windier vs calmer') only, not quantitative comfort criteria; "
        "Lawson grading is only a rough estimation. Research-grade assessment requires fine boundary-layer mesh (first layer ≤ 0.5 m) "
        "and direct 1.5 m sampling.\n"
        "- **Lawson Map Excluded**: Mean speed weighting places the entire site in 'long-term sitting' without discriminatory value "
        "and overestimates comfort (exceedance probability criteria should be used); `cfd_lawson_comfort.png` is retained for audit "
        "only and excluded from demo views."
    )

    required_files = [
        "e5-cfd/results_table.json",
        "e5-cfd/README_zh.md",
        "e5-cfd/cfd_4winds_summary.png",
        "e5-cfd/cfd_wind_risk_zones.png",
        "e5-cfd/cfd_sw_wind_ratio.png",
        "e5-cfd/cfd_w_wind_ratio.png",
        "e5-cfd/cfd_s_wind_ratio.png",
        "e5-cfd/cfd_nw_wind_ratio.png",
    ]

    source_sha256: Dict[str, str] = {}
    missing_files: List[str] = []
    for rel_path in required_files:
        p = root / rel_path
        if p.is_file():
            source_sha256[rel_path] = file_sha256(p)
        else:
            missing_files.append(rel_path)

    if missing_files:
        return ClimateSection(
            id=sec_id,
            title_zh=title_zh,
            title_en=title_en,
            status="MISSING",
            missing_files=missing_files,
            figures=[],
            table=None,
            limitations_zh=commander_limitations_zh,
            limitations_en=limitations_en,
            source_sha256=source_sha256,
        )

    figures = [
        FigureItem(
            path="e5-cfd/cfd_4winds_summary.png",
            path_en="e5-cfd/cfd_4winds_summary-en.png",
            title_zh="4 風向 2x2 對比總覽面板",
            title_en="4-Direction Wind Speed Ratio Summary (2x2)",
            caption_zh="西南、西、南、西北四盛行風向在行人高度 1.5m 之風速比（共用色階）",
            caption_en="Pedestrian level (1.5m) wind speed ratio across SW, W, S, NW prevailing directions (shared color scale)",
        ),
        FigureItem(
            path="e5-cfd/cfd_wind_risk_zones.png",
            path_en="e5-cfd/cfd_wind_risk_zones-en.png",
            title_zh="強風加速區與靜風區複合分區圖",
            title_en="High Wind & Stagnant Wind Risk Zones",
            caption_zh="強風區（風速比 >1.2）與靜風區（風速比 <0.3）空間分布熱點",
            caption_en="Spatial hotspots of high wind acceleration (>1.2) and stagnant wind zones (<0.3)",
        ),
        FigureItem(
            path="e5-cfd/cfd_sw_wind_ratio.png",
            path_en="e5-cfd/cfd_sw_wind_ratio-en.png",
            title_zh="西南風（SW 225°）風速比分布圖",
            title_en="Southwest Wind (SW 225°) Wind Speed Ratio",
            caption_zh="盛行頻率 21.5%，參考風速 6.10 m/s",
            caption_en="Prevailing frequency 21.5%, reference wind speed 6.10 m/s",
            tag="SW",
        ),
        FigureItem(
            path="e5-cfd/cfd_w_wind_ratio.png",
            path_en="e5-cfd/cfd_w_wind_ratio-en.png",
            title_zh="西風（W 270°）風速比分布圖",
            title_en="West Wind (W 270°) Wind Speed Ratio",
            caption_zh="盛行頻率 20.5%，參考風速 5.00 m/s",
            caption_en="Prevailing frequency 20.5%, reference wind speed 5.00 m/s",
            tag="W",
        ),
        FigureItem(
            path="e5-cfd/cfd_s_wind_ratio.png",
            path_en="e5-cfd/cfd_s_wind_ratio-en.png",
            title_zh="南風（S 180°）風速比分布圖",
            title_en="South Wind (S 180°) Wind Speed Ratio",
            caption_zh="盛行頻率 17.7%，參考風速 4.44 m/s",
            caption_en="Prevailing frequency 17.7%, reference wind speed 4.44 m/s",
            tag="S",
        ),
        FigureItem(
            path="e5-cfd/cfd_nw_wind_ratio.png",
            path_en="e5-cfd/cfd_nw_wind_ratio-en.png",
            title_zh="西北風（NW 315°）風速比分布圖",
            title_en="Northwest Wind (NW 315°) Wind Speed Ratio",
            caption_zh="盛行頻率 7.7%，參考風速 4.32 m/s",
            caption_en="Prevailing frequency 7.7%, reference wind speed 4.32 m/s",
            tag="NW",
        ),
    ]

    json_path = root / "e5-cfd/results_table.json"
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    columns = [
        TableColumn(key="direction", title_zh="風向", title_en="Direction"),
        TableColumn(key="angle", title_zh="入射角 (°)", title_en="Angle (°)"),
        TableColumn(key="frequency", title_zh="出現頻率 (%)", title_en="Frequency (%)"),
        TableColumn(key="uref", title_zh="參考風速 Uref (m/s)", title_en="Ref Speed Uref (m/s)"),
        TableColumn(key="mesh_cells", title_zh="網格數 (格)", title_en="Mesh Cells"),
        TableColumn(key="iterations", title_zh="迭代數", title_en="Iterations"),
        TableColumn(key="convergence", title_zh="收斂狀態", title_en="Convergence"),
        TableColumn(key="runtime_s", title_zh="耗時 (秒)", title_en="Runtime (s)"),
        TableColumn(key="max_ratio", title_zh="最大風速比", title_en="Max Wind Ratio"),
        TableColumn(key="mean_ratio", title_zh="平均風速比", title_en="Mean Wind Ratio"),
        TableColumn(key="high_wind_area", title_zh="強風區面積 (>1.2)", title_en="High Wind Area (>1.2)"),
        TableColumn(key="stagnant_area", title_zh="靜風區面積 (<0.3)", title_en="Stagnant Area (<0.3)"),
    ]

    rows: List[Dict[str, Any]] = []
    dir_order = ["SW", "W", "S", "NW"]
    for d in dir_order:
        item = data.get(d)
        if not item:
            continue
        rows.append({
            "direction": d,
            "angle": f"{item.get('wind_direction_deg', 0):.0f}°",
            "frequency": f"{item.get('frequency_pct', 0):.1f}%",
            "uref": f"{item.get('uref_10m', 0):.2f}",
            "mesh_cells": f"{item.get('mesh_cells', 0):,}",
            "iterations": item.get("iterations", 0),
            "convergence": "收斂 (殘差<1e-4)" if item.get("converged") else "未收斂",
            "convergence_en": "Converged (<1e-4)" if item.get("converged") else "Not converged",
            "runtime_s": f"{item.get('runtime_seconds', 0):.1f}s",
            "max_ratio": f"{item.get('max_wind_ratio', 0):.2f}",
            "mean_ratio": f"{item.get('mean_wind_ratio', 0):.2f}",
            "high_wind_area": f"{item.get('high_wind_ratio_area_m2', 0):,.1f} m²",
            "stagnant_area": f"{item.get('stagnant_wind_area_m2', 0):,.1f} m²",
        })

    _attach_english_figure_paths(root, figures, source_sha256)
    return ClimateSection(
        id=sec_id,
        title_zh=title_zh,
        title_en=title_en,
        status="OK",
        missing_files=[],
        figures=figures,
        table=TableData(columns=columns, rows=rows),
        limitations_zh=commander_limitations_zh,
        limitations_en=limitations_en,
        source_sha256=source_sha256,
    )


@router.get("", response_model=List[ClimateSection])
@router.get("/", response_model=List[ClimateSection], include_in_schema=False)
def list_climate_extras(request: Request) -> List[ClimateSection]:
    root = get_climate_artifact_root(request)
    sections = [
        _build_e1_section(root),
        _build_utci_section(root),
        _build_e3_section(root),
        _build_e4_section(root),
        _build_e5_section(root),
    ]
    for section in sections:
        section.limitations_zh = _plain_text(section.limitations_zh)
        section.limitations_en = _plain_text(section.limitations_en)
    return sections


def _plain_text(text: str) -> str:
    """Strip Markdown heading/emphasis/code markers; the panel renders limitations as plain text."""
    lines = [line.lstrip("#").strip() if line.lstrip().startswith("#") else line for line in text.splitlines()]
    return "\n".join(lines).replace("**", "").replace("`", "")


@router.get("/files/{path:path}")
def get_climate_artifact_file(path: str, request: Request) -> FileResponse:
    # Decode path in case percent-encoded characters are passed
    decoded_path = urllib.parse.unquote(path)

    # Reject traversal markers explicitly
    if ".." in path or ".." in decoded_path or "%2e" in path.lower():
        raise HTTPException(status_code=404, detail="Path traversal forbidden")

    if path.startswith("/") or path.startswith("\\") or decoded_path.startswith("/") or decoded_path.startswith("\\"):
        raise HTTPException(status_code=404, detail="Absolute paths forbidden")

    parts = Path(decoded_path).parts
    if not parts or parts[0] not in ALLOWED_SUBDIRS:
        raise HTTPException(status_code=404, detail="Directory not allowed")

    ext = Path(decoded_path).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=404, detail="File extension not allowed")

    root = get_climate_artifact_root(request)
    try:
        root_resolved = root.resolve()
        target = (root_resolved / decoded_path).resolve()
        allowed_subroot = (root_resolved / parts[0]).resolve()
        target.relative_to(allowed_subroot)
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid path")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if Path(decoded_path).stem.endswith("-en") and _validated_english_figure(root, decoded_path) is None:
        raise HTTPException(status_code=404, detail="English figure is not registered or its hash is invalid")

    media_types = {
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".csv": "text/csv; charset=utf-8",
        ".json": "application/json",
        ".md": "text/markdown; charset=utf-8",
    }
    return FileResponse(target, media_type=media_types.get(ext, "application/octet-stream"))
