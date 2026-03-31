"""Parser for Monetka stores (HTML pages)."""

from __future__ import annotations

import logging
import re
from collections import deque
from typing import Any, Iterable
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from requests import RequestException

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

        store_context_by_url: dict[str, dict[str, str | None]] = {}
        for city_url in city_pages:
            context_city, context_region = city_context_by_url.get(city_url, (None, None))
            try:
                city_store_summaries, city_context = self._collect_store_links_for_city(
                    city_url,
                    city_hint=context_city,
                    region_hint=context_region,
                )
            except Exception as exc:
                self._log_request_issue(scope="collect stores for city page", url=city_url, exc=exc)
                continue
            for store_url, summary in city_store_summaries.items():
                # Keep first discovered context for deterministic assignment.
                if store_url not in store_context_by_url:
                    store_context_by_url[store_url] = {
                        "context_city": city_context[0],
                        "context_region": city_context[1],
                        "address": summary.get("address"),
                        "work_time": summary.get("work_time"),
                        "phone": summary.get("phone"),
                        "store_format": summary.get("store_format"),
                    }

        self.logger.info("Monetka: discovered %s unique store pages", len(store_context_by_url))
        if store_context_by_url:
            store_examples = sorted(store_context_by_url)[:5]
            self.logger.info("Monetka: store examples: %s", ", ".join(store_examples))
        parsed_store_pages = 0
        partial_store_pages = 0
        skipped_store_pages = 0
        debug_stores_left = 20
        for store_url in sorted(store_context_by_url):
            store_context = store_context_by_url.get(store_url, {})
            context_city = store_context.get("context_city")
            context_region = store_context.get("context_region")
            fallback_summary = {
                "address": store_context.get("address"),
                "work_time": store_context.get("work_time"),
                "phone": store_context.get("phone"),
                "store_format": store_context.get("store_format"),
            }
            try:
                html, resolved_store_url = self._get_text_with_final_url(store_url)
            except Exception as exc:
                partial_record = None
                if self._is_request_failure(exc):
                    partial_record = self._build_partial_store_record(
                        store_url,
                        context_city=context_city,
                        context_region=context_region,
                        fallback_summary=fallback_summary,
                    )
                if partial_record is not None:
                    stores.append(partial_record)
                    partial_store_pages += 1
                    self.logger.warning(
                        "Monetka: detail page unavailable, saved partial record source_url=%s status_code=%s fields=%s",
                        store_url,
                        self._get_http_status_code(exc),
                        ",".join(self._collect_available_partial_fields(partial_record)),
                    )
                else:
                    skipped_store_pages += 1
                    self.logger.warning("Monetka: failed store page %s: %s", store_url, exc)
                continue
            try:
                store_record = self._parse_store_page(
                    html,
                    resolved_store_url,
                    context_city=context_city,
                    context_region=context_region,
                    fallback_summary=fallback_summary,
                )
            except Exception as exc:
                partial_record = self._build_partial_store_record(
                    store_url,
                    context_city=context_city,
                    context_region=context_region,
                    fallback_summary=fallback_summary,
                )
                if partial_record is not None:
                    stores.append(partial_record)
                    partial_store_pages += 1
                    self.logger.warning(
                        "Monetka: failed parsing store page %s, saved partial record fields=%s error=%s",
                        store_url,
                        ",".join(self._collect_available_partial_fields(partial_record)),
                        exc,
                    )
                else:
                    skipped_store_pages += 1
                    self.logger.warning("Monetka: failed parsing store page %s: %s", store_url, exc)
                continue
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
        deduped = self._deduplicate_stores(stores)
        if len(deduped) != len(stores):
            self.logger.info("Monetka: deduplicated stores %s -> %s", len(stores), len(deduped))
        self.logger.info(
            "Monetka: parsed %s store pages, saved %s partial records, skipped %s store pages",
            parsed_store_pages,
            partial_store_pages,
            skipped_store_pages,
        )
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
                self._log_request_issue(scope="seed city list", url=seed_url, exc=exc, level=logging.INFO)
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
            region_contexts = [(region_url, None) for region_url in region_pages]
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
                self._log_request_issue(scope="seed page", url=url, exc=exc, level=logging.INFO)
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
            self._log_request_issue(scope="region page", url=region_url, exc=exc, level=logging.INFO)
            return result

        resolved_region_name = self._sanitize_location(region_name)
        for link, city_hint in self._extract_city_links_with_hint(html, region_url):
            if link not in result:
                result[link] = (self._sanitize_location(city_hint), resolved_region_name)
        return result

    def _collect_city_hints_for_region(self, region_url: str) -> dict[str, str]:
        city_contexts = self._collect_city_contexts_for_region(
            region_url,
            region_name=None,
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
    ) -> tuple[dict[str, dict[str, str | None]], tuple[str | None, str | None]]:
        """Collect store links from city page and pagination if present."""
        queue: deque[str] = deque([city_url])
        visited: set[str] = set()
        stores: dict[str, dict[str, str | None]] = {}
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
                self._log_request_issue(scope="city/pagination page", url=page_url, exc=exc)
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

            for store_link, summary in self._extract_store_summaries(html, page_url).items():
                if store_link not in stores:
                    stores[store_link] = summary
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
        for store_url in self._extract_store_summaries(html, base_url):
            yield store_url

    def _extract_store_summaries(self, html: str, base_url: str) -> dict[str, dict[str, str | None]]:
        soup = BeautifulSoup(html, "lxml")
        summaries: dict[str, dict[str, str | None]] = {}
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not href:
                continue
            absolute = urljoin(base_url, href)
            path = urlparse(absolute).path
            if not self._is_store_path(path):
                continue
            if absolute in summaries:
                continue
            address = self._clean_address(anchor.get_text(" ", strip=True))
            work_time = self._extract_store_summary_work_time(anchor, address=address)
            summaries[absolute] = {
                "address": address,
                "work_time": work_time,
                "phone": None,
                "store_format": None,
            }
        return summaries

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
        del city_url
        city = self._sanitize_location(city_hint)
        region = None

        if not city:
            heading = soup.select_one("h1")
            if heading:
                heading_text = heading.get_text(" ", strip=True)
                heading_match = re.search(r"Карта\s+магазинов\s+в\s+(.+)$", heading_text, flags=re.IGNORECASE)
                if heading_match:
                    city = self._sanitize_location(heading_match.group(1))

        if not region:
            region_hint = soup.select_one("span.black.dashed")
            if region_hint:
                region = self._sanitize_location(region_hint.get_text(" ", strip=True))
        return city, region

    def _parse_store_page(
        self,
        html: str,
        url: str,
        *,
        context_city: str | None = None,
        context_region: str | None = None,
        fallback_summary: dict[str, str | None] | None = None,
    ) -> StoreRecord:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n", strip=True)
        summary = fallback_summary or {}

        details = self._extract_details_from_dl(soup)
        address = self._clean_address(
            details.get("address")
            or self._extract_label_value(text, ("Адрес", "Почтовый адрес"))
            or summary.get("address")
        )
        work_time = self._clean_work_time(
            details.get("work_time")
            or self._extract_label_value(text, ("Режим работы", "Время работы"))
            or summary.get("work_time")
        )
        store_format = details.get("store_format") or self._extract_label_value(text, ("Формат магазина",)) or summary.get(
            "store_format"
        )
        status = details.get("status") or self._extract_label_value(text, ("Статус",))
        # Ignore generic site-wide footer phones. Publish a phone only when it is
        # attached to store-specific details that the page exposes explicitly.
        phone = details.get("phone") or summary.get("phone")
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

        latitude, longitude = self._extract_coordinates(soup)
        return StoreRecord.build(
            network=self.NETWORK_NAME,
            region=region,
            city=city,
            address=address,
            work_time=work_time,
            lat=latitude,
            lng=longitude,
            phone=phone,
            store_format=store_format,
            status=status,
            source_url=url,
        )

    def _build_partial_store_record(
        self,
        url: str,
        *,
        context_city: str | None,
        context_region: str | None,
        fallback_summary: dict[str, str | None],
    ) -> StoreRecord | None:
        city = self._sanitize_location(context_city)
        region = self._sanitize_location(context_region)
        address = self._clean_address(fallback_summary.get("address"))
        work_time = self._clean_work_time(fallback_summary.get("work_time"))
        phone = fallback_summary.get("phone")
        store_format = fallback_summary.get("store_format")
        if not any((city, region, address, work_time, phone, store_format)):
            return None
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
    def _collect_available_partial_fields(store: StoreRecord) -> list[str]:
        fields: list[str] = []
        for field_name in ("region", "city", "address", "work_time", "phone", "store_format"):
            if getattr(store, field_name):
                fields.append(field_name)
        return fields

    @staticmethod
    def _get_http_status_code(exc: Exception) -> int | None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        return status_code if isinstance(status_code, int) else None

    @staticmethod
    def _is_request_failure(exc: Exception) -> bool:
        return isinstance(exc, RequestException) or MonetkaParser._get_http_status_code(exc) is not None

    @staticmethod
    def _is_expected_handled_404(*, scope: str, exc: Exception) -> bool:
        return MonetkaParser._get_http_status_code(exc) == 404 and scope in {"city/pagination page"}

    @staticmethod
    def _resolve_request_issue_level(
        *,
        scope: str,
        exc: Exception,
        default_level: int,
    ) -> int:
        status_code = MonetkaParser._get_http_status_code(exc)
        if MonetkaParser._is_expected_handled_404(scope=scope, exc=exc):
            return logging.WARNING
        if not MonetkaParser._is_request_failure(exc):
            return logging.ERROR if default_level >= logging.WARNING else default_level
        if status_code is None or status_code >= 500:
            return logging.ERROR if default_level >= logging.WARNING else default_level
        return default_level

    def _log_request_issue(
        self,
        *,
        scope: str,
        url: str,
        exc: Exception,
        level: int = logging.WARNING,
    ) -> None:
        resolved_level = self._resolve_request_issue_level(scope=scope, exc=exc, default_level=level)
        status_code = self._get_http_status_code(exc)
        if self._is_request_failure(exc):
            self.logger.log(
                resolved_level,
                "Monetka: %s unavailable %s status_code=%s error=%s",
                scope,
                url,
                status_code,
                exc,
            )
            return
        self.logger.log(resolved_level, "Monetka: failed %s %s: %s", scope, url, exc)

    def _get_text_with_final_url(self, url: str) -> tuple[str, str]:
        if hasattr(self.client, "get_text_with_final_url"):
            text, final_url = self.client.get_text_with_final_url(url)  # type: ignore[attr-defined]
            return text, final_url
        return self.client.get_text(url), url

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

    @classmethod
    def _extract_store_summary_work_time(cls, anchor: Any, *, address: str | None) -> str | None:
        seen_texts: set[str] = set()
        current = anchor
        for _ in range(5):
            current = getattr(current, "parent", None)
            if current is None:
                break
            text = current.get_text("\n", strip=True)
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            for line in text.splitlines():
                candidate = line.strip()
                if not candidate:
                    continue
                if address and cls._normalize_token(candidate) == cls._normalize_token(address):
                    continue
                normalized = cls._find_work_time_in_text(candidate)
                if normalized:
                    return normalized
        return None

    @classmethod
    def _find_work_time_in_text(cls, text: str) -> str | None:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return None
        lowered = cleaned.lower()
        if "круглосуточ" in lowered:
            return "круглосуточно"
        patterns = (
            r"\b\d{1,2}(?::|\.)\d{2}\s*[—\-]\s*\d{1,2}(?::|\.)\d{2}\b",
            r"\b\d{1,2}\s*[—\-]\s*\d{1,2}(?::|\.)\d{2}\b",
            r"\b\d{1,2}(?::|\.)\d{2}\s*[—\-]\s*\d{1,2}\b",
            r"\b\d{1,2}\s*[—\-]\s*\d{1,2}\b",
        )
        for pattern in patterns:
            match = re.search(pattern, cleaned)
            if not match:
                continue
            normalized = cls._clean_work_time(match.group(0))
            if normalized:
                return normalized
        return None

    @classmethod
    def _clean_work_time(cls, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"\s+", " ", value).strip(" ,;")
        if not cleaned:
            return None
        cleaned = cleaned.replace("—", "-").replace("–", "-")
        cleaned = re.sub(r"\s*-\s*", "-", cleaned)
        if "круглосуточ" in cleaned.lower():
            return "круглосуточно"
        match = re.fullmatch(r"(?P<start>\d{1,2}(?::\d{2}|\.\d{2})?)-(?P<end>\d{1,2}(?::\d{2}|\.\d{2})?)", cleaned)
        if not match:
            return cleaned
        start = cls._normalize_time_token(match.group("start"))
        end = cls._normalize_time_token(match.group("end"))
        if start and end:
            return f"{start}-{end}"
        return cleaned

    @staticmethod
    def _normalize_time_token(token: str) -> str | None:
        cleaned = token.strip().replace(".", ":")
        if re.fullmatch(r"\d{1,2}", cleaned):
            return f"{int(cleaned):02d}:00"
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", cleaned)
        if not match:
            return None
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    @classmethod
    def _clean_address(cls, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"\s+", " ", value).strip(" ,;")
        if not cleaned:
            return None
        cleaned = re.sub(r"^адрес\s*[:\-]?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^у\s+ул\.?\s*", "ул. ", cleaned, flags=re.IGNORECASE)
        if re.match(r"^у\s+", cleaned, flags=re.IGNORECASE):
            cleaned = re.sub(r"^у\s+", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^ул\s+", "ул. ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^пер\s+", "пер. ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^пр[- ]?кт\s+", "пр-кт ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^просп\s+", "просп. ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+,", ",", cleaned)
        cleaned = re.sub(r",\s*,+", ", ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;")
        return cleaned or None

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
                elif "статус" in key_lower or "status" in key_lower:
                    details["status"] = value
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
        del url
        city = MonetkaParser._sanitize_location(
            details_map.get("city")
            or MonetkaParser._extract_strict_label_value(raw_text, ("Город", "Населенный пункт"))
        )
        region = MonetkaParser._sanitize_location(
            details_map.get("region")
            or MonetkaParser._extract_strict_label_value(raw_text, ("Регион", "Область", "Край", "Республика"))
        )

        # Structured HTML/script blocks can also carry explicit geography.
        structured_city, structured_region = MonetkaParser._extract_city_region_from_structured_blocks(soup)
        structured_city = MonetkaParser._sanitize_location(structured_city)
        structured_region = MonetkaParser._sanitize_location(structured_region)
        if not city and structured_city:
            city = structured_city
        if not region and structured_region:
            region = structured_region

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
        """Backfill geography from crawl context only when it is non-conflicting."""
        resolved_city = MonetkaParser._sanitize_location(city)
        resolved_region = MonetkaParser._sanitize_location(region)
        resolved_context_city = MonetkaParser._sanitize_location(context_city)
        resolved_context_region = MonetkaParser._sanitize_location(context_region)

        del source_url

        if (
            resolved_city
            and resolved_context_city
            and not MonetkaParser._locations_match(resolved_city, resolved_context_city)
        ):
            return resolved_city, resolved_region

        if (
            resolved_region
            and resolved_context_region
            and not MonetkaParser._locations_match(resolved_region, resolved_context_region)
        ):
            if resolved_city:
                return resolved_city, resolved_region
            return None, resolved_region

        if not resolved_city and resolved_context_city:
            resolved_city = resolved_context_city

        if (
            not resolved_region
            and resolved_context_region
            and (
                not resolved_city
                or not resolved_context_city
                or MonetkaParser._locations_match(resolved_city, resolved_context_city)
            )
        ):
            resolved_region = resolved_context_region

        return resolved_city, resolved_region

    @staticmethod
    def _extract_city_region_from_visible_text(
        *,
        soup: BeautifulSoup,
        text: str,
        details: dict[str, str],
    ) -> tuple[str | None, str | None]:
        del soup
        city = details.get("city")
        region = details.get("region")

        if not city:
            city = MonetkaParser._extract_strict_label_value(text, ("Город", "Населенный пункт"))
        if not region:
            region = MonetkaParser._extract_strict_label_value(text, ("Регион", "Область", "Край", "Республика"))

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
    def _extract_coordinates(soup: BeautifulSoup) -> tuple[float | None, float | None]:
        for node in soup.select("[data-lat][data-lng], [data-lat][data-lon], [data-latitude][data-longitude]"):
            lat = node.get("data-lat") or node.get("data-latitude")
            lng = node.get("data-lng") or node.get("data-lon") or node.get("data-longitude")
            lat_value = MonetkaParser._to_float(lat)
            lng_value = MonetkaParser._to_float(lng)
            if lat_value is not None and lng_value is not None:
                return lat_value, lng_value

        meta_pairs = (
            (
                'meta[property="place:location:latitude"][content]',
                'meta[property="place:location:longitude"][content]',
                "content",
            ),
            ('[itemprop="latitude"][content]', '[itemprop="longitude"][content]', "content"),
        )
        for lat_selector, lng_selector, attr_name in meta_pairs:
            lat_node = soup.select_one(lat_selector)
            lng_node = soup.select_one(lng_selector)
            if not lat_node or not lng_node:
                continue
            lat_value = MonetkaParser._to_float(lat_node.get(attr_name))
            lng_value = MonetkaParser._to_float(lng_node.get(attr_name))
            if lat_value is not None and lng_value is not None:
                return lat_value, lng_value

        joined_scripts = " ".join(script.get_text(" ", strip=True) for script in soup.find_all("script"))
        if not joined_scripts:
            return None, None

        pair_patterns = (
            r'"lat(?:itude)?"\s*:\s*"?([0-9]{1,2}\.\d+)"?.{0,120}?"(?:lng|lon|longitude)"\s*:\s*"?([0-9]{1,3}\.\d+)"?',
            r'"(?:lng|lon|longitude)"\s*:\s*"?([0-9]{1,3}\.\d+)"?.{0,120}?"lat(?:itude)?"\s*:\s*"?([0-9]{1,2}\.\d+)"?',
        )
        for index, pattern in enumerate(pair_patterns):
            match = re.search(pattern, joined_scripts, flags=re.IGNORECASE)
            if not match:
                continue
            if index == 0:
                lat_raw, lng_raw = match.group(1), match.group(2)
            else:
                lng_raw, lat_raw = match.group(1), match.group(2)
            lat_value = MonetkaParser._to_float(lat_raw)
            lng_value = MonetkaParser._to_float(lng_raw)
            if lat_value is not None and lng_value is not None:
                return lat_value, lng_value
        return None, None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = str(value).strip()
        if not cleaned:
            return None
        cleaned = cleaned.replace(",", ".")
        cleaned = re.sub(r"[^0-9.\-]+", "", cleaned)
        if not cleaned or cleaned in {"-", ".", "-."}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

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
    def _locations_match(left: str | None, right: str | None) -> bool:
        if not left or not right:
            return False
        return MonetkaParser._normalize_token(left) == MonetkaParser._normalize_token(right)

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
