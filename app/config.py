from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    return int(value)


def _get_manual_addresses() -> list[str]:
    raw = os.getenv("WEMO_MANUAL_ADDRESSES", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(slots=True)
class Settings:
    app_title: str = os.getenv("WEMO_APP_TITLE", "WeMo Local Dashboard")
    host: str = os.getenv("WEMO_HOST", "0.0.0.0")
    port: int = int(os.getenv("WEMO_PORT", "8000"))
    log_level: str = os.getenv("WEMO_LOG_LEVEL", "INFO").upper()
    startup_discovery: bool = _get_bool("WEMO_STARTUP_DISCOVERY", True)
    device_poll_seconds: int = int(os.getenv("WEMO_DEVICE_POLL_SECONDS", "20"))
    discovery_timeout: float = float(os.getenv("WEMO_DISCOVERY_TIMEOUT", "5"))
    discovery_max_entries: int | None = _get_optional_int(
        "WEMO_DISCOVERY_MAX_ENTRIES"
    )
    base_dir: Path = Path(__file__).resolve().parent.parent
    data_dir: Path = None  # type: ignore[assignment]
    manual_addresses_file: Path = None  # type: ignore[assignment]
    known_devices_file: Path = None  # type: ignore[assignment]
    schedules_file: Path = None  # type: ignore[assignment]
    manual_addresses: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.data_dir is None:
            self.data_dir = self.base_dir / "data"
        if self.manual_addresses_file is None:
            self.manual_addresses_file = self.data_dir / "manual_addresses.json"
        if self.known_devices_file is None:
            self.known_devices_file = self.data_dir / "known_devices.json"
        if self.schedules_file is None:
            self.schedules_file = self.data_dir / "schedules.json"
        if self.manual_addresses is None:
            self.manual_addresses = _get_manual_addresses()
