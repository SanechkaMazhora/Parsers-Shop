from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd

from core.excel_export import CHANGES_SHEET_NAME, DATA_SHEET_NAME, STATS_SHEET_NAME, export_stores_to_excel
from core.models import STORE_EXPORT_COLUMNS, StoreRecord


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


def test_excel_export_creates_file_and_required_sheets() -> None:
    output_path = _unique_output_path()
    snapshot_path = _snapshot_path_for(output_path)
    try:
        stores = [_make_store("n1", "c1", "a1")]
        export_stores_to_excel(stores, output_path=str(output_path))

        assert output_path.exists()
        assert snapshot_path.exists()
        with pd.ExcelFile(output_path) as workbook:
            assert DATA_SHEET_NAME in workbook.sheet_names
            assert CHANGES_SHEET_NAME in workbook.sheet_names
            assert STATS_SHEET_NAME in workbook.sheet_names
        data_df = pd.read_excel(output_path, sheet_name=DATA_SHEET_NAME)
        stats_df = pd.read_excel(output_path, sheet_name=STATS_SHEET_NAME)
        assert list(data_df.columns) == STORE_EXPORT_COLUMNS
        assert list(stats_df.columns) == ["network", "stores_count"]
        assert stats_df.to_dict(orient="records") == [{"network": "n1", "stores_count": 1}]
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
