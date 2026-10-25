# Renderer v2 獨立複審 — 20261007T132811Z

**結論：REQUIRES_CHANGES。** F01 原始 malformed/nested schema 缺陷修復 PASS；F02 所有 record 驗證修復 PASS；F03 「沒有讀取 race」FAIL。正常 current baseline 與獨立 pinned replay 實際成功，但可重現 snapshot ABA 替換令真實 Qt 用錯誤輸入仍被記為 PASS，且語義 proof 驗證仍不完整。以下 PASS 僅指明列範圍，每項對應下方實存證據及 SHA-256。

## 範圍、權限與來源

派工者 Claude 指揮官；執行者 OpenAI / gpt-6.1-sol / low（本次使用者明確路由），無委派。工作目錄 `/Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor`，分支 `wp/w6-closeout-integration`，HEAD `e6d4d5e1a33a50ecb2107a60fa35e5b0b7fde06f`，逐行檢查 `1f0333a..e6d4d5e` 的六個新增檔案（249 行 validator、346 行 builder、504 行 tests、53 行 decisions）。patch 保存在 `patch.diff`。這是 OpenAI 對 OpenAI 執行產物的獨立重播與內部複審，**不是 cross-provider review**；Claude、Founder 的接受、W6、release、merge gate 均未取代。

已讀 AGENTS.md、README.md、AGENTS-commander.md、架構／證據／評估文件、指定交接文件及 takeover 事件 `20261007T130051Z-b3441a23828e46c9bba719be44e61a80.json`。Founder 2A 僅允許新 baseline；RENDER-C01 僅分類指定歷史 node。批准解析的新規則不影響本次 renderer 審查，也不構成正式 DB 寫入權限。

沒有修改產品程式碼、三個受保護檔案或 decisions；沒有 Git stage/commit、服務/port 操作、安裝、網路、paid API、Live AI、正式 key／密語／.env／Keychain 或 HumanDecision。正式 DB 未以 SQLite 開啟；只有讀取 bytes 計算 SHA，因此未需 backup API。所有 Qt 工作為 offscreen 獨立 process；新 evidence 僅在 `/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1`。既有 untracked .venv 與三個 artifact/out 目錄未處理。

## 原 finding 判定

| Finding | 狀態 | 具體範圍與證據 |
| --- | --- | --- |
| F01 | PASS | exact root/nested field set、非 boolean 整數、Unicode scalar／surrogate、有限正數 font size、glyph > 0、連續 indexes、font/license/runtime/code identities 均有 shape checks。93 focused tests 與另 30 種 record 1 malformed/nested cases 全部依預期拒絕且無 exception。證據 `focused-tests.txt`、`malformed-second-record-probes.json`；這不證明 glyph/font/source 的語義關係，見 R02。 |
| F02 | PASS | validator 遍歷恰好兩筆 record；`assess(records[0],records[1])` 比所有關鍵 fingerprint；artifact validator 為兩筆各 rehash PNG、derived SVG，加上 parent/helper。focused suite 含第二筆 malformed、第二 PNG／SVG／helper corruption；獨立 v2 load/replay 正常成功。最後與 baseline record 0 比較不構成漏驗 record 1，因前段已驗兩筆並要求等價。證據 `focused-tests.txt`、`malformed-second-record-probes.json`、`replay/manifest.json`。 |
| F03 | FAIL | O_EXCL 建檔與 chmod 0400 確实存在，兩個 command 使用同一路徑，外部原 SVG 變動不再直接影響 child；但 child 仍按 pathname 重開 snapshot，父程序只前後 hash，未證明 child 實際解析 bytes。same-owner writable directory 的 rename／restore 可越過只讀檔案權限。真實 Qt 反例 PASS／exit 0，見 R01。 |

## 新 finding（依嚴重度）

### R01 — P1：snapshot ABA 替換仍能令 current gate 錯誤 PASS（F03 未封閉）

位置 `scripts/build_versioned_render_baseline.py:115`、`:137`、`:242`、`:262`、`:272`；HELPER 以 `ET.parse(sys.argv[1])` 重開路徑。O_EXCL 只保護建立時，0400 只限制檔案內容寫入；同一 owner 對 0700 目錄可 rename snapshot。record 的 parent identity 由父程序提前計算，child 不回報自己實際讀到的 input digest。

`adversarial-replay.py` 只在自有臨時目錄插入 dispatch 攔截，**仍呼叫原 subprocess.run 跑兩次真實 QGIS Qt，未 mock 返回或偽造 PASS**。每次 dispatch 前把 snapshot rename 保存，換入 `Rotterdam → RotterdXm` 版本，child 完成後 rename 還原；所有替換檔保留，沒有刪檔。這是受控制、同 owner 並行寫入時窗的確定性重現，不宣稱發生過自然 production race。

- 父程序記錄與最後還原的 parent：`fd36ea06667ce75fc85dac1eec73b342ad11c67d2158e6e0ddfd2b41d7ab4612`。
- 兩個 child 實際 input：`383e8486df178e2d85393464ed33ff00c32bdbded74fb044243a0bcffd7fb890`。
- 兩次真實 child exit 0；builder exit 0、manifest_validation PASS、current PASS。
- 兩 PNG：414932 bytes、`e3d23c5c0f18d6d04a8af1f7b2b924ebb4dc201959e879f3bc698ac8dbd318c1`，不同於合格正常 baseline。

證據 `race-receipts.json`、`race-probe/manifest.json`、兩個 PNG、alternate SVG、`adversarial-replay.py`。此反例不改原 SVG、正常 baseline 或產品程式碼。修復建議：child 一次讀取 input bytes，以同一 buffer 解析並回報 digest；父程序對每筆 actual-input identity 與已捕獲 identity 做 exact binding。必要時用受控 fd/buffer 通道，不能把 chmod 視為 immutable 證明。修正交指揮官另派。

### R02 — P1：型別正確但語義不實的 glyph/font/source proof 仍被接受

位置 `src/urban_design/rendering_provenance.py:122`–`:157`、`:195`；builder artifact load `:141`。每筆只檢查 Unicode scalar、glyph 正整數、mapping 長度與 font hash membership；沒有重算來源文字序列、實際 font cmap／maxp、text node count、font family/style，或 derived paths 與 mapping 的關係。

從本輪合格 baseline 複製出的新 probe manifests，兩筆同步改 first codepoint 為 U+10FFFF、glyph 為 2147483647、text_nodes 為 999999、或 family 與 registered_families 改為 Invented Family，PNG/SVG/helper/snapshot 不變；`load_baseline()` **4/4 PASS**。這些是刻意無效的負測資料，不是新合格 baseline。U+10FFFF 是合法 scalar，但不是來源第一字元 R；glyph 超過三個實際字型的 glyph count（6184／6241／3369）。

正常 baseline 則經獨立純 Python TTF cmap format 4/12、maxp 解析：每筆 890 mapping、26 text nodes，來源序列與 cmap glyph **0 mismatches**；derived SVG 無 text/tspan/use/image。font family 的实际 Qt 來源仍是 raw file；沒有證明 validator 能拒絕語義偽造。因此正常產物有實證，但不能由 shape valid 推論所有 proof 已驗證。

證據 `semantic-probes.json`、`baseline/probe-*.json`、`independent-font-source-audit.json` 及其腳本。修復建議：artifact-aware deterministic validation 應重算 source coverage、font cmap/glyph bounds、font metadata／授權證據綁定，並驗證 derived transformation；shape check 與 relationship validation 分開命名。無需放寬既有門檻。

### R03 — P2：load_baseline 的 PASS 不是 runtime/code 來源完整驗證

位置 builder `:194`–`:212`；`validate_runtime_files()` 只對本次 child record 呼叫（`:266`），load 不呼叫。新 probe 兩筆同步把 executable path 改成不存在的 `/private/tmp/nonexistent-renderer-review-python`，或把 create-site source hash 改為 64 個 0，`load_baseline()` **2/2 PASS**，仍使用「both pinned renders...match」理由。

完整正常 replay 另有與 fresh record 的比較，會拒絕這些更改；本 finding **不宣稱它們能讓完整正常 pinned replay PASS**。但可呼叫的 baseline load/valid 狀態沒有驗它自稱記錄的 runtime local bytes 或 source bytes。須明確把 archival schema/artifact integrity 與可重播 runtime/source qualification 分開，或補來源驗證；跨機器歷史 runtime 缺失應 typed BLOCKED，而非默認全部已驗。證據 `semantic-probes.json` 與兩個 probe manifests。

## 本輪測試、重播及指令

完整 focused 指令（沒有 skip/deselect/mock PASS，plugin autoload 明確禁用）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:. .venv/bin/python -m pytest -p no:cacheprovider tests/test_versioned_render_baseline.py -q --tb=short
```

親自結果：exit 0，**93 passed in 0.13s**。附加腳本 30 malformed record 1 cases 均 BLOCKED（30/30）；六個語義／來源负測卻 PASS（6/6），因此是缺陷證據。沒有 broad suite 重跑；原實作者 93 PASS、aca4cfbd… 與 exit 2 只列 reported，不作本輪親自證據。已知 /dev/tty 與 historical PNG 失敗未改測試或豁免。

builder 三次完整指令，每個 output 目錄皆由 builder exclusive 建立，原 manifest 不覆寫：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. /Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor/.venv/bin/python /Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor/scripts/build_versioned_render_baseline.py --output /private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/baseline
```

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. /Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor/.venv/bin/python /Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor/scripts/build_versioned_render_baseline.py --output /private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/replay --baseline /private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/baseline/manifest.json
```

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. /Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor/.venv/bin/python /Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor/scripts/build_versioned_render_baseline.py --output /private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/v1-rejection --baseline /private/tmp/q5-renderer-version-baseline-20261006-font02/final/manifest.json
```

| 作業 | builder exit | Current gate | Pinned gate |
| --- | --- | --- | --- |
| baseline | 0 | PASS | NOT_REQUESTED |
| replay | 0 | PASS | PASS |
| v1-rejection | 2 | PASS | BLOCKED |

正常 baseline 與 v2 pinned replay 合計四次實際 QGIS Python/Qt render；v1 rejection 再有兩次。版本 qgis-qt-dejavu-outlines-v2，QGIS 3.40.5-Bratislava、Qt 5.15.2、PyQt 5.15.4、x86_64。確切 child argv 完整保存在各 manifest `command`。每份正常 manifest 的兩 PNG hash 都是：

`aca4cfbdb7fd9e9e2c05ee07714c35d21132b215b52b70c64316d1050d1a36f1`（415045 bytes）。

derived SVG 兩份均 `532beeec12c446be4a7886754be5a567575a2b4ca5bc17a767a49cef880dd044`（1225839 bytes）。snapshot mode 0400、input hash fd36ea…；helper hash `2af8f46bf5df0692ebd14e0b029c3eacde0e617b78ec791ff9870eb53ac20c6a`。本輪獨立 audit 對正常 baseline **每筆 rehash 176 runtime/font/license identities PASS**，三個 renderer code identity 與 current files、helper 與 builder literal 完全一致。三個 DejaVu font 及同一 LICENSE_DEJAVU 的完整路徑/hash 在 manifest 與 audit；license hash `d75938dec098f06f0ac3c00853065d94f020be1c3c62ef1dc2975ba15b4d9b0e`、4816 bytes。這是本地 bytes 證据，不是法律授權意見或任意 SVG typography 支援。

font audit 首次用 depth-first source 序列導致 700 mismatch；檢查後確認 helper 按 parent/direct-child 順序處理文字。第一次腳本／結果保留為 `*-depthfirst.*`，修正獨立 audit 的遍歷契約後才得到 0 mismatch。沒有更改產品或測試來消除差異，也不把錯序 audit 當產品 finding。

v1 診斷保持：schema renderer-gates-v1 不支援，expected renderer-gates-v2，pinned BLOCKED／builder exit 2。原 manifest 前後 hash 均 `60c7c3f82269963d98f4b4ea4a6e0c1eed20e87605ae045e5fc863a402f66625`；未遷移、未修改。即使 manifest_validation 為 PASS，也只是 v2 current manifest 結構／current records 合格，不能遮掉 pinned BLOCKED。

## 保護檔案與 DB

三個受保護檔案及歷史 test 本輪開始／結束 SHA 相同，HEAD 不變：

| 檔案 | SHA-256 |
| --- | --- |
| `src/urban_design/rendering_provenance.py` | `8ea2dc4db010e5e9b98419326163f0ab044b2c92793e7a0e98a84b68d8e351c5` |
| `scripts/build_versioned_render_baseline.py` | `2e5efe75a813b0bbc49ddb9d57f0060d2aa35222e685baf719ebf3fc42449397` |
| `tests/test_versioned_render_baseline.py` | `3bc38bb70d259af8aa8bdb6b582f76b2a3314a0a07a1953d2ec68927e3e74b4a` |
| `tests/test_site_proposal_rotterdam_v4.py` | `f3d1e9fe45cbd4dc2912e057ea69afed682ee23fdb15865629076af8256c2075` |

canonical SVG、歷史 PNG 與嚴格 test 均與 HEAD bytes 相同；歷史 PNG SHA `4d50adbfe7b729a4cfaea61cf7cf394141130e17a23412c6a488d98d5d28984d`，test SHA `f3d1e9fe45cbd4dc2912e057ea69afed682ee23fdb15865629076af8256c2075`。新 manifests 都保留 exact historical-node metadata HISTORICAL_BLOCKED／UNCHANGED、release_acceptance false。沒有歷史重建 fresh PASS 主張。

正式 DB 前後 SHA-256 均 **`2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`**。證據 `final-controls.json`；沒有建立 domain HumanDecision 或 key。

## 實存證據與 SHA-256

所有欄位列出實際存在檔案。PNG/SVG/腳本/所有 probe 的完整 hash 與 size 索引：`evidence-sha256.json`；索引自己的 SHA 在本表。正常 PASS 與反例 PASS 不混用。

| 證據 | SHA-256 |
| --- | --- |
| [focused-tests.txt](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/focused-tests.txt) | `b9bd33a53b8bd6934127ef24ce444a15b7d53be72bf68639b10cf6f0fc133c45` |
| [focused-command.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/focused-command.json) | `473571d4cacf740eeb2339b40587dc725de0bd9dc9f8d3f79d82a884a65e5a27` |
| [malformed-second-record-probes.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/malformed-second-record-probes.json) | `1903285115609856eb633d60aedd19f5372f7481f4fb848e59727997ad98553e` |
| [baseline/manifest.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/baseline/manifest.json) | `e751c53c09d82ab297791946d8ef55993f4d17ebe5a32e38bc345bb463ad8c49` |
| [replay/manifest.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/replay/manifest.json) | `015dcc84944df8f635b9c0d3a492698d54a932d32caab0a6a941f756bd70d58c` |
| [v1-rejection/manifest.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/v1-rejection/manifest.json) | `556453245eb0e7efbbe23aa2ea1cd5d14049234234d043a6ebfd7223746d0d3e` |
| [v1-preservation.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/v1-preservation.json) | `37499bfc216f3468309057c020a182da0ecebebe6b865442f88720cba367e7f2` |
| [independent-font-source-audit.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/independent-font-source-audit.json) | `84830254b8c28efc7ae8cd69f66cf77e9c7a9602b7b813a1322b353fcd2410a0` |
| [semantic-probes.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/semantic-probes.json) | `bcfc62b8b2edbc89858f1dc93d0558e767a3eb29261d63f89e20a5033480bab8` |
| [race-receipts.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/race-receipts.json) | `f3c5a42d1aeadcacb4a1d7983fd81716886511ee078da24f6c83703b3d682d16` |
| [race-probe/manifest.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/race-probe/manifest.json) | `ab354d208cd739c86c5024d178abee70d9da9f3fc0b9a66b98843f6522d1ede1` |
| [adversarial-replay.py](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/adversarial-replay.py) | `12df1a761fc323279bee3a055b0d8a6f97ce6a6d4c11c1aa44ab58b4ccd6f701` |
| [final-controls.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/final-controls.json) | `83bf347f1826305d96343dbaff9b7a79f1fea54782af09f9e611eccbbd0cbb12` |
| [patch.diff](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/patch.diff) | `e87005fcc875129a78910b3d4d339429b38f75025aaaecfe643e1624d366d0e4` |
| [evidence-sha256.json](/private/tmp/q5-renderer-v2-independent-20261007T132144Z-47c10db1/evidence-sha256.json) | `dab420d706309e92f85d7889fc4be637b7c5948086065bfaa27ca96e0f884439` |

## 交接結論

**REQUIRES_CHANGES**：正常新 v2 baseline 可重播，F01 shape 與 F02 record coverage 已修；F03 真實輸入未綁定、R02 proof 語義驗證尚缺。報告與事件交指揮官另派修正，未改產品。修正後重新跑 malformed／semantic／snapshot ABA controls、focused suite 及 exclusive v2 replay，再交不同 provider 審查。全套 pytest、W6/release、Founder 接受及 main merge 仍未完成／未授權。
