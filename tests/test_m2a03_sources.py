"""Offline transport, provenance, and v5 package replay gates."""

from __future__ import annotations

import io
import json
import calendar
import hashlib
from pathlib import Path
import shutil
from urllib.error import HTTPError
import zipfile

import pytest

from urban_design.analysis_inputs import (
    AnalysisInputPublicationError,
    ArtifactIntegrityError,
    build_m2a03_package,
    load_analysis_input_package,
)
from urban_design.m2a03_sources import (
    SourceAcquisitionError,
    _capture,
    _epw_metadata,
    _source_request_receipt,
    _tracked_fetcher,
    acquire_epw_candidates,
    acquire_mandatory_sources,
    acquire_osm_overpass,
    acquire_pdok_collection,
    default_fetch,
    query_bounds_crs84,
)
from urban_design.store import ProjectStateStore

from test_m2a03_analysis_inputs import _make_store


NOW = "2026-09-18T18:00:00+00:00"


def test_capture_rejects_response_larger_than_configured_limit() -> None:
    received_kwargs: list[dict[str, object]] = []

    def fetch(_url: str, **_kwargs: object):
        received_kwargs.append(dict(_kwargs))
        return b"12345", 200, {}, NOW

    with pytest.raises(SourceAcquisitionError) as raised:
        _capture(fetch, "https://example.test/large", max_response_bytes=4)
    assert received_kwargs[0]["max_response_bytes"] == 4
    assert raised.value.response_metadata["response_received"] is True
    assert raised.value.response_metadata["response_complete"] is True
    assert raised.value.response_metadata["response_limit_exceeded"] is True
    assert raised.value.response_metadata["observed_body_bytes"] == 5


def test_default_fetch_stops_before_reading_declared_oversize_response(monkeypatch) -> None:
    read_calls: list[int] = []

    class Response:
        status = 200
        headers = {"Content-Length": "11"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size: int = -1) -> bytes:
            read_calls.append(size)
            return b"x" * 11

    monkeypatch.setattr("urban_design.m2a03_sources.urllib.request.urlopen", lambda *_a, **_k: Response())

    with pytest.raises(SourceAcquisitionError, match="10 bytes") as raised:
        default_fetch("https://example.test/large", max_response_bytes=10)

    assert read_calls == []
    assert raised.value.response_metadata == {
        "response_received": True,
        "response_complete": False,
        "http_error_received": False,
        "response_limit_exceeded": True,
        "http_status": 200,
        "declared_size_bytes": 11,
        "observed_body_bytes": 0,
        "response_headers": {"content-length": "11"},
    }


def test_default_fetch_reads_at_most_one_byte_over_stream_limit(monkeypatch) -> None:
    read_calls: list[int] = []

    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size: int = -1) -> bytes:
            read_calls.append(size)
            return b"x" * size

    monkeypatch.setattr("urban_design.m2a03_sources.urllib.request.urlopen", lambda *_a, **_k: Response())

    with pytest.raises(SourceAcquisitionError, match="10 bytes") as raised:
        default_fetch("https://example.test/large", max_response_bytes=10)

    assert read_calls == [11]
    assert raised.value.response_metadata == {
        "response_received": True,
        "response_complete": False,
        "http_error_received": False,
        "response_limit_exceeded": True,
        "http_status": 200,
        "declared_size_bytes": None,
        "observed_body_bytes": 11,
        "response_headers": {},
    }


def test_default_fetch_captures_http_error_status_and_safe_headers(monkeypatch) -> None:
    def reject(url, **_kwargs):
        raise HTTPError(
            url,
            503,
            "Unavailable",
            {"Content-Length": "9", "Content-Type": "text/plain", "Set-Cookie": "secret=value"},
            io.BytesIO(b"unavailable"),
        )

    monkeypatch.setattr("urban_design.m2a03_sources.urllib.request.urlopen", reject)
    with pytest.raises(SourceAcquisitionError, match="HTTP 503") as raised:
        default_fetch("https://example.test/unavailable", max_response_bytes=8)

    metadata = raised.value.response_metadata
    assert metadata["response_received"] is True
    assert metadata["response_complete"] is False
    assert metadata["http_error_received"] is True
    assert metadata["http_status"] == 503
    assert metadata["declared_size_bytes"] == 9
    assert metadata["observed_body_bytes"] == 0
    assert metadata["response_headers"] == {"content-length": "9", "content-type": "text/plain"}


def test_tracked_fetch_receipt_keeps_size_rejection_distinct_from_transport_failure() -> None:
    attempts: list[dict[str, object]] = []

    def oversized(_url: str, **_kwargs: object):
        raise SourceAcquisitionError(
            "source response exceeds configured limit of 10 bytes",
            response_metadata={
                "response_received": True,
                "response_complete": False,
                "response_limit_exceeded": True,
                "http_status": 200,
                "declared_size_bytes": 11,
                "observed_body_bytes": 0,
            },
        )

    tracked = _tracked_fetcher(oversized, attempts)
    with pytest.raises(SourceAcquisitionError, match="10 bytes"):
        tracked("https://example.test/large")

    receipt = _source_request_receipt(
        source_id="osm-overpass",
        required_layers=("regional highway ways",),
        attempts=attempts,
        validation_status="NOT_RUN",
    )
    assert receipt["status"] == "RESPONSE_REJECTED_LIMIT"
    assert receipt["request_sent"] is True
    assert receipt["response_received"] is True
    assert receipt["complete_response"] is False
    assert receipt["validation_status"] == "NOT_RUN"
    assert attempts[0]["request_started_at"]
    assert attempts[0]["response_observed_at"]
    assert "response_completed_at" not in attempts[0]


def test_osm_acquisition_enforces_limit_before_writing_source_artifacts(tmp_path: Path) -> None:
    def fetch(_url: str, **_kwargs: object):
        return b"123456789", 200, {}, NOW

    with pytest.raises(SourceAcquisitionError, match="8 bytes"):
        acquire_osm_overpass(
            package_root=tmp_path,
            query_bounds=_query(),
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            fetcher=fetch,
            max_response_bytes=8,
        )

    assert not list(tmp_path.rglob("*"))


def _query() -> dict[str, object]:
    return query_bounds_crs84([88610.6505405546, 435507.0768308005, 89558.20602756809, 436221.6525033502])


def _feature(feature_id: str) -> dict[str, object]:
    return {
        "type": "Feature",
        "id": feature_id,
        "properties": {"identificatie": feature_id},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[4.42, 51.90], [4.421, 51.90], [4.421, 51.901], [4.42, 51.901], [4.42, 51.90]]],
        },
    }


def _pdok_payload(features: list[dict[str, object]], *, next_url: str | None = None, matched: int | None = None) -> bytes:
    payload: dict[str, object] = {
        "type": "FeatureCollection",
        "timeStamp": NOW,
        "numberReturned": len(features),
        "features": features,
    }
    if matched is not None:
        payload["numberMatched"] = matched
    if next_url is not None:
        payload["links"] = [{"rel": "next", "href": next_url}]
    return json.dumps(payload).encode()


def _epw_zip(
    *,
    row_count: int = 8760,
    chronology_error: bool = False,
    five_columns: bool = False,
    minute: int = 60,
    variable_years: bool = False,
    nonfinite: bool = False,
) -> bytes:
    header = "LOCATION,Rotterdam,ZH,NLD,TMYx,063440,51.95,4.45,1.0,-5.0\n" + "\n".join(["DESIGN CONDITIONS"] + [""] * 6)
    timestamps = [
        (month, day, hour)
        for month in range(1, 13)
        for day in range(1, calendar.monthrange(2024 if row_count == 8784 else 2023, month)[1] + 1)
        for hour in range(1, 25)
    ][:row_count]
    rows: list[str] = []
    for index, (month, day, hour) in enumerate(timestamps):
        if chronology_error and index == 1:
            hour = 1
        year = 2026
        if variable_years:
            year = 1950 + month
        if five_columns:
            rows.append(f"{year},{month},{day},{hour},{minute}")
        else:
            weather = ["0.0"] * 29
            if nonfinite:
                weather[0] = "nan"
            rows.append(",".join([str(year), str(month), str(day), str(hour), str(minute), "A8"] + weather))
    data = (header + "\n" + "\n".join(rows) + "\n").encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("rotterdam.epw", data)
    return output.getvalue()


def test_pdok_pagination_preserves_raw_parent_lineage(tmp_path: Path) -> None:
    first_url = "https://example.test/items"
    second_url = "https://example.test/items?page=2"
    responses = {
        first_url: (_pdok_payload([_feature("a")], next_url=second_url, matched=2), 200, {}, NOW),
        second_url: (_pdok_payload([_feature("b")], matched=2), 200, {}, NOW),
    }

    def fetch(url: str, **_kwargs: object):
        return responses[second_url if "page=2" in url else first_url]

    artifacts, normalized, snapshots, manifest = acquire_pdok_collection(
        package_root=tmp_path,
        source_id="test-pdok",
        collection="pand",
        base_url="https://example.test",
        query_bounds=_query(),
        project_id="rotterdam-m4h-pilot-project",
        created_at=NOW,
        fetcher=fetch,
        package_namespace="m2-a03-analysis-input-test-pdok",
    )

    assert len(artifacts) == len(normalized) == len(snapshots) == 2
    assert manifest["pagination_complete"] is True
    assert all(record["raw_parent_artifact_id"] == raw["id"] for record, raw in zip(normalized, artifacts))
    assert all(record["crs"] == "EPSG:28992" for record in normalized)
    assert {
        feature["id"]
        for record in normalized
        for feature in json.loads((tmp_path / record["uri"]).read_text())["features"]
    } == {"a", "b"}


def test_pdok_duplicate_and_truncation_fail_closed(tmp_path: Path) -> None:
    def duplicate(_url: str, **_kwargs: object):
        return _pdok_payload([_feature("same"), _feature("same")], matched=2), 200, {}, NOW

    with pytest.raises(SourceAcquisitionError, match="duplicate"):
        acquire_pdok_collection(
            package_root=tmp_path / "duplicate",
            source_id="test-pdok",
            collection="pand",
            base_url="https://example.test",
            query_bounds=_query(),
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            fetcher=duplicate,
        )

    def truncated(_url: str, **_kwargs: object):
        return _pdok_payload([_feature("one")]), 200, {}, NOW

    with pytest.raises(SourceAcquisitionError, match="truncated"):
        acquire_pdok_collection(
            package_root=tmp_path / "truncated",
            source_id="test-pdok",
            collection="pand",
            base_url="https://example.test",
            query_bounds=_query(),
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            fetcher=truncated,
            limit=1,
        )


def test_osm_inventory_keeps_raw_shop_tags_and_network_candidates(tmp_path: Path) -> None:
    payload = {
        "osm3s": {"timestamp_osm_base": NOW},
        "elements": [
            {"type": "way", "id": 1, "nodes": [100, 101], "tags": {"highway": "footway"}, "geometry": [{"lat": 51.9, "lon": 4.42}, {"lat": 51.901, "lon": 4.421}]},
            {"type": "node", "id": 2, "lat": 51.9005, "lon": 4.4205, "tags": {"shop": "supermarket", "entrance": "yes"}},
            {"type": "node", "id": 3, "lat": 51.9006, "lon": 4.4206, "tags": {"shop": "convenience"}},
            {"type": "node", "id": 4, "lat": 51.9007, "lon": 4.4207, "tags": {"shop": "grocery"}},
        ],
    }

    def fetch(_url: str, **_kwargs: object):
        return json.dumps(payload).encode(), 200, {}, NOW

    _raw, normalized, snapshots, manifest, grocery, origins = acquire_osm_overpass(
        package_root=tmp_path,
        query_bounds=_query(),
        project_id="rotterdam-m4h-pilot-project",
        created_at=NOW,
        fetcher=fetch,
        package_namespace="m2-a03-analysis-input-test-osm",
    )
    assert manifest["network_way_count"] == 1
    assert grocery["counts_by_shop_tag"] == {"supermarket": 1, "convenience": 1, "grocery": 1}
    assert len(origins["records"]) == 1
    normalized_payload = json.loads((tmp_path / normalized[0]["uri"]).read_text())
    assert len(normalized_payload["features"]) == 4
    assert {feature["id"] for feature in normalized_payload["features"]} == {
        "way/1",
        "node/2",
        "node/3",
        "node/4",
    }
    way = next(feature for feature in normalized_payload["features"] if feature["id"] == "way/1")
    assert way["properties"]["osm_node_ids"] == [100, 101]
    assert snapshots[0]["license"] == "ODbL 1.0"


def test_osm_rejects_way_when_node_refs_do_not_match_geometry(tmp_path: Path) -> None:
    payload = {
        "osm3s": {"timestamp_osm_base": NOW},
        "elements": [
            {
                "type": "way",
                "id": 9,
                "nodes": [100],
                "tags": {"highway": "residential"},
                "geometry": [{"lat": 51.9, "lon": 4.42}, {"lat": 51.901, "lon": 4.421}],
            }
        ],
    }

    def fetch(_url: str, **_kwargs: object):
        return json.dumps(payload).encode(), 200, {}, NOW

    with pytest.raises(SourceAcquisitionError, match="node references"):
        acquire_osm_overpass(
            package_root=tmp_path,
            query_bounds=_query(),
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            fetcher=fetch,
        )
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize(
    "geometry",
    [
        [{"lat": 51.9, "lon": 4.42}, "not-a-coordinate"],
        [{"lat": 51.9, "lon": 4.42}, {"lat": 51.901}],
        [{"lat": 51.9, "lon": 4.42}, {"lat": float("nan"), "lon": 4.421}],
    ],
)
def test_osm_rejects_malformed_way_geometry_without_filtering_points(tmp_path: Path, geometry: list[object]) -> None:
    payload = {
        "osm3s": {"timestamp_osm_base": NOW},
        "elements": [
            {
                "type": "way",
                "id": 10,
                "nodes": [100, 101],
                "tags": {"highway": "residential"},
                "geometry": geometry,
            }
        ],
    }

    def fetch(_url: str, **_kwargs: object):
        return json.dumps(payload).encode(), 200, {}, NOW

    with pytest.raises(SourceAcquisitionError, match="geometry is malformed"):
        acquire_osm_overpass(
            package_root=tmp_path,
            query_bounds=_query(),
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            fetcher=fetch,
        )
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("coordinate_name", ["lat", "lon"])
@pytest.mark.parametrize("invalid_coordinate", [True, float("nan"), float("inf")])
def test_osm_rejects_node_with_non_finite_or_boolean_coordinates(
    tmp_path: Path,
    coordinate_name: str,
    invalid_coordinate: object,
) -> None:
    node = {"type": "node", "id": 11, "lat": 51.9, "lon": 4.42, "tags": {"shop": "grocery"}}
    node[coordinate_name] = invalid_coordinate
    payload = {"osm3s": {"timestamp_osm_base": NOW}, "elements": [node]}

    def fetch(_url: str, **_kwargs: object):
        return json.dumps(payload).encode(), 200, {}, NOW

    with pytest.raises(SourceAcquisitionError, match="OSM node has no valid coordinates"):
        acquire_osm_overpass(
            package_root=tmp_path,
            query_bounds=_query(),
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            fetcher=fetch,
        )
    assert not list(tmp_path.rglob("*"))


def test_epw_requires_a_real_hourly_candidate(tmp_path: Path) -> None:
    archive = _epw_zip()

    def fetch(_url: str, **_kwargs: object):
        return archive, 200, {}, NOW

    _artifacts, snapshots, comparison = acquire_epw_candidates(
        package_root=tmp_path,
        project_id="rotterdam-m4h-pilot-project",
        created_at=NOW,
        query_bounds=_query(),
        fetcher=fetch,
        urls=("https://example.test/Rotterdam.TMYx.zip",),
    )
    assert comparison["status"] == "OBSERVED"
    assert comparison["selected_candidate"] is None
    assert snapshots[0]["raw_artifact_id"].endswith("-epw")

    def bad_fetch(_url: str, **_kwargs: object):
        return b"not a zip", 200, {}, NOW

    with pytest.raises(SourceAcquisitionError, match="archive"):
        acquire_epw_candidates(
            package_root=tmp_path / "bad",
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            query_bounds=_query(),
            fetcher=bad_fetch,
            urls=("https://example.test/bad.zip",),
        )


@pytest.mark.parametrize(
    ("archive", "message"),
    [
        (_epw_zip(five_columns=True), "35 columns"),
        (_epw_zip(row_count=8759), "exactly 8760"),
        (_epw_zip(chronology_error=True), "chronology"),
    ],
)
def test_epw_rejects_structurally_invalid_hourly_candidates(
    tmp_path: Path,
    archive: bytes,
    message: str,
) -> None:
    def fetch(_url: str, **_kwargs: object):
        return archive, 200, {}, NOW

    with pytest.raises(SourceAcquisitionError, match=message):
        acquire_epw_candidates(
            package_root=tmp_path / message.replace(" ", "-"),
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            query_bounds=_query(),
            fetcher=fetch,
            urls=(f"https://example.test/{message}.zip",),
        )


def test_epw_accepts_complete_month_sequence_when_source_year_changes(tmp_path: Path) -> None:
    """TMYx rows may carry the source year selected for each month."""

    archive = _epw_zip(variable_years=True)

    def fetch(_url: str, **_kwargs: object):
        return archive, 200, {}, NOW

    _artifacts, snapshots, comparison = acquire_epw_candidates(
        package_root=tmp_path,
        project_id="rotterdam-m4h-pilot-project",
        created_at=NOW,
        query_bounds=_query(),
        fetcher=fetch,
        urls=("https://example.test/Rotterdam.variable-years.TMYx.zip",),
    )
    assert snapshots[0]["availability"] == "OBSERVED"
    assert comparison["candidates"][0]["chronology_validated"] is True


@pytest.mark.parametrize(
    ("archive", "message"),
    [
        (_epw_zip(minute=0), "chronology"),
        (_epw_zip(nonfinite=True), "nonfinite"),
        (_epw_zip(row_count=8759), "exactly 8760"),
        (_epw_zip(chronology_error=True), "chronology"),
    ],
)
def test_epw_rejects_illegal_timing_missing_and_nonfinite_rows(
    tmp_path: Path,
    archive: bytes,
    message: str,
) -> None:
    def fetch(_url: str, **_kwargs: object):
        return archive, 200, {}, NOW

    with pytest.raises(SourceAcquisitionError, match=message):
        acquire_epw_candidates(
            package_root=tmp_path / message.replace(" ", "-"),
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            query_bounds=_query(),
            fetcher=fetch,
            urls=(f"https://example.test/{message}.zip",),
        )


def test_retained_real_climate_candidate_replays_as_source_invalid(tmp_path: Path) -> None:
    diagnostics = sorted(Path("artifacts/milestone2-analysis-inputs-rotterdam-m4h/diagnostics").glob("epw-r05-*/response.zip"))
    if not diagnostics:
        pytest.skip("R01 diagnostic archive is not present in this checkout")
    archive_path = diagnostics[-1]
    with zipfile.ZipFile(archive_path) as archive:
        epw_name = next(name for name in archive.namelist() if name.casefold().endswith(".epw"))
        epw_bytes = archive.read(epw_name)
    analysis = json.loads(archive_path.parent.joinpath("epw-analysis.json").read_text())
    assert analysis["rows"]["data_row_count"] == 8760
    assert analysis["rows"]["column_counts"] == [35]
    assert analysis["rows"]["minute_values"] == [0]
    assert analysis["rows"]["duplicate_month_day_hour_records"] == []
    assert analysis["rows"]["missing_month_day_hour_records"] == []
    with pytest.raises(SourceAcquisitionError, match="chronology"):
        _epw_metadata(epw_bytes, filename=epw_name)


def _assert_no_weather_url(url: str) -> None:
    lowered = url.lower()
    if lowered.endswith(".zip") or lowered.endswith(".epw") or "climate.onebuilding.org" in lowered:
        raise AssertionError(f"spatial acquisition requested a weather source: {url}")


def _spatial_fetcher(*, fail_source: str | None = None, malformed_pdok: bool = False):
    requested: list[str] = []

    def fetch(url: str, **_kwargs: object):
        _assert_no_weather_url(url)
        requested.append(url)
        if fail_source == "pdok" and "/collections/" in url:
            raise SourceAcquisitionError("simulated PDOK transport failure")
        if fail_source == "osm" and "overpass" in url:
            raise SourceAcquisitionError("simulated Overpass transport failure")
        if "overpass" in url:
            payload = {"osm3s": {"timestamp_osm_base": NOW}, "elements": []}
            return json.dumps(payload).encode(), 200, {}, NOW
        if malformed_pdok:
            return b"{}", 200, {}, NOW
        return _pdok_payload([], matched=0), 200, {}, NOW

    fetch.requested = requested  # type: ignore[attr-defined]
    return fetch


def test_spatial_acquisition_succeeds_when_zip_fetcher_raises(tmp_path: Path) -> None:
    from urban_design.m2a03_sources import SpatialSourceBundle, acquire_spatial_sources

    def fetch(url: str, **_kwargs: object):
        if url.lower().endswith(".zip") or url.lower().endswith(".epw") or "climate.onebuilding.org" in url.lower():
            raise SourceAcquisitionError(f"zip/epw fetcher refused {url}")
        if "overpass" in url:
            payload = {"osm3s": {"timestamp_osm_base": NOW}, "elements": []}
            return json.dumps(payload).encode(), 200, {}, NOW
        return _pdok_payload([], matched=0), 200, {}, NOW

    bundle = acquire_spatial_sources(
        package_root=tmp_path,
        project_id="rotterdam-m4h-pilot-project",
        created_at=NOW,
        observed_bbox=[88610.6505405546, 435507.0768308005, 89558.20602756809, 436221.6525033502],
        fetcher=fetch,
    )
    assert isinstance(bundle, SpatialSourceBundle)
    assert [record["source_id"] for record in bundle.request_records] == [
        "pdok-bag-pand",
        "pdok-bgt-wegdeel",
        "pdok-bgt-waterdeel",
        "osm-overpass",
    ]
    assert all(record["validation_status"] == "PASSED" for record in bundle.request_records)
    assert bundle.request_records[0]["status"] in {"OBSERVED", "EMPTY"}
    serialized = json.dumps(bundle.request_records)
    assert ".zip" not in serialized
    assert "epw" not in {record["source_id"] for record in bundle.request_records}
    assert not list(tmp_path.rglob("*.zip"))
    assert not list(tmp_path.rglob("*.epw"))


def test_spatial_receipts_cover_validation_transport_and_not_attempted(tmp_path: Path) -> None:
    from urban_design.m2a03_sources import acquire_spatial_sources

    transport = _spatial_fetcher(fail_source="pdok")
    with pytest.raises(SourceAcquisitionError) as transported:
        acquire_spatial_sources(
            package_root=tmp_path / "transport",
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            observed_bbox=[88610.6505405546, 435507.0768308005, 89558.20602756809, 436221.6525033502],
            fetcher=transport,
        )
    transport_receipts = {record["source_id"]: record for record in transported.value.request_records}
    assert transport_receipts["pdok-bag-pand"]["status"] == "REQUEST_FAILED"
    assert transport_receipts["pdok-bag-pand"]["request_sent"] is True
    assert transport_receipts["pdok-bag-pand"]["response_received"] is False
    assert transport_receipts["pdok-bgt-wegdeel"]["status"] == "NOT_ATTEMPTED_BLOCKED"
    assert transport_receipts["osm-overpass"]["status"] == "NOT_ATTEMPTED_BLOCKED"
    assert "epw" not in transport_receipts

    validation = _spatial_fetcher(malformed_pdok=True)
    with pytest.raises(SourceAcquisitionError) as validated:
        acquire_spatial_sources(
            package_root=tmp_path / "validation",
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            observed_bbox=[88610.6505405546, 435507.0768308005, 89558.20602756809, 436221.6525033502],
            fetcher=validation,
        )
    validation_receipts = {record["source_id"]: record for record in validated.value.request_records}
    assert validation_receipts["pdok-bag-pand"]["status"] == "VALIDATION_FAILED"
    assert validation_receipts["pdok-bag-pand"]["response_received"] is True
    assert validation_receipts["pdok-bag-pand"]["validation_status"] == "FAILED"
    assert validation_receipts["pdok-bgt-waterdeel"]["status"] == "NOT_ATTEMPTED_BLOCKED"


def test_source_failure_receipt_distinguishes_transport_and_not_attempted(tmp_path: Path) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"

    def fetch(url: str, **_kwargs: object):
        if "overpass-api.de" in url:
            raise SourceAcquisitionError("simulated Overpass transport failure")
        if url.endswith(".zip"):
            return _epw_zip(), 200, {}, NOW
        return _pdok_payload([], matched=0), 200, {}, NOW

    package_dir = build_m2a03_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="r01-source-receipt",
        fetcher=fetch,
    )
    package = load_analysis_input_package(package_dir)
    assert package["status"] == "BLOCKED"
    receipts = {record["source_id"]: record for record in package["source_requests"]}
    assert receipts["pdok-bag-pand"]["request_sent"] is True
    assert receipts["pdok-bag-pand"]["response_received"] is True
    assert receipts["pdok-bag-pand"]["validation_status"] == "PASSED"
    assert receipts["osm-overpass"]["status"] == "REQUEST_FAILED"
    assert receipts["osm-overpass"]["request_sent"] is True
    assert receipts["osm-overpass"]["response_received"] is False
    assert receipts["osm-overpass"]["validation_status"] == "NOT_RUN"
    assert receipts["epw"]["status"] == "NOT_ATTEMPTED_BLOCKED"
    assert receipts["epw"]["request_sent"] is False
    assert receipts["epw"]["response_received"] is False
    assert receipts["epw"]["validation_status"] == "NOT_RUN"
    assert package["snapshots"] == []


def test_spatial_acquisition_records_an_injected_osm_size_rejection(tmp_path: Path, monkeypatch) -> None:
    import urban_design.m2a03_sources as source_module
    from urban_design.m2a03_sources import acquire_spatial_sources

    def fetch(url: str, **kwargs: object):
        if "overpass" in url:
            assert kwargs["max_response_bytes"] == 8
            return b"123456789", 200, {"Content-Length": "9", "Set-Cookie": "secret=value"}, NOW
        return _pdok_payload([], matched=0), 200, {}, NOW

    monkeypatch.setattr(source_module, "default_fetch", fetch)

    with pytest.raises(SourceAcquisitionError) as raised:
        acquire_spatial_sources(
            package_root=tmp_path,
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            observed_bbox=[88610.6505405546, 435507.0768308005, 89558.20602756809, 436221.6525033502],
            fetcher=fetch,
            osm_max_response_bytes=8,
        )

    receipts = {record["source_id"]: record for record in raised.value.request_records}
    osm = receipts["osm-overpass"]
    assert osm["status"] == "RESPONSE_REJECTED_LIMIT"
    assert osm["request_sent"] is True
    assert osm["response_received"] is True
    assert osm["complete_response"] is True
    assert osm["validation_status"] == "NOT_RUN"
    assert osm["attempts"][0]["response_limit_exceeded"] is True
    assert osm["attempts"][0]["observed_body_bytes"] == 9
    assert osm["attempts"][0]["response_headers"] == {"content-length": "9"}
    assert "Set-Cookie" not in osm["attempts"][0]["response_headers"]
    assert not (tmp_path / "sources/raw/osm-overpass-v5.json").exists()
    assert not (tmp_path / "sources/normalized/osm-overpass-v5-epsg28992.geojson").exists()


def test_spatial_acquisition_records_injected_http_error_and_safe_headers(tmp_path: Path) -> None:
    from urban_design.m2a03_sources import acquire_spatial_sources

    def fetch(_url: str, **_kwargs: object):
        return b"unavailable", 503, {
            "Content-Length": "11",
            "Content-Type": "text/plain",
            "Set-Cookie": "secret=value",
        }, NOW

    with pytest.raises(SourceAcquisitionError) as raised:
        acquire_spatial_sources(
            package_root=tmp_path,
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            observed_bbox=[88610.6505405546, 435507.0768308005, 89558.20602756809, 436221.6525033502],
            fetcher=fetch,
        )

    bag = next(item for item in raised.value.request_records if item["source_id"] == "pdok-bag-pand")
    assert bag["status"] == "HTTP_ERROR_RECEIVED"
    assert bag["request_sent"] is True
    assert bag["response_received"] is True
    assert bag["complete_response"] is True
    assert bag["validation_status"] == "NOT_RUN"
    assert bag["attempts"][0]["http_status"] == 503
    assert bag["attempts"][0]["http_error_received"] is True
    assert bag["attempts"][0]["response_headers"] == {
        "content-length": "11",
        "content-type": "text/plain",
    }
    assert not list(tmp_path.rglob("sources/*"))


def test_epw_validation_failure_receipt_records_response_and_failed_validation(tmp_path: Path) -> None:
    invalid_archive = _epw_zip(minute=0)

    def fetch(url: str, **_kwargs: object):
        if "overpass-api.de" in url:
            return json.dumps({"osm3s": {"timestamp_osm_base": NOW}, "elements": []}).encode(), 200, {}, NOW
        if url.endswith(".zip"):
            return invalid_archive, 200, {}, NOW
        return _pdok_payload([], matched=0), 200, {}, NOW

    with pytest.raises(SourceAcquisitionError) as caught:
        acquire_mandatory_sources(
            package_root=tmp_path,
            project_id="rotterdam-m4h-pilot-project",
            created_at=NOW,
            observed_bbox=[88610.6505405546, 435507.0768308005, 89558.20602756809, 436221.6525033502],
            fetcher=fetch,
        )
    receipts = {record["source_id"]: record for record in caught.value.request_records}
    assert caught.value.source_id == "epw"
    assert receipts["epw"]["status"] == "VALIDATION_FAILED"
    assert receipts["epw"]["request_sent"] is True
    assert receipts["epw"]["response_received"] is True
    assert receipts["epw"]["validation_status"] == "FAILED"
    assert receipts["epw"]["attempts"][0]["http_status"] == 200
    assert receipts["epw"]["attempts"][0]["response_sha256"].startswith("sha256:")


def test_v5_package_is_ready_and_replays_without_second_snapshot_set(tmp_path: Path) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"
    archive = _epw_zip()
    osm = {"osm3s": {"timestamp_osm_base": NOW}, "elements": []}

    def fetch(url: str, **_kwargs: object):
        if "overpass-api.de" in url:
            return json.dumps(osm).encode(), 200, {}, NOW
        if url.endswith(".zip"):
            return archive, 200, {}, NOW
        collection = next(name for name in ("pand", "wegdeel", "waterdeel") if f"/collections/{name}/items" in url)
        return _pdok_payload([], matched=0), 200, {}, NOW

    package_dir = build_m2a03_package(database, output, project_id=project_id, study_area_id=area_id, package_revision="r03", fetcher=fetch)
    package = load_analysis_input_package(package_dir)
    assert package["status"] == "READY_FOR_HUMAN_REVIEW"
    assert package["study_area"]["id"].endswith("-v5")
    assert package["weather_candidates"]["selected_candidate"] is None
    assert package["no_accessibility_result"] is True
    assert package["no_climate_result"] is True
    assert package["proposed_policies"]["pedestrian_network"]["status"] == "PROPOSED_PROJECT_DECISION"
    assert [record["source_id"] for record in package["source_requests"]] == [
        "pdok-bag-pand",
        "pdok-bgt-wegdeel",
        "pdok-bgt-waterdeel",
        "osm-overpass",
        "epw",
    ]
    assert package["source_requests"][0]["request_url"].startswith("https://api.pdok.nl/")
    assert package["source_requests"][3]["request_url"].startswith("https://overpass-api.de/")

    def must_not_fetch(*_args: object, **_kwargs: object):
        raise AssertionError("same run must be loaded from its immutable package")

    assert build_m2a03_package(database, output, project_id=project_id, study_area_id=area_id, package_revision="r03", fetcher=must_not_fetch) == package_dir


def _offline_fetcher(archive: bytes):
    osm = {"osm3s": {"timestamp_osm_base": NOW}, "elements": []}

    def fetch(url: str, **_kwargs: object):
        if "overpass-api.de" in url:
            return json.dumps(osm).encode(), 200, {}, NOW
        if url.endswith(".zip"):
            return archive, 200, {}, NOW
        return _pdok_payload([], matched=0), 200, {}, NOW

    return fetch


def _state_counts(database: Path) -> tuple[int, int, int]:
    with ProjectStateStore(database) as store:
        artifacts = sum(
            1
            for row in store.connection.execute(
                "SELECT payload_json FROM state_versions WHERE entity_type = 'Artifact'"
            )
            if json.loads(row["payload_json"]).get("package_id")
        )
        snapshots = sum(
            1
            for row in store.connection.execute(
                "SELECT payload_json FROM state_versions WHERE entity_type = 'DatasetSnapshot'"
            )
            if json.loads(row["payload_json"]).get("raw_artifact_id", "").startswith(("artifact-pdok", "artifact-osm", "artifact-epw"))
        )
        observations = sum(
            1
            for event in store.events()
            if event.action == "SnapshotObservation" and event.target_id.startswith("m2-a03-analysis-input-")
        )
    return artifacts, snapshots, observations


def test_r04_success_resolves_state_artifacts_and_retry_is_exactly_once(tmp_path: Path) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"
    package_dir = build_m2a03_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="r04",
        fetcher=_offline_fetcher(_epw_zip()),
    )
    package = load_analysis_input_package(package_dir)
    first_hashes = {
        path.relative_to(package_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in package_dir.rglob("*")
        if path.is_file()
    }
    assert load_analysis_input_package(package_dir) == package
    second_hashes = {
        path.relative_to(package_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in package_dir.rglob("*")
        if path.is_file()
    }
    assert second_hashes == first_hashes
    counts_before = _state_counts(database)
    with ProjectStateStore(database) as store:
        artifact_rows = [
            row
            for row in store.connection.execute(
                "SELECT payload_json FROM state_versions WHERE entity_type = 'Artifact'"
            ).fetchall()
            if json.loads(row["payload_json"]).get("package_id")
        ]
        snapshot_rows = store.connection.execute(
            "SELECT payload_json FROM state_versions WHERE entity_type = 'DatasetSnapshot'"
        ).fetchall()
    assert counts_before[0] == len(package["artifacts"]) + len(package["normalized_artifacts"])
    assert counts_before[1] == len(package["snapshots"])
    for row in artifact_rows:
        payload = json.loads(row["payload_json"])
        path = Path(payload["uri"])
        assert path.is_file()
        assert payload["package_id"] == package["package_id"]
        assert payload["package_relative_uri"]
        assert payload["package_root_uri"] == str(package_dir.resolve())
    artifact_ids = {json.loads(row["payload_json"])["id"] for row in artifact_rows}
    for row in snapshot_rows:
        payload = json.loads(row["payload_json"])
        if payload["normalized_artifact_id"] is not None:
            assert payload["normalized_artifact_id"] in artifact_ids
    assert load_analysis_input_package(package_dir) == package
    assert build_m2a03_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="r04",
        fetcher=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry fetched source")),
    ) == package_dir
    assert _state_counts(database) == counts_before


def test_r03_reuses_existing_stale_marker_without_rewriting_immutable_event(tmp_path: Path) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"
    prior_id = "m2-a03-analysis-input-study-area-rotterdam-m4h-pilot-project-v4"
    prior_dir = output / "run-study-area-rotterdam-m4h-pilot-project-v4-blocked"
    prior_dir.mkdir(parents=True)
    (prior_dir / "analysis-input-decision-package.json").write_text(
        json.dumps(
            {
                "package_id": prior_id,
                "status": "BLOCKED",
                "study_area": {"geometry_sha256": "sha256:" + "0" * 64},
            }
        ),
        encoding="utf-8",
    )
    stale_event_id = "m2-a03-mark-stale-" + hashlib.sha256(prior_id.encode()).hexdigest()[:24]
    legacy_payload = {"status": "STALE", "legacy_marker": True}
    with ProjectStateStore(database) as store:
        store.append_ledger_event(
            target_id=prior_id,
            target_type="AnalysisInputDecisionPackage",
            project_id=project_id,
            actor="m2-a02-r03",
            action="MarkStale",
            reason="Historical v4 package was superseded during StudyArea activation",
            resulting_refs=(area_id,),
            payload=legacy_payload,
            event_id=stale_event_id,
        )

    package_dir = build_m2a03_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="r03-existing-stale",
        fetcher=_offline_fetcher(_epw_zip()),
    )
    package = load_analysis_input_package(package_dir)
    assert package["status"] == "READY_FOR_HUMAN_REVIEW"
    with ProjectStateStore(database) as store:
        matching = [event for event in store.events() if event.event_id == stale_event_id]
    assert len(matching) == 1
    assert matching[0].payload == legacy_payload


def test_r04_sequential_revisions_scope_immutable_source_ids_and_retry_exactly_once(tmp_path: Path) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"
    fetcher = _offline_fetcher(_epw_zip())
    first_dir = build_m2a03_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="r04-first",
        created_at=NOW,
        fetcher=fetcher,
    )
    second_dir = build_m2a03_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="r04-second",
        created_at=NOW,
        fetcher=fetcher,
    )
    first = load_analysis_input_package(first_dir)
    second = load_analysis_input_package(second_dir)
    first_artifacts = {record["id"] for record in first["artifacts"] + first["normalized_artifacts"]}
    second_artifacts = {record["id"] for record in second["artifacts"] + second["normalized_artifacts"]}
    first_snapshots = {record["id"] for record in first["snapshots"]}
    second_snapshots = {record["id"] for record in second["snapshots"]}
    assert first_artifacts.isdisjoint(second_artifacts)
    assert first_snapshots.isdisjoint(second_snapshots)
    assert all(
        record.get("raw_parent_artifact_id") in first_artifacts
        for record in first["normalized_artifacts"]
    )
    assert all(
        record.get("raw_parent_artifact_id") in second_artifacts
        for record in second["normalized_artifacts"]
    )
    assert all(record["raw_artifact_id"] in first_artifacts for record in first["snapshots"])
    assert all(record["raw_artifact_id"] in second_artifacts for record in second["snapshots"])
    counts_before = _state_counts(database)
    no_fetch = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("revision retry fetched source"))
    assert build_m2a03_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="r04-first",
        fetcher=no_fetch,
    ) == first_dir
    assert build_m2a03_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="r04-second",
        fetcher=no_fetch,
    ) == second_dir
    assert _state_counts(database) == counts_before


def test_r04_same_content_publication_race_reconciles_without_duplicate_state(tmp_path: Path) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"

    def copy_then_report_collision(stage: Path, target: Path) -> None:
        shutil.copytree(stage, target)
        raise FileExistsError("peer won the package target claim")

    package_dir = build_m2a03_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="r04-race-same",
        created_at=NOW,
        fetcher=_offline_fetcher(_epw_zip()),
        package_publisher=copy_then_report_collision,
    )
    package = load_analysis_input_package(package_dir)
    assert package["package_revision"] == "r04-race-same"
    assert _state_counts(database) == (
        len(package["artifacts"]) + len(package["normalized_artifacts"]),
        len(package["snapshots"]),
        1,
    )
    assert not list(output.glob(".run-*.publish-lock"))


def test_r04_different_publication_race_preserves_peer_target_and_rolls_back_state(tmp_path: Path) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"
    peer_target: Path | None = None

    def conflicting_publisher(_stage: Path, target: Path) -> None:
        nonlocal peer_target
        peer_target = target
        target.mkdir()
        (target / "peer-data.txt").write_text("peer publication\n", encoding="utf-8")
        raise FileExistsError("peer target contains a different package")

    with pytest.raises(AnalysisInputPublicationError, match="retry is safe"):
        build_m2a03_package(
            database,
            output,
            project_id=project_id,
            study_area_id=area_id,
            package_revision="r04-race-different",
            fetcher=_offline_fetcher(_epw_zip()),
            package_publisher=conflicting_publisher,
        )
    assert peer_target is not None
    assert (peer_target / "peer-data.txt").read_text(encoding="utf-8") == "peer publication\n"
    assert _state_counts(database)[0:2] == (0, 0)
    assert _state_counts(database)[2] == 0


@pytest.mark.parametrize("failure", ["final-validation", "publication"])
def test_r04_precommit_failures_leave_no_successful_state(tmp_path: Path, failure: str) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"
    if failure == "final-validation":
        def validator(root: Path):
            if root.name.startswith("run-"):
                raise ArtifactIntegrityError("injected final package validation failure")
            return load_analysis_input_package(root)
        kwargs = {"package_validator": validator}
    else:
        def publisher(_stage: Path, _target: Path):
            raise OSError("injected publication failure")
        kwargs = {"package_publisher": publisher}
    with pytest.raises(AnalysisInputPublicationError, match="retry is safe"):
        build_m2a03_package(
            database,
            output,
            project_id=project_id,
            study_area_id=area_id,
            package_revision=f"r04-{failure}",
            fetcher=_offline_fetcher(_epw_zip()),
            **kwargs,
        )
    assert _state_counts(database)[0:2] == (0, 0)
    assert _state_counts(database)[2] == 0
    if failure == "publication":
        assert not list(output.glob("run-*/analysis-input-decision-package.json"))
    else:
        # A target published before a later validation failure is retained so
        # a concurrent or offline retry can reconcile it safely; SQLite state
        # remains rolled back.
        package_dir = next(output.glob("run-*/"))
        assert load_analysis_input_package(package_dir)["status"] == "READY_FOR_HUMAN_REVIEW"


def test_r04_sqlite_interruption_preserves_complete_package_for_offline_retry(tmp_path: Path) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"
    with pytest.raises(AnalysisInputPublicationError, match="retry is safe"):
        build_m2a03_package(
            database,
            output,
            project_id=project_id,
            study_area_id=area_id,
            package_revision="r04-sqlite-interruption",
            fetcher=_offline_fetcher(_epw_zip()),
            commit_hook=lambda: (_ for _ in ()).throw(OSError("injected SQLite interruption")),
        )
    package_dir = next(output.glob("run-*/"))
    package = load_analysis_input_package(package_dir)
    assert package["status"] == "READY_FOR_HUMAN_REVIEW"
    assert _state_counts(database)[0:2] == (0, 0)
    recovered = build_m2a03_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="r04-sqlite-interruption",
        fetcher=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry fetched source")),
    )
    assert recovered == package_dir
    assert _state_counts(database)[0:2] == (
        len(package["artifacts"]) + len(package["normalized_artifacts"]),
        len(package["snapshots"]),
    )
