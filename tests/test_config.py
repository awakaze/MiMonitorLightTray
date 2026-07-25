"""Unit tests for AppConfig serialisation and DeviceConfig validation."""

import json
from pathlib import Path

from mi_monitor_light_tray.config import AppConfig, DeviceConfig


def test_device_config_is_complete():
    assert not DeviceConfig().is_complete()
    assert not DeviceConfig(ip="192.168.1.10", token="short").is_complete()
    assert DeviceConfig(ip="192.168.1.10", token="x" * 32).is_complete()


def test_appconfig_roundtrip(tmp_path: Path):
    cfg = AppConfig(
        devices=[
            DeviceConfig(
                id="test_device_1",
                ip="10.0.0.5",
                token="a" * 32,
                name="Bar",
                model="yeelink.light.lamp22",
                device_id=875277841,
                enable_miot_for_unknown=True,
                power_on_at_startup=True,
                power_off_at_exit=True,
            ),
        ],
    )
    p = tmp_path / "cfg.json"
    cfg.save(p)
    loaded = AppConfig.load(p)
    assert len(loaded.devices) == 1
    dev = loaded.devices[0]
    assert dev.ip == "10.0.0.5"
    assert dev.token == "a" * 32
    assert dev.name == "Bar"
    assert dev.model == "yeelink.light.lamp22"
    assert dev.device_id == 875277841
    assert dev.enable_miot_for_unknown is True
    assert dev.power_on_at_startup is True
    assert dev.power_off_at_exit is True


def test_appconfig_new_flags_default_false(tmp_path: Path):
    """Loading an old config without the new flags must default them to False."""
    p = tmp_path / "old.json"
    p.write_text(
        json.dumps({
            "device": {"ip": "1.2.3.4", "token": "t" * 32, "name": "X"},
        }),
        encoding="utf-8",
    )
    cfg = AppConfig.load(p)
    # Old single-device config should migrate to devices list
    assert len(cfg.devices) == 1
    assert cfg.devices[0].enable_miot_for_unknown is False
    assert cfg.devices[0].power_on_at_startup is False
    assert cfg.devices[0].power_off_at_exit is False


def test_appconfig_missing_file_returns_default(tmp_path: Path):
    p = tmp_path / "missing.json"
    cfg = AppConfig.load(p)
    assert cfg.devices == []
    assert cfg.active_device_id == "ALL"


def test_appconfig_bad_json_returns_default(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    cfg = AppConfig.load(p)
    assert cfg.devices == []
    assert cfg.active_device_id == "ALL"


def test_appconfig_save_atomic(tmp_path: Path):
    p = tmp_path / "cfg.json"
    AppConfig(devices=[DeviceConfig(id="test_1", ip="1.2.3.4", token="t" * 32)]).save(p)
    parsed = json.loads(p.read_text(encoding="utf-8"))
    assert len(parsed["devices"]) == 1
    assert parsed["devices"][0]["ip"] == "1.2.3.4"
    # No leftover tmp file.
    assert not (tmp_path / "cfg.json.tmp").exists()


def test_appconfig_tolerates_legacy_keys(tmp_path: Path):
    """Old configs with last_brightness/last_color_temp/start_with_windows must still load."""
    p = tmp_path / "legacy.json"
    p.write_text(
        json.dumps({
            "device": {
                "ip": "1.2.3.4",
                "token": "t" * 32,
                "name": "X",
                "extra_legacy_field": "ignored",
            },
            "last_brightness": 80,
            "last_color_temp": 2700,
            "start_with_windows": True,
        }),
        encoding="utf-8",
    )
    cfg = AppConfig.load(p)
    # Old single-device config should migrate to devices list
    assert len(cfg.devices) == 1
    assert cfg.devices[0].ip == "1.2.3.4"
    assert cfg.devices[0].name == "X"
