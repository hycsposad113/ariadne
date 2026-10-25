#!/usr/bin/env python3
"""Generate A/B dictionary-driven morphology previews for all five recipes."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from urban_design.morphology.dictionary_generator import (
    DictionaryGenerationError,
    run_dictionary_generator,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("out/dictionary-generator/run-01"),
        help="new or empty output directory (default: out/dictionary-generator/run-01)",
    )
    parser.add_argument("--root", type=Path, help="project root; defaults to this checkout")
    parser.add_argument("--study-area", type=Path, help="explicit StudyArea GeoJSON override")
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        comparison = run_dictionary_generator(
            args.output,
            root=args.root,
            study_area_path=args.study_area,
            seed=args.seed,
        )
    except (DictionaryGenerationError, OSError, ValueError) as exc:
        print(f"狀態：FAIL — {exc}", file=sys.stderr)
        return 2

    print(f"狀態：{comparison['run_status']}")
    print(f"有效方案：A {comparison['valid_count_by_intensity']['A']}/5；B {comparison['valid_count_by_intensity']['B']}/5")
    print(f"輸出：{args.output.resolve()}")
    print("強度 | 策略 | 陸地 FAR | 建蔽率 | 最高已知高度 m | 開放空間比 | 外部接點 | 有效 | 型態組成")
    for row in comparison["strategies"]:
        contacts = row["external_contacts"]
        connected = contacts.get("connected", 0) if isinstance(contacts, dict) else 0
        print(
            f"{row['intensity']} | {row['strategy_id']} | {row['land_far']:.6f} | "
            f"{row['coverage_ratio']:.6f} | {row['maximum_height_m']:.3f} | "
            f"{row['open_space_ratio']:.6f} | {connected} | {row['valid']} | "
            f"{row['type_composition']['building_type_ids']}"
        )
        if row["failure_reasons"]:
            for reason in row["failure_reasons"]:
                print(f"  失敗原因：{reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
