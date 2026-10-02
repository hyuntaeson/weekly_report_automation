#!/usr/bin/env python3
"""
RAG 주제 질의 — 보고서 STEP 2 "주제 질의 요약" 섹션.

설정한 주제(장애 대응, 손익·예산 …)마다
  ① VectorDB에서 이번 주 활동 중 의미가 가까운 것을 찾고 (지난 N주도 함께)
  ② 보고서와 같은 규칙으로 거른 뒤 (노이즈·제외 채팅방·Teams 보고 범위·파트원만 수정한 공유 문서)
  ③ 번호 붙인 근거만 보고 LLM이 요약 — 문장마다 [번호] 인용 강제, 없는 번호를 단 문장은 버림
검색 부분(retrieve)은 STEP 3 예상 질문에서도 재사용한다.
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from weekly_report import paths
from weekly_report.storage.database import ActivityDatabase
from weekly_report.report.sections import classify_program, clean_text, is_my_work, to_local_datetime

SETTINGS_FILE = paths.REPORT_SETTINGS
QUERY_CACHE_FILE = paths.RAG_QUERY_CACHE
DEFAULT_SETTINGS = {
    # 사용자가 Settings에서 추가/삭제 — 행정 업무(손익·구매·계약)도 기본 포함
    "rag_topics": ["장애 대응", "배포·테스트", "결제 연동", "교육·역량 개발", "손익·예산", "구매·계약"],
    "rag_past_weeks": 4,
    # 활동 벡터 보관 기간(주) — 지난 주는 주간 요약 벡터로 남기고 삭제 (storage/retention.py)
    "vector_retention_weeks": 12,
    # 근거 제외 키워드 — 파일 경로·제목·내용에 들어 있으면 RAG·STEP 3 근거로 쓰지 않음
    # (이 프로그램 테스트 메모·이전 보고서 복사본이 원본 대화 대신 인용되는 것 방지)
    "evidence_exclude_keywords": ["주간보고 자동작성", "weekly_report", "WeeklyPulse"],
}
# 근거에서 통째로 빼는 프로그램 — IDE 기록은 거의 이 프로그램 개발 요청이라 업무 근거가 아님
# (STEP 1 프로그램별 기록에는 그대로 남는다)
EVIDENCE_EXCLUDED_PROGRAMS = {"Claude Code (IDE)", "Devin (IDE)"}
# 이 중 하나라도 있어야 근거 후보 (메시지·요약·메일 제목·채팅방·페이지 제목·메모 추가 내용)
EVIDENCE_CONTENT_KEYS = ("text", "summary", "subject", "chat", "title", "content_added")
# 코사인 유사도 기준 — 이 임베딩 모델에서 관련 기록은 보통 0.45~0.55, 무관한 기록은 0.2~0.3
MIN_SCORE = 0.40
# 문장과 그 문장이 인용한 근거의 유사도가 이보다 낮으면 그 인용은 엉뚱한 번호로 보고 지운다.
# 실측(9/28 주 보고서): 잘못 붙은 인용 0.20~0.40, 맞는 인용 대부분 0.44~0.75
SUPPORT_MIN_SCORE = 0.42
# 0.30~0.42는 임베딩만으론 구분이 안 되는 구간(맞는 인용 0.406 사례) → 핵심어가 근거 원문에 있는지로 판정
GRAY_MIN_SCORE = 0.30
KEYWORD_MIN_OVERLAP = 0.5
WEEK_TOP_K = 10
PAST_TOP_K = 3

RAG_PROMPT = (
    "너는 주간 업무 보고서를 쓰는 비서야. <evidence> 안의 번호 붙은 기록만 근거로, "
    "주제 '{topic}'와 관련해 이번 주 무슨 일이 있었는지 한국어 불릿 2~4개로 정리해. "
    "각 불릿은 '- '로 시작하고 무엇을·왜·결과를 알 수 있게 구체적으로 쓰며, "
    "끝에 핵심 근거 번호 1~3개를 [1][3]처럼 반드시 단다. "
    "인사·감사·인증번호 공유 같은 사소한 메시지는 근거로 쓰지 마. "
    "'(지난)' 표시가 붙은 기록은 지난주 이전 기록이므로, 이번 주 내용과 이어지는 경우에만 "
    "마지막 불릿 하나를 '- (지난 기록) …'으로 시작해 연결해 — 지난번에 무슨 일이 있었고 "
    "이번 주와 어떻게 이어지는지 의미가 충분히 전달되게 1~2문장으로 써도 된다. "
    "주제와 관련 없는 기록은 무시하고, 관련 기록이 하나도 없으면 NONE만 출력해. "
    "불릿 외에 서론·설명은 쓰지 마."
)
EXPAND_PROMPT = (
    "다음은 주간 업무 보고서의 주제야. 이 주제와 관련된 실제 업무 기록(메일·채팅·문서)에 "
    "나올 법한 핵심 표현과 키워드를 한국어로, 쉼표로 구분해 한 줄(15개 이내)만 출력해. "
    "IT 운영·개발 조직(POS 시스템) 기준으로 쓰고 설명은 붙이지 마."
)
MAX_REFS_PER_BULLET = 3


def load_report_settings(path=SETTINGS_FILE):
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(path, encoding="utf-8") as f:
            settings.update(json.load(f))
    except (OSError, json.JSONDecodeError):
        pass
    return settings


def save_report_settings(settings, path=SETTINGS_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def parse_cited_bullets(text, evidence_count):
    """LLM 출력 → 인용 번호가 유효한 불릿만. NONE이면 [].
    반환: [(불릿 문장, [인용 번호...])]"""
    if not text or text.strip().upper().startswith("NONE"):
        return []
    bullets = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(("-", "•", "*")):
            continue
        line = line.lstrip("-•* ").strip()
        refs = list(dict.fromkeys(int(n) for n in re.findall(r"\[(\d+)\]", line)))
        # 인용이 없거나 존재하지 않는 근거 번호를 단 문장은 근거 없는 주장으로 보고 버림
        if not refs or any(n < 1 or n > evidence_count for n in refs):
            continue
        if len(refs) > MAX_REFS_PER_BULLET:  # 근거 나열이 길면 앞의 핵심 몇 개만 남김
            for n in refs[MAX_REFS_PER_BULLET:]:
                line = line.replace(f"[{n}]", "")
            refs = refs[:MAX_REFS_PER_BULLET]
        bullets.append((line.strip(), sorted(refs)))
    return bullets


def _cosine(a, b):
    import numpy as np
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / denom) if denom else 0.0


# 핵심어 비교에서 뺄 조사·어미 꼬리와 흔한 말
_JOSA_RE = re.compile(r"(은|는|이|가|을|를|에|에서|의|로|으로|과|와|도|만|까지|부터|이며|하며|했으며|했고|하고|"
                      r"입니다|습니다|했습니다|합니다|됩니다|되었습니다|상태|예정)$")
_COMMON_WORDS = {"확인", "필요", "진행", "완료", "관련", "현재", "이번", "주간", "내용", "상태", "예정", "중입니다"}


def keyword_overlap(claim, evidence_text):
    """문장의 핵심어(2자 이상, 조사·흔한 말 제외) 중 근거 원문에 실제로 들어 있는 비율 (0~1)"""
    words = set()
    for token in re.findall(r"[가-힣A-Za-z0-9%./:]+", claim):
        token = _JOSA_RE.sub("", token)
        if len(token) >= 2 and token not in _COMMON_WORDS:
            words.add(token.lower())
    if not words:
        return 0.0
    haystack = (evidence_text or "").lower()
    return sum(w in haystack for w in words) / len(words)


def check_citations(items, evidence_vectors, embed, min_score=SUPPORT_MIN_SCORE,
                    evidence_texts=None):
    """문장마다 인용한 근거가 실제로 그 내용을 담고 있는지 확인 (하네스 검증).
    ① 임베딩 유사도 ≥ min_score → 유지, < GRAY_MIN_SCORE → 삭제
    ② 그 사이 애매한 구간은 문장 핵심어가 근거 원문 전체(evidence_texts)에 들어 있으면 유지
       — 긴 문서는 저장 벡터가 앞부분 위주라 뒤쪽 내용을 인용하면 유사도가 낮게 나옴
    items: [(문장, [근거 번호])], evidence_vectors: {번호: 벡터}, embed(texts) → 벡터 목록,
    evidence_texts: {번호: 근거 원문 전체}.
    반환: [(문장, 남은 번호)] — 지운 번호는 문장에서도 뺀다. 벡터가 없는 근거는 판단할 수 없어 그대로 둔다.
    임베딩 실패 시 검증 없이 그대로 반환."""
    evidence_texts = evidence_texts or {}

    def supported(claim, vector, n):
        if evidence_vectors.get(n) is None:
            return True
        score = _cosine(vector, evidence_vectors[n])
        if score >= min_score:
            return True
        return score >= GRAY_MIN_SCORE and keyword_overlap(claim, evidence_texts.get(n)) >= KEYWORD_MIN_OVERLAP

    if not items:
        return items
    claims = [re.sub(r"\s*\[\d+\]", "", text).strip() for text, _ in items]
    try:
        vectors = embed(claims)
    except Exception as error:
        print(f"Warning: citation check skipped: {error}")
        vectors = None
    if not vectors or len(vectors) != len(items):
        return items
    checked = []
    for (text, refs), vector, claim in zip(items, vectors, claims):
        kept = [n for n in refs if supported(claim, vector, n)]
        for n in set(refs) - set(kept):
            text = text.replace(f"[{n}]", "")
        checked.append((re.sub(r"\s{2,}", " ", text).strip(), kept))
    return checked


def evidence_label(activity, when):
    """보고서 근거 표시: '09/25 Teams · 운영&서버 방 — "거래저장 실패 원인 확인 중입니다."'
    출처 이름은 자르지 않고, 무엇을 말한 기록인지 요지(첫 문장)를 붙인다."""
    details = activity.get("details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (TypeError, ValueError):
            details = {}
    details = details if isinstance(details, dict) else {}
    program = classify_program(activity) or activity.get("source") or ""
    where = details.get("chat") or details.get("name") or details.get("subject") \
        or details.get("title") or os.path.basename(str(activity.get("file_path") or "")) or ""
    where = clean_text(where, 200)  # 상한은 비정상적으로 긴 URL 대비용
    label = f"{when:%m/%d} {program}" + (f" · {where}" if where else "")
    gist = evidence_gist(details)
    if gist and gist not in where:
        label += f' — "{gist}"'
    return label


# 인증번호·비밀번호가 섞인 메시지는 보고서에 옮기지 않는다 (요지 생략, 출처만 표시)
_SENSITIVE_RE = re.compile(r"인증\s*(번호|코드)|비밀\s*번호|패스워드|OTP|password|token|토큰", re.IGNORECASE)
# 요약 앞머리의 제목줄('# 핵심 요약' 등) — 내용이 아니라 빼고 시작
_SUMMARY_HEADING_RE = re.compile(r"^(핵심\s*)?요약\s*[:：]?\s*")
# 문장 부호 없이 이어지는 원문(로그·알림 전문)에만 쓰는 상한 — 문장으로 끝나는 요지는 자르지 않음
EVIDENCE_GIST_MAX = 200


# 줄 앞의 목록 번호·기호 ('1.', '2)', '■', '▶', '✅', '①', '1️⃣')
_LIST_MARK_RE = re.compile(r"^(?:\d{1,2}[.)](?!\d)\s*|[■□▶▷►●○◆◇✅☑✔•·\-*]\s*|[①-⑳]\s*|\d️?⃣\s*)+")
GIST_MIN_LINE = 12  # 이보다 짧은 줄은 소제목으로 보고 다음 내용 줄을 요지로


def evidence_gist(details):
    """근거 요지 — 메시지·요약·메모 추가 내용에서 내용이 있는 첫 문장.
    '팀장님.' 같은 호칭·대답 문장은 건너뛰고, 문장은 길이와 무관하게 통째로 쓴다.
    문장 부호 없이 이어지는 원문만 EVIDENCE_GIST_MAX 근처 단어 경계에서 끊는다."""
    raw = str(details.get("text") or details.get("summary") or details.get("content_added") or "")
    if not raw.strip() or _SENSITIVE_RE.search(raw):
        return ""
    # 여러 줄 요약(# 제목 / 항목: 내용 …)은 한 덩어리로 펴면 요지가 묻히므로, 제목줄·목록 번호('1.', '■', '✅')를
    # 떼고 '산출물'·'요구사항 정의' 같은 짧은 소제목 줄은 건너뛴 첫 내용 줄
    lines = [_LIST_MARK_RE.sub("", _SUMMARY_HEADING_RE.sub("", clean_text(line, None))).strip()
             for line in raw.splitlines() if not line.lstrip().startswith("#")]
    lines = [line for line in lines if line and not is_trivial_reply(line)]
    text = next((line for line in lines if len(line) >= GIST_MIN_LINE), lines[0] if lines else "")
    sentences = [s for s in re.split(r"(?<=[.!?。])\s+", text) if s and not is_trivial_reply(s)]
    if not sentences:
        return ""
    first = sentences[0]
    if re.search(r"[.!?。]$", first) or len(first) <= EVIDENCE_GIST_MAX:
        return first
    return clean_text(first, EVIDENCE_GIST_MAX)


# 호칭('팀장님')·문장부호를 걷어낸 뒤 이것만 남으면 단순 대답
_TRIVIAL_REPLY_RE = re.compile(
    r"^(네+|넵|넹|예|응|ㅇㅇ|ㅇㅋ|ok|오케이|확인(했습니다|했어요|부탁드립니다|부탁드려요)?|알겠습니다|"
    r"감사합니다|고맙습니다|수고(하셨습니다|많으셨습니다)?)?$", re.IGNORECASE)


def is_trivial_reply(text):
    """'네 팀장님.' '확인했습니다~' 처럼 내용 없는 대답인지"""
    core = re.sub(r"\S*님", "", clean_text(text, None))
    core = re.sub(r"[\s.!~?,^]+|요$", "", core)
    return bool(_TRIVIAL_REPLY_RE.match(core))


def is_evidence_noise(activity, keywords):
    """RAG·STEP 3 근거로 쓰면 안 되는 활동: IDE 기록, 또는 경로·제목·내용에 제외 키워드 포함"""
    if classify_program(activity) in EVIDENCE_EXCLUDED_PROGRAMS:
        return True
    keywords = [k.lower() for k in keywords if k and k.strip()]
    if not keywords:
        return False
    details = activity.get("details")
    if isinstance(details, str):  # 수집기에 따라 한글이 \uXXXX로 저장돼 있어 풀어서 비교
        try:
            details = json.loads(details)
        except (TypeError, ValueError):
            pass
    if not isinstance(details, str):
        details = json.dumps(details or {}, ensure_ascii=False)
    haystack = f"{activity.get('file_path') or ''} {details}".lower()
    return any(k in haystack for k in keywords)


class TopicQueryRAG:
    def __init__(self, generator, config_path=None):
        from weekly_report.ai.clusterer import ActivityClusterer
        from weekly_report.ai.llm_summarizer import LLMSummarizer
        from weekly_report.storage.vector_store import ActivityVectorStore

        config_path = config_path or paths.LITELLM_CONFIG
        self.gen = generator
        self.clusterer = ActivityClusterer(config_path)
        self.llm = LLMSummarizer(config_path)
        self.store = ActivityVectorStore()
        teams_settings, self.me_name = generator._teams_context()
        self.teams_scope = teams_settings.get("report_scope", "mine")
        excluded = teams_settings.get("excluded_chats", [])
        self.excluded_ids = {c.get("id") for c in excluded if isinstance(c, dict)}
        self.excluded_titles = {c.get("title") for c in excluded if isinstance(c, dict)}
        self.noise_keywords = load_report_settings().get("evidence_exclude_keywords", [])

    @property
    def enabled(self):
        return self.clusterer.enabled

    # ---------- 검색 ----------

    def eligible(self, activity):
        """보고서 STEP 2와 같은 기준: 내 업무 + 제외 채팅방 아님 + Teams 보고 범위
        + 근거 노이즈 아님(IDE·제외 키워드) + 이름뿐인 기록 아님."""
        if not is_my_work(activity, self.me_name) or is_evidence_noise(activity, self.noise_keywords):
            return False
        details = activity.get("details")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (TypeError, ValueError):
                details = {}
        details = details if isinstance(details, dict) else {}
        # 이름뿐인 기록(첨부파일·스크린샷·제목 없는 방문 URL·파일 이동)은 근거로 주면
        # LLM이 내용과 무관한 답에 번호를 붙이므로 제외 — 메모·메일·대화처럼 내용이 있는 것만
        if not any(str(details.get(k) or "").strip() for k in EVIDENCE_CONTENT_KEYS):
            return False
        if activity.get("source") != "teams":
            return True
        if activity.get("action") == "message" and is_trivial_reply(details.get("text")):
            return False  # '네 팀장님.' 같은 대답은 근거가 되지 않는다 (LLM이 아무 답에나 번호를 붙임)
        if details.get("chat_id") in self.excluded_ids or details.get("chat") in self.excluded_titles:
            return False
        if activity.get("action") == "message" and self.teams_scope != "all":
            return bool(details.get("from_me") or (self.me_name and details.get("sender") == self.me_name))
        return True

    def retrieve(self, vectors, date_from, date_to, pool, limit, sender_contains=None):
        """질의 벡터마다 기간 내 의미가 가까운 활동 → pool(허용된 활동 key→activity)에 있는 것만.
        반환: 벡터별 [(score, activity)]"""
        requests = [
            {"vector": v, "limit": limit * 3, "date_from": date_from, "date_to": date_to,
             "sender_contains": sender_contains, "min_score": MIN_SCORE}
            for v in vectors
        ]
        results = []
        for hits in self.store.search_many(requests):
            picked = [(h["score"], pool[h["key"]]) for h in hits if h["key"] in pool]
            results.append(picked[:limit])
        return results

    def topic_queries(self, topics):
        """주제명 → 검색 질의문. '장애 대응' 네 글자만으로는 '거래저장 실패' 같은 실제 기록과
        유사도가 낮아서, LLM으로 관련 표현을 붙여 질의를 풍부하게 만든다 (주제별 1회, 파일 캐시)."""
        try:
            with open(QUERY_CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}
        changed = False
        for topic in topics:
            if topic in cache:
                continue
            keywords = self.llm.complete(EXPAND_PROMPT, topic, max_tokens=200, temperature=0)
            keywords = clean_text((keywords or "").splitlines()[0] if keywords else "", 300)
            if keywords:  # 실패하면 캐시하지 않고 다음에 다시 시도
                cache[topic] = keywords
                changed = True
        if changed:
            os.makedirs(os.path.dirname(QUERY_CACHE_FILE), exist_ok=True)
            with open(QUERY_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
        return [f"{t}: {cache[t]}" if cache.get(t) else t for t in topics]

    # ---------- 섹션 생성 ----------

    def build_sections(self, week_activities, week_start, week_end):
        """주제별 [{"topic", "bullets": [str], "evidence": [{"n", "label", "past"}]}]. 근거 없는 주제는 생략."""
        settings = load_report_settings()
        topics = [t for t in settings.get("rag_topics", []) if t.strip()]
        if not topics or not self.enabled:
            return []
        past_weeks = int(settings.get("rag_past_weeks") or 0)
        start = datetime.strptime(week_start, "%Y-%m-%d")
        past_from = (start - timedelta(weeks=past_weeks)).strftime("%Y-%m-%d")
        past_to = (start - timedelta(days=1)).strftime("%Y-%m-%d")
        past_activities = self.gen.fetch_week_activities(past_from, past_to) if past_weeks else []

        # 검색 범위의 활동이 VectorDB에 다 들어 있도록 (없는 것만 임베딩)
        if self.clusterer.embed_activities(week_activities + past_activities) is None:
            return []
        key = ActivityDatabase.activity_key
        week_pool = {key(a): a for a in week_activities if self.eligible(a)}
        past_pool = {key(a): a for a in past_activities if self.eligible(a)}

        topic_vectors = self.clusterer.embed(self.topic_queries(topics))
        if not topic_vectors:
            return []
        week_hits = self.retrieve(topic_vectors, week_start, week_end, week_pool, WEEK_TOP_K)
        past_hits = (self.retrieve(topic_vectors, past_from, past_to, past_pool, PAST_TOP_K)
                     if past_pool else [[] for _ in topics])

        # 이번 주 근거가 없는 주제는 지난 기록도 붙이지 않고 생략. 주제별 요약(LLM 대기)은 동시에
        jobs = [(topic, hits, old) for topic, hits, old in zip(topics, week_hits, past_hits) if hits]
        if not jobs:
            return []
        with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as pool:
            results = list(pool.map(lambda job: self._summarize(*job), jobs))
        return [section for section in results if section]

    def evidence_vectors(self, evidence):
        """근거 목록(각 항목에 'activity') → {번호: 저장된 활동 벡터} (VectorDB·메모리 재사용, 새 임베딩 없음)"""
        activities = [e["activity"] for e in evidence]
        try:
            vectors = self.clusterer._embed_with_cache(
                activities, [self.clusterer._activity_text(a) for a in activities]) or []
        except Exception as error:
            print(f"Warning: evidence vectors unavailable: {error}")
            vectors = []
        return {i: v for i, v in enumerate(vectors, start=1) if v is not None}

    @staticmethod
    def evidence_texts(evidence):
        """근거 목록 → {번호: 원문 전체} (경로 + 메시지·요약·제목 등, 자르지 않음) — 인용 핵심어 확인용"""
        texts = {}
        for i, e in enumerate(evidence, start=1):
            activity = e["activity"]
            details = activity.get("details")
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except (TypeError, ValueError):
                    details = {}
            details = details if isinstance(details, dict) else {}
            parts = [str(activity.get("file_path") or "")] + [str(details.get(k) or "") for k in EVIDENCE_CONTENT_KEYS]
            texts[i] = clean_text(" ".join(parts), None)
        return texts

    def _summarize(self, topic, hits, old):
        evidence = []
        for past, items in ((False, hits), (True, old)):
            for _, activity in items:
                when = to_local_datetime(activity.get("timestamp"), activity.get("source"))
                if when:
                    text = self.clusterer._activity_text(activity)
                    if classify_program(activity) == "Chrome":
                        text = f"{evidence_label(activity, when)} {text}"  # 방문 URL만으론 뜻을 몰라 페이지 제목을 붙임
                    evidence.append({"label": evidence_label(activity, when), "past": past, "text": text,
                                     "activity": activity})
        if not evidence:
            return None
        body = "<evidence>\n" + "\n".join(
            f"[{i}] {'(지난) ' if e['past'] else ''}{e['label']} | {clean_text(e['text'], 300)}"
            for i, e in enumerate(evidence, start=1)
        ) + "\n</evidence>"
        output = self.llm.complete(RAG_PROMPT.format(topic=topic), body,
                                   max_tokens=800, max_input=8000, temperature=0, cache=True)
        bullets = parse_cited_bullets(output, len(evidence))
        if output and output.strip().upper().startswith("NONE"):
            return None  # 검색은 걸렸지만 LLM이 주제와 무관하다고 판단
        if bullets:
            # 엉뚱한 근거 번호는 지우고, 맞는 근거가 하나도 안 남은 불릿은 근거 없는 주장으로 버림
            bullets = [b for b in check_citations(bullets, self.evidence_vectors(evidence), self.clusterer.embed,
                                                  evidence_texts=self.evidence_texts(evidence))
                       if b[1]]
            if not bullets:
                return None
        else:
            # LLM 실패·형식 오류 → 이번 주 근거 제목으로 대체
            bullets = [(e["label"], [i]) for i, e in enumerate(evidence[:3], start=1) if not e["past"]]
        # 인용된 근거만 1부터 다시 번호 매김 ([2][5] → [1][2]).
        # 같은 날 같은 채팅방처럼 출처 표시가 같은 근거는 한 번호로 합친다
        cited = sorted({n for _, refs in bullets for n in refs})
        renum, sources = {}, []
        for n in cited:
            source = (evidence[n - 1]["label"], evidence[n - 1]["past"])
            if source not in sources:
                sources.append(source)
            renum[n] = sources.index(source) + 1

        def rewrite_run(match):  # '[2][5][3]' → 새 번호로, 합쳐져 겹친 번호는 하나만
            nums = sorted({renum.get(int(n), int(n)) for n in re.findall(r"\d+", match.group(0))})
            return "".join(f"[{n}]" for n in nums)

        def rewrite(text):
            return re.sub(r"(?:\[\d+\]\s*)+", lambda m: rewrite_run(m) + (" " if m.group(0).endswith(" ") else ""), text).strip()

        return {
            "topic": topic,
            "bullets": [rewrite(t) for t, _ in bullets],
            "evidence": [{"n": i, "label": label, "past": past}
                         for i, (label, past) in enumerate(sources, start=1)],
        }


def search_past_weeks(query, limit=3, min_score=MIN_SCORE, db_path=paths.DB_PATH,
                      summaries=None, embed=None):
    """장기 질의 ("지난 분기 결제 업무") — 보관 기간이 지나 활동 벡터가 지워진 주까지 찾는다.
    ① 주간 요약 벡터에서 관련 주를 찾고 ② 그 주의 원본 활동은 SQLite에서 꺼내 상세 근거로 붙인다.
    반환: [{"week_start", "week_end", "score", "text"(주간 요약), "activities"}] 유사도 내림차순"""
    from weekly_report.storage.vector_store import WeekSummaryStore

    if embed is None:
        from weekly_report.ai.clusterer import ActivityClusterer
        embed = ActivityClusterer().embed
    vectors = embed([query])
    if not vectors:
        return []
    hits = (summaries or WeekSummaryStore()).search(vectors[0], limit=limit, min_score=min_score)
    with ActivityDatabase(db_path) as db:
        for hit in hits:
            hit["activities"] = db.get_activities_by_date_range(hit["week_start"], hit["week_end"])
    return hits
