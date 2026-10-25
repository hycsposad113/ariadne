# 都市形態字典：研究與起草稿

版本：1.0.0；研究查核日期：2026-09-28。此字典供設計者審閱和修改，並非法規、設計標準、基地分析或生成器驗收結果。

## 字典架構

資料分成三層：單棟平面型、街廓組合、街道與開放空間關係，共 31 條（15＋8＋8）。每一條都有英中名稱、平面尺寸、估算 GSI／FSI／樓層、16 項氛圍分數、適用條件、組合假設、未來生成器欄位、案例與來源 ID。來源 ID 在 config/morphology-dictionary/atmospheres.yaml 的 source_registry 對應完整作者、年份、標題、URL／DOI。

為避免增加 YAML 套件相依，.yaml 檔案使用 JSON 相容的 YAML 1.2 語法，可由一般 YAML 工具讀取，也可直接以 Python 標準函式庫載入。

本庫是獨立唯讀參照。專案產品需求目前只允許 perimeter-block 與 linear-block 兩個生成器家族；其他條目不代表生成器、COMPAS 操作或 P0 範圍已擴大。

## 研究依據和證據界線

- Spacematrix 提供以 GSI（覆蓋）、FSI（樓地板強度）、OSR（開放空間比）與 L（平均樓層指標）多面向描述密度的框架。GSI = 建築 footprint／同一參考面積；FSI = 總樓地板面積／同一參考面積；L = FSI／GSI；OSR = 非建築地面面積／總樓地板面積。參考分母、道路、地下層與樓層納入規則必須在每個實際案例另行指定。
- momepy 將形態量測分布於尺寸、形狀、空間分布、強度、連通性和多樣性等方面；MORPHINT 的 QGIS 目錄頁則列出 BCR、FAR、OSR 和建築形狀特徵。此字典只記錄方法脈絡，沒有安裝或呼叫軟體。
- Conzen 的 town-plan analysis 與 Muratori–Caniggia 的類型—歷史演變脈絡提醒設計者：建築、地塊、街廓、街道和時間應一起讀取，單棟平面不可脫離所在組織。
- Alexander 的 pattern language 支持以可組合模式整理設計討論；本字典的配對關係仍是可質疑、可修改的設計假設。
- Gehl 與 Whyte 的公共生活工作、Lynch 的城市意象，以及社會凝聚和自然監視研究都提醒：實際活力、可辨識性、歸屬與安全需有行為或使用者證據，不會從 footprint 自動得出。
- Portzamparc 的 Masséna 開放街廓案例說明，街廓可以由不同體量、開口和共同戶外空間構成；開口是否為公共路徑仍要有通行權和管理條件。
- Oke 與 SVF 文獻說明 H/W（或其倒數 D/H）、天空視域和街道方位是微氣候幾何指標；不能用單一比例替代日照時數、風場或熱舒適模擬。

研究只查核網頁書目、官方工具／案例頁和論文摘要，未讀完整論文，未下載資料集或大型檔案，也未安裝套件。來源的重點只作摘述；沒有長段直接引用。

## 氛圍面向與代理指標

0–1 分數為 EDITORIAL_ESTIMATE，以字典內幾何線索提供初步排序，不是量表、實測值、模擬結果或因果效果。引用來源支持面向、方法或類型脈絡，不為本字典分數背書。

| 面向 | 定義 | 可操作代理指標 | 所需資料與限制 |
|---|---|---|---|
| 圍合感（enclosure） | 由建築界面界定公共空間的程度。 | 街廓邊界連續率；公共空間周長中由建築臨邊的比例；平均 H/W 與其反向 D/H。 | 幾何或 3D 建築資料；連續邊界可形成視覺圍合線索，但不等於舒適或適居。 |
| 私密性／領域感（privacy） | 公共、半公共與私有空間的界線及可進入程度。 | 半私密入口比例；住戶入口與公共穿越路徑的分離率；庭院可進入邊界比例。 | 地面層入口與權屬／通行資料；形式只能顯示閾限安排；實際私密感取決於使用者、管理與文化。 |
| 通透性／可穿越性（permeability） | 可合法進入的路徑穿越街廓或連接公共空間的程度。 | 每公頃公共通道數；街廓邊界公共開口率；步行網路連通度／繞行係數。 | 有公共通行狀態的路網及開口；私有門洞不算公共連通；高度差、門禁與營運時段必須確認。 |
| 日照／天空開敞（sunlight） | 天空與太陽可視範圍的幾何潛力。 | SVF 近似；指定時段遮蔽角；天空可視率。 | 帶高度的建築／樹冠幾何；日期、方位與地點；幾何代理不等同日照時數、照度或太陽輻射模擬。 |
| 綠化／水岸接觸（green_blue） | 使用者接近可見或可進入的植栽、水體與生態空間的程度。 | 植栽投影面積率；樹冠遮蔭率；開放空間臨水邊長比例；可達綠藍空間距離。 | 植栽、水體、通行邊界圖層；空間形式本身不代表有植栽、可親水、土壤容量或生態品質。 |
| 遮蔭／微氣候調節潛力（microclimate_shelter） | 形態提供遮蔭、避風或冷卻空間的幾何可能性。 | H/W、D/H、SVF、樹冠遮蔭率、迎風投影面積密度；另以模擬或量測驗證。 | 3D 建築、植栽、街道朝向；氣象資料用於性能判讀；同一幾何可能同時遮蔭、蓄熱或妨礙通風；不可由單一指標判定舒適。 |
| 街道活力（street_vitality） | 地面層提供活動、停留與日常目的的條件；實際活力以觀察判定。 | 活躍臨街面比例；入口／100 m；營業或公共用途 frontage 比例；分時行人與停留計數。 | 地面層用途、入口幾何與分時行為觀察；開口只是活動機會的代理，不會自動帶來人流、營業或包容性。 |
| 工業尺度感（industrial_scale） | 大型跨距、較粗建築節奏或生產物流空間帶來的尺度特徵。 | 最大跨距 m；淨高 m；單一 footprint 面積 m²；柱／門洞節奏；物流面比例。 | 帶結構節奏的平面、立面與建築資料；尺度感是詮釋面向；保留文化價值需另作歷史與社群研究。 |
| 人本尺度（human_scale） | 從步行者視點可感知的界面、入口節奏與空間比例。 | 臨街入口數／100 m；立面分段長度；首層高／街寬；步行者視域遮擋。 | 立面、建築高度、出入口與街道斷面；幾何代理不能代表感官、行動能力或不同身高／年齡的實際經驗。 |
| 密度感（density_feel） | 局部建築量與開放空間的相對關係，不等於單一人口密度。 | 同一分母下的 GSI、FSI、OSR、L；高度分布及建築間距。 | 建築 footprint、樓層與明確的參考面積；GSI／FSI 受分母、樓層算法與納入建築規則影響；數字需伴隨範圍。 |
| 可辨識性／易認路（legibility） | 使用者辨認路徑、邊界、節點、區域與地標並形成心智圖像的程度。 | 路網選擇度／轉向複雜度；地標可視性；路徑與節點差異；需搭配訪談或認知地圖。 | 路網、地標與視域；最好加上使用者研究；網路中心性不是人的可辨識性本身；避免以單一中央性代替認知。 |
| 多樣性（diversity） | 土地使用、建築類型、高度、地塊與臨街活動的異質程度。 | 用途 Shannon entropy；建築型態／樓層分布熵；立面段長變異係數。 | 用途、建築類型、樓層與時間資料；高熵不必然代表有品質；多樣性需結合可達性、公平性與維護條件。 |
| 自然監視（natural_surveillance） | 有人使用的室內／地面空間對公共空間形成可視關係的程度。 | 公共路徑上可見的 occupied window / entrance frontage；視域覆蓋率；活躍用途分時覆蓋。 | 窗門、視域、用途與實際佔用資料；窗戶不保證有人看見；不可把視域代理當成治安結果。 |
| 安全感（perceived_safety） | 不同使用者在特定時間與情境中感到可安心使用公共空間的經驗。 | 分時使用者安全感問卷；照明與視域審核；障礙與衝突紀錄；犯罪資料只能作一項背景。 | 使用者調查、時間／照明與情境資料；本字典不從建築類型推定安全；所有幾何分數皆為初始討論線索。 |
| 社交性／共在潛力（sociability） | 空間容納偶遇、停留、交談、共同活動與集會的可能性。 | 可停留邊界長度；座位／100 m；公共空間可達性；分時共在／活動計數。 | 家具與可達性幾何、用途、現地觀察；形態只提供 affordance；社交結果受管理、文化、時間與人群差異影響。 |
| 歸屬感（belonging） | 人與地方之間被認同、熟悉、照料或具有參與權的感受。 | place attachment／sense of community 問卷；可辨認公共／半公共界面；共同管理和參與紀錄。 | 使用者研究、管理／參與歷史與空間邊界；不由庭院、門廊或圍牆自動產生；需由不同使用者參與確認。 |

### 指標操作備註

- 街道斷面可記錄 D/H，其中 D 是兩側建築面的淨距，H 是平均臨街建築高度；多數街谷文獻寫 H/W，兩者在 D=W 時互為倒數。請一併記錄街段、斷面位置、兩側高度算法、樹冠與方位。
- SVF 需要觀測點和天空半球幾何；近似算法須記錄 3D 輸入、樹木、射線取樣或其他估算方法。此版本沒有計算任何條目的 SVF。
- 地面層開口率、臨街面連續率、入口頻率須有立面／出入口資料。僅有建築 footprint 時應標成未知。
- 密度感可用同分母下的 GSI／FSI／OSR／L 作代理，但它們不是人口密度或人的主觀感受。
- 綠化須以植栽、樹冠或土壤資料量測；水岸接觸須確認權利、坡岸、可達性和使用條件。
- 自然監視、安全感、活力、歸屬與社交性需要時段觀察、用途、維護、照明及不同使用者研究。幾何只提出待檢查線索。

## 型態條目白話介紹

### 單棟平面型（其中點陣為建築群原型）

#### 梳狀／M形（Comb / M-shaped building）

主脊加上多個垂直翼片，形成一串半開放的縫隙空間。

#### 口字型／回字型周邊建築（Closed courtyard / perimeter building）

四周量體圍出內院，是典型的內向型組織；庭院是否私有需另外定義。

#### 開角庭院型／C形（Open-corner courtyard / C-shaped building）

保有內院但在一至兩處打開建築邊界，可引入視線或通路。

#### E形（E-shaped building）

有三個翼端的梳狀平面，提供較多端面，但也可能把空隙切成狹長帶。

#### H形（H-shaped building）

兩條平行翼以中段連接，能兼顧兩面採光與中間凹入空間。

#### 一字型板樓（I-shaped slab）

狹長、單一方向的板狀量體，適合以朝向、間距和端頭處理調整街道與採光關係。

#### 工業大跨／廠房大廳（Industrial shed / long-span hall）

以大跨距、深進深和較少柱列形成可調整的生產、物流或公共室內大空間。

案例參照：LocHal, Gare Maritime。它們只說明可比對的空間做法，不構成實測評分。

#### L形（L-shaped building）

兩翼相接的量體可在轉角形成較明確的空間邊界，同時保留一側開口。

#### 庭院住宅／Patio house（Patio house）

低層小 footprint 把小庭院收進單戶或小群組的日常生活範圍。

#### 台座＋塔樓（Podium plus tower）

較寬的低層台座承接街道活動，上方集中一座或數座高層量體。

#### 點陣塔樓群（Point-tower field）

這是同一地塊上多棟點式建築的集合型，不是單一建築 footprint。

#### 點狀塔樓（Point tower）

緊湊 footprint、較高樓層的單體；其空間效果高度依賴首層入口、基座與周圍開放空間。

#### 排屋單棟原型（Rowhouse unit）

以窄面寬、連續側牆的住宅原型，單棟常與鄰棟串接成街道列。

#### 階梯型／退台量體（Terraced / stepped building）

樓層逐段退縮，形成露台或階梯狀輪廓；屋頂可用性與私密性需要逐層定義。

案例參照：CopenHill。它們只說明可比對的空間做法，不構成實測評分。

#### U形（U-shaped building）

三面圍合、單側開口的平面，能把一部分戶外空間收進量體之間。

### 街廓組合

#### 混合街廓（Hybrid block）

在同一街廓混合板樓、點樓、退台或周邊量體，以不同高度與界面回應周邊。

案例參照：Fenix I。它們只說明可比對的空間做法，不構成實測評分。

#### 工業園區／廠房院落群（Industrial campus）

以大跨廠房、物流路徑、工作院落與保留建物組成園區型街廓。

案例參照：LocHal, Gare Maritime。它們只說明可比對的空間做法，不構成實測評分。

#### 開放街廓／îlot ouvert（Open block / îlot ouvert）

以分散體量與街廓開口形成內外連接，仍需定義哪些通路真正公共。

案例參照：Quartier Masséna。它們只說明可比對的空間做法，不構成實測評分。

#### 平行板樓排列（Parallel slab blocks）

多棟長形板樓以相近方向排列，樓間空地形成連續帶狀空間。

#### 周邊式街廓（Perimeter block）

建築沿街廓周邊排列，內部留出庭院；街牆連續度與院落公共性需分開設定。

#### 排屋列／細地塊街廓（Rowhouse strip）

以多棟窄面寬住宅沿街排列，通常形成清楚街道與背向服務空間。

#### 超級街廓（Superblock）

把多個一般街廓整合成大尺度區塊，內部路徑與周邊道路的連接需特別安排。

#### 塔樓在公園（Tower-in-the-park）

塔樓分散於大面積開放地景中，開放空間的公共性、入口與維護需被明確設計。

### 街道與開放空間關係

#### 中庭／共享院落（Courtyard / shared court）

由建築圍出的戶外空間，可私有、半公共或公共；必須在圖面上標清權利與出入口。

#### 有頂公共通道／室內街道（Covered public passage / indoor street）

由屋頂或既有大跨結構遮蔽的公共路徑，可連接大廳、廣場與不同用途。

案例參照：Gare Maritime, LocHal。它們只說明可比對的空間做法，不構成實測評分。

#### 線性公園／綠道（Linear park / greenway）

沿河道、鐵路、街廓或地景延展的開放空間，重點是連續性與橫向接入。

#### 廣場（Plaza）

較開敞、可集散或停留的公共空間；邊界、遮蔭和周邊用途決定實際可用方式。

#### 口袋公園（Pocket park）

嵌在街廓或轉角的小型綠地，可作短暫停留、休息或鄰里日常空間。

#### 共享街道／woon­erf（Shared street / woonerf）

低速、混合使用的街道空間讓行走、停留、騎行和必要車輛共享，但須靠交通管理落實。

#### 街谷／都市街道斷面（Urban street canyon）

兩側建築與中間街道形成街谷；以 H/W 或 D/H 描述幾何，但不能單獨推定微氣候。

#### 水岸步道／濱水公共帶（Waterfront promenade）

沿水體形成的公共步行界面，需先確認合法可達、堤岸、安全及淹水管理。

## 推薦查詢範例

config/morphology-dictionary/atmospheres.yaml 內有 12 組可修改的目標向量和分層組合：安靜有歸屬感的居住中庭、開放可穿越的創作園區、工業尺度的水岸公共空間、採光較佳的緊湊街道、綠色慢行網、兒童友善共享街道、細緻活躍混合街廓、公共空間辨識序列、保有私密的公共閾限、高密度地面生活、安靜水岸、工業遺產再利用。目標分數、條目和使用順序均為設計者可修改的組合草案。

## 案例索引

以下案例只作形態參照；來源年份與工程竣工年在 source_registry 中分別記錄。計畫中案例特別註明，且案例不支援本字典的 ESTIMATE 尺寸或分數。

| ID | 型態 | 代表案例（來源） |
|---|---|---|
| block.hybrid | 混合街廓 | Fenix I（[SRC_FENIX_I_2019](https://mei-arch.eu/en/projects/fenix-1/)） |
| block.industrial_campus | 工業園區／廠房院落群 | LocHal（[SRC_LOCHAL_2019](https://www.dutcharchitects.org/projects/lochal-tilburg)）；Gare Maritime（[SRC_GARE_MARITIME_2020](https://neutelings-riedijk.com/projects/gare-maritime/)） |
| block.open | 開放街廓／îlot ouvert | Quartier Masséna（[SRC_MASSENA_2019](https://journals.open.tudelft.nl/dash/article/view/5100)） |
| block.parallel_slabs | 平行板樓排列 | Alton West, Roehampton（[SRC_HISTORIC_ENGLAND_ALTON_EAST_2020](https://historicengland.org.uk/listing/the-list/list-entry/1468240)） |
| block.perimeter | 周邊式街廓 | Westerdokseiland, Amsterdam（[SRC_WESTERDOKSEILAND_2004](https://www.dvdp.nl/en/work/westerdokseiland-amsterdam)） |
| block.rowhouse_strip | 排屋列／細地塊街廓 | Wisselspoor Utrecht — Block C row houses（[SRC_WISSELSPOOR_ZECC_2022](https://www.zecc.nl/en/project/2034/Wisselspoor-Utrecht)） |
| block.superblock | 超級街廓 | Superilles a Sant Martí, Barcelona（[SRC_BARCELONA_SUPERILLES_UNDATED](https://ajuntament.barcelona.cat/santmarti/ca/lajuntament/estrategia-i-accio-de-govern/plans-i-projectes/superilles-sant-marti)） |
| block.towers_park | 塔樓在公園 | Alton East Estate, Roehampton（[SRC_HISTORIC_ENGLAND_ALTON_EAST_2020](https://historicengland.org.uk/listing/the-list/list-entry/1468240)） |
| building.comb | 梳狀／M形 | Maasstad Hospital, Rotterdam（[SRC_MAASSTAD_HOSPITAL_2011](https://wiegerinck.nl/en/project/maasstad-hospital/)） |
| building.courtyard_closed | 口字型／回字型周邊建築 | Beijing Siheyuan（[SRC_BEIJING_SIHEYUAN_2016](https://english.visitbeijing.com.cn/article/47ONhRtOVtL)） |
| building.courtyard_open_corner | 開角庭院型／C形 | Quartier Masséna, Paris — open-block edge（[SRC_MASSENA_2019](https://journals.open.tudelft.nl/dash/article/view/5100)） |
| building.e_plan | E形 | Xuefu Middle School, Shenzhen（[SRC_XUEFU_MIDDLE_SCHOOL_2024](https://www.archdaily.com/1020816/renovation-of-xuefu-middle-school-multi-architecture)） |
| building.h_plan | H形 | H-House, Surat（[SRC_H_HOUSE_ARCHDAILY_2020](https://www.archdaily.com/942200/h-house-cab-design-studio)） |
| building.i_slab | 一字型板樓 | Alton West, Roehampton（[SRC_HISTORIC_ENGLAND_ALTON_EAST_2020](https://historicengland.org.uk/listing/the-list/list-entry/1468240)） |
| building.industrial_hall | 工業大跨／廠房大廳 | LocHal（[SRC_LOCHAL_2019](https://www.dutcharchitects.org/projects/lochal-tilburg)）；Gare Maritime（[SRC_GARE_MARITIME_2020](https://neutelings-riedijk.com/projects/gare-maritime/)）；Agrotopia, Roeselare — rooftop greenhouse（[SRC_AGROTOPIA_2021](https://www.vanbergenkolpa.nl/)） |
| building.l_block | L形 | Hudson L-House, New York（[SRC_HUDSON_L_HOUSE_2025](https://www.theplan.it/award-2025-house/hudson-l-house-domestic-life-and-curatorial-practice-in-a-flexible-live-work-space-in-new-york-steven-holl-architects)） |
| building.patio | 庭院住宅／Patio house | Patio House, Burgos（[SRC_JEREZ_PATIO_HOUSE_2024](https://www.jerezarquitectos.com/en/project/patio-house/)） |
| building.podium_tower | 台座＋塔樓 | Marina City, Chicago（[SRC_MARINA_CITY_CAC_1967](https://www.architecture.org/online-resources/buildings-of-chicago/marina-city)） |
| building.point_array | 點陣塔樓群 | Alton East Estate, Roehampton（[SRC_HISTORIC_ENGLAND_ALTON_EAST_2020](https://historicengland.org.uk/listing/the-list/list-entry/1468240)） |
| building.point_tower | 點狀塔樓 | Cadnam Point, Alton East（[SRC_HISTORIC_ENGLAND_ALTON_EAST_2020](https://historicengland.org.uk/listing/the-list/list-entry/1468240)） |
| building.rowhouse | 排屋單棟原型 | Wisselspoor Utrecht — Block C row house（[SRC_WISSELSPOOR_ZECC_2022](https://www.zecc.nl/en/project/2034/Wisselspoor-Utrecht)） |
| building.terraced | 階梯型／退台量體 | CopenHill（[SRC_COPENHILL_2019](https://big.dk/projects/copenhill-2391)） |
| building.u_block | U形 | Tenjincho Place, Tokyo（[SRC_TENJINCHO_RIBA_2026](https://www.riba.org/explore/awards/international-awards/international-awards-for-excellence/2026/tenjincho-place/)） |
| space.courtyard | 中庭／共享院落 | Hofblok Hoogwerf, Amsterdam（[SRC_HOFBLOCK_HOOGWERF_2018](https://journals.open.tudelft.nl/dash/article/view/4634)） |
| space.covered_public_passage | 有頂公共通道／室內街道 | Gare Maritime（[SRC_GARE_MARITIME_2020](https://neutelings-riedijk.com/projects/gare-maritime/)）；LocHal（[SRC_LOCHAL_2019](https://www.dutcharchitects.org/projects/lochal-tilburg)） |
| space.linear_park | 線性公園／綠道 | Cheonggyecheon Stream, Seoul（[SRC_CHEONGGYCHEON_SEOUL_2005](https://english.seoul.go.kr/service/amusement/stream/1-cheonggyecheon/)） |
| space.plaza | 廣場 | Bryant Park, New York — west-end oval plaza（[SRC_BRYANT_PARK_HISTORY_2017](https://bryantpark.org/blog/history)） |
| space.pocket_park | 口袋公園 | Paley Park, New York（[SRC_PALEY_PARK_PPS_2024](https://www.pps.org/places/paley-park/)） |
| space.shared_street | 共享街道／woon­erf | Emmerhout, Emmen; Park Rozendaal, Leusden（[SRC_WOONERF_DASH_2018](https://journals.open.tudelft.nl/dash/article/view/4588)） |
| space.street_canyon | 街谷／都市街道斷面 | Alexandria historic city-center canyon study（[SRC_ALEXANDRIA_CANYON_2020](https://doi.org/10.1016/j.uclim.2020.100670)） |
| space.waterfront_promenade | 水岸步道／濱水公共帶 | Rijnhaven, Rotterdam — planned waterfront route（[SRC_RIJNHAVEN_ROTTERDAM_2026](https://www.rotterdam.nl/rijnhaven)） |

## 來源總表

表中論文僅檢視摘要／書目；官方案例頁只支持頁面所述的案例特徵。source_registry 另保留年份依據、搜尋詞、檢視範圍、查核時間與授權狀態。

| Source ID | 作者與年份 | 標題 | 已檢視範圍 |
|---|---|---|---|
| SRC_SPACEMATRIX_2023 | Meta Y. Berghauser Pont; Per Haupt (2023) | [Spacematrix: Space, Density and Urban Form - revised edition](https://doi.org/10.59490/mg.38) | 研究入口頁摘要與書目頁 |
| SRC_MOMEPY_2019 | Martin Fleischmann (2019) | [momepy: Urban Morphology Measuring Toolkit](https://doi.org/10.21105/joss.01807) | JOSS 網頁書目與摘要 |
| SRC_MORPHINT_2025 | Firman Afrianto; Maya Safira (2025) | [MORPHINT: Urban Morphology and Intensity Analyzer, QGIS Processing Plugin 1.0.0](https://plugins.qgis.org/plugins/morphint_morphology_intensity_analyzer/) | QGIS 外掛目錄網頁；檢視版本 1.0.0 與說明 |
| SRC_URBAN_MORPHOMETRICS_2015 | Jacob Dibble et al. (2015) | [Urban Morphometrics: Towards a Science of Urban Evolution](https://arxiv.org/abs/1506.04875) | arXiv 摘要頁 |
| SRC_CONZEN_1960 | M. R. G. Conzen (1960) | [Alnwick, Northumberland: A Study in Town-Plan Analysis](https://www.cca.qc.ca/en/search/details/library/publication/04458844) | Canadian Centre for Architecture 書目網頁 |
| SRC_MURATORI_CANIGGIA_2003 | Giancarlo Cataldi (2003) | [From Muratori to Caniggia: The Origins and Development of the Italian School of Design Typology](https://hdl.handle.net/2158/4135) | 佛羅倫斯大學典藏的文章摘要與書目 |
| SRC_ALEXANDER_1977 | Christopher Alexander; Sara Ishikawa; Murray Silverstein et al. (1977) | [A Pattern Language: Towns, Buildings, Construction](https://www.oup.com.au/books/general-interest/art-technology/9780195019193) | Oxford University Press 書籍介紹頁 |
| SRC_GEHL_2010 | Jan Gehl (2010) | [Cities for People](https://utpdistribution.com/9781597265737/cities-for-people/) | 書籍發行頁與 Gehl 官方方法頁 |
| SRC_LYNCH_1960 | Kevin Lynch (1960) | [The Image of the City](https://mitpress.mit.edu/9780262620017/the-image-of-the-city/) | MIT Press 書籍介紹頁 |
| SRC_EWING_CERVERO_2010 | Reid Ewing; Robert Cervero (2010) | [Travel and the Built Environment: A Meta-Analysis](https://doi.org/10.1080/01944361003766766) | 期刊摘要與書目 |
| SRC_OPEN_BLOCK_2020 | José Carpio-Pinedo; Guillermo Ramírez; Salas Montes; Patxi J. Lamiquiz (2020) | [New Urban Forms, Diversity, and Computational Design: Exploring the Open Block](https://doi.org/10.1061/(ASCE)UP.1943-5444.0000555) | ASCE 期刊摘要與書目 |
| SRC_MASSENA_2019 | Pierijn van der Putt (2019) | [Quartier Masséna Paris (FR): Christian de Portzamparc & Jean-Philippe Pargade, Gaëlle Péneau, Catherine Furet, Antoine Stinco](https://journals.open.tudelft.nl/dash/article/view/5100) | DASH 專題網頁介紹 |
| SRC_OKE_1988 | T. R. Oke (1988) | [Street Design and Urban Canopy Layer Climate](https://doi.org/10.1016/0378-7788(88)90026-6) | 期刊摘要 |
| SRC_SVF_2020 | Chunping Miao; Shuai Yu; Yuanman Hu; Huiwen Zhang; Xingyuan He; Wei Chen (2020) | [Review of Methods Used to Estimate the Sky View Factor in Urban Street Canyons](https://doi.org/10.1016/j.buildenv.2019.106497) | 期刊摘要與書目 |
| SRC_WHYTE_1980 | William H. Whyte (1980) | [The Social Life of Small Urban Spaces](https://www.pps.org/product/the-social-life-of-small-urban-spaces) | Project for Public Spaces 書籍與方法介紹頁 |
| SRC_SOCIAL_COHESION_2024 | J. Qi; S. Mazumdar; A. C. Vasconcelos (2024) | [Understanding the Relationship between Urban Public Space and Social Cohesion: A Systematic Review](https://doi.org/10.1007/s42413-024-00204-5) | White Rose Research Online 摘要與書目 |
| SRC_SAFETY_2024 | Nuria Vidal-Domper; Susana Herrero-Olarte; Gonzalo Hoyos-Bucheli; Marta Benages-Albert (2024) | [Do Jane Jacobs's Conditions Fostering the Presence of People Influence Crimes in Public Space? An Econometric Analysis in La Mariscal Neighborhood in Quito](https://doi.org/10.1016/j.cities.2024.104863) | Cities 期刊摘要與書目 |
| SRC_FENIX_I_2019 | Mei architects and planners (2019) | [Fenix I](https://mei-arch.eu/en/projects/fenix-1/) | 建築師官方案例頁 |
| SRC_LOCHAL_2019 | Civic Architects; Braaksma & Roos; Inside Outside (2019) | [LocHal, Tilburg](https://www.dutcharchitects.org/projects/lochal-tilburg) | 建築師組合案例頁 |
| SRC_GARE_MARITIME_2020 | Neutelings Riedijk Architects (2020) | [Gare Maritime](https://neutelings-riedijk.com/projects/gare-maritime/) | 建築師官方案例頁 |
| SRC_AGROTOPIA_2021 | van Bergen Kolpa Architects; META architectuurbureau (2021) | [Rooftop greenhouse Agrotopia](https://www.vanbergenkolpa.nl/) | 建築師官方案例頁 |
| SRC_COPENHILL_2019 | Bjarke Ingels Group (2019) | [CopenHill](https://big.dk/projects/copenhill-2391) | 建築師官方案例頁 |
| SRC_MAASSTAD_HOSPITAL_2011 | Wiegerinck Architecten (2011) | [Maasstad Hospital](https://wiegerinck.nl/en/project/maasstad-hospital/) | 建築師官方案例頁 |
| SRC_BEIJING_SIHEYUAN_2016 | Beijing Tourism Network (Visit Beijing) (2016) | [Quadrangle Courtyard in Beijing](https://english.visitbeijing.com.cn/article/47ONhRtOVtL) | 城市旅遊官方網頁；檢視索引頁摘要 |
| SRC_HISTORIC_ENGLAND_ALTON_EAST_2020 | Historic England; LCC Architects’ Department (2020) | [Landscaping to Alton East Estate](https://historicengland.org.uk/listing/the-list/list-entry/1468240) | Historic England 官方名錄網頁 |
| SRC_WESTERDOKSEILAND_2004 | de Vries van der Wiel (dvdp) (2004) | [Westerdokseiland, Amsterdam](https://www.dvdp.nl/en/work/westerdokseiland-amsterdam) | 建築與都市設計事務所案例頁 |
| SRC_WISSELSPOOR_ZECC_2022 | Zecc Architecten (2022) | [Wisselspoor Utrecht](https://www.zecc.nl/en/project/2034/Wisselspoor-Utrecht) | 建築師官方案例頁 |
| SRC_BARCELONA_SUPERILLES_UNDATED | Ajuntament de Barcelona, Sant Martí District (年份未標示) | [Superilles a Sant Martí](https://ajuntament.barcelona.cat/santmarti/ca/lajuntament/estrategia-i-accio-de-govern/plans-i-projectes/superilles-sant-marti) | 巴塞隆納市政府專案網頁；頁面未標出版年份 |
| SRC_HUDSON_L_HOUSE_2025 | Steven Holl Architects; The Plan (2025) | [Hudson L-House: domestic life and curatorial practice in a flexible live-work space in New York](https://www.theplan.it/award-2025-house/hudson-l-house-domestic-life-and-curatorial-practice-in-a-flexible-live-work-space-in-new-york-steven-holl-architects) | 建築專題網頁搜尋摘要（原站限制直接擷取） |
| SRC_TENJINCHO_RIBA_2026 | Hiroyuki Ito Architects (2026) | [Tenjincho Place](https://www.riba.org/explore/awards/international-awards/international-awards-for-excellence/2026/tenjincho-place/) | RIBA 官方案例頁 |
| SRC_XUEFU_MIDDLE_SCHOOL_2024 | Multi-Architecture; ArchDaily (2024) | [Renovation of Xuefu Middle School / Multi-Architecture](https://www.archdaily.com/1020816/renovation-of-xuefu-middle-school-multi-architecture) | 建築案例網頁 |
| SRC_H_HOUSE_ARCHDAILY_2020 | Co.lab Design Studio; ArchDaily (2020) | [H-House / Co.lab Design Studio](https://www.archdaily.com/942200/h-house-cab-design-studio) | 建築案例網頁 |
| SRC_JEREZ_PATIO_HOUSE_2024 | Enrique Jerez Abajo; Rebeca Piedra Dueñas; José M. Méndez Primo (2024) | [Patio House](https://www.jerezarquitectos.com/en/project/patio-house/) | 建築師官方案例頁 |
| SRC_MARINA_CITY_CAC_1967 | Bertrand Goldberg Associates; Chicago Architecture Center (1967) | [Marina City](https://www.architecture.org/online-resources/buildings-of-chicago/marina-city) | 建築中心案例百科網頁 |
| SRC_HOFBLOCK_HOOGWERF_2018 | Frederique van Andel (2018) | [Hofblok Hoogwerf Amsterdam: Diener & Diener](https://journals.open.tudelft.nl/dash/article/view/4634) | TU Delft DASH 案例摘要與書目 |
| SRC_CHEONGGYCHEON_SEOUL_2005 | Seoul Metropolitan Government (2005) | [Cheonggyecheon Stream Restoration Project](https://english.seoul.go.kr/service/amusement/stream/1-cheonggyecheon/) | 首爾市政府案例網頁 |
| SRC_PALEY_PARK_PPS_2024 | Project for Public Spaces (2024) | [Paley Park](https://www.pps.org/places/paley-park/) | 公共空間研究組織案例頁；頁面更新 2024 |
| SRC_BRYANT_PARK_HISTORY_2017 | Bryant Park Corporation (2017) | [Bryant Park History](https://bryantpark.org/blog/history) | 公園營運方歷史網頁 |
| SRC_WOONERF_DASH_2018 | Annenies Kraaij; Harald Mooij (2018) | [Plan Documentation: of the Woonerf](https://journals.open.tudelft.nl/dash/article/view/4588) | TU Delft DASH 論文摘要與書目 |
| SRC_ALEXANDRIA_CANYON_2020 | Nada Gaber; Ahmed Ibrahim; Ahmed B. Rashad; Essam Wahba; Zeyad El-Sayad; Ali F. Bakr (2020) | [Improving pedestrian micro-climate in urban canyons: City Center of Alexandria, Egypt](https://doi.org/10.1016/j.uclim.2020.100670) | ScienceDirect 論文摘要頁 |
| SRC_RIJNHAVEN_ROTTERDAM_2026 | Gemeente Rotterdam (2026) | [Rijnhaven](https://www.rotterdam.nl/rijnhaven) | 鹿特丹市政府專案網頁；含 2026 年 9 月更新 |

## 限制與待設計者修改

1. 所有尺寸、樓層、GSI、FSI、空間間距都標為 ESTIMATE，屬於 EDITORIAL_ENVELOPE_V1 草案；它們不是各型態的普遍「典型值」。重用前請 Jack 指定參考地塊、納入建築、樓層／基座算法、道路分母、當地規劃和現況資料。
2. 0–1 氛圍分數是 EDITORIAL_ESTIMATE；它們由類型特徵推論，只適合作為檢索排序。請設計者重設面向權重／分數，或以現地觀察、使用者研究和已核實模擬替代。
3. 日照、微氣候、遮蔭、風、綠化、自然監視、治安、街道活力、社群性及歸屬感都沒有在這個字典內計算或實測。
4. 各城市建築權利、公共通行、消防、無障礙、洪水、水岸管理、規劃限制及保存價值需另查正式資料；本檔不能替代規劃或工程審查。
5. 型態名稱並非互斥分類。不同街廓可同時包含多種單棟型；類型相似不等於性能相同。
6. 先例用於提出問題，不代表型態因果效果。Fenix I、LocHal、Gare Maritime、Agrotopia、CopenHill 均未被量測成此字典分數。
7. 這是字典草案與唯讀查詢工具，不會產生或接受設計方案；任何具後果的設計決定仍由設計者決定。
