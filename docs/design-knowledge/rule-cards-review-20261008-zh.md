# J8 設計知識審核表（候選 0.2.0）

生成時間：2026-10-08T04:32:29Z。執行者 OpenAI，指揮官 Claude；Founder 尚未審核或鎖版。

目前 93 張卡、60 筆文獻。新增 25 張；8 份技能只讀本機 knowledge。Loader 不呼叫網路、不啟用約束、不建立 HumanDecision。

書目 VERIFIED 只表示 API 的書名、作者及年份核對；ABSTRACT_REVIEW 表示另確認可得摘要。BIBLIOGRAPHIC_SCOPE_ONLY 的主張是保守概念摘要，未逐頁核驗。引用提供概念或反方視角，不證明試算尺寸、M4H 因果、施工或法規。

## 查證結果

文獻庫：{'VERIFIED': 58, 'AMBIGUOUS': 2}。最終查詢項目：{'VERIFIED': 58, 'AMBIGUOUS': 2, 'NOT_FOUND': 5}。NOT_FOUND 未建造假 DOI／ISBN，因此不放入 library。

Spacematrix 2010：第一作者與共同作者／版次未完整對上。Transforming Urban Waterfronts：2010／2011 及編者資訊不足。這兩筆保留 AMBIGUOUS，僅候選卡可讀，任何硬性卡均禁止引用。

年份更正：Marshall 2004、Ng 高密度專書 2009、Caniggia 2001、Le Corbusier 英譯 1929、CROW 採 2016 版；El-Geneidy 2013、Buehler／Dill 2015、Dovey／Pafka 2013 採已查得線上出版年，Yuen 新加坡研究 2006、Barthélemy 網路綜述使用 OpenAlex 2010 紀錄。原 id 保留以維持引用。

| 移除書目 id | 原因與保留方式 |
|---|---|
| FOUNDER | 專案決定不是公開學術書目，移至本機權限說明，不計來源門檻。 |
| PORTFOLIO | 公開 API 無相符作品集，移至本機設計意圖脈絡，不計研究來源。 |
| M4H | 原稿未指定精確政策文件，API 無法確認，不保留為正式政策來源。 |
| KRIER79 | 查得同作者相關文章但非 1979 Urban Space 書，移除卡片來源並以已查證形態文獻比較。 |
| YOSHIDA99 | 兩個 API 未查得相符標題作者年份，未納入。 |

Founder 與 portfolio 改存 `knowledge/local-context.json`；portfolio 的原設計意圖與數值保留，沒有將其冒充獨立學術來源。Krier 改以 Conzen 比較形態；M4H 卡只保留待取得政策的缺口，不宣稱土地使用合法。

## 來源偏誤檢查

J7：68 卡，portfolio 18／68（26.47%），Founder／作品集 37 次來源引用，所有 30 筆書目未查證。J8：portfolio 18／93（19.35%），Founder 在文獻來源及作者統計為 0。

作者採完整計數：每個作者每筆文獻或卡片引用各計一次；共同作者百分比總和可以超過 100%。不能用合著人數稀釋集中度。作品集脈絡不進入研究分母；58 筆 VERIFIED 文獻及 229 次 VERIFIED 卡片引用分開統計。

| 引用最多前 5 作者 | J7 引用數／占比 | J8 引用數／占比 |
|---|---|---|
| Stephen Marshall | 17／9.39% | 17／7.42% |
| Edward Ng | 13／7.18% | 15／6.55% |
| Bill Hillier | 10／5.52% | 14／6.11% |
| Susan S. Fainstein | 7／3.87% | 11／4.80% |
| Julienne Hanson | 10／5.52% | 11／4.80% |

J7 最高：[['Founder', 37]]（20.44%）；J8 引用最高 7.42%；文獻庫作者最高 5.17%。兩種分母都低於單一作者 10%，不代表地域或學派已完全平衡。

### 學派

| 分類 | 筆數 |
|---|---|
| 空間語法 | 2 |
| 韌性設計 | 1 |
| 街道案例比較 | 1 |
| 模式語言 | 1 |
| 土地使用相容性 | 1 |
| 空間網路科學 | 1 |
| 節點與場所 | 1 |
| 拉美可及性與公平 | 1 |
| 巴西形態學 | 1 |
| 都市水治理 | 1 |
| 自行車網路實證 | 1 |
| 永續規劃批評 | 1 |
| 義大利類型形態學 | 1 |
| 公共空間治理批評 | 1 |
| 建成環境交通實證 | 1 |
| 英國城鎮平面學 | 1 |
| 現代主義都市設計 | 1 |
| 自行車設計實務 | 1 |
| 韌性批評 | 1 |
| 建築再利用 | 1 |
| 組裝形態學 | 1 |
| 交通實證 | 1 |
| 交通與建成環境實證 | 1 |
| 都市分配正義 | 1 |
| 步行性批評 | 1 |
| 公共生活設計 | 1 |
| 可及性評估 | 1 |
| 開放建築 | 1 |
| 交通與健康 | 1 |
| 協作規劃 | 1 |
| 空間語法回應 | 1 |
| 港城轉型 | 1 |
| 非機動可及性 | 1 |
| 街道生活與多樣性 | 1 |
| 循環經濟批評 | 1 |
| 公共空間文化多樣性 | 1 |
| 都市認知 | 1 |
| 空間資本 | 1 |
| 街道形態 | 1 |
| 跨學派形態學 | 1 |
| 北歐交通實證 | 1 |
| 高密度通風評估 | 1 |
| 高密度環境設計 | 1 |
| 網路科學 MCA | 1 |
| 自行車比較政策 | 1 |
| 空間語法批評 | 1 |
| 非正式都市化 | 1 |
| 自行車安全 | 1 |
| 交通知識去殖民批評 | 1 |
| 行動資料都市研究 | 1 |
| 空間語法整合分析 | 1 |
| 新都市主義批評 | 1 |
| 荷蘭模式選擇實證 | 1 |
| 全球南方規劃批評 | 1 |
| 公共生活觀察 | 1 |
| 整合形態診斷 | 1 |
| 亞洲高層生活 | 1 |

### 地域（多地域每項各計一筆）

| 分類 | 筆數 |
|---|---|
| 跨地域 | 21 |
| 美國 | 12 |
| 荷蘭 | 8 |
| 英國 | 7 |
| 歐洲 | 4 |
| 全球南方 | 3 |
| 澳洲 | 2 |
| 丹麥 | 2 |
| 香港 | 2 |
| 奈及利亞 | 1 |
| 哥倫比亞 | 1 |
| 巴西 | 1 |
| 義大利 | 1 |
| 加拿大 | 1 |
| 瑞典 | 1 |
| 北歐 | 1 |
| 亞洲 | 1 |
| 德國 | 1 |
| 非洲 | 1 |
| 新加坡 | 1 |

### 年代

| 分類 | 筆數 |
|---|---|
| 2010s | 24 |
| 2000s | 17 |
| 1990s | 9 |
| 1960s | 3 |
| 1980s | 2 |
| 1970s | 1 |
| 2020s | 1 |
| 1920s | 1 |

### 文獻主張強度

| 分類 | 筆數 |
|---|---|
| THEORETICAL | 34 |
| MIXED | 18 |
| NORMATIVE_PRACTICE | 5 |
| STRONG_EMPIRICAL | 1 |

### 規則卡強度

| 分類 | 筆數 |
|---|---|
| THEORETICAL | 38 |
| NORMATIVE_PRACTICE | 32 |
| MIXED | 16 |
| ASSUMED | 6 |
| STRONG_EMPIRICAL | 1 |

### 較廣研究取向分組（審核用）

為避免細小學派標籤掩蓋集中度，再把原 library 標籤作較廣分組；這是公開的審核分析分類，不改 runtime domain 或預設偏好。每筆只計一次，成員清單見 statistics.json。

| 研究取向 | VERIFIED 文獻數 | 占 58 筆比例 |
|---|---|---|
| 交通、可及性與自行車 | 14 | 24.14% |
| 公共生活、認知與管理批評 | 9 | 15.52% |
| 形態、類型與密度 | 8 | 13.79% |
| 高密度環境、住宅生活與韌性 | 6 | 10.34% |
| 規劃、公平與知識批評 | 6 | 10.34% |
| 空間語法、延伸與內部批評 | 6 | 10.34% |
| 空間網路科學與行動資料 | 3 | 5.17% |
| 開放建築、再利用與循環 | 3 | 5.17% |
| 土地使用介面與空間公平 | 2 | 3.45% |
| 港城與水岸轉型 | 1 | 1.72% |

最大的研究取向仍值得 Founder 審查；這不是已證明知識無偏誤。批評與替代方法需要在方案說明中實際並列，不能只以來源數量宣稱平衡。

### J7／J8 學派與地域前後對照

J7 使用原稿的一筆來源一票分類，J8 使用 VERIFIED 文獻分類；地域允許多標籤。分類改善與來源增加不表示兩分母直接等價。

| J7 學派 | 來源數 |
|---|---|
| 空間語法 | 2 |
| 交通實證 | 1 |
| 街道形態 | 1 |
| 街道比較設計 | 1 |
| 專案決策 | 1 |
| 現代主義 | 1 |
| 亞洲高密度環境設計 | 1 |
| 場所認知 | 1 |
| 公共生活實地觀察 | 1 |
| 荷蘭密度形態 | 1 |
| 建築再利用 | 1 |
| 開放建築／使用者控製 | 1 |
| Founder 設計作品集 | 1 |
| 傳統都市空間類型 | 1 |
| 都市水治理 | 1 |
| 景觀韌性 | 1 |
| 街道生活／多樣性 | 1 |
| 英國歷史形態學 | 1 |
| 形態學綜述 | 1 |
| 義大利類型形態學 | 1 |
| 自行車比較政策 | 1 |
| 地方政策 | 1 |
| 分配正義 | 1 |
| 空間語法批評 | 1 |
| 荷蘭交通實務 | 1 |
| 網路科學 MCA | 1 |
| 循環經濟批評綜述 | 1 |
| 模式語言 | 1 |
| 公共生活 | 1 |

| J7 作者前 5 | 引用數／占比 |
|---|---|
| Founder | 37／20.44% |
| Stephen Marshall | 17／9.39% |
| Edward Ng | 13／7.18% |
| Bill Hillier | 10／5.52% |
| Julienne Hanson | 10／5.52% |

J7 年代分布：{'2010s': 7, '2000s': 6, '1990s': 4, '2020s': 1, 'UNKNOWN': 5, '1960s': 3, '1980s': 2, '1970s': 2}；J8 年代分布：{'2010s': 24, '1990s': 9, '1970s': 1, '2020s': 1, '2000s': 17, '1960s': 3, '1920s': 1, '1980s': 2}。


| J7 地域 | 來源數 |
|---|---|
| 美國 | 4 |
| 鹿特丹 M4H | 3 |
| 歐洲 | 3 |
| 英國 | 3 |
| 英國／跨案例 | 2 |
| 跨城市 | 2 |
| 荷蘭／跨案例 | 2 |
| 香港／亞洲 | 1 |
| 澳洲／跨案例 | 1 |
| 跨案例 | 1 |
| 跨學派 | 1 |
| 義大利 | 1 |
| 荷蘭／丹麥／德國 | 1 |
| 美國／歐洲 | 1 |
| 荷蘭 | 1 |
| 跨地域 | 1 |
| 美國／跨案例 | 1 |
| 丹麥／跨案例 | 1 |

J7 卡片強度：{'NORMATIVE_PRACTICE': 33, 'THEORETICAL': 28, 'ASSUMED': 7}；J8 卡片強度：{'THEORETICAL': 38, 'ASSUMED': 6, 'MIXED': 16, 'NORMATIVE_PRACTICE': 32, 'STRONG_EMPIRICAL': 1}。J7 空參數 54／68，J8 0／93。

仍不足：西歐／北美經典仍是形態與公共生活的較多來源；亞洲增加香港／新加坡，南方增加巴西／哥倫比亞／奈及利亞及非正式都市化，但沒有地方居民訪談，也缺東亞更多城市及非洲不同工業類型的實證。M4H 現行政策、官方用途與手冊條文不能從書目 API 補齊。每領域已列替代文獻，仍需指揮官審查其與卡片的實際支持關係。

## 覆蓋矩陣摘要

| 階段 | context_response | land_use | mobility | morphology | policy | portfolio | public_space | space_syntax |
|---|---|---|---|---|---|---|---|---|
| S1 | N/A（見理由） | 2 | N/A（見理由） | N/A（見理由） | 4 | N/A（見理由） | N/A（見理由） | N/A（見理由） |
| S2 | 7 | 10 | 15 | 3 | 5 | 18 | 1 | 13 |
| S3 | 7 | 9 | 15 | 16 | 4 | 18 | 8 | 13 |
| S4 | N/A（見理由） | N/A（見理由） | 12 | 13 | N/A（見理由） | 18 | 6 | 1 |
| S5 | N/A（見理由） | N/A（見理由） | 1 | N/A（見理由） | N/A（見理由） | N/A（見理由） | N/A（見理由） | 14 |
| S6 | 7 | 7 | 3 | 16 | 1 | 18 | 8 | 11 |
| S7 | 7 | 10 | 15 | 16 | 5 | 18 | 8 | 14 |
| S8 | 7 | 8 | 4 | 3 | 5 | 18 | 8 | 3 |

矩陣每格包含 card_ids、relevant 及空格理由。相關格有卡不代表工具已實作；所有 check 仍是 SPECIFICATION_ONLY。S1 不做設計診斷，S5 不重新決定量體或政策。

## Founder 待確認的 ASSUMED 值

共 90 個 ASSUMED_COMMANDER 參數；空參數卡 0 張。這些值只是候選試算，不曾寫入正式約束。40 m、20 m、Syntax 半徑等既有專案值另標 FOUNDER，作用仍由已接受狀態解析。

| 卡 | 參數 | 值／範圍 | 單位 | 理由 |
|---|---|---|---|---|
| CTX-001 | dakpark_level_difference | 10 | m | 派工轉述 p21，非已量測高程。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| CTX-002 | cutback_depth_trial | [2, 5] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| CTX-003 | waterfront_height_variants | 3 | variants | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| CTX-004 | landmark_relative_height_trial | 3.5 | m | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| CTX-005 | context_study_buffer_trial | 200 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| CTX-006 | failure_scenarios_min | 3 | scenarios | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| CTX-007 | environment_context_variants_min | 3 | variants | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| LAN-001 | manufacturing_share | [30, 40] | % | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| LAN-001 | office_share | [10, 20] | % | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| LAN-001 | housing_share | [30, 50] | % | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| LAN-001 | facilities_share | 10 | % | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| LAN-002 | unknown_use_review_threshold | 10 | % area | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| LAN-003 | destination_context_radius_trial | 800 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| LAN-004 | temporal_bins_trial | 4 | bins/day | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| LAN-005 | interface_buffer_trial | 200 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| LAN-006 | buffer_depth_trial | [10, 30] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| LAN-007 | production_share_trial | [30, 40] | % GFA | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| LAN-008 | activity_observation_bins_trial | 4 | bins/day | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| LAN-009 | accessibility_groups_min | 3 | groups | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| LAN-010 | unknown_use_review_trial | 10 | % area | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-001 | corridor_gap_trial | 2 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-002 | shared_speed_trial | 15 | km/h | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-003 | parking_to_entry_max | 15 | m | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| MOB-004 | service_speed_trial | 15 | km/h | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-005 | service_loop_detour_trial | 1.5 | ratio | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-007 | small_medium_area_max | 10 | ha | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| MOB-007 | office_share_review_min | 40 | % GFA | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| MOB-009 | entry_snap_tolerance_trial | 1 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-010 | parking_variants_to_compare | 2 | variants | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-011 | delivery_window_trial | 2 | h/day | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-012 | station_catchment_trial | [400, 800] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-013 | walk_distance_sensitivity | [400, 1200] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-014 | city_context_radius_trial | 10000 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOB-015 | mode_scenarios_min | 2 | scenarios | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-001 | fsi_sensitivity_range | [1, 4] | m²/m² | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-002 | block_dimension_candidate | [40, 120] | m | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| MOR-003 | perimeter_depth_trial | [10, 20] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-004 | courtyard_width_trial | [15, 30] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-005 | slab_spacing_trial | [15, 30] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-006 | point_footprint_trial | [200, 500] | m² | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-007 | row_plot_width_trial | [5, 9] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-008 | podium_height_trial | [3.5, 7] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-009 | internal_insertion_clearance_trial | 1 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-010 | height_variants_to_compare | 3 | variants | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-014 | historical_layers_min | 2 | layers | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-015 | morphology_variants_min | 3 | variants | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| MOR-016 | height_alternatives_min | 3 | variants | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POL-001 | policy_versions_to_compare | 2 | versions | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POL-002 | policy_review_versions_trial | 2 | versions | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POL-003 | tradeoff_dimensions_min | 3 | dimensions | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POL-004 | stakeholder_groups_trial | 4 | groups | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POL-005 | conversion_phases_trial | 3 | phases | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-001 | local_production_share_trial | 30 | % GFA | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-002 | rainwater_retention_trial | 20 | mm | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-003 | habitat_gap_trial | 20 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-004 | use_categories_trial | 4 | categories | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-005 | green_corridor_width_trial | [10, 20] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-006 | service_gate_count_trial | 2 | gates | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-007 | stair_rest_interval_trial | 1.5 | m vertical | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-008 | ground_floor_porosity_trial | 40 | % frontage | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-009 | wind_variants_to_compare | 3 | variants | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-010 | rain_event_depth_trial | [10, 30] | mm | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-011 | bridge_clear_width_trial | 4 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-012 | active_plinth_share_trial | 60 | % frontage | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-013 | insertion_footprint_share_trial | 50 | % retained footprint | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-014 | added_floors_trial | [1, 2] | floors | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-015 | adaptable_bay_width_trial | [5, 8] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-016 | social_node_spacing_trial | [30, 60] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-017 | slope_gradient_trial | 5 | % | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| POR-018 | indicative_floor_height | 3.5 | m | 派工提供 p24；非法定或各用途通用層高。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| PUB-001 | square_area_trial | [400, 1600] | m² | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| PUB-002 | clear_passage_width_trial | 3 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| PUB-003 | noncommercial_active_share_trial | 30 | % active frontage | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| PUB-004 | activity_pocket_spacing_trial | [30, 60] | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| PUB-005 | public_access_hours_trial | 24 | h/day | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| PUB-006 | dead_end_length_trial | 40 | m | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| PUB-007 | public_hours_comparison_trial | [12, 24] | h/day | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| PUB-008 | social_observation_period_trial | 7 | days | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| SYN-001 | observation_interval | 30 | min | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| SYN-002 | active_frontage_trial | 60 | % facade length | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| SYN-003 | node_options_min | 3 | options | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| SYN-004 | through_route_detour_trial | 1.3 | ratio | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| SYN-005 | quiet_use_share_trial | 70 | % GFA | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| SYN-006 | entry_candidates_per_side | 2 | entries | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| SYN-010 | modes_to_compare | 3 | modes | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| SYN-011 | high_percentile_min | 80 | percentile | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| SYN-011 | medium_percentile_min | 40 | percentile | 可調試算值，沒有普適證據；需 Founder 確認並做敏感性比較。 原數字保留；來源是作品集轉述或專案假設，未經公開書目佐證，不視為研究或實測。 |
| SYN-012 | sensitivity_radius_delta | 20 | % | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| SYN-013 | representations_to_compare_min | 2 | models | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |
| SYN-014 | network_cost_models_min | 2 | models | 指揮官提出的敏感性試算值，文獻未提供此數值；須 Founder 確認、地方資料及確定性驗證，未生效。 |

## 每張卡的白話審核

需判斷：規則是否合適、不同回應的代價是否完整、數值是否值得試算。證據不是投票表；不要因來源多而偏好某一方案。

### CTX-001｜Dakpark 10 m 高差待量測

**規則**：以作品集提供的 10 m 高差作 context 假說，先核對地面與公園垂直基準，再比較開放樓梯、坡道與分層入口；不得把樓梯當全員可達。
**理由**：隔著堤或高差的居民需要實際入口，不只是視覺連接。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：dakpark_level_difference＝10 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- LYNCH60／C1：The Image of the City；Kevin Lynch；1960；9780262120043；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 可見樓梯加平緩替代路；代價：替代路長且需要無障礙驗證。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 分層公共平台銜接；代價：結構、權利與維護成本。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：地形意象、日照與公共可達可能互相衝突；作品集是候選策略，資料缺口不能填成效果。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 亞洲高密度與英美認知研究可供比較，M4H 的 Dakpark 高程、產權與水岸風險需要地方證據。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### CTX-002｜日照切削是實驗

**規則**：鄰公園或內院量體可提議對角切削與退台，先固定基準案與日照日期／時間，再做確定性陰影比較，未算不說改善。
**理由**：需要光的庭院、住房與公園可能在不同時段使用。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：cutback_depth_trial＝[2, 5] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOVEY14／C1：The urban density assemblage: Modelling multiple measures；Kim Dovey、Elek Pafka；2013；10.1057/udi.2013.13；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。獨立的密度比較或建築適應觀點，用來比較量體及使用條件；不支持本卡的高度、層高或日照試算數字。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 對角切削；代價：GFA 損失、結構複雜。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 錯列或整體降低；代價：佔地或密度改變。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：地形意象、日照與公共可達可能互相衝突；作品集是候選策略，資料缺口不能填成效果。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 亞洲高密度與英美認知研究可供比較，M4H 的 Dakpark 高程、產權與水岸風險需要地方證據。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### CTX-003｜水岸高度與公共面

**規則**：水岸界面保留已接受退縮與連續公共路徑；比較低層開放面與後退較高量體，不編造退縮數值或洪水標高。
**理由**：水岸散步與港區作業需要明確分界和可用連結。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：waterfront_height_variants＝3 variants（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- AHERN11／C1：From fail-safe to safe-to-fail: Sustainability and resilience in the new urban world；Jack Ahern；2011；https://doi.org/10.1016/j.landurbplan.2011.02.021；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 低層水岸加後排量體；代價：後排仍可能遮陰。
- 可淹沒景觀前場；代價：污染、潮汐與安全未驗。
**爭議與地域限制**：地形意象、日照與公共可達可能互相衝突；作品集是候選策略，資料缺口不能填成效果。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 亞洲高密度與英美認知研究可供比較，M4H 的 Dakpark 高程、產權與水岸風險需要地方證據。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### CTX-004｜地標靠相對高度與視線

**規則**：入口地標可由鄰棟高度差、轉角與公共入口形成；試算相對差 3.5 m，同時比較非高度地標，不要求每節點變高。
**理由**：找路可以靠可見入口和活動，不只靠塔。
**層級／強度／權限**：COMMON_SENSE_ASSUMED／ASSUMED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：landmark_relative_height_trial＝3.5 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- LYNCH60／C1：The Image of the City；Kevin Lynch；1960；9780262120043；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- WHYTE80／C1：The social life of small urban spaces；William H. Whyte；1980；https://openalex.org/W1538435250；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 較鄰棟高一層的入口量體；代價：陰影與視覺支配。
- 低量體前的活動廣場；代價：辨識依營運與人群。
**爭議與地域限制**：地形意象、日照與公共可達可能互相衝突；作品集是候選策略，資料缺口不能填成效果。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 亞洲高密度與英美認知研究可供比較，M4H 的 Dakpark 高程、產權與水岸風險需要地方證據。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### CTX-005｜context 先於型態偏好

**規則**：S2 列保留建物、外部入口、產業、Dakpark 與水岸；S6 每個高度／空地決定至少連到一個 context observation 或明示資料缺口。
**理由**：設計者要看到這塊地方的理由，不是搬來通用漂亮形式。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：context_study_buffer_trial＝200 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- MOUDON97／C1：Urban Morphology as an emerging interdisciplinary field；Anne Vernez Moudon；1997；10.51347/jum.v1i1.4047；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- LYNCH60／C1：The Image of the City；Kevin Lynch；1960；9780262120043；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- BRAZIL14／C1：The study of urban form in Brazil；Staël de Alvarenga Pereira Costa、Maria Cristina Villefort Teixeira；2014；10.51347/jum.v18i2.3998；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 從歷史地塊延續配置；代價：可能維持舊隔離。
- 從新入口與公共意象重組；代價：可能減弱地方結構。
**爭議與地域限制**：地形意象、日照與公共可達可能互相衝突；作品集是候選策略，資料缺口不能填成效果。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 亞洲高密度與英美認知研究可供比較，M4H 的 Dakpark 高程、產權與水岸風險需要地方證據。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### CTX-006｜韌性需說明誰承受失效

**規則**：列不同失效情境、暴露群體與恢復路徑，不用韌性一詞代替環境效能計算。
**理由**：容許失效的設計與韌性政治批評需並讀。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：failure_scenarios_min＝3 scenarios（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- AHERN11／C1：From fail-safe to safe-to-fail: Sustainability and resilience in the new urban world；Jack Ahern；2011；https://doi.org/10.1016/j.landurbplan.2011.02.021；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DAVOUDI12／C1：Resilience: A Bridging Concept or a Dead End?“Reframing” Resilience: Challenges for Planning Theory and PracticeInteracting Traps: Resilience Assessment of a Pasture Management System in Northern AfghanistanUrban Resilience: What Does it Mean in Planning Practice?Resilience as a Useful Concept for Climate Change Adaptation?The Politics of Resilience for Planning: A Cautionary Note；Simin Davoudi、Keith Shaw、L. Jamila Haider、Allyson E. Quinlan、Garry D. Peterson、Cathy Wilkinson、Hartmut Fünfgeld、Darryn McEvoy、Libby Porter；2012；10.1080/14649357.2012.677124；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CAMPBELL96／C1：Green Cities, Growing Cities, Just Cities?: Urban Planning and the Contradictions of Sustainable Development；Scott Campbell；1996；10.1080/01944369608975696；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 分散保水及備援路徑；代價：降低集中失效，運維較複雜。
- 集中設施並保留替代路徑；代價：便於維護，仍需控制單點失效。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### CTX-007｜生活與環境方法不可互代

**規則**：分開列高度、生活可接受性、通風與日照的量測或研究範圍；本地缺資料就列 UNKNOWN。
**理由**：香港環境方法與新加坡住宅研究回應不同問題。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：environment_context_variants_min＝3 variants（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- NG09／C1：Policies and technical guidelines for urban planning of high-density cities – air ventilation assessment (AVA) of Hong Kong；Edward Ng；2009；10.1016/j.buildenv.2008.06.013；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- YUE05／C1：High-rise Living in Singapore Public Housing；Belinda Yuen、Anthony Yeh、Stephen John Appold、George Earl、John Ting、Lanny Kurnianingrum Kwee；2006；10.1080/00420980500533133；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CARMONA10／C1：Contemporary Public Space: Critique and Classification, Part One: Critique；Matthew Carmona；2010；https://doi.org/10.1080/13574800903435651；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 切削量體改善環境假說；代價：可能損失樓地板量，須正式模擬。
- 調整開放面與活動分布；代價：保留量體，但需檢查使用及微氣候。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### LAN-001｜Keilekwartier 指示比例

**規則**：把製造 30–40%、辦公 10–20%、住宅 30–50%、設施 10% 作 portfolio 候選；先定義同一分母並選總和 100% 的組合，不將範圍全部上限相加。
**理由**：港區混合要兼顧生產、居住與日常服務。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：manufacturing_share＝[30, 40] %（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）；office_share＝[10, 20] %（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）；housing_share＝[30, 50] %（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）；facilities_share＝10 %（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- JACOBS61／C1：The Death and Life of Great American Cities；Jane Jacobs；1961；0679644334；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 製造優先混合；代價：住宅噪音隔離、租金壓力。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 公共設施優先的混合組合；代價：資金與營運需要評估。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：這是作品集指示，非已查證政府管制；用途分類與 GFA／土地面積分母待確認。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 鹿特丹作品集直接相關，但美國多樣性與公平研究不能證明當地比例。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### LAN-002｜現況與規劃分開

**規則**：現況用途、政府規劃與作品集目標分三欄；每欄保留時間、來源與缺口，不以願景覆寫已存在工業活動。
**理由**：不同使用者與既有租戶的生活不能被規劃圖抹去。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：unknown_use_review_threshold＝10 % area（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- MOUDON97／C1：Urban Morphology as an emerging interdisciplinary field；Anne Vernez Moudon；1997；10.51347/jum.v1i1.4047；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- ROY05／C1：Urban Informality: Toward an Epistemology of Planning；Ananya Roy；2005；https://doi.org/10.1080/01944360508976689；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 保留現況產業再增用途；代價：轉型速度較慢。
- 分期混合並公開受影響群體；代價：需要協商與持續追蹤。
**爭議與地域限制**：現況分類與規劃分類常不一致；沒有法律版本與土地權利資料不能推定可建。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 跨地域方法供分類與公平提問，M4H 用途需 local snapshot。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### LAN-003｜周邊用途與吸引點分開

**規則**：分別建立 BAG 用途面積、OSM 設施點及站點清單；列分類、日期、缺漏與各側路網距離，不能以點數當人流。
**理由**：可及性同時依賴目的地與路網，出行和用途多樣性的關聯不能取代地方活動資料。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：destination_context_radius_trial＝800 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- IACONO10／C1：Measuring non-motorized accessibility: issues, alternatives, and execution；Michael Iacono、Kevin J. Krizek、Ahmed El-Geneidy；2010；10.1016/j.jtrangeo.2009.02.002；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CERVERO97／C1：Travel demand and the 3Ds: Density, diversity, and design；Robert Cervero、Kara Maria Kockelman；1997；https://doi.org/10.1016/s1361-9209(97)00009-6；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- GEURS04／C1：Accessibility evaluation of land-use and transport strategies: review and research directions；Karst Geurs、Bert van Wee；2004；10.1016/j.jtrangeo.2003.10.005；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 按用途聚合吸引點；代價：分類清楚，但無法反映營業時段。
- 按實際活動時段建立吸引清單；代價：較貼近日常，資料需求較高。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### LAN-004｜人流路徑是假說

**規則**：以站點與吸引點之間的合法路徑疊加 Syntax 作相對潛勢，另列用途、時段與門禁；沒有校準不得輸出人數。
**理由**：路網關聯與聚合移動資料都有樣本及尺度限制。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：temporal_bins_trial＝4 bins/day（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HILLIER93／C1：Natural movement: or, configuration and attraction in urban pedestrian movement；Bill Hillier、Alan Penn、Julienne Hanson、T Grajewski、Jianming Xu；1993；10.1068/b200029；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- SHARMIN17／C1：Meta-analysis of the relationships between space syntax measures and pedestrian movement；Samia Sharmin、Md. Kamruzzaman；2017；https://doi.org/10.1080/01441647.2017.1365101；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- SEVTSUK10／C1：Does Urban Mobility Have a Daily Routine? Learning from the Aggregate Data of Mobile Networks；Andres Sevtsuk、Carlo Ratti；2010；10.1080/10630731003597322；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 以最短路徑提出入口假說；代價：易重現，但忽略行為選路。
- 以多路徑與時段對比；代價：保留替代解釋，需要校準資料。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### LAN-005｜各方位用途與介面

**規則**：以基地 centroid 方位分段、外側 buffer 用途分母和入口位置生成各側摘要；說明座標北向及不規則基地分段限制。
**理由**：混合用途、路網及密度需聯讀；總用途比例無法代表每一側面對的情境。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：interface_buffer_trial＝200 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- YE14／C1：Quantitative tools in urban morphology: combining space syntax, spacematrix and mixed-use index in a GIS framework；Yu Ye、Akkelies van Nes；2014；https://doi.org/10.51347/jum.v18i2.3997；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- GEURS04／C1：Accessibility evaluation of land-use and transport strategies: review and research directions；Karst Geurs、Bert van Wee；2004；10.1016/j.jtrangeo.2003.10.005；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOVEY14／C1：The urban density assemblage: Modelling multiple measures；Kim Dovey、Elek Pafka；2013；10.1057/udi.2013.13；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 回應住宅側的入口與安靜活動；代價：改善鄰近使用者介面，可能限制夜間產業活動。
- 保留工業側的服務物流介面；代價：保障生產，但須避免壓縮住宅與行人的安全。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### LAN-006｜住宅工業介面的暴露

**規則**：分開記錄氣味、噪音、貨運路徑及住宅入口；緩衝深度只作試算，正式距離必須來自適用政策及量測。
**理由**：奈及利亞案例提示相鄰活動的暴露問題，但不能外推其距離為荷蘭規範。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：buffer_depth_trial＝[10, 30] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- AZI23／C1：Assessment of the Compatibility of Abattoir and Residential Land Uses in Jos Metropolis, Nigeria；Musa Bulus Azi、Samuel Danjuma Wapwera、Timlok Timothy Wazhi、Patrick Shehu；2023；10.22158/uspa.v6n1p21；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- ROY05／C1：Urban Informality: Toward an Epistemology of Planning；Ananya Roy；2005；https://doi.org/10.1080/01944360508976689；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CAMPBELL96／C1：Green Cities, Growing Cities, Just Cities?: Urban Planning and the Contradictions of Sustainable Development；Scott Campbell；1996；10.1080/01944369608975696；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 以服務帶及綠化分隔；代價：提供空間距離，但不保證消除污染。
- 以時段及物流路徑分離；代價：保留土地效率，但需可執行管理與觀測。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### LAN-007｜保留生產與混合用途的代價

**規則**：列出保留產業面積、工作活動、住房及公共空間的不同配置，不以住宅地價當唯一成效。
**理由**：港城轉型與公平理論要求交代地方活動及誰受益。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：production_share_trial＝[30, 40] % GFA（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HOYLE00／C1：Global and Local Change on the Port-City Waterfront；Brian Hoyle；2000；https://doi.org/10.2307/3250860；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- WATSON09／C1：‘The planned city sweeps the poor away…’: Urban planning and 21st century urbanisation；Vanessa Watson；2009；https://doi.org/10.1016/j.progress.2009.06.002；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 集中產業及獨立物流入口；代價：保障服務，但減少混合介面。
- 小尺度穿插兼容產業；代價：增加日常接觸，需污染及服務相容性檢查。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### LAN-008｜混合用途要讀時間

**規則**：以各用途營業時段比較早晚及週末活動，而非以四種用途的存在直接宣稱活力。
**理由**：街道生活與社群形成需要活動及中介條件，不由形態單獨決定。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：activity_observation_bins_trial＝4 bins/day（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- JACOBS61／C1：The Death and Life of Great American Cities；Jane Jacobs；1961；0679644334；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- TALEN99／C1：Sense of Community and Neighbourhood Form: An Assessment of the Social Doctrine of New Urbanism；Emily Talen；1999；https://doi.org/10.1080/0042098993033；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 沿主軸錯開活動時段；代價：增加全天使用，可能提高住宅干擾。
- 內側保持安靜時段；代價：保障居住，但減少夜間街道活動。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### LAN-009｜密度與機會分布分開

**規則**：按群體及方位分別列工作、服務與到站可及性；總密度或平均距離不能掩蓋不可達群體。
**理由**：波哥大案例顯示高密度可與機會不足並存，北歐研究也強調城市位置。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：accessibility_groups_min＝3 groups（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- BOGOTA17／C1：Urban form and spatial urban equity in Bogota, Colombia；Luis A. Guzman、Juan P. Bocarejo；2017；10.1016/j.trpro.2017.05.345；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- NAESS12／C1：Urban form and travel behavior: experience from a Nordic context；Petter Næss；2012；https://doi.org/10.5198/jtlu.v5i2.314；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- GEURS04／C1：Accessibility evaluation of land-use and transport strategies: review and research directions；Karst Geurs、Bert van Wee；2004；10.1016/j.jtrangeo.2003.10.005；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 優先改善最差可及性群體；代價：提高公平，可能減少總通行效率。
- 先改善最多人使用的連接；代價：提高整體效益，但可能留下小群體缺口。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### LAN-010｜用途未知不等於空地

**規則**：分類不明、非正式使用及資料衝突都列 UNKNOWN；不要把官方標籤當完整活動清單。
**理由**：形態學與非正式都市化研究提示正式分類無法涵蓋所有實際使用。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：unknown_use_review_trial＝10 % area（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- ROY05／C1：Urban Informality: Toward an Epistemology of Planning；Ananya Roy；2005；https://doi.org/10.1080/01944360508976689；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MOUDON97／C1：Urban Morphology as an emerging interdisciplinary field；Anne Vernez Moudon；1997；10.51347/jum.v1i1.4047；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- BRAZIL14／C1：The study of urban form in Brazil；Staël de Alvarenga Pereira Costa、Maria Cristina Villefort Teixeira；2014；10.51347/jum.v18i2.3998；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 保守保留未知區域；代價：減少誤刪用途，但限制生成範圍。
- 先補現場及利益關係人資料；代價：提高解釋力，需要時間與授權。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### MOB-001｜步行騎行相鄰共廊

**規則**：新自行車路與人行路放在同一生活走廊，可相鄰或明確共用；禁止產生無步行到達的孤立騎行支線。
**理由**：朋友並行、推車和抵達入口需要連續生活路線。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／PROJECT_GUARDRAIL／MULTI_SOURCE。
**參數**：corridor_gap_trial＝2 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- PUCHER08／C1：Making Cycling Irresistible: Lessons from The Netherlands, Denmark and Germany；John Pucher、Ralph Buehler；2008；10.1080/01441640701806612；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CROW／C1：Design manual for bicycle traffic；CROW；2016；9789066286597；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 分線相鄰；代價：佔地較多，但減少快慢衝突。
- 低速共用走廊；代價：節省空間但需無障礙和衝突管理。
**爭議與地域限制**：荷蘭比較研究支持系統配套，但不是人行與自行車永遠共用的證明；分隔、共享與入口配對須按流量、速度、脆弱使用者及服務交通比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-002｜公園共用須看衝突

**規則**：公園步道可提議人行騎行共用，需列出兒童、犬隻、停留與快行交點；不能將可以共用寫成必須共用。
**理由**：公園不只是通勤捷徑，也有人停留與慢走。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：shared_speed_trial＝15 km/h（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- PUCHER08／C1：Making Cycling Irresistible: Lessons from The Netherlands, Denmark and Germany；John Pucher、Ralph Buehler；2008；10.1080/01441640701806612；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CROW／C1：Design manual for bicycle traffic；CROW；2016；9789066286597；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 低速共享；代價：快行衝突可能增加。
- 穿越騎行與停留步道分流；代價：佔用更多綠地。
**爭議與地域限制**：分離與共享的效果依速度、流量、行人脆弱性和管理而變；CROW 版本與細則未查證，不能宣稱規範合規。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-003｜自行車停車靠近入口

**規則**：每棟入口附近設可由騎行走廊到達的停車點；試算停車到實際入口步行距離不超過 15 m，該值待 Founder 確認。
**理由**：停好車後不應繞到背面，也不能擋住推車或輪椅入口。
**層級／強度／權限**：COMMON_SENSE_ASSUMED／ASSUMED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：parking_to_entry_max＝15 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- PUCHER08／C1：Making Cycling Irresistible: Lessons from The Netherlands, Denmark and Germany；John Pucher、Ralph Buehler；2008；10.1080/01441640701806612；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CROW／C1：Design manual for bicycle traffic；CROW；2016；9789066286597；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 入口側分散車架；代價：維護分散且易佔入口。
- 小型集中車庫加多入口；代價：步行較遠，需安全與營運。
**爭議與地域限制**：分離與共享的效果依速度、流量、行人脆弱性和管理而變；CROW 版本與細則未查證，不能宣稱規範合規。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-004｜共享服務街道

**規則**：住宅或混合用途服務街道可提議 woonerf 類型；普通交通、服務與步行的準入要逐項列出，不能用名稱推定法定地位。
**理由**：需要配送、照護與生活活動共存而不把所有路都變車道。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：service_speed_trial＝15 km/h（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- PUCHER08／C1：Making Cycling Irresistible: Lessons from The Netherlands, Denmark and Germany；John Pucher、Ralph Buehler；2008；10.1080/01441640701806612；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CROW／C1：Design manual for bicycle traffic；CROW；2016；9789066286597；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 共享低速服務街；代價：依賴行為與管理。
- 服務路和步行庭院分開；代價：空間佔用較多。
**爭議與地域限制**：分離與共享的效果依速度、流量、行人脆弱性和管理而變；CROW 版本與細則未查證，不能宣稱規範合規。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-005｜服務環路

**規則**：中央慢行區可由外圈服務環路供應；每棟卸貨與救援路徑需在配置前保留，不事後用任意短接駁道補齊。
**理由**：工坊物流與住戶搬家需要能運作的後勤。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：service_loop_detour_trial＝1.5 ratio（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- EWING10／C1：Travel and the Built Environment；Reid Ewing、Robert Cervero；2010；10.1080/01944361003766766；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 外圈服務環路；代價：外圈與入口有交叉。
- 數個有時段控制的服務支路；代價：管理較複雜、回車空間待驗。
**爭議與地域限制**：分離與共享的效果依速度、流量、行人脆弱性和管理而變；CROW 版本與細則未查證，不能宣稱規範合規。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-006｜消防服務 40 m 是專案條件

**規則**：沿用既有專案每個分離 footprint 到路面的最短平面距離均 <=40 m 的 road-access 條件；多塊建築取各塊距離的最大值。這不是消防服務路徑或荷蘭消防合規證明。另列救援入口、作業面與准入資料缺口。
**理由**：救援和配送需要實際可用的路、入口和作業位置。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／PROJECT_GUARDRAIL／MULTI_SOURCE。
**參數**：service_reach_max＝40 m（FOUNDER／PROJECT_INSTRUCTION）
**出處**：
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- AJACOBS93／C1：Great streets；Allan B. Jacobs；1993；0262100487；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 環路提供服務面；代價：佔地與交叉多。
- 服務支路到達入口；代價：盡端回車與消防載重另待查。
**爭議與地域限制**：分離與共享的效果依速度、流量、行人脆弱性和管理而變；CROW 版本與細則未查證，不能宣稱規範合規。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-007｜尺度與用途決定交通

**規則**：試算面積<=10 ha 為中小、>10 ha 為較大；辦公 GFA 比例>=40% 提醒評估車行／停車。兩門檻僅候選，不自動增加車道。
**理由**：是否需要車流取決於交通供給、物流與日常用途，不能只看面積。
**層級／強度／權限**：COMMON_SENSE_ASSUMED／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：small_medium_area_max＝10 ha（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）；office_share_review_min＝40 % GFA（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- EWING10／C1：Travel and the Built Environment；Reid Ewing、Robert Cervero；2010；10.1080/01944361003766766；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- PUCHER08／C1：Making Cycling Irresistible: Lessons from The Netherlands, Denmark and Germany；John Pucher、Ralph Buehler；2008；10.1080/01441640701806612；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 中小混合區以慢行加服務為主；代價：仍需無障礙與物流。
- 比較較大辦公區公共交通及停車方案；代價：車位會消耗土地且誘發依賴。
**爭議與地域限制**：分離與共享的效果依速度、流量、行人脆弱性和管理而變；CROW 版本與細則未查證，不能宣稱規範合規。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-008｜城市車道保留

**規則**：既有城市車行道路預設保留，不能以方案偏好封路；逐路列出保留、改造或移除與權限，改變須 Founder 特別指示。
**理由**：周邊交通與產業不能因一塊基地設計被切斷。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／PROJECT_GUARDRAIL／MULTI_SOURCE。
**參數**：protected_geometry_change_max＝0 m²（FOUNDER／PROJECT_INSTRUCTION）
**出處**：
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- EWING10／C1：Travel and the Built Environment；Reid Ewing、Robert Cervero；2010；10.1080/01944361003766766；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 保留車道並改善跨越位置；代價：行人仍需安全穿越。
- 保持車道功能，在基地內另建慢行網；代價：可能增加路網佔地。
**爭議與地域限制**：分離與共享的效果依速度、流量、行人脆弱性和管理而變；CROW 版本與細則未查證，不能宣稱規範合規。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-009｜分模式入口配對

**規則**：每個入口接外部同模式合法道路；樓梯不能當騎行或輪椅唯一入口，水上投影相交不能算道路相接。
**理由**：不同使用者都需要能真的通過的入口。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：entry_snap_tolerance_trial＝1 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- PUCHER08／C1：Making Cycling Irresistible: Lessons from The Netherlands, Denmark and Germany；John Pucher、Ralph Buehler；2008；10.1080/01441640701806612；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- LYNCH60／C1：The Image of the City；Kevin Lynch；1960；9780262120043；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 平坡連續慢行入口；代價：路徑可能較長。
- 樓梯捷徑加獨立可達坡道；代價：需更多空間與坡度驗證。
**爭議與地域限制**：分離與共享的效果依速度、流量、行人脆弱性和管理而變；CROW 版本與細則未查證，不能宣稱規範合規。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-010｜穿越車道與停車先評估

**規則**：提議車道前列出物流、緊急、無障礙接送和普通通勤需求，比較公共交通與共享停車，不從辦公用途直接推定固定車位數。
**理由**：車位需求和日常活動會隨交通選擇與管理改變。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：parking_variants_to_compare＝2 variants（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- EWING10／C1：Travel and the Built Environment；Reid Ewing、Robert Cervero；2010；10.1080/01944361003766766；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 邊緣共用停車與內部慢行；代價：入口後仍有搬運需求。
- 受控穿越車道服務特定用途；代價：減少公共空間且新增衝突。
**爭議與地域限制**：分離與共享的效果依速度、流量、行人脆弱性和管理而變；CROW 版本與細則未查證，不能宣稱規範合規。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-011｜貨運與自行車生活相容

**規則**：工坊卸貨設於服務面，騎行與人行入口保留可識別路徑；交叉點逐一列出，而非把貨運從混合港區隱去。
**理由**：循環製造需要物流，孩子和通勤者也需要安全抵達。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：delivery_window_trial＝2 h/day（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- PUCHER08／C1：Making Cycling Irresistible: Lessons from The Netherlands, Denmark and Germany；John Pucher、Ralph Buehler；2008；10.1080/01441640701806612；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- AJACOBS93／C1：Great streets；Allan B. Jacobs；1993；0262100487；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 分時卸貨與共廊；代價：依賴營運遵守。
- 後勤面與公共入口分開；代價：街廓較深、轉角更多。
**爭議與地域限制**：分離與共享的效果依速度、流量、行人脆弱性和管理而變；CROW 版本與細則未查證，不能宣稱規範合規。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 荷蘭／丹麥／德國自行車研究支持整體系統，非 M4H 特定距離或寬度。港區貨運、消防、無障礙與兒童需求需地方資料。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOB-012｜各側沿路網到站

**規則**：從每一側合法入口到站點計算步行最短路徑，另列直線距離、不可達及路網斷點；不把附近站點直接視作可達。
**理由**：站點距離需要合法可通行路網和各側入口，不同使用者的服務範圍未必相同。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：station_catchment_trial＝[400, 800] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- GEURS04／C1：Accessibility evaluation of land-use and transport strategies: review and research directions；Karst Geurs、Bert van Wee；2004；10.1016/j.jtrangeo.2003.10.005；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- ELGENEIDY14／C1：New evidence on walking distances to transit stops: identifying redundancies and gaps using variable service areas；Ahmed El-Geneidy、Michael Grimsrud、Rania Wasfi、Paul Tétreault、Julien Surprenant-Legault；2013；10.1007/s11116-013-9508-z；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FORSYTH15／C1：What is a walkable place? The walkability debate in urban design；Ann Forsyth；2015；10.1057/udi.2015.22；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 優先接近最近站點；代價：可能集中投資一側，忽略其他方向。
- 分散連接各側站點；代價：路網較長，但提供多方向備援。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### MOB-013｜到站距離衰減敏感性

**規則**：以多個距離門檻比較可及性；只有校準後的衰減模型才可產生推估值，不能把未校準權重當觀測乘客。
**理由**：固定距離圈與步行性定義都有限制，需交代目標人群與模式。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：walk_distance_sensitivity＝[400, 1200] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- ELGENEIDY14／C1：New evidence on walking distances to transit stops: identifying redundancies and gaps using variable service areas；Ahmed El-Geneidy、Michael Grimsrud、Rania Wasfi、Paul Tétreault、Julien Surprenant-Legault；2013；10.1007/s11116-013-9508-z；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FORSYTH15／C1：What is a walkable place? The walkability debate in urban design；Ann Forsyth；2015；10.1057/udi.2015.22；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- IACONO10／C1：Measuring non-motorized accessibility: issues, alternatives, and execution；Michael Iacono、Kevin J. Krizek、Ahmed El-Geneidy；2010；10.1016/j.jtrangeo.2009.02.002；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 用多門檻可達人口比較；代價：簡單可重現但仍需人口與入口資料。
- 校準連續衰減曲線；代價：可反映距離差異，但需要觀測與校準。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### MOB-014｜北歐城市尺度交通回應

**規則**：將基地策略與住業分布、都市中心及公共運輸網一同討論，不只檢查基地內街廓。
**理由**：北歐研究提醒城市尺度的位置關係可能比鄰里特徵更關鍵。
**層級／強度／權限**：ACADEMIC／STRONG_EMPIRICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：city_context_radius_trial＝10000 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- NAESS12／C1：Urban form and travel behavior: experience from a Nordic context；Petter Næss；2012；https://doi.org/10.5198/jtlu.v5i2.314；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- EWING10／C1：Travel and the Built Environment；Reid Ewing、Robert Cervero；2010；10.1080/01944361003766766；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 改善基地內短程路線；代價：可直接改設計，但未必改變區域通勤。
- 加強跨區站點銜接；代價：服務區域需求，但需外部治理及運量資料。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### MOB-015｜步行與騎行分別說明

**規則**：對步行與自行車分別列目的地、合法路網及行程特徵；不可直接共用排名或需求係數。
**理由**：荷蘭實證把步行與自行車視作不同選項，配套政策也不能化約成一條共用路。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：mode_scenarios_min＝2 scenarios（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- TON19／C1：Cycling or walking? Determinants of mode choice in the Netherlands；Danique Ton、Dorine C. Duives、Oded Cats、Sascha Hoogendoorn-Lanser、Serge P. Hoogendoorn；2019；10.1016/j.tra.2018.08.023；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- PUCHER08／C1：Making Cycling Irresistible: Lessons from The Netherlands, Denmark and Germany；John Pucher、Ralph Buehler；2008；10.1080/01441640701806612；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- SCHWANEN18／C1：Towards decolonised knowledge about transport；Tim Schwanen；2018；https://doi.org/10.1057/s41599-018-0130-8；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 平行相鄰但分離路線；代價：降低快慢衝突，佔用更多空間。
- 低流量路段共享；代價：節省空間，需要地方衝突及無障礙檢查。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### MOR-001｜Spacematrix 指標不是類型判決

**規則**：以同一基地分母計算 FSI=GFA/A、GSI=footprint/A、L=GFA/footprint，保留既有與新增貢獻；不能由單一 FSI 直接指定類型。
**理由**：同樣樓地板量可以有不同地面空間與入口生活。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：fsi_sensitivity_range＝[1, 4] m²/m²（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- SPACEMATRIX10／C1：Spacematrix；Meta Berghauser Pont；2010；9056627422；AMBIGUOUS／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MOUDON97／C1：Urban Morphology as an emerging interdisciplinary field；Anne Vernez Moudon；1997；10.51347/jum.v1i1.4047；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOVEY14／C1：The urban density assemblage: Modelling multiple measures；Kim Dovey、Elek Pafka；2013；10.1057/udi.2013.13；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- YE14／C1：Quantitative tools in urban morphology: combining space syntax, spacematrix and mixed-use index in a GIS framework；Yu Ye、Akkelies van Nes；2014；https://doi.org/10.51347/jum.v18i2.3997；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 密度描述後比較多類型；代價：不能直接說明公共使用品質。
- 補歷史地塊與類型演變；代價：需要更多街廓資料。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-002｜街廓尺寸試算範圍

**規則**：先由路網切街廓，試算短邊／長邊 40–120 m，超出只提示比較滲透性與物流，不直接判 INVALID。
**理由**：細街廓易通行但街道佔地多，大街廓可容納工業但繞行長。
**層級／強度／權限**：COMMON_SENSE_ASSUMED／ASSUMED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：block_dimension_candidate＝[40, 120] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CONZEN60／C1：Alnwick, Northumberland: A Study in Town-Plan Analysis；M. R. G. Conzen；1960；https://doi.org/10.2307/621094；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 較細連通街廓；代價：道路佔地較多。
- 保留倉庫大地塊加通廊；代價：通廊權利與時段可能受限。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-003｜周邊式街廓

**規則**：沿街圍合配置入口與內院，沿保留道路退讓；比較首層通廊和封閉內院兩種邊界，不把圍合當唯一好形態。
**理由**：街道可形成清楚公共面，庭院則須協調隱私與日照。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：perimeter_depth_trial＝[10, 20] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- CONZEN60／C1：Alnwick, Northumberland: A Study in Town-Plan Analysis；M. R. G. Conzen；1960；https://doi.org/10.2307/621094；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- SPACEMATRIX10／C1：Spacematrix；Meta Berghauser Pont；2010；9056627422；AMBIGUOUS／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOVEY14／C1：The urban density assemblage: Modelling multiple measures；Kim Dovey、Elek Pafka；2013；10.1057/udi.2013.13；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。獨立的密度比較或建築適應觀點，用來比較量體及使用條件；不支持本卡的高度、層高或日照試算數字。
**可選回應**：
- 連續街牆加共享內院；代價：深院可能陰暗。
- 局部開口周邊式；代價：街牆較弱但增加穿越。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-004｜合院

**規則**：以可達入口圍繞院落，區分公共、共享、私有；生成時保留服務面及至少可說明的院落進出路徑。
**理由**：院落可容納聚會與安靜生活，但公共性不能靠圖面假定。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：courtyard_width_trial＝[15, 30] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- CANIGGIA／C1：Architectural Composition and Building Typology: Interpreting Basic Building；Gianfranco Caniggia、Gian Luigi Maffei；2001；https://openalex.org/W2884949338；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- HABRAKEN98／C1：The Structure of the Ordinary: Form and Control in the Built Environment；N. John Habraken、Jonathan Teicher；1998；https://openalex.org/W1519822538；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 共享居住院落；代價：管理與住戶控制需協商。
- 工坊院落分期改造；代價：與現有深度或結構不一定相容。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-005｜板樓

**規則**：板樓依日照、路網與保留結構比較朝向；每棟入口接生活走廊，樓間空地指定用途而非剩餘綠地。
**理由**：板樓能釋放地面，但空地若無入口和活動可能少人使用。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：slab_spacing_trial＝[15, 30] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- CORBUSIER／C1：The city of to-morrow and its planning；Le Corbusier、Frederick Etchells；1929；https://openalex.org/W1507584428；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 平行板樓形成開放綠帶；代價：街道界面較鬆散。
- 錯列板樓形成小庭與通路；代價：量體互遮與通道需驗證。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-006｜點式量體

**規則**：點式量體只作 20 m 上限內的選項，記錄地面開放空間與核心筒損耗；高值節點不自動長成塔樓。
**理由**：地面可更通透，但住戶入口與公共空間仍需清楚。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：point_footprint_trial＝[200, 500] m²（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- SPACEMATRIX10／C1：Spacematrix；Meta Berghauser Pont；2010；9056627422；AMBIGUOUS／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- YUE05／C1：High-rise Living in Singapore Public Housing；Belinda Yuen、Anthony Yeh、Stephen John Appold、George Earl、John Ting、Lanny Kurnianingrum Kwee；2006；10.1080/00420980500533133；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 少量相對高點式量體；代價：陰影與核心筒效率代價。
- 低點式群落；代價：較多佔地和碎片空間。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-007｜連棟

**規則**：連棟沿路配置獨立入口與服務邊，端部保留步行穿越；報告土地佔用和不同戶型可用性。
**理由**：門前生活易形成，但過長連續排屋會增加繞行。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：row_plot_width_trial＝[5, 9] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- CANIGGIA／C1：Architectural Composition and Building Typology: Interpreting Basic Building；Gianfranco Caniggia、Gian Luigi Maffei；2001；https://openalex.org/W2884949338；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CONZEN60／C1：Alnwick, Northumberland: A Study in Town-Plan Analysis；M. R. G. Conzen；1960；https://doi.org/10.2307/621094；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 短排連棟與橫向通路；代價：端牆與服務佔地增加。
- 長排加共享入口穿廊；代價：通廊管理與私密衝突。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-008｜基座加相對高量體

**規則**：基座沿街放用途，上層局部退台或抬高，總高仍 <=20 m；公共穿越須落在可用入口，不能穿過封閉基座。
**理由**：密度與街道活動可集中，基座也可能成屏障。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：podium_height_trial＝[3.5, 7] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- SPACEMATRIX10／C1：Spacematrix；Meta Berghauser Pont；2010；9056627422；AMBIGUOUS／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- YUE05／C1：High-rise Living in Singapore Public Housing；Belinda Yuen、Anthony Yeh、Stephen John Appold、George Earl、John Ting、Lanny Kurnianingrum Kwee；2006；10.1080/00420980500533133；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 多入口通透基座；代價：管理與結構較複雜。
- 低基座加局部高體；代價：上部 GFA 減少，需日照證據。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-009｜保留與 box-in-box

**規則**：保留倉庫外殼不動，在資料足夠時提出可逆 box-in-box 功能單元；不以知識卡授權穿鑿或新增載重。
**理由**：新用途與舊製造可共存，原有空間和產業不被抹去。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：internal_insertion_clearance_trial＝1 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- DOUGLAS06／C1：Building Adaptation；James Douglas；2006；https://doi.org/10.4324/9780080458519；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- HABRAKEN98／C1：The Structure of the Ordinary: Form and Control in the Built Environment；N. John Habraken、Jonathan Teicher；1998；https://openalex.org/W1519822538；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 可拆內置單元；代價：消防、採光與結構需專業審查。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 少介入維持大空間；代價：能耗與舒適升級可能有限。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-010｜高度不要單一但不強迫花樣

**規則**：依位置與用途提出至少兩種高度配置的比較；選擇等高也須說明原因與 context，不能只為差異製造無功能高低。
**理由**：地標、日照、工坊層高與居住需求不同。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：height_variants_to_compare＝3 variants（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- SPACEMATRIX10／C1：Spacematrix；Meta Berghauser Pont；2010；9056627422；AMBIGUOUS／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOVEY14／C1：The urban density assemblage: Modelling multiple measures；Kim Dovey、Elek Pafka；2013；10.1057/udi.2013.13；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。獨立的密度比較或建築適應觀點，用來比較量體及使用條件；不支持本卡的高度、層高或日照試算數字。
**可選回應**：
- 沿主軸相對高、內側較低；代價：可能加大地價和陰影差。
- 等高加局部退台比較；代價：地標需依入口和公共空間辨識。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-011｜建築不得壓道路

**規則**：任何新建築 footprint 不得佔用保留或新建道路面，包括人行、自行車、服務與城市車道；道路與保留物先凍結再排量體。
**理由**：路面若被佔，生活與救援路徑就不存在。
**層級／強度／權限**：ACADEMIC／THEORETICAL／PROJECT_GUARDRAIL／MULTI_SOURCE。
**參數**：protected_overlap_max＝0 m²（FOUNDER／PROJECT_INSTRUCTION）
**出處**：
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- AJACOBS93／C1：Great streets；Allan B. Jacobs；1993；0262100487；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 退縮量體保留完整路廊；代價：可建面積減少。
- 在路網可編輯區調整量體分塊；代價：更多入口與結構成本，既有城市路仍不動。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-012｜保留建築不可挪動

**規則**：保留建築 id、footprint、已知高度與保留層級不得由新方案改寫；資料缺高度不能補成零。
**理由**：既有生產、記憶與使用者權益需要可追蹤的保留。
**層級／強度／權限**：ACADEMIC／THEORETICAL／PROJECT_GUARDRAIL／MULTI_SOURCE。
**參數**：protected_geometry_change_max＝0 m²（FOUNDER／PROJECT_INSTRUCTION）
**出處**：
- CONZEN60／C1：Alnwick, Northumberland: A Study in Town-Plan Analysis；M. R. G. Conzen；1960；https://doi.org/10.2307/621094；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOUGLAS06／C1：Building Adaptation；James Douglas；2006；https://doi.org/10.4324/9780080458519；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 圍繞保留物配置新建；代價：可建區破碎。
- 不動保留外殼並提可逆用途；代價：使用權與內部改造另需批准。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-013｜20 m 是專案上限

**規則**：D2 A 新建高度維持 20 m 上限；相對地標在此範圍內比較，知識卡不能為增加辨識度抬高上限。
**理由**：設計者可以比較高低與空地，不須犧牲已接受條件。
**層級／強度／權限**：ACADEMIC／THEORETICAL／PROJECT_GUARDRAIL／MULTI_SOURCE。
**參數**：new_building_height_max＝20 m（FOUNDER／PROJECT_INSTRUCTION）
**出處**：
- YE14／C1：Quantitative tools in urban morphology: combining space syntax, spacematrix and mixed-use index in a GIS framework；Yu Ye、Akkelies van Nes；2014；https://doi.org/10.51347/jum.v18i2.3997；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 中心 20 m 以下、鄰棟較低；代價：高處陰影仍需測。
- 較均勻高度靠退台與入口地標；代價：意象效果需設計者判斷。
**爭議與地域限制**：相同密度可由不同形態形成；傳統街廓、現代板樓和高密度策略的公共性、日照與控制方式不同。書目尚未逐頁查證，不能預設一派較好。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國歷史形態、義大利類型學、荷蘭密度與亞洲高密度各有取樣偏向；M4H 倉庫結構與保留邊界需實測，類型不構成偏好排名。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### MOR-014｜巴西與歐洲形態學比較

**規則**：讀基地的街道、地塊與建築歷史，將地方分類和英國城鎮平面框架並列，不強制套用歐洲類型。
**理由**：巴西研究包含多學科與殖民歷史，跨地域分類需說明轉譯限制。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：historical_layers_min＝2 layers（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- BRAZIL14／C1：The study of urban form in Brazil；Staël de Alvarenga Pereira Costa、Maria Cristina Villefort Teixeira；2014；10.51347/jum.v18i2.3998；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CONZEN60／C1：Alnwick, Northumberland: A Study in Town-Plan Analysis；M. R. G. Conzen；1960；https://doi.org/10.2307/621094；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MOUDON97／C1：Urban Morphology as an emerging interdisciplinary field；Anne Vernez Moudon；1997；10.51347/jum.v1i1.4047；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 保留歷史地塊節奏；代價：延續地方閱讀，限制新建尺度。
- 重新組合地塊並記錄損失；代價：提高適應性，可能抹去既有關係。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### MOR-015｜密度路網用途聯合診斷

**規則**：把 FSI、GSI、層數、路網中心性及用途並列，任何一項不能單獨指定最佳型態。
**理由**：荷蘭聯合診斷與密度多維模型提供不同分析視角。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：morphology_variants_min＝3 variants（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- YE14／C1：Quantitative tools in urban morphology: combining space syntax, spacematrix and mixed-use index in a GIS framework；Yu Ye、Akkelies van Nes；2014；https://doi.org/10.51347/jum.v18i2.3997；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOVEY14／C1：The urban density assemblage: Modelling multiple measures；Kim Dovey、Elek Pafka；2013；10.1057/udi.2013.13；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- SPACEMATRIX10／C1：Spacematrix；Meta Berghauser Pont；2010；9056627422；AMBIGUOUS／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 以周邊街廓集中量體；代價：形成街面，需要檢查內院環境。
- 以較疏開量體分散高度；代價：增加間隙，可能降低沿街連續性。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### MOR-016｜亞洲高層生活與環境

**規則**：將高層住宅的地方生活研究與高密度通風方法並列，依 D2 上限試算較低量體；不複製亞洲高度。
**理由**：新加坡住宅生活與香港環境評估不是同一條通用高度規則。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：height_alternatives_min＝3 variants（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- YUE05／C1：High-rise Living in Singapore Public Housing；Belinda Yuen、Anthony Yeh、Stephen John Appold、George Earl、John Ting、Lanny Kurnianingrum Kwee；2006；10.1080/00420980500533133；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- NG09／C1：Policies and technical guidelines for urban planning of high-density cities – air ventilation assessment (AVA) of Hong Kong；Edward Ng；2009；10.1016/j.buildenv.2008.06.013；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOVEY14／C1：The urban density assemblage: Modelling multiple measures；Kim Dovey、Elek Pafka；2013；10.1057/udi.2013.13；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 集中相對高量體留開放面；代價：提高開放面，可能增加風與視線問題。
- 平均分散較低量體；代價：降低局部高差，可能增加覆蓋。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### POL-001｜M4H 政策待查

**規則**：現況、M4H 願景與現行法定規劃要分開呈現；精確政策文件未取得，不能推定政府允許的用途或比例。
**理由**：形態及公平文獻提供審查角度，無法替代具版本、範圍與效力的地方政策文件。
**層級／強度／權限**：POLICY／ASSUMED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：policy_versions_to_compare＝2 versions（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- MOUDON97／C1：Urban Morphology as an emerging interdisciplinary field；Anne Vernez Moudon；1997；10.51347/jum.v1i1.4047；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- WATSON09／C1：‘The planned city sweeps the poor away…’: Urban planning and 21st century urbanisation；Vanessa Watson；2009；https://doi.org/10.1016/j.progress.2009.06.002；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：M4H_PENDING
**可選回應**：
- 以待查政策列資料缺口；代價：不能宣稱合規。
- 僅比較非約束性的 portfolio 候選；代價：仍需正式政策才能決策。
**爭議與地域限制**：未取得政策原文，不知道新舊文件差異；兩學術來源只支持方法與公平，不支持任何 M4H 條文。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 M4H 政策地域相關但文件身份未核實；移用外國政策禁止。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POL-002｜政策書目不能當法定約束

**規則**：記錄每份政策的版本、日期、適用範圍及權責；未取得法定文件時，學術知識只能協助列問題。
**理由**：可及性方法與協作理論不能取代法律效力或人類批准。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：policy_review_versions_trial＝2 versions（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- GEURS04／C1：Accessibility evaluation of land-use and transport strategies: review and research directions；Karst Geurs、Bert van Wee；2004；10.1016/j.jtrangeo.2003.10.005；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- HEALEY97／C1：Collaborative planning；Patsy Healey；1997；9780774805971；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 只對已確認政策作約束檢查；代價：保守可追溯，但可能暫時缺少方向。
- 把願景另列候選策略；代價：可探索未來，不能宣稱已合法。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### POL-003｜成長公平環境衝突表

**規則**：每案列明成長、環境及公平各自的受益與成本，保留分歧；沒有 Founder 決定規則不得產生總冠軍。
**理由**：永續目標存在衝突，協作程序需要顯示參與者與選擇。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：tradeoff_dimensions_min＝3 dimensions（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- CAMPBELL96／C1：Green Cities, Growing Cities, Just Cities?: Urban Planning and the Contradictions of Sustainable Development；Scott Campbell；1996；10.1080/01944369608975696；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- HEALEY97／C1：Collaborative planning；Patsy Healey；1997；9780774805971；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 優先住房與活動量；代價：增加供給，但需比較環境及產業成本。
- 優先既有社群及環境修復；代價：保護地方條件，可能降低開發量。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### POL-004｜非正式使用與遷移風險

**規則**：列實際活動、資料不完整及可能被排除的使用者；不以整齊幾何或新建量代替社會成效。
**理由**：全球南方的規劃批評要求檢視制度例外與排除。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：stakeholder_groups_trial＝4 groups（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- ROY05／C1：Urban Informality: Toward an Epistemology of Planning；Ananya Roy；2005；https://doi.org/10.1080/01944360508976689；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- WATSON09／C1：‘The planned city sweeps the poor away…’: Urban planning and 21st century urbanisation；Vanessa Watson；2009；https://doi.org/10.1016/j.progress.2009.06.002；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- SCHWANEN18／C1：Towards decolonised knowledge about transport；Tim Schwanen；2018；https://doi.org/10.1057/s41599-018-0130-8；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 保留可調整的日常使用；代價：降低排除，管理需求較多。
- 分期轉移並列明保障；代價：可配合改造，需具體權利與補償安排。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### POL-005｜港區轉型分期與物流

**規則**：把港區物流、既有建築與新增公共面分期比較；政府政策未確認不得自動把工業用途改成住宅。
**理由**：港城變動具有全球和地方動因，永續利益可能互相衝突。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：conversion_phases_trial＝3 phases（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HOYLE00／C1：Global and Local Change on the Port-City Waterfront；Brian Hoyle；2000；https://doi.org/10.2307/3250860；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CAMPBELL96／C1：Green Cities, Growing Cities, Just Cities?: Urban Planning and the Contradictions of Sustainable Development；Scott Campbell；1996；10.1080/01944369608975696；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 保留物流帶再開放水岸；代價：減少衝突，公共面可能延後。
- 先開放局部公共節點；代價：較快建立連接，需安全及管理界線。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### POR-001｜循環在地生產

**規則**：將可再利用材料、生產工坊和物流面列入用途候選，並保留流量與營運 DATA_GAP。
**理由**：在地循環需要真實供應與工作空間，不是綠色標籤。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：local_production_share_trial＝30 % GFA（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- KIRCHHERR17／C1：Conceptualizing the circular economy: An analysis of 114 definitions；Julian Kirchherr、Denise Reike、Marko Hekkert；2017；10.1016/j.resconrec.2017.09.005；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CAMPBELL96／C1：Green Cities, Growing Cities, Just Cities?: Urban Planning and the Contradictions of Sustainable Development；Scott Campbell；1996；10.1080/01944369608975696；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 共用工坊和服務面；代價：循環效果需物質流驗證。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 保留分散小製造租戶；代價：協作物流較難。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-002｜自然為本與韌性

**規則**：把蓄排水、耐受變動與綠地列為試案，先標污染、地下管網和洪水資料缺口。
**理由**：讓日常生活可承受天氣變化，同時不假裝已有性能。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：rainwater_retention_trial＝20 mm（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- AHERN11／C1：From fail-safe to safe-to-fail: Sustainability and resilience in the new urban world；Jack Ahern；2011；https://doi.org/10.1016/j.landurbplan.2011.02.021；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- BROWN09／C1：Urban water management in cities: historical, current and future regimes；R. R. Brown、N. Keath、T. H. F. Wong；2009；10.2166/wst.2009.029；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 分散可失效小型綠地；代價：維護多且容量未知。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 集中水治理設施；代價：失效集中並需專業水工。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-003｜綠地與社會生態連結

**規則**：將碎片綠地連成可步行候選網，同時列出生態連續與公共準入差異。
**理由**：走得到的綠地與生態棲地不一定是同一種空間。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：habitat_gap_trial＝20 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- AHERN11／C1：From fail-safe to safe-to-fail: Sustainability and resilience in the new urban world；Jack Ahern；2011；https://doi.org/10.1016/j.landurbplan.2011.02.021；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 公共綠廊連接社區；代價：可能干擾棲地。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 生態緩衝加有限通行；代價：公共滲透性較低。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-004｜港區轉混合用途

**規則**：保留產業需求與倉庫，提出混合用途及分期，不直接以住宅取代製造。
**理由**：工作、居住與服務互補，同時避免原有使用者被排除。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：use_categories_trial＝4 categories（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- JACOBS61／C1：The Death and Life of Great American Cities；Jane Jacobs；1961；0679644334；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- HOYLE00／C1：Global and Local Change on the Port-City Waterfront；Brian Hoyle；2000；https://doi.org/10.2307/3250860；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- WATSON09／C1：‘The planned city sweeps the poor away…’: Urban planning and 21st century urbanisation；Vanessa Watson；2009；https://doi.org/10.1016/j.progress.2009.06.002；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 工坊加住宅分期；代價：噪音與安全需管理。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 先增公共設施再轉型；代價：資金回收較慢。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-005｜無車綠廊

**規則**：基地內提議中央無普通車流綠廊，步行騎行共用或相鄰；外部城市車道保持，後勤由服務網保障。
**理由**：中心可以聚人，但生產和救援不能失聯。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：green_corridor_width_trial＝[10, 20] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- PUCHER08／C1：Making Cycling Irresistible: Lessons from The Netherlands, Denmark and Germany；John Pucher、Ralph Buehler；2008；10.1080/01441640701806612；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 中央共享綠廊；代價：快慢衝突。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 並行分線綠廊；代價：佔地較多。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-006｜服務環路作品集策略

**規則**：把工坊與保留物服務面接至外圈，比較完整環路與分時服務支路，不畫無功能環。
**理由**：物流需要可達，中心保留慢行生活。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：service_gate_count_trial＝2 gates（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- AJACOBS93／C1：Great streets；Allan B. Jacobs；1993；0262100487；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 閉合服務環；代價：佔地與交叉多。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 短服務支路；代價：回車與營運限制。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-007｜開放樓梯

**規則**：Dakpark 高差處可提出可見開放樓梯，同時列可達替代路徑與垂直基準。
**理由**：樓梯是捷徑與相遇點，但不能排除推車或輪椅。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：stair_rest_interval_trial＝1.5 m vertical（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- LYNCH60／C1：The Image of the City；Kevin Lynch；1960；9780262120043；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 可見樓梯加替代坡道；代價：替代路可能較遠。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 分層平台入口；代價：結構與維護成本。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-008｜通透一樓

**規則**：每個提議穿越的一樓列入口、出口、時段和權利，不把柱廊視覺通透當公共通路。
**理由**：人需要實際走到中心，不只是看得穿。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：ground_floor_porosity_trial＝40 % frontage（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HABRAKEN98／C1：The Structure of the Ordinary: Form and Control in the Built Environment；N. John Habraken、Jonathan Teicher；1998；https://openalex.org/W1519822538；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- LYNCH60／C1：The Image of the City；Kevin Lynch；1960；9780262120043；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 全天通廊候選；代價：管理與安全需證據。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 限定共享庭院；代價：公共穿越降低。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-009｜擋風量體

**規則**：提議擋風邊界時列風向與行人高度資料缺口；沒有 CFD 或實測不聲稱風改善。
**理由**：可停留場所受風影響，但擋風也可能形成強風角。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：wind_variants_to_compare＝3 variants（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- AHERN11／C1：From fail-safe to safe-to-fail: Sustainability and resilience in the new urban world；Jack Ahern；2011；https://doi.org/10.1016/j.landurbplan.2011.02.021；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 低量體與樹帶試案；代價：季節性與樹木成長。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 連續建築遮蔽試案；代價：轉角加速與陰影。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-010｜雨水潮汐公園

**規則**：分開雨水滯留與潮汐交換機製，列水位、污染、容量與安全 DATA_GAP，先做候選空間不得填性能。
**理由**：水與生活可以接近，但港區水與土壤風險须被看見。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：rain_event_depth_trial＝[10, 30] mm（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- BROWN09／C1：Urban water management in cities: historical, current and future regimes；R. R. Brown、N. Keath、T. H. F. Wong；2009；10.2166/wst.2009.029；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- AHERN11／C1：From fail-safe to safe-to-fail: Sustainability and resilience in the new urban world；Jack Ahern；2011；https://doi.org/10.1016/j.landurbplan.2011.02.021；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 分散雨水庭；代價：容量與維護分散。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 集中潮汐景觀；代價：污染與水工審查。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-011｜綠橋

**規則**：跨高差或障礙的綠橋須先定入口與到達路徑，列淨空、承重、權利 TODO_SOURCE，不只畫橋連線。
**理由**：橋能跨障礙，也可能使輪椅與自行車繞遠。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：bridge_clear_width_trial＝4 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- LYNCH60／C1：The Image of the City；Kevin Lynch；1960；9780262120043；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 可見綠橋；代價：造價與坡道長。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 地面繞行綠廊；代價：距離較長但結構簡單。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-012｜活躍基座

**規則**：高可達沿街基座放可進入工坊、設施或小店，保留住宅與服務入口各自路徑。
**理由**：地面生活不必全是消費，也包含工作與照護。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：active_plinth_share_trial＝60 % frontage（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- JACOBS61／C1：The Death and Life of Great American Cities；Jane Jacobs；1961；0679644334；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- GEHL10／C1：Cities for People；Jan Gehl；2010；9781597265737；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 小單元混合基座；代價：租金與維護多。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 公共設施入口基座；代價：受營運時間限制。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-013｜Box-in-box 改造

**規則**：保留外殼不動，提議可逆內置單元並列結構、消防、採光未知；不得直接變更正式保留模型。
**理由**：新活動可以進入舊倉而不抹去大空間。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：insertion_footprint_share_trial＝50 % retained footprint（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- DOUGLAS06／C1：Building Adaptation；James Douglas；2006；https://doi.org/10.4324/9780080458519；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- HABRAKEN98／C1：The Structure of the Ordinary: Form and Control in the Built Environment；N. John Habraken、Jonathan Teicher；1998；https://openalex.org/W1519822538；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 可拆內置盒；代價：採光與載重需驗。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 最少介入用途變換；代價：舒適升級有限。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-014｜垂直增密

**規則**：在新建可編輯區比較局部增層或退台，仍守20 m；對保留樓增建只記候選，不授權改動。
**理由**：可保留地面空間，但結構承載與陰影不會由意圖文字解决。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：added_floors_trial＝[1, 2] floors（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- SPACEMATRIX10／C1：Spacematrix；Meta Berghauser Pont；2010；9056627422；AMBIGUOUS／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOVEY14／C1：The urban density assemblage: Modelling multiple measures；Kim Dovey、Elek Pafka；2013；10.1057/udi.2013.13；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。獨立的密度比較或建築適應觀點，用來比較量體及使用條件；不支持本卡的高度、層高或日照試算數字。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 新建局部增層；代價：陰影與核心筒代價。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 分散低層保地面入口；代價：GSI 增加。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-015｜開放建築

**規則**：區分長壽命支撐結構與可變填充，輸出管理與使用者可改的邊界，不假定無限制自由。
**理由**：不同家庭與工作用途会改變，使用者需要控制權。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：adaptable_bay_width_trial＝[5, 8] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HABRAKEN98／C1：The Structure of the Ordinary: Form and Control in the Built Environment；N. John Habraken、Jonathan Teicher；1998；https://openalex.org/W1519822538；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOUGLAS06／C1：Building Adaptation；James Douglas；2006；https://doi.org/10.4324/9780080458519；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 支撐與填充分離；代價：初期成本與管理複雜。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 可逆最小改造；代價：空間彈性可能有限。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-016｜景觀線網與社交節點

**規則**：把主路、步道、水道、植栽斑塊與社交節點分層；圓形只是候選，节點先由入口與活動决定。
**理由**：人走的線、坐的地方與水流路徑需要共同檢查。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：social_node_spacing_trial＝[30, 60] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- WHYTE80／C1：The social life of small urban spaces；William H. Whyte；1980；https://openalex.org/W1538435250；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- AHERN11／C1：From fail-safe to safe-to-fail: Sustainability and resilience in the new urban world；Jack Ahern；2011；https://doi.org/10.1016/j.landurbplan.2011.02.021；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 沿路小型社交節點；代價：維護分散。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 生態連續斑塊加集中活動面；代價：人群可能遠離部分綠地。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-017｜日照對角切削與生態坡

**規則**：Dakpark 邊比較對角切削、生態坡與退台，固定日照條件；坡度與生態成效無資料則未知。
**理由**：高差連結、光與生態可能有不同空間需求。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：slope_gradient_trial＝5 %（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- AHERN11／C1：From fail-safe to safe-to-fail: Sustainability and resilience in the new urban world；Jack Ahern；2011；https://doi.org/10.1016/j.landurbplan.2011.02.021；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DAVOUDI12／C1：Resilience: A Bridging Concept or a Dead End?“Reframing” Resilience: Challenges for Planning Theory and PracticeInteracting Traps: Resilience Assessment of a Pasture Management System in Northern AfghanistanUrban Resilience: What Does it Mean in Planning Practice?Resilience as a Useful Concept for Climate Change Adaptation?The Politics of Resilience for Planning: A Cautionary Note；Simin Davoudi、Keith Shaw、L. Jamila Haider、Allyson E. Quinlan、Garry D. Peterson、Cathy Wilkinson、Hartmut Fünfgeld、Darryn McEvoy、Libby Porter；2012；10.1080/14649357.2012.677124；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 切削量體加生態坡；代價：GFA 減少與結構複雜。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 量體退後保留地形；代價：連接路徑可能较長。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### POR-018｜標準層高僅試算

**規則**：使用約3.5 m 層高估算新建候選層數，混合用途可另提層高；不得用樓層乘法取代量測高度與逐層GFA。
**理由**：工坊、住宅和設施淨高不同，統一層高可能無法使用。
**層級／強度／權限**：PORTFOLIO／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：indicative_floor_height＝3.5 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- SPACEMATRIX10／C1：Spacematrix；Meta Berghauser Pont；2010；9056627422；AMBIGUOUS／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- NG10／C1：Designing high-density cities for social and environmental sustainability；Edward Ng；2009；9781844074600；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- DOUGLAS06／C1：Building Adaptation；James Douglas；2006；https://doi.org/10.4324/9780080458519；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。獨立的密度比較或建築適應觀點，用來比較量體及使用條件；不支持本卡的高度、層高或日照試算數字。
**本機脈絡（不計研究來源）**：PORTFOLIO
**可選回應**：
- 3.5 m 等層試算；代價：只適合早期量體。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
- 首層較高與上層分開試算；代價：總層數可能減少。 作品集提供設計意圖，學術引用僅為類似概念的佐證，未驗證作品集本身。
**爭議與地域限制**：作品集構想可用於提出選項，學術來源提供比較概念而非該設計的驗證；相反取向保留給設計者比較。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 作品集為 M4H 個案；引用的外地研究只支持概念，不能證明本案營運、權利、性能或偏好。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### PUB-001｜廣場大小試算

**規則**：節點廣場可試算 400–1600 m²，再以可達入口、停留邊緣和使用目的比較；不能以面積達標宣稱有活力。
**理由**：過大空場可能難聚人，小場可能不容活動與騎行通過。
**層級／強度／權限**：COMMON_SENSE_ASSUMED／ASSUMED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：square_area_trial＝[400, 1600] m²（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- WHYTE80／C1：The social life of small urban spaces；William H. Whyte；1980；https://openalex.org/W1538435250；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CONZEN60／C1：Alnwick, Northumberland: A Study in Town-Plan Analysis；M. R. G. Conzen；1960；https://doi.org/10.2307/621094；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 小廣場加沿邊座位；代價：大型活動受限。
- 較大清楚圍合廣場；代價：淡季可能空曠。
**爭議與地域限制**：公共生活觀察與場所意象不等同普適處方；氣候、階級、性別、管理與使用時段改變結果。原書未逐頁核對。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 美國小空間與丹麥公共生活經驗可提出試案；港區工人、居民與騎行者的 M4H 使用行為仍未知。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### PUB-002｜停留與通行分清

**規則**：主通路旁安排座位與停留邊，不在最短通行線上放固定活動物件；保留能選擇日曬或遮蔽的位置。
**理由**：老人、照護者與工人午休需要停留，通勤者需要通過。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：clear_passage_width_trial＝3 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- WHYTE80／C1：The social life of small urban spaces；William H. Whyte；1980；https://openalex.org/W1538435250；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- GEHL10／C1：Cities for People；Jan Gehl；2010；9781597265737；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 沿邊坐處；代價：可能形成排他管理。
- 分散小停留點；代價：維護分散、社交聚集較弱。
**爭議與地域限制**：公共生活觀察與場所意象不等同普適處方；氣候、階級、性別、管理與使用時段改變結果。原書未逐頁核對。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 美國小空間與丹麥公共生活經驗可提出試案；港區工人、居民與騎行者的 M4H 使用行為仍未知。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### PUB-003｜活躍立面不是全部商業

**規則**：沿主要生活路線指定可進入的一樓工坊、社會設施或小店及門的位置；無資料時不要虛構營業時間與透明比例。
**理由**：看到活動與實際入口可支持路上生活，製造也能形成公共面。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：noncommercial_active_share_trial＝30 % active frontage（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- GEHL10／C1：Cities for People；Jan Gehl；2010；9781597265737；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- JACOBS61／C1：The Death and Life of Great American Cities；Jane Jacobs；1961；0679644334；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 可見工坊與展示入口；代價：噪音與生產安全要隔離。
- 公共設施與小店交錯；代價：營運與租金有不確定性。
**爭議與地域限制**：公共生活觀察與場所意象不等同普適處方；氣候、階級、性別、管理與使用時段改變結果。原書未逐頁核對。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 美國小空間與丹麥公共生活經驗可提出試案；港區工人、居民與騎行者的 M4H 使用行為仍未知。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### PUB-004｜入口與活動口袋

**規則**：在可達入口或路口側邊提議小活動口袋；門前不得被停車或家具擋住，口袋與中心主路保持看得懂的連結。
**理由**：人会在轉換與等待處停留，不能只靠遠處大廣場。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：activity_pocket_spacing_trial＝[30, 60] m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- ALEX77／C1：A Pattern Language: Towns, Buildings, Construction；Christopher Alexander、Sara Ishikawa、Murray Silverstein、Max Jacobson、Ingrid Fiksdahl-King、Shlomo Angel；1977；https://openalex.org/W1968983388；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- LYNCH60／C1：The Image of the City；Kevin Lynch；1960；9780262120043；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 門側活動口袋；代價：佔用入口面積。
- 可見節點串聯小空間；代價：序列較長、需要導向。
**爭議與地域限制**：公共生活觀察與場所意象不等同普適處方；氣候、階級、性別、管理與使用時段改變結果。原書未逐頁核對。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 美國小空間與丹麥公共生活經驗可提出試案；港區工人、居民與騎行者的 M4H 使用行為仍未知。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### PUB-005｜公共空間公平與控制

**規則**：每個開放空間列 public/shared/private/unknown、開放時段與管理者資料缺口；漂亮圖面不能證明公共使用權。
**理由**：工人、居民、兒童與非消費者都應被考慮。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：public_access_hours_trial＝24 h/day（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- HABRAKEN98／C1：The Structure of the Ordinary: Form and Control in the Built Environment；N. John Habraken、Jonathan Teicher；1998；https://openalex.org/W1519822538；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CARMONA10／C1：Contemporary Public Space: Critique and Classification, Part One: Critique；Matthew Carmona；2010；https://doi.org/10.1080/13574800903435651；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- LOW05／C1：Rethinking urban parks；Setha M. Low；2005；0292712545；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 公開公共空間與非消費坐處；代價：需要持續公共維護。
- 住戶共管庭院加公共通道；代價：通道權利與排他風險。
**爭議與地域限制**：公共生活觀察與場所意象不等同普適處方；氣候、階級、性別、管理與使用時段改變結果。原書未逐頁核對。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 美國小空間與丹麥公共生活經驗可提出試案；港區工人、居民與騎行者的 M4H 使用行為仍未知。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### PUB-006｜路網形態與盡端比較

**規則**：網格、軸線、向心與綠廊至少比較兩種；列出轉角、盡端、入口與繞行，不把正交或無盡端當普適美感規則。
**理由**：好走、好找和安靜可能對不同群體有不同要求。
**層級／強度／權限**：ACADEMIC／NORMATIVE_PRACTICE／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：dead_end_length_trial＝40 m（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- AJACOBS93／C1：Great streets；Allan B. Jacobs；1993；0262100487；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 滲透網格；代價：路口多，安靜區較少。
- 主軸與短支路；代價：入口依賴與繞行可能增加。
**爭議與地域限制**：公共生活觀察與場所意象不等同普適處方；氣候、階級、性別、管理與使用時段改變結果。原書未逐頁核對。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 美國小空間與丹麥公共生活經驗可提出試案；港區工人、居民與騎行者的 M4H 使用行為仍未知。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### PUB-007｜公共空間管理與文化差異

**規則**：除了停留及通行，列可使用時段、管理限制、可負擔性與不同群體的活動需求。
**理由**：公共性受管理與文化差異影響，不由廣場形式單獨確定。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：public_hours_comparison_trial＝[12, 24] h/day（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- CARMONA10／C1：Contemporary Public Space: Critique and Classification, Part One: Critique；Matthew Carmona；2010；https://doi.org/10.1080/13574800903435651；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- LOW05／C1：Rethinking urban parks；Setha M. Low；2005；0292712545；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- FANSTEIN10／C1：The just city；Susan S. Fainstein；2010；9780801476907；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 廣泛開放多種日常活動；代價：增加包容，需維護及衝突協調。
- 分時管理特定活動；代價：便於管理，可能排除部分使用者。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### PUB-008｜社群感不得由形式推定

**規則**：每案分別說明可觀察的相遇機會與尚未驗證的社群結果，不以街廓或活躍基座直接宣稱社會凝聚。
**理由**：新都市主義批評指出物理形式與社群感之間有中介條件。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：social_observation_period_trial＝7 days（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- TALEN99／C1：Sense of Community and Neighbourhood Form: An Assessment of the Social Doctrine of New Urbanism；Emily Talen；1999；https://doi.org/10.1080/0042098993033；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- JACOBS61／C1：The Death and Life of Great American Cities；Jane Jacobs；1961；0679644334；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- CARMONA10／C1：Contemporary Public Space: Critique and Classification, Part One: Critique；Matthew Carmona；2010；https://doi.org/10.1080/13574800903435651；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 用共享活動節點增加相遇；代價：提供機會，但不保證關係形成。
- 以分散小節點支援不同群體；代價：較有選擇，活動可能分散。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### SYN-001｜自然移動是待驗假說

**規則**：把角度整合度與實際入口、用途、時段並列；可提議較易被經過的路線，不把高值轉成預測人數。
**理由**：人選路受可讀性、目的地、安全與門禁共同影響。
**層級／強度／權限**：ACADEMIC／MIXED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：observation_interval＝30 min（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HILLIER93／C1：Natural movement: or, configuration and attraction in urban pedestrian movement；Bill Hillier、Alan Penn、Julienne Hanson、T Grajewski、Jianming Xu；1993；10.1068/b200029；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- RATTI04／C1：Space Syntax: Some Inconsistencies；Carlo Ratti；2004；10.1068/b3019；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- PORTA06／C1：The Network Analysis of Urban Streets: A Primal Approach；Sergio Porta、Paolo Crucitti、Vito Latora；2006；10.1068/b32045；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- SHARMIN17／C1：Meta-analysis of the relationships between space syntax measures and pedestrian movement；Samia Sharmin、Md. Kamruzzaman；2017；https://doi.org/10.1080/01441647.2017.1365101；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- HILLIERPENN04／C1：Rejoinder to Carlo Ratti；Bill Hillier、Alan Penn；2004；https://doi.org/10.1068/b3019a；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 以角度整合度提出候選主軸；代價：可能忽略目的地吸引力。
- 用 primal centrality 與現場流量交叉檢查；代價：需要另一套圖表示與觀察資料。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-002｜高整合度沿街的一樓

**規則**：將 High 路段相鄰首層列為商店、共享工坊或公共設施候選；記錄入口與營業時間，保留噪音隔離。
**理由**：讓路過的人有可進入的目的地，同時避免住宅入口被服務車干擾。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：active_frontage_trial＝60 % facade length（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HILLIER93／C1：Natural movement: or, configuration and attraction in urban pedestrian movement；Bill Hillier、Alan Penn、Julienne Hanson、T Grajewski、Jianming Xu；1993；10.1068/b200029；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- JACOBS61／C1：The Death and Life of Great American Cities；Jane Jacobs；1961；0679644334；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 沿街連續活躍小單元；代價：租金與夜間噪音可能排除原有製造。
- 少量公共入口搭配保留工坊；代價：活躍時段較短但維持生產。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-003｜高整合度節點有多種回應

**規則**：High 節點至少比較廣場、相對較高入口地標、廣場加地標三種配置；分別寫出用途、視線及面積代價。
**理由**：人需要聚集場所，也需要看懂入口；地標不能取代能停留的地方。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：node_options_min＝3 options（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HILLIER93／C1：Natural movement: or, configuration and attraction in urban pedestrian movement；Bill Hillier、Alan Penn、Julienne Hanson、T Grajewski、Jianming Xu；1993；10.1068/b200029；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- WHYTE80／C1：The social life of small urban spaces；William H. Whyte；1980；https://openalex.org/W1538435250；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- LYNCH60／C1：The Image of the City；Kevin Lynch；1960；9780262120043；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 留廣場與座位；代價：減少可建樓地板並需維護。
- 在上限內設相對高地標；代價：可能增加陰影及視覺支配。
- 小廣場加入口地標；代價：面積與形象折衷，仍需日照驗證。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-004｜高選擇度穿越路線

**規則**：對高 choice 路段比較直達穿越與分流；沿線不放阻斷物，另檢查交叉衝突及旁邊住宅。
**理由**：穿越方便可能帶來快速騎行與停留人群衝突。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：through_route_detour_trial＝1.3 ratio（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HILLIER84／C1：The Social Logic of Space；Bill Hillier、Julienne Hanson；1984；https://doi.org/10.1017/cbo9780511597237；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- PORTA06／C1：The Network Analysis of Urban Streets: A Primal Approach；Sergio Porta、Paolo Crucitti、Vito Latora；2006；10.1068/b32045；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 保留清楚直達通路；代價：快行與慢行衝突。
- 平行慢行支線分流；代價：繞行增加、中心人流減少。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-005｜低整合度內側安靜用途

**規則**：Low 內部路段可配置住宅或庭院，但至少保留清楚出口與無障礙到達；不要為追求低值故意斷網。
**理由**：安靜與可達都影響日常照護、外送和回家。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：quiet_use_share_trial＝70 % GFA（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HILLIER84／C1：The Social Logic of Space；Bill Hillier、Julienne Hanson；1984；https://doi.org/10.1017/cbo9780511597237；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- JACOBS61／C1：The Death and Life of Great American Cities；Jane Jacobs；1961；0679644334；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 可穿越的安靜住宅庭院；代價：需要隱私邊界。
- 有限通行的共享庭院；代價：公共滲透性較低，權利待查。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-006｜接外部高整合入口

**規則**：由周邊同模式 High 入口道路向中心提出連續路線；高差、門禁、交叉不可只靠 XY 相交當連通。
**理由**：外面的人要能真的進來並找到中心。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：entry_candidates_per_side＝2 entries（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HILLIER93／C1：Natural movement: or, configuration and attraction in urban pedestrian movement；Bill Hillier、Alan Penn、Julienne Hanson、T Grajewski、Jianming Xu；1993；10.1068/b200029；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 承接最清楚的一條主軸；代價：人流集中。
- 多入口連成網格；代價：更多界面與管理成本。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-007｜800 m 局部尺度

**規則**：800 m 用於近鄰步行與最後一段騎行比較；半徑是網路度量距離，不是保證每人能走到的時間。
**理由**：近鄰路網要回應買菜、回家和入口分布。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：radius_m＝800 m（FOUNDER／PROJECT_INSTRUCTION）
**出處**：
- HILLIER84／C1：The Social Logic of Space；Bill Hillier、Julienne Hanson；1984；https://doi.org/10.1017/cbo9780511597237；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- EWING10／C1：Travel and the Built Environment；Reid Ewing、Robert Cervero；2010；10.1080/01944361003766766；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 以局部整合度尋找生活路線；代價：不代表設施存在。
- 以目的地最短路徑補充；代價：需要可靠用途與入口。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-008｜2 km 街區連結尺度

**規則**：2 km 用於街區間步行／自行車結構與接駁診斷；車行只能在對應合法車網分析，不與行人圖混用。
**理由**：街區與公交或日常騎行目的地需要跨基地理解。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：radius_m＝2000 m（FOUNDER／PROJECT_INSTRUCTION）
**出處**：
- HILLIER84／C1：The Social Logic of Space；Bill Hillier、Julienne Hanson；1984；https://doi.org/10.1017/cbo9780511597237；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- EWING10／C1：Travel and the Built Environment；Reid Ewing、Robert Cervero；2010；10.1080/01944361003766766；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 角度整合度比較街區通達；代價：模式偏好可能不一致。
- 加入目的地距離與交通供給；代價：資料量增加。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-009｜10 km 區域尺度與邊界

**規則**：10 km 用於較廣自行車／車行結構；步行只作區域形態探索。覆蓋僅 3 km 時保留 EXPLORATORY，不宣稱穩定區域結果。
**理由**：裁切網路會改變路徑排序與區域入口判斷。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：radius_m＝10000 m（FOUNDER／PROJECT_INSTRUCTION）
**出處**：
- HILLIER84／C1：The Social Logic of Space；Bill Hillier、Julienne Hanson；1984；https://doi.org/10.1017/cbo9780511597237；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- RATTI04／C1：Space Syntax: Some Inconsistencies；Carlo Ratti；2004；10.1068/b3019；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 擴展凍結上下文後重算；代價：資料與計算增加，擴展也需穩定性比較。
- 保留局部方案評估並標 10 km 資料缺口；代價：不能下區域結論。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-010｜各交通模式分圖

**規則**：步行圖包含允許步行連結；自行車圖包含允許騎行連結；汽車圖依方向與準入建立。只限服務的路不得當一般車流捷徑。
**理由**：地圖畫得到的路不代表每種交通方式都可用。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：modes_to_compare＝3 modes（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- PUCHER08／C1：Making Cycling Irresistible: Lessons from The Netherlands, Denmark and Germany；John Pucher、Ralph Buehler；2008；10.1080/01441640701806612；VERIFIED／ABSTRACT_REVIEW。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARSHALL05／C1：Streets and Patterns；Stephen Marshall；2004；1280099763；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 分模式圖計算；代價：資料標籤與準入常不完整。
- 步行騎行共廊但維持各自通行屬性；代價：共廊衝突需管理。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-011｜目標等級百分位

**規則**：固定基準周邊樣本、模式、半徑與排名規則：High 為 p>=80，Medium 為 40<=p<80，Low 為 p<40；方案不得改分母來變熱。
**理由**：目標是可比較的相對位置，不是普適品質分類。
**層級／強度／權限**：COMMON_SENSE_ASSUMED／ASSUMED／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：high_percentile_min＝80 percentile（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）；medium_percentile_min＝40 percentile（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- PORTA06／C1：The Network Analysis of Urban Streets: A Primal Approach；Sergio Porta、Paolo Crucitti、Vito Latora；2006；10.1068/b32045；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- RATTI04／C1：Space Syntax: Some Inconsistencies；Carlo Ratti；2004；10.1068/b3019；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**本機脈絡（不計研究來源）**：FOUNDER
**可選回應**：
- 固定現況參照分布；代價：方案超出舊分布需明示。
- 另報方案內排序供診斷；代價：不能取代固定基準達成判斷。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-012｜併網重算與替代檢驗

**規則**：方案改路後重新併入同版本周邊圖；分模式與尺度重算 integration／choice，並以 primal centrality 或最短路徑檢查結論是否依賴表示法。
**理由**：讓設計者看見路網變化和方法限制，不把一種學派當唯一真理。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：sensitivity_radius_delta＝20 %（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- HILLIER84／C1：The Social Logic of Space；Bill Hillier、Julienne Hanson；1984；https://doi.org/10.1017/cbo9780511597237；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- RATTI04／C1：Space Syntax: Some Inconsistencies；Carlo Ratti；2004；10.1068/b3019；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- PORTA06／C1：The Network Analysis of Urban Streets: A Primal Approach；Sergio Porta、Paolo Crucitti、Vito Latora；2006；10.1068/b32045；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- HILLIERPENN04／C1：Rejoinder to Carlo Ratti；Bill Hillier、Alan Penn；2004；https://doi.org/10.1068/b3019a；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- BARTHELEMY11／C1：Spatial networks；Marc Barthelemy；2010；https://doi.org/10.1016/j.physrep.2010.11.002；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 用角度路徑比較；代價：角度表示可能忽略長度與寬度。
- 用 primal network 指標比較；代價：量綱與解釋不同，不能直接平均。
**爭議與地域限制**：整合度不是人流因果保證；Ratti 指出表示法與幾何資訊限制，MCA 可作替代比較；本次僅憑書目知識，尚未逐頁查證。 已查證書目與主張的查閱層級見 library；不是逐頁核驗或本基地因果結論。 英國形態／人流研究與跨城市網路方法只能提出假說；M4H 港區的門禁、產業時段、自行車與高差需另驗證。
**例外**：卡片不可替代現行法規、產權、無障礙或已接受 D1/D2。缺必要資料即回報 UNKNOWN；例外須由 Founder 明確決定並保留原結果。

### SYN-013｜批評與回應正式並列

**規則**：比較 Ratti 批評、Hillier／Penn 回應與 MCA；說明圖表示差異，不由作者聲望決定唯一方法。
**理由**：不同圖模型會保留與捨棄不同幾何及組態資訊。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：representations_to_compare_min＝2 models（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- RATTI04／C1：Space Syntax: Some Inconsistencies；Carlo Ratti；2004；10.1068/b3019；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- HILLIERPENN04／C1：Rejoinder to Carlo Ratti；Bill Hillier、Alan Penn；2004；https://doi.org/10.1068/b3019a；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- PORTA06／C1：The Network Analysis of Urban Streets: A Primal Approach；Sergio Porta、Paolo Crucitti、Vito Latora；2006；10.1068/b32045；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 使用角度 Syntax 排名；代價：對轉向組態敏感，需交代表示法。
- 使用 primal 多中心性比較；代價：可保留街段資訊，但指標定義不同。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。

### SYN-014｜空間網路替代分析

**規則**：固定輸入與尺度比較 primal 中心性與 Syntax，報告排名分歧及成本定義。
**理由**：網路科學提醒幾何成本與連接定義不能省略。
**層級／強度／權限**：ACADEMIC／THEORETICAL／CANDIDATE_ONLY／MULTI_SOURCE。
**參數**：network_cost_models_min＝2 models（ASSUMED_COMMANDER／PROPOSED_PENDING_FOUNDER）
**出處**：
- BARTHELEMY11／C1：Spatial networks；Marc Barthelemy；2010；https://doi.org/10.1016/j.physrep.2010.11.002；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- PORTA06／C1：The Network Analysis of Urban Streets: A Primal Approach；Sergio Porta、Paolo Crucitti、Vito Latora；2006；10.1068/b32045；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
- MARCUS10／C1：Spatial Capital : A Proposal for an Extension of Space Syntax into a More General Urban Morphology；Lars Marcus；2010；https://openalex.org/W643687045；VERIFIED／BIBLIOGRAPHIC_SCOPE_ONLY。文獻支持概念與比較角度；本卡具體操作是設計推導，試算值及專案約束不是文獻的普適結論。
**可選回應**：
- 以度量最短路徑比較；代價：可解釋距離，未必反映轉向認知。
- 以角度或拓樸成本比較；代價：能檢查構形，單位不能當米使用。
**爭議與地域限制**：上述做法是文獻引導的設計推導，兩種方案各有代價；不得以某一方法、作者或地域替 Founder 決定。 文獻地域與方法見 library；跨地域只能借用比較框架，數值須本地量測、校準與審核。
**例外**：法規、門禁、資料缺口、無障礙及已接受 D1/D2 優先；資料不足列 UNKNOWN，試算參數須 Founder 確認。
