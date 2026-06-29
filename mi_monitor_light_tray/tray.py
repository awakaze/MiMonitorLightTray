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
        light: Optional[object] = None,
    ) -> None:
        self._on_left_click = on_left_click
        self._on_open_settings = on_open_settings
        self._on_exit = on_exit
        self._get_power_on_at_startup = get_power_on_at_startup
        self._on_toggle_power_on_at_startup = on_toggle_power_on_at_startup
        self._get_power_off_at_exit = get_power_off_at_exit
        self._on_toggle_power_off_at_exit = on_toggle_power_off_at_exit
        self._light = light
        self._desktop_widget: Optional[DesktopWidget] = None

        self._icon = pystray.Icon(
            "mi-monitor-light-tray",
            icon=make_tray_icon(64, on=True),
            title=title,
            menu=Menu(
                MenuItem("Open", self._handle_open, default=True, visible=False),
                MenuItem("调整亮度", self._handle_open),
                MenuItem("设置", self._handle_settings),
                MenuItem(
                    "开机自启动",
                    self._handle_toggle_autostart,
                    checked=lambda _i: autostart.is_enabled(),
                ),
                MenuItem(
                    "灯跟随软件启动",
                    self._handle_toggle_power_on_at_startup,
                    checked=lambda _i: self._get_power_on_at_startup(),
                ),
                MenuItem(
                    "灯跟随软件关闭",
                    self._handle_toggle_power_off_at_exit,
                    checked=lambda _i: self._get_power_off_at_exit(),
                ),
                Menu.SEPARATOR,
                MenuItem(
                    "固定在桌面上",
                    self._handle_toggle_desktop_widget,
                    checked=lambda _i: self._desktop_widget is not None and self._desktop_widget._visible,
                ),
                MenuItem("退出", self._handle_exit),
            ),
        )
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._icon.run, name="tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001
            log.debug("Tray icon stop failed", exc_info=True)

    def set_title(self, title: str) -> None:
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

    def _handle_toggle_desktop_widget(self, icon, _item) -> None:
        """切换桌面小部件的显示状态。"""
        if self._light is None:
            log.warning("灯光控制客户端未初始化，无法显示桌面小部件")
            return

        if self._desktop_widget is None:
            # 创建桌面小部件
            self._desktop_widget = DesktopWidget(
                self._light,
                on_open_setup=self._on_open_settings
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
