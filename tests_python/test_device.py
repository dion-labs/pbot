from pbot.device import AdbDeviceAdapter


def test_parse_adb_devices() -> None:
    output = """List of devices attached
emulator-5554 device product:sdk_gphone64_arm64 model:sdk_gphone64_arm64 transport_id:1
R5CT20 unauthorized usb:1-1 transport_id:2

"""
    devices = AdbDeviceAdapter.parse_devices(output)
    assert len(devices) == 2
    assert devices[0].serial == "emulator-5554"
    assert devices[0].model == "sdk_gphone64_arm64"
    assert devices[0].state == "device"
    assert devices[1].state == "unauthorized"


def test_parse_ignores_daemon_noise() -> None:
    output = """List of devices attached
* daemon started successfully

"""
    assert AdbDeviceAdapter.parse_devices(output) == ()
