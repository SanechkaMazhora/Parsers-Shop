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
