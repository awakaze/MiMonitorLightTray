"""测试 token_extractor 类型定义。"""

import pytest
from mi_monitor_light_tray.token_extractor.types import XiaomiDeviceInfo, LoginResult


class TestXiaomiDeviceInfo:
    """测试 XiaomiDeviceInfo 数据类。"""

    def test_create_valid_device(self):
        """测试创建有效设备信息。"""
        device = XiaomiDeviceInfo(
            name="测试灯",
            did="123456",
            token="abcdef1234567890abcdef1234567890",
            localip="192.168.1.100"
        )
        assert device.name == "测试灯"
        assert device.did == "123456"
        assert device.token == "abcdef1234567890abcdef1234567890"
        assert device.localip == "192.168.1.100"
        assert device.mac is None
        assert device.model is None

    def test_is_valid_with_token_and_ip(self):
        """测试有 token 和 IP 时返回有效。"""
        device = XiaomiDeviceInfo(
            name="灯",
            did="123",
            token="abc",
            localip="192.168.1.1"
        )
        assert device.is_valid() is True

    def test_is_valid_without_token(self):
        """测试无 token 时返回无效。"""
        device = XiaomiDeviceInfo(
            name="灯",
            did="123",
            token="",
            localip="192.168.1.1"
        )
        assert device.is_valid() is False

    def test_is_valid_without_ip(self):
        """测试无 IP 时返回无效。"""
        device = XiaomiDeviceInfo(
            name="灯",
            did="123",
            token="abc",
            localip=""
        )
        assert device.is_valid() is False


class TestLoginResult:
    """测试 LoginResult 数据类。"""

    def test_create_success_result(self):
        """测试创建成功结果。"""
        result = LoginResult(
            success=True,
            message="登录成功",
            session_data={"key": "value"}
        )
        assert result.success is True
        assert result.message == "登录成功"
        assert result.session_data == {"key": "value"}
        assert result.qr_image_data is None

    def test_create_failure_result(self):
        """测试创建失败结果。"""
        result = LoginResult(success=False, message="密码错误")
        assert result.success is False
        assert result.message == "密码错误"
        assert result.session_data is None
