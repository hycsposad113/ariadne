"""E2 proposal/readiness/execution API; human decisions stay in the existing API."""
import json
from pathlib import Path
import sqlite3
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from .e2_service import E2Plan, StrictModel, publish_plan, readiness, simulate, read_result, validate_methods, find_method_validation
from .weather_snapshot import E2Blocked, bound_approval, checked_artifact, load_weather, publish_candidate01

router = APIRouter(prefix="/api/v1/environment/e2", tags=["environment-e2"])


class PublishWeatherRequest(StrictModel):
    project_id: str = Field(min_length=1)


class ValidateMethodsRequest(StrictModel):
    project_id: str = Field(min_length=1)


class ExecutionRequest(StrictModel):
    project_id: str = Field(min_length=1)
    plan_artifact_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class CompareRequest(StrictModel):
    project_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    comparison: str = "direction"


def store_and_root(request):
    store = request.app.state.project_store
    # Configured by the host; no caller-controlled filesystem paths.
    root = Path(getattr(request.app.state, "e2_artifact_root", Path(store.database).parent / "e2-artifacts"))
    return store, root


def blocked(exc):
    raise HTTPException(status_code=409, detail={"status": "BLOCKED", "reason": str(exc)}) from exc


@router.post("/weather/snapshots", status_code=201)
def weather_proposal(payload: PublishWeatherRequest, request: Request):
    store, root = store_and_root(request)
    proposal = getattr(request.app.state, "e2_weather_proposal_root", None)
    source = getattr(request.app.state, "e2_weather_source_root", None)
    if proposal is None or source is None:
        blocked(E2Blocked("WEATHER_SOURCE_PATHS_NOT_CONFIGURED"))
    try:
        record = publish_candidate01(store, payload.project_id, Path(proposal), Path(source), root)
        return {"snapshot_id": record.entity_id, "status": "PROPOSED", "version": record.payload["version"],
                "payload_digest": record.payload["payload_digest"], "decision_target_type": "DatasetSnapshot"}
    except (ValueError, KeyError, OSError) as exc:
        blocked(exc)


@router.get("/weather/snapshots")
def list_weather_snapshots(project_id: str, request: Request):
    store, _ = store_and_root(request)
    try:
        records = store.list_current("DatasetSnapshot", project_id=project_id)
    except Exception:
        return []
    snapshots = []
    for record in records:
        if not (record.entity_id.startswith("snapshot-e2-weather-") or record.payload.get("version") == "weather-derived-method-v1"):
            continue
        digest = record.payload.get("payload_digest")
        decision_id = None
        status = "PROPOSED"
        if digest:
            try:
                decision_id = bound_approval(store, record, digest)
                status = "APPROVED"
            except Exception:
                status = "PROPOSED"
        snapshots.append({
            "id": record.entity_id,
            "snapshot_id": record.entity_id,
            "version": record.payload.get("version", ""),
            "payload_digest": digest,
            "status": status,
            "decision_id": decision_id,
            "decision_target_type": "DatasetSnapshot",
            "created_at": record.payload.get("retrieved_at"),
        })
    return snapshots


@router.get("/weather/snapshots/{snapshot_id}")
def weather_status(snapshot_id: str, project_id: str, request: Request):
    store, _ = store_and_root(request)
    try:
        record, _, _, decision = load_weather(store, snapshot_id, project_id)
        return {"snapshot_id": record.entity_id, "status": "approved", "decision_id": decision, "payload_digest": record.payload["payload_digest"]}
    except (ValueError, KeyError, OSError) as exc:
        blocked(exc)


@router.post("/weather/snapshots/{snapshot_id}/validate-methods")
def validate_snapshot_methods(snapshot_id: str, payload: ValidateMethodsRequest, request: Request):
    store, root = store_and_root(request)
    try:
        weather, bundle, epw, decision = load_weather(store, snapshot_id, payload.project_id, require_approval=True)
        existing = find_method_validation(store, payload.project_id, snapshot_id, weather=weather, bundle=bundle)
        if existing is not None:
            return {"method_validation_artifact_id": existing.entity_id}
        record = validate_methods(store, payload.project_id, snapshot_id, root / "qualification")
        return {"method_validation_artifact_id": record.entity_id}
    except (ValueError, KeyError, OSError) as exc:
        blocked(exc)


@router.post("/plan", status_code=201)
def propose_plan(payload: E2Plan, request: Request):
    store, root = store_and_root(request)
    try:
        record = publish_plan(store, payload, root)
        return {"plan_artifact_id": record.entity_id, "status": "PROPOSED", "version": str(record.revision), "sha256": record.payload["sha256"], "plan": payload.model_dump(mode="json")}
    except (ValueError, KeyError, OSError) as exc:
        blocked(exc)


@router.get("/plans")
def list_plans(project_id: str, request: Request):
    store, _ = store_and_root(request)
    try:
        records = store.list_current("Artifact", project_id=project_id)
    except Exception:
        return []
    plans = []
    for record in records:
        if record.payload.get("type") != "experiment-plan" and not record.entity_id.startswith("artifact-e2-experiment-plan-"):
            continue
        sha = record.payload.get("sha256")
        decision_id = None
        status = "PROPOSED"
        if sha:
            try:
                decision_id = bound_approval(store, record, sha)
                status = "APPROVED"
            except Exception:
                status = "PROPOSED"
        baseline = None
        modified = None
        plan_dict = None
        try:
            raw = Path(record.payload["uri"]).read_bytes()
            plan_obj = E2Plan.model_validate_json(raw)
            plan_dict = plan_obj.model_dump(mode="json")
            baseline = plan_dict.get("baseline")
            modified = plan_dict.get("modified")
        except Exception:
            pass
        plans.append({
            "id": record.entity_id,
            "plan_artifact_id": record.entity_id,
            "sha256": sha,
            "version": str(record.revision),
            "status": status,
            "decision_id": decision_id,
            "baseline": baseline,
            "modified": modified,
            "plan": plan_dict,
            "created_at": record.payload.get("created_at"),
        })
    return plans


@router.get("/plan/{plan_id}")
def get_plan(plan_id: str, project_id: str, request: Request):
    from .weather_snapshot import checked_artifact
    import json
    store, _ = store_and_root(request)
    try:
        record, raw = checked_artifact(store, plan_id, project_id)
        return {"plan_artifact_id": record.entity_id, "sha256": record.payload["sha256"], "plan": E2Plan.model_validate_json(raw).model_dump(mode="json")}
    except (ValueError, KeyError, OSError) as exc:
        blocked(exc)


@router.get("/readiness")
def get_readiness(plan_artifact_id: str, project_id: str, request: Request):
    store, _ = store_and_root(request)
    return readiness(store, plan_artifact_id, project_id)


@router.post("/simulate")
def simulate_plan(payload: ExecutionRequest, request: Request):
    store, _ = store_and_root(request)
    try:
        return simulate(store, payload.plan_artifact_id, payload.project_id, payload.idempotency_key, getattr(request.app.state, "e2_job_database", None))
    except (ValueError, KeyError, OSError) as exc:
        blocked(exc)


@router.get("/results/{job_id}/summary")
def result_summary(job_id: str, project_id: str, request: Request):
    """Same verified result without per-point arrays (the full payload is ~60 MB); read-only."""
    store, _ = store_and_root(request)
    try:
        full = read_result(store, job_id, project_id, getattr(request.app.state, "e2_job_database", None))
    except (ValueError, KeyError, OSError) as exc:
        blocked(exc)
    summary = {key: value for key, value in full.items() if key != "results"}
    summary["comparisons"] = {
        method: {offset: {k: v for k, v in row.items() if not isinstance(v, (list, dict))} for offset, row in offsets.items()}
        for method, offsets in (full.get("comparisons") or {}).items()
    }
    summary["summary_of_full_result"] = True
    return summary


@router.get("/results/{job_id}")
def result(job_id: str, project_id: str, request: Request):
    store, _ = store_and_root(request)
    try:
        return read_result(store, job_id, project_id, getattr(request.app.state, "e2_job_database", None))
    except (ValueError, KeyError, OSError) as exc:
        blocked(exc)


@router.get("/jobs")
def list_jobs(project_id: str, request: Request):
    store, _ = store_and_root(request)
    job_db = getattr(request.app.state, "e2_job_database", None)
    path = Path(job_db) if job_db else Path(store.database).with_name("e2-jobs.sqlite3")
    if not path.is_file():
        return []
    try:
        try:
            connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT job_id, project_id, status, created_at, updated_at, request_json FROM generation_jobs WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            connection = sqlite3.connect(str(path.resolve()), timeout=5)
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT job_id, project_id, status, created_at, updated_at, request_json FROM generation_jobs WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
    except Exception:
        return []

    try:
        jobs = []
        out_dir = path.with_suffix("") / "out"
        for row in rows:
            req = {}
            try:
                req = json.loads(row["request_json"])
            except Exception:
                pass
            plan_id = req.get("plan_id")
            base_scenario_id = None
            mod_scenario_id = None
            if plan_id:
                try:
                    p_rec = store.current(plan_id)
                    p_raw = Path(p_rec.payload["uri"]).read_bytes()
                    p_data = json.loads(p_raw)
                    base_scenario_id = p_data.get("baseline", {}).get("scenario_id")
                    mod_scenario_id = p_data.get("modified", {}).get("scenario_id")
                except Exception:
                    pass
            validated = False
            res_path = out_dir / row["job_id"] / "result.json"
            if res_path.is_file():
                try:
                    res_obj = json.loads(res_path.read_bytes())
                    validated = (res_obj.get("evidence_validation_status") == "validated")
                except Exception:
                    validated = False
            status_val = row["status"]
            completed_at = row["updated_at"] if status_val in ("READY", "FAILED", "CANCELLED", "INTERRUPTED", "OUTCOME_UNKNOWN") else None
            jobs.append({
                "id": row["job_id"],
                "job_id": row["job_id"],
                "status": status_val,
                "created_at": row["created_at"],
                "completed_at": completed_at,
                "updated_at": row["updated_at"],
                "plan_id": plan_id,
                "baseline_scenario_id": base_scenario_id,
                "modified_scenario_id": mod_scenario_id,
                "validated": validated,
            })
        return jobs
    finally:
        connection.close()


@router.post("/compare")
def compare(payload: CompareRequest, request: Request):
    if payload.comparison != "direction":
        blocked(E2Blocked("CROSS_METHOD_ABSOLUTE_COMPARISON_FORBIDDEN"))
    response = result(payload.job_id, payload.project_id, request)
    return {"job_id": payload.job_id, "status": response["status"], "comparisons_within_method": response.get("comparisons"),
            "direction_summary": response.get("direction_summary")}


@router.post('/harbour/register', status_code=201)
def register_harbour_scenario(payload: PublishWeatherRequest, request: Request):
    """Register the pinned fabric as draft geometry; no human decision here."""
    from .harbour_registration import register_harbour
    store, root = store_and_root(request)
    try:
        return register_harbour(store, payload.project_id, root / 'harbour')
    except (ValueError, KeyError, OSError) as exc:
        blocked(exc)


@router.get('/scenarios/{scenario_id}/pin')
def get_scenario_pin(scenario_id: str, project_id: str, request: Request):
    from .harbour_registration import scenario_pin
    store, _ = store_and_root(request)
    try:
        data = scenario_pin(store, scenario_id, project_id).model_dump(mode='json')
        try:
            scenario = store.current(scenario_id)
            data['status'] = scenario.payload.get('status', 'accepted')
        except Exception:
            data['status'] = 'accepted'
        return data
    except (ValueError, KeyError, OSError) as exc:
        blocked(exc)

