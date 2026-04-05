from __future__ import annotations

import json
from pathlib import Path


class ManualDeviceStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        addresses = payload.get("addresses", [])
        if not isinstance(addresses, list):
            return []
        return [str(item).strip() for item in addresses if str(item).strip()]

    def save(self, addresses: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"addresses": sorted(set(addresses), key=str.lower)}
        self.path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
