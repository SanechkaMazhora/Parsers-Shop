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
            name = raw.get("NAME") if isinstance(raw.get("NAME"), str) else None
            city, address = self._split_city_and_address(name)
            coord_pair = self._parse_coordinate_string(raw.get("COORDINATE"))
            work_time = self._build_work_time_from_parts(raw.get("STARTED_WORK"), raw.get("END_WORK"))
            return {
                "address": address,
                "city": city,
                "region": raw.get("SECTION") if isinstance(raw.get("SECTION"), str) else None,
                "work_time": work_time,
                "coords": coord_pair,
                "phone": None,
                "status": None,
                "format": None,
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
                "address": properties.get("address") or popup_data.get("address"),
                "city": properties.get("city") or popup_data.get("city"),
                "region": properties.get("region") or popup_data.get("region"),
                "work_time": properties.get("work_time") or properties.get("schedule") or popup_data.get("work_time"),
                "phone": properties.get("phone") or popup_data.get("phone"),
                "coords": coords,
            }

        # Direct flat objects
        popup_html = raw.get("popup") or raw.get("balloonContent") or raw.get("balloonContentBody")
        popup_data = self._parse_popup_content(popup_html if isinstance(popup_html, str) else "")
        candidate = {
            "address": raw.get("address") or raw.get("addr") or popup_data.get("address"),
            "city": raw.get("city") or raw.get("town") or raw.get("locality") or popup_data.get("city"),
            "region": raw.get("region") or popup_data.get("region"),
            "work_time": raw.get("work_time") or raw.get("schedule") or raw.get("workTime") or popup_data.get("work_time"),
            "phone": raw.get("phone") or popup_data.get("phone"),
            "lat": raw.get("lat"),
            "lng": raw.get("lng"),
            "coords": raw.get("coords") or raw.get("coordinates"),
            "status": raw.get("status"),
            "format": raw.get("format"),
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
        split_match = re.match(
            r"^(?:г\.?|город|пгт|пос\.?|п\.|рп|с\.|д\.п\.?)\s*([^,]+),\s*(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if split_match:
            return split_match.group(1).strip(), split_match.group(2).strip()

        # Sometimes city and address are merged without comma: "рп Кольцово ул.Центральная, 1".
        merged_match = re.match(
            r"^(?P<city>(?:г\.?|город|пгт|пос\.?|п\.|рп|с\.|д\.п\.?)\s*.+?)\s+"
            r"(?P<address>(?:ул\.|улица|пр-кт|просп|пер\.|переулок|мкр\.?|квартал|б-р|бул\.|д\.|дом).+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if merged_match:
            return merged_match.group("city").strip(), merged_match.group("address").strip()

        parts = [part.strip() for part in cleaned.split(",", 1)]
        if len(parts) == 2:
            city_guess = parts[0]
            if len(city_guess) <= 40:
                return city_guess, parts[1]
        return None, cleaned

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
        address = extract(r"(?:Адрес|Магазин)\s*[:\-]?\s*(.+)")
        work_time = extract(r"(?:Режим работы|Время работы)\s*[:\-]?\s*(.+)")
        phone = extract(r"(?:Телефон|Тел\.)\s*[:\-]?\s*(.+)")
        city = extract(r"(?:Город|Населенный пункт)\s*[:\-]?\s*(.+)")
        if address:
            result["address"] = address
        if work_time:
            result["work_time"] = work_time
        if phone:
            result["phone"] = phone
        if city:
            result["city"] = city
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
        city, address = self._clean_city_and_address(city_raw, address_raw)
        region = self._clean_region(region_raw)
        work_time = store.get("work_time") if isinstance(store.get("work_time"), str) else None
        lat, lng = self._extract_coords(store)

        phone = store.get("phone")
        if not isinstance(phone, str):
            phone = None
        store_format = store.get("format")
        if not isinstance(store_format, str):
            store_format = None
        status = store.get("status")
        if not isinstance(status, str):
            status = None

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
            source_url=self.map_url,
        )

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n,;")
        cleaned = re.sub(r"\)+\s*$", "", cleaned).strip(" ,;")
        return cleaned or None

    @staticmethod
    def _looks_like_address(value: str | None) -> bool:
        if not value:
            return False
        lowered = value.lower()
        markers = (
            "ул",
            "улиц",
            "пр-кт",
            "просп",
            "пер",
            "переул",
            "квартал",
            "мкр",
            "дом",
            "д.",
            "б-р",
            "бул",
            "шоссе",
        )
        return bool(re.search(r"\d", lowered) or any(marker in lowered for marker in markers))

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
        if cleaned in technical_regions:
            return None
        if re.fullmatch(r"[A-Z0-9_]{3,}", cleaned):
            return None
        if not re.search(r"[А-Яа-яЁё]", cleaned):
            return None
        return cleaned

    @staticmethod
    def _clean_city(value: str | None) -> str | None:
        cleaned = MariaRaParser._clean_text(value)
        if not cleaned:
            return None
        cleaned = cleaned.rstrip(")")
        cleaned = re.sub(r"\s*\)\s*$", "", cleaned).strip(" ,;")
        if MariaRaParser._looks_like_address(cleaned):
            return None
        return cleaned or None

    @staticmethod
    def _clean_address(value: str | None, city_hint: str | None = None) -> str | None:
        cleaned = MariaRaParser._clean_text(value)
        if not cleaned:
            return None
        if city_hint and "," in cleaned:
            left, right = [part.strip() for part in cleaned.split(",", 1)]
            if MariaRaParser._normalize_text_token(left) == MariaRaParser._normalize_text_token(city_hint) and right:
                cleaned = right
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

        if cleaned_city:
            # Handle merged city+address in one field.
            merged = re.match(
                r"^(?P<city>(?:г\.?|город|пгт|пос\.?|п\.|рп|с\.|д\.п\.?)\s*.+?)\s+"
                r"(?P<address>(?:ул\.|улица|пр-кт|просп|пер\.|переулок|мкр\.?|квартал|б-р|бул\.|д\.|дом).+)$",
                cleaned_city,
                flags=re.IGNORECASE,
            )
            if merged:
                cleaned_city = merged.group("city").strip()
                if not cleaned_address:
                    cleaned_address = merged.group("address").strip()

            if "," in cleaned_city:
                left, right = [part.strip() for part in cleaned_city.split(",", 1)]
                if left and MariaRaParser._looks_like_address(right):
                    cleaned_city = left
                    if not cleaned_address:
                        cleaned_address = right

        normalized_city = MariaRaParser._clean_city(cleaned_city)
        normalized_address = MariaRaParser._clean_address(cleaned_address, city_hint=normalized_city)
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

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
