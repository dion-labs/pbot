from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


class DeviceError(RuntimeError):
    """Raised when the Android control bridge cannot complete an operation."""


@dataclass(frozen=True)
class AndroidDevice:
    serial: str
    state: str
    model: str | None = None
    transport_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class DeviceDoctor:
    adb_found: bool
    adb_path: str | None
    devices: tuple[AndroidDevice, ...]
    selected_serial: str | None
    ready: bool
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "adb_found": self.adb_found,
            "adb_path": self.adb_path,
            "devices": [device.to_dict() for device in self.devices],
            "selected_serial": self.selected_serial,
            "ready": self.ready,
            "message": self.message,
        }


class AdbDeviceAdapter:
    def __init__(self, adb_path: str = "adb", serial: str | None = None, timeout: float = 15) -> None:
        self.adb_path = adb_path
        self.configured_serial = serial
        self.serial = serial
        self.timeout = timeout

    def _resolved_adb(self) -> str | None:
        path = Path(self.adb_path).expanduser()
        if path.parent != Path("."):
            return str(path) if path.exists() else None
        return shutil.which(self.adb_path)

    def _run(self, *args: str, binary: bool = False) -> subprocess.CompletedProcess:
        adb = self._resolved_adb()
        if not adb:
            raise DeviceError("ADB is not installed or PBOT_ADB does not point to it.")
        command = [adb]
        if self.serial:
            command.extend(["-s", self.serial])
        command.extend(args)
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=not binary,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise DeviceError(f"ADB timed out after {self.timeout:g} seconds.") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode(errors="replace") if binary and exc.stderr else exc.stderr
            raise DeviceError((detail or "ADB command failed.").strip()) from exc

    @staticmethod
    def parse_devices(output: str) -> tuple[AndroidDevice, ...]:
        devices: list[AndroidDevice] = []
        for line in output.splitlines()[1:]:
            line = line.strip()
            if not line or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            metadata = dict(token.split(":", 1) for token in parts[2:] if ":" in token)
            devices.append(AndroidDevice(
                serial=parts[0],
                state=parts[1],
                model=metadata.get("model"),
                transport_id=metadata.get("transport_id"),
            ))
        return tuple(devices)

    def list_devices(self) -> tuple[AndroidDevice, ...]:
        result = self._run("devices", "-l")
        return self.parse_devices(result.stdout)

    def doctor(self) -> DeviceDoctor:
        adb = self._resolved_adb()
        if not adb:
            return DeviceDoctor(False, None, (), None, False, "ADB is not installed.")
        try:
            devices = self.list_devices()
        except (subprocess.SubprocessError, DeviceError) as exc:
            return DeviceDoctor(True, adb, (), self.serial, False, f"ADB failed: {exc}")
        ready_devices = tuple(device for device in devices if device.state == "device")
        if self.configured_serial:
            selected = next((device for device in devices if device.serial == self.configured_serial), None)
            if selected is None:
                return DeviceDoctor(True, adb, devices, self.configured_serial, False, "Configured device is not connected.")
            if selected.state != "device":
                return DeviceDoctor(True, adb, devices, self.configured_serial, False, f"Configured device is {selected.state}.")
            return DeviceDoctor(True, adb, devices, self.configured_serial, True, "Android device is ready.")
        if len(ready_devices) == 1:
            return DeviceDoctor(True, adb, devices, ready_devices[0].serial, True, "Android device is ready.")
        if not ready_devices:
            return DeviceDoctor(True, adb, devices, None, False, "No authorized Android device is connected.")
        return DeviceDoctor(True, adb, devices, None, False, "Multiple devices found; set PBOT_ADB_SERIAL.")

    def screenshot(self) -> bytes:
        self.keep_awake()
        result = self._run("exec-out", "screencap", "-p", binary=True)
        return result.stdout

    def keep_awake(self) -> None:
        self._run("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        self._run("shell", "wm", "dismiss-keyguard")

    def tap(self, x: int, y: int) -> None:
        self.keep_awake()
        self._run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.keep_awake()
        self._run("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    def press_back(self) -> None:
        self.keep_awake()
        self._run("shell", "input", "keyevent", "KEYCODE_BACK")
