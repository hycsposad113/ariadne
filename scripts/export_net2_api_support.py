"""Append receipt-bound read-only API support without changing frozen plan/check bytes."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

FABRICS = ('harbour_grain', 'closed_block_extension', 'courtyard_islands', 'landscape_figure')


def append(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f'Existing support differs; refusing overwrite: {path}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def export(root: Path, mirror: Path) -> list[str]:
    created = []
    for key in FABRICS:
        plan_path, raw_path = root / f'{key}-plan.json', root / f'{key}-checks.json'
        plan, raw = json.loads(plan_path.read_text()), json.loads(raw_path.read_text())
        core = raw.get('core_validator', raw)
        if plan['fabric_id'] != f'fabric.{key}' or raw.get('fabric_id') not in (key, plan['fabric_id']):
            raise ValueError(f'Identity mismatch: {key}')
        if core != plan['validation'] or raw.get('failure_ids') != core['failure_ids']:
            raise ValueError(f'Validation mismatch: {key}')
        receipts = {name: {'path': str(path.resolve()), 'sha256': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()}
                    for name, path in [('plan', plan_path), ('raw_checks', raw_path)]}
        wrapper = {'schema_version': 'fabric-api-checks-v1', 'fabric_id': key,
                   'core_validator': core, 'failure_ids': core['failure_ids'], 'source_receipts': receipts}
        files = {f'{key}-api-checks.json': (json.dumps(wrapper, ensure_ascii=False, indent=2) + '\n').encode()}
        metrics = plan['metrics']
        failures = ', '.join(core['failure_ids']) or 'none'
        source = f"{plan_path.name} ({receipts['plan']['sha256']}); {raw_path.name} ({receipts['raw_checks']['sha256']})"
        for lang in ('zh', 'en'):
            if lang == 'en':
                text = (f'# {key}: deterministic exploratory summary\n\n'
                        f'This draft has not been accepted by the designer. The frozen validator reports {core["status"]}. '
                        f'Failed checks: {failures}.\n\n'
                        f'Projected land area: {metrics["land_area_m2"]:.3f} m²; new gross floor area: {metrics["new_gfa_m2"]:.3f} m²; '
                        f'new floor area ratio: {metrics["new_far"]:.6f}. Values come directly from the frozen plan metrics. '
                        'These geometry measurements do not establish movement volumes or an overall preferred scenario. '
                        'Network reference checks are separate exploratory evidence; unavailable measurements remain unproven.\n\n'
                        f'Sources: {source}.\n')
            else:
                text = (f'# {key}：確定性工具的探索性摘要\n\n'
                        f'此草案尚未獲設計者接受。凍結驗證器結果為 {core["status"]}。未通過的檢查：{failures}。\n\n'
                        f'投影陸地面積 {metrics["land_area_m2"]:.3f} m²；新增樓地板面積 {metrics["new_gfa_m2"]:.3f} m²；'
                        f'新增容積比 {metrics["new_far"]:.6f}。數值直接取自凍結方案的 metrics。'
                        '幾何量測不能證明通行量，也不能據此選出整體優勝方案。路網參考基準檢查屬獨立的探索性證據；缺失量測維持未證實。\n\n'
                        f'來源：{source}。\n')
            files[f'ai-explanations/{key}-design-statement-{lang}.md'] = text.encode()
        for relative, content in files.items():
            append(root / relative, content)
            # Mirror only after confirming the immutable parents are byte-identical.
            for parent in (plan_path, raw_path):
                if (mirror / parent.name).read_bytes() != parent.read_bytes():
                    raise ValueError(f'Mirror parent drift: {parent.name}')
            append(mirror / relative, content)
            created.append(relative)
    return created


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('artifacts/fab1/run-7'))
    parser.add_argument('--mirror', type=Path, default=Path('artifacts/net2/round-3/plans'))
    args = parser.parse_args()
    print(json.dumps({'support_files': export(args.root, args.mirror)}, indent=2))
