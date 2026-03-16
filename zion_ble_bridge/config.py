"""Runtime configuration for the BLE bridge."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    """Environment-backed bridge settings."""

    host: str
    port: int
    auth_token: str | None
    scan_timeout: float
    operation_timeout: float
    connect_attempts: int


def load_settings() -> Settings:
    """Load settings from environment variables."""
    auth_token = os.getenv("ZION_BLE_BRIDGE_TOKEN") or None
    return Settings(
        host=os.getenv("ZION_BLE_BRIDGE_HOST", "0.0.0.0"),
        port=int(os.getenv("ZION_BLE_BRIDGE_PORT", "58321")),
        auth_token=auth_token,
        scan_timeout=float(os.getenv("ZION_BLE_SCAN_TIMEOUT", "10")),
        operation_timeout=float(os.getenv("ZION_BLE_OPERATION_TIMEOUT", "12")),
        connect_attempts=int(os.getenv("ZION_BLE_CONNECT_ATTEMPTS", "2")),
    )
