"""Settings 화면 뼈대 + 감시 폴더(Watch Folders) 추가/삭제."""

import json
import os

import flet as ft


class WatchSettingsMixin:
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
                    ft.Container(height=24),
                    self._create_report_settings_section(),
                    ft.Container(height=24),
                    self._create_storage_settings_section(),
                    ft.Container(height=24),
                    self._create_assistant_settings_section(),
                ],
                spacing=8,
            ),
            padding=24,
        )

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
