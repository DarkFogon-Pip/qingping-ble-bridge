"""Configuration model for Qingping clock control."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from enum import Enum

from ...models import ConfigurationState

CONFIGURATION_VALIDITY_TIME = timedelta(minutes=30)


class Language(Enum):
    """Device language enumeration."""

    EN = "en"
    ZH = "zh"


class Configuration:
    """Protocol-backed configuration object for the Qingping clock."""

    def __init__(self, config_bytes: bytes) -> None:
        self.date = datetime.now()

        self._sound_volume = config_bytes[2]
        # Preserve bytes 3-4 for round-tripping (device header bytes)
        self._header_byte3 = config_bytes[3]
        self._header_byte4 = config_bytes[4]
        self._timezone_offset = config_bytes[6] * 6
        self._screen_light_time = config_bytes[7]

        brightness = self._byte_to_brightness(config_bytes[8])
        self._daytime_brightness, self._nighttime_brightness = brightness
        self._night_time_start_hour = config_bytes[9]
        self._night_time_start_minute = config_bytes[10]
        self._night_time_end_hour = config_bytes[11]
        self._night_time_end_minute = config_bytes[12]
        self._tz_plus_flag = config_bytes[13] == 1
        self._night_mode = config_bytes[14] == 1
        # Preserve ringtone/tail bytes for round-tripping
        self._tail_bytes = bytes(config_bytes[15:20]) if len(config_bytes) >= 20 else b"\xff" * 5

        self._language = Language.ZH if config_bytes[5] & 1 << 0 == 0 else Language.EN
        self._use_24h_format = config_bytes[5] & 1 << 1 == 0
        self._use_celsius = config_bytes[5] & 1 << 2 == 0
        self._alarms_on = config_bytes[5] & 1 << 4 == 0

    @property
    def is_expired(self) -> bool:
        return self.date + CONFIGURATION_VALIDITY_TIME < datetime.now()

    @property
    def sound_volume(self) -> int:
        return self._sound_volume

    @sound_volume.setter
    def sound_volume(self, value: int) -> None:
        if value < 1 or value > 5:
            raise ValueError("Sound volume must be between 1 and 5.")
        self._sound_volume = value

    @property
    def timezone_offset(self) -> int:
        return self._timezone_offset if self._tz_plus_flag else -self._timezone_offset

    @timezone_offset.setter
    def timezone_offset(self, value: int) -> None:
        if value > 720 or value < -720:
            raise ValueError("Timezone offset must be between -720 and 720 minutes.")
        self._timezone_offset = abs(value)
        self._tz_plus_flag = value >= 0

    @property
    def screen_light_time(self) -> int:
        return self._screen_light_time

    @screen_light_time.setter
    def screen_light_time(self, value: int) -> None:
        if value < 1 or value > 30:
            raise ValueError("Screen light time must be between 1 and 30 seconds.")
        self._screen_light_time = value

    @property
    def daytime_brightness(self) -> int:
        return self._daytime_brightness

    @daytime_brightness.setter
    def daytime_brightness(self, value: int) -> None:
        if value < 0 or value > 100:
            raise ValueError("Daytime brightness must be between 0 and 100.")
        self._daytime_brightness = value

    @property
    def nighttime_brightness(self) -> int:
        return self._nighttime_brightness

    @nighttime_brightness.setter
    def nighttime_brightness(self, value: int) -> None:
        if value < 0 or value > 100:
            raise ValueError("Nighttime brightness must be between 0 and 100.")
        self._nighttime_brightness = value

    @property
    def night_time_start_time(self) -> time:
        return time(hour=self._night_time_start_hour, minute=self._night_time_start_minute)

    @night_time_start_time.setter
    def night_time_start_time(self, value: time) -> None:
        self._night_time_start_hour = value.hour
        self._night_time_start_minute = value.minute

    @property
    def night_time_end_time(self) -> time:
        return time(hour=self._night_time_end_hour, minute=self._night_time_end_minute)

    @night_time_end_time.setter
    def night_time_end_time(self, value: time) -> None:
        self._night_time_end_hour = value.hour
        self._night_time_end_minute = value.minute

    @property
    def language(self) -> Language:
        return self._language

    @language.setter
    def language(self, value: Language) -> None:
        self._language = value

    @property
    def use_24h_format(self) -> bool:
        return self._use_24h_format

    @use_24h_format.setter
    def use_24h_format(self, value: bool) -> None:
        self._use_24h_format = value

    @property
    def use_celsius(self) -> bool:
        return self._use_celsius

    @use_celsius.setter
    def use_celsius(self, value: bool) -> None:
        self._use_celsius = value

    @property
    def alarms_on(self) -> bool:
        return self._alarms_on

    @alarms_on.setter
    def alarms_on(self, value: bool) -> None:
        self._alarms_on = value

    @property
    def night_mode_enabled(self) -> bool:
        return self._night_mode

    @night_mode_enabled.setter
    def night_mode_enabled(self, value: bool) -> None:
        self._night_mode = value

    def to_bytes(self) -> bytes:
        payload = bytearray([0x13, 0x01, self.sound_volume])

        # Preserve device header bytes (3-4) instead of 0xFF
        payload.append(self._header_byte3)
        payload.append(self._header_byte4)

        config_byte = 0
        config_byte |= 0 if self.language == Language.ZH else (1 << 0)
        config_byte |= 0 if self.use_24h_format else (1 << 1)
        config_byte |= 0 if self.use_celsius else (1 << 2)
        config_byte |= 0 if self.alarms_on else (1 << 4)
        payload.append(config_byte)

        # Use absolute timezone for the byte (sign is in byte 13)
        payload.append(self._timezone_offset // 6)
        payload.append(self.screen_light_time)
        payload.append(
            self._brightness_to_byte(self.daytime_brightness, self.nighttime_brightness)
        )

        if self._night_mode:
            payload.append(self.night_time_start_time.hour)
            payload.append(self.night_time_start_time.minute)
            payload.append(self.night_time_end_time.hour)
            payload.append(self.night_time_end_time.minute)
        else:
            # Disable night mode with 1-minute window (official app behavior)
            payload.extend([0, 0, 0, 1])

        payload.append(0x01 if self._tz_plus_flag else 0x00)
        payload.append(0x01 if self._night_mode else 0x00)

        # Preserve tail bytes (ringtone signature etc.)
        payload.extend(self._tail_bytes)

        if len(payload) != 20:
            raise ValueError(f"Configuration bytes must be 20 bytes long, got {len(payload)}.")
        return bytes(payload)

    def to_state(self) -> ConfigurationState:
        return ConfigurationState(
            sound_volume=self.sound_volume,
            timezone_offset=self.timezone_offset,
            screen_light_time=self.screen_light_time,
            daytime_brightness=self.daytime_brightness,
            nighttime_brightness=self.nighttime_brightness,
            night_time_start=self.night_time_start_time,
            night_time_end=self.night_time_end_time,
            language=self.language.value,
            use_24h_format=self.use_24h_format,
            use_celsius=self.use_celsius,
            alarms_on=self.alarms_on,
            night_mode_enabled=self.night_mode_enabled,
        )

    def _byte_to_brightness(self, int_value: int) -> tuple[int, int]:
        first_nibble = (int_value >> 4) & 0x0F
        second_nibble = int_value & 0x0F
        return (first_nibble * 10, second_nibble * 10)

    def _brightness_to_byte(self, daytime_brightness: int, nighttime_brightness: int) -> int:
        if not 0 <= daytime_brightness <= 100 or daytime_brightness % 10 != 0:
            raise ValueError("Daytime brightness must be between 0 and 100 and a multiple of 10.")
        if not 0 <= nighttime_brightness <= 100 or nighttime_brightness % 10 != 0:
            raise ValueError(
                "Nighttime brightness must be between 0 and 100 and a multiple of 10."
            )
        return ((daytime_brightness // 10) << 4) | (nighttime_brightness // 10)
