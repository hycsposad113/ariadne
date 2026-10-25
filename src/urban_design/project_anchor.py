"""Typed, source-backed geographic guards for a dedicated StudyArea project.

An anchor is a location guard for the drawing workflow.  It is deliberately
not a Site, DesignBoundary, planning constraint, or analysis snapshot.  The
backend and the QGIS companion both consume the same small JSON contract, but
the backend independently validates exported geometry before it can enter
project state.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from pyproj import CRS, Transformer
from shapely.geometry import shape


class ProjectAnchorError(ValueError):
    """Raised when a project anchor is absent, malformed, or not ready."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectAnchorError(f"{field} must be a non-empty string")
    return value.strip()


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) == 64 and all(char in "0123456789abcdef" for char in text):
        return "sha256:" + text
    if text.startswith("sha256:") and len(text) == 71 and all(
        char in "0123456789abcdef" for char in text.removeprefix("sha256:")
    ):
        return text
    raise ProjectAnchorError(f"{field} must be sha256:<64 lowercase hex characters>")


def _bbox(value: Any, field: str) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ProjectAnchorError(f"{field} must be [xmin, ymin, xmax, ymax]")
    values = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in values):
        raise ProjectAnchorError(f"{field} must contain finite numbers")
    xmin, ymin, xmax, ymax = values
    if not xmin < xmax or not ymin < ymax:
        raise ProjectAnchorError(f"{field} must have positive width and height")
    return values


def projected_crs_area_of_use(crs_input: str | CRS) -> tuple[float, float, float, float]:
    """Return deterministic projected bounds for a CRS's geographic area of use."""

    try:
        crs = CRS.from_user_input(crs_input)
        area = crs.area_of_use
        transformer = Transformer.from_crs(4326, crs, always_xy=True)
        points = [
            transformer.transform(area.west, area.south),
            transformer.transform(area.west, area.north),
            transformer.transform(area.east, area.south),
            transformer.transform(area.east, area.north),
        ]
    except Exception as exc:
        raise ProjectAnchorError("CRS area of use could not be projected") from exc
    result = (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )
    if not all(math.isfinite(item) for item in result):
        raise ProjectAnchorError("projected CRS area of use is not finite")
    return result


@dataclass(frozen=True)
class ProjectGeographicAnchor:
    """Validated project-local location guard with explicit provenance."""

    project_id: str
    horizontal_crs: str
    units: str
    anchor_extent: tuple[float, float, float, float]
    crs_area_of_use_projected: tuple[float, float, float, float]
    source_provenance: Mapping[str, Any]
    status: str
    context_layer_path: str
    context_layer_sha256: str
    context_layer_name: str = "NON_AUTHORITATIVE_DRAWING_CONTEXT"
    context_display_only: bool = True
    analysis_eligible: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _text(self.project_id, "project_id"))
        object.__setattr__(self, "horizontal_crs", _text(self.horizontal_crs, "horizontal_crs"))
        object.__setattr__(self, "units", _text(self.units, "units"))
        try:
            crs = CRS.from_user_input(self.horizontal_crs)
        except Exception as exc:  # pragma: no cover - pyproj supplies the detail
            raise ProjectAnchorError("horizontal_crs is invalid") from exc
        if not crs.is_projected:
            raise ProjectAnchorError("project anchor CRS must be projected")
        authority = crs.to_authority()
        if authority and f"{authority[0].upper()}:{authority[1]}" != self.horizontal_crs.upper():
            raise ProjectAnchorError("horizontal_crs must use its canonical authority form")
        if self.units.casefold() not in {"m", "metre", "meter", "metres", "meters"}:
            raise ProjectAnchorError("project anchor units must be metres")
        object.__setattr__(self, "anchor_extent", _bbox(self.anchor_extent, "anchor_extent"))
        object.__setattr__(
            self,
            "crs_area_of_use_projected",
            _bbox(self.crs_area_of_use_projected, "crs_area_of_use_projected"),
        )
        if self.status != "DRAWING_LOCATION_GUARD_ONLY":
            raise ProjectAnchorError("project anchor status must be DRAWING_LOCATION_GUARD_ONLY")
        if not isinstance(self.source_provenance, Mapping) or not self.source_provenance:
            raise ProjectAnchorError("source_provenance is required")
        object.__setattr__(self, "context_layer_path", _text(self.context_layer_path, "context_layer_path"))
        object.__setattr__(self, "context_layer_sha256", _sha(self.context_layer_sha256, "context_layer_sha256"))
        object.__setattr__(self, "context_layer_name", _text(self.context_layer_name, "context_layer_name"))
        if self.context_layer_name != "NON_AUTHORITATIVE_DRAWING_CONTEXT":
            raise ProjectAnchorError("context layer must be labelled NON_AUTHORITATIVE_DRAWING_CONTEXT")
        if self.context_display_only is not True or self.analysis_eligible is not False:
            raise ProjectAnchorError("drawing context must be display-only and analysis-ineligible")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProjectGeographicAnchor":
        if not isinstance(value, Mapping):
            raise ProjectAnchorError("project anchor must be an object")
        return cls(
            project_id=value.get("project_id"),
            horizontal_crs=value.get("horizontal_crs"),
            units=value.get("units"),
            anchor_extent=_bbox(value.get("anchor_extent"), "anchor_extent"),
            crs_area_of_use_projected=_bbox(
                value.get("crs_area_of_use_projected"), "crs_area_of_use_projected"
            ),
            source_provenance=dict(value.get("source_provenance", {})),
            status=value.get("status"),
            context_layer_path=value.get("context_layer_path"),
            context_layer_sha256=value.get("context_layer_sha256"),
            context_layer_name=value.get("context_layer_name", "NON_AUTHORITATIVE_DRAWING_CONTEXT"),
            context_display_only=value.get("context_display_only", True),
            analysis_eligible=value.get("analysis_eligible", False),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "horizontal_crs": self.horizontal_crs,
            "units": self.units,
            "anchor_extent": list(self.anchor_extent),
            "crs_area_of_use_projected": list(self.crs_area_of_use_projected),
            "source_provenance": dict(self.source_provenance),
            "status": self.status,
            "context_layer_path": self.context_layer_path,
            "context_layer_sha256": self.context_layer_sha256,
            "context_layer_name": self.context_layer_name,
            "context_display_only": self.context_display_only,
            "analysis_eligible": self.analysis_eligible,
        }

    def validate_context_files(self, *, root: str | Path) -> None:
        root_path = Path(root).expanduser().resolve()
        path = Path(self.context_layer_path)
        path = path if path.is_absolute() else root_path / path
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ProjectAnchorError(f"context layer is missing: {self.context_layer_path}") from exc
        if not resolved.is_file():
            raise ProjectAnchorError(f"context layer is not a file: {self.context_layer_path}")
        digest = "sha256:" + hashlib.sha256(resolved.read_bytes()).hexdigest()
        if digest != self.context_layer_sha256:
            raise ProjectAnchorError("context layer bytes do not match anchor provenance")
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectAnchorError("context layer is not readable UTF-8 GeoJSON") from exc
        if not isinstance(payload, Mapping) or payload.get("type") != "FeatureCollection":
            raise ProjectAnchorError("context layer must be a GeoJSON FeatureCollection")
        declared_crs = payload.get("crs")
        if isinstance(declared_crs, Mapping):
            properties = declared_crs.get("properties")
            name = properties.get("name") if isinstance(properties, Mapping) else None
            if isinstance(name, str) and not CRS.from_user_input(name).equals(CRS.from_user_input(self.horizontal_crs)):
                raise ProjectAnchorError("context layer CRS does not match project anchor")

    def validate_source_provenance(self, *, root: str | Path) -> None:
        """Verify retained source bytes named by the anchor config."""

        root_path = Path(root).expanduser().resolve()
        provenance = self.source_provenance
        for path_key, hash_key in (
            ("anchor_source_artifact", "anchor_source_artifact_sha256"),
            ("context_source_records", "context_source_records_sha256"),
        ):
            source_value = provenance.get(path_key)
            expected_value = provenance.get(hash_key)
            if source_value is None or expected_value is None:
                raise ProjectAnchorError(f"source provenance is missing {path_key}")
            source_path = Path(_text(source_value, path_key))
            source_path = source_path if source_path.is_absolute() else root_path / source_path
            try:
                resolved = source_path.resolve(strict=True)
            except OSError as exc:
                raise ProjectAnchorError(f"source provenance file is missing: {source_value}") from exc
            if not resolved.is_file():
                raise ProjectAnchorError(f"source provenance path is not a file: {source_value}")
            actual = "sha256:" + hashlib.sha256(resolved.read_bytes()).hexdigest()
            if actual != _sha(expected_value, hash_key):
                raise ProjectAnchorError(f"source provenance hash mismatch: {source_value}")

    def validate_geometry(self, geometry: Mapping[str, Any]) -> None:
        """Validate CRS area-of-use and configured project locality."""

        if not isinstance(geometry, Mapping):
            raise ProjectAnchorError("StudyArea geometry is not an object")
        try:
            planar = shape(geometry)
        except Exception as exc:
            raise ProjectAnchorError("StudyArea geometry could not be parsed") from exc
        if planar.is_empty or not planar.is_valid:
            raise ProjectAnchorError("StudyArea geometry is empty or invalid")
        bounds = tuple(float(item) for item in planar.bounds)
        if not all(math.isfinite(item) for item in bounds):
            raise ProjectAnchorError("StudyArea geometry bounds are not finite")
        area_bounds = self.crs_area_of_use_projected
        if (
            bounds[0] < area_bounds[0]
            or bounds[1] < area_bounds[1]
            or bounds[2] > area_bounds[2]
            or bounds[3] > area_bounds[3]
        ):
            raise ProjectAnchorError("StudyArea geometry is outside the CRS area of use")
        anchor = self.anchor_extent
        if bounds[0] < anchor[0] or bounds[1] < anchor[1] or bounds[2] > anchor[2] or bounds[3] > anchor[3]:
            raise ProjectAnchorError("StudyArea geometry is outside the configured project geographic anchor")


def load_project_anchor(path: str | Path, *, root: str | Path | None = None) -> ProjectGeographicAnchor:
    """Load and verify an anchor config without silently repairing it."""

    config_path = Path(path).expanduser().resolve(strict=True)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectAnchorError("project anchor config is not readable UTF-8 JSON") from exc
    anchor = ProjectGeographicAnchor.from_mapping(payload)
    resolved_root = root or config_path.parent
    anchor.validate_context_files(root=resolved_root)
    anchor.validate_source_provenance(root=resolved_root)
    return anchor


__all__ = [
    "ProjectAnchorError",
    "ProjectGeographicAnchor",
    "load_project_anchor",
    "projected_crs_area_of_use",
]
