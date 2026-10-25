"""Read-only judgement projections. No geometry, simulation or aggregate calculation."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

FABRICS = {'harbour_grain': 'harbour', 'closed_block_extension': 'closed',
           'courtyard_islands': 'courtyard', 'landscape_figure': 'landscape'}
MORPH_FAILURE_LABELS = {
    'ROAD_WATERFRONT_COMBINED_BUDGET': '道路與水岸合計面積預算',
    'SOUTH_QUAY_SHARED_ALLEY': '南碼頭共用巷',
    'SOUTH_QUAY_FACADE_CONTINUITY': '南碼頭立面連續性',
    'BUILDING_STREET_EDGE_3M': '建築臨街三公尺界面',
    'SOUTH_QUAY_MAX_GAP': '南碼頭最大立面間隙',
    'BOUNDARY_PARCEL_SEMANTICS': '邊界地塊語意',
    'NO_LARGE_UNBUILT_PLOT': '不留大塊未配置土地',
    'BLOCK_LAND_BUDGET': '街廓用地預算',
    'SERVICE_FUNCTION_FRONTAGE': '服務機能臨街面',
    'NORTHEAST_REGULAR_BLOCKS': '東北區規則街廓',
    'PARK_AREA_BUDGET': '公園面積預算',
    'COURTYARD_ISLAND_ROAD_CLEARANCE': '院落島道路淨距',
    'COURTYARD_ISLAND_GLOBAL_MEMBERSHIP': '院落島整體歸屬',
    'COURTYARD_ISLAND_COUNT_SPACING': '院落島數量與間距',
}
LABELS = {'港埠線性紋理': 'harbour', '圍合街廓延伸': 'closed', '大型院落島': 'courtyard', '地景為圖': 'landscape'}
CATEGORIES = {'全體開放空間': 'all', '街坊公園/綠軸': 'park', '水岸公共帶': 'waterfront',
              '街道路權': 'street', '街廓中庭': 'courtyard', '街廓內其他空地': 'block_other', '設備院與其他空地': 'utility'}
UTCI_CATEGORIES = {'total': 'all', 'parks': 'park', 'roads': 'street', 'courtyards': 'courtyard',
                   'blocks': 'block_other', 'service': 'utility', 'waterfront': 'waterfront'}


def assemble(store, project_id, skill_id, subject_ids, registry, source_catalog=None):
    root = registry.root.resolve()
    supplied = list(subject_ids or [])
    aliases = {**{v: k for k, v in FABRICS.items()}, **{k: k for k in FABRICS}}
    if skill_id != 'J-SITE' and any(i not in aliases for i in supplied):
        raise ValueError('unknown scheme subject')
    if skill_id == 'J-MORPH' and len(supplied) != 1:
        raise ValueError('J-MORPH requires exactly one scheme subject')
    selected = sorted(set(aliases[i] for i in supplied)) if supplied else sorted(FABRICS)
    subject = {'kind': 'site' if skill_id == 'J-SITE' else ('scheme' if len(selected) == 1 else 'scheme_set'),
               'ids': supplied or ([project_id] if skill_id == 'J-SITE' else selected)}
    result: dict[str, Any] = {'subject': subject, 'metrics': {}, 'references': {'evidence_card': {}, 'artifact': {}},
                              'data_gaps': [], 'context': {}, 'sources': {}, 'inputs': []}

    def read(relative, *, table=False, text=False):
        path = root / relative
        if not path.is_file():
            return None
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        result['sources'][relative] = sha
        if text:
            return raw.decode('utf-8-sig')
        if table:
            return list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
        return json.loads(raw)

    def put(ident, value, unit, source, **extra):
        if value is None:
            gap(ident)
            return
        metric = {'value': value, 'unit': unit, 'source_path': source,
                  'source_sha256': result['sources'][source], **extra}
        if ident in result['metrics'] and result['metrics'][ident] != metric:
            raise ValueError('ambiguous persisted metric: ' + ident)
        result['metrics'][ident] = metric

    def gap(ident):
        result['data_gaps'].append('DATA_GAP:' + ident)

    def persisted_source(name, payload):
        source = 'project-state:' + name
        result['sources'][source] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        return source

    def site():
        if store is not None and source_catalog is not None:
            from urban_design.analysis_persistence import get_persisted_site_analysis, get_persisted_syntax_bundle
            bundle, cards, status, _, _ = get_persisted_site_analysis(store, project_id, source_catalog)
            if status == 'VERIFIED_SOURCE_RESULT_ALIGNMENT':
                for card in cards:
                    state = card.get('validation_status', card.get('status', ''))
                    if state not in {'VERIFIED_SOURCE_RESULT_ALIGNMENT', 'SOURCE_ALIGNED_COVERAGE_LIMITED', 'VERIFIED_OBSERVATION'}:
                        continue
                    ident = card.get('card_id', card.get('id'))
                    source = persisted_source(ident, card)
                    result['references']['evidence_card'][ident] = {**card, 'coverage_limited': 'COVERAGE_LIMITED' in state or state == 'VERIFIED_OBSERVATION',
                        'source_path': source, 'source_sha256': result['sources'][source]}
                    put('evidence_card:' + ident, card.get('value', card), card.get('unit'), source)
            if not result['references']['evidence_card']:
                gap('evidence_card.*')
            syntax = get_persisted_syntax_bundle(store, project_id, source_catalog)
            # Preserve the verified bundle rather than calculate new summaries.
            source = persisted_source('syntax-context', syntax)
            found = False
            # Stored statistics are raw NAIN/NACH values, not percentiles.
            # Preserve their mode, radius and exploratory limitations verbatim.
            result['context']['syntax'] = {key: syntax.get(key) for key in
                ('status', 'limitations', 'evidence_level', 'formal_result_eligible')}
            if syntax.get('status') not in {'STALE', 'BLOCKED', 'NOT_COMPUTED'}:
                for layer in syntax.get('layers', []):
                    mode = {'pedestrian': 'ped', 'bicycle': 'bike', 'motor_vehicle': 'car'}.get(layer.get('network_mode'))
                    metric = layer.get('metric_key')
                    radius = layer.get('radius_m')
                    if layer.get('calculation_status') != 'COMPUTED' or not mode or metric not in {'nain', 'nach'} or radius is None:
                        continue
                    radius = str(int(radius)) if float(radius).is_integer() else str(radius)
                    for key, value in (layer.get('statistics') or {}).items():
                        scope = 'site' if layer.get('coverage_scope') == 'study_area_segments' else 'network'
                        put(f'syntax.context.{mode}.{metric}.{radius}.{scope}.{key}', value,
                            'segments' if key == 'count' else layer.get('unit'), source,
                            evidence_level=layer.get('evidence_level'), limitations=layer.get('limitations'),
                            scope=layer.get('coverage_scope', 'unspecified'))
                        found = True
            if not found:
                gap('syntax.context.*')
            # Each requested mode/radius/metric needs its own persisted statistics.
            # Context endpoint segments do not establish site or network aggregates.
            for required_mode in ('ped', 'bike', 'car'):
                for required_radius in (800, 2000, 10000):
                    for required_metric in ('nain', 'nach'):
                        prefix = f'syntax.context.{required_mode}.{required_metric}.{required_radius}.'
                        if not any(ident.startswith(prefix) for ident in result['metrics']):
                            gap(prefix + 'statistics')
            # Neither stored statistics nor raw segments establish percentile summaries.
            gap('syntax.context.*.site_mean_pctl')
            gap('syntax.context.*.top20_segments_in_site')
        else:
            gap('evidence_card.*'); gap('syntax.context.*')
        plan_path = 'artifacts/fab1/run-8/harbour_grain-plan.json'
        plan = read(plan_path)
        for metric, value in {'design_area_m2': (plan or {}).get('context_reference', {}).get('site', {}).get('area_m2'),
                              'land_area_m2': (plan or {}).get('metrics', {}).get('land_area_m2')}.items():
            if plan:
                put('site.' + metric, value, 'm²', plan_path)
            else:
                gap('site.' + metric)
        for metric in ('waterfront_length_m', 'retained_buildings', 'retained_roads'):
            value = (plan or {}).get('metrics', {}).get(metric)
            records_key = {'retained_buildings': 'retained_inputs', 'retained_roads': 'retained_road_inputs'}.get(metric)
            if value is None and records_key and isinstance((plan or {}).get(records_key), list):
                value = len(plan[records_key])
            if value is None:
                gap('site.' + metric)
            else:
                put('site.' + metric, value, 'm' if metric.endswith('_m') else 'count', plan_path)
        gap('site.retained_building_area_m2')
        gap('site.retained_road_area_m2')
        if plan:
            # Per-item areas and IDs remain inspectable; no summed areas or inferred counts.
            put('site.retained_building_records', plan.get('retained_inputs'), None, plan_path)
            put('site.retained_road_records', plan.get('retained_road_inputs'), None, plan_path)
            put('site.retained_gfa_upper_m2', plan.get('metrics', {}).get('retained_gfa_upper_m2'), 'm²', plan_path)
        context_path = 'artifacts/ctx1-context-morphology/context-summary-zh.md'
        context = read(context_path, text=True)
        if context:
            put('context.osm.summary', context, None, context_path)
        else:
            gap('context.osm.summary')
        problem_path = 'artifacts/w6-problem-definition/problem-statements.json'
        problems = read(problem_path)
        if problems:
            for item in problems.get('statements', []):
                ident = item.get('problem_id', item.get('id'))
                statement = item.get('statement', item.get('statement_zh', item.get('evidence_summary_zh')))
                if ident and statement:
                    put('problem.' + ident + '.statement', statement, None, problem_path)
        if not any(i.startswith('problem.') for i in result['metrics']):
            gap('problem.*.statement')

    def schemes():
        for fabric in selected:
            short = FABRICS[fabric]
            path = f'artifacts/fab1/run-8/{fabric}-plan.json'
            plan = read(path)
            metrics = (plan or {}).get('metrics', {})
            keys = {'fsi': 'fsi', 'gsi': 'gsi', 'osr': 'OSR', 'l': 'L', 'new_gfa_m2': 'new_gfa_m2',
                    'building_count': 'new_building_count', 'height_max_m': 'height_max_m', 'new_gfa_pct_of_cap': 'new_gfa_pct_of_cap'}
            for name, key in keys.items():
                if plan:
                    put(f'scheme.{short}.{name}', metrics.get(key), 'm²' if name.endswith('_m2') else ('m' if name.endswith('_m') else ('%' if name.endswith('cap') else 'count' if name == 'building_count' else 'ratio')), path)
                else:
                    gap(f'scheme.{short}.{name}')
            label = next((label for label, value in LABELS.items() if value == short), fabric)
            if plan:
                put(f'scheme.{short}.label', label, None, path)
            if skill_id == 'J-CLIMATE':
                continue
            if plan:
                put(f'check.{short}.failures', plan.get('validation', {}).get('failure_ids'), None, path)
                put(f'intent.{short}.fabric_concept', plan.get('fabric_dictionary'), None, path)
            statement_path = f'artifacts/fab1/run-8/ai-explanations/{fabric}-design-statement-zh.md'
            statement = read(statement_path, text=True)
            if statement:
                put(f'intent.{short}.summary', statement[:600], None, statement_path)
            else:
                gap(f'intent.{short}.summary')
        # Only explicit persisted decisions with an exact known subject count.
        # Ambiguous/multiple accepted subjects stay a gap; the viewer default is not a decision.
        decisions = store.list_current('HumanDecision', project_id=project_id) if store is not None else []
        decision_aliases = {**aliases, 'formal-fabric-harbour-grain-88445febe1b6': 'harbour_grain'}
        accepted = [record for record in decisions if record.payload.get('action') == 'Accept'
                    and record.payload.get('status') == 'accepted' and record.payload.get('target_id') in decision_aliases]
        targets = {decision_aliases[record.payload['target_id']] for record in accepted}
        if len(targets) == 1:
            record = sorted(accepted, key=lambda item: (item.payload.get('timestamp', ''), item.entity_id))[-1]
            source = persisted_source(record.entity_id, record.payload)
            chosen = next(iter(targets))
            put('decision.selected_scheme', chosen, None, source)
            for fabric in selected:
                put(f'scheme.{FABRICS[fabric]}.selected', fabric == chosen, None, source)
        else:
            gap('decision.selected_scheme')
            for fabric in selected:
                gap(f'scheme.{FABRICS[fabric]}.selected')
        if skill_id == 'J-CLIMATE':
            return
        if store is not None:
            contests = store.list_current('ContestEvent', project_id=project_id)
            for index, record in enumerate(sorted(contests, key=lambda item: (item.payload.get('timestamp', ''), item.entity_id))):
                source = persisted_source(record.entity_id, record.payload)
                put(f'contest.{index}.text', record.payload.get('user_reason'), None, source)
        gap('portfolio.q2.*')
        syntax_path = 'artifacts/net2/round-7/v3-export/net2-assessment.json'
        syntax = read(syntax_path)
        found = set()
        for report in (syntax or {}).get('reports', []):
            assessment = report.get('net2_assessment', {})
            fabric = assessment.get('fabric_id')
            if fabric not in selected:
                continue
            mode = {'pedestrian': 'ped', 'bicycle': 'bike', 'motor_vehicle': 'car'}.get(assessment.get('mode'))
            if not mode:
                continue
            prefix = f'syntax.{FABRICS[fabric]}.{mode}.'
            for check in assessment.get('checks', []):
                suffix = {'primary_street': 'main_street_pctl', 'waterfront_path': 'waterfront_pctl'}.get(check.get('target'))
                if suffix:
                    put(prefix + suffix, check.get('value'), '%', syntax_path)
                    found.add(prefix + suffix)
            for intent in assessment.get('descriptive_intents', []):
                suffix = {'primary_street': 'main_street_pctl', 'waterfront_path': 'waterfront_pctl'}.get(intent.get('intent_en'))
                ident = prefix + suffix if suffix else None
                if ident and ident not in found and intent.get('percentile') is not None:
                    put(ident, intent['percentile'], '%', syntax_path, scope='descriptive_intent',
                        limitations=assessment.get('method'), formal_result_eligible=assessment.get('formal_result_eligible'))
                    found.add(ident)
            for key, baseline in assessment.get('baselines', {}).items():
                put(f'syntax.baseline.{mode}.{key}_pctl', baseline.get('percentile'), '%', syntax_path)
        summary_path = 'artifacts/net2/round-7/syntax/syntax-summary.json'
        summary = read(summary_path)
        for row in (summary or {}).get('results', []):
            fabric = row.get('fabric_id')
            mode = {'pedestrian': 'ped', 'bicycle': 'bike', 'motor_vehicle': 'car'}.get(row.get('mode'))
            if fabric not in selected or not mode or row.get('status') != 'COMPUTED':
                continue
            # These are persisted raw metrics/rankings, never inferred percentiles.
            for phase in ('before', 'after'):
                put(f'syntax.{FABRICS[fabric]}.{mode}.{phase}_metrics',
                    row.get(phase, {}).get('metrics'), None, summary_path,
                    evidence_level=row.get('evidence_level'), limitations=row.get('limitations'))
            put(f'syntax.{FABRICS[fabric]}.{mode}.new_street_ranking',
                row.get('new_street_ranking'), None, summary_path,
                method=row.get('new_street_ranking_method'), truncated=row.get('new_street_ranking_truncated'))
        finding_path = 'artifacts/net2/round-7/v3-recompute-finding-zh.md'
        finding = read(finding_path, text=True)
        if finding:
            for line in finding.splitlines():
                cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
                if len(cells) != 4 or cells[0] not in LABELS:
                    continue
                short = LABELS[cells[0]]
                if short not in {FABRICS[fabric] for fabric in selected}:
                    continue
                try:
                    value = float(cells[2])
                except ValueError:
                    continue
                ident = f'syntax.{short}.ped.new_segments_pctl'
                put(ident, value, '%', finding_path,
                    scope='new primary-street segments excluding existing Keileweg',
                    limitations='Source attribution coverage is 60% for pedestrian main streets; persisted Commander report, not recomputed.')
                found.add(ident)
        for fabric in selected:
            for mode in ('ped', 'bike', 'car'):
                for suffix in ('main_street_pctl', 'waterfront_pctl', 'new_segments_pctl'):
                    ident = f'syntax.{FABRICS[fabric]}.{mode}.{suffix}'
                    if ident not in found:
                        gap(ident)

    def morphology():
        from .proposals import courtyard_relationships, _building_height
        from statistics import median
        import math

        for fabric in selected:
            short = FABRICS[fabric]
            path = f'artifacts/fab1/run-8/{fabric}-plan.json'
            plan = read(path)
            if plan is None:
                gap(f'morph.{short}.*')
                continue
            prefix = f'morph.{short}.'
            for name in ('block_long_m', 'block_short_m', 'street_width_m', 'building_depth_m',
                         'target_gfa_m2', 'seam_width_m', 'orientation_deg'):
                value = plan.get('parameters', {}).get(name)
                if name == 'orientation_deg' and value is None:
                    value = plan.get(name)
                put(prefix + 'param.' + name, value, 'm²' if name.endswith('m2') else '°' if name.endswith('deg') else 'm', path)

            dictionary_path = f'knowledge/v2/domains/MOR/fabrics/fabric.{fabric}.json'
            dictionary = read(dictionary_path)
            if dictionary is None:
                gap(prefix + 'bound.*')

            def bounds(node, trail=''):
                if isinstance(node, list):
                    for index, child in enumerate(node):
                        bounds(child, trail + '.' + str(index))
                    return
                if not isinstance(node, dict):
                    return
                if 'minimum' in node or 'maximum' in node:
                    # Scalars the model can cite exactly; the precedent basis is text under basis.<fabric>.
                    for side in ('minimum', 'maximum'):
                        if isinstance(node.get(side), (int, float)) and not isinstance(node.get(side), bool):
                            put(prefix + 'bound.' + trail + '.' + side, node[side], node.get('unit'), dictionary_path)
                    basis = node.get('basis') or {}
                    if basis:
                        put('basis.' + prefix.split('.', 1)[1] + trail, (str(basis.get('status') or '') + '：' + str(basis.get('note_zh') or '')).strip('：'), None, dictionary_path)
                for key, child in node.items():
                    if isinstance(child, (dict, list)):
                        bounds(child, (trail + '.' + key).strip('.'))
            bounds(dictionary or {})
            for failure in plan.get('validation', {}).get('failure_ids', []):
                detail = plan.get('validation', {}).get('checks', {}).get(failure, {})
                label = MORPH_FAILURE_LABELS.get(failure) or detail.get('name_zh') or detail.get('description_zh')
                descriptions = sorted({item['reason_zh'] for item in detail.get('failure_locations', []) if isinstance(item, dict) and item.get('reason_zh')})
                if not label and descriptions:
                    label = '；'.join(descriptions)
                put(prefix + 'check.' + failure, label or failure, None, path, label_zh=label)
            buildings = [b for b in plan.get('buildings', []) if not b.get('properties', b).get('retained', False)]
            heights = sorted(h for b in buildings if (h := _building_height(b)) is not None)
            if heights and len(heights) == len(buildings):
                def percentile(q):
                    index = (len(heights) - 1) * q
                    lo = math.floor(index); hi = math.ceil(index)
                    return heights[lo] + (heights[hi] - heights[lo]) * (index - lo)
                for name, value in [('p10', percentile(.1)), ('median', median(heights)), ('p90', percentile(.9)),
                                    ('share_at_cap', sum(18 <= h <= 20 for h in heights) / len(heights))]:
                    put(prefix + 'height.' + name, value, 'ratio' if name == 'share_at_cap' else 'm', path,
                        method='linear quantile; share at project 18–20 m cap band')
            else:
                gap(prefix + 'height.*')
            courts = plan.get('courtyards')
            if not courts:
                gap(prefix + 'courtyard.*')
            else:
                for court in courtyard_relationships(courts, buildings):
                    ident = str(court['courtyard_id'])
                    values = {**court, **court.get('solar_geometry', {})}
                    for name in ('clear_width_m', 'area_m2', 'depth_along_sun_m', 'h_north_edge_m',
                                 'south_edge_height_max_m', 'feasible_within_catalogue'):
                        put(prefix + f'courtyard.{ident}.' + name, values.get(name),
                            'm²' if name == 'area_m2' else None if name == 'feasible_within_catalogue' else 'm', path,
                            method='R-PROPOSE courtyard_relationships; winter solstice noon 14.66°')
            statement_path = f'artifacts/fab1/run-8/ai-explanations/{fabric}-design-statement-zh.md'
            statement = read(statement_path, text=True)
            if statement:
                put(prefix + 'statement', statement[:1200], None, statement_path)
            else:
                gap(prefix + 'statement')

    def climate():
        e1_path = 'artifacts/w8/e1-fabric/comparison_table.csv'
        rows = read(e1_path, table=True)
        if rows is None:
            gap('e1.*')
        for row in rows or []:
            fabric, category = row.get('紋理方案代碼'), CATEGORIES.get(row.get('開放空間類別'))
            if fabric not in selected or category is None:
                continue
            for season, zh in [('spring', '春分'), ('summer', '夏至'), ('winter', '冬至')]:
                for name, column, unit in [('mean_h', zh + '平均日照_小時', 'h'), ('ge2h_pct', zh + '日照大於等於2小時比例_百分比', '%'), ('area_m2', '代表面積_m2', 'm²')]:
                    put(f'e1.{FABRICS[fabric]}.{category}.{season}.{name}', float(row[column]), unit, e1_path)
        utci_path = 'artifacts/w8/utci/utci_stress_hours_comparison.json'
        utci = read(utci_path)
        if utci is None:
            gap('utci.*')
        for fabric, data in (utci or {}).get('fabrics', {}).items():
            if fabric not in selected:
                continue
            for category, values in data.get('stress_table', {}).items():
                for name, source_name, unit in [('mean_c', 'mean_utci_c', '°C'), ('very_strong_pct', 'very_strong_pct', '%'), ('strong_plus_pct', 'strong_plus_pct', '%'), ('mean_mrt_c', 'mean_mrt_c', '°C'), ('mean_svf', 'mean_svf', 'ratio')]:
                    put(f'utci.{FABRICS[fabric]}.{UTCI_CATEGORIES.get(category, category)}.{name}', values.get(source_name), unit, utci_path)
        if utci:
            put('utci.weather.date', utci.get('weather', {}).get('date'), 'date', utci_path)
        e2_path = 'artifacts/w8/e2-formal/harbour-vs-mixed-result.json'
        e2 = read(e2_path)
        if e2 is None:
            gap('e2.harbour_vs_mixed.*')
        for method, name in [('honeybee_radiance', 'hb'), ('ladybug_radiance', 'lb')]:
            values = (e2 or {}).get('comparisons', {}).get(method, {}).get('0', {})
            for key, field, unit in [('base', 'baseline_kwh_m2', 'kWh/m²'), ('variant', 'modified_kwh_m2', 'kWh/m²'), ('pct', 'percent_change', '%'), ('delta', 'delta_kwh_m2', 'kWh/m²')]:
                ident = f'e2.harbour_vs_mixed.{name}_0h_kwh_m2.{key}'
                if e2:
                    put(ident, values.get(field), unit, e2_path)
                else:
                    gap(ident)
        energy_path = 'artifacts/w8/e3e4-final/e3e4_results_zh.csv'
        energy = read(energy_path, table=True)
        if energy is None:
            gap('e3.*'); gap('e4.harbour.*')
        for row in energy or []:
            short = LABELS.get(row.get('方案'))
            if short not in {FABRICS[i] for i in selected}:
                continue
            mass = row.get('構造') == 'CZ5_Mass'
            ac = row.get('冷氣') == '開'
            if mass and ac:
                for name, column, unit in [('eui_kwh_m2', 'EUI_kWh_m2年', 'kWh/m²/year'), ('heating_kwh', '暖氣需求_kWh_熱', 'kWh'), ('cooling_kwh', '冷氣需求_kWh_熱', 'kWh'), ('peak_heating_kw', '尖峰暖氣_kW_熱', 'kW'), ('peak_cooling_kw', '尖峰冷氣_kW_熱', 'kW')]:
                    put(f'e3.{short}.{name}', float(row[column]), unit, energy_path, scenario='mass, cooling on')
            if short == 'harbour':
                construction = 'mass' if mass else 'light'
                for name, column, unit in [('overheat_h', '夏季過熱時數_樓地板加權', 'h')] if not ac else [('winter_heating_kwh', '冬季暖氣需求_kWh_熱', 'kWh'), ('peak_cooling_kw', '尖峰冷氣_kW_熱', 'kW')]:
                    put(f'e4.harbour.{construction}.{name}', float(row[column]), unit, energy_path, scenario='cooling on' if ac else 'cooling off')
        wind_path = 'artifacts/w8/e5-cfd/results_table.json'
        wind = read(wind_path) if 'harbour_grain' in selected else None
        if 'harbour_grain' in selected:
            for direction in ('SW', 'W', 'S', 'NW'):
                for name, key, unit in [('freq_pct', 'frequency_pct', '%'), ('mean_ratio', 'mean_wind_ratio', 'ratio'), ('max_ratio', 'max_wind_ratio', 'ratio'), ('gt12_area_m2', 'high_wind_ratio_area_m2', 'm²')]:
                    ident = f'e5.harbour.{direction}.{name}'
                    if wind:
                        put(ident, wind.get(direction, {}).get(key), unit, wind_path)
                    else:
                        gap(ident)
        for family, folder, fallback in [('e1', 'e1-fabric', 'comparison_table.md'), ('utci', 'utci', 'utci_stress_hours_comparison.md'), ('e2', 'e2-formal', None), ('e3', 'e3e4-final', 'e3e4_results_zh.md'), ('e5', 'e5-cfd', None)]:
            if family == 'e2' and e2 and e2.get('limitations'):
                put('limit.e2', e2['limitations'], None, e2_path)
                continue
            for filename in ('README_zh.md', 'README.md', 'REPORT.md', fallback):
                if filename is None:
                    continue
                relative = f'artifacts/w8/{folder}/{filename}'
                content = read(relative, text=True)
                if content:
                    put('limit.' + family, content, None, relative)
                    break
            else:
                gap('limit.' + family)

    if skill_id == 'J-SITE':
        site()
    else:
        schemes()
        if skill_id == 'J-MORPH':
            morphology()
        else:
            climate()
        if skill_id == 'J-COMPARE':
            # Climate summaries only: retain the exact fields specified by J-COMPARE.
            result['metrics'] = {key: value for key, value in result['metrics'].items() if (
                not key.startswith(('e1.', 'utci.', 'e3.', 'e4.', 'e5.'))
                or (key.startswith('e1.') and any(key.endswith('.' + cat + '.winter.mean_h') for cat in ('all', 'street', 'courtyard')))
                or (key.startswith('utci.') and key.endswith('.all.very_strong_pct'))
                or (key.startswith('e3.') and key.endswith('.eui_kwh_m2')))}
    seed_path = 'knowledge/judgement/designer-stance-seed.json'
    seed = read(seed_path)
    for stance in (seed or {}).get('stances', []):
        if skill_id in stance.get('applies_to', []) or (skill_id == 'J-MORPH' and stance.get('key') in {'courtyard_role', 'season_priority'}):
            put('designer.stance.' + stance['key'], {'zh-TW': stance['text_zh'], 'en': stance['text_en']}, None, seed_path)
    if skill_id == 'J-MORPH':
        for ident in registry.specs.get(skill_id, {}).get('missing_knowledge_ids', []):
            gap('ku:' + ident)
    result['data_gaps'] = sorted(set(result['data_gaps']))
    result['metrics'] = dict(sorted(result['metrics'].items()))
    result['inputs'] = [{'metric_id': ident, **value} for ident, value in result['metrics'].items()]
    return result


def compact_projection(bundle: dict[str, Any], skill_id: str) -> dict[str, Any]:
    """Bounded model view; full provenance and exact persisted inputs stay in bundle.

    No measurements are calculated here. Structured per-object records/rankings are
    deliberately omitted: their summaries must come from persisted measurements.
    """
    def text(value: Any, limit: int) -> str:
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        return value[:limit]

    metrics = {}
    excluded = ('.retained_building_records', '.retained_road_records',
                '.new_street_ranking')
    for ident, metric in bundle.get('metrics', {}).items():
        if ident.endswith(excluded):
            continue
        value = metric.get('value')
        if ident.startswith('evidence_card:'):
            # Cards have their own compact representation below.
            if isinstance(value, (dict, list)):
                continue
        limit = (1200 if ident.startswith('morph.') and ident.endswith('.statement') else
                 600 if ident.startswith('intent.') else
                 400 if ident.startswith(('context.', 'problem.')) else
                 160 if ident.startswith('check.') else 400)
        if isinstance(value, str):
            value = text(value, limit)
        elif isinstance(value, (dict, list)):
            if ident.endswith('_metrics'):
                # Existing aggregate metric objects are small; never keep segments.
                value = {key: item for key, item in value.items()
                         if isinstance(item, (int, float, bool)) or item is None} if isinstance(value, dict) else {}
            elif ident.startswith('designer.stance.') and isinstance(value, dict):
                value = {key: text(item, 400) for key, item in value.items() if key in {'zh-TW', 'en'}}
            else:
                value = text(value, limit)
        metrics[ident] = {'value': value, 'unit': metric.get('unit')}
    cards = {}
    for ident, card in bundle.get('references', {}).get('evidence_card', {}).items():
        value = card.get('value')
        if isinstance(value, (dict, list)):
            value = text(value, 160)
        cards[ident] = {'id': ident, 'title': text(card.get('title', card.get('claim', '')), 160),
                        'value': value, 'unit': card.get('unit'),
                        'status': card.get('validation_status', card.get('status')),
                        'limitations': text(card.get('limitations', 'Coverage limited' if card.get('coverage_limited') else ''), 160)}
    return {'subject': bundle.get('subject'), 'metrics': metrics,
            'references': {'evidence_card': cards},
            'context': bundle.get('context', {}), 'data_gaps': bundle.get('data_gaps', [])}


def assemble_morph_inputs(fabric_id, *, registry=None, store=None, project_id='morphology', source_catalog=None):
    """Read one persisted fabric with the shared deterministic solar screen."""
    if registry is None:
        from .core import Registry
        registry = Registry()
    return assemble(store, project_id, 'J-MORPH', [fabric_id], registry, source_catalog)
