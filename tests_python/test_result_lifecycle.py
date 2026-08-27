import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from discover_step_up import BattleObservation
from run_first_pass import FirstPassPilot


class FakeLifecycleDevice:
    def __init__(self) -> None:
        self.backed_out = False
        self.back_presses = 0

    def tap(self, *_args: int) -> None:
        pass

    def press_back(self) -> None:
        self.backed_out = True
        self.back_presses += 1


class FakeLifecycleStore:
    def add_event(self, *_args: object) -> None:
        pass


def test_tie_returns_from_battle_rules_to_list_without_timing_out() -> None:
    pilot = FirstPassPilot.__new__(FirstPassPilot)
    pilot.device = FakeLifecycleDevice()
    pilot.store = FakeLifecycleStore()
    pilot.timeout = 1
    pilot.poll_interval = 0
    frames = iter(
        (
            (Path("summary.png"), "Tie\nTurns played\nTap to Proceed", "summary"),
            (Path("tie.png"), "Tie\nTap to Proceed", "tie"),
        )
    )

    def current_screen(_label: str) -> tuple[Path, str, str]:
        try:
            return next(frames)
        except StopIteration:
            if pilot.device.backed_out:
                return Path("list.png"), "Step-Up Battle\nAdvanced\nExpansions", "battle_list"
            return Path("rules.png"), "Battle Rules\nBattle!\nAuto Off", "prebattle"

    pilot.current_screen = current_screen
    target = BattleObservation(
        id="mega-sharpedo",
        expansion="Ruler of the Skies",
        difficulty="Advanced",
        name="Mega Sharpedo ex Deck (Ruler of the Skies)",
        first_win=False,
        missions_complete=2,
        missions_total=4,
        evidence_path="",
    )

    result, evidence = pilot.play_to_result(target, 186, already_active=True)

    assert result == "tie"
    assert evidence == Path("summary.png")
    assert pilot.device.back_presses == 1
