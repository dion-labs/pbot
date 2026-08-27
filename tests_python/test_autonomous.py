from pathlib import Path

from pbot.autonomous import AutonomousFirstWinRunner, DeckBuildNeedsAttention
from pbot.device import DeviceError
from pbot.storage import Store


def mark_recipe_exact(store: Store, recipe_id: str) -> None:
    with store.connect() as connection:
        connection.execute(
            """INSERT OR REPLACE INTO recipe_buildability(
                   recipe_id, status, missing_cards, unknown_cards, checked_at
               ) VALUES(?, 'exact', '[]', '[]', 'test')""",
            (recipe_id,),
        )


def setup_deferred(store: Store, energy_type: str, deck_name: str | None = None) -> str:
    battle_id = "test:advanced:frontier"
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
    store.resolve_battle_work(battle_id, "deferred", "first pass lost")
    store.record_battle_recommendation(
        battle_id,
        None,
        energy_type,
        deck_name,
        f"{energy_type} recommendation",
        0.98 if deck_name else 0.86,
        "recommendation.png",
    )
    return battle_id


def test_autonomous_run_retries_a_known_counter_then_completes(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    store.register_owned_deck(
        "pbotfire",
        "pbotfire",
        ["Fire"],
        verified=True,
        managed=True,
        slot_number=18,
        source="test_account_scan",
    )
    battle_id = setup_deferred(store, "Fire")
    selected: list[tuple[str, str]] = []

    class WinningWorker:
        def __init__(self, deck_name: str, target_id: str) -> None:
            self.deck_name = deck_name
            self.target_id = target_id

        def run(self, limit: int) -> list[dict[str, object]]:
            selected.append((self.deck_name, self.target_id))
            attempt_id = store.start_attempt(
                battle_id, "Test", "Advanced", "Frontier ex Deck (Test)", self.deck_name, "auto"
            )
            store.finish_attempt(attempt_id, "win", "victory.png", 1, 4)
            store.resolve_battle_work(battle_id, "completed", "First win completed", attempt_id)
            return [{"battle_id": battle_id, "name": "Frontier", "result": "win", "attempt_id": attempt_id}]

    runner = AutonomousFirstWinRunner(
        store,
        lambda deck_name, target_id: WinningWorker(deck_name, target_id),
        ("Advanced",),
        lambda *_args: None,
    )
    result = runner.run()

    assert result["status"] == "completed"
    assert selected == [("pbotfire", battle_id)]
    assert store.latest_run_objective()["status"] == "completed"


def test_autonomous_run_reports_attention_after_known_counter_failed(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    battle_id = setup_deferred(store, "Water")
    attempt_id = store.start_attempt(
        battle_id, "Test", "Advanced", "Frontier ex Deck (Test)", "vaporcuno", "auto"
    )
    store.finish_attempt(attempt_id, "loss", "loss.png")

    runner = AutonomousFirstWinRunner(
        store,
        lambda *_args: (_ for _ in ()).throw(AssertionError("worker must not run")),
        ("Advanced",),
        lambda *_args: None,
    )
    result = runner.run()

    assert result["status"] == "needs_attention"
    assert result["unresolved"][0]["battle_id"] == battle_id
    assert store.get_state()["status"] == "needs_attention"


def test_autonomous_run_requests_reconnect_for_device_loss(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    store.register_owned_deck(
        "sheetmetal",
        None,
        ["Metal"],
        verified=True,
        managed=False,
        slot_number=10,
        source="test_account_scan",
    )
    battle_id = setup_deferred(
        store,
        "Metal",
        "Mega Metagross ex Deck (Ruler of the Skies)",
    )

    class DisconnectedWorker:
        def run(self, _limit: int) -> list[dict[str, object]]:
            raise DeviceError("device not found")

    runner = AutonomousFirstWinRunner(
        store,
        lambda _deck_name, _target_id: DisconnectedWorker(),
        ("Advanced",),
        lambda *_args: None,
    )
    result = runner.run()

    assert result["status"] == "needs_attention"
    assert result["handoff"] == "reconnect_device"
    assert store.latest_run_objective()["status"] == "needs_attention"
    assert store.get_state()["objective"].startswith("Reconnect and authorize")
    assert store.pending_battles()[0]["id"] == battle_id


def test_recovered_researched_retry_keeps_its_strategy(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    store.register_owned_deck(
        "sheetmetal",
        None,
        ["Metal"],
        verified=True,
        managed=False,
        slot_number=10,
        source="test_account_scan",
    )
    battle_id = setup_deferred(
        store,
        "Metal",
        "Mega Metagross ex Deck (Ruler of the Skies)",
    )
    store.resolve_battle_work(battle_id, "queued", "Recovered after interrupted worker")
    selected: list[str] = []

    class WinningWorker:
        def __init__(self, deck_name: str) -> None:
            self.deck_name = deck_name

        def run(self, _limit: int) -> list[dict[str, object]]:
            selected.append(self.deck_name)
            attempt_id = store.start_attempt(
                battle_id,
                "Test",
                "Advanced",
                "Frontier ex Deck (Test)",
                self.deck_name,
                "auto",
            )
            store.finish_attempt(attempt_id, "win", "victory.png", 1, 4)
            store.resolve_battle_work(battle_id, "completed", "First win completed", attempt_id)
            return [{"battle_id": battle_id, "result": "win", "attempt_id": attempt_id}]

    result = AutonomousFirstWinRunner(
        store,
        lambda deck_name, _target_id: WinningWorker(deck_name),
        ("Advanced",),
        lambda *_args: None,
    ).run()

    assert result["status"] == "completed"
    assert selected == ["sheetmetal"]


def test_autonomous_run_builds_a_matching_recipe_then_retries(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    mark_recipe_exact(store, "pbotwater-articuno")
    battle_id = setup_deferred(
        store,
        "Water",
        "Mega Sharpedo ex Deck (Ruler of the Skies)",
    )
    failed_attempt = store.start_attempt(
        battle_id,
        "Test",
        "Advanced",
        "Frontier ex Deck (Test)",
        "vaporcuno",
        "auto",
    )
    store.finish_attempt(failed_attempt, "loss", "loss.png")
    built: list[str] = []
    selected: list[str] = []

    def build(decision: object) -> dict[str, object]:
        built.append(decision.deck_name)
        store.register_owned_deck(
            decision.deck_name,
            decision.adapted_recipe_id,
            [decision.recommended_type],
            verified=True,
            managed=True,
            slot_number=8,
            source="test_constructor",
        )
        return {
            "status": "verified",
            "deck_name": decision.deck_name,
            "slot_number": 8,
            "recipe_id": decision.adapted_recipe_id,
        }

    class WinningWorker:
        def __init__(self, deck_name: str) -> None:
            self.deck_name = deck_name

        def run(self, limit: int) -> list[dict[str, object]]:
            selected.append(self.deck_name)
            attempt_id = store.start_attempt(
                battle_id,
                "Test",
                "Advanced",
                "Frontier ex Deck (Test)",
                self.deck_name,
                "auto",
            )
            store.finish_attempt(attempt_id, "win", "victory.png", 1, 4)
            store.resolve_battle_work(battle_id, "completed", "First win completed", attempt_id)
            return [{"battle_id": battle_id, "result": "win", "attempt_id": attempt_id}]

    runner = AutonomousFirstWinRunner(
        store,
        lambda deck_name, _target_id: WinningWorker(deck_name),
        ("Advanced",),
        lambda *_args: None,
        deck_builder=build,
    )
    result = runner.run()

    assert result["status"] == "completed"
    assert built == ["pbotwater"]
    assert selected == ["pbotwater"]
    assert result["builds"][0]["recipe_id"] == "pbotwater-articuno"
    assert store.latest_run_objective()["checkpoint"]["phase"] == "verify"


def test_recipe_build_blocker_is_durable_needs_attention(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    mark_recipe_exact(store, "pbotwater-articuno")
    battle_id = setup_deferred(
        store,
        "Water",
        "Mega Sharpedo ex Deck (Ruler of the Skies)",
    )
    failed_attempt = store.start_attempt(
        battle_id,
        "Test",
        "Advanced",
        "Frontier ex Deck (Test)",
        "vaporcuno",
        "auto",
    )
    store.finish_attempt(failed_attempt, "loss", "loss.png")

    runner = AutonomousFirstWinRunner(
        store,
        lambda *_args: (_ for _ in ()).throw(AssertionError("worker must not run")),
        ("Advanced",),
        lambda *_args: None,
        deck_builder=lambda _decision: (_ for _ in ()).throw(
            DeckBuildNeedsAttention("all deck slots are occupied")
        ),
    )
    result = runner.run()

    assert result["status"] == "needs_attention"
    assert result["build_blocker"]["deck_name"] == "pbotwater"
    assert result["build_blocker"]["message"] == "all deck slots are occupied"
    assert store.latest_run_objective()["checkpoint"]["phase"] == "build_deck"
    assert store.get_state()["status"] == "needs_attention"
