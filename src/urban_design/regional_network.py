"""Regional street network boundary checks, poly parsing, and buffer clipping (WC-3).

Deterministic spatial utilities:
- Parses Geofabrik / Osmosis .poly polygon boundary files into Shapely polygons.
- Reprojects polygon to EPSG:28992.
- Verifies StudyArea buffer containment against provincial boundaries (4km, 6km, 20km).
- Flags boundary edge-affected regions where requested expansion exceeds provincial extract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence
from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely.ops import transform as shapely_transform

# Standard transformer EPSG:4326 -> EPSG:28992
WGS84_TO_RDNEW = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True).transform

NetworkMode = Literal["pedestrian", "bicycle", "motor_vehicle"]

EXCLUDED_CONSTRUCTION_HIGHWAYS = {
    "construction",
    "proposed",
    "abandoned",
    "disused",
    "raceway",
    "corridor",
    "platform",
    "elevator",
}


def _tag(tags: Mapping[str, Any], key: str) -> str | None:
    if key in tags and tags[key] is not None:
        val = str(tags[key]).strip().casefold()
        return val if val else None
    return None


def evaluate_way_for_mode(tags: Mapping[str, Any], mode: str) -> tuple[bool, bool, str]:
    """Evaluate whether an OSM way is included in a given mode network per PD-20.

    Args:
        tags: OSM way tag mapping.
        mode: One of 'pedestrian', 'bicycle', or 'motor_vehicle'.

    Returns:
        tuple of (included, is_imputed, reason):
        - included: bool, True if way meets criteria for this mode.
        - is_imputed: bool, True if inclusion/exclusion relied on Dutch default traffic rules.
        - reason: str, human-readable rule justification.
    """
    highway = _tag(tags, "highway")
    if not highway:
        return False, False, "missing_highway_tag"

    if highway in EXCLUDED_CONSTRUCTION_HIGHWAYS:
        return False, False, f"construction_or_non_physical_{highway}"

    if mode == "pedestrian":
        # Dutch RVV / autoweg rule: pedestrians prohibited on motorways, trunks, and motorroads
        if highway in {"motorway", "motorway_link", "trunk", "trunk_link"}:
            return False, False, "motorway_or_trunk_autoweg_prohibits_pedestrians"
        if _tag(tags, "motorroad") in {"yes", "true", "1"}:
            return False, False, "motorroad_autoweg_prohibits_pedestrians"

        foot = _tag(tags, "foot")
        access = _tag(tags, "access")
        if foot == "no":
            return False, False, "foot_no"
        if access in {"no", "private"} and foot not in {"yes", "designated", "permissive"}:
            return False, False, "access_prohibited_without_foot_override"

        if highway == "cycleway":
            if foot in {"yes", "designated", "permissive"}:
                return True, False, "cycleway_with_explicit_foot_permission"
            return False, True, "cycleway_defaults_to_no_pedestrian_imputed"

        walkable_classes = {
            "footway", "pedestrian", "living_street", "residential",
            "unclassified", "service", "path", "steps", "track",
            "tertiary", "tertiary_link", "secondary", "secondary_link",
            "primary", "primary_link",
        }
        if highway in walkable_classes:
            is_imputed = (foot is None)
            return True, is_imputed, "walkable_highway_included"
        return False, False, f"highway_{highway}_not_walkable"

    elif mode == "bicycle":
        # Dutch RVV: bicycles prohibited on motorways, trunks, and autoweg
        if highway in {"motorway", "motorway_link", "trunk", "trunk_link"}:
            return False, False, "motorway_or_trunk_prohibits_bicycles"
        if _tag(tags, "motorroad") in {"yes", "true", "1"}:
            return False, False, "motorroad_autoweg_prohibits_bicycles"

        bicycle = _tag(tags, "bicycle")
        access = _tag(tags, "access")
        if bicycle == "no":
            return False, False, "bicycle_no"
        if bicycle == "use_sidepath":
            return False, False, "mandatory_sidepath_rvv_prohibits_carriageway"
        if access in {"no", "private"} and bicycle not in {"yes", "designated", "permissive"}:
            return False, False, "access_prohibited_without_bicycle_override"

        # Fietsstraat (priority cycle street)
        if _tag(tags, "cyclestreet") in {"yes", "true", "1"} or _tag(tags, "bicycle_road") in {"yes", "true", "1"}:
            return True, False, "fietsstraat_included"

        if highway == "cycleway":
            return True, False, "cycleway_included"

        if highway in {"path", "footway", "pedestrian", "steps"}:
            if bicycle in {"yes", "designated", "permissive"}:
                return True, False, "path_or_footway_with_bicycle_permission"
            return False, True, "footway_or_pedestrian_defaults_to_no_bicycle_imputed"

        if highway in {"secondary", "secondary_link", "primary", "primary_link"}:
            cw_tags = [
                _tag(tags, "cycleway"),
                _tag(tags, "cycleway:both"),
                _tag(tags, "cycleway:left"),
                _tag(tags, "cycleway:right"),
            ]
            if any(t in {"separate", "track"} for t in cw_tags):
                return False, False, "separate_sidepath_prohibits_carriageway_cycling"
            is_imputed = (bicycle is None)
            return True, is_imputed, "secondary_primary_without_sidepath"

        general_classes = {
            "residential", "living_street", "unclassified",
            "tertiary", "tertiary_link", "service",
        }
        if highway in general_classes:
            is_imputed = (bicycle is None)
            return True, is_imputed, "general_road_bicycle_permitted"
        return False, False, f"highway_{highway}_not_cyclable"

    elif mode == "motor_vehicle":
        if highway in {"pedestrian", "footway", "cycleway", "path", "steps", "track", "bridleway"}:
            return False, False, "non_motor_infrastructure"

        if highway == "service":
            service_type = _tag(tags, "service")
            if service_type in {"driveway", "parking_aisle", "drive-through"}:
                return False, False, f"service_{service_type}_excluded"

        motor_vehicle = _tag(tags, "motor_vehicle")
        motorcar = _tag(tags, "motorcar")
        access = _tag(tags, "access")
        bus = _tag(tags, "bus")
        if motor_vehicle in {"no", "private"} or motorcar in {"no", "private"}:
            return False, False, "motor_vehicle_prohibited"
        if access in {"no", "private"}:
            if motor_vehicle not in {"yes", "permissive"} and motorcar not in {"yes", "permissive"}:
                return False, False, "access_prohibited_without_motor_vehicle_override"

        # Bus-only infrastructure
        if highway == "bus_guideway":
            return False, False, "bus_guideway_excluded"
        if (access == "no" or motor_vehicle == "no") and bus in {"yes", "designated"}:
            return False, False, "bus_only_excluded"

        car_classes = {
            "motorway", "motorway_link", "trunk", "trunk_link",
            "primary", "primary_link", "secondary", "secondary_link",
            "tertiary", "tertiary_link", "unclassified", "residential",
            "living_street", "service",
        }
        if highway in car_classes:
            is_imputed = (motor_vehicle is None and motorcar is None)
            return True, is_imputed, "motor_road_included"
        return False, False, f"highway_{highway}_not_for_cars"

    raise ValueError(f"Unknown network mode: {mode}. Must be 'pedestrian', 'bicycle', or 'motor_vehicle'.")


def parse_poly_file(content_or_path: str | Path) -> MultiPolygon | Polygon:
    """Parse an Osmosis / Geofabrik .poly format string or file into a Shapely geometry in EPSG:4326."""
    try:
        p = Path(content_or_path)
        if p.is_file():
            text = p.read_text(encoding="utf-8")
        else:
            text = str(content_or_path)
    except OSError:
        text = str(content_or_path)

    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError("Empty .poly content")

    # .poly format:
    # polygon_name
    # section_1 (e.g. 1 or !1 for hole)
    #    lon lat
    #    ...
    # END
    # END
    polygons: list[Polygon] = []
    current_ring: list[tuple[float, float]] = []
    is_in_ring = False
    is_hole = False

    outer_rings: list[list[tuple[float, float]]] = []
    inner_rings: list[list[tuple[float, float]]] = []

    for line in lines[1:]:  # Skip polygon title
        if line == "END":
            if is_in_ring:
                if len(current_ring) >= 3:
                    if is_hole:
                        inner_rings.append(current_ring)
                    else:
                        outer_rings.append(current_ring)
                current_ring = []
                is_in_ring = False
            continue

        if not is_in_ring:
            # Starting a section
            is_hole = line.startswith("!")
            is_in_ring = True
            current_ring = []
            continue

        # Coordinate line: lon lat (e.g. "  4.123456   51.123456")
        parts = line.split()
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                current_ring.append((lon, lat))
            except ValueError:
                continue

    if not outer_rings:
        raise ValueError("No valid polygon rings found in .poly file")

    # Construct polygons
    constructed: list[Polygon] = []
    for outer in outer_rings:
        # Match holes that fall inside outer (for single outer, all inner)
        constructed.append(Polygon(shell=outer, holes=inner_rings))

    if len(constructed) == 1:
        return constructed[0]
    return MultiPolygon(constructed)


def poly_to_rd_new(geom_wgs84: Polygon | MultiPolygon) -> Polygon | MultiPolygon:
    """Reproject WGS84 polygon/multipolygon to EPSG:28992 (RD New)."""
    return shapely_transform(WGS84_TO_RDNEW, geom_wgs84)


def assess_boundary_clearance(
    study_area_geom: Any,
    buffer_distance_m: float,
    provincial_boundary_rd_new: Polygon | MultiPolygon,
) -> dict[str, Any]:
    """Assess whether a StudyArea expansion buffer is fully contained by the provincial boundary.

    Returns:
    - buffer_distance_m: requested buffer radius
    - is_fully_contained: bool
    - clearance_m: minimum distance from StudyArea to provincial boundary
    - buffer_area_m2: total area of requested buffer
    - outside_area_m2: area of requested buffer extending outside provincial boundary
    - outside_ratio: ratio of outside area to buffer area
    - readiness: VALIDATED_COVERAGE or EDGE_AFFECTED_EXTENDS_BEYOND_PROVINCE
    """
    study_area = shape(study_area_geom) if isinstance(study_area_geom, dict) else study_area_geom
    if study_area.is_empty:
        raise ValueError("study_area_geom cannot be empty")

    buffer_geom = study_area.buffer(buffer_distance_m)
    is_contained = provincial_boundary_rd_new.contains(buffer_geom)

    clearance_m = float(study_area.distance(provincial_boundary_rd_new.boundary))
    buffer_area = float(buffer_geom.area)

    outside_geom = buffer_geom.difference(provincial_boundary_rd_new)
    outside_area = float(outside_geom.area) if not outside_geom.is_empty else 0.0
    outside_ratio = outside_area / buffer_area if buffer_area > 0 else 0.0

    readiness = "VALIDATED_COVERAGE" if is_contained else "EDGE_AFFECTED_EXTENDS_BEYOND_PROVINCE"
    limitations = (
        f"Buffer of {buffer_distance_m:.0f}m is fully contained within provincial boundary (clearance {clearance_m:.1f}m)."
        if is_contained
        else f"Buffer of {buffer_distance_m:.0f}m exceeds provincial boundary by {outside_area / 1e6:.2f} km² ({outside_ratio * 100:.1f}%). Segments near provincial border are edge-affected."
    )

    return {
        "buffer_distance_m": buffer_distance_m,
        "is_fully_contained": is_contained,
        "provincial_clearance_m": round(clearance_m, 2),
        "buffer_area_m2": round(buffer_area, 2),
        "outside_area_m2": round(outside_area, 2),
        "outside_ratio": round(outside_ratio, 4),
        "readiness": readiness,
        "limitations": limitations,
    }
