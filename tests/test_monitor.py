import unittest
from unittest.mock import Mock, patch

from szu_sentinel.models import AppConfig
from szu_sentinel.monitor import (
    MonitorController,
    MonitorEvent,
    OFFLINE_RETRY_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
)
from szu_sentinel.network import ConnectionResult


class MonitorControllerTests(unittest.TestCase):
    def test_offline_triggers_fast_retry(self):
        events = []
        mock_client = Mock()
        mock_client.ensure_connected.return_value = ConnectionResult(False, "连接超时")

        controller = MonitorController(
            event_callback=events.append,
            client_factory=lambda: mock_client,
        )

        with patch.object(controller._wake_event, "wait") as mock_wait:
            def stop_on_wait(seconds):
                controller._stop_event.set()

            mock_wait.side_effect = stop_on_wait
            controller._run_loop(AppConfig(username="u", password="p", interval_minutes=5))

            mock_wait.assert_called_once_with(OFFLINE_RETRY_SECONDS)

        states = [e.state for e in events]
        self.assertIn("offline", states)
        self.assertIn("waiting", states)

    def test_online_waits_configured_interval(self):
        events = []
        mock_client = Mock()
        mock_client.ensure_connected.return_value = ConnectionResult(True, "网络连接正常")

        controller = MonitorController(
            event_callback=events.append,
            client_factory=lambda: mock_client,
        )

        with patch.object(controller._wake_event, "wait") as mock_wait:
            def stop_on_wait(seconds):
                controller._stop_event.set()

            mock_wait.side_effect = stop_on_wait
            controller._run_loop(AppConfig(username="u", password="p", interval_minutes=5))

            mock_wait.assert_called_once_with(HEARTBEAT_INTERVAL_SECONDS)

        states = [e.state for e in events]
        self.assertIn("online", states)
        self.assertIn("waiting", states)

    def test_heartbeat_detects_disconnect_and_triggers_reconnect(self):
        events = []
        mock_client = Mock()
        mock_client.ensure_connected.side_effect = [
            ConnectionResult(True, "网络连接正常"),
            ConnectionResult(True, "已自动重连"),
        ]
        # First heartbeat detects session expired
        mock_client.heartbeat.return_value = False

        controller = MonitorController(
            event_callback=events.append,
            client_factory=lambda: mock_client,
        )

        call_count = 0
        with patch.object(controller._wake_event, "wait") as mock_wait:
            def wait_side_effect(seconds):
                nonlocal call_count
                call_count += 1
                if call_count >= 2:
                    controller._stop_event.set()
                return False

            mock_wait.side_effect = wait_side_effect
            controller._run_loop(AppConfig(username="u", password="p", interval_minutes=5))

        states = [e.state for e in events]
        self.assertIn("reconnecting", states)
        self.assertEqual(mock_client.ensure_connected.call_count, 2)


if __name__ == "__main__":
    unittest.main()
