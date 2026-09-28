#!/usr/bin/env python3
"""
Outlook Activity Collector
Collects email and calendar activity from Microsoft Outlook
"""

import os
import win32com.client
from datetime import datetime, timedelta
from database import ActivityDatabase
from llm_summarizer import LLMSummarizer


class OutlookCollector:
    """Collector for Outlook activities"""

    def __init__(self, db_path='data/activities.db'):
        self.db_path = db_path
        self.outlook = None
        self.summarizer = LLMSummarizer()
    
    def connect_outlook(self):
        """Connect to Outlook application"""
        try:
            self.outlook = win32com.client.Dispatch("Outlook.Application")
            return True
        except Exception as e:
            print(f"Error connecting to Outlook: {e}")
            return False
    
    def collect_email_activity(self, days=7):
        """Collect email activity from the last N days"""
        if not self.connect_outlook():
            return []
        
        activities = []
        
        try:
            # Get Inbox
            namespace = self.outlook.GetNamespace("MAPI")
            inbox = namespace.GetDefaultFolder(6)  # 6 = Inbox
            
            # Get emails from last N days
            start_date = datetime.now() - timedelta(days=days)
            items = inbox.Items
            items.Sort("[ReceivedTime]", True)
            
            # Filter by date
            items = items.Restrict(f"[ReceivedTime] >= '{start_date.strftime('%m/%d/%Y %H:%M %p')}'")
            
            for item in items:
                try:
                    activity = {
                        'timestamp': item.ReceivedTime.isoformat() if hasattr(item.ReceivedTime, 'isoformat') else str(item.ReceivedTime),
                        'action': 'email_received',
                        'file_path': f"Email: {item.Subject}",
                        'file_type': 'email',
                        'source': 'outlook',
                        'details': {
                            'subject': item.Subject,
                            'sender': item.SenderEmailAddress if hasattr(item, 'SenderEmailAddress') else 'Unknown',
                            'size': item.Size if hasattr(item, 'Size') else 0
                        }
                    }
                    activities.append(activity)
                except Exception as e:
                    print(f"Error processing email: {e}")
                    continue
        
        except Exception as e:
            print(f"Error collecting email activity: {e}")
        
        return activities
    
    def collect_sent_email_activity(self, days=7):
        """Collect sent email activity from the last N days"""
        if not self.connect_outlook():
            return []
        
        activities = []
        
        try:
            # Get Sent Items
            namespace = self.outlook.GetNamespace("MAPI")
            sent_folder = namespace.GetDefaultFolder(5)  # 5 = Sent Items
            
            # Get sent emails from last N days
            start_date = datetime.now() - timedelta(days=days)
            items = sent_folder.Items
            items.Sort("[SentOn]", True)
            
            # Filter by date
            items = items.Restrict(f"[SentOn] >= '{start_date.strftime('%m/%d/%Y %H:%M %p')}'")

            summary_cache = self._get_summary_cache()
            for item in items:
                try:
                    timestamp = item.SentOn.isoformat() if hasattr(item.SentOn, 'isoformat') else str(item.SentOn)
                    file_path = f"Sent: {item.Subject}"
                    cache_key = (timestamp, 'email_sent', file_path)
                    cached_summary = summary_cache.get(cache_key)
                    if cached_summary is not None:
                        summary = cached_summary
                    else:
                        body_text = item.Body if hasattr(item, 'Body') else ''
                        summary = self._summarize_text(body_text)

                    activity = {
                        'timestamp': timestamp,
                        'action': 'email_sent',
                        'file_path': file_path,
                        'file_type': 'email',
                        'source': 'outlook',
                        'details': {
                            'subject': item.Subject,
                            'recipients': len(item.Recipients) if hasattr(item, 'Recipients') else 0,
                            'size': item.Size if hasattr(item, 'Size') else 0,
                            'summary': summary
                        }
                    }
                    activities.append(activity)
                except Exception as e:
                    print(f"Error processing sent email: {e}")
                    continue
        
        except Exception as e:
            print(f"Error collecting sent email activity: {e}")
        
        return activities
    
    def _get_summary_cache(self):
        """이미 DB에 저장된 outlook 활동의 요약 캐시를 불러온다 (LLM 재호출 방지)"""
        try:
            with ActivityDatabase(self.db_path) as db:
                return db.get_summary_cache('outlook')
        except Exception as e:
            print(f"Warning: Failed to load Outlook summary cache: {e}")
            return {}

    def _summarize_text(self, text, max_len=300):
        """본문 텍스트를 요약. LiteLLM이 설정되어 있으면 실제 AI 요약을 쓰고,
        아니면 앞부분을 발췌하는 방식으로 폴백."""
        if not text:
            return ''
        collapsed = ' '.join(str(text).split())

        llm_summary = self.summarizer.summarize(collapsed)
        if llm_summary:
            return llm_summary

        if len(collapsed) <= max_len:
            return collapsed
        return collapsed[:max_len].rstrip() + '...'

    @staticmethod
    def _is_teams_meeting(location, body):
        """캘린더 항목이 Teams 온라인 회의인지 판별.
        Location 또는 본문에 Teams 참가 링크가 있으면 Teams 회의로 간주."""
        text = f"{location or ''}\n{body or ''}".lower()
        teams_markers = [
            'teams.microsoft.com',
            'teams.live.com',
            'microsoft teams meeting',
        ]
        return any(marker in text for marker in teams_markers)

    def collect_calendar_activity(self, days=7):
        """Collect calendar activity from the last N days"""
        if not self.connect_outlook():
            return []
        
        activities = []
        
        try:
            # Get Calendar
            namespace = self.outlook.GetNamespace("MAPI")
            calendar = namespace.GetDefaultFolder(9)  # 9 = Calendar
            
            # Get appointments from last N days
            start_date = datetime.now() - timedelta(days=days)
            end_date = datetime.now() + timedelta(days=1)
            
            items = calendar.Items
            items.Sort("[Start]", True)
            items = items.Restrict(f"[Start] >= '{start_date.strftime('%m/%d/%Y %H:%M %p')}' AND [End] <= '{end_date.strftime('%m/%d/%Y %H:%M %p')}'")
            
            for item in items:
                try:
                    subject = item.Subject
                    location = item.Location if hasattr(item, 'Location') else ''
                    body = ''
                    try:
                        body = item.Body if hasattr(item, 'Body') else ''
                    except Exception:
                        pass

                    # Teams 온라인 회의인지 판별 (Location/본문에 Teams 링크 존재 여부)
                    is_teams = self._is_teams_meeting(location, body)

                    activity = {
                        'timestamp': item.Start.isoformat() if hasattr(item.Start, 'isoformat') else str(item.Start),
                        'action': 'meeting',
                        'file_path': f"{'Teams Meeting' if is_teams else 'Meeting'}: {subject}",
                        'file_type': 'calendar',
                        'source': 'outlook',
                        'details': {
                            'subject': subject,
                            'location': location,
                            'duration': str(item.Duration) if hasattr(item, 'Duration') else '0',
                            'organizer': item.Organizer if hasattr(item, 'Organizer') else 'Unknown',
                            'is_teams_meeting': is_teams
                        }
                    }
                    activities.append(activity)
                except Exception as e:
                    print(f"Error processing calendar item: {e}")
                    continue
        
        except Exception as e:
            print(f"Error collecting calendar activity: {e}")
        
        return activities
    
    def collect_all_outlook_activity(self, days=7):
        """Collect all Outlook activity from the last N days"""
        all_activities = []
        
        # Email activity
        email_activities = self.collect_email_activity(days)
        all_activities.extend(email_activities)
        
        # Sent email activity
        sent_activities = self.collect_sent_email_activity(days)
        all_activities.extend(sent_activities)
        
        # Calendar activity
        calendar_activities = self.collect_calendar_activity(days)
        all_activities.extend(calendar_activities)
        
        return all_activities
    
    def save_to_database(self, activities):
        """Save collected activities to database"""
        with ActivityDatabase(self.db_path) as db:
            for activity in activities:
                # Store details as JSON string
                activity_copy = activity.copy()
                if 'details' in activity_copy:
                    import json
                    activity_copy['details'] = json.dumps(activity_copy['details'])
                db.add_activity(activity_copy)
        
        return len(activities)


class OutlookLogCollector:
    """Alternative collector using Outlook log files"""
    
    def __init__(self, db_path='data/activities.db'):
        self.db_path = db_path
    
    def collect_outlook_logs(self):
        """Collect activity from Outlook log files"""
        activities = []
        
        # Outlook log file locations
        outlook_log_paths = [
            os.path.expanduser("~/AppData/Local/Microsoft/Outlook"),
            os.path.expanduser("~/AppData/Roaming/Microsoft/Outlook"),
        ]
        
        for path in outlook_log_paths:
            if os.path.exists(path):
                import glob
                log_files = glob.glob(os.path.join(path, "*.log"))
                log_files.extend(glob.glob(os.path.join(path, "*.txt")))
                
                for log_file in log_files:
                    try:
                        modification_time = os.path.getmtime(log_file)
                        timestamp = datetime.fromtimestamp(modification_time).isoformat()
                        
                        activities.append({
                            'timestamp': timestamp,
                            'action': 'modified',
                            'file_path': log_file,
                            'file_type': 'outlook_log',
                            'source': 'outlook_logs'
                        })
                    except Exception as e:
                        print(f"Error processing Outlook log {log_file}: {e}")
        
        return activities


def main():
    """Test Outlook collector"""
    print("Testing Outlook collector...")
    
    # Try log-based collector first (doesn't require Outlook to be running)
    log_collector = OutlookLogCollector()
    log_activities = log_collector.collect_outlook_logs()
    print(f"Found {len(log_activities)} Outlook log activities")
    
    # Try API-based collector (requires Outlook to be installed and running)
    try:
        api_collector = OutlookCollector()
        api_activities = api_collector.collect_all_outlook_activity(days=1)
        print(f"Found {len(api_activities)} Outlook API activities")
        
        if api_activities:
            print("\nSample Outlook activities:")
            for activity in api_activities[:3]:
                print(f"  {activity['timestamp']} | {activity['action']} | {activity['file_path']}")
    except Exception as e:
        print(f"Outlook API collector not available: {e}")
        print("This is normal if Outlook is not installed or not running.")


if __name__ == "__main__":
    main()