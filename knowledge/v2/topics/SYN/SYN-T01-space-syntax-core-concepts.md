# 空間語法基本概念（軸線、線段、整合度、選擇度、R3／Rn）（Space Syntax Core Concepts: Axial, Segment, Integration, Choice, R3/Rn）
領域：SYN｜相關細卡：KU-SYN-001, KU-SYN-002, KU-SYN-003, KU-SYN-004, KU-SYN-005, KU-SYN-006, KU-SYN-007, KU-SYN-008, KU-SYN-009, KU-SYN-010, KU-SYN-011, KU-SYN-012, KU-SYN-013, KU-SYN-014, KU-SYN-015, KU-SYN-016, KU-SYN-033, KU-SYN-034, KU-SYN-035, KU-SYN-036, KU-SYN-037, KU-SYN-038, KU-SYN-039, KU-SYN-040, KU-SYN-065, KU-SYN-066, KU-SYN-067, KU-SYN-071, KU-SYN-072

## 一句話
空間語法透過將實體街道組態抽象為對偶拓樸與角度線段圖，量化路段在網絡中的到達潛力（整合度）與穿行潛力（選擇度），提供一套解碼空間結構如何自組織引導人類移動的客觀圖論方法。

## 核心概念與定義
1. **空間組態與圖表示法演進（Spatial Configuration and Representation）**：
   - 軸線圖（Axial Map）：貫穿連續視覺開敞空間之「最少且最長」直線集合，代表行人的視線與可行進路徑（KU-SYN-003, KU-SYN-071）。
   - 線段圖（Segment Map）：將軸線在每個交叉路口切斷為獨立線段，克服長軸線跨越多個交叉口的粗放限制（KU-SYN-001, KU-SYN-071）。
2. **兩大核心中心性維度（Integration and Choice）**：
   - 整合度（Integration / Closeness）：某路段到達系統內所有其他路段的平均深度（Mean Depth）之倒數，反映該處被作為目的地的「到達潛力（To-movement potential）」（KU-SYN-010, KU-SYN-016）。
   - 選擇度（Choice / Betweenness）：在系統所有起迄點（OD）之間的最短路徑中，經過該路段的頻次比例，反映「穿過該處的過境潛力（Through-movement potential）」（KU-SYN-010, KU-SYN-016）。
3. **距離度量與轉向成本（Cost Metrics）**：
   - 拓樸步數（Topological Steps）：傳統軸線跳躍次數（KU-SYN-033, KU-SYN-072）。
   - 角度偏差成本（Angular Deviation）：依轉彎角度（0°–90°–180°）累加幾何轉向阻抗，更貼合人類導航認知（KU-SYN-033, KU-SYN-067, KU-SYN-072）。
   - 度量公尺距離（Metric Distance）：實體物理長度（KU-SYN-072）。
4. **分析半徑尺度（Radius Scales: R3, Rn, Metric Radii）**：
   - 局部尺度 R3：拓樸 3 步以內的鄰里視野（KU-SYN-065）。
   - 全域尺度 Rn：無邊界限制、全城連通網絡的宏觀視野（KU-SYN-066）。

## 主要立場與學派
1. **古典倫敦 UCL 空間語法學派（Bill Hillier & Julienne Hanson 1984；Alan Penn）**：主張空間組態（Configuration）是決定社會交往與移動的自變數，空間本身即蘊含社會邏輯；主張拓樸與角度阻抗大於純歐氏距離（HILLIER84, HILLIER96, HILLIERPENN04）。
2. **原始網絡科學學派（Sergio Porta et al. 2006 Primal Approach）**：反對將交叉口抽象為邊的對偶圖做法，提倡原生圖（Primal Graph，交叉口為節點、路段為邊），提供與空間語法互補的複雜網絡中心性分析（PORTA06, KU-SYN-002）。

3. **對主流論點的批評**：模型結果可能受裁切邊界、道路分類和缺失通道支配。 [KU-SYN-063]
## 關鍵證據與數字
- **Sharmin & Kamruzzaman（2017）隨機效果統合分析（40 篇實證檢驗）**：
  - 整體整合度與行人移動量之加權合併效果量為 ES 0.206（95% CI 0.173–0.238）（KU-SYN-009, KU-SYN-011, SHARMIN17）。
  - 模型表示法分組顯示：角度整合度（Angular Integration）的合併效果量高達 ES 0.502，而傳統拓樸整合度僅為 0.124，證明角度線段模型具備壓倒性解釋力（KU-SYN-001, KU-SYN-033, KU-SYN-035）。
  - 選擇度維度：角度選擇度 ES 為 0.493，拓樸選擇度為 0.374（KU-SYN-034, KU-SYN-036）。
  - 連通度（Connectivity，相鄰直接路段數）效果量為 ES -0.001（p=0.990，無顯著關聯）（KU-SYN-059, KU-SYN-060）。
- **荷蘭新舊市鎮形態對比（Ye & van Nes 2014）**：歷史舊城（Gouda）在 R800m 局部整合度與建築密度咬合度上顯著高於現代主義新城（Almere），解釋了新城地面步行活力的匱乏（YE14, KU-SYN-049）。

## 經典案例
- **英國倫敦考文特花園與西區街網演化（Hillier 1984, 1996 實證樣本）**：
- **英國倫敦國王十字車站周邊再生總圖（King's Cross Central, 2004–2010 年）**：

## 爭議與批評
空間語法面臨的最主要爭議在於「邊界效應（Edge Effect / Island Effect）」：分析範圍人為裁切邊界會人為壓低邊緣路段的整合度，造成假性「深層邊緣」（KU-SYN-063）。此外，經典空間語法強烈抗拒融入建築量體、微氣候舒適度與特定地標吸引物，常被批判為「幾何唯心主義」；不同分析師在繪製不規則廣場或蜿蜒舊巷時的主觀性，曾引發嚴重的學術複製危機（RATTI04, KU-SYN-041）。

## 設計應用：在新開發區怎麼用、何時不適用
- **在新開發區怎麼用**：在新城總體路網比選中，建立線段角度模型，同步輸出局部度量半徑（R400m、R800m）整合度與全域半徑（Rn）選擇度（KU-SYN-034, KU-SYN-065, KU-SYN-066）。將主要沿街零售、餐飲與公共設施嚴格指派至「高選擇度 + 高局部整合度」的雙高骨幹走廊；將安靜住宅門廳、托兒所配置於次級整合街巷，避免商業配置與人流潛力脫節（KU-SYN-012, KU-SYN-016）。
- **何時不適用**：垂直多層路網、河岸橋接或步行資料不足的場址，需明確建模網路層級、距離方式和邊界；空間語法指標只能作為方案比較線索，不能單獨預測人流。

## 常見錯誤
1. **將拓樸整合度直接等同於人流保證**：以為軟體算出來的紅色高整合路段就一定「人山人海」，不核對周邊有無商業活動、遮陽樹蔭或是否面臨高速公路圍牆阻隔（KU-SYN-009, KU-SYN-057）。
2. **分析範圍過小的嚴重邊界畸變**：基地範圍僅 1 km²，分析時就只繪製基地內部道路，導致基地邊緣所有對外幹道全被算成冰冷的「死角藍色」，大幅扭曲真實空間關係（KU-SYN-063）。

## 延伸閱讀
- HILLIER84: Bill Hillier, Julienne Hanson (1984) - The Social Logic of Space
- HILLIER96: Bill Hillier (1996) - Space is the Machine
- SHARMIN17: Selim Sharmin, Md. Kamruzzaman (2017) - Meta-analysis of the relationships between space syntax measures and pedestrian movement
- HILLIERPENN04: Bill Hillier, Alan Penn (2004) - Rejoinder to Carlo Ratti
- PORTA06: Sergio Porta et al. (2006) - The Network Analysis of Urban Streets: A Primal Approach
