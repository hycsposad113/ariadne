"""Read-only catalogue queries for the morphology dictionary.

The ``.yaml`` catalogue files use JSON-compatible YAML 1.2 documents so this
module can load them with the Python standard library and add no dependency.
The validator implements the JSON Schema keywords used by the checked-in
schema; it is intentionally not a general-purpose JSON Schema implementation.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


_DEFAULT_DIRECTORY = Path(__file__).resolve().parents[2] / "config" / "morphology-dictionary"


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if expected == "null":
        return value is None
    return False


def _resolve_local_ref(reference: str, root_schema: Mapping[str, Any]) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported non-local schema reference: {reference}")
    current: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or part not in current:
            raise ValueError(f"unresolved schema reference: {reference}")
        current = current[part]
    if not isinstance(current, Mapping):
        raise ValueError(f"schema reference is not an object: {reference}")
    return current


def _schema_errors(
    value: Any,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    path: str,
) -> list[str]:
    if "$ref" in schema:
        return _schema_errors(value, _resolve_local_ref(str(schema["$ref"]), root_schema), root_schema, path)

    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        expected_types = [expected] if isinstance(expected, str) else list(expected)
        if not any(_schema_type_matches(value, item) for item in expected_types):
            return [f"{path}: expected {' or '.join(expected_types)}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not one of the allowed choices")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than minLength")
        if len(value) > schema.get("maxLength", math.inf):
            errors.append(f"{path}: longer than maxLength")
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            errors.append(f"{path}: does not match pattern {pattern}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for keyword, predicate in (
            ("minimum", lambda n, bound: n >= bound),
            ("maximum", lambda n, bound: n <= bound),
            ("exclusiveMinimum", lambda n, bound: n > bound),
            ("exclusiveMaximum", lambda n, bound: n < bound),
        ):
            if keyword in schema and not predicate(value, schema[keyword]):
                errors.append(f"{path}: violates {keyword} {schema[keyword]}")

    if isinstance(value, Mapping):
        required = schema.get("required", ())
        for name in required:
            if name not in value:
                errors.append(f"{path}.{name}: required property is missing")
        properties = schema.get("properties", {})
        for name, child in properties.items():
            if name in value:
                errors.extend(_schema_errors(value[name], child, root_schema, f"{path}.{name}"))
        additional = schema.get("additionalProperties", True)
        for name, child_value in value.items():
            if name in properties:
                continue
            if additional is False:
                errors.append(f"{path}.{name}: additional property is not allowed")
            elif isinstance(additional, Mapping):
                errors.extend(_schema_errors(child_value, additional, root_schema, f"{path}.{name}"))
        if len(value) < schema.get("minProperties", 0):
            errors.append(f"{path}: fewer than minProperties")
        if len(value) > schema.get("maxProperties", math.inf):
            errors.append(f"{path}: more than maxProperties")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than minItems")
        if len(value) > schema.get("maxItems", math.inf):
            errors.append(f"{path}: more than maxItems")
        if schema.get("uniqueItems"):
            rendered = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(rendered) != len(set(rendered)):
                errors.append(f"{path}: items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, item_schema, root_schema, f"{path}[{index}]"))

    return errors


def validate_entry(entry: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    """Validate one catalogue entry against the checked-in JSON Schema."""
    target = schema.get("$defs", {}).get("entry", schema)
    if not isinstance(target, Mapping):
        raise ValueError("schema must define an object entry")
    errors = _schema_errors(entry, target, schema, "$entry")
    if errors:
        raise ValueError("; ".join(errors[:12]))


def validate_dictionary(dictionary: Mapping[str, Any]) -> None:
    """Validate entries and cross-file references without mutating the data."""
    schema = dictionary.get("schema")
    entries = dictionary.get("entries")
    atmospheres = dictionary.get("atmospheres")
    if not isinstance(schema, Mapping) or not isinstance(entries, Sequence) or isinstance(entries, str):
        raise ValueError("dictionary must include a schema and an entries list")
    if not isinstance(atmospheres, Mapping):
        raise ValueError("dictionary must include atmospheres metadata")

    source_registry = atmospheres.get("source_registry", {})
    if not isinstance(source_registry, Mapping):
        raise ValueError("atmospheres.source_registry must be an object")
    entry_ids = [entry.get("id") for entry in entries if isinstance(entry, Mapping)]
    if len(entry_ids) != len(entries):
        raise ValueError("every dictionary entry must be an object")
    if len(entry_ids) != len(set(entry_ids)):
        raise ValueError("entry ids must be unique")
    known_entries = set(entry_ids)
    known_sources = set(source_registry)

    for entry in entries:
        validate_entry(entry, schema)
        for source in entry["sources"]:
            if source["id"] not in known_sources:
                raise ValueError(f"{entry['id']}: unknown source id {source['id']}")
        for scores in entry["atmosphere_scores"].values():
            for source_id in scores["source_ids"]:
                if source_id not in known_sources:
                    raise ValueError(f"{entry['id']}: unknown score source id {source_id}")
        for rule in entry["combination_rules"]:
            if rule["target_id"] not in known_entries:
                raise ValueError(f"{entry['id']}: unknown combination target {rule['target_id']}")
            for source_id in rule["source_ids"]:
                if source_id not in known_sources:
                    raise ValueError(f"{entry['id']}: unknown combination source id {source_id}")
        for precedent in entry["precedents"]:
            for source_id in precedent["source_ids"]:
                if source_id not in known_sources:
                    raise ValueError(f"{entry['id']}: unknown precedent source id {source_id}")

    dimensions = atmospheres.get("dimensions", {})
    for entry in entries:
        unknown_dimensions = set(entry["atmosphere_scores"]) - set(dimensions)
        if unknown_dimensions:
            raise ValueError(f"{entry['id']}: unknown atmosphere dimensions {sorted(unknown_dimensions)}")

    recipes = atmospheres.get("recommendation_queries", [])
    if len(recipes) < 10:
        raise ValueError("at least ten atmosphere recommendation queries are required")
    recipe_ids: set[str] = set()
    for recipe in recipes:
        if recipe["id"] in recipe_ids:
            raise ValueError(f"duplicate recommendation query id: {recipe['id']}")
        recipe_ids.add(recipe["id"])
        for dimension, target in recipe["target_scores"].items():
            if dimension not in dimensions or not 0 <= target <= 1:
                raise ValueError(f"{recipe['id']}: invalid atmosphere target {dimension}")
        for recommendation in recipe["recommendations"]:
            if recommendation["entry_id"] not in known_entries:
                raise ValueError(f"{recipe['id']}: unknown recommended entry {recommendation['entry_id']}")


def load_dictionary(directory: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the dictionary from a directory of JSON-compatible YAML."""
    root = Path(directory) if directory is not None else _DEFAULT_DIRECTORY
    schema_path = root / "schema.json"
    atmosphere_path = root / "atmospheres.yaml"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        atmospheres = json.loads(atmosphere_path.read_text(encoding="utf-8"))
        entry_paths = sorted((root / "entries").glob("*.yaml"))
        entries = [json.loads(path.read_text(encoding="utf-8")) for path in entry_paths]
    except FileNotFoundError as error:
        raise ValueError(f"morphology dictionary file is missing: {error.filename}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            "dictionary YAML files must use the JSON-compatible YAML 1.2 subset"
        ) from error

    dictionary = {
        "schema": schema,
        "entries": entries,
        "atmospheres": atmospheres,
        "entry_by_id": {entry["id"]: entry for entry in entries},
        "directory": root,
    }
    validate_dictionary(dictionary)
    return dictionary


def query_by_atmosphere(
    dictionary: Mapping[str, Any],
    preferences: Mapping[str, float],
    *,
    levels: Sequence[str] | None = None,
    min_match: float = 0.0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Rank entries by closeness to requested 0–1 atmosphere targets.

    A preference is a target score, so low values are meaningful (for example,
    low privacy with high permeability). Scores remain editorial estimates.
    """
    if not preferences:
        raise ValueError("at least one atmosphere target is required")
    if not 0 <= min_match <= 1:
        raise ValueError("min_match must be between 0 and 1")
    dimensions = dictionary["atmospheres"]["dimensions"]
    for name, target in preferences.items():
        if name not in dimensions:
            raise ValueError(f"unknown atmosphere dimension: {name}")
        if isinstance(target, bool) or not isinstance(target, (int, float)) or not 0 <= target <= 1:
            raise ValueError(f"target for {name} must be between 0 and 1")
    if limit is not None and limit < 0:
        raise ValueError("limit cannot be negative")
    selected_levels = set(levels) if levels is not None else None
    valid_levels = {"building_plan", "block_assembly", "street_open_space"}
    if selected_levels is not None and (not selected_levels or not selected_levels <= valid_levels):
        raise ValueError("levels must contain one or more known morphology layers")

    ranked: list[dict[str, Any]] = []
    for entry in dictionary["entries"]:
        if selected_levels is not None and entry["level"] not in selected_levels:
            continue
        matches = [
            1.0 - abs(float(entry["atmosphere_scores"][name]["value"]) - float(target))
            for name, target in preferences.items()
        ]
        fit = sum(matches) / len(matches)
        if fit >= min_match:
            ranked.append({"entry_id": entry["id"], "fit": round(fit, 4), "entry": entry})
    ranked.sort(key=lambda result: (-result["fit"], result["entry_id"]))
    return ranked if limit is None else ranked[:limit]


def recommend_composition(dictionary: Mapping[str, Any], recipe_id: str) -> dict[str, Any]:
    """Return one authored, source-linked composition recipe and its entries."""
    recipe = next(
        (item for item in dictionary["atmospheres"]["recommendation_queries"] if item["id"] == recipe_id),
        None,
    )
    if recipe is None:
        raise KeyError(f"unknown recommendation query: {recipe_id}")
    entries_by_id = dictionary["entry_by_id"]
    return {
        "recipe": recipe,
        "entries": [
            {"role": item["role"], "reason_zh": item["reason_zh"], "entry": entries_by_id[item["entry_id"]]}
            for item in recipe["recommendations"]
        ],
    }
