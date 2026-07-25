"""Device editor dialog for adding/editing individual devices."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional
import uuid

from .config import DeviceConfig
from .miio_client import quick_ping

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


class DeviceEditorDialog:
    """Modal dialog for adding/editing a single device."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        device: DeviceConfig,
        on_saved: Callable[[DeviceConfig], None],
    ) -> None:
        self._device = device
        self._on_saved = on_saved
        self._tested_device_id = 0

        self._dialog = tk.Toplevel(parent)
        self._dialog.title("设备配置" if device.ip else "添加设备")
        self._dialog.resizable(False, False)
        self._dialog.configure(bg="#f3f3f3")
        self._dialog.transient(parent)
        self._dialog.grab_set()

        # Center on parent
        self._dialog.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        w = 480
        h = 520
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self._dialog.geometry(f"{w}x{h}+{x}+{y}")

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

        self._build_ui()

    def _build_ui(self) -> None:
        pad = {"padx": 16, "pady": 8}

        frm = ttk.Frame(self._dialog, padding=(20, 16, 20, 16))
        frm.pack(fill="both", expand=True)

        # Title
        ttk.Label(
            frm,
            text="设备信息",
            font=("Microsoft YaHei UI", 11, "bold"),
            foreground="#1a1a1a",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        # Fields
        self._ip_var = tk.StringVar(value=self._device.ip)
        self._token_var = tk.StringVar(value=self._device.token)
        self._name_var = tk.StringVar(value=self._device.name or "显示器挂灯")
        self._model_var = tk.StringVar(value=self._device.model)

        fields = [
            ("设备 IP 地址", self._ip_var, False,
             "从米家 App 或路由器查看\n如: 192.168.31.73"),
            ("miio Token", self._token_var, True,
             "32 位十六进制字符串\n用 Xiaomi-cloud-tokens-extractor 获取"),
            ("显示名称", self._name_var, False,
             "设备的显示名称"),
            ("型号（可选）", self._model_var, False,
             "留空自动识别\n如: yeelink.light.lamp22"),
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

        # Per-device toggles
        ttk.Label(
            frm,
            text="设备选项",
            font=("Microsoft YaHei UI", 11, "bold"),
            foreground="#1a1a1a",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(16, 8))

        self._power_on_at_startup_var = tk.BooleanVar(
            value=self._device.power_on_at_startup)
        cb_on = ttk.Checkbutton(
            frm, text="灯跟随软件启动",
            variable=self._power_on_at_startup_var,
        )
        cb_on.grid(row=7, column=0, sticky="w", padx=16, pady=(4, 0))
        _Tooltip(cb_on, "勾选后：程序启动时自动开灯")

        self._power_off_at_exit_var = tk.BooleanVar(
            value=self._device.power_off_at_exit)
        cb_off = ttk.Checkbutton(
            frm, text="灯跟随软件关闭",
            variable=self._power_off_at_exit_var,
        )
        cb_off.grid(row=7, column=1, sticky="w", padx=16, pady=(4, 0))
        _Tooltip(cb_off, "勾选后：程序退出时自动关灯")

        self._power_off_on_monitor_sleep_var = tk.BooleanVar(
            value=self._device.power_off_on_monitor_sleep)
        cb_monitor = ttk.Checkbutton(
            frm, text="灯随显示器休眠开关",
            variable=self._power_off_on_monitor_sleep_var,
        )
        cb_monitor.grid(row=8, column=0, sticky="w", padx=16, pady=(4, 0))
        _Tooltip(cb_monitor, "勾选后：显示器休眠时自动关灯\n显示器唤醒时自动开灯")

        self._power_off_on_system_suspend_var = tk.BooleanVar(
            value=self._device.power_off_on_system_suspend)
        cb_system_off = ttk.Checkbutton(
            frm, text="系统休眠时关灯",
            variable=self._power_off_on_system_suspend_var,
        )
        cb_system_off.grid(row=8, column=1, sticky="w", padx=16, pady=(4, 0))
        _Tooltip(cb_system_off, "勾选后：系统进入睡眠/休眠时自动关灯")

        self._power_on_on_system_resume_var = tk.BooleanVar(
            value=self._device.power_on_on_system_resume)
        cb_system_on = ttk.Checkbutton(
            frm, text="系统唤醒时开灯",
            variable=self._power_on_on_system_resume_var,
        )
        cb_system_on.grid(row=9, column=0, sticky="w", padx=16, pady=(4, 0))
        _Tooltip(cb_system_on, "勾选后：系统从睡眠/休眠唤醒时自动开灯")

        self._enable_miot_var = tk.BooleanVar(
            value=self._device.enable_miot_for_unknown)
        cb_miot = ttk.Checkbutton(
            frm, text="启用 MIoT（实验性）",
            variable=self._enable_miot_var,
        )
        cb_miot.grid(row=9, column=1, sticky="w", padx=16, pady=(4, 0))
        _Tooltip(cb_miot,
                 "对未列入 MIoT 白名单的新型 Yeelight 设备，\n"
                 "尝试用通用 Light service spec 走 MIoT 协议。")

        frm.columnconfigure(1, weight=1)

        # Status + buttons
        self._status_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self._status_var,
                  foreground="#0066cc"
                  ).grid(row=10, column=0, columnspan=2,
                         sticky="w", padx=16, pady=(8, 0))

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=11, column=0, columnspan=2,
                     sticky="e", pady=(12, 4), padx=16)

        ttk.Button(btn_row, text="取消",
                   command=self._close).pack(side="left", padx=4)
        self._test_btn = ttk.Button(btn_row, text="测试连接",
                                    command=self._on_test)
        self._test_btn.pack(side="left", padx=4)
        self._save_btn = ttk.Button(btn_row, text="保存",
                                    command=self._on_save)
        self._save_btn.pack(side="left", padx=4)

    def _collect(self) -> DeviceConfig:
        # Preserve or generate device id
        device_id_to_use = self._tested_device_id or self._device.device_id
        id_to_use = self._device.id if self._device.id else f"temp_{uuid.uuid4().hex[:8]}"

        return DeviceConfig(
            id=id_to_use,
            ip=self._ip_var.get().strip(),
            token=self._token_var.get().strip(),
            name=self._name_var.get().strip() or "显示器挂灯",
            model=self._model_var.get().strip(),
            device_id=device_id_to_use,
            enable_miot_for_unknown=self._enable_miot_var.get(),
            power_on_at_startup=self._power_on_at_startup_var.get(),
            power_off_at_exit=self._power_off_at_exit_var.get(),
            power_off_on_monitor_sleep=self._power_off_on_monitor_sleep_var.get(),
            power_off_on_system_suspend=self._power_off_on_system_suspend_var.get(),
            power_on_on_system_resume=self._power_on_on_system_resume_var.get(),
        )

    def _on_test(self) -> None:
        dev = self._collect()
        if not dev.is_complete():
            messagebox.showerror("输入错误",
                                 "请填写设备 IP 地址和 32 位 Token",
                                 parent=self._dialog)
            return
        self._status_var.set("正在测试连接…")
        self._test_btn.configure(state="disabled")
        threading.Thread(target=self._test_thread,
                         args=(dev,), daemon=True).start()

    def _test_thread(self, dev: DeviceConfig) -> None:
        ok, message, device_id = quick_ping(dev.ip, dev.token)
        self._dialog.after(0, lambda: self._after_test(ok, message, device_id))

    def _after_test(self, ok: bool, message: str, device_id: int) -> None:
        self._test_btn.configure(state="normal")
        self._status_var.set(message)
        if ok:
            if device_id:
                self._tested_device_id = device_id
                log.info("Test connection captured device_id %08x", device_id)
            messagebox.showinfo("连接成功", f"设备在线\n{message}",
                                parent=self._dialog)
        else:
            messagebox.showerror("连接失败",
                                 f"无法连接到设备\n{message}",
                                 parent=self._dialog)

    def _on_save(self) -> None:
        dev = self._collect()
        if not dev.is_complete():
            messagebox.showerror("输入错误",
                                 "请填写设备 IP 地址和 32 位 Token",
                                 parent=self._dialog)
            return
        self._on_saved(dev)
        self._close()

    def _close(self) -> None:
        try:
            self._dialog.destroy()
        except tk.TclError:
            pass
