# 최근 작업 내역과 다음 할 일

이 문서는 최근 작업 내역과 다음 할 일을 정리합니다. 2026-09-22 이전 작업 로그는 `archive/2026-09.md`를 참고하세요.

## 📅 최근 작업 내역 (2026년 9월 28일)

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

### 알려진 잔여 이슈 (이번 세션에서 새로 확인)
- **`.docx`/`.pptx` DRM fallback 미작동**: `python-docx`/`python-pptx`는 비-zip 파일에 `PackageNotFoundError`(= `docx.opc.exceptions`/`pptx.exc`)를 던지는데, 코드가 `zipfile.BadZipFile`만 잡아서 `except Exception → None` 경로로 빠짐. 결정 24의 fallback이 Excel에서만 실제 동작 중 — 수정 필요 (OLE2 매직바이트 직접 확인 방식 권장)
- **LiteLLM 프록시 타임아웃**: 15초 read timeout 발생 (일시적 네트워크 이슈일 수 있음, fallback은 정상 동작)

## 🎯 다음 할 일

### 최우선
1. ~~**브라우저 활동 실제 수집 확인**~~ ✅ **완료 (2026-09-28)** — GUI Start Tracking이 5757 서버 정상 기동, 크롬 확장 설치 후 실제 브라우징 기록이 DB에 기록됨을 확인. 참고: 확장 프로그램이 아예 미설치 상태였던 것도 이번에 함께 발견/해결됨
2. **Word/PPT 파일도 실제 MS Word/PowerPoint에서 정상 열람되는지 사용자 육안 확인** — 사내 DRM 재암호화 후에도 실사용에는 문제없는지 검증 필요 (코드로는 검증 불가)

### 중기
3. **Git 버전관리 시작** — `weekly_report_automation` 폴더가 아직 git 저장소 아님. `.gitignore`는 준비됨(`config/*_config.json`, `data/`, `reports/`, `logs/` 등 제외)
4. **자동 스케줄링** — Windows Task Scheduler로 "매주 자동 생성" 목표 완성
5. **Slack 연동 마무리** — Bot Token 발급 필요 (사용자가 보류, 천천히 진행 예정)
6. ~~**Teams 연동**~~ ✅ **완료 (2026-09-28)** — 회의는 캘린더 경유 감지, 채팅은 디바이스 코드 로그인 기반 Graph 직접 수집으로 350건 DB 저장 확인
7. **UI 최종 마무리** — 지금은 스켈레톤 상태. Slack/Teams까지 다 붙은 뒤 한 번에 정리하기로 함

### 낮은 우선순위
8. **데이터 정리 스크립트** — `data/` 폴더에 테스트 산출물(`activities_*.json`, `test_results_*.json` 등) 누적 중
9. 고급 분석/시각화 (데이터 축적 후), 브라우저 확장 기능 확장

## 📊 현재 상태

**완료율**: 약 90~95% (핵심 수집 소스 8개 + AI 요약/캐싱 완료, Settings 폴더 관리 UI 완료, Office 파일 내용 캡처 확장 완료, GUI 기능 검증 완료, UI 최종 다듬기와 Slack/Teams 연동만 남음)

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
6. **Teams 연동 미착수**: Azure AD 앱 등록 및 Graph API 인증정보 미확보 상태
7. **Devin 연동 불가**: 클라우드 전용 서비스로 로컬 로그 파일 없음

## 🔗 관련 문서

- **핵심 결정 사항**: <ref_file file="C:\Users\SSG\weekly_report_automation\decisions.md" />
- **완료된 작업 로그**: <ref_file file="C:\Users\SSG\weekly_report_automation\archive\2026-09.md" />
- **프로젝트 개요**: <ref_file file="C:\Users\SSG\weekly_report_automation\README.md" />
