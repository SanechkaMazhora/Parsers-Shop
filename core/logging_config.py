"""Logging configuration for parser execution."""

from __future__ import annotations

import logging

from core.config import get_default_log_file, get_default_log_level


def setup_logging() -> None:
    """Configure file and console logging."""
    log_file = get_default_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_level_name = get_default_log_level()
    log_level = getattr(logging, log_level_name, logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        force=True,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    # Retry internals are too noisy for operational logs; parsers emit final handled failures themselves.
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
    logging.getLogger("urllib3.util.retry").setLevel(logging.ERROR)
