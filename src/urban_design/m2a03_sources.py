"""Bounded, provenance-first source acquisition for M2-A03.

This module contains only deterministic transport, response validation, and
normalisation helpers.  It does not select an origin denominator, destination
taxonomy, network policy, weather file, or climate method.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import calendar
import io
import json
import hashlib
import math
from pathlib import Path
import re
import urllib.parse
import urllib.error
import urllib.request
import zipfile
from typing import Any, Callable, Mapping, Sequence

import pyproj
from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import transform as shapely_transform



def sha256_bytes(value: bytes) -> str:
    """Hash source bytes without importing the package builder."""

    return "sha256:" + hashlib.sha256(value).hexdigest()


def _scoped_id(local_id: str, package_namespace: str | None) -> str:
    """Give persisted package records a stable identity within one package.

    Source-native feature identifiers are deliberately passed through the
    normalisation payload unchanged.  Only the application-owned Artifact and
    DatasetSnapshot identifiers receive the package scope.
    """

    if package_namespace is None:
        return local_id
    scope = hashlib.sha256(package_namespace.encode("utf-8")).hexdigest()[:16]
    return f"{local_id}-{scope}"


class SourceAcquisitionError(RuntimeError):
    """Raised when a mandatory source cannot be frozen completely.

    ``request_records`` is deliberately carried on the exception so a failed
    acquisition can publish a truthful receipt.  A source request that was
    sent, received, and then rejected by validation must remain distinct from
    a request that was never sent or that failed before a response arrived.
    """

    def __init__(
        self,
        message: str,
        *,
        request_records: Sequence[Mapping[str, Any]] = (),
        source_id: str | None = None,
        response_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.request_records = tuple(dict(record) for record in request_records)
        self.source_id = source_id
        self.response_metadata = dict(response_metadata or {})


FetchCallable = Callable[..., tuple[bytes, int, Mapping[str, str], str]]


@dataclass(frozen=True)
class CapturedResponse:
    body: bytes
    status: int
    headers: Mapping[str, str]
    retrieved_at: str


_SAFE_RESPONSE_HEADERS = frozenset(
    {"content-length", "content-type", "date", "etag", "last-modified", "retry-after"}
)


def _safe_response_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    """Keep only response metadata needed for an auditable transport receipt."""

    return {
        str(key).lower(): str(value)
        for key, value in headers.items()
        if str(key).lower() in _SAFE_RESPONSE_HEADERS
    }


def _response_metadata(
    *,
    status: int | None,
    headers: Mapping[str, Any],
    observed_body_bytes: int,
    response_complete: bool,
    http_error_received: bool = False,
    response_limit_exceeded: bool = False,
) -> dict[str, Any]:
    try:
        declared_size = int(headers.get("Content-Length")) if headers.get("Content-Length") is not None else None
    except (TypeError, ValueError):
        declared_size = None
    return {
        "response_received": True,
        "response_complete": response_complete,
        "http_error_received": http_error_received,
        "response_limit_exceeded": response_limit_exceeded,
        "http_status": status,
        "declared_size_bytes": declared_size,
        "observed_body_bytes": observed_body_bytes,
        "response_headers": _safe_response_headers(headers),
    }


@dataclass(frozen=True)
class SpatialSourceBundle:
    """PDOK and OSM records only. This bundle never carries a weather source."""

    artifacts: tuple[dict[str, Any], ...]
    normalized_artifacts: tuple[dict[str, Any], ...]
    snapshots: tuple[dict[str, Any], ...]
    request_records: tuple[dict[str, Any], ...]
    network_manifest: dict[str, Any]
    grocery_inventory: dict[str, Any]
    origin_inventory: dict[str, Any]


@dataclass(frozen=True)
class SourceBundle:
    """The immutable records needed by the historical combined package builder."""

    artifacts: tuple[dict[str, Any], ...]
    normalized_artifacts: tuple[dict[str, Any], ...]
    snapshots: tuple[dict[str, Any], ...]
    request_records: tuple[dict[str, Any], ...]
    network_manifest: dict[str, Any]
    grocery_inventory: dict[str, Any]
    origin_inventory: dict[str, Any]
    weather_candidates: dict[str, Any]


SPATIAL_SOURCE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "source_id": "pdok-bag-pand",
        "required_layers": ["pand"],
        "source_url": "https://api.pdok.nl/kadaster/bag/ogc/v2",
        "kind": "pdok",
        "collection": "pand",
    },
    {
        "source_id": "pdok-bgt-wegdeel",
        "required_layers": ["wegdeel"],
        "source_url": "https://api.pdok.nl/lv/bgt/ogc/v1",
        "kind": "pdok",
        "collection": "wegdeel",
    },
    {
        "source_id": "pdok-bgt-waterdeel",
        "required_layers": ["waterdeel"],
        "source_url": "https://api.pdok.nl/lv/bgt/ogc/v1",
        "kind": "pdok",
        "collection": "waterdeel",
    },
    {
        "source_id": "osm-overpass",
        "required_layers": ["pedestrian source ways/nodes", "grocery POIs"],
        "source_url": "https://overpass-api.de/api/interpreter",
        "kind": "osm",
    },
)
WEATHER_SOURCE_SPEC: dict[str, Any] = {
    "source_id": "epw",
    "required_layers": ["Rotterdam-region candidates"],
    "source_url": "",
    "kind": "epw",
}
SPATIAL_OSM_TIMEOUT_SECONDS = 150.0


def _is_weather_url(url: str) -> bool:
    lowered = url.lower()
    return lowered.endswith(".zip") or lowered.endswith(".epw") or "climate.onebuilding.org" in lowered


def _refuse_weather_url(url: str) -> None:
    if _is_weather_url(url):
        raise SourceAcquisitionError(f"spatial acquisition refused a weather URL: {url}")


def _request_accounting(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Count logical dispatches. Pagination pages after the first are separate."""

    pdok_collections = 0
    pdok_pagination = 0
    osm_requests = 0
    weather_requests = 0
    for record in records:
        source_id = str(record.get("source_id") or "")
        attempts = [attempt for attempt in (record.get("attempts") or []) if attempt.get("request_sent")]
        if source_id.startswith("pdok-"):
            if attempts:
                pdok_collections += 1
                pdok_pagination += max(0, len(attempts) - 1)
        elif source_id == "osm-overpass":
            osm_requests += len(attempts)
        elif source_id == "epw":
            weather_requests += len(attempts)
        else:
            weather_requests += sum(
                1 for attempt in attempts if _is_weather_url(str(attempt.get("request_url") or ""))
            )
    return {
        "pdok_collection_requests": pdok_collections,
        "pdok_pagination_requests": pdok_pagination,
        "osm_overpass_requests": osm_requests,
        "weather_zip_or_api_requests": weather_requests,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def query_bounds_crs84(
    projected_bounds: Sequence[float],
    *,
    input_crs: str = "EPSG:28992",
    buffer_m: float = 1200.0,
) -> dict[str, Any]:
    """Expand a projected bbox and transform it to CRS84 with explicit axes."""

    if len(projected_bounds) != 4 or buffer_m < 0:
        raise SourceAcquisitionError("projected bounds and buffer must be finite bbox values")
    try:
        xmin, ymin, xmax, ymax = (float(value) for value in projected_bounds)
    except (TypeError, ValueError) as exc:
        raise SourceAcquisitionError("projected bounds and buffer must be finite bbox values") from exc
    if not xmin < xmax or not ymin < ymax:
        raise SourceAcquisitionError("projected bounds must have positive width and height")
    projected = (xmin - buffer_m, ymin - buffer_m, xmax + buffer_m, ymax + buffer_m)
    transformer = Transformer.from_crs(input_crs, "OGC:CRS84", always_xy=True)
    corners = [
        transformer.transform(projected[0], projected[1]),
        transformer.transform(projected[0], projected[3]),
        transformer.transform(projected[2], projected[1]),
        transformer.transform(projected[2], projected[3]),
    ]
    crs84 = (
        min(point[0] for point in corners),
        min(point[1] for point in corners),
        max(point[0] for point in corners),
        max(point[1] for point in corners),
    )
    return {
        "projected_crs": input_crs,
        "projected_units": "m",
        "projected_bounds": list(projected),
        "crs84": "OGC:CRS84",
        "crs84_axis_order": "longitude, latitude",
        "crs84_bounds": list(crs84),
        "axis_order": "always_xy=True; x=longitude/easting, y=latitude/northing",
        "pyproj_version": pyproj.__version__,
        "transformer_definition": transformer.definition,
        "transformer_description": transformer.description,
        "buffer_m": float(buffer_m),
    }


def default_fetch(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 90.0,
    max_response_bytes: int | None = None,
) -> tuple[bytes, int, Mapping[str, str], str]:
    if max_response_bytes is not None and (
        isinstance(max_response_bytes, bool)
        or not isinstance(max_response_bytes, int)
        or max_response_bytes <= 0
    ):
        raise SourceAcquisitionError("max_response_bytes must be a positive integer")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"User-Agent": "urban-design-m2-a03/1.0", **dict(headers or {})},
    )
    started = utc_now()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            response_headers = {str(k): str(v) for k, v in response.headers.items()}
            if status < 200 or status >= 300:
                raise SourceAcquisitionError(
                    f"source request returned HTTP {status}: {url}",
                    response_metadata=_response_metadata(
                        status=status,
                        headers=response.headers,
                        observed_body_bytes=0,
                        response_complete=False,
                        http_error_received=True,
                    ),
                )
            if max_response_bytes is None:
                body = response.read()
            else:
                content_length = response.headers.get("Content-Length")
                try:
                    declared_size = int(content_length) if content_length is not None else None
                except (TypeError, ValueError):
                    declared_size = None
                if declared_size is not None and declared_size > max_response_bytes:
                    raise SourceAcquisitionError(
                        f"source response exceeds configured limit of {max_response_bytes} bytes",
                        response_metadata=_response_metadata(
                            status=status,
                            headers=response.headers,
                            observed_body_bytes=0,
                            response_complete=False,
                            response_limit_exceeded=True,
                        ),
                    )
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise SourceAcquisitionError(
                        f"source response exceeds configured limit of {max_response_bytes} bytes",
                        response_metadata=_response_metadata(
                            status=status,
                            headers=response.headers,
                            observed_body_bytes=len(body),
                            response_complete=False,
                            response_limit_exceeded=True,
                        ),
                    )
    except urllib.error.HTTPError as exc:
        response_headers = exc.headers or {}
        raise SourceAcquisitionError(
            f"source request returned HTTP {exc.code}: {url}",
            response_metadata=_response_metadata(
                status=int(exc.code),
                headers=response_headers,
                observed_body_bytes=0,
                response_complete=False,
                http_error_received=True,
            ),
        ) from exc
    except SourceAcquisitionError:
        raise
    except Exception as exc:
        raise SourceAcquisitionError(f"source request failed: {url}: {exc}") from exc
    return body, status, response_headers, started


def _capture(fetcher: FetchCallable | None, url: str, **kwargs: Any) -> CapturedResponse:
    max_response_bytes = kwargs.pop("max_response_bytes", None)
    if max_response_bytes is not None and (
        isinstance(max_response_bytes, bool)
        or not isinstance(max_response_bytes, int)
        or max_response_bytes <= 0
    ):
        raise SourceAcquisitionError("max_response_bytes must be a positive integer")
    if fetcher is None:
        body, status, headers, retrieved_at = default_fetch(
            url,
            max_response_bytes=max_response_bytes,
            **kwargs,
        )
    else:
        fetch_kwargs = dict(kwargs)
        if max_response_bytes is not None:
            fetch_kwargs["max_response_bytes"] = max_response_bytes
        body, status, headers, retrieved_at = fetcher(url, **fetch_kwargs)
    if not isinstance(body, (bytes, bytearray)):
        raise SourceAcquisitionError(f"source response is not bytes: {url}")
    if max_response_bytes is not None and len(body) > max_response_bytes:
        raise SourceAcquisitionError(
            f"source response exceeds configured limit of {max_response_bytes} bytes",
            response_metadata=_response_metadata(
                status=int(status),
                headers=headers,
                observed_body_bytes=len(body),
                response_complete=True,
                response_limit_exceeded=True,
            ),
        )
    if status < 200 or status >= 300:
        raise SourceAcquisitionError(
            f"source request returned HTTP {status}: {url}",
            response_metadata=_response_metadata(
                status=int(status),
                headers=headers,
                observed_body_bytes=len(body),
                response_complete=True,
                http_error_received=True,
            ),
        )
    return CapturedResponse(bytes(body), int(status), dict(headers), retrieved_at)


def _json(body: bytes, url: str) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceAcquisitionError(f"malformed JSON response: {url}") from exc
    if not isinstance(value, dict):
        raise SourceAcquisitionError(f"JSON response must be an object: {url}")
    return value


def _feature_id(feature: Mapping[str, Any], *, source_id: str) -> str:
    value = feature.get("id")
    properties = feature.get("properties")
    if value is None and isinstance(properties, Mapping):
        value = properties.get("id") or properties.get("identificatie") or properties.get("@id")
    if value is None:
        raise SourceAcquisitionError(f"feature without stable ID in {source_id}")
    return str(value)


def _next_url(payload: Mapping[str, Any], current_url: str) -> str | None:
    links = payload.get("links", [])
    if not isinstance(links, list):
        raise SourceAcquisitionError("source links must be a list")
    for link in links:
        if isinstance(link, Mapping) and str(link.get("rel", "")).casefold() == "next":
            href = link.get("href")
            if not isinstance(href, str) or not href.strip():
                raise SourceAcquisitionError("source next link is malformed")
            return urllib.parse.urljoin(current_url, href)
    return None


def _validate_page(
    payload: Mapping[str, Any],
    *,
    source_id: str,
    limit: int,
    seen_ids: set[str],
) -> list[Mapping[str, Any]]:
    features = payload.get("features")
    if not isinstance(features, list):
        raise SourceAcquisitionError(f"{source_id} response has no feature list")
    page_ids: list[str] = []
    for feature in features:
        if not isinstance(feature, Mapping):
            raise SourceAcquisitionError(f"{source_id} contains a malformed feature")
        feature_id = _feature_id(feature, source_id=source_id)
        if feature_id in seen_ids or feature_id in page_ids:
            raise SourceAcquisitionError(f"duplicate feature ID in {source_id}: {feature_id}")
        page_ids.append(feature_id)
    number_returned = payload.get("numberReturned")
    number_matched = payload.get("numberMatched")
    try:
        if number_returned is not None and int(number_returned) != len(features):
            raise SourceAcquisitionError(f"{source_id} response count is inconsistent")
        if number_matched is not None and int(number_matched) < len(features):
            raise SourceAcquisitionError(f"{source_id} response matched count is inconsistent")
    except (TypeError, ValueError) as exc:
        raise SourceAcquisitionError(f"{source_id} response counts are malformed") from exc
    if len(features) > limit:
        raise SourceAcquisitionError(f"{source_id} response exceeds requested limit")
    seen_ids.update(page_ids)
    return features


def _geojson_feature(feature_id: str, geometry: Any, properties: Mapping[str, Any]) -> dict[str, Any]:
    if geometry is None:
        raise SourceAcquisitionError(f"feature {feature_id} has no geometry")
    try:
        geom = shape(geometry)
    except Exception as exc:
        raise SourceAcquisitionError(f"feature {feature_id} has invalid geometry") from exc
    if geom.is_empty or not geom.is_valid:
        raise SourceAcquisitionError(f"feature {feature_id} has empty or invalid geometry")
    return {"type": "Feature", "id": feature_id, "properties": dict(properties), "geometry": mapping(geom)}


def normalize_geojson_features(
    features: Sequence[Mapping[str, Any]],
    *,
    source_crs: str = "OGC:CRS84",
    target_crs: str = "EPSG:28992",
) -> dict[str, Any]:
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    normalized: list[dict[str, Any]] = []
    for feature in features:
        feature_id = _feature_id(feature, source_id="normalized-source")
        geometry = feature.get("geometry")
        try:
            geom = shape(geometry)
            projected = shapely_transform(transformer.transform, geom)
        except Exception as exc:
            raise SourceAcquisitionError(f"cannot normalize feature {feature_id}") from exc
        if projected.is_empty or not projected.is_valid:
            raise SourceAcquisitionError(f"normalized feature {feature_id} is invalid")
        normalized.append(
            {
                "type": "Feature",
                "id": feature_id,
                "properties": dict(feature.get("properties") or {}),
                "geometry": mapping(projected),
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "m2-a03-normalized-epsg28992",
        "crs": {"type": "name", "properties": {"name": target_crs}},
        "features": normalized,
    }


def _artifact(
    *,
    artifact_id: str,
    uri: str,
    data: bytes,
    artifact_type: str,
    mime: str,
    producer: str,
    project_id: str,
    created_at: str,
    crs: str | None = None,
    parents: Sequence[str] = (),
    raw_parent: str | None = None,
) -> dict[str, Any]:
    record = {
        "id": artifact_id,
        "type": artifact_type,
        "uri": uri,
        "sha256": sha256_bytes(data),
        "mime": mime,
        "crs": crs,
        "producer": producer,
        "created_at": created_at,
        "project_id": project_id,
        "size_bytes": len(data),
        "parent_artifact_ids": list(parents),
    }
    if raw_parent is not None:
        record["raw_parent_artifact_id"] = raw_parent
    return record


def _write(root: Path, relative: str, data: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def acquire_pdok_collection(
    *,
    package_root: Path,
    source_id: str,
    collection: str,
    base_url: str,
    query_bounds: Mapping[str, Any],
    project_id: str,
    created_at: str,
    fetcher: FetchCallable | None = None,
    limit: int = 1000,
    package_namespace: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Fetch all OGC API pages and emit one raw/normalized pair per page."""

    xmin, ymin, xmax, ymax = query_bounds["crs84_bounds"]
    query_params = {
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "bbox-crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        "limit": str(limit),
        "f": "json",
    }
    url = base_url.rstrip("/") + "/collections/" + urllib.parse.quote(collection, safe="") + "/items?" + urllib.parse.urlencode(query_params)
    pages = 0
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    artifacts: list[dict[str, Any]] = []
    normalized_artifacts: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    total_features = 0
    page_urls: list[str] = []
    while url:
        if url in seen_urls:
            raise SourceAcquisitionError(f"next-link loop detected for {source_id}")
        seen_urls.add(url)
        page_urls.append(url)
        pages += 1
        if pages > 100:
            raise SourceAcquisitionError(f"pagination limit exceeded for {source_id}")
        response = _capture(fetcher, url)
        payload = _json(response.body, url)
        features = _validate_page(payload, source_id=source_id, limit=limit, seen_ids=seen_ids)
        number_matched = payload.get("numberMatched")
        next_url = _next_url(payload, url)
        try:
            matched_count = None if number_matched is None else int(number_matched)
        except (TypeError, ValueError) as exc:
            raise SourceAcquisitionError(f"{source_id} pagination count is malformed") from exc
        if next_url is None and matched_count is not None and matched_count != len(seen_ids):
            raise SourceAcquisitionError(f"{source_id} pagination is incomplete")
        if next_url is None and len(features) == limit and number_matched is None:
            raise SourceAcquisitionError(f"{source_id} may be truncated at limit={limit}")
        page_id = f"{source_id}-p{pages:03d}"
        raw_uri = f"sources/raw/{page_id}.json"
        raw_id = _scoped_id(f"artifact-{page_id}-raw", package_namespace)
        _write(package_root, raw_uri, response.body)
        raw_artifact = _artifact(
            artifact_id=raw_id,
            uri=raw_uri,
            data=response.body,
            artifact_type="raw_source_response",
            mime="application/json",
            producer="PDOK OGC API",
            project_id=project_id,
            created_at=created_at,
        )
        artifacts.append(raw_artifact)
        normalized_payload = normalize_geojson_features(features)
        normalized_bytes = (json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        normalized_uri = f"sources/normalized/{page_id}-epsg28992.geojson"
        normalized_id = _scoped_id(f"artifact-{page_id}-normalized", package_namespace)
        _write(package_root, normalized_uri, normalized_bytes)
        normalized_artifacts.append(
            _artifact(
                artifact_id=normalized_id,
                uri=normalized_uri,
                data=normalized_bytes,
                artifact_type="normalized_source",
                mime="application/geo+json",
                producer="pyproj/Shapely M2-A03 normalizer",
                project_id=project_id,
                created_at=created_at,
                crs="EPSG:28992",
                parents=(raw_id,),
                raw_parent=raw_id,
            )
        )
        snapshots.append(
            {
                "id": _scoped_id(f"snapshot-{page_id}", package_namespace),
                "project_id": project_id,
                "source_url": url,
                "query": json.dumps(query_params, sort_keys=True),
                "retrieved_at": response.retrieved_at,
                "publisher": "PDOK / Kadaster",
                "license": "PDOK/Kadaster open-data terms; verify current terms before publication",
                "version": str(payload.get("timeStamp") or response.headers.get("Last-Modified") or ""),
                "attribution": "PDOK / Kadaster",
                "sha256": raw_artifact["sha256"],
                "raw_artifact_id": raw_id,
                "normalized_artifact_id": normalized_id,
                "limitations": ["Dataset observation only; it does not establish ownership, zoning, access, safety, or buildability."],
                "availability": "OBSERVED" if features else "EMPTY",
                "parameters": {"collection": collection, "feature_count": len(features), "page": pages, "limit": limit, "query_bounds": dict(query_bounds)},
            }
        )
        if not snapshots[-1]["version"]:
            raise SourceAcquisitionError(f"{source_id} response has no verifiable version or timestamp")
        total_features += len(features)
        url = next_url
    return artifacts, normalized_artifacts, snapshots, {
        "source_id": source_id,
        "collection": collection,
        "source_url": base_url,
        "request_url": page_urls[0] if page_urls else None,
        "page_urls": page_urls,
        "status": "OBSERVED" if total_features else "EMPTY",
        "pages": pages,
        "feature_count": total_features,
        "pagination_complete": True,
        "duplicate_ids": False,
        "query_bounds": dict(query_bounds),
    }


def acquire_osm_overpass(
    *,
    package_root: Path,
    query_bounds: Mapping[str, Any],
    project_id: str,
    created_at: str,
    fetcher: FetchCallable | None = None,
    endpoint: str = "https://overpass-api.de/api/interpreter",
    package_namespace: str | None = None,
    request_timeout: float | None = None,
    max_response_bytes: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Capture one bounded Overpass response and preserve raw tag classes."""

    xmin, ymin, xmax, ymax = query_bounds["crs84_bounds"]
    query = (
        "[out:json][timeout:120];("
        f'way["highway"]({ymin},{xmin},{ymax},{xmax});'
        f'node["shop"~"^(supermarket|convenience|grocery)$"]({ymin},{xmin},{ymax},{xmax});'
        f'node["entrance"]({ymin},{xmin},{ymax},{xmax});'
        f'node["public_transport"]({ymin},{xmin},{ymax},{xmax});'
        ");out body geom;"
    )
    url = endpoint + "?" + urllib.parse.urlencode({"data": query})
    capture_kwargs = {"timeout": request_timeout} if request_timeout is not None else {}
    if max_response_bytes is not None:
        capture_kwargs["max_response_bytes"] = max_response_bytes
    response = _capture(fetcher, url, **capture_kwargs)
    payload = _json(response.body, url)
    if payload.get("remark"):
        raise SourceAcquisitionError(f"Overpass returned an incomplete response: {payload['remark']}")
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise SourceAcquisitionError("Overpass response has no elements list")
    seen: set[str] = set()
    network: list[dict[str, Any]] = []
    grocery_features: list[dict[str, Any]] = []
    origin_features: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, Mapping) or element.get("type") not in {"node", "way"} or not isinstance(element.get("id"), int):
            raise SourceAcquisitionError("Overpass contains a malformed element")
        key = f"{element['type']}/{element['id']}"
        if key in seen:
            raise SourceAcquisitionError(f"duplicate OSM element ID: {key}")
        seen.add(key)
        tags = dict(element.get("tags") or {})
        if element["type"] == "node":
            if not _is_finite_number(element.get("lat")) or not _is_finite_number(element.get("lon")):
                raise SourceAcquisitionError(f"OSM node has no valid coordinates: {key}")
            geometry = {"type": "Point", "coordinates": [element["lon"], element["lat"]]}
        else:
            node_refs = element.get("nodes")
            geometry_points = element.get("geometry")
            if not isinstance(geometry_points, list) or len(geometry_points) < 2:
                raise SourceAcquisitionError(f"OSM way has no complete geometry: {key}")
            if any(
                not isinstance(point, Mapping)
                or not _is_finite_number(point.get("lon"))
                or not _is_finite_number(point.get("lat"))
                for point in geometry_points
            ):
                raise SourceAcquisitionError(f"OSM way geometry is malformed: {key}")
            geometry = {"type": "LineString", "coordinates": [[point["lon"], point["lat"]] for point in geometry_points]}
            if (
                not isinstance(node_refs, list)
                or len(node_refs) != len(geometry["coordinates"])
                or any(not isinstance(node_id, int) or isinstance(node_id, bool) for node_id in node_refs)
            ):
                raise SourceAcquisitionError(f"OSM way node references do not match its geometry: {key}")
        properties = {"osm_type": element["type"], "osm_id": element["id"], "tags": tags}
        if element["type"] == "way":
            properties["osm_node_ids"] = list(node_refs)
        feature = {"type": "Feature", "id": key, "properties": properties, "geometry": geometry}
        if element["type"] == "way" and tags.get("highway"):
            network.append(feature)
        if tags.get("shop") in {"supermarket", "convenience", "grocery"}:
            grocery_features.append(feature)
        if element["type"] == "node" and (tags.get("entrance") or tags.get("public_transport")):
            origin_features.append(feature)
    raw_id = _scoped_id("artifact-osm-overpass-v5-raw", package_namespace)
    raw_uri = "sources/raw/osm-overpass-v5.json"
    _write(package_root, raw_uri, response.body)
    raw_artifact = _artifact(artifact_id=raw_id, uri=raw_uri, data=response.body, artifact_type="raw_source_response", mime="application/json", producer="OpenStreetMap Overpass API", project_id=project_id, created_at=created_at)
    # A node can satisfy more than one query clause. Keep raw classifications
    # in inventories while normalising one feature per OSM element.
    combined_features = list({feature["id"]: feature for feature in (network + grocery_features + origin_features)}.values())
    normalized_payload = normalize_geojson_features(combined_features)
    normalized_bytes = (json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    normalized_id = _scoped_id("artifact-osm-overpass-v5-normalized", package_namespace)
    normalized_uri = "sources/normalized/osm-overpass-v5-epsg28992.geojson"
    _write(package_root, normalized_uri, normalized_bytes)
    normalized_artifact = _artifact(artifact_id=normalized_id, uri=normalized_uri, data=normalized_bytes, artifact_type="normalized_source", mime="application/geo+json", producer="pyproj/Shapely M2-A03 normalizer", project_id=project_id, created_at=created_at, crs="EPSG:28992", parents=(raw_id,), raw_parent=raw_id)
    snapshot = {
        "id": _scoped_id("snapshot-osm-overpass-v5", package_namespace),
        "project_id": project_id,
        "source_url": endpoint,
        "query": query,
        "retrieved_at": response.retrieved_at,
        "publisher": "OpenStreetMap contributors via Overpass API",
        "license": "ODbL 1.0",
        "version": str((payload.get("osm3s") or {}).get("timestamp_osm_base") or ""),
        "attribution": "© OpenStreetMap contributors",
        "sha256": raw_artifact["sha256"],
        "raw_artifact_id": raw_id,
        "normalized_artifact_id": normalized_id,
        "limitations": ["OSM tags are dataset observations; they do not prove access, ownership, safety, suitability, or destination selection."],
        "availability": "OBSERVED" if elements else "EMPTY",
        "parameters": {"query_bounds": dict(query_bounds), "element_count": len(elements), "network_way_count": len(network), "grocery_count": len(grocery_features), "origin_candidate_count": len(origin_features)},
    }
    if not snapshot["version"]:
        raise SourceAcquisitionError("Overpass response has no verifiable osm3s timestamp")
    highway_counts: Counter[str] = Counter()
    foot_counts: Counter[str] = Counter()
    access_counts: Counter[str] = Counter()
    for feature in network:
        tags = feature["properties"]["tags"]
        highway_counts[str(tags.get("highway"))] += 1
        if "foot" in tags:
            foot_counts[str(tags.get("foot"))] += 1
        if "access" in tags:
            access_counts[str(tags.get("access"))] += 1
    manifest = {
        "source_id": "osm-overpass",
        "source_url": endpoint,
        "request_url": url,
        "query": query,
        "status": snapshot["availability"],
        "element_count": len(elements),
        "network_way_count": len(network),
        "network_candidate_ids": [feature["id"] for feature in network],
        "network_tag_distribution": {
            "highway": dict(sorted(highway_counts.items())),
            "foot": dict(sorted(foot_counts.items())),
            "access": dict(sorted(access_counts.items())),
        },
        "conditional_access_limitation": (
            "Conditional, destination-only, permissive, unknown, or otherwise ambiguous "
            "access tags are not treated as public access and remain a visible limitation."
        ),
        "pagination_complete": True,
        "duplicate_ids": False,
        "query_bounds": dict(query_bounds),
        "policy_status": "PROPOSED_PROJECT_DECISION",
    }
    grocery = {"status": snapshot["availability"], "counts_by_shop_tag": {tag: sum(1 for feature in grocery_features if feature["properties"]["tags"].get("shop") == tag) for tag in ("supermarket", "convenience", "grocery")}, "records": [{"feature_id": feature["id"], "shop": feature["properties"]["tags"].get("shop"), "tags": feature["properties"]["tags"]} for feature in grocery_features], "policy_status": "PROPOSED_PROJECT_DECISION"}
    origins = {"status": snapshot["availability"], "records": [{"feature_id": feature["id"], "tags": feature["properties"]["tags"]} for feature in origin_features], "policy_status": "PROPOSED_PROJECT_DECISION", "selection": None, "limitations": ["Candidate inventory only; no origin denominator or access rule is selected."]}
    return [raw_artifact], [normalized_artifact], [snapshot], manifest, grocery, origins


EPW_CANDIDATE_URLS = (
    "https://climate.onebuilding.org/WMO_Region_6_Europe/NLD_Netherlands/ZH_Zuid-Holland/NLD_ZH_Rotterdam.The.Hague.AP.063440_TMYx.zip",
    "https://climate.onebuilding.org/WMO_Region_6_Europe/NLD_Netherlands/ZH_Zuid-Holland/NLD_ZH_Rotterdam.The.Hague.AP.063440_TMYx.2011-2025.zip",
    "https://climate.onebuilding.org/WMO_Region_6_Europe/NLD_Netherlands/ZH_Zuid-Holland/NLD_ZH_Rotterdam.The.Hague.AP.063440_TMYx.2009-2023.zip",
)


def _epw_metadata(epw_bytes: bytes, *, filename: str) -> dict[str, Any]:
    try:
        lines = epw_bytes.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise SourceAcquisitionError(f"EPW is not UTF-8: {filename}") from exc
    if not lines or not lines[0].startswith("LOCATION,"):
        raise SourceAcquisitionError(f"EPW LOCATION header missing: {filename}")
    fields = lines[0].split(",")
    if len(fields) < 10:
        raise SourceAcquisitionError(f"EPW LOCATION header is incomplete: {filename}")
    try:
        latitude, longitude, timezone_value, elevation = (float(fields[6]), float(fields[7]), float(fields[8]), float(fields[9]))
    except (TypeError, ValueError) as exc:
        raise SourceAcquisitionError(f"EPW LOCATION coordinates are invalid: {filename}") from exc
    data_lines = lines[8:]
    data_rows = len(data_lines)
    if data_rows not in {8760, 8784}:
        raise SourceAcquisitionError(
            f"EPW must contain exactly 8760 or 8784 hourly rows, got {data_rows}: {filename}"
        )
    leap_year = data_rows == 8784
    reference_year = 2024 if leap_year else 2023
    expected_times = [
        (month, day, hour)
        for month in range(1, 13)
        for day in range(1, calendar.monthrange(reference_year, month)[1] + 1)
        for hour in range(1, 25)
    ]
    if len(expected_times) != data_rows:  # pragma: no cover - defensive
        raise SourceAcquisitionError(f"EPW chronology model is inconsistent: {filename}")
    for row_number, (line, expected) in enumerate(zip(data_lines, expected_times), start=9):
        row_fields = line.split(",")
        if len(row_fields) != 35:
            raise SourceAcquisitionError(
                f"EPW row {row_number} must contain 35 columns, got {len(row_fields)}: {filename}"
            )
        try:
            year = int(row_fields[0])
            month = int(row_fields[1])
            day = int(row_fields[2])
            hour = int(row_fields[3])
            minute = int(row_fields[4])
        except (TypeError, ValueError) as exc:
            raise SourceAcquisitionError(f"EPW row {row_number} has a nonnumeric timestamp: {filename}") from exc
        if (month, day, hour) != expected or minute != 60:
            raise SourceAcquisitionError(
                f"EPW row {row_number} has invalid hourly chronology: {filename}"
            )
        if not (1 <= month <= 12 and 1 <= day <= 31 and 1 <= hour <= 24 and year >= 1900):
            raise SourceAcquisitionError(f"EPW row {row_number} has invalid timestamp values: {filename}")
        try:
            numeric_fields = [float(value) for value in row_fields[6:]]
        except (TypeError, ValueError) as exc:
            raise SourceAcquisitionError(f"EPW row {row_number} has nonnumeric weather fields: {filename}") from exc
        if any(not math.isfinite(value) for value in numeric_fields):
            raise SourceAcquisitionError(f"EPW row {row_number} has nonfinite weather fields: {filename}")
    match = re.search(r"TMYx(?:\.(\d{4}-\d{4}))?", filename)
    year_type = match.group(1) if match and match.group(1) else "full-period TMYx"
    return {"filename": filename, "city": fields[1], "state": fields[2], "country": fields[3], "data_source": fields[4], "wmo": fields[5], "latitude": latitude, "longitude": longitude, "timezone": timezone_value, "elevation_m": elevation, "hourly_rows": data_rows, "epw_columns": 35, "chronology_validated": True, "year_type": year_type, "comment_lines": lines[7:8]}


def acquire_epw_candidates(
    *,
    package_root: Path,
    project_id: str,
    created_at: str,
    query_bounds: Mapping[str, Any],
    fetcher: FetchCallable | None = None,
    urls: Sequence[str] = EPW_CANDIDATE_URLS,
    package_namespace: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    transformer = Transformer.from_crs("OGC:CRS84", "EPSG:28992", always_xy=True)
    center = ((query_bounds["projected_bounds"][0] + query_bounds["projected_bounds"][2]) / 2, (query_bounds["projected_bounds"][1] + query_bounds["projected_bounds"][3]) / 2)
    for index, url in enumerate(urls, start=1):
        response = _capture(fetcher, url)
        zip_id = _scoped_id(f"artifact-epw-candidate-{index:02d}-zip", package_namespace)
        zip_uri = f"sources/raw/weather-candidate-{index:02d}.zip"
        _write(package_root, zip_uri, response.body)
        artifacts.append(_artifact(artifact_id=zip_id, uri=zip_uri, data=response.body, artifact_type="raw_weather_archive", mime="application/zip", producer="Climate.OneBuilding.Org", project_id=project_id, created_at=created_at))
        try:
            archive = zipfile.ZipFile(io.BytesIO(response.body))
            epw_names = [name for name in archive.namelist() if name.casefold().endswith(".epw")]
            if len(epw_names) != 1:
                raise SourceAcquisitionError(f"EPW archive must contain exactly one EPW: {url}")
            epw_name = epw_names[0]
            epw_bytes = archive.read(epw_name)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise SourceAcquisitionError(f"invalid EPW archive: {url}") from exc
        metadata = _epw_metadata(epw_bytes, filename=epw_name)
        station_x, station_y = transformer.transform(metadata["longitude"], metadata["latitude"])
        metadata["distance_to_query_center_m"] = ((station_x - center[0]) ** 2 + (station_y - center[1]) ** 2) ** 0.5
        epw_id = _scoped_id(f"artifact-epw-candidate-{index:02d}-epw", package_namespace)
        epw_uri = f"sources/raw/weather-candidate-{index:02d}.epw"
        _write(package_root, epw_uri, epw_bytes)
        artifacts.append(_artifact(artifact_id=epw_id, uri=epw_uri, data=epw_bytes, artifact_type="epw_weather_file", mime="text/plain", producer="Climate.OneBuilding.Org", project_id=project_id, created_at=created_at, parents=(zip_id,), raw_parent=zip_id))
        snapshots.append({"id": _scoped_id(f"snapshot-epw-candidate-{index:02d}", package_namespace), "project_id": project_id, "source_url": url, "query": "download ZIP and verify one EPW member", "retrieved_at": response.retrieved_at, "publisher": "Climate.OneBuilding.Org", "license": "Climate.OneBuilding.Org repository; source dataset attribution retained in EPW header", "version": metadata["year_type"], "attribution": "Climate.OneBuilding.Org; source data attribution is retained in EPW metadata", "sha256": sha256_bytes(epw_bytes), "raw_artifact_id": epw_id, "normalized_artifact_id": None, "limitations": ["Weather candidate observation only; no candidate is selected and no climate result is computed."], "availability": "OBSERVED", "parameters": {"archive_artifact_id": zip_id, "archive_sha256": artifacts[-2]["sha256"], "station": metadata}})
        candidates.append({"candidate_id": f"epw-candidate-{index:02d}", "source_url": url, "archive_artifact_id": zip_id, "epw_artifact_id": epw_id, **metadata, "status": "OBSERVED"})
    if not candidates:
        raise SourceAcquisitionError("no trustworthy EPW candidate was retrieved")
    return artifacts, snapshots, {"status": "OBSERVED", "selected_candidate": None, "policy_status": "PROPOSED_PROJECT_DECISION", "candidates": candidates, "comparison_basis": ["station coordinates", "distance to query center in EPSG:28992", "TMYx year type", "file/hash/row validation"], "source_metadata_url": "https://climate.onebuilding.org/sources/default.html"}


def _source_request_receipt(
    *,
    source_id: str,
    required_layers: Sequence[str],
    attempts: Sequence[Mapping[str, Any]],
    validation_status: str,
    result: Mapping[str, Any] | None = None,
    error: str | None = None,
    source_url: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a typed receipt for one source adapter invocation."""

    attempt_list = [dict(attempt) for attempt in attempts]
    request_sent = bool(attempt_list)
    response_received = any(bool(attempt.get("response_received")) for attempt in attempt_list)
    complete_response = bool(attempt_list) and all(
        bool(attempt.get("response_complete", attempt.get("response_received")))
        for attempt in attempt_list
    )
    limit_rejected = any(bool(attempt.get("response_limit_exceeded")) for attempt in attempt_list)
    http_error_received = any(bool(attempt.get("http_error_received")) for attempt in attempt_list)
    if limit_rejected:
        status = "RESPONSE_REJECTED_LIMIT"
    elif http_error_received:
        status = "HTTP_ERROR_RECEIVED"
    elif validation_status == "FAILED":
        status = "VALIDATION_FAILED"
    elif validation_status == "PASSED":
        status = str((result or {}).get("status") or "OBSERVED")
    elif not request_sent:
        status = "NOT_ATTEMPTED_BLOCKED"
    elif response_received:
        status = "RESPONSE_RECEIVED"
    else:
        status = "REQUEST_FAILED"
    record: dict[str, Any] = {
        "source_id": source_id,
        "required_layers": list(required_layers),
        "status": status,
        "request_sent": request_sent,
        "response_received": response_received,
        "complete_response": complete_response,
        "validation_status": validation_status,
        "attempts": attempt_list,
    }
    if source_url is not None:
        record["source_url"] = source_url
    if result:
        record.update(dict(result))
    if extra:
        record.update(dict(extra))
    if error:
        record["error"] = error
    return record


def _tracked_fetcher(
    base_fetcher: FetchCallable,
    attempt_log: list[dict[str, Any]],
) -> FetchCallable:
    def tracked_fetch(url: str, **kwargs: Any) -> tuple[bytes, int, Mapping[str, str], str]:
        request_started_at = utc_now()
        attempt: dict[str, Any] = {
            "request_url": url,
            "request_sent": True,
            "response_received": False,
            "validation_status": "NOT_RUN",
            "request_started_at": request_started_at,
        }
        attempt_log.append(attempt)
        try:
            body, status, headers, retrieved_at = base_fetcher(url, **kwargs)
        except Exception as exc:
            if isinstance(exc, SourceAcquisitionError):
                attempt.update(exc.response_metadata)
            if attempt.get("response_received"):
                observed_at = utc_now()
                attempt.setdefault("response_observed_at", observed_at)
                if attempt.get("response_complete") is True:
                    attempt.setdefault("response_completed_at", observed_at)
            attempt.update(
                {
                    "status": "RESPONSE_REJECTED_LIMIT"
                    if attempt.get("response_limit_exceeded")
                    else "HTTP_ERROR_RECEIVED"
                    if attempt.get("http_error_received")
                    else "REQUEST_FAILED",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            raise
        attempt["response_received"] = True
        attempt["response_complete"] = True
        try:
            status_value = int(status)
        except (TypeError, ValueError):
            status_value = None
        attempt["http_status"] = status_value
        attempt["response_completed_at"] = utc_now()
        attempt["response_headers"] = _safe_response_headers(headers)
        attempt["retrieved_at"] = retrieved_at
        if isinstance(body, (bytes, bytearray)):
            attempt["response_size_bytes"] = len(body)
            attempt["response_sha256"] = sha256_bytes(bytes(body))
        limit = kwargs.get("max_response_bytes")
        if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 and isinstance(body, (bytes, bytearray)) and len(body) > limit:
            metadata = _response_metadata(
                status=status_value,
                headers=headers,
                observed_body_bytes=len(body),
                response_complete=True,
                response_limit_exceeded=True,
            )
            attempt.update(metadata)
            attempt["status"] = "RESPONSE_REJECTED_LIMIT"
            raise SourceAcquisitionError(
                f"source response exceeds configured limit of {limit} bytes",
                response_metadata=metadata,
            )
        if status_value is None or status_value < 200 or status_value >= 300:
            metadata = _response_metadata(
                status=status_value,
                headers=headers,
                observed_body_bytes=len(body) if isinstance(body, (bytes, bytearray)) else 0,
                response_complete=True,
                http_error_received=True,
            )
            attempt.update(metadata)
            attempt["status"] = "HTTP_ERROR_RECEIVED"
            raise SourceAcquisitionError(
                f"source request returned HTTP {status_value}: {url}",
                response_metadata=metadata,
            )
        attempt["status"] = "RESPONSE_RECEIVED"
        return body, status, headers, retrieved_at

    return tracked_fetch


def _invoke_source(
    *,
    specs: Sequence[Mapping[str, Any]],
    spec_index: int,
    operation: Callable[[], Any],
    attempt_log: list[dict[str, Any]],
    requests: list[dict[str, Any]],
    result: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Any:
    spec = specs[spec_index]
    start = len(attempt_log)
    try:
        value = operation()
    except Exception as exc:
        attempts = attempt_log[start:]
        last = attempts[-1] if attempts else {}
        if bool(last.get("response_limit_exceeded")):
            validation_status = "NOT_RUN"
        elif bool(last.get("response_received")) and 200 <= int(last.get("http_status") or 0) < 300:
            validation_status = "FAILED"
        else:
            validation_status = "NOT_RUN"
        failed = _source_request_receipt(
            source_id=str(spec["source_id"]),
            required_layers=spec["required_layers"],
            attempts=attempts,
            validation_status=validation_status,
            error=str(exc),
            source_url=spec.get("source_url"),
            extra=extra,
        )
        remaining = [
            _source_request_receipt(
                source_id=str(remaining_spec["source_id"]),
                required_layers=remaining_spec["required_layers"],
                attempts=(),
                validation_status="NOT_RUN",
                source_url=remaining_spec.get("source_url"),
            )
            for remaining_spec in specs[spec_index + 1 :]
        ]
        raise SourceAcquisitionError(
            str(exc),
            request_records=[*requests, failed, *remaining],
            source_id=str(spec["source_id"]),
        ) from exc
    attempts = attempt_log[start:]
    requests.append(
        _source_request_receipt(
            source_id=str(spec["source_id"]),
            required_layers=spec["required_layers"],
            attempts=attempts,
            validation_status="PASSED",
            result=result,
            source_url=spec.get("source_url"),
            extra=extra,
        )
    )
    return value


def _spatial_fetcher_guard(fetcher: FetchCallable) -> FetchCallable:
    def guarded(url: str, **kwargs: Any) -> tuple[bytes, int, Mapping[str, str], str]:
        _refuse_weather_url(url)
        return fetcher(url, **kwargs)

    return guarded


def acquire_spatial_sources(
    *,
    package_root: Path,
    project_id: str,
    created_at: str,
    observed_bbox: Sequence[float],
    fetcher: FetchCallable | None = None,
    package_namespace: str | None = None,
    osm_max_response_bytes: int | None = None,
) -> SpatialSourceBundle:
    """Acquire PDOK BAG/BGT and bounded OSM. Never requests or parses weather."""

    query_bounds = query_bounds_crs84(observed_bbox)
    all_artifacts: list[dict[str, Any]] = []
    all_normalized: list[dict[str, Any]] = []
    all_snapshots: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    source_manifests: list[dict[str, Any]] = []
    attempt_log: list[dict[str, Any]] = []
    tracked_fetch = _tracked_fetcher(_spatial_fetcher_guard(fetcher or default_fetch), attempt_log)
    specs = SPATIAL_SOURCE_SPECS
    network_manifest: dict[str, Any] = {}
    grocery_inventory: dict[str, Any] = {}
    origin_inventory: dict[str, Any] = {}

    for spec_index, spec in enumerate(specs):
        if spec["kind"] == "pdok":
            collection = str(spec["collection"])
            base = str(spec["source_url"])
            source_id = str(spec["source_id"])
            artifacts, normalized, snapshots, manifest = _invoke_source(
                specs=specs,
                spec_index=spec_index,
                operation=lambda source_id=source_id, collection=collection, base=base: acquire_pdok_collection(
                    package_root=package_root,
                    source_id=source_id,
                    collection=collection,
                    base_url=base,
                    query_bounds=query_bounds,
                    project_id=project_id,
                    created_at=created_at,
                    fetcher=tracked_fetch,
                    package_namespace=package_namespace,
                ),
                attempt_log=attempt_log,
                requests=requests,
                extra={"collection": collection, "query_bounds": query_bounds},
            )
            requests[-1].update(
                {
                    "status": manifest.get("status", requests[-1]["status"]),
                    "source_url": manifest.get("source_url"),
                    "request_url": manifest.get("request_url"),
                    "page_urls": manifest.get("page_urls", []),
                    "pagination_complete": manifest.get("pagination_complete"),
                    "feature_count": manifest.get("feature_count"),
                }
            )
            all_artifacts.extend(artifacts)
            all_normalized.extend(normalized)
            all_snapshots.extend(snapshots)
            source_manifests.append(manifest)
            continue
        osm_artifacts, osm_normalized, osm_snapshots, network_manifest, grocery_inventory, origin_inventory = _invoke_source(
            specs=specs,
            spec_index=spec_index,
            operation=lambda: acquire_osm_overpass(
                package_root=package_root,
                query_bounds=query_bounds,
                project_id=project_id,
                created_at=created_at,
                fetcher=tracked_fetch,
                package_namespace=package_namespace,
                request_timeout=SPATIAL_OSM_TIMEOUT_SECONDS,
                max_response_bytes=osm_max_response_bytes,
            ),
            attempt_log=attempt_log,
            requests=requests,
            extra={"query_bounds": query_bounds},
        )
        requests[-1].update(
            {
                "status": network_manifest.get("status", requests[-1]["status"]),
                "source_url": network_manifest.get("source_url"),
                "request_url": network_manifest.get("request_url"),
                "query": network_manifest.get("query"),
                "pagination_complete": True,
                "element_count": network_manifest.get("element_count"),
            }
        )
        all_artifacts.extend(osm_artifacts)
        all_normalized.extend(osm_normalized)
        all_snapshots.extend(osm_snapshots)
        source_manifests.append(network_manifest)

    published_manifest = {
        **network_manifest,
        "sources": source_manifests,
        "query_bounds": query_bounds,
        "policy_status": "PROPOSED_PROJECT_DECISION",
        "request_accounting": _request_accounting(requests),
        "weather_requested": False,
    }
    return SpatialSourceBundle(
        tuple(all_artifacts),
        tuple(all_normalized),
        tuple(all_snapshots),
        tuple(requests),
        published_manifest,
        grocery_inventory,
        origin_inventory,
    )


def _weather_not_attempted_receipt() -> dict[str, Any]:
    return _source_request_receipt(
        source_id="epw",
        required_layers=WEATHER_SOURCE_SPEC["required_layers"],
        attempts=(),
        validation_status="NOT_RUN",
        source_url=EPW_CANDIDATE_URLS[0],
    )


def acquire_mandatory_sources(
    *,
    package_root: Path,
    project_id: str,
    created_at: str,
    observed_bbox: Sequence[float],
    fetcher: FetchCallable | None = None,
    package_namespace: str | None = None,
) -> SourceBundle:
    """Historical combined PDOK, OSM, and EPW path. Kept for replay only."""

    try:
        spatial = acquire_spatial_sources(
            package_root=package_root,
            project_id=project_id,
            created_at=created_at,
            observed_bbox=observed_bbox,
            fetcher=fetcher,
            package_namespace=package_namespace,
        )
    except SourceAcquisitionError as exc:
        records = list(exc.request_records)
        if not any(record.get("source_id") == "epw" for record in records):
            records.append(_weather_not_attempted_receipt())
        raise SourceAcquisitionError(str(exc), request_records=records, source_id=exc.source_id) from exc

    query_bounds = spatial.network_manifest.get("query_bounds") or query_bounds_crs84(observed_bbox)
    requests = list(spatial.request_records)
    attempt_log: list[dict[str, Any]] = []
    tracked_fetch = _tracked_fetcher(fetcher or default_fetch, attempt_log)
    weather_spec = {
        **WEATHER_SOURCE_SPEC,
        "source_url": EPW_CANDIDATE_URLS[0],
    }
    weather_artifacts, weather_snapshots, weather_candidates = _invoke_source(
        specs=(weather_spec,),
        spec_index=0,
        operation=lambda: acquire_epw_candidates(
            package_root=package_root,
            project_id=project_id,
            created_at=created_at,
            query_bounds=query_bounds,
            fetcher=tracked_fetch,
            package_namespace=package_namespace,
        ),
        attempt_log=attempt_log,
        requests=requests,
        extra={"query": "Rotterdam-region EPW candidate retrieval and validation", "query_bounds": query_bounds},
    )
    requests[-1].update(
        {
            "status": weather_candidates.get("status", requests[-1]["status"]),
            "source_url": weather_candidates.get("source_metadata_url"),
            "candidate_urls": [candidate.get("source_url") for candidate in weather_candidates["candidates"]],
        }
    )
    weather_manifest = {
        "source_id": "epw",
        "source_url": weather_candidates.get("source_metadata_url"),
        "candidate_urls": [candidate.get("source_url") for candidate in weather_candidates["candidates"]],
        "status": weather_candidates["status"],
        "candidate_count": len(weather_candidates["candidates"]),
    }
    source_manifests = list(spatial.network_manifest.get("sources") or [])
    source_manifests.append(weather_manifest)
    network_manifest = {
        **spatial.network_manifest,
        "sources": source_manifests,
        "query_bounds": query_bounds,
        "policy_status": "PROPOSED_PROJECT_DECISION",
        "request_accounting": _request_accounting(requests),
    }
    return SourceBundle(
        tuple([*spatial.artifacts, *weather_artifacts]),
        spatial.normalized_artifacts,
        tuple([*spatial.snapshots, *weather_snapshots]),
        tuple(requests),
        network_manifest,
        spatial.grocery_inventory,
        spatial.origin_inventory,
        weather_candidates,
    )


__all__ = [
    "EPW_CANDIDATE_URLS",
    "SourceAcquisitionError",
    "SourceBundle",
    "SpatialSourceBundle",
    "acquire_epw_candidates",
    "acquire_mandatory_sources",
    "acquire_osm_overpass",
    "acquire_pdok_collection",
    "acquire_spatial_sources",
    "normalize_geojson_features",
    "query_bounds_crs84",
]
