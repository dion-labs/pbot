#!/usr/bin/env python3
"""Run the durable owned-only first-win orchestrator."""

from __future__ import annotations

import argparse
import json

from pbot.autonomous import AutonomousFirstWinRunner, DeckBuildNeedsAttention
from pbot.config import Settings
from pbot.deck_recipe import builtin_recipe
from pbot.managed_deck import ManagedDeckConstructor, ManagedDeckError, ManagedDeckPlan
from pbot.recommendation_backfill import (
    backfill_pending_recommendations,
    recognize_with_vision_binary,
)
from pbot.storage import Store
from pbot.strategy import BuildStrategyDecision

from build_managed_deck import AndroidManagedDeckPort, cached_qr
from discover_step_up import AndroidVision
from run_queue_worker import QueueWorker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial")
    parser.add_argument("--difficulty", action="append", dest="difficulties")
    parser.add_argument("--max-actions", type=int, default=500)
    parser.add_argument("--max-attempts-per-deck", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--poll-interval", type=float, default=5)
    args = parser.parse_args()
    if args.max_actions < 1:
        parser.error("max-actions must be positive")
    if args.max_attempts_per_deck < 1:
        parser.error("max-attempts-per-deck must be positive")

    settings = Settings.load()
    store = Store(settings.database_path)
    store.initialize()
    profile = store.get_account_profile()
    if profile.get("status") != "ready":
        message = "Account bootstrap is required before autonomous play"
        store.set_state("needs_attention", message, args.serial or settings.adb_serial)
        store.add_event("run.bootstrap_required", message, "warning", profile)
        print(json.dumps({"status": "needs_attention", "message": message}, indent=2))
        raise SystemExit(2)
    card_profile = store.get_card_inventory_profile()
    if card_profile.get("status") != "ready":
        message = "Recipe card capability scan is required before autonomous play"
        store.set_state("needs_attention", message, args.serial or settings.adb_serial)
        store.add_event("run.card_scan_required", message, "warning", card_profile)
        print(json.dumps({"status": "needs_attention", "message": message}, indent=2))
        raise SystemExit(2)
    serial = args.serial or settings.adb_serial
    device = AndroidVision(settings.project_root, serial)
    difficulties = tuple(args.difficulties or ("Intermediate", "Advanced", "Expert"))

    def log(kind: str, message: str, level: str = "info", payload: dict | None = None) -> None:
        print(message, flush=True)
        store.add_event(kind, message, level, payload)

    backfill = backfill_pending_recommendations(
        store,
        lambda image_path: recognize_with_vision_binary(device.ocr_binary, image_path),
    )
    if backfill["captured_count"]:
        log(
            "recommendation.backfilled",
            f"Recovered {backfill['captured_count']} structured recommendation(s) from saved evidence",
            "success",
            backfill,
        )

    def worker_factory(deck_name: str, battle_id: str) -> QueueWorker:
        return QueueWorker(
            settings.project_root,
            store,
            device,
            difficulties,
            deck_name,
            args.timeout,
            args.poll_interval,
            False,
            deck_name != "selected deck",
            battle_id,
        )

    def deck_builder(decision: BuildStrategyDecision) -> dict[str, object]:
        try:
            source = builtin_recipe(decision.source_recipe_id)
            adapted = builtin_recipe(decision.adapted_recipe_id)
            probe_plan = ManagedDeckPlan.from_recipes(
                source,
                adapted,
                deck_name=decision.deck_name,
                slot_number=1,
            )
            port = AndroidManagedDeckPort(settings.project_root, serial, probe_plan)
            slot_number = port.discover_managed_slot(decision.deck_name)
            qr_image = cached_qr(settings.project_root, source.id, source.qr_image_url)
            build_plan = ManagedDeckPlan.from_recipes(
                source,
                adapted,
                deck_name=decision.deck_name,
                slot_number=slot_number,
                qr_image=qr_image,
            )
            port.plan = build_plan
            outcome = ManagedDeckConstructor(port, store).run(build_plan)
        except (ManagedDeckError, OSError) as exc:
            raise DeckBuildNeedsAttention(str(exc)) from exc
        return {
            "status": outcome.status,
            "deck_name": decision.deck_name,
            "slot_number": slot_number,
            "recipe_id": outcome.effective_recipe_id,
            "already_present": outcome.already_present,
            "evidence_path": outcome.readback.evidence_path,
        }

    runner = AutonomousFirstWinRunner(
        store,
        worker_factory,
        difficulties,
        log,
        args.max_actions,
        args.max_attempts_per_deck,
        deck_builder,
    )
    print(json.dumps(runner.run(), indent=2))


if __name__ == "__main__":
    main()
