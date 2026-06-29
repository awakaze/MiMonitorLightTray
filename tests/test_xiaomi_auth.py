"""测试认证模块。"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from mi_monitor_light_tray.token_extractor.auth import PasswordAuth, QrCodeAuth
from mi_monitor_light_tray.token_extractor.types import LoginResult


class TestPasswordAuth:
    """测试密码认证。"""

    def test_init(self):
        """测试初始化。"""
        auth = PasswordAuth("test@example.com", "password123")
        assert auth._username == "test@example.com"
        assert auth._password == "password123"
        assert auth._connector is not None

    @patch("mi_monitor_light_tray.token_extractor.auth.requests.Session")
    def test_login_step_1_success(self, mock_session_class):
        """测试登录步骤1成功。"""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"_sign": "testsign123"}'
        mock_session.get.return_value = mock_response

        auth = PasswordAuth("test@example.com", "password")
        result = auth.login_step_1()

        assert result is True
        assert auth._sign == "testsign123"

    @patch("mi_monitor_light_tray.token_extractor.auth.requests.Session")
    def test_login_step_1_failure(self, mock_session_class):
        """测试登录步骤1失败。"""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"error": "invalid"}'
        mock_session.get.return_value = mock_response

        auth = PasswordAuth("test@example.com", "password")
        result = auth.login_step_1()

        assert result is False


class TestQrCodeAuth:
    """测试二维码认证。"""

    def test_init(self):
        """测试初始化。"""
        auth = QrCodeAuth()
        assert auth._connector is not None
        assert auth._qr_image_url is None
        assert auth._login_url is None
