from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


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
            api_host=os.environ.get("PBOT_API_HOST", "127.0.0.1"),
            api_port=int(os.environ.get("PBOT_API_PORT", "8765")),
        )
