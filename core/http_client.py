"""HTTP client helper with retries and robust response parsing."""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry

from core.config import get_default_http_retries, get_default_http_timeout


class HttpClient:
    """Small wrapper around requests.Session with retry support."""

    def __init__(self, timeout: int | None = None, retries: int | None = None) -> None:
        self.timeout = timeout if timeout is not None else get_default_http_timeout()
        resolved_retries = retries if retries is not None else get_default_http_retries()
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            }
        )
        retry = Retry(
            total=resolved_retries,
            connect=resolved_retries,
            read=resolved_retries,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get_text(self, url: str, **kwargs: Any) -> str:
        """Load URL and return response text."""
        text, _final_url = self.get_text_with_final_url(url, **kwargs)
        return text

    def get_text_with_final_url(self, url: str, **kwargs: Any) -> tuple[str, str]:
        """Load URL and return response text plus the final response URL."""
        timeout = kwargs.pop("timeout", self.timeout)
        try:
            response = self.session.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response.text, response.url
        except RequestException as exc:
            self.logger.debug("HTTP text request failed: %s: %s", url, exc)
            raise

    def get_json(self, url: str, **kwargs: Any) -> Any:
        """Load URL and decode JSON response."""
        timeout = kwargs.pop("timeout", self.timeout)
        try:
            response = self.session.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response.json()
        except ValueError as exc:
            self.logger.error("Invalid JSON response from %s: %s", url, exc)
            raise
        except RequestException as exc:
            self.logger.debug("HTTP JSON request failed: %s: %s", url, exc)
            raise
