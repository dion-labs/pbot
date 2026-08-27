from pbot.executor import (
    battle_list_matches,
    classify_screen,
    foreground_package_from_dumpsys,
    normalize_game_label,
    outcome_from_text,
    touch_protection_likely,
    track_actionable_repeat,
)


def test_classifies_battle_lifecycle_screens() -> None:
    assert classify_screen("The date has changed.\nReturning to the title screen.\nOK") == "daily_reset"
    assert classify_screen("News\nWonder Pick Event Underway\nAvailability Period\nX") == "news_modal"
    assert classify_screen("Battle Rules\nBattle!\nAuto On") == "prebattle"
    assert classify_screen("Battle Rules\nSelect a Deck\nMy Decks\nRental Decks\nOK") == "deck_selector"
    assert classify_screen("Remove All\nAuto-build\n20/20\n5 columns\nOK") == "deck_builder"
    assert classify_screen(
        "pbotwater\nEnergy\nAccessories\nHighlight cards\n20/20\nEdit\nCancel\nSave"
    ) == "deck_detail"
    assert classify_screen("My Decks\n21/25\nBuild New\npbotwater") == "owned_deck_list"
    assert classify_screen("Opponent\nAuto\nCelebi ex") == "battle"
    assert classify_screen("Victory\nTap to Proceed") == "victory"
    assert classify_screen("Defeat\nTap to Proceed") == "defeat"
    assert classify_screen("Tie\nTap to Proceed") == "tie"
    assert classify_screen("Victory!\nTurns played\nTap to Proceed") == "summary"
    assert classify_screen("Victory!\nBattle Tasks\nPut a Stage 1 Pokémon into play\nTap to Proceed") == "tasks"
    assert classify_screen("Victory!\nYou did not acquire any rewards.\nNext") == "rewards"
    assert classify_screen("New Battle Unlocked!\nHo-Oh & Blaziken Deck\nOK") == "unlocked"
    assert classify_screen(
        "A Water-type deck is recommended for this battle!\nTo My Decks\nTo Rental Decks"
    ) == "loss_recommendation"
    assert classify_screen("Select Expansion\nB Series\nA Series") == "expansion_selector"
    assert classify_screen("Step-Up Battle\nIntermediate\nExpansions") == "battle_list"
    assert classify_screen("Expert Solo Battle\nWISDOM OF SEA AND SKY\nExpansions") == "battle_list"
    assert classify_screen("Step-Up Battle\nBeginner\nIntermediate\nAdvanced") == "step_up_overview"
    assert classify_screen("Random Battle\nStep-Up Battle") == "solo_menu"
    assert classify_screen("Versus\nSolo") == "battle_hub"
    assert classify_screen("Wonder Pick\nShop\nMissions") == "home"
    assert classify_screen("Offering Rates\nSelect other booster packs") == "home_packs"
    assert classify_screen("Social Hub\nCommunity Showcases\nShare\nTrade\nFriends") == "social_hub"


def test_normalizes_ocr_labels_for_route_matching() -> None:
    assert normalize_game_label("DELUXE PACK: eX") == "deluxe pack ex"
    assert battle_list_matches(
        "Step-Up Battle\nIntermediate\nDELUXE PACK eX\nExpansions",
        "Intermediate",
        "Deluxe Pack: ex",
    )
    assert battle_list_matches(
        "Expert Solo Battle\nWISDOM OF SEA AND SKY\nExpansions",
        "Expert",
        "Wisdom of Sea and Sky",
    )


def test_recovers_outcome_from_summary_text() -> None:
    assert outcome_from_text("Victory!\nTurns played\nTap to Proceed") == "win"
    assert outcome_from_text("Defeat...\nTurns played\nTap to Proceed") == "loss"
    assert outcome_from_text("Tie\nTurns played\nTap to Proceed") == "tie"
    assert outcome_from_text("Battle in progress") is None


def test_extracts_foreground_android_package() -> None:
    assert foreground_package_from_dumpsys(
        "mCurrentFocus=Window{93ffc1c u0 com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity}"
    ) == "com.sec.android.app.launcher"
    assert foreground_package_from_dumpsys("mCurrentFocus=null") is None


def test_actionable_repeat_watchdog_ignores_noisy_ocr_frames() -> None:
    state, count = track_actionable_repeat("", 0, "victory")
    state, count = track_actionable_repeat(state, count, "unknown")
    state, count = track_actionable_repeat(state, count, "battle")
    state, count = track_actionable_repeat(state, count, "victory")
    state, count = track_actionable_repeat(state, count, "unknown")
    assert track_actionable_repeat(state, count, "victory") == ("victory", 3)
    assert track_actionable_repeat("victory", 2, "summary") == ("summary", 1)


def test_detects_unlabeled_dimmed_touch_protection() -> None:
    assert touch_protection_likely(21, "Battle Rules\nMoltres Deck\nBattle!")
    assert touch_protection_likely(20, "Victory!\nTap to Proceed")
    assert touch_protection_likely(18, "Offering Rates\nSelect other booster packs")
    assert not touch_protection_likely(210, "Battle Rules\nBattle!")
    assert not touch_protection_likely(20, "Dark animation with no stable controls")
