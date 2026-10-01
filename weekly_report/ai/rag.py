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
}
# 코사인 유사도 기준 — 이 임베딩 모델에서 관련 기록은 보통 0.45~0.55, 무관한 기록은 0.2~0.3
MIN_SCORE = 0.40
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


def evidence_label(activity, when):
    """보고서 근거 표시용 짧은 출처: '09/25 Teams · 운영&서버 방'.
    본문(메시지·요약)은 넣지 않는다 — 길고 인증번호 같은 민감 내용이 섞일 수 있어서."""
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
    return f"{when:%m/%d} {program}" + (f" · {clean_text(where, 30)}" if where else "")


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

    @property
    def enabled(self):
        return self.clusterer.enabled

    # ---------- 검색 ----------

    def eligible(self, activity):
        """보고서 STEP 2와 같은 기준: 내 업무 + 제외 채팅방 아님 + Teams 보고 범위."""
        if not is_my_work(activity, self.me_name):
            return False
        details = activity.get("details")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (TypeError, ValueError):
                details = {}
        details = details if isinstance(details, dict) else {}
        if classify_program(activity) == "Chrome":
            # 제목 없는 방문 URL(게이트웨이·로그인 페이지 등)은 내용이 없어 근거로 쓰지 않음
            return bool(details.get("title"))
        if activity.get("source") != "teams":
            return True
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

    def _summarize(self, topic, hits, old):
        evidence = []
        for past, items in ((False, hits), (True, old)):
            for _, activity in items:
                when = to_local_datetime(activity.get("timestamp"), activity.get("source"))
                if when:
                    text = self.clusterer._activity_text(activity)
                    if classify_program(activity) == "Chrome":
                        text = f"{evidence_label(activity, when)} {text}"  # 방문 URL만으론 뜻을 몰라 페이지 제목을 붙임
                    evidence.append({"label": evidence_label(activity, when), "past": past, "text": text})
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
        if not bullets:
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
