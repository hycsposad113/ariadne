"""Build a traceable, fixture-only geospatial baseline from Jack's portfolio.

The digitized plan is an analytical transcription, not an approved Site,
DesignBoundary, constraint set, or human decision.  Source inputs are read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box, mapping, shape
from shapely.ops import nearest_points, unary_union

from urban_design.morphology.metrics import FloorPlate, calculate_morphology_metrics


CRS = "EPSG:28992"
STUDY_AREA_REL = Path("artifacts/week4-repair-r02/syntax/study-area.geojson")
NORMALIZED_REL = Path(
    "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/"
    "sources/normalized"
)
P15 = "p15-hires-15.png"
P18 = "p18-18.png"
APPROVAL_ID = "ASSUMED_FROM_PORTFOLIO_2026-09-27"

# SIFT/RANSAC registration between the high-resolution p15 map and the p18
# zoning map, both in source-page pixel coordinates.
P15_TO_P18_H = np.array(
    [
        [3.57833815e-1, -1.32747867e-3, -2.99419485e1],
        [-1.44651243e-4, 3.58205852e-1, -4.28396502e2],
        [-6.61955101e-7, -9.96738613e-7, 1.00203913],
    ],
    dtype=float,
)
P18_BOUNDARY_PIXELS = np.array(
    [[737, 137], [1737, 137], [696, 364], [1737, 364]], dtype=float
)
STUDY_BOUNDARY_CONTROLS = np.array(
    [
        [88610.6505405546, 435704.09331819933],
        [89398.71649014998, 436221.6525033502],
        [88723.2313904968, 435507.0768308005],
        [89558.20602756809, 436037.1449992783],
    ],
    dtype=float,
)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _features(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if payload.get("type") == "Feature":
        return [payload]
    if payload.get("type") == "FeatureCollection":
        return payload.get("features", [])
    raise ValueError(f"Unsupported GeoJSON root in {path}")


def _polygonal(geometry):
    """Repair minor source-ring defects and discard non-polygon remnants."""
    if geometry.is_empty:
        return GeometryCollection()
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    if geometry.geom_type == "Polygon":
        return geometry
    if geometry.geom_type == "MultiPolygon":
        return geometry
    if hasattr(geometry, "geoms"):
        parts = [part for part in geometry.geoms if part.geom_type == "Polygon" and not part.is_empty]
        return unary_union(parts) if parts else GeometryCollection()
    return GeometryCollection()


def _affine_fit(pixel_points: np.ndarray, map_points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    design = np.column_stack([pixel_points, np.ones(len(pixel_points))])
    matrix, *_ = np.linalg.lstsq(design, map_points, rcond=None)
    residuals = np.linalg.norm(design @ matrix - map_points, axis=1)
    return matrix, residuals


def _p15_to_p18(x: float, y: float) -> tuple[float, float]:
    projected = P15_TO_P18_H @ np.array([x, y, 1.0])
    return float(projected[0] / projected[2]), float(projected[1] / projected[2])


def _p18_to_p15(x: float, y: float) -> tuple[float, float]:
    projected = np.linalg.inv(P15_TO_P18_H) @ np.array([x, y, 1.0])
    return float(projected[0] / projected[2]), float(projected[1] / projected[2])


def _apply_affine(matrix: np.ndarray, x: float, y: float) -> tuple[float, float]:
    x_values = np.asarray(x, dtype=float)
    y_values = np.asarray(y, dtype=float)
    if x_values.ndim == 0:
        mapped = np.array([float(x_values), float(y_values), 1.0]) @ matrix
        return float(mapped[0]), float(mapped[1])
    design = np.column_stack((x_values, y_values, np.ones_like(x_values)))
    mapped = design @ matrix
    return mapped[:, 0], mapped[:, 1]


def _transform_geometry(geometry, transform):
    from shapely.ops import transform as shapely_transform

    return shapely_transform(lambda x, y, z=None: transform(x, y), geometry)


def _metric_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [float(value[0]), float(value[1])]
    if hasattr(value, "reason"):
        return {"status": "UNAVAILABLE", "reason": value.reason}
    return float(value)


def _metric_record(value: Any, source_page: str, method: str, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source_page": source_page, "method": method}


def _load_source_data(project_root: Path, worktree_root: Path):
    study_path = project_root / STUDY_AREA_REL
    normalized = project_root / NORMALIZED_REL
    study_feature = _features(study_path)[0]
    study = _polygonal(shape(study_feature["geometry"]))
    if not study.is_valid or study.area <= 0:
        raise ValueError("StudyArea geometry must be valid and have positive area")

    bags: dict[str, tuple[Any, dict[str, Any]]] = {}
    bag_paths = sorted(normalized.glob("pdok-bag-pand-p*.geojson"))
    if not bag_paths:
        raise FileNotFoundError(f"No normalized BAG pand files under {normalized}")
    for path in bag_paths:
        for feature in _features(path):
            properties = feature.get("properties") or {}
            identifier = properties.get("identificatie")
            if not identifier or not feature.get("geometry"):
                continue
            bags.setdefault(str(identifier), (_polygonal(shape(feature["geometry"])), properties))

    water_paths = sorted(normalized.glob("pdok-bgt-waterdeel-*.geojson"))
    water_parts = []
    for path in water_paths:
        for feature in _features(path):
            if feature.get("geometry"):
                candidate = _polygonal(shape(feature["geometry"]))
                if candidate.intersects(study):
                    water_parts.append(candidate.intersection(study))
    water = _polygonal(unary_union(water_parts)) if water_parts else GeometryCollection()
    land = _polygonal(study.difference(water))
    if land.is_empty or land.area <= 0:
        raise ValueError("StudyArea land geometry is empty")

    osm_path = normalized / "osm-overpass-v5-epsg28992.geojson"
    osm_features = _features(osm_path)
    roads = []
    for feature in osm_features:
        tags = (feature.get("properties") or {}).get("tags") or {}
        if tags.get("highway") and feature.get("geometry"):
            roads.append((tags, shape(feature["geometry"])))

    # Optional, local and read-only contextual height table referenced by the
    # checked-in source manifest. It informs provenance only; it does not turn
    # a portfolio pixel trace into an observed as-built condition.
    height_manifest_path = worktree_root / "config/3dbag-height-source-manifest-v1.json"
    height_manifest = _read_json(height_manifest_path) if height_manifest_path.exists() else {}
    height_table_entry = height_manifest.get("height_table") or {}
    height_table_path = Path(
        height_table_entry.get("path")
        or (
            "/Users/jackhsieh/.local/share/urban-design-data/3dbag/"
            "height-table-v2025.09.03-study-area-v5-buffer500m.json"
        )
    )
    height_rows: dict[str, dict[str, Any]] = {}
    if height_table_path.exists():
        height_table = _read_json(height_table_path)
        height_rows = {
            str(row["bag_identificatie"]).removeprefix("NL.IMBAG.Pand."): row
            for row in height_table.get("records", [])
            if row.get("bag_identificatie")
        }
    return {
        "study": study,
        "land": land,
        "water": water,
        "bags": bags,
        "bag_paths": bag_paths,
        "water_paths": water_paths,
        "osm_path": osm_path,
        "roads": roads,
        "height_manifest_path": height_manifest_path,
        "height_manifest": height_manifest,
        "height_table_path": height_table_path if height_rows else None,
        "height_rows": height_rows,
        "study_path": study_path,
        "normalized_dir": normalized,
    }


def _make_georeference(data: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    bags = data["bags"]
    # Corresponding red building centers identified on p15 and candidate BAG
    # polygon centroids. LOW/MEDIUM status remains recorded on the building rows.
    building_controls = [
        ("p15 red #5 center", 3508.0, 1744.0, "0599100000765601", "building outline anchor"),
        ("p15 red #7 center", 3865.0, 1745.0, "0599100010058726", "building outline anchor"),
        ("p15 red #9 center", 3957.0, 1655.0, "0599100010039532", "building outline anchor"),
        ("p15 red #17 center", 3842.5, 2091.0, "0599100000752293", "building outline anchor"),
    ]
    p15_controls: list[tuple[float, float]] = []
    map_controls: list[tuple[float, float]] = []
    control_records: list[dict[str, Any]] = []

    for index, (x, y) in enumerate(P18_BOUNDARY_PIXELS):
        p15x, p15y = _p18_to_p15(float(x), float(y))
        target = STUDY_BOUNDARY_CONTROLS[index]
        p15_controls.append((p15x, p15y))
        map_controls.append((float(target[0]), float(target[1])))
        control_records.append(
            {
                "id": f"boundary-{index + 1}",
                "feature_class": "study-area-boundary / map frame",
                "p15_pixel": [round(p15x, 3), round(p15y, 3)],
                "reference_pixel_p18": [float(x), float(y)],
                "rd_new": [float(target[0]), float(target[1])],
                "target_source": "StudyArea v5 polygon vertex; visually tied to p18 dashed map frame",
                "confidence": "MEDIUM",
            }
        )

    for label, x, y, identifier, target_source in building_controls:
        if identifier not in bags:
            raise ValueError(f"BAG anchor {identifier} is absent from normalized BAG source")
        geometry, _properties = bags[identifier]
        target = geometry.centroid
        p15_controls.append((x, y))
        map_controls.append((target.x, target.y))
        control_records.append(
            {
                "id": label.replace(" ", "-").replace("#", "number-"),
                "feature_class": "BAG building outline",
                "p15_pixel": [x, y],
                "bag_pand_id": identifier,
                "rd_new": [float(target.x), float(target.y)],
                "target_source": target_source,
                "confidence": "LOW" if identifier == "0599100000765601" else "MEDIUM",
            }
        )

    # Additional road and harbour controls: a manually selected pixel is tied
    # to the nearest matching local source geometry after the image-only
    # boundary registration. Their final residuals are included in the RMSE.
    boundary_matrix, _ = _affine_fit(P18_BOUNDARY_PIXELS, STUDY_BOUNDARY_CONTROLS)

    def provisional_pixel_to_rd(x: float, y: float) -> tuple[float, float]:
        p18x, p18y = _p15_to_p18(x, y)
        return _apply_affine(boundary_matrix, p18x, p18y)

    road_candidates = [geometry for tags, geometry in data["roads"] if tags.get("name") == "Keileweg"]
    if not road_candidates:
        raise ValueError("Named OSM Keileweg reference is absent")
    road_pixel = (2800.0, 1610.0)
    road_line = unary_union(road_candidates)
    road_target = nearest_points(Point(provisional_pixel_to_rd(*road_pixel)), road_line)[1]
    p15_controls.append(road_pixel)
    map_controls.append((road_target.x, road_target.y))
    control_records.append(
        {
            "id": "keileweg-centerline",
            "feature_class": "OSM road centerline",
            "p15_pixel": list(road_pixel),
            "rd_new": [float(road_target.x), float(road_target.y)],
            "target_source": "nearest point on named OSM Keileweg after boundary-only image tie",
            "confidence": "MEDIUM",
        }
    )

    water_pixel = (3100.0, 2040.0)
    water_boundary = data["water"].boundary
    water_target = nearest_points(Point(provisional_pixel_to_rd(*water_pixel)), water_boundary)[1]
    p15_controls.append(water_pixel)
    map_controls.append((water_target.x, water_target.y))
    control_records.append(
        {
            "id": "keilehaven-south-bank",
            "feature_class": "BGT water boundary / harbour edge",
            "p15_pixel": list(water_pixel),
            "rd_new": [float(water_target.x), float(water_target.y)],
            "target_source": "nearest BGT waterdeel boundary after boundary-only image tie",
            "confidence": "MEDIUM",
        }
    )

    p15_array = np.asarray(p15_controls, dtype=float)
    map_array = np.asarray(map_controls, dtype=float)
    p15_matrix, residuals = _affine_fit(p15_array, map_array)
    rmse = float(math.sqrt(float(np.mean(np.square(residuals)))))
    for record, residual in zip(control_records, residuals):
        record["residual_m"] = float(residual)

    p18_matrix, p18_residuals = _affine_fit(P18_BOUNDARY_PIXELS, STUDY_BOUNDARY_CONTROLS)
    georef = {
        "schema_version": "portfolio-baseline-georef-v1",
        "status": "DRAFT_DIGITIZED_BASELINE",
        "crs": CRS,
        "units": "m",
        "source_page": P15,
        "secondary_page": P18,
        "method": (
            "p15-to-p18 projective raster registration followed by a least-squares "
            "affine fit in EPSG:28992 using StudyArea-frame, BAG-building, OSM-road, "
            "and BGT-harbour-edge controls."
        ),
        "p15_pixel_to_rd_affine": p15_matrix.tolist(),
        "p18_pixel_to_rd_affine": p18_matrix.tolist(),
        "p15_to_p18_homography": P15_TO_P18_H.tolist(),
        "control_count": len(control_records),
        "control_rmse_m": rmse,
        "controls": control_records,
        "p18_boundary_only_rmse_m": float(math.sqrt(float(np.mean(np.square(p18_residuals))))),
        "registration_quality": "APPROXIMATE; residuals include manual drawing-to-source matching error",
        "limitations": [
            "The dashed p18 boundary is a visual match to StudyArea v5, not a confirmed design boundary.",
            "Building centroids can differ from the drawn retained-building footprint and some BAG status fields conflict with the portfolio image.",
            "The 13 m control RMSE is too coarse for parcel-line, legal-boundary, or construction use.",
            "Road and harbour control points are visual ties to local OSM/BGT geometries; p15 was not supplied as a georeferenced source raster.",
        ],
    }
    return georef, p15_matrix, p18_matrix


PRESERVED = [
    {
        "design_number": 5,
        "name": "Art Studio (Current)",
        "original_function": "Art studio; marked current on the portfolio legend",
        "new_function": "Art studio",
        "overbuild": False,
        "bag_pand_id": "0599100000765601",
        "plan_pixel_reference": [3508.0, 1744.0],
        "confidence": "LOW",
        "reason": "The red plan footprint is close to this BAG outline, but the BAG record says 'Pand gesloopt'; the raster-to-source residual and status conflict prevent a stronger match.",
    },
    {
        "design_number": 7,
        "name": "Museum (Current) / Residence (Artist)",
        "original_function": "Museum; marked current on the portfolio legend",
        "new_function": "Artist residence with museum retained at lower floor",
        "overbuild": True,
        "bag_pand_id": "0599100010058726",
        "plan_pixel_reference": [3865.0, 1745.0],
        "confidence": "MEDIUM",
        "reason": "The digitized red footprint falls in the BAG building outline and the mapped historic building location is plausible; the portfolio is a low-resolution drawing without cadastral labels.",
    },
    {
        "design_number": 9,
        "name": "Restaurant",
        "original_function": "Existing building retained in red; original function label is restaurant",
        "new_function": "Restaurant",
        "overbuild": False,
        "bag_pand_id": "0599100010039532",
        "plan_pixel_reference": [3957.0, 1655.0],
        "confidence": "MEDIUM",
        "reason": "The red footprint center falls close to this BAG pand after local map registration; the adjacent mixed-use industrial block and coarse georeference still prevent a parcel-level claim.",
    },
    {
        "design_number": 11,
        "name": "Art Studio + Office (Current)",
        "original_function": "Art studio and office; marked current on the portfolio legend",
        "new_function": "Art studio and office",
        "overbuild": False,
        "bag_pand_id": "0599100010058726",
        "plan_pixel_reference": [4020.0, 1850.0],
        "confidence": "LOW",
        "reason": "This red block appears to lie within the same broader BAG pand candidate as #7; the image may depict a separate wing, so the duplicate pand association is retained with LOW confidence.",
    },
    {
        "design_number": 12,
        "name": "Design Firm (Current)",
        "original_function": "Design firm; marked current on the portfolio legend",
        "new_function": "Design firm",
        "overbuild": False,
        "bag_pand_id": "0599100000641255",
        "plan_pixel_reference": [4315.0, 1915.0],
        "confidence": "LOW",
        "reason": "This is a nearby industrial BAG candidate for the east-edge red block, but the mapped footprint does not fall inside the polygon and adjacent candidates remain plausible.",
    },
    {
        "design_number": 13,
        "name": "Leisure + Shopping / Residence (Katoenveem)",
        "original_function": "Katoenveem cultural-heritage building, as identified by the designer",
        "new_function": "Leisure and shopping at lower floors; residence above",
        "overbuild": True,
        "bag_pand_id": "0599100000188925",
        "plan_pixel_reference": [2510.5, 2098.0],
        "confidence": "LOW",
        "reason": "The label identifies Katoenveem, but the red plan footprint is about 31 m from this candidate outline after approximate georeferencing; recorded as a tentative contextual match only.",
    },
    {
        "design_number": 15,
        "name": "Community Kitchen + Food Bank (Current)",
        "original_function": "Community kitchen and food bank; marked current on the portfolio legend",
        "new_function": "Community kitchen and food bank",
        "overbuild": False,
        "bag_pand_id": "0599100000641246",
        "plan_pixel_reference": [3345.7, 2096.0],
        "confidence": "LOW",
        "reason": "Several nearby industrial BAG outlines are plausible and the plan-to-source residual is approximately 50 m; no unique correspondence is established.",
    },
    {
        "design_number": 17,
        "name": "Maker Space (Current) / Residence (Maker) (Keilepand)",
        "original_function": "Maker space; marked current on the portfolio legend",
        "new_function": "Maker space at lower floors; residence for makers above",
        "overbuild": True,
        "bag_pand_id": "0599100000752293",
        "plan_pixel_reference": [3842.5, 2091.0],
        "confidence": "HIGH",
        "reason": "The red plan footprint is contained by this BAG pand outline and the mapped location matches the named Keilepand block; HIGH refers to spatial correspondence only, not the building's legal, structural, or preservation status.",
    },
]


BUILDINGS = [
    (1, "Biogas Plant / Greenhouse", "new", False, 1, (1850, 1690, 2385, 1855)),
    (2, "Hydrothermal Battery + Carpark", "new", False, 1, (2460, 1620, 2645, 1740)),
    (3, "Retail / Residence", "new", False, 5, (2645, 1615, 3540, 1740)),
    (4, "Restaurant / Hotel", "new", False, 4, (3360, 1615, 3560, 1825)),
    (5, "Art Studio (Current)", "retained", False, 1, (3430, 1620, 3560, 1825)),
    (6, "Exhibition Hall", "new", False, 2, (3675, 1745, 3848, 1920)),
    (7, "Museum (Current) / Residence (Artist)", "retained_plus_overbuild", True, 5, (3800, 1700, 3935, 1810)),
    (8, "Logistic Hub", "new", False, 3, (3900, 1700, 3965, 1815)),
    (9, "Restaurant", "retained", False, 3, (3925, 1620, 3990, 1710)),
    (10, "Recreation / Residence", "new", False, 5, (4165, 1610, 4340, 1770)),
    (11, "Art Studio + Office (Current)", "retained", False, 2, (3967, 1830, 4050, 1875)),
    (12, "Design Firm (Current)", "retained", False, 2, (4278, 1868, 4352, 1955)),
    (13, "Leisure + Shopping / Residence (Katoenveem)", "retained_plus_overbuild", True, 5, (2346, 2068, 2677, 2129)),
    (14, "Coworking Space / Residence", "new", False, 5, (2730, 2010, 3290, 2185)),
    (15, "Community Kitchen + Food Bank (Current)", "retained", False, 1, (3298, 2035, 3395, 2158)),
    (16, "Logistic Hub / School", "new", False, 4, (3395, 2010, 3510, 2190)),
    (17, "Maker Space (Current) / Residence (Maker)", "retained_plus_overbuild", True, 5, (3708, 2021, 3978, 2160)),
    (18, "Urban Mining Factory + Repair Factory + Logistic Hub / Residence", "new", False, 3, (4000, 2010, 4295, 2190)),
]


ZONES = [
    ("zone-energy-hub", "Energy Hub", [(735, 143), (950, 143), (950, 225), (735, 225)]),
    (
        "zone-residential-tidal-park",
        "Residential + Tidal Park",
        [(951, 143), (1244, 143), (1244, 225), (951, 225)],
    ),
    (
        "zone-art-space-recreation",
        "Art Space + Recreation",
        [(1245, 143), (1540, 143), (1540, 225), (1245, 225)],
    ),
    ("zone-residential", "Residential", [(770, 283), (1244, 283), (1244, 359), (770, 359)]),
    (
        "zone-maker-recycle-hub",
        "Maker Space + Recycle Hub",
        [(1245, 283), (1540, 283), (1540, 359), (1245, 359)],
    ),
]

OPEN_SPACES = [
    ("tidal-waterfront-park", "Tidal Park", [(2350, 1775), (3540, 1775), (3540, 2005), (2350, 2005)]),
    ("central-food-garden", "Central Food Garden", [(3970, 1790), (4390, 1790), (4390, 2020), (3970, 2020)]),
    ("art-park", "Art Park", [(4160, 1725), (4490, 1725), (4490, 1995), (4160, 1995)]),
    ("ecology-forest", "Ecology Forest", [(4105, 1990), (4455, 1990), (4455, 2195), (4105, 2195)]),
]


def _tree_map_items() -> list[dict[str, Any]]:
    items = [
        ("Residence", "residential", 45995),
        ("Residence (Artist)", "residential", None),
        ("Recreation", "facilities", None),
        ("Residence (Maker)", "residential", 6571),
        ("Community Kitchen", "facilities", 3285),
        ("Garage", "facilities", None),
        ("Coworking Space", "office", None),
        ("Design Firm", "office", 600),
        ("Art Studio + Office", "office", None),
        ("Maker Space (Current)", "maker_industry", 20000),
        ("Urban Mining Factory", "maker_industry", 10000),
        ("Logistic Hub", "maker_industry", 7566),
        ("Repair Factory", "maker_industry", 5000),
        ("Retail", "maker_industry", None),
        ("Hotel", "facilities", None),
        ("Museum (Current)", "facilities", None),
        ("Restaurant", "facilities", None),
        ("Leisure + Shopping", "facilities", None),
        ("Greenhouse", "maker_industry", None),
        ("Hydrothermal Battery", "facilities", None),
        ("School", "facilities", 10160),
        ("Biogas Plant", "facilities", None),
    ]
    return [
        {
            "name": name,
            "category": category,
            "value_m2": value,
            "status": "READABLE" if value is not None else "UNREADABLE",
            "source_page": P18,
            "extraction_method": "manual transcription from the p18 treemap labels; ambiguous small text is kept null",
        }
        for name, category, value in items
    ]


def build_portfolio_baseline(*, project_root: Path | str, output_dir: Path | str) -> dict[str, Any]:
    """Create all requested portfolio baseline outputs without mutating sources."""
    project_root = Path(project_root).resolve()
    output_dir = Path(output_dir).resolve()
    worktree_root = Path(__file__).resolve().parents[1]
    output_dir.mkdir(parents=True, exist_ok=True)
    data = _load_source_data(project_root, worktree_root)
    georef, p15_matrix, p18_matrix = _make_georeference(data)

    def p15_to_rd(x: float, y: float) -> tuple[float, float]:
        return _apply_affine(p15_matrix, x, y)

    def p18_to_rd(x: float, y: float) -> tuple[float, float]:
        return _apply_affine(p18_matrix, x, y)

    def pixel_polygon(points: Iterable[tuple[float, float]], transform):
        return Polygon([transform(x, y) for x, y in points])

    # Keep clipped geometry a micron inside the land edge so the strict
    # ``covers`` validation in the shared metric kernel is stable at floating
    # point precision.
    clipped_land = data["land"].buffer(-1e-6)

    # Recompute exact transformed feature checks after the final least-squares fit.
    road_point = Point(p15_to_rd(2800, 1610))
    named_keileweg = unary_union([g for tags, g in data["roads"] if tags.get("name") == "Keileweg"])
    road_residual = float(road_point.distance(named_keileweg))
    harbor_point = Point(p15_to_rd(3100, 2040))
    harbor_residual = float(harbor_point.distance(data["water"].boundary))
    georef["independent_feature_checks"] = [
        {
            "feature_class": "OSM road centerline",
            "source_feature": "Keileweg",
            "p15_pixel": [2800, 1610],
            "nearest_source_residual_m": road_residual,
            "source_path": "normalized/osm-overpass-v5-epsg28992.geojson",
        },
        {
            "feature_class": "BGT harbour edge",
            "source_feature": "nearest waterdeel boundary",
            "p15_pixel": [3100, 2040],
            "nearest_source_residual_m": harbor_residual,
            "source_path": "normalized/pdok-bgt-waterdeel-*.geojson",
        },
    ]
    georef["study_area"] = {
        "source_path": STUDY_AREA_REL.as_posix(),
        "feature_id": _features(data["study_path"])[0].get("id"),
        "area_m2": float(data["study"].area),
        "land_area_m2": float(data["land"].area),
        "water_area_m2": float(data["water"].area),
        "geometry_sha256": (_read_json(data["study_path"]).get("properties") or {}).get(
            "study_area_geometry_sha256"
        ),
        "status_note": "StudyArea v5 is a confirmed exploration area, not a formally adopted design boundary.",
    }
    georef["sources"] = {
        "study_area": {"path": STUDY_AREA_REL.as_posix(), "sha256": _sha256(data["study_path"])},
        "bag_pand": [
            {"path": str(path.relative_to(project_root)), "sha256": _sha256(path)} for path in data["bag_paths"]
        ],
        "bgt_waterdeel": [
            {"path": str(path.relative_to(project_root)), "sha256": _sha256(path)}
            for path in data["water_paths"]
        ],
        "osm_roads": {"path": str(data["osm_path"].relative_to(project_root)), "sha256": _sha256(data["osm_path"])},
        "portfolio_pages": [
            {"path": f"pages/{name}", "sha256": _sha256(output_dir / "pages" / name)}
            for name in ("p15-hires-15.png", "p18-18.png", "p19-19.png", "p20-20.png", "p22-22.png")
            if (output_dir / "pages" / name).exists()
        ],
    }
    if data["height_table_path"]:
        georef["sources"]["3d_bag_height_table"] = {
            "path": str(data["height_table_path"]),
            "sha256": _sha256(data["height_table_path"]),
            "data_version": "v2025.09.03",
            "license": "CC BY 4.0",
            "use": "contextual height reference only; not used to infer portfolio floors",
        }
    _write_json(output_dir / "georef.json", georef)

    preserved_rows = []
    for row in PRESERVED:
        bag_geometry, bag_properties = data["bags"][row["bag_pand_id"]]
        height_record = data["height_rows"].get(row["bag_pand_id"])
        preserved_rows.append(
            {
                **row,
                "source_page": P15,
                "extraction_method": "manual red-footprint interpretation and spatial cross-reference against local normalized BAG pand polygons",
                "bag_status": bag_properties.get("status"),
                "bag_gebruiksdoel": bag_properties.get("gebruiksdoel"),
                "bag_outline_area_m2": float(bag_geometry.area),
                "three_d_bag_height_reference": (
                    {
                        "height_above_ground_m": height_record.get("height_above_ground_m"),
                        "roof_p70_height_m": height_record.get("roof_p70_height_m"),
                        "status": height_record.get("status"),
                        "source_version": height_record.get("source_version"),
                        "use": "context only; does not establish the proposal's future height or legal preservation",
                    }
                    if height_record
                    else None
                ),
            }
        )
    _write_json(
        output_dir / "preserved-buildings.json",
        {
            "schema_version": "portfolio-preserved-buildings-v1",
            "crs": CRS,
            "status": "DRAFT_SPATIAL_MATCHES",
            "source_page": P15,
            "buildings": preserved_rows,
            "limitations": [
                "BAG is a pand geometry/status source, not a preservation register or proof of current occupation.",
                "The plan uses red to indicate retained existing structures; LOW/MEDIUM matches remain unresolved candidates.",
            ],
        },
    )

    zone_features = []
    for identifier, label, coords in ZONES:
        raw = pixel_polygon(coords, p18_to_rd)
        clipped = _polygonal(raw.intersection(clipped_land))
        if clipped.is_empty or clipped.area <= 0:
            continue
        zone_features.append(
            {
                "type": "Feature",
                "id": identifier,
                "geometry": mapping(clipped),
                "properties": {
                    "name": label,
                    "classification": "PREFERENCE",
                    "source_page": P18,
                    "extraction_method": "manual digitization of five translucent zone labels on the p18 masterplan; clipped to StudyArea land",
                    "confidence": "LOW",
                    "approximate_pixel_polygon": coords,
                },
            }
        )
    _write_json(
        output_dir / "zones.geojson",
        {
            "type": "FeatureCollection",
            "name": "Portfolio zoning preferences",
            "crs": {"type": "name", "properties": {"name": CRS}},
            "features": zone_features,
            "properties": {"source_page": P18, "status": "DRAFT_PREFERENCE_GEOMETRY"},
        },
    )

    open_features = []
    for identifier, label, coords in OPEN_SPACES:
        raw = pixel_polygon(coords, p15_to_rd)
        clipped = _polygonal(raw.intersection(clipped_land))
        if clipped.is_empty or clipped.area <= 0:
            continue
        open_features.append(
            {
                "type": "Feature",
                "id": identifier,
                "geometry": mapping(clipped),
                "properties": {
                    "name": label,
                    "classification": "PREFERENCE_OPEN_SPACE",
                    "source_page": "p15-hires-15.png / p19-19.png / p20-20.png",
                    "extraction_method": "approximate manual polygon trace from the numbered masterplan and landscape/public-space diagrams, clipped to StudyArea land",
                    "confidence": "LOW",
                    "approximate_pixel_polygon_p15": coords,
                },
            }
        )
    bridge_line = LineString([p15_to_rd(4180, 2110), p15_to_rd(4500, 1980)])
    bridge = _polygonal(bridge_line.buffer(7.0).intersection(clipped_land))
    if not bridge.is_empty and bridge.area > 0:
        open_features.append(
            {
                "type": "Feature",
                "id": "ecology-bridge-corridor",
                "geometry": mapping(bridge),
                "properties": {
                    "name": "Ecology Bridge corridor",
                    "classification": "PREFERENCE_OPEN_SPACE",
                    "source_page": "p15-hires-15.png / p19-19.png",
                    "extraction_method": "digitized bridge centerline around masterplan label 19 and buffered 7 m to express a corridor; clipped to StudyArea land",
                    "confidence": "LOW",
                    "buffer_width_m": 14.0,
                },
            }
        )
    _write_json(
        output_dir / "open-spaces.geojson",
        {
            "type": "FeatureCollection",
            "name": "Portfolio public and ecological space preferences",
            "crs": {"type": "name", "properties": {"name": CRS}},
            "features": open_features,
            "properties": {"status": "DRAFT_PREFERENCE_GEOMETRY", "clipped_to": "StudyArea v5 minus BGT waterdeel"},
        },
    )

    plates: list[FloorPlate] = []
    scenario_features = []
    for number, name, status, overbuild, floors, pixel_bounds in BUILDINGS:
        x0, y0, x1, y1 = pixel_bounds
        raw = _transform_geometry(box(x0, y0, x1, y1), p15_to_rd)
        footprint = _polygonal(raw.intersection(clipped_land))
        if footprint.is_empty or footprint.area <= 0.1:
            continue
        building_id = f"portfolio-{number:02d}"
        for level in range(floors):
            plates.append(FloorPlate(id=f"{building_id}-floor-{level + 1}", geometry=footprint, level=level, building_id=building_id))
        preserved_match = next((item for item in PRESERVED if item["design_number"] == number), None)
        if preserved_match:
            bag_geometry, _ = data["bags"][preserved_match["bag_pand_id"]]
            nearest = float(footprint.centroid.distance(bag_geometry))
            confidence = preserved_match["confidence"]
            bag_id = preserved_match["bag_pand_id"]
        else:
            nearest = None
            confidence = "LOW"
            bag_id = None
        scenario_features.append(
            {
                "type": "Feature",
                "id": building_id,
                "geometry": mapping(footprint),
                "properties": {
                    "design_number": number,
                    "name": name,
                    "building_status": status,
                    "overbuild": overbuild,
                    "bag_pand_id_candidate": bag_id,
                    "bag_match_confidence": confidence,
                    "bag_centroid_distance_m": nearest,
                    "floor_count_estimate": floors,
                    "height_estimate_m": 4.5 + (floors - 1) * 3.5,
                    "height_method": "first floor 4.5 m plus 3.5 m per upper floor; the p22 note separately describes typical five-floor housing as about 17 m",
                    "source_page": P15,
                    "floor_count_source": "p22 user-supplied portfolio note and p15 functional/massing depiction; all counts are analytical estimates",
                    "footprint_extraction_method": "manual p15 pixel-box trace transformed by the multi-source affine fit and clipped to StudyArea land",
                    "connects_to_ecology_bridge": number == 18,
                    "vertical_context_note": (
                        "The user-supplied design note describes an approximately 10 m level difference to Dakpark via the ecology bridge; this is terrain context, not building height."
                        if number == 18
                        else None
                    ),
                    "confidence": confidence,
                    "digitized_source_pixel_bounds": list(pixel_bounds),
                },
            }
        )

    land_metrics = calculate_morphology_metrics(
        data["land"],
        plates,
        first_floor_height_m=4.5,
        standard_floor_height_m=3.5,
        floor_count=max(row[4] for row in BUILDINGS),
        provenance="FIXTURE_ONLY",
    )
    full_metrics = calculate_morphology_metrics(
        data["study"],
        plates,
        first_floor_height_m=4.5,
        standard_floor_height_m=3.5,
        floor_count=max(row[4] for row in BUILDINGS),
        provenance="FIXTURE_ONLY",
    )
    open_union = unary_union([shape(feature["geometry"]) for feature in open_features]) if open_features else GeometryCollection()
    open_ratio = float(open_union.intersection(data["land"]).area / data["land"].area)
    scenario_metrics = {
        "gfa_m2": _metric_value(land_metrics.gfa_m2),
        "land_far": _metric_value(land_metrics.far),
        "complete_study_area_far": _metric_value(full_metrics.far),
        "coverage_m2": land_metrics.coverage_m2,
        "coverage_ratio": land_metrics.coverage_ratio,
        "maximum_estimated_height_m": _metric_value(land_metrics.height_m),
        "open_space_ratio": open_ratio,
        "land_area_m2": float(data["land"].area),
        "complete_study_area_m2": float(data["study"].area),
        "provenance": "FIXTURE_ONLY",
        "metric_kernel": "urban_design.morphology.metrics.calculate_morphology_metrics",
        "height_parameters_m": {"first_floor": 4.5, "standard_floor": 3.5},
        "limitations": [
            "Every footprint and floor count is a manual analytical estimate; scenario metrics are not the treemap total.",
            "The same floor-plate footprint is repeated for each estimated floor; no setbacks or partial upper floors were digitized.",
            "Open-space ratio is the union of low-confidence digitized preference polygons divided by StudyArea land area.",
        ],
    }
    _write_json(
        output_dir / "portfolio-scenario.geojson",
        {
            "type": "FeatureCollection",
            "name": "Jack's original portfolio scenario (digitized estimate)",
            "crs": {"type": "name", "properties": {"name": CRS}},
            "features": scenario_features,
            "properties": {"status": "DRAFT_FIXTURE_ONLY", "metrics": scenario_metrics},
        },
    )

    items = _tree_map_items()
    known_total = sum(item["value_m2"] for item in items if item["value_m2"] is not None)
    category_values: dict[str, int] = {}
    for item in items:
        if item["value_m2"] is not None:
            category_values[item["category"]] = category_values.get(item["category"], 0) + item["value_m2"]
    category_summary = {
        category: {
            "readable_subtotal_m2": value,
            "share_of_readable_subtotal_percent": round(value / known_total * 100, 4),
            "status": "PARTIAL_LOWER_BOUND",
        }
        for category, value in sorted(category_values.items())
    }
    for category in ("residential", "maker_industry", "office", "facilities"):
        category_summary.setdefault(
            category,
            {"readable_subtotal_m2": 0, "share_of_readable_subtotal_percent": 0.0, "status": "PARTIAL_LOWER_BOUND"},
        )
    _write_json(
        output_dir / "program.json",
        {
            "schema_version": "portfolio-program-v1",
            "source_page": P18,
            "units": "m2 GFA as printed in the portfolio treemap",
            "tree_map": {
                "source_page": P18,
                "items": items,
                "readable_lower_bound_gfa_m2": known_total,
                "complete_treemap_gfa_m2": None,
                "unreadable_item_count": sum(item["value_m2"] is None for item in items),
                "category_readable_subtotals": category_summary,
                "share_denominator_m2": known_total,
                "share_warning": "Percentages are shares of the readable subset only; unreadable cells prevent a complete category share or total GFA.",
                "extraction_method": "manual transcription; null values are retained as UNREADABLE rather than estimated from treemap area",
            },
            "digitized_scenario_estimate": {
                "gfa_m2": scenario_metrics["gfa_m2"],
                "land_far": scenario_metrics["land_far"],
                "complete_study_area_far": scenario_metrics["complete_study_area_far"],
                "source_page": P15,
                "extraction_method": "p15 manual footprint boxes × estimated floors, calculated by the deterministic morphology metrics module",
                "status": "DRAFT_ESTIMATE; distinct from incomplete p18 treemap transcription",
            },
        },
    )

    metric_records = {
        "estimated_gfa_m2": _metric_record(
            scenario_metrics["gfa_m2"], P15, "sum of transformed clipped footprint areas repeated for the estimated floor count via morphology metrics module", "m2"
        ),
        "land_far": _metric_record(
            scenario_metrics["land_far"], P15, "scenario GFA divided by StudyArea minus BGT waterdeel area", "ratio"
        ),
        "complete_study_area_far": _metric_record(
            scenario_metrics["complete_study_area_far"], P15, "scenario GFA divided by full StudyArea v5 polygon area, including harbor water", "ratio"
        ),
        "open_space_ratio": _metric_record(
            scenario_metrics["open_space_ratio"], "p15-hires-15.png / p19-19.png / p20-20.png", "union area of approximate named open-space polygons divided by StudyArea land area", "ratio"
        ),
        "coverage_ratio_estimate": _metric_record(
            scenario_metrics["coverage_ratio"], P15, "union of scenario building footprints divided by StudyArea land area via morphology metrics module", "ratio"
        ),
        "representative_residential_height_m": _metric_record(
            17.0, "p22-22.png (user-supplied page note)", "reported design reference: residential massing approximately five floors / 17 m; this is not a GIS measurement", "m"
        ),
        "kernel_maximum_estimated_height_m": _metric_record(
            scenario_metrics["maximum_estimated_height_m"], P15, "first floor 4.5 m plus 3.5 m per additional estimated floor; maximum floor count among digitized masses", "m"
        ),
        "treemap_readable_gfa_lower_bound_m2": _metric_record(
            known_total, P18, "sum of legible printed treemap values only; unreadable cells omitted and complete total remains unavailable", "m2"
        ),
        "treemap_readable_land_far_lower_bound": _metric_record(
            known_total / data["land"].area, f"{P18} + StudyArea v5 + normalized BGT waterdeel", "readable treemap GFA subtotal divided by StudyArea land area; lower bound only", "ratio"
        ),
    }
    _write_json(
        output_dir / "intensity-portfolio.json",
        {
            "schema_version": "portfolio-intensity-v1",
            "status": "DRAFT_ESTIMATED_BASELINE",
            "crs": CRS,
            "metrics": metric_records,
            "complete_treemap_total_gfa_m2": None,
            "complete_treemap_land_far": None,
            "scenario_to_treemap_readable_lower_bound_factor": round(
                float(scenario_metrics["gfa_m2"]) / known_total, 4
            ),
            "consistency_review": "REVIEW_REQUIRED: the low-confidence footprint/floor transcription yields substantially more GFA than the readable treemap subtotal; unreadable treemap cells and schematic page geometry prevent resolving the difference.",
            "raw_areas": {
                "study_area_m2": _metric_record(float(data["study"].area), "StudyArea v5 GeoJSON", "Shapely polygon area in EPSG:28992", "m2"),
                "land_area_m2": _metric_record(float(data["land"].area), "StudyArea v5 + normalized BGT waterdeel", "StudyArea polygon minus clipped BGT waterdeel union", "m2"),
                "water_area_m2": _metric_record(float(data["water"].area), "normalized BGT waterdeel", "union of waterdeel polygons intersected with StudyArea", "m2"),
            },
            "metric_kernel": "urban_design.morphology.metrics.calculate_morphology_metrics",
            "provenance": "FIXTURE_ONLY",
            "caveat": "Treemap total is incomplete; GFA/FAR/coverage are a separate, low-confidence digitized scenario estimate.",
        },
    )

    portfolio_far = float(scenario_metrics["land_far"])
    portfolio_open = float(scenario_metrics["open_space_ratio"])
    base_parameters = {
        "first_floor_height_m": 4.5,
        "standard_floor_height_m": 3.5,
        "minimum_open_space_ratio_preference": portfolio_open,
        "open_space_preference_basis": "approximate p15/p19/p20 digitized open-space union / StudyArea land; LOW confidence",
    }
    common_assumed = {
        "approval_decision_id": APPROVAL_ID,
        "human_approval_recorded": False,
        "approval_status": "ASSUMPTION_ONLY_NOT_APPROVED",
        "source_page": "p15-hires-15.png / p18-18.png / p22-22.png",
        "status": None,
        "crs": CRS,
        "basis": "analytical comparison preset derived from the portfolio transcription; no HumanDecision was created",
    }
    intensity_a = {
        **common_assumed,
        "schema_version": "portfolio-intensity-assumption-v1",
        "status": "ASSUMED_FROM_PORTFOLIO",
        "parameters": {
            **base_parameters,
            "far_upper_bound_land": round(portfolio_far * 1.1, 6),
            "far_upper_bound_method": "1.1 × the digitized original portfolio scenario land FAR; the incomplete treemap is not used as a complete FAR source",
            "height_upper_bound_m": 20.0,
            "coverage_upper_bound": None,
        },
    }
    intensity_b = {
        **common_assumed,
        "schema_version": "portfolio-intensity-assumption-v1",
        "status": "ASSUMED_HIGH_DENSITY",
        "parameters": {
            **base_parameters,
            "far_target_land": 2.0,
            "far_upper_bound_land": 2.0,
            "height_upper_bound_m": 40.0,
            "coverage_upper_bound": 0.5,
            "far_and_coverage_basis": "explicit user-supplied high-density comparison assumptions",
        },
    }
    _write_json(output_dir / "intensity-A.json", intensity_a)
    _write_json(output_dir / "intensity-B.json", intensity_b)

    return {
        "output_dir": str(output_dir),
        "files": sorted(path.name for path in output_dir.iterdir() if path.is_file()),
        "bag_count": len(data["bags"]),
        "zone_count": len(zone_features),
        "open_space_count": len(open_features),
        "scenario_building_count": len(scenario_features),
        "land_area_m2": float(data["land"].area),
        "control_rmse_m": georef["control_rmse_m"],
        "portfolio_scenario_gfa_m2": scenario_metrics["gfa_m2"],
        "portfolio_land_far": portfolio_far,
    }


def main() -> None:
    worktree_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=worktree_root.parent / "project")
    parser.add_argument("--output-dir", type=Path, default=worktree_root / "artifacts/portfolio-baseline")
    args = parser.parse_args()
    summary = build_portfolio_baseline(project_root=args.project_root, output_dir=args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
