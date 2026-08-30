import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from discover_step_up import OcrLine
from select_owned_deck import find_owned_deck, owned_deck_tap


def test_maps_owned_deck_labels_to_card_centers() -> None:
    assert owned_deck_tap(187, 1132) == (270, 1132)
    assert owned_deck_tap(723, 1132) == (810, 1132)
    assert owned_deck_tap(210, 1900) == (270, 1850)
    assert owned_deck_tap(720, 500) == (810, 600)


class FakeScrollableSelector:
    def __init__(self) -> None:
        self.page = 0
        self.swipes = 0
        self.gestures: list[tuple[int, int, int, int]] = []

    def frame(self, _label: str) -> tuple[Path, list[OcrLine]]:
        names = (("vaporcuno", "aeroape"), ("megachariy", "photfire"))[min(self.page, 1)]
        lines = [
            OcrLine("Battle Rules", 1, 100, 100, 100, 30),
            OcrLine("Select a Deck", 1, 300, 400, 300, 40),
            OcrLine("My Decks", 1, 200, 2040, 160, 40),
            OcrLine("Rental Decks", 1, 680, 2040, 210, 40),
            OcrLine(names[0], 1, 180, 1100, 180, 40),
            OcrLine(names[1], 1, 720, 1100, 180, 40),
        ]
        return Path("selector.png"), lines

    def swipe(self, x1: int, y1: int, x2: int, y2: int, _duration: int) -> None:
        self.page = 1
        self.swipes += 1
        self.gestures.append((x1, y1, x2, y2))


def test_finds_owned_deck_beyond_initial_viewport() -> None:
    device = FakeScrollableSelector()

    match = find_owned_deck(device, "pbotfire")

    assert match is not None
    assert match.text == "photfire"
    assert device.swipes == 1
    assert abs(device.gestures[0][1] - device.gestures[0][3]) <= 500


class FakeSelectorEndpoint:
    def __init__(self) -> None:
        self.swipes = 0

    def frame(self, _label: str) -> tuple[Path, list[OcrLine]]:
        return Path("selector.png"), [
            OcrLine("Battle Rules", 1, 100, 100, 100, 30),
            OcrLine("Select a Deck", 1, 300, 400, 300, 40),
            OcrLine("My Decks", 1, 200, 2040, 160, 40),
            OcrLine("Rental Decks", 1, 680, 2040, 210, 40),
            OcrLine("19", 1, 70, 600, 120, 50),
            OcrLine("pbotfight", 1, 160, 1000, 220, 40),
            OcrLine("20", 1, 560, 600, 120, 50),
            OcrLine("pbotdark", 1, 650, 1000, 220, 40),
            OcrLine("21", 1, 70, 1350, 120, 50),
            OcrLine("pbotwater", 1, 160, 1750, 220, 40),
        ]

    def swipe(self, *_args: object) -> None:
        self.swipes += 1


def test_stops_overscrolling_at_repeated_selector_endpoints() -> None:
    device = FakeSelectorEndpoint()

    assert find_owned_deck(device, "missing deck") is None
    assert device.swipes <= 6


class FakeLastSlotSelector:
    def frame(self, _label: str) -> tuple[Path, list[OcrLine]]:
        return Path("selector.png"), [
            OcrLine("Battle Rules", 1, 100, 100, 100, 30),
            OcrLine("Select a Deck", 1, 300, 400, 300, 40),
            OcrLine("My Decks", 1, 200, 2040, 160, 40),
            OcrLine("Rental Decks", 1, 680, 2040, 210, 40),
            OcrLine("21", 1, 65, 1575, 146, 42),
        ]

    def swipe(self, *_args: object) -> None:
        raise AssertionError("visible managed slot should not require a swipe")


def test_finds_a_managed_last_slot_when_its_name_is_below_the_fixed_bar() -> None:
    match = find_owned_deck(FakeLastSlotSelector(), "pbotwater", 21)

    assert match is not None
    assert match.text == "pbotwater"
    assert owned_deck_tap(match.x, match.center_y) == (270, 1596)


class FakePartiallyHiddenRightSlotSelector:
    def frame(self, _label: str) -> tuple[Path, list[OcrLine]]:
        return Path("selector.png"), [
            OcrLine("Battle Rules", 1, 100, 100, 100, 30),
            OcrLine("Select a Deck", 1, 300, 400, 300, 40),
            OcrLine("My Decks", 1, 200, 2040, 160, 40),
            OcrLine("Rental Decks", 1, 680, 2040, 210, 40),
            # OCR can see the slot number immediately above the fixed bar,
            # but its center is still just above the row-mapping threshold.
            # The large glyph's box begins left of the 540px column boundary,
            # although its center belongs to the right-hand card.
            OcrLine("18", 1, 500, 1450, 146, 42),
        ]

    def swipe(self, *_args: object) -> None:
        raise AssertionError("visible managed slot should not require a swipe")


def test_hidden_bottom_right_slot_maps_to_bottom_card_center() -> None:
    match = find_owned_deck(FakePartiallyHiddenRightSlotSelector(), "pbotfire", 18)

    assert match is not None
    assert match.text == "pbotfire"
    assert owned_deck_tap(match.x, match.center_y) == (810, 1541)


class FakeLongNameUpperRightSelector:
    def frame(self, _label: str) -> tuple[Path, list[OcrLine]]:
        return Path("selector.png"), [
            OcrLine("Battle Rules", 1, 100, 100, 100, 30),
            OcrLine("Select a Deck", 1, 300, 400, 300, 40),
            OcrLine("My Decks", 1, 200, 2040, 160, 40),
            OcrLine("Rental Decks", 1, 680, 2040, 210, 40),
            OcrLine("16", 1, 581, 963, 166, 119),
            # Real selector evidence placed this label just across the generic
            # lower-row threshold even though it belongs to slot 16 above.
            OcrLine("mega blaziken and en'", 1, 591, 1493, 391, 44),
        ]

    def swipe(self, *_args: object) -> None:
        raise AssertionError("visible requested deck should not require a swipe")


def test_ambiguous_long_name_uses_its_slot_number_fallback() -> None:
    match = find_owned_deck(
        FakeLongNameUpperRightSelector(),
        "mega blaziken and ente",
        16,
    )

    assert match is not None
    assert owned_deck_tap(match.x, match.center_y) == (810, 1022)


class FakeVisibleBottomManagedDeckSelector:
    def frame(self, _label: str) -> tuple[Path, list[OcrLine]]:
        return Path("selector.png"), [
            OcrLine("Battle Rules", 1, 194, 194, 190, 31),
            OcrLine("Select a Deck", 1, 346, 412, 391, 51),
            OcrLine("19", 1, 78, 1360, 153, 105),
            OcrLine("20", 1, 577, 1354, 170, 116),
            OcrLine("pbotfight", 1, 200, 1884, 166, 44),
            OcrLine("pbotdark", 1, 717, 1884, 163, 41),
            OcrLine("My Decks", 1, 211, 2051, 163, 41),
            OcrLine("Rental Decks", 1, 679, 2051, 214, 34),
        ]

    def swipe(self, *_args: object) -> None:
        raise AssertionError("visible requested deck should not require a swipe")


def test_visible_bottom_managed_deck_taps_card_body_not_slot_header() -> None:
    match = find_owned_deck(FakeVisibleBottomManagedDeckSelector(), "pbotfight", 19)

    assert match is not None
    assert owned_deck_tap(match.x, match.center_y) == (270, 1850)
