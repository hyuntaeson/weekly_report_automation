#!/usr/bin/env python3
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportOptionalMemberAccess=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false
"""
Confluence Activity Collector
Collects recently created or modified Confluence pages from configured spaces
"""

import json
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests

from database import ActivityDatabase
from llm_summarizer import LLMSummarizer


class ConfluenceCollector:
    """Collector for Confluence page activities"""

    def __init__(
        self, db_path="data/activities.db", config_path="config/confluence_config.json"
    ):
        self.db_path = db_path
        self.config_path = config_path
        self.config = self._load_config()
        self.summarizer = LLMSummarizer()
        self.enabled = bool(self.config.get("enabled", False))
        self.base_url = str(self.config.get("base_url") or "").rstrip("/")
        self.auth_type = str(self.config.get("auth_type") or "bearer")
        self.personal_access_token = str(self.config.get("personal_access_token") or "")
        raw_space_keys = self.config.get("space_keys", [])
        self.space_keys = raw_space_keys if isinstance(raw_space_keys, list) else list()
        self.collection_interval_hours = int(
            self.config.get("collection_interval_hours") or 1
        )
        self.max_results_per_space = int(self.config.get("max_results_per_space") or 50)

    def _load_config(self):
        """Load Confluence configuration safely"""
        if not os.path.exists(self.config_path):
            print(f"Warning: Confluence config not found: {self.config_path}")
            return {"enabled": False}

        try:
            with open(self.config_path, "r", encoding="utf-8") as config_file:
                return json.load(config_file)
        except (OSError, json.JSONDecodeError) as error:
            print(f"Warning: Failed to load Confluence config: {error}")
            return {"enabled": False}

    def collect_all_confluence_activity(self, days=7):
        """설정된 space_keys 전체에 대해 최근 N일간 수정/생성된 페이지 활동 수집"""
        if not self.enabled:
            print("Warning: Confluence collection is disabled in config")
            return []

        if not self.personal_access_token:
            print("Warning: Confluence personal access token is not configured")
            return []

        if not self.base_url:
            print("Warning: Confluence base_url is not configured")
            return []

        if not self.space_keys:
            print("Warning: No Confluence space_keys configured")
            return []

        all_activities = []
        for space_key in self.space_keys:
            space_activities = self._fetch_space_activity(space_key, days)
            all_activities.extend(space_activities)

        print(
            f"Collected {len(all_activities)} Confluence activities from {len(self.space_keys)} spaces"
        )
        return all_activities

    def _search_content(self, cql_query, expand):
        """CQL search API 호출 공통 처리"""
        endpoint = f"{self.base_url}/rest/api/content/search"
        headers = {
            "Authorization": f"Bearer {self.personal_access_token}",
            "Accept": "application/json",
        }
        params = {
            "cql": cql_query,
            "expand": expand,
            "limit": self.max_results_per_space,
        }

        try:
            response = requests.get(
                endpoint, headers=headers, params=params, timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as error:
            print(f"Warning: Failed to fetch Confluence content: {error}")
            return None
        except ValueError as error:
            print(f"Warning: Invalid Confluence response: {error}")
            return None

    def _fetch_space_activity(self, space_key, days):
        """CQL search API 호출로 특정 space의 최근 생성/수정 페이지 및 본문 요약 조회"""
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        cql_query = f'space={space_key} AND lastmodified >= "{cutoff_date}"'
        payload = self._search_content(
            cql_query, expand="history,version,space,body.view.value"
        )
        if payload is None:
            return []

        summary_cache = self._get_summary_cache()
        activities = []
        for content in payload.get("results", []):
            activity = self._map_content_to_activity(content, summary_cache)
            if activity is not None:
                activities.append(activity)

        print(
            f"Collected {len(activities)} Confluence activities from space {space_key}"
        )
        return activities

    def _get_summary_cache(self):
        """이미 DB에 저장된 confluence 활동의 요약 캐시를 불러온다 (LLM 재호출 방지)"""
        try:
            with ActivityDatabase(self.db_path) as db:
                return db.get_summary_cache("confluence")
        except Exception as error:
            print(f"Warning: Failed to load Confluence summary cache: {error}")
            return {}

    def _map_content_to_activity(self, content, summary_cache=None):
        """Convert a Confluence content item to internal activity format"""
        version = self._as_dict(content.get("version"))
        history = self._as_dict(content.get("history"))
        space = self._as_dict(content.get("space"))
        links = self._as_dict(content.get("_links"))

        version_when = version.get("when")
        created_date = history.get("createdDate")
        if not version_when:
            return None

        title = str(content.get("title") or "Untitled")
        space_key = str(space.get("key") or "")
        space_name = str(space.get("name") or space_key or "Unknown Space")
        webui_link = str(links.get("webui") or "")
        page_url = (
            urljoin(f"{self.base_url}/", webui_link.lstrip("/"))
            if webui_link
            else self.base_url
        )
        version_number = int(version.get("number") or 0)
        author = str(self._as_dict(version.get("by")).get("displayName") or "Unknown")

        action = self._determine_action(version_number, created_date, version_when)
        file_path = f"{space_name}/{title}"

        cache_key = (str(version_when), action, file_path)
        cached_summary = (summary_cache or {}).get(cache_key)
        if cached_summary is not None:
            summary = cached_summary
        else:
            body = self._as_dict(content.get("body"))
            body_view = self._as_dict(body.get("view"))
            summary = self._summarize_html(str(body_view.get("value") or ""))

        return {
            "timestamp": str(version_when),
            "action": action,
            "file_path": file_path,
            "file_type": "confluence_page",
            "source": "confluence",
            "details": {
                "page_id": str(content.get("id") or ""),
                "space_key": space_key,
                "space_name": space_name,
                "author": author,
                "url": page_url,
                "version_number": version_number,
                "content_type": str(content.get("type") or "page"),
                "summary": summary,
            },
        }

    def _summarize_html(self, html, max_len=300):
        """Confluence 본문 HTML(body.view)을 요약. LiteLLM이 설정되어 있으면
        실제 AI 요약을 쓰고, 아니면 태그를 제거한 앞부분 발췌로 폴백."""
        if not html:
            return ""
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return ""

        llm_summary = self.summarizer.summarize(text)
        if llm_summary:
            return llm_summary

        if len(text) <= max_len:
            return text
        return text[:max_len].rstrip() + "..."

    def _determine_action(self, version_number, created_date, version_when):
        """Determine whether a page was created or modified"""
        if version_number == 1:
            return "confluence_created"

        created_dt = self._parse_datetime(created_date)
        modified_dt = self._parse_datetime(version_when)
        if (
            created_dt is not None
            and modified_dt is not None
            and created_dt == modified_dt
        ):
            return "confluence_created"

        return "confluence_modified"

    def _parse_datetime(self, value):
        """Parse Confluence datetime strings safely"""
        if not value:
            return None

        try:
            normalized_value = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized_value)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            print(f"Warning: Failed to parse Confluence datetime: {value}")
            return None

    def _as_dict(self, value):
        """Return dict when value is dict, otherwise empty dict"""
        return value if isinstance(value, dict) else {}

    def save_to_database(self, activities):
        """Save collected Confluence activities to database"""
        prepared_activities = []
        for activity in activities:
            activity_copy = activity.copy()
            if isinstance(activity_copy.get("details"), dict):
                activity_copy["details"] = json.dumps(
                    activity_copy["details"], ensure_ascii=False
                )
            prepared_activities.append(activity_copy)

        with ActivityDatabase(self.db_path) as db:
            db.add_activities(prepared_activities)

        return len(prepared_activities)


def main():
    """Test Confluence collector"""
    print("Testing Confluence collector...")
    collector = ConfluenceCollector()
    activities = collector.collect_all_confluence_activity(days=7)
    print(f"Collected {len(activities)} Confluence activities")

    if activities:
        saved_count = collector.save_to_database(activities)
        print(f"Saved {saved_count} Confluence activities to database")
        print("\nSample Confluence activities:")
        for activity in activities[:3]:
            print(
                f"  {activity['timestamp']} | {activity['action']} | {activity['file_path']}"
            )
    else:
        print("No Confluence activities collected")


if __name__ == "__main__":
    main()
