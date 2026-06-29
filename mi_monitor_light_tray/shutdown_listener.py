"""Windows shutdown listener using a dedicated top-level window.

Why this exists: ``atexit`` does not reliably fire during Windows shutdown —
the system terminates the process before Python's exit handlers complete.
Intercepting WndProc on the Tk window is also unreliable because Tk's main
window is hidden/borderless and Windows may not deliver WM_ENDSESSION to it.

This module creates a real top-level window (NOT HWND_MESSAGE, which does
NOT receive WM_QUERYENDSESSION/WM_ENDSESSION) in a dedicated daemon thread,
and runs the shutdown callback during WM_QUERYENDSESSION — the earliest hook,
while the network stack is still fully alive. ShutdownBlockReasonCreate is
called so Windows shows "正在关闭灯…" instead of killing the process during
the brief miio round-trip.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ── Win32 constants ──────────────────────────────────────────────────────────

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION      = 0x0016
WM_CLOSE           = 0x0010
WM_DESTROY         = 0x0002

# WM_ENDSESSION wparam: TRUE if the session is actually ending.
# WM_QUERYENDSESSION lparam flags:
ENDSESSION_CLOSEAPP   = 0x00000001
ENDSESSION_CRITICAL   = 0x40000000
ENDSESSION_LOGOFF     = 0x80000000
# (lparam == 0 means a full system shutdown/reboot)


# WndProc signature — return type must be LRESULT (ssize_t on 64-bit, long on 32-bit).
_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class _WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style",         ctypes.wintypes.UINT),
        ("lpfnWndProc",   _WNDPROC),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     ctypes.wintypes.HINSTANCE),
        ("hIcon",         ctypes.wintypes.HICON),
        ("hCursor",       ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName",  ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
    ]


# Function prototype patches — required so ctypes uses the correct calling
# convention and pointer sizes on x64.
def _configure_user32(user32):
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [
        ctypes.wintypes.HWND, ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
    ]
    user32.CreateWindowExW.restype = ctypes.wintypes.HWND
    user32.RegisterClassW.restype = ctypes.wintypes.ATOM
    user32.GetMessageW.argtypes = [
        ctypes.c_void_p, ctypes.wintypes.HWND,
        ctypes.wintypes.UINT, ctypes.wintypes.UINT,
    ]
    try:
        user32.ShutdownBlockReasonCreate.argtypes = [
            ctypes.wintypes.HWND, ctypes.c_wchar_p,
        ]
        user32.ShutdownBlockReasonCreate.restype = ctypes.wintypes.BOOL
        user32.ShutdownBlockReasonDestroy.argtypes = [ctypes.wintypes.HWND]
        user32.ShutdownBlockReasonDestroy.restype = ctypes.wintypes.BOOL
    except AttributeError:
        pass


class ShutdownListener:
    """Owns a dedicated hidden top-level window that fires ``on_shutdown``
    when Windows is shutting down, logging off, or restarting.

    Idempotent: even if the OS delivers both WM_QUERYENDSESSION and
    WM_ENDSESSION, the callback only runs once.
    """

    _CLASS_NAME = "MiMonitorLightShutdownListener"

    def __init__(self, on_shutdown: Callable[[], None]) -> None:
        self._on_shutdown = on_shutdown
        self._executed = False
        self._executed_lock = threading.Lock()
        self._ready = threading.Event()
        self._hwnd: Optional[int] = None
        self._wndproc_ref: Optional[_WNDPROC] = None  # GC anchor
        self._thread = threading.Thread(
            target=self._run, name="shutdown-listener", daemon=True
        )

    def start(self) -> None:
        self._thread.start()
        # Wait briefly so the window exists before the app continues — keeps
        # the diagnostic logging accurate and ensures we register before the
        # user has a chance to trigger a shutdown.
        self._ready.wait(timeout=2.0)

    def _fire(self, reason: str) -> None:
        with self._executed_lock:
            if self._executed:
                return
            self._executed = True
        log.info("Shutdown listener firing: %s", reason)
        try:
            self._on_shutdown()
        except Exception:  # noqa: BLE001
            log.exception("on_shutdown callback raised")

    def _run(self) -> None:
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            _configure_user32(user32)

            h_instance = kernel32.GetModuleHandleW(None)

            def wndproc(hwnd, msg, wparam, lparam):
                if msg == WM_QUERYENDSESSION:
                    # Windows is asking permission to shut down. Network is
                    # still alive at this stage — do the work HERE, then
                    # return TRUE to approve. Synchronous on purpose: the
                    # OS waits on this return value (subject to the block
                    # reason / hung-app timeout).
                    self._fire(f"WM_QUERYENDSESSION lparam=0x{lparam:08x}")
                    return 1  # TRUE
                if msg == WM_ENDSESSION:
                    # Backstop. If for some reason we did not get
                    # WM_QUERYENDSESSION (rare; can happen on critical
                    # shutdowns), this is the last chance.
                    if wparam:
                        self._fire(f"WM_ENDSESSION wparam={wparam}")
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
            wc.lpszClassName = self._CLASS_NAME

            atom = user32.RegisterClassW(ctypes.byref(wc))
            if not atom:
                # Class might already be registered from a prior run of the
                # interpreter (rare with our single-instance lock, but cheap
                # to handle). Try to create anyway.
                err = ctypes.get_last_error()
                log.debug("RegisterClassW failed: %s", err)

            # IMPORTANT: must be a top-level window (parent=0), NOT a
            # message-only window (parent=HWND_MESSAGE=-3). Message-only
            # windows do NOT receive WM_QUERYENDSESSION / WM_ENDSESSION.
            hwnd = user32.CreateWindowExW(
                0,                       # dwExStyle
                self._CLASS_NAME,        # lpClassName
                "MiMonitorLight Shutdown Listener",  # lpWindowName
                0,                       # dwStyle (no WS_VISIBLE — invisible)
                0, 0, 0, 0,              # x, y, w, h
                0,                       # hWndParent (top-level)
                0,                       # hMenu
                h_instance,              # hInstance
                None,                    # lpParam
            )
            if not hwnd:
                err = ctypes.get_last_error()
                log.error("CreateWindowExW failed: %s", err)
                self._ready.set()
                return

            self._hwnd = hwnd
            log.debug("Shutdown listener window created: hwnd=0x%x", hwnd)

            # Ask Windows to wait for us instead of killing us. The string
            # is shown to the user in the shutdown UI ("This app is
            # preventing shutdown: ...").
            try:
                ok = user32.ShutdownBlockReasonCreate(hwnd, "正在关闭显示器挂灯…")
                log.debug("ShutdownBlockReasonCreate: %s", bool(ok))
            except Exception:  # noqa: BLE001
                log.debug("ShutdownBlockReasonCreate not available", exc_info=True)

            self._ready.set()

            # Pump messages until the window is destroyed.
            msg = ctypes.wintypes.MSG()
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if ret <= 0:  # 0 = WM_QUIT, -1 = error
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            log.exception("Shutdown listener thread crashed")
            self._ready.set()
