# Live AI 驗收封包

狀態：**READY_FOR_FOUNDER**。這不是 PASS，不是合併，也不是 HumanDecision。

分支：`wp/w6-live-ai`（worktree `Q5/w6-12-e2`，自 `27174d92e4b52bb34055c52a502f33d41d2aa753` 切出）。
設定檔：`config/model-providers.json` 的 profile `openai-gpt-4o`，模型 `gpt-4o`，每週上限 200。
本封包不要求執行者設定旗標、讀取鑰匙、重啟 8795／5195，或打任何付費 API。

## Founder 與指揮官要做的事

1. 在 OpenAI 專案後台建立專用 key，並設定用量上限。帳號的模型清單必須包含 `gpt-4o`。程式在清單裡找不到這個模型時會停在 `LIVE_AI: BLOCKED_CONFIGURED_MODEL_NOT_FOUND`，不會改叫別的模型。
2. 把 key 存進 macOS Keychain。這份程式讀的服務名稱是 **`urban-design-openai-gpt-4o`**（`config/model-providers.json` 的 `keychain_service`）。計畫文字裡的 `urban-design-openai` 不是這支程式實際查詢的服務名稱。
3. 由指揮官設定 `PROJECT_AI_AUTHORIZED=1`，並以 `--ariadne-live` 啟動或重啟。`--ariadne-live` 會把 `ARIADNE_LIVE=1`。Ariadne 兩道門都要開：`ARIADNE_LIVE` 與 `PROJECT_AI_AUTHORIZED`。程式**沒有**讀 `PROJECT_OPENAI_AUTHORIZED`。
4. 驗收呼叫：基地說明 1 次，加上方案說明 1 次。預估 2–4 次，計入共用的每週 200 次。只要已經寫下 ModelRun 再送出，失敗或失聯也佔用次數。

執行者不要代做上述步驟。

## 預期的 ModelRun

送出前先寫一筆 `PENDING`。終態只有 `SUCCEEDED`、`MODEL_FAILED`、`OUTCOME_UNKNOWN`。

驗收時應看得到：

- `profile_id`：`openai-gpt-4o`
- `model_id` 與 `configured_model_id`：`gpt-4o`
- `actual_model`：供應商回傳的模型字串；請求 body 的 `model` 仍是 `gpt-4o`
- `status`、`validation_result`（`PASSED`／`FAILED`／`NOT_RUN`）
- `prompt_hash`、`request_sha256`、`response_hash`
- `budget_sequence`、`created_at`、`schema_version`（`site-critic-response-v1`）
- `provider_metadata` 只留 http 狀態、交付狀態與 token 計數這類欄位，不含 key

送出的 body 只有 evidence bundle：模型名稱、提示、公開衍生值與方案指標。不含 key、檔案路徑或個人資料。Key 只出現在 `Authorization` 標頭。

重開同一個 sqlite 後，本週 ModelRun 筆數仍在，不會歸零。滿 200 筆時回 `LIVE_AI: BLOCKED_BUDGET`，而且不會呼叫 transport。

## 驗收畫面

Ariadne 面板用 `data-screen-state` 分開四種狀態。API 的 `mode` 仍只有 `LIVE` 或 `OFFLINE`。

| 畫面 | 英文 | 繁體中文 | 何時 |
| --- | --- | --- | --- |
| OFFLINE | Offline | 離線 | 沒有阻擋碼的離線範本 |
| LIVE | Live AI | 即時 AI | `mode=LIVE` 且沒有阻擋或失聯 |
| BLOCKED | Blocked | 已阻擋 | 旗標、授權、額度、401、429、模型清單失敗 |
| OUTCOME_UNKNOWN | Outcome unknown | 結果未知 | 送出後逾時或失聯 |

`NON_AI: DETERMINISTIC_TEMPLATE` 維持離線，不算 live 通過。

## 失敗時怎麼處理

- **401**：模型清單或 chat 都只打一次。回應本文不留在結果裡。供應商狀態是 `LIVE_AI: REQUEST_REJECTED`。已送出的那次記成 `MODEL_FAILED`。同一個 OpenAI transport 不會自動重送。路由器只在 401 或 403 時才會繼續下一個已啟用的 profile。驗收時不要把 CLI 的後備回答當成 GPT-4o 成功。
- **429**：模型清單失敗是 `LIVE_AI: MODEL_LIST_FAILED`；chat 失敗是 `LIVE_AI: REQUEST_REJECTED`。不重試，也不改模型。請求裡的模型仍是 `gpt-4o`。
- **逾時或送出後例外**：`LIVE_AI: OUTCOME_UNKNOWN`。先核對已寫下的 ModelRun，再決定要不要由人重送。程式不會自動重送，也不會改走下一個 profile。
- **引用錯誤**：方案識別碼不是目前證據卡的 `scenario_id`、單位不符、半徑不符、修訂或來源 hash 過期，都會被 `SiteCriticService.validate_critic_response` 拒絕。若供應商狀態已是 `LIVE_AI: ACTIVE`，這筆記成 `MODEL_FAILED`，不是 `SUCCEEDED`。
- **額度**：持久化的 200 筆在重開 store 之後仍然擋住，transport 呼叫次數是 0。

## CLI 隔離風險

Live 驗收路徑是 OpenAI HTTP profile `openai-gpt-4o`，不是 CLI。

同一份設定的 `fallback_order` 仍包含已啟用的 `codex-cli`（模型 `gpt-6-luna`）與 `claude-cli`。`CliSubprocessCriticProvider` 在 Codex profile 開啟 Ariadne persona 時，會讀取儲存庫裡的 `integrations/hermes/ariadne/SOUL.md`。因此 CLI 隔離在這條分支上還沒有被證明。

`wp/w5-ai-routes`（HEAD `9154ebb5070b91633c10569f66a59fda5e3f9550`）是 Codex 的分支，這次沒有修改，也沒有把該提交抄過來。

若日後要讓 CLI 成為可選路徑，建議用 macOS `sandbox-exec`：工作目錄只用空白暫存目錄，拒絕讀取儲存庫與權威資料庫，網路只留預定端點，並用測試證明程序讀不到 `SOUL.md`。這份提案沒有在這包裡執行，也沒有啟動 CLI。GPT-4o 驗收應選定 `openai-gpt-4o`，不要把 CLI 後備結果當成該模型的通過。

## 這包已用假 transport 檢查的項目

`tests/test_week6_live_ai_fake_transport.py` 注入假 transport，並擋下 `urlopen` 與 Keychain 讀取。覆蓋成功、401、429、逾時、`OUTCOME_UNKNOWN`、錯誤或過期引用、額度用盡與重開。沒有真實 API 呼叫。

畫面測試：`web/src/components/AriadnePanel.test.tsx` 分得出上述四個標籤，繁體中文走 `web/src/i18n/shell.ts`。
