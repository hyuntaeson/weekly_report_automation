"""대시보드 화면 — 실행 중인 앱 감지(Active Work Sessions), 주간 통계 카드, 보고서 생성 버튼."""

import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

import flet as ft
import psutil

try:
    import win32gui
    import win32process

    _WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32process = None
    _WIN32_AVAILABLE = False

_STATUS_LOCK = threading.Lock()  # 보고서 생성 상태: 작업 스레드와 경과 시간 타이머가 같이 갱신


SESSION_CARDS_PER_ROW = 6


class DashboardMixin:
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

    def build_dashboard_controls(self):
        """Dashboard 화면(기본 화면)의 컨트롤 목록. Settings 등으로 전환했다가
        다시 돌아올 때도 재사용."""
        return [
            self.create_header(),
            self.create_todo_card(),
            self.create_active_sessions(),
            self.create_control_panel(),
        ]

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

        # 한 줄에 6개씩 (앱 12개 → 2줄)
        rows = []
        for i in range(0, len(app_cards), SESSION_CARDS_PER_ROW):
            row_cards = app_cards[i : i + SESSION_CARDS_PER_ROW]
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
                    ft.Container(height=4),  # Spacer
                    # App cards rows
                    ft.Column(
                        rows,
                        spacing=10,
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
            size=22,
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
                        width=22,
                        height=22,
                    ),
                    # App name
                    ft.Text(
                        app_name,
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.BLACK,
                    ),
                    # Last active
                    ft.Text(
                        f"Last active {app_data['last_active']}",
                        size=10,
                        color=ft.Colors.GREY_600,
                    ),
                ],
                spacing=3,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=8,
            border_radius=12,
            bgcolor=ft.Colors.WHITE,
            border=ft.BorderSide(1, ft.Colors.GREY_200),
            shadow=ft.BoxShadow(
                blur_radius=8,
                spread_radius=1,
                color=ft.Colors.GREY_200,
                offset=ft.Offset(0, 2),
            ),
            width=150,
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
                                "보고서 생성",
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
                    ft.Container(height=6),
                    # 주 액션: 보고서 생성 — 패널 폭 전체의 다크 버튼
                    ft.Row(
                        [
                            self._remember_generate_button(ft.Button(
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
                            )),
                        ],
                    ),
                    self.create_report_status(),
                ],
                spacing=8,
            ),
            padding=ft.Padding(24, 14, 24, 14),
            bgcolor=ft.Colors.GREY_50,
            border_radius=12,
        )

    # ---------- 보고서 생성 상태 표시 ----------

    REPORT_STATUS_STYLE = {
        "생성대기": (ft.Colors.GREY_700, ft.Colors.GREY_200),
        "작성 중": (ft.Colors.ORANGE_900, ft.Colors.ORANGE_100),
        "주간보고 생성완료": (ft.Colors.GREEN_900, ft.Colors.GREEN_100),
        "생성 실패": (ft.Colors.RED_900, ft.Colors.RED_100),
    }

    def _report_state(self):
        """상태는 앱 객체에 보관 — 화면을 전환했다 돌아와도 유지"""
        if not hasattr(self, "report_state"):
            self.report_state = {"status": "생성대기", "requested_at": "--:--:--", "detail": "",
                                 "output_path": None}
        return self.report_state

    def open_report_folder(self, e=None):
        """생성된 보고서 파일이 있는 폴더를 탐색기로 열기 (Windows는 파일을 선택한 상태로)"""
        path = self._report_state().get("output_path")
        if not path:
            return
        path = os.path.abspath(path)
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception as ex:
            self.show_snack(f"폴더를 열 수 없습니다: {ex}")

    def _remember_generate_button(self, button):
        """작성 중에는 비활성화하려고 버튼을 보관 (화면 전환 시 새로 만들어지면 교체)"""
        self.generate_button = button
        button.disabled = self._report_state()["status"] == "작성 중"
        return button

    def create_report_status(self):
        """Generate 버튼 아래 상태 줄: Status 칩 + 요청 시각 / 진행 단계·소요 시간.
        (이 Flet 빌드는 Row 자식이 3개 이상이면 마지막이 사라져서 2개씩 중첩)"""
        state = self._report_state()
        fg, bg = self.REPORT_STATUS_STYLE.get(state["status"], self.REPORT_STATUS_STYLE["생성대기"])
        self.report_status_text = ft.Text(state["status"], size=13, weight=ft.FontWeight.BOLD, color=fg)
        self.report_status_chip = ft.Container(
            content=self.report_status_text,
            padding=ft.Padding.symmetric(horizontal=12, vertical=4),
            bgcolor=bg,
            border_radius=999,
        )
        self.report_time_text = ft.Text(state["requested_at"], size=13, weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.BLACK)
        self.report_detail_text = ft.Text(state["detail"], size=12, color=ft.Colors.GREY_700)
        # 완료 시 파일명 옆 폴더 바로가기
        self.report_folder_button = ft.Container(
            content=ft.Icon(ft.Icons.FOLDER_OPEN, size=18, color=ft.Colors.BLUE),
            tooltip="보고서 폴더 열기",
            padding=4,
            border_radius=6,
            on_click=self.open_report_folder,
            visible=bool(state.get("output_path")),
        )
        detail_row = ft.Row([self.report_detail_text, self.report_folder_button], spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        status_group = ft.Row(
            [ft.Text("Status", size=13, color=ft.Colors.GREY_600), self.report_status_chip],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        time_group = ft.Row(
            [ft.Text("요청 시각", size=13, color=ft.Colors.GREY_600), self.report_time_text],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row([status_group, time_group], spacing=32,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    detail_row,
                ],
                spacing=6,
            ),
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, ft.Colors.GREY_200),
            border_radius=8,
        )

    def set_report_status(self, status=None, detail=None, requested_at=None, only_if=None,
                          output_path=None):
        """상태 값 갱신 + 화면에 있으면 바로 반영 (백그라운드 스레드에서 호출해도 됨).
        only_if: 현재 상태가 이 값일 때만 갱신 (경과 시간 타이머가 완료 표시를 덮어쓰지 않도록)
        output_path: 완료 시 생성 파일 — 폴더 바로가기 아이콘 표시. 상태가 바뀌면 지워짐."""
        state = self._report_state()
        with _STATUS_LOCK:
            if only_if is not None and state["status"] != only_if:
                return
            if status is not None:
                state["status"] = status
                state["output_path"] = output_path
            if detail is not None:
                state["detail"] = detail
            if requested_at is not None:
                state["requested_at"] = requested_at
        if getattr(self, "report_status_text", None) is None:
            return
        fg, bg = self.REPORT_STATUS_STYLE.get(state["status"], self.REPORT_STATUS_STYLE["생성대기"])
        self.report_status_text.value = state["status"]
        self.report_status_text.color = fg
        self.report_status_chip.bgcolor = bg
        self.report_time_text.value = state["requested_at"]
        self.report_detail_text.value = state["detail"]
        self.report_folder_button.visible = bool(state.get("output_path"))
        button = getattr(self, "generate_button", None)
        if button is not None:
            button.disabled = state["status"] == "작성 중"
        try:
            self.page.update()
        except Exception:
            pass

