# 熱舒適指標（PET、UTCI）（Outdoor Thermal Comfort Indices: PET and UTCI）
領域：CLI｜相關細卡：KU-CLI-008, KU-CLI-038, KU-CLI-039, KU-CLI-040, KU-CLI-041, KU-CLI-050, KU-CLI-057, KU-CLI-058, KU-CLI-059, KU-CLI-060

## 一句話
室外熱舒適指標（PET 與 UTCI）透過人體熱平衡模型將空氣溫度、濕度、風速與平均輻射溫度整合為等效溫度標尺，但在跨氣候帶舒適區界定、心理適應性權重及極端微氣候預測上存在邊界假設差異。

## 核心概念與定義
1. **室外熱平衡與人體熱壓力**：人體與周邊環境的熱交換遵循熱平衡方程：M + W + R + C + ED + ESw + ERe + L = S（代謝率 + 做功 + 輻射 + 對流 + 皮膚擴散散熱 + 出汗蒸發 + 呼吸熱損失 + 呼吸潛熱 = 儲熱率）；當體溫調節機制（血管舒縮、出汗、顫抖）維持儲熱 S ≈ 0 時，人體處於熱中性平衡（HOPPE1999, BRODE2012）。
2. **生理等效溫度（Physiological Equivalent Temperature, PET；Höppe 1999）**：以慕尼黑能量平衡模型（MEMI）為基礎；指在典型的室內參考環境條件下（氣溫等於平均輻射溫度 Ta = Tmrt，相對濕度 50%，靜風 v = 0.1 m/s），當一標準人（男性，代謝率 80 W 輕度工作，服裝熱阻 0.9 clo）的核心與皮膚溫度達到與戶外複雜環境相同的熱平衡時，該室內參考環境的空氣溫度（單位：°C）（HOPPE1999, MATZARAKIS1999, KU-CLI-038）。
3. **通用熱氣候指標（Universal Thermal Climate Index, UTCI；Jendritzky et al. 2012）**：由 COST Action 730 國際團隊開發的高精度多節點人體熱生理模型（Fiala 模型，具 187 個組織節點），耦合了先進的自適應動態服裝隔熱模型；其參考環境為靜止空氣、相對濕度 50% 且 Ta = Tmrt，標準步行代謝率為 135 W/m²（約 2.3 met，時速 4 km/h）（JENDRITZKY2012, BRODE2012, KU-CLI-040）。

## 主要立場與學派
1. **熱生理學與生物氣象客觀學派（Peter Höppe 1999；Gerd Jendritzky 2012；Andreas Matzarakis 1999）**：主張熱舒適本質上是可客觀測量的熱力學與人體生理生化反應；反對單純以氣溫判定舒適，堅持必須全面採集太陽輻射（Tmrt）、風速與濕度，並以多節點生理數學模型為通用標準（RayMan、ENVI-met 核心），為城市法規提供跨地域橫向可比的熱壓力警報標準（MATZARAKIS1999, BRODE2012, KU-CLI-039, KU-CLI-041）。
2. **適應性熱舒適與環境心理學派（Marialena Nikolopoulou 2003；Gail Brager & Richard de Dear 1998）**：批評純生理模型忽略了人的「主觀心理適應（Psychological Adaptation）」、「行為調節（Behavioral Adjustment）」與「文化氣候記憶」；指出長期生活於熱帶或地中海的居民，其心理期望與耐熱閾值顯著高於北歐溫帶人口；單純依賴歐洲基準的 PET 分級會嚴重高估南方居民的熱不適感（NIKOLOPOULOU2003, BRAGER1998, KU-CLI-008, KU-CLI-057）。

3. **對主流論點的批評**：把單一城市的舒適帶移植到另一氣候區可能造成錯誤設計優先次序。 [KU-CLI-039]
## 關鍵證據與數字
- **UTCI 熱壓力分級標準（Cost 730 / Brode et al. 2012）**（KU-CLI-041, KU-CLI-059）：
  - **極端冷壓力**：< -40 °C
  - **強烈冷壓力**：-27 至 -40 °C
  - **中度冷壓力**：-13 至 -27 °C
  - **輕度冷壓力**：0 至 -13 °C
  - **無熱壓力（舒適中性區間）**：+9 至 +26 °C
  - **中度熱壓力**：+26 至 +32 °C
  - **強烈熱壓力**：+32 至 +38 °C
  - **極強熱壓力**：+38 至 +46 °C
  - **極端熱壓力**：> +46 °C
- **PET 舒適區的地域校準差異（Lin & Matzarakis 2008；Johansson et al. 2006）**：
  - 西歐中緯度溫帶（德國原創基準）：中性舒適 PET 為 18–23 °C，>35 °C 即判定為強熱壓力（HOPPE1999）。
- **平均輻射溫度（Tmrt）對舒適指標的支配性（Matzarakis et al. 1999）**：敏感度分析證實，在晴朗無雲的夏季正午，每增加 10 °C 的 Tmrt，PET 指標相應上升約 4–5 °C；而提高風速 1 m/s 僅能降低 PET 約 1.5–2 °C，證實「遮蔽太陽直接輻射」是戶外降溫最直接有力的物理槓桿（MATZARAKIS1999, KU-CLI-030）。

## 經典案例
- **希臘雅典市中心歷史廣場熱適應問卷與實測對比（RUROS 計畫；Nikolopoulou 2003）**：
  - 年代：2001–2003 年（歐盟 RUROS 專案研究）（NIKOLOPOULOU2003）
  - 策略：同步進行微氣候氣象站實時監測（Ta、Tmrt、Va、RH）與現場隨機行人熱感覺投票（TSV / ASHRAE 7 級標度）（KU-CLI-060）。
  - 成效：實證揭示實際處於「客觀強熱壓力」的受訪者中，超過 35% 仍勾選「感覺良好／舒適」，證實空間環境美感、自然景觀視野、自主選擇停留權（Perceived Control）對人體主觀耐受度具有顯著的正面緩衝效應（KU-CLI-008, NIKOLOPOULOU2003）。
- **巴西庫里奇巴（Curitiba）亞熱帶街谷微氣候與熱舒適校準（Krüger et al. 2011）**：
  - 地點：巴西南部庫里奇巴市中心步行街區（KRUGER2011）
  - 策略：以不同幾何街谷（H/W 由 0.3 至 2.5）為對象，對比 PET 與預測平均熱感（PMV）在當地的適用度（KU-CLI-014, KU-CLI-039）。
  - 成效：建立了首個針對巴西亞熱帶氣候的本地化 PET 分級修正量表，證實居民對直射陽光的耐受度顯著高於西歐模型，為南美洲城市氣候規劃提供了本土基準（KU-CLI-058）。

## 爭議與批評
主要學術分歧在於「PET 與 UTCI 之間的模型選型爭論」（KU-CLI-050）。PET 模型假設固定服裝隔熱值（0.9 clo）與室內靜止參考條件，其優勢在於輸出數值為直觀的「攝氏度（°C）」，規劃師與公眾極易理解；但缺點在於無法反映行人在強風環境下的動態衣服透風調節，在極端高風速或極端高濕度下預測偏差較大。UTCI 具備世界氣象組織（WMO）背書的精密多節點動態生理服裝調節算法，在風風速敏銳度與極端環境下物理精確度顯著更高，但其模型過於複雜，計算成本極高且其「熱壓力區間（Stress Categories）」較難直接對應至建築日常設計圖說（KU-CLI-040, KU-CLI-050, BRODE2012）。

## 設計應用：在新開發區怎麼用、何時不適用
- **在新開發區怎麼用**：在新城公共空間規劃中，將 PET 或 UTCI 的時空分佈圖作為空間功能分區的法定前置校核依據：
  - 在夏季正午時段（11:00–15:00），主要步行動線與兒童遊樂場的目標 PET 必須控制在中度熱壓力以下（中緯度 ≤ 29 °C，亞熱帶 ≤ 34 °C）；若裸露地表導致 PET > 40 °C，必須強制配置高密度喬木林冠或連續遮陽棚架（KU-CLI-031, KU-CLI-066）。
  - 建立「清涼步行網絡（Cool Corridors）」：沿軌道站點、住宅出入口與學校之間，串聯陰影連續率大於 70% 的步行路徑，將平均輻射溫度 Tmrt 壓低至 40 °C 以下（KU-CLI-061, KU-CLI-072）。
- **何時不適用**：有季節性熱浪、強風或明顯街谷差異的場址，需以當地逐時氣象、街谷和暴露資料檢核；另一氣候區的單一指標不能直接作為設計門檻。

## 常見錯誤
1. **直接將室內熱舒適 PMV 指標套用於室外**：忽略室外短波太陽直射、散射與地表長波輻射的極端波動性，直接拿適用於室內均勻低風速的 Fanger PMV 模型評價街道廣場，導致預測熱感嚴重失真（HOPPE1999, BRODE2012）。
2. **拿未經本土校準的西歐 PET 門檻評估熱帶新城**：直接以德國 23 °C 以上即為「微熱」的標準宣判熱帶城市整年「不舒適」，否定了當地深厚遮陽通風建築傳統與市民的生理耐受能力（KU-CLI-039, KU-CLI-058）。
3. **只比氣溫忽略平均輻射溫度 Tmrt**：以為樹蔭下氣溫只比陽光下降了 1.0 °C「效果不明顯」，忽視了在樹蔭遮蔽下 Tmrt 劇降 20–30 °C，使行人 PET 實質改善高達 10–15 °C 的決定性生理舒適收益（KU-CLI-030, KU-CLI-062）。

## 延伸閱讀
- HOPPE1999（Höppe, 1999）- The physiological equivalent temperature – a universal index for the biometeorological assessment of the thermal environment.
- MATZARAKIS1999（Matzarakis et al., 1999）- Applications of a universal thermal index: physiological equivalent temperature.
- JENDRITZKY2012（Jendritzky et al., 2012）- UTCI—Why another thermal index?
- BRODE2012（Bröde et al., 2012）- Deriving the operational procedure for the Universal Thermal Climate Index (UTCI).
- NIKOLOPOULOU2003（Nikolopoulou & Steemers, 2003）- Thermal comfort and psychological adaptation as a guide for designing urban spaces.
