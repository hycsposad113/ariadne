from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import struct
from pathlib import Path

import pytest
from shapely import to_wkb
from shapely.geometry import box

from urban_design.models import UnavailableValue
from urban_design.morphology.floor_estimate import estimate_floor_count_from_3dbag
from urban_design.three_d_bag import (
    TileSource,
    extract_3dbag_height_table,
    load_3dbag_height_table,
    normalize_bag_identificatie,
)


PREFIX = "NL.IMBAG.Pand."


def _bag_id(number: int) -> str:
    return f"{number:016d}"


def _gpkg_geometry(geometry, srs_id: int = 7415) -> bytes:
    return b"GP" + bytes((0, 1)) + struct.pack("<i", srs_id) + to_wkb(
        geometry, byte_order=1, output_dimension=2
    )


def _write_fixture_tile(
    path: Path,
    *,
    buildings: list[tuple[str, float | None, object]],
    roof_parts: list[tuple[str, int, float | None]],
) -> str:
    gpkg_path = path.with_suffix(".gpkg")
    connection = sqlite3.connect(gpkg_path)
    connection.executescript(
        """
        CREATE TABLE gpkg_contents (
          table_name TEXT PRIMARY KEY, data_type TEXT, identifier TEXT,
          description TEXT, last_change TEXT, min_x REAL, min_y REAL,
          max_x REAL, max_y REAL, srs_id INTEGER
        );
        CREATE TABLE gpkg_geometry_columns (
          table_name TEXT, column_name TEXT, geometry_type_name TEXT,
          srs_id INTEGER, z INTEGER, m INTEGER
        );
        CREATE TABLE pand (
          fid INTEGER PRIMARY KEY, geom BLOB, identificatie TEXT,
          b3_h_maaiveld REAL
        );
        CREATE TABLE lod22_2d (
          fid INTEGER PRIMARY KEY, geom BLOB, identificatie TEXT,
          b3_h_70p REAL, b3_dd_id INTEGER, b3_pand_deel_id INTEGER
        );
        INSERT INTO gpkg_contents(table_name, data_type, identifier, srs_id)
          VALUES ('pand', 'features', 'pand', 7415),
                 ('lod22_2d', 'features', 'lod22_2d', 7415);
        INSERT INTO gpkg_geometry_columns
          VALUES ('pand', 'geom', 'MULTIPOLYGON', 7415, 2, 0),
                 ('lod22_2d', 'geom', 'MULTIPOLYGON', 7415, 2, 0);
        """
    )
    connection.executemany(
        "INSERT INTO pand(fid, geom, identificatie, b3_h_maaiveld) VALUES (?, ?, ?, ?)",
        [
            (index, _gpkg_geometry(geometry), PREFIX + bag_id, ground)
            for index, (bag_id, ground, geometry) in enumerate(buildings, start=1)
        ],
    )
    connection.executemany(
        """INSERT INTO lod22_2d
           (fid, geom, identificatie, b3_h_70p, b3_dd_id, b3_pand_deel_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (index, _gpkg_geometry(box(0, 0, 1, 1)), PREFIX + bag_id, roof, dd_id, 0)
            for index, (bag_id, dd_id, roof) in enumerate(roof_parts, start=1)
        ],
    )
    connection.commit()
    connection.close()
    path.write_bytes(gzip.compress(gpkg_path.read_bytes(), mtime=0))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_table(tmp_path: Path):
    study_area_path = tmp_path / "study-area.geojson"
    study_area_path.write_text(
        json.dumps(
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
            }
        ),
        encoding="utf-8",
    )
    study_area_hash = hashlib.sha256(study_area_path.read_bytes()).hexdigest()
    tile_path = tmp_path / "tile-1-2-3.gpkg.gz"
    tile_hash = _write_fixture_tile(
        tile_path,
        buildings=[
            (_bag_id(1), 1.25, box(12, 0, 13, 1)),
            # Inside the buffer bbox but outside its rounded corner.
            (_bag_id(2), 1.0, box(13.8, 13.8, 14.0, 14.0)),
            # Touches the exact 5 m buffer boundary.
            (_bag_id(3), -1.0, box(15, 0, 16, 1)),
            (_bag_id(4), 2.0, box(2, 2, 3, 3)),
            (_bag_id(5), 4.0, box(3, 3, 4, 4)),
        ],
        roof_parts=[
            (_bag_id(1), 1, 10.0),
            (_bag_id(1), 2, 11.0),
            (_bag_id(2), 1, 30.0),
            (_bag_id(3), 1, 7.0),
            (_bag_id(5), 1, 3.0),
        ],
    )
    output_path = tmp_path / "height-table.json"
    table = extract_3dbag_height_table(
        study_area_geojson_path=study_area_path,
        study_area_artifact_sha256=f"sha256:{study_area_hash}",
        study_area_geometry_sha256="sha256:" + "a" * 64,
        study_area_id="study-area-fixture-v1",
        study_area_version="v1",
        study_area_crs="EPSG:28992",
        tile_sources=[
            TileSource(
                tile_id="1/2/3",
                path=tile_path,
                sha256=f"sha256:{tile_hash}",
                url="https://data.3dbag.nl/v20250903/tiles/1/2/3/1-2-3.gpkg.gz",
            )
        ],
        data_version="v2025.09.03",
        buffer_distance_m=5.0,
        output_path=output_path,
    )
    return table, output_path


def test_extracts_only_footprints_intersecting_exact_buffer_and_uses_max_roof_p70(
    tmp_path: Path,
) -> None:
    table, output_path = _fixture_table(tmp_path)

    assert set(table.records) == {
        PREFIX + _bag_id(1),
        PREFIX + _bag_id(3),
        PREFIX + _bag_id(4),
        PREFIX + _bag_id(5),
    }
    inside = table.records[PREFIX + _bag_id(1)]
    assert inside.roof_p70_height_m == pytest.approx(11.0)
    assert inside.ground_height_m == pytest.approx(1.25)
    assert inside.roof_part_count == 2
    assert inside.height_above_ground_m == pytest.approx(9.75)
    assert inside.roof_p70_aggregation == "maximum-roofpart-b3_h_70p"

    boundary_touch = table.records[PREFIX + _bag_id(3)]
    assert boundary_touch.height_above_ground_m == pytest.approx(8.0)

    no_roof = table.records[PREFIX + _bag_id(4)]
    assert no_roof.roof_p70_height_m is None
    assert no_roof.height_above_ground_m is None
    assert no_roof.status == "UNAVAILABLE"

    invalid_order = table.records[PREFIX + _bag_id(5)]
    assert invalid_order.roof_p70_height_m == pytest.approx(3.0)
    assert invalid_order.ground_height_m == pytest.approx(4.0)
    assert invalid_order.height_above_ground_m is None
    assert invalid_order.status == "UNAVAILABLE"

    reloaded = load_3dbag_height_table(output_path)
    assert reloaded == table
    assert table.data_version == "v2025.09.03"
    assert table.buffer_distance_m == 5.0
    assert table.study_area_horizontal_crs == "EPSG:28992"
    assert table.vertical_reference == "NAP height (EPSG:5709); compound tile CRS EPSG:7415"


def test_height_table_floor_integration_and_missing_match_are_explicit() -> None:
    from urban_design.three_d_bag import BuildingHeightTable, BuildingHeightRecord

    table = BuildingHeightTable(
        data_version="v2025.09.03",
        license="CC BY 4.0",
        attribution="© 3DBAG by tudelft3d and 3DGI",
        study_area_id="study-area-fixture-v1",
        study_area_version="v1",
        study_area_geometry_sha256="sha256:" + "a" * 64,
        study_area_artifact_sha256="sha256:" + "b" * 64,
        study_area_horizontal_crs="EPSG:28992",
        vertical_reference="NAP height (EPSG:5709); compound tile CRS EPSG:7415",
        buffer_distance_m=500.0,
        buffer_geometry_sha256="sha256:" + "c" * 64,
        buffer_bbox_m=(-500.0, -500.0, 510.0, 510.0),
        buffered_area_m2=1000.0,
        records={
            PREFIX + _bag_id(1): BuildingHeightRecord(
                bag_identificatie=PREFIX + _bag_id(1),
                roof_p70_height_m=13.0,
                ground_height_m=1.0,
                source_version="v2025.09.03",
                roof_part_count=2,
                source_tile_ids=("9/304/512",),
                roof_p70_aggregation="maximum-roofpart-b3_h_70p",
                status="AVAILABLE",
                unavailable_reason=None,
            ),
            PREFIX + _bag_id(2): BuildingHeightRecord(
                bag_identificatie=PREFIX + _bag_id(2),
                roof_p70_height_m=10.0,
                ground_height_m=1.0,
                source_version="v2025.09.03",
                roof_part_count=1,
                source_tile_ids=("9/304/512",),
                roof_p70_aggregation="maximum-roofpart-b3_h_70p",
                status="UNAVAILABLE",
                unavailable_reason="Fixture quality flag",
            ),
        },
    )

    result = estimate_floor_count_from_3dbag(
        building_id="building-1",
        bag_id=_bag_id(1),
        building_use="industriefunctie",
        height_table=table,
    )
    assert result.floor_count == (1, 4)
    assert result.data_version == "v2025.09.03"
    assert result.height_field_name == "b3_h_70p"

    missing = estimate_floor_count_from_3dbag(
        building_id="building-missing",
        bag_id=_bag_id(9),
        building_use="woonfunctie",
        height_table=table,
    )
    assert isinstance(missing.floor_count, UnavailableValue)
    assert missing.floor_count.status == "unavailable"

    flagged = estimate_floor_count_from_3dbag(
        building_id="building-flagged",
        bag_id=_bag_id(2),
        building_use="woonfunctie",
        height_table=table,
    )
    assert isinstance(flagged.floor_count, UnavailableValue)
    assert flagged.floor_count.reason == "Fixture quality flag"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (_bag_id(1), PREFIX + _bag_id(1)),
        (PREFIX + _bag_id(2), PREFIX + _bag_id(2)),
    ],
)
def test_normalizes_only_exact_bag_identificatie_forms(value: str, expected: str) -> None:
    assert normalize_bag_identificatie(value) == expected


def test_rejects_non_projected_scope_and_study_area_hash_mismatch(tmp_path: Path) -> None:
    table, output_path = _fixture_table(tmp_path)
    assert table.data_version == "v2025.09.03"

    study_area_path = tmp_path / "study-area.geojson"
    with pytest.raises(ValueError, match="EPSG:28992"):
        extract_3dbag_height_table(
            study_area_geojson_path=study_area_path,
            study_area_artifact_sha256=table.study_area_artifact_sha256,
            study_area_geometry_sha256=table.study_area_geometry_sha256,
            study_area_id=table.study_area_id,
            study_area_version=table.study_area_version,
            study_area_crs="EPSG:4326",
            tile_sources=[],
            data_version=table.data_version,
            buffer_distance_m=5.0,
            output_path=output_path,
        )

    with pytest.raises(ValueError, match="SHA-256"):
        extract_3dbag_height_table(
            study_area_geojson_path=study_area_path,
            study_area_artifact_sha256="sha256:" + "0" * 64,
            study_area_geometry_sha256=table.study_area_geometry_sha256,
            study_area_id=table.study_area_id,
            study_area_version=table.study_area_version,
            study_area_crs="EPSG:28992",
            tile_sources=[
                TileSource(
                    tile_id=source["tile_id"],
                    path=Path(source["path"]),
                    sha256=source["sha256"],
                    url=source["url"],
                )
                for source in table.source_tiles
            ],
            data_version=table.data_version,
            buffer_distance_m=5.0,
            output_path=output_path,
        )
