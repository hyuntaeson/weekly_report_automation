#!/usr/bin/env python3
"""
Windows Office COM으로 문서 내용을 줄 단위 텍스트로 읽는 공용 모듈.

사내 DRM이 .xlsx/.docx/.pptx를 OLE2로 재암호화하면 openpyxl 등 파서로는
못 읽지만, Office 앱은 자체 권한으로 복호화해 열 수 있다. 로컬 파일 감시
(file_watcher)와 SharePoint 버전 비교(sharepoint_collector)가 함께 쓴다.

- DispatchEx로 항상 새 인스턴스를 띄우고, 종료 시 다른 문서가 열려 있으면
  Quit하지 않는다 (사용자가 작업 중인 Office 창을 닫지 않기 위함)
- 범위를 한 번에 읽어(UsedRange.Value) 셀 단위 COM 호출을 피한다
- 워커 스레드에서도 동작하도록 COM 초기화를 직접 한다
"""

from __future__ import annotations

import sys
from collections import Counter
from contextlib import contextmanager
from datetime import datetime

_OPEN_DOCS = {
    "Excel": lambda app: app.Workbooks.Count,
    "Word": lambda app: app.Documents.Count,
    "PowerPoint": lambda app: app.Presentations.Count,
}
_EXT_PROG = {
    ".xlsx": "Excel", ".xlsm": "Excel", ".xls": "Excel",
    ".docx": "Word", ".doc": "Word",
    ".pptx": "PowerPoint", ".ppt": "PowerPoint",
}
MAX_ROWS_PER_SHEET = 5000


def prog_for(path):
    """파일 확장자 → Office 앱 이름 (지원 안 하면 None)"""
    lower = str(path).lower()
    return next((p for ext, p in _EXT_PROG.items() if lower.endswith(ext)), None)


@contextmanager
def office_app(prog):
    """Office COM 앱 인스턴스. 비Windows/미설치 시 None을 yield."""
    if sys.platform != "win32":
        yield None
        return
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    app = None
    try:
        try:
            app = win32com.client.DispatchEx(f"{prog}.Application")
        except Exception:
            app = None
        if app is not None:
            for attr, val in (("Visible", False), ("DisplayAlerts", False)):
                try:
                    setattr(app, attr, val)
                except Exception:
                    pass
        yield app
    finally:
        if app is not None:
            try:
                if _OPEN_DOCS[prog](app) == 0:
                    app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def excel_snapshot(app, path):
    """{시트명: [행 튜플(문자열 셀)]} — 빈 행 제외. 실패 시 None."""
    try:
        wb = app.Workbooks.Open(path, ReadOnly=True, UpdateLinks=0, AddToMru=False)
    except Exception:
        return None
    try:
        snapshot = {}
        for ws in wb.Worksheets:
            values = ws.UsedRange.Value
            if values is None:
                continue
            if not isinstance(values, tuple):
                values = ((values,),)
            rows = []
            for row in values[:MAX_ROWS_PER_SHEET]:
                cells = tuple(_cell_text(v) for v in row)
                if any(cells):
                    rows.append(cells)
            snapshot[ws.Name] = rows
        return snapshot
    except Exception:
        return None
    finally:
        try:
            wb.Close(False)
        except Exception:
            pass


def word_paragraphs(app, path):
    """문단 텍스트 목록. 실패 시 None."""
    try:
        doc = app.Documents.Open(path, ReadOnly=True, AddToRecentFiles=False, Visible=False)
    except Exception:
        return None
    try:
        text = doc.Content.Text or ""
        return [p.strip() for p in text.replace("\x07", "\r").split("\r") if p.strip()]
    except Exception:
        return None
    finally:
        try:
            doc.Close(0)
        except Exception:
            pass


def ppt_lines(app, path):
    """'[슬라이드 N] 텍스트 / 텍스트' 목록. 실패 시 None."""
    try:
        pres = app.Presentations.Open(path, ReadOnly=True, WithWindow=False)
    except Exception:
        return None
    try:
        lines = []
        for number, slide in enumerate(pres.Slides, start=1):
            texts = []
            for shape in slide.Shapes:
                try:
                    if shape.HasTextFrame and shape.TextFrame.HasText:
                        text = shape.TextFrame.TextRange.Text.strip()
                        if text:
                            texts.append(text)
                except Exception:
                    continue
            if texts:
                lines.append(f"[슬라이드 {number}] " + " / ".join(texts))
        return lines
    except Exception:
        return None
    finally:
        try:
            pres.Close()
        except Exception:
            pass


def document_lines(app, prog, path):
    """앱 종류에 맞춰 문서를 비교용 줄 목록으로 읽는다. 실패 시 None."""
    if prog == "Excel":
        snapshot = excel_snapshot(app, path)
        if snapshot is None:
            return None
        return [
            f"[{sheet}] " + " | ".join(c for c in row if c)
            for sheet, rows in snapshot.items()
            for row in rows
        ]
    if prog == "Word":
        return word_paragraphs(app, path)
    if prog == "PowerPoint":
        return ppt_lines(app, path)
    return None


def diff_lines(old_lines, new_lines):
    """순서 무관 다중집합 비교 → (추가/변경 후 줄, 삭제/변경 전 줄)"""
    old_count, new_count = Counter(old_lines), Counter(new_lines)
    added, removed = [], []
    for line in new_lines:
        if old_count[line] > 0:
            old_count[line] -= 1
        else:
            added.append(line)
    for line in old_lines:
        if new_count[line] > 0:
            new_count[line] -= 1
        else:
            removed.append(line)
    return added, removed
