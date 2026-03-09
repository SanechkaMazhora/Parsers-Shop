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
    assert isinstance(record.parsed_at, str)


def test_store_record_to_dict_contains_all_keys() -> None:
    record = StoreRecord.build(network="N", source_url="https://example.com")
    data = record.to_dict()

    expected_keys = {
        "network",
        "region",
        "city",
        "address",
        "work_time",
        "lat",
        "lng",
        "phone",
        "store_format",
        "status",
        "source_url",
        "parsed_at",
    }
    assert set(data.keys()) == expected_keys
