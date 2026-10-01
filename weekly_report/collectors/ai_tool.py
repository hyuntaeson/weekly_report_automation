#!/usr/bin/env python3
"""
AI Tool Activity Collector
Collects Claude Code session activity and metadata
"""

import glob
import hashlib
import json
import os
import re
from datetime import datetime, timedelta

from weekly_report import paths
from weekly_report.storage.database import ActivityDatabase


def hash_text(parts):
    """요청 묶음이 바뀌었는지 판단하는 캐시 키 (내용 기반, 실행마다 동일)."""
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:16]


class AIToolCollector:
    """Collector for AI tool activities"""

    def __init__(self, db_path=paths.DB_PATH):
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

        all_activities.extend(self.collect_work_summaries(hours=hours))

        return all_activities

    WORK_SUMMARY_VERSION = 8  # 프롬프트를 바꾸면 올린다 → 캐시된 요약 재생성

    def collect_work_summaries(self, hours=24 * 7):
        """Claude Code 요청 기록을 프로젝트·날짜별로 묶어 '무슨 작업을 했는지' LLM 요약.
        같은 요청 묶음(prompts_key)이면 DB에 저장된 요약을 재사용한다."""
        history_path = os.path.expanduser("~/.claude/history.jsonl")
        if not os.path.exists(history_path):
            return []
        cutoff = datetime.now() - timedelta(hours=hours)
        groups = {}
        with open(history_path, "r", encoding="utf-8") as history_file:
            for line in history_file:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                at = self._parse_datetime(entry.get("timestamp"))
                prompt = re.sub(r"\[Pasted text #\d+[^\]]*\]", "", entry.get("display") or "").strip()
                if at is None or at < cutoff or not prompt or prompt.startswith("/"):
                    continue
                key = (entry.get("project") or "unknown", at.date())
                groups.setdefault(key, []).append(prompt[:500])

        try:
            with ActivityDatabase(self.db_path) as db:
                cache = db.get_details_cache("claude_code", "prompts_key")
        except Exception:
            cache = {}

        activities = []
        for (project, day), prompts in sorted(groups.items(), key=lambda kv: kv[0][1]):
            timestamp = f"{day.isoformat()}T23:59:59"
            prompts_key = f"{self.WORK_SUMMARY_VERSION}:{len(prompts)}:{hash_text(prompts)}"
            cached = cache.get((timestamp, project))
            if cached and cached.get("prompts_key") == prompts_key:
                details = cached
            else:
                summary = self._summarize_prompts(prompts)
                details = {"prompt_count": len(prompts), "summary": summary}
                if summary:  # 요약 실패 시 캐시 키를 남기지 않아 다음 수집 때 재시도
                    details["prompts_key"] = prompts_key
            activities.append({
                "timestamp": timestamp,
                "action": "work_summary",
                "file_path": project,
                "file_type": "claude_session",
                "source": "claude_code",
                "details": details,
            })
        return activities

    @staticmethod
    def _summarize_prompts(prompts):
        # 요청 원문이 "~해줘" 같은 지시문이라, 태그로 감싸 요약 대상 '데이터'임을 분명히 한다
        # (안 그러면 모델이 그 지시에 직접 답하려 든다)
        text = "<requests>\n" + "\n".join(f"- {p}" for p in prompts) + "\n</requests>"
        try:
            from weekly_report.ai.llm_summarizer import PROMPT_TEMPLATES, LLMSummarizer
            summary = LLMSummarizer().complete(
                PROMPT_TEMPLATES["work"], text, max_tokens=1000, max_input=8000, temperature=0
            ) or ""
        except Exception:
            return ""
        # 그래도 "이해했습니다. 정리하면:" 같은 서두나 "~ 제공해주시면 작업하겠습니다" 같은
        # 꼬리 문장이 붙으면 번호 목록 부분만 남긴다
        first = re.search(r"(?m)^\s*1[.)]\s", summary)
        if not first:
            # 번호 목록이 없으면 거절·되묻기 응답 → 실패 처리 (캐시 안 되고 다음 수집 때 재시도)
            return ""
        if re.search(r"제공해\s*주|알려\s*주시|확인할 수 없|필요한 정보|요약하지 않", summary):
            return ""  # 목록 형태의 되묻기 응답도 실패 처리
        kept = []
        for line in summary[first.start():].splitlines():
            if line.strip() and not re.match(r"\s*(\d+[.)]|[-*•])\s|\s{2,}\S", line):
                break  # 목록이 끝난 뒤의 일반 문단
            kept.append(line)
        return "\n".join(kept).strip()

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
