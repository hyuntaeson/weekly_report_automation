"""여러 화면에서 같이 쓰는 작은 컨트롤."""

import flet as ft


def removable_chip(label, on_remove):
    """X 버튼으로 지울 수 있는 칩 (예상질문자·주제 질의 공용)"""
    return ft.Container(
        content=ft.Row(
            [
                ft.Text(label, size=13, color=ft.Colors.BLUE_900, weight=ft.FontWeight.W_600),
                ft.Container(
                    content=ft.Icon(ft.Icons.CLOSE, size=16, color=ft.Colors.BLUE_900),
                    tooltip="삭제",
                    on_click=on_remove,
                ),
            ],
            spacing=6,
            tight=True,
        ),
        padding=ft.Padding(12, 6, 8, 6),
        bgcolor=ft.Colors.BLUE_50,
        border_radius=16,
        border=ft.Border.all(1, ft.Colors.BLUE_100),
    )
