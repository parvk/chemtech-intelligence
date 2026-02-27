from datetime import datetime, UTC
from fastapi import APIRouter, HTTPException, Header
from celery.result import AsyncResult

from app.core.logging import get_logger
from app.models.job import JobStatus, JobStatusResponse, SynthesisPlanRequest, SynthesisPlanResult
from app.workers.celery_app import celery_app
from app.workers.synthesis_worker import run_synthesis_plan

router = APIRouter(prefix="/synthesis", tags=["Synthesis Planning"])
logger = get_logger(__name__)

STATUS_PROGRESS_MAP = {
    JobStatus.RESOLVING: 5,
    JobStatus.INFERRING: 15,
    JobStatus.SCORING: 60,
    JobStatus.RANKING: 75,
    JobStatus.EXPLAINING: 80,
    JobStatus.ASSEMBLING: 95,
    JobStatus.COMPLETED: 100,
    JobStatus.FAILED: 0,
}


@router.post("/plan", status_code=202)
async def submit_synthesis_plan(
    request: SynthesisPlanRequest,
    x_tenant_id: str = Header(..., description="Tenant identifier for data isolation"),
) -> dict:
    """
    Submit a synthesis planning job. Returns a job_id immediately.
    Poll /synthesis/jobs/{job_id} for status, then /synthesis/jobs/{job_id}/result for output.
    """
    request.tenant_id = x_tenant_id
    task = run_synthesis_plan.delay(request.model_dump(mode="json"))
    logger.info("synthesis_job_submitted", job_id=task.id, tenant_id=x_tenant_id)
    return {"job_id": task.id, "status": JobStatus.PENDING, "message": "Job submitted"}


@router.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    """Poll synthesis job status."""
    result = AsyncResult(job_id, app=celery_app)

    if result.state == "PENDING":
        return JobStatusResponse(
            job_id=job_id,
            status=JobStatus.PENDING,
            stage_label="Queued",
            progress_pct=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    if result.state == "PROGRESS":
        meta = result.info or {}
        status = JobStatus(meta.get("status", JobStatus.PENDING.value))
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            stage_label=meta.get("stage_label", ""),
            progress_pct=meta.get("progress_pct", 0),
            created_at=datetime.now(UTC),
            updated_at=datetime.fromisoformat(meta.get("updated_at", datetime.now(UTC).isoformat())),
        )

    if result.state == "SUCCESS":
        return JobStatusResponse(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            stage_label="Completed",
            progress_pct=100,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    if result.state == "FAILURE":
        return JobStatusResponse(
            job_id=job_id,
            status=JobStatus.FAILED,
            stage_label="Failed",
            progress_pct=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            error=str(result.info),
        )

    raise HTTPException(status_code=500, detail=f"Unexpected job state: {result.state}")


@router.get("/jobs/{job_id}/result", response_model=SynthesisPlanResult)
async def get_job_result(job_id: str) -> SynthesisPlanResult:
    """Retrieve completed synthesis plan result."""
    result = AsyncResult(job_id, app=celery_app)

    if result.state != "SUCCESS":
        raise HTTPException(
            status_code=404 if result.state == "PENDING" else 400,
            detail=f"Result not available. Job status: {result.state}",
        )

    return SynthesisPlanResult(**result.result)
