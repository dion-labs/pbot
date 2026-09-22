from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Iterator

from .storage import Store


ACTIVE_STATUSES = {"starting", "running", "stopping"}
TERMINAL_STATUSES = {"succeeded", "completed", "needs_attention", "failed", "stopped"}
JOB_TOKEN_ENV = "PBOT_MANAGED_JOB_ID"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:
        waited_pid, _status = os.waitpid(pid, os.WNOHANG)
        if waited_pid == pid:
            return False
    except ChildProcessError:
        pass
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip().startswith("Z"):
        return False
    return True


def runner_identity(pid: int, job_id: str) -> str:
    """Distinguish positive mismatch from unavailable process arguments."""
    result = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "command="],
        check=False, capture_output=True, text=True,
    )
    command = result.stdout.strip()
    if result.returncode or not command or (command.startswith("(") and command.endswith(")")):
        return "uncertain"
    # ps prints argv rather than shell-escaped source. Worker arguments may
    # contain unmatched quote characters; inspect only our fixed token fields.
    arguments = command.split()
    if len(arguments) == 1 and "python" in Path(arguments[0]).name.lower():
        return "uncertain"
    token = ["-m", "pbot.managed_job_runner", "--job-id", job_id]
    if any(arguments[index:index + len(token)] == token for index in range(len(arguments))):
        return "owned"
    return "unrelated"


def process_matches_job(pid: int, job_id: str) -> bool:
    """Require positive runner identity; false alone is not proof of reuse."""
    return process_alive(pid) and runner_identity(pid, job_id) == "owned"


def process_group_members(pgid: int) -> list[int]:
    """List executable members without reading unrelated process arguments."""
    result = subprocess.run(
        ["ps", "-ax", "-o", "pid=,pgid=,stat="],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError("Cannot inspect managed process group; ownership retained")
    members = []
    observed_processes = 0
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            observed_processes += 1
            if int(fields[1]) == pgid and not fields[2].startswith("Z"):
                members.append(int(fields[0]))
    if not observed_processes:
        raise RuntimeError("Process listing unavailable; managed ownership retained")
    return members


def process_has_job_token(pid: int, job_id: str) -> bool:
    # Children/grandchildren inherit this random launch marker. Inspect only
    # candidate group members, and never persist or log their environment.
    result = subprocess.run(
        ["ps", "eww", "-p", str(pid), "-o", "command="],
        check=False, capture_output=True, text=True,
    )
    return result.returncode == 0 and f"{JOB_TOKEN_ENV}={job_id}" in result.stdout.split()


def process_group_state(pid: int, job_id: str) -> tuple[str, list[int]]:
    """Return owned/gone/unrelated/uncertain; uncertainty never releases a job.

    A live runner proves its group via its exact command token. After its exit,
    every remaining member must retain the inherited marker before signalling.
    A different live group leader is a reused PID, not a target to terminate.
    """
    if pid <= 0:
        return "gone", []
    for _ in range(3):
        members = process_group_members(pid)
        if not members:
            return "gone", []
        if pid in members:
            identity = runner_identity(pid, job_id)
            if identity in {"owned", "unrelated"}:
                return identity, members
            continue  # Missing argv may mean inspection failure or runner exit.
        for member in members:
            if not process_has_job_token(member, job_id):
                if not process_alive(member):
                    break  # A descendant exited while being inspected.
                return "uncertain", members
        else:
            return "owned", members
    return "uncertain", members


def terminate_job_group(pid: int, job_id: str) -> None:
    """Stop an owned group, retaining ownership unless termination is proven."""
    for sig, timeout in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 3.0)):
        ownership, _members = process_group_state(pid, job_id)
        if ownership in {"gone", "unrelated"}:
            return
        if ownership != "owned":
            raise RuntimeError("Cannot verify remaining managed processes; no signal sent, ownership retained")
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ownership, _members = process_group_state(pid, job_id)
            if ownership in {"gone", "unrelated"}:
                return
            if ownership != "owned":
                raise RuntimeError("Cannot verify remaining managed processes; ownership retained")
            time.sleep(0.05)
    raise RuntimeError("Managed process group did not terminate; ownership retained")


def serialized_lifecycle(method):
    """Serialize controller actions across processes, including the spawn gap."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        path = self.data_dir / "managed-queue-lifecycle.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            return method(self, *args, **kwargs)
    return wrapped


class ManagedJobState:
    """Atomic JSON state for the single detached pbot queue worker."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield

    def _read_unlocked(self) -> dict[str, object] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write_unlocked(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def read(self) -> dict[str, object] | None:
        with self._locked():
            payload = self._read_unlocked()
            return dict(payload) if payload else None

    def create(self, command: list[str], log_path: Path) -> dict[str, object]:
        with self._locked():
            current = self._read_unlocked()
            if current:
                pid = int(current.get("pid") or 0)
                if pid:
                    ownership, _members = process_group_state(pid, str(current["id"]))
                    owned = ownership in {"owned", "uncertain"}
                else:
                    owned = current.get("status") in ACTIVE_STATUSES and process_alive(int(current.get("launcher_pid") or 0))
                if owned:
                    raise RuntimeError(f"Managed pbot job {current['id']} is already {current['status']}; processes still reserved")
            now = utc_now()
            payload: dict[str, object] = {
                "id": uuid.uuid4().hex[:12],
                "status": "starting",
                "pid": None,
                "launcher_pid": os.getpid(),
                "command": command,
                "log_path": str(log_path),
                "created_at": now,
                "started_at": None,
                "finished_at": None,
                "exit_code": None,
                "message": "Detached queue worker is starting",
            }
            self._write_unlocked(payload)
            return dict(payload)

    def update(self, job_id: str, **changes: object) -> dict[str, object]:
        with self._locked():
            payload = self._read_unlocked()
            if not payload or payload.get("id") != job_id:
                raise RuntimeError(f"Managed pbot job {job_id} is no longer current")
            payload.update(changes)
            self._write_unlocked(payload)
            return dict(payload)


class ManagedQueueController:
    def __init__(self, project_root: Path, database_path: Path, data_dir: Path) -> None:
        self.project_root = project_root
        self.database_path = database_path
        self.data_dir = data_dir
        self.state = ManagedJobState(data_dir / "managed-queue-job.json")
        self.store = Store(database_path)
        self._initialize_store()

    @serialized_lifecycle
    def _initialize_store(self) -> None:
        # A cold SQLite database can reject simultaneous WAL initialization.
        self.store.initialize()

    @serialized_lifecycle
    def start(self, queue_command: list[str]) -> dict[str, object]:
        job_id = uuid.uuid4().hex[:12]
        log_path = self.data_dir / "jobs" / f"queue-{job_id}.log"
        payload = self.state.create(queue_command, log_path)
        job_id = str(payload["id"])
        # create() owns the canonical id; align the preselected log filename.
        canonical_log = self.data_dir / "jobs" / f"queue-{job_id}.log"
        if canonical_log != log_path:
            payload = self.state.update(job_id, log_path=str(canonical_log))
            log_path = canonical_log
        process = None
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)

            runner = [
                sys.executable,
                "-m",
                "pbot.managed_job_runner",
                "--job-id",
                job_id,
                "--project-root",
                str(self.project_root),
                "--database",
                str(self.database_path),
                "--data-dir",
                str(self.data_dir),
                "--",
                *queue_command,
            ]
            with log_path.open("ab", buffering=0) as log:
                process = subprocess.Popen(
                    runner,
                    cwd=self.project_root,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                    env={**os.environ, JOB_TOKEN_ENV: job_id},
                )
            payload = self.state.update(job_id, pid=process.pid)
        except Exception as exc:
            if process is not None:
                try:
                    # Popen created a new session. Never release its reservation
                    # while that session might still execute a device command.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=3)
                    # Reaping the runner alone does not prove its descendants
                    # have stopped. Keep ownership until the group is clear.
                    terminate_job_group(process.pid, job_id)
                except (OSError, subprocess.TimeoutExpired, RuntimeError):
                    # Keep ownership active if termination cannot be confirmed.
                    # The runner also publishes its own PID independently.
                    self.state.update(
                        job_id,
                        pid=process.pid,
                        status="running",
                        message="Startup failed; worker cleanup unconfirmed; stop required",
                    )
                    raise
            recovery = self.store.recover_interrupted_work() if process is not None else {}
            self.state.update(
                job_id,
                pid=process.pid if process is not None else None,
                status="failed",
                finished_at=utc_now(),
                message=f"Could not launch detached worker: {exc}",
                recovery=recovery,
            )
            raise
        self.store.add_event(
            "job.started",
            f"Detached queue job {job_id} started",
            "success",
            {"job_id": job_id, "pid": process.pid, "log_path": str(log_path)},
        )
        return payload

    @serialized_lifecycle
    def status(self) -> dict[str, object] | None:
        return self._status_unlocked()

    def _status_unlocked(self) -> dict[str, object] | None:
        # The runner writes terminal state under this same lock before exiting.
        with self.state._locked():
            payload = self.state._read_unlocked()
            if not payload:
                return None
            status = str(payload.get("status"))
            pid = int(payload.get("pid") or 0)
            if pid:
                ownership, members = process_group_state(pid, str(payload["id"]))
            else:
                ownership = "owned" if process_alive(int(payload.get("launcher_pid") or 0)) else "gone"
                members = []
            owned = ownership in {"owned", "uncertain"}
            descendants_remain = any(member != pid for member in members)
            if pid and owned and (pid not in members or (status not in ACTIVE_STATUSES and descendants_remain)):
                payload.update(
                    status="stopping",
                    finished_at=None,
                    message="Runner exited but descendants remain; stop required before recovery or restart",
                )
                self.state._write_unlocked(payload)
            if status in ACTIVE_STATUSES and not owned:
                recovery = self.store.recover_interrupted_work()
                payload.update(
                    status="failed",
                    finished_at=utc_now(),
                    message="Managed worker disappeared before recording a terminal status",
                    recovery=recovery,
                )
                self.state._write_unlocked(payload)
                self.store.add_event(
                    "job.failed",
                    f"Detached queue job {payload['id']} disappeared; queue state recovered",
                    "error",
                    {"job_id": payload["id"], **recovery},
                )
            return payload

    @serialized_lifecycle
    def stop(self) -> dict[str, object]:
        payload = self._status_unlocked()
        if not payload:
            raise RuntimeError("No managed pbot job exists")
        if payload.get("status") not in ACTIVE_STATUSES:
            return payload
        job_id = str(payload["id"])
        pid = int(payload.get("pid") or 0)
        self.state.update(job_id, status="stopping", message="Stop requested")
        terminate_job_group(pid, job_id)
        recovery = self.store.recover_interrupted_work()
        payload = self.state.update(
            job_id,
            status="stopped",
            finished_at=utc_now(),
            message="Stopped by user; interrupted queue state recovered",
            recovery=recovery,
        )
        run_state = self.store.get_state()
        self.store.set_state(
            "ready",
            "Detached queue job stopped safely",
            str(run_state.get("device_serial") or "") or None,
        )
        self.store.add_event(
            "job.stopped",
            f"Detached queue job {job_id} stopped safely",
            "warning",
            {"job_id": job_id, **recovery},
        )
        return payload

    def log_tail(self, lines: int = 40) -> list[str]:
        payload = self.state.read()
        if not payload:
            return []
        path = Path(str(payload["log_path"]))
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(lines, 500)):]
