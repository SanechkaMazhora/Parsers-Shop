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
        city = city or self._extract_label_value(text, ("Город", "Населенный пункт"))
        region = region or self._extract_label_value(text, ("Регион", "Область", "Край", "Республика"))

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
        parsed_path = [part for part in urlparse(url).path.split("/") if part]
        city: str | None = None
        region: str | None = None
        city_slug: str | None = None

        # /shops_map/{city_slug}/{id} or /{region_slug}/shops_map/{city_slug}/{id}
        if "shops_map" in parsed_path:
            idx = parsed_path.index("shops_map")
            if idx + 1 < len(parsed_path):
                city_slug = parsed_path[idx + 1]
                city = MonetkaParser._slug_to_name(city_slug)
            if idx >= 1:
                region = MonetkaParser._slug_to_name(parsed_path[idx - 1])

        crumbs = [item.get_text(" ", strip=True) for item in soup.select(".breadcrumbs a, .breadcrumbs span, nav.breadcrumbs a, nav.breadcrumbs span")]
        crumbs = [c for c in crumbs if c]
        if crumbs:
            city_from_crumbs = MonetkaParser._pick_city_from_crumbs(crumbs, city_slug)
            region_from_crumbs = MonetkaParser._pick_region_from_crumbs(crumbs, city_from_crumbs)
            city = city_from_crumbs or city
            region = region_from_crumbs or region
        return city, region

    @staticmethod
    def _slug_to_name(slug: str | None) -> str | None:
        if not slug:
            return None
        value = slug.strip().strip("/").replace("-", " ").replace("_", " ")
        if not value:
            return None
        normalized = MonetkaParser._normalize_location_name(value)
        return normalized

    @staticmethod
    def _normalize_location_name(value: str) -> str:
        aliases = {
            "urfo": "Уральский федеральный округ",
            "sfo": "Сибирский федеральный округ",
            "cfo": "Центральный федеральный округ",
        }
        lowered = value.lower().strip()
        if lowered in aliases:
            return aliases[lowered]
        words = [part for part in value.split() if part]
        return " ".join(word.capitalize() for word in words)

    @staticmethod
    def _normalize_token(value: str) -> str:
        return re.sub(r"[^a-zа-я0-9]+", "", value.lower())

    @staticmethod
    def _is_probably_address(value: str) -> bool:
        lowered = value.lower()
        if re.search(r"\d", lowered):
            return True
        return any(token in lowered for token in ("ул.", "улица", "дом", "пр-кт", "проспект", "д."))

    @staticmethod
    def _is_generic_breadcrumb(value: str) -> bool:
        lowered = value.lower()
        return lowered in {"главная", "магазины", "карта магазинов"}

    @staticmethod
    def _pick_city_from_crumbs(crumbs: list[str], city_slug: str | None) -> str | None:
        if city_slug:
            slug_token = MonetkaParser._normalize_token(city_slug)
            for crumb in crumbs:
                if MonetkaParser._normalize_token(crumb) == slug_token:
                    return crumb
        for crumb in reversed(crumbs):
            if MonetkaParser._is_generic_breadcrumb(crumb):
                continue
            if MonetkaParser._is_probably_address(crumb):
                continue
            return crumb
        return None

    @staticmethod
    def _pick_region_from_crumbs(crumbs: list[str], city: str | None) -> str | None:
        if not city:
            return None
        try:
            city_index = crumbs.index(city)
        except ValueError:
            return None
        for i in range(city_index - 1, -1, -1):
            candidate = crumbs[i]
            if MonetkaParser._is_generic_breadcrumb(candidate):
                continue
            if MonetkaParser._is_probably_address(candidate):
                continue
            return candidate
        return None
