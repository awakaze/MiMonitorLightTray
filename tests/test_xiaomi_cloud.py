"""测试 XiaomiCloudConnector 核心功能。"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from mi_monitor_light_tray.token_extractor.core import XiaomiCloudConnector


class TestXiaomiCloudConnectorStaticMethods:
    """测试静态工具方法。"""

    def test_generate_agent_format(self):
        """测试生成的 agent 字符串格式。"""
        agent = XiaomiCloudConnector.generate_agent()
        # 格式：随机字母-随机字母 APP/com.xiaomi.mihome APPV/10.5.201
        assert "APP/com.xiaomi.mihome" in agent
        assert "APPV/10.5.201" in agent

    def test_generate_device_id_length(self):
        """测试生成的设备 ID 长度。"""
        device_id = XiaomiCloudConnector.generate_device_id()
        assert len(device_id) == 6
        assert device_id.isalpha()
        assert device_id.islower()

    def test_generate_nonce_base64(self):
        """测试生成的 nonce 是有效 base64。"""
        import base64
        import time
        millis = int(time.time() * 1000)
        nonce = XiaomiCloudConnector.generate_nonce(millis)
        # 应该能成功解码
        decoded = base64.b64decode(nonce)
        assert len(decoded) == 12  # 8 bytes random + 4 bytes timestamp

    def test_encrypt_decrypt_rc4_roundtrip(self):
        """测试 RC4 加密解密往返。"""
        password = "dGVzdHNlY3VyaXR5"  # base64 encoded
        payload = "Hello, World!"
        encrypted = XiaomiCloudConnector.encrypt_rc4(password, payload)
        decrypted = XiaomiCloudConnector.decrypt_rc4(password, encrypted)
        assert decrypted.decode() == payload

    def test_get_api_url_cn(self):
        """测试中国服务器 URL。"""
        url = XiaomiCloudConnector.get_api_url("cn")
        assert url == "https://api.io.mi.com/app"

    def test_get_api_url_other(self):
        """测试其他服务器 URL。"""
        url = XiaomiCloudConnector.get_api_url("de")
        assert url == "https://de.api.io.mi.com/app"

    def test_signed_nonce_consistency(self):
        """测试签名 nonce 的一致性。"""
        import base64
        ssecurity = base64.b64encode(b"testsecurity").decode()
        nonce = base64.b64encode(b"testnonce1234").decode()
        signed1 = XiaomiCloudConnector.signed_nonce_sec(nonce, ssecurity)
        signed2 = XiaomiCloudConnector.signed_nonce_sec(nonce, ssecurity)
        assert signed1 == signed2


class TestXiaomiCloudConnectorInit:
    """测试连接器初始化。"""

    def test_connector_initialization(self):
        """测试连接器初始化状态。"""
        connector = XiaomiCloudConnector()
        assert connector._ssecurity is None
        assert connector._service_token is None
        assert connector._user_id is None
        assert connector._session is not None
