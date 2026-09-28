# 주간보고 자동작성 프로그램

매주 작업한 내용을 자동으로 수집하여 주간보고용 자료를 생성하는 자동화 프로그램입니다.

## 🎯 목표

매주 1회 리더주간회의를 진행하는데, 작업하고 진행한 내용들에 대해서 자동으로 생성하는 프로그램

## 📋 수집 대상

- 파일 시스템 (엑셀, PPT, Word, 텍스트 등)
- IDE 활동 (VSCode, Orca IDE)
- Outlook (이메일, 캘린더)
- Slack (메시지, 활동, 멘션, 파일 공유)
- AI 툴 (Claude Code)
- Confluence (페이지 생성/수정)
- 브라우저 (Chrome 방문 기록)

## ✅ 완료 기준

- [x] 8개 데이터 소스 수집 완료
- [x] 주간보고서 생성 기능 완료 (Markdown + Word, 액션별 실제 내용 상세 포함)
- [x] 현대적 UI 구현 및 버튼 로직 연동 완료 (레이아웃 버그 해결, 스켈레톤 상태)
- [x] 데이터베이스 시스템 구축 완료 (중복 제거 포함)
- [x] 통합 수집 아키텍처 구축 완료
- [x] AI 요약 연동 완료 (사내 LiteLLM Proxy, 캐싱 포함)
- [x] 전체 자동 테스트 스위트 100% 통과 (9/9 기능)
- [x] UI에서 감시 폴더 직접 추가/관리
- [x] Word/PPT/Excel 파일 내용 변경분 캡처 + 사내 DRM 대응(fallback 메시지)
- [x] 브라우저 활동 실제 수집 여부 실사용 검증 (2026-09-28 검증 완료 — 확장 설치 후 DB 기록 확인)
- [ ] Slack Bot Token 발급 및 연동 마무리

## 🎉 최종 결과

### 구현된 기능

| 기능 | 상태 | 설명 |
|------|------|------|
| 파일 시스템 감시 | ✅ 완료 | 실시간 파일 변경 감시(txt/md/docx/pptx/xlsx 내용 diff 캡처, DRM 파일 fallback 메시지), DB 저장 |
| 데이터베이스 시스템 | ✅ 완료 | SQLite 기반, 다중 소스 통합, 중복 제거(upsert) |
| IDE 활동 수집 | ✅ 완료 | VSCode, Orca IDE 로그 수집 |
| Outlook 활동 수집 | ✅ 완료 | 이메일/캘린더 COM API (보낸메일 AI 요약 포함) |
| Slack API 연동 | ⚙️ 설정 중 | Web API로 메시지/활동 수집 (Bot Token 발급 대기) |
| AI 툴 로그 수집 | ✅ 완료 | Claude Code 로그 파싱 (Devin 스텁) |
| 주간보고서 생성 | ✅ 완료 | Markdown + Word 자동 생성, 액션별 실제 내용 상세 포함 |
| AI 요약 (LiteLLM) | ✅ 완료 | 사내 LiteLLM Proxy로 Outlook/Confluence 내용 실제 요약 (최대 300자, 캐싱) |
| Confluence 연동 | ✅ 완료 | REST API로 페이지 활동 + 본문 요약 수집 |
| 브라우저 확장 | ✅ 완료 | Chrome MV3 확장 + 로컬 서버 |
| 통합 수집 시스템 | ✅ 완료 | 주기적 자동 수집, 스레드 기반 |
| Modern GUI | ✅ 완료 (스켈레톤) | Flet 기반 UI, 실제 프로세스 감지로 앱 활성 상태 실시간 반영 |

### 데이터 소스

| 소스 | 상태 | 수집 방법 |
|------|------|----------|
| 파일 시스템 | ✅ 완료 | 실시간 감시 + 텍스트 파일 내용 diff/AI 요약 |
| VSCode | ✅ 완료 | 로그 파일 + 최근 파일 |
| Orca IDE | ✅ 완료 | 로그 파일 |
| Outlook | ✅ 완료 | COM API (AI 요약 포함) |
| Slack | ⚙️ 설정 중 | Web API (Bot Token 필요) |
| Claude Code | ✅ 완료 | `~/.claude/history.jsonl` + `sessions/*.json` |
| Confluence | ✅ 완료 | REST API (PAT Bearer) + AI 요약 |
| 브라우저 | ✅ 완료 (Chrome only) | MV3 확장 + 로컬 HTTP 서버 |

### 테스트 결과

전체 통합 테스트 100% 통과 (9/9 기능)

## 📁 프로젝트 구조

```
weekly_report_automation/
├── modern_gui.py                # WeeklyPulse 스타일 현대적 UI
├── gui_watcher.py                # Classic tkinter 기반 GUI
├── file_watcher.py               # 파일 시스템 감시 프로그램
├── database.py                   # SQLite 데이터베이스 관리
├── ide_collector.py              # IDE 활동 수집 (VSCode, Orca)
├── outlook_collector.py          # Outlook 활동 수집
├── slack_collector.py            # Slack 활동 수집
├── ai_tool_collector.py          # AI 툴(Claude Code) 활동 수집
├── confluence_collector.py       # Confluence 페이지 활동 수집 (AI 요약 포함)
├── llm_summarizer.py             # 사내 LiteLLM Proxy 기반 텍스트 요약기
├── report_generator.py           # 주간보고서 생성 (Markdown+Word, 액션별 상세 내역)
├── browser_activity_server.py    # 브라우저 확장 수신용 로컬 HTTP 서버
├── integrated_collector.py       # 통합 수집 시스템
├── test_all_completed.py         # 통합 테스트 프로그램
├── check_database.py             # 데이터베이스 확인 프로그램
├── requirements.txt              # 필요한 라이브러리
├── run_modern_gui.bat            # Modern UI 실행 스크립트
├── run_gui.bat                   # Classic UI 실행 스크립트
├── .gitignore                    # config 토큰 파일, data/, reports/, logs/ 등 제외
├── templates/
│   ├── weekly_report.md.j2       # 보고서 Markdown 템플릿
│   └── blank_report_template.docx # python-docx용 빈 템플릿
├── browser_extension/            # Chrome MV3 확장
│   ├── manifest.json
│   ├── background.js
│   ├── popup.html / popup.js
│   └── icons/ (16/48/128px)
├── config/
│   ├── watch_config.json         # 감시 설정 파일 (감시 폴더 목록)
│   ├── slack_config.json         # Slack 설정 파일 (gitignore 처리됨)
│   ├── confluence_config.json    # Confluence 설정 파일 (토큰 포함, gitignore 처리됨)
│   └── litellm_config.json       # 사내 LiteLLM Proxy 설정 (API 키 포함, gitignore 처리됨)
├── reports/                      # 생성된 주간보고서 저장 위치
├── logs/                         # 로그 파일 저장소
├── data/                         # 데이터베이스 및 JSON 파일 저장소
├── README.md                     # 이 파일
├── decisions.md                  # 핵심 결정 사항
├── progress.md                   # 최근 작업 내역과 다음 할 일
└── archive/                      # 완료된 작업 로그, 조사 결과, 이전 계획
```

## 🚀 설치 및 실행

### 1. 필요한 라이브러리 설치
```bash
pip install -r requirements.txt
```

### 2. GUI 프로그램 실행 (권장)

**Modern UI (WeeklyPulse 스타일):**
```bash
run_modern_gui.bat
# 또는
python modern_gui.py
```

**Classic UI (tkinter 기반):**
```bash
python gui_watcher.py
```

### 3. 통합 수집 시스템 실행
```bash
python integrated_collector.py
```

### 4. 전체 기능 테스트
```bash
python test_all_completed.py
```

### 5. 브라우저 확장 설치
`README_BROWSER_EXTENSION.md` 참고 (chrome://extensions → 개발자 모드 → browser_extension 폴더 로드)

## 📊 데이터베이스 구조

### activities 테이블
- `id`: 고유 ID
- `timestamp`: 이벤트 발생 시간
- `action`: 동작 타입 (created, modified, deleted, moved, email_received, email_sent, meeting 등)
- `file_path`: 파일 경로 또는 활동 설명
- `file_type`: 파일 타입 (excel, powerpoint, text, email, calendar 등)
- `source`: 데이터 소스 (filesystem, vscode, orca, outlook, slack, claude_code, confluence, browser)
- `details`: 추가 정보 (JSON 형식)
- `created_at`: 데이터베이스 기록 시간

### weekly_summaries 테이블
- 주간 요약 데이터 저장

### file_stats 테이블
- 파일 타입별 통계 데이터

## ⚠️ 주의사항

- 데이터베이스 파일은 자동으로 감시 제외됩니다
- 로그 파일은 감시 대상에서 제외됩니다
- 대용량 폴더 감시 시 성능에 영향을 줄 수 있습니다
- 개인정보가 포함된 파일 경로가 저장될 수 있으니 주의 필요
- Outlook API 수집은 Outlook이 설치되어 있어야 하며 실행 중이어야 합니다
- IDE 수집은 해당 IDE가 설치되어 있어야 합니다
- Confluence 토큰 등 민감정보는 `config/*.json`에만 저장하고 `.gitignore`로 커밋 방지

## 🛠️ 기술 스택

- **Python 3.x**: 메인 프로그래밍 언어
- **Flet**: 현대적 GUI 프레임워크 (Material Design)
- **tkinter**: Classic GUI 프레임워크
- **watchdog**: 파일 시스템 감시 라이브러리
- **pywin32**: Windows API 및 Outlook 연동
- **SQLite**: 경량 데이터베이스
- **slack-sdk**: Slack API 연동
- **jinja2**: 보고서 템플릿 엔진
- **python-docx**: Word 문서 생성 (내장 템플릿 미사용, 자체 minimal docx 빌더 사용)
- **requests**: Confluence REST API 호출, 사내 LiteLLM Proxy 호출
- **psutil**: 실제 프로세스 실행 여부 감지 (Active Work Sessions)
- **사내 LiteLLM Proxy**: Outlook/Confluence 내용 AI 요약 (모델: claude-haiku-4-5)

## 📞 추가 정보

- **핵심 결정 사항**: <ref_file file="C:\Users\SSG\weekly_report_automation\decisions.md" />
- **최근 작업 내역과 다음 할 일**: <ref_file file="C:\Users\SSG\weekly_report_automation\progress.md" />
- **완료된 작업 로그**: <ref_file file="C:\Users\SSG\weekly_report_automation\archive\" />
