#!/usr/bin/env python3
"""
STEP 3 회귀 평가용 정답셋 초안 생성 (사람이 검토해 확정하는 '초안').

- 택배 PJT: Confluence 페이지 본문을 약 500자 조각으로 나눠 스냅샷(T01…) — 페이지가 바뀌어도 평가가 흔들리지 않게
- 이번 주 실데이터: STEP 2 보고 항목별 후보 근거를 모아 스냅샷(W01…, activity_key 보존)
- 판정 모델(judge_model)이 질문·정답 근거 ID·기대 답변 요지·근거로 답할 수 없는 부분·애매한 점을 작성
- 결과: data/eval/gold_draft.json (평가 스크립트 입력) + gold_draft_review.md (사람 검토용)
  data/는 .gitignore — 사내 메시지·문서 원문이 GitHub에 올라가지 않음

사용법:
  python scripts/build_gold_draft.py --pages 545446581,517147492,540358744,512021544,512009526
"""

import argparse
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from weekly_report import paths  # noqa: E402

EVAL_DIR = os.path.join(paths.DATA_DIR, "eval")
CHUNK_CHARS = 500
PER_POINT_CANDIDATES = 8

GOLD_PROMPT = (
    "너는 주간보고 AI의 '예상 질문 답변' 기능을 평가할 정답셋을 만드는 검토자야. "
    "<report>는 이번 주 보고 항목, <corpus>는 근거 조각(ID 붙음)이야.\n"
    "상사(팀장)가 보고를 듣고 물어볼 법한 질문 {count}개를 만들고, 질문마다 정답을 정리해.\n"
    "규칙:\n"
    "- 질문은 서로 다른 업무·세부를 다룬다. 보고 항목의 세부 사실(수치·코드·대상·일정·상태)을 묻는 질문을 절반 이상 넣는다.\n"
    "{extra}"
    "- gold_evidence: 그 질문에 답하려면 반드시 필요한 근거 ID 1~3개 (corpus에 실제로 있는 ID만). 근거가 없으면 [].\n"
    "- expected_points: 정답에 들어가야 할 핵심 사실 2~4개. corpus에 실제로 적힌 사실만, 짧은 한국어 문장으로.\n"
    "- unanswerable: 질문이 묻는 것 중 corpus로 답할 수 없는 부분 (없으면 \"\"). 답변이 '확인 필요'라고 해야 하는 부분.\n"
    "- ambiguity: 정답 판단이 애매한 점 (용어 해석이 갈리는 등, 없으면 \"\").\n"
    "- 문자열 안에서는 큰따옴표 대신 작은따옴표(')를 쓴다 (JSON 형식이 깨지지 않게).\n"
    "출력은 JSON 배열만: [{{\"question\": ..., \"gold_evidence\": [...], \"expected_points\": [...], "
    "\"unanswerable\": ..., \"ambiguity\": ...}}]"
)


def fetch_confluence_chunks(page_ids):
    import requests
    from weekly_report.collectors.confluence import ConfluenceCollector

    cc = ConfluenceCollector()
    headers = {"Authorization": f"Bearer {cc.personal_access_token}", "Accept": "application/json"}
    corpus, pages = [], []
    for pid in page_ids:
        r = requests.get(f"{cc.base_url}/rest/api/content/{pid}", headers=headers, timeout=20,
                         params={"expand": "body.view,version"})
        r.raise_for_status()
        d = r.json()
        body = re.sub(r"(?i)<(br|/p|/li|/tr|/h[1-6]|/div)[^>]*>", "\n", d["body"]["view"]["value"])
        body = re.sub(r"(?i)</t[dh]>", " | ", body)
        lines = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", l))).strip(" |")
                 for l in body.splitlines()]
        lines = [l for l in lines if l]
        pages.append({"id": pid, "title": d["title"], "version": d["version"]["number"],
                      "when": d["version"]["when"][:10]})
        buf = []
        for line in lines + [None]:
            if buf and (line is None or sum(map(len, buf)) + len(line) > CHUNK_CHARS):
                corpus.append({"id": f"T{len(corpus) + 1:02d}", "source": f"Confluence · {d['title']}",
                               "when": d["version"]["when"][:10], "text": "\n".join(buf)})
                buf = []
            if line is not None:
                buf.append(line)
    return pages, corpus


def week_corpus():
    """이번 주 STEP 2 보고 항목 + 항목별 후보 근거 스냅샷"""
    from weekly_report.ai.questions import ExpectedQuestions
    from weekly_report.ai.rag import TopicQueryRAG, evidence_label
    from weekly_report.common.timeutil import to_local_datetime
    from weekly_report.report.generator import ReportGenerator
    from weekly_report.storage.database import ActivityDatabase

    gen = ReportGenerator()
    ws, we = gen._resolve_week_range(None, None)
    acts = gen.fetch_week_activities(ws, we)
    points = gen._summarize_week(gen.build_program_sections(acts)) or []
    rag = ExpectedQuestions(gen).rag
    key = ActivityDatabase.activity_key
    pool = {key(a): a for a in acts if rag.eligible(a)}
    vectors = rag.clusterer.embed(points) or []
    corpus, seen = [], set()
    for hits in rag.retrieve(vectors, ws, we, pool, PER_POINT_CANDIDATES):
        for _, a in hits:
            k = key(a)
            if k in seen:
                continue
            seen.add(k)
            when = to_local_datetime(a.get("timestamp"), a.get("source"))
            corpus.append({"id": f"W{len(corpus) + 1:02d}", "activity_key": k,
                           "source": evidence_label(a, when).split(" — ")[0],
                           "when": f"{when:%Y-%m-%d}" if when else "",
                           "text": TopicQueryRAG.evidence_texts([{"activity": a}])[1][:1500]})
    return {"week_start": ws, "week_end": we}, points, corpus


def draft_items(points, corpus, count, extra):
    from weekly_report.ai.llm_summarizer import LLMSummarizer

    body = ("<report>\n" + "\n".join(f"- {p}" for p in points) + "\n</report>\n<corpus>\n"
            + "\n".join(f"[{c['id']}] {c['source']} ({c['when']}) | {c['text']}" for c in corpus)
            + "\n</corpus>")
    def parse(output):
        match = re.search(r"\[.*\]", output or "", re.S)
        try:
            return json.loads(match.group(0)) if match else None
        except json.JSONDecodeError:
            return None
    # 형식이 깨진 JSON이면 1회 재요청 (validate가 None을 돌려주면 complete가 다시 묻는다)
    output = LLMSummarizer(judge=True).complete(GOLD_PROMPT.format(count=count, extra=extra), body,
                                                max_tokens=4000, max_input=60000, temperature=0,
                                                validate=lambda out: out if parse(out) is not None else None)
    items = parse(output) or []
    if not items:
        print("Warning: 정답셋 초안 생성 실패 (JSON 형식 오류)")
    ids = {c["id"] for c in corpus}
    for item in items:  # 없는 ID는 지우고 표시
        bad = [e for e in item.get("gold_evidence", []) if e not in ids]
        item["gold_evidence"] = [e for e in item.get("gold_evidence", []) if e in ids]
        if bad:
            item["ambiguity"] = (item.get("ambiguity") or "") + f" (존재하지 않는 근거 ID 제거: {bad})"
    return items


def review_markdown(gold):
    out = ["# STEP 3 정답셋 초안 — 검토용", "",
           "질문마다 **정답 근거**와 **기대 답변 요지**가 맞는지 표시해 주세요. 틀리면 고칠 내용을 메모에 적으면 됩니다.",
           "(근거 원문은 맨 아래 '근거 조각'에 있음)", ""]
    for ds in gold["datasets"]:
        corpus = {c["id"]: c for c in ds["corpus"]}
        out += [f"## {ds['name']}", ""]
        if ds.get("points"):
            out += ["**보고 항목(STEP 2)**", ""] + [f"- {p}" for p in ds["points"]] + [""]
        for item in ds["items"]:
            out += [f"### {item['id']}. {item['question']}", "",
                    "- 정답 근거: " + (", ".join(f"{e} ({corpus[e]['source']})" for e in item["gold_evidence"])
                                    or "없음 — 보고 내용으로만 답해야 함"),
                    "- 기대 답변 요지:"] + [f"  - {p}" for p in item["expected_points"]]
            if item.get("unanswerable"):
                out += [f"- 근거로 답할 수 없는 부분('확인 필요'): {item['unanswerable']}"]
            if item.get("ambiguity"):
                out += [f"- ⚠ 애매한 점: {item['ambiguity']}"]
            out += ["- 검토: 근거 [ O / X ]  요지 [ O / X ]  메모: ", ""]
        out += ["<details><summary>근거 조각</summary>", ""]
        for c in ds["corpus"]:
            out += [f"**{c['id']}** {c['source']} ({c['when']})", "```", c["text"], "```", ""]
        out += ["</details>", ""]
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", default="", help="택배 PJT 등 Confluence pageId (쉼표 구분)")
    parser.add_argument("--count", type=int, default=7, help="데이터셋별 질문 수")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(EVAL_DIR, exist_ok=True)

    datasets = []
    if args.pages:
        pages, corpus = fetch_confluence_chunks([p.strip() for p in args.pages.split(",") if p.strip()])
        items = draft_items([], corpus, args.count,
                            "- 문서 하나에만 있는 세부(권역 프리픽스·TID·트란 코드 등)를 묻는 질문을 포함한다.\n"
                            "- 1개는 corpus에 답이 없는 것(예: 테스트 일정)을 묻는 질문으로 만든다.\n")
        datasets.append({"name": "택배 PJT (Confluence)", "kind": "confluence", "pages": pages,
                         "points": [], "corpus": corpus, "items": items})
    week, points, corpus = week_corpus()
    items = draft_items(points, corpus, args.count,
                        "- 근거가 없는 보고 항목(예: 주간보고 자동작성 프로그램 개발)을 묻는 질문을 1개 넣고 gold_evidence는 []로 한다 "
                        "— 단어가 비슷한 다른 업무 기록을 근거로 고르지 않는다.\n")
    datasets.append({"name": f"이번 주 실데이터 ({week['week_start']} ~ {week['week_end']})", "kind": "week",
                     **week, "points": points, "corpus": corpus, "items": items})

    n = 0
    for ds in datasets:
        for item in ds["items"]:
            n += 1
            item["id"] = f"G{n:02d}"
            item["reviewed"] = False
    gold = {"version": 1, "status": "draft", "datasets": datasets}
    with open(os.path.join(EVAL_DIR, "gold_draft.json"), "w", encoding="utf-8") as f:
        json.dump(gold, f, ensure_ascii=False, indent=1)
    with open(os.path.join(EVAL_DIR, "gold_draft_review.md"), "w", encoding="utf-8") as f:
        f.write(review_markdown(gold))
    print(f"정답셋 초안 {n}문항 → {EVAL_DIR}")


if __name__ == "__main__":
    main()
