from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Protocol, Sequence

from .deck_recipe import BUILTIN_DECK_RECIPES


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


@dataclass(frozen=True)
class AccountDeck:
    display_name: str
    slot_number: int
    energy_types: tuple[str, ...]
    evidence_path: str
    recipe_id: str | None = None
    managed: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["energy_types"] = list(self.energy_types)
        return payload


class AccountDeckScanPort(Protocol):
    def scan_owned_decks(self) -> Sequence[AccountDeck]: ...


def known_recipe_id(display_name: str) -> str | None:
    target = normalized(display_name)
    for recipe in BUILTIN_DECK_RECIPES.values():
        if target in {normalized(recipe.id), normalized(recipe.display_name)}:
            return recipe.id
    return None


def is_managed_recipe(recipe_id: str | None) -> bool:
    return bool(recipe_id and recipe_id.startswith("pbot"))


class AccountBootstrapper:
    """Turn a complete read-only deck scan into the local account authority."""

    def __init__(self, store: object, port: AccountDeckScanPort) -> None:
        self.store = store
        self.port = port

    def run(self, device_serial: str | None) -> dict[str, object]:
        self.store.begin_account_scan(device_serial)
        decks = list(self.port.scan_owned_decks())
        payloads = []
        for deck in decks:
            recipe_id = deck.recipe_id or known_recipe_id(deck.display_name)
            payload = deck.to_dict()
            payload["recipe_id"] = recipe_id
            payload["managed"] = deck.managed or is_managed_recipe(recipe_id)
            payloads.append(payload)
        evidence = decks[-1].evidence_path if decks else None
        profile = self.store.finish_account_scan(device_serial, payloads, evidence)
        self.store.add_event(
            "account.scan_completed",
            f"Account bootstrap verified {len(decks)} owned deck slots",
            "success",
            {"deck_count": len(decks), "device_serial": device_serial},
        )
        return {"profile": profile, "decks": payloads}
