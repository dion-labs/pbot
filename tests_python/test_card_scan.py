import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discover_step_up import OcrLine  # noqa: E402
from pbot.card_inventory import CardTarget  # noqa: E402
from scan_cards import (  # noqa: E402
    adb_search_text,
    choose_variant_line,
    collection_total,
    quantity_near_candidate,
)


def line(text: str, x: int, y: int, width: int = 180, height: int = 35) -> OcrLine:
    return OcrLine(text, 1.0, x, y, width, height)


def test_collection_total_reads_the_fixed_my_cards_counter() -> None:
    lines = [line("My Cards", 400, 200), line("5", 160, 646, 24, 31)]

    assert collection_total(lines) == 5


def test_adb_search_text_preserves_meaningful_card_name_punctuation() -> None:
    assert adb_search_text("Chien-Pao ex") == "Chien-Pao%sex"
    assert adb_search_text("Professor's Research") == "Professor"


def test_variant_identity_hint_selects_the_matching_print() -> None:
    lines = [
        line("Galarian Linoone", 70, 792),
        line("Galarian Linoone", 390, 792),
        line("Rear Kick", 143, 1065, 82, 17),
        line("Night Slash", 475, 1057, 95, 21),
    ]

    selected, reason = choose_variant_line(
        lines,
        CardTarget("B4-096", "Galarian Linoone", 2, "Night Slash"),
    )

    assert selected is not None
    assert selected.x == 390
    assert "Night Slash" in reason


def test_multiple_unidentified_prints_remain_ambiguous() -> None:
    selected, reason = choose_variant_line(
        [line("Feebas", 70, 792), line("Feebas", 390, 792)],
        CardTarget("A4a-021", "Feebas", 2),
    )

    assert selected is None
    assert "Multiple prints" in reason


def test_identity_hint_can_anchor_a_tile_when_its_title_is_unreadable() -> None:
    selected, reason = choose_variant_line(
        [line("Shadow Bullet", 74, 1050, 140, 24)],
        CardTarget("B4-103", "Hoopa ex", 1, "Shadow Bullet"),
    )

    assert selected is not None
    assert selected.y == 850
    assert "without a readable title" in reason


def test_quantity_is_read_from_the_matching_tile_not_an_attack_value() -> None:
    candidate = line("Poochyena", 475, 858, 95, 21)
    lines = [
        line("20", 319, 1065, 27, 20),
        line("4", 438, 1180, 20, 24),
        line("1", 768, 1180, 20, 24),
    ]

    assert quantity_near_candidate(lines, candidate, 17) == 4
