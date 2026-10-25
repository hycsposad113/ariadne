"""Prepare Founder-authorized D2 drafts; never submit decisions or activate sets.

Without --api-base this prints request JSON only. HTTP writes are sequential,
with no automatic retry; any failure or uncertain outcome stops the script.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

import httpx

PROJECT_ID = "rotterdam-m4h-pilot-project"


def prepare_drafts() -> list[dict[str, Any]]:
    drafts = []
    for label, far, coverage, height in (("a", 0.80, 0.35, 20), ("b", 2.00, 0.50, 40)):
        def item(name, value, unit, scope="whole_site", source="ASSUMED: D2 comparison setting; not a planning standard"):
            result = {
                "id": f"d2-{label}-{name}-{scope.replace(':', '-')}",
                "name": name, "value": value, "unit": unit, "scope": scope,
                "enforcement": "HARD", "source_note": source,
            }
            if name == "far_upper_limit":
                result["denominator"] = "land_area"
            return result

        constraints = [
            item("far_upper_limit", far, "ratio", source="FOUNDER_STATED: 2026-10-01 D2; denominator is land area excluding water"),
            item("coverage_upper_limit", coverage, "ratio"),
            item("height_upper_limit", height, "m", source="FOUNDER_STATED: 2026-10-01 D2 height cap"),
            item("first_floor_height", 3.5, "m", source="PORTFOLIO_P24_SECTION: Founder confirmed 3.5 m on 2026-10-01"),
            item("standard_floor_height", 3.5, "m", source="PORTFOLIO_P24_SECTION: Founder confirmed 3.5 m on 2026-10-01"),
            item("road_width", 14, "m", "road:primary"),
            item("road_width", 10, "m", "road:secondary"),
            item("road_width", 6, "m", "road:residential", source="ASSUMED: local mapped to OSM highway=residential; D2 6 m"),
            item("rotation_step", 15, "degree"),
        ]
        drafts.append({
            "id": f"constraint-set-d2-{label}-20261001",
            "idempotency_key": f"d2-{label}-20261001-v1",
            "actor_kind": "AGENT_AUTOMATION", "actor_session_id": "prepare-d2-drafts-20261001",
            "allocation_policy": None,
            "notes": f"D2 {label.upper()} 未核准草稿。開放空間 ≥40% 陸地為偏好，尚非 ConstraintSet 可執行指標；15 m 水岸帶沿用 D1 規則。五區維持偏好，不填分區 FAR。道路 local 對應 highway=residential；primary／secondary 精確比對 highway。所有數值待 Founder 確認，未啟用。",
            "constraints": constraints,
        })
    return drafts


def submit_drafts(api_base: str, client: httpx.Client) -> list[dict[str, Any]]:
    results = []
    for draft in prepare_drafts():
        # Never retry after dispatch, including connection loss or HTTP errors.
        response = client.post(f"{api_base.rstrip('/')}/api/v1/projects/{PROJECT_ID}/constraint-sets", json=draft)
        response.raise_for_status()
        result = response.json()
        if result["constraint_set"]["id"] != draft["id"] or result["constraint_set"]["status"] != "proposed" or result["revision"] != 1:
            raise ValueError("Unexpected draft receipt; stop and reconcile authoritative state")
        results.append(result)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", help="Commander rehearsal API using a DB copy")
    args = parser.parse_args()
    if args.api_base:
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            output = submit_drafts(args.api_base, client)
    else:
        output = {"project_id": PROJECT_ID, "drafts": prepare_drafts()}
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
