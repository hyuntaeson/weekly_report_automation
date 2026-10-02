#!/usr/bin/env python3
"""
LLM-based text summarizer using the internal DevX LiteLLM Proxy.

LangChain LCEL 체인으로 구현 (prompt | model | parser):
- 프록시는 OpenAI 호환이라 ChatOpenAI(base_url=...)로 연결
- 소스별 프롬프트 템플릿을 PROMPT_TEMPLATES로 분리 관리
- 체인 내장 재시도(with_retry)로 일시 오류 자동 폴백
- 모델/프롬프트 변경은 config·템플릿 수정만으로 가능

LangChain 미설치/프록시 실패 시 기존처럼 None을 반환해 호출자가 폴백.
"""

import hashlib
import json
import os
import sqlite3
import time

from weekly_report import paths

# temperature 0(결정적) 호출의 응답 캐시 — 같은 입력이면 같은 출력이므로 결과는 그대로, 재생성만 빨라짐
CACHE_DB = paths.LLM_CACHE
CACHE_TTL = 7 * 24 * 3600

try:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False

DEFAULT_SYSTEM_PROMPT = (
    "다음 텍스트를 한국어로 핵심만 간결하게 요약해줘. "
    "인사말, 서명, formatting 문구는 제외하고 실제 내용(무엇을 했는지/무슨 안건인지)만 담아줘."
)

# 소스별 요약 프롬프트 템플릿 — 체인으로 조합되는 부분만 분리 관리
PROMPT_TEMPLATES = {
    "default": DEFAULT_SYSTEM_PROMPT,
    "file": (
        "다음은 파일 내용이야. 이 파일이 무엇에 관한 것인지 한국어로 "
        "한 줄 요약해줘. 경로·확장자 설명은 빼고 내용의 목적만 담아줘."
    ),
    "teams": (
        "다음은 Teams 채팅 메시지 모음이야. 업무 관점에서 어떤 논의·지시·"
        "결정이 있었는지 한국어로 요약해줘. 인사·잡담은 빼고 업무 내용만."
    ),
    "mail": (
        "다음은 Outlook 메일이야. 발신자 의도와 핵심 안건을 한국어로 "
        "한 줄 요약해줘. 머리말·서명·면책문구는 제외."
    ),
    "diff": (
        "다음은 한 문서의 이전 버전과 새 버전 사이에 바뀐 줄 목록이야. "
        "[+]는 새로 생겼거나 바뀐 뒤의 줄, [-]는 사라졌거나 바뀌기 전의 줄이고 "
        "엑셀은 '[시트명] 셀 | 셀' 형식이야. 짝이 맞는 [-]/[+]는 '수정'으로 해석해서, "
        "무엇을 어떻게 바꿨는지 한국어로 핵심 위주로 요약하되, 의미가 끊기지 않게 써줘. "
        "변경이 적으면 짧게 1문장으로, 많으면 중요한 변경부터 구체적으로 쓰고 "
        "사소한 것은 '등'으로 묶어. "
        "'OO 항목 추가', 'OO를 XX로 변경', 'OO를 A차→B차로 이동'처럼 구체적으로 쓰고, "
        "기호·줄번호·서론 없이 요약문만 출력해."
    ),
    "work": (
        "너는 개발자의 업무 일지를 정리하는 비서야. <requests> 안의 각 줄은 개발자가 하루 동안 "
        "AI 코딩 도구에 보낸 지시문 기록이고, 모두 그대로 작업이 진행됐다고 간주해. "
        "각 지시문을 '~ 구현', '~ 수정', '~ 개선', '~ 조사' 같은 완료형 작업 항목으로 바꿔 쓰고, "
        "비슷한 항목은 하나로 합쳐 '1. …', '2. …' 번호 목록으로 출력해 (한국어). "
        "예) 입력 '- 로그인 화면에 비밀번호 찾기 버튼 추가해줘' / '- 버튼 색을 파란색으로 바꿔줘' "
        "→ 출력 '1. 로그인 화면에 비밀번호 찾기 버튼 추가 및 버튼 색상 변경'. "
        "질문·되묻기·필요한 정보 요청·설명은 절대 쓰지 말고 번호 목록만 출력해."
    ),
    "topic": (
        "다음은 한 주간의 업무 활동 목록이야. 이 활동들을 하나로 묶는 "
        "주제명을 20자 이내 한국어 명사구로 붙여줘. 주제명만 출력하고 "
        "설명·따옴표·불릿은 붙이지 마."
    ),
}


class LLMSummarizer:
    """LiteLLM 프록시(OpenAI 호환)를 LCEL 체인으로 감싼 텍스트 요약기"""

    def __init__(self, config_path=paths.LITELLM_CONFIG):
        self.config = self._load_config(config_path)
        self.enabled = bool(self.config.get("enabled")) and bool(
            self.config.get("api_key")
        )
        self._chain_cache = {}

    def _load_config(self, config_path):
        if not os.path.exists(config_path):
            return {"enabled": False}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as error:
            print(f"Warning: Failed to load LiteLLM config: {error}")
            return {"enabled": False}

    # ---------- LCEL 체인 ----------

    def _make_chain(self, max_tokens=None, temperature=0.3):
        """prompt | ChatOpenAI(LiteLLM 프록시) | StrOutputParser LCEL 체인.
        체인 내장 재시도 2회. LangChain 미설치 시 None."""
        if not _LANGCHAIN_AVAILABLE:
            return None
        base_url = str(self.config.get("base_url") or "").rstrip("/")
        api_key = str(self.config.get("api_key") or "")
        model = str(
            self.config.get("model")
            or "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0"
        )
        max_tokens = int(max_tokens or self.config.get("max_tokens") or 150)

        llm = ChatOpenAI(
            base_url=f"{base_url}/v1",
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            # 응답이 길수록 오래 걸림 — 고정 15초면 긴 생성(STEP 3 등)이 타임아웃 후 재시도로 두 배 걸림
            timeout=15 + max_tokens // 40,
        )
        prompt = ChatPromptTemplate.from_messages(
            [("system", "{system}"), ("user", "{text}")]
        )
        return (prompt | llm | StrOutputParser()).with_retry(
            stop_after_attempt=2
        )

    def _chain(self, max_tokens=None, temperature=0.3):
        key = (max_tokens or "default", temperature)
        if key not in self._chain_cache:
            self._chain_cache[key] = self._make_chain(max_tokens, temperature)
        return self._chain_cache[key]

    # ---------- 공개 API ----------

    def complete(self, system_prompt, user_text, max_tokens=None, temperature=0.3,
                 max_input=4000, cache=False):
        """임의 프롬프트로 LLM 호출. 체인 실패 시 None.
        max_tokens는 응답 길이 상한(미지정 시 config), max_input은 입력 자르기 기준.
        cache=True + temperature 0이면 같은 입력의 응답을 재사용 (보고서 분석 단계용 —
        응답을 검증해 버리고 다음 수집 때 재시도하는 수집 단계 호출에는 쓰지 않는다)."""
        if not self.enabled:
            return None
        chain = self._chain(max_tokens, temperature)
        if chain is None:
            return None
        text = (user_text or "")[:max_input]
        key = self._cache_key(system_prompt, text, max_tokens) if cache and temperature == 0 else None
        cached = self._cache_get(key) if key else None
        if cached is not None:
            return cached
        try:
            result = chain.invoke({"system": system_prompt, "text": text}).strip()
        except Exception as error:
            print(f"Warning: LLM call failed, falling back: {error}")
            return None
        if key and result:
            self._cache_put(key, result)
        return result

    # ---------- 응답 캐시 (temperature 0 전용) ----------

    def _cache_key(self, system_prompt, text, max_tokens):
        model = str(self.config.get("model") or "")
        raw = json.dumps([model, system_prompt, text, max_tokens], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_conn():
        os.makedirs(os.path.dirname(CACHE_DB), exist_ok=True)
        conn = sqlite3.connect(CACHE_DB, timeout=10)
        conn.execute("CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, response TEXT, created REAL)")
        return conn

    def _cache_get(self, key):
        try:
            conn = self._cache_conn()
            try:
                row = conn.execute("SELECT response, created FROM llm_cache WHERE key = ?", (key,)).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        if row and time.time() - row[1] < CACHE_TTL:
            return row[0]
        return None

    def _cache_put(self, key, response):
        try:
            conn = self._cache_conn()
            try:
                with conn:
                    conn.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?)", (key, response, time.time()))
            finally:
                conn.close()
        except sqlite3.Error as error:
            print(f"Warning: LLM cache write failed: {error}")

    def summarize(self, text, max_len=300, template="default"):
        """텍스트를 LLM으로 요약. template은 PROMPT_TEMPLATES 키
        (default/file/teams/mail). 짧은 입력·비활성·실패 시 폴백.
        max_len은 '이보다 짧으면 요약 없이 원문 사용' 기준일 뿐, 요약 길이를 글자 수로 제한하지 않는다
        (의미 전달 우선, 사용자 지정 2026-10-02)."""
        text = (text or "").strip()
        if not text:
            return ""
        if not self.enabled:
            return None
        # 이미 충분히 짧은 텍스트는 그대로 반환 (짧은 입력에 모델이 "요약할 내용 없음"
        # 같은 엉뚱한 응답을 하는 경우가 있어 애초에 API 호출을 생략)
        if len(text) <= max_len:
            return text
        system = PROMPT_TEMPLATES.get(template, DEFAULT_SYSTEM_PROMPT)
        # 글자 수 대신 의미가 전달되게 요청 — 응답 상한은 잘리지 않을 만큼 넉넉히
        max_tokens = max(int(self.config.get("max_tokens") or 150), 1500)
        return self.complete(f"{system} 글자 수에 얽매이지 말고, 핵심만 간결하게 하되 의미가 끊기지 않게 써줘.",
                             text, max_tokens=max_tokens)
