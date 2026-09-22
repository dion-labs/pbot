"""Synthetic profile/device guards; no adapter construction or ADB execution."""
from pathlib import Path
import importlib
import sys

import pytest

from pbot.config import Settings
from pbot.storage import Store

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.mark.parametrize("module_name", ["run_autonomous", "scan_cards"])
@pytest.mark.parametrize("scanned_serial", ["fixture-a", None])
def test_cli_rejects_other_device_before_constructing_adapter(tmp_path, monkeypatch, module_name, scanned_serial):
    settings = Settings(tmp_path, tmp_path / "data", tmp_path / "data" / "fixture.sqlite3",
                        tmp_path / "unused.png", "/nonexistent/fixture-adb", None, "127.0.0.1", 8765)
    store = Store(settings.database_path)
    store.initialize()
    with store.connect() as connection:
        connection.execute("UPDATE account_profile SET status='ready', device_serial=?", (scanned_serial,))
        connection.execute("UPDATE card_inventory_profile SET status='ready', device_serial='fixture-a'")
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module.Settings, "load", lambda: settings)
    monkeypatch.setattr(sys, "argv", [module_name, "--serial", "fixture-b"])
    def forbidden(*args, **kwargs):
        raise AssertionError("Mismatched synthetic device must not construct an adapter")
    monkeypatch.setattr(module, "AndroidVision" if module_name == "run_autonomous" else "AndroidCardInventoryPort", forbidden)
    if module_name == "run_autonomous":
        with pytest.raises(SystemExit) as result:
            module.main()
        assert result.value.code == 2
    else:
        assert module.main() == 2
    assert store.get_state()["status"] == "needs_attention"
    assert store.get_account_profile()["device_serial"] == scanned_serial
    assert store.get_card_inventory_profile()["device_serial"] == "fixture-a"



@pytest.mark.parametrize("module_name", ["run_autonomous", "scan_cards"])
def test_cli_without_override_pins_the_scanned_device(tmp_path, monkeypatch, module_name):
    settings = Settings(tmp_path, tmp_path / "data", tmp_path / "data" / "fixture.sqlite3",
                        tmp_path / "unused.png", "/nonexistent/fixture-adb", None, "127.0.0.1", 8765)
    store = Store(settings.database_path)
    store.initialize()
    with store.connect() as connection:
        connection.execute("UPDATE account_profile SET status='ready', device_serial='fixture-a'")
        connection.execute("UPDATE card_inventory_profile SET status='ready', device_serial='fixture-a'")
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module.Settings, "load", lambda: settings)
    monkeypatch.setattr(sys, "argv", [module_name])
    class PreflightAccepted(Exception):
        pass
    def capture_selection(root, serial):
        assert root == tmp_path
        assert serial == "fixture-a"
        raise PreflightAccepted
    monkeypatch.setattr(module, "AndroidVision" if module_name == "run_autonomous" else "AndroidCardInventoryPort", capture_selection)
    with pytest.raises(PreflightAccepted):
        module.main()
