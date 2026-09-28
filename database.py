#!/usr/bin/env python3
"""
Database module for storing file activity data
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path


class ActivityDatabase:
    """SQLite database for file activity tracking"""
    
    def __init__(self, db_path='data/activities.db'):
        self.db_path = db_path
        self.conn = None
        self._ensure_db_directory()
        self._connect()
        self._migrate_database()
        self._create_tables()
    
    def _ensure_db_directory(self):
        """Ensure database directory exists"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
    
    def _connect(self):
        """Connect to database"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
    
    def _migrate_database(self):
        """Migrate database to new schema"""
        cursor = self.conn.cursor()
        
        try:
            # Check if activities table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='activities'")
            table_exists = cursor.fetchone()
            
            if table_exists:
                # Check if source column exists
                cursor.execute("PRAGMA table_info(activities)")
                columns = [row[1] for row in cursor.fetchall()]
                
                if 'source' not in columns:
                    print("Migrating database: adding source column...")
                    cursor.execute('ALTER TABLE activities ADD COLUMN source TEXT DEFAULT "filesystem"')
                    self.conn.commit()
                
                if 'details' not in columns:
                    print("Migrating database: adding details column...")
                    cursor.execute('ALTER TABLE activities ADD COLUMN details TEXT')
                    self.conn.commit()

                self._deduplicate_activities(cursor)
        except Exception as e:
            print(f"Migration error (may not be critical): {e}")

    def _deduplicate_activities(self, cursor):
        """같은 (timestamp, action, file_path, source) 조합의 중복 활동을 정리하고,
        이후 저장 시 재중복되지 않도록 UNIQUE 인덱스를 건다."""
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_unique_activity'"
        )
        if cursor.fetchone():
            return  # 이미 정리 및 인덱스 생성 완료

        cursor.execute("""
            DELETE FROM activities
            WHERE id NOT IN (
                SELECT MIN(id) FROM activities
                GROUP BY timestamp, action, file_path, source
            )
        """)
        removed = cursor.rowcount
        if removed:
            print(f"Migrating database: removed {removed} duplicate activities...")

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_activity
            ON activities(timestamp, action, file_path, source)
        """)
        self.conn.commit()
    
    def _create_tables(self):
        """Create database tables"""
        cursor = self.conn.cursor()
        
        # Main activities table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT,
                source TEXT DEFAULT 'filesystem',
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Weekly summary table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weekly_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL,
                week_end TEXT NOT NULL,
                summary_data TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(week_start, week_end)
            )
        ''')
        
        # File type statistics
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_type TEXT NOT NULL,
                action TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                date TEXT NOT NULL,
                UNIQUE(file_type, action, date)
            )
        ''')

        # 활동 임베딩 벡터 저장 — 주간 데이터 누적으로 유사 작업 검색을 가능하게.
        # activity_key = "timestamp|action|file_path|source" (activities UNIQUE 키와 동일 조합)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity_embeddings (
                activity_key TEXT PRIMARY KEY,
                text TEXT,
                vector TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        self.conn.commit()
    
    def add_activity(self, activity):
        """Add a single activity to database. 같은 timestamp/action/file_path/source
        조합이 이미 있으면 details(요약 등)를 최신 값으로 갱신한다 (단순 무시하면
        예전에 요약 없이 저장된 행이 영영 갱신되지 않아 캐시가 항상 미스남)."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO activities (timestamp, action, file_path, file_type, source, details)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(timestamp, action, file_path, source) DO UPDATE SET
                file_type = excluded.file_type,
                details = excluded.details
        ''', (
            activity['timestamp'],
            activity['action'],
            activity['file_path'],
            activity.get('file_type', 'unknown'),
            activity.get('source', 'filesystem'),
            activity.get('details', None)
        ))
        self.conn.commit()
        return cursor.lastrowid

    def add_activities(self, activities):
        """Add multiple activities to database (중복이면 details를 최신 값으로 갱신)"""
        cursor = self.conn.cursor()
        for activity in activities:
            cursor.execute('''
                INSERT INTO activities (timestamp, action, file_path, file_type, source, details)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(timestamp, action, file_path, source) DO UPDATE SET
                    file_type = excluded.file_type,
                    details = excluded.details
            ''', (
                activity['timestamp'],
                activity['action'],
                activity['file_path'],
                activity.get('file_type', 'unknown'),
                activity.get('source', 'filesystem'),
                activity.get('details', None)
            ))
        self.conn.commit()
        return len(activities)
    
    @staticmethod
    def activity_key(activity):
        """activities UNIQUE 인덱스와 동일한 조합의 임베딩 캐시 키"""
        return "|".join(
            str(activity.get(k) or "")
            for k in ("timestamp", "action", "file_path", "source")
        )

    def get_embeddings(self, keys):
        """activity_key 목록에 해당하는 저장된 임베딩 벡터를 dict로 반환"""
        if not keys:
            return {}
        cursor = self.conn.cursor()
        placeholders = ",".join("?" for _ in keys)
        rows = cursor.execute(
            f"SELECT activity_key, text, vector FROM activity_embeddings "
            f"WHERE activity_key IN ({placeholders})",
            keys,
        ).fetchall()
        return {
            row["activity_key"]: (row["text"], json.loads(row["vector"]))
            for row in rows
        }

    def save_embeddings(self, items):
        """(activity_key, text, vector) 목록 저장"""
        cursor = self.conn.cursor()
        cursor.executemany(
            "INSERT OR REPLACE INTO activity_embeddings "
            "(activity_key, text, vector) VALUES (?, ?, ?)",
            [(k, t, json.dumps(v)) for k, t, v in items],
        )
        self.conn.commit()

    def get_summary_cache(self, source):
        """이미 저장된 활동들의 (timestamp, action, file_path) -> summary 매핑을 반환.

        수집기(OutlookCollector/ConfluenceCollector 등)가 재수집 시 이미
        요약된 항목을 또 LLM에 보내지 않고 재사용할 수 있도록 하기 위함.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT timestamp, action, file_path, details FROM activities WHERE source = ?",
            (source,),
        )
        cache = {}
        for row in cursor.fetchall():
            details_raw = row["details"]
            if not details_raw:
                continue
            try:
                details = json.loads(details_raw)
            except (TypeError, ValueError):
                continue
            summary = details.get("summary") if isinstance(details, dict) else None
            if summary:
                cache[(row["timestamp"], row["action"], row["file_path"])] = summary
        return cache

    def get_activities_by_date_range(self, start_date, end_date):
        """Get activities within a date range"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM activities 
            WHERE date(timestamp) BETWEEN ? AND ?
            ORDER BY timestamp
        ''', (start_date, end_date))
        return [dict(row) for row in cursor.fetchall()]
    
    def get_activities_by_week(self, year, week):
        """Get activities for a specific week"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM activities 
            WHERE strftime('%Y', timestamp) = ? AND strftime('%W', timestamp) = ?
            ORDER BY timestamp
        ''', (str(year), str(week).zfill(2)))
        return [dict(row) for row in cursor.fetchall()]
    
    def get_file_type_stats(self, start_date=None, end_date=None):
        """Get statistics by file type"""
        cursor = self.conn.cursor()
        if start_date and end_date:
            cursor.execute('''
                SELECT file_type, action, COUNT(*) as count
                FROM activities
                WHERE date(timestamp) BETWEEN ? AND ?
                GROUP BY file_type, action
                ORDER BY count DESC
            ''', (start_date, end_date))
        else:
            cursor.execute('''
                SELECT file_type, action, COUNT(*) as count
                FROM activities
                GROUP BY file_type, action
                ORDER BY count DESC
            ''')
        return [dict(row) for row in cursor.fetchall()]
    
    def get_daily_activity_count(self, days=7):
        """Get daily activity count for last N days"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT date(timestamp) as date, COUNT(*) as count
            FROM activities
            WHERE date(timestamp) >= date('now', '-' || ? || ' days')
            GROUP BY date(timestamp)
            ORDER BY date DESC
        ''', (str(days),))
        return [dict(row) for row in cursor.fetchall()]
    
    def save_weekly_summary(self, week_start, week_end, summary_data):
        """Save weekly summary to database"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO weekly_summaries (week_start, week_end, summary_data)
            VALUES (?, ?, ?)
        ''', (week_start, week_end, json.dumps(summary_data, ensure_ascii=False)))
        self.conn.commit()
    
    def get_weekly_summary(self, week_start, week_end):
        """Get weekly summary from database"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT summary_data FROM weekly_summaries
            WHERE week_start = ? AND week_end = ?
        ''', (week_start, week_end))
        row = cursor.fetchone()
        if row:
            return json.loads(row['summary_data'])
        return None
    
    def get_all_weeks(self):
        """Get all weeks with summaries"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT week_start, week_end, created_at
            FROM weekly_summaries
            ORDER BY week_start DESC
        ''')
        return [dict(row) for row in cursor.fetchall()]
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Utility functions
def get_week_start_end(date=None):
    """Get the start and end of the week for a given date"""
    if date is None:
        date = datetime.now()
    else:
        date = datetime.strptime(date, '%Y-%m-%d')
    
    # Get Monday (start of week)
    start = date - timedelta(days=date.weekday())
    # Get Sunday (end of week)
    end = start + timedelta(days=6)
    
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')