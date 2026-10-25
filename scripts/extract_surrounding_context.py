#!/usr/bin/env python3
"""Extract pinned M4H OSM context using only the already-local source files."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from urban_design.surrounding_context import extract_osm_context, sha256_file  # noqa: E402


EXPECTED_PBF_SHA256 = "71379de6fcb38b114ae2ee564cac99cfb2763b6cc3f6d87667c1079ea578401c"
DEFAULT_PBF = Path.home() / ".local/share/urban-design-data/osm/zuid-holland-260922.osm.pbf"
DEFAULT_STUDY_AREA = (
    ROOT.parent
    / "project/.urban_design_runtime/artifacts/study-area-bridge/study-areas/"
    "4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson"
)
DEFAULT_DATA_ROOT = Path.home() / ".local/share/urban-design-data/context"
DEFAULT_3DBAG_ROOT = Path.home() / ".local/share/urban-design-data/3dbag"
DEFAULT_REFERENCE_MANIFEST = ROOT / "config/context/manifest.json"
HEIGHT_TABLE_NAME = "height-table-v2025.09.03-study-area-v5-buffer500m.json"
THREE_DBAG_TILES = (
    "tile-8-296-512-v2025.09.03.gpkg.gz",
    "tile-9-304-512-v2025.09.03.gpkg.gz",
    "tile-9-304-516-v2025.09.03.gpkg.gz",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", type=Path, default=DEFAULT_PBF)
    parser.add_argument("--study-area", type=Path, default=DEFAULT_STUDY_AREA)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--three-dbag-root", type=Path, default=DEFAULT_3DBAG_ROOT)
    parser.add_argument("--reference-manifest", type=Path, default=DEFAULT_REFERENCE_MANIFEST)
    parser.add_argument("--context-distance-m", type=float, default=2000.0)
    args = parser.parse_args()

    if not args.pbf.is_file():
        parser.error(f"offline source PBF is missing: {args.pbf}")
    if not args.study_area.is_file():
        parser.error(f"active StudyArea artifact is missing: {args.study_area}")
    pbf_hash = sha256_file(args.pbf)
    if pbf_hash != EXPECTED_PBF_SHA256:
        parser.error("existing PBF hash differs from the inspected local source; refusing extraction")

    height_table = args.three_dbag_root / HEIGHT_TABLE_NAME
    tile_paths = [args.three_dbag_root / name for name in THREE_DBAG_TILES]
    missing_bag_inputs = [path for path in [height_table, *tile_paths] if not path.is_file()]
    if missing_bag_inputs:
        parser.error("existing 3D BAG inputs are incomplete: " + ", ".join(path.name for path in missing_bag_inputs))

    data_manifest = args.data_root / "manifest.json"
    if data_manifest.exists():
        parser.error(f"external manifest already exists; refusing to overwrite: {data_manifest}")
    if args.reference_manifest.exists():
        parser.error(f"Git reference manifest already exists; refusing to overwrite: {args.reference_manifest}")
    extraction_id = datetime.now(timezone.utc).strftime("context-%Y%m%dT%H%M%SZ")
    output_dir = args.data_root / extraction_id
    if output_dir.exists():
        parser.error(f"context run directory already exists; refusing to overwrite: {output_dir}")

    manifest = extract_osm_context(
        pbf_path=args.pbf,
        study_area_path=args.study_area,
        output_dir=output_dir,
        height_table_path=height_table,
        three_dbag_tile_paths=tile_paths,
        context_distance_m=args.context_distance_m,
        study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
        study_area_version="v5",
        extraction_id=extraction_id,
        source_data_version="2026-09-22T20:22:59Z",
    )

    encoded_manifest = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    args.data_root.mkdir(parents=True, exist_ok=True)
    args.reference_manifest.parent.mkdir(parents=True, exist_ok=True)
    # Both destinations were checked absent above; write the same small
    # provenance document next to external data and into the source tree.
    data_manifest.write_bytes(encoded_manifest)
    args.reference_manifest.write_bytes(encoded_manifest)
    print(json.dumps({
        "status": "EXTRACTED",
        "run_directory": str(output_dir),
        "external_manifest": str(data_manifest),
        "reference_manifest": str(args.reference_manifest),
        "source_pbf_sha256": manifest["source_pbf_sha256"],
        "study_area_geometry_sha256": manifest["study_area_geometry_sha256"],
        "context_distance_m": manifest["context_distance_m"],
        "feature_counts": manifest["feature_counts"],
        "height_source_counts": manifest["height_policy"]["height_source_counts"],
        "3dbag_matched_buildings": manifest["3dbag"]["matched_building_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
