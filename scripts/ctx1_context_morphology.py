#!/usr/bin/env python3
"""Read-only M4H context morphology extraction and map production.

All spatial measurements are deterministic Shapely calculations in EPSG:28992.
Live acquisition is restricted to the Overpass API and the optional 3DBAG WFS;
raw responses and their request log are retained under /private/tmp/ctx1-raw/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    box,
    mapping,
    shape,
)
from shapely.ops import linemerge, nearest_points, polygonize, unary_union

from urban_design.morphology.context_reading import (
    analyze_block_distribution,
    angle_difference_deg,
    classify_dominant_typology,
    compute_fsi_and_floors,
    compute_gsi,
    compute_intersection_density,
    compute_orientation_peaks,
    compute_site_principal_axis,
    compute_typical_street_spacing,
    compute_wing_depths,
    cut_blocks_from_network,
    find_continuation_street_candidates,
    line_azimuth_deg,
    segment_azimuth_deg,
)


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
THREEDBAG_URL = "https://data.3dbag.nl/api/BAG3D/wfs"
ALLOWED_HOSTS = {"overpass-api.de", "data.3dbag.nl"}
DEFAULT_RAW_DIR = Path("/private/tmp/ctx1-raw")
DEFAULT_SITE_FACTS = Path("artifacts/s6-brief/facts/site-facts.json")
DEFAULT_OUTPUT_DIR = Path("artifacts/ctx1-context-morphology")
MAX_REQUESTS = 40
MIN_REQUEST_INTERVAL_S = 3.0
RETRY_WAIT_S = 60.0
MIN_SPLIT_SPAN_M = 250.0
TYPOLOGY_VERSION = "CTX1-typology-heuristic-v1"


class RequestLimitError(RuntimeError):
    """Raised before making an external request beyond the declared cap."""


class AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only when the destination stays on an allowed host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlparse(newurl).hostname
        if host not in ALLOWED_HOSTS:
            raise urllib.error.HTTPError(
                newurl,
                code,
                f"redirect to non-allowlisted host blocked: {host}",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


class RequestManager:
    """Audited HTTP client with exact-query cache, rate limit, and request cap."""

    def __init__(self, raw_dir: Path, max_requests: int = MAX_REQUESTS, refresh: bool = False):
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.raw_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_requests = max_requests
        self.refresh = refresh
        self.request_log_path = self.raw_dir / "request-log.jsonl"
        self.request_count = self._count_prior_network_requests()
        self.request_count_at_start = self.request_count
        if self.request_count > self.max_requests:
            raise RequestLimitError(
                f"任務累計已記錄 {self.request_count} 次外部請求，超過上限 {self.max_requests} 次"
            )
        self.last_request_started: float | None = None
        self.records: list[dict[str, Any]] = []
        self.opener = urllib.request.build_opener(AllowlistedRedirectHandler())

    def _count_prior_network_requests(self) -> int:
        if not self.request_log_path.exists():
            return 0
        count = 0
        with self.request_log_path.open("r", encoding="utf-8") as log:
            for line in log:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("request_made"):
                    count += 1
        return count

    @staticmethod
    def query_key(method: str, url: str, query: str) -> str:
        canonical = f"{method.upper()}\n{url}\n{query}".encode("utf-8")
        return sha256_bytes(canonical)

    def _cache_paths(self, key: str) -> tuple[Path, Path]:
        return self.cache_dir / f"{key}.meta.json", self.cache_dir / f"{key}.body"

    def cached(self, method: str, url: str, query: str) -> tuple[int, bytes, dict[str, Any]] | None:
        if self.refresh:
            return None
        key = self.query_key(method, url, query)
        meta_path, _ = self._cache_paths(key)
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body_path = self.raw_dir / meta["raw_response_file"]
            if meta.get("query_key") != key or not body_path.is_file():
                return None
            digest = sha256_file(body_path)
            if digest != meta.get("response_sha256"):
                return None
            record = {
                "request_made": False,
                "request_time_utc": utc_now(),
                "url": url,
                "query": query,
                "query_sha256": sha256_bytes(query.encode("utf-8")),
                "status_code": int(meta.get("status_code", 200)),
                "response_sha256": digest,
                "raw_response_file": str(body_path),
                "cache_status": "REUSED_HASH_VERIFIED",
                "original_retrieved_at_utc": meta.get("retrieved_at_utc"),
            }
            self.records.append(record)
            return int(meta.get("status_code", 200)), body_path.read_bytes(), record
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save_cache(self, method: str, url: str, query: str, record: dict[str, Any]) -> None:
        if record.get("status_code") != 200 or not record.get("response_sha256"):
            return
        key = self.query_key(method, url, query)
        meta_path, _ = self._cache_paths(key)
        body_path = Path(str(record["raw_response_file"]))
        try:
            relative = body_path.relative_to(self.raw_dir)
        except ValueError:
            return
        meta = {
            "query_key": key,
            "url": url,
            "query": query,
            "status_code": 200,
            "retrieved_at_utc": record.get("request_time_utc"),
            "response_sha256": record["response_sha256"],
            "raw_response_file": str(relative),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _wait_for_rate_limit(self) -> None:
        if self.last_request_started is None:
            return
        elapsed = time.monotonic() - self.last_request_started
        if elapsed < MIN_REQUEST_INTERVAL_S:
            time.sleep(MIN_REQUEST_INTERVAL_S - elapsed)

    def request(
        self,
        method: str,
        url: str,
        query: str,
        *,
        post_body: bytes | None = None,
        content_type: str | None = None,
        extension: str = "bin",
        timeout_s: int = 240,
        use_cache: bool = True,
    ) -> tuple[int | None, bytes | None, dict[str, Any]]:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"external host is outside the CTX1 allowlist: {url}")
        if use_cache:
            cached = self.cached(method, url, query)
            if cached is not None:
                return cached
        if self.request_count >= self.max_requests:
            raise RequestLimitError(f"已達每次執行 {self.max_requests} 次外部請求上限")

        self._wait_for_rate_limit()
        self.last_request_started = time.monotonic()
        self.request_count += 1
        request_time = utc_now()
        headers = {"User-Agent": "CTX1-M4H-context-reading/1.0 (read-only research extraction)"}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=post_body, headers=headers, method=method.upper())
        status: int | None = None
        response_body: bytes | None = None
        error: str | None = None
        try:
            with self.opener.open(request, timeout=timeout_s) as response:
                status = int(response.status)
                final_host = urllib.parse.urlparse(response.geturl()).hostname
                if final_host not in ALLOWED_HOSTS:
                    raise ValueError(f"response host is outside the CTX1 allowlist: {final_host}")
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            try:
                response_body = exc.read()
            except OSError:
                response_body = None
            error = str(exc)
        except Exception as exc:  # Network/transport errors are recorded, never hidden.
            error = f"{type(exc).__name__}: {exc}"

        digest = sha256_bytes(response_body) if response_body is not None else None
        filename = None
        if response_body is not None:
            key = self.query_key(method, url, query)
            filename = f"{key[:16]}-request-{self.request_count:02d}-http-{status or 'unknown'}.{extension}"
            path = self.raw_dir / filename
            path.write_bytes(response_body)
        record = {
            "request_made": True,
            "request_time_utc": request_time,
            "method": method.upper(),
            "url": url,
            "query": query,
            "query_sha256": sha256_bytes(query.encode("utf-8")),
            "status_code": status,
            "response_sha256": digest,
            "raw_response_file": str(self.raw_dir / filename) if filename else None,
            "error": error,
            "request_number": self.request_count,
        }
        self.records.append(record)
        with self.request_log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return status, response_body, record


def _area_tags(tags: dict[str, Any]) -> bool:
    return bool(
        tags.get("building") not in (None, "no")
        or "landuse" in tags
        or tags.get("leisure") == "park"
        or tags.get("natural") == "water"
        or tags.get("waterway") == "riverbank"
        or tags.get("man_made") in {"pier", "quay"}
    )


def _project_lonlat_coords(coords: Sequence[Any], transformer: Transformer) -> list[tuple[float, float]]:
    projected: list[tuple[float, float]] = []
    for coord in coords:
        if isinstance(coord, dict):
            lon, lat = float(coord["lon"]), float(coord["lat"])
        else:
            lon, lat = float(coord[0]), float(coord[1])
        x, y = transformer.transform(lon, lat)
        projected.append((float(x), float(y)))
    return projected


def _relation_geometry(element: dict[str, Any], transformer: Transformer) -> Any | None:
    outer_lines: list[LineString] = []
    inner_lines: list[LineString] = []
    line_parts: list[LineString] = []
    for member in element.get("members", []):
        coords = member.get("geometry")
        if not coords or member.get("type") != "way":
            continue
        try:
            points = _project_lonlat_coords(coords, transformer)
            if len(points) < 2:
                continue
            line = LineString(points)
            role = member.get("role", "")
            if role == "inner":
                inner_lines.append(line)
            elif role == "outer":
                outer_lines.append(line)
            else:
                line_parts.append(line)
        except (KeyError, TypeError, ValueError):
            continue
    tags = element.get("tags", {})
    if _area_tags(tags) and outer_lines:
        outer_polys = list(polygonize(unary_union(outer_lines)))
        if not outer_polys:
            return None
        outer = unary_union(outer_polys)
        if inner_lines:
            inner = unary_union(list(polygonize(unary_union(inner_lines))))
            outer = outer.difference(inner)
        return outer
    all_lines = outer_lines + inner_lines + line_parts
    if not all_lines:
        return None
    merged = linemerge(unary_union(all_lines))
    return merged


def _element_geometry(element: dict[str, Any], transformer: Transformer) -> Any | None:
    if element.get("type") == "relation":
        return _relation_geometry(element, transformer)
    if element.get("type") == "node":
        try:
            x, y = transformer.transform(float(element["lon"]), float(element["lat"]))
            return Point(float(x), float(y))
        except (KeyError, TypeError, ValueError):
            return None
    coords = element.get("geometry")
    if not coords:
        return None
    try:
        points = _project_lonlat_coords(coords, transformer)
        if len(points) < 2:
            return None
        tags = element.get("tags", {})
        closed = len(points) >= 4 and points[0] == points[-1]
        if closed and _area_tags(tags):
            polygon = Polygon(points)
            return make_valid(polygon) if not polygon.is_valid else polygon
        return LineString(points)
    except (KeyError, TypeError, ValueError):
        return None


def _line_parts(geom: Any) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom] if geom.length > 0 else []
    if isinstance(geom, MultiLineString):
        return [part for part in geom.geoms if part.length > 0]
    if isinstance(geom, GeometryCollection):
        return [line for item in geom.geoms for line in _line_parts(item)]
    if isinstance(geom, Polygon):
        return _line_parts(geom.boundary)
    if isinstance(geom, MultiPolygon):
        return [line for part in geom.geoms for line in _line_parts(part.boundary)]
    return []


def _polygon_parts(geom: Any) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom] if geom.area > 0 else []
    if isinstance(geom, MultiPolygon):
        return [part for part in geom.geoms if part.area > 0]
    if isinstance(geom, GeometryCollection):
        return [polygon for item in geom.geoms for polygon in _polygon_parts(item)]
    return []


def _feature_layers(tags: dict[str, Any], geom: Any) -> list[str]:
    layers: list[str] = []
    has_polygons = bool(_polygon_parts(geom))
    has_lines = bool(_line_parts(geom))
    if tags.get("building") not in (None, "no") and has_polygons:
        layers.append("building")
    if tags.get("highway") and has_lines:
        layers.append("highway")
    if tags.get("railway") and has_lines:
        layers.append("railway")
    if tags.get("landuse") and has_polygons:
        layers.append("landuse")
    if tags.get("leisure") == "park" and has_polygons:
        layers.append("park")
    if (tags.get("natural") == "water" or tags.get("waterway") == "riverbank" or tags.get("landuse") in {"reservoir", "basin"}) and has_polygons:
        layers.append("water")
    if tags.get("waterway"):
        layers.append("waterway")
    if tags.get("man_made") in {"pier", "quay"}:
        layers.append("harbor_structure")
    return layers


def parse_overpass_payload(payload: dict[str, Any], transformer: Transformer | None = None) -> list[dict[str, Any]]:
    """Convert an Overpass JSON payload to EPSG:28992 typed OSM features."""
    if transformer is None:
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
    features: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for element in payload.get("elements", []):
        tags = dict(element.get("tags", {}))
        if not tags:
            continue
        geom = _element_geometry(element, transformer)
        if geom is None or geom.is_empty:
            continue
        element_id = f"{element.get('type', 'object')}/{element.get('id', 'unknown')}"
        for layer in _feature_layers(tags, geom):
            key = (element_id, layer)
            if key in seen:
                continue
            seen.add(key)
            features.append({
                "id": element_id,
                "layer": layer,
                "source": "OpenStreetMap",
                "tags": tags,
                "geometry": geom,
            })
    return features


def _overpass_query(bbox_wgs84: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox_wgs84
    bbox = f"{south:.7f},{west:.7f},{north:.7f},{east:.7f}"
    return "\n".join([
        "[out:json][timeout:180];",
        "(",
        f'  nwr["building"]({bbox});',
        f'  nwr["highway"]({bbox});',
        f'  nwr["railway"]({bbox});',
        f'  nwr["landuse"]({bbox});',
        f'  nwr["leisure"="park"]({bbox});',
        f'  nwr["natural"="water"]({bbox});',
        f'  nwr["waterway"]({bbox});',
        f'  nwr["man_made"~"^(pier|quay)$"]({bbox});',
        ");",
        "out geom;",
    ])


def _query_bbox_28992(site: Polygon, margin_m: float = 1500.0) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = site.bounds
    return minx - margin_m, miny - margin_m, maxx + margin_m, maxy + margin_m


def _bbox_wgs84(bbox_28992: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    transformer = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
    minx, miny, maxx, maxy = bbox_28992
    west, south, east, north = transformer.transform_bounds(minx, miny, maxx, maxy, densify_pts=41)
    return float(west), float(south), float(east), float(north)


def _split_bbox(bbox: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    minx, miny, maxx, maxy = bbox
    midx = (minx + maxx) / 2.0
    midy = (miny + maxy) / 2.0
    return [
        (minx, miny, midx, midy),
        (midx, miny, maxx, midy),
        (minx, midy, midx, maxy),
        (midx, midy, maxx, maxy),
    ]


def _dedupe_elements(elements: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for element in elements:
        key = (str(element.get("type", "")), int(element.get("id", -1)))
        out[key] = element
    return [out[k] for k in sorted(out)]


def _overpass_chunk(
    manager: RequestManager,
    bbox_28992: tuple[float, float, float, float],
    *,
    depth: int = 0,
) -> tuple[list[dict[str, Any]], bool]:
    split_key_query = _overpass_query(_bbox_wgs84(bbox_28992))
    split_key = manager.query_key("POST", OVERPASS_URL, split_key_query)
    split_manifest = manager.raw_dir / f"split-{split_key}.json"
    if not manager.refresh and split_manifest.exists():
        try:
            manifest = json.loads(split_manifest.read_text(encoding="utf-8"))
            children = [tuple(float(v) for v in child) for child in manifest["children_bbox_28992"]]
            collected: list[dict[str, Any]] = []
            all_complete = True
            for child in children:
                child_elements, child_ok = _overpass_chunk(manager, child, depth=depth + 1)
                collected.extend(child_elements)
                all_complete = all_complete and child_ok
            return _dedupe_elements(collected), all_complete
        except (OSError, ValueError, KeyError, TypeError):
            pass

    west, south, east, north = _bbox_wgs84(bbox_28992)
    query = _overpass_query((west, south, east, north))
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    key = manager.query_key("POST", OVERPASS_URL, query)
    cached = manager.cached("POST", OVERPASS_URL, query)
    if cached:
        status, response, record = cached
        try:
            payload = json.loads(response.decode("utf-8"))
            if isinstance(payload.get("elements"), list):
                return list(payload["elements"]), True
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            record["cache_validation_error"] = "Overpass cache is not a valid JSON elements response"

    failures: list[dict[str, Any]] = []
    for attempt in range(1, 4):
        status, response, record = manager.request(
            "POST",
            OVERPASS_URL,
            query,
            post_body=body,
            content_type="application/x-www-form-urlencoded; charset=utf-8",
            extension="json",
            use_cache=False,
        )
        try:
            if status == 200 and response is not None:
                payload = json.loads(response.decode("utf-8"))
                if isinstance(payload.get("elements"), list):
                    manager.save_cache("POST", OVERPASS_URL, query, record)
                    return list(payload["elements"]), True
                record["validation_error"] = "JSON response has no elements list"
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            record["validation_error"] = f"invalid Overpass JSON: {type(exc).__name__}"
        failures.append({"status_code": status, "response_sha256": record.get("response_sha256"), "error": record.get("error")})
        if status in (429, 504):
            time.sleep(RETRY_WAIT_S)

    minx, miny, maxx, maxy = bbox_28992
    if maxx - minx <= MIN_SPLIT_SPAN_M or maxy - miny <= MIN_SPLIT_SPAN_M or depth >= 5:
        return [], False
    children = _split_bbox(bbox_28992)
    split_manifest.write_text(
        json.dumps({"failed_chunk_query_sha256": sha256_bytes(query.encode("utf-8")), "failures": failures, "children_bbox_28992": children}, indent=2) + "\n",
        encoding="utf-8",
    )
    combined: list[dict[str, Any]] = []
    complete = True
    for child in children:
        child_elements, child_ok = _overpass_chunk(manager, child, depth=depth + 1)
        combined.extend(child_elements)
        complete = complete and child_ok
    return _dedupe_elements(combined), complete


def _feature_geometry(feature: dict[str, Any]) -> Any | None:
    geom = feature.get("geometry")
    if geom is None:
        return None
    if hasattr(geom, "geom_type"):
        return geom
    try:
        return shape(geom)
    except (TypeError, ValueError):
        return None


def _features_on_layer(features: Sequence[dict[str, Any]], layer: str) -> list[dict[str, Any]]:
    return [f for f in features if f.get("layer") == layer and _feature_geometry(f) is not None]


def _unique_geometry_list(features: Sequence[dict[str, Any]], layer: str) -> list[Any]:
    geometries: list[Any] = []
    seen: set[bytes] = set()
    for feature in _features_on_layer(features, layer):
        geom = _feature_geometry(feature)
        if geom is None or geom.is_empty:
            continue
        for part in (_polygon_parts(geom) if layer in {"building", "water", "park", "landuse", "building_3dbag"} else _line_parts(geom)):
            key = part.wkb
            if key not in seen:
                geometries.append(part)
                seen.add(key)
    return geometries


def _project_site_features(site_facts: dict[str, Any]) -> list[dict[str, Any]]:
    geometry = site_facts.get("geometry", {})
    features: list[dict[str, Any]] = []
    for layer, source_key, tag_key in (
        ("building", "retained_buildings", "building"),
        ("highway", "retained_roads", "highway"),
    ):
        for item in geometry.get(source_key, []) or []:
            geom = _feature_geometry(item)
            if geom is None or geom.is_empty:
                continue
            features.append({
                "id": str(item.get("id", f"site-facts:{source_key}:{len(features)}")),
                "layer": layer,
                "source": "site-facts",
                "tags": {tag_key: "retained"},
                "geometry": geom,
            })
    for key, layer, tags in (
        ("water", "water", {"natural": "water", "source": "site-facts"}),
        ("dakpark", "park", {"leisure": "park", "name": "Dakpark", "source": "site-facts"}),
    ):
        raw_geom = geometry.get(key)
        if raw_geom:
            geom = _feature_geometry({"geometry": raw_geom})
            if geom is not None and not geom.is_empty:
                features.append({
                    "id": f"site-facts:{key}",
                    "layer": layer,
                    "source": "site-facts",
                    "tags": tags,
                    "geometry": geom,
                })
    return features


def _audit_unordered_3dbag_pages(request_records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Count identifier overlap in earlier WFS pages that lacked explicit ordering."""
    seen_query_hashes: set[str] = set()
    seen_ids: set[str] = set()
    row_count = 0
    missing_id_count = 0
    matched_counts: set[int] = set()
    response_hashes: set[str] = set()
    page_count = 0
    for record in request_records:
        query = str(record.get("query", ""))
        if "data.3dbag.nl" not in str(record.get("url", "")) or "GetFeature" not in query or "sortBy=" in query:
            continue
        if record.get("status_code") != 200 or not record.get("response_sha256"):
            continue
        query_hash = str(record.get("query_sha256") or "")
        if query_hash and query_hash in seen_query_hashes:
            continue
        if query_hash:
            seen_query_hashes.add(query_hash)
        try:
            payload = json.loads(Path(str(record.get("raw_response_file") or "")).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        features = payload.get("features")
        if not isinstance(features, list):
            continue
        page_count += 1
        response_hashes.add(str(record["response_sha256"]))
        try:
            matched_counts.add(int(payload["numberMatched"]))
        except (KeyError, TypeError, ValueError):
            pass
        row_count += len(features)
        for feature in features:
            fid = feature.get("id")
            if fid is None:
                fid = (feature.get("properties") or {}).get("fid")
            if fid is None:
                missing_id_count += 1
            else:
                seen_ids.add(str(fid))
    duplicates = max(0, row_count - len(seen_ids) - missing_id_count)
    if page_count == 0:
        status = "NOT_APPLICABLE"
    elif duplicates:
        status = "EXCLUDED_FROM_FINAL_METRICS_DUPLICATE_IDS"
    else:
        status = "NO_DUPLICATE_IDS_DETECTED"
    return {
        "status": status,
        "page_count": page_count,
        "response_row_count": row_count,
        "unique_feature_id_count": len(seen_ids),
        "duplicate_row_count": duplicates,
        "missing_feature_id_count": missing_id_count,
        "server_number_matched_values": sorted(matched_counts),
        "raw_response_hashes": sorted(response_hashes),
        "final_measurement_use": "EXCLUDED" if duplicates else "NOT_USED",
    }


def _matching_lines(features: Sequence[dict[str, Any]], layer: str) -> list[LineString]:
    lines: list[LineString] = []
    for feature in _features_on_layer(features, layer):
        lines.extend(_line_parts(_feature_geometry(feature)))
    return lines


STREET_HIERARCHY_CLASSES = {
    "primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link",
    "unclassified", "residential", "living_street",
}


def _hierarchical_street_lines(features: Sequence[dict[str, Any]]) -> list[LineString]:
    lines: list[LineString] = []
    for feature in _features_on_layer(features, "highway"):
        if str(feature.get("tags", {}).get("highway", "")).casefold() not in STREET_HIERARCHY_CLASSES:
            continue
        lines.extend(_line_parts(_feature_geometry(feature)))
    return lines


def _weighted_mean_orientation(lines: Sequence[LineString]) -> float | None:
    sin_sum = 0.0
    cos_sum = 0.0
    for line in lines:
        if line.is_empty:
            continue
        coords = list(line.coords)
        for a, b in zip(coords, coords[1:]):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length <= 1e-6:
                continue
            az = segment_azimuth_deg((a[0], a[1]), (b[0], b[1]))
            angle2 = math.radians(2.0 * az)
            sin_sum += length * math.sin(angle2)
            cos_sum += length * math.cos(angle2)
    if math.hypot(sin_sum, cos_sum) <= 1e-9:
        return None
    return round((math.degrees(math.atan2(sin_sum, cos_sum)) / 2.0) % 180.0, 1)


def _orientation_record(lines: Sequence[LineString], site_axis_deg: float | None = None) -> dict[str, Any]:
    peak1, peak2, histogram = compute_orientation_peaks(lines)
    peaks = []
    for rank, angle in enumerate((peak1, peak2), start=1):
        if angle is None:
            continue
        peaks.append({
            "rank": rank,
            "azimuth_deg": angle,
            "angle_to_site_long_axis_deg": angle_difference_deg(angle, site_axis_deg) if site_axis_deg is not None else None,
        })
    return {"primary_peaks": peaks, "histogram": histogram}


def _landuse_label(tags: dict[str, Any]) -> str | None:
    if tags.get("natural") == "water" or tags.get("waterway") == "riverbank" or tags.get("landuse") in {"reservoir", "basin"}:
        return "水域／港池"
    if tags.get("leisure") == "park":
        return "公園／綠地"
    landuse = str(tags.get("landuse", "")).casefold()
    if landuse in {"industrial", "port", "harbour"}:
        return "港區工業／倉儲"
    if landuse == "residential":
        return "住宅區"
    if landuse in {"commercial", "retail"}:
        return "商業／服務"
    if landuse in {"railway", "construction"}:
        return "交通／施工用地"
    return None


def _site_boundary_sides(site: Polygon) -> dict[str, Any]:
    center = site.centroid
    pieces: dict[str, list[LineString]] = {"北側": [], "南側": [], "東側": [], "西側": []}
    polygons = [site] if isinstance(site, Polygon) else list(site.geoms)
    for polygon in polygons:
        coords = list(polygon.exterior.coords)
        for a, b in zip(coords, coords[1:]):
            if math.hypot(b[0] - a[0], b[1] - a[1]) <= 1e-6:
                continue
            midx, midy = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
            if abs(midy - center.y) >= abs(midx - center.x):
                side = "北側" if midy >= center.y else "南側"
            else:
                side = "東側" if midx >= center.x else "西側"
            pieces[side].append(LineString([a, b]))
    return {side: unary_union(lines) if lines else GeometryCollection() for side, lines in pieces.items()}


def _road_junction_points(roads: Sequence[LineString]) -> list[Point]:
    valid = [line for line in roads if not line.is_empty and line.length > 0]
    if not valid:
        return []
    noded = unary_union(valid)
    parts = _line_parts(noded)
    degrees: dict[tuple[float, float], int] = {}
    for line in parts:
        coords = list(line.coords)
        if len(coords) < 2:
            continue
        for coord in (coords[0], coords[-1]):
            key = (round(coord[0], 1), round(coord[1], 1))
            degrees[key] = degrees.get(key, 0) + 1
    return [Point(x, y) for (x, y), degree in degrees.items() if degree >= 3]


def _side_adjacency(
    site: Polygon,
    features: Sequence[dict[str, Any]],
    roads: Sequence[LineString],
) -> list[dict[str, Any]]:
    junctions = _road_junction_points(roads)
    output: list[dict[str, Any]] = []
    for side, boundary_piece in _site_boundary_sides(site).items():
        if boundary_piece.is_empty:
            output.append({"side": side, "adjacent_texture": "UNKNOWN", "nearest_street": None, "nearest_junction": None})
            continue
        outside = boundary_piece.buffer(60.0, cap_style="flat").difference(site)
        area_by_label: dict[str, float] = {}
        for feature in features:
            label = _landuse_label(feature.get("tags", {}))
            if not label:
                continue
            geom = _feature_geometry(feature)
            if geom is None or geom.is_empty or not geom.intersects(outside):
                continue
            area = sum(part.intersection(outside).area for part in _polygon_parts(geom))
            if area > 0:
                area_by_label[label] = area_by_label.get(label, 0.0) + area
        if area_by_label:
            adjacent_texture = max(area_by_label, key=area_by_label.get)
            texture_area_m2 = round(area_by_label[adjacent_texture], 1)
        else:
            adjacent_texture = "建成區／用途未標註" if any(
                (g := _feature_geometry(f)) is not None and g.intersects(outside)
                for f in _features_on_layer(features, "building")
            ) else "未標註／資料不足"
            texture_area_m2 = None

        nearest_street = None
        best_street_distance = math.inf
        for feature in _features_on_layer(features, "highway"):
            geom = _feature_geometry(feature)
            if geom is None or geom.is_empty:
                continue
            dist = boundary_piece.distance(geom)
            if dist < best_street_distance:
                best_street_distance = dist
                line = _line_parts(geom)
                nearest_street = {
                    "id": feature.get("id"),
                    "name": feature.get("tags", {}).get("name"),
                    "highway": feature.get("tags", {}).get("highway"),
                    "distance_m": round(dist, 1),
                    "azimuth_deg": _weighted_mean_orientation(line),
                }
        nearest_junction = None
        if junctions:
            point = min(junctions, key=boundary_piece.distance)
            nearest_junction = {
                "coordinates_epsg28992": [round(point.x, 2), round(point.y, 2)],
                "distance_m": round(boundary_piece.distance(point), 1),
            }
        output.append({
            "side": side,
            "adjacent_texture": adjacent_texture,
            "intersected_landuse_area_m2": texture_area_m2,
            "nearest_street": nearest_street,
            "nearest_junction": nearest_junction,
        })
    return output


def _zone_specs(site: Polygon, dakpark: Any, fetch_window: Polygon, features: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    minx, miny, maxx, maxy = site.bounds
    south_residential = []
    for feature in _features_on_layer(features, "landuse"):
        if feature.get("tags", {}).get("landuse") != "residential":
            continue
        geom = _feature_geometry(feature)
        if geom is None or geom.is_empty or geom.distance(site) > 1500.0:
            continue
        if geom.centroid.y >= site.centroid.y:
            continue
        clipped = geom.intersection(fetch_window)
        if not clipped.is_empty and clipped.area > 0.0:
            south_residential.append(clipped)
    south = unary_union(south_residential) if south_residential else GeometryCollection()
    port = site.buffer(650.0).intersection(fetch_window)
    park_zone = dakpark.buffer(400.0).intersection(fetch_window) if dakpark is not None and not dakpark.is_empty else GeometryCollection()
    specs = [
        {"id": "spangen_bospolder", "name_zh": "Spangen／Bospolder 南側住宅區（OSM 用地對照）", "window": south, "window_method": "基地質心以南 1,500 m 內的 OSM landuse=residential 多邊形聯集，裁切於本次抓取矩形；名稱只表示住宅紋理對照，不代表 Spangen／Bospolder 行政界線"},
        {"id": "m4h_port", "name_zh": "M4H 港區倉庫與廠房（基地及相鄰港池）", "window": port, "window_method": "基地外擴 650 m 的緩衝研究窗"},
        {"id": "dakpark_vierhavensstraat", "name_zh": "Dakpark 與 Vierhavensstraat 一帶", "window": park_zone, "window_method": "Dakpark 幾何外擴 400 m 的緩衝研究窗"},
    ]
    named_areas: dict[str, list[Any]] = {"delfshaven": [], "oud_mathenesse": []}
    for feature in _features_on_layer(features, "landuse"):
        tags = feature.get("tags", {})
        name = str(tags.get("name", "")).casefold().replace("-", " ")
        geom = _feature_geometry(feature)
        if geom is None or geom.is_empty or not geom.intersects(fetch_window):
            continue
        if "delfshaven" in name:
            named_areas["delfshaven"].append(geom)
        if "oud mathenesse" in name or "oude mathenesse" in name:
            named_areas["oud_mathenesse"].append(geom)
    labels = {"delfshaven": "Delfshaven", "oud_mathenesse": "Oud-Mathenesse"}
    for key, geometries in named_areas.items():
        if geometries:
            combined = unary_union(geometries).buffer(100.0).intersection(fetch_window)
            specs.append({
                "id": key,
                "name_zh": f"{labels[key]}（OSM 命名用地範圍）",
                "window": combined,
                "window_method": "OSM landuse 命名幾何外擴 100 m；未用 place 類標籤推定範圍",
            })
    return [s for s in specs if s["window"] is not None and not s["window"].is_empty and s["window"].area > 0.0]


def _height_features_for_window(
    height_features: Sequence[dict[str, Any]],
    window: Polygon,
    water_polygons: Sequence[Polygon],
    industrial_polygons: Sequence[Polygon],
    osm_buildings: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    water_union = unary_union(water_polygons) if water_polygons else Polygon()
    industrial_union = unary_union(industrial_polygons) if industrial_polygons else Polygon()
    measured: list[dict[str, Any]] = []
    for feature in height_features:
        geom = _feature_geometry(feature)
        if geom is None or geom.is_empty or not geom.intersects(window):
            continue
        clipped = geom.intersection(window)
        if not water_union.is_empty:
            clipped = clipped.difference(water_union)
        area = sum(part.area for part in _polygon_parts(clipped))
        if area <= 0.0:
            continue
        industrial_overlap = clipped.intersection(industrial_union).area if not industrial_union.is_empty else 0.0
        use = " ".join(str(feature.get("tags", {}).get(k, "")) for k in ("use", "gebruiksdoel")).casefold()
        use_class: bool | None = None
        if industrial_overlap / area >= 0.5 or any(token in use for token in ("industrial", "industry", "industrie", "warehouse", "fabriek", "factory")):
            use_class = True
        elif any(token in use for token in ("woonfunctie", "residential", "woning", "house", "apartments")):
            use_class = False
        else:
            osm_classes: set[bool] = set()
            for osm_building in osm_buildings:
                osm_geom = _feature_geometry(osm_building)
                if osm_geom is None or osm_geom.is_empty or not osm_geom.intersects(clipped):
                    continue
                overlap = osm_geom.intersection(clipped).area
                if overlap / area < 0.5:
                    continue
                building_tag = str(osm_building.get("tags", {}).get("building", "")).casefold()
                if building_tag in {"industrial", "warehouse", "factory", "manufacture", "hangar"}:
                    osm_classes.add(True)
                elif building_tag in {"residential", "apartments", "house", "terrace", "detached", "semidetached_house", "bungalow", "dormitory"}:
                    osm_classes.add(False)
            if len(osm_classes) == 1:
                use_class = next(iter(osm_classes))
        measured.append({
            "area_m2": area,
            "height_m": feature.get("height_m"),
            "height_source": feature.get("height_source", "3DBAG WFS"),
            "height_method": feature.get("height_method"),
            "is_industrial": use_class,
        })
    return measured


def _zone_metrics(
    zone_window: Any,
    features: Sequence[dict[str, Any]],
    site_axis_deg: float,
    height_features: Sequence[dict[str, Any]],
    site_water: Sequence[Polygon],
) -> dict[str, Any]:
    zone_features: list[dict[str, Any]] = []
    for feature in features:
        geom = _feature_geometry(feature)
        if geom is None or geom.is_empty or not geom.intersects(zone_window):
            continue
        clipped = geom.intersection(zone_window)
        if clipped.is_empty:
            continue
        zone_features.append({**feature, "geometry": clipped})
    roads = _matching_lines(zone_features, "highway")
    waterways = _matching_lines(zone_features, "waterway")
    water_polygons = _unique_geometry_list(zone_features, "water") + list(site_water)
    water_polygons = [p for p in water_polygons if p.intersects(zone_window)]
    railway_lines = _matching_lines(zone_features, "railway")
    buildings_clipped = _unique_geometry_list(zone_features, "building")
    buildings = [
        _feature_geometry(f) for f in _features_on_layer(features, "building")
        if (g := _feature_geometry(f)) is not None and zone_window.covers(g)
    ]
    park_polygons = _unique_geometry_list(zone_features, "park")
    landuse_polygons = _unique_geometry_list(zone_features, "landuse")

    # Commander 2026-10-11: blocks are cut by the street hierarchy only (footways,
    # service roads and cycleways split blocks into fragments; Spangen median 27 m).
    street_roads = _hierarchical_street_lines(zone_features)
    blocks = cut_blocks_from_network(
        zone_window,
        street_roads + waterways,
        water_polygons=water_polygons,
        min_block_area_m2=1000.0,
    )
    block_stats = analyze_block_distribution(blocks, zone_window)
    coverage = compute_gsi(zone_window, buildings_clipped, water_polygons)
    land_area = float(coverage["land_area_m2"] or 0.0)
    if coverage["gsi"] is not None:
        coverage["status"] = "COMPUTED"
    else:
        coverage["status"] = "UNKNOWN_NO_LAND_DENOMINATOR"

    industrial_polygons = [
        _feature_geometry(f)
        for f in _features_on_layer(zone_features, "landuse")
        if f.get("tags", {}).get("landuse") in {"industrial", "port", "harbour"}
    ]
    industrial_polygons = [g for g in industrial_polygons if g is not None and not g.is_empty]
    heights = _height_features_for_window(height_features, zone_window, water_polygons, industrial_polygons, _features_on_layer(zone_features, "building"))
    fsi = compute_fsi_and_floors(heights, land_area)
    wing = compute_wing_depths(buildings, min_area_m2=50.0)
    # Commander 2026-10-11: row houses are mapped per dwelling; merge touching footprints
    # into masses and use 2A/P (≈ wing width for bars and rings) as the wing-depth proxy.
    _masses = unary_union([b.buffer(0.5) for b in buildings]) if buildings else Polygon()
    _masses = list(getattr(_masses, "geoms", [_masses]))
    _depths = sorted(2 * m.area / m.length for m in _masses if not m.is_empty and m.area >= 200 and m.length > 0)
    if _depths:
        import numpy as _np
        wing = {"count": len(_depths), "median_m": round(float(_np.median(_depths)), 1), "p25_m": round(float(_np.percentile(_depths, 25)), 1), "p75_m": round(float(_np.percentile(_depths, 75)), 1), "method": "merged masses (0.5 m buffer, ≥200 m²), 2A/P", "per_footprint_mrr_short_side": wing}
    footprint_union = unary_union(buildings) if buildings else Polygon()
    footprint_area = footprint_union.area if not footprint_union.is_empty else 0.0
    large_area = sum(g.area for g in buildings if g.area >= 2000.0)
    large_ratio = large_area / footprint_area if footprint_area > 0 else 0.0
    industrial_features = [f for f in _features_on_layer(zone_features, "landuse") if f.get("tags", {}).get("landuse") in {"industrial", "port", "harbour"}]
    industrial_area = sum(_feature_geometry(f).intersection(zone_window).area for f in industrial_features if _feature_geometry(f) is not None)
    industrial_share = industrial_area / land_area if land_area > 0 else 0.0
    is_port_industrial = industrial_share >= 0.25
    median_block_area = block_stats["area_m2"]["median"] if block_stats["total_blocks"] else 0.0
    typology, typology_method = classify_dominant_typology(
        gsi=float(coverage["gsi"] or 0.0),
        avg_floors=fsi.get("average_floors"),
        wing_depth_median=float(wing["median_m"] or 0.0),
        median_block_area_m2=float(median_block_area or 0.0),
        large_footprint_ratio=large_ratio,
        is_port_industrial=is_port_industrial,
    )
    peaks = _orientation_record(roads, site_axis_deg)
    spacing_roads = _hierarchical_street_lines(zone_features)
    spacings = []
    for peak in peaks["primary_peaks"]:
        spacing = compute_typical_street_spacing(spacing_roads, peak["azimuth_deg"])
        spacings.append({"axis_azimuth_deg": peak["azimuth_deg"], **spacing})
    intersection_count, intersection_density = compute_intersection_density(roads, land_area)
    railway_orientation = _orientation_record(railway_lines, site_axis_deg)

    clipped_road_count = sum(
        1 for feature in _features_on_layer(zone_features, "highway")
        if (geom := _feature_geometry(feature)) is not None and geom.intersects(zone_window)
    )
    parks_union = unary_union(park_polygons) if park_polygons else Polygon()
    return {
        "window_area_m2": round(float(zone_window.area), 1),
        "land_area_m2": round(land_area, 1),
        "blocks": block_stats,
        "streets": {
            "road_feature_count": clipped_road_count,
            "intersection_count": intersection_count,
            "intersection_density_per_km2": intersection_density,
            "orientation": peaks,
            "typical_parallel_spacing": spacings,
            "railway_orientation": railway_orientation,
        },
        "buildings": {
            "coverage": coverage,
            "fsi": fsi,
            "wing_depth_m": wing,
            "building_count": len(buildings_clipped),
            "large_footprint_share": round(large_ratio, 4),
            "industrial_land_share": round(industrial_share, 4),
            "dominant_typology": typology,
            "typology_method": typology_method,
        },
        "parks_area_m2": round(parks_union.area, 1),
    }


def build_context_facts(
    site_facts: dict[str, Any],
    features: Sequence[dict[str, Any]],
    request_records: Sequence[dict[str, Any]],
    *,
    height_features: Sequence[dict[str, Any]] | None = None,
    acquisition_status: dict[str, Any] | None = None,
    source_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build machine-readable context measurements from projected geometries."""
    geometry = site_facts.get("geometry", {})
    if str(geometry.get("crs", "")).upper() != "EPSG:28992":
        raise ValueError("site-facts geometry must declare EPSG:28992")
    site = shape(geometry["site"])
    if site.is_empty or not site.is_valid or site.area <= 0.0:
        raise ValueError("site geometry must be valid and have positive area")
    dakpark = shape(geometry["dakpark"]) if geometry.get("dakpark") else GeometryCollection()
    site_water = _polygon_parts(shape(geometry["water"])) if geometry.get("water") else []
    enriched = list(features) + _project_site_features(site_facts)
    fetch_bbox = _query_bbox_28992(site)
    fetch_window = box(*fetch_bbox)
    site_axis = compute_site_principal_axis(site)
    axis_az = float(site_axis["long_axis_azimuth_deg"])
    height_features = list(height_features or [])

    zones = []
    for spec in _zone_specs(site, dakpark, fetch_window, enriched):
        zone_window = spec["window"]
        metrics = _zone_metrics(zone_window, enriched, axis_az, height_features, site_water)
        zones.append({
            "id": spec["id"],
            "name_zh": spec["name_zh"],
            "window_method": spec["window_method"],
            "window_geometry_epsg28992": mapping(zone_window),
            "metrics": metrics,
        })

    all_roads = _matching_lines(enriched, "highway")
    all_harbor = [f for f in enriched if f.get("layer") == "harbor_structure"]
    harbor_lines = [line for feature in all_harbor for line in _line_parts(_feature_geometry(feature))]
    railway_lines = _matching_lines(enriched, "railway")
    nearby_water = [
        geom.boundary for geom in _unique_geometry_list(enriched, "water")
        if geom.distance(site) <= 900.0
    ]
    water_edge_lines = [line for geom in nearby_water for line in _line_parts(geom)]
    named_roads: list[dict[str, Any]] = []
    for requested in ("Keileweg", "Vierhavensstraat", "Marconistraat"):
        matches = []
        for feature in _features_on_layer(enriched, "highway"):
            name = str(feature.get("tags", {}).get("name", "")).casefold()
            if requested.casefold() in name:
                matches.extend(_line_parts(_feature_geometry(feature)))
        named_roads.append({
            "name": requested,
            "status": "FOUND" if matches else "NOT_FOUND_IN_QUERY",
            "azimuth_deg": _weighted_mean_orientation(matches),
            "angle_to_site_long_axis_deg": angle_difference_deg(_weighted_mean_orientation(matches), axis_az) if matches else None,
            "source_feature_count": len(matches),
        })

    dakpark_osm = []
    for feature in _features_on_layer(enriched, "park"):
        if "dakpark" in str(feature.get("tags", {}).get("name", "")).casefold():
            dakpark_osm.append(feature)
    if dakpark_osm:
        park_for_axis = unary_union([_feature_geometry(f) for f in dakpark_osm])
        park_axis_source = "OSM leisure=park, name includes Dakpark"
    else:
        park_for_axis = dakpark
        park_axis_source = "site-facts geometry.dakpark; OSM named park polygon not found"
    park_edge_lines = _line_parts(park_for_axis.boundary) if park_for_axis is not None and not park_for_axis.is_empty else []
    park_ele_values: list[float] = []
    for feature in dakpark_osm:
        raw_ele = feature.get("tags", {}).get("ele")
        if raw_ele is not None:
            match = re.search(r"-?\d+(?:\.\d+)?", str(raw_ele))
            if match:
                park_ele_values.append(float(match.group(0)))
    park_edge_geometry = park_for_axis.boundary if park_for_axis is not None and not park_for_axis.is_empty else GeometryCollection()
    adjacent_ground_ele_values: list[float] = []
    for feature in _features_on_layer(enriched, "highway"):
        geom = _feature_geometry(feature)
        raw_ele = feature.get("tags", {}).get("ele")
        if geom is None or raw_ele is None or geom.distance(park_edge_geometry) > 25.0:
            continue
        match = re.search(r"-?\d+(?:\.\d+)?", str(raw_ele))
        if match:
            adjacent_ground_ele_values.append(float(match.group(0)))
    park_ele_mean = sum(park_ele_values) / len(park_ele_values) if park_ele_values else None
    ground_ele_mean = sum(adjacent_ground_ele_values) / len(adjacent_ground_ele_values) if adjacent_ground_ele_values else None
    dakpark_height_difference = park_ele_mean - ground_ele_mean if park_ele_mean is not None and ground_ele_mean is not None else None

    street_entries = []
    for feature in _features_on_layer(enriched, "highway"):
        geom = _feature_geometry(feature)
        if geom is None or geom.distance(site) > 300.0:
            continue
        if str(feature.get("tags", {}).get("highway", "")).casefold() not in STREET_HIERARCHY_CLASSES:
            continue
        for line in _line_parts(geom):
            street_entries.append({
                "id": feature.get("id"),
                "name": feature.get("tags", {}).get("name"),
                "highway": feature.get("tags", {}).get("highway"),
                "geometry": line,
            })
    continuation = find_continuation_street_candidates(site, street_entries, max_search_dist_m=250.0)
    side_adjacencies = _side_adjacency(site, enriched, all_roads)
    global_orientation = _orientation_record(all_roads, axis_az)

    acquisition_status = acquisition_status or {"osm": "SYNTHETIC_OR_LOCAL_INPUT", "three_db_ag": "NOT_REQUESTED"}
    return {
        "schema_version": "ctx1-context-morphology-v1",
        "generated_at_utc": utc_now(),
        "evidence_status": "COMPUTED_RESULT",
        "evidence_scope": "EXPLORATORY_CONTEXT_ONLY",
        "project_id": site_facts.get("project_id"),
        "study_area_id": site_facts.get("site", {}).get("study_area_id"),
        "horizontal_crs": "EPSG:28992",
        "units": "m",
        "request_extent": {
            "margin_from_site_envelope_m": 1500.0,
            "bbox_epsg28992": [round(v, 2) for v in fetch_bbox],
            "bbox_wgs84_lonlat": [round(v, 7) for v in _bbox_wgs84(fetch_bbox)],
        },
        "input_provenance": source_hashes or {},
        "acquisition_status": acquisition_status,
        "software": {
            "script_version": "ctx1-context-morphology-1.0",
            "python": sys.version.split()[0],
            "shapely": _safe_package_version("shapely"),
            "pyproj": _safe_package_version("pyproj"),
            "pillow": _safe_package_version("Pillow"),
        },
        "site": {
            "area_m2": round(float(site.area), 1),
            "geometry_epsg28992": mapping(site),
            "principal_axis": site_axis,
        },
        "texture_zones": zones,
        "boundary_and_alignments": {
            "azimuth_convention": "北起順時針；無向線以 0–180° 表示",
            "road_orientation_peaks": global_orientation,
            "named_roads": named_roads,
            "harbor_water_edge_orientation": _orientation_record(water_edge_lines, axis_az),
            "pier_quay_orientation": _orientation_record(harbor_lines, axis_az),
            "railway_orientation": _orientation_record(railway_lines, axis_az),
            "dakpark_edge": {
                "source": park_axis_source,
                "geometry_epsg28992": mapping(park_for_axis) if park_for_axis is not None and not park_for_axis.is_empty else None,
                "orientation": _orientation_record(park_edge_lines, axis_az),
                "park_elevation_m": round(park_ele_mean, 2) if park_ele_mean is not None else None,
                "adjacent_ground_elevation_m": round(ground_ele_mean, 2) if ground_ele_mean is not None else None,
                "height_difference_m": round(dakpark_height_difference, 2) if dakpark_height_difference is not None else None,
                "park_ele_tag_count": len(park_ele_values),
                "adjacent_ground_ele_tag_count": len(adjacent_ground_ele_values),
                "elevation_status": "COMPUTED_FROM_PAIRED_OSM_ELE_TAGS" if dakpark_height_difference is not None else "UNKNOWN",
                "elevation_method": "Dakpark OSM ele 平均值減距 Dakpark 邊線 25 m 內且帶 ele 標籤之道路平均值；缺任一側即 UNKNOWN。3DBAG 建物高度不代替地坪高程差。",
            },
        },
        "site_adjacencies": side_adjacencies,
        "continuation_street_candidates": continuation,
        "method_parameters": {
            "block_min_area_m2": 100.0,
            "complete_block_rule": "街廓邊界不接觸研究窗外框",
            "street_spacing_min_distance_m": 20.0,
            "street_spacing_max_distance_m": 350.0,
            "street_spacing_parallel_tolerance_deg": 15.0,
            "wing_depth_min_building_area_m2": 50.0,
            "large_footprint_threshold_m2": 2000.0,
            "industrial_land_share_threshold": 0.25,
            "typology_rule_version": TYPOLOGY_VERSION,
            "typology_rules_are_project_standards": False,
            "typology_method_zh": "依 OSM 用地／建物標籤、建蔽率、最小外接矩形翼深與街廓面積作探索性規則分類；有 3DBAG 高度時才使用樓層數。巨型足跡面積占比達 0.40、工業用地占陸地達 0.25 或中位翼深達 28 m 時列廠房／倉庫；周邊式、板樓與點式依建蔽率、翼深與可用樓層數判別。門檻只供本次閱讀，不是規劃標準。",
        },
        "source_feature_counts": {
            layer: len(_features_on_layer(enriched, layer))
            for layer in ("building", "highway", "railway", "landuse", "park", "water", "waterway", "harbor_structure", "building_3dbag")
        },
        "request_log": list(request_records),
        "limitations": [
            "研究窗為相對基地外推的矩形範圍；紋理區是明示的研究窗，不是法定行政邊界。",
            "OSM 幾何／標籤反映資料庫快照；缺少標籤不代表現地不存在。",
            "完整街廓僅依研究窗外框判定；道路中心線、水路與橋隧層級會影響切分。",
            "FSI 僅在 3DBAG 建物高度覆蓋完整時提供完整區域值；部分覆蓋另列觀測子集，不補估缺值。",
            "平均樓層以量體高度除以住宅 3.0 m／工業 5.0 m 層高；是方法假設，不代表實際樓板層數。",
            "Dakpark 高差只有在 OSM 同時提供公園及 25 m 內鄰接道路 ele 標籤時才計算；3DBAG 建物高度不代替地坪高程差，也不把使用者提供的約 10 m 說法當作量測。",
        ],
    }


def _wfs_url(params: dict[str, Any]) -> str:
    return THREEDBAG_URL + "?" + urllib.parse.urlencode(params)


def _wfs_request_with_retries(
    manager: RequestManager,
    params: dict[str, Any],
    query_label: str,
    *,
    extension: str = "json",
    validator=None,
    allow_cache: bool = True,
) -> tuple[dict[str, Any] | None, bytes | None]:
    url = _wfs_url(params)
    last_record: dict[str, Any] | None = None
    for attempt in range(1, 4):
        status, body, record = manager.request(
            "GET", url, query_label, extension=extension, use_cache=allow_cache
        )
        last_record = record
        if status == 200 and body is not None:
            try:
                if validator is None or validator(body):
                    manager.save_cache("GET", url, query_label, record)
                    return record, body
                record["validation_error"] = "WFS response did not satisfy the expected payload schema"
            except Exception as exc:
                record["validation_error"] = f"response validation error: {type(exc).__name__}: {exc}"
        if status in (429, 504):
            time.sleep(RETRY_WAIT_S)
    return last_record, None


def _xml_feature_type_names(payload: bytes) -> list[str]:
    root = ET.fromstring(payload)
    names = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] == "FeatureType":
            for child in item:
                if child.tag.rsplit("}", 1)[-1] == "Name" and child.text:
                    names.append(child.text.strip())
    return names


def _xml_access_constraints(payload: bytes) -> list[str]:
    root = ET.fromstring(payload)
    values = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] in {"AccessConstraints", "Fees"} and item.text and item.text.strip():
            values.append(item.text.strip())
    return values


def _select_3dbag_type(names: Sequence[str]) -> str | None:
    candidates = [n for n in names if re.search(r"building|gebouw|lod", n, re.IGNORECASE)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda n: (
        0 if "lod22" in n.casefold() else 1,
        0 if "building" in n.casefold() or "gebouw" in n.casefold() else 1,
        len(n),
    ))[0]


def _iter_coordinate_tuples(value: Any) -> Iterable[Sequence[float]]:
    if isinstance(value, (list, tuple)):
        if len(value) >= 3 and all(isinstance(v, (int, float)) for v in value[:3]):
            yield value
        else:
            for child in value:
                yield from _iter_coordinate_tuples(child)


def _height_from_3dbag(properties: dict[str, Any], geometry: Any) -> tuple[float | None, str | None]:
    normalized = {str(k).casefold(): v for k, v in properties.items()}
    for key in ("building_height", "height_m", "b3_h_70p", "b3_h_max", "height"):
        raw = normalized.get(key)
        if raw is not None:
            try:
                value = float(raw)
                if 0.0 < value < 250.0:
                    return value, f"3DBAG attribute {key}"
            except (TypeError, ValueError):
                pass
    ground_keys = ("h_maaiveld", "h_ground", "ground_level")
    roof_keys = ("h_dak_70p", "h_dak_max", "h_hoogste_punt", "roof_height")
    ground = next((normalized[k] for k in ground_keys if normalized.get(k) is not None), None)
    roof = next((normalized[k] for k in roof_keys if normalized.get(k) is not None), None)
    if ground is not None and roof is not None:
        try:
            height = float(roof) - float(ground)
            if 0.0 < height < 250.0:
                return height, "3DBAG dakhoogte minus maaiveldhoogte"
        except (TypeError, ValueError):
            pass
    if geometry is not None:
        z_values = [float(coord[2]) for coord in _iter_coordinate_tuples(mapping(geometry).get("coordinates"))]
        if z_values:
            height = max(z_values) - min(z_values)
            if 0.0 < height < 250.0:
                return height, "3DBAG geometry Z-range"
    return None, None


def _parse_3dbag_geojson(payload: bytes, transformer: Transformer | None = None) -> list[dict[str, Any]]:
    if transformer is None:
        transformer = Transformer.from_crs("EPSG:28992", "EPSG:28992", always_xy=True)
    collection = json.loads(payload.decode("utf-8"))
    out = []
    for index, feature in enumerate(collection.get("features", [])):
        raw_geom = feature.get("geometry")
        if not raw_geom:
            continue
        try:
            geom = shape(raw_geom)
            if geom.is_empty:
                continue
            if not geom.is_valid:
                geom = make_valid(geom)
            # WFS is explicitly requested in EPSG:28992; this transformer keeps the
            # conversion boundary visible and prevents accidental lon/lat arithmetic.
            geom = geom_transform(transformer.transform, geom)
            properties = feature.get("properties") or {}
            height, method = _height_from_3dbag(properties, geom)
            use_label = properties.get("gebruiksdoel") or properties.get("building") or properties.get("function")
            out.append({
                "id": str(feature.get("id") or properties.get("identificatie") or f"3dbag:{index}"),
                "layer": "building_3dbag",
                "source": "3DBAG WFS",
                "height_source": "3DBAG WFS",
                "height_m": height,
                "height_method": method,
                "tags": {"use": use_label, "gebruiksdoel": properties.get("gebruiksdoel")},
                "geometry": geom,
            })
        except (TypeError, ValueError, KeyError):
            continue
    return out


def geom_transform(transformer, geom):
    from shapely.ops import transform as shapely_transform
    return shapely_transform(transformer, geom)


def _wfs_geojson_valid(payload: bytes) -> bool:
    try:
        parsed = json.loads(payload.decode("utf-8"))
        return isinstance(parsed, dict) and isinstance(parsed.get("features"), list)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def _fetch_3dbag_chunk(
    manager: RequestManager,
    type_name: str,
    bbox_28992: tuple[float, float, float, float],
    *,
    depth: int = 0,
) -> tuple[list[dict[str, Any]], bool]:
    minx, miny, maxx, maxy = bbox_28992
    bbox_text = f"{minx:.2f},{miny:.2f},{maxx:.2f},{maxy:.2f},EPSG:28992"
    page_size = 5000
    sort_by = "fid A"
    query_key = f"GetFeature typeNames={type_name}; bbox={bbox_text}; outputFormat=application/json; count={page_size}; sortBy={sort_by}"
    query_hash = manager.query_key("GET", THREEDBAG_URL, query_key)
    split_manifest = manager.raw_dir / f"3dbag-split-{query_hash}.json"
    if not manager.refresh and split_manifest.exists():
        try:
            manifest = json.loads(split_manifest.read_text(encoding="utf-8"))
            children = [tuple(float(v) for v in child) for child in manifest["children_bbox_28992"]]
            results: list[dict[str, Any]] = []
            complete = True
            for child in children:
                child_result, child_ok = _fetch_3dbag_chunk(manager, type_name, child, depth=depth + 1)
                results.extend(child_result)
                complete = complete and child_ok
            return results, complete
        except (OSError, ValueError, KeyError, TypeError):
            pass

    results: list[dict[str, Any]] = []
    start_index = 0
    matched_count: int | None = None
    last_record: dict[str, Any] | None = None
    complete = True
    previous_fid: int | None = None
    seen_fids: set[int] = set()
    while True:
        page_label = query_key if start_index == 0 else f"{query_key}; startIndex={start_index}"
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": type_name,
            "outputFormat": "application/json",
            "srsName": "EPSG:28992",
            "bbox": bbox_text,
            "count": str(page_size),
            "sortBy": sort_by,
        }
        if start_index:
            params["startIndex"] = str(start_index)
        last_record, body = _wfs_request_with_retries(manager, params, page_label, validator=_wfs_geojson_valid)
        if body is None:
            complete = False
            break
        try:
            payload = json.loads(body.decode("utf-8"))
            raw_features = payload.get("features", [])
            matched = payload.get("numberMatched")
            try:
                page_matched_count = int(matched) if matched not in (None, "unknown", "*") else None
            except (TypeError, ValueError):
                page_matched_count = None
            if matched_count is None:
                matched_count = page_matched_count
            if not raw_features:
                if matched_count is not None and start_index < matched_count:
                    complete = False
                break
            page_fids: list[int] = []
            try:
                for raw_feature in raw_features:
                    properties = raw_feature.get("properties") or {}
                    raw_fid = properties.get("fid")
                    if raw_fid is None:
                        raw_id = str(raw_feature.get("id", ""))
                        raw_fid = raw_id.rsplit(".", 1)[-1]
                    page_fids.append(int(raw_fid))
            except (TypeError, ValueError):
                complete = False
                if last_record is not None:
                    last_record["validation_error"] = "WFS sorted pagination requires integer fid values"
                break
            if page_fids != sorted(page_fids) or any(fid in seen_fids for fid in page_fids) or (previous_fid is not None and page_fids[0] <= previous_fid):
                complete = False
                if last_record is not None:
                    last_record["validation_error"] = "WFS fid A pagination was not strictly increasing and unique across pages"
                break
            seen_fids.update(page_fids)
            previous_fid = page_fids[-1]
            results.extend(_parse_3dbag_geojson(body))
            returned = int(payload.get("numberReturned") or len(raw_features))
            if returned <= 0:
                complete = False
                break
            start_index += returned
            if matched_count is not None:
                if start_index >= matched_count:
                    break
            elif returned < page_size:
                break
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            complete = False
            break

    if complete:
        return results, True
    minx, miny, maxx, maxy = bbox_28992
    if maxx - minx <= MIN_SPLIT_SPAN_M or maxy - miny <= MIN_SPLIT_SPAN_M or depth >= 5:
        return results, False
    children = _split_bbox(bbox_28992)
    split_manifest.write_text(
        json.dumps({"query": query_key, "children_bbox_28992": children, "last_failure": last_record}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    results = []
    complete = True
    for child in children:
        child_result, child_ok = _fetch_3dbag_chunk(manager, type_name, child, depth=depth + 1)
        results.extend(child_result)
        complete = complete and child_ok
    return results, complete


def fetch_3dbag_heights(
    manager: RequestManager,
    bbox_28992: tuple[float, float, float, float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch 3DBAG building geometry/heights only through the named WFS endpoint."""
    caps_params = {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"}
    caps_label = "WFS GetCapabilities; identify available 3DBAG feature types"
    caps_record, caps_body = _wfs_request_with_retries(
        manager,
        caps_params,
        caps_label,
        extension="xml",
        validator=lambda body: b"WFS_Capabilities" in body or b"WFS_Capabilities" in body.replace(b"wfs:", b""),
    )
    if caps_body is None:
        return [], {"status": "UNKNOWN", "reason": "3DBAG GetCapabilities unavailable after retries", "feature_type": None}
    try:
        names = _xml_feature_type_names(caps_body)
    except ET.ParseError as exc:
        if caps_record is not None:
            caps_record["validation_error"] = f"invalid WFS capabilities XML: {exc}"
        return [], {"status": "UNKNOWN", "reason": "3DBAG capabilities response could not be parsed", "feature_type": None}
    type_name = _select_3dbag_type(names)
    if type_name is None:
        return [], {"status": "UNKNOWN", "reason": "capabilities contained no recognizable building feature type", "feature_type_names": names, "license_terms": _xml_access_constraints(caps_body)}

    features, complete = _fetch_3dbag_chunk(manager, type_name, bbox_28992)
    features = list({f["id"]: f for f in features}.values())
    has_any_height = sum(1 for f in features if f.get("height_m") is not None)
    return features, {
        "status": "COMPLETE" if complete else "PARTIAL",
        "pagination_sort_by": "fid A",
        "pagination_unique_feature_count": len(features),
        "pagination_status": "COMPLETE_SORTED_UNIQUE" if complete else "PARTIAL_OR_FAILED",
        "feature_type": type_name,
        "feature_type_names": names,
        "license_terms": _xml_access_constraints(caps_body),
        "building_count": len(features),
        "height_count": has_any_height,
        "height_coverage_ratio": round(has_any_height / len(features), 4) if features else 0.0,
        "height_methods": sorted({f["height_method"] for f in features if f.get("height_method")}),
        "raw_response_hashes": sorted({r["response_sha256"] for r in manager.records if "data.3dbag.nl" in r.get("url", "") and r.get("response_sha256")}),
    }


def _format_metric(value: Any, digits: int = 1, unit: str = "") -> str:
    if value is None:
        return "未知"
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return "未知"
        return f"{float(value):,.{digits}f}{unit}"
    return str(value)


def _zone_by_id(facts: dict[str, Any], zone_id: str) -> dict[str, Any] | None:
    return next((zone for zone in facts.get("texture_zones", []) if zone.get("id") == zone_id), None)


def _zone_table_row(zone: dict[str, Any]) -> str:
    m = zone["metrics"]
    b = m["blocks"]
    s = m["streets"]
    buildings = m["buildings"]
    cov = buildings["coverage"]
    fsi = buildings["fsi"]
    short = b["short_edge_m"]
    long = b["long_edge_m"]
    area = b["area_m2"]
    spacing = s["typical_parallel_spacing"]
    spacing_label = "；".join(
        f"{_format_metric(item.get('median_m'), 1, ' m')}（軸 {_format_metric(item.get('axis_azimuth_deg'), 1, '°')}）"
        for item in spacing if item.get("median_m") is not None
    ) or "未知"
    if fsi.get("status") == "COMPUTED":
        fsi_label = f"{_format_metric(fsi.get('fsi'), 3)}；平均樓層 {_format_metric(fsi.get('average_floors'), 2)} 層"
    elif fsi.get("status") == "PARTIAL":
        fsi_label = f"高度覆蓋 {fsi.get('height_coverage_ratio', 0):.1%}／樓層用途覆蓋 {fsi.get('floor_height_coverage_ratio', 0):.1%}；子集 FSI {_format_metric(fsi.get('fsi_observed_subset'), 3)}、觀測平均樓層 {_format_metric(fsi.get('average_floors_observed_subset'), 2)} 層"
    else:
        fsi_label = "未知"
    peaks = ", ".join(f"{p['azimuth_deg']:.1f}°（與基地長軸差 {p['angle_to_site_long_axis_deg']:.1f}°）" for p in s["orientation"]["primary_peaks"]) or "未知"
    return "| {name} | {area_m2} | {blocks}/{complete} | {barea} | {short} | {long} | {intersections} / {density} | {spacing} | {peaks} | {gsi} | {fsi} | {wing} | {typology} |".format(
        name=zone["name_zh"],
        area_m2=_format_metric(m["window_area_m2"], 0, " m²"),
        blocks=b["total_blocks"], complete=b["complete_blocks"],
        barea=f"{_format_metric(area.get('median'), 0, ' m²')} [{_format_metric(area.get('p25'), 0)}, {_format_metric(area.get('p75'), 0)}]",
        short=f"{_format_metric(short.get('median'), 1, ' m')} [{_format_metric(short.get('p25'), 1)}, {_format_metric(short.get('p75'), 1)}]",
        long=f"{_format_metric(long.get('median'), 1, ' m')} [{_format_metric(long.get('p25'), 1)}, {_format_metric(long.get('p75'), 1)}]",
        intersections=s["intersection_count"],
        density=_format_metric(s["intersection_density_per_km2"], 1, " 個/km²"),
        spacing=spacing_label,
        peaks=peaks,
        gsi=_format_metric(cov.get("gsi"), 3),
        fsi=fsi_label,
        wing=f"{_format_metric(buildings['wing_depth_m'].get('median_m'), 1, ' m')}（n={buildings['wing_depth_m'].get('count', 0)}）",
        typology="未知" if buildings["dominant_typology"] == "UNKNOWN" else buildings["dominant_typology"],
    )


def _design_implications(facts: dict[str, Any]) -> list[str]:
    south = _zone_by_id(facts, "spangen_bospolder")
    port = _zone_by_id(facts, "m4h_port")
    dak = _zone_by_id(facts, "dakpark_vierhavensstraat")
    notes: list[str] = []
    if south:
        m = south["metrics"]
        short = m["blocks"]["short_edge_m"]
        if m["blocks"]["total_blocks"]:
            notes.append(
                f"Spangen／Bospolder 研究窗的街廓短邊中位數為 {_format_metric(short['median'], 1, ' m')}，P25–P75 為 {_format_metric(short['p25'], 1, '–')}{_format_metric(short['p75'], 1, ' m')}；若測試延續圍合街廓，可先以此量測帶建立生成器比較組，不把它當成規範。"
            )
        spacing = [item for item in m["streets"]["typical_parallel_spacing"] if item.get("median_m") is not None]
        if spacing:
            item = spacing[0]
            notes.append(
                f"南側道路主軸 {_format_metric(item['axis_azimuth_deg'], 1, '°')} 的平行街道最近間距中位數為 {_format_metric(item['median_m'], 1, ' m')}（樣本數 {item['samples_count']}）；可用同一間距指標檢視延續街道方案。"
            )
    if south and port:
        sm = south["metrics"]["buildings"]
        pm = port["metrics"]["buildings"]
        sgsi = sm["coverage"].get("gsi")
        pgsi = pm["coverage"].get("gsi")
        if sgsi is not None and pgsi is not None:
            notes.append(
                f"南側住宅窗 GSI 為 {_format_metric(sgsi, 3)}，M4H 港區窗為 {_format_metric(pgsi, 3)}；兩者差 {_format_metric(abs(sgsi - pgsi), 3)}。生成器可分別比較街廓圍合與大尺度廠房的地面占比。"
            )
        sw = sm["wing_depth_m"].get("median_m")
        pw = pm["wing_depth_m"].get("median_m")
        if sw is not None and pw is not None:
            notes.append(
                f"南側建物翼深中位數 {_format_metric(sw, 1, ' m')}，港區為 {_format_metric(pw, 1, ' m')}；若轉譯住宅量體，可把南側翼深作為尺度對照，並另保留港區量體類型。"
            )
    axis = facts["site"]["principal_axis"]["long_axis_azimuth_deg"]
    road_peaks = facts["boundary_and_alignments"]["road_orientation_peaks"]["primary_peaks"]
    if road_peaks:
        peak = road_peaks[0]
        notes.append(
            f"基地長軸為 {_format_metric(axis, 1, '°')}；外圍道路第一主峰為 {_format_metric(peak['azimuth_deg'], 1, '°')}，夾角 {_format_metric(peak['angle_to_site_long_axis_deg'], 1, '°')}。街道延續方案可把此對位差作為明確比較量。"
        )
    candidates = facts.get("continuation_street_candidates", [])
    if candidates:
        nearest = candidates[0]
        notes.append(
            f"最近的延續街道候選為「{nearest['name']}」，距基地邊界 {_format_metric(nearest['distance_to_site_m'], 1, ' m')}、方位 {_format_metric(nearest['azimuth_deg'], 1, '°')}、來向 {nearest['approach_side']}；候選線段可先作為生成器入口軸，仍需設計者確認。"
        )
    else:
        notes.append("目前幾何延伸條件未找到延續街道候選；這表示 OSM 線形在本次搜尋距離／方向門檻下未通過，不代表現地沒有可連接道路。")
    dak_edge = facts["boundary_and_alignments"]["dakpark_edge"]
    park_peaks = dak_edge["orientation"]["primary_peaks"]
    if park_peaks:
        dak_elevation_status_zh = "已計算" if dak_edge["elevation_status"] == "COMPUTED_FROM_PAIRED_OSM_ELE_TAGS" else "資料不足"
        notes.append(
            f"Dakpark 邊緣主峰 {_format_metric(park_peaks[0]['azimuth_deg'], 1, '°')}，與基地長軸差 {_format_metric(park_peaks[0]['angle_to_site_long_axis_deg'], 1, '°')}；公園與鄰接道路的高差為 {_format_metric(dak_edge['height_difference_m'], 2, ' m')}（{dak_elevation_status_zh}），不得以未配對的高程推論剖面。"
        )
    else:
        notes.append("Dakpark 邊緣方位未能從有效邊線計算；其高差目前未知，需取得公園與鄰接地坪可配對的高程資料後再比較剖面。")
    if len(notes) < 5:
        notes.append("本次資料缺漏或樣本不足之指標保留為未知；生成器應將其視為待補證據，不應轉成零值或預設參數。")
    return notes[:8]


def build_context_summary_zh(facts: dict[str, Any]) -> str:
    lines = [
        "# M4H 基地周邊的脈絡形態閱讀",
        "",
        f"資料擷取／產製時間：{facts.get('generated_at_utc', '未知')}。",
        "",
        "本文件提供可追溯的形態量測，供設計者與生成器讀取。研究窗是比較範圍，分類門檻是探索性方法，不構成規劃標準；缺值以「未知」表示。",
        "",
        "## 紋理區量測",
        "",
        "| 紋理區 | 研究窗面積 | 街廓數／完整數 | 街廓面積中位數 [P25, P75] | 短邊中位數 [P25, P75] | 長邊中位數 [P25, P75] | 交叉口數／密度 | 平行街間距 | 道路兩主峰 | GSI | FSI／平均樓層 | 翼深中位數 | 主導類型 |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|---:|---|---:|---|",
    ]
    lines.extend(_zone_table_row(zone) for zone in facts.get("texture_zones", []))
    lines.extend([
        "",
        "## 邊界與對位",
        "",
        f"基地長軸：{_format_metric(facts['site']['principal_axis']['long_axis_azimuth_deg'], 1, '°')}（北起順時針、無向線 0–180°）；長度 {_format_metric(facts['site']['principal_axis']['long_axis_length_m'], 1, ' m')}。",
    ])
    for road in facts["boundary_and_alignments"]["named_roads"]:
        road_status = "已找到" if road["status"] == "FOUND" else "查詢範圍內未找到"
        lines.append(f"- {road['name']}：{_format_metric(road.get('azimuth_deg'), 1, '°')}；相對基地長軸 {_format_metric(road.get('angle_to_site_long_axis_deg'), 1, '°')}；{road_status}。")
    for label, key in (("港池岸線", "harbor_water_edge_orientation"), ("碼頭／岸壁", "pier_quay_orientation"), ("鐵道", "railway_orientation")):
        peaks = facts["boundary_and_alignments"][key]["primary_peaks"]
        angles = "、".join(f"{item['azimuth_deg']:.1f}°（夾角 {item['angle_to_site_long_axis_deg']:.1f}°）" for item in peaks) or "未知"
        lines.append(f"- {label}主方位：{angles}。")
    dak = facts["boundary_and_alignments"]["dakpark_edge"]
    park_angles = "、".join(f"{item['azimuth_deg']:.1f}°" for item in dak["orientation"]["primary_peaks"]) or "未知"
    elevation_status_zh = "已計算" if dak["elevation_status"] == "COMPUTED_FROM_PAIRED_OSM_ELE_TAGS" else "資料不足"
    lines.append(f"- Dakpark 邊緣主方位：{park_angles}；公園與鄰接道路高差：{_format_metric(dak.get('height_difference_m'), 2, ' m')}（{elevation_status_zh}；公園 ele 標籤 {dak['park_ele_tag_count']} 筆、鄰接道路 {dak['adjacent_ground_ele_tag_count']} 筆）。")
    lines.extend(["", "## 基地四側鄰接與最近接點", "", "| 邊側 | 鄰接紋理 | 最近街道 | 至基地邊界 | 最近交叉口距離 |", "|---|---|---|---:|---:|"])
    for side in facts.get("site_adjacencies", []):
        street = side.get("nearest_street") or {}
        junction = side.get("nearest_junction") or {}
        nearest_street_label = street.get("name") or _highway_class_label_zh(street.get("highway")) if street else "未知"
        lines.append(
            f"| {side['side']} | {'未知' if side['adjacent_texture'] == 'UNKNOWN' else side['adjacent_texture']} | {nearest_street_label} | {_format_metric(street.get('distance_m'), 1, ' m')} | {_format_metric(junction.get('distance_m'), 1, ' m')} |"
        )
    lines.extend(["", "## 延續街道候選", ""])
    candidates = facts.get("continuation_street_candidates", [])
    if candidates:
        for item in candidates:
            lines.append(
                f"- {item['name']}（{_highway_class_label_zh(item['highway'])}）：來向 {item['approach_side']}，方位 {_format_metric(item['azimuth_deg'], 1, '°')}，距基地 {_format_metric(item['distance_to_site_m'], 1, ' m')}，方向偏差 {_format_metric(item['direction_alignment_deg'], 1, '°')}。這是線形延伸候選，不代表已核定街道。"
            )
    else:
        lines.append("本次資料下沒有符合距離與方向條件的線形延續候選。")
    lines.extend(["", "## 對設計的意涵", ""])
    for index, note in enumerate(_design_implications(facts), start=1):
        lines.append(f"{index}. {note}")
    lines.extend([
        "",
        "## 判讀方法與限制",
        "",
        "- 街廓以研究窗扣除水面後，使用 OSM highway 線與 waterway 線切分；水面邊界作為街廓邊界。面積小於 100 m² 的碎片排除。完整街廓指其邊界不接觸研究窗外框。",
        "- 道路方向以 5° 方位直方圖、線長加權及循環平滑取前兩峰；街道間距取主峰方向 ±15°、距離 20–350 m 內的最近平行道路中心線距離中位數。交叉口以幾何 noding 後 degree ≥3 的節點計算；跨橋／隧道標籤依 OSM 資料可用性排除。",
        "- GSI = 建築足跡聯集面積 ÷（研究窗面積 − 水域面積）。翼深是建物最小外接矩形短邊中位數，排除小於 50 m² 量體。",
        "- FSI = 3DBAG 有效建物高度換算之樓地板面積 ÷ 陸地面積。住宅每層 3.0 m、工業每層 5.0 m。完整值要求高度足跡覆蓋 100%；部分覆蓋只列子集觀察值，不補估缺值。",
        "- 主導類型使用 `method_parameters.typology_rule_version` 所列探索性規則；分類是描述性工具，不是 AI 建議或設計決策。",
        "- 南側住宅窗由抓取範圍內、距基地不超過 1,500 m 且位於基地質心以南的 OSM landuse=residential 多邊形聯集；Spangen／Bospolder 僅作住宅紋理對照名稱，不代表已取得行政界線。其他紋理區是明示研究窗，不是法定行政邊界。研究範圍為基地幾何外推 1,500 m 的矩形；圖面另以基地中心 2,000 m × 2,000 m 視窗呈現。所有方位角為北起順時針，線向無方向，採 0–180°。",
        "",
        "## 資料來源與請求紀錄",
        "",
        "完整查詢字串、URL、時間、HTTP 狀態、SHA-256、原始回應路徑與快取驗證紀錄均列於同目錄 `context-facts.json` 的 `request_log`。實際請求與重試如下：",
        "",
        "| 次數 | 時間 | 方法 | URL | 狀態 | 回應 SHA-256 | 結果 |",
        "|---:|---|---|---|---:|---|---|",
    ])
    for i, rec in enumerate(facts.get("request_log", []), start=1):
        made = "網路請求" if rec.get("request_made") else "雜湊核對後重用快取"
        usage_labels = {
            "USED_FOR_FINAL_MEASUREMENTS": "用於最終量測",
            "USED_FOR_SOURCE_METADATA": "用於來源中繼資料",
            "EXCLUDED_FROM_FINAL_METRICS_DUPLICATE_IDS": "未納入量測（未排序頁跨頁重複）",
        }
        method = "快取" if rec.get("method") == "CACHE" else rec.get("method", "快取")
        status = rec.get("status_code") if rec.get("status_code") is not None else "失敗"
        response_hash = rec.get("response_sha256") or "無"
        usage = usage_labels.get(rec.get("result_usage"), rec.get("result_usage", "未分類"))
        error_note = "；回應錯誤詳情見 JSON" if rec.get("error") or rec.get("validation_error") else ""
        retry_note = f"；相同查詢第 {rec['attempt_number']} 次" if rec.get("request_made") and rec.get("attempt_number", 1) > 1 else ""
        lines.append(
            f"| {rec.get('request_number', i)} | {rec.get('request_time_utc', '未知')} | {method} | `{rec.get('url', '未知')}` | {status} | `{response_hash}` | {made}{retry_note}；{usage}{error_note} |"
        )
    page_audit = facts.get("acquisition_status", {}).get("previous_unordered_3dbag_page_audit", {})
    if page_audit.get("duplicate_row_count", 0):
        lines.extend([
            "",
            f"- 分頁完整性修正：首次 3DBAG 未排序分頁共 {page_audit['page_count']} 頁、回傳 {page_audit['response_row_count']:,} 列，但只有 {page_audit['unique_feature_id_count']:,} 個唯一識別碼，重複 {page_audit['duplicate_row_count']:,} 列；這些回應保留稽核但排除量測。最終改以 `fid A` 排序，取得 {facts['acquisition_status']['three_db_ag'].get('pagination_unique_feature_count', 0):,} 筆唯一建物。",
        ])
    lines.extend([
        f"- 請求治理：累計 {facts['acquisition_status'].get('network_request_count', 0)}/{facts['acquisition_status'].get('network_request_limit', MAX_REQUESTS)} 次；請求間隔至少 {MIN_REQUEST_INTERVAL_S:.0f} 秒；遇 429／504 等待 {RETRY_WAIT_S} 秒；同一查詢最多 3 次後縮小範圍。",
    ])
    lines.extend([
        "",
        "- OpenStreetMap 資料：Overpass API 唯讀查詢；標示 © OpenStreetMap contributors，ODbL 1.0。",
        "- 3DBAG：僅在取得 3DBAG 高度時使用指定 WFS；服務授權狀態列於 `context-facts.json`。",
        "- 本摘要屬探索性上下文量測，不採納或變更基地邊界、限制或設計決策。",
        "",
    ])
    return "\n".join(lines)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                pass
    raise RuntimeError("找不到可輸出繁體中文的本機字型")


def _pixel(point: Sequence[float], view: Polygon, map_rect: tuple[int, int, int, int]) -> tuple[float, float]:
    left, top, width, height = map_rect
    minx, miny, maxx, maxy = view.bounds
    x = left + (float(point[0]) - minx) / (maxx - minx) * width
    y = top + (maxy - float(point[1])) / (maxy - miny) * height
    return x, y


def _draw_line_geom(draw: ImageDraw.ImageDraw, geom: Any, view: Polygon, map_rect: tuple[int, int, int, int], fill, width: int = 2) -> None:
    try:
        clipped = geom.intersection(view)
    except Exception:
        return
    for line in _line_parts(clipped):
        points = [_pixel(coord, view, map_rect) for coord in line.coords]
        if len(points) >= 2:
            draw.line(points, fill=fill, width=width, joint="curve")


def _draw_polygon_geom(draw: ImageDraw.ImageDraw, geom: Any, view: Polygon, map_rect: tuple[int, int, int, int], fill, background) -> None:
    try:
        clipped = geom.intersection(view)
    except Exception:
        return
    for polygon in _polygon_parts(clipped):
        exterior = [_pixel(coord, view, map_rect) for coord in polygon.exterior.coords]
        draw.polygon(exterior, fill=fill)
        for ring in polygon.interiors:
            hole = [_pixel(coord, view, map_rect) for coord in ring.coords]
            draw.polygon(hole, fill=background)


def _draw_dashed_boundary(draw: ImageDraw.ImageDraw, geom: Any, view: Polygon, map_rect: tuple[int, int, int, int], fill, width: int = 3) -> None:
    boundary = geom.boundary if isinstance(geom, (Polygon, MultiPolygon)) else geom
    try:
        clipped_boundary = boundary.intersection(view)
    except Exception:
        return
    for line in _line_parts(clipped_boundary):
        pts = [_pixel(coord, view, map_rect) for coord in line.coords]
        for start, end in zip(pts, pts[1:]):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy)
            if length <= 0:
                continue
            step = 22.0
            dash = 13.0
            pos = 0.0
            while pos < length:
                stop = min(pos + dash, length)
                a = (start[0] + dx * pos / length, start[1] + dy * pos / length)
                b = (start[0] + dx * stop / length, start[1] + dy * stop / length)
                draw.line([a, b], fill=fill, width=width)
                pos += step


def _draw_arrow(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float], fill, width: int = 4) -> None:
    draw.line([start, end], fill=fill, width=width)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return
    ux, uy = dx / length, dy / length
    size = 13.0
    left = (end[0] - ux * size - uy * size * 0.6, end[1] - uy * size + ux * size * 0.6)
    right = (end[0] - ux * size + uy * size * 0.6, end[1] - uy * size - ux * size * 0.6)
    draw.polygon([end, left, right], fill=fill)


ZONE_COLORS = ["#cf554c", "#7052a2", "#178774", "#c58b1d", "#2878a5"]
ZONE_DISPLAY_LABELS_ZH = {
    "spangen_bospolder": "南側住宅區（Spangen／Bospolder）",
    "m4h_port": "M4H 港區與港池",
    "dakpark_vierhavensstraat": "Dakpark／Vierhavensstraat",
    "delfshaven": "Delfshaven 命名區",
    "oud_mathenesse": "Oud-Mathenesse 命名區",
}


def _zone_display_label_zh(zone: dict[str, Any]) -> str:
    return ZONE_DISPLAY_LABELS_ZH.get(zone.get("id"), zone.get("name_zh", "紋理區"))


HIGHWAY_CLASS_LABELS_ZH = {
    "primary": "主要道路",
    "primary_link": "主要道路匝道",
    "secondary": "次要道路",
    "secondary_link": "次要道路匝道",
    "tertiary": "第三級道路",
    "tertiary_link": "第三級道路匝道",
    "unclassified": "未分類道路",
    "residential": "住宅道路",
    "living_street": "生活街道",
}


def _highway_class_label_zh(value: Any) -> str:
    return HIGHWAY_CLASS_LABELS_ZH.get(str(value or "").casefold(), "道路類型未知")


def _view_for_site(site: Polygon) -> Polygon:
    center = site.centroid
    return box(center.x - 1000.0, center.y - 1000.0, center.x + 1000.0, center.y + 1000.0)


def _prepare_map_canvas(title: str, site: Polygon) -> tuple[Image.Image, ImageDraw.ImageDraw, Polygon, tuple[int, int, int, int], ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    image = Image.new("RGB", (1600, 1420), "#ffffff")
    draw = ImageDraw.Draw(image)
    view = _view_for_site(site)
    map_rect = (70, 150, 1120, 1120)
    draw.text((70, 42), title, font=_load_font(36), fill="#18212a")
    draw.text((70, 96), "研究範圍：基地中心 2,000 m × 2,000 m；座標 EPSG:28992", font=_load_font(21), fill="#59636e")
    return image, draw, view, map_rect, _load_font(22), _load_font(18)


def _draw_context_base(draw: ImageDraw.ImageDraw, view: Polygon, map_rect: tuple[int, int, int, int], features: Sequence[dict[str, Any]], *, roads: bool = True) -> None:
    bg = "#ffffff"
    for feature in _features_on_layer(features, "water"):
        _draw_polygon_geom(draw, _feature_geometry(feature), view, map_rect, "#9ed7ed", bg)
    for feature in _features_on_layer(features, "park"):
        _draw_polygon_geom(draw, _feature_geometry(feature), view, map_rect, "#d9edcf", bg)
    for feature in _features_on_layer(features, "building"):
        _draw_polygon_geom(draw, _feature_geometry(feature), view, map_rect, "#1e2429", bg)
    if roads:
        for feature in _features_on_layer(features, "highway"):
            _draw_line_geom(draw, _feature_geometry(feature), view, map_rect, "#d8dde1", 2)
    for feature in _features_on_layer(features, "railway"):
        _draw_line_geom(draw, _feature_geometry(feature), view, map_rect, "#7f7785", 2)


def _draw_scale_and_north(draw: ImageDraw.ImageDraw, map_rect: tuple[int, int, int, int], view: Polygon, font: ImageFont.FreeTypeFont) -> None:
    left, top, width, height = map_rect
    scale_px = width * 200.0 / (view.bounds[2] - view.bounds[0])
    sx, sy = left + 34, top + height - 36
    draw.line([(sx, sy), (sx + scale_px, sy)], fill="#1e252b", width=6)
    draw.line([(sx, sy - 8), (sx, sy + 8)], fill="#1e252b", width=3)
    draw.line([(sx + scale_px, sy - 8), (sx + scale_px, sy + 8)], fill="#1e252b", width=3)
    draw.text((sx, sy + 10), "0", font=font, fill="#1e252b")
    draw.text((sx + scale_px - 14, sy + 10), "200 m", font=font, fill="#1e252b")
    ax, ay = left + width - 54, top + 94
    draw.rounded_rectangle((ax - 34, ay - 40, ax + 34, ay + 76), radius=8, fill="#ffffff", outline="#17212b", width=2)
    draw.text((ax - 12, ay - 34), "北", font=font, fill="#17212b")
    _draw_arrow(draw, (ax, ay + 61), (ax, ay + 4), "#17212b", 5)


def render_figure_ground_zh(
    output_path: Path,
    site_facts: dict[str, Any],
    features: Sequence[dict[str, Any]],
    facts: dict[str, Any],
) -> None:
    site = shape(site_facts["geometry"]["site"])
    image, draw, view, map_rect, font, small = _prepare_map_canvas("M4H 周邊都市形態｜圖底圖", site)
    _draw_context_base(draw, view, map_rect, features, roads=False)
    for index, zone in enumerate(facts.get("texture_zones", [])):
        zone_geom = shape(zone["window_geometry_epsg28992"])
        color = ZONE_COLORS[index % len(ZONE_COLORS)]
        _draw_dashed_boundary(draw, zone_geom, view, map_rect, color, 3)
        center = zone_geom.representative_point()
        xy = _pixel((center.x, center.y), view, map_rect)
        if view.buffer(0).covers(Point(center.x, center.y)):
            label = _zone_display_label_zh(zone)
            text_width = draw.textbbox((0, 0), label, font=small)[2]
            label_x = min(xy[0] + 6, map_rect[0] + map_rect[2] - text_width - 6)
            label_y = min(max(xy[1] + 6, map_rect[1] + 4), map_rect[1] + map_rect[3] - 26)
            draw.text((label_x, label_y), label, font=small, fill=color, stroke_width=2, stroke_fill="#ffffff")
    _draw_line_geom(draw, shape(site_facts["geometry"]["site"]).boundary, view, map_rect, "#d52f36", 6)
    _draw_scale_and_north(draw, map_rect, view, font)
    left, top, width, height = map_rect
    legend_x = left + width + 45
    draw.text((legend_x, top + 10), "圖例", font=_load_font(25), fill="#18212a")
    legend = [
        ("#1e2429", "建築量體"),
        ("#ffffff", "空白／街道空間"),
        ("#9ed7ed", "水域"),
        ("#d9edcf", "公園"),
        ("#d52f36", "基地輪廓"),
    ]
    y = top + 62
    for color, label in legend:
        draw.rectangle((legend_x, y, legend_x + 28, y + 22), fill=color, outline="#6a737b")
        draw.text((legend_x + 40, y - 3), label, font=small, fill="#27323b")
        y += 40
    y += 12
    draw.text((legend_x, y), "紋理區研究窗", font=_load_font(22), fill="#18212a")
    y += 34
    for index, zone in enumerate(facts.get("texture_zones", [])):
        color = ZONE_COLORS[index % len(ZONE_COLORS)]
        draw.line([(legend_x, y + 10), (legend_x + 34, y + 10)], fill=color, width=3)
        draw.text((legend_x + 43, y), _zone_display_label_zh(zone), font=small, fill="#27323b")
        y += 34
    draw.text((legend_x, top + height - 8), "OSM 建物／水域／公園；紅線依基地事實檔。", font=small, fill="#59636e")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)


def render_alignments_zh(
    output_path: Path,
    site_facts: dict[str, Any],
    features: Sequence[dict[str, Any]],
    facts: dict[str, Any],
) -> None:
    site = shape(site_facts["geometry"]["site"])
    image, draw, view, map_rect, font, small = _prepare_map_canvas("M4H 周邊都市形態｜主要軸線與延續候選", site)
    _draw_context_base(draw, view, map_rect, features, roads=True)
    for index, zone in enumerate(facts.get("texture_zones", [])):
        geom = shape(zone["window_geometry_epsg28992"])
        _draw_dashed_boundary(draw, geom, view, map_rect, ZONE_COLORS[index % len(ZONE_COLORS)], 2)

    main_colors = {"Keileweg": "#df7b2c", "Vierhavensstraat": "#23779a", "Marconistraat": "#8c55a7"}
    for feature in _features_on_layer(features, "highway"):
        name = str(feature.get("tags", {}).get("name", ""))
        for requested, color in main_colors.items():
            if requested.casefold() in name.casefold():
                _draw_line_geom(draw, _feature_geometry(feature), view, map_rect, color, 5)
    for feature in _features_on_layer(features, "harbor_structure"):
        _draw_line_geom(draw, _feature_geometry(feature), view, map_rect, "#168b9a", 4)

    dak_geom = facts["boundary_and_alignments"]["dakpark_edge"].get("geometry_epsg28992")
    if dak_geom:
        _draw_line_geom(draw, shape(dak_geom).boundary, view, map_rect, "#4c9e42", 4)
    _draw_line_geom(draw, site.boundary, view, map_rect, "#d52f36", 6)

    axis_segment = facts["site"]["principal_axis"].get("long_axis_segment")
    if axis_segment:
        p1 = _pixel(axis_segment[0], view, map_rect)
        p2 = _pixel(axis_segment[1], view, map_rect)
        _draw_arrow(draw, p1, p2, "#2157a3", 4)
    for candidate in facts.get("continuation_street_candidates", []):
        line = candidate.get("extension_line", [])
        if len(line) == 2:
            p1, p2 = _pixel(line[0], view, map_rect), _pixel(line[1], view, map_rect)
            draw.line([p1, p2], fill="#ef8b22", width=5)
            _draw_arrow(draw, p1, p2, "#ef8b22", 4)

    _draw_scale_and_north(draw, map_rect, view, font)
    left, top, width, _ = map_rect
    tx = left + width + 45
    draw.text((tx, top + 10), "方位角（北起順時針）", font=_load_font(24), fill="#18212a")
    y = top + 52
    site_az = facts["site"]["principal_axis"]["long_axis_azimuth_deg"]
    draw.text((tx, y), f"基地長軸 {site_az:.1f}°", font=small, fill="#2157a3")
    y += 34
    for road in facts["boundary_and_alignments"]["named_roads"]:
        color = main_colors[road["name"]]
        label = f"{road['name']} {_format_metric(road.get('azimuth_deg'), 1, '°')}"
        draw.line([(tx, y + 12), (tx + 32, y + 12)], fill=color, width=5)
        draw.text((tx + 42, y), label, font=small, fill="#27323b")
        y += 34
    for idx, peak in enumerate(facts["boundary_and_alignments"]["road_orientation_peaks"]["primary_peaks"], start=1):
        draw.line([(tx, y + 12), (tx + 32, y + 12)], fill="#d25a40" if idx == 1 else "#c59325", width=4)
        draw.text((tx + 42, y), f"道路主峰 {idx}：{peak['azimuth_deg']:.1f}°", font=small, fill="#27323b")
        y += 34
    y += 12
    draw.text((tx, y), "圖面線型", font=_load_font(22), fill="#18212a")
    y += 32
    for color, label in (("#168b9a", "碼頭／岸壁"), ("#4c9e42", "Dakpark 邊緣"), ("#d52f36", "基地邊界"), ("#ef8b22", "延續街道候選")):
        draw.line([(tx, y + 10), (tx + 32, y + 10)], fill=color, width=4)
        draw.text((tx + 42, y), label, font=small, fill="#27323b")
        y += 30
    y += 10
    candidate_font = _load_font(16)
    for index, candidate in enumerate(facts.get("continuation_street_candidates", []), start=1):
        candidate_name = candidate["name"].replace("Galileïstraat", "Galileistraat")
        draw.text((tx, y), f"候選 {index}：{candidate_name}", font=small, fill="#a85d10")
        draw.text((tx + 22, y + 21), f"方位 {candidate['azimuth_deg']:.1f}°", font=candidate_font, fill="#a85d10")
        y += 44
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)


def run_ctx1(
    site_facts_path: Path,
    output_dir: Path,
    raw_dir: Path,
    *,
    refresh: bool = False,
    skip_3dbag: bool = False,
) -> dict[str, Any]:
    site_bytes = site_facts_path.read_bytes()
    site_facts = json.loads(site_bytes.decode("utf-8"))
    site = shape(site_facts["geometry"]["site"])
    bbox_28992 = _query_bbox_28992(site, margin_m=1500.0)
    manager = RequestManager(raw_dir, max_requests=MAX_REQUESTS, refresh=refresh)

    overpass_error = None
    try:
        elements, osm_complete = _overpass_chunk(manager, bbox_28992)
    except RequestLimitError as exc:
        elements, osm_complete = [], False
        overpass_error = str(exc)
    osm_features = parse_overpass_payload({"elements": elements})

    height_features: list[dict[str, Any]] = []
    if skip_3dbag:
        bag_status: dict[str, Any] = {"status": "NOT_REQUESTED", "reason": "命令列明確略過 3DBAG WFS"}
    elif not osm_complete and not elements:
        bag_status = {"status": "NOT_REQUESTED", "reason": "Overpass 未取得可用資料，避免在主資料缺失時擴大請求"}
    else:
        try:
            height_features, bag_status = fetch_3dbag_heights(manager, bbox_28992)
        except RequestLimitError as exc:
            bag_status = {"status": "UNKNOWN", "reason": str(exc), "feature_type": None}

    actual_request_history = []
    request_log_path = raw_dir / "request-log.jsonl"
    if request_log_path.exists():
        with request_log_path.open("r", encoding="utf-8") as log:
            for line in log:
                try:
                    actual_request_history.append(json.loads(line))
                except json.JSONDecodeError:
                    actual_request_history.append({"request_made": True, "error": "請求紀錄 JSONL 含無法解析列"})
    live_records_by_number = {
        r.get("request_number"): r
        for r in manager.records
        if r.get("request_made") and r.get("request_number") is not None
    }
    actual_request_history = [
        {**record, **live_records_by_number.get(record.get("request_number"), {})}
        for record in actual_request_history
    ]
    query_attempts: dict[str, int] = {}
    for record in actual_request_history:
        query_hash = str(record.get("query_sha256") or "")
        query_attempts[query_hash] = query_attempts.get(query_hash, 0) + 1
        record["attempt_number"] = query_attempts[query_hash]
        record["is_retry"] = record["attempt_number"] > 1
    unordered_page_audit = _audit_unordered_3dbag_pages(actual_request_history)
    for record in actual_request_history:
        query = str(record.get("query", ""))
        url = str(record.get("url", ""))
        if "data.3dbag.nl" in url and "GetFeature" in query and "sortBy=" not in query:
            record["result_usage"] = unordered_page_audit["status"]
            record["result_usage_note"] = "未指定穩定排序的舊分頁有跨頁重複；原始回應保留於稽核，但已排除最終量測。"
        elif "data.3dbag.nl" in url and "GetFeature" in query and "sortBy=fid A" in query:
            record["result_usage"] = "USED_FOR_FINAL_MEASUREMENTS"
        elif "data.3dbag.nl" in url and "GetCapabilities" in query:
            record["result_usage"] = "USED_FOR_SOURCE_METADATA"
        elif "overpass-api.de" in url:
            record["result_usage"] = "USED_FOR_FINAL_MEASUREMENTS"
    cache_reuse_events = [r for r in manager.records if not r.get("request_made")]
    for record in cache_reuse_events:
        query = str(record.get("query", ""))
        record["result_usage"] = "USED_FOR_FINAL_MEASUREMENTS" if "sortBy=fid A" in query or "overpass-api.de" in str(record.get("url", "")) else "USED_FOR_SOURCE_METADATA"
    complete_request_history = actual_request_history + cache_reuse_events
    acquisition_status = {
        "osm": "COMPLETE" if osm_complete else "PARTIAL_OR_FAILED",
        "osm_element_count": len(elements),
        "osm_feature_count": len(osm_features),
        "osm_error": overpass_error,
        "three_db_ag": bag_status,
        "network_request_count": manager.request_count,
        "network_request_count_this_run": manager.request_count - manager.request_count_at_start,
        "network_request_limit": MAX_REQUESTS,
        "request_policy": {
            "minimum_interval_seconds": MIN_REQUEST_INTERVAL_S,
            "wait_after_http_429_or_504_seconds": RETRY_WAIT_S,
            "max_attempts_per_query_before_chunk_split": 3,
            "network_request_cap_is_cumulative_in_raw_log": True,
        },
        "raw_response_directory": str(raw_dir),
        "previous_unordered_3dbag_page_audit": unordered_page_audit,
    }
    input_hashes = {"site_facts_sha256": sha256_bytes(site_bytes)}
    facts = build_context_facts(
        site_facts,
        osm_features,
        complete_request_history,
        height_features=height_features,
        acquisition_status=acquisition_status,
        source_hashes=input_hashes,
    )
    facts["sources"] = [
        {
            "dataset": "OpenStreetMap",
            "endpoint": OVERPASS_URL,
            "retrieved_at_utc": next((r.get("original_retrieved_at_utc") or r.get("request_time_utc") for r in manager.records if "overpass-api.de" in r.get("url", "") and r.get("response_sha256")), None),
            "license": "Open Database License 1.0 (ODbL-1.0)",
            "attribution": "© OpenStreetMap contributors",
            "raw_response_hashes": sorted({r["response_sha256"] for r in manager.records if "overpass-api.de" in r.get("url", "") and r.get("response_sha256")}),
            "query_and_request_records": "request_log",
        },
        {
            "dataset": "3DBAG",
            "endpoint": THREEDBAG_URL,
            "status": bag_status.get("status"),
            "license_terms_from_capabilities": bag_status.get("license_terms") or [],
            "license_status": "WFS GetCapabilities 原文條款已擷取" if bag_status.get("license_terms") else "GetCapabilities 未回傳授權條款；請勿將此結果當成已核可重用授權",
            "raw_response_hashes": bag_status.get("raw_response_hashes", []),
            "query_and_request_records": "request_log",
        },
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "context-facts.json"
    json_path.write_text(json.dumps(facts, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output_dir / "context-summary-zh.md").write_text(build_context_summary_zh(facts), encoding="utf-8")
    all_features = osm_features + _project_site_features(site_facts) + height_features
    render_figure_ground_zh(output_dir / "figure-ground-zh.png", site_facts, all_features, facts)
    render_alignments_zh(output_dir / "alignments-zh.png", site_facts, all_features, facts)
    manifest = {
        "generated_at_utc": facts["generated_at_utc"],
        "input_sha256": input_hashes,
        "outputs": {},
        "network_requests": manager.request_count,
        "request_log_path": str(raw_dir / "request-log.jsonl"),
    }
    for name in ("context-facts.json", "figure-ground-zh.png", "alignments-zh.png", "context-summary-zh.md"):
        path = output_dir / name
        manifest["outputs"][name] = {"size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
        if path.stat().st_size >= 2 * 1024 * 1024:
            raise RuntimeError(f"輸出超過 2 MB：{name} ({path.stat().st_size} bytes)")
    (output_dir / "integrity-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"facts": facts, "manifest": manifest, "output_dir": output_dir}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="讀取並量測 M4H 周邊都市形態（唯讀）")
    parser.add_argument("--site-facts", type=Path, default=DEFAULT_SITE_FACTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--refresh", action="store_true", help="忽略已雜湊驗證的快取並重新請求")
    parser.add_argument("--skip-3dbag", action="store_true", help="略過可選的 3DBAG WFS 高度查詢")
    args = parser.parse_args(argv)
    result = run_ctx1(args.site_facts, args.output_dir, args.raw_dir, refresh=args.refresh, skip_3dbag=args.skip_3dbag)
    facts = result["facts"]
    print(f"輸出目錄：{result['output_dir']}")
    print(f"紋理區：{len(facts['texture_zones'])}；實際網路請求：{facts['acquisition_status']['network_request_count']}/{MAX_REQUESTS}")
    print(f"Overpass：{facts['acquisition_status']['osm']}；3DBAG：{facts['acquisition_status']['three_db_ag'].get('status')}")
    for name, record in result["manifest"]["outputs"].items():
        print(f"{name}: {record['size_bytes']} bytes sha256:{record['sha256']}")
    failures = [r for r in facts["request_log"] if r.get("request_made") and (r.get("status_code") != 200 or r.get("error") or r.get("validation_error"))]
    unused = [r for r in facts["request_log"] if r.get("request_made") and str(r.get("result_usage", "")).startswith("EXCLUDED")]
    print(f"HTTP／回應驗證失敗：{len(failures)}；因分頁資料品質而排除的舊請求：{len(unused)}（詳見 JSON／摘要）")
    return 0 if facts["acquisition_status"]["osm"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
