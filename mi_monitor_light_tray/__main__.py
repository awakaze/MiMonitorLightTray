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

        self._config = config
        self._light = self._build_light(config, MiMonitorLight)
        self._flyout = FlyoutWindow(self._light, on_open_setup=self._open_settings)
        self._tray = TrayController(
            title=config.device.name or "Mi Monitor Light",
            on_left_click=self._on_tray_click,
            on_open_settings=self._open_settings,
            on_exit=self._on_exit,
            get_power_on_at_startup=lambda: self._config.device.power_on_at_startup,
            on_toggle_power_on_at_startup=self._toggle_power_on_at_startup,
            get_power_off_at_exit=lambda: self._config.device.power_off_at_exit,
            on_toggle_power_off_at_exit=self._toggle_power_off_at_exit,
            light=self._light,
        )
        self._light.set_listener(self._on_state_changed)
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
