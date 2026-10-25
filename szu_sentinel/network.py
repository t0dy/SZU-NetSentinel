from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import requests
import urllib3

from .direct_network import DirectRoute
from .models import (
    AppConfig,
    ZONE_AUTO,
    ZONE_DORMITORY,
    ZONE_OFFICE,
)
from .srun import SrunClient


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DORMITORY_LOGIN_URL = "http://172.30.255.42:801/eportal/portal/login/"

MICROSOFT_CHECK_URL = "http://www.msftconnecttest.com/connecttest.txt"
MICROSOFT_CHECK_TEXT = "Microsoft Connect Test"
CLOUDFLARE_204_URL = "http://cp.cloudflare.com/generate_204"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    )
}

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    connected: bool
    message: str
    latency_ms: int | None = None
    extra_info: str | None = None


def _new_direct_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(HEADERS)
    return session


def _parse_jsonp_object(text: str) -> dict[str, object]:
    match = re.search(r"^[^(]*\((.*)\)\s*;?\s*$", text.strip(), re.DOTALL)
    if not match:
        raise ConnectionError("宿舍区认证服务器返回了无法识别的数据")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ConnectionError("宿舍区认证服务器返回了无效 JSON") from exc
    if not isinstance(payload, dict):
        raise ConnectionError("宿舍区认证响应格式不正确")
    return payload


class NetworkClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        portal_session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        verify_delays: tuple[float, ...] = (2.0, 3.0, 5.0, 8.0),
    ):
        self.session = session or _new_direct_session()
        self.portal_session = portal_session or (
            session if session is not None else _new_direct_session()
        )
        for active_session in {id(self.session): self.session, id(self.portal_session): self.portal_session}.values():
            active_session.trust_env = False
            active_session.headers.update(HEADERS)
        self.sleeper = sleeper
        self.verify_delays = verify_delays
        self._allow_direct_setup = session is None and portal_session is None
        self.direct_route: DirectRoute | None = None
        self.active_zone: str | None = None

    def _configure_direct(self, enabled: bool) -> None:
        if not enabled or not self._allow_direct_setup or self.direct_route:
            return
        try:
            route = DirectRoute.discover()
            self.direct_route = route
            self.session = route.session()
            self.portal_session = route.session()
            self.session.headers.update(HEADERS)
            self.portal_session.headers.update(HEADERS)
        except Exception:
            # 在某些电脑或网络环境下若直连路由初始化受阻，平滑降级使用标准网络会话
            self.direct_route = None

    def _get_check_target(self, url: str) -> requests.Response:
        if self.direct_route:
            try:
                direct_url, original_host = self.direct_route.rewrite_url(url)
                return self.session.get(
                    direct_url,
                    headers={"Host": original_host},
                    timeout=(3, 5),
                    allow_redirects=False,
                    verify=False,
                )
            except Exception:
                pass
        return self.session.get(
            url,
            timeout=(3, 5),
            allow_redirects=True,
        )

    def check_connection(self) -> ConnectionResult:
        started = time.perf_counter()
        errors: list[str] = []
        probes = (
            (MICROSOFT_CHECK_URL, 200, MICROSOFT_CHECK_TEXT),
            (CLOUDFLARE_204_URL, 204, None),
        )

        for url, expected_code, expected_text in probes:
            try:
                response = self._get_check_target(url)
                location = response.headers.get("Location", "") if hasattr(response, "headers") else ""
                final_url = getattr(response, "url", "")
                history = getattr(response, "history", None)
                history_locs = (
                    [h.headers.get("Location", "") for h in history if hasattr(h, "headers")]
                    if isinstance(history, (list, tuple))
                    else []
                )
                all_indicators = [location, final_url] + history_locs
                if any(
                    any(kw in str(ind) for kw in ("172.30.255.42", "net.szu.edu.cn", "eportal", "srun", "ac_id"))
                    for ind in all_indicators
                ):
                    return ConnectionResult(False, "检测到校园网认证重定向，需要登录")

                valid = (
                    response.status_code == expected_code
                    and (expected_text is None or expected_text in response.text)
                )
                if valid:
                    latency = round((time.perf_counter() - started) * 1000)
                    mode = "（校园网直连）" if self.direct_route else ""
                    return ConnectionResult(True, f"网络连接正常{mode}", latency)
                errors.append(f"返回码 {response.status_code}")
            except requests.RequestException as exc:
                errors.append(type(exc).__name__)

        detail = " / ".join(errors[-2:]) if errors else "无响应"
        return ConnectionResult(False, f"直连外网不可用（{detail}）")

    def heartbeat(self, config: AppConfig) -> bool:
        """Send a periodic lightweight keepalive pulse to prevent gateway idle timeout and check status."""
        self._configure_direct(config.direct_mode)
        effective_zone = config.zone
        if effective_zone == ZONE_AUTO:
            effective_zone = getattr(self, "active_zone", None) or ZONE_OFFICE

        if effective_zone == ZONE_OFFICE:
            status = self._teaching_online_status(config)
            if status is False:
                return False

        try:
            response = self._get_check_target(MICROSOFT_CHECK_URL)
            if response.status_code == 200 and MICROSOFT_CHECK_TEXT in response.text:
                return True
        except Exception:
            pass
        return True

    def _teaching_srun_client(self, config: AppConfig) -> SrunClient:
        base_url = "https://net.szu.edu.cn"
        host_header = None
        if self.direct_route:
            teaching_ip = self.direct_route.resolve("net.szu.edu.cn")[0]
            base_url = f"https://{teaching_ip}"
            host_header = "net.szu.edu.cn"
        return SrunClient(
            config.username,
            config.password,
            session=self.portal_session,
            base_url=base_url,
            host_header=host_header,
        )

    def _teaching_online_status(self, config: AppConfig) -> bool | None:
        try:
            return self._teaching_srun_client(config).is_online()
        except (ConnectionError, requests.RequestException):
            return None

    def _login_dormitory(self, config: AppConfig) -> str:
        response = self.portal_session.get(
            DORMITORY_LOGIN_URL,
            params={
                "user_account": config.username,
                "user_password": config.password,
            },
            timeout=(4, 10),
            allow_redirects=True,
        )
        response.raise_for_status()
        payload = _parse_jsonp_object(response.text)
        message = str(payload.get("msg", "")).strip()
        success = (
            payload.get("result") in (1, "1", True)
            or "success" in message.lower()
            or "成功" in message
            or "已经在线" in message
            or "已在线" in message
            or "已经登录" in message
            or "已登录" in message
            or "already" in message.lower()
        )
        if not success:
            raise ConnectionError(message or "宿舍区认证失败，请检查账号和密码")
        return message or "宿舍区认证成功"

    def _login_teaching(self, config: AppConfig) -> str:
        result = self._teaching_srun_client(config).login()
        if not result.success:
            raise ConnectionError(
                f"教学 / 办公区认证失败：{result.message or '请检查账号和密码'}"
            )
        return result.message

    def _detect_captive_redirect(self) -> str | None:
        targets = (
            MICROSOFT_CHECK_URL,
            "http://1.1.1.1/",
            "http://connectivitycheck.gstatic.com/generate_204",
        )
        for url in targets:
            try:
                response = self._get_check_target(url)
                indicators = []
                if hasattr(response, "headers"):
                    indicators.append(response.headers.get("Location", ""))
                indicators.append(getattr(response, "url", ""))
                history = getattr(response, "history", None)
                if isinstance(history, (list, tuple)):
                    for hist in history:
                        if hasattr(hist, "headers"):
                            indicators.append(hist.headers.get("Location", ""))
                        if hasattr(hist, "url"):
                            indicators.append(str(hist.url))
                combined = (" ".join(str(ind) for ind in indicators) + " " + getattr(response, "text", "")).lower()
                if "172.30.255.42" in combined or "eportal" in combined:
                    return ZONE_DORMITORY
                if "net.szu.edu.cn" in combined or "srun" in combined or "172.31.63.36" in combined:
                    return ZONE_OFFICE
            except Exception:
                continue
        return None

    def detect_zone(self, config: AppConfig) -> str:
        """Automatically identify the current campus network zone (office vs dormitory)."""
        # 1. 优先通过 Captive Portal 重定向目标判定（最直接的网关指令）
        captive_zone = self._detect_captive_redirect()
        if captive_zone:
            self.active_zone = captive_zone
            return captive_zone

        # 2. 检查本机物理网卡获取的真实校园网 IP 网段（0ms 即时精确识别，极度适用于不同电脑）
        try:
            from .direct_network import local_ipv4_candidates

            for ip in local_ipv4_candidates():
                if ip.startswith("172.30."):
                    self.active_zone = ZONE_DORMITORY
                    return ZONE_DORMITORY
                if ip.startswith("172.31.") or ip.startswith("172.28."):
                    self.active_zone = ZONE_OFFICE
                    return ZONE_OFFICE
        except Exception:
            pass

        # 3. 主动轻量探测网关特征
        # 探测宿舍区 ePortal 网关 (172.30.255.42:801)
        try:
            dorm_res = self.portal_session.get(
                DORMITORY_LOGIN_URL,
                timeout=(1.5, 2.5),
                allow_redirects=False,
            )
            if dorm_res.status_code == 200 and (
                "jsonp" in dorm_res.text or "result" in dorm_res.text or "eportal" in dorm_res.text
            ):
                self.active_zone = ZONE_DORMITORY
                return ZONE_DORMITORY
        except Exception:
            pass

        # 探测教学/办公区 SRun 网关
        try:
            if self._teaching_online_status(config) is True:
                self.active_zone = ZONE_OFFICE
                return ZONE_OFFICE
        except Exception:
            pass

        try:
            srun_client = self._teaching_srun_client(config)
            ac_id = srun_client.discover_ac_id()
            if ac_id and ac_id != "1":
                self.active_zone = ZONE_OFFICE
                return ZONE_OFFICE
        except Exception:
            pass

        if getattr(self, "active_zone", None):
            return self.active_zone

        return ZONE_OFFICE

    def send_login(
        self,
        config: AppConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        zone = config.zone
        if zone == ZONE_AUTO:
            detected = self.detect_zone(config)
            zone_desc = "教学 / 办公区" if detected == ZONE_OFFICE else "宿舍区"
            if progress_callback:
                progress_callback(f"自动识别区域：{zone_desc}，正在尝试认证…")

            if detected == ZONE_DORMITORY:
                attempts = (
                    ("宿舍区", ZONE_DORMITORY, self._login_dormitory),
                    ("教学 / 办公区", ZONE_OFFICE, self._login_teaching),
                )
            else:
                attempts = (
                    ("教学 / 办公区", ZONE_OFFICE, self._login_teaching),
                    ("宿舍区", ZONE_DORMITORY, self._login_dormitory),
                )

            errors: list[str] = []
            for zone_name, cand_zone, login in attempts:
                if progress_callback and zone_name != attempts[0][0]:
                    progress_callback(f"正在自动切换至{zone_name}认证…")
                try:
                    result = login(config)
                    self.active_zone = cand_zone
                    return result
                except (ConnectionError, requests.RequestException) as exc:
                    errors.append(f"{zone_name}：{exc}")

            details = "；".join(errors)
            raise ConnectionError(
                f"自动识别并尝试均未成功，请检查账号密码或手动选择区域。{details}"
            )

        if progress_callback:
            zone_name = "宿舍区" if zone == ZONE_DORMITORY else "教学 / 办公区"
            progress_callback(f"正在使用{zone_name}认证…")

        if zone == ZONE_DORMITORY:
            self.active_zone = ZONE_DORMITORY
            return self._login_dormitory(config)
        if zone == ZONE_OFFICE:
            self.active_zone = ZONE_OFFICE
            return self._login_teaching(config)
        raise ConnectionError("无法确定校园网区域")

    def ensure_connected(
        self,
        config: AppConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> ConnectionResult:
        self._configure_direct(config.direct_mode)

        effective_zone = config.zone
        if effective_zone == ZONE_AUTO:
            effective_zone = getattr(self, "active_zone", None) or self.detect_zone(config)

        authentication_expired = False
        if effective_zone == ZONE_OFFICE:
            authentication_expired = self._teaching_online_status(config) is False
            if authentication_expired and progress_callback:
                progress_callback("检测到教学/办公区校园网认证已失效，正在重新认证…")

        if not authentication_expired:
            current = self.check_connection()
            if current.connected:
                extra_info = None
                if effective_zone == ZONE_OFFICE:
                    info = self._teaching_srun_client(config).get_user_info()
                    if info:
                        extra_info = f"账号 {info.username} | IP {info.client_ip} | 已用流量 {info.formatted_bytes} | 在线设备 {info.online_devices}台"
                zone_desc = "教学/办公区" if effective_zone == ZONE_OFFICE else "宿舍区"
                zone_tag = f"（自动识别：{zone_desc}）" if config.zone == ZONE_AUTO else ""
                msg = f"{current.message}{zone_tag}" if zone_tag and zone_tag not in current.message else current.message
                return ConnectionResult(
                    True,
                    msg,
                    current.latency_ms,
                    extra_info=extra_info,
                )

        login_message = self.send_login(config, progress_callback)
        if progress_callback:
            progress_callback(f"{login_message}，正在等待外网恢复…")

        for attempt, delay in enumerate(self.verify_delays, start=1):
            self.sleeper(delay)
            verified = self.check_connection()
            if verified.connected:
                resolved_zone = getattr(self, "active_zone", None) or effective_zone
                extra_info = None
                if resolved_zone == ZONE_OFFICE:
                    info = self._teaching_srun_client(config).get_user_info()
                    if info:
                        extra_info = f"账号 {info.username} | IP {info.client_ip} | 已用流量 {info.formatted_bytes} | 在线设备 {info.online_devices}台"
                zone_desc = "教学/办公区" if resolved_zone == ZONE_OFFICE else "宿舍区"
                zone_tag = f"（自动识别：{zone_desc}）" if config.zone == ZONE_AUTO else ""
                return ConnectionResult(
                    True,
                    f"已自动重连，网络恢复正常{zone_tag}",
                    verified.latency_ms,
                    extra_info=extra_info,
                )
            if progress_callback and attempt < len(self.verify_delays):
                progress_callback(
                    f"外网尚未恢复，{self.verify_delays[attempt]:g} 秒后再次复查…"
                )

        return ConnectionResult(
            False,
            "认证服务器已确认请求，但外网仍不可用；请查看本地日志中的认证结果",
        )
