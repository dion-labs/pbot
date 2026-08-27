from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from pbot.managed_deck import (
    DARKNESS_SYMBOL_MASK,
    WATER_SYMBOL_MASK,
    active_battle_likely,
    readback_from_observations,
    visible_energy_types,
)


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int


def line(text: str, *, x: int = 20, y: int = 100) -> OcrLine:
    return OcrLine(text, 1.0, x, y, 200, 40)


def energy_fixture(tmp_path: Path, *energies: str) -> Path:
    """Build a private-data-free facsimile of the fixed energy-icon panel."""
    image = Image.new("RGB", (1080, 2340), "white")
    draw = ImageDraw.Draw(image)
    colors = {
        "Grass": (35, 190, 110),
        "Metal": (175, 175, 175),
        "Psychic": (185, 45, 205),
        "Water": (30, 180, 220),
        "Darkness": (30, 180, 220),
    }
    masks = {"Water": WATER_SYMBOL_MASK, "Darkness": DARKNESS_SYMBOL_MASK}
    for position, energy in enumerate(energies):
        left = 82 + position * 78
        top = 742
        scale = 4
        draw.rectangle(
            (left, top, left + 16 * scale - 1, top + 16 * scale - 1),
            fill=colors[energy],
        )
        mask = masks.get(energy, 0)
        for index in range(16 * 16):
            if mask & (1 << index):
                x = left + (index % 16) * scale
                y = top + (index // 16) * scale
                draw.rectangle((x, y, x + scale - 1, y + scale - 1), fill=(25, 25, 25))
    path = tmp_path / "energy-panel.png"
    image.save(path)
    return path


def test_water_energy_glyph_is_read_from_synthetic_evidence(tmp_path: Path) -> None:
    evidence = energy_fixture(tmp_path, "Water")

    assert visible_energy_types(evidence, ("Water",)) == ("Water",)


def test_neutral_metal_energy_glyph_is_read_from_synthetic_evidence(tmp_path: Path) -> None:
    evidence = energy_fixture(tmp_path, "Metal")

    assert visible_energy_types(evidence, ("Metal",)) == ("Metal",)


def test_grass_glyph_is_read_from_synthetic_evidence(tmp_path: Path) -> None:
    evidence = energy_fixture(tmp_path, "Grass")

    assert visible_energy_types(evidence, ("Grass",)) == ("Grass",)


def test_darkness_symbol_is_not_confused_with_the_water_ring(tmp_path: Path) -> None:
    evidence = energy_fixture(tmp_path, "Darkness")

    assert visible_energy_types(evidence, ("Water", "Darkness")) == ("Darkness",)


def test_two_energy_symbols_are_classified_independently(tmp_path: Path) -> None:
    evidence = energy_fixture(tmp_path, "Darkness", "Psychic")

    assert visible_energy_types(evidence, ("Water", "Darkness", "Psychic")) == (
        "Darkness",
        "Psychic",
    )


def test_readback_requires_owned_detail_signatures(tmp_path: Path) -> None:
    evidence = energy_fixture(tmp_path, "Water")
    observed = readback_from_observations(
        evidence,
        [line("pbotwater"), line("Energy", y=500), line("20/20", y=820), line("Edit", y=830)],
        "pbotwater",
        ("Water",),
    )

    assert observed.deck_name == "pbotwater"
    assert observed.card_count == 20
    assert observed.energy_types == ("Water",)
    assert observed.ownership_valid is True
    assert observed.detail_screen is True


def test_collection_card_rules_do_not_look_like_an_active_battle() -> None:
    assert active_battle_likely(
        "My Cards\nDisplay Boards\nDecks\nAt any time during your turn, you may discard this card"
    ) is False
    assert active_battle_likely("Auto Battle\nYour Turn\nBattle Log\nConcede") is True
