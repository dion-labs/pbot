from pathlib import Path
import sys
import time

import pytest

from pbot.managed_job import ManagedJobState, ManagedQueueController


def test_managed_job_state_rejects_a_live_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = ManagedJobState(tmp_path / "job.json")
    first = state.create(["python", "worker.py"], tmp_path / "worker.log")
    state.update(str(first["id"]), pid=1234, status="running")
    monkeypatch.setattr("pbot.managed_job.process_alive", lambda pid: pid == 1234)

    with pytest.raises(RuntimeError, match="already running"):
        state.create(["python", "other.py"], tmp_path / "other.log")


def test_managed_job_terminal_state_is_replaceable(tmp_path: Path) -> None:
    state = ManagedJobState(tmp_path / "job.json")
    first = state.create(["python", "worker.py"], tmp_path / "worker.log")
    state.update(str(first["id"]), status="succeeded", exit_code=0)

    second = state.create(["python", "worker.py"], tmp_path / "worker-2.log")

    assert second["id"] != first["id"]
    assert state.read()["status"] == "starting"


def test_detached_job_records_completion_and_log(tmp_path: Path) -> None:
    controller = ManagedQueueController(tmp_path, tmp_path / "pbot.sqlite3", tmp_path / "var")
    started = controller.start([sys.executable, "-c", "print('detached-ok', flush=True)"])

    assert started["status"] in {"starting", "running"}
    deadline = time.monotonic() + 5
    current = controller.status()
    while current and current["status"] in {"starting", "running"} and time.monotonic() < deadline:
        time.sleep(0.05)
        current = controller.status()

    assert current is not None
    assert current["status"] == "succeeded"
    assert current["exit_code"] == 0
    assert controller.log_tail() == ["detached-ok"]
