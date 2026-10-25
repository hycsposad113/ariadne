"""Verified feature and snapshot index for the retained spatial-r01 package."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from datetime import datetime, timezone

from shapely.geometry import shape

from .analysis_inputs import (
    AnalysisInputError,
    load_m2a03_spatial_package,
    inspect_active_study_area,
    require_spatial_package_use,
)
from .store import EntityNotFoundError, ProjectStateStore


DEFAULT_SPATIAL_R01_ROOT = (
    Path(__file__).resolve().parents[2]
    / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
)


class WorkspaceSourceError(ValueError):
    """A source, snapshot, or selectable feature cannot be proven."""


@dataclass(frozen=True)
class SourceFeature:
    feature_id: str
    feature_kind: str
    source_artifact_id: str
    source_snapshot_id: str
    source_feature_id: str
    geometry: Mapping[str, Any]
    properties: Mapping[str, Any]

    def as_api_feature(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.feature_id,
            "feature_kind": self.feature_kind,
            "disposition": "UNDECIDED",
            "source_artifact_id": self.source_artifact_id,
            "source_snapshot_id": self.source_snapshot_id,
            "source_feature_id": self.source_feature_id,
            "crs": "EPSG:28992",
            "lineage_status": "VERIFIED",
            "geometry": dict(self.geometry),
            "properties": dict(self.properties),
        }
        if self.feature_kind == "road":
            geometry = shape(self.geometry)
            result["length_m"] = float(geometry.length)
            tags = self.properties.get("tags", {})
            result["highway"] = tags.get("highway") if isinstance(tags, Mapping) else None
            result["layer"] = result["highway"]
        return result


@dataclass(frozen=True)
class WorkspaceSourceCatalog:
    project_id: str
    study_area_id: str
    study_area_geometry_sha256: str
    package_revision: str
    package_id: str
    package_root: Path
    study_area_geometry: Mapping[str, Any]
    study_area_shape: Any
    snapshots: Mapping[str, Mapping[str, Any]]
    raw_artifacts: Mapping[str, Mapping[str, Any]]
    normalized_artifacts: Mapping[str, Mapping[str, Any]]
    features: Mapping[str, SourceFeature]
    buildings: tuple[SourceFeature, ...]
    roads: tuple[SourceFeature, ...]

    @classmethod
    def load(
        cls,
        store: ProjectStateStore,
        package_root: str | Path | None = None,
    ) -> "WorkspaceSourceCatalog":
        resolved_root = Path(package_root or DEFAULT_SPATIAL_R01_ROOT).expanduser().resolve()
        try:
            package = _load_verified_package(str(resolved_root))
            project_id = str(package["project_id"])
            inspection = inspect_active_study_area(
                store.database,
                project_id=project_id,
                study_area_id=str(package["study_area"]["id"]),
            )
            require_spatial_package_use(
                package,
                active_geometry_sha256=inspection.geometry_sha256,
                active_study_area_id=inspection.study_area_id,
            )
            geometry_document = json.loads(Path(inspection.artifact_uri).read_text(encoding="utf-8"))
            geometry_mapping = geometry_document.get("geometry", geometry_document)
            study_geometry = shape(geometry_mapping)
        except (OSError, KeyError, TypeError, ValueError, AnalysisInputError) as exc:
            raise WorkspaceSourceError(f"spatial-r01 source package is not usable: {exc}") from exc

        raw = {str(record["id"]): record for record in package.get("artifacts", [])}
        normalized = {str(record["id"]): record for record in package.get("normalized_artifacts", [])}
        snapshots = {str(record["id"]): record for record in package.get("snapshots", [])}
        snapshot_by_normalized = {
            str(record.get("normalized_artifact_id")): str(record["id"])
            for record in snapshots.values()
        }
        cls._verify_store_records(store, project_id, resolved_root, raw, normalized, snapshots)

        selected: dict[str, SourceFeature] = {}
        buildings: list[SourceFeature] = []
        roads: list[SourceFeature] = []
        for artifact_id, record in normalized.items():
            uri = str(record.get("uri", ""))
            if "/pdok-bag-pand-" in uri:
                kind = "building"
            elif uri.endswith("/osm-overpass-v5-epsg28992.geojson"):
                kind = "road"
            else:
                continue
            snapshot_id = snapshot_by_normalized.get(artifact_id)
            if not snapshot_id:
                raise WorkspaceSourceError(f"normalized Artifact {artifact_id!r} has no DatasetSnapshot")
            source_file = resolved_root / uri
            try:
                document = json.loads(source_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkspaceSourceError(f"normalized source cannot be decoded: {uri}") from exc
            for feature in document.get("features", []):
                geometry = feature.get("geometry")
                properties = feature.get("properties") or {}
                if not isinstance(geometry, Mapping):
                    continue
                try:
                    geom = shape(geometry)
                except (TypeError, ValueError):
                    continue
                if geom.is_empty or not geom.is_valid or not geom.intersects(study_geometry):
                    continue
                if kind == "building":
                    source_feature_id = str(properties.get("identificatie") or "").strip()
                    feature_id = f"bag:{source_feature_id}" if source_feature_id else ""
                    if not source_feature_id or geom.geom_type not in {"Polygon", "MultiPolygon"}:
                        continue
                else:
                    tags = properties.get("tags")
                    osm_type = str(properties.get("osm_type") or "")
                    osm_id = str(properties.get("osm_id") or "")
                    source_feature_id = str(feature.get("id") or "")
                    if (
                        not isinstance(tags, Mapping)
                        or not tags.get("highway")
                        or osm_type != "way"
                        or not osm_id
                        or source_feature_id != f"way/{osm_id}"
                        or geom.geom_type not in {"LineString", "MultiLineString"}
                    ):
                        continue
                    feature_id = source_feature_id
                if not feature_id:
                    continue
                if feature_id in selected:
                    prior = selected[feature_id]
                    raise WorkspaceSourceError(
                        f"duplicate source feature ID {feature_id!r} in {prior.source_artifact_id!r} and {artifact_id!r}"
                    )
                item = SourceFeature(
                    feature_id=feature_id,
                    feature_kind=kind,
                    source_artifact_id=artifact_id,
                    source_snapshot_id=snapshot_id,
                    source_feature_id=source_feature_id,
                    geometry=geometry,
                    properties=properties,
                )
                selected[feature_id] = item
                (buildings if kind == "building" else roads).append(item)

        return cls(
            project_id=project_id,
            study_area_id=inspection.study_area_id,
            study_area_geometry_sha256=inspection.geometry_sha256,
            package_revision=str(package.get("package_revision")),
            package_id=str(package.get("package_id")),
            package_root=resolved_root,
            study_area_geometry=geometry_mapping,
            study_area_shape=study_geometry,
            snapshots=snapshots,
            raw_artifacts=raw,
            normalized_artifacts=normalized,
            features=selected,
            buildings=tuple(sorted(buildings, key=lambda item: item.feature_id)),
            roads=tuple(sorted(roads, key=lambda item: item.feature_id)),
        )

    @staticmethod
    def _verify_store_records(
        store: ProjectStateStore,
        project_id: str,
        package_root: Path,
        raw_artifacts: Mapping[str, Mapping[str, Any]],
        normalized_artifacts: Mapping[str, Mapping[str, Any]],
        snapshots: Mapping[str, Mapping[str, Any]],
    ) -> None:
        for artifact_id, expected in {**raw_artifacts, **normalized_artifacts}.items():
            try:
                record = store.current(artifact_id)
            except EntityNotFoundError as exc:
                raise WorkspaceSourceError(f"source Artifact {artifact_id!r} is missing from project state") from exc
            if record.entity_type != "Artifact" or record.project_id != project_id:
                raise WorkspaceSourceError(f"source Artifact {artifact_id!r} has the wrong type or project")
            actual = record.payload
            for key in ("id", "project_id", "sha256", "uri", "size_bytes", "mime", "crs", "producer", "type", "parent_artifact_ids"):
                if key == "uri" and key in expected:
                    expected_path = (package_root / str(expected[key])).resolve()
                    actual_path = Path(str(actual.get(key, ""))).expanduser().resolve()
                    matches = actual_path == expected_path or (
                        expected_path.is_file()
                        and actual_path.is_file()
                        and str(actual_path).endswith(str(expected[key]))
                        and expected_path.stat().st_size == actual_path.stat().st_size
                    )
                else:
                    matches = key not in expected or actual.get(key) == expected.get(key)
                if not matches:
                    raise WorkspaceSourceError(f"source Artifact {artifact_id!r} {key} does not match spatial-r01")
        for snapshot_id, expected in snapshots.items():
            try:
                record = store.current(snapshot_id)
            except EntityNotFoundError as exc:
                raise WorkspaceSourceError(f"DatasetSnapshot {snapshot_id!r} is missing from project state") from exc
            if record.entity_type != "DatasetSnapshot" or record.project_id != project_id:
                raise WorkspaceSourceError(f"snapshot {snapshot_id!r} is the wrong type or project")
            actual = record.payload
            comparisons = {
                "id": (actual.get("id"), expected.get("id")),
                "project_id": (actual.get("project_id"), expected.get("project_id")),
                "raw_artifact_id": (actual.get("raw_artifact_id"), expected.get("raw_artifact_id")),
                "normalized_artifact_id": (actual.get("normalized_artifact_id"), expected.get("normalized_artifact_id")),
                "sha256": (actual.get("sha256"), expected.get("sha256")),
                "source": (actual.get("source"), expected.get("source_url")),
                "publisher": (actual.get("publisher"), expected.get("publisher")),
                "license": (actual.get("license"), expected.get("license")),
                "retrieved_at": (_canonical_time(actual.get("retrieved_at")), _canonical_time(expected.get("retrieved_at"))),
            }
            for key, (observed, declared) in comparisons.items():
                if observed != declared:
                    raise WorkspaceSourceError(f"DatasetSnapshot {snapshot_id!r} {key} does not match spatial-r01")

    def validate_snapshot_ids(self, project_id: str, study_area_id: str, snapshot_ids: Sequence[str]) -> None:
        if project_id != self.project_id:
            raise WorkspaceSourceError("workspace project does not match spatial-r01")
        if study_area_id != self.study_area_id:
            raise WorkspaceSourceError("workspace StudyArea is not the active spatial-r01 StudyArea")
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise WorkspaceSourceError("duplicate source snapshot IDs are not allowed")
        if set(snapshot_ids) != set(self.snapshots):
            raise WorkspaceSourceError("source snapshot IDs must exactly match the verified spatial-r01 package")

    def resolve_feature(self, feature_id: str, feature_kind: str, source_artifact_id: str = "") -> SourceFeature:
        feature = self.features.get(feature_id)
        if feature is None:
            raise WorkspaceSourceError(f"feature {feature_id!r} is not selectable from verified spatial-r01 sources")
        if feature.feature_kind != feature_kind:
            raise WorkspaceSourceError(f"feature {feature_id!r} is {feature.feature_kind}, not {feature_kind}")
        if source_artifact_id and source_artifact_id != feature.source_artifact_id:
            raise WorkspaceSourceError(f"feature {feature_id!r} source Artifact does not match verified parent")
        return feature

    def validate_zone_scope(self, geometry: Mapping[str, Any]) -> None:
        try:
            zone = shape(geometry)
        except Exception as exc:
            raise WorkspaceSourceError("SpatialZone geometry is invalid") from exc
        if not self.study_area_shape.covers(zone):
            raise WorkspaceSourceError("SpatialZone geometry must be fully inside the active StudyArea")


def _load_verified_package(root: str) -> dict[str, Any]:
    """Reload and revalidate source bytes on every catalog build."""
    return load_m2a03_spatial_package(root)


def _canonical_time(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
