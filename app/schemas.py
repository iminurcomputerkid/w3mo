from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class InsightMetrics(BaseModel):
    current_power_watts: float | None = None
    today_kwh: float | None = None
    total_kwh: float | None = None
    wifi_power: int | None = None
    standby_state: str | None = None


class DeviceView(BaseModel):
    id: str
    name: str
    state: Literal["on", "off", "unknown"]
    state_value: int | None = None
    reachable: bool
    seen_in_latest_discovery: bool
    discovery_method: str
    status: str
    status_message: str
    last_error: str | None = None
    last_seen: str | None = None
    last_refreshed: str | None = None
    type: str
    model_name: str
    model: str
    manufacturer: str
    firmware_version: str
    serial_number: str
    mac: str
    host: str
    port: int
    location: str
    services: list[str] = Field(default_factory=list)
    brightness_supported: bool = False
    brightness: int | None = None
    insight: InsightMetrics | None = None


class DevicesResponse(BaseModel):
    devices: list[DeviceView]
    total_devices: int
    reachable_devices: int
    latest_discovery: str | None = None
    issues: list[str] = Field(default_factory=list)
    partial_discovery: bool = False


class DeviceActionResponse(BaseModel):
    message: str
    device: DeviceView


class BrightnessRequest(BaseModel):
    brightness: int = Field(ge=0, le=100)


class ManualAddressRequest(BaseModel):
    address: str = Field(min_length=1, max_length=255)


class ManualAddressesResponse(BaseModel):
    addresses: list[str] = Field(default_factory=list)


class ScheduleCreateRequest(BaseModel):
    name: str = Field(default="")
    device_id: str
    schedule_type: Literal["countdown", "daily"]
    action: Literal["on", "off", "brightness"]
    brightness: int | None = Field(default=None, ge=0, le=100)
    time_of_day: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    weekdays: list[
        Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    ] = Field(default_factory=list)


class ScheduleToggleRequest(BaseModel):
    enabled: bool


class ScheduleAdjustTimerRequest(BaseModel):
    delta_minutes: int = Field(ge=-720, le=720)


class ScheduleUpdateRequest(BaseModel):
    name: str = Field(default="")
    device_id: str
    action: Literal["on", "off", "brightness"]
    brightness: int | None = Field(default=None, ge=0, le=100)
    time_of_day: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    weekdays: list[
        Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    ] = Field(default_factory=list)


class ScheduleResponse(BaseModel):
    id: str
    name: str
    device_id: str
    device_name: str | None = None
    schedule_type: Literal["countdown", "daily"]
    action: Literal["on", "off", "brightness"]
    brightness: int | None = None
    time_of_day: str | None = None
    duration_minutes: int | None = None
    weekdays: list[str] = Field(default_factory=list)
    enabled: bool
    created_at: str
    last_run_at: str | None = None
    next_run_at: str | None = None
    pending_off_at: str | None = None
    last_error: str | None = None


class UpcomingScheduleEvent(BaseModel):
    schedule_id: str
    schedule_name: str
    device_id: str
    device_name: str | None = None
    action: Literal["on", "off", "brightness"]
    brightness: int | None = None
    event_time: str
    event_type: Literal["run", "auto_off"]


class SchedulesResponse(BaseModel):
    schedules: list[ScheduleResponse] = Field(default_factory=list)
    upcoming_events: list[UpcomingScheduleEvent] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
