"""Shared API models for the BLE bridge."""

from __future__ import annotations

from datetime import datetime, time as dt_time

from pydantic import BaseModel, ConfigDict, Field


class AlarmState(BaseModel):
    """JSON shape for an alarm slot."""

    model_config = ConfigDict(extra="forbid")

    slot: int
    configured: bool
    enabled: bool | None = None
    time: dt_time | None = None
    days: list[str] = Field(default_factory=list)
    snooze: bool | None = None


class ConfigurationState(BaseModel):
    """JSON shape for the Qingping clock configuration."""

    model_config = ConfigDict(extra="forbid")

    sound_volume: int
    timezone_offset: int
    screen_light_time: int
    daytime_brightness: int
    nighttime_brightness: int
    night_time_start: dt_time
    night_time_end: dt_time
    language: str
    use_24h_format: bool
    use_celsius: bool
    alarms_on: bool
    night_mode_enabled: bool


class SensorSnapshot(BaseModel):
    """Latest passive sensor values observed from advertisements."""

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = None
    humidity: float | None = None
    battery: int | None = None
    rssi: int | None = None
    packet_id: int | None = None


class QingpingState(BaseModel):
    """State payload returned by the bridge."""

    model_config = ConfigDict(extra="forbid")

    mac: str
    name: str
    reachable: bool
    last_refresh: datetime | None = None
    configuration: ConfigurationState | None = None
    alarms: list[AlarmState] = Field(default_factory=list)
    sensors: SensorSnapshot | None = None


class SetTimeRequest(BaseModel):
    """Request payload for updating device time."""

    model_config = ConfigDict(extra="forbid")

    timestamp: int
    timezone_offset: int | None = None


class ConfigurationPatchRequest(BaseModel):
    """Request payload for partial configuration updates."""

    model_config = ConfigDict(extra="forbid")

    alarms_on: bool | None = None
    sound_volume: int | None = None
    screen_light_time: int | None = None
    daytime_brightness: int | None = None
    nighttime_brightness: int | None = None
    night_time_start: dt_time | None = None
    night_time_end: dt_time | None = None
    night_mode_enabled: bool | None = None
    language: str | None = None
    use_24h_format: bool | None = None
    use_celsius: bool | None = None
    timezone_offset: int | None = None


class AlarmRequest(BaseModel):
    """Request payload for creating or updating an alarm slot."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    time: dt_time | None = None
    days: list[str] | None = None
    snooze: bool | None = None
