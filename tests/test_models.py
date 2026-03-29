from __future__ import annotations

from core.models import STORE_OUTPUT_COLUMNS, StoreRecord, normalize_store_output_row


def test_store_record_build_sets_required_fields() -> None:
    record = StoreRecord.build(
        network="Test Network",
        city="Novosibirsk",
        address="Lenina 1",
        source_url="https://example.com/store/1",
    )

    assert record.network == "Test Network"
    assert record.city == "Novosibirsk"
    assert record.address == "Lenina 1"
    assert record.source_url == "https://example.com/store/1"
    assert isinstance(record.collected_at, str)
    assert record.parsed_at == record.collected_at


def test_store_record_to_dict_contains_all_keys() -> None:
    record = StoreRecord.build(network="N", source_url="https://example.com")
    data = record.to_dict()

    expected_keys = set(STORE_OUTPUT_COLUMNS)
    assert set(data.keys()) == expected_keys


def test_store_record_build_normalizes_address_and_legacy_aliases() -> None:
    record = StoreRecord.build(
        network="N",
        city="Novosibirsk",
        address=" Novosibirsk,  ул. Ленина, 1 ",
        lat="55.03",
        lng="82.92",
        source_url="https://example.com/store/1",
    )

    assert record.address == "ул. Ленина, 1"
    assert record.latitude == 55.03
    assert record.longitude == 82.92
    assert record.lat == 55.03
    assert record.lng == 82.92


def test_store_record_stable_key_is_same_for_monetka_store_alias_urls() -> None:
    first = StoreRecord.build(
        network="Монетка",
        city="Кушва",
        address="ул. Ленина, 1",
        source_url="https://www.monetka.ru/shops_map/ekb/1004",
    )
    second = StoreRecord.build(
        network="Монетка",
        city="Кушва",
        address="ул. Ленина, 1",
        source_url="https://www.monetka.ru/shops_map/votkinsk/1004",
    )

    assert first.stable_key() == second.stable_key()


def test_normalize_store_output_row_maps_legacy_aliases_to_canonical_schema() -> None:
    row = normalize_store_output_row(
        {
            "network": "N",
            "city": "Novosibirsk",
            "address": " Novosibirsk, ул. Ленина, 1 ",
            "lat": "55.03",
            "lng": "82.92",
            "parsed_at": "2026-03-17T00:00:00+00:00",
            "source_url": "https://example.com/store/1",
        }
    )

    assert list(row.keys()) == STORE_OUTPUT_COLUMNS
    assert row["address"] == "ул. Ленина, 1"
    assert row["latitude"] == 55.03
    assert row["longitude"] == 82.92
    assert row["collected_at"] == "2026-03-17T00:00:00+00:00"


def test_store_record_build_keeps_locality_prefix_when_only_house_number_remains() -> None:
    record = StoreRecord.build(
        network="N",
        city="Береславка п",
        address="Береславка п, 1А",
        source_url="https://example.com/store/1",
    )

    assert record.address == "Береславка п, 1А"


def test_normalize_store_output_row_keeps_full_address_when_city_prefix_is_required() -> None:
    row = normalize_store_output_row(
        {
            "network": "N",
            "city": "рп Краснообск",
            "address": "рп Краснообск, 207",
            "source_url": "https://example.com/store/1",
        }
    )

    assert row["address"] == "рп Краснообск, 207"
