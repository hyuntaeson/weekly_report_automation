#!/usr/bin/env python3
"""
SharePoint/OneDrive 파일 활동 수집기

teams_collector의 Graph 위임 토큰을 재사용한다 — Files.Read.All scope가
이미 포함되어 있어 추가 인증 불필요.

수집 범위:
- 내 OneDrive 최근 파일(/me/drive/recent) 중 기간 내 수정된 것
- 나와 공유된 파일(/me/drive/sharedWithMe) 중 기간 내 수정된 것

오피스 문서(xlsx/docx/pptx)는 "무엇을 수정했는지"까지 수집한다:
날짜(로컬)별로 그날 마지막 버전과 그 전날까지의 마지막 버전을 받아
Office COM으로 열어 비교하고(다운로드 파일은 사내 DRM으로 암호화되어
파서로는 못 읽음), 바뀐 줄을 LLM으로 한두 문장 요약한다.
같은 버전 쌍은 DB에 저장된 결과를 재사용해 다시 받지 않는다.
그 외 파일은 수정 시각만 기록한다.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone

import office_reader
from database import ActivityDatabase
from teams_collector import GRAPH_BASE, TOKEN_FILE, _graph_get_all, get_access_token

MAX_DIFF_LINES = 60
# 변경 요약 방식(프롬프트·길이)을 바꾸면 올린다 → 캐시된 이전 요약은 다시 생성
SUMMARY_VERSION = 2


class SharePointCollector:
    """Microsoft Graph 기반 SharePoint/OneDrive 파일 수정 활동 수집기"""

    def __init__(self, db_path="data/activities.db", token_file=TOKEN_FILE):
        self.db_path = db_path
        self.token_file = token_file
        self._token = None

    @property
    def enabled(self):
        return os.path.exists(self.token_file)

    def collect_activity(self, days=7, with_changes=True):
        """최근 N일 내 수정된 드라이브 파일을 수집.
        with_changes=False면 버전 비교 없이 수정 시각만 기록."""
        access_token = self._token or get_access_token(self.token_file)
        if not access_token:
            return []
        self._token = access_token

        since = datetime.now(timezone.utc) - timedelta(days=days)
        files = []
        seen_ids = set()

        # 내 OneDrive 최근 파일
        try:
            recent = _graph_get_all(
                access_token, "/me/drive/recent", {"$top": 100}, limit=500
            )
            for item in recent:
                self._append_if_modified(files, seen_ids, item, since, "mydrive")
        except Exception as e:
            print(f"Error collecting OneDrive recent files: {e}")

        # 나와 공유된 파일 (SharePoint/타 사용자 OneDrive 포함)
        try:
            shared = _graph_get_all(
                access_token, "/me/drive/sharedWithMe", {"$top": 100}, limit=500
            )
            for item in shared:
                drive_item = item.get("driveItem") or item
                self._append_if_modified(files, seen_ids, drive_item, since, "shared")
        except Exception as e:
            print(f"Error collecting shared files: {e}")

        if not with_changes:
            return [self._plain_activity(f) for f in files]
        return self._with_change_details(files, since)

    def _append_if_modified(self, files, seen_ids, item, since, kind):
        item_id = item.get("id")
        if not item_id or item_id in seen_ids:
            return
        if "folder" in item or item.get("package"):  # 폴더·패키지는 제외
            return
        modified = item.get("lastModifiedDateTime")
        if not modified or self._parse_dt(modified) < since:
            return
        seen_ids.add(item_id)

        # 공유/최근 항목은 remoteItem이 실제 파일 위치(다른 드라이브)를 가리킴
        remote = item.get("remoteItem") or {}
        drive_id = (remote.get("parentReference") or {}).get("driveId") or (
            item.get("parentReference") or {}
        ).get("driveId")
        files.append(
            {
                "name": item.get("name") or "(이름 없음)",
                "modified": modified,
                "modified_by": ((item.get("lastModifiedBy") or {}).get("user") or {}).get(
                    "displayName"
                ),
                "web_url": item.get("webUrl") or "",
                "kind": kind,  # mydrive | shared
                "folder": (item.get("parentReference") or {}).get("path") or "",
                "item_id": item_id,
                "drive_id": drive_id,
                "remote_id": remote.get("id") or item_id,
                "size": item.get("size"),
            }
        )

    @staticmethod
    def _plain_activity(f):
        return {
            "timestamp": f["modified"],
            "action": "modified",
            "file_path": f"SharePoint 파일: {f['name']}",
            "file_type": "sharepoint",
            "source": "sharepoint",
            "details": json.dumps(
                {k: f[k] for k in ("name", "web_url", "modified_by", "kind", "folder", "item_id", "size")},
                ensure_ascii=False,
            ),
        }

    # ---------- 버전 비교 ----------

    def _with_change_details(self, files, since):
        """오피스 문서는 날짜별 버전 비교 활동으로, 나머지는 수정 기록으로 변환."""
        cache = self._load_cached_details()
        me_name = self._me_name()
        activities = []
        tmpdir = tempfile.mkdtemp(prefix="wr_sp_")
        try:
            with ExitStack() as stack:
                apps = {}

                def app_for(prog):
                    if prog not in apps:
                        apps[prog] = stack.enter_context(office_reader.office_app(prog))
                    return apps[prog]

                for f in files:
                    prog = office_reader.prog_for(f["name"])
                    daily = None
                    if prog and f.get("drive_id"):
                        try:
                            daily = self._daily_version_activities(
                                f, prog, since, cache, me_name, tmpdir, app_for
                            )
                        except Exception as e:
                            print(f"Warning: SharePoint version diff failed ({f['name']}): {e}")
                    activities.extend(daily if daily else [self._plain_activity(f)])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return activities

    def _daily_version_activities(self, f, prog, since, cache, me_name, tmpdir, app_for):
        base = f"/drives/{f['drive_id']}/items/{f['remote_id']}"
        versions = _graph_get_all(self._token, base + "/versions")
        if not versions:
            return None
        for v in versions:
            v["_at"] = self._parse_dt(v["lastModifiedDateTime"]).astimezone()
        versions.sort(key=lambda v: v["_at"])
        current_id = versions[-1]["id"]
        local_since = since.astimezone()

        by_day = {}
        for v in versions:
            if v["_at"] >= local_since:
                by_day.setdefault(v["_at"].date(), []).append(v)

        activities = []
        file_path = f"SharePoint 파일: {f['name']}"
        for day, day_versions in sorted(by_day.items()):
            head = day_versions[-1]
            earlier = [v for v in versions if v["_at"].date() < day]
            prev = earlier[-1] if earlier else None
            # 같은 날 여러 번 저장돼도 한 활동으로 갱신되도록 날짜 고정 키 사용
            timestamp = f"{day.isoformat()}T23:59:59"
            pair = f"{prev['id'] if prev else '-'}->{head['id']}"
            editors = list(dict.fromkeys(
                ((v.get("lastModifiedBy") or {}).get("user") or {}).get("displayName") or "?"
                for v in day_versions
            ))

            details = cache.get((timestamp, file_path))
            if not (
                details
                and details.get("version_pair") == pair
                and details.get("summary_v") == SUMMARY_VERSION
            ):
                details = self._diff_details(
                    base, prog, prev, head, current_id, tmpdir, app_for,
                    ext=os.path.splitext(f["name"])[1].lower(),
                )
            details.update(
                {
                    "name": f["name"],
                    "web_url": f["web_url"],
                    "kind": f["kind"],
                    "item_id": f["item_id"],
                    "editors": editors,
                    "edited_by_me": bool(me_name and me_name in editors),
                    "version_count": len(day_versions),
                }
            )
            # 비교 실패 시에는 캐시 키를 남기지 않아 다음 수집 때 재시도
            if not details.pop("failed", False):
                details["version_pair"] = pair
                details["summary_v"] = SUMMARY_VERSION
            activities.append(
                {
                    "timestamp": timestamp,
                    "action": "modified",
                    "file_path": file_path,
                    "file_type": "sharepoint",
                    "source": "sharepoint",
                    "details": json.dumps(details, ensure_ascii=False),
                }
            )
        return activities

    def _diff_details(self, base, prog, prev, head, current_id, tmpdir, app_for, ext):
        """두 버전을 받아 COM으로 읽고 비교 → {changes, summary}."""
        failed = {"summary": "", "failed": True}
        app = app_for(prog)
        if app is None:
            return failed
        new_lines = self._read_version(base, head["id"], current_id, prog, tmpdir, app, ext)
        if new_lines is None:
            return failed
        old_lines = []
        if prev is not None:
            old_lines = self._read_version(base, prev["id"], current_id, prog, tmpdir, app, ext)
            if old_lines is None:
                return failed

        added, removed = office_reader.diff_lines(old_lines, new_lines)
        if not added and not removed:
            return {"changes": [], "summary": "내용 변경 없음 (서식 등 수정)"}
        changes = [f"[-] {l[:150]}" for l in removed] + [f"[+] {l[:150]}" for l in added]
        changes = changes[:MAX_DIFF_LINES]
        if prev is None:
            changes = [f"(신규 문서) {l}" for l in changes]
        return {"changes": changes, "summary": self._summarize_changes(changes)}

    def _read_version(self, base, version_id, current_id, prog, tmpdir, app, ext):
        # Graph는 현재 버전을 /versions/{id}/content로 내려주지 않음 → 일반 /content
        path = base + ("/content" if version_id == current_id else f"/versions/{version_id}/content")
        data = self._download(path)
        # 원래 확장자 유지 — .xls를 .xlsx로 저장하면 Excel이 형식 불일치로 열기를 거부함
        local = os.path.join(tmpdir, f"v{version_id.replace('.', '_')}_{time.time_ns()}{ext}")
        with open(local, "wb") as fh:
            fh.write(data)
        return office_reader.document_lines(app, prog, local)

    def _download(self, path, max_retries=3):
        req = urllib.request.Request(
            GRAPH_BASE + path, headers={"Authorization": f"Bearer {self._token}"}
        )
        for attempt in range(max_retries):
            try:
                return urllib.request.urlopen(req, timeout=120).read()
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < max_retries - 1:
                    time.sleep(float(e.headers.get("Retry-After") or 2 * (attempt + 1)))
                    continue
                raise

    @staticmethod
    def _summarize_changes(changes):
        text = "\n".join(changes)
        try:
            from llm_summarizer import PROMPT_TEMPLATES, LLMSummarizer
            summary = LLMSummarizer().complete(PROMPT_TEMPLATES["diff"], text, max_tokens=1000)
        except Exception:
            summary = None
        if summary:
            return summary
        # LLM 미사용 시: 추가/변경된 줄 앞부분을 그대로 보여준다
        added = [c[4:] for c in changes if c.startswith("[+]")] or [c[4:] for c in changes]
        return " / ".join(added[:3])[:200]

    def _load_cached_details(self):
        """이미 비교한 (timestamp, file_path) → details. 같은 버전 쌍이면 재사용."""
        cache = {}
        try:
            with ActivityDatabase(self.db_path) as db:
                cache = db.get_details_cache("sharepoint", "version_pair")
        except Exception:
            pass
        return cache

    def _me_name(self):
        try:
            with open(self.token_file, encoding="utf-8") as fh:
                return json.load(fh).get("me_display_name")
        except (OSError, json.JSONDecodeError):
            return None

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
    parser.add_argument("--no-changes", action="store_true", help="skip version diff")
    args = parser.parse_args()

    collector = SharePointCollector()
    if not collector.enabled:
        print("No token file. Run: python teams_collector.py --login")
        return
    acts = collector.collect_activity(days=args.days, with_changes=not args.no_changes)
    print(f"Collected {len(acts)} SharePoint/OneDrive activities")
    for a in acts:
        d = json.loads(a["details"])
        line = f"  {a['timestamp'][:16]} | {a['file_path']}"
        if d.get("summary"):
            line += f"\n      {', '.join(d.get('editors') or [])}: {d['summary']}"
        print(line)
    if args.save:
        print(f"Saved {collector.save_to_database(acts)} to DB")


if __name__ == "__main__":
    main()
