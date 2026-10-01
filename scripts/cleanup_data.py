#!/usr/bin/env python3
"""
data/ 폴더에 쌓이는 테스트·수집 산출물 정리 유틸리티.

기본 동작 (dry-run 없이 바로 정리하려면 --yes):
- activities_*.json, test_results_*.json, slack_test_*.json 등
  테스트 산출물 파일을 제거
- --keep-recent N : 패턴별로 최신 N개만 남김 (기본 3)
- activities.db, 주간 보고서 등 실데이터는 건드리지 않음

사용법:
  python cleanup_data.py           # 삭제 대상 목록만 출력 (dry-run)
  python cleanup_data.py --yes     # 실제 삭제
"""

import argparse
import glob
import os
import time
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)  # 상대 경로(config/, data/, test_reports/)는 프로젝트 루트 기준

CLEANUP_PATTERNS = [
    "data/activities_*.json",
    "data/test_results_*.json",
    "data/slack_test_*.json",
    "data/*_test_*.json",
    "logs/_test.log",
]


def collect_targets(base=".", keep_recent=3):
    targets = []
    for pattern in CLEANUP_PATTERNS:
        files = [
            os.path.join(base, f)
            for f in glob.glob(os.path.join(base, pattern))
            if os.path.isfile(f)
        ]
        files.sort(key=lambda p: -os.path.getmtime(p))
        targets.extend(files[keep_recent:])
    return targets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="실제 삭제 실행")
    parser.add_argument("--keep-recent", type=int, default=3)
    args = parser.parse_args()

    targets = collect_targets(keep_recent=args.keep_recent)
    if not targets:
        print("정리할 테스트 산출물 없음")
        return

    print(f"삭제 대상 {len(targets)}건:")
    total = 0
    for path in targets:
        size = os.path.getsize(path)
        total += size
        age_days = (time.time() - os.path.getmtime(path)) / 86400
        print(f"  {path} ({size//1024}KB, {age_days:.0f}일 전)")
    print(f"합계 {total//1024}KB")

    if not args.yes:
        print("\ndry-run 모드. 실제 삭제는 --yes 옵션.")
        return
    for path in targets:
        os.remove(path)
    print(f"{len(targets)}건 삭제 완료")


if __name__ == "__main__":
    main()
