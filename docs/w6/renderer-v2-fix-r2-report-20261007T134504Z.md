# Renderer v2 R2 修復 — 20261007T134504Z

**R2 指定修復與執行驗證完成，待 Claude 跨 provider 審查與 Founder 接受。** R01 ABA 已拒絕；R02 四項語義偽造已拒絕；R03 完整路徑兩項 runtime/source 偽造已拒絕。112 focused tests、全新 v2 baseline、pinned replay、兩次直接真實 Qt 獨立重播均有下列實存證據與 SHA-256。這些有限範圍 PASS 不代表 W6／release／main 接受。

## 範圍與權限

派工者 Claude 指揮官；執行者 OpenAI / gpt-6.1-sol / low，使用者明確指定這個困難有界語義修復路由，沒有委派或模型 fallback。worktree `/Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor`；分支 `wp/w6-closeout-integration`、開工與結束 HEAD 均 `7ba155f3bb03d092447b20b3cdb8f0da445c1e74`，沒有切換分支、stage、commit、merge、push。

完整讀過指定複審（SHA-256 `ae0f97f119950ee4bc42868bfc349a2bfca3cef566490594cd3a189d677b115e`）、AGENTS.md、README、架構／證據／評估文件、AGENTS-commander.md、指定中文交接與 takeover 事件 `20261007T130051Z-b3441a23828e46c9bba719be44e61a80.json`。交接中尚未回答的批准解析文字已由 takeover 事件回答；本任務沒有操作該政策、DB 或 HumanDecision。

產品變更僅三個授權檔案，完整 diff 在 `patch-r2.diff`，`git diff --check` exit 0（收據 `final-controls-r2.json`）。其餘新內容只為指定報告、臨時證據與 append-only 協調事件／operations log。沒有安裝／下載、網路／付費 API／Live AI、服務或任何指定 port 操作；Qt 是獨立 offscreen process，沒有重啟既有 QGIS 或 runtime。沒有讀取或建立正式密語、key、.env、Keychain；也沒有演練 HumanDecision，因此沒有測試金鑰。

## R01 — actual input 與 parent identity 綁定

Child 只做一次 `Path(...).read_bytes()`，以同一個 `input_bytes` 做 `ET.fromstring`，回報 `actual_input`（SHA-256 與 size）。父程序在每次 child 返回後，先與捕獲 parent identity 比對，再形成合格 record；mismatch 令 current gate **FAIL**。每筆合格 record 必須含 `actual_input`，schema／assess／兩筆 manifest 驗證也強制這個關係。兩個 child stdout 全部保留，包括被拒絕的 child，未把錯誤輸入的產物納入合格 records。

先原樣複製複審 `adversarial-replay.py` 到新證據根執行：兩次真實 QGIS Qt exit 0、builder exit 0／current PASS，為 fresh 紅燈。修正後保留同樣 dispatch rename／restore 攻擊：兩次 Qt 仍 exit 0，但兩筆實際 digest 都回報 `383e8486df178e2d85393464ed33ff00c32bdbded74fb044243a0bcffd7fb890`；父程序及還原後 snapshot 為 `fd36ea06667ce75fc85dac1eec73b342ad11c67d2158e6e0ddfd2b41d7ab4612`。父程序拒絕、builder exit **2**、current **FAIL**、manifest_validation BLOCKED（沒有兩筆合格 record）。

負測 harness 本身 exit 0 表示上述拒絕斷言全部成立，並非 builder PASS。證據：紅 `race-receipts.json`、綠 `race-receipts-r2.json`、`race-probe-r2/manifest.json`，hash 見證據表。所有替換／保留 SVG 都留存，沒有刪除。snapshot capture 例外清理也改成保留診斷檔案，不再 unlink。

## R02 — source／font／derived artifact 的語義關係

Artifact validator 對兩筆 record 各驗：

1. 從 source bytes 依 helper 的 parent/direct-child 遍歷順序重算 codepoint 序列與 text／character coverage（正常為 26 text nodes、890 codepoints），必須 exact match。
2. 用純 Python、stdlib-only 的有界單面 TTF 解析讀取 cmap format 4／12 與 maxp；每筆 glyph 必須等於該 codepoint 的實際 cmap 值且 `0 < glyph < numGlyphs`。不引入套件或 Qt font database 作為 validator。
3. 源 SVG 與 derived SVG 逐節點比對；每個 source text 必須在同一位置被一個 path 取代，fill／stroke／id 等轉換屬性一致，其餘元素／屬性／文字／結構保持一致，沒有殘留 text/tspan/use/image。實際 semantic buffer 的 source／derived digest 也重核。
4. Font family/style 從 TTF name table metadata 重算，registered families 必須 exact match；source class／bold／pixel size 綁定實際檔案及該 face。只接受 renderer v2 已使用的三個 exact DejaVu binary hashes，配同目錄 `LICENSE_DEJAVU` 與保留 license hash `d75938dec098f06f0ac3c00853065d94f020be1c3c62ef1dc2975ba15b4d9b0e`。改過的 font 不能借用相同檔名與 licence 主張。

四個原 probe 紅燈皆被接受，綠燈皆被拒絕且原因精確為：U+10FFFF → source codepoint sequence mismatch；2147483647 → cmap/maxp mismatch；999999 → source text/character coverage mismatch；Invented Family → TTF metadata mismatch。綠證據 `semantic-probes-r2.json`，4/4 拒絕。正常 baseline 的獨立純 Python audit 每筆 890 mapping，**0 mismatches**；證據 `independent-font-source-audit-r2.json`。

另新增 altered-font/licence pair 反例：保持 name/cmap/maxp，改 glyf byte 並同步重綁 manifest hashes，先 **1 failed、111 passed**，pin retained font/licence pair 後通過。style、license、maxp、derived node、source sequence、兩筆 actual digest 負測均納入 focused suite。

**限制明示：** artifact validator 重算語義身份、coverage、節點轉換結構，沒有另用第二套引擎重算每個 Qt glyph path 座標／rasterisation。這在 GateResult 中標成 `Qt outline geometry NOT_INDEPENDENTLY_RECOMPUTED`，實際輸出 bytes 的再現由下面真實 Qt 重播證明。本版本只支援既有三個 bundled DejaVu fonts；focused artifact tests 也需要它們存在，沒有 skip 或虛構成功 fallback。授權證據綁定不是新的法律判斷。

## R03 — 歸檔載入與完整 local bytes 驗證分開

`load_baseline(path)` 仍驗 schema、兩筆 artifacts、source/font/derived-node semantics，但 PASS reason 明示 `runtime/source bytes NOT_VERIFIED; execution replay NOT_VERIFIED`。`load_baseline(path, verify_runtime=True)` 另外對兩筆 runtime executable、Qt／loaded libraries、font／license 身份逐一重核本地檔案，並核對三個 recorded code source 的 current bytes/hash/size。pinned replay 走這條完整路徑。

原 nonexistent executable 與全 0 create-site source hash 的 probe fresh 紅燈 2/2 被接受；完整路徑綠燈 2/2 BLOCKED，精確原因分別為 executable identity unreadable 與 `scripts/create_site_proposal_rotterdam.py` source identity drift。證據 `semantic-probes-r2.json`。完整 local verification 的 PASS 也明示 execution replay NOT_VERIFIED；實際 dispatch 的 replay 收據獨立記錄。

## 測試與真實 Qt 重播

Focused 完整指令（沒有 skip、deselect 或放寬舊 assertions）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:. .venv/bin/python -m pytest -p no:cacheprovider tests/test_versioned_render_baseline.py -q --tb=short
```

- 初次 TDD：**7 failed、93 passed**（R01 buffer contract、四項 R02、兩項 R03）；`red-tests.txt`。
- 首輪修正：100 passed；擴充關係／malformed coverage 後 111 passed。
- Font/licence pair 額外 TDD：**1 failed、111 passed**；`red-font-license-binding.txt`。
- 最終：exit **0**、**112 passed in 0.30s**；`focused-112.txt`。
- 重跑複審的 30 種 malformed second-record cases：**30/30 BLOCKED**、harness exit 0；`malformed-second-record-probes-r2.json`。正常合格 manifest 先完整驗 PASS，再建立 probes，避免把 schema 缺欄位當成語義修復。

全部 final baseline／pinned replay 為 exclusive 新目錄：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python scripts/build_versioned_render_baseline.py --output /private/tmp/q5-renderer-r2-20261007T133136Z/qualified-r2-v2
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python scripts/build_versioned_render_baseline.py --output /private/tmp/q5-renderer-r2-20261007T133136Z/pinned-replay-r2 --baseline /private/tmp/q5-renderer-r2-20261007T133136Z/qualified-r2-v2/manifest.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python /private/tmp/q5-renderer-r2-20261007T133136Z/independent-replay-r2.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python /private/tmp/q5-renderer-r2-20261007T133136Z/adversarial-replay-r2.py
```

Baseline builder exit 0／current PASS；pinned builder exit 0／current PASS／pinned PASS；再直接用保留 helper dispatch **兩次真實 Qt**，不呼叫 builder.main、不 mock 返回。兩次 exit 0、runtime／actual-input／font／code fingerprint match，PNG 與 derived SVG bytes 逐一等同 baseline。證據 `qualified-r2-v2/manifest.json`、`pinned-replay-r2/manifest.json`、`independent-replay-receipts-r2.json`（完整 argv）。

Final baseline、pinned replay、direct independent replay 共 **6 次真實正常 Qt render**，每次 PNG `aca4cfbdb7fd9e9e2c05ee07714c35d21132b215b52b70c64316d1050d1a36f1`（415045 bytes），derived SVG `532beeec12c446be4a7886754be5a567575a2b4ca5bc17a767a49cef880dd044`（1225839 bytes）。QGIS 3.40.5-Bratislava、Qt 5.15.2、PyQt 5.15.4、x86_64。

**過程中無效證據已保留並排除結論：** 首次 green probe harness 錯讀舊 baseline，因此六項只因新必填欄位缺失而 BLOCKED；`green-probes.txt`／`semantic-probes-green.json` 不作 R02/R03 PASS 證據。修正 harness 後先 assert 合格 final baseline 完整載入 PASS，再要求六項各自的語義／runtime/source 原因，才使用 `semantic-probes-r2.json`。較早 baseline／replay 在 font/licence hardening 前建立，保留但不當最終 current-qualified baseline。

沒有重跑全套 pytest；/dev/tty 已知環境性失敗、歷史 PNG 失敗沒有改 assertion／豁免。W6／release／全套／Claude cross-provider review／Founder 接受仍 **INCOMPLETE／未在本次證明**。

## 保護檔案、正式 DB 與提交狀態

正式 DB 開工與結束 SHA-256 均 **`2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`**；全程僅 byte hashing，沒有用 SQLite 開啟 DB，因此沒有 SQLite 操作／backup 需求。證據 `final-controls-r2.json`。

canonical SVG、historical PNG 與嚴格歷史 test 都逐 byte 等於 HEAD，hash 見 controls；historical node 仍 HISTORICAL_BLOCKED、original_assertions UNCHANGED、release_acceptance false。v1 manifest 完整驗證前後 SHA 均 `60c7c3f82269963d98f4b4ea4a6e0c1eed20e87605ae045e5fc863a402f66625`，仍因 renderer-gates-v1 schema BLOCKED；沒有覆寫或遷移。舊 v2 缺 actual_input 也 fail closed，不自動補證据。

目前三個程式／測試修改未提交，交 Claude 審查後處理；沒有嘗試 commit 或聲稱 EPERM。三個最後來源 hash：

| 檔案 | SHA-256 |
| --- | --- |
| `scripts/build_versioned_render_baseline.py` | `1f865b2f5ca799dd6f6b53a017f53d1da7b03af666fb8b0950b88318c758146f` |
| `src/urban_design/rendering_provenance.py` | `67b0897b0e1dd37a435b0d99861220a0b49767cf524a61b0cefc17aac11dddf1` |
| `tests/test_versioned_render_baseline.py` | `e8433e823db4d9d64b879f7f9a46153e360f98204f531f6f18237a8420868822` |

## 實存證據與 SHA-256

完整檔案索引 `/private/tmp/q5-renderer-r2-20261007T133136Z/evidence-sha256-r2.json` 收錄 **173 個**證據檔（包含正常／拒絕／中間嘗試、PNG/SVG/所有脚本），每項有完整 SHA-256 與 size；索引自己的 hash 列於表中。各有限範圍 PASS 均由上方對應收據與本表 hash 支持。

| 證據 | SHA-256 |
| --- | --- |
| [red-tests.txt](/private/tmp/q5-renderer-r2-20261007T133136Z/red-tests.txt) | `f48cab7eafd8a0748177e06f172b43954d28ec9ebd506908d6a1298f9ec718e0` |
| [red-probes.txt](/private/tmp/q5-renderer-r2-20261007T133136Z/red-probes.txt) | `0830a3f208b25448fe0d2eb20cafe58a8d11ee1d62321565dde096bffc3c4ee3` |
| [race-receipts.json](/private/tmp/q5-renderer-r2-20261007T133136Z/race-receipts.json) | `189eb4f9d34f8c741c1bba703e8378d01c6341938196a1a1c8e9aab4db9c0322` |
| [semantic-probes.json](/private/tmp/q5-renderer-r2-20261007T133136Z/semantic-probes.json) | `5f63790f7d413cc8ad08e2a1a5d7dca9a9e4fbd5e0271447739248fdbfd31f25` |
| [red-font-license-binding.txt](/private/tmp/q5-renderer-r2-20261007T133136Z/red-font-license-binding.txt) | `0be0e3aac1973c94e87eba977efa8a62070aa17a570054afe1e462880571df9e` |
| [focused-112.txt](/private/tmp/q5-renderer-r2-20261007T133136Z/focused-112.txt) | `51f1b9d40d7d65a3968983d17bb213679d84bdacdf525c422285d494c0d0e3ad` |
| [qualified-r2-v2/manifest.json](/private/tmp/q5-renderer-r2-20261007T133136Z/qualified-r2-v2/manifest.json) | `1ff52b05455a6acfdf818b592f1811902521e5a855499a8347c7f15156c8d79d` |
| [pinned-replay-r2/manifest.json](/private/tmp/q5-renderer-r2-20261007T133136Z/pinned-replay-r2/manifest.json) | `0c380ab00638146f45556f54c210558c903927a104a2dd1941cbb55735f5c90b` |
| [independent-replay-receipts-r2.json](/private/tmp/q5-renderer-r2-20261007T133136Z/independent-replay-receipts-r2.json) | `7f600b77cfc4d24358fbcea8cb4d54399519ec1717a898e5e63bce883b0e52a2` |
| [semantic-probes-r2.json](/private/tmp/q5-renderer-r2-20261007T133136Z/semantic-probes-r2.json) | `f942bd1c3d8cfd9662d30a44c4136b3d0987e30651298bd054dcc930ef5a4fab` |
| [race-receipts-r2.json](/private/tmp/q5-renderer-r2-20261007T133136Z/race-receipts-r2.json) | `0badd76a040954688c2a284f53e0e4c26bf7813cd4a69700b96f374a6e5e595a` |
| [race-probe-r2/manifest.json](/private/tmp/q5-renderer-r2-20261007T133136Z/race-probe-r2/manifest.json) | `046f314037d050c7c3a265c71542ae1f55e9e60527eee048adce8b6d6544bff5` |
| [malformed-second-record-probes-r2.json](/private/tmp/q5-renderer-r2-20261007T133136Z/malformed-second-record-probes-r2.json) | `1903285115609856eb633d60aedd19f5372f7481f4fb848e59727997ad98553e` |
| [independent-font-source-audit-r2.json](/private/tmp/q5-renderer-r2-20261007T133136Z/independent-font-source-audit-r2.json) | `a20fa793692ced59942958f625ae4f19b1a2b9f53fcb35d62a740a93bc908a70` |
| [adversarial-replay-red.py](/private/tmp/q5-renderer-r2-20261007T133136Z/adversarial-replay-red.py) | `12df1a761fc323279bee3a055b0d8a6f97ce6a6d4c11c1aa44ab58b4ccd6f701` |
| [adversarial-replay-r2.py](/private/tmp/q5-renderer-r2-20261007T133136Z/adversarial-replay-r2.py) | `0dc83f7d96d07b81aa94407113a3597d889ac871b906f52c7653abf47b08868f` |
| [independent-replay-r2.py](/private/tmp/q5-renderer-r2-20261007T133136Z/independent-replay-r2.py) | `4f178944bcc6719293e09460b1adbf68c22101bb0ec36bbc38da5b707a563a17` |
| [final-controls-r2.json](/private/tmp/q5-renderer-r2-20261007T133136Z/final-controls-r2.json) | `c2e872b66c763e2aefce6c4e1b122ba1b6ab8abf21d8310e59399e19f75db235` |
| [patch-r2.diff](/private/tmp/q5-renderer-r2-20261007T133136Z/patch-r2.diff) | `6b0f227f23eb565dd1f75aece4932bcd7a6032d2174e12da983cd9b8c2048eef` |
| [evidence-sha256-r2.json](/private/tmp/q5-renderer-r2-20261007T133136Z/evidence-sha256-r2.json) | `3f88c24237ae050d931e4758f7302d3e0575e0a13a543dd579661f6b598174aa` |

交接：R2 指定修復的執行證據齊備，請 Claude 對 final source／diff／baseline／反例做跨 provider 審查；Founder 保留接受與 consequential decision 權限。main、正式服務、正式 DB 與既有隔離 8940／8941 未變更。
