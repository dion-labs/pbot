from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol, Sequence

from .deck_recipe import BUILTIN_DECK_RECIPES, DeckRecipe


# Stable-ID visual anchors captured from the exact versioned card images. These
# resolve same-name prints in My Cards without trusting collection-wide totals.
CARD_IDENTITY_HINTS = {
    "A1a-068": "Retreat Cost",
    "A4-151": "Move a",
    "A4a-021": "Leap Out",
    "B1-047": "Shell Trap",
    "B2-027": "Mask Ogerpon",
    "B2-092": "Coordinated Unit",
    "B2a-037": "Diving Icicles",
    "B2b-007": "Flame Tail",
    "B2b-008": "Ignition",
    "B3-079": "Fighting Fist",
    "B3b-015": "Aqua Charge",
    "B3b-068": "maximum HP of 50",
    "B4-034": "Sharp Fang",
    "B4-035": "Turbo Shark",
    "B4-091": "Gentle Slap",
    "B4-092": "Ambush",
    "B4-093": "Team Hunt",
    "B4-094": "Bite",
    "B4-096": "Night Slash",
    "B4-097": "Control",
    "B4-100": "Enhanced Blade",
    "B4-103": "Shadow Bullet",
    "B2-099": "Rear Kick",
    "P-A-005": "random Basic",
    "P-A-007": "Professor Oak",
}


@dataclass(frozen=True)
class CardTarget:
    card_id: str
    name: str
    required_quantity: int
    identity_hint: str | None = None


@dataclass(frozen=True)
class CardObservation:
    card_id: str
    name: str
    quantity: int | None
    status: str
    evidence_path: str
    identity_hint: str | None = None
    message: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"verified", "missing", "ambiguous"}:
            raise ValueError(f"Unsupported card observation status: {self.status}")
        if self.status == "ambiguous" and self.quantity is not None:
            raise ValueError("Ambiguous card observations cannot claim a quantity")
        if self.status != "ambiguous" and (self.quantity is None or self.quantity < 0):
            raise ValueError("Verified card observations require a non-negative quantity")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CardInventoryScanPort(Protocol):
    def scan_cards(self, targets: Sequence[CardTarget]) -> Sequence[CardObservation]: ...


def recipe_card_targets(recipes: Sequence[DeckRecipe] | None = None) -> tuple[CardTarget, ...]:
    """Return the maximum quantity needed for every stable shipped card ID."""
    selected = tuple(recipes or BUILTIN_DECK_RECIPES.values())
    targets: dict[str, CardTarget] = {}
    for recipe in selected:
        recipe.validate()
        for card in recipe.cards:
            prior = targets.get(card.card_id)
            if prior and prior.name != card.name:
                raise ValueError(f"Card id {card.card_id} has conflicting names")
            targets[card.card_id] = CardTarget(
                card_id=card.card_id,
                name=card.name,
                required_quantity=max(card.quantity, prior.required_quantity if prior else 0),
                identity_hint=(
                    card.identity_hint
                    or CARD_IDENTITY_HINTS.get(card.card_id)
                    or (prior.identity_hint if prior else None)
                ),
            )
    return tuple(sorted(targets.values(), key=lambda item: (item.name.casefold(), item.card_id)))


def evaluate_recipe(
    recipe: DeckRecipe,
    observations: Sequence[CardObservation],
) -> dict[str, object]:
    by_id = {observation.card_id: observation for observation in observations}
    missing: list[dict[str, object]] = []
    unknown: list[dict[str, object]] = []
    for card in recipe.cards:
        observation = by_id.get(card.card_id)
        if observation is None or observation.status == "ambiguous":
            unknown.append({
                "card_id": card.card_id,
                "name": card.name,
                "required": card.quantity,
                "message": observation.message if observation else "Card was not scanned",
            })
            continue
        owned = int(observation.quantity or 0)
        if owned < card.quantity:
            missing.append({
                "card_id": card.card_id,
                "name": card.name,
                "required": card.quantity,
                "owned": owned,
            })
    status = "unknown" if unknown else "blocked" if missing else "exact"
    return {
        "recipe_id": recipe.id,
        "status": status,
        "missing_cards": missing,
        "unknown_cards": unknown,
    }


class CardInventoryBootstrapper:
    """Atomically replace targeted card capabilities after one complete scan."""

    def __init__(self, store: object, port: CardInventoryScanPort) -> None:
        self.store = store
        self.port = port

    def run(self, device_serial: str | None) -> dict[str, object]:
        targets = recipe_card_targets()
        checkpoints = {
            str(item["card_id"]): item
            for item in self.store.card_scan_checkpoints(device_serial)
        }
        self.store.begin_card_scan(device_serial, len(targets))
        observations: list[CardObservation] = []
        for index, target in enumerate(targets, 1):
            checkpoint = checkpoints.get(target.card_id)
            if (
                checkpoint
                and checkpoint.get("name") == target.name
                and checkpoint.get("identity_hint") == target.identity_hint
            ):
                observation = CardObservation(
                    target.card_id,
                    target.name,
                    checkpoint.get("quantity"),
                    str(checkpoint["status"]),
                    str(checkpoint.get("evidence_path") or ""),
                    target.identity_hint,
                    str(checkpoint.get("message") or ""),
                )
            else:
                scanned = list(self.port.scan_cards((target,)))
                if len(scanned) != 1 or scanned[0].card_id != target.card_id:
                    raise ValueError(
                        f"Card scan did not return exactly one observation for {target.card_id}"
                    )
                observation = scanned[0]
                self.store.save_card_scan_checkpoint(device_serial, observation.to_dict())
            observations.append(observation)
            self.store.update_card_scan_progress(index, len(targets), target.name)
        expected_ids = {target.card_id for target in targets}
        observed_ids = {observation.card_id for observation in observations}
        if len(observations) != len(observed_ids) or observed_ids != expected_ids:
            raise ValueError("Card scan did not return exactly one observation for every target")
        buildability = [
            evaluate_recipe(recipe, observations)
            for recipe in BUILTIN_DECK_RECIPES.values()
        ]
        evidence = observations[-1].evidence_path if observations else None
        profile = self.store.finish_card_scan(
            device_serial,
            [observation.to_dict() for observation in observations],
            buildability,
            evidence,
        )
        exact = sum(item["status"] == "exact" for item in buildability)
        self.store.add_event(
            "account.card_scan_completed",
            f"Recipe preflight checked {len(observations)} stable card identities; {exact} recipes are exact",
            "success",
            {"target_count": len(observations), "exact_recipes": exact},
        )
        return {
            "profile": profile,
            "cards": [observation.to_dict() for observation in observations],
            "recipes": buildability,
        }
