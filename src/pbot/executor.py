from __future__ import annotations

import re


ACTIONABLE_RESULT_STATES = frozenset({
    "victory",
    "defeat",
    "tie",
    "summary",
    "tasks",
    "rewards",
    "unlocked",
    "loss_recommendation",
})


def normalize_game_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def battle_list_matches(text: str, difficulty: str, expansion: str) -> bool:
    normalized = normalize_game_label(text)
    expected_list_header = "step up battle" in normalized or (
        normalize_game_label(difficulty) == "expert" and "expert solo battle" in normalized
    )
    return (
        normalize_game_label(difficulty) in normalized
        and normalize_game_label(expansion) in normalized
        and expected_list_header
        and "expansions" in normalized
    )


def outcome_from_text(text: str) -> str | None:
    normalized = normalize_game_label(text)
    if "victory" in normalized:
        return "win"
    if "defeat" in normalized or "you lost" in normalized:
        return "loss"
    if re.search(r"\btie\b", normalized):
        return "tie"
    return None


def foreground_package_from_dumpsys(text: str) -> str | None:
    """Extract the focused Android package from `dumpsys window` output."""
    match = re.search(r"mCurrentFocus=.*?\bu\d+\s+([A-Za-z0-9._]+)/", text)
    return match.group(1) if match else None


def track_actionable_repeat(previous: str, count: int, state: str) -> tuple[str, int]:
    """Count repeated result states without letting noisy OCR frames reset the watchdog."""
    if state in ACTIONABLE_RESULT_STATES:
        return (state, count + 1) if state == previous else (state, 1)
    if state in {"unknown", "battle"}:
        return previous, count
    return "", 0


def touch_protection_likely(mean_luminance: float, text: str) -> bool:
    """Identify Samsung's dimmed touch lock even when its lock label is absent."""
    if mean_luminance >= 35:
        return False
    normalized = normalize_game_label(text)
    return any(
        marker in normalized
        for marker in (
            "battle rules",
            "tap to proceed",
            "select a deck",
            "step up battle",
            "drag lock icon",
            "offering rates",
            "wonder pick",
            "social hub",
        )
    )


def classify_screen(text: str) -> str:
    """Classify OCR text from the small set of screens used by auto battles."""
    normalized = " ".join(text.casefold().split())
    has_victory = "victory" in normalized
    has_defeat = "defeat" in normalized or "you lost" in normalized
    has_tie = re.search(r"\btie\b", normalized) is not None

    if "date has changed" in normalized and "returning to the title screen" in normalized:
        return "daily_reset"
    if "news" in normalized and "availability period" in normalized:
        return "news_modal"
    if "battle rules" in normalized and "battle!" in normalized:
        return "prebattle"
    if "select a deck" in normalized and "my decks" in normalized and "rental decks" in normalized:
        return "deck_selector"
    if "remove all" in normalized and "auto-build" in normalized and "columns" in normalized:
        return "deck_builder"
    if (
        "energy" in normalized
        and "accessories" in normalized
        and "highlight cards" in normalized
        and "20/20" in normalized
        and "edit" in normalized
    ):
        return "deck_detail"
    if "my decks" in normalized and "build new" in normalized:
        return "owned_deck_list"
    if "new battle unlocked" in normalized and "ok" in normalized:
        return "unlocked"
    if "recommended for this battle" in normalized and "to my decks" in normalized:
        return "loss_recommendation"
    if "turns played" in normalized and "tap to proceed" in normalized:
        return "summary"
    if "battle tasks" in normalized and "tap to proceed" in normalized:
        return "tasks"
    if "next" in normalized and (has_victory or has_defeat or "reward" in normalized):
        return "rewards"
    if "tap to proceed" in normalized and has_victory:
        return "victory"
    if "tap to proceed" in normalized and has_defeat:
        return "defeat"
    if "tap to proceed" in normalized and has_tie:
        return "tie"
    if "select expansion" in normalized and "a series" in normalized and "b series" in normalized:
        return "expansion_selector"
    if "step-up battle" in normalized and "expansions" in normalized:
        return "battle_list"
    if "expert solo battle" in normalized and "expansions" in normalized:
        return "battle_list"
    if "beginner" in normalized and "intermediate" in normalized and "step-up battle" in normalized:
        return "step_up_overview"
    if "random battle" in normalized and "step-up battle" in normalized:
        return "solo_menu"
    if "versus" in normalized and "solo" in normalized:
        return "battle_hub"
    if "wonder pick" in normalized and "shop" in normalized:
        return "home"
    if "offering rates" in normalized and "select other booster packs" in normalized:
        return "home_packs"
    if "social hub" in normalized and ("community showcases" in normalized or "friends" in normalized):
        return "social_hub"
    if "opponent" in normalized or ("auto" in normalized and "battle log" not in normalized):
        return "battle"
    if "tap to start" in normalized:
        return "title"
    return "unknown"
