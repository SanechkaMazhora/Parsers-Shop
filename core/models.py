"""Shared data models for parser output."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class StoreRecord:
    """Unified store record for all retail networks."""

    network: str
    region: str | None
    city: str | None
    address: str | None
    work_time: str | None
    lat: float | None
    lng: float | None
    phone: str | None
    store_format: str | None
    status: str | None
    source_url: str
    parsed_at: str

    @classmethod
    def build(
        cls,
        *,
        network: str,
        source_url: str,
        region: str | None = None,
        city: str | None = None,
        address: str | None = None,
        work_time: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        phone: str | None = None,
        store_format: str | None = None,
        status: str | None = None,
    ) -> "StoreRecord":
        """Create a record with automatic parse timestamp."""
        return cls(
            network=network,
            region=region,
            city=city,
            address=address,
            work_time=work_time,
            lat=lat,
            lng=lng,
            phone=phone,
            store_format=store_format,
            status=status,
            source_url=source_url,
            parsed_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dictionary for export."""
        return asdict(self)

