from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path


def _loopback_host(value: str) -> str:
    host = value.strip().lower()
    if host == "localhost":
        return host
    try:
        if ip_address(host).is_loopback:
            return host
    except ValueError:
        pass
    raise ValueError(
        "PBOT_API_HOST must be a loopback address (127.0.0.1, ::1, or localhost); "
        "pbot's unauthenticated control API must not be exposed to a network"
    )


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    database_path: Path
    screenshot_path: Path
    adb_path: str
    adb_serial: str | None
    api_host: str
    api_port: int

    @classmethod
    def load(cls) -> "Settings":
        root = Path(os.environ.get("PBOT_ROOT", Path.cwd())).resolve()
        data_dir = Path(os.environ.get("PBOT_DATA_DIR", root / "var")).resolve()
        configured_adb = os.environ.get("PBOT_ADB")
        standard_adb = Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb"
        adb_path = configured_adb or shutil.which("adb") or (str(standard_adb) if standard_adb.exists() else "adb")
        return cls(
            project_root=root,
            data_dir=data_dir,
            database_path=Path(os.environ.get("PBOT_DATABASE", data_dir / "pbot.sqlite3")),
            screenshot_path=Path(os.environ.get("PBOT_SCREENSHOT", data_dir / "latest.png")),
            adb_path=adb_path,
            adb_serial=os.environ.get("PBOT_ADB_SERIAL") or None,
            api_host=_loopback_host(os.environ.get("PBOT_API_HOST", "127.0.0.1")),
            api_port=int(os.environ.get("PBOT_API_PORT", "8765")),
        )
