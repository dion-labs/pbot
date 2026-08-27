from __future__ import annotations

import argparse
import json

import uvicorn

from .config import Settings
from .device import AdbDeviceAdapter


def main() -> None:
    parser = argparse.ArgumentParser(prog="pbot", description="Pocket Bot local automation harness")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Check the Android control bridge")
    serve = subparsers.add_parser("serve", help="Run the local control API")
    serve.add_argument("--reload", action="store_true", help="Reload after source changes")
    args = parser.parse_args()
    settings = Settings.load()

    if args.command == "doctor":
        report = AdbDeviceAdapter(settings.adb_path, settings.adb_serial).doctor()
        print(json.dumps(report.to_dict(), indent=2))
        raise SystemExit(0 if report.ready else 1)

    uvicorn.run(
        "pbot.api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=args.reload,
    )
