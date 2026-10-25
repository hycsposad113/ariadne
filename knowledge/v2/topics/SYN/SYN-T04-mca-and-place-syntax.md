# MCA 與 Place Syntax（Multiple Centrality Assessment and Place Syntax）
領域：SYN｜相關細卡：KU-SYN-025, KU-SYN-026, KU-SYN-027, KU-SYN-028, KU-SYN-029, KU-SYN-030, KU-SYN-031, KU-SYN-032, KU-SYN-049, KU-SYN-050, KU-SYN-051, KU-SYN-052, KU-SYN-053, KU-SYN-054, KU-SYN-055, KU-SYN-056, KU-SYN-068, KU-SYN-069, KU-SYN-070, KU-SYN-075, KU-SYN-076

## 一句話
多中心性評估（MCA）透過原生路網圖（Primal Graph）融合度量距離與多重中心性測度，而場所語法（Place Syntax）則將組態分析與 GIS 實體土地機會（空間資本）深度疊合，共同彌補了傳統空間語法脫離物理尺度與忽視目的地吸引力的根本缺憾。

## 核心概念與定義
1. **多中心性評估與原生圖表示（MCA and Primal Graph）**：Sergio Porta、Paolo Crucitti 與 Vito Latora（2006）開創 MCA 架構（PORTA06, KU-SYN-025, KU-SYN-076）：
   - 原生圖（Primal Graph）：交叉口為節點（Nodes），街道線段為邊（Edges），路網保留真實公尺度量長度與地理幾何。此舉與空間語法的對偶圖（Dual Graph，街道為節點、交點為邊）形成鮮明對照。
   - 四大多中心測度：接近中心性（Closeness，度量距離可達性）、中介中心性（Betweenness，路徑穿行頻次）、直達中心性（Straightness，幾何直線效率比）與信息中心性（Information，網絡容錯韌性）（KU-SYN-025, KU-SYN-076）。
2. **場所語法與空間資本（Place Syntax Tool and Spatial Capital）**：Lars Marcus 與 Alexander Ståhle 等人（2010）於瑞典皇家理工學院（KTH）提出（MARCUS10, KU-SYN-026, KU-SYN-075）：
   - 核心哲學：人不會在空無一物的抽象街道上盲目遊蕩；人的流動是為了獲取特定的「場所機會（Attractions / Destinations）」。
   - 空間資本（Spatial Capital）：將街道的拓樸/度量可達性與地塊承載的實體資源（居住人口、就業崗位、零售店鋪、綠地公園面積）在網絡距離半徑內進行卷積計算，得出「網絡可及性加權的場所機會總量」（KU-SYN-026, KU-SYN-075）。
3. **度量步行半徑情境（Metric Walking Scales）**：分析普遍採用 400 m（5 分鐘微觀鄰里）、800 m（10 分鐘 TOD 生活圈）與 1,200 m（15 分鐘擴展服務圈）多尺度敏感度分析（KU-SYN-068, KU-SYN-069, KU-SYN-070）。

## 主要立場與學派
1. **複雜網絡科學與地理原生圖學派（Sergio Porta & Vito Latora 2006）**：主張以標準物理學統計力學與 Primal 網絡分析城市，直接相容於主流 GIS 向量架構；強調直達性與中介度對街道演化的客觀解釋力（PORTA06, KU-SYN-027）。
2. **空間資本與場所整合學派（Lars Marcus 2010；KTH 團隊）**：反對將形態與功能人為割裂；主張形態是容器、功能是內容，唯有將語法與 GIS 土地利用聯讀，才能評估真正的生活品質與空間正義（MARCUS10, KU-SYN-051）。
3. **古典對偶純組態學派（Bill Hillier 1984；UCL 傳統派）**：質疑過早將特定用途（如商店）混入網絡計算，認為用途是短暫易變的，而幾何組態才是決定城市百年演化的持久基因（HILLIER84, KU-SYN-029）。

4. **對主流論點的批評**：本次 API 未找到指定 Place Syntax 工具候選書目。 [KU-SYN-053]
## 關鍵證據與數字
- **Porta et al.（2006）六城市路網中心性對比**：對波隆那、艾哈邁達巴德等六個城市的 MCA 實證表明，Primal 中介中心性（Betweenness）與實體零售商業門面的空間分佈呈現高度皮爾森相關（r > 0.70–0.80），且直達中心性（Straightness）精準捕捉了市民心中地標大道的意象（PORTA06, KU-SYN-025）。
- **荷蘭新城與舊城空間資本對比（Ye & van Nes 2014）**：在荷蘭豪達（Gouda）舊城中，高整合度街道同時承載極高容積率與混合度（空間資本較完整契合）；而在阿爾梅勒（Almere）等現代新城，高整合道路兩側卻常為消極綠帶或停車場，出現嚴重的「空間資本錯位」（YE14, KU-SYN-049）。
- **波哥大非正規住區可及性不平等（KU-SYN-050 實證）**：結合公共交通網絡的場所語法分析顯示，波哥大邊緣貧困社區居民在 45 分鐘內可獲取的就業機會總量（空間資本），不足市中心富裕階層的 1/5，量化揭示了空間隔離的不公本質（KU-SYN-050）。

## 經典案例
- **義大利波隆那市中心路網 MCA 測試（Porta et al. 2006）**：
- **瑞典斯德哥爾摩皇家海港生態城場所語法規劃（Royal Seaport, 2010 年代）**：
  - 策略：Place Syntax 類方法把空間組態可達性與場所吸引點（如人口、商店）結合分析；權重與距離衰減需依研究設定。[KU-SYN-075]。

## 爭議與批評
MCA 與 Place Syntax 面臨的實務批評在於「資料飢渴與動態黑箱（Data Hunger & Static Blackbox）」：Place Syntax 高度依賴詳盡的建物用途資料庫、容積資料與門牌接口，在新開發區前期或資料匱乏的發展中國家，往往因缺乏精確圖層而難以施展（KU-SYN-053）。此外，空間資本模型本質上仍是靜態供給矩陣，無法反映尖峰擁塞、設施營業時間與不同階級的實質購買力差異（KU-SYN-050, KU-SYN-053）。

## 設計應用：在新開發區怎麼用、何時不適用
- **在新開發區怎麼用**：在新城總圖深化階段，導入 Place Syntax 分析：以 400 m 與 800 m 度量半徑，將新建住宅地塊與公服設施（社區醫院、幼兒園、生鮮超市）及綠地公園進行網絡卷積分析（KU-SYN-051, KU-SYN-068, KU-SYN-069）。量化檢驗各街塊的「公共服務空間資本指數」，精確診斷出服務死角地塊，並據此調整公共設施選址或增設微觀步行通道，避免傳統「劃圓圈配指標」的虛假覆蓋（KU-SYN-050, KU-SYN-052）。
- **何時不適用**：垂直多層路網、河岸橋接或步行資料不足的場址，需明確建模網路層級、距離方式和邊界；空間語法指標只能作為方案比較線索，不能單獨預測人流。

## 常見錯誤
1. **將空間資本當成純幾何遊戲**：只計算建築面積多寡，忽視了設施的實際營運品質與社會門檻（如高檔私人會所與公立托兒所在模型中被賦予同等空間資本）（KU-SYN-026, KU-SYN-053）。
2. **底圖路網拓樸未打斷的嚴重失真**：在導入 GIS 原生圖時，忘記在立交橋處打斷線段，或忘記在交叉口建立節點，導致計算出的中介中心性出現大尺度的荒謬捷徑（KU-SYN-028, KU-SYN-062）。

## 延伸閱讀
- PORTA06: Sergio Porta et al. (2006) - The Network Analysis of Urban Streets: A Primal Approach
- MARCUS10: Lars Marcus (2010) - Spatial Capital: A Proposal for an Extension of Space Syntax Using a GIS-Approach
- SEVTSUK10: Andres Sevtsuk (2010) - Path and Place: A Study of Urban Geometry and Retail Activity in Cambridge and Somerville, MA
- HILLIER84: Bill Hillier, Julienne Hanson (1984) - The Social Logic of Space
- YE14: Ye, van Nes (2014) - Quantitative Tools in Urban Morphology: Combining Space Syntax, Spacematrix and Mixed-Use Index
