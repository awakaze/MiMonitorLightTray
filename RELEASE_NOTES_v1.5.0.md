# v1.5.0

一次围绕 **多灯并行管理** 的大重构。核心从"一个实例控制一盏灯"升级为"一个实例控制任意多盏灯，每盏独立配置、独立控制"。

## ✨ 新功能

### 多灯连接

- **无上限的设备数量** — 一个实例可同时管理任意多盏米家 / Yeelight 灯，共享一份托盘图标、一份弹窗、一份快捷键路由
- **图形化设备列表** — 全新的设置界面，卡片式展示每盏灯的名称 / IP / 型号 / 状态；支持添加、编辑、删除
- **拖拽排序** — 按住每张卡片左侧的 `⋮⋮` 图标即可拖动，顺序决定弹窗中的显示位置
- **云端一键多选导入** — 扫码登录小米账号后可**勾选多盏设备**，一次性批量添加，Token 全部自动填入
- **配置自动迁移** — 从 v1.4.x 升级时，旧的顶层 `device` 单对象会被无感转换为 `devices: [...]` 数组，用户不用改一行 JSON

### 弹窗（Flyout）重构

- **每设备一节** — 弹窗按设备列表顺序为每盏灯渲染独立的一节：设备名、状态、⏻ 开关按钮、亮度 / 色温滑杆
- **窗口高度自适应** — 一盏灯与旧版差不多，两盏灯约翻倍高，以此类推
- **关闭所有灯一键按钮** — 底部新增 ⏻ 按钮，一次关掉所有在线设备
- **设备名智能截断** — 名称过长时自动截断为 `xxxx...`，按钮位置保持固定不会被挤出可视区
- **每设备独立防抖器** — 多盏灯拖滑杆时互不干扰，也不会互相延迟

### 每设备独立配置

以下 5 项电源策略在每盏灯上都是独立开关：

- 灯跟随软件启动
- 灯跟随软件关闭
- 灯随显示器休眠开关
- 系统休眠时关灯
- 系统唤醒时开灯

外加两项显示控制：

- **显示亮度调节** — 是否在弹窗中显示此设备的亮度滑杆
- **显示色温调节** — 是否在弹窗中显示此设备的色温滑杆

两个显示开关都关掉的设备**不会出现在弹窗里**（但快捷键仍生效）—— 适合"只想用快捷键控制、不想在弹窗里看到"的辅助灯。

### 每设备独立快捷键

- 每盏灯拥有自己的四个全局快捷键：亮度 +/-、色温 +/-，以及独立的调整步进值
- 快捷键**在输入框内按下即捕获**（点击输入框，按下想要的组合，自动填充）
- **右键输入框直接清空**（原先的实现之前是弹菜单，现在改为一步直达）
- 使用 Windows 系统级 `RegisterHotKey` API，全屏游戏 / 全屏应用中也响应
- 支持修饰键：`Ctrl` / `Shift` / `Alt` / `Win`
- 留空即禁用；多设备下每盏灯**必须使用不同的按键组合**（系统级独占）

## 🎯 使用方法

**首次多灯配置**：
1. 打开 **设置**
2. 点击 **云端导入** → 扫码登录 → 勾选多盏灯 → **确认导入**
3. 每盏灯点 **编辑** 分别配置显示 / 电源策略 / 快捷键
4. 保存后立即生效，无需重启

**升级用户**：直接替换 EXE 即可，旧配置自动迁移到多设备格式，原有那盏灯的所有设置完整保留。

## 🐛 修复

- **设置页"检查更新"按钮之前只跳浏览器** — 现在走完整的托盘菜单同款流程（含"已是最新版本"弹窗、缓存更新、菜单刷新徽标）
- **快捷键在 v1.4 多设备重构初期不生效** — 恢复了 v1.4.3 的按键捕获实现（`event.state` 位掩码解析 + 特殊键 keysym 映射），并接到每设备 hotkey_manager 上
- **`_on_config_saved` 保存后重建的灯回调签名不匹配** — 参数从 `(state)` 修正为 `(state, device_id)`，之前保存配置后新加的灯状态推送会静默失败
- **弹窗遗留的 `self._light` 引用** — 多设备重构后未设置的旧字段，色温 clamp 时会 `AttributeError`，本版清理并改由每设备 section 自持 light 引用

## 🔧 工作原理

- **多设备状态管理**：`App._lights: dict[str, MiMonitorLight]` 以 `DeviceConfig.id` 为键；每盏灯的状态回调通过 lambda 闭包传递 `device_id`，路由到对应的弹窗 section
- **配置迁移**：`AppConfig.load()` 检测到 `data` 里存在 `device` 但没有 `devices` 时，把它包成 `[single_dev]` 并补齐 `id` 字段
- **每设备 Debouncer**：`FlyoutWindow._brightness_debouncers` / `_color_temp_debouncers` 是 dict[device_id, Debouncer]，按需惰性创建，滑动一盏灯的滑杆只会打包这盏灯的请求
- **快捷键 ID 分配**：`_setup_hotkeys()` 从 1 开始给每个 `(device, action)` 分配一个 Windows RegisterHotKey ID，callbacks 表按 ID 索引回具体的灯与动作
- **弹窗高度自适应**：`_position` 里先设 `WIDTH x 100` 让内容按新宽度重排，再 `update_idletasks()` 后读 `winfo_reqheight()`，最终 geometry 用真实高度定位

## 📁 结构变化

- 新增 [device_list_wizard.py](mi_monitor_light_tray/device_list_wizard.py) — 设备列表管理器
- 新增 [device_editor.py](mi_monitor_light_tray/device_editor.py) — 单设备编辑对话框
- 新增 [hotkey_manager.py](mi_monitor_light_tray/hotkey_manager.py) — 全局快捷键注册器（拆自旧 `__main__.py`）
- 大幅重写 [flyout.py](mi_monitor_light_tray/flyout.py) — 引入 `_DeviceSection`，弹窗按设备重复渲染
- 大幅重写 [__main__.py](mi_monitor_light_tray/__main__.py) — `_light` → `_lights` dict，所有系统事件回调改为遍历设备
- [config.py](mi_monitor_light_tray/config.py) — `AppConfig.device` → `devices: list[DeviceConfig]`，`DeviceConfig` 新增 `id`、`brightness_up/down`、`color_temp_up/down`、`hotkey_step`、`show_brightness`、`show_color_temp` 字段

## ⚠️ 已知限制

- **桌面小部件仍为单设备** — 只显示配置里第一盏灯的滑杆，多设备场景请用托盘弹窗或快捷键；小部件多设备版本在计划中
- **托盘右键菜单里的 5 个电源策略开关是"任一为真视为开"的聚合视图** — 想逐灯精确设置，请到 **设置 → 编辑设备** 里对每盏灯单独勾选
- **顶层 `hotkey` 段被废弃** — 保留在配置里只是为了让旧文件仍能被读取，v1.5+ 使用每设备快捷键

---

感谢所有反馈和建议！如有问题请在 [Issues](https://github.com/Martlnez/MiMonitorLightTray/issues) 提出。

**Full Changelog**: https://github.com/Martlnez/MiMonitorLightTray/compare/v1.4.3...v1.5.0
