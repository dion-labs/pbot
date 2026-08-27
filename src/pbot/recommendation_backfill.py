from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from .storage import Store
from .strategy import parse_battle_recommendation


TextRecognizer = Callable[[Path], str]
SEQUENCED_PILOT_FRAME = re.compile(r"^(\d+)-pilot-")


def followup_evidence_paths(evidence_path: Path, limit: int = 5) -> list[Path]:
    """Find the immediately retained result-lifecycle frames after an attempt result."""
    match = SEQUENCED_PILOT_FRAME.match(evidence_path.name)
    if not match or limit < 1 or not evidence_path.parent.is_dir():
        return []
    sequence = int(match.group(1))
    candidates: list[Path] = []
    for offset in range(1, limit + 1):
        candidates.extend(sorted(evidence_path.parent.glob(f"{sequence + offset:04d}-pilot-*.png")))
    return candidates


def recognize_with_vision_binary(binary: Path, image_path: Path) -> str:
    result = subprocess.run(
        [str(binary), str(image_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(result.stdout)
    return "\n".join(str(item["text"]) for item in payload.get("observations", []))


def backfill_pending_recommendations(
    store: Store,
    recognize: TextRecognizer,
    followup_limit: int = 5,
) -> dict[str, object]:
    """Recover structured recommendations from pre-migration saved loss evidence."""
    checked = 0
    captured: list[dict[str, object]] = []
    unresolved: list[str] = []
    for item in store.pending_recommendation_backfill():
        battle_id = str(item["battle_id"])
        evidence = Path(str(item["evidence_path"]))
        found = False
        for candidate in followup_evidence_paths(evidence, followup_limit):
            checked += 1
            parsed = parse_battle_recommendation(recognize(candidate))
            if not parsed:
                continue
            row = store.record_battle_recommendation(
                battle_id,
                int(item["attempt_id"]),
                parsed.recommended_type,
                parsed.recommended_deck_name,
                parsed.source_text,
                parsed.confidence,
                str(candidate),
            )
            captured.append(row)
            found = True
            break
        if not found:
            unresolved.append(battle_id)
    return {
        "checked_frames": checked,
        "captured_count": len(captured),
        "captured": captured,
        "unresolved": unresolved,
    }
