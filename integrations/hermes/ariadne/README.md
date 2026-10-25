# Ariadne: Hermes Profile 發行包

本目錄是 Rotterdam M4H 都市設計平台專屬 AI 角色「**Ariadne**」的 Hermes Profile 發行包。

---

## 1. 架構簡介

Ariadne 作為都市設計者 Jack 的協同分析夥伴，透過 Model Context Protocol（MCP）經由 stdio 連接平台的 FastAPI 服務（預設 `http://127.0.0.1:8795`）。

- **distribution.yaml**：Hermes profile 發行描述檔。
- **SOUL.md**：Ariadne 核心角色、專業風格與憲法護欄。
- **config.yaml**：Hermes 運行配置與 MCP 連線宣告（**絕不包含任何金鑰或憑證**）。
- **skills/**：五大核心工作流技能目錄（基地理解、約束草擬、方案生成預覽、方案評論、與原設計比較）。

---

## 2. 安裝步驟（由 Commander 執行）

依據專案分工規範，**請勿由執行者自行動手安裝 profile**，須由 Commander 在終端中執行以下指令進行安裝：

```bash
# 預覽並安裝 ariadne profile
hermes profile install integrations/hermes/ariadne --name ariadne -y
```

如需覆蓋既有同名 profile（保留用戶自訂記憶）：

```bash
hermes profile install integrations/hermes/ariadne --name ariadne --force -y
```

---

## 3. 認證登入步驟（由設計者 Jack 執行）

發行包配置檔中不含任何靜態 API Key 或密鑰。Jack 需使用 Hermes 支援的 OAuth 指令完成登入：

```bash
# 進行 Anthropic / Claude 登入
hermes auth login anthropic

# 或進行 OpenAI 登入
hermes auth login openai

# 檢視目前有效之認證狀態
hermes auth status
```

---

## 4. 啟動與測試

在平台 FastAPI 服務運行的環境下，即可透過 Hermes 以 Ariadne profile 開始對話：

```bash
# 單次問答測試
hermes -p ariadne chat -q "請列出 Rotterdam M4H 基地目前的關鍵數值與待決策事項"

# 進入互動式設計工作階段
hermes -p ariadne chat
```
