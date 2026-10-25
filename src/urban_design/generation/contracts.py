"""Fixture-safe, serializable contracts for staged morphology generation.

The analysis and design-brief references below are deliberately minimal. Their
field names are an interface boundary only: 待 A2 凍結後對齊。This module does
not import A2 implementation code.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
import shapely
from shapely.geometry import shape


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _FrozenDict(dict):
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("contract JSON mappings are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenDict({key: _deep_freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(child) for child in value)
    return value


class GenerationClass(str, Enum):
    EXPLORATORY = "EXPLORATORY"
    APPROVED_INPUTS = "APPROVED_INPUTS"


class MethodSourceKind(str, Enum):
    REGISTERED_DETERMINISTIC_METHOD = "REGISTERED_DETERMINISTIC_METHOD"
    PROJECT_DATA = "PROJECT_DATA"
    ILLUSTRATIVE_FIXTURE = "ILLUSTRATIVE_FIXTURE"


class AssumptionSourceKind(str, Enum):
    PROJECT_DATA = "PROJECT_DATA"
    HUMAN_DECISION = "HUMAN_DECISION"
    EXPLICIT_ASSUMPTION = "EXPLICIT_ASSUMPTION"
    ILLUSTRATIVE_FIXTURE = "ILLUSTRATIVE_FIXTURE"
    MODEL_PROPOSAL = "MODEL_PROPOSAL"
    RESEARCH_REFERENCE = "RESEARCH_REFERENCE"


class StageStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_RUN = "NOT_RUN"


class FrozenRef(_ContractModel):
    """Small immutable ref interface; analysis/brief details await A2 freeze."""

    id: str
    sha256: str
    kind: str

    @field_validator("id", "kind")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reference id and kind must be non-empty")
        return value.strip()

    @field_validator("sha256")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("reference sha256 must use sha256:<64 lowercase hex characters>")
        return value


class MethodProvenance(_ContractModel):
    method_id: str
    version: str
    description: str
    source_kind: MethodSourceKind
    source_refs: tuple[FrozenRef, ...] = ()

    @model_validator(mode="after")
    def require_source_refs(self):
        if self.source_kind.value in {"PROJECT_DATA", "HUMAN_DECISION"} and not self.source_refs:
            raise ValueError("PROJECT_DATA/HUMAN_DECISION requires non-empty source_refs")
        return self

    @field_validator("method_id", "version", "description")
    @classmethod
    def method_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("method identity, version, and description must be non-empty")
        return value.strip()


class AssumptionSpec(_ContractModel):
    id: str
    statement: str
    source_kind: AssumptionSourceKind
    source_refs: tuple[FrozenRef, ...] = ()

    @model_validator(mode="after")
    def require_source_refs(self):
        if self.source_kind.value in {"PROJECT_DATA", "HUMAN_DECISION"} and not self.source_refs:
            raise ValueError("PROJECT_DATA/HUMAN_DECISION requires non-empty source_refs")
        return self

    @field_validator("id", "statement")
    @classmethod
    def assumption_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("assumption id and statement must be non-empty")
        return value.strip()


def _finite_json(value: Any, path: str = "value") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite JSON numbers")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _finite_json(child, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            _finite_json(child, f"{path}.{key}")
        return
    raise ValueError(f"{path} must contain JSON-compatible values")


class CoordinateTransformAudit(_ContractModel):
    """Inspectable transform lineage; this contract does not execute transforms."""

    source_crs: str
    target_crs: Literal["EPSG:28992"]
    forward_operation_id: str
    inverse_operation_id: str
    axis_order: Literal["xy"]
    horizontal_unit: Literal["m"]
    source_ref: FrozenRef
    output_ref: FrozenRef
    roundtrip_check_ref: FrozenRef
    roundtrip_status: StageStatus
    roundtrip_sample_count: StrictInt = 0
    max_roundtrip_error_m: float | None = None
    tolerance_m: float | None = None

    @field_validator("source_crs", "forward_operation_id", "inverse_operation_id")
    @classmethod
    def transform_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("transform CRS and registered operation IDs must be non-empty")
        return value.strip()

    @field_validator("roundtrip_sample_count")
    @classmethod
    def nonnegative_sample_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("roundtrip_sample_count must be non-negative")
        return value

    @field_validator("max_roundtrip_error_m", "tolerance_m")
    @classmethod
    def finite_nonnegative_measurement(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not math.isfinite(float(value)) or value < 0:
            raise ValueError("roundtrip measurements must be finite and non-negative")
        return float(value)

    @model_validator(mode="after")
    def verified_roundtrip_has_evidence(self) -> "CoordinateTransformAudit":
        if self.roundtrip_status is StageStatus.PASS:
            if self.roundtrip_sample_count < 1 or self.max_roundtrip_error_m is None or self.tolerance_m is None:
                raise ValueError("PASS roundtrip requires samples, measured error, and tolerance")
            if self.tolerance_m <= 0 or self.max_roundtrip_error_m > self.tolerance_m:
                raise ValueError("PASS roundtrip error must be within its positive tolerance")
        return self


class LocalWorldTransform(_ContractModel):
    """Persisted rigid 2D world→local transform and checked local→world inverse.

    This is engineering arithmetic, not a CRS reprojection or approval audit.
    Matrix rows act on column [x, y, 1]. Tolerances are fixed by this version;
    callers cannot enlarge them to make a wrong inverse valid.
    """

    forward: tuple[tuple[float, float, float], tuple[float, float, float]]
    inverse: tuple[tuple[float, float, float], tuple[float, float, float]]
    direction: Literal["world_to_local"] = "world_to_local"
    inverse_direction: Literal["local_to_world"] = "local_to_world"
    source_frame: Literal["world"] = "world"
    target_frame: Literal["local"] = "local"
    world_crs: Literal["EPSG:28992"] = "EPSG:28992"
    coordinate_unit: Literal["m"] = "m"
    axis_order: Literal["xy"] = "xy"
    version: Literal["local-rigid-2d-v1"] = "local-rigid-2d-v1"
    tolerance_version: Literal["local-transform-tolerance-v1"] = "local-transform-tolerance-v1"
    tolerance_m: Literal[1e-9] = 1e-9
    linear_tolerance: Literal[1e-12] = 1e-12

    @field_validator("forward", "inverse", mode="before")
    @classmethod
    def finite_matrix(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("matrix must have exactly two rows")
        for row in value:
            if not isinstance(row, (list, tuple)) or len(row) != 3:
                raise ValueError("matrix rows must have exactly three columns")
            for number in row:
                if isinstance(number, bool) or not isinstance(number, (int, float)):
                    raise ValueError("matrix entries must be finite numeric values, not bool")
                try:
                    finite = math.isfinite(number)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError("matrix entries must be finite")
        return value

    @field_validator("tolerance_m", "linear_tolerance", mode="before")
    @classmethod
    def numeric_tolerance(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("tolerance cannot be bool")
        return value

    @model_validator(mode="after")
    def rigid_and_inverse(self) -> "LocalWorldTransform":
        for matrix in (self.forward, self.inverse):
            (a, b, _), (c, d, _) = matrix
            # SO(2): unit orthogonal columns and determinant +1; no reflection.
            values = (a*a+c*c-1, b*b+d*d-1, a*b+c*d, a*d-b*c-1)
            if any(not math.isfinite(v) or abs(v) > self.linear_tolerance for v in values):
                raise ValueError("matrix must be nonsingular rotation/translation without scale or shear")
        (a, b, tx), (c, d, ty) = self.forward
        determinant = a*d-b*c
        ia, ib, ic, id_ = d/determinant, -b/determinant, -c/determinant, a/determinant
        derived = ((ia, ib, -(ia*tx+ib*ty)), (ic, id_, -(ic*tx+id_*ty)))
        for row in range(2):
            for col in range(3):
                tolerance = self.tolerance_m if col == 2 else self.linear_tolerance
                error = self.inverse[row][col] - derived[row][col]
                if not math.isfinite(error) or abs(error) > tolerance:
                    raise ValueError("supplied inverse disagrees with deterministic inverse")
        # Check both compositions, including translation cancellation in metres.
        for left, right in ((self.forward, self.inverse), (self.inverse, self.forward)):
            for row in range(2):
                for col in range(3):
                    actual = left[row][0]*right[0][col] + left[row][1]*right[1][col]
                    if col == 2:
                        actual += left[row][2]
                    expected = 1.0 if row == col else 0.0
                    tolerance = self.tolerance_m if col == 2 else self.linear_tolerance
                    if not math.isfinite(actual) or abs(actual-expected) > tolerance:
                        raise ValueError("inverse composition is outside engineering tolerance")
        return self

    def _map_point(self, matrix: tuple, point: Any) -> tuple[float, float]:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("point must contain exactly two finite coordinates")
        for value in point:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("point coordinates must be finite numbers, not bool")
        result = tuple(row[0]*point[0] + row[1]*point[1] + row[2] for row in matrix)
        if not all(math.isfinite(value) for value in result):
            raise ValueError("mapped point is nonfinite")
        return result

    def world_to_local(self, point: Any) -> tuple[float, float]:
        return self._map_point(self.forward, point)

    def local_to_world(self, point: Any) -> tuple[float, float]:
        return self._map_point(self.inverse, point)


class GenerationContext(_ContractModel):
    """Frozen refs and calculation inputs; A2 alignment is pending freeze."""

    workspace_ref: FrozenRef
    analysis_ref: FrozenRef
    brief_ref: FrozenRef
    source_refs: tuple[FrozenRef, ...] = ()
    constraint_refs: tuple[FrozenRef, ...] = ()
    crs: str
    coordinate_unit: Literal["m"]
    seed: StrictInt
    method_parameters: dict[str, Any] = Field(default_factory=dict)
    assumptions: tuple[AssumptionSpec, ...] = ()
    coordinate_transforms: tuple[CoordinateTransformAudit, ...] = ()
    # None declares geometry is already world-coordinate geometry; it is not proof
    # that a caller-applied transform was checked. Applied local transforms must persist here.
    local_world_transform: LocalWorldTransform | None = None
    generation_class: GenerationClass

    @field_validator("crs")
    @classmethod
    def projected_crs(cls, value: str) -> str:
        if value != "EPSG:28992":
            raise ValueError("generation geometry requires EPSG:28992 coordinates")
        return value

    @field_validator("method_parameters")
    @classmethod
    def finite_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        _finite_json(value, "method_parameters")
        return _deep_freeze(value)

    @model_validator(mode="after")
    def parameter_provenance(self):
        basis_ids = {item.id for item in self.assumptions} | {ref.id for ref in self.source_refs}
        basis_ids |= {ref.id for item in self.assumptions for ref in item.source_refs}
        missing = set(self.method_parameters) - basis_ids
        if missing:
            raise ValueError(f"method_parameters keys require assumption or source IDs: {sorted(missing)}")
        return self


class StrategyReason(_ContractModel):
    refs: tuple[FrozenRef, ...] = ()
    text: str

    @field_validator("text")
    @classmethod
    def reason_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("strategy reason must be non-empty")
        return value.strip()


class StrategySpec(_ContractModel):
    strategy_id: str
    topology_family: str
    registered_method: MethodProvenance
    intent_ids: tuple[str, ...] = ()
    entry_refs: tuple[FrozenRef, ...] = ()
    open_space_hierarchy: tuple[str, ...] = ()
    height_policy: dict[str, Any] = Field(default_factory=dict)
    program_policy: dict[str, Any] = Field(default_factory=dict)
    permitted_type_ids: tuple[str, ...] = ()
    reasons: tuple[StrategyReason, ...] = ()

    @field_validator("strategy_id", "topology_family")
    @classmethod
    def registered_identity_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("strategy identity and topology family must be non-empty registry references")
        return value.strip()

    @field_validator("height_policy", "program_policy")
    @classmethod
    def declarative_json_policy(cls, value: dict[str, Any]) -> dict[str, Any]:
        _finite_json(value, "strategy policy")
        return _deep_freeze(value)

    @model_validator(mode="after")
    def method_is_registered_deterministic_data(self) -> "StrategySpec":
        if self.registered_method.source_kind is not MethodSourceKind.REGISTERED_DETERMINISTIC_METHOD:
            raise ValueError("strategy semantics must reference a registered deterministic method")
        return self


class GeometryValue(_ContractModel):
    type: Literal["Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"]
    coordinates: tuple[Any, ...]
    crs: str = "EPSG:28992"

    @field_validator("crs")
    @classmethod
    def canonical_crs(cls, value: str) -> str:
        if value != "EPSG:28992":
            raise ValueError("generation geometry requires EPSG:28992 coordinates")
        return value

    @field_validator("coordinates", mode="before")
    @classmethod
    def immutable_coordinates(cls, value: Any) -> tuple[Any, ...]:
        frozen = _deep_freeze(value)
        if not isinstance(frozen, tuple):
            raise ValueError("geometry coordinates must be an array")
        return frozen

    @model_validator(mode="after")
    def valid_geojson_geometry(self) -> "GeometryValue":
        try:
            geometry = shape({"type": self.type, "coordinates": self.coordinates})
        except Exception as error:
            raise ValueError(f"geometry coordinates are invalid: {error}") from error
        if geometry.is_empty:
            raise ValueError("geometry must be non-empty and valid")
        coordinates = shapely.get_coordinates(geometry)
        if not all(math.isfinite(float(value)) for row in coordinates for value in row):
            raise ValueError("geometry coordinates must be finite")
        if not geometry.is_valid:
            raise ValueError("geometry must be non-empty and valid")
        if self.type in {"Polygon", "MultiPolygon"} and (not math.isfinite(float(geometry.area)) or geometry.area <= 0):
            raise ValueError("polygon geometry must have positive finite area")
        return self


class LinearGeometryValue(GeometryValue):
    type: Literal["LineString", "MultiLineString"]

    @model_validator(mode="after")
    def noncollapsed_linear_geometry(self) -> "LinearGeometryValue":
        geometry = shape({"type": self.type, "coordinates": self.coordinates})
        if not math.isfinite(float(geometry.length)) or geometry.length <= 0:
            raise ValueError("linear geometry must have positive finite length")
        return self


class AreaGeometryValue(GeometryValue):
    type: Literal["Polygon", "MultiPolygon"]


class PointGeometryValue(GeometryValue):
    type: Literal["Point"]


class ValidationCheck(_ContractModel):
    check_id: str
    status: StageStatus
    detail: str
    refs: tuple[FrozenRef, ...] = ()


class ValidationReport(_ContractModel):
    geometry_status: StageStatus
    topology_status: StageStatus
    constraint_status: StageStatus
    checks: tuple[ValidationCheck, ...]
    unknowns: tuple[str, ...]
    failures: tuple[str, ...]


class AccessStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    PUBLIC = "PUBLIC"
    NON_PUBLIC = "NON_PUBLIC"


class AccessPolicy(_ContractModel):
    """Explicit access-policy record kept separate from open-space geometry."""

    status: AccessStatus
    source_refs: tuple[FrozenRef, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def classified_access_has_source(self) -> "AccessPolicy":
        if self.status is not AccessStatus.UNKNOWN and not self.source_refs:
            raise ValueError("classified public-access policy requires source references")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("access-policy reason must be non-empty when supplied")
        return self


class OpenSpaceArtifact(_ContractModel):
    id: str
    geometry: AreaGeometryValue
    access_policy: AccessPolicy


class SkeletonNode(_ContractModel):
    id: str
    geometry: PointGeometryValue
    level: StrictInt
    access: str
    source_refs: tuple[FrozenRef, ...] = ()

    @field_validator("id", "access")
    @classmethod
    def node_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("node id and access status must be non-empty")
        return value.strip()


class StageArtifact(_ContractModel):
    artifact_id: str
    context_hash: str
    input_refs: tuple[FrozenRef, ...]
    seed: StrictInt
    algorithm_version: str
    method: MethodProvenance
    assumptions: tuple[AssumptionSpec, ...]
    created_at: datetime

    @field_validator("context_hash")
    @classmethod
    def valid_context_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("context_hash must use sha256:<64 lowercase hex characters>")
        return value

    @field_validator("artifact_id", "algorithm_version")
    @classmethod
    def artifact_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("artifact identity and algorithm version must be non-empty")
        return value.strip()

    @field_validator("created_at")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


class SkeletonEdge(_ContractModel):
    id: str
    from_node_id: str
    to_node_id: str
    geometry: LinearGeometryValue
    level: StrictInt
    access: str
    width_m: float | None = None
    width_ref: FrozenRef | None = None
    source_refs: tuple[FrozenRef, ...] = ()

    @field_validator("id", "from_node_id", "to_node_id", "access")
    @classmethod
    def edge_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("edge identity, endpoint IDs, and access status must be non-empty")
        return value.strip()

    @field_validator("width_m")
    @classmethod
    def positive_finite_width(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not math.isfinite(float(value)) or value <= 0:
            raise ValueError("width_m must be positive and finite")
        return float(value)

    @model_validator(mode="after")
    def width_has_provenance(self) -> "SkeletonEdge":
        if (self.width_m is None) != (self.width_ref is None):
            raise ValueError("width_m and width_ref must be supplied together")
        if self.from_node_id == self.to_node_id:
            raise ValueError("edge endpoints must reference distinct nodes")
        return self


# Kept as a descriptive alias for callers that model a road edge specifically.
RoadArtifact = SkeletonEdge


class ConnectionRecord(_ContractModel):
    id: str
    from_node_id: str
    to_node_id: str
    level: StrictInt
    status: str
    source_refs: tuple[FrozenRef, ...] = ()


class SkeletonArtifact(StageArtifact):
    nodes: tuple[SkeletonNode, ...]
    edges: tuple[SkeletonEdge, ...]
    primary_open_spaces: tuple[OpenSpaceArtifact, ...]
    retained_geometry_refs: tuple[FrozenRef, ...]
    connections: tuple[ConnectionRecord, ...]
    validation: ValidationReport

    @model_validator(mode="after")
    def graph_references_resolve(self) -> "SkeletonArtifact":
        node_ids = [node.id for node in self.nodes]
        edge_ids = [edge.id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("skeleton node IDs must be unique")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("skeleton edge IDs must be unique")
        node_set = set(node_ids)
        for edge in self.edges:
            if edge.from_node_id not in node_set or edge.to_node_id not in node_set:
                raise ValueError("skeleton edge endpoint must reference an included node")
        for connection in self.connections:
            if connection.from_node_id not in node_set or connection.to_node_id not in node_set:
                raise ValueError("skeleton connection endpoint must reference an included node")
        return self


class ProgramBlock(_ContractModel):
    id: str
    geometry: AreaGeometryValue


class ProgramZone(_ContractModel):
    id: str
    geometry: AreaGeometryValue
    use: str


class FrontageRecord(_ContractModel):
    block_id: str
    road_id: str
    edge: LinearGeometryValue
    road_class: str


class ProgramAllocation(_ContractModel):
    zone_id: str
    use: str
    area_m2: float
    source_refs: tuple[FrozenRef, ...] = ()

    @field_validator("area_m2")
    @classmethod
    def positive_program_area(cls, value: float) -> float:
        if isinstance(value, bool) or not math.isfinite(float(value)) or value <= 0:
            raise ValueError("program area_m2 must be positive and finite")
        return float(value)


class UnallocatedArea(_ContractModel):
    geometry: AreaGeometryValue
    area_m2: float
    reason: str

    @field_validator("area_m2")
    @classmethod
    def positive_unallocated_area(cls, value: float) -> float:
        if isinstance(value, bool) or not math.isfinite(float(value)) or value <= 0:
            raise ValueError("unallocated area_m2 must be positive and finite")
        return float(value)

    @field_validator("reason")
    @classmethod
    def nonempty_unallocated_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("unallocated area reason must be non-empty")
        return value.strip()


class BlockProgramArtifact(StageArtifact):
    parent_skeleton_ref: FrozenRef
    blocks: tuple[ProgramBlock, ...]
    zones: tuple[ProgramZone, ...]
    frontages: tuple[FrontageRecord, ...]
    program_allocations: tuple[ProgramAllocation, ...]
    unallocated_areas: tuple[UnallocatedArea, ...]


class FloorGeometry(_ContractModel):
    level: StrictInt
    geometry: AreaGeometryValue
    floor_height_m: float
    use: str

    @field_validator("floor_height_m")
    @classmethod
    def positive_finite_floor_height(cls, value: float) -> float:
        if isinstance(value, bool) or not math.isfinite(float(value)) or value <= 0:
            raise ValueError("floor_height_m must be positive and finite")
        return float(value)

    @field_validator("use")
    @classmethod
    def nonempty_floor_use(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("floor use must be non-empty")
        return value.strip()


class BuildingMassing(_ContractModel):
    id: str
    footprint: AreaGeometryValue
    floors: tuple[FloorGeometry, ...]
    height_m: float
    use: str
    type_id: str
    variant_id: str

    @field_validator("height_m")
    @classmethod
    def positive_finite_building_height(cls, value: float) -> float:
        if isinstance(value, bool) or not math.isfinite(float(value)) or value <= 0:
            raise ValueError("building height_m must be positive and finite")
        return float(value)


class MassingArtifact(StageArtifact):
    parent_block_ref: FrozenRef
    buildings: tuple[BuildingMassing, ...]
    retained_refs: tuple[FrozenRef, ...]
    validation: ValidationReport


__all__ = [
    "AssumptionSourceKind",
    "AssumptionSpec",
    "AreaGeometryValue",
    "AccessPolicy",
    "AccessStatus",
    "BlockProgramArtifact",
    "BuildingMassing",
    "ConnectionRecord",
    "CoordinateTransformAudit",
    "LocalWorldTransform",
    "FloorGeometry",
    "FrozenRef",
    "GenerationClass",
    "GenerationContext",
    "GeometryValue",
    "FrontageRecord",
    "LinearGeometryValue",
    "MassingArtifact",
    "MethodProvenance",
    "MethodSourceKind",
    "OpenSpaceArtifact",
    "PointGeometryValue",
    "ProgramAllocation",
    "ProgramBlock",
    "ProgramZone",
    "RoadArtifact",
    "SkeletonArtifact",
    "SkeletonEdge",
    "SkeletonNode",
    "StageArtifact",
    "StageStatus",
    "StrategyReason",
    "StrategySpec",
    "UnallocatedArea",
    "ValidationCheck",
    "ValidationReport",
]


class FixtureDictionaryRecipe(_ContractModel):
    """Versioned executable dictionary data, never markdown-derived geometry."""
    recipe_id: str
    version: str
    source_ref: FrozenRef
    type_id: str
    geometry_parameters: dict[str, Any]
    floor_uses: tuple[str, ...]

    @field_validator("recipe_id", "version", "type_id")
    @classmethod
    def nonempty_recipe_text(cls, value):
        if not value.strip():
            raise ValueError("recipe identity must be nonempty")
        return value.strip()

    @field_validator("geometry_parameters")
    @classmethod
    def frozen_recipe_parameters(cls, value):
        _finite_json(value)
        return _deep_freeze(value)

    @field_validator("floor_uses")
    @classmethod
    def nonempty_floor_program(cls, value):
        if not value or any(not use.strip() for use in value):
            raise ValueError("recipe requires explicit use for every floor")
        return value


class FixtureRetainedBuilding(_ContractModel):
    source_ref: FrozenRef
    geometry: AreaGeometryValue
    floor_count: StrictInt | None = None

    @field_validator("floor_count")
    @classmethod
    def positive_retained_floors(cls, value):
        if value is not None and value < 1:
            raise ValueError("retained floor_count must be positive or UNKNOWN")
        return value


class FixtureCandidate(_ContractModel):
    recipe_id: str
    status: Literal["FIXTURE_ONLY", "FAIL"]
    input_hash: str
    failure_reasons: tuple[str, ...] = ()
    block_program: BlockProgramArtifact | None = None
    massing: MassingArtifact | None = None
    block_hash: str | None = None
    massing_hash: str | None = None
    road_hash: str | None = None
    open_space_hash: str | None = None
    footprint_hash: str | None = None
    new_gfa_m2: float | None = None
    retained_gfa_m2: float | None = None
    total_gfa_m2: float | None = None
    floor_areas_m2: tuple[float, ...] = ()
    program_gfa_m2: dict[str, float] = Field(default_factory=dict)

    @field_validator("program_gfa_m2")
    @classmethod
    def immutable_measured_program(cls, value):
        _finite_json(value)
        return _deep_freeze(value)


class FixturePipelineResult(_ContractModel):
    status: Literal["FIXTURE_ONLY", "FAIL", "BLOCKED"]
    formal_status: Literal["BLOCKED"] = "BLOCKED"
    formal_reason: str = "W6-3 approved GenerationContext and Founder kernel/dictionary decisions pending"
    candidates: tuple[FixtureCandidate, ...] = ()
    pairwise_differences: tuple[dict[str, Any], ...] = ()
    valid_count: StrictInt = 0
    overall_winner: None = None

    @field_validator("pairwise_differences")
    @classmethod
    def immutable_differences(cls, value):
        return tuple(_deep_freeze(item) for item in value)

__all__ += ["FixtureDictionaryRecipe", "FixtureRetainedBuilding", "FixtureCandidate", "FixturePipelineResult"]
