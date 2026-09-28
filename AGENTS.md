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

## 검증

- 기능 테스트: `python scenario_test.py` (32건, 결과는 `test_reports/*.xlsx`)
- 구버전 통합 테스트: `python test_all_completed.py`
- 임시 스크립트는 `_tmp_*.py`로 만들고 작업 후 삭제. 남기려면 tests/ 개념으로 정리
- `data/`의 테스트 산출물은 `python cleanup_data.py --yes`로 정리
