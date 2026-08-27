from pathlib import Path

import pytest

from pbot.account_bootstrap import AccountBootstrapper, AccountDeck, known_recipe_id
from pbot.storage import Store


class FakeScanPort:
    def __init__(self, decks: list[AccountDeck] | None = None, error: Exception | None = None) -> None:
        self.decks = decks or []
        self.error = error

    def scan_owned_decks(self) -> list[AccountDeck]:
        if self.error:
            raise self.error
        return self.decks


def test_clean_store_has_recipes_but_no_assumed_owned_decks(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()

    assert store.owned_decks() == []
    assert store.get_deck_recipe("pbotfire")["capture_status"] == "complete"
    assert store.get_account_profile()["status"] == "not_scanned"


def test_complete_scan_becomes_the_account_authority(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    scanner = FakeScanPort([
        AccountDeck("starter", 1, ("Water",), "slot-1.png"),
        AccountDeck("pbotfire", 2, ("Fire",), "slot-2.png"),
    ])

    result = AccountBootstrapper(store, scanner).run("device-1")

    assert result["profile"]["status"] == "ready"
    assert result["profile"]["deck_count"] == 2
    assert sorted(
        ((deck["display_name"], deck["slot_number"]) for deck in store.owned_decks()),
        key=lambda item: item[1],
    ) == [
        ("starter", 1),
        ("pbotfire", 2),
    ]
    fire = next(deck for deck in store.owned_decks() if deck["display_name"] == "pbotfire")
    assert fire["recipe_id"] == "pbotfire"
    assert fire["managed"] == 1


def test_interrupted_scan_preserves_last_complete_profile(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    AccountBootstrapper(
        store,
        FakeScanPort([AccountDeck("safe", 1, ("Psychic",), "safe.png")]),
    ).run("device-1")

    store.begin_account_scan("device-1")
    with pytest.raises(RuntimeError, match="disconnected"):
        FakeScanPort(error=RuntimeError("disconnected")).scan_owned_decks()
    store.fail_account_scan("device-1", "disconnected")

    assert [deck["display_name"] for deck in store.owned_decks()] == ["safe"]
    assert store.get_account_profile()["status"] == "needs_attention"


def test_rescan_marks_missing_decks_unavailable_only_after_success(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    AccountBootstrapper(
        store,
        FakeScanPort([
            AccountDeck("keep", 1, ("Water",), "one.png"),
            AccountDeck("remove", 2, ("Fire",), "two.png"),
        ]),
    ).run("device-1")

    AccountBootstrapper(
        store,
        FakeScanPort([AccountDeck("keep", 1, ("Water",), "three.png")]),
    ).run("device-1")

    assert [deck["display_name"] for deck in store.owned_decks()] == ["keep"]


def test_known_recipe_matching_is_exact() -> None:
    assert known_recipe_id("pbotfire") == "pbotfire"
    assert known_recipe_id("PBOTFIGHT") == "pbotfight"
    assert known_recipe_id("similar-pbotfire") is None
