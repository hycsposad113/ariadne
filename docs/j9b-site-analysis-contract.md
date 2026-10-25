# J9b 基本基地分析 API 與方法契約

狀態：實作待 Claude 跨供應商審查／Founder 驗收。所有結果為探索性診斷，不是 HumanDecision、基地接受或規劃規則。

## API

`GET /api/v1/projects/{project_id}/site-analysis/basic?extent_id=…`

成功 `200 BasicResult`：`transit`（各方位、各交通方式最近站名／路線／步行距離／實際路徑）、`closest_transit_sides`（保留同距離並列，僅唯一時填 `closest_transit_side`）、`landuse`、`entrances`（到達潛力排序與主要來源路徑）、`overlay_wgs84`、`source_hashes`、`parameters`、`graph`、`origins`、`syntax`、`limitations`。路徑座標 EPSG:28992／m；地圖疊圖 WGS84。`formal_result_eligible=false`，`interpretation=ESTIMATED_ARRIVAL_POTENTIAL_NOT_OBSERVED_FLOW`。

`404`：project／extent 不存在或不屬於該 project。`409`：抓取未完成、所需檔缺失、manifest／檔案 hash 或 CRS／StudyArea 綁定失敗、Syntax pin 失敗。`422`：缺少 extent_id。GET 不寫 ledger、不建 HumanDecision、不啟動下載；舊 J9 沒有交通／用途檔的快照明確拒絕，不假裝已取得新範圍。

資料對應 project 的現有 active StudyArea，而不是直接將 SiteExtentDraft 當正式基地。須驗證 StudyArea 幾何檔 hash、CRS 及 acquisition extent 包含該幾何。粗範圍只供抓取，不改 C1／D1 或正式基地。

## 抓取與 QGIS

沿用 GenerationJobStore／GenerationJobRunner、append-only ExtentDataFetched／DatasetSnapshot 和檔案 manifest。handler 升版 `site-extent-fetch-v2`；未建立第二套 job 系統或 DB schema。

- OSM：單一 combined Overpass 查詢。道路外推至少 10 km；建物、landuse 與 amenity/shop/office/leisure/tourism 外推 1.5 km；public_transport/railway/bus_stop/ferry_terminal 外推 2 km。另附交通點所屬 route relation 的 name/ref/mode。保留原始回應、查詢、URL、date -u UTC、bytes、SHA-256、ODbL。
- BAG：pand 保持原 500 m；新增 verblijfsobject（gebruiksdoel、oppervlakte）1.5 km，WFS 分頁及 CC0 登記方式不變。
- 新增 `transit.geojson`、`pois.geojson`、`bag-uses.geojson`，都列入不可變 manifest files；GeoPackage 增加 transit／pois／bag_uses 層。
- OSM 自交建物／landuse 仍拒絕。只有實際被當作建物／landuse 的閉合 way 才套 polygon validator；觀光船線不再誤判為建物多邊形。合成測試證明無效建物／landuse 仍失敗。
- polygon multipolygon relations 尚未建立；POI／交通的 relation 成員幾何只取位置代表點，並保存 `location_method`。不是精確入口。
- 需 key 的 DSO／ruimtelijkeplannen API 保持 BLOCKED_NEEDS_KEY；公開規劃 WMS 僅為 raster，不能當法定 zoning。
- 舊回應離線重播必須同 URL／同 POST 查詢；不能拿舊的 500 m 回應宣稱新 1.5 km coverage。此次重播用新的完整查詢回應，未重送 HTTP。

## 方法規則卡 basic-site-assumptions-v1

所有下列推估參數標為 `ASSUMED_COMMANDER`，用 Pydantic 驗證並寫入輸出／參數 hash。它們沒有被轉成正式設計限制或人類決定。

1. **步行路網**：沿既有 regional_network 的 pedestrian 使用／通行政策篩選。每對相鄰 OSM source nodes 建 m 邊長；只有相同 source node ID 才接通，不將不同高度或幾何交叉自動連通。保留 `oneway:foot`。入口候選為路段與 StudyArea 邊界的交點；同座標去重、邊界共線道路不直接當入口。
2. **接線與路徑**：站點／POI／BAG 代表點只在最多 30 m 內投影到步行邊；路徑沿路網 Dijkstra 最短距離，包含明列的假設接線長度。同一邊的兩點直接沿邊相接，不繞到端點。搜尋上限 5,000 m；超出、未 snap 或不連通保留不可達／缺值，不改成零。接線未驗證牆、門、河道、垂直通行。
3. **方位**：以基地 centroid 為原點、N/E/S/W 四個 90° 扇區，交集基地外 0–500 m 環帶。以外圍 BAG point／multipoint centroid 分區；面積比例分母是有有效 `oppervlakte` 的 BAG 樓地板面積，不是物件數或土地面積。多用途物件平均分配面積（假設）；缺面積個數另列。
4. **OSM landuse**：各類 polygon 裁切扇區後類內 union，輸出 m² 與佔扇區環帶面積比例。不同類別重疊仍可能合計超過 100%；未標示空白不是可開發或公共空間。
5. **到達潛力**：來源＝基地外交通站點、POI、BAG 用途物件。`sum(weight × exp(-walking_distance_m / 800))`；所有可達來源參與每個入口的排序，顯示每入口前三條貢獻最大的路徑。權重為相對假設，不是班次或旅次量：bus/ferry/unknown=1、tram=2、metro/rail=3；shop=1.5，其餘 POI=1；住宅=.2、工業=.5、商業／教育=1.5、辦公／集會／醫療／運動／旅宿=1、其他=.2。多用途 BAG 平均權重，未知用途權重=0；可用模型參數覆寫並產生不同 hash。
6. **Syntax 疊加**：沿既有 syntax-context router 的 manifest pin 與 pedestrian 檔 hash 驗證。只在路徑邊與既有 Syntax 線在 2 m 內全邊相符時，取得 length-weighted NAIN／NACH 與 coverage。保留原本 EXPLORATORY／BLOCKED readiness。覆蓋至少 .8 時可顯示假設 multiplier `1 + .25 × mean(percentile_NAIN, percentile_NACH)`；少於 .8 時 multiplier=null。此版主排序使用全來源的距離潛力；Syntax 僅疊加主要路徑，不捏造全來源已校正總分（syntax_adjusted_potential=null）。未提供既有 Syntax 設定時回報 UNAVAILABLE。

## 前端

Site ribbon 的「基本基地分析／Basic site analysis」入口，獨立 panel + MapLibre 疊圖；可切換站點、最近步行路徑、土地使用扇區、主要到達路線。en／zh-TW 文案，顯示估計標示、狀態、來源 hash、假設、限制與缺失面積。既有 Site 2D／3D 保留，未改 `web/index.html` 或 `web/src/index.css`。

`web/j9-review.html`／`web/j9-review.tsx` 是隔離檢查入口，不是產品入口。實際瀏覽器存取 8963 被工具核准政策拒絕，沒有改用其他瀏覽器繞過；實際 WebGL／雙擊畫範圍走查未完成。TestClient 和 jsdom 測試不能代替瀏覽器驗收。
