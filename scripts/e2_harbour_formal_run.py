"""Founder-operated E2 harbour run. No database access or automatic retries.

Reuse the approved weather/method artifacts; fetch current scenario pins before
planning. Every POST requires explicit confirmation. Secrets stay in memory only.
"""
from __future__ import annotations

import argparse
import copy
import getpass
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT = "rotterdam-m4h-pilot-project"
MIXED = "formal-dict-3da03eb0172d-common-mixed-98854aff5f7b"
SNAPSHOT = "snapshot-e2-weather-109b15ff7c739ceb92a161a5"
METHOD_VALIDATION = "artifact-e2-method-validation-c2ddc895d1ccd8b86f164c07"
IDEMPOTENCY_KEY = "founder-e2-harbour-v1"
DRILL = Path(__file__).resolve().parents[1] / "artifacts/w8/e2-drill"
HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


def call(base, method, path, body=None, params=None, timeout=7200):
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                    headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def confirm(label):
    if input(f"\n{label} 輸入 y 繼續，其他鍵中止：").strip().lower() != "y":
        raise SystemExit("已中止，沒有送出這一步。")


def require_response(status, body, expected, label):
    if status not in expected or not isinstance(body, dict):
        print(f"{label}失敗：HTTP {status}；{json.dumps(body, ensure_ascii=False)[:800]}")
        raise SystemExit(2)
    return body


def validate_pin(pin):
    keys = {"scenario_id", "revision", "geometry_artifact_id", "geometry_sha256", "environment_sha256"}
    if not isinstance(pin, dict) or set(pin) != keys:
        raise ValueError("ScenarioPin fields invalid")
    if type(pin["revision"]) is not int or pin["revision"] < 1:
        raise ValueError("ScenarioPin revision invalid")
    if any(not isinstance(pin[k], str) or not pin[k].strip() for k in ("scenario_id", "geometry_artifact_id")):
        raise ValueError("ScenarioPin identifiers invalid")
    if any(not isinstance(pin[k], str) or not HASH.fullmatch(pin[k]) for k in ("geometry_sha256", "environment_sha256")):
        raise ValueError("ScenarioPin hash invalid")
    return copy.deepcopy(pin)


def get_pin(base, scenario_id):
    status, body = call(base, "GET", f"/api/v1/environment/e2/scenarios/{urllib.parse.quote(scenario_id, safe='')}/pin",
                        params={"project_id": PROJECT})
    pin = validate_pin(require_response(status, body, {200}, "讀取方案 pin"))
    if pin["scenario_id"] != scenario_id:
        raise ValueError("ScenarioPin scenario mismatch")
    return pin


def build_plan_request(template, baseline_pin, modified_pin, weather_digest):
    baseline, modified = validate_pin(baseline_pin), validate_pin(modified_pin)
    if baseline["scenario_id"] != MIXED or modified["scenario_id"] == MIXED:
        raise ValueError("Plan must compare MIXED baseline against harbour modified")
    if not isinstance(weather_digest, str) or not HASH.fullmatch(weather_digest):
        raise ValueError("Weather digest invalid")
    request = copy.deepcopy(template)
    request.update(project_id=PROJECT, baseline=baseline, modified=modified,
                   weather_snapshot_id=SNAPSHOT, weather_bundle_sha256=weather_digest,
                   method_validation_artifact_id=METHOD_VALIDATION)
    return request


def decide(base, payload, label):
    # Match generic decisions API syntax before requesting a secret.
    for key in ("target_id", "target_type", "target_version", "reason", "actor_session_id"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ValueError(f"Invalid decision {key}")
    digest = payload.get("target_geometry_sha256") or payload.get("target_artifact_sha256")
    if not isinstance(digest, str) or not HASH.fullmatch(digest):
        raise ValueError("Invalid decision target hash")
    confirm(label)
    secret = getpass.getpass("請輸入決策密語（不會顯示或儲存）：")
    try:
        status, body = call(base, "POST", f"/api/v1/projects/{PROJECT}/decisions", {**payload, "decision_key": secret})
    finally:
        del secret
    # A validation error could reflect submitted secrets; never display its body.
    if status != 201 or not isinstance(body, dict):
        raise SystemExit(f"決策未成立：HTTP {status}；請交給 Commander 對帳。")
    print("✓ 決策已記錄：", body.get("id"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8795")
    args = parser.parse_args()
    template = json.loads((DRILL / "api-04.json").read_text())["request_without_test_key"]
    print("E2 港埠方案正式執行：MIXED 為 baseline、港埠為 modified。每個寫入步驟需 y。")
    status, weather = call(args.api, "GET", f"/api/v1/environment/e2/weather/snapshots/{SNAPSHOT}", params={"project_id": PROJECT})
    weather = require_response(status, weather, {200}, "讀取既有天氣快照")
    if weather.get("snapshot_id") != SNAPSHOT or weather.get("status") != "approved":
        raise ValueError("Existing weather approval missing")
    baseline = get_pin(args.api, MIXED)
    confirm("1/6 登錄固定 artifacts/fab1/run-8/harbour_grain-plan.json 港埠方案")
    status, registration = call(args.api, "POST", "/api/v1/environment/e2/harbour/register", {"project_id": PROJECT})
    registration = require_response(status, registration, {200, 201}, "登錄港埠方案")
    print("原始方案 SHA-256：", registration.get("source_sha256"))
    source_validation = registration.get("source_validation") or {}
    print("原檔規劃檢核 failure_ids：", json.dumps(source_validation.get("failure_ids"), ensure_ascii=False))
    print("環境幾何可計算不代表規劃檢核通過；原檔規劃檢核仍為 FAIL。")
    if str(registration.get("status", "")).lower() == "accepted":
        print("港埠方案已 accepted；請交 Commander 核對既有 job／plan，避免再次接受或重跑未知結果。")
        raise SystemExit(2)
    harbour_id = registration["scenario_id"]
    harbour = get_pin(args.api, harbour_id)
    reason = input("接受港埠方案供 E2 比較的理由：").strip()
    decide(args.api, {"action": "Accept", "status": "accepted", "actor_session_id": "founder-e2-harbour",
                     "reason": reason, "target_type": "DesignScenario", "target_id": harbour_id,
                     "target_version": str(harbour["revision"]), "target_geometry_sha256": harbour["geometry_sha256"]},
           "2/6 接受港埠方案供輻射比較（保留 MIXED，不拒絕 MIXED）")
    # Acceptance can append a scenario revision. Never reuse a pre-decision pin.
    harbour = get_pin(args.api, harbour_id)
    baseline = get_pin(args.api, MIXED)
    request = build_plan_request(template, baseline, harbour, weather["payload_digest"])
    print(json.dumps(request, ensure_ascii=False, indent=2))
    confirm("3/6 建立上述實驗計畫（夏季 6–8 月、地面網格、±1 小時敏感度）")
    status, plan = call(args.api, "POST", "/api/v1/environment/e2/plan", request)
    plan = require_response(status, plan, {201}, "建立實驗計畫")
    decide(args.api, {"action": "Approve", "status": "approved", "actor_session_id": "founder-e2-harbour",
                     "reason": "Founder 批准 MIXED 對港埠 E2 夏季輻射實驗計畫、網格與敏感度設定",
                     "target_type": "Artifact", "target_id": plan["plan_artifact_id"],
                     "target_version": plan["version"], "target_artifact_sha256": plan["sha256"]}, "4/6 批准實驗計畫")
    status, ready = call(args.api, "GET", "/api/v1/environment/e2/readiness", params={"project_id": PROJECT, "plan_artifact_id": plan["plan_artifact_id"]})
    ready = require_response(status, ready, {200}, "派送前檢查")
    if ready.get("dispatch_allowed") is not True:
        raise SystemExit(f"尚不可派送：{json.dumps(ready, ensure_ascii=False)}")
    confirm("5/6 開始計算（Ladybug＋Honeybee-Radiance，只派送一次）")
    try:
        status, result = call(args.api, "POST", "/api/v1/environment/e2/simulate", {
            "project_id": PROJECT, "plan_artifact_id": plan["plan_artifact_id"], "idempotency_key": IDEMPOTENCY_KEY})
    except Exception as error:
        # Any post-dispatch transport/decoding failure leaves the outcome unknown.
        print(f"OUTCOME_UNKNOWN：{type(error).__name__}；請勿重跑，由 Commander 對帳。")
        raise SystemExit(3) from None
    if status != 200 or not isinstance(result, dict) or result.get("status") != "SUCCEEDED":
        print("計算結果不明或失敗，請勿重跑，由 Commander 對帳：", status, json.dumps(result, ensure_ascii=False)[:800])
        raise SystemExit(3)
    confirm("6/6 建立同方法方向比較結果")
    status, comparison = call(args.api, "POST", "/api/v1/environment/e2/compare", {"project_id": PROJECT, "job_id": result["job_id"]})
    comparison = require_response(status, comparison, {200}, "建立比較")
    if comparison.get("status") != "SUCCEEDED" or comparison.get("job_id") != result["job_id"]:
        print("比較未成功：", json.dumps(comparison, ensure_ascii=False)[:800])
        raise SystemExit(2)
    print(f"✓ E2 港埠計算及比較完成，job {result['job_id']}")
    print("方向摘要：", json.dumps(comparison.get("direction_summary"), ensure_ascii=False))
    print("請交給 Commander 核對結果；此腳本不宣告設計優勝者。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        # Never print exception text: transport errors may retain request details.
        print(f"已停止（{type(error).__name__}）；寫入結果須由 Commander 對帳，不會自動重送。")
        sys.exit(2)
