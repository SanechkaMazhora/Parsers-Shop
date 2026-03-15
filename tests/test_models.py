from __future__ import annotations

from core.models import StoreRecord


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

    expected_keys = {
        "network",
        "region",
        "city",
        "address",
        "work_time",
        "latitude",
        "longitude",
        "phone",
        "store_format",
        "status",
        "source_url",
        "collected_at",
    }
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
