# C0：Claude／Codex 共同派工與交接 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 先read current registry，再新增事件；不可覆蓋既有紀錄。

**Goal:** 讓兩位指揮官看見對方的計畫、在做什麼、改了哪些檔案，以及成果是否真的上線。
**Architecture:** Git負責程式與文件；跨worktree共同event registry負責協調；project SQLite/ledger負責設計與分析權威。三者以refs連接，不互相代替。
**Tech Stack:** append-only JSON、SHA-256、OS atomic file operations、Python標準庫；不需要新的雲端協作服務。

## 1. 實際共同位置

Registry `/Users/jackhsieh/.local/share/agent-coordination/projects.json`。
Protocol `/Users/jackhsieh/.local/share/agent-coordination/COORDINATION.md`。
Q5 events `/Users/jackhsieh/.local/share/agent-coordination/q5-urban-design/events/`。
Plans `/Users/jackhsieh/.local/share/agent-coordination/q5-urban-design/plans/`。
每一個plan release為新目錄，plan-index.json列六份計畫SHA、Git source HEAD、draft worktree、建立時間；歷史版本不覆盖。

全域Codex與Claude已各有讀取protocol的pointer。它只影響會讀規則的session；不能假定昨天已開的Claude會自動收到。交接時給對方shared plan-index確切路徑，要求讀後寫ACKNOWLEDGED事件。若Claude位於另一台電腦／雲端，這個本機路徑不會同步；需使用者授權的共享repo或檔案傳遞，不能假裝已互通。

## Task C0：派工前盤點與最小事件

- [ ] 讀全部近期事件，以recorded_at_utc解析排序；不可用filename字典序或mtime當時間。舊檔包含非日期prefix。
- [ ] 按task_id建立event鏈；supersedes/parent_event_ids解決修訂，不能讓較晚的舊STARTED覆蓋真正completed。
- [ ] 分清task execution state、code integration state、deployment state、human design state四欄。
- [ ] 任何STARTED但無worker/no output的舊bg-task，追加RECONCILIATION_REQUIRED或INTERRUPTED證據；不修改原status讓它看似從未啟動。
- [ ] Grok研究以手動交付r02事件為準，不重派；sidebar patch已完成但未merge；plan新增文件不等於功能完成。

必填handoff event示例（示例本身不授權執行）：
```json
{
  "schema_version": "commander-handoff-v2",
  "event_id": "event-example-only",
  "recorded_at_utc": "2026-09-30T00:00:00Z",
  "project_root": "/Users/jackhsieh/Downloads/TUD/Q5/project",
  "task_id": "P1-preview-catalog",
  "event_type": "REVIEW_READY",
  "author_provider": "OpenAI",
  "author_model_requested": "gpt-6-luna",
  "author_effort_requested": "max",
  "author_model_observed": null,
  "executor_id": "native-agent-id-or-cli-session-id",
  "task_status": "COMPLETED_SELF_CHECK",
  "code_state": "WORKTREE_ONLY",
  "deployment_state": "NOT_ACTIVATED",
  "human_acceptance": "NOT_REQUESTED",
  "scope": ["src/urban_design/morphology/preview_catalog.py"],
  "branch": "wp/preview-catalog",
  "worktree": "/absolute/executor/worktree",
  "source_commit": "full-git-sha-at-execution",
  "output_refs": [],
  "tests": [],
  "runtime": {"frontend_port": null, "api_port": null, "database": null},
  "blockers": [],
  "next_action": "cross-provider review",
  "parent_event_ids": [],
  "plan_ref": {"path": "/absolute/shared/plan", "sha256": "actual-file-hash"}
}
```
範例字符串須在實際事件填真值或null，不寫假sha／假模型。model requested與observed分開；子代理說無法確認model不能因此把請求配置當runtime證據。
CP-C0：另一指揮官單靠log可以知道哪個WP、哪份diff與哪個服務，且不會重派。

## Task C1：協調工具與寫入安全

Create planned `scripts/coordination_event.py`、`tests/test_coordination_event.py`；可以先在工具WP實作，shared root不進正式設計DB。
New CLI：`coordination_event.py append --registry <root> --event-file <json>`，`status --project <root>`，`claim --task <id> --owner <id> --scope-file <json>`，`release --task <id> --owner <id>`。

Event write最小核心（不是完整CLI）：
```python
import json, os, uuid
from pathlib import Path

def write_event(events: Path, payload: dict) -> Path:
    events.mkdir(parents=True, exist_ok=True)
    event_id = str(uuid.uuid4())
    output = events / (event_id + ".json")
    temporary = events / (event_id + ".pending")
    data = json.dumps({**payload, "event_id": event_id}, ensure_ascii=False, allow_nan=False, sort_keys=True).encode()
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, output)  # atomic publish, EEXIST never overwrites peer file
    temporary.unlink()
    return output
```
CLI先驗schema/refs，完全寫完再publish；reader只讀.json。暫存檔清理由owned event id處理，不能glob刪同目錄。

Scope claim：
- 在project registry以OS flock/同等互斥鎖保護「讀active claims＋檢scope交集＋建立claim」一個critical section。
- 若scope有parent目錄涵蓋另claim檔案，也算衝突；canonical normalized project-relative paths。
- task claims用owner token、native agent id/CLI PID（含start identity）、heartbeat event。不能只靠過期時間自動搶別人工作。
- conflicting claim→BLOCKED_OWNER_CONFLICT；只有協調者查實舊worker不在＋無未知外部dispatch後，追加reconciled release再領。
- observer/status只產生derived report，不把排序結果改写成authority；同秒events用parents/CAS，不用任意last writer wins。

tests：concurrent double claim只有1成功；disjoint可並行；truncated.pending不可見；duplicate event不可覆寫；filename不按日期仍按timestamp讀；model unknown、部署未知保留null。
CP-C1：兩個commander不能合法領同寫入scope；checker異常可停止新派工但不可刪既有產物。

## Task C2：紀錄頻率與交接規則

不建cron、不定時喚醒模型。本計畫採工作事件觸發，符合「定期記錄」而不忙碌輪詢：
- 每次新session開始／派工前：讀shared index、最新event、current git/runtime。
- dispatch、checkpoint完成、blocked、handoff、review、commit、merge、activation、rollback：立即追加event。
- 持續工作期間最遲每30分鐘在下一安全邊界追加PROGRESS；不為寫log打断不可重入計算，不喚醒休眠agent；live作業另有job heartbeat。
- 回覆使用者已完成前：先event，再final。技術中斷來不及寫時，下次啟動reconcile，不假裝有紀錄。
- 每份plan的狀態進event，不由兩位commander同時修改checkbox；版本化plan修訂另建新文件／Git commit＋hash。

cross-review：作者OpenAI→Claude/AGY審；作者Google/xAI→OpenAI/Claude審。review綁diff hash/commit/實際材料，exit0≠接受。真實模型如未知標unknown。Claude與Founder保留既有merge gate；Codex協調身份不構成繞過。

Executor選擇：原生Luna max優先；AGY可做獨立範圍或review。shell bg-run目前有返回STARTED卻消失的歷史失敗，不能作可靠默認；要用須新任務證明worker start/readiness與完成callback均成功，不能只測shell return。

失聯工作不重送：若可能送出provider request但沒有receipt，OUTCOME_UNKNOWN；查session/產物再決定。配額不足不默默換模型。
CP-C2：抽查兩次跨指揮官交接，都能找到plan hash、active scope、diff／產物與下一步，不需翻聊天猜。

## Task C3：Git整合與服務發佈紀錄

- 每executor own wp/* worktree，只stage具名檔案；不main寫入、不push/reset/clean。
- integration owner在整合分支合併已審patch；共用api/App等衝突由其解，跑affected regressions。
- MERGED事件寫merge SHA與source branch refs，不寫DEPLOYED。
- ACTIVATED事件要實查process cwd、loaded source/build digest、API/frontend端口、DB identity、health與必要可見UI證據；只curl HTML 200不能代表新功能可用。
- SOURCE_DRIFT / DB mismatch / draft-unsaved：停止正式切換；展示已可review成果，不要求人類批准抽象未完成任務。
- rollback保留新舊event／artifacts，不倒寫設計ledger。
CP-C3：看到0個scenario時，能區分未生成、output在外部、未接API、runtime舊版、未批准，不再用單一「尚未做」回答。

## 共同執行契約

本文件與 `2026-09-30-site-analysis-generation-master-zh.md` 同版使用。一次只領一個task，先RED再GREEN；原始輸入只讀、每個CP更新shared event。所有新符號／route為planned，既有fixtures成功不代替live驗證。尚未取得main merge／runtime activation批准時，交付reviewable diff，不自行部署。
