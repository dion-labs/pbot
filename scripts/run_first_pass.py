#!/usr/bin/env python3
"""Run a bounded, deterministic first-pass auto-battle pilot."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from pbot.config import Settings
from pbot.executor import (
    ACTIONABLE_RESULT_STATES,
    battle_list_matches,
    classify_screen,
    normalize_game_label,
    outcome_from_text,
    track_actionable_repeat,
)
from pbot.storage import Store
from pbot.strategy import parse_battle_recommendation

from discover_step_up import (
    AndroidVision,
    BattleObservation,
    DiscoveryRun,
    OcrLine,
    parse_battle_cards,
    parse_expansion_candidates,
    pretty_expansion,
    slug,
    text_dump,
    wait_for,
)


def screen_has(value: str, text: str) -> bool:
    return value.casefold() in text.casefold()


def owned_deck_tap(line_x: int, line_center_y: int) -> tuple[int, int]:
    """Map an owned-deck OCR anchor to a safe point inside its card."""
    column_x = 270 if line_x < 540 else 810
    # The selector can stop at arbitrary scroll offsets, so fixed "upper" and
    # "lower" row centers can target a neighbouring card. OCR anchors are
    # already inside the requested tile (name or durable slot number); tap that
    # observed position directly, bounded away from the modal chrome.
    row_y = max(600, min(line_center_y, 1850))
    return column_x, row_y


def matching_owned_deck_line(lines: list[OcrLine], deck_name: str) -> OcrLine | None:
    return next((line for line in lines if deck_name_visible(deck_name, line.text)), None)


def _within_one_edit(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right, strict=True)) <= 1
    index_left = index_right = differences = 0
    while index_left < len(left) and index_right < len(right):
        if left[index_left] == right[index_right]:
            index_left += 1
        else:
            differences += 1
            if differences > 1:
                return False
        index_right += 1
    return True


def deck_name_visible(deck_name: str, text: str) -> bool:
    """Tolerate one OCR edit while confirming a selected deck name."""
    target_words = normalize_game_label(deck_name).split()
    visible_words = normalize_game_label(text).split()
    if not target_words:
        return False
    target = "".join(target_words)
    for width in range(max(1, len(target_words) - 1), len(target_words) + 2):
        for start in range(len(visible_words) - width + 1):
            candidate = "".join(visible_words[start : start + width])
            if _within_one_edit(target, candidate):
                return True
    return False


def find_owned_deck(
    device: AndroidVision,
    deck_name: str,
    slot_number: int | None = None,
) -> OcrLine | None:
    """Find an exact owned deck even when it is outside the four-card viewport."""
    directions = (
        # Short scrolls are intentional: a full-height gesture can jump from
        # slots 13-16 directly to 19-21 and skip the managed 17-18 row.
        ("forward", 540, 1600, 540, 1100, 32),
        ("backward", 540, 1000, 540, 1450, 40),
    )
    for direction, x1, y1, x2, y2, pages in directions:
        previous_signature: tuple[tuple[str, int, int], ...] | None = None
        stale = 0
        for page in range(pages):
            _, lines = device.frame(f"owned-{direction}-{page + 1}")
            text = text_dump(lines)
            if classify_screen(text) != "deck_selector":
                raise RuntimeError(f"Owned deck selector closed unexpectedly; saw:\n{text}")
            match = matching_owned_deck_line(lines, deck_name)
            if match:
                if slot_number is not None:
                    slot = next(
                        (
                            line
                            for line in lines
                            if normalize_game_label(line.text) == str(slot_number)
                            and 350 <= line.center_y <= 1950
                        ),
                        None,
                    )
                    if slot:
                        # Long names sit at the bottom of their card and can
                        # cross the generic row threshold even while the card
                        # itself is in the upper visible row. The durable slot
                        # number is a safer card-position anchor; Battle Rules
                        # still verifies the selected name before play.
                        return OcrLine(
                            match.text,
                            match.confidence,
                            slot.x + slot.width // 2,
                            slot.y,
                            slot.width,
                            slot.height,
                        )
                return match
            if slot_number is not None:
                slot = next(
                    (
                        line
                        for line in lines
                        if normalize_game_label(line.text) == str(slot_number)
                        and 350 <= line.center_y <= 1950
                    ),
                    None,
                )
                if slot:
                    # A bottom-row name can be hidden under the fixed tab bar
                    # while its large slot number remains visible. Mark the
                    # synthetic match as a bottom-row item even if OCR places
                    # that number just above the normal row threshold. The
                    # slot is durable account knowledge and the selected name
                    # is still verified on Battle Rules before play begins.
                    return OcrLine(
                        deck_name,
                        slot.confidence,
                        # Slot numbers are very large and their bounding box
                        # can begin left of the two-column midpoint. Use the
                        # number's center as the synthetic horizontal anchor.
                        slot.x + slot.width // 2,
                        slot.y if slot.center_y < 1250 else max(slot.y, 1520),
                        slot.width,
                        slot.height,
                    )
            signature = tuple(
                (normalize_game_label(line.text), line.x // 40, line.center_y // 40)
                for line in lines
                if 350 <= line.center_y <= 1950
            )
            stale = stale + 1 if signature == previous_signature else 0
            previous_signature = signature
            if stale >= 2:
                break
            device.swipe(x1, y1, x2, y2, 650)
    return None


class FirstPassPilot:
    def __init__(
        self,
        root: Path,
        store: Store,
        device: AndroidVision,
        difficulty: str,
        expansion: str,
        deck_name: str,
        timeout: float,
        poll_interval: float,
        prefer_requested_deck: bool = False,
    ) -> None:
        self.root = root
        self.store = store
        self.device = device
        self.difficulty = difficulty
        self.expansion = expansion
        self.deck_name = deck_name
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.prefer_requested_deck = prefer_requested_deck
        self.catalog_path = root / "var" / "discovery" / "catalog.json"
        self.discovery = DiscoveryRun(device, self.catalog_path)

    def log(self, kind: str, message: str, level: str = "info", payload: dict | None = None) -> None:
        print(message, flush=True)
        self.store.add_event(kind, message, level, payload)

    def queued_target(self) -> BattleObservation:
        matches = [
            item
            for item in self.store.pending_battles(limit=500)
            if item["difficulty"] == self.difficulty and item["expansion"] == self.expansion
        ]
        if not matches:
            raise RuntimeError(f"No pending {self.difficulty} battle is cataloged for {self.expansion}")
        item = matches[0]
        return BattleObservation(
            id=str(item["id"]),
            expansion=str(item["expansion"]),
            difficulty=str(item["difficulty"]),
            name=str(item["name"]),
            first_win=False,
            missions_complete=int(item["missions_complete"] or 0),
            missions_total=int(item["missions_total"] or 0),
            evidence_path="",
        )

    def requested_deck_slot(self) -> int | None:
        owned_decks = getattr(self.store, "owned_decks", None)
        if not callable(owned_decks):
            return None
        match = next(
            (
                deck
                for deck in owned_decks()
                if normalize_game_label(str(deck["display_name"]))
                == normalize_game_label(self.deck_name)
            ),
            None,
        )
        return int(match["slot_number"]) if match and match.get("slot_number") is not None else None

    def current_screen(self, label: str) -> tuple[Path, str, str]:
        path, lines = self.device.frame(label)
        text = text_dump(lines)
        return path, text, classify_screen(text)

    def choose_recommended_deck(self) -> None:
        _, lines = self.device.frame("pilot-deck-selector")
        text = text_dump(lines)
        if classify_screen(text) != "deck_selector":
            raise RuntimeError(f"Expected the deck selector; saw:\n{text}")
        # Deck selector tabs retain their last position globally. Always move
        # to My Decks before evaluating recommendations so an earlier rental
        # browsing session cannot silently consume a rental use.
        self.device.tap(270, 2050)
        _, lines = self.device.frame("pilot-owned-deck-selector")
        text = text_dump(lines)
        if classify_screen(text) != "deck_selector":
            raise RuntimeError(f"My Decks selector did not remain open; saw:\n{text}")
        if self.prefer_requested_deck:
            requested = find_owned_deck(
                self.device,
                self.deck_name,
                self.requested_deck_slot(),
            )
            if not requested:
                raise RuntimeError(f"Requested owned deck is not available: {self.deck_name}")
            self.device.tap(*owned_deck_tap(requested.x, requested.center_y))
            self.device.tap(800, 2200)
            _, selected, state = self.current_screen("pilot-forced-deck-selected")
            if state != "prebattle" or not deck_name_visible(self.deck_name, selected):
                raise RuntimeError(f"Battle Rules did not confirm owned deck {self.deck_name}; saw:\n{selected}")
            self.log("deck.selected_requested", f"Selected requested owned deck: {self.deck_name}", "success")
            return
        recommended = next((line for line in lines if "recommended" in line.text.casefold()), None)
        if not recommended:
            requested = next(
                (
                    line
                    for line in lines
                    if normalize_game_label(line.text) == normalize_game_label(self.deck_name)
                ),
                None,
            )
            if requested:
                self.device.tap(*owned_deck_tap(requested.x, requested.center_y))
                self.device.tap(800, 2200)
                _, selected, state = self.current_screen("pilot-requested-deck-selected")
                if state != "prebattle":
                    raise RuntimeError(f"Requested owned deck selection did not return to battle rules; saw:\n{selected}")
                self.log("deck.selected_requested", f"Selected requested owned deck: {self.deck_name}", "success")
                return
            fallback_names = [
                line.text
                for line in lines
                if line.x < 540
                and 950 <= line.center_y <= 1250
                and line.text.casefold() not in {"my decks", "rental decks", "cancel", "ok"}
                and any(character.isalpha() for character in line.text)
            ]
            if not fallback_names:
                raise RuntimeError("The deck selector exposed neither a recommended deck nor a usable owned deck")
            self.deck_name = fallback_names[-1]
            self.device.tap(270, 850)
            self.device.tap(800, 2200)
            _, selected, state = self.current_screen("pilot-fallback-deck-selected")
            if state != "prebattle":
                raise RuntimeError(f"Fallback deck selection did not return to battle rules; saw:\n{selected}")
            self.log(
                "deck.selected_fallback",
                f"No recommended owned deck; selected first owned deck: {self.deck_name}",
                "warning",
            )
            return
        left_half = recommended.x < 540
        candidates = [
            line.text
            for line in lines
            if (line.x < 540) == left_half
            and recommended.y + 430 <= line.y <= recommended.y + 700
            and line.text.casefold() not in {"my decks", "rental decks", "cancel", "ok"}
        ]
        if candidates:
            self.deck_name = candidates[-1]
        self.device.tap(270 if left_half else 810, recommended.y + 300)
        self.device.tap(800, 2200)
        _, selected, state = self.current_screen("pilot-deck-selected")
        if state != "prebattle":
            raise RuntimeError(f"Recommended deck selection did not return to battle rules; saw:\n{selected}")
        self.log("deck.selected", f"Selected recommended deck: {self.deck_name}", "success")

    def expansion_signature(self) -> tuple[str, str]:
        target = normalize_game_label(self.expansion)
        for item in reversed(self.discovery.expansions):
            title = pretty_expansion(str(item.get("title_hint", "")))
            signature = str(item.get("signature", ""))
            if normalize_game_label(title) == target and signature[:2] in {"A:", "B:"}:
                return signature[0], signature
        raise RuntimeError(f"No discovery signature is known for expansion {self.expansion}")

    def select_open_expansion(self) -> None:
        tab, target_signature = self.expansion_signature()
        self.device.tap(650 if tab == "A" else 250, 2050)
        stale = 0
        misroutes = 0
        previous: tuple[tuple[str, int], ...] = ()
        for page in range(18):
            _, lines = self.device.frame(f"route-{self.difficulty}-{tab}-{page + 1}")
            text = text_dump(lines)
            if classify_screen(text) != "expansion_selector":
                raise RuntimeError(f"Expansion selector closed unexpectedly; saw:\n{text}")
            candidates = parse_expansion_candidates(lines, tab)
            match = next((item for item in candidates if item.signature == target_signature), None)
            if match:
                self.device.tap(540, match.tap_y)
                _, opened = wait_for(self.device, "Expansions", "route-expansion-opened", timeout=15)
                opened_text = text_dump(opened)
                if not battle_list_matches(opened_text, self.difficulty, self.expansion):
                    misroutes += 1
                    if misroutes >= 3:
                        raise RuntimeError(
                            f"Expansion route repeatedly landed on the wrong list; expected "
                            f"{self.difficulty} / {self.expansion}, saw:\n{opened_text}"
                        )
                    self.log(
                        "route.retry",
                        f"Expansion tap missed {self.expansion}; reopening the selector ({misroutes}/3)",
                        "warning",
                    )
                    self.discovery.open_expansions()
                    self.device.tap(650 if tab == "A" else 250, 2050)
                    stale = 0
                    previous = ()
                    continue
                self.log(
                    "route.completed",
                    f"Routed to {self.difficulty} / {self.expansion}",
                    "success",
                    {"series": tab, "signature": target_signature},
                )
                return

            layout = tuple((item.signature, item.tap_y // 20) for item in candidates)
            stale = stale + 1 if layout == previous else 0
            previous = layout
            if stale >= 3:
                break
            self.device.swipe(540, 1750, 540, 1250, 650)
        raise RuntimeError(
            f"Could not find {self.expansion} ({target_signature}) in the {tab} Series expansion selector"
        )

    def route_to_target(self) -> None:
        _, text, screen = self.current_screen("route-start")
        if screen == "battle_list" and battle_list_matches(text, self.difficulty, self.expansion):
            return
        if screen == "deck_selector":
            self.device.tap(270, 2200)
            self.device.press_back()
        elif screen == "prebattle":
            self.device.press_back()
        elif screen == "expansion_selector":
            self.device.tap(540, 2220)
        elif screen in {"deck_builder", "deck_detail", "owned_deck_list"}:
            # Account/deck management can be restored as the root Unity
            # activity. It has no usable Back stack, while a normal launcher
            # intent merely foregrounds the same screen. No battle lifecycle
            # is active, so a clean force-stop/relaunch is the deterministic
            # recovery path back through the title screen.
            subprocess.run(
                [*self.device.adb, "shell", "am", "force-stop", "jp.pokemon.pokemontcgp"],
                check=True,
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                [
                    *self.device.adb,
                    "shell",
                    "monkey",
                    "-p",
                    "jp.pokemon.pokemontcgp",
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            time.sleep(8)
        elif screen in {"battle", "victory", "defeat", "summary", "tasks", "rewards", "unlocked"}:
            raise RuntimeError(f"Refusing to route away from active battle lifecycle state: {screen}")

        _, text, screen = self.current_screen("route-list-check")
        if screen != "battle_list" or not screen_has(self.difficulty, text):
            self.discovery.select_tier(self.difficulty)
            _, text, screen = self.current_screen("route-tier-selected")
        if screen != "battle_list":
            raise RuntimeError(f"Difficulty route did not reach a battle list; saw:\n{text}")
        if battle_list_matches(text, self.difficulty, self.expansion):
            return

        self.discovery.open_expansions()
        self.select_open_expansion()

    def open_frontier(self) -> BattleObservation:
        stale = 0
        previous: tuple[str, ...] = ()
        for page in range(16):
            path, lines = self.device.frame(f"pilot-frontier-page-{page + 1}")
            text = text_dump(lines)
            if classify_screen(text) != "battle_list":
                raise RuntimeError(f"Expected the Step-Up battle list; saw:\n{text}")
            if not battle_list_matches(text, self.difficulty, self.expansion):
                raise RuntimeError(
                    f"Pilot is guarded for {self.difficulty} / {self.expansion}; the phone is on a different list"
                )
            cards = parse_battle_cards(path, lines, self.difficulty, self.expansion)
            pending = [card for card in cards if not card.observation.first_win]
            if pending:
                card = pending[0]
                # The mission counter can sit under the fixed controls on the final
                # card. Its title area remains visible and is a safe hit target.
                tap_y = card.tap_y if card.tap_y <= 1700 else card.tap_y - 170
                detail_text = text
                for tap_attempt, (x, y) in enumerate(
                    ((750, tap_y), (700, max(750, tap_y - 100)), (850, tap_y)),
                    start=1,
                ):
                    self.device.tap(x, y)
                    _, detail_text, state = self.current_screen(f"pilot-prebattle-{tap_attempt}")
                    if state == "deck_selector":
                        self.choose_recommended_deck()
                        state = "prebattle"
                    if state == "prebattle":
                        return card.observation
                    if state != "battle_list":
                        break
                raise RuntimeError(f"Battle card did not open the rules screen; saw:\n{detail_text}")

            signature = tuple(card.observation.id for card in cards)
            stale = stale + 1 if signature == previous else 0
            previous = signature
            if stale >= 3:
                break
            self.device.swipe(540, 1800, 540, 1250, 600)
        raise RuntimeError(f"No visible frontier found for {self.difficulty} / {self.expansion}")

    def prepare_battle(self, target: BattleObservation) -> None:
        _, text, state = self.current_screen("pilot-prepare")
        if state != "prebattle":
            raise RuntimeError(f"Expected battle rules before starting {target.name}; saw:\n{text}")
        requested = normalize_game_label(self.deck_name)
        if requested != "selected deck" and not deck_name_visible(self.deck_name, text):
            self.device.tap(540, 1750)
            _, selector_text, state = self.current_screen("pilot-explicit-deck-selector")
            if state != "deck_selector":
                raise RuntimeError(f"Could not open the deck selector for {self.deck_name}; saw:\n{selector_text}")
            self.device.tap(270, 2050)
            match = find_owned_deck(
                self.device,
                self.deck_name,
                self.requested_deck_slot(),
            )
            if not match:
                raise RuntimeError(f"Requested owned deck is not available: {self.deck_name}")
            self.device.tap(*owned_deck_tap(match.x, match.center_y))
            self.device.tap(800, 2200)
            _, text, state = self.current_screen("pilot-explicit-deck-selected")
            if state != "prebattle" or not deck_name_visible(self.deck_name, text):
                raise RuntimeError(f"Battle Rules did not confirm owned deck {self.deck_name}; saw:\n{text}")
            self.log("deck.selected_requested", f"Selected requested owned deck: {self.deck_name}", "success")
        expected_prefix = target.name.split(" Deck", 1)[0]
        if expected_prefix.casefold() not in " ".join(text.split()).casefold():
            raise RuntimeError(f"Open battle does not match queued target {target.name}")
        if "auto off" in " ".join(text.casefold().split()):
            self.device.tap(850, 2220)
            _, toggled, state = self.current_screen("pilot-auto-on")
            if state != "prebattle" or "auto on" not in " ".join(toggled.casefold().split()):
                raise RuntimeError("Could not enable auto mode")

    def play_to_result(
        self,
        target: BattleObservation,
        attempt_id: int,
        already_active: bool = False,
    ) -> tuple[str, Path]:
        event = "attempt.reattached_play" if already_active else "attempt.started"
        message = f"Monitoring active auto battle: {target.name}" if already_active else f"Starting auto battle: {target.name}"
        self.log(event, message, "info", {"battle_id": target.id})
        if not already_active:
            self.device.tap(540, 2030)
        deadline = time.monotonic() + self.timeout
        result: str | None = None
        evidence: Path | None = None
        last_state = ""
        repeated_actionable = ""
        actionable_count = 0
        start_retries = 0

        while time.monotonic() < deadline:
            path, text, state = self.current_screen(f"pilot-{target.id}-{int(time.monotonic())}")
            repeated_actionable, actionable_count = track_actionable_repeat(
                repeated_actionable, actionable_count, state
            )
            if state != last_state and state not in {"unknown", "battle"}:
                self.log("attempt.screen", f"{target.name}: {state}", "info")
                last_state = state
            if actionable_count >= 3 and state in ACTIONABLE_RESULT_STATES:
                self.log(
                    "device.touch_protection_recovery",
                    f"{target.name}: result screen remained on {state}; trying Game Booster unlock",
                    "warning",
                )
                self.device.dismiss_touch_protection()
                actionable_count = 0
                time.sleep(self.poll_interval)
                continue
            if state in {"victory", "defeat", "tie"}:
                if result is None:
                    result = {"victory": "win", "defeat": "loss", "tie": "tie"}[state]
                    evidence = path
                self.device.tap(540, 2050)
            elif state == "summary":
                if result is None:
                    result = outcome_from_text(text)
                    if result is None:
                        raise RuntimeError("Summary screen did not expose a recoverable victory or defeat label")
                    evidence = path
                    self.log("attempt.recovered_result", f"Recovered {result} from the battle summary", "warning")
                self.device.tap(540, 2050)
            elif state in {"tasks", "rewards"}:
                if result is None:
                    result = outcome_from_text(text)
                    evidence = path if result else evidence
                if result:
                    self.device.tap(540, 2200)
            elif state == "unlocked" and result:
                self.device.tap(540, 1600)
            elif state == "loss_recommendation":
                recommendation = parse_battle_recommendation(text)
                if recommendation:
                    captured = self.store.record_battle_recommendation(
                        target.id,
                        attempt_id,
                        recommendation.recommended_type,
                        recommendation.recommended_deck_name,
                        recommendation.source_text,
                        recommendation.confidence,
                        str(path),
                    )
                    self.log(
                        "strategy.recommendation_captured",
                        f"Captured {recommendation.recommended_type or 'unknown-type'} recommendation"
                        f" for {target.name}",
                        "success",
                        {
                            "battle_id": target.id,
                            "recommendation_id": captured.get("id"),
                            "recommended_type": recommendation.recommended_type,
                            "recommended_deck_name": recommendation.recommended_deck_name,
                        },
                    )
                if result is None:
                    result = "loss"
                    evidence = path
                    self.log("attempt.recovered_result", "Recovered loss from the deck recommendation modal", "warning")
                self.device.tap(540, 1800)
            elif state == "prebattle" and result is None:
                start_retries += 1
                if start_retries > 3:
                    raise RuntimeError("Battle start remained on the rules screen after three retries")
                self.log(
                    "attempt.start_retried",
                    f"{target.name}: Battle tap did not register; retrying ({start_retries}/3)",
                    "warning",
                )
                self.device.tap(540, 2030)
            elif state == "prebattle" and result in {"loss", "tie"}:
                # Closing the post-result deck recommendation can return to the
                # rules screen rather than the battle list. Back out once so a
                # loss or tie can be persisted and deferred without a blind
                # retry or waiting until the overall battle timeout.
                self.device.press_back()
            elif state == "unknown" and result and self.device.foreground_package() != "jp.pokemon.pokemontcgp":
                # Some post-loss Back transitions exit the app instead of
                # returning to the battle list. The result is already durable
                # in memory, so relaunch and route to the guarded target list
                # before rescanning and persisting it.
                self.log(
                    "attempt.app_recovered",
                    f"{target.name}: game left the foreground after confirmed {result}; routing back to the list",
                    "warning",
                )
                self.route_to_target()
                return result, evidence or path
            elif state == "battle_list" and result:
                return result, evidence or path
            elif state == "title":
                raise RuntimeError("The game returned to the title screen during a battle")
            time.sleep(self.poll_interval)

        raise TimeoutError(f"Timed out after {self.timeout:g}s while running {target.name}")

    def rescan_and_finish(self, attempt_id: int, target: BattleObservation, result: str, evidence: Path) -> None:
        self.discovery.scan_current_expansion(
            self.difficulty,
            f"executor-{slug(self.expansion)}",
            self.expansion,
        )
        observed = self.discovery.battles.get(target.id)
        missions_complete = observed.missions_complete if observed else target.missions_complete
        missions_total = observed.missions_total if observed else target.missions_total
        outcome = self.store.finish_attempt(
            attempt_id,
            result,
            str(evidence),
            missions_complete,
            missions_total,
        )
        current_expansion = [
            item
            for item in self.discovery.battles.values()
            if item.expansion == self.expansion and item.difficulty == self.difficulty
        ]
        self.store.import_battles([asdict(item) for item in current_expansion])
        level = "success" if result == "win" else "warning"
        self.log(
            "attempt.completed",
            f"{target.name}: {result} with {self.deck_name} (auto)",
            level,
            outcome,
        )

    def rescan_and_reconcile(
        self,
        attempt_id: int,
        target: BattleObservation,
        result: str,
        evidence: Path,
    ) -> None:
        self.discovery.scan_current_expansion(
            self.difficulty,
            f"executor-resume-{slug(self.expansion)}",
            self.expansion,
        )
        observed = self.discovery.battles.get(target.id)
        missions_complete = observed.missions_complete if observed else target.missions_complete
        missions_total = observed.missions_total if observed else target.missions_total
        if result == "win":
            if not observed or not observed.first_win:
                raise RuntimeError("Active-battle resume did not find phone-side first-win evidence")
            outcome = self.store.reconcile_interrupted_win(attempt_id, asdict(observed))
        else:
            outcome = self.store.reconcile_error_result(
                attempt_id,
                result,
                str(evidence),
                missions_complete,
                missions_total,
            )
        current_expansion = [
            item
            for item in self.discovery.battles.values()
            if item.expansion == self.expansion and item.difficulty == self.difficulty
        ]
        self.store.import_battles([asdict(item) for item in current_expansion])
        self.log(
            "attempt.resumed",
            f"Reconciled active {target.name}: {result} with {self.deck_name} (auto)",
            "success" if result == "win" else "warning",
            outcome,
        )

    def run(self, limit: int) -> list[dict[str, object]]:
        state = self.store.get_state()
        self.store.set_state(
            "running",
            f"First-pass pilot: {self.difficulty} / {self.expansion}",
            str(state.get("device_serial") or self.device.adb[-1]),
        )
        results: list[dict[str, object]] = []

        for index in range(limit):
            _, _, initial_screen = self.current_screen(f"pilot-resume-check-{index + 1}")
            if initial_screen in {
                "battle",
                "victory",
                "defeat",
                "tie",
                "summary",
                "tasks",
                "rewards",
                "unlocked",
                "loss_recommendation",
            }:
                target = self.queued_target()
                interrupted = self.store.latest_recoverable_attempt(target.id, self.deck_name)
                if not interrupted:
                    raise RuntimeError(
                        "An active battle is visible but no matching interrupted owned-deck attempt exists"
                    )
                attempt_id = int(interrupted["id"])
                self.log(
                    "attempt.reattached",
                    f"Reattached to active {target.name} attempt {attempt_id}",
                    "warning",
                    {"attempt_id": attempt_id, "battle_id": target.id, "deck_name": self.deck_name},
                )
                result, evidence = self.play_to_result(target, attempt_id, already_active=True)
                self.rescan_and_reconcile(attempt_id, target, result, evidence)
                results.append(
                    {
                        "battle_id": target.id,
                        "name": target.name,
                        "result": result,
                        "attempt_id": attempt_id,
                        "resumed": True,
                    }
                )
                if result != "win":
                    break
                continue
            self.route_to_target()
            _, text, screen = self.current_screen(f"pilot-ready-{index + 1}")
            if screen == "prebattle":
                target = self.queued_target()
            elif screen == "deck_selector":
                target = self.queued_target()
                self.choose_recommended_deck()
            elif screen == "battle_list":
                target = self.open_frontier()
            else:
                raise RuntimeError(f"Pilot must start on the battle list or rules screen; saw:\n{text}")

            self.prepare_battle(target)
            attempt_id = self.store.start_attempt(
                target.id,
                target.expansion,
                target.difficulty,
                target.name,
                self.deck_name,
                "auto",
            )
            try:
                result, evidence = self.play_to_result(target, attempt_id)
                self.rescan_and_finish(attempt_id, target, result, evidence)
            except Exception as exc:
                error_path, _, _ = self.current_screen("pilot-error")
                self.store.finish_attempt(attempt_id, "error", str(error_path))
                self.log("attempt.error", f"{target.name}: {exc}", "error", {"attempt_id": attempt_id})
                self.store.set_state("handoff", f"Pilot stopped: {exc}", str(state.get("device_serial") or ""))
                raise

            results.append({"battle_id": target.id, "name": target.name, "result": result, "attempt_id": attempt_id})
            if result != "win":
                self.log("pilot.stopped", "Pilot stopped after the first loss; deck research is required", "warning")
                break

        if self.store.get_state().get("status") != "paused":
            self.store.set_state(
                "ready",
                f"First-pass pilot complete: {len(results)} attempted",
                str(state.get("device_serial") or ""),
            )
        self.log("pilot.completed", f"First-pass pilot completed {len(results)} battle(s)", "success", {"results": results})
        return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial")
    parser.add_argument("--difficulty", default="Intermediate")
    parser.add_argument("--expansion", required=True)
    parser.add_argument("--deck-name")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--poll-interval", type=float, default=5)
    parser.add_argument("--navigate-only", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.limit <= 3:
        parser.error("the guarded pilot limit must be between 1 and 3")

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
        args.deck_name or "selected deck",
        args.timeout,
        args.poll_interval,
        args.deck_name is not None,
    )
    try:
        if args.navigate_only:
            pilot.route_to_target()
            store.set_state(
                "ready",
                f"Route validated: {args.difficulty} / {args.expansion}",
                str(store.get_state().get("device_serial") or args.serial or ""),
            )
            results = []
        else:
            results = pilot.run(args.limit)
    except Exception as exc:
        state = store.get_state()
        if state.get("status") == "running":
            store.set_state("handoff", f"Pilot stopped: {exc}", str(state.get("device_serial") or ""))
            store.add_event("pilot.error", f"Pilot stopped: {exc}", "error")
        raise
    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
