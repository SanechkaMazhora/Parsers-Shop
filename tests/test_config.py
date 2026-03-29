from __future__ import annotations

from pathlib import Path

from core.config import (
    DEFAULT_HTTP_RETRIES,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_OUTPUT_PATH,
    get_default_http_retries,
    get_default_http_timeout,
    get_default_log_file,
    get_default_log_level,
    get_default_output_path,
    get_default_snapshot_path,
)
from core.http_client import HttpClient


def test_config_defaults_are_used_when_env_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("STORE_PARSER_OUTPUT", raising=False)
    monkeypatch.delenv("STORE_PARSER_SNAPSHOT", raising=False)
    monkeypatch.delenv("STORE_PARSER_LOG_FILE", raising=False)
    monkeypatch.delenv("STORE_PARSER_LOG_LEVEL", raising=False)
    monkeypatch.delenv("STORE_PARSER_TIMEOUT", raising=False)
    monkeypatch.delenv("STORE_PARSER_RETRIES", raising=False)

    assert get_default_output_path() == DEFAULT_OUTPUT_PATH
    assert get_default_snapshot_path() is None
    assert get_default_log_file() == Path(DEFAULT_LOG_FILE)
    assert get_default_log_level() == DEFAULT_LOG_LEVEL
    assert get_default_http_timeout() == DEFAULT_HTTP_TIMEOUT
    assert get_default_http_retries() == DEFAULT_HTTP_RETRIES


def test_config_invalid_numeric_values_fall_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setenv("STORE_PARSER_TIMEOUT", "bad")
    monkeypatch.setenv("STORE_PARSER_RETRIES", "-1")

    assert get_default_http_timeout() == DEFAULT_HTTP_TIMEOUT
    assert get_default_http_retries() == DEFAULT_HTTP_RETRIES


def test_http_client_uses_env_timeout_and_retries(monkeypatch) -> None:
    monkeypatch.setenv("STORE_PARSER_TIMEOUT", "15")
    monkeypatch.setenv("STORE_PARSER_RETRIES", "2")

    client = HttpClient()
    try:
        https_retry = client.session.adapters["https://"].max_retries
        assert client.timeout == 15
        assert https_retry.total == 2
        assert https_retry.connect == 2
        assert https_retry.read == 2
    finally:
        client.session.close()
