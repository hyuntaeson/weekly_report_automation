#!/usr/bin/env python3
"""
OneNote Activity Collector
teams_collector의 Graph 위임 토큰을 재사용해 노트북/섹션의 최근 수정 시각을 수집.

제한사항 (2026-09-29 확인):
- /me/onenote/pages·sections/{id}/pages는 Notes.Read.All scope 필요 → 사내
  first-party client에 사전 승인이 없어 403 (AADSTS65002). 페이지 제목/본문은
  수집 불가하고 "어느 노트북의 어느 섹션이 언제 수정됐는지"까지만 가능.
- 데스크톱 OneNote 미설치 환경이라 COM API도 사용 불가.
- .one 파일 자체는 파일 감시(이미 동작)로 수정 이벤트가 잡힘. 이 수집기는
  어떤 노트북/섹션이 바뀌었는지 맥락을 제공하는 역할.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

from database import ActivityDatabase
from teams_collector import _graph_get, get_access_token, TOKEN_FILE


class OneNoteCollector:
    """Microsoft Graph 기반 OneNote 활동 수집기 (섹션 수준)"""

    def __init__(self, db_path="data/activities.db", token_file=TOKEN_FILE):
        self.db_path = db_path
        self.token_file = token_file
        self._token = None

    @property
    def enabled(self):
        return os.path.exists(self.token_file)

    def collect_activity(self, days=7):
        """최근 N일 내 lastModifiedDateTime이 바뀐 노트북·섹션을 수집."""
        access_token = self._token or get_access_token(self.token_file)
        if not access_token:
            return []
        self._token = access_token

        since = datetime.now(timezone.utc) - timedelta(days=days)
        activities = []

        try:
            notebooks = _graph_get(
                access_token,
                "/me/onenote/notebooks",
                {"$select": "displayName,lastModifiedDateTime,id",
                 "$expand": "sections($select=displayName,lastModifiedDateTime)"},
            ).get("value", [])
        except Exception as e:
            print(f"Error collecting OneNote notebooks: {e}")
            return []

        for nb in notebooks:
            nb_name = nb.get("displayName") or "(노트북)"
            nb_mod = nb.get("lastModifiedDateTime")
            if nb_mod and self._parse_dt(nb_mod) >= since:
                activities.append(self._activity(
                    nb_mod, "modified", f"OneNote 노트북: {nb_name}",
                    {"type": "notebook", "name": nb_name},
                ))
            for sec in nb.get("sections", []):
                sec_mod = sec.get("lastModifiedDateTime")
                if not sec_mod or self._parse_dt(sec_mod) < since:
                    continue
                sec_name = sec.get("displayName") or "(섹션)"
                activities.append(self._activity(
                    sec_mod, "modified",
                    f"OneNote 섹션: {nb_name} / {sec_name}",
                    {"type": "section", "notebook": nb_name, "name": sec_name},
                ))
        return activities

    @staticmethod
    def _parse_dt(value):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    @staticmethod
    def _activity(timestamp, action, file_path, extra):
        return {
            "timestamp": timestamp,
            "action": action,
            "file_path": file_path,
            "file_type": "onenote",
            "source": "onenote",
            "details": json.dumps(extra, ensure_ascii=False),
        }

    def save_to_database(self, activities):
        if not activities:
            return 0
        with ActivityDatabase(self.db_path) as db:
            return db.add_activities(activities)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    parser = argparse.ArgumentParser(description="OneNote activity collector")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    collector = OneNoteCollector()
    if not collector.enabled:
        print("No token file. Run: python teams_collector.py --login")
        return
    acts = collector.collect_activity(days=args.days)
    print(f"Collected {len(acts)} OneNote activities")
    for a in acts:
        print(f"  {a['timestamp'][:16]} | {a['file_path']}")


if __name__ == "__main__":
    main()
