"""Token extractor 类型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class XiaomiDeviceInfo:
    """小米设备信息。"""
    name: str
    did: str
    token: str
    localip: str
    mac: Optional[str] = None
    model: Optional[str] = None
    device_id: Optional[int] = None

    def is_valid(self) -> bool:
        """检查设备信息是否有效（必须有 token 和 IP）。"""
        return bool(self.token and self.localip)


@dataclass
class LoginResult:
    """登录结果。"""
    success: bool
    message: str
    session_data: Optional[Dict[str, Any]] = None
    qr_image_data: Optional[bytes] = None  # 二维码登录时的图像数据
