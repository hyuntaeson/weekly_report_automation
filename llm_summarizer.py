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

import json
import os

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
    "topic": (
        "다음은 한 주간의 업무 활동 목록이야. 이 활동들을 하나로 묶는 "
        "주제명을 20자 이내 한국어 명사구로 붙여줘. 주제명만 출력하고 "
        "설명·따옴표·불릿은 붙이지 마."
    ),
}


class LLMSummarizer:
    """LiteLLM 프록시(OpenAI 호환)를 LCEL 체인으로 감싼 텍스트 요약기"""

    def __init__(self, config_path="config/litellm_config.json"):
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

    def _make_chain(self):
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
        max_tokens = int(self.config.get("max_tokens") or 150)

        llm = ChatOpenAI(
            base_url=f"{base_url}/v1",
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=0.3,
            timeout=15,
        )
        prompt = ChatPromptTemplate.from_messages(
            [("system", "{system}"), ("user", "{text}")]
        )
        return (prompt | llm | StrOutputParser()).with_retry(
            stop_after_attempt=2
        )

    def _chain(self):
        if "default" not in self._chain_cache:
            self._chain_cache["default"] = self._make_chain()
        return self._chain_cache["default"]

    # ---------- 공개 API ----------

    def complete(self, system_prompt, user_text, max_tokens=None, temperature=0.3):
        """임의 프롬프트로 LLM 호출. 체인 실패 시 None."""
        if not self.enabled:
            return None
        chain = self._chain()
        if chain is None:
            return None
        try:
            return chain.invoke(
                {"system": system_prompt, "text": (user_text or "")[:4000]}
            ).strip()
        except Exception as error:
            print(f"Warning: LLM call failed, falling back: {error}")
            return None

    def summarize(self, text, max_len=300, template="default"):
        """텍스트를 LLM으로 요약. template은 PROMPT_TEMPLATES 키
        (default/file/teams/mail). 짧은 입력·비활성·실패 시 폴백."""
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
        return self.complete(f"{system} (최대 {max_len}자)", text)
