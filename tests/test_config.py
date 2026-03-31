from __future__ import annotations

from pathlib import Path

from core.config import (
    DEFAULT_HTTP_RETRIES,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_KB_BASE_URL,
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MARIA_RA_BASE_URL,
    DEFAULT_MARIA_RA_MAP_URL,
    DEFAULT_MONETKA_BASE_URL,
    DEFAULT_OUTPUT_PATH,
    get_default_http_retries,
    get_default_http_timeout,
    get_default_log_file,
    get_default_log_level,
    get_default_output_path,
    get_default_snapshot_path,
    get_kb_base_url,
    get_maria_ra_base_url,
    get_maria_ra_map_url,
    get_monetka_base_url,
)
from core.http_client import HttpClient
from parsers.kb_parser import KBParser
from parsers.maria_ra_parser import MariaRaParser
from parsers.monetka_parser import MonetkaParser


def test_config_defaults_are_used_when_env_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("STORE_PARSER_OUTPUT", raising=False)
    monkeypatch.delenv("STORE_PARSER_SNAPSHOT", raising=False)
    monkeypatch.delenv("STORE_PARSER_LOG_FILE", raising=False)
    monkeypatch.delenv("STORE_PARSER_LOG_LEVEL", raising=False)
    monkeypatch.delenv("STORE_PARSER_TIMEOUT", raising=False)
    monkeypatch.delenv("STORE_PARSER_RETRIES", raising=False)
    monkeypatch.delenv("STORE_PARSER_KB_BASE_URL", raising=False)
    monkeypatch.delenv("STORE_PARSER_MONETKA_BASE_URL", raising=False)
    monkeypatch.delenv("STORE_PARSER_MARIA_RA_BASE_URL", raising=False)
    monkeypatch.delenv("STORE_PARSER_MARIA_RA_MAP_URL", raising=False)

    assert get_default_output_path() == DEFAULT_OUTPUT_PATH
    assert get_default_snapshot_path() is None
    assert get_default_log_file() == Path(DEFAULT_LOG_FILE)
    assert get_default_log_level() == DEFAULT_LOG_LEVEL
    assert get_default_http_timeout() == DEFAULT_HTTP_TIMEOUT
    assert get_default_http_retries() == DEFAULT_HTTP_RETRIES
    assert get_kb_base_url() == DEFAULT_KB_BASE_URL
    assert get_monetka_base_url() == DEFAULT_MONETKA_BASE_URL
    assert get_maria_ra_base_url() == DEFAULT_MARIA_RA_BASE_URL
    assert get_maria_ra_map_url() == DEFAULT_MARIA_RA_MAP_URL


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


def test_source_url_overrides_are_normalized(monkeypatch) -> None:
    monkeypatch.setenv("STORE_PARSER_KB_BASE_URL", " https://kb.example.local/ ")
    monkeypatch.setenv("STORE_PARSER_MONETKA_BASE_URL", " https://monetka.example.local/ ")
    monkeypatch.setenv("STORE_PARSER_MARIA_RA_BASE_URL", " https://maria.example.local/ ")
    monkeypatch.setenv("STORE_PARSER_MARIA_RA_MAP_URL", " https://maria.example.local/custom-map ")

    assert get_kb_base_url() == "https://kb.example.local"
    assert get_monetka_base_url() == "https://monetka.example.local"
    assert get_maria_ra_base_url() == "https://maria.example.local"
    assert get_maria_ra_map_url() == "https://maria.example.local/custom-map/"


def test_parsers_read_source_url_overrides_from_config(monkeypatch) -> None:
    monkeypatch.setenv("STORE_PARSER_KB_BASE_URL", "https://kb.example.local/")
    monkeypatch.setenv("STORE_PARSER_MONETKA_BASE_URL", "https://monetka.example.local/")
    monkeypatch.setenv("STORE_PARSER_MARIA_RA_BASE_URL", "https://maria.example.local/")
    monkeypatch.setenv("STORE_PARSER_MARIA_RA_MAP_URL", "https://maria.example.local/custom-map")

    kb_parser = KBParser(client=None)
    monetka_parser = MonetkaParser(client=None)
    maria_ra_parser = MariaRaParser(client=None)

    assert kb_parser.base_url == "https://kb.example.local"
    assert kb_parser._city_endpoint_candidates == (
        "https://kb.example.local/api/cities/list/",
        "https://kb.example.local/api/cities/list",
    )
    assert monetka_parser.base_url == "https://monetka.example.local"
    assert monetka_parser.seed_urls == ("https://monetka.example.local/shops_map/",)
    assert maria_ra_parser.base_url == "https://maria.example.local"
    assert maria_ra_parser.map_url == "https://maria.example.local/custom-map/"
