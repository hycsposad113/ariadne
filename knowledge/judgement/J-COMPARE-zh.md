# J-COMPARE 方案綜合判讀 v1.0.0

## 目的
在分數之外，提出 Ariadne 對多個方案的**綜合設計判斷**：每個方案的設計邏輯是否成立、真正的取捨是什麼、在不同設計優先順序下各自站得住的理由，以及選定方案下一輪最該修的地方。

## 觸發
- 比較頁打開四案並排或選定方案時，設計者按「請 Ariadne 判讀」。
- 任一方案指標、語法、形態檢核或氣候結果更新後（輸入 sha 變了才重跑）。

## 輸入組裝（確定性）
| 群組 | metric_id 格式 | 來源 |
|---|---|---|
| 強度與形態 | `scheme.<id>.fsi`、`.gsi`、`.osr`、`.l`、`.new_gfa_m2`、`.new_gfa_pct_of_cap`、`.building_count`、`.height_max_m` | fabric plans API（metrics） |
| 空間語法 | `syntax.<id>.<ped|bike|car>.main_street_pctl`、`.new_segments_pctl`、`.waterfront_pctl`；基準 `syntax.baseline.<…>` | `artifacts/net2/round-7/v3-export/net2-table-zh.md`、fabric plan `syntax_summary` |
| 形態檢核 | `check.<id>.failures`（id 清單＋中英說明） | plan `checks`、`check_explanations_*` |
| 環境摘要 | `e1.<id>.all.winter.mean_h`、`e1.<id>.street.winter.mean_h`、`e1.<id>.courtyard.winter.mean_h`、`utci.<id>.all.very_strong_pct`、`e3.<id>.eui_kwh_m2`、`e2.harbour_vs_mixed.*` | 同 J-CLIMATE |
| 設計意圖 | `intent.<id>.summary`（設計說明前 600 字）、`intent.<id>.fabric_concept` | `design_statement_markdown`、形態意圖書 |
| 設計者狀態 | `decision.selected_scheme`（目前 Founder 選定）、過去質疑紀錄 `contest.<n>.text` | 帳本（唯讀） |
| 基準 | `portfolio.q2.<metric>`（人類原設計對照組，若有） | portfolio baseline |

## 必讀知識單元
- 形態類型與密度：KU-MOR-023、KU-MOR-028、KU-MOR-031、KU-MOR-033、KU-MOR-035、KU-MOR-039、KU-MOR-041、KU-MOR-043、KU-MOR-047、KU-MOR-049、KU-MOR-051、KU-MOR-079、KU-MOR-080
- 紋理案例（本案四種紋理）：KU-MOR-100、KU-MOR-101、KU-MOR-102、KU-MOR-103；港口再生先例：KU-MOR-083、KU-MOR-084、KU-MOR-090、KU-MOR-091
- 空間語法用法與限制：KU-SYN-009、KU-SYN-010、KU-SYN-012、KU-SYN-014、KU-SYN-019、KU-SYN-021、KU-SYN-057、KU-SYN-061
- 公共空間與界面：KU-PUB-009、KU-PUB-013、KU-PUB-027、KU-PUB-029
- 氣候（只作摘要層級）：KU-CLI-043、KU-CLI-055

## 判斷框架
**L1 設計邏輯是否自洽**：每個方案的紋理概念（意圖書）與實際生成結果（強度、路網、量體）是否一致？說不通的地方是什麼？
**L2 移動與連結**：主街、新設計段、水岸三種語法結果代表的設計意義；新設計段要和整體分開讀（避免既有 Keileweg 段灌水）；語法是潛力不是人流（KU-SYN-014、KU-SYN-057）。
**L3 形態與強度**：Spacematrix 位置（FSI／GSI／OSR／L）對應什麼類型；GFA 是否靠過高覆蓋或過窄中庭達成；形態檢核失敗是「可修」還是「結構性」。
**L4 公共空間品質**：開放空間比例與分布、界面連續性、水岸可及；氣候摘要（冬季日照、夏季熱壓力）作為公共空間品質的一部分，不單獨排名。
**L5 取捨與條件式排序**：把方案的長處與代價放在 2–3 組不同的設計優先順序下（例如「步行連結優先」「冬季公共空間優先」「建築能效優先」），各自說明哪個方案站得住、為什麼。
**L6 選定方案的下一輪**：若已有選定方案，指出它最值得修的 1–3 點，以及修了之後可能犧牲什麼。

## 收斂規則
- headline 是 Ariadne 對整組方案或選定方案的一句判斷，不是排名（例如「港埠方案的步行骨架是四案最有說服力的，但它的冬季公共空間品質目前不足以支撐『最佳』的說法」）。
- 不宣告總冠軍；條件式排序寫在 reasoning 的 L5。
- 若設計者的選定與 Ariadne 的判斷不一致，要明說並給理由，同時尊重設計者決策權（「我的判斷與目前選定不同，原因是…；若你重視…，選定仍成立」）。
- `revision_directions` 至少一項針對選定方案（若有）。

## 驗證
- 數字白名單、metric id 存在、KU 白名單（同 README）。
- 禁止詞：「最佳方案」「冠軍」「勝出」「排名第一即採用」「已核准」「批准」「正式接受」「人流量」「實測人流」。
- 語法相關句子若出現「人流」「行人量」，必須同句含「潛力」或「不是實測」，否則拒絕。

## 評測案例
1. 四案＋選定港埠：預期 headline 不含排名；L5 至少兩組優先順序且結論不同；修正方向指向港埠冬季公共空間或形態檢核失敗項（南碼頭立面、3 m 退縮）。
2. 拿掉氣候輸入：預期 limitations 註明 DATA_GAP，L4 不引用氣候。
3. 院落島：預期指出整體語法過門檻是因含既有 Keileweg 段、新設計段偏低（37.6）。
