"""Parser for Monetka stores (HTML pages)."""

from __future__ import annotations

import logging
import re
from collections import deque
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse

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
        self._debug_location_logs_left = 5
        self._city_links_filtered_count = 0
        self._accepted_city_href_samples: list[str] = []
        self._rejected_city_href_samples: list[str] = []
        self.seed_urls = (
            f"{self.base_url}/shops_map/",
        )

    def parse(self) -> list[StoreRecord]:
        """Collect store pages and normalize parsed content."""
        self._reset_city_link_debug_stats()
        stores: list[StoreRecord] = []
        region_contexts = self._collect_region_contexts()
        region_pages = [region_url for region_url, _ in region_contexts]
        self.logger.info("Monetka: discovered %s regions", len(region_pages))
        if region_pages:
            self.logger.info("Monetka: region examples: %s", ", ".join(region_pages[:5]))
        city_context_by_url = self._collect_city_contexts(region_contexts=region_contexts)
        city_pages = sorted(city_context_by_url)
        self.logger.info("Monetka: discovered %s cities", len(city_pages))
        if city_pages:
            self.logger.info("Monetka: city examples: %s", ", ".join(city_pages[:5]))
        self.logger.info("Monetka: filtered out %s invalid city links", self._city_links_filtered_count)
        if self._accepted_city_href_samples:
            self.logger.info(
                "Monetka: accepted city href examples: %s",
                "; ".join(self._accepted_city_href_samples[:10]),
            )
        if self._rejected_city_href_samples:
            self.logger.info(
                "Monetka: rejected city href examples: %s",
                "; ".join(self._rejected_city_href_samples[:10]),
            )

        store_context_by_url: dict[str, tuple[str | None, str | None]] = {}
        for city_url in city_pages:
            context_city, context_region = city_context_by_url.get(city_url, (None, None))
            try:
                city_store_links, city_context = self._collect_store_links_for_city(
                    city_url,
                    city_hint=context_city,
                    region_hint=context_region,
                )
            except Exception as exc:
                self.logger.warning("Monetka: failed collecting stores for city page %s: %s", city_url, exc)
                continue
            for store_url in city_store_links:
                # Keep first discovered context for deterministic assignment.
                if store_url not in store_context_by_url:
                    store_context_by_url[store_url] = city_context

        self.logger.info("Monetka: discovered %s unique store pages", len(store_context_by_url))
        if store_context_by_url:
            store_examples = sorted(store_context_by_url)[:5]
            self.logger.info("Monetka: store examples: %s", ", ".join(store_examples))
        parsed_store_pages = 0
        debug_stores_left = 20
        for store_url in sorted(store_context_by_url):
            context_city, context_region = store_context_by_url.get(store_url, (None, None))
            try:
                html = self.client.get_text(store_url)
                store_record = self._parse_store_page(
                    html,
                    store_url,
                    context_city=context_city,
                    context_region=context_region,
                )
                stores.append(store_record)
                parsed_store_pages += 1
                if debug_stores_left > 0:
                    self.logger.info(
                        "Monetka: parsed store sample region='%s' city='%s' source_url=%s",
                        store_record.region,
                        store_record.city,
                        store_record.source_url,
                    )
                    debug_stores_left -= 1
            except Exception as exc:
                self.logger.warning("Monetka: failed store page %s: %s", store_url, exc)
        deduped = self._deduplicate_stores(stores)
        if len(deduped) != len(stores):
            self.logger.info("Monetka: deduplicated stores %s -> %s", len(stores), len(deduped))
        self.logger.info("Monetka: parsed %s store pages", parsed_store_pages)
        return deduped

    def _collect_city_pages(self) -> list[str]:
        return sorted(self._collect_city_hints().keys())

    def _collect_city_contexts(
        self,
        *,
        region_contexts: list[tuple[str, str | None]] | None = None,
    ) -> dict[str, tuple[str | None, str | None]]:
        if region_contexts is None:
            region_contexts = self._collect_region_contexts()
        result: dict[str, tuple[str | None, str | None]] = {}
        for seed_url in self.seed_urls:
            try:
                html = self.client.get_text(seed_url)
            except Exception as exc:
                self.logger.info("Monetka: seed city list unavailable %s: %s", seed_url, exc)
                continue
            seed_region_name = self._extract_active_region_name(html)
            seed_city_count = 0
            for city_url, city_hint in self._extract_city_links_with_hint(html, seed_url):
                if city_url not in result:
                    result[city_url] = (self._sanitize_location(city_hint), seed_region_name)
                    seed_city_count += 1
            self.logger.info("Monetka: discovered %s cities from current region page %s", seed_city_count, seed_url)
        for region_url, region_name in region_contexts:
            region_city_contexts = self._collect_city_contexts_for_region(region_url, region_name=region_name)
            self.logger.info("Monetka: region %s -> %s city links", region_url, len(region_city_contexts))
            for city_url, city_context in region_city_contexts.items():
                if city_url not in result:
                    result[city_url] = city_context
        return result

    def _collect_city_hints(self, region_pages: list[str] | None = None) -> dict[str, str]:
        region_contexts: list[tuple[str, str | None]] | None = None
        if region_pages is not None:
            region_contexts = [
                (region_url, self._extract_region_name_from_change_url(region_url))
                for region_url in region_pages
            ]
        city_contexts = self._collect_city_contexts(region_contexts=region_contexts)
        result: dict[str, str] = {}
        for city_url, (city_name, _region_name) in city_contexts.items():
            result[city_url] = city_name or ""
        return result

    def _collect_region_contexts(self) -> list[tuple[str, str | None]]:
        regions: dict[str, str | None] = {}
        for url in self.seed_urls:
            try:
                html = self.client.get_text(url)
            except Exception as exc:
                self.logger.info("Monetka: seed unavailable %s: %s", url, exc)
                continue

            for region_link, region_name in self._extract_region_links_with_name(html, url):
                if region_link not in regions:
                    regions[region_link] = region_name

        if not regions:
            self.logger.warning("Monetka: no region links ending with '/change' found on seed pages")
        return sorted(regions.items())

    def _collect_region_pages(self) -> list[str]:
        return [region_url for region_url, _ in self._collect_region_contexts()]

    def _collect_city_contexts_for_region(
        self,
        region_url: str,
        *,
        region_name: str | None = None,
    ) -> dict[str, tuple[str | None, str | None]]:
        result: dict[str, tuple[str | None, str | None]] = {}
        request_headers = None
        if self._is_region_change_path(urlparse(region_url).path):
            # Region '/change' must be loaded as-is; referer keeps region context.
            request_headers = {"Referer": f"{self.base_url}/shops_map/"}
        try:
            html = self.client.get_text(region_url, headers=request_headers)
        except Exception as exc:
            self.logger.info("Monetka: region page unavailable %s: %s", region_url, exc)
            return result

        resolved_region_name = self._sanitize_location(region_name) or self._extract_region_name_from_change_url(region_url)
        for link, city_hint in self._extract_city_links_with_hint(html, region_url):
            if link not in result:
                result[link] = (self._sanitize_location(city_hint), resolved_region_name)
        return result

    def _collect_city_hints_for_region(self, region_url: str) -> dict[str, str]:
        city_contexts = self._collect_city_contexts_for_region(
            region_url,
            region_name=self._extract_region_name_from_change_url(region_url),
        )
        result: dict[str, str] = {}
        for city_url, (city_name, _region_name) in city_contexts.items():
            result[city_url] = city_name or ""
        return result

    def _collect_store_links_for_city(
        self,
        city_url: str,
        *,
        city_hint: str | None = None,
        region_hint: str | None = None,
    ) -> tuple[set[str], tuple[str | None, str | None]]:
        """Collect store links from city page and pagination if present."""
        queue: deque[str] = deque([city_url])
        visited: set[str] = set()
        stores: set[str] = set()
        max_pages = 20
        resolved_city_hint = self._sanitize_location(city_hint)
        resolved_region_hint = self._sanitize_location(region_hint)
        city_context: tuple[str | None, str | None] = (resolved_city_hint, resolved_region_hint)

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

            if page_url == city_url:
                extracted_city, extracted_region = self._extract_city_context(
                    html,
                    city_url,
                    city_hint=city_hint,
                )
                if not city_context[0] and extracted_city:
                    city_context = (self._sanitize_location(extracted_city), city_context[1])
                if not city_context[1] and extracted_region:
                    city_context = (city_context[0], self._sanitize_location(extracted_region))

            for store_link in self._extract_store_links(html, page_url):
                stores.add(store_link)
            for next_page in self._extract_pagination_links(html, page_url):
                if next_page not in visited:
                    queue.append(next_page)
        return stores, city_context

    def _extract_city_links(self, html: str, base_url: str) -> Iterable[str]:
        for link, _ in self._extract_city_links_with_hint(html, base_url):
            yield link

    def _extract_city_links_with_hint(self, html: str, base_url: str) -> Iterable[tuple[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        for anchor in soup.select("ul.shop_city_list_ul a[href]"):
            href = (anchor.get("href") or "").strip()
            absolute, reject_reason = self._normalize_valid_city_href(href=href, base_url=base_url)
            if not absolute:
                self._register_rejected_city_href(raw_href=href, reason=reject_reason or "invalid")
                continue
            self._register_accepted_city_href(absolute)
            if absolute not in seen:
                seen.add(absolute)
                hint = anchor.get_text(" ", strip=True)
                yield absolute, hint

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
            parsed = urlparse(absolute)
            query_lower = parsed.query.lower()
            path_lower = parsed.path.lower()
            if "page=" in query_lower or "pagen_" in query_lower or "/page/" in path_lower:
                if absolute not in seen:
                    seen.add(absolute)
                    yield absolute

    def _extract_region_links(self, html: str, base_url: str) -> Iterable[str]:
        for link, _ in self._extract_region_links_with_name(html, base_url):
            yield link

    def _extract_region_links_with_name(self, html: str, base_url: str) -> Iterable[tuple[str, str | None]]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not href:
                continue
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.fragment:
                continue
            if not self._is_region_change_path(parsed.path):
                continue
            cleaned = self._strip_url_fragment(absolute)
            if cleaned in seen:
                continue
            seen.add(cleaned)
            region_name = self._sanitize_location(anchor.get_text(" ", strip=True))
            if not region_name:
                region_name = self._extract_region_name_from_change_url(cleaned)
            yield cleaned, region_name

    @staticmethod
    def _is_region_change_path(path: str) -> bool:
        normalized = path.rstrip("/")
        if not normalized:
            return False
        parts = [part for part in normalized.split("/") if part]
        if len(parts) < 2:
            return False
        if parts[-1].lower() != "change":
            return False
        return "shops_map" not in parts

    @staticmethod
    def _strip_url_fragment(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")

    def _extract_active_region_name(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        selectors = (
            "#city_layer li.act span",
            "#city_layer li.act a",
            "select option[selected]",
        )
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            candidate = self._sanitize_location(node.get_text(" ", strip=True))
            if candidate:
                return candidate
        return None

    def _extract_region_name_from_change_url(self, region_url: str) -> str | None:
        parsed = urlparse(region_url)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            return None
        if parts[-1].lower() != "change":
            return None
        return self._sanitize_location(self._slug_to_name(parts[-2]))

    @staticmethod
    def _is_valid_city_page_path(path: str) -> bool:
        normalized = path.rstrip("/")
        if not normalized or MonetkaParser._is_store_path(normalized):
            return False
        parts = [part for part in normalized.split("/") if part]
        if len(parts) != 3:
            return False
        if parts[1].lower() != "shops_map":
            return False
        city_segment = parts[2]
        if not city_segment:
            return False
        if city_segment.startswith("+"):
            return False
        if city_segment.isdigit():
            return False
        return True

    def _normalize_valid_city_href(self, *, href: str, base_url: str) -> tuple[str | None, str | None]:
        if not href:
            return None, "empty"
        href_lower = href.lower()
        if href.startswith("+"):
            return None, "starts_with_plus"
        if href.startswith("#"):
            return None, "starts_with_hash"
        if href_lower.startswith("javascript:"):
            return None, "javascript_link"
        absolute = self._strip_url_fragment(urljoin(base_url, href))
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            return None, "unsupported_scheme"
        if parsed.netloc and parsed.netloc != urlparse(self.base_url).netloc:
            return None, "foreign_domain"
        if not self._is_valid_city_page_path(parsed.path):
            return None, "invalid_city_path"
        return absolute, None

    def _register_rejected_city_href(self, *, raw_href: str, reason: str) -> None:
        self._city_links_filtered_count += 1
        if len(self._rejected_city_href_samples) >= 10:
            return
        href_display = raw_href if raw_href else "<empty>"
        self._rejected_city_href_samples.append(f"{href_display} ({reason})")

    def _register_accepted_city_href(self, absolute_url: str) -> None:
        if len(self._accepted_city_href_samples) >= 10:
            return
        if absolute_url in self._accepted_city_href_samples:
            return
        self._accepted_city_href_samples.append(absolute_url)

    def _reset_city_link_debug_stats(self) -> None:
        self._city_links_filtered_count = 0
        self._accepted_city_href_samples = []
        self._rejected_city_href_samples = []

    def _extract_city_context(
        self,
        city_html: str,
        city_url: str,
        *,
        city_hint: str | None = None,
    ) -> tuple[str | None, str | None]:
        soup = BeautifulSoup(city_html, "lxml")
        title_city, title_region = self._extract_city_region_from_title(soup)
        city = self._sanitize_location(title_city)
        region = self._sanitize_location(title_region)

        if not city:
            heading = soup.select_one("h1")
            if heading:
                heading_text = heading.get_text(" ", strip=True)
                heading_match = re.search(r"Карта\s+магазинов\s+в\s+(.+)$", heading_text, flags=re.IGNORECASE)
                if heading_match:
                    city = self._sanitize_location(heading_match.group(1))

        if not city and soup.title and soup.title.string:
            raw_title = soup.title.string.strip()
            legacy_match = re.search(
                r"в\s+г\.\s*(.+?)\s*-\s*Торговая\s+сеть",
                raw_title,
                flags=re.IGNORECASE,
            )
            if legacy_match:
                city = self._sanitize_location(legacy_match.group(1))

        if not city and city_hint:
            city = self._sanitize_location(city_hint)

        if not region:
            region_hint = soup.select_one("span.black.dashed")
            if region_hint:
                region = self._sanitize_location(region_hint.get_text(" ", strip=True))

        url_city, url_region = self._extract_city_region_from_url(city_url)
        if not city:
            city = self._sanitize_location(url_city)
        if not region:
            region = self._sanitize_location(url_region)
        return city, region

    def _parse_store_page(
        self,
        html: str,
        url: str,
        *,
        context_city: str | None = None,
        context_region: str | None = None,
    ) -> StoreRecord:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n", strip=True)

        details = self._extract_details_from_dl(soup)
        address = details.get("address") or self._extract_label_value(text, ("Адрес", "Почтовый адрес"))
        work_time = details.get("work_time") or self._extract_label_value(text, ("Режим работы", "Время работы"))
        store_format = details.get("store_format") or self._extract_label_value(text, ("Формат магазина",))
        phone = details.get("phone") or self._extract_phone(text)
        city, region = self._extract_city_region(soup, url, text=text, details=details)
        city = city or details.get("city") or self._extract_strict_label_value(text, ("Город", "Населенный пункт"))
        region = region or details.get("region") or self._extract_strict_label_value(
            text, ("Регион", "Область", "Край", "Республика")
        )
        resolved_context_city = self._sanitize_location(context_city)
        resolved_context_region = self._sanitize_location(context_region)
        city, region = self._apply_city_context(
            city=city,
            region=region,
            context_city=resolved_context_city,
            context_region=resolved_context_region,
            source_url=url,
        )
        # Keep crawl hierarchy as source-of-truth; store page HTML is fallback/verification.
        if resolved_context_city:
            city = resolved_context_city
        if resolved_context_region:
            region = resolved_context_region
        city = self._sanitize_location(city)
        region = self._sanitize_location(region)

        if self._debug_location_logs_left > 0:
            self.logger.debug(
                "Monetka: extracted location city='%s' region='%s' source_url=%s",
                city,
                region,
                url,
            )
            self._debug_location_logs_left -= 1

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
    def _extract_strict_label_value(text: str, labels: tuple[str, ...]) -> str | None:
        """Extract values only from explicit `Label: value` lines."""
        for label in labels:
            pattern = rf"(?:^|\n)\s*{re.escape(label)}\s*[:\-]\s*(.+)"
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
                elif any(token in key_lower for token in ("город", "населен", "city", "locality")):
                    details["city"] = value
                elif any(token in key_lower for token in ("регион", "област", "край", "region")):
                    details["region"] = value
        return details

    @staticmethod
    def _extract_city_region(
        soup: BeautifulSoup,
        url: str,
        *,
        text: str | None = None,
        details: dict[str, str] | None = None,
    ) -> tuple[str | None, str | None]:
        raw_text = text or soup.get_text("\n", strip=True)
        details_map = details or MonetkaParser._extract_details_from_dl(soup)
        city: str | None = None
        region: str | None = None

        # 1) Visible page text.
        visible_city, visible_region = MonetkaParser._extract_city_region_from_visible_text(
            soup=soup,
            text=raw_text,
            details=details_map,
        )
        visible_city = MonetkaParser._sanitize_location(visible_city)
        visible_region = MonetkaParser._sanitize_location(visible_region)
        if visible_city:
            city = visible_city
        if visible_region:
            region = visible_region

        # 2) Breadcrumbs.
        breadcrumbs_city, breadcrumbs_region = MonetkaParser._extract_city_region_from_breadcrumbs(soup, url)
        breadcrumbs_city = MonetkaParser._sanitize_location(breadcrumbs_city)
        breadcrumbs_region = MonetkaParser._sanitize_location(breadcrumbs_region)
        if not city and breadcrumbs_city:
            city = breadcrumbs_city
        if not region and breadcrumbs_region:
            region = breadcrumbs_region

        # 3) Structured HTML/script blocks.
        structured_city, structured_region = MonetkaParser._extract_city_region_from_structured_blocks(soup)
        structured_city = MonetkaParser._sanitize_location(structured_city)
        structured_region = MonetkaParser._sanitize_location(structured_region)
        if not city and structured_city:
            city = structured_city
        if not region and structured_region:
            region = structured_region

        # 4) URL slug fallback.
        url_city, url_region = MonetkaParser._extract_city_region_from_url(url)
        url_city = MonetkaParser._sanitize_location(url_city)
        url_region = MonetkaParser._sanitize_location(url_region)
        if not city and url_city:
            city = url_city
        if not region and url_region:
            region = url_region

        return MonetkaParser._sanitize_location(city), MonetkaParser._sanitize_location(region)

    @staticmethod
    def _apply_city_context(
        *,
        city: str | None,
        region: str | None,
        context_city: str | None,
        context_region: str | None,
        source_url: str,
    ) -> tuple[str | None, str | None]:
        """Reconcile store-page location with city-page context.

        Monetka city pages may point to store URLs under '/shops_map/ekb/{id}' for many different cities.
        In such cases URL and store-page title can be generic, while city page context is source-of-truth.
        """
        resolved_city = MonetkaParser._sanitize_location(city)
        resolved_region = MonetkaParser._sanitize_location(region)
        resolved_context_city = MonetkaParser._sanitize_location(context_city)
        resolved_context_region = MonetkaParser._sanitize_location(context_region)

        if not resolved_context_city and not resolved_context_region:
            return resolved_city, resolved_region

        url_city, _ = MonetkaParser._extract_city_region_from_url(source_url)
        url_city_token = MonetkaParser._normalize_token(url_city) if url_city else ""
        extracted_city_token = MonetkaParser._normalize_token(resolved_city) if resolved_city else ""
        context_city_token = MonetkaParser._normalize_token(resolved_context_city) if resolved_context_city else ""

        should_use_context_city = False
        if resolved_context_city:
            if not resolved_city:
                should_use_context_city = True
            elif context_city_token and extracted_city_token and context_city_token != extracted_city_token:
                should_use_context_city = True
            elif context_city_token and url_city_token and context_city_token != url_city_token:
                should_use_context_city = True

        if should_use_context_city:
            resolved_city = resolved_context_city
            if resolved_context_region:
                resolved_region = resolved_context_region
        elif not resolved_region and resolved_context_region:
            resolved_region = resolved_context_region

        return resolved_city, resolved_region

    @staticmethod
    def _extract_city_region_from_visible_text(
        *,
        soup: BeautifulSoup,
        text: str,
        details: dict[str, str],
    ) -> tuple[str | None, str | None]:
        city = details.get("city")
        region = details.get("region")

        if not city:
            city = MonetkaParser._extract_strict_label_value(text, ("Город", "Населенный пункт"))
        if not region:
            region = MonetkaParser._extract_strict_label_value(text, ("Регион", "Область", "Край", "Республика"))

        title_city, title_region = MonetkaParser._extract_city_region_from_title(soup)
        if not city and title_city:
            city = title_city
        if not region and title_region:
            region = title_region

        return city, region

    @staticmethod
    def _extract_city_region_from_breadcrumbs(soup: BeautifulSoup, url: str) -> tuple[str | None, str | None]:
        parsed_path = [part for part in urlparse(url).path.split("/") if part]
        city_slug: str | None = None
        if "shops_map" in parsed_path:
            idx = parsed_path.index("shops_map")
            if idx + 1 < len(parsed_path):
                city_slug = parsed_path[idx + 1]

        crumbs = [
            item.get_text(" ", strip=True)
            for item in soup.select(".breadcrumbs a, .breadcrumbs span, nav.breadcrumbs a, nav.breadcrumbs span")
        ]
        crumbs = [crumb for crumb in crumbs if crumb]
        if not crumbs:
            return None, None

        city = MonetkaParser._pick_city_from_crumbs(crumbs, city_slug)
        region = MonetkaParser._pick_region_from_crumbs(crumbs, city)
        return city, region

    @staticmethod
    def _extract_city_region_from_url(url: str) -> tuple[str | None, str | None]:
        parsed_path = [part for part in urlparse(url).path.split("/") if part]
        if "shops_map" not in parsed_path:
            return None, None

        idx = parsed_path.index("shops_map")
        city: str | None = None
        region: str | None = None
        if idx + 1 < len(parsed_path):
            city = MonetkaParser._slug_to_name(parsed_path[idx + 1])
        if idx >= 1:
            region = MonetkaParser._slug_to_name(parsed_path[idx - 1])
        return city, region

    @staticmethod
    def _extract_city_region_from_title(soup: BeautifulSoup) -> tuple[str | None, str | None]:
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        if not title:
            return None, None
        match = re.search(
            r"Карта\s+магазинов\s+в\s+(.+?)\s*[—-]\s*Магазины\s+«Монетка»\s*[—-]\s*(.+)$",
            title,
            flags=re.IGNORECASE,
        )
        if not match:
            return None, None
        city = match.group(1).strip()
        region = match.group(2).strip()
        return city or None, region or None

    @staticmethod
    def _extract_city_region_from_structured_blocks(soup: BeautifulSoup) -> tuple[str | None, str | None]:
        joined_scripts = " ".join(script.get_text(" ", strip=True) for script in soup.find_all("script"))
        if not joined_scripts:
            return None, None
        city_match = re.search(r'"city"\s*:\s*"([^"]+)"', joined_scripts, flags=re.IGNORECASE)
        region_match = re.search(r'"region"\s*:\s*"([^"]+)"', joined_scripts, flags=re.IGNORECASE)
        city = city_match.group(1).strip() if city_match else None
        region = region_match.group(1).strip() if region_match else None
        return city, region

    @staticmethod
    def _slug_to_name(slug: str | None) -> str | None:
        if not slug:
            return None
        value = unquote(slug).strip().strip("/").replace("-", " ").replace("_", " ")
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
            "ekb": "Екатеринбург",
            "spb": "Санкт-Петербург",
            "msk": "Москва",
        }
        lowered = value.lower().strip()
        if lowered in aliases:
            return aliases[lowered]
        words = [part for part in value.split() if part]
        return " ".join(word.capitalize() for word in words)

    @staticmethod
    def _sanitize_location(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"\s+", " ", value).strip(" ,.;:-")
        if len(cleaned) < 2:
            return None
        if not re.search(r"[A-Za-zА-Яа-яЁё]", cleaned):
            return None
        return cleaned

    @staticmethod
    def _normalize_token(value: str) -> str:
        return re.sub(r"[^a-zа-я0-9]+", "", value.lower())

    @staticmethod
    def _deduplicate_stores(stores: list[StoreRecord]) -> list[StoreRecord]:
        deduped: list[StoreRecord] = []
        seen_keys: set[str] = set()
        for store in stores:
            key = "||".join(
                (
                    MonetkaParser._normalize_dedupe_part(store.network),
                    MonetkaParser._normalize_dedupe_part(store.city),
                    MonetkaParser._normalize_dedupe_part(store.address),
                )
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(store)
        return deduped

    @staticmethod
    def _normalize_dedupe_part(value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"\s+", " ", value.strip().lower())

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
    def _looks_like_region(value: str) -> bool:
        lowered = value.lower()
        region_markers = (
            "област",
            "край",
            "республик",
            "округ",
            "oblast",
            "krai",
            "region",
            "okrug",
        )
        return any(marker in lowered for marker in region_markers)

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
            if MonetkaParser._looks_like_region(crumb):
                continue
            return crumb
        return None

    @staticmethod
    def _pick_region_from_crumbs(crumbs: list[str], city: str | None) -> str | None:
        if city:
            try:
                city_index = crumbs.index(city)
            except ValueError:
                city_index = -1
            if city_index > 0:
                for i in range(city_index - 1, -1, -1):
                    candidate = crumbs[i]
                    if MonetkaParser._is_generic_breadcrumb(candidate):
                        continue
                    if MonetkaParser._is_probably_address(candidate):
                        continue
                    return candidate

        for candidate in reversed(crumbs):
            if MonetkaParser._is_generic_breadcrumb(candidate):
                continue
            if MonetkaParser._is_probably_address(candidate):
                continue
            if MonetkaParser._looks_like_region(candidate):
                return candidate
        return None
