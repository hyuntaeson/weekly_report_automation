#!/usr/bin/env python3
"""
일일 할 일 저장소 (activities.db의 todo_items 테이블) — 화면·md·17:00 점검의 기준.

- 한 날짜의 목록(list_date)에 '오늘'·'내일' 묶음(bucket)으로 항목이 들어간다
- 상태: open(미완료) / in_progress(진행 중) / done(완료) / removed(제외)
  완료 방법(done_by): manual(사용자 체크) / auto(17:00 자동 판정) / schedule(일정 종료)
  — 사용자가 체크한 완료는 자동 판정이 덮어쓰지 않는다 (대면·전화로 처리한 일)
- 제외는 삭제하지 않고 사유와 함께 상태로 남긴다 (되돌리기·추출 개선에 사용)
- 이월: 전날 목록의 미완료·진행 중 항목을 새 목록으로 복사(carry_count +1, origin_id로 연결).
  17:00에 들어온 '새 요청'은 미완료가 아니라 내일 할 일이므로 이월 횟수를 늘리지 않는다
- 실행 기록(todo_runs): 그 날짜에 09:00 추출(am)·17:00 점검(pm)을 했는지 — 이월 항목이 먼저 들어와 있어도
  아침 추출이 건너뛰어지지 않도록 '항목이 있나'가 아니라 '추출했나'로 판단
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime

from weekly_report import paths

OPEN_STATES = ("open", "in_progress")
SCHEMA = """
CREATE TABLE IF NOT EXISTS todo_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_date TEXT NOT NULL,
    bucket TEXT NOT NULL DEFAULT 'today',
    task TEXT NOT NULL,
    kind TEXT,
    requester TEXT,
    due TEXT,
    priority TEXT,
    source_label TEXT,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    done_by TEXT,
    done_at TEXT,
    removed_reason TEXT,
    carry_count INTEGER NOT NULL DEFAULT 0,
    origin_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_todo_list_date ON todo_items(list_date);
CREATE TABLE IF NOT EXISTS todo_runs (
    list_date TEXT NOT NULL,
    kind TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (list_date, kind)
);
"""
# 나중에 생긴 열 — 예전 DB에 없으면 추가
LATE_COLUMNS = {"progress_note": "TEXT", "checked_at": "TEXT"}
FIELDS = ("task", "kind", "requester", "due", "priority", "source_label", "bucket")


def _now():
    return datetime.now().isoformat(timespec="seconds")


class TodoStore:
    def __init__(self, db_path=paths.DB_PATH):
        self.db_path = db_path
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            have = {r[1] for r in conn.execute("PRAGMA table_info(todo_items)")}
            for col, kind in LATE_COLUMNS.items():
                if col not in have:
                    conn.execute(f"ALTER TABLE todo_items ADD COLUMN {col} {kind}")
            conn.commit()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row(row):
        item = dict(row)
        item["evidence"] = json.loads(item.get("evidence") or "[]")
        return item

    # ---------- 조회 ----------

    def list_for(self, list_date, include_removed=False):
        """그 날짜 목록 — 오늘·내일 순, 같은 묶음 안에서는 들어온 순"""
        sql = "SELECT * FROM todo_items WHERE list_date = ?" + ("" if include_removed else " AND status != 'removed'")
        with closing(self._connect()) as conn:
            rows = conn.execute(sql + " ORDER BY CASE bucket WHEN 'today' THEN 0 ELSE 1 END, id", (list_date,)).fetchall()
        return [self._row(r) for r in rows]

    def has_list(self, list_date):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT 1 FROM todo_items WHERE list_date = ? LIMIT 1", (list_date,)).fetchone() is not None

    def get(self, item_id):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM todo_items WHERE id = ?", (item_id,)).fetchone()
        return self._row(row) if row else None

    def mark_run(self, list_date, kind):
        """kind: 'am'(09:00 추출) / 'pm'(17:00 점검)"""
        with closing(self._connect()) as conn:
            conn.execute("INSERT OR REPLACE INTO todo_runs VALUES (?, ?, ?)", (list_date, kind, _now()))
            conn.commit()

    def has_run(self, list_date, kind):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT 1 FROM todo_runs WHERE list_date = ? AND kind = ?",
                                (list_date, kind)).fetchone() is not None

    def run_at(self, list_date, kind):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT at FROM todo_runs WHERE list_date = ? AND kind = ?", (list_date, kind)).fetchone()
        return row[0] if row else None

    def latest_list_before(self, list_date):
        """list_date 이전 가장 최근 목록 날짜 (이월 원본)"""
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT MAX(list_date) FROM todo_items WHERE list_date < ?", (list_date,)).fetchone()
        return row[0] if row and row[0] else None

    # ---------- 쓰기 ----------

    def add_items(self, list_date, items):
        """items: [{"task", "kind", "requester", "due", "priority", "source_label", "bucket", "evidence": [...],
        "carry_count", "origin_id"}] → 새 id 목록"""
        now, ids = _now(), []
        with closing(self._connect()) as conn:
            for item in items:
                cur = conn.execute(
                    "INSERT INTO todo_items (list_date, bucket, task, kind, requester, due, priority, source_label, "
                    "evidence, carry_count, origin_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (list_date, item.get("bucket") or "today", item["task"], item.get("kind"), item.get("requester"),
                     item.get("due"), item.get("priority"), item.get("source_label"),
                     json.dumps(item.get("evidence") or [], ensure_ascii=False),
                     int(item.get("carry_count") or 0), item.get("origin_id"), now, now))
                ids.append(cur.lastrowid)
            conn.commit()
        return ids

    def _update(self, item_id, **fields):
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with closing(self._connect()) as conn:
            conn.execute(f"UPDATE todo_items SET {cols} WHERE id = ?", (*fields.values(), item_id))
            conn.commit()

    def set_done(self, item_id, done, by="manual"):
        """체크(완료)·체크 해제(미완료). 사용자 체크가 아닌 자동 판정은 사용자가 이미 체크한 항목을 바꾸지 않는다."""
        item = self.get(item_id)
        if not item:
            return
        if by != "manual" and item.get("done_by") == "manual":
            return
        if done:
            self._update(item_id, status="done", done_by=by, done_at=_now())
        else:
            self._update(item_id, status="open", done_by=None, done_at=None)

    def set_status(self, item_id, status, by="auto", note=None):
        """17:00 자동 판정용 (완료·진행 중·미착수 + 판정 근거) — 사용자 체크·제외 항목은 건드리지 않음"""
        item = self.get(item_id)
        if item and item.get("done_by") != "manual" and item["status"] != "removed":
            self._update(item_id, status=status, done_by=by if status == "done" else None,
                         done_at=_now() if status == "done" else None, progress_note=note, checked_at=_now())

    def remove(self, item_id, reason):
        self._update(item_id, status="removed", removed_reason=reason)

    def restore(self, item_id):
        self._update(item_id, status="open", removed_reason=None)

    def delete_untouched(self, list_date):
        """다시 추출할 때 — 사용자가 손대지 않은(미완료·자동 생성) 항목만 지운다. 체크·제외한 항목과 이월 항목은 남김."""
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM todo_items WHERE list_date = ? AND status = 'open' AND carry_count = 0", (list_date,))
            conn.commit()

    def carry_over(self, from_date, to_date):
        """from_date 목록의 미완료·진행 중 항목을 to_date 목록 '오늘'로 이월 (이미 이월한 건 건너뜀). 반환: 새 id 목록"""
        with closing(self._connect()) as conn:
            done_origins = {r[0] for r in conn.execute(
                "SELECT origin_id FROM todo_items WHERE list_date = ? AND origin_id IS NOT NULL", (to_date,))}
        # 일정은 옮기지 않음 — 매일 아침 달력에서 오늘·내일 회의를 다시 읽는다
        items = [i for i in self.list_for(from_date) if i["status"] in OPEN_STATES and i["id"] not in done_origins
                 and i.get("kind") != "일정"]
        moved = []
        for i in items:
            # '내일' 묶음(내일 할 일·17:00 새 요청)은 미완료가 아니라 예정대로 넘어가는 것 → 이월 횟수 그대로
            planned = i.get("bucket") == "tomorrow"
            when = from_date[5:].replace("-", "/")
            moved.append({
                **{k: i.get(k) for k in FIELDS}, "bucket": "today",
                "kind": ("요청" if i.get("kind") == "새 요청" else i.get("kind")) if planned else "이월",
                "source_label": (i.get("source_label") if planned else
                                 f"{when} 목록에서 미완료 → 이월 · {i.get('source_label') or ''}".rstrip(" ·")),
                "evidence": i.get("evidence"),
                "carry_count": int(i.get("carry_count") or 0) + (0 if planned else 1),
                "origin_id": i["id"],
            })
        return self.add_items(to_date, moved)
