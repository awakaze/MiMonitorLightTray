"""Monitor and system power state listener.

Detects monitor sleep/wake via user idle time detection, and system
suspend/resume via Windows power broadcast messages.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ── Win32 constants ──────────────────────────────────────────────────────────

WM_POWERBROADCAST = 0x0218
WM_DESTROY = 0x0002

# WM_POWERBROADCAST wparam values
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMPOWERSTATUSCHANGE = 0x000A
PBT_POWERSETTINGCHANGE = 0x8013


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


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_uint),
        ('dwTime', ctypes.c_uint),
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
    user32.GetMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.wintypes.HWND,
        ctypes.wintypes.UINT,
        ctypes.wintypes.UINT,
    ]


def _get_idle_time_ms() -> int:
    """Get user idle time in milliseconds."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)

        if user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = kernel32.GetTickCount()
            return millis - lii.dwTime
        return 0
    except Exception:  # noqa: BLE001
        return 0


class MonitorSleepListener:
    """Detects monitor sleep/wake and system suspend/resume events.

    Monitor sleep/wake is detected via user idle time (55 second threshold).
    System suspend/resume is detected via WM_POWERBROADCAST messages.

    Callbacks (all optional):
        on_monitor_sleep: Called when user is idle >= threshold
        on_monitor_wake: Called when user becomes active again
        on_system_suspend: Called when system goes to sleep/hibernate
        on_system_resume: Called when system resumes from sleep/hibernate
    """

    _CLASS_NAME = "MiMonitorLightPowerListener"
    CHECK_INTERVAL = 1.0
    IDLE_THRESHOLD_MS = 55 * 1000  # 55 seconds

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
        self._monitor_is_off = False
        self._hwnd: Optional[int] = None
        self._wndproc_ref: Optional[_WNDPROC] = None

        self._window_thread = threading.Thread(
            target=self._run_window, name="power-listener-window", daemon=True
        )
        self._monitor_thread = threading.Thread(
            target=self._run_monitor, name="power-listener-idle", daemon=True
        )

    def start(self) -> None:
        log.info("Starting power state listener")
        self._window_thread.start()
        self._monitor_thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        """Stop the listener threads."""
        self._stop_event.set()
        if self._hwnd:
            try:
                user32 = ctypes.windll.user32
                user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)
            except Exception:  # noqa: BLE001
                pass

    def _fire_monitor_sleep(self) -> None:
        if not self._monitor_is_off:
            self._monitor_is_off = True
            log.info("Monitor sleep detected (idle timeout)")
            if self._on_monitor_sleep:
                try:
                    self._on_monitor_sleep()
                except Exception:  # noqa: BLE001
                    log.exception("on_monitor_sleep callback raised")

    def _fire_monitor_wake(self) -> None:
        if self._monitor_is_off:
            self._monitor_is_off = False
            log.info("Monitor wake detected (user activity)")
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
        if self._on_system_resume:
            try:
                self._on_system_resume()
            except Exception:  # noqa: BLE001
                log.exception("on_system_resume callback raised")

    def _run_monitor(self) -> None:
        """Idle time monitoring for monitor sleep/wake detection."""
        log.debug("Idle monitor thread started")

        while not self._stop_event.is_set():
            try:
                idle_ms = _get_idle_time_ms()

                if idle_ms >= self.IDLE_THRESHOLD_MS:
                    self._fire_monitor_sleep()
                else:
                    self._fire_monitor_wake()

            except Exception:  # noqa: BLE001
                log.debug("Idle check failed", exc_info=True)

            self._stop_event.wait(self.CHECK_INTERVAL)

    def _run_window(self) -> None:
        """Message loop for WM_POWERBROADCAST events (system suspend/resume).

        System-wide power events like PBT_APMSUSPEND are broadcast to all
        top-level windows in the system. We create a hidden top-level window
        to receive these broadcasts.
        """
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            _configure_user32(user32)

            h_instance = kernel32.GetModuleHandleW(None)

            def wndproc(hwnd, msg, wparam, lparam):
                if msg == WM_POWERBROADCAST:
                    log.debug("WM_POWERBROADCAST received: wparam=0x%x", wparam)
                    if wparam == PBT_APMSUSPEND:
                        self._fire_system_suspend()
                    elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                        self._fire_system_resume()
                        self._monitor_is_off = False
                    return 1
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
            wc.lpszClassName = self._CLASS_NAME

            atom = user32.RegisterClassW(ctypes.byref(wc))
            if not atom:
                err = ctypes.get_last_error()
                log.debug("RegisterClassW failed: %s", err)

            # Create a top-level window (HWND_MESSAGE-style windows do NOT
            # receive WM_POWERBROADCAST broadcasts; we need a real top-level).
            # Use WS_OVERLAPPED and don't show it — invisible but top-level.
            WS_OVERLAPPED = 0x00000000
            hwnd = user32.CreateWindowExW(
                0,
                self._CLASS_NAME,
                "MiMonitorLight Power Listener",
                WS_OVERLAPPED,
                0, 0, 0, 0,
                0,  # HWND_DESKTOP as parent (top-level)
                0,
                h_instance,
                None,
            )
            if not hwnd:
                err = ctypes.get_last_error()
                log.error("CreateWindowExW failed: %s", err)
                self._ready.set()
                return

            self._hwnd = hwnd
            log.info("Power listener window created: hwnd=0x%x", hwnd)

            self._ready.set()

            # Message loop
            msg = ctypes.wintypes.MSG()
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if ret <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        except Exception:
            log.exception("Power listener thread crashed")
            self._ready.set()
