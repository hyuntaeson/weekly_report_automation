#!/usr/bin/env python3
"""
주간보고 STEP 1 — 프로그램별 · 항목별 활동 묶기.

활동(DB 행)을 사용자가 인식하는 "프로그램" 단위로 분류하고, 한 주 전체를
항목(①②③, 첫 활동 시각순) → 상세 줄로 구조화한다. 날짜별로 쪼개면 같은
파일이 날마다 반복돼 읽기 어려워서 주 단위로 합친다.
활동이 없는 프로그램은 결과에 포함하지 않는다.

반환 형식:
[
  {"name": "Chrome", "total": 12, "active_days": 3, "items": [
     {"title": "github.com", "lines": ["PR 리뷰 — https://..."]},
  ]},
]
"""

from __future__ import annotations

import html
import json
import os
import re
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import urlparse

SHARED_DOCS = "공유 문서 변경"

# 보고서에 표시되는 프로그램 순서: 문서 → 협업/커뮤니케이션 → 브라우저 → 개발 → 파트원 확인용
PROGRAM_ORDER = [
    "Excel", "Word", "PowerPoint", "OneNote", "Notepad",
    "Outlook", "Teams", "Slack", "Confluence",
    "Chrome",
    "Claude Code (IDE)", "Devin (IDE)",
    SHARED_DOCS,
]
# 섹션 제목 아래 붙는 설명. 공유 문서 변경은 내 업무가 아니라 파트원 작업 확인용이라
# STEP 2(내 업무 요약) 입력에서도 빠진다
SECTION_NOTES = {
    SHARED_DOCS: "파트원이 수정한 공유 문서 (SharePoint/OneDrive) — 업무 확인용",
}
MY_WORK_EXCLUDED = {SHARED_DOCS}

_FILE_TYPE_PROGRAM = {
    "excel": "Excel",
    "csv": "Excel",
    "word": "Word",
    "powerpoint": "PowerPoint",
    "text": "Notepad",
    "markdown": "Notepad",
}

_SOURCE_PROGRAM = {
    "onenote": "OneNote",
    "outlook": "Outlook",
    "teams": "Teams",
    "slack": "Slack",
    "confluence": "Confluence",
    "browser": "Chrome",
    "claude_code": "Claude Code (IDE)",
    "vscode": "Claude Code (IDE)",
    "orca": "Claude Code (IDE)",
    "devin": "Devin (IDE)",
}

_HEX_TEMP_NAME_RE = re.compile(r"^[0-9A-Fa-f]{8}(\.[A-Za-z0-9]+)?$")
_FRACTION_RE = re.compile(r"(\.\d{6})\d+")

MAX_LINES_PER_ITEM = 5
MAX_TEXT_LEN = 160
# 파일 변경·문서 요약 줄 — STEP 2 재요약의 재료가 되므로 넉넉하게
SUMMARY_LEN = 500


_OFFICE_EXT_PROGRAM = {
    ".xlsx": "Excel", ".xlsm": "Excel", ".xls": "Excel", ".csv": "Excel",
    ".docx": "Word", ".doc": "Word",
    ".pptx": "PowerPoint", ".ppt": "PowerPoint",
}


def _sharepoint_name(activity, details=None):
    details = details if details is not None else _details(activity)
    return details.get("name") or _strip_prefix(activity.get("file_path"), ("SharePoint 파일:",))


def _same_person(a, b):
    """Graph 표시 이름 비교 — 부서 표기가 달라도 '이름(' 앞부분이 같으면 동일인."""
    if not a or not b:
        return False
    return a == b or a.split("(")[0].strip() == b.split("(")[0].strip()


def _edited_by_me(details, me_name):
    editors = details.get("editors") or (
        [details["modified_by"]] if details.get("modified_by") else []
    )
    return bool(details.get("edited_by_me")) or any(_same_person(e, me_name) for e in editors)


def classify_program(activity, me_name=None):
    """활동 → 프로그램 이름. 보고 대상이 아니면 None."""
    source = activity.get("source")
    if source == "filesystem":
        return _FILE_TYPE_PROGRAM.get(activity.get("file_type"))
    if source == "sharepoint":
        # SharePoint/OneDrive는 오피스 문서만 해당 프로그램으로 편입
        # (스크린샷·zip·html 업로드는 문서 작업이 아니므로 제외)
        details = _details(activity)
        ext = os.path.splitext(_sharepoint_name(activity, details))[1].lower()
        program = _OFFICE_EXT_PROGRAM.get(ext)
        if program and not _edited_by_me(details, me_name):
            return SHARED_DOCS
        return program
    return _SOURCE_PROGRAM.get(source)


def is_my_work(activity, me_name=None):
    """파트원만 수정한 공유 문서 변경이 아니면 True (STEP 2·주제 분석 대상)."""
    return classify_program(activity, me_name) not in MY_WORK_EXCLUDED


def to_local_datetime(timestamp, source=None):
    """수집기마다 제각각인 timestamp를 로컬(naive) datetime으로 통일.

    - 숫자 문자열: epoch 초/밀리초 (Claude Code 세션)
    - 'Z'/오프셋 포함 ISO: 로컬 시간대로 변환 (Graph, 크롬 확장, Confluence)
    - Outlook(COM): pywin32가 로컬 시각에 UTC tzinfo를 붙여서 주므로
      오프셋을 무시하고 값 그대로 로컬로 취급
    - 오프셋 없는 Teams 일정: Graph calendarView는 UTC로 내려줌
    """
    if timestamp is None:
        return None
    text = str(timestamp).strip()
    if not text:
        return None
    if text.isdigit():
        value = int(text)
        return datetime.fromtimestamp(value / 1000 if value > 10**11 else value)
    try:
        parsed = datetime.fromisoformat(
            _FRACTION_RE.sub(r"\1", text.replace("Z", "+00:00"))
        )
    except ValueError:
        return None
    if source == "outlook":
        return parsed.replace(tzinfo=None)
    if parsed.tzinfo is None:
        if source == "teams":
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            return parsed
    return parsed.astimezone().replace(tzinfo=None)


def _details(activity):
    details = activity.get("details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (TypeError, ValueError):
            return {}
    return details if isinstance(details, dict) else {}


def clean_text(text, limit=MAX_TEXT_LEN):
    """HTML 엔티티·마크다운 장식·줄바꿈을 걷어내고 한 줄로 자른다."""
    text = html.unescape(str(text or "")).replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[#*`>]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _strip_prefix(value, prefixes):
    value = str(value or "")
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix):].strip()
    return value.strip()


class _ItemCollector:
    """한 프로그램의 항목들을 첫 등장 순서대로 모은다."""

    def __init__(self):
        self.items = OrderedDict()

    def get(self, key, title):
        if key not in self.items:
            self.items[key] = {"title": title, "lines": [], "counts": OrderedDict()}
        return self.items[key]

    @staticmethod
    def add_line(item, line):
        line = (line or "").strip()
        if line and line not in item["lines"]:
            item["lines"].append(line)

    @staticmethod
    def count(item, label):
        item["counts"][label] = item["counts"].get(label, 0) + 1


def build_program_sections(activities, me_name=None, teams_settings=None):
    """활동 목록 → STEP 1 프로그램 섹션 목록 (PROGRAM_ORDER 순)."""
    teams_settings = teams_settings or {}
    excluded = teams_settings.get("excluded_chats") or []
    excluded_ids = {c.get("id") for c in excluded if isinstance(c, dict)}
    excluded_titles = {c.get("title") for c in excluded if isinstance(c, dict)}
    teams_scope = teams_settings.get("report_scope", "mine")

    grouped: dict[str, _ItemCollector] = {}
    totals: dict[str, int] = {}
    active_days: dict[str, set] = {}

    entries = []
    for activity in activities:
        program = classify_program(activity, me_name)
        if not program:
            continue
        when = to_local_datetime(activity.get("timestamp"), activity.get("source"))
        if when is None:
            continue
        entries.append((when, program, activity))
    entries.sort(key=lambda e: e[0])

    for when, program, activity in entries:
        collector = grouped.setdefault(program, _ItemCollector())
        details = _details(activity)
        handler = _HANDLERS.get(program, _add_file)
        added = handler(
            collector, activity, details, when,
            me_name=me_name, teams_scope=teams_scope,
            excluded_ids=excluded_ids, excluded_titles=excluded_titles,
        )
        if added is not False:
            totals[program] = totals.get(program, 0) + 1
            active_days.setdefault(program, set()).add(when.date())

    sections = []
    for program in PROGRAM_ORDER:
        if program not in grouped:
            continue
        items = [_finalize_item(item) for item in grouped[program].items.values()]
        if items:
            sections.append({
                "name": program,
                "note": SECTION_NOTES.get(program, ""),
                "total": totals.get(program, 0),
                "active_days": len(active_days.get(program, ())),
                "items": items,
            })
    return sections


def _finalize_item(item):
    """count 라벨(예: '수정 3건')과 상세 줄을 합쳐 표시용 항목으로."""
    lines = list(item["lines"]) or list(item.get("fallback_lines", []))
    # 파일은 "무엇을 수정했는지"가 있으면 "수정 N건" 같은 건수 줄은 생략
    if item["counts"] and not (item.get("count_only_fallback") and lines):
        count_line = ", ".join(f"{label} {n}건" for label, n in item["counts"].items())
        lines = [count_line] + lines
    max_lines = item.get("max_lines", MAX_LINES_PER_ITEM)
    more = max(0, len(lines) - max_lines)
    lines = lines[:max_lines]
    if more:
        lines.append(f"… 외 {more}건")
    return {"title": item["title"], "lines": lines}


# ---------------- 프로그램별 항목 핸들러 ----------------

_FILE_ACTION_LABEL = {
    "created": "생성", "modified": "수정", "deleted": "삭제", "moved": "이동/이름변경",
}


def _add_file(collector, activity, details, when, **_):
    """Excel/Word/PowerPoint/Notepad (로컬 파일) + SharePoint(Excel로 편입)."""
    if activity.get("source") == "sharepoint":
        name = _sharepoint_name(activity, details)
        item = collector.get(("sharepoint", name), f"{name} (SharePoint)")
        item["count_only_fallback"] = True
        editors = details.get("editors") or (
            [details["modified_by"]] if details.get("modified_by") else []
        )
        who = ", ".join(dict.fromkeys(e.split("(")[0].strip() for e in editors if e))
        summary = clean_text(details.get("summary") or "", SUMMARY_LEN)
        if summary:
            collector.add_line(item, f"{who}: {summary}" if who else summary)
        else:
            # 버전 비교 이전 방식으로 쌓인 기록 등 — 같은 문서에 실제 변경 요약이
            # 하나라도 있으면 표시하지 않는다 (_finalize_item에서 판단)
            fallback = item.setdefault("fallback_lines", [])
            line = f"{who}: 수정 (변경 내용 확인 불가)" if who else "수정 (변경 내용 확인 불가)"
            if line not in fallback:
                fallback.append(line)
        return True

    path = str(activity.get("file_path") or "")
    action = activity.get("action")
    if action == "moved" and " -> " in path:
        src, dest = (p.strip() for p in path.split(" -> ", 1))
        # 오피스 원자적 저장(임시파일로 바꿔치기)은 사람이 한 이동이 아님
        if _HEX_TEMP_NAME_RE.match(os.path.basename(src)) or _HEX_TEMP_NAME_RE.match(
            os.path.basename(dest)
        ):
            return False
        item = collector.get(dest.lower(), os.path.basename(dest))
        collector.add_line(item, f"이름 변경/이동: {os.path.basename(src)} → {os.path.basename(dest)}")
        collector.count(item, _FILE_ACTION_LABEL["moved"])
        return True

    item = collector.get(path.lower(), os.path.basename(path) or path)
    item["count_only_fallback"] = True
    collector.count(item, _FILE_ACTION_LABEL.get(action, action or "변경"))
    summary = details.get("summary") or details.get("content_added")
    if summary:
        collector.add_line(item, clean_text(summary, SUMMARY_LEN))
    return True


def _add_onenote(collector, activity, details, when, **_):
    if details.get("type") == "notebook":
        # 섹션 단위 기록이 있으면 노트북 단위 기록은 중복이라 생략
        name = details.get("name") or ""
        if any(key[0] == "section" and key[1] == name for key in collector.items):
            return False
        item = collector.get(("notebook", name), name or "(노트북)")
        collector.count(item, "수정")
        return True
    notebook = details.get("notebook") or ""
    section = details.get("name") or _strip_prefix(
        activity.get("file_path"), ("OneNote 섹션:",)
    )
    collector.items.pop(("notebook", notebook), None)
    item = collector.get(("section", notebook, section), f"{notebook} > {section}".strip(" >"))
    collector.count(item, "수정")
    return True


def _add_outlook(collector, activity, details, when, **_):
    action = activity.get("action")
    subject = clean_text(
        details.get("subject")
        or _strip_prefix(activity.get("file_path"), ("Sent:", "Email:", "Meeting:", "Teams Meeting:"))
    )
    if action == "email_sent":
        item = collector.get("sent", "보낸 메일")
        summary = clean_text(details.get("summary") or "", SUMMARY_LEN)
        collector.add_line(item, f"{subject}: {summary}" if summary else subject)
        collector.count(item, "발송")
    elif action == "email_received":
        # 받은 메일은 건수만 집계 (제목 나열 X)
        item = collector.get("received", "받은 메일")
        collector.count(item, "수신")
    elif action == "meeting":
        item = collector.get("meeting", "회의")
        location = clean_text(details.get("location") or "", 40)
        line = f"{when:%m/%d %H:%M} {subject}"
        collector.add_line(item, f"{line} ({location})" if location else line)
    else:
        return False
    return True


def _add_teams(collector, activity, details, when, *, me_name=None, teams_scope="mine",
               excluded_ids=(), excluded_titles=(), **_):
    if activity.get("action") == "meeting":
        subject = clean_text(
            details.get("subject") or _strip_prefix(activity.get("file_path"), ("회의:",))
        )
        item = collector.get(("meeting", subject), f"회의: {subject}")
        count = details.get("attendee_count")
        collector.add_line(item, f"{when:%m/%d %H:%M}, 참석 {count}명" if count else f"{when:%m/%d %H:%M}")
        return True

    chat = details.get("chat") or _strip_prefix(activity.get("file_path"), ("Teams 채팅:",))
    chat_id = details.get("chat_id")
    if chat_id in excluded_ids or chat in excluded_titles:
        return False
    sender = details.get("sender") or ""
    from_me = bool(details.get("from_me") or (me_name and sender == me_name))
    # 이름 없는 1:1/그룹 채팅은 서로 다른 방이 한 항목으로 합쳐지지 않도록
    # chat_id로 구분하고, 제목은 상대방 이름으로 붙인다
    generic = chat in ("oneOnOne", "group", "")
    kind = "1:1" if chat == "oneOnOne" else "그룹"
    item = collector.get(("chat", chat_id or chat), f"{kind} 채팅" if generic else chat)
    partner = sender.split("(")[0].strip()
    if generic and not from_me and partner and partner != "Unknown" and not item.get("named"):
        item["title"] = f"{kind} - {partner}"
        item["named"] = True
    collector.count(item, "보낸 메시지" if from_me else "받은 메시지")
    text = clean_text(details.get("text") or "", 100)
    if text and (from_me or teams_scope == "all"):
        collector.add_line(item, text)
    return True


def _add_slack(collector, activity, details, when, **_):
    channel = details.get("channel") or _strip_prefix(activity.get("file_path"), ("Slack:",))
    item = collector.get(channel, f"#{channel}" if channel else "(채널)")
    collector.count(item, "메시지")
    text = clean_text(details.get("text") or "", 100)
    if text:
        collector.add_line(item, text)
    return True


def _add_confluence(collector, activity, details, when, **_):
    title = activity.get("file_path") or "(페이지)"
    item = collector.get(title, title)
    label = "생성" if activity.get("action") == "confluence_created" else "수정"
    collector.count(item, label)
    summary = clean_text(details.get("summary") or "", SUMMARY_LEN)
    if summary:
        collector.add_line(item, summary)
    return True


def _add_chrome(collector, activity, details, when, **_):
    url = str(activity.get("file_path") or "")
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain:
        return False
    item = collector.get(domain, domain)
    item["max_lines"] = 10
    visits = item.setdefault("visits", OrderedDict())
    if url in visits:
        visits[url]["count"] += 1
    else:
        visits[url] = {"title": clean_text(details.get("title") or "", 60), "count": 1}
    item["lines"] = [
        f"{v['title'] + ' — ' if v['title'] else ''}"
        f"{u if len(u) <= 120 else u[:119] + '…'}"
        + (f" ({v['count']}회)" if v["count"] > 1 else "")
        for u, v in visits.items()
    ]
    return True


def _project_item(collector, project_path):
    """Claude Code 요청 기록과 Orca 에이전트 시간을 같은 프로젝트 항목으로 합친다
    (Orca가 띄우는 에이전트가 곧 Claude Code라서 경로 구분자만 다름)."""
    path = str(project_path or "").replace("/", "\\").rstrip("\\")
    name = os.path.basename(path) or path or "(프로젝트)"
    item = collector.get(("project", path.lower()), name)
    item.setdefault("base_title", name)
    item["count_only_fallback"] = True
    return item


def _add_ide(collector, activity, details, when, **_):
    """VSCode는 작업 폴더별 '파일: 수정 내용', Claude Code/Orca는 프로젝트별 작업 요약.
    요약할 내용이 없는 예전 로그 기록(로그 파일 수정 시각)은 표시하지 않는다."""
    source, action = activity.get("source"), activity.get("action")

    if source == "vscode":
        summary = clean_text(details.get("summary") or "", SUMMARY_LEN)
        if action != "edited" or not summary:
            return False
        workspace = details.get("workspace") or "(작업 폴더)"
        item = collector.get(("vscode", workspace), f"{workspace} (VSCode)")
        file_name = details.get("file") or os.path.basename(str(activity.get("file_path") or ""))
        collector.add_line(item, f"{file_name}: {summary}")
        return True

    if source == "orca":
        if action != "agent_sessions":
            return False
        item = _project_item(collector, activity.get("file_path"))
        item["orca_minutes"] = item.get("orca_minutes", 0) + int(details.get("duration_min") or 0)
        hours, minutes = divmod(item["orca_minutes"], 60)
        spent = f"{hours}시간 {minutes}분" if hours else f"{minutes}분"
        item["title"] = f"{item['base_title']} (Orca 에이전트 작업 약 {spent})"
        return True

    # claude_code
    if action == "work_summary":
        summary = clean_text(details.get("summary") or "", SUMMARY_LEN)
        if not summary:
            return False
        # 한 프로젝트에 여러 날 요약이 쌓이므로 날짜를 머리로 붙여 구분
        collector.add_line(
            _project_item(collector, activity.get("file_path")), f"{when:%m/%d} 작업: {summary}"
        )
        return True
    if action == "claude_interaction":
        # 작업 요약이 없는 날을 위한 대비: 요청 원문 (요약이 하나라도 있으면 숨김)
        prompt = clean_text(details.get("display") or "", 150)
        if not prompt:
            return False
        item = _project_item(collector, details.get("project") or activity.get("file_path"))
        fallback = item.setdefault("fallback_lines", [])
        if prompt not in fallback:
            fallback.append(prompt)
        return True
    return False  # session_start 등 내용 없는 메타 기록


def _add_devin(collector, activity, details, when, **_):
    title = activity.get("file_path") or "Devin 세션"
    item = collector.get(title, title)
    collector.count(item, "세션")
    summary = clean_text(details.get("summary") or "", SUMMARY_LEN)
    if summary:
        collector.add_line(item, summary)
    return True


_HANDLERS = {
    "OneNote": _add_onenote,
    "Outlook": _add_outlook,
    "Teams": _add_teams,
    "Slack": _add_slack,
    "Confluence": _add_confluence,
    "Chrome": _add_chrome,
    "Claude Code (IDE)": _add_ide,
    "Devin (IDE)": _add_devin,
}


_SEQ_NUM_RE = re.compile(r"(?:(?<=\s)|^)(\d{1,2})[.)](?=\s)")
_SEQ_CIRCLED_RE = re.compile("[①-⑳]")


def split_sequence(text):
    """요약 줄 안의 번호 목록을 분리 → {"head": 앞부분, "items": [번호 항목들]}.

    '개선 요청: 1. A 2. B' → head '개선 요청:', items ['1. A', '2. B'].
    IP·버전(10.253.42.50, 3.0)을 번호로 오인하지 않도록 '숫자 + 점/괄호 + 공백'이
    1부터 연속으로 2개 이상일 때만 나눈다. ①②도 같은 규칙."""
    text = text or ""
    starts, expected = [], 1
    for m in _SEQ_NUM_RE.finditer(text):
        if int(m.group(1)) == expected:
            starts.append(m.start())
            expected += 1
    if len(starts) < 2:
        starts, expected = [], 0x2460
        for m in _SEQ_CIRCLED_RE.finditer(text):
            if ord(m.group()) == expected:
                starts.append(m.start())
                expected += 1
    if len(starts) < 2:
        return {"head": text, "items": []}
    bounds = zip(starts, starts[1:] + [len(text)])
    return {
        "head": text[: starts[0]].strip(),
        "items": [text[a:b].strip() for a, b in bounds],
    }


def sections_digest(sections, limit=12000):
    """STEP 2 LLM 요약 입력용 — STEP 1 내용을 거의 그대로 넘긴다.
    한 프로그램(예: 방문 URL이 많은 Chrome)이 입력을 독차지하지 않도록
    프로그램마다 예산을 나눠 자른다. 브라우저 줄은 URL을 빼고 제목만."""
    sections = [s for s in sections if s["name"] not in MY_WORK_EXCLUDED]
    if not sections:
        return ""
    budget = max(limit // len(sections), 1500)
    blocks = []
    for section in sections:
        lines = [f"[{section['name']}]"]
        for item in section["items"]:
            details = [l for l in item["lines"] if not l.startswith("…")]
            if section["name"] == "Chrome":
                details = [l.split(" — ")[0] for l in details]
            lines.append(f"- {item['title']}: " + " / ".join(details))
        blocks.append("\n".join(lines)[:budget])
    return "\n".join(blocks)[:limit]
