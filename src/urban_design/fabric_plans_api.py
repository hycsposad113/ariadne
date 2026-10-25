"""Read-only exploratory FAB1 artifact projection; no ledger/store dependency."""
from __future__ import annotations

import csv
import json
import hashlib
import os
import math
import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from .fabric_syntax_segments import SegmentCollection
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, JsonValue
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SYNTAX_ROOT = PROJECT_ROOT / "artifacts/net2/round-7/syntax"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts/fab1/run-8"
SOURCE_PAIRS = {
    "net2": (ARTIFACT_ROOT, SYNTAX_ROOT),
    "net2-r3": (PROJECT_ROOT / "artifacts/fab1/run-7", PROJECT_ROOT / "artifacts/net2/round-3/syntax"),
    "net1": (PROJECT_ROOT / "artifacts/fab1/run-6", PROJECT_ROOT / "artifacts/net1/round-3/syntax"),
    "run5-int1b": (PROJECT_ROOT / "artifacts/fab1/run-5", PROJECT_ROOT / "artifacts/int1b/syntax"),
}


def resolve_source_roots(artifact_root: Path | None = None, syntax_root: Path | None = None) -> tuple[Path, Path]:
    """Choose a complete source pair; legacy sources require explicit selection."""
    profile = os.environ.get("URBAN_DESIGN_FABRIC_SOURCE", "net2")
    if profile not in SOURCE_PAIRS:
        raise ValueError("Unknown URBAN_DESIGN_FABRIC_SOURCE; use net2, net2-r3, net1 or run5-int1b")
    default_root, default_syntax = SOURCE_PAIRS[profile]
    root = Path(artifact_root) if artifact_root is not None else default_root
    syntax = Path(syntax_root) if syntax_root is not None else (default_syntax if artifact_root is None else root / "syntax")
    # Known retained packages cannot be combined across runs.
    for paired_root, paired_syntax in SOURCE_PAIRS.values():
        if root.resolve() == paired_root.resolve():
            if syntax_root is None:
                syntax = paired_syntax
            elif syntax.resolve() != paired_syntax.resolve() and any(syntax.resolve() == pair[1].resolve() for pair in SOURCE_PAIRS.values()):
                raise ValueError("Fabric plan and syntax source pair mismatch")
    return root, syntax


def source_package(root: Path, syntax: Path) -> dict[str, str]:
    return {"artifact_root": str(root.resolve()), "syntax_root": str(syntax.resolve())}


def _verbatim_copy_ok(raw: dict, plan: dict, plan_path: Path, fabric_id: str) -> bool:
    source = raw.get("copied_verbatim_from")
    if not source or plan.get("fabric_id") not in (fabric_id, "fabric." + fabric_id):
        return False
    src = Path(source) if Path(source).is_absolute() else PROJECT_ROOT / source
    return src.is_file() and src.read_bytes() == plan_path.read_bytes()


def verify_selected_plan_receipt(root: Path, fabric_id: str, receipt: dict) -> None:
    expected = "sha256:" + hashlib.sha256((root / f"{fabric_id}-plan.json").read_bytes()).hexdigest()
    if receipt.get("sha256") != expected:
        raise ValueError("Syntax evidence does not belong to the selected plan")
FABRICS = {
    "harbour_grain": "港埠線性紋理",
    "closed_block_extension": "圍合街廓延伸",
    "courtyard_islands": "大型院落島",
    "landscape_figure": "地景為圖",
}

CHECK_EXPLANATIONS = {
    "BLOCK_LAND_BUDGET": "街廓／建築用地比例未達檢查要求。",
    "BUILDING_STREET_EDGE_3M": "部分建築未符合距街道邊緣 3 公尺內的檢查要求。",
    "FAB1C_NEW_GFA_TARGET": "新增樓地板面積未達本輪目標。",
    "NEW_GFA_TARGET": "新增樓地板面積未達檢查目標。",
    "NORTHEAST_REGULAR_BLOCKS": "東北區規整街廓的數量或形態未符合要求。",
    "NO_LARGE_UNBUILT_PLOT": "仍有未符合要求的大面積未建築地塊。",
    "SERVICE_FUNCTION_FRONTAGE": "部分服務設施未符合臨街要求。",
    "SOUTH_QUAY_FACADE_CONTINUITY": "南岸碼頭帶的臨水立面連續比例不足。",
    "SOUTH_QUAY_MAX_GAP": "南岸碼頭帶缺少實際臨水立面，或立面間隙超過 12 公尺。",
    "SOUTH_QUAY_SHARED_ALLEY": "南岸碼頭帶的共用巷道配置未符合要求。",
    "COURTYARD_ISLAND_COUNT_SPACING": "院落島的數量或間距未符合要求。",
    "COURTYARD_ISLAND_GLOBAL_MEMBERSHIP": "部分建築未符合院落島歸屬要求。",
    "COURTYARD_ISLAND_ROAD_CLEARANCE": "部分院落島未符合道路退距要求。",
    "COURTYARD_ISLAND_SINGLE_VOID": "院落島未形成符合要求的單一完整內院。",
}

CHECK_EXPLANATIONS_EN = {
    "BLOCK_LAND_BUDGET": "The share of land allocated to blocks and buildings does not meet this check.",
    "BUILDING_STREET_EDGE_3M": "Some buildings are not within 3 metres of the street edge.",
    "FAB1C_NEW_GFA_TARGET": "New floor area does not reach the target for this run.",
    "NEW_GFA_TARGET": "New floor area does not reach the check target.",
    "NORTHEAST_REGULAR_BLOCKS": "The number or shape of regular northeast blocks does not meet this check.",
    "NO_LARGE_UNBUILT_PLOT": "Large unbuilt plots remain that do not meet this check.",
    "SERVICE_FUNCTION_FRONTAGE": "Some service facilities do not meet the street frontage requirement.",
    "SOUTH_QUAY_FACADE_CONTINUITY": "The south quay has insufficient continuous waterfront frontage.",
    "SOUTH_QUAY_MAX_GAP": "The south quay lacks waterfront frontage or has gaps greater than 12 metres.",
    "SOUTH_QUAY_SHARED_ALLEY": "The south quay shared alleys do not meet this check.",
    "COURTYARD_ISLAND_COUNT_SPACING": "The number or spacing of courtyard islands does not meet this check.",
    "COURTYARD_ISLAND_GLOBAL_MEMBERSHIP": "Some buildings do not meet the courtyard island membership requirement.",
    "COURTYARD_ISLAND_ROAD_CLEARANCE": "Some courtyard islands do not meet the road setback requirement.",
    "COURTYARD_ISLAND_SINGLE_VOID": "Courtyard islands do not form the required single continuous courtyard.",
}

LAND_USE_CATEGORIES = {
    "保留建築": "retained_buildings", "水岸公共帶": "waterfront_public",
    "道路": "road", "街坊公共公園": "park", "港灣綠軸公園": "park",
    "港灣綠軸道路分界鄰里公園": "park", "街廓／建築用地": "block",
    "西側點樓完整矩形街坊管理用地": "block", "服務空間": "service",
    "廣場": "plaza", "街坊設備院": "utility_yard",
    "街坊邊界綠化維護院": "maintenance_green",
    "東北街坊共用植栽及維護空間": "shared_planting",
}
LandUseCategory = Literal[
    "retained_buildings", "waterfront_public", "road", "park", "block",
    "service", "plaza", "utility_yard", "maintenance_green", "shared_planting",
]
GEOMETRY_CATEGORY_ALIASES = {
    "retained_buildings": "retained_buildings",
    "waterfront": "waterfront_public",
    "waterfront_public": "waterfront_public",
    "roads": "road",
    "road": "road",
    "parks": "park",
    "park": "park",
    "blocks": "block",
    "block": "block",
    "service": "service",
    "plaza": "plaza",
    "utility_yard": "utility_yard",
    "maintenance_green": "maintenance_green",
    "shared_planting": "shared_planting",
}


def normalize_land_use_category(label: str) -> str:
    if not isinstance(label, str):
        raise ValueError("Land-use category must be text")
    label = re.sub(r"\s+use-\d+(?:-road-unit-\d+)?$", "", label).strip()
    try:
        return LAND_USE_CATEGORIES[label]
    except KeyError as exc:
        raise ValueError(f"Unknown land-use category: {label}") from exc


def normalize_geometry_category(category: str) -> str:
    """Map the source artifact's category vocabulary to the stable API taxonomy."""
    if not isinstance(category, str):
        raise ValueError("Geometry category must be text")
    if category in GEOMETRY_CATEGORY_ALIASES:
        return GEOMETRY_CATEGORY_ALIASES[category]
    return normalize_land_use_category(category)

class ReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Feature(ReadModel):
    type: Literal["Feature"] = "Feature"
    id: str | int | None = None
    geometry: dict[str, JsonValue]
    properties: dict[str, JsonValue]

class FeatureCollection(ReadModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[Feature]

class Layers(ReadModel):
    roads: FeatureCollection
    blocks: FeatureCollection
    buildings: FeatureCollection
    land_use: FeatureCollection
    parks: FeatureCollection
    site: FeatureCollection
    water: FeatureCollection | None = None

class LandUseRow(ReadModel):
    category: LandUseCategory
    category_zh: str
    feature_id: str
    area_m2: float
    site_land_percent: float
    geometry_type: str
    status: str
    area_basis: str

class PlanSummary(ReadModel):
    fabric_id: str
    label_zh: str
    metrics: dict[str, JsonValue]

class PlanCatalog(ReadModel):
    status: Literal["EXPLORATORY_DRAFT"] = "EXPLORATORY_DRAFT"
    plans: list[PlanSummary]
    source_package: dict[str, str]

class PlanDetail(PlanSummary):
    status: Literal["EXPLORATORY_DRAFT"] = "EXPLORATORY_DRAFT"
    source_crs: str
    output_crs: Literal["EPSG:4326"] = "EPSG:4326"
    projected_crs: Literal["EPSG:28992"] = "EPSG:28992"
    layers: Layers
    layers_projected: Layers
    land_use_table: list[LandUseRow]
    checks: dict[str, JsonValue]
    check_explanations_zh: dict[str, str]
    check_explanations_en: dict[str, str]
    syntax_summary: dict[str, JsonValue] | None
    design_statement_markdown: str
    limitations: list[str]
    source_package: dict[str, str]


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite artifact value")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _finite(item)


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected artifact object")
    _finite(value)
    return value


def _plan(root: Path, fabric_id: str) -> dict:
    if fabric_id not in FABRICS:
        raise HTTPException(404, "找不到此方案")
    plan = _json(root / f"{fabric_id}-plan.json")
    if plan.get("fabric_id") != f"fabric.{fabric_id}" or CRS.from_user_input(plan.get("crs")) != CRS.from_epsg(28992):
        raise ValueError("Fabric identity or source CRS mismatch")
    return plan


def _collection(features: list[dict], transformer: Transformer | None = None) -> FeatureCollection:
    converted = []
    for feature in features:
        geometry = shape(feature["geometry"])
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("Invalid artifact geometry")
        output_geometry = transform(transformer.transform, geometry) if transformer is not None else geometry
        serialized_geometry = json.loads(json.dumps(mapping(output_geometry), allow_nan=False))
        _finite(serialized_geometry)
        if transformer is not None:
            bounds = shape(serialized_geometry).bounds
            if not (-180 <= bounds[0] <= bounds[2] <= 180 and -90 <= bounds[1] <= bounds[3] <= 90):
                raise ValueError("Invalid WGS84 bounds")
        # Nested source geometry (e.g. road right_of_way) retains its source
        # coordinates only in artifacts; omit it from projected and WGS84 properties.
        properties = {k: v for k, v in feature.get("properties", {}).items()
                      if not (isinstance(v, dict) and "coordinates" in v)}
        if "category" in properties:
            properties["category"] = normalize_geometry_category(properties["category"])
        converted.append(Feature(id=feature.get("id"), geometry=serialized_geometry, properties=properties))
    return FeatureCollection(features=converted)



def _verified_checks(root: Path, fabric_id: str, plan: dict) -> dict:
    raw_path = root / f"{fabric_id}-checks.json"
    raw = _json(raw_path)
    supplemental = root / f"{fabric_id}-api-checks.json"
    if not supplemental.exists():
        if raw.get("fabric_id") != fabric_id:
            raise ValueError("Checks identity mismatch")
        return raw
    checks = _json(supplemental)
    if checks.get("schema_version") != "fabric-api-checks-v1" or checks.get("fabric_id") != fabric_id:
        raise ValueError("Supplemental checks identity mismatch")
    # A supplement can normalize a qualified identity, never invent one.
    # A verbatim-copied plan carries fresh checks without a top-level fabric_id; its identity
    # then comes from the plan, which must be this fabric and byte-identical to the declared source.
    verbatim = _verbatim_copy_ok(raw, plan, root / f"{fabric_id}-plan.json", fabric_id)
    if raw.get("fabric_id") not in (fabric_id, plan["fabric_id"]) and not verbatim:
        raise ValueError("Raw checks identity mismatch")
    receipts = checks.get("source_receipts", {})
    for name, path in (("plan", root / f"{fabric_id}-plan.json"), ("raw_checks", raw_path)):
        expected = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if receipts.get(name, {}).get("sha256") != expected:
            raise ValueError("Supplemental checks source receipt drift")
    core = raw.get("core_validator", raw)
    if not isinstance(core, dict) or checks.get("core_validator") != core:
        raise ValueError("Supplemental checks validator mismatch")
    if core != plan.get("validation") and not (verbatim and sorted(core.get("checks", {})) == sorted((plan.get("validation") or {}).get("checks", {}))):
        raise ValueError("Supplemental checks validator mismatch")
    if checks.get("failure_ids") != raw.get("failure_ids") or sorted(raw.get("failure_ids", [])) != sorted(core.get("failure_ids", [])):
        raise ValueError("Supplemental checks failures mismatch")
    return checks

def _detail(root: Path, fabric_id: str, syntax_root: Path, lang: Literal["zh", "en"] = "zh") -> PlanDetail:
    plan = _plan(root, fabric_id)
    transformer = Transformer.from_crs(plan["crs"], "EPSG:4326", always_xy=True)
    source_features = {name: plan[name] for name in ("roads", "blocks", "buildings", "land_use")}
    for feature in source_features["land_use"]:
        properties = feature.get("properties")
        if not isinstance(properties, dict) or "category" not in properties:
            raise ValueError("Land-use geometry category is missing")
    source_features["parks"] = [
        feature for feature in plan["land_use"]
        if feature.get("properties", {}).get("category") == "parks"
    ]
    # Commander 2026-10-12: water inside the site = site minus all allocated land (canal was not drawn).
    from shapely.geometry import mapping as _mapping
    from shapely.ops import unary_union as _union
    _water = shape(plan["site"]).difference(_union([shape(f["geometry"]) for f in plan["land_use"]]))
    source_features["site"] = [{"geometry": plan["site"], "properties": {}}]
    source_features["water"] = [{"geometry": _mapping(_water), "properties": {"category_zh": "水域"}}] if not _water.is_empty else []
    layers = {name: _collection(features, transformer) for name, features in source_features.items()}
    layers_projected = {name: _collection(features) for name, features in source_features.items()}
    with (root / f"{fabric_id}-landuse.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = [LandUseRow(category=normalize_land_use_category(r["用途或類別"]), category_zh=r["用途或類別"], feature_id=r["圖徵 ID"], area_m2=float(r["面積_m2"]),
                           site_land_percent=float(r["占基地陸地比例_percent"]), geometry_type=r["幾何類型"],
                           status=r["狀態"], area_basis=r["面積口徑"]) for r in csv.DictReader(stream)]
    # CSV values are rounded per feature. Calculate percentages from the
    # immutable projected geometry to preserve the land-budget denominator.
    features = {str(f["id"]): f for f in plan["land_use"]}
    denominator = float(plan["metrics"]["land_area_m2"])
    if denominator <= 0:
        raise ValueError("Invalid land denominator")
    merged: dict[str, LandUseRow] = {}
    output = []
    for row in rows:
        row.category_zh = re.sub(r"\s+use-\d+(?:-road-unit-\d+)?$", "", row.category_zh).strip()
        row.area_m2 = shape(features[row.feature_id]["geometry"]).area
        row.site_land_percent = row.area_m2 / denominator * 100
        if row.category in merged:
            merged[row.category].area_m2 += row.area_m2
            merged[row.category].site_land_percent += row.site_land_percent
        else:
            row.feature_id = "summary:" + row.category
            row.geometry_type = "Polygon/MultiPolygon"
            row.area_basis = "同類用途圖徵投影幾何面積加總；分母為基地陸地面積"
            merged[row.category] = row
            output.append(row)
    rows = output
    if not math.isclose(sum(row.site_land_percent for row in rows), 100, abs_tol=1e-6):
        raise ValueError("Land allocation does not sum to 100 percent")
    _finite([row.model_dump() for row in rows])
    statement = root / "ai-explanations" / f"{fabric_id}-design-statement-{lang}.md"
    try:
        statement_markdown = statement.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        statement_markdown = "English design statement updating" if lang == "en" else "設計說明更新中"
    syntax_path = syntax_root / "syntax-summary.json"
    syntax = _json(syntax_path) if syntax_path.exists() else None
    if syntax is not None:
        syntax = {**syntax, "results": [row for row in syntax.get("results", []) if row.get("fabric_id") == fabric_id]}
        for row in syntax["results"]:
            receipt = row.get("source_receipts", {}).get("plan")
            if receipt is None and any(root.resolve() == pair[0].resolve() for pair in SOURCE_PAIRS.values()):
                raise ValueError("Syntax plan receipt is missing")
            if receipt is not None:
                verify_selected_plan_receipt(root, fabric_id, receipt)
    checks = _verified_checks(root, fabric_id, plan)
    return PlanDetail(fabric_id=fabric_id, label_zh=FABRICS[fabric_id], metrics=plan["metrics"], source_crs=plan["crs"],
                      layers=Layers(**layers), layers_projected=Layers(**layers_projected), land_use_table=rows, checks=checks,
                      check_explanations_zh={key: CHECK_EXPLANATIONS.get(key, "此項檢查尚未通過，請查看原始檢查資料與失敗位置。") for key in checks.get("failure_ids", [])}, check_explanations_en={key: CHECK_EXPLANATIONS_EN.get(key, "This check has not passed. Review the original check data and failure locations.") for key in checks.get("failure_ids", [])}, syntax_summary=syntax,
                      design_statement_markdown=statement_markdown,
                      limitations=plan.get("limitations", []), source_package=source_package(root, syntax_root))


def create_fabric_plans_router(artifact_root: Path | None = None, syntax_root: Path | None = None) -> APIRouter:
    root, syntax = resolve_source_roots(artifact_root, syntax_root)
    router = APIRouter(prefix="/api/v1/fabric-plans", tags=["探索性方案"])

    @router.get("", response_model=PlanCatalog)
    def catalog() -> PlanCatalog:
        try:
            return PlanCatalog(plans=[PlanSummary(fabric_id=key, label_zh=label, metrics=_plan(root, key)["metrics"])
                                      for key, label in FABRICS.items()], source_package=source_package(root, syntax))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(503, "方案檔案尚未備妥或驗證失敗") from exc

    @router.get("/{fabric_id}", response_model=PlanDetail)
    def detail(fabric_id: str, lang: Literal["zh", "en"] = "zh") -> PlanDetail:
        try:
            return _detail(root, fabric_id, syntax, lang)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(503, "方案檔案尚未備妥或驗證失敗") from exc

    syntax_cache: dict[tuple[str, str], tuple[tuple, dict[str, Any]]] = {}

    def prewarm() -> None:
        # Background verification so the first Compare visit after a restart does not wait ~30 s.
        for fabric_id in FABRICS:
            for mode in ("pedestrian", "bicycle", "motor_vehicle"):
                try:
                    syntax_segments(fabric_id, mode)  # type: ignore[arg-type]
                except Exception:  # missing packages stay a 503 at request time
                    pass

    @router.get("/{fabric_id}/syntax/{mode}", response_model=SegmentCollection)
    def syntax_segments(fabric_id: str, mode: Literal["pedestrian", "bicycle", "motor_vehicle"]) -> dict[str, Any]:
        if fabric_id not in FABRICS:
            raise HTTPException(404, "Unknown fabric plan")
        from .fabric_syntax_segments import load_verified
        try:
            segments = syntax / "segments" / f"{fabric_id}-{mode}.geojson"
            plan_path = root / f"{fabric_id}-plan.json"
            # Full verification takes several seconds per call; reuse it until either file changes.
            key = (str(segments), segments.stat().st_mtime_ns, segments.stat().st_size, plan_path.stat().st_mtime_ns, plan_path.stat().st_size)
            cached = syntax_cache.get((fabric_id, mode))
            if cached and cached[0] == key:
                return cached[1]
            result=load_verified(segments)
            if result['metadata']['fabric_id']!=fabric_id or result['metadata']['mode']!=mode:
                raise ValueError('BLOCKED: request identity mismatch')
            verify_selected_plan_receipt(root, fabric_id, result['metadata']['source_receipts']['plan'])
            syntax_cache[(fabric_id, mode)] = (key, result)
            return result
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(503, "BLOCKED: syntax segment evidence missing or drifted") from exc

    if os.environ.get("URBAN_DESIGN_PREWARM_SYNTAX", "0") == "1":
        import threading
        threading.Thread(target=prewarm, name="fabric-syntax-prewarm", daemon=True).start()

    @router.get("/{fabric_id}/figures/{kind}")
    def figure(fabric_id: str, kind: Literal["plan", "axon", "landuse"]) -> FileResponse:
        if fabric_id not in FABRICS:
            raise HTTPException(404, "Unknown fabric plan")
        suffix = {"plan": "massing", "axon": "axon", "landuse": "landuse"}[kind]
        if kind == 'plan' and root.resolve() in (ARTIFACT_ROOT.resolve(), SOURCE_PAIRS['net2-r3'][0].resolve()):
            # Render the actual selected network generation.
            suffix = 'net2-network'
        elif kind == 'plan' and root.resolve() == SOURCE_PAIRS['net1'][0].resolve():
            suffix = 'net1-network'
        path = root / f"{fabric_id}-{suffix}-zh.png"
        if not path.is_file():
            raise HTTPException(404, "Figure unavailable")
        return FileResponse(path, media_type="image/png", filename=path.name)

    return router
