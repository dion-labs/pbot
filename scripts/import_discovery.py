#!/usr/bin/env python3
"""Normalize a visual discovery checkpoint and import it into pbot's database."""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path

from pbot.config import Settings
from pbot.storage import Store


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def pretty_expansion(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", " ", value.strip().upper()).strip()
    special = {
        "DELUXE PACK EX": "Deluxe Pack: ex",
        "EVERYDA WONDERS": "Everyday Wonders",
        "SPACE TIME SMACKDOWN": "Space-Time Smackdown",
        "WISDOM OF SEA AND SKY": "Wisdom of Sea and Sky",
        "RULER OF THE SKIES": "Ruler of the Skies",
    }
    return special.get(normalized, normalized.title())


def repair_expansion(name: str, expansion: str, known: list[str]) -> str:
    if expansion != "Unknown expansion":
        return pretty_expansion(expansion)
    fragment_match = re.search(r"\(([^()]*)", name)
    fragment = fragment_match.group(1) if fragment_match else name
    return max(known, key=lambda candidate: difflib.SequenceMatcher(None, fragment.casefold(), candidate.casefold()).ratio())


def canonical_name(name: str, expansion: str) -> str:
    prefix = name.split("Deck", 1)[0] + "Deck"
    prefix = re.sub(r"^[^A-Za-z0-9]+(?:V\s+)?", "", prefix)
    prefix = re.sub(r"\s+[\^V]+\s*$", "", prefix)
    prefix = re.sub(r"\s+", " ", prefix).strip()
    return f"{prefix} ({expansion})"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.catalog.read_text())
    known = sorted({pretty_expansion(str(item["title_hint"])) for item in payload.get("expansions", [])})
    normalized: dict[str, dict[str, object]] = {}
    for raw in payload.get("battles", []):
        expansion = repair_expansion(str(raw["name"]), str(raw["expansion"]), known)
        name = canonical_name(str(raw["name"]), expansion)
        battle_id = f"{slug(expansion)}:{slug(str(raw['difficulty']))}:{slug(name)}"
        item = {**raw, "id": battle_id, "expansion": expansion, "name": name}
        current = normalized.get(battle_id)
        if current:
            item["first_win"] = bool(current["first_win"]) or bool(item["first_win"])
            item["missions_complete"] = max(int(current["missions_complete"]), int(item["missions_complete"]))
            item["missions_total"] = max(int(current["missions_total"]), int(item["missions_total"]))
        normalized[battle_id] = item

    settings = Settings.load()
    store = Store(settings.database_path)
    store.initialize()
    count = store.import_battles(list(normalized.values()))
    store.add_event("discovery.imported", f"Imported {count} visible Step-Up battle cards", "success")
    print(json.dumps({"imported": count, "pending": len(store.pending_battles())}))


if __name__ == "__main__":
    main()
