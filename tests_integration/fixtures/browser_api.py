"""Disposable HTTP fixture: actual API/Store with fake hardware and dispatch."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--fixture-id", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    assert (root / ".browser-fixture").read_text() == args.fixture_id
    for key in list(os.environ):
        if key.startswith("PBOT_"):
            del os.environ[key]
    os.environ.update(
        PBOT_ROOT=str(root / "project"),
        PBOT_DATA_DIR=str(root / "data"),
        PBOT_DATABASE=str(root / "data" / "fixture.sqlite3"),
        PBOT_SCREENSHOT=str(root / "data" / "fictional.png"),
        PBOT_ADB=str(root / "NO_ADB_EXISTS"),
        PBOT_API_HOST="127.0.0.1",
        PBOT_API_PORT=str(args.port),
    )
    lock = threading.RLock()
    control = {"job": None, "scenario": "empty", "reject_start": False,
               "delay": 0.0, "status_error": False, "status_delay_once": 0.0,
               "held_status": False, "dispatch": [], "forbidden": []}

    def record(kind: str, **values) -> None:
        entry = {"kind": kind, **values}
        with lock:
            control["dispatch"].append(entry)
            with (root / "dispatch.jsonl").open("a") as handle:
                handle.write(json.dumps(entry) + "\n")

    def forbidden(*_args, **_kwargs):
        control["forbidden"].append("subprocess")
        raise AssertionError("Browser API fixture forbids subprocess creation")

    # Install dispatch boundaries BEFORE api.py creates its module-level app.
    import pbot
    assert Path(pbot.__file__).resolve().is_relative_to(root / "project" / "src")
    import pbot.device as device_module
    import pbot.managed_job as managed_module
    from pbot.storage import Store

    class FakeDevice:
        def __init__(self, _path=None, serial=None):
            self.serial = serial

        def doctor(self):
            record("device.doctor")
            ready = control["scenario"] not in {"empty", "disconnected-ready", "disconnected-running"}
            return device_module.DeviceDoctor(
                True, "fixture-only", (), "fixture-phone" if ready else None,
                ready, "Fictional device ready" if ready else "Fictional device disconnected",
            )

        def screenshot(self):
            record("device.screenshot")
            raise device_module.DeviceError("No physical screen in browser fixture")

    class FakeController:
        def __init__(self, _project, database_path, _data_dir):
            self.store = Store(database_path)

        def status(self):
            with lock:
                return dict(control["job"]) if control["job"] else None

        def start(self, command):
            record("controller.start", command=command)
            time.sleep(float(control["delay"]))
            if control["reject_start"]:
                raise RuntimeError("Fictional launch rejected; rescan the selected device and retry")
            if control["job"] and control["job"]["status"] in {"starting", "running", "stopping"}:
                raise RuntimeError("Fictional job already active")
            if "scan_account.py" in command[1]:
                self.store.begin_account_scan("fixture-phone")
            elif "scan_cards.py" in command[1]:
                self.store.begin_card_scan("fixture-phone", 0)
            control["job"] = {"id": "fictional-job", "status": "running", "message": "Fictional run started"}
            self.store.set_state("running", "Fictional run started", "fixture-phone")
            self.store.add_event("fixture.started", "Fictional run started", "success")
            return self.status()

        def stop(self):
            record("controller.stop")
            time.sleep(float(control["delay"]))
            control["job"] = {"id": "fictional-job", "status": "stopped", "message": "Fictional run stopped"}
            self.store.set_state("stopped", "Fictional run stopped", "fixture-phone")
            self.store.add_event("fixture.stopped", "Fictional run stopped", "warning")
            return self.status()

    device_module.AdbDeviceAdapter = FakeDevice
    managed_module.ManagedQueueController = FakeController
    subprocess.Popen = forbidden
    subprocess.run = forbidden
    from pbot.api import app
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse
    store = app.state.harness.store

    def reset(payload: dict) -> None:
        with lock:
            control.update(job=None, scenario=payload.get("scenario", "empty"),
                           reject_start=payload.get("reject_start", False),
                           delay=payload.get("delay", 0.0),
                           status_error=payload.get("status_error", False),
                           status_delay_once=0.0, held_status=False, dispatch=[])
            with store.connect() as connection:
                connection.execute("PRAGMA foreign_keys=OFF")
                tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                for row in tables:
                    if not row["name"].startswith("sqlite_"):
                        connection.execute('DELETE FROM "' + row["name"].replace('"', '""') + '"')
            store.initialize()
            scenario = str(control["scenario"])
            if scenario != "empty":
                store.set_state("ready", "Fictional device ready", "fixture-phone")
            if scenario not in {"empty", "unscanned"}:
                store.finish_account_scan("fixture-phone", [{"slot_number": 1, "display_name": "Fictional deck"}], None)
                store.finish_card_scan("fixture-phone", [{"card_id": "fixture-card", "name": "Fictional card", "quantity": 0, "status": "missing"}], [], None)
            if scenario == "disconnected-ready":
                store.set_state("offline", "Fictional device disconnected", None)
            if scenario in {"running", "disconnected-running", "needs-attention", "long-content"}:
                if scenario in {"running", "disconnected-running"}:
                    control["job"] = {"id": "fictional-job", "status": "running", "message": "Fictional run active"}
                    store.set_state("running", "Fictional run active", None if scenario == "disconnected-running" else "fixture-phone")
                else:
                    reason = "No safe strategies remain for the fictional objective. Review the saved evidence."
                    store.set_state("needs_attention", reason, "fixture-phone")
                    store.add_event("fixture.handoff", reason, "warning")
                    control["job"] = {"id": "fictional-job", "status": "needs_attention", "message": reason}
            if scenario == "long-content":
                store.add_event("fixture.long", "Fictional evidence path: /synthetic/" + "LongFixtureSegment" * 15, "warning")

    def authorize(request):
        if request.headers.get("x-fixture-id") != args.fixture_id:
            raise HTTPException(403, "Fixture control requires its invocation ID")

    @app.middleware("http")
    async def audit(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/api/status" and response.status_code == 200 and control["status_delay_once"]:
            delay = float(control["status_delay_once"])
            control["status_delay_once"] = 0.0
            control["held_status"] = True
            await asyncio.sleep(delay)
            control["held_status"] = False
        if request.url.path == "/api/status" and control["status_error"] and response.status_code == 200:
            cors = {key: value for key, value in response.headers.items() if key.startswith("access-control-") or key == "vary"}
            response = JSONResponse({"detail": "Fictional status temporarily unavailable"}, status_code=503, headers=cors)
        with (root / "requests.jsonl").open("a") as handle:
            handle.write(json.dumps({"method": request.method, "path": request.url.path,
                                     "origin": request.headers.get("origin"), "host": request.headers.get("host"),
                                     "status": response.status_code}) + "\n")
        return response

    @app.post("/__fixture/reset")
    async def configure(request: Request):
        authorize(request)
        reset(await request.json())
        return {"ok": True}

    @app.post("/__fixture/options")
    async def options(request: Request):
        authorize(request)
        values = await request.json()
        assert set(values) <= {"reject_start", "delay", "status_error", "status_delay_once"}
        control.update(values)
        return {"ok": True}

    @app.get("/__fixture/receipt")
    def receipt(request: Request):
        authorize(request)
        with store.connect() as connection:
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            data = {row["name"]: [dict(item) for item in connection.execute('SELECT * FROM "' + row["name"] + '"')]
                    for row in tables if not row["name"].startswith("sqlite_")}
        return {"dispatch": control["dispatch"], "forbidden": control["forbidden"], "held_status": control["held_status"],
                "store_sha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()}

    reset({"scenario": "empty"})
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
