"""In-memory BM25 retrieval over the local v2 knowledge catalogue.

The catalogue is read afresh for each request so newly added topic summaries,
units, and bibliography records are visible without a stale persisted index.
No network access or third-party search package is used here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import unicodedata
from typing import Any


DEFAULT_KNOWLEDGE_ROOT = Path(__file__).resolve().parents[3] / "knowledge" / "v2"
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_ENGLISH = re.compile(r"[a-z0-9]+", re.I)
_UNIT_REF = re.compile(r"KU-[A-Z0-9]+-[0-9]{3}", re.I)
_CJK_FUNCTION_CHARACTERS = set("的了和與及為在是把也或之而對於被將可會需其又但所")
_SYNONYM_GROUPS = (
    ("水岸", "港區", "waterfront", "harbor", "harbour", "port area"),
    ("街廓", "街區", "street block", "urban block", "block"),
    ("容積率", "far", "fsi", "floor area ratio", "floor space index"),
    ("自行車", "單車", "cycling", "cycle", "bicycle", "bike"),
    ("空間語法", "space syntax", "spatial syntax"),
    ("cpted", "crime prevention through environmental design", "防犯罪設計", "環境犯罪預防"),
)


def tokenize(text: str) -> list[str]:
    """Return Chinese character bigrams plus English/numeric tokens."""
    normalized = unicodedata.normalize("NFKC", str(text)).casefold()
    tokens: list[str] = []
    for match in _CJK.finditer(normalized):
        run = match.group()
        if len(run) == 1:
            if run not in _CJK_FUNCTION_CHARACTERS:
                tokens.append(run)
        else:
            for index in range(len(run) - 1):
                token = run[index:index + 2]
                if not any(char in _CJK_FUNCTION_CHARACTERS for char in token):
                    tokens.append(token)
    tokens.extend(_ENGLISH.findall(normalized))
    return tokens


def _expanded_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    tokens = tokenize(normalized)
    present = set(tokens)
    for group_index, group in enumerate(_SYNONYM_GROUPS):
        matched = False
        for alias in group:
            alias_norm = unicodedata.normalize("NFKC", alias).casefold()
            alias_tokens = tokenize(alias_norm)
            is_chinese = bool(_CJK.search(alias_norm))
            if alias_norm and ((is_chinese or " " in alias_norm) and alias_norm in normalized
                               or not is_chinese and " " not in alias_norm
                               and len(alias_tokens) == 1 and alias_tokens[0] in present):
                matched = True
                break
        if matched:
            tokens.append(f"synonym:{group_index}")
    return list(dict.fromkeys(tokens))


@dataclass(frozen=True)
class _Document:
    doc_id: str
    kind: str
    title: str
    text: str
    path: str
    payload: dict[str, Any]
    related_unit_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextPack:
    query_zh: str
    topic_ids: tuple[str, ...]
    unit_ids: tuple[str, ...]
    library_ids: tuple[str, ...]
    text: str


class KnowledgeIndexError(ValueError):
    """Raised when a local index source is unreadable or structurally unusable."""


class _BM25:
    def __init__(self, documents: tuple[_Document, ...], *, k1: float = 1.5, b: float = 0.75):
        self.documents = documents
        self.k1 = k1
        self.b = b
        self.term_counts = tuple(Counter(_expanded_tokens(doc.text)) for doc in documents)
        self.lengths = tuple(sum(counts.values()) for counts in self.term_counts)
        self.average_length = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        self.document_frequency: Counter[str] = Counter()
        for counts in self.term_counts:
            self.document_frequency.update(counts.keys())

    def scores(self, query: str) -> dict[str, float]:
        query_terms = Counter({term: 1 for term in sorted(set(_expanded_tokens(query)))})
        count = len(self.documents)
        scores: dict[str, float] = {}
        if not count:
            return scores
        for document, frequencies, length in zip(self.documents, self.term_counts, self.lengths):
            score = 0.0
            for term, query_frequency in query_terms.items():
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = self.document_frequency[term]
                inverse_frequency = math.log1p((count - df + 0.5) / (df + 0.5))
                normalizer = self.k1 * (1 - self.b + self.b * length / (self.average_length or 1.0))
                score += query_frequency * inverse_frequency * (frequency * (self.k1 + 1)) / (frequency + normalizer)
            if score > 0:
                scores[document.doc_id] = score
        return scores

    def ranked(self, query: str) -> list[tuple[_Document, float]]:
        scores = self.scores(query)
        by_id = {document.doc_id: document for document in self.documents}
        return sorted(((by_id[doc_id], score) for doc_id, score in scores.items()),
                      key=lambda item: (-item[1], item[0].doc_id, item[0].path))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeIndexError(f"cannot read knowledge source {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise KnowledgeIndexError(f"knowledge source must be a JSON object: {path}")
    return data


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_as_text(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(item) for item in value)
    return ""


def _resolve_v2_root(root: Path | str | None) -> Path:
    if root is None:
        candidate = DEFAULT_KNOWLEDGE_ROOT
    else:
        candidate = Path(root).expanduser().resolve()
        if (candidate / "knowledge" / "v2").is_dir():
            candidate = candidate / "knowledge" / "v2"
    return candidate


def _topic_document(path: Path, base: Path) -> _Document:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise KnowledgeIndexError(f"cannot read topic summary {path}: {exc}") from exc
    title_match = re.search(r"^\s*#\s+(.+?)\s*$", content, re.M)
    title = title_match.group(1) if title_match else path.stem.replace("-", " ")
    doc_id = path.relative_to(base).with_suffix("").as_posix()
    refs = tuple(dict.fromkeys(reference.upper() for reference in _UNIT_REF.findall(content)))
    return _Document(doc_id, "topic", title, f"{title}\n{content}", str(path), {"content": content}, refs)


def _unit_document(path: Path) -> _Document:
    data = _read_json(path)
    doc_id = str(data.get("id") or path.stem)
    title = str(data.get("title_zh") or data.get("title_en") or doc_id)
    findings = (data.get("evidence") or {}).get("findings", [])
    searchable = [title, data.get("title_en"), data.get("subtopic"), data.get("summary_zh"),
                  data.get("key_points_zh"), findings, data.get("debates_zh"), data.get("values"),
                  data.get("design_implications_zh"), data.get("design_options"),
                  data.get("applies_when_zh"), data.get("not_applicable_when_zh"), data.get("sources")]
    related = data.get("related_unit_ids", [])
    if not isinstance(related, list):
        related = []
    index_text = " ".join(_as_text(item) for item in searchable if item is not None)
    # Repeat the explicit titles once to give title matches more BM25 weight.
    index_text = f"{title} {data.get('title_en', '')} {index_text}"
    return _Document(doc_id, "unit", title, index_text, str(path), data,
                     tuple(dict.fromkeys(str(item).upper() for item in related)))


def _library_document(path: Path) -> _Document:
    data = _read_json(path)
    doc_id = str(data.get("id") or path.stem)
    title = str(data.get("title") or data.get("title_zh") or doc_id)
    index_text = " ".join((doc_id, title, _as_text(data.get("authors")), _as_text(data.get("year")),
                           _as_text(data.get("venue_or_publisher"))))
    return _Document(doc_id, "library", title, index_text, str(path), data)


def _build_documents(v2_root: Path) -> tuple[tuple[_Document, ...], tuple[_Document, ...], tuple[_Document, ...]]:
    topics_root = v2_root / "topics"
    domains_root = v2_root / "domains"
    library_root = v2_root / "library"
    topics = tuple(_topic_document(path, topics_root) for path in sorted(topics_root.rglob("*.md"))) if topics_root.exists() else ()
    units = tuple(_unit_document(path) for path in sorted(domains_root.glob("*/units/*.json"))) if domains_root.exists() else ()
    library = tuple(_library_document(path) for path in sorted(library_root.glob("*.json"))) if library_root.exists() else ()
    for label, docs in (("topic", topics), ("unit", units), ("library", library)):
        ids = [doc.doc_id for doc in docs]
        if len(ids) != len(set(ids)):
            raise KnowledgeIndexError(f"duplicate {label} identifiers in local knowledge v2 index")
    return topics, units, library


def _selected_documents(index: _BM25, query: str) -> tuple[list[_Document], dict[str, float]]:
    ranked = index.ranked(query)
    return [document for document, _ in ranked], {document.doc_id: score for document, score in ranked}


def _topic_relevance(topic: _Document, query: str) -> int:
    query_terms = set(_expanded_tokens(query))
    topic_terms = set(_expanded_tokens(topic.text))
    return len(query_terms & topic_terms)


def _render_topic(document: _Document) -> str:
    return f"### {document.title}\n主題 ID：{document.doc_id}\n{document.payload['content'].strip()}"


def _value_text(value: Any) -> str:
    if isinstance(value, dict):
        fields = ("name", "range", "effect_or_value", "unit", "context", "library_id", "claim_verification")
        rendered = [f"{field}={_as_text(value[field])}" for field in fields if value.get(field) is not None]
        return "；".join(rendered) or _as_text(value)
    return _as_text(value)


def _render_unit(document: _Document, *, allowed_library_ids: set[str] | None) -> str:
    data = document.payload
    evidence = data.get("evidence") or {}
    findings = evidence.get("findings", []) if isinstance(evidence, dict) else []
    values = data.get("values", [])
    sources = data.get("sources", [])
    source_ids = [str(source.get("library_id")) for source in sources if isinstance(source, dict) and source.get("library_id")]
    if allowed_library_ids is not None:
        source_ids = [library_id for library_id in source_ids if library_id in allowed_library_ids]
    lines = [f"### {document.doc_id}｜{document.title}",
             f"核心主張：{_as_text(data.get('summary_zh')) or '知識單位未提供摘要。'}"]
    if values:
        lines.append("數值／範圍：" + "；".join(_value_text(value) for value in values))
    else:
        observed = [finding.get("effect_or_value") for finding in findings
                    if isinstance(finding, dict) and finding.get("effect_or_value")]
        lines.append("數值／範圍：" + ("；".join(_as_text(item) for item in observed) if observed else "本卡未列明。"))
    limits = [data.get("not_applicable_when_zh"), data.get("debates_zh")]
    limits = [_as_text(item) for item in limits if item]
    lines.append("限制／爭議：" + ("；".join(limits) if limits else "本卡未列明。"))
    strength = evidence.get("strength") if isinstance(evidence, dict) else None
    if strength:
        lines.append(f"證據標記：{strength}")
    lines.append("文獻 ID：" + (", ".join(dict.fromkeys(source_ids)) if source_ids else "無可用於正式輸出的對應文獻 ID"))
    return "\n".join(lines)


def _render_library(document: _Document, *, include_doi: bool) -> str:
    data = document.payload
    authors = ", ".join(str(author) for author in data.get("authors", []) if author) or "作者未列"
    year = data.get("year") or "年份未列"
    venue = data.get("venue_or_publisher") or "出版資訊未列"
    verification = (data.get("verification") or {}).get("status", "狀態未列")
    parts = [f"{document.doc_id}｜{authors}（{year}）。{document.title}。{venue}。書目狀態：{verification}。"]
    doi = data.get("doi")
    if include_doi and doi:
        parts.append(f"DOI: {doi}.")
    limitations = data.get("limitations_zh")
    if limitations:
        parts.append(f"限制：{limitations}")
    return " ".join(parts)


def _limit_text(parts: list[str], max_chars: int) -> str:
    text = "\n\n".join(part for part in parts if part)
    if len(text) <= max_chars:
        return text
    marker = "…[情境包依字元上限截斷]"
    if max_chars <= len(marker):
        return marker[:max_chars]
    return text[:max_chars - len(marker)] + marker


def build_context_pack(
    question: str,
    *,
    root: Path | str | None = None,
    max_chars: int = 50000,
    max_topics: int = 3,
    max_cards: int = 12,
    allowed_library_ids: set[str] | tuple[str, ...] | None = None,
    include_doi: bool = True,
) -> ContextPack:
    """Build a topic-first context pack from the current local v2 catalogue."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be nonblank text")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    if isinstance(max_topics, bool) or not isinstance(max_topics, int) or not 1 <= max_topics <= 3:
        raise ValueError("max_topics must be between 1 and 3")
    if isinstance(max_cards, bool) or not isinstance(max_cards, int) or max_cards < 0:
        raise ValueError("max_cards must be a nonnegative integer")

    v2_root = _resolve_v2_root(root)
    topics, units, library = _build_documents(v2_root)
    topic_index, unit_index, library_index = _BM25(topics), _BM25(units), _BM25(library)
    selected_topics, _ = _selected_documents(topic_index, question)
    query_tokens = set(_expanded_tokens(question))
    query_anchors = {token for token in query_tokens if token.startswith("synonym:")}
    cross_language_anchor = bool(query_anchors) and not _CJK.search(question)
    minimum_topic_overlap = 1 if len(query_tokens) <= 2 or cross_language_anchor else 2
    filtered_topics = []
    for document in selected_topics:
        document_tokens = set(_expanded_tokens(document.text))
        if query_anchors and not query_anchors.intersection(document_tokens):
            continue
        if _topic_relevance(document, question) >= minimum_topic_overlap:
            filtered_topics.append(document)
    selected_topics = filtered_topics
    selected_topics = selected_topics[:max_topics]
    related_ids = list(dict.fromkeys(unit_id for topic in selected_topics for unit_id in topic.related_unit_ids))
    unit_ranking, unit_scores = _selected_documents(unit_index, question)
    units_by_id = {document.doc_id: document for document in units}
    related_set = set(related_ids)
    linked = [units_by_id[unit_id] for unit_id in related_ids if unit_id in units_by_id]
    linked.sort(key=lambda document: (-unit_scores.get(document.doc_id, 0.0), related_ids.index(document.doc_id), document.doc_id))
    supplemental = [document for document in unit_ranking if document.doc_id not in related_set]
    related_limit = min(len(linked), max(1, max_cards // 2)) if max_cards else 0
    selected_units = linked[:related_limit]
    selected_units.extend(supplemental[:max_cards - len(selected_units)])
    if len(selected_units) < max_cards:
        remaining_linked = [document for document in linked if document.doc_id not in {item.doc_id for item in selected_units}]
        selected_units.extend(remaining_linked[:max_cards - len(selected_units)])

    ranked_library, _ = _selected_documents(library_index, question)
    library_by_id = {document.doc_id: document for document in library}
    cited_ids = [str(source.get("library_id")) for document in selected_units
                 for source in document.payload.get("sources", [])
                 if isinstance(source, dict) and source.get("library_id") in library_by_id]
    cited_ids.extend(library_id for topic in selected_topics for library_id in library_by_id
                     if re.search(rf"(?<![A-Z0-9]){re.escape(library_id)}(?![A-Z0-9])", topic.payload["content"], re.I))
    cited_ids.extend(document.doc_id for document in ranked_library)
    cited_ids = list(dict.fromkeys(cited_ids))
    allowlist = set(allowed_library_ids) if allowed_library_ids is not None else None
    if allowlist is not None:
        cited_ids = [library_id for library_id in cited_ids if library_id in allowlist]
    selected_library = [library_by_id[library_id] for library_id in cited_ids[:24]]

    topic_hits_found = bool(selected_topics)
    unit_hits_found = bool(selected_units)
    library_hits_found = bool(selected_library)

    def render_sections() -> list[str]:
        sections = [f"# 知識庫 v2 情境包\n查詢：{question.strip()}\n索引來源：本機 Markdown 主題綜述、知識單位與 library；未進行網路檢索。",
                    "## 主題綜述（依 BM25 相關度排序；先呈現）"]
        if selected_topics:
            sections.extend(_render_topic(document) for document in selected_topics)
        elif topic_hits_found:
            sections.append("（主題綜述因字元上限未納入；提高上限可顯示完整內容。）")
        else:
            sections.append("（目前沒有命中的主題綜述；可新增 Markdown 後於下次查詢自動重建索引。）")
        sections.append("## 相關細卡（主題連結優先，再依 BM25 補充）")
        if selected_units:
            rendered_library_ids = {document.doc_id for document in selected_library}
            sections.extend(_render_unit(document, allowed_library_ids=rendered_library_ids)
                            for document in selected_units)
        elif unit_hits_found:
            sections.append("（細卡因字元上限未納入；提高上限可顯示完整內容。）")
        else:
            sections.append("（沒有命中的 v2 細卡。）")
        sections.append("## 書目（本機 library）")
        if selected_library:
            sections.extend(_render_library(document, include_doi=include_doi) for document in selected_library)
        elif library_hits_found:
            sections.append("（書目因字元上限未納入；提高上限可顯示完整內容。）")
        else:
            sections.append("（沒有可列出的相關書目。）")
        return sections

    while True:
        sections = render_sections()
        text = "\n\n".join(part for part in sections if part)
        if len(text) <= max_chars:
            rendered = text
            break
        if selected_library:
            selected_library.pop()
        elif selected_units:
            selected_units.pop()
        elif selected_topics:
            selected_topics.pop()
        else:
            rendered = _limit_text(sections, max_chars)
            break
    return ContextPack(question.strip(), tuple(document.doc_id for document in selected_topics),
                       tuple(document.doc_id for document in selected_units),
                       tuple(document.doc_id for document in selected_library), rendered)


__all__ = ["ContextPack", "KnowledgeIndexError", "build_context_pack", "tokenize"]
