#!/usr/bin/env python3
"""Acquire the allowlisted read-only source snapshots for the KB4 case library.

The script writes immutable source responses with exclusive creation.  It does
not access project state or call a model/provider.  Morphometry is calculated
offline by ``precedent_morphometrics.py`` from the prepared, projected inputs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any
from urllib.parse import urlparse

import requests
from pyproj import CRS, Transformer
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping, shape
from shapely.ops import transform as transform_geometry, unary_union


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts/kb4-precedents"
RAW = ARTIFACTS / "raw"
OVERPASS = "https://overpass-api.de/api/interpreter"
THREE_DBAG_WFS = "https://data.3dbag.nl/api/BAG3D/wfs"
ALLOWLIST = {"overpass-api.de", "data.3dbag.nl"}
REQUEST_GAP_SECONDS = 2.1
RETRY_WAIT_SECONDS = 60
MAX_ATTEMPTS = 3


# Each AOI is a researcher-defined metric window around a named OSM object.
# The dimensions vary by case and are not claims about an official development
# boundary.  Netherlands windows use RD New; other windows use their local UTM.
CASE_SPECS: list[dict[str, Any]] = [
    {"slug": "borneo-sporenburg", "title_zh": "婆羅洲—斯波倫堡", "title_en": "Borneo-Sporenburg", "city": "Amsterdam", "country": "Netherlands", "group": "amsterdam", "crs": "EPSG:28992", "anchors": [("relation", 12009952), ("relation", 12009953)], "width_m": 480, "height_m": 250},
    {"slug": "java-eiland", "title_zh": "Java 島", "title_en": "Java-eiland", "city": "Amsterdam", "country": "Netherlands", "group": "amsterdam", "crs": "EPSG:28992", "anchors": [("relation", 12009955)], "width_m": 420, "height_m": 240},
    {"slug": "knsm-eiland", "title_zh": "KNSM 島", "title_en": "KNSM-eiland", "city": "Amsterdam", "country": "Netherlands", "group": "amsterdam", "crs": "EPSG:28992", "anchors": [("node", 8222700975)], "width_m": 410, "height_m": 240},
    {"slug": "ijburg-haveneiland", "title_zh": "IJburg Haveneiland", "title_en": "IJburg Haveneiland", "city": "Amsterdam", "country": "Netherlands", "group": "amsterdam", "crs": "EPSG:28992", "anchors": [("relation", 11091616)], "width_m": 500, "height_m": 320},
    {"slug": "kop-van-zuid-wilhelminapier", "title_zh": "Kop van Zuid—Wilhelminapier", "title_en": "Kop van Zuid / Wilhelminapier", "city": "Rotterdam", "country": "Netherlands", "group": "rotterdam", "crs": "EPSG:28992", "anchors": [("relation", 10459179)], "width_m": 420, "height_m": 250},
    {"slug": "katendrecht", "title_zh": "Katendrecht", "title_en": "Katendrecht", "city": "Rotterdam", "country": "Netherlands", "group": "rotterdam", "crs": "EPSG:28992", "anchors": [("relation", 13714901)], "width_m": 400, "height_m": 260},
    {"slug": "lloydkwartier", "title_zh": "Lloydkwartier", "title_en": "Lloydkwartier", "city": "Rotterdam", "country": "Netherlands", "group": "rotterdam", "crs": "EPSG:28992", "anchors": [("node", 6139747997)], "width_m": 320, "height_m": 240},
    {"slug": "spangen-justus-van-effen", "title_zh": "Spangen／Justus van Effen 區", "title_en": "Spangen / Justus van Effen area", "city": "Rotterdam", "country": "Netherlands", "group": "rotterdam", "crs": "EPSG:28992", "anchors": [("relation", 10459101)], "width_m": 400, "height_m": 280},
    {"slug": "funenpark", "title_zh": "Funenpark", "title_en": "Funenpark", "city": "Amsterdam", "country": "Netherlands", "group": "amsterdam", "crs": "EPSG:28992", "anchors": [("relation", 11958889)], "width_m": 300, "height_m": 220},
    {"slug": "hafencity-dalmannkai", "title_zh": "HafenCity／Dalmannkai", "title_en": "HafenCity / Dalmannkai", "city": "Hamburg", "country": "Germany", "group": "hamburg", "crs": "EPSG:25832", "anchors": [("way", 160378021)], "width_m": 380, "height_m": 240},
    {"slug": "vastra-hamnen", "title_zh": "Västra Hamnen", "title_en": "Västra Hamnen", "city": "Malmö", "country": "Sweden", "group": "malmo", "crs": "EPSG:32633", "anchors": [("relation", 3050114)], "width_m": 360, "height_m": 260},
    {"slug": "hammarby-sjostad", "title_zh": "Hammarby Sjöstad", "title_en": "Hammarby Sjöstad", "city": "Stockholm", "country": "Sweden", "group": "stockholm", "crs": "EPSG:32633", "anchors": [("node", 323238489)], "width_m": 450, "height_m": 300},
    {"slug": "nordhavn", "title_zh": "Nordhavn", "title_en": "Nordhavn", "city": "Copenhagen", "country": "Denmark", "group": "copenhagen", "crs": "EPSG:25832", "anchors": [("relation", 7669660)], "width_m": 440, "height_m": 270},
    {"slug": "vauban-freiburg", "title_zh": "Freiburg Vauban", "title_en": "Vauban", "city": "Freiburg", "country": "Germany", "group": "freiburg", "crs": "EPSG:25832", "anchors": [("relation", 86313)], "width_m": 350, "height_m": 250},
    {"slug": "barcelona-eixample", "title_zh": "Barcelona Eixample", "title_en": "Barcelona Eixample", "city": "Barcelona", "country": "Spain", "group": "barcelona", "crs": "EPSG:25831", "anchors": [("relation", 4127732)], "width_m": 420, "height_m": 300},
    {"slug": "amsterdam-oud-zuid", "title_zh": "Amsterdam Oud-Zuid", "title_en": "Amsterdam Oud-Zuid", "city": "Amsterdam", "country": "Netherlands", "group": "amsterdam", "crs": "EPSG:28992", "anchors": [("relation", 17933468)], "width_m": 400, "height_m": 260},
]


def utc_from_date_command() -> str:
    return subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()


class ReadOnlyClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Q5-KB4-morphology-precedents/1.0 (read-only research)"})
        self.last_request_end: dict[str, float] = {}
        self.requests: list[dict[str, Any]] = []
        self.receipt_path = ARTIFACTS / "http-request-receipts.jsonl"
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with self.receipt_path.open("a", encoding="utf-8"):
            pass

    def _append_receipt(self, value: dict[str, Any]) -> None:
        with self.receipt_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")

    def _wait_for_overpass_slot(self) -> None:
        for _ in range(15):
            try:
                resp = self.session.get("https://overpass-api.de/api/status", timeout=10)
                if resp.status_code == 200:
                    text = resp.text
                    match = re.search(r"Slot available after:[^,]+,\s*in\s*(\d+)\s*seconds", text)
                    if "0 slots available now" in text:
                        wait_sec = int(match.group(1)) + 3 if match else 25
                        time.sleep(wait_sec)
                        continue
                    break
            except Exception:
                break

    def get(self, url: str, *, params: dict[str, str] | None = None, data: dict[str, str] | None = None,
            attempt_limit: int | None = None) -> requests.Response:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWLIST:
            raise ValueError(f"network destination is not allowlisted: {url}")
        host = str(parsed.hostname)
        records: list[dict[str, Any]] = []
        max_attempts = MAX_ATTEMPTS if attempt_limit is None else min(MAX_ATTEMPTS, max(1, int(attempt_limit)))
        for attempt in range(1, max_attempts + 1):
            elapsed = time.monotonic() - self.last_request_end.get(host, 0.0)
            if elapsed < REQUEST_GAP_SECONDS:
                time.sleep(REQUEST_GAP_SECONDS - elapsed)
            if host == "overpass-api.de":
                self._wait_for_overpass_slot()
            started = utc_from_date_command()
            try:
                if data is not None:
                    response = self.session.post(url, data=data, timeout=120)
                else:
                    response = self.session.get(url, params=params, timeout=120)
            except requests.RequestException as exc:
                self.last_request_end[host] = time.monotonic()
                failure = {"attempt": attempt, "requested_at_utc": started, "transport_error": type(exc).__name__, "detail": str(exc)}
                records.append(failure)
                self._append_receipt({"url": url, "params": params, "request_data": data, **failure})
                self.requests.append({"url": url, "params": params, "request_data": data, "attempts": records})
                raise RuntimeError(f"read-only request outcome unavailable for {url}: {type(exc).__name__}") from exc
            self.last_request_end[host] = time.monotonic()
            item = {
                "attempt": attempt,
                "requested_at_utc": started,
                "completed_at_utc": utc_from_date_command(),
                "status_code": response.status_code,
                "response_bytes": len(response.content),
                "response_sha256": hashlib.sha256(response.content).hexdigest(),
            }
            records.append(item)
            if response.status_code == 200:
                self._append_receipt({"url": url, "params": params, "request_data": data, **item})
                self.requests.append({"url": url, "params": params, "request_data": data, "attempts": records})
                return response
            item["body_excerpt"] = response.text[:2000]
            # A gateway timeout is also retryable for this read-only acquisition:
            # the response may be transient even though it is not a rate-limit.
            if response.status_code not in (429, 500, 504) or attempt == max_attempts:
                self._append_receipt({"url": url, "params": params, "request_data": data, **item})
                self.requests.append({"url": url, "params": params, "request_data": data, "attempts": records})
                raise RuntimeError(f"HTTP {response.status_code} from allowlisted source: {url}")
            # Preserve the retryable response status and body excerpt in the
            # append-only receipt before waiting and trying again.
            self._append_receipt({"url": url, "params": params, "request_data": data, **item})
            time.sleep(RETRY_WAIT_SECONDS)
            if host == "overpass-api.de":
                self._wait_for_overpass_slot()
        raise AssertionError("unreachable request loop")


def load_anchor_index() -> dict[tuple[str, int], dict[str, Any]]:
    paths = [
        ARTIFACTS / "osm-name-anchors.json",
        ARTIFACTS / "osm-extra-anchors.json",
        ARTIFACTS / "osm-barcelona-anchors.json",
    ]
    index: dict[tuple[str, int], dict[str, Any]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
        if payload.get("remark"):
            raise ValueError(f"incomplete Overpass anchor response: {path}")
        for element in payload.get("elements", []):
            index[(element["type"], int(element["id"]))] = element
    return index


def build_study_areas(anchor_index: dict[tuple[str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    areas: list[dict[str, Any]] = []
    for spec in CASE_SPECS:
        anchor_points: list[tuple[float, float]] = []
        anchor_labels: list[dict[str, Any]] = []
        for object_type, object_id in spec["anchors"]:
            element = anchor_index.get((object_type, object_id))
            if element is None:
                raise ValueError(f"missing source OSM anchor {object_type}/{object_id} for {spec['slug']}")
            center = element.get("center") or element
            if center.get("lat") is None or center.get("lon") is None:
                raise ValueError(f"OSM anchor {object_type}/{object_id} has no observed coordinate")
            anchor_points.append((float(center["lon"]), float(center["lat"])))
            anchor_labels.append({"type": object_type, "id": object_id, "name": element.get("tags", {}).get("name")})
        anchor_lon = sum(point[0] for point in anchor_points) / len(anchor_points)
        anchor_lat = sum(point[1] for point in anchor_points) / len(anchor_points)
        forward = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_user_input(spec["crs"]), always_xy=True)
        inverse = Transformer.from_crs(CRS.from_user_input(spec["crs"]), CRS.from_epsg(4326), always_xy=True)
        anchor_x, anchor_y = forward.transform(anchor_lon, anchor_lat)
        half_w = spec["width_m"] / 2
        half_h = spec["height_m"] / 2
        polygon = Polygon([
            (anchor_x - half_w, anchor_y - half_h),
            (anchor_x + half_w, anchor_y - half_h),
            (anchor_x + half_w, anchor_y + half_h),
            (anchor_x - half_w, anchor_y + half_h),
            (anchor_x - half_w, anchor_y - half_h),
        ])
        if not polygon.is_valid or polygon.area < 50_000 or polygon.area > 200_000:
            raise ValueError(f"research area outside 5-20 ha or invalid for {spec['slug']}: {polygon.area}")
        projected_to_wgs84 = transform_geometry(inverse.transform, polygon)
        bounds = projected_to_wgs84.bounds
        west, south, east, north = bounds
        areas.append({
            **spec,
            "anchor": {"lon": anchor_lon, "lat": anchor_lat, "x": anchor_x, "y": anchor_y, "osm_objects": anchor_labels},
            "area_m2": polygon.area,
            "area_ha": polygon.area / 10_000,
            "geometry": mapping(polygon),
            "geometry_wgs84": mapping(projected_to_wgs84),
            "osm_bbox_s_w_n_e": [south, west, north, east],
            "boundary_note_zh": f"以 OSM 地名物件中心作錨點，在 {spec['crs']} 中向四周量取 {spec['width_m']} m × {spec['height_m']} m 矩形；這是研究窗，不代表歷史開發案或法定邊界。",
        })
    return areas


def make_overpass_query(areas: list[dict[str, Any]]) -> str:
    boxes = sorted({tuple(round(float(v), 7) for v in row["osm_bbox_s_w_n_e"]) for row in areas})
    clauses: list[str] = []
    for south, west, north, east in boxes:
        box = f"({south},{west},{north},{east})"
        clauses.extend([
            f'way["building"]{box};',
            f'relation["building"]{box};',
            f'way["highway"]{box};',
            f'way["natural"~"water|coastline"]{box};',
            f'relation["natural"="water"]{box};',
            f'way["waterway"]{box};',
            f'relation["waterway"]{box};',
        ])
    return "[out:json][timeout:180];(\n" + "\n".join(clauses) + "\n);out body geom;"


def create_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def save_json_exclusive(path: Path, payload: Any) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    create_exclusive(path, data)


def study_area_signature(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = ("slug", "crs", "width_m", "height_m", "area_m2", "osm_bbox_s_w_n_e", "anchor")
    return [{key: row[key] for key in fields} for row in cases]


def osm_element_geometry(element: dict[str, Any]):
    """Build the observed OSM geometry needed only for AOI selection."""
    tags = element.get("tags", {})
    if element.get("type") == "way":
        points = [(float(p["lon"]), float(p["lat"])) for p in element.get("geometry", [])]
        if len(points) < 2:
            return None
        if len(points) >= 4 and points[0] == points[-1] and ("building" in tags or tags.get("natural") == "water"):
            polygon = Polygon(points)
            return polygon if polygon.is_valid else polygon.buffer(0)
        return LineString(points)
    if element.get("type") != "relation":
        return None
    outers: list[list[tuple[float, float]]] = []
    inners: list[list[tuple[float, float]]] = []
    lines = []
    for member in element.get("members", []):
        points = [(float(p["lon"]), float(p["lat"])) for p in member.get("geometry", [])]
        if len(points) < 2:
            continue
        if member.get("type") == "way" and len(points) >= 4 and points[0] == points[-1]:
            (inners if member.get("role") == "inner" else outers).append(points)
        else:
            lines.append(LineString(points))
    if outers:
        polygons = []
        for outer in outers:
            holes = []
            outer_poly = Polygon(outer)
            for inner in inners:
                hole_poly = Polygon(inner)
                if outer_poly.is_valid and hole_poly.is_valid and outer_poly.covers(hole_poly.representative_point()):
                    holes.append(inner)
            polygon = Polygon(outer, holes)
            polygons.append(polygon if polygon.is_valid else polygon.buffer(0))
        return unary_union(polygons)
    return unary_union(lines) if lines else None


def load_complete_osm_batch() -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Reconcile the already-fetched Amsterdam batch against its exact receipt."""
    raw_path = RAW / "osm-amsterdam.json"
    receipts_path = ARTIFACTS / "http-request-receipts.jsonl"
    if not raw_path.is_file() or not receipts_path.is_file():
        return None
    raw_bytes = raw_path.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    receipt = None
    for line in receipts_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if item.get("status_code") == 200 and item.get("response_sha256") == digest:
            receipt = item
            break
    if receipt is None or not isinstance(receipt.get("request_data", {}).get("data"), str):
        return None
    payload = json.loads(raw_bytes)
    if payload.get("remark") or not payload.get("osm3s", {}).get("timestamp_osm_base"):
        raise ValueError("existing OSM batch response is not complete or lacks its source timestamp")
    return payload, receipt


def derive_from_osm_batch(area: dict[str, Any], payload: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any] | None:
    if area["city"] != "Amsterdam":
        return None
    source_query = receipt["request_data"]["data"]
    exact_bbox = "(" + ",".join(f"{float(v):.7f}" for v in area["osm_bbox_s_w_n_e"]) + ")"
    if exact_bbox not in source_query:
        return None
    aoi = shape(area["geometry_wgs84"])
    selected = []
    for element in payload.get("elements", []):
        observed_geometry = osm_element_geometry(element)
        if observed_geometry is not None and observed_geometry.intersects(aoi):
            selected.append(element)
    if not selected:
        return None
    derived = {key: value for key, value in payload.items() if key != "elements"}
    derived["elements"] = selected
    raw_path = RAW / f"osm-{area['slug']}.json"
    record_path = ARTIFACTS / f"osm-source-record-{area['slug']}.json"
    save_json_exclusive(raw_path, derived)
    record = {
        "case_slug": area["slug"],
        "status": "OBSERVED_DERIVED_FROM_COMPLETE_BATCH",
        "endpoint": receipt["url"],
        "source_response_path": str((RAW / "osm-amsterdam.json").relative_to(ROOT)),
        "source_response_sha256": receipt["response_sha256"],
        "source_request_query": source_query,
        "source_request_at_utc": receipt["requested_at_utc"],
        "derived_selection": "OSM way/relation observed geometry intersects the exact study-window polygon; source geometries are retained uncut.",
        "response_path": str(raw_path.relative_to(ROOT)),
        "response_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "response_size_bytes": raw_path.stat().st_size,
        "element_count": len(selected),
        "osm_base_timestamp": derived.get("osm3s", {}).get("timestamp_osm_base"),
        "retrieved_at_utc": receipt["requested_at_utc"],
        "license": "Open Database License 1.0; © OpenStreetMap contributors",
        "limitations": ["Derived from a complete source response whose exact query includes this case bbox; selection retains full observed geometries that intersect the research polygon.", "OSM coverage may omit buildings, paths, shoreline data, or public-access attributes; absence does not prove nonexistence or access status."],
    }
    save_json_exclusive(record_path, record)
    return record


def acquire_osm(areas: list[dict[str, Any]], client: ReadOnlyClient) -> dict[str, Any]:
    snapshots: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    batch = load_complete_osm_batch()
    for area in areas:
        raw_path = RAW / f"osm-{area['slug']}.json"
        record_path = ARTIFACTS / f"osm-source-record-{area['slug']}.json"
        if raw_path.exists() and record_path.exists():
            snapshots.append(json.loads(record_path.read_text(encoding="utf-8")))
            continue
        if raw_path.exists() or record_path.exists():
            raise FileExistsError(f"partial prior OSM output exists for {area['slug']}; preserve and reconcile it before retrying")
        if batch is not None:
            derived_record = derive_from_osm_batch(area, batch[0], batch[1])
            if derived_record is not None:
                snapshots.append(derived_record)
                continue
        query = make_overpass_query([area])
        try:
            response = client.get(OVERPASS, data={"data": query})
        except RuntimeError as exc:
            failures.append({
                "case_slug": area["slug"],
                "status": "INCOMPLETE_HTTP_ERROR",
                "error": str(exc),
                "attempts": client.requests[-1]["attempts"] if client.requests else [],
            })
            continue
        payload = response.json()
        if payload.get("remark"):
            diagnostics = {
                "case_slug": area["slug"],
                "status": "INCOMPLETE_OVERPASS_RESPONSE",
                "query": query,
                "response_sha256": hashlib.sha256(response.content).hexdigest(),
                "response_bytes": len(response.content),
                "remark": payload["remark"],
            }
            save_json_exclusive(ARTIFACTS / f"osm-source-error-{area['slug']}.json", diagnostics)
            raise RuntimeError(f"Overpass returned an incomplete response for {area['slug']}: {payload['remark']}")
        create_exclusive(raw_path, response.content)
        record = {
            "case_slug": area["slug"],
            "status": "OBSERVED",
            "endpoint": OVERPASS,
            "query": query,
            "response_path": str(raw_path.relative_to(ROOT)),
            "response_sha256": hashlib.sha256(response.content).hexdigest(),
            "response_size_bytes": len(response.content),
            "element_count": len(payload.get("elements", [])),
            "osm_base_timestamp": payload.get("osm3s", {}).get("timestamp_osm_base"),
            "retrieved_at_utc": client.requests[-1]["attempts"][-1]["requested_at_utc"],
            "license": "Open Database License 1.0; © OpenStreetMap contributors",
            "limitations": ["Coverage is an OSM observation and may omit buildings, paths, private/public access tags, shoreline data, or recent edits.", "No record implies completeness or a legal/public-access status."],
        }
        save_json_exclusive(record_path, record)
        snapshots.append(record)
    return {"schema_version": "kb4-osm-source-manifest-v1", "snapshots": snapshots, "failures": failures}


def acquire_3dbag(areas: list[dict[str, Any]], client: ReadOnlyClient) -> dict[str, Any]:
    nl_areas = [area for area in areas if area["country"] == "Netherlands"]
    tile_catalogs: list[dict[str, Any]] = []
    catalog_failures: list[dict[str, Any]] = []
    tile_failures: list[dict[str, Any]] = []
    unique_tiles: dict[str, dict[str, Any]] = {}
    params_base = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "BAG3D:tiles", "outputFormat": "application/json", "srsName": "EPSG:28992"}
    for area in nl_areas:
        minx, miny, maxx, maxy = shape(area["geometry"]).bounds
        params = {**params_base, "bbox": f"{minx},{miny},{maxx},{maxy},urn:ogc:def:crs:EPSG::28992"}
        response_path = RAW / "3dbag" / f"tile-catalog-{area['slug']}.json"
        try:
            if response_path.is_file():
                raw_bytes = response_path.read_bytes()
                payload = json.loads(raw_bytes)
                catalog_sha256 = hashlib.sha256(raw_bytes).hexdigest()
                catalog_retrieved_at = "REUSED_EXISTING_HASHED_SNAPSHOT"
            else:
                response = client.get(THREE_DBAG_WFS, params=params)
                payload = response.json()
                raw_bytes = response.content
                catalog_sha256 = hashlib.sha256(raw_bytes).hexdigest()
                catalog_retrieved_at = client.requests[-1]["attempts"][-1]["requested_at_utc"]
        except Exception as exc:
            catalog_failures.append({"case_slug": area["slug"], "status": "INCOMPLETE_REQUEST", "error": f"{type(exc).__name__}: {exc}", "request": params})
            continue
        if payload.get("type") != "FeatureCollection" or not payload.get("features"):
            catalog_failures.append({"case_slug": area["slug"], "status": "INCOMPLETE_RESPONSE", "error": "3DBAG tile catalogue did not return features", "request": params})
            continue
        if not response_path.exists():
            create_exclusive(response_path, raw_bytes)
        found: list[str] = []
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            tile_id = str(props.get("tile_id", "")).strip()
            url = str(props.get("gpkg_download", "")).strip()
            digest = str(props.get("gpkg_sha256", "")).strip()
            if not tile_id or not url or not digest:
                raise ValueError(f"3DBAG catalogue feature lacks tile id, URL, or checksum for {area['slug']}")
            if urlparse(url).hostname != "data.3dbag.nl" or not url.startswith("https://"):
                raise ValueError(f"3DBAG returned a non-allowlisted tile URL: {url}")
            unique_tiles[tile_id] = {"tile_id": tile_id, "url": url, "expected_sha256": digest, "gpkg_size_bytes": props.get("gpkg_size")}
            found.append(tile_id)
        tile_catalogs.append({
            "case_slug": area["slug"],
            "request": params,
            "response_path": str(response_path.relative_to(ROOT)),
            "response_sha256": catalog_sha256,
            "retrieved_at_utc": catalog_retrieved_at,
            "matching_tile_ids": sorted(set(found)),
        })

    tile_receipts: list[dict[str, Any]] = []
    for tile_id, tile in sorted(unique_tiles.items()):
        try:
            file_name = Path(urlparse(tile["url"]).path).name
            output = RAW / "3dbag" / file_name
            if output.is_file():
                actual_hash = hashlib.sha256(output.read_bytes()).hexdigest()
                response_size_bytes = output.stat().st_size
                retrieved_at_utc = "REUSED_EXISTING_HASHED_SNAPSHOT"
            else:
                response = client.get(tile["url"])
                actual_hash = hashlib.sha256(response.content).hexdigest()
                response_size_bytes = len(response.content)
                retrieved_at_utc = client.requests[-1]["attempts"][-1]["requested_at_utc"]
                create_exclusive(output, response.content)
            if actual_hash.lower() != tile["expected_sha256"].removeprefix("sha256:").lower():
                raise ValueError(f"3DBAG response hash mismatch for tile {tile_id}")
            tile_receipts.append({
                **tile,
                "response_path": str(output.relative_to(ROOT)),
                "response_sha256": actual_hash,
                "response_size_bytes": response_size_bytes,
                "retrieved_at_utc": retrieved_at_utc,
            })
        except Exception as exc:
            tile_failures.append({"tile_id": tile_id, "status": "INCOMPLETE_TILE", "error": f"{type(exc).__name__}: {exc}", "url": tile.get("url")})
    return {
        "schema_version": "kb4-3dbag-source-manifest-v1",
        "publisher": "3D geoinformation research group, TU Delft and 3DGI",
        "license": "CC BY 4.0",
        "attribution": "© 3DBAG by tudelft3d and 3DGI",
        "height_fields": {"roof": "b3_h_70p", "ground": "b3_h_maaiveld", "vertical_reference": "NAP; horizontal coordinates RD New (EPSG:28992)"},
        "tile_catalog_requests": tile_catalogs,
        "tiles": tile_receipts,
        "failures": {"tile_catalogs": catalog_failures, "tiles": tile_failures},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", choices=("osm", "3dbag", "all"), default="all")
    parser.add_argument("--resume", action="store_true", help="Reconcile existing study-area definition bytes and continue immutable per-case outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Write the reproducible study-area polygons and request plan only.")
    args = parser.parse_args()
    anchor_index = load_anchor_index()
    calculated_areas = build_study_areas(anchor_index)
    areas_path = ARTIFACTS / "study-areas.json"
    geojson_path = ARTIFACTS / "study-areas.geojson"
    if args.resume:
        existing = json.loads(areas_path.read_text(encoding="utf-8"))
        if study_area_signature(existing.get("cases", [])) != study_area_signature(calculated_areas) or not geojson_path.is_file():
            raise ValueError("existing study-area definition does not match the current OSM anchors and case specification")
        areas = existing["cases"]
    else:
        save_json_exclusive(areas_path, {"schema_version": "kb4-study-areas-v1", "selection_method": "Named OSM reference point plus a case-specific metric rectangle in the recorded CRS; not an official project boundary.", "cases": calculated_areas})
        save_json_exclusive(geojson_path, {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": row["geometry_wgs84"], "properties": {"slug": row["slug"], "title_zh": row["title_zh"], "metric_crs": row["crs"], "area_ha": row["area_ha"], "anchor_osm": row["anchor"]["osm_objects"]}} for row in calculated_areas],
        })
        areas = calculated_areas
    print(json.dumps({"study_area_count": len(areas), "area_ha_min": min(row["area_ha"] for row in areas), "area_ha_max": max(row["area_ha"] for row in areas), "study_areas": str(areas_path.relative_to(ROOT))}, ensure_ascii=False))
    if args.dry_run:
        return 0

    client = ReadOnlyClient()
    manifests: dict[str, Any] = {"schema_version": "kb4-source-requests-v1", "started_at_utc": utc_from_date_command(), "requested_services": []}
    if args.sources in ("osm", "all"):
        osm_manifest = acquire_osm(areas, client)
        save_json_exclusive(ARTIFACTS / "osm-source-manifest.json", osm_manifest)
        manifests["requested_services"].append("Overpass API")
        manifests["osm"] = osm_manifest
    if args.sources in ("3dbag", "all"):
        three_d_manifest = acquire_3dbag(areas, client)
        save_json_exclusive(ARTIFACTS / "3dbag-source-manifest.json", three_d_manifest)
        manifests["requested_services"].append("3DBAG WFS and tile service")
        manifests["3dbag"] = three_d_manifest
    manifests["requests"] = client.requests
    manifests["finished_at_utc"] = utc_from_date_command()
    save_json_exclusive(ARTIFACTS / "source-request-log.json", manifests)
    print(json.dumps({
        "services": manifests["requested_services"],
        "http_attempts": sum(len(row["attempts"]) for row in client.requests),
        "osm_cases": len(manifests.get("osm", {}).get("snapshots", [])),
        "3dbag_tiles": len(manifests.get("3dbag", {}).get("tiles", [])),
        "request_log": str((ARTIFACTS / "source-request-log.json").relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
