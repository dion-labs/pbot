"""Opt-in real OS-boundary acceptance for PB-025; no ADB, network or user data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import uuid


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests_integration" / "fixtures" / "managed_process_fixture.py"


def snapshot(pid: int) -> dict | None:
    for _ in range(5):
        result = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "pid=,ppid=,pgid=,stat=,lstart=,command="],
                                capture_output=True, text=True, check=False)
        fields = result.stdout.strip().split(maxsplit=9)
        if result.returncode or len(fields) < 10:
            return None
        value = {"pid": int(fields[0]), "ppid": int(fields[1]), "pgid": int(fields[2]), "stat": fields[3],
                 "creation_time": " ".join(fields[4:9]), "command": fields[9]}
        if not (value["command"].startswith("(") and value["command"].endswith(")")
                and not value["stat"].startswith("Z")):
            return value
        # macOS can briefly omit argv during process exit. Retry the observation
        # instead of treating that transient snapshot as new signal authority.
        time.sleep(0.01)
    return value  # A persistently unverifiable process still fails closed.


def group_members(pgid: int) -> list[dict]:
    # Read only numeric PID/group fields globally; command lines are read only
    # for members of a process group created by this harness.
    result = subprocess.run(["ps", "-ax", "-o", "pid=,pgid="], capture_output=True, text=True, check=True)
    pids = [int(parts[0]) for line in result.stdout.splitlines()
            if len(parts := line.split()) == 2 and int(parts[1]) == pgid]
    return [value for pid in pids if (value := snapshot(pid)) is not None]


def wait_for(predicate, description: str, seconds: float = 8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.025)
    raise AssertionError(f"Timed out: {description}")


class Scenario:
    def __init__(self, root: Path, name: str) -> None:
        self.root = root / name
        self.root.mkdir()
        (self.root / "data").mkdir()
        self.token = uuid.uuid4().hex
        (self.root / "fixture-token").write_text(self.token)
        shutil.copyfile(FIXTURE, self.root / "fixture.py")
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONUNBUFFERED": "1",
                    "PYTHONUTF8": "1", "PBOT_ROOT": str(self.root), "PBOT_DATA_DIR": str(self.root / "data"),
                    "PBOT_DATABASE": str(self.root / "data" / "fixture.sqlite3"),
                    "PBOT_SCREENSHOT": str(self.root / "unused.png"), "PBOT_ADB": "/nonexistent/fixture-adb"}
        self.processes: list[subprocess.Popen] = []
        self.groups: set[int] = set()
        self.identities: dict[int, dict] = {}
        self.events: list[dict] = []
        self.job = None

    def own(self, value: dict) -> None:
        words = value["command"].split()
        assert any(words[i:i+2] == ["--token", self.token] for i in range(len(words))), value
        assert value["pgid"] > 1 and value["pgid"] != os.getpgrp()
        prior = self.identities.get(value["pid"])
        if prior:
            assert prior["creation_time"] == value["creation_time"], "PID creation identity changed"
        self.identities[value["pid"]] = value
        self.groups.add(value["pgid"])

    def collect(self) -> None:
        for path in self.root.glob("manifest-*.json"):
            record = json.loads(path.read_text())
            assert record["token"] == self.token
            value = snapshot(record["pid"])
            if value and not value["stat"].startswith("Z"):
                self.own(value)
        state_path = self.root / "data" / "managed-queue-job.json"
        if state_path.exists():
            record = json.loads(state_path.read_text())
            value = snapshot(int(record.get("pid") or 0)) if record.get("pid") else None
            if value and not value["stat"].startswith("Z"):
                self.own(value)

    def spawn_action(self, operation: str, *, behavior="graceful", barrier=None, hold=False):
        label = f"controller-{uuid.uuid4().hex[:8]}"
        result = self.root / f"result-{label}.json"
        command = [sys.executable, str(self.root / "fixture.py"), "--root", str(self.root), "--token", self.token,
                   "--role", label, "--operation", operation, "--result", str(result), "--behavior", behavior]
        if barrier:
            command += ["--barrier", str(barrier)]
        if hold:
            command += ["--hold"]
        with (self.root / f"{label}.log").open("wb") as log:
            process = subprocess.Popen(command, cwd=self.root, env=self.env, stdout=log, stderr=log, start_new_session=True)
        self.processes.append(process)
        value = snapshot(process.pid)
        if value:
            self.own(value)
        return process, result

    def result(self, action, *, hold=False):
        process, path = action
        def result_ready():
            self.collect()
            return path.exists()
        wait_for(result_ready, f"controller result {path.name}")
        result = json.loads(path.read_text())
        if not hold:
            assert process.wait(timeout=5) == 0
        self.events.append(result)
        if result.get("job"):
            self.job = result["job"]
        self.collect()
        return result

    def action(self, operation, **kwargs):
        return self.result(self.spawn_action(operation, **kwargs), hold=kwargs.get("hold", False))

    def tree_ready(self):
        wait_for(lambda: len(list(self.root.glob("manifest-grandchild-*.json"))) > 0, "grandchild ready")
        self.collect()
        return self.job

    def signal_owned(self, pid: int, sig: int, *, whole_group: bool):
        value = snapshot(pid)
        assert value and not value["stat"].startswith("Z"), "Owned signal target already gone"
        self.own(value)
        members = group_members(value["pgid"])
        for member in members:
            if not member["stat"].startswith("Z"):
                self.own(member)
        if whole_group:
            os.killpg(value["pgid"], sig)
        else:
            # Parent-only interruption: the PID, start identity and its complete
            # fixture-owned group were verified immediately before this signal.
            os.kill(pid, sig)
        self.events.append({"signal": sig, "pid": pid, "pgid": value["pgid"], "whole_group": whole_group})

    def assert_tree_gone(self, pgid: int, seconds=4):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            members = group_members(pgid)
            if not members:
                return
            time.sleep(0.05)
        self.events.append({"survivors": members})
        raise AssertionError(f"Owned process group {pgid} survived: {[(p['pid'], p['stat']) for p in members]}")

    def stop_and_check(self):
        group = int(self.job["pid"])
        stopped = self.action("stop")
        assert stopped["outcome"] == "ok" and stopped["job"]["status"] == "stopped", stopped
        self.assert_tree_gone(group)
        assert stopped["job"]["recovery"] == {"interrupted_attempts": 1, "released_claims": 1}
        return stopped

    def cleanup(self):
        self.collect()
        for group in sorted(self.groups):
            members = group_members(group)
            live = [member for member in members if not member["stat"].startswith("Z")]
            for member in live:
                self.own(member)
            if live:
                os.killpg(group, signal.SIGKILL)
                self.events.append({"cleanup_group": group, "members": live})
        for process in self.processes:
            process.wait(timeout=5)
        for group in sorted(self.groups):
            self.assert_tree_gone(group)


def concurrent_launch(case: Scenario):
    barrier = case.root / "start-barrier"
    contenders = [case.spawn_action("start", barrier=barrier) for _ in range(2)]
    for _, path in contenders:
        wait_for(path.with_suffix(".ready").exists, "contender waiting")
    barrier.touch()
    results = [case.result(item) for item in contenders]
    assert sorted(item["outcome"] for item in results) == ["ok", "rejected"], results
    assert "already" in next(item["error"] for item in results if item["outcome"] == "rejected")
    case.tree_ready()
    assert len(list(case.root.glob("manifest-child-*.json"))) == 1
    case.stop_and_check()


def graceful_stop(case: Scenario):
    assert case.action("start")["outcome"] == "ok"
    case.tree_ready()
    case.stop_and_check()
    assert len(list(case.root.glob("term-child-*.json"))) == 1
    assert len(list(case.root.glob("term-grandchild-*.json"))) == 1


def stubborn_grandchild(case: Scenario):
    assert case.action("start", behavior="stubborn")["outcome"] == "ok"
    case.tree_ready()
    case.stop_and_check()


def controller_interruption(case: Scenario):
    parent = case.spawn_action("start", hold=True)
    result = case.result(parent, hold=True)
    case.tree_ready()
    original = result["job"]["id"]
    case.signal_owned(parent[0].pid, signal.SIGKILL, whole_group=True)
    parent[0].wait(timeout=5)
    assert case.action("status")["job"]["status"] == "running"
    assert case.action("start")["outcome"] == "rejected"
    case.stop_and_check()
    assert case.action("start")["job"]["id"] != original
    wait_for(lambda: len(list(case.root.glob("manifest-grandchild-*.json"))) == 2, "restarted grandchild")
    case.collect()
    case.stop_and_check()


def runner_interruption(case: Scenario):
    first = case.action("start")["job"]
    case.tree_ready()
    case.signal_owned(int(first["pid"]), signal.SIGKILL, whole_group=False)
    wait_for(lambda: snapshot(int(first["pid"])) is None, "interrupted runner exit")
    assert case.action("start")["outcome"] == "rejected"
    result = case.action("stop")
    # The controller must clear all remaining owned descendants before restart.
    case.assert_tree_gone(int(first["pid"]))
    assert result["job"]["status"] in {"failed", "stopped"}
    second = case.action("start")
    assert second["outcome"] == "ok" and second["job"]["id"] != first["id"]
    wait_for(lambda: len(list(case.root.glob("manifest-grandchild-*.json"))) == 2, "restarted after runner loss")
    case.collect()
    case.stop_and_check()


def unrelated_identity(case: Scenario):
    from pbot.managed_job import ManagedJobState
    command = [sys.executable, str(case.root / "fixture.py"), "--root", str(case.root), "--token", case.token,
               "--role", "unrelated"]
    with (case.root / "unrelated.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=case.root, env=case.env, stdout=log, stderr=log, start_new_session=True)
    case.processes.append(process)
    wait_for(lambda: list(case.root.glob("manifest-unrelated-*.json")), "unrelated fixture ready")
    case.collect()
    state = ManagedJobState(case.root / "data" / "managed-queue-job.json")
    job = state.create(["unrelated-fixture"], case.root / "unused.log")
    state.update(job["id"], pid=process.pid, status="running")
    result = case.action("stop")
    assert result["job"]["status"] == "failed"
    assert process.poll() is None
    assert not list(case.root.glob("term-unrelated-*.json"))
    # Keep this unrelated owned fixture alive through the entire replacement.
    case.action("start")
    case.tree_ready()
    case.stop_and_check()
    assert process.poll() is None


def natural_completion(case: Scenario):
    first = case.action("start", behavior="complete")["job"]
    case.tree_ready()
    wait_for(lambda: case.action("status")["job"]["status"] == "succeeded", "natural completion")
    case.assert_tree_gone(int(first["pid"]))
    assert not list(case.root.glob("term-*.json"))
    second = case.action("start", behavior="complete")["job"]
    assert second["id"] != first["id"]
    wait_for(lambda: case.action("status")["job"]["status"] == "succeeded", "completion after restart")
    case.assert_tree_gone(int(second["pid"]))


def stopper_interruption(case: Scenario):
    case.action("start", behavior="stubborn")
    case.tree_ready()
    stopper = case.spawn_action("stop")
    wait_for(lambda: list(case.root.glob("term-grandchild-*.json")), "stop signal delivered")
    # The grandchild intentionally ignores TERM, leaving a bounded interval in
    # which to interrupt only the separately launched stop controller.
    case.signal_owned(stopper[0].pid, signal.SIGKILL, whole_group=True)
    stopper[0].wait(timeout=5)
    assert case.action("status")["job"]["status"] == "stopping"
    assert case.action("start")["outcome"] == "rejected"
    case.stop_and_check()


def uncertain_descendant(case: Scenario):
    first = case.action("start", behavior="drop-marker")["job"]
    case.tree_ready()
    case.signal_owned(int(first["pid"]), signal.SIGKILL, whole_group=False)
    wait_for(lambda: snapshot(int(first["pid"])) is None, "runner exit with unmarked descendant")
    result = case.action("stop")
    assert result["outcome"] == "rejected" and "ownership retained" in result["error"]
    assert case.action("status")["job"]["status"] == "stopping"
    assert case.action("start")["outcome"] == "rejected"
    assert not list(case.root.glob("term-*.json")), "Uncertain group must not be signalled"
    # The harness can clean these processes using its separate fixture token
    # and creation identities, which the product must not assume it possesses.


def completion_with_descendant(case: Scenario):
    case.action("start", behavior="orphan-on-success")
    case.tree_ready()
    state_path = case.root / "data" / "managed-queue-job.json"
    wait_for(lambda: json.loads(state_path.read_text())["status"] == "succeeded", "runner records direct child success")
    assert case.action("status")["job"]["status"] == "stopping"
    assert case.action("start")["outcome"] == "rejected"
    case.stop_and_check()


def terminal_publication_window(case: Scenario):
    import sqlite3
    first = case.action("start", behavior="complete")["job"]
    case.tree_ready()
    barrier = case.root / "terminal-probe-barrier"
    probe = case.spawn_action("status", barrier=barrier)
    wait_for(probe[1].with_suffix(".ready").exists, "status observer initialized")
    connection = sqlite3.connect(case.root / "data" / "fixture.sqlite3", isolation_level=None)
    try:
        # A real temporary SQLite writer holds the runner in its final event
        # write after terminal JSON publication. No product methods are mocked.
        connection.execute("BEGIN IMMEDIATE")
        state_path = case.root / "data" / "managed-queue-job.json"
        wait_for(lambda: json.loads(state_path.read_text())["status"] == "succeeded", "terminal JSON published")
        barrier.touch()
        result = case.result(probe)
        assert result["job"]["status"] == "succeeded", result
    finally:
        connection.rollback()
        connection.close()
    case.assert_tree_gone(int(first["pid"]))


def reservation_interruption(case: Scenario):
    parent = case.spawn_action("reserve", hold=True)
    reserved = case.result(parent, hold=True)["job"]
    assert reserved["pid"] is None
    assert case.action("start")["outcome"] == "rejected"
    case.signal_owned(parent[0].pid, signal.SIGKILL, whole_group=True)
    parent[0].wait(timeout=5)
    status = case.action("status")["job"]
    assert status["status"] == "failed"
    assert status["recovery"] == {"interrupted_attempts": 0, "released_claims": 0}
    replacement = case.action("start")["job"]
    assert replacement["id"] != reserved["id"]
    case.tree_ready()
    case.stop_and_check()


def pid_publication_failure(case: Scenario):
    import errno
    result = case.action("start-failing-publication")
    assert result["outcome"] == "filesystem-error" and result["errno"] in {errno.EACCES, errno.EPERM}, result
    assert result["job"]["status"] == "failed"
    # The runner independently recorded its PID before the parent write failed.
    case.assert_tree_gone(int(result["job"]["pid"]))
    assert result["job"].get("recovery") == {"interrupted_attempts": 1, "released_claims": 1}, result
    replacement = case.action("start")["job"]
    assert replacement["id"] != result["job"]["id"]
    wait_for(lambda: len(list(case.root.glob("manifest-grandchild-*.json"))) == 2, "restart after PID write failure")
    case.collect()
    case.stop_and_check()


CASES = {"concurrent-launch": concurrent_launch, "graceful-stop": graceful_stop,
         "stubborn-grandchild": stubborn_grandchild, "controller-interruption": controller_interruption,
         "runner-interruption": runner_interruption, "unrelated-identity": unrelated_identity,
         "natural-completion": natural_completion, "stopper-interruption": stopper_interruption,
         "uncertain-descendant": uncertain_descendant, "completion-with-descendant": completion_with_descendant, "terminal-publication-window": terminal_publication_window, "reservation-interruption": reservation_interruption, "pid-publication-failure": pid_publication_failure}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly opt in to disposable processes and signals")
    parser.add_argument("--repeat", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--case", choices=CASES, action="append")
    args = parser.parse_args()
    if not args.run:
        parser.error("Use --run to opt in; no fixture processes were started")
    if os.name != "posix":
        parser.error("The managed worker requires a POSIX process/group platform")
    if os.geteuid() == 0 and (not args.case or "pid-publication-failure" in args.case):
        parser.error("The real permission-failure case requires a non-root user")
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt("Harness termination requested")
    signal.signal(signal.SIGTERM, interrupt)
    evidence = Path(tempfile.mkdtemp(prefix="pbot-process-acceptance-"))
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
              "python": sys.version, "sqlite": sqlite3.sqlite_version, "evidence_dir": str(evidence), "cases": [],
              "source_sha256": {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in [REPO / "src/pbot/managed_job.py", REPO / "src/pbot/managed_job_runner.py", FIXTURE, Path(__file__)]}}
    print(f"Evidence: {evidence}", flush=True)
    for iteration in range(args.repeat):
        for name in args.case or CASES:
            case = Scenario(evidence, f"{iteration + 1:02d}-{name}")
            result = {"case": name, "id": f"PB-025.{list(CASES).index(name) + 1:02d}",
                      "iteration": iteration + 1, "token": case.token, "status": "passed"}
            try:
                CASES[name](case)
            except BaseException as exc:
                result.update(status="failed", error=str(exc), traceback=traceback.format_exc())
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    result["interrupted"] = True
            finally:
                try:
                    case.cleanup()
                    result["cleanup"] = "verified-empty"
                except BaseException as exc:
                    result.update(status="failed", cleanup_error=str(exc))
                result.update(identities=list(case.identities.values()), events=case.events,
                              manifests=[json.loads(path.read_text()) for path in case.root.glob("manifest-*.json")])
                report["cases"].append(result)
                (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
                print(f"{name}: {result['status']} (cleanup: {result.get('cleanup', result.get('cleanup_error'))})", flush=True)
            if result.get("interrupted"):
                return 130
            if result.get("cleanup_error"):
                # Never proceed to further work after uncertain process cleanup.
                return 2
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = all(result["status"] == "passed" for result in report["cases"])
    (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
