"""
All API endpoints:
  POST   /scrape              — sync scrape (waits for result)
  POST   /jobs                — async job (returns job_id immediately)
  GET    /jobs                — list all jobs
  GET    /jobs/{id}           — poll job status & progress
  GET    /jobs/{id}/results   — get full results when done
  GET    /jobs/{id}/stream    — SSE live stream of results
  GET    /jobs/{id}/export    — download CSV or Excel
  DELETE /jobs/{id}           — cancel / delete job
  GET    /health              — health + pool status
  GET    /metrics             — scraping stats
"""
import json
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import Response, StreamingResponse

from app.models.schemas import (
    ScrapeRequest, ScrapeResponse, JobCreateRequest,
    JobStatusResponse, JobResultResponse,
    HealthResponse, MetricsResponse, ErrorResponse,
)
from app.services.scraper_service import scraper_service
from app.core.browser_manager import browser_pool
from app.core.job_manager import job_manager
from app.core.metrics import metrics
from app.utils.export import leads_to_csv, leads_to_excel
from app.core.logger import get_logger

log = get_logger("api")
router = APIRouter()


# ── Sync scrape ────────────────────────────────────────────────────────────────

@router.post("/scrape", response_model=ScrapeResponse, summary="Synchronous scrape — waits for result")
async def scrape(req: ScrapeRequest):
    log.info("Sync scrape", query=req.query, max=req.max_results)
    try:
        return await scraper_service.run_scrape(req)
    except RuntimeError as e:
        raise HTTPException(503, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Async job system ───────────────────────────────────────────────────────────

@router.post("/jobs", response_model=JobStatusResponse, status_code=202, summary="Submit async job")
async def create_job(req: JobCreateRequest):
    job = job_manager.create_job(
        query=req.query,
        max_results=req.max_results,
        extract_details=req.extract_details,
        webhook_url=req.webhook_url,
    )
    return _job_status(job)


@router.get("/jobs", summary="List all jobs")
async def list_jobs():
    return [_job_status(j) for j in job_manager.list_jobs()]


@router.get("/jobs/{job_id}", response_model=JobStatusResponse, summary="Poll job status")
async def get_job(job_id: str):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    return _job_status(job)


@router.get("/jobs/{job_id}/results", response_model=JobResultResponse, summary="Get full results")
async def get_job_results(job_id: str):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    if job.status not in ("completed","failed"):
        raise HTTPException(202, detail=f"Job still {job.status} ({job.progress}%)")
    return JobResultResponse(
        job_id=job.id, status=job.status, query=job.query,
        total_results=len(job.results), execution_time=job.elapsed(),
        data=job.results, errors=job.errors,
    )


@router.get("/jobs/{job_id}/stream", summary="SSE live stream of results as scraped")
async def stream_job(job_id: str):
    """
    Server-Sent Events stream. Connect and receive each lead as it's found.
    Events: started | result | error | done
    """
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")

    async def event_gen():
        q = job.subscribe()
        try:
            # Replay completed state immediately
            if job.status == "completed":
                for lead in job.results:
                    yield _sse({"type":"result","lead":lead.model_dump(mode="json"),"count":len(job.results)})
                yield _sse({"type":"done","status":"completed","total":len(job.results)})
                return

            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                yield _sse(event)

                if event.get("type") == "done":
                    break
        finally:
            job.unsubscribe(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/jobs/{job_id}/export", summary="Download results as CSV or Excel")
async def export_job(job_id: str, format: str = Query("csv", pattern="^(csv|xlsx)$")):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    if not job.results:
        raise HTTPException(404, detail="No results yet")

    fname = f"leads_{job_id[:8]}_{job.query[:20].replace(' ','_')}"
    if format == "xlsx":
        data = leads_to_excel(job.results)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'},
        )
    else:
        data = leads_to_csv(job.results)
        return Response(
            content=data, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
        )


@router.delete("/jobs/{job_id}", summary="Delete job")
async def delete_job(job_id: str):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    job_manager._jobs.pop(job_id, None)
    return {"deleted": True, "job_id": job_id}


# ── Health & Metrics ───────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health():
    pool = await browser_pool.pool_status()
    active_jobs = sum(1 for j in job_manager.list_jobs() if j.status == "running")
    status = "healthy" if pool.get("active",0) > 0 else "degraded"
    return HealthResponse(status=status, uptime_seconds=metrics.uptime_seconds,
                          browser_pool=pool, active_jobs=active_jobs)


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    pool = await browser_pool.pool_status()
    return MetricsResponse(**metrics.to_dict(), browser_pool_size=pool.get("pool_size",0))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _job_status(job):
    return JobStatusResponse(
        job_id=job.id, status=job.status, query=job.query,
        max_results=job.max_results, progress=job.progress,
        results_so_far=len(job.results), created_at=job.created_at,
        started_at=job.started_at, completed_at=job.completed_at,
        execution_time=job.elapsed(), error=job.errors[-1] if job.errors else None,
        download_url=f"/jobs/{job.id}/export" if job.results else None,
    )

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
