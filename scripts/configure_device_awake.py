#!/usr/bin/env python3
"""Enable, inspect, or restore pbot's reversible Android awake policy."""

from __future__ import annotations

import argparse
import json

from pbot.config import Settings
from pbot.device import AdbDeviceAdapter
from pbot.device_awake import enable_awake_policy, policy_status, restore_awake_policy, snapshot_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("enable", "status", "restore"), nargs="?", default="enable")
    parser.add_argument("--serial")
    args = parser.parse_args()

    settings = Settings.load()
    serial = args.serial or settings.adb_serial
    device = AdbDeviceAdapter(settings.adb_path, serial, timeout=30)
    path = snapshot_path(settings.data_dir, serial)

    if args.action == "enable":
        result = enable_awake_policy(device._run, path, serial)
    elif args.action == "restore":
        result = restore_awake_policy(device._run, path)
    else:
        result = {"settings": policy_status(device._run), "snapshot": str(path)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
