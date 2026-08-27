import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discover_step_up import OcrLine  # noqa: E402
from scan_account import slot_is_unusable, visible_slot  # noqa: E402


def line(text: str, x: int, y: int, *, height: int = 100) -> OcrLine:
    return OcrLine(text, 1.0, x, y, 120, height)


def test_visible_slot_accepts_leading_zeroes() -> None:
    assert visible_slot([line("06", 80, 700)], 6).text == "06"


def test_visible_slot_infers_a_faded_tile_from_its_row_partner() -> None:
    inferred = visible_slot([line("06", 80, 700)], 7)

    assert inferred is not None
    assert inferred.text == "07"
    assert inferred.x >= 480
    assert inferred.y == 700


def test_unusable_marker_is_scoped_to_the_target_tile() -> None:
    left = line("06", 80, 700)
    right = visible_slot([left], 7)
    lines = [left, line("Not usable", 620, 930, height=50)]

    assert right is not None
    assert slot_is_unusable(lines, right) is True
    assert slot_is_unusable(lines, left) is False
