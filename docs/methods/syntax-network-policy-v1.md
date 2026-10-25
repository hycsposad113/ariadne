# 路網政策 `syntax-network-policy-v1`

**版本：** 2026-09-25／v1  
**狀態：** `EXPLORATORY_PENDING_DESIGNER_APPROVAL`（設計者確認前標為 EXPLORATORY）  
**依據：** `docs/superpowers/plans/2026-09-25-week4-closeout-plan-zh.md` WC-3 第 4 點、`docs/decisions/2026-09-25-plan-decisions-zh.md` PD-15、PD-17。

---

## 1. 納入與排除之 `highway` 類別

### 納入（公共領域可及路網）
- `primary`, `primary_link`
- `secondary`, `secondary_link`
- `tertiary`, `tertiary_link`
- `unclassified`
- `residential`
- `living_street`
- `pedestrian`
- `footway`
- `cycleway`
- `path`
- `steps`
- `service`

### 區域尺度條件納入（或用於區域聯絡）
- `motorway`, `motorway_link`
- `trunk`, `trunk_link`
*(註：在 800m 步行尺度預設排除無人行權限者；在 10km 區域尺度可作為車行/整體骨幹網絡)*

### 排除
- `construction`（施工中）
- `proposed`（規劃中）
- `abandoned`, `disused`（廢棄）
- `raceway`（賽道）
- `corridor`, `platform`, `elevator`（建築內部或特殊設施）

---

## 2. Access 存取控制規則

- 若 `access=private` 或 `access=no`，預設予以排除。
- 若帶有 `foot=yes`、`foot=designated`、`foot=permissive` 或 `bicycle=yes`，則覆寫並保留可及性。
- 未標註 access 者預設為開放公共領域。

---

## 3. 立體交叉規則（Grade Separation: layer / bridge / tunnel）

- 預設層級（default layer）為 0。
- 屬性鍵包含：`layer`、`bridge`、`tunnel`、`level`。
- **交叉判定原則：**
  - 兩條 OSM 道路在二維平面上存在交點（XY crossing）：
    - 若兩條路共享同一個 OSM 節點 ID，且層級相符：認定為平面路口（at-grade junction），連通計算。
    - 若兩條路**不共享** OSM 節點 ID，或其 `layer`/`bridge`/`tunnel` 屬性不一致：認定為立體交叉（grade-separated crossing，例如高架橋跨越地面道路、地下道穿過鐵路等），**不得形成平面路網節點**。
  - **PST 處理機制：** PST 的 `CreateSegmentMap` 預設會在二維線段交會處打斷路段。為防止立體交叉被錯誤打斷成路口，先計算所有立體交叉點座標，作為 `unlinks` 參數傳入 PST `CreateSegmentMap(AXIAL_OR_SEGMENT, ..., unlinks=unlink_points)`，確保立體交叉保持上下分離不連通。

---

## 4. 尺度定義

| 尺度標籤 | 半徑 | 分析目標 | 緩衝範圍 |
|---|---|---|---|
| 局部尺度 (Local Scale) | 800 m | 行人可及性與步行空間整合度 | 基地外擴 1.2–2 km |
| 中距尺度 (Mid Scale) | 2,000 m | 微移動與行政區級動線流動 | 基地外擴 4 km 與 6 km（穩定性驗證） |
| 區域尺度 (Regional Scale) | 10,000 m | 大都會級交通動線與中介度 | 基地外擴 15 km 與 20 km（省界檢核） |
