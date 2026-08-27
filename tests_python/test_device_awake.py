import json
import subprocess
from pathlib import Path

from pbot.device_awake import (
    MAX_ANDROID_TIMEOUT_MS,
    enable_awake_policy,
    restore_awake_policy,
)


class FakeAdb:
    def __init__(self) -> None:
        self.settings = {
            "global.stay_on_while_plugged_in": "0",
            "system.screen_off_timeout": "30000",
            "secure.lock_screen_lock_after_timeout": "5000",
            "secure.screensaver_enabled": None,
        }
        self.commands: list[tuple[str, ...]] = []

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.commands.append(args)
        if args[:3] == ("shell", "settings", "get"):
            key = f"{args[3]}.{args[4]}"
            return subprocess.CompletedProcess(args, 0, f"{self.settings.get(key) or 'null'}\n", "")
        if args[:3] == ("shell", "settings", "put"):
            self.settings[f"{args[3]}.{args[4]}"] = args[5]
        elif args[:3] == ("shell", "settings", "delete"):
            self.settings[f"{args[3]}.{args[4]}"] = None
        return subprocess.CompletedProcess(args, 0, "", "")


def test_awake_policy_is_persistent_and_reversible(tmp_path: Path) -> None:
    adb = FakeAdb()
    snapshot = tmp_path / "awake.json"

    enabled = enable_awake_policy(adb.run, snapshot, "phone-1")

    assert enabled["warnings"] == []
    assert adb.settings["global.stay_on_while_plugged_in"] == "7"
    assert adb.settings["system.screen_off_timeout"] == MAX_ANDROID_TIMEOUT_MS
    assert ("shell", "svc", "power", "stayon", "true") in adb.commands
    assert ("shell", "input", "keyevent", "KEYCODE_WAKEUP") in adb.commands
    assert json.loads(snapshot.read_text())["serial"] == "phone-1"

    # Enabling again must retain the first snapshot, not snapshot pbot's values.
    enable_awake_policy(adb.run, snapshot, "phone-1")
    restore_awake_policy(adb.run, snapshot)

    assert adb.settings["global.stay_on_while_plugged_in"] == "0"
    assert adb.settings["system.screen_off_timeout"] == "30000"
    assert adb.settings["secure.lock_screen_lock_after_timeout"] == "5000"
    assert adb.settings["secure.screensaver_enabled"] is None
