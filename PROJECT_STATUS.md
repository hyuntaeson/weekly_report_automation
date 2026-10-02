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

**완료율**: 약 95%+ (수집 소스 11종 + AI 분석/영속화 + LangGraph 파이프라인 + GUI 완성, Slack 토큰 발급·자동 스케줄링만 남음)

**2026-10-01 추가**: 소스 `weekly_report/` 패키지 구조화, VectorDB(Qdrant)·RAG 주제 질의(STEP 2)·STEP 3 예상 질문 완료, 보고서 생성 약 104초→55~70초(재생성 27초) + 메인 화면 생성 상태 표시. 저장소 보관 정책(활동 벡터 보관 기간 Settings 선택·지난 주는 주간 요약 벡터로 영구 보관, 레거시 임베딩 삭제로 data 101MB→43MB) 완료

**2026-10-02 추가**: 근거 노이즈 필터(IDE·제외 키워드·이름뿐인 기록·단순 대답 제외 — 보고서가 자기 복사본을 인용하던 문제 해결), 근거 표기(출처 전체 + 내용 요지), 요약 글자 수 제한 정리(긴 원문은 LLM 요약). LLM 출력 하네스(요약 형식 검증·근거 관련성·STEP 3 사실 대조) + STEP 3 답변 품질(아는 사실 먼저, 확인 필요 부분 구분). STEP 3 2단계 근거 검색·판정 모델 분리(Opus 5.5). 정답셋 회귀 평가(요지 정답률 0.36→0.57)·프로젝트 문서 근거. 성과 수치 측정 기준 표시, 주제별 작업 정리(개인 활동 주제 제외). STEP 2 주요 이슈 & 리스크·다음 주 계획(1-5), 메인 화면 정리 완료. 나만의 비서 09:00 오늘 할 일·17:00 진행 점검(메인 카드) 완료, 근무일 09:00·17:00 자동 실행(놓치면 켤 때)·Settings 공휴일 입력 완료(15시 기준 추출/점검). 발표자료 11쪽 갱신(기대 효과·AI 품질·실제 화면). 다음: 알림 채널 결정 → 확장 후보 6-1 지난 업무 검색 → 5-5·6-2 성과 요약 → 6-3 장애·배포 타임라인 → 6-4 파트 취합

**성과** (2026-09-30 기준):
- 파일 시스템(실시간 감시+내용 캡처), IDE, Outlook(COM/Graph), Claude Code, Confluence, 브라우저(Chrome), Teams(채팅+일정), OneNote(섹션), **SharePoint/OneDrive(파일 수정)** — 전체 소스 정상 동작
- 주간보고서 생성 완료 (Markdown + Word, 액션별 상세 + AI 요약 + 노이즈 필터링 + 민감 URL 제거)
- **Teams 사용자 설정** — 수집 기간·채팅 유형·제외 채팅방·보고서 범위(내 메시지/전체)·업무 관련만 요약을 Settings 화면에서 직접 선택
- **GUI 완성** — 추적 자동 시작, 시작 ~10s→~2s (pyenv shim 우회 + lazy import + 프로세스 단일 스캔), Weekly Summary + Generate Report 단일 CTA
- **AI 의미 분석 완료** — 임베딩 클러스터링으로 "주제별 작업" 섹션 생성, VectorDB(Qdrant)로 벡터 영속화(재실행 22.6s→3.3s) + 보관 기간 정책
- **LangGraph 파이프라인** — 보고서 생성을 노드/엣지로 구조화, 활동 없으면 분석 스킵
- **LCEL 체인** — LLM 호출을 소스별 프롬프트 템플릿으로 표준화, 내장 재시도
- **macOS 이식 준비** — win32 가드, Outlook Graph 폴백, pywin32 조건부 의존
- **Git 버전관리** — https://github.com/hyuntaeson/weekly_report_automation
- **시나리오 테스트 스위트** — Excel 결과 자동 생성 (`test_reports/`)
- 사내 LiteLLM Proxy 연동 (요약 + 임베딩 모두, 캐싱 포함)

**남은 핵심 작업**:
- **자동 스케줄링** — Windows 작업 스케줄러로 매주 자동 생성 (마지막 핵심 피스)
- **장기 질의 연결** — 주간 요약 벡터 검색(`rag.search_past_weeks`)을 화면·보고서에 연결
- Slack Bot Token 발급 및 연동 마무리 (사내 승인 대기)
- macOS 실기 검증 (코드 준비 완료, 맥에서 GUI 기동·Graph 로그인 확인 필요)
- Word/PPT DRM 폴백 보완 — `PackageNotFoundError` 미처리 (xlsx만 정상, 보류 중)

## 🎯 다음 할 일

자세한 내용은 <ref_file file="C:\Users\SSG\weekly_report_automation\progress.md" />를 참고하세요.

---

**문서 구조 개편일**: 2026년 9월 21일 (2026년 10월 2일 최종 갱신)
