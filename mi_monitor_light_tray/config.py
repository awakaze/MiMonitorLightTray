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

    def is_complete(self) -> bool:
        return bool(self.ip) and bool(self.token) and len(self.token) == 32


@dataclass
class WebConfig:
    # Expose a small HTTP server on the LAN so phones/tablets/scripts can drive
    # the same lamp without needing the tray UI. On by default — once the user
    # finishes the device wizard, the web UI is reachable at
    # http://<this-pc>:8765/ on the LAN with no extra setup.
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8765
    # Optional bearer token. Empty string = no auth (LAN-only convenience).
    token: str = ""


@dataclass
class AppConfig:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    web: WebConfig = field(default_factory=WebConfig)

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
        dev_data = data.get("device", {})
        # Tolerate legacy keys silently — DeviceConfig(**unknown) would raise.
        known = {f for f in DeviceConfig.__dataclass_fields__}
        dev = DeviceConfig(**{k: v for k, v in dev_data.items() if k in known})

        web_data = data.get("web", {})
        web_known = {f for f in WebConfig.__dataclass_fields__}
        web = WebConfig(**{k: v for k, v in web_data.items() if k in web_known})
        return cls(device=dev, web=web)

    def save(self, path: Optional[Path] = None) -> None:
        path = path or default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"device": asdict(self.device), "web": asdict(self.web)}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def default_config_path() -> Path:
    return _default_config_dir() / "config.json"
