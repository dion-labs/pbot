from pathlib import Path

import pytest

from pbot.deck_recipe import (
    HOOPA_EX_THEME,
    MEGA_SHARPEDO_MILOTIC,
    PBOT_DARK,
    PBOT_FIGHT,
    PBOT_FIRE,
    CardSubstitution,
    DeckCard,
    PBOT_WATER_ARTICUNO,
    adapt_recipe,
    persist_recipe,
)
from pbot.storage import Store


def test_published_water_recipe_is_an_exact_twenty_card_list() -> None:
    MEGA_SHARPEDO_MILOTIC.validate()

    assert sum(card.quantity for card in MEGA_SHARPEDO_MILOTIC.cards) == 20
    assert next(
        card.quantity for card in MEGA_SHARPEDO_MILOTIC.cards if card.card_id == "B4-035"
    ) == 2


def test_account_adaptation_replaces_only_the_missing_copy() -> None:
    adapted = PBOT_WATER_ARTICUNO

    assert sum(card.quantity for card in adapted.cards) == 20
    assert next(card.quantity for card in adapted.cards if card.card_id == "B4-035") == 1
    articuno = next(card for card in adapted.cards if card.card_id == "A1-084")
    assert articuno.quantity == 1
    assert articuno.substitute_for == "B4-035"


def test_account_captured_managed_recipes_are_complete() -> None:
    for recipe in (PBOT_FIRE, PBOT_FIGHT, HOOPA_EX_THEME, PBOT_DARK):
        recipe.validate()
        assert sum(card.quantity for card in recipe.cards) == 20


def test_dark_recipe_records_the_single_owned_linoone_replacement() -> None:
    assert next(card for card in HOOPA_EX_THEME.cards if card.card_id == "B4-096").quantity == 2
    assert next(card for card in PBOT_DARK.cards if card.card_id == "B4-096").quantity == 1
    replacement = next(card for card in PBOT_DARK.cards if card.card_id == "B2-099")
    assert replacement.quantity == 1
    assert replacement.substitute_for == "B4-096"


def test_persists_recipe_and_build_evidence(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    persisted = persist_recipe(store, MEGA_SHARPEDO_MILOTIC)
    build = store.record_deck_build(
        persisted["id"],
        "pbotwater",
        "needs_substitution",
        missing_cards=[{"card_id": "B4-035", "quantity": 1}],
        evidence_path="missing.png",
    )

    assert persisted["capture_status"] == "complete"
    assert len(persisted["cards"]) == 13
    assert build["missing_cards"] == [{"card_id": "B4-035", "quantity": 1}]


def test_rejects_an_invalid_card_total() -> None:
    invalid = adapt_recipe
    with pytest.raises(ValueError, match="is not in"):
        invalid(
            MEGA_SHARPEDO_MILOTIC,
            "bad",
            "bad",
            [CardSubstitution("unknown", DeckCard("A2-150", "Cyrus", 1, "supporter"), "x")],
        )
