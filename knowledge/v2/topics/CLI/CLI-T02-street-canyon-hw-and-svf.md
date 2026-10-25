# 街谷 H/W 與 SVF（Street Canyon Aspect Ratio and Sky View Factor）
領域：CLI｜相關細卡：KU-CLI-001, KU-CLI-002, KU-CLI-003, KU-CLI-009, KU-CLI-012, KU-CLI-013, KU-CLI-014, KU-CLI-015, KU-CLI-016, KU-CLI-017, KU-CLI-018, KU-CLI-019, KU-CLI-065

## 一句話
街谷高寬比（H/W）與天空可視因子（SVF）是決定都市街道微氣候的雙重核心幾何參數，在日間太陽輻射屏蔽與夜間長波散熱／通風稀釋之間構成經典的微氣候權衡（Microclimate Trade-off）。

## 核心概念與定義
1. **街谷高寬比（Aspect Ratio, H/W）**：街道兩側建築平均高度（H）與兩側建築外牆間距／街道寬度（W）的比值；通常分類為淺街谷（H/W < 0.5）、均勻街谷（H/W ≈ 1.0）與深街谷（H/W ≥ 2.0 至 3.0+）（KU-CLI-001, KU-CLI-013, OKE1988）。
2. **天空可視因子（Sky View Factor, SVF）**：某個觀測點（通常取行人頭部高度 1.2–1.5 m）仰望可見的半球天空立體角與整個上半球立體角（2π）的比值，數值介於 0（全被建築與樹木遮蔽）到 1（開敞無遮蔽的平原）之間（KU-CLI-016, KU-CLI-017, GIVONI1998）。
3. **微氣候日夜雙重效應（Diurnal Asymmetry）**：
   - **日間效應**：深街谷（高 H/W、低 SVF）能提供大量自遮蔭（Self-shading），顯著降低行人地面的直接太陽短波輻射與平均輻射溫度（Tmrt），在炎熱夏季提供日間微氣候庇護（ALITOUDERT2006, JOHANSSON2006）。
   - **夜間效應**：低 SVF 阻礙了地面與牆面將白天儲存的熱能以長波長紅外輻射向上空冷宇宙散發，大量輻射在對望建築外牆間反覆反射吸收（Radiation Trapping），導致夜間街谷降溫遲緩、熱島效應加劇（OKE1981, KU-CLI-003）。

## 主要立場與學派
1. **氣候適應幾何平衡派（Florian Ali-Toudert 2006；Erik Johansson 2006）**：主張街谷微氣候優劣無法單看 H/W 值，必須嚴格與「街道走向（Orientation）」及「宏觀氣候帶」聯合判定；在乾熱與亞熱帶氣候中，深街谷搭配東西向或西北-東南向佈局能最大化夏季遮蔭效益，微氣候設計應追求冬夏平衡的幾何優化（ALITOUDERT2006, JOHANSSON2006, KU-CLI-014, KU-CLI-015）。
2. **空氣品質與風環境流體力學派（Urban Air Quality & Fluid Dynamics）**：指出高 H/W 深街谷在流體力學上會形成封閉的「空腔渦流（Cavity Vortex）」，外部風流無法有效滲透至街道底層；車輛排出的二氧化氮、一氧化碳與懸浮微粒（PM2.5）被鎖死在街谷底層無法稀釋擴散，形成高毒性空氣污染走廊（GROMKE2007, KU-CLI-019, BLOCKEN2016）。

3. **對主流論點的批評**：LCZ 分類改善跨站點一致性，但分類品質仰賴現地 metadata。 [KU-CLI-002]
## 關鍵證據與數字
  - **獨立粗糙流（Isolated Roughness Flow）**：H/W < 0.3，建築物後方尾流互不干擾，地面通風良好。
  - **尾流干擾流（Wake Interference Flow）**：0.3 ≤ H/W ≤ 0.65，相鄰建築下洗氣流與尾流交疊，產生局部亂流。
  - **滑行空腔流（Skimming Flow）**：H/W > 0.65，主氣流從建築屋頂上方滑過，街谷內部形成穩定的孤立旋渦，底部風速驟降至外界的 10%–20%，污染物擴散能力急劇衰減。
- **摩洛哥非斯古城實測對比（Johansson 2006）**：對比極端深街谷（傳統古城，H/W ≈ 4.0，SVF ≈ 0.1）與現代開敞淺街谷（新城區，H/W ≈ 0.6，SVF ≈ 0.65）：夏季深街谷日間空氣溫度比淺街谷低達 6.0 °C，生理等效溫度（PET）降溫幅度高達 15–20 °C；但在冬季，深街谷因缺乏陽光，全日體感處於寒冷不適狀態（JOHANSSON2006, KU-CLI-014, KU-CLI-065）。
- **數值模擬遮蔭極限（Ali-Toudert & Mayer 2006）**：在東-西走向的街道中，唯有當 H/W 達到 2.0 以上時，南側建築陰影才能在正午覆蓋人行道；而南-北走向街道即使 H/W 高達 3.0，在正午前後 2 小時仍必然遭受短暫強烈直射曝曬（ALITOUDERT2006, KU-CLI-012）。

## 經典案例
- **摩洛哥非斯（Fez）伊斯蘭傳統古城與新城微氣候對比（Johansson 2006 實證研究）**：
  - 年代：2006 年系統性實測發表（JOHANSSON2006）
  - 策略：古城採用極其緊湊的有機曲折巷道網絡，H/W 高達 3.0–5.0，結合懸挑樓層與拱廊過街樓，將地面 SVF 壓低至 0.05–0.15；新城則採用歐洲寬闊大道（H/W ≈ 0.6）（KU-CLI-014）。
- **西班牙巴塞隆納 Eixample 擴展區八角街廓（Cerdà Block，1859 年至今）**：
  - 策略：原設計街寬 20 公尺，建築限高 16–20 公尺（初期 H/W ≈ 0.8–1.0），轉角設置 45 度倒角（Chamfered corners），內部保留大花園天井以平衡通風與採光（KU-CLI-001, KU-CLI-043）。

## 爭議與批評
街谷設計的主要爭議在於「熱舒適、空氣品質與室內採光的取捨關係」（KU-CLI-015）。深街谷（高 H/W）在炎熱夏季對戶外行人熱舒適極為有利，但直接犧牲了建築低樓層的室內採光係數（Daylight Factor），導致住宅底層長年依賴人工照明，增加室內電耗；同時嚴重的空氣滯留效應使得城市交通主幹道兩側的居民長期吸入高濃度超標污染物（KU-CLI-019, GROMKE2007, ALITOUDERT2006）。

## 設計應用：在新開發區怎麼用、何時不適用
- **在新開發區怎麼用**：依據氣候帶採取差異化 H/W 與斷面控制：
  - **夏熱冬暖／亞熱帶地區**：商業步行街宜控制 H/W 在 1.2–1.8 之間，街道走向優先偏轉為與夏季盛行風成 30°–45° 夾角（避免平行被曬透，亦避免垂直阻風）；底層設置連續騎樓（Arcades）或挑簷，使地面行人有效 SVF 降至 0.2–0.3，同時在建築屋頂設置通風孔隙（KU-CLI-012, KU-CLI-043, KU-CLI-065）。
  - **高層綜合區**：採用「裙樓基座連續（維持行人遮蔭）+ 塔樓退台錯開（開放上空 SVF 促進夜間散熱與高空風下洗）」的復合斷面，打破單一均勻街谷的封閉空腔流（KU-CLI-042, KU-CLI-045）。
- **何時不適用**：有季節性熱浪、強風或明顯街谷差異的場址，需以當地逐時氣象、街谷和暴露資料檢核；另一氣候區的單一指標不能直接作為設計門檻。

## 常見錯誤
1. **脫離街道朝向單純孤立要求 H/W 數值**：未考慮太陽方位角，將東-西向大街兩側建造成 H/W = 0.8 的低矮街谷，導致整條街道在夏季正午裸露在強烈暴曬之下（KU-CLI-001, KU-CLI-012）。
2. **誤將 SVF 數值直接等同於熱舒適指標**：將 SVF 當作打分卡，誤以為「SVF 越低越舒適」，忽略了夜間散熱需求以及冬季需要高 SVF 引入陽光提升體溫的季節矛盾（KU-CLI-018, KU-CLI-057）。
3. **忽略行道樹冠層對 SVF 與通風的耦合干擾**：在深街谷（H/W > 1.5）內部密集種植濃密高大常綠喬木，使得林冠與建築外牆將街谷大幅「封頂」，雖然阻擋了陽光，卻將汽車廢氣封鎖在呼吸帶，且夜間阻斷向上散熱（KU-CLI-005, GROMKE2007）。

## 延伸閱讀
- ALITOUDERT2006（Ali-Toudert & Mayer, 2006）- Numerical study on the effects of aspect ratio and orientation of an urban street canyon on outdoor thermal comfort in hot and dry climate.
- JOHANSSON2006（Johansson, 2006）- Influence of urban geometry on outdoor thermal comfort in a hot dry climate: A study in Fez, Morocco.
- OKE1981（Oke, 1981）- Canyon geometry and the nocturnal urban heat island: comparison of scale model and field observations.
- STEWART2012（Stewart & Oke, 2012）- Local climate zones for urban temperature studies.
- GIVONI1998（Givoni, 1998）- Climate considerations in building and urban design.
