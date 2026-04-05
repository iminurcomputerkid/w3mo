from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ScheduleStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        schedules = payload.get("schedules", [])
        if not isinstance(schedules, list):
            return []
        return [item for item in schedules if isinstance(item, dict)]

    def save(self, schedules: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schedules": schedules}
        self.path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
