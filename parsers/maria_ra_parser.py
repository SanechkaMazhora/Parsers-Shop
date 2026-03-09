"""Parser for Maria-Ra stores (embedded JS + Playwright fallback)."""

from __future__ import annotations

import json
import logging
import re
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
        try:
            html = self.client.get_text(self.map_url)
        except Exception as exc:
            self.logger.error("Maria-Ra: failed loading map page: %s", exc)
            return []

        stores_raw = self._extract_stores_from_html(html)
        if not stores_raw:
            self.logger.warning("Maria-Ra: no stores in inline JS, trying external JS")
            stores_raw = self._extract_stores_from_external_scripts(html)

        if not stores_raw:
            self.logger.warning("Maria-Ra: requests-based extraction failed, trying Playwright fallback")
            stores_raw = self._playwright_fallback()

        stores: list[StoreRecord] = []
        for item in stores_raw:
            try:
                stores.append(self._normalize_store(item))
            except Exception as exc:
                self.logger.warning("Maria-Ra: failed parsing one store: %s", exc)
        self.logger.info("Maria-Ra: parsed %s stores", len(stores))
        return stores

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

    def _extract_store_candidates_from_script(self, script: str) -> list[dict[str, Any]]:
        # 1) direct arrays: markers/stores/shops/features/points = [...]
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

        # 2) GeoJSON style object with features
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

    def _normalize_raw_js_item(self, raw: dict[str, Any]) -> dict[str, Any] | None:
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
        if candidate["address"] is None and candidate["coords"] is None and candidate["lat"] is None:
            return None
        return candidate

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
        try:
            return json.loads(cleaned)
        except Exception:
            return None

    def _playwright_fallback(self) -> list[dict[str, Any]]:
        """Fallback extraction using Playwright if JS parsing fails."""
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            self.logger.error("Maria-Ra: Playwright unavailable: %s", exc)
            return []

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(self.map_url, wait_until="networkidle", timeout=60000)
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
                browser.close()
                if isinstance(payload, list):
                    return [item for item in payload if isinstance(item, dict)]
        except Exception as exc:
            self.logger.error("Maria-Ra: Playwright fallback failed: %s", exc)
        return []

    def _normalize_store(self, store: dict[str, Any]) -> StoreRecord:
        city = store.get("city") if isinstance(store.get("city"), str) else None
        region = store.get("region") if isinstance(store.get("region"), str) else None
        address = store.get("address") if isinstance(store.get("address"), str) else None
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

