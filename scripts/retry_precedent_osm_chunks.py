#!/usr/bin/env python3
"""Acquire the four failed KB4 windows plus KNSM using bounded OSM bbox chunks.

Only the allowlisted read-only Overpass API is contacted. Four sub-bboxes retain
the existing study window while reducing per-request query size. Responses are
deduplicated by OSM type/id and kept with per-chunk query, timestamp and hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/kb4-precedents"
RAW = ART / "raw"
ENDPOINT = "https://overpass-api.de/api/interpreter"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.acquire_precedent_morphology_sources as acq
from scripts.acquire_precedent_morphology_sources import ReadOnlyClient


TARGETS = (
    "katendrecht",
    "vastra-hamnen",
    "barcelona-eixample",
    "knsm-eiland",
)


def utc_now() -> str:
    return subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def spatial_chunks(area: dict[str, Any], grid_n: int = 4) -> list[dict[str, float | str]]:
    south, west, north, east = map(float, area["osm_bbox_s_w_n_e"])
    lat_step = (north - south) / float(grid_n)
    lon_step = (east - west) / float(grid_n)
    chunks = []
    for r in range(grid_n):
        for c in range(grid_n):
            s = south + r * lat_step
            n = south + (r + 1) * lat_step
            w = west + c * lon_step
            e = west + (c + 1) * lon_step
            chunks.append({
                "chunk_id": f"R{r}C{c}",
                "south": s,
                "west": w,
                "north": n,
                "east": e,
            })
    return chunks


def overpass_query(chunk: dict[str, float | str]) -> str:
    bbox = f"({float(chunk['south']):.7f},{float(chunk['west']):.7f},{float(chunk['north']):.7f},{float(chunk['east']):.7f})"
    clauses = [
        f'way["building"]{bbox};',
        f'relation["building"]{bbox};',
        f'way["building:part"]{bbox};',
        f'relation["building:part"]{bbox};',
        f'way["highway"]{bbox};',
        f'way["natural"~"water|coastline"]{bbox};',
        f'relation["natural"="water"]{bbox};',
        f'way["waterway"]{bbox};',
        f'relation["waterway"]{bbox};',
    ]
    return "[out:json][timeout:180];(\n" + "\n".join(clauses) + "\n);out body geom;"


def wait_for_overpass_slot(client: ReadOnlyClient) -> None:
    """Check Overpass API status and wait if no slots are available."""
    for _ in range(12):
        try:
            resp = client.session.get("https://overpass-api.de/api/status", timeout=10)
            if resp.status_code == 200:
                text = resp.text
                match = re.search(r"Slot available after:[^,]+,\s*in\s*(\d+)\s*seconds", text)
                if "0 slots available now" in text:
                    wait_sec = int(match.group(1)) + 2 if match else 20
                    print(f"Waiting {wait_sec}s for Overpass slot cooldown...", file=sys.stderr)
                    time.sleep(wait_sec)
                    continue
                break
        except Exception:
            break


def exclusive_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def prior_attempts_by_query() -> dict[str, list[dict[str, Any]]]:
    path = ART / "http-request-receipts.jsonl"
    attempts: dict[str, list[dict[str, Any]]] = {}
    if not path.is_file():
        return attempts
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("url") != ENDPOINT:
                continue
            query = (row.get("request_data") or {}).get("data")
            if isinstance(query, str):
                attempts.setdefault(query, []).append(row)
    return attempts


def find_latest_partial(slug: str, grid_n: int) -> tuple[dict[str, Any], dict[tuple[str, int], dict[str, Any]]] | None:
    expected_method_prefix = f"{grid_n * grid_n} spatial bbox chunks"
    pattern = f"osm-source-record-{slug}-bbox-chunks-partial-*.json"
    matches = sorted(ART.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for record_path in matches:
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if not record.get("query_method", "").startswith(expected_method_prefix):
                continue
            raw_path = ROOT / record["response_path"]
            if not raw_path.is_file():
                continue
            raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
            elements = raw_data.get("elements", [])
            elem_map = {(str(e.get("type")), int(e.get("id", -1))): e for e in elements if int(e.get("id", -1)) >= 0}
            observed_reqs = {r["chunk_id"]: r for r in record.get("requests", []) if r.get("status") == "OBSERVED"}
            if observed_reqs:
                return observed_reqs, elem_map
        except Exception:
            continue
    return None


def acquire_case(area: dict[str, Any], client: ReadOnlyClient, run_stamp: str,
                 prior_attempts: dict[str, list[dict[str, Any]]], grid_n: int = 4,
                 max_case_attempts: int = 30) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    unique_elements: dict[tuple[str, int], dict[str, Any]] = {}
    timestamps: list[str] = []
    failed_chunks: list[dict[str, Any]] = []
    case_attempts = 0
    chunks = spatial_chunks(area, grid_n=grid_n)

    cached = find_latest_partial(area["slug"], grid_n)
    cached_requests, cached_elements = cached if cached else ({}, {})
    if cached_requests:
        print(f"Reusing {len(cached_requests)}/{len(chunks)} observed chunks from partial record for {area['slug']}...", file=sys.stderr)
        unique_elements.update(cached_elements)

    for chunk in chunks:
        cid = chunk["chunk_id"]
        if cid in cached_requests:
            cached_req = cached_requests[cid]
            requests.append(cached_req)
            if cached_req.get("osm_base_timestamp"):
                timestamps.append(str(cached_req["osm_base_timestamp"]))
            continue

        query = overpass_query(chunk)
        remaining_budget = max_case_attempts - case_attempts
        if remaining_budget <= 0:
            failed = {
                "chunk_id": chunk["chunk_id"],
                "bbox_s_w_n_e": [chunk["south"], chunk["west"], chunk["north"], chunk["east"]],
                "query": query,
                "status": "CASE_ATTEMPTS_EXHAUSTED",
                "attempt_count": 0,
                "http_statuses": [],
                "error": f"The {max_case_attempts}-attempt budget for case {area['slug']} was exhausted; remaining chunks not sent.",
            }
            requests.append(failed)
            failed_chunks.append(failed)
            continue
        chunk_attempt_limit = min(3, remaining_budget)
        try:
            response = client.get(ENDPOINT, data={"data": query}, attempt_limit=chunk_attempt_limit)
            new_attempts = client.requests[-1].get("attempts", []) if client.requests else []
            case_attempts += len(new_attempts)
            payload = response.json()
            if payload.get("remark") or not isinstance(payload.get("elements"), list):
                raise ValueError(f"Overpass response incomplete: {payload.get('remark', 'elements missing')}")
        except Exception as exc:
            new_attempts = client.requests[-1].get("attempts", []) if client.requests else []
            case_attempts += len(new_attempts)
            statuses = [row.get("status_code") for row in new_attempts if row.get("status_code") is not None]
            failed = {
                "chunk_id": chunk["chunk_id"],
                "bbox_s_w_n_e": [chunk["south"], chunk["west"], chunk["north"], chunk["east"]],
                "query": query,
                "status": "FAILED",
                "attempt_count": len(new_attempts),
                "http_statuses": statuses,
                "error": f"{type(exc).__name__}: {exc}",
            }
            requests.append(failed)
            failed_chunks.append(failed)
            continue
        osm3s = payload.get("osm3s", {})
        if osm3s.get("timestamp_osm_base"):
            timestamps.append(str(osm3s["timestamp_osm_base"]))
        for element in payload["elements"]:
            key = (str(element.get("type")), int(element.get("id", -1)))
            if key[1] >= 0:
                unique_elements[key] = element
        requests.append({
            "chunk_id": chunk["chunk_id"],
            "bbox_s_w_n_e": [chunk["south"], chunk["west"], chunk["north"], chunk["east"]],
            "query": query,
            "status": "OBSERVED",
            "attempt_count": len(client.requests[-1].get("attempts", [])),
            "http_status": response.status_code,
            "response_bytes": len(response.content),
            "response_sha256": hashlib.sha256(response.content).hexdigest(),
            "osm_base_timestamp": osm3s.get("timestamp_osm_base"),
        })

    if failed_chunks:
        raw_path = RAW / f"osm-{area['slug']}-bbox-chunks-partial-{run_stamp}.json"
        record_path = ART / f"osm-source-record-{area['slug']}-bbox-chunks-partial-{run_stamp}.json"
        partial_payload = {
            "version": 0.6,
            "generator": f"Overpass API; partial {grid_n}x{grid_n} bbox chunks merged by OSM element type/id",
            "osm3s": {"chunk_timestamps_osm_base": sorted(set(timestamps))},
            "elements": [unique_elements[key] for key in sorted(unique_elements)],
        }
        raw_bytes = (json.dumps(partial_payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with raw_path.open("xb") as stream:
            stream.write(raw_bytes)
        record = {
            "case_slug": area["slug"],
            "status": "NOT_ACQUIRED_PARTIAL_BBOX",
            "endpoint": ENDPOINT,
            "retrieved_at_utc": utc_now(),
            "osm_chunk_timestamps": sorted(set(timestamps)),
            "query_method": f"{len(chunks)} spatial bbox chunks ({grid_n}x{grid_n}) over study-window bbox; at least one chunk failed/exhausted budget",
            "requests": requests,
            "response_path": str(raw_path.relative_to(ROOT)),
            "response_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "response_size_bytes": len(raw_bytes),
            "element_count": len(partial_payload["elements"]),
            "complete_window": False,
            "license": "Open Database License 1.0; © OpenStreetMap contributors",
            "limitations": ["Partial chunks are retained for audit only and are not used to calculate a complete-window morphology.", "A failed chunk is NOT_ACQUIRED, not NOT_FOUND.", "OSM access tags do not establish legal easements or guaranteed public access."],
        }
        exclusive_json(record_path, record)
        return None, {
            "case_slug": area["slug"],
            "status": "NOT_ACQUIRED",
            "requests": requests,
            "failed_chunks": [row["chunk_id"] for row in failed_chunks],
            "attempt_count": sum(row.get("attempt_count", 0) for row in failed_chunks),
            "http_statuses": [status for row in failed_chunks for status in row.get("http_statuses", [])],
            "last_error": failed_chunks[-1]["error"],
            "partial_record_path": str(record_path.relative_to(ROOT)),
            "partial_response_path": str(raw_path.relative_to(ROOT)),
        }

    raw_path = RAW / f"osm-{area['slug']}-bbox-chunks-{run_stamp}.json"
    record_path = ART / f"osm-source-record-{area['slug']}-bbox-chunks-{run_stamp}.json"
    timestamp = timestamps[0] if len(set(timestamps)) == 1 else None
    raw_payload = {
        "version": 0.6,
        "generator": f"Overpass API; {grid_n}x{grid_n} bbox chunks merged by OSM element type/id",
        "osm3s": {"timestamp_osm_base": timestamp} if timestamp else {"chunk_timestamps_osm_base": sorted(set(timestamps))},
        "elements": [unique_elements[key] for key in sorted(unique_elements)],
    }
    raw_bytes = (json.dumps(raw_payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("xb") as stream:
        stream.write(raw_bytes)
    record = {
        "case_slug": area["slug"],
        "status": "OBSERVED_CHUNKED_BBOX",
        "endpoint": ENDPOINT,
        "retrieved_at_utc": utc_now(),
        "osm_base_timestamp": timestamp,
        "osm_chunk_timestamps": sorted(set(timestamps)),
        "query_method": f"{len(chunks)} spatial bbox chunks ({grid_n}x{grid_n}) over the exact study-window bounding box; no place-name lookup",
        "requests": requests,
        "response_path": str(raw_path.relative_to(ROOT)),
        "response_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "response_size_bytes": len(raw_bytes),
        "element_count": len(raw_payload["elements"]),
        "license": "Open Database License 1.0; © OpenStreetMap contributors",
        "limitations": [
            "A bbox chunk response is a snapshot of mapped elements, not evidence of complete ground truth.",
            "Subrequests may have different OSM base timestamps; chunk-level timestamps are retained.",
            "OSM access tags do not establish legal easements, ownership or guaranteed public access.",
        ],
    }
    exclusive_json(record_path, record)
    return {
        "source_record_path": str(record_path.relative_to(ROOT)),
        "response_path": str(raw_path.relative_to(ROOT)),
        "response_sha256": record["response_sha256"],
        "element_count": record["element_count"],
        "status": record["status"],
    }, {"case_slug": area["slug"], "status": "OBSERVED", "requests": requests}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid-size", type=int, default=4, help="Grid subdivision per axis (default: 4, giving 16 chunks)")
    parser.add_argument("--cases", nargs="*", default=None, help="Explicit list of slugs to acquire")
    parser.add_argument("--gap", type=float, default=6.0, help="Minimum request gap seconds (default: 6.0, >= 5.0s)")
    parser.add_argument("--retry-wait", type=int, default=35, help="Seconds to wait before retrying a 429/500/504")
    parser.add_argument("--max-case-attempts", type=int, default=30, help="Maximum Overpass attempts allowed per case")
    args = parser.parse_args()

    acq.REQUEST_GAP_SECONDS = max(5.0, args.gap)
    acq.RETRY_WAIT_SECONDS = max(10, args.retry_wait)

    run_stamp = utc_now().replace("-", "").replace(":", "")[:15] + "Z-" + uuid.uuid4().hex[:8]
    area_rows = json.loads((ART / "study-areas.json").read_text(encoding="utf-8"))["cases"]
    by_slug = {row["slug"]: row for row in area_rows}
    client = ReadOnlyClient()
    attempt_history = prior_attempts_by_query()
    override_path = ART / "source-overrides.json"
    current = json.loads(override_path.read_text(encoding="utf-8")) if override_path.is_file() else {"schema_version": "kb4-source-overrides-v1", "cases": {}}
    successes: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    target_slugs = args.cases if args.cases else TARGETS
    for slug in target_slugs:
        # Re-acquire target slugs; only skip non-target slugs if already present
        if args.cases is None and slug in current.get("cases", {}) and slug not in TARGETS:
            outcomes.append({"case_slug": slug, "status": "ALREADY_ACQUIRED", "source": current["cases"][slug]})
            continue
        success, outcome = acquire_case(
            by_slug[slug], client, run_stamp, attempt_history,
            grid_n=args.grid_size, max_case_attempts=args.max_case_attempts
        )
        outcomes.append(outcome)
        if success:
            successes[slug] = success
        else:
            failures.append({
                "case_slug": slug,
                "status": "NOT_ACQUIRED",
                "attempt_count": outcome.get("attempt_count", 0),
                "http_statuses": outcome.get("http_statuses", []),
                "last_error": outcome.get("last_error", "A chunk request did not return a complete 200 response."),
                "failed_chunks": outcome.get("failed_chunks", []),
                "partial_record_path": outcome.get("partial_record_path"),
            })

    manifest_path = ART / f"osm-bbox-chunk-retry-{run_stamp}.json"
    manifest = {
        "schema_version": "kb4-osm-bbox-chunk-retry-v1",
        "run_id": run_stamp,
        "started_at_utc": run_stamp,
        "finished_at_utc": utc_now(),
        "endpoint": ENDPOINT,
        "grid_size": f"{args.grid_size}x{args.grid_size}",
        "max_attempts_per_case": args.max_case_attempts,
        "minimum_request_gap_seconds": acq.REQUEST_GAP_SECONDS,
        "retry_wait_seconds_for_429_500_504": acq.RETRY_WAIT_SECONDS,
        "study_window_source": "artifacts/kb4-precedents/study-areas.json",
        "cases": outcomes,
        "failures": failures,
        "receipts_path": str((ART / "http-request-receipts.jsonl").relative_to(ROOT)),
    }
    exclusive_json(manifest_path, manifest)
    current.setdefault("cases", {}).update(successes)
    temp_path = ART / f"source-overrides-{run_stamp}.json"
    exclusive_json(temp_path, current)
    if override_path.exists():
        with override_path.open("w", encoding="utf-8") as stream:
            json.dump(current, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    else:
        exclusive_json(override_path, current)
    print(json.dumps({
        "status": "PASS" if not failures else "INCOMPLETE",
        "successful_case_count": len(current.get("cases", {})),
        "successful_cases": current.get("cases", {}),
        "failure_count": len(failures),
        "failures": failures,
        "manifest_path": str(manifest_path.relative_to(ROOT)),
        "active_overrides_path": str(override_path.relative_to(ROOT)),
        "versioned_overrides_path": str(temp_path.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
