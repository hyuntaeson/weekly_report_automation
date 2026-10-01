#!/usr/bin/env python3
"""
Simple test for file watcher
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)  # 상대 경로(config/, data/, test_reports/)는 프로젝트 루트 기준
from weekly_report.collectors.file_watcher import FileWatcher, FileActivityHandler


def main():
    # Test with current directory
    test_path = os.path.dirname(os.path.abspath(__file__))
    
    print(f"Testing file watcher on: {test_path}")
    print("Creating a test file in 3 seconds...")
    
    # Create handler and watcher
    log_file = "logs/test_activity.log"
    db_path = "data/test_activities.db"
    exclude_patterns = ['*.log', 'logs/*', '*.db', '*.db-journal']
    handler = FileActivityHandler(log_file, exclude_patterns, db_path)
    watcher = FileWatcher([test_path], log_file, exclude_patterns, db_path)
    watcher.handler = handler
    
    # Start observer in background
    watcher.observer.schedule(handler, test_path, recursive=True)
    watcher.observer.start()
    
    time.sleep(3)
    
    # Create a test file
    test_file = os.path.join(test_path, "test_activity.txt")
    with open(test_file, 'w') as f:
        f.write("Test file for activity monitoring")
    
    print(f"Created test file: {test_file}")
    
    # Wait for event to be processed
    time.sleep(2)
    
    # Modify the file
    with open(test_file, 'a') as f:
        f.write("\nModified content")
    
    print(f"Modified test file: {test_file}")
    
    time.sleep(2)
    
    # Stop watcher
    watcher.stop()
    
    # Clean up
    if os.path.exists(test_file):
        os.remove(test_file)
        print(f"Cleaned up test file: {test_file}")
    
    print("\nTest completed!")


if __name__ == "__main__":
    main()