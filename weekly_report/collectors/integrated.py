#!/usr/bin/env python3
"""
Integrated Activity Collector
Combines file watching, IDE activity, Outlook activity, and browser activity collection
"""

import os
import threading
import time
from datetime import datetime
from weekly_report import paths
from weekly_report.collectors.file_watcher import FileWatcher, FileActivityHandler
from weekly_report.collectors.ide import IDECollector, RecentFileCollector
from weekly_report.collectors.outlook import OutlookCollector, OutlookLogCollector
from weekly_report.collectors.ai_tool import AIToolCollector
from weekly_report.collectors.confluence import ConfluenceCollector
from weekly_report.collectors.teams import TeamsCollector
from weekly_report.collectors.onenote import OneNoteCollector
from weekly_report.collectors.sharepoint import SharePointCollector
from weekly_report.storage.database import ActivityDatabase
from weekly_report.collectors.browser_server import BrowserActivityServer


class IntegratedCollector:
    """Integrated collector for all activity sources"""

    def __init__(
        self, watch_paths, exclude_patterns=None, db_path=paths.DB_PATH, enable_browser_server=False
    ):
        self.watch_paths = watch_paths
        self.exclude_patterns = exclude_patterns or []
        self.db_path = db_path

        # Individual collectors
        self.file_watcher = None
        self.ide_collector = IDECollector(db_path)
        self.outlook_collector = OutlookCollector(db_path)
        self.outlook_log_collector = OutlookLogCollector(db_path)
        self.ai_tool_collector = AIToolCollector(db_path)
        self.confluence_collector = ConfluenceCollector(db_path)
        self.teams_collector = TeamsCollector(db_path)
        self.onenote_collector = OneNoteCollector(db_path)
        self.sharepoint_collector = SharePointCollector(db_path)

        # Browser activity server (optional)
        self.browser_server = None
        self.enable_browser_server = enable_browser_server

        # Collection intervals (in seconds)
        self.ide_collection_interval = 300  # 5 minutes
        self.outlook_collection_interval = 600  # 10 minutes
        self.ai_tool_collection_interval = 300  # 5 minutes
        self.confluence_collection_interval = 1800  # 30 minutes
        self.teams_collection_interval = 1800  # 30 minutes
        self.onenote_collection_interval = 1800  # 30 minutes
        self.sharepoint_collection_interval = 1800  # 30 minutes

        # Control flags
        self.is_running = False
        self.collection_threads = []

    def start(self):
        """Start all collectors"""
        if self.is_running:
            return

        self.is_running = True

        # Start file watcher
        self.start_file_watcher()

        # Start IDE collector thread
        ide_thread = threading.Thread(target=self.ide_collection_loop, daemon=True)
        ide_thread.start()
        self.collection_threads.append(ide_thread)

        # Start Outlook collector thread
        outlook_thread = threading.Thread(
            target=self.outlook_collection_loop, daemon=True
        )
        outlook_thread.start()
        self.collection_threads.append(outlook_thread)

        # Start Confluence collector thread
        confluence_thread = threading.Thread(
            target=self.confluence_collection_loop, daemon=True
        )
        confluence_thread.start()
        self.collection_threads.append(confluence_thread)

        # Start AI tool collector thread
        ai_tool_thread = threading.Thread(
            target=self.ai_tool_collection_loop, daemon=True
        )
        ai_tool_thread.start()
        self.collection_threads.append(ai_tool_thread)

        # Start Teams collector thread (config 없으면 스텁이라 바로 빈 리스트 반환)
        teams_thread = threading.Thread(
            target=self.teams_collection_loop, daemon=True
        )
        teams_thread.start()
        self.collection_threads.append(teams_thread)

        # Start OneNote collector thread (Teams 토큰 재사용, 토큰 없으면 스텁)
        onenote_thread = threading.Thread(
            target=self.onenote_collection_loop, daemon=True
        )
        onenote_thread.start()
        self.collection_threads.append(onenote_thread)

        # Start SharePoint collector thread (동일 Graph 토큰 재사용)
        sharepoint_thread = threading.Thread(
            target=self.sharepoint_collection_loop, daemon=True
        )
        sharepoint_thread.start()
        self.collection_threads.append(sharepoint_thread)

        # Start browser activity server if enabled
        if self.enable_browser_server:
            self.start_browser_server()

        print("Integrated collector started")


    def start_browser_server(self):
        """Start browser activity server"""
        try:
            self.browser_server = BrowserActivityServer(self.db_path)
            if self.browser_server.start():
                print("Browser activity server started")
            else:
                print("Failed to start browser activity server")
                self.browser_server = None
        except Exception as e:
            print(f"Error starting browser activity server: {e}")
            self.browser_server = None
    def start_file_watcher(self):
        """Start file system watcher"""
        log_file = paths.FILE_ACTIVITY_LOG
        self.file_watcher = FileWatcher(
            self.watch_paths, log_file, self.exclude_patterns, self.db_path
        )

        # Start in separate thread
        watcher_thread = threading.Thread(target=self.file_watcher.start, daemon=True)
        watcher_thread.start()
        self.collection_threads.append(watcher_thread)

    def ide_collection_loop(self):
        """Continuous IDE activity collection loop"""
        while self.is_running:
            try:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Collecting IDE activity..."
                )

                # Collect IDE activity
                ide_activities = self.ide_collector.collect_all_ide_activity()
                if ide_activities:
                    count = self.ide_collector.save_to_database(ide_activities)
                    print(f"Saved {count} IDE activities to database")

                # Collect recent files
                recent_collector = RecentFileCollector(self.db_path)
                recent_activities = recent_collector.collect_vscode_recent_files()
                if recent_activities:
                    with ActivityDatabase(self.db_path) as db:
                        count = db.add_activities(recent_activities)
                    print(f"Saved {count} recent file activities to database")

            except Exception as e:
                print(f"Error in IDE collection: {e}")

            # Wait for next collection
            time.sleep(self.ide_collection_interval)

    def outlook_collection_loop(self):
        """Continuous Outlook activity collection loop"""
        while self.is_running:
            try:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Collecting Outlook activity..."
                )

                # Try API-based collection first
                try:
                    outlook_activities = (
                        self.outlook_collector.collect_all_outlook_activity(days=1)
                    )
                    if outlook_activities:
                        count = self.outlook_collector.save_to_database(
                            outlook_activities
                        )
                        print(f"Saved {count} Outlook API activities to database")
                except Exception as api_error:
                    print(f"Outlook API collection failed: {api_error}")
                    print("Falling back to log-based collection...")

                    # Fallback to log-based collection
                    log_activities = self.outlook_log_collector.collect_outlook_logs()
                    if log_activities:
                        with ActivityDatabase(self.db_path) as db:
                            count = db.add_activities(log_activities)
                        print(f"Saved {count} Outlook log activities to database")

            except Exception as e:
                print(f"Error in Outlook collection: {e}")

            # Wait for next collection
            time.sleep(self.outlook_collection_interval)

    def confluence_collection_loop(self):
        """Continuous Confluence activity collection loop"""
        while self.is_running:
            try:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Collecting Confluence activity..."
                )

                confluence_activities = (
                    self.confluence_collector.collect_all_confluence_activity(days=1)
                )
                if confluence_activities:
                    count = self.confluence_collector.save_to_database(
                        confluence_activities
                    )
                    print(f"Saved {count} Confluence activities to database")

            except Exception as e:
                print(f"Error in Confluence collection: {e}")

            # Wait for next collection
            time.sleep(self.confluence_collection_interval)

    def ai_tool_collection_loop(self):
        """Continuous AI tool activity collection loop"""
        while self.is_running:
            try:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Collecting AI tool activity..."
                )

                ai_tool_activities = (
                    self.ai_tool_collector.collect_all_ai_tool_activity(hours=24)
                )
                if ai_tool_activities:
                    count = self.ai_tool_collector.save_to_database(ai_tool_activities)
                    print(f"Saved {count} AI tool activities to database")

            except Exception as e:
                print(f"Error in AI tool collection: {e}")

            # Wait for next collection
            time.sleep(self.ai_tool_collection_interval)

    def teams_collection_loop(self):
        """Continuous Teams activity collection loop"""
        while self.is_running:
            try:
                teams_activities = (
                    self.teams_collector.collect_all_teams_activity(days=1)
                )
                if teams_activities:
                    count = self.teams_collector.save_to_database(
                        teams_activities
                    )
                    print(f"Saved {count} Teams activities to database")

            except Exception as e:
                print(f"Error in Teams collection: {e}")

            # Wait for next collection
            time.sleep(self.teams_collection_interval)

    def onenote_collection_loop(self):
        """Continuous OneNote activity collection loop"""
        while self.is_running:
            try:
                onenote_activities = (
                    self.onenote_collector.collect_activity(days=1)
                )
                if onenote_activities:
                    count = self.onenote_collector.save_to_database(
                        onenote_activities
                    )
                    print(f"Saved {count} OneNote activities to database")

            except Exception as e:
                print(f"Error in OneNote collection: {e}")

            # Wait for next collection
            time.sleep(self.onenote_collection_interval)

    def sharepoint_collection_loop(self):
        """Continuous SharePoint/OneDrive file activity collection loop"""
        while self.is_running:
            try:
                sp_activities = self.sharepoint_collector.collect_activity(days=1)
                if sp_activities:
                    count = self.sharepoint_collector.save_to_database(
                        sp_activities
                    )
                    print(f"Saved {count} SharePoint activities to database")

            except Exception as e:
                print(f"Error in SharePoint collection: {e}")

            # Wait for next collection
            time.sleep(self.sharepoint_collection_interval)

    def collect_once(self, days=7, progress=None):
        """가져와야 하는(pull) 소스를 한 번씩 수집해 저장 → {소스: 저장 건수 | 오류}.

        GUI는 파일 감시·브라우저 서버만 상시 실행하므로, 보고서 생성 직전에
        이걸 호출해야 IDE·Claude Code·Outlook·Teams 등이 보고서에 반영된다.
        한 소스가 실패해도 나머지는 계속 수집한다."""
        if os.name == "nt":
            try:
                import pythoncom  # Outlook/Office COM은 스레드마다 초기화 필요
                pythoncom.CoInitialize()
            except Exception:
                pass

        steps = [
            ("Claude Code", lambda: self.ai_tool_collector.save_to_database(
                self.ai_tool_collector.collect_all_ai_tool_activity(hours=24 * days))),
            ("IDE", lambda: self.ide_collector.save_to_database(
                self.ide_collector.collect_all_ide_activity(days=days))),
            ("Outlook", lambda: self.outlook_collector.save_to_database(
                self.outlook_collector.collect_all_outlook_activity(days=days))),
            ("Confluence", lambda: self.confluence_collector.save_to_database(
                self.confluence_collector.collect_all_confluence_activity(days=days))),
            ("Teams", lambda: self.teams_collector.save_to_database(
                self.teams_collector.collect_all_teams_activity(days=days))),
            ("OneNote", lambda: self.onenote_collector.save_to_database(
                self.onenote_collector.collect_activity(days=days))),
            ("SharePoint", lambda: self.sharepoint_collector.save_to_database(
                self.sharepoint_collector.collect_activity(days=days))),
        ]
        results = {}
        for name, run in steps:
            if progress:
                progress(name)
            try:
                results[name] = run() or 0
            except Exception as e:
                results[name] = f"오류: {e}"
                print(f"Warning: {name} collection failed: {e}")
        return results

    def stop(self):
        """Stop all collectors"""
        if not self.is_running:
            return

        self.is_running = False

        # Stop file watcher
        if self.file_watcher:
            self.file_watcher.stop()

        # Stop browser activity server
        if self.browser_server:
            self.browser_server.stop()

        # Wait for threads to finish
        for thread in self.collection_threads:
            thread.join(timeout=5)

        print("Integrated collector stopped")

    def get_statistics(self):
        """Get collection statistics"""
        with ActivityDatabase(self.db_path) as db:
            if db.conn is None:
                return {"total": 0, "by_source": {}, "by_action": {}}

            # Total activities
            cursor = db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM activities")
            total = cursor.fetchone()[0]

            # Activities by source
            cursor.execute("SELECT source, COUNT(*) FROM activities GROUP BY source")
            by_source = dict(cursor.fetchall())

            # Activities by action
            cursor.execute("SELECT action, COUNT(*) FROM activities GROUP BY action")
            by_action = dict(cursor.fetchall())

            return {"total": total, "by_source": by_source, "by_action": by_action}


def main():
    """Test integrated collector"""
    import json

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
        print("No watch paths configured. Using default...")
        watch_paths = [os.path.expanduser("~/Documents")]

    # Create integrated collector (브라우저 서버도 함께 실행 - Chrome 확장이
    # 여기로 방문 기록을 전송함. 확장 프로그램은 chrome://extensions에서
    # 별도로 로드해야 함 - README_BROWSER_EXTENSION.md 참고)
    collector = IntegratedCollector(watch_paths, exclude_patterns, enable_browser_server=True)

    try:
        print("Starting integrated collector (press Ctrl+C to stop)...")
        collector.start()

        # 실사용 모드: Ctrl+C로 멈출 때까지 계속 실행 (30초 후 자동 종료 X)
        while True:
            time.sleep(600)  # 10분마다 진행 상황 로그만 출력
            stats = collector.get_statistics()
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] === Collection Statistics ===")
            print(f"Total activities: {stats['total']}")
            print(f"By source: {stats['by_source']}")
            print(f"By action: {stats['by_action']}")

    except KeyboardInterrupt:
        print("\nStopping collector...")
    finally:
        collector.stop()


if __name__ == "__main__":
    import os

    main()
