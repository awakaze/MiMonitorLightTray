"""Small, dependency-free UI catalog. Chinese source strings are stable keys.

Translations are Python data so both source installs and PyInstaller bundles
include them without looking for files relative to the working directory.
"""
from __future__ import annotations

import ctypes
import locale
from typing import Callable

LANGUAGES: dict[str, str] = {"auto": "System default", "en": "English", "ru": "Русский", "zh": "中文"}
FONT: str = "Segoe UI"

# source: (English, Russian). Placeholder positions must match the source.
CATALOG: dict[str, tuple[str, str]] = {
    "Language": ("Language", "Язык"),
    "System default": ("System default", "Как в Windows"),
    "Yes": ("Yes", "Да"),
    "No": ("No", "Нет"),
    "OK": ("OK", "ОК"),
    "Open": ("Open", "Открыть"),
    "miio Token": ("miio token", "Ключ miio (Token)"),
    "Mi Monitor Light": ("Mi Monitor Light", "Лампа монитора"),
    "自动获取设备信息": ("Import devices from Xiaomi Home", "Импорт устройств из Xiaomi Home"),
    "请使用米家 App 扫描二维码登录": ("Scan the QR code with Xiaomi Home to sign in", "Для входа отсканируйте QR-код в Xiaomi Home"),
    "正在获取二维码...": ("Loading QR code…", "Загрузка QR-кода…"),
    "取消": ("Cancel", "Отмена"),
    "二维码显示失败，请查看控制台": ("Could not display the QR code", "Не удалось отобразить QR-код"),
    "请使用米家 App 扫描二维码": ("Scan the QR code with Xiaomi Home", "Отсканируйте QR-код в Xiaomi Home"),
    "获取二维码失败": ("Could not load the QR code", "Не удалось загрузить QR-код"),
    "登录成功，正在获取设备列表...": ("Signed in. Loading devices…", "Вход выполнен. Загрузка устройств…"),
    "登录失败: {0}": ("Sign-in failed: {0}", "Ошибка входа: {0}"),
    "获取设备失败: {0}": ("Could not load devices: {0}", "Не удалось загрузить устройства: {0}"),
    "未找到任何设备": ("No devices found", "Устройства не найдены"),
    "返回": ("Back", "Назад"),
    "请选择设备": ("Select a device", "Выберите устройство"),
    "请选择设备（可多选）": ("Select devices (multiple selection allowed)", "Выберите устройства (можно несколько)"),
    "未知型号": ("Unknown model", "Неизвестная модель"),
    "全选": ("Select all", "Выбрать все"),
    "清空": ("Clear selection", "Снять выбор"),
    "确认选择": ("Confirm selection", "Подтвердить выбор"),
    "未选择": ("Nothing selected", "Ничего не выбрано"),
    "请至少选择一个设备": ("Select at least one device", "Выберите хотя бы одно устройство"),
    "请选择一个设备": ("Select one device", "Выберите одно устройство"),
    "错误: {0}": ("Error: {0}", "Ошибка: {0}"),
    "亮度": ("Brightness", "Яркость"),
    "色温": ("Color temperature", "Температура света"),
    "调整亮度": ("Adjust lighting", "Управление светом"),
    "已开灯": ("On", "Включена"),
    "已关灯": ("Off", "Выключена"),
    "离线 — {0}": ("Offline — {0}", "Нет связи — {0}"),
    "添加设备": ("Add device", "Добавить устройство"),
    "设备配置": ("Device settings", "Настройка устройства"),
    "设备信息": ("Device information", "Данные устройства"),
    "显示器挂灯": ("Monitor light", "Лампа монитора"),
    "设备 IP 地址": ("Device IP address", "IP-адрес лампы"),
    "从米家 App 或路由器查看\n如: 192.168.31.73": ("Find it in Xiaomi Home or your router.\nExample: 192.168.31.73", "Посмотрите в Xiaomi Home или в настройках роутера.\nПример: 192.168.31.73"),
    "32 位十六进制字符串\n用 Xiaomi-cloud-tokens-extractor 获取": ("A 32-character hexadecimal key.\nGet it with Xiaomi-cloud-tokens-extractor.", "Ключ из 32 шестнадцатеричных символов.\nМожно получить через Xiaomi-cloud-tokens-extractor."),
    "显示名称": ("Display name", "Название"),
    "设备的显示名称": ("The device name shown in this app", "Название устройства в программе"),
    "型号（可选）": ("Model (optional)", "Модель (необязательно)"),
    "留空自动识别\n如: yeelink.light.lamp22": ("Leave blank to detect automatically.\nExample: yeelink.light.lamp22", "Оставьте пустым для автоопределения.\nПример: yeelink.light.lamp22"),
    "显示 Token": ("Show token", "Показать ключ"),
    "设备选项": ("Device options", "Параметры устройства"),
    "灯跟随软件启动": ("Turn on when app starts", "Включать при запуске программы"),
    "勾选后：程序启动时自动开灯": ("Automatically turn this light on when the app starts.", "Автоматически включать эту лампу при запуске программы."),
    "灯跟随软件关闭": ("Turn off when app exits", "Выключать при выходе из программы"),
    "勾选后：程序退出时自动关灯": ("Automatically turn this light off when the app exits.", "Автоматически выключать эту лампу при выходе из программы."),
    "灯随显示器休眠开关": ("Follow monitor sleep/wake", "Следовать сну и пробуждению монитора"),
    "勾选后：显示器休眠时自动关灯\n显示器唤醒时自动开灯": ("Turn off when the monitor sleeps.\nRestore its previous state when the monitor wakes.", "Выключать при засыпании монитора.\nВосстанавливать прежнее состояние при пробуждении."),
    "系统休眠时关灯": ("Turn off when PC sleeps", "Выключать при засыпании компьютера"),
    "勾选后：系统进入睡眠/休眠时自动关灯": ("Turn off when the PC sleeps or hibernates.", "Выключать, когда компьютер переходит в сон или гибернацию."),
    "系统唤醒时开灯": ("Turn on when PC wakes", "Включать при пробуждении компьютера"),
    "勾选后：系统从睡眠/休眠唤醒时自动开灯": ("Turn on when the PC wakes from sleep or hibernation.", "Включать при выходе компьютера из сна или гибернации."),
    "启用 MIoT（实验性）": ("Use MIoT (experimental)", "Использовать MIoT (экспериментально)"),
    "对未列入 MIoT 白名单的新型 Yeelight 设备，\n尝试用通用 Light service spec 走 MIoT 协议。": ("Try the generic MIoT light protocol for newer\nYeelight devices that are not recognized automatically.", "Попробовать общий протокол MIoT для новых ламп\nYeelight, которые не определяются автоматически."),
    "快捷键设置（仅控制此设备）": ("Hotkeys (this device only)", "Горячие клавиши для этой лампы"),
    "亮度增加": ("Increase brightness", "Увеличить яркость"),
    "亮度降低": ("Decrease brightness", "Уменьшить яркость"),
    "色温增加": ("Cooler light", "Сделать свет холоднее"),
    "色温降低": ("Warmer light", "Сделать свет теплее"),
    "点击输入框并按下想要的快捷键组合\n如: Ctrl+Alt+Up\n右键点击可清空": ("Click the field and press a key combination.\nExample: Ctrl+Alt+Up\nRight-click to clear.", "Нажмите поле, затем сочетание клавиш.\nПример: Ctrl+Alt+Up\nПравая кнопка мыши — очистить."),
    "点击输入框并按下想要的快捷键组合\n如: Ctrl+Alt+Down\n右键点击可清空": ("Click the field and press a key combination.\nExample: Ctrl+Alt+Down\nRight-click to clear.", "Нажмите поле, затем сочетание клавиш.\nПример: Ctrl+Alt+Down\nПравая кнопка мыши — очистить."),
    "点击输入框并按下想要的快捷键组合\n如: Ctrl+Alt+Right\n右键点击可清空": ("Click the field and press a key combination.\nExample: Ctrl+Alt+Right\nRight-click to clear.", "Нажмите поле, затем сочетание клавиш.\nПример: Ctrl+Alt+Right\nПравая кнопка мыши — очистить."),
    "点击输入框并按下想要的快捷键组合\n如: Ctrl+Alt+Left\n右键点击可清空": ("Click the field and press a key combination.\nExample: Ctrl+Alt+Left\nRight-click to clear.", "Нажмите поле, затем сочетание клавиш.\nПример: Ctrl+Alt+Left\nПравая кнопка мыши — очистить."),
    "调整步进": ("Adjustment step", "Шаг изменения"),
    "  (亮度: 1-100, 色温按比例)": ("  (% brightness / temperature range)", "  (% яркости / диапазона температуры)"),
    "测试连接": ("Test connection", "Проверить подключение"),
    "保存": ("Save", "Сохранить"),
    "输入错误": ("Invalid input", "Ошибка ввода"),
    "请填写设备 IP 地址和 32 位 Token": ("Enter the device IP address and a 32-character token.", "Укажите IP-адрес устройства и ключ из 32 символов."),
    "正在测试连接…": ("Testing connection…", "Проверка подключения…"),
    "设备在线\n{0}": ("Device is online\n{0}", "Устройство доступно\n{0}"),
    "连接成功": ("Connected", "Подключение успешно"),
    "连接失败": ("Connection failed", "Ошибка подключения"),
    "无法连接到设备\n{0}": ("Could not connect to the device\n{0}", "Не удалось подключиться к устройству\n{0}"),
    "小米显示器挂灯 — 设置": ("Mi Monitor Light — Settings", "Лампа монитора — Настройки"),
    "设备列表": ("Devices", "Устройства"),
    "云端导入": ("Cloud import", "Импорт из облака"),
    "+ 添加设备": ("+ Add device", "+ Добавить устройство"),
    "全局设置": ("General settings", "Общие настройки"),
    "开机自启动": ("Start with Windows", "Запускать вместе с Windows"),
    "关于": ("About", "О программе"),
    "检查更新": ("Check for updates", "Проверить обновления"),
    "访问 GitHub 主页": ("Open GitHub project", "Открыть проект на GitHub"),
    "暂无设备\n点击「+ 添加设备」或「云端导入」开始配置": ("No devices yet.\nClick “+ Add device” or “Cloud import” to begin.", "Пока нет устройств.\nНажмите «+ Добавить устройство» или «Импорт из облака»."),
    "未命名设备": ("Unnamed device", "Устройство без названия"),
    "型号: {0}": ("Model: {0}", "Модель: {0}"),
    "显示亮度调节": ("Show brightness slider", "Показывать яркость"),
    "显示色温调节": ("Show temperature slider", "Показывать температуру света"),
    "编辑": ("Edit", "Изменить"),
    "删除": ("Delete", "Удалить"),
    "确认删除": ("Delete device", "Удаление устройства"),
    "确定要删除设备「{0}」吗？\n此操作无法撤销。": ("Delete device “{0}”?\nThis cannot be undone.", "Удалить устройство «{0}»?\nЭто действие нельзя отменить."),
    "导入成功": ("Import complete", "Импорт завершён"),
    "已成功导入 {0} 个设备": ("Devices imported: {0}", "Импортировано устройств: {0}"),
    "设备为空": ("No devices", "Нет устройств"),
    "当前没有配置任何设备，确定要保存吗？": ("No devices are configured. Save anyway?", "Ни одно устройство не настроено. Всё равно сохранить?"),
    "保存失败": ("Could not save", "Не удалось сохранить"),
    "{0} (离线)": ("{0} (offline)", "{0} (нет связи)"),
    "无可显示的设备": ("No devices to display", "Нет устройств для отображения"),
    "自动获取": ("Import automatically", "Получить автоматически"),
    "托盘中显示的设备名称": ("Device name shown in the tray panel", "Название устройства на панели управления"),
    "留空自动识别，填写错误可能导致功能异常\n如: yeelink.light.lamp22": ("Leave blank for automatic detection. An incorrect model may cause errors.\nExample: yeelink.light.lamp22", "Оставьте пустым для автоопределения. Неверная модель может вызвать ошибки.\nПример: yeelink.light.lamp22"),
    "对未列入 MIoT 白名单的新型 Yeelight 设备，\n尝试用通用 Light service spec 走 MIoT 协议。\n若设备不兼容则会持续报错 — 取消勾选即可回到 legacy。": ("Try the generic MIoT light protocol for unrecognized Yeelight devices.\nIf it causes errors, clear this checkbox to use the legacy protocol.", "Попробовать общий протокол MIoT для неопознанных ламп Yeelight.\nПри ошибках снимите галочку, чтобы вернуться к прежнему протоколу."),
    "全局快捷键": ("Global hotkeys", "Глобальные горячие клавиши"),
    "点击后按下按键组合，如: Ctrl+Alt+Up\n右键可清空禁用": ("Click, then press a combination, e.g. Ctrl+Alt+Up.\nRight-click to clear and disable.", "Нажмите поле, затем сочетание, например Ctrl+Alt+Up.\nПравая кнопка мыши — очистить и отключить."),
    "点击后按下按键组合，如: Ctrl+Alt+Down\n右键可清空禁用": ("Click, then press a combination, e.g. Ctrl+Alt+Down.\nRight-click to clear and disable.", "Нажмите поле, затем сочетание, например Ctrl+Alt+Down.\nПравая кнопка мыши — очистить и отключить."),
    "点击后按下按键组合，如: Ctrl+Alt+Right\n偏冷白，右键可清空禁用": ("Click, then press a combination, e.g. Ctrl+Alt+Right.\nCooler light. Right-click to clear and disable.", "Нажмите поле, затем сочетание, например Ctrl+Alt+Right.\nСвет холоднее. Правая кнопка мыши — очистить."),
    "点击后按下按键组合，如: Ctrl+Alt+Left\n偏暖白，右键可清空禁用": ("Click, then press a combination, e.g. Ctrl+Alt+Left.\nWarmer light. Right-click to clear and disable.", "Нажмите поле, затем сочетание, например Ctrl+Alt+Left.\nСвет теплее. Правая кнопка мыши — очистить."),
    "清空快捷键": ("Clear hotkey", "Очистить сочетание"),
    "调整步进值:": ("Adjustment step:", "Шаг изменения:"),
    "(每次按快捷键的调整幅度)": ("(change per hotkey press)", "(изменение за одно нажатие)"),
    "每次按快捷键时，亮度/色温增减的数值\n推荐: 5-10": ("Change in brightness / temperature per key press.\nRecommended: 5–10.", "Шаг изменения яркости / температуры за одно нажатие.\nРекомендуется: 5–10."),
    "保存成功": ("Saved", "Сохранено"),
    "设备「{0}」已保存！\n\n是否继续添加更多设备？": ("Device “{0}” saved.\n\nAdd another device?", "Устройство «{0}» сохранено.\n\nДобавить ещё одно устройство?"),
    "请输入下一个设备信息": ("Enter the next device's details", "Введите данные следующего устройства"),
    "获取成功": ("Import successful", "Данные получены"),
    "已自动填充设备信息：\n\n名称：{0}\nIP：{1}\n型号：{2}": ("Device details filled in:\n\nName: {0}\nIP: {1}\nModel: {2}", "Данные устройства заполнены:\n\nНазвание: {0}\nIP: {1}\nМодель: {2}"),
    "未知": ("Unknown", "Неизвестно"),
    "正在关闭显示器挂灯…": ("Turning off monitor lights…", "Выключение ламп монитора…"),
    "设置": ("Settings", "Настройки"),
    "固定在桌面上": ("Pin to desktop", "Закрепить на рабочем столе"),
    "启动时自动检查更新": ("Check for updates at startup", "Проверять обновления при запуске"),
    "退出": ("Exit", "Выход"),
    "🔔 新版本可用: v{0}": ("🔔 Update available: v{0}", "🔔 Доступно обновление: v{0}"),
    "发现新版本": ("Update available", "Доступно обновление"),
    "新版本 v{0} 可用！\n\n右键托盘菜单 → 访问Github 下载更新。": ("Version v{0} is available.\n\nRight-click the tray icon and open GitHub to download it.", "Доступна версия v{0}.\n\nНажмите значок в трее правой кнопкой и откройте GitHub для загрузки."),
    "已是最新版本": ("Up to date", "Установлена последняя версия"),
    "当前版本 v{0} 已是最新版本。": ("Version v{0} is up to date.", "Установлена последняя версия v{0}."),
    "检测到新版本 v{0}！\n\n当前版本已过时，是否立即前往下载？\n\n点击「是」在浏览器打开下载页\n点击「否」稍后再说（可在托盘菜单中查看）": ("Version v{0} is available.\n\nOpen the download page in your browser now?\nYou can also open it later from the tray menu.", "Доступна версия v{0}.\n\nОткрыть страницу загрузки в браузере?\nК ней также можно перейти позже через меню в трее."),
    "已在运行": ("Already running", "Программа уже запущена"),
    "小米显示器挂灯控制程序已经在运行\n\n请检查系统托盘（屏幕右下角）查看图标": ("Mi Monitor Light Tray is already running.\n\nLook for its icon in the system tray next to the clock.", "Mi Monitor Light Tray уже запущена.\n\nНайдите её значок в трее рядом с часами."),
    "未知设备": ("Unknown device", "Неизвестное устройство"),
    "用户名无效": ("Invalid username", "Неверное имя пользователя"),
    "用户名或密码错误": ("Incorrect username or password", "Неверное имя пользователя или пароль"),
    "无法获取 service token": ("Could not get the service token", "Не удалось получить ключ сервиса"),
    "登录成功": ("Signed in", "Вход выполнен"),
    "登录失败": ("Sign-in failed", "Ошибка входа"),
    "无法获取登录信息": ("Could not get sign-in information", "Не удалось получить данные для входа"),
    "无法获取二维码图像": ("Could not get the QR image", "Не удалось получить изображение QR-кода"),
    "请扫描二维码登录": ("Scan the QR code to sign in", "Отсканируйте QR-код для входа"),
    "未初始化": ("Not initialized", "Не инициализировано"),
    "二维码已过期": ("QR code expired. Go back and try again.", "Срок действия QR-кода истёк. Вернитесь назад и попробуйте снова."),
    "网络错误: {0}": ("Network error: {0}", "Ошибка сети: {0}"),
    "轮询失败: {0}": ("Sign-in status check failed: {0}", "Не удалось проверить состояние входа: {0}"),
    "Connected: {0} (firmware {1})": ("Connected: {0} (firmware {1})", "Подключено: {0} (прошивка {1})"),
    "Connection error: {0}": ("Connection error: {0}", "Ошибка подключения: {0}"),
}

ZH_EXTRA: dict[str, str] = {"Language": "语言", "System default": "跟随系统", "Yes": "是", "No": "否", "OK": "确定", "Open": "打开"}
_language = "en"


def system_language() -> str:
    """Use the Windows UI language, rather than the locale's number format."""
    try:
        name = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "en")
    except (AttributeError, OSError):
        name = locale.getlocale()[0] or "en"
    primary = name.lower().replace("-", "_").split("_")[0]
    return primary if primary in ("en", "ru", "zh") else "en"


def set_language(language: str = "auto") -> str:
    global _language
    _language = system_language() if language == "auto" else language
    if _language not in ("en", "ru", "zh"):
        _language = "en"
    return _language


def get_language() -> str:
    return _language


def t(source: str, *args: object) -> str:
    if _language == "zh":
        text = ZH_EXTRA.get(source, source)
    else:
        variants = CATALOG.get(source)
        text = variants[1 if _language == "ru" else 0] if variants else source
    return text.format(*args) if args else text


def menu_text(source: str) -> Callable[[object], str]:
    """pystray reevaluates callable captions when a running menu is refreshed."""
    return lambda _item: t(source)


set_language()
