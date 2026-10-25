export const conditionsTranslations: Record<string, { en: string; 'zh-TW': string }> = {
  "Exploratory": { en: "Exploratory", 'zh-TW': "探索" },
  "Notes": { en: "Notes", 'zh-TW': "備註" },
  "Source note": { en: "Source note", 'zh-TW': "來源註記" },
  "Source note {0}": { en: "Source note {0}", 'zh-TW': "來源註記 {0}" },
  "FAR denominator {0}": { en: "FAR denominator {0}", 'zh-TW': "FAR 分母 {0}" },
  "Denominator: land area": { en: "Denominator: land area", 'zh-TW': "分母：陸地面積" },
  "Denominator: exploration design area": { en: "Denominator: exploration design area", 'zh-TW': "分母：探索設計範圍面積" },
  "Denominator: unspecified (legacy)": { en: "Denominator: unspecified (legacy)", 'zh-TW': "分母：未指定（舊資料）" },
  "ConstraintSet ID": { en: "ConstraintSet ID", 'zh-TW': "條件集編號" },
  "Load draft": { en: "Load draft", 'zh-TW': "載入草稿" },
  "Site Opportunities": { "en": "Site Opportunities", "zh-TW": "基地機會" },
  "Site opportunities": { "en": "Site opportunities", "zh-TW": "基地機會" },
  "Spatial Zones": { "en": "Spatial Zones", "zh-TW": "空間分區" },
  "Switch to Spatial Zones": { "en": "Switch to Spatial Zones", "zh-TW": "切換至空間分區" },
  "Site Problems & Opportunities": { "en": "Site Problems & Opportunities", "zh-TW": "基地問題與機會" },
  "Defined Spatial Problems (Task S)": { "en": "Defined Spatial Problems (Task S)", "zh-TW": "已定義空間問題（Task S）" },
  "Candidate Opportunities (A3)": { "en": "Candidate Opportunities (A3)", "zh-TW": "候選機會建議（A3）" },
  "Go to Design Brief": { "en": "Go to Design Brief", "zh-TW": "前往設計需求" },
  "Limitation notice": { "en": "Limitation notice", "zh-TW": "限制事項說明" },
  "Geometric difference only (StudyArea minus BGT water and BAG footprints). No surface material, canopy, vacancy, ownership, or land use data. Not an approved vacancy or development zone.": {
    "en": "Geometric difference only (StudyArea minus BGT water and BAG footprints). No surface material, canopy, vacancy, ownership, or land use data. Not an approved vacancy or development zone.",
    "zh-TW": "僅為幾何差額（研究區減去 BGT 水體與 BAG 建築輪廓）。無地表材質、樹冠、空置、所有權或土地用途資料，不得視為核准之空置地或開發區。"
  },
  "PENDING_DESIGNER_CONFIRMATION": { "en": "Pending designer confirmation", "zh-TW": "待設計師確認" },
  "Suggestions and problems are exploratory observations. Selecting an opportunity creates an editable draft intent in the Design Brief and does NOT activate a constraint.": {
    "en": "Suggestions and problems are exploratory observations. Selecting an opportunity creates an editable draft intent in the Design Brief and does NOT activate a constraint.",
    "zh-TW": "建議與問題均為探索性觀察。選取機會將在設計需求中建立可編輯的草稿意向，在確認前不啟動任何限制條件。"
  },
  "No persisted opportunity suggestions are available. You can still write a designer-authored intent.": {
    "en": "No persisted opportunity suggestions are available. You can still write a designer-authored intent.",
    "zh-TW": "目前沒有已儲存的機會建議。您仍可自行編寫設計師意向。"
  },
  "No persisted suggestions are available. A self-authored intent can be saved when matching references are ready.": {
    "en": "No persisted suggestions are available. A self-authored intent can be saved when matching references are ready.",
    "zh-TW": "目前沒有已儲存的建議；相符參考就緒後，可儲存設計師自填意向。"
  },
  "Loading the persisted problem report…": { "en": "Loading the persisted problem report…", "zh-TW": "正在載入已儲存的問題報告…" },
  "NOT_READY: A matching persisted problem report is unavailable.": {
    "en": "NOT_READY: A matching persisted problem report is unavailable.",
    "zh-TW": "尚未就緒：目前沒有與研究區相符的已儲存問題報告。"
  },
  "BLOCKED: The problem report does not match the active StudyArea.": {
    "en": "BLOCKED: The problem report does not match the active StudyArea.",
    "zh-TW": "已阻擋：問題報告與目前研究區不相符。"
  },
  "NOT_READY: Matching workspace, active StudyArea, and analysis references are required.": {
    "en": "NOT_READY: Matching workspace, active StudyArea, and analysis references are required.",
    "zh-TW": "尚未就緒：需要相符的工作區、啟用研究區與分析參考。"
  },
  "BLOCKED: Workspace, StudyArea, or workspace reference does not match the current revision.": {
    "en": "BLOCKED: Workspace, StudyArea, or workspace reference does not match the current revision.",
    "zh-TW": "已阻擋：工作區、研究區或工作區參考與目前版本不符。"
  },
  "NOT_READY: A persisted SiteAnalysisBundle matching this workspace is required.": {
    "en": "NOT_READY: A persisted SiteAnalysisBundle matching this workspace is required.",
    "zh-TW": "尚未就緒：需要與此工作區相符且已儲存的 SiteAnalysisBundle。"
  },
  "BLOCKED: Matching analysis and StudyArea scope references are unavailable.": {
    "en": "BLOCKED: Matching analysis and StudyArea scope references are unavailable.",
    "zh-TW": "已阻擋：找不到相符的分析與研究區範圍參考。"
  },
  "BLOCKED: Opportunity suggestions do not match the persisted analysis references.": {
    "en": "BLOCKED: Opportunity suggestions do not match the persisted analysis references.",
    "zh-TW": "已阻擋：機會建議與已儲存的分析參考不相符。"
  },
  "BLOCKED: Opportunity suggestions have no matching persisted reference.": {
    "en": "BLOCKED: Opportunity suggestions have no matching persisted reference.",
    "zh-TW": "已阻擋：機會建議缺少相符的已儲存參考。"
  },
  "NOT_READY: Matching workspace, persisted analysis, and StudyArea scope references are required.": {
    "en": "NOT_READY: Matching workspace, persisted analysis, and StudyArea scope references are required.",
    "zh-TW": "尚未就緒：需要相符的工作區、已儲存分析與研究區範圍參考。"
  },
  "Analysis limitations": { "en": "Analysis limitations", "zh-TW": "分析限制" },
  "CRITICAL": { "en": "Critical", "zh-TW": "極高" },
  "HIGH": { "en": "High", "zh-TW": "高" },
  "MEDIUM": { "en": "Medium", "zh-TW": "中" },
  "LOW": { "en": "Low", "zh-TW": "低" },
  "UNRATED": { "en": "Unrated", "zh-TW": "未分級" },
  "CONFIRMED_BASELINE": { "en": "Confirmed baseline", "zh-TW": "已確認基線" },
  "ANALYSIS_DEFINED": { "en": "Analysis defined", "zh-TW": "已定義分析" },
  "BAG 建築用途標籤與登記狀態（BAG Use Labels & Registration Status）": {
    "en": "BAG Use Labels & Registration Status",
    "zh-TW": "BAG 建築用途標籤與登記狀態（BAG Use Labels & Registration Status）"
  },
  "OSM 座標頂點、道路線多邊形化與取樣繞行比（OSM Vertex and Route Proxies）": {
    "en": "OSM Vertex and Route Proxies",
    "zh-TW": "OSM 座標頂點、道路線多邊形化與取樣繞行比（OSM Vertex and Route Proxies）"
  },
  "邊界道路幾何交點與拓撲整合度（Boundary Intersections & Topological Integration）": {
    "en": "Boundary Intersections & Topological Integration",
    "zh-TW": "邊界道路幾何交點與拓撲整合度（Boundary Intersections & Topological Integration）"
  },
  "OSM 綠地標籤面積與多邊形間距（Mapped Green Geometry）": {
    "en": "Mapped Green Geometry",
    "zh-TW": "OSM 綠地標籤面積與多邊形間距（Mapped Green Geometry）"
  },
  "水陸幾何界面與 OSM 選定標籤路線鄰近度（Mapped Waterfront Geometry）": {
    "en": "Mapped Waterfront Geometry",
    "zh-TW": "水陸幾何界面與 OSM 選定標籤路線鄰近度（Mapped Waterfront Geometry）"
  },
  "[AI候選·待設計者確認] 非建築／非水體幾何差額（Geometric Remainder）": {
    "en": "[AI candidate · pending designer confirmation] Non-building/non-water geometric remainder",
    "zh-TW": "[AI候選·待設計者確認] 非建築／非水體幾何差額（Geometric Remainder）"
  },
  "CONNECT WATERFRONT PROMENADE": { "en": "Connect waterfront promenade", "zh-TW": "串聯水岸步道" },
  "IMPROVE NETWORK PERMEABILITY": { "en": "Improve network permeability", "zh-TW": "提升路網通透性" },
  "TEST HYPOTHESIS": { "en": "Test hypothesis", "zh-TW": "檢驗假說" },
  "REQUEST DESIGNER REVIEW": { "en": "Request designer review", "zh-TW": "請設計師審閱" },
  "AI_SUGGESTED": { "en": "AI suggested", "zh-TW": "AI 建議" },
  "DESIGNER_AUTHORED": { "en": "Designer authored", "zh-TW": "設計師自填" },
  "RULE_SUGGESTED": { "en": "Rule suggested", "zh-TW": "規則建議" },
  "Suggestions are drafts. Selecting one adds an editable intent to this brief.": {
    "en": "Suggestions are drafts. Selecting one adds an editable intent to this brief.",
    "zh-TW": "建議僅為草稿。選取後將以可編輯的意向加入此設計需求。"
  },
  "Possible measures": { "en": "Possible measures", "zh-TW": "可能措施" },
  "Needs validation": { "en": "Needs validation", "zh-TW": "待驗證項目" },
  "Conditions and counterexamples": { "en": "Conditions and counterexamples", "zh-TW": "條件與反例" },
  "Rejected in this draft": { "en": "Rejected in this draft", "zh-TW": "已在此草稿中拒絕" },
  "Rejection reason: {reason}": { "en": "Rejection reason: {reason}", "zh-TW": "拒絕理由：{reason}" },
  "Undo rejection: {id}": { "en": "Undo rejection: {id}", "zh-TW": "復原拒絕：{id}" },
  "Include in brief: {id}": { "en": "Include in brief: {id}", "zh-TW": "加入需求：{id}" },
  "Remove from brief: {id}": { "en": "Remove from brief: {id}", "zh-TW": "自需求移除：{id}" },
  "Reason to reject opportunity: {id}": { "en": "Reason to reject opportunity: {id}", "zh-TW": "拒絕機會之理由：{id}" },
  "Reject suggestion: {id}": { "en": "Reject suggestion: {id}", "zh-TW": "拒絕建議：{id}" },
  "Design brief · Draft": { "en": "Design brief · Draft", "zh-TW": "設計需求 · 草稿" },
  "Bound to workspace revision {workspaceRevision} and analysis {analysisId}.": {
    "en": "Bound to workspace revision {workspaceRevision} and analysis {analysisId}.",
    "zh-TW": "綁定至工作區版本 {workspaceRevision} 與分析 {analysisId}。"
  },
  "Intent text is saved as a draft and does not activate a constraint.": {
    "en": "Intent text is saved as a draft and does not activate a constraint.",
    "zh-TW": "意向文字僅儲存為草稿，在確認前不啟動任何限制。"
  },
  "Write an intent": { "en": "Write an intent", "zh-TW": "撰寫設計意向" },
  "New design intent": { "en": "New design intent", "zh-TW": "新增設計意向" },
  "Intent type": { "en": "Intent type", "zh-TW": "意向類型" },
  "Preference": { "en": "Preference", "zh-TW": "偏好" },
  "Required feature · draft": { "en": "Required feature · draft", "zh-TW": "必要項目 · 草稿" },
  "Avoid feature": { "en": "Avoid feature", "zh-TW": "避免項目" },
  "Add designer intent": { "en": "Add designer intent", "zh-TW": "新增設計師意向" },
  "Brief intents": { "en": "Brief intents", "zh-TW": "需求意向清單" },
  "No intents in this draft yet.": { "en": "No intents in this draft yet.", "zh-TW": "此草稿中尚無意向。" },
  "Intent text for {id}": { "en": "Intent text for {id}", "zh-TW": "{id} 的意向文字" },
  "Scope: {scopeId} · {sha256}": { "en": "Scope: {scopeId} · {sha256}", "zh-TW": "範圍：{scopeId} · {sha256}" },
  "Remove intent from this draft": { "en": "Remove intent from this draft", "zh-TW": "自此草稿移除意向" },
  "Reason for this draft revision": { "en": "Reason for this draft revision", "zh-TW": "此草稿修訂的理由" },
  "Saved draft revision {revision}": { "en": "Saved draft revision {revision}", "zh-TW": "已儲存草稿版本 {revision}" },
  "Save outcome is unknown. Retry without editing so the server can reconcile this idempotency key.": {
    "en": "Save outcome is unknown. Retry without editing so the server can reconcile this idempotency key.",
    "zh-TW": "儲存結果未知。請勿編輯直接重試，以便伺服器核對此冪等鍵。"
  },
  "Saving draft…": { "en": "Saving draft…", "zh-TW": "正在儲存草稿…" },
  "Retry draft save": { "en": "Retry draft save", "zh-TW": "重試草稿儲存" },
  "Save draft brief": { "en": "Save draft brief", "zh-TW": "儲存需求草稿" },
  "Brief save failed.": { "en": "Brief save failed.", "zh-TW": "需求儲存失敗。" },
  "Draft revision {revision} was saved, but reload failed: {detail}": {
    "en": "Draft revision {revision} was saved, but reload failed: {detail}",
    "zh-TW": "草稿版本 {revision} 已儲存，但重新載入失敗：{detail}"
  },
  "Default StudyArea scope reference is not available. Please ensure StudyArea is loaded.": {
    "en": "Default StudyArea scope reference is not available. Please ensure StudyArea is loaded.",
    "zh-TW": "預設研究區範圍參考無法取得。請確保研究區已載入。"
  },
  "Functional Monoculture": { "en": "Functional Monoculture", "zh-TW": "單一機能" },
  "Spatial Fragmentation": { "en": "Spatial Fragmentation", "zh-TW": "空間斷裂" },
  "Sociospatial Isolation": { "en": "Sociospatial Isolation", "zh-TW": "社會空間孤立" },
  "Ecological Disconnection": { "en": "Ecological Disconnection", "zh-TW": "生態網絡中斷" },
  "Waterfront Inaccessibility": { "en": "Waterfront Inaccessibility", "zh-TW": "水岸難以抵達" },
  "Unclassified Residual Ground": { "en": "Unclassified Residual Ground", "zh-TW": "未分類幾何差額地面" },
  "CONDITIONAL HYPOTHESIS": { "en": "CONDITIONAL HYPOTHESIS", "zh-TW": "條件假說" },
  "OBSERVED PROBLEM": { "en": "OBSERVED PROBLEM", "zh-TW": "觀察問題" },
  "DESIGN PREFERENCE": { "en": "DESIGN PREFERENCE", "zh-TW": "設計偏好" },
  "REQUIRED FEATURE": { "en": "REQUIRED FEATURE", "zh-TW": "必要項目" },
  "AVOID FEATURE": { "en": "AVOID FEATURE", "zh-TW": "避免項目" },
  "PREFERENCE": { "en": "PREFERENCE", "zh-TW": "偏好" },
  "Buildings (": {
    "en": "Buildings (",
    "zh-TW": "建築物（"
  },
  "Roads (": {
    "en": "Roads (",
    "zh-TW": "道路（"
  },
  "BAG Buildings Dispositions": {
    "en": "BAG Buildings Dispositions",
    "zh-TW": "BAG 建築物處置"
  },
  "OSM Road Dispositions": {
    "en": "OSM Road Dispositions",
    "zh-TW": "OSM 道路處置"
  },
  "Total": {
    "en": "Total",
    "zh-TW": "總計"
  },
  "決策對應舊版本 (rev {0})": {
    "en": "Decision applies to an earlier revision ({0})",
    "zh-TW": "決策對應舊版本 (rev {0})"
  },
  "第 1 天決策已確認 ({0})": {
    "en": "Day 1 decision confirmed ({0})",
    "zh-TW": "第 1 天決策已確認 ({0})"
  },
  "Preserve (Lock feature)": {
    "en": "Preserve (Lock feature)",
    "zh-TW": "保留（鎖定要素）"
  },
  "Editable (Scenario overlay)": {
    "en": "Editable (Scenario overlay)",
    "zh-TW": "可編輯（方案疊加）"
  },
  "Undecided": {
    "en": "Undecided",
    "zh-TW": "未決"
  },
  "Local annotation · draft only": {
    "en": "Local annotation · draft only",
    "zh-TW": "本地註記・僅為草稿"
  },
  "Annotation for {0}": {
    "en": "Annotation for {0}",
    "zh-TW": "{0} 的註記"
  },
  "Local note for this feature (draft only)": {
    "en": "Local note for this feature (draft only)",
    "zh-TW": "此要素的本地註記（僅為草稿）"
  },
  "building": {
    "en": "building",
    "zh-TW": "建築物"
  },
  "road": {
    "en": "road",
    "zh-TW": "道路"
  },
  "feature": {
    "en": "feature",
    "zh-TW": "要素"
  },
  "s": {
    "en": "s",
    "zh-TW": ""
  },
  "selected": {
    "en": "selected",
    "zh-TW": "已選取"
  },
  "Selected": {
    "en": "Selected",
    "zh-TW": "選取"
  },
  "Assign all": {
    "en": "Assign all",
    "zh-TW": "全部設定"
  },
  "buildings": {
    "en": "buildings",
    "zh-TW": "建築物"
  },
  "roads": {
    "en": "roads",
    "zh-TW": "道路"
  },
  "All Preserve": {
    "en": "All Preserve",
    "zh-TW": "全部保留"
  },
  "All Editable": {
    "en": "All Editable",
    "zh-TW": "全部可編輯"
  },
  "Reset": {
    "en": "Reset",
    "zh-TW": "重設"
  },
  "Unlock preserved feature?": {
    "en": "Unlock preserved feature?",
    "zh-TW": "解鎖保留要素？"
  },
  "Unlock preserved features?": {
    "en": "Unlock preserved features?",
    "zh-TW": "解鎖保留要素？"
  },
  "This will change the feature to {0} in this draft.": {
    "en": "This will change the feature to {0} in this draft.",
    "zh-TW": "這會在此草稿中將要素改為 {0}。"
  },
  "This will unlock {0} preserved feature{1} and apply the selected batch change in this draft.": {
    "en": "This will unlock {0} preserved feature{1} and apply the selected batch change in this draft.",
    "zh-TW": "這會解鎖 {0} 個保留要素{1}，並在草稿中套用批次變更。"
  },
  "The source data remains unchanged.": {
    "en": "The source data remains unchanged.",
    "zh-TW": "來源資料維持不變。"
  },
  "Cancel": {
    "en": "Cancel",
    "zh-TW": "取消"
  },
  "Unlock and set {0}": {
    "en": "Unlock and set {0}",
    "zh-TW": "解鎖並設為 {0}"
  },
  "Unlock and continue": {
    "en": "Unlock and continue",
    "zh-TW": "解鎖並繼續"
  },
  "Spatial Brief & Zoning (CP4-4)": {
    "en": "Spatial Brief & Zoning (CP4-4)",
    "zh-TW": "空間需求與分區（CP4-4）"
  },
  "Add program and open-space demands; classify hard constraints separately from preferences.": {
    "en": "Add program and open-space demands; classify hard constraints separately from preferences.",
    "zh-TW": "新增機能與開放空間需求；分別列出硬性條件與偏好。"
  },
  "Draft Status": {
    "en": "Draft Status",
    "zh-TW": "草稿狀態"
  },
  ": Program, open-space demands, hard constraints, and preferences remain non-binding until explicit Human Decision adoption.": {
    "en": ": Program, open-space demands, hard constraints, and preferences remain non-binding until explicit Human Decision adoption.",
    "zh-TW": "：機能、開放空間需求、硬性條件與偏好，在明確人工決策採納前不具約束力。"
  },
  "對應舊版本": {
    "en": "Earlier revision",
    "zh-TW": "對應舊版本"
  },
  ": 決策": {
    "en": ": Decision",
    "zh-TW": ": 決策"
  },
  "綁定於 revision": {
    "en": "bound to revision",
    "zh-TW": "綁定於 revision"
  },
  "。目前工作區存在新變更，請於調整完成並同步後重新確認決策。": {
    "en": ". The workspace has new changes. Complete and sync edits before confirming the decision again.",
    "zh-TW": "。目前工作區存在新變更，請於調整完成並同步後重新確認決策。"
  },
  "決策已確認": {
    "en": "Decision confirmed",
    "zh-TW": "決策已確認"
  },
  ": 第 1 天決策": {
    "en": ": Day 1 decision",
    "zh-TW": ": 第 1 天決策"
  },
  "）已綁定至此工作區版本。": {
    "en": ") is bound to this workspace revision.",
    "zh-TW": "）已綁定至此工作區版本。"
  },
  "Exploration Design Area": {
    "en": "Exploration Design Area",
    "zh-TW": "探索設計範圍"
  },
  "A separate conceptual denominator inside the exploratory StudyArea. This is not a legal design boundary, property limit, or zoning envelope.": {
    "en": "A separate conceptual denominator inside the exploratory StudyArea. This is not a legal design boundary, property limit, or zoning envelope.",
    "zh-TW": "探索研究區內的獨立概念面積基準，不屬於法定設計邊界、產權界線或分區範圍。"
  },
  "Draft ·": {
    "en": "Draft ·",
    "zh-TW": "草稿・"
  },
  "m² ·": {
    "en": "m² ·",
    "zh-TW": "m² ·"
  },
  "· revision": {
    "en": "· revision",
    "zh-TW": "・版本"
  },
  "No Exploration Design Area has been saved.": {
    "en": "No Exploration Design Area has been saved.",
    "zh-TW": "尚未儲存探索設計範圍。"
  },
  "Finished polygon ·": {
    "en": "Finished polygon ·",
    "zh-TW": "已完成多邊形・"
  },
  "m²": {
    "en": "m²",
    "zh-TW": "m²"
  },
  "Preview clipped design area": {
    "en": "Preview clipped design area",
    "zh-TW": "預覽裁切設計範圍"
  },
  "Preparing preview…": {
    "en": "Preparing preview…",
    "zh-TW": "準備預覽中…"
  },
  "Preview boundary": {
    "en": "Preview boundary",
    "zh-TW": "預覽邊界"
  },
  "Clipped to StudyArea": {
    "en": "Clipped to StudyArea",
    "zh-TW": "已裁切至研究區"
  },
  "Inside StudyArea · unchanged": {
    "en": "Inside StudyArea · unchanged",
    "zh-TW": "位於研究區內・未變更"
  },
  "Confirm and save design area": {
    "en": "Confirm and save design area",
    "zh-TW": "確認並儲存設計範圍"
  },
  "Confirm and save": {
    "en": "Confirm and save",
    "zh-TW": "確認並儲存"
  },
  "Cancel design area preview": {
    "en": "Cancel design area preview",
    "zh-TW": "取消設計範圍預覽"
  },
  "Cancel preview": {
    "en": "Cancel preview",
    "zh-TW": "取消預覽"
  },
  "Use entire StudyArea": {
    "en": "Use entire StudyArea",
    "zh-TW": "使用整個研究區"
  },
  "Draw replacement outline": {
    "en": "Draw replacement outline",
    "zh-TW": "繪製替代輪廓"
  },
  "Draw exploration design area": {
    "en": "Draw exploration design area",
    "zh-TW": "繪製探索設計範圍"
  },
  "Zone Name (e.g. Keilehaven Maker Hub)": {
    "en": "Zone Name (e.g. Keilehaven Maker Hub)",
    "zh-TW": "分區名稱（例如 Keilehaven 創客中心）"
  },
  "Mixed-Use Innovation Hub": {
    "en": "Mixed-Use Innovation Hub",
    "zh-TW": "混合使用創新中心"
  },
  "Creative Production / Maker": {
    "en": "Creative Production / Maker",
    "zh-TW": "創意生產／創客"
  },
  "Harborfront Public Realm": {
    "en": "Harborfront Public Realm",
    "zh-TW": "港灣公共空間"
  },
  "Water-Sensitive Eco-Buffer": {
    "en": "Water-Sensitive Eco-Buffer",
    "zh-TW": "水敏感生態緩衝區"
  },
  "Circular Tech Incubator": {
    "en": "Circular Tech Incubator",
    "zh-TW": "循環科技育成中心"
  },
  "Author": {
    "en": "Author",
    "zh-TW": "作者"
  },
  "Original design text or intention": {
    "en": "Original design text or intention",
    "zh-TW": "原始設計文字或意圖"
  },
  "Original design text / intention...": {
    "en": "Original design text / intention...",
    "zh-TW": "原始設計文字／意圖…"
  },
  "Additional program demands (draft; comma-separated)": {
    "en": "Additional program demands (draft; comma-separated)",
    "zh-TW": "額外機能需求（草稿；逗號分隔）"
  },
  "e.g. fabrication workshops, shared tool library": {
    "en": "e.g. fabrication workshops, shared tool library",
    "zh-TW": "例如製作工坊、共享工具庫"
  },
  "Open-space demands (draft; comma-separated)": {
    "en": "Open-space demands (draft; comma-separated)",
    "zh-TW": "開放空間需求（草稿；逗號分隔）"
  },
  "e.g. public courtyard, shaded route": {
    "en": "e.g. public courtyard, shaded route",
    "zh-TW": "例如公共庭院、遮蔭路徑"
  },
  "Hard constraints (draft; not active)": {
    "en": "Hard constraints (draft; not active)",
    "zh-TW": "硬性條件（草稿；未啟用）"
  },
  "Hard constraints, draft and not active": {
    "en": "Hard constraints, draft and not active",
    "zh-TW": "硬性條件，草稿且未啟用"
  },
  "e.g. preserve tree row, keep quay access": {
    "en": "e.g. preserve tree row, keep quay access",
    "zh-TW": "例如保留樹列、維持碼頭通道"
  },
  "Preferences (non-binding draft)": {
    "en": "Preferences (non-binding draft)",
    "zh-TW": "偏好（不具約束力的草稿）"
  },
  "e.g. reuse existing structures, active ground floors": {
    "en": "e.g. reuse existing structures, active ground floors",
    "zh-TW": "例如再利用既有結構、活躍地面層"
  },
  "Target FAR (draft ratio)": {
    "en": "Target FAR (draft ratio)",
    "zh-TW": "目標容積率（草稿比率）"
  },
  "Target FAR": {
    "en": "Target FAR",
    "zh-TW": "目標容積率"
  },
  "Maximum height (draft metres)": {
    "en": "Maximum height (draft metres)",
    "zh-TW": "最大高度（草稿；公尺）"
  },
  "Max Height (m)": {
    "en": "Max Height (m)",
    "zh-TW": "最大高度（公尺）"
  },
  "FAR and height are non-binding draft targets; enter finite, non-negative numbers. Leave blank to unset an optional target.": {
    "en": "FAR and height are non-binding draft targets; enter finite, non-negative numbers. Leave blank to unset an optional target.",
    "zh-TW": "容積率與高度為不具約束力的草稿目標；請輸入有限的非負數。留白可取消選填目標。"
  },
  "Editing brief text and parameters only; the saved polygon boundary will be retained.": {
    "en": "Editing brief text and parameters only; the saved polygon boundary will be retained.",
    "zh-TW": "僅編輯需求文字與參數；已儲存多邊形邊界將保留。"
  },
  "Polygon Sketched ({0} pts)": {
    "en": "Polygon Sketched ({0} pts)",
    "zh-TW": "已繪製多邊形（{0} 個點）"
  },
  "Click on map to place vertices...": {
    "en": "Click on map to place vertices...",
    "zh-TW": "點擊地圖以放置頂點…"
  },
  "No polygon sketched yet": {
    "en": "No polygon sketched yet",
    "zh-TW": "尚未繪製多邊形"
  },
  "Calculated Area:": {
    "en": "Calculated Area:",
    "zh-TW": "計算面積："
  },
  "Clear": {
    "en": "Clear",
    "zh-TW": "清除"
  },
  "Drawing...": {
    "en": "Drawing...",
    "zh-TW": "繪製中…"
  },
  "Draw on Map": {
    "en": "Draw on Map",
    "zh-TW": "在地圖繪製"
  },
  "Save Draft Zone": {
    "en": "Save Draft Zone",
    "zh-TW": "儲存分區草稿"
  },
  "Add Draft Zone": {
    "en": "Add Draft Zone",
    "zh-TW": "新增分區草稿"
  },
  "Cancel edit": {
    "en": "Cancel edit",
    "zh-TW": "取消編輯"
  },
  "Load Keilehaven preset boundary for testing": {
    "en": "Load Keilehaven preset boundary for testing",
    "zh-TW": "載入 Keilehaven 預設測試邊界"
  },
  "Preset": {
    "en": "Preset",
    "zh-TW": "預設"
  },
  "No draft spatial zones added yet.": {
    "en": "No draft spatial zones added yet.",
    "zh-TW": "尚未新增空間分區草稿。"
  },
  "· author:": {
    "en": "· author:",
    "zh-TW": "・作者："
  },
  "designer": {
    "en": "designer",
    "zh-TW": "設計者"
  },
  "Edit zone {0}": {
    "en": "Edit zone {0}",
    "zh-TW": "編輯分區 {0}"
  },
  "Remove zone {0}": {
    "en": "Remove zone {0}",
    "zh-TW": "移除分區 {0}"
  },
  "Program demands (draft):": {
    "en": "Program demands (draft):",
    "zh-TW": "機能需求（草稿）："
  },
  "Open-space demands (draft):": {
    "en": "Open-space demands (draft):",
    "zh-TW": "開放空間需求（草稿）："
  },
  "Hard constraints (draft; inactive)": {
    "en": "Hard constraints (draft; inactive)",
    "zh-TW": "硬性條件（草稿；未啟用）"
  },
  "FAR:": {
    "en": "FAR:",
    "zh-TW": "容積率："
  },
  "| H:": {
    "en": "| H:",
    "zh-TW": "｜高度："
  },
  "{0}m": {
    "en": "{0}m",
    "zh-TW": "{0}m"
  },
  "Space Syntax Layers": {
    "en": "Space Syntax Layers",
    "zh-TW": "空間句法圖層"
  },
  "EXPLORATORY OUTPUT": {
    "en": "EXPLORATORY OUTPUT",
    "zh-TW": "探索性輸出"
  },
  "NO COMPUTED RESULT": {
    "en": "NO COMPUTED RESULT",
    "zh-TW": "無計算結果"
  },
  "Computed outputs are exploratory. Each layer below shows its calculation status and source or method limitations.": {
    "en": "Computed outputs are exploratory. Each layer below shows its calculation status and source or method limitations.",
    "zh-TW": "計算輸出僅供探索。下列各圖層顯示計算狀態以及來源或方法限制。"
  },
  "Unavailable: {0}. Planned layers do not supply values.": {
    "en": "Unavailable: {0}. Planned layers do not supply values.",
    "zh-TW": "無法使用：{0}。規劃圖層不提供數值。"
  },
  "檔案回退：已驗證的候選檔，尚未持久化至資料庫。": {
    "en": "File fallback: verified candidate file, not yet persisted to the database.",
    "zh-TW": "檔案回退：已驗證的候選檔，尚未持久化至資料庫。"
  },
  "資料來源：SQLite 持久化記錄。": {
    "en": "Source: persisted SQLite record.",
    "zh-TW": "資料來源：SQLite 持久化記錄。"
  },
  "資料來源尚未標示。": {
    "en": "Source is not identified.",
    "zh-TW": "資料來源尚未標示。"
  },
  "EXPLORATORY ONLY.": {
    "en": "EXPLORATORY ONLY.",
    "zh-TW": "僅供探索。"
  },
  "Computed layers are not approved design conclusions. Layers without a completed calculation have no metric values; see their individual readiness and limitations below.": {
    "en": "Computed layers are not approved design conclusions. Layers without a completed calculation have no metric values; see their individual readiness and limitations below.",
    "zh-TW": "計算圖層不是已核准設計結論。未完成計算的圖層沒有指標數值；請參閱各圖層的就緒狀態與限制。"
  },
  "Download explicitly exploratory 800 m figure (SVG)": {
    "en": "Download explicitly exploratory 800 m figure (SVG)",
    "zh-TW": "下載明確標示探索性的 800 公尺圖（SVG）"
  },
  "No Rotterdam Syntax layer is currently verified against the active spatial-r01 source package. Planned radii do not constitute computed or validated layers.": {
    "en": "No Rotterdam Syntax layer is currently verified against the active spatial-r01 source package. Planned radii do not constitute computed or validated layers.",
    "zh-TW": "目前沒有 Rotterdam 空間句法圖層通過現行 spatial-r01 來源套件驗證。規劃半徑不代表已計算或已驗證圖層。"
  },
  "None (Base Map Only)": {
    "en": "None (Base Map Only)",
    "zh-TW": "無（僅底圖）"
  },
  "R=": {
    "en": "R=",
    "zh-TW": "R="
  },
  "m ·": {
    "en": "m ·",
    "zh-TW": "m ·"
  },
  "Status:": {
    "en": "Status:",
    "zh-TW": "狀態："
  },
  "Computed summary covers {0} segments.": {
    "en": "Computed summary covers {0} segments.",
    "zh-TW": "計算摘要涵蓋 {0} 條路段。"
  },
  "No metric values available; missing is unavailable, not zero.": {
    "en": "No metric values available; missing is unavailable, not zero.",
    "zh-TW": "無指標數值；缺失表示無法使用，不代表零。"
  },
  "Segment geometry is unavailable, so this result cannot be drawn as a map overlay.": {
    "en": "Segment geometry is unavailable, so this result cannot be drawn as a map overlay.",
    "zh-TW": "路段幾何無法使用，因此此結果無法繪製為地圖疊加。"
  },
  "Planned Syntax results": {
    "en": "Planned Syntax results",
    "zh-TW": "規劃空間句法結果"
  },
  "Planned Syntax result readiness": {
    "en": "Planned Syntax result readiness",
    "zh-TW": "規劃空間句法結果就緒狀態"
  },
  "Verified result layer matched by its persisted layer ID, radius, and metric.": {
    "en": "Verified result layer matched by its persisted layer ID, radius, and metric.",
    "zh-TW": "已驗證結果圖層與持久化圖層編號、半徑和指標一致。"
  },
  "Persisted result layer is missing.": {
    "en": "Persisted result layer is missing.",
    "zh-TW": "缺少持久化結果圖層。"
  },
  "Metric legend for {0}": {
    "en": "Metric legend for {0}",
    "zh-TW": "{0} 的指標圖例"
  },
  "METRIC LEGEND:": {
    "en": "METRIC LEGEND:",
    "zh-TW": "指標圖例："
  },
  "Uncomputed / Excluded": {
    "en": "Uncomputed / Excluded",
    "zh-TW": "未計算／已排除"
  },
  "gray dashed line": {
    "en": "gray dashed line",
    "zh-TW": "灰色虛線"
  },
  "Min:": {
    "en": "Min:",
    "zh-TW": "最小："
  },
  "Mean:": {
    "en": "Mean:",
    "zh-TW": "平均："
  },
  "Max:": {
    "en": "Max:",
    "zh-TW": "最大："
  },
  "Classifier breaks": {
    "en": "Classifier breaks",
    "zh-TW": "分類分界"
  },
  "Breaks: ": {
    "en": "Breaks: ",
    "zh-TW": "分界："
  },
  "Classifier breaks unavailable.": {
    "en": "Classifier breaks unavailable.",
    "zh-TW": "分類分界無法使用。"
  },
  "Formula:": {
    "en": "Formula:",
    "zh-TW": "公式："
  },
  "unrecorded": {
    "en": "unrecorded",
    "zh-TW": "未記錄"
  },
  "· Source manifest:": {
    "en": "· Source manifest:",
    "zh-TW": "・來源清單："
  },
  "unavailable": {
    "en": "unavailable",
    "zh-TW": "無法使用"
  },
  "· Result:": {
    "en": "· Result:",
    "zh-TW": "・結果："
  },
  "Constraint set": {
    "en": "Constraint set",
    "zh-TW": "條件集"
  },
  "Values remain a draft until a designer approves this exact version and hash.": {
    "en": "Values remain a draft until a designer approves this exact version and hash.",
    "zh-TW": "在設計者核准此版本與雜湊之前，數值維持草稿狀態。"
  },
  "Parameter": {
    "en": "Parameter",
    "zh-TW": "參數"
  },
  "Value": {
    "en": "Value",
    "zh-TW": "數值"
  },
  "Unit": {
    "en": "Unit",
    "zh-TW": "單位"
  },
  "Scope": {
    "en": "Scope",
    "zh-TW": "範圍"
  },
  "Type": {
    "en": "Type",
    "zh-TW": "類型"
  },
  "Source": {
    "en": "Source",
    "zh-TW": "來源"
  },
  "Overall FAR cap": {
    "en": "Overall FAR cap",
    "zh-TW": "整體容積率上限"
  },
  "Coverage ratio cap": {
    "en": "Coverage ratio cap",
    "zh-TW": "建蔽率上限"
  },
  "Maximum height (m)": {
    "en": "Maximum height (m)",
    "zh-TW": "最大高度（公尺）"
  },
  "First-floor height (m)": {
    "en": "First-floor height (m)",
    "zh-TW": "首層高度（公尺）"
  },
  "Standard-floor height (m)": {
    "en": "Standard-floor height (m)",
    "zh-TW": "標準層高度（公尺）"
  },
  "Rotation step (degrees)": {
    "en": "Rotation step (degrees)",
    "zh-TW": "旋轉步長（度）"
  },
  "{0} type": {
    "en": "{0} type",
    "zh-TW": "{0} 類型"
  },
  "Choose": {
    "en": "Choose",
    "zh-TW": "選擇"
  },
  "Hard": {
    "en": "Hard",
    "zh-TW": "硬性"
  },
  "Pending": {
    "en": "Pending",
    "zh-TW": "待處理"
  },
  "Pending HumanDecision": {
    "en": "Pending HumanDecision",
    "zh-TW": "待人工決策"
  },
  "Road width": {
    "en": "Road width",
    "zh-TW": "道路寬度"
  },
  "Road hierarchy": {
    "en": "Road hierarchy",
    "zh-TW": "道路層級"
  },
  "Designer-defined label": {
    "en": "Designer-defined label",
    "zh-TW": "設計者定義標籤"
  },
  "Road width (m)": {
    "en": "Road width (m)",
    "zh-TW": "道路寬度（公尺）"
  },
  "m": {
    "en": "m",
    "zh-TW": "m"
  },
  "road:{0}": {
    "en": "road:{0}",
    "zh-TW": "道路：{0}"
  },
  "road:<hierarchy>": {
    "en": "road:<hierarchy>",
    "zh-TW": "道路：<層級>"
  },
  "Road width {0} type": {
    "en": "Road width {0} type",
    "zh-TW": "道路寬度 {0} 類型"
  },
  "Zone FAR": {
    "en": "Zone FAR",
    "zh-TW": "分區容積率"
  },
  "Zone ID": {
    "en": "Zone ID",
    "zh-TW": "分區編號"
  },
  "Zone FAR cap": {
    "en": "Zone FAR cap",
    "zh-TW": "分區容積率上限"
  },
  "ratio": {
    "en": "ratio",
    "zh-TW": "比率"
  },
  "zone:{0}": {
    "en": "zone:{0}",
    "zh-TW": "分區：{0}"
  },
  "zone:<id>": {
    "en": "zone:<id>",
    "zh-TW": "分區：<編號>"
  },
  "Zone FAR {0} type": {
    "en": "Zone FAR {0} type",
    "zh-TW": "分區容積率 {0} 類型"
  },
  "Zone allocation policy": {
    "en": "Zone allocation policy",
    "zh-TW": "分區分配規則"
  },
  "No overlap rule": {
    "en": "No overlap rule",
    "zh-TW": "無重疊規則"
  },
  "Priority (workspace zone order)": {
    "en": "Priority (workspace zone order)",
    "zh-TW": "優先順序（工作區分區順序）"
  },
  "Add road hierarchy": {
    "en": "Add road hierarchy",
    "zh-TW": "新增道路層級"
  },
  "Add zone FAR": {
    "en": "Add zone FAR",
    "zh-TW": "新增分區容積率"
  },
  "Saving…": {
    "en": "Saving…",
    "zh-TW": "儲存中…"
  },
  "Save draft": {
    "en": "Save draft",
    "zh-TW": "儲存草稿"
  },
  "Version": {
    "en": "Version",
    "zh-TW": "版本"
  },
  "Approval hash:": {
    "en": "Approval hash:",
    "zh-TW": "核准雜湊："
  },
  "Confirm and activate": {
    "en": "Confirm and activate",
    "zh-TW": "確認並啟用"
  },
  "Confirm human decision": {
    "en": "Confirm human decision",
    "zh-TW": "確認人工決策"
  },
  "Target and revision to be recorded in the design ledger": {
    "en": "Target and revision to be recorded in the design ledger",
    "zh-TW": "將記錄於設計紀錄的目標與版本"
  },
  "Close decision dialog": {
    "en": "Close decision dialog",
    "zh-TW": "關閉決策對話框"
  },
  "Target": {
    "en": "Target",
    "zh-TW": "目標"
  },
  "Action": {
    "en": "Action",
    "zh-TW": "動作"
  },
  "Status": {
    "en": "Status",
    "zh-TW": "狀態"
  },
  "Target hash": {
    "en": "Target hash",
    "zh-TW": "目標雜湊"
  },
  "Missing hash — decision blocked": {
    "en": "Missing hash — decision blocked",
    "zh-TW": "缺少雜湊 — 決策已封鎖"
  },
  "第 1 天決策內容摘要": {
    "en": "Day 1 decision summary",
    "zh-TW": "第 1 天決策內容摘要"
  },
  "設計範圍 (Exploration Design Area)": {
    "en": "Exploration Design Area",
    "zh-TW": "設計範圍 (Exploration Design Area)"
  },
  "面積：": {
    "en": "Area:",
    "zh-TW": "面積："
  },
  "幾何 Hash：": {
    "en": "Geometry hash:",
    "zh-TW": "幾何 Hash："
  },
  "無": {
    "en": "None",
    "zh-TW": "無"
  },
  "本版本未包含自訂設計範圍（使用全區 StudyArea）。": {
    "en": "This revision has no custom design area (the entire StudyArea is used).",
    "zh-TW": "本版本未包含自訂設計範圍（使用全區 StudyArea）。"
  },
  "要素處置 (Feature Dispositions)": {
    "en": "Feature dispositions",
    "zh-TW": "要素處置 (Feature Dispositions)"
  },
  "建築物處置 (": {
    "en": "Building dispositions (",
    "zh-TW": "建築物處置 ("
  },
  "棟)": {
    "en": "buildings)",
    "zh-TW": "棟)"
  },
  "保留:": {
    "en": "Preserve:",
    "zh-TW": "保留:"
  },
  "可改:": {
    "en": "Editable:",
    "zh-TW": "可改:"
  },
  "未決:": {
    "en": "Undecided:",
    "zh-TW": "未決:"
  },
  "檢視保留建築清單 (": {
    "en": "View preserved buildings (",
    "zh-TW": "檢視保留建築清單 ("
  },
  "檢視可改建築清單 (": {
    "en": "View editable buildings (",
    "zh-TW": "檢視可改建築清單 ("
  },
  "檢視未決建築清單 (": {
    "en": "View undecided buildings (",
    "zh-TW": "檢視未決建築清單 ("
  },
  "道路路段處置 (": {
    "en": "Road segment dispositions (",
    "zh-TW": "道路路段處置 ("
  },
  "條)": {
    "en": "segments)",
    "zh-TW": "條)"
  },
  "檢視保留道路清單 (": {
    "en": "View preserved roads (",
    "zh-TW": "檢視保留道路清單 ("
  },
  "檢視可改道路清單 (": {
    "en": "View editable roads (",
    "zh-TW": "檢視可改道路清單 ("
  },
  "檢視未決道路清單 (": {
    "en": "View undecided roads (",
    "zh-TW": "檢視未決道路清單 ("
  },
  "分區清單與條件 (Spatial Zones & Constraints)": {
    "en": "Spatial zones and constraints",
    "zh-TW": "分區清單與條件 (Spatial Zones & Constraints)"
  },
  "區": {
    "en": "zones",
    "zh-TW": "區"
  },
  "限高:": {
    "en": "Height cap:",
    "zh-TW": "限高:"
  },
  "硬性條件：": {
    "en": "Hard constraints:",
    "zh-TW": "硬性條件："
  },
  "偏好條件：": {
    "en": "Preferences:",
    "zh-TW": "偏好條件："
  },
  "目前尚無定義空間分區。": {
    "en": "No spatial zones have been defined.",
    "zh-TW": "目前尚無定義空間分區。"
  },
  "未保存的變更警告：": {
    "en": "Unsaved changes warning:",
    "zh-TW": "未保存的變更警告："
  },
  "目前工作區存在未保存的草稿變更。必須先點擊「Sync Workspace」儲存為正式版本後，才能對該版本確認第 1 天決策。": {
    "en": "The workspace has unsaved draft changes. Use Sync Workspace to save a revision before confirming its Day 1 decision.",
    "zh-TW": "目前工作區存在未保存的草稿變更。必須先點擊「Sync Workspace」儲存為正式版本後，才能對該版本確認第 1 天決策。"
  },
  "Reason": {
    "en": "Reason",
    "zh-TW": "理由"
  },
  "Decision key": {
    "en": "Decision key",
    "zh-TW": "決策密語"
  },
  "The key is sent only with this decision and is not saved in browser storage.": {
    "en": "The key is sent only with this decision and is not saved in browser storage.",
    "zh-TW": "密語僅隨本次決策送出，不儲存於瀏覽器。"
  },
  "未保存的變更存在時不得送出決策": {
    "en": "Decisions cannot be submitted with unsaved changes",
    "zh-TW": "未保存的變更存在時不得送出決策"
  },
  "Submitting…": {
    "en": "Submitting…",
    "zh-TW": "送出中…"
  },
  "Confirm decision": {
    "en": "Confirm decision",
    "zh-TW": "確認決策"
  },
  "Please enter a decision reason.": {
    "en": "Please enter a decision reason.",
    "zh-TW": "請輸入決策理由。"
  },
  "Please enter the decision key.": {
    "en": "Please enter the decision key.",
    "zh-TW": "請輸入決策密語。"
  },
  "Workspace Synchronization & Audit Diff": {
    "en": "Workspace Synchronization & Audit Diff",
    "zh-TW": "工作區同步與審核差異"
  },
  "Target:": {
    "en": "Target:",
    "zh-TW": "目標："
  },
  "POST /api/v1/workspaces/sync": {
    "en": "POST /api/v1/workspaces/sync",
    "zh-TW": "POST /api/v1/workspaces/sync"
  },
  "Close synchronization dialog": {
    "en": "Close synchronization dialog",
    "zh-TW": "關閉同步對話框"
  },
  "Current State": {
    "en": "Current State",
    "zh-TW": "目前狀態"
  },
  "Revision {0}": {
    "en": "Revision {0}",
    "zh-TW": "版本 {0}"
  },
  "NO SERVER REVISION": {
    "en": "NO SERVER REVISION",
    "zh-TW": "無伺服器版本"
  },
  "Target Commit": {
    "en": "Target Commit",
    "zh-TW": "目標提交"
  },
  "Revision": {
    "en": "Revision",
    "zh-TW": "版本"
  },
  "Server Synchronization Failed": {
    "en": "Server Synchronization Failed",
    "zh-TW": "伺服器同步失敗"
  },
  "Reload Server State": {
    "en": "Reload Server State",
    "zh-TW": "重新載入伺服器狀態"
  },
  "Building Disposition Changes (": {
    "en": "Building Disposition Changes (",
    "zh-TW": "建築物處置變更（"
  },
  "No building disposition modifications.": {
    "en": "No building disposition modifications.",
    "zh-TW": "無建築物處置變更。"
  },
  "Road Disposition Changes (": {
    "en": "Road Disposition Changes (",
    "zh-TW": "道路處置變更（"
  },
  "No road disposition modifications.": {
    "en": "No road disposition modifications.",
    "zh-TW": "無道路處置變更。"
  },
  "Spatial Brief Draft Zones (": {
    "en": "Spatial Brief Draft Zones (",
    "zh-TW": "空間需求分區草稿（"
  },
  "No active brief zones configured.": {
    "en": "No active brief zones configured.",
    "zh-TW": "尚未設定需求分區。"
  },
  "disposition diffs ·": {
    "en": "disposition diffs ·",
    "zh-TW": "處置差異・"
  },
  "zones": {
    "en": "zones",
    "zh-TW": "分區"
  },
  "Committing...": {
    "en": "Committing...",
    "zh-TW": "提交中…"
  },
  "Commit & Sync": {
    "en": "Commit & Sync",
    "zh-TW": "提交並同步"
  },
  "Ariadne": {
    "en": "Ariadne",
    "zh-TW": "Ariadne"
  },
  "Rotterdam M4H Pilot": {
    "en": "Rotterdam M4H Pilot",
    "zh-TW": "Rotterdam M4H 試點"
  },
  "Project ID:": {
    "en": "Project ID:",
    "zh-TW": "專案編號："
  },
  "not loaded": {
    "en": "not loaded",
    "zh-TW": "尚未載入"
  },
  "StudyArea ID:": {
    "en": "StudyArea ID:",
    "zh-TW": "研究區編號："
  },
  "EPSG:28992": {
    "en": "EPSG:28992",
    "zh-TW": "EPSG:28992"
  },
  "Workspace rev": {
    "en": "Workspace rev",
    "zh-TW": "工作區版本"
  },
  "StudyArea rev": {
    "en": "StudyArea rev",
    "zh-TW": "研究區版本"
  },
  "StudyArea status:": {
    "en": "StudyArea status:",
    "zh-TW": "研究區狀態："
  },
  "AUTHORITY_UNAVAILABLE": {
    "en": "Authority unavailable",
    "zh-TW": "權威狀態無法使用"
  },
  "CHECKING_AUTHORITY": {
    "en": "Checking authority…",
    "zh-TW": "正在檢查權威狀態"
  },
  "第 1 天決策草稿尚未確認": {
    "en": "Day 1 decision draft is unconfirmed",
    "zh-TW": "第 1 天決策草稿尚未確認"
  },
  "決策 {0} 綁定於舊版本 rev {1}，目前工作區已有新變更。": {
    "en": "Decision {0} is bound to revision {1}; the workspace has new changes.",
    "zh-TW": "決策 {0} 綁定於舊版本 rev {1}，目前工作區已有新變更。"
  },
  "第 1 天決策 {0} 已核准並綁定於當前版本。": {
    "en": "Day 1 decision {0} is approved and bound to the current revision.",
    "zh-TW": "第 1 天決策 {0} 已核准並綁定於當前版本。"
  },
  "D1 決策：未確認 (DRAFT)": {
    "en": "D1 decision: unconfirmed (DRAFT)",
    "zh-TW": "D1 決策：未確認 (DRAFT)"
  },
  "D1 決策：{0} (對應舊版本 rev {1})": {
    "en": "D1 decision: {0} (earlier revision {1})",
    "zh-TW": "D1 決策：{0} (對應舊版本 rev {1})"
  },
  "D1 決策：{0} ({1})": {
    "en": "D1 decision: {0} ({1})",
    "zh-TW": "D1 決策：{0} ({1})"
  },
  "2D Map": {
    "en": "2D Map",
    "zh-TW": "2D 地圖"
  },
  "3D Massing": {
    "en": "3D Massing",
    "zh-TW": "3D 量體"
  },
  "Split View": {
    "en": "Split View",
    "zh-TW": "分割視圖"
  },
  "OUTCOME_UNKNOWN · RECONCILIATION REQUIRED": {
    "en": "OUTCOME_UNKNOWN · RECONCILIATION REQUIRED",
    "zh-TW": "結果未知・需要核對"
  },
  "Loading server authority…": {
    "en": "Loading server authority…",
    "zh-TW": "載入伺服器權威狀態中…"
  },
  "SERVER AUTHORITY UNAVAILABLE": {
    "en": "SERVER AUTHORITY UNAVAILABLE",
    "zh-TW": "伺服器權威狀態無法使用"
  },
  "Unsaved Draft Changes · NO SERVER REVISION": {
    "en": "Unsaved Draft Changes · NO SERVER REVISION",
    "zh-TW": "未儲存草稿變更・無伺服器版本"
  },
  "Unsaved Draft Changes": {
    "en": "Unsaved Draft Changes",
    "zh-TW": "未儲存草稿變更"
  },
  "In Sync (Server Authority)": {
    "en": "In Sync (Server Authority)",
    "zh-TW": "已同步（伺服器權威狀態）"
  },
  "Record an inspection of the current active StudyArea": {
    "en": "Record an inspection of the current active StudyArea",
    "zh-TW": "記錄目前研究區的檢視"
  },
  "A current confirmed StudyArea with no unsaved workspace edits is required.": {
    "en": "A current confirmed StudyArea with no unsaved workspace edits is required.",
    "zh-TW": "需要已確認的現行研究區，且工作區無未儲存變更。"
  },
  "Record Review": {
    "en": "Record Review",
    "zh-TW": "記錄檢視"
  },
  "Reload state from server": {
    "en": "Reload state from server",
    "zh-TW": "重新載入伺服器狀態"
  },
  "Reload": {
    "en": "Reload",
    "zh-TW": "重新載入"
  },
  "Finish or cancel polygon drawing before syncing.": {
    "en": "Finish or cancel polygon drawing before syncing.",
    "zh-TW": "同步前請完成或取消多邊形繪製。"
  },
  "Syncing...": {
    "en": "Syncing...",
    "zh-TW": "同步中…"
  },
  "Sync Workspace": {
    "en": "Sync Workspace",
    "zh-TW": "同步工作區"
  },
  "未保存的變更存在時不得送出決策，請先點擊 Sync Workspace。": {
    "en": "Decisions cannot be submitted with unsaved changes. Use Sync Workspace first.",
    "zh-TW": "未保存的變更存在時不得送出決策，請先點擊 Sync Workspace。"
  },
  "需要已儲存且無未保存變更的工作區版本。": {
    "en": "A saved workspace revision with no unsaved changes is required.",
    "zh-TW": "需要已儲存且無未保存變更的工作區版本。"
  },
  "確認第 1 天決策（綁定目前 WorkspaceRevision）": {
    "en": "Confirm Day 1 decision (bound to the current WorkspaceRevision)",
    "zh-TW": "確認第 1 天決策（綁定目前 WorkspaceRevision）"
  },
  "確認第 1 天決策": {
    "en": "Confirm Day 1 decision",
    "zh-TW": "確認第 1 天決策"
  },
  "AI 模型設定": {
    "en": "AI model settings",
    "zh-TW": "AI 模型設定"
  },
  "不會顯示或輸入任何 key。Keychain 狀態只確認服務項目存在，不會讀取 key 值。profile 選擇會保存於本機 runtime 設定，重啟 API 後仍保留。": {
    "en": "No keys are displayed or entered. Keychain status checks only whether a service item exists and never reads its value. The profile selection is saved in local runtime settings and remains after an API restart.",
    "zh-TW": "不會顯示或輸入任何 key。Keychain 狀態只確認服務項目存在，不會讀取 key 值。profile 選擇會保存於本機 runtime 設定，重啟 API 後仍保留。"
  },
  "正在讀取 profile 狀態…": {
    "en": "Loading profile status…",
    "zh-TW": "正在讀取 profile 狀態…"
  },
  "使用中的 profile": {
    "en": "Active profile",
    "zh-TW": "使用中的 profile"
  },
  "Ariadne 目前使用：{profile}": {
    "en": "Ariadne currently uses: {profile}",
    "zh-TW": "Ariadne 目前使用：{profile}"
  },
  "未設定": {
    "en": "not configured",
    "zh-TW": "未設定"
  },
  "請選擇 profile": {
    "en": "Choose a profile",
    "zh-TW": "請選擇 profile"
  },
  " · 目前選用": {
    "en": " · active",
    "zh-TW": " · 目前選用"
  },
  "保存中…": {
    "en": "Saving…",
    "zh-TW": "保存中…"
  },
  "儲存 profile": {
    "en": "Save profile",
    "zh-TW": "儲存 profile"
  },
  "模型 profile 狀態": {
    "en": "Model profile status",
    "zh-TW": "模型 profile 狀態"
  },
  "本週呼叫：": {
    "en": "Calls this week:",
    "zh-TW": "本週呼叫："
  },
  "無法確認": {
    "en": "Unknown",
    "zh-TW": "無法確認"
  },
  "ALL": {
    "en": "ALL",
    "zh-TW": "全部"
  },
  "PRESERVE": {
    "en": "PRESERVE",
    "zh-TW": "保留"
  },
  "EDITABLE": {
    "en": "EDITABLE",
    "zh-TW": "可編輯"
  },
  "UNDECIDED": {
    "en": "UNDECIDED",
    "zh-TW": "未決"
  },
  "DRAFT": {
    "en": "DRAFT",
    "zh-TW": "草稿"
  },
  "APPROVED": {
    "en": "APPROVED",
    "zh-TW": "已核准"
  },
  "CONFIRMED_FOR_EXPLORATION": {
    "en": "Confirmed for exploration",
    "zh-TW": "已確認供探索"
  },
  "COMPUTED": {
    "en": "COMPUTED",
    "zh-TW": "已計算"
  },
  "UNKNOWN": {
    "en": "UNKNOWN",
    "zh-TW": "未知"
  },
  "Angular integration (NAIN)": {
    "en": "Angular integration (NAIN)",
    "zh-TW": "角度整合度（NAIN）"
  },
  "Angular choice (NACH)": {
    "en": "Angular choice (NACH)",
    "zh-TW": "角度選擇度（NACH）"
  },
  "Unrecognized metric ({0})": {
    "en": "Unrecognized metric ({0})",
    "zh-TW": "未識別指標（{0}）"
  },
  "Computed · review status applies": {
    "en": "Computed · review status applies",
    "zh-TW": "已計算・適用檢視狀態"
  },
  "Computed · exploratory": {
    "en": "Computed · exploratory",
    "zh-TW": "已計算・探索性"
  },
  "Result unavailable · plan/result mismatch": {
    "en": "Result unavailable · plan/result mismatch",
    "zh-TW": "结果無法使用・規劃與結果不一致"
  },
  "Not computed · coverage blocked": {
    "en": "Not computed · coverage blocked",
    "zh-TW": "未計算・覆蓋範圍封鎖"
  },
  "Not computed · runtime budget": {
    "en": "Not computed · runtime budget",
    "zh-TW": "未計算・執行預算限制"
  },
  "Not computed · {0}": {
    "en": "Not computed · {0}",
    "zh-TW": "未計算・{0}"
  },
  "footprint": {
    "en": "footprint",
    "zh-TW": "基底輪廓"
  },
  "segment": {
    "en": "segment",
    "zh-TW": "路段"
  },
  "Preserve": {
    "en": "Preserve",
    "zh-TW": "保留"
  },
  "Editable": {
    "en": "Editable",
    "zh-TW": "可編輯"
  },
  "mixed_use": {
    "en": "mixed_use",
    "zh-TW": "混合使用"
  },
  "residential": {
    "en": "residential",
    "zh-TW": "住宅"
  },
  "commercial": {
    "en": "commercial",
    "zh-TW": "商業"
  },
  "industrial": {
    "en": "industrial",
    "zh-TW": "工業"
  },
  "open_space": {
    "en": "open_space",
    "zh-TW": "開放空間"
  },
  "public_space": {
    "en": "public_space",
    "zh-TW": "公共空間"
  },
  "hard": {
    "en": "hard",
    "zh-TW": "硬性"
  },
  "preference": {
    "en": "preference",
    "zh-TW": "偏好"
  },
  "whole_site": {
    "en": "whole_site",
    "zh-TW": "全場域"
  },
  "可用": {
    "en": "Available",
    "zh-TW": "可用"
  },
  "缺少 Keychain key": {
    "en": "Missing Keychain key",
    "zh-TW": "缺少 Keychain key"
  },
  "停用": {
    "en": "Disabled",
    "zh-TW": "停用"
  },
  "尚未設定": {
    "en": "Not configured",
    "zh-TW": "尚未設定"
  },
  "不支援 JSON Schema": {
    "en": "JSON Schema output is unsupported",
    "zh-TW": "不支援 JSON Schema"
  },
  "Ollama endpoint 與模型尚未設定；未設定前不會呼叫模型。": {
    "en": "The Ollama endpoint and model are not configured. No model call will be made until they are set.",
    "zh-TW": "Ollama endpoint 與模型尚未設定；未設定前不會呼叫模型。"
  },
  "超出預算": {
    "en": "Over budget",
    "zh-TW": "超出預算"
  },
  "尚未授權 Live AI": {
    "en": "Live AI authorization required",
    "zh-TW": "尚未授權 Live AI"
  },
  "ModelRun 記帳尚未接線": {
    "en": "ModelRun accounting is unavailable",
    "zh-TW": "ModelRun 記帳尚未接線"
  },
  "CLI 未安裝": {
    "en": "CLI is not installed",
    "zh-TW": "CLI 未安裝"
  },
  "尚未登入": {
    "en": "Not logged in",
    "zh-TW": "尚未登入"
  },
  "NOT_LOGGED_IN": {
    "en": "Not logged in",
    "zh-TW": "尚未登入"
  },
  "設定與執行檔可用，CLI 已登入。": {
    "en": "Configured, executable found and CLI logged in.",
    "zh-TW": "設定與執行檔可用，CLI 已登入。"
  },
  "CLI 尚未登入；請在終端機執行 claude 並使用 /login（或 codex login）後重新整理。": {
    "en": "CLI is not logged in; run claude and use /login in your terminal (or codex login) then refresh.",
    "zh-TW": "CLI 尚未登入；請在終端機執行 claude 並使用 /login（或 codex login）後重新整理。"
  },
  "Hermes profile 未設定": {
    "en": "Hermes profile is not configured",
    "zh-TW": "Hermes profile 未設定"
  },
  "需檢查 Hermes 工具狀態": {
    "en": "Hermes toolset check required",
    "zh-TW": "需檢查 Hermes 工具狀態"
  },
  "目前只保存偏好，尚不啟動模型呼叫；耐久 ModelRun 記帳接線完成前，Live AI 維持封鎖。": {
    "en": "Preferences only; model calls remain blocked until durable ModelRun accounting is available.",
    "zh-TW": "目前只保存偏好，尚不啟動模型呼叫；耐久 ModelRun 記帳接線完成前，Live AI 維持封鎖。"
  },
  "目前只保存偏好，尚不啟動模型呼叫；Live AI 仍需要專案層級授權。": {
    "en": "Preferences only; Live AI still requires project authorization.",
    "zh-TW": "目前只保存偏好，尚不啟動模型呼叫；Live AI 仍需要專案層級授權。"
  },
  "目前只保存偏好，尚不啟動模型呼叫。": {
    "en": "Preferences only; model calls are not started.",
    "zh-TW": "目前只保存偏好，尚不啟動模型呼叫。"
  },
  "無法讀取模型 profile 狀態。": {
    "en": "Unable to load model profile status.",
    "zh-TW": "無法讀取模型 profile 狀態。"
  },
  "profile 選擇已保存。": {
    "en": "Profile selection saved.",
    "zh-TW": "profile 選擇已保存。"
  },
  "無法保存 profile 選擇。": {
    "en": "Unable to save profile selection.",
    "zh-TW": "無法保存 profile 選擇。"
  },
  "行人路網 (800 m)": {
    "en": "Pedestrian network (800 m)",
    "zh-TW": "行人路網 (800 m)"
  },
  "行人路網": {
    "en": "Pedestrian network",
    "zh-TW": "行人路網"
  },
  "自行車路網 (2 km)": {
    "en": "Bicycle network (2 km)",
    "zh-TW": "自行車路網 (2 km)"
  },
  "自行車路網": {
    "en": "Bicycle network",
    "zh-TW": "自行車路網"
  },
  "汽車路網 (10 km)": {
    "en": "Motor vehicle network (10 km)",
    "zh-TW": "汽車路網 (10 km)"
  },
  "汽車路網": {
    "en": "Motor vehicle network",
    "zh-TW": "汽車路網"
  },
  "網路模式未記錄／未知": {
    "en": "Network mode not recorded / unknown",
    "zh-TW": "網路模式未記錄／未知"
  },
  "自行車路網 RVV (2 km)": {
    "en": "RVV bicycle network (2 km)",
    "zh-TW": "自行車路網 RVV (2 km)"
  },
  "Maximum height": {
    "en": "Maximum height",
    "zh-TW": "最大高度"
  },
  "First-floor height": {
    "en": "First-floor height",
    "zh-TW": "首層高度"
  },
  "Standard-floor height": {
    "en": "Standard-floor height",
    "zh-TW": "標準層高度"
  },
  "Rotation step": {
    "en": "Rotation step",
    "zh-TW": "旋轉步長"
  },
  "degree": {
    "en": "degree",
    "zh-TW": "度"
  },
  "PROPOSED": {
    "en": "PROPOSED",
    "zh-TW": "已提案"
  },
  "CONFIRMED": {
    "en": "CONFIRMED",
    "zh-TW": "已確認"
  },
  "REJECTED": {
    "en": "REJECTED",
    "zh-TW": "已拒絕"
  },
  "LOCAL_ONLY": {
    "en": "Local only",
    "zh-TW": "僅限本地"
  },
  "EFFECTIVE": {
    "en": "EFFECTIVE",
    "zh-TW": "已生效"
  },
  "Available constraint sets": {
    "en": "Available constraint sets",
    "zh-TW": "可用約束集合"
  },
  "No saved constraint sets found.": {
    "en": "No saved constraint sets found.",
    "zh-TW": "查無已儲存的約束集合。"
  },
  "Manual ID lookup": {
    "en": "Manual ID lookup",
    "zh-TW": "手動輸入編號載入"
  },
  "EXPLORATORY_ONLY": {
    "en": "Exploratory only",
    "zh-TW": "僅供探索"
  },
  "VERY LOW": {
    "en": "VERY LOW",
    "zh-TW": "極低"
  },
  "VERY HIGH": {
    "en": "VERY HIGH",
    "zh-TW": "極高"
  },
  "Very low": {
    "en": "Very low",
    "zh-TW": "極低"
  },
  "Low": {
    "en": "Low",
    "zh-TW": "低"
  },
  "Medium": {
    "en": "Medium",
    "zh-TW": "中"
  },
  "High": {
    "en": "High",
    "zh-TW": "高"
  },
  "Very high": {
    "en": "Very high",
    "zh-TW": "極高"
  },
  "Very Low": {
    "en": "Very Low",
    "zh-TW": "極低"
  },
  "Very High": {
    "en": "Very High",
    "zh-TW": "極高"
  },
  "Choose Hard or Preference for every constraint.": {
    "en": "Choose Hard or Preference for every constraint.",
    "zh-TW": "請為每項條件選擇硬性或偏好。"
  },
  "Fill each required value and give every road width a designer-defined hierarchy label.": {
    "en": "Fill each required value and give every road width a designer-defined hierarchy label.",
    "zh-TW": "請填寫所有必填數值，並為各道路寬度提供設計者定義的層級標籤。"
  },
  "Constraint values must be finite numbers.": {
    "en": "Constraint values must be finite numbers.",
    "zh-TW": "條件數值必須為有限數。"
  },
  "ConstraintSet reload failed with HTTP {0}.": {
    "en": "ConstraintSet reload failed with HTTP {0}.",
    "zh-TW": "條件集重新載入失敗，HTTP {0}。"
  },
  "ConstraintSet save failed with HTTP {0}.": {
    "en": "ConstraintSet save failed with HTTP {0}.",
    "zh-TW": "條件集儲存失敗，HTTP {0}。"
  },
  "Draft saved. No constraint is active until the designer confirms it.": {
    "en": "Draft saved. No constraint is active until the designer confirms it.",
    "zh-TW": "草稿已儲存。設計者確認前，條件皆未啟用。"
  },
  "ConstraintSet draft could not be saved.": {
    "en": "ConstraintSet draft could not be saved.",
    "zh-TW": "無法儲存條件集草稿。"
  },
  "Decision recorded. ConstraintSet state reloaded from the server.": {
    "en": "Decision recorded. ConstraintSet state reloaded from the server.",
    "zh-TW": "決策已記錄。已從伺服器重新載入條件集狀態。"
  },
  "Decision recorded. Reload the ConstraintSet to confirm its latest state.": {
    "en": "Decision recorded. Reload the ConstraintSet to confirm its latest state.",
    "zh-TW": "決策已記錄。請重新載入條件集確認最新狀態。"
  },
  "Rejected: Active StudyArea geometry is unavailable. Reload the verified site context before adding a zone.": {
    "en": "Rejected: Active StudyArea geometry is unavailable. Reload the verified site context before adding a zone.",
    "zh-TW": "已拒絕：現行研究區幾何無法使用。新增分區前請重新載入已驗證場址資料。"
  },
  "Rejected: Active StudyArea geometry is invalid; no zone was added.": {
    "en": "Rejected: Active StudyArea geometry is invalid; no zone was added.",
    "zh-TW": "已拒絕：現行研究區幾何無效；未新增分區。"
  },
  "Rejected: Polygon must be fully within one polygon component of the active StudyArea, including its boundary and holes.": {
    "en": "Rejected: Polygon must be fully within one polygon component of the active StudyArea, including its boundary and holes.",
    "zh-TW": "已拒絕：多邊形必須完全位於現行研究區的一個多邊形部分內，包含其邊界與孔洞限制。"
  },
  "Rejected: Polygon is empty, non-finite, self-intersecting, or has no positive area.": {
    "en": "Rejected: Polygon is empty, non-finite, self-intersecting, or has no positive area.",
    "zh-TW": "已拒絕：多邊形為空、包含非有限值、自交或沒有正面積。"
  },
  "This polygon is an Exploration Design Area. Save it in the separate conceptual-area control; it is not a demand zone.": {
    "en": "This polygon is an Exploration Design Area. Save it in the separate conceptual-area control; it is not a demand zone.",
    "zh-TW": "此多邊形為探索設計範圍。請在獨立概念範圍控制項儲存；它不是需求分區。"
  },
  "Zone name is required.": {
    "en": "Zone name is required.",
    "zh-TW": "必須填寫分區名稱。"
  },
  "Rejected: Empty polygon. Please draw a polygon on the 2D map first.": {
    "en": "Rejected: Empty polygon. Please draw a polygon on the 2D map first.",
    "zh-TW": "已拒絕：空多邊形。請先在 2D 地圖繪製多邊形。"
  },
  "Draw and finish a separate Exploration Design Area polygon before saving it.": {
    "en": "Draw and finish a separate Exploration Design Area polygon before saving it.",
    "zh-TW": "儲存前請繪製並完成獨立的探索設計範圍多邊形。"
  },
  "Exploration Design Area saving is unavailable in this workspace view.": {
    "en": "Exploration Design Area saving is unavailable in this workspace view.",
    "zh-TW": "此工作區視圖無法儲存探索設計範圍。"
  },
  "Rejected: drawn coordinates must be finite EPSG:28992 metres.": {
    "en": "Rejected: drawn coordinates must be finite EPSG:28992 metres.",
    "zh-TW": "已拒絕：繪製座標必須為有限的 EPSG:28992 公尺值。"
  },
  "Preview request failed ({0}).": {
    "en": "Preview request failed ({0}).",
    "zh-TW": "預覽要求失敗（{0}）。"
  },
  "The StudyArea intersection is empty. Draw an area that overlaps the StudyArea.": {
    "en": "The StudyArea intersection is empty. Draw an area that overlaps the StudyArea.",
    "zh-TW": "研究區交集為空。請繪製與研究區重疊的範圍。"
  },
  "The StudyArea intersection creates {0} separate pieces. Redraw the outline so it clips to one connected area.": {
    "en": "The StudyArea intersection creates {0} separate pieces. Redraw the outline so it clips to one connected area.",
    "zh-TW": "研究區交集產生 {0} 個獨立部分。請重繪輪廓，使裁切結果為單一連通範圍。"
  },
  "Could not preview the StudyArea intersection: {0}": {
    "en": "Could not preview the StudyArea intersection: {0}",
    "zh-TW": "無法預覽研究區交集：{0}"
  },
  "Could not preview the StudyArea intersection.": {
    "en": "Could not preview the StudyArea intersection.",
    "zh-TW": "無法預覽研究區交集。"
  },
  "The active StudyArea geometry is unavailable or invalid. Reload the verified site context.": {
    "en": "The active StudyArea geometry is unavailable or invalid. Reload the verified site context.",
    "zh-TW": "現行研究區幾何無法使用或無效。請重新載入已驗證場址資料。"
  },
  "{0} must be a finite non-negative number in decimal notation. Leave the field blank to unset this optional draft target.": {
    "en": "{0} must be a finite non-negative number in decimal notation. Leave the field blank to unset this optional draft target.",
    "zh-TW": "{0} 必須為十進位表示的有限非負數。留白可取消此選填草稿目標。"
  },
  "Target height": {
    "en": "Target height",
    "zh-TW": "目標高度"
  },
  " · Area after clipping: {0} m²": {
    "en": " · Area after clipping: {0} m²",
    "zh-TW": "・裁切後面積：{0} 平方公尺"
  },
  "EMPTY": {
    "en": "EMPTY",
    "zh-TW": "空白"
  },
  "MULTIPLE COMPONENTS": {
    "en": "MULTIPLE COMPONENTS",
    "zh-TW": "多個部分"
  },
  "第 1 天決策：確認設計範圍、建築與道路保留／可改處置，以及空間分區草稿。": {
    "en": "Day 1 decision: confirm the design area, preserved or editable buildings and roads, and spatial zone drafts.",
    "zh-TW": "第 1 天決策：確認設計範圍、建築與道路保留／可改處置，以及空間分區草稿。"
  },
  "service": {
    "en": "service",
    "zh-TW": "服務道路"
  },
  "tertiary": {
    "en": "tertiary",
    "zh-TW": "三級道路"
  },
  "secondary": {
    "en": "secondary",
    "zh-TW": "次要道路"
  },
  "primary": {
    "en": "primary",
    "zh-TW": "主要道路"
  },
  "footway": {
    "en": "footway",
    "zh-TW": "人行道"
  },
  "cycleway": {
    "en": "cycleway",
    "zh-TW": "自行車道"
  },
  "pedestrian": {
    "en": "pedestrian",
    "zh-TW": "行人道路"
  },
  "living_street": {
    "en": "living_street",
    "zh-TW": "生活街道"
  },
  "woonfunctie": {
    "en": "Residential use",
    "zh-TW": "住宅機能"
  },
  "industriefunctie": {
    "en": "Industrial use",
    "zh-TW": "工業機能"
  },
  "kantoorfunctie": {
    "en": "Office use",
    "zh-TW": "辦公機能"
  },
  "bijeenkomstfunctie": {
    "en": "Assembly use",
    "zh-TW": "集會機能"
  },
  "winkelfunctie": {
    "en": "Retail use",
    "zh-TW": "零售機能"
  },
  "overige gebruiksfunctie": {
    "en": "Other use",
    "zh-TW": "其他使用機能"
  },
  "logiesfunctie": {
    "en": "Accommodation use",
    "zh-TW": "住宿機能"
  },
  "onderwijsfunctie": {
    "en": "Education use",
    "zh-TW": "教育機能"
  },
  "sportfunctie": {
    "en": "Sports use",
    "zh-TW": "運動機能"
  },
  "gezondheidszorgfunctie": {
    "en": "Healthcare use",
    "zh-TW": "醫療機能"
  }
};
