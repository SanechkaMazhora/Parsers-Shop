from __future__ import annotations

from pathlib import Path
import json
from uuid import uuid4

from core.diff import build_snapshot_rows, compute_diff, load_snapshot, save_snapshot
from core.models import StoreRecord, build_store_stable_key


def _make_store(
    *,
    network: str = "n1",
    city: str = "c1",
    address: str = "a1",
    work_time: str | None = None,
    source_url: str = "https://example.com/store/1",
    latitude: float | None = None,
    longitude: float | None = None,
) -> StoreRecord:
    return StoreRecord.build(
        network=network,
        city=city,
        address=address,
        work_time=work_time,
        source_url=source_url,
        latitude=latitude,
        longitude=longitude,
    )


def test_diff_detects_added_removed_and_changed() -> None:
    previous_snapshot = build_snapshot_rows(
        [
            _make_store(address="a1", work_time="09:00-18:00", source_url="https://example.com/store/1"),
            _make_store(address="a2", source_url="https://example.com/store/2"),
        ]
    )
    current_snapshot = build_snapshot_rows(
        [
            _make_store(address="a1", work_time="10:00-20:00", source_url="https://example.com/store/1"),
            _make_store(address="a3", source_url="https://example.com/store/3"),
        ]
    )

    diff_result = compute_diff(previous_snapshot=previous_snapshot, current_snapshot=current_snapshot)

    assert len(diff_result.added) == 1
    assert len(diff_result.removed) == 1
    assert len(diff_result.changed) == 1
    assert diff_result.changed[0].change_type == "changed"
    assert diff_result.changed[0].changed_fields == ["work_time"]


def test_diff_uses_stable_key_when_address_changes_but_source_url_is_same() -> None:
    previous_snapshot = build_snapshot_rows(
        [
            _make_store(
                city="Novosibirsk",
                address="ул. Ленина, 1",
                work_time="09:00-18:00",
                source_url="https://example.com/store/1",
            )
        ]
    )
    current_snapshot = build_snapshot_rows(
        [
            _make_store(
                city="Novosibirsk",
                address="ул. Ленина, 1А",
                work_time="09:00-18:00",
                source_url="https://example.com/store/1",
            )
        ]
    )

    diff_result = compute_diff(previous_snapshot=previous_snapshot, current_snapshot=current_snapshot)

    assert not diff_result.added
    assert not diff_result.removed
    assert len(diff_result.changed) == 1
    assert diff_result.changed[0].changed_fields == ["address"]


def test_diff_ignores_monetka_source_url_alias_changes_for_same_store_id() -> None:
    previous_snapshot = build_snapshot_rows(
        [
            _make_store(
                network="Монетка",
                city="Кушва",
                address="ул. Ленина, 1",
                source_url="https://www.monetka.ru/shops_map/ekb/1004",
            )
        ]
    )
    current_snapshot = build_snapshot_rows(
        [
            _make_store(
                network="Монетка",
                city="Кушва",
                address="ул. Ленина, 1",
                source_url="https://www.monetka.ru/shops_map/votkinsk/1004",
            )
        ]
    )

    diff_result = compute_diff(previous_snapshot=previous_snapshot, current_snapshot=current_snapshot)

    assert not diff_result.added
    assert not diff_result.removed
    assert not diff_result.changed


def test_snapshot_roundtrip_preserves_stable_keys() -> None:
    stores = [
        _make_store(
            city="Novosibirsk",
            address="ул. Ленина, 1",
            source_url="https://example.com/store/1",
            latitude=55.03,
            longitude=82.92,
        )
    ]
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / f"test_snapshot_{uuid4().hex}.json"

    try:
        save_snapshot(stores, snapshot_path)
        loaded_snapshot = load_snapshot(snapshot_path)

        assert len(loaded_snapshot) == 1
        assert loaded_snapshot[0]["stable_key"] == stores[0].stable_key()
        assert loaded_snapshot[0]["latitude"] == 55.03
        assert loaded_snapshot[0]["longitude"] == 82.92
    finally:
        if snapshot_path.exists():
            snapshot_path.unlink()


def test_diff_can_mark_initial_snapshot_without_added_noise() -> None:
    current_snapshot = build_snapshot_rows(
        [
            _make_store(
                city="Novosibirsk",
                address="ул. Ленина, 1",
                source_url="https://example.com/store/1",
            )
        ]
    )

    diff_result = compute_diff(
        previous_snapshot=[],
        current_snapshot=current_snapshot,
        treat_as_initial=True,
        snapshot_status="missing",
    )

    assert diff_result.is_initial_snapshot is True
    assert diff_result.snapshot_status == "missing"
    assert diff_result.to_rows() == []


def test_load_snapshot_recomputes_stable_key_from_row_data() -> None:
    old_row = {
        "network": "Монетка",
        "region": "Свердловская область",
        "city": "Кушва",
        "address": "ул. Ленина, 1",
        "work_time": None,
        "latitude": None,
        "longitude": None,
        "phone": None,
        "store_format": None,
        "status": None,
        "source_url": "https://www.monetka.ru/shops_map/votkinsk/1004",
        "collected_at": "2026-03-17T00:00:00+00:00",
        "stable_key": "legacy-bad-key",
    }

    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / f"test_snapshot_recompute_{uuid4().hex}.json"

    try:
        snapshot_path.write_text(
            json.dumps({"schema_version": 1, "saved_at": "2026-03-17T00:00:00+00:00", "stores": [old_row]}),
            encoding="utf-8",
        )

        loaded_snapshot = load_snapshot(snapshot_path)

        assert loaded_snapshot[0]["stable_key"] == build_store_stable_key(old_row)
        assert loaded_snapshot[0]["stable_key"] != "legacy-bad-key"
    finally:
        if snapshot_path.exists():
            snapshot_path.unlink()
