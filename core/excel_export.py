"""Excel export for parsed store data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.diff import CHANGE_SHEET_COLUMNS, DiffResult, build_snapshot_rows, compute_diff, load_snapshot, save_snapshot
from core.models import STORE_EXPORT_COLUMNS, StoreRecord

DATA_COLUMNS = STORE_EXPORT_COLUMNS
STATS_COLUMNS = ["network", "stores_count"]

DATA_SHEET_NAME = "Актуальные данные"
CHANGES_SHEET_NAME = "Изменения"
STATS_SHEET_NAME = "Статистика"


def _build_data_df(stores: list[StoreRecord]) -> pd.DataFrame:
    rows = [store.to_dict() for store in stores]
    data_df = pd.DataFrame(rows, columns=DATA_COLUMNS)
    if data_df.empty:
        return pd.DataFrame(columns=DATA_COLUMNS)
    return data_df.sort_values(
        by=["network", "region", "city", "address", "source_url"],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)


def _build_changes_df(diff_result: DiffResult) -> pd.DataFrame:
    rows = diff_result.to_rows()
    if not rows:
        return pd.DataFrame(columns=CHANGE_SHEET_COLUMNS)
    return pd.DataFrame(rows, columns=CHANGE_SHEET_COLUMNS)


def _build_stats_df(data_df: pd.DataFrame) -> pd.DataFrame:
    if data_df.empty:
        return pd.DataFrame(columns=STATS_COLUMNS)
    return (
        data_df.groupby("network", dropna=False)
        .size()
        .reset_index(name="stores_count")
        .sort_values(by=["stores_count", "network"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )


def export_stores_to_excel(
    stores: list[StoreRecord],
    output_path: str = "output/stores.xlsx",
    snapshot_path: str | None = None,
) -> DiffResult:
    """Export stores, changes and statistics into an Excel workbook."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if snapshot_path is None:
        snapshot_file = output_file.with_name(f"{output_file.stem}_snapshot.json")
    else:
        snapshot_file = Path(snapshot_path)

    current_snapshot = build_snapshot_rows(stores)
    previous_snapshot = load_snapshot(snapshot_file)
    diff_result = compute_diff(previous_snapshot=previous_snapshot, current_snapshot=current_snapshot)

    data_df = _build_data_df(stores)
    changes_df = _build_changes_df(diff_result)
    stats_df = _build_stats_df(data_df)

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        data_df.to_excel(writer, sheet_name=DATA_SHEET_NAME, index=False)
        changes_df.to_excel(writer, sheet_name=CHANGES_SHEET_NAME, index=False)
        stats_df.to_excel(writer, sheet_name=STATS_SHEET_NAME, index=False)

    save_snapshot(stores, snapshot_file)
    return diff_result
