import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from discover_step_up import OcrLine
from select_rental_deck import deck_match_core, matching_deck_line


def test_matches_multiline_rental_deck_by_distinctive_title() -> None:
    lines = [
        OcrLine("Mega Charizard X ex", 0.99, 620, 667, 350, 44),
        OcrLine("Deck (Mega Shine)", 0.99, 638, 721, 319, 41),
    ]
    assert deck_match_core("Mega Charizard X ex Deck (Mega Shine)") == "mega charizard x ex"
    assert matching_deck_line(lines, "Mega Charizard X ex Deck (Mega Shine)") == lines[0]
    assert matching_deck_line(lines, "Milotic ex Deck (Everyday Wonders)") is None


def test_matches_wrapped_elite_rental_title() -> None:
    lines = [
        OcrLine("Elite Deck (Mega Lucario", 0.99, 68, 1803, 428, 41),
        OcrLine("ex)", 0.99, 251, 1850, 61, 44),
    ]
    assert deck_match_core("Elite Deck (Mega Lucario ex)") == "mega lucario"
    assert matching_deck_line(lines, "Elite Deck (Mega Lucario ex)") == lines[0]
