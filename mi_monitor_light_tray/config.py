"""Persistent user configuration stored under %APPDATA%/MiMonitorLightTray/config.json.

Only data the program actually consumes lives here. Brightness/color-temp are
remembered by the lamp itself; launch-at-startup is owned by the Windows
registry (see ``autostart.py``).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _default_config_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "MiMonitorLightTray"
    return Path.home() / ".mi-monitor-light-tray"


@dataclass
class DeviceConfig:
    id: str = ""  # Stable identifier: synthetic for new devices, hex(device_id) after connection
    ip: str = ""
    token: str = ""
    name: str = "Mi Monitor Light"
    model: str = ""
    device_id: int = 0  # Stored after first successful connection for auto-discovery
    # Treat unknown models as MIoT and probe with the lamp22 generic Light-service
    # mapping. Default off — only opt-in for users with newer Yeelight devices
    # that aren't in _MIOT_MAPPINGS yet but share the standard Light spec.
    enable_miot_for_unknown: bool = False
    # Power the light on when the tray app starts.
    power_on_at_startup: bool = False
    # Power the light off when the tray app exits.
    power_off_at_exit: bool = False
    # Power the light off when monitor goes to sleep, and restore when monitor wakes up.
    power_off_on_monitor_sleep: bool = False
    # Power the light off when system suspends (sleep/hibernate).
    power_off_on_system_suspend: bool = False
    # Power the light on when system resumes from sleep/hibernate.
    power_on_on_system_resume: bool = False
    # Per-device hotkey settings
    brightness_up: str = ""  # 亮度增加快捷键，如 "ctrl+alt+up"
    brightness_down: str = ""  # 亮度降低快捷键，如 "ctrl+alt+down"
    color_temp_up: str = ""  # 色温增加快捷键，如 "ctrl+alt+right"
    color_temp_down: str = ""  # 色温降低快捷键，如 "ctrl+alt+left"
    hotkey_step: int = 5  # 每次调整的步进值（亮度：1-100，色温按比例）

    def is_complete(self) -> bool:
        return bool(self.ip) and bool(self.token) and len(self.token) == 32


@dataclass
class HotkeyConfig:
    """全局快捷键配置。"""
    brightness_up: str = ""  # 亮度增加快捷键，如 "ctrl+alt+up"
    brightness_down: str = ""  # 亮度降低快捷键，如 "ctrl+alt+down"
    color_temp_up: str = ""  # 色温增加快捷键，如 "ctrl+alt+right"
    color_temp_down: str = ""  # 色温降低快捷键，如 "ctrl+alt+left"
    step: int = 5  # 每次调整的步进值（亮度：1-100，色温按比例）


@dataclass
class WidgetConfig:
    """桌面小部件配置。"""
    visible: bool = False  # 是否显示
    x: int = 0  # X 坐标
    y: int = 0  # Y 坐标
    locked: bool = True  # 是否锁定位置

    def is_valid_position(self) -> bool:
        """检查位置是否有效。"""
        return self.x > 0 and self.y > 0


@dataclass
class AppConfig:
    devices: list[DeviceConfig] = field(default_factory=list)
    active_device_id: str = "ALL"  # "ALL" or specific device id for UI selection
    widget: WidgetConfig = field(default_factory=WidgetConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    auto_check_update: bool = True  # 启动时自动检查更新

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        path = path or default_config_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Failed to read config %s: %s", path, exc)
            return cls()

        # MIGRATION: Convert single "device" to "devices" list
        if "device" in data and "devices" not in data:
            single_dev = data.pop("device")
            if single_dev.get("ip") or single_dev.get("token"):
                # Generate id for migrated device if it doesn't have one
                if "id" not in single_dev or not single_dev["id"]:
                    import uuid
                    single_dev["id"] = f"temp_{uuid.uuid4().hex[:8]}"
                data["devices"] = [single_dev]
                log.info("Migrated single-device config to multi-device format")

        # Load devices list
        devices_data = data.get("devices", [])
        dev_known = {f for f in DeviceConfig.__dataclass_fields__}
        devices = []
        for d in devices_data:
            # Ensure each device has an id
            if "id" not in d or not d["id"]:
                import uuid
                d["id"] = f"temp_{uuid.uuid4().hex[:8]}"
            devices.append(DeviceConfig(**{k: v for k, v in d.items() if k in dev_known}))

        # 加载小部件配置
        widget_data = data.get("widget", {})
        widget_known = {f for f in WidgetConfig.__dataclass_fields__}
        widget = WidgetConfig(**{k: v for k, v in widget_data.items() if k in widget_known})
        # 加载快捷键配置
        hotkey_data = data.get("hotkey", {})
        hotkey_known = {f for f in HotkeyConfig.__dataclass_fields__}
        hotkey = HotkeyConfig(**{k: v for k, v in hotkey_data.items() if k in hotkey_known})
        # 加载自动更新检查配置
        auto_check_update = data.get("auto_check_update", True)
        # 加载活动设备 ID
        active_device_id = data.get("active_device_id", "ALL")

        return cls(
            devices=devices,
            active_device_id=active_device_id,
            widget=widget,
            hotkey=hotkey,
            auto_check_update=auto_check_update
        )

    def save(self, path: Optional[Path] = None) -> None:
        path = path or default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "devices": [asdict(d) for d in self.devices],
            "active_device_id": self.active_device_id,
            "widget": asdict(self.widget),
            "hotkey": asdict(self.hotkey),
            "auto_check_update": self.auto_check_update,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def default_config_path() -> Path:
    return _default_config_dir() / "config.json"
