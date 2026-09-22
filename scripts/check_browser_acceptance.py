"""Opt-in disposable Chrome/UI/HTTP acceptance; never uses a real adapter."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
import uuid

from check_process_lifecycle import snapshot


REPO = Path(__file__).resolve().parents[1]
DEFAULT_PLAYWRIGHT = REPO.parent / "deskmux.dionlabs.ai/node_modules/@playwright/test"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
FIXTURES = ["tests_integration/fixtures/browser_api.py", "tests_integration/fixtures/browser_ui.mjs",
            "tests_integration/browser_acceptance.mjs"]


def source_paths(repo: Path) -> set[str]:
    if (repo / ".git").exists():
        return set(subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")) - {""}
    # Source archives have no Git index. Copy only build/configuration files
    # and code/assets, never scan the checkout's runtime or environment files.
    root_files = {"package.json", "package-lock.json", "vite.config.ts", "next.config.ts", "next-env.d.ts",
                  "tsconfig.json", "postcss.config.mjs", "eslint.config.mjs", "wrangler.jsonc", "pyproject.toml", "uv.lock"}
    files = {name for name in root_files if (repo / name).is_file()}
    extensions = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".css", ".json", ".jsonc",
                  ".png", ".svg", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".swift"}
    for name in ("app", "src", "worker", "public", "scripts", "tests_integration", "resources"):
        directory = repo / name
        if directory.is_symlink():
            raise AssertionError(f"Source directory is a symlink: {name}")
        if directory.exists():
            files.update(str(file.relative_to(repo)) for file in directory.rglob("*")
                         if file.is_file() and file.suffix in extensions and "__pycache__" not in file.parts)
    return files


class OwnedProcesses:
    def __init__(self):
        self.processes = []
        self.identities = {}
        self.uncertain_candidates = set()

    @staticmethod
    def process_table():
        result = subprocess.run(["ps", "-ax", "-o", "pid=,ppid="], capture_output=True, text=True, check=True)
        rows = {}
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            fields = line.split()
            if len(fields) != 2 or not all(field.isdigit() for field in fields):
                raise RuntimeError("Unusable process listing; cleanup remains unconfirmed")
            rows[int(fields[0])] = int(fields[1])
        if not rows:
            raise RuntimeError("Empty process listing; cleanup remains unconfirmed")
        return rows

    def collect(self):
        rows = self.process_table()
        # A retained Popen handle proves a direct child is still ours, but a
        # missing initial snapshot is not permission to claim cleanup later.
        for process in self.processes:
            if process.poll() is None:
                value = snapshot(process.pid)
                if value and process.poll() is None:
                    previous = self.identities.get(process.pid)
                    if previous and previous["creation_time"] != value["creation_time"]:
                        raise RuntimeError("Direct child identity changed; cleanup unconfirmed")
                    self.identities.setdefault(process.pid, value)
        parents = set()
        for pid, original in self.identities.items():
            if pid in rows:
                value = snapshot(pid)
                if value and value["creation_time"] == original["creation_time"] and not value["stat"].startswith("Z"):
                    parents.add(pid)
        self.uncertain_candidates.intersection_update(rows)
        changed = True
        while changed:
            changed = False
            for pid, ppid in rows.items():
                if pid not in self.identities and ppid in parents:
                    value = snapshot(pid)
                    parent = snapshot(ppid)
                    if (value and value["ppid"] == ppid and parent
                            and parent["creation_time"] == self.identities[ppid]["creation_time"]
                            and not parent["stat"].startswith("Z")):
                        self.identities[pid] = value
                        self.uncertain_candidates.discard(pid)
                        if not value["stat"].startswith("Z"):
                            parents.add(pid)
                        changed = True
                    else:
                        # The earlier PPID observation is no longer proof of
                        # ownership. Never signal this candidate; require its
                        # disappearance or a later positive adoption.
                        self.uncertain_candidates.add(pid)

    def remaining(self):
        rows = self.process_table()
        remaining = {process.pid for process in self.processes if process.poll() is None}
        remaining.update(self.uncertain_candidates.intersection(rows))
        for pid, original in self.identities.items():
            if pid in rows:
                value = snapshot(pid)
                # Absent argv/metadata is uncertainty. A positively different
                # creation identity proves the original exited, without giving
                # authority to signal its replacement.
                if value is None or value["creation_time"] == original["creation_time"]:
                    remaining.add(pid)
        return sorted(remaining)

    def start(self, command, cwd, env, log):
        with log.open("wb") as handle:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=handle, start_new_session=True)
        self.processes.append(process)
        self.collect()
        return process

    def wait(self, process, timeout=180):
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            self.collect()
            if time.monotonic() > deadline:
                raise TimeoutError("Owned fixture command timed out")
            time.sleep(0.2)
        self.collect()
        return process.returncode

    def cleanup(self):
        self.collect()
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid, original in reversed(list(self.identities.items())):
                current = snapshot(pid)
                if current and current["creation_time"] == original["creation_time"] and not current["stat"].startswith("Z"):
                    try:
                        os.kill(pid, sig)
                    except ProcessLookupError:
                        pass
            for process in self.processes:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
            time.sleep(0.2)
            self.collect()
            survivors = self.remaining()
            if not survivors:
                return "verified-empty"
        raise AssertionError(f"Fixture cleanup unconfirmed; live or uncertain PIDs: {survivors}")


def free_port(preferred: list[int]) -> int:
    for port in preferred:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free fixture port in {preferred}; existing listeners left untouched")


def wait_http(url: str, process, owned: OwnedProcesses):
    port = urllib.parse.urlsplit(url).port
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError(f"Fixture server exited before ready: {url}")
        owned.collect()
        listener = subprocess.run(["lsof", "-nP", "-a", "-p", str(process.pid), "-iTCP:" + str(port), "-sTCP:LISTEN", "-Fp"], capture_output=True, text=True)
        if listener.returncode or f"p{process.pid}" not in listener.stdout.splitlines():
            time.sleep(0.1)
            continue
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    raise TimeoutError(f"Fixture server never became ready: {url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="explicitly allow disposable fixture processes and Chrome")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--playwright", type=Path, default=DEFAULT_PLAYWRIGHT)
    parser.add_argument("--chrome", type=Path, default=CHROME)
    args = parser.parse_args()
    if not args.run:
        parser.error("No processes created; pass --run to opt in")
    assert args.playwright.is_dir() and args.chrome.is_file()
    api_port = free_port([18731, 18732, 18733])
    ui_port = free_port([3001, 3000])
    hostile_port = free_port([5186, 5187, 5188])
    root = Path(tempfile.mkdtemp(prefix="pbot-browser-acceptance-"))
    fixture_id = uuid.uuid4().hex
    (root / ".browser-fixture").write_text(fixture_id)
    print(f"Evidence: {root}", flush=True)
    project = root / "project"
    project.mkdir()
    for folder in ["data", "home", "tmp"]:
        (root / folder).mkdir()
    owned = OwnedProcesses()
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "ports": {"api": api_port, "ui": ui_port, "hostile": hostile_port},
              "fixture_id": fixture_id, "evidence_dir": str(root), "source_sha256": {},
              "launcher_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    node = shutil.which("node")
    npm = shutil.which("npm")
    assert node and npm
    env = {"PATH": str(Path(node).parent) + ":/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
           "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"), "PYTHONUNBUFFERED": "1",
           "PYTHONPATH": str(project / "src"), "NEXT_PUBLIC_PBOT_API_URL": f"http://127.0.0.1:{api_port}",
           "NPM_CONFIG_UPDATE_NOTIFIER": "false", "NPM_CONFIG_OFFLINE": "true",
           "WRANGLER_SEND_METRICS": "false", "WRANGLER_WRITE_LOGS": "false", "DO_NOT_TRACK": "1",
           "PBOT_PLAYWRIGHT_MODULE": str(args.playwright.resolve()), "PBOT_CHROME": str(args.chrome),
           "PBOT_BROWSER_EVIDENCE": str(root), "PBOT_FIXTURE_API_PORT": str(api_port),
           "PBOT_FIXTURE_UI_PORT": str(ui_port), "PBOT_FIXTURE_HOSTILE_PORT": str(hostile_port),
           "PBOT_FIXTURE_ID": fixture_id, "PBOT_BROWSER_CASES": ",".join(args.case)}

    def interrupt(_signal, _frame):
        raise KeyboardInterrupt("Browser fixture interrupted; cleaning owned processes")
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    try:
        files = source_paths(REPO)
        files.update(FIXTURES)
        files.add("scripts/check_browser_acceptance.py")
        for name in sorted(files - {""}):
            relative = Path(name)
            if any(part.startswith(".env") or part in {"var", "JOURNAL.md", "production.env"} for part in relative.parts):
                continue
            source = REPO / relative
            assert source.resolve().is_relative_to(REPO), name
            assert all(not (REPO / Path(*relative.parts[:index])).is_symlink() for index in range(1, len(relative.parts) + 1)), name
            assert source.is_file() and not source.is_symlink(), name
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            report["source_sha256"][name] = hashlib.sha256(source.read_bytes()).hexdigest()
        # APFS clones isolate dependency cache/build writes without reinstalling.
        clone = owned.start(["/bin/cp", "-cR", str(REPO / "node_modules"), str(project / "node_modules")], root, env, root / "clone.log")
        assert owned.wait(clone) == 0, "Dependency clone failed"
        build = owned.start([npm, "run", "build"], project, env, root / "build.log")
        assert owned.wait(build) == 0, "Fixture build failed; see build.log"
        api = owned.start([sys.executable, str(project / FIXTURES[0]), "--root", str(root), "--port", str(api_port), "--fixture-id", fixture_id], project, env, root / "api.log")
        wait_http(f"http://127.0.0.1:{api_port}/api/health", api, owned)
        ui = owned.start([node, str(project / FIXTURES[1]), str(project), str(ui_port), str(hostile_port)], project, env, root / "ui.log")
        wait_http(f"http://127.0.0.1:{ui_port}/", ui, owned)
        wait_http(f"http://127.0.0.1:{hostile_port}/", ui, owned)
        tests = owned.start([node, str(project / FIXTURES[2])], project, env, root / "browser.log")
        report["test_exit_code"] = owned.wait(tests, timeout=240)
        report["passed"] = report["test_exit_code"] == 0
    except BaseException:
        report["passed"] = False
        report["error"] = traceback.format_exc()
    finally:
        try:
            report["cleanup"] = owned.cleanup()
        except BaseException:
            report["cleanup"] = traceback.format_exc()
            report["passed"] = False
        report["identities"] = list(owned.identities.values())
        report["uncertain_candidates"] = sorted(owned.uncertain_candidates)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (root / "report.json").write_text(json.dumps(report, indent=2))
    print(f"Browser acceptance: {'passed' if report['passed'] else 'failed'}; cleanup: {report['cleanup']}", flush=True)
    if report.get("error"):
        print(report["error"], flush=True)
    if (root / "browser.log").exists():
        print((root / "browser.log").read_text(), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
