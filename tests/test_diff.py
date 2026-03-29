from __future__ import annotations

from pathlib import Path
import json
from uuid import uuid4

from core.diff import build_snapshot_rows, compute_diff, load_snapshot, save_snapshot
from core.models import STORE_OUTPUT_COLUMNS, STORE_SNAPSHOT_COLUMNS, StoreRecord, build_store_stable_key


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


def test_diff_returns_no_changes_for_identical_snapshots() -> None:
    snapshot = build_snapshot_rows(
        [
            _make_store(
                network="n1",
                city="c1",
                address="a1",
                work_time="09:00-18:00",
                source_url="https://example.com/store/1",
                latitude=55.03,
                longitude=82.92,
            )
        ]
    )

    diff_result = compute_diff(previous_snapshot=snapshot, current_snapshot=snapshot)

    assert not diff_result.added
    assert not diff_result.removed
    assert not diff_result.changed
    assert diff_result.to_rows() == []


def test_diff_ignores_collected_at_only_changes() -> None:
    previous_snapshot = [
        {
            "network": "n1",
            "region": None,
            "city": "c1",
            "address": "a1",
            "work_time": "09:00-18:00",
            "latitude": None,
            "longitude": None,
            "phone": None,
            "store_format": None,
            "status": None,
            "source_url": "https://example.com/store/1",
            "collected_at": "2026-03-28T00:00:00+00:00",
        }
    ]
    current_snapshot = [
        {
            "network": "n1",
            "region": None,
            "city": "c1",
            "address": "a1",
            "work_time": "09:00-18:00",
            "latitude": None,
            "longitude": None,
            "phone": None,
            "store_format": None,
            "status": None,
            "source_url": "https://example.com/store/1",
            "collected_at": "2026-03-29T00:00:00+00:00",
        }
    ]

    diff_result = compute_diff(previous_snapshot=previous_snapshot, current_snapshot=current_snapshot)

    assert not diff_result.added
    assert not diff_result.removed
    assert not diff_result.changed
    assert diff_result.to_rows() == []


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


def test_diff_prefers_richer_row_when_snapshot_contains_duplicate_stable_key() -> None:
    previous_snapshot = build_snapshot_rows(
        [
            _make_store(
                network="n1",
                city="c1",
                address="a1",
                work_time="09:00-18:00",
                source_url="https://example.com/store/1",
            )
        ]
    )
    richer_current_row = _make_store(
        network="n1",
        city="c1",
        address="a1",
        work_time="10:00-20:00",
        source_url="https://example.com/store/1",
    ).to_snapshot_dict()
    poorer_current_row = _make_store(
        network="n1",
        city="c1",
        address="a1",
        work_time=None,
        source_url="https://example.com/store/1",
    ).to_snapshot_dict()

    diff_result = compute_diff(
        previous_snapshot=previous_snapshot,
        current_snapshot=[poorer_current_row, richer_current_row],
    )

    assert not diff_result.added
    assert not diff_result.removed
    assert len(diff_result.changed) == 1
    assert diff_result.changed[0].changed_fields == ["work_time"]
    assert diff_result.changed[0].new_value == {"work_time": "10:00-20:00"}


def test_diff_rows_keep_added_removed_changed_order_and_stable_detected_at() -> None:
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

    rows_first = diff_result.to_rows()
    rows_second = diff_result.to_rows()

    assert [row["change_type"] for row in rows_first] == ["added", "removed", "changed"]
    assert rows_first == rows_second
    assert len({row["detected_at"] for row in rows_first}) == 1


def test_diff_added_and_removed_payloads_use_canonical_schema_only() -> None:
    previous_snapshot = build_snapshot_rows(
        [
            StoreRecord.build(
                network="n1",
                region="r1",
                city="c1",
                address="a1",
                work_time="09:00-18:00",
                latitude=55.03,
                longitude=82.92,
                phone="8-800-111-11-11",
                store_format="Супермаркет",
                status="Открыт",
                source_url="https://example.com/store/1",
                collected_at="2026-03-28T00:00:00+00:00",
            )
        ]
    )
    current_snapshot = build_snapshot_rows(
        [
            StoreRecord.build(
                network="n1",
                region="r2",
                city="c2",
                address="a2",
                work_time="10:00-20:00",
                latitude=56.03,
                longitude=83.92,
                phone="8-800-222-22-22",
                store_format="Минимаркет",
                status="Закрыт",
                source_url="https://example.com/store/2",
                collected_at="2026-03-29T00:00:00+00:00",
            )
        ]
    )

    diff_result = compute_diff(previous_snapshot=previous_snapshot, current_snapshot=current_snapshot)
    rows = diff_result.to_rows()
    added_row = next(row for row in rows if row["change_type"] == "added")
    removed_row = next(row for row in rows if row["change_type"] == "removed")
    added_payload = json.loads(added_row["new_value"])
    removed_payload = json.loads(removed_row["old_value"])

    assert set(added_payload.keys()) == set(STORE_OUTPUT_COLUMNS)
    assert set(removed_payload.keys()) == set(STORE_OUTPUT_COLUMNS)
    assert "lat" not in added_payload and "lng" not in added_payload and "parsed_at" not in added_payload
    assert "lat" not in removed_payload and "lng" not in removed_payload and "parsed_at" not in removed_payload


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
        assert list(loaded_snapshot[0].keys()) == STORE_SNAPSHOT_COLUMNS
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


def test_load_snapshot_maps_legacy_schema_aliases_to_canonical_fields() -> None:
    legacy_row = {
        "network": "Test Network",
        "region": "Новосибирская область",
        "city": "Новосибирск",
        "address": "ул. Ленина, 1",
        "work_time": None,
        "lat": "55.03",
        "lng": "82.92",
        "phone": None,
        "store_format": None,
        "status": None,
        "source_url": "https://example.com/store/1",
        "parsed_at": "2026-03-17T00:00:00+00:00",
    }

    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / f"test_snapshot_legacy_aliases_{uuid4().hex}.json"

    try:
        snapshot_path.write_text(
            json.dumps({"schema_version": 1, "saved_at": "2026-03-17T00:00:00+00:00", "stores": [legacy_row]}),
            encoding="utf-8",
        )

        loaded_snapshot = load_snapshot(snapshot_path)

        assert len(loaded_snapshot) == 1
        assert list(loaded_snapshot[0].keys()) == STORE_SNAPSHOT_COLUMNS
        assert loaded_snapshot[0]["latitude"] == 55.03
        assert loaded_snapshot[0]["longitude"] == 82.92
        assert loaded_snapshot[0]["collected_at"] == "2026-03-17T00:00:00+00:00"
        assert loaded_snapshot[0]["stable_key"] == build_store_stable_key(legacy_row)
        assert set(loaded_snapshot[0]) == set(STORE_OUTPUT_COLUMNS) | {"stable_key"}
    finally:
        if snapshot_path.exists():
            snapshot_path.unlink()
