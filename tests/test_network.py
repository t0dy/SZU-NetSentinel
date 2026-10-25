import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from szu_sentinel.models import AppConfig, ZONE_AUTO, ZONE_DORMITORY
from szu_sentinel.network import ConnectionResult, NetworkClient


def response(url, status=200, text=""):
    value = Mock()
    value.url = url
    value.status_code = status
    value.text = text
    value.headers = {}
    value.raise_for_status.return_value = None
    return value


def connected_probe_response(url, **kwargs):
    if "msftconnecttest.com" in url:
        return response(url, text="Microsoft Connect Test")
    token = parse_qs(urlparse(url).query)["wd"][0]
    value = response(url, status=302, text=token)
    value.headers = {"Location": "https://wappass.baidu.com/captcha"}
    return value


class NetworkClientTests(unittest.TestCase):
    def test_online_does_not_send_login(self):
        session = Mock()
        session.headers = {}
        session.get.side_effect = connected_probe_response
        client = NetworkClient(
            session=session,
            portal_session=session,
            sleeper=lambda _: None,
        )

        result = client.ensure_connected(
            AppConfig(
                username="user",
                password="password",
                zone=ZONE_DORMITORY,
            )
        )

        self.assertTrue(result.connected)
        session.post.assert_not_called()

    def test_expired_teaching_session_reconnects_even_when_web_is_reachable(self):
        session = Mock()
        session.headers = {}
        client = NetworkClient(
            session=session,
            portal_session=session,
            sleeper=lambda _: None,
            verify_delays=(0,),
        )
        config = AppConfig(username="user", password="password")

        with (
            patch.object(client, "detect_zone", return_value="office"),
            patch.object(client, "_teaching_online_status", return_value=False),
            patch.object(
                client,
                "check_connection",
                return_value=ConnectionResult(True, "网络连接正常"),
            ) as check,
            patch.object(client, "send_login", return_value="认证成功") as login,
        ):
            result = client.ensure_connected(config)

        self.assertTrue(result.connected)
        login.assert_called_once_with(config, None)
        check.assert_called_once_with()

    def test_offline_sends_login_and_verifies(self):
        session = Mock()
        session.headers = {}
        calls = 0

        def offline_then_login_then_online(url, **kwargs):
            nonlocal calls
            calls += 1
            if calls <= 2:
                return response("http://portal.local", text="login")
            if calls == 3:
                return response(
                    "http://172.30.255.42:801/eportal/portal/login/",
                    text='jsonpReturn({"result":1,"msg":"认证成功"});',
                )
            return connected_probe_response(url)

        session.get.side_effect = offline_then_login_then_online
        client = NetworkClient(
            session=session,
            portal_session=session,
            sleeper=lambda _: None,
            verify_delays=(0,),
        )

        result = client.ensure_connected(
            AppConfig(
                username="user",
                password="password",
                zone="dormitory",
            )
        )

        self.assertTrue(result.connected)
        self.assertIn("自动重连", result.message)

    def test_auto_mode_tries_teaching_first(self):
        session = Mock()
        session.headers = {}
        client = NetworkClient(session=session, portal_session=session)
        config = AppConfig(
            username="user",
            password="password",
            zone=ZONE_AUTO,
        )

        with (
            patch.object(client, "detect_zone", return_value="office"),
            patch.object(
                client,
                "_login_teaching",
                return_value="教学区认证成功",
            ) as teaching,
            patch.object(client, "_login_dormitory") as dormitory,
        ):
            result = client.send_login(config)

        self.assertEqual(result, "教学区认证成功")
        teaching.assert_called_once_with(config)
        dormitory.assert_not_called()

    def test_auto_mode_falls_back_to_dormitory(self):
        session = Mock()
        session.headers = {}
        client = NetworkClient(session=session, portal_session=session)
        config = AppConfig(
            username="user",
            password="password",
            zone=ZONE_AUTO,
        )

        with (
            patch.object(client, "detect_zone", return_value="office"),
            patch.object(
                client,
                "_login_teaching",
                side_effect=ConnectionError("不在教学区"),
            ) as teaching,
            patch.object(
                client,
                "_login_dormitory",
                return_value="宿舍区认证成功",
            ) as dormitory,
        ):
            result = client.send_login(config)

        self.assertEqual(result, "宿舍区认证成功")
        teaching.assert_called_once_with(config)
        dormitory.assert_called_once_with(config)

    def test_detect_zone_recognizes_dormitory_captive_redirect(self):
        session = Mock()
        session.headers = {}
        redirect_resp = response("http://probe", status=302)
        redirect_resp.headers = {"Location": "http://172.30.255.42:801/eportal/index.jsp"}
        session.get.return_value = redirect_resp

        client = NetworkClient(session=session, portal_session=session)
        zone = client.detect_zone(AppConfig(username="u", password="p", zone=ZONE_AUTO))
        self.assertEqual(zone, ZONE_DORMITORY)

    def test_detect_zone_recognizes_teaching_captive_redirect(self):
        session = Mock()
        session.headers = {}
        redirect_resp = response("http://probe", status=302)
        redirect_resp.headers = {"Location": "https://net.szu.edu.cn/srun_portal_pc?ac_id=12"}
        session.get.return_value = redirect_resp

        client = NetworkClient(session=session, portal_session=session)
        zone = client.detect_zone(AppConfig(username="u", password="p", zone=ZONE_AUTO))
        self.assertEqual(zone, "office")

    def test_auto_mode_prioritizes_detected_dormitory(self):
        session = Mock()
        session.headers = {}
        client = NetworkClient(session=session, portal_session=session)
        config = AppConfig(username="u", password="p", zone=ZONE_AUTO)

        with (
            patch.object(client, "detect_zone", return_value=ZONE_DORMITORY),
            patch.object(client, "_login_dormitory", return_value="宿舍区认证成功") as dorm,
            patch.object(client, "_login_teaching") as teach,
        ):
            res = client.send_login(config)

        self.assertEqual(res, "宿舍区认证成功")
        dorm.assert_called_once_with(config)
        teach.assert_not_called()

    def test_heartbeat_returns_false_on_expired_session(self):
        client = NetworkClient()
        config = AppConfig(username="u", password="p", zone=ZONE_AUTO)
        with patch.object(client, "_teaching_online_status", return_value=False):
            self.assertFalse(client.heartbeat(config))

    @patch("szu_sentinel.direct_network.local_ipv4_candidates")
    def test_detect_zone_recognizes_dormitory_subnet(self, mock_candidates):
        mock_candidates.return_value = ["172.30.48.110"]
        session = Mock()
        session.headers = {}
        client = NetworkClient(session=session, portal_session=session)
        with patch.object(client, "_detect_captive_redirect", return_value=None):
            zone = client.detect_zone(AppConfig(username="u", password="p", zone=ZONE_AUTO))
        self.assertEqual(zone, ZONE_DORMITORY)

    @patch("szu_sentinel.direct_network.local_ipv4_candidates")
    def test_detect_zone_recognizes_teaching_subnet_172_31(self, mock_candidates):
        mock_candidates.return_value = ["172.31.123.92"]
        session = Mock()
        session.headers = {}
        client = NetworkClient(session=session, portal_session=session)
        with patch.object(client, "_detect_captive_redirect", return_value=None):
            zone = client.detect_zone(AppConfig(username="u", password="p", zone=ZONE_AUTO))
        self.assertEqual(zone, "office")

    @patch("szu_sentinel.direct_network.local_ipv4_candidates")
    def test_detect_zone_recognizes_teaching_subnet_172_28(self, mock_candidates):
        mock_candidates.return_value = ["172.28.10.55"]
        session = Mock()
        session.headers = {}
        client = NetworkClient(session=session, portal_session=session)
        with patch.object(client, "_detect_captive_redirect", return_value=None):
            zone = client.detect_zone(AppConfig(username="u", password="p", zone=ZONE_AUTO))
        self.assertEqual(zone, "office")

    @patch("szu_sentinel.direct_network.local_ipv4_candidates")
    def test_detect_zone_recognizes_dormitory_gateway_probe(self, mock_candidates):
        mock_candidates.return_value = ["192.168.1.100"]
        session = Mock()
        session.headers = {}
        probe_resp = response("http://172.30.255.42:801/eportal/portal/login/", status=200, text='{"result":0,"msg":"portal"}')
        session.get.return_value = probe_resp
        client = NetworkClient(session=session, portal_session=session)
        with patch.object(client, "_detect_captive_redirect", return_value=None):
            zone = client.detect_zone(AppConfig(username="u", password="p", zone=ZONE_AUTO))
        self.assertEqual(zone, ZONE_DORMITORY)

    @patch("szu_sentinel.direct_network.DirectRoute.discover")
    def test_configure_direct_handles_failure_gracefully(self, mock_discover):
        mock_discover.side_effect = RuntimeError("Socket or DNS binding failed")
        client = NetworkClient()
        client._configure_direct(True)
        self.assertIsNone(client.direct_route)


if __name__ == "__main__":
    unittest.main()
