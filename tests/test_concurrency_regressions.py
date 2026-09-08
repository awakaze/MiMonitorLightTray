"""Regression tests for high-impact concurrency defects found in v1.5.1.

These tests deliberately avoid importing the Windows-only modules
(``single_instance``, ``monitor_sleep_listener``) on Linux, and exercise the
*iteration pattern* rather than the full FlyoutWindow / App objects for the
dict-mutation tests — the pattern is what causes the bug, not the Tk setup.

Bug 1 — ``RuntimeError: dictionary changed size during iteration``:
    ``App._on_model_resolved`` does ``lights[new] = lights.pop(old)`` while
    callers iterate ``self._lights.items()`` / ``.values()`` live views.
    Fix: every call site now uses ``list()`` snapshot iterators.

Bug 2 — double ``_on_monitor_sleep`` after listener restart:
    ``MonitorSleepListener.stop()`` posted ``WM_CLOSE`` but returned without
    joining the old window thread, so restarting the listener created two
    live subscriber windows for ~50ms → duplicate callbacks → pre-sleep
    state overwritten → lamp not restored on wake.
    Fix: ``stop()`` joins the old thread with a 3s timeout.
"""

from __future__ import annotations

import ctypes
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Sentinel for attribute-installation teardown in _shim_ctypes_windows.
_SENTINEL = object()


# ── Bug 1: dict mutation during iteration ─────────────────────────────────────
#
# Tests below do NOT import FlyoutWindow — they reproduce the exact iteration
# patterns used in flyout.py and __main__.py and verify that using list()
# snapshots makes them immune to concurrent dict re-keying. They also run the
# UNFIXED pattern (live view) against a control group to prove the test
# harness itself reproduces the bug when the snapshot is absent.


def _make_lights(n: int = 15) -> dict[str, SimpleNamespace]:
    """Return a dict of id → light_obj with .state.is_on / .state.reachable."""
    lights: dict[str, SimpleNamespace] = {}
    for i in range(n):
        lights[f"temp_id_{i:04d}"] = SimpleNamespace(
            state=SimpleNamespace(is_on=(i % 2 == 0), reachable=True)
        )
    return lights


def _hammer_rekey(
    lights: dict, stop: threading.Event, extra: dict | None = None,
    per_cycle_sleep: float = 0.0,
) -> threading.Thread:
    """Spawn a daemon that continuously re-keys one dict entry."""
    keys_orig = list(lights.keys())

    def run():
        i = 0
        while not stop.is_set():
            old_key = keys_orig[i % len(keys_orig)]
            # If old_key has already been renamed, skip (we rename each key
            # once per cycle, but that's fine — the next iteration uses
            # another original key).
            if old_key in lights:
                new_key = f"resolved_{i:08d}"
                lights[new_key] = lights.pop(old_key)
                if extra is not None and old_key in extra:
                    extra[new_key] = extra.pop(old_key)
                # Refresh the known-keys list so we also "re-rename" keys
                # that were already moved — keeps dict churn high.
                keys_orig[i % len(keys_orig)] = new_key
            i += 1
            if per_cycle_sleep:
                time.sleep(per_cycle_sleep)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_fixed_pattern_any_on_list_snapshot_no_crash():
    """Matches flyout._any_on: any(l.state.is_on for l in list(dict.values()))."""
    lights = _make_lights(20)
    stop = threading.Event()
    errors: list[RuntimeError] = []

    hammer = _hammer_rekey(lights, stop)

    def reader():
        try:
            for _ in range(2500):
                # This is the FIXED pattern — list() snapshot.
                result = any(
                    l.state.is_on for l in list(lights.values())
                )
                assert isinstance(result, bool)
        except RuntimeError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)
    stop.set()
    hammer.join(timeout=2.0)

    assert not errors, (
        f"list()-snapshot pattern unexpectedly raised RuntimeError: "
        f"{[str(e) for e in errors]}"
    )


def test_fixed_pattern_items_snapshot_no_crash():
    """Matches flyout._bg_refresh_all / _open / _on_toggle_all:
    for k, v in list(dict.items())."""
    lights = _make_lights(15)
    sections = {k: True for k in lights}
    stop = threading.Event()
    errors: list[RuntimeError] = []

    hammer = _hammer_rekey(lights, stop, extra=sections, per_cycle_sleep=0.0005)

    def caller():
        for _ in range(300):
            seen = 0
            try:
                # FIXED pattern — list(items()) snapshot.
                for dev_id, light in list(lights.items()):
                    if dev_id in sections:
                        seen += 1
            except RuntimeError as exc:
                errors.append(exc)

    threads = [threading.Thread(target=caller, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)
    stop.set()
    hammer.join(timeout=2.0)

    assert not errors, (
        f"list(items)-snapshot pattern unexpectedly raised RuntimeError: "
        f"{[str(e) for e in errors]}"
    )


def test_control_live_items_view_reproduces_bug():
    """Positive control: WITHOUT the list() fix, live .items() view DOES crash
    under the same concurrent re-keying scenario. This proves the test
    strategy genuinely reproduces the CPython iterator version-tag check."""
    lights = _make_lights(15)
    sections = {k: True for k in lights}
    stop = threading.Event()
    errors: list[RuntimeError] = []

    hammer = _hammer_rekey(lights, stop, extra=sections, per_cycle_sleep=0.0002)

    def caller():
        for _ in range(500):
            try:
                for dev_id, light in lights.items():  # ← LIVE VIEW (unfixed)
                    if dev_id not in sections:
                        continue
                    # Touch attributes on every yield to keep the iterator
                    # active across the hammer's mutation cycles.
                    _ = light.state.is_on
            except RuntimeError as exc:
                errors.append(exc)
                # We just need at least one — stop hammering to save time.
                stop.set()
                return

    t = threading.Thread(target=caller, daemon=True)
    t.start()
    # Give it plenty of time to trip the iterator check.
    t.join(timeout=8.0)
    if not stop.is_set():
        stop.set()
    hammer.join(timeout=2.0)

    # CPython's dict iterator is inherently racy here; the bug manifests
    # probabilistically. With 15 keys × 500 iterations × high-churn hammer we
    # essentially always trip it on multi-core Linux. If we don't, that's a
    # skipped test (NOT a "the bug doesn't exist" claim).
    if not errors:
        pytest.skip(
            "Positive control: live dict-view iteration didn't raise this "
            "run (probabilistic race); test strategy is valid but this "
            "execution didn't sample the bad interleaving."
        )
    assert any("changed size" in str(e) or "dictionary" in str(e).lower()
               for e in errors), (
        f"Expected RuntimeError about dict mutation, got: {errors!r}"
    )


# ── Bug 2: MonitorSleepListener.stop() thread join ───────────────────────────
#
# On Linux, ctypes.WINFUNCTYPE / WinDLL don't exist. Shim them in a
# pytest fixture before attempting the import so the module loads cleanly;
# we never call into real Win32 code anyway (tests use a subclass that
# overrides the message-pump thread entirely).


@pytest.fixture
def _shim_ctypes_windows(request):
    """Install no-op stand-ins for Windows-only ctypes symbols on Linux.

    ``monitor_sleep_listener.py`` uses WINFUNCTYPE and WinDLL at module scope
    (top-level class definitions). On non-Windows CPython these attributes
    simply don't exist. Fake them out with callable placeholders so the
    module imports — our tests never exercise the real Win32 paths.
    """
    import ctypes as _ctypes

    # NOTE: monkeypatch.setattr raises if the attribute doesn't already
    # exist on the target object. For the Windows-only ctypes attributes on
    # Linux, we therefore use plain setattr + addfinalizer teardown.
    restored: list[tuple[type | object, str, object]] = []

    def _install(name: str, value: object) -> None:
        existed = hasattr(_ctypes, name)
        if existed:
            restored.append((_ctypes, name, getattr(_ctypes, name)))
        else:
            # Sentinel — delete on teardown.
            restored.append((_ctypes, name, _SENTINEL))
        setattr(_ctypes, name, value)

    if not hasattr(_ctypes, "WINFUNCTYPE"):
        _install("WINFUNCTYPE", _ctypes.CFUNCTYPE)

    if not hasattr(_ctypes, "WinDLL"):
        class _FakeWinDLL:
            def __init__(self, *a, **kw):
                self.__dict__["_attrs"] = {}

            def __getattr__(self, name):
                stub = self._attrs.get(name)
                if stub is None:
                    def _stub(*a, **kw):
                        return 0
                    stub = _stub
                    self._attrs[name] = stub
                return stub

            def __setattr__(self, k, v):
                # Allow restype/argtypes assignment in _configure_user32.
                # No-op: our code never calls the resulting functions.
                self.__dict__.setdefault("_attrs", {})[k] = v

        _install("WinDLL", _FakeWinDLL)

    if not hasattr(_ctypes, "c_ssize_t"):
        _install("c_ssize_t", _ctypes.c_long)

    def _teardown():
        for mod, name, prev in reversed(restored):
            if prev is _SENTINEL:
                try:
                    delattr(mod, name)
                except AttributeError:
                    pass
            else:
                setattr(mod, name, prev)

    request.addfinalizer(_teardown)
    yield


def test_stop_joins_window_thread_before_returning(_shim_ctypes_windows):
    """After stop() returns, the listener window thread must be dead.

    This is the liveness invariant that prevents overlapping listeners after
    ``App._restart_power_listener``. We subclass MonitorSleepListener so the
    Win32 message-pump is replaced with a controllable stub that sleeps for
    60ms after ``stop()`` unblocks it (mirroring the time between WM_CLOSE
    delivery and the window-class unregistration cleanup in the finally
    block of the real implementation).
    """
    import itertools

    # Import must happen AFTER the ctypes shim is installed by the fixture.
    from mi_monitor_light_tray.monitor_sleep_listener import MonitorSleepListener

    # Keep the teardown window large (500ms) so scheduling jitter and
    # time.sleep() accuracy relative to it stay negligible. A 60ms window with
    # a 10ms tolerance was flaky on Python 3.12 CI (sleep under-ran slightly →
    # stop() returned 47ms vs the ≥50ms assert).
    teardown_sleep = 0.5  # 500ms teardown window simulated in _pump.
    unblock = threading.Event()

    class _Stub(MonitorSleepListener):
        def __init__(self):
            # Bypass parent __init__: avoid all Win32 class registration.
            self._on_monitor_sleep = None
            self._on_monitor_wake = None
            self._on_system_suspend = None
            self._on_system_resume = None
            self._ready = threading.Event()
            self._stop_event = threading.Event()
            self._display_on = True
            self._power_notify_handle = None
            self._suspend_notify_handle = None
            self._hwnd = "fake-hwnd"       # truthy → stop() posts WM_CLOSE
            self._wndproc_ref = None
            self._class_name = f"StubListener_{next(itertools.count(1))}"
            self._window_thread = threading.Thread(
                target=self._pump, daemon=True,
            )

        def start(self):
            self._window_thread.start()
            self._ready.set()

        def _pump(self):
            # Wait until stop() is called…
            unblock.wait(timeout=5.0)
            # …then simulate the 60ms between WM_CLOSE being processed and
            # the finally-block actually releasing resources.
            time.sleep(teardown_sleep)
            self._hwnd = None

    stub = _Stub()
    stub.start()

    # Control: before stop() the thread is definitely alive and post-WM_CLOSE
    # teardown has NOT begun.
    assert stub._window_thread.is_alive()

    t0 = time.monotonic()
    # Unblock the pump at the same moment we call stop — otherwise stop()
    # would hit the 3s timeout (pump never got the signal).
    unblock.set()
    stub.stop()
    elapsed = time.monotonic() - t0

    # stop() must have blocked until the teardown basically finished. Allow up
    # to 30% jitter around the simulated window; is_alive below is the hard
    # guarantee that the window thread fully exited on return.
    assert elapsed >= teardown_sleep * 0.7, (
        f"stop() returned after {elapsed*1000:.0f}ms. Thread teardown takes "
        f"{teardown_sleep*1000:.0f}ms, so stop() cannot possibly have waited "
        f"for the window thread to exit — old listener is still alive and "
        f"would race with a newly-started one."
    )
    # And the thread must actually be dead on return.
    assert not stub._window_thread.is_alive(), (
        "stop() returned but window thread is still alive — restart would "
        "produce overlapping WM_POWERBROADCAST subscribers."
    )


def test_stop_bounded_timeout_on_hung_pump(_shim_ctypes_windows):
    """If the message pump wedges (WM_CLOSE is never processed), stop() MUST
    return after its 3-second safety cap — we can never deadlock the caller.
    """
    import itertools
    from mi_monitor_light_tray.monitor_sleep_listener import MonitorSleepListener

    never = threading.Event()  # never set → thread never exits

    class _Hanging(MonitorSleepListener):
        def __init__(self):
            self._on_monitor_sleep = None
            self._on_monitor_wake = None
            self._on_system_suspend = None
            self._on_system_resume = None
            self._ready = threading.Event()
            self._stop_event = threading.Event()
            self._display_on = True
            self._power_notify_handle = None
            self._suspend_notify_handle = None
            self._hwnd = "fake-hwnd"
            self._wndproc_ref = None
            self._class_name = f"HangingListener_{next(itertools.count(1))}"
            self._window_thread = threading.Thread(
                target=lambda: never.wait(timeout=30.0), daemon=True,
            )

        def start(self):
            self._window_thread.start()
            self._ready.set()

    h = _Hanging()
    h.start()

    t0 = time.monotonic()
    h.stop()
    elapsed = time.monotonic() - t0

    # Safety cap is 3.0s. We expect ~3.0; fail if it's > 5s (meaning the cap
    # wasn't respected and code hangs on a "bad timing" system) or < 2.5s
    # (meaning the thread actually exited — test setup error).
    assert 2.5 <= elapsed <= 5.0, (
        f"stop() took {elapsed:.2f}s with a wedged message pump. Expected "
        f"≈3.0s (the join timeout cap). If this is near 30s the safety cap "
        f"was not applied and stop() is vulnerable to caller deadlock."
    )
