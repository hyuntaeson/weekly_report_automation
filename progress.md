# 최근 작업 내역과 다음 할 일

이 문서는 최근 작업 내역과 다음 할 일을 정리합니다. 2026-09-22 이전 작업 로그는 `archive/2026-09.md`를 참고하세요.

## 📅 최근 작업 내역 (2026년 9월 28일 ~ 10월 1일)

사용자가 실사용 중 발견한 3가지 문제를 조사/수정함.

### 1. 보고서 노이즈 필터링 강화
- **문제**: 보고서에 `C:\Users\SSG\Downloads\미확인 819675.crdownload`, `C:\Users\SSG\Documents\(DDr^7D3\(DDr^7D3.jpg` 같이 사람이 이해할 수 없는 파일 경로가 그대로 노출됨
- **조치**: `file_watcher.py`의 `should_exclude()`와 `report_generator.py`의 `_is_noise_activity()`에 동일 규칙 추가
  - `.crdownload`/`.part`/`.lock` 확장자, `.git` 내부 파일 제외
  - 오피스/OS 원자적 저장 중 생기는 8자리 16진수 임시 파일명 정규식(`_HEX_TEMP_NAME_RE`)으로 제외
  - 파일명에 `^` 포함 시 제외 (사내 DRM이 재암호화하며 만드는 깨진 파일명 패턴)
- **검증**: 사용자가 제시한 두 예시 파일 모두 필터링 확인, 정상 파일은 필터링 안 되는 것도 확인

### 2. Excel 수정 내용이 보고서에 안 나오는 문제 → 원인은 사내 DRM (Word와 동일 이슈)
- **문제**: `보안점검_모니터링계획.xlsx` 수정해도 보고서에 반영 안 됨
- **원인 조사**: 실제 파일의 매직바이트를 확인해보니 `D0 CF 11 E0 A1 B1 1A E1`(OLE2 시그니처)로, 원래 zip이어야 할 xlsx가 사내 DRM에 의해 재암호화되어 있었음. `openpyxl.load_workbook()`이 `zipfile.BadZipFile` 예외로 실패 → 기존 코드는 이를 조용히 삼키고 None 반환하고 있었음
- **결론**: 코드 버그가 아니라 환경적 제약 (Word 파일에서 이미 확인됐던 DRM 재암호화 현상이 Excel에도 동일하게 적용됨 — PPT도 동일 구조로 추정)
- **조치**: `zipfile.BadZipFile` 예외만 구분해서 잡고, 이 경우 `_drm_blocked_details()`로 "(내용 변경 감지됨 - 사내 보안 정책으로 암호화되어 상세 내용 확인 불가)"라는 fallback summary를 반환하도록 `_capture_word_content`/`_capture_ppt_content`/`_capture_excel_content` 전부 수정. 단순 파일 잠금(PermissionError 등)은 기존처럼 조용히 None 반환(다음 저장 시 재시도됨)
- **검증**: 실제 DRM 걸린 파일로 직접 호출해서 fallback 메시지 확인

### 3. 브라우저 활동이 한 번도 보고서에 안 나오는 문제 → GUI가 브라우저 서버를 안 켜고 있었음
- **원인 조사**: DB를 직접 조회해서 `source='browser'` 행이 지금까지 0건인 것을 확인. `modern_gui.py`의 "Start Tracking" 버튼(`start_tracking()`)이 `FileWatcher`만 시작하고, 크롬 확장이 POST하는 로컬 서버(`browser_activity_server.py`, 포트 5757)는 시작하지 않고 있었음
- **조치**: `start_tracking()`/`stop_tracking()`에 `BrowserActivityServer` 시작/종료 로직 추가
- **검증 완료 (2026-09-28)**: GUI에서 Start Tracking으로 포트 5757 리스닝 확인. 이후 조사에서 크롬 확장 자체가 설치되어 있지 않은 것도 발견(Chrome/Edge Secure Preferences 양쪽에 미등록) → 사용자가 `chrome://extensions`에서 개발자 모드로 `browser_extension/` 로드 + 활성화 → 실제 사내 사이트(Confluence/SharePoint/Bitbucket) 방문 기록 5건이 DB에 정상 기록됨을 확인. end-to-end 동작 검증 끝

### 검증
- `test_all_completed.py` 9/9 전체 재실행 통과
- 노이즈 필터 예시 2개 + 정상 파일 1개 별도 스크립트로 필터링 결과 확인
- 실제 DRM 걸린 xlsx 파일로 fallback 메시지 확인

### 4. 소소한 개선 묶음 (세션 인계 후 Devin 세션)
- **watcher/report 노이즈 규칙 비대칭 해소**: `~$*`, `*.tmp`, `*.cache`, `.~lock.*`가 `report_generator.NOISE_FILENAME_PATTERNS`에만 있고 `file_watcher` 기본 제외 패턴에는 없어서 config에 의존하던 문제 → watcher 기본 패턴에도 동일 규칙 추가
- **FileWatcher 스레드 누수 수정**: `start()`의 `while True: sleep(1)` 루프가 `stop_tracking()` 이후에도 계속 살아있어 재시작 때마다 스레드가 누적되던 문제 → `_running` 플래그로 종료되도록 수정 (daemon 스레드라 실해는 없었지만 클린업 목적)
- **검증**: 별도 스크립트로 `~$report.docx`/`plain.tmp` 필터링 및 stop() 후 스레드 종료 확인, `test_all_completed.py` 9/9 재통과

### 5. Teams 연동 완료: 캘린더 회의 감지 + 채팅 수집 (실제 동작 확인)
- **Teams 회의**: `outlook_collector.py` 캘린더 수집 시 `Location`/본문의 Teams 링크(`teams.microsoft.com` 등) 감지 → `details.is_teams_meeting` 플래그 + file_path "Teams Meeting: {제목}"
- **Teams 채팅**: `teams_collector.py` — 사내 DevX MCP 경유를 시도했으나 그 MCP의 토큰 캐시가 로컬 Qdrant를 요구해 불가 → Microsoft Office first-party client + 디바이스 코드 로그인을 Python으로 직접 구현. 토큰은 `config/teams_graph_token.json`에 저장(gitignore), refresh_token 자동 갱신
- **검증 완료**: 디바이스 코드 로그인 후 `/me/chats` 9개 채팅방 조회, 최근 7일 메시지 350건 수집·DB 저장 확인 (`source='teams'`)
- `integrated_collector.py`: Teams 수집 루프(30분 주기) 연결 + 기존 `stop()`의 `file_watcher.stop()` 중복 호출 버그 정리
- 최초 로그인/재로그인: `python teams_collector.py --login`

### 6. Teams 후속 개선 (같은 세션)
- **GUI Active Work Sessions에 Teams 추가**: `ms-teams.exe`(신형)/`teams.exe`(구형) 양쪽 감지
- **본인 메시지 식별**: 수집 시 `/me`로 displayName 조회→토큰 파일에 `me_display_name` 캐시, details에 `from_me` 플래그 (실제 로그인 계정: "손현태(이마트24 POS서버)")
- **주간보고서 "Teams 내 메시지 요약" 섹션 신설**: 주간 Teams 메시지 중 본인 발신만 골라 LLM 요약해서 표시 (Markdown+Word 양쪽). 본인 발신 메시지 상세 목록에도 메시지 본문(text)이 나오도록 `_extract_summary` 확장
- **Teams 일정(캘린더) 수집**: `/me/calendarview`로 주간 일정 수집 — 회의 제목/참석자 명단/주최자/온라인 회의 여부 포함해 `source='teams'`, `action='meeting'`으로 저장. 취소된 회의(isCancelled)는 제외. Outlook(COM)으로 수집된 동일 회의와의 중복은 `report_generator._dedupe_meetings`가 제목 기준으로 제거(정보가 풍부한 teams 쪽 우선)
- **배포 가이드**: README에 "다른 사용자에게 배포할 때" 섹션 추가 (1회 디바이스 코드 로그인 절차 + 주의사항)

### 7. 실제 보고서 리뷰 후 개선 (같은 세션)
- **OAuth 콜백 URL 차단**: background.js 필터에 `/callback`·`session_state`·`access_token`·`id_token`·`code=` 추가 + report 필터에도 동일 마커 적용(기존 DB 데이터까지 정화)
- **집계 일관성**: daily_counts/by_file_type을 DB 원시값이 아닌 노이즈 필터·중복제거 적용된 activities 기준으로 집계 → 총계와 일치
- **일시 파일 제거**: 같은 기간에 created+deleted가 모두 기록된 파일은 관련 이벤트 전부 제거 (DRM 임시파일 churn)
- **경로 정규화**: 윈도 드라이브 경로의 `/` 구분자를 `\`로 통일
- **1:1 채팅 이름 해석**: 멤버 목록→메시지 발신자 순으로 상대방 이름 추정("1:1 - 이름"). 외부 게스트 계정은 Graph가 이름을 안 주는 한계 있음("oneOnOne" 유지)
- **GUI**: Active Work Sessions에 Outlook(outlook.exe/olk.exe), Word(winword.exe) 추가

### 8. 보고용 개요 문서 + AI 적용 계획 수립
- `weekly_report_automation_overview.html`: Spharos 사내 템플릿 스타일의 프로젝트 개요 보고서 생성 (목적/구조/구현요소/AI기술/기대효과, 진행상태 제외)
- **사내 LiteLLM 프록시 임베딩 확인**: `azure/text-embedding-3-large`(dim 3072) 등 4개 임베딩 모델 + 다수 채팅 모델 이용 가능 → VectorDB/RAG/LCEL/LangGraph 전체 경로가 사내 인프라만으로 가능함을 검증
- **다음 단계(사용자 승인)**: ① 임베딩+VectorDB 의미 클러스터링 → "주제별 작업" 보고서 섹션 ② LCEL 요약 체인 표준화 ③ LangGraph 보고서 생성 파이프라인 노드화
- DRM 폴백 버그는 의도적 보류 — 암호화 문서 처리의 더 나은 방법을 검토 중

### 9. AI 적용 1단계: 임베딩 클러스터링 → "주제별 작업" 섹션 (완료)
- `activity_clusterer.py` 신규: 사내 LiteLLM 임베딩(`azure/text-embedding-3-large`, dim 3072) + 코사인 유사도 그리디 클러스터링(임계값 0.62, 외부 VectorDB 없이 인메모리)
- 클러스터명은 LLM이 대표 활동들을 보고 20자 주제명으로 생성 — 실측 결과 "신세계 개발 플랫폼 접근", "이마트24 POS 시스템 정기 점검", "POS서버 DB 접근 문제 해결" 등 정확한 주제 분류 확인
- `llm_summarizer.py`: 요약 전용 외에 범용 `complete(system_prompt, text)` 메서드 추가
- 보고서 Markdown/Word 양쪽에 "주제별 작업 (AI 분석)" 섹션 추가. LLM/임베딩 실패 시 섹션 생략 (폴백)
### 10. AI 적용 2단계: LCEL 요약 체인 표준화 (완료)
- `llm_summarizer.py`를 LangChain LCEL(`prompt | ChatOpenAI | StrOutputParser`)로 재작성 — 프록시가 OpenAI 호환이라 `base_url` 지정만으로 연결
- `PROMPT_TEMPLATES`에 소스별 프롬프트 분리: default/file/teams/mail/topic — `summarize(text, template="...")`로 선택
- 체인 내장 `with_retry(2회)`, 모델/프롬프트는 config·템플릿만 바꾸면 됨
- LangChain 미설치 환경에서는 기존처럼 None 반환 폴백 (선택 의존성)
- 호출자 연결: file_watcher→"file", outlook→"mail", teams 요약→"teams", 클러스터 명명→"topic"
- 의존성 추가: langchain-core 1.6.5, langchain-openai 1.6.6
### 11. AI 적용 3단계: LangGraph 보고서 파이프라인 (완료)
- `report_pipeline.py` 신규: `collect → filter → analyze → aggregate → output` 5노드 StateGraph
- `collect_weekly_data`를 `fetch_week_activities`/`analyze_week_activities`/`compose_weekly_data` 단계 함수로 분해 — 그래프 노드와 순차 경로가 같은 함수를 공유
- 조건 엣지: 활동 0건이면 analyze(LLM/임베딩)를 건너뛰고 바로 집계
- `generate_and_save_weekly_report`는 langgraph 경로 우선, ImportError/실패 시 순차 폴백
- 검증: 실제 데이터로 그래프 실행 동일 결과(111건, 주제 10개), 통합 테스트 9/9
- 의존성 추가: langgraph 1.2.12

### 12. macOS 이식 준비 (완료, macOS 실기 검증 필요)
- `modern_gui.py`: win32gui/win32process 가드 — 비Windows는 psutil 프로세스 존재로 판정. macOS 프로세스명(Slack/Teams/Outlook/Word/Chrome 등) 추가
- `outlook_collector.py`: win32com 가드 + COM 없으면 Graph 폴백 — teams_collector 디바이스 토큰으로 Inbox/SentItems 메일 수집. 캘린더는 teams_collector가 커버
- `ide_collector.py`: Windows/macOS/Linux 경로 후보 통합 (exists() 필터가 자동 분기)
- `requirements.txt`: `pywin32`를 `sys_platform == 'win32'` 조건부로
- macOS 실기 검증 필요: GUI 기동, Graph 디바이스 로그인, Outlook 메일 수집 동작 여부

### 13. 시나리오 테스트 스위트 + 보완 패치 (완료)
- `scenario_test.py` 신규: 32개 기능 시나리오(환경/수집/가공/AI/보고서/GUI) 실행 → `test_reports/`에 스타일된 Excel(결과+요약 시트) 자동 생성
- 보완 패치 적용:
  - Graph API 429 → Retry-After 기반 백오프 재시도 (실제 429 발생해 자동 복구 확인)
  - Outlook 수집: COM 실패 시 Graph 경로로 폴백 — Windows에서도 동일 적용 (플랫폼·실행 상태 무관)
  - 임베딩 영속화: `activity_embeddings` 테이블 추가, 활동 벡터 캐시 → 2회차 실행 22.6s→3.3s, 과거 활동 유사검색 기반 확보
  - 1:1 채팅 상대방 해석에 `/me/people` 매칭 추가 — GUID만 잡히던 외부 계정도 실명 해석 (8개 중 6개 성공)
  - 빈 주간 보고서 하이라이트에 "활동 없음" 명시
  - `is_app_running`을 `@staticmethod`로
  - `cleanup_data.py` 신규: data/ 테스트 산출물 정리 유틸 (dry-run 기본, --yes로 실행)
- 테스트 결과: PASS 31 / FAIL 0 / SKIP 1 (브라우저 서버는 트래킹 OFF라 정상 SKIP)

### 14. Teams 1:1 채팅 상대방 이름 해석 강화 (완료)
- 해석 체인 확장: 멤버 목록 → 최근 메시지 발신자 → **과거 메시지 히스토리 페이징(최대 300건)** → **chat id GUID를 /me/people 주소록과 매칭**
- 봇/알림 채팅 처리: `from.application.displayName`도 상대방으로 인식 → "봇 - 아이앤씨 알림" 등으로 표기
- 결과: 14개 중 12개 실명 해석. 미해결 2개는 사람이 아닌 채팅 — 시스템 메시지 1건뿐이거나 메시지 0건의 빈 채팅이라 해석 불가 ("1:1 - (상대방 정보 없음)" 표기)

### 15. OneNote 연동 — 섹션 수준 (제한적 완료, 2026-09-29)
- `onenote_collector.py` 신규: Teams Graph 토큰 재사용, 노트북/섹션의 `lastModifiedDateTime` 수집 → `source='onenote'`
- **권한 제한 확인**: 페이지 제목/본문은 `Notes.Read.All` 필요 → first-party client 사전승인 없음 (`AADSTS65002`). 디바이스 로그인으로 동적 동의 시도했으나 차단됨
- 데스크톱 OneNote 미설치 → COM 경로도 불가
- `.one` 파일 자체는 기존 파일 감시에서 이미 수정 이벤트로 잡힘 (Documents 감시 경로에 포함)
- IntegratedCollector에 30분 주기 수집 스레드 추가, GUI 소스 매핑(onenote→OneNote), scenario_test COL-11 추가

### 16. 보고자료 개편 + GUI 재구성 (2026-09-30)
- **`weekly_report_automation_overview.html` 9페이지 재구성**: 텍스트 표/목록 → 시각 중심
  - 목적: 문제 3카드 + 목표 수평 플로우 + "왜 로컬" 4카드
  - 구조: 데이터 흐름 수평 플로우 + AI 계층 4카드
  - 구현 요소: 표 → 소스 타일 그리드 9장 (방식 태그 + 한 줄 설명)
  - AI 기술: 사내 인프라 4카드 + 교육 기술 4카드 + RAG 미니 플로우
  - **WBS 페이지 추가**: 2026-10-01 착수 → 10-21 완료, 간트 바 스타일. 설계(10/1-6) → 개발 3트랙 병렬(수집기반/SaaS연동/AI·보고서, 10/7-16) → AI 테스트+사용자 테스트 병행(10/19-20) → 완료·발표(10/21)
- **발표 모드**: 우하단 컨트롤러(◀ ▶·페이지 표시·발표 모드·전체화면), 키보드 ←/→/PgUp/PgDn 이동, F=전체화면, 발표 모드=한 페이지씩 + 자동 전체화면, 인쇄 시 전체 출력
- **GUI 재구성** (`2ba72af`): 추적 자동 시작(Start Tracking 버튼 폐지 → "Tracking Active" 배지), 사이드바를 Dashboard+Settings로 축소(미구현 Tracked Apps/Reports 제거), Active Work Sessions에 OneNote 추가, Collect 수동 버튼 4개 제거(자동 수집이라 불필요), 하단 보고서 생성 패널·미리보기 버튼 제거 → Weekly Summary 하단에 전폭 Generate Weekly Report 버튼 (스크롤 없이 노출)

### 17. Teams 수집/보고 설정 사용자화 (2026-09-30)
- **`config/teams_settings.json`** + Settings 화면 "Teams 수집·보고 설정" 섹션: 수집 기간(일), 채팅 유형(1:1/그룹/회의), 보고서 범위(내 메시지/전체), 업무 관련만 요약(work_only)
- **채팅/메시지 상한 제거**: `@odata.nextLink` 전체 페이징으로 전량 수집 — 기존 상위 50방×50건 제한이 오래된 1:1 대화 누락 원인이었음. `stop_before`로 기간 이전 페이지는 조기 중단해 비용 방지
- **보고서에 보낸/받은 메시지 구분 표시**: "내가 보낸 메시지 n건 … (받은 메시지 m건)" / scope=all이면 주고받은 전체 요약
- **업무 관련 선별(work_only, 기본 ON)**: 요약 전 LLM이 업무 관련 메시지만 선별 — 인사·잡담·이모티콘 제외. 실패 시 전체 유지 폴백
- GUI 성능: 시작 시간 ~10s→~2.2s (lazy import + 프로세스 단일 스캔 + pyenv shim 우회 배치)

### 18. SharePoint/OneDrive 수집 + 제외 채팅방 설정 (2026-09-30)
- `sharepoint_collector.py` 신규: 동일 Graph 토큰 재사용(Files.Read.All). `/me/drive/recent` + `/me/drive/sharedWithMe`에서 기간 내 수정 파일 수집 → `source='sharepoint'` (파일명·수정자·webUrl·폴더 기록, 본문은 안 읽음)
- 공유 링크 디코딩(`u!`+base64url)으로 임의 공유 파일의 driveItem도 해석 가능 — 샘플 파일 접근 확인
- IntegratedCollector에 30분 주기 스레드 추가, GUI 소스 매핑(sharepoint→SharePoint), scenario COL-12 추가
- **제외 채팅방 설정**: `excluded_chats`(id+제목) — 수집 시 스킵 + 보고서에서도 제외(과거 데이터 포함). Settings에서 "채팅방 목록 불러오기" 버튼으로 체크 선택
- **수집 속도 최적화**: 전체 채팅방(실측 903개) 중 `lastUpdatedDateTime`이 수집 기간 이전인 방은 메시지 조회 생략 — 무제한 페이징 도입 후 생긴 수백 회 API 호출 문제 해소. list_chats는 멤버 조회 병렬화(8 workers)

### 19. 주간보고서 형식 개편 — STEP 1 프로그램별 / STEP 2 업무 요약 (2026-09-30)
- `program_sections.py` 신규: 활동을 **프로그램 단위**(Excel·Word·PowerPoint·OneNote·Notepad·Outlook·Teams·Slack·Confluence·Chrome·Claude Code(IDE)·Devin(IDE))로 묶고 **■ 프로그램 → ① 항목 → 내용** 구조로 출력. 날짜별 묶음은 가독성 문제로 사용자 요청에 따라 주 단위로 합침
- 매핑: VSCode·Orca → Claude Code(IDE), SharePoint 오피스 문서 → 확장자별 Excel/Word/PPT (스크린샷·zip 등은 제외)
- 항목 요약 **500자**까지 (STEP 2가 STEP 1을 재요약하므로 재료 확보), 요약 안 "1. 2. 3." 번호 목록은 줄바꿈 분리(IP·버전 오탐 방지)
- 파일은 "수정 1건" 대신 "무엇을 수정함"으로 표기, 수집기마다 다른 타임스탬프 형식(UTC·+09:00·epoch ms·Outlook COM)을 로컬 시간으로 통일
- **공유 문서 변경** 섹션: 파트원만 수정한 SharePoint 문서는 별도 섹션으로 분리하고 STEP 2·주제 분석에서 제외 (사용자가 파트원 업무 더블체크 용도로 요청)
- STEP 2: STEP 1 전체(최대 12,000자)를 LLM에 넘겨 핵심 요약 생성, LLM 미사용 시 규칙 기반 요약. Word 출력도 같은 구조(프로그램 13.5pt·항목 12pt 굵게)
- `LLMSummarizer.complete()`에 `max_tokens`·`max_input`·`temperature` 실제 반영 (기존엔 무시되어 500자 요약이 잘릴 수 있었음)

### 20. "무엇을 수정했는지" 요약 — SharePoint·VSCode·Claude Code (2026-09-30)
- **SharePoint**: Graph로 날짜별 버전을 받아 비교 → 수정자 이름과 함께 변경 내용 LLM 요약. 다운로드 파일도 사내 DRM으로 암호화되어 있어 **Office COM으로 읽음**. 같은 버전 쌍은 DB 캐시 재사용(첫 수집 113s → 재수집 13s). 현재 버전은 `/versions/{id}/content`가 안 돼서 `/content` 사용, `.xls`는 원래 확장자로 저장해야 열림
- `office_reader.py` 신규(공용 COM 리더): 범위 일괄 읽기(셀 단위 79s → 2s), `DispatchEx`로 별도 인스턴스 + 다른 문서가 열려 있으면 Quit 안 함(사용자 Office 창 보호), 워커 스레드 COM 초기화. `file_watcher`도 이 모듈 사용
- **VSCode**: 로그 파일 수정 시각 대신 **Local History 스냅샷**을 파일·날짜별로 비교해 요약 (처음 저장본은 "무슨 내용인지" 요약, 자체 `reports/` 폴더 제외)
- **Orca**: `orca-stats.json`의 agent_start/stop으로 프로젝트별 에이전트 작업 시간 집계 → 항목 제목에 표시
- **Claude Code**: 요청 기록을 프로젝트·날짜별로 LLM 요약. 지시문을 모델이 자기에게 하는 말로 오인해 거절·되묻기하던 문제 → 완료형 항목 변환 프롬프트 + `temperature=0` + 번호 목록 아닌 응답·되묻기 문구는 실패 처리(캐시 안 하고 재시도)
- DB `get_details_cache()` 추가 — 버전·스냅샷·요청 묶음 단위 요약 재사용

### 21. Generate Report 전 1회 수집 (2026-09-30)
- 원인 발견: GUI는 파일 감시·브라우저 서버만 상시 실행 → **Claude Code·IDE·Outlook·Teams·OneNote·SharePoint가 GUI 사용 시 전혀 수집되지 않았음** (Claude Code 요청 기록 DB 0건이었던 이유)
- `IntegratedCollector.collect_once(days=7)` 추가, GUI "Generate Report"가 보고서 생성 직전 호출 (한 소스 실패해도 계속 진행). 대신 생성 시 약 1분 40초 추가 대기
- 시나리오 테스트: PROC-06(공유 문서 분리)·PROC-07(번호 목록 분리)·COL-13(COM 읽기+버전 diff) 추가 — 36건 통과

### 22. 킥오프 보고자료 개편 및 발표 완료 (2026-09-30 ~ 10-01)
- `weekly_report_automation_overview.html` 9쪽: 표지 · 목적 · 활용하는 AI 기술 · 시스템 구조 · 시스템 구성도 · 추진 일정 · 실행 화면(샘플) · 생성 결과(샘플 보고서) · STEP 3 예상 질문(샘플)
- 모든 쪽 1120×630 한 장 고정 + 발표 모드 화면 맞춤 확대, 다이어그램 인라인 SVG 재작성, 7·8쪽은 카드 내부 스크롤
- 발표에서 약속한 신규 범위: **VectorDB 도입, RAG 질의 섹션, STEP 2 이슈·리스크/다음 주 계획, STEP 3 예상 질문(예상질문자 설정), 전체 LLM 출력 검증** → 아래 "다음 할 일" 1·2번
- 킥오프 기준(청중은 구현 진행을 모름)으로 구현 흔적 제거, 샘플 보고서는 발표용 정리본. 10/01 발표 완료
- 좋았던 작성 원칙은 `C:\01.AI\AI_Context\2026\02.html-report\SKILL.md`에 반영

### 23. RAG 주제 질의 섹션 (2026-10-01)
- `rag.py` `TopicQueryRAG`: Settings 주제마다 VectorDB(Qdrant)에서 이번 주 활동(상위 10)과 지난 N주 활동(상위 3)을 검색 → 번호 붙인 근거만으로 LLM 요약 → STEP 2 "주제별 작업" 바로 아래 **"주제 질의 요약"** (Markdown·Word)
- 기본 주제: 장애 대응·배포·테스트·결제 연동·교육·역량 개발·손익·예산·구매·계약 (행정 업무 포함). 지난 기록 범위 기본 4주. 관련 기록이 없는 주제는 생략
- 검색 대상은 STEP 2와 같은 기준: 내 업무만, 제외 채팅방·Teams 보고 범위 반영, 제목 없는 Chrome 방문 URL 제외
- **질의 확장**: 짧은 주제명("장애 대응")은 실제 기록과 유사도가 낮아(최고 0.38) 놓침 → LLM이 주제별 관련 키워드를 1회 생성해 질의에 붙임(`data/rag_topic_queries.json` 캐시). 장애 대응·결제 연동이 잡히게 됨. 유사도 기준 0.40
- **근거 검증(하네스)**: 불릿마다 `[n]` 인용 필수, 인용이 없거나 없는 번호를 단 불릿은 버림, 불릿당 인용 최대 3개, NONE이면 섹션 생략, LLM 실패 시 근거 출처로 대체. 근거 표시는 "09/25 Teams · 채팅방" 출처만(본문 미노출), 같은 출처는 한 번호로 병합
- 지난 기록은 이번 주와 이어질 때만 "(지난 기록) …" 불릿으로 연결 — 의미가 전달되게 1~2문장 허용
- Settings 화면 "보고서 설정 — 주제 질의": 주제 칩 추가·삭제, 지난 기록 검색 범위(주) → `config/report_settings.json`
- `vector_store.search_many`(저장소 1회 열기로 여러 검색), `activity_clusterer.embed_activities` 추가. `retrieve()`는 STEP 3(발신자 필터)에서 재사용 예정
- 실데이터(09/24~09/30): 장애 대응·배포·테스트·결제 연동·교육·역량 개발 4개 섹션, 약 20초
- 시나리오 테스트: AI-04(근거 인용 검증)·AI-05(실데이터 RAG)·GUI-05(주제 설정) 추가, RPT-03이 `reports/` 대신 `test_reports/`에 저장하도록 수정 — 41 PASS / SKIP 1(Outlook)

### 알려진 잔여 이슈
- ~~`.docx`/`.pptx` DRM fallback 미작동~~ → **해소**: OLE2 매직바이트로 판별 후 COM 읽기 (`file_watcher._is_ole2`)
- **DRM 내용 추출**: Windows + Office 환경은 COM으로 동작. macOS는 수정 이벤트만 기록 — 사내 DevX `DocumentLoader.yaml` 워크플로우 검증 여지
- **LiteLLM 프록시 일시 오류**: 15초 타임아웃·502 Bad Gateway 간헐 발생. 요약 실패는 캐시하지 않고 다음 수집 때 재시도
- **공유 문서 수정자 구분**: 하루 단위 버전 비교라 같은 날 여러 명이 고치면 "A, B: …"로 묶임 (사람별 구분하려면 버전마다 비교 필요)

## 🎯 다음 할 일 (2026-10-01 킥오프 발표 기준)

> 크기: S = 1일 이내 · M = 2~3일 · L = 1주 이상. 추천 순서: 1-4 → 1-1 → 1-3 → 1-2 → 1-5

### 1. 신규 개발 — 발표에서 보여줬지만 아직 없는 기능
1-1. ~~**VectorDB 도입**~~ ✅ **완료 (2026-10-01)** — Qdrant 로컬 모드(`vector_store.py`, `data/qdrant`, 서버 없음). 활동별 벡터 + 소스·로컬 날짜·시각·Teams 발신자/채팅방 메타데이터, 날짜·소스·발신자 필터 검색. 클러스터링 캐시를 Qdrant로 전환, 기존 SQLite 임베딩 816건 이전(원본 활동이 지워진 36건 제외). 로컬 모드는 한 프로세스만 열 수 있어 작업마다 열고 닫음. 테스트 PROC-08
1-2. ~~**RAG 의미 질의 섹션**~~ ✅ **완료 (2026-10-01)** — 아래 항목 23
1-3. **STEP 3 예상 질문 & 답변** (L, 9쪽) — ① 예상질문자 대화 별도 수집(Teams 발신자 이름 기준, 내가 참여한 대화·업무 메시지만) ② 질문 성향 분석 ③ 보고서와 맥락 비슷한 대화 검색(1-1·1-2 활용) ④ 예상 Q&A 생성(근거 없는 내용은 "확인 필요") ⑤ MD·Word에 STEP 3 섹션
1-4. ~~**예상질문자 설정 UI**~~ ✅ **완료 (2026-10-01)** — Settings > Teams "보고서 범위" 아래 입력·칩 추가/삭제, `teams_settings.json`의 `expected_questioners`(Teams 표시 이름 일부 일치용). 설정 저장 경로를 읽기와 같은 절대 경로로 통일. 테스트 GUI-04
1-5. **STEP 2 보강 섹션** (M, 8쪽) — "주요 이슈 & 리스크" 표(구분·내용·상태)와 "다음 주 계획" LLM 생성

### 2. 보완 — 있지만 발표 수준에 못 미치는 것
2-1. **주제별 작업 표시 정리** (S) — 예시에 긴 경로·URL·"Teams 채팅: …" 원문이 나열됨 → 짧은 이름으로
2-2. **LLM 출력 검증 확대** (S, 4쪽 ⑤) — 형식 검증·재시도가 Claude Code 작업 요약에만 적용 → 공통 요약 모듈로 확대
2-3. **로컬 파일 요약을 "무엇을 바꿨는지"로** (S) — 로컬 Excel·Notepad는 "무슨 파일인지"로 요약됨 → 변경 요약 프롬프트로 통일
2-4. **보고서 생성 대기 시간 단축** (M) — 생성 직전 1회 수집으로 약 1분 40초 대기 → GUI 실행 중 백그라운드 주기 수집, 버튼은 증분만
2-5. **Word 출력 동기화** (S) — 1-3·1-5 신규 섹션을 Word에도 같은 구조로 (1-2 주제 질의 요약은 반영됨)
2-6. **RAG 품질 관찰** (S) — 주제 질의가 행정 업무(손익·구매·계약)를 실제로 잡는지 해당 업무가 있는 주에 확인, 필요 시 유사도 기준(0.40)·질의 키워드 조정 (`data/rag_topic_queries.json` 삭제 시 재생성)

### 3. 검증 — 구현됐지만 실데이터 확인 못 한 것
3-1. SharePoint Word·PPT 버전 비교 (Excel만 실데이터 확인)
3-2. 로컬 DRM 파일 COM 읽기 — 파일 감시 스레드 COM 초기화 수정 후 실제 저장으로 확인
3-3. macOS 실기 검증 (발표 2쪽 "OS 무관") — GUI 기동·Graph 로그인·Outlook 수집
3-4. Word/PPT가 DRM 재암호화 후에도 MS Office에서 정상 열람되는지 육안 확인

### 4. 운영·정리
4-1. ~~미커밋 코드 커밋~~ ✅ 2026-10-01 커밋·푸시 완료
4-2. `decisions.md`에 보고서 형식·VectorDB·STEP 3 결정 기록
4-3. Slack 연동 — Bot Token 사내 승인 대기
4-4. 자체 Slack MCP(발표 3쪽 "제작·마켓플레이스 배포") 실제 진행 상태 확인
4-5. 자동 스케줄링(선택) — Windows 작업 스케줄러로 매주 자동 생성
4-6. 데이터 정리 — `data/` 테스트 산출물 누적 (`python cleanup_data.py --yes`)

## 📊 현재 상태

**완료율**: 약 95% (수집 소스 11개, GUI 완성, Teams 사용자 설정 완료 — Slack 토큰 발급과 자동 스케줄링만 남음)

**핵심 성과**:
- 파일 시스템(실시간 감시+내용 캡처: txt/md/docx/pptx/xlsx), IDE, Outlook(API), Slack(설정만 남음), Claude Code, Confluence(AI 요약), 브라우저(Chrome, 서버 기동 이슈 수정) — 데이터 소스 정상 동작
- 주간보고서 생성 완료 (Markdown + Word, 액션별 실제 내용 상세 포함, 노이즈 필터링)
- AI 기반 요약 (사내 LiteLLM Proxy) + 캐싱으로 비용/속도 최적화
- Active Work Sessions 실시간 프로세스 감지
- DB 무결성(중복 제거 + upsert) 확보
- Settings 화면에서 감시 폴더 추가/삭제 UI 완료

## ⚠️ 현재 제한사항

1. **사내 DRM/문서보안 솔루션 개입**: `.docx`/`.xlsx`/`.pptx` 파일이 로컬에 저장된 직후 자동으로 OLE2 암호화 컨테이너로 재저장됨. 코드로 해결 불가 — 대신 "변경 감지됨" fallback 메시지로 최소한의 정보는 보고서에 남기도록 대응함. 실제 MS Office에서는 정상 열람될 것으로 추정 (육안 확인 필요)
2. **Notepad류 캡처는 저장 시점만**: 미저장 상태의 실시간 타이핑 내용은 캡처 불가
3. **UI 자동클릭 스크롤 한계**: Flet 앱의 스크롤 영역에 대한 자동화 도구 마우스 휠 이벤트가 인식 안 됨. 실사용 검증은 사용자 직접 클릭 권장
4. **Outlook API**: Outlook이 설치되어 있어야 하며 실행 중이어야 함
5. ~~브라우저 수집~~ **해결됨 (2026-09-28)**: GUI Start Tracking → 서버 기동 → 확장 프로그램 → DB 기록까지 실사용 검증 완료
6. ~~Teams 연동 미착수~~ **해결됨 (2026-09-28)**: Office first-party client + 디바이스 코드 로그인으로 채팅·일정 수집
7. **Devin 연동 불가**: 클라우드 전용 서비스로 로컬 로그 파일 없음

## 🔗 관련 문서

- **핵심 결정 사항**: <ref_file file="C:\Users\SSG\weekly_report_automation\decisions.md" />
- **완료된 작업 로그**: <ref_file file="C:\Users\SSG\weekly_report_automation\archive\2026-09.md" />
- **프로젝트 개요**: <ref_file file="C:\Users\SSG\weekly_report_automation\README.md" />
