"""Twinkle Tray-style flyout — one section per device, each with sliders."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from typing import Callable, Optional

from .miio_client import Debouncer, LightState, MiMonitorLight
from .config import AppConfig, DeviceConfig

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

        self.create_rounded_rect(r, cy - self.TRACK_H // 2,
                                  w - r, cy + self.TRACK_H // 2,
                                  2, fill=self.TRACK_BG)
        if tx > r:
            self.create_rounded_rect(r, cy - self.TRACK_H // 2,
                                      tx, cy + self.TRACK_H // 2,
                                      2, fill=self.TRACK_FG)
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

class _DeviceSection:
    """One visible device block: name label + optional brightness/color-temp rows."""

    BG    = "#1f1f1f"
    TEXT  = "#ffffff"
    MUTED = "#8a8a8a"

    def __init__(self, parent: tk.Widget, device: DeviceConfig,
                 light: MiMonitorLight,
                 on_brightness: Callable[[str, int], None],
                 on_color_temp: Callable[[str, int], None],
                 on_toggle: Callable[[str], None]) -> None:
        self._device = device
        self._light = light
        self._on_brightness = on_brightness
        self._on_color_temp = on_color_temp
        self._on_toggle = on_toggle
        self._suppress = False

        self.frame = tk.Frame(parent, bg=self.BG)

        # Header row: device name + status + power toggle (grid layout for fixed widths)
        header = tk.Frame(self.frame, bg=self.BG)
        header.pack(fill="x", pady=(0, 4))
        header.columnconfigure(0, weight=0)  # Device name, fixed max width
        header.columnconfigure(1, weight=1)  # Status, fills remaining space
        header.columnconfigure(2, weight=0)  # Power button, fixed

        # Truncate device name if too long (max 12 chars for Chinese, ~18 for ASCII mix)
        display_name = device.name or "未命名设备"
        if len(display_name) > 12:
            display_name = display_name[:11] + "..."

        tk.Label(header, text=display_name,
                 fg=self.TEXT, bg=self.BG,
                 font=("Microsoft YaHei UI", 10, "bold"),
                 anchor="w", width=13).grid(row=0, column=0, sticky="w")

        self._status_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self._status_var,
                 fg=self.MUTED, bg=self.BG,
                 font=("Microsoft YaHei UI", 9),
                 anchor="w").grid(row=0, column=1, sticky="w", padx=(8, 0))

        power_btn = tk.Label(header, text="⏻", fg=self.MUTED, bg=self.BG,
                             font=("Segoe UI Symbol", 13),
                             padx=6, cursor="hand2")
        power_btn.grid(row=0, column=2, sticky="e")
        power_btn.bind("<Button-1>", lambda _e: self._on_toggle(device.id))
        power_btn.bind("<Enter>", lambda _e: power_btn.configure(fg=self.TEXT))
        power_btn.bind("<Leave>", lambda _e: power_btn.configure(fg=self.MUTED))

        self._brightness_var: Optional[tk.IntVar] = None
        self._color_temp_var: Optional[tk.IntVar] = None
        self._brightness_slider: Optional[_DarkSlider] = None
        self._color_temp_slider: Optional[_DarkSlider] = None

        if device.show_brightness:
            self._brightness_var = tk.IntVar(value=50)
            self._brightness_slider = self._build_row(
                "亮度",
                self._brightness_var,
                MiMonitorLight.BRIGHTNESS_MIN,
                MiMonitorLight.BRIGHTNESS_MAX,
                "",
                lambda v: self._on_brightness(device.id, int(float(v))))

        if device.show_color_temp:
            self._color_temp_var = tk.IntVar(value=4000)
            self._color_temp_slider = self._build_row(
                "色温",
                self._color_temp_var,
                light.color_temp_min,
                light.color_temp_max,
                "K",
                lambda v: self._on_color_temp(device.id, int(float(v))))

    def _build_row(self, label: str, var: tk.IntVar, from_: int, to: int,
                   unit: str, cmd: Callable[[str], None]) -> _DarkSlider:
        row = tk.Frame(self.frame, bg=self.BG)
        row.pack(fill="x", pady=(0, 6))

        top = tk.Frame(row, bg=self.BG)
        top.pack(fill="x")
        tk.Label(top, text=label, fg=self.MUTED, bg=self.BG,
                 font=("Microsoft YaHei UI", 9),
                 anchor="w").pack(side="left")

        bot = tk.Frame(row, bg=self.BG)
        bot.pack(fill="x", pady=(2, 0))

        val_var = tk.StringVar(value="--")
        tk.Label(bot, textvariable=val_var, fg=self.TEXT, bg=self.BG,
                 font=("Segoe UI Variable Display", 12, "bold"),
                 width=6, anchor="e").pack(side="right")

        slider = _DarkSlider(bot, from_=from_, to=to,
                             variable=var,
                             command=lambda v, c=cmd: (None if self._suppress else c(v)),
                             bg=self.BG)
        slider.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def _sync(*_, _v=var, _vv=val_var, _u=unit):
            _vv.set(f"{int(_v.get())}{_u}")
        var.trace_add("write", _sync)
        _sync()
        return slider

    def apply_state(self, state: LightState) -> None:
        self._suppress = True
        try:
            if self._brightness_var is not None:
                b = max(MiMonitorLight.BRIGHTNESS_MIN,
                        state.brightness or MiMonitorLight.BRIGHTNESS_MIN)
                self._brightness_var.set(b)
            if self._color_temp_var is not None and self._color_temp_slider is not None:
                ct = state.color_temp or 4000
                ct = max(self._light.color_temp_min,
                         min(self._light.color_temp_max, ct))
                self._color_temp_var.set(ct)
        finally:
            self._suppress = False

        if state.reachable:
            self._status_var.set("已开灯" if state.is_on else "已关灯")
        else:
            err = (state.error or "")[:30]
            self._status_var.set(f"离线 — {err}" if err else "离线")

    def apply_ct_range(self, lo: int, hi: int) -> None:
        if self._color_temp_slider is None:
            return
        self._suppress = True
        try:
            self._color_temp_slider.set_range(lo, hi)
        finally:
            self._suppress = False


class FlyoutWindow:
    WIDTH    = 360
    PAD_X    = 12
    PAD_Y    = 10

    BG       = "#1f1f1f"
    TEXT     = "#ffffff"
    MUTED    = "#8a8a8a"

    def __init__(self, lights: dict[str, MiMonitorLight],
                 config: AppConfig,
                 on_open_setup: Callable[[], None]) -> None:
        self._lights        = lights
        self._config        = config
        self._on_open_setup = on_open_setup

        self._root = tk.Tk()
        self._root.withdraw()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.configure(bg=self.BG)
        try:
            self._root.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        self._brightness_debouncers: dict[str, Debouncer] = {}
        self._color_temp_debouncers: dict[str, Debouncer] = {}
        self._visible  = False
        self._sections: dict[str, _DeviceSection] = {}

        self._build_ui()
        self._root.bind("<FocusOut>", self._on_focus_out)
        self._root.bind("<Escape>",   lambda _e: self.hide())

    def _apply_rounded_corners(self) -> None:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetAncestor(self._root.winfo_id(), 2)
            val  = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(val), 4)
        except Exception:
            pass

    def _build_ui(self) -> None:
        self._container = tk.Frame(self._root, bg=self.BG)
        self._container.pack(fill="both", expand=True,
                             padx=self.PAD_X, pady=(self.PAD_Y, 0))

        self._devices_frame = tk.Frame(self._container, bg=self.BG)
        self._devices_frame.pack(fill="x")

        self._build_device_sections()

        # Footer: status label (left) + power-off-all button + settings button (right)
        tk.Frame(self._root, height=1, bg="#2e2e2e").pack(fill="x")
        footer = tk.Frame(self._root, bg=self.BG)
        footer.pack(fill="x", padx=self.PAD_X, pady=(4, 6))

        self._empty_var = tk.StringVar(value="")
        tk.Label(footer, textvariable=self._empty_var,
                 fg=self.MUTED, bg=self.BG,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")

        # Settings button (rightmost)
        settings_btn = tk.Label(footer, text="⚙", fg=self.MUTED, bg=self.BG,
                                font=("Segoe UI Symbol", 14),
                                padx=6, cursor="hand2")
        settings_btn.pack(side="right")
        settings_btn.bind("<Button-1>", lambda _e: self._open_settings())
        settings_btn.bind("<Enter>", lambda _e: settings_btn.configure(fg=self.TEXT))
        settings_btn.bind("<Leave>", lambda _e: settings_btn.configure(fg=self.MUTED))

        # Power-off-all button (left of settings)
        poweroff_all_btn = tk.Label(footer, text="⏻", fg=self.MUTED, bg=self.BG,
                                    font=("Segoe UI Symbol", 14),
                                    padx=6, cursor="hand2")
        poweroff_all_btn.pack(side="right")
        poweroff_all_btn.bind("<Button-1>", lambda _e: self._on_power_off_all())
        poweroff_all_btn.bind("<Enter>", lambda _e: poweroff_all_btn.configure(fg=self.TEXT))
        poweroff_all_btn.bind("<Leave>", lambda _e: poweroff_all_btn.configure(fg=self.MUTED))

    def _build_device_sections(self) -> None:
        """Build one section per device that has at least one control visible."""
        for w in self._devices_frame.winfo_children():
            w.destroy()
        self._sections.clear()

        visible = [d for d in self._config.devices
                   if d.id in self._lights and (d.show_brightness or d.show_color_temp)]

        for idx, dev in enumerate(visible):
            light = self._lights[dev.id]
            section = _DeviceSection(
                self._devices_frame, dev, light,
                on_brightness=self._on_brightness,
                on_color_temp=self._on_color_temp,
                on_toggle=self._on_toggle,
            )
            pad_top = 0 if idx == 0 else 6
            section.frame.pack(fill="x", pady=(pad_top, 4))
            if idx < len(visible) - 1:
                tk.Frame(self._devices_frame, height=1, bg="#2e2e2e"
                         ).pack(fill="x", pady=(2, 0))
            self._sections[dev.id] = section

        # Show empty hint if no visible sections
        if hasattr(self, "_empty_var"):
            self._empty_var.set("" if visible else "无可显示的设备")

    def rebuild(self, lights: dict[str, MiMonitorLight],
                config: AppConfig) -> None:
        """Rebuild device sections after config change."""
        self._lights = lights
        self._config = config
        self._build_device_sections()

    def _debouncer(self, table: dict[str, Debouncer], device_id: str,
                   delay: float) -> Debouncer:
        deb = table.get(device_id)
        if deb is None:
            deb = Debouncer(delay=delay)
            table[device_id] = deb
        return deb

    def schedule_open(self, x: int, y: int) -> None:
        self._root.after(0, lambda: self._open(x, y))

    def schedule_apply_state(self, state: LightState, device_id: str) -> None:
        self._root.after(0, lambda: self._apply_state(state, device_id))

    def schedule_apply_ct_range(self, device_id: str, lo: int, hi: int) -> None:
        self._root.after(0, lambda: self._apply_ct_range(device_id, lo, hi))

    def shutdown(self) -> None:
        for d in self._brightness_debouncers.values():
            d.cancel()
        for d in self._color_temp_debouncers.values():
            d.cancel()
        try:
            self._root.after(0, self._root.destroy)
        except tk.TclError:
            pass

    def run(self) -> None:
        self._root.mainloop()

    def _open(self, x: int, y: int) -> None:
        # Rebuild in case device visibility settings changed
        self._build_device_sections()
        threading.Thread(target=self._bg_refresh_all, daemon=True).start()
        self._position(x, y)
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()
        self._visible = True
        self._apply_rounded_corners()

    def hide(self) -> None:
        if self._visible:
            self._root.withdraw()
            self._visible = False

    def _on_focus_out(self, _e: tk.Event) -> None:
        if self._root.focus_get() is None:
            self.hide()

    def _position(self, ax: int, ay: int) -> None:
        self._root.update_idletasks()
        w = self.WIDTH
        # Force width first so content reflows, then re-measure height
        self._root.geometry(f"{w}x100")
        self._root.update_idletasks()
        h = self._root.winfo_reqheight()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x  = max(8, min(sw - w - 8, ax - w // 2))
        y  = max(8, min(sh - h - 8, ay - h  - 35))
        self._root.geometry(f"{w}x{h}+{x}+{y}")

    def _apply_state(self, state: LightState, device_id: str) -> None:
        section = self._sections.get(device_id)
        if section:
            section.apply_state(state)

    def _apply_ct_range(self, device_id: str, lo: int, hi: int) -> None:
        section = self._sections.get(device_id)
        if section:
            section.apply_ct_range(lo, hi)

    def _bg_refresh_all(self) -> None:
        for dev_id, light in self._lights.items():
            if dev_id not in self._sections:
                continue
            state = light.refresh()
            self._root.after(0, lambda s=state, d=dev_id: self._apply_state(s, d))

    def _on_brightness(self, device_id: str, val: int) -> None:
        light = self._lights.get(device_id)
        if light:
            self._debouncer(self._brightness_debouncers, device_id, 0.12
                            ).call(light.set_brightness, val)

    def _on_color_temp(self, device_id: str, val: int) -> None:
        light = self._lights.get(device_id)
        if light:
            self._debouncer(self._color_temp_debouncers, device_id, 0.18
                            ).call(light.set_color_temp, val)

    def _on_toggle(self, device_id: str) -> None:
        light = self._lights.get(device_id)
        if not light:
            return
        threading.Thread(target=self._toggle_thread,
                         args=(device_id, light), daemon=True).start()

    def _toggle_thread(self, device_id: str, light: MiMonitorLight) -> None:
        light.toggle()
        state = light.state
        self._root.after(0, lambda: self._apply_state(state, device_id))

    def _on_power_off_all(self) -> None:
        """Turn off all reachable devices."""
        threading.Thread(target=self._power_off_all_thread, daemon=True).start()

    def _power_off_all_thread(self) -> None:
        for light in self._lights.values():
            if light.state.reachable:
                light.set_power(False)
        # Refresh all sections to show updated status
        for dev_id, light in self._lights.items():
            state = light.state
            self._root.after(0, lambda s=state, d=dev_id: self._apply_state(s, d))

    def _open_settings(self) -> None:
        self.hide()
        self._on_open_setup()

