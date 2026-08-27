import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from discover_step_up import DiscoveryRun, OcrLine


def line(text: str) -> OcrLine:
    return OcrLine(text, 1.0, 0, 0, 100, 40)


def test_step_up_navigation_leaves_my_cards_through_solo_tab(tmp_path: Path) -> None:
    class FakeDevice:
        def __init__(self) -> None:
            self.frames = [
                [line("My Cards"), line("Binders"), line("Display Boards"), line("Decks")],
                [line("Step-Up Battle"), line("Beginner"), line("Intermediate")],
            ]
            self.taps: list[tuple[int, int]] = []

        def frame(self, _label: str) -> tuple[Path, list[OcrLine]]:
            return tmp_path / "frame.png", self.frames.pop(0)

        def tap(self, x: int, y: int) -> None:
            self.taps.append((x, y))

    device = FakeDevice()
    DiscoveryRun(device, tmp_path / "catalog.json").ensure_step_up_overview()

    assert device.taps == [(742, 2320)]


def test_step_up_navigation_leaves_pack_home_through_current_solo_tab(tmp_path: Path) -> None:
    class FakeDevice:
        def __init__(self) -> None:
            self.frames = [
                [line("Offering Rates"), line("Select other booster packs")],
                [line("Step-Up Battle"), line("Beginner"), line("Intermediate")],
            ]
            self.taps: list[tuple[int, int]] = []

        def frame(self, _label: str) -> tuple[Path, list[OcrLine]]:
            return tmp_path / "frame.png", self.frames.pop(0)

        def tap(self, x: int, y: int) -> None:
            self.taps.append((x, y))

    device = FakeDevice()
    DiscoveryRun(device, tmp_path / "catalog.json").ensure_step_up_overview()

    assert device.taps == [(742, 2320)]


def test_step_up_navigation_backs_out_of_retained_battle_rules(tmp_path: Path) -> None:
    class FakeDevice:
        def __init__(self) -> None:
            self.frames = [
                [line("Battle Rules"), line("Skarmory ex & Scizor Deck"), line("Battle!"), line("Auto Off")],
                [line("Step-Up Battle"), line("Beginner"), line("Intermediate")],
            ]
            self.back_presses = 0

        def frame(self, _label: str) -> tuple[Path, list[OcrLine]]:
            return tmp_path / "frame.png", self.frames.pop(0)

        def press_back(self) -> None:
            self.back_presses += 1

    device = FakeDevice()
    DiscoveryRun(device, tmp_path / "catalog.json").ensure_step_up_overview()

    assert device.back_presses == 1
