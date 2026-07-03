"""Global hotkey manager using Windows RegisterHotKey API.

Uses Win32 RegisterHotKey with a thread-local message queue (hWnd=NULL).
Works even in fullscreen games. Does not require admin rights or a window.

Supports auto-repeat with acceleration: hold key for continuous adjustment,
speed increases gradually (slow → medium → fast).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

# Windows constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
# MOD_NOREPEAT removed - we want auto-repeat for long press

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# Virtual key codes
VK_MAP = {
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "insert": 0x2D,
}

# Generate F1-F12
for i in range(1, 13):
    VK_MAP[f"f{i}"] = 0x70 + i - 1

# Generate A-Z
for i in range(26):
    VK_MAP[chr(ord('a') + i)] = ord('A') + i

# Generate 0-9
for i in range(10):
    VK_MAP[str(i)] = ord('0') + i


# Win32 API function signatures
user32 = ctypes.windll.user32

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL

user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL

user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int

user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL

kernel32 = ctypes.windll.kernel32
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class HotkeyManager:
    """Manages global hotkeys using Windows RegisterHotKey API."""

    def __init__(
        self,
        on_brightness_up: Optional[Callable[[], None]] = None,
        on_brightness_down: Optional[Callable[[], None]] = None,
        on_color_temp_up: Optional[Callable[[], None]] = None,
        on_color_temp_down: Optional[Callable[[], None]] = None,
    ) -> None:
        self._callbacks = {
            1: on_brightness_up,
            2: on_brightness_down,
            3: on_color_temp_up,
            4: on_color_temp_down,
        }
        self._thread: Optional[threading.Thread] = None
        self._thread_id: int = 0
        self._running = False

        # Auto-repeat acceleration tracking
        self._repeat_count = {}  # hotkey_id -> count
        self._last_trigger = {}  # hotkey_id -> timestamp

    def set_hotkeys(
        self,
        brightness_up: str = "",
        brightness_down: str = "",
        color_temp_up: str = "",
        color_temp_down: str = "",
    ) -> None:
        """Set hotkey combinations and restart listener."""
        self.stop()

        hotkeys = [
            (1, brightness_up),
            (2, brightness_down),
            (3, color_temp_up),
            (4, color_temp_down),
        ]

        # Parse and validate hotkeys
        parsed = []
        for hotkey_id, hotkey_str in hotkeys:
            if not hotkey_str.strip():
                continue
            try:
                mods, vk = self._parse_hotkey(hotkey_str)
                if vk:
                    parsed.append((hotkey_id, mods, vk, hotkey_str))
                else:
                    log.warning("Hotkey '%s' has no valid key", hotkey_str)
            except Exception as exc:
                log.warning("Invalid hotkey '%s': %s", hotkey_str, exc)

        if not parsed:
            log.info("No hotkeys configured")
            return

        # Start message loop thread
        self._running = True
        self._thread = threading.Thread(
            target=self._message_loop,
            args=(parsed,),
            daemon=True,
            name="hotkey-listener"
        )
        self._thread.start()

    def _parse_hotkey(self, hotkey: str) -> tuple[int, int]:
        """Parse hotkey string to modifiers and virtual key code."""
        parts = [p.strip().lower() for p in hotkey.split("+")]
        modifiers = 0
        vk = 0

        for part in parts:
            if not part:
                continue
            if part in ("ctrl", "control"):
                modifiers |= MOD_CONTROL
            elif part == "alt":
                modifiers |= MOD_ALT
            elif part == "shift":
                modifiers |= MOD_SHIFT
            elif part in ("win", "windows"):
                modifiers |= MOD_WIN
            elif part in VK_MAP:
                vk = VK_MAP[part]
            elif len(part) == 1 and part.isalpha():
                vk = ord(part.upper())
            elif len(part) == 1 and part.isdigit():
                vk = ord(part)
            else:
                log.warning("Unknown key part: '%s'", part)

        log.info("Parsed hotkey '%s' -> modifiers=0x%x, vk=0x%x", hotkey, modifiers, vk)
        return modifiers, vk

    def _message_loop(self, hotkeys: list) -> None:
        """Message loop thread that registers hotkeys and handles WM_HOTKEY."""
        try:
            # Get current thread ID for later PostThreadMessage
            self._thread_id = kernel32.GetCurrentThreadId()
            log.info("Hotkey thread started, TID=%d", self._thread_id)

            # Register all hotkeys with hWnd=NULL (messages go to thread queue)
            registered = []
            for hotkey_id, mods, vk, hotkey_str in hotkeys:
                # Don't add MOD_NOREPEAT - we want auto-repeat for long press
                result = user32.RegisterHotKey(None, hotkey_id, mods, vk)
                if result:
                    registered.append(hotkey_id)
                    log.info("Registered hotkey #%d: '%s' (mods=0x%x, vk=0x%x)",
                             hotkey_id, hotkey_str, mods, vk)
                else:
                    err = ctypes.get_last_error()
                    log.warning("Failed to register hotkey #%d '%s': error=%d (may be in use)",
                                hotkey_id, hotkey_str, err)

            if not registered:
                log.warning("No hotkeys could be registered")
                return

            log.info("Hotkey listener active with %d hotkey(s), waiting for events...", len(registered))

            # Message loop
            msg = wintypes.MSG()
            while self._running:
                # GetMessageW: hWnd=NULL means "thread messages"
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    log.debug("GetMessage returned %d, exiting loop", ret)
                    break

                if msg.message == WM_HOTKEY:
                    hotkey_id = msg.wParam
                    current_time = time.time()

                    # Auto-repeat acceleration logic
                    last_time = self._last_trigger.get(hotkey_id, 0)
                    time_delta = current_time - last_time

                    # Reset count if too much time passed (key was released)
                    if time_delta > 0.5:
                        self._repeat_count[hotkey_id] = 0

                    # Increment repeat counter
                    count = self._repeat_count.get(hotkey_id, 0) + 1
                    self._repeat_count[hotkey_id] = count
                    self._last_trigger[hotkey_id] = current_time

                    # Acceleration tiers:
                    # 1-5: slow (every trigger)
                    # 6-15: medium (every trigger)
                    # 16+: fast (every trigger, but OS auto-repeat is faster)
                    # Skip some events for smoother acceleration
                    if count <= 5:
                        # Slow: process all
                        skip = False
                    elif count <= 15:
                        # Medium: skip none (but system repeat is getting faster)
                        skip = False
                    else:
                        # Fast: process all (system auto-repeat is at max speed)
                        skip = False

                    if not skip:
                        log.debug("WM_HOTKEY id=%d, count=%d, delta=%.3f", hotkey_id, count, time_delta)
                        callback = self._callbacks.get(hotkey_id)
                        if callback:
                            try:
                                # Run callback directly (not in thread) for faster response
                                callback()
                            except Exception as exc:
                                log.exception("Hotkey callback error: %s", exc)
                        else:
                            log.warning("No callback for hotkey id=%d", hotkey_id)

            # Unregister hotkeys
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)
            log.info("Unregistered %d hotkey(s)", len(registered))

        except Exception as exc:
            log.exception("Hotkey message loop error: %s", exc)
        finally:
            self._thread_id = 0

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if self._running:
            self._running = False
            # Post WM_QUIT to break the message loop
            if self._thread_id:
                user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            if self._thread:
                self._thread.join(timeout=2)
            self._thread = None
            log.debug("Hotkey listener stopped")

    def is_running(self) -> bool:
        """Check if the hotkey listener is active."""
        return self._running and self._thread is not None and self._thread.is_alive()
