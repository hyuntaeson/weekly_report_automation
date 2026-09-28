#!/usr/bin/env python3
"""
Test Slack collector functionality
"""

import os
import json
from slack_collector import SlackCollector, SlackConfigManager


def test_slack_config():
    """Test Slack configuration"""
    print("=== Testing Slack Configuration ===")
    
    config_manager = SlackConfigManager()
    
    # Create default config if not exists
    if not os.path.exists('config/slack_config.json'):
        print("Creating default Slack configuration...")
        config = config_manager.create_default_config()
        print(f"Config created at: config/slack_config.json")
        print(f"Config content: {json.dumps(config, indent=2)}")
    else:
        print("Slack config already exists")
        config = config_manager.load_config()
        print(f"Config content: {json.dumps(config, indent=2)}")
    
    # Check if enabled
    if config.get('enabled', False):
        print("Slack collection is ENABLED")
    else:
        print("Slack collection is DISABLED")
    
    return config


def test_slack_collector():
    """Test Slack collector"""
    print("\n=== Testing Slack Collector ===")
    
    # Load config
    config = test_slack_config()
    
    if not config.get('enabled', False):
        print("Skipping Slack collector test (not enabled)")
        return
    
    token = config.get('token', '')
    if not token:
        print("Skipping Slack collector test (no token)")
        return
    
    # Create collector
    collector = SlackCollector(token=token)
    
    # Test connection
    print("Testing Slack connection...")
    if collector.connect_slack():
        print("PASS: Slack connection successful")
        
        # Test activity collection
        print("Collecting Slack activity...")
        activities = collector.collect_all_slack_activity(days=1)
        print(f"PASS: Collected {len(activities)} activities")
        
        # Show sample activities
        if activities:
            print("\nSample activities:")
            for activity in activities[:3]:
                print(f"  {activity['timestamp']} | {activity['action']} | {activity['file_path']}")
        
        # Test database save
        if activities:
            print("\nTesting database save...")
            count = collector.save_to_database(activities)
            print(f"PASS: Saved {count} activities to database")
        
        return activities
    else:
        print("FAIL: Slack connection failed")
        return []


def main():
    """Main test function"""
    print("Starting Slack collector tests...")
    print("=" * 50)
    
    test_slack_config()
    test_slack_collector()
    
    print("=" * 50)
    print("Slack collector tests completed!")


if __name__ == "__main__":
    main()