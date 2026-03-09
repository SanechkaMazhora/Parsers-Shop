"""Excel export for parsed store data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.models import StoreRecord


def export_stores_to_excel(stores: list[StoreRecord], output_path: str = "output/stores.xlsx") -> None:
    """Export stores and summary statistics into an Excel workbook."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    data = [store.to_dict() for store in stores]
    data_df = pd.DataFrame(
        data,
        columns=[
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
        ],
    )

    if data_df.empty:
        stats_df = pd.DataFrame(
            [
                {"metric": "total_stores", "value": 0},
                {"metric": "stores_per_network", "value": None},
            ]
        )
    else:
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
        stats_df = pd.DataFrame(rows, columns=["metric", "value"])

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        data_df.to_excel(writer, sheet_name="Актуальные данные", index=False)
        stats_df.to_excel(writer, sheet_name="Статистика", index=False)
