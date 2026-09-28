#!/usr/bin/env python3
"""
임베딩 기반 활동 의미 클러스터링.
사내 LiteLLM 프록시의 임베딩 엔드포인트(text-embedding-3-large)로 각 활동을
벡터화하고, 코사인 유사도로 같은 주제의 활동을 묶는다. LLM으로 클러스터별
주제명을 붙여 "주제별 작업" 보고서 섹션을 생성.

외부 VectorDB 없이 인메모리 코사인 유사도로 시작 (주간 활동 수백 건 규모에 충분).
추후 활동 누적 시 FAISS/Qdrant로 교체 가능한 구조.
"""

import json
import math
import os

import requests

from llm_summarizer import LLMSummarizer

EMBEDDING_MODEL = "azure/text-embedding-3-large"
# 코사인 유사도가 이 값 이상이면 같은 주제로 묶는다 (0~1, 높을수록 엄격)
SIMILARITY_THRESHOLD = 0.62
# 클러스터당 LLM 명명용 대표 아이템 수, 보고서에 표시할 최대 주제 수
MAX_CLUSTER_ITEMS_FOR_NAMING = 8
MAX_TOPICS_IN_REPORT = 10


class ActivityClusterer:
    """LiteLLM 프록시 임베딩으로 활동을 의미 단위 클러스터로 묶는 분석기"""

    def __init__(self, config_path="config/litellm_config.json"):
        self.config = self._load_config(config_path)
        self.summarizer = LLMSummarizer(config_path)

    @property
    def enabled(self):
        return bool(self.config.get("enabled")) and bool(self.config.get("api_key"))

    def _load_config(self, config_path):
        if not os.path.exists(config_path):
            return {"enabled": False}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {"enabled": False}

    # ---------- 임베딩 ----------

    def _embed(self, texts, batch_size=50):
        """텍스트 목록을 임베딩 벡터로 변환. 실패 시 None."""
        if not texts:
            return []
        base_url = str(self.config.get("base_url") or "").rstrip("/")
        api_key = str(self.config.get("api_key") or "")
        vectors = []
        try:
            for i in range(0, len(texts), batch_size):
                batch = [t[:800] for t in texts[i:i + batch_size]]
                response = requests.post(
                    f"{base_url}/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": EMBEDDING_MODEL, "input": batch},
                    timeout=60,
                )
                response.raise_for_status()
                vectors.extend(
                    item["embedding"] for item in response.json()["data"]
                )
            return vectors
        except (requests.exceptions.RequestException, KeyError, ValueError) as e:
            print(f"Warning: embedding failed, clustering skipped: {e}")
            return None

    @staticmethod
    def _cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if not na or not nb:
            return 0.0
        return dot / (na * nb)

    # ---------- 활동 → 텍스트 ----------

    def _activity_text(self, activity):
        """활동 하나를 임베딩용 짧은 텍스트로 변환 (경로 + 상세 본문)."""
        parts = [str(activity.get("file_path") or "")]
        details = activity.get("details")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (json.JSONDecodeError, TypeError):
                details = None
        if isinstance(details, dict):
            for key in ("text", "summary", "subject", "chat"):
                if details.get(key):
                    parts.append(str(details[key]))
        return " ".join(parts).strip()[:400]

    # ---------- 클러스터링 ----------

    def cluster_activities(self, activities, threshold=SIMILARITY_THRESHOLD):
        """활동 목록을 의미 유사도로 클러스터링.
        반환: [{"items": [activity...], "centroid": vec}, ...] 건수 내림차순.
        임베딩 실패/소량 데이터면 빈 리스트."""
        if not self.enabled or len(activities) < 3:
            return []
        texts = [self._activity_text(a) for a in activities]
        keep = [i for i, t in enumerate(texts) if t]
        vectors = self._embed([texts[i] for i in keep])
        if not vectors:
            return []

        clusters = []
        for idx, vec in zip(keep, vectors):
            best, best_sim = None, -1.0
            for cluster in clusters:
                sim = self._cosine(vec, cluster["centroid"])
                if sim > best_sim:
                    best, best_sim = cluster, sim
            if best is not None and best_sim >= threshold:
                best["items"].append(activities[idx])
                # 센트로이드 이동평균
                n = len(best["items"])
                best["centroid"] = [
                    (c * (n - 1) + v) / n for c, v in zip(best["centroid"], vec)
                ]
            else:
                clusters.append({"items": [activities[idx]], "centroid": vec})

        clusters.sort(key=lambda c: -len(c["items"]))
        return clusters

    def name_cluster(self, items):
        """클러스터의 대표 활동들로 주제명 생성. 실패 시 대표 경로 사용."""
        texts = [self._activity_text(a) for a in items[:MAX_CLUSTER_ITEMS_FOR_NAMING]]
        joined = "\n".join(f"- {t}" for t in texts if t)
        name = self.summarizer.complete(
            "다음은 한 주간의 업무 활동 목록이야. 이 활동들을 하나로 묶는 "
            "주제명을 20자 이내 한국어 명사구로 붙여줘. 주제명만 출력하고 "
            "설명·따옴표·불릿은 붙이지 마.",
            joined,
            max_tokens=40,
            temperature=0.2,
        )
        if name:
            return name.strip()
        # 폴백: 가장 긴 대표 경로의 파일/주제명 부분
        fallback = (items[0].get("file_path") or "기타").split(":")[-1].strip()
        return fallback[:30] or "기타"

    def build_topics(self, activities, min_cluster_size=2):
        """보고서용 주제 목록 생성.
        반환: [{"name", "count", "examples": [str...]}] 건수 내림차순."""
        clusters = self.cluster_activities(activities)
        topics = []
        for cluster in clusters[:MAX_TOPICS_IN_REPORT]:
            items = cluster["items"]
            if len(items) < min_cluster_size:
                continue
            name = self.name_cluster(items)
            examples = []
            seen = set()
            for item in items:
                label = str(item.get("file_path") or "").strip()
                if label and label not in seen:
                    seen.add(label)
                    examples.append(label[:60])
                if len(examples) >= 3:
                    break
            topics.append(
                {"name": name, "count": len(items), "examples": examples}
            )
        return topics
