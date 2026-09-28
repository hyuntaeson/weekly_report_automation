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
- **미검증**: 코드 수정은 완료. 사용자가 GUI에서 재시작 후 실제 브라우징하면서 DB에 browser 행이 쌓이는지는 아직 확인 안 됨 — **다음 세션 최우선 확인 사항**

### 검증
- `test_all_completed.py` 9/9 전체 재실행 통과
- 노이즈 필터 예시 2개 + 정상 파일 1개 별도 스크립트로 필터링 결과 확인
- 실제 DRM 걸린 xlsx 파일로 fallback 메시지 확인

## 🎯 다음 할 일

### 최우선
1. **브라우저 활동 실제 수집 확인** — GUI에서 Stop → Start Tracking 다시 누른 뒤 크롬으로 실제 사이트 방문(예: fastcampus.co.kr) 후 `SELECT * FROM activities WHERE source='browser'`로 행이 쌓이는지 확인. 안 쌓이면 크롬 확장(`chrome://extensions`)이 실제로 로드/활성화돼 있는지, `manifest.json`의 host_permissions(`localhost:5757`)가 맞는지부터 재점검
2. **Word/PPT 파일도 실제 MS Word/PowerPoint에서 정상 열람되는지 사용자 육안 확인** — 사내 DRM 재암호화 후에도 실사용에는 문제없는지 검증 필요 (코드로는 검증 불가)

### 중기
3. **Git 버전관리 시작** — `weekly_report_automation` 폴더가 아직 git 저장소 아님. `.gitignore`는 준비됨(`config/*_config.json`, `data/`, `reports/`, `logs/` 등 제외)
4. **자동 스케줄링** — Windows Task Scheduler로 "매주 자동 생성" 목표 완성
5. **Slack 연동 마무리** — Bot Token 발급 필요 (사용자가 보류, 천천히 진행 예정)
6. **Teams 연동** — Azure AD 앱 등록 필요 (자격증명 확보 시 착수)
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
5. **브라우저 수집**: 코드는 수정했으나 사용자 환경에서 실제 수집되는지 아직 미확인 (위 "다음 할 일" 1번 참고)
6. **Teams 연동 미착수**: Azure AD 앱 등록 및 Graph API 인증정보 미확보 상태
7. **Devin 연동 불가**: 클라우드 전용 서비스로 로컬 로그 파일 없음

## 🔗 관련 문서

- **핵심 결정 사항**: <ref_file file="C:\Users\SSG\weekly_report_automation\decisions.md" />
- **완료된 작업 로그**: <ref_file file="C:\Users\SSG\weekly_report_automation\archive\2026-09.md" />
- **프로젝트 개요**: <ref_file file="C:\Users\SSG\weekly_report_automation\README.md" />
