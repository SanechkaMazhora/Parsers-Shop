from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pandas as pd
from openpyxl import load_workbook

from core.excel_export import CHANGES_SHEET_NAME, DATA_SHEET_NAME, STATS_SHEET_NAME, export_stores_to_excel
from core.models import STORE_OUTPUT_COLUMNS, STORE_SNAPSHOT_COLUMNS, StoreRecord


def _make_store(network: str, city: str, address: str, work_time: str | None = None) -> StoreRecord:
    return StoreRecord.build(
        network=network,
        city=city,
        address=address,
        work_time=work_time,
        source_url=f"https://example.com/{network}/{city}/{address}",
    )


def _unique_output_path() -> Path:
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"test_stores_{uuid4().hex}.xlsx"


def _snapshot_path_for(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_snapshot.json")


def _load_snapshot_store_keys(snapshot_path: Path) -> list[str]:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    first_store = payload["stores"][0]
    return list(first_store.keys())


def _load_snapshot_stores(snapshot_path: Path) -> list[dict[str, object]]:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return payload["stores"]


def test_excel_export_creates_file_and_required_sheets() -> None:
    output_path = _unique_output_path()
    snapshot_path = _snapshot_path_for(output_path)
    try:
        stores = [_make_store("n1", "c1", "a1")]
        diff_result = export_stores_to_excel(stores, output_path=str(output_path))

        assert output_path.exists()
        assert snapshot_path.exists()
        assert diff_result.is_initial_snapshot is True
        with pd.ExcelFile(output_path) as workbook:
            assert DATA_SHEET_NAME in workbook.sheet_names
            assert CHANGES_SHEET_NAME in workbook.sheet_names
            assert STATS_SHEET_NAME in workbook.sheet_names
        data_df = pd.read_excel(output_path, sheet_name=DATA_SHEET_NAME)
        stats_df = pd.read_excel(output_path, sheet_name=STATS_SHEET_NAME)
        changes_df = pd.read_excel(output_path, sheet_name=CHANGES_SHEET_NAME)
        assert list(data_df.columns) == STORE_OUTPUT_COLUMNS
        assert list(stats_df.columns) == ["network", "stores_count"]
        assert stats_df.to_dict(orient="records") == [{"network": "n1", "stores_count": 1}]
        assert changes_df.empty
        assert _load_snapshot_store_keys(snapshot_path) == STORE_SNAPSHOT_COLUMNS

        workbook = load_workbook(output_path)
        for sheet_name in (DATA_SHEET_NAME, CHANGES_SHEET_NAME, STATS_SHEET_NAME):
            worksheet = workbook[sheet_name]
            assert worksheet.freeze_panes == "A2"
            assert worksheet.auto_filter.ref is not None
            assert worksheet.column_dimensions["A"].width >= 12
    finally:
        if output_path.exists():
            output_path.unlink()
        if snapshot_path.exists():
            snapshot_path.unlink()


def test_excel_export_changes_are_detected_on_second_run() -> None:
    output_path = _unique_output_path()
    snapshot_path = _snapshot_path_for(output_path)
    try:
        first_run = [
            _make_store("n1", "c1", "a1", work_time="09:00-18:00"),
            _make_store("n1", "c1", "a2"),
        ]
        export_stores_to_excel(first_run, output_path=str(output_path))

        second_run = [
            _make_store("n1", "c1", "a1", work_time="10:00-20:00"),  # updated
            _make_store("n1", "c1", "a3"),  # added
        ]
        export_stores_to_excel(second_run, output_path=str(output_path))

        changes_df = pd.read_excel(output_path, sheet_name=CHANGES_SHEET_NAME)
        assert (changes_df["change_type"] == "added").any()
        assert (changes_df["change_type"] == "removed").any()
        changed_row = changes_df.loc[changes_df["change_type"] == "changed"].iloc[0]
        assert "work_time" in changed_row["changed_fields"]
    finally:
        if output_path.exists():
            output_path.unlink()
        if snapshot_path.exists():
            snapshot_path.unlink()


def test_excel_export_second_identical_run_has_empty_changes_sheet() -> None:
    output_path = _unique_output_path()
    snapshot_path = _snapshot_path_for(output_path)
    try:
        stores = [
            _make_store("n1", "c1", "a1", work_time="09:00-18:00"),
            _make_store("n1", "c1", "a2"),
        ]

        first_diff = export_stores_to_excel(stores, output_path=str(output_path))
        second_diff = export_stores_to_excel(stores, output_path=str(output_path))

        assert first_diff.is_initial_snapshot is True
        assert second_diff.is_initial_snapshot is False
        assert not second_diff.added
        assert not second_diff.removed
        assert not second_diff.changed

        changes_df = pd.read_excel(output_path, sheet_name=CHANGES_SHEET_NAME)
        assert changes_df.empty
    finally:
        if output_path.exists():
            output_path.unlink()
        if snapshot_path.exists():
            snapshot_path.unlink()


def test_excel_export_snapshot_and_data_sheet_share_canonical_schema() -> None:
    output_path = _unique_output_path()
    snapshot_path = _snapshot_path_for(output_path)
    try:
        stores = [
            _make_store("n1", "c1", "a1", work_time="09:00-18:00"),
            _make_store("n2", "c2", "a2", work_time="10:00-20:00"),
        ]

        export_stores_to_excel(stores, output_path=str(output_path))

        data_df = pd.read_excel(output_path, sheet_name=DATA_SHEET_NAME)
        assert list(data_df.columns) == STORE_OUTPUT_COLUMNS
        assert _load_snapshot_store_keys(snapshot_path) == STORE_SNAPSHOT_COLUMNS
        assert set(_load_snapshot_store_keys(snapshot_path)) == set(STORE_OUTPUT_COLUMNS) | {"stable_key"}
    finally:
        if output_path.exists():
            output_path.unlink()
        if snapshot_path.exists():
            snapshot_path.unlink()


def test_excel_export_changes_sheet_payloads_use_canonical_schema() -> None:
    output_path = _unique_output_path()
    snapshot_path = _snapshot_path_for(output_path)
    try:
        first_run = [
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
        second_run = [
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

        export_stores_to_excel(first_run, output_path=str(output_path))
        export_stores_to_excel(second_run, output_path=str(output_path))

        changes_df = pd.read_excel(output_path, sheet_name=CHANGES_SHEET_NAME)
        added_row = changes_df.loc[changes_df["change_type"] == "added"].iloc[0]
        removed_row = changes_df.loc[changes_df["change_type"] == "removed"].iloc[0]
        added_payload = json.loads(added_row["new_value"])
        removed_payload = json.loads(removed_row["old_value"])

        assert set(added_payload.keys()) == set(STORE_OUTPUT_COLUMNS)
        assert set(removed_payload.keys()) == set(STORE_OUTPUT_COLUMNS)
        assert "lat" not in added_payload and "lng" not in added_payload and "parsed_at" not in added_payload
        assert "lat" not in removed_payload and "lng" not in removed_payload and "parsed_at" not in removed_payload
    finally:
        if output_path.exists():
            output_path.unlink()
        if snapshot_path.exists():
            snapshot_path.unlink()


def test_excel_export_deduplicates_duplicate_stable_key_in_data_sheet_and_snapshot() -> None:
    output_path = _unique_output_path()
    snapshot_path = _snapshot_path_for(output_path)
    try:
        stores = [
            _make_store("n1", "c1", "a1", work_time=None),
            _make_store("n1", "c1", "a1", work_time="09:00-18:00"),
        ]

        export_stores_to_excel(stores, output_path=str(output_path))

        data_df = pd.read_excel(output_path, sheet_name=DATA_SHEET_NAME)
        stats_df = pd.read_excel(output_path, sheet_name=STATS_SHEET_NAME)
        snapshot_stores = _load_snapshot_stores(snapshot_path)

        assert len(data_df) == 1
        assert data_df.iloc[0]["work_time"] == "09:00-18:00"
        assert stats_df.to_dict(orient="records") == [{"network": "n1", "stores_count": 1}]
        assert len(snapshot_stores) == 1
        assert snapshot_stores[0]["work_time"] == "09:00-18:00"
    finally:
        if output_path.exists():
            output_path.unlink()
        if snapshot_path.exists():
            snapshot_path.unlink()


def test_excel_export_duplicate_stable_key_baseline_does_not_create_diff_noise() -> None:
    output_path = _unique_output_path()
    snapshot_path = _snapshot_path_for(output_path)
    try:
        first_run = [
            _make_store("n1", "c1", "a1", work_time=None),
            _make_store("n1", "c1", "a1", work_time="09:00-18:00"),
        ]
        second_run = [_make_store("n1", "c1", "a1", work_time="09:00-18:00")]

        first_diff = export_stores_to_excel(first_run, output_path=str(output_path))
        second_diff = export_stores_to_excel(second_run, output_path=str(output_path))

        assert first_diff.is_initial_snapshot is True
        assert second_diff.is_initial_snapshot is False
        assert not second_diff.added
        assert not second_diff.removed
        assert not second_diff.changed

        changes_df = pd.read_excel(output_path, sheet_name=CHANGES_SHEET_NAME)
        data_df = pd.read_excel(output_path, sheet_name=DATA_SHEET_NAME)
        snapshot_stores = _load_snapshot_stores(snapshot_path)

        assert changes_df.empty
        assert len(data_df) == 1
        assert len(snapshot_stores) == 1
    finally:
        if output_path.exists():
            output_path.unlink()
        if snapshot_path.exists():
            snapshot_path.unlink()
