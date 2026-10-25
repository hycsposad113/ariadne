#!/usr/bin/env python3
"""W8-A 凍結清單與重建驗證工具 (Freeze Manifest & Drift Verification).

目標：建立可重算的凍結清單，確保 W8 報告用到的資料、程式、模型設定與方法沒有漂移。
模式：
  --write <MANIFEST_PATH>: 收集並記錄 SHA-256（大檔案串流計算）。
  --check <MANIFEST_PATH>: 重算並逐項比對，輸出 PASS／DRIFT／MISSING 表，任何 DRIFT/MISSING 時 exit 1。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHUNK_SIZE = 1024 * 1024  # 1MB 串流讀取


def sha256_stream(file_path: Path, chunk_size: int = CHUNK_SIZE) -> tuple[str, int]:
    """串流計算檔案的 SHA-256 與位元組大小，避免大檔案耗盡記憶體。"""
    hasher = hashlib.sha256()
    total_bytes = 0
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
            total_bytes += len(chunk)
    return hasher.hexdigest(), total_bytes


def sha256_text(text: str) -> tuple[str, int]:
    """計算字串的 SHA-256 與 UTF-8 位元組大小。"""
    data = text.encode("utf-8")
    return hashlib.sha256(data).hexdigest(), len(data)


def compute_knowledge_combined_hash(knowledge_dir: Path) -> tuple[str, int, int]:
    """計算 knowledge/v2 目錄下所有 JSON 檔案的合併雜湊與檔案數。

    將所有 .json 依相對路徑排序後，依序將路徑與檔案內容串流餵入 SHA-256。
    """
    if not knowledge_dir.is_dir():
        return "", 0, 0
    json_files = sorted(knowledge_dir.rglob("*.json"))
    hasher = hashlib.sha256()
    total_bytes = 0
    for file_path in json_files:
        rel_path = file_path.relative_to(knowledge_dir).as_posix()
        hasher.update(rel_path.encode("utf-8"))
        with open(file_path, "rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                hasher.update(chunk)
                total_bytes += len(chunk)
    return hasher.hexdigest(), total_bytes, len(json_files)


def get_git_info(repo_root: Path) -> dict[str, Any]:
    """讀取當前 git HEAD commit、分支與 status --porcelain 摘要（唯讀）。"""
    head_commit = "unknown"
    branch = "unknown"
    status_summary = {
        "modified_count": 0,
        "untracked_count": 0,
        "staged_count": 0,
        "total_changes": 0,
        "is_clean": False,
    }
    try:
        head_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=repo_root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        status_lines = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=repo_root, text=True, stderr=subprocess.DEVNULL
        ).splitlines()

        modified = 0
        untracked = 0
        staged = 0
        for line in status_lines:
            if not line:
                continue
            code = line[:2]
            if code == "??":
                untracked += 1
            else:
                if code[0] in "MADRC":
                    staged += 1
                if code[1] in "MD":
                    modified += 1

        status_summary = {
            "modified_count": modified,
            "untracked_count": untracked,
            "staged_count": staged,
            "total_changes": len(status_lines),
            "is_clean": len(status_lines) == 0,
        }
    except Exception:
        pass
    return {
        "head_commit": head_commit,
        "branch": branch,
        "status_summary": status_summary,
    }


def get_pip_freeze(python_bin: Path | None = None) -> tuple[str, list[str]]:
    """執行 pip freeze 並取得排序後的輸出與 SHA-256。"""
    executable = str(python_bin) if python_bin and python_bin.exists() else sys.executable
    try:
        raw_output = subprocess.check_output(
            [executable, "-m", "pip", "freeze"], text=True, stderr=subprocess.DEVNULL
        )
        lines = sorted(line.strip() for line in raw_output.splitlines() if line.strip())
        sorted_freeze_text = "\n".join(lines) + "\n"
        digest, _ = sha256_text(sorted_freeze_text)
        return digest, lines
    except Exception:
        return "unknown", []


def get_node_version() -> str:
    """取得 Node.js 版本。"""
    try:
        return subprocess.check_output(["node", "-v"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "missing"


def get_pst_version(repo_root: Path) -> str:
    """取得 PST (pstalgo) 版本。"""
    pst_runtime = Path.home() / ".local/share/urban-design-runtimes/pstalgo-3.3.1"
    pst_config = repo_root / "config/runtimes/pstalgo-3.3.1.json"
    if pst_config.is_file():
        try:
            cfg = json.loads(pst_config.read_text(encoding="utf-8"))
            if "version" in cfg:
                return str(cfg["version"])
        except Exception:
            pass
    if pst_runtime.is_dir():
        return "3.3.1"
    return "missing"


def get_radiance_version() -> str:
    """取得 Radiance 版本字串。"""
    # 嘗試 PATH 或 ~/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/bin/rtrace
    rad_bin = Path.home() / ".local/share/urban-design-runtimes/radiance-6.0.2-arm64/bin/rtrace"
    rad_lib = Path.home() / ".local/share/urban-design-runtimes/radiance-6.0.2-arm64/lib"
    env = os.environ.copy()
    if rad_lib.is_dir():
        env["RAYPATH"] = str(rad_lib)

    candidates = [rad_bin, Path("rtrace")]
    for cand in candidates:
        try:
            out = subprocess.check_output(
                [str(cand), "-version"], env=env, text=True, stderr=subprocess.STDOUT
            ).strip()
            if out:
                return out
        except Exception:
            continue
    return "missing"


def get_qgis_info() -> tuple[str, bool, str]:
    """檢查 QGIS 安裝路徑與版本。"""
    candidates = [
        Path("/Applications/QGIS-LTR.app"),
        Path("/Applications/QGIS.app"),
    ]
    for cand in candidates:
        if cand.exists():
            return str(cand), True, "3.40.5-Bratislava"
    return "/Applications/QGIS-LTR.app", False, "missing"


def find_live_ai_model_configs(repo_root: Path) -> dict[str, Any]:
    """搜尋 repo 內核准之 Live AI 模型名稱與配置（嚴格排除任何憑證與 .env）。"""
    model_cfg_path = repo_root / "config/model-providers.json"
    models_found = []
    if model_cfg_path.is_file():
        try:
            data = json.loads(model_cfg_path.read_text(encoding="utf-8"))
            for profile in data.get("profiles", []):
                models_found.append({
                    "id": profile.get("id"),
                    "adapter": profile.get("adapter"),
                    "model": profile.get("model"),
                    "cli_command": profile.get("cli_command"),
                    "reasoning_effort": profile.get("reasoning_effort"),
                    "enabled": profile.get("enabled", False),
                    "data_egress": profile.get("data_egress"),
                })
        except Exception:
            pass

    return {
        "config_file": "config/model-providers.json",
        "models": models_found,
        "policy": "僅記錄公開模型名稱與設定檔雜湊；嚴格禁止讀取憑證、API key 或 .env 檔。",
    }


def normalize_path(path: Path, repo_root: Path, home_dir: Path | None = None) -> str:
    """將路徑正規化為相對 repo 或以 ~/ 開頭之可移植路徑。"""
    home = home_dir or Path.home()
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        pass
    try:
        rel_home = path.resolve().relative_to(home.resolve()).as_posix()
        return f"~/{rel_home}"
    except ValueError:
        return path.as_posix()


def resolve_manifest_path(path_str: str, repo_root: Path, home_dir: Path | None = None) -> Path:
    """將清單中的路徑解析為本機絕對路徑。"""
    home = home_dir or Path.home()
    if path_str.startswith("~/"):
        return home / path_str[2:]
    p = Path(path_str)
    if p.is_absolute():
        return p
    return repo_root / p


def build_w8_manifest(
    repo_root: Path,
    data_root: Path | None = None,
    test_dir: Path | None = None,
) -> dict[str, Any]:
    """收集並產生完整的 W8 凍結清單字典。"""
    now_iso = datetime.now(timezone.utc).isoformat()
    home = Path.home()
    data_base = data_root or (home / ".local/share/urban-design-data")

    # 若指定 test_dir，則僅掃描 test_dir 下之假檔案（用於測試）
    if test_dir is not None:
        items = []
        for file_path in sorted(test_dir.rglob("*")):
            if file_path.is_file() and not file_path.name.startswith("."):
                digest, size = sha256_stream(file_path)
                rel_path = file_path.relative_to(test_dir).as_posix()
                items.append({
                    "category": "test_mock",
                    "path": rel_path,
                    "size_bytes": size,
                    "sha256": digest,
                    "description": f"測試用假檔案: {rel_path}",
                })
        return {
            "schema_version": "w8-freeze-manifest-v1",
            "created_at": now_iso,
            "test_mode": True,
            "total_items": len(items),
            "items": items,
        }

    # 1. Git 資訊
    git_info = get_git_info(repo_root)

    # 2. 依賴與執行期版本
    py_bin = repo_root / ".venv/bin/python"
    pip_sha, pip_packages = get_pip_freeze(py_bin)
    node_ver = get_node_version()
    pst_ver = get_pst_version(repo_root)
    rad_ver = get_radiance_version()
    qgis_path, qgis_exists, qgis_ver = get_qgis_info()
    py_ver = sys.version.split()[0]

    # 3. Live AI 模型設定
    model_configs = find_live_ai_model_configs(repo_root)

    items: list[dict[str, Any]] = []

    # -------------------------------------------------------------
    # A. 資料集 (Datasets)
    # -------------------------------------------------------------
    # A1. context
    context_files = [
        data_base / "context/manifest.json",
        data_base / "context/context-20260927T153054Z/buildings.geojson",
        data_base / "context/context-20260927T153054Z/green.geojson",
        data_base / "context/context-20260927T153054Z/roads.geojson",
        data_base / "context/context-20260927T153054Z/water.geojson",
        data_base / "context/context-20260927T153054Z/study-area-v5.geojson",
        data_base / "context/context-20260927T153054Z/manifest.json",
    ]
    for p in context_files:
        if p.is_file():
            digest, size = sha256_stream(p)
            items.append({
                "category": "dataset",
                "path": normalize_path(p, repo_root, home),
                "size_bytes": size,
                "sha256": digest,
                "description": f"Context 空間背景圖層: {p.name}",
            })

    # A2. syntax-context
    syntax_context_dir = data_base / "syntax-context/run-20261001T105231Z"
    if syntax_context_dir.is_dir():
        for p in sorted(syntax_context_dir.glob("*.json")):
            digest, size = sha256_stream(p)
            items.append({
                "category": "dataset",
                "path": normalize_path(p, repo_root, home),
                "size_bytes": size,
                "sha256": digest,
                "description": f"Syntax-Context 空間語法背景資料: {p.name}",
            })

    # A3. OSM pbf
    osm_pbf = data_base / "osm/zuid-holland-260922.osm.pbf"
    if osm_pbf.is_file():
        digest, size = sha256_stream(osm_pbf)
        items.append({
            "category": "dataset",
            "path": normalize_path(osm_pbf, repo_root, home),
            "size_bytes": size,
            "sha256": digest,
            "description": "Zuid-Holland 區域 OSM PBF 原始路網資料檔",
        })

    # A4. 3dbag
    bag_dir = data_base / "3dbag"
    if bag_dir.is_dir():
        for p in sorted(bag_dir.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                digest, size = sha256_stream(p)
                items.append({
                    "category": "dataset",
                    "path": normalize_path(p, repo_root, home),
                    "size_bytes": size,
                    "sha256": digest,
                    "description": f"3D BAG 荷蘭建物高度與瓦片索引檔: {p.name}",
                })

    # A5. artifacts/net2/water/
    water_dir = repo_root / "artifacts/net2/water"
    if water_dir.is_dir():
        for p in sorted(water_dir.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                digest, size = sha256_stream(p)
                items.append({
                    "category": "dataset",
                    "path": normalize_path(p, repo_root, home),
                    "size_bytes": size,
                    "sha256": digest,
                    "description": f"Net2 局部水系與覆蓋率成果: {p.name}",
                })

    # -------------------------------------------------------------
    # B. 方法與知識 (Methods & Knowledge)
    # -------------------------------------------------------------
    # B1. knowledge/v2 合併雜湊
    knowledge_dir = repo_root / "knowledge/v2"
    k_digest, k_size, k_count = compute_knowledge_combined_hash(knowledge_dir)
    if k_count > 0:
        items.append({
            "category": "knowledge",
            "path": "knowledge/v2",
            "size_bytes": k_size,
            "sha256": k_digest,
            "description": f"知識庫 v2 全體 JSON 規則合併雜湊 (共 {k_count} 檔)",
            "extra": {"file_count": k_count},
        })

    # B2. src/urban_design 全部 .py
    src_dir = repo_root / "src/urban_design"
    if src_dir.is_dir():
        for p in sorted(src_dir.rglob("*.py")):
            if p.is_file():
                digest, size = sha256_stream(p)
                items.append({
                    "category": "code_src",
                    "path": normalize_path(p, repo_root, home),
                    "size_bytes": size,
                    "sha256": digest,
                    "description": f"都市設計核心模組: {p.relative_to(src_dir).as_posix()}",
                })

    # B3. scripts/ 相關腳本 (.py 與 .cjs，排除快取)
    scripts_dir = repo_root / "scripts"
    if scripts_dir.is_dir():
        for p in sorted(scripts_dir.rglob("*")):
            if p.is_file() and p.suffix in {".py", ".cjs"} and "__pycache__" not in str(p):
                digest, size = sha256_stream(p)
                items.append({
                    "category": "code_script",
                    "path": normalize_path(p, repo_root, home),
                    "size_bytes": size,
                    "sha256": digest,
                    "description": f"維運與分析腳本: {p.name}",
                })

    # -------------------------------------------------------------
    # C. 方案與結果 (Proposals & Results)
    # -------------------------------------------------------------
    # C1. artifacts/net2/round-3/plans/*-plan.json
    net2_plans_dir = repo_root / "artifacts/net2/round-3/plans"
    if net2_plans_dir.is_dir():
        for p in sorted(net2_plans_dir.glob("*-plan.json")):
            digest, size = sha256_stream(p)
            items.append({
                "category": "proposal",
                "path": normalize_path(p, repo_root, home),
                "size_bytes": size,
                "sha256": digest,
                "description": f"Net2 Round-3 設計方案成果: {p.name}",
            })

    # C2. artifacts/fab1/run-6/*-plan.json
    fab1_plans_dir = repo_root / "artifacts/fab1/run-6"
    if fab1_plans_dir.is_dir():
        for p in sorted(fab1_plans_dir.glob("*-plan.json")):
            digest, size = sha256_stream(p)
            items.append({
                "category": "proposal",
                "path": normalize_path(p, repo_root, home),
                "size_bytes": size,
                "sha256": digest,
                "description": f"Fab1 Run-6 基準設計方案成果: {p.name}",
            })

    # C3. W8 定案：平台整合包 run-8、NET2 round-7 v3 語法與路段、W8 圖組
    final_sets = [
        ("artifacts/fab1/run-8", ("*.json", "*.csv", "ai-explanations/*.md", "ai-explanations/*.json"), "proposal", "W8 定案平台整合包 run-8"),
        ("artifacts/net2/round-7/plans", ("*.json",), "proposal", "NET2 第 7 輪定案方案"),
        ("artifacts/net2/round-7/syntax", ("*.json", "segments/*.geojson", "segments/*.receipt.json"), "result", "NET2 第 7 輪 v3 語法（12 組）"),
        ("artifacts/net2/round-7/v3-export", ("net2-assessment.json", "net2-table-zh.md"), "result", "NET2 第 7 輪 v3 評估"),
        ("artifacts/w8/figures/round-7-v3", ("*.png", "manifest.json"), "result", "W8 報告圖組"),
    ]
    for rel, patterns, category, label in final_sets:
        base = repo_root / rel
        if not base.is_dir():
            continue
        for pattern in patterns:
            for p in sorted(base.glob(pattern)):
                if p.is_file():
                    digest, size = sha256_stream(p)
                    items.append({"category": category, "path": normalize_path(p, repo_root, home),
                                  "size_bytes": size, "sha256": digest, "description": f"{label}: {p.name}"})

    # -------------------------------------------------------------
    # D. 依賴與執行期 (Dependencies & Runtimes)
    # -------------------------------------------------------------
    # D1. pip freeze
    items.append({
        "category": "dependency",
        "path": "dependency:pip_freeze",
        "size_bytes": len(pip_packages),
        "sha256": pip_sha,
        "description": f"Python 虛擬環境套件清單 (pip freeze, {len(pip_packages)} 套件)",
    })

    # D2. web/package-lock.json
    pkg_lock = repo_root / "web/package-lock.json"
    if pkg_lock.is_file():
        digest, size = sha256_stream(pkg_lock)
        items.append({
            "category": "dependency",
            "path": normalize_path(pkg_lock, repo_root, home),
            "size_bytes": size,
            "sha256": digest,
            "description": "前端 Web npm package-lock.json 鎖定檔",
        })

    # D3. Runtimes
    py_digest, _ = sha256_text(py_ver)
    items.append({
        "category": "runtime",
        "path": "runtime:python",
        "size_bytes": len(py_ver.encode("utf-8")),
        "sha256": py_digest,
        "description": f"Python 執行期版本: {py_ver}",
    })

    node_digest, _ = sha256_text(node_ver)
    items.append({
        "category": "runtime",
        "path": "runtime:node",
        "size_bytes": len(node_ver.encode("utf-8")),
        "sha256": node_digest,
        "description": f"Node.js 執行期版本: {node_ver}",
    })

    pst_digest, _ = sha256_text(pst_ver)
    items.append({
        "category": "runtime",
        "path": "runtime:pstalgo",
        "size_bytes": len(pst_ver.encode("utf-8")),
        "sha256": pst_digest,
        "description": f"PST (Place Syntax Tool) 空間語法版本: {pst_ver}",
    })

    rad_digest, _ = sha256_text(rad_ver)
    items.append({
        "category": "runtime",
        "path": "runtime:radiance",
        "size_bytes": len(rad_ver.encode("utf-8")),
        "sha256": rad_digest,
        "description": f"Radiance 日照模擬版本: {rad_ver}",
    })

    qgis_digest, _ = sha256_text(f"{qgis_path}:{qgis_exists}")
    items.append({
        "category": "runtime",
        "path": "runtime:qgis",
        "size_bytes": len(qgis_path.encode("utf-8")),
        "sha256": qgis_digest,
        "description": f"QGIS 應用程式路徑狀態: {qgis_path} (存在: {qgis_exists}, 版本: {qgis_ver})",
    })

    # -------------------------------------------------------------
    # E. 模型與 Prompt 設定 (Model & Prompt Configurations)
    # -------------------------------------------------------------
    model_cfg = repo_root / "config/model-providers.json"
    if model_cfg.is_file():
        digest, size = sha256_stream(model_cfg)
        items.append({
            "category": "model_prompt",
            "path": normalize_path(model_cfg, repo_root, home),
            "size_bytes": size,
            "sha256": digest,
            "description": "Live AI 模型與 Provider 路由設定 (不含任何密鑰)",
        })

    prompt_docs_dir = repo_root / "docs/prompts"
    if prompt_docs_dir.is_dir():
        for p in sorted(prompt_docs_dir.glob("*.md")):
            digest, size = sha256_stream(p)
            items.append({
                "category": "model_prompt",
                "path": normalize_path(p, repo_root, home),
                "size_bytes": size,
                "sha256": digest,
                "description": f"模型 Prompt 範本規格文件: {p.name}",
            })

    w6_acceptance = repo_root / "docs/w6/live-ai-acceptance-packet-20261005T0000Z.md"
    if w6_acceptance.is_file():
        digest, size = sha256_stream(w6_acceptance)
        items.append({
            "category": "model_prompt",
            "path": normalize_path(w6_acceptance, repo_root, home),
            "size_bytes": size,
            "sha256": digest,
            "description": "Live AI 驗收認證與規格封包",
        })

    # -------------------------------------------------------------
    # F. Git 項目
    # -------------------------------------------------------------
    if git_info.get("head_commit") != "unknown":
        head_digest, _ = sha256_text(git_info["head_commit"])
        items.append({
            "category": "git",
            "path": "git:head",
            "size_bytes": 40,
            "sha256": head_digest,
            "description": f"Git HEAD Commit: {git_info['head_commit']}",
        })

    return {
        "schema_version": "w8-freeze-manifest-v1",
        "created_at": now_iso,
        "git": git_info,
        "environment": {
            "python_version": py_ver,
            "python_executable": str(py_bin.resolve()) if py_bin.exists() else sys.executable,
            "node_version": node_ver,
            "pst_version": pst_ver,
            "radiance_version": rad_ver,
            "qgis_path": qgis_path,
            "qgis_exists": qgis_exists,
            "qgis_version": qgis_ver,
            "pip_freeze_sha256": pip_sha,
            "pip_freeze_packages_count": len(pip_packages),
            "pip_freeze_packages": pip_packages,
        },
        "models": model_configs,
        "total_items": len(items),
        "items": items,
    }


def verify_manifest(
    manifest: dict[str, Any],
    repo_root: Path,
    data_root: Path | None = None,
) -> tuple[bool, list[dict[str, Any]], dict[str, int]]:
    """逐項重算並核對清單內容。

    回傳:
      (is_all_passed, results_list, summary_counts)
    """
    home = Path.home()
    results: list[dict[str, Any]] = []
    counts = {"PASS": 0, "DRIFT": 0, "MISSING": 0}

    is_test_mode = manifest.get("test_mode", False)

    for item in manifest.get("items", []):
        cat = item.get("category", "")
        path_str = item.get("path", "")
        expected_sha = item.get("sha256", "")
        expected_size = item.get("size_bytes", 0)
        desc = item.get("description", "")

        status = "PASS"
        actual_sha = ""
        actual_size = 0
        detail = ""

        # 特殊項目檢查
        if cat == "knowledge" and path_str == "knowledge/v2":
            k_dir = repo_root / "knowledge/v2"
            if not k_dir.is_dir():
                status = "MISSING"
                detail = f"知識庫目錄不存在: {k_dir}"
            else:
                k_sha, k_bytes, k_cnt = compute_knowledge_combined_hash(k_dir)
                actual_sha = k_sha
                actual_size = k_bytes
                exp_cnt = item.get("extra", {}).get("file_count")
                if k_sha != expected_sha:
                    status = "DRIFT"
                    detail = f"知識庫 SHA 漂移: 預期 {expected_sha[:12]}..., 實際 {k_sha[:12]}... (檔案數: 預期 {exp_cnt}, 實際 {k_cnt})"
                elif exp_cnt is not None and k_cnt != exp_cnt:
                    status = "DRIFT"
                    detail = f"知識庫檔案數漂移: 預期 {exp_cnt}, 實際 {k_cnt}"

        elif cat == "dependency" and path_str == "dependency:pip_freeze":
            py_bin = repo_root / ".venv/bin/python"
            cur_sha, cur_pkgs = get_pip_freeze(py_bin)
            actual_sha = cur_sha
            actual_size = len(cur_pkgs)
            if cur_sha != expected_sha:
                status = "DRIFT"
                detail = f"pip freeze 依賴漂移: 預期雜湊 {expected_sha[:12]}..., 實際 {cur_sha[:12]}..."

        elif cat == "runtime" and path_str == "runtime:python":
            cur_ver = sys.version.split()[0]
            cur_sha, _ = sha256_text(cur_ver)
            actual_sha = cur_sha
            if cur_sha != expected_sha:
                status = "DRIFT"
                detail = f"Python 版本漂移: 預期雜湊 {expected_sha[:12]}..., 實際版本 {cur_ver}"

        elif cat == "runtime" and path_str == "runtime:node":
            cur_node = get_node_version()
            cur_sha, _ = sha256_text(cur_node)
            actual_sha = cur_sha
            if cur_sha != expected_sha:
                status = "DRIFT"
                detail = f"Node.js 版本漂移: 預期雜湊 {expected_sha[:12]}..., 實際版本 {cur_node}"

        elif cat == "runtime" and path_str == "runtime:pstalgo":
            cur_pst = get_pst_version(repo_root)
            cur_sha, _ = sha256_text(cur_pst)
            actual_sha = cur_sha
            if cur_sha != expected_sha:
                status = "DRIFT"
                detail = f"PST 版本漂移: 預期雜湊 {expected_sha[:12]}..., 實際版本 {cur_pst}"

        elif cat == "runtime" and path_str == "runtime:radiance":
            cur_rad = get_radiance_version()
            cur_sha, _ = sha256_text(cur_rad)
            actual_sha = cur_sha
            if cur_sha != expected_sha:
                status = "DRIFT"
                detail = f"Radiance 版本漂移: 預期雜湊 {expected_sha[:12]}..., 實際版本 {cur_rad}"

        elif cat == "runtime" and path_str == "runtime:qgis":
            cur_qgis_path, cur_qgis_exists, cur_qgis_ver = get_qgis_info()
            cur_sha, _ = sha256_text(f"{cur_qgis_path}:{cur_qgis_exists}")
            actual_sha = cur_sha
            if cur_sha != expected_sha:
                status = "DRIFT"
                detail = f"QGIS 路徑狀態漂移: 預期雜湊 {expected_sha[:12]}..., 實際路徑 {cur_qgis_path} (存在: {cur_qgis_exists})"

        elif cat == "git" and path_str == "git:head":
            git_info = get_git_info(repo_root)
            cur_head = git_info.get("head_commit", "")
            cur_sha, _ = sha256_text(cur_head)
            actual_sha = cur_sha
            if cur_sha != expected_sha:
                status = "DRIFT"
                detail = f"Git HEAD 漂移: 預期雜湊 {expected_sha[:12]}..., 實際 HEAD {cur_head}"

        else:
            # 一般檔案檢查
            target_path = resolve_manifest_path(path_str, repo_root, home)
            if not target_path.exists():
                status = "MISSING"
                detail = f"檔案缺失不存在: {target_path}"
            elif not target_path.is_file():
                status = "MISSING"
                detail = f"目標非一般檔案: {target_path}"
            else:
                try:
                    file_sha, file_bytes = sha256_stream(target_path)
                    actual_sha = file_sha
                    actual_size = file_bytes
                    if file_sha != expected_sha:
                        status = "DRIFT"
                        detail = (
                            f"內容雜湊漂移: 預期 {expected_sha[:12]}..., 實際 {file_sha[:12]}... "
                            f"(大小: 預期 {expected_size:,} B, 實際 {file_bytes:,} B)"
                        )
                except Exception as exc:
                    status = "DRIFT"
                    detail = f"讀取或計算雜湊時發生錯誤: {exc}"

        counts[status] += 1
        results.append({
            "status": status,
            "category": cat,
            "path": path_str,
            "expected_sha": expected_sha,
            "actual_sha": actual_sha,
            "expected_size": expected_size,
            "actual_size": actual_size,
            "description": desc,
            "detail": detail,
        })

    is_all_passed = (counts["DRIFT"] == 0 and counts["MISSING"] == 0)
    return is_all_passed, results, counts


def format_table(results: list[dict[str, Any]], counts: dict[str, int]) -> str:
    """輸出對齊且清晰之繁體中文 PASS / DRIFT / MISSING 檢查表。"""
    lines = []
    lines.append("=" * 105)
    lines.append(f"{'狀態 (Status)':<9} | {'類別 (Category)':<14} | {'大小 (Size)':<14} | {'路徑 / 項目名稱 (Path / Item)':<40} | 說明")
    lines.append("-" * 105)

    for r in results:
        status = r["status"]
        cat = r["category"]
        path_str = r["path"]
        if len(path_str) > 40:
            path_disp = "..." + path_str[-37:]
        else:
            path_disp = path_str

        size_disp = f"{r['actual_size'] or r['expected_size']:,} B"
        desc = r["description"]
        if len(desc) > 30:
            desc = desc[:28] + ".."

        lines.append(f"{status:<9} | {cat:<14} | {size_disp:<14} | {path_disp:<40} | {desc}")

        if status in {"DRIFT", "MISSING"} and r["detail"]:
            lines.append(f"          ↳ [診斷原因] {r['detail']}")

    lines.append("=" * 105)
    lines.append("【W8 凍結驗證結果摘要】")
    lines.append(f"  總檢核項目數 : {len(results)}")
    lines.append(f"  通過 (PASS)   : {counts['PASS']}")
    lines.append(f"  漂移 (DRIFT)  : {counts['DRIFT']}")
    lines.append(f"  缺失 (MISSING): {counts['MISSING']}")
    if counts["DRIFT"] == 0 and counts["MISSING"] == 0:
        lines.append("  整體判定結果 : [PASS] 全數吻合，未偵測到任何資料、程式、模型設定或依賴漂移！")
    else:
        lines.append("  整體判定結果 : [FAILED] 偵測到漂移或檔案缺失，已標示詳細原因並中斷執行 (exit 1)！")
    lines.append("=" * 105)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="W8-A 凍結清單與重建驗證工具")
    parser.add_argument("--write", metavar="MANIFEST_PATH", help="收集並記錄 SHA-256 至指定清單 JSON 檔")
    parser.add_argument("--check", metavar="MANIFEST_PATH", help="重算並逐項比對指定清單 JSON 檔")
    parser.add_argument("--repo-root", type=Path, default=None, help="指定 Repository 根目錄 (預設為當前目錄或 git root)")
    parser.add_argument("--data-root", type=Path, default=None, help="指定資料集根目錄 (預設為 ~/.local/share/urban-design-data)")
    parser.add_argument("--test-dir", type=Path, default=None, help="測試模式：僅掃描並凍結指定目錄之假檔案")

    args = parser.parse_args()

    # 判斷 repo_root
    repo_root = args.repo_root or Path(__file__).resolve().parents[1]
    data_root = args.data_root or (Path.home() / ".local/share/urban-design-data")

    if not args.write and not args.check:
        parser.print_help()
        sys.exit(2)

    if args.write:
        target_manifest = Path(args.write)
        if not target_manifest.is_absolute():
            target_manifest = repo_root / target_manifest

        print(f"[*] 正在收集並計算 W8 凍結清單 SHA-256 (儲存至: {target_manifest})...")
        manifest_data = build_w8_manifest(repo_root, data_root, test_dir=args.test_dir)

        target_manifest.parent.mkdir(parents=True, exist_ok=True)
        with open(target_manifest, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, ensure_ascii=False, indent=2)

        print(f"[+] 凍結清單產生成功！共記錄 {manifest_data['total_items']} 個項目。")
        sys.exit(0)

    if args.check:
        target_manifest = Path(args.check)
        if not target_manifest.is_absolute():
            target_manifest = repo_root / target_manifest

        if not target_manifest.is_file():
            print(f"[!] 錯誤：找不到指定的凍結清單檔案: {target_manifest}", file=sys.stderr)
            sys.exit(1)

        print(f"[*] 正在重算並驗證 W8 凍結清單 (來源: {target_manifest})...")
        with open(target_manifest, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        passed, results, counts = verify_manifest(manifest_data, repo_root, data_root)
        table_output = format_table(results, counts)
        print(table_output)

        if not passed:
            sys.exit(1)
        sys.exit(0)


if __name__ == "__main__":
    main()
