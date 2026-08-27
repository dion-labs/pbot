#!/usr/bin/env python3
"""Idempotently verify or construct one guarded pbot-managed deck slot."""

from __future__ import annotations

import argparse
import colorsys
import re
import time
import urllib.request
from pathlib import Path
from typing import Sequence

from PIL import Image

from discover_step_up import AndroidVision, OcrLine, text_dump
from pbot.deck_recipe import builtin_recipe, persist_recipe
from pbot.managed_deck import (
    DeckReadback,
    ImportSaveResult,
    ManagedDeckConstructor,
    ManagedDeckError,
    ManagedDeckPlan,
    RecipeSubstitution,
    active_battle_likely,
    readback_from_observations,
)
from pbot.storage import Store


INVALID_DECK_MARKERS = (
    "not usable",
    "do not own",
    "don't own",
    "not enough cards",
    "cannot use this deck",
    "unable to use this deck",
)


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def exact_line(lines: Sequence[OcrLine], value: str) -> OcrLine | None:
    target = normalized(value)
    candidates = [line for line in lines if normalized(line.text) == target]
    return max(candidates, key=lambda item: item.confidence, default=None)


def readback_from_frame(
    path: Path,
    lines: Sequence[OcrLine],
    expected_name: str,
    expected_energy: Sequence[str],
) -> DeckReadback:
    return readback_from_observations(path, lines, expected_name, expected_energy)


class AndroidManagedDeckPort:
    def __init__(self, root: Path, serial: str | None, plan: ManagedDeckPlan) -> None:
        self.root = root
        self.plan = plan
        self.device = AndroidVision(root, serial)
        self._last_frame: tuple[Path, list[OcrLine]] | None = None

    def _frame(self, label: str) -> tuple[Path, list[OcrLine]]:
        self._last_frame = self.device.frame(label)
        return self._last_frame

    def _tap_text(self, lines: Sequence[OcrLine], value: str) -> bool:
        line = exact_line(lines, value)
        if not line:
            return False
        self.device.tap(line.x + line.width // 2, line.y + line.height // 2)
        return True

    def _wait_text(self, value: str, label: str, timeout: float = 15) -> tuple[Path, list[OcrLine]]:
        deadline = time.monotonic() + timeout
        last: tuple[Path, list[OcrLine]] | None = None
        while time.monotonic() < deadline:
            last = self._frame(label)
            if normalized(value) in normalized(text_dump(last[1])):
                return last
            time.sleep(0.8)
        seen = text_dump(last[1]) if last else "<no frame>"
        raise ManagedDeckError(f"Timed out waiting for {value!r}; saw:\n{seen}")

    @staticmethod
    def _deck_count(lines: Sequence[OcrLine]) -> int | None:
        match = re.search(r"(\d+)\s*/\s*25", text_dump(list(lines)))
        return int(match.group(1)) if match else None

    def _ensure_my_decks(self) -> tuple[Path, list[OcrLine]]:
        path, lines = self._frame("managed-route-check")
        dump = normalized(text_dump(lines))
        if "share with 2d pattern code" in dump:
            self.device.dismiss_touch_protection()
            close = exact_line(lines, "X")
            if close:
                self.device.tap(close.x + close.width // 2, close.y + close.height // 2)
            else:
                self.device.tap(540, 2140)
            path, lines = self._frame("managed-close-share-code")
            dump = normalized(text_dump(lines))
        if "my decks" in dump or re.search(r"\b\d+\s+25\b", dump):
            return path, lines
        if active_battle_likely(text_dump(lines)):
            raise ManagedDeckError("Refusing deck navigation while an active battle is visible")
        if "20 20" in dump and exact_line(lines, "Edit"):
            cancel = exact_line(lines, "Cancel")
            if cancel:
                self.device.tap(cancel.x + cancel.width // 2, cancel.y + cancel.height // 2)
            else:
                self.device.press_back()
            time.sleep(2)
            path, lines = self._frame("managed-return-check")
            dump = normalized(text_dump(lines))
            if "my decks" in dump or re.search(r"\b\d+\s+25\b", dump):
                return path, lines
            if "20 20" in dump and exact_line(lines, "Edit"):
                # Unity can restore account/deck management as its root
                # activity. Back has no history in that state. Since no battle
                # lifecycle is visible, a clean relaunch is the safe reset.
                self.device._run("shell", "am", "force-stop", "jp.pokemon.pokemontcgp")
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

        for step in range(16):
            path, lines = self._frame(f"managed-route-decks-{step + 1}")
            dump = normalized(text_dump(lines))
            if "my decks" in dump or re.search(r"\b\d+\s+25\b", dump):
                return path, lines
            if "my cards" in dump:
                if not self._tap_text(lines, "Decks"):
                    raise ManagedDeckError("Cards screen did not expose the Decks tab")
                return self._wait_text("My Decks", "managed-open-decks", 20)
            if active_battle_likely(text_dump(lines)):
                raise ManagedDeckError("Refusing deck navigation while an active battle is visible")
            if "tap to start" in dump:
                self.device.tap(540, 2050)
                time.sleep(5)
                continue
            if "date has changed" in dump and "title screen" in dump:
                self.device.tap(540, 1540)
                time.sleep(3)
                continue
            if "news" in dump and "availability period" in dump:
                self.device.tap(540, 2150)
                time.sleep(2)
                continue
            # All supported non-battle game hubs share the Cards bottom-nav
            # target. The next observation must prove My Cards before any
            # account mutation is allowed.
            self.device.tap(340, 2260)
            time.sleep(2)
        raise ManagedDeckError("Could not route from the current safe game screen to My Decks")

    def _reset_list_top(self) -> tuple[Path, list[OcrLine]]:
        latest = self._ensure_my_decks()
        for _ in range(6):
            self.device.swipe(530, 620, 530, 1950, 350)
        return self._frame("managed-decks-top")

    def _open_slot(self, slot_number: int, expected_name: str) -> DeckReadback | None:
        path, lines = self._reset_list_top()
        count = self._deck_count(lines)
        if count is not None and slot_number > count:
            return None

        prior_signature = ""
        for page in range(12):
            path, lines = self._frame(f"managed-slot-{slot_number}-page-{page + 1}")
            name_line = exact_line(lines, expected_name)
            slot_lines = [
                line
                for line in lines
                if line.text.strip() == str(slot_number) and line.y > 350 and line.height > 65
            ]
            candidate = slot_lines[0] if slot_lines else None
            if name_line and candidate and abs(name_line.x - candidate.x) < 360:
                self.device.tap(name_line.x + name_line.width // 2, name_line.y + name_line.height // 2)
                detail_path, detail_lines = self._wait_text("20/20", "managed-slot-detail")
                return readback_from_frame(
                    detail_path,
                    detail_lines,
                    expected_name,
                    self.plan.adapted_recipe.energy_types,
                )
            if candidate:
                column_x = 250 if candidate.x < 480 else 750
                self.device.tap(column_x, min(candidate.y + 300, 2050))
                detail_path, detail_lines = self._wait_text("20/20", "managed-occupied-slot-detail")
                return readback_from_frame(
                    detail_path,
                    detail_lines,
                    expected_name,
                    self.plan.adapted_recipe.energy_types,
                )

            signature = "|".join(line.text for line in lines if line.y > 350)
            if signature == prior_signature:
                break
            prior_signature = signature
            self.device.swipe(530, 1900, 530, 500, 450)
        if count is not None and slot_number <= count:
            raise ManagedDeckError(f"Could not visually locate occupied deck slot {slot_number}")
        return None

    def inspect_slot(self, slot_number: int, expected_name: str) -> DeckReadback | None:
        return self._open_slot(slot_number, expected_name)

    def discover_managed_slot(self, expected_name: str) -> int:
        """Reuse an exactly named slot, otherwise return only the next free slot."""
        _path, lines = self._reset_list_top()
        count = self._deck_count(lines)
        if count is None:
            raise ManagedDeckError("Could not read the My Decks slot count")

        prior_signature = ""
        for page in range(12):
            _path, lines = self._frame(f"managed-discover-slot-page-{page + 1}")
            name_line = exact_line(lines, expected_name)
            if name_line:
                same_column = [
                    line
                    for line in lines
                    if re.fullmatch(r"\d{1,2}", line.text.strip())
                    and line.y < name_line.y
                    and name_line.y - line.y < 750
                    and abs(name_line.x - line.x) < 360
                    and line.height > 65
                ]
                if same_column:
                    slot = max(same_column, key=lambda item: item.y)
                    return int(slot.text.strip())

            signature = "|".join(line.text for line in lines if line.y > 350)
            if signature == prior_signature:
                break
            prior_signature = signature
            self.device.swipe(530, 1900, 530, 500, 450)
        if count >= 25:
            raise ManagedDeckError("All 25 deck slots are occupied and the managed deck was not found")
        return count + 1

    def import_qr(self, plan: ManagedDeckPlan) -> str | None:
        path, lines = self._reset_list_top()
        count = self._deck_count(lines)
        if count is None:
            raise ManagedDeckError("Could not read the My Decks slot count")
        if plan.slot_number != count + 1:
            raise ManagedDeckError(
                f"Build New would create slot {count + 1}, not managed slot {plan.slot_number}"
            )
        if plan.qr_image is None:
            raise ManagedDeckError("No QR image was provided")

        remote_name = f"pbot-{plan.source_recipe.id}.png"
        remote_path = f"/sdcard/Download/{remote_name}"
        self.device._run("push", str(plan.qr_image), remote_path)
        self.device._run(
            "shell",
            "am",
            "broadcast",
            "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d",
            f"file://{remote_path}",
        )
        if not self._tap_text(lines, "Build New"):
            raise ManagedDeckError("My Decks did not expose Build New")
        _, lines = self._wait_text("Scan Code", "managed-build-menu")
        if not self._tap_text(lines, "Scan Code"):
            raise ManagedDeckError("Build menu did not expose Scan Code")
        _, lines = self._wait_text("Scan Saved Image", "managed-qr-scanner", 20)
        if not self._tap_text(lines, "Scan Saved Image"):
            raise ManagedDeckError("QR scanner did not expose Scan Saved Image")
        time.sleep(2)
        _, lines = self._frame("managed-photo-picker")
        download = exact_line(lines, "Download")
        if download:
            self.device.tap(download.x + download.width // 2, download.y + download.height // 2)
            time.sleep(1)
        # The just-scanned media item is first in Android's Download collection.
        self.device.tap(180, 520)
        imported_path, imported_lines = self._wait_text("20/20", "managed-imported-deck", 25)
        if not exact_line(imported_lines, "Edit"):
            raise ManagedDeckError("QR import did not reach a 20-card deck detail screen")
        return str(imported_path)

    def rename_draft(self, deck_name: str) -> None:
        path, lines = self._frame("managed-before-rename")
        if "20/20" not in text_dump(lines).replace(" ", ""):
            raise ManagedDeckError(f"Refusing rename outside a 20-card deck detail screen: {path}")
        self.device.tap(780, 215)
        time.sleep(1)
        self.device.tap(470, 560)
        self.device._run("shell", "input", "keyevent", "KEYCODE_MOVE_END")
        for _ in range(30):
            self.device._run("shell", "input", "keyevent", "KEYCODE_DEL")
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "", deck_name)
        if safe_name != deck_name:
            raise ManagedDeckError("Managed deck names must use letters, numbers, _ or -")
        self.device._run("shell", "input", "text", safe_name)
        self.device._run("shell", "input", "keyevent", "KEYCODE_ENTER")
        time.sleep(0.8)
        _, lines = self._frame("managed-name-modal")
        ok_lines = [line for line in lines if normalized(line.text) == "ok"]
        if ok_lines:
            ok = max(ok_lines, key=lambda item: item.y)
            self.device.tap(ok.x + ok.width // 2, ok.y + ok.height // 2)
        else:
            self.device.tap(540, 2055)
        self._wait_text(deck_name, "managed-renamed", 12)

    def attempt_save(self) -> ImportSaveResult:
        _, lines = self._frame("managed-before-save")
        save = exact_line(lines, "Save")
        if not save:
            raise ManagedDeckError("Deck detail screen did not expose Save")
        self.device.tap(save.x + save.width // 2, save.y + save.height // 2)
        time.sleep(2)
        _, lines = self._frame("managed-after-save")
        dump = normalized(text_dump(lines))
        if any(normalized(marker) in dump for marker in INVALID_DECK_MARKERS):
            ok = exact_line(lines, "OK")
            if ok:
                self.device.tap(ok.x + ok.width // 2, ok.y + ok.height // 2)
            return ImportSaveResult.OWNERSHIP_FAILURE
        if "my decks" in dump:
            return ImportSaveResult.SAVED
        # Known invalid QR imports remain on the draft detail screen after the
        # validation modal closes; a valid save returns to My Decks.
        if "20 20" in dump and exact_line(lines, "Edit"):
            return ImportSaveResult.OWNERSHIP_FAILURE
        raise ManagedDeckError(f"Could not classify the post-save screen:\n{text_dump(lines)}")

    @staticmethod
    def _card_tile_saturation(path: Path, line: OcrLine) -> float:
        image = Image.open(path).convert("RGB")
        center_x = line.x + line.width // 2
        left = max(0, center_x - 145)
        right = min(image.width, center_x + 145)
        top = max(0, line.y - 120)
        bottom = min(image.height, line.y + 260)
        values = []
        for red, green, blue in image.crop((left, top, right, bottom)).get_flattened_data():
            _hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
            if value > 0.15:
                values.append(saturation)
        return sum(values) / len(values) if values else 1.0

    def _type_search(self, value: str) -> None:
        self.device.tap(960, 960)
        time.sleep(1)
        self.device.tap(500, 520)
        self.device._run("shell", "input", "text", value.replace(" ", "%s"))
        self.device._run("shell", "input", "keyevent", "KEYCODE_ENTER")
        time.sleep(0.8)
        _, lines = self._frame("managed-search-filter")
        ok_lines = [line for line in lines if normalized(line.text) == "ok"]
        if ok_lines:
            ok = max(ok_lines, key=lambda item: item.y)
            self.device.tap(ok.x + ok.width // 2, ok.y + ok.height // 2)
        else:
            self.device.tap(540, 2055)
        time.sleep(1.5)

    def apply_substitutions(self, substitutions: Sequence[RecipeSubstitution]) -> str | None:
        _, lines = self._frame("managed-before-substitution")
        edit = exact_line(lines, "Edit")
        if not edit:
            raise ManagedDeckError("Draft detail did not expose Edit for substitution")
        self.device.tap(edit.x + edit.width // 2, edit.y + edit.height // 2)
        time.sleep(2)

        for index, substitution in enumerate(substitutions):
            if substitution.quantity != 1:
                raise ManagedDeckError("Android substitution currently requires one declared copy per action")
            candidates: list[tuple[float, OcrLine, Path]] = []
            for page in range(8):
                path, lines = self._frame(f"managed-find-missing-{index + 1}-{page + 1}")
                for line in lines:
                    if normalized(substitution.missing_card_name) in normalized(line.text):
                        candidates.append((self._card_tile_saturation(path, line), line, path))
                if candidates:
                    break
                self.device.swipe(850, 500, 220, 500, 450)
            if not candidates:
                raise ManagedDeckError(
                    f"Could not locate declared missing card {substitution.missing_card_name!r}"
                )
            _saturation, missing_line, _path = min(candidates, key=lambda item: item[0])
            self.device.tap(
                missing_line.x + missing_line.width // 2,
                missing_line.y + missing_line.height // 2,
            )
            _, lines = self._wait_text("Remove", f"managed-remove-{index + 1}")
            if not self._tap_text(lines, "Remove"):
                raise ManagedDeckError("Missing-card detail did not expose Remove")
            self._type_search(substitution.replacement_card_name)
            _, lines = self._frame(f"managed-replacement-{index + 1}")
            replacement = next(
                (
                    line
                    for line in lines
                    if normalized(substitution.replacement_card_name) in normalized(line.text)
                ),
                None,
            )
            if replacement:
                self.device.tap(
                    replacement.x + replacement.width // 2,
                    replacement.y + replacement.height // 2 + 180,
                )
            else:
                self.device.tap(200, 1300)
            time.sleep(1.2)

        path, lines = self._frame("managed-substituted-20-check")
        if "20/20" not in text_dump(lines).replace(" ", ""):
            raise ManagedDeckError("Declared substitutions did not restore the visible deck to 20/20")
        ok_lines = [line for line in lines if normalized(line.text) == "ok"]
        if not ok_lines:
            raise ManagedDeckError("Deck builder did not expose its final OK control")
        ok = max(ok_lines, key=lambda item: item.y)
        self.device.tap(ok.x + ok.width // 2, ok.y + ok.height // 2)
        self._wait_text("20/20", "managed-adapted-detail")
        return str(path)

    def read_back(self, slot_number: int, expected_name: str) -> DeckReadback:
        readback = self._open_slot(slot_number, expected_name)
        if readback is None:
            raise ManagedDeckError(f"Saved deck slot {slot_number} disappeared during read-back")
        return readback


def cached_qr(root: Path, source_recipe_id: str, source_url: str | None) -> Path | None:
    shipped = root / "resources" / "deck-qr" / f"{source_recipe_id}.png"
    if shipped.is_file():
        return shipped
    known = root / "var" / "deck-builds" / "20260823-pbotwater" / "source-qr.png"
    if source_recipe_id == "mega-sharpedo-milotic-tournament" and known.is_file():
        return known
    destination = root / "var" / "deck-qr" / f"{source_recipe_id}.png"
    if destination.is_file():
        return destination
    if not source_url:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(source_url, headers={"User-Agent": "pbot/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read(5_000_001)
    if len(payload) > 5_000_000 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ManagedDeckError("Deck QR download was not a bounded PNG image")
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.replace(destination)
    return destination


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--serial")
    result.add_argument("--database", type=Path)
    result.add_argument("--source-recipe-id", default="mega-sharpedo-milotic-tournament")
    result.add_argument("--adapted-recipe-id", default="pbotwater-articuno")
    result.add_argument("--deck-name", default="pbotwater")
    result.add_argument("--slot", type=int, default=21)
    result.add_argument("--qr-image", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    root = Path(__file__).resolve().parents[1]
    store = Store(args.database or root / "var" / "pbot.sqlite3")
    store.initialize()
    source = builtin_recipe(args.source_recipe_id)
    adapted = builtin_recipe(args.adapted_recipe_id)
    persist_recipe(store, source)
    persist_recipe(store, adapted)
    qr_image = args.qr_image or cached_qr(root, source.id, source.qr_image_url)
    plan = ManagedDeckPlan.from_recipes(
        source,
        adapted,
        deck_name=args.deck_name,
        slot_number=args.slot,
        qr_image=qr_image,
    )
    port = AndroidManagedDeckPort(root, args.serial, plan)
    try:
        outcome = ManagedDeckConstructor(port, store).run(plan)
    except ManagedDeckError as exc:
        print(f"needs_attention: {exc}")
        return 2
    print(
        f"verified {outcome.readback.deck_name} in slot {plan.slot_number}; "
        f"recipe={outcome.effective_recipe_id}; already_present={outcome.already_present}; "
        f"evidence={outcome.readback.evidence_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
