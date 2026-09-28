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

**완료율**: 약 95%+ (수집 소스 8종 + AI 분석/영속화 + LangGraph 파이프라인 + macOS 이식 준비 완료, Slack 토큰 발급·자동 스케줄링·UI 최종 다듬기만 남음)

**성과** (2026-09-28 기준):
- 파일 시스템(실시간 감시+내용 캡처), IDE, Outlook(COM/Graph), Claude Code, Confluence, 브라우저(Chrome), Teams(Graph 디바이스 로그인) — 전체 소스 정상 동작 확인
- 주간보고서 생성 완료 (Markdown + Word, 액션별 상세 + AI 요약 + 노이즈 필터링 + 민감 URL 제거)
- **Teams 연동 완료** — Graph 위임권한(디바이스 코드 로그인)으로 채팅·일정 수집, 1:1 대화 상대방 실명 해석(14개 중 12개)
- **AI 의미 분석 완료** — 임베딩 클러스터링으로 "주제별 작업" 섹션 생성, `activity_embeddings` 테이블로 벡터 영속화(재실행 22.6s→3.3s)
- **LangGraph 파이프라인** — 보고서 생성을 노드/엣지로 구조화, 활동 없으면 분석 스킵
- **LCEL 체인** — LLM 호출을 소스별 프롬프트 템플릿으로 표준화, 내장 재시도
- **macOS 이식 준비** — win32 가드, Outlook Graph 폴백, pywin32 조건부 의존
- **Git 버전관리 시작** — https://github.com/hyuntaeson/weekly_report_automation
- **전체 기능 시나리오 32건 테스트** — Excel 결과 자동 생성 (`test_reports/`), PASS 31 / FAIL 0 / SKIP 1
- 사내 LiteLLM Proxy 연동 (요약 + 임베딩 모두, 캐싱 포함)

**남은 핵심 작업**:
- **자동 스케줄링** — Windows 작업 스케줄러로 매주 자동 생성 (마지막 핵심 피스)
- **RAG 의미 질의 섹션** — 임베딩 저장 완료됨, "장애 대응" 같은 정의된 질의로 누적 벡터 검색 → 보고서 섹션 자동 생성
- Slack Bot Token 발급 및 연동 마무리 (사내 승인 대기)
- macOS 실기 검증 (코드 준비 완료, 맥에서 GUI 기동·Graph 로그인 확인 필요)
- Word/PPT DRM 폴백 보완 — `PackageNotFoundError` 미처리 (xlsx만 정상, 보류 중)
- UI 최종 다듬기 (Slack까지 다 붙은 뒤 한 번에 정리)

## 🎯 다음 할 일

자세한 내용은 <ref_file file="C:\Users\SSG\weekly_report_automation\progress.md" />를 참고하세요.

---

**문서 구조 개편일**: 2026년 9월 21일 (2026년 9월 28일 최종 갱신)
