"""Qingping bridge-specific exceptions."""

from __future__ import annotations


class DeviceOperationError(Exception):
    """Raised when the bridge cannot complete a BLE operation."""


class InvalidDeviceConfiguration(DeviceOperationError):
    """Raised when a requested configuration change is invalid."""
