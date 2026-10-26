from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Callable

from .memory import trim_memory
from .models import AppConfig
from .network import NetworkClient


@dataclass(frozen=True, slots=True)
class MonitorEvent:
    state: str
    message: str
    level: str = "info"
    latency_ms: int | None = None
    extra_info: str | None = None


OFFLINE_RETRY_SECONDS = 10
HEARTBEAT_INTERVAL_SECONDS = 30


class MonitorController:
    def __init__(
        self,
        event_callback: Callable[[MonitorEvent], None],
        client_factory: Callable[[], NetworkClient] = NetworkClient,
    ):
        self.event_callback = event_callback
        self.client_factory = client_factory
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, config: AppConfig) -> None:
        with self._lock:
            if self.running:
                self._wake_event.set()
                return
            self._stop_event.clear()
            self._wake_event.clear()
            copied = replace(config)
            self._thread = threading.Thread(
                target=self._run_loop,
                args=(copied,),
                name="szu-network-monitor",
                daemon=True,
            )
            self._thread.start()

    def check_now(self) -> None:
        if self.running:
            self._wake_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        else:
            self.event_callback(MonitorEvent("stopped", "监控已停止"))

    def _emit(self, event: MonitorEvent) -> None:
        self.event_callback(event)

    def _run_loop(self, config: AppConfig) -> None:
        client = self.client_factory()
        self._emit(MonitorEvent("checking", "正在检测网络状态…"))

        while not self._stop_event.is_set():
            self._wake_event.clear()
            is_connected = False
            try:
                result = client.ensure_connected(
                    config,
                    progress_callback=lambda message: self._emit(
                        MonitorEvent("reconnecting", message, "warning")
                    ),
                )
                is_connected = result.connected
                if result.connected:
                    self._emit(
                        MonitorEvent(
                            "online",
                            result.message,
                            "success",
                            result.latency_ms,
                            extra_info=result.extra_info,
                        )
                    )
                else:
                    self._emit(MonitorEvent("offline", result.message, "warning"))
            except Exception as exc:
                self._emit(
                    MonitorEvent(
                        "offline",
                        f"检测或重连失败：{exc}",
                        "error",
                    )
                )

            if self._stop_event.is_set():
                break

            if is_connected:
                trim_memory()
                self._emit(
                    MonitorEvent(
                        "waiting",
                        f"下次检测将在 {config.interval_minutes} 分钟内进行（保活心跳运行中）",
                    )
                )
                total_wait = config.interval_minutes * 60
                while total_wait > 0 and not self._stop_event.is_set():
                    sleep_time = min(total_wait, HEARTBEAT_INTERVAL_SECONDS)
                    if self._wake_event.wait(sleep_time):
                        break
                    total_wait -= sleep_time

                    if not self._stop_event.is_set():
                        try:
                            alive = client.heartbeat(config)
                            if not alive:
                                self._emit(
                                    MonitorEvent(
                                        "reconnecting",
                                        "检测到校园网会话已过期，正在立即恢复…",
                                        "warning",
                                    )
                                )
                                break
                        except Exception:
                            pass

                        if getattr(config, "arp_guard", True):
                            try:
                                from .security import audit_security
                                sec_report = audit_security()
                                if sec_report.arp_spoofed:
                                    self._emit(
                                        MonitorEvent(
                                            "warning",
                                            "⚠️ 局域网安全警报：检测到网关 ARP 缓存被篡改！可能存在同网段中间人嗅探或劫持挂马",
                                            "error",
                                        )
                                    )
                            except Exception:
                                pass
            else:
                self._emit(
                    MonitorEvent(
                        "waiting",
                        f"网络异常，将在 {OFFLINE_RETRY_SECONDS} 秒后自动重试…",
                        "warning",
                    )
                )
                self._wake_event.wait(OFFLINE_RETRY_SECONDS)

            if not self._stop_event.is_set():
                self._emit(MonitorEvent("checking", "正在检测网络状态…"))
        self._emit(MonitorEvent("stopped", "监控已停止"))
