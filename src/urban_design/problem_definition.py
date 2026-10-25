"""Spatial problem definition (Understand -> Define) for Rotterdam M4H.

This module converts observed site and context conditions into computable spatial
problem metrics, GeoJSON problem layers, plain-language statements, and
morphology dictionary recommendations.

Core principles:
- LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.
- Pure deterministic calculations using Shapely and standard library.
- Metrics are bound to verified evidence from Week 5 site analysis.
- Unobserved values remain explicitly UNKNOWN / Unavailable.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    mapping,
    shape,
)
from shapely.ops import polygonize, unary_union

from .morphology_dictionary import load_dictionary


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class MetricItem:
    key: str
    label_zh: str
    value: float | int | str | None
    unit: str
    comparison_value: float | int | str | None = None
    comparison_label_zh: str | None = None
    evidence_level: str = "COMPUTED_RESULT"
    evidence_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


@dataclass
class MorphologyRecommendation:
    entry_id: str
    name_zh: str
    level: str
    rationale_zh: str


@dataclass
class ProblemStatement:
    problem_id: str
    title_zh: str
    category: str
    is_designer_baseline: bool
    status: str  # "CONFIRMED_BASELINE" or "PENDING_DESIGNER_CONFIRMATION"
    location_zh: str
    severity_zh: str
    severity_code: str
    severity_rule_id: str
    severity_basis_zh: str
    evidence_summary_zh: str
    uncertainties_zh: list[str]
    jack_portfolio_response_zh: str
    recommended_morphology: list[MorphologyRecommendation]
    metrics: list[MetricItem]
    evidence_ids: list[str]
    limitations: list[str]


@dataclass
class SpatialProblemResult:
    problem_id: str
    title_zh: str
    summary_zh: str
    statement: ProblemStatement
    geojson_layer: dict[str, Any]
    metrics: dict[str, Any]


@dataclass
class ProblemDefinitionBundle:
    timestamp: str
    study_area_id: str
    study_area_area_m2: float
    land_area_m2: float
    water_area_m2: float
    problems: list[SpatialProblemResult]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "study_area_id": self.study_area_id,
            "study_area_area_m2": self.study_area_area_m2,
            "land_area_m2": self.land_area_m2,
            "water_area_m2": self.water_area_m2,
            "problem_count": len(self.problems),
            "problems": [
                {
                    "problem_id": p.problem_id,
                    "title_zh": p.title_zh,
                    "status": p.statement.status,
                    "is_designer_baseline": p.statement.is_designer_baseline,
                    "severity_zh": p.statement.severity_zh,
                    "severity_code": p.statement.severity_code,
                    "severity_rule_id": p.statement.severity_rule_id,
                    "severity_basis_zh": p.statement.severity_basis_zh,
                    "summary_zh": p.summary_zh,
                    "metrics": [asdict(m) for m in p.statement.metrics],
                    "recommended_morphology": [asdict(r) for r in p.statement.recommended_morphology],
                    "evidence_ids": p.statement.evidence_ids,
                    "limitations": p.statement.limitations,
                }
                for p in self.problems
            ],
            "metadata": self.metadata,
        }

    def to_statements_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "study_area_id": self.study_area_id,
            "statements": [asdict(p.statement) for p in self.problems],
        }


# ---------------------------------------------------------------------------
# Helper Mathematical Functions
# ---------------------------------------------------------------------------

SEVERITY_RULES_VERSION = "s2-review-bands-v1"
SEVERITY_BANDS = {
    "relative_coverage_v1": ((0.25, "CRITICAL"), (0.50, "HIGH"), (0.75, "MODERATE"), (None, "LOW")),
    "detour_vs_direct_v1": ((1.0, "LOW"), (1.25, "MODERATE"), (1.50, "HIGH"), (None, "CRITICAL")),
    "measured_share_v1": ((10.0, "CRITICAL"), (25.0, "HIGH"), (50.0, "MODERATE"), (None, "LOW")),
}
SEVERITY_LABELS_ZH = {
    "CRITICAL": "極高（S2 規則分級）",
    "HIGH": "高（S2 規則分級）",
    "MODERATE": "中（S2 規則分級）",
    "LOW": "低（S2 規則分級）",
    "UNRATED": "未分級（比較基準或指標語意不足）",
}


@dataclass(frozen=True)
class SeverityAssessment:
    code: str
    label_zh: str
    rule_id: str
    basis_zh: str
    observed: float | None = None
    reference: float | None = None
    ratio: float | None = None


def classify_review_severity(
    rule_id: str,
    observed: float | None = None,
    reference: float | None = None,
) -> SeverityAssessment:
    """Apply versioned review bands; these are triage labels, not planning standards."""
    if observed is not None and not math.isfinite(float(observed)):
        observed = None
    if reference is not None and not math.isfinite(float(reference)):
        reference = None

    ratio: float | None = None
    code = "UNRATED"
    if rule_id == "relative_coverage_v1" and observed is not None and reference is not None and reference > 0:
        ratio = float(observed) / float(reference)
        code = next(level for upper, level in SEVERITY_BANDS[rule_id] if upper is None or ratio <= upper)
        basis = f"觀測值／同資料外環參考值 = {ratio:.4f}；依 coverage 比例帶分級。"
    elif rule_id == "detour_vs_direct_v1" and observed is not None and reference is not None and reference > 0:
        ratio = float(observed) / float(reference)
        code = next(level for upper, level in SEVERITY_BANDS[rule_id] if upper is None or ratio <= upper)
        basis = f"繞行比／直線距離下界 = {ratio:.4f}；依 detour 比例帶分級。"
    elif rule_id == "measured_share_v1" and observed is not None:
        share = float(observed)
        code = next(level for upper, level in SEVERITY_BANDS[rule_id] if upper is None or share <= upper)
        basis = f"觀測比例 = {share:.2f}%；依 measured-share 審查帶分級，不表示規劃合規或設計品質。"
    else:
        basis = "缺少可比參考值，或幾何殘差不能直接代表不利程度；不產生嚴重度結論。"

    return SeverityAssessment(
        code=code,
        label_zh=SEVERITY_LABELS_ZH[code],
        rule_id=rule_id,
        basis_zh=basis,
        observed=float(observed) if observed is not None else None,
        reference=float(reference) if reference is not None else None,
        ratio=round(ratio, 6) if ratio is not None else None,
    )

def calculate_shannon_entropy(categories: Sequence[str], exclude_unknown: bool = True) -> float:
    """Calculate Shannon entropy H = -sum(p * ln(p)) over category occurrences."""
    items = [c for c in categories if not (exclude_unknown and c in {"UNKNOWN", "onbekend", ""})]
    if not items:
        return 0.0
    counts = Counter(items)
    total = len(items)
    entropy = -sum((cnt / total) * math.log(cnt / total) for cnt in counts.values())
    return round(entropy, 4)


def _safe_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Problem 1: BAG use labels and registration status
# ---------------------------------------------------------------------------

def compute_functional_monoculture(
    study_area_geom: Polygon | MultiPolygon,
    bag_features: Sequence[Mapping[str, Any]],
    context_bag_features: Sequence[Mapping[str, Any]] | None = None,
    buffer_m: float = 800.0,
) -> SpatialProblemResult:
    """Compute functional monoculture metrics and hotspot GeoJSON layer."""
    site_usages: list[str] = []
    site_buildings_info: list[dict[str, Any]] = []

    unknown_count = 0
    demolished_count = 0

    for feat in bag_features:
        geom_raw = feat.get("geometry")
        if not geom_raw:
            continue
        g = shape(geom_raw)
        if g.intersects(study_area_geom):
            cl = g.intersection(study_area_geom)
            if cl.area < 1e-2:
                continue
            props = feat.get("properties", {})
            raw_usage = props.get("gebruiksdoel")
            status = props.get("status")

            feat_usages: list[str] = []
            if raw_usage:
                for part in str(raw_usage).split(","):
                    p_clean = part.strip()
                    if p_clean:
                        feat_usages.append(p_clean)
                        site_usages.append(p_clean)
            else:
                site_usages.append("UNKNOWN")
                unknown_count += 1
            if status == "Pand gesloopt":
                demolished_count += 1

            site_buildings_info.append({
                "geometry": cl,
                "pand_id": props.get("identificatie", "unknown"),
                "status": status,
                "gebruiksdoel": raw_usage or "UNKNOWN",
                "usages": feat_usages or ["UNKNOWN"],
                "area_m2": round(cl.area, 2),
                "is_demolished": status == "Pand gesloopt",
                "has_unknown_usage": not bool(raw_usage),
            })

    site_entropy = calculate_shannon_entropy(site_usages, exclude_unknown=True)
    site_counts = Counter([u for u in site_usages if u != "UNKNOWN"])
    total_known_tags = sum(site_counts.values())

    site_res_share = round((site_counts.get("woonfunctie", 0) / total_known_tags * 100), 2) if total_known_tags else 0.0
    site_ind_share = round((site_counts.get("industriefunctie", 0) / total_known_tags * 100), 2) if total_known_tags else 0.0
    site_office_share = round((site_counts.get("kantoorfunctie", 0) / total_known_tags * 100), 2) if total_known_tags else 0.0

    # Compare with the 0-800 m StudyArea exterior ring, not a buffer that includes the site.
    ctx_usages: list[str] = []
    ctx_feature_count = 0
    if context_bag_features:
        context_ring = study_area_geom.buffer(buffer_m).difference(study_area_geom)
        for feat in context_bag_features:
            geom_raw = feat.get("geometry")
            if not geom_raw:
                continue
            g = shape(geom_raw)
            if g.intersection(context_ring).area > 1e-2:
                ctx_feature_count += 1
                props = feat.get("properties", {})
                raw_u = props.get("gebruiksdoel")
                if raw_u:
                    for part in str(raw_u).split(","):
                        p_clean = part.strip()
                        if p_clean:
                            ctx_usages.append(p_clean)
                else:
                    ctx_usages.append("UNKNOWN")

    ctx_entropy = calculate_shannon_entropy(ctx_usages, exclude_unknown=True) if ctx_usages else None
    ctx_counts = Counter([u for u in ctx_usages if u != "UNKNOWN"])
    total_ctx_known = sum(ctx_counts.values())
    ctx_res_share = round((ctx_counts.get("woonfunctie", 0) / total_ctx_known * 100), 2) if total_ctx_known else None
    ctx_ind_share = round((ctx_counts.get("industriefunctie", 0) / total_ctx_known * 100), 2) if total_ctx_known else None
    unknown_or_demolished_count = sum(
        item["has_unknown_usage"] or item["is_demolished"]
        for item in site_buildings_info
    )
    severity = classify_review_severity("relative_coverage_v1", site_res_share, ctx_res_share)

    # GeoJSON FeatureCollection
    features = []
    for b in site_buildings_info:
        main_type = "UNKNOWN"
        if b["is_demolished"]:
            main_type = "demolished"
        elif "industriefunctie" in b["usages"]:
            main_type = "industrial"
        elif "kantoorfunctie" in b["usages"]:
            main_type = "office"
        elif "winkelfunctie" in b["usages"]:
            main_type = "retail"
        elif "bijeenkomstfunctie" in b["usages"]:
            main_type = "amenity"
        elif b["usages"] != ["UNKNOWN"]:
            main_type = b["usages"][0]

        features.append({
            "type": "Feature",
            "geometry": mapping(b["geometry"]),
            "properties": {
                "pand_id": b["pand_id"],
                "functional_category": main_type,
                "gebruiksdoel": b["gebruiksdoel"],
                "area_m2": b["area_m2"],
                "status": b["status"],
            },
        })

    geojson_layer = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
        "features": features,
    }

    metrics = [
        MetricItem(
            key="shannon_entropy_site",
            label_zh="基地建築用途 Shannon 多樣性指數",
            value=site_entropy,
            unit="index",
            comparison_value=ctx_entropy,
            comparison_label_zh="StudyArea 外側 0–800m BAG 用途標籤 Shannon 指數",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-002", "claim-w5-site-007"],
            limitations=["僅依據 BAG 用途標籤；不推論實際營運或拆除後的現地狀態"],
        ),
        MetricItem(
            key="residential_share_site",
            label_zh="基地住宅功能佔比（woonfunctie）",
            value=site_res_share,
            unit="%",
            comparison_value=ctx_res_share,
            comparison_label_zh="StudyArea 外側 0–800m BAG 住宅用途標籤佔比",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-007"],
            limitations=["計數 BAG woonfunctie 用途標籤；不推論實際居住、合法性或非正式使用"],
        ),
        MetricItem(
            key="industrial_share_site",
            label_zh="基地 BAG industriefunctie 用途標籤佔比",
            value=site_ind_share,
            unit="%",
            comparison_value=ctx_ind_share,
            comparison_label_zh="StudyArea 外側 0–800m BAG 工業用途標籤佔比",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-007"],
            limitations=["計數 BAG industriefunctie 標籤；不代表實際營運活動"],
        ),
        MetricItem(
            key="unknown_usage_building_count",
            label_zh="用途標籤缺漏的 BAG 建築圖徵數",
            value=unknown_count,
            unit="features",
            comparison_value=len(site_buildings_info),
            comparison_label_zh="StudyArea 相交 BAG 建築圖徵數",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-007"],
            limitations=["只計用途欄位缺漏；不含已拆除狀態計數"],
        ),
        MetricItem(
            key="demolished_building_count",
            label_zh="BAG 狀態標示為 Pand gesloopt 的圖徵數",
            value=demolished_count,
            unit="features",
            comparison_value=len(site_buildings_info),
            comparison_label_zh="StudyArea 相交 BAG 建築圖徵數",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-005"],
            limitations=["BAG 狀態欄位不證明現地仍有或不存在實體量體"],
        ),
        MetricItem(
            key="unknown_or_demolished_building_count",
            label_zh="用途標籤缺漏或 BAG 狀態標示拆除的圖徵聯集數",
            value=unknown_or_demolished_count,
            unit="features",
            comparison_value=len(site_buildings_info),
            comparison_label_zh="StudyArea 相交 BAG 建築圖徵數",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-005", "claim-w5-site-007"],
            limitations=["符合兩條件的圖徵只計一次；聯集數不解讀為停滯率"],
        ),
        MetricItem(
            key="site_building_feature_count",
            label_zh="StudyArea 相交 BAG 建築圖徵數",
            value=len(site_buildings_info),
            unit="features",
            limitations=["按正面積相交判定；不是已確認現存建築數"],
        ),
        MetricItem(
            key="site_known_usage_tag_count",
            label_zh="StudyArea BAG 已知用途標籤總數（百分比共同分母）",
            value=total_known_tags,
            unit="usage tags",
            limitations=["多用途建築可能計入多個標籤；缺漏用途不進入已知標籤分母"],
        ),
        MetricItem(
            key="site_residential_usage_tag_count",
            label_zh="StudyArea woonfunctie 標籤數（住宅比例分子）",
            value=site_counts.get("woonfunctie", 0),
            unit="usage tags",
            limitations=["登記用途標籤不證明實際居住"],
        ),
        MetricItem(
            key="site_industrial_usage_tag_count",
            label_zh="StudyArea industriefunctie 標籤數（工業比例分子）",
            value=site_counts.get("industriefunctie", 0),
            unit="usage tags",
            limitations=["登記用途標籤不證明實際營運"],
        ),
        MetricItem(
            key="context_ring_building_feature_count",
            label_zh="StudyArea 外側 0–800m 環內相交 BAG 建築圖徵數",
            value=ctx_feature_count,
            unit="features",
            limitations=["外環為 StudyArea buffer(800m) 減去 StudyArea 的平面幾何環；非步行服務區"],
        ),
        MetricItem(
            key="context_ring_known_usage_tag_count",
            label_zh="外側 0–800m 環內 BAG 已知用途標籤總數（百分比共同分母）",
            value=total_ctx_known,
            unit="usage tags",
            limitations=["排除用途缺漏；多用途建築會貢獻多個標籤"],
        ),
        MetricItem(
            key="context_ring_residential_usage_tag_count",
            label_zh="外側 0–800m 環內 woonfunctie 標籤數",
            value=ctx_counts.get("woonfunctie", 0),
            unit="usage tags",
            limitations=["登記用途標籤不證明實際居住"],
        ),
        MetricItem(
            key="context_ring_industrial_usage_tag_count",
            label_zh="外側 0–800m 環內 industriefunctie 標籤數",
            value=ctx_counts.get("industriefunctie", 0),
            unit="usage tags",
            limitations=["登記用途標籤不證明實際營運"],
        ),
    ]

    recs = [
        MorphologyRecommendation(
            entry_id="block.hybrid",
            name_zh="混合街廓 (Block Hybrid)",
            level="block_assembly",
            rationale_zh="作為居住、生產與公共底層複合配置的候選；政策條件、現況使用與適宜性須另行評估。",
        ),
        MorphologyRecommendation(
            entry_id="building.courtyard_open_corner",
            name_zh="開角合院建築 (Building Courtyard Open Corner)",
            level="building_plan",
            rationale_zh="作為街道與街廓內公共空間連接的形態候選；可達性和使用情況須由後續資料驗證。",
        ),
        MorphologyRecommendation(
            entry_id="building.podium_tower",
            name_zh="裙樓塔樓 (Building Podium Tower)",
            level="building_plan",
            rationale_zh="作為混合住宅與工作空間的形態候選；既有建築條件、法規與需求未由本次資料驗證。",
        ),
        MorphologyRecommendation(
            entry_id="space.plaza",
            name_zh="市民廣場 (Space Plaza)",
            level="street_open_space",
            rationale_zh="作為公共開放空間的形態候選；土地使用、通行權與現場活動未由本次資料驗證。",
        ),
    ]

    statement = ProblemStatement(
        problem_id="prob-01-functional-monoculture",
        title_zh="BAG 建築用途標籤與登記狀態（BAG Use Labels & Registration Status）",
        category="function_and_land_use",
        is_designer_baseline=True,
        status="CONFIRMED_BASELINE",
        location_zh="StudyArea 內與 PDOK BAG 建築圖徵相交的範圍",
        severity_zh=severity.label_zh,
        severity_code=severity.code,
        severity_rule_id=severity.rule_id,
        severity_basis_zh=severity.basis_zh,
        evidence_summary_zh="以 PDOK BAG 建築用途與狀態欄位計算；800m 對照只取 StudyArea 外環，不代表實際活動。",
        uncertainties_zh=[
            "BAG 登記用途不一定等於現況使用",
            "用途缺漏與 Pand gesloopt 是不同狀態，且部分圖徵同時符合兩者",
        ],
        jack_portfolio_response_zh="原作品集回應未由本次地理資料驗證；形態字典條目只列為待評估設計方向。",
        recommended_morphology=recs,
        metrics=metrics,
        evidence_ids=["claim-w5-site-002", "claim-w5-site-005", "claim-w5-site-007"],
        limitations=[
            "BAG 屬性不等於即時租約或合法營運實況",
            "Shannon 指數排除缺漏用途標籤；周邊比較使用同一 BAG 輸入的 StudyArea 外側 0–800m 幾何環",
        ],
    )

    return SpatialProblemResult(
        problem_id="prob-01-functional-monoculture",
        title_zh="BAG 建築用途標籤與登記狀態",
        summary_zh=f"BAG 用途標籤住宅佔比 {site_res_share:.2f}%，工業用途標籤佔比 {site_ind_share:.2f}%；用途缺漏 {unknown_count} 個，拆除狀態 {demolished_count} 個，兩者聯集 {unknown_or_demolished_count} 個。",
        statement=statement,
        geojson_layer=geojson_layer,
        metrics={m.key: m.value for m in metrics},
    )


# ---------------------------------------------------------------------------
# Problem 2: OSM line-vertex and route proxies
# ---------------------------------------------------------------------------

def compute_spatial_fragmentation(
    study_area_geom: Polygon | MultiPolygon,
    water_geom: Polygon | MultiPolygon,
    road_features: Sequence[Mapping[str, Any]],
    building_features: Sequence[Mapping[str, Any]],
) -> SpatialProblemResult:
    """Compute OSM line-vertex, polygonized-area, and sampled-route proxies."""
    land_geom = study_area_geom.difference(water_geom)
    land_area_ha = round(land_geom.area / 10000.0, 2)

    # 1. Road network lines & types
    road_lines: list[LineString] = []
    total_road_length = 0.0
    permeable_length = 0.0
    service_length = 0.0
    permeable_types = {"footway", "path", "pedestrian", "cycleway", "steps", "living_street"}

    for feat in road_features:
        geom_raw = feat.get("geometry")
        if not geom_raw:
            continue
        g = shape(geom_raw)
        if g.intersects(land_geom):
            cl = g.intersection(land_geom)
            if cl.is_empty:
                continue
            parts = [cl] if isinstance(cl, LineString) else (list(cl.geoms) if isinstance(cl, MultiLineString) else [])
            for p in parts:
                road_lines.append(p)
                l = p.length
                total_road_length += l
                hw = feat.get("properties", {}).get("tags", {}).get("highway") or feat.get("properties", {}).get("highway")
                if hw in permeable_types:
                    permeable_length += l
                elif hw == "service":
                    service_length += l

    permeable_ratio = round((permeable_length / total_road_length * 100), 2) if total_road_length else 0.0
    service_ratio = round((service_length / total_road_length * 100), 2) if total_road_length else 0.0

    # 2. OSM line-coordinate vertex degrees; these are not noded junctions or dead ends.
    node_degrees: dict[tuple[float, float], int] = {}
    graph_edges: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = {}

    def add_edge(u: tuple[float, float], v: tuple[float, float], w: float) -> None:
        graph.setdefault(u, []).append((v, w))
        graph.setdefault(v, []).append((u, w))
        graph_edges.append((u, v, w))

    for line in road_lines:
        coords = list(line.coords)
        for i in range(len(coords) - 1):
            p1 = (round(coords[i][0], 1), round(coords[i][1], 1))
            p2 = (round(coords[i + 1][0], 1), round(coords[i + 1][1], 1))
            d = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
            if d > 0.05:
                add_edge(p1, p2, d)
                node_degrees[p1] = node_degrees.get(p1, 0) + 1
                node_degrees[p2] = node_degrees.get(p2, 0) + 1

    degree_ge3_vertices = [pt for pt, deg in node_degrees.items() if deg >= 3]
    degree_one_vertices = [pt for pt, deg in node_degrees.items() if deg == 1]
    road_degree_ge3_vertex_density = round(len(degree_ge3_vertices) / land_area_ha, 2) if land_area_ha else 0.0

    # 3. Street Block Polygonization
    block_lines = list(road_lines)
    if isinstance(land_geom, Polygon):
        block_lines.append(LineString(land_geom.exterior.coords))
        for interior in land_geom.interiors:
            block_lines.append(LineString(interior.coords))
    elif isinstance(land_geom, MultiPolygon):
        for poly in land_geom.geoms:
            block_lines.append(LineString(poly.exterior.coords))
            for interior in poly.interiors:
                block_lines.append(LineString(interior.coords))

    merged_network = unary_union(block_lines)
    raw_blocks = list(polygonize(merged_network))
    valid_blocks = [
        b for b in raw_blocks
        if land_geom.contains(b.representative_point()) and b.area > 50.0
    ]
    large_blocks = [b for b in valid_blocks if b.area > 10000.0]
    block_areas = [b.area for b in valid_blocks]
    block_perimeters = [b.length for b in valid_blocks]
    avg_block_area = round(sum(block_areas) / len(block_areas), 2) if block_areas else 0.0
    avg_block_perimeter = round(sum(block_perimeters) / len(block_perimeters), 2) if block_perimeters else 0.0
    max_block_area = round(max(block_areas), 2) if block_areas else 0.0

    # 4. Long axis of BAG building-footprint polygons (not a measured barrier).
    building_lengths: list[float] = []
    long_axis_buildings = []
    for feat in building_features:
        geom_raw = feat.get("geometry")
        if not geom_raw:
            continue
        g = shape(geom_raw)
        if g.intersects(land_geom):
            cl = g.intersection(land_geom)
            if cl.area < 10.0:
                continue
            mrr = cl.minimum_rotated_rectangle
            coords = list(mrr.exterior.coords)
            edge_lens = [Point(coords[i]).distance(Point(coords[i + 1])) for i in range(len(coords) - 1)]
            max_len = max(edge_lens) if edge_lens else 0.0
            building_lengths.append(max_len)
            if max_len >= 80.0:
                long_axis_buildings.append({
                    "geometry": cl,
                    "length_m": round(max_len, 2),
                    "pand_id": feat.get("properties", {}).get("identificatie", "unknown"),
                })

    max_building_long_axis_m = round(max(building_lengths), 2) if building_lengths else 0.0

    # 5. Grid-sampled Pedestrian Detour Ratio (Circuity)
    # Sampling a 90 m grid on land_geom; route ratios are exploratory proxies.
    minx, miny, maxx, maxy = land_geom.bounds
    grid_pts: list[tuple[float, float]] = []
    step = 90.0
    gx = minx + step / 2
    while gx < maxx:
        gy = miny + step / 2
        while gy < maxy:
            pt = Point(gx, gy)
            if land_geom.contains(pt):
                grid_pts.append((round(gx, 1), round(gy, 1)))
            gy += step
        gx += step

    import heapq

    def dijkstra(start: tuple[float, float], targets: set[tuple[float, float]]) -> dict[tuple[float, float], float]:
        dist = {start: 0.0}
        pq = [(0.0, start)]
        remaining = set(targets)
        res: dict[tuple[float, float], float] = {}
        while pq and remaining:
            d, u = heapq.heappop(pq)
            if u in remaining:
                res[u] = d
                remaining.remove(u)
            if d > dist.get(u, float("inf")):
                continue
            for v, w in graph.get(u, []):
                if d + w < dist.get(v, float("inf")):
                    dist[v] = d + w
                    heapq.heappush(pq, (d + w, v))
        return res

    nodes_list = list(graph.keys())
    def nearest_node(p: tuple[float, float]) -> tuple[tuple[float, float], float]:
        best_n = nodes_list[0]
        best_d = float("inf")
        for n in nodes_list:
            d = math.hypot(p[0] - n[0], p[1] - n[1])
            if d < best_d:
                best_d = d
                best_n = n
        return best_n, best_d

    mapped_grid = []
    if nodes_list:
        for pt in grid_pts:
            nn, d_snap = nearest_node(pt)
            if d_snap < 150.0:
                mapped_grid.append((pt, nn, d_snap))

    detour_ratios: list[float] = []
    for i in range(len(mapped_grid)):
        p1, n1, d1 = mapped_grid[i]
        targets_dict: dict[tuple[float, float], tuple[float, float]] = {}
        for j in range(i + 1, len(mapped_grid)):
            p2, n2, d2 = mapped_grid[j]
            eucl = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
            if 120.0 <= eucl <= 450.0 and n1 != n2:
                targets_dict[n2] = (eucl, d1 + d2)
        if targets_dict:
            short_paths = dijkstra(n1, set(targets_dict.keys()))
            for n2, (eucl, snap_sum) in targets_dict.items():
                if n2 in short_paths:
                    circuity = (short_paths[n2] + snap_sum) / eucl
                    if circuity <= 6.0:
                        detour_ratios.append(circuity)

    mean_detour_ratio = round(sum(detour_ratios) / len(detour_ratios), 2) if detour_ratios else None
    max_detour_ratio = round(max(detour_ratios), 2) if detour_ratios else None

    # GeoJSON FeatureCollection
    features = []
    # 1. Degree-one OSM line-coordinate vertices.
    for pt in degree_one_vertices:
        features.append({
            "type": "Feature",
            "geometry": mapping(Point(pt[0], pt[1])),
            "properties": {
                "feature_type": "osm_line_degree_one_vertex",
                "problem": "osm_line_vertex_degree_one",
                "degree": 1,
            },
        })
    # 2. Long building-footprint axes
    for b in long_axis_buildings:
        features.append({
            "type": "Feature",
            "geometry": mapping(b["geometry"]),
            "properties": {
                "feature_type": "long_building_footprint_axis",
                "pand_id": b["pand_id"],
                "long_axis_m": b["length_m"],
                "problem": "building_footprint_long_axis",
            },
        })
    # 3. Road-line polygonized areas over 1.0 ha.
    for b in large_blocks:
        features.append({
            "type": "Feature",
            "geometry": mapping(b),
            "properties": {
                "feature_type": "polygonized_road_area_over_1ha",
                "area_m2": round(b.area, 2),
                "perimeter_m": round(b.length, 2),
                "problem": "road_lines_polygonized_area_over_1ha",
            },
        })

    geojson_layer = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
        "features": features,
    }

    metrics = [
        MetricItem(
            key="road_degree_ge3_vertex_density",
            label_zh="OSM 道路座標節點度數 >= 3 的密度（未將線段交點重新切分）",
            value=road_degree_ge3_vertex_density,
            unit="nodes/ha",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-008", "claim-w5-site-010"],
            limitations=["依 OSM polyline 座標頂點建圖；不是經驗證的交叉口或可通行路網密度"],
        ),
        MetricItem(
            key="road_degree_ge3_node_count",
            label_zh="OSM polyline 座標節點度數 >= 3 數量",
            value=len(degree_ge3_vertices),
            unit="vertices",
            limitations=["線段內部幾何交點、立體交叉與通行權未建模"],
        ),
        MetricItem(
            key="road_degree_one_vertex_count",
            label_zh="OSM polyline 座標頂點 degree == 1 數量",
            value=len(degree_one_vertices),
            unit="vertices",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-008"],
            limitations=["度數一的 polyline 座標頂點不能單獨證明道路為死巷或現場不可通行"],
        ),
        MetricItem(
            key="walking_detour_ratio",
            label_zh="網格取樣 OSM polyline 路徑繞行比均值（探索性代理值）",
            value=mean_detour_ratio,
            unit="ratio",
            comparison_value=1.0,
            comparison_label_zh="直線距離下界比值；不是步行設計標準",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-008", "claim-w5-site-009"],
            limitations=[f"90m 網格取樣；僅 {len(detour_ratios)} 組可連通樣本，未計門禁、坡度或高差"],
        ),
        MetricItem(
            key="max_walking_detour_ratio",
            label_zh="網格取樣 OSM polyline 路徑繞行比最大值（探索性代理值）",
            value=max_detour_ratio,
            unit="ratio",
            limitations=[f"由相同 {len(detour_ratios)} 組可連通樣本計算；缺少樣本時輸出 null"],
        ),
        MetricItem(
            key="walking_detour_sample_pair_count",
            label_zh="通過篩選並可由 OSM 座標頂點圖連通的取樣點對數",
            value=len(detour_ratios),
            unit="pairs",
            limitations=["依 90m 網格、120–450m 點對距離、150m 吸附上限及 6.0 比值截斷計算"],
        ),
        MetricItem(
            key="max_building_footprint_long_axis_m",
            label_zh="BAG 建築面圖徵最小旋轉矩形長軸最大值",
            value=max_building_long_axis_m,
            unit="m",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-003"],
            limitations=["長軸不等於臨街立面、連續牆體或不可穿越阻隔"],
        ),
        MetricItem(
            key="service_road_ratio",
            label_zh="OSM highway=service 線長佔比",
            value=service_ratio,
            unit="%",
            comparison_value=permeable_ratio,
            comparison_label_zh="OSM footway/path/pedestrian/cycleway/steps/living_street 線長佔比",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-009"],
            limitations=[f"以 StudyArea 陸域裁切線長 {total_road_length:.2f}m 為分母；highway 標籤不證明道路只供車行或貨運"],
        ),
        MetricItem(
            key="total_osm_road_line_length_m",
            label_zh="StudyArea 陸域內裁切 OSM 道路線總長",
            value=round(total_road_length, 2),
            unit="m",
            limitations=["依輸入 OSM 道路線圖徵裁切；不代表道路權限或實際可通行狀況"],
        ),
        MetricItem(
            key="highway_service_line_length_m",
            label_zh="StudyArea 陸域內 highway=service 線長",
            value=round(service_length, 2),
            unit="m",
            limitations=["OSM highway=service 標籤不表示專供貨運或車行"],
        ),
        MetricItem(
            key="selected_path_network_line_length_m",
            label_zh="StudyArea 陸域內所選步行／騎行類 OSM highway 標籤線長",
            value=round(permeable_length, 2),
            unit="m",
            limitations=["統計 footway/path/pedestrian/cycleway/steps/living_street 標籤；不驗證實地通行權"],
        ),
        MetricItem(
            key="long_building_footprint_over_80m_count",
            label_zh="BAG footprint 最小旋轉矩形長軸 ≥80m 圖徵數",
            value=len(long_axis_buildings),
            unit="features",
            limitations=["幾何篩選門檻；不表示連續立面或不可穿越阻隔"],
        ),
        MetricItem(
            key="polygonized_blocks_over_1ha_count",
            label_zh="OSM 道路線多邊形化後面積 >1ha 的多邊形數",
            value=len(large_blocks),
            unit="polygons",
            limitations=["由 OSM 道路線與 StudyArea 邊界多邊形化；不等同經確認的地籍街廓"],
        ),
    ]
    severity = classify_review_severity("detour_vs_direct_v1", mean_detour_ratio, 1.0)

    recs = [
        MorphologyRecommendation(
            entry_id="block.open",
            name_zh="開放街廓 (Block Open)",
            level="block_assembly",
            rationale_zh="作為可供後續比較的開放街廓形態候選；是否提高連通性須以後續路網分析驗證。",
        ),
        MorphologyRecommendation(
            entry_id="space.covered_public_passage",
            name_zh="覆蓋式公共穿廊 (Space Covered Public Passage)",
            level="street_open_space",
            rationale_zh="作為既有建築內部通道的形態候選；本次未驗證特定建築、產權或公共通行權。",
        ),
        MorphologyRecommendation(
            entry_id="space.shared_street",
            name_zh="人車共用街道 (Space Shared Street)",
            level="street_open_space",
            rationale_zh="作為可供後續設計研究的共享街道候選；成本、道路權限與交通適用性未由本次分析驗證。",
        ),
        MorphologyRecommendation(
            entry_id="block.rowhouse_strip",
            name_zh="排屋街帶 (Block Rowhouse Strip)",
            level="block_assembly",
            rationale_zh="作為另一種街廓尺度候選；不表示本次量測已證明需要替換既有建築。",
        ),
    ]

    statement = ProblemStatement(
        problem_id="prob-02-spatial-fragmentation",
        title_zh="OSM 座標頂點、道路線多邊形化與取樣繞行比（OSM Vertex and Route Proxies）",
        category="spatial_configuration",
        is_designer_baseline=True,
        status="CONFIRMED_BASELINE",
        location_zh="StudyArea 陸域內的 BAG 建築面與 OSM 道路線圖徵",
        severity_zh=severity.label_zh,
        severity_code=severity.code,
        severity_rule_id=severity.rule_id,
        severity_basis_zh=severity.basis_zh,
        evidence_summary_zh=f"OSM polyline 座標頂點代理值：度數一 {len(degree_one_vertices)}、度數至少三 {len(degree_ge3_vertices)}；{len(detour_ratios)} 組取樣點對的網絡繞行比均值 {mean_detour_ratio}、最大值 {max_detour_ratio}。",
        uncertainties_zh=[
            "頂點度數圖未對 polyline 內部相交點重新切分；不能視為完整道路拓撲",
            "OSM highway 標籤與幾何不驗證現場門禁、通行權、交通方向、坡度或高差",
        ],
        jack_portfolio_response_zh="原作品集回應未由本次地理資料驗證；形態字典條目只列為待評估設計方向。",
        recommended_morphology=recs,
        metrics=metrics,
        evidence_ids=["claim-w5-site-008", "claim-w5-site-009", "claim-w5-site-010"],
        limitations=[
            "頂點度數依座標四捨五入至 0.1m 統計，忽略線段內部交點與立體交叉",
            "90m 取樣、150m 吸附上限、120–450m 點對距離及 6.0 繞行比截斷均為本版方法參數",
        ],
    )

    return SpatialProblemResult(
        problem_id="prob-02-spatial-fragmentation",
        title_zh="OSM 座標頂點、道路線多邊形化與取樣繞行比",
        summary_zh=f"OSM 座標頂點代理值為度數一 {len(degree_one_vertices)}、度數至少三 {len(degree_ge3_vertices)}；{len(detour_ratios)} 組取樣點對網絡繞行比均值為 {mean_detour_ratio}。建築長軸與道路線圖徵不驗證實際阻隔或公共通行。",
        statement=statement,
        geojson_layer=geojson_layer,
        metrics={m.key: m.value for m in metrics},
    )


# ---------------------------------------------------------------------------
# Problem 3: Boundary intersections and topological integration
# ---------------------------------------------------------------------------

def compute_sociospatial_isolation(
    study_area_geom: Polygon | MultiPolygon,
    road_features: Sequence[Mapping[str, Any]],
    syntax_layer_ped_800: Mapping[str, Any] | None = None,
    boundary_geom: LineString | MultiLineString | None = None,
) -> SpatialProblemResult:
    """Compute socio-spatial isolation: boundary chokepoints and space syntax integration delta."""
    sa_ext = study_area_geom.exterior if isinstance(study_area_geom, Polygon) else boundary_geom
    if sa_ext is None and isinstance(study_area_geom, MultiPolygon):
        sa_ext = unary_union([p.exterior for p in study_area_geom.geoms])

    # 1. Boundary crossing points
    boundary_intersection_points: list[tuple[float, float, str, str]] = []
    for feat in road_features:
        geom_raw = feat.get("geometry")
        if not geom_raw or sa_ext is None:
            continue
        g = shape(geom_raw)
        if g.intersects(sa_ext):
            inter = g.intersection(sa_ext)
            pts = [inter] if isinstance(inter, Point) else (list(inter.geoms) if isinstance(inter, MultiPoint) else [])
            for pt in pts:
                hw = feat.get("properties", {}).get("tags", {}).get("highway") or feat.get("properties", {}).get("highway") or "unclassified"
                name = feat.get("properties", {}).get("tags", {}).get("name") or feat.get("properties", {}).get("name") or "unnamed"
                boundary_intersection_points.append((pt.x, pt.y, hw, name))

    # Cluster within 5m
    distinct_intersection_points: list[tuple[float, float, str, str]] = []
    for x, y, hw, name in boundary_intersection_points:
        if not any(math.hypot(x - dx, y - dy) < 5.0 for dx, dy, _, _ in distinct_intersection_points):
            distinct_intersection_points.append((x, y, hw, name))

    # This y-coordinate is a project-defined northern-boundary selector in EPSG:28992.
    north_intersection_points = [point for point in distinct_intersection_points if point[1] > 436000.0]

    # Recalculate the candidate layer mean from its segment values. The source
    # contains StudyArea segments only, so there is no supported outside delta.
    raw_nain_values = (syntax_layer_ped_800 or {}).get("segment_values", {})
    nain_values = [
        value for raw in raw_nain_values.values()
        if (value := _safe_float(raw)) is not None
    ]
    inside_mean_nain = round(sum(nain_values) / len(nain_values), 4) if nain_values else None
    zero_nain_count = sum(math.isclose(value, 0.0, abs_tol=1e-12) for value in nain_values) if nain_values else None
    severity = classify_review_severity("unrated_no_reference_v1", inside_mean_nain)

    # GeoJSON FeatureCollection
    features = []
    # OSM line / StudyArea boundary geometry intersections.
    for x, y, hw, name in distinct_intersection_points:
        is_north = y > 436000.0
        features.append({
            "type": "Feature",
            "geometry": mapping(Point(x, y)),
            "properties": {
                "boundary_intersection_type": "north_y_threshold_intersection" if is_north else "other_boundary_intersection",
                "road_name": name,
                "highway_type": hw,
                "is_north_of_y_436000m": is_north,
            },
        })

    geojson_layer = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
        "features": features,
    }

    metrics = [
        MetricItem(
            key="north_boundary_osm_intersections_count",
            label_zh="y > 436000m 的北側 StudyArea 邊界 OSM 線幾何交點（5m 聚類）",
            value=len(north_intersection_points),
            unit="points",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-010"],
            limitations=["是 OSM 線與研究邊界的幾何相交，不代表實地可通行或安全穿越"],
        ),
        MetricItem(
            key="all_boundary_osm_intersections_count",
            label_zh="StudyArea 全邊界 OSM 線幾何交點數（5m 聚類）",
            value=len(distinct_intersection_points),
            unit="points",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-010"],
            limitations=["只統計點型交集；重疊線段或幾何不相交的連接不計入"],
        ),
        MetricItem(
            key="syntax_pedestrian_800m_nain_mean",
            label_zh="PST 3.3.1 行人 800m 拓撲整合度 NAIN（StudyArea 候選層均值）",
            value=inside_mean_nain,
            unit="NAIN",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT" if nain_values else "DATA_GAP",
            evidence_ids=["claim-w5-site-018", "claim-w5-site-024"],
            limitations=[
                f"由 {len(nain_values)} 個來源 segment_values 重算；只描述路網拓撲指標，不能推論人流或出行人數",
                "來源標記 boundary stability 未評估，結果為 EXPLORATORY 候選值",
            ],
        ),
        MetricItem(
            key="syntax_zero_nain_segment_count",
            label_zh="PST 候選層 NAIN 等於 0 的 segment 數",
            value=zero_nain_count,
            unit="segments",
            comparison_value=len(nain_values) if nain_values else None,
            comparison_label_zh="具來源 segment_values 的路段數" if nain_values else None,
            evidence_level="COMPUTED_RESULT" if nain_values else "DATA_GAP",
            evidence_ids=["claim-w5-site-018"],
            limitations=["NAIN=0 是候選層的數值分類；不證明路段物理隔離或無法通行"],
        ),
        MetricItem(
            key="syntax_source_segment_count",
            label_zh="候選層具有有效 NAIN 數值的 segment_values 數",
            value=len(nain_values),
            unit="segments",
            limitations=["只計來源 JSON 中能轉成有限數字的 StudyArea segment_values"],
        ),
    ]

    recs = [
        MorphologyRecommendation(
            entry_id="space.linear_park",
            name_zh="線形公園／綠色走廊 (Space Linear Park)",
            level="street_open_space",
            rationale_zh="作為後續可評估的線性空間候選；本次未驗證地形、土地權限或跨界可通行性。",
        ),
        MorphologyRecommendation(
            entry_id="building.terraced",
            name_zh="階梯疊落建築 (Building Terraced)",
            level="building_plan",
            rationale_zh="作為地形與量體設計候選；本次沒有高程資料支持特定高差或坡道方案。",
        ),
        MorphologyRecommendation(
            entry_id="space.shared_street",
            name_zh="人車共用街道 (Space Shared Street)",
            level="street_open_space",
            rationale_zh="作為街道設計候選；是否能改善道路拓撲需以幾何方案及後續分析驗證。",
        ),
    ]

    statement = ProblemStatement(
        problem_id="prob-03-sociospatial-isolation",
        title_zh="邊界道路幾何交點與拓撲整合度（Boundary Intersections & Topological Integration）",
        category="urban_connectivity",
        is_designer_baseline=True,
        status="CONFIRMED_BASELINE",
        location_zh="StudyArea 邊界與 PST 3.3.1 800m 行人模式候選層",
        severity_zh=severity.label_zh,
        severity_code=severity.code,
        severity_rule_id=severity.rule_id,
        severity_basis_zh=severity.basis_zh,
        evidence_summary_zh=f"OSM 線與 StudyArea 邊界點型幾何交點共 {len(distinct_intersection_points)} 個，其中 y > 436000m 選取區有 {len(north_intersection_points)} 個；PST 候選層均值 {inside_mean_nain}。沒有周邊 NAIN 可比值。",
        uncertainties_zh=[
            "道路邊界交點不驗證現場穿越設施、安全或通行權",
            "PST 輸入僅含 StudyArea segment_values，缺少可比的周邊平均值；邊界穩定性亦未評估",
        ],
        jack_portfolio_response_zh="原作品集回應未由本次地理資料驗證；形態字典條目只列為待評估設計方向。",
        recommended_morphology=recs,
        metrics=metrics,
        evidence_ids=["claim-w5-site-010", "claim-w5-site-018", "claim-w5-site-024"],
        limitations=[
            "NAIN 只表示路網拓撲整合指標；不能解讀為人流、出行人數或社會隔離程度",
            "北界選取使用 EPSG:28992 y > 436000m，交點以 5m 距離貪婪聚類；屬本版方法參數",
        ],
    )

    return SpatialProblemResult(
        problem_id="prob-03-sociospatial-isolation",
        title_zh="邊界道路交點與拓撲整合度",
        summary_zh=f"OSM 線與邊界點型幾何交點 {len(distinct_intersection_points)} 個；y > 436000m 選取區有 {len(north_intersection_points)} 個。PST 行人 800m 拓撲整合度候選層均值為 {inside_mean_nain}，缺周邊比較值，不作人流推論。",
        statement=statement,
        geojson_layer=geojson_layer,
        metrics={m.key: m.value for m in metrics},
    )


# ---------------------------------------------------------------------------
# Problem 4: OSM green-tag polygon geometry
# ---------------------------------------------------------------------------

def compute_ecological_disconnection(
    study_area_geom: Polygon | MultiPolygon,
    context_green_features: Sequence[Mapping[str, Any]],
) -> SpatialProblemResult:
    """Compute ecological corridor gaps, green patch isolation, and missing biophilic links."""
    site_greens: list[Polygon] = []
    ext_greens: list[Polygon] = []
    buf_1000 = study_area_geom.buffer(1000.0)

    for feat in context_green_features:
        geom_raw = feat.get("geometry")
        if not geom_raw:
            continue
        g = shape(geom_raw)
        if not g.is_valid:
            g = g.buffer(0)
        if g.intersects(study_area_geom):
            cl = g.intersection(study_area_geom)
            if cl.area > 5.0:
                polys = [cl] if isinstance(cl, Polygon) else (list(cl.geoms) if isinstance(cl, MultiPolygon) else [])
                site_greens.extend(polys)
        elif g.intersects(buf_1000):
            cl_ext = g.difference(study_area_geom)
            if cl_ext.area > 30.0:
                polys = [cl_ext] if isinstance(cl_ext, Polygon) else (list(cl_ext.geoms) if isinstance(cl_ext, MultiPolygon) else [])
                ext_greens.extend(polys)

    site_green_union = unary_union(site_greens) if site_greens else Polygon()
    total_site_green_m2 = round(site_green_union.area, 2)
    study_area_m2 = round(study_area_geom.area, 2)
    green_coverage_pct = round(total_site_green_m2 / study_area_m2 * 100, 2)

    # Count pieces whose nearest other mapped green polygon is more than 40 m away.
    gap_over_40m_fragments = []
    for g in site_greens:
        others = [og for og in site_greens if og != g]
        if others:
            d = min(g.distance(og) for og in others)
            if d > 40.0:
                gap_over_40m_fragments.append(g)

    # GeoJSON FeatureCollection
    features = []
    for g in site_greens:
        features.append({
            "type": "Feature",
            "geometry": mapping(g),
            "properties": {
                "feature_type": "osm_green_tag_polygon_piece",
                "area_m2": round(g.area, 2),
                "nearest_other_mapped_polygon_gap_over_40m": any(g == gap for gap in gap_over_40m_fragments),
            },
        })

    geojson_layer = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
        "features": features,
    }

    metrics = [
        MetricItem(
            key="green_coverage_percentage",
            label_zh="StudyArea 中 OSM 綠地標籤多邊形面積佔比",
            value=green_coverage_pct,
            unit="%",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-017"],
            limitations=["OSM 綠地用途標籤不等於樹冠、可進入公園、生態品質或土地覆蓋分類"],
        ),
        MetricItem(
            key="site_green_area_m2",
            label_zh="StudyArea 內 OSM 綠地標籤多邊形聯集面積",
            value=total_site_green_m2,
            unit="m²",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-017"],
            limitations=["聯集面積只反映輸入多邊形幾何；不代表實際植被面積或狀態"],
        ),
        MetricItem(
            key="green_polygon_nearest_gap_over_40m_count",
            label_zh="最近其他 OSM 綠地多邊形距離 > 40m 的片段數",
            value=len(gap_over_40m_fragments),
            unit="patches",
            comparison_value=len(site_greens),
            comparison_label_zh="面積 > 5m² 且與 StudyArea 相交的綠地多邊形片段數",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-017"],
            limitations=["40m 為本版幾何鄰近判定參數；不作生物棲地或傳粉連通推論"],
        ),
        MetricItem(
            key="site_green_polygon_count",
            label_zh="面積 > 5m² 且與 StudyArea 相交的綠地多邊形片段數",
            value=len(site_greens),
            unit="polygons",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-017"],
            limitations=["MultiPolygon 會拆為多個 Polygon；片段數不等於 OSM 原始 feature 數"],
        ),
    ]
    severity = classify_review_severity("measured_share_v1", green_coverage_pct)

    recs = [
        MorphologyRecommendation(
            entry_id="space.linear_park",
            name_zh="線形生態公園 (Space Linear Park)",
            level="street_open_space",
            rationale_zh="作為線性綠地配置候選；本次資料不驗證連續性、樹冠、風環境或物種遷移。",
        ),
        MorphologyRecommendation(
            entry_id="space.pocket_park",
            name_zh="口袋公園 (Space Pocket Park)",
            level="street_open_space",
            rationale_zh="作為小型開放空間配置候選；適宜位置與生態效益須由後續資料評估。",
        ),
        MorphologyRecommendation(
            entry_id="block.towers_park",
            name_zh="公園塔樓街廓 (Block Towers Park)",
            level="block_assembly",
            rationale_zh="作為建築與開放空間配置候選；建蔽、雨水與可達性效益未由本次分析計算。",
        ),
    ]

    statement = ProblemStatement(
        problem_id="prob-04-ecological-disconnection",
        title_zh="OSM 綠地標籤面積與多邊形間距（Mapped Green Geometry）",
        category="environment_and_landscape",
        is_designer_baseline=True,
        status="CONFIRMED_BASELINE",
        location_zh="StudyArea 與 OSM 綠地標籤多邊形幾何相交的範圍",
        severity_zh=severity.label_zh,
        severity_code=severity.code,
        severity_rule_id=severity.rule_id,
        severity_basis_zh=severity.basis_zh,
        evidence_summary_zh=f"裁切後綠地標籤多邊形聯集 {total_site_green_m2:.2f}m²（{green_coverage_pct:.2f}%）；面積篩選後 {len(site_greens)} 個片段，其中 {len(gap_over_40m_fragments)} 個最近其他片段距離大於 40m。",
        uncertainties_zh=[
            "OSM 綠地標籤不提供地表材料、樹冠或生態狀態",
            "圖徵分類和幾何不能證明公眾可進入或植被實際存在",
        ],
        jack_portfolio_response_zh="原作品集回應未由本次地理資料驗證；形態字典條目只列為待評估設計方向。",
        recommended_morphology=recs,
        metrics=metrics,
        evidence_ids=["claim-w5-site-012", "claim-w5-site-017"],
        limitations=[
            "缺乏地表材質、樹冠、土壤、土地使用權與生態調查資料",
            "本次未計算外部綠地至 StudyArea 的生態廊道連續性",
        ],
    )

    return SpatialProblemResult(
        problem_id="prob-04-ecological-disconnection",
        title_zh="OSM 綠地標籤面積與多邊形間距",
        summary_zh=f"StudyArea 內 OSM 綠地標籤多邊形聯集面積 {total_site_green_m2:.2f}m²，佔 {green_coverage_pct:.2f}%；{len(site_greens)} 個多邊形片段中，{len(gap_over_40m_fragments)} 個與最近其他片段距離大於 40m。",
        statement=statement,
        geojson_layer=geojson_layer,
        metrics={m.key: m.value for m in metrics},
    )


# ---------------------------------------------------------------------------
# Problem 5: Water-land interface and OSM-way proximity
# ---------------------------------------------------------------------------

def compute_waterfront_inaccessibility(
    study_area_geom: Polygon | MultiPolygon,
    water_geom: Polygon | MultiPolygon,
    road_features: Sequence[Mapping[str, Any]],
) -> SpatialProblemResult:
    """Measure water-land interface segments within 22 m of selected OSM ways."""
    # Water-land interface line
    water_boundary = water_geom.boundary
    sa_ext = study_area_geom.exterior if isinstance(study_area_geom, Polygon) else unary_union([p.exterior for p in study_area_geom.geoms])
    quay_interface = water_boundary.intersection(study_area_geom).difference(sa_ext.buffer(0.8))
    total_interface_length_m = round(quay_interface.length, 2)

    # OSM way proximity is a map proxy, not verified public access.
    path_proximity_m = 22.0
    pedestrian_ways_near_quay: list[LineString] = []

    for feat in road_features:
        geom_raw = feat.get("geometry")
        if not geom_raw:
            continue
        g = shape(geom_raw)
        tags = feat.get("properties", {}).get("tags", {}) or feat.get("properties", {})
        hw = tags.get("highway")
        access = tags.get("access")
        if hw not in {"footway", "pedestrian", "path", "cycleway"} or access in {"no", "private"}:
            continue
        if g.distance(quay_interface) <= path_proximity_m:
            parts = [g] if isinstance(g, LineString) else (list(g.geoms) if isinstance(g, MultiLineString) else [])
            pedestrian_ways_near_quay.extend(parts)

    near_osm_way_length_m = 0.0
    near_osm_way_geom = None
    no_nearby_way_geom = quay_interface

    if pedestrian_ways_near_quay:
        ped_union = unary_union(pedestrian_ways_near_quay)
        near_osm_way_geom = quay_interface.intersection(ped_union.buffer(path_proximity_m))
        if not near_osm_way_geom.is_empty:
            near_osm_way_length_m = round(near_osm_way_geom.length, 2)
            no_nearby_way_geom = quay_interface.difference(ped_union.buffer(path_proximity_m))

    no_nearby_way_length_m = round(no_nearby_way_geom.length, 2) if no_nearby_way_geom else 0.0
    mapped_path_proximity_pct = round(near_osm_way_length_m / total_interface_length_m * 100, 2) if total_interface_length_m else 0.0
    severity = classify_review_severity("measured_share_v1", mapped_path_proximity_pct)

    # GeoJSON FeatureCollection
    features = []
    if near_osm_way_geom and not near_osm_way_geom.is_empty:
        features.append({
            "type": "Feature",
            "geometry": mapping(near_osm_way_geom),
            "properties": {
                "quay_status": "NEAR_SELECTED_OSM_WAY",
                "length_m": near_osm_way_length_m,
                "description_zh": "距符合 highway 標籤且未明確標示 no/private 的 OSM way 不超過 22m",
            },
        })
    if no_nearby_way_geom and not no_nearby_way_geom.is_empty:
        features.append({
            "type": "Feature",
            "geometry": mapping(no_nearby_way_geom),
            "properties": {
                "quay_status": "NO_SELECTED_OSM_WAY_WITHIN_22M",
                "length_m": no_nearby_way_length_m,
                "description_zh": "22m 內沒有符合本次 OSM highway/access 標籤篩選的路線圖徵",
            },
        })

    geojson_layer = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
        "features": features,
    }

    metrics = [
        MetricItem(
            key="osmped_way_quay_proximity_pct",
            label_zh="22m 內有符合標籤 OSM footway/pedestrian/path/cycleway 圖徵的界面比例",
            value=mapped_path_proximity_pct,
            unit="%",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-014", "claim-w5-site-015"],
            limitations=["只反映 OSM way 距離與標籤；不證明公眾可達、法律開放或現地安全"],
        ),
        MetricItem(
            key="water_land_interface_length_m",
            label_zh="BGT 水體幾何與 StudyArea 內部交界長度",
            value=total_interface_length_m,
            unit="m",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-015"],
            limitations=["幾何交界不一定等於護岸、碼頭牆或可到達岸線"],
        ),
        MetricItem(
            key="quay_near_osm_pedestrian_way_m",
            label_zh="距符合標籤 OSM way 不超過 22m 的幾何界面長度",
            value=near_osm_way_length_m,
            unit="m",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-015"],
            limitations=["此為幾何鄰近指標；OSM 未標示的通路不計入，亦不能判定實地開放狀態"],
        ),
        MetricItem(
            key="quay_without_nearby_osm_pedestrian_way_m",
            label_zh="22m 內無符合篩選 OSM way 的幾何界面長度",
            value=no_nearby_way_length_m,
            unit="m",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-015"],
            limitations=["不等於封閉、私有或不可親水；只表示本次輸入沒有符合條件的 OSM way"],
        ),
    ]

    recs = [
        MorphologyRecommendation(
            entry_id="space.waterfront_promenade",
            name_zh="水岸散步道 (Space Waterfront Promenade)",
            level="street_open_space",
            rationale_zh="作為岸線步行空間候選；實際連續性、公共通行權與港務安全須另行驗證。",
        ),
        MorphologyRecommendation(
            entry_id="space.plaza",
            name_zh="水岸端景廣場 (Space Plaza)",
            level="street_open_space",
            rationale_zh="作為水岸公共空間候選；位置、視線、水上交通及親水安全未由本次分析驗證。",
        ),
        MorphologyRecommendation(
            entry_id="block.open",
            name_zh="面水開放街廓 (Block Open)",
            level="block_assembly",
            rationale_zh="作為面水街廓候選；風環境、視線與行人可達性需後續計算。",
        ),
    ]

    statement = ProblemStatement(
        problem_id="prob-05-waterfront-inaccessibility",
        title_zh="水陸幾何界面與 OSM 選定標籤路線鄰近度（Mapped Waterfront Geometry）",
        category="water_and_public_realm",
        is_designer_baseline=True,
        status="CONFIRMED_BASELINE",
        location_zh="BGT 水體多邊形與 StudyArea 內部的幾何交界",
        severity_zh=severity.label_zh,
        severity_code=severity.code,
        severity_rule_id=severity.rule_id,
        severity_basis_zh=severity.basis_zh,
        evidence_summary_zh=f"水陸幾何界面 {total_interface_length_m:.2f}m；其中 {near_osm_way_length_m:.2f}m（{mapped_path_proximity_pct:.2f}%）距本次篩選的 OSM way 不超過 22m。",
        uncertainties_zh=[
            "BGT 水體邊界不等於可接觸護岸或港池設施邊界",
            "OSM way 的 access 缺漏不等於公眾通行許可；現場安全、門禁、租約及水質未核實",
        ],
        jack_portfolio_response_zh="原作品集回應未由本次地理資料驗證；形態字典條目只列為待評估設計方向。",
        recommended_morphology=recs,
        metrics=metrics,
        evidence_ids=["claim-w5-site-014", "claim-w5-site-015"],
        limitations=[
            "幾何鄰近指標不能推論水岸被封閉、物流使用或資源浪費",
            "OSM tag 篩選範圍為 footway/pedestrian/path/cycleway，明確 access=no/private 者排除；未知 access 仍納入候選",
        ],
    )

    return SpatialProblemResult(
        problem_id="prob-05-waterfront-inaccessibility",
        title_zh="水陸幾何界面與 OSM 選定標籤路線鄰近度",
        summary_zh=f"StudyArea 內水陸幾何界面 {total_interface_length_m:.2f}m；{near_osm_way_length_m:.2f}m（{mapped_path_proximity_pct:.2f}%）距符合標籤的 OSM way 不超過 22m。此值不等於公眾可達比例。",
        statement=statement,
        geojson_layer=geojson_layer,
        metrics={m.key: m.value for m in metrics},
    )


# ---------------------------------------------------------------------------
# Problem 6 (AI-discovered): Massive Unclassified Ground Residual
# ---------------------------------------------------------------------------

def compute_unclassified_residual_ground(
    study_area_geom: Polygon | MultiPolygon,
    water_geom: Polygon | MultiPolygon,
    building_features: Sequence[Mapping[str, Any]],
    road_features: Sequence[Mapping[str, Any]],
) -> SpatialProblemResult:
    """Compute the geometric remainder after subtracting water and BAG footprints."""
    study_area_area_m2 = round(study_area_geom.area, 2)

    # Building footprints union
    clipped_buildings = []
    for feat in building_features:
        geom_raw = feat.get("geometry")
        if not geom_raw:
            continue
        g = shape(geom_raw)
        if g.intersects(study_area_geom):
            cl = g.intersection(study_area_geom)
            if cl.area > 1e-2:
                clipped_buildings.append(cl)

    building_union = unary_union(clipped_buildings) if clipped_buildings else Polygon()
    building_area_m2 = round(building_union.area, 2)
    water_area_m2 = round(water_geom.area, 2)

    # This is a geometric difference only; it does not classify ground cover or use.
    occupied = unary_union([water_geom, building_union])
    residual_geom = study_area_geom.difference(occupied)
    residual_area_m2 = round(residual_geom.area, 2)
    residual_ratio_pct = round(residual_area_m2 / study_area_area_m2 * 100, 2)

    # Extract residual polygons above the versioned 5,000 m2 display threshold.
    raw_res_polys = [residual_geom] if isinstance(residual_geom, Polygon) else (list(residual_geom.geoms) if isinstance(residual_geom, MultiPolygon) else [])
    large_residual_patches = [p for p in raw_res_polys if p.area > 5000.0]
    severity = classify_review_severity("unrated_nonsemantic_geometry_v1")

    # GeoJSON FeatureCollection
    features = []
    for idx, p in enumerate(large_residual_patches):
        features.append({
            "type": "Feature",
            "geometry": mapping(p),
            "properties": {
                "residual_id": f"residual-patch-{idx+1:02d}",
                "area_m2": round(p.area, 2),
                "area_ha": round(p.area / 10000.0, 2),
                "feature_type": "nonbuilding_nonwater_residual_polygon",
            },
        })

    geojson_layer = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
        "features": features,
    }

    metrics = [
        MetricItem(
            key="nonbuilding_nonwater_residual_area_m2",
            label_zh="StudyArea 減去 BGT 水體與 BAG 建築面聯集後的幾何面積",
            value=residual_area_m2,
            unit="m²",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-016"],
            limitations=["是幾何差額，不是地表材質、空置、開發適宜性或公共性分類"],
        ),
        MetricItem(
            key="nonbuilding_nonwater_residual_ratio_pct",
            label_zh="幾何差額面積佔 StudyArea 面積比例",
            value=residual_ratio_pct,
            unit="%",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-004", "claim-w5-site-016"],
            limitations=["幾何比例不等於未使用土地比例或應改善比例"],
        ),
        MetricItem(
            key="residual_polygons_over_5000m2_count",
            label_zh="面積 > 5,000m² 的幾何差額多邊形數",
            value=len(large_residual_patches),
            unit="patches",
            comparison_value=None,
            comparison_label_zh=None,
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-016"],
            limitations=["5,000m² 為輸出篩選門檻，不表示土地價值或問題程度"],
        ),
        MetricItem(
            key="building_footprint_union_area_m2",
            label_zh="StudyArea 內 BAG 建築面聯集面積",
            value=building_area_m2,
            unit="m²",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-004"],
            limitations=["BAG footprint 幾何不能證明建築狀況、高度或用途"],
        ),
        MetricItem(
            key="residual_polygon_count",
            label_zh="幾何差額 Polygon 片段數",
            value=len(raw_res_polys),
            unit="polygons",
            evidence_level="COMPUTED_RESULT",
            evidence_ids=["claim-w5-site-016"],
            limitations=["MultiPolygon 片段依 Shapely geometry 結果計數"],
        ),
    ]

    recs = [
        MorphologyRecommendation(
            entry_id="block.industrial_campus",
            name_zh="產業園區街廓 (Block Industrial Campus)",
            level="block_assembly",
            rationale_zh="作為可能的產業街廓配置候選；本次幾何差額沒有判定土地使用或裝卸活動。",
        ),
        MorphologyRecommendation(
            entry_id="space.plaza",
            name_zh="多功能市民廣場 (Space Plaza)",
            level="street_open_space",
            rationale_zh="作為廣場配置候選；地表材料、公共可達性、遮蔭與現況活動未由本次資料確認。",
        ),
        MorphologyRecommendation(
            entry_id="space.shared_street",
            name_zh="共享生活街道 (Space Shared Street)",
            level="street_open_space",
            rationale_zh="作為道路與街廓配置候選；本次幾何差額不證明新增道路的必要性或可行性。",
        ),
    ]

    statement = ProblemStatement(
        problem_id="prob-06-unclassified-residual-ground",
        title_zh="[AI候選·待設計者確認] 非建築／非水體幾何差額（Geometric Remainder）",
        category="spatial_configuration_and_ground",
        is_designer_baseline=False,
        status="PENDING_DESIGNER_CONFIRMATION",
        location_zh="StudyArea 減去輸入 BGT 水體與 BAG 建築面聯集後的幾何範圍",
        severity_zh=severity.label_zh,
        severity_code=severity.code,
        severity_rule_id=severity.rule_id,
        severity_basis_zh=severity.basis_zh,
        evidence_summary_zh=f"幾何差額 {residual_area_m2:.2f}m²（StudyArea 的 {residual_ratio_pct:.2f}%）；BAG 建築面聯集 {building_area_m2:.2f}m²；{len(large_residual_patches)} 個 Polygon 大於 5,000m²。",
        uncertainties_zh=[
            "差額可能包含道路、廣場、庭院、作業空間、綠地及其他未輸入圖層；本次未分類地表材質或現況使用",
            "沒有土地所有權、租約、地籍、土壤污染或可開發性資料",
        ],
        jack_portfolio_response_zh="此幾何觀察仍待設計者確認；不建立 HumanDecision，也不把差額視為設計目標。",
        recommended_morphology=recs,
        metrics=metrics,
        evidence_ids=["claim-w5-site-004", "claim-w5-site-016"],
        limitations=[
            "幾何差額本身不證明存在獨立的空間問題，嚴重度未分級",
            "若要推論地面材質、使用或開發限制，需取得相應來源資料並另行審查",
        ],
    )

    return SpatialProblemResult(
        problem_id="prob-06-unclassified-residual-ground",
        title_zh="[AI候選·待確認] 非建築／非水體幾何差額",
        summary_zh=f"StudyArea 扣除 BAG 建築面與 BGT 水體後的幾何差額為 {residual_area_m2:.2f}m²（{residual_ratio_pct:.2f}%）；此結果不分類地面材質、空置或用途。",
        statement=statement,
        geojson_layer=geojson_layer,
        metrics={m.key: m.value for m in metrics},
    )


# ---------------------------------------------------------------------------
# High-Level Analysis Orchestrator
# ---------------------------------------------------------------------------

def run_problem_definition_analysis(
    study_area_geom: Polygon | MultiPolygon,
    bag_features: Sequence[Mapping[str, Any]],
    water_features: Sequence[Mapping[str, Any]],
    road_features: Sequence[Mapping[str, Any]],
    context_green_features: Sequence[Mapping[str, Any]],
    context_bag_features: Sequence[Mapping[str, Any]] | None = None,
    syntax_candidate_layer0: Mapping[str, Any] | None = None,
    study_area_id: str = "study-area-rotterdam-m4h-pilot-project-v5",
) -> ProblemDefinitionBundle:
    """Run full deterministic spatial problem analysis for Rotterdam M4H."""
    # Water union
    clipped_water = []
    for feat in water_features:
        geom_raw = feat.get("geometry")
        if not geom_raw:
            continue
        g = shape(geom_raw)
        if g.intersects(study_area_geom):
            cl = g.intersection(study_area_geom)
            if cl.area > 1e-2:
                clipped_water.append(cl)
    water_geom = unary_union(clipped_water) if clipped_water else Polygon()
    land_geom = study_area_geom.difference(water_geom)

    # 1. Functional Monoculture
    res1 = compute_functional_monoculture(
        study_area_geom=study_area_geom,
        bag_features=bag_features,
        context_bag_features=context_bag_features,
    )

    # 2. Spatial Fragmentation
    res2 = compute_spatial_fragmentation(
        study_area_geom=study_area_geom,
        water_geom=water_geom,
        road_features=road_features,
        building_features=bag_features,
    )

    # 3. Socio-Spatial Isolation
    res3 = compute_sociospatial_isolation(
        study_area_geom=study_area_geom,
        road_features=road_features,
        syntax_layer_ped_800=syntax_candidate_layer0,
    )

    # 4. Ecological Disconnection
    res4 = compute_ecological_disconnection(
        study_area_geom=study_area_geom,
        context_green_features=context_green_features,
    )

    # 5. Waterfront Inaccessibility
    res5 = compute_waterfront_inaccessibility(
        study_area_geom=study_area_geom,
        water_geom=water_geom,
        road_features=road_features,
    )

    # 6. Massive Unclassified Ground Residual (AI-discovered)
    res6 = compute_unclassified_residual_ground(
        study_area_geom=study_area_geom,
        water_geom=water_geom,
        building_features=bag_features,
        road_features=road_features,
    )

    # Verify morphology dictionary IDs against catalogue
    dictionary = load_dictionary()
    known_entries = dictionary["entry_by_id"]

    for r in [res1, res2, res3, res4, res5, res6]:
        for rec in r.statement.recommended_morphology:
            if rec.entry_id not in known_entries:
                raise ValueError(f"Unknown morphology dictionary entry recommended: {rec.entry_id}")

    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    return ProblemDefinitionBundle(
        timestamp=now_iso,
        study_area_id=study_area_id,
        study_area_area_m2=round(study_area_geom.area, 2),
        land_area_m2=round(land_geom.area, 2),
        water_area_m2=round(water_geom.area, 2),
        problems=[res1, res2, res3, res4, res5, res6],
        metadata={
            "crs": "EPSG:28992",
            "methodology": "deterministic_spatial_indicators_s2_review_v2",
            "evidence_framework": "PD-06",
            "syntax_engine": "PST_3.3.1_EXPLORATORY",
            "severity_rules_version": SEVERITY_RULES_VERSION,
            "severity_bands": SEVERITY_BANDS,
            "method_parameters": {
                "context_comparison_buffer_m": 800.0,
                "north_boundary_selector_y_m_epsg28992": 436000.0,
                "boundary_crossing_cluster_distance_m": 5.0,
                "green_context_buffer_m": 1000.0,
                "site_green_polygon_min_area_m2": 5.0,
                "context_green_polygon_min_area_m2": 30.0,
                "green_polygon_gap_threshold_m": 40.0,
                "waterfront_osm_way_proximity_m": 22.0,
                "residual_polygon_export_min_area_m2": 5000.0,
                "road_graph_coordinate_precision_m": 0.1,
                "detour_grid_step_m": 90.0,
                "detour_snap_limit_m": 150.0,
                "detour_euclidean_pair_range_m": [120.0, 450.0],
                "detour_ratio_inclusion_max": 6.0,
            },
        },
    )


def export_problem_definition_artifacts(
    bundle: ProblemDefinitionBundle,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Export problem layers (GeoJSON), problem statements (JSON), and summary."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    exported: dict[str, Path] = {}

    # Export GeoJSON layers
    file_map = {
        "prob-01-functional-monoculture": "problem_01_functional_monoculture.geojson",
        "prob-02-spatial-fragmentation": "problem_02_spatial_fragmentation.geojson",
        "prob-03-sociospatial-isolation": "problem_03_sociospatial_isolation.geojson",
        "prob-04-ecological-disconnection": "problem_04_ecological_disconnection.geojson",
        "prob-05-waterfront-inaccessibility": "problem_05_waterfront_inaccessibility.geojson",
        "prob-06-unclassified-residual-ground": "problem_06_unclassified_residual_ground.geojson",
    }

    for p in bundle.problems:
        filename = file_map.get(p.problem_id, f"{p.problem_id}.geojson")
        p_path = out / filename
        p_path.write_text(json.dumps(p.geojson_layer, indent=2, ensure_ascii=False), encoding="utf-8")
        exported[p.problem_id] = p_path

    # Export JSON statements
    statements_path = out / "problem-statements.json"
    statements_path.write_text(json.dumps(bundle.to_statements_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    exported["statements"] = statements_path

    # Export summary
    summary_path = out / "problem-summary.json"
    summary_path.write_text(json.dumps(bundle.to_summary_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    exported["summary"] = summary_path

    return exported
