"""Device list manager for Setup Wizard - manage multiple devices graphically."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from .config import AppConfig, DeviceConfig, HotkeyConfig
from .device_editor import DeviceEditorDialog
from . import autostart
from .cloud_login_window import CloudLoginWindow
from .token_extractor.types import XiaomiDeviceInfo

log = logging.getLogger(__name__)


class DeviceListWizard:
    """Setup wizard with graphical device list management."""

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

        self._root = tk.Tk() if parent is None else tk.Toplevel(parent)
        self._root.title("小米显示器挂灯 — 设置")
        self._root.resizable(True, True)
        self._root.configure(bg="#f3f3f3")
        self._root.minsize(600, 500)

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
        style.configure("Small.TButton", padding=(8, 4),
                        font=("Microsoft YaHei UI", 9))

        self._build_ui()

    def _build_ui(self) -> None:
        # Main container with scrollbar
        main_container = ttk.Frame(self._root)
        main_container.pack(fill="both", expand=True, padx=20, pady=16)

        # ── Title and Add Button ──────────────────────────────────────────
        title_row = ttk.Frame(main_container)
        title_row.pack(fill="x", pady=(0, 12))

        ttk.Label(
            title_row,
            text="设备列表",
            font=("Microsoft YaHei UI", 13, "bold"),
            foreground="#1a1a1a",
        ).pack(side="left")

        btn_frame = ttk.Frame(title_row)
        btn_frame.pack(side="right")

        ttk.Button(
            btn_frame,
            text="云端导入",
            command=self._open_cloud_login,
            style="Blue.TButton",
        ).pack(side="left", padx=4)

        ttk.Button(
            btn_frame,
            text="+ 添加设备",
            command=self._on_add_device,
            style="Blue.TButton",
        ).pack(side="left")

        # ── Device List (Scrollable) ──────────────────────────────────────
        list_frame = ttk.Frame(main_container, relief="solid", borderwidth=1)
        list_frame.pack(fill="both", expand=True, pady=(0, 12))

        # Canvas for scrolling
        canvas = tk.Canvas(list_frame, bg="#ffffff", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical",
                                  command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._device_list_frame = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=self._device_list_frame,
                                            anchor="nw")

        def _on_frame_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        self._device_list_frame.bind("<Configure>", _on_frame_configure)

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_window, width=e.width)

        canvas.bind("<Configure>", _on_canvas_configure)

        # Mousewheel scrolling
        def _on_wheel(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")

        canvas.bind_all("<MouseWheel>", _on_wheel)

        # Populate device list
        self._refresh_device_list()

        # ── Global Settings ────────────────────────────────────────────────
        ttk.Separator(main_container, orient="horizontal").pack(
            fill="x", pady=(0, 12))

        settings_title = ttk.Label(
            main_container,
            text="全局设置",
            font=("Microsoft YaHei UI", 11, "bold"),
            foreground="#1a1a1a",
        )
        settings_title.pack(anchor="w", pady=(0, 8))

        # Autostart toggle
        self._autostart_var = tk.BooleanVar(value=autostart.is_enabled())

        def _toggle_autostart():
            target = self._autostart_var.get()
            ok = autostart.enable() if target else autostart.disable()
            actual = autostart.is_enabled()
            if actual != target or not ok:
                self._autostart_var.set(actual)

        ttk.Checkbutton(main_container, text="开机自启动",
                        variable=self._autostart_var,
                        command=_toggle_autostart).pack(anchor="w", pady=(0, 12))

        # ── Hotkey Settings (Collapsed) ────────────────────────────────────
        hotkey_frame = ttk.Frame(main_container)
        hotkey_frame.pack(fill="x", pady=(0, 12))

        self._hotkey_expanded = tk.BooleanVar(value=False)
        hotkey_toggle = ttk.Checkbutton(
            hotkey_frame,
            text="▶ 快捷键设置",
            variable=self._hotkey_expanded,
            command=self._toggle_hotkey_section,
            style="TCheckbutton"
        )
        hotkey_toggle.pack(anchor="w")

        self._hotkey_detail_frame = ttk.Frame(main_container)
        # Will be packed when expanded

        # ── Footer Buttons ─────────────────────────────────────────────────
        btn_row = ttk.Frame(main_container)
        btn_row.pack(fill="x", pady=(12, 0))

        ttk.Button(btn_row, text="取消",
                   command=self._close).pack(side="right", padx=4)
        ttk.Button(btn_row, text="保存",
                   command=self._on_save).pack(side="right")

    def _refresh_device_list(self) -> None:
        """Refresh the device list display."""
        # Clear existing widgets
        for widget in self._device_list_frame.winfo_children():
            widget.destroy()

        if not self._config.devices:
            # Empty state
            empty_label = ttk.Label(
                self._device_list_frame,
                text="暂无设备\n点击「+ 添加设备」或「云端导入」开始配置",
                font=("Microsoft YaHei UI", 10),
                foreground="#8a8a8a",
                justify="center"
            )
            empty_label.pack(pady=60)
            return

        # Render device cards
        for idx, device in enumerate(self._config.devices):
            self._build_device_card(device, idx)

    def _build_device_card(self, device: DeviceConfig, index: int) -> None:
        """Build a card for one device."""
        card = ttk.Frame(self._device_list_frame, relief="flat")
        card.pack(fill="x", padx=8, pady=4)

        # Device info
        info_frame = ttk.Frame(card)
        info_frame.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        name_label = ttk.Label(
            info_frame,
            text=device.name or "未命名设备",
            font=("Microsoft YaHei UI", 10, "bold"),
            foreground="#1a1a1a"
        )
        name_label.pack(anchor="w")

        ip_label = ttk.Label(
            info_frame,
            text=f"IP: {device.ip}  |  Token: {'●' * 8}",
            font=("Microsoft YaHei UI", 9),
            foreground="#666666"
        )
        ip_label.pack(anchor="w")

        if device.model:
            model_label = ttk.Label(
                info_frame,
                text=f"型号: {device.model}",
                font=("Microsoft YaHei UI", 9),
                foreground="#666666"
            )
            model_label.pack(anchor="w")

        # Action buttons
        btn_frame = ttk.Frame(card)
        btn_frame.pack(side="right", padx=8)

        ttk.Button(
            btn_frame,
            text="编辑",
            command=lambda: self._on_edit_device(index),
            style="Small.TButton"
        ).pack(side="left", padx=2)

        ttk.Button(
            btn_frame,
            text="删除",
            command=lambda: self._on_delete_device(index),
            style="Small.TButton"
        ).pack(side="left", padx=2)

        # Separator
        ttk.Separator(self._device_list_frame, orient="horizontal").pack(
            fill="x", padx=8, pady=2)

    def _toggle_hotkey_section(self) -> None:
        """Toggle hotkey settings expansion."""
        if self._hotkey_expanded.get():
            # Expand - show hotkey settings
            self._hotkey_detail_frame.pack(fill="x", pady=(8, 0))
            self._build_hotkey_settings()
        else:
            # Collapse
            self._hotkey_detail_frame.pack_forget()

    def _build_hotkey_settings(self) -> None:
        """Build hotkey configuration UI."""
        # Clear existing
        for widget in self._hotkey_detail_frame.winfo_children():
            widget.destroy()

        # Implementation similar to setup_wizard.py hotkey section
        # For brevity, keeping it simple
        ttk.Label(
            self._hotkey_detail_frame,
            text="快捷键配置（待实现）",
            foreground="#8a8a8a"
        ).pack(pady=8)

    def _on_add_device(self) -> None:
        """Add a new device."""
        import uuid
        new_device = DeviceConfig(
            id=f"temp_{uuid.uuid4().hex[:8]}",
            ip="",
            token="",
            name="",
            model="",
            device_id=0,
        )

        def on_saved(device: DeviceConfig):
            self._config.devices.append(device)
            self._refresh_device_list()

        DeviceEditorDialog(self._root, new_device, on_saved)

    def _on_edit_device(self, index: int) -> None:
        """Edit an existing device."""
        device = self._config.devices[index]

        def on_saved(updated_device: DeviceConfig):
            self._config.devices[index] = updated_device
            self._refresh_device_list()

        DeviceEditorDialog(self._root, device, on_saved)

    def _on_delete_device(self, index: int) -> None:
        """Delete a device."""
        device = self._config.devices[index]
        result = messagebox.askyesno(
            "确认删除",
            f"确定要删除设备「{device.name}」吗？\n此操作无法撤销。",
            parent=self._root
        )
        if result:
            del self._config.devices[index]
            self._refresh_device_list()
            log.info("Deleted device %s", device.name)

    def _open_cloud_login(self) -> None:
        """Open cloud login for device import (multi-select mode)."""
        initial_count = len(self._config.devices)

        def on_device_selected(device: XiaomiDeviceInfo):
            import uuid
            dev_config = DeviceConfig(
                id=f"temp_{uuid.uuid4().hex[:8]}",
                ip=device.localip,
                token=device.token,
                name=device.name or "显示器挂灯",
                model=device.model or "",
                device_id=0,
            )
            self._config.devices.append(dev_config)

        # Create cloud login with multi-select enabled
        # The window will call on_device_selected for each selected device
        CloudLoginWindow(self._root, on_device_selected, multi_select=True)

        # Refresh after window closes
        self._root.after(500, lambda: self._check_import_complete(initial_count))

    def _check_import_complete(self, initial_count: int) -> None:
        """Check if devices were imported and refresh list."""
        new_count = len(self._config.devices)
        if new_count > initial_count:
            self._refresh_device_list()
            added = new_count - initial_count
            messagebox.showinfo(
                "导入成功",
                f"已成功导入 {added} 个设备",
                parent=self._root,
            )

    def _on_save(self) -> None:
        """Save configuration."""
        if not self._config.devices:
            result = messagebox.askyesno(
                "设备为空",
                "当前没有配置任何设备，确定要保存吗？",
                parent=self._root
            )
            if not result:
                return

        try:
            self._config.save()
            self._on_saved(self._config)
            self._close()
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self._root)

    def _close(self) -> None:
        """Close the wizard."""
        try:
            self._root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        """Run the wizard main loop."""
        if self._owns_root:
            self._root.mainloop()
