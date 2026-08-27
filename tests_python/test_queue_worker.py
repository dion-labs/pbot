import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_queue_worker import EXPERT_DEFAULT_DECK, default_deck_name


def test_expert_uses_owned_aeroape_default() -> None:
    assert default_deck_name(("Expert",)) == EXPERT_DEFAULT_DECK
    assert default_deck_name(("Advanced",)) == "selected deck"
    assert default_deck_name(("Intermediate", "Advanced", "Expert")) == "selected deck"
