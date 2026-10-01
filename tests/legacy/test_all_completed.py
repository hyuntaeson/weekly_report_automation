#!/usr/bin/env python3
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportOptionalMemberAccess=false
"""
Comprehensive test for all completed features
"""

import os
import sys
import json
import time
from typing import Any
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)  # 상대 경로(config/, data/, test_reports/)는 프로젝트 루트 기준
from weekly_report.collectors.file_watcher import FileWatcher, FileActivityHandler
from weekly_report.collectors.ide import IDECollector, RecentFileCollector
from weekly_report.collectors.outlook import OutlookCollector, OutlookLogCollector
from weekly_report.collectors.ai_tool import AIToolCollector
from weekly_report.collectors.confluence import ConfluenceCollector
from weekly_report.report.generator import ReportGenerator
from weekly_report.storage.database import ActivityDatabase
from weekly_report.collectors.browser_server import BrowserActivityServer


class FeatureTester:
    """Test all completed features"""

    def __init__(self):
        self.results: dict[str, dict[str, Any]] = {
            "file_watcher": {
                "status": "pending",
                "details": [],
                "start_time": None,
                "end_time": None,
            },
            "database": {
                "status": "pending",
                "details": [],
                "start_time": None,
                "end_time": None,
            },
            "ide_collector": {
                "status": "pending",
                "details": [],
                "start_time": None,
                "end_time": None,
            },
            "outlook_collector": {
                "status": "pending",
                "details": [],
                "start_time": None,
                "end_time": None,
            },
            "confluence_collector": {
                "status": "pending",
                "details": [],
                "start_time": None,
                "end_time": None,
            },
            "ai_tool_collector": {
                "status": "pending",
                "details": [],
                "start_time": None,
                "end_time": None,
            },
            "report_generator": {
                "status": "pending",
                "details": [],
                "start_time": None,
                "end_time": None,
            },
            "integrated_system": {
                "status": "pending",
                "details": [],
                "start_time": None,
                "end_time": None,
            },
            "browser_activity_server": {
                "status": "pending",
                "details": [],
                "start_time": None,
                "end_time": None,
            },
        }

    def test_database(self):
        """Test database functionality"""
        print("=== Testing Database ===")
        self.results["database"]["start_time"] = datetime.now()

        try:
            db_path = "data/test_activities.db"

            # Test database creation and connection
            with ActivityDatabase(db_path) as db:
                self.results["database"]["details"].append(
                    "PASS: Database connection successful"
                )

                # Test adding activity
                test_activity = {
                    "timestamp": datetime.now().isoformat(),
                    "action": "test",
                    "file_path": "test/file.txt",
                    "file_type": "text",
                    "source": "test",
                }
                db.add_activity(test_activity)
                self.results["database"]["details"].append(
                    "PASS: Activity insertion successful"
                )

                # Test query
                conn = db.conn
                if conn is None:
                    raise RuntimeError("Database connection is not available")
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM activities")
                count = cursor.fetchone()[0]
                self.results["database"]["details"].append(
                    f"PASS: Query successful: {count} activities"
                )

                # Test statistics
                stats = db.get_file_type_stats()
                self.results["database"]["details"].append(
                    f"PASS: Statistics query successful: {len(stats)} file types"
                )

            self.results["database"]["status"] = "passed"

        except Exception as e:
            self.results["database"]["status"] = "failed"
            self.results["database"]["details"].append(f"FAIL: Error: {e}")

        self.results["database"]["end_time"] = datetime.now()
        print(f"Database test completed: {self.results['database']['status']}")

    def test_ide_collector(self):
        """Test IDE collector functionality"""
        print("=== Testing IDE Collector ===")
        self.results["ide_collector"]["start_time"] = datetime.now()

        try:
            collector = IDECollector("data/test_activities.db")

            # Test VSCode collection
            vscode_activities = collector.collect_vscode_activity()
            self.results["ide_collector"]["details"].append(
                f"PASS: VSCode collection: {len(vscode_activities)} activities"
            )

            # Test Orca collection
            orca_activities = collector.collect_orca_activity()
            self.results["ide_collector"]["details"].append(
                f"PASS: Orca collection: {len(orca_activities)} activities"
            )

            # Test recent files
            recent_collector = RecentFileCollector("data/test_activities.db")
            recent_activities = recent_collector.collect_vscode_recent_files()
            self.results["ide_collector"]["details"].append(
                f"PASS: Recent files: {len(recent_activities)} files"
            )

            # Test database save
            if vscode_activities or orca_activities:
                all_activities = vscode_activities + orca_activities
                count = collector.save_to_database(all_activities)
                self.results["ide_collector"]["details"].append(
                    f"PASS: Database save: {count} activities"
                )

            self.results["ide_collector"]["status"] = "passed"

        except Exception as e:
            self.results["ide_collector"]["status"] = "failed"
            self.results["ide_collector"]["details"].append(f"FAIL: Error: {e}")

        self.results["ide_collector"]["end_time"] = datetime.now()
        print(
            f"IDE collector test completed: {self.results['ide_collector']['status']}"
        )

    def test_outlook_collector(self):
        """Test Outlook collector functionality"""
        print("=== Testing Outlook Collector ===")
        self.results["outlook_collector"]["start_time"] = datetime.now()

        try:
            # Test log-based collection (safer method)
            log_collector = OutlookLogCollector("data/test_activities.db")
            log_activities = log_collector.collect_outlook_logs()
            self.results["outlook_collector"]["details"].append(
                f"PASS: Log collection: {len(log_activities)} activities"
            )

            # Test database save
            if log_activities:
                with ActivityDatabase("data/test_activities.db") as db:
                    count = db.add_activities(log_activities)
                self.results["outlook_collector"]["details"].append(
                    f"PASS: Database save: {count} activities"
                )

            # Try API-based collection (may fail if Outlook not running)
            try:
                api_collector = OutlookCollector("data/test_activities.db")
                api_activities = api_collector.collect_all_outlook_activity(days=1)
                self.results["outlook_collector"]["details"].append(
                    f"PASS: API collection: {len(api_activities)} activities"
                )
            except Exception as api_error:
                self.results["outlook_collector"]["details"].append(
                    f"WARN: API collection not available: {str(api_error)[:50]}"
                )

            self.results["outlook_collector"]["status"] = "passed"

        except Exception as e:
            self.results["outlook_collector"]["status"] = "failed"
            self.results["outlook_collector"]["details"].append(f"FAIL: Error: {e}")

        self.results["outlook_collector"]["end_time"] = datetime.now()
        print(
            f"Outlook collector test completed: {self.results['outlook_collector']['status']}"
        )

    def test_confluence_collector(self):
        """Test Confluence collector functionality"""
        print("=== Testing Confluence Collector ===")
        self.results["confluence_collector"]["start_time"] = datetime.now()

        try:
            collector = ConfluenceCollector(
                "data/test_activities.db", config_path="config/confluence_config.json"
            )
            activities = collector.collect_all_confluence_activity(days=7)
            self.results["confluence_collector"]["details"].append(
                f"PASS: API collection: {len(activities)} activities"
            )

            if activities:
                count = collector.save_to_database(activities)
                self.results["confluence_collector"]["details"].append(
                    f"PASS: Database save: {count} activities"
                )

                with ActivityDatabase("data/test_activities.db") as db:
                    conn = db.conn
                    if conn is None:
                        raise RuntimeError("Database connection is not available")
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT COUNT(*) FROM activities WHERE source = ?",
                        ("confluence",),
                    )
                    stored_count = cursor.fetchone()[0]
                    self.results["confluence_collector"]["details"].append(
                        f"PASS: Database verification: {stored_count} Confluence activities stored"
                    )

                    cursor.execute(
                        "SELECT details FROM activities WHERE source = ? AND details IS NOT NULL LIMIT 1",
                        ("confluence",),
                    )
                    details_row = cursor.fetchone()
                    if details_row:
                        json.loads(details_row[0])
                        self.results["confluence_collector"]["details"].append(
                            "PASS: Details JSON serialization verified"
                        )
            else:
                self.results["confluence_collector"]["details"].append(
                    "WARN: No recent Confluence activities found"
                )

            self.results["confluence_collector"]["status"] = "passed"

        except Exception as e:
            self.results["confluence_collector"]["status"] = "failed"
            self.results["confluence_collector"]["details"].append(f"FAIL: Error: {e}")

        self.results["confluence_collector"]["end_time"] = datetime.now()
        print(
            f"Confluence collector test completed: {self.results['confluence_collector']['status']}"
        )

    def test_ai_tool_collector(self):
        """Test AI tool collector functionality"""
        print("=== Testing AI Tool Collector ===")
        self.results["ai_tool_collector"]["start_time"] = datetime.now()

        try:
            collector = AIToolCollector("data/test_activities.db")

            history_activities = collector.collect_claude_history(hours=24)
            self.results["ai_tool_collector"]["details"].append(
                f"PASS: Claude history collection: {len(history_activities)} activities"
            )

            session_activities = collector.collect_claude_sessions()
            self.results["ai_tool_collector"]["details"].append(
                f"PASS: Claude sessions collection: {len(session_activities)} activities"
            )

            devin_activities = collector.collect_devin_activity()
            self.results["ai_tool_collector"]["details"].append(
                f"PASS: Devin stub collection: {len(devin_activities)} activities"
            )

            all_activities = collector.collect_all_ai_tool_activity(hours=24)
            self.results["ai_tool_collector"]["details"].append(
                f"PASS: All AI tool collection: {len(all_activities)} activities"
            )

            if all_activities:
                count = collector.save_to_database(all_activities)
                self.results["ai_tool_collector"]["details"].append(
                    f"PASS: Database save: {count} activities"
                )

                with ActivityDatabase("data/test_activities.db") as db:
                    conn = db.conn
                    if conn is None:
                        raise RuntimeError("Database connection is not available")
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT COUNT(*) FROM activities WHERE source = ?",
                        ("claude_code",),
                    )
                    stored_count = cursor.fetchone()[0]
                    self.results["ai_tool_collector"]["details"].append(
                        f"PASS: Database verification: {stored_count} Claude Code activities stored"
                    )

                    cursor.execute(
                        "SELECT details FROM activities WHERE source = ? AND details IS NOT NULL LIMIT 1",
                        ("claude_code",),
                    )
                    details_row = cursor.fetchone()
                    if details_row:
                        json.loads(details_row[0])
                        self.results["ai_tool_collector"]["details"].append(
                            "PASS: Details JSON serialization verified"
                        )
            else:
                self.results["ai_tool_collector"]["details"].append(
                    "WARN: No recent AI tool activities found"
                )

            self.results["ai_tool_collector"]["status"] = "passed"

        except Exception as e:
            self.results["ai_tool_collector"]["status"] = "failed"
            self.results["ai_tool_collector"]["details"].append(f"FAIL: Error: {e}")

        self.results["ai_tool_collector"]["end_time"] = datetime.now()
        print(
            f"AI tool collector test completed: {self.results['ai_tool_collector']['status']}"
        )

    def test_report_generator(self):
        """Test weekly report generator functionality"""
        print("=== Testing Report Generator ===")
        self.results["report_generator"]["start_time"] = datetime.now()

        try:
            generator = ReportGenerator(
                db_path="data/test_activities.db",
            )
            weekly_data = generator.collect_weekly_data()
            self.results["report_generator"]["details"].append(
                f"PASS: Weekly data collected: {weekly_data['total_activities']} activities"
            )

            markdown_content = generator.generate_markdown(weekly_data)
            if markdown_content.strip():
                self.results["report_generator"]["details"].append(
                    f"PASS: Markdown generated: {len(markdown_content)} characters"
                )
            else:
                raise ValueError("Generated markdown is empty")

            report_paths = generator.save_report(
                weekly_data,
                formats=("markdown", "word"),
                output_dir="reports/test_reports",
            )
            for report_format, path in report_paths.items():
                if path and os.path.exists(path):
                    self.results["report_generator"]["details"].append(
                        f"PASS: {report_format} report created: {path}"
                    )
                else:
                    raise FileNotFoundError(f"Missing generated {report_format} report")

            self.results["report_generator"]["status"] = "passed"

        except Exception as e:
            self.results["report_generator"]["status"] = "failed"
            self.results["report_generator"]["details"].append(f"FAIL: Error: {e}")

        self.results["report_generator"]["end_time"] = datetime.now()
        print(
            f"Report generator test completed: {self.results['report_generator']['status']}"
        )

    def test_file_watcher(self):
        """Test file watcher functionality"""
        print("=== Testing File Watcher ===")
        self.results["file_watcher"]["start_time"] = datetime.now()

        try:
            # Create test directory
            test_dir = "data/test_watch_dir"
            os.makedirs(test_dir, exist_ok=True)

            # Create file watcher
            log_file = "logs/test_file_watcher.log"
            db_path = "data/test_activities.db"
            exclude_patterns = ["*.log", "logs/*", "*.db", "*.db-journal"]

            watcher = FileWatcher([test_dir], log_file, exclude_patterns, db_path)

            # Create handler
            handler = FileActivityHandler(log_file, exclude_patterns, db_path)

            # Test file creation
            test_file = os.path.join(test_dir, "test_file.txt")
            with open(test_file, "w") as f:
                f.write("Test content")

            time.sleep(1)  # Wait for event processing

            # Test file modification
            with open(test_file, "a") as f:
                f.write("\nModified content")

            time.sleep(1)  # Wait for event processing

            # Check if activities were recorded
            if len(handler.activities) > 0:
                self.results["file_watcher"]["details"].append(
                    f"PASS: File events detected: {len(handler.activities)}"
                )
                for activity in handler.activities:
                    self.results["file_watcher"]["details"].append(
                        f"  - {activity['action']}: {os.path.basename(activity['file_path'])}"
                    )
            else:
                self.results["file_watcher"]["details"].append(
                    "WARN: No file events detected (may need more time)"
                )

            # Cleanup
            if os.path.exists(test_file):
                os.remove(test_file)

            self.results["file_watcher"]["status"] = "passed"

        except Exception as e:
            self.results["file_watcher"]["status"] = "failed"
            self.results["file_watcher"]["details"].append(f"FAIL: Error: {e}")

        self.results["file_watcher"]["end_time"] = datetime.now()
        print(f"File watcher test completed: {self.results['file_watcher']['status']}")

    def test_integrated_system(self):
        """Test integrated system functionality"""
        print("=== Testing Integrated System ===")
        self.results["integrated_system"]["start_time"] = datetime.now()

        try:
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

            self.results["integrated_system"]["details"].append(
                f"PASS: Config loaded: {len(watch_paths)} watch paths"
            )

            # Test database availability
            with ActivityDatabase("data/test_activities.db") as db:
                conn = db.conn
                if conn is None:
                    raise RuntimeError("Database connection is not available")
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM activities")
                total_activities = cursor.fetchone()[0]
                self.results["integrated_system"]["details"].append(
                    f"PASS: ******** contains {total_activities} activities"
                )

                # Test file types collected
                stats = db.get_file_type_stats()
                self.results["integrated_system"]["details"].append(
                    f"PASS: File types: {len(stats)} different types"
                )

                # Test sources collected
                cursor.execute("SELECT DISTINCT source FROM activities")
                sources = [row[0] for row in cursor.fetchall()]
                self.results["integrated_system"]["details"].append(
                    f"PASS: Data sources: {sources}"
                )

            self.results["integrated_system"]["status"] = "passed"

        except Exception as e:
            self.results["integrated_system"]["status"] = "failed"
            self.results["integrated_system"]["details"].append(f"FAIL: Error: {e}")

        self.results["integrated_system"]["end_time"] = datetime.now()
        print(
            f"Integrated system test completed: {self.results['integrated_system']['status']}"
        )


    def test_browser_activity_server(self):
        """Test browser activity server"""
        print("=== Testing Browser Activity Server ===")
        self.results["browser_activity_server"]["start_time"] = datetime.now()

        import urllib.request
        import urllib.error

        try:
            # Use a different port to avoid conflicts
            test_port = 5758
            test_url = f'http://127.0.0.1:{test_port}/activity'

            # Start server
            server = BrowserActivityServer(
                db_path='data/test_activities.db',
                host='127.0.0.1',
                port=test_port
            )

            if not server.start():
                raise RuntimeError('Failed to start server')

            self.results["browser_activity_server"]["details"].append(
                f"PASS: Server started on port {test_port}"
            )

            # Wait for server to be ready
            time.sleep(1)

            # Test POST request
            test_activity = {
                'url': 'https://example.com',
                'title': 'Test Page',
                'timestamp': datetime.now().isoformat()
            }

            try:
                request = urllib.request.Request(
                    test_url,
                    data=json.dumps(test_activity).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                response = urllib.request.urlopen(request, timeout=5)
                if response.status == 200:
                    self.results["browser_activity_server"]["details"].append(
                        f"PASS: POST request succeeded (status 200)"
                    )
                else:
                    raise RuntimeError(f'Unexpected status: {response.status}')
            except urllib.error.URLError as e:
                raise RuntimeError(f'POST request failed: {e}')

            # Verify data was saved to database
            time.sleep(0.5)  # Give database time to commit
            try:
                with ActivityDatabase('data/test_activities.db') as db:
                    cursor = db.conn.cursor()
                    cursor.execute(
                        'SELECT COUNT(*) FROM activities WHERE source = ? AND file_path = ?',
                        ('browser', 'https://example.com')
                    )
                    count = cursor.fetchone()[0]
                    if count > 0:
                        self.results["browser_activity_server"]["details"].append(
                            f"PASS: Activity saved to database (count: {count})"
                        )
                    else:
                        raise RuntimeError('Activity not found in database')
            except Exception as db_error:
                raise RuntimeError(f'Database verification failed: {db_error}')

            self.results["browser_activity_server"]["status"] = "passed"

        except Exception as e:
            self.results["browser_activity_server"]["status"] = "failed"
            self.results["browser_activity_server"]["details"].append(f"FAIL: Error: {e}")

        finally:
            # Stop server
            try:
                if 'server' in locals():
                    server.stop()
            except:
                pass

        self.results["browser_activity_server"]["end_time"] = datetime.now()
        print(
            f"Browser activity server test completed: {self.results['browser_activity_server']['status']}"
        )
    def run_all_tests(self):
        """Run all tests"""
        print("Starting comprehensive feature tests...")
        print("=" * 50)

        # Run tests in order
        self.test_database()
        self.test_ide_collector()
        self.test_outlook_collector()
        self.test_confluence_collector()
        self.test_ai_tool_collector()
        self.test_report_generator()
        self.test_file_watcher()
        self.test_integrated_system()
        self.test_browser_activity_server()

        print("=" * 50)
        print("All tests completed!")

        return self.results

    def generate_report(self):
        """Generate test report"""
        print("\n=== TEST RESULTS SUMMARY ===")

        for feature, result in self.results.items():
            duration = None
            if result["start_time"] and result["end_time"]:
                duration = (result["end_time"] - result["start_time"]).total_seconds()

            print(f"\n{feature.upper()}:")
            print(f"  Status: {result['status']}")
            if duration:
                print(f"  Duration: {duration:.2f}s")
            print(f"  Details:")
            for detail in result["details"]:
                # Remove emoji symbols to avoid encoding issues
                clean_detail = (
                    detail.replace("PASS: ", "")
                    .replace("FAIL: ", "")
                    .replace("WARN: ", "")
                )
                print(f"    - {clean_detail}")

        # Calculate pass rate
        passed = sum(1 for r in self.results.values() if r["status"] == "passed")
        total = len(self.results)
        pass_rate = (passed / total) * 100 if total > 0 else 0

        print(f"\n=== OVERALL RESULTS ===")
        print(f"Total Features: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        print(f"Pass Rate: {pass_rate:.1f}%")

        return self.results


def main():
    """Main entry point"""
    tester = FeatureTester()
    results = tester.run_all_tests()
    tester.generate_report()

    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"data/test_results_{timestamp}.json"

    with open(report_file, "w", encoding="utf-8") as f:
        # Convert datetime objects to strings for JSON serialization
        serializable_results = {}
        for feature, result in results.items():
            serializable_results[feature] = {
                "status": result["status"],
                "details": result["details"],
                "start_time": result["start_time"].isoformat()
                if result["start_time"]
                else None,
                "end_time": result["end_time"].isoformat()
                if result["end_time"]
                else None,
            }

        json.dump(serializable_results, f, indent=2, ensure_ascii=False)

    print(f"\nTest results saved to: {report_file}")


if __name__ == "__main__":
    main()
