from pathlib import Path

import pytest

from pbot.deck_recipe import MEGA_SHARPEDO_MILOTIC, PBOT_WATER_ARTICUNO
from pbot.managed_deck import (
    DeckReadback,
    ImportSaveResult,
    ManagedDeckConstructor,
    ManagedDeckError,
    ManagedDeckPlan,
)
from pbot.storage import Store


def plan(qr_image: Path | None = None) -> ManagedDeckPlan:
    return ManagedDeckPlan.from_recipes(
        MEGA_SHARPEDO_MILOTIC,
        PBOT_WATER_ARTICUNO,
        deck_name="pbotwater",
        slot_number=21,
        qr_image=qr_image,
    )


def readback(*, name: str = "pbotwater", count: int = 20, owned: bool = True) -> DeckReadback:
    return DeckReadback(
        deck_name=name,
        card_count=count,
        energy_types=("Water",),
        ownership_valid=owned,
        detail_screen=True,
        evidence_path="verified.png",
        screen_text="pbotwater Energy 20/20 Edit",
    )


class FakePort:
    def __init__(self, existing: DeckReadback | None, saves: list[ImportSaveResult]) -> None:
        self.existing = existing
        self.saves = saves
        self.calls: list[object] = []

    def inspect_slot(self, slot_number: int, expected_name: str) -> DeckReadback | None:
        self.calls.append(("inspect", slot_number, expected_name))
        return self.existing

    def import_qr(self, build_plan: ManagedDeckPlan) -> str:
        self.calls.append(("import", build_plan.source_recipe.id))
        return "imported.png"

    def rename_draft(self, deck_name: str) -> None:
        self.calls.append(("rename", deck_name))

    def attempt_save(self) -> ImportSaveResult:
        self.calls.append("save")
        return self.saves.pop(0)

    def apply_substitutions(self, substitutions: object) -> str:
        values = tuple(substitutions)
        self.calls.append(("substitute", values))
        return "substituted.png"

    def read_back(self, slot_number: int, expected_name: str) -> DeckReadback:
        self.calls.append(("readback", slot_number, expected_name))
        return readback()


def test_plan_delta_is_fully_declared() -> None:
    build_plan = plan()

    assert [item.to_dict() for item in build_plan.substitutions] == [
        {
            "missing_card_id": "B4-035",
            "missing_card_name": "Mega Sharpedo ex",
            "replacement_card_id": "A1-084",
            "replacement_card_name": "Articuno ex",
            "quantity": 1,
        }
    ]


def test_existing_valid_slot_is_read_only_and_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    port = FakePort(readback(), [])

    outcome = ManagedDeckConstructor(port, store).run(plan())

    assert outcome.already_present is True
    assert outcome.effective_recipe_id == "pbotwater-articuno"
    assert port.calls == [("inspect", 21, "pbotwater")]
    assert store.owned_decks("Water")[0]["display_name"] == "pbotwater"


def test_ownership_failure_applies_only_declared_substitution(tmp_path: Path) -> None:
    qr = tmp_path / "source.png"
    qr.write_bytes(b"png fixture")
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    port = FakePort(
        None,
        [ImportSaveResult.OWNERSHIP_FAILURE, ImportSaveResult.SAVED],
    )

    outcome = ManagedDeckConstructor(port, store).run(plan(qr))

    assert outcome.effective_recipe_id == "pbotwater-articuno"
    assert len(outcome.used_substitutions) == 1
    assert [call[0] if isinstance(call, tuple) else call for call in port.calls] == [
        "inspect",
        "import",
        "rename",
        "save",
        "substitute",
        "save",
        "readback",
    ]


def test_readback_refuses_wrong_name_or_card_count(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    port = FakePort(readback(name="not-our-slot", count=19), [])

    with pytest.raises(ManagedDeckError, match="expected deck name.*expected 20/20"):
        ManagedDeckConstructor(port, store).run(plan())

    assert store.owned_decks("Water") == []


def test_absent_slot_requires_a_local_qr_before_any_import(tmp_path: Path) -> None:
    store = Store(tmp_path / "pbot.sqlite3")
    store.initialize()
    port = FakePort(None, [])

    with pytest.raises(ManagedDeckError, match="Source QR image is required"):
        ManagedDeckConstructor(port, store).run(plan())

    assert port.calls == [("inspect", 21, "pbotwater")]
