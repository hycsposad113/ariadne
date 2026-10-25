#!/usr/bin/env python3
"""Download approved regional OSM files under PD-17 and WC-3.

Approved files:
1. https://download.geofabrik.de/europe/netherlands/zuid-holland-260922.osm.pbf
   Expected size: 211,355,323 bytes, max 262,144,000 bytes, timeout 300s.
2. https://download.geofabrik.de/europe/netherlands/zuid-holland.poly
   Expected size: <= 1,048,576 bytes, timeout 300s.

Constraints:
- Exactly 1 GET per file.
- No automatic retry, no resume, no URL substitution.
- follow_redirects=False. If cross-host redirect, timeout, size mismatch, or HTTP != 200: stop and reconcile without retrying.
- Save raw bytes, response headers, and SHA-256 into artifacts/week4-regional-osm/.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "artifacts/week4-regional-osm"
RAW_DIR = OUTPUT_DIR / "raw"

PBF_URL = "https://download.geofabrik.de/europe/netherlands/zuid-holland-260922.osm.pbf"
PBF_EXPECTED_SIZE = 211_355_323
PBF_MAX_SIZE = 262_144_000

POLY_URL = "https://download.geofabrik.de/europe/netherlands/zuid-holland.poly"
POLY_MAX_SIZE = 1_048_576

TIMEOUT_SECONDS = 300.0


def download_single_file(
    url: str,
    target_path: Path,
    *,
    expected_exact_size: int | None = None,
    max_size: int,
    timeout: float,
) -> dict[str, Any]:
    print(f"Starting single GET: {url}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(target_path.suffix + ".downloading")
    
    hasher = hashlib.sha256()
    total_bytes = 0
    start_time = datetime.datetime.now(datetime.timezone.utc)
    
    headers_dict: dict[str, str] = {}
    http_status: int = 0
    
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        try:
            with client.stream("GET", url, headers={"User-Agent": "Rotterdam-M4H-UrbanDesign/1.0"}) as response:
                http_status = response.status_code
                headers_dict = dict(response.headers)
                print(f"HTTP Status: {http_status}")
                
                if http_status != 200:
                    print(f"STOP: HTTP status is {http_status} != 200. Headers: {headers_dict}")
                    return {
                        "url": url,
                        "status_code": http_status,
                        "headers": headers_dict,
                        "success": False,
                        "error": f"HTTP status {http_status} != 200",
                        "started_at": start_time.isoformat(),
                        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    }
                
                content_length_header = headers_dict.get("content-length")
                if content_length_header is not None:
                    cl_int = int(content_length_header)
                    print(f"Content-Length header: {cl_int}")
                    if expected_exact_size is not None and cl_int != expected_exact_size:
                        print(f"STOP: Content-Length header {cl_int} != expected {expected_exact_size}")
                        return {
                            "url": url,
                            "status_code": http_status,
                            "headers": headers_dict,
                            "success": False,
                            "error": f"Content-Length {cl_int} != expected {expected_exact_size}",
                            "started_at": start_time.isoformat(),
                            "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        }
                
                with open(temp_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > max_size:
                            print(f"STOP: Response size {total_bytes} exceeded cap {max_size}")
                            if temp_path.exists():
                                temp_path.unlink()
                            return {
                                "url": url,
                                "status_code": http_status,
                                "headers": headers_dict,
                                "success": False,
                                "error": f"Size exceeded cap {max_size}",
                                "started_at": start_time.isoformat(),
                                "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            }
                        hasher.update(chunk)
                        f.write(chunk)
                        
        except Exception as exc:
            print(f"STOP: Exception during request: {type(exc).__name__}: {exc}")
            if temp_path.exists():
                temp_path.unlink()
            return {
                "url": url,
                "status_code": http_status,
                "headers": headers_dict,
                "success": False,
                "error": f"Exception: {type(exc).__name__}: {exc}",
                "started_at": start_time.isoformat(),
                "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            
    completed_time = datetime.datetime.now(datetime.timezone.utc)
    
    if expected_exact_size is not None and total_bytes != expected_exact_size:
        print(f"STOP: Downloaded bytes {total_bytes} != expected {expected_exact_size}")
        if temp_path.exists():
            temp_path.unlink()
        return {
            "url": url,
            "status_code": http_status,
            "headers": headers_dict,
            "success": False,
            "error": f"Downloaded bytes {total_bytes} != expected {expected_exact_size}",
            "started_at": start_time.isoformat(),
            "completed_at": completed_time.isoformat(),
        }
        
    temp_path.rename(target_path)
    sha256_hash = hasher.hexdigest()
    print(f"SUCCESS: {target_path.name} saved ({total_bytes} bytes, SHA-256: {sha256_hash})")
    
    return {
        "url": url,
        "target_file": str(target_path.relative_to(ROOT)),
        "status_code": http_status,
        "headers": headers_dict,
        "size_bytes": total_bytes,
        "sha256": sha256_hash,
        "success": True,
        "started_at": start_time.isoformat(),
        "completed_at": completed_time.isoformat(),
    }


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Download PBF
    pbf_target = RAW_DIR / "zuid-holland-260922.osm.pbf"
    pbf_record = download_single_file(
        PBF_URL,
        pbf_target,
        expected_exact_size=PBF_EXPECTED_SIZE,
        max_size=PBF_MAX_SIZE,
        timeout=TIMEOUT_SECONDS,
    )
    (OUTPUT_DIR / "response-headers-pbf.json").write_text(
        json.dumps(pbf_record, indent=2) + "\n"
    )
    if not pbf_record.get("success"):
        print(f"FAILED to download PBF: {pbf_record.get('error')}")
        return 1

    # 2. Download POLY
    poly_target = RAW_DIR / "zuid-holland.poly"
    poly_record = download_single_file(
        POLY_URL,
        poly_target,
        expected_exact_size=None,
        max_size=POLY_MAX_SIZE,
        timeout=TIMEOUT_SECONDS,
    )
    (OUTPUT_DIR / "response-headers-poly.json").write_text(
        json.dumps(poly_record, indent=2) + "\n"
    )
    if not poly_record.get("success"):
        print(f"FAILED to download POLY: {poly_record.get('error')}")
        return 1

    summary = {
        "license": "ODbL 1.0",
        "attribution": "© OpenStreetMap contributors",
        "provider": "Geofabrik Download Server",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "files": {
            "pbf": pbf_record,
            "poly": poly_record,
        },
    }
    (OUTPUT_DIR / "download-record.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print("All approved regional OSM files downloaded and recorded successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
