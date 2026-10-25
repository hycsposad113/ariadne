"""Offline end-to-end caller schema and durable dispatch contract tests."""
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from urban_design.judgement.core import Registry
from urban_design.judgement.service import JudgementService, RunRequest, strict_output_schema
from urban_design.model_profiles import ModelProviderProfile
from urban_design.model_provider import (
    CliSubprocessCriticProvider, ModelProviderRouter,
    OpenAICompatibleCriticProvider, StructuredRequest,
)
from urban_design.store import ProjectStateStore
from test_judgement_service import card, bundle, registry


def profile(command='codex'):
    return ModelProviderProfile.model_validate({
        'id': command+'-test', 'adapter':'cli_subprocess',
        'cli_command':command, 'base_url':'', 'model':'gpt-6-luna' if command=='codex' else 'fixture-model',
        'reasoning_effort':'max' if command=='codex' else None,
        'supports_json_schema':True, 'data_egress':'cloud','enabled':True,
    })


@pytest.fixture(autouse=True)
def authorize(monkeypatch):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED','1')
    monkeypatch.setenv('ARIADNE_LIVE','1')


def request():
    return StructuredRequest(study_area_id='project-test', query='Interpret supplied evidence only.',
                             response_schema=Registry().schema)


@pytest.mark.parametrize('command',['codex','claude'])
def test_judgement_cli_sends_own_schema_direct_to_validator(tmp_path,monkeypatch,bundle,command):
    calls=[]
    store=ProjectStateStore(tmp_path/'project.sqlite3')
    def runner(args,**kwargs):
        calls.append(args)
        [pending]=store.list_current('ModelRun',project_id='project-test')
        assert pending.payload['status']=='PENDING'
        schema=(json.loads(Path(args[args.index('--output-schema')+1]).read_text())
                if command=='codex' else json.loads(args[args.index('--json-schema')+1]))
        assert schema==strict_output_schema(Registry().schema)
        assert 'critic_id' not in schema['properties']
        assert '[System Persona: Ariadne]' in kwargs['input']
        assert '[Judgement Task Instructions]' in kwargs['input']
        assert 'Critic Task Instructions' not in kwargs['input']
        output=card() if command=='codex' else {'structured_output':card(),'model':'actual-fixture'}
        return SimpleNamespace(returncode=0,stdout=json.dumps(output))
    provider=CliSubprocessCriticProvider(profile(command),cli_runner=runner,
        cli_resolver=lambda _: '/fake/'+command,use_ariadne_persona=True)
    monkeypatch.setattr('urban_design.judgement.service.assemble',lambda *a,**kw:copy.deepcopy(bundle))
    svc=JudgementService(store,tmp_path/'judgements.sqlite3',provider_factory=lambda *a:provider)
    result=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert result['status']=='VALIDATED'
    assert result['card']==card() and len(calls)==1
    raw=svc.attempts('project-test',result['id'])['attempts'][0]['raw_json']
    assert raw['structured']==card()
    [run]=store.list_current('ModelRun',project_id='project-test')
    assert run.payload['status']=='SUCCEEDED' and run.payload['validation_result']=='PASSED'
    assert run.payload['schema_version']=='urban_design_judgement'
    assert run.payload['response_hash']==hashlib.sha256(json.dumps(card(),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


@pytest.mark.parametrize('supports',[True,False])
def test_judgement_openai_uses_caller_schema(supports):
    p=ModelProviderProfile.model_validate({'id':'http-test','adapter':'openai_compatible',
        'base_url':'https://fixture.invalid/v1','model':'fixture-model','supports_json_schema':supports,
        'data_egress':'cloud','keychain_service':'fixture-only','enabled':True})
    def transport(url,headers,body,timeout):
        if supports:
            assert body['response_format']['json_schema']['schema']==request().response_schema
            assert body['response_format']['json_schema']['strict'] is False
        else: assert body['response_format']=={'type':'json_object'}
        assert 'evidence-bound urban-design critic' not in body['messages'][0]['content']
        return 200,{'model':'actual-fixture','choices':[{'message':{'content':json.dumps(card())}}]}
    provider=OpenAICompatibleCriticProvider(p,api_key='fake-key',transport=transport,
        model_list_transport=lambda *a:(200,{'data':[{'id':'fixture-model'}]}))
    result=provider.generate_structured(request())
    assert result['structured']==card() and result['provider_status']=='LIVE_AI: ACTIVE'


class Recording:
    is_live_available=True
    provider_name='fixture'
    def __init__(self,store,result=None,throws=False):
        self.profile=profile(); self.store=store; self.calls=0; self.result=result; self.throws=throws
    def generate_structured(self,req):
        self.calls+=1
        runs=self.store.list_current('ModelRun',project_id='project-test')
        assert any(r.payload['status']=='PENDING' for r in runs)
        if self.throws: raise subprocess.TimeoutExpired('fake',1)
        return self.result or {'structured':card(),'provider_status':'LIVE_AI: ACTIVE','provider_model':'fixture'}


def router(store,providers,**kwargs):
    return ModelProviderRouter(providers=providers,fallback_order=list(providers),store=store,
                               project_id='project-test',**kwargs)


@pytest.mark.parametrize('passed',[True,False])
def test_judgement_structured_validation_and_shared_budget(tmp_path,passed):
    store=ProjectStateStore(tmp_path/'project.sqlite3'); provider=Recording(store)
    r=router(store,{'first':provider},weekly_call_limit=2)
    for _ in range(2):
        result=r.generate_structured(request())
        assert r.record_validation_result(result,passed=passed)
    assert r.generate_structured(request())['provider_status']=='LIVE_AI: BLOCKED_BUDGET'
    assert provider.calls==2 and r.weekly_calls_used()==2
    for run in store.list_current('ModelRun',project_id='project-test'):
        assert run.payload['validation_result']==('PASSED' if passed else 'FAILED')
        assert run.payload['status']==('SUCCEEDED' if passed else 'MODEL_FAILED')
        assert run.payload['response_hash']


@pytest.mark.parametrize('code',[401,402,403,None])
def test_judgement_structured_rejection_or_unknown_never_falls_back(tmp_path,code):
    store=ProjectStateStore(tmp_path/'project.sqlite3')
    first=Recording(store,result={'provider_status':'LIVE_AI: REQUEST_REJECTED',
        'provider_metadata':{'http_status':code}},throws=code is None)
    second=Recording(store)
    r=router(store,{'first':first,'second':second})
    result=r.generate_structured(request())
    assert first.calls==1 and second.calls==0
    [run]=store.list_current('ModelRun',project_id='project-test')
    assert run.payload['status']==('OUTCOME_UNKNOWN' if code is None else 'MODEL_FAILED')
    if code is None: assert result['provider_status']=='LIVE_AI: OUTCOME_UNKNOWN'


def test_judgement_and_critic_share_default_200_call_reservations(tmp_path):
    from urban_design.model_provider import CriticRequest
    store=ProjectStateStore(tmp_path/'project.sqlite3')
    provider=Recording(store)
    provider.generate_criticism=lambda req: {'provider_status':'LIVE_AI: ACTIVE',
        'observations':['fixture'],'evidence_refs':[],'design_hypotheses':[],
        'limitations':[],'next_questions':[]}
    r=router(store,{'fixture':provider})
    for i in range(200):
        result=(r.generate_structured(request()) if i%2 else
                r.generate_criticism(CriticRequest(study_area_id='project-test')))
        assert result['provider_status']=='LIVE_AI: ACTIVE'
        assert r.record_validation_result(result,passed=True)
    assert r.weekly_calls_used()==200 and provider.calls==100
    assert r.generate_structured(request())['provider_status']=='LIVE_AI: BLOCKED_BUDGET'
    assert r.generate_criticism(CriticRequest(study_area_id='project-test'))['provider_status']=='LIVE_AI: BLOCKED_BUDGET'
    assert len(store.list_current('ModelRun',project_id='project-test'))==200


def test_judgement_does_not_extract_legacy_observations_string(tmp_path,monkeypatch,bundle,registry):
    from test_judgement_service import service
    legacy={'observations':[json.dumps(card())]}
    svc,provider=service(tmp_path,monkeypatch,bundle,registry,[legacy,legacy])
    result=svc.run('project-test',RunRequest(skill_id='J-SITE'))
    assert result['status']=='VALIDATION_FAILED' and result['card'] is None
    assert provider.calls==2


@pytest.mark.parametrize('command', ['codex', 'claude'])
@pytest.mark.parametrize('failure', ['e2big', 'missing', 'permission', 'timeout', 'nonzero', 'malformed', 'unexpected'])
def test_cli_failures_always_finalize_model_run(tmp_path, command, failure):
    import errno

    store = ProjectStateStore(tmp_path / 'project.sqlite3')
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        assert kwargs['input'] not in args
        assert kwargs['text'] is True and 'stdin' not in kwargs
        assert kwargs['timeout'] == 300  # structured judgement window (STRUCTURED_CLI_TIMEOUT_SECONDS)
        if command == 'codex':
            assert args[-1] == '-'
        if failure == 'e2big':
            raise OSError(errno.E2BIG, 'argument list too long')
        if failure == 'missing':
            raise FileNotFoundError('fixture')
        if failure == 'permission':
            raise PermissionError('fixture')
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 120)
        if failure == 'unexpected':
            raise RuntimeError('fixture')
        return SimpleNamespace(returncode=1 if failure == 'nonzero' else 0, stdout='invalid json')

    provider = CliSubprocessCriticProvider(profile(command), cli_runner=runner,
        cli_resolver=lambda _: '/fake/' + command)
    result = router(store, {'fixture': provider}).generate_structured(request())
    [run] = store.list_current('ModelRun', project_id='project-test')
    assert len(calls) == 1
    assert result['provider_metadata']['model_run_id'] == run.entity_id
    assert run.payload['validation_result'] == 'NOT_RUN'
    if failure in {'e2big', 'missing', 'permission'}:
        assert result['provider_status'] == 'LIVE_AI: CONNECTION_FAILED'
        assert result['provider_metadata']['delivery'] == 'not_started'
        assert run.payload['status'] == 'MODEL_FAILED'
    elif failure == 'malformed':
        assert result['provider_status'] == 'LIVE_AI: MODEL_FAILED'
        assert run.payload['status'] == 'MODEL_FAILED'
    else:
        assert result['provider_status'] == 'LIVE_AI: OUTCOME_UNKNOWN'
        assert result['provider_metadata']['delivery'] == 'unknown'
        assert run.payload['status'] == 'OUTCOME_UNKNOWN'


def test_terminal_receipt_persistence_failure_retains_model_run_id(tmp_path, monkeypatch):
    store = ProjectStateStore(tmp_path / 'project.sqlite3')
    provider = Recording(store, throws=True)
    routed = router(store, {'fixture': provider})
    monkeypatch.setattr(routed.accounting, 'finish', lambda *a, **kw: False)
    result = routed.generate_structured(request())
    [run] = store.list_current('ModelRun', project_id='project-test')
    assert result['provider_status'] == 'LIVE_AI: OUTCOME_UNKNOWN'
    assert result['provider_metadata']['model_run_id'] == run.entity_id
    assert result['provider_metadata']['delivery'] == 'unknown'
    assert run.payload['status'] == 'PENDING'


def test_structured_cli_requests_get_longer_bounded_timeout():
    from urban_design import model_provider as mp
    seen = []
    class Done:
        returncode = 1; stdout = ''; stderr = ''
    def runner(command, **options):
        seen.append(options['timeout']); return Done()
    profile = next(p for p in mp.load_model_provider_config().profiles if p.id == 'codex-cli') if hasattr(mp, 'load_model_provider_config') else None
    if profile is None:
        import pytest; pytest.skip('profile loader unavailable')
    provider = mp.CliSubprocessCriticProvider(profile, cli_runner=runner, cli_resolver=lambda command: '/usr/bin/true', timeout_seconds=120.0, request_id_factory=lambda: 'r1')
    provider.project_authorized = True
    provider.generate_structured(mp.StructuredRequest(study_area_id='p', query='{}', evidence_bundle=[], response_schema={'type': 'object', 'properties': {}}))
    provider.generate_criticism(mp.CriticRequest(study_area_id='p', query='q', evidence_bundle=[]))
    assert seen[0] == mp.STRUCTURED_CLI_TIMEOUT_SECONDS == 300.0
    assert seen[1] == 120.0
