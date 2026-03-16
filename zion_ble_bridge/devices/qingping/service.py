"""Application service for Qingping BLE bridge operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from ...config import Settings
from ...models import AlarmRequest, ConfigurationPatchRequest, QingpingState
from .alarm import AlarmDay
from .configuration import Configuration, Language
from .exceptions import DeviceOperationError, InvalidDeviceConfiguration
from .parser import discover_snapshot, normalize_mac
from .session import QingpingSession

DEFAULT_DEVICE_NAME = "Qingping Alarm Clock"


@dataclass(slots=True)
class DeviceCache:
    """Per-device cached state and serialization lock."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    state: QingpingState | None = None


class QingpingBridgeService:
    """Manage BLE-backed operations for Qingping clock devices."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._devices: dict[str, DeviceCache] = {}

    async def get_state(self, mac: str) -> QingpingState:
        normalized_mac = normalize_mac(mac)
        cache = self._devices.setdefault(normalized_mac, DeviceCache())
        if cache.state is not None:
            return cache.state
        return await self.refresh(normalized_mac)

    async def refresh(self, mac: str) -> QingpingState:
        normalized_mac = normalize_mac(mac)
        cache = self._devices.setdefault(normalized_mac, DeviceCache())
        async with cache.lock:
            return await self._refresh_locked(normalized_mac, cache)

    async def set_time(
        self,
        mac: str,
        timestamp: int,
        timezone_offset: int | None,
    ) -> QingpingState:
        normalized_mac = normalize_mac(mac)
        cache = self._devices.setdefault(normalized_mac, DeviceCache())
        async with cache.lock:
            async with self._open_session(normalized_mac) as session:
                await session.set_time(timestamp, timezone_offset)
                configuration = None
                if timezone_offset is not None:
                    configuration = await session.get_configuration()
            return await self._update_state(
                cache,
                normalized_mac,
                configuration=configuration,
                refresh_sensors=False,
            )

    async def patch_configuration(
        self,
        mac: str,
        payload: ConfigurationPatchRequest,
    ) -> QingpingState:
        normalized_mac = normalize_mac(mac)
        cache = self._devices.setdefault(normalized_mac, DeviceCache())
        async with cache.lock:
            async with self._open_session(normalized_mac) as session:
                configuration = await session.get_configuration()
                self._apply_configuration_patch(configuration, payload)
                configuration = await session.set_configuration(configuration)
            return await self._update_state(
                cache,
                normalized_mac,
                configuration=configuration,
                refresh_sensors=False,
            )

    async def set_alarm(self, mac: str, slot: int, payload: AlarmRequest) -> QingpingState:
        normalized_mac = normalize_mac(mac)
        cache = self._devices.setdefault(normalized_mac, DeviceCache())
        async with cache.lock:
            async with self._open_session(normalized_mac) as session:
                await session.set_alarm(
                    slot,
                    payload.enabled,
                    payload.time,
                    self._alarm_days_from_strings(payload.days),
                    payload.snooze,
                )
                alarms = await session.get_alarms()
            return await self._update_state(
                cache,
                normalized_mac,
                alarms=alarms,
                refresh_sensors=False,
            )

    async def delete_alarm(self, mac: str, slot: int) -> QingpingState:
        normalized_mac = normalize_mac(mac)
        cache = self._devices.setdefault(normalized_mac, DeviceCache())
        async with cache.lock:
            async with self._open_session(normalized_mac) as session:
                await session.delete_alarm(slot)
                alarms = await session.get_alarms()
            return await self._update_state(
                cache,
                normalized_mac,
                alarms=alarms,
                refresh_sensors=False,
            )

    async def _refresh_locked(self, mac: str, cache: DeviceCache) -> QingpingState:
        async with self._open_session(mac) as session:
            configuration, alarms = await session.refresh()
        return await self._update_state(
            cache,
            mac,
            configuration=configuration,
            alarms=alarms,
            refresh_sensors=True,
        )

    def _open_session(self, mac: str) -> QingpingSession:
        return QingpingSession(
            mac,
            scan_timeout=self._settings.scan_timeout,
            operation_timeout=self._settings.operation_timeout,
            connect_attempts=self._settings.connect_attempts,
        )

    async def _update_state(
        self,
        cache: DeviceCache,
        mac: str,
        configuration: Configuration | None = None,
        alarms=None,
        *,
        refresh_sensors: bool,
    ) -> QingpingState:
        previous_state = cache.state
        previous_configuration = previous_state.configuration if previous_state else None
        previous_alarms = previous_state.alarms if previous_state else []
        previous_sensors = previous_state.sensors if previous_state else None

        if configuration is None and previous_configuration is None:
            raise DeviceOperationError("No cached configuration is available")

        sensors = previous_sensors
        if refresh_sensors:
            sensors = await discover_snapshot(mac, self._settings.scan_timeout) or previous_sensors

        cache.state = QingpingState(
            mac=mac,
            name=(previous_state.name if previous_state else DEFAULT_DEVICE_NAME),
            reachable=True,
            last_refresh=datetime.now().astimezone(),
            configuration=(
                configuration.to_state() if configuration is not None else previous_configuration
            ),
            alarms=(
                [alarm.to_state() for alarm in alarms]
                if alarms is not None
                else list(previous_alarms)
            ),
            sensors=sensors,
        )
        return cache.state

    def _apply_configuration_patch(
        self,
        configuration: Configuration,
        payload: ConfigurationPatchRequest,
    ) -> None:
        try:
            if payload.alarms_on is not None:
                configuration.alarms_on = payload.alarms_on
            if payload.sound_volume is not None:
                configuration.sound_volume = payload.sound_volume
            if payload.screen_light_time is not None:
                configuration.screen_light_time = payload.screen_light_time
            if payload.daytime_brightness is not None:
                configuration.daytime_brightness = payload.daytime_brightness
            if payload.nighttime_brightness is not None:
                configuration.nighttime_brightness = payload.nighttime_brightness
            if payload.night_time_start is not None:
                configuration.night_time_start_time = payload.night_time_start
            if payload.night_time_end is not None:
                configuration.night_time_end_time = payload.night_time_end
            if payload.night_mode_enabled is not None:
                configuration.night_mode_enabled = payload.night_mode_enabled
            if payload.language is not None:
                configuration.language = Language(payload.language)
            if payload.use_24h_format is not None:
                configuration.use_24h_format = payload.use_24h_format
            if payload.use_celsius is not None:
                configuration.use_celsius = payload.use_celsius
            if payload.timezone_offset is not None:
                configuration.timezone_offset = payload.timezone_offset
        except ValueError as err:
            raise InvalidDeviceConfiguration(str(err)) from err

    def _alarm_days_from_strings(self, days: list[str] | None) -> set[AlarmDay] | None:
        if days is None:
            return None

        mapping = {
            "mon": AlarmDay.MONDAY,
            "tue": AlarmDay.TUESDAY,
            "wed": AlarmDay.WEDNESDAY,
            "thu": AlarmDay.THURSDAY,
            "fri": AlarmDay.FRIDAY,
            "sat": AlarmDay.SATURDAY,
            "sun": AlarmDay.SUNDAY,
        }
        try:
            return {mapping[day.lower()] for day in days}
        except KeyError as err:
            raise InvalidDeviceConfiguration(f"Unsupported alarm day: {err.args[0]}") from err
