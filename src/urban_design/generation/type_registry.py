"""Versioned geometry capabilities for morphology-dictionary type IDs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
import math
from types import MappingProxyType
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict
import shapely
from shapely.affinity import rotate
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from urban_design.morphology_dictionary import load_dictionary
from urban_design.generation.hashing import canonical_geometry_payload


def generate_block_profile(type_id, envelope, *, wing_depth_m):
    """S6 block-scale capability using catalogue identity, separate from W5 replay.

    Box-in-box needs a retained shell and clear-space survey, so no new-build
    operator is advertised for it. No unsupported legacy capability is promoted.
    """
    if type_id not in _default_type_registry().entries:
        raise UnsupportedMorphologyType(type_id)
    from urban_design.morphology.block_massing import block_profile
    return block_profile(type_id, envelope, wing_depth_m=wing_depth_m)


def generate_streetwall_profile(block, *, wing_depth_m, setback_m=1):
    if 'block.perimeter' not in _default_type_registry().entries:
        raise UnsupportedMorphologyType('block.perimeter')
    from urban_design.morphology.block_massing import streetwall_profile
    return streetwall_profile(block,wing_depth_m=wing_depth_m,setback_m=setback_m)


class BlockScaleCapability(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    type_id: str
    variant_id: str
    capability_state: str
    algorithm_version: str = 'j12-block-scale-v1'
    rule_card_ids: tuple[str,...]
    geometry_basis: str
    provenance: str = 'ASSUMED_COMMANDER DRAFT'


def block_scale_capabilities():
    """S6 capability namespace; does not promote W5's unsupported API paths."""
    specs=(('block.perimeter','MOR-003','actual block minus setback, courtyard erosion'),
           ('building.courtyard_closed','MOR-004','full block-fitted outer envelope and >=20m courtyard'),
           ('building.i_slab','MOR-005','30-80m complete bar; measured wing depth'),
           ('building.point_tower','MOR-006','400-900m2 mid-rise plate; D2 height bound'),
           ('building.rowhouse','MOR-007','6-20 units with measured frontage and depth'),
           ('building.podium_tower','MOR-008','two podium plates; setback upper plates'),
           ('building.l_block','MOR-010','connected L wings in complete envelope'),
           ('building.industrial_hall','POR-001','20-40m gross span study; structural/headroom survey unknown'))
    result=[BlockScaleCapability(type_id=id,variant_id='block-scaled',capability_state='SUPPORTED_DRAFT',rule_card_ids=(card,'MOR-001'),geometry_basis=basis) for id,card,basis in specs]
    result.append(BlockScaleCapability(type_id='building.industrial_hall',variant_id='box-in-box-retained-shell',
        capability_state='UNKNOWN_INTERNAL_SURVEY',rule_card_ids=('MOR-009','POR-013'),geometry_basis='retained shell unchanged; internal clear space, structure and loading required'))
    for entry in result:
        if entry.type_id not in _default_type_registry().entries:raise UnsupportedMorphologyType(entry.type_id)
    return tuple(result)


class CapabilityState(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class UnsupportedMorphologyType(ValueError):
    """Raised when no registered, semantically checked geometry exists."""


class InvalidMorphologyParameters(ValueError):
    """Raised when a supported profile request violates its geometry contract."""


class MorphologyCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type_id: str
    variant_id: str
    implementation_id: str | None
    algorithm_version: str | None
    capability_state: CapabilityState
    supported_capabilities: tuple[str, ...]
    unsupported_capabilities: tuple[str, ...]
    allowed_parameters: tuple[str, ...]
    required_parameters: tuple[str, ...]
    integer_parameters: tuple[str, ...]
    parameter_ranges: tuple[tuple[str, float, float], ...]
    range_basis: str = "EDITORIAL_ENVELOPE_V1"
    not_regulatory: bool = True
    range_source: str = "executor-defined engineering envelope; not human-approved constraints"
    semantic_test_ids: tuple[str, ...]
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class GeneratedMorphology:
    type_id: str
    variant_id: str
    implementation_id: str
    algorithm_version: str
    crs: str
    coordinate_unit: str
    parameters: Mapping[str, float | int]
    geometry: BaseGeometry


@dataclass(frozen=True)
class TypeRegistry:
    entries: Mapping[str, MorphologyCapability]


_UNSUPPORTED_REASON = "no versioned geometry adapter has been implemented and semantically tested for this type"
_SUPPORTED_PROFILE_CAPABILITIES = ("footprint_geometry",)
_UNSUPPORTED_PROFILE_CAPABILITIES = (
    "openings",
    "opening_orientation",
    "ground_upper_floor_range",
    "per_floor_height",
    "variable_comb_count",
    "public_access_policy",
)
_H_PARAMETERS = (
    "width_m",
    "depth_m",
    "left_wing_width_m",
    "right_wing_width_m",
    "thickness_m",
    "rotation_deg",
)
_H_REQUIRED = ("width_m", "depth_m", "left_wing_width_m", "right_wing_width_m", "thickness_m")
_E_PARAMETERS = ("width_m", "depth_m", "spine_thickness_m", "wing_thickness_m", "rotation_deg")
_E_REQUIRED = ("width_m", "depth_m", "spine_thickness_m", "wing_thickness_m")
_COMB_PARAMETERS = (
    "spine_length_m",
    "spine_thickness_m",
    "wing_depth_m",
    "wing_thickness_m",
    "wing_count",
    "gap_m",
    "rotation_deg",
)
_COMB_REQUIRED = tuple(parameter for parameter in _COMB_PARAMETERS if parameter != "rotation_deg")
_COMB_INTEGER_PARAMETERS = ("wing_count",)
# wing_depth_m 10–36 m is an executor-defined engineering value, not a dictionary field.
_COMB_PARAMETER_RANGES = (
    ("spine_length_m", 40.0, 120.0),
    ("wing_depth_m", 10.0, 36.0),
    ("wing_count", 2.0, 5.0),
    ("gap_m", 12.0, 30.0),
)
_IMPLEMENTATION_IDS = {
    "building.h_plan": "h_profile_v1",
    "building.e_plan": "e_profile_v1",
    "building.comb": "comb_profile_v1",
}
_SEMANTIC_TEST_IDS = {
    "building.h_plan": (
        "test_h_profile_is_not_a_one_sided_comb",
        "test_h_profile_matches_non_symmetric_dimensions",
        "test_h_profile_supports_rotate90_and_preserves_site_containment",
        "test_h_profile_rejects_retained_obstacle_that_disconnects_central_connector",
        "test_h_profile_removes_nonbreaking_retained_obstacle_and_preserves_semantics",
        "test_h_profile_rejects_invalid_wall_thickness_fail_closed",
    ),
    "building.e_plan": (
        "test_e_profile_is_one_spine_with_three_same_side_wings",
        "test_e_profile_rejects_obstacle_that_splits_the_required_spine",
        "test_e_profile_rejects_obstacle_that_removes_one_required_wing",
    ),
    "building.comb": (
        "test_comb_profile_matches_independent_reference_union_for_supported_wing_counts",
        "test_e_and_comb_three_are_equivalent_only_for_the_matching_dimension_layout",
        "test_comb_profile_rejects_obstacle_that_splits_the_required_spine",
    ),
}


@dataclass(frozen=True)
class _ProfileShape:
    geometry: BaseGeometry
    connector_name: str
    connector: BaseGeometry
    wings: tuple[tuple[str, BaseGeometry], ...]


_HANDLERS: dict[str, Callable[[BaseGeometry, Mapping[str, float | int]], _ProfileShape]] = {}


def build_type_registry(dictionary: Mapping[str, Any] | None = None) -> TypeRegistry:
    catalogue = dictionary if dictionary is not None else load_dictionary()
    raw_entries = catalogue.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("morphology dictionary must contain an entries list")
    ids = [entry.get("id") for entry in raw_entries if isinstance(entry, Mapping)]
    if len(ids) != len(raw_entries) or len(ids) != len(set(ids)):
        raise ValueError("morphology dictionary entries require unique type IDs")
    missing_supported_ids = set(_IMPLEMENTATION_IDS) - set(ids)
    if missing_supported_ids:
        raise ValueError(f"dictionary is missing registered geometry type IDs: {sorted(missing_supported_ids)}")
    entries: dict[str, MorphologyCapability] = {}
    for type_id in ids:
        implementation_id = _IMPLEMENTATION_IDS.get(type_id)
        if implementation_id == "h_profile_v1":
            allowed, required, version = _H_PARAMETERS, _H_REQUIRED, "morphology-profile-h-v1"
            supported_capabilities = _SUPPORTED_PROFILE_CAPABILITIES
            unsupported_capabilities = _UNSUPPORTED_PROFILE_CAPABILITIES
            integer_parameters, parameter_ranges, variant_id = (), (), "default"
        elif implementation_id == "e_profile_v1":
            allowed, required, version = _E_PARAMETERS, _E_REQUIRED, "morphology-profile-e-v1"
            supported_capabilities = _SUPPORTED_PROFILE_CAPABILITIES
            unsupported_capabilities = _UNSUPPORTED_PROFILE_CAPABILITIES
            integer_parameters, parameter_ranges, variant_id = (), (), "default"
        elif implementation_id == "comb_profile_v1":
            allowed, required, version = _COMB_PARAMETERS, _COMB_REQUIRED, "morphology-profile-comb-v1"
            supported_capabilities = (*_SUPPORTED_PROFILE_CAPABILITIES, "variable_comb_count")
            unsupported_capabilities = tuple(
                capability for capability in _UNSUPPORTED_PROFILE_CAPABILITIES if capability != "variable_comb_count"
            )
            integer_parameters, parameter_ranges, variant_id = (
                _COMB_INTEGER_PARAMETERS,
                _COMB_PARAMETER_RANGES,
                "variable-wing",
            )
        else:
            allowed, required, version = (), (), None
            supported_capabilities = ()
            unsupported_capabilities = ("footprint_geometry", *_UNSUPPORTED_PROFILE_CAPABILITIES)
            integer_parameters, parameter_ranges, variant_id = (), (), "default"
        supported = implementation_id is not None
        entries[type_id] = MorphologyCapability(
            type_id=type_id,
            variant_id=variant_id,
            implementation_id=implementation_id,
            algorithm_version=version,
            capability_state=CapabilityState.SUPPORTED if supported else CapabilityState.UNSUPPORTED,
            supported_capabilities=supported_capabilities,
            unsupported_capabilities=unsupported_capabilities,
            allowed_parameters=allowed,
            required_parameters=required,
            integer_parameters=integer_parameters,
            parameter_ranges=parameter_ranges,
            semantic_test_ids=_SEMANTIC_TEST_IDS.get(type_id, ()),
            unsupported_reason=None if supported else _UNSUPPORTED_REASON,
        )
    return TypeRegistry(entries=MappingProxyType(entries))


@lru_cache(maxsize=1)
def _default_type_registry() -> TypeRegistry:
    return build_type_registry()


def _positive_finite(parameters: Mapping[str, float | int], name: str) -> float:
    value = parameters[name]
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(float(value)) or value <= 0:
        raise InvalidMorphologyParameters(f"{name} must be a positive finite number")
    return float(value)


def _rotation(parameters: Mapping[str, float | int]) -> float:
    value = parameters.get("rotation_deg", 0.0)
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(float(value)):
        raise InvalidMorphologyParameters("rotation_deg must be a finite number")
    return float(value) % 360.0


def _centered_bounds(site: BaseGeometry, width: float, depth: float) -> tuple[float, float, float, float, float, float]:
    min_x, min_y, max_x, max_y = site.bounds
    center_x, center_y = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    return center_x - width / 2.0, center_y - depth / 2.0, center_x + width / 2.0, center_y + depth / 2.0, center_x, center_y


def _assemble_profile(
    connector_name: str,
    connector: BaseGeometry,
    wings: tuple[tuple[str, BaseGeometry], ...],
    *,
    rotation: float,
    center_x: float,
    center_y: float,
) -> _ProfileShape:
    def orient(geometry: BaseGeometry) -> BaseGeometry:
        return rotate(geometry, rotation, origin=(center_x, center_y), use_radians=False) if rotation else geometry

    oriented_connector = orient(connector)
    oriented_wings = tuple((name, orient(geometry)) for name, geometry in wings)
    geometry = unary_union((oriented_connector, *(item for _, item in oriented_wings)))
    return _ProfileShape(geometry, connector_name, oriented_connector, oriented_wings)


def _generate_h_profile(site: BaseGeometry, parameters: Mapping[str, float | int]) -> _ProfileShape:
    width = _positive_finite(parameters, "width_m")
    depth = _positive_finite(parameters, "depth_m")
    left_width = _positive_finite(parameters, "left_wing_width_m")
    right_width = _positive_finite(parameters, "right_wing_width_m")
    thickness = _positive_finite(parameters, "thickness_m")
    if thickness >= min(width, depth) / 2.0:
        raise InvalidMorphologyParameters("thickness_m must be less than half of the narrower H envelope dimension")
    gap = width - left_width - right_width
    if gap <= 0:
        raise InvalidMorphologyParameters("left_wing_width_m plus right_wing_width_m must leave a positive crossbar span")
    left, bottom, right, top, center_x, center_y = _centered_bounds(site, width, depth)
    left_wing = Polygon(((left, bottom), (left + left_width, bottom), (left + left_width, top), (left, top)))
    right_wing = Polygon(((right - right_width, bottom), (right, bottom), (right, top), (right - right_width, top)))
    crossbar = Polygon(
        (
            (left + left_width, center_y - thickness / 2.0),
            (right - right_width, center_y - thickness / 2.0),
            (right - right_width, center_y + thickness / 2.0),
            (left + left_width, center_y + thickness / 2.0),
        )
    )
    rotation = _rotation(parameters)
    return _assemble_profile(
        "central connector",
        crossbar,
        (("left wing", left_wing), ("right wing", right_wing)),
        rotation=rotation,
        center_x=center_x,
        center_y=center_y,
    )


def _generate_e_profile(site: BaseGeometry, parameters: Mapping[str, float | int]) -> _ProfileShape:
    width = _positive_finite(parameters, "width_m")
    depth = _positive_finite(parameters, "depth_m")
    spine_thickness = _positive_finite(parameters, "spine_thickness_m")
    wing_thickness = _positive_finite(parameters, "wing_thickness_m")
    if spine_thickness >= width / 2.0:
        raise InvalidMorphologyParameters("spine_thickness_m must be less than half of width_m")
    if wing_thickness >= depth / 3.0:
        raise InvalidMorphologyParameters("wing_thickness_m must leave a gap between the three E wings")
    left, bottom, right, top, center_x, center_y = _centered_bounds(site, width, depth)
    spine = Polygon(((left, bottom), (left + spine_thickness, bottom), (left + spine_thickness, top), (left, top)))
    wings = []
    for index in range(3):
        wing_center_y = bottom + depth * (index + 0.5) / 3.0
        wings.append(
            Polygon(
                (
                    (left + spine_thickness, wing_center_y - wing_thickness / 2.0),
                    (right, wing_center_y - wing_thickness / 2.0),
                    (right, wing_center_y + wing_thickness / 2.0),
                    (left + spine_thickness, wing_center_y + wing_thickness / 2.0),
                )
            )
        )
    rotation = _rotation(parameters)
    return _assemble_profile(
        "spine",
        spine,
        tuple((f"wing {index + 1}", wing) for index, wing in enumerate(wings)),
        rotation=rotation,
        center_x=center_x,
        center_y=center_y,
    )


def _generate_comb_profile(site: BaseGeometry, parameters: Mapping[str, float | int]) -> _ProfileShape:
    spine_length = _positive_finite(parameters, "spine_length_m")
    spine_thickness = _positive_finite(parameters, "spine_thickness_m")
    wing_depth = _positive_finite(parameters, "wing_depth_m")
    wing_thickness = _positive_finite(parameters, "wing_thickness_m")
    gap = _positive_finite(parameters, "gap_m")
    wing_count = parameters["wing_count"]
    if isinstance(wing_count, bool) or type(wing_count) is not int or not 2 <= wing_count <= 5:
        raise InvalidMorphologyParameters("wing_count must be a strict integer from 2 through 5")
    if spine_thickness >= wing_depth:
        raise InvalidMorphologyParameters("spine_thickness_m must be less than wing_depth_m")
    occupied_span = wing_count * wing_thickness + (wing_count - 1) * gap
    if occupied_span >= spine_length:
        raise InvalidMorphologyParameters("wing thickness and gaps must leave positive spine-end margins")

    min_x, min_y, max_x, max_y = site.bounds
    center_x, center_y = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    spine_left = center_x - spine_length / 2.0
    total_depth = spine_thickness + wing_depth
    spine_bottom = center_y - total_depth / 2.0
    spine_top = spine_bottom + spine_thickness
    spine = Polygon(
        (
            (spine_left, spine_bottom),
            (spine_left + spine_length, spine_bottom),
            (spine_left + spine_length, spine_top),
            (spine_left, spine_top),
        )
    )
    end_margin = (spine_length - occupied_span) / 2.0
    wings = []
    for index in range(wing_count):
        wing_center = spine_left + end_margin + wing_thickness / 2.0 + index * (wing_thickness + gap)
        wings.append(
            Polygon(
                (
                    (wing_center - wing_thickness / 2.0, spine_top),
                    (wing_center + wing_thickness / 2.0, spine_top),
                    (wing_center + wing_thickness / 2.0, spine_top + wing_depth),
                    (wing_center - wing_thickness / 2.0, spine_top + wing_depth),
                )
            )
        )
    return _assemble_profile(
        "spine",
        spine,
        tuple((f"wing {index + 1}", wing) for index, wing in enumerate(wings)),
        rotation=_rotation(parameters),
        center_x=center_x,
        center_y=center_y,
    )


_HANDLERS.update(
    {"h_profile_v1": _generate_h_profile, "e_profile_v1": _generate_e_profile, "comb_profile_v1": _generate_comb_profile}
)


def _validate_site_geometry(geometry: BaseGeometry) -> None:
    if not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty or not geometry.is_valid:
        raise InvalidMorphologyParameters("site_geometry must be a non-empty valid Polygon or MultiPolygon")
    coordinates = shapely.get_coordinates(geometry)
    if not all(math.isfinite(float(value)) for row in coordinates for value in row):
        raise InvalidMorphologyParameters("site_geometry coordinates must be finite")
    if not math.isfinite(float(geometry.area)) or geometry.area <= 0:
        raise InvalidMorphologyParameters("site_geometry must have positive finite area")


def _validated_parameters(capability: MorphologyCapability, parameters: Mapping[str, Any]) -> dict[str, float | int]:
    if not isinstance(parameters, Mapping):
        raise InvalidMorphologyParameters("parameters must be a mapping")
    extras = set(parameters) - set(capability.allowed_parameters)
    if extras:
        raise InvalidMorphologyParameters(f"unsupported parameter(s): {sorted(extras)}")
    missing = set(capability.required_parameters) - set(parameters)
    if missing:
        raise InvalidMorphologyParameters(f"required parameter(s) missing: {sorted(missing)}")
    result: dict[str, float | int] = {}
    for key, value in parameters.items():
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(float(value)):
            raise InvalidMorphologyParameters(f"{key} must be a finite number")
        if key in capability.integer_parameters:
            if type(value) is not int:
                raise InvalidMorphologyParameters(f"{key} must be a strict integer")
            result[key] = value
        else:
            result[key] = float(value)
    for name, minimum, maximum in capability.parameter_ranges:
        if name in result and not minimum <= result[name] <= maximum:
            raise InvalidMorphologyParameters(f"{name} must be within the registered range [{minimum}, {maximum}]")
    if "rotation_deg" in capability.allowed_parameters and "rotation_deg" not in result:
        result["rotation_deg"] = 0.0
    return result


# EDITORIAL engineering assumptions, not regulatory or human-approved constraints.
MIN_RETAINED_WIDTH_M = 3.0
MIN_CONNECTION_LENGTH_M = 3.0


def _validate_retained_width(remaining: Polygon, original: BaseGeometry, type_id: str, name: str) -> None:
    # Project into the original rectangular feature's long/transverse axes.
    corners = list(original.exterior.coords)
    segments = [(corners[i], corners[i + 1]) for i in range(4)]
    a, b = max(segments, key=lambda pair: math.dist(*pair))
    length = math.dist(a, b)
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    local = shapely.ops.transform(
        lambda x, y, z=None: ((x-a[0])*ux+(y-a[1])*uy, -(x-a[0])*uy+(y-a[1])*ux), remaining
    )
    xs = sorted(set(float(row[0]) for row in shapely.get_coordinates(local)))
    if xs[-1] - xs[0] < MIN_RETAINED_WIDTH_M:
        raise InvalidMorphologyParameters(f"{type_id} {name} retained width below EDITORIAL minimum")
    min_y, max_y = local.bounds[1], local.bounds[3]
    for left, right in zip(xs, xs[1:]):
        if right - left < 1e-10:
            continue
        # Linear polygon edges: check both interval limits and midpoint.
        for fraction in (1e-7, 0.5, 1-1e-7):
            x = left + (right-left)*fraction
            section = local.intersection(LineString([(x, min_y-1), (x, max_y+1)]))
            parts = section.geoms if hasattr(section, "geoms") else (section,)
            if any(part.length < MIN_RETAINED_WIDTH_M - 1e-8 for part in parts):
                raise InvalidMorphologyParameters(f"{type_id} {name} retained width below EDITORIAL minimum")


def _single_polygon_feature(geometry: BaseGeometry, type_id: str, feature_name: str) -> Polygon:
    if not isinstance(geometry, Polygon) or geometry.is_empty or not geometry.is_valid or geometry.area <= 0:
        raise InvalidMorphologyParameters(
            f"{type_id} obstacle removal destroys required semantic feature: {feature_name} must remain connected"
        )
    return geometry


def _validate_profile_semantics(
    profile: _ProfileShape,
    geometry: BaseGeometry,
    obstacle_union: BaseGeometry | None,
    type_id: str,
) -> None:
    connector = profile.connector if obstacle_union is None else profile.connector.difference(obstacle_union)
    connector = _single_polygon_feature(connector, type_id, profile.connector_name)
    _validate_retained_width(connector, profile.connector, type_id, profile.connector_name)
    for wing_name, wing in profile.wings:
        remaining_wing = wing if obstacle_union is None else wing.difference(obstacle_union)
        remaining_wing = _single_polygon_feature(remaining_wing, type_id, wing_name)
        _validate_retained_width(remaining_wing, wing, type_id, wing_name)
        shared_boundary = remaining_wing.boundary.intersection(connector.boundary)
        boundary_parts = shared_boundary.geoms if hasattr(shared_boundary, "geoms") else (shared_boundary,)
        if max((part.length for part in boundary_parts), default=0) < MIN_CONNECTION_LENGTH_M:
            raise InvalidMorphologyParameters(
                f"{type_id} obstacle removal disconnects required semantic feature: {wing_name} from {profile.connector_name}"
            )
    if not isinstance(geometry, Polygon) or geometry.is_empty or not geometry.is_valid:
        raise InvalidMorphologyParameters(
            f"{type_id} obstacle removal disconnects required semantic features"
        )


def generate_profile_geometry(
    type_id: str,
    site_geometry: BaseGeometry,
    parameters: Mapping[str, Any],
    *,
    crs: str,
    coordinate_unit: str,
    preserved_obstacles: tuple[BaseGeometry, ...] | list[BaseGeometry] = (),
    registry: TypeRegistry | None = None,
) -> GeneratedMorphology:
    capabilities = registry or _default_type_registry()
    capability = capabilities.entries.get(type_id)
    if capability is None:
        raise UnsupportedMorphologyType(f"unknown morphology type {type_id!r}")
    if capability.capability_state is CapabilityState.UNSUPPORTED:
        reason = capability.unsupported_reason or _UNSUPPORTED_REASON
        raise UnsupportedMorphologyType(f"{type_id}: {reason}")
    if crs != "EPSG:28992":
        raise InvalidMorphologyParameters("generation geometry requires horizontal CRS EPSG:28992")
    if coordinate_unit != "m":
        raise InvalidMorphologyParameters("coordinate unit must be metres (m)")
    implementation = capability.implementation_id
    if implementation is None or implementation not in _HANDLERS:
        raise UnsupportedMorphologyType(f"{type_id}: registered implementation is unavailable")
    _validate_site_geometry(site_geometry)
    resolved = _validated_parameters(capability, parameters)
    profile = _HANDLERS[implementation](site_geometry, resolved)
    geometry = profile.geometry
    if not geometry.is_valid or geometry.is_empty or not math.isfinite(float(geometry.area)) or geometry.area <= 0:
        raise InvalidMorphologyParameters(f"{type_id} generated empty or invalid geometry")
    if not site_geometry.covers(geometry):
        raise InvalidMorphologyParameters(f"{type_id} geometry does not fit inside site_geometry")
    obstacle_geometries = tuple(preserved_obstacles)
    for obstacle in obstacle_geometries:
        if not isinstance(obstacle, (Polygon, MultiPolygon)) or obstacle.is_empty or not obstacle.is_valid:
            raise InvalidMorphologyParameters("preserved obstacles must be valid polygon geometry")
    obstacle_union = unary_union(obstacle_geometries) if obstacle_geometries else None
    if obstacle_union is not None:
        geometry = geometry.difference(obstacle_union)
        if geometry.is_empty or not geometry.is_valid or geometry.area <= 0:
            raise InvalidMorphologyParameters(f"{type_id} has no usable geometry after preserving obstacles")
    _validate_profile_semantics(profile, geometry, obstacle_union, type_id)
    try:
        canonical_geometry_payload(geometry, crs=crs)
    except ValueError as error:
        raise InvalidMorphologyParameters(f"{type_id} geometry is not hashable: {error}") from error
    return GeneratedMorphology(
        type_id=type_id,
        variant_id=capability.variant_id,
        implementation_id=implementation,
        algorithm_version=capability.algorithm_version or "",
        crs=crs,
        coordinate_unit=coordinate_unit,
        parameters=MappingProxyType(resolved),
        geometry=geometry,
    )


__all__ = [
    "CapabilityState",
    "GeneratedMorphology",
    "InvalidMorphologyParameters",
    "MorphologyCapability",
    "TypeRegistry",
    "UnsupportedMorphologyType",
    "build_type_registry",
    "generate_profile_geometry",
]
