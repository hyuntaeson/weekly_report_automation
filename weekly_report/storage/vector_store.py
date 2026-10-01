#!/usr/bin/env python3
"""
활동 임베딩 VectorDB (Qdrant 로컬 모드 — 서버 없이 data/qdrant 폴더에 저장).

- 활동 1건 = 포인트 1개: 임베딩 벡터 + 메타데이터(소스·로컬 날짜·시각·Teams 발신자/채팅방)
- 메타데이터 필터 검색: 날짜 범위·소스·발신자 → RAG 질의 섹션, STEP 3(예상질문자 대화만 검색)의 기반
- 로컬 모드는 한 번에 한 프로세스만 폴더를 열 수 있어서, 작업마다 잠깐 열고 바로 닫는다

임베딩 자체는 사내 LiteLLM(text-embedding-3-large, 3072차원)로 activity_clusterer가 만든다.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, FieldCondition, Filter, FilterSelector, MatchAny, PointStruct, Range, VectorParams,
)

from weekly_report import paths
from weekly_report.common.timeutil import to_local_datetime

DEFAULT_PATH = paths.QDRANT_DIR
COLLECTION = "activities"
SUMMARY_COLLECTION = "week_summaries"  # 보관 기간이 지난 주의 STEP 2 요약 — 주당 1개, 영구 보관
VECTOR_SIZE = 3072  # text-embedding-3-large
# 로컬 모드는 같은 폴더를 동시에 두 클라이언트가 열 수 없음 — 보고서 분석 단계를 병렬로 돌릴 때 직렬화
_LOCK = threading.RLock()


def point_id(activity_key):
    """activity_key(timestamp|action|file_path|source) → 항상 같은 UUID (재업서트 시 덮어쓰기)"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, activity_key))


def activity_payload(activity, text):
    """검색 필터에 쓸 메타데이터. 날짜는 수집기마다 다른 시각 형식을 로컬 기준으로 통일."""
    from weekly_report.storage.database import ActivityDatabase

    details = activity.get("details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (TypeError, ValueError):
            details = {}
    details = details if isinstance(details, dict) else {}
    when = to_local_datetime(activity.get("timestamp"), activity.get("source"))
    return {
        "key": ActivityDatabase.activity_key(activity),
        "text": text,
        "source": activity.get("source") or "",
        "action": activity.get("action") or "",
        "file_path": str(activity.get("file_path") or "")[:300],
        "ts": when.timestamp() if when else 0.0,
        "date": when.strftime("%Y-%m-%d") if when else "",
        "sender": details.get("sender") or "",
        "chat": details.get("chat") or "",
    }


class ActivityVectorStore:
    def __init__(self, path=DEFAULT_PATH, collection=COLLECTION, vector_size=VECTOR_SIZE):
        self.path = path
        self.collection = collection
        self.vector_size = vector_size

    @contextmanager
    def _client(self):
        os.makedirs(self.path, exist_ok=True)
        with _LOCK:
            client = QdrantClient(path=self.path)
            try:
                if not client.collection_exists(self.collection):
                    client.create_collection(
                        self.collection,
                        vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
                    )
                yield client
            finally:
                client.close()

    def count(self):
        with self._client() as client:
            return client.count(self.collection, exact=True).count

    def get_vectors(self, keys):
        """activity_key 목록 → {key: (저장 당시 텍스트, 벡터)}. 없는 키는 빠짐."""
        if not keys:
            return {}
        with self._client() as client:
            points = client.retrieve(
                self.collection, ids=[point_id(k) for k in keys],
                with_payload=True, with_vectors=True,
            )
        return {p.payload["key"]: (p.payload.get("text", ""), list(p.vector)) for p in points}

    def upsert(self, items):
        """[(activity, text, vector)] 저장 (같은 활동이면 덮어씀)."""
        if not items:
            return 0
        points = [
            PointStruct(id=point_id(payload["key"]), vector=vector, payload=payload)
            for payload, vector in ((activity_payload(a, t), v) for a, t, v in items)
        ]
        with self._client() as client:
            client.upsert(self.collection, points=points)
        return len(points)

    def search(self, vector, limit=10, date_from=None, date_to=None, sources=None,
               sender_contains=None, min_score=0.0):
        """의미가 가까운 활동 검색. 날짜는 'YYYY-MM-DD'(로컬, 양끝 포함).
        sender_contains: Teams 표시 이름 일부 (예: '김영호') — 해당 발신자 메시지만.
        반환: [{"score", **payload}] 유사도 내림차순."""
        with self._client() as client:
            return self._query(client, vector, limit, date_from, date_to, sources, sender_contains, min_score)

    def search_many(self, requests):
        """여러 검색을 저장소를 한 번만 열어 처리 (열 때마다 전체 벡터를 읽어서 비쌈).
        requests: [{"vector": ..., 그 외 search()와 같은 인자}] → 결과 목록을 같은 순서로."""
        with self._client() as client:
            return [self._query(client, **r) for r in requests]

    def _query(self, client, vector, limit=10, date_from=None, date_to=None, sources=None,
               sender_contains=None, min_score=0.0):
        must = []
        if date_from or date_to:
            # Range는 숫자 전용 → 로컬 날짜를 epoch(ts)로 바꿔 거른다 (끝 날짜는 그날 끝까지)
            day = lambda d: datetime.strptime(d, "%Y-%m-%d").timestamp()
            must.append(FieldCondition(key="ts", range=Range(
                gte=day(date_from) if date_from else None,
                lt=day(date_to) + 86400 if date_to else None)))
        if sources:
            must.append(FieldCondition(key="source", match=MatchAny(any=list(sources))))
        # 발신자 부분 일치는 로컬 모드 전문 검색 인덱스 없이 후처리로 거른다
        fetch = limit * 5 if sender_contains else limit
        result = client.query_points(
            self.collection, query=vector, limit=fetch,
            query_filter=Filter(must=must) if must else None, with_payload=True,
        )
        hits = []
        for p in result.points:
            if p.score < min_score:
                continue
            if sender_contains and sender_contains not in (p.payload.get("sender") or ""):
                continue
            hits.append({"score": p.score, **p.payload})
            if len(hits) >= limit:
                break
        return hits

    def count_since(self, ts):
        """ts(epoch) 이후 활동 벡터 수 — 주간 증가량 추정용"""
        with self._client() as client:
            return client.count(self.collection, exact=True, count_filter=Filter(
                must=[FieldCondition(key="ts", range=Range(gte=ts))])).count

    def timestamps_before(self, ts):
        """ts(epoch) 이전 활동 벡터들의 ts 목록 (벡터는 읽지 않음) — 보관 기간 정리 대상 주 찾기"""
        found, offset = [], None
        flt = Filter(must=[FieldCondition(key="ts", range=Range(lt=ts))])
        with self._client() as client:
            while True:
                points, offset = client.scroll(
                    self.collection, scroll_filter=flt, limit=1000, offset=offset,
                    with_payload=["ts"], with_vectors=False,
                )
                found.extend(p.payload.get("ts", 0.0) for p in points)
                if offset is None:
                    return found

    def delete_range(self, ts_from, ts_to):
        """ts_from 이상 ts_to 미만 활동 벡터 삭제. 반환: 삭제 건수."""
        flt = Filter(must=[FieldCondition(key="ts", range=Range(gte=ts_from, lt=ts_to))])
        with self._client() as client:
            n = client.count(self.collection, exact=True, count_filter=flt).count
            if n:
                client.delete(self.collection, points_selector=FilterSelector(filter=flt))
        return n

    def migrate_from_sqlite(self, db_path):
        """예전 SQLite activity_embeddings 벡터를 이전 (다시 임베딩하지 않음).
        이미 Qdrant에 데이터가 있으면 아무것도 하지 않는다. 반환: 이전 건수."""
        if not os.path.exists(db_path) or self.count() > 0:
            return 0
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            if not conn.execute("SELECT name FROM sqlite_master WHERE name='activity_embeddings'").fetchone():
                return 0
            rows = conn.execute(
                "SELECT e.activity_key, e.text, e.vector, a.timestamp, a.action, a.file_path, a.source, a.details "
                "FROM activity_embeddings e LEFT JOIN activities a "
                "ON a.timestamp || '|' || a.action || '|' || a.file_path || '|' || a.source = e.activity_key"
            ).fetchall()
        finally:
            conn.close()
        items = []
        for r in rows:
            if r["timestamp"] is None:  # 원본 활동이 지워진 벡터는 메타데이터가 없어 건너뜀
                continue
            activity = {k: r[k] for k in ("timestamp", "action", "file_path", "source", "details")}
            items.append((activity, r["text"], json.loads(r["vector"])))
        for i in range(0, len(items), 256):
            self.upsert(items[i:i + 256])
        return len(items)


class WeekSummaryStore(ActivityVectorStore):
    """주간 요약 벡터 (같은 Qdrant 폴더의 별도 컬렉션, 주당 포인트 1개).
    활동 벡터는 보관 기간이 지나면 지우지만, 그 주의 요약은 여기 남겨 장기 질의에 쓴다."""

    def __init__(self, path=DEFAULT_PATH, collection=SUMMARY_COLLECTION, vector_size=VECTOR_SIZE):
        super().__init__(path, collection, vector_size)

    def week_starts(self):
        """요약이 저장된 주의 시작일('YYYY-MM-DD') 집합"""
        found, offset = set(), None
        with self._client() as client:
            while True:
                points, offset = client.scroll(
                    self.collection, limit=1000, offset=offset,
                    with_payload=["week_start"], with_vectors=False,
                )
                found.update(p.payload["week_start"] for p in points)
                if offset is None:
                    return found

    def upsert_week(self, week_start, week_end, text, vector):
        """같은 주는 덮어씀"""
        payload = {
            "week_start": week_start, "week_end": week_end, "text": text,
            "ts": datetime.strptime(week_start, "%Y-%m-%d").timestamp(),
        }
        with self._client() as client:
            client.upsert(self.collection, points=[PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"week|{week_start}")),
                vector=vector, payload=payload,
            )])

    def search(self, vector, limit=5, min_score=0.0):
        """의미가 가까운 주 검색. 반환: [{"score", "week_start", "week_end", "text", "ts"}]"""
        with self._client() as client:
            result = client.query_points(self.collection, query=vector, limit=limit, with_payload=True)
        return [{"score": p.score, **p.payload} for p in result.points if p.score >= min_score]
