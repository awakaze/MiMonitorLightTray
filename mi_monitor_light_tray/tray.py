"""System-tray icon glue between pystray (worker thread) and the Tk flyout."""

from __future__ import annotations

import ctypes
import logging
import threading
from typing import Callable

import pystray
from pystray import Menu, MenuItem

from . import autostart
from .icon import make_tray_icon
from .desktop_widget import DesktopWidget

log = logging.getLogger(__name__)


def _cursor_pos() -> tuple[int, int]:
    """Return the current cursor position (x, y).

    pystray does not expose the icon's pixel location; the cursor is on or
    next to the icon when the user clicks it, which is good enough to anchor
    the flyout near the tray.
    """
    try:
        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = _POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)
    except (OSError, AttributeError):
        return 0, 0


class TrayController:
    def __init__(
        self,
        *,
        title: str,
        on_left_click: Callable[[int, int], None],
        on_open_settings: Callable[[], None],
        on_exit: Callable[[], None],
        get_power_on_at_startup: Callable[[], bool],
        on_toggle_power_on_at_startup: Callable[[], None],
        get_power_off_at_exit: Callable[[], bool],
        on_toggle_power_off_at_exit: Callable[[], None],
        get_power_off_on_monitor_sleep: Callable[[], bool],
        on_toggle_power_off_on_monitor_sleep: Callable[[], None],
        get_power_off_on_system_suspend: Callable[[], bool],
        on_toggle_power_off_on_system_suspend: Callable[[], None],
        get_power_on_on_system_resume: Callable[[], bool],
        on_toggle_power_on_on_system_resume: Callable[[], None],
        light: Optional[object] = None,
        config: Optional[object] = None,
        version_checker: Optional[object] = None,
        on_toggle_auto_check_update: Optional[Callable[[], None]] = None,
        get_auto_check_update: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._on_left_click = on_left_click
        self._on_open_settings = on_open_settings
        self._on_exit = on_exit
        self._get_power_on_at_startup = get_power_on_at_startup
        self._on_toggle_power_on_at_startup = on_toggle_power_on_at_startup
        self._get_power_off_at_exit = get_power_off_at_exit
        self._on_toggle_power_off_at_exit = on_toggle_power_off_at_exit
        self._get_power_off_on_monitor_sleep = get_power_off_on_monitor_sleep
        self._on_toggle_power_off_on_monitor_sleep = on_toggle_power_off_on_monitor_sleep
        self._get_power_off_on_system_suspend = get_power_off_on_system_suspend
        self._on_toggle_power_off_on_system_suspend = on_toggle_power_off_on_system_suspend
        self._get_power_on_on_system_resume = get_power_on_on_system_resume
        self._on_toggle_power_on_on_system_resume = on_toggle_power_on_on_system_resume
        self._light = light
        self._config = config
        self._version_checker = version_checker
        self._on_toggle_auto_check_update = on_toggle_auto_check_update
        self._get_auto_check_update = get_auto_check_update
        self._desktop_widget: Optional[DesktopWidget] = None
        self._title = title  # Store title before building menu

        # Build menu dynamically to support update notification
        self._build_menu()
        self._thread: threading.Thread | None = None

    def _build_menu(self) -> None:
        """Build or rebuild the tray menu."""
        menu_items = [
            MenuItem("Open", self._handle_open, default=True, visible=False),
            MenuItem("调整亮度", self._handle_open),
            MenuItem("设置", self._handle_settings),
            MenuItem(
                "开机自启动",
                self._handle_toggle_autostart,
                checked=lambda _i: autostart.is_enabled(),
            ),
            Menu.SEPARATOR,
            MenuItem(
                "固定在桌面上",
                self._handle_toggle_desktop_widget,
                checked=lambda _i: self._desktop_widget is not None and self._desktop_widget._visible,
            ),
        ]

        # Add update menu items
        if self._version_checker:
            menu_items.append(Menu.SEPARATOR)

            # Check if update is available
            if self._version_checker.has_checked():
                update_info = self._version_checker.get_update_info()
                if update_info:
                    menu_items.append(MenuItem(
                        f"🔔 新版本可用: v{update_info['version']}",
                        self._handle_download_update,
                    ))

            # Manual check for updates
            menu_items.append(MenuItem("检查更新", self._handle_check_update))

            # Auto-check toggle
            if self._get_auto_check_update:
                menu_items.append(MenuItem(
                    "启动时自动检查更新",
                    self._handle_toggle_auto_check_update,
                    checked=lambda _i: self._get_auto_check_update(),
                ))

            # GitHub link
            menu_items.append(MenuItem("访问 GitHub 主页", self._handle_open_github))

        menu_items.append(Menu.SEPARATOR)
        menu_items.append(MenuItem("退出", self._handle_exit))

        self._icon = pystray.Icon(
            "mi-monitor-light-tray",
            icon=make_tray_icon(64, on=True),
            title=self._title,
            menu=Menu(*menu_items),
        )

    def start(self) -> None:
        # Rebuild menu in case version check completed
        if self._version_checker and self._version_checker.has_checked():
            try:
                self._build_menu()
            except Exception as exc:
                log.warning("Failed to build menu with version check: %s", exc)
        self._thread = threading.Thread(target=self._icon.run, name="tray", daemon=True)
        self._thread.start()

    def refresh_menu_if_update_available(self) -> None:
        """Rebuild menu if version check found an update (called from main thread)."""
        if self._version_checker and self._version_checker.has_checked():
            update_info = self._version_checker.get_update_info()
            if update_info:
                log.info("Update available, refreshing menu: v%s", update_info['version'])
                try:
                    # Rebuild the icon with new menu
                    old_icon = self._icon
                    self._build_menu()
                    # Update the running icon's menu
                    if hasattr(old_icon, '_menu_handle'):
                        old_icon.update_menu()
                except Exception as exc:
                    log.warning("Failed to refresh menu: %s", exc)

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001
            log.debug("Tray icon stop failed", exc_info=True)

    def set_title(self, title: str) -> None:
        self._title = title
        self._icon.title = title

    def set_state(self, on: bool) -> None:
        try:
            self._icon.icon = make_tray_icon(64, on=on)
        except Exception:  # noqa: BLE001
            log.debug("Tray icon update failed", exc_info=True)

    # ---------- pystray callbacks (run on tray thread) ----------

    def _handle_open(self, _icon, _item) -> None:
        x, y = _cursor_pos()
        self._on_left_click(x, y)

    def _handle_settings(self, _icon, _item) -> None:
        self._on_open_settings()

    def _handle_toggle_autostart(self, icon, _item) -> None:
        new_state = autostart.toggle()
        log.info("Autostart toggled to %s", new_state)
        # Force the menu to redraw so the checkmark reflects the new state.
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("update_menu failed", exc_info=True)

    def _handle_toggle_power_on_at_startup(self, icon, _item) -> None:
        try:
            self._on_toggle_power_on_at_startup()
        except Exception:  # noqa: BLE001
            log.exception("power_on_at_startup toggle failed")
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("update_menu failed", exc_info=True)

    def _handle_toggle_power_off_at_exit(self, icon, _item) -> None:
        try:
            self._on_toggle_power_off_at_exit()
        except Exception:  # noqa: BLE001
            log.exception("power_off_at_exit toggle failed")
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("update_menu failed", exc_info=True)

    def _handle_toggle_power_off_on_monitor_sleep(self, icon, _item) -> None:
        try:
            self._on_toggle_power_off_on_monitor_sleep()
        except Exception:  # noqa: BLE001
            log.exception("power_off_on_monitor_sleep toggle failed")
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("update_menu failed", exc_info=True)

    def _handle_toggle_power_off_on_system_suspend(self, icon, _item) -> None:
        try:
            self._on_toggle_power_off_on_system_suspend()
        except Exception:  # noqa: BLE001
            log.exception("power_off_on_system_suspend toggle failed")
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("update_menu failed", exc_info=True)

    def _handle_toggle_power_on_on_system_resume(self, icon, _item) -> None:
        try:
            self._on_toggle_power_on_on_system_resume()
        except Exception:  # noqa: BLE001
            log.exception("power_on_on_system_resume toggle failed")
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("update_menu failed", exc_info=True)

    def _handle_toggle_desktop_widget(self, icon, _item) -> None:
        """切换桌面小部件的显示状态。"""
        if self._light is None:
            log.warning("灯光控制客户端未初始化，无法显示桌面小部件")
            return

        if self._desktop_widget is None:
            # 创建桌面小部件
            self._desktop_widget = DesktopWidget(
                self._light,
                config=self._config,
                on_open_setup=self._on_open_settings,
            )
            self._desktop_widget.show()
            log.info("桌面小部件已创建并显示")
        else:
            # 切换显示状态
            self._desktop_widget.toggle_visibility()
            if self._desktop_widget._visible:
                log.info("桌面小部件已显示")
            else:
                log.info("桌面小部件已隐藏")

        # 更新菜单状态
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("update_menu failed", exc_info=True)

    def _handle_exit(self, _icon, _item) -> None:
        self._on_exit()
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001
            log.debug("Tray icon stop failed", exc_info=True)

    def _handle_check_update(self, _icon, _item) -> None:
        """Manually check for updates."""
        if self._version_checker:
            import threading
            def check_and_notify():
                log.info("Manually checking for updates...")
                # Force a fresh check
                from .version_checker import check_for_updates
                update_info = check_for_updates()

                # Update the checker's cache
                self._version_checker._update_info = update_info
                self._version_checker._checked = True

                # Rebuild menu to show result
                try:
                    self._build_menu()
                except Exception as exc:
                    log.warning("Failed to rebuild menu: %s", exc)

                # Show notification
                if update_info:
                    try:
                        import tkinter as tk
                        from tkinter import messagebox
                        root = tk.Tk()
                        root.withdraw()
                        messagebox.showinfo(
                            "发现新版本",
                            f"新版本 v{update_info['version']} 可用！\n\n"
                            f"右键托盘菜单 → 访问Github 下载更新。",
                            parent=root,
                        )
                        root.destroy()
                    except Exception as exc:
                        log.warning("Failed to show update dialog: %s", exc)
                else:
                    try:
                        import tkinter as tk
                        from tkinter import messagebox
                        root = tk.Tk()
                        root.withdraw()
                        from .version_checker import get_current_version
                        current = get_current_version()
                        messagebox.showinfo(
                            "已是最新版本",
                            f"当前版本 v{current} 已是最新版本。",
                            parent=root,
                        )
                        root.destroy()
                    except Exception as exc:
                        log.warning("Failed to show no-update dialog: %s", exc)

            threading.Thread(target=check_and_notify, daemon=True).start()

    def _handle_download_update(self, _icon, _item) -> None:
        """Open the update download page in browser."""
        if self._version_checker:
            update_info = self._version_checker.get_update_info()
            if update_info and update_info.get("url"):
                import webbrowser
                webbrowser.open(update_info["url"])
                log.info("Opened update URL: %s", update_info["url"])

    def _handle_open_github(self, _icon, _item) -> None:
        """Open GitHub repository in browser."""
        import webbrowser
        url = "https://github.com/Martlnez/MiMonitorLightTray"
        webbrowser.open(url)
        log.info("Opened GitHub: %s", url)

    def _handle_toggle_auto_check_update(self, icon, _item) -> None:
        """Toggle auto-check for updates on startup."""
        if self._on_toggle_auto_check_update:
            try:
                self._on_toggle_auto_check_update()
            except Exception:  # noqa: BLE001
                log.exception("auto_check_update toggle failed")
            try:
                icon.update_menu()
            except Exception:  # noqa: BLE001
                log.debug("update_menu failed", exc_info=True)
