"""Platform geometry adapter for environmental simulation (W6-11 E1).

Converts platform geometry models (BuildingMassing, MassingArtifact, GeoJSON, Shapely)
to environmental simulation obstacles and sensor footprints with:
- Asymmetric 2D footprint to 3D multi-face obstacle conversion
- Invertible roundtrip verification (2D -> 3D -> 2D) with micro-metre tolerance
- True North and Grid Convergence (meridian convergence) calculation for EPSG:28992
- Rigid local-to-world transform verification
- Strict unit validation (metres for space, hours for sunlight)
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import triangulate, unary_union

from .contracts import Obstacle


class UnknownRetainedHeightError(ValueError):
    """A retained building is an obstacle candidate but its height is unknown."""

    def __init__(self, building_id: str):
        self.building_id = building_id
        super().__init__(
            f"Retained building {building_id} has no numeric height_m and no demolished or zero-floor evidence"
        )


@dataclass(frozen=True)
class ScenarioEnvironmentGeometry:
    """Validated simulation geometry extracted from one formal scenario artifact."""

    obstacles: tuple[Obstacle, ...]
    site_area: Polygon | MultiPolygon
    water_geometry: BaseGeometry
    public_open_space: Polygon | MultiPolygon
    excluded_obstacles: tuple[dict[str, str], ...] = ()


def validate_coordinate_units(units: str | None) -> str:
    """Validate that linear spatial measurement units are metres ('m').

    Fails closed on missing or unexpected unit declarations.
    """
    if not isinstance(units, str) or not units.strip():
        raise ValueError("Coordinate unit is required and must not be empty.")
    normalized = units.strip().lower()
    if normalized not in ("m", "meter", "meters", "metre", "metres"):
        raise ValueError(
            f"Invalid coordinate unit '{units}': simulation requires metres ('m')."
        )
    return "m"


def compute_grid_convergence_deg(
    longitude: float,
    latitude: float,
) -> float:
    """Compute meridian convergence for the EPSG:28992 grid at a WGS84 location."""
    if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
        raise ValueError(f"Invalid geographical coordinates: lon={longitude}, lat={latitude}")
    try:
        from pyproj import Proj

        gamma_deg = Proj("EPSG:28992").get_factors(longitude, latitude).meridian_convergence
    except Exception as exc:
        raise RuntimeError("EPSG:28992 meridian convergence calculation is unavailable") from exc
    if not math.isfinite(gamma_deg):
        raise ValueError("EPSG:28992 meridian convergence is not finite")
    return round(float(gamma_deg), 6)


def rotate_point_2d(
    point: tuple[float, float],
    angle_deg: float,
    origin: tuple[float, float] = (0.0, 0.0),
) -> tuple[float, float]:
    """Rotate a 2D point around an origin by angle_deg (clockwise positive)."""
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    ox, oy = origin
    px, py = point[0] - ox, point[1] - oy

    # Clockwise rotation: x' = x*cos + y*sin, y' = -x*sin + y*cos
    rx = px * cos_a + py * sin_a + ox
    ry = -px * sin_a + py * cos_a + oy
    return (round(rx, 8), round(ry, 8))


def rotate_geometry_2d(
    coords: Sequence[tuple[float, float]],
    angle_deg: float,
    origin: tuple[float, float] = (0.0, 0.0),
) -> list[tuple[float, float]]:
    """Rotate a sequence of 2D coordinates around an origin by angle_deg."""
    return [rotate_point_2d(pt, angle_deg, origin) for pt in coords]


def _hash_faces(faces: Sequence[Sequence[tuple[float, float, float]]]) -> str:
    """Compute deterministic SHA-256 hash for 3D polygon faces."""
    canonical = []
    for face in faces:
        canonical.append([[round(c, 5) for c in pt] for pt in face])
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def footprint_to_obstacle(
    footprint_coords: Sequence[tuple[float, float]] | Polygon,
    height_m: float,
    base_z: float = 0.0,
    obstacle_id: str = "obstacle_bldg",
    source: str = "FIXTURE_ONLY",
) -> Obstacle:
    """Convert an asymmetric 2D polygon footprint and height into a 3D multi-face Obstacle.

    Triangulated horizontal faces preserve concavities and holes; vertical walls
    follow both the exterior and interior rings.
    """
    if not math.isfinite(height_m) or height_m <= 0.0:
        raise ValueError(f"Building height must be > 0.0, got {height_m}")
    if not math.isfinite(base_z):
        raise ValueError(f"Building base elevation must be finite, got {base_z}")
    polygon = footprint_coords if isinstance(footprint_coords, Polygon) else Polygon(footprint_coords)
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0.0:
        raise ValueError("Footprint must be a valid, non-empty polygon with positive area")

    triangles = [triangle for triangle in triangulate(polygon) if polygon.covers(triangle) and triangle.area > 0.0]
    triangulated_footprint = unary_union(triangles)
    if triangulated_footprint.symmetric_difference(polygon).area > 1e-6:
        raise ValueError("Footprint triangulation did not preserve its full area")

    top_z = base_z + height_m
    faces: list[list[tuple[float, float, float]]] = []
    for triangle in triangles:
        ring = list(triangle.exterior.coords)[:-1]
        faces.append([(float(x), float(y), float(base_z)) for x, y in reversed(ring)])
        faces.append([(float(x), float(y), float(top_z)) for x, y in ring])

    # Close both the exterior shell and any interior courtyard walls.
    for linear_ring in (polygon.exterior, *polygon.interiors):
        ring = list(linear_ring.coords)
        for p1, p2 in zip(ring, ring[1:]):
            faces.append([
                (float(p1[0]), float(p1[1]), float(base_z)),
                (float(p2[0]), float(p2[1]), float(base_z)),
                (float(p2[0]), float(p2[1]), float(top_z)),
                (float(p1[0]), float(p1[1]), float(top_z)),
            ])

    geom_hash = _hash_faces(faces)

    return Obstacle(
        obstacle_id=obstacle_id,
        kind="POLYGONS",
        source=source,
        geometry_hash=geom_hash,
        faces=faces,
    )


def obstacle_to_2d_footprint(obstacle: Obstacle) -> Polygon:
    """Project a 3D Obstacle back onto the 2D horizontal plane (ground footprint)."""
    if obstacle.kind == "BOX_AABB" and obstacle.bounds is not None:
        min_x, min_y, _, max_x, max_y, _ = obstacle.bounds
        return Polygon([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)])

    if obstacle.kind == "POLYGONS" and obstacle.faces:
        return polygon_faces_to_footprint(obstacle.faces)

    raise ValueError(f"Cannot extract 2D footprint from obstacle {obstacle.obstacle_id}")


def polygon_faces_to_footprint(
    faces: Sequence[Sequence[tuple[float, float, float]]], tolerance: float = 1e-8
) -> Polygon:
    """Union all coplanar lowest faces to reconstruct a polygon footprint with holes."""
    if not faces or not any(faces):
        raise ValueError("Polygon obstacle has no faces")
    min_z = min(point[2] for face in faces for point in face)
    ground_polygons: list[Polygon] = []
    for face in faces:
        if len(face) < 3 or any(abs(point[2] - min_z) > tolerance for point in face):
            continue
        candidate = Polygon([(point[0], point[1]) for point in face])
        if candidate.is_valid and candidate.area > tolerance:
            ground_polygons.append(candidate)
    if not ground_polygons:
        raise ValueError("Polygon obstacle has no valid ground faces")
    footprint = unary_union(ground_polygons)
    if not isinstance(footprint, Polygon) or not footprint.is_valid or footprint.is_empty:
        raise ValueError("Polygon obstacle ground faces do not form one valid footprint")
    return footprint


def verify_geometry_roundtrip(
    footprint_coords: Sequence[tuple[float, float]] | Polygon,
    height_m: float,
    base_z: float = 0.0,
    tolerance_m: float = 1e-6,
) -> dict[str, Any]:
    """Verify asymmetric geometry transformation roundtrip: 2D Footprint -> 3D Obstacle -> 2D Projection.

    Enforces that:
    1. Area matches within 1e-6 m2
    2. Perimeter matches within 1e-6 m
    3. Vertex coordinates reconstruct original within tolerance_m
    """
    poly_orig = footprint_coords if isinstance(footprint_coords, Polygon) else Polygon(footprint_coords)
    if not poly_orig.is_valid:
        raise ValueError("Input footprint polygon is topologically invalid.")

    # Convert to 3D obstacle
    obs = footprint_to_obstacle(footprint_coords, height_m=height_m, base_z=base_z)

    # Project back to 2D
    poly_proj = obstacle_to_2d_footprint(obs)

    area_orig = poly_orig.area
    area_proj = poly_proj.area
    area_diff = abs(area_orig - area_proj)

    perim_orig = poly_orig.length
    perim_proj = poly_proj.length
    perim_diff = abs(perim_orig - perim_proj)

    # Hausdorff distance between original boundary and projected boundary
    geom_dist = poly_orig.boundary.hausdorff_distance(poly_proj.boundary)

    if area_diff > tolerance_m:
        raise ValueError(
            f"Roundtrip area mismatch: original={area_orig:.6f}, reconstructed={area_proj:.6f}, diff={area_diff:.8f}"
        )
    if perim_diff > tolerance_m:
        raise ValueError(
            f"Roundtrip perimeter mismatch: original={perim_orig:.6f}, reconstructed={perim_proj:.6f}, diff={perim_diff:.8f}"
        )
    if geom_dist > tolerance_m:
        raise ValueError(
            f"Roundtrip Hausdorff error {geom_dist:.8f} exceeds tolerance {tolerance_m}"
        )

    return {
        "roundtrip_passed": True,
        "original_area_m2": round(area_orig, 6),
        "reconstructed_area_m2": round(area_proj, 6),
        "area_diff_m2": round(area_diff, 8),
        "perimeter_diff_m": round(perim_diff, 8),
        "max_coordinate_error_m": round(geom_dist, 8),
        "faces_generated": len(obs.faces or []),
        "tolerance_m": tolerance_m,
    }


def extract_building_footprints(geometries: Sequence[Any]) -> list[Polygon]:
    """Extract 2D Shapely Polygon footprints from obstacles, massing contracts, or GeoJSON dicts."""
    footprints: list[Polygon] = []

    for item in geometries:
        if isinstance(item, Polygon):
            if item.is_valid and not item.is_empty:
                footprints.append(item)
        elif isinstance(item, Obstacle):
            footprints.append(obstacle_to_2d_footprint(item))
        elif isinstance(item, dict):
            # GeoJSON Feature or geometry dict
            geom_dict = item.get("geometry", item)
            geom_type = geom_dict.get("type")
            if geom_type == "Polygon":
                coords = geom_dict.get("coordinates", [[]])[0]
                footprints.append(Polygon(coords))
            elif geom_type == "MultiPolygon":
                for poly_coords in geom_dict.get("coordinates", []):
                    footprints.append(Polygon(poly_coords[0]))
            elif "footprint" in item:
                fp_dict = item["footprint"]
                coords = fp_dict.get("coordinates", [[]])[0]
                footprints.append(Polygon(coords))
            elif "bounds" in item and item.get("kind") == "BOX_AABB":
                b = item["bounds"]
                footprints.append(Polygon([(b[0], b[1]), (b[3], b[1]), (b[3], b[4]), (b[0], b[4])]))
        elif hasattr(item, "footprint") and hasattr(item.footprint, "coordinates"):
            # BuildingMassing instance
            coords = item.footprint.coordinates[0]
            footprints.append(Polygon(coords))

    return [fp for fp in footprints if fp.is_valid and not fp.is_empty]


def massing_to_obstacles(
    buildings: Sequence[Any],
    source: str = "FIXTURE_ONLY",
) -> list[Obstacle]:
    """Convert platform BuildingMassing objects or dictionaries to 3D simulation Obstacles."""
    obstacles: list[Obstacle] = []

    for bldg in buildings:
        if isinstance(bldg, Obstacle):
            obstacles.append(bldg)
            continue

        if isinstance(bldg, dict):
            bldg_id = str(bldg.get("id", f"bldg_{len(obstacles)}"))
            height = float(bldg.get("height_m", 15.0))
            floors = bldg.get("floors", [])

            # Check if multi-level floor footprints are provided
            if floors and isinstance(floors, (list, tuple)):
                current_z = 0.0
                for fl_idx, floor in enumerate(floors):
                    fl_dict = floor if isinstance(floor, dict) else floor.model_dump()
                    fl_height = float(fl_dict.get("floor_height_m", height / len(floors)))
                    fl_geom = fl_dict.get("geometry", {})
                    coords = fl_geom.get("coordinates", [[]])[0] if isinstance(fl_geom, dict) else fl_geom.coordinates[0]
                    obs = footprint_to_obstacle(
                        footprint_coords=coords,
                        height_m=fl_height,
                        base_z=current_z,
                        obstacle_id=f"{bldg_id}_fl{fl_idx}",
                        source=source,
                    )
                    obstacles.append(obs)
                    current_z += fl_height
            else:
                geom = bldg.get("footprint") or bldg.get("geometry") or {}
                coords = geom.get("coordinates", [[]])[0] if isinstance(geom, dict) else geom.coordinates[0]
                obs = footprint_to_obstacle(
                    footprint_coords=coords,
                    height_m=height,
                    base_z=0.0,
                    obstacle_id=bldg_id,
                    source=source,
                )
                obstacles.append(obs)
        elif hasattr(bldg, "footprint") and hasattr(bldg, "height_m"):
            # BuildingMassing Pydantic model
            bldg_id = str(bldg.id)
            height = float(bldg.height_m)
            if getattr(bldg, "floors", None):
                current_z = 0.0
                for fl_idx, fl in enumerate(bldg.floors):
                    fl_height = float(fl.floor_height_m)
                    coords = fl.geometry.coordinates[0]
                    obs = footprint_to_obstacle(
                        footprint_coords=coords,
                        height_m=fl_height,
                        base_z=current_z,
                        obstacle_id=f"{bldg_id}_fl{fl_idx}",
                        source=source,
                    )
                    obstacles.append(obs)
                    current_z += fl_height
            else:
                coords = bldg.footprint.coordinates[0]
                obs = footprint_to_obstacle(
                    footprint_coords=coords,
                    height_m=height,
                    base_z=0.0,
                    obstacle_id=bldg_id,
                    source=source,
                )
                obstacles.append(obs)

    return obstacles


def supplement_missing_domain_features(
    geojson: dict[str, Any],
    *,
    site_area: BaseGeometry | None = None,
    water: BaseGeometry | None = None,
    site_properties: Mapping[str, Any] | None = None,
    water_properties: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add site and water only when the persisted scenario artifact omitted them.

    Existing site_area and water features stay as stored. The returned document
    is a copy; the artifact bytes and their hash are not rewritten.
    """
    if not isinstance(geojson, dict) or not isinstance(geojson.get("features"), list):
        raise ValueError("Formal scenario geometry must be a GeoJSON FeatureCollection")
    def geometry_mapping(geometry: BaseGeometry) -> dict[str, Any]:
        if geometry.is_empty:
            return {"type": "Polygon", "coordinates": []}
        return mapping(geometry)

    features = list(geojson["features"])
    roles = {
        feature.get("properties", {}).get("role")
        for feature in features
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict)
    }
    sources: dict[str, Any] = {}
    if "site_area" in roles:
        sources["site_area"] = "scenario_artifact"
    elif site_area is None:
        raise ValueError("Formal scenario geometry must include a site_area polygon")
    else:
        features.append({
            "type": "Feature",
            "geometry": geometry_mapping(site_area),
            "properties": {"role": "site_area", **dict(site_properties or {})},
        })
        sources["site_area"] = "approved_workspace_exploration_design_area"
    if "water" in roles:
        sources["water"] = "scenario_artifact"
    elif water is None:
        raise ValueError(
            "Formal scenario geometry must include a water geometry, including an empty geometry when absent"
        )
    else:
        features.append({
            "type": "Feature",
            "geometry": geometry_mapping(water),
            "properties": {"role": "water", **dict(water_properties or {})},
        })
        sources["water"] = "approved_workspace_bgt_waterdeel"
    return {**geojson, "features": features}, sources


def formal_scenario_geojson_to_environment(
    geojson: dict[str, Any],
    floor_estimates: Sequence[Mapping[str, Any]] = (),
) -> ScenarioEnvironmentGeometry:
    """Validate formal EPSG:28992 GeoJSON and extract building and public-space geometry.

    Formal geometry is already in RD New metres. Buildings are extruded only from
    their explicit ``height_m`` property; missing or invalid heights never receive
    a display default.
    """
    if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
        raise ValueError("Formal scenario geometry must be a GeoJSON FeatureCollection")
    crs_name = (
        geojson.get("crs", {}).get("properties", {}).get("name")
        if isinstance(geojson.get("crs"), dict)
        else None
    )
    if not isinstance(crs_name, str) or not crs_name.strip():
        raise ValueError("Formal scenario geometry must declare EPSG:28992")
    try:
        from pyproj import CRS

        epsg_code = CRS.from_user_input(crs_name).to_epsg()
    except Exception as exc:
        raise ValueError("Formal scenario geometry must declare EPSG:28992") from exc
    if epsg_code != 28992:
        raise ValueError("Formal scenario geometry must declare EPSG:28992")

    features = geojson.get("features")
    if not isinstance(features, list):
        raise ValueError("Formal scenario geometry features must be a list")

    obstacles: list[Obstacle] = []
    excluded_obstacles: list[dict[str, str]] = []
    site_areas: list[Polygon | MultiPolygon] = []
    water_geometries: list[BaseGeometry] = []
    public_space_building_footprints: list[Polygon | MultiPolygon] = []
    floor_estimate_by_building_id = {
        str(estimate.get("building_id")): estimate
        for estimate in floor_estimates
        if isinstance(estimate, Mapping) and estimate.get("building_id") is not None
    }
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"Formal scenario feature {index} is invalid")
        properties = feature.get("properties")
        geometry_doc = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry_doc, dict):
            raise ValueError(f"Formal scenario feature {index} is missing geometry or properties")
        role = properties.get("role")
        if role not in {"site_area", "water", "new_building", "retained", "primary_open_space"}:
            continue
        try:
            geometry = shape(geometry_doc)
        except Exception as exc:
            raise ValueError(f"Formal scenario feature {index} has invalid geometry") from exc
        if role == "water" and geometry.is_empty:
            water_geometries.append(geometry)
            continue
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(f"Formal scenario feature {index} has empty or invalid geometry")

        if role == "site_area":
            if not isinstance(geometry, (Polygon, MultiPolygon)):
                raise ValueError("site_area must be Polygon or MultiPolygon geometry")
            site_areas.append(geometry)
            continue

        if role == "water":
            if not isinstance(geometry, (Polygon, MultiPolygon)):
                raise ValueError("water must be Polygon or MultiPolygon geometry")
            water_geometries.append(geometry)
            continue

        if role == "primary_open_space":
            if not isinstance(geometry, (Polygon, MultiPolygon)):
                raise ValueError("primary_open_space must be Polygon or MultiPolygon geometry")
            continue

        if not isinstance(geometry, (Polygon, MultiPolygon)):
            raise ValueError(f"Building feature {index} must be Polygon or MultiPolygon geometry")
        public_space_building_footprints.append(geometry)
        building_id = str(properties.get("building_id") or feature.get("id") or f"feature-{index}")
        estimate = floor_estimate_by_building_id.get(building_id, {})
        height_estimate = properties.get("height_estimate")
        if not isinstance(height_estimate, Mapping):
            height_estimate = {}
        bag_status = height_estimate.get("bag_observed_status") or estimate.get("bag_observed_status")
        floor_count = height_estimate.get("floor_count", estimate.get("floor_count"))

        if role == "retained":
            normalized_bag_status = str(bag_status or "").strip().casefold()
            demolished = normalized_bag_status in {"pand gesloopt", "gesloopt", "demolished"}
            if demolished:
                excluded_obstacles.append({
                    "building_id": building_id,
                    "reason": f"BAG status '{bag_status}' identifies a demolished retained building; excluded as a sunlight obstacle.",
                })
                continue
            zero_floors = (
                isinstance(floor_count, (int, float))
                and not isinstance(floor_count, bool)
                and floor_count == 0
            ) or (
                isinstance(floor_count, Mapping)
                and floor_count.get("lower") == 0
                and floor_count.get("upper") == 0
            )
            if zero_floors:
                excluded_obstacles.append({
                    "building_id": building_id,
                    "reason": "Recorded floor-count evidence is 0..0; excluded as a sunlight obstacle.",
                })
                continue

        height_value = properties.get("height_m")
        if height_value is None:
            height_value = estimate.get("height_above_ground_m")
        if isinstance(height_value, bool) or not isinstance(height_value, (int, float)):
            if role == "retained":
                raise UnknownRetainedHeightError(building_id)
            raise ValueError(f"Building feature {index} ({building_id}) requires a numeric height_m")
        height_m = float(height_value)
        if not math.isfinite(height_m) or height_m <= 0.0:
            raise ValueError(f"Building feature {index} ({building_id}) height_m must be finite and greater than zero")

        polygons = list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]
        for part_index, polygon in enumerate(polygons):
            verify_geometry_roundtrip(polygon, height_m=height_m)
            feature_id = feature.get("id") or properties.get("building_id") or f"building-{index}"
            obstacle_id = str(feature_id) if len(polygons) == 1 else f"{feature_id}-{part_index}"
            obstacles.append(
                footprint_to_obstacle(
                    polygon,
                    height_m=height_m,
                    obstacle_id=obstacle_id,
                    source="FORMAL_SCENARIO_EPSG28992",
                )
            )

    if not site_areas:
        raise ValueError("Formal scenario geometry must include a site_area polygon")
    if not water_geometries:
        raise ValueError("Formal scenario geometry must include a water geometry, including an empty geometry when absent")
    site_area = unary_union(site_areas)
    water_geometry = unary_union(water_geometries)
    if site_area.is_empty or not site_area.is_valid or not isinstance(site_area, (Polygon, MultiPolygon)):
        raise ValueError("Formal scenario site_area union is invalid")
    if not water_geometry.is_empty and (
        not water_geometry.is_valid or not isinstance(water_geometry, (Polygon, MultiPolygon))
    ):
        raise ValueError("Formal scenario water union is invalid")

    excluded_areas = [water_geometry, *public_space_building_footprints]
    exclusion = unary_union([geometry for geometry in excluded_areas if not geometry.is_empty]) if any(
        not geometry.is_empty for geometry in excluded_areas
    ) else GeometryCollection()
    public_open_space = site_area.difference(exclusion)
    if public_open_space.is_empty or not public_open_space.is_valid or not isinstance(public_open_space, (Polygon, MultiPolygon)):
        raise ValueError("Formal scenario public-space domain is empty or invalid")
    return ScenarioEnvironmentGeometry(
        obstacles=tuple(obstacles),
        site_area=site_area,
        water_geometry=water_geometry,
        public_open_space=public_open_space,
        excluded_obstacles=tuple(excluded_obstacles),
    )
