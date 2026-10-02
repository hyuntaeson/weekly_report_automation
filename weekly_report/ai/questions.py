#!/usr/bin/env python3
"""
STEP 3 예상 질문 & 답변 — Settings > Teams '예상질문자'마다

  ① 수집: DB에 쌓인 Teams 메시지 중 발신자가 예상질문자인 업무 메시지 (같은 방 직전 대화를 맥락으로)
  ② 성향: 질문형 메시지로 질문 성향 3~4줄 + 대표 예시 (새 메시지가 생길 때만 다시 분석, 파일 캐시)
  ③ 맥락: 이번 주 보고 내용(STEP 2 핵심 요약·주제 질의 요약)마다
          그 사람의 과거 메시지 중 의미가 가까운 것 + 이번 주 내 활동 근거를 검색 (rag.retrieve 재사용)
  ④ 생성: 그 사람 말투의 질문 + 보고체 답변 — 답변은 [번호] 인용 필수,
          근거 없는 사실은 '확인 필요' (인용도 '확인 필요'도 없으면 자동으로 붙임)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from weekly_report import paths
from weekly_report.ai.rag import TopicQueryRAG, _cosine, check_citations, evidence_full_text, evidence_label
from weekly_report.common.timeutil import to_local_datetime
from weekly_report.report.sections import clean_text, condense
from weekly_report.storage.database import ActivityDatabase

QUESTION_COUNT = 5
CANDIDATE_EXTRA = 3        # 반복 질문을 걸러낼 여유분만큼 더 생성
HISTORY_WEEKS = 8          # 질문 성향·과거 대화를 찾는 기간
CONTEXT_BEFORE = 3         # 질문 앞에 붙일 같은 방 직전 메시지 수
CONTEXT_WINDOW = timedelta(hours=3)
PAST_PER_POINT = 2         # 보고 항목 하나당 그 사람의 비슷한 과거 메시지 수
WEEK_PER_POINT = 3         # 보고 항목 하나당 이번 주 내 활동 근거 수
QUESTION_EVIDENCE_K = 3    # 질문이 만들어진 뒤 질문으로 다시 찾는 근거 수 (2단계 검색)
# 2단계 근거는 질문과 이 이상 가까울 때만 — 실측: 맞는 근거 0.46~0.66, 단어만 겹친 남의 건(덴텀 프린터 테스트가
# '주간보고 프로그램 테스트' 질문에 붙음) 0.42. 낮은 근거를 주면 답변이 그 내용을 베껴 관련성·사실 대조를 모두 통과함
QUESTION_EVIDENCE_MIN = 0.45
MAX_POINTS = 16            # STEP 2 핵심 요약 + 주제 질의 요약 불릿
PAST_MIN_SCORE = 0.35
STYLE_SAMPLE = 40
STYLE_CACHE_FILE = os.path.join(paths.DATA_DIR, "questioner_style.json")
STYLE_VERSION = 1

# 대답·맞장구처럼 내용이 없는 메시지
_TRIVIAL_RE = re.compile(r"^(어+|엉|잉|응|네+|넵|넹|예|ㅇㅇ|ㅇㅋ|ok|오케이|했어|봤어|그래|알겠|감사|고마|수고)[\s.!~요]*$", re.I)
_QUESTION_RE = re.compile(r"\?|거지|건가|는지|었나|였나|인가|없나|않어|않나|어때|언제|어디|뭐|왜|몇시|됐어|된거|했어\?|해\?")

STYLE_PROMPT = (
    "아래는 한 사람(직장 상사)이 Teams에서 보낸 질문 메시지들이야. 이 사람이 업무 보고를 받을 때 "
    "어떤 관점으로 질문하는지 성향을 한국어 불릿 3~4개로 정리해 (예: 과거 유사 이슈와 연결해서 묻는다, "
    "일정·완료 시점을 확인한다). 각 불릿은 '- '로 시작하고 한 문장으로. "
    "마지막 줄에 이 성향을 가장 잘 보여주는 메시지 번호 3개를 '대표: [3][7][12]' 형식으로 써. "
    "그 외 설명은 쓰지 마."
)
ANSWER_RULES = (
    "- 답변은 보고체로, 질문이 묻는 것을 빠짐없이 답하되 간결하게 (보통 2~4문장). 반드시 이 순서로 쓴다:\n"
    "  ① <evidence>·<report>로 알 수 있는 현재 상태를 먼저 구체적으로 쓴다 (무엇을 어디까지 했는지, 수치·일정 포함).\n"
    "  ② 질문이 묻는 것 중 자료로 확인되지 않는 부분(원인·일정·결과 등)만 '~는 확인 필요'로 덧붙인다. "
    "지어내지 않는다. '확인 필요'만 단독으로 쓰지 않는다 — 자료에 관련 내용이 조금이라도 있으면 그것부터 답한다.\n"
    "  ③ 끝에 출처: <evidence>에 실제로 적힌 사실이면 [1][3]처럼 그 번호, <evidence>에는 없고 <report>에만 있으면 (보고 내용).\n"
    "  '(지난 보고)' 근거는 AI가 만든 지난주 보고서 요약(2차 자료)이다 — 같은 사실의 원본 근거가 있으면 원본 번호를 달고, "
    "지난 보고로만 확인되는 사실은 문장에 '(지난 보고 기준)'을 붙인다.\n"
    "  <report>에서 '(근거 기록 없음)' 표시된 항목에 대한 질문은 <evidence>를 쓰지 말고 보고 내용으로만 답한다 "
    "(단어가 비슷한 다른 업무 기록을 끌어오지 않는다).\n"
    "  예) A: 프로그램 개발은 완료됐고 테스트 장비는 9월 초 제공 예정으로 문서에 반영돼 있습니다. 실제 장비 수령·테스트 착수 여부는 확인 필요합니다. [2]\n"
)

QA_PROMPT = (
    "너는 주간 업무 보고를 준비하는 담당자의 비서야. 상사 '{name}'이(가) 이번 주 보고를 듣고 "
    "물어볼 만한 질문 {count}개와 답변 초안을 만들어.\n"
    "[상사의 질문 성향]\n{style}\n[상사의 실제 말투 예시]\n{examples}\n\n"
    "규칙:\n"
    "- 질문은 <report>의 이번 주 보고 내용에 대한 것이어야 하고, 상사의 말투(반말·짧은 구어체 등)를 그대로 따른다. "
    "<past>에 이번 주 보고와 같은 주제의 과거 발언이 있으면 "
    "질문 1~2개는 그 발언과 연결해서 묻고 질문 끝에 [P2]처럼 그 번호를 단다 (주제가 다르면 연결하지 않는다).\n"
    "- <asked>는 상사가 이번 주에 이미 한 질문이다. 같은 질문을 반복하지 말고, 필요하면 그 결과나 후속 조치를 묻는다.\n"
    + ANSWER_RULES +
    "- <past>는 상사의 과거 발언일 뿐 사실 근거가 아니므로 답변에 쓰지 않는다.\n"
    "- 출력 형식은 질문마다 정확히 두 줄:\nQ: 질문 [P번호(있을 때만)]\nA: 답변 [번호] 또는 (보고 내용)\n"
    "- 그 외 서론·설명은 쓰지 마."
)


REANSWER_PROMPT = (
    "너는 주간 업무 보고를 준비하는 담당자의 비서야. 아래 질문마다, 그 질문 바로 밑의 근거와 <report>만 보고 "
    "답변을 다시 써.\n" + ANSWER_RULES +
    "- 출력은 질문마다 한 줄: 'A1: 답변 [번호]' 형식. 번호는 그 질문 밑에 있는 근거 번호만 쓴다. 그 외 설명은 쓰지 마."
)


FIXED_ANSWER_PROMPT = (
    "너는 주간 업무 보고를 준비하는 담당자의 비서야. 상사의 아래 질문마다 <evidence>와 <report>만 보고 답변을 써.\n"
    + ANSWER_RULES +
    "- 출력은 질문마다 한 줄: 'A1: 답변 [번호]' 형식. 그 외 설명은 쓰지 마."
)


def parse_reanswers(output, allowed):
    """재답변 출력 → {질문 순번: (답변, [근거 번호])}. allowed: {질문 순번: 그 질문에 준 근거 번호 집합}.
    질문에 주지 않은 번호는 지우고, 남은 번호가 없으면 '(확인 필요)' 표시 (parse_qa와 같은 규칙)."""
    result = {}
    for k, answer in re.findall(r"(?m)^\s*A(\d+)\s*[:.]\s*(.+)$", output or ""):
        k = int(k)
        if k not in allowed:
            continue
        refs = [n for n in dict.fromkeys(int(m) for m in re.findall(r"\[(\d+)\]", answer)) if n in allowed[k]]
        answer = re.sub(r"\s{2,}", " ", re.sub(r"\[\d+\]", "", answer)).strip()
        if refs:
            answer += " " + "".join(f"[{n}]" for n in sorted(refs))
        else:
            answer = mark_unsupported(answer)
        result[k] = (answer, sorted(refs))
    return result


FACT_CHECK_PROMPT = (
    "번호마다 '답변'을 바로 아래 '근거' 원문과 대조해. 답변이 말한 사실(용도·대상·숫자·일정·상태)이 "
    "근거와 맞으면 OK, 근거와 다르거나 근거를 왜곡했으면 DIFF, 답변의 핵심 사실이 근거에 아예 없으면 NONE. "
    "'확인 필요'라고 남겨 둔 부분은 판정 대상이 아니다. 같은 사실을 다른 말로 쓴 것은 OK다. "
    "답변마다 한 줄씩 '답변1: OK - 이유(짧게)' 형식으로 답해. 근거의 [번호]가 아니라 '답변N' 번호로 답한다."
)
DIFF_MARK = "(근거와 다름, 확인 필요)"


def fact_check_answers(answers, evidence_texts, complete):
    """LLM-as-judge 사실 대조: 근거 번호가 붙은 답변을 인용 근거 원문과 비교해 표시만 단다 (내용은 고치지 않음).
    answers: [(답변, [근거 번호])], evidence_texts: {번호: 원문}, complete(system, body) → 응답.
    반환: 답변 목록 — 근거와 다르면 '(근거와 다름, 확인 필요)', 근거에 없으면 '(확인 필요)'. 판정 실패 시 그대로."""
    targets = [(i, a, refs) for i, (a, refs) in enumerate(answers) if refs]
    if not targets:
        return [a for a, _ in answers]
    strip_refs = lambda text: re.sub(r"\s*\[\d+\]", "", text)
    body = "\n\n".join(
        f"답변{k}: {strip_refs(a)}\n   근거:\n"
        + "\n".join(f"   [{n}] {clean_text(evidence_texts.get(n), 1500)}" for n in refs)
        for k, (_, a, refs) in enumerate(targets, start=1))
    try:
        output = complete(FACT_CHECK_PROMPT, body) or ""
    except Exception as error:
        print(f"Warning: answer fact check skipped: {error}")
        output = ""
    # 답변 번호를 근거 [번호]와 다른 '답변N'으로, 판정엔 짧은 이유를 같이 쓰게 함 — 한 단어 판정은 오탐이 잦았음
    # (실측: 근거와 같은 답변이 이유 없이는 DIFF, 이유와 함께는 OK)
    verdict = {int(k): v.upper() for k, v in re.findall(r"답변\s*(\d+)\s*[:：.]\s*(OK|DIFF|NONE)", output, re.I)}
    result = [a for a, _ in answers]
    for k, (i, a, _) in enumerate(targets, start=1):
        if verdict.get(k) == "DIFF":
            result[i] = f"{a} {DIFF_MARK}"
        elif verdict.get(k) == "NONE" and "확인 필요" not in a:
            result[i] = f"{a} (확인 필요)"
    return result


LINK_JUDGE_PROMPT = (
    "각 번호마다 '질문'이 '과거 발언'과 같은 업무 이슈(같은 시스템·같은 건·같은 작업)를 다루는지 판정해. "
    "단어 몇 개가 겹치는 것만으로는 같은 이슈가 아니다. "
    "번호마다 한 줄씩 '1: Y' 또는 '1: N' 형식으로만 답해."
)


def _details(activity):
    details = activity.get("details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (TypeError, ValueError):
            details = {}
    return details if isinstance(details, dict) else {}


def short_name(sender):
    """'이세형(이마트24POS) - 이마트24POS팀' → '이세형'"""
    return (sender or "").split("(")[0].split(" - ")[0].strip() or "?"


def is_meaningful(text):
    text = (text or "").strip()
    return len(text) >= 6 and not _TRIVIAL_RE.match(text) and not text.startswith("http")


def is_question(text):
    return bool(_QUESTION_RE.search(text or ""))


def is_repeat(question, asked_texts, threshold=0.6):
    """이미 한 질문과 거의 같은 문장인지 (공백·문장부호 무시, 문자열 유사도)"""
    norm = lambda t: re.sub(r"[\s?!.,~]", "", t or "")
    q = norm(question)
    return any(SequenceMatcher(None, q, norm(t)).ratio() >= threshold for t in asked_texts if t)


def _take_refs(text, pattern, count):
    """text에서 pattern 번호들을 떼어 (정리된 text, 범위 안 번호 목록)"""
    refs = [n for n in dict.fromkeys(int(m) for m in re.findall(pattern, text)) if 1 <= n <= count]
    return re.sub(r"\s{2,}", " ", re.sub(pattern, "", text)).strip(), sorted(refs)


def is_bare_answer(answer):
    """'확인 필요'·출처 표시만 있고 실제 내용이 없는 답변인지"""
    core = re.sub(r"\[\d+\]|\(보고 내용\)|\(근거와 다름, 확인 필요\)|확인\s*필요(합니다|함)?|[\s.。,]", "", answer or "")
    return len(core) < 4


def fill_bare_answers(questions, answers, points, point_vectors, embed):
    """'확인 필요'만 남은 답변 → 질문과 가장 가까운 보고 내용으로 채운다 (하네스 폴백).
    '확인 필요.'만으로는 보고자가 무엇을 알고 있는지조차 안 보여서, 보고 기준 현재 상태를 함께 적는다."""
    bare = [i for i, a in enumerate(answers) if is_bare_answer(a)]
    if not bare or not points or not point_vectors:
        return answers
    try:
        vectors = embed([questions[i] for i in bare]) or []
    except Exception as error:
        print(f"Warning: bare answer fallback skipped: {error}")
        vectors = []
    filled = list(answers)
    for i, vector in zip(bare, vectors):
        best = max(range(len(points)), key=lambda k: _cosine(vector, point_vectors[k]))
        filled[i] = f"보고 기준: {points[best]} — 질문하신 부분은 확인 필요합니다. (보고 내용)"
    return filled


def mark_unsupported(answer):
    """근거 번호가 없는 답변 — '확인 필요'·'(보고 내용)' 표시가 없으면 '(확인 필요)'를 붙인다.
    '확인 필요'인 답에 붙은 '(보고 내용)'은 뜻이 없어 지운다 ('확인 필요 (보고 내용)' → '확인 필요')."""
    if "확인 필요" in answer:
        return re.sub(r"\s*\(보고 내용\)", "", answer).strip()
    if "보고 내용" in answer:
        return answer
    return answer + " (확인 필요)"


def parse_qa(text, evidence_count, past_count=0, limit=QUESTION_COUNT):
    """LLM 출력 → [(질문, 답변, [근거 번호], [과거 대화 번호])]. 하네스 검증:
    - Q 다음에 A가 없는 질문은 버림
    - 없는 번호는 지움. 과거 대화 [P#]는 질문에만 — 답변의 사실 근거로 쓰지 못하게 답변에서는 삭제
    - 인용도 '확인 필요'도 '(보고 내용)'도 없는 답변 → '(확인 필요)'를 붙여 근거 없음을 드러냄"""
    pairs, question, past = [], None, []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if re.match(r"^Q\d*\s*[:.]", line):
            question, past = _take_refs(re.sub(r"^Q\d*\s*[:.]\s*", "", line), r"\[P(\d+)\]", past_count)
            question = re.sub(r"\s*\[\d+\]", "", question).strip()
        elif re.match(r"^A\d*\s*[:.]", line) and question:
            answer = re.sub(r"\s*\[P\d+\]", "", re.sub(r"^A\d*\s*[:.]\s*", "", line))
            for n in set(int(m) for m in re.findall(r"\[(\d+)\]", answer)):
                if not 1 <= n <= evidence_count:
                    answer = answer.replace(f"[{n}]", "")
            answer, refs = _take_refs(answer, r"\[(\d+)\]", evidence_count)
            if refs:
                answer += " " + "".join(f"[{n}]" for n in refs)
            else:
                answer = mark_unsupported(answer)
            pairs.append((question, answer, refs, past))
            question, past = None, []
        if len(pairs) >= limit:
            break
    return pairs


class ExpectedQuestions:
    def __init__(self, generator, config_path=None):
        from weekly_report.collectors.teams import load_teams_settings

        self.gen = generator
        self.rag = TopicQueryRAG(generator, config_path)
        self.questioners = [n for n in load_teams_settings().get("expected_questioners", []) if n.strip()]

    @property
    def enabled(self):
        return self.rag.enabled and bool(self.questioners)

    # ---------- ① 수집 ----------

    def questioner_messages(self, name, history):
        """history(Teams 활동)에서 name이 보낸 업무 메시지 + 같은 방 직전 대화.
        반환: [{"activity", "text", "when", "context": [str]}] 시간순"""
        by_chat = {}
        for a in history:
            if a.get("source") != "teams" or a.get("action") != "message":
                continue
            d = _details(a)
            when = to_local_datetime(a.get("timestamp"), "teams")
            if when and d.get("text"):
                by_chat.setdefault(d.get("chat_id") or d.get("chat"), []).append((when, d, a))
        found = []
        for msgs in by_chat.values():
            msgs.sort(key=lambda m: m[0])
            for i, (when, d, a) in enumerate(msgs):
                sender = d.get("sender") or ""
                if name not in sender or (self.rag.me_name and sender == self.rag.me_name):
                    continue
                if not is_meaningful(d["text"]):
                    continue
                context = [f"{short_name(pd.get('sender'))}: {clean_text(pd.get('text'), 120)}"
                           for pw, pd, _ in msgs[max(0, i - CONTEXT_BEFORE):i]
                           if when - pw <= CONTEXT_WINDOW and pd.get("text")]
                found.append({"activity": a, "text": condense(d["text"]), "when": when, "context": context})
        found.sort(key=lambda m: m["when"])
        return found

    # ---------- ② 성향 ----------

    def style_profile(self, name, messages):
        """{"style": [str], "examples": [str]} — 마지막 메시지가 그대로면 캐시 재사용."""
        questions = [m for m in messages if is_question(m["text"])][-STYLE_SAMPLE:]
        if not questions:
            return {"style": [], "examples": []}
        marker = f"{STYLE_VERSION}|{len(questions)}|{questions[-1]['when'].isoformat()}"
        try:
            with open(STYLE_CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}
        if cache.get(name, {}).get("marker") == marker:
            return cache[name]["profile"]

        body = "\n".join(f"[{i}] {m['text']}" for i, m in enumerate(questions, start=1))
        output = self.rag.llm.complete(STYLE_PROMPT, body, max_tokens=500, max_input=6000, temperature=0) or ""
        style = [l.strip()[2:].strip() for l in output.splitlines() if l.strip().startswith("- ")][:4]
        picked = [int(n) for n in re.findall(r"\[(\d+)\]", output.split("대표")[-1])] if "대표" in output else []
        examples = [questions[n - 1]["text"] for n in dict.fromkeys(picked) if 1 <= n <= len(questions)][:3]
        if not examples:  # 번호를 못 받으면 최근 질문 중 긴 것
            examples = sorted((m["text"] for m in questions[-10:]), key=len, reverse=True)[:3]
        profile = {"style": style, "examples": examples}
        if style:  # 분석 실패는 캐시하지 않고 다음에 다시 시도
            cache[name] = {"marker": marker, "profile": profile}
            os.makedirs(os.path.dirname(STYLE_CACHE_FILE), exist_ok=True)
            with open(STYLE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
        return profile

    # ---------- ③ 맥락 + ④ 생성 ----------

    def build_sections(self, week_activities, week_start, week_end, report_points):
        """예상질문자별 [{"name", "style", "examples", "qa": [{"q", "a", "past"}],
        "past": [{"n", "when", "chat", "text"}], "evidence": [{"n", "label"}]}]"""
        points = [clean_text(p, None) for p in report_points if p and p.strip()][:MAX_POINTS]
        if not self.enabled or not points:
            return []
        end = datetime.strptime(week_end, "%Y-%m-%d")
        history_from = (end - timedelta(weeks=HISTORY_WEEKS)).strftime("%Y-%m-%d")
        history = self.gen.fetch_week_activities(history_from, week_end)

        key = ActivityDatabase.activity_key
        week_pool = {key(a): a for a in week_activities if self.rag.eligible(a)}
        if self.rag.clusterer.embed_activities(week_activities) is None:
            return []
        point_vectors = self.rag.clusterer.embed(points)
        if not point_vectors:
            return []
        week_hits = self.rag.retrieve(point_vectors, week_start, week_end, week_pool, WEEK_PER_POINT)
        # 2단계 검색용 — 질문이 정해진 뒤 질문 자체로 이번 주 근거를 다시 찾는다
        self.question_search = lambda vectors: self.rag.retrieve(
            vectors, week_start, week_end, week_pool, QUESTION_EVIDENCE_K, min_score=QUESTION_EVIDENCE_MIN)

        sections = []
        for name in self.questioners:
            messages = self.questioner_messages(name, history)
            if not messages:
                continue
            section = self._build_one(name, messages, points, point_vectors, week_hits, week_start)
            if section:
                sections.append(section)
        return sections

    def _past_matches(self, messages, point_vectors):
        """보고 항목마다 그 사람의 과거 메시지 중 의미가 가까운 것 (이번 주 보고와 이어지는 대화).
        반환: [(message, vector)] 시간순"""
        vectors = self.rag.clusterer.embed_activities([m["activity"] for m in messages])
        if not vectors:
            return []
        cosine = self.rag.clusterer._cosine
        picked = {}
        for pv in point_vectors:
            scored = sorted(((cosine(pv, v), i) for i, v in enumerate(vectors) if v), reverse=True)
            for score, i in scored[:PAST_PER_POINT]:
                if score >= PAST_MIN_SCORE:
                    picked[i] = max(score, picked.get(i, 0))
        return [(messages[i], vectors[i]) for i in sorted(picked, key=lambda i: messages[i]["when"])]

    def _verify_past_links(self, pairs, past):
        """생성 단계가 단 [P#] 연결을 별도 LLM 호출로 판정(LLM-as-judge) — 같은 이슈가 아니면 연결을 끊는다.
        짧은 채팅 문장은 임베딩 점수가 단어 겹침('DB' 등)에 흔들려서 판정은 LLM에 맡긴다.
        판정 실패 시에는 보수적으로 모든 연결을 끊는다."""
        links = [(i, n) for i, (_, _, _, refs) in enumerate(pairs) for n in refs]
        if not links:
            return pairs
        body = "\n".join(f"{k}. 질문: {pairs[i][0]}\n   과거 발언: {past[n - 1]['text']}"
                         for k, (i, n) in enumerate(links, start=1))
        output = self.rag.judge_llm.complete(LINK_JUDGE_PROMPT, body, max_tokens=200, temperature=0, cache=True) or ""
        verdict = {int(k): v.upper() == "Y" for k, v in re.findall(r"(\d+)\s*[:.]\s*([YNyn])", output)}
        keep = {(i, n) for k, (i, n) in enumerate(links, start=1) if verdict.get(k)}
        return [(q, a, refs, [n for n in past_refs if (i, n) in keep])
                for i, (q, a, refs, past_refs) in enumerate(pairs)]

    def _add_question_evidence(self, points, point_vectors, point_has_evidence, pairs, evidence):
        """2단계 검색: 근거는 보고 항목별로 찾아 두는데, 질문은 그 항목의 세부(예: 권역 프리픽스)를 묻기도 해서
        가장 맞는 근거가 빠지는 경우가 있다. 질문으로 근거를 다시 찾아, 가장 맞는 근거를 그 답변이 인용하지
        않았으면 해당 질문만 (기존 인용 근거 + 질문 근거)로 답변을 다시 쓴다.
        단, 질문이 가리키는 보고 항목(가장 가까운 항목)에 근거가 하나도 없으면(예: 근거에서 일부러 뺀 이 프로그램 개발)
        단어만 비슷한 남의 업무 기록이 붙기 쉬워서, 근거를 인용한 답변은 보고 내용만으로 다시 쓴다.
        반환: (pairs, evidence) — evidence는 늘어날 수 있음"""
        search = getattr(self, "question_search", None)
        if not pairs:
            return pairs, evidence
        key = ActivityDatabase.activity_key
        try:
            question_vectors = self.rag.clusterer.embed([q for q, _, _, _ in pairs]) or []
            hits = search(question_vectors) if search else [[] for _ in pairs]
        except Exception as error:
            print(f"Warning: question evidence search skipped: {error}")
            return pairs, evidence
        if len(question_vectors) != len(pairs):
            return pairs, evidence
        evidence = list(evidence)
        index = {key(e["activity"]): i for i, e in enumerate(evidence, start=1)}
        targets = {}  # 질문 순번(1부터) → 그 질문에 줄 근거 번호 ([]면 보고 내용만으로)
        for qi, ((_, _, refs, _), qv, qhits) in enumerate(zip(pairs, question_vectors, hits), start=1):
            nearest = max(range(len(points)), key=lambda k: _cosine(qv, point_vectors[k])) if points else None
            if nearest is not None and not point_has_evidence[nearest]:
                if refs:
                    targets[qi] = []
                continue
            numbers = []
            for _, a in qhits:
                k = key(a)
                if k not in index:
                    when = to_local_datetime(a.get("timestamp"), a.get("source"))
                    if not when:
                        continue
                    evidence.append({"label": evidence_label(a, when), "activity": a,
                                     "text": evidence_full_text(a)})
                    index[k] = len(evidence)
                numbers.append(index[k])
            if numbers and numbers[0] not in refs:  # 가장 맞는 근거를 인용하지 않은 답변만
                targets[qi] = list(dict.fromkeys(refs + numbers))
        if not targets:
            return pairs, evidence
        body = "<report>\n" + "\n".join(f"- {p}" for p in points) + "\n</report>\n\n" + "\n\n".join(
            f"Q{qi}: {pairs[qi - 1][0]}\n근거:\n" + ("\n".join(
                f"[{n}] {evidence[n - 1]['label']} | {evidence[n - 1]['text']}" for n in numbers)
                or "(없음 — 근거 기록이 없는 보고 항목이므로 <report> 내용으로만 답하고 끝에 (보고 내용))")
            for qi, numbers in targets.items())
        output = self.rag.llm.complete(REANSWER_PROMPT, body, max_tokens=2000, max_input=60000, temperature=0)
        redone = parse_reanswers(output, {qi: set(numbers) for qi, numbers in targets.items()})
        return [(q, *redone[qi], prefs) if qi in redone else (q, a, refs, prefs)
                for qi, (q, a, refs, prefs) in enumerate(pairs, start=1)], evidence

    def _finalize_answers(self, points, point_vectors, point_has_evidence, pairs, evidence):
        """답변 후처리 하네스 (예상 질문 생성·정답셋 평가 공통): 2단계 근거 보강·재답변 → 근거 관련성 검사 →
        사실 대조(표시만) → '확인 필요'만 남은 답변 폴백. 반환: (pairs, evidence)"""
        pairs, evidence = self._add_question_evidence(points, point_vectors, point_has_evidence, pairs, evidence)
        # 답변 내용과 무관한 근거 번호는 지우고, 남은 근거가 없으면 '(확인 필요)' 표시 (rag와 같은 하네스)
        checked = check_citations([(a, refs) for _, a, refs, _ in pairs],
                                  self.rag.evidence_vectors(evidence), self.rag.clusterer.embed,
                                  evidence_texts=self.rag.evidence_texts(evidence))
        pairs = [(q, a2 if refs2 else mark_unsupported(a2), refs2, prefs)
                 for (q, _, _, prefs), (a2, refs2) in zip(pairs, checked)]
        # 근거 문서는 맞는데 그 안의 사실을 틀리게 말한 답변(예: '정산용' 구분자를 '운임 계산용'으로) — 표시만
        answers = fact_check_answers(
            [(a, refs) for _, a, refs, _ in pairs], self.rag.evidence_texts(evidence),
            # 판정마다 짧은 이유를 쓰므로 답변 5개 기준으로 넉넉히
            lambda system, body: self.rag.judge_llm.complete(system, body, max_tokens=600, max_input=40000,
                                                       temperature=0, cache=True))
        answers = fill_bare_answers([q for q, _, _, _ in pairs], answers, points, point_vectors,
                                    self.rag.clusterer.embed)
        pairs = [(q, a2, refs if not is_bare_answer(a) else [], prefs)
                 for (q, a, refs, prefs), a2 in zip(pairs, answers)]
        return pairs, evidence

    def _evidence_from_hits(self, week_hits):
        """보고 항목별 검색 결과 → 근거 목록 (중복 제거, 순서 유지)"""
        evidence, seen = [], set()
        for hits in week_hits:
            for _, a in hits:
                k = ActivityDatabase.activity_key(a)
                when = to_local_datetime(a.get("timestamp"), a.get("source"))
                if k in seen or not when:
                    continue
                seen.add(k)
                evidence.append({"label": evidence_label(a, when), "activity": a,
                                 "text": evidence_full_text(a)})
        return evidence

    def answer_questions(self, questions, points, point_vectors, week_hits):
        """주어진 질문에 답한다 (정답셋 회귀 평가용) — 질문만 고정이고 근거 검색·답변 규칙·후처리는 예상 질문과 같다.
        반환: [{"q", "a", "evidence": [activity...]}] (답변이 인용한 근거)"""
        evidence = self._evidence_from_hits(week_hits)
        point_has_evidence = [bool(h) for h in week_hits]
        body = ("<report>\n" + "\n".join(f"- {p}" + ("" if ok else " (근거 기록 없음)")
                                         for p, ok in zip(points, point_has_evidence)) + "\n</report>\n<evidence>\n"
                + "\n".join(f"[{i}] {e['label']} | {e['text']}" for i, e in enumerate(evidence, start=1))
                + "\n</evidence>\n\n" + "\n".join(f"Q{i}: {q}" for i, q in enumerate(questions, start=1)))
        output = self.rag.llm.complete(FIXED_ANSWER_PROMPT, body, max_tokens=4000, max_input=80000, temperature=0)
        every = set(range(1, len(evidence) + 1))
        answered = parse_reanswers(output, {i: every for i in range(1, len(questions) + 1)})
        pairs = [(q, *answered.get(i, ("확인 필요", [])), []) for i, q in enumerate(questions, start=1)]
        pairs, evidence = self._finalize_answers(points, point_vectors, point_has_evidence, pairs, evidence)
        return [{"q": q, "a": a, "evidence": [evidence[n - 1]["activity"] for n in refs]} for q, a, refs, _ in pairs]

    def _build_one(self, name, messages, points, point_vectors, week_hits, week_start):
        profile = self.style_profile(name, messages)
        # 이번 주에 이미 한 질문은 '지난 대화'가 아니라 반복하지 말아야 할 질문
        start = datetime.strptime(week_start, "%Y-%m-%d")
        before = [m for m in messages if m["when"] < start]
        asked = [m for m in messages if m["when"] >= start and is_question(m["text"])]
        matches = self._past_matches(before, point_vectors) if before else []
        past = [m for m, _ in matches]

        # 이번 주 내 활동 = 답변의 사실 근거 [n]
        evidence = self._evidence_from_hits(week_hits)
        # 상사의 과거 발언 = 질문의 맥락 [P#] (사실 근거 아님)
        past_lines = []
        for i, m in enumerate(past, start=1):
            context = " / ".join(m["context"])
            past_lines.append(f"[P{i}] {m['when']:%m/%d} " + (f"(앞 대화: {context}) " if context else "")
                              + f"{name}: {m['text']}")

        point_has_evidence = [bool(h) for h in week_hits]
        body = (
            "<report>\n" + "\n".join(f"- {p}" + ("" if ok else " (근거 기록 없음)")
                                       for p, ok in zip(points, point_has_evidence)) + "\n</report>\n"
            "<past>\n" + ("\n".join(past_lines) or "(없음)") + "\n</past>\n"
            "<asked>\n" + ("\n".join(f"- {m['when']:%m/%d} {m['text']}" for m in asked[-15:]) or "(없음)")
            + "\n</asked>\n<evidence>\n"
            + "\n".join(f"[{i}] {e['label']} | {e['text']}" for i, e in enumerate(evidence, start=1))
            + "\n</evidence>"
        )
        system = QA_PROMPT.format(
            name=name, count=QUESTION_COUNT + CANDIDATE_EXTRA,
            style="\n".join(f"- {s}" for s in profile["style"]) or "- (분석 자료 부족)",
            examples="\n".join(f'- "{e}"' for e in profile["examples"]) or "- (없음)",
        )
        output = self.rag.llm.complete(system, body, max_tokens=3000, max_input=60000, temperature=0.3)
        pairs = parse_qa(output, len(evidence), len(past), limit=QUESTION_COUNT + CANDIDATE_EXTRA)
        # 이번 주에 이미 한 질문을 그대로 베낀 후보는 버림 (프롬프트로 막아도 종종 복사함)
        pairs = [p for p in pairs if not is_repeat(p[0], [m["text"] for m in asked])][:QUESTION_COUNT]
        if not pairs:
            return None
        pairs = self._verify_past_links(pairs, past)
        pairs, evidence = self._finalize_answers(points, point_vectors, point_has_evidence, pairs, evidence)

        # 인용된 근거만 1부터 다시 번호 매김 (같은 출처는 한 번호로) — rag와 같은 방식
        cited = sorted({n for _, _, refs, _ in pairs for n in refs})
        renum, sources = {}, []
        for n in cited:
            label = evidence[n - 1]["label"]
            if label not in sources:
                sources.append(label)
            renum[n] = sources.index(label) + 1
        past_cited = sorted({n for _, _, _, refs in pairs for n in refs})
        past_renum = {n: i for i, n in enumerate(past_cited, start=1)}

        def rewrite(text):
            def run(m):
                nums = sorted({renum.get(int(n), int(n)) for n in re.findall(r"\d+", m.group(0))})
                return "".join(f"[{n}]" for n in nums)
            return re.sub(r"(?:\[\d+\]\s*)+", lambda m: run(m) + (" " if m.group(0).endswith(" ") else ""), text).strip()

        return {
            "name": name,
            "style": profile["style"],
            "examples": profile["examples"],
            "qa": [{"q": q, "a": rewrite(a), "past": [f"P{past_renum[n]}" for n in refs]}
                   for q, a, _, refs in pairs],
            # 질문의 바탕이 된 상사의 실제 과거 발언 (사실 근거가 아니라 질문 맥락)
            "past": [{"n": f"P{past_renum[n]}", "when": f"{past[n - 1]['when']:%m/%d}",
                      "chat": clean_text(_details(past[n - 1]["activity"]).get("chat"), 200),
                      "text": past[n - 1]["text"]} for n in past_cited],
            "evidence": [{"n": i, "label": label} for i, label in enumerate(sources, start=1)],
        }
