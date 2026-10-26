from __future__ import annotations

import ctypes
import datetime as dt
import queue
import sys
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

from . import __version__
from .local_log import LocalLog
from .memory import trim_memory
from .models import AppConfig, ZONE_AUTO, ZONE_DORMITORY, ZONE_OFFICE
from .monitor import MonitorController, MonitorEvent
from .startup import is_autostart_enabled, set_autostart, sync_autostart_path
from .storage import ConfigStore
from .tray import TrayController


COLORS = {
    "background": "#F8FAFC",
    "card": "#FFFFFF",
    "text": "#0F172A",
    "muted": "#64748B",
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "border": "#E2E8F0",
    "success": "#16A34A",
    "warning": "#D97706",
    "error": "#DC2626",
    "idle": "#94A3B8",
}


def _generate_checkbox_images() -> dict[str, ImageTk.PhotoImage]:
    """Generate crisp, anti-aliased modern checkmark and checkbox state images."""
    size = (40, 40)
    images = {}
    states = {
        "unchecked": ("#FFFFFF", "#CBD5E1", 3, False),
        "unchecked_active": ("#F8FAFC", "#3B82F6", 3, False),
        "checked": ("#2563EB", "#2563EB", 2, True),
        "checked_active": ("#1D4ED8", "#1D4ED8", 2, True),
    }
    for name, (fill, border, border_width, is_checked) in states.items():
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        box = [3, 3, 36, 36]
        draw.rounded_rectangle(box, radius=8, fill=fill, outline=border, width=border_width)
        if is_checked:
            # 优雅清晰的白色勾选标记 (✔)，杜绝令人困惑的打叉 ☒
            points = [(10, 20), (16, 26), (29, 13)]
            draw.line(points, fill="#FFFFFF", width=4, joint="curve")
        resampled = img.resize((20, 20), Image.Resampling.LANCZOS)
        images[name] = ImageTk.PhotoImage(resampled)
    return images

ZONE_LABELS = {
    "自动识别（全校自适应，推荐）": ZONE_AUTO,
    "教学 / 办公区（实验室）": ZONE_OFFICE,
    "宿舍区": ZONE_DORMITORY,
}
ZONE_NAMES = {
    ZONE_AUTO: "自动识别（全校自适应，推荐）",
    ZONE_OFFICE: "教学 / 办公区（实验室）",
    ZONE_DORMITORY: "宿舍区",
    "自动尝试（实验性）": "自动识别（全校自适应，推荐）",
}
UI_LOG_RETENTION = dt.timedelta(hours=3)


class SentinelApp:
    def __init__(self, store: ConfigStore, launched_by_autostart: bool = False):
        self.store = store
        self.launched_by_autostart = launched_by_autostart
        self.config = store.load()
        self.events: queue.Queue[MonitorEvent] = queue.Queue()
        self.tray_actions: queue.Queue[str] = queue.Queue()
        self.monitor = MonitorController(self.events.put)
        self.local_log = LocalLog()
        self.log_entries: deque[tuple[dt.datetime, str]] = deque()
        self.is_exiting = False
        self.tray_notice_shown = False
        self._last_extra_info: str | None = None

        self.root = tk.Tk()
        self.root.title(f"SZU NetSentinel (深大校园网智能哨兵) v{__version__}")
        self._setup_window_geometry()
        self.root.configure(bg=COLORS["background"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Unmap>", self._on_unmap)

        self.username_var = tk.StringVar(value=self.config.username)
        self.password_var = tk.StringVar(value=self.config.password)
        self.zone_var = tk.StringVar(
            value=ZONE_NAMES.get(self.config.zone, "自动识别（全校自适应，推荐）")
        )
        self.interval_var = tk.StringVar(value=str(self.config.interval_minutes))
        self.autostart_var = tk.BooleanVar(
            value=is_autostart_enabled() or self.config.autostart
        )
        self.start_on_launch_var = tk.BooleanVar(value=self.config.start_on_launch)
        self.direct_mode_var = tk.BooleanVar(value=self.config.direct_mode)
        self.arp_guard_var = tk.BooleanVar(value=getattr(self.config, "arp_guard", True))
        self.password_visible = False

        self._load_app_icons()
        self._configure_styles()
        self._build_ui()
        sync_autostart_path()
        self.tray = TrayController(self.tray_actions.put)
        self.tray.start()
        self._append_log("程序已启动")
        self.root.after(120, self._process_events)
        self.root.after(250, self._handle_initial_start)
        self.root.after(500, self._refresh_security_status)
        self.root.after(1000, trim_memory)
        self.root.after(300000, self._periodic_memory_trim)

    def _setup_window_geometry(self) -> None:
        try:
            self.root.update_idletasks()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            win_w = 680
            # 屏幕自适应高度：确保在各类分辨率与屏幕缩放比例下，窗口完整呈现且日志区高度充足
            win_h = min(780, max(640, sh - 80))
            x = max(0, (sw - win_w) // 2)
            y = max(10, (sh - win_h - 40) // 2)
            self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")
            self.root.minsize(580, 580)
        except Exception:
            self.root.geometry("680x760")
            self.root.minsize(580, 580)

    def _periodic_memory_trim(self) -> None:
        if not self.is_exiting:
            trim_memory()
            self.root.after(300000, self._periodic_memory_trim)

    def _load_app_icons(self) -> None:
        try:
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                base_dir = Path(sys._MEIPASS) / "assets"
            else:
                base_dir = Path(__file__).resolve().parent.parent / "assets"

            ico_path = base_dir / "app.ico"
            png_path = base_dir / "app.png"

            # 1. 优先通过 PhotoImage 设置顶级窗口图标 (跨平台生效)
            if png_path.exists():
                try:
                    self._app_icon_img = ImageTk.PhotoImage(
                        Image.open(png_path).resize((32, 32), Image.Resampling.LANCZOS)
                    )
                    self._header_badge_img = ImageTk.PhotoImage(
                        Image.open(png_path).resize((44, 44), Image.Resampling.LANCZOS)
                    )
                    self.root.iconphoto(True, self._app_icon_img)
                except Exception:
                    pass

            # 2. Windows 平台通过 iconbitmap 设置标准 ICO 资源
            if ico_path.exists():
                try:
                    self.root.iconbitmap(default=str(ico_path))
                except Exception:
                    try:
                        self.root.iconbitmap(str(ico_path))
                    except Exception:
                        pass

                # 3. Windows 平台调用底层 Win32 API 强制设置窗口标题栏左上角 16x16 图标，
                # 彻底消除 Tkinter 默认的羽毛笔/毛笔图标！
                if sys.platform == "win32":
                    try:
                        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SZU.NetSentinel.App.v2.5")
                        self.root.update_idletasks()
                        hwnd = self.root.winfo_id()
                        parent_hwnd = ctypes.windll.user32.GetParent(hwnd) or hwnd
                        IMAGE_ICON = 1
                        LR_LOADFROMFILE = 0x00000010
                        WM_SETICON = 0x0080
                        hicon_small = ctypes.windll.user32.LoadImageW(
                            None, str(ico_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE
                        )
                        hicon_big = ctypes.windll.user32.LoadImageW(
                            None, str(ico_path), IMAGE_ICON, 32, 32, LR_LOADFROMFILE
                        )
                        if hicon_small:
                            ctypes.windll.user32.SendMessageW(parent_hwnd, WM_SETICON, 0, hicon_small)
                            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 0, hicon_small)
                        if hicon_big:
                            ctypes.windll.user32.SendMessageW(parent_hwnd, WM_SETICON, 1, hicon_big)
                            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 1, hicon_big)
                    except Exception:
                        pass
        except Exception:
            pass

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self._checkbox_images = _generate_checkbox_images()

        style.configure(
            "TFrame",
            background=COLORS["background"],
        )
        style.configure(
            "Card.TFrame",
            background=COLORS["card"],
            relief="solid",
            borderwidth=1,
            bordercolor=COLORS["border"],
            darkcolor=COLORS["border"],
            lightcolor=COLORS["border"],
        )
        style.configure(
            "Inner.Card.TFrame",
            background=COLORS["card"],
            relief="flat",
            borderwidth=0,
        )
        style.configure(
            "Info.Card.TFrame",
            background="#EFF6FF",
            relief="solid",
            borderwidth=1,
            bordercolor="#BFDBFE",
            darkcolor="#BFDBFE",
            lightcolor="#BFDBFE",
        )
        style.configure(
            "Inner.Info.TFrame",
            background="#EFF6FF",
            relief="flat",
            borderwidth=0,
        )
        style.configure(
            "Info.TLabel",
            background="#EFF6FF",
            foreground="#1E40AF",
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "TLabel",
            background=COLORS["background"],
            foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Card.TLabel",
            background=COLORS["card"],
            foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Muted.Card.TLabel",
            background=COLORS["card"],
            foreground=COLORS["muted"],
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "Title.TLabel",
            background=COLORS["background"],
            foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 22, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=COLORS["background"],
            foreground=COLORS["muted"],
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "Section.Card.TLabel",
            background=COLORS["card"],
            foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.configure(
            "TEntry",
            fieldbackground="#FFFFFF",
            background="#FFFFFF",
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            padding=(10, 8),
            font=("Microsoft YaHei UI", 10),
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", COLORS["primary"])],
            lightcolor=[("focus", COLORS["primary"])],
            darkcolor=[("focus", COLORS["primary"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground="#FFFFFF",
            background="#FFFFFF",
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            arrowcolor="#475569",
            arrowsize=13,
            padding=(10, 8),
            font=("Microsoft YaHei UI", 10),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#FFFFFF"), ("disabled", "#F1F5F9")],
            bordercolor=[("focus", COLORS["primary"])],
            lightcolor=[("focus", COLORS["primary"])],
            darkcolor=[("focus", COLORS["primary"])],
        )
        style.configure(
            "TSpinbox",
            fieldbackground="#FFFFFF",
            background="#FFFFFF",
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            arrowcolor="#475569",
            arrowsize=10,
            padding=(8, 7),
            font=("Microsoft YaHei UI", 10),
        )
        style.map(
            "TSpinbox",
            bordercolor=[("focus", COLORS["primary"])],
            lightcolor=[("focus", COLORS["primary"])],
            darkcolor=[("focus", COLORS["primary"])],
        )

        # 现代无歧义勾选框样式（采用平滑抗锯齿高清图标，替换原先容易被误认成错误的 ☒ 图标）
        style.element_create(
            "ModernCheck.indicator",
            "image",
            self._checkbox_images["unchecked"],
            ("selected", "active", self._checkbox_images["checked_active"]),
            ("selected", self._checkbox_images["checked"]),
            ("active", self._checkbox_images["unchecked_active"]),
            padding=5,
        )
        style.layout(
            "Modern.TCheckbutton",
            [
                ("ModernCheck.indicator", {"side": "left", "sticky": ""}),
                (
                    "Checkbutton.padding",
                    {
                        "children": [("Checkbutton.label", {"sticky": "nswe"})],
                        "side": "left",
                        "sticky": "nswe",
                    },
                ),
            ],
        )
        style.configure(
            "Modern.TCheckbutton",
            background=COLORS["card"],
            foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 9),
            padding=(2, 4),
        )
        style.map(
            "Modern.TCheckbutton",
            background=[("active", COLORS["card"])],
        )

        style.configure(
            "Primary.TButton",
            background=COLORS["primary"],
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(16, 8),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[
                ("active", COLORS["primary_hover"]),
                ("disabled", "#E2E8F0"),
            ],
            foreground=[
                ("disabled", "#94A3B8"),
            ],
        )
        style.configure(
            "Secondary.TButton",
            background="#EFF6FF",
            foreground=COLORS["primary"],
            relief="solid",
            borderwidth=1,
            bordercolor="#BFDBFE",
            darkcolor="#BFDBFE",
            lightcolor="#BFDBFE",
            padding=(14, 8),
            font=("Microsoft YaHei UI", 10),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#DBEAFE")],
        )
        style.configure(
            "Stop.TButton",
            background="#FEE2E2",
            foreground="#DC2626",
            relief="solid",
            borderwidth=1,
            bordercolor="#FECACA",
            darkcolor="#FECACA",
            lightcolor="#FECACA",
            padding=(14, 8),
            font=("Microsoft YaHei UI", 10),
        )
        style.map(
            "Stop.TButton",
            background=[
                ("active", "#FECACA"),
                ("disabled", "#F1F5F9"),
            ],
            foreground=[
                ("disabled", "#94A3B8"),
            ],
            bordercolor=[
                ("disabled", "#E2E8F0"),
            ],
        )
        style.configure(
            "Ghost.TButton",
            background=COLORS["card"],
            foreground=COLORS["muted"],
            borderwidth=0,
            padding=(8, 6),
            font=("Microsoft YaHei UI", 9),
        )
        style.map(
            "Ghost.TButton",
            background=[("active", "#F1F5F9")],
            foreground=[("active", COLORS["text"])],
        )
        style.configure(
            "Shield.TButton",
            background="#0284C7",
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(14, 8),
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "Shield.TButton",
            background=[("active", "#0369A1"), ("disabled", "#CBD5E1")],
            foreground=[("disabled", "#94A3B8")],
        )

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(22, 12, 22, 10))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 8))

        header_box = ttk.Frame(header)
        header_box.pack(side="left")

        if hasattr(self, "_header_badge_img"):
            badge_label = ttk.Label(header_box, image=self._header_badge_img)
            badge_label.pack(side="left", padx=(0, 12), pady=(2, 0))

        title_box = ttk.Frame(header_box)
        title_box.pack(side="left")
        ttk.Label(title_box, text="SZU 网络守护", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="轻量、安静地守护你的校园网连接 · v2.5.0",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # 1. 网络状态卡片
        status_card = ttk.Frame(outer, style="Card.TFrame", padding=(16, 10))
        status_card.pack(fill="x", pady=(0, 8))
        status_line = ttk.Frame(status_card, style="Inner.Card.TFrame")
        status_line.pack(fill="x")
        self.status_dot = tk.Canvas(
            status_line,
            width=18,
            height=18,
            bg=COLORS["card"],
            highlightthickness=0,
        )
        self.status_dot.pack(side="left")
        self.status_circle = self.status_dot.create_oval(
            4, 4, 14, 14, fill=COLORS["idle"], outline=""
        )
        self.status_label = ttk.Label(
            status_line,
            text="等待开始",
            style="Section.Card.TLabel",
        )
        self.status_label.pack(side="left", padx=(5, 0))
        self.detail_label = ttk.Label(
            status_line,
            text="尚未启动监控",
            style="Muted.Card.TLabel",
        )
        self.detail_label.pack(side="right")

        # 2. 局域网安全与防病毒加固卡片
        sec_card = ttk.Frame(outer, style="Card.TFrame", padding=(16, 10))
        sec_card.pack(fill="x", pady=(0, 8))
        sec_box = ttk.Frame(sec_card, style="Inner.Card.TFrame")
        sec_box.pack(fill="x")

        sec_left = ttk.Frame(sec_box, style="Inner.Card.TFrame")
        sec_left.pack(side="left", fill="x", expand=True)

        sec_title_row = ttk.Frame(sec_left, style="Inner.Card.TFrame")
        sec_title_row.pack(fill="x")
        ttk.Label(
            sec_title_row,
            text="🛡️ 局域网安全与防病毒加固",
            style="Section.Card.TLabel",
        ).pack(side="left")

        self.sec_desc_label = ttk.Label(
            sec_left,
            text="正在检测局域网风险（ARP 嗅探防护、445/SMB 蠕虫端口隔离）…",
            style="Muted.Card.TLabel",
        )
        self.sec_desc_label.pack(anchor="w", pady=(3, 0))

        self.sec_action_btn = ttk.Button(
            sec_box,
            text="一键安全加固",
            style="Shield.TButton",
            command=self._trigger_security_hardening,
            cursor="hand2",
        )
        self.sec_action_btn.pack(side="right", padx=(10, 0))

        # 3. 连接参数设置卡片 (整齐排列，独立保存设置按钮杜绝文字截断)
        form_card = ttk.Frame(outer, style="Card.TFrame", padding=(16, 10))
        form_card.pack(fill="x", pady=(0, 8))

        form_header = ttk.Frame(form_card, style="Inner.Card.TFrame")
        form_header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(
            form_header,
            text="连接设置",
            style="Section.Card.TLabel",
        ).pack(side="left")
        ttk.Button(
            form_header,
            text="保存设置",
            style="Ghost.TButton",
            command=self._save_settings,
            cursor="hand2",
            padding=(10, 2),
        ).pack(side="right")
        form_card.columnconfigure(1, weight=1)

        self._form_label(form_card, "账号", 1)
        self.username_entry = ttk.Entry(
            form_card,
            textvariable=self.username_var,
        )
        self.username_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)

        self._form_label(form_card, "密码", 2)
        self.password_entry = ttk.Entry(
            form_card,
            textvariable=self.password_var,
            show="●",
        )
        self.password_entry.grid(row=2, column=1, sticky="ew", pady=4)
        self.show_password_button = ttk.Button(
            form_card,
            text="显示",
            style="Ghost.TButton",
            command=self._toggle_password,
            width=6,
            cursor="hand2",
        )
        self.show_password_button.grid(row=2, column=2, padx=(6, 0), pady=4)

        self._form_label(form_card, "区域", 3)
        self.zone_combo = ttk.Combobox(
            form_card,
            textvariable=self.zone_var,
            values=list(ZONE_LABELS),
            state="readonly",
        )
        self.zone_combo.grid(row=3, column=1, columnspan=2, sticky="ew", pady=4)

        self._form_label(form_card, "检测间隔", 4)
        interval_row = ttk.Frame(form_card, style="Inner.Card.TFrame")
        interval_row.grid(row=4, column=1, columnspan=2, sticky="ew", pady=4)
        self.interval_spinbox = ttk.Spinbox(
            interval_row,
            from_=1,
            to=1440,
            textvariable=self.interval_var,
            width=10,
        )
        self.interval_spinbox.pack(side="left")
        ttk.Label(
            interval_row,
            text="分钟",
            style="Muted.Card.TLabel",
        ).pack(side="left", padx=(8, 0))

        options = ttk.Frame(form_card, style="Inner.Card.TFrame")
        options.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 2))
        ttk.Checkbutton(
            options,
            text="开机自动启动",
            variable=self.autostart_var,
            style="Modern.TCheckbutton",
            cursor="hand2",
        ).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Checkbutton(
            options,
            text="程序启动后自动监控",
            variable=self.start_on_launch_var,
            style="Modern.TCheckbutton",
            cursor="hand2",
        ).grid(row=0, column=1, sticky="w", padx=(20, 0), pady=2)
        ttk.Checkbutton(
            options,
            text="检测和认证强制直连（推荐）",
            variable=self.direct_mode_var,
            style="Modern.TCheckbutton",
            cursor="hand2",
        ).grid(row=1, column=0, sticky="w", pady=(6, 2))
        ttk.Checkbutton(
            options,
            text="网关防 ARP 嗅探与篡改监测（推荐）",
            variable=self.arp_guard_var,
            style="Modern.TCheckbutton",
            cursor="hand2",
        ).grid(row=1, column=1, sticky="w", padx=(20, 0), pady=(6, 2))

        # 4. 核心控制按键栏 (开始守护 / 立即检测 / 停止)
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(0, 8))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        buttons.columnconfigure(2, weight=1)
        self.start_button = ttk.Button(
            buttons,
            text="开始守护",
            style="Primary.TButton",
            command=self._start_monitoring,
            cursor="hand2",
        )
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.check_button = ttk.Button(
            buttons,
            text="立即检测",
            style="Secondary.TButton",
            command=self._check_now,
            cursor="hand2",
        )
        self.check_button.grid(row=0, column=1, sticky="ew", padx=5)
        self.stop_button = ttk.Button(
            buttons,
            text="停止",
            style="Stop.TButton",
            command=self._stop_monitoring,
            state="disabled",
            cursor="hand2",
        )
        self.stop_button.grid(row=0, column=2, sticky="ew", padx=(5, 0))

        # 5. 底部常驻提示信息优先使用 side="bottom" 停靠，确保在任何屏幕缩放比例下都绝对可见、不被挤出视图
        footer_label = ttk.Label(
            outer,
            text="最小化或关闭窗口后将在系统托盘继续守护 · 密码使用 DPAPI 硬件加密",
            style="Subtitle.TLabel",
        )
        footer_label.pack(side="bottom", anchor="center", pady=(6, 2))

        # 6. 运行记录卡片占据中间剩余高度空间，自适应填充且自带纵向滚动条
        log_card = ttk.Frame(outer, style="Card.TFrame", padding=(16, 10))
        log_card.pack(fill="both", expand=True, pady=(0, 6))
        log_header = ttk.Frame(log_card, style="Inner.Card.TFrame")
        log_header.pack(fill="x", pady=(0, 6))
        ttk.Label(
            log_header,
            text="运行记录（最近 3 小时）",
            style="Section.Card.TLabel",
        ).pack(side="left")
        ttk.Button(
            log_header,
            text="退出",
            style="Ghost.TButton",
            command=self._exit_application,
            cursor="hand2",
            padding=(8, 2),
        ).pack(side="right")
        ttk.Button(
            log_header,
            text="日志目录",
            style="Ghost.TButton",
            command=self._open_log_directory,
            cursor="hand2",
            padding=(8, 2),
        ).pack(side="right", padx=(0, 6))
        ttk.Button(
            log_header,
            text="清空",
            style="Ghost.TButton",
            command=self._clear_logs,
            cursor="hand2",
            padding=(8, 2),
        ).pack(side="right", padx=(0, 6))

        # 运行记录文本区带原生滚动条，确保日志随时可滚屏查阅
        log_container = ttk.Frame(log_card, style="Inner.Card.TFrame")
        log_container.pack(fill="both", expand=True)

        log_scroll = ttk.Scrollbar(log_container, orient="vertical")
        log_scroll.pack(side="right", fill="y")

        self.log_text = tk.Text(
            log_container,
            height=6,
            relief="flat",
            borderwidth=1,
            highlightthickness=1,
            highlightcolor=COLORS["border"],
            highlightbackground=COLORS["border"],
            background="#F8FAFC",
            foreground="#334155",
            font=("Microsoft YaHei UI", 9),
            padx=10,
            pady=8,
            wrap="word",
            state="disabled",
            yscrollcommand=log_scroll.set,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.config(command=self.log_text.yview)

    @staticmethod
    def _form_label(parent: ttk.Frame, text: str, row: int) -> None:
        ttk.Label(
            parent,
            text=text,
            style="Card.TLabel",
            width=10,
        ).grid(row=row, column=0, sticky="w", pady=5)

    def _read_form(self, validate: bool = True) -> AppConfig:
        try:
            interval = int(self.interval_var.get().strip())
        except ValueError:
            interval = 0
        config = AppConfig(
            username=self.username_var.get(),
            password=self.password_var.get(),
            zone=ZONE_LABELS.get(self.zone_var.get(), ""),
            interval_minutes=interval,
            autostart=self.autostart_var.get(),
            start_on_launch=self.start_on_launch_var.get(),
            direct_mode=self.direct_mode_var.get(),
            arp_guard=self.arp_guard_var.get(),
        )
        if validate:
            config.validate()
        return config

    def _refresh_security_status(self) -> None:
        try:
            from .security import audit_security

            report = audit_security()
            if report.lan_shield_active:
                arp_text = f"网关: {report.gateway_ip or '未知'} [{report.arp_type}]"
                self.sec_desc_label.configure(
                    text=f"安全加固已生效 · 局域网高危蠕虫端口 (445/135等) 已阻断 · {arp_text}",
                    foreground=COLORS["success"],
                )
                self.sec_action_btn.configure(
                    text="防护生效中",
                    style="Secondary.TButton",
                )
            elif report.arp_spoofed:
                self.sec_desc_label.configure(
                    text="⚠️ 警报：检测到网关 MAC 遭到篡改，疑似局域网 ARP 欺骗嗅探！",
                    foreground=COLORS["error"],
                )
                self.sec_action_btn.configure(
                    text="立即锁定网关",
                    style="Stop.TButton",
                )
            else:
                self.sec_desc_label.configure(
                    text="高危端口 (445/135等) 暴露在校园网中，建议一键加固阻断病毒侵入",
                    foreground=COLORS["warning"],
                )
                self.sec_action_btn.configure(
                    text="一键安全加固",
                    style="Shield.TButton",
                )
        except Exception:
            pass

    def _trigger_security_hardening(self) -> None:
        from .security import apply_security_hardening, is_admin, request_elevation

        if is_admin():
            ok, msg = apply_security_hardening()
            if ok:
                messagebox.showinfo("安全加固成功", msg, parent=self.root)
            else:
                messagebox.showwarning("加固提示", msg, parent=self.root)
            self._refresh_security_status()
        else:
            elevated = request_elevation("--harden-lan")
            if not elevated:
                messagebox.showwarning(
                    "权限提示",
                    "应用局域网防火墙加固规则需要管理员权限。请在系统 UAC 弹窗中点击允许以完成加固。",
                    parent=self.root,
                )
            self.root.after(2000, self._refresh_security_status)

    def _save_settings(self, quiet: bool = False) -> bool:
        try:
            config = self._read_form(validate=True)
            self.store.save(config)
            set_autostart(config.autostart)
            self.config = config
            if not quiet:
                self._append_log("设置已安全保存")
            return True
        except (ValueError, OSError) as exc:
            messagebox.showerror("无法保存", str(exc), parent=self.root)
            return False

    def _start_monitoring(self) -> None:
        if self.monitor.running:
            self.monitor.check_now()
            return
        if not self._save_settings(quiet=True):
            return
        self.monitor.start(self.config)
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._append_log(
            f"开始监控，间隔 {self.config.interval_minutes} 分钟"
        )

    def _stop_monitoring(self) -> None:
        if self.monitor.running:
            self.monitor.stop()
        self.stop_button.configure(state="disabled")

    def _check_now(self) -> None:
        if self.monitor.running:
            self.monitor.check_now()
            self._append_log("已请求立即检测")
        else:
            self._start_monitoring()

    def _toggle_password(self) -> None:
        self.password_visible = not self.password_visible
        self.password_entry.configure(show="" if self.password_visible else "●")
        self.show_password_button.configure(
            text="隐藏" if self.password_visible else "显示"
        )

    def _handle_initial_start(self) -> None:
        should_start = self.launched_by_autostart or self.config.start_on_launch
        if self.launched_by_autostart:
            self._hide_to_tray(notify=False)
        if should_start and self.config.username and self.config.password:
            self._start_monitoring()

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                self._apply_event(event)
        except queue.Empty:
            pass
        try:
            while True:
                self._handle_tray_action(self.tray_actions.get_nowait())
        except queue.Empty:
            pass
        if not self.is_exiting:
            self.root.after(150, self._process_events)

    def _apply_event(self, event: MonitorEvent) -> None:
        state_map = {
            "checking": ("检测中", COLORS["primary"]),
            "reconnecting": ("正在重连", COLORS["warning"]),
            "online": ("网络正常", COLORS["success"]),
            "offline": ("网络异常", COLORS["error"]),
            "waiting": ("守护中", COLORS["success"]),
            "stopped": ("已停止", COLORS["idle"]),
        }
        title, color = state_map.get(event.state, ("运行中", COLORS["idle"]))
        self.tray.update(event.state)
        self.status_label.configure(text=title)
        self.status_dot.itemconfigure(self.status_circle, fill=color)
        if event.latency_ms is not None:
            detail_text = f"{event.latency_ms} ms"
            if event.extra_info:
                detail_text += f" | {event.extra_info}"
            self.detail_label.configure(text=detail_text)
        elif event.extra_info:
            self.detail_label.configure(text=event.extra_info)
        else:
            self.detail_label.configure(text=event.message)
        if event.state == "stopped":
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
        if event.state == "online" and event.extra_info and event.extra_info != self._last_extra_info:
            self._last_extra_info = event.extra_info
            self._append_log(f"当前会话信息：{event.extra_info}")
        if event.state == "waiting":
            self.local_log.write(event.message, event.level)
        else:
            self._append_log(event.message, event.level)

    def _append_log(self, message: str, level: str = "info") -> None:
        now = dt.datetime.now()
        self.local_log.write(message, level)
        self.log_entries.append((now, message))
        cutoff = now - UI_LOG_RETENTION
        removed = False
        while self.log_entries and (
            self.log_entries[0][0] < cutoff or len(self.log_entries) > 200
        ):
            self.log_entries.popleft()
            removed = True

        self.log_text.configure(state="normal")
        if removed:
            self.log_text.delete("1.0", "end")
            for timestamp, entry in self.log_entries:
                self.log_text.insert("end", f"{timestamp:%H:%M:%S}  {entry}\n")
        else:
            self.log_text.insert("end", f"{now:%H:%M:%S}  {message}\n")
            try:
                line_count = int(float(self.log_text.index("end-1c").split(".")[0]))
                if line_count > 250:
                    self.log_text.delete("1.0", "51.0")
            except Exception:
                pass
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_unmap(self, _event: tk.Event) -> None:
        self.root.after(80, self._hide_if_iconified)

    def _hide_if_iconified(self) -> None:
        if not self.is_exiting and self.root.state() == "iconic":
            self._hide_to_tray()

    def _hide_to_tray(self, notify: bool = True) -> None:
        if self.is_exiting:
            return
        self.root.withdraw()
        trim_memory()
        if notify and not self.tray_notice_shown:
            self.tray.notify("程序仍在后台监控，双击托盘图标可打开主界面")
            self.tray_notice_shown = True

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def _handle_tray_action(self, action: str) -> None:
        if action == "show":
            self._show_window()
        elif action == "check":
            self._check_now()
        elif action == "exit":
            self._exit_application()

    def _open_log_directory(self) -> None:
        try:
            self.local_log.open_directory()
        except OSError as exc:
            messagebox.showerror("无法打开日志目录", str(exc), parent=self.root)

    def _clear_logs(self) -> None:
        self.log_entries.clear()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        self._hide_to_tray()

    def _exit_application(self) -> None:
        if self.is_exiting:
            return
        self.is_exiting = True
        self.local_log.write("程序退出")
        if self.monitor.running:
            self.monitor.stop()
        self.tray.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


GuardianApp = SentinelApp
