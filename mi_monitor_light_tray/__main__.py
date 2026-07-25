"""Application entrypoint: wires config, tray icon, flyout, and setup wizard."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from tkinter import messagebox

from .config import AppConfig
from .single_instance import SingleInstance

log = logging.getLogger("mi_monitor_light_tray")


def _quiet_miio_warnings() -> None:
    """Suppress python-miio's noisy startup warnings.

    - ``spec_helper`` warns "Unknown model" for Mi monitor lights even though
      the standard Yeelight commands work for them.
    - ``miioprotocol`` logs every UDP discovery hiccup at WARNING; we already
      surface unreachable devices via state.error, so demote that channel.
    """
    logging.getLogger("miio.integrations.light.yeelight.spec_helper").setLevel(
        logging.ERROR
    )
    logging.getLogger("miio.miioprotocol").setLevel(logging.ERROR)


class App:
    def __init__(self, config: AppConfig) -> None:
        # Lazy-import heavy modules only when App is instantiated, not at script load.
        from .flyout import FlyoutWindow
        from .miio_client import MiMonitorLight
        from .tray import TrayController
        from .shutdown_listener import ShutdownListener
        from .monitor_sleep_listener import MonitorSleepListener
        from .hotkey_manager import HotkeyManager
        from .version_checker import VersionChecker

        self._config = config
        # Dict[device_id, MiMonitorLight] - keyed by DeviceConfig.id
        self._lights: dict[str, MiMonitorLight] = {}

        # Build all lights from config
        for dev_config in config.devices:
            if dev_config.is_complete():
                light = self._build_light(dev_config, MiMonitorLight)
                self._lights[dev_config.id] = light

        # Pass all lights and config to flyout for multi-device support
        self._flyout = FlyoutWindow(self._lights, config, on_open_setup=self._open_settings)

        # Initialize version checker
        self._version_checker = VersionChecker()
        self._update_available = False

        # Get first light for backward compatibility with TrayController
        first_light = next(iter(self._lights.values()), None)

        self._tray = TrayController(
            title="Mi Monitor Light",
            on_left_click=self._on_tray_click,
            on_open_settings=self._open_settings,
            on_exit=self._on_exit,
            get_power_on_at_startup=lambda: any(d.power_on_at_startup for d in self._config.devices),
            on_toggle_power_on_at_startup=self._toggle_power_on_at_startup,
            get_power_off_at_exit=lambda: any(d.power_off_at_exit for d in self._config.devices),
            on_toggle_power_off_at_exit=self._toggle_power_off_at_exit,
            get_power_off_on_monitor_sleep=lambda: any(d.power_off_on_monitor_sleep for d in self._config.devices),
            on_toggle_power_off_on_monitor_sleep=self._toggle_power_off_on_monitor_sleep,
            get_power_off_on_system_suspend=lambda: any(d.power_off_on_system_suspend for d in self._config.devices),
            on_toggle_power_off_on_system_suspend=self._toggle_power_off_on_system_suspend,
            get_power_on_on_system_resume=lambda: any(d.power_on_on_system_resume for d in self._config.devices),
            on_toggle_power_on_on_system_resume=self._toggle_power_on_on_system_resume,
            light=first_light,
            config=self._config,
            version_checker=self._version_checker,
            on_toggle_auto_check_update=self._toggle_auto_check_update,
            get_auto_check_update=lambda: self._config.auto_check_update,
        )
        # Set up state listeners for all lights
        for dev_id, light in self._lights.items():
            light.set_listener(lambda state, did=dev_id: self._on_state_changed(state, did))

        # Initialize hotkey manager (no callbacks in constructor - will be set dynamically)
        self._hotkey_manager = HotkeyManager()
        self._setup_hotkeys()

        # Initialize monitor/system power listener
        need_listener = any(
            d.power_off_on_monitor_sleep or d.power_off_on_system_suspend or d.power_on_on_system_resume
            for d in config.devices
        )
        self._monitor_sleep_listener = MonitorSleepListener(
            on_monitor_sleep=self._on_monitor_sleep if need_listener else None,
            on_monitor_wake=self._on_monitor_wake if need_listener else None,
            on_system_suspend=self._on_system_suspend if need_listener else None,
            on_system_resume=self._on_system_resume if need_listener else None,
        )
        if need_listener:
            self._monitor_sleep_listener.start()
            log.info("Power state listener started")

        # Track light state before monitor sleep for restoration (per-device)
        self._lights_state_before_sleep: dict[str, bool] = {}

        # Cache the imports for later use.
        self._MiMonitorLight = MiMonitorLight
        # Track whether the shutdown has already run, so we don't double-fire
        # when several exit paths converge (tray "退出", atexit, OS shutdown).
        self._shutdown_done = False
        self._shutdown_lock = __import__("threading").Lock()
        # Register the atexit backstop unconditionally — it's a no-op if the
        # power_off_at_exit flag is false at exit time. Covers exit paths that
        # bypass the tray menu (Ctrl+C, taskbar close, sys.exit).
        import atexit
        atexit.register(self._atexit_shutdown)
        # Dedicated top-level window that catches WM_QUERYENDSESSION /
        # WM_ENDSESSION. atexit alone does not run reliably during Windows
        # shutdown — the OS terminates the process before Python's exit
        # handlers finish. The listener runs the power-off synchronously
        # during WM_QUERYENDSESSION while the network stack is still alive.
        self._shutdown_listener = ShutdownListener(self._run_shutdown_power_off)
        self._shutdown_listener.start()

    def _build_light(self, dev_config, MiMonitorLight) -> "MiMonitorLight":
        return MiMonitorLight(
            ip=dev_config.ip,
            token=dev_config.token,
            model=dev_config.model,
            device_id=dev_config.device_id,
            on_ip_changed=lambda new_ip: self._on_ip_changed(dev_config.id, new_ip),
            on_range_changed=lambda lo, hi: self._on_ct_range_changed(dev_config.id, lo, hi),
            on_model_resolved=lambda model: self._on_model_resolved(dev_config.id, model),
            enable_miot_for_unknown=dev_config.enable_miot_for_unknown,
        )

    def run(self) -> int:
        self._tray.start()

        # Start version check in background if enabled (async, non-blocking)
        if self._config.auto_check_update:
            import threading
            def delayed_check():
                import time
                time.sleep(3)  # Wait 3 seconds after startup
                log.info("Starting background version check...")
                self._version_checker.check_async()

                # Wait for check to complete (poll for up to 10 seconds)
                for _ in range(20):
                    if self._version_checker.has_checked():
                        break
                    time.sleep(0.5)

                if self._version_checker.has_checked():
                    log.info("Version check completed")
                    update_info = self._version_checker.get_update_info()

                    # Refresh menu to show update indicator
                    self._tray.refresh_menu_if_update_available()

                    # Show notification popup if update available
                    if update_info:
                        log.info("New version available: v%s", update_info['version'])
                        self._show_update_notification(update_info)
                else:
                    log.warning("Version check timed out")
            threading.Thread(target=delayed_check, daemon=True).start()

        # Power on devices with power_on_at_startup enabled
        devices_to_power_on = [d for d in self._config.devices if d.power_on_at_startup]
        if devices_to_power_on:
            import threading
            threading.Thread(target=self._startup_power_on, daemon=True).start()
        else:
            # No power-on at startup, but still refresh devices without model/device_id
            devices_need_refresh = [
                d for d in self._config.devices
                if d.is_complete() and (not d.model or d.device_id == 0)
            ]
            if devices_need_refresh:
                import threading
                def refresh_all():
                    for dev_config in devices_need_refresh:
                        light = self._lights.get(dev_config.id)
                        if light:
                            light.refresh()
                threading.Thread(target=refresh_all, daemon=True).start()
        try:
            self._flyout.run()
        finally:
            # Primary shutdown path: clean tray "退出". Idempotent — atexit
            # backstop will see _shutdown_done and skip.
            self._run_shutdown_power_off()
            self._hotkey_manager.stop()
            self._tray.stop()
        return 0

    def _startup_power_on(self) -> None:
        """Light follows app startup — refresh, then turn on if reachable."""
        for dev_config in self._config.devices:
            if not dev_config.power_on_at_startup:
                continue
            light = self._lights.get(dev_config.id)
            if not light:
                continue
            state = light.refresh()
            if state.reachable:
                light.set_power(True)
                log.info("Startup power-on sent to %s", dev_config.name)
            else:
                log.info("Skipping startup power-on for %s: device unreachable (%s)",
                         dev_config.name, state.error)

    def _run_shutdown_power_off(self) -> None:
        """Send power-off if configured. Idempotent; safe to call from any thread."""
        with self._shutdown_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True

        log.info("Sending shutdown power-off…")
        for dev_config in self._config.devices:
            if not dev_config.power_off_at_exit:
                continue
            light = self._lights.get(dev_config.id)
            if not light:
                continue
            try:
                light.set_power(False)
                if light.state.reachable:
                    log.info("Shutdown power-off acknowledged for %s", dev_config.name)
                else:
                    log.warning("Shutdown power-off failed for %s: %s",
                                dev_config.name, light.state.error)
            except Exception:  # noqa: BLE001
                log.exception("Shutdown power-off raised for %s", dev_config.name)

    def _atexit_shutdown(self) -> None:
        """Backstop for exit paths that bypass the tray menu (Ctrl+C, taskbar X)."""
        self._run_shutdown_power_off()

    def _toggle_power_on_at_startup(self) -> None:
        # Toggle for first device (backward compat with tray menu checkbox)
        if not self._config.devices:
            return
        new_value = not self._config.devices[0].power_on_at_startup
        self._config.devices[0].power_on_at_startup = new_value
        try:
            self._config.save()
            log.info("power_on_at_startup toggled to %s for %s", new_value, self._config.devices[0].name)
        except OSError as exc:
            log.warning("Failed to save power_on_at_startup: %s", exc)
            self._config.devices[0].power_on_at_startup = not new_value

    def _toggle_power_off_at_exit(self) -> None:
        if not self._config.devices:
            return
        new_value = not self._config.devices[0].power_off_at_exit
        self._config.devices[0].power_off_at_exit = new_value
        try:
            self._config.save()
            log.info("power_off_at_exit toggled to %s for %s", new_value, self._config.devices[0].name)
        except OSError as exc:
            log.warning("Failed to save power_off_at_exit: %s", exc)
            self._config.devices[0].power_off_at_exit = not new_value

    def _toggle_power_off_on_monitor_sleep(self) -> None:
        if not self._config.devices:
            return
        new_value = not self._config.devices[0].power_off_on_monitor_sleep
        self._config.devices[0].power_off_on_monitor_sleep = new_value
        try:
            self._config.save()
            log.info("power_off_on_monitor_sleep toggled to %s for %s", new_value, self._config.devices[0].name)
            # Restart listener with new callbacks
            self._restart_power_listener()
        except OSError as exc:
            log.warning("Failed to save power_off_on_monitor_sleep: %s", exc)
            self._config.devices[0].power_off_on_monitor_sleep = not new_value

    def _toggle_power_off_on_system_suspend(self) -> None:
        if not self._config.devices:
            return
        new_value = not self._config.devices[0].power_off_on_system_suspend
        self._config.devices[0].power_off_on_system_suspend = new_value
        try:
            self._config.save()
            log.info("power_off_on_system_suspend toggled to %s for %s", new_value, self._config.devices[0].name)
            self._restart_power_listener()
        except OSError as exc:
            log.warning("Failed to save power_off_on_system_suspend: %s", exc)
            self._config.devices[0].power_off_on_system_suspend = not new_value

    def _toggle_power_on_on_system_resume(self) -> None:
        if not self._config.devices:
            return
        new_value = not self._config.devices[0].power_on_on_system_resume
        self._config.devices[0].power_on_on_system_resume = new_value
        try:
            self._config.save()
            log.info("power_on_on_system_resume toggled to %s for %s", new_value, self._config.devices[0].name)
            self._restart_power_listener()
        except OSError as exc:
            log.warning("Failed to save power_on_on_system_resume: %s", exc)
            self._config.devices[0].power_on_on_system_resume = not new_value

    def _restart_power_listener(self) -> None:
        """Restart the monitor/system power listener with updated callbacks."""
        if hasattr(self, '_monitor_sleep_listener'):
            self._monitor_sleep_listener.stop()

        from .monitor_sleep_listener import MonitorSleepListener

        need_listener = any(
            d.power_off_on_monitor_sleep or d.power_off_on_system_suspend or d.power_on_on_system_resume
            for d in self._config.devices
        )

        self._monitor_sleep_listener = MonitorSleepListener(
            on_monitor_sleep=self._on_monitor_sleep if need_listener else None,
            on_monitor_wake=self._on_monitor_wake if need_listener else None,
            on_system_suspend=self._on_system_suspend if need_listener else None,
            on_system_resume=self._on_system_resume if need_listener else None,
        )

        if need_listener:
            self._monitor_sleep_listener.start()
            log.info("Power state listener restarted")

    def _on_monitor_sleep(self) -> None:
        """Called when monitor goes to sleep."""
        log.info("Monitor sleep event - turning off lights")
        # Save current light state per device
        self._lights_state_before_sleep = {}
        for dev_config in self._config.devices:
            if not dev_config.power_off_on_monitor_sleep:
                continue
            light = self._lights.get(dev_config.id)
            if not light:
                continue
            state = light.state
            self._lights_state_before_sleep[dev_config.id] = state.is_on
            # Turn off light if it's on
            if state.is_on:
                import threading
                threading.Thread(target=lambda l=light: l.set_power(False), daemon=True).start()

    def _on_monitor_wake(self) -> None:
        """Called when monitor wakes up."""
        log.info("Monitor wake event - restoring light state")
        # Restore light state if it was on before sleep
        for dev_config in self._config.devices:
            if not dev_config.power_off_on_monitor_sleep:
                continue
            light = self._lights.get(dev_config.id)
            if not light:
                continue
            if self._lights_state_before_sleep.get(dev_config.id):
                import threading
                threading.Thread(target=lambda l=light: l.set_power(True), daemon=True).start()

    def _on_system_suspend(self) -> None:
        """Called when system goes to sleep/hibernate."""
        log.info("System suspend event - turning off lights")
        for dev_config in self._config.devices:
            if not dev_config.power_off_on_system_suspend:
                continue
            light = self._lights.get(dev_config.id)
            if light:
                import threading
                threading.Thread(target=lambda l=light: l.set_power(False), daemon=True).start()

    def _on_system_resume(self) -> None:
        """Called when system resumes from sleep/hibernate."""
        log.info("System resume event - turning on lights")
        for dev_config in self._config.devices:
            if not dev_config.power_on_on_system_resume:
                continue
            light = self._lights.get(dev_config.id)
            if light:
                import threading
                threading.Thread(target=lambda l=light: l.set_power(True), daemon=True).start()

    def _toggle_auto_check_update(self) -> None:
        new_value = not self._config.auto_check_update
        self._config.auto_check_update = new_value
        try:
            self._config.save()
            log.info("auto_check_update toggled to %s", new_value)
        except OSError as exc:
            log.warning("Failed to save auto_check_update: %s", exc)
            self._config.auto_check_update = not new_value

    # ---------- callbacks ----------

    def _on_tray_click(self, x: int, y: int) -> None:
        self._flyout.schedule_open(x, y)

    def _on_state_changed(self, state: "LightState", device_id: str) -> None:
        # Called from worker threads — marshal to Tk thread.
        # Only update flyout if this is the active device or in ALL mode
        if self._config.active_device_id == "ALL" or self._config.active_device_id == device_id:
            self._flyout.schedule_apply_state(state)

        # Update tray with aggregate status
        any_on = any(l.state.is_on for l in self._lights.values() if l.state.reachable)
        self._tray.set_state(any_on)

    def _on_ip_changed(self, device_id: str, new_ip: str) -> None:
        """Called when auto-discovery finds the device at a new IP."""
        dev_config = self._find_device_config(device_id)
        if not dev_config:
            return
        log.info("Device %s IP changed to %s, updating config", dev_config.name, new_ip)
        dev_config.ip = new_ip
        try:
            self._config.save()
        except OSError as exc:
            log.warning("Failed to save updated IP: %s", exc)

    def _on_ct_range_changed(self, device_id: str, lo: int, hi: int) -> None:
        """Called from a worker thread once info() resolves the model — push to UI."""
        # Only update flyout if this is the first device (backward compat)
        if self._config.devices and device_id == self._config.devices[0].id:
            self._flyout.schedule_apply_ct_range(lo, hi)

    def _on_model_resolved(self, device_id: str, model: str) -> None:
        """Persist an auto-detected model to config (worker thread)."""
        dev_config = self._find_device_config(device_id)
        if not dev_config or not model or model == dev_config.model:
            return
        log.info("Auto-detected model %s for %s; saving to config", model, dev_config.name)
        dev_config.model = model

        # Update device.id to use hardware device_id if available
        light = self._lights.get(device_id)
        if light and light.device_id > 0:
            old_id = dev_config.id
            new_id = f"{light.device_id:08x}"
            if old_id != new_id:
                dev_config.id = new_id
                # Re-key in lights dict
                self._lights[new_id] = self._lights.pop(old_id)
                log.info("Updated device id from %s to %s", old_id, new_id)

        try:
            self._config.save()
        except OSError as exc:
            log.warning("Failed to save resolved model: %s", exc)

    def _find_device_config(self, device_id: str):
        """Find device config by id."""
        return next((d for d in self._config.devices if d.id == device_id), None)

    def _open_settings(self) -> None:
        # Tk doesn't allow opening a second Tk root from another thread; route
        # through the flyout's Tk loop with after(0) so the wizard is created
        # on the main thread.
        self._flyout._root.after(0, self._show_settings)

    def _show_settings(self) -> None:
        from .device_list_wizard import DeviceListWizard

        DeviceListWizard(
            self._config,
            on_saved=self._on_config_saved,
            parent=self._flyout._root,
        )

    def _on_config_saved(self, config: AppConfig) -> None:
        log.info("Config updated; reconnecting to devices")
        self._config = config

        # Rebuild lights dict from new device list
        old_lights = self._lights
        self._lights = {}
        for dev_config in config.devices:
            if not dev_config.is_complete():
                continue
            # Reuse existing light if device_id matches (avoids reconnection)
            existing = old_lights.get(dev_config.id)
            if existing:
                self._lights[dev_config.id] = existing
            else:
                light = self._build_light(dev_config, self._MiMonitorLight)
                light.set_listener(self._on_state_changed)
                self._lights[dev_config.id] = light

        # Update flyout with first available light (backward compat)
        first_light = next(iter(self._lights.values()), None)
        self._flyout._light = first_light
        if first_light:
            # Reset slider bounds to whatever the freshly-built light reports —
            # info() will refine them once we reconnect, but this keeps the slider
            # consistent if the user picked a different model in the wizard.
            self._flyout.schedule_apply_ct_range(
                first_light.color_temp_min, first_light.color_temp_max
            )

        # Update tray
        self._tray.set_title("Mi Monitor Light")
        if first_light:
            self._tray._light = first_light

        # Update hotkeys
        self._setup_hotkeys()
        # Update monitor/system power listener
        self._restart_power_listener()

        # Trigger a refresh to capture device_id and/or model if missing
        for dev_config in config.devices:
            if dev_config.device_id == 0 or not dev_config.model:
                light = self._lights.get(dev_config.id)
                if light:
                    import threading
                    threading.Thread(target=light.refresh, daemon=True).start()

    def _on_exit(self) -> None:
        self._flyout.shutdown()

    def _show_update_notification(self, update_info: dict) -> None:
        """Show update notification popup on the main Tk thread."""
        def show_dialog():
            try:
                import tkinter as tk
                from tkinter import messagebox
                import webbrowser

                # Use existing flyout root for the dialog
                root = self._flyout._root

                result = messagebox.askyesno(
                    "发现新版本",
                    f"检测到新版本 v{update_info['version']}！\n\n"
                    f"当前版本已过时，是否立即前往下载？\n\n"
                    f"点击「是」在浏览器打开下载页\n"
                    f"点击「否」稍后再说（可在托盘菜单中查看）",
                    parent=root,
                )

                if result:
                    url = update_info.get("url", "")
                    if url:
                        webbrowser.open(url)
                        log.info("Opened update URL: %s", url)
            except Exception as exc:
                log.warning("Failed to show update notification: %s", exc)

        # Schedule on the main Tk thread
        try:
            self._flyout._root.after(0, show_dialog)
        except Exception as exc:
            log.warning("Failed to schedule update dialog: %s", exc)

    def _setup_hotkeys(self) -> None:
        """Configure hotkeys for all devices."""
        try:
            # Clear previous registrations
            self._hotkey_manager._hotkeys_to_register = []

            # Collect all hotkey configurations from devices
            hotkey_id = 1
            callbacks = {}

            for device_id, light in self._lights.items():
                dev_config = self._find_device_config(device_id)
                if not dev_config:
                    continue

                # Register brightness up
                if dev_config.brightness_up:
                    callbacks[hotkey_id] = lambda l=light, s=dev_config.hotkey_step: self._on_device_brightness_up(l, s)
                    self._hotkey_manager.register_hotkey(hotkey_id, dev_config.brightness_up)
                    hotkey_id += 1

                # Register brightness down
                if dev_config.brightness_down:
                    callbacks[hotkey_id] = lambda l=light, s=dev_config.hotkey_step: self._on_device_brightness_down(l, s)
                    self._hotkey_manager.register_hotkey(hotkey_id, dev_config.brightness_down)
                    hotkey_id += 1

                # Register color temp up
                if dev_config.color_temp_up:
                    callbacks[hotkey_id] = lambda l=light, s=dev_config.hotkey_step: self._on_device_color_temp_up(l, s)
                    self._hotkey_manager.register_hotkey(hotkey_id, dev_config.color_temp_up)
                    hotkey_id += 1

                # Register color temp down
                if dev_config.color_temp_down:
                    callbacks[hotkey_id] = lambda l=light, s=dev_config.hotkey_step: self._on_device_color_temp_down(l, s)
                    self._hotkey_manager.register_hotkey(hotkey_id, dev_config.color_temp_down)
                    hotkey_id += 1

            self._hotkey_manager.set_callbacks(callbacks)
            self._hotkey_manager.start()
            log.info("Hotkeys configured for %d devices", len(self._lights))
        except Exception as exc:
            log.warning("Failed to setup hotkeys: %s", exc)

    def _on_device_brightness_up(self, light, step: int) -> None:
        """Hotkey callback: increase brightness for specific device."""
        def _do():
            if not light.state.reachable:
                return
            current = light.state.brightness or 50
            new_value = min(100, current + step)
            light.set_brightness(new_value)
        threading.Thread(target=_do, daemon=True).start()

    def _on_device_brightness_down(self, light, step: int) -> None:
        """Hotkey callback: decrease brightness for specific device."""
        def _do():
            if not light.state.reachable:
                return
            current = light.state.brightness or 50
            new_value = max(1, current - step)
            light.set_brightness(new_value)
        threading.Thread(target=_do, daemon=True).start()

    def _on_device_color_temp_up(self, light, step: int) -> None:
        """Hotkey callback: increase color temp for specific device."""
        def _do():
            if not light.state.reachable:
                return
            current = light.state.color_temp or 4000
            ct_range = light.color_temp_max - light.color_temp_min
            actual_step = int(ct_range * step / 100)
            new_value = min(light.color_temp_max, current + actual_step)
            light.set_color_temp(new_value)
        threading.Thread(target=_do, daemon=True).start()

    def _on_device_color_temp_down(self, light, step: int) -> None:
        """Hotkey callback: decrease color temp for specific device."""
        def _do():
            if not light.state.reachable:
                return
            current = light.state.color_temp or 4000
            ct_range = light.color_temp_max - light.color_temp_min
            actual_step = int(ct_range * step / 100)
            new_value = max(light.color_temp_min, current - actual_step)
            light.set_color_temp(new_value)
        threading.Thread(target=_do, daemon=True).start()



def _run_setup_only(config: AppConfig) -> int:
    from .setup_wizard import SetupWizard

    saved: dict = {}

    def _on_saved(updated: AppConfig) -> None:
        saved["config"] = updated

    wizard = SetupWizard(config, on_saved=_on_saved)
    wizard.run()
    return 0 if saved else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mi-monitor-light-tray")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Open the settings wizard and exit, even if a saved config exists.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _quiet_miio_warnings()

    # Single-instance check — prevent multiple copies running simultaneously.
    lock = SingleInstance("MiMonitorLightTray")
    if not lock.acquired:
        log.warning("Another instance is already running")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning(
                "已在运行",
                "小米显示器挂灯控制程序已经在运行\n\n"
                "请检查系统托盘（屏幕右下角）查看图标",
            )
            root.destroy()
        except Exception:
            pass
        return 1

    config = AppConfig.load()

    # Open wizard if no devices configured OR if --setup flag passed
    if args.setup or not config.devices or not any(d.is_complete() for d in config.devices):
        rc = _run_setup_only(config)
        if rc != 0:
            return rc
        config = AppConfig.load()
        if not config.devices or not any(d.is_complete() for d in config.devices):
            log.error("Setup not completed; exiting.")
            return 1

    app = App(config)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
