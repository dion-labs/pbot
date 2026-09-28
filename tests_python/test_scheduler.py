from pathlib import Path

import pytest

from pbot.scheduler import ContinuousScheduler
from pbot.storage import Store


def battle(expansion: str) -> dict[str, object]:
    return {
        "id": f"{expansion.lower()}:intermediate:frontier",
        "expansion": expansion,
        "difficulty": "Intermediate",
        "name": f"{expansion} Frontier Deck",
        "first_win": False,
        "missions_complete": 0,
        "missions_total": 3,
        "evidence_path": None,
    }


class CompletingWorker:
    def __init__(self, store: Store, definitions: dict[str, dict[str, object]]) -> None:
        self.store = store
        self.definitions = definitions

    def run(self, limit: int) -> list[dict[str, object]]:
        claimed = self.store.claim_next_battle(("Intermediate",))
        if not claimed:
            return []
        battle_id = str(claimed["id"])
        completed = {**self.definitions[battle_id], "first_win": True}
        self.store.import_battles([completed])
        self.store.resolve_battle_work(battle_id, "completed", "test")
        return [{"battle_id": battle_id, "result": "win"}]


class StalledWorker:
    def run(self, limit: int) -> list[dict[str, object]]:
        return []


def test_continuous_scheduler_runs_rounds_until_queue_is_exhausted(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    definitions = {item["id"]: item for item in (battle("Alpha"), battle("Beta"))}
    store.import_battles(list(definitions.values()))
    events: list[str] = []
    scheduler = ContinuousScheduler(
        store,
        CompletingWorker(store, definitions),
        ("Intermediate",),
        1,
        lambda kind, message, level, payload: events.append(kind),
    )

    summary = scheduler.run()

    assert summary["rounds"] == 2
    assert summary["exhausted"] is True
    assert len(summary["results"]) == 2
    assert scheduler.eligible() == []
    assert events == ["scheduler.round_started", "scheduler.round_started", "scheduler.completed"]


def test_continuous_scheduler_fails_if_a_round_makes_no_progress(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    store.import_battles([battle("Alpha")])
    scheduler = ContinuousScheduler(
        store,
        StalledWorker(),
        ("Intermediate",),
        10,
        lambda kind, message, level, payload: None,
    )

    with pytest.raises(RuntimeError, match="made no progress"):
        scheduler.run()


@pytest.mark.parametrize("hidden_by", ["other_difficulty", "deferred"])
def test_scheduler_does_not_exhaust_hidden_queued_work(tmp_path: Path, hidden_by: str) -> None:
    store = Store(tmp_path / "fixture.sqlite3")
    store.initialize()
    definitions = [{
        **battle("Synthetic"), "id": f"fictional:{i}", "name": f"Fictional {i:04}",
        "difficulty": "Beginner" if hidden_by == "other_difficulty" and i < 500 else "Intermediate",
    } for i in range(501)]
    store.import_battles(definitions)
    if hidden_by == "deferred":
        for item in definitions[:500]:
            store.resolve_battle_work(str(item["id"]), "deferred", "Fictional bounded handoff")
    scheduler = ContinuousScheduler(store, StalledWorker(), ("Intermediate",), 1, lambda *_: None)
    with pytest.raises(RuntimeError, match="made no progress"):
        scheduler.run()
