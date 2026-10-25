from __future__ import annotations
import hashlib
import json
import re
import math
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP, DecimalException
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
STAGES = {'J-SITE': 'site', 'J-COMPARE': 'compare', 'J-CLIMATE': 'climate', 'J-MORPH': 'morphology'}

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

class Registry:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        folder = self.root / 'knowledge/judgement'
        self.schema = json.loads((folder / 'judgement-card.schema.json').read_text())
        # Runtime extension; the Commander-owned source schema stays immutable.
        if 'J-MORPH' not in self.schema['properties']['skill_id']['enum']:
            self.schema['properties']['skill_id']['enum'].append('J-MORPH')
        self.specs = {}
        self.seed = json.loads((folder / 'designer-stance-seed.json').read_text())
        for skill, stage in STAGES.items():
            path = folder / (skill + '-zh.md')
            text = path.read_text()
            ids = sorted(set(re.findall(r'KU-[A-Z]{3}-\d{3}', text)))
            units = []
            missing_ids = []
            hashes = {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()}
            for ident in ids:
                p = self.root / 'knowledge/v2/domains' / ident.split('-')[1] / 'units' / (ident + '.json')
                if not p.is_file() and skill == 'J-MORPH':
                    missing_ids.append(ident)
                    continue
                unit = json.loads(p.read_text())
                units.append({'id': ident, **{key: unit.get(key) for key in ('title_zh', 'title_en', 'summary_zh', 'design_implications_zh', 'not_applicable_when_zh')}})
                hashes[str(p.relative_to(self.root))] = hashlib.sha256(p.read_bytes()).hexdigest()
            required_section=text.split('## 必讀知識單元',1)[1].split('## 判斷框架',1)[0]
            required_text, _, optional_text = required_section.partition('可選：')
            required_ids=sorted(set(re.findall(r'KU-[A-Z]{3}-\d{3}',required_text)))
            optional_ids=sorted(set(re.findall(r'KU-[A-Z]{3}-\d{3}',optional_text)))
            self.specs[skill] = dict(required_knowledge_ids=required_ids,optional_knowledge_ids=optional_ids,skill_id=skill, stage=stage, version=re.search(r'v(1\.\d+\.\d+)', text).group(1), text=text,
                                     knowledge=units, knowledge_ids=[ident for ident in ids if ident not in missing_ids], missing_knowledge_ids=missing_ids, hashes=hashes,
                                     lenses=re.findall(r'\*\*(L\d+)', text))
        self.common=(folder/'README-zh.md').read_text()
        self.version = digest({'specs': self.specs, 'schema': self.schema, 'seed': self.seed, 'common':self.common})

def narrative(card):
    yield from (o['text'] for o in card['observations'])
    yield card['judgement']['headline']
    for reason in card['reasoning']:
        yield reason['text']
        yield reason['lens']
    yield card['confidence']['why']
    for r in card['revision_directions']:
        yield from (r[k] for k in ('action', 'target', 'expected_effect', 'trade_off'))
    for key in ('counterpoints', 'limitations', 'questions_for_designer'):
        yield from card[key]

NUMBER = re.compile(r'(?<![A-Za-z_])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?')

TEXT_PREFIXES = ('designer.stance.', 'context.', 'problem.', 'intent.', 'check.', 'limit.', 'basis.')
UNIT_GROUPS = [ {'h','小時','hours'}, {'%','百分比'}, {'m²','m2','平方公尺'},
                {'kWh/m²·年','kWh/m2/yr','kWh/m²/year'}, {'°C','℃'}, {'kW','千瓦'} ]

def unit_equal(written, source):
    return written == source or any(written in group and source in group for group in UNIT_GROUPS)

def rounded_equal(written, source):
    """Compare using the expressed decimal precision, never a relative tolerance."""
    try:
        value, original = Decimal(str(written)), Decimal(str(source))
        if not value.is_finite() or not original.is_finite():
            return False
        exponent = value.as_tuple().exponent
        return value == original or (exponent <= 0 and original.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP) == value)
    except (DecimalException, ValueError, TypeError):
        return False

def validate(card, bundle, spec, schema):
    errors = [('/' + '/'.join(map(str, e.absolute_path)) + ': ' + e.message) for e in Draft202012Validator(schema).iter_errors(card)]
    if errors:
        return errors
    if card['skill_id'] != spec['skill_id'] or card['skill_version'] != spec['version'] or card['stage'] != spec['stage'] or card['subject'] != bundle['subject']:
        errors.append('SKILL_OR_SUBJECT_MISMATCH')
    forbidden = ['已核准','批准','正式接受','決策成立','最佳方案','冠軍','HumanDecision','Jack','簽署']  # names / governance boilerplate leak in from CLI-level instructions
    forbidden += {'site':['人流量','實測人流','合法','權屬確認'], 'compare':['勝出','排名第一即採用','人流量','實測人流'], 'morphology':['已通過檢核','合規','最佳形態'], 'climate':['認證','合格','符合法規','實測','風安全','Lawson 判定']}[spec['stage']]
    values = [Decimal(str(m['value'])) for m in bundle['metrics'].values() if isinstance(m['value'], (int,float)) and not isinstance(m['value'],bool)]
    # Numbers that appear verbatim in the assembled input are sourced too: text-type inputs
    # (context/problem/limit/evidence wording) and metric ids (e.g. the 800 m radius in a syntax id).
    # A number must still be found somewhere in the input; nothing outside it is accepted.
    sourced_text = [ident for ident in bundle['metrics']]
    sourced_text += [m['value'] for m in bundle['metrics'].values() if isinstance(m.get('value'), str)]
    if spec['stage'] == 'morphology':
        sourced_text += [json.dumps(m['value'], ensure_ascii=False) for m in bundle['metrics'].values() if isinstance(m.get('value'), (dict, list))]
    sourced_text += [str(m.get('limitations')) for m in bundle['metrics'].values() if m.get('limitations')]
    for card_ref in (bundle.get('references') or {}).values():
        sourced_text += [json.dumps(item, ensure_ascii=False, default=str) for item in card_ref.values()]
    for match in NUMBER.finditer(' '.join(map(str, sourced_text))):
        token = match.group(0).replace(',', '')  # same thousands-separator handling as the card side
        try:
            values.append(Decimal(token))
        except Exception:
            pass
    extra_text=[str(ref[key]) for observation in card['observations'] for ref in observation['refs'] for key in ('value','unit') if isinstance(ref.get(key),str) and not (ref['kind']=='metric' and ref['id'].startswith(TEXT_PREFIXES))]
    for text in [*narrative(card),*extra_text]:
        if not set(re.findall(r'KU-[A-Z]{3}-\d{3}',text)) <= set(spec['knowledge_ids']):
            errors.append('UNKNOWN_KNOWLEDGE_REFERENCE')
        english_forbidden = r'\b(?:best scheme|overall winner|champion|approved|formally accepted)\b'
        if spec['stage'] == 'climate':
            english_forbidden += r'|\b(?:certified|certification|code compliant|wind safety|Lawson determination|measured)\b'
        if any(term in text for term in forbidden) or re.search(english_forbidden, text, re.I) or re.search(r'https?://|doi:', text, re.I):
            errors.append('FORBIDDEN_CLAIM_OR_EXTERNAL_REFERENCE')
        if spec['stage'] in ('site','compare'):
            for sentence in re.split(r'[。！？!?;；\n]',text):
                if any(term in sentence for term in ('人流','行人量')) and not any(term in sentence for term in ('潛力','不是實測')):
                    errors.append('SYNTAX_FLOW_CONFLATION')
        # Explicit source identifiers are structural references, not numeric claims.
        clean=text
        identifiers=[*bundle['metrics'],*spec['knowledge_ids'],*[ident for refs in bundle['references'].values() for ident in refs]]
        for ident in sorted(identifiers,key=len,reverse=True):
            clean=re.sub(r'(?<![A-Za-z0-9_.-])'+re.escape(ident)+r'(?![A-Za-z0-9_.-])','',clean)
        clean=re.sub(r'\b(?:E[1-5]|L[1-6])\b','',clean)
        for metric in bundle['metrics'].values():
            if isinstance(metric['value'],str):
                for date in re.findall(r'\b\d{4}-\d{2}-\d{2}\b',metric['value']):
                    clean=clean.replace(date,'')
        for match in NUMBER.finditer(clean):
            token=match.group(0)
            try:
                value = Decimal(token.replace(',',''))
            except DecimalException:
                errors.append('UNSOURCED_NUMBER:' + token)
                continue
            if clean[match.end():].lstrip().startswith('%') and any(m.get('unit') in {'ratio','fraction'} and isinstance(m['value'],(int,float)) and rounded_equal(token.replace(',', ''), Decimal(str(m['value']))*100) for m in bundle['metrics'].values()):
                continue
            if not any(rounded_equal(token.replace(',', ''), v) for v in values):
                errors.append('UNSOURCED_NUMBER:' + token)
    for observation in card['observations']:
        for ref in observation['refs']:
            known = bundle['metrics'] if ref['kind'] == 'metric' else bundle['references'].get(ref['kind'], {})
            if ref['id'] not in known:
                errors.append('UNKNOWN_REFERENCE:' + ref['id'])
            elif ref['kind'] == 'metric':
                metric = known[ref['id']]
                if ref['id'].startswith(TEXT_PREFIXES):
                    continue
                numeric = isinstance(ref.get('value'), (int, float)) and not isinstance(ref.get('value'), bool)
                ref_value = ref.get('value')
                if isinstance(metric['value'], bool) and isinstance(ref_value, str) and ref_value.strip().lower() in ('true', 'false'):
                    ref_value = ref_value.strip().lower() == 'true'
                value_bad = ref_value is not None and not (rounded_equal(ref_value, metric['value']) if numeric else ref_value == metric['value'])
                unit_bad = ref.get('unit') is not None and not unit_equal(ref['unit'], metric['unit'])
                if value_bad or unit_bad:
                    errors.append('METRIC_VALUE_UNIT_MISMATCH:' + ref['id'])
            elif known[ref['id']].get('coverage_limited') and not any(t in observation['text'] for t in ('資料涵蓋','coverage','涵蓋範圍')):
                errors.append('COVERAGE_QUALIFIER_REQUIRED')
    for reason in card['reasoning']:
        if not set(reason['knowledge_refs']) <= set(spec['knowledge_ids']):
            errors.append('UNKNOWN_KNOWLEDGE_REFERENCE')
        if reason['lens'].split('-')[0] not in spec['lenses']:
            errors.append('UNKNOWN_LENS')
        if spec['stage'] in ('site','compare') and any(t in reason['text'] for t in ('人流','行人量')) and not any(t in reason['text'] for t in ('潛力','不是實測')):
            errors.append('SYNTAX_FLOW_CONFLATION')
    allowed = {'morphology':{'height','courtyard_width','setback','intensity','block_subdivision','street_section','street_add_remove','open_space_allocation','analysis_needed'},'site':{'retention','street_add_remove','open_space_allocation','intensity','land_use','analysis_needed'},'climate':{'height','setback','courtyard_width','orientation','open_space_allocation','planting_shade','analysis_needed'}}
    if spec['stage'] in allowed and any(r['parameter_family'] not in allowed[spec['stage']] for r in card['revision_directions']):
        errors.append('INVALID_PARAMETER_FAMILY')
    if spec['stage'] == 'climate':
        for text in list(narrative(card))[:-len(card['questions_for_designer'])]:
            wind_related = 'E5' in text or '風' in text or re.search(r'\bwind\b', text, re.I)
            conclusion = any(t in text for t in ('舒適','安全')) or re.search(r'\b(?:comfortable|comfort|safe|safety)\b', text, re.I)
            if wind_related and conclusion and text not in card['limitations']:
                errors.append('E5_CONCLUSION')
        if any('中庭' in r['action'] and any(t in r['action'] for t in ('不停留','不需停留','改定位')) for r in card['revision_directions']):
            errors.append('DESIGNER_STANCE_CONFLICT')
    if spec['stage'] == 'morphology':
        mentions = '\n'.join([o['text'] for o in card['observations']] + card['limitations'])
        for ident, metric in bundle['metrics'].items():
            if ident.startswith('morph.') and '.check.' in ident:
                failure = ident.split('.check.', 1)[1]
                label = metric.get('label_zh')
                if failure not in mentions and not (label and label in mentions):
                    errors.append('MORPH_FAILURE_OMITTED:' + failure)
        if len(card['questions_for_designer']) > 2:
            errors.append('MORPH_QUESTION_COUNT')
    limitation_text='\n'.join(card['limitations'])
    if bundle['data_gaps'] and not any(term in limitation_text for term in ('DATA_GAP','資料缺口','資料不足','缺少','缺漏','missing','gap')):
        errors.append('DATA_GAP_OMITTED')
    e5_named = 'DATA_GAP:e5' in limitation_text or any(('DATA_GAP' in item or '資料缺口' in item) and re.search(r'(?<![A-Za-z0-9])[eE]5(?![0-9])|風場', item) for item in card['limitations'])
    if spec['stage']=='climate' and any(gap.startswith('DATA_GAP:e5') for gap in bundle['data_gaps']) and not e5_named:
        errors.append('DATA_GAP_OMITTED:DATA_GAP:e5.*')
    return sorted(set(errors))
