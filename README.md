# 小米显示器挂灯托盘控制器

> English version: **[README_EN.md](README_EN.md)**

一款 Windows 系统托盘小工具，用类似 [Twinkle Tray](https://twinkletray.com/) 的弹出式滑杆，控制小米 / Yeelight 显示器挂灯及各类米家灯具的开关、亮度与色温。基于 [python-miio](https://github.com/rytilahti/python-miio) 与设备本地局域网通信，**不经过云端**。

**支持多灯同时控制** — 可在同一实例中管理任意数量的设备，每盏灯拥有独立的显示、快捷键、休眠 / 唤醒策略。基本兼容所有可以连接米家的灯具。

![Python](https://img.shields.io/badge/Python-3.9%2B-blue) ![Platform](https://img.shields.io/badge/platform-Windows-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

## 兼容设备

本程序按设备 `model` **自动选择 legacy 或 MIoT 协议**。除少数手工 curated 的机型外，**~2100 个 MIoT 灯具的协议映射与色温范围已从 [home.miot-spec.com](https://home.miot-spec.com) 抓取并嵌入** ([mi_monitor_light_tray/_miot_data.py](mi_monitor_light_tray/_miot_data.py))，覆盖 yeelink、xiaomi、mijia 以及大量第三方品牌。

**路由决策**（按 model 在以下集合的成员关系自动推导）：

1. **curated `_MIOT_MAPPINGS`**（[miio_client.py](mi_monitor_light_tray/miio_client.py) 顶部，含 lamp22）→ MIoT
2. **python-miio `YeelightSpecHelper`**（specs.yaml 已知的 legacy 设备，41 个）→ legacy
3. **本项目 curated `MODEL_CT_RANGES`**（手工验证过 legacy 的设备，如 lamp2）→ legacy
4. **bulk `_miot_data`**（前 3 个都没听说过的 MIoT-only 设备，~2100 个）→ MIoT
5. **完全未知** → legacy（兜底，配合「启用 MIoT 实验性」开关可改走 MIoT）

**色温范围解析**（同样优先级）：curated 覆盖表 > YeelightSpecHelper > bulk → 默认 2700–6500K。bulk 数据有合理性过滤（min ≥ 1000K、max ∈ [2000, 15000]K、span ≥ 500K），拒绝 spec 里把色温单位错标成 percentage 的伪 Kelvin 条目（~7% 的源数据是这样）。

下表只列重点机型，其它任何在嵌入数据库里的设备都会自动拿到正确协议与色温区间：

| 型号 ID | 设备 | 协议 | 色温范围 | 数据来源 |
|---|---|---|---|---|
| `yeelink.light.lamp22` | 米家智能显示器挂灯 1S（默认型号） | MIoT   | 2700–6500 K | curated |
| `yeelink.light.lamp1`  | 米家台灯                          | legacy | 2700–5000 K | YeelightSpecHelper |
| `yeelink.light.lamp2`  | 米家台灯 Pro                      | legacy | 2500–4800 K | 项目覆盖表 |
| `yeelink.light.lamp4`  | 米家台灯 1S                       | legacy | 2600–5000 K | YeelightSpecHelper |
| `yeelink.light.ceiling*` 系列 | 米家智能吸顶灯 | legacy | 2700–6500 K | YeelightSpecHelper |
| `yeelink.light.bslamp*` | 米家床头灯 | legacy | 1700–6500 K | YeelightSpecHelper |
| 其它 ~2100 个 MIoT-only 机型 | 各品牌新型智能灯 | MIoT | 按 spec | _miot_data.py（bulk） |

如果你的机型不在任何来源里 → 程序按 legacy 处理。MIoT-only 但未被收录的新机型可在**设备编辑器**里勾选 **启用 MIoT（实验性）** 强制走 MIoT 通用 Light service spec 试探。

> **反馈兼容性问题时请带上 `model` 字段**（例如 `yeelink.light.lamp22`）。可在配置文件 `%APPDATA%\MiMonitorLightTray\config.json` 的 `devices[].model` 看到，或者用 `miiocli device --ip <IP> --token <token> info` 查。

## 特性

- **多灯并行管理** — 一个实例控制任意多盏米家 / Yeelight 灯，每灯独立配置
- **类 Twinkle Tray 弹出窗** — 每盏灯一节滑杆与开关按钮，窗口高度按内容自适应
- **"关闭所有灯"一键操作** — 弹窗底部按钮，一次关掉所有在线设备
- **设备列表管理** — 图形化增删设备，拖拽排序，编辑 IP / Token / 型号
- **云端一键导入** — 扫码登录小米账号后多选设备，一次性批量添加
- **每设备独立快捷键** — 每盏灯有自己的亮度 / 色温加减快捷键，互不干扰；使用 Windows RegisterHotKey API，全屏游戏中也响应
- **每设备独立电源策略** — 逐灯配置软件启动 / 关闭、显示器休眠 / 唤醒、系统休眠 / 唤醒的自动开关
- **每设备可见性控制** — 单独隐藏某盏灯的亮度或色温滑杆，只保留常用控件
- **桌面小部件** — 可固定在桌面任意位置的控制面板，深色主题 + 圆角窗口，支持拖动 / 锁定，记忆位置与可见性
- **自动更新检测** — 启动时自动检查 GitHub Release 新版本，托盘菜单直接跳转下载
- **亮度 / 色温滑杆** — 亮度 1–100，色温由设备实际支持范围决定（自动读取）
- **滑杆防抖** — 拖动时合并请求，约 120 / 180 ms 才发一次 miio 调用，避免网络拥塞（每设备独立防抖器）
- **单例锁** — Windows 命名互斥锁防止重复启动，重复运行时弹窗提示
- **IP 变化自动发现** — DHCP 续约导致 IP 变化时，自动通过 device ID 在局域网内重新定位设备并更新配置
- **空 model 自动识别** — 配置里没填型号时，启动时通过 `info()` 探测真实型号并选择正确协议，避免协议错配
- **Fluent Design 风格** — DWM 原生圆角窗口、半透明、Win11 配色
- **极简托盘图标** — 矢量绘制，高 DPI 清晰；开 / 关有不同视觉
- **持久化配置** — 保存到 `%APPDATA%\MiMonitorLightTray\config.json`，原子写入
- **单设备配置自动迁移** — 从 v1.4.x 升级时旧的 `device` 单对象自动转为 `devices` 数组，无需手工处理
- **免安装** — 提供单文件 EXE，无需 Python 环境
- **拖滑杆自动开灯** — 灯处于关闭状态时拖动亮度 / 色温，会先开灯再生效，避免"白拖一通"
- **MIoT 实验开关** — 对未被白名单收录的新型 Yeelight 设备，可在设备编辑器里手动启用 MIoT 协议尝试

## 安装

### 方式一：下载预编译版本（推荐）

从 [Releases](https://github.com/Martlnez/MiMonitorLightTray/releases) 下载 `MiMonitorLightTray.exe`，双击运行即可。每次 push 到 `main` 与每个 tag 都会自动构建（见 [build.yml](.github/workflows/build.yml)）。

### 方式二：从源码运行

```bash
git clone https://github.com/Martlnez/MiMonitorLightTray.git
cd MiMonitorLightTray

python -m venv .venv
.venv\Scripts\activate
pip install -e .

mi-monitor-light-tray
```

要求 Python 3.9+。

## 首次设置

首次运行会自动打开设备列表向导。**推荐流程**（多设备一键导入）：

1. 点击 **云端导入**
2. 用小米账号 / 米家 App 扫描弹出的二维码登录
3. 在设备列表中**勾选一个或多个**灯具，点击 **确认导入**

所有勾选的设备会带着 IP / Token / 型号自动进入设备列表。Token 仅写入本地 `%APPDATA%\MiMonitorLightTray\config.json`，不上传第三方服务器。

### 手动添加设备

也可以点击 **+ 添加设备** 逐个填写：

- **设备 IP**：米家 App → 设备页面 → ⋮ → 更多设置 → 网络信息；或在路由器 DHCP 列表里找名称含 `yeelight` / `monitor` 的设备
- **miio Token**：32 位十六进制串，可用 [Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor) 或 `miiocli cloud` 提取
- **显示名称**：随意，会显示在弹窗上方
- **型号**：留空即可，连接后自动识别

点击 **测试连接** 验证连通性，**保存** 后设备加入列表。可以对已添加的设备执行 **编辑** / **删除**，或按住行首 `⋮⋮` 图标 **拖拽** 调整显示顺序 —— 顺序决定弹窗中每个设备的显示位置。

## 使用

- **左键单击**托盘图标 → 在光标附近弹出控制窗
- 弹窗按设备列表顺序为每盏灯渲染一节：设备名 + 状态 + 独立 **⏻** 开关按钮，下方是亮度 / 色温滑杆
- 窗口高度**按内容自适应**：一盏灯与旧版差不多，两盏灯约翻倍高
- 底部按钮从右到左：**⚙** 打开设置、**⏻** 关闭所有在线灯
- 点击窗口外或按 `Esc` 关闭弹窗
- 设备名过长时自动截断为 `xxxx...`，按钮位置保持固定，不会被挤出可视区

### 右键托盘菜单

- **调整亮度** — 打开控制窗
- **桌面小部件** — 切换桌面小部件显示（当前小部件绑定第一盏灯）
- **设置** — 打开设备列表管理器
- **开机自启动** — 开关开机自启动
- **灯跟随软件启动** — 若任一设备启用，视为开
- **灯跟随软件关闭** — 若任一设备启用，视为开
- **灯随显示器休眠开关** — 若任一设备启用，视为开
- **系统休眠时关灯** — 若任一设备启用，视为开
- **系统唤醒时开灯** — 若任一设备启用，视为开
- **检查更新** — 手动检查 GitHub Release 新版本
- **启动时自动检查更新** — 开关自动更新检测
- **访问 GitHub 主页** — 在浏览器中打开项目主页
- **退出** — 关闭程序

托盘菜单里那几个"聚合视图"的开关只显示第一台设备的取反效果 — 想逐灯精确设置，请到 **设置 → 编辑设备** 里对每盏灯单独勾选。有新版本时托盘菜单会显示 🔔 提示并提供下载链接。

### 全局快捷键（每设备独立）

在 **设置 → 编辑设备** 底部的"快捷键设置"里，为每盏灯单独绑定：

1. **点击**快捷键输入框
2. **按下**想要的按键组合（如 `Ctrl+Alt+Up`）
3. 输入框自动填充，可再次修改
4. **右键**输入框直接清空
5. 设置调整步进（默认 5，亮度按 1–100 直加减，色温按范围百分比换算）
6. 保存

**可用修饰键**：Ctrl、Shift、Alt、Win  
**推荐组合示例**：
- 亮度增加：`Ctrl+Alt+Up`
- 亮度降低：`Ctrl+Alt+Down`
- 色温增加：`Ctrl+Alt+Right`（偏冷白）
- 色温降低：`Ctrl+Alt+Left`（偏暖白）

留空则禁用该功能。多设备场景下**每盏灯必须使用不同的按键组合** — 系统级 `RegisterHotKey` 是独占的，重复绑定会失败。快捷键在设置保存后立即生效。

### 每设备显示控制

在 **设置** 界面的设备卡片上可以直接勾选 / 取消：

- **显示亮度调节** — 是否在弹窗中显示此设备的亮度滑杆
- **显示色温调节** — 是否在弹窗中显示此设备的色温滑杆

两个开关都关掉时，该设备**不会出现在弹窗里**（快捷键仍生效）—— 适合"只想快捷键控制、不想在弹窗里看到"的辅助灯。

### 桌面小部件

右键托盘菜单点击 **桌面小部件** 即可在桌面显示一个常驻控制面板：

- **拖动**标题区域移动位置
- 右键小部件可 **锁定/解锁** 位置（锁定后无法拖动，防止误碰）
- 位置、锁定状态、可见性自动持久化到 `config.json` 的 `widget` 段

**注意：桌面小部件当前只显示配置里第一盏灯**（老单设备实现，多设备扩展在计划中）。要控制其它灯请用托盘弹窗或快捷键。

### 开机自启动

在托盘**右键菜单**或**设备列表底部**勾选"开机自启动"。本质是向 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 写一条 `MiMonitorLightTray`，不需要管理员权限，只对当前用户生效。

### 每设备电源策略

每盏灯在**设备编辑器**里都有独立的五个开关：

- **灯跟随软件启动** — 程序启动时自动开这盏灯
- **灯跟随软件关闭** — 程序退出（含托盘"退出"、`Ctrl+C`、任务栏关闭、Windows 关机）时自动关这盏灯
- **灯随显示器休眠开关** — 显示器休眠时关灯，唤醒时恢复休眠前状态
- **系统休眠时关灯** — 系统进入睡眠 / 休眠时关灯
- **系统唤醒时开灯** — 系统从睡眠 / 休眠恢复时开灯

每盏灯**互不干扰**：可以让台灯跟随软件启停、显示器挂灯跟随显示器休眠、床头灯只用系统休眠 / 唤醒 —— 组合自由。

底层实现：
- 显示器休眠通过 `RegisterPowerSettingNotification` 订阅 `GUID_CONSOLE_DISPLAY_STATE`，跟随 Windows 自身的显示器电源广播，不做独立空闲计时（看视频、听音乐时不会误关）
- 系统休眠 / 唤醒监听 `WM_POWERBROADCAST` 的 `PBT_APMSUSPEND` / `PBT_APMRESUMESUSPEND`
- 程序退出关灯走 `atexit` 钩子 + 顶级窗口的 `WM_QUERYENDSESSION` 双保险，覆盖 Windows 强制关机场景

### 拖滑杆自动开灯

当灯处于关闭状态时拖动亮度或色温滑杆，程序会**先发送开灯指令，再设置目标值**。默认行为、无需开关 —— 避免"拖了半天没反应"（legacy Yeelight 由固件决定是否自动开，MIoT 协议则完全不会自动开）。

### 启用 MIoT（实验性）

设备编辑器里的开关。适合以下情况：手上是新型 Yeelight / MIoT 设备、不在 `_MIOT_MAPPINGS` 白名单里、又怀疑它实际走 MIoT 协议。勾选后程序会用 lamp22 的通用 Light service spec（`(siid=2, piid=1/2/3) = power/brightness/color-temperature`）尝试通信。设备不兼容时会持续报错；关掉即可回到 legacy 路径。

### 命令行参数

```bash
MiMonitorLightTray.exe --setup    # 强制打开设备列表向导
MiMonitorLightTray.exe --debug    # 开启调试日志
```

## 从源码构建 EXE

```bash
pip install -e ".[build]"
python scripts/build_exe.py
```

输出到 `dist\MiMonitorLightTray.exe`。脚本会用 PyInstaller 的 `--onefile --noconsole`，并通过 `--collect-data miio` 把 python-miio 的 YAML / JSON 规格文件一起打包（否则会在运行时崩溃）。构建脚本开头会自动执行 `pip install -e . --no-deps --quiet` 同步 dist-info，确保 EXE 报告的版本号与 `pyproject.toml` 一致。

## 运行测试

```bash
pip install -e ".[dev]"
pytest -q
```

测试覆盖配置序列化（[tests/test_config.py](tests/test_config.py)）、托盘图标渲染（[tests/test_icon.py](tests/test_icon.py)）、miio 包装层与防抖器（[tests/test_miio_client.py](tests/test_miio_client.py)）。UI 与真实网络路径需要手动验证。

## 项目结构

```
mi_monitor_light_tray/
  __main__.py             入口：单例锁 → 加载配置 → 启动托盘、弹窗、快捷键
  config.py               AppConfig / DeviceConfig / WidgetConfig / HotkeyConfig
                          持久化（原子写入），含 v1.4→v1.5 单设备自动迁移
  miio_client.py          legacy Yeelight + MIoT 协议分发，线程安全 + 每设备 Debouncer
  flyout.py               无边框弹窗，每设备一节，高度自适应，含"关闭所有灯"按钮
  desktop_widget.py       桌面小部件（当前绑定第一盏灯）
  device_list_wizard.py   设备列表管理器（增删 / 拖拽排序 / 云端导入 / 全局设置）
  device_editor.py        单设备编辑对话框（IP / Token / 型号 / 电源策略 / 快捷键）
  cloud_login_window.py   云端登录窗口（二维码 + 多选设备）
  token_extractor/        小米云 API 客户端：authentication + device list 拉取
  hotkey_manager.py       全局快捷键管理（Windows RegisterHotKey，每设备独立 ID）
  version_checker.py      GitHub Release 版本检查（importlib.metadata 读版本）
  icon.py                 Pillow 程序化绘制托盘图标（无二进制资源）
  setup_wizard.py         首次运行时的空态引导，跳到 device_list_wizard
  tray.py                 pystray 系统托盘控制器
  shutdown_listener.py    Windows WM_QUERYENDSESSION 监听，关机时关灯
  monitor_sleep_listener.py Windows WM_POWERBROADCAST + GUID_CONSOLE_DISPLAY_STATE
  single_instance.py      Windows 命名互斥锁（单例保护）
  discovery.py            UDP 广播设备发现，按 device_id 重定位
scripts/
  build_exe.py            PyInstaller 打包脚本，构建前自动同步 dist-info
  run_app.py              PyInstaller 入口（避免相对导入问题）
tests/                    pytest 单元测试套件
```

## 配置文件

位置：`%APPDATA%\MiMonitorLightTray\config.json`

```json
{
  "devices": [
    {
      "id": "1a2b3c4d",
      "ip": "192.168.1.100",
      "token": "...32 位十六进制...",
      "name": "显示器挂灯",
      "model": "yeelink.light.lamp22",
      "device_id": 12345678,
      "enable_miot_for_unknown": false,
      "power_on_at_startup": false,
      "power_off_at_exit": false,
      "power_off_on_monitor_sleep": false,
      "power_off_on_system_suspend": false,
      "power_on_on_system_resume": false,
      "brightness_up": "Ctrl+Alt+Up",
      "brightness_down": "Ctrl+Alt+Down",
      "color_temp_up": "Ctrl+Alt+Right",
      "color_temp_down": "Ctrl+Alt+Left",
      "hotkey_step": 5,
      "show_brightness": true,
      "show_color_temp": true
    }
  ],
  "active_device_id": "ALL",
  "widget": {
    "visible": false,
    "x": 100,
    "y": 100,
    "locked": true
  },
  "hotkey": {
    "brightness_up": "",
    "brightness_down": "",
    "color_temp_up": "",
    "color_temp_down": "",
    "step": 5
  },
  "auto_check_update": true
}
```

**字段说明**：

- `devices[]`：所有设备的数组。可以是空数组（此时启动会进设备列表向导）
- `devices[].id`：稳定标识符，新设备是 `temp_xxxxxxxx`，首次成功连接后自动升级为 `<device_id 的 8 位十六进制>`
- `devices[].device_id`：首次连接时从 miio `info()` 捕获，用于 IP 变化后的自动发现
- `devices[].model`：留空时启动时通过 `info()` 自动探测并回填
- `devices[].enable_miot_for_unknown`：未在 `_MIOT_MAPPINGS` 白名单的 Yeelight 设备强制走 MIoT
- `devices[].power_on_at_startup` / `power_off_at_exit` / `power_off_on_monitor_sleep` / `power_off_on_system_suspend` / `power_on_on_system_resume`：五个独立电源策略开关
- `devices[].brightness_up` / `brightness_down` / `color_temp_up` / `color_temp_down`：本设备的四个全局快捷键
- `devices[].hotkey_step`：快捷键调整步进（亮度：加减 N，色温：按范围 N% 换算）
- `devices[].show_brightness` / `show_color_temp`：弹窗内此设备是否显示对应滑杆
- `active_device_id`：`"ALL"` 保留字段（历史遗留，当前未使用）
- `widget`：桌面小部件位置 / 可见性 / 锁定状态
- `hotkey`：**已废弃的旧全局快捷键段**，仅为向后兼容保留，v1.5+ 使用每设备快捷键
- `auto_check_update`：启动时是否自动检查 GitHub Release

**v1.4 → v1.5 迁移**：程序首次读取旧配置时会自动把顶层 `device` 单对象转成 `devices: [...]` 数组并生成 id，用户无需手工处理。

## 常见问题

**Q：从 v1.4.x 升级后设备没了 / 报错**  
A：程序会自动把旧的 `device` 字段迁移为 `devices` 数组。如果没有生效，检查 `%APPDATA%\MiMonitorLightTray\config.json` 是否可读；实在不行删掉重新走一遍设备列表向导。

**Q：多盏灯的快捷键冲突**  
A：系统级 `RegisterHotKey` 每个组合只能被注册一次，所以**每盏灯必须用不同的快捷键**。冲突时后注册的会失败并写入日志（`--debug` 可看到）。

**Q：提示"已在运行"**  
A：程序已启动，检查系统托盘溢出区（右下角向上箭头）是否有图标。

**Q：状态显示"离线 — Unable to discover the device"**  
A：
1. 确认挂灯通电且与电脑在同一局域网
2. 确认 IP 正确（用米家 App 或路由器复查）
3. miio 走 UDP 54321，部分企业网络 / 防火墙会拦截，可临时关闭防火墙测试
4. 程序会在后台自动尝试发现新 IP（如果 `device_id` 已知）

**Q：提示"miio error: Invalid token"**  
A：Token 在设备重新配对到米家时会刷新，需用 cloud-tokens-extractor 重新提取，或者用云端导入功能重新拉一次。

**Q：托盘图标不显示**  
A：Windows 资源管理器可能把它收进了溢出区，点击托盘左侧的向上箭头查看。

**Q：拖滑杆时灯有约 0.1 秒延迟**  
A：这是有意的防抖（120ms 亮度 / 180ms 色温），用来合并请求避免设备被刷爆，松开手后会立即生效。每盏灯有独立防抖器，多设备不会互相拖累。

**Q：桌面小部件只显示一盏灯**  
A：小部件目前是旧的单设备实现，多设备场景请用托盘弹窗或快捷键。

## 致谢

- [@zengzoxiong](https://github.com/zengzoxiong) — 云端 Token 提取与桌面小部件功能（[PR #1](https://github.com/Martlnez/MiMonitorLightTray/pull/1)）
- [python-miio](https://github.com/rytilahti/python-miio) — miio 协议库
- [pystray](https://github.com/moses-palmer/pystray) — Python 系统托盘
- [Pillow](https://python-pillow.org/) — 图标生成
- [Twinkle Tray](https://twinkletray.com/) — UI 灵感

## 开源协议

[MIT License](LICENSE)

