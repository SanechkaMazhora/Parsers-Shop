"""Excel export for parsed store data."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from core.models import StoreRecord

DATA_COLUMNS = [
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
]
CHANGE_TRACKED_COLUMNS = ["work_time", "phone", "store_format", "status"]
CHANGE_KEY_COLUMNS = ["network", "city", "address"]

DATA_SHEET_NAME = "Актуальные данные"
CHANGES_SHEET_NAME = "Изменения"
STATS_SHEET_NAME = "Статистика"


def _build_data_df(stores: list[StoreRecord]) -> pd.DataFrame:
    data = [store.to_dict() for store in stores]
    return pd.DataFrame(data, columns=DATA_COLUMNS)


def _load_previous_data(output_file: Path) -> pd.DataFrame:
    if not output_file.exists():
        return pd.DataFrame(columns=DATA_COLUMNS)
    try:
        previous_df = pd.read_excel(output_file, sheet_name=DATA_SHEET_NAME)
    except Exception:
        return pd.DataFrame(columns=DATA_COLUMNS)
    for col in DATA_COLUMNS:
        if col not in previous_df.columns:
            previous_df[col] = None
    return previous_df[DATA_COLUMNS]


def _normalize_key_value(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _record_key(row: pd.Series) -> str:
    parts = [_normalize_key_value(row[col]) for col in CHANGE_KEY_COLUMNS]
    return "||".join(parts)


def _to_str_or_none(value: Any) -> str | None:
    if pd.isna(value):
        return None
    string = str(value).strip()
    return string if string else None


def _build_changes_df(current_df: pd.DataFrame, previous_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["network", "city", "address", "change_type", "old_value", "new_value", "detected_at"]
    if previous_df.empty:
        return pd.DataFrame(columns=columns)

    current = current_df.copy()
    previous = previous_df.copy()
    current["__key"] = current.apply(_record_key, axis=1)
    previous["__key"] = previous.apply(_record_key, axis=1)

    # Deduplicate by key and keep first entry if duplicates happen.
    current_map = current.drop_duplicates("__key", keep="first").set_index("__key")
    previous_map = previous.drop_duplicates("__key", keep="first").set_index("__key")

    current_keys = set(current_map.index)
    previous_keys = set(previous_map.index)

    detected_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, str | None]] = []

    for key in sorted(current_keys - previous_keys):
        row = current_map.loc[key]
        rows.append(
            {
                "network": _to_str_or_none(row["network"]),
                "city": _to_str_or_none(row["city"]),
                "address": _to_str_or_none(row["address"]),
                "change_type": "added",
                "old_value": None,
                "new_value": None,
                "detected_at": detected_at,
            }
        )

    for key in sorted(previous_keys - current_keys):
        row = previous_map.loc[key]
        rows.append(
            {
                "network": _to_str_or_none(row["network"]),
                "city": _to_str_or_none(row["city"]),
                "address": _to_str_or_none(row["address"]),
                "change_type": "removed",
                "old_value": None,
                "new_value": None,
                "detected_at": detected_at,
            }
        )

    for key in sorted(current_keys & previous_keys):
        current_row = current_map.loc[key]
        previous_row = previous_map.loc[key]
        for field in CHANGE_TRACKED_COLUMNS:
            old_value = _to_str_or_none(previous_row[field])
            new_value = _to_str_or_none(current_row[field])
            if old_value != new_value:
                rows.append(
                    {
                        "network": _to_str_or_none(current_row["network"]),
                        "city": _to_str_or_none(current_row["city"]),
                        "address": _to_str_or_none(current_row["address"]),
                        "change_type": f"updated:{field}",
                        "old_value": old_value,
                        "new_value": new_value,
                        "detected_at": detected_at,
                    }
                )

    return pd.DataFrame(rows, columns=columns)


def _build_stats_df(data_df: pd.DataFrame) -> pd.DataFrame:
    if data_df.empty:
        return pd.DataFrame(
            [
                {"metric": "total_stores", "value": 0},
                {"metric": "stores_per_network", "value": None},
            ]
        )

    by_network = (
        data_df.groupby("network", dropna=False)
        .size()
        .reset_index(name="stores_count")
        .sort_values("stores_count", ascending=False)
    )
    rows: list[dict[str, object]] = [{"metric": "total_stores", "value": int(len(data_df))}]
    for row in by_network.itertuples(index=False):
        network_name = row.network if row.network else "unknown_network"
        rows.append({"metric": f"network:{network_name}", "value": int(row.stores_count)})
    return pd.DataFrame(rows, columns=["metric", "value"])


def export_stores_to_excel(stores: list[StoreRecord], output_path: str = "output/stores.xlsx") -> None:
    """Export stores, changes and summary statistics into an Excel workbook."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    data_df = _build_data_df(stores)
    previous_df = _load_previous_data(output_file)
    changes_df = _build_changes_df(data_df, previous_df)
    stats_df = _build_stats_df(data_df)

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        data_df.to_excel(writer, sheet_name=DATA_SHEET_NAME, index=False)
        changes_df.to_excel(writer, sheet_name=CHANGES_SHEET_NAME, index=False)
        stats_df.to_excel(writer, sheet_name=STATS_SHEET_NAME, index=False)
