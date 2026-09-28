#!/usr/bin/env python3
"""
Microsoft Teams Activity Collector
Collects chat/channel activity via Microsoft Graph API.

사내 Azure AD 앱 등록이 막혀 있으면 config를 만들 수 없으므로
현재는 스텁 상태로 동작한다 (Devin 스텁과 같은 패턴):
config/teams_config.json 이 없거나 enabled=false이면 빈 리스트 반환.

자격증명이 확보되면 아래 형식의 config/teams_config.json을 만들면
별도 코드 수정 없이 바로 수집이 시작된다:

    {
        "enabled": true,
        "tenant_id": "...",
        "client_id": "...",
        "client_secret": "...",
        "user_id": "me 또는 user@domain"  // /me는 delegated 전용, client_credentials는 UPN
    }

필요 권한 (application permission, 관리자 동의 필요):
    - ChannelMessage.Read.All  (채널 메시지)
    - Chat.Read.All            (1:1/그룹 채팅)
    - Team.ReadBasic.All       (팀 목록)
"""

import json
import os
from datetime import datetime, timedelta

import requests

from database import ActivityDatabase

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


class TeamsCollector:
    """Microsoft Graph 기반 Teams 활동 수집기 (미설정 시 스텁)"""

    def __init__(self, db_path="data/activities.db", config_path="config/teams_config.json"):
        self.db_path = db_path
        self.config = self._load_config(config_path)
        self.enabled = bool(self.config.get("enabled"))
        self._access_token = None
        self._token_expires = None

    def _load_config(self, config_path):
        if not os.path.exists(config_path):
            return {"enabled": False}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: Failed to load Teams config: {e}")
            return {"enabled": False}

    # ---------- 인증 ----------

    def _acquire_token(self):
        """client_credentials 플로우로 액세스 토큰 발급 (application permission용)"""
        if self._access_token and self._token_expires and datetime.now() < self._token_expires:
            return self._access_token

        resp = requests.post(
            TOKEN_URL.format(tenant=self.config["tenant_id"]),
            data={
                "grant_type": "client_credentials",
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._access_token = payload["access_token"]
        self._token_expires = datetime.now() + timedelta(
            seconds=int(payload.get("expires_in", 3600)) - 60
        )
        return self._access_token

    def _graph_get(self, path, params=None):
        token = self._acquire_token()
        resp = requests.get(
            f"{GRAPH_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # ---------- 수집 ----------

    def collect_all_teams_activity(self, days=7):
        """Teams 채널/채팅 활동 수집. 미설정 상태면 빈 리스트(스텁)."""
        if not self.enabled:
            return []

        activities = []
        try:
            activities.extend(self._collect_channel_messages(days))
            activities.extend(self._collect_chat_messages(days))
        except Exception as e:
            print(f"Error collecting Teams activity: {e}")
        return activities

    def _collect_channel_messages(self, days):
        """참여 중인 팀의 채널 메시지 수집 (application permission 필요)"""
        since = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
        activities = []

        user_id = self.config.get("user_id", "me")
        teams = self._graph_get(f"/users/{user_id}/joinedTeams").get("value", [])

        for team in teams:
            try:
                channels = self._graph_get(
                    f"/teams/{team['id']}/channels"
                ).get("value", [])
            except Exception:
                continue

            for channel in channels:
                try:
                    messages = self._graph_get(
                        f"/teams/{team['id']}/channels/{channel['id']}/messages",
                        params={"$top": 50},
                    ).get("value", [])
                except Exception:
                    continue

                for msg in messages:
                    created = msg.get("createdDateTime", "")
                    if created < since:
                        continue
                    activities.append(self._message_to_activity(
                        msg, f"Teams 채널: {team.get('displayName')} / {channel.get('displayName')}"
                    ))
        return [a for a in activities if a]

    def _collect_chat_messages(self, days):
        """1:1/그룹 채팅 메시지 수집 (application permission 필요)"""
        since = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
        activities = []

        try:
            chats = self._graph_get(
                f"/users/{self.config.get('user_id', 'me')}/chats",
                params={"$top": 50},
            ).get("value", [])
        except Exception as e:
            print(f"Error listing Teams chats: {e}")
            return []

        for chat in chats:
            try:
                messages = self._graph_get(
                    f"/chats/{chat['id']}/messages",
                    params={"$top": 50},
                ).get("value", [])
            except Exception:
                continue

            for msg in messages:
                created = msg.get("createdDateTime", "")
                if created < since:
                    continue
                activities.append(self._message_to_activity(
                    msg, f"Teams 채팅: {chat.get('topic') or chat.get('chatType')}"
                ))
        return [a for a in activities if a]

    def _message_to_activity(self, msg, context):
        """Graph message 객체를 activities 테이블 포맷으로 변환"""
        body = (msg.get("body") or {}).get("content") or ""
        # HTML 태그 대충 제거 (메시지 본문은 contentType=text/html인 경우가 많음)
        import re
        body_text = re.sub(r"<[^>]+>", " ", body).strip()

        sender = ((msg.get("from") or {}).get("user") or {}).get("displayName") or "Unknown"

        return {
            "timestamp": msg.get("createdDateTime", datetime.now().isoformat()),
            "action": "message",
            "file_path": f"{context} - {sender}",
            "file_type": "teams_message",
            "source": "teams",
            "details": json.dumps(
                {
                    "sender": sender,
                    "context": context,
                    "text": body_text[:200],
                    "message_type": msg.get("messageType"),
                },
                ensure_ascii=False,
            ),
        } if sender or body_text else None

    def save_to_database(self, activities):
        """수집 결과를 DB에 저장"""
        if not activities:
            return 0
        with ActivityDatabase(self.db_path) as db:
            return db.add_activities(activities)


def main():
    """테스트 실행"""
    collector = TeamsCollector()
    print(f"Teams collector enabled: {collector.enabled}")
    activities = collector.collect_all_teams_activity(days=7)
    print(f"Collected {len(activities)} Teams activities")


if __name__ == "__main__":
    main()
