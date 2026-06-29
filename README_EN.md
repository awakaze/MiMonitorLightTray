# Mi Monitor Light Tray

> 中文版：**[README.md](README.md)**

A Windows system-tray utility that controls Xiaomi / Yeelight monitor light bars with the same flyout-slider experience as [Twinkle Tray](https://twinkletray.com/). Built on [python-miio](https://github.com/rytilahti/python-miio), talks to the light over the **local LAN** (no cloud calls).

![Python](https://img.shields.io/badge/Python-3.9%2B-blue) ![Platform](https://img.shields.io/badge/platform-Windows-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

## Supported devices

The app **picks the protocol per device `model`** automatically. Beyond a small hand-curated set, **~2100 MIoT light specs (protocol mappings + CT ranges) have been scraped from [home.miot-spec.com](https://home.miot-spec.com) and embedded** ([mi_monitor_light_tray/_miot_data.py](mi_monitor_light_tray/_miot_data.py)), covering yeelink, xiaomi, mijia and many third-party brands.

**Routing decision** (derived from set membership in this order):

1. **Curated `_MIOT_MAPPINGS`** ([miio_client.py](mi_monitor_light_tray/miio_client.py) top, contains lamp22) → MIoT
2. **python-miio `YeelightSpecHelper`** (specs.yaml — 41 known legacy Yeelight devices) → legacy
3. **Project `MODEL_CT_RANGES`** (hand-verified legacy devices like lamp2) → legacy
4. **Bulk `_miot_data`** (~2100 MIoT-only devices that none of the above knew) → MIoT
5. **Truly unknown** → legacy (fallback; user can flip with **Enable MIoT (experimental)**)

**CT range resolution** uses the same precedence: curated overrides > YeelightSpecHelper > bulk → default 2700–6500K. Bulk data passes a plausibility filter (min ≥ 1000K, max ∈ [2000, 15000]K, span ≥ 500K) that rejects specs where the color-temperature property is mis-declared in percentage instead of Kelvin — about 7% of the upstream corpus is broken that way.

The table below highlights key models; every other device in the embedded database picks up correct protocol + CT range automatically:

| Model ID | Device | Protocol | CT range | Source |
|---|---|---|---|---|
| `yeelink.light.lamp22` | Mi Smart Monitor Light Bar 1S (default model) | MIoT   | 2700–6500 K | curated |
| `yeelink.light.lamp1`  | Mi LED Smart Desk Lamp (米家台灯)             | legacy | 2700–5000 K | YeelightSpecHelper |
| `yeelink.light.lamp2`  | Mi Smart LED Desk Lamp Pro (米家台灯 Pro)     | legacy | 2500–4800 K | project override |
| `yeelink.light.lamp4`  | Mi LED Desk Lamp 1S (米家台灯 1S)             | legacy | 2600–5000 K | YeelightSpecHelper |
| `yeelink.light.ceiling*` | Mi Smart Ceiling Light series                | legacy | 2700–6500 K | YeelightSpecHelper |
| `yeelink.light.bslamp*`  | Mi Bedside Lamp series                       | legacy | 1700–6500 K | YeelightSpecHelper |
| ~2100 other MIoT-only lights | Various branded smart lights              | MIoT   | per spec    | _miot_data.py (bulk) |

If your model is in none of the sources → the app falls back to legacy. For MIoT-only models that aren't covered yet, tick **Enable MIoT (experimental)** in the settings dialog to probe with the generic Light-service spec.

> **When filing a compatibility issue, include the `model` field** (e.g. `yeelink.light.lamp22`) — it pins down the protocol and CT range. You can read it from `device.model` in `%APPDATA%\MiMonitorLightTray\config.json`, or run `miiocli device --ip <IP> --token <token> info`.

## Features

- **Twinkle Tray-style flyout** — appears near the cursor, dismisses on outside click or `Esc`
- **Desktop widget** — pinnable on-desktop control panel, dark theme + rounded window, drag / lock, remembers position and visibility
- **Cloud token auto-extract** — built-in "Auto-fetch" button in the setup wizard; scan a QR code with your Xiaomi account and pull device IP + Token in one go
- **Brightness & color-temperature sliders** — brightness 1–100, color temperature 2700K–6500K
- **Debounced slider updates** — drags are coalesced into one miio call every ~120/180 ms instead of one per pixel
- **Single-instance lock** — a Windows named mutex prevents duplicate launches and shows a friendly dialog instead
- **Auto-rediscovery on IP change** — when DHCP rotates the light's IP, the app locates it again by device ID and updates the config silently
- **Empty-model auto-detect** — when no model is configured, the app probes via `info()` at startup and picks the correct protocol, avoiding protocol mismatch
- **Fluent Design look** — native DWM rounded corners, semi-transparent dark surface, Win11 accent color
- **Minimal vector tray icon** — drawn with Pillow, sharp on any DPI, distinct on/off states
- **First-run wizard** — IP/Token capture with a built-in **Test connection** button
- **Persistent config** — atomic write to `%APPDATA%\MiMonitorLightTray\config.json`
- **No install required** — single-file EXE, no Python on the target machine
- **Light follows the app** — two independent toggles: power on at app startup, power off at app exit
- **Auto-power-on while dragging sliders** — if the light is off when you move the brightness/CT slider, the app powers it on first so the change is visible
- **Experimental MIoT toggle** — for newer Yeelight devices not yet in the MIoT whitelist, try MIoT manually from the settings dialog

## Install

### Option 1: pre-built binary (recommended)

Grab `MiMonitorLightTray.exe` from [Releases](https://github.com/Martlnez/MiMonitorLightTray/releases). Every push to `main` and every tag triggers a CI build (see [build.yml](.github/workflows/build.yml)).

### Option 2: run from source

```bash
git clone https://github.com/Martlnez/MiMonitorLightTray.git
cd MiMonitorLightTray

python -m venv .venv
.venv\Scripts\activate
pip install -e .

mi-monitor-light-tray
```

Requires Python 3.9+.

## First-run setup

The setup wizard opens automatically on first launch. **Recommended flow** (three steps):

1. Click **Auto-fetch (自动获取)**
2. Scan the QR code with your Xiaomi account / Mi Home app
3. Pick your light from the device grid (2×N layout)

IP / Token / model are filled in for you. Hit **Test connection** to verify, then **Save**. The token is written **locally only** to `%APPDATA%\MiMonitorLightTray\config.json` — it never leaves your machine.

### Manual entry (fallback)

If you'd rather not sign in, or auto-fetch fails, fill the form by hand:

- **Device IP**: Mi Home → device page → ⋮ → More settings → Network info; or look in your router's DHCP list for a host named `yeelight` / `monitor`
- **miio Token**: 32-char hex string; extract it with [Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor) or `miiocli cloud`
- **Display name**: anything — shown in the tray tooltip
- **Model**: leave blank; the app auto-detects it after connecting

### (Optional) verify connectivity by hand

```python
from miio import Device

dev = Device(ip="192.168.1.xxx", token="your-32-char-token")
info = dev.info()
print(f"Connected: model={info.model} firmware={info.firmware_version}")
```

`Device.info()` is a protocol-layer command and works for both legacy Yeelight and MIoT devices. Property reads/writes after that need either the `Yeelight` or `MiotDevice` subclass — the app picks one automatically per model, you don't need to choose manually.

## Usage

- **Left-click** the tray icon → flyout opens near the cursor
- Drag the **Brightness** slider (1–100) and the **Color temperature** slider (2700K warm — 6500K cool)
- Click **⏻** in the footer to toggle power, **⚙** to open settings
- Click outside the flyout, or press `Esc`, to dismiss it
- **Right-click** the tray icon:
  - **调整亮度** (Adjust) — open the flyout
  - **桌面小部件** (Desktop widget) — toggle the desktop widget
  - **设置** (Settings) — reconfigure the device
  - **退出** (Exit) — quit the app

> The right-click menu is intentionally localized to Chinese to match the rest of the device's ecosystem (Mi Home is Chinese-first); the English README mirrors the labels for reference.

### Desktop widget

Open it from the tray right-click menu (**桌面小部件**). The widget is a persistent control panel pinned on the desktop, sharing the flyout's dark theme:

- **Drag** the title area to move it
- **Right-click** the widget to lock/unlock the position (locked = drag disabled, prevents accidental moves)
- Position, locked state, and visibility persist in the `widget` block of `config.json`
- Hidden from the taskbar to keep the desktop tidy

### Run at startup

Open **设置** (Settings) and tick "开机自启动" (Run at startup), or use the same item in the tray right-click menu. This writes a `MiMonitorLightTray` entry to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` — current-user only, no admin required.

### Light follows the app

Two independent toggles in the settings dialog and in the tray right-click menu:

- **灯跟随软件启动** — power the light **on** when the app starts
- **灯跟随软件关闭** — power the light **off** when the app exits (tray "退出", `Ctrl+C`, taskbar close, etc.)

Either can be enabled alone; combined with system autostart they give you "power on the PC → light on, shut down → light off". The exit-off path registers an `atexit` handler so it also covers exit routes that bypass the tray menu.

### Auto-power-on while dragging sliders

When the light is currently off and you move the brightness or CT slider, the app sends a power-on command first, then the target value. This is on by default and not configurable — it avoids the "dragging seems to do nothing" confusion (legacy Yeelight's auto-on behavior is firmware-dependent, and MIoT lights never auto-on).

### Enable MIoT (experimental)

`_MIOT_MAPPINGS` is the whitelist of known MIoT devices. If your device is a newer Yeelight model that isn't in the whitelist but you suspect it actually speaks MIoT, tick **"启用 MIoT（实验性）"** in the settings dialog. The app then attempts to talk to it using lamp22's generic Light-service spec (`(siid=2, piid=1/2/3) = power/brightness/color-temperature`). This is a calculated gamble — most Mi/Yeelight monitor lights and desk lamps follow that layout, but compatibility isn't guaranteed. If the device doesn't respond, errors will pile up; untick the box to fall back to legacy.

### Command-line flags

```bash
MiMonitorLightTray.exe --setup    # force-open the setup wizard
MiMonitorLightTray.exe --debug    # enable DEBUG logging
```

## Build a single-file EXE locally

```bash
pip install -e ".[build]"
python scripts/build_exe.py
```

Outputs to `dist\MiMonitorLightTray.exe`. The script invokes PyInstaller with `--onefile --noconsole`, and uses `--collect-data miio` to bundle python-miio's YAML/JSON spec files (without that, the device-info parser crashes at runtime).

## Run tests

```bash
pip install -e ".[dev]"
pytest -q
```

Coverage: config serialization ([tests/test_config.py](tests/test_config.py)), tray icon rendering ([tests/test_icon.py](tests/test_icon.py)), miio wrapper and debouncer ([tests/test_miio_client.py](tests/test_miio_client.py)). UI and live-network paths are exercised manually.

## Project layout

```
mi_monitor_light_tray/
  __main__.py          entrypoint: single-instance lock → config → tray + flyout
  config.py            AppConfig / DeviceConfig / WidgetConfig persistence (atomic write)
  miio_client.py       legacy Yeelight + MIoT protocol dispatch, thread-safe wrapper + slider Debouncer
  flyout.py            borderless Tk window with Canvas dark sliders
  desktop_widget.py    pinned-on-desktop widget (drag, lock, position memory)
  cloud_login_window.py cloud login window (QR sign-in + device picker)
  token_extractor/     Xiaomi cloud API client: auth + device list fetcher
  icon.py              Pillow-generated tray icon (no binary assets)
  setup_wizard.py      IP/Token capture window with Auto-fetch button and connection test
  tray.py              pystray system-tray controller
  shutdown_listener.py Windows WM_QUERYENDSESSION listener — power-off at OS shutdown
  single_instance.py   Windows named-mutex single-instance lock
  discovery.py         UDP-broadcast device discovery, re-locate by device_id
scripts/
  build_exe.py         PyInstaller helper
  run_app.py           PyInstaller entry (avoids relative-import issues)
tests/                 pytest unit suite
```

## Config file

Location: `%APPDATA%\MiMonitorLightTray\config.json`

```json
{
  "device": {
    "ip": "192.168.1.100",
    "token": "...32 hex chars...",
    "name": "Mi Monitor Light",
    "model": "",
    "device_id": 12345678,
    "enable_miot_for_unknown": false,
    "power_on_at_startup": false,
    "power_off_at_exit": false
  },
  "widget": {
    "visible": false,
    "x": 100,
    "y": 100,
    "locked": true
  }
}
```

`device_id` is captured automatically on the first successful connect and is what enables auto-rediscovery when the IP changes. Leaving `model` blank is fine — the app probes via `info()` at startup, picks the right protocol, and writes the resolved model back. `enable_miot_for_unknown` lets Yeelight devices outside the `_MIOT_MAPPINGS` whitelist try MIoT using lamp22's generic Light-service spec — for newer models that follow the same layout. `power_on_at_startup` / `power_off_at_exit` are two independent toggles that control whether the light follows the app's lifecycle. The `widget` block stores the desktop widget's position, lock state, and visibility. Brightness and color temperature are remembered by the lamp itself; the system-level launch-at-startup flag lives in the Windows registry, not here.

## Troubleshooting

**"Another instance is already running"**
The app is already up — check the tray overflow area (the up-arrow on the right of the taskbar).

**Status shows "Offline — Unable to discover the device"**
1. Confirm the light is powered on and on the same LAN as your PC
2. Re-check the IP via Mi Home or the router
3. miio uses UDP/54321 — corporate firewalls sometimes block it; try disabling the firewall briefly to confirm
4. If `device_id` was captured before, the app keeps retrying discovery in the background

**"miio error: Invalid token"**
Tokens rotate when the device is re-paired in Mi Home — re-extract with cloud-tokens-extractor.

**Tray icon doesn't appear**
Windows Explorer may have hidden it in the overflow area; click the up-arrow on the taskbar.

**Sliders feel ~0.1 s laggy while dragging**
That's intentional debouncing (120 ms brightness / 180 ms color temperature) to avoid flooding the device. The final value commits as soon as you let go.

## Acknowledgements

- [@zengzoxiong](https://github.com/zengzoxiong) — cloud Token extractor and desktop widget ([PR #1](https://github.com/Martlnez/MiMonitorLightTray/pull/1))
- [python-miio](https://github.com/rytilahti/python-miio) — the protocol library
- [pystray](https://github.com/moses-palmer/pystray) — Python system-tray glue
- [Pillow](https://python-pillow.org/) — icon rendering
- [Twinkle Tray](https://twinkletray.com/) — UX inspiration

## License

[MIT License](LICENSE)
