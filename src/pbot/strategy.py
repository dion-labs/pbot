from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .executor import normalize_game_label
from .storage import Store


ENERGY_TYPES = (
    "Grass",
    "Fire",
    "Water",
    "Lightning",
    "Psychic",
    "Fighting",
    "Darkness",
    "Metal",
    "Dragon",
    "Colorless",
)


@dataclass(frozen=True)
class ParsedRecommendation:
    recommended_type: str | None
    recommended_deck_name: str | None
    confidence: float
    source_text: str


@dataclass(frozen=True)
class StrategyDecision:
    battle_id: str
    deck_name: str
    recommended_type: str
    recommended_deck_name: str | None
    reason: str
    prior_attempts: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BuildStrategyDecision:
    battle_id: str
    source_recipe_id: str
    adapted_recipe_id: str
    deck_name: str
    recommended_type: str
    recommended_deck_name: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


KNOWN_RECIPE_BUILDS = (
    {
        "recommended_type": "Water",
        "recommended_name_marker": "mega sharpedo ex deck",
        "source_recipe_id": "mega-sharpedo-milotic-tournament",
        "adapted_recipe_id": "pbotwater-articuno",
        "deck_name": "pbotwater",
    },
    {
        "recommended_type": "Fire",
        "recommended_name_marker": "elite deck mega charizard y ex",
        "source_recipe_id": "pbotfire",
        "adapted_recipe_id": "pbotfire",
        "deck_name": "pbotfire",
    },
    {
        "recommended_type": "Fighting",
        "recommended_name_marker": "elite deck mega lucario ex",
        "source_recipe_id": "pbotfight",
        "adapted_recipe_id": "pbotfight",
        "deck_name": "pbotfight",
    },
    {
        "recommended_type": "Darkness",
        "recommended_name_marker": "hoopa ex deck",
        "source_recipe_id": "pbotdark",
        "adapted_recipe_id": "pbotdark",
        "deck_name": "pbotdark",
    },
)


def parse_battle_recommendation(text: str) -> ParsedRecommendation | None:
    """Convert the game's post-result recommendation modal into durable facts."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    normalized = normalize_game_label(text)
    if "recommended for this battle" not in normalized:
        return None

    recommended_type = next(
        (energy for energy in ENERGY_TYPES if f"{energy.casefold()} type deck" in normalized),
        None,
    )

    recommended_deck_name: str | None = None
    marker = next(
        (index for index, line in enumerate(lines) if normalize_game_label(line) == "recommended"),
        None,
    )
    if marker is not None:
        deck_parts: list[str] = []
        for line in lines[marker + 1 :]:
            label = normalize_game_label(line)
            if label.startswith("to my decks") or label.startswith("to rental decks") or label == "x":
                break
            deck_parts.append(line)
            if "deck" in label and not line.startswith("("):
                continue
            if deck_parts and line.endswith(")"):
                break
        candidate = " ".join(deck_parts).strip()
        if "deck" in normalize_game_label(candidate):
            recommended_deck_name = candidate

    confidence = 0.98 if recommended_type and recommended_deck_name else 0.86
    return ParsedRecommendation(
        recommended_type=recommended_type,
        recommended_deck_name=recommended_deck_name,
        confidence=confidence,
        source_text=text,
    )


class StrategyResolver:
    """Rank policy-safe owned decks for deferred first-win battles."""

    def __init__(self, store: Store, max_attempts_per_deck: int = 1) -> None:
        self.store = store
        self.max_attempts_per_deck = max(1, max_attempts_per_deck)

    def resolve(self, battle_id: str) -> StrategyDecision | None:
        recommendation = self.store.latest_battle_recommendation(battle_id)
        if not recommendation or not recommendation.get("recommended_type"):
            return None

        recommended_type = str(recommendation["recommended_type"])
        named_deck = str(recommendation.get("recommended_deck_name") or "") or None
        candidates: list[tuple[tuple[int, int, str], dict[str, object], dict[str, int]]] = []
        for deck in self.store.owned_decks(recommended_type):
            name = str(deck["display_name"])
            attempts = self.store.deck_attempt_summary(battle_id, name)
            if attempts["wins"]:
                continue
            if attempts["attempts"] >= self.max_attempts_per_deck:
                continue
            source_ref = normalize_game_label(str(deck.get("recipe_source_ref") or ""))
            named_match = int(bool(named_deck) and source_ref == normalize_game_label(named_deck or ""))
            managed = int(bool(deck.get("managed")))
            candidates.append(((-named_match, -managed, name.casefold()), deck, attempts))

        if not candidates:
            return None
        _, deck, attempts = sorted(candidates, key=lambda item: item[0])[0]
        deck_name = str(deck["display_name"])
        reason = f"Owned {recommended_type} counter selected from structured recommendation"
        if named_deck and normalize_game_label(str(deck.get("recipe_source_ref") or "")) == normalize_game_label(named_deck):
            reason = f"Owned deck matches recommended recipe {named_deck}"
        return StrategyDecision(
            battle_id=battle_id,
            deck_name=deck_name,
            recommended_type=recommended_type,
            recommended_deck_name=named_deck,
            reason=reason,
            prior_attempts=attempts["attempts"],
        )

    def next_deferred(self, difficulties: tuple[str, ...]) -> StrategyDecision | None:
        allowed = set(difficulties)
        for battle in reversed(self.store.deferred_battles()):
            if str(battle["difficulty"]) not in allowed:
                continue
            decision = self.resolve(str(battle["id"]))
            if decision:
                return decision
        return None

    def resolve_build(self, battle_id: str) -> BuildStrategyDecision | None:
        """Return a shipped complete recipe only for a specific named recommendation."""
        recommendation = self.store.latest_battle_recommendation(battle_id)
        if not recommendation:
            return None
        recommended_type = str(recommendation.get("recommended_type") or "")
        recommended_name = str(recommendation.get("recommended_deck_name") or "")
        if not recommended_type or not recommended_name:
            return None
        normalized_name = normalize_game_label(recommended_name)

        for candidate in KNOWN_RECIPE_BUILDS:
            if recommended_type.casefold() != str(candidate["recommended_type"]).casefold():
                continue
            marker = normalize_game_label(str(candidate["recommended_name_marker"]))
            if marker not in normalized_name:
                continue
            deck_name = str(candidate["deck_name"])
            if any(
                str(deck["display_name"]).casefold() == deck_name.casefold()
                for deck in self.store.owned_decks(recommended_type)
            ):
                return None
            source = self.store.get_deck_recipe(str(candidate["source_recipe_id"]))
            adapted = self.store.get_deck_recipe(str(candidate["adapted_recipe_id"]))
            if not source or not adapted:
                continue
            if source.get("capture_status") != "complete" or adapted.get("capture_status") != "complete":
                continue
            buildability = self.store.recipe_buildability(str(candidate["adapted_recipe_id"]))
            if not buildability or buildability[0].get("status") != "exact":
                continue
            return BuildStrategyDecision(
                battle_id=battle_id,
                source_recipe_id=str(candidate["source_recipe_id"]),
                adapted_recipe_id=str(candidate["adapted_recipe_id"]),
                deck_name=deck_name,
                recommended_type=recommended_type,
                recommended_deck_name=recommended_name,
                reason=f"Complete shipped recipe matches recommendation {recommended_name}",
            )
        return None

    def next_deferred_build(
        self,
        difficulties: tuple[str, ...],
    ) -> BuildStrategyDecision | None:
        allowed = set(difficulties)
        for battle in reversed(self.store.deferred_battles()):
            if str(battle["difficulty"]) not in allowed:
                continue
            decision = self.resolve_build(str(battle["id"]))
            if decision:
                return decision
        return None
