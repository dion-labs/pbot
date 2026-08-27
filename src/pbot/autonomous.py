from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .device import DeviceError
from .storage import Store
from .strategy import BuildStrategyDecision, StrategyDecision, StrategyResolver


class BattleWorker(Protocol):
    def run(self, limit: int) -> list[dict[str, object]]: ...


WorkerFactory = Callable[[str, str], BattleWorker]
DeckBuilder = Callable[[BuildStrategyDecision], dict[str, object]]
LogFunction = Callable[[str, str, str, dict | None], None]


class DeckBuildNeedsAttention(RuntimeError):
    """A known recipe could not be constructed without human intervention."""


def first_pass_deck(difficulty: str) -> str:
    return "aeroape" if difficulty == "Expert" else "selected deck"


class AutonomousFirstWinRunner:
    """Alternate first-pass frontiers and safe deferred strategies until terminal."""

    def __init__(
        self,
        store: Store,
        worker_factory: WorkerFactory,
        difficulties: tuple[str, ...],
        log: LogFunction,
        max_actions: int = 500,
        max_attempts_per_deck: int = 1,
        deck_builder: DeckBuilder | None = None,
    ) -> None:
        self.store = store
        self.worker_factory = worker_factory
        self.difficulties = difficulties
        self.log = log
        self.max_actions = max(1, max_actions)
        self.resolver = StrategyResolver(store, max_attempts_per_deck)
        self.deck_builder = deck_builder

    def _pending(self) -> list[dict[str, object]]:
        allowed = set(self.difficulties)
        return [
            battle
            for battle in self.store.pending_battles(limit=500)
            if str(battle["difficulty"]) in allowed
        ]

    def _next_action(self) -> tuple[dict[str, object], str, StrategyDecision | None] | None:
        pending = self._pending()
        for queued in (battle for battle in pending if battle["work_state"] == "queued"):
            battle_id = str(queued["id"])
            if self.store.latest_battle_recommendation(battle_id):
                decision = self.resolver.resolve(battle_id)
                if decision:
                    self.store.resolve_battle_work(
                        battle_id,
                        "queued",
                        f"Autonomous retry: {decision.reason} using {decision.deck_name}",
                    )
                    return queued, decision.deck_name, decision
                self.store.resolve_battle_work(
                    battle_id,
                    "deferred",
                    "Recovered researched retry has no untried policy-safe owned counter",
                )
                continue
            return queued, first_pass_deck(str(queued["difficulty"])), None

        decision = self.resolver.next_deferred(self.difficulties)
        if not decision:
            return None
        battle = next((item for item in pending if item["id"] == decision.battle_id), None)
        if not battle:
            return None
        self.store.resolve_battle_work(
            decision.battle_id,
            "queued",
            f"Autonomous retry: {decision.reason} using {decision.deck_name}",
        )
        battle["work_state"] = "queued"
        return battle, decision.deck_name, decision

    def run(self) -> dict[str, object]:
        scope = {"difficulties": list(self.difficulties), "objective": "first_wins"}
        policy = {
            "owned_only": True,
            "spending_locked": True,
            "rental_decks": False,
            "max_attempts_per_deck": self.resolver.max_attempts_per_deck,
        }
        run = self.store.start_run_objective("Complete safe Step-Up first wins", scope, policy)
        run_id = str(run["id"])
        device_serial = str(self.store.get_state().get("device_serial") or "") or None
        recovery = self.store.recover_interrupted_work()
        self.store.set_state("running", "Autonomous first-win run", device_serial)
        self.store.add_run_checkpoint(
            run_id,
            "recover",
            "completed",
            "Recovered the last safe queue boundary",
            strategy=recovery,
        )
        outcomes: list[dict[str, object]] = []
        builds: list[dict[str, object]] = []

        try:
            for action_number in range(1, self.max_actions + 1):
                pending = self._pending()
                if not pending:
                    self.store.add_run_checkpoint(
                        run_id,
                        "verify",
                        "completed",
                        "No incomplete first-win frontier remains in scope",
                    )
                    self.store.update_run_objective(run_id, "completed")
                    self.store.set_state("completed", "Autonomous first-win objective complete", device_serial)
                    self.log(
                        "autonomous.completed",
                        f"Autonomous run completed after {len(outcomes)} battle action(s)",
                        "success",
                        {"run_id": run_id, "outcomes": outcomes},
                    )
                    return {
                        "run_id": run_id,
                        "status": "completed",
                        "outcomes": outcomes,
                        "builds": builds,
                    }

                action = self._next_action()
                if not action:
                    build_decision = (
                        self.resolver.next_deferred_build(self.difficulties)
                        if self.deck_builder
                        else None
                    )
                    if build_decision and self.deck_builder:
                        strategy = build_decision.to_dict()
                        self.store.add_run_checkpoint(
                            run_id,
                            "build_deck",
                            "running",
                            f"Action {action_number}: construct {build_decision.deck_name}",
                            build_decision.battle_id,
                            strategy,
                        )
                        self.log(
                            "autonomous.deck_build_started",
                            f"Constructing owned deck {build_decision.deck_name}",
                            "info",
                            {"run_id": run_id, **strategy},
                        )
                        try:
                            build = self.deck_builder(build_decision)
                        except DeckBuildNeedsAttention as exc:
                            self.store.add_run_checkpoint(
                                run_id,
                                "build_deck",
                                "needs_attention",
                                str(exc),
                                build_decision.battle_id,
                                strategy,
                            )
                            self.store.update_run_objective(run_id, "needs_attention")
                            self.store.set_state(
                                "needs_attention",
                                f"Could not construct {build_decision.deck_name}: {exc}",
                                device_serial,
                            )
                            self.log(
                                "autonomous.deck_build_needs_attention",
                                f"Could not construct {build_decision.deck_name}: {exc}",
                                "warning",
                                {"run_id": run_id, **strategy},
                            )
                            return {
                                "run_id": run_id,
                                "status": "needs_attention",
                                "outcomes": outcomes,
                                "builds": builds,
                                "build_blocker": {
                                    **strategy,
                                    "message": str(exc),
                                },
                            }
                        if build.get("status") != "verified":
                            raise RuntimeError(
                                f"Deck constructor did not verify {build_decision.deck_name}"
                            )
                        if not any(
                            str(deck["display_name"]).casefold()
                            == build_decision.deck_name.casefold()
                            for deck in self.store.owned_decks(build_decision.recommended_type)
                        ):
                            raise RuntimeError(
                                f"Verified build {build_decision.deck_name} was not registered as owned"
                            )
                        builds.append(build)
                        self.store.add_run_checkpoint(
                            run_id,
                            "build_deck",
                            "completed",
                            f"Verified owned deck {build_decision.deck_name}",
                            build_decision.battle_id,
                            {**strategy, "build": build},
                        )
                        self.log(
                            "autonomous.deck_build_completed",
                            f"Verified owned deck {build_decision.deck_name}",
                            "success",
                            {"run_id": run_id, **build},
                        )
                        continue

                    unresolved = [
                        {
                            "battle_id": item["id"],
                            "name": item["name"],
                            "reason": item.get("reason"),
                            "recommendation": self.store.latest_battle_recommendation(str(item["id"])),
                        }
                        for item in pending
                    ]
                    self.store.add_run_checkpoint(
                        run_id,
                        "resolve_deferred",
                        "needs_attention",
                        "No untried policy-safe owned counter is known",
                        strategy={"unresolved": unresolved},
                    )
                    self.store.update_run_objective(run_id, "needs_attention")
                    self.store.set_state(
                        "needs_attention",
                        f"{len(unresolved)} battle(s) need a new owned-deck strategy",
                        device_serial,
                    )
                    self.log(
                        "autonomous.needs_attention",
                        f"Autonomous run needs a new strategy for {len(unresolved)} battle(s)",
                        "warning",
                        {"run_id": run_id, "unresolved": unresolved},
                    )
                    return {
                        "run_id": run_id,
                        "status": "needs_attention",
                        "outcomes": outcomes,
                        "builds": builds,
                        "unresolved": unresolved,
                    }

                battle, deck_name, decision = action
                battle_id = str(battle["id"])
                strategy = decision.to_dict() if decision else {
                    "battle_id": battle_id,
                    "deck_name": deck_name,
                    "reason": "first_pass",
                }
                phase = "resolve_deferred" if decision else "first_pass"
                self.store.add_run_checkpoint(
                    run_id,
                    phase,
                    "running",
                    f"Action {action_number}: {battle['name']} with {deck_name}",
                    battle_id,
                    strategy,
                )
                self.log(
                    "autonomous.action_started",
                    f"Autonomous action {action_number}: {battle['name']} with {deck_name}",
                    "info",
                    {"run_id": run_id, **strategy},
                )
                result_rows = self.worker_factory(deck_name, battle_id).run(1)
                if not result_rows:
                    raise RuntimeError(f"Autonomous worker returned no outcome for {battle_id}")
                outcome = result_rows[0]
                outcomes.append(outcome)
                self.store.add_run_checkpoint(
                    run_id,
                    phase,
                    "completed",
                    f"{battle['name']}: {outcome['result']}",
                    battle_id,
                    {**strategy, "outcome": outcome},
                )

            self.store.add_run_checkpoint(
                run_id,
                "safety_limit",
                "needs_attention",
                f"Stopped at the {self.max_actions}-action safety limit",
            )
            self.store.update_run_objective(run_id, "needs_attention")
            self.store.set_state("needs_attention", "Autonomous action safety limit reached", device_serial)
            return {
                "run_id": run_id,
                "status": "needs_attention",
                "outcomes": outcomes,
                "builds": builds,
            }
        except DeviceError as exc:
            self.store.add_run_checkpoint(
                run_id,
                "recover",
                "needs_attention",
                f"Android device unavailable: {exc}",
            )
            self.store.update_run_objective(run_id, "needs_attention")
            self.store.set_state(
                "needs_attention",
                "Reconnect and authorize the Android device, then run pbot again",
                device_serial,
            )
            self.log(
                "autonomous.device_unavailable",
                f"Autonomous run paused because the Android device is unavailable: {exc}",
                "warning",
                {"run_id": run_id},
            )
            return {
                "run_id": run_id,
                "status": "needs_attention",
                "outcomes": outcomes,
                "builds": builds,
                "handoff": "reconnect_device",
            }
        except Exception as exc:
            self.store.add_run_checkpoint(run_id, "recover", "failed", str(exc))
            self.store.update_run_objective(run_id, "failed")
            self.store.set_state("handoff", f"Autonomous run failed: {exc}", device_serial)
            self.log(
                "autonomous.failed",
                f"Autonomous run failed: {exc}",
                "error",
                {"run_id": run_id},
            )
            raise
