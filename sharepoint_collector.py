#!/usr/bin/env python3
"""
SharePoint/OneDrive 파일 활동 수집기

teams_collector의 Graph 위임 토큰을 재사용한다 — Files.Read.All scope가
이미 포함되어 있어 추가 인증 불필요.

수집 범위:
- 내 OneDrive 최근 파일(/me/drive/recent) 중 기간 내 수정된 것
- 나와 공유된 파일(/me/drive/sharedWithMe) 중 기간 내 수정된 것

수정 시각(lastModifiedDateTime) 기준으로만 수집하며 파일 본문은 읽지 않는다.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

from database import ActivityDatabase
from teams_collector import _graph_get, _graph_get_all, get_access_token, TOKEN_FILE


class SharePointCollector:
    """Microsoft Graph 기반 SharePoint/OneDrive 파일 수정 활동 수집기"""

    def __init__(self, db_path="data/activities.db", token_file=TOKEN_FILE):
        self.db_path = db_path
        self.token_file = token_file
        self._token = None

    @property
    def enabled(self):
        return os.path.exists(self.token_file)

    def collect_activity(self, days=7):
        """최근 N일 내 수정된 드라이브 파일을 수집."""
        access_token = self._token or get_access_token(self.token_file)
        if not access_token:
            return []
        self._token = access_token

        since = datetime.now(timezone.utc) - timedelta(days=days)
        activities = []
        seen_ids = set()

        # 내 OneDrive 최근 파일
        try:
            recent = _graph_get_all(
                access_token, "/me/drive/recent", {"$top": 100}, limit=500
            )
            for item in recent:
                self._append_if_modified(activities, seen_ids, item, since, "mydrive")
        except Exception as e:
            print(f"Error collecting OneDrive recent files: {e}")

        # 나와 공유된 파일 (SharePoint/타 사용자 OneDrive 포함)
        try:
            shared = _graph_get_all(
                access_token, "/me/drive/sharedWithMe", {"$top": 100}, limit=500
            )
            for item in shared:
                drive_item = item.get("driveItem") or item
                self._append_if_modified(
                    activities, seen_ids, drive_item, since, "shared"
                )
        except Exception as e:
            print(f"Error collecting shared files: {e}")

        return activities

    def _append_if_modified(self, activities, seen_ids, item, since, kind):
        item_id = item.get("id")
        if not item_id or item_id in seen_ids:
            return
        if "folder" in item or item.get("package"):  # 폴더·패키지는 제외
            return
        modified = item.get("lastModifiedDateTime")
        if not modified or self._parse_dt(modified) < since:
            return
        seen_ids.add(item_id)

        name = item.get("name") or "(이름 없음)"
        modified_by = ((item.get("lastModifiedBy") or {}).get("user") or {}).get(
            "displayName"
        )
        web_url = item.get("webUrl") or ""
        owner = (
            ((item.get("remoteItem") or {}).get("sharepointIds") or {}).get(
                "listItemUniqueId"
            )
            or None
        )
        path = (item.get("parentReference") or {}).get("path") or ""

        activities.append(
            {
                "timestamp": modified,
                "action": "modified",
                "file_path": f"SharePoint 파일: {name}",
                "file_type": "sharepoint",
                "source": "sharepoint",
                "details": json.dumps(
                    {
                        "name": name,
                        "web_url": web_url,
                        "modified_by": modified_by,
                        "kind": kind,  # mydrive | shared
                        "folder": path,
                        "owner_ref": owner,
                        "item_id": item_id,
                        "size": item.get("size"),
                    },
                    ensure_ascii=False,
                ),
            }
        )

    @staticmethod
    def _parse_dt(value):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def save_to_database(self, activities):
        if not activities:
            return 0
        with ActivityDatabase(self.db_path) as db:
            return db.add_activities(activities)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    parser = argparse.ArgumentParser(description="SharePoint/OneDrive activity collector")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--save", action="store_true", help="save to DB")
    args = parser.parse_args()

    collector = SharePointCollector()
    if not collector.enabled:
        print("No token file. Run: python teams_collector.py --login")
        return
    acts = collector.collect_activity(days=args.days)
    print(f"Collected {len(acts)} SharePoint/OneDrive activities")
    for a in acts:
        print(f"  {a['timestamp'][:16]} | {a['file_path']}")
    if args.save:
        print(f"Saved {collector.save_to_database(acts)} to DB")


if __name__ == "__main__":
    main()
