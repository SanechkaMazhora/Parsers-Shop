"""Snapshot persistence and diff engine for store records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.models import STORE_EXPORT_COLUMNS, StoreRecord, build_store_stable_key, normalize_compare_source_url

SNAPSHOT_SCHEMA_VERSION = 1
CHANGE_SHEET_COLUMNS = [
    "network",
    "region",
    "city",
    "address",
    "source_url",
    "change_type",
    "changed_fields",
    "old_value",
    "new_value",
    "detected_at",
    "stable_key",
]
TRACKED_CHANGE_FIELDS = [
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
]


def _normalize_snapshot_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    row = {column: raw.get(column) for column in STORE_EXPORT_COLUMNS}
    row["stable_key"] = build_store_stable_key(row)
    return row


def _serialize_payload(data: Mapping[str, Any] | None) -> str | None:
    if not data:
        return None
    filtered = {key: value for key, value in data.items() if value is not None}
    if not filtered:
        return None
    return json.dumps(filtered, ensure_ascii=False, sort_keys=True)


def build_snapshot_rows(stores: Iterable[StoreRecord]) -> list[dict[str, Any]]:
    """Convert records to deterministic snapshot rows."""
    rows = [store.to_snapshot_dict() for store in stores]
    rows.sort(
        key=lambda row: (
            str(row.get("network") or ""),
            str(row.get("city") or ""),
            str(row.get("address") or ""),
            str(row.get("source_url") or ""),
            str(row.get("stable_key") or ""),
        )
    )
    return rows


def load_snapshot(snapshot_path: str | Path) -> list[dict[str, Any]]:
    """Load a previously saved snapshot; return empty data on missing/corrupt files."""
    return load_snapshot_with_meta(snapshot_path).rows


@dataclass(slots=True)
class SnapshotLoadResult:
    """Snapshot rows plus load status for explainable diff handling."""

    rows: list[dict[str, Any]]
    status: str


def load_snapshot_with_meta(snapshot_path: str | Path) -> SnapshotLoadResult:
    """Load a previously saved snapshot and describe whether it was available."""
    snapshot_file = Path(snapshot_path)
    if not snapshot_file.exists():
        return SnapshotLoadResult(rows=[], status="missing")

    try:
        payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SnapshotLoadResult(rows=[], status="invalid")

    stores = payload.get("stores")
    if not isinstance(stores, list):
        return SnapshotLoadResult(rows=[], status="invalid")
    return SnapshotLoadResult(
        rows=[_normalize_snapshot_row(item) for item in stores if isinstance(item, dict)],
        status="loaded",
    )


def save_snapshot(stores: Iterable[StoreRecord], snapshot_path: str | Path) -> Path:
    """Persist the latest store snapshot next to the generated report."""
    snapshot_file = Path(snapshot_path)
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "stores": build_snapshot_rows(stores),
    }
    snapshot_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot_file


@dataclass(slots=True)
class DiffEntry:
    """Single store-level diff result."""

    stable_key: str
    change_type: str
    network: str | None
    region: str | None
    city: str | None
    address: str | None
    source_url: str | None
    changed_fields: list[str]
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None

    def to_row(self, *, detected_at: str) -> dict[str, Any]:
        """Serialize diff entry for Excel export."""
        return {
            "network": self.network,
            "region": self.region,
            "city": self.city,
            "address": self.address,
            "source_url": self.source_url,
            "change_type": self.change_type,
            "changed_fields": ",".join(self.changed_fields) if self.changed_fields else None,
            "old_value": _serialize_payload(self.old_value),
            "new_value": _serialize_payload(self.new_value),
            "detected_at": detected_at,
            "stable_key": self.stable_key,
        }


@dataclass(slots=True)
class DiffResult:
    """Grouped diff entries for convenient logging/export."""

    added: list[DiffEntry]
    removed: list[DiffEntry]
    changed: list[DiffEntry]
    is_initial_snapshot: bool = False
    snapshot_status: str = "loaded"

    def to_rows(self) -> list[dict[str, Any]]:
        """Flatten diff entries into Excel-ready rows."""
        if self.is_initial_snapshot:
            return []
        detected_at = datetime.now(timezone.utc).isoformat()
        rows = [entry.to_row(detected_at=detected_at) for entry in self.added + self.removed + self.changed]
        rows.sort(
            key=lambda row: (
                str(row.get("change_type") or ""),
                str(row.get("network") or ""),
                str(row.get("city") or ""),
                str(row.get("address") or ""),
            )
        )
        return rows


def compute_diff(
    previous_snapshot: Iterable[Mapping[str, Any]],
    current_snapshot: Iterable[Mapping[str, Any]],
    *,
    treat_as_initial: bool = False,
    snapshot_status: str = "loaded",
) -> DiffResult:
    """Compare two snapshots and return added/removed/changed stores."""
    previous_map = {
        row["stable_key"]: row
        for row in (_normalize_snapshot_row(item) for item in previous_snapshot)
    }
    current_map = {
        row["stable_key"]: row
        for row in (_normalize_snapshot_row(item) for item in current_snapshot)
    }

    if treat_as_initial:
        return DiffResult(
            added=[],
            removed=[],
            changed=[],
            is_initial_snapshot=True,
            snapshot_status=snapshot_status,
        )

    added: list[DiffEntry] = []
    removed: list[DiffEntry] = []
    changed: list[DiffEntry] = []

    for stable_key in sorted(current_map.keys() - previous_map.keys()):
        current_row = current_map[stable_key]
        added.append(
            DiffEntry(
                stable_key=stable_key,
                change_type="added",
                network=current_row.get("network"),
                region=current_row.get("region"),
                city=current_row.get("city"),
                address=current_row.get("address"),
                source_url=current_row.get("source_url"),
                changed_fields=[],
                old_value=None,
                new_value={column: current_row.get(column) for column in STORE_EXPORT_COLUMNS},
            )
        )

    for stable_key in sorted(previous_map.keys() - current_map.keys()):
        previous_row = previous_map[stable_key]
        removed.append(
            DiffEntry(
                stable_key=stable_key,
                change_type="removed",
                network=previous_row.get("network"),
                region=previous_row.get("region"),
                city=previous_row.get("city"),
                address=previous_row.get("address"),
                source_url=previous_row.get("source_url"),
                changed_fields=[],
                old_value={column: previous_row.get(column) for column in STORE_EXPORT_COLUMNS},
                new_value=None,
            )
        )

    for stable_key in sorted(previous_map.keys() & current_map.keys()):
        previous_row = previous_map[stable_key]
        current_row = current_map[stable_key]
        changed_fields: list[str] = []
        old_value: dict[str, Any] = {}
        new_value: dict[str, Any] = {}

        for field_name in TRACKED_CHANGE_FIELDS:
            previous_value = previous_row.get(field_name)
            current_value = current_row.get(field_name)
            if field_name == "source_url":
                previous_value = normalize_compare_source_url(previous_value)
                current_value = normalize_compare_source_url(current_value)
            if previous_value == current_value:
                continue
            changed_fields.append(field_name)
            old_value[field_name] = previous_row.get(field_name)
            new_value[field_name] = current_row.get(field_name)

        if not changed_fields:
            continue

        changed.append(
            DiffEntry(
                stable_key=stable_key,
                change_type="changed",
                network=current_row.get("network"),
                region=current_row.get("region"),
                city=current_row.get("city"),
                address=current_row.get("address"),
                source_url=current_row.get("source_url"),
                changed_fields=changed_fields,
                old_value=old_value,
                new_value=new_value,
            )
        )
    return DiffResult(
        added=added,
        removed=removed,
        changed=changed,
        snapshot_status=snapshot_status,
    )
