"""Source-bound J-CLIMATE projection of one immutable proposal rerun directory."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ConfigDict, StrictFloat, StrictInt, StrictStr, ValidationError, model_validator

from .core import canonical
from .inputs import CATEGORIES, UTCI_CATEGORIES


class _RevisionDesignerResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: StrictStr
    kind: StrictStr
    text: StrictStr


class _RevisionDryRun(BaseModel):
    model_config = ConfigDict(extra='forbid')

    gfa_before_m2: StrictInt | StrictFloat | None
    gfa_after_m2: StrictInt | StrictFloat | None
    affected_building_ids: list[StrictStr]
    solar_access_check: dict[str, Any]
    strategy_report: list[dict[str, Any]] = Field(default_factory=list)


class _RevisionContext(BaseModel):
    model_config = ConfigDict(extra='forbid')

    proposal_id: StrictStr
    card_id: StrictStr
    card_round: StrictInt
    proposal_summary: StrictStr
    operations_text_zh: list[StrictStr]
    operations_text_en: list[StrictStr]
    designer_responses: list[_RevisionDesignerResponse]
    dry_run: _RevisionDryRun
    before_metrics: dict[StrictStr, StrictInt | StrictFloat]

    @model_validator(mode='after')
    def comparison_metrics_only(self):
        from .proposal_comparison import METRICS
        allowed = {metric_id for metric_id, _unit in METRICS.values()}
        unexpected = set(self.before_metrics) - allowed
        if unexpected:
            raise ValueError('before_metrics contains ids outside proposal_comparison.METRICS')
        return self


def assemble_revision(store, project, subject, registry, revision_dir):
    root = Path(revision_dir).resolve()
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('project_id') != project or manifest.get('subject_id') != subject:
        raise ValueError('revision manifest project or subject mismatch')
    expected_subject = 'harbour_grain@draft-r' + str(manifest.get('draft_revision'))
    if subject != expected_subject:
        raise ValueError('revision manifest draft revision mismatch')
    result = {'subject': {'kind': 'scheme', 'ids': [subject]}, 'metrics': {},
              'references': {'evidence_card': {}, 'artifact': {}}, 'data_gaps': [],
              'context': {'proposal_id': manifest.get('proposal_id'), 'draft_id': manifest.get('draft_id'),
                          'draft_revision': manifest['draft_revision'], 'provenance': 'FORMAL_DRAFT',
                          'is_human_decision': False, 'revision_context': None}, 'sources': {}, 'inputs': []}
    hashes = {}
    for item in manifest.get('outputs', []):
        path = Path(item['path'])
        path = path.resolve() if path.is_absolute() else (root / path).resolve()
        if not path.is_relative_to(root):
            raise ValueError('revision output escapes revision directory')
        hashes[path] = item['sha256'].removeprefix('sha256:')

    def read(relative, table=False):
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError('revision source escapes revision directory')
        if not path.is_file():
            return None
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if path in hashes and hashes[path] != sha:
            raise ValueError('revision output hash mismatch: ' + relative)
        result['sources'][str(path)] = sha
        return list(csv.DictReader(raw.decode('utf-8-sig').splitlines())) if table else json.loads(raw)

    def put(ident, value, unit, relative):
        if value is None:
            result['data_gaps'].append('DATA_GAP:' + ident)
            return
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('non-finite revision metric')
        path = str((root / relative).resolve())
        result['metrics'][ident] = {'value': value, 'unit': unit, 'source_path': path,
                                    'source_sha256': result['sources'][path]}

    read('manifest.json')
    revision_context = read('revision-context.json')
    if revision_context is None:
        result['data_gaps'].append('DATA_GAP:revision_context')
    else:
        context_path = (root / 'revision-context.json').resolve()
        if context_path not in hashes:
            raise ValueError('revision-context.json missing from manifest outputs')
        if not isinstance(revision_context, dict):
            raise ValueError('revision-context.json must contain an object')
        try:
            revision_context = _RevisionContext.model_validate(revision_context).model_dump(mode='python')
        except (ValidationError, ValueError) as exc:
            raise ValueError('revision-context.json schema invalid') from exc
        result['context']['revision_context'] = revision_context
    for name, value, unit in [('label', subject, None), ('draft_revision', manifest['draft_revision'], 'count'),
                              ('new_gfa_m2', manifest.get('gfa_after_m2'), 'm²')]:
        put('scheme.harbour.' + name, value, unit, 'manifest.json')
    requested = set(manifest.get('analyses', []))
    if 'E1' in requested:
        relative = 'e1/comparison_table.csv'
        rows = read(relative, table=True)
        if rows is None:
            result['data_gaps'].append('DATA_GAP:e1.*')
        for row in rows or []:
            category = CATEGORIES.get(row.get('開放空間類別'))
            if row.get('紋理方案代碼') != 'harbour_grain' or category is None:
                continue
            for season, zh in [('spring', '春分'), ('summer', '夏至'), ('winter', '冬至')]:
                for name, column, unit in [('mean_h', zh + '平均日照_小時', 'h'),
                                            ('ge2h_pct', zh + '日照大於等於2小時比例_百分比', '%'),
                                            ('area_m2', '代表面積_m2', 'm²')]:
                    raw = row.get(column)
                    put(f'e1.harbour.{category}.{season}.{name}', float(raw) if raw not in (None, '') else None, unit, relative)
        courtyard_relative = 'e1/per_courtyard.json'
        courtyard_rows = read(courtyard_relative)
        if courtyard_rows is None:
            result['data_gaps'].append('DATA_GAP:e1.harbour.courtyard_breakdown')
        elif not isinstance(courtyard_rows, list):
            raise ValueError('revision per_courtyard.json must contain a list')
        else:
            for row in courtyard_rows:
                if row.get('fabric_id') != 'harbour_grain' or not row.get('courtyard_id'):
                    continue
                courtyard_id = str(row['courtyard_id'])
                prefix = f'e1.harbour.{courtyard_id}'
                put(prefix + '.points', row.get('points'), 'count', courtyard_relative)
                put(prefix + '.area_m2', row.get('area_m2'), 'm²', courtyard_relative)
                for season in ('spring', 'summer', 'winter'):
                    put(prefix + f'.{season}.mean_h', row.get(f'{season}_mean'), 'h', courtyard_relative)
                put(prefix + '.winter.ge2h_pct', row.get('winter_ge_2h_pct'), '%', courtyard_relative)
    else:
        result['data_gaps'].extend(['DATA_GAP:e1.*', 'DATA_GAP:e1.harbour.courtyard_breakdown'])
    if 'UTCI' in requested:
        relative = 'utci/utci_stress_hours_comparison.json'
        data = read(relative)
        if data is None:
            result['data_gaps'].append('DATA_GAP:utci.*')
        values = (data or {}).get('fabrics', {}).get('harbour_grain', {})
        for category, row in values.get('stress_table', {}).items():
            for name, key, unit in [('mean_c', 'mean_utci_c', '°C'), ('very_strong_pct', 'very_strong_pct', '%'),
                                   ('strong_plus_pct', 'strong_plus_pct', '%'), ('mean_mrt_c', 'mean_mrt_c', '°C'),
                                   ('mean_svf', 'mean_svf', 'ratio')]:
                put(f'utci.harbour.{UTCI_CATEGORIES.get(category, category)}.{name}', row.get(key), unit, relative)
        if data:
            put('utci.weather.date', data.get('weather', {}).get('date'), 'date', relative)
    else:
        result['data_gaps'].append('DATA_GAP:utci.*')
    if revision_context is not None:
        summary = _revision_context_summary(revision_context, result['metrics'])
        put('context.revision_summary_zh', summary, 'text', 'revision-context.json')
        # Before-values get their own citable ids; the plain metric ids hold this revision's (after) values.
        from .proposal_comparison import METRICS
        units = {metric_id: unit for metric_id, unit in METRICS.values()}
        for metric_id, value in (revision_context.get('before_metrics') or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                put('prev.' + metric_id, value, units.get(metric_id), 'revision-context.json')
    # Unrerun analyses must never borrow measurements from the baseline geometry.
    result['data_gaps'].extend(['DATA_GAP:e2.*', 'DATA_GAP:e3.*', 'DATA_GAP:e4.*', 'DATA_GAP:e5.*'])
    for stance in registry.seed.get('stances', []):
        if 'J-CLIMATE' in stance.get('applies_to', []):
            value = {'zh-TW': stance['text_zh'], 'en': stance['text_en']}
            source = 'designer-stance-seed'
            result['sources'][source] = hashlib.sha256(canonical(registry.seed).encode()).hexdigest()
            result['metrics']['designer.stance.' + stance['key']] = {
                'value': value, 'unit': None, 'source_path': source, 'source_sha256': result['sources'][source]}
    result['data_gaps'] = sorted(set(result['data_gaps']))
    result['metrics'] = dict(sorted(result['metrics'].items()))
    result['inputs'] = [{'metric_id': key, **value} for key, value in result['metrics'].items()]
    return result


def _revision_context_summary(revision_context, metrics):
    from .proposal_comparison import METRICS

    proposal_id = revision_context.get('proposal_id') or '(unknown proposal)'
    operations = revision_context.get('operations_text_zh') or []
    summary = f"此草稿是在提案 {proposal_id} 核准後重算"
    if operations:
        summary += '：' + '；'.join(operations)
    summary += '。'

    labels = {
        'courtyard_winter_mean_h': '中庭冬至平均日照',
        'all_winter_mean_h': '全體冬至平均日照',
        'all_winter_ge2h_pct': '全體冬至日照至少 2 小時比例',
        'street_winter_mean_h': '街道冬至平均日照',
        'utci_very_strong_pct': 'UTCI 非常強烈熱壓力比例',
    }
    comparisons = []
    for name, (metric_id, unit) in METRICS.items():
        before = revision_context.get('before_metrics', {}).get(metric_id)
        current = metrics.get(metric_id, {})
        after = current.get('value') if isinstance(current, dict) else None
        if (not isinstance(before, (int, float)) or isinstance(before, bool)
                or not isinstance(after, (int, float)) or isinstance(after, bool)):
            continue
        places = 3 if unit == 'h' else 2
        before_text = _format_metric_number(before, places)
        after_text = _format_metric_number(after, places)
        unit_text = ' 小時' if unit == 'h' else '%'
        comparisons.append(f"重算前{labels[name]} {before_text}{unit_text}；重算後 {after_text}{unit_text}")
    if comparisons:
        summary += ' '.join(comparisons) + '。'
    else:
        summary += '重算前後沒有可比的指標數值。'

    checks = (((revision_context.get('dry_run') or {}).get('solar_access_check') or {}).get('courtyards') or [])
    for check in checks:
        height = check.get('south_height_after_m')
        north_edge = check.get('h_north_edge_m')
        courtyard_id = check.get('courtyard_id') or '中庭'
        if (isinstance(height, (int, float)) and not isinstance(height, bool)
                and isinstance(north_edge, (int, float)) and not isinstance(north_edge, bool)):
            relation = '高於' if height > north_edge else '不高於'
            if check.get('reaches_north_edge') is True:
                outcome = '已達北緣'
            elif check.get('reaches_north_edge') is False:
                outcome = '未達北緣'
            else:
                outcome = '是否到達北緣未知'
            summary += (f"乾跑日照檢查：{courtyard_id} 重算後南側最高 {height} 公尺，{relation}"
                        f"正午陽光到達北緣所需的 {north_edge} 公尺（{outcome}）。")
        else:
            summary += f'乾跑日照檢查：{courtyard_id} 的高度或北緣需求值缺漏，不能判定是否到達北緣。'
    return summary


def _format_metric_number(value, places):
    rendered = f'{value:.{places}f}'
    if '.' in rendered:
        rendered = rendered.rstrip('0').rstrip('.')
    return rendered
