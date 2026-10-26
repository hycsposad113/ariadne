"""Shared reference values for the designer's original portfolio baseline."""

from __future__ import annotations

PORTFOLIO_ORIGINAL_BASELINE = {
    "title": "Rotterdam M4H Waterfront Circular District (Q2 Portfolio Original Design)",
    "designer": "the author (Q2 studio design)",
    "provenance": "PORTFOLIO_ORIGINAL_BASELINE",
    "status": "PORTFOLIO_BASELINE_APPROX",
    "source_document": "urbanism-q2-portfolio.pdf",
    "baseline_metrics": {
        "far": {
            "value": 0.8,
            "unit": "ratio",
            "denominator": "land_area",
            "status": "PORTFOLIO_BASELINE_APPROX",
        },
        "max_height_m": {
            "value": 20.0,
            "unit": "m",
            "basis": "4–6 storeys; 3.5 m storey height",
            "status": "PORTFOLIO_BASELINE_APPROX",
        },
        "open_space_ratio": {
            "value": 0.4,
            "unit": "ratio",
            "role": "preference",
            "status": "PORTFOLIO_BASELINE_APPROX",
        },
        "waterfront_public_band_m": {
            "value": 15.0,
            "unit": "m",
            "status": "PORTFOLIO_BASELINE_APPROX",
        },
    },
    "spatial_principles": [
        "連續親水公共長廊（15m 水岸開放帶），維護港池開放視野",
        "工業遺產與既有大型倉庫（如 Gusto、Keilepand 意象）適應性再利用",
        "複合機能導向：創新產業工坊（maker spaces）與住商混合共融",
        "綠色藍色網絡滲透：透過線型綠帶連結內陸與馬斯河（Nieuwe Maas）水岸",
    ],
}
