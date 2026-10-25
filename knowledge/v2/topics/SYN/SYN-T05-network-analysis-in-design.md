# 網路分析在設計中的使用（Network Analysis in Urban Design Practice）
領域：SYN｜相關細卡：KU-SYN-057, KU-SYN-058, KU-SYN-059, KU-SYN-060, KU-SYN-061, KU-SYN-062, KU-SYN-063, KU-SYN-064, KU-SYN-077, KU-STR-077, KU-SYN-002

## 一句話
空間網路分析在都市設計實踐中應當被視為「可被反駁與方案迭代的診斷假說」，透過嚴格凍結路網規則、度量半徑與成本設定，在循證設計中引導活躍界面與可及性優化，而非作為推銷特定形式的偽客觀科學包裝。

## 核心概念與定義
1. **循證都市設計迭代流程（Evidence-Based Design Iteration）**：將網絡分析從純學術事後解釋轉型為前置方案生成與多方案比選工具（KU-SYN-061, KU-SYN-064）：
   - 凍結基線網絡與邊界條件（Baseline network freezing）；
   - 生成多個替代路網拓樸方案（如方案 A 正交網、方案 B 局部打通、方案 C 超級街廓人行化）；
   - 在相同尺度半徑與參數下比較整合度、選擇度與空間資本變化；
   - 識別關鍵「瓶頸切點（Bottlenecks）」與「潛力骨幹走廊」（KU-SYN-061, KU-SYN-064）。
2. **城市網絡分析工具箱（Urban Network Analysis Toolbox, UNA）**：Andres Sevtsuk 等人（2010, 2016）開發的空間網絡架構（SEVTSUK10, SEVTSUK2016）：
   - 以建築物地塊作為起點與終點，以實際度量人行路網為載體；
   - 計算五大空間網絡指標：可達性（Reach）、重力吸引（Gravity）、中介性（Betweenness）、接近性（Closeness）與競爭度（Hubs）；
   - 克服了空間語法忽視建築容積與門店尺度的限制（SEVTSUK2016）。
3. **凱文·林奇城市意象之網絡映射（Lynch's Imageability and Networks）**：將 Kevin Lynch（1960）的五大意象元素（路徑 Paths、邊界 Edges、節點 Nodes、區域 Districts、地標 Landmarks）與網路中心性指標聯讀：高選擇度路段映射為關鍵意象路徑，高接近度節點映射為城市公共活動節點，低連通屏障映射為空間邊界（KU-SYN-077, KU-STR-077）。
4. **邊界截斷誤差與防範協定（Edge Effect Mitigation）**：若分析邊界僅以規劃紅線為界，邊緣節點將被人為剝奪外部連接，產生嚴重的虛假邊界畸變；專業實踐要求分析底圖半徑必須至少為研究目標尺度半徑的 2 至 3 倍以上（KU-SYN-063）。

## 主要立場與學派
1. **循證設計與分析引導學派（Foster + Partners 專案組；Space Syntax Ltd.；Andres Sevtsuk UNA 團隊）**：主張將網絡演算法無縫嵌入 CAD/BIM/GIS 數位工作流，以數據驅動方案優化，消解設計師盲目的主觀臆斷（SEVTSUK2016, KU-SYN-061）。

2. **對主流論點的批評**：把指標當作可反駁假說，並在設計前後用同一邊界、模式、半徑和路網建構方法比較。 [KU-SYN-061]
## 關鍵證據與數字
- **Sharmin & Kamruzzaman（2017）相關性上限警告**：實證統合分析顯示，空間網絡指標對行人流動的統計相關係數（r）中位數約落在 0.40 至 0.50 之間（R² 約 0.20–0.30），意味著有 70% 以上的人流變異是由微氣候、商業業態、階級偏好與歷史習慣決定，網絡分析絕非全能預測器（SHARMIN17, KU-SYN-059）。

## 經典案例
- **英國倫敦千禧橋與泰晤士河南北岸縫合分析（Millennium Bridge, 2000 年）**：
- **新加坡裕廊湖區立體步道網絡 UNA 最佳化（Jurong Lake District, 2016 年起）**：

## 爭議與批評
實務中主要爭議之一是「以量化結果為既定方案背書」：設計機構往往已預設特定形態方案，事後透過調試演算法參數、調整邊界緩衝區產生「數據證明方案較完整」的報告，誤導決策（KU-SYN-058, KU-SYN-063）。此外，純網絡指標忽略了無障礙坡道、治安死角、街道照明與樹蔭遮蔽等細微但關鍵的空間體驗（KU-SYN-057, KU-SYN-061）。

## 設計應用：在新開發區怎麼用、何時不適用
- **在新開發區怎麼用**：建立規範的循證分析協定：在方案初期凍結基地周邊 3–5 公里半徑的區域網絡（防範邊界效應）（KU-SYN-063）。將路網微調作為變數，在度量尺度（R400m、R800m）下比選選擇度（Choice）增益（KU-SYN-061, KU-SYN-068, KU-SYN-069）。分析成果僅作為指派底層商業連續界面與活動節點的候選假說，必須交由團隊進行微觀建築邊界、遮蔭與無障礙校核（KU-SYN-061, KU-SYN-077）。
- **何時不適用**：垂直多層路網、河岸橋接或步行資料不足的場址，需明確建模網路層級、距離方式和邊界；空間語法指標只能作為方案比較線索，不能單獨預測人流。

## 常見錯誤
1. **未擴大底圖邊界的「紅線自嗨」**：僅對自己設計的基地紅線內部路網做封閉分析，基地外圍幾十米處有一條城市高鐵站或主幹道卻不納入計算，得出荒謬的內部中心性（KU-SYN-063）。
2. **演算法決定論取代綜合設計**：以為軟體計算出某個路口中介度最高，就盲目在該處硬造一個大尺度廣場，無視該處面臨強烈的西曬與立面消極排風口，最終成為炎熱無人的活動較少空間（KU-SYN-058, KU-SYN-061）。

## 延伸閱讀
- SEVTSUK10: Andres Sevtsuk (2010) - Path and Place: A Study of Urban Geometry and Retail Activity in Cambridge and Somerville, MA
- SEVTSUK2016: Andres Sevtsuk, Kaloyan Mekonnen (2016) - Urban Network Analysis Toolbox: Open-Source Tools for Evaluating Pedestrian Activity
- PORTA06: Sergio Porta et al. (2006) - The Network Analysis of Urban Streets: A Primal Approach
- SHARMIN17: Selim Sharmin, Md. Kamruzzaman (2017) - Meta-analysis of the relationships between space syntax measures and pedestrian movement
- HILLIER96: Bill Hillier (1996) - Space is the Machine
