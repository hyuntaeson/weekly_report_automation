#!/usr/bin/env python3
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportOptionalMemberAccess=false
"""
WeeklyPulse GUI (Flet) — 앱 뼈대: 창 설정, 사이드바 내비게이션, 화면 전환.

화면별 코드는 mixin으로 나눠 둠:
  dashboard.py        대시보드 (앱 감지·통계·보고서 생성 버튼)
  watch_settings.py   Settings 뼈대 + 감시 폴더
  teams_settings.py   Settings > Teams 수집·보고 설정
  report_settings.py  Settings > 보고서 설정 (RAG 주제 질의·근거 제외 키워드)
  storage_settings.py Settings > 저장소 관리 (보관 기간·사용량)
  todo_card.py        메인 '오늘 할 일' 카드 (나만의 비서, 09:00·17:00 자동 실행)
  assistant_settings.py Settings > 나만의 비서 (자동 실행·공휴일)
  actions.py          추적·수집·보고서 생성 동작
  widgets.py          공용 컨트롤
"""

import os
import threading

import flet as ft

from weekly_report import paths
from weekly_report.gui.actions import ActionsMixin
from weekly_report.gui.assistant_settings import AssistantSettingsMixin
from weekly_report.gui.dashboard import DashboardMixin
from weekly_report.gui.report_settings import ReportSettingsMixin
from weekly_report.gui.storage_settings import StorageSettingsMixin
from weekly_report.gui.teams_settings import TeamsSettingsMixin
from weekly_report.gui.todo_card import TodoCardMixin
from weekly_report.gui.watch_settings import WatchSettingsMixin

# 수집기·보고서 생성기 등 무거운 모듈은 실제 호출 시점에 lazy import —
# langchain/langgraph/docx/watchdog 로딩이 창이 뜨기 전 수 초를 차지하므로
# 최초 렌더링 경로에서는 빼둔다.


def work_area():
    """작업표시줄을 뺀 화면 영역 (left, top, width, height) — 논리 픽셀(화면 배율 반영). Windows 외에는 None"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if not ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
            return None
        scale = ctypes.windll.user32.GetDpiForSystem() / 96 or 1
        return (rect.left / scale, rect.top / scale,
                (rect.right - rect.left) / scale, (rect.bottom - rect.top) / scale)
    except Exception:
        return None


class WeeklyPulseApp(DashboardMixin, TodoCardMixin, WatchSettingsMixin, TeamsSettingsMixin,
                     ReportSettingsMixin, StorageSettingsMixin, AssistantSettingsMixin, ActionsMixin):
    """Modern WeeklyPulse-style application with proper sizing"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "WeeklyPulse"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self._fit_window_to_work_area(width=1400, height=780, min_width=1200, min_height=650)
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

        # UI references
        self.tracking_button_ref = None
        self.nav_items = {}
        self.app_card_refs = {}
        self.status_refresh_thread = None
        self.main_content_column = None
        self.watch_folder_list_ref = None
        self.watch_config_path = paths.WATCH_CONFIG

    def _fit_window_to_work_area(self, width, height, min_width, min_height):
        """창을 작업표시줄을 뺀 화면 영역(작업 영역) 안에 맞춘다 — 기본 크기가 들어가면 그대로,
        안 들어가면 줄이고 위쪽에 붙인다. 넘치는 내용은 본문 스크롤로 본다.
        (예전엔 고정 1400×780이라 화면 배율 125% 노트북에서 작업표시줄을 덮었음)"""
        window = self.page.window
        area = work_area()
        if area:
            left, top, area_width, area_height = area
            width, height = min(width, area_width), min(height, area_height)
            min_width, min_height = min(min_width, width), min(min_height, height)
            window.left = left + (area_width - width) / 2
            window.top = top + max(0, (area_height - height) / 2)
        window.width, window.height = width, height
        window.min_width, window.min_height = min_width, min_height

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
    app.start_todo_scheduler()  # 근무일 09:00 할 일 추출·17:00 진행 점검 (놓쳤으면 켜자마자)
    # 추적은 프로그램 시작과 동시에 자동으로 켬 — 별도 Start 버튼 없음.
    # FileWatcher import+시작에 수 백ms 걸리므로 UI 표시를 지연시키지 않도록
    # 백그라운드 스레드로 돌림
    threading.Thread(target=app.start_tracking, daemon=True).start()


if __name__ == "__main__":
    ft.run(main)
