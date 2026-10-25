# Ariadne —— Rotterdam M4H 都市設計 AI 協同夥伴架構與操作指南

## 1. 角色定位與背景 (Identity & Mission)

**Ariadne** 是鹿特丹 Makers District（M4H, Merwe-Vierhavens）都市設計平台的專屬 AI 夥伴。

在整個設計推演過程中，Ariadne 的角色是設計者 **Jack** 的專業對話者與協同分析助手：
1. **先證據、後建議**：所有論述必須引用具體驗證的證據卡（Evidence Cards，如 `card-m2-001`）與分析論斷（Claims，如 `claim-m2-001`），絕不憑空推論。
2. **空間語法嚴謹警語**：呈現 Integration、Choice、Connectivity 等軸線或線段測度時，必須嚴格標明「**空間語法測度反映拓撲與幾何配置之可達性，不等於實際人流或交通量預測**」。
3. **對照原設計基準**：在審視與評論新生成的設計方案時，主動比對 Jack 於 Q2 Portfolio 的原始方案（容積率 FAR ~2.85、15m 親水公共長廊、保留工業筒倉等歷史遺產）。
4. **恪守憲法底線**：遵循平台核心法則——
   > **LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.**
   
   Ariadne 僅產出未核准之「草稿（DRAFT）」或「假設預覽（ASSUMED Preview）」，絕不建立 `HumanDecision`，絕不詢問、記錄或代持決策密語。

---

## 2. 系統架構 (System Architecture)

Ariadne 支援雙重執行路線：
- **Hermes Profile 路線**：以獨立 Profile 及 Skills 運行於 Hermes Agent 框架，透過 Model Context Protocol (MCP stdio) 呼叫平台。
- **Codex CLI 路線**：作為 `site_critic` 之 system persona，直接注入 `SOUL.md` 提示詞引導方案評論。

```
+-----------------------------------------------------------------------------------+
|                                  Jack (Designer)                                  |
+-----------------------------------------+-----------------------------------------+
                                          |
        +---------------------------------+---------------------------------+
        | (Route A: Interactive Agent)                                      | (Route B: Automated Critic)
        v                                                                   v
+-------------------------------+                                   +-------------------------------+
|     Hermes CLI / Profile      |                                   |       Codex / Claude CLI      |
|    (integrations/hermes/      |                                   |  (site_critic persona switch: |
|           ariadne/)           |                                   |     use_ariadne_persona)      |
+---------------+---------------+                                   +---------------+---------------+
                |                                                                   |
                | stdio (MCP Protocol)                                              |
                v                                                                   |
+-------------------------------+                                                   |
|       Ariadne MCP Server      |                                                   |
| (src/urban_design/ariadne_mcp)|                                                   |
| - 9 Tools (Read/Draft/Critique|                                                   |
| - Built-in Guardrails (PD-14) |                                                   |
+---------------+---------------+                                                   |
                |                                                                   |
                | HTTP REST (FastAPI, default http://127.0.0.1:8795)                |
                v                                                                   v
+-----------------------------------------------------------------------------------+
|                         FastAPI Core Application & Engine                         |
|                            (src/urban_design/api.py)                              |
+-----------------------------------------------------------------------------------+
                                          |
             +----------------------------+----------------------------+
             v                                                         v
+--------------------------+                             +--------------------------+
|  Deterministic Analysis  |                             |   Authoritative Store    |
| - Space Syntax Engine    |                             | - SQLite Event Ledger    |
| - Climate / Wind / Shadow|                             | - Evidence & Claims Repo |
| - Constraint Sets        |                             | - Portfolio Baseline     |
+--------------------------+                             +--------------------------+
```

---

## 3. 與 TREK 旅行專案對照 (Comparison with TREK)

Ariadne 承襲了 Jack 於旅行專案 `TREK` 驗證成功的 MCP 實踐，並針對都市設計的工程憲法進行了領域強化：

| 設計構面 | TREK 旅行專案 (`/Users/jackhsieh/travel/TREK`) | Ariadne 都市設計平台 (`w5-ariadne`) |
| :--- | :--- | :--- |
| **通訊協定** | FastMCP stdio 伺服器 | `mcp.server.mcpserver.MCPServer` (MCP 2.2+ stdio) |
| **Provider 策略** | Provider-neutral，支援多模型切換 | Provider-neutral（Hermes 支援 Anthropic/OpenAI；平台支援 Codex CLI / API） |
| **憑證分離** | 零憑證發行包，依賴本地 OAuth / Keychain | `integrations/hermes/ariadne/config.yaml` 絕無金鑰，由 Jack 本地完成 OAuth |
| **技能架構** | Skills 模組化設計（`SKILL.md`） | 5 大都市設計技能（基地分析、約束草擬、預覽生成、方案評論、方案對照） |
| **工具計算屬性** | 旅行時間估算、地點檢索 | **確定性數值守門**：空間語法幾何網絡、微氣候模擬、容積計算，嚴禁 LLM 捏造 |
| **決策權限控制** | 使用者確認行程清單 | **嚴格憲法隔離 (PD-14)**：禁止代持或要求決策密語，所有輸出嚴格標註 `AGENT_AUTOMATION` |

---

## 4. 安裝與設定指南 (Installation & Setup)

> [!IMPORTANT]
> 依據工程憲法與安全規範，**執行者嚴禁自行安裝 Profile 或啟動 Gateway 服務**。發行包安裝由 **Commander** 執行，金鑰與 OAuth 登入由 **Jack** 親自操作。

### 步驟 A：Commander 安裝 Hermes Profile
Commander 在具有適當權限之終端機執行發行包安裝：
```bash
# 從 w5-ariadne 工作目錄安裝發行包
hermes profile install ./integrations/hermes/ariadne
```
安裝完成後，Hermes 會在 `~/.hermes/profiles/ariadne/` 建立 Profile 檔案並載入技能與 MCP 設定。

### 步驟 B：Jack 登入模型 Provider (零金鑰外洩原則)
發行包中預設採用 `anthropic` 作為推理 provider，模型為 `claude-3-7-sonnet`。Jack 需在個人環境執行 OAuth 授權：
```bash
# 透過 Hermes 內建 OAuth 流程登入（或依個人偏好選擇 openai / google）
hermes auth login anthropic
```

### 步驟 C：Codex CLI 路線啟用 Ariadne Persona
若希望在批次或 CLI 評論工作流程中使用 Ariadne 人格，可在 `config/model-providers.json` 中將 `codex-cli` 的 `use_ariadne_persona` 設為 `true`：
```json
{
  "active_critic_profile": "codex-cli",
  "critic_profiles": {
    "codex-cli": {
      "provider": "codex-cli",
      "model": "gpt-6-luna",
      "use_ariadne_persona": true
    }
  }
}
```

---

## 5. MCP 工具清單與功能 (Tools Inventory)

Ariadne MCP Server 提供 9 項標準工具（透過 stdio 暴露）：

| 工具名稱 | 類型 | 說明與輸入參數 | 憲法約束與輸出特徵 |
| :--- | :--- | :--- | :--- |
| `get_site_analysis` | 唯讀分析 | 取得 M4H 基地已驗證分析摘要、證據卡與 24 項 Claims。<br>`project_id`: 專案識別碼 | 附帶具體 Evidence ID 與權威雜湊。 |
| `get_syntax_layers` | 唯讀分析 | 取得空間語法 6 個核心測度層（整合度、選擇度、連通度等）。<br>`radius`: 拓撲半徑 (n, r1200, r400) | **強制附帶空間語法警語**，列出五級分位與分析邊界。 |
| `get_surrounding_context_summary` | 唯讀分析 | 取得 Galileo、Bunkerdorp、Merwehaven 等周邊街區關係。<br>`project_id`: 專案識別碼 | 呈現邊界條件與過渡銜接要求。 |
| `list_scenarios` | 唯讀檢索 | 列出所有已計算或草稿方案，標明狀態（APPROVED / ASSUMED）。<br>`project_id`: 專案識別碼 | 清楚標示 ASSUMED 預覽方案。 |
| `compare_scenarios` | 唯讀比較 | 比對兩個指定方案，或將新方案與 Jack 原設計基準（Q2 Portfolio）比對。<br>`scenario_a`, `scenario_b`, `include_portfolio_baseline` | 包含 FAR、親水廊道寬度、綠覆率與遺產保留比率。 |
| `draft_constraints` | 草擬工具 | 將自然語言設計意圖轉換為草稿 `ConstraintSet`。<br>`natural_language_intent`, `target_parameters` | **標註 `status: DRAFT`**，actor 標註為 `AGENT_AUTOMATION`，不寫入生效配置。 |
| `run_preview_generation` | 預覽生成 | 根據草擬約束觸發確定性引擎生成未核准預覽。<br>`draft_constraint_set`, `seed` | **方案狀態為 `ASSUMED`**，明確警示需 Jack 簽署核准方可生效。 |
| `critique_scenario` | 審查評論 | 針對指定方案從空間品質、微氣候、結構連結性提出結構化評論。<br>`scenario_id`, `focus_areas` | 記錄完整 `ModelRun` 元資料，明確列出支持與反對證據。 |
| `explain_decision_needed` | 決策摘要 | 列出目前需由 Jack 決定的事項（如邊界變更、約束啟用）。<br>`project_id`: 專案識別碼 | **僅彙整決策點**，絕不代為裁決，不要求密語。 |

---

## 6. 工程憲法與安全護欄 (Constitutional Guardrails)

在 `src/urban_design/ariadne_mcp/guardrails.py` 與 `tools.py` 中，程式級別貫徹了以下守則：

1. **嚴禁代持或要求決策密語 (PD-14 決策安全)**
   - 任何工具若接收到含有 `passphrase`、`secret`、`confirm_decision` 或 `HumanDecision` 意圖的請求，立即觸發 `assert_no_human_decision_attempt` 拋出例外中斷。
   - 人機決策邊界不可逾越：人類決策必須由 Jack 於實體終端親自輸入確認。

2. **嚴格 Agent 行為元資料標記**
   - 任何由 Ariadne 經手的寫入、草案或預覽，強制經由 `enforce_agent_actor_metadata` 附加：
     ```json
     {
       "actor_kind": "AGENT_AUTOMATION",
       "actor_id": "ariadne-agent",
       "status": "DRAFT",
       "requires_human_approval": true
     }
     ```

3. **真實證據約束與數值防偽**
   - 禁止 LLM 自行計算或虛構 GIS 座標、街廓面積、日照時數或風速。
   - 所有指標一律由平台 FastAPI 後端確定性模組輸出，或回退至已簽署之已驗證報告與證據卡。
