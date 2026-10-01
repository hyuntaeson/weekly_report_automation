"""수집기마다 다른 timestamp 형식을 로컬 시각으로 통일."""

import re
from datetime import datetime, timezone

_FRACTION_RE = re.compile(r"(\.\d{6})\d+")


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
