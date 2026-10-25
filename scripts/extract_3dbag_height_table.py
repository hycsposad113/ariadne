#!/usr/bin/env python3
"""Build a BAG-keyed 3D BAG height table from frozen official tile responses.

This script performs no network access and no project-state database writes.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from urban_design.three_d_bag import (
    THREE_DBAG_EXTRACTOR_VERSION,
    TileSource,
    extract_3dbag_height_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "config/3dbag-height-source-manifest-v1.json"
DATA_ROOT = (Path.home() / ".local/share/urban-design-data/3dbag").resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def build_from_manifest(manifest_path: Path, *, record_output: bool = False) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, Mapping):
        raise ValueError("source manifest must be a JSON object")
    if manifest.get("schema_version") != "3dbag-height-source-manifest-v1":
        raise ValueError("unsupported 3D BAG source manifest")
    dataset = manifest.get("dataset")
    study_area = manifest.get("study_area")
    scope = manifest.get("scope")
    preflight = manifest.get("preflight")
    processing = manifest.get("processing")
    height_table = manifest.get("height_table")
    tile_records = manifest.get("tiles")
    if not all(
        isinstance(item, Mapping)
        for item in (dataset, study_area, scope, preflight, processing, height_table)
    ):
        raise ValueError(
            "manifest dataset, study_area, scope, preflight, processing, and height_table sections are required"
        )
    if processing.get("extractor_version") != THREE_DBAG_EXTRACTOR_VERSION:
        raise ValueError("manifest extractor_version does not match the local extractor")
    if not isinstance(tile_records, list) or not tile_records:
        raise ValueError("manifest must contain downloaded tile records")

    study_area_path = Path(study_area["artifact_path"])
    output_path = Path(height_table["path"])
    if not output_path.resolve().is_relative_to(DATA_ROOT):
        raise ValueError(f"derived height table must remain under {DATA_ROOT}")
    tiles = tuple(
        TileSource(
            tile_id=item["tile_id"],
            path=Path(item["path"]),
            sha256=item["sha256"],
            url=item["url"],
        )
        for item in tile_records
        if isinstance(item, Mapping)
    )
    if len(tiles) != len(tile_records):
        raise ValueError("every tile manifest record must be an object")

    table = extract_3dbag_height_table(
        study_area_geojson_path=study_area_path,
        study_area_artifact_sha256=study_area["artifact_sha256"],
        study_area_geometry_sha256=study_area["geometry_sha256"],
        study_area_id=study_area["id"],
        study_area_version=study_area["version"],
        study_area_crs=study_area["horizontal_crs"],
        tile_sources=tiles,
        data_version=dataset["version"],
        buffer_distance_m=scope["buffer_distance_m"],
        output_path=output_path,
    )
    result: dict[str, Any] = {
        "output_path": str(output_path.resolve()),
        "sha256": _sha256(output_path),
        "size_bytes": output_path.stat().st_size,
        "study_area_id": table.study_area_id,
        "study_area_version": table.study_area_version,
        "data_version": table.data_version,
        "buffer_distance_m": table.buffer_distance_m,
        "buffered_area_m2": table.buffered_area_m2,
        "buffer_geometry_sha256": table.buffer_geometry_sha256,
        "record_count": len(table.records),
        "available_count": sum(item.status == "AVAILABLE" for item in table.records.values()),
        "unavailable_count": sum(item.status == "UNAVAILABLE" for item in table.records.values()),
    }
    if record_output:
        mutable_manifest = dict(manifest)
        mutable_height_table = dict(height_table)
        mutable_height_table.update(
            {
                "sha256": result["sha256"],
                "size_bytes": result["size_bytes"],
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "buffer_geometry_sha256": table.buffer_geometry_sha256,
                "record_count": len(table.records),
                "available_count": result["available_count"],
                "unavailable_count": result["unavailable_count"],
            }
        )
        mutable_manifest["height_table"] = mutable_height_table
        manifest_path.write_text(
            json.dumps(mutable_manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        result["manifest_updated"] = str(manifest_path.resolve())
    else:
        result["manifest_updated"] = None
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--record-output",
        action="store_true",
        help="write derived file hash, size, count, and creation time into the source manifest",
    )
    args = parser.parse_args()
    result = build_from_manifest(args.manifest, record_output=args.record_output)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
