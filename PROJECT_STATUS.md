# 주간보고 자동작성 프로그램 - 프로젝트 상태

이 문서는 문서 구조가 개편되었습니다. 새로운 문서 구조는 다음과 같습니다:

## 📁 새로운 문서 구조

| 파일 | 내용 | 위치 |
|------|------|------|
| **README.md** | 현재 목표, 범위, 완료 기준, 최종 결과 | 프로젝트 루트 |
| **decisions.md** | 아직 유효한 핵심 결정과 이유 | 프로젝트 루트 |
| **progress.md** | 최근 작업 내역과 다음 할 일 | 프로젝트 루트 |
| **archive/** | 완료된 작업 로그, 조사 결과, 이전 계획 | `archive/` 폴더 |

## 🔗 문서 참조

- **프로젝트 개요 및 최종 결과**: <ref_file file="C:\Users\SSG\weekly_report_automation\README.md" />
- **핵심 결정 사항**: <ref_file file="C:\Users\SSG\weekly_report_automation\decisions.md" />
- **최근 작업 내역과 다음 할 일**: <ref_file file="C:\Users\SSG\weekly_report_automation\progress.md" />
- **완료된 작업 로그**: <ref_file file="C:\Users\SSG\weekly_report_automation\archive\2026-09.md" />

## 📊 현재 상태 요약

**완료율**: 약 90~95% (핵심 수집 소스 8개 + AI 요약/캐싱 완료, Settings 폴더 관리 UI 완료, Office 파일 내용 캡처 확장 + DRM 대응 완료, GUI 기능 검증 완료, UI 최종 다듬기와 Slack/Teams 연동만 남음)

**성과**:
- 파일 시스템(실시간 감시+내용 캡처: txt/md/docx/pptx/xlsx), IDE, Outlook(API), Claude Code, Confluence(AI 요약), 브라우저(Chrome, 서버 자동 기동 수정) — 데이터 소스 정상 동작 확인
- 주간보고서 생성 기능 완료 (Markdown + Word, 액션별 실제 내용 상세 + AI 요약 포함, 노이즈 필터링)
- Flet UI 렌더링 버그 해결 (0.86.5 다운그레이드 + 레이아웃 재설계), 실제 프로세스 기반 Active Work Sessions 실시간 반영
- 사내 LiteLLM Proxy 연동으로 AI 요약 기능 완료 (캐싱으로 재수집 시 비용/속도 최적화)
- 데이터베이스 무결성 확보 (중복 제거 + upsert)
- Settings 화면에서 감시 폴더 추가/삭제 UI 완료
- 사내 DRM이 Word뿐 아니라 Excel/PPT도 OLE2로 재암호화한다는 사실 확인 + fallback 메시지로 대응
- **전체 자동 테스트 스위트 100% 통과 (9/9 기능)**

**남은 핵심 작업**:
- **브라우저 활동 실제 수집 여부 확인** (다음 세션 최우선 — 코드 수정은 완료, 실사용 검증 대기)
- Slack Bot Token 발급 및 연동 마무리 (보류 중)
- Teams 연동 (인증정보 확보 필요)
- Git 버전관리 시작
- 자동 스케줄링으로 "매주 자동 생성" 목표 완성
- Word/PPT 파일 실제 MS Office 열람 확인 (사내 DRM 재암호화 후 검증 필요)

## 🎯 다음 할 일

자세한 내용은 <ref_file file="C:\Users\SSG\weekly_report_automation\progress.md" />를 참고하세요.

### 최우선: 브라우저 활동 실제 수집 확인

**목표**: GUI에서 Stop → Start Tracking 다시 누른 뒤 크롬으로 실제 사이트 방문 후, DB(`data/activities.db`)에 `source='browser'` 행이 쌓이는지 확인. 원인(GUI가 브라우저 수신 서버를 안 켜고 있던 문제)은 이미 코드로 수정했으나 사용자 환경에서 실사용 검증이 아직 안 됨

---

**문서 구조 개편일**: 2026년 9월 21일 (2026년 9월 28일 상태 갱신)
