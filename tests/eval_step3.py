# -*- coding: utf-8 -*-
"""
STEP 3 답변 회귀 평가 — 사용자가 확정한 정답셋(data/eval/gold.json)으로 지금 시스템을 잰다.

질문은 정답셋 것으로 고정하고, 근거 검색·답변 규칙·후처리(2단계 근거·관련성·사실 대조)는 실제 STEP 3와
같은 경로(ExpectedQuestions.answer_questions)를 쓴다. 정답셋·결과에는 사내 원문이 있어 data/·test_reports/(gitignore)에만 쓴다.

지표 (문항별 → 데이터셋·전체 평균):
  근거 재현율   정답 근거를 인용했나 (evidence_match=any면 하나라도, all이면 비율)
  근거 정밀도   인용한 근거 중 정답 근거 비율 (정답 근거가 없는 문항은 제외)
  주장 충실도   답변을 주장 단위로 쪼개 인용 근거(또는 보고 내용)로 뒷받침되는 비율 — Ragas Faithfulness 방식
  요지 정답률   기대 답변 요지 중 답변에 담긴 비율
  확인 필요 처리 근거로 답할 수 없는 부분을 지어내지 않고 '확인 필요'로 남겼나
  질문 적합      답변이 질문과 같은 업무를 말하나 (덴텀 프린터가 주간보고 질문에 붙은 사례)
판정은 judge_model(Opus 5.5)로 JUDGE_RUNS회 → 점수는 평균, 예/아니오는 다수결, 회차 간 차이는 '흔들림'으로 기록.

사용법:
  python tests/eval_step3.py --label baseline
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from weekly_report import paths  # noqa: E402

EVAL_DIR = os.path.join(paths.DATA_DIR, "eval")
JUDGE_RUNS = 3

JUDGE_PROMPT = (
    "너는 주간보고 AI의 '예상 질문 답변'을 채점하는 검수자야. 아래 자료로 답변 하나를 채점해.\n"
    "1) claims: 답변을 사실 주장 단위로 쪼갠다 ('~는 확인 필요' 같은 미확인 표시는 주장이 아니므로 뺀다). "
    "주장마다 <근거> 또는 <보고 내용>에 실제로 적혀 있으면 supported=true, 없거나 다르면 false.\n"
    "2) expected: <기대 요지> 각 항목이 답변에 (다른 말로라도) 담겼으면 covered=true.\n"
    "3) unanswerable_ok: <답할 수 없는 부분>이 있으면 답변이 그 부분을 지어내지 않고 '확인 필요' 등으로 남겼는지 true/false, "
    "그 항목이 비어 있으면 null.\n"
    "4) on_topic: 답변이 질문이 묻는 업무(시스템·건)와 같은 업무를 말하면 true, 다른 업무 내용을 가져왔으면 false.\n"
    "출력은 JSON 하나만 (문자열 안 큰따옴표는 작은따옴표로): "
    "{\"claims\": [{\"claim\": \"...\", \"supported\": true, \"why\": \"...\"}], "
    "\"expected\": [{\"point\": \"...\", \"covered\": true}], \"unanswerable_ok\": null, \"on_topic\": true, "
    "\"note\": \"한 줄 총평\"}"
)


# ---------------------------------------------------------------- 데이터셋 준비

def confluence_setup(eq, ds):
    """택배처럼 Confluence 스냅샷으로 만든 데이터셋 — 근거는 스냅샷 조각만, 검색은 메모리에서 (DB·VectorDB에 안 씀)"""
    from weekly_report.ai import questions as Q
    from weekly_report.ai.rag import MIN_SCORE, _cosine
    from weekly_report.ai.llm_summarizer import LLMSummarizer, check_summary
    from weekly_report.report.generator import ReportGenerator
    from weekly_report.storage.database import ActivityDatabase

    key = ActivityDatabase.activity_key
    activities, id_of = [], {}
    for i, c in enumerate(ds["corpus"]):
        a = {"timestamp": f"{c['when']}T10:00:{i % 60:02d}", "action": "confluence_modified",
             "file_path": f"택배/{c['source'].split(' · ', 1)[-1]}", "source": "confluence",
             "details": json.dumps({"title": c["source"].split(" · ", 1)[-1], "summary": c["text"]}, ensure_ascii=False)}
        activities.append(a)
        id_of[key(a)] = c["id"]
    cl = eq.rag.clusterer
    vectors = cl.embed([cl._activity_text(a) for a in activities])
    by_key = {key(a): v for a, v in zip(activities, vectors)}
    eq.rag.evidence_vectors = lambda evidence: {i: by_key.get(key(e["activity"])) for i, e in enumerate(evidence, start=1)}

    def search(query_vectors, k, min_score):
        out = []
        for qv in query_vectors:
            scored = sorted(((_cosine(qv, v), a) for a, v in zip(activities, vectors)), key=lambda x: -x[0])
            out.append([(s, a) for s, a in scored if s >= min_score][:k])
        return out

    eq.question_search = lambda qv, texts=None: search(qv, Q.QUESTION_EVIDENCE_K, Q.QUESTION_EVIDENCE_MIN)
    digest = "\n".join(f"■ {c['source']} ({c['when']})\n{c['text']}" for c in ds["corpus"])
    summary = LLMSummarizer().complete(ReportGenerator.WEEK_SUMMARY_PROMPT, digest, max_tokens=1500,
                                       max_input=20000, temperature=0, cache=True, validate=check_summary) or ""
    points = [l.strip().lstrip("-•* ").strip() for l in summary.splitlines() if l.strip().startswith(("-", "•", "*"))]
    point_vectors = cl.embed(points)
    week_hits = search(point_vectors, Q.WEEK_PER_POINT, MIN_SCORE)
    return points, point_vectors, week_hits, id_of


def week_setup(eq, ds):
    """이번 주 실데이터 — 실제 DB·VectorDB로 검색 (보고 항목은 정답셋 작성 때의 스냅샷)"""
    from weekly_report.ai import questions as Q
    from weekly_report.storage.database import ActivityDatabase

    key = ActivityDatabase.activity_key
    ws, we = ds["week_start"], ds["week_end"]
    acts = eq.gen.fetch_week_activities(ws, we)
    pool = {key(a): a for a in acts if eq.rag.eligible(a)}
    eq.rag.clusterer.embed_activities(acts)
    points = ds["points"]
    point_vectors = eq.rag.clusterer.embed(points)
    week_hits = eq.rag.retrieve(point_vectors, ws, we, pool, Q.WEEK_PER_POINT)
    eq.question_search = lambda qv, texts=None: eq.rag.retrieve(qv, ws, we, pool, Q.QUESTION_EVIDENCE_K,
                                                           min_score=Q.QUESTION_EVIDENCE_MIN)
    id_of = {c["activity_key"]: c["id"] for c in ds["corpus"] if c.get("activity_key")}
    return points, point_vectors, week_hits, id_of


# ---------------------------------------------------------------- 채점

def judge_once(llm, item, answer, cited_texts, points):
    body = (f"<질문>\n{item['question']}\n</질문>\n<답변>\n{answer}\n</답변>\n<근거>\n"
            + ("\n".join(f"- {t}" for t in cited_texts) or "(인용 없음)") + "\n</근거>\n<보고 내용>\n"
            + "\n".join(f"- {p}" for p in points) + "\n</보고 내용>\n<기대 요지>\n"
            + "\n".join(f"- {p}" for p in item["expected_points"]) + "\n</기대 요지>\n<답할 수 없는 부분>\n"
            + (item.get("unanswerable") or "") + "\n</답할 수 없는 부분>")

    def parse(out):
        m = re.search(r"\{.*\}", out or "", re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            return None
    out = llm.complete(JUDGE_PROMPT, body, max_tokens=2000, max_input=30000, temperature=0,
                       validate=lambda o: o if parse(o) is not None else None)
    return parse(out)


def score(verdicts, item):
    def avg(values):
        values = [v for v in values if v is not None]
        return sum(values) / len(values) if values else None

    def majority(values):
        values = [v for v in values if v is not None]
        return (sum(values) > len(values) / 2) if values else None
    faith = [avg([c.get("supported") is True for c in v.get("claims", [])]) if v.get("claims") else None for v in verdicts]
    correct = [avg([e.get("covered") is True for e in v.get("expected", [])]) if v.get("expected") else None
               for v in verdicts]
    unans = [v.get("unanswerable_ok") for v in verdicts]
    topic = [v.get("on_topic") for v in verdicts]
    spread = lambda xs: (max(xs) - min(xs)) if len([x for x in xs if x is not None]) > 1 else 0.0
    return {
        "faithfulness": avg(faith), "correctness": avg(correct),
        "unanswerable_ok": majority(unans) if item.get("unanswerable") else None,
        "on_topic": majority(topic),
        "unstable": max(spread([x for x in faith if x is not None] or [0]),
                        spread([x for x in correct if x is not None] or [0])) >= 0.25
                    or len({t for t in topic if t is not None}) > 1,
        "notes": [v.get("note", "") for v in verdicts],
        "claims": verdicts[0].get("claims", []) if verdicts else [],
    }


def evidence_scores(item, cited_ids):
    gold = set(item["gold_evidence"])
    if not gold:
        return {"recall": None, "precision": None}
    hit = gold & set(cited_ids)
    recall = (1.0 if hit else 0.0) if item.get("evidence_match") == "any" else len(hit) / len(gold)
    precision = len([c for c in cited_ids if c in gold]) / len(cited_ids) if cited_ids else 0.0
    return {"recall": recall, "precision": precision}


# ---------------------------------------------------------------- 실행

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="", help="이번 측정 이름 (예: baseline, gate-0.20)")
    parser.add_argument("--gold", default=os.path.join(EVAL_DIR, "gold.json"))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    from weekly_report.ai.llm_summarizer import LLMSummarizer
    from weekly_report.ai.questions import ExpectedQuestions
    from weekly_report.ai.rag import TopicQueryRAG
    from weekly_report.report.generator import ReportGenerator
    from weekly_report.storage.database import ActivityDatabase

    gold = json.load(open(args.gold, encoding="utf-8"))
    judge = LLMSummarizer(judge=True)
    key = ActivityDatabase.activity_key
    started = time.time()
    rows = []
    for ds in gold["datasets"]:
        items = [i for i in ds["items"] if i.get("status") == "confirmed"]
        if not items:
            continue
        eq = ExpectedQuestions(ReportGenerator())
        setup = confluence_setup if ds["kind"] == "confluence" else week_setup
        points, point_vectors, week_hits, id_of = setup(eq, ds)
        answers = eq.answer_questions([i["question"] for i in items], points, point_vectors, week_hits)
        corpus_text = {c["id"]: c["text"] for c in ds["corpus"]}

        def evaluate(pair):
            item, ans = pair
            cited = [id_of.get(key(a), "기타") for a in ans["evidence"]]
            texts = [corpus_text.get(id_of.get(key(a)), "") or TopicQueryRAG.evidence_texts([{"activity": a}])[1]
                     for a in ans["evidence"]]
            verdicts = [v for v in (judge_once(judge, item, ans["a"], [t[:3000] for t in texts], points)
                                    for _ in range(JUDGE_RUNS)) if v]
            return {"dataset": ds["name"], "id": item["id"], "question": item["question"], "answer": ans["a"],
                    "cited": cited, "gold": item["gold_evidence"], **evidence_scores(item, cited),
                    **score(verdicts, item), "judged": len(verdicts)}
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows += list(pool.map(evaluate, zip(items, answers)))
    elapsed = time.time() - started

    def mean(name, subset):
        values = [r[name] for r in subset if r[name] is not None]
        if not values:
            return None
        return sum(float(v) for v in values) / len(values)

    metrics = [("근거 재현율", "recall"), ("근거 정밀도", "precision"), ("주장 충실도", "faithfulness"),
               ("요지 정답률", "correctness"), ("확인 필요 처리", "unanswerable_ok"), ("질문 적합", "on_topic")]
    groups = [(name, [r for r in rows if r["dataset"] == name]) for name in dict.fromkeys(r["dataset"] for r in rows)]
    groups.append(("전체", rows))
    summary = {g: {m: mean(m, subset) for _, m in metrics} for g, subset in groups}
    fmt = lambda v: "-" if v is None else f"{v:.2f}"

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out = [f"# STEP 3 회귀 평가 — {args.label or stamp}", "",
           f"- 측정 {datetime.now():%Y-%m-%d %H:%M} · 문항 {len(rows)}개 · 판정 {JUDGE_RUNS}회 다수결(Opus) · 소요 {elapsed:.0f}초",
           f"- 판정이 흔들린 문항: {sum(r['unstable'] for r in rows)}개", "",
           "| 데이터셋 | " + " | ".join(n for n, _ in metrics) + " |", "|---" * (len(metrics) + 1) + "|"]
    out += [f"| {g} | " + " | ".join(fmt(summary[g][m]) for _, m in metrics) + " |" for g, _ in groups]
    out += ["", "## 문항별", ""]
    for r in rows:
        out += [f"### {r['id']}. {r['question']}", "", f"- 답변: {r['answer']}",
                f"- 인용: {', '.join(r['cited']) or '없음'} / 정답 근거: {', '.join(r['gold']) or '없음'}",
                "- " + " · ".join(f"{n} {fmt(r[m])}" for n, m in metrics) + (" · ⚠ 판정 흔들림" if r["unstable"] else ""),
                "- 뒷받침 안 된 주장: " + ("; ".join(c.get("claim", "") + f" ({c.get('why', '')})"
                                              for c in r["claims"] if c.get("supported") is not True) or "없음"),
                f"- 총평: {r['notes'][0] if r['notes'] else ''}", ""]
    os.makedirs(paths.TEST_REPORTS_DIR, exist_ok=True)
    report_path = os.path.join(paths.TEST_REPORTS_DIR, f"eval_step3_{stamp}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    with open(os.path.join(EVAL_DIR, "history.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "label": args.label,
                            "summary": summary, "rows": rows}, ensure_ascii=False) + "\n")
    print("\n".join(out[:8 + len(groups)]))
    print(f"\n상세: {report_path}")


if __name__ == "__main__":
    main()
