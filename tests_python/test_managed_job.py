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


def test_starting_reservation_rejects_duplicate_before_worker_pid(tmp_path: Path) -> None:
    state = ManagedJobState(tmp_path / "job.json")
    first = state.create(["synthetic-worker"], tmp_path / "first.log")
    with pytest.raises(RuntimeError, match="already"):
        state.create(["other-worker"], tmp_path / "second.log")
    assert state.read() == first


def test_failed_spawn_releases_reservation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = ManagedQueueController(tmp_path, tmp_path / "db.sqlite3", tmp_path / "var")
    def fail_spawn(*args, **kwargs):
        raise OSError("synthetic spawn failure")
    monkeypatch.setattr("pbot.managed_job.subprocess.Popen", fail_spawn)
    with pytest.raises(OSError, match="synthetic spawn failure"):
        controller.start(["synthetic-worker"])
    failed = controller.state.read()
    assert failed["status"] == "failed"
    assert failed["finished_at"]
    replacement = controller.state.create(["replacement"], tmp_path / "replacement.log")
    assert replacement["id"] != failed["id"]


def test_abandoned_start_is_recovered_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = ManagedQueueController(tmp_path, tmp_path / "db.sqlite3", tmp_path / "var")
    controller.state.create(["synthetic-worker"], tmp_path / "worker.log")
    monkeypatch.setattr("pbot.managed_job.process_alive", lambda pid: False)
    assert controller.status()["status"] == "failed"
    assert controller.status()["status"] == "failed"
    assert len([e for e in controller.store.recent_events() if e["kind"] == "job.failed"]) == 1


def test_stale_worker_cannot_update_replacement(tmp_path: Path) -> None:
    state = ManagedJobState(tmp_path / "job.json")
    old = state.create(["old"], tmp_path / "old.log")
    state.update(old["id"], status="failed")
    current = state.create(["new"], tmp_path / "new.log")
    with pytest.raises(RuntimeError, match="no longer current"):
        state.update(old["id"], status="succeeded")
    assert state.read() == current


def test_concurrent_controllers_launch_only_one_worker(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)
    marker = tmp_path / "launches.txt"
    controllers = [ManagedQueueController(tmp_path, tmp_path / "db.sqlite3", tmp_path / "var") for _ in range(2)]
    command = [sys.executable, "-c", "import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text('one'); time.sleep(0.5)", str(marker)]
    def start(controller):
        barrier.wait(timeout=5)
        try:
            return controller.start(command)
        except RuntimeError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(start, controllers))
    try:
        assert sum(isinstance(result, dict) for result in outcomes) == 1
        assert sum(isinstance(result, str) and "already" in result for result in outcomes) == 1
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = controllers[0].status()
            if current["status"] not in {"starting", "running"}:
                break
            time.sleep(0.05)
        assert current["status"] == "succeeded"
        assert marker.read_text() == "one"
    finally:
        controllers[0].stop()


def test_nonzero_worker_exit_is_failure(tmp_path: Path) -> None:
    controller = ManagedQueueController(tmp_path, tmp_path / "db.sqlite3", tmp_path / "var")
    controller.start([sys.executable, "-c", "print('synthetic-error', flush=True); raise SystemExit(7)"])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = controller.status()
        if current["status"] not in {"starting", "running"}:
            break
        time.sleep(0.05)
    assert current["status"] == "failed"
    assert current["exit_code"] == 7
    assert controller.log_tail() == ["synthetic-error"]


def test_log_tail_handles_absence_and_bounds(tmp_path: Path) -> None:
    controller = ManagedQueueController(tmp_path, tmp_path / "db.sqlite3", tmp_path / "var")
    assert controller.log_tail() == []
    log = tmp_path / "missing.log"
    controller.state.create(["synthetic-worker"], log)
    assert controller.log_tail() == []
    log.write_text("\n".join(str(i) for i in range(700)))
    assert controller.log_tail(10000) == [str(i) for i in range(200, 700)]
    assert controller.log_tail(0) == ["699"]
