"""Project logging helpers for consistent console output."""
from __future__ import annotations

import logging
import os

_LOG_LEVEL_ENV = "HPA_MDO_LOG_LEVEL"
_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_LOG_FORMAT = "[%(levelname)s] %(name)s: %(message)s"


def _resolve_level(level_name: str) -> int:
    """Convert a level name into a stdlib logging level."""
    return getattr(logging, level_name.upper(), logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for HPA-MDO modules."""
    logger = logging.getLogger(name)
    level_name = os.getenv(_LOG_LEVEL_ENV, _DEFAULT_LOG_LEVEL)
    level = _resolve_level(level_name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_DEFAULT_LOG_FORMAT))
        logger.addHandler(handler)

    logger.propagate = False
    return logger
