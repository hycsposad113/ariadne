---
name: draft-constraints
description: "將自然語言設計構想轉化為平台草稿 ConstraintSet 預覽（不生效，需設計者核准）"
version: 1.0.0
author: Ariadne
license: MIT
metadata:
  hermes:
    tags: [urban-design, constraints, draft, planning, rotterdam-m4h]
---

# 約束草擬（Draft Constraints）

將設計者 Jack 的口語或文字設計意圖，精確轉換為平台資料模型支援的結構化約束條件集（ConstraintSet）草稿。

## 相關 MCP 工具

- `draft_constraints`：輸入自然語言 prompt 或具體數值參數（如 `far_upper_bound`、`max_height_m`、`min_open_space_ratio`、`waterfront_setback_m`），產出狀態為 `DRAFT_PENDING_HUMAN_DECISION` 的草稿約束集。
- `explain_decision_needed`：列出該草稿生效所需的設計者簽署程序。

## 憲法護欄

1. **不可代行核准**：本技能產出的約束條件集僅為**預覽草稿**，不具任何法定效力，不會直接約束後續生成引擎。
2. **禁止建立 HumanDecision**：AI 代理人嚴禁發送核准命令或持有任何決策密語。
3. **引導設計者決策**：完成草擬後，主動提示 Jack 至平台介面檢視草稿，並由 Jack 親自確認並輸入決策密語予以採納（APPROVE）。
