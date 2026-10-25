# 都市熱島（Urban Heat Island: Canopy and Surface Heat Dynamics）
領域：CLI｜相關細卡：KU-CLI-004, KU-CLI-020, KU-CLI-021, KU-CLI-022, KU-CLI-049, KU-CLI-064, KU-CLI-068, KU-CLI-071

## 一句話
都市熱島效應是由不透水硬質鋪面、幾何蓄熱、人為排熱與植被蒸散減少共同驅動的微氣候現象，其強度取決於大氣觀測層次與周邊對照基準，需以局部氣候區（LCZ）框架進行標準化界定以避免指標混淆。

## 核心概念與定義
1. **熱島層次的分異（Layers of Urban Heat Island）**：氣候學上熱島並非單一數值，嚴格劃分為不同物理層次（KU-CLI-004, KU-CLI-020, OKE2017）：
   - **地表熱島（Surface UHI, SUHI）**：透過衛星紅外熱遙感（如 Landsat、MODIS）測量的地表輻射溫度（LST）；日夜皆存在，白晝因建材強烈吸熱達到峰值（可高於周邊郊區 10–15 °C），但不能直接等同於人體感知的空氣溫度（KU-CLI-071）。
   - **都市冠層熱島（Canopy Layer UHI, CLUHI）**：由建築屋頂以下至地表空間的空氣溫度（2 m 行人高度）決定；通常在「日落後數小時至清晨日出前」達到最大強度，主因是高熱容量建物在夜間持續釋放儲存的長波輻射（KU-CLI-022, ARNFIELD2003）。
   - **都市邊界層熱島（Boundary Layer UHI, BLUHI）**：位於屋頂上方直至中尺度大氣混合層，受區域大氣對流與熱羽流主導。
2. **熱島強度（Urban Heat Island Intensity, UHII / ΔTᵤ₋ᵣ）**：都市測站與周邊未開發鄉村基準測站之間的氣溫差值（ΔT = T_urban - T_rural）；基準測站的選址（農田、森林、沙漠或機場）對計算結果具決定性影響（KU-CLI-021, KU-CLI-022）。
3. **局部氣候區體系（Local Climate Zones, LCZ；Stewart & Oke 2012）**：為消除傳統「城-鄉」二分法的模糊性，依據建築幾何密度、透水率、表面材料與人為熱釋放，將地表劃分為 17 類標準化景觀類型（LCZ 1 緊湊高層至 LCZ 10 重工業區，以及 LCZ A 茂密樹林至 LCZ G 水體）（STEWART2012, KU-CLI-002, KU-CLI-009）。

## 主要立場與學派
1. **都市微氣象與熱平衡學派（T.R. Oke 1981, 2017；I.D. Stewart 2012）**：主張以嚴格的地表能量平衡方程（Rn = H + LE + G + Qf，淨輻射 = 感熱 + 潛熱 + 導熱儲熱 + 人為熱）為基礎，透過量化幾何高寬比（H/W）、天空可視因子（SVF）、反照率與植被蒸散率解析熱島驅動機制；強調微氣候改善必須建立在客觀熱力學物理邊界之上（OKE1981, OKE2017, STEWART2012, KU-CLI-020）。

2. **對主流論點的批評**：遙測解析度可能將陰影與混合像元錯判成材料效應。 [KU-CLI-071]
## 關鍵證據與數字
- **夜間熱島強度與幾何關係（Oke 1981 經典定律）**：在晴朗無風的典型夜間，歐洲與北美城市的最高夜間冠層熱島強度（ΔT_max）與市中心街谷幾何高寬比（H/W）及天空可視因子（SVF）呈現高度對數相關（ΔT_max ≈ 7.45 + 1.98 ln(H/W)），最大熱島強度在特大城市可達 4–10 °C（OKE1981, KU-CLI-003, KU-CLI-022）。
- **綠地冷卻島效應與衰減距離（Bowler et al. 2010；Huang et al. 2020）**：系統性文獻計量顯示，城市公園平均可比周邊街區低 0.5–2.0 °C（Park Cool Island, PCI）；但冷卻效益隨距離迅速指數衰減，公園邊界以外 100–300 公尺處冷卻效果即衰減 50% 以上，無法對整個宏觀大都市產生均質降溫（BOWLER2010, HUANG2020, KU-CLI-049）。

## 經典案例
- **德國斯圖加特都市通風廊道與氣候地圖（Klimaatlas Stuttgart，1970 年代起）**：
- **希臘雅典市中心超高反照率與降溫街區改造（Flisvos & Western Athens，2010–2014 年）**：
  - 年代：2012–2014 年實施（SANTAMOURIS2014）
  - 策略：在超過 37,000 m² 的城市公共空間與屋頂全面塗裝高反射冷塗料（反照率由 0.2 提升至 0.7–0.8），配合透水冷鋪面與噴霧遮陽（KU-CLI-011, KU-CLI-035）。
  - 成效：實測夏季戶外最高地表溫度降低達 10–12 °C，局部空氣環境溫度降低 1.5–2.0 °C，空調峰值能耗下降約 15%（SANTAMOURIS2014, KU-CLI-032）。
  - 批評：強烈反射的淺色地表在盛夏正午造成嚴重的直射眩光，且被地面反射的短波輻射直接打在行人身上，在缺乏上方樹木遮蔭的情況下，行人生理等效溫度（PET）反而惡化（KU-CLI-036, KU-CLI-063）。

## 爭議與批評
規劃界最常見的爭議在於「地表衛星熱圖（LST）與人體真實熱舒適的脫節」（KU-CLI-071）。許多設計競賽與方案宣稱「透過種樹或冷屋頂使熱島降低 5 °C」，實質上只是引用了衛星熱紅外地表溫度，而行人高度的空氣溫度可能僅微幅下降不到 0.5 °C。此外，「反照率陷阱」亦引發廣泛爭議：只顧提升地面反射率，忽略了反射短波輻射會增加行人所承受的平均輻射溫度（Tmrt），導致地表雖涼但人體更熱（KU-CLI-036, KU-CLI-069, ARMSON2012）。

## 設計應用：在新開發區怎麼用、何時不適用
- **在新開發區怎麼用**：在新城總圖中落實 LCZ 分區管控，將高容積核心區（LCZ 1/2）與連續冷島基質（LCZ A 森林、LCZ G 水體）沿盛行夏季風向交替串聯，打造寬度不少於 50–100 公尺的貫通性綠色通風廊道（KU-CLI-010, KU-CLI-068）；規定建築屋頂必須達到高反射（反照率 ≥ 0.7）或藍綠屋頂覆蓋；但在行人地表層，不宜大面積裸露高反照率鋪裝，應強制採用「高樹冠遮蔭 + 實質透水鋪面」組合（KU-CLI-029, KU-CLI-069）。
- **何時不適用**：有季節性熱浪、強風或明顯街谷差異的場址，需以當地逐時氣象、街谷和暴露資料檢核；另一氣候區的單一指標不能直接作為設計門檻。

## 常見錯誤
1. **混淆地表溫度（LST）與空氣溫度（Air Temperature）**：直接把遙感 Landsat 熱紅外影像的數值當作行人感受到的熱島強度，宣稱自己設計降低了幾度氣溫（KU-CLI-004, KU-CLI-071）。
2. **忽視夜間散熱幾何約束**：將高層建築封閉圍合，形成低天空可視因子（SVF < 0.2）的深口袋，白天蓄積的熱量在夜間無法以長波輻射向上空逸散，造成夜間持續嚴重悶熱（KU-CLI-003, KU-CLI-018）。
3. **空調外機無序排熱直接吹向行人**：沿商業街地面層密集佈設未經導流的冷氣室外機，將高達 45–50 °C 的廢熱直接排放至步行通道，大幅抵銷周邊景觀綠化帶的降溫收益（KU-CLI-047）。

## 延伸閱讀
- OKE1981（Oke, 1981）- Canyon geometry and the nocturnal urban heat island: comparison of scale model and field observations.
- OKE2017（Oke et al., 2017）- Urban Climates. Cambridge University Press.
- ARNFIELD2003（Arnfield, 2003）- Two decades of urban climate research: a review of turbulence, exchanges of energy and water, and the urban heat island.
- STEWART2012（Stewart & Oke, 2012）- Local climate zones for urban temperature studies.
- NORTON2015（Norton et al., 2015）- Planning for cooler cities: A framework to prioritise green infrastructure to mitigate high temperatures in urban landscapes.
