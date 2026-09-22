from __future__ import annotations

import sys
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .config import Settings, _loopback_host
from .device import AdbDeviceAdapter, DeviceError
from .engine import Harness
from .managed_job import ACTIVE_STATUSES, ManagedQueueController
from .storage import Store


class HandoffRequest(BaseModel):
    objective: str = "Complete the requested action on the Android device"


class ProgressRequest(BaseModel):
    battles_total: int
    battles_won: int
    missions_total: int
    missions_complete: int


class AttemptRequest(BaseModel):
    battle_id: str
    expansion: str
    difficulty: str
    name: str
    deck_name: str
    mode: str
    result: str
    evidence_path: str | None = None


class AutonomousRunRequest(BaseModel):
    difficulties: list[str] = Field(default_factory=lambda: ["Intermediate", "Advanced", "Expert"])
    max_actions: int = 500
    max_attempts_per_deck: int = 1


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    harness = Harness(
        store=Store(settings.database_path),
        device=AdbDeviceAdapter(settings.adb_path, settings.adb_serial),
        screenshot_path=settings.screenshot_path,
    )
    harness.initialize()
    controller = ManagedQueueController(settings.project_root, settings.database_path, settings.data_dir)

    app = FastAPI(title="pbot control API", version="0.1.1")
    app.state.harness = harness
    dashboard_origins = ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", "http://127.0.0.1:3001"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=dashboard_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_local_request(request: Request, call_next):
        # Binding loopback alone does not prevent browser cross-origin writes or
        # DNS rebinding. Reject before any endpoint can observe or mutate state.
        hosts = request.headers.getlist("host")
        try:
            if len(hosts) != 1:
                raise ValueError("Exactly one Host is required")
            parsed = urlsplit("//" + hosts[0])
            if parsed.netloc != hosts[0] or parsed.username is not None or parsed.password is not None:
                raise ValueError("Invalid Host")
            _loopback_host(parsed.hostname or "")
            _ = parsed.port  # Validate a supplied port before accepting the host.
        except ValueError:
            return JSONResponse({"detail": "A loopback Host is required"}, status_code=400)
        origins = request.headers.getlist("origin")
        if origins and (len(origins) != 1 or origins[0] not in dashboard_origins):
            return JSONResponse({"detail": "Browser origin is not allowed"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status")
    def status() -> dict[str, object]:
        return {
            **harness.snapshot(),
            "job": controller.status(),
            "account_profile": harness.store.get_account_profile(),
            "card_inventory_profile": harness.store.get_card_inventory_profile(),
            "recipe_buildability": harness.store.recipe_buildability(),
            "autonomous_run": harness.store.latest_run_objective(),
            "recommendations": harness.store.recent_recommendations(limit=10),
        }

    @app.post("/api/runs")
    def start_run(request: AutonomousRunRequest) -> dict[str, object]:
        profile = harness.store.get_account_profile()
        if profile.get("status") != "ready":
            raise HTTPException(status_code=409, detail="Scan the connected account before running pbot")
        card_profile = harness.store.get_card_inventory_profile()
        if card_profile.get("status") != "ready":
            raise HTTPException(
                status_code=409,
                detail="Scan shipped recipe card capabilities before running pbot",
            )
        allowed = {"Intermediate", "Advanced", "Expert"}
        difficulties = tuple(dict.fromkeys(request.difficulties))
        if not difficulties or any(item not in allowed for item in difficulties):
            raise HTTPException(status_code=422, detail="Choose Intermediate, Advanced, and/or Expert")
        if not 1 <= request.max_actions <= 500:
            raise HTTPException(status_code=422, detail="max_actions must be between 1 and 500")
        if not 1 <= request.max_attempts_per_deck <= 3:
            raise HTTPException(status_code=422, detail="max_attempts_per_deck must be between 1 and 3")
        device_report = harness.device.doctor()
        if not device_report.ready or not device_report.selected_serial:
            harness.store.set_state("offline", "Connect and authorize an Android device")
            raise HTTPException(status_code=409, detail=device_report.message)
        serial = settings.adb_serial or device_report.selected_serial
        command = [sys.executable, str(settings.project_root / "scripts" / "run_autonomous.py")]
        command.extend(["--serial", serial])
        for difficulty in difficulties:
            command.extend(["--difficulty", difficulty])
        command.extend([
            "--max-actions",
            str(request.max_actions),
            "--max-attempts-per-deck",
            str(request.max_attempts_per_deck),
        ])
        try:
            job = controller.start(command)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"job": job, "state": harness.store.get_state()}

    @app.post("/api/account/bootstrap")
    def bootstrap_account() -> dict[str, object]:
        current = controller.status()
        if current and current.get("status") in ACTIVE_STATUSES:
            raise HTTPException(status_code=409, detail="Another managed pbot job is active")
        state = harness.store.get_state()
        serial = settings.adb_serial or str(state.get("device_serial") or "") or None
        if not serial:
            raise HTTPException(status_code=409, detail="Connect and authorize an Android device first")
        command = [sys.executable, str(settings.project_root / "scripts" / "scan_account.py"), "--serial", serial]
        try:
            job = controller.start(command)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"job": job, "account_profile": harness.store.get_account_profile()}

    @app.post("/api/account/cards")
    def scan_recipe_cards() -> dict[str, object]:
        current = controller.status()
        if current and current.get("status") in ACTIVE_STATUSES:
            raise HTTPException(status_code=409, detail="Another managed pbot job is active")
        if harness.store.get_account_profile().get("status") != "ready":
            raise HTTPException(status_code=409, detail="Scan owned decks before recipe cards")
        state = harness.store.get_state()
        serial = settings.adb_serial or str(state.get("device_serial") or "") or None
        if not serial:
            raise HTTPException(status_code=409, detail="Connect and authorize an Android device first")
        command = [
            sys.executable,
            str(settings.project_root / "scripts" / "scan_cards.py"),
            "--serial",
            serial,
        ]
        try:
            job = controller.start(command)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"job": job, "card_inventory_profile": harness.store.get_card_inventory_profile()}

    @app.get("/api/runs/current")
    def current_run() -> dict[str, object]:
        return {
            "job": controller.status(),
            "run": harness.store.latest_run_objective(),
        }

    @app.post("/api/runs/current/stop")
    def stop_run() -> dict[str, object]:
        job = controller.status()
        if not job or job.get("status") not in ACTIVE_STATUSES:
            raise HTTPException(status_code=409, detail="No autonomous run is active")
        try:
            stopped = controller.stop()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        active_run = harness.store.latest_run_objective()
        if active_run and active_run.get("status") == "running":
            harness.store.update_run_objective(str(active_run["id"]), "stopped")
        return {"job": stopped, "run": harness.store.latest_run_objective()}

    @app.post("/api/device/check")
    def check_device() -> dict[str, object]:
        return {"device": harness.check_device(), **harness.snapshot()}

    @app.get("/api/device/screenshot")
    def screenshot(refresh: bool = True) -> FileResponse:
        try:
            if refresh:
                harness.capture_screen()
        except DeviceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not settings.screenshot_path.exists():
            raise HTTPException(status_code=404, detail="No device screenshot is available.")
        return FileResponse(settings.screenshot_path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/control/pause")
    def pause() -> dict[str, object]:
        return harness.pause()

    @app.post("/api/control/handoff")
    def handoff(request: HandoffRequest) -> dict[str, object]:
        return harness.handoff(request.objective)

    @app.post("/api/control/resume")
    def resume() -> dict[str, object]:
        return harness.resume()

    @app.post("/api/progress")
    def update_progress(request: ProgressRequest) -> dict[str, object]:
        return harness.update_progress(
            request.battles_total,
            request.battles_won,
            request.missions_total,
            request.missions_complete,
        )

    @app.post("/api/attempts")
    def record_attempt(request: AttemptRequest) -> dict[str, object]:
        return harness.record_attempt(
            request.battle_id,
            request.expansion,
            request.difficulty,
            request.name,
            request.deck_name,
            request.mode,
            request.result,
            request.evidence_path,
        )

    return app


app = create_app()
