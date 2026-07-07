"""Application entrypoint: wires config, tray icon, flyout, and setup wizard."""

from __future__ import annotations

import argparse
import logging
import sys
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
        self._light = self._build_light(config, MiMonitorLight)
        self._flyout = FlyoutWindow(self._light, on_open_setup=self._open_settings)

        # Initialize version checker
        self._version_checker = VersionChecker()
        self._update_available = False

        self._tray = TrayController(
            title=config.device.name or "Mi Monitor Light",
            on_left_click=self._on_tray_click,
            on_open_settings=self._open_settings,
            on_exit=self._on_exit,
            get_power_on_at_startup=lambda: self._config.device.power_on_at_startup,
            on_toggle_power_on_at_startup=self._toggle_power_on_at_startup,
            get_power_off_at_exit=lambda: self._config.device.power_off_at_exit,
            on_toggle_power_off_at_exit=self._toggle_power_off_at_exit,
            get_power_off_on_monitor_sleep=lambda: self._config.device.power_off_on_monitor_sleep,
            on_toggle_power_off_on_monitor_sleep=self._toggle_power_off_on_monitor_sleep,
            get_power_off_on_system_suspend=lambda: self._config.device.power_off_on_system_suspend,
            on_toggle_power_off_on_system_suspend=self._toggle_power_off_on_system_suspend,
            get_power_on_on_system_resume=lambda: self._config.device.power_on_on_system_resume,
            on_toggle_power_on_on_system_resume=self._toggle_power_on_on_system_resume,
            light=self._light,
            config=self._config,
            version_checker=self._version_checker,
            on_toggle_auto_check_update=self._toggle_auto_check_update,
            get_auto_check_update=lambda: self._config.auto_check_update,
        )
        self._light.set_listener(self._on_state_changed)

        # Initialize hotkey manager
        self._hotkey_manager = HotkeyManager(
            on_brightness_up=self._on_hotkey_brightness_up,
            on_brightness_down=self._on_hotkey_brightness_down,
            on_color_temp_up=self._on_hotkey_color_temp_up,
            on_color_temp_down=self._on_hotkey_color_temp_down,
        )
        self._setup_hotkeys()

        # Initialize monitor/system power listener
        self._monitor_sleep_listener = MonitorSleepListener(
            on_monitor_sleep=self._on_monitor_sleep if config.device.power_off_on_monitor_sleep else None,
            on_monitor_wake=self._on_monitor_wake if config.device.power_off_on_monitor_sleep else None,
            on_system_suspend=self._on_system_suspend if config.device.power_off_on_system_suspend else None,
            on_system_resume=self._on_system_resume if config.device.power_on_on_system_resume else None,
        )
        if (config.device.power_off_on_monitor_sleep
                or config.device.power_off_on_system_suspend
                or config.device.power_on_on_system_resume):
            self._monitor_sleep_listener.start()
            log.info("Power state listener started")

        # Track light state before monitor sleep for restoration
        self._light_was_on_before_sleep = False

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

    def _build_light(self, config: AppConfig, MiMonitorLight) -> "MiMonitorLight":
        return MiMonitorLight(
            ip=config.device.ip,
            token=config.device.token,
            model=config.device.model,
            device_id=config.device.device_id,
            on_ip_changed=self._on_ip_changed,
            on_range_changed=self._on_ct_range_changed,
            on_model_resolved=self._on_model_resolved,
            enable_miot_for_unknown=config.device.enable_miot_for_unknown,
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

        if self._config.device.power_on_at_startup:
            import threading
            threading.Thread(target=self._startup_power_on, daemon=True).start()
        elif not self._config.device.model or self._config.device.device_id == 0:
            # No power-on at startup, but we still need at least one refresh so
            # device_id and model get captured into config. Avoids the silent
            # "I never get persisted" trap when the user leaves model="" but
            # never opens the flyout.
            import threading
            threading.Thread(target=self._light.refresh, daemon=True).start()
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
        state = self._light.refresh()
        if state.reachable:
            self._light.set_power(True)
            log.info("Startup power-on sent")
        else:
            log.info("Skipping startup power-on: device unreachable (%s)", state.error)

    def _run_shutdown_power_off(self) -> None:
        """Send power-off if configured. Idempotent; safe to call from any thread."""
        with self._shutdown_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
        if not self._config.device.power_off_at_exit:
            return
        log.info("Sending shutdown power-off…")
        try:
            self._light.set_power(False)
            if self._light.state.reachable:
                log.info("Shutdown power-off acknowledged")
            else:
                log.warning("Shutdown power-off failed: %s", self._light.state.error)
        except Exception:  # noqa: BLE001
            log.exception("Shutdown power-off raised")

    def _atexit_shutdown(self) -> None:
        """Backstop for exit paths that bypass the tray menu (Ctrl+C, taskbar X)."""
        self._run_shutdown_power_off()

    def _toggle_power_on_at_startup(self) -> None:
        new_value = not self._config.device.power_on_at_startup
        self._config.device.power_on_at_startup = new_value
        try:
            self._config.save()
            log.info("power_on_at_startup toggled to %s", new_value)
        except OSError as exc:
            log.warning("Failed to save power_on_at_startup: %s", exc)
            self._config.device.power_on_at_startup = not new_value

    def _toggle_power_off_at_exit(self) -> None:
        new_value = not self._config.device.power_off_at_exit
        self._config.device.power_off_at_exit = new_value
        try:
            self._config.save()
            log.info("power_off_at_exit toggled to %s", new_value)
        except OSError as exc:
            log.warning("Failed to save power_off_at_exit: %s", exc)
            self._config.device.power_off_at_exit = not new_value

    def _toggle_power_off_on_monitor_sleep(self) -> None:
        new_value = not self._config.device.power_off_on_monitor_sleep
        self._config.device.power_off_on_monitor_sleep = new_value
        try:
            self._config.save()
            log.info("power_off_on_monitor_sleep toggled to %s", new_value)
            # Restart listener with new callbacks
            self._restart_power_listener()
        except OSError as exc:
            log.warning("Failed to save power_off_on_monitor_sleep: %s", exc)
            self._config.device.power_off_on_monitor_sleep = not new_value

    def _toggle_power_off_on_system_suspend(self) -> None:
        new_value = not self._config.device.power_off_on_system_suspend
        self._config.device.power_off_on_system_suspend = new_value
        try:
            self._config.save()
            log.info("power_off_on_system_suspend toggled to %s", new_value)
            self._restart_power_listener()
        except OSError as exc:
            log.warning("Failed to save power_off_on_system_suspend: %s", exc)
            self._config.device.power_off_on_system_suspend = not new_value

    def _toggle_power_on_on_system_resume(self) -> None:
        new_value = not self._config.device.power_on_on_system_resume
        self._config.device.power_on_on_system_resume = new_value
        try:
            self._config.save()
            log.info("power_on_on_system_resume toggled to %s", new_value)
            self._restart_power_listener()
        except OSError as exc:
            log.warning("Failed to save power_on_on_system_resume: %s", exc)
            self._config.device.power_on_on_system_resume = not new_value

    def _restart_power_listener(self) -> None:
        """Restart the monitor/system power listener with updated callbacks."""
        if hasattr(self, '_monitor_sleep_listener'):
            self._monitor_sleep_listener.stop()

        from .monitor_sleep_listener import MonitorSleepListener
        self._monitor_sleep_listener = MonitorSleepListener(
            on_monitor_sleep=self._on_monitor_sleep if self._config.device.power_off_on_monitor_sleep else None,
            on_monitor_wake=self._on_monitor_wake if self._config.device.power_off_on_monitor_sleep else None,
            on_system_suspend=self._on_system_suspend if self._config.device.power_off_on_system_suspend else None,
            on_system_resume=self._on_system_resume if self._config.device.power_on_on_system_resume else None,
        )

        if (self._config.device.power_off_on_monitor_sleep
                or self._config.device.power_off_on_system_suspend
                or self._config.device.power_on_on_system_resume):
            self._monitor_sleep_listener.start()
            log.info("Power state listener restarted")

    def _on_monitor_sleep(self) -> None:
        """Called when monitor goes to sleep."""
        if not self._config.device.power_off_on_monitor_sleep:
            return
        log.info("Monitor sleep event - turning off light")
        # Save current light state
        state = self._light.state
        self._light_was_on_before_sleep = state.is_on
        # Turn off light if it's on
        if state.is_on:
            import threading
            threading.Thread(target=lambda: self._light.set_power(False), daemon=True).start()

    def _on_monitor_wake(self) -> None:
        """Called when monitor wakes up."""
        if not self._config.device.power_off_on_monitor_sleep:
            return
        log.info("Monitor wake event - restoring light state")
        # Restore light state if it was on before sleep
        if self._light_was_on_before_sleep:
            import threading
            threading.Thread(target=lambda: self._light.set_power(True), daemon=True).start()
            self._light_was_on_before_sleep = False

    def _on_system_suspend(self) -> None:
        """Called when system goes to sleep/hibernate."""
        if not self._config.device.power_off_on_system_suspend:
            return
        log.info("System suspend event - turning off light")
        import threading
        threading.Thread(target=lambda: self._light.set_power(False), daemon=True).start()

    def _on_system_resume(self) -> None:
        """Called when system resumes from sleep/hibernate."""
        if not self._config.device.power_on_on_system_resume:
            return
        log.info("System resume event - turning on light")
        import threading
        threading.Thread(target=lambda: self._light.set_power(True), daemon=True).start()

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

    def _on_state_changed(self, state: "LightState") -> None:
        # Called from worker threads — marshal to Tk thread.
        self._flyout.schedule_apply_state(state)
        self._tray.set_state(state.is_on)

    def _on_ip_changed(self, new_ip: str) -> None:
        """Called when auto-discovery finds the device at a new IP."""
        log.info("Device IP changed to %s, updating config", new_ip)
        self._config.device.ip = new_ip
        try:
            self._config.save()
        except OSError as exc:
            log.warning("Failed to save updated IP: %s", exc)

    def _on_ct_range_changed(self, lo: int, hi: int) -> None:
        """Called from a worker thread once info() resolves the model — push to UI."""
        self._flyout.schedule_apply_ct_range(lo, hi)

    def _on_model_resolved(self, model: str) -> None:
        """Persist an auto-detected model to config (worker thread)."""
        if not model or model == self._config.device.model:
            return
        log.info("Auto-detected model %s; saving to config", model)
        self._config.device.model = model
        try:
            self._config.save()
        except OSError as exc:
            log.warning("Failed to save resolved model: %s", exc)

    def _open_settings(self) -> None:
        # Tk doesn't allow opening a second Tk root from another thread; route
        # through the flyout's Tk loop with after(0) so the wizard is created
        # on the main thread.
        self._flyout._root.after(0, self._show_settings)

    def _show_settings(self) -> None:
        from .setup_wizard import SetupWizard

        SetupWizard(
            self._config,
            on_saved=self._on_config_saved,
            parent=self._flyout._root,
        )

    def _on_config_saved(self, config: AppConfig) -> None:
        log.info("Config updated; reconnecting to %s", config.device.ip)
        self._config = config
        self._light = self._build_light(config, self._MiMonitorLight)
        self._light.set_listener(self._on_state_changed)
        self._flyout._light = self._light
        # Reset slider bounds to whatever the freshly-built light reports —
        # info() will refine them once we reconnect, but this keeps the slider
        # consistent if the user picked a different model in the wizard.
        self._flyout.schedule_apply_ct_range(
            self._light.color_temp_min, self._light.color_temp_max
        )
        self._tray.set_title(config.device.name or "Mi Monitor Light")
        # Update hotkeys
        self._setup_hotkeys()
        # Update monitor/system power listener
        self._restart_power_listener()
        # Trigger a refresh to capture device_id and/or model if missing —
        # _on_model_resolved handles model persistence; we still need this
        # thread to backfill device_id, which has no listener.
        if config.device.device_id == 0 or not config.device.model:
            import threading
            threading.Thread(target=self._initial_refresh, daemon=True).start()

    def _initial_refresh(self) -> None:
        """Refresh device state and save device_id to config if newly captured.

        Model persistence is handled by ``_on_model_resolved`` (fired from
        within the light's _record_success when auto-detect runs); this method
        only covers device_id, which has no callback hook.
        """
        self._light.refresh()
        if self._light.device_id > 0 and self._config.device.device_id == 0:
            self._config.device.device_id = self._light.device_id
            try:
                self._config.save()
                log.info("Saved device_id %08x to config", self._light.device_id)
            except OSError as exc:
                log.warning("Failed to save device_id: %s", exc)

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
        """Configure hotkeys based on current config."""
        try:
            self._hotkey_manager.set_hotkeys(
                brightness_up=self._config.hotkey.brightness_up,
                brightness_down=self._config.hotkey.brightness_down,
                color_temp_up=self._config.hotkey.color_temp_up,
                color_temp_down=self._config.hotkey.color_temp_down,
            )
            log.info("Hotkeys configured")
        except Exception as exc:
            log.warning("Failed to setup hotkeys: %s", exc)

    def _on_hotkey_brightness_up(self) -> None:
        """Hotkey callback: increase brightness."""
        state = self._light.state
        if not state.reachable:
            return
        current = state.brightness or 50
        step = self._config.hotkey.step
        new_value = min(100, current + step)
        # Direct call - set_brightness is already immediate
        self._light.set_brightness(new_value)
        log.debug("Hotkey: brightness %d -> %d", current, new_value)

    def _on_hotkey_brightness_down(self) -> None:
        """Hotkey callback: decrease brightness."""
        state = self._light.state
        if not state.reachable:
            return
        current = state.brightness or 50
        step = self._config.hotkey.step
        new_value = max(1, current - step)
        # Direct call - set_brightness is already immediate
        self._light.set_brightness(new_value)
        log.debug("Hotkey: brightness %d -> %d", current, new_value)

    def _on_hotkey_color_temp_up(self) -> None:
        """Hotkey callback: increase color temperature (cooler)."""
        state = self._light.state
        if not state.reachable:
            return
        current = state.color_temp or 4000
        step = self._config.hotkey.step
        # Scale step based on color temp range
        ct_range = self._light.color_temp_max - self._light.color_temp_min
        actual_step = int(ct_range * step / 100)  # step as percentage
        new_value = min(self._light.color_temp_max, current + actual_step)
        # Direct call - set_color_temp is already immediate
        self._light.set_color_temp(new_value)
        log.debug("Hotkey: color temp %d -> %d", current, new_value)

    def _on_hotkey_color_temp_down(self) -> None:
        """Hotkey callback: decrease color temperature (warmer)."""
        state = self._light.state
        if not state.reachable:
            return
        current = state.color_temp or 4000
        step = self._config.hotkey.step
        # Scale step based on color temp range
        ct_range = self._light.color_temp_max - self._light.color_temp_min
        actual_step = int(ct_range * step / 100)  # step as percentage
        new_value = max(self._light.color_temp_min, current - actual_step)
        # Direct call - set_color_temp is already immediate
        self._light.set_color_temp(new_value)
        log.debug("Hotkey: color temp %d -> %d", current, new_value)


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

    if args.setup or not config.device.is_complete():
        rc = _run_setup_only(config)
        if rc != 0:
            return rc
        config = AppConfig.load()
        if not config.device.is_complete():
            log.error("Setup not completed; exiting.")
            return 1

    app = App(config)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
