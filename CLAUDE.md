# MiMonitorLightTray · CLAUDE 开发规范

> 本文档是 AI Agent 在本仓库中开发时必须遵循的统一规范。
> 新增或修改代码前先通读；与既有实现保持一致；不要凭感觉引入未在本项目使用过的设计模式或依赖。

---

## 1. 工程基本信息

- **语言**：Python 3.10+（CI matrix = 3.10 / 3.11 / 3.12，EXE 打包用 3.10，与本地 venv 保持一致）
- **入口**：`mi_monitor_light_tray.__main__:main()` / `scripts/run_app.py`（PyInstaller 打包入口）
- **打包**：PyInstaller 单文件 + `--noconsole`（Windows 托盘程序不能有黑窗）
- **配置位置**：`pyproject.toml` 的 `[project]` 段（版本号、依赖、唯一真源）
- **版本号唯一来源**：`pyproject.toml` → `version = "x.y.z"`。代码通过 `importlib.metadata.version("mi-monitor-light-tray")` 读取；不要在别处写死。
- **测试**：`pytest tests/ -q`
- **平台**：Windows only（大量用到 `ctypes.user32`、`WM_POWERBROADCAST`、pystray 在 Windows 上才有完整行为）。不要引入 Linux/macOS 独有的 API。

---

## 2. 目录结构速览

```
MiMonitorLightTray/
├── mi_monitor_light_tray/          # 主包
│   ├── __main__.py                 # App 类：装配 config / tray / flyout / 电源监听 / 热键 / 退出
│   ├── flyout.py                   # 托盘点击弹出的 Tk 窗口：多设备分节、滑杆、总开关
│   ├── tray.py                     # pystray 胶水：菜单、图标切换、点击坐标（cursor_pos）
│   ├── miio_client.py              # MiMonitorLight：封装 python-miio、状态对象、防抖、回调
│   ├── config.py                   # AppConfig / DeviceConfig：JSON 存储、迁移、热加载
│   ├── monitor_sleep_listener.py   # ⭐ WM_POWERBROADCAST 隐藏窗口：显/显示器状态、系统挂起/唤醒
│   ├── shutdown_listener.py        # WM_QUERYENDSESSION：OS 关机时同步关灯（比 atexit 稳）
│   ├── hotkey_manager.py           # 全局键盘热键（每设备路由）
│   ├── icon.py                     # make_tray_icon(size, on)：Pillow 动态生成 ico
│   ├── autostart.py                # 开机自启动（HKCU\...\Run 注册表项）
│   ├── single_instance.py          # Mutex 单实例
│   ├── version_checker.py          # GitHub Releases API 版本对比（importlib.metadata）
│   ├── setup_wizard.py             # 首次启动向导
│   ├── device_list_wizard.py       # 设置界面：多设备卡片 + 云端多选导入 + 拖拽排序
│   ├── device_editor.py            # 单设备编辑器：IP / Token / 电源策略 / 显示 / 热键
│   ├── cloud_login_window.py       # 小米云扫码 / 账密登录 → token 拉取
│   ├── discovery.py                # UDP 广播 + miio info() 反查 IP
│   ├── desktop_widget.py           # 桌面常驻小部件（仍为「配置里第一台」单设备）
│   ├── token_extractor/            # 小米 Cloud 端 token 提取子包
│   └── _miot_data.py               # 2100+ 机型的 MIoT 属性表（bulk 导入）
├── release-notes/
│   └── RELEASE_NOTES_vX.Y.Z.md     # 对应 tag 的发版说明（CI + gh CLI 会读）
├── docs/                           # GitHub Pages：index.html / guide.html / releases.html
├── scripts/
│   ├── build_exe.py                # PyInstaller 一键打包（--collect-data miio 重要！）
│   └── run_app.py                  # PyInstaller 入口文件
├── tests/                          # pytest：config / miio_client / types / cloud / auth / icon
├── .github/workflows/build.yml     # CI：test → build-exe → release（tag v* 触发）
└── pyproject.toml                  # 版本号 / 依赖 / optional-dependencies [build] [dev]
```

---

## 3. 核心架构约定（不要乱改）

### 3.1 线程模型
- **Tk 主循环在主线程**（`self._flyout.run()` 阻塞）。所有 UI 写入（`Label.configure` / `StringVar.set` / pystray `icon.icon = …`）**必须回到 Tk 线程**：
  - 跨线程：`flyout._root.after(0, lambda: ...)` 或 `schedule_apply_state` 这类已经封装好的方法
  - tray：`self._icon.icon = …` 在 tray 自己的线程调用是 OK 的（pystray 自身是线程安全的）
- **网络/阻塞操作一律走 `threading.Thread(target=…, daemon=True)` 单独线程**：`light.refresh()` / `set_power()` / `version_checker.check_async()` / 多设备并行刷新等。绝不能在 `after()` 回调里做 UDP send，否则卡 UI。
- 不要用 `asyncio`。整个项目是经典多线程模型，引入 async 会和 Tk / pystray 不兼容。

### 3.2 状态与监听
- `MiMonitorLight.state` 是「缓存」，不保证是真的；`state.reachable` 表示最后一次 refresh / set_* 是否真的收到回复。
- 每盏灯注册一个 `listener(state, device_id)` 回调（在 App.__init__ 里通过 `set_listener`），回调把状态转给 Flyout + Tray。任何修改灯状态的代码路径最后都要让这个链路触发，**不要直接跨模块改 UI 控件**。
- 缓存优先原则：UI 打开时先把 `light.state` 的值应用上去，再后台 `refresh()` 校正。不要硬编码 50 / 4000 等默认值。

### 3.3 电源事件（monitor_sleep_listener.py）
- 只有「**始终启动**」这一条 — 用户哪怕一个电源策略复选框都没勾，**监听器也必须常驻运行**，否则系统恢复后没人刷新。（v1.5.1 修复的核心 Bug）
- 回调内部再判断 per-device flags：
  - `power_off_on_monitor_sleep`：显示器 off → 关灯
  - `power_off_on_system_suspend`：系统 sleep/hibernate → 关灯
  - `power_on_on_system_resume`：系统 resume → 开灯（其余设备也必须 refresh！）
  - `power_on_at_startup` / `power_off_at_exit`：由 `App.run()` / `_run_shutdown_power_off()` 和 `ShutdownListener` 共同处理
- 系统恢复后要发 **三轮 refresh**（t+0s / +3s / +8s），覆盖 WiFi / 扩展坞网卡晚就绪。
- 显示器 on → 对**所有**设备 refresh，而不仅是托管设备。

### 3.4 Flyout 多设备约定
- 每设备渲染一个 `_DeviceSection`：设备名 label + 状态 StringVar + ⏻ + 亮度/色温滑杆（按 `show_brightness` / `show_color_temp`）
- 设备名截断规则：**> 34 字符**才截为 `[:32] + "…"`。不要固定 Label width=13，改成流式布局。
- 亮度 / 色温初始值必须来自 `light.state.brightness` / `light.state.color_temp`，并 clamp 到 `[BRIGHTNESS_MIN, BRIGHTNESS_MAX]` / `[color_temp_min, color_temp_max]`。
- 状态标签在 unreachable 时**保留最后已知开关状态**后加 `(离线)`，不要只显示「离线」两字。
- 底部 ⏻ 总开关：双向 toggle。`any(l.state.is_on for l in lights)` → 有任意亮 → 点击=全关；否则 → 点击=全开。
- 总开关**不要跳过 cached unreachable 的设备**。恢复后 unreachable 标记往往只是还没刷新，不是真的控制不了。
- 每设备独立防抖器（`_suppress`）。

---

## 4. 编码风格

- **类型注解**：所有公开 `def` / 类字段写 `from __future__ import annotations` 风格的类型注解。
- **日志**：`logging.getLogger(__name__)`。不要 `print`。关键事件（电源切换、刷新轮次、配置保存失败）用 INFO/WARNING；异常捕获里用 `log.exception("...")` 记录堆栈。
- **异常安全**：所有来自工作线程、窗口过程、Tk 回调的外层 try/except 都写 `except Exception:  # noqa: BLE001` + `log.exception(...)`。吞异常但必须留痕。
- **Lambda 闭包陷阱**：循环内创建 `threading.Thread(target=lambda: light.xxx())` **必须用默认参数**绑循环变量：`lambda l=light: l.set_power(True)`。否则全绑定到最后一个变量！
- 字符串：中文文案统一中文（"已开灯/离线/显示器唤醒刷新全部设备…"），不要中英混装成 "Device offline"。
- 不要新增第三方依赖。所有改动尽量在 python-miio / pystray / Pillow / tkinter + 标准库范围内解决。必须加依赖时：写进 pyproject.toml，并同步在 build.yml 的 pip install 命令里会被覆盖（因为 `pip install -e ".[build]"` 会读 pyproject，所以只要放进去就够了）。

---

## 5. 提交流程

### 5.1 每条 commit 保持一个功能 / 一次修复
> 用户明确要求：每次提交尽量只提交一个功能的更新或修复。
- 好的：`fix: resume refresh always fires even with 0 power flags enabled`
- 好的：`feat: slider initial value from cached state`
- 坏的：`update everything`（把修复、版本号、release notes、workflow 一次性全塞一个 commit）
- **例外**：一个完整 release 需要 bump version + release notes + docs，这些可以跟一个 `release: vX.Y.Z - xxx` 大 commit，但 workflow 之类的工程化改动要单独 commit（就像 v1.5.1 时 `chore(ci): release notes auto-read md` 单独一个）。

### 5.2 提交信息格式
使用 Conventional Commits 风格（跟现有历史一致）：
```
release:   v1.5.1 - 休眠恢复自动刷新 & Flyout 体验优化
feat:      显示器点亮时刷新全部设备
fix:       MonitorSleepListener 无论复选框与否始终启动
refactor:  移除 first_light 引用链
chore(ci): release job auto-read md
docs:      v1.5.1 release notes + releases.html 置顶
```

### 5.3 编译（本地出 EXE 给用户测试）
```powershell
cd C:\tool\MiMonitorLightTray
.venv\Scripts\python.exe scripts\build_exe.py     # 产出 dist\MiMonitorLightTray.exe
```
- **版本号**：修改 `pyproject.toml` 的 `version`（唯一真源）。测试编译可暂不改版本；仅发版时才 bump。
- 首次装 PyInstaller（若 .venv 里没有）：`.venv\Scripts\python.exe -m pip install -e ".[build]"`
- `build_exe.py` 第一步会跑 `pip install -e . --no-deps` 同步版本号 metadata（装进 .venv，不会碰全局环境）。

---

## 6. 发版流程（严格按 v1.5.1 模式执行）

### 6.1 前提
- 所有功能改动已 commit + push 到 `main` 并通过 CI
- 已在本地编译 EXE 并交给用户测试 OK（「修复完成进行编译 我手动测试」这一步必须有）

### 6.2 步骤（顺序执行，不要跳步）

1. **bump 版本号**：`pyproject.toml` → `version = "X.Y.Z"`
   - 补丁修复：`Z + 1`（1.5.0 → 1.5.1）
   - 新功能较多但兼容：`Y + 1`（1.5.1 → 1.6.0）
   - 架构重构：`X + 1`（2.0.0）

2. **写发版说明 md**：`release-notes/RELEASE_NOTES_vX.Y.Z.md`
   - 开头标题 `# vX.Y.Z`，一两句总结
   - 大段按 emoji 分章：🐛 修复 / ✨ 新功能 / ⚠️ 注意事项 / 🧹 其它 / 对比
   - 末尾附 Compare：`https://github.com/Martlnez/MiMonitorLightTray/compare/v{prev}...v{X.Y.Z}`
   - 中文撰写，与 releases.html 文档站对应章节内容保持一致

3. **更新 docs/releases.html**
   - 在 `<article class="release release-latest">` 位置插入新版本作为「● 当前版本」的第一张卡片
   - 旧的 release-latest 卡片降级为普通 `<article class="release">`，其 release-tag 改成灰色 tertiary 背景
   - 每张卡片按钮四件套：下载 EXE（latest）/ GitHub Release / Compare / Markdown 原文

4. **commit 提交一个 release 大 commit**：
   - 包含：pyproject.toml / 所有 source code 修复 / release-notes md / docs/releases.html
   - 标题格式：`release: vX.Y.Z - 一句话主题`

5. **打 annotated tag 并 push**：
   ```powershell
   git tag -a vX.Y.Z -m "vX.Y.Z - 一句话主题"
   git push origin main --follow-tags
   ```
   - tag 必须是 `v` 前缀（build.yml 触发条件是 `tags: ["v*"]`）
   - 必须 annotated（`-a`），不要 lightweight

6. **CI 观察**：run 在 Actions 列表里有两个（main push + tag push）
   - 我们关心 tag 那条（`ref = refs/tags/vX.Y.Z`），它才会跑 `release` job
   - 流程：`test` (3× 版本) → `build-exe`（PyInstaller 5~10 分钟）→ `release`（上传 EXE + 创建 Release）

7. **替换 Release Body**（当前这步必须手动，因为当前 tag 用的是打 tag 前的 workflow yaml）：
   ```powershell
   gh release view vX.Y.Z                  # 等到存在为止（bodyLen ≈ 90 = auto-generate）
   gh release edit vX.Y.Z --notes-file release-notes/RELEASE_NOTES_vX.Y.Z.md
   ```
   - 校验：`gh release view vX.Y.Z --json assets,body,url` 看 assets 是否有 MiMonitorLightTray.exe、body 是否是 md 全文

8. **（可选但推荐）提交 workflow 未来发版改进**：如果发版流程里改了 build.yml，单独一个 `chore(ci): ...` commit 紧跟 push 到 main。下次发版会自动用。

### 6.3 验证清单
发版完成后逐一确认：
- [ ] `pyproject.toml` 的 version 与 tag 名一致
- [ ] GitHub Release URL：`https://github.com/Martlnez/MiMonitorLightTray/releases/tag/vX.Y.Z` 可打开
- [ ] Release 非 draft、附带 MiMonitorLightTray.exe
- [ ] Release body 是完整中文 md 不是 auto-generate 的"What's Changed"
- [ ] `docs/releases.html` 里最新卡片的标题是 `vX.Y.Z · xxx` 且带有「● 当前版本」蓝标
- [ ] Compare 链接是对的（diff 数量能对上）

---

## 7. 私有文件处理

> 用户明确要求：私有文档添加到 `.git/info/exclude`，不要污染 `.gitignore` 文件。

**规则：所有只在开发者本地有用、不需要全仓库共享的文件 → 写进 `.git/info/exclude`**


`.git/info/exclude` 与 `.gitignore` 语法相同、效果相同，**仅在本地生效**，不会通过 commit 传播给其他协作者。

> 确认是否生效：`git check-ignore -v CLAUDE.md` 若输出 `.git/info/exclude:xx:CLAUDE.md` 即成功。



*本规范随项目演进不断完善。新增约定请按章节归档，保持目录化结构。*

---

## Agent skills

### Issue tracker

Issues/specs 用 GitHub Issues 追踪，走 `gh` CLI。详见 [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md)。

### Triage labels

五个默认 triage 标签：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。详见 [docs/agents/triage-labels.md](docs/agents/triage-labels.md)。

### Domain docs

单上下文：仓库根一个 `CONTEXT.md` + `docs/adr/`。详见 [docs/agents/domain.md](docs/agents/domain.md)。
