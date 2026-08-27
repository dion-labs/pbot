#!/usr/bin/env python3
"""Select an exact rental deck on a guarded Step-Up battle rules screen."""

from __future__ import annotations

import argparse

from pbot.config import Settings
from pbot.executor import classify_screen, normalize_game_label
from pbot.storage import Store

from discover_step_up import AndroidVision, OcrLine, parse_battle_cards, text_dump
from run_first_pass import FirstPassPilot


def deck_match_core(deck_name: str) -> str:
    normalized = normalize_game_label(deck_name)
    if normalized.startswith("elite deck "):
        # Elite rental titles commonly wrap before the trailing `ex`, e.g.
        # `Elite Deck (Mega Lucario` / `ex)`. Match the distinctive Pokémon
        # portion that remains on the first OCR line.
        return normalized.removeprefix("elite deck ").removesuffix(" ex")
    return normalize_game_label(deck_name.split(" Deck", 1)[0])


def matching_deck_line(lines: list[OcrLine], deck_name: str) -> OcrLine | None:
    core = deck_match_core(deck_name)
    return next((line for line in lines if core in normalize_game_label(line.text)), None)


def open_frontier_selector(pilot: FirstPassPilot) -> None:
    pilot.route_to_target()
    device = pilot.device
    previous: tuple[str, ...] = ()
    stale = 0
    for page in range(16):
        path, lines = device.frame(f"rental-frontier-{page + 1}")
        cards = parse_battle_cards(path, lines, pilot.difficulty, pilot.expansion)
        pending = [card for card in cards if not card.observation.first_win]
        if pending:
            card = pending[0]
            tap_y = card.tap_y if card.tap_y <= 1700 else card.tap_y - 170
            text = ""
            for attempt, (x, y) in enumerate(
                ((750, tap_y), (700, max(750, tap_y - 100)), (850, tap_y)),
                start=1,
            ):
                device.tap(x, y)
                _, text, state = pilot.current_screen(f"rental-frontier-opened-{attempt}")
                if state == "prebattle":
                    device.tap(540, 1750)
                    _, text, state = pilot.current_screen("rental-selector-opened")
                if state == "deck_selector":
                    return
                if state != "battle_list":
                    break
            raise RuntimeError(f"Could not open the deck selector; saw:\n{text}")

        signature = tuple(card.observation.id for card in cards)
        stale = stale + 1 if signature == previous else 0
        previous = signature
        if stale >= 3:
            break
        device.swipe(540, 1800, 540, 1250, 600)
    raise RuntimeError(f"No visible frontier found for {pilot.difficulty} / {pilot.expansion}")


def select_rental(device: AndroidVision, deck_name: str) -> None:
    device.tap(780, 2050)
    directions = (
        ("forward", 540, 1750, 540, 900, 48),
        ("backward", 540, 900, 540, 1750, 64),
    )
    for direction, x1, y1, x2, y2, pages in directions:
        for page in range(pages):
            _, lines = device.frame(f"rental-{direction}-{page + 1}")
            text = text_dump(lines)
            if classify_screen(text) != "deck_selector":
                raise RuntimeError(f"Rental selector closed unexpectedly; saw:\n{text}")
            match = matching_deck_line(lines, deck_name)
            if match:
                device.tap(match.x + match.width // 2, min(1900, match.center_y + 100))
                device.tap(800, 2200)
                _, selected_lines = device.frame("rental-selected")
                selected_text = text_dump(selected_lines)
                if classify_screen(selected_text) != "prebattle":
                    raise RuntimeError(f"Rental selection did not return to Battle Rules; saw:\n{selected_text}")
                if deck_match_core(deck_name) not in normalize_game_label(selected_text):
                    raise RuntimeError(f"Battle Rules did not confirm {deck_name}; saw:\n{selected_text}")
                print(f"Selected rental deck: {deck_name}", flush=True)
                return
            if page and page % 10 == 0:
                print(f"Searching rental decks {direction}: page {page + 1}", flush=True)
            device.swipe(x1, y1, x2, y2, 650)
    raise RuntimeError(f"Rental deck is not available: {deck_name}")


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
    select_rental(device, args.deck_name)
    store.add_event(
        "deck.rental_selected",
        f"Selected rental deck: {args.deck_name}",
        "success",
        {"difficulty": args.difficulty, "expansion": args.expansion, "deck": args.deck_name},
    )


if __name__ == "__main__":
    main()
