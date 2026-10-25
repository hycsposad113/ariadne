#!/usr/bin/env python3
"""Validate the six MOR fabric records and their local knowledge references."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


EXPECTED_IDS = {
    "fabric.harbour_grain",
    "fabric.closed_block_extension",
    "fabric.courtyard_islands",
    "fabric.landscape_figure",
    "fabric.orthogonal_grid",
    "fabric.irregular_fine",
}
REQUIRED_EDGE_TYPES = {
    "waterfront",
    "large_park",
    "topographic_edge",
    "retained_building",
    "existing_city_road",
}
KU_PATTERN = re.compile(r"KU-MOR-[0-9]{3}")


def _read_json(path: Path, errors: list[str]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{path}: 無法讀取 JSON：{exc}")
        return None


def _check_range(value: dict[str, Any], path: str, errors: list[str]) -> None:
    minimum = value.get("minimum")
    maximum = value.get("maximum")
    if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)) and minimum > maximum:
        errors.append(f"{path}: minimum {minimum} 大於 maximum {maximum}")


def validate_fabrics(root: Path | str | None = None) -> list[str]:
    """Return all schema, budget, and local reference errors without writing files."""
    project_root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    schema_path = project_root / "knowledge/v2/fabric.schema.json"
    fabric_dir = project_root / "knowledge/v2/domains/MOR/fabrics"
    unit_dir = project_root / "knowledge/v2/domains/MOR/units"
    library_dir = project_root / "knowledge/v2/library"
    entries_dir = project_root / "config/morphology-dictionary/entries"
    errors: list[str] = []

    schema = _read_json(schema_path, errors)
    if schema is None:
        return errors
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except Exception as exc:  # Includes schema errors with a useful CLI message.
        errors.append(f"{schema_path}: JSON Schema 無效：{exc}")
        return errors

    files = sorted(fabric_dir.glob("*.json"))
    if len(files) != len(EXPECTED_IDS):
        errors.append(f"{fabric_dir}: 預期 6 個紋理 JSON，實際 {len(files)} 個")

    fabrics: list[tuple[Path, dict[str, Any]]] = []
    observed_ids: set[str] = set()
    for path in files:
        data = _read_json(path, errors)
        if not isinstance(data, dict):
            continue
        fabric_id = data.get("id")
        if fabric_id in observed_ids:
            errors.append(f"{path}: 重複的紋理 id {fabric_id}")
        if isinstance(fabric_id, str):
            observed_ids.add(fabric_id)
        fabrics.append((path, data))
        for issue in sorted(validator.iter_errors(data), key=lambda item: list(map(str, item.path))):
            location = "/".join(map(str, issue.path)) or "$"
            errors.append(f"{path.relative_to(project_root)}:{location}: {issue.message}")

    missing_ids = EXPECTED_IDS - observed_ids
    unexpected_ids = observed_ids - EXPECTED_IDS
    for fabric_id in sorted(missing_ids):
        errors.append(f"缺少紋理 id：{fabric_id}")
    for fabric_id in sorted(unexpected_ids):
        errors.append(f"非預期紋理 id：{fabric_id}")

    part_ids: set[str] = set()
    for entry_path in sorted(entries_dir.glob("*.yaml")):
        entry = _read_json(entry_path, errors)
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            part_ids.add(entry["id"])

    composition_signatures: dict[tuple[tuple[str, float], ...], str] = {}
    for path, fabric in fabrics:
        label = str(fabric.get("id", path.name))
        budget = fabric.get("land_use_budget", {})
        if isinstance(budget, dict):
            minimum_total = 0.0
            maximum_total = 0.0
            valid_budget = True
            for key, value in budget.items():
                if not isinstance(value, dict):
                    valid_budget = False
                    continue
                _check_range(value, f"{label}.land_use_budget.{key}", errors)
                low, high = value.get("minimum"), value.get("maximum")
                if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
                    valid_budget = False
                    continue
                minimum_total += low
                maximum_total += high
            if valid_budget and not minimum_total <= 100 <= maximum_total:
                errors.append(
                    f"{label}.land_use_budget: 100% 不可達；合計範圍 {minimum_total:g}–{maximum_total:g}%"
                )

        street_network = fabric.get("street_network", {})
        if isinstance(street_network, dict):
            for index, level in enumerate(street_network.get("hierarchy", [])):
                if not isinstance(level, dict):
                    continue
                _check_range(level.get("section_width_m", {}), f"{label}.street_network.hierarchy[{index}].section_width_m", errors)
                _check_range(level.get("spacing_m", {}), f"{label}.street_network.hierarchy[{index}].spacing_m", errors)

            proxy = street_network.get("street_width_building_gap_proxy_m", {})
            if isinstance(proxy, dict):
                p25, median, p75 = proxy.get("p25"), proxy.get("median"), proxy.get("p75")
                if all(isinstance(value, (int, float)) for value in (p25, median, p75)):
                    if not p25 <= median <= p75:
                        errors.append(f"{label}.street_network.street_width_building_gap_proxy_m: 須符合 P25 ≤ median ≤ P75")
                for ku_id in proxy.get("ku_ids", []):
                    if not (unit_dir / f"{ku_id}.json").is_file():
                        errors.append(f"{label}.street_network.street_width_building_gap_proxy_m: 不存在的先例單元 {ku_id}")

        blocks = fabric.get("blocks", {})
        if isinstance(blocks, dict):
            for key in ("short_edge_m", "long_edge_m"):
                value = blocks.get(key, {})
                if isinstance(value, dict):
                    _check_range(value, f"{label}.blocks.{key}", errors)
                    basis = value.get("basis", {})
                    if not isinstance(basis, dict) or basis.get("status") not in {
                        "EDITORIAL",
                        "MEASURED_PRECEDENT_DERIVED",
                    }:
                        errors.append(f"{label}.blocks.{key}: basis.status 必須標示 EDITORIAL 或 MEASURED_PRECEDENT_DERIVED")
                    for ku_id in basis.get("ku_ids", []) if isinstance(basis, dict) else []:
                        if not (unit_dir / f"{ku_id}.json").is_file():
                            errors.append(f"{label}.blocks.{key}: 不存在的先例單元 {ku_id}")

        targets = fabric.get("density_targets", {})
        if isinstance(targets, dict):
            for metric, value in targets.items():
                if not isinstance(value, dict):
                    continue
                _check_range(value.get("range", {}), f"{label}.density_targets.{metric}", errors)
                mentioned_kus = KU_PATTERN.findall(str(value.get("basis", "")))
                if value.get("status") == "MEASURED_PRECEDENT" and not mentioned_kus:
                    errors.append(f"{label}.density_targets.{metric}: MEASURED_PRECEDENT 缺少 KU 引用")
                for ku_id in mentioned_kus:
                    if not (unit_dir / f"{ku_id}.json").is_file():
                        errors.append(f"{label}.density_targets.{metric}: 不存在的先例單元 {ku_id}")

        steps = fabric.get("drawing_steps", [])
        if isinstance(steps, list):
            orders = [step.get("order") for step in steps if isinstance(step, dict)]
            if orders and orders != list(range(1, len(orders) + 1)):
                errors.append(f"{label}.drawing_steps: order 必須由 1 連續遞增")

        edges = fabric.get("edges", [])
        edge_types = {edge.get("type") for edge in edges if isinstance(edge, dict)}
        if edge_types != REQUIRED_EDGE_TYPES:
            errors.append(f"{label}.edges: 必須各有一條指定的五種邊界處理規則")

        part_references = [
            item.get("part_id")
            for item in fabric.get("building_composition", {}).get("components", [])
            if isinstance(item, dict)
        ]
        part_references.extend(fabric.get("open_space_system", {}).get("types", []))
        for part_id in part_references:
            if part_id not in part_ids:
                errors.append(f"{label}: 不存在的零件 id {part_id}")

        composition = fabric.get("building_composition", {}).get("components", [])
        signature_rows: list[tuple[str, float]] = []
        for index, item in enumerate(composition):
            if not isinstance(item, dict):
                continue
            if not isinstance(item.get("basis_zh"), str) or not item["basis_zh"].strip():
                errors.append(f"{label}.building_composition.components[{index}]: 占比缺少 basis_zh")
            part_id, share = item.get("part_id"), item.get("recommended_share_percent")
            if isinstance(part_id, str) and isinstance(share, (int, float)):
                signature_rows.append((part_id, share))
        if signature_rows:
            signature = tuple(sorted(signature_rows))
            other = composition_signatures.get(signature)
            if other:
                errors.append(f"{label}.building_composition: composition 與 {other} 完全相同")
            composition_signatures[signature] = label
        if label == "fabric.harbour_grain":
            shares = {
                item.get("part_id"): item.get("recommended_share_percent")
                for item in composition
                if isinstance(item, dict)
            }
            perimeter = shares.get("block.perimeter")
            other_shares = [
                value
                for key, value in shares.items()
                if key != "block.perimeter" and isinstance(value, (int, float))
            ]
            if isinstance(perimeter, (int, float)) and other_shares and perimeter >= max(other_shares):
                errors.append("fabric.harbour_grain: block.perimeter 不得是最大 composition 占比")

        ku_references = [
            item.get("ku_id")
            for item in fabric.get("precedents", [])
            if isinstance(item, dict)
        ]
        for item in fabric.get("blocks", {}).values() if isinstance(fabric.get("blocks"), dict) else []:
            if isinstance(item, dict) and isinstance(item.get("basis"), dict):
                ku_references.extend(item["basis"].get("ku_ids", []))
        proxy = fabric.get("street_network", {}).get("street_width_building_gap_proxy_m", {})
        if isinstance(proxy, dict):
            ku_references.extend(proxy.get("ku_ids", []))
        for metric in targets.values() if isinstance(targets, dict) else []:
            if isinstance(metric, dict):
                ku_references.extend(KU_PATTERN.findall(str(metric.get("basis", ""))))
        for ku_id in set(ku_references):
            if isinstance(ku_id, str) and not (unit_dir / f"{ku_id}.json").is_file():
                errors.append(f"{label}: 不存在的 KU id {ku_id}")

        for library_id in fabric.get("sources", []):
            if not isinstance(library_id, str) or not (library_dir / f"{library_id}.json").is_file():
                errors.append(f"{label}: 不存在的 library_id {library_id}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="專案根目錄；預設為此腳本所在專案")
    args = parser.parse_args()
    errors = validate_fabrics(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"FAIL: {len(errors)} 項紋理驗證問題")
        return 1
    print(f"PASS: {len(EXPECTED_IDS)} 種都市紋理、schema、預算與本地引用皆有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
