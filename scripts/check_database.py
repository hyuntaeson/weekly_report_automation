#!/usr/bin/env python3
"""
Check database contents
"""

import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)  # 상대 경로(config/, data/, test_reports/)는 프로젝트 루트 기준

from weekly_report.storage.database import ActivityDatabase

def main():
    db_path = "data/test_activities.db"
    
    with ActivityDatabase(db_path) as db:
        print("=== Database Contents ===")
        
        # Get all activities
        cursor = db.conn.cursor()
        cursor.execute('SELECT * FROM activities ORDER BY timestamp DESC')
        activities = [dict(row) for row in cursor.fetchall()]
        
        print(f"\nTotal activities: {len(activities)}")
        for activity in activities:
            print(f"{activity['timestamp']} | {activity['action']:10} | {activity['file_path']} | {activity['file_type']}")
        
        # Get file type stats
        stats = db.get_file_type_stats()
        print(f"\n=== File Type Statistics ===")
        for stat in stats:
            print(f"{stat['file_type']:15} | {stat['action']:10} | {stat['count']}")

if __name__ == "__main__":
    main()