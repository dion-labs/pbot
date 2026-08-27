from pathlib import Path

from pbot.storage import Store


def test_store_initializes_and_persists_state(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    assert store.get_state()["status"] == "offline"

    store.set_state("ready", "Open Pokémon TCG Pocket", "emulator-5554")
    state = store.get_state()
    assert state["status"] == "ready"
    assert state["device_serial"] == "emulator-5554"


def test_events_round_trip_structured_payload(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    event_id = store.add_event("device.ready", "Device ready", "success", {"serial": "test-1"})
    event = store.recent_events(limit=1)[0]
    assert event["id"] == event_id
    assert event["payload"] == {"serial": "test-1"}


def test_empty_metrics_are_zero(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    assert store.metrics() == {
        "battles_total": 0,
        "battles_won": 0,
        "missions_total": 0,
        "missions_complete": 0,
        "attempts_total": 0,
    }


def test_guarded_attempt_lifecycle_updates_summary_once(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    store.set_progress_summary(10, 3, 30, 8)
    store.import_battles([
        {
            "id": "test:intermediate:frontier",
            "expansion": "Test",
            "difficulty": "Intermediate",
            "name": "Frontier Deck (Test)",
            "first_win": False,
            "missions_complete": 0,
            "missions_total": 3,
            "evidence_path": None,
        }
    ])

    attempt_id = store.start_attempt(
        "test:intermediate:frontier", "Test", "Intermediate", "Frontier Deck (Test)", "pilot", "auto"
    )
    outcome = store.finish_attempt(attempt_id, "win", "result.png", 2, 3)

    assert outcome["win_delta"] == 1
    assert outcome["mission_delta"] == 2
    assert store.metrics() == {
        "battles_total": 10,
        "battles_won": 4,
        "missions_total": 30,
        "missions_complete": 10,
        "attempts_total": 1,
    }
    assert store.pending_battles() == []


def test_loss_records_attempt_without_clearing_frontier(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    attempt_id = store.start_attempt(
        "test:intermediate:frontier", "Test", "Intermediate", "Frontier Deck (Test)", "pilot", "auto"
    )
    outcome = store.finish_attempt(attempt_id, "loss", "loss.png", 0, 3)

    assert outcome["win_delta"] == 0
    assert store.pending_battles()[0]["id"] == "test:intermediate:frontier"


def test_worker_claims_and_defers_without_blocking_other_expansions(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    store.import_battles([
        {
            "id": f"{expansion.lower()}:intermediate:frontier",
            "expansion": expansion,
            "difficulty": "Intermediate",
            "name": f"{expansion} Frontier Deck",
            "first_win": False,
            "missions_complete": 0,
            "missions_total": 3,
            "evidence_path": None,
        }
        for expansion in ("Alpha", "Beta")
    ])

    first = store.claim_next_battle(("Intermediate",))
    assert first and first["expansion"] == "Alpha"
    store.resolve_battle_work(str(first["id"]), "deferred", "needs another deck")
    deferred_pending = next(item for item in store.pending_battles() if item["id"] == first["id"])
    assert deferred_pending["work_state"] == "deferred"
    assert deferred_pending["reason"] == "needs another deck"
    second = store.claim_next_battle(("Intermediate",))
    assert second and second["expansion"] == "Beta"
    assert store.deferred_battles()[0]["id"] == first["id"]


def test_worker_recovers_interrupted_attempt_and_claim(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    store.import_battles([{
        "id": "alpha:intermediate:frontier",
        "expansion": "Alpha",
        "difficulty": "Intermediate",
        "name": "Alpha Frontier Deck",
        "first_win": False,
        "missions_complete": 0,
        "missions_total": 3,
        "evidence_path": None,
    }])
    claimed = store.claim_next_battle(("Intermediate",))
    assert claimed
    attempt_id = store.start_attempt(
        str(claimed["id"]), "Alpha", "Intermediate", "Alpha Frontier Deck", "pilot", "auto"
    )

    recovered = store.recover_interrupted_work()
    assert recovered == {"interrupted_attempts": 1, "released_claims": 1}
    reclaimed = store.claim_next_battle(("Intermediate",))
    assert reclaimed and reclaimed["id"] == claimed["id"]
    with store.connect() as connection:
        attempt = connection.execute("SELECT result, finished_at FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    assert attempt["result"] == "interrupted"
    assert attempt["finished_at"]


def test_reconciles_phone_confirmed_win_after_worker_interruption(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    store.set_progress_summary(10, 3, 30, 8)
    attempt_id = store.start_attempt(
        "test:intermediate:deck-test", "Test", "Intermediate", "Deck (Test)", "pilot", "auto"
    )
    store.recover_interrupted_work()

    outcome = store.reconcile_interrupted_win(
        attempt_id,
        {
            "id": "test:intermediate:toxapex-deck-test",
            "expansion": "Test",
            "difficulty": "Intermediate",
            "name": "Toxapex Deck (Test)",
            "first_win": True,
            "missions_complete": 2,
            "missions_total": 3,
            "evidence_path": "confirmed.png",
        },
        ("test:intermediate:toxape-deck-test",),
    )

    assert outcome["win_delta"] == 1
    assert outcome["mission_delta"] == 2
    assert store.metrics() == {
        "battles_total": 10,
        "battles_won": 4,
        "missions_total": 30,
        "missions_complete": 10,
        "attempts_total": 1,
    }
    with store.connect() as connection:
        attempt = connection.execute("SELECT battle_id, result FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        aliases = connection.execute("SELECT COUNT(*) count FROM battles WHERE name = 'Deck (Test)'").fetchone()
    assert attempt["battle_id"] == "test:intermediate:toxapex-deck-test"
    assert attempt["result"] == "win"
    assert aliases["count"] == 0


def test_reconciles_phone_confirmed_win_after_worker_error(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    store.set_progress_summary(10, 3, 30, 8)
    attempt_id = store.start_attempt(
        "test:intermediate:milotic", "Test", "Intermediate", "Milotic Deck", "pilot", "auto"
    )
    store.finish_attempt(attempt_id, "error", "timeout.png")

    outcome = store.reconcile_interrupted_win(
        attempt_id,
        {
            "id": "test:intermediate:milotic",
            "expansion": "Test",
            "difficulty": "Intermediate",
            "name": "Milotic Deck",
            "first_win": True,
            "missions_complete": 1,
            "missions_total": 3,
            "evidence_path": "victory.png",
        },
    )

    assert outcome["win_delta"] == 1
    assert outcome["mission_delta"] == 1
    with store.connect() as connection:
        attempt = connection.execute(
            "SELECT result, evidence_path FROM attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
    assert attempt["result"] == "win"
    assert attempt["evidence_path"] == "victory.png"


def test_reconciles_error_as_screen_confirmed_loss(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    attempt_id = store.start_attempt(
        "test:intermediate:frontier", "Test", "Intermediate", "Frontier Deck", "pilot", "auto"
    )
    store.finish_attempt(attempt_id, "error", "timeout.png")

    outcome = store.reconcile_error_as_loss(attempt_id, "defeat.png")

    assert outcome["result"] == "loss"
    with store.connect() as connection:
        attempt = connection.execute("SELECT result, evidence_path FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    assert attempt["result"] == "loss"
    assert attempt["evidence_path"] == "defeat.png"


def test_reconciles_error_as_screen_confirmed_tie(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    store.set_progress_summary(10, 3, 30, 8)
    attempt_id = store.start_attempt(
        "test:intermediate:frontier", "Test", "Intermediate", "Frontier Deck", "pilot", "auto"
    )
    store.finish_attempt(attempt_id, "error", "ocr-miss.png")

    outcome = store.reconcile_error_result(attempt_id, "tie", "tie.png", 2, 3)

    assert outcome["result"] == "tie"
    assert outcome["mission_delta"] == 2
    with store.connect() as connection:
        attempt = connection.execute("SELECT result, evidence_path FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    assert attempt["result"] == "tie"
    assert attempt["evidence_path"] == "tie.png"
    assert store.metrics()["missions_complete"] == 10


def test_reconciles_loss_from_an_interrupted_active_battle(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    battle_id = "test:advanced:resume"
    attempt_id = store.start_attempt(
        battle_id,
        "Test",
        "Advanced",
        "Resume Deck (Test)",
        "pbotwater",
        "auto",
    )
    store.recover_interrupted_work()

    recoverable = store.latest_recoverable_attempt(battle_id, "pbotwater")
    outcome = store.reconcile_error_result(attempt_id, "loss", "loss.png", 1, 4)

    assert recoverable is not None
    assert recoverable["id"] == attempt_id
    assert outcome["result"] == "loss"
    with store.connect() as connection:
        attempt = connection.execute(
            "SELECT result FROM attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
    assert attempt["result"] == "loss"
