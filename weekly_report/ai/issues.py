#!/usr/bin/env python3
"""
STEP 2 보강 — '주요 이슈 & 리스크' 표와 '다음 주 계획' (킥오프 발표 8쪽에서 약속한 섹션).

① 이번 주 근거 후보(RAG와 같은 근거 자격: 노이즈·IDE·이름뿐인 기록·단순 대답 제외)에서
   장애·이슈 질의와 일정·예정 질의로 각각 관련 기록을 찾고
② 번호 붙은 근거만 보고 LLM이 표 행·계획을 쓴다 — 상태는 기록에 적힌 것만(없으면 '확인 필요'),
   기한은 기록에 있을 때만, 기록에 없는 계획은 쓰지 않는다
③ 하네스: 인용 없는 줄은 버리고, 근거 관련성 검사로 무관한 번호를 지우고(남은 근거 없으면 버림),
   사실 대조(판정 모델)로 근거와 다른 행은 '(근거와 다름, 확인 필요)' 표시
"""

from __future__ import annotations

import re

from weekly_report.ai.rag import TopicQueryRAG, check_citations, evidence_full_text, evidence_label
from weekly_report.common.timeutil import to_local_datetime
from weekly_report.storage.database import ActivityDatabase

ISSUE_TYPES = ("장애", "이슈", "리스크")
MAX_ROWS = 5
TOP_K = 15  # 질의별 근거 후보 수
ISSUE_QUERY = "장애 오류 실패 에러 문제 이슈 리스크 지연 누락 원인 확인 긴급 조치 필요 회신 대기 미해결 재발"
PLAN_QUERY = "다음 주 예정 계획 일정 배포 예정 진행 예정 착수 완료 목표 마감 후속 조치 재확인 예정 익일"

ISSUE_PROMPT = (
    "너는 주간 업무 보고서 STEP 2의 '주요 이슈 & 리스크'와 '다음 주 계획'을 쓰는 비서야. "
    "<evidence> 안의 번호 붙은 실제 기록만 근거로 아래 두 부분을 써.\n"
    "[이슈·리스크]\n"
    "- 이번 주 발생한 장애·이슈와, 앞으로 문제가 될 수 있는 리스크를 중요한 것부터 최대 5개.\n"
    "- 한 줄에 하나씩 '구분 | 내용 | 상태 [번호]' 형식. 구분은 장애/이슈/리스크 중 하나 "
    "(장애=서비스·거래에 실제 영향이 난 것, 이슈=해결해야 할 문제, 리스크=아직 안 났지만 우려되는 것).\n"
    "- 내용은 무엇이 문제인지 구체적으로(시스템·대상·건수). 상태는 기록에 적힌 현재 상태"
    "(예: 'KIS 회신 대기', '원인 확인 중', '조치 완료'), 기록에 없으면 '확인 필요'.\n"
    "- 인사·단순 문의·교육 안내는 이슈가 아니다. 해당 없으면 '없음' 한 줄.\n"
    "[다음 주 계획]\n"
    "- 오늘은 {today}, 보고 주간은 {week_start}~{week_end}이다. 오늘 이전에 이미 지난 일정·끝난 작업은 계획이 아니다.\n"
    "- 기록에 실제로 적힌 앞으로의 일정·예정·후속 조치만 최대 5개, '- 계획 내용 (기한) [번호]' 형식. "
    "기한은 기록에 있을 때만 쓴다. 기록에 없는 계획을 지어내지 않는다. 해당 없으면 '없음' 한 줄.\n"
    "출력은 위 두 부분만, 다른 설명은 쓰지 마."
)


def plan_dates(text, year):
    """계획 문장 속 날짜('10/01', '10/1', '10월 1일') → [date]. 연도는 보고 주간 기준."""
    from datetime import date
    found = []
    for m in re.finditer(r"(?<![\d.])(\d{1,2})\s*(?:/|월\s*)(\d{1,2})(?:\s*일)?(?![\d/])", text or ""):
        try:
            found.append(date(year, int(m.group(1)), int(m.group(2))))
        except ValueError:
            continue
    return found


def drop_past_plans(plans, today):
    """날짜가 적힌 계획 중 모든 날짜가 오늘 이전이면 이미 지난 일정 → 버림 (날짜 없는 계획은 둔다)"""
    kept = []
    for plan in plans:
        dates = plan_dates(plan["text"], today.year)
        if dates and max(dates) < today:
            continue
        kept.append(plan)
    return kept


def parse_issue_output(text, evidence_count):
    """LLM 출력 → (issues, plans). 인용 번호가 없거나 범위를 벗어난 줄, 형식이 맞지 않는 줄은 버린다.
    issues: [{"type", "content", "status", "refs"}], plans: [{"text", "refs"}]"""
    issues, plans, mode = [], [], None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[이슈"):
            mode = "issue"
            continue
        if line.startswith("[다음 주"):
            mode = "plan"
            continue
        refs = [n for n in dict.fromkeys(int(m) for m in re.findall(r"\[(\d+)\]", line)) if 1 <= n <= evidence_count]
        body = re.sub(r"\s*\[\d+\]", "", line).strip().lstrip("-•* ").strip()
        if not refs or not body or body == "없음":
            continue
        if mode == "issue":
            parts = [p.strip() for p in body.split("|")]
            if len(parts) < 3 or parts[0] not in ISSUE_TYPES or not parts[1]:
                continue
            issues.append({"type": parts[0], "content": parts[1],
                           "status": " / ".join(p for p in parts[2:] if p) or "확인 필요", "refs": refs})
        elif mode == "plan":
            plans.append({"text": body, "refs": refs})
    return issues[:MAX_ROWS], plans[:MAX_ROWS]


class IssuesAndPlan:
    def __init__(self, generator, config_path=None):
        self.rag = TopicQueryRAG(generator, config_path)

    def build(self, week_activities, week_start, week_end, today=None):
        """{"issues": [...], "plans": [...], "evidence": [{"n", "label"}]} — 근거·LLM 없으면 None"""
        from datetime import date
        today = today or date.today()
        if not self.rag.enabled or not week_activities:
            return None
        key = ActivityDatabase.activity_key
        pool = {key(a): a for a in week_activities if self.rag.eligible(a)}
        if not pool or self.rag.clusterer.embed_activities(week_activities) is None:
            return None
        vectors = self.rag.clusterer.embed([ISSUE_QUERY, PLAN_QUERY])
        if not vectors:
            return None
        evidence, seen = [], set()
        for hits in self.rag.retrieve(vectors, week_start, week_end, pool, TOP_K):
            for _, a in hits:
                k = key(a)
                when = to_local_datetime(a.get("timestamp"), a.get("source"))
                if k in seen or not when:
                    continue
                seen.add(k)
                evidence.append({"label": evidence_label(a, when), "activity": a, "text": evidence_full_text(a)})
        if not evidence:
            return None
        body = "<evidence>\n" + "\n".join(f"[{i}] {e['label']} | {e['text']}"
                                          for i, e in enumerate(evidence, start=1)) + "\n</evidence>"
        prompt = ISSUE_PROMPT.format(today=today.isoformat(), week_start=week_start, week_end=week_end)
        output = self.rag.llm.complete(prompt, body, max_tokens=2000, max_input=60000, temperature=0, cache=True)
        issues, plans = parse_issue_output(output, len(evidence))
        plans = drop_past_plans(plans, today)  # 프롬프트로 막아도 지난 일정이 섞여 나옴
        if not issues and not plans:
            return None
        return self._verify(issues, plans, evidence)

    def _verify(self, issues, plans, evidence):
        from weekly_report.ai.questions import DIFF_MARK, fact_check_answers

        texts = self.rag.evidence_texts(evidence)
        rows = [(f"{i['content']} (상태: {i['status']})", i["refs"]) for i in issues] + [(p["text"], p["refs"]) for p in plans]
        checked = check_citations(rows, self.rag.evidence_vectors(evidence), self.rag.clusterer.embed,
                                  evidence_texts=texts)
        judged = fact_check_answers(
            [(text, refs) for text, refs in checked], texts,
            lambda system, body: self.rag.judge_llm.complete(system, body, max_tokens=800, max_input=40000,
                                                             temperature=0, cache=True))
        kept_issues, kept_plans = [], []
        for idx, ((_, refs), verdict) in enumerate(zip(checked, judged)):
            if not refs:
                continue  # 맞는 근거가 하나도 안 남은 줄은 근거 없는 주장으로 보고 버림
            differs = verdict.endswith(DIFF_MARK)
            if idx < len(issues):
                row = dict(issues[idx], refs=refs)
                if differs:  # '확인 필요 (근거와 다름, 확인 필요)'처럼 겹치지 않게
                    row["status"] = (DIFF_MARK.strip("()") if row["status"] == "확인 필요"
                                     else f"{row['status']} {DIFF_MARK}")
                kept_issues.append(row)
            else:
                plan = dict(plans[idx - len(issues)], refs=refs)
                if differs:
                    plan["text"] = f"{plan['text']} {DIFF_MARK}"
                kept_plans.append(plan)
        if not kept_issues and not kept_plans:
            return None
        # 인용된 근거만 1부터 다시 번호 (같은 출처 표시는 한 번호로)
        renum, sources = {}, []
        for n in sorted({n for row in kept_issues + kept_plans for n in row["refs"]}):
            label = evidence[n - 1]["label"]
            if label not in sources:
                sources.append(label)
            renum[n] = sources.index(label) + 1
        for row in kept_issues + kept_plans:
            row["refs"] = sorted({renum[n] for n in row["refs"]})
        return {"issues": kept_issues, "plans": kept_plans,
                "evidence": [{"n": i, "label": label} for i, label in enumerate(sources, start=1)]}
