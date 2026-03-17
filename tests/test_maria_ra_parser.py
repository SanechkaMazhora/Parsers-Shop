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
