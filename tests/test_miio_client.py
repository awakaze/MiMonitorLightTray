"""Unit tests for the miio wrapper — focus on error capture and listener wiring.

These tests stub out python-miio's ``Yeelight`` / ``MiotDevice`` so they run
offline. The point is to verify our wrapper's contract: errors should be
captured into state, listeners should fire, no DeviceException should escape,
and the right backend should be selected per model id.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from miio.exceptions import DeviceException

from mi_monitor_light_tray import miio_client


LEGACY_MODEL = "yeelink.light.lamp1"  # legacy backend, 2700-6500K (matches class defaults)
MIOT_MODEL = "yeelink.light.lamp22"


@pytest.fixture
def fake_yeelight(monkeypatch):
    """Replace miio.Yeelight in the wrapper with a MagicMock factory."""
    factory = MagicMock()
    monkeypatch.setattr(miio_client, "Yeelight", factory)
    return factory


@pytest.fixture
def fake_miot(monkeypatch):
    """Replace miio.MiotDevice in the wrapper with a MagicMock factory."""
    factory = MagicMock()
    monkeypatch.setattr(miio_client, "MiotDevice", factory)
    return factory


def _make_legacy(fake_yeelight, **device_methods):
    """Construct a wrapper forced onto the legacy backend (model=lamp4)."""
    device = MagicMock()
    for name, value in device_methods.items():
        method = (
            MagicMock(side_effect=value)
            if isinstance(value, Exception)
            else MagicMock(return_value=value)
        )
        setattr(device, name, method)
    fake_yeelight.return_value = device
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model=LEGACY_MODEL
    )
    return light, device


def _make_miot(fake_miot, **device_methods):
    """Construct a wrapper forced onto the MIoT backend (model=lamp22)."""
    device = MagicMock()
    for name, value in device_methods.items():
        method = (
            MagicMock(side_effect=value)
            if isinstance(value, Exception)
            else MagicMock(return_value=value)
        )
        setattr(device, name, method)
    fake_miot.return_value = device
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model=MIOT_MODEL
    )
    return light, device


# ── legacy backend ────────────────────────────────────────────────────────────


def test_set_brightness_captures_device_exception(fake_yeelight):
    light, dev = _make_legacy(fake_yeelight, set_brightness=DeviceException("boom"))
    result = light.set_brightness(50)
    assert result == 50  # clamped value still returned
    assert light.state.reachable is False
    assert "boom" in light.state.error
    dev.set_brightness.assert_called_once_with(50)


def test_set_brightness_clamps(fake_yeelight):
    light, dev = _make_legacy(fake_yeelight, set_brightness=None)
    assert light.set_brightness(999) == 100
    assert light.set_brightness(-5) == 1
    assert light.state.brightness == 1
    assert light.state.reachable is True


def test_set_color_temp_clamps_and_captures(fake_yeelight):
    light, dev = _make_legacy(fake_yeelight, set_color_temp=DeviceException("nope"))
    assert light.set_color_temp(10000) == light.color_temp_max
    assert light.set_color_temp(0) == light.color_temp_min
    assert light.state.error == "nope"
    assert light.state.reachable is False


def test_listener_is_called_on_state_change(fake_yeelight):
    light, _ = _make_legacy(fake_yeelight, set_brightness=None)
    seen = []
    light.set_listener(lambda s: seen.append((s.brightness, s.reachable)))
    light.set_brightness(42)
    light.set_brightness(80)
    assert seen == [(42, True), (80, True)]


def test_toggle_captures_exception(fake_yeelight):
    light, _ = _make_legacy(fake_yeelight, toggle=DeviceException("offline"))
    # Should not raise — should just record the error.
    result = light.toggle()
    assert isinstance(result, bool)
    assert light.state.reachable is False
    assert light.state.error == "offline"


def test_refresh_offline_returns_state(fake_yeelight):
    light, _ = _make_legacy(fake_yeelight, status=DeviceException("noop"))
    state = light.refresh()
    assert state.reachable is False
    assert state.error == "noop"


def test_lock_serialises_calls(fake_yeelight):
    """Two threads calling set_brightness should not interleave inside the lock."""
    light, dev = _make_legacy(fake_yeelight, set_brightness=None)

    inside = []
    barrier = threading.Event()

    def slow(_value):
        inside.append("enter")
        barrier.wait(timeout=0.1)
        inside.append("exit")

    dev.set_brightness = MagicMock(side_effect=slow)

    t1 = threading.Thread(target=light.set_brightness, args=(30,))
    t2 = threading.Thread(target=light.set_brightness, args=(60,))
    t1.start()
    t2.start()
    barrier.set()
    t1.join()
    t2.join()

    # Each call must be fully bracketed (enter, exit) before the next starts.
    assert inside == ["enter", "exit", "enter", "exit"]


def test_debouncer_coalesces_rapid_calls():
    d = miio_client.Debouncer(delay=0.05)
    calls = []
    for v in range(10):
        d.call(calls.append, v)
    # The timer fires after the delay; wait it out.
    import time
    time.sleep(0.15)
    assert calls == [9]
    d.cancel()


def test_ct_range_for_known_models():
    # lamp22 — bundled in python-miio's specs.yaml (2700-6500)
    assert miio_client.MiMonitorLight.ct_range_for("yeelink.light.lamp22") == (2700, 6500)
    # lamp4 — bundled in python-miio's specs.yaml (2600-5000)
    assert miio_client.MiMonitorLight.ct_range_for("yeelink.light.lamp4") == (2600, 5000)
    # lamp2 — NOT in python-miio's specs.yaml; only via our override
    assert miio_client.MiMonitorLight.ct_range_for("yeelink.light.lamp2") == (2500, 4800)


def test_ct_range_resolves_through_spec_helper():
    """Models in python-miio's bundled specs.yaml but not in our override table."""
    # ceiling1 is in python-miio's specs.yaml as (2700, 6500); not in our override
    assert "yeelink.light.ceiling1" not in miio_client.MiMonitorLight.MODEL_CT_RANGES
    assert miio_client.MiMonitorLight.ct_range_for("yeelink.light.ceiling1") == (2700, 6500)
    # bslamp1 is in specs.yaml as (1700, 6500) — a value we'd never reach via our defaults
    assert miio_client.MiMonitorLight.ct_range_for("yeelink.light.bslamp1") == (1700, 6500)


def test_ct_range_for_unknown_falls_back_to_defaults():
    cls = miio_client.MiMonitorLight
    assert cls.ct_range_for("") == (cls.COLOR_TEMP_MIN, cls.COLOR_TEMP_MAX)
    assert cls.ct_range_for("yeelink.light.something-new") == (
        cls.COLOR_TEMP_MIN, cls.COLOR_TEMP_MAX
    )


def test_set_color_temp_clamps_to_instance_range(fake_yeelight):
    # Fake device with info() that reports the same model we constructed with,
    # so _record_success doesn't try to "re-resolve" to a different range.
    device = MagicMock()
    device.set_color_temp = MagicMock(return_value=None)
    device.info = MagicMock(return_value=MagicMock(model="yeelink.light.lamp4"))
    fake_yeelight.return_value = device
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model="yeelink.light.lamp4"
    )
    assert light.color_temp_min == 2600
    assert light.color_temp_max == 5000
    assert light.set_color_temp(9000) == 5000
    assert light.set_color_temp(1000) == 2600


# ── backend dispatch ──────────────────────────────────────────────────────────


def test_default_model_uses_legacy_backend(fake_yeelight, fake_miot):
    """Constructing without an explicit model falls back to legacy backend."""
    fake_yeelight.return_value = MagicMock()
    light = miio_client.MiMonitorLight(ip="1.2.3.4", token="t" * 32)
    assert isinstance(light._device, miio_client._LegacyBackend)
    assert light.model == ""
    assert light.color_temp_min == 2700
    assert light.color_temp_max == 6500
    # The MIoT factory must not have been called.
    fake_miot.assert_not_called()


def test_legacy_model_uses_legacy_backend(fake_yeelight, fake_miot):
    fake_yeelight.return_value = MagicMock()
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model="yeelink.light.lamp4"
    )
    assert isinstance(light._device, miio_client._LegacyBackend)
    fake_miot.assert_not_called()


def test_unknown_model_falls_back_to_legacy(fake_yeelight, fake_miot):
    fake_yeelight.return_value = MagicMock()
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model="yeelink.light.bogus"
    )
    assert isinstance(light._device, miio_client._LegacyBackend)
    fake_miot.assert_not_called()


# ── MIoT backend ──────────────────────────────────────────────────────────────


def test_miot_set_brightness_calls_set_property(fake_miot):
    light, dev = _make_miot(fake_miot, set_property=None)
    light.set_brightness(60)
    dev.set_property.assert_called_with("brightness", 60)
    assert light.state.brightness == 60
    assert light.state.reachable is True


def test_miot_set_color_temp_calls_set_property(fake_miot):
    light, dev = _make_miot(fake_miot, set_property=None)
    light.set_color_temp(4200)
    dev.set_property.assert_called_with("color_temperature", 4200)


def test_miot_on_off_calls_set_property(fake_miot):
    light, dev = _make_miot(fake_miot, set_property=None)
    light.set_power(True)
    dev.set_property.assert_called_with("power", True)
    light.set_power(False)
    dev.set_property.assert_called_with("power", False)


def test_miot_status_aggregates_properties(fake_miot):
    device = MagicMock()
    device.get_properties_for_mapping = MagicMock(return_value=[
        {"did": "power", "siid": 2, "piid": 1, "code": 0, "value": True},
        {"did": "brightness", "siid": 2, "piid": 2, "code": 0, "value": 73},
        {"did": "color_temperature", "siid": 2, "piid": 3, "code": 0, "value": 5100},
    ])
    fake_miot.return_value = device
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model=MIOT_MODEL
    )
    state = light.refresh()
    assert state.is_on is True
    assert state.brightness == 73
    assert state.color_temp == 5100
    assert state.reachable is True


def test_miot_status_drops_failed_properties(fake_miot):
    device = MagicMock()
    device.get_properties_for_mapping = MagicMock(return_value=[
        {"did": "power", "siid": 2, "piid": 1, "code": 0, "value": False},
        # brightness read failed — code != 0, value should be ignored
        {"did": "brightness", "siid": 2, "piid": 2, "code": -1, "value": None},
        {"did": "color_temperature", "siid": 2, "piid": 3, "code": 0, "value": 3000},
    ])
    fake_miot.return_value = device
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model=MIOT_MODEL
    )
    state = light.refresh()
    assert state.is_on is False
    assert state.brightness == 0  # default when value was rejected
    assert state.color_temp == 3000


def test_miot_toggle_reads_then_inverts(fake_miot):
    device = MagicMock()
    device.get_properties_for_mapping = MagicMock(return_value=[
        {"did": "power", "siid": 2, "piid": 1, "code": 0, "value": True},
    ])
    device.set_property = MagicMock(return_value=None)
    fake_miot.return_value = device
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model=MIOT_MODEL
    )
    light.toggle()
    device.set_property.assert_called_with("power", False)


def test_miot_set_brightness_captures_device_exception(fake_miot):
    light, dev = _make_miot(fake_miot, set_property=DeviceException("offline"))
    result = light.set_brightness(40)
    assert result == 40
    assert light.state.reachable is False
    assert "offline" in light.state.error


# ── auto-on (light powers on when the user drags a slider while off) ──────────


def test_set_brightness_auto_powers_on_when_off(fake_yeelight):
    """When state.is_on is False, set_brightness must call on() before set_brightness."""
    device = MagicMock()
    device.on = MagicMock(return_value=None)
    device.set_brightness = MagicMock(return_value=None)
    fake_yeelight.return_value = device
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model=LEGACY_MODEL
    )
    # Cached state defaults to is_on=False
    assert light.state.is_on is False
    light.set_brightness(40)
    device.on.assert_called_once()
    device.set_brightness.assert_called_once_with(40)
    assert light.state.is_on is True


def test_set_brightness_does_not_call_on_when_already_on(fake_yeelight):
    device = MagicMock()
    device.on = MagicMock(return_value=None)
    device.set_brightness = MagicMock(return_value=None)
    fake_yeelight.return_value = device
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model=LEGACY_MODEL
    )
    light.state.is_on = True  # simulate light already on
    light.set_brightness(40)
    device.on.assert_not_called()
    device.set_brightness.assert_called_once_with(40)


def test_set_color_temp_auto_powers_on_when_off(fake_yeelight):
    device = MagicMock()
    device.on = MagicMock(return_value=None)
    device.set_color_temp = MagicMock(return_value=None)
    fake_yeelight.return_value = device
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model=LEGACY_MODEL
    )
    light.set_color_temp(4000)
    device.on.assert_called_once()
    device.set_color_temp.assert_called_once_with(4000)
    assert light.state.is_on is True


def test_miot_set_brightness_auto_powers_on_when_off(fake_miot):
    """Auto-on must also work on the MIoT path — set_property('power', True) first."""
    device = MagicMock()
    device.set_property = MagicMock(return_value=None)
    fake_miot.return_value = device
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32, model=MIOT_MODEL
    )
    light.set_brightness(55)
    # First call must be the power-on, then brightness
    calls = [c.args for c in device.set_property.call_args_list]
    assert ("power", True) in calls
    assert ("brightness", 55) in calls
    assert calls.index(("power", True)) < calls.index(("brightness", 55))


# ── MIoT-for-unknown probe path ───────────────────────────────────────────────


def test_enable_miot_for_unknown_routes_unknown_to_miot(fake_miot, fake_yeelight):
    """With the flag on, an unknown model goes to the MIoT backend (generic mapping)."""
    fake_miot.return_value = MagicMock()
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32,
        model="yeelink.light.bogus",
        enable_miot_for_unknown=True,
    )
    assert isinstance(light._device, miio_client._MiotBackend)
    fake_yeelight.assert_not_called()
    # MiotDevice should have been constructed with the lamp22 generic mapping.
    _, kwargs = fake_miot.call_args
    assert kwargs["mapping"] == miio_client._MIOT_MAPPINGS["yeelink.light.lamp22"]


def test_enable_miot_for_unknown_does_not_override_whitelist(fake_miot, fake_yeelight):
    """Whitelisted models still use their model-specific mapping, not the generic one."""
    fake_miot.return_value = MagicMock()
    miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32,
        model="yeelink.light.lamp22",
        enable_miot_for_unknown=True,
    )
    _, kwargs = fake_miot.call_args
    # Both happen to be the same dict in this case, but verify by identity that
    # the whitelist path is taken.
    assert kwargs["mapping"] is miio_client._MIOT_MAPPINGS["yeelink.light.lamp22"]


def test_flag_off_keeps_legacy_for_unknown(fake_yeelight, fake_miot):
    """Without the flag, unknown models still fall back to legacy (regression guard)."""
    fake_yeelight.return_value = MagicMock()
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32,
        model="yeelink.light.bogus",
        enable_miot_for_unknown=False,
    )
    assert isinstance(light._device, miio_client._LegacyBackend)
    fake_miot.assert_not_called()


# ── user-locked model (config override stays authoritative) ───────────────────


def test_explicit_model_locks_against_info_overwrite(fake_yeelight):
    """User-set model must survive even if info() reports a different one.

    Scenario: user manually wrote ``model=yeelink.light.lamp2`` into config to
    test the narrower 2500-4800K range. The actual device reports back as
    lamp22 (2700-6500K). Honoring info() would silently snap the slider back to
    the wider range and confuse the user — see issue noted in the README.
    """
    device = MagicMock()
    device.set_color_temp = MagicMock(return_value=None)
    # Real device reports a *different* model than what the user configured.
    device.info = MagicMock(return_value=MagicMock(model="yeelink.light.lamp22"))
    fake_yeelight.return_value = device
    range_callbacks: list[tuple[int, int]] = []
    model_callbacks: list[str] = []
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32,
        model="yeelink.light.lamp2",
        on_range_changed=lambda lo, hi: range_callbacks.append((lo, hi)),
        on_model_resolved=lambda m: model_callbacks.append(m),
    )
    # Pre-info() state: range comes from MODEL_CT_RANGES override for lamp2.
    assert light.model == "yeelink.light.lamp2"
    assert (light.color_temp_min, light.color_temp_max) == (2500, 4800)

    # Trigger the success path → info() reports lamp22; we must IGNORE it.
    light.set_color_temp(3000)
    assert light.model == "yeelink.light.lamp2"  # NOT overwritten
    assert (light.color_temp_min, light.color_temp_max) == (2500, 4800)
    # No range change → no callback fired.
    assert range_callbacks == []
    # And critically: the model-resolved callback must NOT fire when locked —
    # otherwise we'd silently persist the wrong value over the user's choice.
    assert model_callbacks == []


def test_blank_model_auto_resolves_and_fires_callback(fake_yeelight, fake_miot, monkeypatch):
    """Blank model in config → info() resolves → on_model_resolved fires once.

    This is the persistence path: caller writes the captured model to config so
    subsequent startups skip the round-trip.
    """
    # Mock Device for the __init__ probe
    fake_device_probe = MagicMock()
    fake_device_probe.info = MagicMock(return_value=MagicMock(model="yeelink.light.lamp4"))
    fake_device_probe._protocol = MagicMock()
    fake_device_probe._protocol._device_id = b'\x01\x02\x03\x04'
    fake_device_class = MagicMock(return_value=fake_device_probe)
    monkeypatch.setattr(miio_client, "Device", fake_device_class)

    device = MagicMock()
    device.set_brightness = MagicMock(return_value=None)
    fake_yeelight.return_value = device

    resolved: list[str] = []
    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32,
        model="",  # blank — let auto-detect take over
        on_model_resolved=lambda m: resolved.append(m),
    )
    # Should have auto-detected lamp4 during __init__
    assert light.model == "yeelink.light.lamp4"
    assert light.device_id == 0x01020304
    # Callback fired during __init__
    assert resolved == ["yeelink.light.lamp4"]
    # Subsequent operations don't re-fire the callback
    light.set_brightness(50)
    assert resolved == ["yeelink.light.lamp4"]


def test_blank_model_still_auto_resolves(fake_yeelight, fake_miot, monkeypatch):
    """Sanity: when the user leaves model="" in config, info() auto-detect still works."""
    # Mock Device for the __init__ probe
    fake_device_probe = MagicMock()
    fake_device_probe.info = MagicMock(return_value=MagicMock(model="yeelink.light.lamp4"))
    fake_device_probe._protocol = MagicMock()
    fake_device_probe._protocol._device_id = b'\x01\x02\x03\x04'
    fake_device_class = MagicMock(return_value=fake_device_probe)
    monkeypatch.setattr(miio_client, "Device", fake_device_class)

    device = MagicMock()
    device.set_brightness = MagicMock(return_value=None)
    fake_yeelight.return_value = device

    light = miio_client.MiMonitorLight(
        ip="1.2.3.4", token="t" * 32,
        model="",  # blank — let auto-detect take over
    )
    # Should have auto-detected lamp4 during __init__
    assert light.model == "yeelink.light.lamp4"
    assert (light.color_temp_min, light.color_temp_max) == (2600, 5000)
