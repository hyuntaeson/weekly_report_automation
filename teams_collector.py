#!/usr/bin/env python3
"""
Microsoft Teams Activity Collector
Microsoft Graph API (위임 권한, 디바이스 코드 로그인)로 본인 Teams 채팅 수집.

배경:
- 사내 DevX MCP(sm-ops-pub-mcp)에도 Teams 조회 도구가 있지만, 그 MCP의 토큰 캐시가
  로컬 Qdrant(localhost:6333)를 요구해서 이 환경에서는 동작하지 않음 (2026-09-28 확인).
- 대신 같은 방식의 위임 권한 로그인을 직접 구현: Microsoft Office first-party
  client_id + `.default` scope로 디바이스 코드 로그인 → 토큰을 로컬 파일에 저장 →
  refresh_token으로 자동 갱신. Azure AD 앱 등록 불필요.

토큰 파일: config/teams_graph_token.json (access+refresh token 포함, gitignore 필수)
최초 1회 로그인: `python teams_collector.py --login` 실행 후 안내 코드 입력.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

from database import ActivityDatabase

TENANT = "shinsegaegroup.onmicrosoft.com"
# Microsoft Office first-party client (DevX MCP와 동일한 client 사용).
# 사내 전역 admin consent가 이미 적용된 상태라 별도 Azure AD 앱 등록 불필요.
CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"
SCOPE = "https://graph.microsoft.com/.default offline_access"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_FILE = "config/teams_graph_token.json"


# ---------- HTTP 헬퍼 ----------

def _post_form(url, data):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def _graph_get(access_token, path, params=None):
    url = GRAPH_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {access_token}"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


# ---------- 토큰 관리 ----------

def device_code_login(token_file=TOKEN_FILE):
    """디바이스 코드 로그인 대화형 실행. 완료 시 토큰을 token_file에 저장."""
    dc = _post_form(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/devicecode",
        {"client_id": CLIENT_ID, "scope": SCOPE},
    )
    print(dc["message"], flush=True)

    interval = dc.get("interval", 5)
    deadline = time.time() + dc.get("expires_in", 900)
    while time.time() < deadline:
        time.sleep(interval)
        try:
            token = _post_form(
                f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": CLIENT_ID,
                    "device_code": dc["device_code"],
                },
            )
        except urllib.error.HTTPError as e:
            err = json.loads(e.read())
            if err.get("error") == "authorization_pending":
                continue
            raise RuntimeError(f"login failed: {err}")
        token["saved_at"] = time.time()
        with open(token_file, "w", encoding="utf-8") as f:
            json.dump(token, f, indent=2)
        print(f"Token saved to {token_file}", flush=True)
        return token
    raise RuntimeError("device code expired")


def _is_expired(token):
    saved = token.get("saved_at", 0)
    return time.time() > saved + int(token.get("expires_in", 3600)) - 120


def get_access_token(token_file=TOKEN_FILE):
    """저장된 토큰 로드. 만료 시 refresh_token으로 갱신. 없으면 None."""
    if not os.path.exists(token_file):
        return None
    try:
        with open(token_file, encoding="utf-8") as f:
            token = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    if not _is_expired(token):
        return token.get("access_token")

    refresh = token.get("refresh_token")
    if not refresh:
        return None
    try:
        new_token = _post_form(
            f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
            {
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": refresh,
                "scope": SCOPE,
            },
        )
    except urllib.error.HTTPError as e:
        print(f"Warning: token refresh failed: {e}")
        return None
    new_token["saved_at"] = time.time()
    if "refresh_token" not in new_token and refresh:
        new_token["refresh_token"] = refresh
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(new_token, f, indent=2)
    return new_token.get("access_token")


# ---------- 수집 ----------

class TeamsCollector:
    """Microsoft Graph 기반 Teams 활동 수집기 (위임 권한)"""

    def __init__(self, db_path="data/activities.db", token_file=TOKEN_FILE):
        self.db_path = db_path
        self.token_file = token_file
        self._token = None
        self._me_name = None

    def _me_display_name(self, access_token):
        """본인 표시이름 조회. 토큰 파일에 캐시해서 매번 /me를 안 부르게 함.
        보고서 생성기가 '내가 보낸 메시지'를 구분할 때도 이 값을 사용."""
        if self._me_name:
            return self._me_name
        try:
            with open(self.token_file, encoding="utf-8") as f:
                cached = json.load(f).get("me_display_name")
            if cached:
                self._me_name = cached
                return cached
        except (OSError, json.JSONDecodeError):
            pass
        try:
            me = _graph_get(access_token, "/me", {"$select": "displayName"})
            name = me.get("displayName")
        except Exception as e:
            print(f"Warning: failed to fetch /me displayName: {e}")
            return None
        if name:
            self._me_name = name
            try:
                with open(self.token_file, encoding="utf-8") as f:
                    token = json.load(f)
                token["me_display_name"] = name
                with open(self.token_file, "w", encoding="utf-8") as f:
                    json.dump(token, f, indent=2)
            except (OSError, json.JSONDecodeError):
                pass
        return name

    @property
    def enabled(self):
        return os.path.exists(self.token_file)

    def collect_all_teams_activity(self, days=7):
        """본인 Teams 채팅방의 최근 메시지 수집. 토큰 없으면 빈 리스트."""
        access_token = self._token or get_access_token(self.token_file)
        if not access_token:
            return []
        self._token = access_token

        me_name = self._me_display_name(access_token)
        since = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        activities = []
        try:
            chats = _graph_get(access_token, "/me/chats", {"$top": 50}).get("value", [])
        except Exception as e:
            print(f"Error listing Teams chats: {e}")
            return []

        for chat in chats:
            chat_id = chat.get("id")
            title = chat.get("topic") or chat.get("chatType") or "chat"
            try:
                messages = _graph_get(
                    access_token,
                    f"/me/chats/{urllib.parse.quote(chat_id, safe='')}/messages",
                    {"$top": 50},
                ).get("value", [])
            except Exception as e:
                print(f"Error reading messages for chat {title}: {e}")
                continue

            for msg in messages:
                created = msg.get("createdDateTime", "")
                if created < since:
                    continue
                activity = self._message_to_activity(msg, title, me_name)
                if activity:
                    activities.append(activity)

        activities.extend(self.collect_calendar_events(days))
        return activities

    def collect_calendar_events(self, days=7):
        """Graph /me/calendarview로 최근 N일 + 내일까지의 일정을 수집.
        참석자 목록·온라인 회의 여부 포함 — Outlook COM 수집보다 정보가
        풍부하므로 회의 관련은 이쪽이 기준(source='teams')."""
        access_token = self._token or get_access_token(self.token_file)
        if not access_token:
            return []
        self._token = access_token

        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            events = _graph_get(
                access_token, "/me/calendarview",
                {
                    "startDateTime": start,
                    "endDateTime": end,
                    "$top": 100,
                    "$select": "subject,start,end,attendees,organizer,isOnlineMeeting,onlineMeetingUrl,location,isCancelled",
                    "$orderby": "start/dateTime",
                },
            ).get("value", [])
        except Exception as e:
            print(f"Error collecting Teams calendar: {e}")
            return []

        activities = []
        for ev in events:
            if ev.get("isCancelled"):
                continue
            subject = (ev.get("subject") or "(no subject)").strip()
            attendees = [
                a.get("emailAddress", {}).get("name")
                for a in ev.get("attendees", [])
            ]
            attendees = [n for n in attendees if n]
            is_online = bool(ev.get("isOnlineMeeting"))
            start_dt = (ev.get("start") or {}).get("dateTime") or now.isoformat()
            organizer = (
                (ev.get("organizer") or {}).get("emailAddress") or {}
            ).get("name")
            location = (ev.get("location") or {}).get("displayName")

            shown = attendees[:10]
            summary = ""
            if attendees:
                summary = f"참석자: {', '.join(shown)}"
                if len(attendees) > len(shown):
                    summary += f" 외 {len(attendees) - len(shown)}명"
            if organizer:
                summary = (summary + " | " if summary else "") + f"주최: {organizer}"

            activities.append(
                {
                    "timestamp": start_dt,
                    "action": "meeting",
                    "file_path": f"{'Teams 회의' if is_online else '회의'}: {subject}",
                    "file_type": "calendar",
                    "source": "teams",
                    "details": json.dumps(
                        {
                            "subject": subject,
                            "attendees": attendees[:15],
                            "attendee_count": len(attendees),
                            "organizer": organizer,
                            "is_online_meeting": is_online,
                            "location": location,
                            "summary": summary,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        return activities

    def _message_to_activity(self, msg, chat_title, me_name=None):
        """Graph message 객체를 activities 테이블 포맷으로 변환"""
        sender = ((msg.get("from") or {}).get("user") or {}).get("displayName") or "Unknown"
        body_html = (msg.get("body") or {}).get("content") or ""
        text = re.sub(r"<[^>]+>", " ", body_html)
        text = " ".join(text.split())
        if not sender and not text:
            return None

        return {
            "timestamp": msg.get("createdDateTime", datetime.now().isoformat()),
            "action": "message",
            "file_path": f"Teams 채팅: {chat_title} - {sender}",
            "file_type": "teams_message",
            "source": "teams",
            "details": json.dumps(
                {
                    "chat": chat_title,
                    "sender": sender,
                    "text": text[:300],
                    "message_type": msg.get("messageType"),
                    # 주간보고서에서 '내가 보낸 메시지'만 골라 요약할 때 사용
                    "from_me": bool(me_name and sender == me_name),
                },
                ensure_ascii=False,
            ),
        }

    def save_to_database(self, activities):
        """수집 결과를 DB에 저장"""
        if not activities:
            return 0
        with ActivityDatabase(self.db_path) as db:
            return db.add_activities(activities)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Teams activity collector")
    parser.add_argument(
        "--login",
        action="store_true",
        help="디바이스 코드 로그인 실행 (최초 1회 또는 토큰 만료 시)",
    )
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    if args.login:
        device_code_login()
        return

    collector = TeamsCollector()
    if not collector.enabled:
        print("No token file. Run: python teams_collector.py --login")
        return

    activities = collector.collect_all_teams_activity(days=args.days)
    print(f"Collected {len(activities)} Teams activities")
    for a in activities[:10]:
        print(f"  {a['timestamp']} | {a['file_path']}")


if __name__ == "__main__":
    main()
