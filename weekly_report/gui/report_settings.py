"""Settings > 보고서 설정 — RAG 주제 질의 (config/report_settings.json)."""

import flet as ft

from weekly_report.gui.widgets import removable_chip


class ReportSettingsMixin:
    def _create_report_settings_section(self):
        """Settings 화면의 '보고서 설정 — 주제 질의' 섹션 — config/report_settings.json에 저장"""
        from weekly_report.ai.rag import load_report_settings

        self.report_settings = load_report_settings()
        row_width = self.page.window.width - 200 - 60 - 48
        self.rag_topic_input = ft.TextField(
            label="주제 추가",
            hint_text="예: 손익·예산, 구매·계약, 장애 대응",
            width=row_width - 110,
            on_submit=self._add_rag_topic,
        )
        self.rag_topic_chips = ft.Row(spacing=8, run_spacing=8, wrap=True)
        self._render_rag_topics()
        past_weeks = ft.TextField(
            label="지난 기록 검색 범위(주)",
            value=str(self.report_settings.get("rag_past_weeks", 4)),
            hint_text="기본 4, 0이면 이번 주만",
            width=200,
            on_change=lambda e: self._rag_past_weeks_changed(e.control.value),
        )
        return ft.Column(
            [
                ft.Text("보고서 설정 — 주제 질의", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK),
                ft.Text(
                    "주제마다 VectorDB에서 관련 기록을 찾아 STEP 2 '주제 질의 요약'에 근거 번호와 함께 정리합니다. "
                    "관련 기록이 없는 주제는 보고서에서 생략됩니다.",
                    size=12, color=ft.Colors.GREY_600,
                ),
                ft.Row(
                    [
                        self.rag_topic_input,
                        ft.Button(
                            "추가",
                            icon=ft.Icons.ADD,
                            style=ft.ButtonStyle(
                                bgcolor=ft.Colors.BLUE,
                                color=ft.Colors.WHITE,
                                padding=14,
                                shape=ft.RoundedRectangleBorder(radius=8),
                            ),
                            on_click=self._add_rag_topic,
                        ),
                    ],
                    spacing=8,
                ),
                self.rag_topic_chips,
                past_weeks,
            ],
            spacing=10,
            width=row_width,
        )

    def _save_report_settings(self):
        from weekly_report.ai.rag import save_report_settings
        try:
            save_report_settings(self.report_settings)
        except Exception as ex:
            print(f"Warning: failed to save report settings: {ex}")

    def _render_rag_topics(self):
        topics = self.report_settings.get("rag_topics", [])
        if not topics:
            self.rag_topic_chips.controls = [
                ft.Text("등록된 주제가 없습니다 — 주제 질의 섹션이 생략됩니다.", size=12, color=ft.Colors.GREY_500)
            ]
            return
        self.rag_topic_chips.controls = [
            removable_chip(topic, lambda e, t=topic: self._remove_rag_topic(t))
            for topic in topics
        ]

    def _add_rag_topic(self, e):
        topic = " ".join((self.rag_topic_input.value or "").split())
        if not topic:
            self.show_snack("주제를 입력해주세요")
            return
        topics = list(self.report_settings.get("rag_topics", []))
        if topic in topics:
            self.show_snack("이미 등록된 주제입니다")
            return
        topics.append(topic)
        self.report_settings["rag_topics"] = topics
        self._save_report_settings()
        self._render_rag_topics()
        self.rag_topic_input.value = ""
        self.page.update()
        self.show_snack(f"주제 추가됨: {topic}")

    def _remove_rag_topic(self, topic):
        self.report_settings["rag_topics"] = [
            t for t in self.report_settings.get("rag_topics", []) if t != topic
        ]
        self._save_report_settings()
        self._render_rag_topics()
        self.page.update()
        self.show_snack(f"주제 삭제됨: {topic}")

    def _rag_past_weeks_changed(self, value):
        try:
            self.report_settings["rag_past_weeks"] = max(0, min(52, int(value)))
        except (TypeError, ValueError):
            return
        self._save_report_settings()
