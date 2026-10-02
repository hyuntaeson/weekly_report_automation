"""Settings > 나만의 비서 — 자동 실행 켜기/끄기, 공휴일 (config/report_settings.json의 todo_auto·holidays)."""

from datetime import date

import flet as ft

from weekly_report.gui.widgets import removable_chip

# 올해 남은 법정 공휴일 (2026-10 기준) — 회사 휴무일은 사용자가 직접 추가
SUGGESTED_HOLIDAYS = {"2026-10-05": "개천절 대체공휴일", "2026-10-09": "한글날", "2026-12-25": "성탄절"}
WEEKDAYS = "월화수목금토일"


class AssistantSettingsMixin:
    def _create_assistant_settings_section(self):
        row_width = self.page.window.width - 200 - 60 - 48
        self.holiday_input = ft.TextField(label="공휴일·휴무일 추가", hint_text="예: 2026-10-05", width=260,
                                          on_submit=self._add_holiday)
        self.holiday_chips = ft.Row(spacing=8, run_spacing=8, wrap=True)
        self._render_holidays()
        auto = ft.Switch(label="근무일 09:00 오늘 할 일 추출 · 17:00 진행 점검 자동 실행",
                         value=bool(self.report_settings.get("todo_auto", True)),
                         on_change=lambda e: self._todo_auto_changed(e.control.value))
        add_button = ft.Button("추가", icon=ft.Icons.ADD, on_click=self._add_holiday,
                               style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE, padding=14,
                                                    shape=ft.RoundedRectangleBorder(radius=8)))
        suggest = ft.TextButton("올해 남은 공휴일 넣기 (10/05·10/09·12/25)", icon=ft.Icons.EVENT_AVAILABLE,
                                on_click=self._add_suggested_holidays)
        return ft.Column(
            [
                ft.Text("나만의 비서", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK),
                ft.Text("프로그램이 켜져 있으면 근무일 09:00에 오늘 할 일을 뽑고 17:00에 진행 상황을 점검합니다. "
                        "그 시각에 PC가 꺼져 있었으면 다음에 켤 때 바로 실행합니다. "
                        "주말과 아래 공휴일·휴무일은 근무일에서 빠집니다 (월요일·연휴 다음 날은 직전 근무일부터 분석).",
                        size=12, color=ft.Colors.GREY_600),
                auto,
                ft.Row([ft.Row([self.holiday_input, add_button], spacing=8), suggest], spacing=16),
                self.holiday_chips,
            ],
            spacing=10,
            width=row_width,
        )

    def _holidays(self):
        return sorted(set(self.report_settings.get("holidays") or []))

    def _render_holidays(self):
        days = self._holidays()
        if not days:
            self.holiday_chips.controls = [ft.Text("등록된 공휴일이 없습니다 — 주말만 근무일에서 빠집니다.",
                                                   size=12, color=ft.Colors.GREY_500)]
            return
        chips = []
        for d in days:
            day = date.fromisoformat(d)
            label = f"{d} ({WEEKDAYS[day.weekday()]})" + (f" {SUGGESTED_HOLIDAYS[d]}" if d in SUGGESTED_HOLIDAYS else "")
            chips.append(removable_chip(label, lambda e, d=d: self._remove_holiday(d)))
        self.holiday_chips.controls = chips

    def _save_holidays(self, days):
        self.report_settings["holidays"] = sorted(set(days))
        self._save_report_settings()
        self._render_holidays()
        self.page.update()

    def _add_holiday(self, e=None):
        value = (self.holiday_input.value or "").strip().replace(".", "-").replace("/", "-")
        try:
            day = date.fromisoformat(value)
        except ValueError:
            self.show_snack("날짜를 2026-10-05 형식으로 입력해주세요")
            return
        if day.isoformat() in self._holidays():
            self.show_snack("이미 등록된 날짜입니다")
            return
        self.holiday_input.value = ""
        self._save_holidays(self._holidays() + [day.isoformat()])
        self.show_snack(f"공휴일 추가됨: {day.isoformat()}({WEEKDAYS[day.weekday()]})")

    def _add_suggested_holidays(self, e=None):
        today = date.today().isoformat()
        new = [d for d in SUGGESTED_HOLIDAYS if d >= today and d not in self._holidays()]
        self._save_holidays(self._holidays() + new)
        self.show_snack(f"공휴일 {len(new)}개 추가됨" if new else "이미 모두 등록돼 있어요")

    def _remove_holiday(self, day):
        self._save_holidays([d for d in self._holidays() if d != day])
        self.show_snack(f"공휴일 삭제됨: {day}")

    def _todo_auto_changed(self, value):
        self.report_settings["todo_auto"] = bool(value)
        self._save_report_settings()
        self.show_snack("자동 실행을 켰어요" if value else "자동 실행을 껐어요 — 메인 카드 버튼으로 실행하세요")
