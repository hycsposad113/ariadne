"""Offline retrieval tests for v2 topics, units, and bibliography."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from urban_design.knowledge.retrieval_v2 import build_context_pack


def write_unit(root: Path, unit_id: str, domain: str, title_zh: str, title_en: str,
               summary: str, *, sources=(), related=(), values=(), findings=()):
    path = root / "knowledge" / "v2" / "domains" / domain / "units" / f"{unit_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": unit_id,
        "domain": domain,
        "subtopic": title_zh,
        "title_zh": title_zh,
        "title_en": title_en,
        "summary_zh": summary,
        "key_points_zh": [summary],
        "evidence": {"strength": "MIXED", "findings": list(findings)},
        "values": list(values),
        "debates_zh": "需檢查研究脈絡、街網尺度與地域適用限制。",
        "not_applicable_when_zh": "不可直接當成本基地的實測值或法規門檻。",
        "sources": [{"library_id": source, "claim_id": "C1"} for source in sources],
        "related_unit_ids": list(related),
    }, ensure_ascii=False), encoding="utf-8")
    return path


def write_library(root: Path, library_id: str, title: str, *, authors=("A. Researcher",), year=2020):
    path = root / "knowledge" / "v2" / "library" / f"{library_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": library_id,
        "title": title,
        "authors": list(authors),
        "year": year,
        "venue_or_publisher": "Urban Studies Review",
        "doi": "10.1234/example.2020",
        "limitations_zh": "僅作書目識別，不代表完整全文審查。",
        "verification": {"status": "VERIFIED"},
    }, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def kb_root(tmp_path):
    root = tmp_path
    write_unit(root, "KU-SYN-001", "SYN", "街網表示與空間語法整合度",
               "Street representation and integration", "空間語法整合度需配合街網表示理解。",
               sources=("SHARMIN17",), related=("KU-SYN-001",))
    write_unit(root, "KU-MOR-001", "MOR", "周邊式街廓中庭與容積率",
               "Perimeter block courtyard and floor area ratio",
               "周邊式街廓中庭尺寸、容積率與容積指數須依脈絡比較。",
               sources=("SPACEMATRIX",), values=({"name": "FSI", "range": "1.0–2.5", "unit": "ratio", "context": "illustrative"},))
    write_unit(root, "KU-MOB-001", "MOB", "自行車與步行共廊",
               "Walking and bicycle corridors", "自行車路線應與步行網絡及入口關係一併檢視。",
               sources=("CROW_GUIDE",))
    write_unit(root, "KU-WAT-001", "WAT", "水岸與港區再生",
               "Harbor edge regeneration", "水岸與港區再生需檢視公共通達、生產活動及生態取捨。",
               sources=("WATERFRONT_STUDY",))
    write_library(root, "SHARMIN17", "Space Syntax and Pedestrian Movement")
    write_library(root, "SPACEMATRIX", "The Spacematrix Method")
    write_library(root, "CROW_GUIDE", "Design Manual for Bicycle Traffic")
    write_library(root, "WATERFRONT_STUDY", "Port and Waterfront Regeneration")
    topics = root / "knowledge" / "v2" / "topics"
    topics.mkdir(parents=True, exist_ok=True)
    (topics / "space-syntax.md").write_text(
        "# 空間語法與街網表示\n\n整合度是街網分析指標；研究結論會受表示方法、尺度與行人活動脈絡影響。\n\n相關細卡：KU-SYN-001\n",
        encoding="utf-8")
    (topics / "urban-form.md").write_text(
        "# 街廓與建築型態\n\n中庭尺寸與容積指標需連同街廓形態及地區條件比較。\n\n相關細卡：KU-MOR-001\n",
        encoding="utf-8")
    return root


def test_kb_chinese_question_prefers_topic_then_related_detail_and_deduplicates(kb_root):
    pack = build_context_pack("空間語法整合度與街網表示", root=kb_root)

    assert pack.topic_ids[0] == "space-syntax"
    assert pack.unit_ids.count("KU-SYN-001") == 1
    assert pack.text.index("空間語法與街網表示") < pack.text.index("KU-SYN-001")
    assert "需檢查研究脈絡" in pack.text
    assert "SHARMIN17" in pack.text


def test_kb_chinese_topic_ranking_ignores_repeated_function_words(kb_root):
    topics = kb_root / "knowledge" / "v2" / "topics"
    (topics / "waterfront-generations.md").write_text(
        "# 港區再生的世代\n\n水岸更新的歷程可比較不同階段與港區轉型。\n",
        encoding="utf-8")
    (topics / "generic-city.md").write_text(
        "# 城市理論\n\n" + "城市的空間與生活的關係、城市的形式與治理的條件。\n" * 30,
        encoding="utf-8")

    pack = build_context_pack("水岸再生的世代", root=kb_root)

    assert pack.topic_ids[0] == "waterfront-generations"
    assert "generic-city" not in pack.topic_ids


def test_kb_topic_ranking_requires_more_than_one_incidental_synonym(kb_root):
    topics = kb_root / "knowledge" / "v2" / "topics"
    (topics / "waterfront-generations.md").write_text(
        "# 水岸再生的世代\n\n比較港區再生歷程的不同階段與公共空間轉變。\n",
        encoding="utf-8")
    (topics / "incidental-port.md").write_text(
        "# 城市形式\n\n" + "港區的道路與城市的建築、港區的活動與城市的生活。\n" * 20,
        encoding="utf-8")

    pack = build_context_pack("水岸再生的世代", root=kb_root)

    assert pack.topic_ids[0] == "waterfront-generations"
    assert "incidental-port" not in pack.topic_ids


def test_kb_topic_shortlist_requires_query_concept_anchor_when_available(kb_root):
    topics = kb_root / "knowledge" / "v2" / "topics"
    (topics / "generic-space-integration.md").write_text(
        "# Space integration in public space\n\n"
        + "Space integration and public space shape city activity.\n" * 12,
        encoding="utf-8")

    pack = build_context_pack("space syntax integration", root=kb_root)

    assert "space-syntax" in pack.topic_ids
    assert "generic-space-integration" not in pack.topic_ids


def test_kb_topic_links_cannot_consume_all_detail_slots(kb_root):
    linked_ids = []
    for number in range(1, 7):
        unit_id = f"KU-SOC-{number:03d}"
        linked_ids.append(unit_id)
        write_unit(kb_root, unit_id, "SOC", f"一般城市研究主題 {number}", f"General city study {number}",
                   "此細卡只記錄一般城市研究，沒有港區或水岸主題。")
    topics = kb_root / "knowledge" / "v2" / "topics"
    (topics / "waterfront-generations.md").write_text(
        "# 水岸再生\n\n港區再生的不同階段。相關細卡：" + ", ".join(linked_ids),
        encoding="utf-8")

    pack = build_context_pack("waterfront", root=kb_root, max_cards=4)

    assert len(pack.unit_ids) <= 4
    assert "KU-WAT-001" in pack.unit_ids


def test_kb_english_query_matches_v2_unit_and_library_title(kb_root):
    pack = build_context_pack("space syntax integration", root=kb_root)

    assert "KU-SYN-001" in pack.unit_ids
    assert "SHARMIN17" in pack.library_ids
    assert "Space Syntax and Pedestrian Movement" in pack.text


def test_kb_bm25_indexes_numeric_values_in_knowledge_units(kb_root):
    pack = build_context_pack("1.0–2.5", root=kb_root)

    assert "KU-MOR-001" in pack.unit_ids
    assert "1.0–2.5" in pack.text


@pytest.mark.parametrize(("query", "expected"), [
    ("waterfront", "KU-WAT-001"),
    ("街廓", "KU-MOR-001"),
    ("street block", "KU-MOR-001"),
    ("FAR", "KU-MOR-001"),
    ("FSI", "KU-MOR-001"),
    ("容積率", "KU-MOR-001"),
    ("cycling", "KU-MOB-001"),
    ("自行車", "KU-MOB-001"),
    ("港區", "KU-WAT-001"),
])
def test_kb_mixed_language_synonyms(query, expected, kb_root):
    pack = build_context_pack(query, root=kb_root)

    assert expected in pack.unit_ids


def test_kb_context_pack_length_limit_is_hard(kb_root):
    pack = build_context_pack("空間語法整合度", root=kb_root, max_chars=320)

    assert len(pack.text) <= 320
    assert pack.text


def test_kb_bounded_pack_returns_only_complete_rendered_ids(kb_root):
    pack = build_context_pack("空間語法整合度", root=kb_root, max_chars=500, max_topics=2, max_cards=12)

    assert len(pack.text) <= 500
    assert pack.topic_ids and pack.unit_ids
    assert "情境包依字元上限截斷" not in pack.text
    for topic_id in pack.topic_ids:
        topic_path = kb_root / "knowledge" / "v2" / "topics" / f"{topic_id}.md"
        assert topic_path.read_text(encoding="utf-8").strip() in pack.text
    for unit_id in pack.unit_ids:
        unit_path = kb_root / "knowledge" / "v2" / "domains" / "SYN" / "units" / f"{unit_id}.json"
        unit = json.loads(unit_path.read_text(encoding="utf-8"))
        assert f"### {unit_id}｜" in pack.text
        assert f"核心主張：{unit['summary_zh']}" in pack.text
    bibliography = pack.text.split("## 書目", 1)[1] if "## 書目" in pack.text else ""
    for library_id in pack.library_ids:
        assert f"\n\n{library_id}｜" in bibliography


def test_kb_index_is_rebuilt_when_topics_are_added(kb_root):
    first = build_context_pack("CPTED critique", root=kb_root)
    assert "cpted-critique" not in first.topic_ids

    topics = kb_root / "knowledge" / "v2" / "topics"
    (topics / "cpted-critique.md").write_text(
        "# CPTED 批評\n\nCPTED 的批評關注位移、監控與社會排除。\n",
        encoding="utf-8")
    write_unit(kb_root, "KU-REG-001", "REG", "CPTED 批評與防犯罪設計",
               "CPTED critique", "CPTED 批評涉及自然監視、排除與犯罪位移。")

    rebuilt = build_context_pack("CPTED critique", root=kb_root)
    assert "cpted-critique" in rebuilt.topic_ids
    assert "KU-REG-001" in rebuilt.unit_ids


def test_kb_cli_prints_a_bounded_context_pack():
    repo = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(repo / "scripts" / "kb_context_pack.py"), "space syntax integration", "--max-chars", "500"],
        cwd=repo,
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": "/private/tmp"},
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("# 知識庫 v2 情境包")
    assert len(completed.stdout) <= 500


def test_kb_graduate_answer_skill_prescribes_six_sections_and_source_labels():
    path = Path(__file__).resolve().parents[1] / "knowledge" / "v2" / "skills" / "graduate-answer-zh.md"
    text = path.read_text(encoding="utf-8")

    assert all(f"{number}．" in text for number in range(1, 7))
    assert "[KU-" in text
    assert "（一般專業知識）" in text
    assert "700–1,100" in text
