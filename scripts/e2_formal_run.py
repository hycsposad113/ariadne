"""E2 formal run — run by the Founder in their own terminal against the live API.

Every human decision asks for the decision passphrase with getpass (no echo, never stored,
never logged). The script only replays the request sequence that passed the DB-copy drill
(artifacts/w8/e2-drill). It never opens the database file and never dispatches twice:
an unknown simulate outcome stops the script.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = "rotterdam-m4h-pilot-project"
DRILL = Path(__file__).resolve().parents[1] / "artifacts/w8/e2-drill"
COMPACT = "formal-dict-3da03eb0172d-common-compact-a1ff97864a21"
MIXED = "formal-dict-3da03eb0172d-common-mixed-98854aff5f7b"


def call(base: str, method: str, path: str, body: dict | None = None, params: dict | None = None, timeout: int = 7200):
    url = base.rstrip("/") + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def confirm(question: str) -> None:
    if input(f"\n{question} 輸入 y 繼續，其他鍵中止：").strip().lower() != "y":
        print("已中止，沒有送出這一步。"); sys.exit(1)


def decide(base: str, payload: dict, label: str) -> dict:
    confirm(f"【需要你的決策】{label}")
    key = getpass.getpass("請輸入決策密語（不會顯示）：")
    status, body = call(base, "POST", f"/api/v1/projects/{PROJECT}/decisions", {**payload, "decision_key": key})
    del key
    if status != 201:
        print("決策未成立：", status, json.dumps(body, ensure_ascii=False)[:500]); sys.exit(2)
    print("✓ 決策已記錄：", body.get("id"))
    return body


def build_plan_request(
    template: dict,
    snapshot_id: str,
    bundle_sha256: str,
    method_validation_artifact_id: str,
    accepted_scenario_id: str,
) -> dict:
    import copy
    plan_req = copy.deepcopy(template)
    plan_req["weather_snapshot_id"] = snapshot_id
    plan_req["weather_bundle_sha256"] = bundle_sha256
    plan_req["method_validation_artifact_id"] = method_validation_artifact_id

    compact_pin = template["baseline"] if template["baseline"]["scenario_id"] == COMPACT else template["modified"]
    mixed_pin = template["modified"] if template["modified"]["scenario_id"] == MIXED else template["baseline"]

    if accepted_scenario_id == MIXED:
        plan_req["baseline"] = copy.deepcopy(mixed_pin)
        plan_req["modified"] = copy.deepcopy(compact_pin)
    else:
        plan_req["baseline"] = copy.deepcopy(compact_pin)
        plan_req["modified"] = copy.deepcopy(mixed_pin)

    return plan_req


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--api", default="http://127.0.0.1:8795"); a = ap.parse_args()
    template = json.loads((DRILL / "api-04.json").read_text())["request_without_test_key"]
    print("E2 正式執行（輻射分析）。每一步都會先問你；三個決策步驟需要決策密語。")

    status, snap = call(a.api, "POST", "/api/v1/environment/e2/weather/snapshots", {"project_id": PROJECT})
    if status != 201: print("建立天氣快照失敗：", status, snap); sys.exit(2)
    print(f"1/6 天氣資料快照已建立：{snap['snapshot_id']}（{snap['version']}）")
    decide(a.api, {"action": "Approve", "status": "approved", "actor_session_id": "founder-e2-formal",
                   "reason": "Founder 正式批准 E2 天氣推導方法 candidate-01 綁定",
                   "target_type": snap["decision_target_type"], "target_id": snap["snapshot_id"],
                   "target_version": snap["version"], "target_payload_digest": snap["payload_digest"]},
           "2/6 批准天氣資料快照（E2 使用的天氣推導方法）")

    print("\n正在驗證計算方法（Radiance 實體驗證）...")
    status, val = call(a.api, "POST", f"/api/v1/environment/e2/weather/snapshots/{snap['snapshot_id']}/validate-methods", {"project_id": PROJECT})
    if status not in (200, 201):
        print("方法驗證失敗：", status, json.dumps(val, ensure_ascii=False)[:500]); sys.exit(2)
    method_val_id = val["method_validation_artifact_id"]
    print(f"✓ 方法驗證完成：{method_val_id}")

    print(f"\n3/6 選擇基準方案：\n  1 = common-compact（緊湊）\n  2 = common-mixed（混合）")
    choice = input("哪一案當基準？輸入 1 或 2：").strip()
    accepted, rejected = (COMPACT, MIXED) if choice == "1" else (MIXED, COMPACT) if choice == "2" else (None, None)
    if not accepted: print("未選擇，中止。"); sys.exit(1)
    reason = input("接受理由（一句話）：").strip() or "Founder 選為 E2 基準方案"
    confirm(f"【需要你的決策】接受 {accepted} 為基準，另一案保留作輻射比較")
    key = getpass.getpass("請輸入決策密語（不會顯示）：")
    status, base_dec = call(a.api, "POST", "/api/v1/scenarios/comparison/decision", {
        "project_id": PROJECT, "scenario_ids": [COMPACT, MIXED], "accepted_scenario_id": accepted,
        "acceptance_reason": reason, "rejected_reasons": {rejected: "保留作 E2 輻射比較的對照方案"},
        "actor_session_id": "founder-e2-formal", "decision_key": key})
    del key
    if status != 201: print("基準決策未成立：", status, json.dumps(base_dec, ensure_ascii=False)[:500]); sys.exit(2)
    print("✓ 基準方案已記錄")

    plan_req = build_plan_request(
        template=template,
        snapshot_id=snap["snapshot_id"],
        bundle_sha256=snap["payload_digest"],
        method_validation_artifact_id=method_val_id,
        accepted_scenario_id=accepted,
    )
    status, plan = call(a.api, "POST", "/api/v1/environment/e2/plan", plan_req)
    if status != 201: print("建立實驗計畫失敗：", status, json.dumps(plan, ensure_ascii=False)[:500]); sys.exit(2)
    print(f"\n4/6 實驗計畫已建立：{plan['plan_artifact_id']}（夏季 6–8 月、地面網格、±1 小時敏感度）")
    decide(a.api, {"action": "Approve", "status": "approved", "actor_session_id": "founder-e2-formal",
                   "reason": "Founder 正式批准 E2 夏季輻射實驗計畫、網格與敏感度設定",
                   "target_type": "Artifact", "target_id": plan["plan_artifact_id"],
                   "target_version": str(plan.get("version", "1")), "target_artifact_sha256": plan["sha256"]},
           "5/6 批准輻射實驗計畫")

    status, ready = call(a.api, "GET", "/api/v1/environment/e2/readiness", params={"project_id": PROJECT, "plan_artifact_id": plan["plan_artifact_id"]})
    if status != 200 or not ready.get("dispatch_allowed"): print("尚不可派送：", ready); sys.exit(2)
    confirm("6/6 開始計算（Ladybug＋Honeybee-Radiance，約數分鐘到數十分鐘，只派送一次）")
    status, result = call(a.api, "POST", "/api/v1/environment/e2/simulate",
                          {"project_id": PROJECT, "plan_artifact_id": plan["plan_artifact_id"], "idempotency_key": "founder-e2-formal-v1"})
    if status != 200 or result.get("status") != "SUCCEEDED":
        print("計算結果不明或失敗，請不要重跑，交給 Commander 對帳：", status, json.dumps(result, ensure_ascii=False)[:500]); sys.exit(3)
    status, comparison = call(a.api, "POST", "/api/v1/environment/e2/compare", {"project_id": PROJECT, "job_id": result["job_id"]})
    print(f"\n✓ E2 完成，job {result['job_id']}；方向摘要：{json.dumps(result.get('direction_summary'), ensure_ascii=False)[:400]}")
    print("結果已寫入正式帳本。請告訴 Commander「E2 跑完了」。")


if __name__ == "__main__":
    main()
