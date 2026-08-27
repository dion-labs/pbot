from pathlib import Path

import pytest

from pbot.card_inventory import (
    CardInventoryBootstrapper,
    CardObservation,
    evaluate_recipe,
    recipe_card_targets,
)
from pbot.deck_recipe import PBOT_DARK, PBOT_WATER_ARTICUNO
from pbot.storage import Store


class FakeCardPort:
    def __init__(self, observations: list[CardObservation]) -> None:
        self.observations = {item.card_id: item for item in observations}
        self.scanned: list[str] = []

    def scan_cards(self, targets):
        self.scanned.extend(target.card_id for target in targets)
        return [self.observations[target.card_id] for target in targets if target.card_id in self.observations]


def observation_for(target, quantity: int | None = 2, status: str = "verified"):
    return CardObservation(
        target.card_id,
        target.name,
        quantity,
        status,
        f"{target.card_id}.png",
        target.identity_hint,
    )


def test_targets_merge_shared_cards_by_stable_id() -> None:
    targets = recipe_card_targets()

    assert len(targets) == len({target.card_id for target in targets})
    assert next(target for target in targets if target.card_id == "B4-096").identity_hint == "Night Slash"
    assert next(target for target in targets if target.card_id == "B2-099").identity_hint == "Rear Kick"
    assert next(target for target in targets if target.card_id == "B4-034").identity_hint == "Sharp Fang"
    assert next(target for target in targets if target.card_id == "P-A-005").identity_hint == "random Basic"
    assert next(target for target in targets if target.card_id == "P-A-005").required_quantity == 2


def test_recipe_evaluation_is_exact_only_when_every_quantity_is_known() -> None:
    targets = {target.card_id: target for target in recipe_card_targets((PBOT_DARK,))}
    observations = [observation_for(target) for target in targets.values()]

    assert evaluate_recipe(PBOT_DARK, observations)["status"] == "exact"

    observations[0] = observation_for(next(iter(targets.values())), None, "ambiguous")
    assert evaluate_recipe(PBOT_DARK, observations)["status"] == "unknown"


def test_recipe_evaluation_records_a_verified_shortage() -> None:
    targets = {target.card_id: target for target in recipe_card_targets((PBOT_WATER_ARTICUNO,))}
    observations = [observation_for(target) for target in targets.values()]
    sharpedo = targets["B4-035"]
    observations = [
        observation_for(target, 0, "missing")
        if target.card_id == sharpedo.card_id
        else observation_for(target)
        for target in targets.values()
    ]

    result = evaluate_recipe(PBOT_WATER_ARTICUNO, observations)

    assert result["status"] == "blocked"
    assert result["missing_cards"] == [{
        "card_id": "B4-035",
        "name": "Mega Sharpedo ex",
        "required": 1,
        "owned": 0,
    }]


def test_complete_scan_atomically_persists_cards_and_buildability(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    targets = recipe_card_targets()
    observations = [observation_for(target) for target in targets]

    result = CardInventoryBootstrapper(store, FakeCardPort(observations)).run("device-1")

    assert result["profile"]["status"] == "ready"
    assert result["profile"]["target_count"] == len(targets)
    assert result["profile"]["known_count"] == len(targets)
    assert len(store.owned_cards()) == len(targets)
    assert all(item["status"] == "exact" for item in store.recipe_buildability())


def test_incomplete_scan_does_not_replace_last_complete_inventory(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    targets = recipe_card_targets()
    complete = [observation_for(target) for target in targets]
    CardInventoryBootstrapper(store, FakeCardPort(complete)).run("device-1")

    with pytest.raises(ValueError, match="exactly one observation"):
        CardInventoryBootstrapper(store, FakeCardPort(complete[:-1])).run("device-1")
    store.fail_card_scan("device-1", "interrupted")

    assert len(store.owned_cards()) == len(targets)
    assert store.get_card_inventory_profile()["status"] == "needs_attention"


def test_interrupted_scan_resumes_from_durable_per_card_checkpoints(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    targets = recipe_card_targets()
    first = observation_for(targets[0])
    store.begin_card_scan("device-1", len(targets))
    store.save_card_scan_checkpoint("device-1", first.to_dict())
    store.fail_card_scan("device-1", "USB disconnected")
    port = FakeCardPort([observation_for(target) for target in targets])

    result = CardInventoryBootstrapper(store, port).run("device-1")

    assert result["profile"]["status"] == "ready"
    assert targets[0].card_id not in port.scanned
    assert len(port.scanned) == len(targets) - 1
    assert store.card_scan_checkpoints("device-1") == []
