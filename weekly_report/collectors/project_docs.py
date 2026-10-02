#!/usr/bin/env python3
"""
이 프로젝트 문서·지난 보고서 → 근거 전용 활동 (RAG·STEP 3 근거로만 쓰고 STEP 1 기록에는 나오지 않음)

- 프로젝트 MD 문서(progress.md·decisions.md·README.md·PROJECT_STATUS.md) — source='project_docs', 원본 근거
  바뀔 때마다 이전 스냅샷(data/project_docs_snapshot.json)과 비교해 추가·변경된 줄을 LLM으로 요약.
  처음 실행할 때는 이번 주 월요일 이전 마지막 git 커밋의 문서를 비교 기준으로 쓴다 (이번 주 변경분만).
  git 기록이 없으면 비교 기준만 저장한다 (문서 전체를 '이번 주 변경'으로 넣지 않도록)
- 지난 보고서(reports/weekly_report_<시작>_<끝>.md) — source='past_report', 2차 근거 '(지난 보고)'
  이미 끝난 주의 보고서만, '이번 주 핵심 요약' 부분을 그다음 주 월요일 시각의 활동으로 넣는다.
  이번 주 보고서·test_reports/·복사본은 넣지 않는다 — AI가 만든 요약을 근거로 되먹이면
  지난 보고의 오류가 다음 보고의 '근거'가 되어 굳어지므로, 원본 근거가 있으면 원본을 우선한다.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta

from weekly_report import paths
from weekly_report.storage.database import ActivityDatabase

PROJECT_DOCS = ("progress.md", "decisions.md", "README.md", "PROJECT_STATUS.md")
SNAPSHOT_PATH = os.path.join(paths.DATA_DIR, "project_docs_snapshot.json")
REPORT_NAME_RE = re.compile(r"^weekly_report_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.md$")
PAST_REPORT_WEEKS = 8   # 지난 보고는 최근 몇 주치까지
MAX_CHANGE_LINES = 80   # 요약에 넘길 변경 줄 수 (그 이상은 LLM 입력만 길어짐)


def week_summary_bullets(markdown):
    """보고서 md → '이번 주 핵심 요약' 불릿 목록"""
    match = re.search(r"^###\s*이번 주 핵심 요약\s*$(.*?)(?=^#{1,3}\s)", markdown, re.M | re.S)
    if not match:
        return []
    return [line.strip()[2:].strip() for line in match.group(1).splitlines() if line.strip().startswith("- ")]


class ProjectDocsCollector:
    def __init__(self, db_path=paths.DB_PATH, base_dir=paths.BASE_DIR, reports_dir=paths.REPORTS_DIR,
                 snapshot_path=SNAPSHOT_PATH, summarize=None, today=None):
        self.db_path = db_path
        self.base_dir = base_dir
        self.reports_dir = reports_dir
        self.snapshot_path = snapshot_path
        self.summarize = summarize or self._summarize_changes
        self.today = today

    def collect(self):
        return self.collect_docs() + self.collect_past_reports()

    # ---------- 프로젝트 문서 ----------

    def _load_snapshot(self):
        try:
            with open(self.snapshot_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def collect_docs(self):
        from weekly_report.common.office_reader import diff_lines

        snapshot = self._load_snapshot()
        activities = []
        for name in PROJECT_DOCS:
            path = os.path.join(self.base_dir, name)
            if not os.path.exists(path):
                continue
            mtime = os.path.getmtime(path)
            previous = snapshot.get(name)
            if previous and previous.get("mtime") == mtime:
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = [line.rstrip() for line in f.read().splitlines() if line.strip()]
            snapshot[name] = {"mtime": mtime, "lines": lines}
            if previous is None:
                previous = self._git_baseline(name)
                if previous is None:
                    continue  # 첫 실행이고 git 기록도 없으면 비교 기준만 저장
            added, removed = diff_lines(previous.get("lines", []), lines)
            if not added and not removed:
                continue
            changes = ([f"[-] {line}" for line in removed] + [f"[+] {line}" for line in added])[:MAX_CHANGE_LINES]
            summary = self.summarize(name, changes)
            if not summary:
                continue
            when = datetime.fromtimestamp(mtime)
            activities.append({
                "timestamp": when.isoformat(timespec="seconds"),
                "action": "modified",
                "file_path": path,
                "file_type": "md",
                "source": "project_docs",
                "details": json.dumps({"title": f"주간보고 자동작성 프로그램 문서 {name}", "summary": summary,
                                       "content_added": "\n".join(added)}, ensure_ascii=False),
            })
        os.makedirs(os.path.dirname(self.snapshot_path), exist_ok=True)
        with open(self.snapshot_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
        return activities

    def _git_baseline(self, name):
        """이번 주 월요일 이전 마지막 커밋의 문서 → {"lines": [...]} (없으면 None).
        월요일 이전 커밋이 없으면(이번 주에 저장소를 만든 경우) 이번 주 첫 커밋을 기준으로 한다."""
        import subprocess
        today = self.today or date.today()
        monday = today - timedelta(days=today.weekday())
        try:
            commit = subprocess.run(
                ["git", "-C", self.base_dir, "log", "-1", f"--before={monday.isoformat()} 00:00", "--format=%H", "--", name],
                capture_output=True, text=True, timeout=10).stdout.strip()
            if not commit:
                commit = subprocess.run(
                    ["git", "-C", self.base_dir, "log", "--reverse", f"--since={monday.isoformat()} 00:00",
                     "--format=%H", "--", name],
                    capture_output=True, text=True, timeout=10).stdout.split()
                commit = commit[0] if commit else ""
            if not commit:
                return None
            text = subprocess.run(["git", "-C", self.base_dir, "show", f"{commit}:{name}"],
                                  capture_output=True, timeout=10).stdout.decode("utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            return None
        return {"lines": [line.rstrip() for line in text.splitlines() if line.strip()]}

    @staticmethod
    def _summarize_changes(name, changes):
        try:
            from weekly_report.ai.llm_summarizer import PROMPT_TEMPLATES, LLMSummarizer, check_summary
            return LLMSummarizer().complete(PROMPT_TEMPLATES["diff"], f"파일: {name}\n" + "\n".join(changes),
                                            max_tokens=1000, max_input=8000, temperature=0,
                                            validate=check_summary)
        except Exception as error:
            print(f"Warning: project doc summary failed: {error}")
            return None

    # ---------- 지난 보고서 (2차 근거) ----------

    def collect_past_reports(self):
        if not os.path.isdir(self.reports_dir):
            return []
        today = self.today or date.today()
        this_monday = today - timedelta(days=today.weekday())
        oldest = this_monday - timedelta(weeks=PAST_REPORT_WEEKS)
        activities = []
        for name in sorted(os.listdir(self.reports_dir)):
            match = REPORT_NAME_RE.match(name)
            if not match:
                continue  # 복사본·미리보기 등은 제외
            start, end = (date.fromisoformat(d) for d in match.groups())
            if end >= this_monday or end < oldest:
                continue  # 이번 주(아직 진행 중) 보고서는 근거로 쓰지 않음
            path = os.path.join(self.reports_dir, name)
            with open(path, encoding="utf-8", errors="replace") as f:
                bullets = week_summary_bullets(f.read())
            if not bullets:
                continue
            # 다음 주 월요일 활동으로 — 그 주의 STEP 3에서 '지난 보고'로 검색되도록
            when = datetime.combine(end + timedelta(days=1), datetime.min.time()).replace(hour=9)
            activities.append({
                "timestamp": when.isoformat(timespec="seconds"),
                "action": "past_report",
                "file_path": path,
                "file_type": "md",
                "source": "past_report",
                "details": json.dumps({"title": f"{start:%m/%d}~{end:%m/%d} 주간보고", "week_start": start.isoformat(),
                                       "week_end": end.isoformat(), "summary": "\n".join(f"- {b}" for b in bullets)},
                                      ensure_ascii=False),
            })
        return activities

    def save_to_database(self, activities):
        if not activities:
            return 0
        with ActivityDatabase(self.db_path) as db:
            return db.add_activities(activities)
