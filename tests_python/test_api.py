"""HTTP contract checks with synthetic storage, no server sockets or ADB."""
from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

from pbot.config import Settings
from pbot.device import DeviceError


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # api.py constructs a module-level app: isolate environment BEFORE import.
    for key in ("PBOT_DATABASE", "PBOT_SCREENSHOT", "PBOT_ADB_SERIAL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PBOT_ROOT", str(tmp_path))
    monkeypatch.setenv("PBOT_DATA_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("PBOT_API_HOST", "127.0.0.1")
    api = importlib.import_module("pbot.api")
    def forbidden(*args, **kwargs):
        raise AssertionError("This HTTP test must not launch a process or use ADB")
    monkeypatch.setattr(api.ManagedQueueController, "start", forbidden)
    monkeypatch.setattr(api.AdbDeviceAdapter, "doctor", forbidden)
    monkeypatch.setattr(api.AdbDeviceAdapter, "screenshot", forbidden)
    return api.create_app(Settings.load())


def request(app, method, path, body=None, headers=None):
    async def invoke():
        messages = []
        async def receive():
            return {"type": "http.request", "body": json.dumps(body).encode() if body is not None else b"", "more_body": False}
        async def send(message):
            messages.append(message)
        route, _, query = path.partition("?")
        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                   "scheme": "http", "path": route, "raw_path": route.encode(), "query_string": query.encode(),
                   "root_path": "", "headers": [(b"content-type", b"application/json"), *(headers if headers is not None else [(b"host", b"127.0.0.1:8765")])],
                   "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8765)}, receive, send)
        start = next(item for item in messages if item["type"] == "http.response.start")
        data = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return start["status"], dict(start["headers"]), data
    return asyncio.run(invoke())


def test_health_and_empty_current_job(app):
    assert json.loads(request(app, "GET", "/api/health")[2]) == {"status": "ok"}
    assert json.loads(request(app, "GET", "/api/runs/current")[2]) == {"job": None, "run": None}


@pytest.mark.parametrize("path,body", [("/api/runs", {}), ("/api/account/bootstrap", None),
                                      ("/api/account/cards", None), ("/api/runs/current/stop", None)])
def test_unprepared_actions_reject_without_device_or_process(app, path, body):
    assert request(app, "POST", path, body)[0] == 409


@pytest.mark.parametrize("body", [{"difficulties": []}, {"difficulties": ["Unknown"]}, {"max_actions": 0},
                                  {"max_actions": 501}, {"max_attempts_per_deck": 0}, {"max_attempts_per_deck": 4}])
def test_invalid_run_policy_never_reaches_device(app, monkeypatch, body):
    store = app.state.harness.store
    monkeypatch.setattr(store, "get_account_profile", lambda: {"status": "ready"})
    monkeypatch.setattr(store, "get_card_inventory_profile", lambda: {"status": "ready"})
    assert request(app, "POST", "/api/runs", body)[0] == 422


def test_screenshot_missing_capture_failure_and_no_store(app, monkeypatch):
    assert request(app, "GET", "/api/device/screenshot?refresh=false")[0] == 404
    def disconnected():
        raise DeviceError("synthetic disconnect")
    monkeypatch.setattr(app.state.harness, "capture_screen", disconnected)
    assert request(app, "GET", "/api/device/screenshot")[0] == 503
    app.state.harness.screenshot_path.write_bytes(b"synthetic-image")
    status, headers, data = request(app, "GET", "/api/device/screenshot?refresh=false")
    assert status == 200
    assert headers[b"cache-control"] == b"no-store"
    assert data == b"synthetic-image"


@pytest.mark.parametrize("host", [b"attacker.example:8765", b"0.0.0.0:8765", b"user@localhost", b"localhost/path", b"localhost:invalid"])
def test_nonlocal_or_malformed_host_rejected(app, host):
    assert request(app, "POST", "/api/control/pause", headers=[(b"host", host)])[0] == 400
    assert app.state.harness.store.get_state()["status"] == "offline"


@pytest.mark.parametrize("origin", [b"https://attacker.example", b"null", b"http://localhost:3000.attacker.example"])
def test_external_origin_cannot_mutate_local_state(app, origin):
    assert request(app, "POST", "/api/control/pause", headers=[(b"host", b"127.0.0.1:8765"), (b"origin", origin)])[0] == 403
    assert app.state.harness.store.get_state()["status"] == "offline"


@pytest.mark.parametrize("host", [b"localhost:8765", b"127.0.0.1:8765", b"[::1]:8765"])
def test_local_dashboard_origin_allowed(app, host):
    status, headers, _ = request(app, "GET", "/api/health", headers=[(b"host", host), (b"origin", b"http://localhost:3001")])
    assert status == 200
    assert headers[b"access-control-allow-origin"] == b"http://localhost:3001"


@pytest.mark.parametrize("headers", [[], [(b"host", b"localhost"), (b"host", b"attacker.example")],
                                     [(b"host", b"localhost"), (b"origin", b"http://localhost:3001"), (b"origin", b"https://attacker.example")]])
def test_missing_or_duplicate_security_headers_rejected(app, headers):
    assert request(app, "POST", "/api/control/pause", headers=headers)[0] in {400, 403}
    assert app.state.harness.store.get_state()["status"] == "offline"
