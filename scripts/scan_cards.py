#!/usr/bin/env python3
"""Read-only inventory scan for stable card IDs used by shipped recipes."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageOps

from build_managed_deck import exact_line, normalized
from discover_step_up import AndroidVision, OcrLine, text_dump
from pbot.card_inventory import (
    CardInventoryBootstrapper,
    CardObservation,
    CardTarget,
)
from pbot.config import Settings
from pbot.managed_deck import ManagedDeckError, active_battle_likely
from pbot.storage import Store


CARD_SEARCH_OVERRIDES = {
    # Pocket accepts the distinctive stem but leaves the full possessive query
    # on an inert confirmation control. Result identity/quantity is still read
    # from the matching Professor Oak tile, never from the broad total.
    "Professor's Research": "Professor",
}


def collection_total(lines: Sequence[OcrLine]) -> int | None:
    candidates = [
        line
        for line in lines
        if re.fullmatch(r"\d{1,5}", line.text.replace(",", "").strip())
        and line.x < 260
        and 570 <= line.y <= 720
        and line.height >= 24
    ]
    if not candidates:
        return None
    return int(max(candidates, key=lambda line: line.confidence).text.replace(",", ""))


def adb_search_text(card_name: str) -> str:
    """Encode spaces for `adb input text` without changing card-name punctuation."""
    query = re.sub(r"\s+", " ", CARD_SEARCH_OVERRIDES.get(card_name, card_name)).strip()
    if not query or not re.fullmatch(r"[A-Za-z0-9' -]+", query):
        raise ManagedDeckError(f"Card name is not safe for ADB search input: {card_name!r}")
    # `adb shell` reconstructs a remote shell command even when subprocess
    # receives an argv list. Escape apostrophes for that remote parse.
    return query.replace("'", r"\'").replace(" ", "%s")


def card_name_lines(lines: Sequence[OcrLine], card_name: str) -> list[OcrLine]:
    target = normalized(card_name)
    candidates = [
        line
        for line in lines
        if target in normalized(line.text)
        and 700 <= line.y <= 2050
        and (
            normalized(line.text) == target
            or (
                len(target.split()) > 1
                and len(normalized(line.text)) <= len(target) + 25
            )
        )
    ]
    # Vision can emit the same title twice with near-identical geometry.
    unique: list[OcrLine] = []
    for candidate in sorted(candidates, key=lambda line: (line.y, line.x)):
        if not any(
            abs(candidate.x - prior.x) < 80 and abs(candidate.y - prior.y) < 80
            for prior in unique
        ):
            unique.append(candidate)
    return unique


def choose_variant_line(
    lines: Sequence[OcrLine], target: CardTarget
) -> tuple[OcrLine | None, str]:
    candidates = card_name_lines(lines, target.name)
    if len(candidates) == 1:
        return candidates[0], "unique visible print"
    if len(candidates) > 1 and target.identity_hint:
        hints = [
            line
            for line in lines
            if normalized(target.identity_hint) in normalized(line.text)
            and 700 <= line.y <= 2050
        ]
        if hints:
            hint = max(hints, key=lambda line: line.confidence)
            return min(
                candidates,
                key=lambda line: abs(
                    (line.x + line.width // 2) - (hint.x + hint.width // 2)
                ),
            ), f"matched identity hint {target.identity_hint}"
    if not candidates and target.identity_hint:
        hints = [
            line
            for line in lines
            if normalized(target.identity_hint) in normalized(line.text)
            and 700 <= line.y <= 2050
        ]
        if len(hints) == 1:
            hint = hints[0]
            # The title itself can be missed (notably Hoopa ex, Ogerpon, and
            # Poké Ball). Anchor a synthetic title row above the unique effect
            # text so the existing per-tile quantity crop remains usable.
            target_tokens = {token for token in normalized(target.name).split() if len(token) >= 5}
            hint_tokens = set(normalized(hint.text).split())
            title_y = hint.y if target_tokens & hint_tokens else hint.y - 200
            return OcrLine(
                target.name,
                hint.confidence,
                hint.x,
                max(700, title_y),
                hint.width,
                hint.height,
            ), f"matched identity hint {target.identity_hint} without a readable title"
    if len(candidates) > 1:
        return None, "Multiple prints share this name and no visible identity hint resolved them"
    return None, "The filtered result did not expose a readable card title"


def quantity_near_candidate(
    lines: Sequence[OcrLine], candidate: OcrLine, maximum: int
) -> int | None:
    """Read a tile's quantity from the already-OCRed full frame when available."""
    center_x = candidate.x + candidate.width // 2
    quantities: list[tuple[OcrLine, int]] = []
    for line in lines:
        text = line.text.replace(",", "").strip()
        if not re.fullmatch(r"\d{1,4}", text):
            continue
        value = int(text)
        if not 0 <= value <= maximum:
            continue
        line_center_x = line.x + line.width // 2
        if abs(line_center_x - center_x) > 140:
            continue
        if not candidate.y + 280 <= line.y <= candidate.y + 460:
            continue
        quantities.append((line, value))
    if not quantities:
        return None
    return max(quantities, key=lambda item: (item[0].confidence, item[0].height))[1]


class AndroidCardInventoryPort:
    def __init__(
        self,
        root: Path,
        serial: str | None,
    ) -> None:
        self.root = root
        self.device = AndroidVision(root, serial)

    def _frame(self, label: str) -> tuple[Path, list[OcrLine]]:
        return self.device.frame(label)

    def _ensure_my_cards(self) -> tuple[Path, list[OcrLine]]:
        for step in range(18):
            if self.device.foreground_package() != "jp.pokemon.pokemontcgp":
                self.device._run(
                    "shell",
                    "monkey",
                    "-p",
                    "jp.pokemon.pokemontcgp",
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                )
                time.sleep(8)
                continue
            path, lines = self._frame(f"card-scan-route-{step + 1}")
            dump = normalized(text_dump(lines))
            if "clear" in dump and exact_line(lines, "OK") and "my cards" not in dump:
                self.device.tap(540, 2200)
                time.sleep(1.5)
                continue
            if "my cards" in dump and ("binders" in dump or "display boards" in dump):
                return path, lines
            if "obtain flair" in dump or "cards eligible for this exchange" in dump:
                raise ManagedDeckError(
                    "Close the Flair exchange/tutorial before the read-only card scan"
                )
            if active_battle_likely(text_dump(lines)):
                raise ManagedDeckError("Refusing card inventory navigation during an active battle")
            if "tap to start" in dump:
                self.device.tap(540, 2050)
                time.sleep(7)
                continue
            if "date has changed" in dump and "title screen" in dump:
                self.device.tap(540, 1540)
                time.sleep(3)
                continue
            if "news" in dump and "availability period" in dump:
                self.device.tap(540, 2150)
                time.sleep(2)
                continue
            # My Decks and all normal hubs retain the Cards bottom-nav target.
            self.device.tap(340, 2260)
            time.sleep(3)
        raise ManagedDeckError("Could not route from the current safe screen to My Cards")

    def _open_filter(self) -> list[OcrLine]:
        deadline = time.monotonic() + 12
        next_tap = 0.0
        last: list[OcrLine] = []
        while time.monotonic() < deadline:
            _path, last = self._frame("card-scan-filter")
            if exact_line(last, "OK") and exact_line(last, "Clear"):
                return last
            dump = normalized(text_dump(last))
            if "my cards" in dump and time.monotonic() >= next_tap:
                # The device is already held awake by AndroidVision. Sending a
                # wake/dismiss-keyguard pair immediately before this small icon
                # occasionally makes Unity drop the following touch.
                self.device._run("shell", "input", "touchscreen", "tap", "955", "660")
                next_tap = time.monotonic() + 2
            time.sleep(0.5)
        raise ManagedDeckError("My Cards did not open its read-only search filters")

    def _search(self, target: CardTarget) -> tuple[Path, list[OcrLine]]:
        lines = self._open_filter()
        clear = exact_line(lines, "Clear")
        if not clear:
            raise ManagedDeckError("Card filter did not expose Clear")
        self.device.tap(clear.x + clear.width // 2, clear.y + clear.height // 2)
        self.device.tap(500, 520)
        self.device._run("shell", "input", "text", adb_search_text(target.name))
        self.device._run("shell", "input", "keyevent", "KEYCODE_ENTER")
        time.sleep(0.6)
        _path, lines = self._frame(f"card-scan-{target.card_id}-filter-ready")
        ok = exact_line(lines, "OK")
        if not ok:
            raise ManagedDeckError(f"Card filter did not expose OK for {target.card_id}")
        for attempt in range(3):
            self.device.tap(ok.x + ok.width // 2, ok.y + ok.height // 2)
            time.sleep(1.5)
            path, lines = self._frame(f"card-scan-{target.card_id}-results-{attempt + 1}")
            dump = normalized(text_dump(lines))
            if "my cards" in dump:
                return path, lines
            ok = exact_line(lines, "OK")
            if not ok or not exact_line(lines, "Clear"):
                break
        raise ManagedDeckError(f"Card search for {target.card_id} did not return to My Cards")

    def _tile_quantity(self, path: Path, line: OcrLine, maximum: int) -> int | None:
        image = Image.open(path).convert("RGB")
        left = max(0, line.x - 30)
        right = min(image.width, line.x + 170)
        top = max(0, line.y + 320)
        bottom = min(image.height, line.y + 440)
        crop_path = path.with_name(path.stem + "-quantity.png")
        crop = ImageOps.autocontrast(ImageOps.grayscale(image.crop((left, top, right, bottom))))
        crop = crop.point(lambda pixel: 0 if pixel > 165 else 255)
        crop.resize((1200, 720)).save(crop_path)
        result = subprocess.run(
            [str(self.device.ocr_binary), str(crop_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(result.stdout)
        quantities = [
            int(str(item["text"]).strip())
            for item in payload.get("observations", [])
            if re.fullmatch(r"\d{1,4}", str(item.get("text", "")).strip())
        ]
        plausible = [quantity for quantity in quantities if 0 <= quantity <= maximum]
        return max(plausible, default=None)

    def _observe(self, target: CardTarget) -> CardObservation:
        path, lines = self._search(target)
        total = collection_total(lines)
        candidate, reason = choose_variant_line(lines, target)
        if total is None:
            if candidate is not None:
                quantity = quantity_near_candidate(lines, candidate, 9999)
                if quantity is None:
                    quantity = self._tile_quantity(path, candidate, 9999)
                if quantity is not None:
                    return CardObservation(
                        target.card_id,
                        target.name,
                        quantity,
                        "verified" if quantity else "missing",
                        str(path),
                        target.identity_hint,
                        f"{reason}; quantity read from the matched tile",
                    )
            return CardObservation(
                target.card_id,
                target.name,
                None,
                "ambiguous",
                str(path),
                target.identity_hint,
                "Could not read the filtered collection total or matched tile quantity",
            )
        if total == 0:
            return CardObservation(
                target.card_id,
                target.name,
                0,
                "missing",
                str(path),
                target.identity_hint,
                "The exact-name filter returned no owned cards",
            )
        if candidate is None:
            return CardObservation(
                target.card_id,
                target.name,
                None,
                "ambiguous",
                str(path),
                target.identity_hint,
                reason,
            )
        variants = card_name_lines(lines, target.name)
        if len(variants) == 1 and target.name not in CARD_SEARCH_OVERRIDES:
            quantity = total
        else:
            quantity = quantity_near_candidate(lines, candidate, total)
            if quantity is None:
                quantity = self._tile_quantity(path, candidate, total)
        if quantity is None:
            return CardObservation(
                target.card_id,
                target.name,
                None,
                "ambiguous",
                str(path),
                target.identity_hint,
                f"{reason}, but its owned quantity was unreadable",
            )
        return CardObservation(
            target.card_id,
            target.name,
            quantity,
            "verified" if quantity else "missing",
            str(path),
            target.identity_hint,
            reason,
        )

    def scan_cards(self, targets: Sequence[CardTarget]) -> Sequence[CardObservation]:
        self._ensure_my_cards()
        observations: list[CardObservation] = []
        for target in targets:
            observation = self._observe(target)
            observations.append(observation)
        return observations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial")
    args = parser.parse_args()
    settings = Settings.load()
    serial = args.serial or settings.adb_serial
    store = Store(settings.database_path)
    store.initialize()
    account = store.get_account_profile()
    if account.get("status") != "ready":
        message = "Complete the owned-deck account scan before recipe card preflight"
        store.fail_card_scan(serial, message)
        print(json.dumps({"status": "needs_attention", "message": message}, indent=2))
        return 2
    scanner = AndroidCardInventoryPort(settings.project_root, serial)
    store.set_state("running", "Scanning recipe card inventory", serial)
    try:
        result = CardInventoryBootstrapper(store, scanner).run(serial)
    except Exception as exc:
        store.fail_card_scan(serial, str(exc))
        store.set_state("needs_attention", f"Card inventory scan needs attention: {exc}", serial)
        store.add_event("account.card_scan_failed", str(exc), "error", {"device_serial": serial})
        print(json.dumps({"status": "needs_attention", "message": str(exc)}, indent=2))
        return 2
    store.set_state(
        "ready",
        f"Recipe inventory ready: {result['profile']['exact_recipe_count']} exact recipes",
        serial,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
