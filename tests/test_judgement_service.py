import copy
import json
from types import SimpleNamespace
import pytest
from urban_design.judgement.core import Registry, validate
from urban_design.judgement.service import JudgementService, RunRequest, ResponseRequest, compliance_checklist
from urban_design.store import ProjectStateStore

@pytest.fixture
def registry(): return Registry()
@pytest.fixture
def bundle():
    return {'subject':{'kind':'site','ids':['site-test']},'metrics':{'site.area':{'value':12.345,'unit':'m2','source_sha256':'a'*64}},'references':{'evidence_card':{},'artifact':{}},'data_gaps':[],'sources':{},'context':{}}

def card():
    return {'skill_id':'J-SITE','skill_version':'1.0.0','stage':'site','subject':{'kind':'site','ids':['site-test']},'observations':[{'text':'基地資料顯示既有邊緣需要持續關注。','refs':[{'kind':'metric','id':'site.area','value':12.345,'unit':'m2'}]} for _ in range(3)],'judgement':{'stance':'CONCERN','headline':'我認為基地的連結需要先釐清再提出空間策略。'},'reasoning':[{'lens':'L1','text':'現有的資料可以支持提出暫時的空間判斷，但仍需設計者提供在地知識。','knowledge_refs':['KU-MOR-009']},{'lens':'L2','text':'路網連結僅能表達潛力，仍需要補充現場觀察以支持後續的空間策略。','knowledge_refs':['KU-SYN-009']}],'confidence':{'level':'low','why':'輸入範圍有限，尚需進一步資料。'},'revision_directions':[{'action':'先補充基地入口與周邊連結分析。','target':'site','parameter_family':'analysis_needed','expected_effect':'釐清連結條件','trade_off':'需要更多資料'}],'counterpoints':['保留既有骨架也可能限制後續的空間調整。'],'limitations':['資料涵蓋範圍有限，判斷仍屬暫時。'],'questions_for_designer':['你認為哪些港埠遺構最值得保留？']}

class Fake:
    provider_name='fixture';is_live_available=True
    profile=SimpleNamespace(id='fixture',model='fixture',adapter='fixture')
    def __init__(self,outputs): self.outputs=iter(outputs);self.calls=0
    def generate_structured(self,request):
        self.calls+=1
        output=next(self.outputs)
        if isinstance(output,Exception): raise output
        return {'provider_status':'LIVE_AI: ACTIVE','structured':output,'provider_model':'fixture','limitations':[]}

def service(tmp_path,monkeypatch,bundle,registry,outputs):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED','1');monkeypatch.setenv('ARIADNE_LIVE','1')
    monkeypatch.setattr('urban_design.judgement.service.assemble',lambda *a,**kw:copy.deepcopy(bundle))
    store=ProjectStateStore(tmp_path/'project.sqlite3');provider=Fake(outputs)
    return JudgementService(store,tmp_path/'judgements.sqlite3',registry=registry,provider_factory=lambda *a:provider),provider

def test_registry_and_valid_card(registry,bundle):
    assert set(registry.specs)=={'J-SITE', 'J-COMPARE', 'J-CLIMATE', 'J-MORPH'}
    assert validate(card(),bundle,registry.specs['J-SITE'],registry.schema)==[]

@pytest.mark.parametrize('mutation,expected',[
    (lambda c:c['observations'][0].update(text='基地面積為 99.7 m2，需持續關注。'),'UNSOURCED_NUMBER'),
    (lambda c:c['observations'][0]['refs'][0].update(unit='ha'),'METRIC_VALUE_UNIT_MISMATCH'),
    (lambda c:c['reasoning'][0].update(knowledge_refs=['KU-CLI-999']),'UNKNOWN_KNOWLEDGE_REFERENCE'),
    (lambda c:c['judgement'].update(headline='這個基地已核准可以作為最終的設計基地。'),'FORBIDDEN'),
])
def test_rejects(registry,bundle,mutation,expected):
    output=card();mutation(output)
    assert any(expected in error for error in validate(output,bundle,registry.specs['J-SITE'],registry.schema))

def test_rounding(registry,bundle):
    output=card();output['observations'][0]['text']='基地面積為 12.35，必須結合其他資料判斷。'
    assert not validate(output,bundle,registry.specs['J-SITE'],registry.schema)

def test_input_digest_independent_of_output_language(tmp_path,monkeypatch,bundle,registry):
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[card(),card()])
    zh=svc.run('project-test',RunRequest(skill_id='J-SITE',language='zh-TW'))
    en=svc.run('project-test',RunRequest(skill_id='J-SITE',language='en'))
    assert zh['input_sha256']==en['input_sha256']
    assert zh['id']!=en['id'] and provider.calls==2

def test_lens_suffix_cannot_hide_unsourced_number(registry,bundle):
    output=card();output['reasoning'][0]['lens']='L1-999999'
    assert any('UNSOURCED_NUMBER' in error for error in validate(output,bundle,registry.specs['J-SITE'],registry.schema))

def test_extreme_precision_fails_closed(registry,bundle):
    output=card();output['observations'][0]['text']='基地觀察值為 1e-999999，仍需要進一步調查。'
    assert any('UNSOURCED_NUMBER' in error for error in validate(output,bundle,registry.specs['J-SITE'],registry.schema))

def test_coverage_qualifier_required_even_when_negated_claim(registry,bundle):
    bundle['references']['evidence_card']['limited']={'coverage_limited':True}
    output=card();output['observations'][0]['refs']=[{'kind':'evidence_card','id':'limited'}]
    assert 'COVERAGE_QUALIFIER_REQUIRED' in validate(output,bundle,registry.specs['J-SITE'],registry.schema)
    output['observations'][0]['text']='在資料涵蓋範圍內，既有邊緣需要持續關注。'
    assert not validate(output,bundle,registry.specs['J-SITE'],registry.schema)
    output['judgement']['headline']='我認為目前不能說此基地已核准，仍需要調查。'
    assert 'FORBIDDEN_CLAIM_OR_EXTERNAL_REFERENCE' in validate(output,bundle,registry.specs['J-SITE'],registry.schema)

def test_e5_conclusion_rejected_outside_limitations(registry,bundle):
    output=card();output.update(skill_id='J-CLIMATE',skill_version='1.1.0',stage='climate')
    output['reasoning'][0]['knowledge_refs']=['KU-CLI-007']
    output['reasoning'][1]['knowledge_refs']=['KU-CLI-026']
    output['observations'][0]['text']='E5 風場結果代表這個地方可以舒適停留。'
    assert 'E5_CONCLUSION' in validate(output,bundle,registry.specs['J-CLIMATE'],registry.schema)

def test_cache_accounting_and_project_scope(tmp_path,monkeypatch,bundle,registry):
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[card()])
    first=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert first['status']=='VALIDATED'
    assert svc.run('project-test',RunRequest(skill_id='J-SITE'))['id']==first['id']
    assert provider.calls==1
    assert svc.usage('project-test')['calls']==1
    with pytest.raises(KeyError):svc.get('other-project',first['id'])
    with pytest.raises(ValueError):svc.respond('project-test',first['id'],ResponseRequest(kind='contest'))
    response=svc.respond('project-test',first['id'],ResponseRequest(kind='contest',text='請重新考慮保留價值'))
    assert response['is_human_decision'] is False
    assert svc.get('project-test',first['id'])['responses'][0]==response
    assert svc.store.list_current('HumanDecision',project_id='project-test')==[]
    agent_response=svc.respond('project-test',first['id'],ResponseRequest(
        kind='supplement',text='Please retain the existing entrance.',language='en',
        actor_kind='AGENT',actor_id='agent-ariadne'))
    assert agent_response['actor_kind']=='AGENT'
    assert agent_response['actor_id']=='agent-ariadne'
    assert agent_response['language']=='en'
    assert agent_response['is_human_decision'] is False
    assert svc.list('project-test',language='en')['cards']==[]
    assert svc.store.list_current('HumanDecision',project_id='project-test')==[]
    input_bundle,_previous=svc.inputs('project-test',RunRequest(skill_id='J-SITE'))
    assert input_bundle['designer_responses']==[response]


def test_judgement_cache_respects_provider_profile_and_preserves_old_rows(tmp_path, monkeypatch, bundle, registry):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    monkeypatch.setenv('ARIADNE_LIVE', '1')
    monkeypatch.setattr('urban_design.judgement.service.assemble', lambda *a, **kw: copy.deepcopy(bundle))
    store = ProjectStateStore(tmp_path / 'project.sqlite3')

    p1 = Fake([card(), card()])
    p1.profile = SimpleNamespace(id='codex-cli', model='gpt-6-luna', adapter='cli_subprocess')

    p2 = Fake([card(), card()])
    p2.profile = SimpleNamespace(id='claude-cli', model='claude-default', adapter='cli_subprocess')

    active_provider = p1
    svc = JudgementService(
        store,
        tmp_path / 'judgements.sqlite3',
        registry=registry,
        provider_factory=lambda *a: active_provider,
    )

    first = svc.run('project-test', RunRequest(skill_id='J-SITE'))
    assert first['status'] == 'VALIDATED'
    assert first['provider_profile_id'] == 'codex-cli'
    assert first['provider_profile_id'] == 'codex-cli' and 'provider_profile_id' not in first['card']
    assert p1.calls == 1

    # Same profile hits cache
    cached_first = svc.run('project-test', RunRequest(skill_id='J-SITE'))
    assert cached_first['id'] == first['id']
    assert p1.calls == 1

    # Switch profile to claude-cli: cache must NOT return codex-cli card
    active_provider = p2
    second = svc.run('project-test', RunRequest(skill_id='J-SITE'))
    assert second['status'] == 'VALIDATED'
    assert second['id'] != first['id']
    assert second['provider_profile_id'] == 'claude-cli'
    assert second['provider_profile_id'] == 'claude-cli' and 'provider_profile_id' not in second['card']
    assert p2.calls == 1

    # Same profile claude-cli hits cache
    cached_second = svc.run('project-test', RunRequest(skill_id='J-SITE'))
    assert cached_second['id'] == second['id']
    assert p2.calls == 1

    # Verify old database row without provider_profile_id in payload defaults to codex-cli
    with svc.connect() as db:
        old_row = db.execute("SELECT payload FROM judgement_runs WHERE id=?", (first['id'],)).fetchone()
        old_payload = json.loads(old_row['payload'])
        del old_payload['provider_profile_id']
        old_id = 'judgement-old-legacy-row'
        old_payload['id'] = old_id
        db.execute(
            "INSERT INTO judgement_runs VALUES (?,?,?,?,?)",
            (old_id, 'project-test', 'J-SITE', 'cache-key-legacy', json.dumps(old_payload)),
        )

    # When accessed via get, provider_profile_id falls back to codex-cli
    legacy_card = svc.get('project-test', old_id)
    assert legacy_card['provider_profile_id'] == 'codex-cli'
    assert 'provider_profile_id' not in (legacy_card['card'] or {})

def test_one_validation_retry(tmp_path,monkeypatch,bundle,registry):
    bad=card();bad['judgement']['headline']='這個基地已核准可以作為最終的設計基地。'
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[bad,card()])
    result=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert result['status']=='VALIDATED' and provider.calls==2
    assert svc.usage('project-test')['calls']==2

def test_unknown_never_redispatches(tmp_path,monkeypatch,bundle,registry):
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[TimeoutError('after dispatch')])
    first=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert first['status']=='OUTCOME_UNKNOWN'
    assert svc.run('project-test',RunRequest(skill_id='J-SITE'))['id']==first['id']
    assert provider.calls==1
    assert svc.store.list_current('ModelRun',project_id='project-test')[0].payload['status']=='OUTCOME_UNKNOWN'

def test_response_creates_next_round(tmp_path,monkeypatch,bundle,registry):
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[card(),card()])
    first=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    svc.respond('project-test',first['id'],ResponseRequest(kind='supplement',text='入口應保留'))
    second=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert second['round']==2 and second['id']!=first['id'] and provider.calls==2

def test_blocked_can_retry_after_gate_reenabled(tmp_path,monkeypatch,bundle,registry):
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[card()])
    monkeypatch.setenv('ARIADNE_LIVE','0')
    first=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert first['status']=='BLOCKED_AI_AUTHORIZATION' and provider.calls==0
    monkeypatch.setenv('ARIADNE_LIVE','1')
    second=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert second['status']=='VALIDATED' and provider.calls==1
    assert second['input_sha256']==first['input_sha256']
    assert svc.run('project-test',RunRequest(skill_id='J-SITE'))['id']==second['id']

def test_flow_qualifier_must_be_same_sentence(registry,bundle):
    output=card();output['observations'][0]['text']='語法顯示人流集中。這是潛力判斷而已。'
    assert 'SYNTAX_FLOW_CONFLATION' in validate(output,bundle,registry.specs['J-SITE'],registry.schema)

def test_api_inputs_hash_and_response_scope(tmp_path,monkeypatch,bundle,registry):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from urban_design.judgement.router import create_judgement_router
    store=ProjectStateStore(tmp_path/'project.sqlite3')
    monkeypatch.setattr('urban_design.judgement.service.assemble',lambda *a,**kw:copy.deepcopy(bundle))
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED','1');monkeypatch.setenv('ARIADNE_LIVE','1')
    fake=Fake([card()]);app=FastAPI()
    app.include_router(create_judgement_router(project_store=store,database=tmp_path/'judgement.sqlite3',registry=registry,provider_factory=lambda *a:fake))
    client=TestClient(app);base='/api/v1/projects/project-test/ariadne/judgements'
    inputs=client.get(base+'/inputs',params={'skill_id':'J-SITE'}).json()
    result=client.post(base,json={'skill_id':'J-SITE','force':True}).json()
    assert inputs['input_sha256']==result['input_sha256']
    assert result['card_json']==result['card']
    assert client.post(base+'/'+result['id']+'/responses',json={'kind':'contest','text':''}).status_code==422
    assert client.post(base+'/'+result['id']+'/responses',json={'kind':'supplement','text':'x'*1001}).status_code==422
    assert client.get('/api/v1/projects/other/ariadne/judgements/'+result['id']).status_code==404

def test_budget_blocks_without_provider_dispatch(tmp_path,monkeypatch,bundle,registry):
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[card()])
    monkeypatch.setattr(svc,'usage',lambda project:{'calls':200,'limit':200})
    result=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert result['status']=='BLOCKED_BUDGET' and provider.calls==0

def test_exact_source_date_only(registry,bundle):
    bundle['metrics']['weather.date']={'value':'2017-08-19','unit':'date'}
    output=card();output['limitations']=['天氣資料只代表 2017-08-19，不能推廣全年。']
    assert not validate(output,bundle,registry.specs['J-SITE'],registry.schema)
    output['limitations']=['天氣資料只代表 2018-08-19，不能推廣全年。']
    assert any('UNSOURCED_NUMBER' in e for e in validate(output,bundle,registry.specs['J-SITE'],registry.schema))

def test_percent_conversion_requires_ratio_unit(registry,bundle):
    bundle['metrics']['site.ratio']={'value':0.25,'unit':'ratio'}
    output=card();output['observations'][0]['text']='比例為 25%，仍需要在空間上持續查核。'
    assert not validate(output,bundle,registry.specs['J-SITE'],registry.schema)
    output['observations'][0]['text']='比例為 25，仍需要在空間上持續查核。'
    assert any('UNSOURCED_NUMBER' in e for e in validate(output,bundle,registry.specs['J-SITE'],registry.schema))

def test_many_gaps_allow_human_summary(registry,bundle):
    bundle['data_gaps']=['DATA_GAP:site.'+str(i) for i in range(38)]
    output=card();output['limitations']=['基地資料仍有資料缺口，需補充後再判斷。']
    assert not validate(output,bundle,registry.specs['J-SITE'],registry.schema)

def test_force_success_but_never_unknown(tmp_path,monkeypatch,bundle,registry):
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[card(),card(),TimeoutError()])
    first=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    second=svc.run('project-test',RunRequest(skill_id='J-SITE',force=True))
    assert first['id']!=second['id'] and provider.calls==2
    unknown=svc.run('project-test',RunRequest(skill_id='J-SITE',force=True))
    assert unknown['status']=='OUTCOME_UNKNOWN'
    assert svc.run('project-test',RunRequest(skill_id='J-SITE',force=True))['id']==unknown['id']
    assert provider.calls==3

@pytest.mark.parametrize('mode,expected,calls',[('blocked','BLOCKED_AI_AUTHORIZATION',0),('budget','BLOCKED_BUDGET',0),('invalid','VALIDATION_FAILED',2),('unknown','OUTCOME_UNKNOWN',1)])
def test_api_terminal_paths(tmp_path,monkeypatch,bundle,registry,mode,expected,calls):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from urban_design.judgement.router import create_judgement_router
    bad=card();bad['counterpoints']=[]
    outputs=[bad,bad] if mode=='invalid' else [TimeoutError()] if mode=='unknown' else [card()]
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,outputs)
    if mode=='blocked':monkeypatch.setenv('ARIADNE_LIVE','0')
    if mode=='budget':monkeypatch.setattr(JudgementService,'usage',lambda self,project:{'calls':200,'limit':200})
    app=FastAPI();app.include_router(create_judgement_router(project_store=svc.store,database=tmp_path/'api.sqlite3',registry=registry,provider_factory=lambda *a:provider))
    client=TestClient(app);base='/api/v1/projects/project-test/ariadne/judgements'
    result=client.post(base,json={'skill_id':'J-SITE'}).json()
    assert result['status']==expected and result['card'] is None and provider.calls==calls
    if mode=='unknown':
        assert client.post(base,json={'skill_id':'J-SITE','force':True}).json()['id']==result['id']
        assert provider.calls==1

def test_unknown_dotted_identifier_cannot_hide_number(registry,bundle):
    output=card();output['observations'][0]['text']='基地面積為 site.invented.9999，仍需要更多查核。'
    assert any('UNSOURCED_NUMBER' in e for e in validate(output,bundle,registry.specs['J-SITE'],registry.schema))

def test_designer_response_follows_skill_across_subjects(tmp_path,monkeypatch,bundle,registry):
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[card()])
    first=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    response=svc.respond('project-test',first['id'],ResponseRequest(kind='supplement',text='既有遺構需要優先保留'))
    other=copy.deepcopy(bundle);other['subject']['ids']=['different-site']
    monkeypatch.setattr('urban_design.judgement.service.assemble',lambda *a,**kw:copy.deepcopy(other))
    inputs,previous=svc.inputs('project-test',RunRequest(skill_id='J-SITE',subject_ids=['different-site']))
    assert previous==[]
    assert inputs['designer_responses']==[response]
    assert inputs['metrics']['designer.stance.response.0']['value']==response['text']
    other_skill,_=svc.inputs('project-test',RunRequest(skill_id='J-COMPARE',subject_ids=['different-site']))
    assert other_skill['designer_responses']==[]

@pytest.mark.parametrize('written,unit,ok',[(0.11,'小時',True),(0.2,'h',False),(0.108,None,True),(0.11,'ha',False)])
def test_ref_rounding_and_unit_aliases(registry,bundle,written,unit,ok):
    bundle['metrics']['site.area'].update(value=0.108,unit='h')
    output=card();ref=output['observations'][0]['refs'][0]
    for obs in output['observations']:obs['refs']=[{'kind':'metric','id':'site.area'}]
    output['observations'][0]['refs'][0].update(value=written)
    if unit is not None:output['observations'][0]['refs'][0]['unit']=unit
    errors=validate(output,bundle,registry.specs['J-SITE'],registry.schema)
    assert (not errors)==ok

@pytest.mark.parametrize('prefix',['designer.stance.','context.','problem.','intent.','check.'])
def test_text_refs_only_check_identity(registry,bundle,prefix):
    ident=prefix+'example';bundle['metrics'][ident]={'value':{'zh':'文字'},'unit':None}
    output=card();output['observations'][0]['refs']=[{'kind':'metric','id':ident,'value':'文字 98765','unit':'任意'}]
    assert not validate(output,bundle,registry.specs['J-SITE'],registry.schema)

def test_attempt_raw_is_durable_and_private(tmp_path,monkeypatch,bundle,registry):
    bad=card();bad['counterpoints']=[]
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[bad,card()])
    result=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    attempts=svc.attempts('project-test',result['id'])['attempts']
    assert attempts[0]['raw_json']['structured']==bad
    assert attempts[0]['validation_errors']
    assert 'raw_json' not in json.dumps(svc.get('project-test',result['id']))
    assert 'raw_json' not in json.dumps(result)
    with pytest.raises(KeyError):svc.attempts('other',result['id'])

@pytest.mark.parametrize('source_unit,alias', [('h','hours'),('%','百分比'),('m²','m2'),('m²','平方公尺'),('kWh/m²·年','kWh/m2/yr'),('°C','℃'),('kW','千瓦')])
def test_all_unit_aliases(registry,bundle,source_unit,alias):
    bundle['metrics']['site.area'].update(value=26.4,unit=source_unit)
    output=card()
    for observation in output['observations']:
        observation['refs']=[{'kind':'metric','id':'site.area','value':26.4,'unit':alias}]
    assert not validate(output,bundle,registry.specs['J-SITE'],registry.schema)

@pytest.mark.parametrize('number,ok',[('0.11',True),('0.2',False)])
def test_narrative_expressed_precision(registry,bundle,number,ok):
    bundle['metrics']['site.area'].update(value=0.108,unit='h')
    output=card()
    for observation in output['observations']:observation['refs']=[{'kind':'metric','id':'site.area'}]
    output['observations'][0]['text']=f'冬至平均日照為 {number} 小時，需繼續釐清。'
    assert (not validate(output,bundle,registry.specs['J-SITE'],registry.schema))==ok

def test_attempts_endpoint_locality_and_project_scope(tmp_path,monkeypatch,bundle,registry):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from urban_design.judgement.router import create_judgement_router
    bad=card();bad['counterpoints']=[]
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[bad,bad])
    app=FastAPI();app.include_router(create_judgement_router(project_store=svc.store,database=tmp_path/'api.sqlite3',registry=registry,provider_factory=lambda *a:provider))
    local=TestClient(app,client=('127.0.0.1',1234));base='/api/v1/projects/project-test/ariadne/judgements'
    result=local.post(base,json={'skill_id':'J-SITE'}).json();url=base+'/'+result['id']+'/attempts'
    review=local.get(url)
    assert review.status_code==200 and len(review.json()['attempts'])==2
    assert review.json()['attempts'][0]['raw_json']['structured']==bad
    assert 'raw_json' not in json.dumps(local.get(base).json())
    assert local.get(url.replace('project-test','other')).status_code==404
    assert TestClient(app,client=('192.0.2.1',1234)).get(url).status_code==403

def test_retry_prompt_has_example_minitems_and_individual_errors(tmp_path,monkeypatch,bundle,registry):
    bad=card();bad['counterpoints']=[];bad['limitations']=[]
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[bad,card()])
    requests=[];original=provider.generate_structured
    def capture(request):
        requests.append(json.loads(request.query));return original(request)
    provider.generate_structured=capture
    svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert requests[0]['filled_example']['skill_id']=='J-CLIMATE'
    assert 'minItems' in requests[0]['instruction']
    errors=requests[1]['correction']['validation_errors']
    assert any('/counterpoints:' in error for error in errors)
    assert any('/limitations:' in error for error in errors)

def test_prompt_update_cannot_retry_unknown(tmp_path,monkeypatch,bundle,registry):
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[TimeoutError()])
    first=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    monkeypatch.setattr('urban_design.judgement.service.INSTRUCTION','changed template')
    assert svc.run('project-test',RunRequest(skill_id='J-SITE',force=True))['id']==first['id']
    assert provider.calls==1


def test_null_ref_value_and_limit_refs_are_not_assertions(registry,bundle):
    output=card()
    output['observations'][0]['refs']=[{**output['observations'][0]['refs'][0],'value':None,'unit':None}]
    assert not any('METRIC_VALUE_UNIT_MISMATCH' in e for e in validate(output,bundle,registry.specs['J-SITE'],registry.schema))

@pytest.mark.parametrize('resolution',['NOT_DELIVERED','DELIVERED_DISCARD'])
def test_reconcile_unlocks_and_preserves_model_receipt(tmp_path,monkeypatch,bundle,registry,resolution):
    from urban_design.judgement.service import ReconcileRequest
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[TimeoutError(),card()])
    first=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert svc.run('project-test',RunRequest(skill_id='J-SITE',force=True))['id']==first['id']
    receipt=svc.reconcile('project-test',first['id'],ReconcileRequest(resolution=resolution,note='Checked local process receipt'))
    assert receipt['model_runs'][0]['status']=='OUTCOME_UNKNOWN'
    assert 'provider_metadata' in receipt['model_runs'][0]
    with pytest.raises(ValueError):svc.reconcile('project-test',first['id'],ReconcileRequest(resolution=resolution,note='again'))
    second=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert second['id']!=first['id'] and second['status']=='VALIDATED' and provider.calls==2
    assert svc.get('project-test',first['id'])['status']=='OUTCOME_UNKNOWN'

def test_reconcile_api_only_ipv4_loopback(tmp_path,monkeypatch,bundle,registry):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from urban_design.judgement.router import create_judgement_router
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[TimeoutError()])
    app=FastAPI();app.include_router(create_judgement_router(project_store=svc.store,database=tmp_path/'api.sqlite3',registry=registry,provider_factory=lambda *a:provider))
    local=TestClient(app,client=('127.0.0.1',123));base='/api/v1/projects/project-test/ariadne/judgements'
    first=local.post(base,json={'skill_id':'J-SITE'}).json();url=base+'/'+first['id']+'/reconcile'
    body={'resolution':'NOT_DELIVERED','note':'Local inspection'}
    for host in ['192.0.2.1','::1','localhost']:
        assert TestClient(app,client=(host,123)).post(url,json=body).status_code==403
    assert local.post(url.replace('project-test','other'),json=body).status_code==404
    assert local.post(url,json={**body,'resolution':'RETRY'}).status_code==422
    assert local.post(url,json=body).status_code==200

def test_model_prompt_compact_and_bounded(tmp_path,monkeypatch,bundle,registry):
    bundle['inputs']=[{'metric_id':'site.area','value':12.345,'source_path':'private'}]
    bundle['sources']={'private':'a'*64}
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[card()])
    requests=[];original=provider.generate_structured
    def capture(request):
        requests.append(request.query);return original(request)
    provider.generate_structured=capture
    svc.run('project-test',RunRequest(skill_id='J-SITE'))
    payload=json.loads(requests[0])['input']
    assert 'inputs' not in payload and 'sources' not in payload
    assert payload['metrics']['site.area']=={'value':12.345,'unit':'m2'}
    assert len(requests[0].encode())<120_000

def test_reconcile_rejects_while_provider_running(tmp_path,monkeypatch,bundle,registry):
    from urban_design.judgement.service import ReconcileRequest
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[TimeoutError()])
    first=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    svc._execution_lock.acquire()
    try:
        with pytest.raises(ValueError,match='execution in progress'):
            svc.reconcile('project-test',first['id'],ReconcileRequest(resolution='NOT_DELIVERED',note='too soon'))
    finally:
        svc._execution_lock.release()

@pytest.mark.parametrize('skill',['J-SITE','J-COMPARE','J-CLIMATE'])
def test_real_complete_prompt_below_120kb(tmp_path,monkeypatch,registry,skill):
    from urban_design.judgement.inputs import assemble
    real=assemble(None,'fixture',skill,[],registry)
    svc,provider=service(tmp_path,monkeypatch,real,registry,[card(),card()])
    prompts=[];original=provider.generate_structured
    def capture(request):
        prompts.append(request.query);return original(request)
    provider.generate_structured=capture
    svc.run('project-test',RunRequest(skill_id=skill))
    assert prompts
    assert all(len(prompt.encode('utf-8'))<120_000 for prompt in prompts)
    from urban_design.model_provider import CliSubprocessCriticProvider, StructuredRequest, _structured_prompt
    from urban_design.judgement.service import strict_output_schema
    for prompt in prompts:
        wire = CliSubprocessCriticProvider._apply_ariadne_persona(
            _structured_prompt(StructuredRequest(study_area_id='project-test', query=prompt,
                response_schema=strict_output_schema(registry.schema))), task_title='Judgement Task Instructions')
        assert len(wire.encode('utf-8')) < 120_000

def test_reconcile_finalizes_pending_after_lost_terminal_write(tmp_path,monkeypatch,bundle,registry):
    from urban_design.judgement.service import ReconcileRequest
    from urban_design.model_provider import ProjectStateModelRunAccounting
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[TimeoutError()])
    finish=ProjectStateModelRunAccounting.finish
    monkeypatch.setattr(ProjectStateModelRunAccounting,'finish',lambda *a,**kw:False)
    first=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert svc.store.list_current('ModelRun',project_id='project-test')[0].payload['status']=='PENDING'
    monkeypatch.setattr(ProjectStateModelRunAccounting,'finish',finish)
    receipt=svc.reconcile('project-test',first['id'],ReconcileRequest(resolution='NOT_DELIVERED',note='Commander verified launch never occurred'))
    assert receipt['model_runs'][0]['status']=='PENDING'
    assert receipt['model_runs'][0]['reconciled_status']=='MODEL_FAILED'
    assert svc.store.list_current('ModelRun',project_id='project-test')[0].payload['status']=='MODEL_FAILED'


def test_numbers_inside_text_inputs_and_ids_are_sourced_but_others_are_not(registry,bundle):
    bundle['metrics']['context.osm.summary']={'value':'Galileïstraat 延伸候選長約 1330.20 m。','unit':None}
    bundle['metrics']['syntax.context.ped.nain.800.site.mean']={'value':0.5,'unit':'NAIN'}
    output=card(); output['observations'][0]['text']='在資料涵蓋範圍內，延伸候選約 1330.20 m，800 m 半徑結果僅供參考。'
    errors=validate(output,bundle,registry.specs['J-SITE'],registry.schema)
    assert not any(e.startswith('UNSOURCED_NUMBER:1330') or e.startswith('UNSOURCED_NUMBER:800') for e in errors)
    output['observations'][0]['text']='在資料涵蓋範圍內，延伸候選約 4321.5 m。'
    assert 'UNSOURCED_NUMBER:4321.5' in validate(output,bundle,registry.specs['J-SITE'],registry.schema)

def test_revision_summary_text_input_whitelists_before_and_after_values(registry,bundle):
    from urban_design.judgement.revision_inputs import _revision_context_summary
    revision_context = {
        'proposal_id': 'proposal-1',
        'operations_text_zh': ['new-7、new-8 各降 1 層'],
        'before_metrics': {'e1.harbour.courtyard.winter.mean_h': 0.108},
        'dry_run': {'solar_access_check': {'courtyards': []}},
    }
    summary = _revision_context_summary(revision_context, {
        'e1.harbour.courtyard.winter.mean_h': {'value': 0.109},
    })
    bundle['metrics']['context.revision_summary_zh'] = {'value': summary, 'unit': 'text'}
    bundle['inputs'] = [{'metric_id': 'context.revision_summary_zh',
                         **bundle['metrics']['context.revision_summary_zh']}]
    output = card()
    output['observations'][0]['text'] = '重算前中庭冬至平均日照 0.108 小時；重算後 0.109 小時。'

    assert not any(error.startswith(('UNSOURCED_NUMBER:0.108', 'UNSOURCED_NUMBER:0.109'))
                   for error in validate(output,bundle,registry.specs['J-SITE'],registry.schema))
    output['observations'][0]['text'] = '重算前後數值為 0.108 與 0.999 小時。'
    assert 'UNSOURCED_NUMBER:0.999' in validate(output,bundle,registry.specs['J-SITE'],registry.schema)

@pytest.mark.parametrize(('subject_ids', 'revision_context', 'expected'), [
    (['harbour_grain@draft-r3'], {'dry_run': {'solar_access_check': {'courtyards': [
        {'courtyard_id': 'courtyard-0', 'reaches_north_edge': False}]}}}, True),
    (['harbour_grain'], {'dry_run': {'solar_access_check': {'courtyards': [
        {'courtyard_id': 'courtyard-0', 'reaches_north_edge': False}]}}}, False),
    (['harbour_grain@draft-r3'], None, False),
])
def test_revision_context_checklist_only_applies_to_draft_judgements(registry,bundle,subject_ids,revision_context,expected):
    bundle['subject'] = {'kind': 'scheme', 'ids': subject_ids}
    bundle['context'] = {'revision_context': revision_context}

    items = compliance_checklist(bundle, registry.specs['J-CLIMATE'])
    revision_rules = [item for item in items if '第一個 observation' in item]
    assert bool(revision_rules) is expected
    if expected:
        assert '重算前數值引用 prev.' in revision_rules[0]
        assert '降層幅度不足' in revision_rules[0]


def test_compliance_checklist_lists_input_specific_rules(registry,bundle):
    from urban_design.judgement.service import compliance_checklist
    bundle['data_gaps']=['DATA_GAP:site.waterfront_length_m']
    bundle['references']['evidence_card']['limited']={'coverage_limited':True}
    items=compliance_checklist(bundle, registry.specs['J-SITE'])
    assert any('site.waterfront_length_m' in i and i.startswith('limitations') for i in items)
    bundle['data_gaps']=[f'DATA_GAP:g{n}' for n in range(9)]
    gap_rule=next(i for i in compliance_checklist(bundle, registry.specs['J-SITE']) if i.startswith('limitations'))
    assert '等 9 項' in gap_rule and 'g8' not in gap_rule
    assert any('limited' in i and '在資料涵蓋範圍內' in i for i in items)
    assert any('人流' in i for i in items)


def test_strict_output_schema_drops_keywords_strict_mode_rejects():
    import json
    from pathlib import Path
    from urban_design.judgement.service import strict_output_schema
    schema = json.loads(Path('knowledge/judgement/proposal.schema.json').read_text())
    text = json.dumps(strict_output_schema(schema))
    for keyword in ('uniqueItems', 'minimum', 'maximum', 'minItems', 'maxLength', 'pattern'):
        assert f'"{keyword}"' not in text


def test_compliance_checklist_requires_literal_e5_gap_for_climate(registry,bundle):
    from urban_design.judgement.service import compliance_checklist
    bundle['data_gaps']=[f'DATA_GAP:g{n}' for n in range(6)]+['DATA_GAP:e5.harbour.wind']
    items=compliance_checklist(bundle, registry.specs['J-CLIMATE'])
    assert any('逐字包含「DATA_GAP:e5」' in i for i in items)
    bundle['data_gaps']=['DATA_GAP:g1']
    assert not any('DATA_GAP:e5' in i for i in compliance_checklist(bundle, registry.specs['J-CLIMATE']))


def test_sourced_numbers_with_thousands_separators_and_listed_e5_gap(registry, bundle):
    from urban_design.judgement.core import validate
    output = card()
    bundle['metrics']['context.revision_summary_zh'] = {'value': '移除 4,009.747 平方公尺，移入 3,067.2 平方公尺', 'unit': None}
    output['observations'][0]['text'] = '包絡移除約 4,009.7 平方公尺、移入 3,067.2 平方公尺。'
    assert not any(e.startswith('UNSOURCED_NUMBER') for e in validate(output, bundle, registry.specs['J-SITE'], registry.schema))


def test_checklist_states_length_limits(registry, bundle):
    from urban_design.judgement.service import compliance_checklist
    assert any('headline ≤ 200' in item for item in compliance_checklist(bundle, registry.specs['J-SITE']))
