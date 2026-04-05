from __future__ import annotations

import logging
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlparse

import pywemo
from pywemo.exceptions import HTTPException, PyWeMoException

from app.config import Settings
from app.schemas import DeviceView, DevicesResponse, InsightMetrics
from app.services.known_device_store import KnownDeviceRecord, KnownDeviceStore
from app.services.manual_device_store import ManualDeviceStore

LOG = logging.getLogger(__name__)

SUPPORTED_SWITCH_TYPES = (
    pywemo.Switch,
    pywemo.Insight,
    pywemo.OutdoorPlug,
    pywemo.LightSwitch,
    pywemo.LightSwitchLongPress,
    pywemo.Dimmer,
    pywemo.DimmerLongPress,
    pywemo.DimmerV2,
)


class DeviceOperationError(RuntimeError):
    """Raised when a device operation cannot be completed."""


@dataclass(slots=True)
class ManagedDevice:
    device: Any
    discovery_method: str
    reachable: bool = True
    seen_in_latest_discovery: bool = True
    status_message: str = "Ready"
    last_error: str | None = None
    last_seen: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_refreshed: datetime | None = None


class WemoService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._manual_store = ManualDeviceStore(settings.manual_addresses_file)
        self._known_store = KnownDeviceStore(settings.known_devices_file)
        self._devices: dict[str, ManagedDevice] = {}
        self._lock = RLock()
        self._last_discovery: datetime | None = None
        self._last_issues: list[str] = []
        self._manual_addresses = self._load_manual_addresses()
        self._known_devices = self._load_known_device_records()
        self._restore_known_devices()

    def _load_manual_addresses(self) -> list[str]:
        configured = {
            item.strip() for item in self.settings.manual_addresses if item.strip()
        }
        stored = {
            item.strip() for item in self._manual_store.load() if item.strip()
        }
        addresses = sorted(configured | stored, key=str.lower)
        if addresses:
            self._manual_store.save(addresses)
        return addresses

    def _load_known_device_records(self) -> dict[str, KnownDeviceRecord]:
        records = self._known_store.load()
        return {record.device_id: record for record in records if record.device_id}

    def _restore_known_devices(self) -> None:
        restored_count = 0
        for record in list(self._known_devices.values()):
            device = self._load_device_from_record(record)
            if device is None:
                continue
            if not self._is_supported_switch(device):
                LOG.info(
                    "Skipping unsupported saved device %s (%s)",
                    record.device_id,
                    device.__class__.__name__,
                )
                continue

            managed = ManagedDevice(
                device=device,
                discovery_method=record.discovery_method,
                status_message="Loaded from saved devices",
            )
            managed.seen_in_latest_discovery = True
            restored_device_id = self._device_id(device)
            if restored_device_id != record.device_id:
                self._known_devices.pop(record.device_id, None)
            self._devices[restored_device_id] = managed
            self._upsert_known_device_record(managed)
            restored_count += 1

        if restored_count:
            self._persist_known_devices()
            LOG.info("Restored %s devices from saved cache", restored_count)

    def list_manual_addresses(self) -> list[str]:
        with self._lock:
            return list(self._manual_addresses)

    def add_manual_address(self, address: str) -> list[str]:
        normalized = address.strip()
        if not normalized:
            raise DeviceOperationError("Manual address cannot be empty.")
        with self._lock:
            if normalized.lower() not in {
                item.lower() for item in self._manual_addresses
            }:
                self._manual_addresses.append(normalized)
                self._manual_addresses.sort(key=str.lower)
                self._manual_store.save(self._manual_addresses)
            return list(self._manual_addresses)

    def remove_manual_address(self, address: str) -> list[str]:
        normalized = address.strip()
        with self._lock:
            remaining = [
                item
                for item in self._manual_addresses
                if item.lower() != normalized.lower()
            ]
            self._manual_addresses = remaining
            self._manual_store.save(self._manual_addresses)
            return list(self._manual_addresses)

    def discover_devices(self, refresh_after: bool = True) -> DevicesResponse:
        with self._lock:
            LOG.info("Starting device discovery")
            for managed in self._devices.values():
                managed.seen_in_latest_discovery = False

            issues: list[str] = []
            discovered: dict[str, ManagedDevice] = {}

            for device in self._discover_ssdp(issues):
                self._remember_discovery(device, "ssdp", discovered)

            for device in self._discover_manual(issues):
                self._remember_discovery(device, "manual", discovered)

            for device in self._discover_saved(issues):
                self._remember_discovery(device, "saved", discovered)

            if refresh_after:
                for managed in discovered.values():
                    self._refresh_managed(managed)

            for device_id, managed in self._devices.items():
                if device_id not in discovered:
                    managed.status_message = (
                        "Not seen in the latest discovery scan"
                    )

            self._last_discovery = datetime.now(timezone.utc)
            self._last_issues = issues
            self._persist_known_devices()
            LOG.info(
                "Discovery complete: %s devices, %s issues",
                len(self._devices),
                len(issues),
            )
            return self._build_devices_response(issues)

    def get_devices(self, refresh: bool = False) -> DevicesResponse:
        with self._lock:
            if refresh:
                for managed in self._devices.values():
                    self._refresh_managed(managed)
            return self._build_devices_response(self._last_issues)

    def refresh_device(self, device_id: str) -> DeviceView:
        with self._lock:
            managed = self._get_managed(device_id)
            self._refresh_managed(managed, raise_on_error=True)
            return self._serialize_device(managed)

    def get_device_name(self, device_id: str) -> str | None:
        with self._lock:
            managed = self._devices.get(device_id)
            return managed.device.name if managed else None

    def device_supports_brightness(self, device_id: str) -> bool:
        with self._lock:
            managed = self._devices.get(device_id)
            if not managed:
                return False
            return self._supports_brightness(managed.device)

    def turn_on(self, device_id: str) -> DeviceView:
        return self._set_power(device_id, power_on=True)

    def turn_off(self, device_id: str) -> DeviceView:
        return self._set_power(device_id, power_on=False)

    def set_brightness(self, device_id: str, brightness: int) -> DeviceView:
        with self._lock:
            managed = self._get_managed(device_id)
            if not self._supports_brightness(managed.device):
                raise DeviceOperationError(
                    f"Brightness control is not supported for {managed.device.name}."
                )

            def operation() -> None:
                managed.device.set_brightness(brightness)
                managed.device.get_state(force_update=True)
                managed.device.get_brightness(force_update=True)

            self._run_with_reconnect(
                managed, operation, f"set brightness to {brightness}%"
            )
            if brightness == 0:
                managed.status_message = "Brightness set to 0%. Device is off."
            else:
                managed.status_message = f"Brightness set to {brightness}%."
            return self._serialize_device(managed)

    def _set_power(self, device_id: str, power_on: bool) -> DeviceView:
        with self._lock:
            managed = self._get_managed(device_id)
            verb = "turn on" if power_on else "turn off"

            def operation() -> None:
                try:
                    if power_on:
                        managed.device.on()
                    else:
                        managed.device.off()
                except Exception:
                    managed.device.get_state(force_update=True)
                    current_state = managed.device.get_state(force_update=False)
                    target_state = 1 if power_on else 0
                    if current_state != target_state:
                        raise
                managed.device.get_state(force_update=True)
                if hasattr(managed.device, "get_brightness"):
                    managed.device.get_brightness(force_update=False)

            self._run_with_reconnect(managed, operation, verb)
            managed.status_message = (
                "Device is on" if power_on else "Device is off"
            )
            return self._serialize_device(managed)

    def _discover_ssdp(self, issues: list[str]) -> list[Any]:
        kwargs: dict[str, Any] = {
            "timeout": self.settings.discovery_timeout,
        }
        if self.settings.discovery_max_entries is not None:
            kwargs["max_entries"] = self.settings.discovery_max_entries
        try:
            return [
                device
                for device in pywemo.discover_devices(**kwargs)
                if self._is_supported_switch(device)
            ]
        except Exception as exc:
            message = self._format_error(exc, "SSDP discovery")
            issues.append(message)
            LOG.warning(message)
            return []

    def _discover_manual(self, issues: list[str]) -> list[Any]:
        return self._discover_from_addresses(
            self._manual_addresses,
            issues,
            source_label="Manual discovery",
            context_label="manual discovery",
        )

    def _discover_saved(self, issues: list[str]) -> list[Any]:
        manual_addresses = {item.lower() for item in self._manual_addresses}
        addresses = [
            address
            for address in self._saved_addresses()
            if address.lower() not in manual_addresses
        ]
        return self._discover_from_addresses(
            addresses,
            issues,
            source_label="Saved device discovery",
            context_label="saved device discovery",
        )

    def _discover_from_addresses(
        self,
        addresses: list[str],
        issues: list[str],
        source_label: str,
        context_label: str,
    ) -> list[Any]:
        devices: list[Any] = []
        for address in addresses:
            try:
                url = pywemo.setup_url_for_address(address)
                if not url:
                    issues.append(
                        f"{source_label} could not find setup.xml for {address}."
                    )
                    continue
                device = pywemo.device_from_description(url)
                if device is None:
                    issues.append(
                        f"{source_label} returned no device for {address}."
                    )
                    continue
                if not self._is_supported_switch(device):
                    issues.append(
                        f"{source_label} skipping unsupported WeMo device at {address}: "
                        f"{device.__class__.__name__}."
                    )
                    continue
                devices.append(device)
            except Exception as exc:
                message = self._format_error(exc, f"{context_label} for {address}")
                issues.append(message)
                LOG.warning(message)
        return devices

    def _remember_discovery(
        self,
        device: Any,
        discovery_method: str,
        discovered: dict[str, ManagedDevice],
    ) -> None:
        device_id = self._device_id(device)
        existing = self._devices.get(device_id)
        if existing:
            existing.device = device
            existing.discovery_method = self._merge_discovery_method(
                existing.discovery_method, discovery_method
            )
            existing.seen_in_latest_discovery = True
            existing.last_seen = datetime.now(timezone.utc)
            existing.reachable = True
            existing.last_error = None
            existing.status_message = "Discovered"
            discovered[device_id] = existing
            self._upsert_known_device_record(existing)
            return

        managed = ManagedDevice(
            device=device,
            discovery_method=discovery_method,
            status_message="Discovered",
        )
        self._devices[device_id] = managed
        discovered[device_id] = managed
        self._upsert_known_device_record(managed)

    def _refresh_managed(
        self, managed: ManagedDevice, raise_on_error: bool = False
    ) -> None:
        def operation() -> None:
            managed.device.get_state(force_update=True)
            if hasattr(managed.device, "get_brightness"):
                managed.device.get_brightness(force_update=False)

        try:
            self._run_with_reconnect(managed, operation, "refresh state")
            managed.status_message = "State refreshed"
        except DeviceOperationError as exc:
            if raise_on_error:
                raise
            managed.status_message = str(exc)

    def _run_with_reconnect(
        self,
        managed: ManagedDevice,
        operation: Callable[[], None],
        action_name: str,
    ) -> None:
        try:
            operation()
            managed.reachable = True
            managed.last_error = None
            managed.last_seen = datetime.now(timezone.utc)
            managed.last_refreshed = managed.last_seen
            return
        except Exception as exc:
            first_message = self._format_error(exc, action_name)
            LOG.warning("%s on %s failed: %s", action_name, managed.device, exc)

        try:
            managed.device.reconnect_with_device()
            operation()
            managed.reachable = True
            managed.last_error = None
            managed.last_seen = datetime.now(timezone.utc)
            managed.last_refreshed = managed.last_seen
            managed.status_message = "Recovered after reconnect"
            return
        except Exception as exc:
            second_message = self._format_error(exc, action_name)
            message = (
                f"{first_message}. Reconnect attempt failed: {second_message}"
            )
            managed.reachable = False
            managed.last_error = message
            managed.last_refreshed = datetime.now(timezone.utc)
            managed.status_message = message
            raise DeviceOperationError(message) from exc

    def _build_devices_response(self, issues: list[str]) -> DevicesResponse:
        devices = sorted(
            (self._serialize_device(managed) for managed in self._devices.values()),
            key=lambda item: (item.type.lower(), item.name.lower()),
        )
        reachable_devices = sum(1 for device in devices if device.reachable)
        partial_discovery = bool(issues) or any(
            not managed.seen_in_latest_discovery
            for managed in self._devices.values()
        )
        return DevicesResponse(
            devices=devices,
            total_devices=len(devices),
            reachable_devices=reachable_devices,
            latest_discovery=self._isoformat(self._last_discovery),
            issues=issues,
            partial_discovery=partial_discovery,
        )

    def _serialize_device(self, managed: ManagedDevice) -> DeviceView:
        device = managed.device
        state_value = getattr(device, "_state", None)
        if state_value == 1:
            state = "on"
        elif state_value == 0:
            state = "off"
        else:
            state = "unknown"

        status = "online"
        if not managed.reachable:
            status = "offline"
        elif not managed.seen_in_latest_discovery:
            status = "stale"

        brightness = None
        brightness_supported = self._supports_brightness(device)
        if brightness_supported:
            brightness = getattr(device, "_brightness", None)

        insight = None
        if isinstance(device, pywemo.Insight):
            insight = InsightMetrics(
                current_power_watts=round(device.current_power_watts, 3),
                today_kwh=round(device.today_kwh, 6),
                total_kwh=round(device.total_kwh, 6),
                wifi_power=device.wifi_power,
                standby_state=device.standby_state.name.lower(),
            )

        return DeviceView(
            id=self._device_id(device),
            name=device.name,
            state=state,
            state_value=state_value,
            reachable=managed.reachable,
            seen_in_latest_discovery=managed.seen_in_latest_discovery,
            discovery_method=managed.discovery_method,
            status=status,
            status_message=managed.status_message,
            last_error=managed.last_error,
            last_seen=self._isoformat(managed.last_seen),
            last_refreshed=self._isoformat(managed.last_refreshed),
            type=device.__class__.__name__,
            model_name=device.model_name,
            model=device.model,
            manufacturer=device.manufacturer,
            firmware_version=device.firmware_version,
            serial_number=device.serial_number,
            mac=device.mac,
            host=device.host,
            port=device.port,
            location=device.session.url,
            services=device.list_services(),
            brightness_supported=brightness_supported,
            brightness=brightness,
            insight=insight,
        )

    def _saved_addresses(self) -> list[str]:
        addresses: list[str] = []
        seen: set[str] = set()
        for record in sorted(
            self._known_devices.values(),
            key=lambda item: (item.name.lower(), item.host.lower()),
        ):
            address = record.host.strip()
            if not address:
                continue
            normalized = address.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            addresses.append(address)
        return addresses

    def _load_device_from_record(self, record: KnownDeviceRecord) -> Any | None:
        try:
            device = pywemo.device_from_description(record.location)
        except Exception as exc:
            LOG.info(
                "Saved device description lookup failed for %s: %s",
                record.device_id,
                self._format_error(exc, "saved device restore"),
            )
            device = None
        if device is not None:
            return device

        try:
            url = pywemo.setup_url_for_address(record.host)
            if not url:
                return None
            return pywemo.device_from_description(url)
        except Exception as exc:
            LOG.info(
                "Saved device address lookup failed for %s (%s): %s",
                record.device_id,
                record.host,
                self._format_error(exc, "saved device restore"),
            )
            return None

    def _upsert_known_device_record(self, managed: ManagedDevice) -> None:
        device = managed.device
        location = getattr(getattr(device, "session", None), "url", "")
        host = getattr(device, "host", "") or self._host_from_location(location)
        if not location or not host:
            return
        self._known_devices[self._device_id(device)] = KnownDeviceRecord(
            device_id=self._device_id(device),
            name=device.name,
            host=host,
            port=int(getattr(device, "port", 0) or 0),
            location=location,
            discovery_method=managed.discovery_method,
            type_name=device.__class__.__name__,
            model_name=getattr(device, "model_name", ""),
            serial_number=getattr(device, "serial_number", ""),
            mac=getattr(device, "mac", ""),
            last_seen=self._isoformat(managed.last_seen),
        )

    def _persist_known_devices(self) -> None:
        self._known_store.save(list(self._known_devices.values()))

    def _get_managed(self, device_id: str) -> ManagedDevice:
        try:
            return self._devices[device_id]
        except KeyError as exc:
            raise DeviceOperationError(f"Unknown device id: {device_id}") from exc

    @staticmethod
    def _device_id(device: Any) -> str:
        return str(device.udn)

    @staticmethod
    def _is_supported_switch(device: Any) -> bool:
        return isinstance(device, SUPPORTED_SWITCH_TYPES)

    @staticmethod
    def _supports_brightness(device: Any) -> bool:
        return hasattr(device, "get_brightness") and hasattr(
            device, "set_brightness"
        )

    @staticmethod
    def _merge_discovery_method(current: str, new: str) -> str:
        methods = {part.strip() for part in current.split("+") if part.strip()}
        methods.add(new)
        return "+".join(sorted(methods))

    @staticmethod
    def _host_from_location(location: str) -> str:
        parsed = urlparse(location)
        return parsed.hostname or ""

    @staticmethod
    def _isoformat(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _format_error(exc: Exception, context: str) -> str:
        if isinstance(exc, DeviceOperationError):
            return str(exc)
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return f"{context.capitalize()} timed out."
        if isinstance(exc, HTTPException):
            return f"{context.capitalize()} failed while contacting the device."
        if isinstance(exc, PyWeMoException):
            return f"{context.capitalize()} failed: {exc}"
        return f"{context.capitalize()} failed: {exc.__class__.__name__}: {exc}"
