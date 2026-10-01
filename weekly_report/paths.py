"""
프로젝트 경로를 한 곳에서 관리.

모든 경로는 프로젝트 루트 기준 절대 경로라서, 어느 폴더에서 실행해도
같은 설정·DB·보고서 위치를 쓴다 (예전에는 실행 폴더 기준 상대 경로와
__file__ 기준 경로가 섞여 있어 다른 폴더에서 실행하면 설정을 못 찾았음).
"""

import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PACKAGE_DIR)  # 프로젝트 루트

CONFIG_DIR = os.path.join(BASE_DIR, "config")
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
TEST_REPORTS_DIR = os.path.join(BASE_DIR, "test_reports")
TEMPLATES_DIR = os.path.join(PACKAGE_DIR, "report", "templates")

# data/
DB_PATH = os.path.join(DATA_DIR, "activities.db")
QDRANT_DIR = os.path.join(DATA_DIR, "qdrant")
RAG_QUERY_CACHE = os.path.join(DATA_DIR, "rag_topic_queries.json")

# logs/
FILE_ACTIVITY_LOG = os.path.join(LOGS_DIR, "file_activity.log")

# config/
WATCH_CONFIG = os.path.join(CONFIG_DIR, "watch_config.json")
LITELLM_CONFIG = os.path.join(CONFIG_DIR, "litellm_config.json")
TEAMS_TOKEN = os.path.join(CONFIG_DIR, "teams_graph_token.json")
TEAMS_SETTINGS = os.path.join(CONFIG_DIR, "teams_settings.json")
REPORT_SETTINGS = os.path.join(CONFIG_DIR, "report_settings.json")
SLACK_CONFIG = os.path.join(CONFIG_DIR, "slack_config.json")
CONFLUENCE_CONFIG = os.path.join(CONFIG_DIR, "confluence_config.json")
