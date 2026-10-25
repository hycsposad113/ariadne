"""測試 W8 凍結清單與重建驗證工具 (scripts/verify_w8_freeze.py).

驗證流程：
  暫存目錄假檔案：寫入 → 檢查 PASS → 改一個檔 → DRIFT exit 1 → 刪除一個檔 → MISSING exit 1
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/verify_w8_freeze.py"

# 確保可直接 import 腳本模組進行單元測試
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.verify_w8_freeze as vfreeze


def test_verify_w8_freeze_workflow(tmp_path: Path) -> None:
    """端對端測試：寫入 -> 檢查 PASS -> 修改檔案觸發 DRIFT -> 刪除檔案觸發 MISSING。"""
    # 1. 建立測試用假目錄與檔案
    mock_data = tmp_path / "data"
    mock_data.mkdir()
    file_a = mock_data / "sample.geojson"
    file_a.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    mock_src = tmp_path / "src"
    mock_src.mkdir()
    file_b = mock_src / "pipeline.py"
    file_b.write_text("print('urban design pipeline ready')\n", encoding="utf-8")

    manifest_file = tmp_path / "test-manifest.json"

    # 2. 模式一：--write 寫入凍結清單
    cmd_write = [
        sys.executable,
        str(SCRIPT_PATH),
        "--write",
        str(manifest_file),
        "--test-dir",
        str(tmp_path),
        "--repo-root",
        str(tmp_path),
    ]
    proc_write = subprocess.run(cmd_write, capture_output=True, text=True, check=False)
    assert proc_write.returncode == 0, f"Write failed: {proc_write.stderr}"
    assert manifest_file.is_file(), "Manifest file was not created"

    # 驗證產生的清單格式
    with open(manifest_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("schema_version") == "w8-freeze-manifest-v1"
    assert data.get("total_items") >= 2

    # 3. 模式二：--check 首次檢查（應全數 PASS，exit 0）
    cmd_check = [
        sys.executable,
        str(SCRIPT_PATH),
        "--check",
        str(manifest_file),
        "--repo-root",
        str(tmp_path),
    ]
    proc_check_pass = subprocess.run(cmd_check, capture_output=True, text=True, check=False)
    assert proc_check_pass.returncode == 0, f"Check failed unexpectedly: {proc_check_pass.stdout}"
    assert "通過 (PASS)   : 2" in proc_check_pass.stdout or "PASS" in proc_check_pass.stdout
    assert "漂移 (DRIFT)  : 0" in proc_check_pass.stdout
    assert "缺失 (MISSING): 0" in proc_check_pass.stdout
    assert "[PASS] 全數吻合" in proc_check_pass.stdout

    # 4. 改動其中一個檔案內容以模擬漂移
    file_a.write_text('{"type": "FeatureCollection", "features": [{"id": 1}]}', encoding="utf-8")

    # 5. 再次 --check 檢查（應偵測到 DRIFT 並 exit 1）
    proc_check_drift = subprocess.run(cmd_check, capture_output=True, text=True, check=False)
    assert proc_check_drift.returncode == 1, "Expected exit 1 upon DRIFT detection"
    assert "DRIFT" in proc_check_drift.stdout
    assert "內容雜湊漂移" in proc_check_drift.stdout
    assert "[FAILED]" in proc_check_drift.stdout

    # 6. 刪除檔案以模擬檔案缺失
    file_a.unlink()

    # 7. 再次 --check 檢查（應偵測到 MISSING 並 exit 1）
    proc_check_missing = subprocess.run(cmd_check, capture_output=True, text=True, check=False)
    assert proc_check_missing.returncode == 1, "Expected exit 1 upon MISSING detection"
    assert "MISSING" in proc_check_missing.stdout
    assert "檔案缺失不存在" in proc_check_missing.stdout


def test_verify_manifest_programmatic(tmp_path: Path) -> None:
    """單元測試：直接呼叫 verify_manifest 函式驗證比對邏輯。"""
    test_file = tmp_path / "unit.json"
    test_file.write_text('{"key": "value"}', encoding="utf-8")

    digest, size = vfreeze.sha256_stream(test_file)

    manifest = {
        "schema_version": "w8-freeze-manifest-v1",
        "items": [
            {
                "category": "test",
                "path": "unit.json",
                "size_bytes": size,
                "sha256": digest,
                "description": "單元測試檔案",
            }
        ],
    }

    passed, results, counts = vfreeze.verify_manifest(manifest, repo_root=tmp_path)
    assert passed is True
    assert counts["PASS"] == 1
    assert counts["DRIFT"] == 0
    assert counts["MISSING"] == 0

    # 篡改檔案觸發 DRIFT
    test_file.write_text('{"key": "tampered"}', encoding="utf-8")
    passed_drift, _, counts_drift = vfreeze.verify_manifest(manifest, repo_root=tmp_path)
    assert passed_drift is False
    assert counts_drift["DRIFT"] == 1
