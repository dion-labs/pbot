#!/usr/bin/env python3
"""Recover structured recommendations from retained pre-migration loss frames."""

from __future__ import annotations

import json
import platform
import subprocess

from pbot.config import Settings
from pbot.recommendation_backfill import (
    backfill_pending_recommendations,
    recognize_with_vision_binary,
)
from pbot.storage import Store


def main() -> None:
    settings = Settings.load()
    binary = settings.data_dir / "vision_ocr"
    if not binary.exists():
        if platform.system() != "Darwin":
            raise SystemExit("Saved-evidence OCR currently requires macOS Apple Vision")
        subprocess.run(
            ["swiftc", str(settings.project_root / "scripts" / "vision_ocr.swift"), "-o", str(binary)],
            check=True,
            timeout=60,
        )
    store = Store(settings.database_path)
    store.initialize()
    outcome = backfill_pending_recommendations(
        store,
        lambda image_path: recognize_with_vision_binary(binary, image_path),
    )
    print(json.dumps(outcome, indent=2))


if __name__ == "__main__":
    main()
