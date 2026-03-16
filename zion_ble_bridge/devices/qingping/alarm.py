"""Alarm model for Qingping clock control."""

from __future__ import annotations

from datetime import time as dtime
from enum import Enum

from ...models import AlarmState


class AlarmDay(Enum):
    """Alarm day enumeration used by the Qingping protocol."""

    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


class Alarm:
    """Representation of a single device alarm slot."""

    def __init__(self, slot: int, alarm_bytes: bytes) -> None:
        self.slot = slot
        self.is_enabled: bool | None = None
        self.hour: int | None = None
        self.minute: int | None = None
        self.days: set[AlarmDay] | None = None
        self.snooze: bool | None = None

        if alarm_bytes == bytes.fromhex("ffffffffff"):
            return

        self.is_enabled = alarm_bytes[0] == 1
        self.hour = alarm_bytes[1]
        self.minute = alarm_bytes[2]
        self.days = self._bitmask_to_days(alarm_bytes[3])
        self.snooze = alarm_bytes[4] == 1

    @property
    def is_configured(self) -> bool:
        return (
            self.is_enabled is not None
            and self.hour is not None
            and self.minute is not None
            and self.days is not None
            and self.snooze is not None
        )

    @property
    def time(self) -> dtime | None:
        if self.hour is None or self.minute is None:
            return None
        return dtime(self.hour, self.minute)

    @time.setter
    def time(self, value: dtime) -> None:
        self.hour = value.hour
        self.minute = value.minute

    @property
    def days_string(self) -> str:
        abbreviation_map = {
            AlarmDay.MONDAY: "mon",
            AlarmDay.TUESDAY: "tue",
            AlarmDay.WEDNESDAY: "wed",
            AlarmDay.THURSDAY: "thu",
            AlarmDay.FRIDAY: "fri",
            AlarmDay.SATURDAY: "sat",
            AlarmDay.SUNDAY: "sun",
        }
        return ",".join(
            abbreviation_map[day] for day in sorted(self.days or set(), key=lambda day: day.value)
        )

    def deactivate(self) -> None:
        self.is_enabled = None
        self.hour = None
        self.minute = None
        self.days = None
        self.snooze = None

    def to_bytes(self) -> bytes:
        payload = [0x07, 0x05, self.slot]
        if self.is_configured:
            payload.extend(
                [
                    0x01 if self.is_enabled else 0x00,
                    self.hour,
                    self.minute,
                    self._days_to_bitmask(self.days or set()),
                    0x01 if self.snooze else 0x00,
                ]
            )
        else:
            payload.extend([0xFF] * 5)
        return bytes(payload)

    def to_state(self) -> AlarmState:
        return AlarmState(
            slot=self.slot,
            configured=self.is_configured,
            enabled=self.is_enabled,
            time=self.time,
            days=[] if self.days is None else self.days_string.split(","),
            snooze=self.snooze,
        )

    def _bitmask_to_days(self, bitmask: int) -> set[AlarmDay]:
        bit_to_day = {
            1 << 0: AlarmDay.MONDAY,
            1 << 1: AlarmDay.TUESDAY,
            1 << 2: AlarmDay.WEDNESDAY,
            1 << 3: AlarmDay.THURSDAY,
            1 << 4: AlarmDay.FRIDAY,
            1 << 5: AlarmDay.SATURDAY,
            1 << 6: AlarmDay.SUNDAY,
        }
        return {day for bit, day in bit_to_day.items() if bitmask & bit}

    def _days_to_bitmask(self, days: set[AlarmDay]) -> int:
        day_to_bit = {
            AlarmDay.MONDAY: 1 << 0,
            AlarmDay.TUESDAY: 1 << 1,
            AlarmDay.WEDNESDAY: 1 << 2,
            AlarmDay.THURSDAY: 1 << 3,
            AlarmDay.FRIDAY: 1 << 4,
            AlarmDay.SATURDAY: 1 << 5,
            AlarmDay.SUNDAY: 1 << 6,
        }
        bitmask = 0
        for day in days:
            bitmask |= day_to_bit[day]
        return bitmask
