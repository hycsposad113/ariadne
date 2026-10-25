# E1 草案日照比較（2026-10-04）

這是執行者在 DB 副本上的結果，不是 Founder 驗收，也不是正式 HumanDecision。

## 比較

- 基準：`formal-dict-3da03eb0172d-grid-mixed-f764c233baa3`
- 比較：`formal-dict-3da03eb0172d-common-mixed-98854aff5f7b`
- 引擎：`ladybug-sunpath+ladybug-radiance`
- 計畫標籤：`E1_PLAN: DRAFT_DOMAIN_FOUNDER_2026-10-04`
- 計畫狀態：`DRAFT_UNAPPROVED`
- EvidenceCard：`unverified`
- 客戶端 101.161 秒；伺服器 `elapsed_seconds` 93.011
- 基準 6209 點、44.696 秒、公共空間 154926.7485 m²
- 比較方案 6212 點、43.981 秒、公共空間 155364.1373 m²
- 共同重疊配對 5763 點；`delta_mean_hours` 0.224406
- 3 月 21 日只供參考：基準平均 7.634885 小時、中位 8.75、≥2 小時 5893（94.9106%）；比較方案平均 7.756157、中位 9.0、≥2 小時 5830（93.8506%）
- 交叉檢查 PASS。分層抽樣 48／5763，種子 20261004。基準平均絕對差 0.151，比較方案 0.1458，上限 0.25 小時
- 缺的基地與水域來自已批准的工作區設計範圍與 BGT waterdeel，沒有改寫既有 GeoJSON，也沒有編造建物高度

## 圖

- `g2-panel-expanded-before-run.png`：Compare 階段、面板展開、草案標籤
- `g2-panel-maps.png`：同一面板、grid-mixed 對 common-mixed、兩張日照圖、共用色階 0.0–27.8 小時、未驗證
- `g2-sun-maps-shared-scale.png`：同一份結果的可讀散點圖，共用色階

面板圖是 Google Chrome 154 無頭模式打開臨時 Vite `127.0.0.1:5280`，API 指向 DB 副本的 `127.0.0.1:8880`。Playwright 未安裝，也沒有下載。為了不重跑 Radiance，瀏覽器的 simulate POST 被回放成已完成的回應；伺服器日誌只有 OPTIONS，沒有第二次 POST。正式 DB SHA-256 前後都是 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`。

## 給指揮官的計畫批准摘要（尚未批准）

預設草案 `get_default_draft_plan()` 的內容雜湊是 `sha256:d13778890802493fd41e4599527810be8545d4ee9b8832f75b6aaf63bea0224b`。若存成 Artifact，id 會是 `artifact-e1-plan-d13778890802493fd41e4599`。這份雜湊沒有寫進正式 DB。Founder 要用自己的密語批准；執行者沒有讀密語，也沒有建立正式 HumanDecision。草案位元組一改，就會是另一個 artifact id，舊批准不會跟著走。
