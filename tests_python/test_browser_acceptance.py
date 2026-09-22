"""Fault-injected fixture ownership checks; no processes, ports or signals."""
import importlib
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
browser = importlib.import_module("check_browser_acceptance")


def identity(pid, ppid=1, creation="fixture-start"):
    return {"pid": pid, "ppid": ppid, "pgid": pid, "stat": "S", "creation_time": creation, "command": "inert fixture"}


@pytest.fixture
def isolation(monkeypatch):
    kill = Mock()
    monkeypatch.setattr(browser.os, "kill", kill)
    monkeypatch.setattr(browser.time, "sleep", lambda *_: None)
    return kill


def test_missing_identity_is_not_cleanup_proof(monkeypatch, isolation):
    owned = browser.OwnedProcesses()
    owned.identities[987654] = identity(987654)
    monkeypatch.setattr(browser.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout="1 0\n987654 1\n"))
    monkeypatch.setattr(browser, "snapshot", lambda _pid: None)
    with pytest.raises(AssertionError, match="unconfirmed|uncertain|survived"):
        owned.cleanup()
    isolation.assert_not_called()


def test_new_child_requires_fresh_parent_relation(monkeypatch, isolation):
    owned = browser.OwnedProcesses()
    owned.identities[900001] = identity(900001)
    monkeypatch.setattr(browser.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout="1 0\n900001 1\n900002 900001\n"))
    monkeypatch.setattr(browser, "snapshot", lambda pid: identity(pid, ppid=1, creation="other-start" if pid == 900002 else "fixture-start"))
    owned.collect()
    assert 900002 not in owned.identities
    isolation.assert_not_called()


def test_live_uncaptured_direct_child_prevents_empty_receipt(monkeypatch, isolation):
    owned = browser.OwnedProcesses()
    child = Mock(pid=987654)
    child.poll.return_value = None
    child.wait.side_effect = subprocess.TimeoutExpired("inert", 3)
    owned.processes.append(child)
    monkeypatch.setattr(browser.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout="1 0\n"))
    monkeypatch.setattr(browser, "snapshot", lambda _pid: None)
    with pytest.raises(AssertionError, match="unconfirmed|uncertain|survived"):
        owned.cleanup()
    isolation.assert_not_called()


def test_empty_process_listing_cannot_prove_cleanup(monkeypatch, isolation):
    owned = browser.OwnedProcesses()
    owned.identities[987654] = identity(987654)
    monkeypatch.setattr(browser.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout=""))
    monkeypatch.setattr(browser, "snapshot", lambda _pid: None)
    with pytest.raises((RuntimeError, AssertionError)):
        owned.cleanup()
    isolation.assert_not_called()


def test_confirmed_child_can_be_owned_and_cleaned(monkeypatch, isolation):
    owned = browser.OwnedProcesses()
    members = {900001: identity(900001), 900002: identity(900002, ppid=900001)}
    owned.identities[900001] = members[900001]
    monkeypatch.setattr(browser.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout="1 0\n" + "".join(f"{pid} {item['ppid']}\n" for pid, item in members.items())))
    monkeypatch.setattr(browser, "snapshot", lambda pid: members.get(pid))
    isolation.side_effect = lambda pid, _sig: members.pop(pid)
    owned.collect()
    assert set(owned.identities) == {900001, 900002}
    assert owned.cleanup() == "verified-empty"
    assert {call.args[0] for call in isolation.call_args_list} == {900001, 900002}


def test_parent_identity_is_rechecked_before_adoption(monkeypatch, isolation):
    owned = browser.OwnedProcesses()
    owned.identities[900001] = identity(900001)
    monkeypatch.setattr(browser.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout="1 0\n900001 1\n900002 900001\n"))
    reads = 0
    def observe(pid):
        nonlocal reads
        if pid == 900001:
            reads += 1
            return identity(pid, creation="fixture-start" if reads == 1 else "replacement")
        return identity(pid, ppid=900001)
    monkeypatch.setattr(browser, "snapshot", observe)
    owned.collect()
    assert 900002 not in owned.identities
    isolation.assert_not_called()


def test_known_child_can_reparent_without_losing_ownership(monkeypatch, isolation):
    owned = browser.OwnedProcesses()
    owned.identities[900002] = identity(900002, ppid=900001)
    members = {900002: identity(900002, ppid=1)}
    monkeypatch.setattr(browser.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout="1 0\n" + "".join(f"{pid} 1\n" for pid in members)))
    monkeypatch.setattr(browser, "snapshot", lambda pid: members.get(pid))
    isolation.side_effect = lambda pid, _sig: members.pop(pid)
    assert owned.cleanup() == "verified-empty"
    isolation.assert_called_once()


def test_positive_pid_reuse_never_signals_replacement(monkeypatch, isolation):
    owned = browser.OwnedProcesses()
    owned.identities[900002] = identity(900002)
    monkeypatch.setattr(browser.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout="1 0\n900002 1\n"))
    monkeypatch.setattr(browser, "snapshot", lambda pid: identity(pid, creation="replacement"))
    assert owned.cleanup() == "verified-empty"
    isolation.assert_not_called()


def test_source_archive_selects_code_without_runtime_or_environment(tmp_path):
    for name in ["app/page.tsx", "src/pbot/api.py", "package.json", "production.env", ".env", "var/profile.json", "logs/private.json", "src/pbot/__pycache__/api.pyc"]:
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("synthetic")
    assert browser.source_paths(tmp_path) == {"app/page.tsx", "src/pbot/api.py", "package.json"}


def test_source_archive_rejects_symlinked_code_directory(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.py").write_text("synthetic")
    (tmp_path / "src").symlink_to(outside, target_is_directory=True)
    with pytest.raises(AssertionError, match="symlink"):
        browser.source_paths(tmp_path)
