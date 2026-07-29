from __future__ import annotations

import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from tech_desk.api.services import run_pipeline_job
from tech_desk.config import get_settings
from tech_desk.database import init_db

logger = logging.getLogger(__name__)

_pipeline_lock = threading.Lock()


class TechDeskScheduler:
    """Automated scheduling for daily, weekly, and monthly pipelines."""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.settings = get_settings()
        self._started = False

    def _run_pipeline(self, period: str) -> None:
        if not self.settings.openai_api_key:
            logger.error("Cannot run scheduled pipeline: API key not configured")
            return
        if not _pipeline_lock.acquire(blocking=False):
            logger.warning("Skipping scheduled %s pipeline — another run is in progress", period)
            return
        try:
            logger.info("Starting scheduled %s pipeline", period)
            result = run_pipeline_job(period=period, desk_keys=None)  # type: ignore[arg-type]
            logger.info(
                "Scheduled %s pipeline done: %s (%d updates)",
                period,
                result["report"]["title"],
                result["research"]["updates_found"],
            )
        except Exception:
            logger.exception("Scheduled %s pipeline failed", period)
        finally:
            _pipeline_lock.release()

    def start(self) -> BackgroundScheduler:
        if self._started:
            return self.scheduler
        init_db()

        self.scheduler.add_job(
            lambda: self._run_pipeline("daily"),
            CronTrigger(hour=6, minute=0),
            id="daily_pipeline",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.add_job(
            lambda: self._run_pipeline("weekly"),
            CronTrigger(day_of_week="mon", hour=7, minute=0),
            id="weekly_pipeline",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.add_job(
            lambda: self._run_pipeline("monthly"),
            CronTrigger(day=1, hour=8, minute=0),
            id="monthly_pipeline",
            replace_existing=True,
            max_instances=1,
        )

        self.scheduler.start()
        self._started = True
        logger.info("Scheduler started (daily 06:00, weekly Mon 07:00, monthly 1st 08:00 UTC)")
        return self.scheduler

    def stop(self) -> None:
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False
