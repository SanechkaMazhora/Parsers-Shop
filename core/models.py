"""Shared data models and normalization helpers for parser output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Mapping

STORE_EXPORT_COLUMNS = [
    "network",
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
    "collected_at",
]


def normalize_optional_text(value: Any) -> str | None:
    """Trim text values and convert empty placeholders to None."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n,;")
    if not cleaned:
        return None
    if cleaned.lower() in {"none", "null", "nan", "n/a", "-"}:
        return None
    return cleaned


def normalize_text_token(value: Any) -> str:
    """Build a compare-friendly token from arbitrary text."""
    cleaned = normalize_optional_text(value)
    if not cleaned:
        return ""
    return re.sub(r"[^0-9a-zа-яё]+", "", cleaned.lower())


def normalize_coordinate(value: Any) -> float | None:
    """Convert coordinates to floats when possible."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_address(value: Any, *, city_hint: str | None = None) -> str | None:
    """Clean address noise and remove duplicated city prefixes when present."""
    cleaned = normalize_optional_text(value)
    if not cleaned:
        return None
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r",\s*,+", ", ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if city_hint and "," in cleaned:
        left, right = [part.strip() for part in cleaned.split(",", 1)]
        if normalize_text_token(left) == normalize_text_token(city_hint) and right:
            cleaned = right
    return cleaned or None


def normalize_source_url(value: Any) -> str:
    """Keep official source URLs stable for diff/snapshot persistence."""
    cleaned = normalize_optional_text(value)
    return cleaned or ""


def normalize_compare_source_url(value: Any) -> str:
    """Normalize source URLs for diff/stable-key comparison."""
    source_url = normalize_source_url(value)
    if not source_url:
        return ""
    monetka_match = re.search(
        r"https?://(?:www\.)?monetka\.ru/(?:[^/]+/)?shops_map/[^/]+/(\d+)/?$",
        source_url,
        flags=re.IGNORECASE,
    )
    if monetka_match:
        return f"monetka-store:{monetka_match.group(1)}"
    return source_url


def is_store_specific_source_url(value: Any) -> bool:
    """Detect whether the source URL already identifies a single store."""
    source_url = normalize_compare_source_url(value)
    if not source_url:
        return False
    if source_url.startswith("monetka-store:"):
        return True
    if "#" in source_url:
        return True
    if re.search(r"/\d+/?$", source_url):
        return True
    if "store=" in source_url.lower() or "shop=" in source_url.lower():
        return True
    return False


def build_store_stable_key(data: Mapping[str, Any]) -> str:
    """Build a stable identity key for diffing snapshots across runs."""
    latitude = data.get("latitude", data.get("lat"))
    longitude = data.get("longitude", data.get("lng"))
    city = normalize_optional_text(data.get("city"))

    parts = [f"network:{normalize_text_token(data.get('network'))}"]
    source_url = normalize_compare_source_url(data.get("source_url"))
    if source_url:
        parts.append(f"url:{source_url}")

    normalized_latitude = normalize_coordinate(latitude)
    normalized_longitude = normalize_coordinate(longitude)
    if normalized_latitude is not None and normalized_longitude is not None:
        parts.append(f"coords:{normalized_latitude:.6f},{normalized_longitude:.6f}")

    needs_location_fallback = not is_store_specific_source_url(source_url)
    if needs_location_fallback:
        for field_name in ("region", "city"):
            token = normalize_text_token(data.get(field_name))
            if token:
                parts.append(f"{field_name}:{token}")

        address = normalize_address(data.get("address"), city_hint=city)
        address_token = normalize_text_token(address)
        if address_token:
            parts.append(f"address:{address_token}")

    if len(parts) == 1:
        parts.append("fallback:unknown")

    digest = hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()
    return digest


@dataclass(slots=True)
class StoreRecord:
    """Unified store record for all retail networks."""

    network: str
    region: str | None
    city: str | None
    address: str | None
    work_time: str | None
    latitude: float | None
    longitude: float | None
    phone: str | None
    store_format: str | None
    status: str | None
    source_url: str
    collected_at: str

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
        latitude: float | None = None,
        longitude: float | None = None,
        lat: float | None = None,
        lng: float | None = None,
        phone: str | None = None,
        store_format: str | None = None,
        status: str | None = None,
        collected_at: str | None = None,
        parsed_at: str | None = None,
    ) -> "StoreRecord":
        """Create a normalized record with an automatic collection timestamp."""
        normalized_city = normalize_optional_text(city)
        normalized_source_url = normalize_source_url(source_url)
        return cls(
            network=normalize_optional_text(network) or "",
            region=normalize_optional_text(region),
            city=normalized_city,
            address=normalize_address(address, city_hint=normalized_city),
            work_time=normalize_optional_text(work_time),
            latitude=normalize_coordinate(latitude if latitude is not None else lat),
            longitude=normalize_coordinate(longitude if longitude is not None else lng),
            phone=normalize_optional_text(phone),
            store_format=normalize_optional_text(store_format),
            status=normalize_optional_text(status),
            source_url=normalized_source_url,
            collected_at=normalize_optional_text(collected_at or parsed_at)
            or datetime.now(timezone.utc).isoformat(),
        )

    @property
    def lat(self) -> float | None:
        """Backward-compatible alias for legacy code/tests."""
        return self.latitude

    @property
    def lng(self) -> float | None:
        """Backward-compatible alias for legacy code/tests."""
        return self.longitude

    @property
    def parsed_at(self) -> str:
        """Backward-compatible alias for legacy code/tests."""
        return self.collected_at

    def stable_key(self) -> str:
        """Return the stable snapshot/diff key for the record."""
        return build_store_stable_key(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dictionary for export/snapshots."""
        return {
            "network": self.network,
            "region": self.region,
            "city": self.city,
            "address": self.address,
            "work_time": self.work_time,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "phone": self.phone,
            "store_format": self.store_format,
            "status": self.status,
            "source_url": self.source_url,
            "collected_at": self.collected_at,
        }

    def to_snapshot_dict(self) -> dict[str, Any]:
        """Convert record to a snapshot row with a stable diff key."""
        data = self.to_dict()
        data["stable_key"] = self.stable_key()
        return data
