"""추적 시작/중지, 소스별 수동 수집, 보고서 생성 — 무거운 모듈은 호출 시점에 lazy import."""

import asyncio
import json
import os
import threading
import time
from datetime import datetime

import flet as ft

from weekly_report import paths


class ActionsMixin:
    def toggle_tracking(self, e):
        """Toggle file tracking"""
        if not self.is_running:
            self.start_tracking()
        else:
            self.stop_tracking()

    def start_tracking(self):
        """Start file tracking"""
        try:
            from weekly_report.collectors.file_watcher import FileWatcher
            from weekly_report.collectors.browser_server import BrowserActivityServer

            # Load config
            config_file = paths.WATCH_CONFIG
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
            log_file = paths.FILE_ACTIVITY_LOG
            db_path = paths.DB_PATH

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
            from weekly_report.collectors.ide import IDECollector

            self.show_snack("Collecting IDE activity...")

            collector = IDECollector(paths.DB_PATH)
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
            from weekly_report.collectors.outlook import OutlookCollector, OutlookLogCollector
            from weekly_report.storage.database import ActivityDatabase

            self.show_snack("Collecting Outlook activity...")

            api_collector = OutlookCollector(paths.DB_PATH)
            api_activities = api_collector.collect_all_outlook_activity(days=7)

            if api_activities:
                count = api_collector.save_to_database(api_activities)
                self.show_snack(f"Collected {count} Outlook activities (Outlook API)")
                return

            # API returned nothing (e.g. Outlook not running) - fall back to logs
            log_collector = OutlookLogCollector(paths.DB_PATH)
            log_activities = log_collector.collect_outlook_logs()

            if log_activities:
                with ActivityDatabase(paths.DB_PATH) as db:
                    count = db.add_activities(log_activities)
                self.show_snack(f"Collected {count} Outlook activities (logs)")
            else:
                self.show_snack("No Outlook activity found (is Outlook running?)")

        except Exception as ex:
            self.show_snack(f"Error collecting Outlook: {ex}")

    def collect_slack(self, e):
        """Collect Slack activity"""
        try:
            from weekly_report.collectors.slack import SlackCollector

            self.show_snack("Collecting Slack activity...")

            # Load Slack config
            config_file = paths.SLACK_CONFIG
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

            collector = SlackCollector(paths.DB_PATH, token=token)
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
            from weekly_report.collectors.confluence import ConfluenceCollector

            self.show_snack("Collecting Confluence activity...")

            config_file = paths.CONFLUENCE_CONFIG
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
                paths.DB_PATH, config_path=config_file
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
        """Generate weekly report — 백그라운드 스레드에서 실행하고 상태 줄로 진행을 보여준다
        (버튼 핸들러에서 바로 돌리면 1~2분 동안 눌렸는지 알 수 없음)."""
        if self._report_state()["status"] == "작성 중":
            self.show_snack("이미 주간보고를 작성 중입니다")
            return
        started = time.time()
        step = {"text": "준비 중"}
        self.set_report_status("작성 중", detail=step["text"],
                               requested_at=datetime.now().strftime("%H:%M:%S"))

        def elapsed():
            sec = int(time.time() - started)
            return f"{sec // 60}분 {sec % 60:02d}초" if sec >= 60 else f"{sec}초"

        def set_step(text):
            step["text"] = text
            self.set_report_status(detail=f"{text} · 경과 {elapsed()}", only_if="작성 중")

        async def ticker():  # 단계가 길어도 경과 시간이 흐르는 게 보이도록 (Flet 이벤트 루프에서 1초마다)
            while self._report_state()["status"] == "작성 중":
                self.set_report_status(detail=f"{step['text']} · 경과 {elapsed()}", only_if="작성 중")
                await asyncio.sleep(1)

        def worker():
            try:
                from weekly_report.collectors.integrated import COLLECT_REUSE_MINUTES, IntegratedCollector
                from weekly_report.report.generator import ReportGenerator

                # 상시 실행 중인 건 파일 감시·브라우저뿐이라, IDE·Claude Code·Outlook·
                # Teams 등은 보고서 직전에 수집해야 반영된다 (최근에 수집했으면 생략)
                collected = IntegratedCollector([]).collect_if_stale(
                    days=7, progress=lambda name: set_step(f"최신 데이터 수집 중: {name}")
                )
                if collected is None:
                    set_step(f"최근 {COLLECT_REUSE_MINUTES}분 내 수집한 데이터 사용")
                generator = ReportGenerator()
                generator.on_progress = set_step
                result = generator.generate_and_save_weekly_report()
                generated_paths = [path for path in result["file_paths"].values() if path]
                if not generated_paths:
                    raise RuntimeError("보고서 생성 결과 파일이 없습니다")
                print("Generated weekly report files:")
                for path in generated_paths:
                    print(f"- {path}")
                self.set_report_status(
                    "주간보고 생성완료",
                    detail=f"소요 {elapsed()} · {os.path.basename(generated_paths[0])}",
                    output_path=generated_paths[0],
                )
            except Exception as ex:
                print(f"Error generating weekly report: {ex}")
                self.set_report_status("생성 실패", detail=f"{ex} · 경과 {elapsed()}")

        # Flet 0.86은 화면 갱신이 페이지 컨텍스트에 묶여 있어서, 일반 threading.Thread에서
        # page.update()를 부르면 오류 없이 무시됨 → page.run_thread로 실행해야 상태 줄이 갱신됨
        self.page.run_task(ticker)
        self.page.run_thread(worker)

    def preview_draft(self, e):
        """Preview draft report"""
        try:
            from weekly_report.report.generator import ReportGenerator

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
