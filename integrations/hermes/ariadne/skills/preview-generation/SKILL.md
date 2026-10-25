---
name: preview-generation
description: "呼叫假設輸入生成三種形態方案（GRID / GREEN AXIS / CENTRAL OPEN）之未核准預覽"
version: 1.0.0
author: Ariadne
license: MIT
metadata:
  hermes:
    tags: [urban-design, morphology, generative, preview, rotterdam-m4h]
---

# 方案生成預覽（Preview Generation）

在設計初期探索階段，運用平台的形態生成引擎，基於假設輸入（ASSUMED inputs）快速產出三種典型空間結構的方案預覽。

## 相關 MCP 工具

- `run_preview_generation`：接受 `seed`、`strategy_floor_count`、`road_width_m` 等參數，產出候選預覽方案。
- `list_scenarios`：列出生成完畢的預覽方案清單。

## 產出形態策略

1. **GRID（格網型態）**：強調高效率路網劃分與規律街區尺度。
2. **GREEN AXIS（線型綠軸）**：以中央或連續貫穿的綠色開放空間引導街廓配置。
3. **CENTRAL OPEN（核心開放空間）**：環繞大型中央公共廣場或開放腹地集中配置量體。

## 憲法護欄

1. **嚴格標記未核准預覽**：所有生成成果一律標註為 `UNAPPROVED_PREVIEW` 與 `ASSUMED`。
2. **絕不寫入權威資料庫**：生成過程僅於本地暫存或測試端點運作，絕不直接修改正式專案之 `state.sqlite3`。
3. **禁止宣稱最佳方案**：AI 不得在未經設計者評價前宣告任何方案為「勝出方案（Winner）」。
