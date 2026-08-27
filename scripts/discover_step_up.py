#!/usr/bin/env python3
"""Visually enumerate Pokémon TCG Pocket Step-Up battles from an Android device."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageStat

from pbot.device import DeviceError
from pbot.device_awake import enable_awake_policy, snapshot_path, wake_and_dismiss
from pbot.executor import classify_screen, foreground_package_from_dumpsys, touch_protection_likely


BASE_WIDTH = 1080
BASE_HEIGHT = 2340
FRACTION = re.compile(r"(\d+)\s*/\s*(\d+)")


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


@dataclass
class BattleObservation:
    id: str
    expansion: str
    difficulty: str
    name: str
    first_win: bool
    missions_complete: int
    missions_total: int
    evidence_path: str


@dataclass(frozen=True)
class BattleCard:
    observation: BattleObservation
    tap_y: int


@dataclass(frozen=True)
class ExpansionCandidate:
    signature: str
    title_hint: str
    tap_y: int
    wins_text: str | None
    missions_text: str


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" #•º*-_")


def parse_fraction(value: str) -> tuple[int, int] | None:
    match = FRACTION.search(value.replace("I", "1").replace("l", "1"))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


class AndroidVision:
    def __init__(self, root: Path, serial: str | None = None) -> None:
        self.root = root
        self.run_dir = root / "var" / "discovery" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.ocr_binary = root / "var" / "vision_ocr"
        adb = shutil.which("adb") or str(Path.home() / "Library/Android/sdk/platform-tools/adb")
        self.adb = [adb]
        if serial:
            self.adb.extend(["-s", serial])
        self.serial = serial
        self.sequence = 0
        self.width = BASE_WIDTH
        self.height = BASE_HEIGHT
        self._prepare()

    def _run(self, *args: str, binary: bool = False) -> subprocess.CompletedProcess:
        command = [*self.adb, *args]
        for attempt in range(3):
            try:
                return subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=not binary,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                if attempt < 2:
                    time.sleep(2)
                    continue
                raise DeviceError("ADB timed out while controlling the Android device") from exc
            except subprocess.CalledProcessError as exc:
                detail = exc.stderr.decode(errors="replace") if binary and exc.stderr else exc.stderr
                message = str(detail or "ADB command failed").strip()
                unavailable = any(
                    marker in message.casefold()
                    for marker in (
                        "device not found",
                        "no devices/emulators found",
                        "device offline",
                        "device unauthorized",
                        "closed",
                    )
                )
                if unavailable and attempt < 2:
                    time.sleep(2)
                    continue
                raise DeviceError(message) from exc
        raise DeviceError("ADB command failed")

    def _prepare(self) -> None:
        enable_awake_policy(
            self._run,
            snapshot_path(self.root / "var", self.serial),
            self.serial,
        )
        if not self.ocr_binary.exists():
            subprocess.run(
                ["swiftc", str(self.root / "scripts/vision_ocr.swift"), "-o", str(self.ocr_binary)],
                check=True,
                timeout=60,
            )
        size = self._run("shell", "wm", "size").stdout
        match = re.search(r"Physical size:\s*(\d+)x(\d+)", size)
        if match:
            self.width, self.height = map(int, match.groups())
        self.dismiss_keyguard()

    def dismiss_keyguard(self) -> None:
        wake_and_dismiss(self._run)

    def foreground_package(self) -> str | None:
        return foreground_package_from_dumpsys(self._run("shell", "dumpsys", "window").stdout)

    def dismiss_touch_protection(self) -> None:
        """Dismiss Samsung Game Booster's drag-to-unlock overlay."""
        self.dismiss_keyguard()
        # Game Booster accepts a drag from the centered lock icon in any
        # direction. Try the common center positions used across One UI sizes.
        self._run("shell", "input", "touchscreen", "tap", str(self.width // 2), str(self.height // 2))
        time.sleep(0.3)
        for start_y in (self.height // 2, round(self.height * 0.68), round(self.height * 0.82)):
            self._run(
                "shell",
                "input",
                "swipe",
                str(self.width // 2),
                str(start_y),
                str(self.width // 2),
                str(max(200, start_y - round(self.height * 0.3))),
                "650",
            )
            time.sleep(0.5)

    def tap(self, x: int, y: int) -> None:
        self.dismiss_keyguard()
        sx = round(x * self.width / BASE_WIDTH)
        sy = round(y * self.height / BASE_HEIGHT)
        self._run("shell", "input", "touchscreen", "tap", str(sx), str(sy))
        time.sleep(1.0)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> None:
        self.dismiss_keyguard()
        coords = [
            round(x1 * self.width / BASE_WIDTH),
            round(y1 * self.height / BASE_HEIGHT),
            round(x2 * self.width / BASE_WIDTH),
            round(y2 * self.height / BASE_HEIGHT),
        ]
        self._run("shell", "input", "swipe", *(str(value) for value in coords), str(duration_ms))
        time.sleep(1.2)

    def press_back(self) -> None:
        self.dismiss_keyguard()
        self._run("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1.5)

    def frame(self, label: str) -> tuple[Path, list[OcrLine]]:
        self.dismiss_keyguard()
        self.sequence += 1
        path = self.run_dir / f"{self.sequence:04d}-{slug(label)}.png"
        for attempt in range(2):
            path.write_bytes(self._run("exec-out", "screencap", "-p", binary=True).stdout)
            result = subprocess.run(
                [str(self.ocr_binary), str(path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            payload = json.loads(result.stdout)
            lines = [OcrLine(**line) for line in payload["observations"]]
            luminance = sum(
                ImageStat.Stat(Image.open(path).convert("RGB").resize((64, 64))).mean
            ) / 3
            if attempt == 0 and (
                "drag lock icon" in text_dump(lines).casefold()
                or touch_protection_likely(luminance, text_dump(lines))
            ):
                self.dismiss_touch_protection()
                time.sleep(0.8)
                continue
            return path, lines
        raise RuntimeError("Unable to dismiss the Android keyguard")


def text_dump(lines: list[OcrLine]) -> str:
    return "\n".join(line.text for line in lines)


def wait_for(device: AndroidVision, needle: str, label: str, timeout: float = 12) -> tuple[Path, list[OcrLine]]:
    deadline = time.monotonic() + timeout
    last: tuple[Path, list[OcrLine]] | None = None
    while time.monotonic() < deadline:
        last = device.frame(label)
        if needle.casefold() in text_dump(last[1]).casefold():
            return last
        time.sleep(0.7)
    found = text_dump(last[1]) if last else "<no frame>"
    raise RuntimeError(f"Timed out waiting for {needle!r}; saw:\n{found}")


def reward_color_fraction(image: Image.Image, mission_y: int) -> float:
    crop = image.convert("RGB").crop((700, max(0, mission_y - 120), 1010, min(image.height, mission_y + 70)))
    pixels = list(crop.get_flattened_data())
    if not pixels:
        return 0
    saturated = 0
    for pixel in pixels:
        high = max(pixel)
        saturation = (high - min(pixel)) / max(high, 1)
        saturated += saturation > 0.25
    return saturated / len(pixels)


def infer_expansion(name: str) -> str:
    matches = re.findall(r"\(([^()]*)\)", name)
    return clean_text(matches[-1]) if matches else "Unknown expansion"


def pretty_expansion(title_hint: str) -> str:
    special = {
        "DELUXE PACK EX": "Deluxe Pack: ex",
        "EVERYDA WONDERS": "Everyday Wonders",
        "SPACE TIME SMACKDOWN": "Space-Time Smackdown",
        "WISDOM OF SEA AND SKY": "Wisdom of Sea and Sky",
        "RULER OF THE SKIES": "Ruler of the Skies",
    }
    normalized = re.sub(r"[^A-Z0-9]+", " ", clean_text(title_hint).upper()).strip()
    return special.get(normalized, normalized.title())


def canonical_battle_name(raw_name: str, expansion: str) -> str:
    prefix = raw_name.split("Deck", 1)[0] + "Deck"
    prefix = re.sub(r"^[^A-Za-z0-9]+(?:V\s+)?", "", prefix)
    prefix = re.sub(r"\s+[\^V]+\s*$", "", prefix)
    return f"{clean_text(prefix)} ({expansion})"


def parse_battle_cards(
    path: Path,
    lines: list[OcrLine],
    difficulty: str,
    expansion_hint: str | None = None,
) -> list[BattleCard]:
    image = Image.open(path)
    cards: list[BattleCard] = []
    fractions: list[tuple[OcrLine, tuple[int, int]]] = []
    for line in lines:
        value = parse_fraction(line.text)
        if value and 430 <= line.x <= 690 and 700 <= line.center_y <= 2010 and 0 <= value[0] <= value[1] <= 5:
            fractions.append((line, value))

    for line, (complete, total) in fractions:
        name_parts = [
            candidate
            for candidate in lines
            if candidate.x >= 400
            and line.y - 235 <= candidate.y <= line.y - 25
            and candidate.height >= 25
            and not parse_fraction(candidate.text)
        ]
        name = clean_text(" ".join(part.text for part in sorted(name_parts, key=lambda item: (item.y, item.x))))
        if "deck" not in name.casefold():
            continue
        expansion = pretty_expansion(expansion_hint) if expansion_hint else infer_expansion(name)
        name = canonical_battle_name(name, expansion)
        first_win = reward_color_fraction(image, line.center_y) < 0.02
        cards.append(
            BattleCard(
                observation=BattleObservation(
                    id=f"{slug(expansion)}:{slug(difficulty)}:{slug(name)}",
                    expansion=expansion,
                    difficulty=difficulty,
                    name=name,
                    first_win=first_win,
                    missions_complete=complete,
                    missions_total=total,
                    evidence_path=str(path),
                ),
                tap_y=line.center_y,
            )
        )
    return cards


def parse_battles(
    path: Path,
    lines: list[OcrLine],
    difficulty: str,
    expansion_hint: str | None = None,
) -> list[BattleObservation]:
    return [card.observation for card in parse_battle_cards(path, lines, difficulty, expansion_hint)]


def parse_expansion_candidates(lines: list[OcrLine], tab: str) -> list[ExpansionCandidate]:
    right_totals: list[tuple[OcrLine, tuple[int, int]]] = []
    for line in lines:
        value = parse_fraction(line.text)
        if value and line.x >= 700 and 400 <= line.center_y <= 1910 and value[1] > 5:
            right_totals.append((line, value))

    candidates: list[ExpansionCandidate] = []
    for right, right_value in right_totals:
        title_parts = [
            line
            for line in lines
            if 80 <= line.x <= 450
            and right.y - 285 <= line.y <= right.y - 105
            and line.height >= 24
            and "select expansion" not in line.text.casefold()
        ]
        title = clean_text(" ".join(line.text for line in sorted(title_parts, key=lambda item: (item.y, item.x))))
        if not title:
            continue
        left = next(
            (
                line.text
                for line in lines
                if 430 <= line.x < 700 and abs(line.center_y - right.center_y) < 45
            ),
            None,
        )
        signature = f"{tab}:{right_value[1]}"
        candidates.append(
            ExpansionCandidate(
                signature=signature,
                title_hint=title,
                tap_y=max(420, right.center_y - 125),
                wins_text=left,
                missions_text=right.text,
            )
        )
    return sorted(candidates, key=lambda candidate: candidate.tap_y)


class DiscoveryRun:
    def __init__(self, device: AndroidVision, output: Path) -> None:
        self.device = device
        self.output = output
        self.battles: dict[str, BattleObservation] = {}
        self.expansions: list[dict[str, str | int | None]] = []
        if output.exists():
            payload = json.loads(output.read_text())
            self.battles = {
                item["id"]: BattleObservation(**item)
                for item in payload.get("battles", [])
                if item.get("expansion") != "Unknown expansion"
                and str(item.get("name", "")).count("(") == str(item.get("name", "")).count(")")
            }
            self.expansions = payload.get("expansions", [])

    def checkpoint(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "battles": [asdict(item) for item in sorted(self.battles.values(), key=lambda item: item.id)],
            "expansions": self.expansions,
        }
        self.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def scan_current_expansion(self, difficulty: str, signature: str, title_hint: str) -> int:
        stale = 0
        previous_ids: set[str] = set()
        found: dict[str, BattleObservation] = {}
        for page in range(20):
            path, lines = self.device.frame(f"{difficulty}-{signature}-page-{page + 1}")
            page_battles = parse_battles(path, lines, difficulty, title_hint)
            for battle in page_battles:
                found[battle.id] = battle
                self.battles[battle.id] = battle
            current_ids = set(found)
            stale = stale + 1 if current_ids == previous_ids else 0
            previous_ids = current_ids
            if stale >= 3:
                break
            self.device.swipe(540, 1800, 540, 1300, 600)
        self.expansions.append(
            {
                "difficulty": difficulty,
                "signature": signature,
                "title_hint": title_hint,
                "battles_found": len(found),
            }
        )
        self.checkpoint()
        return len(found)

    def open_expansions(self) -> None:
        last_text = ""
        for attempt, (x, y) in enumerate(((900, 700), (880, 690), (920, 720)), start=1):
            self.device.tap(x, y)
            _, lines = self.device.frame(f"expansion-selector-{attempt}")
            last_text = text_dump(lines)
            if "select expansion" in last_text.casefold():
                return
        raise RuntimeError(f"Could not open the expansion selector; saw:\n{last_text}")

    def scan_tab(self, difficulty: str, tab: str) -> None:
        self.device.tap(650 if tab == "A" else 250, 2050)
        processed = {
            str(item["signature"])
            for item in self.expansions
            if item.get("difficulty") == difficulty and str(item.get("signature", "")).startswith(f"{tab}:")
        }
        stale_scrolls = 0
        while stale_scrolls < 3:
            _, lines = self.device.frame(f"{difficulty}-{tab}-selector")
            candidates = parse_expansion_candidates(lines, tab)
            candidate = next((item for item in candidates if item.signature not in processed), None)
            if candidate:
                processed.add(candidate.signature)
                print(f"[{difficulty}/{tab}] {candidate.title_hint} ({candidate.signature})", flush=True)
                self.device.tap(540, candidate.tap_y)
                wait_for(self.device, "Expansions", f"{difficulty}-{candidate.signature}-opened")
                count = self.scan_current_expansion(difficulty, candidate.signature, candidate.title_hint)
                print(f"  discovered {count} battle cards", flush=True)
                self.open_expansions()
                continue
            before_layout = [(item.signature, item.tap_y // 25) for item in candidates]
            self.device.swipe(540, 1750, 540, 1450, 700)
            _, after_lines = self.device.frame(f"{difficulty}-{tab}-selector-after-scroll")
            after_candidates = parse_expansion_candidates(after_lines, tab)
            after_layout = [(item.signature, item.tap_y // 25) for item in after_candidates]
            stale_scrolls = stale_scrolls + 1 if after_layout == before_layout else 0

    def scan_current_tier(self, difficulty: str) -> None:
        self.open_expansions()
        self.scan_tab(difficulty, "A")
        self.device.tap(250, 2050)
        self.scan_tab(difficulty, "B")
        self.device.tap(540, 2220)
        self.checkpoint()

    def ensure_step_up_overview(self) -> None:
        # Pocket's current bottom bar centers Battle/Solo on the fourth icon.
        # Its clickable region now begins lower than the old y=2250 target; a
        # live coordinate probe verified that (742, 2320) opens Battle/Solo.
        solo_tab = (742, 2320)
        orphaned_list_backs = 0
        for step in range(24):
            _, lines = self.device.frame(f"navigate-step-up-{step + 1}")
            text = text_dump(lines).casefold()
            if "date has changed" in text and "returning to the title screen" in text:
                self.device.tap(540, 1540)
                time.sleep(3)
            elif "news" in text and "availability period" in text:
                self.device.tap(540, 2150)
            elif "select expansion" in text:
                self.device.tap(540, 2220)
            elif classify_screen(text) == "prebattle":
                # A stopped/restarted worker can retain the Battle Rules page.
                # No battle has started, so Back safely returns to its list.
                self.device.press_back()
            elif "expansions" in text:
                orphaned_list_backs += 1
                if orphaned_list_backs >= 3:
                    # Android can restore a battle-list activity as the app's
                    # root after a process restart. Back then exits to the
                    # launcher, and a normal relaunch restores the same orphan.
                    # No battle lifecycle is active here, so a clean relaunch
                    # is safe and rebuilds navigation from the title screen.
                    subprocess.run(
                        [*self.device.adb, "shell", "am", "force-stop", "jp.pokemon.pokemontcgp"],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                    subprocess.run(
                        [*self.device.adb, "shell", "monkey", "-p", "jp.pokemon.pokemontcgp", "-c", "android.intent.category.LAUNCHER", "1"],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                    orphaned_list_backs = 0
                    time.sleep(8)
                else:
                    self.device.press_back()
            elif "beginner" in text and "intermediate" in text and "step-up battle" in text:
                return
            elif "random battle" in text and "step-up battle" in text:
                self.device.tap(800, 1850)
            elif "versus" in text and "solo" in text:
                self.device.tap(800, 1860)
            elif "wonder pick" in text and "shop" in text:
                self.device.tap(*solo_tab)
            elif "offering rates" in text and "select other booster packs" in text:
                self.device.tap(*solo_tab)
            elif "social hub" in text and ("community showcases" in text or "friends" in text):
                self.device.tap(*solo_tab)
            elif "my cards" in text and ("binders" in text or "display boards" in text or "decks" in text):
                # Card/deck capability scans intentionally finish on this
                # account screen. The fourth bottom tab is the normal Solo
                # route and is safe from every My Cards subview.
                self.device.tap(*solo_tab)
            elif "tap to start" in text:
                self.device.tap(540, 2050)
                time.sleep(5)
            else:
                # Relaunching is recoverable and returns to the title or the last game screen.
                subprocess.run(
                    [*self.device.adb, "shell", "monkey", "-p", "jp.pokemon.pokemontcgp", "-c", "android.intent.category.LAUNCHER", "1"],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
                time.sleep(5)
        raise RuntimeError("Could not navigate to the Step-Up Battle overview")

    def select_tier(self, difficulty: str) -> None:
        self.ensure_step_up_overview()
        for _ in range(3):
            self.device.swipe(540, 900, 540, 1750, 500)
        for page in range(8):
            _, lines = self.device.frame(f"select-{difficulty}-{page + 1}")
            match = next(
                (
                    line
                    for line in lines
                    if difficulty.casefold() in line.text.casefold() and 350 <= line.center_y <= 2050
                ),
                None,
            )
            if match:
                self.device.tap(match.x + match.width // 2, match.center_y)
                wait_for(self.device, "Expansions", f"{difficulty}-tier-opened")
                return
            self.device.swipe(540, 1850, 540, 950, 500)
        raise RuntimeError(f"Could not find the {difficulty} tier")

    def scan_all_tiers(self) -> None:
        for difficulty in ("Beginner", "Intermediate", "Advanced", "Expert"):
            print(f"=== {difficulty} ===", flush=True)
            self.select_tier(difficulty)
            self.scan_current_tier(difficulty)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial")
    parser.add_argument("--difficulty", default="Intermediate")
    parser.add_argument("--current-expansion", action="store_true")
    parser.add_argument("--all-tiers", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("var/discovery/catalog.json"))
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output = args.output if args.output.is_absolute() else root / args.output
    run = DiscoveryRun(AndroidVision(root, args.serial), output)
    if args.current_expansion:
        count = run.scan_current_expansion(args.difficulty, "current", "current")
        print(f"discovered {count} battle cards", flush=True)
    elif args.all_tiers:
        run.scan_all_tiers()
        print(f"discovered {len(run.battles)} unique battle cards", flush=True)
    else:
        run.scan_current_tier(args.difficulty)
        print(f"discovered {len(run.battles)} unique battle cards", flush=True)


if __name__ == "__main__":
    main()
