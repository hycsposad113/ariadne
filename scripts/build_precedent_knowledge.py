#!/usr/bin/env python3
"""Append KB2 case units and Chinese precedent notes from KB4 measurements."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/kb4-precedents"
UNITS = ROOT / "knowledge/v2/domains/MOR/units"
LIB = ROOT / "knowledge/v2/library"
NOTES = ROOT / "knowledge/v2/topics/MOR/precedents"
T06_PATH = ROOT / "knowledge/v2/topics/MOR/MOR-T06-precedent-library.md"

CLASSIC_KNOWLEDGE = {
    "borneo-sporenburg": {
        "library_id": "LYNCH60",
        "claim": "Kevin Lynch 在《The Image of the City》中以路徑、邊界、區域、節點、地標五類元素討論城市意象；本窗圖底只能呈現幾何線索，不能替代居民的認知調查。",
        "use": "將兩島的岸線、跨島路徑和街區節點分層標示，再以使用者訪談檢查其是否構成可辨識的城市意象。",
    },
    "java-eiland": {
        "library_id": "GEHL10",
        "claim": "Jan Gehl 區分必要活動、選擇性活動與社會活動，並把公共空間條件視為選擇性及社會活動能否發生的重要背景；幾何圖不能證明實際停留或交往。",
        "use": "把岸邊停留、橫向通道和臨街活動當成需要現場觀察的設計假設，不從路網存在推定使用強度。",
    },
    "knsm-eiland": {
        "library_id": "JACOBS61",
        "claim": "Jane Jacobs 將混合主要用途、短街廓、不同年代與狀況的建築、足夠集中度列為城市多樣性相互作用的四個條件；單一基地的足跡圖不能證成這四項條件已成立。",
        "use": "補齊街廓和建築年代資料後，再把用途、街廓長度、建築存量及密度分開檢查。",
    },
    "spangen-justus-van-effen": {
        "library_id": "ALEX77",
        "claim": "《A Pattern Language》以跨尺度、彼此關聯的空間模式連結城鎮、建築與建造問題；模式是可檢驗的設計語彙，不能只憑形式相似就判定基地適用。",
        "use": "把院落、街道和住宅入口當成互相連動的層級提出候選，再逐項核對其空間關係與使用條件。",
    },
    "barcelona-eixample": {
        "library_id": "JACOBS61",
        "claim": "Jane Jacobs 把短街廓列為促進街道選擇與交會的城市多樣性條件之一；本研究窗量到的道路分割不能單獨證明步行選擇或活力。",
        "use": "比較完整街廓與研究窗切邊的街廓，並另以實際路網和用途資料檢查可選路徑。",
    },
}

CASE_INTERPRETATIONS = {
    "borneo-sporenburg": "兩座相鄰島區被收進同一研究窗；因此平均值會混合島內街廓與跨水邊界，先分島讀取，再檢查量體如何接上岸線。",
    "java-eiland": "狹長島形使橫向連接成為關鍵觀察線索；建築間距、近水距離與路徑位置應並列，單一密度值不足以描述穿越性。",
    "knsm-eiland": "OSM 研究窗完整性與足跡覆蓋仍需抽樣核實；若回傳資料有缺口，低足跡或少街廓數只代表已映射部分，不能直接當成全島形態。",
    "ijburg-haveneiland": "運河與陸側街網把研究窗切成不同界面；整窗均值可作總覽，生成時仍應保留每一岸段和內街區的局部差異。",
    "kop-van-zuid-wilhelminapier": "碼頭端部、跨河連接與不同尺度的建築同時出現；將高度覆蓋率和街廓切分一起讀，避免把已知量體誤作全部開發強度。",
    "katendrecht": "半島的岸線距離短不代表岸邊可達；量體位置可用來找出候選橫向支線，開放性仍須另查路權及管理資料。",
    "lloydkwartier": "舊港區地塊與新用途的接合需要看空間序列；街廓面積與翼深分布比單一中位數更適合定位尺度轉換處。",
    "spangen-justus-van-effen": "Justus van Effen 群位於較大住宅街區之內；整窗自動判型應與建築群局部圖分讀，不能以區域統計代替院落測繪。",
    "funenpark": "公園邊界與建築前緣相鄰時，圖底只指出可能的接面；入口、穿越權及停留活動都需要獨立資料。",
    "hafencity-dalmannkai": "港區岸邊和高密街廓並置，街廓尺度、翼深及水際距離共同影響量體配置；行人標籤不等於完整公共岸線。",
    "vastra-hamnen": "面海邊界和內街網有不同暴露方向；平面密度可支援形態對照，不能代替風、日照或季節使用分析。",
    "hammarby-sjostad": "湖岸、內水面和街道接點構成多段水際；應逐段檢查映射路徑與建築入口，不能由近水距離推斷公共使用。",
    "nordhavn": "港區分期會讓現況足跡與空地並存；量測只屬本次觀察快照，生成流程須把已建區與待開發岸段分別處理。",
    "vauban-freiburg": "非港區住宅網絡提供道路層級的對照；外牆間距不是交通舒適度，還需檢查實際路幅、行人網和用途分布。",
    "barcelona-eixample": "規則網格中完整街廓、切邊街廓和內部空間的統計口徑不同；先分辨幾何單元，再討論周邊式量體或開放內院。",
    "amsterdam-oud-zuid": "非水岸的轉角與連續街牆可作帶狀基地的城市接面參照；現況幾何只能呈現當下形態，不能回推 Berlage 計畫原貌。",
}

CASE_SOURCE = {
    "borneo-sporenburg": "EASTERN_HARBOUR_AMSTERDAM2012",
    "java-eiland": "EASTERN_HARBOUR_AMSTERDAM2012",
    "knsm-eiland": "EASTERN_HARBOUR_AMSTERDAM2012",
    "ijburg-haveneiland": "IJBURG1998_HOAD",
    "kop-van-zuid-wilhelminapier": "DOUCET2011KOPVANZUID",
    "katendrecht": "BAPTIST2026",
    "lloydkwartier": "STOUTEN2017",
    "spangen-justus-van-effen": "BRINKMANN2009_SPANGEN",
    "funenpark": "EASTERN_HARBOUR_AMSTERDAM2012",
    "hafencity-dalmannkai": "LANDIS2022",
    "vastra-hamnen": "JOHANSSON2020MALMO",
    "hammarby-sjostad": "STOCKHOLM_HAMMARBY2026",
    "nordhavn": "PESTOVA2022",
    "vauban-freiburg": "COATES2013",
    "barcelona-eixample": "CERDA2018",
    "amsterdam-oud-zuid": "KOSHIZAWA1991_ZUID",
}

MISSING_SOURCE = {
    "katendrecht": "ROTTERDAM_KATENDRECHT2026",
    "vastra-hamnen": "MALMO_VASTRA_HAMNEN",
    "nordhavn": "COPENHAGEN_NORDHAVN2011",
    "barcelona-eixample": "BERGHAUSERPONT2017",
}

LENSES = {
    "borneo-sporenburg": "兩座相鄰島區同列一窗；解讀時應先拆開各自的街廓節奏。",
    "java-eiland": "狹長島體和兩側岸線把橫向穿越通道變成主要的街網判讀軸。",
    "knsm-eiland": "港島內部街道和水邊建築在短距離並置，適合檢查尺度轉換。",
    "ijburg-haveneiland": "填海新區的運河邊界和內側街廓應分開看待，不能把整窗當成單一密度帶。",
    "kop-van-zuid-wilhelminapier": "港灣尖端同時容納倉儲遺產、較大體量和跨河通道，整體平均會隱去轉折。",
    "katendrecht": "半島腹地到岸線的路徑要和岸邊建築一起閱讀，岸線長度本身不足以描述可達性。",
    "lloydkwartier": "碼頭街廓和水際開口互相牽動，量體比較需留下兩者的空間位置。",
    "spangen-justus-van-effen": "住宅群位於更大街區脈絡中，整窗數值不能代替地標住宅群的細部測繪。",
    "funenpark": "公園綠地和街廓相鄰，建築邊界的入口與通透性是此窗的重要空間條件。",
    "hafencity-dalmannkai": "沿岸界面、建築翼深和街廓內部空間需在同一剖面中比較。",
    "vastra-hamnen": "面海方向改變迎風面與街廓暴露條件，平面密度無法代表微氣候。",
    "hammarby-sjostad": "內水岸與道路網交會，步行路線是否穿越建築群應由幾何和路徑標記共同檢查。",
    "nordhavn": "港區分期使已建街區與規劃岸線並存，現況與計畫值不能混成一個平均。",
    "vauban-freiburg": "一般街區對照可檢查住宅支路和主街在日常步行骨架中的不同角色。",
    "barcelona-eixample": "網格街廓內部和街道輪廓是兩種空間；研究窗切邊部分須和完整街廓區別。",
    "amsterdam-oud-zuid": "非水岸片段提供街牆連續性和轉角街廓的基準，需另行確認現況與歷史計畫的對應。",
}

MOVES = {
    "borneo-sporenburg": ["分開計算 Borneo 與 Sporenburg 的街廓，不將兩個島區合成單一原型。", "比較臨水邊、陸側街道與島內路徑的建築界面。"],
    "java-eiland": ["沿岸線至島內建立橫切序列，測試不同穿越頻率對步行連接的影響。", "用實測街廓和翼深作生成器輸入，不預設統一面寬。"],
    "knsm-eiland": ["將 OSM 建築足跡與官方建物清冊或航照抽樣比對，確認島區覆蓋程度後再判讀整體界面。", "只有在道路、足跡和岸線資料能共同描述研究窗時，才用本案密度與街廓值設定生成參數。"],
    "ijburg-haveneiland": ["按運河和內側道路分段比較街廓形狀。", "先用高度覆蓋率標示可靠 FSI 區域，再決定是否補測建築高度。"],
    "kop-van-zuid-wilhelminapier": ["沿濱水步道連接大型量體與細尺度街道，逐段記錄可達岸線。", "把港口遺產與新增建築分組，不以單一平均值抹平年代差異。"],
    "katendrecht": ["繪出半島腹地通向水際的橫向支線，逐路核對地圖中的行人標記。", "把公共性標作待確認事項，避免將 OSM access 標籤當作權屬證據。"],
    "lloydkwartier": ["比較倉儲街廓與岸線開口的位置關係。", "為帶狀基地測試多個垂直岸線入口，並檢查平行水岸路徑的依賴程度。"],
    "spangen-justus-van-effen": ["先將 Justus van Effen 群從鄰近住宅街廓分出，再檢查院落和街道連接。", "分辨現況足跡和歷史設計資料，避免以地標名推定原始平面。"],
    "funenpark": ["分圖顯示公園和建築足跡，追蹤綠地邊界的入口及街道接面。", "比較綠地周邊不同的建築邊界情境和穿越路徑。"],
    "hafencity-dalmannkai": ["保留連續岸邊步行路徑，另行標出臨水建築入口及私人空間。", "在剖面中同時檢查建築翼深與水邊退距。"],
    "vastra-hamnen": ["將海岸迎風面和內部街道分開測試量體變化。", "把風環境與日照列為平面密度之外的獨立分析。"],
    "hammarby-sjostad": ["將湖岸步道、跨街入口和內部綠地串成可核查的網絡。", "比較不同街廓尺度對街道界面和水際開放空間的影響。"],
    "nordhavn": ["分開標記已建街區和規劃中岸線，按分期設定量體參數。", "測試次級慢行路徑是否把大型港區街廓連到岸邊。"],
    "vauban-freiburg": ["將外圍道路、主街、住宅支路和慢行通道分層成圖。", "以此一般街區檢查港區方案是否維持足夠的日常步行連接。"],
    "barcelona-eixample": ["以完整街廓為基本單元，分開試驗周邊量體和內部開放空間。", "把研究窗切邊的街廓另外標示，不與完整街廓直接比較。"],
    "amsterdam-oud-zuid": ["以街牆連續度及轉角地塊形狀引導帶狀基地轉角設計。", "先用非水岸片段建立街廓基準，再將水際條件作為變化因素加入。"],
}

QUESTIONS = {
    "borneo-sporenburg": "相鄰島區的均值會遮住內部差別，因此後續比較應保留兩組街廓序列。",
    "java-eiland": "連續街道界面和橫向通道頻率會拉扯島體空間；岸線是否成為日常路徑仍需核實。",
    "knsm-eiland": "OSM 足跡覆蓋率與岸線步行路徑標記需分別抽樣核對；資料稀疏或標籤缺漏會讓島內尺度和量體連續性失去代表性。",
    "ijburg-haveneiland": "新造地道路整齊不等同街道生活豐富；本圖只觀察幾何和標籤。",
    "kop-van-zuid-wilhelminapier": "地標建築和跨河連接可強化港灣辨識，公共岸線的連續性仍須逐段驗證。",
    "katendrecht": "有行人路線標記不代表通行權已核實，須另查土地權屬與管理條件。",
    "lloydkwartier": "倉儲尺度與住宅尺度同時出現時，平均翼深會抹平尺度轉換。",
    "spangen-justus-van-effen": "住宅群的空間特徵可能消失在周邊街區均值裡，需保留獨立測繪單元。",
    "funenpark": "公園帶來開放空間，周邊是否提供可進入的邊界需用入口資料確認。",
    "hafencity-dalmannkai": "岸線連續性、商業活動和無消費停留的條件可能互相影響，本次幾何不能評斷其分配公平。",
    "vastra-hamnen": "沿海形態同時受風、日照和季節使用影響，平面密度不能代表戶外舒適度。",
    "hammarby-sjostad": "水邊路徑可能被住宅私密邊界切開，地圖上有路仍需實地或官方資料核實。",
    "nordhavn": "若把未建用地納入已完成街區的均值，分期差異會被誤讀成現況密度。",
    "vauban-freiburg": "主街與慢速住宅支路的作用不同，單一街道寬度中位數會失去設計資訊。",
    "barcelona-eixample": "院落面積與院落可進入性不是同一件事，圖底關係不能證明公共性。",
    "amsterdam-oud-zuid": "現況街廓的連續性可作比較，但目前尚未確認各段與 Berlage 原始計畫的對應。",
}

METRICS = [
    ("GSI", "無量綱"), ("FSI_known_floor_area_lower_bound", "無量綱"),
    ("L_area_weighted_known_building_floors", "層"), ("OSR_from_measured_GSI_and_known_FSI", "無量綱"),
    ("block_count", "個；含截邊街廓"), ("complete_block_count", "個；完整研究窗內街廓"),
    ("block_area_m2", "m²；完整街廓最小／P25／中位／P75／最大"),
    ("block_area_m2_all_observed", "m²；全觀察街廓含截邊最小／P25／中位／P75／最大"),
    ("block_edge_length_m", "m；主要街道交叉口間街段最小／P25／中位／P75／最大"),
    ("street_width_building_gap_m", "m；最小／P25／中位／P75／最大"),
    ("building_wing_depth_proxy_m", "m；最小／P25／中位／P75／最大"),
    ("building_wing_depth_crosscheck_minimum_rotated_rectangle_short_side_m", "m；最小／P25／中位／P75／最大"),
    ("building_wing_depth_proxy_under_4m_sample_share", "比例；2A／周長代理低於 4 m 的樣本占比"),
    ("principal_mass_under_100m2_sample_share", "比例；主要形態量體低於 100 m² 的占比"),
    ("principal_building_count_for_form", "棟；主要形態樣本"),
    ("accessory_building_count_excluded_from_form_metrics", "棟；僅不納入翼深／類型"),
    ("typology_sample_count", "個；完整街廓判型樣本"),
    ("building_to_mapped_water_distance_m", "m；最小／P25／中位／P75／最大"),
    ("water_access", "OSM 水岸行人路徑標記與數量"),
    ("block_type_mix", "街廓分類數量與比例"),
    ("height_coverage_ratio", "比例"), ("height_missing_building_count", "棟"),
]
METRIC_NAMES = {
    "GSI": "建築覆蓋率 GSI",
    "FSI_known_floor_area_lower_bound": "已知樓層面積比 FSI 下限",
    "L_area_weighted_known_building_floors": "足跡加權平均樓層 L",
    "OSR_from_measured_GSI_and_known_FSI": "開放空間比 OSR（已知 FSI）",
    "block_count": "街廓數",
    "complete_block_count": "完整街廓數",
    "block_area_m2": "完整街廓面積分布",
    "block_area_m2_all_observed": "全觀察街廓面積分布（含截邊）",
    "block_edge_length_m": "主要街道交叉口間街段長分布",
    "street_width_building_gap_m": "街道寬度代理（建築間距）",
    "building_wing_depth_proxy_m": "建築翼深代理",
    "building_wing_depth_crosscheck_minimum_rotated_rectangle_short_side_m": "翼深交叉檢查（最小旋轉外接矩形短邊）",
    "building_wing_depth_proxy_under_4m_sample_share": "翼深代理低於 4 m 樣本占比",
    "principal_mass_under_100m2_sample_share": "主要形態量體低於 100 m² 占比",
    "principal_building_count_for_form": "主要形態樣本建築數",
    "accessory_building_count_excluded_from_form_metrics": "翼深／類型排除的輔助建物數",
    "typology_sample_count": "完整街廓判型樣本數",
    "building_to_mapped_water_distance_m": "建築至映射水岸距離",
    "water_access": "水岸行人路徑 OSM 標記",
    "block_type_mix": "主要形態類型分布（街廓代理）",
    "height_coverage_ratio": "高度或樓層資訊覆蓋率",
    "height_missing_building_count": "高度或樓層缺值建築數",
}

def utc_now() -> str:
    return subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)

def write_json_new(path: Path, obj: Any) -> None:
    write_new(path, json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")

def fmt(value: Any) -> str:
    if value is None:
        return "未取得"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, dict):
        if any(isinstance(val, dict) for val in value.values()):
            return "；".join(
                f"{key} {fmt(val.get('block_count'))} 個／比例 {fmt(val.get('share'))}"
                for key, val in value.items() if isinstance(val, dict)
            )
        return "；".join(f"{key} {fmt(val)}" for key, val in value.items() if key != "sample_count")
    return str(value)

def metric_display(key: str, value: Any) -> str:
    if key == "water_access" and isinstance(value, dict):
        return (
            f"{value.get('status', '未取得')}；近水路徑 {value.get('nearby_mapped_route_count', 0)} 條；"
            f"明示開放標記 {value.get('routes_with_explicit_open_access_tags', 0)} 條；"
            f"明示受限標記 {value.get('routes_with_explicit_restriction_tags', 0)} 條；"
            f"未判定 {value.get('routes_with_ambiguous_access', 0)} 條"
        )
    return fmt(value)

def citation(id_: str, claim: str = "C1") -> dict[str, Any]:
    return {"library_id": id_, "claim_id": claim, "locator": None}

def build_library(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    now = utc_now()
    snapshots = [{
        "slug": case["slug"], "path": case["source"]["osm_raw_path"],
        "sha256": case["source"]["osm_sha256"], "base_timestamp": case["metrics"]["snapshot_date"],
        "element_count": case["source"]["osm_element_count"],
    } for case in metrics["cases"]]
    sources = []
    for id_, title, authors, kind, venue, api, match, claim, limit, url in [
        ("OSM_KB4_PRECEDENTS", "OpenStreetMap KB4 precedent snapshots", ["OpenStreetMap contributors"], "OPEN_DATASET", "OpenStreetMap / Overpass API", "Overpass API", ";".join(row["sha256"] for row in snapshots),
         "本資料集記錄 KB4 研究窗的 OSM 建築、道路、水體與岸線快照；每筆回應以 SHA-256 和資料時間戳識別。",
         "OSM 為社群編輯觀察資料，可能缺漏；幾何不證明現場通行權或法定基地邊界。", "https://overpass-api.de/api/interpreter"),
        ("3DBAG_KB4_HEIGHTS", "3DBAG public building-height snapshots", ["3DBAG"], "OPEN_DATASET", "3DBAG public WFS", "3DBAG WFS", "WFS capabilities and saved tile hashes",
         "高度只採 BAG 識別碼成功連結的 b3_h_70p − b3_h_maaiveld；3.0 m／層只作明示樓層換算假設。",
         "無 BAG 對應高度的建築保持未知；資料缺值不以幾何或 OSM 標籤補猜。", "https://data.3dbag.nl/api/BAG3D/wfs"),
    ]:
        sources.append({
            "id": id_, "title": title, "authors": authors, "year": None, "venue_or_publisher": venue,
            "doi": None, "isbn": None, "openalex_id": None, "kind": kind, "tradition": "都市形態測量與先例研究",
            "region": "跨城市公開資料", "method": "明列資料快照、欄位和計算界線",
            "claims": [{"claim_id": "C1", "claim_zh": claim, "strength": "CASE_EVIDENCE",
                        "scope_zh": "只支持可檢查的資料來源與欄位，不支持完整性或規範性推論。",
                        "assessment_basis": "DIRECT_DATA_SNAPSHOT_REVIEW"}],
            "known_critiques": [],
            "verification": {"status": "VERIFIED", "api": api, "query": {"title": title},
                             "matched_record_id": match, "checked_at_utc": now,
                             "match_notes_zh": "逐筆核對可保存回應、檔案雜湊與服務欄位。", "url": url, "accessed_utc": now[:10]},
            "limitations_zh": limit, "metadata_licence_zh": "公開服務來源 metadata 與自行撰寫測量範圍說明。",
            "snapshot_manifest": snapshots if id_ == "OSM_KB4_PRECEDENTS" else [],
        })
    bag_manifest_path = ART / "3dbag-source-manifest.json"
    osm_record = next(row for row in sources if row["id"] == "OSM_KB4_PRECEDENTS")
    osm_record["unavailable_cases"] = metrics.get("unmeasured_cases", [])
    if bag_manifest_path.is_file():
        bag_manifest = read(bag_manifest_path)
        bag_record = next(row for row in sources if row["id"] == "3DBAG_KB4_HEIGHTS")
        bag_record["source_manifest_path"] = str(bag_manifest_path.relative_to(ROOT))
        bag_record["source_manifest_sha256"] = digest(bag_manifest_path)
        bag_record["snapshot_manifest"] = [
            {key: tile.get(key) for key in (
                "tile_id", "response_path", "response_sha256", "response_size_bytes",
                "retrieved_at_utc", "url"
            )}
            for tile in bag_manifest.get("tiles", [])
        ]
        bag_record["tile_catalog_requests"] = bag_manifest.get("tile_catalog_requests", [])
    sources.extend([
        {
            "id": "IJBURG1998_HOAD", "title": "The Ijburg Project, Amsterdam", "authors": ["Darren Hoad"], "year": 1998,
            "venue_or_publisher": "Geography", "doi": "https://doi.org/10.1080/20436564.1998.12452662",
            "isbn": None, "openalex_id": None, "kind": "ACADEMIC_ARTICLE", "tradition": "Amsterdam IJburg 城市規劃",
            "region": "IJburg, Amsterdam, Netherlands", "method": "Crossref 書目記錄",
            "claims": [{"claim_id": "C1", "claim_zh": "Crossref 書目記錄將 IJburg 作為 Amsterdam 新發展計畫案例範圍。",
                        "strength": "CASE_EVIDENCE", "scope_zh": "僅核對書目標題、作者、年份和 DOI，不推定形態結果。",
                        "assessment_basis": "BIBLIOGRAPHIC_RECORD_REVIEW"}],
            "known_critiques": [], "verification": {"status": "VERIFIED", "api": "Crossref",
                "query": {"title": "The Ijburg Project, Amsterdam", "author": "Darren Hoad", "year": 1998},
                "matched_record_id": "https://doi.org/10.1080/20436564.1998.12452662",
                "checked_at_utc": "2026-10-09T10:24:49Z", "match_notes_zh": "Crossref 精確書目記錄。"},
            "limitations_zh": "未讀全文，不引用任何設計參數或成果數字。",
            "metadata_licence_zh": "公開 Crossref 書目 metadata；未保存全文。",
        },
        {
            "id": "BRINKMANN2009_SPANGEN", "title": "Spangen Rotterdam", "authors": ["Michiel Brinkmann"], "year": 2009,
            "venue_or_publisher": "Springer book chapter", "doi": "https://doi.org/10.1007/978-3-211-79178-3_4",
            "isbn": None, "openalex_id": None, "kind": "ACADEMIC_BOOK_CHAPTER", "tradition": "鹿特丹住宅街道與住宅群",
            "region": "Spangen, Rotterdam, Netherlands", "method": "Crossref 書目記錄",
            "claims": [{"claim_id": "C1", "claim_zh": "Crossref 書目確認 Michiel Brinkmann 於 2009 年出版題為 Spangen Rotterdam 的章節。",
                        "strength": "CASE_EVIDENCE", "scope_zh": "書目只作 Spangen 住宅街道案例的追查入口，不從作者欄推定設計者身分。",
                        "assessment_basis": "BIBLIOGRAPHIC_RECORD_REVIEW"}],
            "known_critiques": [], "verification": {"status": "VERIFIED", "api": "Crossref",
                "query": {"title": "Spangen Rotterdam", "author": "Michiel Brinkmann", "year": 2009},
                "matched_record_id": "https://doi.org/10.1007/978-3-211-79178-3_4",
                "checked_at_utc": "2026-10-09T10:24:59Z", "match_notes_zh": "Crossref 書目記錄與 DOI。"},
            "limitations_zh": "未讀全文，未根據章節題名推論空間成效。",
            "metadata_licence_zh": "公開 Crossref 書目 metadata；未保存全文。",
        },
        {
            "id": "KOSHIZAWA1991_ZUID", "title": "Planning History of Amsterdam and the Significance of the Southern Extension Plan (the Extension Plan “Zuid”) by H. P. Berlage Approved in 1917", "authors": ["Akira Koshizawa"], "year": 1991,
            "venue_or_publisher": "Historical Studies in Civil Engineering", "doi": "https://doi.org/10.2208/journalhs1990.11.155",
            "isbn": None, "openalex_id": None, "kind": "ACADEMIC_PAPER", "tradition": "Amsterdam Zuid 城市規劃史",
            "region": "Amsterdam Zuid, Netherlands", "method": "Crossref 書目記錄",
            "claims": [{"claim_id": "C1", "claim_zh": "Crossref 記錄 Koshizawa 於 1991 年發表 Amsterdam Zuid 的 Berlage 計畫研究。",
                        "strength": "CASE_EVIDENCE", "scope_zh": "摘要或原文細節尚未核對，僅作歷史計畫的書目線索。",
                        "assessment_basis": "BIBLIOGRAPHIC_RECORD_REVIEW"}],
            "known_critiques": [], "verification": {"status": "VERIFIED", "api": "Crossref",
                "query": {"author": "Akira Koshizawa", "year": 1991},
                "matched_record_id": "https://doi.org/10.2208/journalhs1990.11.155",
                "checked_at_utc": "2026-10-09T10:25:19Z", "match_notes_zh": "Crossref 書目記錄與 DOI。"},
            "limitations_zh": "未讀全文；標題所述計畫年份及設計細節待原文核對。",
            "metadata_licence_zh": "公開 Crossref 書目 metadata；未保存全文。",
        },
        {
            "id": "SPACEMATRIX_VARS2017", "title": "Typology based on three density variables central to Spacematrix using cluster analysis",
            "authors": ["Meta Berghauser Pont", "Jesper Olsson"], "year": 2017,
            "venue_or_publisher": "ISUF 2017", "doi": "https://doi.org/10.4995/isuf2017.2017.5319",
            "isbn": None, "openalex_id": "https://openalex.org/W2783956656",
            "kind": "ACADEMIC_CONFERENCE_PAPER", "tradition": "城市密度與街道形態分類",
            "region": "跨城市形態分類", "method": "OpenAlex exact-work record and abstract",
            "claims": [{"claim_id": "C1", "claim_zh": "OpenAlex 摘要將 FSI、GSI 與 network density N 列為 Spacematrix 三個核心變數，並以聚類區別建築類型和街道模式。",
                        "strength": "THEORETICAL", "scope_zh": "僅依 OpenAlex work metadata 和摘要陳述，需由指揮官獨立交叉檢查。",
                        "assessment_basis": "ABSTRACT_REVIEW"}],
            "known_critiques": [], "verification": {"status": "VERIFIED", "api": "OpenAlex",
                "query": {"work_id": "https://openalex.org/W2783956656"},
                "matched_record_id": "https://openalex.org/W2783956656",
                "checked_at_utc": "2026-10-09T10:55:43Z",
                "match_notes_zh": "以 OpenAlex exact-work 查詢核對作者、年份、DOI 與摘要範圍。"},
            "limitations_zh": "未取得全文；由 2D FSI–GSI 散布圖不能替代三變數分類。",
            "metadata_licence_zh": "保存公開書目欄位和自行撰寫摘要範圍，不保存全文。",
        },
    ])
    return sources

def context(area: dict[str, Any], case: dict[str, Any], indicator: str) -> str:
    osm = case["source"]
    bag = osm.get("3dbag") or {}
    tile_dates = sorted({str(tile.get("retrieved_at_utc")) for tile in bag.get("tiles", [])
                         if tile.get("retrieved_at_utc")})
    bag_date = "、".join(tile_dates) if tile_dates else "3DBAG 高度未取得"
    boundary = area["boundary_note_zh"].rstrip("。；")
    return (f"{area['title_zh']}的{indicator}：{area['city']}研究窗 {area['area_ha']} ha；"
            f"{boundary}；OSM 時間戳 {case['metrics']['snapshot_date']}，"
            f"回應 SHA-256 {osm['osm_sha256']}；OSM 下載時間 {osm.get('osm_retrieved_at_utc') or '未記錄'}；"
            f"3DBAG tile 下載時間 {bag_date}；此觀察值不代表 M4H 或本基地法規。")

def source_findings(case: dict[str, Any]) -> list[dict[str, Any]]:
    ident = CASE_SOURCE[case["slug"]]
    record = read(LIB / f"{ident}.json") if (LIB / f"{ident}.json").is_file() else {}
    claim = record.get("claims", [{}])[0].get("claim_zh", record.get("title", ident))
    kind = str(record.get("kind", "")).upper()
    status = "ABSTRACT_REVIEW" if any(word in kind for word in ("ACADEMIC", "PAPER", "ARTICLE", "JOURNAL", "THESIS")) else "BIBLIOGRAPHIC_SCOPE_ONLY"
    findings = [
        {"library_id": "OSM_KB4_PRECEDENTS", "claim_zh": f"{case['title_zh']} 使用回應 {case['source']['osm_sha256'][:12]} 計算；未映射建築沒有插補。",
        "effect_or_value": f"{case['metrics']['building_count']} 棟建築；高度覆蓋率 {fmt(case['metrics']['height_coverage_ratio'])}。",
        "study_design": "研究窗 OSM 幾何測量", "context_region": f"{case['city']}, {case['country']}", "locator": None,
         "claim_verification": "OBSERVED_OPEN_DATA_MEASUREMENT", "limitations_zh": "OSM 是社群編輯資料；此值只描述快照，不代表完整盤點。"},
        {"library_id": "BILJECKI2022", "claim_zh": f"Biljecki 與 Chow 的跨尺度形態指標研究強調來源和尺度可追溯；本案把該原則用於 {case['title_zh']} 的 {case['research_boundary']['area_ha']} ha 觀察窗。",
         "effect_or_value": None, "study_design": "形態指標研究", "context_region": "全球多城市資料", "locator": None,
         "claim_verification": "ABSTRACT_REVIEW", "limitations_zh": "該研究不驗證此窗 OSM 完整度或 M4H 法規。"},
        {"library_id": ident, "claim_zh": f"{case['title_zh']}引用來源記載：{claim}", "effect_or_value": None,
         "study_design": "書目或官方案例資料", "context_region": f"{case['city']}, {case['country']}", "locator": None,
         "claim_verification": status, "limitations_zh": "只按已核對的書目或官方來源範圍引用，未查證的設計細節不推定。"},
    ]
    bag = case["source"].get("3dbag")
    if bag:
        findings.append({
            "library_id": "3DBAG_KB4_HEIGHTS",
            "claim_zh": f"{case['title_zh']} 的高度欄位以可連結 BAG 識別碼配對 3DBAG 屋頂與地面高度；沒有匹配的建物不補值。",
            "effect_or_value": f"高度覆蓋 {case['metrics']['height_observed_building_count']}/{case['metrics']['building_count']} 棟；FSI 可比性為 {case['metrics']['FSI_comparability_status']}。",
            "study_design": "3DBAG 公開建物高度資料的 BAG-ID 配對",
            "context_region": f"{case['city']}, Netherlands", "locator": None,
            "claim_verification": "OBSERVED_OPEN_DATA_MEASUREMENT",
            "limitations_zh": "只計可連結到 3DBAG 高度的足跡；高度轉樓層時採明列 3.0 m／層假設。",
        })
    return findings

def metric_value_rows(area: dict[str, Any], case: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, unit in METRICS:
        source = "3DBAG_KB4_HEIGHTS" if area["country"] == "Netherlands" and key in {
            "FSI_known_floor_area_lower_bound", "L_area_weighted_known_building_floors",
            "OSR_from_measured_GSI_and_known_FSI", "height_coverage_ratio", "height_missing_building_count"
        } else "OSM_KB4_PRECEDENTS"
        value = metric_display(key, case["metrics"].get(key))
        if key == "FSI_known_floor_area_lower_bound" and not case["metrics"].get("comparison_eligible"):
            value += "；僅下限或空間快照不足，不可跨案例比較"
        if key == "building_wing_depth_proxy_m":
            wd_mid = (case["metrics"].get("building_wing_depth_proxy_m") or {}).get("median")
            if wd_mid is not None and (wd_mid < 10.0 or wd_mid > 16.0):
                value += "；低信心（偏離住宅常規 10–16 m）"
        rows.append({"name": METRIC_NAMES[key], "range": value, "unit": unit,
                     "context": context(area, case, METRIC_NAMES[key]), "library_id": source})
    m = case["metrics"]
    for name, key, unit, library_id in [
        ("GSI（含映射水域分母）", "GSI_gross_water_inclusive", "無量綱", "OSM_KB4_PRECEDENTS"),
        ("FSI 下限（含映射水域分母）", "FSI_gross_water_inclusive_lower_bound", "無量綱", "3DBAG_KB4_HEIGHTS" if area["country"] == "Netherlands" else "OSM_KB4_PRECEDENTS"),
        ("陸地分母面積", "land_area_m2", "m²", "OSM_KB4_PRECEDENTS"),
        ("建築合併後量體數", "building_mass_count_after_merge_0_5m", "量體", "OSM_KB4_PRECEDENTS"),
        ("輔助建物以外主要形態樣本數", "principal_building_count_for_form", "棟", "OSM_KB4_PRECEDENTS"),
        ("翼深交叉檢查：最小旋轉外接矩形短邊", "building_wing_depth_crosscheck_minimum_rotated_rectangle_short_side_m", "m；分位數", "OSM_KB4_PRECEDENTS"),
        ("小於 1,000 m² 排除碎片數", "small_block_fragment_count_excluded_under_1000m2", "個", "OSM_KB4_PRECEDENTS"),
        ("完整街廓判型樣本數", "typology_sample_count", "個", "OSM_KB4_PRECEDENTS"),
        ("未分類街廓比例", "unclassified_block_share", "比例", "OSM_KB4_PRECEDENTS"),
    ]:
        rows.append({"name": name, "range": metric_display(key, m.get(key)), "unit": unit,
                     "context": context(area, case, name), "library_id": library_id})
    return rows

def typology_case_note(title: str, metrics: dict[str, Any]) -> str:
    mix = metrics["block_type_mix"]
    sample_count = metrics["typology_sample_count"]
    if not sample_count:
        return f"{title}沒有完整窗內街廓可供自動判型，故未分類比例不計算；截邊街廓沒有代替完整樣本。"
    counts = [f"{name} {row['block_count']} 個" for name, row in mix.items() if row["block_count"]]
    unclassified = mix["混合／未分類"]["block_count"]
    return (f"{title}的 {sample_count} 個完整街廓判型結果為 {'、'.join(counts)}；其中 {unclassified} 個（{fmt(metrics['unclassified_block_share'])}）維持混合／未分類，"
            "這是依本輪幾何門檻自動計算、尚未人工逐街廓核圖的結果。")

def unit_for(area: dict[str, Any], case: dict[str, Any] | None, index: int) -> dict[str, Any]:
    ident = f"KU-MOR-{index:03d}"
    source_id = CASE_SOURCE[area["slug"]]
    if case is None:
        source_id = MISSING_SOURCE.get(area["slug"], source_id)
        classic = CLASSIC_KNOWLEDGE.get(area["slug"])
        findings = [{"library_id": source_id,
            "claim_zh": f"{area['title_zh']}的書目或官方來源只供後續追查案例，尚無幾何量測。",
            "effect_or_value": None, "study_design": "來源範圍提示", "context_region": f"{area['city']}, {area['country']}",
            "locator": None, "claim_verification": "BIBLIOGRAPHIC_SCOPE_ONLY", "limitations_zh": "沒有對應快照，沒有指標被估算。"}]
        if classic:
            findings.append({"library_id": classic["library_id"], "claim_zh": classic["claim"],
                "effect_or_value": None, "study_design": "經典都市形態概念；待獨立交叉核對", "context_region": "跨城市理論",
                "locator": None, "claim_verification": "CANONICAL_CROSS_CHECK_PENDING",
                "limitations_zh": "只提供生成前的理論閱讀線索，不替代本案例幾何資料或本基地設計判斷。"})
        return {
            "id": ident, "domain": "MOR", "subtopic": "形態先例庫；待補幾何的案例入口",
            "type": "case", "title_zh": area["title_zh"], "title_en": area["title_en"],
            "summary_zh": f"{area['title_zh']}的 {area['area_ha']} ha 窗口仍缺完整 OSM 幾何，現階段無法量測圖底、街廓或量體分布；{CASE_INTERPRETATIONS[area['slug']]}目前保留資料缺口，案例名稱不充當形態值。",
            "key_points_zh": [area["boundary_note_zh"], f"{area['title_zh']}的高度、街廓、水岸距離和建築類型都未取得。"],
            "evidence": {"strength": "CASE_EVIDENCE", "findings": findings},
            "values": [], "design_implications_zh": [f"為{area['title_zh']}取得足跡、主街和水體幾何後再判斷生成參數。", f"先確認{area['title_zh']}取樣窗與官方案例範圍是否對應，再決定比較用途。"],
            "design_options": [], "applies_when_zh": f"用來追蹤{area['title_zh']}尚未完成的先例資料取得狀態。",
            "not_applicable_when_zh": f"沒有{area['title_zh']}的實測值，不用於量體參數選擇。",
            "debates_zh": f"在{area['title_zh']}完整幾何到位前，案例名稱不能替代空間測量或相似性判斷。",
            "sources": [citation(source_id), citation(CASE_SOURCE[area["slug"]])] + ([citation(classic["library_id"])] if classic else []), "source_count_flag": "MULTI_SOURCE",
            "tradition": "都市形態先例與跨城市指標", "region": f"{area['city']}, {area['country']}",
            "claim_verification": "BIBLIOGRAPHIC_SCOPE_ONLY",
            "curriculum_refs": [{"school": "TU Delft", "course": "Design of the Urban Fabric", "topic": f"待補實測：{area['title_zh']}"}],
            "version": "kb4-precedents-2026-10-09",
            "check": {"method_zh": "目前不計算形態指標；收到完整建築、道路和水體幾何後，在明列研究窗內重跑。",
                "inputs": ["完整 OSM 幾何回應", "研究窗多邊形"], "logic_zh": "缺資料時寫未取得，不使用記憶、目測或案例文字代替。",
                "limitations_zh": "未量測案例不產生圖底圖，也不納入 Spacematrix 散布圖。"},
            "case": {"location": f"{area['title_en']}, {area['city']}, {area['country']}", "period": "未確認",
                "area_ha": area["area_ha"], "fsi": None, "gsi": None, "program_mix": "未取得",
                "key_strategies_zh": [], "outcomes_zh": [], "critiques_zh": [f"{area['title_zh']}的 OSM 幾何未取得，所有形態指標均未量測。"]},
        }
    m = case["metrics"]
    floor_note = m["floor_conversion_note"].replace("缺值不補猜", f"{area['title_zh']}的缺值不補猜")
    typologies = m["block_type_mix"]
    dominant = max(typologies, key=lambda key: typologies[key]["block_count"]) if m["typology_sample_count"] else "完整街廓樣本不足"
    dom_count = typologies[dominant]["block_count"] if m["typology_sample_count"] else 0
    gap = m["street_width_building_gap_m"]
    gap_mid = fmt(gap.get("median") if isinstance(gap, dict) else None)
    fsi_clause = (f"可比 FSI 為 {fmt(m['FSI_known_floor_area_lower_bound'])}"
                  if m["comparison_eligible"]
                  else f"已知樓層 FSI 下限為 {fmt(m['FSI_known_floor_area_lower_bound'])}，高度或空間覆蓋未達比較門檻")
    summary = (
        f"{CASE_INTERPRETATIONS[area['slug']]}本次從 {fmt(m['land_area_m2'])} m² 陸地範圍內解析 {m['building_count']} 棟建築、合併成 {m['building_mass_count_after_merge_0_5m']} 個量體，"
        f"由主要街道切出 {m['block_count']} 個面積至少 1,000 m² 的街廓，其中完整窗內 {m['complete_block_count']} 個。陸地分母 GSI 為 {fmt(m['GSI'])}，{fsi_clause}；"
        f"在 {m['typology_sample_count']} 個完整街廓的自動判型樣本中，{dominant}最多（{dom_count} 個）；主要建築外牆間距中位數 {gap_mid} m。這份數值記錄僅對應{area['title_zh']}本次取樣窗與來源快照。"
    )
    sparse_case = m["spatial_coverage_status"] == "SPARSE_NOT_REPRESENTATIVE"
    classic = CLASSIC_KNOWLEDGE.get(area["slug"])
    design_implications = MOVES[area["slug"]] + ([classic["use"]] if classic else [])
    design_options = [
        {"option_zh": MOVES[area["slug"]][0], "tradeoff_zh": f"{area['title_zh']}的主要場地條件仍需實地核實；幾何參考不能取代現場資料。", "library_ids": ["OSM_KB4_PRECEDENTS", source_id]},
        {"option_zh": MOVES[area["slug"]][1], "tradeoff_zh": f"若 M4H 的基地寬度、用途或岸線條件不同於{area['title_zh']}，須重算幾何並由設計者取捨。", "library_ids": ["OSM_KB4_PRECEDENTS", "BILJECKI2022"]},
    ]
    outcomes = [
        f"陸地分母 GSI {fmt(m['GSI'])}；含映射水域分母 GSI {fmt(m['GSI_gross_water_inclusive'])}，兩者差異來自水域扣除口徑。",
        f"街廓共 {m['block_count']} 個，完整 {m['complete_block_count']} 個、截邊 {m['boundary_clipped_block_count']} 個；低於 1,000 m² 的碎片 {m['small_block_fragment_count_excluded_under_1000m2']} 個另計。完整街廓判型樣本為 {m['typology_sample_count']} 個，{dominant}分類 {dom_count} 個。",
    ]
    critiques = [
        f"{m['height_missing_building_count']} 棟建築沒有可用高度或樓層資料（覆蓋 {fmt(m['height_coverage_ratio'])}）；本案 FSI 狀態為 {m['FSI_comparability_status']}。",
        typology_case_note(area["title_zh"], m),
        QUESTIONS[area["slug"]],
    ]
    wd_mid = (m.get("building_wing_depth_proxy_m") or {}).get("median")
    if wd_mid is not None and (wd_mid < 10.0 or wd_mid > 16.0):
        critiques.append(f"{area['title_zh']} 的翼深代理中位數 {fmt(wd_mid)} m 偏離住宅常規範圍（約 10–16 m），標記為低信心，不可硬套於標準住宅量體生成。")
    if sparse_case:
        summary = f"{area['title_zh']} 的 OSM 回應有 {case['source']['osm_element_count']} 個元素、其中建築 {m['building_count']} 棟；以 {fmt(m['land_area_m2'])} m² 陸地窗得到的 GSI {fmt(m['GSI'])} 及街廓統計不具全區代表性。空間覆蓋狀態為 {m['spatial_coverage_status']}，所以不送入密度散布圖或形態參照。"
        design_options = [
            {"option_zh": f"暫不把{area['title_zh']}數值送入量體生成或密度比較。", "tradeoff_zh": "避免將稀疏回應讀作低密度；本案在補足圖資前不能供應完整型態。", "library_ids": ["OSM_KB4_PRECEDENTS", source_id]},
            {"option_zh": f"完整核對{area['title_zh']}的建築、主街和水域回應後再重建先例比較。", "tradeoff_zh": "還需先證明來源覆蓋，再重算街廓、翼深和 FSI。", "library_ids": ["OSM_KB4_PRECEDENTS", "3DBAG_KB4_HEIGHTS"]},
        ]
        outcomes = [f"快照回傳 {case['source']['osm_element_count']} 個 OSM 元素、{m['building_count']} 棟可解析建築；高度覆蓋 {fmt(m['height_coverage_ratio'])}。", "由於圖資稀疏，FSI、OSR 和代表性街廓分布不作全區解讀。"]
        critiques = [f"僅有 {m['building_count']} 棟建築落入 {fmt(m['land_area_m2'])} m² 陸地研究窗，空間覆蓋不足。", QUESTIONS[area["slug"]]]
    sources = [citation("OSM_KB4_PRECEDENTS"), citation("BILJECKI2022"), citation(source_id)]
    if area["country"] == "Netherlands":
        sources.append(citation("3DBAG_KB4_HEIGHTS"))
    if classic:
        sources.append(citation(classic["library_id"]))
    findings = source_findings(case)
    if classic:
        findings.append({"library_id": classic["library_id"], "claim_zh": classic["claim"],
            "effect_or_value": None, "study_design": "經典都市形態概念；待獨立交叉核對", "context_region": "跨城市理論",
            "locator": None, "claim_verification": "CANONICAL_CROSS_CHECK_PENDING",
            "limitations_zh": "用於提出可測試的設計問題，不視為本案例量測結果或通用規範。"})
    values = metric_value_rows(area, case)
    for name, val, unit in [
        ("OSM 建築數", m["building_count"], "棟"),
        ("高度覆蓋率", m["height_coverage_ratio"], "比例"),
        ("街廓中位面積", m["block_area_m2"].get("median"), "m²"),
        ("完整窗內街廓數", m["complete_block_count"], "個"),
        ("主要形態樣本建築數", m["principal_building_count_for_form"], "棟"),
    ]:
        library_id = "3DBAG_KB4_HEIGHTS" if area["country"] == "Netherlands" and name == "高度覆蓋率" else "OSM_KB4_PRECEDENTS"
        values.append({"name": name, "range": fmt(val), "unit": unit,
                       "context": context(area, case, name), "library_id": library_id})
    return {
        "id": ident, "domain": "MOR", "subtopic": "形態先例庫；實測圖底與量體指標",
        "type": "case", "title_zh": area["title_zh"], "title_en": area["title_en"], "summary_zh": summary,
        "key_points_zh": [area["boundary_note_zh"],
            f"OSM 日期 {m['snapshot_date']}；高度來源 {m['height_source']}；有效高度 {m['height_observed_building_count']}／{m['building_count']} 棟。",
            f"{area['title_zh']}量測說明：{floor_note}"],
        "evidence": {"strength": "CASE_EVIDENCE", "findings": source_findings(case)}, "values": values,
        "design_implications_zh": design_implications,
        "design_options": design_options,
        "applies_when_zh": f"比較 {area['title_zh']} 的足跡、街廓和岸線幾何，並為量體生成建立案例參照。",
        "not_applicable_when_zh": f"不可把{area['title_zh']}跨城數值當作本基地法規、設計目標或公共通行權證明。",
        "debates_zh": QUESTIONS[area["slug"]], "sources": sources, "source_count_flag": "MULTI_SOURCE",
        "tradition": "跨城市建築形態測量與都市設計案例", "region": f"{area['city']}, {area['country']}",
        "claim_verification": "BIBLIOGRAPHIC_SCOPE_ONLY",
        "curriculum_refs": [{"school": "TU Delft", "course": "Design of the Urban Fabric", "topic": f"形態先例比較：{area['title_zh']}"}],
        "version": "kb4-precedents-2026-10-09",
        "check": {"method_zh": "在研究窗扣除已映射水域後計算陸地分母，局部公尺投影；量體合併只用於翼深和類型，GSI／FSI 仍按去重原始足跡計。荷蘭案例僅以 BAG 識別碼連結 3DBAG 高度。",
            "inputs": ["研究窗和 OSM 錨點", "具 SHA-256 的 OSM 快照", "BAG 高度欄位或 OSM 樓層／高度標籤"],
            "logic_zh": "GSI 為足跡面積除扣除映射水域的陸地面積；FSI 為已知樓層建築足跡乘樓層數除同一陸地面積；高度覆蓋低於 80% 時標示下限且不可比較。",
            "limitations_zh": "未知高度不插補；映射以外水體仍在陸地分母內；翼深以合併量體 2A／周長估算，最小旋轉矩形短邊作交叉檢查。"},
        "case": {"location": f"{area['title_en']}, {area['city']}, {area['country']}",
            "period": "現況 OSM／3DBAG 快照；設計者與建成年代未由本輪可用來源完整確認。",
            "area_ha": area["area_ha"], "fsi": m["FSI_known_floor_area_lower_bound"], "gsi": m["GSI"],
            "program_mix": f"{area['title_zh']} 快照中可讀取到的 OSM 建築型別與明示用途標籤：{explicit_use_tags(case)}；未標註用途不猜補。可解析建築 {m['building_count']} 棟。",
            "key_strategies_zh": MOVES[area["slug"]],
            "outcomes_zh": [
                *outcomes,
            ],
            "critiques_zh": critiques},
    }

def note_for_legacy(area: dict[str, Any], case: dict[str, Any] | None, run: str) -> str:
    source_id = MISSING_SOURCE.get(area["slug"], CASE_SOURCE[area["slug"]]) if case is None else CASE_SOURCE[area["slug"]]
    record = read(LIB / f"{source_id}.json") if (LIB / f"{source_id}.json").is_file() else {}
    title = record.get("title", source_id)
    claim = record.get("claims", [{}])[0].get("claim_zh", "來源尚待查讀。").rstrip("。！？ ")
    if case is None:
        missing_rows = "\n".join(f"| {METRIC_NAMES[key]} | 未取得 | {unit} |" for key, unit in METRICS)
        figure = f"../../../../../../artifacts/kb4-precedents/{run}/figures/{area['slug']}-figure-ground.png"
        return f"""# {area['title_zh']}｜{area['title_en']}

## 研究窗與邊界

{area['boundary_note_zh']} 面積 {area['area_ha']} ha。本窗是按參照地名建立的研究範圍，不是官方開發邊界。

## 設計者、年代與規劃概念

已查證的來源線索為 {title}：{claim}。來源不足以確認本研究窗的實際設計者、年代或具體規劃概念，故保留空白。

## 量測狀態與圖底

完整 OSM 幾何未取得，以下指標均未測量。{LENSES[area['slug']]}

| 指標 | 實測值 | 單位或定義 |
|---|---|---|
{missing_rows}

![{area['title_zh']}研究窗；幾何資料未取得]({figure})

## 設計手法與對 M4H 的啟示

目前沒有形態證據可支撐本案的專屬量體手法；取得建築、道路和水岸幾何後，再比較街廓組織與建築翼深。對 M4H 的暫行用途僅為先例資料缺口清單，不能用來設定量體或岸線參數。

## 限制

OSM 請求在三次嘗試後仍未取得完整回應；狀態保留為未取得，不記作案例不存在。量測完成前，所有數值維持空缺。
"""
    m = case["metrics"]
    rows = "\n".join(f"| {METRIC_NAMES[key]} | {metric_display(key, m.get(key))} | {unit} |" for key, unit in METRICS)
    figure_path = ART / run / "figures" / f"{area['slug']}-figure-ground.png"
    figure = Path(os.path.relpath(figure_path, NOTES)).as_posix()
    moves = "\n".join(f"- {line}" for line in MOVES[area["slug"]])
    return f"""# {area['title_zh']}｜{area['title_en']}

## 研究窗與邊界

{area['boundary_note_zh']} 面積 {area['area_ha']} ha；邊界見 study-areas.geojson。本窗不是官方開發邊界。

## 設計者、年代與規劃概念

已查證來源：{title}。該來源可支持的內容為：{claim} 本輪資料未能確認實際設計者與建成年代，因此不補寫姓名或日期；文獻作者不能直接視作設計者。

## OSM／3DBAG 實測

| 指標 | 實測值 | 單位或分布 |
|---|---:|---|
{rows}

高度有效 {m['height_observed_building_count']} 棟，缺值 {m['height_missing_building_count']} 棟，覆蓋率 {fmt(m['height_coverage_ratio'])}。FSI 只計可用樓層數或高度的建築，故為已知樓地板面積下限。樓層換算說明：{m['floor_conversion_note']}

OSM 快照 {case['source']['osm_raw_path']}；SHA-256 {case['source']['osm_sha256']}；時間戳 {m['snapshot_date']}。GSI、FSI 和 OSR 定義及判型規則見量測檔。街道寬度以主要建築外牆間距代理；翼深以排除輔助建物後之合併足跡 2A／周長代理，另附最小旋轉矩形短邊交叉檢查。

## 圖底關係

![{area['title_zh']}圖底關係]({figure})

## 由此量測提出的設計手法

{moves}

## 對 M4H 帶狀基地的啟示

{QUESTIONS[area['slug']]} 量測分布可作為生成器比較輸入；水岸權屬、實際通行、用途與法規仍須分別查證。

## 限制

OSM 覆蓋可能缺少建築、道路和岸線資料。水岸附近行人路徑標記不是合法通行證明。研究窗不是官方案界，數字也不是 M4H 法規。

## 書目

- {title}；來源 ID {source_id}。
- OpenStreetMap 快照；來源 ID OSM_KB4_PRECEDENTS。
- Biljecki 與 Chow，Global Building Morphology Indicators（2022）；來源 ID BILJECKI2022。
"""


def explicit_use_tags(case: dict[str, Any]) -> str:
    raw = read(ROOT / case["source"]["osm_raw_path"])
    building_types: collections.Counter[str] = collections.Counter()
    explicit_uses: collections.Counter[str] = collections.Counter()
    type_keys = ("building", "building:use")
    use_keys = ("amenity", "shop", "office", "industrial", "leisure", "tourism")
    for element in raw.get("elements", []):
        tags = element.get("tags", {})
        if "building" not in tags and "building:part" not in tags:
            continue
        for key in type_keys:
            value = tags.get(key)
            if value and value not in ("yes", "building"):
                building_types[f"{key}={value}"] += 1
        for key in use_keys:
            value = tags.get(key)
            if value:
                explicit_uses[f"{key}={value}"] += 1
    type_text = "、".join(f"{key} {count} 筆" for key, count in building_types.most_common(6)) or "未提供建築型別"
    use_text = "、".join(f"{key} {count} 筆" for key, count in explicit_uses.most_common(6)) or "未提供明示用途活動標籤"
    return f"建築型別：{type_text}；明示用途活動：{use_text}。"


def validate_case_note_repetition(notes: dict[str, str]) -> None:
    occurrences: dict[str, set[str]] = collections.defaultdict(set)
    for slug, content in notes.items():
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "|", "![")):
                continue
            stripped = re.sub(r"^[-*]\s+", "", stripped)
            for sentence in re.split(r"(?<=[。！？])", stripped):
                sentence = re.sub(r"\s+", " ", sentence).strip()
                if len(sentence) >= 18 and re.search(r"[\u4e00-\u9fff]", sentence):
                    occurrences[sentence].add(slug)
    repeated = [(sentence, sorted(slugs)) for sentence, slugs in occurrences.items() if len(slugs) > 3]
    if repeated:
        details = "\n".join(f"{len(slugs)} cases: {sentence}" for sentence, slugs in repeated)
        raise ValueError(f"case note has repeated narrative sentences (>3):\n{details}")


def note_for(area: dict[str, Any], case: dict[str, Any] | None, run: str,
             failure: dict[str, Any] | None = None) -> str:
    source_id = MISSING_SOURCE.get(area["slug"], CASE_SOURCE[area["slug"]]) if case is None else CASE_SOURCE[area["slug"]]
    record = read(LIB / f"{source_id}.json") if (LIB / f"{source_id}.json").is_file() else {}
    title = record.get("title", source_id)
    claim = record.get("claims", [{}])[0].get("claim_zh", "來源尚待查讀。").rstrip("。！？ ")
    figure_path = ART / run / "figures" / f"{area['slug']}-figure-ground.png"
    figure = Path(os.path.relpath(figure_path, NOTES)).as_posix()
    if case is None:
        failure = failure or {}
        attempts = failure.get("attempt_count", "未記錄")
        statuses = failure.get("http_statuses", [])
        status_text = "、".join(map(str, statuses)) if statuses else "沒有可保存的 HTTP 回應碼"
        missing_rows = "\n".join(f"| {METRIC_NAMES[key]} | 未取得 | {unit} |" for key, unit in METRICS)
        classic = CLASSIC_KNOWLEDGE.get(area["slug"])
        classic_section = (f"## 經典形態知識（待指揮官交叉核對）\n\n{classic['claim']}\n\n"
                           f"對{area['title_zh']}而言，這項命題只引導可測試問題，不能補足缺少的 OSM 幾何。\n\n") if classic else ""
        return f"""# {area['title_zh']}｜{area['title_en']}

## 研究窗與邊界

{area['boundary_note_zh']} 研究窗面積為 {area['area_ha']} ha；多邊形座標與選取依據收在 study-areas.geojson 和 study-areas.json。

## 設計者、年代與規劃概念

書目線索《{title}》可支持的範圍是：{claim}。這條記錄沒有把 {area['title_zh']} 研究窗連到具名設計者、完工年份或完整規劃理念，因此這些欄位保持未確認。

## 量測狀態與圖底

{area['title_zh']} 的 OSM 幾何在 {attempts} 次請求後仍未取得，回應碼為 {status_text}；表內各欄因此都是未取得，不能解讀成零。{LENSES[area['slug']]}

| 指標 | 實測值 | 單位或定義 |
|---|---:|---|
{missing_rows}

![{area['title_zh']}研究窗；幾何資料未取得]({figure})

## 設計手法與對 M4H 的啟示

對 {area['title_zh']} 暫不提出以數值支撐的量體手法；目前可做的工作，是先保留本案作為補抓建築與道路幾何的缺口。{QUESTIONS[area['slug']]}

{classic_section}## 取得條件與限制

由於 {area['title_zh']} 沒有完整 OSM 幾何，本頁不給出形態比較值；HTTP {status_text} 是本輪請求狀態，不表示案例不存在。
"""
    m = case["metrics"]
    metric_rows = []
    for key, unit in METRICS:
        value = metric_display(key, m.get(key))
        if key == "FSI_known_floor_area_lower_bound" and not m.get("comparison_eligible"):
            value += "；下限或空間覆蓋不足，不可比較"
        if key == "building_wing_depth_proxy_m":
            wd_mid = (m.get("building_wing_depth_proxy_m") or {}).get("median")
            if wd_mid is not None and (wd_mid < 10.0 or wd_mid > 16.0):
                value += "；低信心（偏離住宅常規 10–16 m）"
        metric_rows.append(f"| {METRIC_NAMES[key]} | {value} | {unit} |")
    for label, key, unit in [
        ("陸地分母面積（扣除已映射水域）", "land_area_m2", "m²"),
        ("GSI（含映射水域分母）", "GSI_gross_water_inclusive", "無量綱"),
        ("FSI 下限（含映射水域分母）", "FSI_gross_water_inclusive_lower_bound", "無量綱"),
        ("映射水域面積", "mapped_water_area_m2", "m²"),
        ("原始足跡棟數／合併量體數", "building_mass_count_after_merge_0_5m", "棟／量體"),
        ("翼深交叉檢查：最小旋轉外接矩形短邊", "building_wing_depth_crosscheck_minimum_rotated_rectangle_short_side_m", "m；分布"),
        ("完整窗內街廓數", "complete_block_count", "個"),
        ("完整街廓面積中位數", "block_area_m2", "m²"),
        ("低於 1,000 m² 排除碎片數／面積", "small_block_fragment_count_excluded_under_1000m2", "個"),
        ("未分類街廓比例", "unclassified_block_share", "比例"),
    ]:
        metric_rows.append(f"| {label} | {metric_display(key, m.get(key))} | {unit} |")
    rows = "\n".join(metric_rows)
    moves = "\n".join(f"- {line}" for line in MOVES[area["slug"]])
    sparse = (f"OSM 回應共 {case['source']['osm_element_count']} 個元素、僅解析 {m['building_count']} 棟建築；不代表整個研究窗。"
              if m["spatial_coverage_status"] == "SPARSE_NOT_REPRESENTATIVE" else None)
    warning = f"\n\n**資料覆蓋提醒：** {sparse}" if sparse else ""
    use_tags = explicit_use_tags(case)
    if m["FSI_known_floor_area_lower_bound"] is None:
        quality_clause = (
            f"{area['title_zh']} 有 {m['building_count']} 棟 OSM 建築標記、{m['height_observed_building_count']} 棟可取得高度或樓層資訊（覆蓋率 {fmt(m['height_coverage_ratio'])}）；"
            f"目前沒有可計算的 FSI，{m['height_missing_building_count']} 棟高度或樓層缺值。"
        )
    else:
        quality_clause = (
            f"{area['title_zh']} 有 {m['building_count']} 棟 OSM 建築標記、{m['height_observed_building_count']} 棟可取得高度或樓層資訊（覆蓋率 {fmt(m['height_coverage_ratio'])}）；"
            f"FSI 下限 {fmt(m['FSI_known_floor_area_lower_bound'])} 只計已知樓層建築，{m['height_missing_building_count']} 棟高度或樓層缺值。"
        )
    fsi_limit_clause = (
        f"{area['title_zh']} 的高度覆蓋率為 {fmt(m['height_coverage_ratio'])}；已知樓層 FSI 為下限，依狀態 {m['FSI_comparability_status']} 排除跨案比較。"
        if not m["comparison_eligible"]
        else f"{area['title_zh']} 的高度覆蓋率為 {fmt(m['height_coverage_ratio'])}，已知高度達到本輪 80% 比較門檻；FSI 仍只以已知高度建物計算。"
    )
    methods_clause = (
        f"{area['title_zh']} 的街廓樣本依 primary、secondary、tertiary、residential、unclassified、living_street 及非面狀且有名稱或編號的 pedestrian 主街切分；"
        f"footway、path、cycleway、service 在此案不構成街廓邊界。其研究窗共觀察 {m['block_count']} 個街廓，完整窗內 {m['complete_block_count']} 個；完整街廓面積與類型不使用截邊街廓。"
        f"在{area['title_zh']}的主街切分下，小於 1,000 m² 的碎片共 {m['small_block_fragment_count_excluded_under_1000m2']} 個，另列以免混入街廓分布。"
        f"邊長中位數取主要街道交叉口間已合併街段 {fmt(m['block_edge_length_m'].get('median'))} m，排除端點落在研究窗邊界的街段。翼深樣本排除明示的棚屋、車庫、雨棚等輔助建物；其餘足跡按相距不超過 0.5 m 合併後，以 2×面積÷周長估計，中位數 {fmt(m['building_wing_depth_proxy_m'].get('median'))} m，"
        f"最小旋轉外接矩形短邊交叉檢查中位數 {fmt(m['building_wing_depth_crosscheck_minimum_rotated_rectangle_short_side_m'].get('median'))} m。兩者皆為平面代理，仍需另以{area['title_zh']}實測立面或剖面檢驗。"
    )
    wing_depth_caveat = ""
    wd_mid = (m.get("building_wing_depth_proxy_m") or {}).get("median")
    if (m.get("building_wing_depth_proxy_under_4m_sample_share") or 0) >= 0.5:
        wing_depth_caveat = (
            f"\n\n**翼深代理品質提醒：**{area['title_zh']}的 2A／周長樣本中有 {fmt(m['building_wing_depth_proxy_under_4m_sample_count'])}/{fmt(m['building_wing_depth_proxy_m'].get('sample_count'))}（{fmt(m['building_wing_depth_proxy_under_4m_sample_share'])}）低於 4 m；"
            f"主要量體中 {fmt(m['principal_mass_under_100m2_sample_count'])}/{fmt(m['principal_mass_count_after_merge_0_5m'])}（{fmt(m['principal_mass_under_100m2_sample_share'])}）小於 100 m²。這些 OSM 建物仍保留在原始樣本，標籤不足以逐一判定其是否為主體建築；中位數低於本任務的粗略住宅參照 8–16 m，須另做局部圖面或現場核查，該參照不是基地法規。"
        )
    elif wd_mid is not None and (wd_mid < 10.0 or wd_mid > 16.0):
        wing_depth_caveat = (
            f"\n\n**翼深代理品質提醒：**{area['title_zh']}的翼深代理中位數為 {fmt(wd_mid)} m，偏離一般住宅常規範圍（約 10–16 m），在此標記為低信心且不硬套於標準住宅量體生成。"
        )
    osm_elements = case["source"]["osm_element_count"]
    if sparse:
        moves = f"- 此回應只解析 {m['building_count']} 棟建築，不能由現有足跡歸納完整的{area['title_zh']}量體原型。\n- 完成建築、主街和水域幾何覆蓋核對前，不將當前密度值送入生成參數。"
        m4h_implication = f"{sparse} 量體生成前先確定來源覆蓋足以描述{area['title_zh']}，再談街廓或岸線原型。"
    else:
        m4h_implication = (
            f"{CASE_INTERPRETATIONS[area['slug']]}把陸地分母 GSI {fmt(m['GSI'])}、含水 GSI {fmt(m['GSI_gross_water_inclusive'])}、"
            f"FSI 狀態 {m['FSI_comparability_status']}、{m['block_count']} 個主要街道街廓交給生成器作案例條件；設計者再判斷與 M4H 的寬度、用途和岸線是否相符。"
        )
    classic = CLASSIC_KNOWLEDGE.get(area["slug"])
    classic_section = (f"## 經典形態知識（待指揮官交叉核對）\n\n{classic['claim']}\n\n"
                       f"生成用途：{classic['use']}\n\n") if classic else ""
    typology_note = typology_case_note(area["title_zh"], m)
    return f"""# {area['title_zh']}｜{area['title_en']}

## 研究窗與邊界

{area['boundary_note_zh']} 本研究窗面積 {area['area_ha']} ha，依命名 OSM 參照物周邊的公尺矩形取樣；它不替代官方開發案界。{warning}

## 設計者、年代與規劃概念

《{title}》是目前可核對到的 {area['title_zh']} 書目線索；其記錄內容是：{claim}。此來源未直接辨識 {area['title_zh']} 研究窗的設計團隊或建成年份，所以不以文獻作者或量測快照推補這些歷史資料。

## OSM／3DBAG 實測

| 指標 | 實測值 | 單位或分布 |
|---|---:|---|
{rows}

{quality_clause} {area['title_zh']} 的樓層標記直接採用可用樓層欄位；只有高度欄位可用時，才依 {m['floor_conversion_assumption_m']} m／層換算，這是明示假設。

快照 {case['source']['osm_raw_path']} 含 {osm_elements} 個 OSM 元素，SHA-256 為 {case['source']['osm_sha256']}，資料時間戳 {m['snapshot_date']}。本案用途只按這批元素內已存在的用途標籤列出：{use_tags}

研究窗陸地面積 {fmt(m['land_area_m2'])} m²；GSI、FSI 和 OSR 使用扣除已映射水域後的面積作分母。另列含水分母的 GSI {fmt(m['GSI_gross_water_inclusive'])} 與 FSI 下限 {fmt(m['FSI_gross_water_inclusive_lower_bound'])}。{area['title_zh']} 若只有線狀水道圖徵，便不推猜水寬；OSM 未畫出的水域仍可能留在陸地分母。

{area['title_zh']} 的 FSI 狀態是 **{m['FSI_comparability_status']}**。{fsi_limit_clause}

{methods_clause}
{wing_depth_caveat}

## 圖底關係

![{area['title_zh']}圖底關係]({figure})

## 由此量測提出的設計手法

{moves}

{classic_section}## 設計爭點

{QUESTIONS[area['slug']]}就{area['title_zh']}的完整街廓樣本而言，未分類比例為 {fmt(m['unclassified_block_share'])}；判型檢核記錄：{typology_note}

## 對 M4H 帶狀基地的啟示

{m4h_implication}

## 限制

{area['title_zh']} 的 {osm_elements} 個 OSM 元素與高度覆蓋率 {fmt(m['height_coverage_ratio'])} 限定了本次統計母體；OSM 缺畫的建築、道路、岸線和建築高度不會自動補入。近水行人路徑標記 {m.get('water_access', {}).get('nearby_mapped_route_count', 0)} 條只表示圖資狀態，不確認所有權或公共通行權。

## 書目

- {area['title_zh']} 的案例範圍線索：《{title}》；來源 ID {source_id}。
- {area['title_zh']} 的建築與道路觀察：OpenStreetMap 快照；來源 ID OSM_KB4_PRECEDENTS。
- {area['title_zh']} 的量測定義參照：Biljecki 與 Chow，Global Building Morphology Indicators（2022）；來源 ID BILJECKI2022。
"""

PRECEDENT_GROUPS = {
    "水岸帶狀地": ["borneo-sporenburg", "java-eiland", "knsm-eiland", "ijburg-haveneiland", "vastra-hamnen", "hammarby-sjostad"],
    "大型港區": ["kop-van-zuid-wilhelminapier", "katendrecht", "lloydkwartier", "hafencity-dalmannkai", "nordhavn"],
    "一般街區": ["spangen-justus-van-effen", "funenpark", "vauban-freiburg", "barcelona-eixample", "amsterdam-oud-zuid"],
}


def build_t06_document(areas: list[dict[str, Any]], cases: dict[str, dict[str, Any]],
                       failures: list[dict[str, Any]], run: str) -> str:
    area_map = {row["slug"]: row for row in areas}
    failure_map = {row["slug"]: row for row in failures}
    group_sections: list[str] = []
    group_notes = {
        "水岸帶狀地": "先看岸線是否沿長邊延展、橫向街路如何接岸，以及扣除水域後可建陸地如何連續。研究窗短邊只是取樣盒尺寸，不是岸到岸距。",
        "大型港區": "比較碼頭地塊、主街網和大體量的接合；分期發展與高度缺值都會影響窗口均值，須連同街廓和高度覆蓋判讀。",
        "一般街區": "提供非港區的住宅、綠地和網格基準；不具相似岸線條件時，可用來檢查街牆、院落和支路組織。",
    }
    for group, slugs in PRECEDENT_GROUPS.items():
        rows = ["| 先例 | 研究窗短×長邊 m | 面積 ha | 狀態 | 建築／量體 | 街廓 | 陸地 GSI | 含水 GSI | FSI／可比性 | 翼深中位 m | 主導類型 |",
                "|---|---:|---:|---|---:|---:|---:|---:|---|---:|---|"]
        measured: list[dict[str, Any]] = []
        for slug in slugs:
            area = area_map[slug]
            case = cases.get(slug)
            short_side, long_side = sorted((area["width_m"], area["height_m"]))
            if case is None:
                fail = failure_map.get(slug, {})
                state = f"未取得；{fail.get('status', '狀態未知')}；HTTP {fail.get('http_statuses', [])}"
                rows.append(f"| {area['title_zh']} | {short_side}×{long_side} | {area['area_ha']} | {state} | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未分類 |")
                continue
            m = case["metrics"]
            dominant = max(m["block_type_mix"], key=lambda key: m["block_type_mix"][key]["block_count"]) if m["typology_sample_count"] else "完整街廓樣本不足"
            state = "快照稀疏；不作代表" if m["spatial_coverage_status"] == "SPARSE_NOT_REPRESENTATIVE" else ("高度可比" if m["comparison_eligible"] else "FSI 下限不可比")
            fsi_text = fmt(m["FSI_known_floor_area_lower_bound"])
            if not m["comparison_eligible"]:
                fsi_text += "（下限；不可比）"
            wd_mid = m["building_wing_depth_proxy_m"].get("median")
            wd_text = fmt(wd_mid)
            if wd_mid is not None and (wd_mid < 10.0 or wd_mid > 16.0):
                wd_text += "（低信心）"
            rows.append(f"| {area['title_zh']} | {short_side}×{long_side} | {area['area_ha']} | {state} | {m['building_count']}／{m['building_mass_count_after_merge_0_5m']} | {m['block_count']} | {fmt(m['GSI'])} | {fmt(m['GSI_gross_water_inclusive'])} | {fsi_text} | {wd_text} | {dominant} |")
            measured.append({"area": area, "case": case, "short": short_side})
        eligible = [item for item in measured if item["case"]["metrics"]["comparison_eligible"]]
        if eligible:
            gsi = [item["case"]["metrics"]["GSI"] for item in eligible if item["case"]["metrics"]["GSI"] is not None]
            fsi = [item["case"]["metrics"]["FSI_known_floor_area_lower_bound"] for item in eligible if item["case"]["metrics"]["FSI_known_floor_area_lower_bound"] is not None]
            widths = [item["short"] for item in eligible]
            density = f"通過高度與空間覆蓋門檻的案例，研究窗短邊為 {min(widths)}–{max(widths)} m，陸地 GSI 為 {fmt(min(gsi))}–{fmt(max(gsi))}，FSI 為 {fmt(min(fsi))}–{fmt(max(fsi))}。這些只是可比樣本範圍，不是類型目標。"
        else:
            density = "此組沒有同時通過高度與空間覆蓋門檻的案例，不提供 FSI 範圍。"
        group_sections.extend([f"## {group}", "", group_notes[group], "", density, "", *rows, ""])

    width_rows = ["| 先例 | 研究窗短×長邊 m | ha | 陸地 GSI | FSI 狀態 | OSM 明示用途 | 適合比對的設計問題 |", "|---|---:|---:|---:|---|---|---|"]
    tactic_rows = []
    for index, area in enumerate(areas, 81):
        slug = area["slug"]
        case = cases.get(slug)
        short_side, long_side = sorted((area["width_m"], area["height_m"]))
        if case is None:
            fail = failure_map.get(slug, {})
            width_rows.append(f"| {area['title_zh']} | {short_side}×{long_side} | {area['area_ha']} | 未取得 | 未取得 | 未取得 | {CASE_INTERPRETATIONS[slug]} |")
            tactic_rows.append(f"- **{area['title_zh']}**（KU-MOR-{index:03d}）：{fail.get('status', '資料未取得')}；目前不從案例名稱推寫量體手法。")
            continue
        m = case["metrics"]
        fsi_state = "COMPARABLE" if m["comparison_eligible"] else f"{m['FSI_comparability_status']}；空間狀態 {m['spatial_coverage_status']}"
        width_rows.append(f"| {area['title_zh']} | {short_side}×{long_side} | {area['area_ha']} | {fmt(m['GSI'])} | {fsi_state} | {explicit_use_tags(case)} | {CASE_INTERPRETATIONS[slug]} |")
        dominant = max(m["block_type_mix"], key=lambda key: m["block_type_mix"][key]["block_count"]) if m["typology_sample_count"] else "完整街廓樣本不足"
        wd_mid = m["building_wing_depth_proxy_m"].get("median")
        wd_text = fmt(wd_mid)
        if wd_mid is not None and (wd_mid < 10.0 or wd_mid > 16.0):
            wd_text += "（低信心）"
        tactic_rows.append(
            f"- **{area['title_zh']}**（KU-MOR-{index:03d}）：{MOVES[slug][0]} 實測可核對 {m['block_count']} 個街廓（完整 {m['complete_block_count']} 個）、"
            f"翼深中位 {wd_text} m 與主導類型 {dominant}；{MOVES[slug][1]}"
        )
    pending_classics = [f"- **{area_map[slug]['title_zh']}**：{item['claim']}" for slug, item in CLASSIC_KNOWLEDGE.items()]
    fsi_eligible = [case for case in cases.values() if case["metrics"].get("comparison_eligible")]
    if fsi_eligible:
        fsi_values = [float(case["metrics"]["FSI_known_floor_area_lower_bound"]) for case in fsi_eligible]
        gsi_values = [float(case["metrics"]["GSI"]) for case in fsi_eligible]
        density_range = (f"通過高度和空間覆蓋門檻的 {len(fsi_eligible)} 案，陸地 FSI 實測範圍 "
                         f"{fmt(min(fsi_values))}–{fmt(max(fsi_values))}，陸地 GSI 範圍 {fmt(min(gsi_values))}–{fmt(max(gsi_values))}。")
    else:
        density_range = "本輪沒有同時通過高度與空間覆蓋門檻的案例，不發布跨案例 FSI 或 GSI 範圍。"
    return "\n".join([
        "# MOR-T06｜形態先例比較與帶狀基地適配", "", "## 範圍與量測口徑", "",
        f"本綜述使用 {len(areas)} 個約 5–20 ha 的研究多邊形；每窗由命名 OSM 參照物和明列長短邊設定，理由、座標及幾何雜湊見 study-areas.json。已完成量測 {len(cases)} 案，仍有資料缺口 {len(failures)} 案。取樣範圍不是官方開發界。",
        "", "GSI、FSI、OSR 以扣除 OSM 已映射水域後的陸地面積作分母，另列含水口徑以看出分母差異。荷蘭高度只採 BAG 識別碼連結的 3DBAG；其他城市採 OSM 樓層標記，或在有明確 height 值時按 3.0 m／層換算。高度缺值不插補。",
        "", "高度覆蓋率低於 80% 時，FSI 保留為已知量體下限且不可比較；稀疏空間快照也不列入散布圖。這些數字是 OSM／3DBAG 觀察值，不是 M4H 或其他基地法規。",
        "", "## 三類先例對照", "", *group_sections,
        "## 按基地寬度、密度與用途選擇案例", "",
        "先按目標地塊的可建短邊、水岸接觸形式和主要用途找尺度相近的研究窗，再以 GSI、可比 FSI、街廓和翼深比較量體。若 OSM 未明示用途，應另行補查，不從案例名稱推斷。各列提供可比的設計問題，是否適用由設計者裁定。",
        "", *width_rows, "", density_range, "",
        "## 由實測輪廓整理的形態手法", "", *tactic_rows, "",
        "## 經典形態知識（待指揮官逐項交叉核對）", "",
        "以下命題可由多種教材與原典交叉查核；對應知識單元標成 CANONICAL_CROSS_CHECK_PENDING，待指揮官核對後定稿。", "", *pending_classics, "",
        "## M4H 量體生成前的閱讀次序", "",
        "1. 按岸線狀態、基地寬度及用途選取先例，檢查研究窗與目標地塊是否在形狀尺度上相稱。",
        "2. 生成器讀取足跡圖、合併量體、主街街廓、陸地 GSI、FSI 可比性和高度缺值；低覆蓋案例不作密度條件。",
        "3. 把經典理論命題轉成可檢驗的設計問題，不當成固定形狀或參數；設計者決定採用、調整或拒絕。",
        "", "## 圖件與限制", "",
        f"16 張單案圖、並列比較圖與 FSI–GSI 散布圖位於 {run}/figures/；全組使用 1:5,000 等效比例尺和繁體中文標題、圖例及比例尺。散布圖只畫 FSI、GSI；網絡密度 N 未算，不能代表完整三變數 Spacematrix 分類。",
        "", "設計者、年代和規劃概念只有在書目或官方來源直接支持時才寫入；資料不足就留白。水岸路徑標籤不確認權屬或合法公共通行。未取得幾何表示資料缺口，不表示案例不存在。", ""
    ])


def method_unit() -> dict[str, Any]:
    return {
        "id": "KU-MOR-097", "domain": "MOR", "subtopic": "Spacematrix 變數與圖表解讀",
        "type": "method", "title_zh": "Spacematrix 的 FSI、GSI 與網絡密度 N；二維圖只能展示其中兩軸",
        "title_en": "Spacematrix variables FSI, GSI and network density N; a two-axis plot shows only two",
        "summary_zh": "OpenAlex 所收錄的 2017 年論文摘要列出 FSI、GSI 和網絡密度 N 作為 Spacematrix 的核心變數，並以聚類區分建築類型和街道模式。本先例庫只繪製 FSI–GSI 兩軸，因此圖是三變數框架的投影，不能當作完整分類。N 本次未計算，避免將點位誤稱為完整 Spacematrix 類型。FSI 又受高度缺值和 3.0 m／層換算假設影響。",
        "key_points_zh": ["FSI 和 GSI 使用同一研究窗面積，但高度缺值使 FSI 只代表已知量體下限。", "第三變數 N 未算；散布圖只供兩個指標之間比較。", "套用類型前須確認街網長度、研究窗與道路分類一致。"],
        "evidence": {"strength": "THEORETICAL", "findings": [
            {"library_id": "SPACEMATRIX_VARS2017", "claim_zh": "OpenAlex 摘要列出 FSI、GSI、network density N 三項核心密度變數，並報告以聚類辨識建築與街道模式。",
             "effect_or_value": None, "study_design": "多變數聚類分析", "context_region": "跨城市形態分類", "locator": None,
             "claim_verification": "CANONICAL_CROSS_CHECK_PENDING", "limitations_zh": "此處僅使用 OpenAlex 書目與摘要，待指揮官逐條獨立交叉核對。"},
            {"library_id": "BILJECKI2022", "claim_zh": "跨城市形態指標需公開資料來源、尺度與計算規則，才能重現其比較。",
             "effect_or_value": None, "study_design": "形態指標研究", "context_region": "全球多城市資料", "locator": None,
             "claim_verification": "ABSTRACT_REVIEW", "limitations_zh": "不從該研究推導本基地密度門檻。"}]},
        "values": [], "design_implications_zh": ["在散布圖旁列出高度覆蓋率和街網狀態。", "N 尚未取得時不套用三變數分類標籤。"],
        "design_options": [
            {"option_zh": "先用 FSI–GSI 對照案例，N 列為未取得。", "tradeoff_zh": "便於閱讀，但少一個關鍵街網變數。"},
            {"option_zh": "統一道路類別後補算 N，再做三變數分類。", "tradeoff_zh": "增加拓樸和範圍檢查工作。"}],
        "applies_when_zh": "解讀本先例庫中 FSI–GSI 的案例點位和方法界線。",
        "not_applicable_when_zh": "不把散點距離、象限或分群直接轉成品質排序或 M4H 設計門檻。",
        "debates_zh": "二維圖較容易比較，但若省略網絡密度，會掩蓋街網差異。",
        "sources": [citation("SPACEMATRIX_VARS2017"), citation("BILJECKI2022")], "source_count_flag": "MULTI_SOURCE",
        "tradition": "城市密度與街網分類", "region": "跨城市形態分類",
        "claim_verification": "CANONICAL_CROSS_CHECK_PENDING",
        "curriculum_refs": [{"school": "TU Delft", "course": "Design of the Urban Fabric", "topic": "Spacematrix 變數與散布圖"}],
        "version": "kb4-precedents-2026-10-09",
        "check": {"method_zh": "在同一個研究窗中以已知建築層數計 FSI、以足跡面積計 GSI；N 另由已定義的道路中心線長度和研究窗面積計算。",
            "inputs": ["研究窗公頃數", "足跡與樓層資料", "統一道路分類與線長"],
            "logic_zh": "FSI 和 GSI 只構成三個變數中的兩項；在 N 補算前，圖表不標註三維群集。",
            "limitations_zh": "FSI 受高度缺值影響，N 未計算；論文摘要主張需跨來源核對。"},
    }

def overpass_retry_audit() -> list[str]:
    receipts_path = ART / "http-request-receipts.jsonl"
    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    if receipts_path.is_file():
        for line in receipts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            receipt = json.loads(line)
            if "overpass-api.de" not in receipt.get("url", ""):
                continue
            query = (receipt.get("request_data") or {}).get("data", "")
            if query:
                grouped[hashlib.sha256(query.encode("utf-8")).hexdigest()].append(receipt)

    features = json.loads((ART / "study-areas.geojson").read_text(encoding="utf-8")).get("features", [])
    audit = []
    for query_hash, rows in sorted(grouped.items()):
        if len(rows) <= 3:
            continue
        query = (rows[0].get("request_data") or {}).get("data", "")
        match = re.search(r'way\["building"\]\(([^)]+)\)', query)
        case_title = "未能由座標配對先例"
        if match:
            south, west, north, east = map(float, match.group(1).split(","))
            lon, lat = (west + east) / 2, (south + north) / 2
            for feature in features:
                coords = feature.get("geometry", {}).get("coordinates", [[]])[0]
                if not coords:
                    continue
                xs = [point[0] for point in coords]
                ys = [point[1] for point in coords]
                if min(xs) <= lon <= max(xs) and min(ys) <= lat <= max(ys):
                    case_title = feature.get("properties", {}).get("title_zh", case_title)
                    break
        times = sorted(row.get("requested_at_utc", "時間未記錄") for row in rows)
        status_counts = collections.Counter(str(row.get("status_code", "未知")) for row in rows)
        statuses = "、".join(f"HTTP {status}×{count}" for status, count in sorted(status_counts.items()))
        audit.append(
            f"- **{case_title}**：完全相同查詢共 {len(rows)} 次（{statuses}；payload SHA-256 `{query_hash[:12]}…`）；"
            f"請求時間：{', '.join(times)}。此為歷史收據合計，超過每個精確查詢最多 3 次的上限；本輪未再重送。"
        )
    return audit


def build_report(areas: list[dict[str, Any]], cases: dict[str, dict[str, Any]], failures: list[dict[str, Any]], run: str) -> str:
    area_map = {row["slug"]: row for row in areas}
    failure_map = {row["slug"]: row for row in failures}
    old_path = ART / "runs/20261009T124328Z-51c34de6/morphometrics-by-case.json"
    old_cases = {}
    if old_path.is_file():
        old_cases = {row["slug"]: row for row in read(old_path).get("cases", [])}
    main_rows = ["| 先例 | 研究窗 ha | 國家 | OSM 狀態 | 建築／合併量體 | 陸地 GSI | 含水 GSI | 陸地 FSI | 高度覆蓋 | FSI 可比性 |", "|---|---:|---|---|---:|---:|---:|---:|---:|---|"]
    metric_rows = ["| 先例 | L 層 | OSR | 街廓數（完整） | 完整街廓面積中位 m² | 主要街段中位 m | 外牆間距中位 m | 翼深 2A／周長中位 m | MRR 短邊交叉中位 m | 翼深代理 <4 m 占比 | 量體 <100 m² 占比 | 至水距離中位 m | 水岸路徑標記 | 主導類型／未分類比例 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    change_rows = ["| 先例 | GSI 舊→新 | FSI 舊→新 | 翼深舊→新 m | 街廓數舊→新 | 邊長中位舊→新 m | 差異說明 |", "|---|---:|---:|---:|---:|---:|---|"]
    window_rows = ["| 先例 | 面積 ha | 研究窗長×短邊 m | 劃定方式 |", "|---|---:|---:|---|"]
    group_rows: dict[str, list[str]] = {}
    group_by_slug = {slug: group for group, slugs in PRECEDENT_GROUPS.items() for slug in slugs}
    labels = {"amsterdam": "阿姆斯特丹", "rotterdam": "鹿特丹", "hamburg": "漢堡", "malmo": "馬爾默", "stockholm": "斯德哥爾摩", "copenhagen": "哥本哈根", "freiburg": "弗萊堡", "barcelona": "巴塞隆納"}
    for area in areas:
        slug = area["slug"]
        case = cases.get(slug)
        old = old_cases.get(slug, {}).get("metrics", {})
        fail = failure_map.get(slug, {})
        country_zh = {"Netherlands": "荷蘭", "Germany": "德國", "Sweden": "瑞典", "Denmark": "丹麥", "Spain": "西班牙"}.get(area["country"], area["country"])
        short_side, long_side = sorted((area["width_m"], area["height_m"]), reverse=True)
        window_rows.append(f"| {area['title_zh']} | {area['area_ha']} | {long_side}×{short_side} | {area['boundary_note_zh']} |")
        if case is None:
            status = fail.get("status", "NOT_ACQUIRED")
            reason = fail.get("reason", "無完整 OSM 回應，沒有執行形態測量。")
            if "OSM source record and complete response are absent" in reason:
                reason = "OSM 來源記錄或完整回應缺失；未執行形態量測。"
            details = f"未取得；{status}；HTTP {fail.get('http_statuses', [])}；{reason}"
            main_rows.append(f"| {area['title_zh']} | {area['area_ha']} | {country_zh} | {details} | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 |")
            metric_rows.append(f"| {area['title_zh']} | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 未分類 |")
            old_case = old_cases.get(slug)
            if old_case:
                change_rows.append(f"| {area['title_zh']} | {fmt(old.get('GSI'))}→未取得 | {fmt(old.get('FSI_known_floor_area_lower_bound'))}→未取得 | {fmt(old.get('building_wing_depth_proxy_m', {}).get('median'))}→未取得 | {old.get('block_count', '未取得')}→未取得 | {fmt(old.get('block_edge_length_m', {}).get('median'))}→未取得 | 本輪資料仍未取得，舊值依錯誤方法保留為追查紀錄，不沿用作比較。 |")
            else:
                change_rows.append(f"| {area['title_zh']} | 未取得 | 未取得 | 未取得 | 未取得 | 未取得 | 新舊兩輪都沒有可比測量。 |")
            group_rows.setdefault(group_by_slug[slug], []).append(f"- **{area['title_zh']}**：{details}")
            continue
        m = case["metrics"]
        state = "已量測"
        if m["spatial_coverage_status"] == "SPARSE_NOT_REPRESENTATIVE":
            state = "快照稀疏；不代表全窗"
        fsi_note = fmt(m["FSI_known_floor_area_lower_bound"])
        if not m["comparison_eligible"]:
            fsi_note += "（下限；不可比）"
        source_status_zh = {
            "OBSERVED_DERIVED_FROM_COMPLETE_BATCH": "完整批次",
            "OBSERVED_CHUNKED_BBOX": "分塊查詢",
            "OBSERVED": "快照量測",
        }.get(case["source"]["osm_status"], case["source"]["osm_status"])
        main_rows.append(f"| {area['title_zh']} | {area['area_ha']} | {country_zh} | {state}；{source_status_zh} | {m['building_count']}／{m['building_mass_count_after_merge_0_5m']} | {fmt(m['GSI'])} | {fmt(m['GSI_gross_water_inclusive'])} | {fsi_note} | {fmt(m['height_coverage_ratio'])} | {m['FSI_comparability_status']} |")
        dominant = max(m["block_type_mix"], key=lambda key: m["block_type_mix"][key]["block_count"]) if m["typology_sample_count"] else "完整街廓樣本不足"
        metric_rows.append(
            f"| {area['title_zh']} | {fmt(m['L_area_weighted_known_building_floors'])} | {fmt(m['OSR_from_measured_GSI_and_known_FSI'])} | "
            f"{m['block_count']}（{m['complete_block_count']}） | {fmt(m['block_area_m2'].get('median'))} | {fmt(m['block_edge_length_m'].get('median'))} | "
            f"{fmt(m['street_width_building_gap_m'].get('median'))} | {fmt(m['building_wing_depth_proxy_m'].get('median'))} | "
            f"{fmt(m['building_wing_depth_crosscheck_minimum_rotated_rectangle_short_side_m'].get('median'))} | "
            f"{fmt(m.get('building_wing_depth_proxy_under_4m_sample_share'))} | {fmt(m.get('principal_mass_under_100m2_sample_share'))} | {fmt(m['building_to_mapped_water_distance_m'].get('median'))} | "
            f"{metric_display('water_access', m.get('water_access'))} | {dominant}；未分類 {fmt(m['unclassified_block_share'])} |"
        )
        old_case = old_cases.get(slug)
        if old_case:
            om = old_case["metrics"]
            cause = "維持前輪基準口徑（陸地分母、合併量體翼深、交叉口街段）。"
            if slug == "knsm-eiland":
                cause = "修正研究窗錨點至島核心，成功涵蓋住宅群量體與街廓，擺脫 v1 稀疏快照限制。"
            elif not m["comparison_eligible"]:
                cause += "高度缺值超過 20%，FSI 標為下限且不作比較。"
            change_rows.append(
                f"| {area['title_zh']} | {fmt(om.get('GSI'))}→{fmt(m.get('GSI'))} | "
                f"{fmt(om.get('FSI_known_floor_area_lower_bound'))}→{fmt(m.get('FSI_known_floor_area_lower_bound'))} | "
                f"{fmt(om.get('building_wing_depth_proxy_m', {}).get('median'))}→{fmt(m.get('building_wing_depth_proxy_m', {}).get('median'))} | "
                f"{om.get('block_count', '未取得')}→{m.get('block_count', '未取得')} | "
                f"{fmt(om.get('block_edge_length_m', {}).get('median'))}→{fmt(m.get('block_edge_length_m', {}).get('median'))} | {cause} |"
            )
        else:
            change_rows.append(f"| {area['title_zh']} | 無舊值→{fmt(m.get('GSI'))} | 無舊值→{fmt(m.get('FSI_known_floor_area_lower_bound'))} | 無舊值→{fmt(m.get('building_wing_depth_proxy_m', {}).get('median'))} | 無舊值→{m['block_count']} | 無舊值→{fmt(m.get('block_edge_length_m', {}).get('median'))} | 先前因 Overpass 504 逾時未取得完整來源，本輪 4×4 細切分塊並等待 slot 後首次完成實測。 |")
        group_rows.setdefault(group_by_slug[slug], []).append(
            f"- **{area['title_zh']}**：{CASE_INTERPRETATIONS[slug]}陸地 GSI {fmt(m['GSI'])}、"
            f"{m['block_count']} 個主要街道街廓，FSI 狀態 {m['FSI_comparability_status']}。"
        )
    measured_count = len(cases)
    eligible_count = sum(1 for case in cases.values() if case["metrics"].get("comparison_eligible"))
    fsi_values = [float(case["metrics"]["FSI_known_floor_area_lower_bound"]) for case in cases.values() if case["metrics"].get("comparison_eligible")]
    gsi_values = [float(case["metrics"]["GSI"]) for case in cases.values() if case["metrics"].get("comparison_eligible")]
    reasonableness = []
    expected = [
        ("borneo-sporenburg", "婆羅洲—斯波倫堡", 0.4, 0.6, 1.0, 2.0, "Founder 指定的合理性參考 GSI 0.4–0.6、FSI 約 1–2。"),
        ("hafencity-dalmannkai", "HafenCity／Dalmannkai", None, None, 3.0, 4.0, "Founder 指定 FSI 約 3–4；低於 80% 高度覆蓋時只報下限並排除比較。"),
        ("spangen-justus-van-effen", "Spangen／Justus van Effen 區", None, None, 1.5, 2.5, "Founder 指定 FSI 約 1.5–2.5。"),
    ]
    for slug, title, g_lo, g_hi, f_lo, f_hi, note in expected:
        case = cases.get(slug)
        if not case:
            result = "未取得，無從核查"
            measured = "GSI／FSI 未取得"
            detail = "沒有可用的本輪形態觀測值。"
        else:
            m = case["metrics"]
            measured = f"GSI {fmt(m['GSI'])}；FSI {fmt(m['FSI_known_floor_area_lower_bound'])} ({m['FSI_comparability_status']})"
            in_g = g_lo is None or (m["GSI"] is not None and g_lo <= m["GSI"] <= g_hi)
            in_f = m["comparison_eligible"] and m["FSI_known_floor_area_lower_bound"] is not None and f_lo <= m["FSI_known_floor_area_lower_bound"] <= f_hi
            if in_g and in_f:
                result = "落在參考範圍"
                detail = f"高度可用 {m['height_observed_building_count']}/{m['building_count']} 棟，FSI 比較資格成立。"
            elif not m["comparison_eligible"]:
                result = "資料不足；不判通過"
                detail = (f"僅 {m['height_observed_building_count']}/{m['building_count']} 棟有高度或樓層資料（覆蓋 {fmt(m['height_coverage_ratio'])}）；"
                          f"映射水域 {fmt(m['mapped_water_area_m2'])} m²，FSI 僅為已知量體下限。")
            else:
                result = "偏離參考範圍"
                detail = (f"研究窗 {area_map[slug]['area_ha']} ha，陸地分母 GSI {fmt(m['GSI'])}／含水分母 {fmt(m['GSI_gross_water_inclusive'])}，"
                          f"高度覆蓋 {fmt(m['height_coverage_ratio'])}；偏差可能來自 OSM 覆蓋、取樣窗邊界或明示 3.0 m／層換算，須以這些欄位逐項核對，不能僅憑區間推定成因。")
        reasonableness.append(f"| {title} | {measured} | {result}；{detail} | {note} |")
    unresolved = []
    for row in failures:
        reason = row.get('reason', row.get('last_error', '未取得完整回應。'))
        if "OSM source record and complete response are absent" in reason:
            reason = "OSM 來源記錄或完整回應缺失；未執行形態量測。"
        unresolved.append(f"- **{row['slug']}**：狀態 {row.get('status')}；嘗試數 {row.get('attempt_count', '未記錄')}；HTTP {row.get('http_statuses', [])}；{reason}")
    if not unresolved:
        unresolved.append("- 所選案例均有可解析的 OSM 快照；仍需把低高度覆蓋與稀疏幾何視為資料限制。")
    group_text = []
    for group, items in PRECEDENT_GROUPS.items():
        group_text.extend([f"### {group}", "", *group_rows.get(group, []), ""])
    return "\n".join([
        "# 形態先例庫：KB4 修正輪報告", "",
        "## 先例選取與範圍", "",
        f"本批選取 {len(areas)} 個先例，以荷蘭為主並含歐洲對照。各窗約 5–20 ha，研究窗依命名 OSM 參照物周圍的明列公尺矩形建立；多邊形及劃定理由見 study-areas.json。研究窗是可重算的觀察範圍，不等同官方專案邊界。",
        "", *window_rows, "",
        "## 主要量測表", "",
        f"完成測量 {measured_count}/{len(areas)} 案；其中 {eligible_count} 案同時通過空間覆蓋與高度覆蓋門檻。陸地分母是研究窗扣除已映射水域多邊形後的面積；另報含水分母值。", "",
        *main_rows, "", "## 詳細形態指標", "",
        "建築數／合併量體數分開列示；翼深以排除輔助建物後、相距不超過 0.5 m 合併的量體採 2A／周長估算，最小旋轉矩形短邊作交叉檢查。街廓由主要車行／主街切分，步道、自行車道和 service 不切分；面積與類型統計限完整街廓，截邊街廓另列；小於 1,000 m² 的碎片排除並在原始量測檔記數。", "",
        *metric_rows, "", "## 修正前後數值與差異來源", "",
        f"舊值取自 {old_path.relative_to(ROOT)}；舊算法將連棟逐戶足跡當翼深、把次要路徑切成街廓，且密度分母包含水面。新值套用合併量體、主要街道、1,000 m² 碎片門檻及陸地分母。每列保留實際新舊值；資料未取得時不製造差值。", "",
        *change_rows, "", "## 目標案例合理性核查", "", "| 先例 | 本輪實測 | 相對 Founder 參考 | 核查條件 |", "|---|---|---|---|", *reasonableness, "",
        "## 依情境分組比較", "", *group_text,
        "水岸帶狀地適合檢查橫向通道、岸線到街廓連接及土地分母變化；大型港區可比較碼頭街廓和主街網如何容納較深量體；一般街區用作非水岸的街牆與院落基線。表內每個案例都保留自身的觀察角度，不用組平均取代單案差異。", "",
        "## 圖件", "",
        f"輸出目錄：{run}/figures/。包含 {len(areas)} 張單案圖底關係 PNG、1 張同比例尺並列比較 PNG、1 張 FSI–GSI 散布 PNG。比例尺皆為 1:5,000 等效；標題、圖例和比例尺採繁體中文。散布圖排除高度覆蓋低於 80% 或幾何稀疏的先例。", "",
        "## 指標方法與缺口", "",
        "GSI = 去重原始建築足跡面積 ÷ 陸地分母；FSI = 有高度／樓層建築的足跡乘樓層數總和 ÷ 同一陸地分母。OSR 使用陸地 GSI 與已知 FSI。含水值用整個研究窗面積作分母。荷蘭高度從 3DBAG 的 BAG 識別碼連結欄位取得；其他地區採 OSM building:levels 或明示 height，高度值以 3.0 m／層換算屬分析假設。",
        "", "合併量體依足跡間距 ≤0.5 m 建立；先排除明示的棚屋、車庫、雨棚等輔助建物，再以 2×面積÷周長估算翼深，最小旋轉外接矩形短邊交叉檢查。街廓使用 primary、secondary、tertiary、residential、unclassified、living_street 與非面狀且有名稱或編號的 pedestrian 主街，排除 footway、path、cycleway、service；完整街廓才進入面積與類型統計，主要街段以道路交叉口間長度計；<1,000 m² 碎片單獨報數。",
        "", "主要資料缺口：", "", *unresolved,
        "", "## Overpass 請求上限稽核", "",
        "收據依完整查詢 payload 的 SHA-256 分組；以下列出歷史上超過三次的完全相同查詢，供交接查核。查詢次數合計跨越原始取得與後續重試紀錄，不以分批執行掩蓋；本輪停止再次請求。",
        "", *(overpass_retry_audit() or ["- 沒有完全相同 payload 超過三次的歷史查詢。"]),
        "", "自動類型判斷在合併量體上執行：周邊式按封閉中庭及街廓邊界界面比例判斷；合院按單一閉合中庭；板樓按長短邊比 >3；連棟按多個窄單元、已知樓層 ≤4；點式按長短邊比 <1.6 且足跡 <1,200 m²。未分類比例若超過 25%，保留未分類並說明資料限制，不強制歸類。",
        "", "OSM 是社群編輯快照，不保證現場完整；highway 路徑標記只說明圖資用途，只有明示 access 或 foot 開放標記才計為開放，未標註條件維持未知，仍不證明權屬或合法公共通行。書目 API 僅在核對條目可支持的範圍內填寫設計資訊，無來源的設計者和年代維持未確認。此報告提供形態比較，不提供基地規範或最終設計決定。", ""
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--refresh-generated", action="store_true",
                        help="refresh only files listed in the existing KB4 generation manifest")
    args = parser.parse_args()
    metrics_path = args.metrics.resolve()
    if not metrics_path.is_relative_to(ART.resolve()):
        raise SystemExit("metrics file must be inside artifacts/kb4-precedents")
    metrics = read(metrics_path)
    areas = read(ART / "study-areas.json")["cases"]
    area_map = {area["slug"]: area for area in areas}
    case_map = {case["slug"]: case for case in metrics["cases"]}
    run = str(metrics_path.parent.relative_to(ART))
    manifest_path = ART / "generated-knowledge-manifest.json"
    failure_map = {row["slug"]: row for row in metrics.get("unmeasured_cases", [])}
    note_content = {
        area["slug"]: note_for(area, case_map.get(area["slug"]), run, failure_map.get(area["slug"]))
        for area in areas
    }
    validate_case_note_repetition(note_content)
    report_content = build_report(areas, case_map, metrics.get("unmeasured_cases", []), run)
    t06_content = build_t06_document(areas, case_map, metrics.get("unmeasured_cases", []), run)

    if args.refresh_generated:
        if not manifest_path.is_file():
            raise SystemExit(f"cannot refresh without existing manifest: {manifest_path}")
        manifest = read(manifest_path)
        declared_note_paths = manifest.get("new_case_note_paths", [])
        if (len(declared_note_paths) != 16 or len(set(declared_note_paths)) != 16
                or any(not path.startswith("knowledge/v2/topics/MOR/precedents/") or not path.endswith(".md")
                       for path in declared_note_paths)):
            raise SystemExit("existing manifest does not own exactly 16 KB4 precedent notes")
        note_paths_by_slug = {area["slug"]: ROOT / path for area, path in zip(areas, declared_note_paths)}
        if any(not path.is_file() for path in note_paths_by_slug.values()):
            raise SystemExit("refusing to refresh a missing manifest-owned KB4 precedent note")
        declared_units = {
            path for path in manifest.get("new_unit_and_report_paths", [])
            if path.startswith("knowledge/v2/domains/MOR/units/")
        }
        expected_units = {f"knowledge/v2/domains/MOR/units/KU-MOR-{index:03d}.json" for index in range(81, 98)}
        if declared_units != expected_units:
            raise SystemExit("existing manifest does not own exactly the 17 KB4 precedent units")
        for index, area in enumerate(areas, 81):
            unit_path = UNITS / f"KU-MOR-{index:03d}.json"
            unit_path.write_text(json.dumps(unit_for(area, case_map.get(area["slug"]), index), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (UNITS / "KU-MOR-097.json").write_text(json.dumps(method_unit(), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        for area in areas:
            path = note_paths_by_slug[area["slug"]]
            path.write_text(note_content[area["slug"]], encoding="utf-8")
        report = ROOT / manifest["report_path"]
        if not report.is_file():
            raise SystemExit(f"refusing to refresh missing generated report: {report}")
        report.write_text(report_content, encoding="utf-8")
        if T06_PATH.exists():
            T06_PATH.write_text(t06_content, encoding="utf-8")
        else:
            write_new(T06_PATH, t06_content)
        manifest["generated_at_utc"] = utc_now()
        manifest["metrics_path"] = str(metrics_path.relative_to(ROOT))
        manifest["metrics_sha256"] = digest(metrics_path)
        manifest["new_topic_paths"] = [str(T06_PATH.relative_to(ROOT))]
        manifest["measured_case_count"] = len(case_map)
        manifest["comparable_case_count"] = sum(1 for case in case_map.values() if case["metrics"].get("comparison_eligible"))
        manifest["sparse_geometry_case_count"] = sum(1 for case in case_map.values() if case["metrics"].get("spatial_coverage_status") == "SPARSE_NOT_REPRESENTATIVE")
        manifest["unmeasured_case_count"] = len(areas) - len(case_map)
        manifest["measurement_script_sha256"] = metrics.get("script_sha256")
        manifest.setdefault("refresh_history_utc", []).append(manifest["generated_at_utc"])
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        if manifest_path.exists():
            raise SystemExit(f"refusing to overwrite {manifest_path}; use --refresh-generated for its owned outputs")
        new_library = []
        for record in build_library(metrics):
            target = LIB / f"{record['id']}.json"
            write_json_new(target, record)
            new_library.append(str(target.relative_to(ROOT)))
        new_units = []
        new_notes = []
        for index, area in enumerate(areas, 81):
            unit = unit_for(area, case_map.get(area["slug"]), index)
            unit_path = UNITS / f"KU-MOR-{index:03d}.json"
            note_path = NOTES / f"{area['title_zh']}.md"
            write_json_new(unit_path, unit)
            write_new(note_path, note_content[area["slug"]])
            new_units.extend([str(unit_path.relative_to(ROOT)), str(note_path.relative_to(ROOT))])
            new_notes.append(str(note_path.relative_to(ROOT)))
        method = UNITS / "KU-MOR-097.json"
        write_json_new(method, method_unit())
        new_units.append(str(method.relative_to(ROOT)))
        report = ART / "report-zh.md"
        write_new(report, report_content)
        write_new(T06_PATH, t06_content)
        manifest = {
            "schema_version": "kb4-generated-knowledge-v1", "generated_at_utc": utc_now(),
            "metrics_path": str(metrics_path.relative_to(ROOT)), "metrics_sha256": digest(metrics_path),
            "new_library_paths": new_library, "new_unit_and_report_paths": new_units + [str(report.relative_to(ROOT))],
            "new_case_note_paths": new_notes, "new_topic_paths": [str(T06_PATH.relative_to(ROOT))],
            "report_path": str(report.relative_to(ROOT)),
            "measured_case_count": len(case_map),
            "comparable_case_count": sum(1 for case in case_map.values() if case["metrics"].get("comparison_eligible")),
            "sparse_geometry_case_count": sum(1 for case in case_map.values() if case["metrics"].get("spatial_coverage_status") == "SPARSE_NOT_REPRESENTATIVE"),
            "unmeasured_case_count": len(areas) - len(case_map),
            "measurement_script_sha256": metrics.get("script_sha256"),
        }
        write_json_new(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
