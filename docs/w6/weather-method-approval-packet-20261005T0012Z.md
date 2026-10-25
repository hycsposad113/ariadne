# 天氣方法批准封包

狀態：**READY_FOR_FOUNDER**。這不是 PASS，不是 DatasetSnapshot 發布，也不是 HumanDecision。Live AI 同樣維持 **READY_FOR_FOUNDER**。

分支：`wp/w6-weather-e2`（worktree `Q5/w6-12-e2`，自 `1e3830f1ac48a368b0cc427993a7285184d9d0c3` 切出）。
建議採用的提案包：`artifacts/w5-weather-derived-method-proposal-20260926T115309Z`。
較早的 `20260926T114957Z` 對同一份原始檔給出相同的 derived EPW 與 mapping CSV；本封包以較晚那份 analysis 為準。

## 建議的 candidate

建議 Founder 批准 **candidate-01**：

`NLD_ZH_Rotterdam.The.Hague.AP.063440_TMYx.2011-2025.epw`

理由：

- 測站是 Rotterdam The Hague AP，WMO `063440`，與 candidate-02 同一站。嵌入註記的紀錄年數是 15 年，期間 2011–2025，比 candidate-02 的 2009–2023 更近。
- candidate-03 是另一站 Geulhaven AWS `063430`，嵌入註記只有 5 個來源年（1994–1998）。既有 diagnostics 已把它放在 01 與 02 之後。
- Founder 已指定的時間規則是 `Minute=0` 視為該小時結束。candidate-01 在這個假設下，正 DNI 且太陽在地平線下的小時是 1；同一檔用 hour_start 是 216、hour_midpoint 是 69。
- 取捨：candidate-02 在 hour_end 下的地平線下正 DNI 小時是 0。這份封包仍建議較新的 15 年檔，並把那 1 小時留在紀錄裡。Founder 可以改選 candidate-02；那是另一個 HumanDecision，不是這份建議的自動升級。

## 重現結果

2026-10-05 以 worktree 內的 `derive_minute_zero_as_hour_end` 在記憶體重算三份原始 EPW。沒有下載，沒有寫回原始檔或提案檔。三份重算位元組都等於提案裡的 `derived-minute60.epw`，還原後回到原始 sha256。每份 mapping 8760 列，`source_minute` 只有 0，`derived_minute` 只有 60。

candidate-01 再以 `sensitivity_direct_radiation` 重算。四個面（horizontal、south、east、west）在 -1、0、+1 小時的 kWh/m² 與 `candidate-01/analysis.json` 逐項相同。`scenario_e2_direction` 仍是 `NOT_ASSESSABLE_WITHOUT_SCENARIO_SENSOR_RESULTS`。原始檔 sha256 在重算前後相同。

| 檔 | 位元組 | SHA-256 |
|---|---:|---|
| 原始 EPW | 1593131 | `3c9a109d7f0b2e54c2b204d592bf5ec59774d16f36054bb89c284db4b5f7802a` |
| derived-minute60.epw | 1601891 | `d6cc646473f2805002e28c99d13eb0c6d5fa08d40734b8fb2c89dbaae1371369` |
| minute-row-mapping.csv | 1922534 | `df37de88155db44e4d7731bbca79e700666349e21c3b5d2db62e4dcbbe4479e5` |
| analysis.json | 6585 | `6abd39570fe5043a94170eac1a2cf1e683f38fd271d8b32b559758db3971adb0` |
| weather-diagnostics.json | 4345 | `8e619394a555680a0490cdef83e6d4b5570ba1ede340bcf2a8e42e36d27b3409` |

另外兩份只作對照，不是這次建議：

| candidate | 原始 SHA-256 | derived SHA-256 |
|---|---|---|
| 02 `…TMYx.2009-2023.epw` | `ed73b9e453d7cf36fe16dbe3d24d2ab025cac41939b31a300e736a10c6fd3813` | `bc9585b17a16429544770ba8ac1e0ac75b23eeaf4e4b76d5a09b76f01b79b431` |
| 03 `…Geulhaven.AWS.063430_TMYx.epw` | `ff3d49802ed5c201bfc8ad5c5be42d0bb99ae6aa1e3ca8ea486e4f42347cbd10` | `08850c8629b63a4f7dc27497df14e172de25a0e0b247def39414578aaef563b6` |

## 敏感度設計

- 基準是 hour_end。位移是 -1、0、+1 小時。
- 期間是六月至八月。每個小時的 DNI（Wh/m²）乘上水平、南、東、西四個面的正向入射餘弦，再換成 kWh/m²。這是方法敏感度的篩選代理，不是方案輻射結果。
- candidate-01 的面排序在 ±1 小時有變，標記 `orientation_proxy_order_changed=true`，`may_change_orientation_sensitive_comparison=POSSIBLE_FOR_NEAR_TIES`。
- 方案之間的比較方向目前無法判斷。沒有已核准的方案感測結果時，標籤是 `NOT_ASSESSABLE_WITHOUT_SCENARIO_SENSOR_RESULTS`。
- 將來同一個方法裡若已有方向，`label_hour_shift_comparison_direction` 只在 `INCREASED` 與 `DECREASED` 對調時標 `REVERSED`，方向相同或只碰到 `UNCHANGED` 時標 `NOT_REVERSED`。這個標籤不放行派送。

## DatasetSnapshot 草稿

執行者沒有把它寫進權威 DB。Founder 若批准，目標紀錄是：

- entity：`DatasetSnapshot`
- status：`DRAFT`，`designer_human_decision_id` 仍是 null
- parent：`m2-a03-r08-minute-semantics-20260919T154701Z` 的 candidate-01 原始 EPW，sha256 `3c9a109d7f0b2e54c2b204d592bf5ec59774d16f36054bb89c284db4b5f7802a`
- derived：上表的 `d6cc6464…` 與 mapping `df37de88…`
- method：`weather-derived-method-v1`，`Minute=0 -> Minute=60`，視為該小時結束
- 禁止把 `UNAPPROVED_PREVIEW`、`FIXTURE_ONLY` 或呼叫端傳入的 `APPROVED` 字串當成這筆快照

## 批准之後才做的發布

1. Founder 的 HumanDecision 點名 candidate-01、minute 規則，以及上表三個內容 hash（原始、derived、mapping）。
2. 指揮官把 DatasetSnapshot 寫入權威 DB，並綁定 `weather_snapshot_ref`。
3. 同一決定一併留下 `method_approval_ref`、`experiment_approval_ref`、`weather_pause_release_ref`。材料、反射、recipe 仍要各自核准；Ladybug screening 與 Honeybee verification 不共用 recipe。
4. 之後的執行包才可以改 `E2_WEATHER_PAUSE_ACTIVE`。派送走既有的 `GenerationJobStore` 與 `GenerationJobRunner`，不另做排程器。
5. 比較範圍沿用 E1：各方案先以自己的公共開放空間計分，成對差值用兩個範圍的交集（`COMMON_OVERLAP`）。這個範圍是幾何分析範圍，不是 legal right of way。
6. 跨方法只記方向是否一致。絕對值不相減。沒有已批准的 DatasetSnapshot 時，`refuse_formal_e2` 維持 `dispatch_allowed=false`，gate 維持 `READY_FOR_FOUNDER`。
