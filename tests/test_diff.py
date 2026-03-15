from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from core.diff import build_snapshot_rows, compute_diff, load_snapshot, save_snapshot
from core.models import StoreRecord


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
