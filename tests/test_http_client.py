from __future__ import annotations

import logging

import pytest
from requests import HTTPError, Response

from core.http_client import HttpClient


def test_http_client_logs_request_failures_at_debug(monkeypatch, caplog) -> None:
    client = HttpClient()

    def fake_get(url: str, **kwargs):  # type: ignore[no-untyped-def]
        response = Response()
        response.status_code = 404
        response.url = url
        raise HTTPError("404 Client Error: Not Found", response=response)

    monkeypatch.setattr(client.session, "get", fake_get)

    try:
        with caplog.at_level(logging.DEBUG, logger="core.http_client"):
            with pytest.raises(HTTPError):
                client.get_text("https://www.monetka.ru/missing")
    finally:
        client.session.close()

    assert any(
        record.levelno == logging.DEBUG and "HTTP text request failed" in record.message
        for record in caplog.records
    )
    assert not any(record.levelno >= logging.ERROR for record in caplog.records)
