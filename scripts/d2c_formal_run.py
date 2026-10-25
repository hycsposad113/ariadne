"""D2-C formal run — run by the Founder in their own terminal against the live API.

Formalizes the three ASSUMED values into D2-C constraint set (constraint-set-d2-c-20261016):
1. FAR 0.8 (land_area denominator; new GFA cap 146,873 m²).
2. New GFA lower limit 85% (124,842.05 m²; recorded in notes/validation report).
3. Retained halls counted as 1-2 floors, not calculated by 3.5 m floor height (recorded in notes).
4. Height cap 20 m (max 5 floors: ground floor 4 m + standard floor 3.5 m).
Plus baseline coverage (0.35), road widths (14/10/6 m), and rotation step (15°) retained from D2-A.

Every human decision asks for the decision passphrase with getpass (no echo, never stored,
never logged). The script only creates the draft idempotently, presents the content for confirmation,
and prompts the Founder for the passphrase to activate D2-C.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
from typing import Any

PROJECT = "rotterdam-m4h-pilot-project"
D2C_ID = "constraint-set-d2-c-20261016"
D2C_IDEMPOTENCY_KEY = "d2c-formal-run-20261016"
D2C_ACTOR_SESSION_ID = "agent-d2c-formal-session"
D2C_NOTES = (
    "Founder 2026-10-11／10-15 決定：\n"
    "1. FAR 0.8 只計「新建＋加蓋」樓地板，保留建築不計入；新建 GFA 上限 146,873 m²（分母 land_area）。\n"
    "2. 新建 GFA 下限為上限的 85%（124,842.05 m²）。現有約束型別僅支援上限，下限列為無法直接表達項，於 notes 明定並由驗證器與報告把關。\n"
    "3. 保留廠房（retained halls）以 1–2 層計，不以 3.5 m 層高推算。現有型別無保留建物專屬層數欄位，列為無法直接表達項。\n"
    "4. 高度上限 20 m，首層 4 m，標準層 3.5 m（最多 5 層：4 m＋4×3.5 m = 18 m ≤ 20 m）。其餘建蔽率 0.35、道路路寬（14/10/6 m）與旋轉步階 15° 沿用 D2-A 基準。"
)


def build_d2c_constraints() -> list[dict[str, Any]]:
    return [
        {
            "id": "d2-c-far_upper_limit-whole_site",
            "name": "far_upper_limit",
            "value": 0.8,
            "unit": "ratio",
            "scope": "whole_site",
            "enforcement": "HARD",
            "denominator": "land_area",
            "source_note": "FOUNDER_STATED: Founder 2026-10-11／10-15 決定：FAR 0.8 只計「新建＋加蓋」樓地板，保留建築不計入；新建 GFA 上限 146,873 m²，分母為 land_area",
        },
        {
            "id": "d2-c-coverage_upper_limit-whole_site",
            "name": "coverage_upper_limit",
            "value": 0.35,
            "unit": "ratio",
            "scope": "whole_site",
            "enforcement": "HARD",
            "denominator": None,
            "source_note": "ASSUMED: 沿用 D2-A 基準建蔽率 0.35",
        },
        {
            "id": "d2-c-height_upper_limit-whole_site",
            "name": "height_upper_limit",
            "value": 20.0,
            "unit": "m",
            "scope": "whole_site",
            "enforcement": "HARD",
            "denominator": None,
            "source_note": "FOUNDER_STATED: Founder 既有決定：高度上限 20 m（最多 5 層：首層 4 m＋4×3.5 m）",
        },
        {
            "id": "d2-c-first_floor_height-whole_site",
            "name": "first_floor_height",
            "value": 4.0,
            "unit": "m",
            "scope": "whole_site",
            "enforcement": "HARD",
            "denominator": None,
            "source_note": "FOUNDER_STATED: Founder 2026-10-11／10-15 決定：首層 4 m",
        },
        {
            "id": "d2-c-standard_floor_height-whole_site",
            "name": "standard_floor_height",
            "value": 3.5,
            "unit": "m",
            "scope": "whole_site",
            "enforcement": "HARD",
            "denominator": None,
            "source_note": "FOUNDER_STATED: Founder 2026-10-11／10-15 決定：標準層 3.5 m（首層 4 m＋4×3.5 m = 18 m ≤ 20 m）",
        },
        {
            "id": "d2-c-road_width-road-primary",
            "name": "road_width",
            "value": 14.0,
            "unit": "m",
            "scope": "road:primary",
            "enforcement": "HARD",
            "denominator": None,
            "source_note": "ASSUMED: 沿用 D2-A 道路設定 primary 14 m",
        },
        {
            "id": "d2-c-road_width-road-secondary",
            "name": "road_width",
            "value": 10.0,
            "unit": "m",
            "scope": "road:secondary",
            "enforcement": "HARD",
            "denominator": None,
            "source_note": "ASSUMED: 沿用 D2-A 道路設定 secondary 10 m",
        },
        {
            "id": "d2-c-road_width-road-residential",
            "name": "road_width",
            "value": 6.0,
            "unit": "m",
            "scope": "road:residential",
            "enforcement": "HARD",
            "denominator": None,
            "source_note": "ASSUMED: local mapped to OSM highway=residential; D2 6 m",
        },
        {
            "id": "d2-c-rotation_step-whole_site",
            "name": "rotation_step",
            "value": 15.0,
            "unit": "degree",
            "scope": "whole_site",
            "enforcement": "HARD",
            "denominator": None,
            "source_note": "ASSUMED: 沿用 D2-A 旋轉步階 15 度",
        },
    ]


def build_d2c_draft_payload(project_id: str = PROJECT) -> dict[str, Any]:
    return {
        "id": D2C_ID,
        "actor_kind": "AGENT_AUTOMATION",
        "actor_session_id": D2C_ACTOR_SESSION_ID,
        "idempotency_key": D2C_IDEMPOTENCY_KEY,
        "allocation_policy": None,
        "notes": D2C_NOTES,
        "constraints": build_d2c_constraints(),
    }


def call(base: str, method: str, path: str, body: dict | None = None, params: dict | None = None, timeout: int = 60):
    url = base.rstrip("/") + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read() or b"{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read() or b"{}"
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"error": raw.decode("utf-8", errors="replace")}


def confirm(question: str) -> None:
    if input(f"\n{question} 輸入 y 繼續，其他鍵中止：").strip().lower() != "y":
        print("已中止，沒有送出這一步。")
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="D2-C 正式執行：建立並批准 D2-C 約束集草稿")
    ap.add_argument("--api", default="http://127.0.0.1:8795", help="API 服務網址（預設 http://127.0.0.1:8795）")
    ap.add_argument("--project", default=PROJECT, help=f"專案代號（預設 {PROJECT}）")
    a = ap.parse_args()

    print("================================================================================")
    print("D2-C 正式執行（約束集草稿建立與 Founder 決策批准）")
    print(f"API 伺服器：{a.api}")
    print(f"目標專案  ：{a.project}")
    print(f"約束集 ID ：{D2C_ID}")
    print("================================================================================\n")

    # 1. 檢查是否已經存在且已生效
    status_code, existing = call(a.api, "GET", f"/api/v1/projects/{a.project}/constraint-sets/{D2C_ID}")
    if status_code == 200:
        cs = existing.get("constraint_set", {})
        if cs.get("status") == "effective":
            print(f"✓ D2-C 約束集（{D2C_ID}）已經處於生效（effective）狀態，版本 revision {existing.get('revision')}。")
            print("無需重複批准。程序結束。")
            sys.exit(0)
        print(f"發現既有 D2-C 草稿，狀態：{cs.get('status')}，Digest：{existing.get('payload_digest')}")
        draft_body = existing
    else:
        # 建立草稿（冪等）
        print("1/2 建立 D2-C 約束集草稿（AGENT_AUTOMATION，冪等）...")
        draft_payload = build_d2c_draft_payload(project_id=a.project)
        status_code, draft_body = call(a.api, "POST", f"/api/v1/projects/{a.project}/constraint-sets", draft_payload)
        if status_code != 201:
            print("建立 D2-C 草稿失敗：", status_code, json.dumps(draft_body, ensure_ascii=False)[:500])
            sys.exit(2)
        print(f"✓ D2-C 草稿已建立：{D2C_ID}（revision {draft_body.get('revision')}）")

    digest = draft_body.get("payload_digest")
    if not digest:
        print("無法取得草稿之 payload_digest，中止。")
        sys.exit(2)

    # 2. 顯示草稿內容讓 Founder 確認
    print("\n--------------------------------------------------------------------------------")
    print("【D2-C 約束集內容清單】")
    print(f"  - 約束集 ID：{D2C_ID}")
    print(f"  - 內容摘要 (Digest)：{digest}")
    print("  - 包含四項 Founder 決定值：")
    print("    [1] far_upper_limit = 0.8 (land_area 分母) -> 新建 GFA 上限 146,873 m²（只計新建＋加蓋）")
    print("    [2] 新建 GFA 下限 85% (124,842.05 m²) -> （記載於 notes，現有型別僅支援上限，由驗證器把關）")
    print("    [3] 保留廠房 1–2 層計 -> （記載於 notes，現有型別無專屬保留層數欄位）")
    print("    [4] height_upper_limit = 20 m (最多 5 層: 首層 4 m + 標準層 3.5 m)")
    print("  - 沿用 D2-A 基準設定：")
    print("    [5] coverage_upper_limit = 0.35")
    print("    [6] road_width: primary 14 m, secondary 10 m, residential 6 m")
    print("    [7] rotation_step = 15°")
    print("  - 說明備註 (notes)：")
    for line in D2C_NOTES.split("\n"):
        print(f"      {line}")
    print("--------------------------------------------------------------------------------\n")

    confirm("2/2 【需要你的決策】批准 D2-C 約束集（constraint-set-d2-c-20261016）生效")

    key = getpass.getpass("請輸入決策密語（不會顯示）：")
    if not key:
        print("未輸入決策密語，中止。")
        sys.exit(1)

    decision_payload = {
        "target_id": D2C_ID,
        "target_type": "ConstraintSet",
        "target_version": "v1",
        "target_payload_digest": digest,
        "action": "Approve",
        "status": "approved",
        "reason": "Founder 正式批准 D2-C 約束集（FAR 0.8 / 新建 GFA 上限 146,873 m² / 高度 20 m 首層 4 m）",
        "actor_session_id": "founder-d2c-formal",
        "decision_key": key,
    }
    del key

    status_code, decision_result = call(a.api, "POST", f"/api/v1/projects/{a.project}/decisions", decision_payload)
    if status_code != 201:
        print("決策未成立：", status_code, json.dumps(decision_result, ensure_ascii=False)[:500])
        sys.exit(2)

    decision_id = decision_result.get("id")
    print(f"✓ 決策已記錄：{decision_id}")

    # 3. 驗證生效狀態
    status_code, verified = call(a.api, "GET", f"/api/v1/projects/{a.project}/constraint-sets/{D2C_ID}")
    if status_code == 200 and verified.get("constraint_set", {}).get("status") == "effective":
        print(f"✓ D2-C 約束集已成功生效（status: effective, revision: {verified.get('revision')}）。")
        print("結果已寫入正式帳本。請告訴 Commander「D2-C 跑完了」。")
    else:
        print("警告：決策已送出，但狀態讀回未顯示 effective，請交給 Commander 對帳：", verified)
        sys.exit(3)


if __name__ == "__main__":
    main()
