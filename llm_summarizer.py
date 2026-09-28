#!/usr/bin/env python3
"""
LLM-based text summarizer using the internal DevX LiteLLM Proxy.
Falls back to None (caller decides fallback) if disabled/unconfigured/failing.
"""

import json
import os

import requests

DEFAULT_SYSTEM_PROMPT = (
    "다음 텍스트를 한국어로 핵심만 간결하게 요약해줘. "
    "인사말, 서명, formatting 문구는 제외하고 실제 내용(무엇을 했는지/무슨 안건인지)만 담아줘."
)


class LLMSummarizer:
    """DevX LiteLLM Proxy(OpenAI 호환 Chat Completions)를 이용한 텍스트 요약기"""

    def __init__(self, config_path="config/litellm_config.json"):
        self.config = self._load_config(config_path)
        self.enabled = bool(self.config.get("enabled")) and bool(
            self.config.get("api_key")
        )

    def _load_config(self, config_path):
        if not os.path.exists(config_path):
            return {"enabled": False}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as error:
            print(f"Warning: Failed to load LiteLLM config: {error}")
            return {"enabled": False}

    def _endpoint(self):
        base_url = str(self.config.get("base_url") or "").rstrip("/")
        api_key = str(self.config.get("api_key") or "")
        model = str(
            self.config.get("model")
            or "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0"
        )
        return base_url, api_key, model

    def complete(self, system_prompt, user_text, max_tokens=None, temperature=0.3):
        """임의 프롬프트로 LLM 호출 (요약 외 용도: 클러스터 명명, 키워드 추출 등).
        비활성화되었거나 실패하면 None."""
        if not self.enabled:
            return None
        base_url, api_key, model = self._endpoint()
        try:
            response = requests.post(
                f"{base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text[:4000]},
                    ],
                    "max_tokens": int(max_tokens or self.config.get("max_tokens") or 150),
                    "temperature": temperature,
                },
                timeout=15,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except (requests.exceptions.RequestException, KeyError, IndexError, ValueError) as error:
            print(f"Warning: LLM call failed, falling back: {error}")
            return None

    def summarize(self, text, max_len=300):
        """텍스트를 LLM으로 요약. 비활성화되었거나 실패하면 None 반환(호출자가 폴백 처리)."""
        text = (text or "").strip()
        if not text:
            return ""
        if not self.enabled:
            return None
        # 이미 충분히 짧은 텍스트는 그대로 반환 (짧은 입력에 모델이 "요약할 내용 없음"
        # 같은 엉뚱한 응답을 하는 경우가 있어 애초에 API 호출을 생략)
        if len(text) <= max_len:
            return text
        return self.complete(
            f"{DEFAULT_SYSTEM_PROMPT} (최대 {max_len}자)", text
        )
