#!/usr/bin/env python3
"""
임베딩 기반 활동 의미 클러스터링.
사내 LiteLLM 프록시의 임베딩 엔드포인트(text-embedding-3-large)로 각 활동을
벡터화하고, 코사인 유사도로 같은 주제의 활동을 묶는다. LLM으로 클러스터별
주제명을 붙여 "주제별 작업" 보고서 섹션을 생성.

임베딩은 VectorDB(Qdrant 로컬, vector_store.py)에 누적 저장해 재사용하고,
같은 벡터를 RAG·STEP 3 의미 검색에도 쓴다. 주간 클러스터링 자체는 수백 건 규모라
인메모리 코사인 유사도로 계산한다.
"""

import json
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from weekly_report import paths
from weekly_report.storage.database import ActivityDatabase
from weekly_report.ai.llm_summarizer import LLMSummarizer, PROMPT_TEMPLATES
from weekly_report.storage.vector_store import ActivityVectorStore

DB_PATH = paths.DB_PATH
_migrated = False
_VECTOR_MEMO = {}  # activity_key → (임베딩 텍스트, 벡터) — 프로세스 안에서 VectorDB 재조회 방지
_MEMO_LOCK = threading.Lock()

EMBEDDING_MODEL = "azure/text-embedding-3-large"
# 코사인 유사도가 이 값 이상이면 같은 주제로 묶는다 (0~1, 높을수록 엄격)
SIMILARITY_THRESHOLD = 0.62
# 클러스터당 LLM 명명용 대표 아이템 수, 보고서에 표시할 최대 주제 수
MAX_CLUSTER_ITEMS_FOR_NAMING = 8
MAX_TOPICS_IN_REPORT = 10


class ActivityClusterer:
    """LiteLLM 프록시 임베딩으로 활동을 의미 단위 클러스터로 묶는 분석기"""

    def __init__(self, config_path=paths.LITELLM_CONFIG):
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

    def embed(self, texts, batch_size=50):
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

    def _embed_with_cache(self, activities, texts):
        """활동별 임베딩을 VectorDB에서 조회.
        저장된 벡터는 재사용하고 없는 것만 API 호출 → 주차를 거듭할수록
        누적돼 과거 활동과의 유사 검색(RAG) 기반이 된다."""
        global _migrated
        store = ActivityVectorStore()
        keys = [ActivityDatabase.activity_key(a) for a in activities]
        # 한 번 읽은 벡터는 프로세스 메모리에 보관 — 저장소 열기(수 초)를 클러스터링·RAG·STEP 3이
        # 반복하지 않도록, GUI에서는 두 번째 보고서 생성부터 저장소를 거의 열지 않음
        with _MEMO_LOCK:
            cached = {k: _VECTOR_MEMO[k] for k in keys if k in _VECTOR_MEMO}
        unknown = [k for i, k in enumerate(keys) if cached.get(k, ("",))[0] != texts[i]]
        try:
            if not _migrated:
                moved = store.migrate_from_sqlite(DB_PATH)
                if moved:
                    print(f"VectorDB: SQLite 임베딩 {moved}건 이전 완료")
                _migrated = True
            if unknown:
                fetched = store.get_vectors(unknown)
                cached.update(fetched)
                with _MEMO_LOCK:
                    _VECTOR_MEMO.update(fetched)
        except Exception as e:
            print(f"Warning: VectorDB read failed: {e}")

        vectors = [None] * len(activities)
        missing = []
        for i, key in enumerate(keys):
            entry = cached.get(key)
            if entry and entry[0] == texts[i]:
                vectors[i] = entry[1]
            elif texts[i]:
                missing.append(i)

        if missing:
            new_vecs = self.embed([texts[i] for i in missing])
            if not new_vecs:
                return None
            to_save = []
            for i, vec in zip(missing, new_vecs):
                vectors[i] = vec
                to_save.append((activities[i], texts[i], vec))
            with _MEMO_LOCK:
                _VECTOR_MEMO.update({keys[i]: (texts[i], vectors[i]) for i in missing})
            try:
                store.upsert(to_save)
            except Exception as e:
                print(f"Warning: VectorDB write failed: {e}")
        return vectors

    def embed_activities(self, activities):
        """활동들이 VectorDB에 들어 있도록 보장 (없는 것만 임베딩·저장). 실패 시 None."""
        return self._embed_with_cache(activities, [self._activity_text(a) for a in activities])

    def cluster_activities(self, activities, threshold=SIMILARITY_THRESHOLD):
        """활동 목록을 의미 유사도로 클러스터링.
        반환: [{"items": [activity...], "centroid": vec}, ...] 건수 내림차순.
        임베딩 실패/소량 데이터면 빈 리스트."""
        if not self.enabled or len(activities) < 3:
            return []
        texts = [self._activity_text(a) for a in activities]
        keep = [i for i, t in enumerate(texts) if t]
        all_vectors = self._embed_with_cache(activities, texts)
        if not all_vectors:
            return []
        X = np.asarray([all_vectors[i] for i in keep], dtype=np.float64)

        # 그리디 클러스터링: 가장 가까운 센트로이드와 코사인 유사도가 기준 이상이면 합류(센트로이드
        # 이동평균), 아니면 새 클러스터. 수백 건 × 3072차원이라 행렬 연산(numpy)으로 계산
        centroids = np.empty_like(X)
        centroid_norms = np.empty(len(X))
        members = []
        norms = np.linalg.norm(X, axis=1)
        for row, idx in enumerate(keep):
            vec, norm = X[row], norms[row]
            k = len(members)
            if k:
                denom = centroid_norms[:k] * norm
                sims = np.divide(centroids[:k] @ vec, denom, out=np.zeros(k), where=denom > 0)
                best = int(np.argmax(sims))
            if k and sims[best] >= threshold:
                members[best].append(activities[idx])
                n = len(members[best])
                centroids[best] = (centroids[best] * (n - 1) + vec) / n
                centroid_norms[best] = np.linalg.norm(centroids[best])
            else:
                centroids[k], centroid_norms[k] = vec, norm
                members.append([activities[idx]])

        clusters = [{"items": items, "centroid": centroids[i].tolist()} for i, items in enumerate(members)]
        clusters.sort(key=lambda c: -len(c["items"]))
        return clusters

    def name_cluster(self, items):
        """클러스터의 대표 활동들로 주제명 생성. 실패 시 대표 경로 사용."""
        texts = [self._activity_text(a) for a in items[:MAX_CLUSTER_ITEMS_FOR_NAMING]]
        joined = "\n".join(f"- {t}" for t in texts if t)
        name = self.summarizer.complete(
            PROMPT_TEMPLATES["topic"],
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
        clusters = [c for c in self.cluster_activities(activities)[:MAX_TOPICS_IN_REPORT]
                    if len(c["items"]) >= min_cluster_size]
        if not clusters:
            return []
        # 클러스터 이름 짓기(LLM 대기)는 동시에
        with ThreadPoolExecutor(max_workers=min(8, len(clusters))) as pool:
            names = list(pool.map(lambda c: self.name_cluster(c["items"]), clusters))
        topics = []
        for cluster, name in zip(clusters, names):
            items = cluster["items"]
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
