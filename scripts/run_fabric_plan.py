#!/usr/bin/env python3
"""Build the FAB1 four-fabric comparison package from frozen local inputs.

The runner only calls the deterministic `fabric_plan` domain API.  It reads no
network data, never writes project state, and keeps the input snapshot immutable
after its first creation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont
from shapely import make_valid
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Polygon, mapping, shape
from shapely.ops import triangulate


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "artifacts" / "fab1"
INPUTS_DIR = OUTPUT_DIR / "inputs"
RUN_DIR = OUTPUT_DIR / "run-2"
INTENTS_DIR = OUTPUT_DIR / "intents"
SITE_SOURCE = ROOT / "artifacts" / "s6-brief" / "facts" / "site-facts.json"
CONTEXT_SOURCE = ROOT / "artifacts" / "ctx1-context-morphology" / "context-facts.json"
FABRIC_SOURCE_DIR = Path(
    "/Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor/knowledge/v2/domains/MOR/fabrics"
)
DICTIONARY_SOURCE_DIR = FABRIC_SOURCE_DIR.parents[4] / "config" / "morphology-dictionary" / "entries"
FABRIC_IDS = (
    "harbour_grain",
    "closed_block_extension",
    "courtyard_islands",
    "landscape_figure",
)
MAX_JSON_BYTES = 5_000_000
MAX_ARTIFACT_BYTES = 5_000_000
RUNNER_VERSION = "fab1-runner-v5"
FAB1B_DICTIONARY_REVISION = "36f4d95"
FAB1B_INPUT_MANIFEST_SHA256 = "b0f89a398767ccb17d783d029aa8eb1eedc7995ee153b384ddb9dd9b2a7f7c8c"

# Keep every original run-2 validator visible even if a later core response
# accidentally omits one. New core validator IDs are added from the returned
# mapping, so they are listed and reported without a hard-coded allowlist.
FAB1_ORIGINAL_VALIDATOR_IDS = (
    "ALL_BUILDINGS_FRONTAGE",
    "BLOCK_DICTIONARY_DIMENSIONS",
    "BLOCK_MINIMUM",
    "BLOCK_STREET_FRONTAGE",
    "BOUNDARY_PARCEL_SEMANTICS",
    "BUILDING_BUILDABLE",
    "BUILDING_CONTAINMENT",
    "BUILDING_NO_OVERLAP",
    "BUILDING_ROAD_CLEARANCE",
    "CONNECTIVITY_BICYCLE",
    "CONNECTIVITY_CAR",
    "CONNECTIVITY_FIRE",
    "CONNECTIVITY_PEDESTRIAN",
    "CONNECTIVITY_SERVICE",
    "COURTYARD_CLEAR_WIDTH",
    "CRS",
    "ENTRANCES_BICYCLE",
    "ENTRANCES_CAR",
    "ENTRANCES_PEDESTRIAN",
    "EVERY_BLOCK_BUILT_COVERAGE",
    "FIRE_ALL_EXTERIORS",
    "FLOOR_HEIGHT",
    "GEOMETRY_VALID",
    "HEIGHT_CAP",
    "LAND_COVERAGE",
    "LAND_MANAGEMENT",
    "LAND_NO_OVERLAP",
    "LAND_SUM_100_PERCENT",
    "LAND_USE_CATEGORIES",
    "MASSING_CORNERS",
    "MEZZANINE_GEOMETRY",
    "NEW_GFA_TARGET",
    "NO_LARGE_UNBUILT_PLOT",
    "ORTHOGONAL_TEMPLATES",
    "PARK_AREA_BUDGET",
    "PARK_COHERENT_SHAPE",
    "PARK_PRESENT",
    "PLAZA_BUDGET_AND_LOCATION",
    "PRIMARY_STREET_DICTIONARY",
    "PRIMARY_STREET_THROUGH_SITE",
    "RETAINED_ROADS_PRESERVED",
    "RETAINED_UNCHANGED",
    "ROAD_AREA_BUDGET",
    "ROAD_WATERFRONT_COMBINED_BUDGET",
    "SHARED_COURTYARD_MARKED_WIDTH",
    "SLAB_LENGTH_DEPTH",
    "SLAB_SPACING",
    "STREET_FRONTAGE",
    "TERRACE_FRONTAGE",
    "WATERFRONT_CONTINUITY",
    "WATERFRONT_PUBLIC_BAND",
    "WING_DEPTH",
)

FAB1C_REQUIRED_VALIDATOR_IDS = (
    "FAB1C_NEW_GFA_TARGET",
    "COURTYARD_ISLAND_GLOBAL_MEMBERSHIP",
    "COURTYARD_ISLAND_ROAD_CLEARANCE",
    "SERVICE_AREA_BUDGET",
    "SERVICE_FUNCTION_FRONTAGE",
    "BLOCK_LAND_BUDGET",
    "SOUTH_QUAY_SHARED_ALLEY",
    "SOUTH_QUAY_FACADE_CONTINUITY",
    "NORTHEAST_REGULAR_BLOCKS",
    "COURTYARD_ISLAND_COUNT_SPACING",
    "WATERFRONT_DETOUR_GEOMETRY",
    "BUILDING_STREET_EDGE_3M",
    "NORTHEAST_NO_SMALL_BUILDING_BLOCKS",
    "SOUTH_QUAY_MAX_GAP",
)
WATERFRONT_DETOUR_MARKED = "WATERFRONT_DETOUR_MARKED"
MAP_TEXT_LABEL_LIMIT = "MAP_TEXT_LABEL_LIMIT"
LANDUSE_NO_MOBILITY_OVERLAY = "LANDUSE_NO_MOBILITY_OVERLAY"
REQUIRED_FAB1C_CHECK_IDS = (*FAB1_ORIGINAL_VALIDATOR_IDS, *FAB1C_REQUIRED_VALIDATOR_IDS, LANDUSE_NO_MOBILITY_OVERLAY)

FAB1B_VALIDATOR_IDS = (
    "ROAD_AREA_BUDGET",
    "ROAD_WATERFRONT_COMBINED_BUDGET",
    "WATERFRONT_PUBLIC_BAND",
    "PRIMARY_STREET_THROUGH_SITE",
    "PLAZA_BUDGET_AND_LOCATION",
    "PARK_AREA_BUDGET",
    "EVERY_BLOCK_BUILT_COVERAGE",
    "NO_LARGE_UNBUILT_PLOT",
    "SHARED_COURTYARD_MARKED_WIDTH",
)

sys.path.insert(0, str(ROOT / "src"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(path: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def repository_provenance(path: Path) -> dict[str, Any]:
    return {
        "repository_root": _git_value(path, "rev-parse", "--show-toplevel"),
        "revision": _git_value(path, "rev-parse", "HEAD"),
        "worktree_status_porcelain": _git_value(path, "status", "--porcelain"),
    }


def json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    options: dict[str, Any] = {"ensure_ascii": False, "allow_nan": False, "default": _json_default}
    if pretty:
        options.update(indent=2, sort_keys=True)
    else:
        options.update(separators=(",", ":"), sort_keys=True)
    return (json.dumps(value, **options) + "\n").encode("utf-8")


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__geo_interface__"):
        return dict(value.__geo_interface__)
    raise TypeError(f"無法序列化 {type(value).__name__}")


def write_json(path: Path, value: Any, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json_bytes(value, pretty=pretty)
    if len(payload) >= MAX_JSON_BYTES:
        raise ValueError(f"JSON 檔將達 {len(payload):,} bytes，必須小於 {MAX_JSON_BYTES:,} bytes：{path}")
    path.write_bytes(payload)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _fabric_ids() -> dict[str, Path]:
    return {fabric_id: FABRIC_SOURCE_DIR / f"fabric.{fabric_id}.json" for fabric_id in FABRIC_IDS}


def _dictionary_entry_ids() -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not DICTIONARY_SOURCE_DIR.is_dir():
        raise FileNotFoundError(f"找不到本地 morphology dictionary：{DICTIONARY_SOURCE_DIR}")
    for path in sorted(DICTIONARY_SOURCE_DIR.glob("*.yaml")):
        # The entries in this checkout are JSON-compatible documents despite
        # their .yaml suffix. Avoid adding PyYAML to the project runtime.
        source = path.read_text(encoding="utf-8")
        entry_id = None
        try:
            parsed = json.loads(source)
            if isinstance(parsed, Mapping) and isinstance(parsed.get("id"), str):
                entry_id = parsed["id"]
        except json.JSONDecodeError:
            match = re.search(
                r"(?m)^\s*(?:id|['\"]id['\"]):\s*['\"]?([^\s#'\"]+)['\"]?\s*(?:#.*)?$",
                source,
            )
            if match:
                entry_id = match.group(1)
        if entry_id:
            result[entry_id] = path
    return result


def _collect_referenced_entry_ids(value: Any, known_ids: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for child in value.values():
            found.update(_collect_referenced_entry_ids(child, known_ids))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_referenced_entry_ids(child, known_ids))
    elif isinstance(value, str) and value in known_ids:
        found.add(value)
    return found


def _copy_exact(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(f"輸入來源不存在：{source}")
    source_hash = sha256_file(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    destination.write_bytes(data)
    snapshot_hash = sha256_file(destination)
    if source_hash != snapshot_hash:
        raise RuntimeError(f"快照 SHA-256 不一致：{source}")
    return {
        "source_path": str(source),
        "snapshot_path": str(destination.relative_to(OUTPUT_DIR)),
        "size_bytes": len(data),
        "source_sha256": source_hash,
        "snapshot_sha256": snapshot_hash,
    }


def snapshot_inputs(*, allow_create: bool = True, repair: bool = False) -> dict[str, Any]:
    """Create the first immutable snapshot, or verify and return the existing one."""
    manifest_path = INPUTS_DIR / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        if manifest.get("schema_version") != "fab1-input-snapshot-v1":
            raise ValueError("既有 FAB1 輸入 manifest 版本不符；停止以免覆寫快照。")
        for record in manifest.get("files", []):
            snapshot = OUTPUT_DIR / record["snapshot_path"]
            if not snapshot.is_file():
                raise FileNotFoundError(f"輸入快照缺檔：{snapshot}")
            actual_hash = sha256_file(snapshot)
            if actual_hash != record.get("snapshot_sha256"):
                raise ValueError(f"輸入快照 SHA-256 不符：{snapshot}")
            if snapshot.stat().st_size != record.get("size_bytes"):
                raise ValueError(f"輸入快照檔案大小不符：{snapshot}")
        expected = {f"fabric.{fabric_id}.json" for fabric_id in FABRIC_IDS}
        captured = {
            Path(record["snapshot_path"]).name
            for record in manifest.get("files", [])
            if "/fabrics/" in record["snapshot_path"]
        }
        if not expected.issubset(captured):
            raise ValueError("既有快照未包含本次四個 fabric；不會自動改寫 immutable inputs。")
        dictionary_ids = _dictionary_entry_ids()
        expected_refs: set[str] = set()
        snapshot_fabrics = [
            OUTPUT_DIR / record["snapshot_path"]
            for record in manifest.get("files", [])
            if "/fabrics/" in record["snapshot_path"]
        ]
        for fabric_path in snapshot_fabrics:
            expected_refs.update(_collect_referenced_entry_ids(load_json(fabric_path), set(dictionary_ids)))
        captured_refs = set(manifest.get("referenced_morphology_entry_ids", []))
        missing_refs = sorted(expected_refs - captured_refs)
        if missing_refs:
            if not repair:
                raise ValueError(
                    "既有快照缺少 fabric 引用的 morphology entries："
                    + ", ".join(missing_refs)
                    + "；請先明確執行 --snapshot-only --repair-snapshot。"
                )
            previous_bytes = manifest_path.read_bytes()
            previous_hash = hashlib.sha256(previous_bytes).hexdigest()
            archive_path = INPUTS_DIR / "manifest-attempt-01-incomplete.json"
            if not archive_path.exists():
                archive_path.write_bytes(previous_bytes)
            added_records = []
            for entry_id in missing_refs:
                source = dictionary_ids[entry_id]
                added_records.append(_copy_exact(source, INPUTS_DIR / "dictionary_entries" / source.name))
            manifest["files"] = list(manifest.get("files", [])) + added_records
            manifest["referenced_morphology_entry_ids"] = sorted(captured_refs | set(missing_refs))
            history = list(manifest.get("snapshot_repairs", []))
            history.append({
                "repaired_at_utc": utc_now(),
                "reason_zh": "初版讀取器只辨識 YAML scalar；實際 .yaml entries 為 JSON-compatible 文件，依 fabric part_id 補齊 exact bytes。",
                "previous_manifest_sha256": previous_hash,
                "archived_manifest_path": str(archive_path.relative_to(OUTPUT_DIR)),
                "added_entry_ids": missing_refs,
            })
            manifest["snapshot_repairs"] = history
            write_json(manifest_path, manifest, pretty=True)
        return manifest

    if not allow_create:
        raise FileNotFoundError("FAB1 輸入快照尚未建立；請先執行 --snapshot-only。")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fabric_sources = _fabric_ids()
    for fabric_id, path in fabric_sources.items():
        if not path.is_file():
            raise FileNotFoundError(f"找不到 fabric source：{path}")

    dictionary_ids = _dictionary_entry_ids()
    referenced_ids: set[str] = set()
    fabric_values: dict[str, Any] = {}
    for fabric_id, path in fabric_sources.items():
        fabric_value = load_json(path)
        fabric_values[fabric_id] = fabric_value
        referenced_ids.update(_collect_referenced_entry_ids(fabric_value, set(dictionary_ids)))
    # Fabric files also cite source IDs (KU-MOR-*).  Those are evidence source
    # references, not morphology-entry IDs, so their referenced file is the
    # fabric JSON itself and the cited identifier stays in that exact snapshot.
    # This list is intentionally empty unless a component ID was unmatched.
    unresolved_component_ids: list[str] = []
    for fabric_id in FABRIC_IDS:
        for component in fabric_values[fabric_id].get("building_composition", {}).get("components", []):
            part_id = component.get("part_id")
            if isinstance(part_id, str) and part_id.startswith(("block.", "building.", "space.")) and part_id not in dictionary_ids:
                unresolved_component_ids.append(part_id)
        for type_id in fabric_values[fabric_id].get("open_space_system", {}).get("types", []):
            if isinstance(type_id, str) and type_id.startswith("space.") and type_id not in dictionary_ids:
                unresolved_component_ids.append(type_id)

    records: list[dict[str, Any]] = []
    records.append(_copy_exact(SITE_SOURCE, INPUTS_DIR / "site-facts.json"))
    records.append(_copy_exact(CONTEXT_SOURCE, INPUTS_DIR / "context-facts.json"))
    for fabric_id, source in fabric_sources.items():
        records.append(_copy_exact(source, INPUTS_DIR / "fabrics" / source.name))
    for entry_id in sorted(referenced_ids):
        source = dictionary_ids[entry_id]
        records.append(_copy_exact(source, INPUTS_DIR / "dictionary_entries" / source.name))

    fabric_repo_root = FABRIC_SOURCE_DIR
    manifest = {
        "schema_version": "fab1-input-snapshot-v1",
        "created_at_utc": utc_now(),
        "runner_version": RUNNER_VERSION,
        "fabric_ids": list(FABRIC_IDS),
        "files": records,
        "referenced_morphology_entry_ids": sorted(referenced_ids),
        "unresolved_component_dictionary_ids": sorted(set(unresolved_component_ids)),
        "morphology_dictionary_note_zh": (
            "MOR-T07 在 config/morphology-dictionary/entries 未找到；20–40 m 接縫寬度依 FAB1 任務輸入保留為假設，"
            "不標示為字典值。"
        ),
        "project_source_revision": repository_provenance(ROOT),
        "fabric_source_revision": repository_provenance(fabric_repo_root),
        "supersedes_manifest_sha256": sha256_file(OUTPUT_DIR / "inputs" / "manifest.json") if INPUTS_DIR != OUTPUT_DIR / "inputs" and (OUTPUT_DIR / "inputs" / "manifest.json").exists() else None,
    }
    write_json(manifest_path, manifest, pretty=True)
    return manifest


def snapshot_paths(manifest: Mapping[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for record in manifest["files"]:
        snapshot = OUTPUT_DIR / record["snapshot_path"]
        relative = Path(record["snapshot_path"])
        if relative.parts[-1:] == ("site-facts.json",):
            paths["site-facts"] = snapshot
        elif relative.parts[-1:] == ("context-facts.json",):
            paths["context-facts"] = snapshot
        elif "fabrics" in relative.parts and relative.name.startswith("fabric.") and relative.name.endswith(".json"):
            fabric_id = relative.name.removeprefix("fabric.").removesuffix(".json")
            paths[f"fabric:{fabric_id}"] = snapshot
    return paths


def load_frozen_run2_snapshot() -> dict[str, Any]:
    """Verify and copy the run-2 manifest while consuming its exact frozen bytes."""
    source_dir = OUTPUT_DIR / "run-2" / "inputs"
    source_manifest = source_dir / "manifest.json"
    if not source_manifest.is_file():
        raise FileNotFoundError(f"找不到 run-2 凍結輸入 manifest：{source_manifest}")
    manifest_bytes = source_manifest.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_hash != FAB1B_INPUT_MANIFEST_SHA256:
        raise ValueError(
            "run-2 manifest SHA-256 與凍結基準不符："
            f"需要 {FAB1B_INPUT_MANIFEST_SHA256}，實際 {manifest_hash}"
        )
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("schema_version") != "fab1-input-snapshot-v1":
        raise ValueError("run-2 輸入 manifest schema 不符。")
    if manifest.get("runner_version") != "fab1-runner-v2":
        raise ValueError("run-2 輸入 manifest 未由指定 runner 版本建立。")

    source_root = source_dir.resolve()
    seen_paths: set[Path] = set()
    recorded_names: set[str] = set()
    for record in manifest.get("files", []):
        relative_path = Path(str(record.get("snapshot_path", "")))
        snapshot = (OUTPUT_DIR / relative_path).resolve()
        try:
            snapshot.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(f"run-2 manifest 引用凍結快照目錄外路徑：{relative_path}") from exc
        if snapshot in seen_paths:
            raise ValueError(f"run-2 manifest 重複記錄同一快照路徑：{relative_path}")
        seen_paths.add(snapshot)
        if not snapshot.is_file():
            raise FileNotFoundError(f"run-2 凍結輸入缺檔：{snapshot}")
        actual_hash = sha256_file(snapshot)
        if actual_hash != record.get("snapshot_sha256"):
            raise ValueError(f"run-2 凍結輸入 SHA-256 不符：{snapshot}")
        if snapshot.stat().st_size != record.get("size_bytes"):
            raise ValueError(f"run-2 凍結輸入檔案大小不符：{snapshot}")
        recorded_names.add(relative_path.name)

    required_names = {
        "site-facts.json",
        "context-facts.json",
        *(f"fabric.{fabric_id}.json" for fabric_id in FABRIC_IDS),
    }
    if not required_names.issubset(recorded_names):
        missing = sorted(required_names - recorded_names)
        raise ValueError("run-2 快照缺少必要輸入：" + ", ".join(missing))
    dictionary_ids = set(manifest.get("referenced_morphology_entry_ids", []))
    snapshot_dictionary_ids = {
        str(load_json(path).get("id"))
        for path in seen_paths
        if path.parent == source_root / "dictionary_entries" and path.suffix == ".yaml"
    }
    missing_dictionary = sorted(dictionary_ids - snapshot_dictionary_ids)
    if missing_dictionary:
        raise ValueError("run-2 快照缺少 fabric 引用 dictionary entries：" + ", ".join(missing_dictionary))

    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    for snapshot in seen_paths:
        archived = INPUTS_DIR / snapshot.relative_to(source_root)
        archived.parent.mkdir(parents=True, exist_ok=True)
        frozen_bytes = snapshot.read_bytes()
        if archived.exists() and archived.read_bytes() != frozen_bytes:
            raise FileExistsError(f"拒絕覆寫本輪既有輸入快照：{archived}")
        if not archived.exists():
            archived.write_bytes(frozen_bytes)
    target_manifest = INPUTS_DIR / "manifest.json"
    if target_manifest.exists():
        if target_manifest.read_bytes() != manifest_bytes:
            raise FileExistsError(f"拒絕覆寫現有輸入 manifest：{target_manifest}")
    else:
        target_manifest.write_bytes(manifest_bytes)
    return manifest


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size=size, index=0)
            except OSError:
                continue
    raise RuntimeError("找不到繁體中文字型（PingFang / STHeiti / Hiragino）。")


def _font_path() -> str:
    for candidate in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ):
        if Path(candidate).is_file():
            try:
                font = ImageFont.truetype(candidate, size=32, index=0)
                # Fail closed if the chosen font cannot rasterize a Traditional
                # Chinese sample; availability alone is not a glyph check.
                if font.getmask("四種城市紋理方案").getbbox():
                    return candidate
            except OSError:
                continue
    raise RuntimeError("找不到可實際繪製繁體中文字的字型。")


FABRIC_LABELS_ZH = {
    "harbour_grain": "港埠線性紋理",
    "closed_block_extension": "圍合街廓延伸",
    "courtyard_islands": "大型院落島",
    "landscape_figure": "地景為圖",
}


LANDUSE_LABELS_ZH = {
    "retained_buildings": "保留建築",
    "roads": "道路",
    "waterfront": "水岸公共帶",
    "parks": "公園／綠地",
    "service": "服務空間",
    "blocks": "街廓／建築用地",
    "plazas": "廣場",
    "public_facilities": "公共設施",
    "residential": "住宅",
    "housing": "住宅",
    "industrial": "產業／工業",
    "commercial": "商業",
    "mixed_use": "混合使用",
    "building.rowhouse": "街屋",
    "building.industrial_hall": "產業廠房",
    "building.point_array": "點式住宅量體",
    "building.i_slab": "短翼板式量體",
    "building.courtyard_closed": "圍合院落量體",
    "building.u_block": "U 形院落量體",
    "building.courtyard_open_corner": "開角院落量體",
    "building.terraced": "連棟住宅",
    "block_edge_street": "街廓邊緣街道",
    "retained_city_road": "既有保留道路",
    "boundary_connector": "基地邊界連接街道",
    "waterfront_path": "水岸慢行路徑",
    "courtyard_service_gate": "院落服務通道",
    "courtyard_fire_lane": "院落消防巷",
    "retained_service_lane": "保留建物服務巷",
    "entrance_connector": "入口連接路徑",
    "network_connector": "道路網連接段",
    "primary_street": "主街",
    "facade_service_spur": "建築服務支路",
    "harbour_cross_lane": "港埠穿越窄巷",
    "park_edge_street": "公園臨街道路",
    "boundary_plot_service_lane": "邊界宗地服務通道",
    "park_maintenance_path": "公園維護通道",
}


def _fabric_label(fabric_id: str) -> str:
    return FABRIC_LABELS_ZH.get(fabric_id, fabric_id)


def _zh_label(value: Any) -> str:
    text = str(value)
    return LANDUSE_LABELS_ZH.get(text, text)


class MapTransform:
    def __init__(self, bounds: tuple[float, float, float, float], rect: tuple[int, int, int, int]):
        minx, miny, maxx, maxy = bounds
        left, top, width, height = rect
        self.bounds = bounds
        self.scale = min(width / max(maxx - minx, 1e-6), height / max(maxy - miny, 1e-6))
        self.width = (maxx - minx) * self.scale
        self.height = (maxy - miny) * self.scale
        self.left = left + (width - self.width) / 2
        self.top = top + (height - self.height) / 2

    def point(self, coord: Sequence[float]) -> tuple[int, int]:
        minx, miny, _, maxy = self.bounds
        x = self.left + (float(coord[0]) - minx) * self.scale
        y = self.top + (maxy - float(coord[1])) * self.scale
        return round(x), round(y)

    def line_width(self, width_m: float | None, fallback_px: int = 3) -> int:
        if width_m is None or not math.isfinite(float(width_m)) or float(width_m) <= 0:
            return fallback_px
        return max(1, round(float(width_m) * self.scale))


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _geometry_value(feature: Mapping[str, Any]) -> Any:
    return feature.get("geometry") or feature.get("footprint") or feature.get("geometry_geojson")


def _properties(feature: Mapping[str, Any]) -> dict[str, Any]:
    properties = feature.get("properties")
    return dict(properties) if isinstance(properties, Mapping) else {k: v for k, v in feature.items() if k != "geometry"}


def feature_rows(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        if value.get("type") == "FeatureCollection":
            value = value.get("features", [])
        elif value.get("type") == "Feature":
            value = [value]
        elif "features" in value and isinstance(value["features"], list):
            value = value["features"]
        else:
            value = [value]
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, Mapping) and _geometry_value(item):
            row = dict(item)
            row.setdefault("id", item.get("id", str(index + 1)))
            rows.append(row)
    return rows


def feature_shape(feature: Mapping[str, Any]) -> Any | None:
    raw = _geometry_value(feature)
    if not isinstance(raw, Mapping):
        return None
    try:
        geometry = shape(raw)
    except Exception:
        return None
    return geometry if not geometry.is_empty else None


def _shape_value(raw: Mapping[str, Any]) -> Any:
    """Accept a GeoJSON geometry or a GeoJSON Feature wrapper."""
    candidate = raw.get("geometry") if raw.get("type") == "Feature" else raw
    if not isinstance(candidate, Mapping):
        raise ValueError("GeoJSON geometry is missing")
    return shape(candidate)


def _polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [polygon for child in geometry.geoms for polygon in _polygon_parts(child)]
    if hasattr(geometry, "geoms"):
        return [polygon for child in geometry.geoms for polygon in _polygon_parts(child)]
    return []


def _line_parts(geometry: Any) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection) or hasattr(geometry, "geoms"):
        return [line for child in geometry.geoms for line in _line_parts(child)]
    return []


def _iter_lines(raw: Any) -> Iterable[list[Sequence[float]]]:
    if raw is None:
        return
    try:
        geometry = raw if hasattr(raw, "geom_type") else shape(raw)
    except Exception:
        return
    for line in _line_parts(geometry):
        yield list(line.coords)


def _draw_polygon(
    image: Image.Image,
    geometry: Any,
    transform: MapTransform,
    fill: tuple[int, int, int] | None,
    outline: tuple[int, int, int] | None,
    outline_width: int = 2,
) -> None:
    for polygon in _polygon_parts(geometry):
        if not polygon.is_valid:
            polygon = make_valid(polygon)
            subpolygons = _polygon_parts(polygon)
        else:
            subpolygons = [polygon]
        for part in subpolygons:
            if fill is not None:
                mask = Image.new("L", image.size, 0)
                mask_draw = ImageDraw.Draw(mask)
                exterior = [transform.point(point) for point in part.exterior.coords]
                mask_draw.polygon(exterior, fill=255)
                for ring in part.interiors:
                    hole = [transform.point(point) for point in ring.coords]
                    mask_draw.polygon(hole, fill=0)
                image.paste(fill, mask=mask)
            if outline is not None:
                draw = ImageDraw.Draw(image)
                draw.line([transform.point(point) for point in part.exterior.coords], fill=outline, width=outline_width, joint="curve")
                for ring in part.interiors:
                    draw.line([transform.point(point) for point in ring.coords], fill=outline, width=max(1, outline_width - 1), joint="curve")


def _draw_geometry(
    image: Image.Image,
    geometry: Any,
    transform: MapTransform,
    *,
    fill: tuple[int, int, int] | None = None,
    outline: tuple[int, int, int] | None = None,
    outline_width: int = 2,
) -> None:
    if geometry is None or geometry.is_empty:
        return
    parts = _polygon_parts(geometry)
    if parts:
        _draw_polygon(image, geometry, transform, fill, outline, outline_width)
        return
    draw = ImageDraw.Draw(image)
    for line in _line_parts(geometry):
        coords = [transform.point(point) for point in line.coords]
        if len(coords) >= 2:
            draw.line(coords, fill=outline or fill or (60, 60, 60), width=outline_width, joint="curve")
    if geometry.geom_type == "Point" and outline:
        x, y = transform.point((geometry.x, geometry.y))
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=outline)


def _site_geometries(facts: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    raw = facts.get("geometry", {})
    site_raw = raw.get("site")
    water_raw = raw.get("water")
    if not isinstance(site_raw, Mapping):
        raise ValueError("site-facts 缺少 geometry.site，不能定位 FAB1 圖面。")
    site = shape(site_raw)
    water = shape(water_raw) if isinstance(water_raw, Mapping) else GeometryCollection()
    land = site.difference(water)
    return site, water, land


def _site_bounds(site: Any) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = site.bounds
    padx = max(12.0, (maxx - minx) * 0.015)
    pady = max(12.0, (maxy - miny) * 0.015)
    return minx - padx, miny - pady, maxx + padx, maxy + pady


def _feature_label(properties: Mapping[str, Any], fallback: str = "未分類") -> str:
    for key in ("use_zh", "land_use_zh", "name_zh", "use", "land_use", "category", "class", "type_id", "building_type", "ground_use", "name", "role"):
        value = properties.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return _zh_label(value)
    return fallback


def _road_label(properties: Mapping[str, Any]) -> str:
    role = properties.get("role")
    if isinstance(role, str) and role:
        return _zh_label(role)
    hierarchy = properties.get("hierarchy")
    if isinstance(hierarchy, str) and hierarchy:
        return _zh_label(hierarchy)
    return "方案道路"


def _category_color(label: str) -> tuple[int, int, int]:
    key = label.casefold()
    palette = (
        (206, 136, 106), (118, 162, 173), (201, 169, 101), (127, 162, 119),
        (166, 137, 174), (199, 118, 120), (123, 145, 181), (177, 158, 132),
        (110, 155, 143), (190, 130, 99), (143, 149, 154), (178, 178, 112),
    )
    known = (
        (("park", "green", "landscape", "公園", "綠地", "地景"), (115, 166, 124)),
        (("plaza", "廣場"), (219, 184, 114)),
        (("water", "水岸", "promenade", "水面"), (131, 180, 199)),
        (("road", "street", "道路", "街道"), (182, 185, 188)),
        (("residential", "housing", "住宅"), (213, 150, 135)),
        (("industrial", "workspace", "work", "產業", "工業"), (129, 157, 169)),
        (("courtyard", "院落", "中庭"), (153, 181, 139)),
        (("service", "服務"), (166, 151, 128)),
    )
    for words, color in known:
        if any(word in key for word in words):
            return color
    return palette[int(hashlib.sha1(label.encode("utf-8")).hexdigest()[:8], 16) % len(palette)]


def _road_width(properties: Mapping[str, Any]) -> float | None:
    for key in ("width_m", "section_width_m", "right_of_way_width_m", "road_width_m", "width"):
        number = _finite_number(properties.get(key))
        if number is not None and number > 0:
            return number
    return None


MODE_COLORS = {
    "pedestrian": (38, 137, 91),
    "bicycle": (38, 113, 183),
    "car": (193, 79, 61),
}
MODE_LABELS_ZH = {"pedestrian": "步行", "bicycle": "自行車", "car": "汽車"}
ROAD_CLASS_ORDER = ("主街", "次街", "窄巷", "水岸公共帶", "服務通道", "連接路徑", "保留道路", "其他道路")
ROAD_CLASS_COLORS = {
    "主街": (30, 67, 109),
    "次街": (86, 109, 123),
    "窄巷": (151, 144, 126),
    "水岸公共帶": (37, 137, 172),
    "服務通道": (146, 126, 94),
    "連接路徑": (128, 139, 142),
    "保留道路": (111, 75, 58),
    "其他道路": (117, 119, 117),
}
ROAD_SURFACE_COLOR = (161, 158, 151)


def _road_class_label(properties: Mapping[str, Any]) -> str:
    role = str(properties.get("role", "")).casefold()
    hierarchy = _finite_number(properties.get("hierarchy"))
    width_m = _road_width(properties)
    if role == "waterfront_path":
        return "水岸公共帶"
    if any(token in role for token in ("service", "fire_lane", "maintenance")):
        return "服務通道"
    if "retain" in role and "service" in role:
        return "服務通道"
    if "retain" in role:
        return "保留道路"
    if role == "primary_street" or hierarchy == 0:
        return "主街"
    if hierarchy == 1:
        return "次街"
    alley_role = any(token in role for token in ("narrow_alley", "public_alley", "pedestrian_alley", "harbour_cross_lane"))
    if alley_role and width_m is not None and 6 <= width_m <= 8:
        return "窄巷"
    if hierarchy is not None and hierarchy >= 2:
        return "連接路徑"
    return "其他道路"


def _road_modes(properties: Mapping[str, Any]) -> list[str]:
    raw = properties.get("modes", properties.get("allowed_modes", []))
    values = [raw] if isinstance(raw, str) else raw
    if not isinstance(values, (list, tuple, set)):
        return []
    aliases = {"walk": "pedestrian", "walking": "pedestrian", "cycle": "bicycle", "cycling": "bicycle", "motor_vehicle": "car", "automobile": "car"}
    normalized = {aliases.get(str(value).casefold(), str(value).casefold()) for value in values}
    return [mode for mode in ("pedestrian", "bicycle", "car") if mode in normalized]


def _draw_mode_access_strokes(
    draw: ImageDraw.ImageDraw,
    coords: Sequence[Sequence[float]],
    modes: Sequence[str],
    transform: MapTransform,
) -> int:
    """Draw every allowed mode along the full route, with parallel display offsets.

    The offsets are purely cartographic: they keep overlapping mode networks
    visible and do not represent lane location or width.
    """
    if not modes or len(coords) < 2:
        return 0
    points = [transform.point(point) for point in coords]
    normalized_modes = [mode for mode in ("pedestrian", "bicycle", "car") if mode in modes]
    if not normalized_modes:
        return 0
    offsets = {
        1: (0.0,),
        2: (-1.5, 1.5),
        3: (-3.0, 0.0, 3.0),
    }[len(normalized_modes)]

    def offset_points(offset: float) -> list[tuple[int, int]]:
        if not offset:
            return points
        result: list[tuple[int, int]] = []
        for index, point in enumerate(points):
            normals: list[tuple[float, float]] = []
            for start, end in (
                (points[index - 1], point) if index else (point, points[min(1, len(points) - 1)]),
                (point, points[index + 1]) if index + 1 < len(points) else (points[max(0, index - 1)], point),
            ):
                dx, dy = end[0] - start[0], end[1] - start[1]
                length = math.hypot(dx, dy)
                if length > 0:
                    normals.append((-dy / length, dx / length))
            if not normals:
                result.append(point)
                continue
            nx = sum(value[0] for value in normals)
            ny = sum(value[1] for value in normals)
            normal_length = math.hypot(nx, ny)
            if normal_length <= 1e-9:
                nx, ny = normals[-1]
                normal_length = 1.0
            nx, ny = nx / normal_length, ny / normal_length
            scale = min(abs(offset) * 2.0, abs(offset) / max(0.35, abs(nx * normals[-1][0] + ny * normals[-1][1])))
            direction = 1.0 if offset > 0 else -1.0
            result.append((round(point[0] + nx * scale * direction), round(point[1] + ny * scale * direction)))
        return result

    drawn_segments = 0
    for mode, offset in zip(normalized_modes, offsets):
        shifted = offset_points(offset)
        draw.line(shifted, fill=MODE_COLORS[mode], width=2, joint="curve")
        drawn_segments += max(0, len(shifted) - 1)
    return drawn_segments


def _draw_roads(
    image: Image.Image,
    roads: Sequence[Mapping[str, Any]],
    transform: MapTransform,
    *,
    draw_mode_networks: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    draw = ImageDraw.Draw(image)
    grouped: dict[str, dict[str, Any]] = {}
    mode_feature_paths_drawn = 0
    mode_network_segments_drawn = 0
    mode_route_feature_counts = Counter()
    mode_routes: list[tuple[LineString, list[str]]] = []
    for road in roads:
        geom = feature_shape(road)
        props = _properties(road)
        label = _road_class_label(props)
        color = ROAD_SURFACE_COLOR
        width_m = _road_width(props)
        record = grouped.setdefault(label, {"label": label, "color": color, "widths_m": set(), "feature_count": 0})
        record["feature_count"] += 1
        if width_m is not None:
            record["widths_m"].add(width_m)
        right_of_way = props.get("right_of_way")
        if isinstance(right_of_way, Mapping):
            try:
                _draw_geometry(image, _shape_value(right_of_way), transform, fill=ROAD_SURFACE_COLOR, outline=(130, 128, 121), outline_width=1)
            except Exception:
                pass
        if geom is not None:
            if _polygon_parts(geom):
                _draw_geometry(image, geom, transform, fill=color, outline=(130, 128, 121), outline_width=1)
            else:
                for line in _line_parts(geom):
                    coords = [transform.point(point) for point in line.coords]
                    if len(coords) > 1:
                        draw.line(coords, fill=color, width=transform.line_width(width_m, fallback_px=3), joint="curve")
                        modes = _road_modes(props)
                        if draw_mode_networks and modes:
                            mode_routes.append((line, modes))
    # Draw mode networks after every neutral road surface so later road
    # polygons cannot hide an earlier allowed route.
    for line, modes in mode_routes:
        mode_network_segments_drawn += _draw_mode_access_strokes(draw, list(line.coords), modes, transform)
        mode_feature_paths_drawn += len(modes)
        mode_route_feature_counts.update(modes)
    result = []
    for label in ROAD_CLASS_ORDER:
        record = grouped.get(label)
        if not record:
            continue
        widths = sorted(record["widths_m"])
        if not widths:
            width_text = "未提供"
        elif len(widths) == 1:
            width_text = f"{widths[0]:g} m"
        elif len(widths) == 2:
            width_text = f"{widths[0]:g}／{widths[1]:g} m"
        else:
            width_text = f"{widths[0]:g}–{widths[-1]:g} m"
        result.append({**record, "width_text": width_text, "widths_m": widths})
    return result, {
        "mode_overlay_enabled": draw_mode_networks,
        "mode_overlay_feature_paths_drawn": mode_feature_paths_drawn,
        "mode_overlay_line_segments_drawn": mode_network_segments_drawn,
        "mode_route_feature_counts": dict(sorted(mode_route_feature_counts.items())),
    }


def _courtyard_features(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    return feature_rows(plan.get("courtyards"))


def _draw_courtyard_markers(
    image: Image.Image,
    courtyards: Sequence[Mapping[str, Any]],
    transform: MapTransform,
) -> list[dict[str, Any]]:
    draw = ImageDraw.Draw(image)
    font = _font(14)
    audit_rows = []
    for index, feature in enumerate(courtyards):
        geometry = feature_shape(feature)
        if geometry is None:
            continue
        point = geometry if geometry.geom_type == "Point" else geometry.representative_point()
        x, y = transform.point((point.x, point.y))
        radius = 13
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=(44, 124, 83), outline=(250, 249, 244), width=2)
        props = _properties(feature)
        audit_rows.append({
            "label_zh": props.get("label_zh", "未提供"),
            "block_id": props.get("block_id", "未提供"),
            "feature_id": _feature_identity(feature, index),
        })
    return audit_rows


def _draw_landuse_labels(
    image: Image.Image,
    landuse: Sequence[Mapping[str, Any]],
    transform: MapTransform,
) -> list[dict[str, Any]]:
    """Label the largest legible polygon for each land-use category."""
    largest: dict[str, tuple[float, Mapping[str, Any], Any]] = {}
    for feature in landuse:
        geometry = feature_shape(feature)
        if geometry is None or not _polygon_parts(geometry):
            continue
        properties = _properties(feature)
        category = str(properties.get("category", _feature_label(properties)))
        if category not in {"parks", "plazas", "waterfront"}:
            continue
        area = float(geometry.area)
        if area < 900.0:
            continue
        if category not in largest or area > largest[category][0]:
            largest[category] = (area, feature, geometry)

    draw = ImageDraw.Draw(image)
    font = _font(16)
    labels: list[dict[str, Any]] = []
    for category, (_area, feature, geometry) in sorted(largest.items()):
        properties = _properties(feature)
        label = {"parks": "主要公園", "plazas": "主要廣場", "waterfront": "水岸公共帶"}[category]
        point = geometry.representative_point()
        x, y = transform.point((point.x, point.y))
        draw.text((x, y), label, font=font, fill=(44, 49, 48), anchor="mm", stroke_width=2, stroke_fill=(246, 244, 237))
        labels.append({
            "feature_id": _feature_identity(feature, 0),
            "category": category,
            "label_zh": label,
            "position_px": [x, y],
        })
    return labels


def _first_finite_property(properties: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = _finite_number(properties.get(key))
        if value is not None:
            return value
    return None


def _detour_label(properties: Mapping[str, Any]) -> str:
    width = _first_finite_property(properties, ("width_m", "route_width_m"))
    length = _first_finite_property(properties, ("route_length_m", "length_m"))
    return f"水岸替代步行路徑｜寬 {_fmt(width)} 公尺、長 {_fmt(length)} 公尺"


def _feature_numeric_values_text(
    features: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
    *,
    digits: int = 1,
) -> str:
    if not features:
        return "無"
    values = [_first_finite_property(_properties(feature), keys) for feature in features]
    return "；".join(_fmt(value, digits) for value in values)


def _feature_route_labels_text(features: Sequence[Mapping[str, Any]]) -> str:
    if not features:
        return "無"
    labels = []
    for feature in features:
        properties = _properties(feature)
        label = properties.get("label_zh") or properties.get("name_zh")
        labels.append(str(label) if label else "未提供")
    return "；".join(labels)


def _feature_route_lengths_text(features: Sequence[Mapping[str, Any]]) -> str:
    if not features:
        return "無"
    values = []
    for feature in features:
        properties = _properties(feature)
        length = _first_finite_property(properties, ("route_length_m", "detour_length_m", "path_length_m", "length_m"))
        if length is None:
            line_parts = _line_parts(feature_shape(feature))
            if line_parts:
                length = sum(float(line.length) for line in line_parts)
        values.append(_fmt(length, 1))
    return "；".join(values)


def _detour_endpoints_obstructions_text(features: Sequence[Mapping[str, Any]]) -> str:
    if not features:
        return "無"
    parts: list[str] = []
    for index, feature in enumerate(features):
        properties = _properties(feature)
        endpoints = properties.get("gap_endpoints", properties.get("gap_endpoint_ids"))
        if isinstance(endpoints, (list, tuple)) and len(endpoints) >= 2:
            endpoint_text = f"{endpoints[0]}→{endpoints[1]}"
        elif isinstance(properties.get("gap_start_id"), str) and isinstance(properties.get("gap_end_id"), str):
            endpoint_text = f"{properties['gap_start_id']}→{properties['gap_end_id']}"
        else:
            endpoint_text = "端點未提供"
        obstructions = properties.get("obstructions", properties.get("obstruction_ids", []))
        if isinstance(obstructions, str):
            obstruction_values = [obstructions]
        elif isinstance(obstructions, (list, tuple)):
            obstruction_values = [str(value.get("id", value.get("name_zh", "未提供"))) if isinstance(value, Mapping) else str(value) for value in obstructions]
        else:
            obstruction_values = []
        obstruction_text = "、".join(obstruction_values) if obstruction_values else "障礙物未提供"
        parts.append(f"路徑{index + 1}：{endpoint_text}；{obstruction_text}")
    return "；".join(parts)


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[int, int]],
    *,
    fill: tuple[int, int, int],
    width: int,
    dash_px: float = 10.0,
    gap_px: float = 6.0,
) -> int:
    drawn = 0
    for start, end in zip(points, points[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 0:
            continue
        step = dash_px + gap_px
        position = 0.0
        while position < length:
            finish = min(length, position + dash_px)
            p0 = (round(start[0] + dx * position / length), round(start[1] + dy * position / length))
            p1 = (round(start[0] + dx * finish / length), round(start[1] + dy * finish / length))
            draw.line((p0, p1), fill=fill, width=width)
            drawn += 1
            position += step
    return drawn


def _draw_waterfront_detours(
    image: Image.Image,
    detours: Sequence[Mapping[str, Any]],
    transform: MapTransform,
) -> dict[str, Any]:
    draw = ImageDraw.Draw(image)
    line_color = (125, 67, 139)
    text_font = _font(15)
    drawn_ids: list[str] = []
    label_records: list[dict[str, Any]] = []
    line_part_count = 0
    dash_count = 0
    missing_line_ids: list[str] = []
    for index, feature in enumerate(detours):
        geometry = feature_shape(feature)
        line_parts = _line_parts(geometry)
        feature_id = _feature_identity(feature, index)
        if not line_parts:
            missing_line_ids.append(feature_id)
            continue
        drawn_ids.append(feature_id)
        properties = _properties(feature)
        label = _detour_label(properties)
        anchor: tuple[int, int] | None = None
        for line in line_parts:
            points = [transform.point(point) for point in line.coords]
            if len(points) < 2:
                continue
            dash_count += _draw_dashed_line(draw, points, fill=line_color, width=5)
            line_part_count += 1
            midpoint = line.interpolate(line.length / 2)
            anchor = transform.point((midpoint.x, midpoint.y))
        if anchor is None:
            continue
        # Two-line annotation keeps the route label explicit without hiding its
        # source properties in a dense side legend.
        draw.text(anchor, label, font=text_font, fill=line_color, anchor="mm", stroke_width=3, stroke_fill=(250, 249, 244))
        label_records.append({"feature_id": feature_id, "label_zh": label, "position_px": list(anchor)})
    return {
        "feature_count": len(detours),
        "drawn_feature_ids": drawn_ids,
        "line_part_count": line_part_count,
        "dash_count": dash_count,
        "missing_line_geometry_ids": missing_line_ids,
        "labels": label_records,
        "render_status": "PASS" if not missing_line_ids and len(drawn_ids) == len(detours) else "FAIL",
    }


def _draw_service_facilities(
    image: Image.Image,
    facilities: Sequence[Mapping[str, Any]],
    transform: MapTransform,
) -> list[dict[str, Any]]:
    draw = ImageDraw.Draw(image)
    font = _font(13)
    records: list[dict[str, Any]] = []
    for index, feature in enumerate(facilities):
        geometry = feature_shape(feature)
        properties = _properties(feature)
        feature_id = _feature_identity(feature, index)
        label = str(properties.get("name_zh") or "服務設施")
        if geometry is None:
            records.append({
                "feature_id": feature_id,
                "function": properties.get("function", "未提供"),
                "name_zh": label,
                "serves_allocation_id": properties.get("serves_allocation_id", "未提供"),
                "render_status": "FAIL",
                "reason": "missing_geometry",
            })
            continue
        point = geometry if geometry.geom_type == "Point" else geometry.representative_point()
        x, y = transform.point((point.x, point.y))
        radius = 6
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(97, 70, 45), outline=(249, 247, 240), width=2)
        records.append({
            "feature_id": feature_id,
            "symbol_only": True,
            "function": properties.get("function", "未提供"),
            "name_zh": label,
            "serves_allocation_id": properties.get("serves_allocation_id", "未提供"),
            "position_px": [x, y],
            "render_status": "PASS",
        })
    return records


def _south_quay_feature(plan: Mapping[str, Any]) -> dict[str, Any] | None:
    value = plan.get("south_quay_band")
    rows = feature_rows(value)
    return rows[0] if rows else None


def _draw_south_quay_band_label(
    image: Image.Image,
    feature: Mapping[str, Any] | None,
    transform: MapTransform,
) -> dict[str, Any] | None:
    if feature is None:
        return None
    geometry = feature_shape(feature)
    if geometry is None:
        return {"feature_id": _feature_identity(feature, 0), "render_status": "FAIL", "reason": "missing_geometry"}
    point = geometry.representative_point()
    x, y = transform.point((point.x, point.y))
    properties = _properties(feature)
    label = str(properties.get("label_zh") or "南岸碼頭帶")
    draw = ImageDraw.Draw(image)
    boundary_segments = 0
    for polygon in _polygon_parts(geometry):
        for ring in (polygon.exterior, *polygon.interiors):
            boundary_segments += _draw_dashed_line(
                draw,
                [transform.point(coord) for coord in ring.coords],
                fill=(126, 100, 63),
                width=2,
                dash_px=7,
                gap_px=4,
            )
    for line in _line_parts(geometry):
        boundary_segments += _draw_dashed_line(
            draw,
            [transform.point(coord) for coord in line.coords],
            fill=(126, 100, 63),
            width=2,
            dash_px=7,
            gap_px=4,
        )
    draw.text((x, y), label, font=_font(16), fill=(79, 71, 55), anchor="mm", stroke_width=3, stroke_fill=(246, 244, 237))
    return {
        "feature_id": _feature_identity(feature, 0),
        "label_zh": label,
        "position_px": [x, y],
        "frontage_axis_azimuth_deg": properties.get("frontage_axis_azimuth_deg", "未提供"),
        "boundary_segments_drawn": boundary_segments,
        "render_status": "PASS",
    }


def _budget_interval(value: Any) -> tuple[float, float] | None:
    if isinstance(value, Mapping):
        low = _finite_number(value.get("minimum"))
        high = _finite_number(value.get("maximum"))
        if low is None:
            low = _finite_number(value.get("value", value.get("target_percent")))
        if high is None:
            high = low
        if low is not None and high is not None:
            return min(low, high), max(low, high)
    number = _finite_number(value)
    return (number, number) if number is not None else None


def _percent_interval_text(interval: tuple[float, float] | None) -> str:
    if interval is None:
        return "未提供"
    low, high = interval
    return f"{low:.1f}%" if math.isclose(low, high) else f"{low:.1f}–{high:.1f}%"


def _budget_override_relation(
    dictionary_range: tuple[float, float] | None,
    user_override: tuple[float, float] | None,
) -> str:
    if user_override is None:
        return "無覆寫"
    if dictionary_range is None:
        return "字典未提供，無法判定"
    if user_override[1] < dictionary_range[0] or user_override[0] > dictionary_range[1]:
        return "與字典範圍衝突"
    return "有覆寫；範圍有交集"


def _intent_landuse_override(intent: Mapping[str, Any], category: str) -> tuple[float, float] | None:
    for key in ("land_use_budget_override", "land_use_budget"):
        value = intent.get(key)
        if isinstance(value, Mapping) and category in value:
            result = _budget_interval(value[category])
            if result is not None:
                return result
    return None


def _draw_landuse_budget_chart(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    width: int,
    plan: Mapping[str, Any],
    land_area_m2: float,
    fabric: Mapping[str, Any],
    intent: Mapping[str, Any],
    label_font: ImageFont.FreeTypeFont,
    small_font: ImageFont.FreeTypeFont,
) -> tuple[int, list[dict[str, Any]]]:
    categories = (
        ("roads", "道路"), ("blocks", "建築街廓"), ("parks", "公園／綠地"), ("plazas", "廣場"),
        ("waterfront", "水岸步道"), ("service", "服務／卸貨"), ("retained_buildings", "保留建築基地"),
        ("public_facilities", "公共設施"),
    )
    budget = fabric.get("land_use_budget", {}) if isinstance(fabric.get("land_use_budget"), Mapping) else {}
    areas = _landuse_area_by_category(plan)
    max_percent = 60.0
    bar_width = max(150, width - 12)
    rows = []
    row_y = y
    for category, label in categories:
        area = _finite_number(areas.get(category, 0.0)) or 0.0
        actual = 100.0 * area / land_area_m2 if land_area_m2 > 0 else None
        interval = _budget_interval(budget.get(category))
        override = _intent_landuse_override(intent, category)
        actual_text = f"{actual:.1f}%" if actual is not None else "未提供"
        if interval is None:
            dictionary_text = "字典 未提供"
        elif math.isclose(interval[0], interval[1]):
            dictionary_text = f"字典 {interval[0]:.1f}%"
        else:
            dictionary_text = f"字典 {interval[0]:.1f}–{interval[1]:.1f}%"
        if override is None:
            override_text = "覆寫 無"
        elif math.isclose(override[0], override[1]):
            override_text = f"覆寫 {override[0]:.1f}%"
        else:
            override_text = f"覆寫 {override[0]:.1f}–{override[1]:.1f}%"
        override_conflicts = bool(
            interval is not None
            and override is not None
            and (override[1] < interval[0] or override[0] > interval[1])
        )
        if override_conflicts:
            override_text += "（衝突）"
        draw.text((x, row_y), label, font=label_font, fill=(49, 57, 60))
        right = x + width
        actual_bbox = draw.textbbox((0, 0), actual_text, font=label_font)
        draw.text((right - (actual_bbox[2] - actual_bbox[0]), row_y), actual_text, font=label_font, fill=(49, 57, 60))
        draw.text((x, row_y + 23), f"{dictionary_text}｜{override_text}", font=small_font, fill=(97, 101, 101))
        track_y = row_y + 47
        draw.rectangle((x, track_y, x + bar_width, track_y + 9), fill=(228, 226, 219))
        scale = bar_width / max_percent
        if interval is not None:
            x0 = x + round(max(0.0, min(max_percent, interval[0])) * scale)
            x1 = x + round(max(0.0, min(max_percent, interval[1])) * scale)
            draw.rectangle((x0, track_y + 1, max(x0 + 2, x1), track_y + 8), fill=(133, 177, 197))
        if actual is not None:
            actual_x = x + round(max(0.0, min(max_percent, actual)) * scale)
            draw.line((x, track_y + 4, max(x + 1, actual_x), track_y + 4), fill=_category_color(label), width=3)
            if actual > max_percent:
                draw.polygon(((x + bar_width, track_y - 2), (x + bar_width + 7, track_y + 4), (x + bar_width, track_y + 11)), fill=_category_color(label))
        if override is not None:
            for value in set(override):
                override_x = x + round(max(0.0, min(max_percent, value)) * scale)
                draw.line((override_x, track_y - 3, override_x, track_y + 12), fill=(127, 88, 149), width=2)
        rows.append({
            "category": category,
            "actual_percent_of_land": actual,
            "dictionary_range_percent": list(interval) if interval is not None else None,
            "user_override_percent": list(override) if override is not None else None,
            "override_conflicts_dictionary": override_conflicts if override is not None and interval is not None else None,
        })
        row_y += 67
    return row_y, rows


def render_landuse_budget_chart(
    path: Path,
    *,
    plan: Mapping[str, Any],
    facts: Mapping[str, Any],
    fabric: Mapping[str, Any],
    intent: Mapping[str, Any],
    fabric_label: str,
) -> dict[str, Any]:
    image = Image.new("RGB", (1600, 1000), (249, 248, 244))
    draw = ImageDraw.Draw(image)
    draw.text((54, 30), f"{fabric_label}｜土地使用占比與字典預算", font=_font(39), fill=(35, 44, 49))
    draw.text((58, 91), "實色條＝plan 實際面積比例；藍帶＝字典範圍；紫線＝使用者覆寫。", font=_font(23), fill=(75, 82, 84))
    draw.text((58, 132), "分母：site facts 陸地面積｜比例為圖徵面積加總；有類別重疊時不可相加視為互斥預算。", font=_font(18), fill=(89, 94, 95))
    land_area = _finite_number(facts.get("site", {}).get("land_area_m2")) or 0.0
    chart_end, rows = _draw_landuse_budget_chart(
        draw,
        x=68,
        y=188,
        width=1460,
        plan=plan,
        land_area_m2=land_area,
        fabric=fabric,
        intent=intent,
        label_font=_font(27),
        small_font=_font(19),
    )
    x, bar_width, scale = 68, 1448, 1448 / 60.0
    axis_y = chart_end + 3
    draw.line((x, axis_y, x + bar_width, axis_y), fill=(95, 99, 99), width=1)
    for tick in (0, 15, 30, 45, 60):
        xx = x + round(tick * scale)
        draw.line((xx, axis_y - 4, xx, axis_y + 5), fill=(95, 99, 99), width=1)
        draw.text((xx, axis_y + 7), f"{tick}%", font=_font(16), fill=(89, 94, 95), anchor="mt")
    draw.text((58, 900), "字典來源：凍結 `fabric.<方案>.json` 的 `land_use_budget`（editorial 範圍）。", font=_font(18), fill=(82, 88, 90))
    draw.text((58, 932), "使用者覆寫：intent `land_use_budget_override`／`land_use_budget`；與字典範圍不相交時標示「衝突」。", font=_font(18), fill=(82, 88, 90))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    return {
        "file": path.name,
        "canvas_size_px": [1600, 1000],
        "category_rows": rows,
        "denominator": "site facts land_area_m2",
        "dictionary_source": "frozen fabric.<fabric_id>.json.land_use_budget; editorial range",
        "user_override_source": "intent.land_use_budget_override or intent.land_use_budget",
    }


def _draw_north_and_scale(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], transform: MapTransform, small_font: ImageFont.FreeTypeFont) -> None:
    left, top, width, _ = rect
    nx, ny = left + width - 38, top + 30
    draw.line((nx, ny + 30, nx, ny + 4), fill=(40, 49, 55), width=4)
    draw.polygon(((nx, ny - 2), (nx - 9, ny + 12), (nx + 9, ny + 12)), fill=(40, 49, 55))
    draw.text((nx - 10, ny + 34), "N", font=small_font, fill=(40, 49, 55))
    # Use a round, visible ground distance that fits in about 20% of the map.
    target_m = max(25.0, (width / transform.scale) * 0.18)
    power = 10 ** math.floor(math.log10(target_m))
    unit = target_m / power
    nice = (1 if unit < 1.5 else 2 if unit < 3.5 else 5 if unit < 7.5 else 10) * power
    bar_px = max(30, round(nice * transform.scale))
    x0, y0 = rect[0] + 20, rect[1] + rect[3] - 36
    draw.line((x0, y0, x0 + bar_px, y0), fill=(45, 50, 52), width=6)
    draw.line((x0, y0 - 6, x0, y0 + 6), fill=(45, 50, 52), width=3)
    draw.line((x0 + bar_px, y0 - 6, x0 + bar_px, y0 + 6), fill=(45, 50, 52), width=3)
    draw.text((x0, y0 - 27), f"{nice:g} m", font=small_font, fill=(45, 50, 52))


def _map_image(
    *,
    title: str,
    note: str,
    facts: Mapping[str, Any],
    plan: Mapping[str, Any],
    canvas_size: tuple[int, int] = (2800, 1600),
    fixed_bounds: tuple[float, float, float, float] | None = None,
    mode: str = "landuse",
    fabric: Mapping[str, Any] | None = None,
    intent: Mapping[str, Any] | None = None,
    show_side_panel: bool = True,
    render_audit: dict[str, Any] | None = None,
) -> Image.Image:
    width, height = canvas_size
    image = Image.new("RGB", canvas_size, (248, 247, 242))
    draw = ImageDraw.Draw(image)
    title_font, body_font, small_font = _font(42), _font(24), _font(19)
    draw.text((48, 28), title, font=title_font, fill=(35, 44, 49))
    draw.text((50, 82), note, font=small_font, fill=(89, 94, 95))
    site, water, land = _site_geometries(facts)
    bounds = fixed_bounds or _site_bounds(site)
    map_rect = (52, 140, width - 520, height - 220) if show_side_panel else (42, 130, width - 84, height - 190)
    transform = MapTransform(bounds, map_rect)
    _draw_geometry(image, site, transform, fill=(238, 235, 225), outline=(67, 77, 81), outline_width=3)
    _draw_geometry(image, water, transform, fill=(194, 222, 230), outline=(116, 160, 174), outline_width=1)

    roads = feature_rows(plan.get("roads"))
    available_modes = sorted({mode_key for road in roads for mode_key in _road_modes(_properties(road))}, key=("pedestrian", "bicycle", "car").index)
    blocks = feature_rows(plan.get("blocks"))
    parcels = feature_rows(plan.get("boundary_parcels"))
    buildings = feature_rows(plan.get("buildings"))
    landuse = feature_rows(plan.get("land_use"))
    courtyards = _courtyard_features(plan)
    detours = feature_rows(plan.get("waterfront_detours"))
    service_facilities = feature_rows(plan.get("service_facilities"))
    south_quay_band = _south_quay_feature(plan)
    retained_geom = facts.get("geometry", {}).get("retained_buildings", [])

    landuse_labels = sorted({_feature_label(_properties(feature)) for feature in landuse})
    color_by_label = {label: _category_color(label) for label in landuse_labels}
    if mode in {"landuse", "mobility"}:
        for feature in landuse:
            geom = feature_shape(feature)
            if geom is None:
                continue
            label = _feature_label(_properties(feature))
            _draw_geometry(image, geom, transform, fill=color_by_label[label], outline=(247, 244, 236), outline_width=1)
    if mode == "massing":
        # Green open space remains readable without cadastral construction lines.
        for feature in landuse:
            if _properties(feature).get("category") == "parks":
                geom = feature_shape(feature)
                if geom is not None:
                    _draw_geometry(image, geom, transform, fill=_category_color("公園／綠地"), outline=None)
    road_legend, road_render_audit = _draw_roads(
        image,
        roads,
        transform,
        draw_mode_networks=(mode == "mobility"),
    )
    if mode == "massing":
        for feature in buildings:
            geom = feature_shape(feature)
            if geom is None:
                continue
            properties = _properties(feature)
            height_m = _building_height_m(properties, facts)[0]
            retained = "retain" in str(properties.get("role", properties.get("status", ""))).casefold() or bool(properties.get("preserved")) or bool(properties.get("retained"))
            if retained:
                color = (103, 103, 99)
            else:
                color = _height_color(height_m)
            _draw_geometry(image, geom, transform, fill=color, outline=(53, 60, 64), outline_width=1)
    else:
        for feature in buildings:
            geom = feature_shape(feature)
            if geom is not None:
                props = _properties(feature)
                retained = "retain" in str(props.get("role", props.get("status", ""))).casefold() or bool(props.get("preserved")) or bool(props.get("retained"))
                color = (103, 103, 99) if retained else _height_color(_building_height_m(props, facts)[0])
                _draw_geometry(image, geom, transform, fill=color, outline=(119, 105, 91), outline_width=1)
        # Historical retained footprints remain visible when the generated
        # plan does not include preserved features as GeoJSON buildings.
        plan_ids = {str(feature.get("id")) for feature in buildings}
        for index, retained in enumerate(retained_geom):
            raw = retained.get("geometry") if isinstance(retained, Mapping) else None
            if not isinstance(raw, Mapping) or str(retained.get("id")) in plan_ids:
                continue
            try:
                _draw_geometry(image, shape(raw), transform, fill=(150, 147, 139), outline=(70, 71, 70), outline_width=2)
            except Exception:
                continue

    courtyard_audit = (_draw_courtyard_markers(image, courtyards, transform) if mode == "mobility" else {"feature_count": len(courtyards), "render_status": "NOT_RENDERED", "reason_zh": "內院留白；避免公園綠色與院落符號混淆"})

    landuse_label_audit = _draw_landuse_labels(image, landuse, transform) if mode in {"landuse", "mobility"} and show_side_panel else []
    service_facility_audit = _draw_service_facilities(image, service_facilities, transform) if mode in {"landuse", "mobility"} else []
    south_quay_label_audit = _draw_south_quay_band_label(image, south_quay_band, transform) if mode in {"landuse", "mobility"} and show_side_panel else None
    detour_audit = _draw_waterfront_detours(image, detours, transform) if mode in {"landuse", "mobility"} and show_side_panel else {
        "feature_count": len(detours), "drawn_feature_ids": [], "line_part_count": 0, "dash_count": 0,
        "missing_line_geometry_ids": [], "labels": [], "render_status": "NOT_RENDERED",
    }
    mobility_overlay_absent = (
        road_render_audit.get("mode_overlay_enabled") is False
        and road_render_audit.get("mode_overlay_feature_paths_drawn") == 0
        and road_render_audit.get("mode_overlay_line_segments_drawn") == 0
    )

    if mode in {'massing', 'landuse'}:
        number_font=_font(12)
        for feature in buildings:
            props=_properties(feature);geom=feature_shape(feature)
            if geom is None:continue
            count=props.get('floors')
            if 'retain' in str(props.get('role', props.get('status', ''))).casefold() or props.get('retained') or props.get('preserved'):label='R'
            elif isinstance(count,(int,float)):label=str(int(count))+('M' if props.get('mezzanine_geometry') else '')
            else:continue
            xy=transform.point(geom.representative_point().coords[0])
            draw.text(xy,label,font=number_font,fill=(20,25,28),anchor='mm',stroke_width=1,stroke_fill=(242,239,230))
    _draw_north_and_scale(draw, map_rect, transform, small_font)
    legend_x, legend_y = width - 445, 150
    side_width = width - legend_x - 24
    metrics = plan.get("metrics", {}) if isinstance(plan.get("metrics"), Mapping) else {}
    budget_rows = []
    if show_side_panel:
        draw.text((legend_x, legend_y), "圖例與土地使用對照", font=body_font, fill=(42, 51, 56))
        legend_y += 40
        if mode in {"landuse", "mobility"}:
            for feature in landuse:
                label = _feature_label(_properties(feature))
                color_by_label.setdefault(label, _category_color(label))
            draw.rectangle((legend_x, legend_y + 2, legend_x + 20, legend_y + 21), fill=(194, 222, 230), outline=(116, 160, 174))
            draw.text((legend_x + 30, legend_y), "水域（不計入陸地分母）", font=small_font, fill=(55, 61, 63))
            legend_y += 30
        elif mode == "massing":
            for label, color in (("低層量體", _height_color(6)), ("中層量體", _height_color(12)), ("較高量體", _height_color(19)), ("保留建築", (103, 103, 99))):
                draw.rectangle((legend_x, legend_y + 2, legend_x + 20, legend_y + 21), fill=color, outline=(108, 108, 100))
                draw.text((legend_x + 30, legend_y), label, font=small_font, fill=(55, 61, 63))
                legend_y += 28
        if mode == "mobility":
            draw.text((legend_x, legend_y), "底圖：土地使用、建築與道路", font=small_font, fill=(55, 61, 63))
            legend_y += 30
        draw.text((legend_x, legend_y + 2), "道路層級／實際 plan 寬度", font=small_font, fill=(55, 61, 63))
        legend_y += 28
        for record in road_legend:
            class_widths = record["widths_m"]
            exemplar_width_m = (class_widths[0] + class_widths[-1]) / 2 if class_widths else None
            sample_width_px = min(12, transform.line_width(exemplar_width_m, fallback_px=3))
            draw.line((legend_x, legend_y + 10, legend_x + 25, legend_y + 10), fill=record["color"], width=sample_width_px)
            draw.text((legend_x + 34, legend_y), f"{record['label']} · {record['width_text']}", font=small_font, fill=(55, 61, 63))
            legend_y += 26
        if mode == "mobility":
            draw.text((legend_x, legend_y + 1), "通行網絡（整段路線；平行偏移僅供辨識）", font=small_font, fill=(55, 61, 63))
            legend_y += 26
        mode_x = legend_x
        if mode == "mobility":
            for mode_key in ("pedestrian", "bicycle", "car"):
                draw.line((mode_x, legend_y + 10, mode_x + 20, legend_y + 10), fill=MODE_COLORS[mode_key], width=4)
                suffix = "" if mode_key in available_modes else "（無路段）"
                draw.text((mode_x + 25, legend_y), MODE_LABELS_ZH[mode_key] + suffix, font=small_font, fill=(55, 61, 63))
                mode_x += 125
            legend_y += 28
        draw.ellipse((legend_x, legend_y + 2, legend_x + 19, legend_y + 21), fill=(44, 124, 83), outline=(250, 249, 244), width=1)
        draw.text((legend_x + 29, legend_y), f"共用內院 · {len(courtyard_audit)} 處（院字記號）", font=small_font, fill=(55, 61, 63))
        legend_y += 34
        if service_facility_audit:
            draw.ellipse((legend_x, legend_y + 4, legend_x + 14, legend_y + 18), fill=(97, 70, 45), outline=(249, 247, 240), width=1)
            drawn_facilities = sum(record.get("render_status") == "PASS" for record in service_facility_audit)
            missing_facilities = len(service_facility_audit) - drawn_facilities
            suffix = f"；{missing_facilities} 處缺幾何" if missing_facilities else ""
            draw.text((legend_x + 25, legend_y), f"服務設施 · {drawn_facilities} 處{suffix}", font=small_font, fill=(55, 61, 63))
            legend_y += 28
        if south_quay_label_audit:
            draw.text((legend_x, legend_y), f"南岸碼頭帶 · 軸角 {_fmt(south_quay_label_audit.get('frontage_axis_azimuth_deg'), 1)}°", font=small_font, fill=(55, 61, 63))
            legend_y += 26
        if detour_audit["feature_count"]:
            draw.line((legend_x, legend_y + 10, legend_x + 25, legend_y + 10), fill=(125, 67, 139), width=4)
            draw.text((legend_x + 34, legend_y), f"水岸替代路徑 · {len(detour_audit['drawn_feature_ids'])} 條", font=small_font, fill=(55, 61, 63))
            legend_y += 28
        if mode == "landuse":
            draw.text((legend_x, legend_y), "土地使用占比｜實際與字典預算", font=small_font, fill=(42, 51, 56))
            legend_y += 23
            draw.text((legend_x, legend_y), "實色線＝plan 幾何；藍帶＝字典範圍；紫線＝覆寫（超出範圍標衝突）", font=_font(12), fill=(89, 94, 95))
            legend_y += 22
            if fabric is None:
                chart_fabric: Mapping[str, Any] = {}
            else:
                chart_fabric = fabric
            land_area = _finite_number(facts.get("site", {}).get("land_area_m2")) or 0.0
            legend_y, budget_rows = _draw_landuse_budget_chart(
                draw,
                x=legend_x,
                y=legend_y,
                width=side_width,
                plan=plan,
                land_area_m2=land_area,
                fabric=chart_fabric,
                intent=intent or {},
                label_font=_font(16),
                small_font=_font(13),
            )
            draw.text((legend_x, legend_y + 1), "計算分母：陸地面積；類別相交時不可直接加總。", font=_font(12), fill=(89, 94, 95))
        draw.text((legend_x, height - 154), f"建築 {len(buildings)} 棟 · 街廓 {len(blocks)} 個", font=small_font, fill=(55, 61, 63))
        if mode == "massing":
            draw.text((legend_x, height - 122), f"新建 GFA {_fmt(metrics.get('new_gfa_m2'), 0)} m²", font=small_font, fill=(55, 61, 63))
            draw.text((legend_x, height - 92), "數字＝樓層；M＝夾層；R＝保留建築", font=small_font, fill=(89, 94, 95))
    draw.text((50, height - 55), "座標：EPSG:28992（m）｜北箭頭為投影網格北｜比例尺以地面公尺計", font=small_font, fill=(89, 94, 95))
    if render_audit is not None:
        render_audit.update({
            "map_panel_width_percent": round(100 * map_rect[2] / width, 2),
            "map_panel_area_percent": round(100 * map_rect[2] * map_rect[3] / (width * height), 2),
            "site_bounds_padding_fraction": 0.015,
            "side_legend_present": show_side_panel,
            "road_hierarchy_widths": road_legend,
            "mode_color_keys": ({MODE_LABELS_ZH[key]: f"#{''.join(f'{channel:02X}' for channel in MODE_COLORS[key])}" for key in ("pedestrian", "bicycle", "car")} if mode == "mobility" else {}),
            "available_modes": available_modes if mode == "mobility" else [],
            "mode_strokes_meaning": "允許模式沿完整道路路段的識別；平行偏移僅為繪圖，非車道位置或車道寬度" if mode == "mobility" else "本圖未繪製步行、自行車或汽車模式覆蓋",
            "mode_overlay_render": road_render_audit,
            "mobility_overlay_status": "PASS" if mode == "landuse" and mobility_overlay_absent else ("NOT_APPLICABLE" if mode != "landuse" else "FAIL"),
            "shared_courtyard_markers": courtyard_audit,
            "boundary_parcel_count": len(parcels),
            "map_text_annotation_count": len(landuse_label_audit) + len(detour_audit.get("labels", [])) + int(south_quay_label_audit is not None),
            "map_text_annotation_basis_zh": "計算地圖內中文位置標註；純符號、樓層數、標題與圖例另列",
            "land_use_labels": landuse_label_audit,
            "service_facilities": service_facility_audit,
            "south_quay_band_label": south_quay_label_audit,
            "waterfront_detours": detour_audit,
            "land_use_budget_chart": budget_rows if mode == "landuse" else [],
            "land_use_budget_source": "凍結 fabric.land_use_budget（EDITORIAL）" if mode == "landuse" else None,
        })
    return image


def _fmt(value: Any, digits: int = 1) -> str:
    number = _finite_number(value)
    return "未提供" if number is None else f"{number:,.{digits}f}"


def _height_color(height_m: float | None) -> tuple[int, int, int]:
    if height_m is None:
        return (174, 174, 168)
    value = max(0.0, min(float(height_m), 20.0))
    t = value / 20.0
    low = (224, 181, 159)
    high = (155, 79, 61)
    return tuple(round(low[i] * (1 - t) + high[i] * t) for i in range(3))


def _building_height_m(properties: Mapping[str, Any], facts: Mapping[str, Any]) -> tuple[float | None, str]:
    for key in ("height_m", "height", "building_height_m", "height_above_ground_m"):
        number = _finite_number(properties.get(key))
        if number is not None and number > 0:
            return number, f"properties.{key}"
    floors = None
    for key in ("floor_count", "storeys", "floors_count", "levels"):
        floors = _finite_number(properties.get(key))
        if floors is not None and floors > 0:
            break
    floor_rows = properties.get("floors")
    if floors is None and isinstance(floor_rows, list) and floor_rows:
        floors = float(len(floor_rows))
    if floors is not None:
        standard = _finite_number(facts.get("height", {}).get("standard_floor_height_m"))
        if standard is None:
            standard = _finite_number(facts.get("height", {}).get("first_floor_height_m"))
        if standard is not None and standard > 0:
            return floors * standard, f"floor_count × site-facts {standard:g} m/floor"
    return None, "height_unknown"


def _feature_height(properties: Mapping[str, Any], facts: Mapping[str, Any]) -> float | None:
    return _building_height_m(properties, facts)[0]


def _feature_identity(feature: Mapping[str, Any], index: int) -> str:
    properties = _properties(feature)
    return str(feature.get("id", properties.get("id", properties.get("feature_id", index + 1))))


def _landuse_csv_rows(plan: Mapping[str, Any], facts: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = feature_rows(plan.get("land_use"))
    land_area = _finite_number(facts.get("site", {}).get("land_area_m2"))
    if land_area is None or land_area <= 0:
        raise ValueError("site-facts 的陸地面積無效。")
    result: list[dict[str, Any]] = []
    for index, feature in enumerate(rows):
        geom = feature_shape(feature)
        props = _properties(feature)
        area = float(geom.area) if geom is not None and geom.geom_type in {"Polygon", "MultiPolygon"} else None
        result.append({
            "用途或類別": _feature_label(props),
            "圖徵 ID": _feature_identity(feature, index),
            "面積_m2": area,
            "占基地陸地比例_percent": 100.0 * area / land_area if area is not None else None,
            "幾何類型": geom.geom_type if geom is not None else "未知",
            "狀態": str(props.get("status", props.get("evidence_status", "未提供"))),
            "面積口徑": "單一圖徵 Polygon/MultiPolygon 幾何面積；有重疊時不可直接相加",
        })
    return result


def write_landuse_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ("用途或類別", "圖徵 ID", "面積_m2", "占基地陸地比例_percent", "幾何類型", "狀態", "面積口徑")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            clean = dict(row)
            for key in ("面積_m2", "占基地陸地比例_percent"):
                value = _finite_number(clean.get(key))
                clean[key] = "" if value is None else f"{value:.3f}"
            writer.writerow(clean)


def _geometry_audit(plan: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"schema_version": "fab1-render-geometry-audit-v1", "collections": {}}
    collection_keys = ("roads", "blocks", "boundary_parcels", "courtyards", "buildings", "land_use", "waterfront_detours", "service_facilities", "south_quay_band")
    for key in collection_keys:
        rows = feature_rows(plan.get(key))
        counts = Counter()
        invalid_ids: list[str] = []
        empty_ids: list[str] = []
        polygon_count = 0
        hole_count = 0
        for index, row in enumerate(rows):
            geom = feature_shape(row)
            if geom is None:
                empty_ids.append(_feature_identity(row, index))
                continue
            counts[geom.geom_type] += 1
            if not geom.is_valid:
                invalid_ids.append(_feature_identity(row, index))
            for polygon in _polygon_parts(geom):
                polygon_count += 1
                hole_count += len(polygon.interiors)
        result["collections"][key] = {
            "feature_count": len(rows),
            "geometry_type_counts": dict(sorted(counts.items())),
            "polygon_part_count": polygon_count,
            "interior_ring_count": hole_count,
            "invalid_geometry_ids": invalid_ids,
            "missing_or_empty_geometry_ids": empty_ids,
            "render_geometry_status": "PASS" if not invalid_ids and not empty_ids else "FAIL",
        }
    return result


def _axon_projector(bounds: tuple[float, float, float, float], rect: tuple[int, int, int, int], max_height: float, angle_deg: float = 45.0):
    minx, miny, maxx, maxy = bounds
    theta = math.radians(angle_deg)
    c, s = math.cos(theta), math.sin(theta)
    coords = ((minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy))
    u_values = [x * c - y * s for x, y in coords]
    v_values = [x * s + y * c for x, y in coords]
    uv_bounds = (min(u_values), min(v_values), max(u_values), max(v_values))
    u0, v0, u1, v1 = uv_bounds
    left, top, width, height = rect
    vertical_ratio = 1.3
    total_v_span = (v1 - v0) + max_height * vertical_ratio
    scale = min(width / max(u1 - u0, 1e-6), height / max(total_v_span, 1e-6))
    used_w = (u1 - u0) * scale
    used_h = total_v_span * scale
    xoffset = left + (width - used_w) / 2
    yoffset = top + (height - used_h) / 2

    def project(point: Sequence[float], z: float = 0.0) -> tuple[int, int]:
        x, y = float(point[0]), float(point[1])
        u = x * c - y * s
        v = x * s + y * c
        px = xoffset + (u - u0) * scale
        py = yoffset + ((v1 - v) + (max_height - z) * vertical_ratio) * scale
        return round(px), round(py)

    return project, (u0, v0, u1, v1), scale, (c, s)


def _ring_sides(draw: ImageDraw.ImageDraw, ring: Any, z: float, project: Any, fill: tuple[int, int, int], outline: tuple[int, int, int]) -> None:
    coords = list(ring.coords)
    for start, end in zip(coords, coords[1:]):
        polygon = [project(start, 0.0), project(end, 0.0), project(end, z), project(start, z)]
        draw.polygon(polygon, fill=fill)
        draw.line(polygon + [polygon[0]], fill=outline, width=1)


def render_axonometric(path: Path, plan: Mapping[str, Any], facts: Mapping[str, Any], fabric_label: str) -> dict[str, Any]:
    site, water, _land = _site_geometries(facts)
    bounds = _site_bounds(site)
    image = Image.new("RGB", (1920, 1440), (249, 248, 244))
    draw = ImageDraw.Draw(image)
    title_font, body_font, small_font = _font(42), _font(23), _font(18)
    draw.text((48, 28), f"{fabric_label}｜等角量體圖", font=title_font, fill=(35, 44, 49))
    draw.text((50, 82), "使用輸出建築 footprint 逐棟垂直擠出；高度來自 plan 欄位或其樓層資料", font=small_font, fill=(89, 94, 95))
    map_rect = (90, 140, 1720, 1120)
    buildings = feature_rows(plan.get("buildings"))
    heights = [_feature_height(_properties(feature), facts) for feature in buildings]
    max_height = max([20.0, *(h for h in heights if h is not None)])
    project, _uv, scale, (c, s) = _axon_projector(bounds, map_rect, max_height)
    # Ground plane and water keep the real site outline and holes visible.
    for polygon in _polygon_parts(site):
        projected = [project(point, 0) for point in polygon.exterior.coords]
        draw.polygon(projected, fill=(236, 233, 222), outline=(86, 92, 92))
        for ring in polygon.interiors:
            draw.polygon([project(point, 0) for point in ring.coords], fill=(249, 248, 244), outline=(86, 92, 92))
    for polygon in _polygon_parts(water):
        draw.polygon([project(point, 0) for point in polygon.exterior.coords], fill=(194, 222, 230), outline=(116, 160, 174))
        for ring in polygon.interiors:
            draw.polygon([project(point, 0) for point in ring.coords], fill=(236, 233, 222), outline=(116, 160, 174))
    roads = feature_rows(plan.get("roads"))
    for road in roads:
        geom = feature_shape(road)
        if geom is None:
            continue
        props = _properties(road)
        right_of_way = props.get("right_of_way")
        if isinstance(right_of_way, Mapping):
            try:
                for polygon in _polygon_parts(_shape_value(right_of_way)):
                    draw.polygon([project(point, 0.1) for point in polygon.exterior.coords], fill=(196, 194, 186), outline=(136, 134, 127))
            except Exception:
                pass
        for line in _line_parts(geom):
            draw.line([project(point, 0.15) for point in line.coords], fill=(129, 126, 117), width=max(2, round((_road_width(props) or 3.0) * scale)), joint="curve")

    records: list[tuple[float, dict[str, Any], Any, float | None, str]] = []
    for index, feature in enumerate(buildings):
        geom = feature_shape(feature)
        if geom is None:
            continue
        props = _properties(feature)
        height_m, height_source = _building_height_m(props, facts)
        # Render geometry with unknown height as a ground-level footprint and
        # report the gap; never invent an extrusion height.
        center = geom.representative_point()
        depth = center.x * s + center.y * c
        records.append((depth, feature, geom, height_m, height_source))
    unknown_height_count = 0
    extruded_count = 0
    for _depth, feature, geom, height_m, height_source in sorted(records, key=lambda item: item[0]):
        props = _properties(feature)
        label = _feature_label(props, "量體")
        color = (143, 148, 145) if props.get('retained') else _height_color(height_m)
        side = tuple(max(0, round(v * 0.72)) for v in color)
        edge = tuple(max(0, round(v * 0.55)) for v in color)
        z = height_m or 0.0
        if z > 0:
            for polygon in _polygon_parts(geom):
                _ring_sides(draw, polygon.exterior, z, project, side, edge)
                for ring in polygon.interiors:
                    _ring_sides(draw, ring, z, project, side, edge)
                # Delaunay triangles are kept only when wholly covered by the
                # actual polygon, so courtyard holes remain empty on the roof.
                for triangle in triangulate(polygon):
                    if not polygon.covers(triangle):
                        continue
                    roof = [project(point, z) for point in triangle.exterior.coords]
                    draw.polygon(roof, fill=color, outline=edge)
            extruded_count += 1
        else:
            unknown_height_count += 1
            for polygon in _polygon_parts(geom):
                draw.line([project(point, 0.2) for point in polygon.exterior.coords], fill=(98, 100, 96), width=2)

    # Grid-north vector in the same axonometric projection.
    north_start = (1780, 240)
    dx, dy = -s, -c
    length = 80
    nx = round(north_start[0] + dx * length)
    ny = round(north_start[1] + dy * length)
    draw.line((north_start[0], north_start[1], nx, ny), fill=(48, 57, 60), width=4)
    draw.polygon(((nx, ny), (nx + 9, ny + 20), (nx - 9, ny + 20)), fill=(48, 57, 60))
    draw.text((nx - 12, ny + 24), "N", font=small_font, fill=(48, 57, 60))
    scale_m = 100.0
    sx, sy = 130, 1280
    draw.line((sx, sy, sx + round(scale_m * scale), sy), fill=(45, 50, 52), width=6)
    draw.line((sx, sy - 7, sx, sy + 7), fill=(45, 50, 52), width=3)
    draw.line((sx + round(scale_m * scale), sy - 7, sx + round(scale_m * scale), sy + 7), fill=(45, 50, 52), width=3)
    draw.text((sx, sy - 35), "100 m 地面尺度", font=small_font, fill=(45, 50, 52))
    draw.text((560, 1220), f"量體 {len(buildings)} 棟｜實際擠出 {extruded_count} 棟｜高度缺值 {unknown_height_count} 棟", font=body_font, fill=(55, 61, 63))
    draw.text((560, 1260), "未提供高度者只描 footprint；未用示意方盒補值。保留建物高度可能是 3DBAG 估算。", font=small_font, fill=(89, 94, 95))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    return {
        "building_count": len(buildings),
        "extruded_building_count": extruded_count,
        "height_unknown_count": unknown_height_count,
        "projection": "axonometric orthographic; actual plan polygons extruded vertically",
    }


def _section_name(road: Mapping[str, Any], index: int) -> str:
    props = _properties(road)
    for key in ("name_zh", "name", "street_name", "label"):
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"路名未提供（{_feature_identity(road, index)}）"


def _section_candidates(plan: Mapping[str, Any], site: Any) -> list[tuple[dict[str, Any], LineString, str]]:
    candidates = []
    for index, road in enumerate(feature_rows(plan.get("roads"))):
        geom = feature_shape(road)
        if geom is None:
            continue
        lines = _line_parts(geom.intersection(site))
        if not lines:
            continue
        line = max(lines, key=lambda item: item.length)
        if line.length < 10:
            continue
        candidates.append((road, line, _section_name(road, index)))
    candidates.sort(key=lambda item: (-item[1].length, item[2]))
    selected: list[tuple[dict[str, Any], LineString, str]] = []
    names: set[str] = set()
    for item in candidates:
        normalized = item[2].casefold()
        if normalized in names:
            continue
        names.add(normalized)
        selected.append(item)
        if len(selected) == 4:
            break
    return selected


def _section_line(road_line: LineString, site: Any) -> tuple[LineString | None, tuple[float, float]]:
    distance = road_line.length / 2
    center = road_line.interpolate(distance)
    delta = max(1.0, min(5.0, road_line.length / 20))
    before = road_line.interpolate(max(0.0, distance - delta))
    after = road_line.interpolate(min(road_line.length, distance + delta))
    dx, dy = after.x - before.x, after.y - before.y
    norm = math.hypot(dx, dy)
    if norm <= 1e-8:
        return None, (center.x, center.y)
    nx, ny = -dy / norm, dx / norm
    minx, miny, maxx, maxy = site.bounds
    reach = math.hypot(maxx - minx, maxy - miny) * 1.2
    long_line = LineString(((center.x - nx * reach, center.y - ny * reach), (center.x + nx * reach, center.y + ny * reach)))
    clipped = long_line.intersection(site)
    lines = _line_parts(clipped)
    if not lines:
        return None, (center.x, center.y)
    return max(lines, key=lambda line: line.length), (center.x, center.y)


def _section_building_segments(section: LineString, buildings: Sequence[Mapping[str, Any]], facts: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    segments: list[dict[str, Any]] = []
    unknown_count = 0
    for index, feature in enumerate(buildings):
        geom = feature_shape(feature)
        if geom is None:
            continue
        intersection = geom.intersection(section)
        if intersection.is_empty:
            continue
        props = _properties(feature)
        height_m = _feature_height(props, facts)
        if height_m is None:
            unknown_count += 1
        for line in _line_parts(intersection):
            if line.length <= 0.01:
                continue
            positions = sorted(section.project(shape_point) for shape_point in (line.interpolate(0), line.interpolate(line.length)))
            segments.append({
                "id": _feature_identity(feature, index),
                "start_m": positions[0],
                "end_m": positions[1],
                "height_m": height_m,
                "label": _feature_label(props, "建築"),
            })
    return segments, unknown_count


def _draw_section_panel(
    image: Image.Image,
    panel: tuple[int, int, int, int],
    title: str,
    section: LineString,
    buildings: Sequence[Mapping[str, Any]],
    roads: Sequence[Mapping[str, Any]],
    selected_road: Mapping[str, Any],
    facts: Mapping[str, Any],
    panel_no: int,
) -> dict[str, Any]:
    left, top, width, height = panel
    draw = ImageDraw.Draw(image)
    title_font, body_font, small_font = _font(24), _font(18), _font(15)
    draw.text((left + 18, top + 10), title, font=title_font, fill=(40, 48, 52))
    chart = (left + 62, top + 58, width - 90, height - 105)
    cx, cy, cw, ch = chart
    segments, unknown_count = _section_building_segments(section, buildings, facts)
    max_h = max([20.0, *(float(row["height_m"]) for row in segments if row["height_m"] is not None)])
    minx, miny, maxx, maxy = section.bounds
    # The section is straight; use projection along its actual endpoints.
    first = section.interpolate(0)
    last = section.interpolate(section.length)
    horizontal_span = section.length
    px_per_m = cw / max(horizontal_span, 1e-6)
    py_per_m = (ch - 25) / max_h

    def x_for(distance: float) -> int:
        return round(cx + distance * px_per_m)

    def y_for(height_m: float) -> int:
        return round(cy + ch - 25 - height_m * py_per_m)

    draw.line((cx, cy + ch - 25, cx + cw, cy + ch - 25), fill=(70, 73, 73), width=2)
    draw.line((cx, cy, cx, cy + ch - 25), fill=(70, 73, 73), width=2)
    # A section is generated from actual plan footprint intersections. Missing
    # heights are listed but are not represented as fabricated blocks.
    for row in sorted(segments, key=lambda item: item["start_m"]):
        height_m = row["height_m"]
        x0, x1 = x_for(row["start_m"]), x_for(row["end_m"])
        if height_m is None:
            continue
        fill = _category_color(row["label"])
        draw.rectangle((x0, y_for(height_m), max(x0 + 2, x1), y_for(0)), fill=fill, outline=(65, 70, 72), width=1)
    # Draw the selected street's measured ROW interval when supplied.
    road_props = _properties(selected_road)
    road_geom = feature_shape(selected_road)
    row_raw = road_props.get("right_of_way")
    row_geom = None
    if isinstance(row_raw, Mapping):
        try:
            row_geom = _shape_value(row_raw)
        except Exception:
            row_geom = None
    if row_geom is not None:
        intersections = _line_parts(row_geom.intersection(section))
        for line in intersections:
            distances = sorted(section.project(line.interpolate(d)) for d in (0, line.length))
            draw.line((x_for(distances[0]), y_for(0), x_for(distances[1]), y_for(0)), fill=(83, 88, 91), width=10)
    elif road_geom is not None and road_geom.intersects(section):
        point = road_geom.intersection(section)
        if not point.is_empty:
            nearest = point.representative_point()
            distance = section.project(nearest)
            x = x_for(distance)
            draw.line((x, y_for(0) - 2, x, y_for(0) + 4), fill=(60, 65, 69), width=3)
    # y tick labels and vertical scale show metres; x ticks are actual section distance.
    for tick in (0, 5, 10, 15, 20):
        yy = y_for(tick)
        draw.line((cx - 5, yy, cx + cw, yy), fill=(226, 225, 220), width=1)
        draw.text((left + 9, yy - 10), f"{tick}m", font=small_font, fill=(93, 97, 97))
    interval = 25 if horizontal_span > 160 else 10
    for tick in range(0, int(horizontal_span) + 1, interval):
        xx = x_for(tick)
        draw.line((xx, cy + ch - 25, xx, cy + ch - 20), fill=(70, 73, 73), width=1)
        if tick % (interval * 2) == 0:
            draw.text((xx - 18, cy + ch - 16), f"{tick}", font=small_font, fill=(93, 97, 97))
    width_m = _road_width(road_props)
    road_note = f"道路 ROW 依多邊形實切" if row_geom is not None else (f"道路寬度 {width_m:g} m" if width_m is not None else "僅標道路中心線；寬度未提供")
    draw.text((cx + 8, top + height - 34), f"沿剖切線距離（m）｜建築高度（m）｜{road_note}｜高度缺值命中 {unknown_count} 棟未繪", font=small_font, fill=(82, 88, 90))
    return {
        "street_label": title,
        "section_length_m": section.length,
        "building_intersection_count": len({row["id"] for row in segments}),
        "height_unknown_building_count": unknown_count,
        "building_segments": segments,
        "road_width_m": width_m,
        "road_right_of_way_intersection": row_geom is not None,
    }


def _primary_street_widths(plan: Mapping[str, Any]) -> list[float]:
    widths = []
    for road in feature_rows(plan.get("roads")):
        props = _properties(road)
        if props.get("role") != "primary_street":
            continue
        width = _road_width(props)
        if width is not None:
            widths.append(width)
    return sorted(set(widths))


def _primary_section_allocation(width_m: float) -> dict[str, float] | None:
    if not 16 <= width_m <= 22:
        return None
    if width_m >= 20:
        sidewalk_m, tree_m, cycle_m = 3.0, 1.0, 2.0
    elif width_m >= 18:
        sidewalk_m, tree_m, cycle_m = 3.0, 1.0, 1.5
    else:
        sidewalk_m, tree_m, cycle_m = 2.5, 1.0, 1.5
    car_m = (width_m - 2 * (sidewalk_m + tree_m + cycle_m)) / 2
    if car_m <= 0:
        return None
    return {"sidewalk_each_m": sidewalk_m, "tree_band_each_m": tree_m, "cycle_each_m": cycle_m, "car_each_m": car_m}


def _validator_status(core_checks: Mapping[str, Any] | None, validator_id: str) -> str:
    check_map = core_checks.get("checks") if isinstance(core_checks, Mapping) else None
    record = check_map.get(validator_id) if isinstance(check_map, Mapping) else None
    if not isinstance(record, Mapping):
        return "未驗證"
    passed = record.get("passed")
    if passed is True:
        return "PASS"
    if passed is False:
        return "FAIL"
    status = str(record.get("status", "")).upper()
    return status if status in {"PASS", "FAIL", "ERROR", "BLOCKED"} else "未驗證"


def _draw_primary_street_schematic(
    image: Image.Image,
    panel: tuple[int, int, int, int],
    plan: Mapping[str, Any],
    core_checks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    left, top, width, height = panel
    draw = ImageDraw.Draw(image)
    title_font, label_font, small_font = _font(26), _font(17), _font(15)
    widths = _primary_street_widths(plan)
    validator_status = _validator_status(core_checks, "PRIMARY_STREET_THROUGH_SITE")
    draw.text((left, top), "主街示意斷面｜取自 plan 實際寬度", font=title_font, fill=(40, 48, 52))
    if not widths:
        draw.text((left, top + 48), f"plan 未提供 primary_street.width_m；PRIMARY_STREET_THROUGH_SITE：{validator_status}", font=label_font, fill=(160, 50, 45))
        return {
            "width_source": "plan.roads[role=primary_street].properties.width_m",
            "observed_widths_m": [],
            "width_gate": "未驗證",
            "validator_id": "PRIMARY_STREET_THROUGH_SITE",
            "gate_status": validator_status,
            "overall_status": "FAIL" if validator_status == "FAIL" else "未驗證",
            "layout_status": "未提供",
            "note_zh": "寬度未提供，沒有補造道路數值。",
        }
    # Current FAB1 plans use one primary width. For multiple values, draw the
    # most frequent width and retain the complete set in the audit.
    counts = Counter(
        _road_width(_properties(road))
        for road in feature_rows(plan.get("roads"))
        if _properties(road).get("role") == "primary_street" and _road_width(_properties(road)) is not None
    )
    width_m = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    width_gate = "範圍內" if all(18 <= item <= 22 for item in widths) else "FAIL"
    if width_gate == "FAIL" or validator_status == "FAIL":
        overall_status = "FAIL"
    elif width_gate == "範圍內" and validator_status == "PASS":
        overall_status = "PASS"
    else:
        overall_status = "未驗證"
    if width_gate == "範圍內" and validator_status == "FAIL":
        gate_text = "寬度數值合格，實際路權 FAIL"
    elif width_gate == "FAIL":
        gate_text = f"寬度數值 FAIL；實際路權 {validator_status}"
    else:
        gate_text = f"寬度數值範圍內；實際路權 {validator_status}"
    gate_color = (45, 111, 74) if overall_status == "PASS" else (174, 49, 42) if overall_status == "FAIL" else (153, 106, 37)
    draw.text((left, top + 42), f"主街 {width_m:g} m（plan）｜本輪條件 18–22 m：{gate_text}", font=label_font, fill=gate_color)
    allocation = _primary_section_allocation(width_m)
    if allocation is None:
        draw.text((left, top + 86), "目前寬度沒有可用的示意配置包絡，故不繪配置。", font=small_font, fill=(160, 50, 45))
        return {
            "width_source": "plan.roads[role=primary_street].properties.width_m",
            "observed_widths_m": widths,
            "diagram_width_m": width_m,
            "width_gate": width_gate,
            "validator_id": "PRIMARY_STREET_THROUGH_SITE",
            "gate_status": validator_status,
            "overall_status": overall_status,
            "layout_status": "未配置",
            "note_zh": "此 runner 不為 16–22 m 範圍外的主街補造斷面；核心路權結果另外照實標示。",
        }

    side, tree, cycle, car = (
        allocation["sidewalk_each_m"], allocation["tree_band_each_m"],
        allocation["cycle_each_m"], allocation["car_each_m"],
    )
    bands = [
        ("人行道", side, (223, 221, 211), "人行"),
        ("行道樹帶", tree, (119, 163, 105), "樹"),
        ("自行車道", cycle, MODE_COLORS["bicycle"], "自行車"),
        ("汽車道", car, MODE_COLORS["car"], "汽車"),
        ("汽車道", car, MODE_COLORS["car"], "汽車"),
        ("自行車道", cycle, MODE_COLORS["bicycle"], "自行車"),
        ("行道樹帶", tree, (119, 163, 105), "樹"),
        ("人行道", side, (223, 221, 211), "人行"),
    ]
    total = sum(item[1] for item in bands)
    delta = total - width_m
    scale = min((width - 44) / max(width_m, 1e-6), 42.0)
    bar_width = round(total * scale)
    bar_x = left + (width - bar_width) // 2
    bar_y = top + 110
    bar_height = 96
    cursor = bar_x
    for name, band_width, color, short_label in bands:
        band_px = round(band_width * scale)
        draw.rectangle((cursor, bar_y, cursor + band_px, bar_y + bar_height), fill=color, outline=(248, 247, 242), width=2)
        if name == "行道樹帶":
            cx = cursor + band_px // 2
            cy = bar_y + bar_height // 2
            draw.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), fill=(53, 111, 56), outline=(248, 247, 242), width=2)
        elif band_px >= 66:
            draw.text((cursor + band_px // 2, bar_y + bar_height // 2), short_label, font=small_font, fill=(255, 255, 255) if name in {"自行車道", "汽車道"} else (47, 54, 54), anchor="mm")
        cursor += band_px
    draw.text((left, top + 220), f"人行 {side:g}×2 + 樹帶 {tree:g}×2 + 自行車 {cycle:g}×2 + 汽車 {car:g}×2 = {total:g} m", font=label_font, fill=(50, 57, 60))
    draw.line((bar_x, top + 258, bar_x + bar_width, top + 258), fill=(58, 64, 66), width=2)
    draw.line((bar_x, top + 250, bar_x, top + 266), fill=(58, 64, 66), width=2)
    draw.line((bar_x + bar_width, top + 250, bar_x + bar_width, top + 266), fill=(58, 64, 66), width=2)
    draw.text((bar_x, top + 270), f"總路幅 {total:g} m", font=small_font, fill=(58, 64, 66))
    draw.text((left, top + 300), "行道樹、自行車與汽車配置為探索斷面假設；未計算交通量、車道安全或法規合規。", font=small_font, fill=(89, 94, 95))
    arithmetic_ok = math.isclose(total, width_m, rel_tol=0.0, abs_tol=0.01)
    return {
        "width_source": "plan.roads[role=primary_street].properties.width_m",
        "observed_widths_m": widths,
        "diagram_width_m": width_m,
        "width_gate": width_gate,
        "validator_id": "PRIMARY_STREET_THROUGH_SITE",
        "gate_status": validator_status,
        "overall_status": "FAIL" if not arithmetic_ok or overall_status == "FAIL" else "PASS" if overall_status == "PASS" else "未驗證",
        "width_requirement_m": [18, 22],
        "bands": [
            {"name_zh": name, "width_m": band_width}
            for name, band_width, _color, _short_label in bands
        ],
        "sum_m": total,
        "sum_delta_m": delta,
        "arithmetic_check": "PASS" if arithmetic_ok else "FAIL",
        "layout_status": "RENDERED",
        "note_zh": "探索斷面配置假設；不是交通計算或法規合規驗證。主街通過狀態取核心 PRIMARY_STREET_THROUGH_SITE。",
    }


def render_sections(
    path: Path,
    plan: Mapping[str, Any],
    facts: Mapping[str, Any],
    fabric_label: str,
    core_checks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One actual cross-section, selected for buildings on both street sides."""
    site,_,_=_site_geometries(facts);buildings=feature_rows(plan.get('buildings'));roads=feature_rows(plan.get('roads'));candidates=[]
    for road in roads:
        if _properties(road).get('role')!='block_edge_street':continue
        for source_line in _line_parts(feature_shape(road)):
            coords=list(source_line.coords)
            for a,b in zip(coords,coords[1:]):
                segment=LineString([a,b])
                if segment.length<20:continue
                dx,dy=b[0]-a[0],b[1]-a[1];length=segment.length
                for fraction in (.25,.5,.75):
                    center=segment.interpolate(segment.length*fraction);nx,ny=-dy/length,dx/length
                    transect=LineString([(center.x-75*nx,center.y-75*ny),(center.x+75*nx,center.y+75*ny)])
                    parts=_line_parts(transect.intersection(site));section=next((g for g in parts if g.distance(center)<.01),None)
                    if section is None:continue
                    hits=[];center_d=section.project(center)
                    for building in buildings:
                        geom=feature_shape(building)
                        if geom is not None and geom.intersection(section).length>.1:
                            point=geom.intersection(section).representative_point();hits.append(section.project(point)-center_d)
                    both=any(v<0 for v in hits) and any(v>0 for v in hits)
                    score=(both,2<=len(hits)<=6,-abs(len(hits)-3),-abs(section.length-140))
                    candidates.append((score,section,center,road,segment))
    image=Image.new('RGB',(2600,1280),(249,248,244));draw=ImageDraw.Draw(image)
    draw.text((48,28),f'{fabric_label}｜典型街道橫剖面',font=_font(40),fill=(35,44,49))
    draw.text((50,84),'依實際道路法線剖切；水平與垂直比例不同，軸線以公尺標示。',font=_font(19),fill=(89,94,95))
    if not candidates:
        draw.text((80,220),'FAIL：未找到可剖切的街廓道路。',font=_font(28),fill=(160,50,45))
        primary_audit = _draw_primary_street_schematic(image, (1460, 170, 1080, 540), plan, core_checks)
        path.parent.mkdir(parents=True,exist_ok=True);image.save(path,format='PNG',optimize=True)
        return {'section_count':0,'status':'FAIL','primary_street_cross_section':primary_audit}
    _,section,center,road,segment=max(candidates,key=lambda row:row[0]);props=_properties(road);width=_road_width(props)
    selected=dict(road);selected['properties']=dict(props)
    row_raw=props.get('right_of_way')
    if isinstance(row_raw,Mapping):selected['properties']['right_of_way']=mapping(shape(row_raw).intersection(segment.buffer(width/2,cap_style=2,join_style=2)))
    label=f'A—A′｜{_road_label(props)}，路權 {width:g} m'
    audit=_draw_section_panel(image,(40,140,1360,800),label,section,buildings,roads,selected,facts,0)
    # Inset shows the exact transect on the same plan geometry.
    rect=(1460,190,1080,450);transform=MapTransform(_site_bounds(site),rect)
    _draw_geometry(image,site,transform,fill=(233,231,219),outline=(102,110,110),outline_width=1)
    _draw_geometry(image,_site_geometries(facts)[1],transform,fill=(194,222,230),outline=(116,160,174),outline_width=1)
    for building in buildings:_draw_geometry(image,feature_shape(building),transform,fill=(141,139,127),outline=(97,97,88),outline_width=1)
    xy=[transform.point(p) for p in section.coords];draw.line(xy,fill=(197,57,47),width=4)
    draw.text((xy[0][0]-15,xy[0][1]-20),'A',font=_font(19),fill=(180,43,40));draw.text((xy[-1][0]+5,xy[-1][1]),'A′',font=_font(19),fill=(180,43,40))
    draw.text((1460,150),'剖切位置',font=_font(23),fill=(40,48,52));_draw_north_and_scale(draw,rect,transform,_font(15))
    draw.text((1460,647),'路權為輸出多邊形的實際切面。',font=_font(16),fill=(82,88,90))
    draw.text((1460,672),'允許模式線色只表示通行許可；斷面配置另列探索假設。',font=_font(16),fill=(82,88,90))
    primary_audit = _draw_primary_street_schematic(image, (1460, 705, 1080, 540), plan, core_checks)
    path.parent.mkdir(parents=True,exist_ok=True);image.save(path,format='PNG',optimize=True)
    audit['center_epsg28992']=[center.x,center.y];audit['section_endpoints_epsg28992']=[list(section.coords[0]),list(section.coords[-1])]
    return {'section_count':1,'status':'RENDERED','sections':[audit],'primary_street_cross_section':primary_audit}


def _draw_comparison_grid(path: Path, plans: Mapping[str, Mapping[str, Any]], facts: Mapping[str, Any], *, mode: str) -> None:
    site, _water, _land = _site_geometries(facts)
    fixed_bounds = _site_bounds(site)
    width, height = 2400, 1840
    image = Image.new("RGB", (width, height), (248, 247, 242))
    draw = ImageDraw.Draw(image)
    title = "四種街廓策略｜同範圍同比例尺用地比較" if mode == "landuse" else "四種街廓策略｜同範圍同比例尺量體比較"
    draw.text((50, 25), title, font=_font(40), fill=(35, 44, 49))
    draw.text((52, 82), "每格均使用 StudyArea v5 同一 EPSG:28992 界線、相同 map extent 與地面尺度。", font=_font(19), fill=(89, 94, 95))
    panel_w, panel_h = 1140, 820
    panel_locations = ((35, 125), (1225, 125), (35, 990), (1225, 990))
    for index, fabric_id in enumerate(FABRIC_IDS):
        plan = plans[fabric_id]
        x, y = panel_locations[index]
        panel_image = _map_image(
            title=f"{index + 1}. {_fabric_label(fabric_id)}",
            note="", facts=facts, plan=plan, canvas_size=(panel_w, panel_h), fixed_bounds=fixed_bounds, mode=mode,
            show_side_panel=False,
        )
        image.paste(panel_image, (x, y))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def _metrics(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = plan.get("metrics", {})
    return metrics if isinstance(metrics, Mapping) else {}


def _plan_geometry_summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for key in ("roads", "blocks", "boundary_parcels", "courtyards", "buildings", "land_use", "waterfront_detours", "service_facilities", "south_quay_band"):
        rows = feature_rows(plan.get(key))
        result[key] = {"feature_count": len(rows), "missing_geometry_count": sum(feature_shape(row) is None for row in rows)}
    return result


def _landuse_area_by_category(plan: Mapping[str, Any]) -> dict[str, float]:
    areas: dict[str, float] = {}
    for feature in feature_rows(plan.get("land_use")):
        geometry = feature_shape(feature)
        if geometry is None or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            continue
        category = str(_properties(feature).get("category", _feature_label(_properties(feature))))
        areas[category] = areas.get(category, 0.0) + float(geometry.area)
    return areas


def _check_status(checks: Mapping[str, Any]) -> tuple[str, list[str]]:
    status = str(checks.get("status", "未驗證")).upper()
    failures = checks.get("failure_ids", checks.get("failed_checks", checks.get("failures", [])))
    failures = [str(value) for value in failures] if isinstance(failures, list) else []
    per_check = checks.get("checks")
    if isinstance(per_check, Mapping):
        failures.extend(
            str(name)
            for name, value in per_check.items()
            if isinstance(value, Mapping) and (value.get("passed") is False or str(value.get("status", "")).upper() == "FAIL")
        )
    if checks.get("passed") is True:
        status = "PASS"
    elif checks.get("passed") is False:
        status = "FAIL"
    elif status not in {"PASS", "FAIL", "ERROR", "BLOCKED", "UNVERIFIED", "未驗證"}:
        status = "未驗證"
    if status in {"UNVERIFIED", "未驗證"} and failures:
        status = "FAIL"
    return status, sorted(set(failures))


def _check_result_label(core_checks: Mapping[str, Any], validator_id: str) -> str:
    check_map = core_checks.get("checks") if isinstance(core_checks, Mapping) else None
    if not isinstance(check_map, Mapping) or validator_id not in check_map:
        return "未驗證（核心未回傳）"
    record = check_map[validator_id]
    if not isinstance(record, Mapping):
        return "未驗證（核心回傳格式無結果旗標）"
    passed = record.get("passed")
    if passed is True:
        return "PASS"
    if passed is False:
        return "FAIL"
    status = str(record.get("status", "")).upper()
    return status if status in {"PASS", "FAIL", "ERROR", "BLOCKED"} else "未驗證（核心未提供結果旗標）"


def _required_core_check_ids(fabric_id: str | None) -> tuple[str, ...]:
    """第四輪院落島檢查只適用院落案；其他既有檢查不得略過。"""
    new_ids = tuple(key for key in FAB1C_REQUIRED_VALIDATOR_IDS
                    if key not in {"COURTYARD_ISLAND_COUNT_SPACING", "COURTYARD_ISLAND_GLOBAL_MEMBERSHIP", "COURTYARD_ISLAND_ROAD_CLEARANCE"} or fabric_id in (None, "courtyard_islands", "fabric.courtyard_islands"))
    conditional = ("COURTYARD_ISLAND_SINGLE_VOID",) if fabric_id in ("courtyard_islands", "fabric.courtyard_islands") else (("LANDSCAPE_GREEN_AXIS_CONTINUITY",) if fabric_id in ("landscape_figure", "fabric.landscape_figure") else ())
    return (*FAB1_ORIGINAL_VALIDATOR_IDS, *new_ids, *conditional)


def _fab1c_case_status(summary: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Fail closed when a core check or the landuse render gate is missing."""
    core_checks = summary.get("core_checks", {})
    if not isinstance(core_checks, Mapping):
        core_checks = {}
    core_status, failures = _check_status(core_checks)
    reported_status = str(core_checks.get("status", "")).upper()
    if reported_status in {"FAIL", "ERROR", "BLOCKED"} and core_checks.get("passed") is True:
        failures.append(f"CORE_STATUS_CONFLICT:{reported_status}")
    check_map = core_checks.get("checks", {})
    check_map = check_map if isinstance(check_map, Mapping) else {}
    required_ids = _required_core_check_ids(summary.get("fabric_id") or summary.get("api_plan", {}).get("fabric_id"))
    for check_id in required_ids:
        result = _check_result_label(core_checks, check_id)
        if result != "PASS":
            failures.append(f"{check_id}:{result}")
    # Keep every returned core check in the aggregate, including any new ID
    # that was not known to this runner when it was authored.
    for check_id in check_map:
        result = _check_result_label(core_checks, str(check_id))
        if result != "PASS":
            failures.append(f"{check_id}:{result}")
    runner_checks = summary.get("runner_checks", {})
    gate = runner_checks.get(LANDUSE_NO_MOBILITY_OVERLAY, {}) if isinstance(runner_checks, Mapping) else {}
    if not isinstance(gate, Mapping) or gate.get("passed") is not True:
        failures.append(LANDUSE_NO_MOBILITY_OVERLAY)
    detour_gate = runner_checks.get(WATERFRONT_DETOUR_MARKED, {}) if isinstance(runner_checks, Mapping) else {}
    if not isinstance(detour_gate, Mapping) or detour_gate.get("passed") is not True:
        failures.append(WATERFRONT_DETOUR_MARKED)
    label_gate = runner_checks.get(MAP_TEXT_LABEL_LIMIT, {}) if isinstance(runner_checks, Mapping) else {}
    if not isinstance(label_gate, Mapping) or label_gate.get("passed") is not True:
        failures.append(MAP_TEXT_LABEL_LIMIT)
    failures = sorted(set(failures))
    if failures or core_status != "PASS":
        return "FAIL", failures or [f"CORE_STATUS:{core_status}"]
    return "PASS", []


def _intent_for(fabric_id: str, *, reuse_run2: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read an optional per-fabric intent; no file means core dictionary defaults."""
    if reuse_run2:
        frozen_plan_path = OUTPUT_DIR / "run-2" / f"{fabric_id}-plan.json"
        if not frozen_plan_path.is_file():
            raise FileNotFoundError(f"run-2 方案 provenance 缺檔，無法確認 intent 狀態：{frozen_plan_path}")
        frozen_plan = load_json(frozen_plan_path)
        provenance = frozen_plan.get("fab1_provenance", {}) if isinstance(frozen_plan, Mapping) else {}
        frozen_intent = provenance.get("intent") if isinstance(provenance, Mapping) else None
        frozen_source = provenance.get("intent_source") if isinstance(provenance, Mapping) else None
        if frozen_intent != {} or not isinstance(frozen_source, Mapping) or frozen_source.get("status") != "NO_OVERRIDE_DICTIONARY_DEFAULTS":
            raise ValueError(f"run-2 {fabric_id} 不是無 intent 覆寫的基準案例；停止讀取 live intent。")
        return {}, {
            "status": "NO_OVERRIDE_REUSED_FROM_RUN2",
            "source_path": str(frozen_plan_path.relative_to(ROOT)),
            "sha256": sha256_file(frozen_plan_path),
        }
    source = INTENTS_DIR / f"{fabric_id}.json"
    if not source.is_file():
        return {}, {"status": "NO_OVERRIDE_DICTIONARY_DEFAULTS", "source_path": None, "sha256": None}
    value = load_json(source)
    if not isinstance(value, Mapping):
        raise ValueError(f"intent 必須是 JSON object：{source}")
    snapshot_path = RUN_DIR / "intent-sources" / source.name
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    exact_bytes = source.read_bytes()
    snapshot_path.write_bytes(exact_bytes)
    digest = hashlib.sha256(exact_bytes).hexdigest()
    if sha256_file(snapshot_path) != digest:
        raise RuntimeError(f"intent 快照 SHA-256 不一致：{source}")
    return dict(value), {
        "status": "SNAPSHOTTED_OVERRIDE",
        "source_path": str(source),
        "snapshot_path": str(snapshot_path.relative_to(RUN_DIR)),
        "sha256": digest,
    }


def _check_plan_epsg28992(plan: Mapping[str, Any]) -> None:
    crs = plan.get("crs")
    if crs is None:
        raise ValueError("plan 缺少 CRS，不能安全繪圖。")
    if "28992" not in json.dumps(crs, ensure_ascii=False):
        raise ValueError(f"plan CRS 必須為 EPSG:28992，收到 {crs!r}")


def _package_plan(
    plan: Mapping[str, Any],
    *,
    fabric_id: str,
    fabric_file_hash: str,
    input_manifest_hash: str,
    source_revision: Mapping[str, Any],
    intent: Mapping[str, Any],
    intent_source: Mapping[str, Any],
    core_source_sha256: str,
    runner_sha256: str,
    reused_run2_snapshot: bool,
) -> dict[str, Any]:
    packaged = dict(plan)
    packaged["fab1_provenance"] = {
        "runner_version": RUNNER_VERSION,
        "created_at_utc": utc_now(),
        "fabric_id": fabric_id,
        "fabric_source_sha256": fabric_file_hash,
        "input_manifest_sha256": input_manifest_hash,
        "input_snapshot_origin": "artifacts/fab1/run-2/inputs (exact bytes)" if reused_run2_snapshot else "current snapshot workflow",
        "project_source_revision": source_revision,
        "core_source_path": "src/urban_design/generation/fabric_plan.py",
        "core_source_sha256": core_source_sha256,
        "runner_source_path": "scripts/run_fabric_plan.py",
        "runner_source_sha256": runner_sha256,
        "intent": dict(intent),
        "intent_source": dict(intent_source),
        "intent_interpretation_zh": "沒有對應 intent JSON 時傳入空 object，由核心依 frozen fabric、context 與其明列預設值生成；runner 不注入範圍中點或其他覆寫。",
    }
    return packaged


def _run_one(
    fabric_id: str,
    *,
    facts: Mapping[str, Any],
    context: Mapping[str, Any],
    fabric: Mapping[str, Any],
    fabric_path: Path,
    input_manifest_hash: str,
    source_revision: Mapping[str, Any],
    runner_sha256: str,
    core_source_sha256: str,
    reused_run2_snapshot: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    from urban_design.generation.fabric_plan import generate_plan, validate_plan

    intent, intent_source = _intent_for(fabric_id, reuse_run2=reused_run2_snapshot)
    raw_plan = generate_plan(facts, context, fabric, intent)
    if not isinstance(raw_plan, Mapping):
        raise TypeError(f"generate_plan({fabric_id}) 必須回傳 dict")
    _check_plan_epsg28992(raw_plan)
    # Validation is a separate authoritative output; it is never inferred from
    # successful rendering or the presence of a non-empty feature collection.
    try:
        core_checks = validate_plan(raw_plan)
    except Exception as exc:
        core_checks = {"status": "ERROR", "validator_exception": f"{type(exc).__name__}: {exc}"}
    if not isinstance(core_checks, Mapping):
        core_checks = {"status": "ERROR", "validator_result_type": type(core_checks).__name__}

    fabric_hash = sha256_file(fabric_path)
    _core_status, failure_ids = _check_status(core_checks)
    core_check_map = core_checks.get("checks", {}) if isinstance(core_checks, Mapping) else {}
    core_check_map = core_check_map if isinstance(core_check_map, Mapping) else {}
    missing_core_check_ids = [
        check_id for check_id in _required_core_check_ids(fabric_id)
        if check_id not in core_check_map
    ]
    plan = _package_plan(
        raw_plan,
        fabric_id=fabric_id,
        fabric_file_hash=fabric_hash,
        input_manifest_hash=input_manifest_hash,
        source_revision=source_revision,
        intent=intent,
        intent_source=intent_source,
        core_source_sha256=core_source_sha256,
        runner_sha256=runner_sha256,
        reused_run2_snapshot=reused_run2_snapshot,
    )
    stem = fabric_id
    write_json(RUN_DIR / f"{stem}-plan.json", plan)
    audit = _geometry_audit(raw_plan)
    checks = {
        "schema_version": "fab1-plan-checks-v1",
        "fabric_id": fabric_id,
        "core_validator": dict(core_checks),
        "render_geometry_audit": audit,
        "inputs": {
            "input_manifest_sha256": input_manifest_hash,
            "fabric_source_sha256": fabric_hash,
            "core_source_sha256": core_source_sha256,
            "runner_source_sha256": runner_sha256,
            "intent_source": intent_source,
            "horizontal_crs": "EPSG:28992",
            "snapshot_origin": "artifacts/fab1/run-2/inputs" if reused_run2_snapshot else "current snapshot workflow",
        },
        "failure_ids": failure_ids,
        "plan_feature_counts": _plan_geometry_summary(raw_plan),
    }
    write_landuse_csv(RUN_DIR / f"{stem}-landuse.csv", _landuse_csv_rows(raw_plan, facts))
    landuse_render_audit: dict[str, Any] = {}
    landuse_path = RUN_DIR / f"{stem}-landuse-zh.png"
    _map_image(
        title=f"{_fabric_label(fabric_id)}｜土地使用與街廓",
        note=f"土地使用、道路、建築與內院均取自同一 plan GeoJSON｜核心 {_core_status}；{len(failure_ids)} 項未通過；缺 {len(missing_core_check_ids)} 項檢查",
        facts=facts,
        plan=raw_plan,
        mode="landuse",
        fabric=fabric,
        intent=intent,
        render_audit=landuse_render_audit,
    ).save(landuse_path, format="PNG", optimize=True)
    landuse_render_audit["file"] = landuse_path.name
    landuse_render_audit["sha256"] = sha256_file(landuse_path)

    mobility_render_audit: dict[str, Any] = {}
    mobility_path = RUN_DIR / f"{stem}-mobility-zh.png"
    _map_image(
        title=f"{_fabric_label(fabric_id)}｜步行、自行車與汽車通行網絡",
        note="依道路 features 的 modes／allowed_modes 繪製完整允許路段；平行偏移只供辨識，不表示車道位置或寬度",
        facts=facts,
        plan=raw_plan,
        mode="mobility",
        fabric=fabric,
        intent=intent,
        render_audit=mobility_render_audit,
    ).save(mobility_path, format="PNG", optimize=True)
    mobility_render_audit["file"] = mobility_path.name
    mobility_render_audit["sha256"] = sha256_file(mobility_path)

    landuse_mode_render = landuse_render_audit.get("mode_overlay_render", {})
    no_mobility_overlay_pass = (
        landuse_render_audit.get("mobility_overlay_status") == "PASS"
        and landuse_mode_render.get("mode_overlay_enabled") is False
        and landuse_mode_render.get("mode_overlay_feature_paths_drawn") == 0
        and landuse_mode_render.get("mode_overlay_line_segments_drawn") == 0
        and not landuse_render_audit.get("mode_color_keys")
    )
    render_gate = {
        "status": "PASS" if no_mobility_overlay_pass else "FAIL",
        "passed": no_mobility_overlay_pass,
        "evidence": {
            "landuse_map_sha256": landuse_render_audit.get("sha256"),
            "mode_overlay_render": landuse_mode_render,
            "mode_color_keys": landuse_render_audit.get("mode_color_keys"),
            "mobility_map": mobility_render_audit.get("file"),
        },
    }
    label_counts = {"landuse": landuse_render_audit.get("map_text_annotation_count"), "mobility": mobility_render_audit.get("map_text_annotation_count")}
    runner_checks = {LANDUSE_NO_MOBILITY_OVERLAY: render_gate, MAP_TEXT_LABEL_LIMIT: {
        "passed": all(isinstance(v, int) and v <= 10 for v in label_counts.values()),
        "counts": label_counts, "maximum": 10,
        "status": "PASS" if all(isinstance(v, int) and v <= 10 for v in label_counts.values()) else "FAIL",
    }}
    expected_detours = {_feature_identity(row, i) for i, row in enumerate(feature_rows(raw_plan.get("waterfront_detours")))}
    marked = all(set(audit.get("waterfront_detours", {}).get("drawn_feature_ids", [])) == expected_detours and not audit.get("waterfront_detours", {}).get("missing_line_geometry_ids", []) for audit in (landuse_render_audit, mobility_render_audit))
    runner_checks[WATERFRONT_DETOUR_MARKED] = {"passed": marked, "status": "PASS" if marked else "FAIL", "expected_ids": sorted(expected_detours), "reason_zh": "用地圖與交通圖均須實際繪出全部替代路徑"}
    checks["runner_checks"] = runner_checks
    checks["required_core_checks_missing"] = missing_core_check_ids
    budget_chart_audit = render_landuse_budget_chart(
        RUN_DIR / f"{stem}-budget-zh.png",
        plan=raw_plan,
        facts=facts,
        fabric=fabric,
        intent=intent,
        fabric_label=_fabric_label(fabric_id),
    )
    _map_image(
        title=f"{_fabric_label(fabric_id)}｜量體平面",
        note=f"依輸出高度與樓層資料上色；保留建築另以灰色標示｜核心檢查 {_core_status}；{len(failure_ids)} 項未通過",
        facts=facts,
        plan=raw_plan,
        mode="massing",
        fabric=fabric,
        intent=intent,
    ).save(RUN_DIR / f"{stem}-massing-zh.png", format="PNG", optimize=True)
    axon_audit = render_axonometric(RUN_DIR / f"{stem}-axon-zh.png", raw_plan, facts, _fabric_label(fabric_id))
    section_audit = render_sections(
        RUN_DIR / f"{stem}-section-zh.png", raw_plan, facts, _fabric_label(fabric_id), core_checks
    )
    checks["render_outputs"] = {
        "land_use_map": landuse_render_audit,
        "mobility_map": mobility_render_audit,
        "land_use_budget_chart": budget_chart_audit,
        "axonometric": axon_audit,
        "sections": section_audit,
    }
    checks["plan_parameters"] = dict(raw_plan.get("parameters", {})) if isinstance(raw_plan.get("parameters"), Mapping) else {}
    checks["metrics"] = dict(_metrics(raw_plan))
    write_json(RUN_DIR / f"{stem}-checks.json", checks)
    return plan, checks, {
        "fabric_id": fabric_id,
        "intent": intent,
        "intent_source": intent_source,
        "parameters": dict(raw_plan.get("parameters", {})) if isinstance(raw_plan.get("parameters"), Mapping) else {},
        "orientation_deg": raw_plan.get("orientation_deg"),
        "block_axis_azimuth_deg": raw_plan.get("block_axis_azimuth_deg"),
        "metrics": dict(_metrics(raw_plan)),
        "geometry_summary": _plan_geometry_summary(raw_plan),
        "core_checks": dict(core_checks),
        "runner_checks": runner_checks,
        "render_audit": {"land_use_map": landuse_render_audit, "mobility_map": mobility_render_audit, "axonometric": axon_audit, "sections": section_audit},
    }, dict(raw_plan)


def _comparison_source_summary(plans: Mapping[str, Mapping[str, Any]], compare_result: Any) -> dict[str, Any]:
    return {
        "schema_version": "fab1-comparison-v1",
        "created_at_utc": utc_now(),
        "comparison": compare_result,
        "plans": {
            fabric_id: {
                "fabric_id": fabric_id,
                "metrics": dict(_metrics(plan)),
                "feature_counts": _plan_geometry_summary(plan),
                "status": plan.get("status", "未提供"),
            }
            for fabric_id, plan in plans.items()
        },
        "decision_rule": "本比較不設定總分或總排名；由設計者依明確目標判斷各項取捨。",
    }


def _readme_content(
    *,
    manifest: Mapping[str, Any],
    summaries: Mapping[str, Mapping[str, Any]],
    comparison: Mapping[str, Any],
    command: str,
    reused_run2_snapshot: bool,
) -> str:
    facts = load_json(INPUTS_DIR / "site-facts.json")
    context = load_json(INPUTS_DIR / "context-facts.json")
    land_area = float(facts["site"]["land_area_m2"])
    retained_upper = _finite_number(facts.get("gfa", {}).get("retained_upper_m2"))
    if retained_upper is None:
        retained_upper = sum(_finite_number(row.get("gfa_upper_m2")) or 0.0 for row in facts.get("retained_buildings", []))
    old_new_budget = _finite_number(facts.get("gfa", {}).get("new_gfa_budget_m2"))
    old_total_upper = _finite_number(facts.get("gfa", {}).get("total_gfa_upper_at_far_max_m2"))
    runner_hash = sha256_file(Path(__file__).resolve())
    core_hash = sha256_file(ROOT / "src" / "urban_design" / "generation" / "fabric_plan.py")
    snapshot_note = (
        "本輪從 `artifacts/fab1/run-2/inputs/` 重用 run-2 27 檔凍結快照；逐檔重新核對大小與 SHA-256，manifest 完全沿用，SHA-256 必須為 `b0f89a398767ccb17d783d029aa8eb1eedc7995ee153b384ddb9dd9b2a7f7c8c`。不讀取 live site、context、fabric、dictionary 或 intent 來源。"
        if reused_run2_snapshot else
        "本輪按一般快照流程建立或驗證輸入；其 source revision、manifest 和逐檔雜湊見下方。"
    )
    intent_note = (
        "本輪依 run-2 四份方案 provenance 確認四案均使用空 intent；不讀取 live `intents/`。每份 run-2 plan 的 SHA-256 列於新 plan provenance。"
        if reused_run2_snapshot else
        "若無單案 intent JSON，runner 傳入 `{}` 並依字典預設生成；有檔案時保存 exact bytes 和 SHA-256，不將意圖混入凍結字典。"
    )
    lines = [
        "# FAB1e｜第五輪四種都市紋理方案",
        "",
        "本次使用 Rotterdam M4H StudyArea v5 凍結 site facts、CTX1 context 與四個唯讀 fabric source，透過確定性核心 API 產生四個探索方案。圖面直接繪製 plan GeoJSON；validator 結果逐項保留。沒有設定整體勝者，亦不代表法律可建性、土地權屬、公共通行權或正式方案接受。",
        "",
        "**本輪整體檢查：** " + "；".join(f"{_fabric_label(fid)} {_fab1c_case_status(summaries[fid])[0]}" for fid in FABRIC_IDS) + "。核心 validator、必需檢查完整性及實際用地圖 render gate 均須通過；缺少檢查或未驗證均列為 FAIL。",
        "",
        "## 第五輪修正對照表",
        "",
        "本輪承接 run-3 圍合案西側周邊式街廓品質標準，仍保留全部舊檢查。水岸東北替代路徑與西南36.7公尺未服務岸線分別列示，不能稱為同一位置的覆蓋。",
        "",
        "| run-4 問題 | 第五輪修正與檢查 | 可核對證據 |",
        "|---|---|---|",
        "| 東北碎街廓 | 按四案紋理重排，院落東北1–2大島，其餘3–6街廓；新增1500平方公尺下限和全量體歸屬檢查 | NORTHEAST_REGULAR_BLOCKS、NORTHEAST_NO_SMALL_BUILDING_BLOCKS |",
        "| 獨立量體置於地塊中央 | 新增真正公共路權3公尺臨街檢查，排除臨時服務支線；記錄每棟實際外邊長與退縮 | BUILDING_STREET_EDGE_3M |",
        "| 南碼頭缺帶或立面不連續 | 以實際臨水正面投影檢查60%立面及相鄰間隙12公尺，背巷另查；未成功部分維持FAIL | SOUTH_QUAY_SHARED_ALLEY、SOUTH_QUAY_FACADE_CONTINUITY、SOUTH_QUAY_MAX_GAP |",
        "| 院落西側小宗地與57公尺大院 | 重排大島，保留全案4–7島、單院20–45公尺及道路不得穿入的全部檢查 | COURTYARD_ISLAND_* |",
        "| 地景5053平方公尺空地 | 依實際共界將完整地塊併入公園並命名；仍須通過公園核心、預算與綠軸檢查 | NO_LARGE_UNBUILT_PLOT、PARK_COHERENT_SHAPE |",
        "| 水岸36.7公尺缺口 | 採Founder第四輪核准例外：無法放入10公尺完整路幅時，合法4公尺替代路徑不超過60公尺且有標示可PASS；未服務岸線長度照列 | WATERFRONT_PUBLIC_BAND例外旗標、WATERFRONT_DETOUR_GEOMETRY、圖面 |",
        "| 圖面內部ID干擾 | 公園、廣場及水岸使用簡短中文名稱；服務院和內院僅符號，量體僅樓層數；位置文字最多10項 | MAP_TEXT_LABEL_LIMIT、render audit |",
        "| 六組比較僅五組通過 | 沿用方向10度、街廓中位面積10%、類型配比TV20%門檻，至少兩維不同；未通過不隱藏 | comparison.json |",
        "| 輸入可變與漏檢風險 | 使用逐檔雜湊核對的run-2凍結輸入，所有原有及新增必要ID缺項即FAIL | inputs/manifest.json、逐案checks |",
        "",
        "## 輸入與重現方式",
        "",
        f"- 實際生成命令：`{command}`。runner `{RUNNER_VERSION}` SHA-256：`{runner_hash}`；核心 `src/urban_design/generation/fabric_plan.py` SHA-256：`{core_hash}`。",
        f"- {snapshot_note}",
        f"- 快照 UTC：`{manifest.get('created_at_utc', '未提供')}`；manifest SHA-256：`{sha256_file(INPUTS_DIR / 'manifest.json')}`。來源與 exact-byte 快照逐檔雜湊見 [`inputs/manifest.json`](inputs/manifest.json)。",
        f"- 專案 revision：`{manifest.get('project_source_revision', {}).get('revision') or '未取得'}`；fabric source revision：`{manifest.get('fabric_source_revision', {}).get('revision') or '未取得'}`。",
        f"- facts `{facts.get('schema_version')}`，StudyArea `{facts.get('site', {}).get('study_area_id')}`（{facts.get('site', {}).get('status')}）；context `{context.get('schema_version')}`（範圍 `{context.get('evidence_scope')}`）。",
        f"- 基地總面積 {_fmt(facts['site']['area_including_water_m2'], 1)} m²；陸地 {_fmt(land_area, 1)} m²；基地內水面 {_fmt(facts['site']['water_area_intersection_m2'], 1)} m²；水平座標 EPSG:28992，單位 m。",
        f"- 快照含 {len(manifest.get('referenced_morphology_entry_ids', []))} 個 fabric 引用的 dictionary entries。`MOR-T07` 在 `config/morphology-dictionary/entries/` 找不到；20–40 m 接縫範圍是 FAB1 任務輸入，不是字典證據。",
        f"- 圖面繁中字型：`{_font_path()}`；已用該字型實際繪製「四種都市紋理方案」樣本文字並確認字形遮罩非空。",
        "",
        "## 任務限制與核心實際參數",
        "",
        "- 本次 Founder/FAB1 探索限制：新建 GFA 上限 146,873 m²，保留建築不計入此新建上限；建築高度上限 20 m。這些任務條件不改寫原始 site facts 或正式規劃規則。",
        f"- site facts 另載 FAR max 0.8：新建預算 {_fmt(old_new_budget, 1)} m²、含保留建築 GFA 上限估算的總量 {_fmt(old_total_upper, 1)} m²；保留估算 {_fmt(retained_upper, 1)} m²。兩種口徑並列，沒有互相覆寫。",
        f"- {intent_note}",
        "- 下表逐案抄錄核心 `plan.parameters`。fabric 的 `blocks` 尺寸與 `drawing_steps` editorial 尺度存在歧異；列出核心實際值不代表已消除來源矛盾。",
        "",
        "| 方案 | 核心實際參數（鍵＝值） | 北向順時針方向角／街廓軸角 (°) | intent 來源狀態 |",
        "|---|---|---:|---|",
    ]
    parameter_zh = {
        "block_long_m": "街廓長邊_m", "block_short_m": "街廓短邊_m",
        "street_width_m": "道路寬_m", "building_depth_m": "建築進深_m",
        "target_gfa_m2": "新建GFA目標_m2", "seam_width_m": "接縫寬_m",
    }
    for fabric_id in FABRIC_IDS:
        summary = summaries[fabric_id]
        params = summary.get("parameters", {})
        parameter_text = "；".join(f"{parameter_zh.get(key, key)}={value}" for key, value in sorted(params.items())) or "核心未提供"
        intent_source = summary.get("intent_source", {})
        source_text = str(intent_source.get("status", "未提供"))
        if intent_source.get("sha256"):
            source_text += f"；SHA-256 `{intent_source['sha256']}`"
        orientation_text = f"{_fmt(summary.get('orientation_deg'), 2)}／{_fmt(summary.get('block_axis_azimuth_deg'), 2)}"
        lines.append(f"| {_fabric_label(fabric_id)} (`{fabric_id}`) | {parameter_text} | {orientation_text} | {source_text} |")
    lines.extend([
        "",
        "## 方案指標",
        "",
        "| 方案 | FAB1e 整體狀態 | 新建 GFA (m²) | 新 FAR | GSI | FSI（新建＋保留估算） | L | OSR | 最大消防距離 (m) | 保留 GFA 上限估算 (m²) | 建築／街廓／道路數 | 未通過／未驗證 ID |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ])
    for fabric_id in FABRIC_IDS:
        summary = summaries[fabric_id]
        metrics = summary.get("metrics", {})
        counts = summary.get("geometry_summary", {})
        gfa = _finite_number(metrics.get("new_gfa_m2", metrics.get("new_gfa", metrics.get("gfa_new_m2"))))
        fsi_new = gfa / land_area if gfa is not None else None
        total_fsi = _finite_number(metrics.get("fsi"))
        if total_fsi is None and gfa is not None:
            total_fsi = (gfa + retained_upper) / land_area
        status, failures = _fab1c_case_status(summary)
        count_text = "/".join(str(counts.get(key, {}).get("feature_count", 0)) for key in ("buildings", "blocks", "roads"))
        lines.append(
            f"| {_fabric_label(fabric_id)} (`{fabric_id}`) | {status} | {_fmt(gfa, 1)} | {_fmt(metrics.get('new_far', fsi_new), 3)} | "
            f"{_fmt(metrics.get('gsi'), 3)} | {_fmt(total_fsi, 3)} | {_fmt(metrics.get('L'), 3)} | {_fmt(metrics.get('OSR'), 3)} | "
            f"{_fmt(metrics.get('max_fire_distance_upper_m'), 2)} | {_fmt(metrics.get('retained_gfa_upper_m2', retained_upper), 1)} | {count_text} | "
            f"{', '.join(failures) if failures else '無'} |"
        )
    lines.extend([
        "",
        "新 FAR 為 plan 新建 GFA／陸地分母；FSI 欄由核心以新建 GFA 加保留建築 GFA 上限估算計算。保留 GFA 是凍結 facts 的上限估算，並非實測樓板。核心沒有提供的指標一律標示「未提供」，不從圖面臆算。",
        "",
        "| 方案 | 道路，不含水岸 (%) | 道路＋水岸 (%) | 公園 (%) | 廣場 (%) | 主街連續軸向長度 (m) | 新建 GFA／146,873 (%) | 邊界建築宗地數 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for fabric_id in FABRIC_IDS:
        summary = summaries[fabric_id]
        metrics = summary.get("metrics", {})
        gfa = _finite_number(metrics.get("new_gfa_m2"))
        lines.append(f"| {_fabric_label(fabric_id)} | {_fmt(metrics.get('road_percent'), 2)} | {_fmt(metrics.get('road_waterfront_percent'), 2)} | {_fmt(metrics.get('park_percent'), 2)} | {_fmt(metrics.get('plaza_percent'), 2)} | {_fmt(metrics.get('primary_axis_span_m'), 2)} | {_fmt(100*gfa/146873 if gfa is not None else None, 2)} | {len(summary.get('api_plan', {}).get('boundary_parcels', []))} |")
    lines.extend([
        "",
        "道路比例由核心重新對公開街道走廊做幾何聯集，街廓內院消防巷與服務院另記為街廓／服務用地；全部通行空間比例亦保留於 metrics.all_circulation_percent。邊界宗地保留獨立幾何、建蔽與臨街檢查；用地圖不再疊加宗地或街廓邊界線。",
        "",
        "### FAB1d 水岸替代路徑與服務配置指標",
        "",
        "下表依核心 `label_zh`／`name_zh` 分別列出替代路徑；路寬、缺口長度、端點和障礙物讀自 plan，路徑長度優先讀核心屬性，未提供時按該路徑線幾何量測。未提供的欄位標示未提供，不由圖像估算。東北候選連接線的長度是當前候選幾何值，不是固定輸入數字，也不會抵銷 run-2 的西南 36.6962 m 未服務岸段；這些替代路徑不等於 `WATERFRONT_PUBLIC_BAND` 10 m gate 通過。",
        "",
        "| 方案 | 替代路徑數 | 核心路徑名稱 | 路寬 (m) | 水岸缺口 (m) | 路徑長度 (m) | 缺口端點與障礙物 | 服務設施數 | 南岸前緣軸角 (°) |",
        "|---|---:|---|---|---|---|---|---:|---:|",
    ])
    for fabric_id in FABRIC_IDS:
        api_plan = summaries[fabric_id].get("api_plan", {})
        detours = feature_rows(api_plan.get("waterfront_detours"))
        facilities = feature_rows(api_plan.get("service_facilities"))
        south_quay = _south_quay_feature(api_plan)
        south_props = _properties(south_quay) if south_quay else {}
        lines.append(
            f"| {_fabric_label(fabric_id)} | {len(detours)} | {_feature_route_labels_text(detours)} | "
            f"{_feature_numeric_values_text(detours, ('route_width_m', 'detour_width_m', 'access_width_m', 'width_m', 'width'))} | "
            f"{_feature_numeric_values_text(detours, ('gap_length_m', 'unserved_gap_m', 'gap_m', 'unserved_shoreline_m'))} | "
            f"{_feature_route_lengths_text(detours)} | "
            f"{_detour_endpoints_obstructions_text(detours)} | {len(facilities)} | "
            f"{_fmt(south_props.get('frontage_axis_azimuth_deg'), 1)} |"
        )
    lines.extend([
        "",
        "### 字典土地預算與 plan 實際分類面積",
        "",
        "字典預算來源為凍結輸入快照中的各案 `fabric.<fabric_id>.json` → `land_use_budget`（本輪 `inputs/fabrics/`），屬 editorial 範圍，不是法規。使用者覆寫只讀 `intents/<fabric_id>.json` 的 `land_use_budget_override` 或 `land_use_budget`；本次依 provenance，`NO_OVERRIDE_DICTIONARY_DEFAULTS` 或 `NO_OVERRIDE_REUSED_FROM_RUN2` 均表示無覆寫。兩種來源並列；超出字典範圍的覆寫標為衝突，不會暗中取代字典值。實際比例以各 plan `land_use` Polygon／MultiPolygon 面積總和除以相同陸地面積計算；分類差異或幾何重疊須檢視原圖徵，不能直接視為可互換預算。",
        "",
        "| 方案 | 分類 | 字典預算 (% 陸地) | 使用者覆寫 (% 陸地) | 覆寫關係 | plan 幾何面積 (m²) | plan 佔陸地 (%) |",
        "|---|---|---:|---:|---|---:|---:|",
    ])
    budget_labels = {"roads": "道路", "blocks": "建築街廓", "parks": "公園", "plazas": "廣場", "waterfront": "水岸步道", "service": "服務／卸貨", "retained_buildings": "保留建築基地", "public_facilities": "公共設施"}
    for fabric_id in FABRIC_IDS:
        fabric = load_json(INPUTS_DIR / "fabrics" / f"fabric.{fabric_id}.json")
        budget = fabric.get("land_use_budget", {}) if isinstance(fabric.get("land_use_budget"), Mapping) else {}
        api_plan = summaries[fabric_id].get("api_plan", {})
        intent = summaries[fabric_id].get("intent", {})
        intent = intent if isinstance(intent, Mapping) else {}
        category_areas = _landuse_area_by_category(api_plan)
        for category, label in budget_labels.items():
            budget_row = budget.get(category, {})
            dictionary_range = _budget_interval(budget_row)
            user_override = _intent_landuse_override(intent, category)
            area = _finite_number(category_areas.get(category, 0))
            ratio = 100 * area / land_area if area is not None else None
            lines.append(
                f"| {_fabric_label(fabric_id)} | {label} | {_percent_interval_text(dictionary_range)} | "
                f"{_percent_interval_text(user_override)} | {_budget_override_relation(dictionary_range, user_override)} | {_fmt(area, 1)} | {_fmt(ratio, 2)} |"
            )
        lines.append(f"| {_fabric_label(fabric_id)} | 陸地合計 | — | — | — | {_fmt(sum(category_areas.values()), 1)} | {_fmt(100*sum(category_areas.values())/land_area, 2)} |")
    lines.extend([
        "",
        "土地類別必須互斥且配置合計 100%；水岸公共帶與保留建築的交疊由實際幾何檢查，不沿用 run-1 的歷史重疊數字。",
        "圍合街廓字典已改為街廓淨密度，其 GSI 下限 0.40 使用街廓分母；其他方案保留字典原文口徑。`EVERY_BLOCK_BUILT_COVERAGE` 按本輪要求逐街廓對照下限，屬探索驗證條件，並非規劃法規。",
    ])
    lines.extend(["", "### 密度與字典先例包絡", "", "圍合街廓另以實際建築與街廓幾何重算淨 GSI、淨 FSI；其餘指標為全基地陸地口徑。不可把全基地毛密度與新版街廓淨密度當成同分母比較。先例限制見快照原文。", "", "| 方案 | 指標 | 本案 | 字典先例包絡 | 範圍關係 |", "|---|---|---:|---:|---|"])
    for fabric_id in FABRIC_IDS:
        fabric = load_json(INPUTS_DIR / "fabrics" / f"fabric.{fabric_id}.json")
        metrics = summaries[fabric_id]['metrics']
        density_rows = [('GSI','gsi'),('FSI','new_far'),('FSI','fsi'),('L','L'),('OSR','OSR')]
        if fabric_id == 'closed_block_extension':
            from shapely.ops import unary_union
            plan = summaries[fabric_id]['api_plan']
            blocks = unary_union([shape(row['geometry']) for row in plan['blocks']])
            new = [row for row in plan['buildings'] if not row['properties'].get('retained')]
            net_footprint = unary_union([shape(row['geometry']) for row in plan['buildings']]).intersection(blocks).area
            net_gfa = sum(shape(row['geometry']).intersection(blocks).area * row['properties']['floors'] + (shape(row['properties']['mezzanine_geometry']).intersection(blocks).area if row['properties'].get('mezzanine_geometry') else 0) for row in new)
            metrics = {**metrics, 'block_net_gsi': net_footprint / blocks.area if blocks.area else None, 'block_net_fsi': net_gfa / blocks.area if blocks.area else None}
            density_rows = [('GSI','block_net_gsi'), ('FSI','block_net_fsi')]
        for key, metric_key in density_rows:
            envelope = fabric.get('density_targets',{}).get(key,{}).get('range',{})
            value = metrics.get(metric_key)
            low, high = envelope.get('minimum'), envelope.get('maximum')
            relation = '未提供' if None in (value,low,high) else ('低於' if value < low else '高於' if value > high else '範圍內')
            label = key + ('（街廓淨密度，含保留足跡）' if metric_key == 'block_net_gsi' else '（街廓淨密度，僅新建）' if metric_key == 'block_net_fsi' else '（新建）' if metric_key=='new_far' else '（含保留估算）' if key=='FSI' else '')
            lines.append(f"| {_fabric_label(fabric_id)} | {label} | {_fmt(value,3)} | {_fmt(low,3)}–{_fmt(high,3)} | {relation} |")
    lines.extend([
        "",
        "### 核心 validator 逐項結果",
        "",
        "下表逐案列出 run-2 原有 52 個 validator、核心本輪新增的所有 ID、本輪必要 FAB1d validator（院落島數量、全案歸屬與道路淨用地僅適用院落案），以及 runner 的 `LANDUSE_NO_MOBILITY_OVERLAY` 與 `MAP_TEXT_LABEL_LIMIT` 圖面 gate。缺 ID 或結果旗標明列為未驗證，並使 runner 回傳 FAIL；繪圖成功、幾何非空或 comparison API 有回應不會改寫核心 FAIL。",
        "",
        "| 方案 | 原有 52 項 PASS | 原有 52 項未通過 (FAIL／ERROR／BLOCKED) | 原有 52 項未驗證 | FAB1d 適用項目 PASS | FAB1d 適用項目未通過 (FAIL／ERROR／BLOCKED) | FAB1d 適用項目未驗證 | 用地圖無模式覆蓋 gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ])
    for fabric_id in FABRIC_IDS:
        checks = summaries[fabric_id].get("core_checks", {})
        runner_checks = summaries[fabric_id].get("runner_checks", {})
        original_results = [_check_result_label(checks, check_id) for check_id in FAB1_ORIGINAL_VALIDATOR_IDS]
        new_results = [_check_result_label(checks, check_id) for check_id in FAB1C_REQUIRED_VALIDATOR_IDS if check_id not in {"COURTYARD_ISLAND_COUNT_SPACING", "COURTYARD_ISLAND_GLOBAL_MEMBERSHIP", "COURTYARD_ISLAND_ROAD_CLEARANCE"} or fabric_id == "courtyard_islands"]
        gate = runner_checks.get(LANDUSE_NO_MOBILITY_OVERLAY, {}) if isinstance(runner_checks, Mapping) else {}
        gate_status = str(gate.get("status", "未驗證")) if isinstance(gate, Mapping) else "未驗證"
        counts = lambda results, status: sum(1 for result in results if result == status)
        original_unverified = sum(1 for result in original_results if result.startswith("未驗證"))
        new_unverified = sum(1 for result in new_results if result.startswith("未驗證"))
        original_nonpass = len(original_results) - counts(original_results, "PASS") - original_unverified
        new_nonpass = len(new_results) - counts(new_results, "PASS") - new_unverified
        lines.append(
            f"| {_fabric_label(fabric_id)} | {counts(original_results, 'PASS')} | {original_nonpass} | "
            f"{original_unverified} | {counts(new_results, 'PASS')} | {new_nonpass} | {new_unverified} | {gate_status} |"
        )
    lines.extend([
        "",
        "| 方案 | 檢查 ID | 結果 |",
        "|---|---|---|",
    ])
    for fabric_id in FABRIC_IDS:
        checks = summaries[fabric_id].get("core_checks", {})
        check_map = checks.get("checks", {}) if isinstance(checks, Mapping) else {}
        global_status, global_failures = _check_status(checks if isinstance(checks, Mapping) else {})
        case_status, case_failures = _fab1c_case_status(summaries[fabric_id])
        lines.append(
            f"| {_fabric_label(fabric_id)} | 全域 validator 狀態 | {global_status}；本輪整體 {case_status}；未通過／缺少 ID：{', '.join(case_failures or global_failures) if case_failures or global_failures else '無'} |"
        )
        check_ids = set(check_map) if isinstance(check_map, Mapping) else set()
        check_ids.update(FAB1_ORIGINAL_VALIDATOR_IDS)
        check_ids.update(FAB1C_REQUIRED_VALIDATOR_IDS)
        for check_id in sorted(check_ids):
            result = ("不適用（此案非院落島）" if check_id in {"COURTYARD_ISLAND_COUNT_SPACING", "COURTYARD_ISLAND_GLOBAL_MEMBERSHIP", "COURTYARD_ISLAND_ROAD_CLEARANCE"} and fabric_id != "courtyard_islands" else _check_result_label(checks if isinstance(checks, Mapping) else {}, str(check_id)))
            lines.append(f"| {_fabric_label(fabric_id)} | `{check_id}` | {result} |")
        runner_checks = summaries[fabric_id].get("runner_checks", {})
        runner_gate = runner_checks.get(LANDUSE_NO_MOBILITY_OVERLAY, {}) if isinstance(runner_checks, Mapping) else {}
        gate_result = str(runner_gate.get("status", "未驗證")) if isinstance(runner_gate, Mapping) else "未驗證"
        lines.append(f"| {_fabric_label(fabric_id)} | `{LANDUSE_NO_MOBILITY_OVERLAY}`（runner render gate） | {gate_result} |")
        marker_gate = runner_checks.get(WATERFRONT_DETOUR_MARKED, {})
        lines.append(f"| {_fabric_label(fabric_id)} | `{WATERFRONT_DETOUR_MARKED}`（替代路徑實際標示） | {marker_gate.get('status', '未驗證')} |")
        label_gate = runner_checks.get(MAP_TEXT_LABEL_LIMIT, {})
        lines.append(f"| {_fabric_label(fabric_id)} | `{MAP_TEXT_LABEL_LIMIT}`（位置中文標註上限） | {label_gate.get('status', '未驗證')}；{label_gate.get('counts', {})} |")
    lines.extend([
        "",
        "完整檢查 JSON：" + "；".join(f"[{_fabric_label(fid)}](./{fid}-checks.json)" for fid in FABRIC_IDS) + "。",
        f"比較 API 原始回應保存在 [`comparison.json`](./comparison.json)；其狀態和 pairwise 結果不轉換為總分或排名。比較呼叫摘要：`{json.dumps(comparison.get('comparison', {}), ensure_ascii=False, sort_keys=True)[:500]}`。",
        "",
        "## 圖面說明",
        "",
        "- 每案提供 `-landuse-zh.png`、獨立 `-mobility-zh.png`、`-budget-zh.png`、`-massing-zh.png`、`-axon-zh.png`、`-section-zh.png`。用地圖呈現 land_use 面填色、道路實際路幅、建築、內院和繁中標籤，不畫步行／自行車／汽車模式覆蓋；mobility 圖以三色分別標示各模式可通行的完整道路路段。單案用地圖使用 2,800×1,600 畫布及側欄圖例；獨立預算圖以大字和 0–60% 軸線對照 plan、字典與 intent 覆寫。Polygon／MultiPolygon 外環及洞環各自繪製，洞內保留底圖。",
        "- `comparison-landuse-zh.png` 與 `comparison-massing-zh.png` 為 2×2 比較圖，共用相同 StudyArea 範圍、extent、像素比例和地面比例尺；方案名稱以繁體中文標示。",
        "- 等角圖逐棟垂直擠出實際建築 footprint。高度取 plan 高度，或僅在有 plan 樓層與 site-facts 層高時換算；缺值者只畫 footprint，不補造方盒。",
        "- 剖切線垂直於 plan 道路中心線並裁切在 site geometry；建築只有與剖切線相交才繪出。缺高度者不畫高度。若 plan 有 ROW polygon，實際相交區間按幾何繪出；只有中心線時標示道路寬度未提供。另附主街行人、樹帶、自行車與汽車的探索配置斷面，依 plan `primary_street.width_m` 配平總寬；寬度數值 gate 與核心 `PRIMARY_STREET_THROUGH_SITE` 實際結果分開顯示，斷面配置不代表交通或法規驗證。",
        "- 平面北箭頭表示 EPSG:28992 投影網格北；比例尺是地面公尺。等角圖比例尺只適用水平地面距離。繁中文字型經遮罩檢查。",
        "",
        "## 限制與未決事項",
        "",
        "- 未完成：意圖目前只接受有界的方向與尺度數值；街道選擇、公園／地標位置及類型組合覆寫尚未接入，會明確報錯。預設四案已產出，但不能宣稱完整意圖介面完成。",
        "- 空間語法：待接，本輪未重算，也沒有複製大型 Syntax JSON。跨供應商 Claude 覆核及 Founder 接受尚未執行。",
        "- 本輪依共用街網及主街保留區組織街廓，再配置矩形量體；輸出保留每個街廓的方向、建築及共用內院。實際尺寸與道路、公園面積是否合格，逐案依 validator 計算。",
        "- 公園先保留完整形狀及臨街空間；地景案依本輪 15–25% 條件，與字典 18–28% 範圍另行並列。連續主公園、圍合街廓方向接縫及大型院落島仍須連同實際圖面覆核。",
        "- 零件原文已快照，但目前樣板尺度主要由 FAB1 指定範圍控制，未全面套用零件字典的組合、適用條件及高度剖面。點式群採單棟 20×20 m 的明示草稿假設，不能將零件字典群組尺度誤當單棟尺度。",
        "- Site facts 為探索性輸入，CTX1 僅供探索。OSM、入口、公共通行、3DBAG 高度和既有建築 GFA 都有來源限制，不能由此推定法定公共可達、地籍面積或可建權利。",
        "- fabric `blocks` 尺寸與 `drawing_steps` editorial 尺度有內部矛盾。本次保留原始字典，逐案列出核心實際參數；scalar 執行值不代表該矛盾已解決。",
        "- `landuse.csv` 記錄每個輸出面圖徵的幾何面積及同一陸地分母比例。面積重疊或用途分類差異時，不應直接加總成完整土地預算。",
        "- GFA/FAR、通行連續性、道路接續、消防距離及保留建物避讓依核心 validator 結果；FAIL 項目保留原樣，修正後須重新驗證。此輸出不接受任何方案。",
        "- 未提供日照、風、交通量、公共性、成本或使用者行為模擬；也沒有跨指標權重或總排名。",
        "",
        "## 執行紀錄與驗證證據",
        "",
        "- 本 README 由 runner 在生成結尾寫入；逐案核心檢查結果、圖面 SHA-256、快照 manifest SHA-256 及 render audit 分別保存在本目錄 JSON。測試套件結果未由 runner 執行或記錄，標示為「未提供」，不推定通過。",
        "- runner 會在完成前檢查本輪每個產物小於 5 MB；此限制不表示任何核心 validator 通過。既有 run-1、run-2 與 partial-run 證據由 runner 保留，不在此聲稱已重算其逐檔完整性。",
        "",
        "## 產物",
        "",
        "四個方案各有 `-plan.json`、`-landuse.csv`、`-checks.json`、`-landuse-zh.png`、`-mobility-zh.png`、`-budget-zh.png`、`-massing-zh.png`、`-axon-zh.png`、`-section-zh.png`；另有兩張四格比較圖與 `comparison.json`。exact-byte 輸入快照及 SHA-256 manifest 在 `inputs/`。",
        "",
    ])
    return "\n".join(lines)

def _assert_artifact_limits() -> None:
    too_large = [
        (path, path.stat().st_size)
        for path in RUN_DIR.rglob("*")
        if path.is_file() and path.stat().st_size >= MAX_ARTIFACT_BYTES
    ]
    if too_large:
        details = ", ".join(f"{path.relative_to(ROOT)}={size:,} bytes" for path, size in too_large)
        raise ValueError(f"FAB1 產物每檔必須小於 5 MB：{details}")


def _configure_run_dir(output_dir: Path) -> None:
    global RUN_DIR, INPUTS_DIR
    candidate = output_dir if output_dir.is_absolute() else ROOT / output_dir
    candidate = candidate.resolve()
    allowed_root = OUTPUT_DIR.resolve()
    try:
        relative = candidate.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(f"輸出目錄必須位於 {allowed_root} 之內：{candidate}") from exc
    if not relative.parts or relative.parts[0] in {"run-1", "run-2", "run-2-partial", "run-2-partial2", "inputs"}:
        raise ValueError("輸出不可指向既有證據或輸入目錄；run-1、run-2 與 partial runs 必須保留。")
    RUN_DIR = candidate
    INPUTS_DIR = RUN_DIR / "inputs"


def _assert_fresh_run_dir(*, reuse_run2_snapshot: bool = False) -> None:
    expected = []
    for fabric_id in FABRIC_IDS:
        expected.extend(
            RUN_DIR / f"{fabric_id}{suffix}"
            for suffix in (
                "-plan.json", "-checks.json", "-landuse.csv", "-landuse-zh.png", "-mobility-zh.png", "-budget-zh.png",
                "-massing-zh.png", "-axon-zh.png", "-section-zh.png",
            )
        )
        if not reuse_run2_snapshot and (INTENTS_DIR / f"{fabric_id}.json").is_file():
            expected.append(RUN_DIR / "intent-sources" / f"{fabric_id}.json")
    expected.extend(RUN_DIR / name for name in ("comparison.json", "comparison-landuse-zh.png", "comparison-massing-zh.png", "README-zh.md"))
    expected.append(INPUTS_DIR / "manifest.json")
    existing = [path for path in expected if path.exists()]
    if existing:
        paths = ", ".join(str(path.relative_to(ROOT)) for path in existing)
        raise FileExistsError(f"拒絕覆寫既有 FAB1 產物；請指定新的 --output-dir。既有檔案：{paths}")


def run(
    *,
    command: str,
    output_dir: Path = Path("artifacts/fab1/run-4"),
    reuse_run2_snapshot: bool = False,
) -> None:
    _configure_run_dir(output_dir)
    _assert_fresh_run_dir(reuse_run2_snapshot=reuse_run2_snapshot)
    _font_path()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_frozen_run2_snapshot() if reuse_run2_snapshot else snapshot_inputs()
    paths = snapshot_paths(manifest)
    if reuse_run2_snapshot:
        source_root = (OUTPUT_DIR / "run-2" / "inputs").resolve()
        paths = {key: INPUTS_DIR / path.resolve().relative_to(source_root) for key, path in paths.items()}
    facts = load_json(paths["site-facts"])
    context = load_json(paths["context-facts"])
    input_manifest_hash = sha256_file(INPUTS_DIR / "manifest.json")
    project_revision = manifest.get("project_source_revision", {})
    runner_sha256 = sha256_file(Path(__file__).resolve())
    core_path = ROOT / "src" / "urban_design" / "generation" / "fabric_plan.py"
    if not core_path.is_file():
        raise FileNotFoundError(f"找不到 FAB1 核心模組：{core_path}")
    core_source_sha256 = sha256_file(core_path)
    summaries: dict[str, dict[str, Any]] = {}
    plans: dict[str, dict[str, Any]] = {}
    api_plans: dict[str, dict[str, Any]] = {}
    checks_by_id: dict[str, dict[str, Any]] = {}
    for fabric_id in FABRIC_IDS:
        fabric_path = paths.get(f"fabric:{fabric_id}")
        if fabric_path is None:
            raise FileNotFoundError(f"fabric 不在快照中：{fabric_id}")
        fabric = load_json(fabric_path)
        plan, checks, summary, api_plan = _run_one(
            fabric_id,
            facts=facts,
            context=context,
            fabric=fabric,
            fabric_path=fabric_path,
            input_manifest_hash=input_manifest_hash,
            source_revision=project_revision,
            runner_sha256=runner_sha256,
            core_source_sha256=core_source_sha256,
            reused_run2_snapshot=reuse_run2_snapshot,
        )
        plans[fabric_id] = plan
        api_plans[fabric_id] = api_plan
        checks_by_id[fabric_id] = checks
        summary["api_plan"] = api_plan
        summaries[fabric_id] = summary

    from urban_design.generation.fabric_plan import compare_plans

    compare_result = compare_plans([api_plans[fabric_id] for fabric_id in FABRIC_IDS])
    comparison = _comparison_source_summary(api_plans, compare_result)
    write_json(RUN_DIR / "comparison.json", comparison)
    _draw_comparison_grid(RUN_DIR / "comparison-landuse-zh.png", plans, facts, mode="landuse")
    _draw_comparison_grid(RUN_DIR / "comparison-massing-zh.png", plans, facts, mode="massing")
    (RUN_DIR / "README-zh.md").write_text(
        _readme_content(manifest=manifest, summaries=summaries, comparison=comparison, command=command, reused_run2_snapshot=reuse_run2_snapshot),
        encoding="utf-8",
    )
    _assert_artifact_limits()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="產生 FAB1 四種都市紋理方案及繁體中文圖面。")
    parser.add_argument("--snapshot-only", action="store_true", help="只建立或驗證不可變輸入快照，不呼叫 FAB1 核心生成器。")
    parser.add_argument("--repair-snapshot", action="store_true", help="明確追加缺少的 morphology entry 快照，保留舊 manifest 作為修復紀錄。")
    parser.add_argument("--reuse-run2-snapshot", action="store_true", help="只讀並驗證 run-2 exact-byte 快照；略過 live source revision 與 intent 讀取。")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/fab1/run-4"), help="新產物目錄；必須位於 artifacts/fab1 內，且不可覆寫舊 run。")
    parser.add_argument("--intent-dir", type=Path, help="FAB2：讀取設計意圖 JSON，使用凍結 FAB1 本地輸入。")
    args = parser.parse_args(argv)
    if args.intent_dir is not None:
        if args.snapshot_only or args.repair_snapshot or args.reuse_run2_snapshot:
            parser.error("FAB2 --intent-dir 不可與 FAB1 snapshot 選項混用。")
        from fab2_runner import run_intents
        output = args.output_dir
        if output == Path("artifacts/fab1/run-4"):
            output = Path("artifacts/fab2/run-1")
        return run_intents(args.intent_dir, output)
    if args.snapshot_only and args.reuse_run2_snapshot:
        parser.error("--snapshot-only 不可與 --reuse-run2-snapshot 同時使用。")
    if args.repair_snapshot and args.reuse_run2_snapshot:
        parser.error("run-2 exact-byte replay 不允許修補或改寫 frozen snapshot。")
    _configure_run_dir(args.output_dir)
    if not args.reuse_run2_snapshot:
        revision = _git_value(FABRIC_SOURCE_DIR, "rev-parse", "HEAD")
        if not revision or not revision.startswith(FAB1B_DICTIONARY_REVISION):
            raise ValueError(f"FAB1b 字典來源 revision 不符：需要 {FAB1B_DICTIONARY_REVISION}，實際 {revision}")
    if args.snapshot_only:
        manifest = snapshot_inputs(repair=args.repair_snapshot)
        print(json.dumps({
            "status": "SNAPSHOT_READY",
            "manifest": str((INPUTS_DIR / "manifest.json").relative_to(ROOT)),
            "file_count": len(manifest.get("files", [])),
            "sha256": sha256_file(INPUTS_DIR / "manifest.json"),
        }, ensure_ascii=False))
        return 0
    command = f"TMPDIR=/private/tmp PYTHONPATH=src .venv/bin/python scripts/run_fabric_plan.py --output-dir {args.output_dir}"
    if args.reuse_run2_snapshot:
        command += " --reuse-run2-snapshot"
    try:
        run(command=command, output_dir=args.output_dir, reuse_run2_snapshot=args.reuse_run2_snapshot)
    except Exception as exc:
        print(f"FAB1 runner failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"FAB1 產物已寫入 {RUN_DIR}")
    failed = {}
    for fid in FABRIC_IDS:
        check_artifact = load_json(RUN_DIR / f"{fid}-checks.json")
        case_status, case_failures = _fab1c_case_status({
            "fabric_id": fid,
            "core_checks": check_artifact.get("core_validator", {}),
            "runner_checks": check_artifact.get("runner_checks", {}),
        })
        failed[fid] = case_failures if case_status != "PASS" else []
    comparison = load_json(RUN_DIR / "comparison.json")["comparison"]
    if any(failed.values()) or comparison.get("status") != "PASS":
        print(json.dumps({"status": "FAIL", "failures": failed, "comparison_status": comparison.get("status")}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
