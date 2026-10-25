---
name: site-understanding
description: "獲取 Rotterdam M4H 基地邊界、已驗證證據卡、24 項分析主張、六層空間語法及周邊 2km 環境摘要"
version: 1.0.0
author: Ariadne
license: MIT
metadata:
  hermes:
    tags: [urban-design, site-analysis, evidence, rotterdam-m4h, space-syntax]
---

# 基地理解（Site Understanding）

協助設計者 Jack 全面掌握 Rotterdam M4H StudyArea v5 之現況測度、空間語法與周邊環境脈絡。

## 相關 MCP 工具

- `get_site_analysis`：取得 StudyArea v5 面積（226,064.33 m²）、51 個 BAG 建築圖徵、基底面積聯集（44,699.56 m²）、3D BAG 高度統計（配對中位數 9.85 m）及 24 項驗證主張。
- `get_syntax_layers`：取得三模式（車、騎、行）之整合度與穿行度六層圖層、五級分位分布與限制。
- `get_surrounding_context_summary`：取得 2 km 腹地之 OSM 建築、水體、綠地與主要聯外路網要素統計。

## 使用指引與工作原則

1. **先證據後推論**：任何空間討論必須引用確定性計算之證據 ID（如 `card-*` 或 `claim-w5-site-*`）。
2. **空間語法警語**：向設計者說明空間語法圖層時，**必須主動重申**：空間語法之 Integration 與 Choice 僅為空間拓撲測度，**不等於實際人流或交通量**。
3. **探索範圍限制**：明確指出 StudyArea v5 為探索研究範圍，並非正式地籍分區或法定 DesignBoundary。
