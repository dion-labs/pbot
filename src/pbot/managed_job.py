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
            if current and current.get("status") in ACTIVE_STATUSES and process_alive(int(current.get("pid") or current.get("launcher_pid") or 0)):
                raise RuntimeError(f"Managed pbot job {current['id']} is already {current['status']}")
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
                )
            payload = self.state.update(job_id, pid=process.pid)
        except Exception as exc:
            self.state.update(
                job_id,
                status="failed",
                finished_at=utc_now(),
                message=f"Could not launch detached worker: {exc}",
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
        payload = self.state.read()
        if not payload:
            return None
        status = str(payload.get("status"))
        pid = int(payload.get("pid") or payload.get("launcher_pid") or 0)
        if status in ACTIVE_STATUSES and not process_alive(pid):
            recovery = self.store.recover_interrupted_work()
            payload = self.state.update(
                str(payload["id"]),
                status="failed",
                finished_at=utc_now(),
                message="Managed worker disappeared before recording a terminal status",
                recovery=recovery,
            )
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
        if process_alive(pid):
            os.killpg(pid, signal.SIGTERM)
            deadline = time.monotonic() + 3
            while process_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            if process_alive(pid):
                os.killpg(pid, signal.SIGKILL)
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
