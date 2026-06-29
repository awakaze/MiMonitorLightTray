
"""小米云 API 核心连接器。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import time
from typing import Any, Dict, List, Optional

import requests

from .types import XiaomiDeviceInfo


class XiaomiCloudConnector:
    """小米云 API 连接器。"""

    SERVERS: List[str] = ["cn", "de", "us", "ru", "tw", "sg", "in", "i2"]

    def __init__(self) -> None:
        """初始化连接器。"""
        self._agent: str = self.generate_agent()
        self._device_id: str = self.generate_device_id()
        self._session: requests.Session = requests.Session()
        self._ssecurity: Optional[str] = None
        self._service_token: Optional[str] = None
        self._user_id: Optional[str] = None

    # ── 公共 API ──────────────────────────────────────────────────────

    def get_homes(self, country: str) -> Optional[Dict[str, Any]]:
        """获取家庭列表。

        Args:
            country: 服务器区域代码（cn, de, us 等）

        Returns:
            家庭列表数据，失败返回 None
        """
        url = self.get_api_url(country) + "/v2/homeroom/gethome"
        params = {
            "data": '{"fg": true, "fetch_share": true, "fetch_share_dev": true, "limit": 300, "app_ver": 7}'
        }
        return self.execute_api_call_encrypted(url, params)

    def get_devices(
        self, country: str, home_id: int, owner_id: int
    ) -> Optional[Dict[str, Any]]:
        """获取指定家庭的设备列表。

        Args:
            country: 服务器区域代码
            home_id: 家庭 ID
            owner_id: 家庭所有者 ID

        Returns:
            设备列表数据，失败返回 None
        """
        url = self.get_api_url(country) + "/v2/home/home_device_list"
        params = {
            "data": (
                '{"home_owner": ' + str(owner_id) +
                ',"home_id": ' + str(home_id) +
                ', "limit": 200, "get_split_device": true, "support_smart_home": true}'
            )
        }
        return self.execute_api_call_encrypted(url, params)

    def get_dev_cnt(self, country: str) -> Optional[Dict[str, Any]]:
        """获取设备数量。

        Args:
            country: 服务器区域代码

        Returns:
            设备数量数据，失败返回 None
        """
        url = self.get_api_url(country) + "/v2/user/get_device_cnt"
        params = {"data": '{ "fetch_own": true, "fetch_share": true}'}
        return self.execute_api_call_encrypted(url, params)

    def get_beaconkey(
        self, country: str, did: str
    ) -> Optional[Dict[str, Any]]:
        """获取 BLE 设备的 beaconkey。

        Args:
            country: 服务器区域代码
            did: 设备 ID

        Returns:
            beaconkey 数据，失败返回 None
        """
        url = self.get_api_url(country) + "/v2/device/blt_get_beaconkey"
        params = {"data": '{"did":"' + did + '","pdid":1}'}
        return self.execute_api_call_encrypted(url, params)

    def execute_api_call_encrypted(
        self, url: str, params: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """执行加密 API 调用。

        Args:
            url: API URL
            params: 请求参数

        Returns:
            解密后的响应数据，失败返回 None
        """
        headers = {
            "Accept-Encoding": "identity",
            "User-Agent": self._agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
            "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
        }
        cookies = {
            "userId": str(self._user_id),
            "yetAnotherServiceToken": str(self._service_token),
            "serviceToken": str(self._service_token),
            "locale": "en_GB",
            "timezone": "GMT+02:00",
            "is_daylight": "1",
            "dst_offset": "3600000",
            "channel": "MI_APP_STORE",
        }
        millis = round(time.time() * 1000)
        nonce = self.generate_nonce(millis)
        signed_nonce = self.signed_nonce(nonce)
        fields = self.generate_enc_params(
            url, "POST", signed_nonce, nonce, params, self._ssecurity
        )
        response = self._session.post(
            url, headers=headers, cookies=cookies, params=fields
        )
        if response.status_code == 200:
            decoded = self.decrypt_rc4(
                self.signed_nonce(fields["_nonce"]), response.text
            )
            return json.loads(decoded)
        return None

    def set_session_data(
        self,
        ssecurity: str,
        service_token: str,
        user_id: str,
    ) -> None:
        """设置会话数据（登录成功后调用）。

        Args:
            ssecurity: 安全密钥
            service_token: 服务 token
            user_id: 用户 ID
        """
        self._ssecurity = ssecurity
        self._service_token = service_token
        self._user_id = user_id

    # ── 静态工具方法 ──────────────────────────────────────────────────

    @staticmethod
    def get_api_url(country: str) -> str:
        """获取 API URL。

        Args:
            country: 服务器区域代码

        Returns:
            完整的 API URL
        """
        return "https://" + ("" if country == "cn" else (country + ".")) + "api.io.mi.com/app"

    def signed_nonce(self, nonce: str) -> str:
        """生成签名 nonce。

        Args:
            nonce: 原始 nonce

        Returns:
            签名后的 nonce
        """
        hash_object = hashlib.sha256(
            base64.b64decode(self._ssecurity) + base64.b64decode(nonce)
        )
        return base64.b64encode(hash_object.digest()).decode("utf-8")

    @staticmethod
    def signed_nonce_sec(nonce: str, ssecurity: str) -> str:
        """使用指定安全密钥生成签名 nonce。

        Args:
            nonce: 原始 nonce
            ssecurity: 安全密钥

        Returns:
            签名后的 nonce
        """
        hash_object = hashlib.sha256(
            base64.b64decode(ssecurity) + base64.b64decode(nonce)
        )
        return base64.b64encode(hash_object.digest()).decode("utf-8")

    @staticmethod
    def generate_nonce(millis: int) -> str:
        """生成 nonce。

        Args:
            millis: 毫秒时间戳

        Returns:
            Base64 编码的 nonce
        """
        nonce_bytes = os.urandom(8) + (int(millis / 60000)).to_bytes(
            4, byteorder="big"
        )
        return base64.b64encode(nonce_bytes).decode()

    @staticmethod
    def generate_agent() -> str:
        """生成 User-Agent 字符串。

        Returns:
            随机生成的 User-Agent
        """
        agent_id = "".join(
            map(lambda i: chr(i), [random.randint(65, 69) for _ in range(13)])
        )
        random_text = "".join(
            map(lambda i: chr(i), [random.randint(97, 122) for _ in range(18)])
        )
        return f"{random_text}-{agent_id} APP/com.xiaomi.mihome APPV/10.5.201"

    @staticmethod
    def generate_device_id() -> str:
        """生成设备 ID。

        Returns:
            6 位随机小写字母字符串
        """
        return "".join(
            map(lambda i: chr(i), [random.randint(97, 122) for _ in range(6)])
        )

    @staticmethod
    def generate_signature(
        url: str, signed_nonce: str, nonce: str, params: Dict[str, str]
    ) -> str:
        """生成 API 签名。

        Args:
            url: API URL
            signed_nonce: 签名 nonce
            nonce: 原始 nonce
            params: 请求参数

        Returns:
            Base64 编码的签名
        """
        signature_params = [url.split("com")[1], signed_nonce, nonce]
        for k, v in params.items():
            signature_params.append(f"{k}={v}")
        signature_string = "&".join(signature_params)
        signature = hmac.new(
            base64.b64decode(signed_nonce),
            msg=signature_string.encode(),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(signature.digest()).decode()

    @staticmethod
    def generate_enc_signature(
        url: str, method: str, signed_nonce: str, params: Dict[str, str]
    ) -> str:
        """生成加密 API 签名。

        Args:
            url: API URL
            method: HTTP 方法
            signed_nonce: 签名 nonce
            params: 请求参数

        Returns:
            Base64 编码的签名
        """
        signature_params = [
            str(method).upper(),
            url.split("com")[1].replace("/app/", "/"),
        ]
        for k, v in params.items():
            signature_params.append(f"{k}={v}")
        signature_params.append(signed_nonce)
        signature_string = "&".join(signature_params)
        return base64.b64encode(
            hashlib.sha1(signature_string.encode("utf-8")).digest()
        ).decode()

    @staticmethod
    def generate_enc_params(
        url: str,
        method: str,
        signed_nonce: str,
        nonce: str,
        params: Dict[str, str],
        ssecurity: str,
    ) -> Dict[str, str]:
        """生成加密 API 参数。

        Args:
            url: API URL
            method: HTTP 方法
            signed_nonce: 签名 nonce
            nonce: 原始 nonce
            params: 原始参数
            ssecurity: 安全密钥

        Returns:
            加密后的参数
        """
        params["rc4_hash__"] = XiaomiCloudConnector.generate_enc_signature(
            url, method, signed_nonce, params
        )
        for k, v in params.items():
            params[k] = XiaomiCloudConnector.encrypt_rc4(signed_nonce, v)
        params.update(
            {
                "signature": XiaomiCloudConnector.generate_enc_signature(
                    url, method, signed_nonce, params
                ),
                "ssecurity": ssecurity,
                "_nonce": nonce,
            }
        )
        return params

    @staticmethod
    def to_json(response_text: str) -> Dict[str, Any]:
        """解析响应 JSON。

        Args:
            response_text: 响应文本

        Returns:
            解析后的 JSON 对象
        """
        return json.loads(response_text.replace("&&&START&&&", ""))

    @staticmethod
    def encrypt_rc4(password: str, payload: str) -> str:
        """RC4 加密。

        Args:
            password: Base64 编码的密钥
            payload: 明文

        Returns:
            Base64 编码的密文
        """
        from Crypto.Cipher import ARC4

        r = ARC4.new(base64.b64decode(password))
        r.encrypt(bytes(1024))
        return base64.b64encode(r.encrypt(payload.encode())).decode()

    @staticmethod
    def decrypt_rc4(password: str, payload: str) -> bytes:
        """RC4 解密。

        Args:
            password: Base64 编码的密钥
            payload: Base64 编码的密文

        Returns:
            解密后的字节数据
        """
        from Crypto.Cipher import ARC4

        r = ARC4.new(base64.b64decode(password))
        r.encrypt(bytes(1024))
        return r.encrypt(base64.b64decode(payload))
