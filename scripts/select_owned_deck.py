#!/usr/bin/env python3
"""Select an exact owned deck on a guarded Step-Up battle rules screen."""

from __future__ import annotations

import argparse

from pbot.config import Settings
from pbot.executor import classify_screen
from pbot.storage import Store

from discover_step_up import AndroidVision, text_dump
from run_first_pass import FirstPassPilot, deck_name_visible, find_owned_deck, owned_deck_tap
from select_rental_deck import open_frontier_selector


def select_owned(device: AndroidVision, deck_name: str, slot_number: int | None = None) -> None:
    device.tap(270, 2050)
    _, lines = device.frame("owned-selector")
    text = text_dump(lines)
    if classify_screen(text) != "deck_selector":
        raise RuntimeError(f"Owned deck selector is not open; saw:\n{text}")
    match = find_owned_deck(device, deck_name, slot_number)
    if not match:
        raise RuntimeError(f"Owned deck is not available: {deck_name}\n{text}")
    device.tap(*owned_deck_tap(match.x, match.center_y))
    device.tap(800, 2200)
    _, selected_lines = device.frame("owned-selected")
    selected_text = text_dump(selected_lines)
    if classify_screen(selected_text) != "prebattle":
        raise RuntimeError(f"Owned selection did not return to Battle Rules; saw:\n{selected_text}")
    if not deck_name_visible(deck_name, selected_text):
        raise RuntimeError(f"Battle Rules did not confirm owned deck {deck_name}; saw:\n{selected_text}")
    print(f"Selected owned deck: {deck_name}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial")
    parser.add_argument("--difficulty", required=True)
    parser.add_argument("--expansion", required=True)
    parser.add_argument("--deck-name", required=True)
    args = parser.parse_args()

    settings = Settings.load()
    store = Store(settings.database_path)
    store.initialize()
    device = AndroidVision(settings.project_root, args.serial or settings.adb_serial)
    pilot = FirstPassPilot(
        settings.project_root,
        store,
        device,
        args.difficulty,
        args.expansion,
        args.deck_name,
        900,
        5,
    )
    open_frontier_selector(pilot)
    deck = next(
        (
            item
            for item in store.owned_decks()
            if item["display_name"].casefold() == args.deck_name.casefold()
        ),
        None,
    )
    slot_number = int(deck["slot_number"]) if deck and deck.get("slot_number") is not None else None
    select_owned(device, args.deck_name, slot_number)
    store.add_event(
        "deck.owned_selected",
        f"Selected owned deck: {args.deck_name}",
        "success",
        {"difficulty": args.difficulty, "expansion": args.expansion, "deck": args.deck_name},
    )


if __name__ == "__main__":
    main()
