#!/usr/bin/env python3
"""
나만의 비서 — 09:00 오늘 할 일 추출 (5-2).

① 기간: 전 근무일 0시 ~ 오늘 09시 (월요일이면 금요일·주말 포함, 공휴일은 report_settings의 holidays)
② 재료: 수신·그룹 주소 메일, 내가 보낸 메일, Teams 그룹(나를 @언급·내 이름을 부름·내가 보낸 메시지 + 앞 대화),
        1:1 대화(collect_direct_messages — DB에 저장하지 않고 할 일 근거로만), 오늘·내일 일정(LLM 없이 바로)
③ 판정 모델이 '오늘|내일 | 종류 | 할 일 | 요청자 | 기한 | 우선순위 [번호]'로 추출 → 하네스: 인용 검사,
   근거 관련성 검사, 이월 항목과 중복 제거, 지난 기한은 '기한 지남' 표시
④ 어제 목록의 미완료는 이월, 결과는 TodoStore(DB)에 저장하고 md로 내보냄
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, time, timedelta

from weekly_report import paths
from weekly_report.ai.rag import _cosine, check_citations, evidence_full_text, evidence_label, is_trivial_reply
from weekly_report.common.timeutil import to_local_datetime
from weekly_report.report.sections import clean_text
from weekly_report.storage.todos import TodoStore

WORK_START = time(9, 0)
MAX_TODOS = 12
CONTEXT_BEFORE = 2            # 나를 부른 그룹 메시지 앞 대화 몇 개를 같이 줄지
DUPLICATE_SCORE = 0.85        # 이월 항목과 이 이상 비슷하면 같은 일로 보고 새로 넣지 않음
WEEKDAYS = "월화수목금토일"
TODO_DIR = os.path.join(paths.DATA_DIR, "todos")

TODO_PROMPT = (
    "너는 직장인의 아침 업무 비서야. <evidence>는 {window} 동안 나({me})에게 온 메일·메시지와 내가 보낸 메시지야. "
    "오늘({today})과 내일({tomorrow}) 내가 처리해야 할 일을 뽑아.\n"
    "- 할 일: 나에게 직접 온 요청(수신 메일·1:1·@언급·내 이름을 부른 요청), 내가 하겠다고 한 일"
    "('확인해보겠습니다', '~까지 드리겠습니다'), 나도 받은 공지 중 회신·조치가 필요한 것.\n"
    "- 할 일이 아닌 것: 단순 공유·안내·참고, 다른 사람에게 한 요청, 이미 끝났다고 말한 일, 인사·잡담, 광고·교육 홍보 메일.\n"
    "- 한 줄에 하나: '오늘|내일 | 요청|내 약속 | 할 일 | 요청자 | 기한 | 높음|보통 [번호]'\n"
    "  할 일은 무엇을 하면 되는지 구체적으로(대상·건 포함, '~회신', '~확인'처럼 동사로 끝나게). "
    "요청자는 사람 이름(내 약속이면 '나'). 기한은 근거에 날짜·시각이 있을 때만(예: 10/06, 오늘 15시), 없으면 '-'.\n"
    "  기한이 오늘·이미 지남·없음이면 '오늘', 내일이면 '내일', 그 뒤 날짜면 '오늘'에 넣고 기한을 적는다. "
    "높음: 기한이 오늘·내일이거나 장애·고객 영향·상사 요청.\n"
    "- 같은 일은 한 줄로, 최대 {max_items}개. 해당 없으면 '없음' 한 줄. 다른 설명은 쓰지 마."
)


# ---------------------------------------------------------------- 근무일

def is_workday(day, holidays=()):
    return day.weekday() < 5 and day.isoformat() not in set(holidays)


def previous_workday(day, holidays=()):
    day -= timedelta(days=1)
    while not is_workday(day, holidays):
        day -= timedelta(days=1)
    return day


def collection_window(today, holidays=()):
    """(시작, 끝) 로컬 datetime — 전 근무일 0시 ~ 오늘 09시 (월요일이면 금요일 0시부터 → 주말 포함)"""
    return datetime.combine(previous_workday(today, holidays), time(0, 0)), datetime.combine(today, WORK_START)


# ---------------------------------------------------------------- 출력 파싱

def parse_todo_output(text, evidence_count):
    """'오늘|내일 | 종류 | 할 일 | 요청자 | 기한 | 우선순위 [번호]' → 항목 목록. 형식·인용이 맞지 않는 줄은 버린다."""
    items = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-•* ").strip()
        refs = [n for n in dict.fromkeys(int(m) for m in re.findall(r"\[(\d+)\]", line)) if 1 <= n <= evidence_count]
        body = re.sub(r"\s*\[\d+\]", "", line).strip()
        parts = [p.strip() for p in body.split("|")]
        if not refs or len(parts) < 6 or parts[0] not in ("오늘", "내일") or parts[1] not in ("요청", "내 약속"):
            continue
        task = parts[2]
        if not task or is_trivial_reply(task):
            continue
        priority = parts[5] if parts[5] in ("높음", "보통") else "보통"
        items.append({"bucket": "today" if parts[0] == "오늘" else "tomorrow", "kind": parts[1], "task": task,
                      "requester": parts[3] if parts[3] not in ("-", "") else None,
                      "due": parts[4] if parts[4] not in ("-", "") else None, "priority": priority, "refs": refs})
    return items[:MAX_TODOS]


def mark_overdue(items, today):
    """기한이 오늘 이전 날짜면 '기한 지남'으로 표시 (요청은 지워지지 않는다)"""
    from weekly_report.ai.issues import plan_dates
    for item in items:
        dates = plan_dates(item.get("due") or "", today.year)
        if dates and max(dates) < today:
            item["due"] = f"{item['due']} (기한 지남)"
            item["priority"] = "높음"
            item["bucket"] = "today"
    return items


# ---------------------------------------------------------------- 추출

class DailyTodos:
    def __init__(self, generator=None, store=None, teams=None, config_path=None):
        from weekly_report.ai.rag import TopicQueryRAG, load_report_settings
        from weekly_report.report.generator import ReportGenerator

        self.gen = generator or ReportGenerator()
        self.rag = TopicQueryRAG(self.gen, config_path)
        self.store = store or TodoStore()
        self.teams = teams
        self.holidays = load_report_settings().get("holidays", [])
        _, self.me_name = self.gen._teams_context()

    # ----- 재료 -----

    def _short_names(self):
        """내 이름 부르기 감지용 ('손현태(이마트24 POS서버) - …' → '손현태', '현태')"""
        full = (self.me_name or "").split("(")[0].split(" - ")[0].strip()
        return [n for n in {full, full[1:] if len(full) == 3 else ""} if len(n) >= 2]

    def _candidates(self, start, end):
        """기간 안의 할 일 재료 활동 목록 (시간순)"""
        acts = self.gen.fetch_week_activities(start.date().isoformat(), end.date().isoformat())
        names = self._short_names()
        picked, by_chat = [], {}
        for a in acts:
            when = to_local_datetime(a.get("timestamp"), a.get("source"))
            if not when or not (start <= when.replace(tzinfo=None) < end):
                continue
            d = _details(a)
            if a.get("source") == "outlook" and a.get("action") == "email_received":
                if d.get("recipient_type", "to") != "cc":  # 수신 위치를 모르는 예전 기록은 수신으로
                    picked.append(a)
            elif a.get("source") == "outlook" and a.get("action") == "email_sent":
                picked.append(a)
            elif a.get("source") == "teams" and a.get("action") == "message":
                by_chat.setdefault(d.get("chat_id") or d.get("chat"), []).append((when, a))
        for msgs in by_chat.values():
            msgs.sort(key=lambda m: m[0])
            for i, (_, a) in enumerate(msgs):
                d = _details(a)
                text = d.get("text") or ""
                if d.get("mentions_me") or d.get("mentions_all") or d.get("from_me") or any(n in text for n in names):
                    picked.extend(m[1] for m in msgs[max(0, i - CONTEXT_BEFORE):i + 1])
        try:
            from weekly_report.collectors.teams import TeamsCollector
            picked += (self.teams or TeamsCollector()).collect_direct_messages(start, end)
        except Exception as error:
            print(f"Warning: 1:1 messages unavailable: {error}")
        unique, seen = [], set()
        for a in picked:
            k = (a.get("timestamp"), a.get("action"), a.get("file_path"), a.get("source"))
            if k not in seen and not is_trivial_reply(_details(a).get("text") or "x" * 10):
                seen.add(k)
                unique.append(a)
        return sorted(unique, key=lambda a: str(to_local_datetime(a.get("timestamp"), a.get("source")) or ""))

    def _schedule_items(self, today):
        """오늘·내일 회의 → 일정 항목 (LLM 없이)"""
        tomorrow = today + timedelta(days=1)
        acts = self.gen.fetch_week_activities(today.isoformat(), tomorrow.isoformat())
        items, seen = [], set()
        for a in acts:
            if a.get("action") != "meeting":
                continue
            when = to_local_datetime(a.get("timestamp"), a.get("source"))
            if not when or when.date() not in (today, tomorrow):
                continue
            d = _details(a)
            subject = clean_text(d.get("subject") or str(a.get("file_path") or "").split(":", 1)[-1])
            key = (when.date(), when.strftime("%H:%M"), subject)
            if key in seen:
                continue
            seen.add(key)
            organizer = d.get("organizer")
            items.append({"bucket": "today" if when.date() == today else "tomorrow", "kind": "일정",
                          "task": f"{when:%H:%M} {subject}", "due": f"{when:%H:%M}", "priority": "일정",
                          "requester": organizer,
                          "source_label": " · ".join(x for x in ("Teams 일정" if a.get("source") == "teams" else "Outlook 일정",
                                                                  f"주최 {organizer}" if organizer else "") if x),
                          "evidence": []})
        return sorted(items, key=lambda i: (i["bucket"] != "today", i["task"]))

    # ----- 생성 -----

    def generate(self, today=None, force=False):
        """오늘 목록 생성 → TodoStore. 이미 있으면 그대로(force면 사용자가 손대지 않은 항목만 다시 추출).
        반환: 그 날짜 목록"""
        today = today or date.today()
        key = today.isoformat()
        # '항목이 있나'가 아니라 '추출했나'로 — 전날 17:00 '내일로 이월 확정'으로 이월 항목이 먼저 들어와 있을 수 있음
        if self.store.has_run(key, "am") and not force:
            return self.store.list_for(key)
        if force:
            self.store.delete_untouched(key)
        previous = self.store.latest_list_before(key)
        if previous:
            self.store.carry_over(previous, key)
        existing = self.store.list_for(key, include_removed=True)
        start, end = collection_window(today, self.holidays)
        extracted = self._extract(today, start, end)
        fresh = self._drop_duplicates(extracted, existing)
        schedules = [s for s in self._schedule_items(today) if s["task"] not in {e["task"] for e in existing}]
        self.store.add_items(key, schedules + fresh)
        self.store.mark_run(key, "am")
        items = self.store.list_for(key)
        export_markdown(key, items, start, end)
        return items

    def _extract(self, today, start, end):
        candidates = self._candidates(start, end)
        if not candidates or not self.rag.enabled:
            return []
        evidence = []
        for a in candidates:
            when = to_local_datetime(a.get("timestamp"), a.get("source"))
            d = _details(a)
            tag = ("나 → " if d.get("from_me") or a.get("action") == "email_sent" else "") + (
                "[1:1] " if d.get("chat_type") == "oneOnOne" else "[@나] " if d.get("mentions_me") else
                "[메일 수신] " if d.get("recipient_type") == "to" else "")
            if a.get("action") == "email_received" and (d.get("sender_name") or d.get("sender")):
                tag += f"보낸 사람 {d.get('sender_name') or d.get('sender')} · "  # 요청자 판단 재료
            evidence.append({"label": evidence_label(a, when), "activity": a,
                             "text": f"{when:%m/%d %H:%M} {tag}{evidence_full_text(a)}"})
        body = "<evidence>\n" + "\n".join(f"[{i}] {e['text']}" for i, e in enumerate(evidence, start=1)) + "\n</evidence>"
        tomorrow = today + timedelta(days=1)
        prompt = TODO_PROMPT.format(
            window=f"{start:%m/%d %H:%M}~{end:%m/%d %H:%M}", me=self.me_name or "나",
            today=f"{today:%m/%d}({WEEKDAYS[today.weekday()]})", tomorrow=f"{tomorrow:%m/%d}({WEEKDAYS[tomorrow.weekday()]})",
            max_items=MAX_TODOS)
        output = self.rag.judge_llm.complete(prompt, body, max_tokens=2500, max_input=80000, temperature=0)
        items = parse_todo_output(output, len(evidence))
        # 근거 관련성 검사 (할 일 문장 ↔ 인용 근거) — 맞는 근거가 하나도 안 남으면 버림
        checked = check_citations([(i["task"], i["refs"]) for i in items], self.rag.evidence_vectors(evidence),
                                  self.rag.clusterer.embed, evidence_texts=self.rag.evidence_texts(evidence))
        kept = []
        for item, (_, refs) in zip(items, checked):
            if not refs:
                continue
            first = evidence[refs[0] - 1]
            item["source_label"] = " · ".join(x for x in (f"요청 {item['requester']}" if item.get("requester")
                                                          and item["requester"] != "나" else "", first["label"]) if x)
            item["evidence"] = [{"label": evidence[n - 1]["label"], "text": clean_text(evidence[n - 1]["text"], 600)}
                                for n in refs]
            kept.append(item)
        return mark_overdue(kept, today)

    def _drop_duplicates(self, items, existing):
        """이월·이미 있는 항목과 같은 일이면 새로 넣지 않음 (할 일 문장 임베딩 유사도)"""
        if not items or not existing:
            return items
        try:
            vectors = self.rag.clusterer.embed([i["task"] for i in items] + [e["task"] for e in existing])
        except Exception:
            return items
        if not vectors:
            return items
        new_vecs, old_vecs = vectors[:len(items)], vectors[len(items):]
        return [i for i, v in zip(items, new_vecs) if all(_cosine(v, o) < DUPLICATE_SCORE for o in old_vecs)]


def _details(activity):
    d = activity.get("details")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except (TypeError, ValueError):
            d = {}
    return d if isinstance(d, dict) else {}


# ---------------------------------------------------------------- md 기록

STATUS_MARK = {"open": "[ ]", "in_progress": "[~]", "done": "[x]", "removed": "[-]"}


def export_markdown(list_date, items, start=None, end=None, out_dir=TODO_DIR):
    """그날 목록 → data/todos/YYYY-MM-DD.md (DB가 기준, md는 내보내기)"""
    os.makedirs(out_dir, exist_ok=True)
    day = date.fromisoformat(list_date)
    lines = [f"# 할 일 — {day:%Y-%m-%d}({WEEKDAYS[day.weekday()]})", ""]
    if start and end:
        lines += [f"- 분석 기간: {start:%m/%d %H:%M} ~ {end:%m/%d %H:%M}", ""]
    for bucket, title in (("today", "오늘"), ("tomorrow", "내일")):
        rows = [i for i in items if i["bucket"] == bucket]
        lines += [f"## {title} ({len(rows)})", ""]
        for i in rows:
            extra = " · ".join(x for x in (i.get("kind"), f"기한 {i['due']}" if i.get("due") else "", i.get("priority"),
                                           f"{i['carry_count']}일째 이월" if i.get("carry_count") else "") if x)
            lines.append(f"- {STATUS_MARK.get(i['status'], '[ ]')} {i['task']} ({extra})")
            if i.get("source_label"):
                lines.append(f"  - 출처: {i['source_label']}")
            for e in i.get("evidence") or []:
                lines.append(f"  - 근거: {e['text']}")
        lines.append("")
    path = os.path.join(out_dir, f"{list_date}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
