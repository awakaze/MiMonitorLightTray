"""Monitor and system power state listener.

Uses only Windows power broadcast messages (WM_POWERBROADCAST). No idle-time
polling — display state and system suspend/resume come exclusively from the
OS so we stay in sync with what Windows itself considers a display-off event.

On modern Windows (10/11), Microsoft has stopped broadcasting
`PBT_APMSUSPEND` / resume events to all top-level windows on Modern Standby
capable machines. Applications are required to explicitly register via
`RegisterSuspendResumeNotification` to keep receiving them. We register with
`DEVICE_NOTIFY_WINDOW_HANDLE` so the notifications still arrive as
`WM_POWERBROADCAST` on our hidden top-level window.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import itertools
import logging
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ── Win32 constants ──────────────────────────────────────────────────────────

WM_POWERBROADCAST = 0x0218
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010

# WM_POWERBROADCAST wparam values
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_POWERSETTINGCHANGE = 0x8013

# Register*Notification flags
DEVICE_NOTIFY_WINDOW_HANDLE = 0x00000000

# GUID_CONSOLE_DISPLAY_STATE = {6fe69556-704a-47a0-8f24-c28d936fda47}
# Correct for Windows 8+. GUID_MONITOR_POWER_ON ({02731015-...}) is deprecated.
_GUID_CONSOLE_DISPLAY_STATE_BYTES = (
    b"\x56\x95\xe6\x6f"
    b"\x4a\x70"
    b"\xa0\x47"
    b"\x8f\x24\xc2\x8d\x93\x6f\xda\x47"
)

# Display state values (from POWERBROADCAST_SETTING.Data for the display GUID)
DISPLAY_STATE_OFF = 0
DISPLAY_STATE_ON = 1
DISPLAY_STATE_DIMMED = 2


# Give each listener instance a fresh window-class name so restarting the
# listener never hits ERROR_CLASS_ALREADY_EXISTS against a stale WNDPROC.
_class_name_counter = itertools.count(1)


# WndProc signature
_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class _WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.wintypes.HINSTANCE),
        ("hIcon", ctypes.wintypes.HICON),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_bytes(cls, buf: bytes) -> "_GUID":
        assert len(buf) == 16
        g = cls()
        ctypes.memmove(ctypes.byref(g), buf, 16)
        return g

    def to_bytes(self) -> bytes:
        return bytes(bytearray(memoryview(ctypes.string_at(ctypes.byref(self), 16))))


class _POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [
        ("PowerSetting", _GUID),
        ("DataLength", ctypes.wintypes.DWORD),
        ("Data", ctypes.c_ubyte * 4),
    ]


def _configure_user32(user32):
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    ]
    user32.CreateWindowExW.restype = ctypes.wintypes.HWND
    user32.RegisterClassW.restype = ctypes.wintypes.ATOM
    user32.UnregisterClassW.restype = ctypes.wintypes.BOOL
    user32.UnregisterClassW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.HINSTANCE,
    ]
    user32.DestroyWindow.restype = ctypes.wintypes.BOOL
    user32.DestroyWindow.argtypes = [ctypes.wintypes.HWND]
    user32.GetMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.wintypes.HWND,
        ctypes.wintypes.UINT,
        ctypes.wintypes.UINT,
    ]
    user32.PostMessageW.restype = ctypes.wintypes.BOOL
    user32.PostMessageW.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    ]
    user32.RegisterPowerSettingNotification.restype = ctypes.c_void_p
    user32.RegisterPowerSettingNotification.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.c_void_p,  # LPCGUID
        ctypes.wintypes.DWORD,
    ]
    user32.UnregisterPowerSettingNotification.restype = ctypes.wintypes.BOOL
    user32.UnregisterPowerSettingNotification.argtypes = [ctypes.c_void_p]
    # RegisterSuspendResumeNotification exists on Windows 8+ (user32.dll).
    # It's how modern-standby machines still deliver PBT_APMSUSPEND / resume
    # to hidden top-level windows.
    if hasattr(user32, "RegisterSuspendResumeNotification"):
        user32.RegisterSuspendResumeNotification.restype = ctypes.c_void_p
        user32.RegisterSuspendResumeNotification.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
        ]
    if hasattr(user32, "UnregisterSuspendResumeNotification"):
        user32.UnregisterSuspendResumeNotification.restype = ctypes.wintypes.BOOL
        user32.UnregisterSuspendResumeNotification.argtypes = [ctypes.c_void_p]


class MonitorSleepListener:
    """Detects monitor sleep/wake and system suspend/resume events.

    Everything comes from WM_POWERBROADCAST on a hidden top-level window:
        - PBT_POWERSETTINGCHANGE + GUID_CONSOLE_DISPLAY_STATE → monitor on/off/dim
          (via `RegisterPowerSettingNotification`)
        - PBT_APMSUSPEND → system suspend
        - PBT_APMRESUMEAUTOMATIC / PBT_APMRESUMESUSPEND → system resume
          (via `RegisterSuspendResumeNotification` — required on modern Windows
          where top-level broadcasts are no longer delivered by default).

    Callbacks (all optional):
        on_monitor_sleep: Called when Windows turns the display off
        on_monitor_wake: Called when Windows turns the display back on
        on_system_suspend: Called when the system goes to sleep/hibernate
        on_system_resume: Called when the system resumes from sleep/hibernate
    """

    def __init__(
        self,
        on_monitor_sleep: Optional[Callable[[], None]] = None,
        on_monitor_wake: Optional[Callable[[], None]] = None,
        on_system_suspend: Optional[Callable[[], None]] = None,
        on_system_resume: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_monitor_sleep = on_monitor_sleep
        self._on_monitor_wake = on_monitor_wake
        self._on_system_suspend = on_system_suspend
        self._on_system_resume = on_system_resume
        self._ready = threading.Event()
        self._stop_event = threading.Event()
        # Track the last display state we broadcast so we don't fire the same
        # transition twice (Windows may send several PBT_POWERSETTINGCHANGE
        # events for the same underlying state).
        self._display_on = True
        self._power_notify_handle: Optional[int] = None
        self._suspend_notify_handle: Optional[int] = None
        self._hwnd: Optional[int] = None
        self._wndproc_ref: Optional[_WNDPROC] = None
        self._class_name = (
            f"MiMonitorLightPowerListener_{next(_class_name_counter)}"
        )

        self._window_thread = threading.Thread(
            target=self._run_window, name="power-listener-window", daemon=True
        )

    def start(self) -> None:
        log.info("Starting power state listener (class=%s)", self._class_name)
        self._window_thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        """Stop the listener thread."""
        self._stop_event.set()
        if self._hwnd:
            try:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostMessageW.restype = ctypes.wintypes.BOOL
                user32.PostMessageW.argtypes = [
                    ctypes.wintypes.HWND,
                    ctypes.wintypes.UINT,
                    ctypes.wintypes.WPARAM,
                    ctypes.wintypes.LPARAM,
                ]
                user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            except Exception:  # noqa: BLE001
                log.debug("PostMessage(WM_CLOSE) failed", exc_info=True)

    def _fire_monitor_sleep(self) -> None:
        if self._display_on:
            self._display_on = False
            log.info("Monitor sleep (display off broadcast)")
            if self._on_monitor_sleep:
                try:
                    self._on_monitor_sleep()
                except Exception:  # noqa: BLE001
                    log.exception("on_monitor_sleep callback raised")

    def _fire_monitor_wake(self) -> None:
        if not self._display_on:
            self._display_on = True
            log.info("Monitor wake (display on broadcast)")
            if self._on_monitor_wake:
                try:
                    self._on_monitor_wake()
                except Exception:  # noqa: BLE001
                    log.exception("on_monitor_wake callback raised")

    def _fire_system_suspend(self) -> None:
        log.info("System suspend detected")
        if self._on_system_suspend:
            try:
                self._on_system_suspend()
            except Exception:  # noqa: BLE001
                log.exception("on_system_suspend callback raised")

    def _fire_system_resume(self) -> None:
        log.info("System resume detected")
        # After resume Windows re-sends a display-on event; reset tracked
        # state so the next off→on transition isn't swallowed.
        self._display_on = True
        if self._on_system_resume:
            try:
                self._on_system_resume()
            except Exception:  # noqa: BLE001
                log.exception("on_system_resume callback raised")

    def _handle_power_setting_change(self, lparam: int) -> None:
        """Parse a PBT_POWERSETTINGCHANGE payload and fire monitor callbacks."""
        try:
            setting = ctypes.cast(
                lparam, ctypes.POINTER(_POWERBROADCAST_SETTING)
            ).contents

            guid_bytes = setting.PowerSetting.to_bytes()
            if guid_bytes != _GUID_CONSOLE_DISPLAY_STATE_BYTES:
                log.debug(
                    "PBT_POWERSETTINGCHANGE for unrelated GUID: %s",
                    guid_bytes.hex(),
                )
                return

            if setting.DataLength < 1:
                log.warning(
                    "POWERBROADCAST_SETTING has zero DataLength for display GUID"
                )
                return

            # The payload for the display GUID is a DWORD (0/1/2). Reading
            # the low byte is enough on little-endian Windows.
            state = int(setting.Data[0])
            log.info(
                "Display state broadcast: %s (0=off, 1=on, 2=dim)", state
            )

            if state == DISPLAY_STATE_OFF:
                self._fire_monitor_sleep()
            elif state == DISPLAY_STATE_ON:
                self._fire_monitor_wake()
            # DISPLAY_STATE_DIMMED (2) is ignored — the monitor is still on.
        except Exception:  # noqa: BLE001
            log.exception("Failed to parse POWERBROADCAST_SETTING")

    def _run_window(self) -> None:
        """Message loop for WM_POWERBROADCAST events.

        System-wide power events (PBT_APMSUSPEND etc.) are broadcast to every
        top-level window in the system on legacy Windows, but modern-standby
        machines require an explicit `RegisterSuspendResumeNotification` call.
        Message-only windows (HWND_MESSAGE) never receive these events.
        """
        user32 = None
        atom = 0
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _configure_user32(user32)

            h_instance = kernel32.GetModuleHandleW(None)

            def wndproc(hwnd, msg, wparam, lparam):
                if msg == WM_POWERBROADCAST:
                    log.info(
                        "WM_POWERBROADCAST wparam=0x%x lparam=0x%x",
                        wparam,
                        lparam,
                    )
                    if wparam == PBT_APMSUSPEND:
                        self._fire_system_suspend()
                    elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                        self._fire_system_resume()
                    elif wparam == PBT_POWERSETTINGCHANGE:
                        self._handle_power_setting_change(lparam)
                    return 1
                if msg == WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                if msg == WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc_ref = _WNDPROC(wndproc)

            wc = _WNDCLASS()
            wc.style = 0
            wc.lpfnWndProc = self._wndproc_ref
            wc.cbClsExtra = 0
            wc.cbWndExtra = 0
            wc.hInstance = h_instance
            wc.hIcon = None
            wc.hCursor = None
            wc.hbrBackground = None
            wc.lpszMenuName = None
            wc.lpszClassName = self._class_name

            atom = user32.RegisterClassW(ctypes.byref(wc))
            if not atom:
                err = ctypes.get_last_error()
                log.error("RegisterClassW failed: err=%s", err)
                self._ready.set()
                return

            # Hidden top-level window. HWND_MESSAGE won't get system broadcasts.
            WS_OVERLAPPED = 0x00000000
            hwnd = user32.CreateWindowExW(
                0,
                self._class_name,
                "MiMonitorLight Power Listener",
                WS_OVERLAPPED,
                0, 0, 0, 0,
                0,   # no parent → top-level
                0,   # no menu
                h_instance,
                None,
            )
            if not hwnd:
                err = ctypes.get_last_error()
                log.error("CreateWindowExW failed: err=%s", err)
                self._ready.set()
                return

            self._hwnd = hwnd
            log.info(
                "Power listener window created (hwnd=0x%x, class=%s)",
                hwnd,
                self._class_name,
            )

            # 1) Subscribe to display-state changes. Without this the display
            #    GUID's PBT_POWERSETTINGCHANGE messages are never delivered.
            guid_struct = _GUID.from_bytes(_GUID_CONSOLE_DISPLAY_STATE_BYTES)
            handle = user32.RegisterPowerSettingNotification(
                hwnd,
                ctypes.byref(guid_struct),
                DEVICE_NOTIFY_WINDOW_HANDLE,
            )
            if not handle:
                err = ctypes.get_last_error()
                log.error(
                    "RegisterPowerSettingNotification failed: err=%s", err
                )
            else:
                self._power_notify_handle = handle
                log.info(
                    "Registered for GUID_CONSOLE_DISPLAY_STATE notifications"
                )

            # 2) Subscribe to suspend/resume. On Modern Standby capable
            #    machines (Win10/11) top-level PBT_APMSUSPEND broadcasts are
            #    NOT delivered by default — explicit registration is required.
            if hasattr(user32, "RegisterSuspendResumeNotification"):
                sr_handle = user32.RegisterSuspendResumeNotification(
                    hwnd, DEVICE_NOTIFY_WINDOW_HANDLE
                )
                if not sr_handle:
                    err = ctypes.get_last_error()
                    log.error(
                        "RegisterSuspendResumeNotification failed: err=%s",
                        err,
                    )
                else:
                    self._suspend_notify_handle = sr_handle
                    log.info("Registered for suspend/resume notifications")
            else:
                log.warning(
                    "RegisterSuspendResumeNotification not available; "
                    "system suspend detection may not work on modern Windows"
                )

            self._ready.set()

            # Message loop.
            msg = ctypes.wintypes.MSG()
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if ret == 0:
                    log.info("Power listener received WM_QUIT — exiting loop")
                    break
                if ret == -1:
                    err = ctypes.get_last_error()
                    log.error("GetMessageW failed: err=%s", err)
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        except Exception:
            log.exception("Power listener thread crashed")
            self._ready.set()
        finally:
            if user32 is not None:
                if self._power_notify_handle:
                    try:
                        user32.UnregisterPowerSettingNotification(
                            self._power_notify_handle
                        )
                    except Exception:  # noqa: BLE001
                        log.debug(
                            "UnregisterPowerSettingNotification failed",
                            exc_info=True,
                        )
                    self._power_notify_handle = None
                if self._suspend_notify_handle and hasattr(
                    user32, "UnregisterSuspendResumeNotification"
                ):
                    try:
                        user32.UnregisterSuspendResumeNotification(
                            self._suspend_notify_handle
                        )
                    except Exception:  # noqa: BLE001
                        log.debug(
                            "UnregisterSuspendResumeNotification failed",
                            exc_info=True,
                        )
                    self._suspend_notify_handle = None
                if atom:
                    try:
                        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                        h_instance = kernel32.GetModuleHandleW(None)
                        user32.UnregisterClassW(self._class_name, h_instance)
                    except Exception:  # noqa: BLE001
                        log.debug("UnregisterClassW failed", exc_info=True)
            self._hwnd = None
