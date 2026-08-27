#!/usr/bin/env python3
"""Read-only bootstrap scan of every numbered deck on the connected account."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from build_managed_deck import AndroidManagedDeckPort, exact_line
from discover_step_up import OcrLine, text_dump
from pbot.account_bootstrap import AccountBootstrapper, AccountDeck
from pbot.config import Settings
from pbot.deck_recipe import PBOT_FIRE
from pbot.managed_deck import ENERGY_HUES, ManagedDeckError, ManagedDeckPlan, visible_energy_types
from pbot.storage import Store


def deck_count(lines: list[OcrLine]) -> int | None:
    match = re.search(r"(\d+)\s*/\s*25", text_dump(lines))
    return int(match.group(1)) if match else None


def visible_slot(lines: list[OcrLine], slot_number: int) -> OcrLine | None:
    def exact_slot(number: int) -> OcrLine | None:
        candidates = [
            line
            for line in lines
            if re.fullmatch(r"0*\d{1,2}", line.text.strip())
            and int(line.text.strip()) == number
            and line.y > 350
            and line.height > 55
        ]
        return max(candidates, key=lambda line: line.confidence, default=None)

    candidate = exact_slot(slot_number)
    if candidate:
        return candidate

    # A faded unusable tile can hide its white number from OCR. Deck rows after
    # slot 1 are even/odd pairs, so the partner supplies safe vertical geometry.
    if slot_number <= 1:
        return None
    partner_number = slot_number - 1 if slot_number % 2 else slot_number + 1
    partner = exact_slot(partner_number)
    if not partner:
        return None
    return OcrLine(
        text=f"{slot_number:02d}",
        confidence=partner.confidence,
        x=600 if slot_number % 2 else 100,
        y=partner.y,
        width=partner.width,
        height=partner.height,
    )


def slot_is_unusable(lines: list[OcrLine], candidate: OcrLine) -> bool:
    target_is_left = candidate.x < 480
    return any(
        re.sub(r"[^a-z]+", " ", line.text.casefold()).strip() == "not usable"
        and (line.x < 480) == target_is_left
        and candidate.y <= line.center_y <= candidate.y + 650
        for line in lines
    )


def detail_deck_name(lines: list[OcrLine]) -> str | None:
    excluded = {"edit", "change", "energy", "accessories", "highlight card", "highlight cards"}
    candidates = [
        line.text.strip()
        for line in lines
        if 120 <= line.y <= 340
        and line.text.strip()
        and re.sub(r"[^a-z0-9]+", " ", line.text.casefold()).strip() not in excluded
        and not re.fullmatch(r"[.·• ]+", line.text)
    ]
    return candidates[0] if candidates else None


class AndroidAccountDeckScanPort:
    def __init__(self, root: Path, serial: str | None) -> None:
        plan = ManagedDeckPlan.from_recipes(
            PBOT_FIRE,
            PBOT_FIRE,
            deck_name="pbotfire",
            slot_number=1,
        )
        self.port = AndroidManagedDeckPort(root, serial, plan)

    def _return_to_list(self, lines: list[OcrLine]) -> tuple[Path, list[OcrLine]]:
        cancel = exact_line(lines, "Cancel")
        if not cancel:
            raise ManagedDeckError("Deck detail did not expose the non-mutating Cancel action")
        self.port.device.tap(cancel.x + cancel.width // 2, cancel.y + cancel.height // 2)
        deadline = time.monotonic() + 15
        last: tuple[Path, list[OcrLine]] | None = None
        while time.monotonic() < deadline:
            last = self.port._frame("account-scan-return-list")
            if deck_count(last[1]) is not None:
                return last
            time.sleep(0.6)
        raise ManagedDeckError(
            "Cancel did not return to My Decks: " + (text_dump(last[1]) if last else "no frame")
        )

    def scan_owned_decks(self) -> list[AccountDeck]:
        _path, lines = self.port._reset_list_top()
        count = deck_count(lines)
        if count is None or not 1 <= count <= 25:
            raise ManagedDeckError("Could not read a valid owned-deck count")

        results: list[AccountDeck] = []
        for slot_number in range(1, count + 1):
            candidate = visible_slot(lines, slot_number)
            for page in range(18):
                if candidate:
                    break
                self.port.device.swipe(530, 1650, 530, 1100, 350)
                _path, lines = self.port._frame(
                    f"account-scan-slot-{slot_number}-page-{page + 1}"
                )
                candidate = visible_slot(lines, slot_number)
            if not candidate:
                raise ManagedDeckError(f"Could not visually locate owned deck slot {slot_number}")
            if slot_is_unusable(lines, candidate):
                continue

            column_x = 250 if candidate.x < 480 else 750
            self.port.device.tap(column_x, min(candidate.y + 300, 2050))
            detail_path, detail_lines = self.port._wait_text(
                "20/20", f"account-scan-slot-{slot_number}-detail", 20
            )
            name = detail_deck_name(detail_lines)
            if not name or not exact_line(detail_lines, "Edit"):
                raise ManagedDeckError(f"Slot {slot_number} did not expose a verified deck detail")
            invalid = ("not usable", "do not own", "don't own", "not enough cards")
            if any(marker in text_dump(detail_lines).casefold() for marker in invalid):
                raise ManagedDeckError(f"Slot {slot_number} is visibly unusable")
            energy_types = visible_energy_types(detail_path, tuple(ENERGY_HUES))
            if not energy_types:
                raise ManagedDeckError(f"Could not identify energy for slot {slot_number} ({name})")
            results.append(
                AccountDeck(
                    display_name=name,
                    slot_number=slot_number,
                    energy_types=energy_types,
                    evidence_path=str(detail_path),
                )
            )
            _path, lines = self._return_to_list(detail_lines)
        return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial")
    args = parser.parse_args()
    settings = Settings.load()
    serial = args.serial or settings.adb_serial
    store = Store(settings.database_path)
    store.initialize()
    scanner = AndroidAccountDeckScanPort(settings.project_root, serial)
    try:
        result = AccountBootstrapper(store, scanner).run(serial)
    except Exception as exc:
        store.fail_account_scan(serial, str(exc))
        store.set_state("needs_attention", f"Account scan needs attention: {exc}", serial)
        store.add_event("account.scan_failed", str(exc), "error", {"device_serial": serial})
        print(json.dumps({"status": "needs_attention", "message": str(exc)}, indent=2))
        return 2
    store.set_state("ready", f"Account ready: {result['profile']['deck_count']} owned decks verified", serial)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
