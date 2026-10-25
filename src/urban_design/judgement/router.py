from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
import ipaddress
from .service import JudgementService, RunRequest, ResponseRequest, ReconcileRequest

def create_judgement_router(*, project_store, source_catalog=None, database=None, provider_factory=None, registry=None):
    router=APIRouter(prefix='/api/v1/projects/{project_id}/ariadne/judgements',tags=['judgements'])
    # Lazy setup: application startup does not touch the independent judgement database.
    service=None
    def get_service():
        nonlocal service
        if service is None:
            path=database or Path(project_store.database).with_name('ariadne-judgements.sqlite3')
            service=JudgementService(project_store,path,source_catalog=source_catalog,provider_factory=provider_factory,registry=registry)
        return service
    def invoke(fn,*args,**kwargs):
        try:return fn(*args,**kwargs)
        except KeyError as exc:raise HTTPException(404,'judgement not found') from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    @router.get('')
    def listing(project_id:str,stage:str|None=None,subject_ids:str|None=None,skill_id:str|None=None,subject:str|None=None,language:Literal['zh-TW','en']|None=None):
        ids=(subject_ids or subject)
        return invoke(get_service().list,project_id,stage,ids.split(',') if ids else None,skill_id,language)
    @router.post('')
    def run(project_id:str,request:RunRequest):return invoke(get_service().run,project_id,request)
    @router.get('/inputs')
    def inputs(project_id:str,skill_id:str,subject:str|None=None,subject_ids:str|None=None,language:Literal['zh-TW','en']='zh-TW'):
        request=RunRequest(skill_id=skill_id,subject_ids=(subject_ids or subject).split(',') if (subject_ids or subject) else [],language=language)
        bundle,_previous=invoke(get_service().inputs,project_id,request)
        from .core import digest
        return {**bundle,'input_sha256':digest(bundle)}
    @router.get('/{judgement_id}/attempts')
    def attempts(project_id: str, judgement_id: str, request: Request):
        try:
            local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        if not local:
            raise HTTPException(403, 'local review only')
        return invoke(get_service().attempts, project_id, judgement_id)
    @router.post('/{judgement_id}/reconcile')
    def reconcile(project_id: str, judgement_id: str, body: ReconcileRequest, request: Request):
        if request.client is None or request.client.host != '127.0.0.1':
            raise HTTPException(403, 'local reconciliation only')
        return invoke(get_service().reconcile, project_id, judgement_id, body)
    @router.get('/{judgement_id}')
    def get(project_id:str,judgement_id:str):return invoke(get_service().get,project_id,judgement_id)
    @router.post('/{judgement_id}/responses')
    def response(project_id:str,judgement_id:str,request:ResponseRequest):return invoke(get_service().respond,project_id,judgement_id,request)
    from .proposal_router import create_proposal_router
    combined = APIRouter()
    combined.include_router(router)
    combined.include_router(create_proposal_router(project_store=project_store,
                                                   judgement_service_factory=get_service))
    return combined
