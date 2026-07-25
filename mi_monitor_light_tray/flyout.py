"""Twinkle Tray-style flyout — one row per control, icon + slider + value."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from .miio_client import Debouncer, LightState, MiMonitorLight
from .config import AppConfig

log = logging.getLogger(__name__)


class _DarkSlider(tk.Canvas):
    """Canvas-based horizontal slider with full dark-mode color control.

    Replaces ttk.Scale which cannot reliably render dark in all Windows themes.
    """

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
        n = 32  # enough points for a smooth circle at this size
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


class FlyoutWindow:
    WIDTH    = 360
    PAD_X    = 12
    PAD_Y    = 10

    BG       = "#1f1f1f"
    TEXT     = "#ffffff"
    MUTED    = "#8a8a8a"
    ACCENT   = "#60cdff"

    def __init__(self, lights: dict[str, MiMonitorLight],
                 config: AppConfig,
                 on_open_setup: Callable[[], None]) -> None:
        self._lights        = lights
        self._config        = config
        self._on_open_setup = on_open_setup
        self._active_id     = config.active_device_id  # "ALL" or specific device id

        self._root = tk.Tk()
        self._root.withdraw()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.configure(bg=self.BG)
        try:
            self._root.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        self._brightness_debounce = Debouncer(delay=0.12)
        self._color_temp_debounce = Debouncer(delay=0.18)
        self._suppress = False
        self._visible  = False

        self._build_ui()
        self._root.bind("<FocusOut>", self._on_focus_out)
        self._root.bind("<Escape>",   lambda _e: self.hide())

    # ── rounded corners ──────────────────────────────────────────────────────

    def _apply_rounded_corners(self) -> None:
        try:
            import ctypes
            # winfo_id() gives the embedded frame; GetAncestor(GA_ROOT=2) gets the true top-level HWND
            hwnd = ctypes.windll.user32.GetAncestor(self._root.winfo_id(), 2)
            val  = ctypes.c_int(2)   # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(val), 4)
        except Exception:
            pass

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = tk.Frame(self._root, bg=self.BG)
        outer.pack(fill="x", padx=self.PAD_X, pady=(self.PAD_Y, 0))

        # Device selector (only show if multiple devices or "ALL" mode makes sense)
        if len(self._lights) > 1:
            selector_frame = tk.Frame(outer, bg=self.BG)
            selector_frame.pack(fill="x", pady=(0, 8))

            tk.Label(selector_frame, text="设备", fg=self.MUTED, bg=self.BG,
                     font=("Microsoft YaHei UI", 9),
                     anchor="w").pack(side="left", padx=(0, 8))

            self._device_var = tk.StringVar(value=self._format_device_option(self._active_id))
            device_combo = ttk.Combobox(
                selector_frame, textvariable=self._device_var,
                state="readonly", width=25,
                font=("Microsoft YaHei UI", 9)
            )
            device_combo['values'] = self._build_device_options()
            device_combo.bind("<<ComboboxSelected>>", self._on_device_changed)
            device_combo.pack(side="left", fill="x", expand=True)

        self._brightness_var = tk.IntVar(value=50)
        self._color_temp_var = tk.IntVar(value=4000)

        # Get initial color temp range from first reachable device
        ct_min, ct_max = self._get_ct_range()

        self._build_row(outer, "", "亮度",
                        self._brightness_var,
                        MiMonitorLight.BRIGHTNESS_MIN,
                        MiMonitorLight.BRIGHTNESS_MAX,
                        "", self._on_brightness)

        self._build_row(outer, "", "色温",
                        self._color_temp_var,
                        ct_min, ct_max,
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
            ("⚙", self._open_settings),
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

    # ── device selector helpers ───────────────────────────────────────────────

    def _build_device_options(self) -> list[str]:
        """Build dropdown options: ['所有设备', 'Device 1', 'Device 2', ...]"""
        options = ["所有设备"]
        for dev_id in self._lights.keys():
            dev_config = self._find_device_config(dev_id)
            name = dev_config.name if dev_config else f"设备 {dev_id[:8]}"
            options.append(name)
        return options

    def _format_device_option(self, device_id: str) -> str:
        """Convert device_id to display name for dropdown."""
        if device_id == "ALL":
            return "所有设备"
        dev_config = self._find_device_config(device_id)
        return dev_config.name if dev_config else f"设备 {device_id[:8]}"

    def _find_device_config(self, device_id: str):
        """Find DeviceConfig by id."""
        return next((d for d in self._config.devices if d.id == device_id), None)

    def _on_device_changed(self, event) -> None:
        """Handle device selection change."""
        selected = self._device_var.get()
        if selected == "所有设备":
            self._active_id = "ALL"
        else:
            # Find device id by name
            for dev_config in self._config.devices:
                if dev_config.name == selected:
                    self._active_id = dev_config.id
                    break

        # Save active device to config
        self._config.active_device_id = self._active_id
        self._config.save()

        # Refresh state for selected device
        threading.Thread(target=self._bg_refresh, daemon=True).start()

    def _get_active_light(self) -> Optional[MiMonitorLight]:
        """Get the currently selected light (first reachable if ALL mode)."""
        if self._active_id == "ALL":
            # Return first reachable device
            for light in self._lights.values():
                if light.state.reachable:
                    return light
            # All offline, return first device
            return next(iter(self._lights.values()), None)
        else:
            return self._lights.get(self._active_id)

    def _get_ct_range(self) -> tuple[int, int]:
        """Get color temp range from active device."""
        light = self._get_active_light()
        if light:
            return light.color_temp_min, light.color_temp_max
        return 2700, 6500  # Default range

    # ── thread-safe entry points ──────────────────────────────────────────────

    def schedule_open(self, x: int, y: int) -> None:
        self._root.after(0, lambda: self._open(x, y))

    def schedule_apply_state(self, state: LightState) -> None:
        self._root.after(0, lambda: self._apply_state(state))

    def schedule_apply_ct_range(self, lo: int, hi: int) -> None:
        """Push a new color-temp slider range from any thread."""
        self._root.after(0, lambda: self._apply_ct_range(lo, hi))

    def shutdown(self) -> None:
        self._brightness_debounce.cancel()
        self._color_temp_debounce.cancel()
        try:
            self._root.after(0, self._root.destroy)
        except tk.TclError:
            pass

    def run(self) -> None:
        self._root.mainloop()

    # ── main-thread helpers ───────────────────────────────────────────────────

    def _open(self, x: int, y: int) -> None:
        threading.Thread(target=self._bg_refresh, daemon=True).start()
        self._position(x, y)
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()
        self._visible = True
        # Apply rounded corners after window is visible (DWM requires the HWND to exist)
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
        w = self.WIDTH   # force fixed width, ignore content's natural width
        h = self._root.winfo_reqheight()
        self._root.geometry(f"{w}x{h}")  # set width first so content reflows
        self._root.update_idletasks()
        h = self._root.winfo_reqheight()  # re-measure after reflow
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x  = max(8, min(sw - w - 8, ax - w // 2))
        y  = max(8, min(sh - h - 8, ay - h  - 35))
        self._root.geometry(f"{w}x{h}+{x}+{y}")

    def _apply_state(self, state: LightState) -> None:
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

    def _apply_ct_range(self, lo: int, hi: int) -> None:
        """Update the color-temp slider's bounds — called after model is resolved."""
        slider = getattr(self, "_color_temp_slider", None)
        if slider is None:
            return
        self._suppress = True
        try:
            slider.set_range(lo, hi)
        finally:
            self._suppress = False

    # ── callbacks ────────────────────────────────────────────────────────────

    def _bg_refresh(self) -> None:
        light = self._get_active_light()
        if light:
            state = light.refresh()
            self._root.after(0, lambda: self._apply_state(state))

    def _on_brightness(self, v: str) -> None:
        if self._suppress:
            return
        val = int(float(v))
        if self._active_id == "ALL":
            # Broadcast to all reachable devices
            for light in self._lights.values():
                if light.state.reachable:
                    self._brightness_debounce.call(light.set_brightness, val)
        else:
            light = self._lights.get(self._active_id)
            if light:
                self._brightness_debounce.call(light.set_brightness, val)

    def _on_color_temp(self, v: str) -> None:
        if self._suppress:
            return
        val = int(float(v))
        if self._active_id == "ALL":
            # Broadcast to all reachable devices
            for light in self._lights.values():
                if light.state.reachable:
                    self._color_temp_debounce.call(light.set_color_temp, val)
        else:
            light = self._lights.get(self._active_id)
            if light:
                self._color_temp_debounce.call(light.set_color_temp, val)

    def _on_toggle_power(self) -> None:
        threading.Thread(target=self._toggle_thread, daemon=True).start()

    def _toggle_thread(self) -> None:
        if self._active_id == "ALL":
            # Broadcast to all devices
            for light in self._lights.values():
                light.toggle()
            # Show aggregate status
            any_on = any(l.state.is_on for l in self._lights.values() if l.state.reachable)
            self._root.after(0, lambda: self._status_var.set("已开灯" if any_on else "已关灯"))
        else:
            light = self._lights.get(self._active_id)
            if light:
                new = light.toggle()
                st = light.state
                self._root.after(0, lambda: self._status_var.set(
                    "已开灯" if new else "已关灯"
                    if st.reachable else f"离线 — {(st.error or '')[:40]}"))

    def _open_settings(self) -> None:
        self.hide()
        self._on_open_setup()
