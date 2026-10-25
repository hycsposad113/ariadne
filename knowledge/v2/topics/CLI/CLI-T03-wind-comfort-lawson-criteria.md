# 風舒適（Lawson）（Pedestrian Wind Comfort and Lawson Criteria）
領域：CLI｜相關細卡：KU-CLI-006, KU-CLI-010, KU-CLI-023, KU-CLI-024, KU-CLI-025, KU-CLI-052, KU-CLI-053

## 一句話
行人高度風舒適評估透過統計機率閾值（如 Lawson 準則）將風速大小與特定活動類型進行等級對應，其核心目標在於平衡高層建築下洗風引發的風災安全風險與夏季通風散熱需求。

## 核心概念與定義
1. **行人層風環境（Pedestrian-Level Wind, PLW）**：通常指地面以上 1.5–2.0 公尺（人體胸部至頭部高度）處的局部風速向量與紊流強度（KU-CLI-006, BLOCKEN2016）。
2. **Lawson 風舒適度準則（Lawson Comfort Criteria / LDDC / Lawson 2001）**：Lawson 類準則將風速門檻與活動類型、超越頻率相連；引用時需註明準則版本、平均時距和超越頻率。[KU-CLI-025]。
   - 準則規定某活動類型在該空間成立的前提是：等效風速（通常為小時平均風速或平均風加紊流陣風）超越特定臨界值的時間比例不超過 5%（即 P(U > U_threshold) < 5%）。
3. Lawson 風舒適準則有多個版本：LDDC 版約 4／6／8／10 m/s，City of London 版約 2.5／4／6／8 m/s；平均時距與超越頻率需與版本一致。[KU-CLI-025]。
   - **久坐（Sitting）**：U ≤ 4 m/s（適合戶外咖啡、長椅休憩、露天餐飲）。
   - **短暫停留／站立（Standing）**：U ≤ 6 m/s（適合公車站候車、櫥窗流連）。
   - **休閒漫步（Strolling）**：U ≤ 8 m/s（適合公園步道、商業街悠閒散步）。
   - **商務快步通行（Business Walking）**：U ≤ 10 m/s（適合地鐵出入口、主要交通通道）。
   - **不適／危險（Uncomfortable / Distress）**：U > 10 m/s 判定為全活動不適。
   - **風安全上限（Wind Safety Threshold）**：每年超越機率 0.022%（即約一年 2 小時）風速不得超過 15 m/s（老弱者跌倒風險）與 20 m/s（全體公眾吹倒吹傷風險）（KU-CLI-053）。

## 主要立場與學派
1. **風工程力學與建築安全學派（Bert Blocken 2016；Ted Stathopoulos 2006；AIJ 日本建築學會 2008）**：強調微觀風環境的嚴肅工程責任；主張任何超高層建築開發必須在規劃階段強制進行大比例尺邊界層風洞試驗（Boundary Layer Wind Tunnel, BLWT）或嚴格遵循 AIJ 規範的高精度大渦模擬（LES / RANS-CFD），將消除行人跌倒吹傷的「安全門檻（Safety Criteria）」置於首要法規地位（BLOCKEN2016, TOMINAGA2008, STATHOPOULOS2006, KU-CLI-024）。
2. **濕熱氣候自然通風與城市通風廊道學派（Edward Ng 2009；Baruch Givoni 1998）**：指出歐美源起之 Lawson 準則帶有顯著的溫帶/寒帶「防風」偏見；在香港、新加坡等高溫高濕熱帶與亞熱帶城市，行人層微氣候矛盾絕大多數時候是「靜穩無風、高度悶熱」，適度提升風速（1.5–3.0 m/s）是排走人體汗液、緩解熱壓力的關鍵手段；盲目防風將扼殺通風廊道（Air Paths）的散熱效益（NG09, KU-CLI-010, KU-CLI-052）。

3. **對主流論點的批評**：縮寫常被轉成一組脫離背景的數字，可能抹去地方採用規則。 [KU-CLI-025]
## 關鍵證據與數字
- **高層孤立塔樓的風速放大係數（Blocken & Carmeliet 2004）**：當孤立高層建築高度大於周邊平均建築高度的 2 倍以上時，其下洗風在迎風轉角處（Corner）產生的行人層風速放大倍數可達 2.0–2.5 倍（即外界 5 m/s 的和風，在轉角處被放大為 10–12.5 m/s 的強勁疾風），足以使常規步行受阻（BLOCKEN2016, KU-CLI-006）。
- **CFD 模擬的網格與邊界敏感度（AIJ 基準評估；Tominaga et al. 2008）**：日本建築學會跨機構盲測顯示，使用標準 k-ε 模型常高估建築背風面的空腔回流長度達 30%–50%，且對轉角分離流的紊流動能預測存在顯著偏差；因此法規審查要求 CFD 計算域入口邊界必須精確輸入氣象站威布爾分佈（Weibull Distribution）參數，且建築地面附近第一層網格高度必須嚴格小於 0.1–0.2 H（TOMINAGA2008, KU-CLI-024）。

## 經典案例
- **英國倫敦「對講機大樓」（20 Fenchurch Street / The Walkie-Talkie，2014 年）**：
- **瑞典馬爾默 Bo01 西方港灣生態新城（2001 年起）**：
  - 年代：2001 年作為歐洲住宅展覽示範區啟用（JOHANSSON2020MALMO）
  - 策略：面對波羅的海強勁凜冽的冬季海風，摒棄筆直棋盤網格，採用細密有機曲折的「碎步街巷（Irregular Alley Network）」；外圍建築高度朝向海側遞減，內部建築群落彼此遮擋以消解風能（KU-CLI-001, JOHANSSON2020MALMO）。
  - 批評：沿海第一排頂層公寓仍面臨劇烈海風呼嘯，且緊湊封閉的街巷格局在特定方向風向時形成了微型風洞效應通道（Wind Funnels）（JOHANSSON2020MALMO）。

## 爭議與批評
實踐中風舒適準則最常見的爭議在於「統計年超越機率是否掩蓋了嚴重的瞬時極端陣風」（KU-CLI-053）。Lawson 準則以小時平均風速統計超過 5% 為判定標尺，然而高層下洗風的致災往往發生在數秒鐘的突發孤立強陣風（Gust）。若僅關注全年的平均舒適時數，設計者可能得出「該地 96% 時間適合散步」的樂觀合規結論，卻掩蓋了每年數十次足以將長者吹倒骨折的極端轉角角隅陣風危險（KU-CLI-023, KU-CLI-053, STATHOPOULOS2006）。

## 設計應用：在新開發區怎麼用、何時不適用
- **在新開發區怎麼用**：在新城高層 CBD 規劃中，強制執行「建築形態消能四法」：
  1. **裙樓緩衝（Podium Shielding）**：高層塔樓底部強制退縮並設置連續 2–4 層裙樓（寬度不小於塔樓高度的 1/3），將高空下洗風攔截在裙樓屋頂，大幅阻止氣流直墜地面（BLOCKEN2016）。
  2. **角隅倒角或凹槽（Corner Chamfering / Recesses）**：塔樓平面輪廓避免銳利直角，採用倒角或開縫以削弱角隅渦流分離強度。
  3. **連續挑簷與多孔遮蔽**：在主要人行出入口設置長度不小於 3–5 公尺的水平連續防風挑簷或雙層大堂緩衝門斗。
  4. **防風林帶分級佈設**：在迎風廣場佈設透風率 40%–50% 的多孔常綠落葉混交林帶（多孔林消能效果顯著優於 100% 封閉實體牆）（KU-CLI-024, KU-CLI-052）。
- **何時不適用**：有季節性熱浪、強風或明顯街谷差異的場址，需以當地逐時氣象、街谷和暴露資料檢核；另一氣候區的單一指標不能直接作為設計門檻。

## 常見錯誤
1. **單一風向孤立評估**：僅模擬基地全年中頻率最高的一個主導風向，忽略了攜帶強風暴的次主導風向（如冬季極端寒潮或夏季強颱風方向），導致在次主導風向襲擊時街角產生極端風災風險（KU-CLI-052）。
2. **拿均勻風替代大氣邊界層風廓線**：在數值模擬中於計算域入口直接給予上下均勻的固定風速，忽視大氣邊界層風速隨高度呈對數或指數增長（Power Law）的客觀物理規律，嚴重低估塔樓頂部引發的下洗動能（BLOCKEN2016, TOMINAGA2008）。
3. **綠化防風屏障過於密實**：設置 100% 不透風的厚重實心圍牆，強風翻越牆頂後在背風側產生強烈負壓回流與反向渦旋，反而加劇了後方人行道的混亂紊流（KU-CLI-024, GROMKE2007）。

## 延伸閱讀
- BLOCKEN2016（Blocken et al., 2016）- Pedestrian-level wind conditions around buildings: Review of wind-tunnel and CFD techniques and their accuracy.
- TOMINAGA2008（Tominaga et al., 2008）- AIJ guidelines for practical applications of CFD to pedestrian wind environment around buildings.
- STATHOPOULOS2006（Stathopoulos, 2006）- Pedestrian level winds and outdoor human comfort.
- GROMKE2007（Gromke & Ruck, 2007）- Influence of trees on the dispersion of pollutants in an urban street canyon.
- JOHANSSON2020MALMO（Johansson et al., 2020）- Wind comfort and solar access in a coastal development in Malmö, Sweden.
