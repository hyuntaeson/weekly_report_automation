"""Settings > Teams 수집·보고 설정 — 채팅 유형, 보고 범위, 예상질문자, 제외 채팅방 (config/teams_settings.json)."""

import json
import os
import threading

import flet as ft

from weekly_report.gui.widgets import removable_chip


class TeamsSettingsMixin:
    def _create_teams_settings_section(self):
        """Settings 화면의 'Teams 수집·보고 설정' 섹션 — config/teams_settings.json에 저장"""
        from weekly_report.collectors.teams import load_teams_settings

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
        self.questioner_input = ft.TextField(
            label="예상질문자",
            hint_text="Teams에 표시되는 이름 (예: 김영호)",
            width=row_width - 110,
            on_submit=self._add_expected_questioner,
        )
        self.questioner_chips = ft.Row(spacing=8, run_spacing=8, wrap=True)
        self._render_expected_questioners()
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
                ft.Container(height=4),
                ft.Row(
                    [
                        self.questioner_input,
                        ft.Button(
                            "추가",
                            icon=ft.Icons.ADD,
                            style=ft.ButtonStyle(
                                bgcolor=ft.Colors.BLUE,
                                color=ft.Colors.WHITE,
                                padding=14,
                                shape=ft.RoundedRectangleBorder(radius=8),
                            ),
                            on_click=self._add_expected_questioner,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Text(
                    "지정한 사람과의 Teams 대화에서 질문 성향을 학습해, 보고서 STEP 3에 예상 질문과 답변 초안을 만듭니다.",
                    size=12, color=ft.Colors.GREY_600,
                ),
                self.questioner_chips,
                ft.Container(height=4),
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
        # 읽기(load_teams_settings)와 같은 절대 경로에 저장 — 상대 경로면 다른
        # 폴더에서 실행했을 때 저장한 설정이 반영되지 않음
        from weekly_report.collectors.teams import SETTINGS_FILE
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.teams_settings, f, indent=2, ensure_ascii=False)
        except Exception as ex:
            print(f"Warning: failed to save teams settings: {ex}")

    def _render_expected_questioners(self):
        """등록된 예상질문자를 삭제 가능한 칩으로 표시"""
        names = self.teams_settings.get("expected_questioners", [])
        if not names:
            self.questioner_chips.controls = [
                ft.Text("등록된 예상질문자가 없습니다.", size=12, color=ft.Colors.GREY_500)
            ]
            return
        self.questioner_chips.controls = [
            removable_chip(name, lambda e, n=name: self._remove_expected_questioner(n))
            for name in names
        ]

    def _add_expected_questioner(self, e):
        name = " ".join((self.questioner_input.value or "").split())
        if not name:
            self.show_snack("예상질문자 이름을 입력해주세요")
            return
        names = list(self.teams_settings.get("expected_questioners", []))
        if name in names:
            self.show_snack("이미 등록된 예상질문자입니다")
            return
        names.append(name)
        self.teams_settings["expected_questioners"] = names
        self._save_teams_settings()
        self._render_expected_questioners()
        self.questioner_input.value = ""
        self.page.update()
        self.show_snack(f"예상질문자 추가됨: {name}")

    def _remove_expected_questioner(self, name):
        names = [n for n in self.teams_settings.get("expected_questioners", []) if n != name]
        self.teams_settings["expected_questioners"] = names
        self._save_teams_settings()
        self._render_expected_questioners()
        self.page.update()
        self.show_snack(f"예상질문자 삭제됨: {name}")

    def _load_chat_exclusions(self, e):
        """Graph에서 채팅방 목록을 가져와 체크박스로 표시 (백그라운드 — 수 초 소요)"""
        self.excluded_chats_list.controls = [
            ft.Text("채팅방 목록 불러오는 중...", size=12, color=ft.Colors.GREY_500)
        ]
        self.page.update()

        def _worker():
            try:
                from weekly_report.collectors.teams import TeamsCollector
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
            # 수집 유형에서 빠진 채팅 유형의 방은 제외 선택지에도 안 띄운다
            allowed = set(self.teams_settings.get("chat_types", []))
            type_label = {"oneOnOne": "1:1", "group": "그룹", "meeting": "회의"}
            controls = []
            for chat in chats:
                if chat.get("chat_type") not in allowed:
                    continue
                last = (chat.get("last_activity") or "")[:10]
                label = (
                    f"[{type_label.get(chat['chat_type'], chat['chat_type'])}] "
                    f"{chat['title']} · {last}"
                )
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
