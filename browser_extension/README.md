# 📊 Chrome 브라우저 확장 프로그램 - 웹페이지 활동 추적

이 Chrome 확장 프로그램은 사용자가 방문한 웹페이지의 URL, 제목, 방문 시각을 자동으로 수집하여 주간보고 시스템에 전달합니다.

## 🚀 설치 방법

### 1단계: 로컬 서버 시작

확장 프로그램이 데이터를 보낼 로컬 HTTP 서버를 먼저 실행해야 합니다.

```bash
python -m weekly_report.collectors.browser_server
```

성공 메시지:
```
Browser Activity Server started on http://127.0.0.1:5757
Endpoint: POST http://127.0.0.1:5757/activity
Database: data/activities.db
```

**주의**: 이 서버는 항상 실행 중이어야 브라우저 확장이 활동을 기록할 수 있습니다.

### 2단계: Chrome 확장 프로그램 로드

#### Chrome 개발자 모드 활성화

1. Chrome 주소 표시줄에 `chrome://extensions` 입력 후 이동
2. **개발자 모드** 토글 (우상단)을 **ON**으로 전환

#### 확장 프로그램 로드

1. **압축 해제된 확장 프로그램 로드** 클릭
2. 프로젝트 경로에서 `browser_extension` 폴더 선택
3. **폴더 선택** 클릭

#### 로드 완료

- Chrome 확장 프로그램 목록에 "Weekly Report Activity Tracker" 표시
- 확장 프로그램 아이콘이 Chrome 우상단에 나타남

### 3단계: 확장 프로그램 사용

1. Chrome 우상단의 확장 프로그램 아이콘 클릭
2. 팝업에서 **추적 활성화** 토글로 활동 추적 on/off 제어
3. 웹페이지 방문시 자동으로 활동 기록

## 🔒 프라이버시 및 보안

### 자동 제외되는 URL 패턴

다음 URL은 민감정보 보호를 위해 자동으로 제외됩니다:

- **브라우저 내부 페이지**: `chrome://`, `about:`, `file://`, `edge://`
- **인증 관련**: `accounts.google.com`, `login.`, `signin`, `password`
- **금융**: `.bank`, `banking`, `credit-card`, `paypal.com`
- **소셜 미디어**: `facebook.com/login`, `twitter.com/login`
- **기타 보안**: `oauth`, `microsoft.com/oauth` 등

### 수집 정보

**수집되는 정보:**
- 방문한 URL
- 웹페이지 제목
- 방문 시각 (ISO 8601 형식)

**수집되지 않는 정보:**
- URL 쿼리 스트링 (제거되지 않음 - 전체 URL이 기록됨)
- 페이지 내용
- 쿠키 또는 로컬 저장소
- 검색 기록

### 데이터 저장 위치

모든 데이터는 **로컬 시스템의 SQLite 데이터베이스**에만 저장됩니다:
- 위치: `data/activities.db`
- 외부 서버로 전송되지 않음
- 오직 `http://localhost:5757`로만 통신

## ⚙️ 설정

### 포트 변경

기본 포트 5757을 다른 포트로 변경하려면:

1. `weekly_report/collectors/browser_server.py`에서 `main()` 함수 수정:
```python
server = BrowserActivityServer(
    db_path='data/activities.db',
    host='127.0.0.1',
    port=YOUR_PORT  # 변경할 포트 번호
)
```

2. `browser_extension/background.js`에서 서버 URL 수정:
```javascript
const SERVER_URL = 'http://localhost:YOUR_PORT/activity';
```

### 필터링 규칙 커스터마이징

민감한 도메인을 추가하거나 제거하려면 `browser_extension/background.js`의 `SENSITIVE_PATTERNS` 배열을 수정하세요:

```javascript
const SENSITIVE_PATTERNS = [
  'chrome://',
  'about:',
  // ... 기타 패턴
  'your-custom-domain.com'  // 추가
];
```

## 🧪 테스트

### 수동 테스트

1. 로컬 서버 실행
2. 확장 프로그램 로드
3. 몇 개의 웹페이지 방문
4. 데이터베이스 확인:
```bash
python scripts/check_database.py
```

### 자동 테스트

```bash
python tests/legacy/test_all_completed.py
```

테스트 결과에 `browser_activity_server: passed` 항목이 표시됩니다.

## 🔍 데이터베이스 조회

저장된 브라우저 활동을 확인하려면:

```bash
python scripts/check_database.py
```

또는 직접 SQL 쿼리:

```python
from database import ActivityDatabase

with ActivityDatabase('data/activities.db') as db:
    activities = db.get_activities_by_date_range('2024-09-21', '2024-09-22')
    for act in activities:
        if act['source'] == 'browser':
            print(f"URL: {act['file_path']}")
            print(f"Title: {act['details']}")
```

## 🐛 문제 해결

### 확장 프로그램이 활동을 기록하지 않는 경우

**원인 1: 로컬 서버가 실행되지 않음**
- 해결: `python -m weekly_report.collectors.browser_server` 실행

**원인 2: 포트 충돌**
- 확인: `netstat -an | findstr 5757` (Windows) 또는 `lsof -i :5757` (Mac/Linux)
- 해결: 다른 포트 사용 또는 기존 프로세스 종료

**원인 3: 확장 프로그램이 비활성화됨**
- 확인: `chrome://extensions`에서 "Weekly Report Activity Tracker" 상태 확인
- 해결: 토글을 ON으로 전환

### 특정 URL이 기록되지 않는 경우

URL이 자동 제외 목록에 포함되었을 가능성:
- `browser_extension/background.js`의 `SENSITIVE_PATTERNS` 확인
- 콘솔 로그: F12 → DevTools → "Activity Tracker" 검색

## 📊 통합 실행

로컬 서버를 `IntegratedCollector`에 포함시켜 통합 실행할 수 있습니다:

```python
from integrated_collector import IntegratedCollector

collector = IntegratedCollector(
    watch_paths=['C:\\Users\\YourName\\Documents'],
    enable_browser_server=True  # 브라우저 서버 활성화
)
collector.start()
```

## 📋 파일 구조

```
browser_extension/
├── manifest.json        # Chrome 확장 설정
├── background.js        # Service Worker (핵심 로직)
├── popup.html          # UI 토글 페이지
├── popup.js            # 토글 로직
└── icons/
    ├── icon-16.png
    ├── icon-48.png
    └── icon-128.png

weekly_report/collectors/browser_server.py  # 로컬 HTTP 서버
```

## 🔗 관련 문서

- [주간보고 자동화 README](README.md)
- [데이터베이스 스키마](../weekly_report/storage/database.py)
- [통합 수집 시스템](../weekly_report/collectors/integrated.py)

## 📞 지원

문제 발생 시:
1. 로컬 서버 로그 확인
2. Chrome DevTools (F12) 콘솔 확인
3. `tests/legacy/test_all_completed.py` 실행으로 시스템 상태 점검

## 📄 라이선스

이 프로젝트의 일부입니다. 자세한 내용은 [LICENSE](LICENSE)를 참조하세요.
