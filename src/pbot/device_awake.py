from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol


MAX_ANDROID_TIMEOUT_MS = "2147483647"


class CommandResult(Protocol):
    stdout: str


CommandRunner = Callable[..., CommandResult]


PERSISTENT_SETTINGS = (
    ("global", "stay_on_while_plugged_in", "7", True),
    ("system", "screen_off_timeout", MAX_ANDROID_TIMEOUT_MS, True),
    ("secure", "lock_screen_lock_after_timeout", MAX_ANDROID_TIMEOUT_MS, False),
    ("secure", "screensaver_enabled", "0", False),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snapshot_path(data_dir: Path, serial: str | None) -> Path:
    safe_serial = re.sub(r"[^A-Za-z0-9_.-]+", "-", serial or "default")
    return data_dir / f"device-awake-{safe_serial}.json"


def wake_and_dismiss(run: CommandRunner) -> None:
    """Wake the display and dismiss only a non-secure keyguard."""
    run("shell", "input", "keyevent", "KEYCODE_WAKEUP")
    run("shell", "wm", "dismiss-keyguard")


def read_setting(run: CommandRunner, namespace: str, name: str) -> str | None:
    value = run("shell", "settings", "get", namespace, name).stdout.strip()
    return None if value in {"", "null"} else value


def policy_status(run: CommandRunner) -> dict[str, str | None]:
    return {
        f"{namespace}.{name}": read_setting(run, namespace, name)
        for namespace, name, _value, _required in PERSISTENT_SETTINGS
    }


def _write_snapshot(path: Path, serial: str | None, settings: dict[str, str | None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {"serial": serial, "captured_at": utc_now(), "settings": settings},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def enable_awake_policy(
    run: CommandRunner,
    path: Path,
    serial: str | None = None,
) -> dict[str, object]:
    """Keep a powered Android device awake and preserve its original settings once."""
    if not path.exists():
        _write_snapshot(path, serial, policy_status(run))

    warnings: list[str] = []
    for namespace, name, value, required in PERSISTENT_SETTINGS:
        try:
            run("shell", "settings", "put", namespace, name, value)
        except Exception as exc:
            if required:
                raise
            warnings.append(f"Could not set {namespace}.{name}: {exc}")

    # This reinforces stay_on_while_plugged_in for Android builds that cache the
    # value in the power service. The persistent setting remains the source of
    # truth across pbot/agent restarts.
    run("shell", "svc", "power", "stayon", "true")
    wake_and_dismiss(run)
    return {"settings": policy_status(run), "warnings": warnings, "snapshot": str(path)}


def restore_awake_policy(run: CommandRunner, path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"No device-awake snapshot exists at {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    original = payload.get("settings", {})
    for namespace, name, _value, _required in PERSISTENT_SETTINGS:
        key = f"{namespace}.{name}"
        value = original.get(key)
        if value is None:
            run("shell", "settings", "delete", namespace, name)
        else:
            run("shell", "settings", "put", namespace, name, str(value))
    return {"settings": policy_status(run), "snapshot": str(path)}
