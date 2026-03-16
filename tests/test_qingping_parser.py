from __future__ import annotations

from struct import pack
from types import SimpleNamespace

from zion_ble_bridge.devices.qingping.parser import normalize_mac, parse_advertisement_data


def test_normalize_mac_accepts_mixed_formats() -> None:
    assert normalize_mac("58-2d-34-51-d0-f3") == "58:2D:34:51:D0:F3"
    assert normalize_mac("582d3451d0f3") == "58:2D:34:51:D0:F3"


def test_parse_advertisement_data_extracts_environment_values() -> None:
    service_data = (
        b"\x00" * 8
        + bytes([0x01, 0x04])
        + pack("<hH", 243, 636)
        + bytes([0x02, 0x01, 100])
        + bytes([0x0F, 0x01, 7])
    )
    advertisement = SimpleNamespace(
        service_data={"0000fdcd-0000-1000-8000-00805f9b34fb": service_data},
        rssi=-62,
    )

    snapshot = parse_advertisement_data(advertisement)

    assert snapshot is not None
    assert snapshot.temperature == 24.3
    assert snapshot.humidity == 63.6
    assert snapshot.battery == 100
    assert snapshot.packet_id == 7
    assert snapshot.rssi == -62
