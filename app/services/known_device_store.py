from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class KnownDeviceRecord:
    device_id: str
    name: str
    host: str
    port: int
    location: str
    discovery_method: str
    type_name: str
    model_name: str
    serial_number: str
    mac: str
    last_seen: str | None = None


class KnownDeviceStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[KnownDeviceRecord]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        items = payload.get("devices", [])
        if not isinstance(items, list):
            return []

        records: list[KnownDeviceRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            device_id = str(item.get("device_id", "")).strip()
            location = str(item.get("location", "")).strip()
            host = str(item.get("host", "")).strip()
            if not device_id or not location or not host:
                continue
            try:
                port = int(item.get("port", 0))
            except (TypeError, ValueError):
                port = 0
            records.append(
                KnownDeviceRecord(
                    device_id=device_id,
                    name=str(item.get("name", "")).strip() or device_id,
                    host=host,
                    port=port,
                    location=location,
                    discovery_method=str(
                        item.get("discovery_method", "")
                    ).strip()
                    or "unknown",
                    type_name=str(item.get("type_name", "")).strip(),
                    model_name=str(item.get("model_name", "")).strip(),
                    serial_number=str(item.get("serial_number", "")).strip(),
                    mac=str(item.get("mac", "")).strip(),
                    last_seen=str(item.get("last_seen", "")).strip() or None,
                )
            )
        return records

    def save(self, records: list[KnownDeviceRecord]) -> None:
        unique_records = {
            record.device_id: record
            for record in records
            if record.device_id and record.location and record.host
        }
        payload = {
            "devices": [
                asdict(record)
                for record in sorted(
                    unique_records.values(),
                    key=lambda item: (
                        item.name.lower(),
                        item.host.lower(),
                        item.device_id.lower(),
                    ),
                )
            ]
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
