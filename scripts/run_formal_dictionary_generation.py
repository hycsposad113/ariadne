#!/usr/bin/env python3
"""W6-A formal generation gate. BLOCKED inputs never reach fixture generation.

Only the explicitly supplied rehearsal database can be used; runtime paths are rejected.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from urban_design.generation_context import FreezeRequest, freeze_context, resolve_readiness
from urban_design.store import ProjectStateStore
from urban_design.generation.formal_adapter import adapt_frozen_context, retained_gfa_bounds, VERSION as ADAPTER_VERSION
from urban_design.generation.hashing import generation_context_digest
from urban_design.approved_generation import _load_approved_inputs
from urban_design.generation.formal_pipeline import run_formal_pipeline, VERSION


def checked_database(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if '.urban_design_runtime' in resolved.parts:
        raise ValueError('BLOCKED: runtime databases are prohibited; use the authorised rehearsal copy')
    if not resolved.is_file():
        raise ValueError('database must be an existing file')
    return resolved


def preflight(database: Path, project_id: str | None = None, *, seed: int = 42, dry_run: bool = False) -> dict:
    database = checked_database(database)
    with ProjectStateStore(database, read_only=True) as store:
        if project_id is None:
            projects = store.list_current('Project')
            if len(projects) != 1:
                raise ValueError('exactly one Project required or specify --project-id')
            project_id = projects[0].entity_id
        readiness = resolve_readiness(store, project_id)
        frozen = None
        typed_context = None
        retained_gfa = None
        blockers = list(readiness.blockers)
        if readiness.status == 'READY':
            assert readiness.context is not None and readiness.context_hash is not None
            frozen = freeze_context(store, project_id, FreezeRequest(
                expected_workspace_revision=readiness.context.workspace_revision,
                expected_context_hash=readiness.context_hash))
            typed_context = adapt_frozen_context(frozen, seed=seed)
            retained_gfa = retained_gfa_bounds(frozen.context)
            if retained_gfa['status'] == 'UNAVAILABLE':
                blockers.append('Hard FAR cannot be verified: retained GFA is unavailable for '+', '.join(retained_gfa['unavailable_buildings'])+'. Heights are now bound at freeze; unknown GFA remains unavailable, not zero.')
            pipeline = None
            if not blockers:
                inputs = _load_approved_inputs(store, project_id, site_generation=True)
                pipeline = run_formal_pipeline(typed_context, frozen.context, inputs)
                blockers.extend(pipeline['blockers'])
        pipeline = locals().get('pipeline') or {}
        return dict(status=pipeline.get('status', 'BLOCKED'), phase='FORMAL_DICTIONARY',
                    implementation_status='IMPLEMENTED_PENDING_REVIEW' if pipeline.get('status')=='READY' else 'PARTIAL', database=str(database), project_id=project_id,
                    dry_run=dry_run, seed=seed, recipe_version=VERSION,
                    readiness=readiness.model_dump(mode='json'),
                    frozen_context=None if frozen is None else frozen.model_dump(mode='json'),
                    typed_context=None if typed_context is None else typed_context.model_dump(mode='json'),
                    typed_context_hash=None if typed_context is None else generation_context_digest(typed_context),
                    adapter_version=ADAPTER_VERSION, retained_gfa=retained_gfa,
                    blockers=blockers, scenario_ids=[], candidates=pipeline.get('candidates', []),
                    pairwise_differences=pipeline.get('pairwise_differences', []),
                    authored_recipe_settings=pipeline.get('authored_recipe_settings'),
                    routing_overlay_residue_m2=pipeline.get('routing_overlay_residue_m2'),
                    commander_assumptions=pipeline.get('commander_assumptions', []),
                    candidate_generation_status='RUN' if pipeline else 'NOT_RUN', actor='AGENT_AUTOMATION',
                    database_access='READ_ONLY', overall_winner=None)


def write_report(report: dict, output: Path, *, existing=False) -> None:
    # A new directory is mandatory: preserve prior runs, even after failure.
    if not existing:
        output.mkdir(parents=True, exist_ok=False)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n')
    text = ['# W6-A 正式字典生成', '', '狀態：'+report['status'], '',
            '## 阻擋原因', '', *['- '+reason for reason in report['blockers']], '',
            '## ASSUMED_COMMANDER', '', *['- '+reason for reason in report.get('commander_assumptions', [])], '',
            '## 保留建築', '', '| BAG ID | 狀態 | 層數下–上界 | GFA 下–上界 m² | snapshot |', '|---|---|---|---|---|']
    context = (report.get('frozen_context') or {}).get('context') or {}
    for row in context.get('floor_estimates', []):
        floors = row['floor_count']
        text.append(f"| {row['bag_id']} | {row['status']} | {floors.get('lower')}–{floors.get('upper')} | {row.get('gfa_lower_m2')}–{row.get('gfa_upper_m2')} | {', '.join(row.get('snapshot_ids', []))} |")
    text += ['', '## 方案', '', '| 策略 / Scenario | 狀態 | FAR (land_area) | 分母 m² | 建蔽率 | 新建最高 m | 開放空間比例 / ≥40% |', '|---|---|---|---|---|---|---|']
    for row in report.get('candidates', []):
        m=row.get('metrics', {})
        text.append(f"| {row['recipe_id']} / {row.get('scenario_id', '')} | {row['status']} | {m.get('far')} | {m.get('far_denominator_m2')} | {m.get('coverage')} | {m.get('highest_new_height_m')} | {m.get('open_space_ratio')} / {m.get('open_space_preference_met')} |")
        text += ['', f"{row['recipe_id']} 各區用途 GFA m²：{m.get('program_gfa_m2')}", f"五區配置：{m.get('zone_uses')}", f"失敗原因：{row['failure_reasons']}", f"新建／總 GFA 上界 m²：{m.get('new_gfa_m2')} / {m.get('total_gfa_upper_m2')}；保留 GFA 下–上界 m²：{m.get('retained_gfa_lower_m2')}–{m.get('retained_gfa_upper_m2')}", f"UNALLOCATED 比例：{m.get('unallocated_share')}；型態：{m.get('dictionary_types')}", '']
    settings = report.get('authored_recipe_settings') or {}
    text += ['', '## authored recipe settings', '', '```json', json.dumps(settings, ensure_ascii=False, indent=2), '```', '']
    text += ['', '## 每棟新建型態', '', '| 策略 | 建築 | 型態 | 高度 m | 用途 |', '|---|---|---|---|---|']
    for row in report.get('candidates', []):
        for b in ((row.get('stages') or {}).get('massing') or {}).get('buildings', []):
            text.append(f"| {row['recipe_id']} | {b['id']} | {b['type_id']} | {b['height_m']} | {b['use']} |")
    text += ['', 'Routing 數值殘片面積 m²：'+str(report.get('routing_overlay_residue_m2'))+'；原 FAR 分母保留。接點內側 witness 位移 ≤10⁻⁶ m；正式 noding 精度 10⁻⁶ m。', '', '## 方案間差異', '', '道路／真實街廓／主要開放空間／量體 footprint 對稱差面積比，加上用途 GFA 比例的 total variation；至少兩項 ≥0.1。此門檻為 recipe 工程設定，不是核准設計約束。', '',
             '```json', json.dumps(report.get('pairwise_differences', []), ensure_ascii=False, indent=2), '```', '',
             '## 限制', '', '沿用 W5 courtyard、L、bar、point_array footprint operators，透過正式 adapter 接入；無加蓋候選。point_array 僅採 footprint 能力，其案例 tower 樓層範圍 6–28 不用作本案限制；本案以 D2 與 authored recipe 配置 4–5 層。此為低層點陣量體，不宣稱符合高層 tower 案例。五區外最近分區用途延伸與逐層用途比例標 ASSUMED_FROM_PORTFOLIO；不是已核准用途或新分區。Portfolio p9 的全址比例是參考而非硬約束，p18 無可機讀數值，本輪沒有補造。',
             'Open space 為陸地扣除建築與道路的幾何餘量，不代表公共可達性或已設計公園。',
             '未建立 HumanDecision、未接受方案、未升級舊 UNAPPROVED_PREVIEW；需 Claude 獨立 review 與 Founder 決定。', '']
    (output / 'report.md').write_text('\n'.join(text))


from urban_design.generation.formal_persistence import persist_results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--project-id')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        report = preflight(args.database, args.project_id, seed=args.seed, dry_run=args.dry_run)
        output = args.output or Path('out/formal-dictionary') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output.mkdir(parents=True, exist_ok=False)
        persist_results(report, args.database, output, dry_run=args.dry_run)
        write_report(report, output, existing=True)
    except (OSError, ValueError) as exc:
        print(f'BLOCKED: {exc}')
        return 2
    print(f"{report['status']}: Scenario ids: {report['scenario_ids']}; report: {output.resolve()}")
    return 0 if report['status']=='READY' else 2


if __name__ == '__main__':
    raise SystemExit(main())
