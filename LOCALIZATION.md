# Localization

The interface supports Chinese (`zh`), English (`en`) and Russian (`ru`). Users choose a language from the tray menu or **Settings → General settings**. `auto` uses the Windows display language, falling back to English for unsupported languages. `--language auto|en|ru|zh` selects the startup language without immediately writing the config.

The optional top-level `language` field in `config.json` stores the preference. Older files default to `auto`. Tray selections apply immediately and persist. Settings provides a preview: Save keeps the choice; Cancel restores the previous preference. A language selected from the tray while Settings is open becomes the new Cancel baseline.

## Catalog and stable keys

[`mi_monitor_light_tray/i18n.py`](mi_monitor_light_tray/i18n.py) holds the catalog, language detection, translation functions and display font. Translations are Python data, so source installs and PyInstaller bundles use the same catalog without resolving external files at runtime.

`CATALOG` maps each stable source string to `(English, Russian)`. Most keys are the original Chinese UI text; Chinese renders those source strings directly. `ZH_EXTRA` provides Chinese values for shared keys such as `Language` and `Yes`.

Keep existing keys stable when changing a translation. A copy edit to an English or Russian caption belongs in its catalog value. If the meaning of an existing message changes, introduce or update its source key and every language together. Unknown keys fall back to the source string, so missing catalog entries should be caught by tests rather than accepted as an English or Russian UI fallback.

```python
from .i18n import menu_text, t

label.configure(text=t("显示名称"))
status.configure(text=t("型号: {0}", device.model))
# pystray reevaluates callable captions when its menu is refreshed.
settings_item = pystray.MenuItem(menu_text("设置"), on_open_settings)
```

Use literal keys at call sites so the catalog coverage test can discover them. Do not build translation keys with f-strings or concatenate translated fragments. Translate the complete sentence, then insert dynamic values.

## Placeholders and user data

- Preserve every format field, including its index, conversion and format specification: `{0}`, `{1}`, `{0!r}`, etc. Translations may reorder fields but must not add or remove occurrences.
- Pass values separately to `t(source, *arguments)`; do not format the source before looking it up. Escape literal braces as `{{` and `}}` when a formatted message needs them.
- Keep deliberate newlines where they help the layout, and check longer translations in the actual window.
- Translate the surrounding message while leaving user device names, IP addresses, tokens, model IDs, firmware versions and external diagnostic details intact.
- Use the localized helpers in [`dialogs.py`](mi_monitor_light_tray/dialogs.py) for confirmation buttons, so Yes/No/OK follows the app language independently of the Windows language.

## Applying a language change

`set_language()` resolves the requested preference into the active `en`, `ru` or `zh` language. `get_language()` returns that resolved language; retain `auto` in the configuration when the user chooses System default.

Tray callbacks dispatch through the main Tk event loop. Refresh the existing tray menu and visible UI rather than starting another tray icon. Rebuilding device controls must retain cached state and must not reconnect to lamps or send power commands. Settings preview and Cancel must stay consistent with language changes made through the tray.

When adding UI, cover its title, labels, menus, tooltips, status text, validation, confirmations and error wrappers. Allow space for translated captions: use flexible columns, wrapping or scrolling instead of clipping text into the original Chinese dimensions. Keep language names recognizable: English, Русский, 中文.

## Validation

Install the development dependencies and run the localization tests, then the full suite:

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q tests/test_i18n.py tests/test_localized_ui.py
python -m pytest -q
```

[`tests/test_i18n.py`](tests/test_i18n.py) checks literal-key coverage, nonempty translations, preserved placeholders, Windows display-language detection, fallback behavior, configuration compatibility and dynamic menu captions. [`tests/test_localized_ui.py`](tests/test_localized_ui.py) exercises translated windows, dialogs and language changes using dummy devices. Tk-dependent checks skip when Tk cannot initialize; a passing headless run does not replace visual inspection.

Manually switch through all three languages and System default. Check the first-run window, device list and editor, cloud sign-in and device selection, flyout, desktop widget, confirmation buttons, update messages and settings Save/Cancel. Check long device names and Windows display scaling. Verify that switching language alone sends no commands to lamps.

For a packaged Windows check:

```powershell
python -m pip install -e ".[build]"
python scripts/build_exe.py
.\dist\MiMonitorLightTray.exe --language ru
```

Exit any running instance first. Repeat with `en` and `zh`, and verify the reported version comes from the package metadata. No separate translation files or language-specific launch scripts are required.
