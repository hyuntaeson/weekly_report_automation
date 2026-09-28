#!/usr/bin/env python3
"""
GUI File Watcher with Real-time Monitoring
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
import os
import json
from datetime import datetime
from file_watcher import FileWatcher, FileActivityHandler
from database import ActivityDatabase
from ide_collector import IDECollector, RecentFileCollector
from outlook_collector import OutlookCollector, OutlookLogCollector


class GUIFileWatcher:
    """GUI-based file watcher with real-time monitoring"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("주간보고 자동작성 - 파일 감시 모니터")
        self.root.geometry("1000x700")
        
        # Activity queue for thread-safe communication
        self.activity_queue = queue.Queue()
        
        # File watcher instance
        self.watcher = None
        self.is_running = False
        
        # Additional collectors
        self.ide_collector = IDECollector('data/activities.db')
        self.outlook_collector = OutlookCollector('data/activities.db')
        self.outlook_log_collector = OutlookLogCollector('data/activities.db')
        
        # Statistics
        self.stats = {
            'total_activities': 0,
            'created': 0,
            'modified': 0,
            'deleted': 0,
            'moved': 0
        }
        
        # Setup GUI
        self.setup_ui()
        
        # Start update loop
        self.update_gui()
    
    def setup_ui(self):
        """Setup the GUI components"""
        
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Title
        title_label = ttk.Label(
            main_frame, 
            text="📁 주간보고 자동작성 - 실시간 파일 감시 모니터",
            font=("Arial", 16, "bold")
        )
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 10))
        
        # Status frame
        status_frame = ttk.LabelFrame(main_frame, text="상태", padding="10")
        status_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Status indicators
        self.status_label = ttk.Label(status_frame, text="상태: 중지", font=("Arial", 12))
        self.status_label.grid(row=0, column=0, padx=(0, 20))
        
        self.watch_count_label = ttk.Label(status_frame, text="감시 폴더: 0개", font=("Arial", 12))
        self.watch_count_label.grid(row=0, column=1, padx=(0, 20))
        
        self.activity_count_label = ttk.Label(status_frame, text="활동 수: 0", font=("Arial", 12))
        self.activity_count_label.grid(row=0, column=2, padx=(0, 20))
        
        self.ide_status_label = ttk.Label(status_frame, text="IDE: 대기", font=("Arial", 10), foreground="gray")
        self.ide_status_label.grid(row=0, column=3, padx=(0, 20))
        
        self.outlook_status_label = ttk.Label(status_frame, text="Outlook: 대기", font=("Arial", 10), foreground="gray")
        self.outlook_status_label.grid(row=0, column=4)
        
        # Statistics frame
        stats_frame = ttk.LabelFrame(main_frame, text="통계", padding="10")
        stats_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        
        # Stat labels
        self.created_label = ttk.Label(stats_frame, text="생성: 0", font=("Arial", 11), foreground="green")
        self.created_label.grid(row=0, column=0, pady=5, sticky=tk.W)
        
        self.modified_label = ttk.Label(stats_frame, text="수정: 0", font=("Arial", 11), foreground="blue")
        self.modified_label.grid(row=1, column=0, pady=5, sticky=tk.W)
        
        self.deleted_label = ttk.Label(stats_frame, text="삭제: 0", font=("Arial", 11), foreground="red")
        self.deleted_label.grid(row=2, column=0, pady=5, sticky=tk.W)
        
        self.moved_label = ttk.Label(stats_frame, text="이동: 0", font=("Arial", 11), foreground="orange")
        self.moved_label.grid(row=3, column=0, pady=5, sticky=tk.W)
        
        # Activity log frame
        log_frame = ttk.LabelFrame(main_frame, text="실시간 활동 로그", padding="10")
        log_frame.grid(row=2, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(5, 0))
        
        # Activity log text area
        self.activity_log = scrolledtext.ScrolledText(
            log_frame, 
            width=60, 
            height=20,
            font=("Consolas", 9),
            wrap=tk.WORD
        )
        self.activity_log.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        # Control buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        
        # Start button
        self.start_button = ttk.Button(
            button_frame, 
            text="시작", 
            command=self.start_watching,
            width=15
        )
        self.start_button.grid(row=0, column=0, padx=5)
        
        # Stop button
        self.stop_button = ttk.Button(
            button_frame, 
            text="중지", 
            command=self.stop_watching,
            width=15,
            state=tk.DISABLED
        )
        self.stop_button.grid(row=0, column=1, padx=5)
        
        # Clear button
        self.clear_button = ttk.Button(
            button_frame, 
            text="로그 지우기", 
            command=self.clear_log,
            width=15
        )
        self.clear_button.grid(row=0, column=2, padx=5)
        
        # Export button
        self.export_button = ttk.Button(
            button_frame, 
            text="내보내기", 
            command=self.export_data,
            width=15
        )
        self.export_button.grid(row=0, column=3, padx=5)
        
        # Collect IDE button
        self.ide_button = ttk.Button(
            button_frame, 
            text="IDE 수집", 
            command=self.collect_ide_activity,
            width=15
        )
        self.ide_button.grid(row=0, column=4, padx=5)
        
        # Collect Outlook button
        self.outlook_button = ttk.Button(
            button_frame, 
            text="Outlook 수집", 
            command=self.collect_outlook_activity,
            width=15
        )
        self.outlook_button.grid(row=0, column=5, padx=5)
        
        # Watched folders display
        folders_frame = ttk.LabelFrame(main_frame, text="감시 중인 폴더", padding="10")
        folders_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        
        self.folders_text = scrolledtext.ScrolledText(
            folders_frame, 
            height=4,
            font=("Consolas", 9),
            wrap=tk.WORD
        )
        self.folders_text.grid(row=0, column=0, sticky=(tk.W, tk.E))
        folders_frame.columnconfigure(0, weight=1)
        
        # Load config
        self.load_config()
    
    def load_config(self):
        """Load watch configuration"""
        config_file = 'config/watch_config.json'
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                watch_paths = config.get('watch_paths', [])
                
                # Display watched folders
                self.folders_text.delete(1.0, tk.END)
                for path in watch_paths:
                    self.folders_text.insert(tk.END, f"📂 {path}\n")
                
                self.watch_count_label.config(text=f"감시 폴더: {len(watch_paths)}개")
    
    def start_watching(self):
        """Start file watching"""
        if self.is_running:
            return
        
        # Load config
        config_file = 'config/watch_config.json'
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                watch_paths = config.get('watch_paths', [])
                exclude_patterns = config.get('exclude_patterns', [])
        else:
            watch_paths = []
            exclude_patterns = []
        
        if not watch_paths:
            self.log_message("⚠️ 감시할 폴더가 설정되지 않았습니다.")
            return
        
        # Create custom handler that sends to GUI
        class GUIFileActivityHandler(FileActivityHandler):
            def __init__(self, log_file, exclude_patterns, db_path, activity_queue):
                super().__init__(log_file, exclude_patterns, db_path)
                self.activity_queue = activity_queue
            
            def log_activity(self, action, file_path):
                super().log_activity(action, file_path)
                # Send to GUI
                self.activity_queue.put({
                    'action': action,
                    'file_path': file_path,
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })
        
        # Create watcher with custom handler
        log_file = 'logs/file_activity.log'
        db_path = 'data/activities.db'
        
        self.watcher = FileWatcher(watch_paths, log_file, exclude_patterns, db_path)
        self.watcher.handler = GUIFileActivityHandler(log_file, exclude_patterns, db_path, self.activity_queue)
        
        # Start in separate thread
        self.watcher_thread = threading.Thread(target=self.watcher.start, daemon=True)
        self.watcher_thread.start()
        
        self.is_running = True
        self.status_label.config(text="상태: 실행 중", foreground="green")
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        
        self.log_message("🚀 파일 감시가 시작되었습니다.")
    
    def stop_watching(self):
        """Stop file watching"""
        if not self.is_running:
            return
        
        if self.watcher:
            self.watcher.stop()
        
        self.is_running = False
        self.status_label.config(text="상태: 중지", foreground="black")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        
        self.log_message("⏹️ 파일 감시가 중지되었습니다.")
    
    def clear_log(self):
        """Clear the activity log"""
        self.activity_log.delete(1.0, tk.END)
        self.reset_stats()
    
    def reset_stats(self):
        """Reset statistics"""
        self.stats = {
            'total_activities': 0,
            'created': 0,
            'modified': 0,
            'deleted': 0,
            'moved': 0
        }
        self.update_stats_display()
    
    def export_data(self):
        """Export collected data"""
        try:
            with ActivityDatabase('data/activities.db') as db:
                cursor = db.conn.cursor()
                cursor.execute('SELECT * FROM activities ORDER BY timestamp DESC LIMIT 100')
                activities = cursor.fetchall()
                
                if not activities:
                    self.log_message("📭 내보낼 데이터가 없습니다.")
                    return
                
                # Create export file
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                export_file = f"data/export_{timestamp}.txt"
                
                with open(export_file, 'w', encoding='utf-8') as f:
                    f.write("=== 파일 활동 내보내기 ===\n\n")
                    for activity in activities:
                        # Handle both old and new database schemas
                        if len(activity) >= 7:
                            source = activity[5] if len(activity) > 5 else 'filesystem'
                            f.write(f"{activity[1]} | {activity[2]:10} | {activity[3]} | {activity[4]} | {source}\n")
                        else:
                            f.write(f"{activity[1]} | {activity[2]:10} | {activity[3]} | {activity[4]}\n")
                
                self.log_message(f"📤 데이터가 내보내기 되었습니다: {export_file}")
        
        except Exception as e:
            self.log_message(f"❌ 내보내기 실패: {e}")
    
    def collect_ide_activity(self):
        """Manually trigger IDE activity collection"""
        try:
            self.ide_status_label.config(text="IDE: 수집 중...", foreground="orange")
            self.log_message("🔍 IDE 활동 수집 시작...")
            
            # Collect IDE activity
            ide_activities = self.ide_collector.collect_all_ide_activity()
            if ide_activities:
                count = self.ide_collector.save_to_database(ide_activities)
                self.log_message(f"✅ IDE 활동 {count}개 수집 완료")
                
                # Update stats
                self.stats['total_activities'] += count
                self.update_stats_display()
            else:
                self.log_message("📭 IDE 활동 없음")
            
            # Collect recent files
            recent_collector = RecentFileCollector('data/activities.db')
            recent_activities = recent_collector.collect_vscode_recent_files()
            if recent_activities:
                with ActivityDatabase('data/activities.db') as db:
                    count = db.add_activities(recent_activities)
                self.log_message(f"✅ 최근 파일 {count}개 수집 완료")
                self.stats['total_activities'] += count
                self.update_stats_display()
            
            self.ide_status_label.config(text="IDE: 완료", foreground="green")
            
        except Exception as e:
            self.log_message(f"❌ IDE 수집 실패: {e}")
            self.ide_status_label.config(text="IDE: 오류", foreground="red")
    
    def collect_outlook_activity(self):
        """Manually trigger Outlook activity collection"""
        try:
            self.outlook_status_label.config(text="Outlook: 수집 중...", foreground="orange")
            self.log_message("🔍 Outlook 활동 수집 시작...")
            
            # Try API-based collection first
            try:
                outlook_activities = self.outlook_collector.collect_all_outlook_activity(days=1)
                if outlook_activities:
                    count = self.outlook_collector.save_to_database(outlook_activities)
                    self.log_message(f"✅ Outlook 활동 {count}개 수집 완료 (API)")
                    
                    # Update stats
                    self.stats['total_activities'] += count
                    self.update_stats_display()
                    self.outlook_status_label.config(text="Outlook: 완료", foreground="green")
                else:
                    self.log_message("📭 Outlook 활동 없음 (API)")
                    self.outlook_status_label.config(text="Outlook: 완료", foreground="green")
            
            except Exception as api_error:
                self.log_message(f"⚠️ Outlook API 실패: {api_error}")
                self.log_message("🔄 로그 기반 수집 시도...")
                
                # Fallback to log-based collection
                log_activities = self.outlook_log_collector.collect_outlook_logs()
                if log_activities:
                    with ActivityDatabase('data/activities.db') as db:
                        count = db.add_activities(log_activities)
                    self.log_message(f"✅ Outlook 로그 {count}개 수집 완료")
                    self.stats['total_activities'] += count
                    self.update_stats_display()
                    self.outlook_status_label.config(text="Outlook: 완료", foreground="green")
                else:
                    self.log_message("📭 Outlook 로그 없음")
                    self.outlook_status_label.config(text="Outlook: 완료", foreground="green")
        
        except Exception as e:
            self.log_message(f"❌ Outlook 수집 실패: {e}")
            self.outlook_status_label.config(text="Outlook: 오류", foreground="red")
    
    def log_message(self, message):
        """Add message to activity log"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.activity_log.insert(tk.END, f"[{timestamp}] {message}\n")
        self.activity_log.see(tk.END)
    
    def update_stats_display(self):
        """Update statistics display"""
        self.activity_count_label.config(text=f"활동 수: {self.stats['total_activities']}")
        self.created_label.config(text=f"생성: {self.stats['created']}")
        self.modified_label.config(text=f"수정: {self.stats['modified']}")
        self.deleted_label.config(text=f"삭제: {self.stats['deleted']}")
        self.moved_label.config(text=f"이동: {self.stats['moved']}")
    
    def update_gui(self):
        """Update GUI with new activities"""
        # Process all queued activities
        while not self.activity_queue.empty():
            try:
                activity = self.activity_queue.get_nowait()
                
                # Update stats
                self.stats['total_activities'] += 1
                action = activity['action']
                if action in self.stats:
                    self.stats[action] += 1
                
                # Update display
                self.update_stats_display()
                
                # Add to log with color coding
                timestamp = activity['timestamp']
                action_korean = {
                    'created': '생성',
                    'modified': '수정', 
                    'deleted': '삭제',
                    'moved': '이동'
                }.get(action, action)
                
                color_map = {
                    'created': 'green',
                    'modified': 'blue',
                    'deleted': 'red',
                    'moved': 'orange'
                }
                
                file_name = os.path.basename(activity['file_path'])
                message = f"[{timestamp}] {action_korean}: {file_name}"
                
                self.activity_log.insert(tk.END, message + "\n")
                self.activity_log.see(tk.END)
                
            except queue.Empty:
                break
        
        # Schedule next update
        self.root.after(100, self.update_gui)
    
    def on_closing(self):
        """Handle window closing"""
        if self.is_running:
            self.stop_watching()
        self.root.destroy()


def main():
    """Main entry point"""
    root = tk.Tk()
    app = GUIFileWatcher(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()