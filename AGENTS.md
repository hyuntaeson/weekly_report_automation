# 주간보고 자동작성 — 에이전트 작업 규칙

이 프로젝트에서 작업할 때 지켜야 할 규칙들.

## 문서 관리

- **"정리하자 / 문서 정리해줘" 요청 시 MD 파일들도 함께 최신화한다** — 코드만 커밋하고 문서를 방치하지 말 것
- 대상 문서와 역할:
  - `README.md` — 기능 표, 수집 소스 표, 프로젝트 구조, DB 스키마, 기술 스택, 배포 절차
  - `PROJECT_STATUS.md` — 현재 상태 요약 (완료율·성과·남은 핵심 작업)
  - `progress.md` — 작업 내역 + 다음 할 일 + 알려진 잔여 이슈
  - `decisions.md` — 채택/폐기 결정과 그 이유 (번호 붙은 `### N.` 형식 유지)
  - `archive/` — 완료된 월별 로그. 새 작업은 progress.md에, 아카이빙은 사용자와 합의 후
- 문서만 수정된 커밋도 별도로 남길 것 (메시지 예: `Doc: ...`)

## 고정 제약

- **Flet은 반드시 `0.86.5`** — 1.0 계열은 레이아웃 계산이 달라 UI가 깨짐
- `pywin32`는 `; sys_platform == 'win32'` 조건부 유지
- `config/`의 토큰·API키 파일은 절대 커밋 금지 (`.gitignore`로 차단됨)
- 보고서 출력 포맷은 Markdown + Word — 사용자가 PDF/HTML은 명시적으로 제외함
- Teams 수집은 Microsoft Office first-party client + 디바이스 코드 로그인 방식 유지 (Azure AD 앱 등록 불가)

## 코드 구조

- 소스는 `weekly_report/` 패키지 안에 역할별로 둔다: `collectors/`(수집) · `storage/`(DB·VectorDB) · `ai/`(LLM·임베딩·RAG) · `report/`(섹션·생성·파이프라인·템플릿) · `common/`(공용 유틸) · `gui/`(화면별 mixin)
- 루트에 새 `.py`를 만들지 않는다. 테스트는 `tests/`, 일회성 유틸은 `scripts/`
- import는 `from weekly_report.<패키지>.<모듈> import ...` 절대 경로
- 파일 경로는 `weekly_report/paths.py` 상수만 사용 — 실행 폴더 기준 상대 경로(`"config/..."`) 금지
- GUI 새 화면/섹션은 `gui/`에 mixin 모듈로 추가하고 `WeeklyPulseApp` 상속 목록에 넣는다
- **Flet 0.86: 화면 갱신은 페이지 컨텍스트에 묶임** — 일반 `threading.Thread`에서 `page.update()`하면 오류 없이 무시된다. 백그라운드 작업은 `page.run_thread(fn)`, 주기 갱신은 `page.run_task(async_fn)` 사용
- LLM 응답 캐시(`complete(..., cache=True)`)는 temperature 0인 보고서 분석 단계 호출에만 — 응답을 검증해 버리고 재시도하는 수집 단계 호출에는 쓰지 않는다

## 검증

- 기능 테스트: `python tests/scenario_test.py` (51건, 결과는 `test_reports/*.xlsx`)
- 구버전 통합 테스트: `python tests/legacy/test_all_completed.py`
- 테스트에서 보고서를 만들 때는 `output_dir="test_reports"` 지정 — `reports/`에 쓰지 않는다
- 임시 스크립트는 `_tmp_*.py`로 만들고 작업 후 삭제. 남기려면 tests/ 개념으로 정리
- `data/`의 테스트 산출물은 `python scripts/cleanup_data.py --yes`로 정리
