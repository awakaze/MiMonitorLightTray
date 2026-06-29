"""First-run / settings wizard."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from .config import AppConfig, DeviceConfig
from .miio_client import quick_ping
from . import autostart
from .cloud_login_window import CloudLoginWindow
from .token_extractor.types import XiaomiDeviceInfo

log = logging.getLogger(__name__)


class _Tooltip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._w = widget
        self._text = text
        self._win: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _e=None) -> None:
        if self._win:
            return
        x = self._w.winfo_rootx() + 4
        y = self._w.winfo_rooty() + self._w.winfo_height() + 4
        self._win = tw = tk.Toplevel(self._w)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        tk.Label(tw, text=self._text, background="#ffffc0",
                 relief="solid", borderwidth=1,
                 font=("Microsoft YaHei UI", 9),
                 padx=8, pady=6, justify="left").pack()

    def _hide(self, _e=None) -> None:
        if self._win:
            self._win.destroy()
            self._win = None


class SetupWizard:
    def __init__(
        self,
        config: AppConfig,
        on_saved: Callable[[AppConfig], None],
        *,
        parent: Optional[tk.Tk] = None,
    ) -> None:
        self._config = config
        self._on_saved = on_saved
        self._owns_root = parent is None
        self._tested_device_id = 0

        self._root = tk.Tk() if parent is None else tk.Toplevel(parent)
        self._root.title("小米显示器挂灯 — 设置")
        self._root.resizable(True, True)
        self._root.configure(bg="#f3f3f3")
        self._root.minsize(460, 400)

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            style.theme_use("clam")
        style.configure("TLabel", background="#f3f3f3",
                        font=("Microsoft YaHei UI", 9))
        style.configure("TFrame", background="#f3f3f3")
        style.configure("TButton", padding=(12, 6),
                        font=("Microsoft YaHei UI", 9))
        style.configure("Blue.TButton", foreground="#0066cc")

        self._style = style

        self._build_ui()

    def _build_ui(self) -> None:
        pad = {"padx": 16, "pady": 8}

        # Scrollable canvas
        canvas = tk.Canvas(self._root, bg="#f3f3f3", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self._root, orient="vertical",
                                  command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        frm = ttk.Frame(canvas, padding=(20, 16, 20, 16))
        win_id = canvas.create_window((0, 0), window=frm, anchor="nw")

        def _on_frame_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        frm.bind("<Configure>", _on_frame_configure)

        def _on_canvas_configure(e):
            canvas.itemconfig(win_id, width=e.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mousewheel — clamp at top, don't scroll past 0
        def _on_wheel(e):
            top, _ = canvas.yview()
            if top <= 0 and e.delta > 0:
                return  # already at top, block upward scroll
            canvas.yview_scroll(-1 * (e.delta // 120), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)

        # ── Title ─────────────────────────────────────────────────────────────
        title_row = ttk.Frame(frm)
        title_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        ttk.Label(
            title_row,
            text="设备配置",
            font=("Microsoft YaHei UI", 13, "bold"),
            foreground="#1a1a1a",
        ).pack(side="left")

        # 蓝色的「自动获取」按钮
        fetch_btn = ttk.Button(
            title_row,
            text="自动获取",
            command=self._open_cloud_login,
            width=10,
            style="Blue.TButton",
        )
        fetch_btn.pack(side="right")

        # ── Fields ─────────────────────────────────────────────────────────────
        self._ip_var    = tk.StringVar(value=self._config.device.ip)
        self._token_var = tk.StringVar(value=self._config.device.token)
        self._name_var  = tk.StringVar(
            value=self._config.device.name or "显示器挂灯")
        self._model_var = tk.StringVar(value=self._config.device.model)

        fields = [
            ("设备 IP 地址", self._ip_var,    False,
             "从米家 App 或路由器查看\n如: 192.168.31.73"),
            ("miio Token",  self._token_var, True,
             "32 位十六进制字符串\n用 Xiaomi-cloud-tokens-extractor 获取"),
            ("显示名称",    self._name_var,  False,
             "托盘中显示的设备名称"),
            ("型号（可选）", self._model_var, False,
             "留空自动识别，填写错误可能导致功能异常\n如: yeelink.light.lamp22"),
        ]

        self._token_entry: Optional[ttk.Entry] = None
        for i, (label, var, secret, tip) in enumerate(fields, start=1):
            ttk.Label(frm, text=label).grid(row=i, column=0,
                                            sticky="w", **pad)
            e = ttk.Entry(frm, textvariable=var, width=30,
                          show="*" if secret else "",
                          font=("Consolas", 10) if not label.startswith("显") else
                               ("Microsoft YaHei UI", 10))
            e.grid(row=i, column=1, sticky="ew", **pad)
            _Tooltip(e, tip)
            if secret:
                self._token_entry = e

        self._show_token = tk.BooleanVar(value=False)

        def _toggle():
            self._token_entry.configure(
                show="" if self._show_token.get() else "*")

        ttk.Checkbutton(frm, text="显示 Token",
                        variable=self._show_token, command=_toggle
                        ).grid(row=5, column=1, sticky="w", padx=16)

        # Launch-at-startup toggle. Reads/writes the user-scope Run registry key
        # via autostart.py; state is independent of config.json.
        self._autostart_var = tk.BooleanVar(value=autostart.is_enabled())

        def _toggle_autostart():
            target = self._autostart_var.get()
            ok = autostart.enable() if target else autostart.disable()
            actual = autostart.is_enabled()
            if actual != target or not ok:
                # Restore checkbox to what actually happened so UI doesn't lie.
                self._autostart_var.set(actual)

        ttk.Checkbutton(frm, text="开机自启动",
                        variable=self._autostart_var,
                        command=_toggle_autostart
                        ).grid(row=5, column=0, sticky="w", padx=16)

        # ── New per-device toggles ─────────────────────────────────────────────
        self._power_on_at_startup_var = tk.BooleanVar(
            value=self._config.device.power_on_at_startup)
        cb_on = ttk.Checkbutton(
            frm, text="灯跟随软件启动",
            variable=self._power_on_at_startup_var,
        )
        cb_on.grid(row=6, column=0, sticky="w", padx=16, pady=(4, 0))
        _Tooltip(cb_on, "勾选后：程序启动时自动开灯")

        self._power_off_at_exit_var = tk.BooleanVar(
            value=self._config.device.power_off_at_exit)
        cb_off = ttk.Checkbutton(
            frm, text="灯跟随软件关闭",
            variable=self._power_off_at_exit_var,
        )
        cb_off.grid(row=6, column=1, sticky="w", padx=16, pady=(4, 0))
        _Tooltip(cb_off, "勾选后：程序退出时自动关灯")

        self._enable_miot_var = tk.BooleanVar(
            value=self._config.device.enable_miot_for_unknown)
        cb_miot = ttk.Checkbutton(
            frm, text="启用 MIoT（实验性）",
            variable=self._enable_miot_var,
        )
        cb_miot.grid(row=7, column=0, columnspan=2, sticky="w", padx=16,
                     pady=(4, 0))
        _Tooltip(cb_miot,
                 "对未列入 MIoT 白名单的新型 Yeelight 设备，\n"
                 "尝试用通用 Light service spec 走 MIoT 协议。\n"
                 "若设备不兼容则会持续报错 — 取消勾选即可回到 legacy。")

        frm.columnconfigure(1, weight=1)

        # ── Status + buttons ───────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self._status_var,
                  foreground="#0066cc"
                  ).grid(row=8, column=0, columnspan=2,
                         sticky="w", padx=16)

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=9, column=0, columnspan=2,
                     sticky="e", pady=(12, 4), padx=16)

        ttk.Button(btn_row, text="取消",
                   command=self._close).pack(side="left", padx=4)
        self._test_btn = ttk.Button(btn_row, text="测试连接",
                                    command=self._on_test)
        self._test_btn.pack(side="left", padx=4)
        self._save_btn = ttk.Button(btn_row, text="保存",
                                    command=self._on_save)
        self._save_btn.pack(side="left", padx=4)

        # Auto-size window to content after build
        self._root.update_idletasks()
        h = min(frm.winfo_reqheight() + 40, 600)
        self._root.geometry(f"500x{h}")

    # ── actions ────────────────────────────────────────────────────────────────

    def _collect(self) -> DeviceConfig:
        # Preserve device_id captured by a prior successful connection or test —
        # never wipe it here, or auto-rediscovery on IP change stops working.
        return DeviceConfig(
            ip=self._ip_var.get().strip(),
            token=self._token_var.get().strip(),
            name=self._name_var.get().strip() or "显示器挂灯",
            model=self._model_var.get().strip(),
            device_id=self._tested_device_id or self._config.device.device_id,
            enable_miot_for_unknown=self._enable_miot_var.get(),
            power_on_at_startup=self._power_on_at_startup_var.get(),
            power_off_at_exit=self._power_off_at_exit_var.get(),
        )

    def _on_test(self) -> None:
        dev = self._collect()
        if not dev.is_complete():
            messagebox.showerror("输入错误",
                                 "请填写设备 IP 地址和 32 位 Token",
                                 parent=self._root)
            return
        self._status_var.set("正在测试连接…")
        self._test_btn.configure(state="disabled")
        threading.Thread(target=self._test_thread,
                         args=(dev,), daemon=True).start()

    def _test_thread(self, dev: DeviceConfig) -> None:
        ok, message, device_id = quick_ping(dev.ip, dev.token)
        self._root.after(0, lambda: self._after_test(ok, message, device_id))

    def _after_test(self, ok: bool, message: str, device_id: int) -> None:
        self._test_btn.configure(state="normal")
        self._status_var.set(message)
        if ok:
            if device_id:
                self._tested_device_id = device_id
                log.info("Test connection captured device_id %08x", device_id)
            messagebox.showinfo("连接成功", f"设备在线\n{message}",
                                parent=self._root)
        else:
            messagebox.showerror("连接失败",
                                 f"无法连接到设备\n{message}",
                                 parent=self._root)

    def _on_save(self) -> None:
        dev = self._collect()
        if not dev.is_complete():
            messagebox.showerror("输入错误",
                                 "请填写设备 IP 地址和 32 位 Token",
                                 parent=self._root)
            return
        self._config.device = dev
        try:
            self._config.save()
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc),
                                 parent=self._root)
            return
        self._on_saved(self._config)
        self._close()

    def _close(self) -> None:
        try:
            self._root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        if self._owns_root:
            self._root.mainloop()

    def _open_cloud_login(self) -> None:
        """打开云端登录窗口。"""
        def on_device_selected(device: XiaomiDeviceInfo) -> None:
            """设备选择回调。"""
            self._ip_var.set(device.localip)
            self._token_var.set(device.token)
            if device.name:
                self._name_var.set(device.name)
            if device.model:
                self._model_var.set(device.model)
            messagebox.showinfo(
                "获取成功",
                f"已自动填充设备信息：\n\n"
                f"名称：{device.name}\n"
                f"IP：{device.localip}\n"
                f"型号：{device.model or '未知'}",
                parent=self._root,
            )

        CloudLoginWindow(self._root, on_device_selected)
