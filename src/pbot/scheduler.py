from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .storage import Store


class RoundWorker(Protocol):
    def run(self, limit: int) -> list[dict[str, object]]: ...


LogFunction = Callable[[str, str, str, dict | None], None]


class ContinuousScheduler:
    """Run restart-safe queue rounds until only completed or deferred work remains."""

    def __init__(
        self,
        store: Store,
        worker: RoundWorker,
        difficulties: tuple[str, ...],
        round_limit: int,
        log: LogFunction,
        max_rounds: int = 0,
    ) -> None:
        self.store = store
        self.worker = worker
        self.difficulties = difficulties
        self.round_limit = round_limit
        self.log = log
        self.max_rounds = max_rounds

    def eligible(self) -> list[dict[str, object]]:
        return [
            item
            for item in self.store.pending_battles(limit=500)
            if item["difficulty"] in self.difficulties and item["work_state"] == "queued"
        ]

    def run(self) -> dict[str, object]:
        scope = "/".join(self.difficulties)
        recovery = self.store.recover_interrupted_work()
        if recovery["interrupted_attempts"] or recovery["released_claims"]:
            self.log("scheduler.recovered", "Recovered interrupted queue state", "warning", recovery)

        rounds = 0
        results: list[dict[str, object]] = []
        while self.eligible():
            if self.max_rounds and rounds >= self.max_rounds:
                self.log(
                    "scheduler.round_limit",
                    f"Continuous scheduler stopped at its {self.max_rounds}-round safety limit",
                    "warning",
                    {"rounds": rounds, "results": len(results)},
                )
                return {"rounds": rounds, "results": results, "exhausted": False}

            rounds += 1
            before = len(self.eligible())
            self.log(
                "scheduler.round_started",
                f"Starting continuous queue round {rounds} with {before} eligible frontier(s)",
                "info",
                {"round": rounds, "eligible": before},
            )
            outcomes = self.worker.run(self.round_limit)
            if not outcomes:
                remaining = len(self.eligible())
                if remaining:
                    raise RuntimeError(
                        f"Continuous scheduler made no progress with {remaining} eligible frontier(s) remaining"
                    )
                break
            results.extend(outcomes)

        self.log(
            "scheduler.completed",
            f"{scope} queue exhausted after {rounds} round(s) and {len(results)} battle(s)",
            "success",
            {"scope": scope, "rounds": rounds, "results": len(results)},
        )
        return {"rounds": rounds, "results": results, "exhausted": True}
