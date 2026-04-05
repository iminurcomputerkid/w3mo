from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from typing import Literal

from app.schemas import (
    ScheduleCreateRequest,
    ScheduleUpdateRequest,
    ScheduleResponse,
    UpcomingScheduleEvent,
)
from app.services.schedule_store import ScheduleStore
from app.services.wemo_service import DeviceOperationError, WemoService

LOG = logging.getLogger(__name__)

ActionType = Literal["on", "off", "brightness"]
ScheduleType = Literal["countdown", "daily"]
WEEKDAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_INDEX = {day: index for index, day in enumerate(WEEKDAY_ORDER)}


@dataclass(slots=True)
class ScheduleRecord:
    id: str
    name: str
    device_id: str
    schedule_type: ScheduleType
    action: ActionType
    brightness: int | None
    time_of_day: str | None
    duration_minutes: int | None
    weekdays: list[str]
    enabled: bool
    created_at: str
    last_run_at: str | None = None
    next_run_at: str | None = None
    pending_off_at: str | None = None
    last_error: str | None = None


class ScheduleService:
    def __init__(self, store: ScheduleStore, wemo_service: WemoService) -> None:
        self._store = store
        self._wemo_service = wemo_service
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._schedules = [self._from_stored_record(item) for item in self._store.load()]
        self._recalculate_startup_state()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="wemo-schedule-loop",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def list_schedules(self) -> list[ScheduleResponse]:
        with self._lock:
            return [self._serialize(item) for item in self._sorted()]

    def list_upcoming_events(self, hours: int = 24) -> list[UpcomingScheduleEvent]:
        with self._lock:
            return self._upcoming_events(hours=hours)

    def create_schedule(self, payload: ScheduleCreateRequest) -> ScheduleResponse:
        with self._lock:
            self._validate_payload(payload)
            record = ScheduleRecord(
                id=str(uuid.uuid4()),
                name=payload.name.strip() or self._default_name(payload),
                device_id=payload.device_id,
                schedule_type=payload.schedule_type,
                action=payload.action,
                brightness=payload.brightness,
                time_of_day=payload.time_of_day,
                duration_minutes=payload.duration_minutes,
                weekdays=self._normalize_weekdays(payload.weekdays),
                enabled=True,
                created_at=self._now().isoformat(),
            )
            if record.schedule_type == "countdown":
                record.last_run_at = self._now().isoformat()
                if record.action != "off":
                    self._execute_primary_action(record)
                record.pending_off_at = (
                    self._now()
                    + timedelta(minutes=record.duration_minutes or 0)
                ).isoformat()
                record.next_run_at = None
            else:
                record.next_run_at = self._next_daily_run(record).isoformat()
            self._schedules.append(record)
            self._persist()
            return self._serialize(record)

    def delete_schedule(self, schedule_id: str) -> None:
        with self._lock:
            self._schedules = [
                item for item in self._schedules if item.id != schedule_id
            ]
            self._persist()

    def toggle_schedule(self, schedule_id: str, enabled: bool) -> ScheduleResponse:
        with self._lock:
            record = self._get(schedule_id)
            record.enabled = enabled
            record.last_error = None
            if enabled and record.schedule_type == "daily":
                record.next_run_at = self._next_daily_run(record).isoformat()
            elif not enabled:
                record.pending_off_at = None
                record.next_run_at = None
            self._persist()
            return self._serialize(record)

    def update_schedule(
        self, schedule_id: str, payload: ScheduleUpdateRequest
    ) -> ScheduleResponse:
        with self._lock:
            record = self._get(schedule_id)
            if record.schedule_type != "daily":
                raise DeviceOperationError(
                    "Only daily schedules can be edited from the schedule form."
                )
            create_like = ScheduleCreateRequest(
                name=payload.name,
                device_id=payload.device_id,
                schedule_type="daily",
                action=payload.action,
                brightness=payload.brightness,
                time_of_day=payload.time_of_day,
                duration_minutes=payload.duration_minutes,
                weekdays=payload.weekdays,
            )
            self._validate_payload(create_like)
            record.name = payload.name.strip() or self._default_name(create_like)
            record.device_id = payload.device_id
            record.action = payload.action
            record.brightness = payload.brightness
            record.time_of_day = payload.time_of_day
            record.duration_minutes = payload.duration_minutes
            record.weekdays = self._normalize_weekdays(payload.weekdays)
            record.last_error = None
            record.next_run_at = (
                self._next_daily_run(record).isoformat() if record.enabled else None
            )
            self._persist()
            return self._serialize(record)

    def adjust_countdown_timer(
        self, schedule_id: str, delta_minutes: int
    ) -> ScheduleResponse:
        with self._lock:
            record = self._get(schedule_id)
            if record.schedule_type != "countdown":
                raise DeviceOperationError(
                    "Timer adjustment is only available for countdown schedules."
                )
            if not record.enabled or not record.pending_off_at:
                raise DeviceOperationError("This timer is no longer active.")
            if delta_minutes == 0:
                return self._serialize(record)

            pending_off = self._parse_dt(record.pending_off_at)
            new_pending_off = pending_off + timedelta(minutes=delta_minutes)
            now = self._now()
            if new_pending_off <= now:
                self._wemo_service.turn_off(record.device_id)
                record.pending_off_at = None
                record.enabled = False
                record.next_run_at = None
                record.last_error = None
                self._persist()
                return self._serialize(record)

            elapsed_minutes = max(
                1,
                int(
                    round(
                        (
                            new_pending_off
                            - self._parse_dt(record.last_run_at or now.isoformat())
                        ).total_seconds()
                        / 60
                    )
                ),
            )
            record.duration_minutes = elapsed_minutes
            record.pending_off_at = new_pending_off.isoformat()
            record.last_error = None
            self._persist()
            return self._serialize(record)

    def _recalculate_startup_state(self) -> None:
        now = self._now()
        changed = False
        for record in self._schedules:
            if record.schedule_type == "daily" and record.enabled:
                if not record.next_run_at:
                    record.next_run_at = self._next_daily_run(record).isoformat()
                    changed = True
            if record.schedule_type == "countdown" and record.enabled:
                if not record.pending_off_at:
                    record.enabled = False
                    changed = True
                elif self._parse_dt(record.pending_off_at) <= now:
                    try:
                        self._wemo_service.turn_off(record.device_id)
                    except DeviceOperationError as exc:
                        record.last_error = str(exc)
                    record.enabled = False
                    record.next_run_at = None
                    changed = True
        if changed:
            self._persist()

    def _run_loop(self) -> None:
        while not self._stop_event.wait(5):
            try:
                self._process_due_schedules()
            except Exception:
                LOG.exception("Scheduler loop failed")

    def _process_due_schedules(self) -> None:
        now = self._now()
        with self._lock:
            changed = False
            for record in self._schedules:
                if not record.enabled:
                    continue

                if record.pending_off_at and self._parse_dt(record.pending_off_at) <= now:
                    try:
                        self._wemo_service.turn_off(record.device_id)
                        record.last_error = None
                    except DeviceOperationError as exc:
                        record.last_error = str(exc)
                    record.pending_off_at = None
                    if record.schedule_type == "countdown":
                        record.enabled = False
                        record.next_run_at = None
                    changed = True

                if (
                    record.schedule_type == "daily"
                    and record.next_run_at
                    and self._parse_dt(record.next_run_at) <= now
                ):
                    try:
                        self._execute_primary_action(record)
                        record.last_error = None
                    except DeviceOperationError as exc:
                        record.last_error = str(exc)
                    record.last_run_at = now.isoformat()
                    if record.duration_minutes and record.action in {"on", "brightness"}:
                        record.pending_off_at = (
                            now + timedelta(minutes=record.duration_minutes)
                        ).isoformat()
                    else:
                        record.pending_off_at = None
                    record.next_run_at = self._next_daily_run(record, now).isoformat()
                    changed = True
            if changed:
                self._persist()

    def _execute_primary_action(self, record: ScheduleRecord) -> None:
        if record.action == "on":
            self._wemo_service.turn_on(record.device_id)
            return
        if record.action == "off":
            self._wemo_service.turn_off(record.device_id)
            return
        if record.brightness is None:
            raise DeviceOperationError("Brightness schedules require a brightness value.")
        self._wemo_service.set_brightness(record.device_id, record.brightness)

    def _next_daily_run(
        self, record: ScheduleRecord, base: datetime | None = None
    ) -> datetime:
        base = base or self._now()
        assert record.time_of_day
        hour_str, minute_str = record.time_of_day.split(":")
        target = datetime.combine(
            base.date(),
            time(hour=int(hour_str), minute=int(minute_str)),
            tzinfo=base.tzinfo,
        )
        if target <= base:
            target += timedelta(days=1)
        valid_weekdays = set(record.weekdays or WEEKDAY_ORDER)
        while WEEKDAY_ORDER[target.weekday()] not in valid_weekdays:
            target += timedelta(days=1)
        return target

    def _validate_payload(self, payload: ScheduleCreateRequest) -> None:
        if payload.schedule_type == "countdown":
            if not payload.duration_minutes or payload.duration_minutes <= 0:
                raise DeviceOperationError(
                    "Countdown schedules require a positive duration."
                )
        if payload.schedule_type == "daily" and not payload.time_of_day:
            raise DeviceOperationError("Daily schedules require a time of day.")
        if payload.schedule_type == "daily" and not self._normalize_weekdays(
            payload.weekdays
        ):
            raise DeviceOperationError(
                "Daily schedules require at least one weekday."
            )
        if payload.action == "brightness" and payload.brightness is None:
            raise DeviceOperationError(
                "Brightness schedules require a brightness value."
            )
        if (
            payload.action == "brightness"
            and not self._wemo_service.device_supports_brightness(payload.device_id)
        ):
            raise DeviceOperationError(
                "The selected device does not support brightness schedules."
            )

    def _default_name(self, payload: ScheduleCreateRequest) -> str:
        if payload.schedule_type == "countdown":
            return "Timer"
        return "Daily Schedule"

    def _get(self, schedule_id: str) -> ScheduleRecord:
        for record in self._schedules:
            if record.id == schedule_id:
                return record
        raise DeviceOperationError(f"Unknown schedule id: {schedule_id}")

    @staticmethod
    def _normalize_weekdays(weekdays: list[str]) -> list[str]:
        unique = []
        for day in weekdays:
            if day in WEEKDAY_INDEX and day not in unique:
                unique.append(day)
        return sorted(unique, key=lambda day: WEEKDAY_INDEX[day])

    def _from_stored_record(self, item: dict) -> ScheduleRecord:
        data = dict(item)
        weekdays = data.get("weekdays")
        if not isinstance(weekdays, list):
            weekdays = WEEKDAY_ORDER.copy() if data.get("schedule_type") == "daily" else []
        data["weekdays"] = self._normalize_weekdays([str(day) for day in weekdays])
        return ScheduleRecord(**data)

    def _persist(self) -> None:
        self._store.save([asdict(item) for item in self._schedules])

    def _sorted(self) -> list[ScheduleRecord]:
        return sorted(
            self._schedules,
            key=lambda item: (
                item.schedule_type,
                item.next_run_at or "",
                item.name.lower(),
            ),
        )

    def _serialize(self, record: ScheduleRecord) -> ScheduleResponse:
        data = asdict(record)
        data["device_name"] = self._wemo_service.get_device_name(record.device_id)
        return ScheduleResponse(**data)

    def _upcoming_events(self, hours: int) -> list[UpcomingScheduleEvent]:
        now = self._now()
        cutoff = now + timedelta(hours=hours)
        events: list[UpcomingScheduleEvent] = []
        for record in self._schedules:
            if not record.enabled:
                continue
            if record.pending_off_at:
                off_time = self._parse_dt(record.pending_off_at)
                if now <= off_time <= cutoff:
                    events.append(
                        UpcomingScheduleEvent(
                            schedule_id=record.id,
                            schedule_name=record.name,
                            device_id=record.device_id,
                            device_name=self._wemo_service.get_device_name(
                                record.device_id
                            ),
                            action="off",
                            event_time=off_time.isoformat(),
                            event_type="auto_off",
                        )
                    )
            if record.schedule_type == "daily":
                run_time = self._parse_dt(record.next_run_at) if record.next_run_at else None
                iterations = 0
                while run_time and run_time <= cutoff and iterations < 8:
                    events.append(
                        UpcomingScheduleEvent(
                            schedule_id=record.id,
                            schedule_name=record.name,
                            device_id=record.device_id,
                            device_name=self._wemo_service.get_device_name(
                                record.device_id
                            ),
                            action=record.action,
                            brightness=record.brightness,
                            event_time=run_time.isoformat(),
                            event_type="run",
                        )
                    )
                    if (
                        record.duration_minutes
                        and record.action in {"on", "brightness"}
                    ):
                        auto_off = run_time + timedelta(
                            minutes=record.duration_minutes
                        )
                        if auto_off <= cutoff:
                            events.append(
                                UpcomingScheduleEvent(
                                    schedule_id=record.id,
                                    schedule_name=record.name,
                                    device_id=record.device_id,
                                    device_name=self._wemo_service.get_device_name(
                                        record.device_id
                                    ),
                                    action="off",
                                    event_time=auto_off.isoformat(),
                                    event_type="auto_off",
                                )
                            )
                    run_time = self._next_daily_run(record, run_time)
                    iterations += 1
            elif record.schedule_type == "countdown" and record.next_run_at:
                run_time = self._parse_dt(record.next_run_at)
                if now <= run_time <= cutoff and record.pending_off_at != record.next_run_at:
                    events.append(
                        UpcomingScheduleEvent(
                            schedule_id=record.id,
                            schedule_name=record.name,
                            device_id=record.device_id,
                            device_name=self._wemo_service.get_device_name(
                                record.device_id
                            ),
                            action=record.action,
                            brightness=record.brightness,
                            event_time=run_time.isoformat(),
                            event_type="run",
                        )
                    )
        return sorted(events, key=lambda item: item.event_time)

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        return datetime.fromisoformat(value)

    @staticmethod
    def _now() -> datetime:
        return datetime.now().astimezone()
