# W5-7／W5-8：批准後生成操作頁

## 目前狀態

入口唯讀檢查當前 `WorkspaceRevision` 與 `ConstraintSet`，要求 HumanDecision 為 `Approve`／`approved`、目標版本和 payload digest 都吻合。設計範圍、每筆要素處置及分區由同一個目前工作區決策綁定；處置仍是 `undecided`、分區缺漏、來源 Artifact/hash 不符、ConstraintSet 未啟用或決策過期時，命令逐項回報並停止，不會寫輸出 DB，也不會用 fixture 或預設值補缺。

本分支加入 `generate_site_strategies(SiteGenerationInput)` 正式基地路徑，保留 `generate_fixture_strategies(FixtureGenerationInput)` 測試路徑。正式路徑讀取不規則 EPSG:28992 設計範圍、保留建築／道路、分區、批准 ConstraintSet，以及已核准 DatasetSnapshot 指向的道路 Artifact。策略均標示為系統範本；幾何與硬性上限由確定性驗證器檢查。三個輸出維持 `PROPOSED`；驗證失敗的候選以 `BLOCKED` 保存原因，不會建立 HumanDecision 或接受方案。此程式碼仍待 Commander 獨立審查，本頁和本地測試不代表 W5-7／CP5-5 已驗收。

## 設計者完成第 1、3 天決策後

1. Commander 先確認設計者已在平台完成第 1 天的設計範圍、建築／道路處置、分區決策，以及第 3 天 ConstraintSet 數值決策。入口不建立 HumanDecision，也不讀取決策密語。
2. 先在獲准的測試 DB 副本或審查環境執行一般模式；一般模式使用新 SiteGenerationInput，不要加 `--fixture-only`：

   ```bash
   PROJECT_ID="填入 state 中的 project id"
   PYTHONPATH=src python scripts/run_approved_generation.py \
     --database /path/to/state.sqlite3 \
     --project-id "$PROJECT_ID" \
     --output-db /path/to/review/state-generation.sqlite3 \
     --artifact-root /path/to/review/state-generation-artifacts
   ```

   成功時會把三個系統範本候選及驗證結果寫到新的 DB 副本和 Artifact 目錄。`GenerationResult` 會列出有效／失敗候選數；若有效候選少於三個，保存每個失敗原因並回報實際數量，不會補湊。任何一個必要批准值、來源幾何或決策缺失時，入口會在建立輸出前回報 `BLOCKED`。將輸出和來源 hash 交 Commander 審查；勿以 `--fixture-only` 重試正式 DB。

3. Commander 審查新生成器的程式、精確輸入 hash、方案幾何與驗證收據後，再決定是否安排權威 DB 唯讀來源／新副本執行。成功且驗證通過的候選為 `PROPOSED Scenario`，並附幾何 Artifact、ToolExecution 和無排名／總分的比較表；失敗候選保留為 `BLOCKED`。Commander 檢查批准目標版本/hash、原始保留幾何、外部道路接點的同層連通、每個上限、資料缺口和比較基礎，再交獨立審查。執行者不驗收方案或把方案升為 `ACCEPTED`。

4. 若 3D BAG 快照或某保留建築的樓層數無法核實，結果保留建築並記錄缺值；硬性 FAR 無法驗證時，該候選為 `BLOCKED`，不會把未知值當 0。外部道路的 `layer` 或 BGT 相對高度缺欄時，輸入轉換依道路來源慣例記為同層 0；`bridge` 和 `tunnel` 仍分開記錄，不能跨層連線。說明文字由確定性系統範本生成，不呼叫模型。街廓碎片門檻 100 m²／6 m 以版本化系統規則標示，屬範本參數，不是設計者批准的規劃標準。

## 只在測試 fixture DB 使用

測試會在 pytest 暫存目錄建立 DB，以測試專用密語經 `record_human_decision` 建立 fixture HumanDecision；密語不輸出、不保存明文。只有此類 fixture DB 可加 `--fixture-only`：

```bash
PYTHONPATH=src python scripts/run_approved_generation.py \
  --database /tmp/fixture-state.sqlite3 \
  --project-id project-generation-fixture \
  --output-db /tmp/fixture-generation-copy.sqlite3 \
  --artifact-root /tmp/fixture-generation-artifacts \
  --fixture-only
```

預設寫入新的 SQLite backup 副本，拒絕覆寫既有輸出。fixture 成功結果一律標記 `FIXTURE_ONLY`，只證明決策讀取、狀態拒絕、持久化和比較流程；不證明正式基地生成有效。測試命令見根目錄 `AGENTS.md`。

## 權威寫入選項

本工作不執行權威寫入。獲得獨立核准且正式算子已就緒後，Commander 才能明確指定同一 DB 路徑並帶入目前檔案 SHA-256。程式會先比對雜湊，再用 SQLite backup API 建立同目錄快照，之後才開始寫入：

```bash
DB=/path/to/state.sqlite3
PROJECT_ID="填入 state 中的 project id"
EXPECTED_SHA256="$(shasum -a 256 "$DB" | awk '{print $1}')"
PYTHONPATH=src python scripts/run_approved_generation.py \
  --database "$DB" --output-db "$DB" --project-id "$PROJECT_ID" \
  --write-authority --expected-sha256 "$EXPECTED_SHA256"
```

缺少 `--expected-sha256`、雜湊不符、fixture 模式或輸出路徑不是同一 DB 時，入口拒絕執行。快照路徑與快照 SHA-256 會列在成功收據中。
