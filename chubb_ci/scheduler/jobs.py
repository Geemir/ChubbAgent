"""Register and run the daily / weekly cron jobs.

In-process APScheduler keeps the MVP to a single container. Each job wraps a full
pipeline run and never lets an exception kill the scheduler.
"""

from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from chubb_ci.config.settings import Settings, get_settings
from chubb_ci.pipeline import run_daily, run_weekly


def _safe(fn, label: str):
    def _wrapped() -> None:
        logger.info("scheduled job start: {}", label)
        try:
            fn()
            logger.info("scheduled job done: {}", label)
        except Exception as exc:  # noqa: BLE001 - keep scheduler alive
            logger.exception("scheduled job failed: {} ({})", label, exc)

    return _wrapped


def build_scheduler(settings: Settings | None = None) -> BlockingScheduler:
    settings = settings or get_settings()
    scheduler = BlockingScheduler(timezone=settings.timezone)

    scheduler.add_job(
        _safe(lambda: run_daily(settings), "daily"),
        CronTrigger.from_crontab(settings.daily_cron, timezone=settings.timezone),
        id="daily", name="daily-digest", replace_existing=True,
    )
    scheduler.add_job(
        _safe(lambda: run_weekly(settings), "weekly"),
        CronTrigger.from_crontab(settings.weekly_cron, timezone=settings.timezone),
        id="weekly", name="weekly-report", replace_existing=True,
    )
    logger.info(
        "scheduler configured: daily='{}' weekly='{}' tz={}",
        settings.daily_cron, settings.weekly_cron, settings.timezone,
    )
    return scheduler


def run_scheduler(settings: Settings | None = None) -> None:
    scheduler = build_scheduler(settings)
    logger.info("starting scheduler (Ctrl+C to stop)")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):  # pragma: no cover
        logger.info("scheduler stopped")
