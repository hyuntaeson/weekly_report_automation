#!/usr/bin/env python3
"""
나만의 비서 — 17:00 진행 점검 (5-3).

① 오늘 목록의 열린 항목(미완료·진행 중, 사용자가 체크하지 않은 것)마다 오늘 09:00~지금 활동에서 후보를 고른다
   — 그 할 일이 나온 채팅방·메일 제목과 같은 곳의 활동 + 할 일 문장과 의미가 가까운 활동
   (활동: 내가 보낸 Teams·1:1 대화(DB 미저장)·보낸 메일·문서 수정·Confluence·SharePoint)
② 판정 모델이 할 일마다 완료 / 진행 중 / 미착수 + 판정 근거(시각·활동)를 쓴다. 회의는 시작 시각이 지나면 완료
③ 오늘 09:00 이후 새로 들어온 요청은 아침과 같은 방식으로 뽑아 '내일' 묶음에 '새 요청'으로 추가
④ '내일로 이월 확정': 미완료·진행 중·새 요청을 다음 근무일 목록으로 바로 옮긴다 (새 요청은 이월 횟수 안 늘림)
사용자가 체크한 항목은 자동 판정이 덮어쓰지 않는다 (TodoStore.set_status).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from weekly_report.ai.rag import _cosine, evidence_full_text, evidence_label, is_trivial_reply
from weekly_report.ai.todos import (DUPLICATE_SCORE, WORK_START, DailyTodos, _details, export_markdown,
                                    previous_workday)
from weekly_report.common.timeutil import to_local_datetime
from weekly_report.report.sections import clean_text

CANDIDATES_PER_TODO = 6
STATUS_MAP = {"완료": "done", "진행 중": "in_progress", "미착수": "open"}

PROGRESS_PROMPT = (
    "너는 업무 비서야. <todos>의 각 할 일이 오늘({today}) {window} 활동으로 처리됐는지 판정해. "
    "할 일마다 아래에 관련 활동 후보가 있다('나 →'는 내가 보낸 것).\n"
    "- 완료: 요청자에게 결과를 회신·전달했거나 요청한 작업이 끝났다고 말한 기록이 있음\n"
    "- 진행 중: 관련 활동(문의·자료 요청·메일 발송·문서 작업)은 있지만 끝났다는 신호가 없음\n"
    "- 미착수: 이 할 일과 관련된 활동이 없음 (단어만 비슷한 다른 일은 관련 없음)\n"
    "할 일마다 한 줄: '할일N: 완료|진행 중|미착수 - 근거(시각과 무엇을 했는지 한 문장, 미착수면 \"관련 활동 없음\")'. "
    "다른 설명은 쓰지 마."
)


def next_workday(day, holidays=()):
    from weekly_report.ai.todos import is_workday
    day += timedelta(days=1)
    while not is_workday(day, holidays):
        day += timedelta(days=1)
    return day


def parse_progress_output(text, count):
    """'할일N: 상태 - 근거' → {N: (status, note)}"""
    result = {}
    for k, status, note in re.findall(r"할일\s*(\d+)\s*[:：]\s*(완료|진행 중|진행중|미착수)\s*[-–—]?\s*(.*)", text or ""):
        k = int(k)
        if 1 <= k <= count:
            result[k] = (STATUS_MAP["진행 중" if status == "진행중" else status], note.strip())
    return result


class ProgressCheck(DailyTodos):
    def _today_activities(self, start, end):
        """오늘 내가 한 일·나와 주고받은 대화 (DB + 1:1 대화)"""
        acts = self.gen.fetch_week_activities(start.date().isoformat(), end.date().isoformat())
        picked = []
        for a in acts:
            when = to_local_datetime(a.get("timestamp"), a.get("source"))
            if not when or not (start <= when.replace(tzinfo=None) < end):
                continue
            d = _details(a)
            source, action = a.get("source"), a.get("action")
            if source == "teams" and action == "message":
                if d.get("from_me") or d.get("mentions_me"):
                    picked.append(a)
            elif source == "outlook" and action in ("email_sent", "email_received"):
                picked.append(a)
            elif source in ("filesystem", "confluence", "sharepoint", "onenote"):
                picked.append(a)
        try:
            from weekly_report.collectors.teams import TeamsCollector
            picked += (self.teams or TeamsCollector()).collect_direct_messages(start, end)
        except Exception as error:
            print(f"Warning: 1:1 messages unavailable: {error}")
        return [a for a in picked if not is_trivial_reply(_details(a).get("text") or "x" * 10)]

    def run(self, today=None, now=None):
        """17:00 점검 → 상태 저장 + 새 요청 추가. 반환: 그 날짜 목록"""
        today = today or date.today()
        now = now or datetime.now()
        key = today.isoformat()
        start, end = datetime.combine(today, WORK_START), now
        items = self.store.list_for(key)
        # 회의: 시작 시각이 지났으면 완료 (사용자 체크와 무관한 일정 종료)
        for item in items:
            if item.get("kind") == "일정" and item["status"] != "done" and item["bucket"] == "today":
                m = re.match(r"(\d{1,2}):(\d{2})", item.get("due") or "")
                if m and datetime.combine(today, time(int(m.group(1)), int(m.group(2)))) <= now:
                    self.store.set_status(item["id"], "done", by="schedule", note=f"{m.group(0)} 회의 일정 지남")
        targets = [i for i in self.store.list_for(key)
                   if i["status"] in ("open", "in_progress") and i.get("kind") not in ("일정", "새 요청")
                   and i.get("done_by") != "manual" and i["bucket"] == "today"]
        activities = self._today_activities(start, end) if targets else []
        if targets:
            self._judge(targets, activities, today, start, end)
        self._add_new_requests(today, key, start, end)
        self.store.mark_run(key, "pm")
        result = self.store.list_for(key)
        export_markdown(key, result)
        return result

    def _judge(self, targets, activities, today, start, end):
        texts = []
        for a in activities:
            when = to_local_datetime(a.get("timestamp"), a.get("source"))
            d = _details(a)
            mine = d.get("from_me") or a.get("action") == "email_sent" or a.get("source") in ("filesystem", "confluence",
                                                                                              "sharepoint", "onenote")
            texts.append((a, f"{when:%H:%M} {'나 → ' if mine else ''}{evidence_label(a, when)} | "
                             f"{clean_text(evidence_full_text(a), 400)}"))
        try:
            vectors = self.rag.clusterer.embed([t["task"] for t in targets] + [t for _, t in texts]) if texts else []
        except Exception as error:
            print(f"Warning: progress embedding failed: {error}")
            vectors = []
        task_vecs, act_vecs = vectors[:len(targets)], vectors[len(targets):]
        blocks = []
        for k, item in enumerate(targets, start=1):
            # 같은 채팅방·메일 제목(할 일이 나온 곳)의 활동 + 의미가 가까운 활동
            origin = " ".join(e.get("label", "") for e in item.get("evidence") or []) + " " + (item.get("source_label") or "")
            same_place = [i for i, (a, _) in enumerate(texts) if _place(a) and _place(a) in origin]
            similar = []
            if task_vecs and act_vecs:
                similar = sorted(range(len(texts)), key=lambda i: -_cosine(task_vecs[k - 1], act_vecs[i]))
            chosen = list(dict.fromkeys(same_place[-3:] + similar))[:CANDIDATES_PER_TODO]
            lines = [f"  - {texts[i][1]}" for i in sorted(chosen, key=lambda i: texts[i][1][:5])] or ["  - (오늘 활동 없음)"]
            blocks.append(f"할일{k}: {item['task']} (요청자 {item.get('requester') or '-'}, 출처 {item.get('source_label') or '-'})\n"
                          + "\n".join(lines))
        prompt = PROGRESS_PROMPT.format(today=f"{today:%m/%d}", window=f"{start:%H:%M}~{end:%H:%M}")
        output = self.rag.judge_llm.complete(prompt, "<todos>\n" + "\n\n".join(blocks) + "\n</todos>",
                                             max_tokens=1500, max_input=60000, temperature=0)
        verdicts = parse_progress_output(output, len(targets))
        for k, item in enumerate(targets, start=1):
            status, note = verdicts.get(k, ("open", "판정 실패 — 확인 필요"))
            self.store.set_status(item["id"], status, by="auto", note=note)

    def _add_new_requests(self, today, key, start, end):
        """오늘 09:00 이후 새로 들어온 요청 → '내일' 묶음에 '새 요청' (아침 목록·이미 넣은 것과 겹치면 뺌)"""
        fresh = self._extract(today, start, end)
        existing = self.store.list_for(key, include_removed=True)
        fresh = self._drop_duplicates(fresh, existing)
        for item in fresh:
            item["bucket"], item["kind"] = "tomorrow", "새 요청"
        if fresh:
            self.store.add_items(key, fresh)

    def confirm_carry(self, today=None):
        """'내일로 이월 확정' — 미완료·진행 중·새 요청을 다음 근무일 목록으로. 반환: (다음 근무일, 옮긴 건수)"""
        today = today or date.today()
        target = next_workday(today, self.holidays)
        moved = self.store.carry_over(today.isoformat(), target.isoformat())
        export_markdown(target.isoformat(), self.store.list_for(target.isoformat()))
        return target, len(moved)


def _place(activity):
    """활동이 일어난 곳 (Teams 채팅방 이름·메일 제목) — 할 일이 나온 곳과 같은지 비교용"""
    d = _details(activity)
    return d.get("chat") or d.get("subject") or ""
