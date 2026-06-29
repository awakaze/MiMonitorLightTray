"""云端登录窗口。"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, List, Optional

from .token_extractor.auth import PasswordAuth, QrCodeAuth
from .token_extractor.types import LoginResult, XiaomiDeviceInfo

log = logging.getLogger(__name__)


class CloudLoginWindow:
    """云端登录窗口。"""

    def __init__(
        self,
        parent: tk.Tk,
        on_success: Callable[[XiaomiDeviceInfo], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        """初始化云端登录窗口。

        Args:
            parent: 父窗口
            on_success: 设备选择成功回调
            on_cancel: 取消回调
        """
        self._parent = parent
        self._on_success = on_success
        self._on_cancel = on_cancel
        self._is_closing = False
        self._current_thread: Optional[threading.Thread] = None
        self._auth: Optional[object] = None

        # 创建顶级窗口（模态）
        self._root = tk.Toplevel(parent)
        self._root.title("自动获取设备信息")
        self._root.resizable(False, False)
        self._root.configure(bg="#f3f3f3")
        self._root.transient(parent)
        self._root.grab_set()

        # 窗口关闭时清理
        self._root.protocol("WM_DELETE_WINDOW", self._close)

        self._build_ui()
        self._show_login_method_selection()

    def _build_ui(self) -> None:
        """构建 UI 框架。"""
        self._content_frame = ttk.Frame(self._root, padding=24)
        self._content_frame.pack(fill="both", expand=True)

    def _clear_content(self) -> None:
        """清空内容区域。"""
        for widget in self._content_frame.winfo_children():
            widget.destroy()

    def _show_login_method_selection(self) -> None:
        """显示登录方式选择界面。"""
        self._clear_content()

        ttk.Label(
            self._content_frame,
            text="请选择登录方式",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(pady=(0, 16))

        ttk.Button(
            self._content_frame,
            text="用户名密码登录",
            command=self._show_password_login,
            width=25,
        ).pack(pady=8)

        ttk.Button(
            self._content_frame,
            text="扫码登录",
            command=self._show_qrcode_login,
            width=25,
        ).pack(pady=8)

        ttk.Button(
            self._content_frame,
            text="取消",
            command=self._close,
        ).pack(pady=(16, 0))

    def _show_password_login(self) -> None:
        """显示密码登录界面。"""
        self._clear_content()

        ttk.Label(
            self._content_frame,
            text="用户名密码登录",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=(0, 12))

        # 用户名输入
        ttk.Label(self._content_frame, text="邮箱/手机号/用户ID:").pack(
            anchor="w", pady=(8, 2)
        )
        self._username_var = tk.StringVar()
        ttk.Entry(
            self._content_frame, textvariable=self._username_var, width=30
        ).pack(fill="x", pady=(0, 8))

        # 密码输入
        ttk.Label(self._content_frame, text="密码:").pack(
            anchor="w", pady=(8, 2)
        )
        self._password_var = tk.StringVar()
        ttk.Entry(
            self._content_frame,
            textvariable=self._password_var,
            show="*",
            width=30,
        ).pack(fill="x", pady=(0, 8))

        # 状态标签
        self._status_var = tk.StringVar(value="")
        self._status_label = ttk.Label(
            self._content_frame,
            textvariable=self._status_var,
            foreground="#0066cc",
        )
        self._status_label.pack(pady=(8, 4))

        # 按钮
        btn_frame = ttk.Frame(self._content_frame)
        btn_frame.pack(pady=(8, 0))

        ttk.Button(
            btn_frame, text="返回", command=self._show_login_method_selection
        ).pack(side="left", padx=4)

        self._login_btn = ttk.Button(
            btn_frame, text="登录", command=self._on_password_login
        )
        self._login_btn.pack(side="left", padx=4)

    def _show_qrcode_login(self) -> None:
        """显示二维码登录界面。"""
        self._clear_content()

        ttk.Label(
            self._content_frame,
            text="扫码登录",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=(0, 12))

        # 二维码显示区域
        self._qr_label = ttk.Label(self._content_frame, text="正在获取二维码...")
        self._qr_label.pack(pady=16)

        # 状态标签
        self._status_var = tk.StringVar(value="")
        self._status_label = ttk.Label(
            self._content_frame,
            textvariable=self._status_var,
            foreground="#0066cc",
        )
        self._status_label.pack(pady=(8, 4))

        # 按钮
        btn_frame = ttk.Frame(self._content_frame)
        btn_frame.pack(pady=(8, 0))

        ttk.Button(
            btn_frame, text="返回", command=self._show_login_method_selection
        ).pack(side="left", padx=4)

        # 开始获取二维码
        self._current_thread = threading.Thread(
            target=self._fetch_qr_code, daemon=True
        )
        self._current_thread.start()

    def _on_password_login(self) -> None:
        """密码登录按钮点击事件。"""
        username = self._username_var.get().strip()
        password = self._password_var.get().strip()

        if not username or not password:
            messagebox.showwarning("输入错误", "请输入用户名和密码", parent=self._root)
            return

        self._login_btn.configure(state="disabled")
        self._status_var.set("正在登录...")
        self._auth = PasswordAuth(username, password)

        self._current_thread = threading.Thread(
            target=self._login_thread, daemon=True
        )
        self._current_thread.start()

    def _fetch_qr_code(self) -> None:
        """获取二维码（线程中执行）。"""
        try:
            self._auth = QrCodeAuth()
            result = self._auth.login()
            if self._is_closing:
                return
            self._root.after(0, lambda: self._handle_qr_result(result))
        except Exception as e:
            if self._is_closing:
                return
            self._root.after(0, lambda: self._handle_login_error(str(e)))

    def _login_thread(self) -> None:
        """登录线程。"""
        try:
            result = self._auth.login()
            if self._is_closing:
                return
            self._root.after(0, lambda: self._handle_login_result(result))
        except Exception as e:
            if self._is_closing:
                return
            self._root.after(0, lambda: self._handle_login_error(str(e)))

    def _handle_qr_result(self, result: LoginResult) -> None:
        """处理二维码获取结果。"""
        if result.success and result.qr_image_data:
            # 显示二维码图像
            try:
                from PIL import Image, ImageTk
                import io

                image = Image.open(io.BytesIO(result.qr_image_data))
                image = image.resize((200, 200), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                self._qr_label.configure(image=photo, text="")
                self._qr_label.image = photo  # 保持引用
            except Exception as e:
                log.warning("显示二维码失败: %s", e)
                self._qr_label.configure(text="二维码显示失败，请查看控制台")

            self._status_var.set("请使用米家 App 扫描二维码")

            # 开始等待扫码
            self._current_thread = threading.Thread(
                target=self._wait_for_scan_thread, daemon=True
            )
            self._current_thread.start()
        else:
            self._qr_label.configure(text="获取二维码失败")
            self._status_var.set(result.message)

    def _wait_for_scan_thread(self) -> None:
        """等待扫码线程。"""
        try:
            result = self._auth.wait_for_scan()
            if self._is_closing:
                return
            self._root.after(0, lambda: self._handle_login_result(result))
        except Exception as e:
            if self._is_closing:
                return
            self._root.after(0, lambda: self._handle_login_error(str(e)))

    def _handle_login_result(self, result: LoginResult) -> None:
        """处理登录结果。"""
        if result.success:
            self._status_var.set("登录成功，正在获取设备列表...")
            self._current_thread = threading.Thread(
                target=self._fetch_devices_thread, daemon=True
            )
            self._current_thread.start()
        else:
            self._status_var.set(f"登录失败: {result.message}")
            if hasattr(self, "_login_btn"):
                self._login_btn.configure(state="normal")

    def _fetch_devices_thread(self) -> None:
        """获取设备列表线程。"""
        try:
            devices = self._auth.get_devices()
            if self._is_closing:
                return
            self._root.after(0, lambda: self._show_device_selection(devices))
        except Exception as e:
            if self._is_closing:
                return
            self._root.after(
                0,
                lambda: self._handle_login_error(f"获取设备失败: {e}"),
            )

    def _show_device_selection(self, devices: List[XiaomiDeviceInfo]) -> None:
        """显示设备选择界面。"""
        self._clear_content()

        if not devices:
            ttk.Label(
                self._content_frame,
                text="未找到任何设备",
                font=("Microsoft YaHei UI", 11),
            ).pack(pady=16)
            ttk.Button(
                self._content_frame,
                text="返回",
                command=self._show_login_method_selection,
            ).pack()
            return

        ttk.Label(
            self._content_frame,
            text="请选择设备",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=(0, 12))

        # 设备列表
        listbox_frame = ttk.Frame(self._content_frame)
        listbox_frame.pack(fill="both", expand=True, pady=(0, 12))

        scrollbar = ttk.Scrollbar(listbox_frame)
        scrollbar.pack(side="right", fill="y")

        self._device_listbox = tk.Listbox(
            listbox_frame,
            yscrollcommand=scrollbar.set,
            font=("Microsoft YaHei UI", 10),
            selectmode="single",
        )
        self._device_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._device_listbox.yview)

        self._devices = devices
        for i, device in enumerate(devices):
            display_text = f"{device.name} ({device.model or '未知型号'}) - {device.localip}"
            self._device_listbox.insert(tk.END, display_text)

        # 选择第一个
        if devices:
            self._device_listbox.selection_set(0)

        # 按钮
        btn_frame = ttk.Frame(self._content_frame)
        btn_frame.pack(pady=(0, 0))

        ttk.Button(
            btn_frame, text="取消", command=self._close
        ).pack(side="left", padx=4)

        ttk.Button(
            btn_frame, text="确认选择", command=self._on_device_selected
        ).pack(side="left", padx=4)

    def _on_device_selected(self) -> None:
        """设备选择确认按钮点击事件。"""
        selection = self._device_listbox.curselection()
        if not selection:
            messagebox.showwarning("未选择", "请选择一个设备", parent=self._root)
            return

        device = self._devices[selection[0]]
        self._on_success(device)
        self._close()

    def _handle_login_error(self, error_message: str) -> None:
        """处理登录错误。"""
        self._status_var.set(f"错误: {error_message}")
        if hasattr(self, "_login_btn"):
            self._login_btn.configure(state="normal")

    def _close(self) -> None:
        """关闭窗口。"""
        self._is_closing = True
        try:
            self._root.destroy()
        except tk.TclError:
            pass
        if self._on_cancel:
            self._on_cancel()
