"""Advertisement parsing helpers for Qingping BLE devices."""

from __future__ import annotations

import asyncio
from struct import unpack

from bleak import BleakScanner
from bleak.backends.scanner import AdvertisementData

from ...models import SensorSnapshot

SERVICE_DATA_UUID = "0000fdcd-0000-1000-8000-00805f9b34fb"


def normalize_mac(mac: str) -> str:
    """Normalize a MAC address into uppercase colon-separated form."""
    cleaned = mac.replace("-", "").replace(":", "").strip().upper()
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    return ":".join(cleaned[index : index + 2] for index in range(0, 12, 2))


def parse_advertisement_data(advertisement: AdvertisementData) -> SensorSnapshot | None:
    """Parse Qingping service data into a sensor snapshot."""
    service_data = advertisement.service_data.get(SERVICE_DATA_UUID)
    if not service_data:
        return None

    payload = b"\x00\x00\x00\x00" + service_data
    if len(payload) < 12:
        return None

    snapshot = SensorSnapshot(rssi=advertisement.rssi)
    cursor = 14
    while cursor < len(payload):
        xdata_id = payload[cursor - 2]
        xdata_size = payload[cursor - 1]
        if cursor + xdata_size > len(payload):
            break
        xdata = payload[cursor : cursor + xdata_size]
        if xdata_id == 0x01 and xdata_size == 4:
            temp, humi = unpack("<hH", xdata)
            snapshot.temperature = temp / 10
            snapshot.humidity = humi / 10
        elif xdata_id == 0x02 and xdata_size == 1:
            snapshot.battery = unpack("B", xdata)[0]
        elif xdata_id == 0x0F and xdata_size == 1:
            snapshot.packet_id = unpack("B", xdata)[0]
        cursor += xdata_size + 2
    return snapshot


async def discover_snapshot(mac: str, timeout: float) -> SensorSnapshot | None:
    """Actively scan for a Qingping advertisement snapshot."""
    normalized_mac = normalize_mac(mac)
    result: SensorSnapshot | None = None
    found = asyncio.Event()

    def _detection_callback(device, advertisement_data: AdvertisementData) -> None:
        nonlocal result
        if normalize_mac(device.address) != normalized_mac:
            return
        result = parse_advertisement_data(advertisement_data)
        found.set()

    scanner = BleakScanner(detection_callback=_detection_callback)
    await scanner.start()
    try:
        try:
            await asyncio.wait_for(found.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
    finally:
        await scanner.stop()
    return result
