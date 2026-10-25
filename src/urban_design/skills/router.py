"""Skill jobs run through the existing workspace store, never a new service."""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from urban_design.store import EntityNotFoundError
from .contracts import RunRequest
from .runner import SkillConflict, SkillRunner


def create_skills_router(store, *, runner=None):
    # Defer job-table creation until the skill API is actually used.
    from threading import RLock
    lock = RLock()
    def get_runner():
        nonlocal runner
        with lock:
            if runner is None:
                runner = SkillRunner(store)
            return runner
    router = APIRouter(prefix='/api/v1/scenarios/{scenario_id}/skills/{skill_id}')

    @router.post('/runs', status_code=202)
    def submit(scenario_id: str, skill_id: str, body: RunRequest, tasks: BackgroundTasks):
        try:
            job, created = get_runner().submit(scenario_id, skill_id, body)
        except EntityNotFoundError as exc:
            raise HTTPException(404, 'scenario not found') from exc
        except SkillConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if created:
            tasks.add_task(get_runner().execute, job['run_id'])
        return job

    @router.get('/runs/{run_id}')
    def get(scenario_id: str, skill_id: str, run_id: str):
        try:
            return get_runner().get(scenario_id, skill_id, run_id)
        except EntityNotFoundError as exc:
            raise HTTPException(404, 'skill run not found') from exc
        except (SkillConflict, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
    return router
