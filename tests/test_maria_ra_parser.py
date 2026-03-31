from __future__ import annotations

import builtins

from parsers.maria_ra_parser import MariaRaParser


def test_age_gate_detection() -> None:
    assert MariaRaParser._is_age_gate_page("<html>Вам есть 18+ ?</html>")
    assert not MariaRaParser._is_age_gate_page("<html><body>Карта сети</body></html>")


def test_playwright_fallback_is_graceful_when_import_fails(monkeypatch, caplog) -> None:
    original_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if name.startswith("playwright"):
            raise OSError("libnspr4.so: cannot open shared object file")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    parser = MariaRaParser(client=None)

    with caplog.at_level("WARNING"):
        stores = parser._playwright_fallback()

    assert stores == []
    assert any("Playwright unavailable, skipping fallback" in record.message for record in caplog.records)


def test_clean_region_filters_technical_tokens() -> None:
    assert MariaRaParser._clean_region("SELECTION_WINES") is None
    assert MariaRaParser._clean_region("selection_wines") is None
    assert MariaRaParser._clean_region("ROUND_CLOCK_SERVICES") is None
    assert MariaRaParser._clean_region("Новосибирская область") == "Новосибирская область"
    assert MariaRaParser._clean_region("ул. Ленина, 1") is None


def test_clean_city_and_address_splits_merged_city_string() -> None:
    city, address = MariaRaParser._clean_city_and_address("рп Кольцово ул.Центральная, 5", None)

    assert city == "рп Кольцово"
    assert address == "ул. Центральная, 5"


def test_clean_city_strips_trailing_parenthesis_noise() -> None:
    city, address = MariaRaParser._clean_city_and_address("п. Победа)", "ул. Школьная, 1")

    assert city == "п. Победа"
    assert address == "ул. Школьная, 1"


def test_clean_city_keeps_explicit_locality_prefix_from_source_field() -> None:
    assert MariaRaParser._clean_city("с. Первомайское,") == "с. Первомайское"


def test_clean_city_and_address_extracts_city_from_address_when_city_missing() -> None:
    city, address = MariaRaParser._clean_city_and_address(None, "г. Новосибирск, ул. Советская, 10")

    assert city == "Новосибирск"
    assert address == "ул. Советская, 10"


def test_clean_city_and_address_does_not_invent_city_from_street_name() -> None:
    city, address = MariaRaParser._clean_city_and_address(None, "Змеиногорский тракт, 71в")

    assert city is None
    assert address == "Змеиногорский тракт, 71в"


def test_clean_city_and_address_keeps_full_address_when_only_house_number_remains() -> None:
    city, address = MariaRaParser._clean_city_and_address(None, "п. Научный городок, 30")

    assert city == "п. Научный городок"
    assert address == "п. Научный городок, 30"


def test_clean_city_and_address_extracts_locality_when_address_has_street_part() -> None:
    city, address = MariaRaParser._clean_city_and_address(None, "п.Казенная Заимка, ул.Кольцевая, 11а")

    assert city == "п. Казенная Заимка"
    assert address == "ул. Кольцевая, 11а"


def test_clean_city_and_address_extracts_village_prefix_with_dot() -> None:
    city, address = MariaRaParser._clean_city_and_address(None, "д. Бурмистрово, ул. Центральная, 30б")

    assert city == "д. Бурмистрово"
    assert address == "ул. Центральная, 30б"


def test_clean_city_and_address_extracts_urban_settlement_prefix_with_spaces() -> None:
    city, address = MariaRaParser._clean_city_and_address(None, "р. п. Горный, ул. Космическая, 10/2")

    assert city == "р. п. Горный"
    assert address == "ул. Космическая, 10/2"


def test_clean_city_and_address_extracts_station_prefix() -> None:
    city, address = MariaRaParser._clean_city_and_address(None, "ст. Мочище, ул. Линейная, 64")

    assert city == "ст. Мочище"
    assert address == "ул. Линейная, 64"


def test_clean_city_and_address_splits_merged_city_with_tract_address() -> None:
    city, address = MariaRaParser._clean_city_and_address("г Барнаул Павловский тракт, 188", None)

    assert city == "Барнаул"
    assert address == "Павловский тракт, 188"


def test_clean_address_normalizes_obvious_noise() -> None:
    assert MariaRaParser._clean_address(" Адрес магазина: ул.Ленина,, 1; ") == "ул. Ленина, 1"


def test_normalize_store_builds_unique_source_url_from_coordinates() -> None:
    parser = MariaRaParser(client=None)

    record = parser._normalize_store(
        {
            "city": "Новосибирск",
            "address": "ул. Ленина, 1",
            "coords": [82.92, 55.03],
        }
    )

    assert record.source_url == "https://www.maria-ra.ru/o-kompanii/karta-seti/#store=55.030000,82.920000"


def test_normalize_store_extracts_region_and_city_from_address_prefix() -> None:
    parser = MariaRaParser(client=None)

    record = parser._normalize_store(
        {
            "address": "Алтайский край, г. Барнаул, ул. Попова, 1",
        }
    )

    assert record.region == "Алтайский край"
    assert record.city == "Барнаул"
    assert record.address == "ул. Попова, 1"


def test_normalize_store_keeps_explicit_locality_prefixed_city_from_source_field() -> None:
    parser = MariaRaParser(client=None)

    record = parser._normalize_store(
        {
            "city": "с. Первомайское,",
            "address": "ул. Ленинская, 23",
            "coords": [86.22733, 57.07005],
        }
    )

    assert record.city == "с. Первомайское"
    assert record.address == "ул. Ленинская, 23"


def test_normalize_store_keeps_missing_optional_fields_as_none() -> None:
    parser = MariaRaParser(client=None)

    record = parser._normalize_store(
        {
            "address": "Змеиногорский тракт, 71в",
        }
    )

    assert record.region is None
    assert record.city is None
    assert record.address == "Змеиногорский тракт, 71в"
    assert record.latitude is None
    assert record.longitude is None
    assert record.store_format is None
    assert record.status is None


def test_normalize_raw_js_item_extracts_popup_metadata_when_present() -> None:
    parser = MariaRaParser(client=None)

    raw_item = {
        "popup": """
            <div>
              Город: Бийск<br>
              Регион: Алтайский край<br>
              Адрес магазина: ул. Ленина, 1<br>
              Формат магазина: Супермаркет<br>
              Статус: Открыт<br>
              Телефон: 8-800-123-45-67
            </div>
        """,
        "lat": "52,54",
        "lng": "85.21",
    }

    normalized = parser._normalize_raw_js_item(raw_item)

    assert normalized is not None
    record = parser._normalize_store(normalized)

    assert record.city == "Бийск"
    assert record.region == "Алтайский край"
    assert record.address == "ул. Ленина, 1"
    assert record.latitude == 52.54
    assert record.longitude == 85.21
    assert record.phone == "8-800-123-45-67"
    assert record.store_format == "Супермаркет"
    assert record.status == "Открыт"


def test_normalize_raw_js_item_with_partial_popup_keeps_missing_fields_as_none() -> None:
    parser = MariaRaParser(client=None)

    raw_item = {
        "popup": """
            <div>
              Город: г. Новосибирск<br>
              Адрес магазина: г. Новосибирск, ул.Ленина,, 1;
            </div>
        """,
    }

    normalized = parser._normalize_raw_js_item(raw_item)

    assert normalized is not None
    record = parser._normalize_store(normalized)

    assert record.city == "Новосибирск"
    assert record.address == "ул. Ленина, 1"
    assert record.region is None
    assert record.work_time is None
    assert record.latitude is None
    assert record.longitude is None
    assert record.phone is None
    assert record.store_format is None
    assert record.status is None


def test_deduplicate_normalized_stores_collapses_duplicate_stable_key_and_tracks_conflict() -> None:
    parser = MariaRaParser(client=None)
    stores = [
        parser._normalize_store(
            {
                "city": "г. Новосибирск",
                "address": "ул.Плющихинская, 6",
                "work_time": "8:00-22:00",
                "coords": [83.00199, 55.01444],
            }
        ),
        parser._normalize_store(
            {
                "city": "г. Новосибирск",
                "address": "ул Плющихинская, д. 6",
                "work_time": "9:00-22:00",
                "coords": [83.00199, 55.01444],
            }
        ),
    ]

    deduped, duplicate_rows, conflicting_duplicates = parser._deduplicate_normalized_stores(stores)

    assert len(deduped) == 1
    assert duplicate_rows == 1
    assert conflicting_duplicates == 1
    assert deduped[0].city == "Новосибирск"
