"""Parser for Krasnoe & Beloe (REST API JSON)."""

from __future__ import annotations

import logging
from typing import Any

from core.http_client import HttpClient
from core.models import StoreRecord


class KBParser:
    """Parse stores from Krasnoe & Beloe API."""

    NETWORK_NAME = "Красное & Белое"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.base_url = "https://krasnoeibeloe.ru"
        self._city_endpoint_candidates = (
            f"{self.base_url}/api/cities/list/",
        )

    def parse(self) -> list[StoreRecord]:
        """Collect and normalize all stores."""
        stores: list[StoreRecord] = []
        cities = self._load_cities()
        self.logger.info("KB: loaded %s cities", len(cities))

        for city in cities:
            city_id = city.get("id")
            city_name = self._extract_city_name(city)
            region = self._extract_region_name(city) or self._derive_region_from_city(city)
            if city_id is None:
                self.logger.warning("KB: skip city without id: %s", city)
                continue
            try:
                city_stores = self._load_city_stores(int(city_id))
            except Exception as exc:
                self.logger.error("KB: failed city=%s id=%s: %s", city_name, city_id, exc)
                continue
            for shop in city_stores:
                if not isinstance(shop, dict):
                    continue
                try:
                    stores.append(
                        self._normalize_shop(
                            shop,
                            city_id=int(city_id),
                            city_name=city_name if isinstance(city_name, str) else None,
                            region=region if isinstance(region, str) else None,
                        )
                    )
                except Exception as exc:
                    self.logger.warning("KB: failed parsing one shop city=%s: %s", city_name, exc)
        return stores

    def _load_cities(self) -> list[dict[str, Any]]:
        for url in self._city_endpoint_candidates:
            try:
                payload = self.client.get_json(url)
                cities = self._extract_city_list(payload)
                if cities:
                    region_lookup = self._extract_region_lookup(payload)
                    self._enrich_cities_with_region(cities, region_lookup)
                    return cities
            except Exception as exc:
                self.logger.warning("KB: cities endpoint failed %s: %s", url, exc)
                continue
        self.logger.warning("KB: cities endpoint not found")
        return []

    def _load_city_stores(self, city_id: int) -> list[dict[str, Any]]:
        url = f"{self.base_url}/api/cities/{city_id}/shops/"
        payload = self.client.get_json(url)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("shops", "data", "items", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_city_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        direct = payload.get("cities")
        if isinstance(direct, list):
            return [item for item in direct if isinstance(item, dict)]
        for key in ("data", "result", "items"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                nested_cities = nested.get("cities")
                if isinstance(nested_cities, list):
                    return [item for item in nested_cities if isinstance(item, dict)]
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_region_lookup(payload: Any) -> dict[int, str]:
        if not isinstance(payload, dict):
            return {}
        regions = payload.get("regions")
        if not isinstance(regions, list):
            return {}
        lookup: dict[int, str] = {}
        for item in regions:
            if not isinstance(item, dict):
                continue
            region_id = item.get("id")
            region_name = item.get("name")
            if isinstance(region_id, (int, float)) and isinstance(region_name, str) and region_name.strip():
                lookup[int(region_id)] = region_name.strip()
        return lookup

    @staticmethod
    def _enrich_cities_with_region(cities: list[dict[str, Any]], region_lookup: dict[int, str]) -> None:
        if not region_lookup:
            return
        for city in cities:
            if not isinstance(city, dict):
                continue
            if isinstance(city.get("regionName"), str) and city.get("regionName", "").strip():
                continue
            region_id = city.get("regionId") or city.get("region_id")
            if isinstance(region_id, (int, float)):
                mapped = region_lookup.get(int(region_id))
                if mapped:
                    city["regionName"] = mapped

    @staticmethod
    def _format_work_time(raw: Any) -> str | None:
        if raw is None:
            return None
        if isinstance(raw, str):
            return raw.strip() or None
        if isinstance(raw, dict):
            week = raw.get("week")
            if isinstance(week, list) and len(week) >= 2:
                return f"{week[0]}-{week[1]}"
            if isinstance(week, str):
                return week.strip() or None
            for key in ("all", "daily", "value"):
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return None
        return None

    @staticmethod
    def _extract_phone(shop: dict[str, Any]) -> str | None:
        if isinstance(shop.get("phone"), str):
            return shop.get("phone")
        phones = shop.get("phones")
        if isinstance(phones, list):
            first = next((str(p).strip() for p in phones if str(p).strip()), None)
            return first
        return None

    def _normalize_shop(
        self,
        shop: dict[str, Any],
        *,
        city_id: int,
        city_name: str | None,
        region: str | None,
    ) -> StoreRecord:
        source_url = f"{self.base_url}/api/cities/{city_id}/shops/"
        resolved_city = self._extract_city_name(shop) or city_name
        resolved_region = self._extract_region_name(shop) or region
        return StoreRecord.build(
            network=self.NETWORK_NAME,
            region=resolved_region,
            city=resolved_city,
            address=shop.get("address") if isinstance(shop.get("address"), str) else None,
            work_time=self._format_work_time(shop.get("workTime")),
            lat=self._to_float(shop.get("lat")),
            lng=self._to_float(shop.get("lng")),
            phone=self._extract_phone(shop),
            store_format=shop.get("format") if isinstance(shop.get("format"), str) else None,
            status=shop.get("status") if isinstance(shop.get("status"), str) else None,
            source_url=source_url,
        )

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_city_name(payload: dict[str, Any]) -> str | None:
        for key in ("city", "cityName", "name", "town", "locality"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_region_name(payload: dict[str, Any]) -> str | None:
        for key in ("region", "regionName", "regionTitle", "area", "district"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested_region = payload.get("region")
        if isinstance(nested_region, dict):
            nested_name = nested_region.get("name")
            if isinstance(nested_name, str) and nested_name.strip():
                return nested_name.strip()
        return None

    @staticmethod
    def _derive_region_from_city(city_payload: dict[str, Any]) -> str | None:
        """Build a fallback region value from city metadata when name is missing."""
        explicit_name = city_payload.get("regionName") or city_payload.get("region_name")
        if isinstance(explicit_name, str) and explicit_name.strip():
            return explicit_name.strip()
        nested_region = city_payload.get("region")
        if isinstance(nested_region, dict):
            nested_name = nested_region.get("name")
            if isinstance(nested_name, str) and nested_name.strip():
                return nested_name.strip()
        region_id = city_payload.get("regionId") or city_payload.get("region_id")
        if region_id is None:
            return None
        if isinstance(region_id, (int, float)):
            return f"Регион #{int(region_id)}"
        if isinstance(region_id, str) and region_id.strip():
            return f"Регион #{region_id.strip()}"
        return None
