#!/usr/bin/env python3
"""
IDE Activity Collector
Collects activity from VSCode, Orca, and other IDEs
"""

import os
import json
import glob
from datetime import datetime
from pathlib import Path
from database import ActivityDatabase


class IDECollector:
    """Collector for IDE activities"""
    
    def __init__(self, db_path='data/activities.db'):
        self.db_path = db_path
        self.collected_activities = []
    
    def collect_vscode_activity(self):
        """Collect VSCode activity from log files"""
        vscode_paths = self._find_vscode_paths()
        activities = []
        
        for vscode_path in vscode_paths:
            # Check for various VSCode log locations
            log_patterns = [
                os.path.join(vscode_path, "logs", "*.log"),
                os.path.join(vscode_path, "User", "globalStorage", "*.json"),
                os.path.join(vscode_path, "User", "History", "*.json"),
            ]
            
            for pattern in log_patterns:
                for log_file in glob.glob(pattern):
                    try:
                        file_activities = self._parse_vscode_log(log_file)
                        activities.extend(file_activities)
                    except Exception as e:
                        print(f"Error parsing VSCode log {log_file}: {e}")
        
        return activities
    
    def _find_vscode_paths(self):
        """Find VSCode installation paths"""
        possible_paths = [
            os.path.expanduser("~/.vscode"),
            os.path.expanduser("~/AppData/Roaming/Code"),
            os.path.expanduser("~/AppData/Local/Programs/Microsoft VS Code"),
            "C:\\Program Files\\Microsoft VS Code",
            "C:\\Program Files (x86)\\Microsoft VS Code",
        ]
        
        found_paths = []
        for path in possible_paths:
            if os.path.exists(path):
                found_paths.append(path)
        
        return found_paths
    
    def _parse_vscode_log(self, log_file):
        """Parse VSCode log file for activity"""
        activities = []
        modification_time = os.path.getmtime(log_file)
        timestamp = datetime.fromtimestamp(modification_time).isoformat()
        
        activities.append({
            'timestamp': timestamp,
            'action': 'modified',
            'file_path': log_file,
            'file_type': 'vscode_log',
            'source': 'vscode'
        })
        
        return activities
    
    def collect_orca_activity(self):
        """Collect Orca IDE activity using orca-cli"""
        activities = []
        
        try:
            # Try to use orca-cli if available
            # This would require the orca-cli skill to be available
            # For now, we'll look for Orca log files
            orca_paths = self._find_orca_paths()
            
            for orca_path in orca_paths:
                log_patterns = [
                    os.path.join(orca_path, "*.log"),
                    os.path.join(orca_path, "logs", "*.log"),
                ]
                
                for pattern in log_patterns:
                    for log_file in glob.glob(pattern):
                        try:
                            file_activities = self._parse_orca_log(log_file)
                            activities.extend(file_activities)
                        except Exception as e:
                            print(f"Error parsing Orca log {log_file}: {e}")
        
        except Exception as e:
            print(f"Error collecting Orca activity: {e}")
        
        return activities
    
    def _find_orca_paths(self):
        """Find Orca installation paths"""
        possible_paths = [
            os.path.expanduser("~/.orca"),
            os.path.expanduser("~/AppData/Local/Orca"),
            os.path.expanduser("~/AppData/Roaming/Orca"),
        ]
        
        found_paths = []
        for path in possible_paths:
            if os.path.exists(path):
                found_paths.append(path)
        
        return found_paths
    
    def _parse_orca_log(self, log_file):
        """Parse Orca log file for activity"""
        activities = []
        modification_time = os.path.getmtime(log_file)
        timestamp = datetime.fromtimestamp(modification_time).isoformat()
        
        activities.append({
            'timestamp': timestamp,
            'action': 'modified',
            'file_path': log_file,
            'file_type': 'orca_log',
            'source': 'orca'
        })
        
        return activities
    
    def collect_all_ide_activity(self):
        """Collect activity from all IDEs"""
        all_activities = []
        
        # VSCode
        vscode_activities = self.collect_vscode_activity()
        all_activities.extend(vscode_activities)
        
        # Orca
        orca_activities = self.collect_orca_activity()
        all_activities.extend(orca_activities)
        
        return all_activities
    
    def save_to_database(self, activities):
        """Save collected activities to database"""
        with ActivityDatabase(self.db_path) as db:
            for activity in activities:
                # Add source information
                activity_with_source = {
                    **activity,
                    'source': activity.get('source', 'ide')
                }
                db.add_activity(activity_with_source)
        
        return len(activities)


class RecentFileCollector:
    """Collector for recently opened files in IDEs"""
    
    def __init__(self, db_path='data/activities.db'):
        self.db_path = db_path
    
    def collect_vscode_recent_files(self):
        """Collect recently opened files from VSCode"""
        activities = []
        
        # VSCode stores recent files in workspace storage
        vscode_paths = [
            os.path.expanduser("~/AppData/Roaming/Code/User/globalStorage"),
            os.path.expanduser("~/.vscode/User/globalStorage"),
        ]
        
        for path in vscode_paths:
            if os.path.exists(path):
                # Look for recent files in storage
                storage_files = glob.glob(os.path.join(path, "*.json"))
                for storage_file in storage_files:
                    try:
                        with open(storage_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            # Parse recent files from the JSON structure
                            if isinstance(data, dict):
                                self._extract_recent_files(data, storage_file, activities)
                    except Exception as e:
                        print(f"Error reading VSCode storage {storage_file}: {e}")
        
        return activities
    
    def _extract_recent_files(self, data, source_file, activities):
        """Extract recent file information from VSCode storage"""
        if isinstance(data, dict):
            for key, value in data.items():
                if 'recent' in key.lower() or 'history' in key.lower():
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict) and 'path' in item:
                                activities.append({
                                    'timestamp': datetime.now().isoformat(),
                                    'action': 'opened',
                                    'file_path': item['path'],
                                    'file_type': self._get_file_type(item['path']),
                                    'source': 'vscode_recent'
                                })
                elif isinstance(value, (dict, list)):
                    self._extract_recent_files(value, source_file, activities)
    
    def _get_file_type(self, file_path):
        """Determine file type from extension"""
        ext = Path(file_path).suffix.lower()
        type_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.cs': 'csharp',
            '.go': 'go',
            '.rs': 'rust',
            '.php': 'php',
            '.rb': 'ruby',
            '.swift': 'swift',
            '.kt': 'kotlin',
            '.scala': 'scala',
            '.html': 'html',
            '.css': 'css',
            '.scss': 'scss',
            '.json': 'json',
            '.xml': 'xml',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.md': 'markdown',
            '.txt': 'text',
            '.sql': 'sql',
        }
        return type_map.get(ext, 'unknown')


def main():
    """Test IDE collector"""
    collector = IDECollector()
    
    print("Collecting VSCode activity...")
    vscode_activities = collector.collect_vscode_activity()
    print(f"Found {len(vscode_activities)} VSCode activities")
    
    print("Collecting Orca activity...")
    orca_activities = collector.collect_orca_activity()
    print(f"Found {len(orca_activities)} Orca activities")
    
    all_activities = vscode_activities + orca_activities
    print(f"Total IDE activities: {len(all_activities)}")
    
    if all_activities:
        print("\nSample activities:")
        for activity in all_activities[:5]:
            print(f"  {activity['timestamp']} | {activity['action']} | {activity['file_path']}")


if __name__ == "__main__":
    main()