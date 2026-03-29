"""Minimal configuration helpers backed by environment variables."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_OUTPUT_PATH = "output/stores.xlsx"
DEFAULT_LOG_FILE = "logs/parser.log"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_HTTP_TIMEOUT = 20
DEFAULT_HTTP_RETRIES = 3


def _get_int_env(name: str, default: int, *, min_value: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    if parsed < min_value:
        return default
    return parsed


def get_default_output_path() -> str:
    """Resolve workbook path from environment or fallback default."""
    return os.getenv("STORE_PARSER_OUTPUT", DEFAULT_OUTPUT_PATH)


def get_default_snapshot_path() -> str | None:
    """Resolve optional snapshot path from environment."""
    snapshot_path = os.getenv("STORE_PARSER_SNAPSHOT")
    return snapshot_path or None


def get_default_log_file() -> Path:
    """Resolve log file path from environment or fallback default."""
    return Path(os.getenv("STORE_PARSER_LOG_FILE", DEFAULT_LOG_FILE))


def get_default_log_level() -> str:
    """Resolve log level from environment or fallback default."""
    return os.getenv("STORE_PARSER_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()


def get_default_http_timeout() -> int:
    """Resolve HTTP timeout in seconds from environment."""
    return _get_int_env("STORE_PARSER_TIMEOUT", DEFAULT_HTTP_TIMEOUT, min_value=1)


def get_default_http_retries() -> int:
    """Resolve HTTP retry count from environment."""
    return _get_int_env("STORE_PARSER_RETRIES", DEFAULT_HTTP_RETRIES, min_value=0)
