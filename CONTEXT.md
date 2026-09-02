# MiMonitorLightTray Context

单上下文仓库。本仓库是 Windows 托盘程序，用于控制小米/Yeelight 智能显示器挂灯：按电源事件（显示器休眠、系统挂起/唤醒）自动开关灯，并通过托盘菜单、弹出面板、全局热键手动控制多台设备。

## Language

**设备 (Device)**:
一台受控的智能显示器挂灯或台灯，有独立 IP/Token/型号。`DeviceConfig` 对应。
_Avoid_: 灯 (light)、节点 (node)

**协议 (Protocol)**:
设备与应用层通信的两种方式——旧式 Yeelight（字符串属性）与 MIoT（`(siid,piid)` 属性寻址）。由型号决定，`_Backend` 抽象隐藏差异。
_Avoid_: 通信方式、驱动

**可达 (reachable)**:
最后一次 refresh / set_* 是否真的收到设备回复。决定 UI 是否显示「离线」。
_Avoid_: 在线 (online)、连接

**缓存状态 (cached state)**:
`MiMonitorLight.state` 保存的本地副本，不保证与设备真实状态一致。UI 先展示它再后台刷新校正。
_Avoid_: 状态、真实状态

**回复 (response)**:
设备对底层 miio 指令的成功返回，是「可达」的唯一依据。

**显示器休眠 (monitor sleep/off)**:
Windows 显示器进入待机/熄灭。触发 per-device `power_off_on_monitor_sleep`。

**系统挂起/恢复 (system suspend/resume)**:
Windows 整机 sleep/hibernate/wakeup。挂起触发关灯，恢复触发开灯（对托管设备）并对全部设备刷新。
_Avoid_: 睡眠、唤醒

**恢复刷新 (resume refresh)**:
系统恢复后按 t+0s/+3s/+8s 发三轮 refresh，覆盖网卡/扩展坞晚就绪。对**所有**设备，不仅是托管设备。

**新面板 (Flyout)**:
点击托盘图标弹出的 Tk 窗口，分设备展示状态与亮度/色温滑杆。
_Avoid_: 弹窗、面板 (panel)、弹层

**托盘 (Tray)**:
Windows 系统托盘的常驻图标与菜单。
_Avoid_: 系统栏、通知区

**热键 (Hotkey)**:
全局键盘快捷键，按设备路由亮度/色温增减。

**总开关 (master power)**:
Flyout 底部一键全开/全关所有设备。任意一台亮 → 全关；否则全开。
_Avoid_: 主开关、聚合开关

**活动设备 (active device)**:
UI 聚焦操作的设备 id，特殊值 `ALL` 表示全部。

**回退后端 (backend)**:
按型号为某协议抽象出的统一接口（Legacy Yeelight / MIoT），对外暴露一致的 on/off/refresh/brightness/color-temp。

**型号 (model)**:
设备运行时上报的型号 id（如 `yeelink.light.lamp22`），决定协议选择与色温范围。
_Avoid_: 版本、固件

**色温范围 (color-temp range)**:
某型号支持的色温最小/最大值（开尔文），用于 clamp 滑杆初始值与拖动。
_Avoid_: 色温、温度范围