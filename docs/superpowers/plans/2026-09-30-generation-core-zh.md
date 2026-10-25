# G3：基地回應、道路骨架與量體生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 每個 task獨立RED→GREEN→review；不一次改完整dictionary_generator.py。

**Goal:** 使方案差異来自空間組織與基地訴求，並修正型態名／幾何不符、密度失真、殘餘空間無理由等問題。
**Architecture:** v4留作historical replay；v5以typed stage adapters組合現有pure geometry functions，新能力逐項加入。先骨架、再街廓／用途、再量體／高度，對每一層保留可編輯的immutable結果。
**Tech Stack:** 現有Shapely／pyproj、Pydantic、seeded標準PRNG、pytest；不引入黑箱最佳化或以LLM直接輸出權威頂點。

## Task G0：stage contracts、geometry基準與技術對齊

Create `src/urban_design/generation/contracts.py`、`hashing.py`、`tests/test_generation_contracts.py`。
Read existing `morphology/contracts.py`、`metrics.py`、`validation.py`、`dictionary_generator.py`、`models.py`，復用合法type而非平行發明Scenario。

Proposed datatypes：
- `GenerationContext`: FrozenRefs of workspace/analysis/brief/source/constraints，crs，seed，method_parameters，assumptions，generation_class=`EXPLORATORY|APPROVED_INPUTS`。
- `StrategySpec`: strategy_id、topology_family、intent_ids、entry_refs、open_space_hierarchy、height_policy、program_policy、permitted_type_ids、reasons（refs＋短理由）。
- `SkeletonArtifact`: ref、context_hash、roads(edges/nodes/levels/access/width refs)、primary_open_spaces、retained_geometry_refs、connections、validation。
- `BlockProgramArtifact`: ref、parent_skeleton_ref、blocks、zones、frontages、program_allocations、unallocated_areas_and_reasons。
- `MassingArtifact`: ref、parent_block_ref、buildings(footprint/逐層polygon/height/use/type variant)、retained_refs、validation。
- `ValidationReport`: geometry/topology/constraint status分欄、checks、unknowns、failures，不用單一valid代替。
- `StrategySpec`是AI可提議的typed語義，不含可自由執行code；型態／拓撲只能挑registered capability。

planned functions及回傳：
`build_skeleton(context, strategy) -> SkeletonArtifact`
`partition_and_allocate(context, skeleton, strategy) -> BlockProgramArtifact`
`generate_massing(context, blocks, strategy) -> MassingArtifact`
`validate_stage(context, artifact) -> ValidationReport`
`compare_candidates(context, artifacts) -> ComparisonBundle`
上述context包括已解析幾何與FrozenRefs；request refs由backend解析，client不能指定任意source path。

- [ ] Geometry以EPSG:28992公尺計算，局部座標平移／旋轉保存4×4或2D affine及inverse，不把分析geometry投影到顯示pixels後再計算。
- [ ] 1mm座標正規化只用於hash與重播策略，工程公差版本`geom-tolerance-v1`；不作1m設計步進、不移動原始保留geometry。超公差變更必須反映hash。
- [ ] semantic hash包含輸入hash、seed、stage algo version、參數、geometry；不包含UI mode、wall time、job id。每stage使用hash-derived seed，避免多跑一步消耗PRNG後結果不同。
- [ ] 保留v4函式與舊serialized output，不將舊metadata重寫成v5；新adapter version明確。
- [ ] ARCH-01確認為使用現有Shapely adapter後才動正式架構文件；禁止臨時安裝COMPAS來湊舊標題。

測試例：
```python
def test_repeated_skeleton_has_same_semantic_hash(context, skeleton_strategy):
    a = build_skeleton(context, skeleton_strategy)
    b = build_skeleton(context, skeleton_strategy)
    assert a.ref.sha256 == b.ref.sha256
    assert a.context_hash == b.context_hash
```
context/skeleton_strategy為synthetic fixture，值固定於test conftest，不讀runtime。這個測試只證明重複計算一致；mode 排除須另測下列 request-to-context projection 與 U0 三模式端到端，不能用重複呼叫冒充 mode 測試。
CP-G0：contracts freeze；三stage可獨立序列化，hash deterministic，method/assumptions有來源種類。

## Task G1：能力 registry與不支援型態 fail closed

Create `generation/type_registry.py`、`tests/test_generation_type_registry.py`、`tests/test_morphology_shape_semantics.py`。
Modify狹義 `morphology/dictionary_generator.py` 只新增versioned adapter分支，不更改v4 replay semantics。

研究r02只作reference。Runtime registry每個entry包含type_id、variant_id、implementation_id、algorithm_version、capability_state、allowed_parameters、semantic_test_ids。不得從研究卡的名稱推定支援。
- [ ] RED：unknown profile或slab無實作→`UnsupportedMorphologyType`；v5不能默默回empty geometry或換成comb。
- [ ] H：使用左右兩條翼帶＋中央橫接，與单侧comb不同；測左右對稱（fixture指定對稱時）、中央連接、兩側缺口、面積/containment。
- [ ] E：單側spine＋三個同側翼；comb翼數可變，E與comb3只有幾何等價時可共享算法，metadata保留語義別名，不把所有comb都叫E。
- [ ] corridor/courtyard開口有orientation與ground/upper-level範圍；公共性是policy欄，不能由洞口自動判斷。
- [ ] profile參數只接受合法width/depth/thickness域；拒絕wall thickness>=half width等退化形狀；未知參數extra=forbid。
- [ ] measured shape assertion，而非只assert非空。Known-answer H：site100×80，兩翼各10×60，中央連接60×10（扣除重疊依實際union計算）；獨立rectangle union算reference。
CP-G1：型態名對應幾何可檢查；未支援profile顯示原因，不塞空白方案。

## Task G2：多策略道路／公共空間骨架

Create `generation/skeleton.py`、`generation/strategy_catalog.py`、`tests/test_generation_skeleton.py`。
Reuse既有roads contacts／同層connectivity檢查，移除「所有新策略必須正交」的普遍假設；正交只對grid strategy必要。

三個基線 topology family（是演算法候選，非已批准基地選擇）：
1. CONNECTED_GRID：依有效外部入口與site axis建立可裁切網格，保留主要穿越與多條替代路。
2. CENTRAL_COMMON：先選可放置中央公共空間的連續可用區，再建連接入口與中心周邊的路，不能以建築剩餘空地冒充中央廣場。
3. LINEAR_SPINE：沿使用者選定的entry-target／green-waterfront軸線建立主公共路徑，接分支與局部空間節點。

若人類required intent排除某family，不能為湊三種違反它；在允許family裡產生有可量測組織差異的變體，不足就報不足。

演算法順序：
- [ ] 建 immutable obstacle set：保留＋未決建築、水體、明確no-build zones；existing editable features以scenario overlay管理，原始source不刪。
- [ ] Road allowed domain不同於building allowed domain；水體除非有批准bridge操作不得跨越；waterfront setback沒有決策時用明示假設生成exploration，不能宣稱法規。
- [ ] 將明示入口／接點依level分組；未知同層關係標uncertain，不以平面交點冒充接通。
- [ ] 產生family骨架，再在obstacles邊界候選點＋entry點構visibility graph；邊只有當其含道路半寬buffer不穿禁區時才可用，以length成本Dijkstra修接。
- [ ] 每条路width與class對應parameter refs；路端點吸附到合法same-level contacts，用已設定公尺容差。不捏造dead-end必須全部消除的法規。
- [ ] 用polygonize檢查主要開放空間與roads的連通界面；沒有路權時只標proposed connection。
- [ ] 不可達／路過窄／無中央空間→strategy BLOCKED帶具體geometry，不能隱藏該失敗。

Fixtures至少：矩形、L形基地、中央水洞、兩個不連通陸塊、保留建築擋中心、不同level交叉、唯一入口、完全無入口。
CP-G2：至少三種synthetic骨架可重播；真正的入口、水體、保留、意圖改變會影響結果，純高度改變不影響。

## Task G3：街廓、用途與開放空間配置

Create `generation/blocks.py`、`generation/program.py`、`tests/test_generation_blocks.py`、`tests/test_generation_program.py`。
- [ ] 建道路用地union（buffer join/cap policy版本化），從EDA扣除水體／道路／主要開放空間與不可設計區，取得可配置faces；不是從StudyArea gross area偷換land分母。
- [ ] 每face保留frontage edges與相邻road class，建立block adjacency graph。無路接觸的face標needs access，不直接放建築。
- [ ] 依brief program zones分配用途；重疊按已選priority/allocation policy，無policy→BLOCKED_ZONE_OVERLAP，不默認後寫覆蓋先寫。
- [ ] long/thin fragments不直接丟掉：標remnant with reason，供open-space/service/保留或幾何修復選項；重複把剩餘地當綠地不允許。
- [ ] 各地表polygon disjoint，area budget必須守恆：
```python
assert abs(eda.area - classified_union.area - unclassified.area) <= area_tolerance
assert classified_union.intersection(unclassified).area <= area_tolerance
```
area_tolerance取已版本化精度policy，而非以大容差掩飾漏地。
- [ ] 南側／遠端陸塊不得因rectangular crop被忽略；對每個connected component給utilized/unallocated理由與面積。
CP-G3：每平方公尺有分類或明示未分類；用途為提議，不是地籍／實際使用事實。

## Task G4：量體、樓層與強度分配

Create `generation/massing.py`、`generation/density.py`、`tests/test_generation_massing.py`、`tests/test_generation_density.py`。

步驟：
- [ ] 候選型態先由capability registry過濾，再按frontage、block尺寸、用途、保留干擾及brief意圖選組合；大街廓可混型，不僅整基地套一個profile。
- [ ] 使用footprint＋逐層polygon表達樓層；高度 `first_floor + (n-1)*standard_floor`。層高全需parameter ref；不能以3.5m預設冒充human choice。
- [ ] orientation綁可用臨街邊或使用者方向；不能只旋轉全局axis而忽略building entrance。
- [ ] hard FAR upper bound與optional target_range分離。沒有target不自動追求填滿上限；若目標不可達，回gap與reason，不偷偷改target。
- [ ] height policies可選uniform／toward_center／along_spine／context_transition；政策是設計偏好，環境效益未模擬就不宣稱。
- [ ] 先配置合法footprints，再逐層分配GFA額度：按使用者program優先與strategy order，新增一層前檢查global＋zone cap＋height。相同seed固定tie-break；不可因B上限提高重新換seed／減少原A量體却稱更高強度。
- [ ] 對不同layout不保證B必然FAR較高；只有相同footprint/strategy的controlled intensity test要求目標回應，否則報布局改變造成的trade-off。
- [ ] retained GFA未知：如果有可信範圍，用upper bound做cap conservative check；完全未知時formal cap=UNVERIFIABLE，不能除掉它。Preview可報known_part，但不能標正式全量合格。

Independent known-answer test：EDA1000m²、兩棟10×20m各3層→new GFA1200、coverage0.4、new FAR1.2；再有保留100m²兩層→total GFA1400、coverage0.5、FAR1.4。setback/overlap另用獨立fixture，不能用generator自身metrics當reference。
height-only增加一層→增量GFA=該層實際polygon.area，road hash相同；側面1m改動後後端以每層geometry重算。
CP-G4：density、用途與高度可解釋；無numeric overclaim；不是只把幾何VALID畫在圖上。

## Task G5：策略差異與設計品質比較

Create `generation/comparison.py`、`tests/test_generation_comparison.py`。
ComparisonBundle欄位：同context refs、每candidate validation、metric values/units/status、strategy choices、unallocated理由、changes、remaining_hypotheses；無overall_score/winner。

差異檢查：
- hash equality先去除完全重複。
- skeleton差異：同域roads buffer對稱差面積比、graph degree histogram、主要open-space連通分量／位置。
- massing差異：footprint union IoU、height分布、frontage orientation、type mix；顏色或名稱不算差異。
- 候選對至少一個組織維度有明確差異且附圖；工程初始顯著差異閾值作版本化method parameter，不能假稱都市設計美學標準。
- display目前method未算的sun/wind/energy只寫NOT_RUN。

- [ ] RED：同geometry換label→duplicate；只加高在skeleton diversity上仍same；三個recipe輸出同骨架不能謊称三個不同道路策略。
- [ ] target3策略、最大候選嘗試數9作有界工程budget；不足保留1/2個及failure原因，不盲目無限重抽。
- [ ] 使用者不喜歡的結果可Reject＋理由，不刪除；這些回饋是下一brief revision，不倒寫本次測量。
CP-G5：比較說明「不同在哪、回應什麼、代價是什麼」；展示不自動排名。

## Task G6：frozen M4H integration及人類設計評議

Create `tests/test_generation_pipeline.py`、`scripts/run_generation_v5_preview.py`（只在輸出新目錄與DB副本中跑）。
- [ ] 先合成fixture驗證G0–G5，再用frozen M4H來源跑新的append-only preview，不能覆寫v4/run-01。
- [ ] 歷史研究preserved清單可作UNAPPROVED_PREVIEW assumptions；正式approved-input run必須讀有效workspace處置及ConstraintSet。
- [ ] 執行入口必填output root、source refs、brief ref、mode-independent strategy ids/seed；空directory用exclusive create，已存在拒絕，不覆蓋peer output。
- [ ] 交付圖面：同視角平面、等角、道路／開放空間骨架、保留對照、用途／高度圖、每分區強度表。
- [ ] Designer看三方案是否有合理組織／基地回應／量體差異；記feedback而非AI自評優秀。
- [ ] 與舊v4比較的是改變與已驗證指標，不宣稱新的generator必定更好。
CP-G6：工程可用與人類認可分開列；風/熱/能耗或法律判斷不在此gate。

## 共同執行契約

本文件與 `2026-09-30-site-analysis-generation-master-zh.md` 同版使用。一次只領一個task，先RED再GREEN；原始輸入只讀、每個CP更新shared event。所有新符號／route為planned，既有fixtures成功不代替live驗證。尚未取得main merge／runtime activation批准時，交付reviewable diff，不自行部署。

## 實作參考與可執行反例（G0/G1）

`generation/hashing.py` 的 JSON 語義摘要核心；呼叫前先把 geometry canonicalize、set 轉排序序列、units 正規化，禁止直接用 GeoJSON 原始頂點順序：
```python
import hashlib
import json

def semantic_digest(payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()

def stage_seed(run_seed: int, strategy_id: str, stage: str) -> int:
    value = semantic_digest({"seed": run_seed, "strategy": strategy_id, "stage": stage})
    return int(value.split(":")[1][:16], 16)

def geometry_request_payload(request: dict) -> dict:
    # Explicit allowlist: UI mode cannot affect geometry. Missing keys fail.
    fields = ("input_refs", "seed", "strategy_id", "algorithm_version", "method_parameters")
    return {key: request[key] for key in fields}
```
geometry canonicalization：Polygon exterior CCW、holes CW；ring起點使用lexicographic最小座標，holes及MultiPolygon components按normalized WKB排序；拒絕非finite。保留原geometry bytes，hash另保存精度版本與normalized digest。若採Shapely normalize/set_precision，先測自交、窄於精度的通道、塌縮polygon，禁止正規化悄悄改變可通行性。

`tests/test_generation_contracts.py`：
```python
from urban_design.generation.hashing import geometry_request_payload, semantic_digest

def test_stage_hash_excludes_mode_and_timestamps():
    base = dict(input_refs=[], seed=17, strategy_id="fixture-grid",
                algorithm_version="fixture-v1", method_parameters={})
    a = dict(base, mode="FULL_SCHEME", created_at="fixture-time-A")
    b = dict(base, mode="STEPWISE", created_at="fixture-time-B")
    assert semantic_digest(geometry_request_payload(a)) == semantic_digest(geometry_request_payload(b))
    c = dict(base, seed=18)
    assert semantic_digest(geometry_request_payload(a)) != semantic_digest(geometry_request_payload(c))
```
這是純hash fixture，空refs不代表完整GenerationContext允許無來源執行。

H-shape 的synthetic geometry specification（米，局部origin，非基地批准參數）：
```python
from shapely.geometry import box
from shapely.ops import unary_union

def h_fixture_reference():
    return unary_union([box(10, 10, 20, 70), box(80, 10, 90, 70),
                        box(20, 35, 80, 45)])

def test_h_reference_known_area():
    reference = h_fixture_reference()
    assert reference.area == 1800
    assert reference.is_valid
    assert reference.geom_type == "Polygon"
```
正式 profile test 必須呼叫 adapter 後對 reference 做 symmetric_difference area 與 boundary Hausdorff distance 比較，不能只測reference自身。另用非對稱尺寸、rotate90、保留障礙物與無效thickness反例，避免 implementation 直接hardcode這個fixture。
