# Zion BLE Bridge

A Python REST API bridge for controlling **Qingping Alarm Clocks** (CGC1 / CGD1) over Bluetooth Low Energy. Exposes temperature, humidity, battery, and full device configuration (language, alarms, brightness, night mode, etc.) via a simple HTTP API.

Built for integration with **Home Assistant** via RESTful sensors, but works with anything that can call HTTP endpoints.

## Features

- Read temperature, humidity, and battery from BLE advertisements
- Read and write all device configuration (language, volume, brightness, time format, temp unit, night mode)
- Manage up to 18 alarm slots (create, update, delete)
- Sync device time from host clock
- Bearer token authentication for the API
- Auto-retry with bluetoothctl fallback for flaky BLE connections

## Quick Start

```bash
# Clone and set up
git clone https://github.com/yourusername/zion-ble-bridge.git
cd zion-ble-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Run (replace with your device MAC)
export ZION_BLE_BRIDGE_TOKEN="your-secret-token"
uvicorn zion_ble_bridge.app:app --host 0.0.0.0 --port 58321
```

## API Endpoints

All endpoints (except `/healthz`) require `Authorization: Bearer <token>`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Health check (no auth) |
| `GET` | `/api/v1/qingping/{mac}/state` | Get cached device state |
| `POST` | `/api/v1/qingping/{mac}/refresh` | Force BLE reconnect and re-read |
| `POST` | `/api/v1/qingping/{mac}/time` | Sync device time |
| `PATCH` | `/api/v1/qingping/{mac}/configuration` | Update device settings |
| `PUT` | `/api/v1/qingping/{mac}/alarms/{slot}` | Set an alarm (slots 0-17) |
| `DELETE` | `/api/v1/qingping/{mac}/alarms/{slot}` | Delete an alarm |

### Example: Change Language to English

```bash
curl -X PATCH \
  -H "Authorization: Bearer your-secret-token" \
  -H "Content-Type: application/json" \
  -d '{"language": "en"}' \
  http://localhost:58321/api/v1/qingping/58:2D:34:51:D0:F3/configuration
```

### Example: Set an Alarm

```bash
curl -X PUT \
  -H "Authorization: Bearer your-secret-token" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "time": "07:30", "days": ["mon","tue","wed","thu","fri"], "snooze": true}' \
  http://localhost:58321/api/v1/qingping/58:2D:34:51:D0:F3/alarms/0
```

### Configuration Fields

| Field | Type | Values |
|-------|------|--------|
| `language` | string | `"en"`, `"zh"` |
| `sound_volume` | int | 1-5 |
| `use_24h_format` | bool | |
| `use_celsius` | bool | |
| `alarms_on` | bool | Master alarm toggle |
| `screen_light_time` | int | 1-30 (seconds) |
| `daytime_brightness` | int | 0-100 (multiples of 10) |
| `nighttime_brightness` | int | 0-100 (multiples of 10) |
| `night_mode_enabled` | bool | |
| `night_time_start` | time | e.g. `"21:00"` |
| `night_time_end` | time | e.g. `"06:00"` |
| `timezone_offset` | int | Minutes from UTC (usually 0, see protocol notes) |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ZION_BLE_BRIDGE_HOST` | `0.0.0.0` | Listen address |
| `ZION_BLE_BRIDGE_PORT` | `58321` | Listen port |
| `ZION_BLE_BRIDGE_TOKEN` | *(none)* | Bearer token for API auth (disabled if unset) |
| `ZION_BLE_SCAN_TIMEOUT` | `10` | BLE scan timeout in seconds |
| `ZION_BLE_OPERATION_TIMEOUT` | `12` | BLE operation timeout in seconds |
| `ZION_BLE_CONNECT_ATTEMPTS` | `2` | Connection retry attempts |

## Deployment (systemd)

```bash
# Copy service file
sudo cp deploy/zion-ble-bridge.service /etc/systemd/system/

# Create env file
sudo tee /etc/zion-ble-bridge.env << EOF
ZION_BLE_BRIDGE_HOST=0.0.0.0
ZION_BLE_BRIDGE_PORT=58321
ZION_BLE_BRIDGE_TOKEN=your-secret-token
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now zion-ble-bridge
```

## Home Assistant Integration

Add REST sensors to your HA `configuration.yaml`:

```yaml
rest:
  - resource: "http://YOUR_HOST:58321/api/v1/qingping/58:2D:34:51:D0:F3/state"
    headers:
      Authorization: "Bearer your-secret-token"
    scan_interval: 30
    sensor:
      - name: "Alarm Clock Temperature"
        value_template: "{{ value_json.sensors.temperature }}"
        unit_of_measurement: "°C"
        device_class: temperature
      - name: "Alarm Clock Humidity"
        value_template: "{{ value_json.sensors.humidity }}"
        unit_of_measurement: "%"
        device_class: humidity
      - name: "Alarm Clock Battery"
        value_template: "{{ value_json.sensors.battery }}"
        unit_of_measurement: "%"
        device_class: battery
```

---

## Qingping CGC1/CGD1 BLE Protocol

> **This is the result of hands-on reverse engineering.** If you're building your own integration for Qingping alarm clocks, this section documents the key protocol details that aren't available elsewhere.

### GATT Services and Characteristics

**Vendor Service:** `22210000-554a-4546-5542-46534450464d`

| UUID | Properties | Purpose |
|------|-----------|---------|
| `00000001-0000-1000-8000-00805f9b34fb` | write | Auth writes, time sync |
| `00000002-0000-1000-8000-00805f9b34fb` | notify | Auth ACKs |
| `0000000b-0000-1000-8000-00805f9b34fb` | write | Config/alarm writes |
| `0000000c-0000-1000-8000-00805f9b34fb` | notify | Config/alarm responses |
| `00000100-0000-1000-8000-00805f9b34fb` | notify | Sensor data |

**Xiaomi Service** (`0000fe95-...`) is also present but not used for configuration.

### Critical: Time Sync Unlocks Persistent Writes

**This is the most important protocol detail.** The device will accept configuration writes at any time, but they only go to **volatile RAM**. Changes revert when the BLE session ends.

To make writes persist to **flash**, you must send a **time sync command** at the start of each BLE session:

```
Write to 00000001: 05 09 [4-byte little-endian Unix timestamp]
```

Example (Python):
```python
import time
timestamp = int(time.time())
payload = bytes([0x05, 0x09]) + timestamp.to_bytes(4, 'little')
await client.write_gatt_char("00000001-...", payload)
```

Without this, the device behaves as if writes succeed (reads back the new values within the same session), but **reverts everything on disconnect**. This is the #1 gotcha when working with these devices.

### Authentication (Optional)

The CGC1 accepts auth writes (`0x11 0x01` + token, `0x11 0x02` + token) on char `00000001` but **does not validate them**. Auth is effectively a no-op on this model. The time sync alone is sufficient for persistent writes.

The CGD1 may behave differently — the [clOwOck project](https://github.com/MrBoombastic/clOwOck) documents a token-based auth flow for that model.

### Configuration Read/Write

**Read:** Write `01 02` to char `0000000b`. Response arrives as a 20-byte notification on `0000000c` starting with `13 02`.

**Write:** Write 20 bytes to char `0000000b` starting with `13 01`. Response is an ACK on `0000000c`: `04 FF 01 00 00`.

### Configuration Byte Map (20 bytes)

```
Byte  Purpose
----  -------
[0]   0x13 (command: configuration)
[1]   0x01 (write) / 0x02 (read response)
[2]   Volume (1-5)
[3]   Device header (preserve from read)
[4]   Device header (preserve from read)
[5]   Flags bitfield:
        bit 0: language (0=Chinese, 1=English)
        bit 1: time format (0=24h, 1=12h)
        bit 2: temp unit (0=Celsius, 1=Fahrenheit)
        bit 4: alarms disabled (0=on, 1=off)
[6]   Timezone offset: abs(minutes) / 6
[7]   Screen backlight duration (seconds)
[8]   Brightness: high nibble = day/10, low nibble = night/10
[9]   Night mode start hour (0 if disabled)
[10]  Night mode start minute (0 if disabled)
[11]  Night mode end hour (0 if disabled)
[12]  Night mode end minute (1 if disabled — creates 1-min window)
[13]  Timezone sign (1=positive, 0=negative)
[14]  Night mode (1=enabled, 0=disabled)
[15-19] Ringtone signature + padding (preserve from read)
```

**Important:** Bytes 3-4 and 15-19 must be **preserved from the last read**. Setting them to `0xFF` causes the write to be treated differently. Always read config first, modify the fields you need, and write back the full 20 bytes.

### Night Mode Disable Trick

The night mode enable flag (byte 14) alone doesn't reliably disable night mode. The official Qingping app uses a trick: set the night window to `00:00 - 00:01` (a 1-minute window) to effectively disable it.

### Alarm Read/Write

**Read:** Write `01 06` to char `0000000b`. Response arrives in chunks of 18 bytes on `0000000c`, starting with `11 06`, containing 3 alarm slots per chunk (5 bytes each). An unconfigured slot is `FF FF FF FF FF`.

**Write:** Write 8 bytes to char `0000000b`:
```
07 05 [slot] [enabled] [hour] [minute] [days_bitmask] [snooze]
```

Days bitmask: bit 0=Mon, bit 1=Tue, ..., bit 6=Sun.

### Timezone Note

The `timezone_offset` in the config byte map is relative to the device's internal clock. If you sync time using a UTC Unix timestamp, set `timezone_offset` to **0** — the device handles local time conversion internally. Setting a non-zero offset will double-apply the timezone correction.

## Supported Devices

| Model | Name | Tested |
|-------|------|--------|
| CGC1 | Qingping BT Clock Lite | Yes |
| CGD1 | Qingping BT Alarm Clock | Should work (same vendor service) |

## Credits

- Protocol insights from [clOwOck](https://github.com/MrBoombastic/clOwOck) (CGD1 reverse engineering)
- BLE connectivity via [bleak](https://github.com/hbldh/bleak) and [bleak-retry-connector](https://github.com/bluetooth-devices/bleak-retry-connector)
