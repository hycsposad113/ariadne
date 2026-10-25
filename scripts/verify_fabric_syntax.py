"""核對十二組 PST 結果、來源與逐路憑據，產生繁體中文摘要。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from shapely.geometry import shape
from urban_design import scenario_syntax as ss
from urban_design.fabric_syntax import proposal_roads, compact_result
from urban_design.generation.formal_multimodal import unlink_points
from urban_design.fabric_plans_api import FABRICS
from urban_design.syntax_engines.pst_adapter import verify_runtime
from compute_fabric_syntax import receipt, write

MODE_ZH = {'pedestrian': '步行', 'bicycle': '自行車', 'motor_vehicle': '汽車'}


def verify(summary_path: Path) -> tuple[dict, str]:
    summary = json.loads(summary_path.read_text())
    expected_ids = {(fabric, mode) for fabric in FABRICS for mode in ss.MODES}
    rows = summary['results']
    if (summary['status'] != 'COMPUTED' or summary['computed_count'] != 12
            or summary['expected_count'] != 12 or len(rows) != 12
            or {(r['fabric_id'], r['mode']) for r in rows} != expected_ids):
        raise ValueError('十二組計算尚未完整，不能產生通過報告')
    verify_runtime(ss.DEFAULT_PST_MANIFEST)
    extracts = {mode: ss.verified_extract(mode) for mode in ss.MODES}
    external = {mode: value[0]['network']['features'] for mode, value in extracts.items()}
    checks = []
    markdown = ['# INT1b 空間語法結果', '',
                '十二組均為探索性計算，不代表方案已接受。平均 NAIN 採基地內分段不加權平均；'
                '高整合段長度採固定基準網路 q60 門檻，僅計基地內長度。'
                '汽車沿用 PST walking-radius 契約，不能解讀為交通量或行車時間。', '',
                '| 方案 | 運具 | 半徑（m） | 高整合段前→後（m） | 平均 NAIN 前→後 | ΔNAIN | 新街道數 |',
                '|---|---|---:|---:|---:|---:|---:|']
    for row in rows:
        if row['status'] != 'COMPUTED' or row['formal_result_eligible'] is not False:
            raise ValueError('結果狀態或探索性資格不符')
        records = [row['source_receipts']['plan'], row['complete_intermediate'], row['retained_road_receipts']]
        for record in records:
            if receipt(Path(record['path'])) != record:
                raise ValueError('結果或來源雜湊已變動：' + record['path'])
        mode = row['mode']
        docs, extract_receipt = extracts[mode]
        if row['source_receipts']['extract'] != extract_receipt:
            raise ValueError('已驗證 extract 或 PST 執行環境憑據已變動')
        plan = json.loads(Path(row['source_receipts']['plan']['path']).read_text())
        site = shape(plan['site'])
        road_receipts = []
        roads = proposal_roads(plan, external, mode=mode, receipts=road_receipts)
        if road_receipts != json.loads(Path(row['retained_road_receipts']['path']).read_text()):
            raise ValueError('逐路憑據與目前來源比對不符')
        full = json.loads(Path(row['complete_intermediate']['path']).read_text())
        expected = {
            'road_input_sha256': ss.digest([r.model_dump() for r in roads]),
            'network_input_sha256': ss.digest(external[mode]),
            'unlinks_sha256': ss.digest(unlink_points(docs['unlinks'])),
            'site_sha256': ss.digest(site.__geo_interface__),
            'radius_m': ss.MODES[mode][1],
            'parameters': ss.MergeParameters(snap_tolerance_m=0).model_dump(),
            'implementation_sha256': ss.IMPLEMENTATION_SHA256,
            'formula_version': 'pstalgo-3.3.1-walking-radius-v1',
        }
        if any(full.get(key) != value for key, value in expected.items()):
            raise ValueError('完整結果的輸入契約不符')
        compact = compact_result(full, site, roads)
        if any(row.get(key) != value for key, value in compact.items()):
            raise ValueError('交付摘要與完整結果不符')
        checks.append({'fabric_id': row['fabric_id'], 'mode': mode,
                       'status': 'VERIFIED', 'full_result': row['complete_intermediate'],
                       'retained_road_count': len(road_receipts)})
        before, after = (row[phase]['metrics'] for phase in ('before', 'after'))
        markdown.append(f"| {FABRICS[row['fabric_id']]} | {MODE_ZH[mode]} | {row['radius_m']:.0f} | "
                        f"{before['high_integration_length_m']:.3f} → {after['high_integration_length_m']:.3f} | "
                        f"{before['mean_integration_nain']:.6f} → {after['mean_integration_nain']:.6f} | "
                        f"{row['delta_mean_integration_nain']:+.6f} | {row['new_street_ranking_count']} |")
    for row in rows:
        markdown.extend(['', f"## {FABRICS[row['fabric_id']]}／{MODE_ZH[row['mode']]}：全部新街道排名", '',
                         '| 排名 | 道路 ID | NAIN | NACH | 基地內長度（m） |', '|---:|---|---:|---:|---:|'])
        for index, road in enumerate(row['new_street_ranking'], 1):
            markdown.append(f"| {index} | {road['road_id']} | {road['nain']:.6f} | {road['nach']:.6f} | {road['inside_length_m']:.3f} |")
    return {'status': 'VERIFIED', 'verified_count': len(checks), 'summary': receipt(summary_path),
            'results': checks, 'formal_result_eligible': False}, '\n'.join(markdown) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', type=Path, default=Path('artifacts/int1b/syntax/syntax-summary.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report, markdown = verify(args.summary)
    write(args.output / 'syntax-verification-zh.json', report)
    (args.output / 'syntax-results-zh.md').write_text(markdown)
    print('十二組結果、來源、逐路憑據與摘要一致；瀏覽器驗證仍待指揮官執行。')
