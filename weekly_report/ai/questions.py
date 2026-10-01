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
from weekly_report.ai.rag import TopicQueryRAG, evidence_label
from weekly_report.common.timeutil import to_local_datetime
from weekly_report.report.sections import clean_text
from weekly_report.storage.database import ActivityDatabase

QUESTION_COUNT = 5
CANDIDATE_EXTRA = 3        # 반복 질문을 걸러낼 여유분만큼 더 생성
HISTORY_WEEKS = 8          # 질문 성향·과거 대화를 찾는 기간
CONTEXT_BEFORE = 3         # 질문 앞에 붙일 같은 방 직전 메시지 수
CONTEXT_WINDOW = timedelta(hours=3)
PAST_PER_POINT = 2         # 보고 항목 하나당 그 사람의 비슷한 과거 메시지 수
WEEK_PER_POINT = 3         # 보고 항목 하나당 이번 주 내 활동 근거 수
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
QA_PROMPT = (
    "너는 주간 업무 보고를 준비하는 담당자의 비서야. 상사 '{name}'이(가) 이번 주 보고를 듣고 "
    "물어볼 만한 질문 {count}개와 답변 초안을 만들어.\n"
    "[상사의 질문 성향]\n{style}\n[상사의 실제 말투 예시]\n{examples}\n\n"
    "규칙:\n"
    "- 질문은 <report>의 이번 주 보고 내용에 대한 것이어야 하고, 상사의 말투(반말·짧은 구어체 등)를 그대로 따른다. "
    "<past>에 이번 주 보고와 같은 주제의 과거 발언이 있으면 "
    "질문 1~2개는 그 발언과 연결해서 묻고 질문 끝에 [P2]처럼 그 번호를 단다 (주제가 다르면 연결하지 않는다).\n"
    "- <asked>는 상사가 이번 주에 이미 한 질문이다. 같은 질문을 반복하지 말고, 필요하면 그 결과나 후속 조치를 묻는다.\n"
    "- 답변은 보고체로 1~2문장, 간결하게(예: '~완료, ~예정'). <evidence>의 이번 주 근거만 사용하고 끝에 근거 번호를 "
    "[1][3]처럼 단다. <past>는 상사의 과거 발언일 뿐 사실 근거가 아니므로 답변에 쓰지 않는다.\n"
    "- 근거로 확인되지 않는 사실(원인·일정·수치 등)은 지어내지 말고 '확인 필요'라고 쓴다.\n"
    "- 출력 형식은 질문마다 정확히 두 줄:\nQ: 질문 [P번호(있을 때만)]\nA: 답변 [번호]\n"
    "- 그 외 서론·설명은 쓰지 마."
)


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


def parse_qa(text, evidence_count, past_count=0, limit=QUESTION_COUNT):
    """LLM 출력 → [(질문, 답변, [근거 번호], [과거 대화 번호])]. 하네스 검증:
    - Q 다음에 A가 없는 질문은 버림
    - 없는 번호는 지움. 과거 대화 [P#]는 질문에만 — 답변의 사실 근거로 쓰지 못하게 답변에서는 삭제
    - 인용도 '확인 필요'도 없는 답변 → '(확인 필요)'를 붙여 근거 없음을 드러냄"""
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
            elif "확인 필요" not in answer:
                answer += " (확인 필요)"
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
                found.append({"activity": a, "text": clean_text(d["text"], 200), "when": when, "context": context})
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
        points = [clean_text(p, 200) for p in report_points if p and p.strip()][:MAX_POINTS]
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
        output = self.rag.llm.complete(LINK_JUDGE_PROMPT, body, max_tokens=200, temperature=0, cache=True) or ""
        verdict = {int(k): v.upper() == "Y" for k, v in re.findall(r"(\d+)\s*[:.]\s*([YNyn])", output)}
        keep = {(i, n) for k, (i, n) in enumerate(links, start=1) if verdict.get(k)}
        return [(q, a, refs, [n for n in past_refs if (i, n) in keep])
                for i, (q, a, refs, past_refs) in enumerate(pairs)]

    def _build_one(self, name, messages, points, point_vectors, week_hits, week_start):
        profile = self.style_profile(name, messages)
        # 이번 주에 이미 한 질문은 '지난 대화'가 아니라 반복하지 말아야 할 질문
        start = datetime.strptime(week_start, "%Y-%m-%d")
        before = [m for m in messages if m["when"] < start]
        asked = [m for m in messages if m["when"] >= start and is_question(m["text"])]
        matches = self._past_matches(before, point_vectors) if before else []
        past = [m for m, _ in matches]

        # 이번 주 내 활동 = 답변의 사실 근거 [n]
        evidence, seen = [], set()
        for hits in week_hits:
            for _, a in hits:
                k = ActivityDatabase.activity_key(a)
                when = to_local_datetime(a.get("timestamp"), a.get("source"))
                if k in seen or not when:
                    continue
                seen.add(k)
                evidence.append({"label": evidence_label(a, when),
                                 "text": clean_text(self.rag.clusterer._activity_text(a), 300)})
        # 상사의 과거 발언 = 질문의 맥락 [P#] (사실 근거 아님)
        past_lines = []
        for i, m in enumerate(past, start=1):
            context = " / ".join(m["context"])
            past_lines.append(f"[P{i}] {m['when']:%m/%d} " + (f"(앞 대화: {context}) " if context else "")
                              + f"{name}: {m['text']}")

        body = (
            "<report>\n" + "\n".join(f"- {p}" for p in points) + "\n</report>\n"
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
        output = self.rag.llm.complete(system, body, max_tokens=2200, max_input=12000, temperature=0.3)
        pairs = parse_qa(output, len(evidence), len(past), limit=QUESTION_COUNT + CANDIDATE_EXTRA)
        # 이번 주에 이미 한 질문을 그대로 베낀 후보는 버림 (프롬프트로 막아도 종종 복사함)
        pairs = [p for p in pairs if not is_repeat(p[0], [m["text"] for m in asked])][:QUESTION_COUNT]
        if not pairs:
            return None
        pairs = self._verify_past_links(pairs, past)

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
                      "chat": clean_text(_details(past[n - 1]["activity"]).get("chat"), 30),
                      "text": past[n - 1]["text"]} for n in past_cited],
            "evidence": [{"n": i, "label": label} for i, label in enumerate(sources, start=1)],
        }
