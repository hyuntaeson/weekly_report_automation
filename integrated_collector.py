#!/usr/bin/env python3
"""
Integrated Activity Collector
Combines file watching, IDE activity, Outlook activity, and browser activity collection
"""

import os
import threading
import time
from datetime import datetime
from file_watcher import FileWatcher, FileActivityHandler
from ide_collector import IDECollector, RecentFileCollector
from outlook_collector import OutlookCollector, OutlookLogCollector
from ai_tool_collector import AIToolCollector
from confluence_collector import ConfluenceCollector
from teams_collector import TeamsCollector
from database import ActivityDatabase
from browser_activity_server import BrowserActivityServer


class IntegratedCollector:
    """Integrated collector for all activity sources"""

    def __init__(
        self, watch_paths, exclude_patterns=None, db_path="data/activities.db", enable_browser_server=False
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

        # Browser activity server (optional)
        self.browser_server = None
        self.enable_browser_server = enable_browser_server

        # Collection intervals (in seconds)
        self.ide_collection_interval = 300  # 5 minutes
        self.outlook_collection_interval = 600  # 10 minutes
        self.ai_tool_collection_interval = 300  # 5 minutes
        self.confluence_collection_interval = 1800  # 30 minutes
        self.teams_collection_interval = 1800  # 30 minutes

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
        log_file = "logs/file_activity.log"
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
    config_file = "config/watch_config.json"
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
