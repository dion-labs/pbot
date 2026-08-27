import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from discover_step_up import BattleObservation, OcrLine
from run_first_pass import FirstPassPilot, deck_name_visible, owned_deck_tap


def test_maps_requested_owned_deck_labels_to_card_centers() -> None:
    assert owned_deck_tap(187, 1132) == (270, 1132)
    assert owned_deck_tap(723, 1132) == (810, 1132)
    assert owned_deck_tap(210, 1900) == (270, 1850)
    assert owned_deck_tap(720, 500) == (810, 600)


def test_selected_deck_confirmation_tolerates_one_ocr_substitution() -> None:
    assert deck_name_visible("pbotfire", "Recommended\n18\nphotfire\nBattle!")
    assert not deck_name_visible("pbotfire", "Recommended\n04\naeroape\nBattle!")


class FakeDeckSwitchDevice:
    def __init__(self) -> None:
        self.mode = "prebattle"
        self.selected = "aeroape"

    def frame(self, _label: str) -> tuple[Path, list[OcrLine]]:
        if self.mode == "selector":
            texts = ("Battle Rules", "Select a Deck", "My Decks", "Rental Decks", "pbotfire")
        else:
            texts = ("Battle Rules", "Vespiquen ex Deck", self.selected, "Battle!", "Auto On")
        return Path("frame.png"), [
            OcrLine(text, 1, 720 if text == "pbotfire" else 100, 1100 + index * 40, 180, 30)
            for index, text in enumerate(texts)
        ]

    def tap(self, x: int, y: int) -> None:
        if (x, y) == (540, 1750):
            self.mode = "selector"
        elif (x, y) == (800, 2200):
            self.mode = "prebattle"
            self.selected = "pbotfire"

    def swipe(self, *_args: int) -> None:
        pass


class FakeStore:
    def add_event(self, *_args: object) -> None:
        pass


def test_prepare_battle_switches_from_persisted_deck_to_requested_owned_deck() -> None:
    pilot = FirstPassPilot.__new__(FirstPassPilot)
    pilot.device = FakeDeckSwitchDevice()
    pilot.store = FakeStore()
    pilot.deck_name = "pbotfire"
    target = BattleObservation(
        id="vespiquen",
        expansion="Ruler of the Skies",
        difficulty="Advanced",
        name="Vespiquen ex Deck (Ruler of the Skies)",
        first_win=False,
        missions_complete=0,
        missions_total=4,
        evidence_path="",
    )

    pilot.prepare_battle(target)

    assert pilot.device.selected == "pbotfire"
