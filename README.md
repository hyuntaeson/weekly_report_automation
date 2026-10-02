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
- Teams (회의 + 채팅 메시지)
- OneNote (노트북·섹션 수정 이력 — Graph 권한 제한으로 페이지 본문은 불가)
- SharePoint/OneDrive (본인 드라이브 + 공유받은 파일의 수정 이력)

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
- [x] AI 의미 분석: 임베딩 클러스터링으로 주간 활동을 주제 단위로 자동 분류 (주제별 작업 섹션)
- [x] 임베딩 영속 저장: VectorDB(Qdrant)에 벡터 누적 — 재실행 시 캐시 재사용
- [x] 보고서 생성 LangGraph 파이프라인 (collect→filter→analyze→aggregate→output 노드화)
- [x] 전체 기능 시나리오 테스트 — Excel 결과 자동 생성 (`tests/scenario_test.py`)
- [x] GUI 자동 추적 시작 + 시작 시간 최적화 (~10s→~2s)
- [x] Teams 수집/보고 기준 사용자 설정 (기간·채팅유형·제외 채팅방·업무만 요약)
- [x] SharePoint/OneDrive 파일 수정 이력 수집 (동일 Graph 토큰 재사용)
- [x] VectorDB(Qdrant 로컬 모드) — 활동 임베딩 + 날짜·소스·발신자 필터 검색
- [x] RAG 주제 질의 요약 (STEP 2) — Settings 주제별 근거 인용 요약, 지난 4주 기록 연결
- [x] STEP 3 예상 질문 & 답변 — 예상질문자(Teams) 질문 성향 학습 → 예상 Q&A 5개, 근거 없으면 '확인 필요'
- [x] 근거 노이즈 필터 — IDE 기록·근거 제외 키워드(Settings)·이름뿐인 기록·단순 대답은 RAG/STEP 3 근거에서 제외, 근거는 출처 + 내용 요지로 표기
- [x] 요약 글자 수 제한 정리 — 요약은 자르지 않고 의미 전달 우선, 긴 Teams 메시지·지난 대화는 LLM 요약
- [x] LLM 출력 하네스 — 요약 거절·되묻기 재요청, 근거 번호-문장 관련성 검증, STEP 3 답변 사실 대조('근거와 다름' 표시)
- [x] STEP 3 2단계 근거 검색(질문별 근거 보강·재답변) + 판정 전용 모델(`litellm_config.json`의 `judge_model`, 예: Opus 5.5)
- [x] 프로젝트 문서(progress.md 등) 근거 수집 + 지난 보고서 2차 근거
- [x] STEP 3 회귀 평가 — 사용자 확정 정답셋(`data/eval/gold.json`) + `tests/eval_step3.py`
- [x] 주제별 작업 표시 정리 — 짧은 예시 이름, 개인 활동 주제 제외
- [x] STEP 2 주요 이슈 & 리스크 표 + 다음 주 계획 (근거 인용·상태는 기록 기준·지난 일정 제외)
- [x] 메인 화면 정리 — Active Work Sessions 6×2, 보고서 생성 패널, 창을 작업 영역 안에 맞춤
- [x] 나만의 비서 — 메인 카드 09:00 오늘 할 일(전 근무일 메일·Teams·1:1·일정·이월) / 17:00 진행 점검·이월 (지금은 버튼 실행)
- [x] 나만의 비서 자동 실행(근무일 09:00·17:00, 놓치면 켤 때) + Settings 공휴일 입력
- [ ] 나만의 비서 알림 채널 (md / 메일 / Teams 나에게)
- [x] 보고서 생성 속도 개선(분석 병렬화·LLM 캐시·10분 내 재수집 생략) + 메인 화면 생성 상태 표시(요청 시각·진행 단계·폴더 바로가기)
- [x] 저장소 보관 정책 — Settings에서 활동 벡터 보관 기간(8~104주) 선택, 지난 주는 주간 요약 벡터로 영구 보관, 현재 사용량·예상 속도 표시
- [x] macOS 이식 준비 — win32 가드, Outlook은 Graph 폴백으로 플랫폼 무관 수집
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
| Modern GUI | ✅ 완료 | Flet 기반 UI — 추적 자동 시작, Weekly Summary + Generate Report 단일 CTA, 실시간 프로세스 감지 |
| AI 의미 분석 | ✅ 완료 | 임베딩 클러스터링 → 보고서 "주제별 작업" 섹션 (흩어진 활동을 주제로 묶음) |
| 임베딩 캐시 | ✅ 완료 | VectorDB(Qdrant)에 누적, 2회차 보고서 생성 시 재계산 불필요 |
| 저장소 보관 정책 | ✅ 완료 | 활동 벡터는 보관 기간(Settings)만, 지난 주는 주간 요약 벡터로 영구 보관 — 원본 활동은 유지 |
| LangGraph 파이프라인 | ✅ 완료 | 보고서 생성을 노드/엣지 그래프로 — 활동 없으면 분석 스킵 분기 |
| macOS 이식 | ✅ 코드 준비 | win32 가드, Outlook Graph 폴백 (맥에서 실기 검증 필요) |
| Teams 사용자 설정 | ✅ 완료 | Settings 화면에서 수집 기간/채팅 유형/제외 채팅방/보고서 범위/업무만 요약 선택 |
| SharePoint/OneDrive 수집 | ✅ 완료 | `/me/drive/recent` + `sharedWithMe`에서 기간 내 수정 파일 수집 |

### 데이터 소스

| 소스 | 상태 | 수집 방법 |
|------|------|----------|
| 파일 시스템 | ✅ 완료 | 실시간 감시 + 텍스트 파일 내용 diff/AI 요약 |
| VSCode | ✅ 완료 | 로그 파일 + 최근 파일 |
| Orca IDE | ✅ 완료 | 로그 파일 |
| Outlook | ✅ 완료 | COM API (Windows) 또는 Graph 폴백 (macOS/Linux·Outlook 미실행 시) |
| Slack | ⚙️ 설정 중 | Web API (Bot Token 필요) |
| Claude Code | ✅ 완료 | `~/.claude/history.jsonl` + `sessions/*.json` |
| Confluence | ✅ 완료 | REST API (PAT Bearer) + AI 요약 |
| 브라우저 | ✅ 완료 (Chrome only) | MV3 확장 + 로컬 HTTP 서버 |
| Teams | ✅ 완료 | 채팅+일정=Graph 위임권한(디바이스 로그인), 1:1 대화 상대방 실명 해석 |
| OneNote | ✅ 완료 (제한적) | Graph 위임권한 — 노트북/섹션 수정 시각 수집. 페이지 제목·본문은 `Notes.Read.All` 미승인으로 불가 |
| SharePoint/OneDrive | ✅ 완료 | Graph 위임권한 (Files.Read.All) — 최근 수정 파일 + 공유받은 파일 |

### 테스트 결과

전체 통합 테스트 100% 통과 (9/9 기능)

## 📁 프로젝트 구조

```
weekly_report_automation/
├── weekly_report/                # 소스 패키지 (python -m weekly_report → GUI 실행)
│   ├── paths.py                  # config/·data/·reports/ 등 경로를 한 곳에서 관리 (루트 기준 절대 경로)
│   ├── collectors/               # 데이터 수집기
│   │   ├── file_watcher.py       # 파일 시스템 실시간 감시 + Office 내용 캡처
│   │   ├── browser_server.py     # 브라우저 확장 수신용 로컬 HTTP 서버 (5757)
│   │   ├── ide.py                # IDE 활동 (VSCode Local History, Orca)
│   │   ├── ai_tool.py            # Claude Code 요청 기록 + 작업 요약
│   │   ├── outlook.py            # Outlook 메일·일정 (Graph/COM)
│   │   ├── teams.py              # Teams 채팅·일정 (Graph, 디바이스 코드 로그인)
│   │   ├── onenote.py            # OneNote 노트북·섹션 변경 (Graph)
│   │   ├── sharepoint.py         # SharePoint/OneDrive 수정 파일 + 버전 비교 (Graph)
│   │   ├── confluence.py         # Confluence 페이지 (AI 요약)
│   │   ├── slack.py              # Slack (토큰 승인 대기)
│   │   ├── project_docs.py       # 이 프로젝트 문서 변경분·지난 보고서 → 근거 전용
│   │   └── integrated.py         # 통합 수집기 (상시 감시 + 보고서 직전 1회 수집)
│   ├── storage/
│   │   ├── database.py           # SQLite 활동 DB (upsert, 요약 캐시)
│   │   ├── todos.py              # 할 일 저장소 (체크·제외·이월·실행 기록)
│   │   ├── vector_store.py       # Qdrant 로컬 VectorDB (활동 임베딩 + 메타데이터 필터 검색, 주간 요약)
│   │   └── retention.py          # 저장소 보관 정책 (요약 저장 후 지난 벡터 정리, 사용량 측정)
│   ├── ai/
│   │   ├── llm_summarizer.py     # 사내 LiteLLM Proxy 요약기 (LCEL 체인, 소스별 프롬프트)
│   │   ├── clusterer.py          # 임베딩 의미 클러스터링 → "주제별 작업"
│   │   ├── todos.py              # 나만의 비서 09:00 오늘 할 일 추출 (+ md 내보내기)
│   │   ├── progress.py           # 나만의 비서 17:00 진행 점검·이월
│   │   ├── issues.py             # STEP 2 주요 이슈 & 리스크·다음 주 계획 (근거 인용 검증)
│   │   └── rag.py                # RAG 주제 질의 → "주제 질의 요약" (근거 인용 검증)
│   ├── report/
│   │   ├── sections.py           # STEP 1 프로그램별·항목별 섹션 빌더
│   │   ├── generator.py          # 주간보고서 생성 (Markdown + Word)
│   │   ├── pipeline.py           # LangGraph 파이프라인 (collect→filter→analyze→aggregate→output)
│   │   └── templates/            # weekly_report.md.j2, blank_report_template.docx
│   ├── common/
│   │   ├── office_reader.py      # DRM 문서용 Office COM 리더
│   │   └── timeutil.py           # 수집기별 timestamp → 로컬 시각 통일
│   └── gui/                      # Flet GUI (WeeklyPulseApp = 화면별 mixin 조합)
│       ├── app.py                # 창·사이드바·화면 전환, main()
│       ├── dashboard.py          # 대시보드 (앱 감지·통계·보고서 생성 버튼)
│       ├── watch_settings.py     # Settings 뼈대 + 감시 폴더
│       ├── teams_settings.py     # Settings > Teams 수집·보고 설정
│       ├── report_settings.py    # Settings > 보고서 설정 (RAG 주제 질의·근거 제외 키워드)
│       ├── storage_settings.py   # Settings > 저장소 관리 (보관 기간·사용량)
│       ├── todo_card.py          # 메인 '오늘 할 일' 카드 (09:00/17:00 자동 실행)
│       ├── assistant_settings.py # Settings > 나만의 비서 (자동 실행·공휴일)
│       ├── actions.py            # 추적·수집·보고서 생성 동작
│       └── widgets.py            # 공용 컨트롤
├── tests/
│   ├── scenario_test.py          # 전체 기능 시나리오 테스트 (62건 → test_reports/*.xlsx)
│   ├── eval_step3.py             # STEP 3 정답셋 회귀 평가 (→ test_reports/eval_step3_*.md)
│   └── legacy/                   # 구버전 테스트 (test_all_completed 등)
├── scripts/
│   ├── cleanup_data.py           # data/ 테스트 산출물 정리
│   └── check_database.py         # DB 내용 확인
├── docs/
│   └── weekly_report_automation_overview.html  # 킥오프 발표자료
├── browser_extension/            # Chrome MV3 확장 (README.md = 설치 안내)
├── config/                       # 설정 (토큰·API 키 파일은 gitignore)
│   ├── watch_config.json         # 감시 폴더 목록
│   ├── teams_settings.json       # Teams 수집/보고 설정 (Settings 화면에서 저장)
│   ├── report_settings.json      # 보고서 설정 — RAG 주제 (Settings 화면에서 저장)
│   ├── slack_config.json / confluence_config.json / litellm_config.json / teams_graph_token.json
├── data/                         # activities.db, qdrant/, 캐시 (gitignore)
├── reports/                      # 생성된 주간보고서 (gitignore)
├── test_reports/                 # 테스트 결과·테스트용 보고서 (gitignore)
├── logs/                         # 로그 (gitignore)
├── archive/                      # 완료된 작업 로그, legacy/ (구 tkinter GUI·UI 시안 등)
├── run_modern_gui.bat            # GUI 실행 (pythonw -m weekly_report)
├── requirements.txt
├── README.md · AGENTS.md · PROJECT_STATUS.md · progress.md · decisions.md
```

## 🚀 설치 및 실행

### 1. 필요한 라이브러리 설치
```bash
pip install -r requirements.txt
```

### 2. GUI 프로그램 실행 (권장)
```bash
run_modern_gui.bat
# 또는 (콘솔 로그 확인)
python -m weekly_report
```

### 3. 통합 수집 시스템 실행 (GUI 없이)
```bash
python -m weekly_report.collectors.integrated
```

### 4. 전체 기능 테스트
```bash
python tests/scenario_test.py
```

### 5. 브라우저 확장 설치
`browser_extension/README.md` 참고 (chrome://extensions → 개발자 모드 → browser_extension 폴더 로드)

## 📊 데이터베이스 구조

### activities 테이블
- `id`: 고유 ID
- `timestamp`: 이벤트 발생 시간
- `action`: 동작 타입 (created, modified, deleted, moved, email_received, email_sent, meeting 등)
- `file_path`: 파일 경로 또는 활동 설명
- `file_type`: 파일 타입 (excel, powerpoint, text, email, calendar 등)
- `source`: 데이터 소스 (filesystem, vscode, orca, outlook, slack, claude_code, confluence, browser, teams, onenote, sharepoint)
- `details`: 추가 정보 (JSON 형식)
- `created_at`: 데이터베이스 기록 시간

### weekly_summaries 테이블
- 주간 요약 데이터 저장

### file_stats 테이블
- 파일 타입별 통계 데이터

### VectorDB (Qdrant 로컬, `data/qdrant/`)
- `activities` 컬렉션: 활동별 임베딩(3072차원) + 소스·날짜·발신자 메타데이터 — 보관 기간(Settings, `config/report_settings.json`의 `vector_retention_weeks`)이 지난 주는 삭제
- `week_summaries` 컬렉션: 주당 1개, STEP 2 요약 임베딩 — 영구 보관, 장기 질의용
- (레거시 SQLite `activity_embeddings` 테이블은 Qdrant 이전 후 저장소 정리 때 삭제됨)

## 👥 다른 사용자에게 배포할 때

각 사용자가 본인 PC에서 1회만 수행하면 되는 설정:

1. `pip install -r requirements.txt`
2. **Teams 로그인**: `python -m weekly_report.collectors.teams --login` 실행 → 화면에 표시되는 코드를 https://login.microsoft.com/device 에 입력 (본인 회사 MS 계정). 완료되면 `config/teams_graph_token.json`이 생성되고, 이후에는 refresh_token으로 자동 갱신되어 재로그인 불필요
3. **Chrome 확장**: `chrome://extensions` → 개발자 모드 → `browser_extension` 폴더 로드
4. `config/watch_config.json`의 `watch_paths`를 본인 작업 폴더로 수정
5. Slack/Confluence/LiteLLM을 쓰려면 각각 `config/*_config.json`에 본인 토큰 발급

**macOS/Linux도 동작**: pywin32는 자동으로 스킵되고, Outlook 대신 Teams 토큰으로 Graph 메일 수집, GUI는 프로세스 존재 기반으로 앱 활성 상태 감지

**주의**: 토큰 파일(`config/teams_graph_token.json`, `config/*_config.json`)은 개인 인증정보이므로 공유/커밋 금지 — `.gitignore`로 이미 제외되어 있음. 토큰은 Azure 앱 등록 없이 Microsoft Office first-party client의 위임 권한으로 발급되며, 각자 본인 데이터만 조회 가능

## ⚠️ 주의사항

- 데이터베이스 파일은 자동으로 감시 제외됩니다
- 로그 파일은 감시 대상에서 제외됩니다
- 대용량 폴더 감시 시 성능에 영향을 줄 수 있습니다
- 개인정보가 포함된 파일 경로가 저장될 수 있으니 주의 필요
- Outlook 수집은 Windows에선 Outlook 실행이 필요하지만, 미실행 또는 macOS에서는 Graph로 자동 폴백됩니다 (Teams 로그인 토큰 재사용)
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
- **사내 LiteLLM Proxy**: Outlook/Confluence 내용 AI 요약 (모델: claude-haiku-4-5), `text-embedding-3-large` 임베딩
- **LangChain (LCEL)**: LLM 호출 체인 표준화 — 소스별 프롬프트 템플릿, 재시도 내장
- **LangGraph**: 보고서 생성 파이프라인을 상태 그래프로 노드화

## 📞 추가 정보

- **핵심 결정 사항**: <ref_file file="C:\Users\SSG\weekly_report_automation\decisions.md" />
- **최근 작업 내역과 다음 할 일**: <ref_file file="C:\Users\SSG\weekly_report_automation\progress.md" />
- **완료된 작업 로그**: <ref_file file="C:\Users\SSG\weekly_report_automation\archive\" />
