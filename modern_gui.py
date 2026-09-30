#!/usr/bin/env python3
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportOptionalMemberAccess=false
"""
Modern WeeklyPulse-style GUI using Flet
Improved layout and sizing based on reference image
"""

import flet as ft
import json
import os
import threading
import time
import psutil

try:
    import win32gui
    import win32process

    _WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32process = None
    _WIN32_AVAILABLE = False
from collections import Counter
from datetime import datetime, timedelta

# 수집기·보고서 생성기 등 무거운 모듈은 실제 호출 시점에 lazy import —
# langchain/langgraph/docx/watchdog 로딩이 창이 뜨기 전 수 초를 차지하므로
# 최초 렌더링 경로에서는 빼둔다.


class WeeklyPulseApp:
    """Modern WeeklyPulse-style application with proper sizing"""

    # 실제 실행 여부를 확인할 프로세스 이름 (Confluence는 웹 기반이라 별도 실행파일이 없음)
    # 각 항목에 Windows + macOS/Linux 프로세스명을 함께 둠 — 비Windows 환경에서는
    # 창 검사 없이 psutil 프로세스 존재 여부로만 판정 (win32gui는 Windows 전용).
    PROCESS_NAMES = {
        "Slack": ["slack.exe", "Slack"],
        "Excel": ["excel.exe", "Microsoft Excel"],
        "PowerPoint": ["powerpnt.exe", "Microsoft PowerPoint"],
        "Notepad": ["notepad.exe", "TextEdit"],
        "Chrome": ["chrome.exe", "Google Chrome"],
        "Claude Code": ["claude.exe", "claude"],
        "Devin": ["devin.exe", "Devin"],
        # 신형 Teams(ms-teams.exe) + 구형 클래식 Teams(Teams.exe) 둘 다 감지
        "Teams": ["ms-teams.exe", "teams.exe", "Microsoft Teams", "MSTeams"],
        # 클래식 Outlook(outlook.exe) + 신형 Outlook(olk.exe)
        "Outlook": ["outlook.exe", "olk.exe", "Microsoft Outlook"],
        "Word": ["winword.exe", "Microsoft Word"],
        # 데스크톱 OneNote(ONENOTE.EXE) + Store/UWP(OneNoteIm.exe)
        "OneNote": ["onenote.exe", "onenoteim.exe", "Microsoft OneNote"],
    }

    @staticmethod
    def is_app_running(process_names):
        """지정된 프로세스 이름 중 하나가, 눈에 보이는 창을 가지고 실행 중인지 확인.

        단순 프로세스 존재 여부(psutil)만 보면 Slack 같은 Electron 앱은 창을
        닫아도 백그라운드 헬퍼 프로세스가 남아있어 항상 "실행 중"으로 오판됨.
        그래서 실제로 IsWindowVisible + 제목이 있는 창을 가진 프로세스인지까지 확인.
        """
        if not process_names:
            return False
        target = {name.lower() for name in process_names}

        target_pids = set()
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                if (proc.info.get("name") or "").lower() in target:
                    target_pids.add(proc.info["pid"])
        except Exception:
            return False

        if not target_pids:
            return False

        # win32 창 검사는 Windows 전용 — 다른 플랫폼은 프로세스 존재로 판정
        if not _WIN32_AVAILABLE:
            return True

        found = {"visible": False}

        def _enum_callback(hwnd, _):
            if found["visible"] or not win32gui.IsWindowVisible(hwnd):
                return
            if not win32gui.GetWindowText(hwnd):
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                return
            if pid in target_pids:
                found["visible"] = True

        try:
            win32gui.EnumWindows(_enum_callback, None)
        except Exception:
            # EnumWindows 자체가 실패하면 프로세스 존재 여부로 폴백
            return True

        return found["visible"]

    def _scan_running_apps(self):
        """tracked_apps 전체의 실행 여부를 프로세스·창 열거 각 1회씩으로 판정.

        앱마다 is_app_running()을 따로 부르면 process_iter + EnumWindows가
        N번 반복돼 시작이 수 초 느려진다 — 여기서는 한 번만 스캔한다.
        """
        name_to_pids = {}
        all_names = {n.lower() for names in self.PROCESS_NAMES.values() for n in names}
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                name = (proc.info.get("name") or "").lower()
                if name in all_names:
                    name_to_pids.setdefault(name, []).append(proc.info["pid"])
        except Exception:
            name_to_pids = {}

        # 보이는 창을 가진 프로세스 PID만 수집 (Windows). 다른 OS는 프로세스 존재로 판정
        visible_pids = None
        if _WIN32_AVAILABLE and name_to_pids:
            visible_pids = set()

            def _cb(hwnd, _):
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        visible_pids.add(pid)
                    except Exception:
                        pass

            try:
                win32gui.EnumWindows(_cb, None)
            except Exception:
                visible_pids = None  # 창 열거 실패 → 프로세스 존재로 폴백

        running = set()
        for app_name, names in self.PROCESS_NAMES.items():
            pids = {p for n in names for p in name_to_pids.get(n.lower(), [])}
            if visible_pids is None:
                alive = bool(pids)
            else:
                alive = bool(pids & visible_pids)
            if alive:
                running.add(app_name)
        return running

    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "WeeklyPulse"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.window.width = 1400
        self.page.window.height = 780
        self.page.window.min_width = 1200
        self.page.window.min_height = 650
        self.page.padding = 0
        self.page.bgcolor = ft.Colors.WHITE

        # App state
        self.is_running = False
        self.file_watcher = None
        self.watcher_thread = None
        self.browser_server = None
        self.collected_activities = []

        # Tracked apps data - "active"는 실제 프로세스 실행 여부를 확인해서 채움
        self.tracked_apps = {
            "Slack": {"icon": ft.Icons.CHAT, "last_active": "30 min ago"},
            "Excel": {"icon": ft.Icons.TABLE_VIEW, "last_active": "1 hour ago"},
            "PowerPoint": {"icon": ft.Icons.SLIDESHOW, "last_active": "2 hours ago"},
            "Confluence": {"icon": ft.Icons.ARTICLE, "last_active": "45 min ago"},
            "Notepad": {"icon": ft.Icons.EDIT, "last_active": "15 min ago"},
            "Chrome": {"icon": ft.Icons.LANGUAGE, "last_active": "now"},
            "Claude Code": {"icon": ft.Icons.PSYCHOLOGY, "last_active": "5 min ago"},
            "Devin": {"icon": ft.Icons.SMART_TOY, "last_active": "10 min ago"},
            "Teams": {"icon": ft.Icons.GROUPS, "last_active": "10 min ago"},
            "Outlook": {"icon": ft.Icons.MAIL, "last_active": "10 min ago"},
            "Word": {"icon": ft.Icons.DESCRIPTION, "last_active": "10 min ago"},
            "OneNote": {"icon": ft.Icons.NOTE, "last_active": "10 min ago"},
        }
        running = self._scan_running_apps()
        for app_name, app_data in self.tracked_apps.items():
            app_data["active"] = app_name in running

        # Statistics - 실제 수집 데이터 기반으로 compute_weekly_stats()가 채움
        self.total_hours = "0 hrs"
        self.active_tools = 0
        self.most_used = "-"
        self.stat_value_refs = {}
        self._stats_last_computed = 0.0
        self.compute_weekly_stats()

        # UI references
        self.tracking_button_ref = None
        self.nav_items = {}
        self.app_card_refs = {}
        self.status_refresh_thread = None
        self.main_content_column = None
        self.watch_folder_list_ref = None
        self.watch_config_path = "config/watch_config.json"

    def compute_weekly_stats(self, force=False):
        """실제 데이터 기반 주간 통계 계산.
        - total_hours: 최근 7일 활동이 기록된 시간대(hour bucket) 수
        - active_tools: tracked_apps 중 현재 실행 중으로 감지된 앱 수
        - most_used: 최근 7일 활동이 가장 많은 소스 → 앱 이름 매핑"""
        now = time.time()
        if not force and now - self._stats_last_computed < 60:
            # DB 조회는 60초에 한 번만, 실행 중 앱 수는 매번 갱신
            self.active_tools = sum(
                1 for app in self.tracked_apps.values() if app.get("active")
            )
            return
        self._stats_last_computed = now

        hours = 0
        most_source = None
        try:
            from database import ActivityDatabase

            today = datetime.now()
            week_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            with ActivityDatabase() as db:
                acts = db.get_activities_by_date_range(
                    week_start, today.strftime("%Y-%m-%d")
                )
            hours = len(
                {(a.get("timestamp") or "")[:13] for a in acts if a.get("timestamp")}
            )
            counts = Counter(a.get("source") or "unknown" for a in acts)
            if counts:
                most_source = counts.most_common(1)[0][0]
        except Exception as e:
            print(f"Warning: weekly stats computation failed: {e}")

        source_to_app = {
            "browser": "Chrome",
            "teams": "Teams",
            "outlook": "Outlook",
            "slack": "Slack",
            "confluence": "Confluence",
            "claude_code": "Claude Code",
            "vscode": "VS Code",
            "orca": "Orca",
            "filesystem": "Files",
            "onenote": "OneNote",
            "sharepoint": "SharePoint",
        }
        self.total_hours = f"{hours} hrs"
        self.active_tools = sum(
            1 for app in self.tracked_apps.values() if app.get("active")
        )
        self.most_used = source_to_app.get(most_source, most_source or "-")

    def refresh_stats_cards(self):
        """통계 재계산 후 카드 텍스트 갱신"""
        self.compute_weekly_stats()
        refs = self.stat_value_refs
        values = {
            "hours": self.total_hours,
            "tools": str(self.active_tools),
            "most": self.most_used,
        }
        changed = False
        for key, value in values.items():
            ref = refs.get(key)
            if ref is not None and ref.value != value:
                ref.value = value
                changed = True
        if changed:
            self.page.update()

    def start_status_refresh_loop(self, interval_seconds=5):
        """백그라운드에서 주기적으로 실제 프로세스 실행 여부를 다시 확인해서
        Active Work Sessions 카드에 반영 (앱 실행 중 Slack 등을 껐다 켜도 반영되도록)"""
        if self.status_refresh_thread is not None:
            return

        def loop():
            while True:
                time.sleep(interval_seconds)
                try:
                    self.refresh_app_statuses()
                    self.refresh_stats_cards()
                except Exception as ex:
                    print(f"Error refreshing app statuses: {ex}")

        self.status_refresh_thread = threading.Thread(target=loop, daemon=True)
        self.status_refresh_thread.start()

    def refresh_app_statuses(self):
        """실제 프로세스 상태를 다시 확인하고 변경된 카드만 갱신"""
        changed = False
        running = self._scan_running_apps()
        for app_name, app_data in self.tracked_apps.items():
            new_active = app_name in running
            if new_active == app_data.get("active"):
                continue
            app_data["active"] = new_active
            changed = True

            refs = self.app_card_refs.get(app_name)
            if refs:
                refs["icon"].color = (
                    ft.Colors.BLUE if new_active else ft.Colors.GREY_400
                )
                refs["dot"].visible = new_active

        if changed:
            self.page.update()

    def build_ui(self):
        """Build the modern UI with proper sizing.

        Skeleton layout only — more data sources (e.g. Teams) are still
        being added, so this will get a final visual pass once everything
        is wired up. For now: sidebar (fixed) + main content (fixed width),
        just two Row children. A 3-panel Row (sidebar + content + a right
        sidebar) mis-renders in this Flet build — the trailing fixed-width
        panel silently fails to paint — so the former right-sidebar content
        (Weekly Summary + tracking/collect buttons) now lives in a
        horizontal control panel at the bottom of the main content instead.
        """
        margin = 60
        window_width = self.page.window.width
        window_height = self.page.window.height
        sidebar_width = 200
        content_width = window_width - sidebar_width - margin
        panel_height = window_height - margin

        sidebar = self.create_sidebar()
        sidebar.height = panel_height

        self.main_content_column = ft.Column(
            self.build_dashboard_controls(),
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

        main_content = ft.Container(
            content=self.main_content_column,
            width=content_width,
            height=panel_height,
        )

        return ft.Row(
            [sidebar, main_content],
            spacing=0,
        )

    def build_dashboard_controls(self):
        """Dashboard 화면(기본 화면)의 컨트롤 목록. Settings 등으로 전환했다가
        다시 돌아올 때도 재사용."""
        return [
            self.create_header(),
            self.create_active_sessions(),
            self.create_control_panel(),
        ]

    def switch_view(self, view_name):
        """왼쪽 네비게이션 클릭에 따라 본문 내용을 교체"""
        if self.main_content_column is None:
            return

        if view_name == "Dashboard":
            self.main_content_column.controls = self.build_dashboard_controls()
        elif view_name == "Settings":
            self.main_content_column.controls = [self.create_settings_view()]
        else:
            # Tracked Apps / Reports: 아직 별도 화면 미구현
            self.main_content_column.controls = [
                ft.Container(
                    content=ft.Text(
                        f"{view_name} 화면은 아직 준비 중입니다.",
                        size=16,
                        color=ft.Colors.GREY_600,
                    ),
                    padding=24,
                )
            ]

        self.page.update()

    def create_sidebar(self):
        """Create left sidebar navigation with proper sizing"""
        return ft.Container(
            content=ft.Column(
                [
                    # Logo/Title
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.FAVORITE, size=28, color=ft.Colors.WHITE),
                                ft.Text(
                                    "WeeklyPulse",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        padding=20,
                        margin=ft.Margin(0, 0, 20, 0),
                    ),
                    # Navigation items
                    ft.Container(
                        content=ft.Column(
                            [
                                self.create_nav_item("Dashboard", ft.Icons.DASHBOARD, True),
                                self.create_nav_item("Settings", ft.Icons.SETTINGS, False),
                            ],
                            spacing=8,
                        ),
                    ),
                ],
            ),
            width=200,
            bgcolor=ft.Colors.BLUE_GREY_900,
            padding=16,
        )

    def create_nav_item(self, text, icon_name, is_selected):
        """Create navigation item with proper sizing"""

        def on_click(e):
            self.on_nav_click(text)

        container = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        icon_name,
                        size=18,
                        color=ft.Colors.WHITE
                        if is_selected
                        else ft.Colors.BLUE_GREY_400,
                    ),
                    ft.Text(
                        text,
                        size=13,
                        color=ft.Colors.WHITE
                        if is_selected
                        else ft.Colors.BLUE_GREY_400,
                        weight=ft.FontWeight.BOLD
                        if is_selected
                        else ft.FontWeight.NORMAL,
                    ),
                ],
                spacing=12,
            ),
            padding=12,
            border_radius=8,
            bgcolor=ft.Colors.BLUE_GREY_800 if is_selected else None,
            on_click=on_click,
        )

        self.nav_items[text] = container
        return container

    def create_header(self):
        """Create top header section with proper spacing"""
        return ft.Container(
            content=ft.Column(
                [
                    # Date range
                    ft.Text(
                        f"Week of {(datetime.now() - timedelta(days=7)).strftime('%b %d')} - {datetime.now().strftime('%b %d')}",
                        size=13,
                        color=ft.Colors.GREY_600,
                    ),
                    # Title
                    ft.Text(
                        "Weekly Report Generator",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLACK,
                    ),
                ],
                spacing=4,
                alignment=ft.MainAxisAlignment.START,
            ),
            padding=ft.Padding(24, 16, 24, 8),
        )

    def create_active_sessions(self):
        """Create active work sessions grid with proper sizing"""
        # Create app cards
        app_cards = [
            self.create_app_card(name, data) for name, data in self.tracked_apps.items()
        ]

        # Create rows with 4 cards each
        rows = []
        for i in range(0, len(app_cards), 4):
            row_cards = app_cards[i : i + 4]
            rows.append(
                ft.Row(
                    row_cards,
                    spacing=16,
                    alignment=ft.MainAxisAlignment.START,
                )
            )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Active Work Sessions",
                        size=18,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLACK,
                    ),
                    ft.Container(height=10),  # Spacer
                    # App cards rows
                    ft.Column(
                        rows,
                        spacing=12,
                    ),
                ],
            ),
            padding=ft.Padding(24, 8, 24, 8),
            expand=True,
        )

    def create_app_card(self, app_name, app_data):
        """Create individual app card with proper sizing"""
        icon_ref = ft.Icon(
            app_data["icon"],
            size=28,
            color=ft.Colors.BLUE if app_data["active"] else ft.Colors.GREY_400,
        )
        dot_ref = ft.CircleAvatar(
            bgcolor=ft.Colors.GREEN,
            radius=5,
            visible=app_data["active"],
        )
        # Start/Stop Tracking처럼 상태 변화를 반영할 수 있도록 참조 저장
        self.app_card_refs[app_name] = {"icon": icon_ref, "dot": dot_ref}

        return ft.Container(
            content=ft.Column(
                [
                    # App icon with active indicator
                    ft.Stack(
                        [icon_ref, dot_ref],
                        width=28,
                        height=28,
                    ),
                    # App name
                    ft.Text(
                        app_name,
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLACK,
                    ),
                    # Last active
                    ft.Text(
                        f"Last active {app_data['last_active']}",
                        size=11,
                        color=ft.Colors.GREY_600,
                    ),
                ],
                spacing=5,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=10,
            border_radius=12,
            bgcolor=ft.Colors.WHITE,
            border=ft.BorderSide(1, ft.Colors.GREY_200),
            shadow=ft.BoxShadow(
                blur_radius=8,
                spread_radius=1,
                color=ft.Colors.GREY_200,
                offset=ft.Offset(0, 2),
            ),
            width=160,
        )

    def create_control_panel(self):
        """Horizontal control panel: weekly summary stats + tracking/collect
        buttons. Skeleton layout for now (see build_ui note) — was a
        vertical right sidebar, moved here to dodge a Flet layout bug.
        """
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                "Weekly Summary",
                                size=18,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLACK,
                            ),
                            ft.Container(expand=True),
                            # 추적 상태 표시 — 프로그램 시작 시 자동으로 켜짐
                            ft.Container(
                                content=ft.Row(
                                    [
                                        ft.CircleAvatar(bgcolor=ft.Colors.GREEN, radius=5),
                                        ft.Text("Tracking Active", size=12, color=ft.Colors.GREY_700, weight=ft.FontWeight.BOLD),
                                    ],
                                    spacing=8,
                                ),
                                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                                bgcolor=ft.Colors.GREEN_50,
                                border_radius=999,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=10),
                    ft.Row(
                        [
                            self.create_stat_card("hours", "Total Hours Tracked", ft.Icons.SCHEDULE),
                            self.create_stat_card("tools", "Active Tools", ft.Icons.APPS),
                            self.create_stat_card("most", "Most Used This Week", ft.Icons.LANGUAGE),
                        ],
                        spacing=12,
                    ),
                    ft.Container(height=10),
                    # 주 액션: 보고서 생성 — 패널 폭 전체의 다크 버튼
                    ft.Row(
                        [
                            ft.Button(
                                content=ft.Row(
                                    [
                                        ft.Icon(ft.Icons.ASSIGNMENT, size=22),
                                        ft.Text("Generate Weekly Report", size=15, weight=ft.FontWeight.BOLD),
                                    ],
                                    spacing=10,
                                    alignment=ft.MainAxisAlignment.CENTER,
                                ),
                                style=ft.ButtonStyle(
                                    bgcolor=ft.Colors.BLUE_GREY_900,
                                    color=ft.Colors.WHITE,
                                    padding=ft.Padding.symmetric(vertical=14),
                                    shape=ft.RoundedRectangleBorder(radius=10),
                                ),
                                on_click=self.generate_report,
                                expand=True,
                                height=52,
                            ),
                        ],
                    ),
                ],
                spacing=8,
            ),
            padding=ft.Padding(24, 14, 24, 14),
            bgcolor=ft.Colors.GREY_50,
            border_radius=12,
        )

    def create_stat_card(self, key, label, icon_name):
        """통계 카드 생성. key별 텍스트 참조를 남겨서 실시간 갱신이 가능하도록."""
        initial = {
            "hours": self.total_hours,
            "tools": str(self.active_tools),
            "most": self.most_used,
        }[key]
        value_text = ft.Text(
            initial,
            size=18,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.BLACK,
        )
        self.stat_value_refs[key] = value_text
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icon_name, size=16, color=ft.Colors.BLUE),
                            value_text,
                            ft.Text(
                                label,
                                size=11,
                                color=ft.Colors.GREY_600,
                            ),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=0,
            ),
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            border_radius=8,
            bgcolor=ft.Colors.WHITE,
            border=ft.BorderSide(1, ft.Colors.GREY_200),
            expand=1,
        )

    def on_nav_click(self, nav_item):
        """Handle navigation item click"""
        print(f"Navigation clicked: {nav_item}")
        with open("nav_click_debug.log", "a", encoding="utf-8") as f:
            f.write(f"nav clicked: {nav_item}\n")

        # Update nav item styles
        for name, container in self.nav_items.items():
            if name == nav_item:
                container.bgcolor = ft.Colors.BLUE_GREY_800
                # Update icon and text colors
                for control in container.content.controls:
                    if isinstance(control, ft.Icon):
                        control.color = ft.Colors.WHITE
                    elif isinstance(control, ft.Text):
                        control.color = ft.Colors.WHITE
                        control.weight = ft.FontWeight.BOLD
            else:
                container.bgcolor = None
                # Update icon and text colors
                for control in container.content.controls:
                    if isinstance(control, ft.Icon):
                        control.color = ft.Colors.BLUE_GREY_400
                    elif isinstance(control, ft.Text):
                        control.color = ft.Colors.BLUE_GREY_400
                        control.weight = ft.FontWeight.NORMAL

        self.switch_view(nav_item)

    def toggle_tracking(self, e):
        """Toggle file tracking"""
        if not self.is_running:
            self.start_tracking()
        else:
            self.stop_tracking()

    def _load_watch_config(self):
        """watch_config.json을 읽어서 dict로 반환 (없으면 빈 기본값)"""
        if os.path.exists(self.watch_config_path):
            with open(self.watch_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"watch_paths": [], "file_types": [], "exclude_patterns": []}

    def _save_watch_config(self, config):
        """watch_config.json에 저장"""
        os.makedirs(os.path.dirname(self.watch_config_path), exist_ok=True)
        with open(self.watch_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def create_settings_view(self):
        """감시 폴더를 추가/삭제할 수 있는 Settings 화면"""
        config = self._load_watch_config()
        watch_paths = config.get("watch_paths", [])

        self.watch_folder_list_ref = ft.Column(spacing=8)
        self._render_watch_folder_list(watch_paths)

        row_width = self.page.window.width - 200 - 60 - 48
        self.new_folder_input = ft.TextField(
            label="폴더 경로 입력 (예: C:\\Users\\SSG\\Documents)",
            width=row_width - 110,
            on_submit=self.add_watch_folder,
        )

        note = ft.Text(
            "추적은 프로그램 시작 시 자동으로 켜집니다 — 폴더 추가/삭제는 프로그램 재시작 시 반영됩니다."
            if self.is_running
            else "폴더를 추가하면 프로그램 재시작 후 추적 대상에 포함됩니다.",
            size=12,
            color=ft.Colors.ORANGE if self.is_running else ft.Colors.GREY_600,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Settings",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLACK,
                    ),
                    ft.Container(height=8),
                    ft.Text(
                        "감시 폴더 (Watch Folders)",
                        size=18,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLACK,
                    ),
                    note,
                    ft.Container(height=12),
                    self.watch_folder_list_ref,
                    ft.Container(height=12),
                    ft.Row(
                        [
                            self.new_folder_input,
                            ft.Button(
                                "추가",
                                icon=ft.Icons.ADD,
                                style=ft.ButtonStyle(
                                    bgcolor=ft.Colors.BLUE,
                                    color=ft.Colors.WHITE,
                                    padding=14,
                                    shape=ft.RoundedRectangleBorder(radius=8),
                                ),
                                on_click=self.add_watch_folder,
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Container(height=24),
                    self._create_teams_settings_section(),
                ],
                spacing=8,
            ),
            padding=24,
        )

    def _create_teams_settings_section(self):
        """Settings 화면의 'Teams 수집·보고 설정' 섹션 — config/teams_settings.json에 저장"""
        from teams_collector import load_teams_settings

        s = load_teams_settings()
        self.teams_settings = s

        def num_field(key, label, hint):
            return ft.TextField(
                label=label,
                value=str(s[key]),
                hint_text=hint,
                width=200,
                on_change=lambda e: self._teams_setting_changed(key, e.control.value),
            )

        def check_field(key, label):
            return ft.Checkbox(
                label=label,
                value=bool(s.get(key)),
                on_change=lambda e: self._teams_setting_changed(key, e.control.value),
            )

        self._teams_chat_checks = {}
        type_labels = {"oneOnOne": "1:1 채팅", "group": "그룹 채팅", "meeting": "회의 채팅"}
        checks = []
        for ctype, label in type_labels.items():
            cb = ft.Checkbox(
                label=label,
                value=ctype in s["chat_types"],
                on_change=lambda e, c=ctype: self._teams_type_toggled(c, e.control.value),
            )
            self._teams_chat_checks[ctype] = cb
            checks.append(cb)

        self.teams_scope_dropdown = ft.Dropdown(
            label="보고서 범위",
            value=s.get("report_scope", "mine"),
            options=[
                ft.dropdown.Option("mine", "내가 보낸 메시지만 요약"),
                ft.dropdown.Option("all", "주고받은 메시지 전체 요약"),
            ],
            width=260,
            on_select=lambda e: self._teams_setting_changed("report_scope", e.control.value),
        )

        row_width = self.page.window.width - 200 - 60 - 48
        self.excluded_chats_list = ft.Column(
            [ft.Text("'채팅방 목록 불러오기'를 누르면 선택할 수 있습니다.",
                     size=12, color=ft.Colors.GREY_500)],
            spacing=2,
            scroll=ft.ScrollMode.AUTO,
        )
        return ft.Column(
            [
                ft.Text("Teams 수집·보고 설정", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK),
                ft.Text(
                    "변경 사항은 다음 수집/보고서 생성부터 자동 적용됩니다.",
                    size=12, color=ft.Colors.GREY_600,
                ),
                ft.Row(
                    [num_field("days", "수집 기간(일)", "기본 7")],
                    spacing=16,
                    wrap=True,
                ),
                ft.Row([ft.Text("수집할 채팅 유형", size=13, weight=ft.FontWeight.BOLD)] + checks, spacing=16),
                check_field("work_only", "업무 관련 메시지만 보고서에 요약 (인사·잡담·비속어 제외, LLM 선별)"),
                self.teams_scope_dropdown,
                ft.Row(
                    [
                        ft.Text("수집 제외할 채팅방", size=13, weight=ft.FontWeight.BOLD),
                        ft.Button(
                            "채팅방 목록 불러오기",
                            icon=ft.Icons.REFRESH,
                            on_click=self._load_chat_exclusions,
                        ),
                    ],
                    spacing=12,
                ),
                ft.Container(
                    content=self.excluded_chats_list,
                    border=ft.Border.all(1, ft.Colors.GREY_300),
                    border_radius=8,
                    padding=12,
                    height=220,
                ),
            ],
            spacing=10,
            width=row_width,
        )

    def _teams_setting_changed(self, key, value):
        """Teams 숫자/범위 설정 변경 → settings dict 갱신 + 저장"""
        if key == "days":
            try:
                value = int(value)
            except (TypeError, ValueError):
                return
            self.teams_settings[key] = max(0, value)
        else:
            self.teams_settings[key] = value
        self._save_teams_settings()

    def _teams_type_toggled(self, chat_type, checked):
        types = set(self.teams_settings.get("chat_types", []))
        if checked:
            types.add(chat_type)
        else:
            types.discard(chat_type)
        self.teams_settings["chat_types"] = sorted(types)
        self._save_teams_settings()

    def _save_teams_settings(self):
        try:
            os.makedirs("config", exist_ok=True)
            with open("config/teams_settings.json", "w", encoding="utf-8") as f:
                json.dump(self.teams_settings, f, indent=2, ensure_ascii=False)
        except Exception as ex:
            print(f"Warning: failed to save teams settings: {ex}")

    def _load_chat_exclusions(self, e):
        """Graph에서 채팅방 목록을 가져와 체크박스로 표시 (백그라운드 — 수 초 소요)"""
        self.excluded_chats_list.controls = [
            ft.Text("채팅방 목록 불러오는 중...", size=12, color=ft.Colors.GREY_500)
        ]
        self.page.update()

        def _worker():
            try:
                from teams_collector import TeamsCollector
                chats = TeamsCollector().list_chats()
            except Exception as ex:
                self.excluded_chats_list.controls = [
                    ft.Text(f"목록 로딩 실패: {ex}", size=12, color=ft.Colors.RED_400)
                ]
                self.page.update()
                return

            excluded_ids = {
                c.get("id") for c in self.teams_settings.get("excluded_chats", [])
            }
            type_label = {"oneOnOne": "1:1", "group": "그룹", "meeting": "회의"}
            controls = []
            for chat in chats:
                label = f"[{type_label.get(chat['chat_type'], chat['chat_type'])}] {chat['title']}"
                controls.append(
                    ft.Checkbox(
                        label=label,
                        value=chat["id"] in excluded_ids,
                        on_change=lambda ev, c=chat: self._teams_chat_excluded(c, ev.control.value),
                    )
                )
            if not controls:
                controls = [ft.Text("채팅방이 없거나 로그인이 필요합니다.", size=12)]
            self.excluded_chats_list.controls = controls
            self.page.update()

        threading.Thread(target=_worker, daemon=True).start()

    def _teams_chat_excluded(self, chat, checked):
        excluded = [c for c in self.teams_settings.get("excluded_chats", []) if isinstance(c, dict)]
        if checked:
            if all(c.get("id") != chat["id"] for c in excluded):
                excluded.append({"id": chat["id"], "title": chat["title"]})
        else:
            excluded = [c for c in excluded if c.get("id") != chat["id"]]
        self.teams_settings["excluded_chats"] = excluded
        self._save_teams_settings()
        self.show_snack("채팅방 제외 설정이 저장되었습니다 (수집·보고서 모두 적용)")

    def _render_watch_folder_list(self, watch_paths):
        """watch_folder_list_ref 내용을 현재 watch_paths 기준으로 다시 그림"""
        if not watch_paths:
            self.watch_folder_list_ref.controls = [
                ft.Text("등록된 감시 폴더가 없습니다.", size=13, color=ft.Colors.GREY_600)
            ]
            return

        window_width = self.page.window.width
        row_width = window_width - 200 - 60 - 48  # sidebar + margin + outer padding
        delete_area_width = 40
        text_width = row_width - 30 - delete_area_width - 24 - 16  # icon + delete area + padding + spacing

        rows = []
        for path in watch_paths:
            # Note: a Row with 3+ children silently drops its LAST child in
            # this Flet build (the same bug worked around earlier in
            # build_ui - see its docstring). Nest 2-child Rows instead of
            # using one 3-child Row.
            delete_control = ft.Container(
                content=ft.Icon(ft.Icons.DELETE_OUTLINE, color=ft.Colors.RED, size=20),
                width=delete_area_width,
                padding=8,
                border_radius=6,
                bgcolor=ft.Colors.RED_50,
                tooltip="삭제",
                on_click=lambda e, p=path: self.remove_watch_folder(p),
            )
            icon_and_text = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.FOLDER, size=18, color=ft.Colors.BLUE),
                        ft.Text(path, size=13, width=text_width),
                    ],
                    spacing=8,
                )
            )
            rows.append(
                ft.Container(
                    width=row_width,
                    content=ft.Row(
                        [icon_and_text, delete_control],
                        spacing=8,
                    ),
                    padding=ft.Padding(12, 8, 8, 8),
                    bgcolor=ft.Colors.GREY_50,
                    border_radius=8,
                    border=ft.BorderSide(1, ft.Colors.GREY_200),
                )
            )
        self.watch_folder_list_ref.controls = rows

    def add_watch_folder(self, e):
        """입력창에 적은 경로를 watch_paths에 추가.

        Note: 이 Flet 데스크톱 빌드(0.86.5)에는 FilePicker의 Windows 플러그인이
        빠져있어("Unknown control: FilePicker") 네이티브 폴더 선택 창을 쓸 수
        없음 - 그래서 경로 직접 입력 방식으로 구현함.
        """
        path = (self.new_folder_input.value or "").strip().strip('"')
        if not path:
            self.show_snack("폴더 경로를 입력해주세요")
            return

        config = self._load_watch_config()
        watch_paths = config.setdefault("watch_paths", [])
        if path in watch_paths:
            self.show_snack("이미 추가된 폴더입니다")
            return

        if not os.path.isdir(path):
            self.show_snack(f"경로를 찾을 수 없습니다: {path}")
            return

        watch_paths.append(path)
        self._save_watch_config(config)
        self._render_watch_folder_list(watch_paths)
        self.new_folder_input.value = ""
        self.page.update()
        self.show_snack(f"폴더 추가됨: {path}")

    def remove_watch_folder(self, path):
        """watch_paths에서 폴더 제거"""
        config = self._load_watch_config()
        watch_paths = config.get("watch_paths", [])
        if path in watch_paths:
            watch_paths.remove(path)
            self._save_watch_config(config)
            self._render_watch_folder_list(watch_paths)
            self.page.update()
            self.show_snack(f"폴더 삭제됨: {path}")

    def start_tracking(self):
        """Start file tracking"""
        try:
            from file_watcher import FileWatcher
            from browser_activity_server import BrowserActivityServer

            # Load config
            config_file = "config/watch_config.json"
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    watch_paths = config.get("watch_paths", [])
                    exclude_patterns = config.get("exclude_patterns", [])
            else:
                watch_paths = []
                exclude_patterns = []

            if not watch_paths:
                self.show_snack("No watch paths configured")
                return

            # Create file watcher
            log_file = "logs/file_activity.log"
            db_path = "data/activities.db"

            self.file_watcher = FileWatcher(
                watch_paths, log_file, exclude_patterns, db_path
            )

            # Start in separate thread
            self.watcher_thread = threading.Thread(
                target=self.file_watcher.start, daemon=True
            )
            self.watcher_thread.start()

            # 브라우저 확장프로그램이 활동을 보내는 로컬 서버도 같이 켜야
            # "Start Tracking" 버튼만 눌러도 browser 수집이 동작한다
            # (기존에는 integrated_collector.py를 따로 띄워야만 켜졌음)
            if self.browser_server is None:
                self.browser_server = BrowserActivityServer(db_path=db_path)
            if not self.browser_server.is_running:
                self.browser_server.start()

            self.is_running = True
            self.update_tracking_button()
            self.show_snack("Tracking started")

        except Exception as e:
            self.show_snack(f"Error starting tracking: {e}")

    def stop_tracking(self):
        """Stop file tracking"""
        if self.file_watcher:
            self.file_watcher.stop()

        if self.browser_server:
            self.browser_server.stop()

        self.is_running = False
        self.update_tracking_button()
        self.show_snack("Tracking stopped")

    def update_tracking_button(self):
        """Update tracking button state"""
        if self.tracking_button_ref:
            icon = ft.Icons.STOP if self.is_running else ft.Icons.PLAY_ARROW
            text = "Stop Tracking" if self.is_running else "Start Tracking"
            bgcolor = ft.Colors.RED if self.is_running else ft.Colors.BLUE

            self.tracking_button_ref.content.controls[0].icon = icon
            self.tracking_button_ref.content.controls[1].text = text
            self.tracking_button_ref.style.bgcolor = bgcolor
            self.page.update()

    def collect_ide(self, e):
        """Collect IDE activity"""
        try:
            from ide_collector import IDECollector

            self.show_snack("Collecting IDE activity...")

            collector = IDECollector("data/activities.db")
            ide_activities = collector.collect_all_ide_activity()

            if ide_activities:
                count = collector.save_to_database(ide_activities)
                self.show_snack(f"Collected {count} IDE activities")
            else:
                self.show_snack("No IDE activity found")

        except Exception as ex:
            self.show_snack(f"Error collecting IDE: {ex}")

    def collect_outlook(self, e):
        """Collect Outlook activity via the Outlook COM API (requires Outlook
        to be installed and running). Falls back to log-file scanning if the
        API is unavailable.
        """
        try:
            from outlook_collector import OutlookCollector, OutlookLogCollector
            from database import ActivityDatabase

            self.show_snack("Collecting Outlook activity...")

            api_collector = OutlookCollector("data/activities.db")
            api_activities = api_collector.collect_all_outlook_activity(days=7)

            if api_activities:
                count = api_collector.save_to_database(api_activities)
                self.show_snack(f"Collected {count} Outlook activities (Outlook API)")
                return

            # API returned nothing (e.g. Outlook not running) - fall back to logs
            log_collector = OutlookLogCollector("data/activities.db")
            log_activities = log_collector.collect_outlook_logs()

            if log_activities:
                with ActivityDatabase("data/activities.db") as db:
                    count = db.add_activities(log_activities)
                self.show_snack(f"Collected {count} Outlook activities (logs)")
            else:
                self.show_snack("No Outlook activity found (is Outlook running?)")

        except Exception as ex:
            self.show_snack(f"Error collecting Outlook: {ex}")

    def collect_slack(self, e):
        """Collect Slack activity"""
        try:
            from slack_collector import SlackCollector

            self.show_snack("Collecting Slack activity...")

            # Load Slack config
            config_file = "config/slack_config.json"
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)

                if not config.get("enabled", False):
                    self.show_snack("Slack collection is disabled in config")
                    return

                token = config.get("token", "")
                if not token:
                    self.show_snack("No Slack token configured")
                    return
            else:
                self.show_snack("Slack config not found")
                return

            collector = SlackCollector("data/activities.db", token=token)
            slack_activities = collector.collect_all_slack_activity(days=7)

            if slack_activities:
                count = collector.save_to_database(slack_activities)
                self.show_snack(f"Collected {count} Slack activities")
            else:
                self.show_snack("No Slack activity found")

        except Exception as ex:
            self.show_snack(f"Error collecting Slack: {ex}")

    def collect_confluence(self, e):
        """Collect Confluence activity"""
        try:
            from confluence_collector import ConfluenceCollector

            self.show_snack("Collecting Confluence activity...")

            config_file = "config/confluence_config.json"
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)

                if not config.get("enabled", False):
                    self.show_snack("Confluence collection is disabled in config")
                    return

                if not config.get("personal_access_token", ""):
                    self.show_snack("No Confluence token configured")
                    return
            else:
                self.show_snack("Confluence config not found")
                return

            collector = ConfluenceCollector(
                "data/activities.db", config_path=config_file
            )
            confluence_activities = collector.collect_all_confluence_activity(days=7)

            if confluence_activities:
                count = collector.save_to_database(confluence_activities)
                self.show_snack(f"Collected {count} Confluence activities")
            else:
                self.show_snack("No Confluence activity found")

        except Exception as ex:
            self.show_snack(f"Error collecting Confluence: {ex}")

    def generate_report(self, e):
        """Generate weekly report"""
        try:
            from report_generator import ReportGenerator

            self.show_snack("Generating weekly report...")
            generator = ReportGenerator()
            result = generator.generate_and_save_weekly_report()
            generated_paths = [path for path in result["file_paths"].values() if path]
            if generated_paths:
                self.show_snack(f"보고서 생성 완료: {generated_paths[0]}")
                print("Generated weekly report files:")
                for path in generated_paths:
                    print(f"- {path}")
            else:
                self.show_snack("보고서 생성 결과 파일이 없습니다")
        except Exception as ex:
            print(f"Error generating weekly report: {ex}")
            self.show_snack(f"Error generating weekly report: {ex}")

    def preview_draft(self, e):
        """Preview draft report"""
        try:
            from report_generator import ReportGenerator

            self.show_snack("Previewing draft report...")
            generator = ReportGenerator()
            weekly_data = generator.collect_weekly_data()
            markdown_preview = generator.generate_markdown(weekly_data)
            print("\n=== Weekly Report Preview ===\n")
            print(markdown_preview)
            self.show_snack(f"미리보기 생성 완료 ({len(markdown_preview)}자)")
        except Exception as ex:
            print(f"Error previewing weekly report: {ex}")
            self.show_snack(f"Error previewing weekly report: {ex}")

    def show_snack(self, message):
        """Show snack bar message"""
        snack_bar = ft.SnackBar(
            content=ft.Text(message),
            duration=3000,
        )
        self.page.overlay.append(snack_bar)
        snack_bar.open = True
        self.page.update()


def main(page: ft.Page):
    """Main entry point"""
    app = WeeklyPulseApp(page)
    page.add(app.build_ui())
    page.update()
    app.start_status_refresh_loop()
    # 추적은 프로그램 시작과 동시에 자동으로 켬 — 별도 Start 버튼 없음.
    # FileWatcher import+시작에 수 백ms 걸리므로 UI 표시를 지연시키지 않도록
    # 백그라운드 스레드로 돌림
    threading.Thread(target=app.start_tracking, daemon=True).start()


if __name__ == "__main__":
    ft.run(main)
