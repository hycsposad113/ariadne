#!/usr/bin/env python3
"""Print a local v2 knowledge context pack for one research question."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from urban_design.knowledge.retrieval_v2 import KnowledgeIndexError, build_context_pack  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="以本機 knowledge/v2 建立研究生作答情境包。")
    parser.add_argument("question", help="單一研究問題")
    parser.add_argument("--max-chars", type=int, default=50000, metavar="N",
                        help="輸出字元上限（預設：50000）")
    args = parser.parse_args(argv)
    try:
        pack = build_context_pack(args.question, root=REPO_ROOT, max_chars=args.max_chars)
    except (KnowledgeIndexError, ValueError) as exc:
        parser.error(str(exc))
    sys.stdout.write(pack.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
