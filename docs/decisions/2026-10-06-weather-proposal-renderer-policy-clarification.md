# Founder 政策澄清：天氣 PROPOSED 與 renderer version — 2026-10-06

Status: HUMAN_AUTHORIZED_POLICY_IMPLEMENTATION; NOT_SOURCE_APPROVAL; NOT_RELEASE_ACCEPTANCE.
直接授權：Founder 在本聊天室回答「1A、2A」。依最後一次中文選項的內容解讀：
1A = 允許保存未批准 PROPOSED 天氣 DatasetSnapshot，正式使用仍需 Founder 批准。
2A = 保留舊 PNG 與失敗紀錄，新增版本化 renderer 基準供新 release 驗收。
注意：早先 decision-packet 的 PNG 選項名稱 B 對應最後回覆中的 2A。此處以內容為準，不重寫歷史 packet，不以字母誤配授權。

## 天氣政策補充 PD-08-C01
舊 PD-08 bytes 保持不變。本澄清針對其中「批准前不得發布」的記錄範圍：
允許 append-only 建立 status=PROPOSED 的候選 Artifact / DatasetSnapshot 及可追溯父檔、方法假設。PROPOSED 不是 approved weather source，不得提升成正式合格候選或 formal climate result。
正式使用仍必須經平台內當前、hash/version-bound 的 Founder HumanDecision；來源 Minute 語義未因本選擇獲證明。receipt qualification 不代替來源批准、實驗批准或最終方法接受。
本選擇只授權政策文件、分支程式與測試整合，不授權本輪寫正式 DB、真實候選發布、天氣選站/分析、main 合併或部署。

## renderer 政策補充 RENDER-C01
建立明確版本、完整現有環境與輸入 fingerprint、實際 SHA-256 基準及相同版本的重建驗證。原圖與原嚴格 byte-equivalence 測試不變，舊歷史重建仍 BLOCKED/失敗，不新加 skip/deselect 或假 PASS。
新的 release gate 以對應版本的新固定基準與受驗證 fingerprint 為準。完整 suite 仍逐項跑並誠實回報：歷史失敗不得聲稱全套零失敗；任何不在本澄清範圍的新錯誤仍為 release blocking。
必須顯式、版本化 gate mapping：historical v4 reproduction 與 current-version reproducibility 分開。缺失的 runtime/font/version/hash 仍造成相應 gate BLOCKED。先完成 TDD、實際重建、mutation/drift controls、獨立 review 後才可推薦 release 接受。
本澄清不是新 renderer 基準已通過，也不是最終 W6 / W7 或 Founder release acceptance。

## 明確不包含
不建立 domain HumanDecision 假資料，不查密語或 Keychain；不更改 StudyArea、已批准設計約束、舊 ledger、舊天氣 bytes、歷史 manifests 或正式服務。
main／正式服務／正式 DB 各步仍需 Founder 當次批准。

## 來源
原待決 packet SHA-256: 4a85b6b0cc92eab235284d1297c0c2c18db0d4e52c823918564ca94973da900e
