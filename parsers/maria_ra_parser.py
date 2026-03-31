"""Parser for Maria-Ra stores (embedded JS + Playwright fallback)."""

from __future__ import annotations

import json
import logging
import re
import ast
import warnings
from html import unescape
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.http_client import HttpClient
from core.models import StoreRecord


class MariaRaParser:
    """Parse Maria-Ra stores from JS payloads with optional Playwright fallback."""

    NETWORK_NAME = "Мария-Ра"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.map_url = "https://www.maria-ra.ru/o-kompanii/karta-seti/"
        self.base_url = "https://www.maria-ra.ru"

    def parse(self) -> list[StoreRecord]:
        """Collect stores from map page scripts or fallback DOM extraction."""
        html = self._load_map_html_with_age_gate()
        if html is None:
            return []

        stores_raw = self._extract_stores_from_html(html)
        if stores_raw:
            self.logger.info("Maria-Ra: strategy success = inline_js")
        if not stores_raw:
            self.logger.warning("Maria-Ra: no stores in inline JS, trying external JS")
            stores_raw = self._extract_stores_from_external_scripts(html)
            if stores_raw:
                self.logger.info("Maria-Ra: strategy success = external_js")

        if not stores_raw:
            self.logger.warning("Maria-Ra: no stores in scripts, trying HTML-embedded map data")
            stores_raw = self._extract_stores_from_data_attributes(html)
            if stores_raw:
                self.logger.info("Maria-Ra: strategy success = html_embedded")

        if not stores_raw:
            self.logger.warning("Maria-Ra: requests-based extraction failed, trying Playwright fallback")
            stores_raw = self._playwright_fallback()
            if stores_raw:
                self.logger.info("Maria-Ra: strategy success = playwright_fallback")

        stores_raw = self._deduplicate_candidates(stores_raw)
        stores: list[StoreRecord] = []
        for item in stores_raw:
            try:
                stores.append(self._normalize_store(item))
            except Exception as exc:
                self.logger.warning("Maria-Ra: failed parsing one store: %s", exc)
        stores, duplicate_rows, conflicting_duplicates = self._deduplicate_normalized_stores(stores)
        if duplicate_rows:
            log_method = self.logger.warning if conflicting_duplicates else self.logger.info
            log_method(
                "Maria-Ra: deduplicated normalized stores %s -> %s (removed=%s conflicting=%s)",
                len(stores) + duplicate_rows,
                len(stores),
                duplicate_rows,
                conflicting_duplicates,
            )
        self.logger.info("Maria-Ra: parsed %s stores", len(stores))
        return stores

    def _load_map_html_with_age_gate(self) -> str | None:
        """Load map HTML and retry with age-confirmation cookies if needed."""
        try:
            html = self.client.get_text(self.map_url)
        except Exception as exc:
            self.logger.error("Maria-Ra: failed loading map page: %s", exc)
            return None

        if not self._is_age_gate_page(html):
            return html

        self.logger.warning("Maria-Ra: age gate detected, retrying with confirm cookies")
        self._set_age_gate_cookies()
        try:
            # Prime main domain first so backend can apply session/cookie checks.
            self.client.get_text(self.base_url)
        except Exception as exc:
            self.logger.info("Maria-Ra: base page reload failed during age bypass: %s", exc)
        try:
            html = self.client.get_text(self.map_url)
        except Exception as exc:
            self.logger.error("Maria-Ra: map reload failed after age bypass: %s", exc)
            return None

        if self._is_age_gate_page(html):
            self.logger.warning("Maria-Ra: age gate still present after cookie bypass")
        return html

    def _extract_stores_from_html(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        for script in soup.find_all("script"):
            script_text = script.get_text("\n", strip=True)
            if not script_text:
                continue
            stores = self._extract_store_candidates_from_script(script_text)
            if stores:
                return stores
        return []

    def _extract_stores_from_external_scripts(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        script_urls = []
        for script in soup.find_all("script"):
            src = script.get("src")
            if isinstance(src, str) and src.strip():
                full_url = urljoin(self.base_url, src.strip())
                script_urls.append(full_url)

        for script_url in script_urls:
            try:
                js_text = self.client.get_text(script_url)
            except Exception as exc:
                self.logger.info("Maria-Ra: external script unavailable %s: %s", script_url, exc)
                continue

            stores = self._extract_store_candidates_from_script(js_text)
            if stores:
                self.logger.info("Maria-Ra: stores found in external script %s", script_url)
                return stores
        return []

    def _extract_stores_from_data_attributes(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        attributes = (
            "data-objects",
            "data-points",
            "data-shops",
            "data-stores",
            "data-features",
        )
        for node in soup.find_all(True):
            for attr_name in attributes:
                raw = node.attrs.get(attr_name)
                if not isinstance(raw, str) or not raw.strip():
                    continue
                parsed = self._safe_json_loads(unescape(raw))
                normalized = self._normalize_candidate_list(parsed)
                if normalized:
                    return normalized
        return []

    def _extract_store_candidates_from_script(self, script: str) -> list[dict[str, Any]]:
        # 1) JSON.parse("...") payloads with escaped JSON inside strings.
        for match in re.finditer(r"JSON\.parse\(\s*(\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*')\s*\)", script):
            decoded = self._decode_js_string_literal(match.group(1))
            if not decoded:
                continue
            parsed = self._safe_json_loads(decoded)
            normalized = self._normalize_candidate_list(parsed)
            if normalized:
                return normalized

        # 2) direct arrays: markers/stores/shops/features/points = [...]
        array_patterns = [
            r"(?:shops|stores|points|markers|features)\s*[:=]\s*(\[[\s\S]*?\])\s*[;,}]",
            r"(\[[\s\S]*?\"(?:address|lat|lng|coords|balloonContent)\"[\s\S]*?\])",
        ]
        for pattern in array_patterns:
            for match in re.finditer(pattern, script, flags=re.IGNORECASE):
                parsed = self._safe_json_loads(match.group(1))
                normalized = self._normalize_candidate_list(parsed)
                if normalized:
                    return normalized

        # 3) objects with common map payload keys.
        object_patterns = [
            r"(?:objects|shopsData|storesData|mapData)\s*[:=]\s*(\{[\s\S]*?\})\s*[;,]",
        ]
        for pattern in object_patterns:
            for match in re.finditer(pattern, script, flags=re.IGNORECASE):
                parsed = self._safe_json_loads(match.group(1))
                if isinstance(parsed, dict):
                    for key in ("features", "objects", "shops", "stores", "points", "data"):
                        normalized = self._normalize_candidate_list(parsed.get(key))
                        if normalized:
                            return normalized

        # 4) GeoJSON style object with features
        for match in re.finditer(r"(\{[\s\S]*?\"features\"\s*:\s*\[[\s\S]*?\][\s\S]*?\})", script):
            parsed = self._safe_json_loads(match.group(1))
            if isinstance(parsed, dict):
                features = parsed.get("features")
                normalized = self._normalize_candidate_list(features)
                if normalized:
                    return normalized

        return []

    def _normalize_candidate_list(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            return []

        items: list[dict[str, Any]] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            item = self._normalize_raw_js_item(raw)
            if item:
                items.append(item)
        return items

    @staticmethod
    def _get_first_value(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in payload:
                return payload[key]
        lowered_payload = {key.lower(): value for key, value in payload.items() if isinstance(key, str)}
        for key in keys:
            if key.lower() in lowered_payload:
                return lowered_payload[key.lower()]
        return None

    @staticmethod
    def _get_first_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        value = MariaRaParser._get_first_value(payload, keys)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _decode_js_string_literal(token: str) -> str | None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                decoded = ast.literal_eval(token)
        except Exception:
            return None
        return decoded if isinstance(decoded, str) else None

    def _normalize_raw_js_item(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        # Common Maria-Ra map payload style: NAME + COORDINATE + STARTED/END_WORK
        if any(key in raw for key in ("NAME", "COORDINATE", "STARTED_WORK", "END_WORK")):
            name = self._get_first_string(raw, ("NAME", "name"))
            city, address = self._split_city_and_address(name)
            coord_pair = self._parse_coordinate_string(self._get_first_value(raw, ("COORDINATE", "coordinate")))
            work_time = self._build_work_time_from_parts(raw.get("STARTED_WORK"), raw.get("END_WORK")) or self._get_first_string(
                raw,
                ("WORK_TIME", "SCHEDULE", "WORKTIME"),
            )
            return {
                "address": address or self._get_first_string(raw, ("ADDRESS", "ADDR", "FULL_ADDRESS", "FULLADDRESS")),
                "city": city or self._get_first_string(raw, ("CITY", "TOWN", "LOCALITY", "SETTLEMENT")),
                "region": self._get_first_string(raw, ("REGION", "REGION_NAME", "REGIONNAME", "SECTION")),
                "work_time": work_time,
                "coords": coord_pair,
                "phone": self._get_first_string(raw, ("PHONE", "TEL", "TELEPHONE")),
                "status": self._get_first_string(raw, ("STATUS", "STATUS_NAME", "STATUSNAME")),
                "format": self._get_first_string(raw, ("FORMAT", "STORE_FORMAT", "STOREFORMAT")),
            }

        # GeoJSON feature format
        if isinstance(raw.get("geometry"), dict) or isinstance(raw.get("properties"), dict):
            geometry = raw.get("geometry") if isinstance(raw.get("geometry"), dict) else {}
            properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
            coords = geometry.get("coordinates")
            popup_html = (
                properties.get("balloonContent")
                or properties.get("balloonContentBody")
                or properties.get("hintContent")
            )
            popup_data = self._parse_popup_content(popup_html if isinstance(popup_html, str) else "")
            return {
                "address": self._get_first_string(properties, ("address", "addr", "full_address", "fullAddress"))
                or popup_data.get("address"),
                "city": self._get_first_string(properties, ("city", "town", "locality", "settlement"))
                or popup_data.get("city"),
                "region": self._get_first_string(properties, ("region", "region_name", "regionName"))
                or popup_data.get("region"),
                "work_time": self._get_first_string(properties, ("work_time", "schedule", "workTime"))
                or popup_data.get("work_time"),
                "phone": self._get_first_string(properties, ("phone", "tel", "telephone")) or popup_data.get("phone"),
                "coords": coords,
                "status": self._get_first_string(properties, ("status", "status_name", "statusName"))
                or popup_data.get("status"),
                "format": self._get_first_string(properties, ("format", "store_format", "storeFormat"))
                or popup_data.get("format"),
            }

        # Direct flat objects
        popup_html = self._get_first_string(raw, ("popup", "balloonContent", "balloonContentBody"))
        popup_data = self._parse_popup_content(popup_html if isinstance(popup_html, str) else "")
        candidate = {
            "address": self._get_first_string(raw, ("address", "addr", "full_address", "fullAddress"))
            or popup_data.get("address"),
            "city": self._get_first_string(raw, ("city", "town", "locality", "settlement")) or popup_data.get("city"),
            "region": self._get_first_string(raw, ("region", "region_name", "regionName")) or popup_data.get("region"),
            "work_time": self._get_first_string(raw, ("work_time", "schedule", "workTime")) or popup_data.get("work_time"),
            "phone": self._get_first_string(raw, ("phone", "tel", "telephone")) or popup_data.get("phone"),
            "lat": self._get_first_value(raw, ("lat", "latitude")),
            "lng": self._get_first_value(raw, ("lng", "lon", "longitude")),
            "coords": self._get_first_value(raw, ("coords", "coordinates")),
            "status": self._get_first_string(raw, ("status", "status_name", "statusName")) or popup_data.get("status"),
            "format": self._get_first_string(raw, ("format", "store_format", "storeFormat")) or popup_data.get("format"),
        }
        # Keep only meaningful store candidates.
        if (
            candidate["address"] is None
            and candidate["coords"] is None
            and candidate["lat"] is None
            and candidate["city"] is None
            and candidate["work_time"] is None
        ):
            return None
        return candidate

    @staticmethod
    def _split_city_and_address(name: str | None) -> tuple[str | None, str | None]:
        if not name:
            return None, None
        cleaned = re.sub(r"\s+", " ", name).strip(" ,")
        if not cleaned:
            return None, None
        prefix_part, remainder = MariaRaParser._split_locality_prefix(cleaned)
        if prefix_part and remainder:
            return prefix_part, remainder

        # Sometimes city and address are merged without comma: "рп Кольцово ул.Центральная, 1".
        tokens = cleaned.split()
        for split_index in range(2, len(tokens)):
            city_candidate = " ".join(tokens[:split_index]).strip()
            address_candidate = " ".join(tokens[split_index:]).strip()
            if not MariaRaParser._looks_like_locality_name(city_candidate):
                continue
            if MariaRaParser._is_informative_address_fragment(address_candidate):
                return city_candidate, address_candidate

        return None, cleaned

    @staticmethod
    def _looks_like_locality_name(value: str | None) -> bool:
        cleaned = MariaRaParser._clean_text(value)
        if not cleaned:
            return False
        return bool(
            re.match(
                r"^(?:г\.?|город|пгт|пос\.?|поселок|п\.|рп|р\.\s*п\.?|с\.|село|д\.|д\.п\.?|деревня|ст\.?|ст-ца|станица)\s*\S",
                cleaned,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _looks_like_explicit_region_name(value: str | None) -> bool:
        cleaned = MariaRaParser._clean_text(value)
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if lowered.startswith(("респ. ", "республика ")):
            return True
        return any(marker in lowered for marker in ("область", "обл.", "край", "автономный округ", " ао"))

    @staticmethod
    def _split_locality_prefix(value: str) -> tuple[str | None, str | None]:
        parts = re.split(r"\s*[,;]\s*", value, maxsplit=1)
        if len(parts) != 2:
            return None, None
        city_candidate, remainder = parts[0].strip(), parts[1].strip()
        if not MariaRaParser._looks_like_locality_name(city_candidate):
            return None, None
        if MariaRaParser._is_informative_address_fragment(city_candidate):
            return None, None
        return city_candidate, remainder

    @staticmethod
    def _split_region_prefix(value: str | None) -> tuple[str | None, str | None]:
        cleaned = MariaRaParser._clean_text(value)
        if not cleaned:
            return None, None
        cleaned = re.sub(r"^(?:адрес(?: магазина)?)\s*[:\-]?\s*", "", cleaned, flags=re.IGNORECASE)
        parts = re.split(r"\s*[,;]\s*", cleaned, maxsplit=1)
        if len(parts) != 2:
            return None, None
        region_candidate, remainder = parts[0].strip(), parts[1].strip()
        if not MariaRaParser._looks_like_explicit_region_name(region_candidate):
            return None, None
        return region_candidate, remainder

    @staticmethod
    def _parse_coordinate_string(value: Any) -> list[float] | None:
        if not isinstance(value, str):
            return None
        chunks = [part.strip() for part in value.split(",")]
        if len(chunks) != 2:
            return None
        try:
            lat = float(chunks[0])
            lng = float(chunks[1])
        except ValueError:
            return None
        return [lng, lat]

    @staticmethod
    def _build_work_time_from_parts(start: Any, end: Any) -> str | None:
        if isinstance(start, str) and isinstance(end, str) and start.strip() and end.strip():
            return f"{start.strip()}-{end.strip()}"
        return None

    @staticmethod
    def _parse_popup_content(html_text: str) -> dict[str, str]:
        if not html_text:
            return {}
        normalized = unescape(html_text)
        soup = BeautifulSoup(normalized, "lxml")
        text = soup.get_text("\n", strip=True)

        def extract(pattern: str) -> str | None:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            return match.group(1).strip() if match else None

        result: dict[str, str] = {}
        address = extract(r"(?:Адрес(?: магазина)?|Магазин)\s*[:\-]?\s*(.+)")
        work_time = extract(r"(?:Режим работы|Время работы)\s*[:\-]?\s*(.+)")
        phone = extract(r"(?:Телефон|Тел\.)\s*[:\-]?\s*(.+)")
        city = extract(r"(?:Город|Населенный пункт|Населённый пункт)\s*[:\-]?\s*(.+)")
        region = extract(r"(?:Регион|Область|Край|Республика)\s*[:\-]?\s*(.+)")
        store_format = extract(r"(?:Формат(?: магазина)?)\s*[:\-]?\s*(.+)")
        status = extract(r"(?:Статус)\s*[:\-]?\s*(.+)")
        if address:
            result["address"] = address
        if work_time:
            result["work_time"] = work_time
        if phone:
            result["phone"] = phone
        if city:
            result["city"] = city
        if region:
            result["region"] = region
        if store_format:
            result["format"] = store_format
        if status:
            result["status"] = status
        return result

    @staticmethod
    def _safe_json_loads(payload: str) -> Any:
        cleaned = payload.strip().rstrip(";")
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        cleaned = cleaned.replace("'", '"')
        cleaned = cleaned.replace("\\/", "/")
        try:
            return json.loads(cleaned)
        except Exception:
            return None

    @staticmethod
    def _deduplicate_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            key = "||".join(
                [
                    str(item.get("address") or "").strip().lower(),
                    str(item.get("city") or "").strip().lower(),
                    str(item.get("lat") or "").strip(),
                    str(item.get("lng") or "").strip(),
                    str(item.get("coords") or "").strip(),
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _playwright_fallback(self) -> list[dict[str, Any]]:
        """Fallback extraction using Playwright if JS parsing fails."""
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            self.logger.warning("Maria-Ra: Playwright unavailable, skipping fallback: %s", exc)
            return []

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                self._prepare_age_bypass_playwright(context)
                page.goto(self.map_url, wait_until="networkidle", timeout=60000)
                self._dismiss_age_gate_playwright(page)
                if self._is_age_gate_page(page.content()):
                    self.logger.warning("Maria-Ra: Playwright still sees age gate, reloading map")
                    page.goto(self.map_url, wait_until="networkidle", timeout=60000)
                    self._dismiss_age_gate_playwright(page)
                page.wait_for_timeout(3000)
                payload = page.evaluate(
                    """() => {
                        const collect = [];
                        const keys = Object.keys(window);
                        for (const key of keys) {
                          const value = window[key];
                          if (Array.isArray(value) && value.length && typeof value[0] === "object") {
                            const s = JSON.stringify(value[0] || {});
                            if (s.includes("address") || s.includes("coords") || s.includes("balloon")) {
                              collect.push(value);
                            }
                          }
                        }
                        if (collect.length) return collect[0];
                        return [];
                    }"""
                )
                context.close()
                browser.close()
                if isinstance(payload, list):
                    return [item for item in payload if isinstance(item, dict)]
        except Exception as exc:
            self.logger.warning("Maria-Ra: Playwright fallback failed, skipping: %s", exc)
        return []

    def _set_age_gate_cookies(self) -> None:
        """Set common age-confirmation cookies used by age gates."""
        cookie_variants = (
            ("is_adult", "1"),
            ("adult", "1"),
            ("age_verified", "1"),
            ("confirm18", "1"),
            ("age", "18"),
        )
        for name, value in cookie_variants:
            self.client.session.cookies.set(name, value, domain=".maria-ra.ru", path="/")
            self.client.session.cookies.set(name, value, domain="www.maria-ra.ru", path="/")

    @staticmethod
    def _is_age_gate_page(html: str) -> bool:
        text = re.sub(r"\s+", " ", html.lower())
        strict_markers = (
            "age-gate",
            "age_gate",
            "вам есть 18",
            "мне есть 18",
            "подтвердите возраст",
            "подтверждение возраста",
        )
        if any(marker in text for marker in strict_markers):
            return True
        return "18+" in text and ("подтверд" in text or "возраст" in text)

    def _prepare_age_bypass_playwright(self, context: Any) -> None:
        """Preseed common age-confirmation cookies before opening pages."""
        cookies = [
            {"name": "is_adult", "value": "1", "domain": ".maria-ra.ru", "path": "/"},
            {"name": "adult", "value": "1", "domain": ".maria-ra.ru", "path": "/"},
            {"name": "age_verified", "value": "1", "domain": ".maria-ra.ru", "path": "/"},
            {"name": "confirm18", "value": "1", "domain": ".maria-ra.ru", "path": "/"},
            {"name": "age", "value": "18", "domain": ".maria-ra.ru", "path": "/"},
        ]
        try:
            context.add_cookies(cookies)
        except Exception as exc:
            self.logger.info("Maria-Ra: Playwright cookie preseed failed: %s", exc)

    def _dismiss_age_gate_playwright(self, page: Any) -> None:
        """Try to confirm 18+ dialog via common selectors."""
        selectors = (
            "button:has-text('Да')",
            "button:has-text('Мне есть 18')",
            "button:has-text('Мне исполнилось 18')",
            "button:has-text('Подтвердить')",
            "a:has-text('Да')",
            ".age-confirm button",
            ".age-gate button",
            "[data-age-confirm]",
            "[data-confirm-age]",
        )
        for selector in selectors:
            try:
                if page.locator(selector).count() > 0:
                    page.locator(selector).first.click(timeout=1500)
                    page.wait_for_timeout(700)
                    if not self._is_age_gate_page(page.content()):
                        return
            except Exception:
                continue

    def _normalize_store(self, store: dict[str, Any]) -> StoreRecord:
        city_raw = store.get("city") if isinstance(store.get("city"), str) else None
        region_raw = store.get("region") if isinstance(store.get("region"), str) else None
        address_raw = store.get("address") if isinstance(store.get("address"), str) else None
        region_from_address, address_without_region = self._split_region_prefix(address_raw)
        city, address = self._clean_city_and_address(city_raw, address_without_region or address_raw)
        region = self._clean_region(region_raw) or self._clean_region(region_from_address)
        work_time = store.get("work_time") if isinstance(store.get("work_time"), str) else None
        lat, lng = self._extract_coords(store)
        source_url = self._build_source_url(address=address, latitude=lat, longitude=lng)

        phone = store.get("phone")
        if not isinstance(phone, str):
            phone = None
        store_format = store.get("format")
        store_format = self._clean_text(store_format) if isinstance(store_format, str) else None
        status = store.get("status")
        status = self._clean_text(status) if isinstance(status, str) else None

        return StoreRecord.build(
            network=self.NETWORK_NAME,
            region=region,
            city=city,
            address=address,
            work_time=work_time,
            lat=lat,
            lng=lng,
            phone=phone,
            store_format=store_format,
            status=status,
            source_url=source_url,
        )

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n,;")
        cleaned = re.sub(r"\.(?=[A-Za-zА-Яа-яЁё])", ". ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\)+\s*$", "", cleaned).strip(" ,;")
        return cleaned or None

    @staticmethod
    def _looks_like_address(value: str | None) -> bool:
        if not value:
            return False
        lowered = value.lower()
        address_patterns = (
            r"(?:^|[\s,])ул\.?(?:\s|$|[a-zа-яё])",
            r"\bулиц",
            r"(?:^|[\s,])пр-кт(?:\s|$|[a-zа-яё])",
            r"(?:^|[\s,])пр-т(?:\s|$|[a-zа-яё])",
            r"\bпросп(?:ект)?\b",
            r"(?:^|[\s,])пер\.?(?:\s|$|[a-zа-яё])",
            r"\bпереул",
            r"\bквартал\b",
            r"(?:^|[\s,])кв-л(?:\s|$|[a-zа-яё])",
            r"(?:^|[\s,])мкр\.?(?:\s|$|[a-zа-яё])",
            r"\bдом\b",
            r"(?:^|[\s,])д\.\s*\d",
            r"(?:^|[\s,])б-р(?:\s|$|[a-zа-яё])",
            r"(?:^|[\s,])бул\.?(?:\s|$|[a-zа-яё])",
            r"\bшоссе\b",
            r"\bтракт\b",
            r"\bпроезд\b",
            r"\bпр-д\b",
            r"\bнабереж",
            r"\bплощад",
            r"\bаллея\b",
        )
        return bool(re.search(r"\d", lowered) or any(re.search(pattern, lowered) for pattern in address_patterns))

    @staticmethod
    def _clean_region(value: str | None) -> str | None:
        cleaned = MariaRaParser._clean_text(value)
        if not cleaned:
            return None
        technical_regions = {
            "SELECTION_WINES",
            "COFFEE_FRAME",
            "ROUND_CLOCK_SERVICES",
            "OPENING_SOON",
        }
        cleaned_upper = cleaned.upper()
        cleaned_lower = cleaned.lower()
        if cleaned_upper in technical_regions:
            return None
        if any(token in cleaned_lower for token in ("selection_wines", "coffee_frame", "round_clock_services", "opening_soon")):
            return None
        if re.fullmatch(r"[A-Z0-9_]{3,}", cleaned):
            return None
        if MariaRaParser._looks_like_address(cleaned):
            return None
        if not re.search(r"[А-Яа-яЁё]", cleaned):
            return None
        return cleaned

    @staticmethod
    def _clean_city(value: str | None) -> str | None:
        cleaned = MariaRaParser._clean_text(value)
        if not cleaned:
            return None
        cleaned = re.sub(r"^(?:г\.?|город)\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.rstrip(")")
        cleaned = re.sub(r"\s*\)\s*$", "", cleaned).strip(" ,;")
        if MariaRaParser._looks_like_locality_name(cleaned):
            return cleaned or None
        if MariaRaParser._looks_like_address(cleaned):
            return None
        return cleaned or None

    @staticmethod
    def _clean_address(value: str | None, city_hint: str | None = None) -> str | None:
        cleaned = MariaRaParser._clean_text(value)
        if not cleaned:
            return None
        cleaned = re.sub(r"^(?:адрес(?: магазина)?)\s*[:\-]?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*;\s*", ", ", cleaned)
        cleaned = re.sub(r"\s+,", ",", cleaned)
        cleaned = re.sub(r",\s*,+", ", ", cleaned)
        cleaned = re.sub(r",(?=[^\s])", ", ", cleaned)
        if city_hint and "," in cleaned:
            left, right = [part.strip() for part in cleaned.split(",", 1)]
            normalized_left = MariaRaParser._clean_city(left) or left
            if MariaRaParser._normalize_text_token(normalized_left) == MariaRaParser._normalize_text_token(city_hint) and right:
                cleaned = right
        replacements = (
            (r"^ул\s+", "ул. "),
            (r"^пер\s+", "пер. "),
            (r"^пр[- ]?кт\s+", "пр-кт "),
            (r"^пр-т\s*", "пр-т "),
            (r"^просп(?:ект)?\s+", "просп. "),
            (r"^б[- ]?р\s+", "б-р "),
            (r"^бул\s+", "бул. "),
            (r"^мкр\s+", "мкр. "),
            (r"^кв[- ]?л\s+", "кв-л "),
            (r"^д\s+", "д. "),
        )
        for pattern, replacement in replacements:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;")
        if not re.search(r"[А-Яа-яЁё0-9]", cleaned):
            return None
        return cleaned

    @staticmethod
    def _normalize_text_token(value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-zа-я0-9]+", "", value.lower())

    @staticmethod
    def _clean_city_and_address(city: str | None, address: str | None) -> tuple[str | None, str | None]:
        cleaned_city = MariaRaParser._clean_text(city)
        cleaned_address = MariaRaParser._clean_address(address)
        original_address = cleaned_address
        preserve_full_address = False

        if not cleaned_city and cleaned_address:
            split_city, split_address = MariaRaParser._split_city_and_address(cleaned_address)
            if split_city:
                cleaned_city = split_city
            if split_address and MariaRaParser._is_informative_address_fragment(split_address):
                cleaned_address = split_address
            else:
                cleaned_address = original_address
                preserve_full_address = True

        if cleaned_city:
            split_city, split_address = MariaRaParser._split_city_and_address(cleaned_city)
            if split_city and split_address and split_city != cleaned_city:
                cleaned_city = split_city
                if not cleaned_address:
                    cleaned_address = split_address

            if "," in cleaned_city:
                left, right = [part.strip() for part in cleaned_city.split(",", 1)]
                if left and MariaRaParser._looks_like_address(right):
                    cleaned_city = left
                    if not cleaned_address:
                        cleaned_address = right

        normalized_city = MariaRaParser._clean_city(cleaned_city)
        normalized_address = MariaRaParser._clean_address(
            cleaned_address,
            city_hint=None if preserve_full_address else normalized_city,
        )
        return normalized_city, normalized_address

    @staticmethod
    def _extract_coords(store: dict[str, Any]) -> tuple[float | None, float | None]:
        lat = store.get("lat")
        lng = store.get("lng")
        if lat is None or lng is None:
            coords = store.get("coords") or store.get("coordinates")
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                lng, lat = coords[0], coords[1]  # GeoJSON order is [lng, lat]
        return MariaRaParser._to_float(lat), MariaRaParser._to_float(lng)

    def _build_source_url(
        self,
        *,
        address: str | None,
        latitude: float | None,
        longitude: float | None,
    ) -> str:
        if latitude is not None and longitude is not None:
            return f"{self.map_url}#store={latitude:.6f},{longitude:.6f}"
        address_token = self._normalize_text_token(address)
        if address_token:
            return f"{self.map_url}#store={address_token}"
        return self.map_url

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            if isinstance(value, str):
                value = value.replace(",", ".").strip()
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_informative_address_fragment(value: str | None) -> bool:
        if not value:
            return False
        return MariaRaParser._looks_like_address(value) and not bool(re.fullmatch(r"\d+[а-яa-z]?", value.strip(), flags=re.IGNORECASE))

    @staticmethod
    def _store_business_payload(store: StoreRecord) -> dict[str, Any]:
        data = store.to_dict()
        data.pop("collected_at", None)
        return data

    @classmethod
    def _store_completeness_score(cls, store: StoreRecord) -> int:
        return sum(
            1
            for value in cls._store_business_payload(store).values()
            if value not in (None, "")
        )

    @classmethod
    def _store_preference_key(cls, store: StoreRecord) -> tuple[int, int, tuple[str, ...]]:
        data = cls._store_business_payload(store)
        return (
            cls._store_completeness_score(store),
            len(str(data.get("address") or "")),
            tuple(str(value or "") for value in data.values()),
        )

    @classmethod
    def _deduplicate_normalized_stores(
        cls,
        stores: list[StoreRecord],
    ) -> tuple[list[StoreRecord], int, int]:
        deduped_by_key: dict[str, StoreRecord] = {}
        conflicting_keys: set[str] = set()
        for store in stores:
            stable_key = store.stable_key()
            existing = deduped_by_key.get(stable_key)
            if existing is None:
                deduped_by_key[stable_key] = store
                continue
            if cls._store_business_payload(existing) != cls._store_business_payload(store):
                conflicting_keys.add(stable_key)
            if cls._store_preference_key(store) >= cls._store_preference_key(existing):
                deduped_by_key[stable_key] = store
        deduped = sorted(
            deduped_by_key.values(),
            key=lambda store: tuple(str(value or "") for value in cls._store_business_payload(store).values()),
        )
        duplicate_rows = len(stores) - len(deduped)
        return deduped, duplicate_rows, len(conflicting_keys)
