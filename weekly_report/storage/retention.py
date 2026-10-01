#!/usr/bin/env python3
"""
저장소 보관 정책 — 활동 벡터는 최근 N주만, 지난 주는 주간 요약 벡터로 남긴다.

POS의 거래 상세(보관 기간 후 정리) → 일·월 집계 테이블(영구)과 같은 구조:
  - 원본 활동 텍스트(SQLite activities)  : 지우지 않음 — 가볍고, 상세 근거·재임베딩 원본
  - 활동 벡터(Qdrant activities)         : 보관 기간(Settings, 기본 12주)이 지난 주는 삭제
  - 주간 요약 벡터(Qdrant week_summaries): 삭제 전에 그 주의 STEP 2 요약을 임베딩해 영구 보관

요약을 저장하지 못한 주(임베딩 실패 등)는 벡터를 지우지 않고 다음 정리 때 다시 시도한다.
Qdrant 로컬 모드는 열 때 벡터 전체를 메모리로 읽어서, 벡터 수에 비례해 보고서 생성이 느려진다
(측정: 1만 개당 약 3.6초, 디스크 약 290MB).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import date, datetime, timedelta

from qdrant_client.models import FieldCondition, Filter, Range

from weekly_report import paths
from weekly_report.storage.vector_store import SUMMARY_COLLECTION, ActivityVectorStore, WeekSummaryStore

RETENTION_CHOICES = (8, 12, 26, 52, 78, 104)  # 주
DEFAULT_RETENTION_WEEKS = 12
AUTO_INTERVAL_DAYS = 7  # 보고서 생성 후 자동 정리는 주 1회만
SECONDS_PER_VECTOR = 0.00036  # 저장소 여는 시간 추정 (5천·1만5천 개 벤치마크 기준)
MB_PER_VECTOR = 0.029


def _monday(d):
    return d - timedelta(days=d.weekday())


def _day_ts(d):
    return datetime.combine(d, datetime.min.time()).timestamp()


def _size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs)


# ---------- 사용량 ----------

def storage_usage(db_path=paths.DB_PATH):
    """파일 크기만 보는 가벼운 사용량 (VectorDB는 열지 않음). 단위: 바이트"""
    usage = {
        "data": _size(paths.DATA_DIR) if os.path.exists(paths.DATA_DIR) else 0,
        "db": _size(db_path) if os.path.exists(db_path) else 0,
        "vectors": _size(paths.QDRANT_DIR) if os.path.exists(paths.QDRANT_DIR) else 0,
        "llm_cache": _size(paths.LLM_CACHE) if os.path.exists(paths.LLM_CACHE) else 0,
        "legacy_rows": 0,
    }
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            if _has_legacy_table(conn):
                usage["legacy_rows"] = conn.execute("SELECT COUNT(*) FROM activity_embeddings").fetchone()[0]
        finally:
            conn.close()
    return usage


def vector_stats(store=None, today=None):
    """VectorDB를 실제로 열어 개수·여는 시간·주간 증가량을 잰다 (수 초 걸릴 수 있음)"""
    store = store or ActivityVectorStore()
    today = today or date.today()
    started = time.time()
    with store._client() as client:  # 열 때마다 전체를 읽으므로 한 번만 열어 모두 센다
        open_seconds = time.time() - started
        count = client.count(store.collection, exact=True).count
        since = lambda days: Filter(must=[FieldCondition(
            key="ts", range=Range(gte=_day_ts(today - timedelta(days=days))))])
        # 수집 소스가 늘면 최근 주가 더 많으므로 4주 평균과 최근 7일 중 큰 값 (예상을 낮게 잡지 않도록)
        weekly_rate = max(client.count(store.collection, exact=True, count_filter=since(28)).count / 4,
                          client.count(store.collection, exact=True, count_filter=since(7)).count)
        summary_weeks = (client.count(SUMMARY_COLLECTION, exact=True).count
                         if client.collection_exists(SUMMARY_COLLECTION) else 0)
    return {
        "count": count,
        "open_seconds": open_seconds,
        "weekly_rate": weekly_rate,
        "summary_weeks": summary_weeks,
    }


def estimate(weeks, weekly_rate):
    """보관 기간을 채웠을 때 예상 벡터 수·여는 시간(초)·크기(MB)"""
    n = int(weeks * weekly_rate)
    return {"vectors": n, "open_seconds": n * SECONDS_PER_VECTOR, "mb": n * MB_PER_VECTOR}


# ---------- 정리 ----------

def week_summary_text(weekly_data):
    """보고서 weekly_data → 주간 요약 벡터에 넣을 텍스트 (STEP 2 핵심 요약 + 주제 질의 요약)"""
    lines = [f"- {b}" for b in weekly_data.get("week_summary") or []]
    for section in weekly_data.get("rag_sections") or []:
        lines += [f"- {section['topic']}: {b}" for b in section.get("bullets", [])]
    if not lines:
        return ""
    return f"[{weekly_data['week_start']} ~ {weekly_data['week_end']}] 주간 업무 요약\n" + "\n".join(lines)


def _stored_week_summary(db_path, monday):
    """weekly_summaries에 저장된 보고서 중 이 주(월~일)와 4일 이상 겹치는 것의 요약 텍스트"""
    sunday = monday + timedelta(days=6)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT week_start, week_end, summary_data FROM weekly_summaries ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    for start, end, data in rows:
        try:
            s, e = date.fromisoformat(start), date.fromisoformat(end)
        except (TypeError, ValueError):
            continue
        if (min(e, sunday) - max(s, monday)).days + 1 >= 4:
            text = week_summary_text(json.loads(data))
            if text:
                return text
    return ""


def _generate_week_summary(monday):
    """보고서를 만든 적 없는 주 — 원본 활동으로 STEP 2 핵심 요약만 만든다 (LLM 실패 시 규칙 기반)"""
    from weekly_report.report.generator import ReportGenerator

    gen = ReportGenerator()
    start, end = monday.isoformat(), (monday + timedelta(days=6)).isoformat()
    sections = gen.build_program_sections(gen.fetch_week_activities(start, end))
    if not sections:
        return ""
    bullets = gen._summarize_week(sections) or gen._fallback_week_summary(sections)
    return week_summary_text({"week_start": start, "week_end": end, "week_summary": bullets})


def _embed(text):
    from weekly_report.ai.clusterer import ActivityClusterer

    vectors = ActivityClusterer().embed([text])
    return vectors[0] if vectors else None


def apply_retention(weeks, db_path=paths.DB_PATH, store=None, summaries=None, today=None,
                    summary_for_week=None, embed=_embed, progress=None,
                    cache_path=paths.LLM_CACHE):
    """보관 기간(weeks)이 지난 주의 활동 벡터를 요약 저장 후 삭제.
    summary_for_week(monday) → 요약 텍스트 (기본: 저장된 보고서 → 없으면 새로 생성).
    반환: {"cutoff", "deleted", "summarized", "kept"(요약 실패로 남긴 주), "legacy_dropped"}"""
    store = store or ActivityVectorStore()
    summaries = summaries or WeekSummaryStore(path=store.path)
    today = today or date.today()
    summary_for_week = summary_for_week or (
        lambda monday: _stored_week_summary(db_path, monday) or _generate_week_summary(monday))
    report = lambda msg: progress and progress(msg)

    # 이번 주를 포함해 weeks주는 남김 — 주 단위로 자르므로 정리 직후에도 weeks주 전체가 검색됨
    cutoff = _monday(today) - timedelta(weeks=weeks - 1)
    old_weeks = sorted({_monday(datetime.fromtimestamp(ts).date())
                        for ts in store.timestamps_before(_day_ts(cutoff))})
    have = summaries.week_starts() if old_weeks else set()
    result = {"cutoff": cutoff.isoformat(), "deleted": 0, "summarized": [], "kept": []}
    for monday in old_weeks:
        week_start = monday.isoformat()
        if week_start not in have:
            report(f"{week_start} 주간 요약 저장 중")
            text = summary_for_week(monday)
            if text:
                vector = embed(text)
                if not vector:  # 요약을 못 남기면 지우지 않는다 — 다음 정리 때 재시도
                    result["kept"].append(week_start)
                    continue
                summaries.upsert_week(week_start, (monday + timedelta(days=6)).isoformat(), text, vector)
                result["summarized"].append(week_start)
            # text가 비면 보고서에 남을 활동이 없는 주(노이즈만) — 원본은 SQLite에 있으니 그냥 정리
        result["deleted"] += store.delete_range(_day_ts(monday), _day_ts(monday + timedelta(days=7)))
    result["legacy_dropped"] = drop_legacy_embeddings(db_path)
    expire_llm_cache(_day_ts(cutoff), cache_path)
    return result


def _has_legacy_table(conn):
    return bool(conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='activity_embeddings'").fetchone())


def drop_legacy_embeddings(db_path=paths.DB_PATH):
    """Qdrant 이전 후 안 쓰는 SQLite activity_embeddings 삭제 + VACUUM. 반환: 삭제한 행 수"""
    if not os.path.exists(db_path):
        return 0
    conn = sqlite3.connect(db_path)
    try:
        if not _has_legacy_table(conn):
            return 0
        rows = conn.execute("SELECT COUNT(*) FROM activity_embeddings").fetchone()[0]
        conn.execute("DROP TABLE activity_embeddings")
        conn.commit()
        try:
            conn.execute("VACUUM")  # 다른 연결이 쓰는 중이면 실패 — 다음 정리 때 공간 회수
        except sqlite3.OperationalError as e:
            print(f"Warning: VACUUM skipped: {e}")
        return rows
    finally:
        conn.close()


def expire_llm_cache(before_ts, cache_path=paths.LLM_CACHE):
    """보관 기간 이전에 만든 LLM 응답 캐시 삭제 (지난 주 보고서 분석 결과라 다시 쓰일 일이 드묾)"""
    if not os.path.exists(cache_path):
        return 0
    conn = sqlite3.connect(cache_path)
    try:
        n = conn.execute("DELETE FROM llm_cache WHERE created < ?", (before_ts,)).rowcount
        conn.commit()
        if n:
            conn.execute("VACUUM")
        return n
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


# ---------- 자동 실행 ----------

def _load_state(path=paths.RETENTION_STATE):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def last_run(path=paths.RETENTION_STATE):
    return _load_state(path)


def run_retention(weeks, progress=None, state_path=paths.RETENTION_STATE, **kwargs):
    """정리 실행 + 실행 기록 저장"""
    result = apply_retention(weeks, progress=progress, **kwargs)
    state = {"last_run": datetime.now().isoformat(timespec="seconds"), "weeks": weeks, "result": result}
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    return result


def run_if_due(weeks, state_path=paths.RETENTION_STATE, **kwargs):
    """마지막 정리 후 AUTO_INTERVAL_DAYS 지났으면 실행 (보고서 생성 후 백그라운드 호출용). 안 돌면 None"""
    last = _load_state(state_path).get("last_run")
    if last:
        try:
            if datetime.now() - datetime.fromisoformat(last) < timedelta(days=AUTO_INTERVAL_DAYS):
                return None
        except ValueError:
            pass
    return run_retention(weeks, state_path=state_path, **kwargs)
