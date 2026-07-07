# 小米显示器挂灯托盘控制器

> English version: **[README_EN.md](README_EN.md)**

一款 Windows 系统托盘小工具，用类似 [Twinkle Tray](https://twinkletray.com/) 的弹出式滑杆，控制小米 / Yeelight 显示器挂灯的开关、亮度与色温。基于 [python-miio](https://github.com/rytilahti/python-miio) 与设备本地局域网通信，**不经过云端**。

**现在基本兼容所有可以连接米家的灯具**

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

如果你的机型不在任何来源里 → 程序按 legacy 处理。MIoT-only 但未被收录的新机型可在 **设置** 里勾选 **启用 MIoT（实验性）** 强制走 MIoT 通用 Light service spec 试探。

> **反馈兼容性问题时请带上 `model` 字段**（例如 `yeelink.light.lamp22`），这是定位设备协议、色温区间的关键信息。可在配置文件 `%APPDATA%\MiMonitorLightTray\config.json` 的 `device.model` 看到，或者用 `miiocli device --ip <IP> --token <token> info` 查。

1. 本项目的 [`MODEL_CT_RANGES`](mi_monitor_light_tray/miio_client.py) 覆盖表（极少数特例）；
2. **python-miio 自带的 `specs.yaml` 数据库**（约 40 个 Yeelight 机型，本项目直接复用 `YeelightSpecHelper`，不需要我们维护）；
3. 保守默认 `2700–6500 K`。

下表只列重点机型；任何在 python-miio 已知列表里的 Yeelight 设备都会自动拿到正确的色温区间。首次连接后由 `info()` 报告的真实 `model` 自动确认协议与范围，超出范围的滑杆值会被夹到设备实际支持的区间。

| 型号 ID | 设备 | 协议 | 色温范围 | 范围来源 |
|---|---|---|---|---|
| `yeelink.light.lamp22` | 米家智能显示器挂灯 1S（默认型号） | MIoT   | 2700–6500 K | python-miio specs.yaml |
| `yeelink.light.lamp1`  | 米家台灯                          | legacy | 2700–5000 K | python-miio specs.yaml |
| `yeelink.light.lamp2`  | 米家台灯 Pro                      | legacy | 2500–4800 K | 项目覆盖表（specs.yaml 未收录） |
| `yeelink.light.lamp4`  | 米家台灯 1S                       | legacy | 2600–5000 K | python-miio specs.yaml |

未列出的 Yeelight 设备如果在 python-miio 的 specs.yaml 里能查到，色温区间自动套用；否则回落到 2700–6500 K。如果你手上的新机型是 MIoT 设备且未被列入，需要把 `(siid, piid)` 映射加进 `_MIOT_MAPPINGS`，否则会按 legacy 处理。

> **反馈兼容性问题时请带上 `model` 字段**（例如 `yeelink.light.lamp22`），这是定位设备协议、色温区间的关键信息。可在配置文件 `%APPDATA%\MiMonitorLightTray\config.json` 的 `device.model` 看到，或者用 `miiocli device --ip <IP> --token <token> info` 查。

## 特性

- **类 Twinkle Tray 弹出窗** — 鼠标在哪里，弹窗就在哪里，点击外部或 Esc 关闭
- **桌面小部件** — 可固定在桌面任意位置的控制面板，深色主题 + 圆角窗口，支持拖动 / 锁定，记忆位置与可见性
- **全局快捷键** — 系统级热键调节亮度和色温，支持全屏游戏（使用 Windows RegisterHotKey API）
- **自动更新检测** — 启动时自动检查 GitHub Release 新版本，托盘菜单直接跳转下载
- **云端 Token 自动提取** — 设置向导内置「自动获取」按钮，扫码登录小米账号即可一键拉取设备 IP 和 Token
- **亮度 / 色温滑杆** — 亮度 1–100，色温 2700K–6500K
- **滑杆防抖** — 拖动时合并请求，约 120/180 ms 才发一次 miio 调用，避免网络拥塞
- **单例锁** — Windows 命名互斥锁防止重复启动，重复运行时弹窗提示
- **IP 变化自动发现** — DHCP 续约导致 IP 变化时，自动通过 device ID 在局域网内重新定位设备并更新配置
- **空 model 自动识别** — 配置里没填型号时，启动时通过 `info()` 探测真实型号并选择正确协议，避免协议错配
- **Fluent Design 风格** — DWM 原生圆角窗口、半透明、Win11 配色
- **极简托盘图标** — 矢量绘制，高 DPI 清晰；开/关有不同视觉
- **首次运行向导** — 内置 IP/Token 配置界面，含"测试连接"按钮
- **持久化配置** — 保存到 `%APPDATA%\MiMonitorLightTray\config.json`，原子写入
- **免安装** — 提供单文件 EXE，无需 Python 环境
- **灯跟随软件启动/关闭** — 可选；程序启动时自动开灯、退出时自动关灯（两个独立开关）
- **灯随显示器休眠开关** — 显示器休眠时自动关灯，唤醒时自动恢复灯光状态
- **拖滑杆自动开灯** — 灯处于关闭状态时拖动亮度/色温，会先开灯再生效，避免"白拖一通"
- **MIoT 实验开关** — 对未被白名单收录的新型 Yeelight 设备，可在设置里手动启用 MIoT 协议尝试

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

首次运行会自动打开设置向导。**推荐流程**（三步搞定）：

1. 点击 **自动获取** 按钮
2. 用小米账号 / 米家 App 扫描弹出的二维码登录
3. 在设备列表（2×N 网格）中点击你的台灯

IP / Token / 型号会自动填入表单。点击 **测试连接** 验证，**保存**即可。Token 仅写入本地 `%APPDATA%\MiMonitorLightTray\config.json`，不上传第三方服务器。

### 手动填写（备选）

如果你不想登录小米账号、或自动获取失败，可以手动填：

- **设备 IP**：米家 App → 设备页面 → ⋮ → 更多设置 → 网络信息；或在路由器 DHCP 列表里找名称含 `yeelight` / `monitor` 的设备
- **miio Token**：32 位十六进制串，可用 [Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor) 或 `miiocli cloud` 提取
- **显示名称**：随意，会显示在托盘提示
- **型号**：留空即可，连接后自动识别

### （可选）手动验证连接

```python
from miio import Device

dev = Device(ip="192.168.1.xxx", token="你的32位token")
info = dev.info()
print(f"连接成功: model={info.model} firmware={info.firmware_version}")
```

`Device.info()` 是协议层命令，legacy 与 MIoT 设备都支持。后续的属性读写需要按设备 model 走对应的 `Yeelight` 或 `MiotDevice` 接口 —— 本程序内部已经按 model 自动分发，普通使用不需要手动区分。

## 使用

- **左键单击**托盘图标 → 在光标附近弹出控制窗
- 拖动 **亮度** 滑杆（1–100）和 **色温** 滑杆（2700K 暖白 — 6500K 冷白）
- 点击底部 **⏻** 切换开关，**⚙** 进入设置
- 点击窗口外或按 `Esc` 关闭弹窗
- **右键单击**托盘图标：
  - **调整亮度** — 打开控制窗
  - **桌面小部件** — 切换桌面小部件显示
  - **设置** — 重新配置设备
  - **开机自启动** — 开关开机自启动
  - **灯跟随软件启动** — 开关程序启动时自动开灯
  - **灯跟随软件关闭** — 开关程序退出时自动关灯
  - **灯随显示器休眠开关** — 开关显示器休眠时自动关灯
  - **系统休眠时关灯** — 系统进入睡眠/休眠时自动关灯
  - **系统唤醒时开灯** — 系统从睡眠/休眠唤醒时自动开灯
  - **固定在桌面上** — 切换桌面小部件显示
  - **检查更新** — 手动检查 GitHub Release 新版本
  - **启动时自动检查更新** — 开关自动更新检测
  - **访问 GitHub 主页** — 在浏览器中打开项目主页
  - **退出** — 关闭程序

如果有新版本可用，托盘菜单会显示 🔔 提示并提供下载链接。

### 全局快捷键

在 **设置** 窗口的"全局快捷键"区域配置系统级热键，即使在全屏游戏或其他应用中也能生效：

1. 点击快捷键输入框
2. 按下你想要的按键组合（如 `Ctrl+Alt+Up`）
3. 输入框会自动填充按键组合
4. 设置调整步进值（默认 5）
5. 点击"保存"应用

**可用修饰键**：Ctrl、Shift、Alt、Win  
**推荐组合**：
- 亮度增加：`Ctrl+Alt+Up`
- 亮度降低：`Ctrl+Alt+Down`
- 色温增加：`Ctrl+Alt+Right`（偏冷白）
- 色温降低：`Ctrl+Alt+Left`（偏暖白）

留空某个快捷键可禁用该功能。使用系统级 `RegisterHotKey` API，确保在全屏独占游戏中也能响应。

### 桌面小部件

右键托盘菜单点击 **桌面小部件** 即可在桌面显示一个常驻控制面板，UI 与托盘弹窗一致：

- **拖动** 标题区域移动位置
- 右键小部件可 **锁定/解锁** 位置（锁定后无法拖动，防止误碰）
- 位置、锁定状态、可见性自动持久化到 `config.json` 的 `widget` 段
- 不在任务栏显示，保持桌面整洁

### 开机自启动

打开 **设置** 窗口勾选"开机自启动"，或者在托盘**右键菜单**点击"开机自启动"切换。本质是向 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 写一条 `MiMonitorLightTray`，不需要管理员权限，只对当前用户生效。

### 灯跟随软件启动 / 关闭

设置窗口或托盘右键菜单都能勾选以下两个独立开关：

- **灯跟随软件启动** — 程序启动时自动开灯
- **灯跟随软件关闭** — 程序退出（含点托盘菜单"退出"、`Ctrl+C`、任务栏关闭）时自动关灯

两个开关相互独立，可以单独勾选。和"开机自启动"组合使用就能做到"开机 → 灯亮，关机 → 灯灭"。退出关灯走 `atexit` 钩子兜底，覆盖非托盘"退出"的退出路径。

### 灯随显示器休眠开关

设置窗口或托盘右键菜单都能勾选"灯随显示器休眠开关"：

- **显示器休眠时** — 自动关闭灯光，节能省电
- **显示器唤醒时** — 自动恢复到休眠前的灯光状态

此功能使用用户空闲时间检测（空闲 55 秒触发）监听显示器状态变化，智能记忆休眠前的开关状态。特别适合离开电脑时让显示器和灯光同步休眠，回来时自动恢复。

### 系统休眠时关灯 / 系统唤醒时开灯

设置窗口或托盘右键菜单提供两个独立的开关：

- **系统休眠时关灯** — 系统进入睡眠/休眠时自动关闭灯光
- **系统唤醒时开灯** — 系统从睡眠/休眠唤醒时自动打开灯光

两个开关相互独立，可以单独勾选。此功能监听 Windows 电源广播消息（WM_POWERBROADCAST），使用顶级窗口接收 PBT_APMSUSPEND / PBT_APMRESUMESUSPEND 事件。适合离开电脑让系统自动休眠的场景，回来时灯光自动恢复。

### 拖滑杆自动开灯

当灯处于关闭状态时拖动亮度或色温滑杆，程序会**先发送开灯指令，再设置目标值**。这是默认行为、无需开关 — 避免出现"拖了半天没反应"的困惑（legacy Yeelight 的自动开灯由固件决定，MIoT 协议则完全不会自动开）。

### 启用 MIoT（实验性）

`_MIOT_MAPPINGS` 是已知 MIoT 设备的白名单。如果你手上是新型 Yeelight 设备、不在白名单里、又怀疑它实际走 MIoT 协议，可以在 **设置** 里勾选"启用 MIoT（实验性）"，程序会用 lamp22 的通用 Light service spec（`(siid=2, piid=1/2/3) = power/brightness/color-temperature`）尝试与设备通信。这是一个赌注 — Mi/Yeelight 监视器灯/台灯多数遵循这个布局，但不保证所有设备如此。设备不兼容时会持续报错；关掉这个开关即可回到 legacy 路径。

### 命令行参数

```bash
MiMonitorLightTray.exe --setup    # 强制打开设置向导
MiMonitorLightTray.exe --debug    # 开启调试日志
```

## 从源码构建 EXE

```bash
pip install -e ".[build]"
python scripts/build_exe.py
```

输出到 `dist\MiMonitorLightTray.exe`。脚本会用 PyInstaller 的 `--onefile --noconsole`，并通过 `--collect-data miio` 把 python-miio 的 YAML/JSON 规格文件一起打包（否则会在运行时崩溃）。

## 运行测试

```bash
pip install -e ".[dev]"
pytest -q
```

测试覆盖配置序列化（[tests/test_config.py](tests/test_config.py)）、托盘图标渲染（[tests/test_icon.py](tests/test_icon.py)）、miio 包装层与防抖器（[tests/test_miio_client.py](tests/test_miio_client.py)）。UI 与真实网络路径需要手动验证。

## 项目结构

```
mi_monitor_light_tray/
  __main__.py          入口：单例锁 → 加载配置 → 启动托盘与弹窗
  config.py            AppConfig / DeviceConfig / WidgetConfig 持久化（原子写入）
  miio_client.py       legacy Yeelight + MIoT 协议分发，线程安全包装 + Debouncer 防抖
  flyout.py            Tk 无边框弹窗 + Canvas 实现的暗色滑杆
  desktop_widget.py    桌面小部件（可拖动、锁定、记忆位置）
  cloud_login_window.py 云端登录窗口（二维码登录 + 设备选择）
  token_extractor/     小米云 API 客户端：authentication + device list 拉取
  icon.py              Pillow 程序化绘制托盘图标（无二进制资源）
  setup_wizard.py      IP/Token 配置向导，含「自动获取」按钮和测试连接
  tray.py              pystray 系统托盘控制器
  shutdown_listener.py Windows WM_QUERYENDSESSION 监听，关机时关灯
  monitor_sleep_listener.py Windows WM_POWERBROADCAST 监听，显示器休眠时关灯
  single_instance.py   Windows 命名互斥锁（单例保护）
  discovery.py         UDP 广播设备发现，按 device_id 重定位
scripts/
  build_exe.py         PyInstaller 打包脚本
  run_app.py           PyInstaller 入口（避免相对导入问题）
tests/                 pytest 单元测试套件
```

## 配置文件

位置：`%APPDATA%\MiMonitorLightTray\config.json`

```json
{
  "device": {
    "ip": "192.168.1.100",
    "token": "...32 位十六进制...",
    "name": "显示器挂灯",
    "model": "",
    "device_id": 12345678,
    "enable_miot_for_unknown": false,
    "power_on_at_startup": false,
    "power_off_at_exit": false,
    "power_off_on_monitor_sleep": false,
    "power_off_on_system_suspend": false,
    "power_on_on_system_resume": false
  },
  "widget": {
    "visible": false,
    "x": 100,
    "y": 100,
    "locked": true
  },
  "hotkey": {
    "brightness_up": "Ctrl+Alt+Up",
    "brightness_down": "Ctrl+Alt+Down",
    "color_temp_up": "Ctrl+Alt+Right",
    "color_temp_down": "Ctrl+Alt+Left",
    "step": 5
  },
  "auto_check_update": true
}
```

`device_id` 在首次连接成功时自动捕获，用于 IP 变化后的自动发现。`model` 留空时程序会在启动时通过 `info()` 自动探测并回填，避免协议错配。`enable_miot_for_unknown` 让未在 `_MIOT_MAPPINGS` 白名单里的 Yeelight 设备也走 MIoT 协议（用 lamp22 的通用 Light service spec 探测），适合新机型；`power_on_at_startup` / `power_off_at_exit` / `power_off_on_monitor_sleep` / `power_off_on_system_suspend` / `power_on_on_system_resume` 五个独立开关分别控制程序启动时自动开灯、程序退出时自动关灯、显示器休眠时自动关灯、系统休眠时自动关灯、系统唤醒时自动开灯。`widget` 段记录桌面小部件的位置、锁定状态与可见性。`hotkey` 段存储全局快捷键配置和调整步进值。`auto_check_update` 控制是否在启动时自动检查 GitHub Release 更新。亮度/色温由挂灯自己记忆；开机自启动（Windows 系统层面的）状态由注册表保存，不在此文件里。

## 常见问题

**Q：提示"已在运行"**
A：程序已启动，检查系统托盘溢出区（右下角向上箭头）是否有图标。

**Q：状态显示"离线 — Unable to discover the device"**
A：
1. 确认挂灯通电且与电脑在同一局域网
2. 确认 IP 正确（用米家 App 或路由器复查）
3. miio 走 UDP 54321，部分企业网络/防火墙会拦截，可临时关闭防火墙测试
4. 程序会在后台自动尝试发现新 IP（如果 `device_id` 已知）

**Q：提示"miio error: Invalid token"**
A：Token 在设备重新配对到米家时会刷新，需用 cloud-tokens-extractor 重新提取。

**Q：托盘图标不显示**
A：Windows 资源管理器可能把它收进了溢出区，点击托盘左侧的向上箭头查看。

**Q：拖滑杆时灯有约 0.1 秒延迟**
A：这是有意的防抖（120ms 亮度 / 180ms 色温），用来合并请求避免设备被刷爆，松开手后会立即生效。

## 致谢

- [@zengzoxiong](https://github.com/zengzoxiong) — 云端 Token 提取与桌面小部件功能（[PR #1](https://github.com/Martlnez/MiMonitorLightTray/pull/1)）
- [python-miio](https://github.com/rytilahti/python-miio) — miio 协议库
- [pystray](https://github.com/moses-palmer/pystray) — Python 系统托盘
- [Pillow](https://python-pillow.org/) — 图标生成
- [Twinkle Tray](https://twinkletray.com/) — UI 灵感

## 开源协议

[MIT License](LICENSE)
