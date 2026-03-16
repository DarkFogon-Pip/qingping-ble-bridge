"""Direct BLE session for Qingping clock control."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import time as dtime

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    close_stale_connections_by_address,
    establish_connection,
)

from .alarm import Alarm, AlarmDay
from .configuration import Configuration
from .exceptions import DeviceOperationError
from .parser import normalize_mac

ALARM_SLOTS_COUNT = 18
MAIN_CHAR = "00000001-0000-1000-8000-00805f9b34fb"
CFG_WRITE_CHAR = "0000000B-0000-1000-8000-00805f9b34fb"
CFG_READ_CHAR = "0000000C-0000-1000-8000-00805f9b34fb"
EMPTY_ALARM_BYTES = bytes.fromhex("ffffffffff")
_LOGGER = logging.getLogger(__name__)


class QingpingSession:
    """Single-operation BLE session against a Qingping alarm clock."""

    def __init__(
        self,
        mac: str,
        *,
        scan_timeout: float,
        operation_timeout: float,
        connect_attempts: int = 2,
    ) -> None:
        self.mac = normalize_mac(mac)
        self.scan_timeout = scan_timeout
        self.operation_timeout = operation_timeout
        self.connect_attempts = max(1, connect_attempts)
        self.client: BleakClientWithServiceCache | None = None
        self.configuration: Configuration | None = None
        self.alarms: list[Alarm] = []
        self._configuration_event = asyncio.Event()
        self._alarms_event = asyncio.Event()
        self._alarms_by_slot: dict[int, Alarm] = {}

    async def __aenter__(self) -> QingpingSession:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, exc_tb) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self.connect_attempts + 1):
            try:
                await self._connect_with_active_scan()
                return
            except Exception as err:  # noqa: BLE001
                last_error = err
                await self.disconnect()
                _LOGGER.debug(
                    "Initial BLE discovery/connect attempt %s/%s failed for %s: %r",
                    attempt,
                    self.connect_attempts,
                    self.mac,
                    err,
                )

            await self._prime_connection_with_bluetoothctl()

            try:
                await self._connect_with_active_scan()
                return
            except Exception as err:  # noqa: BLE001
                last_error = err
                await self.disconnect()
                _LOGGER.debug(
                    "Primed BLE discovery/connect attempt %s/%s failed for %s: %r",
                    attempt,
                    self.connect_attempts,
                    self.mac,
                    err,
                )
                if attempt < self.connect_attempts:
                    await asyncio.sleep(1)

        raise DeviceOperationError(f"Failed to connect to {self.mac}: {last_error}")

    async def disconnect(self) -> None:
        if self.client is None:
            return

        try:
            if self.client.is_connected:
                await self.client.disconnect()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Ignoring disconnect failure for %s: %r", self.mac, err)
        finally:
            self.client = None

    async def refresh(self) -> tuple[Configuration, list[Alarm]]:
        await self.get_configuration()
        await self.get_alarms()
        if self.configuration is None:
            raise DeviceOperationError("Device configuration was not received")
        return self.configuration, self.alarms

    async def get_configuration(self) -> Configuration:
        self._configuration_event.clear()
        await self._write_config(b"\x01\x02")
        await self._wait_for_event(self._configuration_event, "configuration")
        if self.configuration is None:
            raise DeviceOperationError("Configuration payload was empty")
        return self.configuration

    async def set_configuration(self, configuration: Configuration) -> Configuration:
        await self._write_config(configuration.to_bytes())
        return await self.get_configuration()

    async def set_time(self, timestamp: int, timezone_offset: int | None = None) -> None:
        start_time = time.time()
        configuration = await self.get_configuration()
        adjusted_timestamp = int(timestamp + (time.time() - start_time))
        await self._write_gatt_char(MAIN_CHAR, self._get_timestamp_bytes(adjusted_timestamp))

        if timezone_offset is not None and configuration.timezone_offset != timezone_offset:
            configuration.timezone_offset = timezone_offset
            await self.set_configuration(configuration)

    async def get_alarms(self) -> list[Alarm]:
        self._alarms_by_slot = {}
        self._alarms_event.clear()
        await self._write_config(b"\x01\x06")
        await self._wait_for_event(self._alarms_event, "alarms")
        return self.alarms

    async def set_alarm(
        self,
        slot: int,
        is_enabled: bool | None,
        value: dtime | None,
        days: set[AlarmDay] | None,
        snooze: bool | None,
    ) -> None:
        alarms = await self.get_alarms()
        if not 0 <= slot < ALARM_SLOTS_COUNT:
            raise DeviceOperationError(f"Alarm slot {slot} is out of range")

        alarm = alarms[slot]
        if is_enabled is not None:
            alarm.is_enabled = is_enabled
        if value is not None:
            alarm.time = value
        if days is not None:
            alarm.days = days
        if snooze is not None:
            alarm.snooze = snooze

        if not alarm.is_configured:
            raise DeviceOperationError("Alarm is not fully configured")

        await self._write_config(alarm.to_bytes())
        await self.get_alarms()

    async def delete_alarm(self, slot: int) -> None:
        alarms = await self.get_alarms()
        if not 0 <= slot < ALARM_SLOTS_COUNT:
            raise DeviceOperationError(f"Alarm slot {slot} is out of range")
        alarms[slot].deactivate()
        await self._write_config(alarms[slot].to_bytes())
        await self.get_alarms()

    async def _connect_with_active_scan(self) -> None:
        device, scanner = await self._discover_device_with_active_scan()
        if device is None or scanner is None:
            raise DeviceOperationError(f"Could not discover {self.mac} over BLE")

        try:
            await asyncio.wait_for(
                self._establish_session(device),
                timeout=self.operation_timeout + 3,
            )
        finally:
            await scanner.stop()

    async def _discover_device_with_active_scan(self) -> tuple[BLEDevice | None, BleakScanner | None]:
        found = asyncio.Event()
        discovered_device: BLEDevice | None = None

        def _detection_callback(device: BLEDevice, _advertisement_data) -> None:
            nonlocal discovered_device
            if normalize_mac(device.address) != self.mac:
                return
            discovered_device = device
            found.set()

        scanner = BleakScanner(detection_callback=_detection_callback)
        await scanner.start()
        try:
            await asyncio.wait_for(found.wait(), timeout=self.scan_timeout)
        except asyncio.TimeoutError:
            await scanner.stop()
            return None, None
        return discovered_device, scanner

    async def _establish_session(self, device: BLEDevice) -> None:
        await close_stale_connections_by_address(self.mac)
        self.client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            self.mac,
            timeout=self.operation_timeout,
        )
        await asyncio.sleep(0.5)
        await self.client.start_notify(CFG_READ_CHAR, self._notification_handler)

        # Time sync unlocks persistent config writes on Qingping clocks
        await self._sync_time()

    async def _sync_time(self) -> None:
        """Send current unix timestamp to the device.

        This is required before config writes — the device only persists
        changes to flash after receiving a valid time sync.
        """
        timestamp = int(time.time())
        _LOGGER.debug("Syncing time to %s: %d", self.mac, timestamp)
        await self._write_gatt_char(MAIN_CHAR, self._get_timestamp_bytes(timestamp))
        await asyncio.sleep(0.3)

    async def _prime_connection_with_bluetoothctl(self) -> None:
        process = await asyncio.create_subprocess_exec(
            "bluetoothctl",
            "connect",
            self.mac,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(process.communicate(), timeout=self.operation_timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
        await asyncio.sleep(1)

    async def _write_config(self, data: bytes) -> None:
        await self._write_gatt_char(CFG_WRITE_CHAR, data)

    async def _write_gatt_char(self, uuid: str, data: bytes) -> None:
        if not self.client or not self.client.is_connected:
            raise DeviceOperationError("Device is not connected")
        await self.client.write_gatt_char(uuid, data)

    async def _wait_for_event(self, event: asyncio.Event, description: str) -> None:
        try:
            await asyncio.wait_for(event.wait(), timeout=self.operation_timeout)
        except asyncio.TimeoutError as err:
            raise DeviceOperationError(f"Timed out waiting for {description}") from err

    def _get_timestamp_bytes(self, timestamp: int) -> bytes:
        payload = [0x05, 0x09]
        payload.extend((timestamp >> shift) & 0xFF for shift in (0, 8, 16, 24))
        return bytes(payload)

    def _notification_handler(self, sender, data: bytearray) -> None:
        sender_uuid = getattr(sender, "uuid", "")
        if str(sender_uuid).lower() != CFG_READ_CHAR.lower():
            return

        if data.startswith(b"\x13\x02"):
            self.configuration = Configuration(bytes(data))
            self._configuration_event.set()
            return

        if data.startswith(b"\x11\x06") and len(data) == 18:
            slot_offset = data[2]
            for chunk_index, start in enumerate((3, 8, 13)):
                slot = slot_offset + chunk_index
                if slot >= ALARM_SLOTS_COUNT:
                    break
                self._alarms_by_slot[slot] = Alarm(slot, bytes(data[start : start + 5]))
            if slot_offset + 3 >= ALARM_SLOTS_COUNT:
                self.alarms = [
                    self._alarms_by_slot.get(slot, Alarm(slot, EMPTY_ALARM_BYTES))
                    for slot in range(ALARM_SLOTS_COUNT)
                ]
                self._alarms_event.set()
