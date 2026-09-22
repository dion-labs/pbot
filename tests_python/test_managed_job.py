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
    monkeypatch.setattr("pbot.managed_job.process_matches_job", lambda pid, job_id: pid == 1234)
    monkeypatch.setattr("pbot.managed_job.process_group_state", lambda pid, job_id: ("owned", [pid]) if pid == 1234 else ("gone", []))

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


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_pid_publication_failure_cannot_leave_replaceable_live_worker(tmp_path: Path, monkeypatch, cleanup_fails):
    import signal

    controller = ManagedQueueController(tmp_path, tmp_path / "db.sqlite3", tmp_path / "var")
    alive = set()
    killed = []
    class FakeProcess:
        pid = 987654
        def wait(self, timeout):
            assert self.pid not in alive
            return -signal.SIGKILL
    def spawn(*args, **kwargs):
        alive.add(FakeProcess.pid)
        return FakeProcess()
    def kill_group(pid, sig):
        assert pid == FakeProcess.pid
        assert sig == signal.SIGKILL
        if cleanup_fails:
            raise PermissionError("synthetic cleanup failure")
        killed.append(pid)
        alive.remove(pid)
    monkeypatch.setattr("pbot.managed_job.subprocess.Popen", spawn)
    monkeypatch.setattr("pbot.managed_job.os.killpg", kill_group)
    monkeypatch.setattr("pbot.managed_job.process_alive", lambda pid: pid in alive)
    monkeypatch.setattr("pbot.managed_job.process_matches_job", lambda pid, job_id: pid in alive)
    monkeypatch.setattr("pbot.managed_job.process_group_state", lambda pid, job_id: ("owned", [pid]) if pid in alive else ("gone", []))
    update = controller.state.update
    failed_once = False
    def fail_first_pid(job_id, **changes):
        nonlocal failed_once
        if "pid" in changes and not failed_once:
            failed_once = True
            raise OSError("synthetic PID publication failure")
        return update(job_id, **changes)
    monkeypatch.setattr(controller.state, "update", fail_first_pid)
    with pytest.raises(OSError):
        controller.start(["synthetic-worker"])
    if cleanup_fails:
        assert controller.state.read()["status"] == "running"
        with pytest.raises(RuntimeError, match="already"):
            controller.start(["second-worker"])
        assert alive == {FakeProcess.pid}
    else:
        assert controller.state.read()["status"] == "failed"
        assert not alive
        assert killed == [FakeProcess.pid]
        controller.state.create(["replacement"], tmp_path / "replacement.log")



def test_reused_pid_is_never_signalled(tmp_path: Path, monkeypatch):
    controller = ManagedQueueController(tmp_path, tmp_path / "db.sqlite3", tmp_path / "var")
    job = controller.state.create(["synthetic-worker"], tmp_path / "worker.log")
    controller.state.update(job["id"], status="running", pid=987654)
    monkeypatch.setattr("pbot.managed_job.process_alive", lambda pid: True)
    monkeypatch.setattr("pbot.managed_job.process_group_members", lambda pid: [987654])
    from types import SimpleNamespace
    monkeypatch.setattr("pbot.managed_job.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="unrelated application --job-id other"))
    def forbidden_signal(*args):
        raise AssertionError("Unrelated reused PID must not be signalled")
    monkeypatch.setattr("pbot.managed_job.os.killpg", forbidden_signal)
    assert controller.stop()["status"] == "failed"
    assert controller.state.create(["replacement"], tmp_path / "replacement.log")["id"] != job["id"]


@pytest.mark.parametrize("command,expected", [
    ("python -m pbot.managed_job_runner --job-id synthetic123 -- other", True),
    ('python -m pbot.managed_job_runner --job-id synthetic123 -- print("', True),
    ("python -m pbot.managed_job_runner --job-id synthetic1234 -- other", False),
    ("python -m unrelated --job-id synthetic123", False),
    ('broken "command', False),
])
def test_runner_identity_requires_exact_launch_token(monkeypatch, command, expected):
    from types import SimpleNamespace
    from pbot.managed_job import process_matches_job
    monkeypatch.setattr("pbot.managed_job.process_alive", lambda pid: True)
    monkeypatch.setattr("pbot.managed_job.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=command))
    assert process_matches_job(987654, "synthetic123") is expected



def test_unconfirmed_group_termination_keeps_claims_and_reservation(tmp_path: Path, monkeypatch):
    import itertools
    import signal
    controller = ManagedQueueController(tmp_path, tmp_path / "db.sqlite3", tmp_path / "var")
    job = controller.state.create(["synthetic-worker"], tmp_path / "worker.log")
    controller.state.update(job["id"], pid=987654, status="running")
    attempt = controller.store.start_attempt("fixture:battle", "Fixture", "Intermediate", "Inert", "owned", "auto")
    controller.store.claim_battle("fixture:battle")
    monkeypatch.setattr("pbot.managed_job.process_group_state", lambda pid, job_id: ("owned", [pid]))
    clock = itertools.count()
    monkeypatch.setattr("pbot.managed_job.time.monotonic", lambda: float(next(clock)))
    monkeypatch.setattr("pbot.managed_job.time.sleep", lambda seconds: None)
    signals = []
    monkeypatch.setattr("pbot.managed_job.os.killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(RuntimeError, match="did not terminate; ownership retained"):
        controller.stop()
    assert signals == [(987654, signal.SIGTERM), (987654, signal.SIGKILL)]
    assert controller.state.read()["status"] == "stopping"
    with controller.store.connect() as connection:
        assert connection.execute("SELECT finished_at FROM attempts WHERE id = ?", (attempt,)).fetchone()[0] is None
        assert connection.execute("SELECT state FROM battle_work WHERE battle_id = 'fixture:battle'").fetchone()[0] == "in_progress"
    with pytest.raises(RuntimeError, match="already"):
        controller.state.create(["replacement"], tmp_path / "other.log")



@pytest.mark.parametrize("returncode,command", [(1, ""), (0, ""), (0, "(python3.13)"), (0, "/usr/bin/python3")])
def test_unavailable_runner_identity_never_releases_or_signals(tmp_path: Path, monkeypatch, returncode, command):
    from types import SimpleNamespace
    from pbot.managed_job import process_group_state
    controller = ManagedQueueController(tmp_path, tmp_path / "db.sqlite3", tmp_path / "var")
    job = controller.state.create(["synthetic-worker"], tmp_path / "worker.log")
    controller.state.update(job["id"], pid=987654, status="running")
    monkeypatch.setattr("pbot.managed_job.process_group_members", lambda pid: [987654, 987655])
    monkeypatch.setattr("pbot.managed_job.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=returncode, stdout=command))
    def forbidden(*args):
        raise AssertionError("Uncertain ownership must not be signalled")
    monkeypatch.setattr("pbot.managed_job.os.killpg", forbidden)
    assert process_group_state(987654, job["id"])[0] == "uncertain"
    assert controller.status()["status"] == "running"
    with pytest.raises(RuntimeError, match="already"):
        controller.state.create(["replacement"], tmp_path / "replacement.log")
    with pytest.raises(RuntimeError, match="ownership retained"):
        controller.stop()
    assert controller.state.read()["status"] == "stopping"


def test_empty_process_listing_is_not_proof_of_termination(monkeypatch):
    from types import SimpleNamespace
    from pbot.managed_job import process_group_state
    monkeypatch.setattr("pbot.managed_job.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=""))
    with pytest.raises(RuntimeError, match="ownership retained"):
        process_group_state(987654, "synthetic")
