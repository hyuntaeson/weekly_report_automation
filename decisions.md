# 핵심 결정 사항

이 문서는 프로젝트에서 내린 아직 유효한 핵심 결정과 그 이유를 정리합니다. 폐기된 결정은 취소 사유와 함께 표시합니다.

## ✅ 유효한 결정

### 1. 프로그래밍 언어: Python

**결정**: Python 3.x 사용

**이유**:
- 다양한 라이브러리 지원 (watchdog, pywin32, slack-sdk 등)
- 쉬운 통합과 빠른 개발 가능
- Windows API 및 Outlook 연동 지원 (pywin32)
- 데이터베이스 작업에 용이

### 2. 데이터베이스: SQLite

**결정**: SQLite 사용

**이유**:
- 경량, 설치 불필요, 신뢰성
- Python 표준 라이브러리에 포함
- 단일 사용자 환경에 적합
- 마이그레이션 및 백업 용이

### 3. Modern GUI 프레임워크: Flet

**결정**: Flet 사용 (Material Design, Flutter 엔진 기반)

**이유**:
- 현대적 UI 제공
- 웹/데스크톱 호환
- 내장 Material Icons
- 비교적 쉬운 학습 곡선

**대안 고려**: PyQt/PySide (더 전문적이나 학습 곡선 있음)

### 4. Classic GUI 프레임워크: tkinter

**결정**: tkinter 사용 (Classic UI)

**이유**:
- Python 기본 포함 (별도 설치 불필요)
- 안정성
- 간단한 기능에 충분

### 5. 파일 시스템 감시: watchdog

**결정**: watchdog 라이브러리 사용

**이유**:
- 안정적인 파일 감시
- 크로스 플랫폼 지원
- 이벤트 기반 아키텍처
- 쉬운 사용법

### 6. 보고서 자연어 처리: Jinja2 (NLTK/spacy 대신)

**결정**: Jinja2 템플릿 방식 사용, NLTK/spacy 미사용

**이유**:
- 무거운 자연어처리 라이브러리(모델 다운로드 필요) 대신 집계 통계 기반 템플릿 방식 채택
- 가볍고 빠르며 유지보수 쉬움
- 사용자와 합의된 스코프 결정
- 현재 데이터 양에서는 구조화된 문장으로 충분

### 7. 브라우저 확장 수신 서버: Python 표준 http.server (Flask 대신)

**결정**: Python 표준 라이브러리 `http.server` 사용, Flask 미사용

**이유**:
- 브라우저 확장 수신 서버에 신규 웹 프레임워크 의존성을 추가하지 않기 위해 표준 라이브러리만으로 최소 구현
- 기능이 단순하여 Flask 같은 웹 프레임워크는 과함
- 의존성 최소화

### 8. 보고서 포맷: Markdown + Word (PDF/HTML 제외)

**결정**: Markdown + Word(.docx) 2개만 지원, PDF/HTML 제외

**이유**:
- 사용자와 합의된 스코프 결정
- 기본 보고서 템플릿으로 충분
- 개발 범위 축소로 빠른 완성

**대안 고려**: PDF(ReportLab), HTML도 고려했으나 이번 스코프에서 제외

### 9. 브라우저 확장: Chrome only (Manifest V3)

**결정**: Chrome 대상만, Manifest V3 사용

**이유**:
- 가장 널리 사용되는 브라우저
- Manifest V3가 최신 표준
- Firefox/Edge 등 확장은 추후 고려

### 10. 브라우저 확장 수집 항목: 방문 URL, 페이지 제목, 방문 시각만

**결정**: 방문 URL, 페이지 제목, 방문 시각만 수집, 검색기록 추적/실시간 탭 감지 제외

**이유**:
- 사용자와 합의된 스코프 결정
- 기본 기능으로 충분
- 개발 범위 축소

### 11. Confluence 인증: Personal Access Token (Bearer)

**결정**: Confluence Server/Data Center, Personal Access Token (Bearer) 인증 사용

**이유**:
- 사용자 환경이 Confluence Server/Data Center임
- Cloud의 email+API키 방식이 아님
- Bearer 토큰이 표준적이고 안전

### 12. Slack 라이브러리: slack-sdk

**결정**: slack-sdk==3.27.0 사용

**이유**:
- 공식 Slack Python SDK
- 안정적이고 지속 업데이트
- Web API 지원 완벽

### 13. Devin 연동: 스텁만 구현

**결정**: Devin 활동 수집 스텁만 구현 (빈 리스트 반환)

**이유**:
- Devin은 클라우드 전용 서비스라 로컬 로그 파일이 존재하지 않음
- API 연동은 가능하나 이번 스코프에서는 미착수
- 구조만 확보해두고 추후 API 연동 가능

### 14. 데이터 소스: 8개로 확정 (→ 이후 Teams/OneNote/SharePoint 추가로 11개)

**결정**: 파일 시스템, VSCode, Orca IDE, Outlook, Slack, Claude Code, Confluence, 브라우저(Chrome) 8개로 확정

**이유**:
- Devin은 로컬 로그 없음으로 스텁만
- Teams는 인증정보 미확보로 대기
- 실사용 가능한 8개 소스에 집중

**후속**: Teams(채팅+일정), OneNote(섹션), SharePoint/OneDrive(파일 수정)가 추가되어 현재 11개 소스. 전부 동일한 Graph 디바이스 토큰으로 동작

### 16. Flet 버전: 1.0.0 → 0.86.5 다운그레이드

**결정**: `flet==0.86.5` 사용 (1.0.0 사용 안 함)

**이유**:
- 1.0.0은 API가 크게 바뀌었을 뿐 아니라, Row/Stack 레이아웃 자체에 렌더링 버그가 있음 (자식 요소 폭의 합이 창 너비와 정확히 같으면 마지막 패널이 그려지지 않음)
- 0.86.5에서도 동일 레이아웃 버그가 일부 재현되어, 근본적으로는 3단 레이아웃 자체를 포기하고 2단 구조로 재설계함 (아래 17번 참고)

### 17. 대시보드 레이아웃: 3단 → 2단(사이드바+본문) 구조

**결정**: 오른쪽 고정폭 사이드바를 없애고, 해당 내용(Weekly Summary/버튼)을 본문 하단 섹션으로 이동

**이유**:
- Flet Row/Stack에서 "고정폭+flex+고정폭" 3단 구성 시 마지막 고정폭 패널이 렌더링되지 않는 버그를 여러 우회 방법(Stack 절대좌표, RTL 트릭, 여백 조정)으로도 완전히 해결하지 못함
- 데이터 소스가 계속 늘어날 예정(Teams 등)이라 UI 최종 다듬기는 마지막 단계에 한 번에 하기로 하고, 우선 안정적으로 렌더링되는 구조로 스켈레톤 완성

### 18. Word 문서 생성: 자체 minimal docx 빌더 사용

**결정**: python-docx의 `Document()` 무인자 호출(내장 기본 템플릿 의존) 대신, `_write_minimal_docx()`로 최소 유효 docx를 raw zip으로 직접 생성

**이유**:
- python-docx 내장 기본 템플릿(`default.docx`)이 사내 DRM/문서보안 솔루션에 의해 OLE2 컨테이너로 손상되어 있어 `Document()` 무인자 호출이 항상 실패함
- 매번 새 템플릿을 직접 생성하면 이 문제를 완전히 우회 가능

### 19. Outlook 수집 방식: 로그 스캔 → COM API

**결정**: `OutlookLogCollector`(로그 파일 스캔) 대신 `OutlookCollector`(COM API)를 기본으로 사용, API 실패 시 로그 방식 폴백

**이유**:
- 최신 Outlook은 로그 스캔 대상 경로에 유의미한 파일을 거의 안 남겨 항상 0건이 나옴
- COM API는 Outlook이 실행 중이면 받은편지함/보낸편지함/캘린더를 실제로 조회 가능

### 20. AI 요약: 사내 LiteLLM Proxy 연동

**결정**: `https://dev-devx-llm-gw-api.shinsegae-inc.com` (OpenAI 호환 Chat Completions), 기본 모델 `bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0`, 최대 300자

**이유**:
- 사용자가 Outlook 보낸메일/Confluence 페이지의 실제 내용을 요약해서 보고서에 담고 싶어함
- 사내 승인된 프록시로 별도 외부 API 키 없이 사용 가능
- Haiku 4.5는 사내 개발환경 기본 모델과 동일, 빠르고 저렴
- 비활성화/실패 시 발췌(truncation) 방식으로 자동 폴백하여 API 키 미설정 상태에서도 동작 보장

### 21. DB 저장 방식: INSERT OR IGNORE → UPSERT

**결정**: 활동 저장 시 `(timestamp, action, file_path, source)` 충돌 시 `ON CONFLICT DO UPDATE`로 details 갱신

**이유**:
- 단순 IGNORE 방식은 요약 기능 추가 이전에 저장된 "요약 없는" 행이 영영 갱신되지 않아, 캐싱을 도입해도 같은 항목의 LLM 재호출을 막을 수 없었음
- upsert로 재수집 시 최신 details(요약 등)로 항상 갱신되면서도 중복 행은 생기지 않음

### 22. Active Work Sessions: 실제 프로세스 감지 (psutil) + 주기적 갱신

**결정**: 하드코딩된 active 값 대신 `psutil`로 실제 프로세스 실행 여부 확인, 5초 주기로 재확인해서 화면 갱신

**이유**:
- 실행 중인 앱이 카드에 비활성(회색)으로 잘못 표시되는 문제 해결
- 앱 실행 중 다른 프로그램을 껐다 켜는 경우까지 반영하려면 최초 1회 체크로는 부족, 주기적 갱신 필요

### 23. GUI 테스트 방법: 사용자 직접 테스트 (computer-use 자동화 불가)

**결정**: Flet(Flutter) 앱 GUI 테스트는 사용자 직접 수행, computer-use 자동화 미사용

**이유**:
- Flet 앱은 Flutter 엔진 기반이라 accessibility tree가 매우 얽음 (개별 버튼/위젯이 accessibility 트리에 잡히지 않음)
- element-index 기반 클릭 불가능
- 좌표 기반 클릭 시도하나 개별 버튼의 정확한 위치 파악 어려움
- computer-use 도구로 자동화된 테스트는 기술적으로 어려움
- 사용자가 직접 버튼을 클릭해서 동작을 확인하는 것이 효율적

### 24. Office 파일 DRM 재암호화 대응: `zipfile.BadZipFile`만 구분해서 fallback 메시지 반환

**결정**: `.docx`/`.pptx`/`.xlsx` 내용 캡처 시 `zipfile.BadZipFile` 예외는 별도로 잡아서 "(내용 변경 감지됨 - 사내 보안 정책으로 암호화되어 상세 내용 확인 불가)" fallback summary를 반환. 그 외 예외(PermissionError 등 파일 잠김)는 기존처럼 조용히 None 반환

**이유**:
- 사내 DRM이 저장 직후 Office 파일을 OLE2로 재암호화해서(Word에 이어 Excel도 동일 현상 확인) zip 기반 라이브러리(openpyxl/python-docx/python-pptx)가 못 읽는 문제는 코드로 해결 불가한 환경적 제약
- 그렇다고 조용히 None만 반환하면 보고서에 아무 것도 안 남아 사용자가 "프로그램이 감지를 못 했나?"로 오해함 → 최소한 "변경은 있었다"는 사실이라도 남기는 게 낫다고 판단
- 반면 파일이 다른 프로그램에서 열려있어 일시적으로 읽기 실패하는 경우까지 fallback 메시지를 남기면 노이즈가 되므로, `BadZipFile`(=DRM 재암호화로 포맷 자체가 바뀐 경우)만 구분해서 처리

### 25. 노이즈 파일 필터링: 8자리 16진수 임시 파일명 + `^` 포함 파일명 제외

**결정**: `file_watcher.py`의 `should_exclude()`와 `report_generator.py`의 `_is_noise_activity()`에 `_HEX_TEMP_NAME_RE = r'^[0-9A-Fa-f]{8}(\.[A-Za-z0-9]+)?$'` 정규식 매칭 파일명, 그리고 `^` 문자가 포함된 파일명을 노이즈로 간주해 제외. `.crdownload`/`.part`/`.lock`/`.git` 도 함께 제외 목록에 추가

**이유**:
- 사용자가 실사용 중 `미확인 819675.crdownload`(브라우저 다운로드 임시파일), `(DDr^7D3\(DDr^7D3.jpg`(DRM 재암호화로 깨진 파일명) 같이 사람이 이해할 수 없는 항목이 보고서에 그대로 노출되는 것을 지적함
- 오피스/OS가 원자적 저장(임시파일 쓰고 이름 바꿔치기) 중 만드는 8자리 16진수 파일명, DRM이 만드는 `^` 포함 깨진 파일명은 둘 다 사람이 봐서 의미를 알 수 없는 패턴이라 일괄 필터링
- 두 위치(watcher/report_generator)에 동일 규칙을 중복 적용한 이유는, watcher 단에서 걸러지지 않고 DB에 이미 쌓인 과거 데이터도 report_generator에서 한 번 더 걸러줘야 하기 때문

### 26. GUI "Start Tracking" 버튼이 브라우저 수신 서버도 함께 기동

**결정**: `modern_gui.py`의 `start_tracking()`/`stop_tracking()`에서 `FileWatcher`뿐 아니라 `BrowserActivityServer`도 함께 시작/종료

**이유**:
- DB에 `source='browser'` 행이 한 번도 기록된 적 없어 조사한 결과, GUI의 "Start Tracking" 버튼은 파일 감시만 시작하고 크롬 확장이 POST하는 로컬 서버(포트 5757)는 켜지 않고 있었음 (별도 스크립트 `integrated_collector.py`를 실행해야만 켜지는 구조였음)
- 사용자가 GUI 버튼으로만 트래킹을 시작/종료하는 워크플로우를 쓰고 있어서, GUI 경로에서도 브라우저 서버가 자동으로 켜지도록 통일

### 27. Teams 연동: 디바이스 코드 로그인(위임 권한) + Graph 직접 호출

**결정**: `teams_collector.py`가 Microsoft Graph `/me/chats`, `/me/chats/{id}/messages`를 직접 호출해 본인 Teams 채팅을 수집. 인증은 Microsoft Office first-party client(`d3590ed6-52b3-4102-aeff-aad2292ab01c`)+`.default offline_access` scope의 디바이스 코드 로그인으로, 토큰은 `config/teams_graph_token.json`에 저장하고 `refresh_token`으로 자동 갱신. Teams **회의**는 Outlook 캘린더 수집에서 `is_teams_meeting` 플래그로 구분

**이유**:
- 사내 정책상 Azure AD 앱 등록이 막혀 있을 수 있어 client_credentials 앱 권한 경로는 불가 (2026-09-28 사용자 확인)
- 사내 DevX MCP(`sm-ops-pub-mcp`)에도 Teams 조회 도구가 있었으나, 그 MCP의 토큰 캐시가 로컬 Qdrant(localhost:6333)를 요구해서 이 환경에서는 `fetch failed`로 동작 불가 — 단, 그 MCP가 쓰는 first-party client 방식은 확인됐으므로 동일 방식을 Python으로 직접 구현
- `.default` scope는 사내 전역 admin consent가 이미 적용된 권한만 포함 → 권한 이름을 명시하면 `AADSTS65002`가 나는 사내 환경에서 유일하게 동작하는 방식 (DevX MCP 코드 주석에서 확인)
- delegated permission이라 본인 채팅만 조회 가능 (주간보고 용도로 적절)
- 토큰 파일은 access+refresh token을 포함하므로 `.gitignore` 필수 처리

### 28. AI 임베딩: 사내 LiteLLM 프록시의 `azure/text-embedding-3-large`

**결정**: 활동 의미 분류에 사내 프록시의 임베딩 엔드포인트 사용 (dim 3072)

**이유**:
- 프록시의 `/v1/models` 조회 결과 임베딩 모델 4종 확인 — 별도 로컬 모델 다운로드 없이 사내 인프라만으로 의미 분석 가능
- OpenAI 호환 `/v1/embeddings`라 향후 LangChain `OpenAIEmbeddings`로도 재사용 가능

### 29. 활동 클러스터링: 외부 VectorDB 없이 인메모리 코사인 유사도

**결정**: `activity_clusterer.py`에서 그리디 코사인 유사도 클러스터링(임계값 0.62), 영속 벡터 저장소 도입은 보류

**이유**:
- 주간 활동 수백 건 규모에서는 O(n²) 인메모리 비교로 충분 — FAISS/Qdrant 같은 별도 벡터DB는 오버엔지니어링
- sm-ops-pub-mcp가 쓰던 Qdrant(localhost:6333)는 별도 서버 기동이 필요해 로컬 단독 실행 구조와 안 맞음
- 향후 활동 누적·"유사 과거 작업" 검색이 필요해지면 SQLite에 임베딩 테이블 추가 방식으로 확장 예정

### 30. LLM 호출 구조: LangChain LCEL 체인 (요약 표준화)

**결정**: `llm_summarizer.py`를 `ChatPromptTemplate | ChatOpenAI | StrOutputParser` LCEL 체인으로 구현, `PROMPT_TEMPLATES`에 소스별 프롬프트 분리

**이유**:
- 프록시가 OpenAI 호환이라 `ChatOpenAI(base_url=프록시)`만으로 연결됨
- 소스별(파일/메일/Teams/주제명) 프롬프트를 템플릿으로 분리 → 코드 수정 없이 프롬프트·모델 교체 가능
- 체인의 `with_retry`로 일시 오류 자동 재시도, 실패 시 기존 폴백(None) 유지
- LangChain은 선택 의존성 — 미설치 환경에선 None 반환으로 조용히 폴백

### 31. 보고서 생성: LangGraph 파이프라인 (순차 경로 폴백 유지)

**결정**: `report_pipeline.py`의 StateGraph(`collect→filter→analyze→aggregate→output`)로 보고서 생성. `generate_and_save_weekly_report`는 그래프 경로 우선, 실패 시 기존 순차 경로로 폴백

**이유**:
- `collect_weekly_data`의 내부를 `fetch_week_activities`/`analyze_week_activities`/`compose_weekly_data` 단계 함수로 분해해 그래프 노드와 순차 경로가 같은 로직을 공유 — 중복 구현 없음
- 조건 엣지로 "활동 0건이면 LLM 분석 건너뛰기"를 그래프 구조로 표현 — try/except 산재 대신 명시적 분기
- 향후 새 분석 단계(RAG 의미 질의 등) 추가 시 노드 하나만 붙이면 됨

### 32. macOS 이식: win32 가드 + Outlook Graph 폴백

**결정**: Windows 전용 코드를 가드 처리하고, macOS에서는 `teams_collector`의 디바이스 토큰을 재사용해 Graph로 메일을 수집

**이유**:
- `win32gui`/`win32process`(GUI 프로세스 감지)와 `win32com`(Outlook COM)이 유일한 Windows 전용 의존성 — try/except 가드로 다른 OS에서도 import 통과
- macOS에서 Outlook 대체가 필요했는데, Teams 인증 토큰으로 `/me/mailFolders/{Inbox,SentItems}`가 이미 동작 — 새 인증 경로를 만들 필요가 없어 이중 구현 부담이 사라짐
- `pywin32`를 `sys_platform == 'win32'` 조건부로 설치해 macOS pip 설치 오류 방지

### 33. 임베딩 영속화: SQLite `activity_embeddings` 테이블

**결정**: 활동별 임베딩 벡터를 `activity_embeddings(activity_key, text, vector)` 테이블에 누적 저장하고, 클러스터러는 캐시 히트된 벡터를 재계산하지 않는다.

**이유**:
- 보고서 생성 시마다 임베딩 API를 재호출하던 것이 측정상 22.6s→3.3s로 개선됨
- 누적 벡터가 곧 VectorDB 역할 — "지난주 유사 작업" 검색(RAG) 기반이 됨
- 외부 VectorDB(FAISS/Qdrant) 설치 없이 SQLite 하나로 영속성 확보 (29번 결정의 확장)

### 34. Teams 1:1 상대방 이름 해석: 다단계 체인 + 봇 인식

**결정**: `_chat_title`에서 다음 순서로 상대방 이름을 찾는다: 멤버 목록 → 최근 메시지 발신자 → 과거 히스토리(최대 300건 페이징) → chat id GUID를 `/me/people` 주소록과 매칭. 봇 채팅은 `from.application.displayName`으로 "봇 - 이름" 표기. 전부 실패 시 "1:1 - (상대방 정보 없음)".

**이유**:
- `/users/{guid}`는 사내 권한(User.Read.All) 부재로 404 — `/me/people`은 내 주소록이라 권한 추가 없이 동작
- 미해결 채팅 중 상당수는 사람이 아닌 앱/봇(예: "아이앤씨 알림") — `from.application.displayName`으로 의미 있는 표기 확보
- 결과: 14개 1:1 채팅 중 12개 실명/봇명 해석, 나머지 2개는 메시지 0~1건의 해석 불가능한 채팅

### 35. Graph API 429 대응: Retry-After 기반 백오프

**결정**: `_graph_get`이 429(Too Many Requests)를 받으면 `Retry-After` 헤더(없으면 지수 백오프)만큼 대기 후 최대 3회 재시도. `@odata.nextLink` 전체 URL도 그대로 받아 페이징 가능.

**이유**:
- 채팅 목록 순회 시 멤버/메시지 호출이 연속돼 429가 실제로 관측됨 — 무재시도면 해당 채팅 수집이 빠짐
- 429만 재시도하고 다른 에러는 즉시 raise — 무한 재시도로 인한 지연 방지

### 36. OneNote 수집: Graph 섹션 수준 (페이지 내용은 권한 제한으로 불가)

**결정**: `onenote_collector.py`가 Teams 디바이스 토큰을 재사용해 `/me/onenote/notebooks?$expand=sections`로 노트북·섹션의 `lastModifiedDateTime`을 수집. 페이지 제목·본문은 수집하지 않는다.

**이유**:
- `/me/onenote/pages` 등 페이지 경로는 `Notes.Read.All` scope를 요구하는데, Microsoft Office first-party client에 사전 승인이 없어 동적 동의 시 `AADSTS65002`로 차단됨 (2026-09-29 직접 확인)
- 데스크톱 OneNote 미설치 환경이라 `OneNote.Application` COM도 불가
- `.one` 파일은 이미 파일 감시가 수정 이벤트를 잡고 있음 — 이 수집기는 "어느 노트북/섹션을 만졌는지" 맥락만 제공
- 사용자가 OneNote 페이지 본문까지 원하면 조직 차원에서 `Notes.Read.All` 승인이 필요하거나 데스크톱 OneNote+COM 경로를 써야 함

### 37. DRM 문서 내용 추출: Office COM 직접 읽기 폴백 (Windows)

**결정**: 파서가 `BadZipFile`(OLE2 재암호화)로 실패한 Office 문서는 Windows에서 Excel/Word/PowerPoint COM으로 열어 내용을 읽는다 (`_excel_snapshot_via_com` 등). COM도 실패하면 기존 "보안 문서" 폴백 메시지 유지.

**이유**:
- 원래 검토한 "Purview 라벨 해제 후 재로드" 방식은 라벨 변경이 감사 로그에 남고 추가 권한·GUID 확보가 필요했음
- 반면 Office COM은 `Workbooks.Open(ReadOnly)`만으로 자체 권한 복호화 → **원본 파일 무수정, 라벨 변경 없이** 내용 추출 (2026-09-29 실제 DRM 발주서 xlsx로 검증)
- Windows+Office 설치 환경 한정 — macOS/Office 미설치 환경에서는 기존 폴백(수정 이벤트만 기록) 유지
- 발견한 DRM 파일들은 Purview 라벨이 아닌 별도 문서보안 솔루션으로 보임 (`SensitivityLabel.GetLabel()` 빈 값)

### 38. GUI: 추적 자동 시작 + 지연 import (기동 ~10s→~2s)

**결정**: GUI 시작 시 추적이 자동으로 켜지고 Start/Stop 버튼을 폐지. 무거운 모듈(collectors·report_generator 등)은 실제 호출 시점에 lazy import, 프로세스 감지는 `process_iter`+창 열거 각 1회의 배치 스캔. `run_modern_gui.bat`은 pyenv shim을 우회해 실제 `pythonw.exe`를 직접 호출.

**이유**:
- 사용자가 "프로그램 시작 시 자동 실행이 효과적"이라고 명시 — 별도 Start 버튼은 불필요한 클릭
- 측정 결과 기동 10초+ 중 대부분이 ①pyenv shim 버전 해석(~6.5s) ②langchain/watchdog 등 무거운 선행 import ③앱 12개 각각 전체 프로세스 스캔이었음
- `pythonw`로 콘솔 없이 띄워 이중창(콘솔+GUI)도 제거

### 39. Teams 수집/보고 기준: 사용자 설정 파일 + Settings UI

**결정**: `config/teams_settings.json`에 수집 기간·채팅 유형(1:1/그룹/회의)·보고서 범위(mine/all)·업무 관련만 요약(work_only)·제외 채팅방(excluded_chats)을 저장하고, Settings 화면에서 직접 편집. 채팅방·메시지 수집 상한은 아예 제거하고 `nextLink` 전체 페이징으로 수집.

**이유**:
- 사용자가 "1:1 대화가 누락돼 보인다"고 지적 — 상위 50방×50건 하드캡이 원인이었고, 하드코딩된 기준 대신 사용자가 직접 조절할 수 있어야 한다고 요청
- work_only는 수집이 아니라 **보고서 요약 단계**에서 LLM이 선별 — 원본 데이터는 보존하고 언제든 토글로 원복 가능
- 제외 채팅방도 수집/보고서 양쪽에서 적용해 과거 데이터까지 즉시 반영

### 40. 채팅 최신성 기준: `lastMessagePreview.createdDateTime` (lastUpdatedDateTime 아님)

**결정**: 채팅 목록 요청에 `$expand=lastMessagePreview`를 붙이고, 최신성 판정·조기 페이징 중단(stop_before)은 마지막 메시지 시각(`lastMessagePreview.createdDateTime`) 기준. 폴백으로만 `lastUpdatedDateTime` 사용.

**이유**:
- `lastUpdatedDateTime`은 멤버/메타데이터 변경 시각이라 ①오래된 대화가 최근 방처럼 보이고 ②오늘 메시지가 온 오래된 방을 놓치는 양방향 오류 확인 (2026-09-30 실제 데이터로 검증)
- 이 기준 적용으로 전체 채팅 903개→최근 22개, 목록 로딩 27s→0.9s

### 41. SharePoint/OneDrive 수집: 동일 Graph 토큰 재사용

**결정**: `sharepoint_collector.py`가 Teams 디바이스 토큰의 `Files.Read.All`을 재사용해 `/me/drive/recent` + `/me/drive/sharedWithMe`에서 기간 내 수정 파일을 수집. 파일 본문은 읽지 않고 수정 메타데이터만.

**이유**:
- 토큰에 `Files.Read.All`이 이미 포함돼 추가 인증이 전혀 필요 없음 (공유 링크 `u!`+base64url 디코딩으로 임의 파일 해석도 확인)
- 파일 내용은 이미 로컬 파일 감시+COM 폴백 경로가 담당 — 클라우드 쪽은 "어떤 공유 문서를 언제 만졌나" 메타데이터만으로 충분

## ❌ 폐기된 결정

### 1. 보고서 포맷: PDF/HTML 포함

**결정**: PDF(ReportLab), HTML도 고려

**취소 사유**: 사용자와 합의하여 Markdown + Word로 축소 결정. 기본 보고서 템플릿으로 충분하며 개발 범위 축소로 빠른 완성 위해 제외

### 2. 브라우저 확장: 다중 브라우저 지원

**결정**: Firefox/Edge 등 다중 브라우저 지원 고려

**취소 사유**: Chrome only로 축소 결정. 가장 널리 사용되는 브라우저에 집중, 추후 확장 가능

### 3. 브라우저 확장 기능: 검색기록 추적, 실시간 탭 감지

**결정**: 검색기록 추적, 실시간 탭 감지, 확장 자체 설정 UI 구현

**취소 사유**: 이번 스코프에서 제외. on/off 토글만 최소 구현, 추후 기능 확장 가능

### 4. 보고서 자연어 처리: NLTK/spacy 사용

**결정**: NLTK/spacy 등 ML 라이브러리 사용 고려

**취소 사유**: Jinja2 템플릿 방식으로 변경. 무거운 자연어처리 라이브러리 대신 집계 통계 기반 템플릿 방식 채택으로 가볍고 빠르며 유지보수 쉬움

### 5. 브라우저 확장 수신 서버: Flask 사용

**결정**: Flask 사용 고려

**취소 사유**: Python 표준 http.server로 변경. 신규 웹 프레임워크 의존성 추가 방지, 표준 라이브러리만으로 최소 구현

## 📝 결정 변경 이력

| 결정 | 원래 결정 | 변경된 결정 | 변경 사유 | 변경일 |
|------|----------|------------|----------|--------|
| 보고서 포맷 | Markdown + Word + PDF/HTML | Markdown + Word | 스코프 축소 | 2026-09-21 |
| 브라우저 확장 대상 | Chrome + Firefox/Edge | Chrome only | 스코프 축소 | 2026-09-21 |
| 브라우저 확장 기능 | 방문기록 + 검색기록 + 탭 감지 | 방문기록만 | 스코프 축소 | 2026-09-21 |
| 보고서 자연어 처리 | NLTK/spacy 사용 | Jinja2 템플릿 | 의존성 최소화 | 2026-09-21 |
| 브라우저 확장 서버 | Flask 사용 | Python 표준 http.server | 의존성 최소화 | 2026-09-21 |
