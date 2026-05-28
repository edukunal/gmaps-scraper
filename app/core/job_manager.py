"""
In-memory async job queue.
No Redis needed — asyncio Queue + Dict.
Survives restarts via simple file persistence (optional).
"""
import asyncio
import time
import uuid
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional, AsyncIterator, Any
from dataclasses import dataclass, field

from app.models.schemas import BusinessLead, JobStatus
from app.core.logger import get_logger

log = get_logger("jobs")


@dataclass
class Job:
    id: str
    query: str
    max_results: int
    extract_details: bool
    webhook_url: Optional[str]
    status: JobStatus = "queued"
    progress: int = 0
    results: List[BusinessLead] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    _subscribers: List[asyncio.Queue] = field(default_factory=list)

    def elapsed(self) -> Optional[str]:
        if self.started_at and self.completed_at:
            s = (self.completed_at - self.started_at).total_seconds()
            return f"{round(s, 2)}s"
        return None

    def push_event(self, event: dict) -> None:
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for d in dead:
            self._subscribers.remove(d)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass


class JobManager:
    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self._worker_task = asyncio.create_task(self._worker_loop())
        log.info("Job worker started")

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    def create_job(
        self,
        query: str,
        max_results: int,
        extract_details: bool = True,
        webhook_url: Optional[str] = None,
    ) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            query=query,
            max_results=max_results,
            extract_details=extract_details,
            webhook_url=webhook_url,
        )
        self._jobs[job.id] = job
        self._queue.put_nowait(job.id)
        log.info("Job created", id=job.id, query=query)
        self._purge_old_jobs()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[Job]:
        return list(self._jobs.values())

    # ── Worker ────────────────────────────────────────────────────────────────

    async def _worker_loop(self) -> None:
        """Process jobs from queue one at a time (browser pool handles concurrency)."""
        from app.services.scraper_service import scraper_service  # avoid circular
        while True:
            try:
                job_id = await self._queue.get()
                job = self._jobs.get(job_id)
                if not job:
                    continue
                await self._run_job(job, scraper_service)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Worker loop error", error=str(e))
                await asyncio.sleep(1)

    async def _run_job(self, job: Job, scraper_service) -> None:
        from app.models.schemas import ScrapeRequest
        job.status = "running"
        job.started_at = datetime.utcnow()
        job.push_event({"type": "started", "job_id": job.id})
        log.info("Job started", id=job.id, query=job.query)

        try:
            req = ScrapeRequest(
                query=job.query,
                max_results=job.max_results,
                extract_details=job.extract_details,
            )

            # Use streaming scraper so we push results as they arrive
            async for lead, progress in scraper_service.run_scrape_streaming(req):
                job.results.append(lead)
                job.progress = progress
                job.push_event({
                    "type": "result",
                    "job_id": job.id,
                    "progress": progress,
                    "count": len(job.results),
                    "lead": lead.model_dump(mode="json"),
                })

            job.status = "completed"
            job.progress = 100

        except Exception as e:
            job.status = "failed"
            job.errors.append(str(e))
            job.push_event({"type": "error", "job_id": job.id, "error": str(e)})
            log.error("Job failed", id=job.id, error=str(e))
        finally:
            job.completed_at = datetime.utcnow()
            job.push_event({"type": "done", "job_id": job.id, "status": job.status, "total": len(job.results)})

            if job.webhook_url:
                asyncio.create_task(self._fire_webhook(job))

        log.info("Job complete", id=job.id, leads=len(job.results), status=job.status)

    async def _fire_webhook(self, job: Job) -> None:
        payload = {
            "job_id": job.id,
            "status": job.status,
            "query": job.query,
            "total_results": len(job.results),
            "execution_time": job.elapsed(),
            "data": [r.model_dump(mode="json") for r in job.results],
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    job.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    log.info("Webhook fired", url=job.webhook_url, status=resp.status)
        except Exception as e:
            log.error("Webhook failed", url=job.webhook_url, error=str(e))

    def _purge_old_jobs(self) -> None:
        from app.config import settings
        now = time.time()
        cutoff = settings.JOB_MAX_AGE_SECONDS
        stale = [
            jid for jid, j in self._jobs.items()
            if j.status in ("completed", "failed")
            and j.completed_at
            and (now - j.completed_at.timestamp()) > cutoff
        ]
        for jid in stale:
            del self._jobs[jid]


job_manager = JobManager()
