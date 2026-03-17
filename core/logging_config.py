"""Logging configuration for parser execution."""

from __future__ import annotations

import logging
import os
from pathlib import Path


def setup_logging() -> None:
    """Configure file and console logging."""
    log_file = Path(os.getenv("STORE_PARSER_LOG_FILE", "logs/parser.log"))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_level_name = os.getenv("STORE_PARSER_LOG_LEVEL", "INFO").upper()
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
