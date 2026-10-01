#!/usr/bin/env python3
"""
IDE Activity Collector

- VSCode: Local History(User/History/*/entries.json)는 파일을 저장할 때마다
  스냅샷을 남긴다. 날짜별로 그날 마지막 스냅샷과 그 전 스냅샷을 비교해
  "무엇을 수정했는지" LLM으로 요약한다 (같은 스냅샷 쌍은 DB 캐시 재사용).
- Orca: orca-stats.json의 agent_start/agent_stop 이벤트로 프로젝트별·날짜별
  에이전트 작업 횟수와 시간을 집계한다. 무엇을 했는지는 Orca가 띄우는
  Claude Code의 요청 기록(ai_tool_collector 작업 요약)에서 나온다.
"""

import os
import re
import json
import glob
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

from weekly_report import paths
from weekly_report.storage.database import ActivityDatabase

MAX_SNAPSHOT_BYTES = 1_000_000
MAX_DIFF_LINES = 60
# 변경 요약 방식을 바꾸면 올린다 → 캐시된 이전 요약은 다시 생성
SUMMARY_VERSION = 3
# 이 프로그램이 만든 보고서를 VSCode로 열어본 것은 사용자 작업이 아니므로 제외
_OWN_REPORTS_DIR = paths.REPORTS_DIR.lower() + "\\"
_SKIP_PATH_PARTS = (
    "\\.git\\", "\\node_modules\\", "\\appdata\\roaming\\code\\user\\", _OWN_REPORTS_DIR,
)


class IDECollector:
    """Collector for IDE activities"""

    def __init__(self, db_path=paths.DB_PATH):
        self.db_path = db_path
        self.collected_activities = []

    # ---------------- VSCode ----------------

    def collect_vscode_activity(self, days=7):
        """VSCode Local History로 파일별·날짜별 수정 내용을 요약해 수집."""
        since = datetime.now() - timedelta(days=days)
        workspaces = self._vscode_workspaces()
        cache = self._load_cache("vscode", "snapshot_pair")
        activities = []
        for vscode_path in self._find_vscode_paths():
            for entries_file in glob.glob(os.path.join(vscode_path, "User", "History", "*", "entries.json")):
                try:
                    activities.extend(
                        self._vscode_file_activities(entries_file, since, workspaces, cache)
                    )
                except Exception as e:
                    print(f"Error reading VSCode history {entries_file}: {e}")
        return activities

    def _vscode_file_activities(self, entries_file, since, workspaces, cache):
        with open(entries_file, encoding="utf-8") as f:
            data = json.load(f)
        file_path = self._uri_to_path(data.get("resource", ""))
        if not file_path or any(p in file_path.lower() for p in _SKIP_PATH_PARTS):
            return []
        history_dir = os.path.dirname(entries_file)
        entries = sorted(
            (e for e in data.get("entries", []) if e.get("timestamp") and e.get("id")),
            key=lambda e: e["timestamp"],
        )
        for e in entries:
            e["_at"] = datetime.fromtimestamp(e["timestamp"] / 1000)

        by_day = defaultdict(list)
        for e in entries:
            if e["_at"] >= since:
                by_day[e["_at"].date()].append(e)

        workspace = self._workspace_for(file_path, workspaces)
        name = os.path.basename(file_path)
        activities = []
        for day, day_entries in sorted(by_day.items()):
            head = day_entries[-1]
            earlier = [e for e in entries if e["_at"].date() < day]
            prev = earlier[-1] if earlier else None
            timestamp = f"{day.isoformat()}T23:59:59"
            pair = f"{prev['id'] if prev else '-'}->{head['id']}"

            details = cache.get((timestamp, file_path))
            if not (details and details.get("snapshot_pair") == pair
                    and details.get("summary_v") == SUMMARY_VERSION):
                details = self._diff_snapshots(history_dir, prev, head, name)
                if details is None:
                    continue
                details.update({"snapshot_pair": pair, "summary_v": SUMMARY_VERSION})
            details.update({"workspace": workspace, "file": name, "save_count": len(day_entries)})
            activities.append({
                "timestamp": timestamp,
                "action": "edited",
                "file_path": file_path,
                "file_type": RecentFileCollector()._get_file_type(file_path),
                "source": "vscode",
                "details": json.dumps(details, ensure_ascii=False),
            })
        return activities

    def _diff_snapshots(self, history_dir, prev, head, name):
        new_lines = self._read_snapshot(os.path.join(history_dir, head["id"]), name)
        if new_lines is None:
            return None
        old_lines = []
        if prev is not None:
            old_lines = self._read_snapshot(os.path.join(history_dir, prev["id"]), name) or []

        if prev is None:
            # 비교할 이전 저장본이 없으면 "무엇이 바뀌었나" 대신 "무슨 내용인가"로 요약
            return {"changes": [], "summary": self._summarize_new_file(name, new_lines)}

        from weekly_report.common.office_reader import diff_lines
        added, removed = diff_lines(old_lines, new_lines)
        if not added and not removed:
            return {"changes": [], "summary": "내용 변경 없음"}
        changes = [f"[-] {l[:150]}" for l in removed] + [f"[+] {l[:150]}" for l in added]
        changes = changes[:MAX_DIFF_LINES]
        return {"changes": changes, "summary": self._summarize_changes(name, changes)}

    @staticmethod
    def _summarize_new_file(name, lines):
        text = "\n".join(lines)[:6000]
        try:
            from weekly_report.ai.llm_summarizer import LLMSummarizer
            summary = LLMSummarizer().summarize(f"파일: {name}\n{text}", max_len=500, template="file")
        except Exception:
            summary = None
        # LLM이 붙이는 '# 요약' 같은 제목 줄 제거
        summary = re.sub(r"^\s*#+[^\n]*\n+", "", summary or "").strip()
        return f"(새로 작성/처음 저장) {summary or text[:200]}"

    @staticmethod
    def _read_snapshot(path, name):
        """스냅샷 파일 → 비교용 줄 목록. 바이너리·대용량이면 None.
        .ipynb는 JSON 전체가 아니라 셀 소스만 비교한다 (출력·메타데이터 노이즈 제거)."""
        try:
            if os.path.getsize(path) > MAX_SNAPSHOT_BYTES:
                return None
            raw = open(path, "rb").read()
        except OSError:
            return None
        if b"\x00" in raw:
            return None
        text = raw.decode("utf-8", errors="replace")
        if name.lower().endswith(".ipynb"):
            try:
                cells = json.loads(text).get("cells", [])
                text = "\n".join("".join(c.get("source") or "") for c in cells)
            except (ValueError, AttributeError):
                pass
        return [l.rstrip() for l in text.splitlines() if l.strip()]

    @staticmethod
    def _summarize_changes(name, changes):
        text = f"파일: {name}\n" + "\n".join(changes)
        try:
            from weekly_report.ai.llm_summarizer import PROMPT_TEMPLATES, LLMSummarizer
            summary = LLMSummarizer().complete(PROMPT_TEMPLATES["diff"], text, max_tokens=1000)
        except Exception:
            summary = None
        if summary:
            return summary
        added = [c.split("] ", 1)[-1] for c in changes if "[+]" in c]
        return " / ".join(added[:3])[:300]

    def _vscode_workspaces(self):
        """workspaceStorage에 기록된 작업 폴더 경로 목록 (긴 경로 우선)."""
        folders = set()
        for vscode_path in self._find_vscode_paths():
            for ws in glob.glob(os.path.join(vscode_path, "User", "workspaceStorage", "*", "workspace.json")):
                try:
                    with open(ws, encoding="utf-8") as f:
                        folder = self._uri_to_path(json.load(f).get("folder", ""))
                    if folder:
                        folders.add(folder)
                except (OSError, ValueError):
                    continue
        return sorted(folders, key=len, reverse=True)

    @staticmethod
    def _workspace_for(file_path, workspaces):
        lower = file_path.lower()
        for folder in workspaces:
            if lower.startswith(folder.lower().rstrip("\\") + "\\"):
                return os.path.basename(folder.rstrip("\\"))
        return os.path.basename(os.path.dirname(file_path))

    @staticmethod
    def _uri_to_path(uri):
        """file:///c%3A/Users/... → C:\\Users\\... (로컬 파일이 아니면 '')"""
        parsed = urlparse(uri or "")
        if parsed.scheme != "file":
            return ""
        path = unquote(parsed.path)
        if os.name == "nt":
            path = path.lstrip("/").replace("/", "\\")
            if len(path) > 1 and path[1] == ":":
                path = path[0].upper() + path[1:]
        return path

    def _find_vscode_paths(self):
        """Find VSCode user-data paths"""
        # Windows/macOS/Linux 경로를 모두 후보에 두고 존재하는 것만 사용
        possible_paths = [
            os.path.expanduser("~/AppData/Roaming/Code"),
            os.path.expanduser("~/Library/Application Support/Code"),
            os.path.expanduser("~/.config/Code"),
        ]
        return [p for p in possible_paths if os.path.exists(p)]

    # ---------------- Orca ----------------

    def collect_orca_activity(self, days=7):
        """orca-stats.json → 프로젝트별·날짜별 에이전트 작업 횟수/시간."""
        since = datetime.now() - timedelta(days=days)
        totals = defaultdict(lambda: {"sessions": 0, "duration_ms": 0})
        for orca_path in self._find_orca_paths():
            stats_file = os.path.join(orca_path, "orca-stats.json")
            if not os.path.exists(stats_file):
                continue
            try:
                with open(stats_file, encoding="utf-8") as f:
                    events = json.load(f).get("events") or []
            except (OSError, ValueError) as e:
                print(f"Error reading Orca stats {stats_file}: {e}")
                continue

            running = {}
            for ev in sorted(events, key=lambda e: e.get("at", 0)):
                key = (ev.get("meta") or {}).get("sessionKey")
                if ev.get("type") == "agent_start" and key:
                    worktree = str(ev.get("worktreeId") or "")
                    project = worktree.split("::", 1)[-1].replace("/", "\\")
                    running[key] = (project, ev["at"])
                elif ev.get("type") == "agent_stop" and key in running:
                    project, started = running.pop(key)
                    started_at = datetime.fromtimestamp(started / 1000)
                    if started_at < since or not project:
                        continue
                    duration = (ev.get("meta") or {}).get("durationMs") or (ev.get("at", started) - started)
                    bucket = totals[(project, started_at.date())]
                    bucket["sessions"] += 1
                    bucket["duration_ms"] += max(0, int(duration))

        return [
            {
                "timestamp": f"{day.isoformat()}T23:59:59",
                "action": "agent_sessions",
                "file_path": project,
                "file_type": "orca_agent",
                "source": "orca",
                "details": json.dumps({
                    "project": os.path.basename(project.rstrip("\\")),
                    "sessions": t["sessions"],
                    "duration_min": round(t["duration_ms"] / 60000),
                }, ensure_ascii=False),
            }
            for (project, day), t in sorted(totals.items(), key=lambda kv: kv[0][1])
        ]

    def _find_orca_paths(self):
        """Find Orca user-data paths"""
        possible_paths = [
            os.path.expanduser("~/AppData/Roaming/Orca"),
            os.path.expanduser("~/Library/Application Support/Orca"),
            os.path.expanduser("~/.config/Orca"),
        ]
        return [p for p in possible_paths if os.path.exists(p)]

    # ---------------- 공통 ----------------

    def _load_cache(self, source, marker):
        try:
            with ActivityDatabase(self.db_path) as db:
                return db.get_details_cache(source, marker)
        except Exception:
            return {}

    def collect_all_ide_activity(self, days=7):
        """Collect activity from all IDEs"""
        return self.collect_vscode_activity(days) + self.collect_orca_activity(days)

    def save_to_database(self, activities):
        """Save collected activities to database"""
        if not activities:
            return 0
        with ActivityDatabase(self.db_path) as db:
            db.add_activities(activities)
        return len(activities)


class RecentFileCollector:
    """Collector for recently opened files in IDEs"""
    
    def __init__(self, db_path=paths.DB_PATH):
        self.db_path = db_path
    
    def collect_vscode_recent_files(self):
        """Collect recently opened files from VSCode"""
        activities = []
        
        # VSCode stores recent files in workspace storage
        vscode_paths = [
            os.path.expanduser("~/AppData/Roaming/Code/User/globalStorage"),
            os.path.expanduser("~/.vscode/User/globalStorage"),
            os.path.expanduser(
                "~/Library/Application Support/Code/User/globalStorage"
            ),
            os.path.expanduser("~/.config/Code/User/globalStorage"),
        ]
        
        for path in vscode_paths:
            if os.path.exists(path):
                # Look for recent files in storage
                storage_files = glob.glob(os.path.join(path, "*.json"))
                for storage_file in storage_files:
                    try:
                        with open(storage_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            # Parse recent files from the JSON structure
                            if isinstance(data, dict):
                                self._extract_recent_files(data, storage_file, activities)
                    except Exception as e:
                        print(f"Error reading VSCode storage {storage_file}: {e}")
        
        return activities
    
    def _extract_recent_files(self, data, source_file, activities):
        """Extract recent file information from VSCode storage"""
        if isinstance(data, dict):
            for key, value in data.items():
                if 'recent' in key.lower() or 'history' in key.lower():
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict) and 'path' in item:
                                activities.append({
                                    'timestamp': datetime.now().isoformat(),
                                    'action': 'opened',
                                    'file_path': item['path'],
                                    'file_type': self._get_file_type(item['path']),
                                    'source': 'vscode_recent'
                                })
                elif isinstance(value, (dict, list)):
                    self._extract_recent_files(value, source_file, activities)
    
    def _get_file_type(self, file_path):
        """Determine file type from extension"""
        ext = Path(file_path).suffix.lower()
        type_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.cs': 'csharp',
            '.go': 'go',
            '.rs': 'rust',
            '.php': 'php',
            '.rb': 'ruby',
            '.swift': 'swift',
            '.kt': 'kotlin',
            '.scala': 'scala',
            '.html': 'html',
            '.css': 'css',
            '.scss': 'scss',
            '.json': 'json',
            '.xml': 'xml',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.md': 'markdown',
            '.txt': 'text',
            '.sql': 'sql',
        }
        return type_map.get(ext, 'unknown')


def main():
    """Test IDE collector"""
    collector = IDECollector()
    
    print("Collecting VSCode activity...")
    vscode_activities = collector.collect_vscode_activity()
    print(f"Found {len(vscode_activities)} VSCode activities")
    
    print("Collecting Orca activity...")
    orca_activities = collector.collect_orca_activity()
    print(f"Found {len(orca_activities)} Orca activities")
    
    all_activities = vscode_activities + orca_activities
    print(f"Total IDE activities: {len(all_activities)}")
    
    if all_activities:
        print("\nSample activities:")
        for activity in all_activities[:5]:
            print(f"  {activity['timestamp']} | {activity['action']} | {activity['file_path']}")


if __name__ == "__main__":
    main()