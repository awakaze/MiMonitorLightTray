"""小米云认证模块。"""

from __future__ import annotations

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from .core import XiaomiCloudConnector
from .types import LoginResult, XiaomiDeviceInfo

log = logging.getLogger(__name__)


class XiaomiAuth(ABC):
    """小米认证基类。"""

    def __init__(self) -> None:
        """初始化认证器。"""
        self._connector = XiaomiCloudConnector()
        self._session = requests.Session()

    @abstractmethod
    def login(self) -> LoginResult:
        """执行登录流程。

        Returns:
            登录结果
        """
        pass

    def get_devices(self) -> List[XiaomiDeviceInfo]:
        """获取所有服务器的设备列表。

        Returns:
            设备信息列表
        """
        devices: List[XiaomiDeviceInfo] = []
        for server in XiaomiCloudConnector.SERVERS:
            try:
                homes_data = self._connector.get_homes(server)
                if homes_data and "result" in homes_data:
                    for home in homes_data["result"].get("homelist", []):
                        home_id = home.get("id")
                        owner_id = self._connector._user_id
                        if home_id and owner_id:
                            dev_data = self._connector.get_devices(
                                server, home_id, owner_id
                            )
                            if dev_data and "result" in dev_data:
                                for dev in dev_data["result"].get(
                                    "device_info", []
                                ):
                                    device = XiaomiDeviceInfo(
                                        name=dev.get("name", "未知设备"),
                                        did=dev.get("did", ""),
                                        token=dev.get("token", ""),
                                        localip=dev.get("localip", ""),
                                        mac=dev.get("mac"),
                                        model=dev.get("model"),
                                    )
                                    if device.is_valid():
                                        devices.append(device)
            except Exception as e:
                log.warning("获取服务器 %s 设备失败: %s", server, e)
        return devices


class PasswordAuth(XiaomiAuth):
    """用户名密码认证。"""

    def __init__(self, username: str, password: str) -> None:
        """初始化密码认证器。

        Args:
            username: 用户名（邮箱/手机号/用户 ID）
            password: 密码
        """
        super().__init__()
        self._username = username
        self._password = password
        self._sign: Optional[str] = None
        self._ssecurity: Optional[str] = None
        self._user_id: Optional[str] = None
        self._c_user_id: Optional[str] = None
        self._pass_token: Optional[str] = None
        self._location: Optional[str] = None
        self._code: Optional[str] = None

    def login(self) -> LoginResult:
        """执行密码登录流程。

        Returns:
            登录结果
        """
        log.info("开始密码登录: %s", self._username)

        # 设置 cookies
        self._session.cookies.set(
            "sdkVersion", "accountsdk-18.8.15", domain="mi.com"
        )
        self._session.cookies.set(
            "sdkVersion", "accountsdk-18.8.15", domain="xiaomi.com"
        )
        self._session.cookies.set(
            "deviceId", self._connector._device_id, domain="mi.com"
        )
        self._session.cookies.set(
            "deviceId", self._connector._device_id, domain="xiaomi.com"
        )

        # 步骤1：获取签名
        if not self.login_step_1():
            return LoginResult(success=False, message="用户名无效")

        # 步骤2：验证密码
        if not self.login_step_2():
            return LoginResult(success=False, message="用户名或密码错误")

        # 步骤3：获取 service token
        if self._location and not self._connector._service_token:
            if not self.login_step_3():
                return LoginResult(
                    success=False, message="无法获取 service token"
                )

        # 设置连接器会话数据
        if self._ssecurity and self._connector._service_token and self._user_id:
            self._connector.set_session_data(
                self._ssecurity,
                self._connector._service_token,
                self._user_id,
            )
            return LoginResult(
                success=True,
                message="登录成功",
                session_data={
                    "ssecurity": self._ssecurity,
                    "service_token": self._connector._service_token,
                    "user_id": self._user_id,
                },
            )

        return LoginResult(success=False, message="登录失败")

    def login_step_1(self) -> bool:
        """步骤1：获取签名。

        Returns:
            是否成功
        """
        log.debug("login_step_1")
        url = "https://account.xiaomi.com/pass/serviceLogin?sid=xiaomiio&_json=true"
        headers = {
            "User-Agent": self._connector._agent,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        cookies = {"userId": self._username}
        response = self._session.get(url, headers=headers, cookies=cookies, timeout=10)
        log.debug("login_step_1 response: %s", response.text[:200])

        if response.status_code == 200:
            json_resp = XiaomiCloudConnector.to_json(response.text)
            if "_sign" in json_resp:
                self._sign = json_resp["_sign"]
                return True
            elif "ssecurity" in json_resp:
                self._ssecurity = json_resp["ssecurity"]
                self._user_id = str(json_resp.get("userId", ""))
                self._c_user_id = json_resp.get("cUserId")
                self._pass_token = json_resp.get("passToken")
                self._location = json_resp.get("location")
                self._code = json_resp.get("code")
                return True
        return False

    def login_step_2(self) -> bool:
        """步骤2：验证密码。

        Returns:
            是否成功
        """
        log.debug("login_step_2")
        url = "https://account.xiaomi.com/pass/serviceLoginAuth2"
        headers = {
            "User-Agent": self._connector._agent,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        fields = {
            "sid": "xiaomiio",
            "hash": hashlib.md5(self._password.encode()).hexdigest().upper(),
            "callback": "https://sts.api.io.mi.com/sts",
            "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
            "user": self._username,
            "_sign": self._sign,
            "_json": "true",
        }

        response = self._session.post(
            url, headers=headers, params=fields, allow_redirects=False, timeout=10
        )
        log.debug("login_step_2 response: %s", response.text[:200])

        if response is not None and response.status_code == 200:
            json_resp = XiaomiCloudConnector.to_json(response.text)
            valid = "ssecurity" in json_resp and len(str(json_resp["ssecurity"])) > 4
            if valid:
                self._ssecurity = json_resp["ssecurity"]
                self._user_id = str(json_resp.get("userId", ""))
                self._c_user_id = json_resp.get("cUserId")
                self._pass_token = json_resp.get("passToken")
                self._location = json_resp.get("location")
                self._code = json_resp.get("code")
                return True
            else:
                if "notificationUrl" in json_resp:
                    log.warning("需要 2FA 验证，暂不支持")
                    return False
        return False

    def login_step_3(self) -> bool:
        """步骤3：获取 service token。

        Returns:
            是否成功
        """
        log.debug("login_step_3")
        headers = {
            "User-Agent": self._connector._agent,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = self._session.get(self._location, headers=headers, timeout=10)
        log.debug("login_step_3 response status: %s", response.status_code)

        if response.status_code == 200:
            self._connector._service_token = response.cookies.get("serviceToken")
            return self._connector._service_token is not None
        return False


class QrCodeAuth(XiaomiAuth):
    """二维码认证。"""

    def __init__(self) -> None:
        """初始化二维码认证器。"""
        super().__init__()
        self._qr_image_url: Optional[str] = None
        self._login_url: Optional[str] = None
        self._long_polling_url: Optional[str] = None
        self._timeout: int = 300  # 5分钟超时

    def login(self) -> LoginResult:
        """执行二维码登录流程。

        Returns:
            登录结果（包含二维码图像数据）
        """
        log.info("开始二维码登录")

        # 步骤1：获取登录 URL
        if not self.login_step_1():
            return LoginResult(success=False, message="无法获取登录信息")

        # 步骤2：获取二维码图像
        qr_image_data = self.login_step_2()
        if qr_image_data is None:
            return LoginResult(success=False, message="无法获取二维码图像")

        return LoginResult(
            success=True,
            message="请扫描二维码登录",
            qr_image_data=qr_image_data,
            session_data={
                "login_url": self._login_url,
                "long_polling_url": self._long_polling_url,
                "timeout": self._timeout,
            },
        )

    def login_step_1(self) -> bool:
        """步骤1：获取登录 URL。

        Returns:
            是否成功
        """
        log.debug("login_step_1")
        url = "https://account.xiaomi.com/longPolling/loginUrl"
        data = {
            "_qrsize": "480",
            "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
            "callback": "https://sts.api.io.mi.com/sts",
            "_hasLogo": "false",
            "sid": "xiaomiio",
            "serviceParam": "",
            "_locale": "en_GB",
            "_dc": str(int(time.time() * 1000)),
        }

        response = self._session.get(url, params=data, timeout=10)
        log.debug("login_step_1 response: %s", response.text[:200])

        if response.status_code == 200:
            response_data = XiaomiCloudConnector.to_json(response.text)
            if "qr" in response_data:
                self._qr_image_url = response_data["qr"]
                self._login_url = response_data["loginUrl"]
                self._long_polling_url = response_data["lp"]
                self._timeout = int(response_data.get("timeout", 300))
                return True
        return False

    def login_step_2(self) -> Optional[bytes]:
        """步骤2：获取二维码图像。

        Returns:
            二维码图像数据，失败返回 None
        """
        log.debug("login_step_2")
        if not self._qr_image_url:
            return None

        response = self._session.get(self._qr_image_url, timeout=10)
        if response.status_code == 200:
            return response.content
        return None

    def wait_for_scan(self) -> LoginResult:
        """等待用户扫描二维码。

        Returns:
            登录结果
        """
        log.debug("等待扫码...")
        if not self._long_polling_url:
            return LoginResult(success=False, message="未初始化")

        start_time = time.time()
        while True:
            try:
                response = self._session.get(
                    self._long_polling_url, timeout=10
                )
            except requests.exceptions.Timeout:
                if time.time() - start_time > self._timeout:
                    return LoginResult(success=False, message="二维码已过期")
                continue
            except requests.exceptions.RequestException as e:
                return LoginResult(success=False, message=f"网络错误: {e}")

            if response.status_code == 200:
                response_data = XiaomiCloudConnector.to_json(response.text)
                self._connector._user_id = str(response_data.get("userId", ""))
                self._connector._ssecurity = response_data.get("ssecurity")
                location = response_data.get("location")

                if location:
                    # 获取 service token
                    resp = self._session.get(
                        location,
                        headers={
                            "content-type": "application/x-www-form-urlencoded"
                        },
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        self._connector._service_token = resp.cookies.get(
                            "serviceToken"
                        )
                        if self._connector._service_token:
                            return LoginResult(
                                success=True,
                                message="登录成功",
                                session_data={
                                    "ssecurity": self._connector._ssecurity,
                                    "service_token": self._connector._service_token,
                                    "user_id": self._connector._user_id,
                                },
                            )
                return LoginResult(success=False, message="登录失败")
            else:
                return LoginResult(
                    success=False,
                    message=f"轮询失败: {response.status_code}",
                )
