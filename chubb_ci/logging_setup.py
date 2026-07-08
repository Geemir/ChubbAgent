"""Loguru configuration (console + rotating file)."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Configure console and optional file logging. Idempotent."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
        "<cyan>{name}</cyan> - {message}",
        colorize=True,
    )
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "chubb_ci_{time:YYYYMMDD}.log",
            level=level,
            rotation="10 MB",
            retention="30 days",
            encoding="utf-8",
        )
