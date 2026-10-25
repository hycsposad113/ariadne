# P1：既有方案唯讀預覽與選單修復 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 一次領一個 task。

**Goal:** 先讓使用者看見已生成的十個方案，且側欄不再溢出。
**Architecture:** 既有 persisted Scenario API 不變；新增無 store 依賴的 read-only catalog 與獨立顯示元件。視覺修復先完成獨立 review。
**Tech Stack:** FastAPI、Pydantic、Shapely、React、SVG、既有 PNG、pytest/Vitest。

## Task P0：處理已完成的 sidebar patch

Files：只讀 `/Users/jackhsieh/.codex/worktrees/q5-sidebar-overflow/project/web/src/App.tsx` diff；不重新實作。
- [ ] 核對實際 branch、diff，應只把固定 sidebar 设 `flex: 0 0 330px`，tabs 改三欄 grid；其他差異另列。
- [ ] 對照先前 1920×1080、1440×900、1280×800 的報告；若沒有保存的 browser artifact，於 disposable preview 補一份 bounds JSON／截圖，不操作使用者 5195 分頁。
- [ ] 跨 provider review：原作者 OpenAI，AGY/Claude 只能審同一 diff hash；前端相關測試及 build。不要把新版 App 整檔拷回 main。
- [ ] Claude review 與 Founder merge permission 由既有治理處理；採用前檢查使用者 unsaved draft，不能用強制 reload 解決。

CP-P0：可點到所有五個 tab 與 AI settings，button bounds不越 sidebar；center不重疊。報 READY_FOR_REVIEW／MERGED／ACTIVATED 三者真實狀態。

## Task P1：typed readonly catalog

Create：`src/urban_design/morphology/preview_catalog.py`、`tests/test_preview_catalog.py`。
Inputs：configured root、已核對 manifest digest；root 未設定即 DISABLED。
New interfaces：
```python
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict

class PreviewIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    intensity: Literal["A", "B"]
    strategy_id: str
    status: Literal["UNAPPROVED_PREVIEW"]
    human_decision_created: Literal[False]
    generator_version: str
    run_created_at: str | None
    generator_commit: str | None
```
Implement `load_catalog(root: Path, manifest_sha256: str) -> PreviewCatalog` 與 `get_asset(catalog, identity, kind) -> VerifiedAsset`；PreviewCatalog 包含 tuple identities、limits、comparison hash、input refs。VerifiedAsset 包含 bytes、media_type、sha256；驗證後服務同一份 bytes，避免檢查後再開路徑的 TOCTOU。

精確步驟：
- [ ] 先寫 valid／corrupt asset／wrong CRS／path escape 反例；執行 pytest 指定節點，確認新增行為 RED。
- [ ] manifest 自身 digest 必須等於 server config 的 pinned digest；否則拒絕，不能讓攻擊者一起改 data＋manifest 後通過。
- [ ] 限定 comparison／manifest 的 schema，禁止 NaN/Infinity/duplicate JSON keys；candidate identity 在 comparison、metrics、recipe、GeoJSON 一致。
- [ ] manifest paths 僅接受相對路徑；resolve 後必須在 root 內；拒絕 `..`、絕對路徑、逃逸 symlink；未列 asset 不服務。
- [ ] 所有列檔 size/hash 匹配，geometry finite/nonempty/valid、CRS EPSG:28992。缺檔／未知 schema／不一致 status 回明確 error，不回零方案。
- [ ] 對原 run 缺執行時間／source commit 保留 null＋UNKNOWN limitation；不由 mtime 或 current HEAD 補值。只是 preview，不設假 provenance。
- [ ] 保留六個 retained features 的 confidence、UNKNOWN floor、known-part FAR；row來源信心不可變成 HumanDecision。

測試命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PROJECT/.venv/bin/python" -m pytest -q -p no:cacheprovider tests/test_preview_catalog.py`
Fixture tree只包含2個縮小候選與PNG bytes（測結構/hash）；real-input integration獨立讀現有run，不能以fixture宣稱10個實檔完整。
CP-P1：實檔5A＋5B、52檔驗證；缺漏與篡改拒絕；原檔未改。

## Task P2：GET-only API

Create `src/urban_design/morphology/preview_api.py`、`tests/test_morphology_preview_api.py`。
Integration owner modify `src/urban_design/api.py`、`scripts/run_workspace_server.py`。

Routes（全為新介面）：
| Method/path | Response | Failure |
|---|---|---|
| GET /api/v1/morphology/previews | catalog status＋A/B cards | disabled→200 status DISABLED；configured malformed→503 |
| GET /api/v1/morphology/previews/{intensity}/{strategy_id} | typed detail/asset URLs | unknown ID→404；integrity drift→409 |
| GET /api/v1/morphology/previews/{intensity}/{strategy_id}/assets/{kind} | allowlisted image／GeoJSON bytes | unknown kind→404；containment failure→400 |

kind enum：plan、axonometric、geometry；不可由 client 傳 filename、root 或任意 URL。
新增 `--morphology-preview-root` 與 `--morphology-preview-manifest-sha256`；兩者須同時存在或同時缺省，configuration error 啟動前退出。
- [ ] 先測 root absent、hash drift、路徑穿越、同api原 Scenario listing不變。
- [ ] API module 不接 ProjectStateStore，不新增 POST/PUT/DELETE。
- [ ] serializer 去除本機絕對路徑，保留 hashes、method version、source標籤。
- [ ] GET前後比較 disposable store entity/ledger counts，另以readonly real bundle smoke核對無來源修改。
- [ ] tests：preview API＋`tests/test_scenario_api.py`，不呼叫 live sources。
CP-P2：read-only 結構保證＋測試保證；新 catalog 不能成為批准、編輯或 climate input。

## Task P3：前端預覽面板

Create `web/src/components/MorphologyPreviewCatalog.tsx`、`.css`、`.test.tsx`。
Modify `web/src/components/ScenarioStudio.tsx`、`ScenarioStudio.test.tsx`，不與sidebar worker搶App.tsx。

- [ ] 先測 catalog被停用、loading、error、5+5成功狀態；不得將error渲染為「0個方案」。
- [ ] UI明確分頁「既有探索預覽」／「可編輯方案」，preview沒有接受、編輯、生成新scenario的按鈕。
- [ ] A/B列出其假設強度；不把A/B當等級或好壞，無winner。
- [ ] plan與axonometric image可下載；地圖坐標使用實際bbox。SVG x/y投影核心：
```typescript
export function projectPoint(x: number, y: number, b: [number, number, number, number], width: number, height: number) {
  const [minX, minY, maxX, maxY] = b;
  const scale = Math.min((width - 32) / Math.max(maxX - minX, 1), (height - 32) / Math.max(maxY - minY, 1));
  return [16 + (x - minX) * scale, height - 16 - (y - minY) * scale];
}
```
- [ ] bbox不能 clamp到0；保留holes與MultiPolygon。point投影是2D圖紙，不是lon/lat地圖轉換。
- [ ] 顯示 retained confidence、unknown floors、known-part FAR 與generator provenance缺口，全部可點開，不以黃色警告遮住整張圖。
- [ ] Vitest測no POST；真實Chromium在disposable API/ports載入run-01，切A/B與image，確認全部10個可見。
CP-P3：使用者可以看現有成果；viewer可用不代表正式Scenario流程完成。

執行止點：交付diff、test artifacts、預覽截圖與啟動config。任何正式runtime重啟需先確認草稿；不自動import preview到store。

## 共同執行契約

本文件與 `2026-09-30-site-analysis-generation-master-zh.md` 同版使用。一次只領一個task，先RED再GREEN；原始輸入只讀、每個CP更新shared event。所有新符號／route為planned，既有fixtures成功不代替live驗證。尚未取得main merge／runtime activation批准時，交付reviewable diff，不自行部署。
