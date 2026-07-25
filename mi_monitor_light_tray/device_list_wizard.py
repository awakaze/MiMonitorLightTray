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

        # ── About Section ──────────────────────────────────────────────────
        about_frame = ttk.Frame(main_container)
        about_frame.pack(fill="x", pady=(8, 12))

        ttk.Label(
            about_frame,
            text="关于",
            font=("Microsoft YaHei UI", 10, "bold"),
            foreground="#1a1a1a"
        ).pack(anchor="w", pady=(0, 8))

        btn_frame = ttk.Frame(about_frame)
        btn_frame.pack(anchor="w")

        ttk.Button(
            btn_frame,
            text="检查更新",
            command=self._on_check_update,
            style="TButton"
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            btn_frame,
            text="访问 GitHub 主页",
            command=self._on_open_github,
            style="TButton"
        ).pack(side="left")

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
        """Build a card for one device with drag-and-drop support."""
        card = tk.Frame(self._device_list_frame, relief="solid", borderwidth=1,
                        bg="#ffffff")
        card.pack(fill="x", padx=8, pady=4)

        # Store index for drag-and-drop
        card._device_index = index

        # Bind drag events on the card
        card.bind("<ButtonPress-1>", lambda e, i=index: self._on_drag_start(e, i))
        card.bind("<B1-Motion>", self._on_drag_motion)
        card.bind("<ButtonRelease-1>", self._on_drag_end)

        # Drag handle (left side)
        drag_handle = tk.Label(
            card,
            text="⋮⋮",
            font=("Microsoft YaHei UI", 14),
            foreground="#8a8a8a",
            bg="#ffffff",
            cursor="fleur"
        )
        drag_handle.pack(side="left", padx=(8, 4))
        drag_handle.bind("<ButtonPress-1>", lambda e, i=index: self._on_drag_start(e, i))
        drag_handle.bind("<B1-Motion>", self._on_drag_motion)
        drag_handle.bind("<ButtonRelease-1>", self._on_drag_end)

        # Device info
        info_frame = tk.Frame(card, bg="#ffffff")
        info_frame.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        name_label = tk.Label(
            info_frame,
            text=device.name or "未命名设备",
            font=("Microsoft YaHei UI", 10, "bold"),
            foreground="#1a1a1a",
            bg="#ffffff"
        )
        name_label.pack(anchor="w")

        ip_label = tk.Label(
            info_frame,
            text=f"IP: {device.ip}  |  Token: {'●' * 8}",
            font=("Microsoft YaHei UI", 9),
            foreground="#666666",
            bg="#ffffff"
        )
        ip_label.pack(anchor="w")

        if device.model:
            model_label = tk.Label(
                info_frame,
                text=f"型号: {device.model}",
                font=("Microsoft YaHei UI", 9),
                foreground="#666666",
                bg="#ffffff"
            )
            model_label.pack(anchor="w")

        # Display option checkboxes
        display_frame = tk.Frame(info_frame, bg="#ffffff")
        display_frame.pack(anchor="w", pady=(4, 0))

        show_brightness_var = tk.BooleanVar(value=device.show_brightness)
        cb_brightness = tk.Checkbutton(
            display_frame,
            text="显示亮度调节",
            variable=show_brightness_var,
            bg="#ffffff",
            font=("Microsoft YaHei UI", 9),
            command=lambda i=index, v=show_brightness_var: self._on_toggle_show_brightness(i, v),
        )
        cb_brightness.pack(side="left", padx=(0, 12))

        show_color_temp_var = tk.BooleanVar(value=device.show_color_temp)
        cb_color_temp = tk.Checkbutton(
            display_frame,
            text="显示色温调节",
            variable=show_color_temp_var,
            bg="#ffffff",
            font=("Microsoft YaHei UI", 9),
            command=lambda i=index, v=show_color_temp_var: self._on_toggle_show_color_temp(i, v),
        )
        cb_color_temp.pack(side="left")

        # Action buttons
        btn_frame = tk.Frame(card, bg="#ffffff")
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

    def _on_toggle_show_brightness(self, index: int, var: tk.BooleanVar) -> None:
        """Toggle brightness visibility for a device."""
        if 0 <= index < len(self._config.devices):
            self._config.devices[index].show_brightness = var.get()

    def _on_toggle_show_color_temp(self, index: int, var: tk.BooleanVar) -> None:
        """Toggle color temp visibility for a device."""
        if 0 <= index < len(self._config.devices):
            self._config.devices[index].show_color_temp = var.get()

    # ── Drag-and-drop implementation ─────────────────────────────────────
    def _on_drag_start(self, event, index: int) -> None:
        """Start dragging a device card."""
        self._drag_source_index = index
        self._drag_start_y = event.y_root

        # Create drag preview window
        self._create_drag_preview(index)

    def _create_drag_preview(self, index: int) -> None:
        """Create a floating preview window for the dragged card."""
        device = self._config.devices[index]

        # Create a toplevel window for drag preview
        self._drag_preview = tk.Toplevel(self._root)
        self._drag_preview.overrideredirect(True)
        self._drag_preview.attributes("-alpha", 0.7)
        self._drag_preview.attributes("-topmost", True)

        # Build preview card
        card = tk.Frame(self._drag_preview, relief="solid", borderwidth=2,
                        bg="#e3f2fd", bd=2)
        card.pack(fill="both", expand=True)

        # Just show basic info
        info_frame = tk.Frame(card, bg="#e3f2fd")
        info_frame.pack(padx=16, pady=12)

        tk.Label(
            info_frame,
            text=device.name or "未命名设备",
            font=("Microsoft YaHei UI", 10, "bold"),
            foreground="#1a1a1a",
            bg="#e3f2fd"
        ).pack(anchor="w")

        tk.Label(
            info_frame,
            text=f"IP: {device.ip}",
            font=("Microsoft YaHei UI", 9),
            foreground="#666666",
            bg="#e3f2fd"
        ).pack(anchor="w")

        # Position will be updated in _on_drag_motion
        self._drag_preview.withdraw()

    def _on_drag_motion(self, event) -> None:
        """Handle drag motion - update preview position and highlight target."""
        if not hasattr(self, "_drag_source_index"):
            return

        # Update drag preview position
        if hasattr(self, "_drag_preview") and self._drag_preview.winfo_exists():
            self._drag_preview.deiconify()
            self._drag_preview.geometry(f"+{event.x_root + 10}+{event.y_root + 10}")

        # Find which card the cursor is currently over
        target_index = self._find_card_at_y(event.y_root)
        if target_index is None or target_index == self._drag_source_index:
            return

        # Show visual feedback (highlight target)
        self._highlight_drop_target(target_index)

    def _on_drag_end(self, event) -> None:
        """Handle drag end - perform reorder if applicable."""
        if not hasattr(self, "_drag_source_index"):
            return

        source = self._drag_source_index
        target = self._find_card_at_y(event.y_root)

        # Destroy drag preview
        if hasattr(self, "_drag_preview") and self._drag_preview.winfo_exists():
            self._drag_preview.destroy()
            del self._drag_preview

        # Clear drag state
        del self._drag_source_index

        if target is None or target == source:
            self._clear_drop_highlights()
            return

        # Perform reorder
        if 0 <= source < len(self._config.devices) and 0 <= target < len(self._config.devices):
            device = self._config.devices.pop(source)
            self._config.devices.insert(target, device)
            self._refresh_device_list()
            log.info("Moved device from position %d to %d", source, target)

    def _find_card_at_y(self, y_root: int) -> Optional[int]:
        """Find which card index is at the given y_root coordinate."""
        for child in self._device_list_frame.winfo_children():
            if not hasattr(child, "_device_index"):
                continue
            child_top = child.winfo_rooty()
            child_bottom = child_top + child.winfo_height()
            if child_top <= y_root <= child_bottom:
                return child._device_index
        return None

    def _highlight_drop_target(self, target_index: int) -> None:
        """Highlight the drop target card."""
        for child in self._device_list_frame.winfo_children():
            if not hasattr(child, "_device_index"):
                continue
            if child._device_index == target_index:
                try:
                    child.configure(bg="#e3f2fd")
                    for widget in child.winfo_children():
                        self._recursive_bg(widget, "#e3f2fd")
                except tk.TclError:
                    pass
            else:
                try:
                    child.configure(bg="#ffffff")
                    for widget in child.winfo_children():
                        self._recursive_bg(widget, "#ffffff")
                except tk.TclError:
                    pass

    def _clear_drop_highlights(self) -> None:
        """Clear all drop target highlights."""
        for child in self._device_list_frame.winfo_children():
            if not hasattr(child, "_device_index"):
                continue
            try:
                child.configure(bg="#ffffff")
                for widget in child.winfo_children():
                    self._recursive_bg(widget, "#ffffff")
            except tk.TclError:
                pass

    def _recursive_bg(self, widget, color: str) -> None:
        """Recursively set background color for tk widgets."""
        try:
            widget.configure(bg=color)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._recursive_bg(child, color)

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

    def _on_check_update(self) -> None:
        """Check for updates."""
        import webbrowser
        webbrowser.open("https://github.com/Martlnez/MiMonitorLightTray/releases/latest")

    def _on_open_github(self) -> None:
        """Open GitHub repository."""
        import webbrowser
        webbrowser.open("https://github.com/Martlnez/MiMonitorLightTray")

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
