from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Iterable


@dataclass(frozen=True)
class DeckCard:
    card_id: str
    name: str
    quantity: int
    role: str
    substitute_for: str | None = None
    identity_hint: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DeckRecipe:
    id: str
    display_name: str
    energy_types: tuple[str, ...]
    cards: tuple[DeckCard, ...]
    capabilities: tuple[str, ...]
    source_kind: str
    source_ref: str
    qr_image_url: str | None = None

    def validate(self) -> None:
        total = sum(card.quantity for card in self.cards)
        if total != 20:
            raise ValueError(f"Deck recipe {self.id} has {total} cards; expected 20")
        ids: set[str] = set()
        for card in self.cards:
            if card.quantity not in (1, 2):
                raise ValueError(f"{card.card_id} has unsupported quantity {card.quantity}")
            if card.card_id in ids:
                raise ValueError(f"Deck recipe {self.id} repeats card id {card.card_id}")
            ids.add(card.card_id)

    def card_dicts(self) -> list[dict[str, object]]:
        self.validate()
        return [card.to_dict() for card in self.cards]


@dataclass(frozen=True)
class CardSubstitution:
    missing_card_id: str
    replacement: DeckCard
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "missing_card_id": self.missing_card_id,
            "replacement": self.replacement.to_dict(),
            "reason": self.reason,
        }


def adapt_recipe(
    source: DeckRecipe,
    recipe_id: str,
    display_name: str,
    substitutions: Iterable[CardSubstitution],
) -> DeckRecipe:
    """Create an auditable 20-card account adaptation from a complete source list."""
    cards = {card.card_id: card for card in source.cards}
    for substitution in substitutions:
        missing = cards.get(substitution.missing_card_id)
        if not missing:
            raise ValueError(f"Missing card {substitution.missing_card_id} is not in {source.id}")
        if missing.quantity == 1:
            del cards[missing.card_id]
        else:
            cards[missing.card_id] = replace(missing, quantity=missing.quantity - 1)

        replacement_card = replace(
            substitution.replacement,
            substitute_for=substitution.missing_card_id,
        )
        existing = cards.get(replacement_card.card_id)
        if existing:
            next_quantity = existing.quantity + replacement_card.quantity
            if next_quantity > 2:
                raise ValueError(f"Substitution would exceed two copies of {existing.card_id}")
            cards[existing.card_id] = replace(existing, quantity=next_quantity)
        else:
            cards[replacement_card.card_id] = replacement_card

    adapted = DeckRecipe(
        id=recipe_id,
        display_name=display_name,
        energy_types=source.energy_types,
        cards=tuple(cards.values()),
        capabilities=source.capabilities + ("owned-card-adaptation",),
        source_kind="account_adaptation",
        source_ref=source.id,
    )
    adapted.validate()
    return adapted


MEGA_SHARPEDO_MILOTIC = DeckRecipe(
    id="mega-sharpedo-milotic-tournament",
    display_name="Mega Sharpedo ex / Milotic ex",
    energy_types=("Water",),
    capabilities=("water", "auto-battle", "mega-sharpedo", "milotic"),
    source_kind="published_tournament_aggregate",
    source_ref="https://pokemontcgpocket.app/en/deck/mega-sharpedo-ex-b4-milotic-ex-b3b",
    qr_image_url=(
        "https://game.pokemontcgpocket.app/deck-qr/v1/"
        "deck_3aedd04d3383/0fc32fb10becbbf8a3ce28a771bceec9400da41f8118429cbb6bcca4fff0bd50.png"
    ),
    cards=(
        DeckCard("B4-034", "Carvanha", 2, "basic"),
        DeckCard("B4-035", "Mega Sharpedo ex", 2, "primary-attacker"),
        DeckCard("A4a-021", "Feebas", 2, "basic"),
        DeckCard("B3b-015", "Milotic ex", 1, "secondary-attacker"),
        DeckCard("B2a-037", "Chien-Pao ex", 1, "basic-attacker"),
        DeckCard("B3b-068", "Wallace", 2, "supporter"),
        DeckCard("P-A-007", "Professor's Research", 2, "supporter", identity_hint="Professor Oak"),
        DeckCard("P-A-005", "Poke Ball", 2, "item"),
        DeckCard("A4-151", "Elemental Switch", 2, "item"),
        DeckCard("B1-225", "Copycat", 1, "supporter"),
        DeckCard("A3a-064", "Repel", 1, "item"),
        DeckCard("B3b-065", "Elegant Cape", 1, "tool"),
        DeckCard("B4-154", "Soothing Shore", 1, "stadium"),
    ),
)


PBOT_WATER_ARTICUNO = adapt_recipe(
    MEGA_SHARPEDO_MILOTIC,
    "pbotwater-articuno",
    "pbotwater",
    (
        CardSubstitution(
            "B4-035",
            DeckCard("A1-084", "Articuno ex", 1, "basic-attacker"),
            "Use an owned basic Water attacker when a second Mega Sharpedo ex is unavailable",
        ),
    ),
)


PBOT_FIRE = DeckRecipe(
    id="pbotfire",
    display_name="pbotfire",
    energy_types=("Fire",),
    capabilities=("fire", "auto-battle", "mega-charizard-y", "elite-deck"),
    source_kind="account_verified_theme_list",
    source_ref="https://bulbapedia.bulbagarden.net/wiki/Elite_Deck_%28Mega_Charizard_Y_ex%29",
    cards=(
        DeckCard("B1-047", "Turtonator", 2, "basic"),
        DeckCard("A1-047", "Moltres ex", 1, "energy-accelerator"),
        DeckCard("B2b-007", "Charmander", 2, "basic"),
        DeckCard("B2b-008", "Charmeleon", 2, "energy-accelerator"),
        DeckCard("B1a-014", "Mega Charizard Y ex", 2, "primary-attacker"),
        DeckCard("B2-027", "Hearthflame Mask Ogerpon", 1, "energy-accelerator"),
        DeckCard("P-A-005", "Poke Ball", 2, "item"),
        DeckCard("B1-217", "Flame Patch", 2, "item"),
        DeckCard("P-A-007", "Professor's Research", 2, "supporter", identity_hint="Professor Oak"),
        DeckCard("A1-225", "Sabrina", 1, "supporter"),
        DeckCard("A1a-068", "Leaf", 1, "supporter"),
        DeckCard("A3-155", "Lillie", 1, "supporter"),
        DeckCard("B1-225", "Copycat", 1, "supporter"),
    ),
)


PBOT_FIGHT = DeckRecipe(
    id="pbotfight",
    display_name="pbotfight",
    energy_types=("Fighting",),
    capabilities=("fighting", "auto-battle", "mega-lucario", "elite-deck"),
    source_kind="account_verified_theme_list",
    source_ref="https://bulbapedia.bulbagarden.net/wiki/Elite_Deck_%28Mega_Lucario_ex%29",
    cards=(
        DeckCard("A4-101", "Tyrogue", 2, "basic"),
        DeckCard("B1-124", "Hitmonchan ex", 1, "basic-attacker"),
        DeckCard("B3-079", "Riolu", 2, "basic"),
        DeckCard("B3-081", "Mega Lucario ex", 2, "primary-attacker"),
        DeckCard("B2-092", "Falinks", 2, "basic-attacker"),
        DeckCard("P-A-002", "X Speed", 2, "item"),
        DeckCard("P-A-005", "Poke Ball", 2, "item"),
        DeckCard("P-A-007", "Professor's Research", 2, "supporter", identity_hint="Professor Oak"),
        DeckCard("A2-150", "Cyrus", 1, "supporter"),
        DeckCard("B1-225", "Copycat", 1, "supporter"),
        DeckCard("B3-149", "Korrina", 1, "supporter"),
        DeckCard("B3-154", "Arena of Antiquity", 2, "stadium"),
    ),
)


HOOPA_EX_THEME = DeckRecipe(
    id="hoopa-ex-theme",
    display_name="Hoopa ex Deck",
    energy_types=("Darkness",),
    capabilities=("darkness", "auto-battle", "hoopa-ex", "theme-deck"),
    source_kind="published_theme_list",
    source_ref="https://bulbapedia.bulbagarden.net/wiki/Hoopa_ex_Deck_%28Ruler_of_the_Skies%29",
    cards=(
        DeckCard("B4-091", "Grimer", 2, "basic"),
        DeckCard("B4-092", "Muk", 1, "stage-one-attacker"),
        DeckCard("B4-093", "Poochyena", 2, "basic"),
        DeckCard("B4-094", "Mightyena", 2, "stage-one-attacker"),
        DeckCard("B4-095", "Galarian Zigzagoon", 2, "basic"),
        DeckCard("B4-096", "Galarian Linoone", 2, "stage-one-attacker", identity_hint="Night Slash"),
        DeckCard("B4-097", "Galarian Obstagoon", 1, "secondary-attacker"),
        DeckCard("B4-100", "Absol", 1, "basic-attacker"),
        DeckCard("B4-103", "Hoopa ex", 1, "primary-attacker"),
        DeckCard("B4-148", "Deceptive Needle", 1, "tool"),
        DeckCard("P-A-002", "X Speed", 1, "item"),
        DeckCard("P-A-005", "Poke Ball", 2, "item"),
        DeckCard("P-A-007", "Professor's Research", 2, "supporter", identity_hint="Professor Oak"),
    ),
)


PBOT_DARK = adapt_recipe(
    HOOPA_EX_THEME,
    "pbotdark",
    "pbotdark",
    (
        CardSubstitution(
            "B4-096",
            DeckCard("B2-099", "Galarian Linoone", 1, "stage-one-attacker", identity_hint="Rear Kick"),
            "Use the owned Rear Kick print when a second Night Slash print is unavailable",
        ),
    ),
)


BUILTIN_DECK_RECIPES = {
    recipe.id: recipe
    for recipe in (
        MEGA_SHARPEDO_MILOTIC,
        PBOT_WATER_ARTICUNO,
        PBOT_FIRE,
        PBOT_FIGHT,
        HOOPA_EX_THEME,
        PBOT_DARK,
    )
}


def builtin_recipe(recipe_id: str) -> DeckRecipe:
    try:
        return BUILTIN_DECK_RECIPES[recipe_id]
    except KeyError as exc:
        raise ValueError(f"No complete built-in recipe named {recipe_id!r}") from exc


def persist_recipe(store: object, recipe: DeckRecipe) -> dict[str, object]:
    recipe.validate()
    return store.upsert_deck_recipe(
        recipe.id,
        recipe.display_name,
        list(recipe.energy_types),
        recipe.card_dicts(),
        list(recipe.capabilities),
        recipe.source_kind,
        recipe.source_ref,
        "complete",
    )
