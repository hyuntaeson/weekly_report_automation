#!/usr/bin/env python3
"""
AI Tool Activity Collector
Collects Claude Code session activity and metadata
"""

import glob
import json
import os
from datetime import datetime, timedelta

from database import ActivityDatabase


class AIToolCollector:
    """Collector for AI tool activities"""

    def __init__(self, db_path="data/activities.db"):
        self.db_path = db_path

    def collect_all_ai_tool_activity(self, hours=24):
        """Collect activity from all supported AI tools within the last N hours"""
        all_activities = []

        history_activities = self.collect_claude_history(hours=hours)
        all_activities.extend(history_activities)

        session_activities = self.collect_claude_sessions()
        recent_session_activities = [
            activity
            for activity in session_activities
            if self._is_within_hours(activity.get("timestamp"), hours)
        ]
        all_activities.extend(recent_session_activities)

        devin_activities = self.collect_devin_activity()
        all_activities.extend(devin_activities)

        return all_activities

    def collect_claude_history(self, hours=24):
        """Collect Claude Code interaction history from JSONL log"""
        history_path = os.path.expanduser("~/.claude/history.jsonl")
        activities = []

        if not os.path.exists(history_path):
            print(f"Warning: Claude history file not found: {history_path}")
            return activities

        cutoff = datetime.now() - timedelta(hours=hours)

        try:
            with open(history_path, "r", encoding="utf-8") as history_file:
                for line_number, line in enumerate(history_file, start=1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                        timestamp_ms = entry.get("timestamp")

                        if timestamp_ms is None:
                            print(
                                f"Warning: Missing timestamp in Claude history line {line_number}"
                            )
                            continue

                        entry_datetime = self._parse_datetime(timestamp_ms)
                        if entry_datetime is None:
                            print(
                                f"Warning: Invalid timestamp in Claude history line {line_number}: {timestamp_ms}"
                            )
                            continue

                        if entry_datetime < cutoff:
                            continue

                        activities.append(
                            {
                                "timestamp": datetime.fromtimestamp(
                                    self._timestamp_to_seconds(timestamp_ms)
                                ).isoformat(),
                                "action": "claude_interaction",
                                "file_path": entry.get("project", "unknown"),
                                "file_type": "claude_session",
                                "source": "claude_code",
                                "details": {
                                    "sessionId": entry.get("sessionId"),
                                    "display": entry.get("display", "")[:200],
                                    "project": entry.get("project", "unknown"),
                                },
                            }
                        )
                    except json.JSONDecodeError as error:
                        print(
                            f"Warning: Failed to parse Claude history line {line_number}: {error}"
                        )
                    except Exception as error:
                        print(
                            f"Warning: Failed to process Claude history line {line_number}: {error}"
                        )
        except Exception as error:
            print(f"Error collecting Claude history: {error}")

        return activities

    def collect_claude_sessions(self):
        """Collect Claude Code session metadata from local session files"""
        sessions_dir = os.path.expanduser("~/.claude/sessions")
        activities = []

        if not os.path.exists(sessions_dir):
            print(f"Warning: Claude sessions directory not found: {sessions_dir}")
            return activities

        session_files = glob.glob(os.path.join(sessions_dir, "*.json"))

        for session_file in session_files:
            try:
                with open(session_file, "r", encoding="utf-8") as file:
                    session = json.load(file)

                started_at = session.get("startedAt")
                timestamp = (
                    str(started_at)
                    if started_at is not None
                    else datetime.now().isoformat()
                )

                activities.append(
                    {
                        "timestamp": timestamp,
                        "action": "session_start",
                        "file_path": session.get("cwd", "unknown"),
                        "file_type": "claude_session_meta",
                        "source": "claude_code",
                        "details": {
                            "sessionId": session.get("sessionId"),
                            "pid": session.get("pid"),
                            "status": session.get("status"),
                            "version": session.get("version"),
                        },
                    }
                )
            except json.JSONDecodeError as error:
                print(
                    f"Warning: Failed to parse Claude session file {session_file}: {error}"
                )
            except Exception as error:
                print(
                    f"Warning: Failed to process Claude session file {session_file}: {error}"
                )

        return activities

    def collect_devin_activity(self):
        """Devin은 클라우드 기반 서비스로 로컬 로그 접근 불가, 추후 API 연동 필요"""
        return []

    def save_to_database(self, activities):
        """Save collected AI tool activities to database"""
        prepared_activities = []

        for activity in activities:
            activity_copy = activity.copy()
            if isinstance(activity_copy.get("details"), dict):
                activity_copy["details"] = json.dumps(
                    activity_copy["details"], ensure_ascii=False
                )
            prepared_activities.append(activity_copy)

        with ActivityDatabase(self.db_path) as db:
            conn = db.conn
            if conn is None:
                raise RuntimeError("Database connection is not available")
            db.add_activities(prepared_activities)

        return len(prepared_activities)

    def _is_within_hours(self, timestamp_value, hours):
        """Check whether a timestamp is within the provided hour range"""
        parsed_datetime = self._parse_datetime(timestamp_value)
        if parsed_datetime is None:
            print(
                f"Warning: Unable to evaluate timestamp range for value: {timestamp_value}"
            )
            return False

        cutoff = datetime.now() - timedelta(hours=hours)
        return parsed_datetime >= cutoff

    def _parse_datetime(self, timestamp_value):
        """Parse timestamp values from milliseconds, seconds, or ISO strings"""
        if timestamp_value is None:
            return None

        try:
            if isinstance(timestamp_value, (int, float)):
                return datetime.fromtimestamp(
                    self._timestamp_to_seconds(timestamp_value)
                )

            if isinstance(timestamp_value, str):
                stripped_value = timestamp_value.strip()
                if not stripped_value:
                    return None

                if stripped_value.isdigit():
                    return datetime.fromtimestamp(
                        self._timestamp_to_seconds(int(stripped_value))
                    )

                normalized_value = stripped_value.replace("Z", "+00:00")
                return (
                    datetime.fromisoformat(normalized_value).replace(tzinfo=None)
                    if "T" in normalized_value
                    else datetime.fromisoformat(normalized_value)
                )
        except Exception as error:
            print(f"Warning: Failed to parse timestamp {timestamp_value}: {error}")

        return None

    def _timestamp_to_seconds(self, timestamp_value):
        """Convert Unix seconds or milliseconds to seconds"""
        numeric_timestamp = float(timestamp_value)
        return (
            numeric_timestamp / 1000
            if numeric_timestamp > 1000000000000
            else numeric_timestamp
        )


def main():
    """Test AI tool collector"""
    collector = AIToolCollector()

    print("Collecting Claude history...")
    history_activities = collector.collect_claude_history(hours=24)
    print(f"Found {len(history_activities)} Claude history activities")

    print("Collecting Claude sessions...")
    session_activities = collector.collect_claude_sessions()
    print(f"Found {len(session_activities)} Claude session activities")

    all_activities = collector.collect_all_ai_tool_activity(hours=24)
    print(f"Total AI tool activities: {len(all_activities)}")

    if all_activities:
        print("\nSample activities:")
        for activity in all_activities[:5]:
            print(
                f"  {activity['timestamp']} | {activity['action']} | {activity['file_path']}"
            )

        saved_count = collector.save_to_database(all_activities)
        print(f"\nSaved {saved_count} AI tool activities to database")

        with ActivityDatabase(collector.db_path) as db:
            conn = db.conn
            if conn is None:
                raise RuntimeError("Database connection is not available")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM activities WHERE source = ?", ("claude_code",)
            )
            stored_count = cursor.fetchone()[0]
            print(
                f"Database verification: {stored_count} Claude Code activities stored"
            )
    else:
        print("No AI tool activities found to save")


if __name__ == "__main__":
    main()
