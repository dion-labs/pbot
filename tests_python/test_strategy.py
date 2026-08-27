from pathlib import Path

from pbot.storage import Store
from pbot.strategy import StrategyResolver, parse_battle_recommendation


def import_frontier(store: Store, battle_id: str = "test:advanced:frontier") -> None:
    store.import_battles([{
        "id": battle_id,
        "expansion": "Test",
        "difficulty": "Advanced",
        "name": "Frontier ex Deck (Test)",
        "first_win": False,
        "missions_complete": 0,
        "missions_total": 4,
        "evidence_path": None,
    }])


def test_parses_structured_post_result_recommendation() -> None:
    parsed = parse_battle_recommendation(
        "A Water-type deck is recommended for this battle!\n"
        "Adjust your deck and try again.\nRecommended\n"
        "Mega Sharpedo ex Deck\n(Ruler of the Skies)\nTo My Decks\nTo Rental Decks"
    )

    assert parsed is not None
    assert parsed.recommended_type == "Water"
    assert parsed.recommended_deck_name == "Mega Sharpedo ex Deck (Ruler of the Skies)"
    assert parsed.confidence == 0.98


def register_vaporcuno(store: Store) -> None:
    store.register_owned_deck(
        "vaporcuno",
        None,
        ["Water"],
        verified=True,
        managed=False,
        slot_number=1,
        source="test_account_scan",
    )


def mark_recipe_exact(store: Store, recipe_id: str) -> None:
    with store.connect() as connection:
        connection.execute(
            """INSERT OR REPLACE INTO recipe_buildability(
                   recipe_id, status, missing_cards, unknown_cards, checked_at
               ) VALUES(?, 'exact', '[]', '[]', 'test')""",
            (recipe_id,),
        )


def test_store_seeds_recipes_but_not_account_ownership(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()

    assert store.owned_decks() == []
    assert store.get_account_profile()["status"] == "not_scanned"
    assert all(
        store.get_deck_recipe(recipe_id)["capture_status"] == "complete"
        for recipe_id in ("pbotfire", "pbotfight", "hoopa-ex-theme", "pbotdark")
    )


def test_resolver_selects_an_untried_owned_counter_and_avoids_blind_retry(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    register_vaporcuno(store)
    import_frontier(store)
    store.resolve_battle_work("test:advanced:frontier", "deferred", "first pass lost")
    store.record_battle_recommendation(
        "test:advanced:frontier",
        None,
        "Water",
        "Mega Sharpedo ex Deck (Ruler of the Skies)",
        "Water recommendation",
        0.98,
        "recommendation.png",
    )

    decision = StrategyResolver(store).resolve("test:advanced:frontier")
    assert decision is not None
    assert decision.deck_name == "vaporcuno"

    attempt_id = store.start_attempt(
        "test:advanced:frontier", "Test", "Advanced", "Frontier ex Deck (Test)", "vaporcuno", "auto"
    )
    store.finish_attempt(attempt_id, "loss", "loss.png")
    assert StrategyResolver(store).resolve("test:advanced:frontier") is None


def test_resolver_can_use_a_new_verified_managed_water_deck(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    register_vaporcuno(store)
    import_frontier(store)
    store.record_battle_recommendation(
        "test:advanced:frontier",
        None,
        "Water",
        "Mega Sharpedo ex Deck (Ruler of the Skies)",
        "Water recommendation",
        0.98,
        "recommendation.png",
    )
    store.register_owned_deck(
        "pbotwater",
        "mega-sharpedo-milotic-tournament",
        ["Water"],
        verified=True,
        managed=True,
        slot_number=21,
        source="pbot_managed",
    )

    decision = StrategyResolver(store).resolve("test:advanced:frontier")

    assert decision is not None
    assert decision.deck_name == "pbotwater"


def test_resolver_offers_complete_recipe_after_owned_counter_is_exhausted(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    mark_recipe_exact(store, "pbotwater-articuno")
    import_frontier(store)
    store.resolve_battle_work("test:advanced:frontier", "deferred", "first pass lost")
    store.record_battle_recommendation(
        "test:advanced:frontier",
        None,
        "Water",
        "Mega Sharpedo ex Deck (Ruler of the Skies)",
        "Water recommendation",
        0.98,
        "recommendation.png",
    )
    attempt_id = store.start_attempt(
        "test:advanced:frontier",
        "Test",
        "Advanced",
        "Frontier ex Deck (Test)",
        "vaporcuno",
        "auto",
    )
    store.finish_attempt(attempt_id, "loss", "loss.png")

    resolver = StrategyResolver(store)
    build = resolver.resolve_build("test:advanced:frontier")

    assert resolver.resolve("test:advanced:frontier") is None
    assert build is not None
    assert build.deck_name == "pbotwater"
    assert build.source_recipe_id == "mega-sharpedo-milotic-tournament"
    assert build.adapted_recipe_id == "pbotwater-articuno"


def test_resolver_will_not_build_from_a_type_only_recommendation(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    import_frontier(store)
    store.record_battle_recommendation(
        "test:advanced:frontier",
        None,
        "Water",
        None,
        "Water recommendation",
        0.86,
        "recommendation.png",
    )

    assert StrategyResolver(store).resolve_build("test:advanced:frontier") is None


def test_resolver_matches_each_shipped_managed_recipe_by_named_recommendation(
    tmp_path: Path,
) -> None:
    cases = (
        ("Fire", "Elite Deck (Mega Charizard Y ex)", "pbotfire"),
        ("Fighting", "Elite Deck (Mega Lucario ex)", "pbotfight"),
        ("Darkness", "Hoopa ex Deck (Ruler of the Skies)", "pbotdark"),
    )
    for index, (energy, recommended_name, deck_name) in enumerate(cases):
        store = Store(tmp_path / f"pbot-{index}.sqlite3")
        store.initialize()
        mark_recipe_exact(store, deck_name)
        battle_id = f"test:advanced:frontier-{index}"
        import_frontier(store, battle_id)
        store.record_battle_recommendation(
            battle_id,
            None,
            energy,
            recommended_name,
            f"{energy} recommendation",
            0.98,
            "recommendation.png",
        )
        with store.connect() as connection:
            connection.execute(
                "UPDATE owned_decks SET available = 0 WHERE display_name = ?",
                (deck_name,),
            )

        decision = StrategyResolver(store).resolve_build(battle_id)

        assert decision is not None
        assert decision.source_recipe_id == deck_name
        assert decision.adapted_recipe_id == deck_name
        assert decision.deck_name == deck_name


def test_resolver_refuses_a_recipe_without_exact_inventory_preflight(tmp_path: Path) -> None:
    store = Store(tmp_path / "blocked.sqlite3")
    store.initialize()
    import_frontier(store)
    store.record_battle_recommendation(
        "test:advanced:frontier",
        None,
        "Water",
        "Mega Sharpedo ex Deck (Ruler of the Skies)",
        "Water recommendation",
        0.98,
        "recommendation.png",
    )

    assert StrategyResolver(store).resolve_build("test:advanced:frontier") is None
