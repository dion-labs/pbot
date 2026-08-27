from __future__ import annotations

from pathlib import Path

from .device import AdbDeviceAdapter, DeviceError
from .storage import Store


class Harness:
    def __init__(self, store: Store, device: AdbDeviceAdapter, screenshot_path: Path) -> None:
        self.store = store
        self.device = device
        self.screenshot_path = screenshot_path

    def initialize(self) -> None:
        self.store.initialize()
        if not self.store.recent_events(limit=1):
            self.store.add_event("harness.started", "Harness initialized", "success")
            self.store.add_event("device.waiting", "Waiting for an Android device", "warning")

    def check_device(self) -> dict[str, object]:
        report = self.device.doctor()
        if report.ready:
            self.device.serial = report.selected_serial
            self.store.set_state("ready", "Open Pokémon TCG Pocket", report.selected_serial)
            self.store.add_event("device.ready", "Android device is ready", "success", report.to_dict())
            try:
                self.capture_screen()
            except DeviceError as exc:
                self.store.add_event("device.screenshot_failed", str(exc), "error")
        else:
            self.store.set_state("offline", "Connect an Android device")
            self.store.add_event("device.unavailable", report.message, "warning", report.to_dict())
        return report.to_dict()

    def capture_screen(self) -> Path:
        image = self.device.screenshot()
        self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.screenshot_path.write_bytes(image)
        return self.screenshot_path

    def pause(self) -> dict[str, object]:
        state = self.store.get_state()
        self.store.set_state("paused", "Paused by user", state.get("device_serial"))
        self.store.add_event("control.paused", "Harness paused", "warning")
        return self.store.get_state()

    def handoff(self, objective: str) -> dict[str, object]:
        state = self.store.get_state()
        self.store.set_state("handoff", objective, state.get("device_serial"))
        self.store.add_event("control.handoff", objective, "warning")
        return self.store.get_state()

    def resume(self) -> dict[str, object]:
        report = self.device.doctor()
        status = "ready" if report.ready else "offline"
        objective = "Open Pokémon TCG Pocket" if report.ready else "Connect an Android device"
        self.store.set_state(status, objective, report.selected_serial)
        self.store.add_event("control.resumed", "Harness resumed", "success")
        return self.store.get_state()

    def update_progress(
        self,
        battles_total: int,
        battles_won: int,
        missions_total: int,
        missions_complete: int,
    ) -> dict[str, object]:
        self.store.set_progress_summary(battles_total, battles_won, missions_total, missions_complete)
        state = self.store.get_state()
        self.store.set_state("running", "Map Step-Up battles and missions", state.get("device_serial"))
        self.store.add_event(
            "progress.updated",
            f"Progress snapshot: {battles_won}/{battles_total} battles, {missions_complete}/{missions_total} missions",
            "success",
        )
        return self.snapshot()

    def record_attempt(
        self,
        battle_id: str,
        expansion: str,
        difficulty: str,
        name: str,
        deck_name: str,
        mode: str,
        result: str,
        evidence_path: str | None,
    ) -> dict[str, object]:
        attempt_id = self.store.record_attempt(
            battle_id, expansion, difficulty, name, deck_name, mode, result, evidence_path
        )
        self.store.add_event(
            "attempt.completed",
            f"{name}: {result} with {deck_name} ({mode})",
            "success" if result == "win" else "warning",
            {"attempt_id": attempt_id, "battle_id": battle_id},
        )
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        return {
            "state": self.store.get_state(),
            "metrics": self.store.metrics(),
            "events": self.store.recent_events(),
            "queue": self.store.pending_battles(),
            "screenshot_available": self.screenshot_path.exists(),
        }
