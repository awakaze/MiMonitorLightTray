"""Localization regressions without network, lamps, or real user config writes."""

from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import re
from string import Formatter
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mi_monitor_light_tray import i18n
from mi_monitor_light_tray.config import AppConfig, DeviceConfig


PACKAGE = Path(i18n.__file__).parent
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


@pytest.fixture(autouse=True)
def restore_language():
    """Language selection is global; leave unrelated tests in their original state."""
    previous = i18n.get_language()
    yield
    i18n.set_language(previous)


def test_every_literal_ui_translation_has_both_catalog_entries():
    missing = []
    for path in PACKAGE.rglob("*.py"):
        if path.name == "i18n.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in {"t", "menu_text"} or not node.args:
                continue
            source = node.args[0]
            if isinstance(source, ast.Constant) and isinstance(source.value, str):
                if source.value not in i18n.CATALOG:
                    missing.append(f"{path.name}:{node.lineno}: {source.value!r}")
    assert not missing, "Untranslated UI strings:\n" + "\n".join(missing)


def test_english_and_russian_catalogs_are_nonempty_and_have_no_chinese():
    problems = []
    for source, variants in i18n.CATALOG.items():
        assert len(variants) == 2, source
        for code, value in zip(("en", "ru"), variants):
            if not isinstance(value, str) or not value.strip() or CJK.search(value):
                problems.append((code, source, value))
    assert not problems


def _placeholders(text):
    return Counter(
        (field, conversion, spec)
        for _literal, field, spec, conversion in Formatter().parse(text)
        if field is not None
    )


def test_translations_preserve_format_fields_and_format_safely():
    problems = []
    for source, variants in i18n.CATALOG.items():
        expected = _placeholders(source)
        for code, translated in zip(("en", "ru"), variants):
            if _placeholders(translated) != expected:
                problems.append((code, source, translated))
            # All current UI templates accept positional strings such as names,
            # versions and network errors. Exercise the real formatting path.
            fields = [int(field) for field, _conversion, _spec in expected if field.isdecimal()]
            if fields:
                i18n.set_language(code)
                arguments = [f"value-{index}" for index in range(max(fields) + 1)]
                rendered = i18n.t(source, *arguments)
                for index in fields:
                    assert arguments[index] in rendered, (code, source)
    assert not problems


@pytest.mark.parametrize("language, expected", [("en", "Save"), ("ru", "Сохранить"), ("zh", "保存")])
def test_explicit_language_translation(language, expected):
    assert i18n.set_language(language) == language
    assert i18n.get_language() == language
    assert i18n.t("保存") == expected


def test_translating_device_details_preserves_dynamic_data():
    i18n.set_language("ru")
    assert i18n.t("已自动填充设备信息：\n\n名称：{0}\nIP：{1}\n型号：{2}",
                  "Моя лампа", "192.0.2.10", "xiaomi.light.bar2") == (
        "Данные устройства заполнены:\n\nНазвание: Моя лампа\nIP: 192.0.2.10\nМодель: xiaomi.light.bar2"
    )


@pytest.mark.parametrize("language", ["en", "ru", "zh"])
def test_unknown_message_falls_back_without_losing_details(language):
    i18n.set_language(language)
    assert i18n.t("Custom device: {0}", "Office") == "Custom device: Office"
    assert i18n.t("Vendor error 123") == "Vendor error 123"


def test_chinese_keeps_original_strings_and_translates_shared_english_keys():
    i18n.set_language("zh")
    assert i18n.t("设备「{0}」已保存！\n\n是否继续添加更多设备？", "Desk") == (
        "设备「Desk」已保存！\n\n是否继续添加更多设备？"
    )
    assert i18n.t("Yes") == "是"
    assert i18n.t("System default") == "跟随系统"


@pytest.mark.parametrize("invalid", ["de", "", None, "RU", "ru_RU"])
def test_unknown_language_falls_back_to_english(invalid):
    assert i18n.set_language(invalid) == "en"
    assert i18n.t("保存") == "Save"


def test_auto_language_is_resolved_when_selected(monkeypatch):
    resolve = Mock(return_value="ru")
    monkeypatch.setattr(i18n, "system_language", resolve)
    assert i18n.set_language("auto") == "ru"
    assert i18n.t("保存") == "Сохранить"
    resolve.assert_called_once_with()
    resolve.reset_mock()
    i18n.set_language("en")
    resolve.assert_not_called()


@pytest.mark.parametrize("language_id, expected", [
    (0x0409, "en"), (0x0419, "ru"), (0x0804, "zh"), (0x0404, "zh"),
    (0x040C, "en"), (0xFFFF, "en"),
])
def test_system_language_uses_windows_ui_language(monkeypatch, language_id, expected):
    monkeypatch.setattr(i18n.ctypes, "windll", SimpleNamespace(
        kernel32=SimpleNamespace(GetUserDefaultUILanguage=lambda: language_id)
    ), raising=False)
    # Windows formatting locale may differ from the display language.
    fallback = Mock(return_value=("de_DE", "UTF-8"))
    monkeypatch.setattr(i18n.locale, "getlocale", fallback)
    assert i18n.system_language() == expected
    fallback.assert_not_called()


@pytest.mark.parametrize("locale_name, expected", [
    ("ru_RU", "ru"), ("en-US", "en"), ("zh_CN", "zh"), ("de_DE", "en"), (None, "en"),
])
def test_system_language_falls_back_when_windows_api_is_unavailable(monkeypatch, locale_name, expected):
    monkeypatch.delattr(i18n.ctypes, "windll", raising=False)
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: (locale_name, "UTF-8"))
    assert i18n.system_language() == expected


@pytest.mark.parametrize("language", ["auto", "en", "ru", "zh"])
def test_language_roundtrip_keeps_existing_device_settings(tmp_path, language):
    path = tmp_path / "config.json"
    original = AppConfig(language=language, devices=[DeviceConfig(
        id="test-light", ip="192.0.2.10", token="a" * 32,
        name="Моя лампа", model="xiaomi.light.bar2", brightness_up="ctrl+alt+up",
        power_off_at_exit=True,
    )])
    original.save(path)
    assert json.loads(path.read_text(encoding="utf-8"))["language"] == language
    assert AppConfig.load(path) == original
    assert not path.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("devices_key", ["device", "devices"])
def test_config_without_language_preserves_legacy_devices_and_uses_auto(tmp_path, devices_key):
    path = tmp_path / "legacy.json"
    device = {"ip": "192.0.2.10", "token": "a" * 32, "name": "Old light"}
    payload = {devices_key: device if devices_key == "device" else [device]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    config = AppConfig.load(path)
    assert config.language == "auto"
    assert len(config.devices) == 1
    assert config.devices[0].name == "Old light"
    assert config.devices[0].is_complete()


@pytest.mark.parametrize("invalid", ["de", "", None, 42, ["ru"], {"code": "ru"}])
def test_invalid_saved_language_uses_auto(tmp_path, invalid):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"language": invalid}), encoding="utf-8")
    assert AppConfig.load(path).language == "auto"


def test_dynamic_menu_caption_follows_current_language():
    caption = i18n.menu_text("设置")
    for code, expected in [("en", "Settings"), ("ru", "Настройки"), ("zh", "设置")]:
        i18n.set_language(code)
        assert caption(None) == expected


@pytest.mark.skipif(sys.platform != "win32", reason="Tray backend requires Windows")
def test_tray_language_selection_updates_captions_without_replacing_running_icon(monkeypatch):
    from mi_monitor_light_tray import tray

    fake_icon = Mock()
    def create_icon(*_args, **kwargs):
        fake_icon.menu = kwargs["menu"]
        return fake_icon

    monkeypatch.setattr(tray.pystray, "Icon", create_icon)
    monkeypatch.setattr(tray, "make_tray_icon", lambda *_args, **_kwargs: None)
    config = AppConfig(language="en")
    def select_language(code):
        config.language = code
        i18n.set_language(code)

    callbacks = {
        "on_left_click": Mock(), "on_open_settings": Mock(), "on_exit": Mock(),
    }
    for setting in ("power_on_at_startup", "power_off_at_exit", "power_off_on_monitor_sleep",
                    "power_off_on_system_suspend", "power_on_on_system_resume"):
        callbacks[f"get_{setting}"] = lambda: False
        callbacks[f"on_toggle_{setting}"] = Mock()
    i18n.set_language("en")
    controller = tray.TrayController(title="Test", config=config,
                                     on_language_changed=select_language, **callbacks)
    menu = tuple(fake_icon.menu.items)
    settings = next(item for item in menu if item.text == "Settings")
    languages = next(item.submenu for item in menu if item.submenu is not None)
    language_items = tuple(languages.items)
    assert len(language_items) == 4
    assert [item.checked for item in language_items] == [False, True, False, False]
    russian = next(item for item in language_items if item.text == "Русский")
    russian(fake_icon)
    controller.refresh_language()
    assert config.language == "ru"
    assert settings.text == "Настройки"
    assert language_items[0].text == "Как в Windows"
    assert [item.checked for item in language_items] == [False, False, True, False]
    assert controller._icon is fake_icon
    fake_icon.update_menu.assert_called_once_with()
