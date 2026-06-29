"""桌面小部件 - 固定在桌面上的灯光控制面板。"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from .miio_client import Debouncer, LightState, MiMonitorLight

log = logging.getLogger(__name__)


class DesktopWidget:
    """桌面小部件 - 固定在桌面上的灯光控制面板。"""

    def __init__(
        self,
        light: MiMonitorLight,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        """初始化桌面小部件。

        Args:
            light: 灯光控制客户端
            on_close: 关闭回调
        """
        self._light = light
        self._on_close = on_close
        self._visible = False

        # 创建主窗口
        self._root = tk.Tk()
        self._root.title("灯光控制")
        self._root.resizable(False, False)
        self._root.configure(bg="#1f1f1f")
        self._root.attributes("-topmost", True)  # 始终在最前面
        self._root.overrideredirect(True)  # 无边框窗口

        # 窗口关闭时清理
        self._root.protocol("WM_DELETE_WINDOW", self._hide)

        # 初始化状态
        self._brightness_var = tk.IntVar(value=50)
        self._color_temp_var = tk.IntVar(value=4000)
        self._power_var = tk.BooleanVar(value=False)

        # 防抖器
        self._brightness_debouncer = Debouncer(delay=0.12)
        self._color_temp_debouncer = Debouncer(delay=0.18)

        # 绑定变量变化
        self._brightness_var.trace_add("write", self._on_brightness_change)
        self._color_temp_var.trace_add("write", self._on_color_temp_change)

        # 初始化 UI
        self._build_ui()

        # 初始隐藏
        self._root.withdraw()

    def _build_ui(self) -> None:
        """构建 UI。"""
        # 主框架
        main_frame = tk.Frame(self._root, bg="#1f1f1f", padx=16, pady=12)
        main_frame.pack(fill="both", expand=True)

        # 标题栏
        title_frame = tk.Frame(main_frame, bg="#1f1f1f")
        title_frame.pack(fill="x", pady=(0, 12))

        title_label = tk.Label(
            title_frame,
            text="灯光控制",
            font=("Microsoft YaHei UI", 11, "bold"),
            fg="#ffffff",
            bg="#1f1f1f",
        )
        title_label.pack(side="left")

        # 关闭按钮
        close_btn = tk.Button(
            title_frame,
            text="×",
            font=("Microsoft YaHei UI", 12),
            fg="#ffffff",
            bg="#1f1f1f",
            relief="flat",
            command=self._hide,
            width=2,
        )
        close_btn.pack(side="right")

        # 电源开关
        power_frame = tk.Frame(main_frame, bg="#1f1f1f")
        power_frame.pack(fill="x", pady=(0, 12))

        self._power_btn = tk.Button(
            power_frame,
            text="⏻",
            font=("Segoe UI Emoji", 16),
            fg="#ffffff",
            bg="#1f1f1f",
            relief="flat",
            command=self._toggle_power,
            width=3,
        )
        self._power_btn.pack(side="left")

        self._power_label = tk.Label(
            power_frame,
            text="关闭",
            font=("Microsoft YaHei UI", 10),
            fg="#888888",
            bg="#1f1f1f",
        )
        self._power_label.pack(side="left", padx=(8, 0))

        # 亮度控制
        brightness_frame = tk.Frame(main_frame, bg="#1f1f1f")
        brightness_frame.pack(fill="x", pady=(0, 8))

        brightness_icon = tk.Label(
            brightness_frame,
            text="☀",
            font=("Segoe UI Emoji", 12),
            fg="#ffffff",
            bg="#1f1f1f",
        )
        brightness_icon.pack(side="left")

        self._brightness_slider = tk.Scale(
            brightness_frame,
            from_=1,
            to=100,
            orient="horizontal",
            variable=self._brightness_var,
            bg="#1f1f1f",
            fg="#ffffff",
            highlightthickness=0,
            troughcolor="#3d3d3d",
            activebackground="#60cdff",
            sliderrelief="flat",
            length=180,
        )
        self._brightness_slider.pack(side="left", padx=(8, 0), fill="x", expand=True)

        self._brightness_label = tk.Label(
            brightness_frame,
            text="50%",
            font=("Microsoft YaHei UI", 10),
            fg="#ffffff",
            bg="#1f1f1f",
            width=4,
        )
        self._brightness_label.pack(side="right")

        # 色温控制
        color_temp_frame = tk.Frame(main_frame, bg="#1f1f1f")
        color_temp_frame.pack(fill="x")

        color_temp_icon = tk.Label(
            color_temp_frame,
            text="🌡",
            font=("Segoe UI Emoji", 12),
            fg="#ffffff",
            bg="#1f1f1f",
        )
        color_temp_icon.pack(side="left")

        self._color_temp_slider = tk.Scale(
            color_temp_frame,
            from_=2700,
            to=6500,
            orient="horizontal",
            variable=self._color_temp_var,
            bg="#1f1f1f",
            fg="#ffffff",
            highlightthickness=0,
            troughcolor="#3d3d3d",
            activebackground="#60cdff",
            sliderrelief="flat",
            length=180,
        )
        self._color_temp_slider.pack(side="left", padx=(8, 0), fill="x", expand=True)

        self._color_temp_label = tk.Label(
            color_temp_frame,
            text="4000K",
            font=("Microsoft YaHei UI", 10),
            fg="#ffffff",
            bg="#1f1f1f",
            width=6,
        )
        self._color_temp_label.pack(side="right")

    def _on_brightness_change(self, *_args) -> None:
        """亮度变化事件。"""
        value = self._brightness_var.get()
        self._brightness_label.configure(text=f"{value}%")
        self._brightness_debouncer.call(self._set_brightness, value)

    def _on_color_temp_change(self, *_args) -> None:
        """色温变化事件。"""
        value = self._color_temp_var.get()
        self._color_temp_label.configure(text=f"{value}K")
        self._color_temp_debouncer.call(self._set_color_temp, value)

    def _set_brightness(self, value: int) -> None:
        """设置亮度。"""
        try:
            self._light.set_brightness(value)
        except Exception as e:
            log.warning("设置亮度失败: %s", e)

    def _set_color_temp(self, value: int) -> None:
        """设置色温。"""
        try:
            self._light.set_color_temp(value)
        except Exception as e:
            log.warning("设置色温失败: %s", e)

    def _toggle_power(self) -> None:
        """切换电源状态。"""
        try:
            self._light.toggle()
            self._update_power_state()
        except Exception as e:
            log.warning("切换电源状态失败: %s", e)

    def _update_power_state(self) -> None:
        """更新电源状态显示。"""
        try:
            state = self._light.state
            if state and state.is_on:
                self._power_label.configure(text="开启", fg="#60cdff")
                self._power_btn.configure(fg="#60cdff")
            else:
                self._power_label.configure(text="关闭", fg="#888888")
                self._power_btn.configure(fg="#ffffff")
        except Exception as e:
            log.warning("获取电源状态失败: %s", e)

    def show(self) -> None:
        """显示小部件。"""
        if not self._visible:
            self._visible = True
            self._root.deiconify()
            self._update_power_state()
            # 居中显示在屏幕右下角
            self._position_widget()

    def _hide(self) -> None:
        """隐藏小部件。"""
        if self._visible:
            self._visible = False
            self._root.withdraw()

    def _position_widget(self) -> None:
        """将小部件定位在屏幕右下角。"""
        self._root.update_idletasks()
        width = self._root.winfo_width()
        height = self._root.winfo_height()
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()
        x = screen_width - width - 20
        y = screen_height - height - 60
        self._root.geometry(f"+{x}+{y}")

    def toggle_visibility(self) -> None:
        """切换小部件可见性。"""
        if self._visible:
            self._hide()
        else:
            self.show()

    def destroy(self) -> None:
        """销毁小部件。"""
        try:
            self._root.destroy()
        except Exception:
            pass
