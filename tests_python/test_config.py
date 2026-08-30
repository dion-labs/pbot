from __future__ import annotations

import pytest

from pbot.config import Settings


@pytest.mark.parametrize("host", ["127.0.0.1", "127.1.2.3", "::1", "localhost"])
def test_settings_accept_loopback_api_hosts(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("PBOT_API_HOST", host)

    assert Settings.load().api_host == host


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "pbot.example.com", ""])
def test_settings_reject_non_loopback_api_hosts(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("PBOT_API_HOST", host)

    with pytest.raises(ValueError, match="must be a loopback address"):
        Settings.load()
