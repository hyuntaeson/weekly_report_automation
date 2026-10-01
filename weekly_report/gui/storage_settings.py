"""Settings > 저장소 관리 — 활동 벡터 보관 기간 · 현재 사용량 · 속도 영향 안내 (config/report_settings.json)."""

import flet as ft


def _mb(size):
    return f"{size / 1024 / 1024:,.1f}MB"


class StorageSettingsMixin:
    def _create_storage_settings_section(self):
        from weekly_report.storage.retention import DEFAULT_RETENTION_WEEKS, RETENTION_CHOICES

        row_width = self.page.window.width - 200 - 60 - 48
        weeks = self.report_settings.get("vector_retention_weeks", DEFAULT_RETENTION_WEEKS)
        labels = {8: "8주 (약 2개월)", 12: "12주 (약 3개월)", 26: "26주 (약 6개월)", 52: "52주 (약 1년)",
                  78: "78주 (약 1년 6개월)", 104: "104주 (약 2년)"}
        self.retention_dropdown = ft.Dropdown(
            label="활동 벡터 보관 기간",
            value=str(weeks),
            options=[ft.dropdown.Option(str(w), labels.get(w, f"{w}주")) for w in RETENTION_CHOICES],
            width=260,
            on_select=lambda e: self._retention_changed(e.control.value),
        )
        self.storage_usage_text = ft.Text("사용량 확인 중…", size=13, color=ft.Colors.GREY_800, selectable=True)
        self.storage_speed_text = ft.Text("", size=12, color=ft.Colors.ORANGE_900)
        self.storage_last_run_text = ft.Text("", size=12, color=ft.Colors.GREY_600)
        self.storage_cleanup_button = ft.Button(
            "지금 정리",
            icon=ft.Icons.CLEANING_SERVICES_OUTLINED,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.BLUE,
                color=ft.Colors.WHITE,
                padding=14,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
            on_click=self._cleanup_storage_clicked,
        )
        self._vector_stats = None
        self._render_storage_info()
        # VectorDB 개수·여는 시간은 실제로 열어야 알 수 있어(수 초) 화면을 띄운 뒤 채운다
        self.page.run_thread(self._load_vector_stats)
        return ft.Column(
            [
                ft.Text("저장소 관리 — 보관 기간", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK),
                ft.Text(
                    "보관 기간이 지난 주의 활동 벡터(VectorDB)는 그 주의 업무 요약을 먼저 저장한 뒤 삭제합니다. "
                    "원본 활동 기록은 지우지 않으므로, 지난 업무도 주간 요약으로 찾고 원본에서 상세 내용을 확인할 수 있습니다. "
                    "정리는 보고서 생성 후 주 1회 자동으로 실행됩니다.",
                    size=12, color=ft.Colors.GREY_600,
                ),
                ft.Row([self.retention_dropdown, self.storage_cleanup_button], spacing=12),
                ft.Container(
                    content=ft.Column(
                        [self.storage_usage_text, self.storage_speed_text, self.storage_last_run_text],
                        spacing=6,
                    ),
                    padding=14,
                    border_radius=8,
                    bgcolor=ft.Colors.GREY_100,
                    width=row_width,
                ),
            ],
            spacing=10,
            width=row_width,
        )

    def _retention_weeks(self):
        from weekly_report.storage.retention import DEFAULT_RETENTION_WEEKS
        return int(self.report_settings.get("vector_retention_weeks", DEFAULT_RETENTION_WEEKS))

    def _retention_changed(self, value):
        try:
            self.report_settings["vector_retention_weeks"] = int(value)
        except (TypeError, ValueError):
            return
        self._save_report_settings()
        self._render_storage_info()
        self.page.update()
        self.show_snack(f"활동 벡터 보관 기간: {value}주")

    def _load_vector_stats(self):
        from weekly_report.storage.retention import vector_stats
        try:
            self._vector_stats = vector_stats()
        except Exception as ex:
            print(f"Warning: vector stats failed: {ex}")
            self._vector_stats = {"error": str(ex)}
        self._render_storage_info()
        self.page.update()

    def _render_storage_info(self):
        from weekly_report.storage.retention import estimate, last_run, storage_usage

        usage = storage_usage()
        stats = self._vector_stats
        weeks = self._retention_weeks()
        lines = [f"현재 사용량: 전체 {_mb(usage['data'])}"]
        legacy = f" (정리 대상 레거시 임베딩 {usage['legacy_rows']:,}건 포함)" if usage["legacy_rows"] else ""
        lines.append(f"· 활동 기록 DB {_mb(usage['db'])}{legacy}")
        if stats is None:
            lines.append(f"· VectorDB {_mb(usage['vectors'])} — 벡터 수 확인 중…")
        elif "error" in stats:
            lines.append(f"· VectorDB {_mb(usage['vectors'])} — 확인 실패 (다른 작업이 사용 중일 수 있음)")
        else:
            lines.append(
                f"· VectorDB {_mb(usage['vectors'])} — 활동 벡터 {stats['count']:,}개, "
                f"주간 요약 {stats['summary_weeks']}주, 여는 시간 {stats['open_seconds']:.1f}초"
            )
        lines.append(f"· LLM 응답 캐시 {_mb(usage['llm_cache'])}")
        self.storage_usage_text.value = "\n".join(lines)

        speed = ("VectorDB는 보고서를 만들 때 저장된 벡터 전체를 메모리로 읽습니다. "
                 "보관 기간이 길수록 벡터가 많아져 보고서 생성이 느려집니다.")
        if stats and "error" not in stats and stats["weekly_rate"]:
            est = estimate(weeks, stats["weekly_rate"])
            speed += (f"\n최근 주 평균 약 {stats['weekly_rate']:,.0f}개씩 늘고 있어, {weeks}주를 다 채우면 "
                      f"약 {est['vectors']:,}개 · {est['mb']:,.0f}MB · 여는 데 약 {est['open_seconds']:.0f}초가 예상됩니다.")
        self.storage_speed_text.value = "⚠ " + speed

        state = last_run()
        if state.get("last_run"):
            r = state.get("result", {})
            self.storage_last_run_text.value = (
                f"마지막 정리: {state['last_run'].replace('T', ' ')} — 벡터 {r.get('deleted', 0):,}개 삭제, "
                f"주간 요약 {len(r.get('summarized', []))}주 저장"
                + (f", 요약 실패로 {len(r['kept'])}주 보류" if r.get("kept") else "")
            )
        else:
            self.storage_last_run_text.value = "아직 정리한 적 없음 — 보고서 생성 후 자동으로 실행됩니다."

    def _cleanup_storage_clicked(self, e):
        from weekly_report.storage.retention import run_retention

        weeks = self._retention_weeks()
        self.storage_cleanup_button.disabled = True
        self.storage_last_run_text.value = f"정리 중… ({weeks}주 이전 벡터)"
        self.page.update()

        def worker():
            try:
                def progress(msg):
                    self.storage_last_run_text.value = f"정리 중… {msg}"
                    self.page.update()
                result = run_retention(weeks, progress=progress)
                message = f"정리 완료: 벡터 {result['deleted']:,}개 삭제, 주간 요약 {len(result['summarized'])}주 저장"
            except Exception as ex:
                print(f"Error: storage cleanup failed: {ex}")
                message = f"정리 실패: {ex}"
            self.storage_cleanup_button.disabled = False
            self._vector_stats = None
            self._render_storage_info()
            self.page.update()
            self.show_snack(message)
            self._load_vector_stats()

        self.page.run_thread(worker)

    def auto_cleanup_storage(self):
        """보고서 생성 후 호출 — 마지막 정리 후 7일이 지났을 때만 실행 (백그라운드 스레드에서)"""
        from weekly_report.ai.rag import load_report_settings
        from weekly_report.storage.retention import DEFAULT_RETENTION_WEEKS, run_if_due
        try:
            weeks = int(load_report_settings().get("vector_retention_weeks", DEFAULT_RETENTION_WEEKS))
            result = run_if_due(weeks)
            if result:
                print(f"Storage cleanup: {result}")
        except Exception as ex:
            print(f"Warning: storage cleanup failed: {ex}")
