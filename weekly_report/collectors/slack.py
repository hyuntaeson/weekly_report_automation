#!/usr/bin/env python3
"""
Slack Activity Collector
Collects messages and activity from Slack using Slack API
"""

import os
import json
from datetime import datetime, timedelta
from weekly_report import paths
from weekly_report.storage.database import ActivityDatabase


class SlackCollector:
    """Collector for Slack activities"""
    
    def __init__(self, db_path=paths.DB_PATH, token=None):
        self.db_path = db_path
        self.token = token or os.environ.get('SLACK_BOT_TOKEN')
        self.client = None
        
        if not self.token:
            print("Warning: No Slack token provided. Set SLACK_BOT_TOKEN environment variable or pass token parameter.")
    
    def connect_slack(self):
        """Connect to Slack API"""
        try:
            from slack_sdk import WebClient
            self.client = WebClient(token=self.token)
            # Test connection
            auth_result = self.client.auth_test()
            print(f"Connected to Slack as {auth_result['user']}")
            return True
        except ImportError:
            print("Error: slack-sdk library not installed. Run: pip install slack-sdk")
            return False
        except Exception as e:
            print(f"Error connecting to Slack: {e}")
            return False
    
    def collect_channel_messages(self, channel_id, days=7):
        """Collect messages from a specific channel"""
        if not self.connect_slack():
            return []
        
        activities = []
        
        try:
            # Calculate timestamp
            oldest = datetime.now() - timedelta(days=days)
            
            # Get channel history
            result = self.client.conversations_history(
                channel=channel_id,
                oldest=oldest.timestamp(),
                limit=1000
            )
            
            for message in result['messages']:
                if message.get('type') == 'message' and 'bot_id' not in message:
                    activity = {
                        'timestamp': datetime.fromtimestamp(float(message['ts'])).isoformat(),
                        'action': 'message',
                        'file_path': f"Slack: {message.get('channel', 'unknown')}",
                        'file_type': 'slack_message',
                        'source': 'slack',
                        'details': json.dumps({
                            'channel': message.get('channel'),
                            'user': message.get('user'),
                            'text': message.get('text', '')[:100],  # Truncate long messages
                            'reactions': len(message.get('reactions', [])),
                            'thread_ts': message.get('thread_ts')
                        }, ensure_ascii=False)
                    }
                    activities.append(activity)
            
            print(f"Collected {len(activities)} messages from channel {channel_id}")
            
        except Exception as e:
            print(f"Error collecting channel messages: {e}")
        
        return activities
    
    def collect_user_activity(self, user_id, days=7):
        """Collect activity for a specific user"""
        if not self.connect_slack():
            return []
        
        activities = []
        
        try:
            # Get user info
            user_info = self.client.users_info(user=user_id)
            print(f"Collecting activity for user: {user_info['user']['name']}")
            
            # Search for messages by user
            oldest = datetime.now() - timedelta(days=days)
            
            # This is a simplified approach - in production you'd need to iterate through channels
            # For now, we'll create a placeholder activity
            activity = {
                'timestamp': datetime.now().isoformat(),
                'action': 'user_activity',
                'file_path': f"Slack User: {user_info['user']['name']}",
                'file_type': 'slack_user',
                'source': 'slack',
                'details': json.dumps({
                    'user_id': user_id,
                    'user_name': user_info['user']['name'],
                    'activity_type': 'presence'
                }, ensure_ascii=False)
            }
            activities.append(activity)
            
        except Exception as e:
            print(f"Error collecting user activity: {e}")
        
        return activities
    
    def collect_all_channels_activity(self, days=7):
        """Collect activity from all public channels"""
        if not self.connect_slack:
            return []
        
        all_activities = []
        
        try:
            # Get all channels
            channels = self.client.conversations_list(
                types="public_channel",
                exclude_archived=True,
                limit=100
            )
            
            print(f"Found {len(channels['channels'])} public channels")
            
            # Collect messages from each channel
            for channel in channels['channels']:
                print(f"Collecting from channel: {channel['name']}")
                channel_activities = self.collect_channel_messages(channel['id'], days)
                all_activities.extend(channel_activities)
                
        except Exception as e:
            print(f"Error collecting from all channels: {e}")
        
        return all_activities
    
    def collect_recent_mentions(self, days=7):
        """Collect recent mentions of the bot/user"""
        if not self.connect_slack():
            return []
        
        activities = []
        
        try:
            # Get team info
            team_info = self.client.team_info()
            
            # Search for mentions (simplified approach)
            # In production, you'd use the search API
            activity = {
                'timestamp': datetime.now().isoformat(),
                'action': 'mention',
                'file_path': f"Slack: {team_info['team']['name']}",
                'file_type': 'slack_mention',
                'source': 'slack',
                'details': json.dumps({
                    'team_id': team_info['team']['id'],
                    'team_name': team_info['team']['name']
                }, ensure_ascii=False)
            }
            activities.append(activity)
            
        except Exception as e:
            print(f"Error collecting mentions: {e}")
        
        return activities
    
    def collect_file_shares(self, days=7):
        """Collect file sharing activity"""
        if not self.connect_slack():
            return []
        
        activities = []
        
        try:
            # Get all files shared recently
            # This is a placeholder - in production you'd use files.list API
            activity = {
                'timestamp': datetime.now().isoformat(),
                'action': 'file_share',
                'file_path': "Slack: File Sharing",
                'file_type': 'slack_file',
                'source': 'slack',
                'details': json.dumps({
                    'collection_type': 'file_shares',
                    'note': 'Full implementation requires files.list API'
                }, ensure_ascii=False)
            }
            activities.append(activity)
            
        except Exception as e:
            print(f"Error collecting file shares: {e}")
        
        return activities
    
    def collect_all_slack_activity(self, days=7):
        """Collect all Slack activity"""
        all_activities = []
        
        # Collect channel messages
        channel_activities = self.collect_all_channels_activity(days)
        all_activities.extend(channel_activities)
        
        # Collect user activity
        # Note: This would require user IDs list in production
        
        # Collect mentions
        mention_activities = self.collect_recent_mentions(days)
        all_activities.extend(mention_activities)
        
        # Collect file shares
        file_activities = self.collect_file_shares(days)
        all_activities.extend(file_activities)
        
        return all_activities
    
    def save_to_database(self, activities):
        """Save collected activities to database"""
        with ActivityDatabase(self.db_path) as db:
            for activity in activities:
                db.add_activity(activity)
        
        return len(activities)


class SlackConfigManager:
    """Manager for Slack configuration"""
    
    def __init__(self, config_file=paths.SLACK_CONFIG):
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self):
        """Load Slack configuration"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def save_config(self, config):
        """Save Slack configuration"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    
    def create_default_config(self):
        """Create default Slack configuration"""
        default_config = {
            "enabled": False,
            "token": "",
            "channels_to_monitor": [],
            "users_to_monitor": [],
            "collect_mentions": True,
            "collect_file_shares": True,
            "collection_interval_hours": 1
        }
        self.save_config(default_config)
        return default_config


def main():
    """Test Slack collector"""
    print("Testing Slack collector...")
    
    # Create config
    config_manager = SlackConfigManager()
    if not os.path.exists(paths.SLACK_CONFIG):
        print("Creating default Slack configuration...")
        config_manager.create_default_config()
        print("Please edit config/slack_config.json with your Slack token and channels")
        return
    
    config = config_manager.load_config()
    
    if not config.get('enabled', False):
        print("Slack collection is disabled in config")
        return
    
    # Create collector
    collector = SlackCollector()
    
    # Test connection
    if collector.connect_slack():
        # Collect activity
        activities = collector.collect_all_slack_activity(days=1)
        print(f"Collected {len(activities)} Slack activities")
        
        # Save to database
        if activities:
            count = collector.save_to_database(activities)
            print(f"Saved {count} activities to database")
        
        # Show sample activities
        if activities:
            print("\nSample Slack activities:")
            for activity in activities[:3]:
                print(f"  {activity['timestamp']} | {activity['action']} | {activity['file_path']}")
    else:
        print("No Slack activities collected")


if __name__ == "__main__":
    main()