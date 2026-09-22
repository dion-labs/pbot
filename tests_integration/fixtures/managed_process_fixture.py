"""Inert subprocess fixture. Invoked only by the opt-in lifecycle harness."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--behavior", choices=["graceful", "stubborn", "complete", "orphan-on-success", "drop-marker"], default="graceful")
    parser.add_argument("--operation", choices=["start", "status", "stop", "reserve", "start-failing-publication"])
    parser.add_argument("--result", type=Path)
    parser.add_argument("--barrier", type=Path)
    parser.add_argument("--hold", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if (root / "fixture-token").read_text().strip() != args.token:
        raise SystemExit("Not a harness-owned temporary project")
    if root != Path.cwd().resolve() or root.is_symlink():
        raise SystemExit("Fixture must run in its own temporary project")
    record = {"pid": os.getpid(), "ppid": os.getppid(), "pgid": os.getpgrp(), "token": args.token,
              "role": args.role, "created_monotonic_ns": time.monotonic_ns(),
              "created_utc": time.time(),
              "creation_time": subprocess.check_output(["ps", "-p", str(os.getpid()), "-o", "lstart="], text=True).strip()}
    write_json(root / f"manifest-{args.role}-{os.getpid()}.json", record)

    if args.role.startswith("controller"):
        from pbot.managed_job import ManagedQueueController
        controller = ManagedQueueController(root, root / "data" / "fixture.sqlite3", root / "data")
        if args.operation == "start-failing-publication":
            # Inject an actual temporary-directory permission failure, not a
            # fabricated Popen, signal, liveness or storage-error result.
            original_update = controller.state.update
            injected = False
            def publish_with_filesystem_failure(job_id, **changes):
                nonlocal injected
                if "pid" in changes and not injected:
                    injected = True
                    deadline = time.monotonic() + 10
                    while not list(root.glob("manifest-grandchild-*.json")):
                        if time.monotonic() > deadline:
                            raise RuntimeError("Fixture descendants did not become ready")
                        time.sleep(0.01)
                    data = root / "data"
                    original_mode = stat.S_IMODE(data.stat().st_mode)
                    try:
                        data.chmod(0o500)
                        return original_update(job_id, **changes)
                    finally:
                        data.chmod(original_mode)
                return original_update(job_id, **changes)
            controller.state.update = publish_with_filesystem_failure
        if args.barrier:
            args.result.with_suffix(".ready").touch()
            deadline = time.monotonic() + 10
            while not args.barrier.exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("Harness barrier timed out")
                time.sleep(0.01)
        try:
            if args.operation == "reserve":
                job = controller.state.create(["inert-reserved-command"], root / "data" / "reserved.log")
            elif args.operation in {"start", "start-failing-publication"}:
                job = controller.start([sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                                        "--token", args.token, "--role", "child", "--behavior", args.behavior])
            elif args.operation == "stop":
                job = controller.stop()
            else:
                job = controller.status()
            write_json(args.result, {"outcome": "ok", "job": job})
        except OSError as exc:
            if args.operation != "start-failing-publication":
                raise
            write_json(args.result, {"outcome": "filesystem-error", "errno": exc.errno,
                                     "error": str(exc), "job": controller.state.read()})
        except RuntimeError as exc:
            write_json(args.result, {"outcome": "rejected", "error": str(exc)})
        if args.hold:
            time.sleep(45)  # Bounded even if the harness is interrupted.
        return

    stopping = False
    def terminate(signum, _frame):
        nonlocal stopping
        write_json(root / f"term-{args.role}-{os.getpid()}.json", {**record, "signal": signum})
        if not (args.role == "grandchild" and args.behavior == "stubborn"):
            stopping = True
    signal.signal(signal.SIGTERM, terminate)
    child = None
    if args.role == "child":
        from pbot.storage import Store
        store = Store(root / "data" / "fixture.sqlite3")
        store.initialize()
        attempt = store.start_attempt("fixture:battle", "Fixture", "Intermediate", "Inert battle", "owned-fixture", "auto")
        store.claim_battle("fixture:battle")
        write_json(root / f"attempt-{os.getpid()}.json", {"attempt": attempt})
        child_env = dict(os.environ)
        if args.behavior == "drop-marker":
            child_env.pop("PBOT_MANAGED_JOB_ID", None)
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                                  "--token", args.token, "--role", "grandchild", "--behavior", args.behavior], env=child_env)
    print(f"fixture-ready {args.role} {os.getpid()}", flush=True)
    started = time.monotonic()
    lifetime = 0.4 if args.behavior == "complete" or (args.behavior == "orphan-on-success" and args.role == "child") else 45
    while not stopping and time.monotonic() - started < lifetime:
        (root / f"heartbeat-{args.role}-{os.getpid()}").write_text(str(time.monotonic_ns()))
        time.sleep(0.025)
    if child and args.behavior != "orphan-on-success":
        try:
            child.wait(timeout=0.7 if stopping else 2)
        except subprocess.TimeoutExpired:
            # Deliberately leave a stubborn descendant for the real controller
            # to handle. The harness owns and verifies cleanup of this group.
            pass
    print(f"fixture-exit {args.role} {os.getpid()}", flush=True)


if __name__ == "__main__":
    main()
