"""桌面小部件 - 固定在桌面上的灯光控制面板。"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from typing import Callable, Optional

from .miio_client import Debouncer, LightState, MiMonitorLight

log = logging.getLogger(__name__)


class _DarkSlider(tk.Canvas):
    """Canvas-based horizontal slider with full dark-mode color control."""

    TRACK_H  = 4
    THUMB_R  = 8
    TRACK_BG = "#3d3d3d"
    TRACK_FG = "#60cdff"
    THUMB_BG = "#60cdff"
    THUMB_HOV= "#9de4ff"

    def __init__(self, parent, from_: int, to: int,
                 variable: tk.IntVar,
                 command: Callable[[str], None],
                 bg: str = "#1f1f1f",
                 **kw) -> None:
        super().__init__(parent, bg=bg, highlightthickness=0,
                         height=20, cursor="hand2", **kw)
        self._from = from_
        self._to   = to
        self._var  = variable
        self._cmd  = command
        self._drag = False

        self._var.trace_add("write", self._redraw)
        self.bind("<Configure>",      self._redraw)
        self.bind("<ButtonPress-1>",  self._on_press)
        self.bind("<B1-Motion>",      self._on_drag)
        self.bind("<ButtonRelease-1>",self._on_release)
        self.bind("<MouseWheel>",     self._on_wheel)
        self.bind("<Enter>",          lambda _: self._redraw(hover=True))
        self.bind("<Leave>",          lambda _: self._redraw(hover=False))
        self._hover = False

    def _frac(self) -> float:
        return (self._var.get() - self._from) / max(1, self._to - self._from)

    def _thumb_x(self) -> int:
        w = self.winfo_width()
        r = self.THUMB_R
        return int(r + self._frac() * (w - 2 * r))

    def _draw_circle(self, cx: int, cy: int, r: int, color: str) -> None:
        """Draw an anti-aliased-looking circle using a smooth polygon."""
        import math
        n = 32
        pts = []
        for i in range(n):
            a = 2 * math.pi * i / n
            pts.extend([cx + r * math.cos(a), cy + r * math.sin(a)])
        self.create_polygon(pts, fill=color, outline="", smooth=True)

    def _redraw(self, *_, hover: Optional[bool] = None) -> None:
        if hover is not None:
            self._hover = hover
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2:
            return
        cy = h // 2
        r  = self.THUMB_R
        tx = self._thumb_x()

        # Track background
        self.create_rounded_rect(r, cy - self.TRACK_H // 2,
                                  w - r, cy + self.TRACK_H // 2,
                                  2, fill=self.TRACK_BG)
        # Track fill (filled portion)
        if tx > r:
            self.create_rounded_rect(r, cy - self.TRACK_H // 2,
                                      tx, cy + self.TRACK_H // 2,
                                      2, fill=self.TRACK_FG)
        # Thumb — smooth polygon circle (no jagged edges)
        col = self.THUMB_HOV if self._hover else self.THUMB_BG
        self._draw_circle(tx, cy, r, col)

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kw):
        r = min(r, (x2 - x1) // 2, (y2 - y1) // 2)
        self.create_polygon(
            x1 + r, y1,  x2 - r, y1,
            x2, y1,      x2, y1 + r,
            x2, y2 - r,  x2, y2,
            x2 - r, y2,  x1 + r, y2,
            x1, y2,      x1, y2 - r,
            x1, y1 + r,  x1, y1,
            smooth=True, **kw)

    def _px_to_val(self, x: int) -> int:
        w = self.winfo_width()
        r = self.THUMB_R
        frac = max(0.0, min(1.0, (x - r) / max(1, w - 2 * r)))
        return int(self._from + frac * (self._to - self._from))

    def _on_press(self, e: tk.Event) -> None:
        self._drag = True
        self._set(self._px_to_val(e.x))

    def _on_drag(self, e: tk.Event) -> None:
        if self._drag:
            self._set(self._px_to_val(e.x))

    def _on_release(self, _e: tk.Event) -> None:
        self._drag = False

    def _on_wheel(self, e: tk.Event) -> None:
        step = 1 if e.delta > 0 else -1
        self._set(max(self._from, min(self._to, self._var.get() + step)))

    def set_range(self, from_: int, to_: int) -> None:
        """Update the slider's bounds and re-clamp the current value into them."""
        if from_ == self._from and to_ == self._to:
            return
        self._from = from_
        self._to = to_
        current = self._var.get()
        clamped = max(from_, min(to_, current))
        if clamped != current:
            self._var.set(clamped)
        self._redraw()

    def _set(self, val: int) -> None:
        self._var.set(val)
        self._cmd(str(val))
        self._redraw()


class DesktopWidget:
    """桌面小部件 - 固定在桌面上的灯光控制面板。"""

    WIDTH = 320
    PAD_X = 12
    PAD_Y = 10

    BG     = "#1f1f1f"
    TEXT   = "#ffffff"
    MUTED  = "#8a8a8a"
    ACCENT = "#60cdff"

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
        self._suppress = False

        # 创建主窗口
        self._root = tk.Toplevel()
        self._root.title("灯光控制")
        self._root.resizable(False, False)
        self._root.configure(bg=self.BG)
        self._root.attributes("-topmost", True)  # 始终在最前面
        self._root.attributes("-toolwindow", True)  # 不在任务栏显示

        # 窗口关闭时清理
        self._root.protocol("WM_DELETE_WINDOW", self._hide)

        # 防抖器
        self._brightness_debouncer = Debouncer(delay=0.12)
        self._color_temp_debouncer = Debouncer(delay=0.18)

        # 初始化状态
        self._brightness_var = tk.IntVar(value=50)
        self._color_temp_var = tk.IntVar(value=4000)

        # 初始化 UI
        self._build_ui()

        # 初始隐藏
        self._root.withdraw()

    def _build_ui(self) -> None:
        """构建 UI。"""
        outer = tk.Frame(self._root, bg=self.BG)
        outer.pack(fill="x", padx=self.PAD_X, pady=(self.PAD_Y, 0))

        self._build_row(outer, "☀", "亮度",
                        self._brightness_var,
                        MiMonitorLight.BRIGHTNESS_MIN,
                        MiMonitorLight.BRIGHTNESS_MAX,
                        "", self._on_brightness)

        self._build_row(outer, "🌡", "色温",
                        self._color_temp_var,
                        self._light.color_temp_min,
                        self._light.color_temp_max,
                        "K", self._on_color_temp)

        # ── Footer ───────────────────────────────────────────────────────────
        tk.Frame(self._root, height=1, bg="#2e2e2e").pack(fill="x")
        footer = tk.Frame(self._root, bg=self.BG)
        footer.pack(fill="x", padx=self.PAD_X, pady=(4, 6))

        self._status_var = tk.StringVar(value="调整亮度")
        tk.Label(footer, textvariable=self._status_var,
                 fg=self.MUTED, bg=self.BG,
                 font=("Segoe UI", 9)).pack(side="left")

        for glyph, cmd in reversed([
            ("⏻", self._on_toggle_power),
        ]):
            self._icon_btn(footer, glyph, cmd)

    def _build_row(self, parent, icon: str, label: str,
                   var: tk.IntVar, from_: int, to: int,
                   unit: str, cmd: Callable) -> None:
        row = tk.Frame(parent, bg=self.BG)
        row.pack(fill="x", pady=(0, 8))

        top = tk.Frame(row, bg=self.BG)
        top.pack(fill="x")
        tk.Label(top, text=icon, fg=self.MUTED, bg=self.BG,
                 font=("Segoe MDL2 Assets", 12)).pack(side="left", padx=(0, 6))
        tk.Label(top, text=label, fg=self.TEXT, bg=self.BG,
                 font=("Microsoft YaHei UI", 10),
                 anchor="w").pack(side="left")

        bot = tk.Frame(row, bg=self.BG)
        bot.pack(fill="x", pady=(4, 0))

        val_var = tk.StringVar(value="--")
        tk.Label(bot, textvariable=val_var, fg=self.TEXT, bg=self.BG,
                 font=("Segoe UI Variable Display", 14, "bold"),
                 width=5, anchor="e").pack(side="right")

        slider = _DarkSlider(bot, from_=from_, to=to,
                             variable=var, command=cmd, bg=self.BG)
        slider.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def _sync(*_, _v=var, _vv=val_var, _u=unit):
            _vv.set(f"{int(_v.get())}{_u}")
        var.trace_add("write", _sync)
        _sync()

        if unit == "":
            self._brightness_slider = slider
        else:
            self._color_temp_slider = slider

    def _icon_btn(self, parent, glyph: str, cmd: Callable) -> None:
        btn = tk.Label(parent, text=glyph, fg=self.MUTED, bg=self.BG,
                       font=("Segoe UI Symbol", 14),
                       padx=6, cursor="hand2")
        btn.pack(side="right")
        btn.bind("<Button-1>", lambda _: cmd())
        btn.bind("<Enter>",    lambda _: btn.configure(fg=self.TEXT))
        btn.bind("<Leave>",    lambda _: btn.configure(fg=self.MUTED))

    def _on_brightness(self, v: str) -> None:
        """亮度变化事件。"""
        if self._suppress:
            return
        self._brightness_debouncer.call(
            self._light.set_brightness, int(float(v)))

    def _on_color_temp(self, v: str) -> None:
        """色温变化事件。"""
        if self._suppress:
            return
        self._color_temp_debouncer.call(
            self._light.set_color_temp, int(float(v)))

    def _on_toggle_power(self) -> None:
        """切换电源状态。"""
        threading.Thread(target=self._toggle_thread, daemon=True).start()

    def _toggle_thread(self) -> None:
        """切换电源状态线程。"""
        try:
            new_state = self._light.toggle()
            self._root.after(0, lambda: self._update_power_state(new_state))
        except Exception as e:
            log.warning("切换电源状态失败: %s", e)

    def _update_power_state(self, is_on: bool) -> None:
        """更新电源状态显示。"""
        if is_on:
            self._status_var.set("已开灯")
        else:
            self._status_var.set("已关灯")

    def _apply_state(self, state: LightState) -> None:
        """应用灯光状态。"""
        self._suppress = True
        try:
            b = max(MiMonitorLight.BRIGHTNESS_MIN,
                    state.brightness or MiMonitorLight.BRIGHTNESS_MIN)
            self._brightness_var.set(b)
            ct = state.color_temp or 4000
            ct = max(self._light.color_temp_min,
                     min(self._light.color_temp_max, ct))
            self._color_temp_var.set(ct)
        finally:
            self._suppress = False

        if state.reachable:
            self._status_var.set("已开灯" if state.is_on else "已关灯")
        else:
            self._status_var.set(f"离线 — {(state.error or '')[:40]}")

    def show(self) -> None:
        """显示小部件。"""
        if not self._visible:
            self._visible = True
            self._root.deiconify()
            self._position_widget()
            # 刷新状态
            threading.Thread(target=self._bg_refresh, daemon=True).start()

    def _hide(self) -> None:
        """隐藏小部件。"""
        if self._visible:
            self._visible = False
            self._root.withdraw()

    def _position_widget(self) -> None:
        """将小部件定位在屏幕右下角。"""
        self._root.update_idletasks()
        width = self.WIDTH
        height = self._root.winfo_reqheight()
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()
        x = screen_width - width - 20
        y = screen_height - height - 60
        self._root.geometry(f"{width}x{height}+{x}+{y}")

    def _bg_refresh(self) -> None:
        """后台刷新状态。"""
        try:
            state = self._light.refresh()
            self._root.after(0, lambda: self._apply_state(state))
        except Exception as e:
            log.warning("刷新状态失败: %s", e)

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
