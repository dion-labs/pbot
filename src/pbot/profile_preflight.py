"""Bind reusable scan evidence to the explicitly selected Android device."""
from __future__ import annotations

from collections.abc import Mapping


class ProfileDeviceMismatch(ValueError):
    """Scan evidence is missing or belongs to a different device."""


def require_profile_device(serial: str | None, profile: Mapping[str, object], scan_name: str) -> None:
    if not serial or profile.get("status") != "ready" or profile.get("device_serial") != serial:
        raise ProfileDeviceMismatch(f"Scan {scan_name} on the selected device before continuing")
