# v1.4.3

## ✨ 新功能

- **灯随显示器休眠开关** - 显示器休眠时自动关灯，唤醒时自动恢复灯光状态
  - 可在设置窗口中配置
  - 可在托盘右键菜单中快速开关
  - 完全依赖 Windows 显示器电源广播（`GUID_CONSOLE_DISPLAY_STATE`），与 Windows 自身的显示器关闭时机保持一致
  - 智能记忆休眠前的灯光状态，唤醒时自动恢复

- **系统休眠时关灯** - 系统进入睡眠/休眠时自动关灯
  - 可在设置窗口中配置
  - 可在托盘右键菜单中快速开关
  - 监听 Windows 电源广播消息 `PBT_APMSUSPEND`

- **系统唤醒时开灯** - 系统从睡眠/休眠唤醒时自动开灯
  - 可在设置窗口中配置
  - 可在托盘右键菜单中快速开关
  - 监听 Windows 电源广播消息 `PBT_APMRESUMEAUTOMATIC` / `PBT_APMRESUMESUSPEND`

**三个独立开关，可根据需要自由组合使用**

## 🎯 使用方法

1. 右键托盘图标 → 勾选需要的开关
2. 或在「设置」窗口中勾选对应选项

**灯随显示器休眠开关：**
- Windows 关闭显示器时，灯会自动关闭
- Windows 唤醒显示器时，灯会自动恢复到关闭前的状态

**系统休眠时关灯：**
- 电脑进入睡眠/休眠时，灯会自动关闭

**系统唤醒时开灯：**
- 电脑从睡眠/休眠恢复时，灯会自动打开

## 🔧 工作原理

**显示器休眠检测：**
- 使用顶级窗口注册 `RegisterPowerSettingNotification`，订阅 `GUID_CONSOLE_DISPLAY_STATE`
- 显示器状态 = OFF (0) → 触发关灯
- 显示器状态 = ON (1) → 触发开灯
- 显示器状态 = DIMMED (2) → 忽略（显示器仍处于开启状态）
- **完全不做自己的空闲计时**，避免播放视频等长时间无输入但显示器仍开启的场景被误判

**系统休眠检测：**
- 同一个顶级窗口接收 `WM_POWERBROADCAST` 广播（消息窗口收不到系统广播事件）
- 系统休眠事件（`PBT_APMSUSPEND`）→ 触发关灯（如启用）
- 系统恢复事件（`PBT_APMRESUMEAUTOMATIC` / `PBT_APMRESUMESUSPEND`）→ 触发开灯（如启用）

## 🐛 修复

- 修正之前版本使用的 `GUID_MONITOR_POWER_ON`（在 Windows 8 之后已废弃、不会被派发），改为正确的 `GUID_CONSOLE_DISPLAY_STATE`
- 移除基于 55 秒空闲判断的显示器休眠误报路径（播放视频不动鼠标时会被误关灯）
- 使用顶级窗口而非 `HWND_MESSAGE`，确保能收到系统级广播
- **修复 Modern Standby 系统（Win10/11 笔记本和部分台式机）不触发系统休眠事件的问题** — 调用 `RegisterSuspendResumeNotification` 显式订阅，而不依赖默认的顶级窗口广播（微软在支持 Modern Standby 的系统上已停止默认广播）
- 修复监听器重启时窗口类冲突导致回调失效的问题（每个实例使用唯一类名）
- 改进错误日志（启用 `use_last_error=True`，错误代码不再全是 0）
- 将 `WM_POWERBROADCAST` 日志从 DEBUG 提升到 INFO 级别，方便用户诊断事件是否触发

---

感谢所有反馈和建议！如有问题请在 [Issues](https://github.com/Martlnez/MiMonitorLightTray/issues) 提出。

**Full Changelog**: https://github.com/Martlnez/MiMonitorLightTray/compare/v1.4.2...v1.4.3
