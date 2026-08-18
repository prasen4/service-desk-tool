from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    job_type: str
    status: JobStatus = JobStatus.PENDING
    message: str = "Queued"
    progress: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_type": self.job_type,
            "status": self.status.value,
            "message": self.message,
            "progress": self.progress,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
        }


def _persist(job: Job) -> None:
    """Write-through a job's current state to the DB so the Activity view
    survives process restarts/redeploys (the in-memory dict alone does not).
    Never let telemetry persistence take down a running job.
    """
    try:
        from tech_desk.database import JobORM, get_session_factory

        session = get_session_factory()()
        try:
            session.merge(
                JobORM(
                    id=job.id,
                    job_type=job.job_type,
                    status=job.status.value,
                    message=job.message,
                    progress=job.progress,
                    created_at=job.created_at.replace(tzinfo=None),
                    completed_at=job.completed_at.replace(tzinfo=None) if job.completed_at else None,
                    result_json=json.dumps(job.result) if job.result is not None else None,
                    error=job.error,
                )
            )
            session.commit()
        finally:
            session.close()
    except Exception:
        logger.debug("Job persistence skipped for %s", job.id, exc_info=True)


def _job_from_orm(orm: "Any") -> Job:
    return Job(
        id=orm.id,
        job_type=orm.job_type,
        status=JobStatus(orm.status),
        message=orm.message,
        progress=orm.progress,
        created_at=orm.created_at.replace(tzinfo=timezone.utc),
        completed_at=orm.completed_at.replace(tzinfo=timezone.utc) if orm.completed_at else None,
        result=json.loads(orm.result_json) if orm.result_json else None,
        error=orm.error,
    )


def _load_recent_from_db(limit: int = 100) -> list[Job]:
    try:
        from tech_desk.database import JobORM, get_session_factory

        session = get_session_factory()()
        try:
            rows = session.query(JobORM).order_by(JobORM.created_at.desc()).limit(limit).all()
            return [_job_from_orm(r) for r in rows]
        finally:
            session.close()
    except Exception:
        logger.debug("Could not load job history from DB", exc_info=True)
        return []


class JobManager:
    """In-process background job runner for long-running pipeline tasks."""

    def __init__(self, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="techdesk")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._running = False

    def start(self) -> None:
        self._running = True
        # Rehydrate recent job history from the DB so the Activity view isn't
        # empty right after a restart/redeploy.
        for job in _load_recent_from_db(limit=100):
            self._jobs.setdefault(job.id, job)

    def shutdown(self) -> None:
        self._running = False
        self._executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, job_type: str, fn: Callable[..., dict[str, Any]], **kwargs) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, job_type=job_type)
        with self._lock:
            self._jobs[job_id] = job
            # Keep last 100 jobs in memory (DB retains full history)
            if len(self._jobs) > 100:
                oldest = sorted(self._jobs.values(), key=lambda j: j.created_at)[:20]
                for old in oldest:
                    self._jobs.pop(old.id, None)
        _persist(job)

        def _progress(message: str, progress: int) -> None:
            self._update(job_id, message=message, progress=min(progress, 99))

        def _run() -> None:
            self._update(job_id, status=JobStatus.RUNNING, message="Starting...", progress=1)
            try:
                result = fn(progress=_progress, **kwargs)
                self._update(
                    job_id,
                    status=JobStatus.COMPLETED,
                    message="Complete",
                    progress=100,
                    result=result,
                    completed_at=datetime.now(timezone.utc),
                )
                logger.info("Job %s (%s) completed", job_id, job_type)
            except Exception as exc:
                logger.exception("Job %s (%s) failed", job_id, job_type)
                self._update(
                    job_id,
                    status=JobStatus.FAILED,
                    message="Failed",
                    error=str(exc),
                    completed_at=datetime.now(timezone.utc),
                )

        self._executor.submit(_run)
        return job_id

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            snapshot = job
        _persist(snapshot)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job:
            return job
        # Not in the in-memory cache (e.g. right after a restart) — fall back to the DB.
        from tech_desk.database import JobORM, get_session_factory

        session = get_session_factory()()
        try:
            orm = session.get(JobORM, job_id)
            return _job_from_orm(orm) if orm else None
        finally:
            session.close()

    def list_recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return jobs[:limit]


job_manager = JobManager()
