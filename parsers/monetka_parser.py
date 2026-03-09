"""Parser for Monetka stores (HTML pages)."""

from __future__ import annotations

import logging
import re
from collections import deque
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from core.http_client import HttpClient
from core.models import StoreRecord


class MonetkaParser:
    """Parse stores from Monetka website by traversing city and store pages."""

    NETWORK_NAME = "Монетка"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.base_url = "https://www.monetka.ru"
        self.seed_urls = (
            f"{self.base_url}/shops_map/",
            f"{self.base_url}/urfo/shops_map",
        )

    def parse(self) -> list[StoreRecord]:
        """Collect store pages and normalize parsed content."""
        stores: list[StoreRecord] = []
        city_pages = self._collect_city_pages()
        self.logger.info("Monetka: loaded %s city pages", len(city_pages))

        store_urls: set[str] = set()
        for city_url in city_pages:
            try:
                for store_url in self._collect_store_links_for_city(city_url):
                    store_urls.add(store_url)
            except Exception as exc:
                self.logger.warning("Monetka: failed collecting stores for city page %s: %s", city_url, exc)

        self.logger.info("Monetka: loaded %s unique store pages", len(store_urls))
        for store_url in sorted(store_urls):
            try:
                html = self.client.get_text(store_url)
                stores.append(self._parse_store_page(html, store_url))
            except Exception as exc:
                self.logger.warning("Monetka: failed store page %s: %s", store_url, exc)
        return stores

    def _collect_city_pages(self) -> list[str]:
        result: set[str] = set()
        for url in self.seed_urls:
            for candidate_url in self._seed_candidates(url):
                try:
                    html = self.client.get_text(candidate_url)
                except Exception as exc:
                    self.logger.info("Monetka: seed unavailable %s: %s", candidate_url, exc)
                    continue
                for link in self._extract_city_links(html, candidate_url):
                    result.add(link)
        return sorted(result)

    @staticmethod
    def _seed_candidates(url: str) -> tuple[str, str, str]:
        normalized = url.rstrip("/")
        return (normalized + "/", normalized + "/list", normalized + "/list/")

    def _collect_store_links_for_city(self, city_url: str) -> set[str]:
        """Collect store links from city page and pagination if present."""
        queue: deque[str] = deque([city_url])
        visited: set[str] = set()
        stores: set[str] = set()
        max_pages = 20

        while queue and len(visited) < max_pages:
            page_url = queue.popleft()
            if page_url in visited:
                continue
            visited.add(page_url)
            try:
                html = self.client.get_text(page_url)
            except Exception as exc:
                self.logger.warning("Monetka: failed city/pagination page %s: %s", page_url, exc)
                continue

            for store_link in self._extract_store_links(html, page_url):
                stores.add(store_link)
            for next_page in self._extract_pagination_links(html, page_url):
                if next_page not in visited:
                    queue.append(next_page)
        return stores

    def _extract_city_links(self, html: str, base_url: str) -> Iterable[str]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        for href in self._iter_hrefs(soup):
            absolute = urljoin(base_url, href)
            path = urlparse(absolute).path.rstrip("/")
            if not path or "/shops_map" not in path:
                continue
            if self._is_store_path(path):
                continue
            parts = [part for part in path.split("/") if part]
            if len(parts) < 2:
                continue
            if absolute not in seen:
                seen.add(absolute)
                yield absolute

    def _extract_store_links(self, html: str, base_url: str) -> Iterable[str]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        for href in self._iter_hrefs(soup):
            absolute = urljoin(base_url, href)
            path = urlparse(absolute).path
            if self._is_store_path(path) and absolute not in seen:
                seen.add(absolute)
                yield absolute

    def _extract_pagination_links(self, html: str, base_url: str) -> Iterable[str]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        for href in self._iter_hrefs(soup):
            absolute = urljoin(base_url, href)
            if absolute == base_url:
                continue
            if "page=" in absolute or "/page/" in absolute:
                if absolute not in seen:
                    seen.add(absolute)
                    yield absolute

    def _parse_store_page(self, html: str, url: str) -> StoreRecord:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n", strip=True)

        details = self._extract_details_from_dl(soup)
        address = details.get("address") or self._extract_label_value(text, ("Адрес", "Почтовый адрес"))
        work_time = details.get("work_time") or self._extract_label_value(text, ("Режим работы", "Время работы"))
        store_format = details.get("store_format") or self._extract_label_value(text, ("Формат магазина",))
        phone = details.get("phone") or self._extract_phone(text)
        city, region = self._extract_city_region(soup, url)

        return StoreRecord.build(
            network=self.NETWORK_NAME,
            region=region,
            city=city,
            address=address,
            work_time=work_time,
            lat=None,
            lng=None,
            phone=phone,
            store_format=store_format,
            status=None,
            source_url=url,
        )

    @staticmethod
    def _iter_hrefs(soup: BeautifulSoup) -> Iterable[str]:
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if href:
                yield href

    @staticmethod
    def _is_store_path(path: str) -> bool:
        normalized = path.rstrip("/")
        return bool(
            re.search(r"/shops_map/[^/]+/\d+$", normalized)
            or re.search(r"/[^/]+/shops_map/[^/]+/\d+$", normalized)
        )

    @staticmethod
    def _extract_label_value(text: str, labels: tuple[str, ...]) -> str | None:
        for label in labels:
            pattern = rf"{re.escape(label)}\s*[:\-]?\s*(.+)"
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.group(1).split("\n")[0].strip()
                if value:
                    return value
        return None

    @staticmethod
    def _extract_phone(text: str) -> str | None:
        match = re.search(r"(\+?\d[\d\-\s()]{7,}\d)", text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_details_from_dl(soup: BeautifulSoup) -> dict[str, str]:
        details: dict[str, str] = {}
        for block in soup.select("dl, .shop-card, .store-card, .contacts, .content"):
            dts = [dt.get_text(" ", strip=True) for dt in block.select("dt")]
            dds = [dd.get_text(" ", strip=True) for dd in block.select("dd")]
            for key, value in zip(dts, dds):
                key_lower = key.lower()
                if "адрес" in key_lower:
                    details["address"] = value
                elif "режим" in key_lower or "время" in key_lower:
                    details["work_time"] = value
                elif "формат" in key_lower:
                    details["store_format"] = value
                elif "тел" in key_lower:
                    details["phone"] = value
        return details

    @staticmethod
    def _extract_city_region(soup: BeautifulSoup, url: str) -> tuple[str | None, str | None]:
        crumbs = [item.get_text(" ", strip=True) for item in soup.select("nav a, .breadcrumbs a, .breadcrumbs span")]
        crumbs = [c for c in crumbs if c]
        city: str | None = None
        region: str | None = None

        if crumbs:
            if len(crumbs) >= 2:
                city = crumbs[-1]
                region = crumbs[-2]
            else:
                city = crumbs[-1]

        parsed_path = [part for part in urlparse(url).path.split("/") if part]
        # /shops_map/{city_slug}/{id} or /{region}/shops_map/{city_slug}/{id}
        if city is None and len(parsed_path) >= 3:
            if "shops_map" in parsed_path:
                idx = parsed_path.index("shops_map")
                if idx + 1 < len(parsed_path):
                    city = parsed_path[idx + 1]
                if idx >= 1:
                    region = region or parsed_path[idx - 1]
        return city, region
