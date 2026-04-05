from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.schemas import (
    BrightnessRequest,
    DeviceActionResponse,
    DevicesResponse,
    HealthResponse,
    ManualAddressRequest,
    ManualAddressesResponse,
    ScheduleCreateRequest,
    ScheduleAdjustTimerRequest,
    SchedulesResponse,
    ScheduleToggleRequest,
    ScheduleUpdateRequest,
)
from app.services.schedule_service import ScheduleService
from app.services.wemo_service import DeviceOperationError, WemoService

router = APIRouter()


def get_service(request: Request) -> WemoService:
    return request.app.state.wemo_service


def get_schedule_service(request: Request) -> ScheduleService:
    return request.app.state.schedule_service


@router.get("/health", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/devices", response_model=DevicesResponse)
def list_devices(request: Request, refresh: bool = False) -> DevicesResponse:
    service = get_service(request)
    return service.get_devices(refresh=refresh)


@router.post("/discover", response_model=DevicesResponse)
def discover_devices(request: Request) -> DevicesResponse:
    service = get_service(request)
    return service.discover_devices(refresh_after=True)


@router.get("/manual-addresses", response_model=ManualAddressesResponse)
def list_manual_addresses(request: Request) -> ManualAddressesResponse:
    service = get_service(request)
    return ManualAddressesResponse(addresses=service.list_manual_addresses())


@router.post("/manual-addresses", response_model=ManualAddressesResponse)
def add_manual_address(
    request: Request, payload: ManualAddressRequest
) -> ManualAddressesResponse:
    service = get_service(request)
    try:
        addresses = service.add_manual_address(payload.address)
    except DeviceOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ManualAddressesResponse(addresses=addresses)


@router.delete("/manual-addresses")
def remove_manual_address(request: Request, address: str) -> JSONResponse:
    service = get_service(request)
    addresses = service.remove_manual_address(address)
    return JSONResponse({"addresses": addresses})


@router.get("/schedules", response_model=SchedulesResponse)
def list_schedules(request: Request) -> SchedulesResponse:
    service = get_schedule_service(request)
    return SchedulesResponse(
        schedules=service.list_schedules(),
        upcoming_events=service.list_upcoming_events(),
    )


@router.post("/schedules", response_model=SchedulesResponse)
def create_schedule(
    request: Request, payload: ScheduleCreateRequest
) -> SchedulesResponse:
    service = get_schedule_service(request)
    try:
        service.create_schedule(payload)
    except DeviceOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SchedulesResponse(
        schedules=service.list_schedules(),
        upcoming_events=service.list_upcoming_events(),
    )


@router.delete("/schedules/{schedule_id}", response_model=SchedulesResponse)
def delete_schedule(request: Request, schedule_id: str) -> SchedulesResponse:
    service = get_schedule_service(request)
    service.delete_schedule(schedule_id)
    return SchedulesResponse(
        schedules=service.list_schedules(),
        upcoming_events=service.list_upcoming_events(),
    )


@router.post("/schedules/{schedule_id}/toggle", response_model=SchedulesResponse)
def toggle_schedule(
    request: Request, schedule_id: str, payload: ScheduleToggleRequest
) -> SchedulesResponse:
    service = get_schedule_service(request)
    try:
        service.toggle_schedule(schedule_id, payload.enabled)
    except DeviceOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SchedulesResponse(
        schedules=service.list_schedules(),
        upcoming_events=service.list_upcoming_events(),
    )


@router.put("/schedules/{schedule_id}", response_model=SchedulesResponse)
def update_schedule(
    request: Request, schedule_id: str, payload: ScheduleUpdateRequest
) -> SchedulesResponse:
    service = get_schedule_service(request)
    try:
        service.update_schedule(schedule_id, payload)
    except DeviceOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SchedulesResponse(
        schedules=service.list_schedules(),
        upcoming_events=service.list_upcoming_events(),
    )


@router.post(
    "/schedules/{schedule_id}/adjust-timer", response_model=SchedulesResponse
)
def adjust_timer(
    request: Request, schedule_id: str, payload: ScheduleAdjustTimerRequest
) -> SchedulesResponse:
    service = get_schedule_service(request)
    try:
        service.adjust_countdown_timer(schedule_id, payload.delta_minutes)
    except DeviceOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SchedulesResponse(
        schedules=service.list_schedules(),
        upcoming_events=service.list_upcoming_events(),
    )


@router.post("/devices/{device_id}/refresh", response_model=DeviceActionResponse)
def refresh_device(request: Request, device_id: str) -> DeviceActionResponse:
    service = get_service(request)
    try:
        device = service.refresh_device(device_id)
    except DeviceOperationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DeviceActionResponse(message="Device refreshed.", device=device)


@router.post("/devices/{device_id}/on", response_model=DeviceActionResponse)
def turn_on(request: Request, device_id: str) -> DeviceActionResponse:
    service = get_service(request)
    try:
        device = service.turn_on(device_id)
    except DeviceOperationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DeviceActionResponse(message="Device turned on.", device=device)


@router.post("/devices/{device_id}/off", response_model=DeviceActionResponse)
def turn_off(request: Request, device_id: str) -> DeviceActionResponse:
    service = get_service(request)
    try:
        device = service.turn_off(device_id)
    except DeviceOperationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DeviceActionResponse(message="Device turned off.", device=device)


@router.post(
    "/devices/{device_id}/brightness", response_model=DeviceActionResponse
)
def set_brightness(
    request: Request, device_id: str, payload: BrightnessRequest
) -> DeviceActionResponse:
    service = get_service(request)
    try:
        device = service.set_brightness(device_id, payload.brightness)
    except DeviceOperationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DeviceActionResponse(
        message=f"Brightness set to {payload.brightness}%.",
        device=device,
    )
