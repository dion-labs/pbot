from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, Sequence

from PIL import Image

from .deck_recipe import DeckCard, DeckRecipe


class ImportSaveResult(str, Enum):
    SAVED = "saved"
    OWNERSHIP_FAILURE = "ownership_failure"


class ManagedDeckError(RuntimeError):
    """A guarded deck build could not continue without risking account state."""


class OcrObservation(Protocol):
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int


ENERGY_HUES = {
    "Fire": 5.0,
    "Fighting": 30.0,
    "Lightning": 55.0,
    "Grass": 145.0,
    "Water": 195.0,
    "Darkness": 195.0,
    "Psychic": 290.0,
    "Metal": 0.0,
}

# Sixteen-by-sixteen dark-pixel signatures from the game's fixed energy icons.
# Water and Darkness intentionally share a cyan ring, so their inner symbols
# (droplet versus crescent) are the stable differentiator.
WATER_SYMBOL_MASK = int(
    "1000e601f181ff81ff80ff807f807f803f007c00f80000000000000", 16
)
DARKNESS_SYMBOL_MASK = int(
    "1c00ff01ff81ffc3ffc3ffc3ffc3e7c3c3c1c000c00000000000000", 16
)

ACTIVE_BATTLE_MARKERS = (
    "auto battle",
    "your turn",
    "opponent's turn",
    "concede",
    "battle log",
)


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _nearest_hue(left: float, right: float) -> float:
    difference = abs(left - right)
    return min(difference, 360.0 - difference)


def active_battle_likely(screen_text: str) -> bool:
    normalized = _normalized(screen_text)
    safe_account_signatures = (
        "my cards",
        "my decks",
        "display boards",
        "highlight card",
        "highlight cards",
    )
    if any(signature in normalized for signature in safe_account_signatures):
        return False
    return any(marker in normalized for marker in ACTIVE_BATTLE_MARKERS)


def visible_energy_types(path: Path, expected: Sequence[str]) -> tuple[str, ...]:
    """Classify one or more fixed deck-detail energy icons."""
    image = Image.open(path).convert("RGB")
    width, height = image.size
    region = image.crop(
        (
            round(70 * width / 1080),
            round(720 * height / 2340),
            round(280 * width / 1080),
            round(835 * height / 2340),
        )
    ).resize((210, 115))
    foreground: set[tuple[int, int]] = set()
    for y in range(region.height):
        for x in range(region.width):
            red, green, blue = region.getpixel((x, y))
            _hue, saturation, value = colorsys.rgb_to_hsv(
                red / 255, green / 255, blue / 255
            )
            if (saturation > 0.25 and value > 0.25) or value < 0.72:
                foreground.add((x, y))

    components: list[list[tuple[int, int]]] = []
    while foreground:
        start = foreground.pop()
        pending = [start]
        component = [start]
        while pending:
            x, y = pending.pop()
            for neighbor in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if neighbor in foreground:
                    foreground.remove(neighbor)
                    pending.append(neighbor)
                    component.append(neighbor)
        if len(component) >= 500:
            components.append(component)

    observed: list[str] = []
    color_targets = {
        energy: hue
        for energy, hue in ENERGY_HUES.items()
        if energy not in {"Darkness", "Metal"}
    }
    for component in sorted(components, key=lambda points: min(x for x, _y in points)):
        xs = [x for x, _y in component]
        ys = [y for _x, y in component]
        glyph = region.crop((min(xs), min(ys), max(xs) + 1, max(ys) + 1))
        votes = {energy: 0 for energy in color_targets}
        saturated = 0
        for red, green, blue in glyph.get_flattened_data():
            hue, saturation, value = colorsys.rgb_to_hsv(
                red / 255, green / 255, blue / 255
            )
            if saturation <= 0.25 or value <= 0.30:
                continue
            saturated += 1
            degrees = hue * 360
            nearest = min(
                color_targets,
                key=lambda energy: _nearest_hue(degrees, color_targets[energy]),
            )
            votes[nearest] += 1

        if saturated < 100:
            observed.append("Metal")
            continue
        energy = max(votes, key=votes.get)
        if energy == "Water":
            mask = 0
            resized = glyph.resize((16, 16))
            for index, (red, green, blue) in enumerate(resized.get_flattened_data()):
                _hue, _saturation, value = colorsys.rgb_to_hsv(
                    red / 255, green / 255, blue / 255
                )
                if value < 0.45:
                    mask |= 1 << index
            if (mask ^ DARKNESS_SYMBOL_MASK).bit_count() < (
                mask ^ WATER_SYMBOL_MASK
            ).bit_count():
                energy = "Darkness"
        observed.append(energy)

    return tuple(energy for energy in expected if energy in observed)


def readback_from_observations(
    path: Path,
    lines: Sequence[OcrObservation],
    expected_name: str,
    expected_energy: Sequence[str],
) -> DeckReadback:
    dump = "\n".join(line.text for line in lines)
    folded = dump.casefold()
    count_match = re.search(r"(\d+)\s*/\s*20", dump)
    expected_line = next(
        (line for line in lines if _normalized(line.text) == _normalized(expected_name)),
        None,
    )
    excluded = {"energy", "accessories", "change", "highlight cards"}
    top_labels = [
        line.text.strip()
        for line in lines
        if line.y < 320
        and _normalized(line.text) not in excluded
        and not re.fullmatch(r"[.·• ]+", line.text)
    ]
    observed_name = expected_line.text.strip() if expected_line else (top_labels[0] if top_labels else None)
    invalid_markers = (
        "not usable",
        "do not own",
        "don't own",
        "not enough cards",
        "cannot use this deck",
        "unable to use this deck",
    )
    compact = dump.replace(" ", "")
    return DeckReadback(
        deck_name=observed_name,
        card_count=int(count_match.group(1)) if count_match else None,
        energy_types=visible_energy_types(path, expected_energy),
        ownership_valid=not any(marker in folded for marker in invalid_markers) and "20/20" in compact,
        detail_screen=any(_normalized(line.text) == "edit" for line in lines) and "20/20" in compact,
        evidence_path=str(path),
        screen_text=dump,
    )


@dataclass(frozen=True)
class RecipeSubstitution:
    missing_card_id: str
    missing_card_name: str
    replacement_card_id: str
    replacement_card_name: str
    quantity: int

    def to_dict(self) -> dict[str, object]:
        return {
            "missing_card_id": self.missing_card_id,
            "missing_card_name": self.missing_card_name,
            "replacement_card_id": self.replacement_card_id,
            "replacement_card_name": self.replacement_card_name,
            "quantity": self.quantity,
        }


@dataclass(frozen=True)
class ManagedDeckPlan:
    source_recipe: DeckRecipe
    adapted_recipe: DeckRecipe
    deck_name: str
    slot_number: int
    substitutions: tuple[RecipeSubstitution, ...]
    qr_image: Path | None = None

    @classmethod
    def from_recipes(
        cls,
        source_recipe: DeckRecipe,
        adapted_recipe: DeckRecipe,
        *,
        deck_name: str,
        slot_number: int,
        qr_image: Path | None = None,
    ) -> ManagedDeckPlan:
        source_recipe.validate()
        adapted_recipe.validate()
        source_cards = {card.card_id: card for card in source_recipe.cards}
        adapted_cards = {card.card_id: card for card in adapted_recipe.cards}

        removed: dict[str, int] = {}
        for card_id, source_card in source_cards.items():
            difference = source_card.quantity - adapted_cards.get(
                card_id, DeckCard(card_id, source_card.name, 0, source_card.role)
            ).quantity
            if difference > 0:
                removed[card_id] = difference

        substitutions: list[RecipeSubstitution] = []
        covered: dict[str, int] = {}
        for card in adapted_recipe.cards if source_recipe.id != adapted_recipe.id else ():
            if not card.substitute_for:
                continue
            source_quantity = source_cards.get(card.card_id)
            added_quantity = card.quantity - (source_quantity.quantity if source_quantity else 0)
            if added_quantity <= 0:
                raise ValueError(
                    f"Adapted card {card.card_id} declares a substitution but adds no copies"
                )
            missing = source_cards.get(card.substitute_for)
            if not missing:
                raise ValueError(
                    f"Adapted card {card.card_id} substitutes unknown card {card.substitute_for}"
                )
            substitutions.append(
                RecipeSubstitution(
                    missing_card_id=missing.card_id,
                    missing_card_name=missing.name,
                    replacement_card_id=card.card_id,
                    replacement_card_name=card.name,
                    quantity=added_quantity,
                )
            )
            covered[missing.card_id] = covered.get(missing.card_id, 0) + added_quantity

        if removed != covered:
            raise ValueError(
                "Adapted recipe delta is not fully explained by declared substitutions: "
                f"removed={removed}, declared={covered}"
            )
        if source_recipe.id != adapted_recipe.id and not substitutions:
            raise ValueError("A distinct adapted recipe must declare at least one substitution")
        if not deck_name.strip():
            raise ValueError("Managed deck name cannot be empty")
        if not 1 <= slot_number <= 25:
            raise ValueError("Managed deck slot must be between 1 and 25")

        return cls(
            source_recipe=source_recipe,
            adapted_recipe=adapted_recipe,
            deck_name=deck_name.strip(),
            slot_number=slot_number,
            substitutions=tuple(substitutions),
            qr_image=qr_image,
        )


@dataclass(frozen=True)
class DeckReadback:
    deck_name: str | None
    card_count: int | None
    energy_types: tuple[str, ...]
    ownership_valid: bool
    detail_screen: bool
    evidence_path: str | None
    screen_text: str

    def validation_errors(self, plan: ManagedDeckPlan) -> tuple[str, ...]:
        errors: list[str] = []
        if (self.deck_name or "").casefold() != plan.deck_name.casefold():
            errors.append(
                f"expected deck name {plan.deck_name!r}, observed {self.deck_name!r}"
            )
        if self.card_count != 20:
            errors.append(f"expected 20/20 cards, observed {self.card_count!r}")
        expected_energy = {item.casefold() for item in plan.adapted_recipe.energy_types}
        observed_energy = {item.casefold() for item in self.energy_types}
        if not expected_energy.issubset(observed_energy):
            errors.append(
                "expected energy "
                f"{sorted(plan.adapted_recipe.energy_types)!r}, observed {sorted(self.energy_types)!r}"
            )
        if not self.ownership_valid:
            errors.append("visible deck did not pass the owned-card usability check")
        if not self.detail_screen:
            errors.append("read-back was not captured from the deck detail screen")
        return tuple(errors)


@dataclass(frozen=True)
class ManagedDeckOutcome:
    status: str
    effective_recipe_id: str
    readback: DeckReadback
    used_substitutions: tuple[RecipeSubstitution, ...]
    already_present: bool


class ManagedDeckPort(Protocol):
    def inspect_slot(self, slot_number: int, expected_name: str) -> DeckReadback | None: ...

    def import_qr(self, plan: ManagedDeckPlan) -> str | None: ...

    def rename_draft(self, deck_name: str) -> None: ...

    def attempt_save(self) -> ImportSaveResult: ...

    def apply_substitutions(self, substitutions: Sequence[RecipeSubstitution]) -> str | None: ...

    def read_back(self, slot_number: int, expected_name: str) -> DeckReadback: ...


class DeckBuildRecorder(Protocol):
    def record_deck_build(
        self,
        recipe_id: str,
        deck_name: str,
        status: str,
        missing_cards: list[dict[str, object]] | None = None,
        substitutions: list[dict[str, object]] | None = None,
        evidence_path: str | None = None,
        message: str | None = None,
    ) -> dict[str, object]: ...

    def register_owned_deck(
        self,
        display_name: str,
        recipe_id: str | None,
        energy_types: list[str],
        *,
        verified: bool,
        managed: bool,
        slot_number: int | None,
        source: str,
        available: bool = True,
    ) -> dict[str, object]: ...


class ManagedDeckConstructor:
    """Build or verify one explicit pbot-owned slot without spend-capable actions."""

    def __init__(self, port: ManagedDeckPort, recorder: DeckBuildRecorder) -> None:
        self.port = port
        self.recorder = recorder

    def _record_failure(self, plan: ManagedDeckPlan, message: str, evidence: str | None) -> None:
        self.recorder.record_deck_build(
            plan.adapted_recipe.id,
            plan.deck_name,
            "failed",
            substitutions=[item.to_dict() for item in plan.substitutions],
            evidence_path=evidence,
            message=message,
        )

    def _verify_and_register(
        self,
        plan: ManagedDeckPlan,
        readback: DeckReadback,
        *,
        effective_recipe_id: str,
        substitutions: tuple[RecipeSubstitution, ...],
        already_present: bool,
    ) -> ManagedDeckOutcome:
        errors = readback.validation_errors(plan)
        if errors:
            message = "; ".join(errors)
            self._record_failure(plan, message, readback.evidence_path)
            raise ManagedDeckError(message)

        self.recorder.record_deck_build(
            effective_recipe_id,
            plan.deck_name,
            "verified",
            substitutions=[item.to_dict() for item in substitutions],
            evidence_path=readback.evidence_path,
            message=(
                "Existing managed slot passed guarded read-back"
                if already_present
                else "Managed slot saved and passed guarded read-back"
            ),
        )
        self.recorder.register_owned_deck(
            plan.deck_name,
            effective_recipe_id,
            list(plan.adapted_recipe.energy_types),
            verified=True,
            managed=True,
            slot_number=plan.slot_number,
            source="pbot_managed_constructor",
        )
        return ManagedDeckOutcome(
            status="verified",
            effective_recipe_id=effective_recipe_id,
            readback=readback,
            used_substitutions=substitutions,
            already_present=already_present,
        )

    def run(self, plan: ManagedDeckPlan) -> ManagedDeckOutcome:
        existing = self.port.inspect_slot(plan.slot_number, plan.deck_name)
        if existing is not None:
            return self._verify_and_register(
                plan,
                existing,
                effective_recipe_id=plan.adapted_recipe.id,
                substitutions=plan.substitutions,
                already_present=True,
            )

        self.recorder.record_deck_build(
            plan.source_recipe.id,
            plan.deck_name,
            "planned",
            substitutions=[item.to_dict() for item in plan.substitutions],
            message=f"Guarded construction planned for managed slot {plan.slot_number}",
        )
        if plan.qr_image is None or not plan.qr_image.is_file():
            message = "Source QR image is required when the managed slot is absent"
            self._record_failure(plan, message, None)
            raise ManagedDeckError(message)

        imported_evidence = self.port.import_qr(plan)
        self.recorder.record_deck_build(
            plan.source_recipe.id,
            plan.deck_name,
            "imported",
            substitutions=[item.to_dict() for item in plan.substitutions],
            evidence_path=imported_evidence,
            message="Source QR imported; validating owned-card usability",
        )
        self.port.rename_draft(plan.deck_name)
        save_result = self.port.attempt_save()
        effective_recipe_id = plan.source_recipe.id
        used_substitutions: tuple[RecipeSubstitution, ...] = ()

        if save_result is ImportSaveResult.OWNERSHIP_FAILURE:
            if not plan.substitutions:
                message = "Source recipe is not usable and has no declared substitutions"
                self._record_failure(plan, message, imported_evidence)
                raise ManagedDeckError(message)
            self.recorder.record_deck_build(
                plan.adapted_recipe.id,
                plan.deck_name,
                "needs_substitution",
                missing_cards=[
                    {
                        "card_id": item.missing_card_id,
                        "name": item.missing_card_name,
                        "quantity": item.quantity,
                    }
                    for item in plan.substitutions
                ],
                substitutions=[item.to_dict() for item in plan.substitutions],
                evidence_path=imported_evidence,
                message="Ownership validation failed; applying only declared substitutions",
            )
            substitution_evidence = self.port.apply_substitutions(plan.substitutions)
            if self.port.attempt_save() is not ImportSaveResult.SAVED:
                message = "Adapted recipe still failed owned-card usability validation"
                self._record_failure(plan, message, substitution_evidence)
                raise ManagedDeckError(message)
            effective_recipe_id = plan.adapted_recipe.id
            used_substitutions = plan.substitutions

        readback = self.port.read_back(plan.slot_number, plan.deck_name)
        return self._verify_and_register(
            plan,
            readback,
            effective_recipe_id=effective_recipe_id,
            substitutions=used_substitutions,
            already_present=False,
        )
