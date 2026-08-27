#!/usr/bin/env python3
"""Consume the persisted Step-Up frontier queue with restart-safe checkpoints."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pbot.config import Settings
from pbot.scheduler import ContinuousScheduler
from pbot.storage import Store

from discover_step_up import AndroidVision
from run_first_pass import FirstPassPilot


EXPERT_DEFAULT_DECK = "aeroape"


def default_deck_name(difficulties: tuple[str, ...]) -> str:
    return EXPERT_DEFAULT_DECK if difficulties == ("Expert",) else "selected deck"


class QueueWorker:
    def __init__(
        self,
        root: Path,
        store: Store,
        device: AndroidVision,
        difficulties: tuple[str, ...],
        deck_name: str,
        timeout: float,
        poll_interval: float,
        one_per_expansion: bool,
        prefer_requested_deck: bool = False,
        target_battle_id: str | None = None,
    ) -> None:
        self.root = root
        self.store = store
        self.device = device
        self.difficulties = difficulties
        self.deck_name = deck_name
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.one_per_expansion = one_per_expansion
        self.prefer_requested_deck = prefer_requested_deck
        self.target_battle_id = target_battle_id

    def log(self, kind: str, message: str, level: str = "info", payload: dict | None = None) -> None:
        print(message, flush=True)
        self.store.add_event(kind, message, level, payload)

    def wait_if_paused(self) -> None:
        announced = False
        while self.store.get_state().get("status") == "paused":
            if not announced:
                self.log("worker.paused", "Queue worker paused between battles", "warning")
                announced = True
            time.sleep(2)
        if announced:
            self.log("worker.resumed", "Queue worker resumed", "success")

    def run(self, limit: int) -> list[dict[str, object]]:
        recovery = self.store.recover_interrupted_work()
        if recovery["interrupted_attempts"] or recovery["released_claims"]:
            self.log("worker.recovered", "Recovered interrupted queue state", "warning", recovery)

        initial = self.store.get_state()
        serial = str(initial.get("device_serial") or (self.device.adb[-1] if len(self.device.adb) > 1 else ""))
        seen_expansions: set[str] = set()
        outcomes: list[dict[str, object]] = []
        wins = 0
        losses = 0

        while len(outcomes) < limit:
            self.wait_if_paused()
            claimed = (
                self.store.claim_battle(self.target_battle_id, self.difficulties)
                if self.target_battle_id and not outcomes
                else self.store.claim_next_battle(
                    self.difficulties,
                    tuple(sorted(seen_expansions)) if self.one_per_expansion else (),
                )
            )
            if not claimed:
                self.log("worker.empty", "No eligible frontier remains for this worker run", "success")
                break

            battle_id = str(claimed["id"])
            expansion = str(claimed["expansion"])
            difficulty = str(claimed["difficulty"])
            if self.one_per_expansion:
                seen_expansions.add(expansion)
            ordinal = len(outcomes) + 1
            self.store.set_state(
                "running",
                f"Queue worker {ordinal}/{limit}: {difficulty} / {expansion}",
                serial,
            )
            self.log(
                "worker.claimed",
                f"Claimed {claimed['name']} ({ordinal}/{limit})",
                "info",
                {"battle_id": battle_id, "difficulty": difficulty, "expansion": expansion},
            )

            pilot = FirstPassPilot(
                self.root,
                self.store,
                self.device,
                difficulty,
                expansion,
                self.deck_name,
                self.timeout,
                self.poll_interval,
                self.prefer_requested_deck,
            )
            try:
                result_rows = pilot.run(1)
                if not result_rows:
                    raise RuntimeError("Battle pilot returned no outcome")
                outcome = result_rows[0]
                if outcome["battle_id"] != battle_id:
                    raise RuntimeError(
                        f"Claimed {battle_id} but the visible frontier was {outcome['battle_id']}; queue reconciliation required"
                    )
            except Exception as exc:
                self.store.resolve_battle_work(battle_id, "queued", f"Worker stopped before resolution: {exc}")
                self.store.set_state("handoff", f"Queue worker stopped: {exc}", serial)
                self.log("worker.error", f"Queue worker stopped: {exc}", "error", {"battle_id": battle_id})
                raise

            result = str(outcome["result"])
            attempt_id = int(outcome["attempt_id"])
            if result == "win":
                wins += 1
                self.store.resolve_battle_work(battle_id, "completed", "First win completed", attempt_id)
            else:
                losses += 1
                self.store.resolve_battle_work(
                    battle_id,
                    "deferred",
                    "Auto first pass lost; deck research required",
                    attempt_id,
                )
            outcomes.append(outcome)
            self.log(
                "worker.resolved",
                f"Resolved {claimed['name']}: {result}",
                "success" if result == "win" else "warning",
                {"battle_id": battle_id, "attempt_id": attempt_id, "result": result},
            )

        if self.store.get_state().get("status") != "paused":
            self.store.set_state(
                "ready",
                f"Queue worker complete: {wins} wins, {losses} deferred",
                serial,
            )
        self.log(
            "worker.completed",
            f"Queue worker completed {len(outcomes)} battle(s): {wins} wins, {losses} deferred",
            "success" if losses == 0 else "warning",
            {"wins": wins, "losses": losses, "outcomes": outcomes},
        )
        return outcomes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial")
    parser.add_argument("--difficulty", action="append", dest="difficulties")
    parser.add_argument("--deck-name")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--poll-interval", type=float, default=5)
    parser.add_argument("--one-per-expansion", action="store_true")
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=0)
    parser.add_argument("--battle-id")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("limit must be between 1 and 100")
    if args.max_rounds < 0:
        parser.error("max-rounds must be zero (unlimited) or a positive integer")

    settings = Settings.load()
    store = Store(settings.database_path)
    store.initialize()
    device = AndroidVision(settings.project_root, args.serial or settings.adb_serial)
    difficulties = tuple(args.difficulties or ("Intermediate", "Advanced", "Expert"))
    worker = QueueWorker(
        settings.project_root,
        store,
        device,
        difficulties,
        args.deck_name or default_deck_name(difficulties),
        args.timeout,
        args.poll_interval,
        args.one_per_expansion,
        args.deck_name is not None,
        args.battle_id,
    )
    if args.continuous:
        scheduler = ContinuousScheduler(
            store,
            worker,
            difficulties,
            args.limit,
            worker.log,
            args.max_rounds,
        )
        summary = scheduler.run()
        results = list(summary["results"])
        wins = sum(str(item["result"]) == "win" for item in results)
        deferred = len(results) - wins
        if summary["exhausted"] and store.get_state().get("status") != "paused":
            state = store.get_state()
            scope = "/".join(args.difficulties or ("Intermediate", "Advanced", "Expert"))
            store.set_state(
                "ready",
                f"{scope} queue complete: {wins} wins, {deferred} deferred",
                str(state.get("device_serial") or args.serial or ""),
            )
        print(json.dumps(summary, indent=2))
    else:
        print(json.dumps({"results": worker.run(args.limit)}, indent=2))


if __name__ == "__main__":
    main()
