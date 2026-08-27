from pathlib import Path

from pbot.recommendation_backfill import (
    backfill_pending_recommendations,
    followup_evidence_paths,
)
from pbot.storage import Store


def setup_deferred(store: Store, evidence_path: Path) -> tuple[str, int]:
    battle_id = "test:advanced:frontier"
    attempt_id = store.start_attempt(
        battle_id,
        "Test",
        "Advanced",
        "Frontier ex Deck (Test)",
        "selected deck",
        "auto",
    )
    store.finish_attempt(attempt_id, "loss", str(evidence_path))
    store.resolve_battle_work(battle_id, "deferred", "first pass lost", attempt_id)
    return battle_id, attempt_id


def test_followup_evidence_paths_are_bounded_and_sequenced(tmp_path: Path) -> None:
    evidence = tmp_path / "0048-pilot-frontier-100.png"
    evidence.touch()
    expected = tmp_path / "0051-pilot-frontier-121.png"
    expected.touch()
    (tmp_path / "0054-pilot-other-battle-150.png").touch()

    assert followup_evidence_paths(evidence, limit=3) == [expected]


def test_backfill_recovers_and_persists_a_saved_recommendation(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    evidence = tmp_path / "0048-pilot-frontier-100.png"
    evidence.touch()
    recommendation = tmp_path / "0052-pilot-frontier-130.png"
    recommendation.touch()
    battle_id, attempt_id = setup_deferred(store, evidence)
    seen: list[Path] = []

    def recognize(path: Path) -> str:
        seen.append(path)
        return (
            "A Fire-type deck is recommended for this battle!\n"
            "Recommended\nElite Deck (Mega\nCharizard Y ex)\nTo My Decks"
        )

    outcome = backfill_pending_recommendations(store, recognize)

    assert seen == [recommendation]
    assert outcome["captured_count"] == 1
    captured = store.latest_battle_recommendation(battle_id)
    assert captured is not None
    assert captured["attempt_id"] == attempt_id
    assert captured["recommended_type"] == "Fire"
    assert captured["recommended_deck_name"] == "Elite Deck (Mega Charizard Y ex)"
    assert captured["evidence_path"] == str(recommendation)


def test_backfill_does_not_reprocess_a_battle_with_structured_data(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    evidence = tmp_path / "0010-pilot-frontier-100.png"
    evidence.touch()
    battle_id, attempt_id = setup_deferred(store, evidence)
    store.record_battle_recommendation(
        battle_id,
        attempt_id,
        "Water",
        "Milotic ex Deck (Everyday Wonders)",
        "saved",
        0.98,
        "saved.png",
    )

    outcome = backfill_pending_recommendations(
        store,
        lambda _path: (_ for _ in ()).throw(AssertionError("must not OCR")),
    )

    assert outcome["captured_count"] == 0
    assert outcome["checked_frames"] == 0
