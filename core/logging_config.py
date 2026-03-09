"""Logging configuration for parser execution."""

from __future__ import annotations

import logging
from pathlib import Path


def setup_logging() -> None:
    """Configure file and console logging."""
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        force=True,
        handlers=[
            logging.FileHandler(logs_dir / "parser.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
