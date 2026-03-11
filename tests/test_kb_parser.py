from __future__ import annotations

from parsers.kb_parser import KBParser


def test_kb_city_endpoints_use_api_cities_list_strategy() -> None:
    parser = KBParser(client=None)

    assert any("/api/cities/list" in endpoint for endpoint in parser._city_endpoint_candidates)
    assert all("/address/list" not in endpoint for endpoint in parser._city_endpoint_candidates)


def test_extract_city_name_prefers_city_fields() -> None:
    assert KBParser._extract_city_name({"cityName": "Томск"}) == "Томск"
    assert KBParser._extract_city_name({"name": "Омск"}) == "Омск"
    assert KBParser._extract_city_name({"town": "Барнаул"}) == "Барнаул"


def test_extract_region_name_prefers_region_fields() -> None:
    assert KBParser._extract_region_name({"regionName": "Томская область"}) == "Томская область"
    assert KBParser._extract_region_name({"region": "Алтайский край"}) == "Алтайский край"
    assert KBParser._extract_region_name({"area": "УРФО"}) == "УРФО"


def test_normalize_shop_uses_shop_city_region_as_priority() -> None:
    parser = KBParser(client=None)
    shop = {
        "address": "ул. Ленина, 1",
        "cityName": "Новосибирск",
        "regionName": "Новосибирская область",
        "lat": 55.03,
        "lng": 82.92,
        "workTime": {"week": ["09:00", "22:00"]},
    }

    record = parser._normalize_shop(
        shop,
        city_id=1,
        city_name="Fallback City",
        region="Fallback Region",
    )

    assert record.city == "Новосибирск"
    assert record.region == "Новосибирская область"


def test_extract_city_list_filters_shop_like_payload() -> None:
    payload = [
        {"id": 1, "name": "Томск", "regionId": 10},
        {"id": 2, "address": "ул. Ленина, 1", "cityId": 1, "lat": 55.0, "lng": 82.0},
    ]

    cities = KBParser._extract_city_list(payload)

    assert len(cities) == 1
    assert cities[0]["name"] == "Томск"


def test_parse_deduplicates_stores_by_network_city_address() -> None:
    class FakeClient:
        def get_json(self, url: str):  # type: ignore[no-untyped-def]
            if "cities/list" in url:
                return {
                    "cities": [
                        {"id": 1, "name": "Томск", "regionId": 10},
                        {"id": 1, "name": "Томск", "regionId": 10},
                    ],
                    "regions": [{"id": 10, "name": "Томская область"}],
                }
            if "/api/cities/1/shops/" in url:
                return [
                    {"id": 101, "address": "ул. Ленина, 1"},
                    {"id": 102, "address": "ул. Ленина, 1"},
                ]
            return []

    parser = KBParser(client=FakeClient())

    stores = parser.parse()

    assert len(stores) == 1
    assert stores[0].city == "Томск"
    assert stores[0].region == "Томская область"
